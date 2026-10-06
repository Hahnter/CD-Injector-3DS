#!/usr/bin/env python3
"""Writes cdinjector/thumbnail_names.py: the discs whose picture libretro's thumbnails keep under a slightly different
name (another capital letter or punctuation mark) than the disc's Redump name.

    git clone --depth 1 --filter=blob:none --no-checkout https://github.com/libretro-thumbnails/<repo>.git
    git -C <repo> ls-tree -r --name-only HEAD > <repo>.txt          (for each repo in download.REPOS)
    python scripts/make_thumbnail_names.py <folder with the .txt listings>

The app already tries a name without its language, revision and similar notes ("Dune (USA) (En,Fr,De,Es,It)" finds
"Dune (USA)"), so only names that still don't match are listed. Run it again after libretro renames pictures.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdinjector import gameinfo as gi  # noqa: E402
from cdinjector.download import REPOS  # noqa: E402
from cdinjector.gamelist import DISCS  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "cdinjector" / "thumbnail_names.py"


def key(name):
    return re.sub(r"[^a-z0-9()]+", " ", name.lower()).strip()


def main(listings):
    lines = ['"""Discs whose picture libretro\'s thumbnails keep under another name: {system: {Redump name: thumbnail',
             'name}}. Written by scripts/make_thumbnail_names.py from the file names in libretro-thumbnails',
             '(https://github.com/libretro-thumbnails); don\'t edit."""', "", "NAMES = {"]
    for system, repo in REPOS.items():
        names = set()
        for line in (Path(listings) / f"{repo}.txt").read_text(encoding="utf-8").splitlines():
            kind, _, file = line.strip().partition("/")
            if kind in gi.THUMBNAIL_KINDS and file.endswith(".png") and "/" not in file:
                names.add(file[:-4])
        keyed = {}
        for n in sorted(names):
            keyed.setdefault(key(n), n)
        found = {}
        for disc in DISCS[system]:
            redump = disc[3]
            if not redump or any(gi.thumbnail_file_name(c) in names for c in gi.name_variants(redump)):
                continue
            for c in gi.name_variants(redump):
                match = keyed.get(key(gi.thumbnail_file_name(c)))
                if match:
                    found[redump] = match
                    break
        lines.append(f'    "{system}": {{')
        lines += [f"        {k!r}: {v!r}," for k, v in sorted(found.items())]
        lines.append("    },")
        print(f"{system}: {len(found)} names")
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
