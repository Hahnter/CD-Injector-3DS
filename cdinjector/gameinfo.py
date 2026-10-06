"""Recognising a PC Engine CD or Sega CD disc, for filling in its title, publisher, year and picture.

Everything here works offline. A disc is recognised, in this order, by:
  1. the serial number in a Sega CD disc's own header (PC Engine CD discs have none),
  2. the size and CRC-32 of one of its tracks, compared with the discs Redump has verified (see gamelist.py),
  3. its .cue file's name, when that is the disc's Redump or MAME name.
A Sega CD disc that isn't in the list still gives its year (and "Sega" for Sega's own games) from its header.

Pictures come from RetroArch's thumbnail packs when they're on the PC (or from a folder the user chooses): RetroArch
names each picture after the game's Redump name, so a recognised disc finds its title screen or box art there.
"""

import os
import re
import zlib
from dataclasses import dataclass
from pathlib import Path

from .gamelist import DISCS

THUMBNAIL_SYSTEMS = {"pce": "NEC - PC Engine CD - TurboGrafx-CD", "segacd": "Sega - Mega-CD - Sega CD"}
THUMBNAIL_KINDS = ("Named_Titles", "Named_Snaps", "Named_Boxarts")      # title screen first, box art last
PICTURE_TYPES = (".png", ".jpg", ".jpeg")


@dataclass
class GameInfo:
    title: str = ""
    publisher: str = ""
    year: str = ""
    name: str = ""            # the disc's Redump (or MAME) name, e.g. "Sonic CD (Europe)"
    found_by: str = ""        # "header", "tracks", "name" or "" (not recognised)


def display_title(name):
    """A Redump or MAME name as a title for the banner: no region or notes in brackets, a leading article back at the
    front, and the subtitle after a colon. "Addams Family, The (USA)" -> "The Addams Family";
    "Lunar - The Silver Star (Japan)" -> "Lunar: The Silver Star"."""
    title = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", name).strip()
    m = re.match(r"^(.*?), (The|A|An)\b(.*)$", title)
    if m:
        title = f"{m.group(2)} {m.group(1)}{m.group(3)}"
    title = title.replace(" - ", ": ", 1)
    return re.sub(r"\s+", " ", title).strip()


def _key(name):
    """A name reduced for matching: no brackets, no punctuation, lower case."""
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", name.lower())).strip()


_INDEX = {}


def _index(system):
    """{"size": {size: [discs]}, "serial": {...}, "name": {exact lower-case name: [discs]}, "key": {...}}."""
    if system not in _INDEX:
        idx = {"size": {}, "serial": {}, "name": {}, "key": {}}
        for disc in DISCS.get(system, ()):
            size, _crc, serial, redump, mame = disc[:5]
            if size:
                idx["size"].setdefault(size, []).append(disc)
            if serial:
                idx["serial"].setdefault(serial.upper(), []).append(disc)
            for n in (redump, mame):
                if n:
                    idx["name"].setdefault(n.lower(), []).append(disc)
                    idx["key"].setdefault(_key(n), []).append(disc)
        _INDEX[system] = idx
    return _INDEX[system]


def _crc32(path):
    crc = 0
    with open(path, "rb") as f:
        while chunk := f.read(8 << 20):
            crc = zlib.crc32(chunk, crc)
    return crc


def segacd_header(folder, tracks):
    """{"serial", "year", "maker", "title"} from the system area at the start of a Sega CD disc's first data track,
    or None. The area holds a Mega Drive style header: maker and date at 0x110 ("(C)SEGA 1993.JUN"), the overseas
    title at 0x150 and the serial at 0x180 ("GM G-6021  -00")."""
    for t in tracks[:4]:
        try:
            with open(Path(folder) / t, "rb") as f:
                head = f.read(0x10000)
        except OSError:
            continue
        at = head.find(b"SEGADISCSYSTEM")
        if at < 0 or len(head) < at + 0x190:
            continue
        field = lambda o, n: head[at + o:at + o + n].decode("ascii", "replace").strip()      # noqa: E731
        made = field(0x110, 16)
        year = re.search(r"(19[89]\d|20[0-2]\d)", made)
        words = field(0x180, 14).split()
        serial = words[1] if len(words) > 1 and len(words[0]) == 2 else (words[0] if words else "")
        return dict(serial=re.sub(r"-\d\d$", "", serial), year=year.group(1) if year else "",
                    maker=made[3:].split()[0] if made.upper().startswith("(C)") and len(made) > 3 else "",
                    title=re.sub(r"\s+", " ", field(0x150, 48)))
    return None


