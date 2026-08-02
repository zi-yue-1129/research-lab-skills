"""Tests for review-sheet composition and its command-line interface."""

import inspect
import subprocess
import sys
from pathlib import Path
from typing import Tuple

import pytest
from PIL import Image

from render_review_sheet import _parse_arguments, compose_review_sheet


SCRIPT = Path(__file__).resolve().parent.parent / "render_review_sheet.py"


@pytest.fixture
def source_images(tmp_path: Path) -> Tuple[Path, Path]:
    """Create red and blue PNG fixtures for review-sheet tests."""
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (120, 68), (255, 0, 0)).save(first)
    Image.new("RGB", (120, 68), (0, 0, 255)).save(second)
    return first, second


def test_compose_review_sheet_creates_typed_grid_output(
    source_images: Tuple[Path, Path], tmp_path: Path
) -> None:
    """Compose centered previews with the specified grid geometry."""
    first, second = source_images
    output = tmp_path / "nested" / "review-sheet.png"

    result = compose_review_sheet(
        [first, second], output, columns=2, cell_width=120, cell_height=68
    )

    assert result == output
    with Image.open(output) as sheet:
        assert sheet.size == (264, 116)
        assert sheet.getpixel((62, 42))[0] > 200
        assert sheet.getpixel((194, 42))[2] > 200


def test_review_sheet_defaults_match_visual_authoring_contract() -> None:
    """Keep composition and CLI geometry defaults aligned with the plan."""
    parameters = inspect.signature(compose_review_sheet).parameters
    assert (
        parameters["columns"].default,
        parameters["cell_width"].default,
        parameters["cell_height"].default,
    ) == (2, 600, 338)

    parsed = _parse_arguments(["--input", "slide.png", "--out", "review.png"])
    assert (parsed.columns, parsed.cell_width, parsed.cell_height) == (2, 600, 338)


def test_compose_review_sheet_requires_existing_inputs(
    tmp_path: Path,
) -> None:
    """Raise FileNotFoundError when an input image does not exist."""
    with pytest.raises(FileNotFoundError):
        compose_review_sheet(
            [tmp_path / "missing.png"],
            tmp_path / "review-sheet.png",
            columns=1,
            cell_width=120,
            cell_height=68,
        )


@pytest.mark.parametrize(
    "input_path",
    [Path("diagram.svg"), Path("diagram.SVG")],
)
def test_compose_review_sheet_rejects_svg_inputs(
    input_path: Path, tmp_path: Path
) -> None:
    """Reject SVG inputs before attempting raster decoding."""
    svg_path = tmp_path / input_path
    svg_path.write_text("<svg />", encoding="utf-8")

    with pytest.raises(ValueError):
        compose_review_sheet(
            [svg_path],
            tmp_path / "review-sheet.png",
            columns=1,
            cell_width=120,
            cell_height=68,
        )


def test_compose_review_sheet_rejects_empty_inputs(tmp_path: Path) -> None:
    """Reject an empty input sequence."""
    with pytest.raises(ValueError):
        compose_review_sheet(
            [],
            tmp_path / "review-sheet.png",
            columns=1,
            cell_width=120,
            cell_height=68,
        )


@pytest.mark.parametrize(
    ("columns", "cell_width", "cell_height"),
    [(0, 120, 68), (1, 0, 68), (1, 120, -1)],
)
def test_compose_review_sheet_rejects_non_positive_geometry(
    columns: int, cell_width: int, cell_height: int, tmp_path: Path
) -> None:
    """Reject non-positive grid geometry before reading input files."""
    with pytest.raises(ValueError):
        compose_review_sheet(
            [tmp_path / "missing.png"],
            tmp_path / "review-sheet.png",
            columns=columns,
            cell_width=cell_width,
            cell_height=cell_height,
        )


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the review-sheet CLI with the supplied arguments."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_review_sheet_cli_accepts_repeated_inputs(
    source_images: Tuple[Path, Path], tmp_path: Path
) -> None:
    """Accept repeated --input arguments and report the output path."""
    first, second = source_images
    output = tmp_path / "review-sheet.png"

    result = _run_cli(
        "--input",
        str(first),
        "--input",
        str(second),
        "--out",
        str(output),
        "--columns",
        "2",
        "--cell-width",
        "120",
        "--cell-height",
        "68",
    )

    assert result.returncode == 0
    assert result.stdout.strip() == f"OK: review sheet written to {output}"
    assert result.stderr == ""


def test_review_sheet_cli_reports_failures_to_stderr(tmp_path: Path) -> None:
    """Report composition failures with an ERROR prefix and exit one."""
    result = _run_cli(
        "--input",
        str(tmp_path / "missing.png"),
        "--out",
        str(tmp_path / "review-sheet.png"),
        "--columns",
        "1",
        "--cell-width",
        "120",
        "--cell-height",
        "68",
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR: ")
