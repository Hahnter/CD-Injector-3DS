"""Checks on the release notes made from the changelog."""

import re
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


ROOT = Path(__file__).resolve().parents[1]


class PinTests(unittest.TestCase):
    """bannertool.exe is the author's release file, checked against SHA-256 sums pinned in two places that must agree."""

    def setUp(self):
        self.script = (ROOT / "scripts" / "build_emulators.sh").read_text(encoding="utf-8")
        self.flow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_the_build_script_and_the_workflow_pin_the_same_files(self):
        for script_name, flow_name in (("BANNERTOOL_ZIP_SHA", "BANNERTOOL_ZIP_SHA256"),
                                       ("BANNERTOOL_WIN_SHA", "BANNERTOOL_EXE_SHA256")):
            in_script = re.search(rf"^{script_name}=(\S+)$", self.script, re.M).group(1)
            in_flow = re.search(rf"^\s+{flow_name}: (\S+)$", self.flow, re.M).group(1)
            self.assertRegex(in_script, r"^[0-9a-f]{64}$")
            self.assertEqual(in_script, in_flow, script_name)
        tag = re.search(r'^\s+BANNERTOOL_TAG: "([^"]+)"$', self.flow, re.M).group(1)
        self.assertIn(f"/diasurgical/bannertool/releases/download/{tag}/bannertool.zip", self.script)

    def test_a_release_is_only_published_from_main(self):
        self.assertIn("PUBLISH: ${{ inputs.publish && github.ref == 'refs/heads/main' }}", self.flow)
        publish = self.flow.split("- name: Publish", 1)[1]
        self.assertIn("if: env.PUBLISH == 'true'", publish.split("run:", 1)[0])
        self.assertIn("default: false", self.flow)                  # a run started without ticking "publish" only builds


if __name__ == "__main__":
    unittest.main()
