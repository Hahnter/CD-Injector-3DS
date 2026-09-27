"""Security and robustness tests: hostile, damaged or oversized input must give a clear error, never a crash,
a hang, a huge memory use, or a file from outside the game's folder in a CIA.

Files chosen by the user are the only untrusted input this app has (it makes no network connections), so the tests
feed it broken .cue sheets, broken banner and icon files, awkward titles and a damaged settings file.

Special characters are built with chr() so this file stays plain ASCII (see scripts/hygiene.py).
"""

import json
import os
import random
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cdinjector import builder, cgfx, disc, nsui  # noqa: E402

# How many damaged copies to try per banner. The default keeps a normal test run quick; set FUZZ_ITERATIONS=2000 for a
# long run.
FUZZ = int(os.environ.get("FUZZ_ITERATIONS", "120"))

# Real NSUI banners (they can't be shipped with the tests): list them in CDI_TEST_BANNERS, separated by the system's
# path separator (";" on Windows). Tests that need them are skipped otherwise.
BANNERS = [Path(p) for p in os.environ.get("CDI_TEST_BANNERS", "").split(os.pathsep) if p and Path(p).is_file()]


def write(path, data):
    Path(path).write_bytes(data)
    return Path(path)


class SafeNameTests(unittest.TestCase):
    def test_path_separators_and_forbidden_characters_are_removed(self):
        name = builder.safe_name("..\\..\\Windows\\System32/evil:<>|?*")
        self.assertNotRegex(name, r'[\\/:<>|?*]')

    def test_dots_only_gives_a_default(self):
        self.assertEqual(builder.safe_name(".."), "game")
        self.assertEqual(builder.safe_name("..."), "game")
        self.assertEqual(builder.safe_name(""), "game")

    def test_reserved_device_names_are_changed(self):
        for n in ("CON", "nul", "Com1", "LPT9", "aux.cia", "PRN"):
            self.assertNotIn(builder.safe_name(n).split(".")[0].upper(), builder.RESERVED_NAMES, n)

    def test_control_and_invisible_characters_are_removed(self):
        title = "Game" + chr(0) + chr(7) + chr(0x200B) + chr(0x202E) + "Name" + chr(0xA0) + "X"
        name = builder.safe_name(title)
        self.assertEqual(name, "GameName X")
        self.assertTrue(all(ch.isprintable() for ch in name))

    def test_length_is_limited(self):
        self.assertLessEqual(len(builder.safe_name("A" * 5000)), 120)

    def test_trailing_dots_and_spaces_are_removed(self):
        self.assertFalse(builder.safe_name("Sonic CD. . ").endswith((".", " ")))


