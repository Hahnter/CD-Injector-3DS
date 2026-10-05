"""Just enough CGFX / CBMD handling to re-texture a 3DS banner model.

CGFX pointers are self-relative. PICA200 raw textures are stored as 8x8 blocks
in row order with Z-order (Morton) pixels inside each block, top row first.
"""

import struct

PICA_RGBA8 = 0
PICA_RGB565 = 3
PICA_LA8 = 5
PICA_L8 = 7
PICA_ETC1 = 12
PICA_ETC1A4 = 13
GL_UNSIGNED_BYTE = 0x1401


class CGFXError(ValueError):
    """The data isn't a well-formed CGFX model or banner. Every reader in this module raises this (and only this)
    for bad input, so callers can treat a damaged or hostile file as one ordinary error."""


# The Home Menu itself limits a banner model to 512 KB; these limits are generous but stop a hostile file from
# asking for gigabytes of memory or billions of loop passes.
MAX_MODEL = 2 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_TEXTURE_SIDE = 1024


def u32(d, o):
    if o < 0:
        raise CGFXError("the file is damaged (bad offset)")
    try:
        return struct.unpack_from("<I", d, o)[0]
    except struct.error:
        raise CGFXError("the file is truncated or damaged")


def u16(d, o):
    try:
        return struct.unpack_from("<H", d, o)[0]
    except struct.error:
        raise CGFXError("the file is truncated or damaged")


def rel(d, o):
    return o + u32(d, o)


def _cstr(d, o):
    if not 0 <= o < len(d):
        raise CGFXError("the file is damaged (bad name offset)")
    end = d.find(b"\0", o, o + 256)
    if end < 0:
        raise CGFXError("the file is damaged (a name is not terminated)")
    return bytes(d[o:end]).decode("latin1")


def _dict(d, off):
    if off < 0 or bytes(d[off:off + 4]) != b"DICT":
        raise CGFXError("the file is damaged (bad dictionary)")
    n = u32(d, off + 8)
    if n > MAX_ENTRIES:
        raise CGFXError("the file is damaged (too many entries)")
    return [(_cstr(d, rel(d, off + 0x1C + i * 0x10 + 8)), rel(d, off + 0x1C + i * 0x10 + 0xC)) for i in range(n)]


def textures(d):
    """{name: {w, h, length, data (offset), fmt}} for every image texture in a CGFX."""
    data = u16(d, 6)
    if bytes(d[:4]) != b"CGFX" or bytes(d[data:data + 4]) != b"DATA":
        raise CGFXError("not a CGFX file")
    if u32(d, data + 0x10) == 0:
        return {}
    out = {}
    for name, t in _dict(d, rel(d, data + 0x14)):
        if bytes(d[t + 4:t + 8]) != b"TXOB":
            continue
        img = rel(d, t + 0x38)
        h, w = u32(d, img), u32(d, img + 4)
        if not (8 <= w <= MAX_TEXTURE_SIDE and 8 <= h <= MAX_TEXTURE_SIDE and w % 8 == 0 and h % 8 == 0):
            raise CGFXError(f"texture {name} has an unusable size ({w} x {h})")
        out[name] = dict(name=name, h=h, w=w, length=u32(d, img + 8), data=rel(d, img + 0xC), fmt=u32(d, t + 0x34),
                         levels=max(1, u32(d, t + 0x28)), txob=t)
    return out


def _coords(w, h):
    coords = []
    for by in range(0, h, 8):
        for bx in range(0, w, 8):
            for i in range(64):
                coords.append((bx + ((i & 1) | ((i >> 1) & 2) | ((i >> 2) & 4)),
                               by + (((i >> 1) & 1) | ((i >> 2) & 2) | ((i >> 3) & 4))))
    return coords


