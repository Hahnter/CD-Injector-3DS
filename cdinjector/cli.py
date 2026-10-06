"""Command line:
    cd_injector.py build <game.cue or folder> [--bios ...] [--title ...]
"""

import argparse
import sys
from pathlib import Path

from . import APP_NAME, VERSION
from . import banner as bn
from .builder import BuildError, BuildOptions, build


def _build(a):
    color = None
    if a.frame_color:
        color = bn.parse_color(a.frame_color)
        if not color:
            print(f"error: {a.frame_color!r} isn't a colour: use the form #rrggbb, for example #d63030", file=sys.stderr)
            return 1
    opt = BuildOptions(game=a.game, bios=a.bios, title=a.title, publisher=a.publisher, year=a.year,
                       system=a.system, out_dir=a.out, image=a.image, icon_fit=a.icon_fit,
                       icon_file=a.icon_file, banner_file=a.banner_file, frame_color=color,
                       sound_file=a.sound, plate_font=a.plate_font, lookup=not a.no_lookup, pictures_dir=a.pictures)
    last = [-1]

    def progress(frac, msg):
        pct = int(frac * 100)
        if pct != last[0]:
            last[0] = pct
            msg = msg.replace(chr(0x2026), "...")                # plain dots: every console can show them
            print(f"\r[{pct:3d}%] {msg:<50}", end="", flush=True)

    try:
        cia = build(opt, progress)
    except BuildError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    print(f"\nbuilt   {cia}  ({cia.stat().st_size / 1048576:.1f} MB)")
    print(f"game    {opt.info['title']} - {opt.info['system']} - title ID {opt.info['title_id']}")
    if opt.info.get("recognised"):
        print(f"found   {opt.info['recognised']} (title, publisher and year filled in where you gave none)")
    if opt.info.get("picture"):
        print(f"picture {opt.info['picture']}")
    print(f"banner  {opt.info['banner_kind']}")
    for n in opt.info["notes"]:
        print(f"BIOS    {n}")
    return 0


def main(argv=None):
    # A console or pipe in the Windows code page can't show every title or path (Japanese, say): print what it can
    # instead of stopping with an error after the CIA is already made.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="cd_injector", description=f"{APP_NAME} {VERSION}")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="make a CIA from a PC Engine CD or Sega CD game")
    b.add_argument("game", type=Path, help="the game's .cue file, or its folder")
    b.add_argument("--bios", type=Path, help="BIOS file or folder (default: search near the game)")
    b.add_argument("--title", default="", help="default: the recognised game's title, else from the .cue file name")
    b.add_argument("--publisher", default="")
    b.add_argument("--year", default="")
    b.add_argument("--image", type=Path, help="title screen for the banner and the icon")
    b.add_argument("--icon-fit", choices=["height", "width"], default="height")
    b.add_argument("--system", choices=["pce", "segacd"], default="")
    b.add_argument("--out", type=Path, help="output folder (default: next to the game folder)")
    b.add_argument("--frame-color", default="", help="colour of the banner's frame, #rrggbb (default: the system's own)")
    b.add_argument("--icon-file", type=Path, help="use a ready-made icon (.icn / NSUI icon .bin), or a picture")
    b.add_argument("--banner-file", type=Path, help="use a ready-made banner (.bnr / NSUI banner .bin), or a picture")
    b.add_argument("--sound", type=Path, help=".wav or .bcwav banner sound")
    b.add_argument("--plate-font", type=Path, help="font file (.ttf) for the title plate's text")
    b.add_argument("--pictures", type=Path, help="folder to find the game's picture in (default: RetroArch's thumbnails)")
    b.add_argument("--no-lookup", action="store_true",
                   help="don't fill in the title, publisher, year and picture from what the disc is recognised as")
    b.set_defaults(run=_build)

    a = ap.parse_args(argv)
    return a.run(a)
