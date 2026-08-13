"""Tests for the deterministic plan-preview formatter and CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from render_plan_preview import format_plan_preview


SCRIPT = Path(__file__).resolve().parent.parent / "render_plan_preview.py"


def valid_plan() -> dict[str, Any]:
    """Return a complete plan fixture covering every preview field."""
    return {
        "schema_version": 1,
        "deck_id": "deck-preview",
        "plan_version": 3,
        "purpose": "Explain the measured result.",
        "audience": "Research leads",
        "estimated_duration_minutes": 12,
        "core_narrative": "Evidence changes decisions.",
        "status": "reviewed",
        "authored_by": "planner-a",
        "known_gaps": ["Long-term validation is pending."],
        "excluded_content": ["Unrelated benchmark details."],
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Evidence changes decisions",
                "key_takeaway": "The intervention improves outcomes.",
                "evidence_refs": ["study:table-1", "study:figure-2"],
                "intended_visual_type": "data",
                "visual_rationale": "A compact trend makes the change visible.",
                "purpose": "State the result.",
                "speaker_message": "Name the decision implication.",
                "dependencies": [],
                "open_questions": [],
            },
        ],
    }


def test_plan_preview_contains_every_approval_field() -> None:
    """Render all plan-level and slide-level evidence in deterministic text."""
    output = format_plan_preview(valid_plan())

    for text in (
        "Purpose",
        "Audience",
        "Duration",
        "Core narrative",
        "Known gaps",
        "Excluded content",
        "slide-01",
        "Key takeaway",
        "Evidence",
        "Planned visual",
    ):
        assert text in output


def test_plan_preview_rejects_non_mapping() -> None:
    """Fail closed instead of formatting an invalid plan as an empty preview."""
    with pytest.raises(ValueError, match="plan must be a mapping"):
        format_plan_preview([])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", True, "schema_version"),
        ("estimated_duration_minutes", 0, "estimated_duration_minutes"),
        ("status", "approved", "status"),
        ("slides", None, "slides"),
        ("slides", [{"slide_id": "slide-01", "title": "A"}], r"slides\[0\]"),
    ],
)
def test_plan_preview_rejects_any_strict_plan_validation_error(
    field: str, value: Any, message: str
) -> None:
    """Formatting must run the strict Deck Plan validator before rendering."""
    plan = valid_plan()
    if field == "slides" and value is None:
        plan["slides"] = None
    elif field == "slides":
        plan["slides"] = [dict(value[0])]
    else:
        plan[field] = value

    with pytest.raises(ValueError, match=message):
        format_plan_preview(plan)


def test_plan_preview_rejects_dependency_cycles() -> None:
    """Cyclic dependencies are contract errors, not displayable previews."""
    plan = valid_plan()
    second = dict(plan["slides"][0], slide_id="slide-02", dependencies=["slide-01"])
    plan["slides"][0]["dependencies"] = ["slide-02"]
    plan["slides"].append(second)

    with pytest.raises(ValueError, match="dependencies"):
        format_plan_preview(plan)


def test_plan_preview_rejects_invalid_visual_enum() -> None:
    """Unknown planned visual types are rejected by the strict validator."""
    plan = valid_plan()
    plan["slides"][0]["intended_visual_type"] = "mystery"

    with pytest.raises(ValueError, match="intended_visual_type"):
        format_plan_preview(plan)


def test_plan_preview_cli_writes_only_stdout(tmp_path: Path) -> None:
    """The --plan CLI prints preview text and creates no artifact files."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(valid_plan()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--plan", str(plan_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Core narrative" in result.stdout
    assert result.stderr == ""
    assert sorted(tmp_path.iterdir()) == [plan_path]


def test_plan_preview_cli_reports_malformed_yaml_without_traceback(tmp_path: Path) -> None:
    """Malformed YAML produces structured stderr and no traceback/artifacts."""
    plan_path = tmp_path / "broken.yaml"
    plan_path.write_text("slides: [", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--plan", str(plan_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    error = json.loads(result.stderr)
    assert error["error"] in {"YAMLError", "ParserError", "ScannerError"}
    assert sorted(tmp_path.iterdir()) == [plan_path]
