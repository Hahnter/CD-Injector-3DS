"""Tests for scripts/hygiene.py: it must find (and, with --fix, remove) hidden characters and metadata.

Every special character here is built with chr() at run time. Typing them into this file would put real hidden
characters (even a bidirectional override) into the source, which is exactly what the checker is there to stop.
"""

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hygiene  # noqa: E402

ZWSP, ZWNJ, ZWJ, WJ, BOM, SHY = (chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD))
NBSP, EMSP, NNBSP, IDSP = (chr(c) for c in (0x00A0, 0x2003, 0x202F, 0x3000))
RLO, VS16 = chr(0x202E), chr(0xFE0F)
TAG_A, VS_SUP = chr(0xE0041), chr(0xE0100)
CYR_A = chr(0x0430)
CYR_WORD = "".join(chr(c) for c in (0x043F, 0x0440, 0x0438, 0x0432, 0x0435, 0x0442))
CHECK, ELLIPSIS = chr(0x2713), chr(0x2026)


def png(extra_chunks=()):
    def chunk(name, payload):
        body = name + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    parts = [hygiene.PNG_SIG, chunk(b"IHDR", ihdr)]
    parts += [chunk(n, p) for n, p in extra_chunks]
    parts += [chunk(b"IDAT", idat), chunk(b"IEND", b"")]
    return b"".join(parts)


class TextTests(unittest.TestCase):
    def check(self, text, suffix=".md"):
        return hygiene.classify(text, suffix)

    def test_clean_text_is_clean(self):
        self.assertEqual(self.check("plain ASCII text, a check " + CHECK + " mark and an ellipsis " + ELLIPSIS), {})

    def test_zero_width_characters(self):
        for ch in (ZWSP, ZWNJ, ZWJ, WJ, BOM, SHY):
            self.assertIn("invisible character", self.check("a" + ch + "b"), hex(ord(ch)))

    def test_tag_characters_and_variation_selectors(self):
        for ch in (TAG_A, VS16, VS_SUP):
            self.assertIn("invisible character", self.check("a" + ch + "b"), hex(ord(ch)))

    def test_exotic_spaces(self):
        for ch in (NBSP, EMSP, NNBSP, IDSP):
            self.assertIn("exotic space", self.check("a" + ch + "b"), hex(ord(ch)))

    def test_bidi_controls_are_reported_in_source(self):
        self.assertIn("bidirectional control", self.check("x = 1  # " + RLO + " evil", ".py"))

    def test_lookalikes_only_matter_in_source(self):
        self.assertIn("look-alike letter in source", self.check("p" + CYR_A + "ssword = 1", ".py"))
        self.assertEqual(self.check(CYR_WORD, ".md"), {})                     # ordinary prose is fine

    def test_control_characters(self):
        self.assertIn("control, private-use or unassigned", self.check("a" + chr(7) + "b"))

    def test_positions_are_reported(self):
        found = self.check("ab\ncd" + ZWSP + "e")
        self.assertEqual(found["invisible character"], [(2, 3, 0x200B)])

    def test_fix_removes_and_normalises(self):
        text = "a" + ZWSP + "b" + NBSP + "c" + RLO + "d" + VS16 + "e"
        self.assertEqual(hygiene.clean_text(text, ".md"), "ab cde")

    def test_emoji_sequences_are_left_alone(self):
        man, school, heart, keycap = chr(0x1F468), chr(0x1F3EB), chr(0x2764), chr(0x20E3)
        teacher = man + ZWJ + school                                 # a real emoji made with a joiner
        self.assertEqual(self.check("Hello " + teacher + " and " + heart + VS16 + " and 1" + VS16 + keycap), {})
        self.assertEqual(hygiene.clean_text(teacher, ".md"), teacher)

    def test_a_joiner_between_ordinary_letters_is_still_flagged(self):
        self.assertIn("invisible character", self.check("wo" + ZWJ + "rd"))
        self.assertIn("invisible character", self.check("a" + VS16 + "b"))
        self.assertEqual(hygiene.clean_text("wo" + ZWJ + "rd", ".md"), "word")

    def test_bom_kept_only_where_asked(self):
        self.assertEqual(hygiene.clean_text(BOM + "x", ".ps1", keep_bom=True), BOM + "x")
        self.assertEqual(hygiene.clean_text(BOM + "x", ".md"), "x")


