"""Tests for report-slides setup scripts."""

import subprocess
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent.parent
SETUP_SH = SCRIPT_DIR / "setup.sh"
SETUP_PS1 = SCRIPT_DIR / "setup.ps1"


def test_setup_sh_copies_scripts_and_creates_slide_directories(
    tmp_path: Path,
) -> None:
    """Copy all report-slides utilities and create the asset directories."""
    result = subprocess.run(
        ["bash", str(SETUP_SH)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    expected_paths = (
        "scripts/generate_slides.py",
        "scripts/validate_diagram_manifest.py",
        "scripts/render_review_sheet.py",
        "docs/slides/reports/",
        "docs/slides/assets/diagrams/",
    )
    for expected_path in expected_paths:
        assert expected_path in result.stdout

    assert (tmp_path / "scripts/generate_slides.py").is_file()
    assert (tmp_path / "scripts/validate_diagram_manifest.py").is_file()
    assert (tmp_path / "scripts/render_review_sheet.py").is_file()
    assert (tmp_path / "docs/slides/reports").is_dir()
    assert (tmp_path / "docs/slides/assets/diagrams").is_dir()
    assert "Pillow" in result.stdout
    assert "review-sheet composition" in result.stdout


def test_setup_ps1_mentions_all_scripts_and_diagram_directory() -> None:
    """Keep the PowerShell setup aligned with the shell setup contract."""
    setup_text = SETUP_PS1.read_text(encoding="utf-8")

    assert "generate_slides.py" in setup_text
    assert "validate_diagram_manifest.py" in setup_text
    assert "render_review_sheet.py" in setup_text
    assert 'docs\\slides"' in setup_text  # default $SlidesDir value preserved
    assert "Pillow" in setup_text
    assert "review-sheet composition" in setup_text


def test_setup_sh_accepts_custom_slides_dir(tmp_path: Path) -> None:
    """A caller-supplied SLIDES_DIR argument overrides the docs/slides default."""
    result = subprocess.run(
        ["bash", str(SETUP_SH), "custom/slides/root"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "custom/slides/root/reports/" in result.stdout
    assert (tmp_path / "custom/slides/root/reports").is_dir()
    assert (tmp_path / "custom/slides/root/assets/diagrams").is_dir()
    assert not (tmp_path / "docs").exists()
