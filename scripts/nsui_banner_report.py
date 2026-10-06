#!/usr/bin/env python3
"""Lists the 3DS banners inside NSUI's program file, to work out which one is which console.

    python scripts/nsui_banner_report.py "<NSUI folder>\\New Super Ultimate Injector for 3DS.exe" [previews folder]

It reads the program file, finds every 3DS banner (CBMD) stored in it, checks each one, and writes
nsui-banners.txt: for each banner its size, its texture and part names, and what kind it looks like (a frame, a
console + TV, or another kind). With a previews folder it also saves a picture of each banner there, for you to look
at. Nothing is changed, copied or sent anywhere: the report holds only names and sizes, and the previews stay on
your PC.
"""

import hashlib
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdinjector import cgfx, model3d, nsui  # noqa: E402

MAX_PROGRAM = 1024 * 1024 * 1024


def banner_spans(data):
    """(start, end) of each complete-looking banner in `data`."""
    at = data.find(b"CBMD")
    while at >= 0:
        if at + nsui.HEADER <= len(data):
            words = struct.unpack_from("<%dI" % (nsui.HEADER // 4), data, at)
            common, cwav = words[2], words[-1]
            if words[1] == 0 and common == nsui.HEADER and cwav and at + cwav + 0x10 <= len(data) \
                    and data[at + cwav:at + cwav + 4] == b"CWAV":
                size = struct.unpack_from("<I", data, at + cwav + 0xC)[0]
                if 0x40 <= size <= nsui.MAX_BANNER:
                    yield at, at + cwav + size
        at = data.find(b"CBMD", at + 4)


def model_spans(data, taken):
    """(start, end) of each 3D model (CGFX) stored on its own, outside the banners already found."""
    at = data.find(b"CGFX")
    while at >= 0:
        if data[at + 4:at + 8] == b"\xff\xfe\x14\x00" and data[at + 0x14:at + 0x18] == b"DATA" \
                and not any(s <= at < e for s, e in taken):
            size = struct.unpack_from("<I", data, at + 12)[0]
            if 0x40 <= size <= cgfx.MAX_MODEL and at + size <= len(data):
                yield at, at + size
        at = data.find(b"CGFX", at + 4)


def describe_model(model):
    lines = ["  textures: " + ", ".join(f"{n} {t['w']}x{t['h']} f{t['fmt']}" for n, t in cgfx.textures(model).items())]
    try:
        lines.append("  parts: " + ", ".join(f"{m['node']}({m['texture']}, {len(m['tris'])})"
                                             for m in model3d.read_meshes(model)))
    except nsui.MODEL_ERRORS as e:
        lines.append(f"  parts: can't be read ({e})")
    return lines


def describe(path):
    """Lines describing one banner file."""
    b = nsui.Banner(path, require_nsui=False).validate()
    main = bytes(b.common)
    plate, picture, screen = nsui._parts(main)
    kind = "frame" if picture else "console + TV" if screen else "plate only" if plate else "other"
    lines = [f"  kind: {kind}; title plate: {plate}; picture: {picture}; TV screen: {screen}",
             f"  language models: {len(b.lang_offs)}; sound: {'yes' if b.cwav_off else 'no'}"]
    for label, model in (("main", main), ("language", b.language_model())):
        if not model:
            continue
        texs = cgfx.textures(model)
        lines.append(f"  {label} textures: " + ", ".join(f"{n} {t['w']}x{t['h']} f{t['fmt']}" for n, t in texs.items()))
        try:
            meshes = model3d.read_meshes(model)
            lines.append(f"  {label} parts: " + ", ".join(f"{m['node']}({m['texture']}, {len(m['tris'])})" for m in meshes))
        except nsui.MODEL_ERRORS as e:
            lines.append(f"  {label} parts: can't be read ({e})")
    return lines


def main(program, previews=None):
    program = Path(program)
    if program.stat().st_size > MAX_PROGRAM:
        sys.exit(f"{program.name} is too big to be NSUI's program file.")
    data = program.read_bytes()
    out, seen = [f"Banners in {program.name} ({len(data)} bytes)", ""], {}
    if previews:
        Path(previews).mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.TemporaryDirectory() as t:
        for start, end in banner_spans(data):
            blob = data[start:end]
            digest = hashlib.sha1(blob).hexdigest()[:12]
            if digest in seen:
                out.append(f"#{seen[digest]} again at {start:#x}")
                continue
            count += 1
            seen[digest] = count
            out.append(f"#{count} at {start:#x}, {end - start} bytes, id {digest}")
            path = Path(t) / f"{count}.bin"
            path.write_bytes(blob)
            try:
                out += describe(path)
            except (nsui.NSUIError,) + nsui.MODEL_ERRORS as e:
                out.append(f"  can't be read: {e}")
                continue
            if previews:
                try:
                    nsui.preview_image(path, "Game Title", "1993", (400, 240)).save(Path(previews) / f"{count:03d}.png")
                except (nsui.NSUIError,) + nsui.MODEL_ERRORS as e:
                    out.append(f"  no preview: {e}")
    taken = list(banner_spans(data))
    models = 0
    for start, end in model_spans(data, taken):
        blob = data[start:end]
        digest = hashlib.sha1(blob).hexdigest()[:12]
        if digest in seen:
            continue
        models += 1
        seen[digest] = f"M{models}"
        out.append(f"model M{models} at {start:#x}, {end - start} bytes, id {digest}")
        try:
            out += describe_model(blob)
        except nsui.MODEL_ERRORS as e:
            out.append(f"  can't be read: {e}")
    out.insert(1, f"{count} different banners and {models} separate 3D models found")
    Path("nsui-banners.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{count} different banners and {models} separate 3D models found; the list is in "
          f"{Path('nsui-banners.txt').resolve()}")
    if previews:
        print(f"pictures of them are in {Path(previews).resolve()}")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    main(*sys.argv[1:])
