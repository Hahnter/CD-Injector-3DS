"""Checks on how the banner, plate and icon are drawn and written."""

import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageChops  # noqa: E402

from cdinjector import banner as bn  # noqa: E402
from cdinjector import cgfx, model3d, nsui  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
# NSUI banners to test with, separated by the path separator (";" on Windows). They can't be part of this repository;
# tests that need them are skipped otherwise.
BANNERS = [Path(p) for p in os.environ.get("CDI_TEST_BANNERS", "").split(os.pathsep) if p and Path(p).is_file()]


def bannertool_model():
    """bannertool's own banner model with its 256 x 128 RGBA4444 picture (all zero) after it."""
    return (DATA / "bannertool-banner-model.cgfx").read_bytes() + bytes(256 * 128 * 2)


def a_picture(size=(320, 224)):
    img = Image.new("RGB", size)
    img.putdata([(x * 255 // size[0], y * 255 // size[1], (x ^ y) & 255) for y in range(size[1]) for x in range(size[0])])
    return img


class DefaultBannerTests(unittest.TestCase):
    def test_the_console_label_stays_inside_the_screen(self):
        """Without a picture the screen shows the console's name. It used to run past the screen's edges ("PC ENGINE
        CD" was wider than the screen), so the strips just inside each edge must stay dark."""
        qx, qy = bn.BANNER_QUAD[:2]
        x0, y0, x1, y1 = (round(v) for v in bn.WINDOW_BOX)
        for system in ("pce", "segacd"):
            for color in (None, (52, 52, 58), (226, 178, 40)):
                img = bn.draw_vc_banner(None, "Title", "1994", system, color).convert("RGB")
                for x in (x0 + 2, x0 + 3, x0 + 4, x1 - 5, x1 - 4, x1 - 3):
                    for y in range((y0 + y1) // 2 - 6, (y0 + y1) // 2 + 6):
                        self.assertLess(sum(img.getpixel((x - qx, y - qy))), 150, f"{system} {color}: text at {x}, {y}")

    def test_the_banner_has_nsuis_layout(self):
        """The frame, picture and plate sit where NSUI's frame banner has them; the rest is see-through."""
        img = bn.draw_vc_banner(a_picture(), "Castlevania: Rondo of Blood", "1993", "pce")
        self.assertEqual(img.size, (256, 192))
        qx, qy = bn.BANNER_QUAD[:2]
        alpha = img.getchannel("A")
        x0, y0, x1, y1 = (round(v) for v in bn.FRAME_BOX)
        middle_row = alpha.crop((x0 - qx + 1, (y0 + y1) // 2 - qy, x1 - qx - 1, (y0 + y1) // 2 - qy + 1))
        middle_column = alpha.crop(((x0 + x1) // 2 - qx, y0 - qy + 1, (x0 + x1) // 2 - qx + 1, y1 - qy - 1))
        self.assertEqual((middle_row.getextrema(), middle_column.getextrema()), ((255, 255), (255, 255)))
        box = alpha.point(lambda v: 255 if v > 128 else 0).getbbox()
        expected = (bn.PLATE_BOX[0] - qx, bn.FRAME_BOX[1] - qy, bn.PLATE_BOX[2] - qx, bn.PLATE_BOX[3] - qy)
        for got, want in zip(box, expected):
            self.assertAlmostEqual(got, want, delta=1)

    def test_screenshots_get_a_tvs_shape(self):
        self.assertEqual(bn.tv_picture(Image.new("RGB", (256, 224))).size, (299, 224))
        self.assertEqual(bn.tv_picture(Image.new("RGB", (512, 448))).size, (597, 448))
        for size in ((320, 240), (400, 300), (600, 800), (256, 256 + 300)):
            self.assertEqual(bn.tv_picture(Image.new("RGB", size)).size, size)


class PlateTests(unittest.TestCase):
    def test_short_titles_take_one_line_at_11_points(self):
        f, lines = bn.plate_title_layout("Sonic CD")
        self.assertEqual((f.size, lines), (bn.TITLE_SIZES[0][0], ["Sonic CD"]))

    def test_long_titles_wrap_and_always_fit(self):
        for title in ("The Legend of Zelda: A Link to the Past & Four Swords", "Castlevania: Rondo of Blood",
                      "Lunar: Eternal Blue " * 4, "Supercalifragilisticexpialidociousandthensome" * 2, ""):
            f, lines = bn.plate_title_layout(title, S=4)
            self.assertLessEqual(len(lines), 3, title)
            self.assertLessEqual(max((f.getlength(t) for t in lines), default=0), bn.PLATE_TEXT_W * 4 + 0.5, title)
            if len(lines) == 3:
                self.assertLessEqual(f.size, bn.TITLE_SIZES[1][0] * 4, title)

    def test_the_plate_body_matches_nsuis(self):
        """Spot checks against the plate in an NSUI banner: the outline, the two-tone rim, the face and the badge."""
        plate = bn.draw_plate("", "1990", S=4).reduce(4)
        lum, alpha = plate.convert("L"), plate.getchannel("A")
        self.assertEqual(alpha.crop((0, 0, 256, 1)).getextrema(), (0, 0))
        self.assertEqual(alpha.crop((0, 63, 256, 64)).getextrema(), (0, 0))
        self.assertEqual(alpha.getpixel((128, 32)), 255)
        self.assertAlmostEqual(lum.getpixel((1, 32)), 201, delta=3)          # light rim on the left
        self.assertLess(lum.getpixel((254, 32)), 180)                        # darker rim on the right
        self.assertAlmostEqual(lum.getpixel((120, 10)), 255, delta=1)        # white face at the top
        self.assertAlmostEqual(lum.getpixel((120, 58)), 216, delta=3)        # a little gray at the bottom
        self.assertAlmostEqual(lum.getpixel((11, 30)), 140, delta=1)         # the badge


class IconTests(unittest.TestCase):
    def test_the_icon_has_nsuis_silver_border(self):
        for picture in (None, a_picture()):
            icon = bn.icon_image(picture, "height", "Sonic CD", "segacd")
            self.assertEqual(icon.size, (48, 48))
            self.assertEqual(icon.getpixel((0, 0)), (250, 250, 250))
            self.assertEqual(icon.getpixel((47, 47)), (101, 101, 101))
            self.assertEqual(icon.getpixel((2, 2)), (101, 101, 101))
            self.assertEqual(icon.getpixel((45, 45)), (190, 190, 190))

    def test_the_picture_fills_the_window(self):
        icon = bn.icon_image(Image.new("RGB", (40, 40), (10, 200, 30)), "height", "X", "pce")
        self.assertEqual(icon.crop(bn.ICON_WINDOW).getcolors(), [(1600, (10, 200, 30))])


class FullColourModelTests(unittest.TestCase):
    def test_bannertools_model_shows_the_picture_in_full_colour(self):
        img = bn.draw_vc_banner(a_picture(), "Castlevania: Rondo of Blood", "1993", "pce")
        model = model3d.flat_banner_model(bannertool_model(), img, bn.BANNER_QUAD)
        self.assertEqual(struct.unpack_from("<I", model, 12)[0], len(model))
        (t,) = cgfx.textures(model).values()
        self.assertEqual((t["w"], t["h"], t["fmt"], t["length"]), (256, 256, cgfx.PICA_RGBA8, 256 * 256 * 4))
        tex = cgfx.read_texture(model, t)
        self.assertIsNone(ImageChops.difference(tex.crop((0, 0, 256, 192)), img).getbbox())
        self.assertIsNone(tex.crop((0, 192, 256, 256)).getbbox())
        corners = {tuple(round(c, 4) for c in v) for m in model3d.read_meshes(model) for tri in m["tris"] for v in tri}
        self.assertEqual(corners, {(-12.8, 9.0, 0.0, 0.0, 1.0), (12.8, 9.0, 0.0, 1.0, 1.0),
                                   (-12.8, -10.2, 0.0, 0.0, 0.25), (12.8, -10.2, 0.0, 1.0, 0.25)})

    def test_on_the_screen_it_lands_where_the_preview_shows_it(self):
        img = bn.draw_vc_banner(a_picture(), "Sonic CD", "1993", "segacd")
        model = model3d.flat_banner_model(bannertool_model(), img, bn.BANNER_QUAD)
        shown = model3d.render(model3d.textured(model), 0, (400, 240), ss=1)
        diff = ImageChops.difference(shown, bn.on_screen(img, bn.BANNER_QUAD, (400, 240))).convert("L")
        self.assertLess(sum(diff.tobytes()) / (400 * 240), 1.0)

    def test_a_picture_used_as_it_is_keeps_bannertools_place(self):
        model = model3d.flat_banner_model(bannertool_model(), a_picture((256, 128)), bn.CUSTOM_QUAD)
        (t,) = cgfx.textures(model).values()
        self.assertEqual((t["w"], t["h"]), (256, 128))
        xs = {round(v[0], 4) for m in model3d.read_meshes(model) for tri in m["tris"] for v in tri}
        self.assertEqual(xs, {-13.0, 13.0})

    def test_unusable_sizes_are_refused(self):
        with self.assertRaises(cgfx.CGFXError):
            model3d.flat_banner_model(bannertool_model(), Image.new("RGBA", (200, 100)), bn.BANNER_QUAD)

    def test_replacing_the_model_in_a_banner_file(self):
        """Only the model's block changes; the sound moves along by whole 32-byte steps and keeps its bytes."""
        old = cgfx.lz11_compress(bannertool_model())
        old += bytes(-len(old) % 32)
        sound = b"CWAV" + bytes(60)
        words = [0x444D4243, 0, 0x88] + [0] * 30 + [0x88 + len(old)]
        data = struct.pack("<34I", *words) + old + sound
        new_model = model3d.flat_banner_model(bannertool_model(), a_picture((256, 128)), bn.CUSTOM_QUAD)
        out = cgfx.cbmd_replace_common(data, new_model)
        start, end = cgfx.cbmd_common(out)
        self.assertEqual(cgfx.lz11_decompress(out[start:end]), new_model)
        cwav = struct.unpack_from("<I", out, 0x84)[0]
        self.assertEqual((cwav % 32, out[cwav:]), (0x88 % 32, sound))

    def test_rgba8_pictures_read_back_exactly(self):
        model = bytearray(model3d.flat_banner_model(bannertool_model(), Image.new("RGBA", (256, 128)), bn.CUSTOM_QUAD))
        (t,) = cgfx.textures(bytes(model)).values()
        picture = Image.merge("RGBA", a_picture((256, 128)).split() + (Image.linear_gradient("L").resize((256, 128)),))
        cgfx.write_rgba8(model, t, picture)
        self.assertIsNone(ImageChops.difference(cgfx.read_texture(bytes(model), t), picture).getbbox())

    def test_an_etc1_block(self):
        """One ETC1 block in "individual" mode: both halves gray 136, every pixel the first modifier (+2)."""
        block = struct.pack("<Q", 0x88888800 << 32)
        img = cgfx.read_texture(block * 4 * 64, dict(w=64, h=8, data=0, fmt=cgfx.PICA_ETC1, name="t"))
        self.assertEqual(img.getcolors(), [(512, (138, 138, 138, 255))])


class ScreenTests(unittest.TestCase):
    def test_the_picture_is_stretched_over_the_screen_only(self):
        tv = Image.new("RGB", (128, 128), (30, 34, 34))
        out = nsui.screen_picture(tv, (5, 5, 123, 92), Image.new("RGB", (320, 224), (200, 10, 10)))
        self.assertEqual(out.crop((5, 5, 123, 92)).getcolors(), [(118 * 87, (200, 10, 10))])
        self.assertEqual(out.crop((0, 92, 128, 128)).getcolors(), [(128 * 36, (30, 34, 34))])


@unittest.skipUnless(BANNERS, "needs an NSUI banner file (set CDI_TEST_BANNERS)")
class NSUITemplateTests(unittest.TestCase):
    def test_a_banner_takes_this_games_picture_and_title(self):
        """Frame and console + TV banners alike: only the plate and the picture (frame or TV screen) change, and
        the language models and sound keep their bytes."""
        with tempfile.TemporaryDirectory() as t:
            for path in BANNERS:
                b = nsui.Banner(path)
                out, note = nsui.prepare(path, "Castlevania: Rondo of Blood", "1993", t, picture=a_picture())
                where = b.picture if b.is_frame else b.screen and b.screen[0]
                self.assertTrue(where, f"{path.name}: no frame or TV screen found for the picture")
                self.assertEqual(note, "your picture and title added", path.name)
                new = nsui.Banner(out).validate()
                self.assertEqual(new.data[new.common_end:], b.data[b.common_end:])
                texs = cgfx.textures(bytes(b.common))
                changed = [i for i, (x, y) in enumerate(zip(b.common, new.common)) if x != y]
                inside = [i for i in changed if any(v["data"] <= i < v["data"] + v["length"]
                                                    for n, v in texs.items() if n in (b.plate, where))]
                self.assertEqual(len(changed), len(inside), path.name)
                if not b.plate_blank():                                          # NSUI's badge is kept
                    self.assertEqual(new.texture(b.plate).crop((0, 0, 92, 64)).tobytes(),
                                     b.texture(b.plate).crop((0, 0, 92, 64)).tobytes(), path.name)


if __name__ == "__main__":
    unittest.main()
