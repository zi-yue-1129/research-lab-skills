"""Tests for the generative prompt-record contract."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml
from PIL import Image

from style_anchors import CANDIDATE_COUNT
from validate_generative_prompt import (
    parse_prompt_record, validate_prompt_record,
)

_SKILL_DIR = Path(__file__).resolve().parents[2]
_SCRIPTS = _SKILL_DIR / "scripts"
_CLI = _SCRIPTS / "validate_generative_prompt.py"


@pytest.fixture()
def anchors(tmp_path: Path) -> Path:
    """Write a one-anchor registry with a real reference image.

    The shipped registry is empty by design (spec D6), so a test that needs a
    resolvable anchor must supply one. Building it here also keeps the test
    independent of whichever anchors a human later curates.
    """
    directory = tmp_path / "anchors"
    directory.mkdir()
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (30, 58, 95)).save(buffer, format="PNG")
    (directory / "schematic-01.png").write_bytes(buffer.getvalue())
    registry = directory / "anchors.yaml"
    registry.write_text(yaml.safe_dump({"anchors": [{
        "id": "technical-schematic",
        "name": "Technical schematic",
        "summary": "A flat drafted diagram in the manner of a paper figure.",
        "applies_to": ["system architectures"],
        "composition": "Orthogonal arrangement on a single plane.",
        "line_treatment": "Uniform-weight outlines, flat fills.",
        "palette_roles": ["primary", "body", "line", "bg"],
        "forbidden": ["glow or bloom"],
        "reference_images": [{
            "path": "schematic-01.png",
            "sha256": hashlib.sha256(buffer.getvalue()).hexdigest(),
        }],
    }]}), encoding="utf-8")
    return registry


def _candidates(count: int = CANDIDATE_COUNT,
                matching: int = 1) -> List[Dict[str, Any]]:
    """Build a ranked candidate list.

    Args:
        count: How many candidates to produce.
        matching: How many of them match the anchor, taken from the top rank
            downwards.

    Returns:
        Candidate entries in rank order.
    """
    return [
        {"id": f"c{index + 1}",
         "asset": f"renders/candidate-{index + 1:02d}.png",
         "rank": index + 1,
         "matches_anchor": index < matching}
        for index in range(count)
    ]


def _record(**overrides: Any) -> Dict[str, Any]:
    """Build a valid prompt record, then apply overrides."""
    record: Dict[str, Any] = {
        "purpose": "Show how retrieved passages enter the ranking stage.",
        "illustration_rationale": (
            "The claim is about the shape of the flow, which the deterministic "
            "diagram route cannot render at the required level of abstraction."),
        "style_anchor": "technical-schematic",
        "composition": "Three stages left to right, open margin above.",
        "subject": "A retrieval pipeline and its ranked output.",
        "palette": "Design-token roles primary, body, line, card, bg.",
        "lighting": "Flat, no directional light.",
        "empty_annotation_regions": "Upper third.",
        "exclusions": ["prose", "labels", "legends", "exact values",
                       "watermarks", "signatures"],
        "aspect_ratio": "16:9",
        "references": [],
        "changed_regions": [],
        "candidates": _candidates(),
        "ranking": {"blinded": True, "ranked_by": "art_direction"},
        "selected": "c1",
    }
    record.update(overrides)
    return record


def test_a_complete_record_validates(anchors: Path) -> None:
    """The reference record passes."""
    assert validate_prompt_record(_record(), anchors) == []


def test_a_missing_style_anchor_is_rejected(anchors: Path) -> None:
    """An unanchored prompt is the failure mode; it cannot be optional."""
    record = _record()
    del record["style_anchor"]
    errors = validate_prompt_record(record, anchors)
    assert any("style_anchor" in error for error in errors)


def test_an_unknown_style_anchor_is_rejected(anchors: Path) -> None:
    """Citing an anchor that does not exist is not anchoring."""
    errors = validate_prompt_record(_record(style_anchor="vibes"), anchors)
    assert any("vibes" in error for error in errors)


def test_an_empty_registry_rejects_every_record() -> None:
    """With no curated anchor the generative route is closed, not permissive."""
    errors = validate_prompt_record(_record())
    assert errors
    assert any("empty" in error for error in errors)


def test_a_missing_rationale_is_rejected(anchors: Path) -> None:
    """The generative route must be justified, not merely chosen."""
    record = _record()
    del record["illustration_rationale"]
    errors = validate_prompt_record(record, anchors)
    assert any("illustration_rationale" in error for error in errors)


def test_a_banned_motif_anywhere_in_the_record_is_rejected(
    anchors: Path,
) -> None:
    """The scan reads the whole record, not just one field."""
    errors = validate_prompt_record(_record(
        subject="A glowing neural network sphere above a data city."), anchors)
    assert any("glowing-neural-sphere" in error for error in errors)
    assert any("abstract-data-city" in error for error in errors)


def test_the_shipped_examples_prompt_would_now_be_rejected(
    anchors: Path,
) -> None:
    """The documented failure must not be able to recur through this path."""
    errors = validate_prompt_record(_record(
        composition=("One focal researcher in a lab coat at left, a glowing "
                     "neural network sphere at right, flowing light above.")),
        anchors)
    assert errors


def test_required_exclusions_must_be_present(anchors: Path) -> None:
    """The pre-existing exclusion contract is still enforced."""
    errors = validate_prompt_record(_record(exclusions=["prose"]), anchors)
    assert any("exclusions" in error for error in errors)


def test_fewer_than_three_candidates_is_rejected(anchors: Path) -> None:
    """Spec D6 requires three candidates, not the first image that arrived."""
    errors = validate_prompt_record(
        _record(candidates=_candidates(count=2)), anchors)
    assert any("candidates" in error and "3" in error for error in errors)


def test_unblinded_ranking_is_rejected(anchors: Path) -> None:
    """A ranker who knows which candidate is which is not ranking blind.

    This is the assertion that carries the requirement. Without it the field is
    documentation: a record could set `blinded: false` and still validate, and
    "ranked blind" would mean whatever the author felt it meant.
    """
    errors = validate_prompt_record(
        _record(ranking={"blinded": False, "ranked_by": "art_direction"}),
        anchors)
    assert any("blinded" in error for error in errors)


def test_duplicate_or_gapped_ranks_are_rejected(anchors: Path) -> None:
    """Ranks must be a permutation of 1..n, or the ordering means nothing."""
    broken = _candidates()
    broken[1]["rank"] = 1
    errors = validate_prompt_record(_record(candidates=broken), anchors)
    assert any("rank" in error for error in errors)


def test_selecting_a_candidate_that_does_not_match_is_rejected(
    anchors: Path,
) -> None:
    """Spec D6: "Accepting the least-bad image is prohibited."

    When the top-ranked candidate still does not match the anchor, the module
    downgrades. Selecting it anyway is the exact behaviour the spec forbids, so
    it must fail validation rather than depend on the author's restraint.
    """
    errors = validate_prompt_record(
        _record(candidates=_candidates(matching=0)), anchors)
    assert any("downgrade" in error for error in errors)


def test_a_clean_downgrade_validates(anchors: Path) -> None:
    """No candidate matched, and the record says so instead of selecting one."""
    record = _record(candidates=_candidates(matching=0), selected=None,
                     downgraded_to="native-editorial")
    assert validate_prompt_record(record, anchors) == []


def test_selecting_an_unknown_candidate_id_is_rejected(anchors: Path) -> None:
    """`selected` must name one of the candidates that were actually ranked."""
    errors = validate_prompt_record(_record(selected="c9"), anchors)
    assert any("c9" in error for error in errors)


def test_parse_reads_the_yaml_block_from_a_prompt_markdown(
    tmp_path: Path,
) -> None:
    """prompt.md carries the record in a fenced yaml block."""
    path = tmp_path / "prompt.md"
    path.write_text(
        "# Prompt\n\n```yaml\npurpose: A\n"
        "style_anchor: technical-schematic\n```\n",
        encoding="utf-8")
    record = parse_prompt_record(path)
    assert record["style_anchor"] == "technical-schematic"


def test_parse_accepts_a_plain_yaml_record(tmp_path: Path) -> None:
    """Records predating the fenced-block convention still validate."""
    path = tmp_path / "prompt.md"
    path.write_text("purpose: A\nstyle_anchor: technical-schematic\n",
                    encoding="utf-8")
    assert parse_prompt_record(path)["style_anchor"] == "technical-schematic"


def test_parse_rejects_a_record_that_is_not_a_mapping(tmp_path: Path) -> None:
    """A record that cannot be read is an error, not an empty record."""
    path = tmp_path / "prompt.md"
    path.write_text("# Prompt\n\nsome prose\n", encoding="utf-8")
    with pytest.raises(ValueError, match="prompt-record mapping"):
        parse_prompt_record(path)


def test_cli_exits_one_on_an_invalid_record(tmp_path: Path) -> None:
    """The CLI is usable as a gate."""
    path = tmp_path / "prompt.md"
    path.write_text("```yaml\npurpose: A\n```\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--prompt", str(path), "--json"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["valid"] is False
