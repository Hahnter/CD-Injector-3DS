"""Making NSUI's console banners from NSUI's own program file.

NSUI (New Super Ultimate Injector for 3DS) is a .NET program that keeps the parts of its banners as resources inside
"New Super Ultimate Injector for 3DS.exe": a 3D model per console (banner_cgfx_mega_drive, banner_cgfx_pce, ...), a
model of the console itself for each language section where a console comes in regional versions
(banner_bcmdl_pc_engine, banner_bcmdl_turbografx_16, ...) and each console's banner tune (banner_wav_gen, ...).
NSUI puts a banner together from them with bannertool, and so does this module, from the copy of NSUI the user
already has: nothing from NSUI comes with this app. The banner made is the one NSUI's "export banner" gives, and it
is used as a template the same way (see nsui.py): each game gets its title and picture on it.

A .NET resource table (a ".resources" stream) is: a header (magic 0xBEEFCACE), the number of resources and their
type names, padding to 8 bytes, a hash and a name offset per resource, the offset of the data section, the names
(UTF-16, each followed by its value's offset in the data section) and the data section. A byte array value is a
type code (0x20, or 0x21 for a stream) and a 32-bit length before its bytes.
"""

import mmap
import os
import shutil
import struct
import wave
from dataclasses import dataclass, field
from pathlib import Path

from . import APP_NAME, cgfx, model3d, nsui
from .resources import run_tool, tool

RESOURCES_MAGIC = b"\xce\xca\xef\xbe"
MAX_RESOURCES = 100000
BYTES, STREAM = 0x20, 0x21
MAX_PROGRAM = 1024 * 1024 * 1024
MAX_PART = 4 * 1024 * 1024                  # NSUI's banner parts are each under 1 MB

# bannertool's options for the language sections' models, in the order of the banner's language slots: Europe
# (English, French, German, Italian, Spanish, Dutch, Portuguese, Russian), Japan, the Americas (English, French,
# Spanish, Portuguese).
LANGUAGE_OPTIONS = ("-eeci", "-efci", "-egci", "-eici", "-esci", "-edci", "-epci", "-erci",
                    "-jjci", "-ueci", "-ufci", "-usci", "-upci")
JAPAN = 8
EVERY = "every"
TUNES = {"segacd": "banner_wav_gen", "pce": "banner_wav_pce"}


@dataclass(frozen=True)
class Console:
    label: str
    systems: tuple
    model: str                                       # the main 3D model
    languages: dict = field(default_factory=dict)    # {slot or EVERY: the console's model for that language section}


CONSOLES = {
    "genesis": Console("Genesis / Mega Drive with a TV", ("segacd",), "banner_cgfx_mega_drive"),
    "pc_engine": Console("PC Engine with a TV", ("pce",), "banner_cgfx_pce", {EVERY: "banner_bcmdl_pc_engine"}),
    "turbografx_16": Console("TurboGrafx-16 with a TV", ("pce",), "banner_cgfx_pce",
                             {EVERY: "banner_bcmdl_turbografx_16"}),
    "by_region": Console("PC Engine on Japanese 3DS systems, TurboGrafx-16 on the others", ("pce",), "banner_cgfx_pce",
                         {EVERY: "banner_bcmdl_turbografx_16", JAPAN: "banner_bcmdl_pc_engine"}),
    "frame": Console("3D frame", ("segacd", "pce"), "banner_cgfx_gba"),
}
DEFAULT_CONSOLE = {"segacd": "genesis", "pce": "pc_engine"}


class NSUIProgramError(nsui.NSUIError):
    """NSUI's program file can't be used to make the banner."""


def consoles_for(system):
    """[(key, label)] of the banners that can be made for `system`'s games, the usual one first."""
    keys = [DEFAULT_CONSOLE[system]] + [k for k, c in CONSOLES.items() if system in c.systems
                                        and k != DEFAULT_CONSOLE[system]]
    return [(k, CONSOLES[k].label) for k in keys]


def banners_folder():
    """Where the banners made from NSUI's program are kept, next to the app's settings."""
    return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME / "nsui banners"


