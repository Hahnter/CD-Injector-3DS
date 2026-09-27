#!/usr/bin/env python3
"""Checks (and optionally cleans) files for invisible or look-alike characters and hidden metadata.

    python scripts/hygiene.py [--fix] [paths...]        (default path: the project folder)

What it looks for, and why:

  * Invisible characters: zero-width and other format controls, Unicode "tag" characters and variation
    selectors. They can be pasted in by accident, can carry hidden markers (including provenance marks that
    some tools add to generated text), and they break diffs and searches.
  * Bidirectional controls in source files: these can make code read differently from how it runs
    ("Trojan Source", CVE-2021-42574). They are always reported, and never left in place by --fix.
  * Exotic spaces (no-break space and friends) that look like a normal space but aren't.
  * Look-alike letters (Cyrillic, Greek, fullwidth Latin) inside source files. Reported only: whether one is
    intended is a human decision.
  * Hidden metadata in PNG and JPEG files: text chunks, EXIF, XMP and C2PA "content credentials".

--fix removes the invisible characters and metadata and turns exotic spaces into normal ones. It does not
rewrite wording. Removing a mark does not change whether something was AI-assisted, so keep any disclosure
that a platform or a licence asks for.

Exit status: 0 = clean, 1 = something was found (or, with --fix, something was changed).
"""

import argparse
import struct
import sys
import unicodedata
from pathlib import Path

TEXT_SUFFIXES = {".py", ".md", ".txt", ".ps1", ".sh", ".json", ".patch", ".rsf", ".toml", ".yml", ".yaml", ".cfg",
                 ".ini", ".spec", ".rst", ".csv", ".html", ".css", ".js", ".ts", ".gitignore", ".gitattributes",
                 "license", "licence", "notice", "copying", "authors", "readme", "makefile"}
SKIP_DIRS = {".git", "dist", "build", "__pycache__", "retired", "node_modules", ".venv", "venv", "cores", "tools",
             "banner_templates"}
SOURCE_SUFFIXES = {".py", ".ps1", ".sh", ".js", ".ts"}
KEEP_BOM = {".ps1"}                                   # Windows PowerShell 5.1 needs the BOM for non-ASCII scripts

BIDI = {0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0x200E, 0x200F, 0x061C}
INVISIBLE = {
    0x00AD, 0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180C, 0x180D, 0x180E, 0x180F,
    0x200B, 0x200C, 0x200D, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0x206A, 0x206B, 0x206C, 0x206D, 0x206E, 0x206F,
    0xFEFF, 0x3164, 0xFFA0, 0xFFF9, 0xFFFA, 0xFFFB,
} | BIDI | set(range(0xFE00, 0xFE10)) | set(range(0xE0000, 0xE0080)) | set(range(0xE0100, 0xE01F0))
SPACES = {0x00A0, 0x1680, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000}


def _confusable(cp):
    return 0x0370 <= cp <= 0x03FF or 0x0400 <= cp <= 0x04FF or 0xFF21 <= cp <= 0xFF5A


def _bad_control(cp):
    return (cp < 0x20 and cp not in (0x09, 0x0A, 0x0D, 0x0C)) or 0x7F <= cp <= 0x9F


def _emoji(ch):
    """A character that is (part of) an emoji: symbols and pictographs, plus the digits and # * that keycap emoji use."""
    cp = ord(ch)
    return (0x1F000 <= cp <= 0x1FFFF or 0x2190 <= cp <= 0x2BFF or unicodedata.category(ch) == "So"
            or ch in "0123456789#*")


def legitimate_in_emoji(text, i):
    """True for a zero-width joiner or emoji-presentation selector that is part of a real emoji sequence: the joiner
    sits between two emoji, and U+FE0F (or the keycap mark U+20E3) follows an emoji."""
    cp = ord(text[i])
    before = text[i - 1] if i > 0 else ""
    after = text[i + 1] if i + 1 < len(text) else ""
    if cp == 0x200D:
        return bool(before) and bool(after) and (_emoji(before) or ord(before) == 0xFE0F) and _emoji(after)
    if cp == 0xFE0F:
        return bool(before) and _emoji(before)
    return False


def classify(text, suffix):
    """{name: [(line, column, codepoint)]} for everything suspicious in `text`."""
    found = {}
    line, col = 1, 0
    for i, ch in enumerate(text):
        cp = ord(ch)
        if cp in (0x200D, 0xFE0F) and legitimate_in_emoji(text, i):
            col += 1
            continue
        col += 1
        if ch == "\n":
            line, col = line + 1, 0
            continue
        kind = None
        if cp in BIDI:
            kind = "bidirectional control"
        elif cp in INVISIBLE:
            kind = "invisible character"
        elif cp in SPACES:
            kind = "exotic space"
        elif _bad_control(cp) or unicodedata.category(ch) in ("Co", "Cn") or 0xFDD0 <= cp <= 0xFDEF or (cp & 0xFFFE) == 0xFFFE:
            kind = "control, private-use or unassigned"
        elif suffix in SOURCE_SUFFIXES and _confusable(cp):
            kind = "look-alike letter in source"
        if kind:
            found.setdefault(kind, []).append((line, col, cp))
    return found


