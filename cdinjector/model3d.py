"""Draw the 3D console + TV inside an NSUI banner, for the app's preview.

This only reads a banner's CGFX model (triangles, texture coordinates and which bone each mesh
sits on) and draws it flat-shaded with its own textures through the Home Menu's camera. It never
changes the file, and a banner is built without it. It is a preview: the 3DS's own renderer will
light things a little differently.
"""

import math
import struct

from PIL import Image, ImageDraw

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
    data = cgfx.u16(d, 6)
    models = _dict(d, rel(d, data + 12))
    if not models:
        raise CGFXError("the banner has no 3D model")
    return models[0][1]


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


def read_meshes(d):
    """[{node, billboard, tris}]: tris are ((x, y, z, u, v) * 3) in model space, or an empty list if the file
    isn't laid out like an NSUI banner."""
    model = _model(d)
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
        va_arr = rel(d, shape + 60)
        mesh = dict(node=node, billboard=bones.get(node, {}).get("billboard", 0), tris=[],
                    texture=_texture_name(d, model, u32(d, mo + 28), texnames))
        world = bones.get(node, {}).get("world", ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0)))
        verts = None
        if u32(d, shape + 56) > MAX_LISTED or u32(d, shape + 44) > MAX_LISTED:
            raise CGFXError("the model is damaged (too many lists)")
        for j in range(u32(d, shape + 56)):
            attr = rel(d, va_arr + 4 * j)
            if u32(d, attr) != 0x40000002:                       # an interleaved vertex buffer
                continue
            entry, start = u32(d, attr + 36), rel(d, attr + 24)
            if not 12 <= entry <= 256 or u32(d, attr + 40) > MAX_LISTED:
                raise CGFXError("the model is damaged (bad vertex layout)")
            layout = {}
            arr = rel(d, attr + 44)
            for k in range(u32(d, attr + 40)):
                s = rel(d, arr + 4 * k)
                layout[u32(d, s + 4)] = u32(d, s + 48)           # usage -> byte offset in the entry
            if 0 not in layout:
                continue
            count = u32(d, attr + 20) // entry
            if count > MAX_VERTICES or start < 0 or start + count * entry > len(d):
                raise CGFXError("the model is damaged (bad vertex data)")
            if any(off < 0 or off + 12 > entry for off in (layout[0],)) or (4 in layout and layout[4] + 8 > entry):
                raise CGFXError("the model is damaged (bad vertex layout)")
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

    rgb = {}
    for _, image, pts, uvs in work:
        tex = rgb.setdefault(id(image), image.convert("RGB"))
        tw, th = tex.size
        coeffs = _affine(pts, [(u * tw, (1 - v) * th) for u, v in uvs])
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
        img.paste(patch, (x0, y0), mask)

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
