"""Draw the 3D console + TV inside an NSUI banner, for the app's preview.

This only reads a banner's CGFX model (triangles, texture coordinates and which bone each mesh
sits on) and draws it flat-shaded with its own textures through the Home Menu's camera. It never
changes the file, and a banner is built without it. It is a preview: the 3DS's own renderer will
light things a little differently.
"""

import math
import struct

from PIL import Image, ImageChops, ImageDraw

from . import cgfx
from .cgfx import CGFXError, _cstr, _dict, rel, u32

CAM = (0.0, 1.0, 44.786)            # the Home Menu's banner camera
YFOV = math.radians(30.0)
NEAR = 26.5
BACKGROUND = (223, 229, 236)
VIEW = (384, 192)

# Sanity limits for a banner model (real ones are far smaller). A damaged or hostile file that goes past them is
# refused instead of being allowed to use up memory or time.
MAX_MESHES, MAX_LISTED, MAX_VERTICES, MAX_INDICES, MAX_TRIANGLES = 64, 32, 65536, 300000, 20000

def _f(d, o, n):
    try:
        return struct.unpack_from("<%df" % n, d, o)
    except struct.error:
        raise CGFXError("the model is truncated or damaged")


def _model(d):
    """Where the CGFX's first 3D model is, or None when it has none (a language model can hold only textures)."""
    data = cgfx.u16(d, 6)
    if u32(d, data + 8) == 0:
        return None
    models = _dict(d, rel(d, data + 12))
    return models[0][1] if models else None


def _compose(a, b):
    """3x4 affine a * b."""
    return tuple(tuple(sum(a[r][k] * b[k][c] for k in range(3)) + (a[r][3] if c == 3 else 0.0)
                       for c in range(4)) for r in range(3))


def _bones(d, model):
    """{name: dict(world=3x4 rows, billboard=int)}. The file's own world matrices are unset, so each bone's
    world matrix is its parents' local matrices multiplied together."""
    skel = rel(d, model + 224)
    raw = []
    for name, b in _dict(d, rel(d, skel + 28)):
        w = _f(d, b + 68, 12)
        raw.append((name, struct.unpack_from("<i", d, b + 12)[0], (w[0:4], w[4:8], w[8:12]), u32(d, b + 212)))
    world, out = {}, {}
    for i, (name, parent, local, billboard) in enumerate(raw):
        if parent >= i:
            raise CGFXError("the model's bones are out of order")
        world[i] = local if parent < 0 else _compose(world[parent], local)
        out[name] = dict(world=world[i], billboard=billboard)
    return out


def _apply(m, p):
    return tuple(m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2] + m[r][3] for r in range(3))


def _texture_name(d, model, material_index, texnames):
    """The texture a material's first texture mapper points at (its name is stored 0x33c into the material)."""
    mats = _dict(d, rel(d, model + 192))
    if material_index >= len(mats):
        return None
    o = mats[material_index][1] + 0x33c
    try:
        name = _cstr(d, rel(d, o))
    except (ValueError, struct.error):
        return None
    return name if name in texnames else None


def _vertex_arrays(d, shape):
    """(start, count, entry size, {usage: byte offset}) for each interleaved vertex buffer of a shape that has
    positions (usage 0) as 3 floats and, if it has them, texture coordinates (usage 4) as 2 floats."""
    va_arr = rel(d, shape + 60)
    if u32(d, shape + 56) > MAX_LISTED or u32(d, shape + 44) > MAX_LISTED:
        raise CGFXError("the model is damaged (too many lists)")
    for j in range(u32(d, shape + 56)):
        attr = rel(d, va_arr + 4 * j)
        if u32(d, attr) != 0x40000002:                           # an interleaved vertex buffer
            continue
        entry, start = u32(d, attr + 36), rel(d, attr + 24)
        if not 12 <= entry <= 256 or u32(d, attr + 40) > MAX_LISTED:
            raise CGFXError("the model is damaged (bad vertex layout)")
        layout = {}
        arr = rel(d, attr + 44)
        for k in range(u32(d, attr + 40)):
            s = rel(d, arr + 4 * k)
            layout[u32(d, s + 4)] = u32(d, s + 48)               # usage -> byte offset in the entry
        if 0 not in layout:
            continue
        count = u32(d, attr + 20) // entry
        if count > MAX_VERTICES or start < 0 or start + count * entry > len(d):
            raise CGFXError("the model is damaged (bad vertex data)")
        if layout[0] < 0 or layout[0] + 12 > entry or (4 in layout and layout[4] + 8 > entry):
            raise CGFXError("the model is damaged (bad vertex layout)")
        yield start, count, entry, layout