def _7bit(d, p):
    """A 7-bit encoded length (as .NET writes it) at d[p:]: (value, next position)."""
    n = shift = 0
    while True:
        b = d[p]
        p += 1
        n |= (b & 0x7F) << shift
        if b < 0x80:
            return n, p
        shift += 7
        if shift > 28:
            raise ValueError("bad length")


def _table(d, base):
    """[(name, data offset, size)] for each byte-array or stream resource in the resource table at d[base:]."""
    _magic, header_version, skip = struct.unpack_from("<III", d, base)
    if header_version != 1 or skip > 4096:
        return []
    p = base + 12 + skip
    version, count, n_types = struct.unpack_from("<iii", d, p)
    p += 12
    if version != 2 or not 0 < count <= MAX_RESOURCES or not 0 <= n_types <= 1000:
        return []
    for _ in range(n_types):
        n, p = _7bit(d, p)
        p += n
    p += -(p - base) % 8                                  # "PAD" up to a multiple of 8
    positions = struct.unpack_from("<%di" % count, d, p + 4 * count)
    p += 8 * count
    data_section = base + struct.unpack_from("<i", d, p)[0]
    names = p + 4
    out = []
    for pos in positions:
        q = names + pos
        n, q = _7bit(d, q)
        if n > 1024:
            raise ValueError("bad name")
        name = bytes(d[q:q + n]).decode("utf-16-le")
        value = data_section + struct.unpack_from("<i", d, q + n)[0]
        code, v = _7bit(d, value)
        if code in (BYTES, STREAM):
            size = struct.unpack_from("<i", d, v)[0]
            if 0 <= size and v + 4 + size <= len(d):
                out.append((name, v + 4, size))
    return out


def resources(data):
    """[(name, offset, size)] for every byte-array or stream resource in every .NET resource table in `data`."""
    out = []
    at = data.find(RESOURCES_MAGIC)
    while at >= 0:
        try:
            out += _table(data, at)
        except (ValueError, IndexError, struct.error, UnicodeDecodeError):
            pass
        at = data.find(RESOURCES_MAGIC, at + 4)
    return out


def sound_spans(data):
    """[(start, end, sample rate, channels, seconds)] for each 3DS banner sound (CWAV) in `data`."""
    out = []
    at = data.find(b"CWAV\xff\xfe")
    while at >= 0:
        try:
            size = struct.unpack_from("<I", data, at + 0xC)[0]
            if 0x60 <= size <= 4 * 1024 * 1024 and at + size <= len(data) and data[at + 0x40:at + 0x44] == b"INFO":
                rate, _loop_start, samples, _reserved, channels = struct.unpack_from("<5I", data, at + 0x4C)
                if 0 < rate <= 192000:
                    out.append((at, at + size, rate, channels, samples / rate))
        except struct.error:
            pass
        at = data.find(b"CWAV\xff\xfe", at + 4)
    return out


