"""Unit tests for check_profiles.py.

Covers the three things the lint guards: schema validity, registry parity with
the profiles on disk, and the rule that profiles carry no identifying terms.
"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.test_helpers import run_script

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "checks" / "check_profiles.py"
REGISTRY_HEAD = "| Profile | Axes set | Extends | Use for |\n|---|---|---|---|\n"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return run_script(SCRIPT, "--root", str(root))


class CheckProfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        scripts = self.root / "skills/research-profile/scripts"
        scripts.mkdir(parents=True)
        shutil.copy(REPO / "skills/research-profile/scripts/profile.py", scripts)
        self.profiles = self.root / "skills/research-profile/profiles"
        self.profiles.mkdir()
        self._profile("plain-voice", "name: plain-voice\ndescription: Plain voice.\n"
                      "axes:\n  voice:\n    rules: voice.md\n", {"voice.md": "Short sentences.\n"})
        self._registry(["plain-voice"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _profile(self, name: str, manifest: str, files: dict) -> None:
        directory = self.profiles / name
        directory.mkdir()
        (directory / "profile.yaml").write_text(manifest, encoding="utf-8")
        for rel, text in files.items():
            (directory / rel).write_text(text, encoding="utf-8")

    def _registry(self, names: list[str]) -> None:
        rows = "".join(f"| `{n}` | voice | — | x |\n" for n in names)
        (self.root / "PROFILE_REGISTRY.md").write_text(REGISTRY_HEAD + rows, encoding="utf-8")

    def test_valid_registered_profile_passes(self) -> None:
        result = _run(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_unregistered_profile_fails(self) -> None:
        self._registry([])
        result = _run(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing a row for profile 'plain-voice'", result.stdout)

    def test_registry_row_without_profile_fails(self) -> None:
        self._registry(["plain-voice", "ghost"])
        self.assertIn("lists 'ghost'", _run(self.root).stdout)

    def test_invalid_schema_fails(self) -> None:
        (self.profiles / "plain-voice" / "voice.md").unlink()
        self.assertIn("missing file 'voice.md'", _run(self.root).stdout)

    def test_identifying_term_inside_profile_fails(self) -> None:
        (self.profiles / "plain-voice" / "voice.md").write_text(
            "Instead of X, write as in the CM-SAC manuscript.\n", encoding="utf-8")
        result = _run(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("identifying term 'CM-SAC'", result.stdout)


if __name__ == "__main__":
    unittest.main()
