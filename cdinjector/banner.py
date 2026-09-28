"""Icons, banners and the banner sound. Everything here is drawn or synthesised
by this program; no third-party artwork or audio is used."""

import math
import shutil
import struct
import wave
from pathlib import Path

from PIL import Image as _Image

from .resources import font_path, font_path_rounded, run_tool, tool

# Pictures come from the user. Anything over about 50 million pixels is refused as a possible decompression bomb
# (a small file that unpacks to gigabytes); a title screen or box art is far smaller.
_Image.MAX_IMAGE_PIXELS = 25_000_000

# The banner's frame colour: each system has a default, and the user can pick any other.
DEFAULT_COLORS = {
    "pce": (236, 120, 40),                      # PC Engine orange
    "segacd": (50, 110, 220),                   # Sega CD blue
}
COLOR_PRESETS = [
    ("Orange", (236, 120, 40)), ("Red", (214, 48, 48)), ("Pink", (232, 96, 160)), ("Purple", (128, 84, 204)),
    ("Blue", (50, 110, 220)), ("Teal", (30, 160, 170)), ("Green", (60, 170, 80)), ("Gold", (226, 178, 40)),
    ("Silver", (150, 155, 165)), ("Black", (52, 52, 58)),
]


def parse_color(text):
    """'#rrggbb' (or 'rrggbb') -> (r, g, b), or None when empty or not a colour."""
    text = (text or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def color_hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def frame_colors(color):
    """(top, bottom) of the frame's vertical gradient for a base colour."""
    return tuple(color), tuple(round(c * 0.62) for c in color)


def _font(size, bold=True, custom=None):
    """The banner's text font: `custom` (a font file the user chose) if it loads, else Arial Bold or the nearest match."""
    from PIL import ImageFont
    if custom:
        try:
            return ImageFont.truetype(str(custom), size)
        except OSError:
            pass
    path = font_path(bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def fit_image(src, size, mode="height", background=(0, 0, 0)):
    """mode: height / width letterbox, cover crops to fill."""
    from PIL import Image
    img = src if hasattr(src, "size") else Image.open(src)
    img = img.convert("RGBA")
    w, h = size
    scale = {"cover": max(w / img.width, h / img.height), "width": w / img.width}.get(mode, h / img.height)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", size, background + (255,))
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2), img)
    return canvas.convert("RGB")


def _gradient(size, top, bottom):
    from PIL import Image
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(w):
            px[x, y] = c
    return img


def _fit_text(draw, text, max_w, sizes, bold=True, custom=None):
    for s in sizes:
        f = _font(s, bold, custom)
        if draw.textlength(text, font=f) <= max_w:
            return f, text
    f = _font(sizes[-1], bold, custom)
    while text and draw.textlength(text + "...", font=f) > max_w:
        text = text[:-1]
    return f, text.rstrip() + "..."


def _rounded_mask(size, box, radius):
    from PIL import Image, ImageDraw
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius, fill=255)
    return m


