"""The shipped examples must satisfy the gates this skill enforces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from design_tokens import DEFAULT_TOKENS_PATH
from validate_generative_prompt import (
    parse_prompt_record, validate_prompt_record,
)
from validate_visual_style import lint_paths

_REPO = Path(__file__).resolve().parents[4]
_EXAMPLE = _REPO / "examples/report-slides/visual-authoring"
_COUNTER = _EXAMPLE / "assets/research-collaboration"


def test_the_example_deck_directory_is_where_the_test_expects() -> None:
    """Guard the path arithmetic, so a miss is not a silent pass."""
    assert _EXAMPLE.is_dir()
    assert (_EXAMPLE / "slides").is_dir()


def test_the_counter_example_prompt_is_rejected() -> None:
    """The prompt that produced the documented failure must not validate."""
    record = parse_prompt_record(_COUNTER / "prompt.md")
    errors = validate_prompt_record(record)
    assert errors
    assert any("banned motif" in error for error in errors)


def test_the_counter_example_is_documented_as_one() -> None:
    """A retained failure must say why it is retained."""
    text = (_COUNTER / "WHY-THIS-FAILS.md").read_text(encoding="utf-8")
    assert "visual-cliche" in text
    assert "stock-ai-composition" in text
    assert "decorative-noise" in text
    assert "downgrade" in text.lower()


def test_the_counter_example_review_records_the_failure() -> None:
    """review.json must no longer claim this asset passed."""
    review = json.loads((_COUNTER / "review.json").read_text(encoding="utf-8"))
    assert review["status"] == "failed"
    kinds = {finding["kind"]
             for finding in review["art_direction"]["findings"]}
    assert {"visual-cliche", "stock-ai-composition",
            "decorative-noise"} <= kinds


def test_the_raster_layer_was_downgraded_out_of_the_deck() -> None:
    """The atmosphere-only bitmap is no longer referenced by any slide."""
    review = json.loads((_COUNTER / "review.json").read_text(encoding="utf-8"))
    assert review["remaining_raster_layers"] == []
    for svg in sorted((_EXAMPLE / "slides").glob("*.svg")):
        assert "research-collaboration/generated.png" not in svg.read_text(
            encoding="utf-8")


@pytest.mark.parametrize(
    "slide_name",
    ["slide01-architecture.svg", "slide02-hybrid.svg", "slide03-chart.svg"])
def test_every_shipped_slide_passes_the_visual_style_gate(
    slide_name: str,
) -> None:
    """The examples must satisfy the gate this skill applies to users' decks."""
    result = lint_paths([_EXAMPLE / "slides" / slide_name],
                        DEFAULT_TOKENS_PATH)
    assert result["valid"] is True, json.dumps(
        result["files"][0]["findings"], indent=2)
