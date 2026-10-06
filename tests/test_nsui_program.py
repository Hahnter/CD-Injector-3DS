"""Checks on finding NSUI's banner parts inside its program file."""

import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from cdinjector import banner as bn  # noqa: E402
from cdinjector import nsui, nsui_program, resources  # noqa: E402

# NSUI banners to stand in for the parts of NSUI's program (see test_banner.py); they can't be part of this
# repository, so the tests that need them are skipped otherwise.
BANNERS = [Path(p) for p in os.environ.get("CDI_TEST_BANNERS", "").split(os.pathsep) if p and Path(p).is_file()]


def _7bit(n):
    out = bytearray()
    while n >= 0x80:
        out.append(n & 0x7F | 0x80)
        n >>= 7
    return bytes(out + bytes([n]))


def resource_table(items):
    """A .NET resource table (as System.Resources.ResourceWriter writes one) holding `items`: [(name, bytes)]."""
    reader = b"System.Resources.ResourceReader, mscorlib"
    kind = b"System.Resources.RuntimeResourceSet"
    header = _7bit(len(reader)) + reader + _7bit(len(kind)) + kind
    out = bytearray(nsui_program.RESOURCES_MAGIC + struct.pack("<II", 1, len(header)) + header)
    out += struct.pack("<iii", 2, len(items), 1) + _7bit(13) + b"System.Byte[]"
    out += (b"PAD" * 3)[:-len(out) % 8]
    names, values, positions = bytearray(), bytearray(), []
    for name, data in items:
        positions.append(len(names))
        encoded = name.encode("utf-16-le")
        names += _7bit(len(encoded)) + encoded + struct.pack("<i", len(values))
        values += _7bit(nsui_program.BYTES) + struct.pack("<i", len(data)) + data
    out += struct.pack("<%di" % len(items), *range(len(items)))           # hashes: not used when reading
    out += struct.pack("<%di" % len(items), *positions)
    out += struct.pack("<i", len(out) + 4 + len(names))
    return bytes(out + names + values)


class ResourceTests(unittest.TestCase):
    def test_resources_are_found_by_name(self):
        table = resource_table([("genesis_cgfx", b"CGFX" + bytes(60)), ("genesis_bcwav", b"CWAV" + bytes(28))])
        program = b"MZ" + bytes(1000) + struct.pack("<i", len(table)) + table + bytes(100)
        found = {name: program[o:o + size] for name, o, size in nsui_program.resources(program)}
        self.assertEqual(found, {"genesis_cgfx": b"CGFX" + bytes(60), "genesis_bcwav": b"CWAV" + bytes(28)})

    def test_a_damaged_table_is_skipped(self):
        table = resource_table([("a", b"x" * 10)])
        for cut in (8, 40, len(table) - 5):
            self.assertEqual(nsui_program.resources(b"MZ" + table[:cut]), [])

    def test_sounds_are_found_with_their_length(self):
        cwav = bytearray(0x80)
        cwav[0:6] = b"CWAV\xff\xfe"
        struct.pack_into("<I", cwav, 0xC, len(cwav))
        cwav[0x40:0x44] = b"INFO"
        struct.pack_into("<5I", cwav, 0x4C, 22050, 0, 44100, 0, 2)
        program = bytes(10) + bytes(cwav) + bytes(10)
        self.assertEqual(nsui_program.sound_spans(program), [(10, 10 + 0x80, 22050, 2, 2.0)])


def a_program(folder, items):
    """A stand-in for NSUI's program file holding `items` ([(name, bytes)]) as resources."""
    table = resource_table(items)
    path = Path(folder) / "New Super Ultimate Injector for 3DS.exe"
    path.write_bytes(b"MZ" + bytes(4096) + struct.pack("<i", len(table)) + table + bytes(4096))
    return path


