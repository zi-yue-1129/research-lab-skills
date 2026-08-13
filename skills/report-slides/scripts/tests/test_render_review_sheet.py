"""Tests for review-sheet composition and its command-line interface."""

import inspect
import subprocess
import sys
from pathlib import Path
from typing import Tuple

import pytest
from PIL import Image
import yaml

from presentation_contracts import contract_sha256
from render_review_sheet import _parse_arguments, compose_review_sheet, contact_sheet_source_digest
from render_plan_preview import _canonical_source_digest
from test_artifact_entrypoint_gates import deck_awaiting_approval


SCRIPT = Path(__file__).resolve().parent.parent / "render_review_sheet.py"


@pytest.fixture
def approved_deck_project(tmp_path: Path) -> Tuple[Path, str]:
    """Create an approved deck fixture for the supported CLI path."""
    project, deck_id = deck_awaiting_approval(tmp_path)
    plan = yaml.safe_load((project / "plan.yaml").read_text(encoding="utf-8"))
    state_path = project / ".research/presentations/state/decks.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["decks"][deck_id].update(
        {
            "status": "approved",
            "approval_id": "approval-test",
            "approved_plan_version": plan["plan_version"],
            "approved_plan_sha256": contract_sha256(plan),
        }
    )
    state_path.write_text(yaml.safe_dump(state), encoding="utf-8")
    return project, deck_id


@pytest.fixture
def source_images(tmp_path: Path) -> Tuple[Path, Path]:
    """Create red and blue PNG fixtures for review-sheet tests."""
    (tmp_path / ".git").mkdir()
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

    parsed = _parse_arguments(
        ["--input", "slide.png", "--out", "review.png", "--deck-id", "deck-test"]
    )
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


def test_contact_sheet_source_digest_binds_ordered_input_bytes(
    source_images: Tuple[Path, Path],
) -> None:
    """Source digest changes when either bytes or ordering changes."""
    first, second = source_images
    forward = contact_sheet_source_digest([first, second])
    reverse = contact_sheet_source_digest([second, first])
    assert forward != reverse
    first.write_bytes(b"changed")
    assert contact_sheet_source_digest([first, second]) != forward


def test_contact_sheet_source_digest_uses_preview_canonical_helper(
    source_images: Tuple[Path, Path],
) -> None:
    """Renderer and preview gate derive identical ordered source digests."""
    first, second = source_images
    paths = [first.name, second.name]
    digests = [
        __import__("hashlib").sha256(first.read_bytes()).hexdigest(),
        __import__("hashlib").sha256(second.read_bytes()).hexdigest(),
    ]

    assert contact_sheet_source_digest([first, second]) == _canonical_source_digest(paths, digests)


def test_contact_sheet_source_digest_uses_canonical_project_relative_nested_paths(
    tmp_path: Path,
) -> None:
    """Nested absolute inputs hash their ordered project-relative paths."""
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    render_dir = project / "renders" / "nested"
    render_dir.mkdir(parents=True)
    first = render_dir / "slide-01.png"
    second = render_dir / "slide-02.png"
    Image.new("RGB", (10, 10), (10, 20, 30)).save(first)
    Image.new("RGB", (10, 10), (40, 50, 60)).save(second)
    digests = [
        __import__("hashlib").sha256(first.read_bytes()).hexdigest(),
        __import__("hashlib").sha256(second.read_bytes()).hexdigest(),
    ]

    expected = _canonical_source_digest(
        ["renders/nested/slide-01.png", "renders/nested/slide-02.png"],
        digests,
    )
    assert contact_sheet_source_digest([first, second]) == expected


def test_compose_review_sheet_rejects_duplicate_or_overwritten_inputs(
    source_images: Tuple[Path, Path], tmp_path: Path
) -> None:
    """Reject ambiguous source sets before creating a contact sheet."""
    first, _ = source_images
    with pytest.raises(ValueError, match="unique"):
        compose_review_sheet([first, first], tmp_path / "contact.png")
    with pytest.raises(ValueError, match="overwrite"):
        compose_review_sheet([first], first)


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
    source_images: Tuple[Path, Path], approved_deck_project: Tuple[Path, str]
) -> None:
    """Accept repeated --input arguments and report the output path."""
    first, second = source_images
    project, deck_id = approved_deck_project
    output = project / "review-sheet.png"

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
        "--deck-id",
        deck_id,
        "--project-root",
        str(project),
    )

    assert result.returncode == 0
    assert result.stdout.strip() == f"OK: review sheet written to {output}"
    assert result.stderr == ""


def test_review_sheet_cli_reports_failures_to_stderr(
    approved_deck_project: Tuple[Path, str]
) -> None:
    """Report composition failures with an ERROR prefix and exit one."""
    project, deck_id = approved_deck_project
    result = _run_cli(
        "--input",
        str(project / "missing.png"),
        "--out",
        str(project / "review-sheet.png"),
        "--columns",
        "1",
        "--cell-width",
        "120",
        "--cell-height",
        "68",
        "--deck-id",
        deck_id,
        "--project-root",
        str(project),
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR: ")