def clean_text(text, suffix, keep_bom=False):
    out = []
    for i, ch in enumerate(text):
        cp = ord(ch)
        if cp in (0x200D, 0xFE0F) and legitimate_in_emoji(text, i):
            out.append(ch)
        elif cp == 0xFEFF and i == 0 and keep_bom:
            out.append(ch)
        elif cp in SPACES:
            out.append(" ")
        elif cp in INVISIBLE or _bad_control(cp) or unicodedata.category(ch) in ("Co", "Cn") or 0xFDD0 <= cp <= 0xFDEF \
                or (cp & 0xFFFE) == 0xFFFE:
            continue
        else:
            out.append(ch)
    return "".join(out)


# ------------------------------------------------------------------------------------------------ images
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_HIDDEN = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"caBX", b"tIME", b"dSIG"}
JPEG_HIDDEN = {0xE1: "EXIF/XMP", 0xEB: "JUMBF (C2PA)", 0xED: "Photoshop info", 0xFE: "comment"}


def png_chunks(data):
    pos = 8
    while pos + 8 <= len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        yield data[pos + 4:pos + 8], pos, pos + 12 + n
        pos += 12 + n


def jpeg_segments(data):
    """(marker, start, end) of the segments before the image data."""
    pos = 2
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker == 0xDA:                                # start of scan: the rest is image data
            break
        n = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        yield marker, pos, pos + 2 + n
        pos += 2 + n


def scan_image(path):
    data = path.read_bytes()
    if data.startswith(PNG_SIG):
        return [name.decode("latin1") for name, _, _ in png_chunks(data) if name in PNG_HIDDEN]
    if data[:2] == b"\xff\xd8":
        return [JPEG_HIDDEN[m] for m, _, _ in jpeg_segments(data) if m in JPEG_HIDDEN]
    return []


def clean_image(path):
    """Rewrite a PNG or JPEG without its hidden metadata. Pixels are untouched."""
    data = path.read_bytes()
    if data.startswith(PNG_SIG):
        keep = [data[:8]] + [data[s:e] for name, s, e in png_chunks(data) if name not in PNG_HIDDEN]
        out = b"".join(keep)
    elif data[:2] == b"\xff\xd8":
        drop = [(s, e) for m, s, e in jpeg_segments(data) if m in JPEG_HIDDEN]
        out, last = bytearray(), 0
        for s, e in drop:
            out += data[last:s]
            last = e
        out += data[last:]
        out = bytes(out)
    else:
        return False
    if out != data:
        path.write_bytes(out)
        return True
    return False


# ------------------------------------------------------------------------------------------------ walking
def files_under(paths):
    for p in paths:
        p = Path(p)
        if p.is_file():
            yield p
            continue
        for f in sorted(p.rglob("*")):
            if f.is_file() and not (set(f.relative_to(p).parts[:-1]) & SKIP_DIRS):
                yield f


def run(paths, fix=False, out=print):
    findings = changed = 0
    for f in files_under(paths):
        suffix = f.suffix.lower() or f.name.lower()
        if suffix in (".png", ".jpg", ".jpeg"):
            hidden = scan_image(f)
            if hidden:
                findings += 1
                out(f"{f}: hidden metadata: {', '.join(sorted(set(hidden)))}")
                if fix and clean_image(f):
                    changed += 1
                    out("    cleaned")
            continue
        if suffix not in TEXT_SUFFIXES and f.suffix.lower() not in TEXT_SUFFIXES:
            continue
        raw = f.read_bytes()
        if b"\0" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            findings += 1
            out(f"{f}: not valid UTF-8 (check the encoding)")
            continue
        found = classify(text, f.suffix.lower())
        if not found:
            continue
        findings += 1
        for kind, hits in found.items():
            where = ", ".join(f"{ln}:{col} U+{cp:04X}" for ln, col, cp in hits[:6])
            more = f" (+{len(hits) - 6} more)" if len(hits) > 6 else ""
            out(f"{f}: {len(hits)} x {kind}: {where}{more}")
        if fix:
            new = clean_text(text, f.suffix.lower(), keep_bom=f.suffix.lower() in KEEP_BOM)
            if new != text:
                f.write_bytes(new.encode("utf-8"))
                changed += 1
                out("    cleaned")
    return findings, changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=[str(Path(__file__).resolve().parents[1])])
    ap.add_argument("--fix", action="store_true", help="remove what is found (text and PNG/JPEG metadata)")
    a = ap.parse_args(argv)
    findings, changed = run(a.paths, a.fix)
    if not findings:
        print("clean: no invisible characters, exotic spaces or hidden metadata found")
        return 0
    print(f"{findings} file(s) with findings" + (f", {changed} cleaned" if a.fix else " (run with --fix to clean)"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
