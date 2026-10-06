"""The CIA build pipeline shared by the app and the command line."""

import os
import re
import shutil
import tempfile
import unicodedata
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import banner as bn
from . import gameinfo, nsui
from .bios import BiosError, find_bios
from .disc import CUE_FILE, SYSTEMS, DiscError, read_cue
from .resources import core_dir, run_tool, tool


class BuildError(Exception):
    pass


@dataclass
class BuildOptions:
    game: Path                        # the .cue, or the folder that contains it
    bios: Path = None                 # BIOS file/folder; None = look next to the game
    title: str = ""                   # "" = from the .cue file name
    publisher: str = ""
    year: str = ""
    system: str = ""                  # "" = detect from the disc
    out_dir: Path = None              # None = next to the game folder
    image: Path = None                # title screen / box art for the banner and icon
    icon_fit: str = "height"
    icon_file: Path = None            # optional ready-made .icn / .smdh, or a picture
    banner_file: Path = None          # optional ready-made .bnr, or a picture
    frame_color: tuple = None         # (r, g, b) of the banner's frame; None = the system's own colour
    sound_file: Path = None           # optional .wav / .bcwav banner sound
    plate_font: Path = None           # optional font file for the title plate's text
    lookup: bool = False              # fill in an empty title, publisher, year and picture when the disc is recognised
    pictures_dir: Path = None         # where to look for the picture (None: RetroArch's thumbnails, if found)
    download_picture: bool = False    # with lookup: download the picture from libretro's thumbnails if none is found
    info: dict = field(default_factory=dict)


def clean_title(stem):
    title = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", stem).strip()
    return title or stem


RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
PICTURE_ERRORS = (OSError, ValueError, SyntaxError, Image.DecompressionBombError)   # Pillow can raise any of these
ICON_BYTES = 0x36C0                         # the size of every 3DS icon (SMDH) file


def printable(text, limit=200):
    """`text` without control or invisible characters (odd spaces become plain ones), for anything that ends up in a
    file name or in the 3DS's title fields."""
    text = "".join(" " if unicodedata.category(ch) == "Zs" else ch for ch in str(text))
    return "".join(ch for ch in text if ch.isprintable())[:limit].strip()


def safe_name(title):
    """A title turned into a safe file name: no path separators or characters Windows forbids, no control
    characters, not a reserved device name (CON, NUL, COM1...), not empty, and not too long."""
    name = re.sub(r'[<>:"/\\|?*]+', "", printable(title, 120)).strip().rstrip(". ")
    if name.split(".")[0].strip().upper() in RESERVED_NAMES:
        name = "_" + name
    return name or "game"


def ascii_name(title, uid):
    """The game's name inside the CIA (its .cue there, and so its save folder on the SD card). It is plain ASCII,
    the only kind of name tested on a 3DS: accents are dropped (Pokémon becomes Pokemon), and a title with no
    Latin letters or digits at all becomes "Game <id>". For an ASCII title it is simply safe_name(title)."""
    plain = printable(unicodedata.normalize("NFKD", str(title)).encode("ascii", "ignore").decode("ascii"))
    if not any(ch.isalnum() for ch in plain):
        return f"Game {uid:05X}"
    return safe_name(plain)


def romfs_track_names(tracks):
    """{track file: its name inside the CIA}. ASCII names are kept, so the .cue goes in unchanged. If any name isn't
    ASCII, every track is renamed "Track NN.bin" and the .cue is rewritten to match (see rewrite_cue)."""
    if all(t.isascii() for t in tracks):
        return {t: t for t in tracks}
    names = {}
    for i, t in enumerate(tracks, 1):
        ext = Path(t).suffix.lower()
        names[t] = f"Track {i:02d}" + (ext if re.fullmatch(r"\.[a-z0-9]{1,5}", ext) else ".bin")
    return names


def rewrite_cue(text, names):
    """The .cue sheet with each FILE line pointing at the track's new name; every other line is left as it was."""
    out = []
    for line in text.splitlines(keepends=True):
        m = CUE_FILE.match(line)
        if m:
            name = Path((m.group(1) or m.group(2)).replace("\\", "/")).name
            start, end = (m.start(1) - 1, m.end(1) + 1) if m.group(1) else m.span(2)
            line = line[:start] + '"' + names[name] + '"' + line[end:]
        out.append(line)
    return "".join(out)


