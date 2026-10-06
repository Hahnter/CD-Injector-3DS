"""Icons, banners and the banner sound. Everything here is drawn or synthesised
by this program; no third-party artwork or audio is used."""

import math
import shutil
import struct
import wave
from pathlib import Path

from PIL import Image as _Image

from . import cgfx, model3d
from .model3d import BACKGROUND
from .resources import font_path, font_path_rounded, official_font, run_tool, tool

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
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


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


# ------------------------------------------------------------------------------------------------ the title plate
# The plate is drawn on the 256 x 64 grid of the plate texture in NSUI's banners. Every position below was measured
# from an NSUI banner and from the 3DS's own screen, so a CD game's plate matches the GBA, NES and Genesis ones beside
# it on the Home Menu.
PLATE_BADGE = (8.0, 7.6, 92.6, 56.3)                   # the gray "Virtual Console" badge
PLATE_WORDS = (("Virtual", (16.6, 16.6, 76.4, 31.4)),  # the ink box of each word of the white lettering
               ("Console", (15.6, 32.6, 86.4, 48.4)))
PLATE_TEXT_X, PLATE_TEXT_W = 173, 152                  # the title and year are centred here, at most this wide
PLATE_TITLE_Y = 22.5                                   # the middle of the title's lines
PLATE_YEAR_BASELINE = 57.0
PLATE_YEAR_SIZE = 14.67                                # 11 pt, as NSUI writes it
PLATE_INK = (32, 32, 32, 255)
# Title sizes, largest first, with the most lines each may take: 11 pt on one or two lines, 8.5 pt on three (NSUI's
# own sizes), then smaller still for very long titles.
TITLE_SIZES = ((14.67, 2), (11.33, 3), (10.0, 3), (9.0, 3), (8.0, 3))
LINE_PITCH = 1.15                                      # line spacing, in font sizes