def _wordmark(layer, S):
    """The white slanted "Virtual / Console" lettering on the badge, drawn onto `layer` (256x64 units at S x)."""
    from PIL import Image, ImageDraw, ImageFont
    path = font_path_rounded()
    if not path:
        return
    target = 69 * S                                    # "Console" is about 69 units wide
    size = 200
    while size > 8 and ImageDraw.Draw(layer).textlength("Console", font=ImageFont.truetype(path, size)) + 1.5 * S > target:
        size -= 1
    f = ImageFont.truetype(path, size)
    shear = 0.2
    tall = 1.14                                        # the real lettering is taller than this font
    for text, cy in (("Virtual", 22.5), ("Console", 40.5)):
        tmp = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((16 * S, int(cy * S)), text, font=f, fill=(255, 255, 255, 255), anchor="lm",
                                 stroke_width=S * 5 // 8, stroke_fill=(255, 255, 255, 255))
        # slant and stretch about the line's own centre so the text keeps its place
        tmp = tmp.transform(tmp.size, Image.AFFINE,
                            (1, shear, -shear * cy * S, 0, 1 / tall, cy * S * (1 - 1 / tall)), resample=Image.BICUBIC)
        layer.alpha_composite(tmp)


def draw_plate(title, year, S=4, font_file=None):
    """The Virtual Console title plate, 256x64 units drawn at S x: a silver-edged white plate, a gray badge with
    the slanted "Virtual Console" lettering on the left, the game's title and "Released: year" centred beside it.
    font_file: a font for the title and year (the official Virtual Console banners use a Rodin-style face)."""
    from PIL import Image, ImageDraw
    W, H = 256 * S, 64 * S
    plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    edge = _gradient((W, H), (222,) * 3, (140,) * 3)                                 # silver rim, darker at the bottom
    plate.paste(edge, (0, 0), _rounded_mask((W, H), (0, 0, W - 1, H - 1), 9 * S))
    inset = 3 * S
    face = _gradient((W, H), (255,) * 3, (226,) * 3)                                  # white, a little gray at the bottom
    plate.paste(face, (0, 0), _rounded_mask((W, H), (inset, inset, W - 1 - inset, H - 1 - inset), 7 * S))
    plate.paste((140, 140, 140, 255), (0, 0), _rounded_mask((W, H), (8 * S, 7 * S, 92 * S, 57 * S), 5 * S))
    _wordmark(plate, S)

    d = ImageDraw.Draw(plate)
    cx, max_w = 172 * S, 154 * S
    ink = (30, 30, 34, 255)
    lines, f = [title], _font(12 * S, True, font_file)
    for size in (14, 13, 12):                          # one line if it fits at a readable size
        f = _font(size * S, True, font_file)
        if d.textlength(title, font=f) <= max_w:
            break
    else:
        words = title.split()
        for size in (14, 13, 12, 11, 10, 9, 8):
            f = _font(size * S, True, font_file)
            best = None
            for i in range(1, len(words)):
                a, b = " ".join(words[:i]), " ".join(words[i:])
                width = max(d.textlength(a, font=f), d.textlength(b, font=f))
                if a.endswith((":", "-")):
                    width *= 0.85
                if best is None or width < best[0]:
                    best = (width, [a, b])
            lines = best[1] if best else [title]
            if all(d.textlength(t, font=f) <= max_w for t in lines):
                break
        if len(lines) == 1:                            # one long word: shorten it
            f, text = _fit_text(d, title, max_w, [11 * S, 10 * S, 9 * S, 8 * S], custom=font_file)
            lines = [text]
    lines = lines[:2]
    line_h = int(f.size * 1.2)
    y = (23 * S if len(lines) == 1 else 21 * S) - (len(lines) - 1) * line_h // 2
    for t in lines:
        d.text((cx, y), t, font=f, fill=ink, anchor="mm")
        y += line_h
    d.text((cx, 51 * S), "Released: " + (year or "Unknown"), font=_font(13 * S, True, font_file), fill=ink, anchor="mm")
    return plate


def draw_vc_banner(image, title, year, system, color=None, font_file=None):
    """256x128 banner: the game's title screen in a frame of the chosen colour (the frame follows the
    picture's shape, so nothing is cropped), with the Virtual Console title plate underneath.
    color: (r, g, b), or None for the system's own colour."""
    from PIL import Image, ImageDraw
    S = 4
    W, H = 256 * S, 128 * S
    top, bottom = frame_colors(color or DEFAULT_COLORS.get(system, (120, 120, 120)))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    aspect = 4 / 3
    if image:
        pic = image if hasattr(image, "size") else Image.open(image)
        aspect = min(2.2, max(1.0, pic.width / pic.height))
    B = 6                                              # bezel width around the screen
    sh = 54                                            # the screen fits a 152 x 54 box
    sw = round(sh * aspect)
    if sw > 152:
        sw, sh = 152, round(152 / aspect)

    def rounded(box, r, fill):
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).rounded_rectangle(box, r, fill=255)
        if hasattr(fill, "size"):
            out.paste(fill, (0, 0), m)
        else:
            out.paste(fill, mask=m)

    # frame body with a soft drop shadow, centred in the space above the plate (with a clear gap before it)
    fx0 = (256 - (sw + 2 * B)) * S // 2
    fy0 = (2 + (66 - (sh + 2 * B)) // 2) * S
    fx1, fy1 = fx0 + (sw + 2 * B) * S, fy0 + (sh + 2 * B) * S
    rounded((fx0 + 2 * S, fy0 + 3 * S, fx1 + 2 * S, fy1 + 3 * S), 10 * S, (0, 0, 0, 90))
    rounded((fx0, fy0, fx1, fy1), 10 * S, _gradient((W, H), top, bottom).convert("RGBA"))
    hl = Image.new("L", (W, H), 0)
    ImageDraw.Draw(hl).rounded_rectangle((fx0 + 3 * S, fy0 + 2 * S, fx1 - 3 * S, fy0 + 10 * S), 7 * S, fill=70)
    out.paste((255, 255, 255, 255), mask=hl)

    # screen
    sx0, sy0, sx1, sy1 = fx0 + B * S, fy0 + B * S, fx1 - B * S, fy1 - B * S
    rounded((sx0 - S, sy0 - S, sx1 + S, sy1 + S), 4 * S, (15, 15, 20, 255))
    screen = (fit_image(image, (sx1 - sx0, sy1 - sy0), "cover") if image
              else _gradient((sx1 - sx0, sy1 - sy0), (30, 30, 40), (10, 10, 14)))
    sm = Image.new("L", (sx1 - sx0, sy1 - sy0), 0)
    ImageDraw.Draw(sm).rounded_rectangle((0, 0, sx1 - sx0 - 1, sy1 - sy0 - 1), 4 * S, fill=255)
    out.paste(screen.convert("RGBA"), (sx0, sy0), sm)
    if not image:
        label = {"pce": "PC ENGINE CD", "segacd": "SEGA CD"}.get(system, "")
        dark = 0.3 * top[0] + 0.59 * top[1] + 0.11 * top[2] < 90          # keep the label readable on a dark frame
        d = ImageDraw.Draw(out)
        font, label = _fit_text(d, label, (sx1 - sx0) - 10 * S, [s * S for s in (11, 10, 9, 8, 7)])  # fits the screen
        d.text(((sx0 + sx1) // 2, (sy0 + sy1) // 2), label, font=font,
               fill=(175, 175, 185, 255) if dark else top + (255,), anchor="mm")

    # the Virtual Console plate, 204 x 51 at the bottom
    pw, ph = 204 * S, 51 * S
    px0, py0 = (W - pw) // 2, H - ph - 3 * S
    plate = draw_plate(title, year, S, font_file).resize((pw, ph), Image.LANCZOS)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 70), (px0, py0 + S), plate.getchannel("A"))
    out.alpha_composite(shadow)
    out.alpha_composite(plate, (px0, py0))
    return out.resize((256, 128), Image.LANCZOS)


