"""Just enough CGFX / CBMD handling to re-texture a 3DS banner model.

CGFX pointers are self-relative. PICA200 raw textures are stored as 8x8 blocks
in row order with Z-order (Morton) pixels inside each block, top row first.
"""

import struct

PICA_RGB565 = 3
PICA_LA8 = 5
PICA_L8 = 7


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
        out[name] = dict(name=name, h=h, w=w, length=u32(d, img + 8), data=rel(d, img + 0xC), fmt=u32(d, t + 0x34))
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


def read_texture(d, t):
    from PIL import Image
    _check_texture(d, t, {PICA_RGB565: 2, PICA_LA8: 2, PICA_L8: 1}.get(t["fmt"], 2))
    w, h, p = t["w"], t["h"], t["data"]
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


def write_texture(buf, t, img):
    _check_texture(buf, t, 2)
    w, h, p = t["w"], t["h"], t["data"]
    if img.size != (w, h):
        raise CGFXError("texture size mismatch")
    if t["fmt"] == PICA_RGB565:
        px = img.convert("RGB").load()
        for x, y in _coords(w, h):
            r, g, b = px[x, y]
            struct.pack_into("<H", buf, p, ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5
                             | ((b * 31 + 127) // 255))
            p += 2
    elif t["fmt"] == PICA_LA8:
        px = img.convert("LA").load()
        for x, y in _coords(w, h):
            buf[p + 1], buf[p] = px[x, y]
            p += 2
    else:
        raise CGFXError(f"texture format {t['fmt']} not supported")


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
