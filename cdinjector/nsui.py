"""Banners and icons exported from NSUI (New Super Ultimate Injector for 3DS).

NSUI can't make CIAs from Sega CD or PC Engine CD games, but it can from Genesis and TurboGrafx
cartridge games. Its "export banner / icon" gives a 3D console + TV banner (`.bin`, a 3DS banner)
and an icon (`.bin`, a 3DS icon) that this app can put on a CD game's CIA instead of its own.

The banner is used exactly as NSUI made it, with one repair: NSUI leaves the Virtual Console title
plate blank in some exports (the PC Engine ones). When the plate is blank, this app draws it with the
game's title and year. Everything else in the file (the console models, the TV picture, the sound and
every language slot) is copied byte for byte.

A 3DS banner (CBMD) is a header, a main 3D model (LZ11-compressed CGFX), up to 30 language-specific
models, and a sound. The main model and the language model of the current system language are both
drawn by the Home Menu. In NSUI's PC Engine banner the main model holds the TV and the plate and the
language models hold the console.
"""

import struct
from pathlib import Path

from . import banner as bn
from . import cgfx, model3d

PLATE = "COMMON1"
HEADER = 0x88
MAX_BANNER = 4 * 1024 * 1024               # real banners are under 1 MB; this stops a huge file being read into memory
MAX_LANGUAGES = 30


class NSUIError(Exception):
    """The file can't be used as an NSUI banner."""


class DamagedBannerError(NSUIError):
    """The file claims to be a 3DS banner but its structure is broken. Such a file must never end up in a CIA:
    a bad banner can stop the Home Menu from showing the game."""


class Banner:
    """A parsed NSUI banner: the main model, the language-model blocks, and where everything sits in the file."""

    def __init__(self, path, require_nsui=True):
        """Read and check the banner's structure. require_nsui=False accepts any well-formed banner; the default
        also insists on NSUI's console + TV layout (raising the plain NSUIError when it isn't)."""
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
        try:
            self.common = bytearray(cgfx.lz11_decompress(d[self.common_off:self.common_end]))
            if bytes(self.common[:4]) != b"CGFX":
                raise DamagedBannerError(f"{name}'s 3D model isn't valid.")
            texs = cgfx.textures(bytes(self.common)) if require_nsui else {}
        except ValueError as e:
            raise DamagedBannerError(f"{name} is damaged: {e}.")
        if require_nsui and PLATE not in texs:
            raise NSUIError(f"{name} is a 3DS banner, but not a console + TV banner from NSUI.")

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

    def plate_blank(self):
        """True when the title plate has nothing on it (one flat value), as in some NSUI exports."""
        plate = cgfx.read_texture(self.common, cgfx.textures(bytes(self.common))[PLATE])
        (l0, l1), (a0, a1) = plate.getextrema()
        return l0 == l1 and a0 == a1


def plate_texture(title, year, font_file=None):
    """Our Virtual Console plate as the 256x64 luminance + alpha texture the banner uses (hard-edged corners)."""
    from PIL import Image
    plate = bn.draw_plate(title, year, font_file=font_file).resize((256, 64), Image.LANCZOS)
    return Image.merge("LA", (plate.convert("L"), plate.getchannel("A").point(lambda v: 255 if v >= 128 else 0)))


def prepare(path, title, year, workdir, font_file=None):
    """The banner file to put in the CIA: (path, plate_was_added). A banner whose plate is already filled in is
    used untouched. A blank plate is drawn into the main model and only that block of the file is rewritten;
    the language models and the sound keep their bytes."""
    b = Banner(path).validate()
    if not b.plate_blank():
        return Path(path), False
    cg = bytearray(b.common)
    cgfx.write_texture(cg, cgfx.textures(bytes(cg))[PLATE], plate_texture(title, year, font_file))
    comp = cgfx.lz11_compress(bytes(cg))
    old_len = b.common_end - b.common_off
    pad = (-(len(comp) - old_len)) % 32            # keep every later offset where its alignment was
    comp += bytes(pad)
    delta = len(comp) - old_len
    words = list(b.words)
    for i in range(3, HEADER // 4):
        if words[i] and words[i] > b.common_off:
            words[i] += delta
    out = struct.pack("<%dI" % (HEADER // 4), *words) + comp + b.data[b.common_end:]
    dest = Path(workdir) / "nsui_banner.bnr"
    dest.write_bytes(out)
    return dest, True


def scene(path, title, year, font_file=None):
    """The banner's 3D parts ready to draw: the main model and the first language model, with the drawn plate if
    the file's plate is blank."""
    b = Banner(path)
    try:
        overrides = {PLATE: plate_texture(title, year, font_file)} if b.plate_blank() else {}
        parts = model3d.textured(bytes(b.common), overrides)
        lang = b.language_model()
        if lang:
            parts += model3d.textured(bytes(lang), overrides)
    except (ValueError, IndexError, KeyError, struct.error, ZeroDivisionError, OverflowError, MemoryError) as e:
        raise DamagedBannerError(f"{b.path.name}'s 3D model can't be read ({e}).")
    return parts


def preview_image(path, title, year, size=model3d.VIEW, yaw=0.0, font_file=None):
    """A picture of the banner's 3D console + TV + plate for the app's preview."""
    parts = scene(path, title, year, font_file)
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
