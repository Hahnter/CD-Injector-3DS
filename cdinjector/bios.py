"""Finding BIOS files and mapping them to the names the emulators look for inside the CIA."""

import hashlib
from pathlib import Path

# lower-cased file names each emulator accepts, best first
PCE_NAMES = ["syscard3.pce"]
PCE_SIZES = {262144, 262656}                       # with or without 512-byte header
SEGACD_NAMES = {
    "U": ["bios_cd_u.bin", "us_scd2_9306.bin", "segacdbios9303.bin", "us_scd1_9210.bin"],
    "E": ["bios_cd_e.bin", "eu_mcd2_9306.bin", "eu_mcd2_9303.bin", "eu_mcd1_9210.bin"],
    "J": ["bios_cd_j.bin", "jp_mcd2_921222.bin", "jp_mcd1_9112.bin", "jp_mcd1_9111.bin"],
}
SEGACD_SIZE = 131072

# MD5s of commonly verified dumps (libretro docs); unknown hashes only give a warning.
KNOWN_MD5 = {
    "38179df8f4ac870017db21ebcbf53114": "PC Engine CD System Card 3.0",
    "2efd74e3232ff260e371b99f84024f7f": "Sega CD BIOS (USA)",
    "e66fa1dc5820d254611fdcdba0662372": "Mega CD BIOS (Europe)",
    "278a9397d192149e84e820ac621a8edd": "Mega CD BIOS (Japan)",
}


class BiosError(Exception):
    pass


def md5(path: Path) -> str:
    # only used to recognise a known dump, never for security
    return hashlib.md5(Path(path).read_bytes(), usedforsecurity=False).hexdigest()


def _candidates(src: Path, recursive=True):
    src = Path(src)
    if src.is_file():
        return [src]
    if src.is_dir():
        found = []
        walker = src.rglob("*") if recursive else src.glob("*")
        for p in walker:
            if p.suffix.lower() in (".pce", ".bin", ".rom") and p.is_file() and p.stat().st_size < 1_000_000:
                found.append(p)
                if len(found) > 5000:          # don't crawl a whole drive
                    break
        return sorted(found)
    raise BiosError(f"{src} not found.")


def find_bios(system: str, src: Path, recursive=True):
    """Returns ({path inside the CIA's RomFS: source file}, [notes])."""
    files = _candidates(src, recursive)
    by_name = {}
    for f in files:
        by_name.setdefault(f.name.lower(), f)
    notes = []

    if system == "pce":
        pick = None
        for n in PCE_NAMES:
            f = by_name.get(n)
            if f and f.stat().st_size in PCE_SIZES:
                pick = f
                break
        if not pick and Path(src).is_file() and Path(src).stat().st_size in PCE_SIZES:
            pick = Path(src)
        if not pick:
            raise BiosError("No PC Engine System Card 3.0 found (a 256 KB file named syscard3.pce).")
        found = {"syscards/syscard3.pce": pick}
    elif system == "segacd":
        found = {}
        for region, names in SEGACD_NAMES.items():
            for n in names:
                f = by_name.get(n)
                if f and f.stat().st_size == SEGACD_SIZE:
                    found[f"bios/bios_CD_{region}.bin"] = f
                    break
        if not found:
            raise BiosError("No Sega CD BIOS found (128 KB files named like bios_CD_U.bin or us_scd1_9210.bin).")
    else:
        raise BiosError(f"Unknown system {system!r}.")

    for rel, f in found.items():
        h = md5(f)
        notes.append(f"{f.name}: {KNOWN_MD5[h]} (verified)" if h in KNOWN_MD5
                     else f"{f.name}: unrecognised dump (MD5 {h}); it may still work")
    return found, notes