def read_smdh_icon(path):
    """The 48x48 icon inside a 3DS icon (SMDH) file: RGB565 in 8x8 tiles, Z-order inside each tile."""
    from PIL import Image
    d = Path(path).read_bytes()
    if d[:4] != b"SMDH" or len(d) < 0x24C0 + 0x1200:
        raise ValueError("not a 3DS icon file")
    img = Image.new("RGB", (48, 48))
    px = img.load()
    p = 0x24C0
    for by in range(0, 48, 8):
        for bx in range(0, 48, 8):
            for i in range(64):
                x = bx + ((i & 1) | ((i >> 1) & 2) | ((i >> 2) & 4))
                y = by + (((i >> 1) & 1) | ((i >> 2) & 2) | ((i >> 3) & 4))
                v = d[p] | (d[p + 1] << 8)
                p += 2
                px[x, y] = ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)
    return img


def draw_custom_banner(image, size=(256, 128)):
    """A user-supplied picture, used as the banner exactly as given (letterboxed to fit)."""
    return fit_image(image, size, "height")


def chime_wav(dest: Path) -> Path:
    """A short two-note chime (synthesised here, 0.9 s)."""
    rate = 32000
    notes = [(0.00, 659.25), (0.12, 987.77)]        # E5, B5
    n = int(rate * 0.9)
    frames = bytearray()
    for i in range(n):
        t = i / rate
        v = 0.0
        for start, freq in notes:
            if t >= start:
                u = t - start
                env = math.exp(-u * 5.0) * min(1.0, u * 200)
                v += env * (math.sin(2 * math.pi * freq * u) + 0.25 * math.sin(4 * math.pi * freq * u))
        s = int(max(-1.0, min(1.0, v * 0.35)) * 32767)
        frames += struct.pack("<hh", s, s)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return Path(dest)


SOUND_TYPES = (".wav", ".bcwav", ".cwav")
MAX_SOUND_SECONDS = 3.0                         # the Home Menu doesn't play a longer banner sound
MAX_CWAV_BYTES = 1024 * 1024


class SoundError(ValueError):
    """The banner sound file can't be used."""


def check_sound(path):
    """Refuse a banner sound that bannertool or the Home Menu can't use, before any work is done."""
    path = Path(path)
    if not path.is_file():
        raise SoundError(f"The banner sound file was not found:{chr(10)}{path}")
    kind = path.suffix.lower()
    if kind not in SOUND_TYPES:
        raise SoundError(f"{path.name} isn't a .wav or .bcwav file.")
    if kind == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                seconds = w.getnframes() / max(1, w.getframerate())
                if w.getsampwidth() not in (1, 2) or w.getnchannels() not in (1, 2):
                    raise SoundError(f"{path.name} must be 8- or 16-bit mono or stereo PCM.")
        except (wave.Error, EOFError, OSError) as e:
            raise SoundError(f"{path.name} isn't a usable .wav file ({e}).")
        if seconds > MAX_SOUND_SECONDS:
            raise SoundError(f"{path.name} is {seconds:.1f} seconds long; a banner sound can be at most "
                             f"{MAX_SOUND_SECONDS:.0f} seconds.")
    else:
        if path.stat().st_size > MAX_CWAV_BYTES:
            raise SoundError(f"{path.name} is too big for a banner sound.")
        with open(path, "rb") as f:
            if f.read(4) != b"CWAV":
                raise SoundError(f"{path.name} isn't a .bcwav file.")
    return path


