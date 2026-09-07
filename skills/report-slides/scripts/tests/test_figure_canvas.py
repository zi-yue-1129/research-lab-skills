"""The figure canvas is unlocked for figures only, and only its size.

Allowing a larger canvas is what buys density: the type and spacing floors are
absolute, so four times the area at the same minimums holds four times as much.
That makes it important to prove the relaxation is narrow -- a slide must still
be refused the larger canvas, and a figure must still be held to every floor.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
TOKENS = SCRIPTS.parent / "references" / "tokens"


def _validate(tmp_path: Path, tokens: dict) -> bool:
    """Run the token validator over a token mapping.

    Args:
        tmp_path: Directory to write the candidate file into.
        tokens: The token mapping to check.

    Returns:
        Whether the validator accepted it.
    """
    path = tmp_path / "candidate.tokens.yaml"
    path.write_text(yaml.safe_dump(tokens, sort_keys=False), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "validate_design_tokens.py"),
         "--tokens", str(path)],
        capture_output=True, text=True, check=False,
    )
    return json.loads(result.stdout)["valid"]


@pytest.fixture
def slide_tokens() -> dict:
    """The shipped slide token set."""
    return yaml.safe_load((TOKENS / "default.tokens.yaml").read_text(encoding="utf-8"))


def test_the_shipped_sets_are_both_valid() -> None:
    """Neither shipped set may drift out of the schema."""
    for name in ("default", "figure"):
        data = yaml.safe_load((TOKENS / f"{name}.tokens.yaml").read_text(encoding="utf-8"))
        assert isinstance(data, dict)


def test_a_slide_is_refused_the_figure_canvas(tmp_path: Path, slide_tokens: dict) -> None:
    """Without declaring `kind: figure` the canvas stays fixed."""
    tokens = copy.deepcopy(slide_tokens)
    tokens["canvas"]["width"], tokens["canvas"]["height"] = 2400, 1350
    assert _validate(tmp_path, tokens) is False


def test_a_figure_may_use_the_larger_canvas(tmp_path: Path, slide_tokens: dict) -> None:
    """Declaring the kind is what unlocks it."""
    tokens = copy.deepcopy(slide_tokens)
    tokens["kind"] = "figure"
    tokens["canvas"]["width"], tokens["canvas"]["height"] = 2400, 1350
    assert _validate(tmp_path, tokens) is True


def test_a_figure_must_stay_sixteen_by_nine(tmp_path: Path, slide_tokens: dict) -> None:
    """A figure drops into a deck, so its shape is not a free choice."""
    tokens = copy.deepcopy(slide_tokens)
    tokens["kind"] = "figure"
    tokens["canvas"]["width"], tokens["canvas"]["height"] = 2400, 675
    assert _validate(tmp_path, tokens) is False


def test_a_figure_is_still_held_to_the_type_floor(tmp_path: Path, slide_tokens: dict) -> None:
    """The floors are the point: density comes from area, not smaller text."""
    tokens = copy.deepcopy(slide_tokens)
    tokens["kind"] = "figure"
    tokens["canvas"]["width"], tokens["canvas"]["height"] = 2400, 1350
    tokens["typography"]["roles"]["node_label"]["size"] = 9
    assert _validate(tmp_path, tokens) is False


def test_a_figure_is_still_held_to_the_spacing_floor(tmp_path: Path, slide_tokens: dict) -> None:
    """Likewise for the gap a reader needs between two nodes."""
    tokens = copy.deepcopy(slide_tokens)
    tokens["kind"] = "figure"
    tokens["canvas"]["width"], tokens["canvas"]["height"] = 2400, 1350
    tokens["spacing"]["node_gap_min"] = 8
    assert _validate(tmp_path, tokens) is False


def test_font_scale_is_one_on_the_slide_canvas() -> None:
    """Every existing deck must render exactly as it did before.

    The converter scales a declared `font-size` against a 1200-unit reference.
    Any value but 1.0 here would resize the text of every deck already authored.
    """
    from svg_to_pptx.converter import CoordSystem

    assert CoordSystem(1200.0, 675.0).font_scale() == 1.0


def test_font_scale_halves_on_the_double_width_canvas() -> None:
    """The same declared size reads the same on either canvas."""
    from svg_to_pptx.converter import CoordSystem

    assert CoordSystem(2400.0, 1350.0).font_scale() == 0.5