def read_parts(program, names):
    """{name: bytes} of NSUI's resources called `names`, read from its program file without loading all of it."""
    program = Path(program)
    try:
        size = program.stat().st_size
        if not 0 < size <= MAX_PROGRAM:
            raise NSUIProgramError(f"{program.name} can't be NSUI's program file.")
        with open(program, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            table = {}
            for name, offset, length in resources(m):
                table.setdefault(name, (offset, length))
            missing = [n for n in names if n not in table]
            if missing:
                raise NSUIProgramError(f"{program.name} isn't NSUI's program file, or this version of NSUI keeps its "
                                       f"banners differently (it has no {', '.join(missing)}).")
            out = {}
            for n in names:
                offset, length = table[n]
                if length > MAX_PART:
                    raise NSUIProgramError(f"{n} in {program.name} is far too big to be a banner part.")
                out[n] = bytes(m[offset:offset + length])
            return out
    except (OSError, ValueError) as e:
        if isinstance(e, NSUIProgramError):
            raise
        raise NSUIProgramError(f"Couldn't read {program.name}: {e}")


def _check_model(name, data):
    if data[:4] != b"CGFX":
        raise NSUIProgramError(f"NSUI's {name} isn't a 3D model.")
    try:
        cgfx.textures(data)
        model3d.read_meshes(data)
    except nsui.MODEL_ERRORS as e:
        raise NSUIProgramError(f"NSUI's {name} can't be read ({e}).")


def _clear_sample(main, langs):
    """NSUI's models come with a sample game on them (Gradius on the PC Engine's TV, Sonic on the Genesis's, the old
    title on the plate): wipe the plate's text and black out the picture, in the main model and in every language
    model that has its own copy. The picture's place must still be found afterwards, or nothing is wiped."""
    from PIL import Image
    plate, picture, screen = nsui._parts(bytes(main))
    if plate is None or (picture is None and screen is None):
        raise NSUIProgramError("NSUI's banner model isn't laid out as expected (no title plate or picture found).")
    texs = cgfx.textures(bytes(main))
    new = {plate: nsui.wiped_plate(cgfx.read_texture(main, texs[plate]))}
    if picture:
        new[picture] = nsui.framed_picture(cgfx.read_texture(main, texs[picture]), Image.new("RGB", (64, 64)))
    else:
        name, box = screen
        new[name] = nsui.screen_picture(cgfx.read_texture(main, texs[name]), box, Image.new("RGB", (64, 64)))
    cleared = [bytearray(main)] + [bytearray(m) for m in langs]
    for m in cleared:
        nsui._write_textures(m, new)
    if nsui._parts(bytes(cleared[0])) != (plate, picture, screen):
        return main, langs
    return cleared[0], cleared[1:]


def build_banner(program, console, system, out_path, workdir):
    """Make NSUI's `console` banner (a key of CONSOLES) for `system`'s games from NSUI's program file, as NSUI's own
    "export banner" would, and save it at `out_path`. Returns out_path."""
    c = CONSOLES.get(console)
    if c is None or system not in c.systems:
        raise NSUIProgramError("That banner isn't one for this console's games.")
    names = [c.model, TUNES[system]] + sorted(set(c.languages.values()))
    parts = read_parts(program, names)
    for n in [c.model] + list(c.languages.values()):
        _check_model(n, parts[n])
    if parts[TUNES[system]][:4] != b"RIFF" or parts[TUNES[system]][8:12] != b"WAVE":
        raise NSUIProgramError(f"NSUI's {TUNES[system]} isn't a .wav sound.")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    slots = [c.languages.get(i, c.languages.get(EVERY)) for i in range(len(LANGUAGE_OPTIONS))] if c.languages else []
    kinds = sorted(set(slots))
    main, models = _clear_sample(parts[c.model], [parts[k] for k in kinds])
    (workdir / "main.cgfx").write_bytes(main)
    for i, model in enumerate(models):
        (workdir / f"language{i}.cgfx").write_bytes(model)
    (workdir / "tune.wav").write_bytes(parts[TUNES[system]])
    try:
        with wave.open(str(workdir / "tune.wav"), "rb"):
            pass
    except (wave.Error, EOFError) as e:
        raise NSUIProgramError(f"NSUI's {TUNES[system]} can't be read ({e}).")
    cmd = [tool("bannertool"), "makebanner", "-ci", "main.cgfx"]
    for option, kind in zip(LANGUAGE_OPTIONS, slots):
        cmd += [option, f"language{kinds.index(kind)}.cgfx"]
    cmd += ["-a", "tune.wav", "-o", "nsui_banner.bin"]
    run_tool(cmd, cwd=workdir)
    made = workdir / "nsui_banner.bin"
    try:
        b = nsui.Banner(made).validate()
    except nsui.NSUIError as e:
        raise NSUIProgramError(f"The banner made from NSUI's parts isn't right: {e}")
    if len(b.lang_offs) != len(slots):
        raise NSUIProgramError("The banner made from NSUI's parts is missing some of its language sections.")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    part = out_path.with_name(out_path.name + ".part")
    shutil.copyfile(made, part)
    os.replace(part, out_path)
    return out_path
