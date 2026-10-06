"""Checks on the release notes made from the changelog."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import release_notes  # noqa: E402

from cdinjector import VERSION  # noqa: E402

CHANGELOG = """# Changelog

## 2.0.0 (unreleased)

- Next.

## 1.2.0 (2026-10-06)

Intro.

- One.

## 1.1.0 (2026-10-05)

- Older.
"""


class ReleaseNotesTests(unittest.TestCase):
    def test_a_dated_section_is_used(self):
        self.assertEqual(release_notes.section(CHANGELOG, "1.2.0"), "Intro.\n\n- One.")
        self.assertEqual(release_notes.section(CHANGELOG, "1.1.0"), "- Older.")

    def test_an_unreleased_or_missing_version_is_refused(self):
        for version in ("2.0.0", "9.9.9"):
            with self.assertRaises(SystemExit):
                release_notes.section(CHANGELOG, version)

    def test_the_notes_name_the_release_files(self):
        notes = release_notes.notes("1.2.0", CHANGELOG)
        self.assertTrue(notes.startswith("Intro.\n\n- One.\n"))
        for name in ("CD-Injector-3DS-v1.2.0-windows.zip", "CD-Injector-3DS-v1.2.0-emulator-source.tar.gz",
                     "SHA256SUMS.txt"):
            self.assertIn(name, notes)

    def test_the_changelog_has_a_section_for_this_version(self):
        text = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## {VERSION} (", text)


if __name__ == "__main__":
    unittest.main()
