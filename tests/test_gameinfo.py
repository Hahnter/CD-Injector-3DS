"""Checks on recognising discs and finding their pictures."""

import io
import re
import sys
import urllib.error
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdinjector import download  # noqa: E402
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

    def test_the_box_art_alone_for_the_cover(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t) / gi.THUMBNAIL_SYSTEMS["pce"]
            for kind in ("Named_Titles", "Named_Boxarts"):
                (base / kind).mkdir(parents=True)
                (base / kind / "Game (Japan).png").write_bytes(b"png")
            (Path(t) / "Game (Japan).png").write_bytes(b"png")
            self.assertEqual(gi.find_picture("pce", ["Game (Japan)"], [t], gi.COVER_KINDS),
                             base / "Named_Boxarts" / "Game (Japan).png")
            (base / "Named_Boxarts" / "Game (Japan).png").unlink()
            self.assertIsNone(gi.find_picture("pce", ["Game (Japan)"], [t], gi.COVER_KINDS))   # never the title

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

    def test_the_cd_case_gets_the_box_art(self):
        with tempfile.TemporaryDirectory() as t:
            d = a_disc(t, "x.cue", {"t.bin": segacd_track() * 4})
            boxes = Path(t) / "pics" / gi.THUMBNAIL_SYSTEMS["segacd"] / "Named_Boxarts"
            boxes.mkdir(parents=True)
            (boxes / "Sonic The Hedgehog CD (Japan).png").write_bytes(b"png")
            opt = BuildOptions(game=d.cue, pictures_dir=Path(t) / "pics", banner_style="cdcase")
            fill_in(opt, d, "segacd")
            self.assertEqual(opt.cover, boxes / "Sonic The Hedgehog CD (Japan).png")
            opt = BuildOptions(game=d.cue, pictures_dir=Path(t) / "pics")                  # the frame needs none
            fill_in(opt, d, "segacd")
            self.assertIsNone(opt.cover)


class FakeServer:
    """Stands in for libretro's thumbnails: {URL: body}; anything else is a 404."""

    def __init__(self, files, final_url=None):
        self.files, self.final_url, self.asked = files, final_url, []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.asked.append(url)
        if url not in self.files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        body, final = self.files[url], self.final_url or url

        class Response(io.BytesIO):
            def geturl(self):
                return final
        return Response(body)


def a_png():
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (320, 224), (10, 20, 200)).save(out, "PNG")
    return out.getvalue()


class DownloadTests(unittest.TestCase):
    name = "Akumajou Dracula X - Chi no Rondo (Japan)"

    def test_the_title_screen_is_fetched_once_and_kept(self):
        url = download.picture_url("pce", "Named_Titles", self.name)
        self.assertEqual(url, "https://raw.githubusercontent.com/libretro-thumbnails/NEC_-_PC_Engine_CD_-_TurboGrafx-CD"
                              "/master/Named_Titles/Akumajou%20Dracula%20X%20-%20Chi%20no%20Rondo%20%28Japan%29.png")
        server = FakeServer({url: a_png()})
        with tempfile.TemporaryDirectory() as t:
            got = download.download_picture("pce", self.name, t, opener=server)
            self.assertEqual(got, Path(t) / gi.THUMBNAIL_SYSTEMS["pce"] / "Named_Titles" / (self.name + ".png"))
            self.assertEqual(gi.find_picture("pce", [self.name], [t]), got)      # found offline from now on
            download.download_picture("pce", self.name, t, opener=server)
            self.assertEqual(len(server.asked), 1)

    def test_box_art_when_there_is_no_title_screen(self):
        url = download.picture_url("segacd", "Named_Boxarts", "Sonic CD (Europe)")
        with tempfile.TemporaryDirectory() as t:
            got = download.download_picture("segacd", "Sonic CD (Europe)", t, opener=FakeServer({url: a_png()}))
            self.assertEqual(got.parent.name, "Named_Boxarts")
            self.assertIsNone(download.download_picture("segacd", "Not A Game", t, opener=FakeServer({})))

    def test_a_picture_kept_under_another_name(self):
        """libretro keeps some pictures under a name with another capital letter, or without the disc's notes."""
        sonic = download.picture_url("segacd", "Named_Titles", "Sonic The Hedgehog CD (Japan)")
        dune = download.picture_url("segacd", "Named_Boxarts", "Dune (USA)")
        with tempfile.TemporaryDirectory() as t:
            server = FakeServer({sonic: a_png(), dune: a_png()})
            got = download.download_picture("segacd", "Sonic the Hedgehog CD (Japan)", t, opener=server)
            self.assertEqual(got.name, "Sonic The Hedgehog CD (Japan).png")
            self.assertEqual(server.asked, [sonic])
            got = download.download_picture("segacd", "Dune (USA) (En,Fr,De,Es,It)", t, opener=server)
            self.assertEqual((got.parent.name, got.name), ("Named_Boxarts", "Dune (USA).png"))
            self.assertEqual(gi.find_picture("segacd", ["Dune (USA) (En,Fr,De,Es,It)"], [t]), got)    # and offline

    def test_name_variants(self):
        self.assertEqual(gi.name_variants("Shin Megami Tensei (Japan) (Rev 2)"),
                         ["Shin Megami Tensei (Japan) (Rev 2)", "Shin Megami Tensei (Japan)"])
        self.assertEqual(gi.name_variants("Supreme Warrior (USA) (Disc 1) (Fire & Earth) (Alt)")[1],
                         "Supreme Warrior (USA) (Disc 1) (Fire & Earth)")
        self.assertEqual(gi.name_variants("Lunar - The Silver Star (Japan)"), ["Lunar - The Silver Star (Japan)"])

    def test_bad_downloads_are_refused(self):
        url = download.picture_url("pce", "Named_Titles", self.name)
        with tempfile.TemporaryDirectory() as t:
            for server in (FakeServer({url: b"<html>not a picture</html>"}),
                           FakeServer({url: b"\x89PNG\r\n\x1a\n" + b"broken" * 10}),
                           FakeServer({url: b"\x89PNG\r\n\x1a\n" + bytes(download.MAX_BYTES)}),
                           FakeServer({url: a_png()}, final_url="https://elsewhere.example/x.png")):
                with self.assertRaises(download.DownloadError):
                    download.download_picture("pce", self.name, t, opener=server)
            self.assertEqual(list(Path(t).rglob("*.png")), [])

    def test_no_connection_is_a_clean_error(self):
        def offline(request, timeout=None):
            raise urllib.error.URLError("no route to host")
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(download.DownloadError):
                download.download_picture("pce", self.name, t, opener=offline)


if __name__ == "__main__":
    unittest.main()