def _info(disc, found_by):
    size, crc, serial, redump, mame, publisher, year = disc
    return GameInfo(title=display_title(mame or redump), publisher=publisher, year=year, name=redump or mame,
                    found_by=found_by)


def identify(disc, system):
    """GameInfo for a disc (a disc.Disc) of `system`; an empty GameInfo when it isn't recognised."""
    idx = _index(system)
    folder = disc.cue.parent
    sizes = {}
    for t in disc.tracks:
        try:
            sizes[t] = (folder / t).stat().st_size
        except OSError:
            pass

    header = segacd_header(folder, disc.tracks) if system == "segacd" else None
    if header and header["serial"]:
        options = idx["serial"].get(header["serial"].upper(), [])
        same_size = [d for d in options if d[0] and d[0] in sizes.values()]
        if same_size or options:
            return _info((same_size or options)[0], "header")

    for t, size in sizes.items():                     # a CRC is only worked out for a track of a known size
        options = idx["size"].get(size)
        if options:
            crc = _crc32(folder / t)
            for d in options:
                if d[1] == crc:
                    return _info(d, "tracks")

    stem = disc.cue.stem
    options = idx["name"].get(stem.lower()) or idx["key"].get(_key(stem))
    if options:
        return _info(options[0], "name")

    if header:                                        # not in the list: what the disc itself says
        return GameInfo(year=header["year"], publisher="Sega" if header["maker"].upper() == "SEGA" else "",
                        found_by="header")
    return GameInfo()


def thumbnail_folders(chosen=None):
    """RetroArch thumbnail folders on this PC (the chosen folder first), the ones that exist."""
    home = Path.home()
    places = [Path(chosen)] if chosen else []
    appdata = os.environ.get("APPDATA")
    if appdata:
        places.append(Path(appdata) / "RetroArch" / "thumbnails")
    for drive in ("C:/", "D:/"):
        places += [Path(drive) / "RetroArch-Win64" / "thumbnails", Path(drive) / "RetroArch" / "thumbnails",
                   Path(drive) / "Program Files (x86)" / "Steam" / "steamapps" / "common" / "RetroArch" / "thumbnails",
                   Path(drive) / "Program Files" / "Steam" / "steamapps" / "common" / "RetroArch" / "thumbnails"]
    places += [home / ".config" / "retroarch" / "thumbnails",
               home / "Library" / "Application Support" / "RetroArch" / "thumbnails"]
    seen, out = set(), []
    for p in places:
        try:
            if p.is_dir() and str(p).lower() not in seen:
                seen.add(str(p).lower())
                out.append(p)
        except OSError:
            pass
    return out


def thumbnail_file_name(name):
    """RetroArch's file name for a game's picture: these characters become "_"."""
    return re.sub(r'[&*/:`<>?\\|"]', "_", name)


def find_picture(system, names, folders):
    """The first picture for any of `names` (a title screen if there is one, then a screenshot, then box art) in
    the thumbnail folders, laid out as RetroArch does (<folder>/<system>/Named_Titles/<name>.png) or flat."""
    names = [thumbnail_file_name(n) for n in names if n]
    sub = THUMBNAIL_SYSTEMS.get(system, "")
    for folder in folders:
        folder = Path(folder)
        for place in [folder / sub / kind for kind in THUMBNAIL_KINDS] + [folder / kind for kind in THUMBNAIL_KINDS] \
                + [folder]:
            for n in names:
                for ext in PICTURE_TYPES:
                    p = place / (n + ext)
                    try:
                        if p.is_file():
                            return p
                    except OSError:
                        pass
    return None
