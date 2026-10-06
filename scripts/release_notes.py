#!/usr/bin/env python3
"""Writes the GitHub release notes for the app's current version, from its section of CHANGELOG.md.

    release_notes.py [notes.md]          (default: print them)

The notes are the version's introduction and changes, then how to download it and what each release file is.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cdinjector import VERSION  # noqa: E402

REPO = "https://github.com/Hahnter/CD-Injector-3DS"


def section(changelog, version):
    """The text of `version`'s section of the changelog, without its heading."""
    m = re.search(rf"^## {re.escape(version)} \([^)]*\)\n(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    if not m or "unreleased" in m.group(0).splitlines()[0]:
        raise SystemExit(f"CHANGELOG.md has no dated section for {version}")
    return m.group(1).strip()


def notes(version, changelog=None):
    base = f"CD-Injector-3DS-v{version}"
    changelog = changelog if changelog is not None else (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return f"""{section(changelog, version)}

**Download** `{base}-windows.zip`, unzip it and run `CD-Injector-3DS.exe`. You supply the game (`.cue` + `.bin`) \
and the BIOS; none are included. See the [README]({REPO}#readme) for how to use it and \
[CHANGELOG.md]({REPO}/blob/main/CHANGELOG.md) for all changes.

### Files
- `{base}-windows.zip`: the app.
- `{base}-emulator-source.tar.gz`: the complete source of the patched emulators inside every CIA (required by \
PicoDrive's license).
- `SHA256SUMS.txt`: checksums. In PowerShell: `Get-FileHash .\\{base}-windows.zip -Algorithm SHA256`

The app isn't code-signed, so Windows SmartScreen may warn the first time you run it. Never share the CIAs you make: \
they contain the game and the BIOS.
"""


if __name__ == "__main__":
    text = notes(VERSION)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