class CueTests(unittest.TestCase):
    def make(self, tmp, cue_text, files=("game.bin",)):
        tmp = Path(tmp)
        for f in files:
            write(tmp / f, b"\0" * 64)
        return write(tmp / "game.cue", cue_text.encode("utf-8"))

    def test_a_normal_cue_works(self):
        with tempfile.TemporaryDirectory() as t:
            cue = self.make(t, 'FILE "game.bin" BINARY\n  TRACK 01 MODE1/2352\n')
            self.assertEqual(disc.read_cue(cue).tracks, ["game.bin"])

    def test_traversal_in_a_track_name_only_ever_uses_the_local_file(self):
        with tempfile.TemporaryDirectory() as t:
            outer = Path(t)
            write(outer / "secret.bin", b"top secret")                      # a file OUTSIDE the game's folder
            game = outer / "game"
            game.mkdir()
            cue = write(game / "game.cue", b'FILE "..\\secret.bin" BINARY\nFILE "../../secret.bin" BINARY\n')
            with self.assertRaises(disc.DiscError):                         # only a same-named file next to the cue counts
                disc.read_cue(cue)

    def test_absolute_paths_are_reduced_to_the_file_name(self):
        with tempfile.TemporaryDirectory() as t:
            cue = self.make(t, 'FILE "C:\\Windows\\system32\\game.bin" BINARY\n')
            self.assertEqual(disc.read_cue(cue).tracks, ["game.bin"])

    def test_huge_cue_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            cue = write(Path(t) / "game.cue", b"REM " + b"x" * (disc.MAX_CUE_BYTES + 10))
            with self.assertRaises(disc.DiscError):
                disc.read_cue(cue)

    def test_too_many_tracks_are_refused(self):
        with tempfile.TemporaryDirectory() as t:
            text = "".join(f'FILE "t{i}.bin" BINARY\n' for i in range(disc.MAX_TRACKS + 5))
            cue = self.make(t, text, files=[f"t{i}.bin" for i in range(disc.MAX_TRACKS + 5)])
            with self.assertRaises(disc.DiscError):
                disc.read_cue(cue)

    def test_garbage_bytes_do_not_crash(self):
        with tempfile.TemporaryDirectory() as t:
            cue = write(Path(t) / "game.cue", bytes(random.Random(1).randrange(256) for _ in range(4000)))
            with self.assertRaises(disc.DiscError):
                disc.read_cue(cue)

    def test_the_link_check_with_a_pretend_link(self):
        """The same rule as below, checked without needing permission to create real links."""
        with tempfile.TemporaryDirectory() as t:
            cue = self.make(t, 'FILE "game.bin" BINARY' + chr(10))
            real_resolve = Path.resolve

            def fake(self, *a, **k):
                if self.name == "game.bin":
                    return Path(t).parent / "elsewhere" / "game.bin"
                return real_resolve(self, *a, **k)
            with mock.patch.object(Path, "resolve", fake):
                with self.assertRaises(disc.DiscError):
                    disc.read_cue(cue)

    def test_a_link_to_a_file_elsewhere_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            outer = Path(t)
            real = write(outer / "elsewhere.bin", b"not part of this game")
            game = outer / "game"
            game.mkdir()
            try:
                os.symlink(real, game / "game.bin")
            except (OSError, NotImplementedError):
                self.skipTest("this account can't create symbolic links")
            cue = write(game / "game.cue", b'FILE "game.bin" BINARY\n')
            with self.assertRaises(disc.DiscError):
                disc.read_cue(cue)


class CgfxTests(unittest.TestCase):
    def test_round_trip(self):
        data = bytes(random.Random(5).randrange(4) for _ in range(20000))
        self.assertEqual(cgfx.lz11_decompress(cgfx.lz11_compress(data)), data)

    def test_a_decompression_bomb_is_refused_quickly(self):
        # a header claiming 8 MB, followed by tokens that copy the maximum every time
        bomb = bytes([0x11, 0x00, 0x00, 0x80]) + b"\xff" + b"\x00" * 2000
        t0 = time.time()
        with self.assertRaises(cgfx.CGFXError):
            cgfx.lz11_decompress(bomb)
        self.assertLess(time.time() - t0, 1.0)

    def test_a_size_of_gigabytes_is_refused_before_allocating(self):
        header = bytes([0x11, 0, 0, 0]) + struct.pack("<I", 0xF0000000)
        with self.assertRaises(cgfx.CGFXError):
            cgfx.lz11_decompress(header + b"\0" * 20)

    def test_truncated_and_wrong_tag_data(self):
        good = cgfx.lz11_compress(b"hello world" * 100)
        for bad in (good[:-3], good[:6], b"", b"\x10" + good[1:], b"\x11\x05"):
            with self.assertRaises(cgfx.CGFXError):
                cgfx.lz11_decompress(bad)

    def test_a_copy_from_before_the_start_is_refused(self):
        with self.assertRaises(cgfx.CGFXError):
            cgfx.lz11_decompress(bytes([0x11, 0x10, 0, 0, 0x80, 0x20, 0x05]))

    def test_short_or_random_input_is_only_ever_a_cgfx_error(self):
        rng = random.Random(9)
        for n in list(range(0, 60)) + [500, 4000]:
            blob = bytes(rng.randrange(256) for _ in range(n))
            with self.assertRaises(cgfx.CGFXError):
                cgfx.textures(blob)


