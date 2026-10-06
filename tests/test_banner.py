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


def ink_lines(layer):
    """(top row, bottom row, left, right) of each line of ink on a plate text layer at 1x."""
    a = layer.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    rows = [a.crop((0, y, 256, y + 1)).getbbox() for y in range(64)]
    out, run = [], None
    for y, r in enumerate(rows + [None]):
        if r and run is None:
            run = [y, y, r[0], r[2]]
        elif r:
            run = [run[0], y, min(run[2], r[0]), max(run[3], r[2])]
        elif run:
            out.append(tuple(run))
            run = None
    return out


class OfficialPlateTests(unittest.TestCase):
    """The plate's text laid out as on Nintendo's own Virtual Console banners (measured from official ones)."""

    def test_a_short_title_takes_one_line(self):
        (t0, t1, _, _), (y0, y1, yl, yr) = ink_lines(bn.official_text("EarthBound", "1995", S=4).reduce(4))
        self.assertEqual((t0, t1), (17, 28))                      # 12 px capitals on baseline 29
        self.assertEqual((y0, y1), (36, 46))                      # 11 px capitals on baseline 47
        self.assertAlmostEqual(yr - yl, 130, delta=3)             # "Released: 1995" spaced out to Nintendo's width

    def test_a_long_title_takes_two_smaller_lines(self):
        lines = ink_lines(bn.official_text("The Legend of Xanadu: Part II", "1994", S=4).reduce(4))
        self.assertEqual([a for a, _, _, _ in lines], [11, 27, 42])         # 10 px capitals on baselines 21, 37, 52
        self.assertEqual((lines[1][1], lines[2][1]), (36, 51))
        for _, _, left, right in lines:
            self.assertLessEqual(right - left, bn.PLATE_TEXT_W)

    def test_titles_split_like_nintendos(self):
        split = lambda t: bn._two_lines(t.split(), len)                                  # noqa: E731
        self.assertEqual(split("DOUBLE DRAGON II: The Revenge"), ["DOUBLE DRAGON II:", "The Revenge"])
        self.assertEqual(split("The Mysterious Murasame Castle"), ["The Mysterious", "Murasame Castle"])
        self.assertEqual(split("Pokémon Puzzle Challenge"), ["Pokémon", "Puzzle Challenge"])

    def test_a_very_long_line_is_squeezed_to_fit(self):
        for _, _, left, right in ink_lines(bn.official_text("Super Long Title " * 4, "", S=4).reduce(4)):
            self.assertLessEqual(right - left, bn.PLATE_TEXT_W)


