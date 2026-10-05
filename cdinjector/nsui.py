"""Banners and icons exported from NSUI (New Super Ultimate Injector for 3DS).

NSUI can't make CIAs from Sega CD or PC Engine CD games, but it can from cartridge games (Genesis, TurboGrafx, GBA
and others). Its "export banner / icon" gives a 3D banner (`.bin`, a 3DS banner) and an icon (`.bin`, a 3DS icon)
that this app can put on a CD game's CIA instead of its own. Two kinds of NSUI banner are understood:

* "3D frame with color": the game's picture in a 3D frame, with the Virtual Console title plate below. Such a
  banner works as a template for any number of games: this app puts the game's picture in the frame and the game's
  title and year on the plate. The frame (its 3D model, colour and movement), the plate's badge and the sound are
  NSUI's, byte for byte.
* 3D console + TV: used exactly as NSUI made it, with one repair. NSUI leaves the title plate blank in some exports
  (the PC Engine ones); when it's blank, this app draws it with the game's title and year.

Either way, only the main 3D model's block of the file is rewritten; every language model and the sound keep their
bytes.

A 3DS banner (CBMD) is a header, a main 3D model (LZ11-compressed CGFX), up to 30 language-specific models, and a
sound. The main model and the language model of the current system language are both drawn by the Home Menu. In
NSUI's PC Engine banner the main model holds the TV and the plate and the language models hold the console; its
frame banners have only the main model.
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
    """(plate, picture): the names of the title plate's texture (256 x 64 luminance + alpha, on the part that always
    faces the camera) and of the frame's picture (full colour, on a single rectangle; None in a console + TV
    banner). plate is None when the model has no such plate."""
    texs = cgfx.textures(cg)
    plate = picture = None
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
    return plate, picture


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
        self.plate = self.picture = None
        try:
            self.common = bytearray(cgfx.lz11_decompress(d[self.common_off:self.common_end]))
            if bytes(self.common[:4]) != b"CGFX":
                raise DamagedBannerError(f"{name}'s 3D model isn't valid.")
            if require_nsui:
                self.plate, self.picture = _parts(bytes(self.common))
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
        ends = sorted(self.lang_offs + ([self.cwav_off] if self.cwav_off else []) + [len(self.data)])
        for start in self.lang_offs:
            end = min(e for e in ends if e > start)
            try:
                block = cgfx.lz11_decompress(self.data[start:end])
            except ValueError as e:
                raise DamagedBannerError(f"{self.path.name} is damaged: {e}.")
            if block[:4] != b"CGFX":
                raise DamagedBannerError(f"{self.path.name} has a language model that isn't valid.")
        return self

    def language_model(self):
        """The first language-specific model, decompressed, or None."""
        if not self.lang_offs:
            return None
        start = self.lang_offs[0]
        later = sorted(o for o in self.lang_offs + [self.cwav_off] if o > start)
        try:
            return cgfx.lz11_decompress(self.data[start:later[0] if later else len(self.data)])
        except ValueError:
            return None

    def texture(self, name):
        return cgfx.read_texture(self.common, cgfx.textures(bytes(self.common))[name])

    def plate_blank(self):
        """True when the title plate has nothing on it (one flat value), as in some NSUI exports."""
        (l0, l1), (a0, a1) = self.texture(self.plate).getextrema()
        return l0 == l1 and a0 == a1

    def changes(self, title, year, font_file=None, picture=None):
        """{texture name: new picture} for this game, and a note saying what they are (None for no change).
        A frame banner gets the game's title on its plate, and the game's picture in the frame when there is one; a
        console + TV banner gets a whole plate only when its own is blank."""
        if self.is_frame:
            new = {self.plate: retitled_plate(self.texture(self.plate), title, year, font_file)}
            if picture is not None:
                new[self.picture] = framed_picture(self.texture(self.picture), picture)
                return new, "your picture and title added"
            return new, "title added"
        if self.plate_blank():
            return {self.plate: plate_texture(title, year, font_file)}, "title plate added"
        return {}, None


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


def prepare(path, title, year, workdir, font_file=None, picture=None):
    """The banner file to put in the CIA: (path, note). note says what was added for this game (see
    Banner.changes), or is None when the banner is used untouched. Only the main model's block of the file is
    rewritten; the language models and the sound keep their bytes."""
    b = Banner(path).validate()
    try:
        new, note = b.changes(title, year, font_file, picture)
        if not new:
            return Path(path), None
        cg = bytearray(b.common)
        texs = cgfx.textures(bytes(cg))
        for name, img in new.items():
            if texs[name]["fmt"] == cgfx.PICA_RGBA8:
                cgfx.write_rgba8(cg, texs[name], img)
            else:
                cgfx.write_texture(cg, texs[name], img)
    except MODEL_ERRORS as e:
        raise DamagedBannerError(f"{b.path.name}'s 3D model can't be used ({e}).")
    dest = Path(workdir) / "nsui_banner.bnr"
    dest.write_bytes(cgfx.cbmd_replace_common(b.data, cg))
    return dest, note


def scene(path, title, year, font_file=None, picture=None):
    """The banner's 3D parts ready to draw: the main model and the first language model, with this game's plate
    and picture where prepare() would put them."""
    b = Banner(path)
    try:
        overrides, _ = b.changes(title, year, font_file, picture)
        parts = model3d.textured(bytes(b.common), overrides)
        lang = b.language_model()
        if lang:
            parts += model3d.textured(bytes(lang), overrides)
    except MODEL_ERRORS as e:
        raise DamagedBannerError(f"{b.path.name}'s 3D model can't be read ({e}).")
    return parts


def preview_image(path, title, year, size=model3d.VIEW, yaw=0.0, font_file=None, picture=None):
    """A picture of the banner's 3D model (frame or console + TV) and plate for the app's preview."""
    parts = scene(path, title, year, font_file, picture)
    if not parts:
        raise NSUIError("There's no 3D model in this banner to show.")
    return model3d.render(parts, yaw, size)


def sibling(path):
    """NSUI names its exports <game>_banner.bin and <game>_icon.bin: the other file of the pair, if it's there."""
    p = Path(path)
    for a, b in (("_banner", "_icon"), ("_icon", "_banner")):
        if p.stem.lower().endswith(a):
            other = p.with_name(p.stem[:-len(a)] + b + p.suffix)
            if other.is_file():
                return other
    return None