def _wordmark(layer, S):
    """The white slanted "Virtual / Console" lettering on the badge, drawn onto `layer` (256 x 64 units at S x)."""
    from PIL import Image, ImageDraw, ImageFont
    path = font_path_rounded()
    if not path:
        return
    big = 160
    f = ImageFont.truetype(path, big)
    for text, (x0, y0, x1, y1) in PLATE_WORDS:
        tmp = Image.new("L", (big * (len(text) + 2), big * 2), 0)
        ImageDraw.Draw(tmp).text((big, big // 2), text, font=f, fill=255, stroke_width=big // 30, stroke_fill=255)
        tmp = tmp.transform(tmp.size, Image.AFFINE, (1, 0.2, -0.2 * big, 0, 1, 0), resample=Image.BICUBIC)
        tmp = tmp.crop(tmp.getbbox())                   # slanted, then stretched over the word's measured ink box
        mask = tmp.resize((round((x1 - x0) * S), round((y1 - y0) * S)), Image.LANCZOS)
        layer.paste((255, 255, 255, 255), (round(x0 * S), round(y0 * S)), mask)


def _plate_body(S):
    """The plate without its text: a two-tone rim (light top and left, darker right and bottom), a white face that
    turns a little gray towards the bottom, and the gray badge with its lettering."""
    from PIL import Image
    W, H = 256 * S, 64 * S
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for k, shade in enumerate((150, 160, 174)):          # darker towards the right and bottom edges
        out.paste((shade,) * 3 + (255,), (0, 0), _rounded_mask((W, H), (0, S, (256 - k) * S - 1, (63 - k) * S - 1), 6 * S))
    out.paste((201, 201, 201, 255), (0, 0), _rounded_mask((W, H), (0, S, 252 * S - 1, 60 * S - 1), 6 * S))
    column = Image.new("L", (1, H))
    column.putdata([round(255 - max(0.0, (y + 0.5) / S - 20.5) * 1.03) for y in range(H)])
    face = Image.merge("RGB", (column,) * 3).resize((W, H), Image.NEAREST)
    out.paste(face, (0, 0), _rounded_mask((W, H), (4 * S, 4 * S, 252 * S - 1, 60 * S - 1), 3 * S))
    x0, y0, x1, y1 = PLATE_BADGE
    out.paste((140, 140, 140, 255), (0, 0),
              _rounded_mask((W, H), (round(x0 * S), round(y0 * S), round(x1 * S) - 1, round(y1 * S) - 1), 5 * S))
    _wordmark(out, S)
    return out


def _wrap(draw, words, font, width):
    """Greedy word wrap, as NSUI does it: each line takes as many words as fit."""
    lines, line = [], ""
    for word in words:
        trial = f"{line} {word}" if line else word
        if line and draw.textlength(trial, font=font) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


def plate_title_layout(title, S=1, font_file=None):
    """(font, lines) for the title on the plate. Like NSUI: the title is wrapped at 11 pt; one or two lines stay at
    11 pt, and three lines keep those line breaks at 8.5 pt. Longer titles take the largest smaller size that fits."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    words, width = title.split() or [""], PLATE_TEXT_W * S
    f = _font(TITLE_SIZES[0][0] * S, True, font_file)
    lines = _wrap(d, words, f, width)
    if len(lines) == 3 and all(d.textlength(t, font=f) <= width for t in lines):
        return _font(TITLE_SIZES[1][0] * S, True, font_file), lines
    for size, most in TITLE_SIZES:
        f = _font(size * S, True, font_file)
        lines = _wrap(d, words, f, width)
        if len(lines) <= most and all(d.textlength(t, font=f) <= width for t in lines):
            return f, lines
    lines = _wrap(d, words, f, width)                   # too long even then: shorten what doesn't fit
    lines = lines[:2] + [" ".join(lines[2:])] if len(lines) > 3 else lines
    return f, [_fit_text(d, t, width, [f.size], custom=font_file)[1] if d.textlength(t, font=f) > width else t
               for t in lines]


# Nintendo's own plates, measured from official Virtual Console banners: a title that fits on one line has capitals
# 12 px tall on baseline 29, with "Released: <year>" under it in 11 px capitals on baseline 47; a longer title takes
# two lines of 10 px capitals on baselines 21 and 37, with the year line in 10 px capitals on baseline 52. A line
# that's too wide is squeezed rather than made smaller, and the year line is spaced out ("Released: 1999" is 130 px
# wide at 11 px). The ink is a softer gray than NSUI's.
OFFICIAL_ONE_LINE = (((12, 29),), (11, 47))            # ((cap height, baseline) of each title line), year line
OFFICIAL_TWO_LINES = (((10, 21), (10, 37)), (10, 52))
OFFICIAL_YEAR_WIDTH = 130 / 11                         # the width of "Released: 1999" per pixel of cap height
OFFICIAL_INK = (50, 50, 50, 255)
OFFICIAL_SQUEEZE = 0.8                                 # how far a one-line title is squeezed before it takes two
PLATE_STYLES = ("nsui", "official")


def _font_for_caps(cap, font_file):
    """The plate font at the size whose capitals are `cap` pixels tall (whatever the font's proportions)."""
    f = _font(100, True, font_file)
    return _font(cap * 100 / max(1, -f.getbbox("H", anchor="ls")[1]), True, font_file)


def _line_mask(text, font, tracking=0.0):
    """(mask, baseline, width) of one line of text: its ink as an L picture, the baseline's height in it and the
    line's advance width. `tracking` is extra space after each character but the last."""
    from PIL import Image, ImageDraw
    size = max(1, round(font.size))
    advances = [font.getlength(ch) for ch in text] if tracking else [font.getlength(text)]
    width = sum(advances) + tracking * max(0, len(text) - 1)
    mask = Image.new("L", (round(width) + 2 * size, 2 * size), 0)
    d = ImageDraw.Draw(mask)
    base = round(1.4 * size)
    if tracking:
        x = size
        for ch, adv in zip(text, advances):
            d.text((x, base), ch, font=font, fill=255, anchor="ls")
            x += adv + tracking
    else:
        d.text((size, base), text, font=font, fill=255, anchor="ls")
    return mask.crop((size, 0, size + max(1, round(width)), mask.height)), base, width


def _two_lines(words, measure):
    """The title split in two the way Nintendo's plates do it: after a colon if there is one; otherwise the split
    whose wider line is narrowest, the second line not narrower than the first if that can be."""
    for i in range(1, len(words)):
        if words[i - 1].endswith(":"):
            return [" ".join(words[:i]), " ".join(words[i:])]
    splits = [([" ".join(words[:i]), " ".join(words[i:])]) for i in range(1, len(words))]
    if not splits:
        return [" ".join(words)]
    bottom_heavy = [s for s in splits if measure(s[1]) >= measure(s[0])]
    return min(bottom_heavy or splits, key=lambda s: max(measure(s[0]), measure(s[1])))


def official_text(title, year, S=4, font_file=None):
    """The title and "Released: <year>" laid out as on Nintendo's own Virtual Console plates (see OFFICIAL_ONE_LINE),
    on a transparent 256 x 64 (x S) layer. With no font chosen, the bundled look-alike of Nintendo's Rodin is used."""
    from PIL import Image
    font_file = font_file or official_font()
    layer = Image.new("RGBA", (256 * S, 64 * S), (0, 0, 0, 0))
    width = PLATE_TEXT_W * S

    def place(text, cap, baseline, tracking_for=None):
        f = _font_for_caps(cap * S, font_file)
        tracking = 0.0
        if tracking_for:                                # spaced out like Nintendo's "Released: 1999"
            natural = f.getlength(tracking_for)
            tracking = max(0.0, (OFFICIAL_YEAR_WIDTH * cap * S - natural) / max(1, len(tracking_for) - 1))
        mask, base, w = _line_mask(text, f, tracking)
        if w > width:                                   # too wide: squeezed, as Nintendo does
            mask = mask.resize((round(width), mask.height), Image.LANCZOS)
            w = width
        layer.paste(OFFICIAL_INK, (round(PLATE_TEXT_X * S - w / 2), round(baseline * S - base)), mask)

    words = title.split()
    one = _font_for_caps(12 * S, font_file)
    if not words or one.getlength(title.strip()) * OFFICIAL_SQUEEZE <= width:
        lines, (titles, (year_cap, year_base)) = [" ".join(words)], OFFICIAL_ONE_LINE
    else:
        two = _font_for_caps(10 * S, font_file)
        lines = _two_lines(words, two.getlength)
        titles, (year_cap, year_base) = OFFICIAL_TWO_LINES
    for text, (cap, baseline) in zip(lines, titles):
        if text:
            place(text, cap, baseline)
    place("Released: " + (year or "Unknown"), year_cap, year_base, tracking_for="Released: 1999")
    return layer


def plate_text(title, year, S=4, font_file=None, style="nsui"):
    """The title and "Released: <year>" in the plate's ink on a transparent 256 x 64 (x S) layer, laid out as NSUI
    does it, or with style="official" as on Nintendo's own plates (see official_text)."""
    from PIL import Image, ImageDraw
    if style == "official":
        return official_text(title, year, S, font_file)
    layer = Image.new("RGBA", (256 * S, 64 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f, lines = plate_title_layout(title, S, font_file)
    cap = -f.getbbox("H", anchor="ls")[1]               # lines are placed by their capital letters, like NSUI's
    pitch = LINE_PITCH * f.size
    for i, text in enumerate(lines):
        middle = PLATE_TITLE_Y * S + (i - (len(lines) - 1) / 2) * pitch
        d.text((PLATE_TEXT_X * S, middle + cap / 2), text, font=f, fill=PLATE_INK, anchor="ms")
    fy, released = _fit_text(d, "Released: " + (year or "Unknown"), PLATE_TEXT_W * S, [PLATE_YEAR_SIZE * S],
                             custom=font_file)
    d.text((PLATE_TEXT_X * S, PLATE_YEAR_BASELINE * S), released, font=fy, fill=PLATE_INK, anchor="ms")
    return layer


def draw_plate(title, year, S=4, font_file=None, style="nsui"):
    """The Virtual Console title plate, 256 x 64 units drawn at S x: the gray badge with the slanted "Virtual Console"
    lettering on the left, the game's title and "Released: <year>" beside it, laid out as NSUI does it or (style=
    "official") as on Nintendo's own plates. font_file: a font for the title and year (Arial Bold when None, as NSUI
    uses)."""
    plate = _plate_body(S)
    plate.alpha_composite(plate_text(title, year, S, font_file, style))
    return plate


# ------------------------------------------------------------------------------------------------ the 2D banner
# Where everything sits on the banner, in pixels of the 3DS's top screen (400 x 240). These are the places of NSUI's
# "3D frame with color" banner at rest, so a CD game's banner lines up with the cartridge games' on the Home Menu.
BANNER_QUAD = (72, 40, 328, 232)                       # the part of the screen the banner picture covers (256 x 192)
FRAME_BOX = (133.7, 48.2, 266.3, 146.2)
BEZEL_BOX = (144.5, 59.3, 255.5, 132.7)                # the light inner rim around the game's picture
WINDOW_BOX = (148.1, 62.7, 251.9, 129.3)               # the game's picture
PLATE_BOX = (92.2, 163.6, 307.8, 217.5)                # the title plate (its 256 x 64 drawing, shown a little smaller)

# Screenshot sizes of PC Engine and Mega Drive / Sega CD games. A TV showed every one of them 4:3.
CONSOLE_WIDTHS = {256, 320, 336, 352, 512, 640}
CONSOLE_HEIGHTS = set(range(192, 257)) | set(range(384, 513))


def tv_picture(img):
    """A screenshot at a console's own resolution (256 x 224, 320 x 224, 512 x 448 and so on) stretched to the 4:3
    shape a TV gave it; any other picture is returned as it is."""
    from PIL import Image
    w, h = img.size
    if w in CONSOLE_WIDTHS and h in CONSOLE_HEIGHTS and w * 3 != h * 4:
        return img.resize((round(h * 4 / 3), h), Image.LANCZOS)
    return img


def frame_palette(color):
    """(body, edge, line, bezel) of the frame in a colour: the body is the colour itself, the edge is the light
    rounded rim around it, the line is the dark seam before the inner rim, and the bezel is the light inner rim."""
    import colorsys
    body = tuple(int(c) for c in color)
    edge = tuple(min(255, c + 63) for c in body)
    line = tuple(round(c * 0.8) for c in body)
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in body))
    bezel = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s * 0.8, min(1.0, v * 1.5)))
    return body, edge, line, bezel


# The banner's layers, back to front, each at its own depth in the 3D model (model units towards the camera) so that
# the banner stands out of the screen with the 3D slider up, as NSUI's do. NSUI's frame sits at about 1.8 and its
# plate floats at 8; the game's picture is set a little behind the frame's face.
PICTURE_DEPTH, FRAME_DEPTH, PLATE_DEPTH = 1.2, 1.8, 8.0
PLATE_QUAD = (92, 164, 308, 218)                       # PLATE_BOX on whole pixels: the plate is drawn 216 x 54
FRAME_QUAD = (133, 48, 267, 147)                       # FRAME_BOX on whole pixels
PICTURE_QUAD = (145, 60, 255, 132)                     # WINDOW_BOX and a little more, so no gap shows in 3D


def _box_in(b, origin, S, grow=0.0):
    """A box in screen pixels as a box in a layer that starts at `origin`, drawn at S x."""
    return (round((b[0] - origin[0] - grow) * S), round((b[1] - origin[1] - grow) * S),
            round((b[2] - origin[0] + grow) * S) - 1, round((b[3] - origin[1] + grow) * S) - 1)


def _shade(colour, factor):
    return tuple(max(0, min(255, round(c * factor))) for c in colour)


def plate_layer(title, year, font_file=None, plate_style="nsui"):
    """The title plate as a layer: (picture, quad, depth)."""
    from PIL import Image
    w, h = PLATE_QUAD[2] - PLATE_QUAD[0], PLATE_QUAD[3] - PLATE_QUAD[1]
    plate = draw_plate(title, year, 4, font_file, plate_style).resize((w * 4, h * 4), Image.LANCZOS).reduce(4)
    return plate, PLATE_QUAD, PLATE_DEPTH


def _screen_picture(image, system, size, S):
    """The game's picture (a console screenshot stretched to 4:3, filling `size`), or a dark screen with the system's
    name when there's no picture."""
    from PIL import Image, ImageDraw
    if image:
        pic = image if hasattr(image, "size") else Image.open(image)
        return fit_image(tv_picture(pic.convert("RGBA")), size, "cover")
    screen = _gradient(size, (30, 30, 40), (10, 10, 14))
    label = {"pce": "PC ENGINE CD", "segacd": "SEGA CD"}.get(system, "")
    d = ImageDraw.Draw(screen)
    font, label = _fit_text(d, label, size[0] - 12 * S, [s * S for s in (13, 12, 11, 10, 9, 8)])
    d.text((size[0] // 2, size[1] // 2), label, font=font, fill=(200, 200, 210), anchor="mm")
    return screen


def frame_layers(image, title, year, system, color=None, font_file=None, plate_style="nsui"):
    """The "frame" banner as layers, back to front: the game's title screen, the coloured frame around it (its window
    cut out, so the picture looks set into it in 3D) and the Virtual Console title plate, laid out like NSUI's frame
    banners. color: (r, g, b), or None for the system's own colour."""
    from PIL import Image, ImageDraw
    S = 4
    body, edge, line, bezel = frame_palette(color or DEFAULT_COLORS.get(system, (120, 120, 120)))

    # the picture, with a soft shadow along its top edge where the frame overhangs it
    pw, ph = PICTURE_QUAD[2] - PICTURE_QUAD[0], PICTURE_QUAD[3] - PICTURE_QUAD[1]
    picture = _screen_picture(image, system, (pw * S, ph * S), S).convert("RGBA")
    shade = Image.new("L", picture.size, 0)
    top = round((WINDOW_BOX[1] - PICTURE_QUAD[1]) * S)
    for k in range(4 * S):
        ImageDraw.Draw(shade).line((0, top + k, picture.width, top + k), fill=round(110 * (1 - k / (4 * S)) ** 2))
    picture.paste((0, 0, 0, 255), (0, 0), shade)
    picture = picture.reduce(S)

    # the frame: a rounded rim that catches the light, a face that's a little lighter at the top, a dark seam and
    # the light inner rim, with the window cut out
    fw, fh = (FRAME_QUAD[2] - FRAME_QUAD[0]) * S, (FRAME_QUAD[3] - FRAME_QUAD[1]) * S
    frame = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))

    def mask(b, radius, grow=0.0):
        return _rounded_mask((fw, fh), _box_in(b, FRAME_QUAD, S, grow), round(radius * S))

    for k in range(5 * S):
        t = (1 - k / (5 * S)) ** 2
        frame.paste(tuple(round(b + (e - b) * t) for b, e in zip(body, edge)) + (255,), (0, 0),
                    mask(FRAME_BOX, max(10 - k / S, 5), -k / S))
    face = Image.new("RGBA", (fw, fh))
    face.paste(_gradient((fw, fh), _shade(body, 1.08), _shade(body, 0.9)).convert("RGBA"))
    frame.paste(face, (0, 0), mask(FRAME_BOX, 5, -5))
    frame.paste(line + (255,), (0, 0), mask(BEZEL_BOX, 7, 1))
    frame.paste(bezel + (255,), (0, 0), mask(BEZEL_BOX, 6))
    frame.paste((0, 0, 0, 0), (0, 0), mask(WINDOW_BOX, 3))
    frame = frame.reduce(S)

    return [(picture, PICTURE_QUAD, PICTURE_DEPTH), (frame, FRAME_QUAD, FRAME_DEPTH),
            plate_layer(title, year, font_file, plate_style)]


# The CD case: the game's cover in a CD case, and its disc, with the game's title screen printed on it, sliding out
# of the right side. The case takes the cover's shape: square for a jewel case (PC Engine CD and Japanese Mega-CD
# covers), taller for the long cases of American Sega CD games.
CASE_AREA = (100, 46, 300, 156)                        # the case and disc together stay inside this
CASE_DEPTH, DISC_DEPTH = 2.4, 0.9
CASE_SHAPES = (0.62, 1.14)                             # narrowest and widest case, width / height


def _disc(image, system, d, S):
    """The disc, d x d pixels at S x: the title screen printed on it, a silver rim, the clear hub and its hole."""
    from PIL import Image, ImageChops, ImageDraw
    D = d * S
    c = D / 2
    out = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    ring = Image.new("L", (D, D), 0)
    ImageDraw.Draw(ring).ellipse((0, 0, D - 1, D - 1), fill=255)
    silver = _gradient((D, D), (238, 240, 244), (150, 155, 165)).convert("RGBA")
    out.paste(silver, (0, 0), ring)
    label_r = 0.94 * c
    label = _screen_picture(image, system, (round(2 * label_r), round(2 * label_r)), S).convert("RGBA")
    lmask = Image.new("L", label.size, 0)
    ImageDraw.Draw(lmask).ellipse((0, 0, label.width - 1, label.height - 1), fill=255)
    hub = 0.36 * c
    ImageDraw.Draw(lmask).ellipse((label_r - hub, label_r - hub, label_r + hub, label_r + hub), fill=0)
    out.paste(label, (round(c - label_r), round(c - label_r)), lmask)
    d2 = ImageDraw.Draw(out)
    d2.ellipse((c - hub, c - hub, c + hub, c + hub), fill=(205, 210, 218, 255))         # the clear plastic hub
    d2.ellipse((c - 0.3 * c, c - 0.3 * c, c + 0.3 * c, c + 0.3 * c), outline=(170, 175, 185, 255), width=S)
    hole = 0.125 * c
    d2.ellipse((c - hole, c - hole, c + hole, c + hole), fill=(0, 0, 0, 0))
    gloss = Image.new("L", (D, D), 0)                    # a soft sheen across the disc
    ImageDraw.Draw(gloss).polygon([(0, D * 0.25), (D * 0.25, 0), (D * 0.55, 0), (0, D * 0.55)], fill=70)
    gloss = ImageChops.multiply(gloss, ring)
    out.paste((255, 255, 255, 255), (0, 0), gloss)
    return out.reduce(S)


def _cover(cover, size, S):
    """The cover art filling `size` (at S x): cropped a little if its shape is close, else fitted on a blurred,
    darkened copy of itself."""
    from PIL import Image, ImageEnhance, ImageFilter
    img = (cover if hasattr(cover, "size") else Image.open(cover)).convert("RGB")
    w, h = size
    if abs((img.width / img.height) / (w / h) - 1) <= 0.12:
        return fit_image(img, size, "cover")
    back = ImageEnhance.Brightness(fit_image(img, size, "cover").filter(ImageFilter.GaussianBlur(4 * S))).enhance(0.5)
    front = img.resize((max(1, round(img.width * min(w / img.width, h / img.height))),
                        max(1, round(img.height * min(w / img.width, h / img.height)))), Image.LANCZOS)
    back.paste(front, ((w - front.width) // 2, (h - front.height) // 2))
    return back


def cd_case_layers(image, cover, title, year, system, font_file=None, plate_style="nsui"):
    """The "CD case" banner as layers, back to front: the disc (the title screen printed on it) sliding out of the
    case, the case with the game's cover (its box art, or the title screen when there's none), and the title plate."""
    from PIL import Image, ImageDraw
    S = 4
    art = cover or image
    if art:
        a = art if hasattr(art, "size") else Image.open(art)
        shape = min(max(a.width / a.height, CASE_SHAPES[0]), CASE_SHAPES[1])
    else:
        shape = CASE_SHAPES[1]
    ax0, ay0, ax1, ay1 = CASE_AREA
    ch = ay1 - ay0
    cw = round(ch * shape)
    d = round(ch * 0.9)                                  # the disc is a little smaller than the case is tall
    peek = round(d * 0.42)                               # how much of the disc shows beside the case
    left = round((ax0 + ax1) / 2 - (cw + peek) / 2)
    case_quad = (left, ay0, left + cw, ay1)
    disc_top = round((ay0 + ay1) / 2 - d / 2)
    disc_quad = (left + cw + peek - d, disc_top, left + cw + peek, disc_top + d)
    disc = _disc(image, system, d, S)

    W, H = cw * S, ch * S
    case = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dc = ImageDraw.Draw(case)
    dc.rounded_rectangle((0, 0, W - 1, H - 1), 3 * S, fill=(222, 226, 232, 255))          # clear plastic, seen edge on
    dc.rounded_rectangle((S, S, W - 1 - S, H - 1 - S), 2.5 * S, fill=(196, 202, 210, 255))
    hinge = round(max(6, cw * 0.075) * S)                  # the hinge down the left side, with its ridges
    dc.rectangle((S, S, hinge, H - 1 - S), fill=(176, 182, 192, 255))
    for y in range(3 * S, H - 3 * S, 3 * S):
        dc.line((2 * S, y, hinge - S, y), fill=(150, 156, 166, 255), width=S)
    inset = (hinge + S, 2 * S, W - 2 * S, H - 2 * S)
    if art:
        insert = _cover(art, (inset[2] - inset[0], inset[3] - inset[1]), S)
    else:
        insert = _screen_picture(None, system, (inset[2] - inset[0], inset[3] - inset[1]), S)
    case.paste(insert.convert("RGBA"), inset[:2])
    sheen = Image.new("L", (W, H), 0)                       # light on the plastic lid
    ImageDraw.Draw(sheen).polygon([(inset[0], inset[1]), (inset[0] + W * 0.45, inset[1]),
                                   (inset[0] + W * 0.15, inset[3]), (inset[0], inset[3])], fill=34)
    case.paste((255, 255, 255, 255), (0, 0), sheen)
    dc.rectangle(inset, outline=(240, 243, 247, 255), width=S)
    case = case.reduce(S)

    shadow = Image.new("RGBA", disc.size, (0, 0, 0, 0))    # the case's shadow on the disc beside it
    edge = case_quad[2] - disc_quad[0]
    for k in range(6):
        ImageDraw.Draw(shadow).line((edge + k, 0, edge + k, d), fill=(0, 0, 0, round(70 * (1 - k / 6))))
    disc.alpha_composite(Image.composite(shadow, Image.new("RGBA", disc.size), disc.getchannel("A")))

    return [(disc, disc_quad, DISC_DEPTH), (case, case_quad, CASE_DEPTH),
            plate_layer(title, year, font_file, plate_style)]


def flatten(layers):
    """The layers as they look on the top screen, as one BANNER_QUAD-sized picture (for the preview)."""
    from PIL import Image
    qx, qy = BANNER_QUAD[:2]
    out = Image.new("RGBA", (BANNER_QUAD[2] - qx, BANNER_QUAD[3] - qy), (0, 0, 0, 0))
    for img, quad, _depth in layers:
        piece = img.convert("RGBA")
        if piece.size != (quad[2] - quad[0], quad[3] - quad[1]):
            piece = piece.resize((quad[2] - quad[0], quad[3] - quad[1]), Image.LANCZOS)
        out.alpha_composite(piece, (quad[0] - qx, quad[1] - qy))
    return out


def draw_vc_banner(image, title, year, system, color=None, font_file=None, plate_style="nsui"):
    """The frame banner as one 256 x 192 picture (the BANNER_QUAD part of the top screen), for the preview."""
    return flatten(frame_layers(image, title, year, system, color, font_file, plate_style))


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


# bannertool's own banner: a 256 x 128 picture on this part of the top screen (kept for a picture used as it is)
CUSTOM_QUAD = (70, 75, 330, 205)


def _run_makebanner(image, quad, sound, out_bnr, workdir, layers=None):
    """bannertool makes the banner file and its sound; its model then gets `image` in full colour on `quad` (see
    model3d.flat_banner_model), or the pictures of `layers` at their depths (see model3d.layered_banner_model).
    bannertool runs inside `workdir` with plain relative names (see resources.run_tool)."""
    from PIL import Image
    workdir = Path(workdir)
    Image.new("RGBA", (256, 128), (0, 0, 0, 0)).save(workdir / "banner.png")      # replaced below
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
    data = (workdir / out_name).read_bytes()
    start, end = cgfx.cbmd_common(data)
    base = cgfx.lz11_decompress(data[start:end])
    model = model3d.layered_banner_model(base, layers) if layers else model3d.flat_banner_model(base, image, quad)
    Path(out_bnr).write_bytes(cgfx.cbmd_replace_common(data, model))


BANNER_STYLES = ("frame", "cdcase")


def make_banner(image, title, year, system, sound, out_bnr, workdir, style="frame", color=None, font_file=None,
                plate_style="nsui", cover=None):
    """style: 'frame' draws the coloured frame and the Virtual Console plate (default), 'cdcase' the game's cover in
    a CD case with its disc (cover: the box art; the picture is used when there's none), both in layers at different
    depths; 'custom' uses `image` as the whole banner picture, unmodified. Returns the banner as it looks on the
    top screen."""
    if style == "custom":
        if not image:
            raise ValueError("Choose a banner image, or switch to the Virtual Console banner style.")
        img = draw_custom_banner(image)
        _run_makebanner(img, CUSTOM_QUAD, sound, out_bnr, workdir)
        return img
    if style == "cdcase":
        layers = cd_case_layers(image, cover, title, year, system, font_file, plate_style)
    else:
        layers = frame_layers(image, title, year, system, color, font_file, plate_style)
    _run_makebanner(None, None, sound, out_bnr, workdir, layers)
    return flatten(layers)


def on_screen(img, quad, size):
    """The banner picture as it shows on the top screen, for the app's preview: framed like model3d.render's view
    (the screen's full height, centred) and scaled to `size`."""
    from PIL import Image
    w = round(240 * size[0] / size[1])
    screen = Image.new("RGBA", (max(w, 400), 240), BACKGROUND + (255,))
    screen.alpha_composite(img.convert("RGBA"), (quad[0] + (screen.width - 400) // 2, quad[1]))
    left = (screen.width - w) // 2
    return screen.crop((left, 0, left + w, 240)).convert("RGB").resize(size, Image.LANCZOS)


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


ICON_WINDOW = (4, 4, 44, 44)                            # the picture's 40 x 40 window inside the icon's border


def icon_image(image, fit, short_name, system, color=None):
    """The 48 x 48 Home Menu icon: the picture (or the game's initials on the frame colour) inside the silver border
    NSUI gives its Virtual Console icons: two 2-pixel rings, the outer one light at the top and dark at the bottom,
    the inner one the other way round."""
    from PIL import Image, ImageDraw
    icon = Image.new("RGB", (48, 48))
    d = ImageDraw.Draw(icon)
    for y in range(48):
        d.line((0, y, 47, y), fill=(round(250 - 149 * y / 47),) * 3)
    for y in range(2, 46):
        d.line((2, y, 45, y), fill=(round(101 + 89 * (y - 2) / 43),) * 3)
    x0, y0, x1, y1 = ICON_WINDOW
    size = (x1 - x0, y1 - y0)
    if image:
        window = fit_image(image, size, fit)
    else:
        window = _gradient(size, *frame_colors(color or DEFAULT_COLORS.get(system, (120, 120, 120))))
        letters = "".join(w[0] for w in short_name.replace(":", " ").split()[:3]).upper() or "?"
        ImageDraw.Draw(window).text((size[0] // 2, size[1] // 2 + 1), letters,
                                    font=_font(15 if len(letters) < 3 else 12), fill=(255, 255, 255), anchor="mm")
    icon.paste(window, (x0, y0))
    return icon


def make_icon(image, fit, short_name, long_name, publisher, system, out_icn, color=None):
    icon = icon_image(image, fit, short_name, system, color)
    Path(out_icn).write_bytes(smdh_bytes(icon, short_name, long_name, publisher or "Unknown"))
    return icon
