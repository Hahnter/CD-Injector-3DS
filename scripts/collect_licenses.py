#!/usr/bin/env python3
"""Copies the licence texts of what PyInstaller packs into the app (used by build_windows.ps1):
Python itself, Tcl, Tk and Pillow, from the Python that builds the app.

    collect_licenses.py <folder to write them to>

Tcl/Tk 8.6 keeps license.terms in tcl/tcl8.6 and tcl/tk8.6; Tcl/Tk 9 keeps it inside tcl/libtcl*.zip and
tcl/libtk*.zip. Both layouts are handled, and a missing licence stops the build.
"""

import importlib.metadata
import shutil
import sys
import zipfile
from pathlib import Path


def tcl_tk_licence(tcl_dir, name):
    """The license.terms text of "tcl" or "tk"."""
    for folder in sorted(tcl_dir.glob(f"{name}[0-9]*")):
        if (folder / "license.terms").is_file():
            return (folder / "license.terms").read_bytes()
    for archive in sorted(tcl_dir.glob(f"lib{name}[0-9]*.zip")):
        with zipfile.ZipFile(archive) as z:
            for entry in z.namelist():
                if entry == f"{name}_library/license.terms":
                    return z.read(entry)
    raise SystemExit(f"No {name} license.terms found in {tcl_dir}")


def main(dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    home = Path(sys.base_prefix)
    shutil.copyfile(home / "LICENSE.txt", dest / "Python-LICENSE.txt")
    for name, label in (("tcl", "Tcl"), ("tk", "Tk")):
        (dest / f"{label}-license.txt").write_bytes(tcl_tk_licence(home / "tcl", name))
    pillow = [f for f in importlib.metadata.distribution("pillow").files if f.name == "LICENSE"]
    if not pillow:
        raise SystemExit("Pillow's LICENSE file not found")
    shutil.copyfile(pillow[0].locate(), dest / "Pillow-LICENSE.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
