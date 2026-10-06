"""Banners and icons exported from NSUI (New Super Ultimate Injector for 3DS).

NSUI can't make CIAs from Sega CD or PC Engine CD games, but it can from cartridge games (Genesis, TurboGrafx, GBA
and others). Its "export banner / icon" gives a 3D banner (`.bin`, a 3DS banner) and an icon (`.bin`, a 3DS icon)
that this app can put on a CD game's CIA instead of its own.

An exported banner works as a template for any number of games: this app puts the game's title and year on the
Virtual Console plate and the game's picture where the banner shows one. Two kinds are understood:

* "3D frame with color": the picture goes in the frame.
* 3D console + TV (NSUI's Genesis and PC Engine banners): the picture goes on the TV's screen, stretched over it as
  NSUI does. In the Genesis banner the screen is a rectangle of its own; in the PC Engine one it is part of the TV's
  front, ringed by the TV's own colour. NSUI leaves the PC Engine banner's plate blank, so the whole plate is drawn.

The 3D models, their colours and movement, the plate's badge and the sound stay NSUI's: only the plate's and the
picture's textures are rewritten, and the sound keeps its bytes.

A 3DS banner (CBMD) is a header, a main 3D model (LZ11-compressed CGFX), up to 30 language-specific models, and a
sound. The Home Menu draws the main model and the language model of the system's language, and a texture in the
language model takes the place of the main model's texture of the same name. In NSUI's PC Engine banner the main
model holds the TV and the plate and each language model holds the console, with its own copy of the plate and the
TV's texture: those copies are what the 3DS shows, so they get the title and picture too. Its frame banners and its
Genesis banner have only the main model.
"""

import struct
from pathlib import Path

from . import banner as bn
from . import cgfx, model3d

PLATE = "COMMON1"                          # the plate's name in NSUI's console + TV banners
HEADER = 0x88
MAX_BANNER = 4 * 1024 * 1024               # real banners are under 1 MB; this stops a huge file being read into memory
MAX_LANGUAGES = 30
FRAME_RIM = 4                              # the light rim around the picture in a frame banner, in texels
TEXT_AREA = (95, 4, 249, 60)               # the part of the plate the title and year are written on


# What reading a damaged 3D model can raise (the readers check sizes and offsets, but a hostile file can still be
# inconsistent in ways that end in one of these).
MODEL_ERRORS = (ValueError, IndexError, KeyError, struct.error, ZeroDivisionError, OverflowError, MemoryError)


class NSUIError(Exception):
    """The file can't be used as an NSUI banner."""


class DamagedBannerError(NSUIError):
    """The file claims to be a 3DS banner but its structure is broken. Such a file must never end up in a CIA:
    a bad banner can stop the Home Menu from showing the game."""


def _parts(cg):
    """(plate, picture, screen) in a banner's main model. plate: the name of the title plate's texture (256 x 64
    luminance + alpha, on the part that always faces the camera), or None when there is none. picture: a frame
    banner's picture texture (full colour with see-through corners, on a single rectangle), else None. screen: a
    console + TV banner's TV screen as (texture name, (left, top, right, bottom) in texels), else None."""
    texs = cgfx.textures(cg)
    plate = picture = screen = None
    try:
        meshes = model3d.read_meshes(cg)
    except MODEL_ERRORS:                                   # a model this reader can't follow: look the plate up by name
        meshes = []
    for m in meshes:
        t = texs.get(m["texture"])
        if t is None:
            continue
        if m["billboard"] and t["fmt"] == cgfx.PICA_LA8 and (t["w"], t["h"]) == (256, 64):
            plate = m["texture"]
        elif not m["billboard"] and len(m["tris"]) == 2 and t["fmt"] == cgfx.PICA_RGBA8:
            picture = m["texture"]
    if plate is None and PLATE in texs and texs[PLATE]["fmt"] == cgfx.PICA_LA8 and \
            (texs[PLATE]["w"], texs[PLATE]["h"]) == (256, 64):
        plate = PLATE
    if picture is None:
        try:
            screen = _screen(cg, meshes, texs)
        except MODEL_ERRORS:
            screen = None
    return plate, picture, screen


def _front(mesh):
    """The texel-space box ((u0, v0), (u1, v1) as fractions) of the mesh's biggest flat rectangle: the two triangles
    that cover the most of its texture."""
    def uv_area(tri):
        (u0, v0), (u1, v1), (u2, v2) = ((v[3], v[4]) for v in tri)
        return abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0)) / 2
    tris = sorted(mesh["tris"], key=uv_area, reverse=True)[:2]
    us = [v[3] for t in tris for v in t]
    vs = [v[4] for t in tris for v in t]
    return (min(us), min(vs)), (max(us), max(vs))


