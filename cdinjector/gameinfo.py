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

from . import APP_NAME
from .gamelist import DISCS
from .thumbnail_names import NAMES as THUMBNAIL_NAMES

THUMBNAIL_SYSTEMS = {"pce": "NEC - PC Engine CD - TurboGrafx-CD", "segacd": "Sega - Mega-CD - Sega CD"}
THUMBNAIL_KINDS = ("Named_Titles", "Named_Snaps", "Named_Boxarts")      # title screen first, box art last
COVER_KINDS = ("Named_Boxarts",)                                         # the cover, for the CD case banner
PICTURE_TYPES = (".png", ".jpg", ".jpeg")
# the country or region words in a Redump or MAME name, by the Sega CD region they belong to (J, U or E)
REGION_WORDS = {"japan": "J", "asia": "J", "korea": "J", "taiwan": "J", "hong kong": "J",
                "usa": "U", "brazil": "U", "canada": "U",
                "europe": "E", "germany": "E", "france": "E", "uk": "E", "spain": "E", "italy": "E", "netherlands": "E",
                "sweden": "E", "scandinavia": "E", "portugal": "E", "australia": "E"}
REGION_NAMES = {"J": "Japan", "U": "USA", "E": "Europe"}
# notes after the region in a Redump name that a game's picture is usually kept without: its languages
# "(En,Fr,De)", a revision "(Rev 2)", "(Alt)", "(Rerelease)", "(Beta)" and so on
NOTES = re.compile(r"\s*\((?:(?:[A-Z][a-z](?:-[A-Z][a-z])?,)*[A-Z][a-z](?:-[A-Z][a-z])?|Rev [^)]*|Alt[^)]*|Rerelease"
                   r"|Beta[^)]*|Proto[^)]*|Demo[^)]*)\)")


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


def regions_of(name):
    """The regions (a set of "J", "U", "E") in the first brackets of a name: "Sonic CD (USA)" -> {"U"}."""
    m = re.search(r"\(([^)]*)\)", name or "")
    return {REGION_WORDS[w.strip().lower()] for w in m.group(1).split(",") if w.strip().lower() in REGION_WORDS} \
        if m else set()


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
    """{"serial", "year", "maker", "title", "regions"} from the system area at the start of a Sega CD disc's first
    data track, or None. The area holds a Mega Drive style header: maker and date at 0x110 ("(C)SEGA 1993.JUN"), the
    overseas title at 0x150, the serial at 0x180 ("GM G-6021  -00") and the regions at 0x1F0, as letters ("U",
    "JUE") or, on later discs, one hex digit (1 Japan, 4 USA, 8 Europe, added up)."""
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
        codes = field(0x1F0, 16).upper()
        regions = {c for c in codes[:3] if c in "JUE"}
        if not regions and codes[:1] and codes[0] in "0123456789ABCDEF":
            regions = {r for bit, r in ((1, "J"), (4, "U"), (8, "E")) if int(codes[0], 16) & bit}
        return dict(serial=re.sub(r"-\d\d$", "", serial), year=year.group(1) if year else "",
                    maker=made[3:].split()[0] if made.upper().startswith("(C)") and len(made) > 3 else "",
                    title=re.sub(r"\s+", " ", field(0x150, 48)), regions=regions)
    return None


def _info(disc, found_by, name=""):
    size, crc, serial, redump, mame, publisher, year = disc
    return GameInfo(title=display_title(mame or redump), publisher=publisher, year=year,
                    name=name or redump or mame, found_by=found_by)