def _run_makebanner(image, sound, out_bnr, workdir):
    """bannertool runs inside `workdir` with plain relative names (see resources.run_tool)."""
    workdir = Path(workdir)
    image.save(workdir / "banner.png")
    out_name = "banner_out.bnr"
    cmd = [tool("bannertool"), "makebanner", "-i", "banner.png", "-o", out_name]
    if sound:
        kind = Path(sound).suffix.lower()
        shutil.copyfile(check_sound(sound), workdir / ("sound" + kind))
        cmd += ["-ca" if kind in (".bcwav", ".cwav") else "-a", "sound" + kind]
    else:
        chime_wav(workdir / "chime.wav")
        cmd += ["-a", "chime.wav"]
    run_tool(cmd, cwd=workdir)
    shutil.move(str(workdir / out_name), str(out_bnr))


def make_banner(image, title, year, system, sound, out_bnr, workdir, style="vc", color=None, font_file=None):
    """style: 'vc' draws the coloured-frame + Virtual Console plate (default);
    'custom' uses `image` as the whole banner picture, unmodified."""
    if style == "custom":
        if not image:
            raise ValueError("Choose a banner image, or switch to the Virtual Console banner style.")
        img = draw_custom_banner(image)
    else:
        img = draw_vc_banner(image, title, year, system, color, font_file)
    _run_makebanner(img, sound, out_bnr, workdir)
    return img


SMDH_BYTES = 0x36C0


def _tiled_rgb565(img):
    """An RGB picture as PICA200 RGB565 tiles: 8x8 blocks in row order, Z-order pixels inside each block (the same
    bytes bannertool writes)."""
    w, h = img.size
    px = img.load()
    out = bytearray(w * h * 2)
    for y in range(h):
        for x in range(w):
            i = (((y >> 3) * (w >> 3) + (x >> 3)) << 6) + ((x & 1) | ((y & 1) << 1) | ((x & 2) << 1)
                                                          | ((y & 2) << 2) | ((x & 4) << 2) | ((y & 4) << 3))
            r, g, b = px[x, y][:3]
            struct.pack_into("<H", out, i * 2, ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return bytes(out)


def _utf16_field(text, chars):
    """`text` as UTF-16 in a field of `chars` 16-bit units, cut at a whole character and zero-padded (always
    leaving room for the terminating zero)."""
    data = b""
    for ch in text:
        enc = ch.encode("utf-16-le")
        if len(data) + len(enc) > (chars - 1) * 2:
            break
        data += enc
    return data.ljust(chars * 2, b"\0")


def smdh_bytes(icon, short_name, long_name, publisher):
    """A 3DS icon file (SMDH) for a 48x48 RGB picture, written here rather than by bannertool so that titles in any
    language come out right (bannertool only sees the Windows code page, which turns Japanese titles into "???").
    For plain ASCII titles of up to 32 characters the result is byte for byte what `bannertool makesmdh` makes
    with its defaults: every language slot filled, region free, visible + allow 3D + record usage."""
    from PIL import Image
    icon = icon.convert("RGB")
    if icon.size != (48, 48):
        icon = icon.resize((48, 48), Image.LANCZOS)
    small = Image.new("RGB", (24, 24))
    big, sp = icon.load(), small.load()
    for y in range(24):
        for x in range(24):
            quad = [big[2 * x + ox, 2 * y + oy] for oy in (0, 1) for ox in (0, 1)]
            sp[x, y] = tuple(sum(p[c] for p in quad) // 4 for c in range(3))
    title = _utf16_field(short_name, 0x40) + _utf16_field(long_name, 0x80) + _utf16_field(publisher, 0x40)
    settings = (bytes(16) + struct.pack("<IIQIHHII", 0x7FFFFFFF, 0, 0, 0x0001 | 0x0004 | 0x0100, 0, 0, 0, 0))
    data = b"SMDH" + struct.pack("<HH", 0, 0) + title * 16 + settings + bytes(8) + _tiled_rgb565(small) \
        + _tiled_rgb565(icon)
    assert len(data) == SMDH_BYTES
    return data


def make_icon(image, fit, short_name, long_name, publisher, system, out_icn, color=None):
    from PIL import ImageDraw
    if image:
        icon = fit_image(image, (48, 48), fit)
    else:
        top, bottom = frame_colors(color or DEFAULT_COLORS.get(system, (120, 120, 120)))
        icon = _gradient((48, 48), top, bottom)
        letters = "".join(w[0] for w in short_name.replace(":", " ").split()[:3]).upper() or "?"
        ImageDraw.Draw(icon).text((24, 25), letters, font=_font(18 if len(letters) < 3 else 14),
                                  fill=(255, 255, 255), anchor="mm")
    Path(out_icn).write_bytes(smdh_bytes(icon, short_name, long_name, publisher or "Unknown"))
    return icon