def unique_id(system, title):
    # Stable per game so rebuilding updates the same Home Menu title.
    # 0xE0000-0xEFFFF is used by homebrew only.
    return 0xE0000 + (zlib.crc32(f"{system}:{title}".encode()) & 0xFFFF)


def resolve_cue(game: Path) -> Path:
    game = Path(game)
    if game.is_dir():
        cues = sorted(game.glob("*.cue"))
        if not cues:
            raise BuildError(f"No .cue file in {game}.")
        if len(cues) > 1:
            raise BuildError(f"{game} has several .cue files; choose one of them.")
        return cues[0]
    return game


def locate_bios(system, bios, cue: Path):
    """Use the given BIOS, or search near the game (its folder and two levels up)."""
    if bios:
        return find_bios(system, bios)
    searched = []
    for folder in (cue.parent, cue.parent.parent, cue.parent.parent.parent):
        # folders named bios are searched fully; the others only at the top level
        for cand, recursive in ((folder / "bios", True), (folder / "BIOS", True), (folder, False)):
            key = (str(cand).lower(), recursive)
            if cand.is_dir() and key not in searched:
                searched.append(key)
                try:
                    return find_bios(system, cand, recursive)
                except BiosError:
                    pass
    raise BiosError(f"No {SYSTEMS[system]['bios_hint']} found near the game. Choose the BIOS file or folder.")


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def is_picture(path):
    return Path(path).suffix.lower() in IMAGE_EXTS


def _read_ready_made(path, magic, what):
    """Validate a ready-made icon (SMDH) or banner (CBMD) file, e.g. one exported from NSUI."""
    path = Path(path)
    if not path.is_file():
        raise BuildError(f"The {what} file was not found:" + chr(10) + str(path))
    size = path.stat().st_size
    if size > (ICON_BYTES if what == "icon" else nsui.MAX_BANNER):
        raise BuildError(f"{path.name} is too big to be a 3DS {what} file.")
    with open(path, "rb") as f:
        head = f.read(4)
    if head != magic:
        raise BuildError(f"{path.name} isn't a 3DS {what} file.")
    if what == "icon" and size != ICON_BYTES:
        raise BuildError(f"{path.name} isn't a complete 3DS icon file.")
    return path


def check(opt: BuildOptions):
    """Everything that can be checked before building. Returns (disc, system, bios files, notes)."""
    try:
        cue = resolve_cue(opt.game)
        disc = read_cue(cue)
    except (DiscError, OSError) as e:
        raise BuildError(str(e))
    system = opt.system or disc.system
    if system not in SYSTEMS:
        raise BuildError("This doesn't look like a PC Engine CD or Sega CD disc. "
                         "If it is, choose the system manually.")
    if opt.system and disc.system and opt.system != disc.system:
        raise BuildError(f"This disc looks like a {SYSTEMS[disc.system]['name']} game, "
                         f"but {SYSTEMS[opt.system]['name']} is selected.")
    try:
        bios_files, notes = locate_bios(system, opt.bios, cue)
    except BiosError as e:
        raise BuildError(str(e))
    return disc, system, bios_files, notes


def _check_picture(path, what):
    """Open and fully decode a picture the user chose, so a missing, damaged or oversized one is reported at once."""
    path = Path(path)
    if not path.is_file():
        raise BuildError(f"The {what} was not found:" + chr(10) + str(path))
    try:
        with Image.open(path) as img:
            img.load()
    except PICTURE_ERRORS as e:
        raise BuildError(f"The {what} ({path.name}) can't be read: {e}")


def preflight(opt: BuildOptions):
    """Check every extra file (pictures, ready-made banner and icon, sound, font) before any work is done, so a bad
    one is reported at once and not after the game has been copied."""
    for path, what in ((opt.image, "picture"), (opt.icon_file, "icon picture"), (opt.banner_file, "banner picture")):
        if path and (what == "picture" or is_picture(path)):
            _check_picture(path, what)
    if opt.icon_file and not is_picture(opt.icon_file):
        _read_ready_made(opt.icon_file, b"SMDH", "icon")
    if opt.banner_file and not is_picture(opt.banner_file):
        path = _read_ready_made(opt.banner_file, b"CBMD", "banner")
        try:
            nsui.Banner(path, require_nsui=False).validate()
        except nsui.NSUIError as e:
            raise BuildError(str(e))
    elif opt.sound_file:                                  # an NSUI banner keeps its own sound, so it isn't used then
        try:
            bn.check_sound(opt.sound_file)
        except bn.SoundError as e:
            raise BuildError(str(e))
    if opt.plate_font and not Path(opt.plate_font).is_file():
        raise BuildError("The title plate font was not found:" + chr(10) + str(opt.plate_font))


