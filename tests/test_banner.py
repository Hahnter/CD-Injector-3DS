"""Checks on how the banner is drawn."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdinjector import banner as bn  # noqa: E402


class DefaultBannerTests(unittest.TestCase):
    def test_the_console_label_stays_inside_the_screen(self):
        """Without a picture the screen shows the console's name. It used to run past the screen's edges
        ("PC ENGINE CD" was wider than the screen), so the strips just inside each edge must stay dark."""
        # With no picture the frame is 4:3, so the screen box is x 92-164, y 8-62 (see draw_vc_banner).
        for system in ("pce", "segacd"):
            for color in (None, (52, 52, 58), (226, 178, 40)):
                img = bn.draw_vc_banner(None, "Title", "1994", system, color).convert("RGB")
                for x in (93, 94, 95, 161, 162, 163):
                    for y in range(28, 44):
                        self.assertLess(sum(img.getpixel((x, y))), 150, f"{system} {color}: text at ({x}, {y})")


if __name__ == "__main__":
    unittest.main()
