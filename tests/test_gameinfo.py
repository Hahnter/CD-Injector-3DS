"""Checks on recognising discs and finding their pictures."""

import re
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdinjector import gameinfo as gi  # noqa: E402
from cdinjector.builder import BuildOptions, fill_in  # noqa: E402
from cdinjector.disc import Disc  # noqa: E402
from cdinjector.gamelist import DISCS  # noqa: E402


def segacd_track(serial=b"GM G-6021  -00", made=b"(C)SEGA 1993.JUN", raw=True):
    """The start of a Sega CD data track: the system area, in a raw 2352-byte sector or a plain 2048-byte one."""
    area = bytearray(0x200)
    area[0:14] = b"SEGADISCSYSTEM"
    area[0x100:0x110] = b"SEGA MEGA DRIVE "
    area[0x110:0x120] = made.ljust(16)
    area[0x150:0x180] = b"SONIC THE HEDGEHOG-CD".ljust(48)
    area[0x180:0x18E] = serial.ljust(14)
    if not raw:
        return bytes(area) + bytes(2048 - len(area))
    sector = bytearray(2352)
    sector[0:12] = b"\x00" + b"\xff" * 10 + b"\x00"
    sector[16:16 + len(area)] = area
    return bytes(sector)


def a_disc(folder, cue_name, tracks):
    folder = Path(folder)
    for name, data in tracks.items():
        (folder / name).write_bytes(data)
    (folder / cue_name).write_text("".join(f'FILE "{n}" BINARY\n' for n in tracks))
    return Disc(cue=folder / cue_name, tracks=list(tracks))


class TitleTests(unittest.TestCase):
    def test_names_become_titles(self):
        for name, title in (("Addams Family, The (USA)", "The Addams Family"),
                            ("Lunar - The Silver Star (Japan)", "Lunar: The Silver Star"),
                            ("3x3 Eyes - Sanjiyan Hensei (ACD, SCD)(Japan)", "3x3 Eyes: Sanjiyan Hensei"),
                            ("Legend of Xanadu, The - Part II (Japan)", "The Legend of Xanadu: Part II"),
                            ("Sonic CD (Europe)", "Sonic CD")):
            self.assertEqual(gi.display_title(name), title)


class GameListTests(unittest.TestCase):
    def test_the_list_is_well_formed(self):
        for system in ("pce", "segacd"):
            self.assertGreater(len(DISCS[system]), 400)
            for disc in DISCS[system]:
                size, crc, serial, redump, mame, publisher, year = disc
                self.assertTrue(isinstance(size, int) and isinstance(crc, int) and (redump or mame), disc)
                self.assertTrue(year == "" or re.fullmatch(r"\d{4}", year), disc)

    def test_well_known_games(self):
        names = {d[3]: d for d in DISCS["pce"]}
        self.assertEqual(names["Akumajou Dracula X - Chi no Rondo (Japan)"][5:], ("Konami", "1993"))
        serials = {d[2]: d for d in DISCS["segacd"] if d[0]}
        self.assertEqual(serials["G-6021"][5:], ("Sega", "1993"))


class IdentifyTests(unittest.TestCase):
    def test_a_sega_cd_disc_by_the_serial_in_its_header(self):
        for raw in (True, False):
            with tempfile.TemporaryDirectory() as t:
                d = a_disc(t, "anything.cue", {"track01.bin": segacd_track(raw=raw) * 4})
                info = gi.identify(d, "segacd")
                self.assertEqual((info.title, info.publisher, info.year, info.found_by),
                                 ("Sonic the Hedgehog CD", "Sega", "1993", "header"))

    def test_an_unlisted_sega_cd_disc_still_gives_its_year(self):
        with tempfile.TemporaryDirectory() as t:
            d = a_disc(t, "x.cue", {"t.bin": segacd_track(serial=b"GM ZZ-99999-00", made=b"(C)T-99 1995.MAR")})
            info = gi.identify(d, "segacd")
            self.assertEqual((info.title, info.publisher, info.year), ("", "", "1995"))

    def test_a_disc_by_its_tracks(self):
        """Redump lists each disc's data track by size and CRC-32: a track that matches both is recognised, whatever
        the files are called."""
        data = bytes(range(256)) * 64
        fake = {"pce": ((len(data), zlib.crc32(data), "XXCD0001", "Some Game - The Sequel (Japan)",
                         "Some Game - The Sequel (Japan)", "Some Maker", "1992"),)}
        saved, gi.DISCS = gi.DISCS, fake
        gi._INDEX.clear()
        try:
            with tempfile.TemporaryDirectory() as t:
                d = a_disc(t, "random.cue", {"01.bin": b"\0" * 2352, "02.bin": data})
                info = gi.identify(d, "pce")
                self.assertEqual((info.title, info.publisher, info.year, info.found_by),
                                 ("Some Game: The Sequel", "Some Maker", "1992", "tracks"))
                d = a_disc(t, "random2.cue", {"02.bin": data[:-1] + b"!"})        # same size, other contents
                self.assertEqual(gi.identify(d, "pce").found_by, "")
        finally:
            gi.DISCS = saved
            gi._INDEX.clear()

    def test_a_disc_by_its_cue_name(self):
        with tempfile.TemporaryDirectory() as t:
            d = a_disc(t, "Akumajou Dracula X - Chi no Rondo (Japan).cue", {"t.bin": b"x" * 100})
            info = gi.identify(d, "pce")
            self.assertEqual((info.title, info.publisher, info.year, info.found_by),
                             ("Akumajou Dracula X: Chi no Rondo", "Konami", "1993", "name"))
            d = a_disc(t, "Castlevania - Rondo of Blood (English patch).cue", {"t.bin": b"x" * 100})
            self.assertEqual(gi.identify(d, "pce"), gi.GameInfo())


class PictureTests(unittest.TestCase):
    def test_retroarch_thumbnails_title_screen_first(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t) / gi.THUMBNAIL_SYSTEMS["pce"]
            for kind in ("Named_Boxarts", "Named_Titles"):
                (base / kind).mkdir(parents=True)
                (base / kind / "Game_ The Sequel (Japan).png").write_bytes(b"png")
            got = gi.find_picture("pce", ["Game: The Sequel (Japan)"], [t])
            self.assertEqual(got, base / "Named_Titles" / "Game_ The Sequel (Japan).png")

    def test_a_flat_folder_of_pictures(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "My Game.jpg").write_bytes(b"jpg")
            self.assertEqual(gi.find_picture("segacd", ["Nope", "My Game"], [t]), Path(t) / "My Game.jpg")
            self.assertIsNone(gi.find_picture("segacd", ["Other"], [t]))


class FillInTests(unittest.TestCase):
    def test_only_empty_fields_are_filled(self):
        with tempfile.TemporaryDirectory() as t:
            d = a_disc(t, "x.cue", {"t.bin": segacd_track() * 4})
            opt = BuildOptions(game=d.cue, title="My Own Title", pictures_dir=Path(t))
            fill_in(opt, d, "segacd")
            self.assertEqual((opt.title, opt.publisher, opt.year), ("My Own Title", "Sega", "1993"))
            self.assertEqual(opt.info["recognised"], "Sonic the Hedgehog CD (Japan)")


if __name__ == "__main__":
    unittest.main()