class ReadPartsTests(unittest.TestCase):
    def test_parts_are_read_by_name(self):
        with tempfile.TemporaryDirectory() as t:
            program = a_program(t, [("banner_wav_pce", b"RIFF1234WAVE"), ("banner_cgfx_pce", b"CGFX" + bytes(8))])
            self.assertEqual(nsui_program.read_parts(program, ["banner_cgfx_pce"]), {"banner_cgfx_pce": b"CGFX" + bytes(8)})

    def test_a_program_without_the_parts_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            program = a_program(t, [("something_else", b"x")])
            with self.assertRaisesRegex(nsui_program.NSUIProgramError, "banner_cgfx_mega_drive"):
                nsui_program.read_parts(program, ["banner_cgfx_mega_drive"])
            (Path(t) / "empty.exe").write_bytes(b"")
            for bad in (Path(t) / "empty.exe", Path(t) / "missing.exe"):
                with self.assertRaises(nsui_program.NSUIProgramError):
                    nsui_program.read_parts(bad, ["banner_cgfx_pce"])

    def test_the_build_checks_the_nsui_options_first(self):
        from cdinjector.builder import BuildError, BuildOptions, preflight
        with tempfile.TemporaryDirectory() as t:
            for opt in (BuildOptions(game=Path(t), nsui_program=Path(t) / "missing.exe"),
                        BuildOptions(game=Path(t), nsui_program=a_program(t, []), nsui_console="nes")):
                with self.assertRaises(BuildError):
                    preflight(opt)

    def test_a_banner_for_another_console_is_refused(self):
        with self.assertRaises(nsui_program.NSUIProgramError):
            nsui_program.build_banner("x.exe", "genesis", "pce", "out.bin", ".")
        self.assertEqual([k for k, _ in nsui_program.consoles_for("pce")],
                         ["pc_engine", "turbografx_16", "by_region", "frame"])
        self.assertEqual([k for k, _ in nsui_program.consoles_for("segacd")], ["genesis", "frame"])


def _bannertool_here():
    try:
        resources.tool("bannertool")
        return True
    except FileNotFoundError:
        return False


@unittest.skipUnless(BANNERS and _bannertool_here(), "needs NSUI banner files (set CDI_TEST_BANNERS) and bannertool")
class BuildTests(unittest.TestCase):
    """NSUI's banners made from the parts of a stand-in program file: each exported NSUI banner given to the tests
    gives its main model (and its first language model) as the parts of a console of the same kind."""

    def stand_in(self, folder):
        bn.chime_wav(Path(folder) / "tune.wav")
        tune = (Path(folder) / "tune.wav").read_bytes()
        items, consoles = [("banner_wav_gen", tune), ("banner_wav_pce", tune)], []
        for path in BANNERS:
            b = nsui.Banner(path)
            if b.is_frame and "frame" not in consoles:
                items.append(("banner_cgfx_gba", bytes(b.common)))
                consoles += [("frame", "segacd"), ("frame", "pce")]
            elif b.lang_offs and "pc_engine" not in consoles:
                items += [("banner_cgfx_pce", bytes(b.common)), ("banner_bcmdl_pc_engine", b.language_model()),
                          ("banner_bcmdl_turbografx_16", b.language_model())]
                consoles += [("pc_engine", "pce"), ("turbografx_16", "pce"), ("by_region", "pce")]
            elif not b.is_frame and not b.lang_offs and "genesis" not in consoles:
                items.append(("banner_cgfx_mega_drive", bytes(b.common)))
                consoles.append(("genesis", "segacd"))
        return a_program(folder, items), consoles

    def test_each_console_banner_is_made_and_takes_a_game(self):
        calls = []
        real_run = nsui_program.run_tool

        def run(cmd, timeout=900, cwd=None):
            calls.append((cmd, cwd))
            return real_run(cmd, timeout, cwd)
        with tempfile.TemporaryDirectory() as t, mock.patch.object(nsui_program, "run_tool", run):
            program, consoles = self.stand_in(t)
            for console, system in consoles:
                out = nsui_program.build_banner(program, console, system, Path(t) / "made" / f"{console}.bin",
                                                Path(t) / f"work-{console}-{system}")
                b = nsui.Banner(out).validate()
                langs = len(nsui_program.CONSOLES[console].languages and nsui_program.LANGUAGE_OPTIONS)
                self.assertEqual(len(b.lang_offs), langs, console)
                self.assertTrue(b.plate and (b.picture or b.screen), console)
                if b.screen:                                       # NSUI's sample game is blacked out
                    name, box = b.screen
                    self.assertEqual(b.texture(name).convert("RGB").crop(box).getextrema(), ((0, 0),) * 3, console)
                made, note = nsui.prepare(out, "Lunar: The Silver Star", "1992", t,
                                          picture=Image.new("RGB", (256, 224), (200, 30, 30)))
                self.assertEqual(note, "your picture and title added", console)
        for cmd, cwd in calls:                       # bannertool only gets plain relative names, inside the work folder
            self.assertIsNotNone(cwd)
            for arg in cmd[1:]:
                self.assertTrue(arg.isascii() and not Path(arg).is_absolute(), arg)


if __name__ == "__main__":
    unittest.main()
