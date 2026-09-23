"""Unit tests for check_installer_skill_parity.py.

Regression coverage for the bug this check exists to catch: a skill added
to ``marketplace.json`` (e.g. ``advisor-writing-style``) but to none of
``install.sh`` / ``install.ps1`` / ``bin/crs.js``'s hardcoded arrays,
so the plugin path installs it and the three script-based installers
silently do not.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.test_helpers import run_script

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "checks"
    / "check_installer_skill_parity.py"
)


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the check script against a fixture repository root."""
    return run_script(SCRIPT, "--path", str(root))


def _write_manifest(root: Path, ars_skills: list[str]) -> None:
    """Fixture marketplace.json with `resource-resolver`/`agent-state`
    shared across two plugins, plus the given ARS-plugin-only skills.
    """
    manifest = {
        "name": "fixture",
        "plugins": [
            {
                "name": "lab-tools",
                "skills": [
                    "./skills/resource-resolver",
                    "./skills/agent-state",
                    "./skills/research-log",
                ],
            },
            {
                "name": "academic-research-skills",
                "skills": [
                    "./skills/resource-resolver",
                    "./skills/agent-state",
                    *[f"./skills/{name}" for name in ars_skills],
                ],
            },
        ],
    }
    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "marketplace.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def _write_install_sh(root: Path, ars_skills: list[str]) -> None:
    """Fixture install.sh with the three-array shape the real script uses."""
    ars_literal = " ".join(f'"{name}"' for name in ars_skills)
    (root / "install.sh").write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            RESOLVER_SKILLS=("resource-resolver" "agent-state")
            LAB_SKILLS=("research-log")
            ARS_SKILLS=({ars_literal})
            """
        ),
        encoding="utf-8",
    )


def _write_install_ps1(root: Path, ars_skills: list[str]) -> None:
    """Fixture install.ps1 with the three-array shape the real script uses."""
    ars_literal = ", ".join(f'"{name}"' for name in ars_skills)
    (root / "install.ps1").write_text(
        textwrap.dedent(
            f"""\
            $ResolverSkills = @("resource-resolver", "agent-state")
            $LabSkills = @("research-log")
            $ArsSkills = @({ars_literal})
            """
        ),
        encoding="utf-8",
    )


def _write_crs_js(root: Path, ars_skills: list[str]) -> None:
    """Fixture bin/crs.js with the three-array shape the real script uses."""
    ars_literal = ", ".join(f"'{name}'" for name in ars_skills)
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "crs.js").write_text(
        textwrap.dedent(
            f"""\
            const RESOLVER_SKILLS = ['resource-resolver', 'agent-state'];
            const LAB_SKILLS = ['research-log'];
            const ARS_SKILLS = [{ars_literal}];
            """
        ),
        encoding="utf-8",
    )


def _write_aligned_fixture(root: Path, ars_skills: list[str]) -> None:
    """Write a manifest and all three installers, all agreeing on `ars_skills`."""
    _write_manifest(root, ars_skills)
    _write_install_sh(root, ars_skills)
    _write_install_ps1(root, ars_skills)
    _write_crs_js(root, ars_skills)


class TestCheckInstallerSkillParity(unittest.TestCase):
    """Behaviour of check_installer_skill_parity.py."""

    def test_aligned_fixture_passes(self) -> None:
        """Every installer naming the same skills as the manifest is OK."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_aligned_fixture(root, ["academic-paper", "deep-research"])
            result = _run(root)
            assert result.returncode == 0, result.stdout
            assert "OK" in result.stdout

    def test_skill_missing_from_install_sh_fails(self) -> None:
        """A skill in the manifest but absent from install.sh's arrays fails.

        This is the exact shape of the bug this check exists to catch:
        ``advisor-writing-style`` was added to marketplace.json's
        ``academic-research-skills`` plugin but never to any installer's
        ``ARS_SKILLS`` array, so `curl | bash` silently never installed it.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_aligned_fixture(root, ["academic-paper", "new-skill"])
            _write_install_sh(root, ["academic-paper"])  # new-skill left out
            result = _run(root)
            assert result.returncode == 1, result.stdout
            assert "install.sh" in result.stdout
            assert "new-skill" in result.stdout

    def test_skill_missing_from_every_installer_fails_for_each(self) -> None:
        """A skill left out of all three installers is reported three times."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_aligned_fixture(root, ["academic-paper"])
            _write_manifest(root, ["academic-paper", "advisor-writing-style"])
            result = _run(root)
            assert result.returncode == 1, result.stdout
            for installer in ("install.sh", "install.ps1", "crs.js"):
                assert installer in result.stdout, result.stdout
            assert result.stdout.count("advisor-writing-style") == 3

    def test_installer_skill_absent_from_manifest_fails(self) -> None:
        """An installer offering a skill no plugin declares is also drift."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_aligned_fixture(root, ["academic-paper"])
            _write_install_sh(root, ["academic-paper", "ghost-skill"])
            result = _run(root)
            assert result.returncode == 1, result.stdout
            assert "ghost-skill" in result.stdout

    def test_missing_manifest_reports_a_clear_error(self) -> None:
        """No marketplace.json at all fails with a readable message, not a
        traceback."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _run(root)
            assert result.returncode == 1, result.stdout
            assert "marketplace.json" in result.stdout

    def test_missing_array_in_an_installer_reports_a_clear_error(self) -> None:
        """An installer missing one of the three expected arrays fails
        with a readable message naming the array, not a raw regex failure.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_aligned_fixture(root, ["academic-paper"])
            (root / "install.sh").write_text(
                "#!/usr/bin/env bash\necho no arrays here\n", encoding="utf-8"
            )
            result = _run(root)
            assert result.returncode == 1, result.stdout
            assert "RESOLVER_SKILLS" in result.stdout