def _choose(options, sizes, regions, found_by):
    """The GameInfo of the best of `options` (discs with the same serial or name) for a disc with tracks of `sizes`
    from `regions`. A disc whose track size Redump lists is that one. Otherwise one from the disc's own region, by
    its Redump name if Redump has it; when Redump only has the game from another region, that disc's details under
    its name with the disc's region ("Sonic CD (Europe)" for a USA disc becomes "Sonic CD (USA)"), which is how
    libretro's pictures are named. Without regions, the first one."""
    same_size = [d for d in options if d[0] and d[0] in sizes]
    if same_size:
        return _info(same_size[0], found_by)
    if regions:
        local = [d for d in options if regions_of(d[3] or d[4]) & regions]
        verified = [d for d in options if d[3]]
        if [d for d in local if d[3]]:
            return _info([d for d in local if d[3]][0], found_by)
        if verified and len(regions) == 1:
            base = re.sub(r"\s*\(.*$", "", verified[0][3])
            return _info(verified[0], found_by, name=f"{base} ({REGION_NAMES[next(iter(regions))]})")
        if local:
            return _info(local[0], found_by)
    return _info(options[0], found_by)


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
        serial = header["serial"].upper()             # Sega's own discs say "MK-4407"; the list may say "4407"
        options = idx["serial"].get(serial) or idx["serial"].get(re.sub(r"^MK-?", "", serial), [])
        if options:
            return _choose(options, sizes.values(), header["regions"], "header")

    for t, size in sizes.items():                     # a CRC is only worked out for a track of a known size
        options = idx["size"].get(size)
        if options:
            crc = _crc32(folder / t)
            for d in options:
                if d[1] == crc:
                    return _info(d, "tracks")

    stem = disc.cue.stem
    options = idx["name"].get(stem.lower())
    if options:
        return _info(options[0], "name")
    options = idx["key"].get(_key(stem))
    if options:                                       # the same game, maybe from another region
        return _choose(options, sizes.values(), regions_of(stem) or (header or {}).get("regions"), "name")

    if header:                                        # not in the list: what the disc itself says
        return GameInfo(year=header["year"], publisher="Sega" if header["maker"].upper() == "SEGA" else "",
                        found_by="header")
    return GameInfo()


def downloaded_pictures():
    """Where pictures downloaded from libretro's thumbnails are kept (see download.py): next to the app's settings,
    laid out like RetroArch's thumbnails."""
    return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME / "pictures"


def thumbnail_folders(chosen=None):
    """Folders to look for pictures in, the ones that exist: the chosen folder, pictures downloaded before, and
    RetroArch's thumbnails on this PC."""
    home = Path.home()
    places = ([Path(chosen)] if chosen else []) + [downloaded_pictures()]
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


def name_variants(name):
    """`name` and the same name without its language, revision and similar notes, which libretro's pictures are
    usually kept without: "Dune (USA) (En,Fr,De,Es,It)" -> also "Dune (USA)"."""
    plain = NOTES.sub("", name).strip()
    return [name] + ([plain] if plain and plain != name else [])


def picture_names(system, names):
    """The names to look for a picture under, best first: for each of `names`, the one libretro's thumbnails use if
    it differs (see thumbnail_names.py), then the name itself and its variants."""
    out = []
    for n in names:
        if not n:
            continue
        for v in [THUMBNAIL_NAMES.get(system, {}).get(n, "")] + name_variants(n):
            if v and v not in out:
                out.append(v)
    return out


def find_picture(system, names, folders, kinds=THUMBNAIL_KINDS):
    """The first picture for any of `names` (a title screen if there is one, then a screenshot, then box art; or
    only the kinds given, say COVER_KINDS) in the thumbnail folders, laid out as RetroArch does
    (<folder>/<system>/Named_Titles/<name>.png) or, for any kind, flat."""
    names = [thumbnail_file_name(n) for n in picture_names(system, names)]
    sub = THUMBNAIL_SYSTEMS.get(system, "")
    for folder in folders:
        folder = Path(folder)
        for place in [folder / sub / kind for kind in kinds] + [folder / kind for kind in kinds] \
                + ([folder] if tuple(kinds) == THUMBNAIL_KINDS else []):
            for n in names:
                for ext in PICTURE_TYPES:
                    p = place / (n + ext)
                    try:
                        if p.is_file():
                            return p
                    except OSError:
                        pass
    return None