def _check_texture(d, t, bytes_per_pixel):
    w, h, p = t["w"], t["h"], t["data"]
    if not (8 <= w <= MAX_TEXTURE_SIDE and 8 <= h <= MAX_TEXTURE_SIDE and w % 8 == 0 and h % 8 == 0):
        raise CGFXError(f"texture {t.get('name', '')} has an unusable size ({w} x {h})")
    if p < 0 or p + w * h * bytes_per_pixel > len(d):
        raise CGFXError(f"texture {t.get('name', '')} runs past the end of the file")


ETC1_TABLES = ((2, 8), (5, 17), (9, 29), (13, 42), (18, 60), (24, 80), (33, 106), (47, 183))


def _etc1_block(word):
    """{(x, y): (r, g, b)} for one 4x4 ETC1 block, given as a 64-bit number."""
    hi, lo = word >> 32, word & 0xFFFFFFFF
    flip, t1, t2 = hi & 1, (hi >> 5) & 7, (hi >> 2) & 7
    if (hi >> 1) & 1:                                   # differential mode: a 5-bit colour and a 3-bit offset
        def five(v):
            return (v << 3) | (v >> 2)
        base = [(hi >> 27) & 31, (hi >> 19) & 31, (hi >> 11) & 31]
        delta = [((hi >> s) & 7) - (8 if (hi >> s) & 4 else 0) for s in (24, 16, 8)]
        c1 = tuple(five(b) for b in base)
        c2 = tuple(five((b + e) & 31) for b, e in zip(base, delta))
    else:                                               # individual mode: two 4-bit colours
        c1 = tuple(((hi >> s) & 15) * 17 for s in (28, 20, 12))
        c2 = tuple(((hi >> s) & 15) * 17 for s in (24, 16, 8))
    out = {}
    for x in range(4):
        for y in range(4):
            i = x * 4 + y
            second = y >= 2 if flip else x >= 2
            small, large = ETC1_TABLES[t2 if second else t1]
            mod = (small, large, -small, -large)[((lo >> (16 + i)) & 1) * 2 + ((lo >> i) & 1)]
            out[x, y] = tuple(max(0, min(255, c + mod)) for c in (c2 if second else c1))
    return out


def _read_etc1(d, t, alpha):
    from PIL import Image
    w, h, p = t["w"], t["h"], t["data"]
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            for by, bx in ((0, 0), (0, 4), (4, 0), (4, 4)):
                a = struct.unpack_from("<Q", d, p)[0] if alpha else None
                p += 8 if alpha else 0
                for (x, y), c in _etc1_block(struct.unpack_from("<Q", d, p)[0]).items():
                    px[tx + bx + x, ty + by + y] = c + ((((a >> (4 * (x * 4 + y))) & 15) * 17,) if alpha else (255,))
                p += 8
    return img


def read_texture(d, t):
    """The texture's picture (its largest size, for one with mipmaps)."""
    from PIL import Image
    size = {PICA_RGBA8: 4, PICA_RGB565: 2, PICA_LA8: 2, PICA_L8: 1, PICA_ETC1: 0.5, PICA_ETC1A4: 1}.get(t["fmt"], 2)
    _check_texture(d, t, size)
    w, h, p = t["w"], t["h"], t["data"]
    if t["fmt"] == PICA_RGBA8:
        img = Image.new("RGBA", (w, h))
        px = img.load()
        for x, y in _coords(w, h):
            px[x, y] = (d[p + 3], d[p + 2], d[p + 1], d[p])
            p += 4
        return img
    if t["fmt"] in (PICA_ETC1, PICA_ETC1A4):
        return _read_etc1(d, t, t["fmt"] == PICA_ETC1A4)
    if t["fmt"] == PICA_RGB565:
        img = Image.new("RGB", (w, h))
        px = img.load()
        for x, y in _coords(w, h):
            v = struct.unpack_from("<H", d, p)[0]
            p += 2
            px[x, y] = ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)
        return img
    if t["fmt"] == PICA_LA8:
        img = Image.new("LA", (w, h))
        px = img.load()
        for x, y in _coords(w, h):
            px[x, y] = (d[p + 1], d[p])
            p += 2
        return img
    if t["fmt"] == PICA_L8:
        img = Image.new("L", (w, h))
        px = img.load()
        for x, y in _coords(w, h):
            px[x, y] = d[p]
            p += 1
        return img
    raise CGFXError(f"texture format {t['fmt']} not supported")


