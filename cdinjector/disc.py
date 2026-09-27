"""Reading .cue sheets and working out which system a disc is for."""

import re
from dataclasses import dataclass, field
from pathlib import Path

SYSTEMS = {
    "pce": dict(name="PC Engine CD", core="temperpce", short="PCE",
                bios_hint="PC Engine CD System Card 3.0 (syscard3.pce)"),
    "segacd": dict(name="Sega CD", core="picodrive", short="SCD",
                   bios_hint="Sega CD BIOS (bios_CD_U.bin / bios_CD_E.bin / bios_CD_J.bin)"),
}

MAX_CUE_BYTES = 256 * 1024          # a real .cue sheet is a few KB
MAX_TRACKS = 200                    # a CD has at most 99 tracks

SIGNATURES = [(b"SEGADISCSYSTEM", "segacd"), (b"PC Engine CD-ROM SYSTEM", "pce")]
CUE_FILE = re.compile(r'\s*FILE\s+(?:"([^"]+)"|(\S+))\s*(\w*)', re.IGNORECASE)


class DiscError(Exception):
    pass


@dataclass
class Disc:
    cue: Path
    tracks: list = field(default_factory=list)       # track file names, in order
    system: str = ""                                  # "pce", "segacd" or "" if unknown
    total_bytes: int = 0


def read_cue(cue: Path) -> Disc:
    cue = Path(cue)
    if cue.suffix.lower() != ".cue":
        raise DiscError("Choose the game's .cue file (it lists the .bin tracks).")
    if not cue.is_file():
        raise DiscError(f"{cue} not found.")
    if cue.stat().st_size > MAX_CUE_BYTES:
        raise DiscError(f"{cue.name} is far too big to be a .cue sheet. Is it the right file?")
    names, kinds = [], []
    for line in cue.read_bytes().decode("utf-8", errors="replace").splitlines():
        m = CUE_FILE.match(line)
        if m:
            names.append(Path((m.group(1) or m.group(2)).replace("\\", "/")).name)
            kinds.append((m.group(3) or "").upper())
    if not names:
        raise DiscError(f"{cue.name} doesn't list any track files.")
    seen, tracks = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            tracks.append(n)
    if len(tracks) > MAX_TRACKS:
        raise DiscError(f"{cue.name} lists {len(tracks)} track files, which is not a real disc.")
    if any(not t or t in (".", "..") or any(ord(c) < 32 for c in t) for t in tracks):
        raise DiscError(f"{cue.name} lists a track file with an invalid name.")
    missing = [t for t in tracks if not (cue.parent / t).is_file()]
    if missing:
        raise DiscError("These track files are missing next to the .cue:\n  " + "\n  ".join(missing))
    # Only files that really sit in the .cue's own folder are packed. A shortcut (symbolic link or junction) that
    # points somewhere else would otherwise pull an unrelated file into a CIA that people may then share.
    folder = cue.parent.resolve()
    outside = [t for t in tracks if (cue.parent / t).resolve().parent != folder]
    if outside:
        raise DiscError("These track files are shortcuts to files outside the game's folder, so they were not "
                        "used:\n  " + "\n  ".join(outside) + "\nCopy the real files into the folder.")
    disc = Disc(cue=cue, tracks=tracks)
    disc.total_bytes = cue.stat().st_size + sum((cue.parent / t).stat().st_size for t in tracks)
    disc.system = detect_system(cue.parent, tracks)
    return disc


def detect_system(folder: Path, tracks) -> str:
    # The boot sector of the first data track carries a system signature.
    for t in tracks[:4]:
        with open(folder / t, "rb") as f:
            head = f.read(0x10000)
        for sig, system in SIGNATURES:
            if sig in head:
                return system
    return ""