class FileTests(unittest.TestCase):
    def test_fix_rewrites_files_and_second_run_is_clean(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "notes.md"
            f.write_text("hello" + ZWSP + " world" + NBSP + "!\n", encoding="utf-8")
            findings, changed = hygiene.run([t], fix=True, out=lambda s: None)
            self.assertEqual((findings, changed), (1, 1))
            self.assertEqual(f.read_text(encoding="utf-8"), "hello world !\n")
            self.assertEqual(hygiene.run([t], fix=False, out=lambda s: None), (0, 0))

    def test_report_mode_does_not_change_files(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "a.py"
            f.write_text("x = 1" + ZWSP + "\n", encoding="utf-8")
            hygiene.run([t], fix=False, out=lambda s: None)
            self.assertIn(ZWSP, f.read_text(encoding="utf-8"))

    def test_invalid_utf8_is_reported(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "b.txt").write_bytes(b"\xff\xfe bad")
            self.assertEqual(hygiene.run([t], out=lambda s: None)[0], 1)

    def test_skipped_folders_are_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "dist"
            d.mkdir()
            (d / "x.txt").write_text("a" + ZWSP + "b", encoding="utf-8")
            self.assertEqual(hygiene.run([t], out=lambda s: None), (0, 0))


class ImageTests(unittest.TestCase):
    def test_png_metadata_found_and_removed_without_touching_pixels(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "a.png"
            f.write_bytes(png([(b"tEXt", b"Comment\x00made by an AI"), (b"caBX", b"c2pa-manifest-bytes"),
                               (b"eXIf", b"Exif\x00\x00")]))
            self.assertEqual(sorted(hygiene.scan_image(f)), ["caBX", "eXIf", "tEXt"])
            self.assertTrue(hygiene.clean_image(f))
            self.assertEqual(hygiene.scan_image(f), [])
            self.assertEqual(f.read_bytes(), png())                  # exactly the metadata-free file
            try:
                from PIL import Image
            except ImportError:
                return
            self.assertEqual(Image.open(f).convert("RGB").getpixel((0, 0)), (255, 0, 0))

    def test_clean_png_is_left_alone(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "a.png"
            f.write_bytes(png())
            self.assertFalse(hygiene.clean_image(f))

    def test_jpeg_app_segments(self):
        def seg(marker, payload):
            return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload
        jpeg = (b"\xff\xd8" + seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00") + seg(0xE1, b"Exif\x00\x00II")
                + seg(0xEB, b"jumbf-c2pa") + seg(0xFE, b"a comment") + b"\xff\xda\x00\x02\x00\x01\x02\x03\xff\xd9")
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "a.jpg"
            f.write_bytes(jpeg)
            self.assertEqual(sorted(hygiene.scan_image(f)), ["EXIF/XMP", "JUMBF (C2PA)", "comment"])
            self.assertTrue(hygiene.clean_image(f))
            self.assertEqual(hygiene.scan_image(f), [])
            self.assertIn(b"JFIF", f.read_bytes())                   # the harmless header stays
            self.assertTrue(f.read_bytes().endswith(b"\xff\xda\x00\x02\x00\x01\x02\x03\xff\xd9"))


class ProjectTest(unittest.TestCase):
    def test_the_project_itself_is_clean(self):
        root = Path(__file__).resolve().parents[1]
        lines = []
        findings, _ = hygiene.run([root], out=lines.append)
        self.assertEqual(findings, 0, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