def rgba8_bytes(img):
    """An RGBA picture as PICA200 RGBA8 tiles (each texel stored as A, B, G, R)."""
    w, h = img.size
    px = img.convert("RGBA").load()
    out = bytearray(w * h * 4)
    p = 0
    for x, y in _coords(w, h):
        r, g, b, a = px[x, y]
        out[p:p + 4] = bytes((a, b, g, r))
        p += 4
    return bytes(out)


def mipmaps(img, levels):
    """`img` and each half-size version of it below, `levels` pictures in all."""
    from PIL import Image
    out = [img]
    for _ in range(levels - 1):
        img = img.resize((img.width // 2, img.height // 2), Image.BOX)
        out.append(img)
    return out


def write_rgba8(buf, t, img):
    """Write `img` into an RGBA8 texture of the same size, mipmaps included."""
    w, h = t["w"], t["h"]
    if t["fmt"] != PICA_RGBA8 or img.size != (w, h):
        raise CGFXError("texture format or size mismatch")
    data = b"".join(rgba8_bytes(level) for level in mipmaps(img.convert("RGBA"), t["levels"]))
    if len(data) != t["length"] or t["data"] < 0 or t["data"] + len(data) > len(buf):
        raise CGFXError(f"texture {t.get('name', '')} isn't laid out as expected")
    buf[t["data"]:t["data"] + len(data)] = data


def _texture_bytes(img, fmt):
    w, h = img.size
    out = bytearray(w * h * 2)
    p = 0
    if fmt == PICA_RGB565:
        px = img.convert("RGB").load()
        for x, y in _coords(w, h):
            r, g, b = px[x, y]
            struct.pack_into("<H", out, p, ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5
                             | ((b * 31 + 127) // 255))
            p += 2
    elif fmt == PICA_LA8:
        px = img.convert("LA").load()
        for x, y in _coords(w, h):
            out[p + 1], out[p] = px[x, y]
            p += 2
    else:
        raise CGFXError(f"texture format {fmt} not supported")
    return bytes(out)


def write_texture(buf, t, img):
    """Write `img` into an RGB565 or luminance + alpha texture of the same size, with its smaller mipmap levels too
    when the texture has them."""
    _check_texture(buf, t, 2)
    if img.size != (t["w"], t["h"]):
        raise CGFXError("texture size mismatch")
    levels = mipmaps(img, t["levels"]) if t["levels"] > 1 else [img]
    if sum(level.width * level.height * 2 for level in levels) > t["length"]:
        levels = [img]                                  # laid out differently: the full size is what shows anyway
    data = b"".join(_texture_bytes(level, t["fmt"]) for level in levels)
    buf[t["data"]:t["data"] + len(data)] = data


CBMD_HEADER = 0x88


def cbmd_common(data):
    """(start, end) of the main 3D model's compressed block in a 3DS banner (CBMD)."""
    words = struct.unpack_from("<%dI" % (CBMD_HEADER // 4), data, 0)
    start = words[2]
    later = sorted(w for w in words[3:] if w > start)
    return start, later[0] if later else len(data)


def cbmd_replace_common(data, model):
    """The banner `data` with its main 3D model replaced by `model` (an uncompressed CGFX). Only that block is
    rewritten: the language models and the sound keep their bytes and move along by whole 32-byte steps, so each
    stays as aligned as it was."""
    if bytes(data[:4]) != b"CBMD" or len(data) < CBMD_HEADER:
        raise CGFXError("not a 3DS banner")
    start, end = cbmd_common(data)
    comp = lz11_compress(bytes(model))
    comp += bytes((-(len(comp) - (end - start))) % 32)
    delta = len(comp) - (end - start)
    words = list(struct.unpack_from("<%dI" % (CBMD_HEADER // 4), data, 0))
    for i in range(3, CBMD_HEADER // 4):
        if words[i] and words[i] > start:
            words[i] += delta
    return struct.pack("<%dI" % (CBMD_HEADER // 4), *words) + bytes(data[CBMD_HEADER:start]) + comp + bytes(data[end:])


def lz11_decompress(src, max_size=MAX_MODEL):
    """Decompress LZ11 data. The stated size is checked against `max_size` before anything is allocated, so a tiny
    hostile file can't ask for a huge output."""
    if len(src) < 4 or src[0] != 0x11:
        raise CGFXError("not LZ11 data")
    size = u32(src, 0) >> 8
    p = 4
    if size == 0:
        size, p = u32(src, 4), 8
    if size > max_size:
        raise CGFXError(f"the compressed data claims to be {size} bytes, which is too large")
    out = bytearray()
    try:
        while len(out) < size:
            flags = src[p]
            p += 1
            for i in range(8):
                if len(out) >= size:
                    break
                if flags & (0x80 >> i):
                    b = src[p]
                    ind = b >> 4
                    if ind == 0:
                        ln = (((b & 0xF) << 4) | (src[p + 1] >> 4)) + 0x11
                        disp = (((src[p + 1] & 0xF) << 8) | src[p + 2]) + 1
                        p += 3
                    elif ind == 1:
                        ln = (((b & 0xF) << 12) | (src[p + 1] << 4) | (src[p + 2] >> 4)) + 0x111
                        disp = (((src[p + 2] & 0xF) << 8) | src[p + 3]) + 1
                        p += 4
                    else:
                        ln = ind + 1
                        disp = (((b & 0xF) << 8) | src[p + 1]) + 1
                        p += 2
                    if disp > len(out):
                        raise CGFXError("the compressed data is damaged")
                    for _ in range(min(ln, size - len(out))):
                        out.append(out[-disp])
                else:
                    out.append(src[p])
                    p += 1
    except IndexError:
        raise CGFXError("the compressed data is truncated")
    return bytes(out)


def lz11_compress(data):
    """LZ11 (the 3DS's 0x11 compression): a simple greedy encoder that reads back exactly with lz11_decompress."""
    n = len(data)
    out = bytearray(bytes([0x11, n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF]))
    if n >= 1 << 24:
        out = bytearray(bytes([0x11, 0, 0, 0])) + struct.pack("<I", n)
    chains = {}                                        # 3-byte key -> recent positions
    i = 0
    while i < n:
        flags, block = 0, bytearray()
        for bit in range(8):
            if i >= n:
                break
            best_len, best_disp = 0, 0
            if i + 3 <= n:
                key = data[i:i + 3]
                for j in reversed(chains.get(key, ())[-24:]):
                    disp = i - j
                    if disp > 0x1000:
                        break
                    ln = 3
                    limit = min(0x10110, n - i)
                    while ln < limit and data[j + ln] == data[i + ln]:
                        ln += 1
                    if ln > best_len:
                        best_len, best_disp = ln, disp
                        if ln >= 0x10110:
                            break
            if best_len >= 3:
                flags |= 0x80 >> bit
                d = best_disp - 1
                if best_len <= 16:
                    block += bytes([((best_len - 1) << 4) | (d >> 8), d & 0xFF])
                elif best_len <= 0x110:
                    v = best_len - 0x11
                    block += bytes([v >> 4, ((v & 0xF) << 4) | (d >> 8), d & 0xFF])
                else:
                    v = best_len - 0x111
                    block += bytes([0x10 | (v >> 12), (v >> 4) & 0xFF, ((v & 0xF) << 4) | (d >> 8), d & 0xFF])
                step = best_len
            else:
                block.append(data[i])
                step = 1
            for k in range(i, min(i + step, n - 2)):   # remember every position we skipped over
                chains.setdefault(data[k:k + 3], []).append(k)
            i += step
        out.append(flags)
        out += block
    return bytes(out)