class BannerFileTests(unittest.TestCase):
    def check_error(self, data, name="x.bin"):
        with tempfile.TemporaryDirectory() as t:
            f = write(Path(t) / name, data)
            with self.assertRaises(nsui.NSUIError):
                nsui.Banner(f).validate()

    def test_random_bytes_and_wrong_magic(self):
        self.check_error(bytes(random.Random(2).randrange(256) for _ in range(3000)))
        self.check_error(b"NOTB" + b"\0" * 400)

    def test_truncated_header(self):
        self.check_error(b"CBMD" + b"\0" * 20)

    def test_offsets_pointing_outside_the_file(self):
        words = [0x444D4243, 0, 0x88] + [0] * 30
        words[3] = 0x7FFFFFF0
        self.check_error(struct.pack("<%dI" % len(words), *words) + b"\0" * 100)

    def test_sound_section_without_cwav_magic(self):
        words = [0x444D4243, 0, 0x88] + [0] * 30
        words[33 if len(words) > 33 else -1] = 0x100
        blob = struct.pack("<%dI" % len(words), *words) + b"\0" * 400
        self.check_error(blob)

    def test_a_file_far_too_big_is_refused_without_reading_it(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "big.bin"
            with open(f, "wb") as h:
                h.truncate(nsui.MAX_BANNER + 1)
            with self.assertRaises(nsui.DamagedBannerError):
                nsui.Banner(f)

    def test_a_decompression_bomb_inside_a_banner(self):
        words = [0x444D4243, 0, 0x88] + [0] * 30
        bomb = bytes([0x11, 0x00, 0x00, 0x80]) + b"\xff" + b"\x00" * 3000
        with tempfile.TemporaryDirectory() as t:
            f = write(Path(t) / "bomb.bin", struct.pack("<%dI" % len(words), *words)[:0x88] + bomb)
            t0 = time.time()
            with self.assertRaises(nsui.NSUIError):
                nsui.Banner(f)
            self.assertLess(time.time() - t0, 1.5)

    @unittest.skipUnless(BANNERS, "needs an NSUI banner file")
    def test_a_banner_cut_off_inside_its_sound_is_refused(self):
        """Found by an end-to-end run: a banner cut short inside the sound section used to be accepted."""
        with tempfile.TemporaryDirectory() as t:
            for banner in BANNERS:
                b = nsui.Banner(banner)
                for cut in (b.cwav_off + 20, b.cwav_off + 1000, len(b.data) - 1):
                    f = write(Path(t) / "cut.bin", b.data[:cut])
                    with self.assertRaises(nsui.DamagedBannerError, msg=f"cut at {cut}"):
                        nsui.Banner(f)
                    with self.assertRaises(nsui.DamagedBannerError):
                        nsui.Banner(f, require_nsui=False).validate()

    @unittest.skipUnless(BANNERS, "needs an NSUI banner file")
    def test_real_banners_still_load_and_validate(self):
        for b in BANNERS:
            self.assertIn(nsui.Banner(b).validate().plate_blank(), (True, False))

    @unittest.skipUnless(BANNERS, "needs an NSUI banner file")
    def test_fuzzing_real_banners_only_ever_gives_a_clean_error(self):
        """Damage a real banner thousands of ways (flipped bytes, truncation, garbage in the header): loading it must
        either work or raise NSUIError, quickly, and never any other exception."""
        rng = random.Random(20260921)
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "fuzz.bin"
            for banner in BANNERS:
                original = banner.read_bytes()
                ok = refused = 0
                slowest = 0.0
                for i in range(FUZZ):
                    data = bytearray(original)
                    mode = i % 4
                    if mode == 0:                                            # flip a few bytes anywhere
                        for _ in range(rng.randrange(1, 8)):
                            data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
                    elif mode == 1:                                          # damage the header
                        for _ in range(rng.randrange(1, 5)):
                            data[rng.randrange(0x88)] = rng.randrange(256)
                    elif mode == 2:                                          # cut it short
                        del data[rng.randrange(1, len(data)):]
                    else:                                                    # a run of garbage in the middle
                        at = rng.randrange(len(data))
                        data[at:at + rng.randrange(1, 300)] = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 300)))
                    f.write_bytes(bytes(data))
                    t0 = time.time()
                    try:
                        nsui.Banner(f).validate()
                        ok += 1
                    except nsui.NSUIError:
                        refused += 1
                    slowest = max(slowest, time.time() - t0)
                self.assertEqual(ok + refused, FUZZ)
                self.assertLess(slowest, 5.0, "one damaged file took far too long: something is slow on bad input")

    @unittest.skipUnless(BANNERS, "needs an NSUI banner file")
    def test_damaged_models_never_crash_the_preview(self):
        """The preview reads the 3D model. Damage the model itself (not just the header) and check it always ends in
        an ordinary NSUIError or a picture."""
        rng = random.Random(77)
        with tempfile.TemporaryDirectory() as t:
            for banner in BANNERS:
                b = nsui.Banner(banner)
                model = bytes(b.common)
                for i in range(max(10, FUZZ // 6)):
                    data = bytearray(model)
                    for _ in range(rng.randrange(1, 12)):
                        data[rng.randrange(len(data))] = rng.randrange(256)
                    comp = cgfx.lz11_compress(bytes(data))
                    words = list(b.words)
                    delta = len(comp) - (b.common_end - b.common_off)
                    for k in range(3, len(words)):
                        if words[k] and words[k] > b.common_off:
                            words[k] += delta
                    blob = struct.pack("<%dI" % len(words), *words) + comp + b.data[b.common_end:]
                    f = write(Path(t) / "m.bin", blob)
                    t0 = time.time()
                    try:
                        nsui.preview_image(f, "Test", "1993", (160, 80))
                    except nsui.NSUIError:
                        pass
                    self.assertLess(time.time() - t0, 8, "the preview took too long on a damaged model")


class ReadyMadeFileTests(unittest.TestCase):
    def test_icon_files_must_be_exactly_the_right_size(self):
        with tempfile.TemporaryDirectory() as t:
            f = write(Path(t) / "i.bin", b"SMDH" + b"\0" * 100)
            with self.assertRaises(builder.BuildError):
                builder._read_ready_made(f, b"SMDH", "icon")
            big = write(Path(t) / "big.bin", b"SMDH" + b"\0" * (builder.ICON_BYTES + 10))
            with self.assertRaises(builder.BuildError):
                builder._read_ready_made(big, b"SMDH", "icon")
            good = write(Path(t) / "ok.bin", b"SMDH" + b"\0" * (builder.ICON_BYTES - 4))
            self.assertEqual(builder._read_ready_made(good, b"SMDH", "icon"), good)

    def test_wrong_magic_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            f = write(Path(t) / "b.bin", b"XXXX" + b"\0" * 300)
            with self.assertRaises(builder.BuildError):
                builder._read_ready_made(f, b"CBMD", "banner")

    def test_missing_file_is_a_clean_error(self):
        with self.assertRaises(builder.BuildError):
            builder._read_ready_made(Path("no-such-file.bin"), b"CBMD", "banner")


JP = "".join(chr(c) for c in (0x60AA, 0x9B54, 0x57CE))           # three kanji
E_ACUTE = chr(0xE9)


class NameTests(unittest.TestCase):
    """Names inside the CIA stay plain ASCII (the only kind tested on a 3DS); any title still works."""

    def test_ascii_titles_keep_their_name(self):
        for t in ("Sonic CD", "Ys I & II", "Castlevania Rondo of Blood"):
            self.assertEqual(builder.ascii_name(t, 0xE1234), builder.safe_name(t))

    def test_accents_are_dropped_and_other_scripts_get_a_fallback(self):
        self.assertEqual(builder.ascii_name("Pok" + E_ACUTE + "mon", 1), "Pokemon")
        self.assertEqual(builder.ascii_name(JP, 0xE1234), "Game E1234")
        self.assertEqual(builder.ascii_name("...", 0xE1234), "Game E1234")
        self.assertTrue(builder.ascii_name(JP + " Test", 1).isascii())

    def test_ascii_tracks_are_left_alone(self):
        tracks = ["Game (Track 01).bin", "Game (Track 02).bin"]
        self.assertEqual(builder.romfs_track_names(tracks), {t: t for t in tracks})

    def test_non_ascii_tracks_are_renamed_and_the_cue_follows(self):
        tracks = [JP + " (Track 01).bin", JP + " (Track 02).BIN"]
        names = builder.romfs_track_names(tracks)
        self.assertEqual(list(names.values()), ["Track 01.bin", "Track 02.bin"])
        cue = ('FILE "' + tracks[0] + '" BINARY\r\n  TRACK 01 MODE1/2352\r\n    INDEX 01 00:00:00\r\n'
               'FILE "' + tracks[1] + '" BINARY\r\n  TRACK 02 AUDIO\r\n')
        out = builder.rewrite_cue(cue, names)
        self.assertEqual(out, cue.replace(tracks[0], "Track 01.bin").replace(tracks[1], "Track 02.bin"))
        self.assertEqual(builder.rewrite_cue("FILE game.bin BINARY\n", {"game.bin": "Track 01.bin"}),
                         'FILE "Track 01.bin" BINARY\n')


class SmdhTests(unittest.TestCase):
    def test_layout_and_unicode_titles(self):
        from PIL import Image
        from cdinjector import banner as bn
        data = bn.smdh_bytes(Image.new("RGB", (48, 48), (255, 0, 0)), JP + " Test", "Long " + JP, "Pub")
        self.assertEqual(len(data), builder.ICON_BYTES)
        self.assertEqual(data[:4], b"SMDH")
        for slot in range(16):                                   # every language shows the same title
            base = 8 + slot * 0x200
            self.assertEqual(data[base:base + 0x80].decode("utf-16-le").rstrip(chr(0)), JP + " Test")
        self.assertEqual(struct.unpack_from("<H", data, 0x24C0)[0], 0xF800)      # pure red in RGB565

    def test_long_titles_are_cut_at_a_whole_character_with_room_for_the_end_mark(self):
        from PIL import Image
        from cdinjector import banner as bn
        smile = chr(0x1F600)                                      # needs two UTF-16 units
        data = bn.smdh_bytes(Image.new("RGB", (48, 48)), smile * 50, "x", "y")
        short = data[8:8 + 0x80]
        self.assertEqual(short[-2:], bytes(2))
        short.decode("utf-16-le")                                 # no half character left at the end


class SoundTests(unittest.TestCase):
    def wav(self, path, seconds, width=2):
        import wave
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(width)
            w.setframerate(8000)
            w.writeframes(bytes(int(8000 * seconds) * width))
        return path

    def test_good_and_bad_sounds(self):
        from cdinjector import banner as bn
        with tempfile.TemporaryDirectory() as t:
            self.assertTrue(bn.check_sound(self.wav(Path(t) / "ok.wav", 1.5)))
            with self.assertRaises(bn.SoundError):
                bn.check_sound(self.wav(Path(t) / "long.wav", 4))
            with self.assertRaises(bn.SoundError):
                bn.check_sound(self.wav(Path(t) / "wide.wav", 1, width=4))
            with self.assertRaises(bn.SoundError):
                bn.check_sound(write(Path(t) / "fake.wav", b"RIFF" + bytes(40)))
            with self.assertRaises(bn.SoundError):
                bn.check_sound(write(Path(t) / "fake.bcwav", b"NOPE" + bytes(40)))
            with self.assertRaises(bn.SoundError):
                bn.check_sound(write(Path(t) / "song.mp3", b"ID3"))
            with self.assertRaises(bn.SoundError):
                bn.check_sound(Path(t) / "missing.wav")


class PreflightTests(unittest.TestCase):
    def test_bad_extra_files_are_refused_before_any_work(self):
        with tempfile.TemporaryDirectory() as t:
            broken = write(Path(t) / "shot.png", b"\x89PNG\r\n\x1a\n" + bytes(30))
            for opt in (builder.BuildOptions(game=Path(t), image=broken),
                        builder.BuildOptions(game=Path(t), image=Path(t) / "gone.png"),
                        builder.BuildOptions(game=Path(t), icon_file=broken),
                        builder.BuildOptions(game=Path(t), sound_file=Path(t) / "gone.wav"),
                        builder.BuildOptions(game=Path(t), plate_font=Path(t) / "gone.ttf")):
                with self.assertRaises(builder.BuildError):
                    builder.preflight(opt)


class ToolArgumentTests(unittest.TestCase):
    """makerom and bannertool only understand the Windows code page, so they must only ever get plain relative
    names and run inside the work folder, whatever the paths on the PC look like."""

    def test_tools_get_only_ascii_relative_names(self):
        from cdinjector import banner as bn
        from cdinjector import resources
        if not (resources.core_dir("temperpce") / "emulator.elf").is_file():
            self.skipTest("the bundled emulators aren't built here (scripts/build_emulators.sh)")
        calls = []

        def fake_run(cmd, timeout=900, cwd=None):
            calls.append((cmd, cwd))
            out = cmd[cmd.index("-o") + 1]
            Path(cwd, out).write_bytes(b"x")
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t) / (JP + " game")
            folder.mkdir()
            write(folder / (JP + " 1.bin"), bytes(0x800) + b"PC Engine CD-ROM SYSTEM" + bytes(3000))
            write(folder / (JP + ".cue"), ('FILE "' + JP + ' 1.bin" BINARY' + chr(10)).encode("utf-8"))
            write(folder / "syscard3.pce", bytes(262144))
            out = Path(t) / ("out " + JP)
            opt = builder.BuildOptions(game=folder, system="pce", title=JP + " Pok" + E_ACUTE + "mon", out_dir=out)
            with mock.patch.object(builder, "run_tool", fake_run), mock.patch.object(bn, "run_tool", fake_run):
                cia = builder.build(opt)
            self.assertTrue(cia.is_file())
            self.assertEqual(cia.name, JP + " Pok" + E_ACUTE + "mon.cia")
            self.assertEqual([p.name for p in out.iterdir()], [cia.name])          # no .part file left behind
        self.assertEqual(len(calls), 2)                                           # bannertool, then makerom
        for cmd, cwd in calls:
            self.assertIsNotNone(cwd)
            for arg in cmd[1:]:
                self.assertTrue(arg.isascii(), arg)
                self.assertFalse(Path(arg).is_absolute(), arg)


class SettingsTests(unittest.TestCase):
    def load(self, text):
        try:
            from cdinjector import gui
        except ImportError:
            self.skipTest("tkinter isn't available")
        with tempfile.TemporaryDirectory() as t:
            saved = gui.SETTINGS
            gui.SETTINGS = Path(t) / "settings.json"
            try:
                if text is not None:
                    gui.SETTINGS.write_text(text, encoding="utf-8")
                return gui.App._load_settings(None)
            finally:
                gui.SETTINGS = saved

    def test_missing_or_broken_files_give_defaults(self):
        for text in (None, "", "{not json", "[1, 2, 3]", "null", "42", '"text"'):
            self.assertEqual(self.load(text), {}, repr(text))

    def test_only_plain_text_values_are_kept(self):
        got = self.load(json.dumps({"bios": "C:/bios", "color": 5, "out": ["x"], "plate_font": "f.ttf", "big": "x" * 5000}))
        self.assertEqual(got, {"bios": "C:/bios", "plate_font": "f.ttf"})


class SourceRulesTests(unittest.TestCase):
    """Rules about the code itself that keep the app safe by construction."""

    def sources(self):
        return [p for p in (ROOT / "cdinjector").glob("*.py")] + [ROOT / "cd_injector.py"]

    def test_no_network_and_no_dynamic_code(self):
        # the names are assembled from pieces so that this list is not itself flagged by code scanners
        modules = ("sock" "et", "url" "lib", "ht" "tp", "requ" "ests", "ft" "plib", "smtp" "lib", "web" "browser",
                   "pic" "kle", "mar" "shal")
        calls = ("ev" "al(", "ex" "ec(", "os.sys" "tem(", "__imp" "ort__(", "yaml.lo" "ad(", "shell" "=True")
        banned = tuple("import " + m for m in modules) + calls
        for p in self.sources():
            text = p.read_text(encoding="utf-8")
            for word in banned:
                self.assertNotIn(word, text, f"{p.name} uses {word}")

    def test_tools_are_only_run_with_argument_lists(self):
        for p in self.sources():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "subprocess.run(" in line or "subprocess.Popen(" in line:
                    self.assertNotIn('f"', line.split("(", 1)[1][:3], f"{p.name}: build commands as lists, not strings")


if __name__ == "__main__":
    unittest.main()