class DesignTests(unittest.TestCase):
    """The app's own banners: layers at different depths, each on its own part of the screen."""

    def check(self, layers):
        for img, quad, depth in layers:
            self.assertEqual(img.size, (quad[2] - quad[0], quad[3] - quad[1]))
            self.assertTrue(bn.BANNER_QUAD[0] <= quad[0] < quad[2] <= bn.BANNER_QUAD[2], quad)
            self.assertTrue(bn.BANNER_QUAD[1] <= quad[1] < quad[3] <= bn.BANNER_QUAD[3], quad)
        self.assertEqual([d for _, _, d in layers], sorted(d for _, _, d in layers))       # back to front
        self.assertEqual(layers[-1][1:], (bn.PLATE_QUAD, bn.PLATE_DEPTH))                   # the plate in front
        (mesh,) = model3d.read_meshes(model3d.layered_banner_model(bannertool_model(), layers))
        self.assertEqual(len(mesh["tris"]), 2 * len(layers))

    def test_the_frame(self):
        layers = bn.frame_layers(a_picture(), "Castlevania: Rondo of Blood", "1993", "pce")
        self.check(layers)
        frame = layers[1][0]                             # the window is cut out of the frame, so the picture shows
        window = [round(v) - o for v, o in zip(bn.WINDOW_BOX, bn.FRAME_QUAD[:2] * 2)]
        self.assertEqual(frame.getchannel("A").crop((window[0] + 4, window[1] + 4, window[2] - 4, window[3] - 4))
                         .getextrema(), (0, 0))

    def test_the_cd_case(self):
        square, tall = a_picture((300, 300)), a_picture((300, 510))
        for cover in (square, tall, None):
            layers = bn.cd_case_layers(a_picture(), cover, "Lunar: The Silver Star", "1993", "segacd")
            self.check(layers)
            (_, disc, _), (_, case, _) = layers[0], layers[1]
            for quad in (disc, case):
                self.assertTrue(bn.CASE_AREA[0] <= quad[0] and quad[2] <= bn.CASE_AREA[2], quad)
            self.assertLess(case[0], disc[0])                  # the disc slides out to the right
            self.assertGreater(disc[2], case[2])
            width, height = case[2] - case[0], case[3] - case[1]
            self.assertAlmostEqual(width / height, 0.62 if cover is tall else 1.0 if cover is square else 1.14,
                                   delta=0.02)
        self.assertEqual(bn.draw_vc_banner(None, "T", "", "pce").size, (256, 192))


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

    def test_layers_at_different_depths_cover_their_part_of_the_screen(self):
        """Each picture of a layered banner lands on its own rectangle of the top screen, whatever its depth, and
        reads back from the shared texture as it was given."""
        pictures = [a_picture((134, 98)).convert("RGBA"), a_picture((104, 67)).convert("RGBA"),
                    bn.draw_plate("Lunar", "1992").reduce(4).resize((216, 54))]
        quads = [(133, 48, 267, 146), (148, 63, 252, 130), (92, 164, 308, 218)]
        model = model3d.layered_banner_model(bannertool_model(), list(zip(pictures, quads, (1.8, 1.9, 8.0))))
        (mesh,) = model3d.read_meshes(model)
        self.assertEqual(len(mesh["tris"]), 6)
        texture = cgfx.read_texture(model, cgfx.textures(model)["COMMON1"])
        for k, (picture, quad) in enumerate(zip(pictures, quads)):
            corners = [v for tri in mesh["tris"][2 * k:2 * k + 2] for v in tri]
            scale = model3d.depth_scale(corners[0][2])
            xs = [200 + (v[0] - model3d.CAM[0]) * model3d.PIXELS_PER_UNIT / scale for v in corners]
            ys = [120 - (v[1] - model3d.CAM[1]) * model3d.PIXELS_PER_UNIT / scale for v in corners]
            for got, want in zip((min(xs), min(ys), max(xs), max(ys)), quad):
                self.assertAlmostEqual(got, want, places=3)
            us, vs = [v[3] for v in corners], [v[4] for v in corners]
            box = (round(min(us) * 256), round((1 - max(vs)) * texture.height), round(max(us) * 256),
                   round((1 - min(vs)) * texture.height))
            self.assertIsNone(ImageChops.difference(texture.crop(box), picture.convert("RGBA")).getbbox())
        with self.assertRaises(cgfx.CGFXError):
            model3d.layered_banner_model(bannertool_model(), [(Image.new("RGBA", (256, 64)), quads[2], 8.0)])

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

    def test_replacing_a_language_model(self):
        """Any model of a banner can be replaced: the others and the sound keep their bytes and their alignment."""
        blocks = []
        for model in (bannertool_model(), bannertool_model()[:-64] + bytes(64), bannertool_model()):
            comp = cgfx.lz11_compress(model)
            blocks.append(comp + bytes(-len(comp) % 32))
        sound = b"CWAV" + bytes(60)
        offs = [0x88]
        for b in blocks:
            offs.append(offs[-1] + len(b))
        words = [0x444D4243, 0, offs[0], offs[1], offs[2]] + [0] * 28 + [offs[3]]
        data = struct.pack("<34I", *words) + b"".join(blocks) + sound
        new_model = model3d.flat_banner_model(bannertool_model(), a_picture((256, 128)), bn.CUSTOM_QUAD)
        out = cgfx.cbmd_replace(data, {offs[1]: new_model})
        w = struct.unpack_from("<34I", out, 0)
        self.assertEqual((w[2], w[3] % 32, w[4] % 32, w[33] % 32), (offs[0], offs[1] % 32, offs[2] % 32, offs[3] % 32))
        self.assertEqual(out[w[2]:w[3]], blocks[0])
        self.assertEqual(cgfx.lz11_decompress(out[w[3]:w[4]]), new_model)
        self.assertEqual((out[w[4]:w[33]], out[w[33]:]), (blocks[2], sound))
        with self.assertRaises(cgfx.CGFXError):
            cgfx.cbmd_replace(data, {offs[1] + 4: new_model})

    def test_four_bit_textures(self):
        """L4 and A4 hold two texels a byte, the first in the low half."""
        for fmt, texel in ((cgfx.PICA_L4, lambda v: (v * 17, 255)), (cgfx.PICA_A4, lambda v: (255, v * 17))):
            img = cgfx.read_texture(bytes([0xF3]) * 32, dict(w=8, h=8, data=0, fmt=fmt, name="t"))
            self.assertEqual(sorted(img.getcolors()), sorted([(32, texel(3)), (32, texel(15))]))
            self.assertEqual((img.getpixel((0, 0)), img.getpixel((1, 0))), (texel(3), texel(15)))

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
        """Frame and console + TV banners alike: only the plate and the picture (frame or TV screen) change, in the
        main model and in every language model that has its own copy of them, and the sound keeps its bytes."""
        with tempfile.TemporaryDirectory() as t:
            for path in BANNERS:
                b = nsui.Banner(path)
                out, note = nsui.prepare(path, "Castlevania: Rondo of Blood", "1993", t, picture=a_picture())
                where = b.picture if b.is_frame else b.screen and b.screen[0]
                self.assertTrue(where, f"{path.name}: no frame or TV screen found for the picture")
                self.assertEqual(note, "your picture and title added", path.name)
                new = nsui.Banner(out).validate()
                self.assertEqual(new.data[new.cwav_off:], b.data[b.cwav_off:])
                old_models = [bytes(b.common)] + [m for _, m in b.language_blocks()]
                new_models = [bytes(new.common)] + [m for _, m in new.language_blocks()]
                self.assertEqual(len(old_models), len(new_models), path.name)
                for i, (old, now) in enumerate(zip(old_models, new_models)):
                    texs = cgfx.textures(old)
                    self.assertEqual(len(old), len(now), path.name)
                    changed = [k for k, (x, y) in enumerate(zip(old, now)) if x != y]
                    inside = [k for k in changed if any(v["data"] <= k < v["data"] + v["length"]
                                                        for n, v in texs.items() if n in (b.plate, where))]
                    self.assertEqual(len(changed), len(inside), f"{path.name}, model {i}")
                    if b.plate in texs:                              # what the 3DS shows is this game's plate
                        self.assertEqual(cgfx.read_texture(now, cgfx.textures(now)[b.plate]).tobytes(),
                                         new.texture(b.plate).tobytes(), f"{path.name}, model {i}")
                if not b.plate_blank():                                          # NSUI's badge is kept
                    self.assertEqual(new.texture(b.plate).crop((0, 0, 92, 64)).tobytes(),
                                     b.texture(b.plate).crop((0, 0, 92, 64)).tobytes(), path.name)


if __name__ == "__main__":
    unittest.main()