def fill_in(opt: BuildOptions, disc, system):
    """Fill in whatever of the title, publisher, year and picture is empty, from what the disc is recognised as (see
    gameinfo). What was given is never replaced."""
    try:
        found = gameinfo.identify(disc, system)
    except (OSError, ValueError):
        found = gameinfo.GameInfo()
    opt.info["recognised"] = found.name
    opt.title = opt.title or found.title
    opt.publisher = opt.publisher or found.publisher
    opt.year = opt.year or found.year
    if not opt.image:
        try:
            opt.image = gameinfo.find_picture(system, [found.name, disc.cue.stem],
                                              gameinfo.thumbnail_folders(opt.pictures_dir))
        except OSError:
            opt.image = None
        if not opt.image and opt.download_picture and found.name:
            from . import download                            # the only part of the app that goes online
            try:
                opt.image = download.download_picture(system, found.name)
            except download.DownloadError as e:
                opt.info["picture_note"] = str(e)
        opt.info["picture"] = opt.image


def build(opt: BuildOptions, progress=lambda frac, msg: None) -> Path:
    progress(0.01, "Checking game and BIOS…")
    disc, system, bios_files, bios_notes = check(opt)
    if opt.lookup:
        fill_in(opt, disc, system)
    preflight(opt)
    info = SYSTEMS[system]
    title = printable(opt.title or clean_title(disc.cue.stem)) or "Game"
    opt.publisher = printable(opt.publisher, 64)
    opt.year = printable(opt.year, 12)
    game = safe_name(title)

    cores = core_dir(info["core"])
    for need in ("emulator.elf", "cia.rsf", "romfs"):
        if not (cores / need).exists():
            raise BuildError(f"Bundled emulator files missing: {cores / need}")

    out_dir = Path(opt.out_dir) if opt.out_dir else disc.cue.parent.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    cia = out_dir / f"{game}.cia"
    uid = unique_id(system, title)
    rom_name = ascii_name(title, uid)                      # the .cue's name inside the CIA and the save folder's name
    track_names = romfs_track_names(disc.tracks)

    # Everything the tools read or write lives in this work folder and is passed to them by a plain relative name
    # (see resources.run_tool), so any path on the PC works: a Japanese user name, an accented folder, and so on.
    with tempfile.TemporaryDirectory(prefix="cdinjector_") as tmp:
        tmp = Path(tmp)

        # RomFS: emulator assets + game + BIOS + boot.txt
        romfs = tmp / "romfs"
        shutil.copytree(cores / "romfs", romfs)
        (romfs / "boot.txt").write_text(f"romfs:/game/{rom_name}.cue\n", encoding="utf-8", newline="\n")
        game_dir = romfs / "game"
        game_dir.mkdir()
        if all(track_names[t] == t for t in disc.tracks):
            shutil.copyfile(disc.cue, game_dir / f"{rom_name}.cue")
        else:
            text = disc.cue.read_bytes().decode("utf-8", errors="replace")
            (game_dir / f"{rom_name}.cue").write_bytes(rewrite_cue(text, track_names).encode("utf-8"))
        done, total = 0, max(1, disc.total_bytes)
        for i, t in enumerate(disc.tracks, 1):
            msg = f"Packing the game ({i} of {len(disc.tracks)} files)…"
            with open(disc.cue.parent / t, "rb") as src, open(game_dir / track_names[t], "wb") as dst:
                while chunk := src.read(8 << 20):
                    dst.write(chunk)
                    done += len(chunk)
                    progress(0.03 + 0.55 * done / total, msg)
        for rel, src in bios_files.items():
            (romfs / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, romfs / rel)

        # RSF: this game's title ID + RomFS path
        rsf = (cores / "cia.rsf").read_text(encoding="utf-8")
        rsf = re.sub(r"(UniqueId\s*:\s*)0x[0-9A-Fa-f]+", rf"\g<1>0x{uid:05X}", rsf)
        rsf = re.sub(r'(ProductCode\s*:\s*)"[^"]*"', rf'\g<1>"CTR-H-{uid & 0xFFFF:04X}"', rsf)
        rsf = re.sub(r'(^\s*Title\s*:\s*)"[^"]*"', rf'\g<1>"{info["short"]}CDI"', rsf, flags=re.M)
        rsf = re.sub(r"(RootPath\s*:\s*).*", lambda m: m.group(1) + '"romfs"', rsf)
        (tmp / "game.rsf").write_text(rsf, encoding="utf-8")
        shutil.copyfile(cores / "emulator.elf", tmp / "emulator.elf")

        progress(0.60, "Making the icon and banner…")
        color = tuple(opt.frame_color) if opt.frame_color else None
        if opt.icon_file and not is_picture(opt.icon_file):
            icon = tmp / "icon.icn"
            shutil.copyfile(_read_ready_made(opt.icon_file, b"SMDH", "icon"), icon)
        else:
            icon = tmp / "icon.icn"
            picture = opt.icon_file or opt.image                # an icon picture, else the title screen
            try:
                opt.info["icon"] = bn.make_icon(picture, opt.icon_fit, title, f"{title} ({info['name']})",
                                                opt.publisher, system, icon, color)
            except PICTURE_ERRORS as e:
                raise BuildError(f"Couldn't make the icon from the picture: {e}")
        year = opt.year.strip()
        if opt.banner_file and not is_picture(opt.banner_file):
            banner = _read_ready_made(opt.banner_file, b"CBMD", "banner")
            try:                                                 # this game's title (and picture) go on an NSUI banner
                banner, note = nsui.prepare(banner, title, year, tmp, opt.plate_font, opt.image)
                opt.info["banner_kind"] = "NSUI banner" + (f" ({note})" if note else "")
            except nsui.DamagedBannerError as e:                 # a broken banner could stop the Home Menu showing the game
                raise BuildError(str(e))
            except nsui.NSUIError:
                try:                                             # some other 3DS banner: check its structure, use it as it is
                    nsui.Banner(banner, require_nsui=False).validate()
                except nsui.NSUIError as e:
                    raise BuildError(str(e))
                opt.info["banner_kind"] = "your banner file"
            except PICTURE_ERRORS + (RuntimeError,) as e:
                raise BuildError(f"Couldn't use the banner: {e}")
        else:
            banner = tmp / "banner.bnr"
            try:
                if opt.banner_file:                              # a picture used as the whole banner
                    opt.info["banner"] = bn.make_banner(opt.banner_file, title, year, system, opt.sound_file, banner,
                                                        tmp, style="custom")
                    opt.info["banner_kind"] = "your banner picture"
                else:
                    opt.info["banner"] = bn.make_banner(opt.image, title, year, system, opt.sound_file, banner, tmp,
                                                        color=color, font_file=opt.plate_font)
                    opt.info["banner_kind"] = "title screen in a coloured frame"
            except PICTURE_ERRORS as e:
                raise BuildError(f"Couldn't make the banner: {e}")
            except bn.SoundError as e:
                raise BuildError(str(e))
        if Path(banner).parent != tmp:                           # an untouched ready-made banner: bring it in
            shutil.copyfile(banner, tmp / "banner.bnr")
            banner = tmp / "banner.bnr"

        progress(0.64, "Building the CIA…")
        run_tool([tool("makerom"), "-f", "cia", "-o", "out.cia", "-rsf", "game.rsf", "-elf", "emulator.elf",
                  "-icon", icon.name, "-banner", banner.name], cwd=tmp)

        # The CIA only appears under its real name once it is complete, so a failed or cancelled build never
        # leaves a half-written CIA that someone might install.
        progress(0.9, "Saving the CIA…")
        part = cia.with_name(cia.name + ".part")
        try:
            shutil.move(str(tmp / "out.cia"), str(part))
            os.replace(part, cia)
        finally:
            if part.exists():
                part.unlink()

    progress(1.0, "Done")
    opt.info.update(title=title, system=info["name"], notes=bios_notes, title_id=f"000400000{uid:05X}00")
    return cia
