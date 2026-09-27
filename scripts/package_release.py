#!/usr/bin/env python3
"""Zips the built app folder and writes SHA256SUMS.txt (used by build_windows.ps1).

    package_release.py <app folder> <zip to make> <other release file> <SHA256SUMS.txt>

The zip holds the app folder itself (so it unzips into "CD Injector 3DS/") with "/" in every name, as the zip
format requires, and the checksum file has one "<sha256>  <file name>" line per file with "\n" line ends.
"""

import hashlib
import sys
import zipfile
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def main(app, zip_path, other, sums):
    app, zip_path = Path(app), Path(zip_path)
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                z.write(f, (Path(app.name) / f.relative_to(app)).as_posix())
    lines = [f"{sha256(p)}  {Path(p).name}\n" for p in (zip_path, Path(other))]
    Path(sums).write_bytes("".join(lines).encode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:5]))
