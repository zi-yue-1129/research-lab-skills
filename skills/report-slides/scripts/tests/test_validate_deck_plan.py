"""Tests for validate_deck_plan.py."""
import json
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parent.parent / "validate_deck_plan.py"

_VALID_SLIDE = {
    "slide_id": "slide-01",
    "title": "Action conditioning improves command sensitivity",
    "purpose": "Establish the core result",
    "key_takeaway": "Conditioning on action improves sensitivity by 2x",
    "evidence_refs": ["log-2026-08-01#experiment-3"],
    "intended_visual_type": "data",
    "visual_rationale": "A bar chart best shows the magnitude of improvement",
    "speaker_message": "This is our headline finding",
    "dependencies": [],
    "open_questions": [],
}

_VALID_PLAN = {
    "deck_id": "deck-q3-results",
    "purpose": "Report Q3 experiment results to the research team",
    "audience": "internal research team",
    "estimated_duration_minutes": 15,
    "slides": [_VALID_SLIDE],
    "excluded_content": ["Unrelated Q2 baseline data"],
    "known_gaps": ["Long-horizon rollout stability not yet measured"],
}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_valid_plan_passes(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(_VALID_PLAN))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 0, result.stdout
    data = json.loads(result.stdout)
    assert data == {"valid": True, "errors": []}


def test_plan_missing_purpose_fails(tmp_path: Path) -> None:
    plan = {**_VALID_PLAN}
    del plan["purpose"]
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["valid"] is False
    assert any("purpose" in err for err in data["errors"])


def test_plan_empty_slides_list_fails(tmp_path: Path) -> None:
    plan = {**_VALID_PLAN, "slides": []}
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("slides" in err for err in data["errors"])


def test_plan_duplicate_slide_id_fails(tmp_path: Path) -> None:
    plan = {**_VALID_PLAN, "slides": [_VALID_SLIDE, {**_VALID_SLIDE}]}
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("duplicate slide_id" in err for err in data["errors"])


def test_plan_invalid_visual_type_fails(tmp_path: Path) -> None:
    bad_slide = {**_VALID_SLIDE, "intended_visual_type": "not-a-real-route"}
    plan = {**_VALID_PLAN, "slides": [bad_slide]}
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("intended_visual_type" in err for err in data["errors"])


def test_plan_slide_missing_key_takeaway_fails(tmp_path: Path) -> None:
    bad_slide = {k: v for k, v in _VALID_SLIDE.items() if k != "key_takeaway"}
    plan = {**_VALID_PLAN, "slides": [bad_slide]}
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("key_takeaway" in err for err in data["errors"])


def test_valid_approval_approve_passes(tmp_path: Path) -> None:
    approval = {"deck_id": "deck-q3-results", "plan_version": 1, "decision": "approve", "approved_by": "user"}
    approval_path = tmp_path / "approval.yaml"
    approval_path.write_text(yaml.safe_dump(approval))

    result = _run("--approval", str(approval_path), "--json")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_valid_approval_revise_requires_revisions_requested(tmp_path: Path) -> None:
    approval = {"deck_id": "deck-q3-results", "decision": "revise", "approved_by": "user"}
    approval_path = tmp_path / "approval.yaml"
    approval_path.write_text(yaml.safe_dump(approval))

    result = _run("--approval", str(approval_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("revisions_requested" in err for err in data["errors"])


def test_approval_invalid_decision_fails(tmp_path: Path) -> None:
    approval = {"deck_id": "deck-q3-results", "decision": "maybe", "approved_by": "user"}
    approval_path = tmp_path / "approval.yaml"
    approval_path.write_text(yaml.safe_dump(approval))

    result = _run("--approval", str(approval_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("decision" in err for err in data["errors"])


def test_malformed_yaml_reports_error(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("deck_id: [unterminated")

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["valid"] is False
