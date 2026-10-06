#!/usr/bin/env python3
"""Lists the 3DS banners inside NSUI's program file, to work out which one is which console.

    python scripts/nsui_banner_report.py "<NSUI folder>\\New Super Ultimate Injector for 3DS.exe" [previews folder]

It reads the program file, finds every 3DS banner (CBMD) and every separate 3D model (CGFX) stored in it, checks
each one, and writes nsui-banners.txt: for each its size, its texture and part names, and what kind it looks like (a
frame, a console + TV, or another kind). With a previews folder it also saves there, for you to look at, a picture of
each banner and model as the 3DS would draw it (with whatever title its plate holds) and a picture of each of its
textures, in a folder per banner or model. Nothing is changed or sent anywhere: the report holds only names and
sizes, and the pictures stay on your PC unless you choose to share them.
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


def draw(main, lang=None):
    """A picture of a 3D model as the Home Menu draws it, with a language model's textures in place of the main
    one's of the same name and the language model's own parts; None when there's nothing to draw."""
    textures = nsui._language_textures(lang) if lang else {}
    parts = model3d.textured(main, textures) + (model3d.textured(lang) if lang else [])
    return model3d.render(parts, 0.0, (400, 240)) if parts else None


def save_textures(models, folder):
    """Each texture of each model in `models` ([(label, CGFX)]) as a PNG in `folder`, each different picture once."""
    folder.mkdir(parents=True, exist_ok=True)
    seen = set()
    for label, model in models:
        for name, t in cgfx.textures(model).items():
            try:
                img = cgfx.read_texture(model, t)
            except nsui.MODEL_ERRORS:
                continue
            key = (name, hashlib.sha1(img.tobytes()).hexdigest())
            if key in seen:
                continue
            seen.add(key)
            img.save(folder / f"{label}_{name}.png")


def save_previews(folder, main, langs):
    """The banner or model drawn, and its textures, in `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    picture = draw(main, langs[0] if langs else None)
    if picture is not None:
        picture.save(folder / "banner.png")
    save_textures([("main", main)] + [(f"lang{i + 1}", m) for i, m in enumerate(langs)], folder)


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
    langs = [m for _, m in b.language_blocks()]
    if plate is None and langs:                         # the plate's texture may be in the language models only
        lang_texs = cgfx.textures(langs[0])
        try:
            billboards = {m["texture"] for m in model3d.read_meshes(main) if m["billboard"]}
        except nsui.MODEL_ERRORS:
            billboards = set()
        plate = next((f"{n} (in the language models)" for n in sorted(billboards) if n in lang_texs
                      and lang_texs[n]["fmt"] == cgfx.PICA_LA8 and (lang_texs[n]["w"], lang_texs[n]["h"]) == (256, 64)),
                     None)
    slots = [i for i, w in enumerate(b.words[3:3 + nsui.MAX_LANGUAGES]) if w]
    names = {hashlib.sha1(m).hexdigest() for m in langs}
    lines = [f"  kind: {kind}; title plate: {plate}; picture: {picture}; TV screen: {screen}",
             f"  language models: {len(b.lang_offs)} ({len(names)} different), in slots {slots}; "
             f"sound: {'yes' if b.cwav_off else 'no'}"]
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
                    b = nsui.Banner(path, require_nsui=False)
                    save_previews(Path(previews) / f"{count:03d}", bytes(b.common), [m for _, m in b.language_blocks()])
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
            continue
        if previews:
            try:
                save_previews(Path(previews) / f"M{models:02d}", blob, [])
            except nsui.MODEL_ERRORS as e:
                out.append(f"  no preview: {e}")
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
