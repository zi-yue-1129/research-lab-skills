"""Unit tests for check_core_neutrality.py.

The lint is a ratchet over a per-file baseline: it must fail when a core file
gains profile-specific terms, when a new file has any, and when a file's count
drops without the baseline being lowered; and it must ignore profiles, tests
and fixtures.
"""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.test_helpers import run_script

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "checks" / "check_core_neutrality.py"
BASELINE = Path("scripts/checks/core_neutrality_baseline.json")


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return run_script(SCRIPT, "--root", str(root), *extra)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _baseline(root: Path, counts: dict) -> None:
    _write(root, BASELINE.as_posix(), json.dumps(counts))


class CheckCoreNeutralityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "skills/demo/SKILL.md", "General guidance. Example from Taiwan.\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_matching_baseline_passes(self) -> None:
        _baseline(self.root, {"skills/demo/SKILL.md": 1})
        result = _run(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_new_hit_in_core_fails(self) -> None:
        _baseline(self.root, {"skills/demo/SKILL.md": 1})
        _write(self.root, "skills/demo/references/new.md", "Default to TSSCI journals.\n")
        result = _run(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("skills/demo/references/new.md: 1", result.stdout)

    def test_identifying_term_counts(self) -> None:
        _baseline(self.root, {"skills/demo/SKILL.md": 1})
        _write(self.root, "commands/demo.md", "Write like the CM-SAC paper.\n")
        self.assertEqual(_run(self.root).returncode, 1)

    def test_drop_without_lowering_baseline_fails(self) -> None:
        _baseline(self.root, {"skills/demo/SKILL.md": 3})
        result = _run(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--update-baseline", result.stdout)

    def test_profiles_tests_and_fixtures_are_ignored(self) -> None:
        _baseline(self.root, {"skills/demo/SKILL.md": 1})
        _write(self.root, "skills/research-profile/profiles/x/field.md", "Taiwan IRB\n")
        _write(self.root, "skills/demo/scripts/tests/test_x.py", "'Taiwan'\n")
        _write(self.root, "skills/demo/fixtures/f.md", "Taiwan\n")
        self.assertEqual(_run(self.root).returncode, 0)

    def test_update_baseline_writes_current_counts(self) -> None:
        _baseline(self.root, {})
        self.assertEqual(_run(self.root, "--update-baseline").returncode, 0)
        written = json.loads((self.root / BASELINE).read_text(encoding="utf-8"))
        self.assertEqual(written, {"skills/demo/SKILL.md": 1})
        self.assertEqual(_run(self.root).returncode, 0)


if __name__ == "__main__":
    unittest.main()
