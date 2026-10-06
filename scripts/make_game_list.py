#!/usr/bin/env python3
"""Writes cdinjector/gamelist.py, the list of PC Engine CD and Sega CD discs the app recognises.

    python scripts/make_game_list.py <libretro-database folder> <MAME hash folder>

Two public lists are joined by each disc's serial number:

  * libretro-database (https://github.com/libretro/libretro-database), `rdb/`: every disc Redump has verified,
    with its name, region, serial and the size and CRC-32 of its first data track. This is how the app recognises
    a disc. Licence: CC BY-SA 4.0.
  * MAME's software lists (https://github.com/mamedev/mame), `hash/pcecd.xml` and `hash/megacd.xml`: the title,
    publisher and year of each disc. Licence: CC0 1.0 (public domain).

Only those few fields are kept. Run it again to pick up newer lists; the output is sorted, so a diff shows exactly
what changed.
"""

import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SYSTEMS = {
    "pce": ("NEC - PC Engine CD - TurboGrafx-CD.rdb", "pcecd.xml"),
    "segacd": ("Sega - Mega-CD - Sega CD.rdb", "megacd.xml"),
}
OUT = Path(__file__).resolve().parents[1] / "cdinjector" / "gamelist.py"


def unpack(d, p):
    """One MessagePack value at d[p:] (the subset libretro's .rdb files use): (value, next position)."""
    b = d[p]
    if b <= 0x7F:
        return b, p + 1
    if 0x80 <= b <= 0x8F or b in (0xDE, 0xDF):
        n, p = (b & 0x0F, p + 1) if b <= 0x8F else (struct.unpack_from(">H" if b == 0xDE else ">I", d, p + 1)[0],
                                                     p + (3 if b == 0xDE else 5))
        out = {}
        for _ in range(n):
            k, p = unpack(d, p)
            v, p = unpack(d, p)
            out.setdefault(k, v)                       # some records list a key twice; the first one counts
        return out, p
    if 0xA0 <= b <= 0xBF:
        n = b & 0x1F
        return d[p + 1:p + 1 + n].decode("utf-8", "replace"), p + 1 + n
    sizes = {0xD9: 1, 0xDA: 2, 0xDB: 4, 0xC4: 1, 0xC5: 2, 0xC6: 4}
    if b in sizes:
        k = sizes[b]
        n = int.from_bytes(d[p + 1:p + 1 + k], "big")
        raw = d[p + 1 + k:p + 1 + k + n]
        return (raw.decode("utf-8", "replace") if b in (0xD9, 0xDA, 0xDB) else raw), p + 1 + k + n
    ints = {0xCC: 1, 0xCD: 2, 0xCE: 4, 0xCF: 8, 0xD0: 1, 0xD1: 2, 0xD2: 4, 0xD3: 8}
    if b in ints:
        k = ints[b]
        return int.from_bytes(d[p + 1:p + 1 + k], "big", signed=b >= 0xD0), p + 1 + k
    if b == 0xC0:
        return None, p + 1
    raise ValueError(f"unexpected MessagePack byte {b:#x} at {p}")


def read_rdb(path):
    d = Path(path).read_bytes()
    if d[:7] != b"RARCHDB":
        raise SystemExit(f"{path} isn't a libretro database")
    p, out = 16, []
    while p < len(d):
        rec, p = unpack(d, p)
        if not isinstance(rec, dict):
            break
        out.append(rec)
    return out


def text(value):
    return value.decode("ascii", "replace") if isinstance(value, bytes) else str(value or "")


def key(name):
    """A name reduced for matching: no regions or notes in brackets, no punctuation, lower case."""
    name = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", name)
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def region(name):
    groups = re.findall(r"\(([^)]*)\)", name)
    return groups[0].split(",")[0].strip() if groups else ""


def mame_entries(path):
    out = []
    for sw in ET.parse(path).getroot().findall("software"):
        info = {i.get("name"): i.get("value") for i in sw.findall("info")}
        year = (sw.findtext("year") or "").strip()
        publisher = (sw.findtext("publisher") or "").strip()
        out.append(dict(name=sw.findtext("description").strip(), serial=(info.get("serial") or "").strip(),
                        year=year if re.fullmatch(r"\d{4}", year) else "",
                        publisher="" if publisher.startswith("<") else publisher))
    return out


def join(rdb, mame):
    """[(size, crc, serial, Redump name, MAME name, publisher, year)] for every disc in either list."""
    by_serial, by_key, used, rows = {}, {}, set(), []
    for i, m in enumerate(mame):
        for s in m["serial"].replace(",", " ").split():
            by_serial.setdefault(s.upper(), []).append(i)
        by_key.setdefault(key(m["name"]), []).append(i)
    for r in rdb:
        name, serial = text(r.get("name")), text(r.get("serial")).strip()
        size, crc = r.get("size") or 0, int.from_bytes(r.get("crc") or b"\0\0\0\0", "big")
        options = by_serial.get(serial.upper(), []) or by_key.get(key(name), [])
        same_region = [i for i in options if region(mame[i]["name"]) == region(name)]
        pick = (same_region or options or [None])[0]
        m = mame[pick] if pick is not None else dict(name="", publisher="", year="")
        if pick is not None:
            used.add(pick)
        rows.append((size, crc, serial, name, m["name"], m["publisher"], m["year"]))
    for i, m in enumerate(mame):                     # discs MAME knows that Redump hasn't verified
        if i not in used:
            rows.append((0, 0, m["serial"], "", m["name"], m["publisher"], m["year"]))
    return sorted(set(rows), key=lambda r: (r[3] or r[4]).lower())


def main(libretro, mame_hash):
    lines = ['"""PC Engine CD and Sega CD discs the app recognises. Written by scripts/make_game_list.py: don\'t edit.',
             "",
             "Each disc is (size and CRC-32 of its first data track, serial, Redump name, MAME name, publisher, year).",
             "Sizes, CRCs, serials and Redump names: libretro-database (https://github.com/libretro/libretro-database),",
             "licensed CC BY-SA 4.0, so this file is shared under the same licence. MAME names, publishers and years:",
             'MAME\'s software lists (https://github.com/mamedev/mame), CC0 1.0. Size 0 means MAME lists a disc that',
             'Redump hasn\'t verified; it can only be recognised by its serial or name."""',
             "",
             "DISCS = {"]
    for system, (rdb_name, xml_name) in SYSTEMS.items():
        rows = join(read_rdb(Path(libretro) / "rdb" / rdb_name), mame_entries(Path(mame_hash) / xml_name))
        lines.append(f'    "{system}": (')
        for size, crc, serial, redump, mame, publisher, year in rows:
            lines.append(f"        ({size}, 0x{crc:08X}, {serial!r}, {redump!r}, {mame!r}, {publisher!r}, {year!r}),")
        lines.append("    ),")
        print(f"{system}: {len(rows)} discs, {sum(1 for r in rows if r[5])} with a publisher")
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