def read_meshes(d):
    """[{node, billboard, tris}]: tris are ((x, y, z, u, v) * 3) in model space, or an empty list if the file
    isn't laid out like an NSUI banner or has no 3D model, only textures."""
    model = _model(d)
    if model is None:
        return []
    bones = _bones(d, model)
    texnames = set(cgfx.textures(d))
    meshes = []
    n_mesh, mesh_arr = u32(d, model + 180), rel(d, model + 184)
    shape_arr = rel(d, model + 200)
    if n_mesh > MAX_MESHES:
        raise CGFXError("the model has too many parts")
    n_shapes = u32(d, model + 196)
    for i in range(n_mesh):
        mo = rel(d, mesh_arr + 4 * i)
        node = _cstr(d, rel(d, mo + 112))
        if u32(d, mo + 24) >= n_shapes:
            raise CGFXError("the model is damaged (bad shape number)")
        shape = rel(d, shape_arr + 4 * u32(d, mo + 24))
        mesh = dict(node=node, billboard=bones.get(node, {}).get("billboard", 0), tris=[],
                    texture=_texture_name(d, model, u32(d, mo + 28), texnames))
        world = bones.get(node, {}).get("world", ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0)))
        verts = None
        for start, count, entry, layout in _vertex_arrays(d, shape):
            verts = []
            for v in range(count):
                o = start + v * entry
                x, y, z = _f(d, o + layout[0], 3)
                u, w = _f(d, o + layout[4], 2) if 4 in layout else (0.0, 0.0)
                verts.append(_apply(world, (x, y, z)) + (u, w))
        if verts is None:
            continue
        ps_arr = rel(d, shape + 48)
        for j in range(u32(d, shape + 44)):
            ps = rel(d, ps_arr + 4 * j)
            pr_arr = rel(d, ps + 16)
            if u32(d, ps + 12) > MAX_LISTED:
                raise CGFXError("the model is damaged (too many lists)")
            for q in range(u32(d, ps + 12)):
                pr = rel(d, pr_arr + 4 * q)
                is_arr = rel(d, pr + 4)
                if u32(d, pr) > MAX_LISTED:
                    raise CGFXError("the model is damaged (too many lists)")
                for r in range(u32(d, pr)):
                    ist = rel(d, is_arr + 4 * r)
                    fmt, length, ptr = u32(d, ist), u32(d, ist + 8), rel(d, ist + 12)
                    width = {0x1403: 2, 0x1401: 1}.get(fmt)
                    if width is None:
                        continue
                    if length // width > MAX_INDICES or ptr < 0 or ptr + length > len(d):
                        raise CGFXError("the model is damaged (bad index data)")
                    idx = struct.unpack_from(("<%dH" if width == 2 else "<%dB") % (length // width), d, ptr)
                    if idx and max(idx) >= len(verts):
                        raise CGFXError("the model is damaged (an index points past the vertices)")
                    for k in range(0, len(idx) - 2, 3):
                        mesh["tris"].append(tuple(verts[idx[k + c]] for c in range(3)))
                    if len(mesh["tris"]) > MAX_TRIANGLES:
                        raise CGFXError("the model has too many triangles")
        meshes.append(mesh)
    return meshes


def textured(d, overrides=None):
    """[{tris, image, billboard}] for one CGFX: every mesh with the picture of the texture it wears. `overrides` maps
    a texture name to a replacement PIL image (the drawn title plate, say)."""
    texs = cgfx.textures(d)
    cache, out = {}, []
    buf = bytearray(d)
    for m in read_meshes(d):
        name = m["texture"]
        if name is None or not m["tris"]:
            continue
        if name not in cache:
            try:
                cache[name] = (overrides or {}).get(name) or cgfx.read_texture(buf, texs[name])
            except ValueError:
                cache[name] = None                           # a lookup or normal-map format: not drawn
        if cache[name] is not None:
            out.append(dict(tris=m["tris"], image=cache[name], billboard=m["billboard"]))
    return out


# ---------------------------------------------------------------------------------------------- flat banners
SCREEN = (400, 240)                                      # the 3DS's top screen
PIXELS_PER_UNIT = 10.0          # on the top screen at depth 0: 120 / tan(15 degrees) / 44.786 = 10.0003


def screen_to_model(x, y):
    """A point of the top screen (400 x 240 pixels) as a position in the banner model at depth 0."""
    return (x - SCREEN[0] / 2) / PIXELS_PER_UNIT + CAM[0], CAM[1] + (SCREEN[1] / 2 - y) / PIXELS_PER_UNIT


def flat_banner_model(base, img, quad):
    """bannertool's flat banner model (one picture on one rectangle) showing `img` in full colour (RGBA8, where
    bannertool uses 4 bits per channel) on the rectangle quad = (left, top, right, bottom) of the top screen, in
    pixels. img's width must be a power of two; its height is padded with transparent rows to the next one."""
    texs = list(cgfx.textures(base).values())
    if len(texs) != 1 or texs[0]["data"] + texs[0]["length"] != len(base):
        raise CGFXError("the banner model isn't laid out like bannertool's")
    t = texs[0]
    w, h = img.size
    th = 8
    while th < h:
        th *= 2
    if w not in (8, 16, 32, 64, 128, 256, 512, 1024) or th > cgfx.MAX_TEXTURE_SIDE:
        raise CGFXError(f"a {w} x {h} picture can't be a banner texture")
    tex = Image.new("RGBA", (w, th), (0, 0, 0, 0))
    tex.paste(img.convert("RGBA"), (0, 0))
    out = bytearray(base[:t["data"]]) + cgfx.rgba8_bytes(tex)

    image = rel(base, t["txob"] + 0x38)
    for off, value in ((t["txob"] + 0x18, th), (t["txob"] + 0x1C, w), (t["txob"] + 0x24, cgfx.GL_UNSIGNED_BYTE),
                       (t["txob"] + 0x28, 1), (t["txob"] + 0x34, cgfx.PICA_RGBA8), (image, th), (image + 4, w),
                       (image + 8, w * th * 4), (image + 0x14, 32)):
        struct.pack_into("<I", out, off, value)
    imag = cgfx.u16(base, 6) + u32(base, 0x18)            # the image block follows the data block
    if bytes(base[imag:imag + 4]) != b"IMAG":
        raise CGFXError("the banner model isn't laid out like bannertool's")
    struct.pack_into("<I", out, 12, len(out))
    struct.pack_into("<I", out, imag + 4, len(out) - imag)

    model = _model(base)
    if model is None or u32(base, model + 180) != 1:
        raise CGFXError("the banner model isn't laid out like bannertool's")
    arrays = list(_vertex_arrays(base, rel(base, rel(base, model + 200))))
    if len(arrays) != 1 or arrays[0][1] != 4 or 4 not in arrays[0][3]:
        raise CGFXError("the banner model isn't laid out like bannertool's")
    start, count, entry, layout = arrays[0]
    corners = [_f(base, start + v * entry + layout[0], 2) for v in range(4)]
    mid_x, mid_y = sum(c[0] for c in corners) / 4, sum(c[1] for c in corners) / 4
    (x0, y0), (x1, y1) = screen_to_model(quad[0], quad[1]), screen_to_model(quad[2], quad[3])
    for v, (x, y) in enumerate(corners):
        right, top = x > mid_x, y > mid_y
        o = start + v * entry
        struct.pack_into("<2f", out, o + layout[0], x1 if right else x0, y0 if top else y1)
        struct.pack_into("<2f", out, o + layout[4], 1.0 if right else 0.0, 1.0 if top else 1.0 - h / th)
    return bytes(out)


def _buffers(base, model):
    """(vertex attribute, index stream, shape) offsets of bannertool's model: one shape with one interleaved vertex
    buffer and one stream of 8-bit indices."""
    if u32(base, model + 180) != 1 or u32(base, model + 196) != 1:
        raise CGFXError("the banner model isn't laid out like bannertool's")
    shape = rel(base, rel(base, model + 200))
    attrs = [rel(base, rel(base, shape + 60) + 4 * j) for j in range(u32(base, shape + 56))]
    attrs = [a for a in attrs if u32(base, a) == 0x40000002]
    if u32(base, shape + 44) != 1 or len(attrs) != 1:
        raise CGFXError("the banner model isn't laid out like bannertool's")
    ps = rel(base, rel(base, shape + 48))
    if u32(base, ps + 12) != 1:
        raise CGFXError("the banner model isn't laid out like bannertool's")
    pr = rel(base, rel(base, ps + 16))
    if u32(base, pr) != 1:
        raise CGFXError("the banner model isn't laid out like bannertool's")
    ist = rel(base, rel(base, pr + 4))
    if u32(base, ist) != 0x1401 or u32(base, attrs[0] + 36) != 20:
        raise CGFXError("the banner model isn't laid out like bannertool's")
    return attrs[0], ist, shape


def depth_scale(z):
    """How much smaller a thing at depth z (towards the camera) must be in the model to cover the same part of the
    screen as at depth 0."""
    return (CAM[2] - z) / CAM[2]


def layered_banner_model(base, layers):
    """bannertool's banner model (see flat_banner_model) turned into several pictures at different depths, so the
    banner stands out of the screen with the 3D slider up, as NSUI's 3D banners do. `layers` is [(picture, quad,
    depth)], back to front: each picture covers quad = (left, top, right, bottom) of the top screen, in pixels, at
    its depth (in model units towards the camera; NSUI's frame sits at about 1.8 and its plate at 8). The pictures
    share one full-colour RGBA8 texture, each with a clear border so they don't bleed into each other."""
    texs = list(cgfx.textures(base).values())
    if len(texs) != 1 or texs[0]["data"] + texs[0]["length"] != len(base) or not 0 < len(layers) <= 40:
        raise CGFXError("the banner model isn't laid out like bannertool's")
    t = texs[0]
    model = _model(base)
    if model is None:
        raise CGFXError("the banner model isn't laid out like bannertool's")
    attr, ist, shape = _buffers(base, model)
    imag = cgfx.u16(base, 6) + u32(base, 0x18)
    if bytes(base[imag:imag + 4]) != b"IMAG":
        raise CGFXError("the banner model isn't laid out like bannertool's")

    # the pictures, packed in rows into one texture 256 wide, 2 clear texels around each
    W, gap, places, x, y, row = 256, 2, [], 0, 0, 0
    for img, _quad, _z in layers:
        w, h = img.size
        if w + 2 * gap > W:
            raise CGFXError(f"a {w} x {h} picture is too wide for the banner")
        if x + w + 2 * gap > W:
            x, y, row = 0, y + row, 0
        places.append((x + gap, y + gap))
        x, row = x + w + 2 * gap, max(row, h + 2 * gap)
    H = 8
    while H < y + row:
        H *= 2
    if H > W:
        raise CGFXError("the banner's pictures don't fit in one texture")
    tex = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for (img, _quad, _z), (px, py) in zip(layers, places):
        tex.paste(img.convert("RGBA"), (px, py))

    indices, vertices, xs, ys, zs = bytearray(), bytearray(), [], [], []
    for k, ((img, quad, z), (px, py)) in enumerate(zip(layers, places)):
        f = depth_scale(z) / PIXELS_PER_UNIT
        left, right = CAM[0] + (quad[0] - SCREEN[0] / 2) * f, CAM[0] + (quad[2] - SCREEN[0] / 2) * f
        top, bottom = CAM[1] + (SCREEN[1] / 2 - quad[1]) * f, CAM[1] + (SCREEN[1] / 2 - quad[3]) * f
        u0, u1 = px / W, (px + img.width) / W
        v_top, v_bottom = 1 - py / H, 1 - (py + img.height) / H
        for vx, vy, u, v in ((left, bottom, u0, v_bottom), (right, bottom, u1, v_bottom),
                             (left, top, u0, v_top), (right, top, u1, v_top)):
            vertices += struct.pack("<5f", vx, vy, z, u, v)
        indices += bytes(4 * k + i for i in (0, 1, 2, 1, 3, 2))
        xs += [left, right]
        ys += [top, bottom]
        zs.append(z)

    out = bytearray(base[:imag + 8])
    index_at = len(out)
    out += indices + bytes(-len(indices) % 8)
    vertex_at = len(out)
    out += vertices
    out += bytes(-len(out) % 128)
    texture_at = len(out)
    out += cgfx.rgba8_bytes(tex)

    image = rel(base, t["txob"] + 0x38)
    for off, value in ((t["txob"] + 0x18, H), (t["txob"] + 0x1C, W), (t["txob"] + 0x24, cgfx.GL_UNSIGNED_BYTE),
                       (t["txob"] + 0x28, 1), (t["txob"] + 0x34, cgfx.PICA_RGBA8), (image, H), (image + 4, W),
                       (image + 8, W * H * 4), (image + 0x14, 32), (image + 0xC, texture_at - (image + 0xC)),
                       (ist + 8, len(indices)), (ist + 12, index_at - (ist + 12)),
                       (attr + 20, len(vertices)), (attr + 24, vertex_at - (attr + 24)),
                       (12, len(out)), (imag + 4, len(out) - imag)):
        struct.pack_into("<I", out, off, value)
    obb = rel(base, shape + 0x1C)                       # the shape's bounding box: centre, orientation, size
    struct.pack_into("<3f", out, obb + 4, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    struct.pack_into("<3f", out, obb + 0x34, max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    return bytes(out)


# ---------------------------------------------------------------------------------------------- drawing
def _affine(dst, src):
    """(a, b, c, d, e, f) with u = a x + b y + c and v = d x + e y + f for the three point pairs."""
    (x0, y0), (x1, y1), (x2, y2) = dst
    det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(det) < 1e-9:
        return None
    out = []
    for k in (0, 1):
        s0, s1, s2 = src[0][k], src[1][k], src[2][k]
        a = ((s1 - s0) * (y2 - y0) - (s2 - s0) * (y1 - y0)) / det
        b = ((x1 - x0) * (s2 - s0) - (x2 - x0) * (s1 - s0)) / det
        out += [a, b, s0 - a * x0 - b * y0]
    return tuple(out)


def render(parts, yaw_deg=0.0, size=VIEW, ss=2):
    """Draw `parts` (from textured()). Billboard parts (the title plate) face the camera."""
    W, H = size[0] * ss, size[1] * ss
    f = (H / 2) / math.tan(YFOV / 2)
    img = Image.new("RGB", (W, H), BACKGROUND)
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))

    def cam(p):
        x, z = p[0] * c + p[2] * s, -p[0] * s + p[2] * c
        return (x - CAM[0], p[1] - CAM[1], CAM[2] - z)

    def proj(q):
        return (W / 2 + q[0] / q[2] * f, H / 2 - q[1] / q[2] * f)

    if sum(len(m["tris"]) for m in parts) > MAX_TRIANGLES:
        raise CGFXError("the model has too many triangles")
    work, plates = [], []
    for m in parts:
        if m["billboard"]:
            plates.append(m)
            continue
        small = len(m["tris"]) <= 4                          # a screen quad sits just in front of its TV
        for tri in m["tris"]:
            q = [cam(v) for v in tri]
            if any(p[2] < NEAR for p in q):
                continue
            pts = [proj(p) for p in q]
            area = (pts[1][0] - pts[0][0]) * (pts[2][1] - pts[0][1]) - (pts[2][0] - pts[0][0]) * (pts[1][1] - pts[0][1])
            if area >= 0:
                continue                                    # facing away
            work.append((sum(p[2] for p in q) / 3 - (1.5 if small else 0.0), m["image"], pts,
                         [(v[3], v[4]) for v in tri]))
    work.sort(key=lambda t: -t[0])

    tiled = {}
    for _, image, pts, uvs in work:
        su, sv = math.floor(min(u for u, _ in uvs)), math.floor(min(v for _, v in uvs))
        uvs = [(u - su, v - sv) for u, v in uvs]             # a repeating texture: n x n copies of it cover these
        n = max(1, math.ceil(max(max(uv) for uv in uvs) - 1e-6))
        if n > 4:
            continue
        if (id(image), n) not in tiled:
            one = image.convert("RGBA")
            many = Image.new("RGBA", (one.width * n, one.height * n))
            for i in range(n * n):
                many.paste(one, (i % n * one.width, i // n * one.height))
            tiled[id(image), n] = many
        tex = tiled[id(image), n]
        tw, th = tex.width / n, tex.height / n
        coeffs = _affine(pts, [(u * tw, (n - v) * th) for u, v in uvs])
        if coeffs is None:
            continue
        cx, cy = sum(p[0] for p in pts) / 3, sum(p[1] for p in pts) / 3
        grown = []
        for p in pts:                                       # a hair bigger so neighbours leave no gaps
            dx, dy = p[0] - cx, p[1] - cy
            n = math.hypot(dx, dy) or 1.0
            grown.append((p[0] + dx / n * 0.7 * ss, p[1] + dy / n * 0.7 * ss))
        x0, y0 = max(0, int(min(p[0] for p in grown)) - 1), max(0, int(min(p[1] for p in grown)) - 1)
        x1, y1 = min(W, int(max(p[0] for p in grown)) + 2), min(H, int(max(p[1] for p in grown)) + 2)
        if x1 <= x0 or y1 <= y0:
            continue
        a, b, cc, dd, e, ff = coeffs
        local = (a, b, cc + a * x0 + b * y0, dd, e, ff + dd * x0 + e * y0)
        patch = tex.transform((x1 - x0, y1 - y0), Image.AFFINE, local, Image.BILINEAR)
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(mask).polygon([(p[0] - x0, p[1] - y0) for p in grown], fill=255)
        img.paste(patch.convert("RGB"), (x0, y0), ImageChops.multiply(mask, patch.getchannel("A")))

    for m in plates:                                        # the title plate faces the camera
        xs = [v[0] for t in m["tris"] for v in t]
        ys = [v[1] for t in m["tris"] for v in t]
        zs = [v[2] for t in m["tris"] for v in t]
        dist = CAM[2] - sum(zs) / len(zs)
        w_px, h_px = (max(xs) - min(xs)) / dist * f, (max(ys) - min(ys)) / dist * f
        cx = W / 2 + ((min(xs) + max(xs)) / 2 - CAM[0]) / dist * f
        cy = H / 2 - ((min(ys) + max(ys)) / 2 - CAM[1]) / dist * f
        tex = m["image"].convert("RGBA").resize((max(1, round(w_px)), max(1, round(h_px))), Image.LANCZOS)
        img.paste(tex.convert("RGB"), (round(cx - w_px / 2), round(cy - h_px / 2)), tex.getchannel("A"))
    return img.resize(size, Image.LANCZOS) if ss != 1 else img