def _screen(cg, meshes, texs):
    """Where the TV screen is in a console + TV banner (see _parts), or None."""
    solid = [m for m in meshes if not m["billboard"] and m["tris"] and m["texture"] in texs
             and texs[m["texture"]]["fmt"] == cgfx.PICA_RGB565]
    for m in solid:          # NSUI's Genesis banner: the screen is a rectangle of its own, showing all of its texture
        if len(m["tris"]) == 2 and sum(x["texture"] == m["texture"] for x in meshes) == 1:
            t = texs[m["texture"]]
            return m["texture"], (0, 0, t["w"], t["h"])
    if len(solid) != 1:
        return None
    # NSUI's PC Engine banner: the TV is the main model's only solid part, and its screen is the part of the TV's
    # front inside the ring of the TV's own colour
    m = solid[0]
    t = texs[m["texture"]]
    img = cgfx.read_texture(cg, t).convert("RGB")
    (u0, v0), (u1, v1) = _front(m)
    fx0, fx1 = max(0, round(u0 * t["w"])), min(t["w"], round(u1 * t["w"]))
    fy0, fy1 = max(0, round((1 - v1) * t["h"])), min(t["h"], round((1 - v0) * t["h"]))
    if fx1 - fx0 < 16 or fy1 - fy0 < 16:
        return None
    ring = img.getpixel((fx0 + 1, (fy0 + fy1) // 2))

    def is_ring(x, y):
        return max(abs(a - b) for a, b in zip(img.getpixel((x, y)), ring)) <= 12

    cx = (fx0 + fx1) // 2
    top = next((y for y in range(fy0, fy1) if not is_ring(cx, y)), None)
    if top is None:
        return None
    # the bottom is a whole row of the ring's colour: a dark texel in the old game's picture can match it on its own
    across = [fx0 + (fx1 - fx0) * k // 8 for k in range(2, 7)]
    bottom = next((y for y in range(top, fy1) if all(is_ring(x, y) for x in across)), fy1)
    cy = (top + bottom) // 2
    left = next((x for x in range(fx0, fx1) if not is_ring(x, cy)), fx0)
    right = next((x + 1 for x in range(fx1 - 1, fx0, -1) if not is_ring(x, cy)), fx1)
    if (right - left) * (bottom - top) < 0.4 * (fx1 - fx0) * (fy1 - fy0):
        return None
    return m["texture"], (left, top, right, bottom)


class Banner:
    """A parsed NSUI banner: the main model, the language-model blocks, and where everything sits in the file."""

    def __init__(self, path, require_nsui=True):
        """Read and check the banner's structure. require_nsui=False accepts any well-formed banner; the default
        also insists on one of NSUI's layouts (raising the plain NSUIError when it isn't)."""
        self.path = Path(path)
        try:
            if self.path.stat().st_size > MAX_BANNER:
                raise DamagedBannerError(f"{self.path.name} is far too big to be a 3DS banner.")
            d = self.path.read_bytes()
        except OSError as e:
            raise NSUIError(f"Couldn't read {self.path.name}: {e}")
        if d[:4] != b"CBMD":
            raise NSUIError(f"{self.path.name} doesn't look like a 3DS banner.")
        name = self.path.name
        if len(d) < HEADER + 8:
            raise DamagedBannerError(f"{name} is cut short.")
        self.data = d
        self.words = list(struct.unpack_from("<%dI" % (HEADER // 4), d, 0))
        self.common_off = self.words[2]
        self.lang_offs = [w for w in self.words[3:HEADER // 4 - 1] if w]
        self.cwav_off = self.words[HEADER // 4 - 1]
        offsets = [self.common_off] + self.lang_offs + ([self.cwav_off] if self.cwav_off else [])
        if (self.common_off < HEADER or len(self.lang_offs) > MAX_LANGUAGES or offsets != sorted(set(offsets))
                or offsets[-1] >= len(d)):
            raise DamagedBannerError(f"{name} has a damaged header (its sections don't fit the file).")
        if self.cwav_off and bytes(d[self.cwav_off:self.cwav_off + 4]) != b"CWAV":
            raise DamagedBannerError(f"{name} has no valid sound section.")
        if self.cwav_off:                                   # the sound states its own length: all of it must be there
            stated = struct.unpack_from("<I", d, self.cwav_off + 0xC)[0] if len(d) >= self.cwav_off + 0x10 else 0
            if stated < 0x40 or stated > len(d) - self.cwav_off:
                raise DamagedBannerError(f"{name} is cut short: its sound is incomplete.")
        following = sorted(o for o in self.lang_offs + [self.cwav_off] if o > self.common_off)
        self.common_end = following[0] if following else len(d)
        self.plate = self.picture = self.screen = None
        try:
            self.common = bytearray(cgfx.lz11_decompress(d[self.common_off:self.common_end]))
            if bytes(self.common[:4]) != b"CGFX":
                raise DamagedBannerError(f"{name}'s 3D model isn't valid.")
            if require_nsui:
                self.plate, self.picture, self.screen = _parts(bytes(self.common))
        except ValueError as e:
            raise DamagedBannerError(f"{name} is damaged: {e}.")
        if require_nsui and self.plate is None:
            raise NSUIError(f"{name} is a 3DS banner, but not one exported from NSUI.")

    @property
    def is_frame(self):
        """True for NSUI's "3D frame with color" banners (a picture in a frame), False for console + TV ones."""
        return self.picture is not None

    def validate(self):
        """Check every 3D model in the banner (the main one and each language one) decompresses to a real CGFX.
        Raises DamagedBannerError otherwise."""
        self.language_blocks()
        return self

    def language_blocks(self):
        """[(offset in the file, decompressed CGFX)] for each language-specific model. Raises DamagedBannerError
        when one can't be decompressed."""
        out = []
        for start in self.lang_offs:
            later = sorted(o for o in self.lang_offs + [self.cwav_off] if o > start)
            try:
                block = cgfx.lz11_decompress(self.data[start:later[0] if later else len(self.data)])
            except ValueError as e:
                raise DamagedBannerError(f"{self.path.name} is damaged: {e}.")
            if block[:4] != b"CGFX":
                raise DamagedBannerError(f"{self.path.name} has a language model that isn't valid.")
            out.append((start, block))
        return out

    def language_model(self):
        """The first language-specific model, decompressed, or None."""
        if not self.lang_offs:
            return None
        try:
            return self.language_blocks()[0][1]
        except NSUIError:
            return None

    def texture(self, name):
        return cgfx.read_texture(self.common, cgfx.textures(bytes(self.common))[name])

    def plate_blank(self):
        """True when the title plate has nothing on it (one flat value), as in some NSUI exports."""
        (l0, l1), (a0, a1) = self.texture(self.plate).getextrema()
        return l0 == l1 and a0 == a1

    def changes(self, title, year, font_file=None, picture=None):
        """{texture name: new picture} for this game, and a note saying what was added. The plate gets the game's
        title and year (a blank plate is drawn whole; a filled one keeps NSUI's badge and gets new text), and the
        game's picture, if there is one, goes in the frame or on the TV screen."""
        if self.plate_blank():
            new = {self.plate: plate_texture(title, year, font_file)}
        else:
            new = {self.plate: retitled_plate(self.texture(self.plate), title, year, font_file)}
        if picture is not None and self.is_frame:
            new[self.picture] = framed_picture(self.texture(self.picture), picture)
        elif picture is not None and self.screen:
            name, box = self.screen
            new[name] = screen_picture(self.texture(name), box, picture)
        return new, "your picture and title added" if len(new) > 1 else "title added"


def plate_texture(title, year, font_file=None):
    """Our whole Virtual Console plate as the 256 x 64 luminance + alpha texture the banner uses. Like NSUI's own,
    its see-through texels are white, so the 3DS's smoothing doesn't give the plate a dark outline."""
    from PIL import Image
    plate = bn.draw_plate(title, year, S=4, font_file=font_file).reduce(4)
    alpha = plate.getchannel("A")
    lum = plate.convert("L")
    lum.paste(255, (0, 0), alpha.point(lambda v: 255 if v == 0 else 0))
    return Image.merge("LA", (lum, alpha))


def retitled_plate(plate, title, year, font_file=None):
    """A frame banner's own plate (luminance + alpha) with this game's title and year in place of the old ones. The
    badge and rim stay NSUI's; the text area is wiped with the plate's own face, taken from the clean column just
    left of it."""
    from PIL import Image
    x0, y0, x1, y1 = TEXT_AREA
    rgba = Image.merge("RGBA", (plate.getchannel(0),) * 3 + (plate.getchannel(1),))
    face = rgba.crop((x0 - 1, y0, x0, y1))
    rgba.paste(face.resize((x1 - x0, y1 - y0), Image.NEAREST), (x0, y0))
    rgba.alpha_composite(bn.plate_text(title, year, S=4, font_file=font_file).reduce(4))
    return Image.merge("LA", (rgba.convert("L"), rgba.getchannel("A")))


def framed_picture(old, picture):
    """A frame banner's picture texture with `picture` in place of the old game's: the light rim (its colour and
    rounded outline) stays as NSUI drew it, and the new picture fills the window inside it."""
    from PIL import Image, ImageDraw
    out = old.convert("RGBA")
    box = out.getchannel("A").getbbox()
    if not box or box[2] - box[0] <= 4 * FRAME_RIM or box[3] - box[1] <= 4 * FRAME_RIM:
        raise NSUIError("This frame banner's picture isn't laid out as expected.")
    rim = out.getpixel((box[0] + 1, (box[1] + box[3]) // 2))
    x0, y0, x1, y1 = box[0] + FRAME_RIM, box[1] + FRAME_RIM, box[2] - FRAME_RIM, box[3] - FRAME_RIM
    out.paste(rim, (x0, y0, x1, y1))
    S = 4
    pic = picture if hasattr(picture, "size") else Image.open(picture)
    big = bn.fit_image(bn.tv_picture(pic.convert("RGBA")), ((x1 - x0) * S, (y1 - y0) * S), "cover")
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big.width - 1, big.height - 1), 3.5 * S, fill=255)
    small = Image.merge("RGBA", big.split() + (mask,)).resize((x1 - x0, y1 - y0), Image.LANCZOS)
    out.alpha_composite(small, (x0, y0))
    return out


def screen_picture(old, box, picture):
    """A console + TV banner's screen texture with `picture` stretched over the screen's box, as NSUI does it; the
    rest of the texture (the TV's front around the screen) is kept."""
    from PIL import Image
    out = old.convert("RGB")
    pic = picture if hasattr(picture, "size") else Image.open(picture)
    out.paste(pic.convert("RGB").resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS), box[:2])
    return out


def _write_textures(cg, new):
    """Write the pictures in `new` ({texture name: picture}) into the CGFX `cg` (a bytearray), each into its texture
    of that name and size. Returns how many were written."""
    texs = cgfx.textures(bytes(cg))
    written = 0
    for name, img in new.items():
        t = texs.get(name)
        if t is None or (t["w"], t["h"]) != img.size:
            continue
        if t["fmt"] == cgfx.PICA_RGBA8:
            cgfx.write_rgba8(cg, t, img)
        else:
            cgfx.write_texture(cg, t, img)
        written += 1
    return written


def prepare(path, title, year, workdir, font_file=None, picture=None):
    """The banner file to put in the CIA, with this game's title and picture: (path, note), where note says what was
    added (see Banner.changes). The main model gets them, and so does every language model with its own copy of
    the plate or the picture's texture; the other language models and the sound keep their bytes."""
    b = Banner(path).validate()
    try:
        new, note = b.changes(title, year, font_file, picture)
        cg = bytearray(b.common)
        if _write_textures(cg, new) != len(new):
            raise DamagedBannerError(f"{b.path.name}'s 3D model isn't laid out as expected.")
        models = {b.common_off: cg}
        for start, block in b.language_blocks():
            block = bytearray(block)
            if _write_textures(block, new):
                models[start] = block
    except MODEL_ERRORS as e:
        raise DamagedBannerError(f"{b.path.name}'s 3D model can't be used ({e}).")
    dest = Path(workdir) / "nsui_banner.bnr"
    dest.write_bytes(cgfx.cbmd_replace(b.data, models))
    return dest, note


def _language_textures(lang):
    """{name: picture} of a language model's textures, which the Home Menu uses in place of the main model's."""
    out = {}
    for name, t in cgfx.textures(lang).items():
        try:
            out[name] = cgfx.read_texture(lang, t)
        except ValueError:
            pass                                             # a lookup or normal-map format: not drawn
    return out


def scene(path, title, year, font_file=None, picture=None):
    """The banner's 3D parts ready to draw: the main model and the first language model, with this game's plate
    and picture where prepare() would put them."""
    b = Banner(path)
    try:
        overrides, _ = b.changes(title, year, font_file, picture)
        lang = b.language_model()
        textures = {**(_language_textures(lang) if lang else {}), **overrides}
        parts = model3d.textured(bytes(b.common), textures)
        if lang:
            parts += model3d.textured(bytes(lang), overrides)
    except MODEL_ERRORS as e:
        raise DamagedBannerError(f"{b.path.name}'s 3D model can't be read ({e}).")
    return parts


def preview_image(path, title, year, size=model3d.VIEW, yaw=0.0, font_file=None, picture=None):
    """A picture of the banner's 3D model (frame or console + TV) and plate, as prepare() would make it, for the
    app's preview."""
    parts = scene(path, title, year, font_file, picture)
    if not parts:
        raise NSUIError("There's no 3D model in this banner to show.")
    return model3d.render(parts, yaw, size)
