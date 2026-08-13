"""Tests for strict Deck Plan and Deck Approval validation."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from validate_deck_plan import validate_deck_plan


SCRIPT = Path(__file__).resolve().parent.parent / "validate_deck_plan.py"


def valid_slide(slide_id: str = "slide-01") -> dict[str, Any]:
    """Return one complete slide fixture for a valid Deck Plan."""
    return {
        "slide_id": slide_id,
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


def valid_plan() -> dict[str, Any]:
    """Return a complete reviewed Deck Plan fixture."""
    return {
        "schema_version": 1,
        "plan_version": 1,
        "deck_id": "deck-q3-results",
        "purpose": "Report Q3 experiment results to the research team",
        "audience": "internal research team",
        "estimated_duration_minutes": 15,
        "core_narrative": "Action-conditioned models provide the clearest gains.",
        "status": "reviewed",
        "slides": [valid_slide()],
        "excluded_content": ["Unrelated Q2 baseline data"],
        "known_gaps": ["Long-horizon rollout stability not yet measured"],
        "authored_by": "research_narrative_planner",
    }


def valid_approval() -> dict[str, Any]:
    """Return a complete Deck Approval fixture."""
    return {
        "schema_version": 1,
        "deck_id": "deck-q3-results",
        "plan_version": 1,
        "plan_sha256": "a" * 64,
        "decision": "approve",
        "approved_by": "user",
        "approved_at": "2026-08-08T12:30:45Z",
        "approval_mode": "interactive",
    }


def run_validator(tmp_path: Path, option: str, document: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    """Run the validator CLI for a YAML fixture document."""
    document_path = tmp_path / "document.yaml"
    document_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), option, str(document_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_valid_plan_passes(tmp_path: Path) -> None:
    """Accept a reviewed plan containing every required contract field."""
    result = run_validator(tmp_path, "--plan", valid_plan())

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_plan_missing_purpose_fails(tmp_path: Path) -> None:
    """Reject a plan that omits its audience-facing purpose."""
    plan = valid_plan()
    plan.pop("purpose")

    result = run_validator(tmp_path, "--plan", plan)

    assert result.returncode == 1
    assert any("purpose" in error for error in json.loads(result.stdout)["errors"])


def test_plan_empty_slides_list_fails(tmp_path: Path) -> None:
    """Reject a plan that proposes no slides."""
    plan = valid_plan()
    plan["slides"] = []

    result = run_validator(tmp_path, "--plan", plan)

    assert result.returncode == 1
    assert any("slides" in error for error in json.loads(result.stdout)["errors"])


def test_plan_requires_complete_user_preview_fields(tmp_path: Path) -> None:
    """Reject a user-preview plan whenever a mandatory contract field is absent."""
    for field in (
        "schema_version",
        "plan_version",
        "core_narrative",
        "status",
        "excluded_content",
        "known_gaps",
        "authored_by",
    ):
        invalid = dict(valid_plan())
        invalid.pop(field)

        result = run_validator(tmp_path, "--plan", invalid)

        assert result.returncode == 1
        assert any(field in error for error in json.loads(result.stdout)["errors"])


def test_plan_accepts_planning_status_for_registration(tmp_path: Path) -> None:
    """Accept planner output before the separate content-review gate."""
    plan = valid_plan()
    plan["status"] = "planning"

    result = run_validator(tmp_path, "--plan", plan)

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_plan_rejects_unknown_status(tmp_path: Path) -> None:
    """Reject plan statuses outside the contract lifecycle."""
    plan = valid_plan()
    plan["status"] = "not-a-status"

    result = run_validator(tmp_path, "--plan", plan)

    assert result.returncode == 1
    assert any("status" in error for error in json.loads(result.stdout)["errors"])


def test_plan_rejects_empty_evidence_and_dependency_cycle() -> None:
    """Reject slides without evidence and plans with circular dependencies."""
    plan = valid_plan()
    first_slide = plan["slides"][0]
    second_slide = valid_slide("slide-02")
    first_slide["evidence_refs"] = []
    first_slide["dependencies"] = ["slide-02"]
    second_slide["dependencies"] = ["slide-01"]
    plan["slides"] = [first_slide, second_slide]

    errors = validate_deck_plan(plan)

    assert any("evidence_refs" in error for error in errors)
    assert any("cycle" in error for error in errors)


def test_plan_rejects_undeclared_dependency() -> None:
    """Reject dependencies that do not name a declared slide."""
    plan = valid_plan()
    plan["slides"][0]["dependencies"] = ["slide-unknown"]

    errors = validate_deck_plan(plan)

    assert any("dependencies" in error and "slide-unknown" in error for error in errors)


def test_plan_requires_dependency_and_open_question_lists(tmp_path: Path) -> None:
    """Reject slides that omit dependency or open-question collections."""
    for field in ("dependencies", "open_questions"):
        plan = valid_plan()
        plan["slides"][0].pop(field)

        result = run_validator(tmp_path, "--plan", plan)

        assert result.returncode == 1
        assert any(field in error for error in json.loads(result.stdout)["errors"])


def test_plan_duplicate_slide_id_fails(tmp_path: Path) -> None:
    """Reject plans that reuse a slide identifier."""
    plan = valid_plan()
    plan["slides"] = [valid_slide(), valid_slide()]

    result = run_validator(tmp_path, "--plan", plan)

    assert result.returncode == 1
    assert any("duplicate slide_id" in error for error in json.loads(result.stdout)["errors"])


def test_plan_invalid_visual_type_fails(tmp_path: Path) -> None:
    """Reject a slide whose visual routing value is outside the contract."""
    plan = valid_plan()
    plan["slides"][0]["intended_visual_type"] = "not-a-real-route"

    result = run_validator(tmp_path, "--plan", plan)

    assert result.returncode == 1
    assert any("intended_visual_type" in error for error in json.loads(result.stdout)["errors"])


def test_plan_slide_missing_key_takeaway_fails(tmp_path: Path) -> None:
    """Reject slides without a protected takeaway."""
    plan = valid_plan()
    plan["slides"][0].pop("key_takeaway")

    result = run_validator(tmp_path, "--plan", plan)

    assert result.returncode == 1
    assert any("key_takeaway" in error for error in json.loads(result.stdout)["errors"])


def test_valid_approval_approve_passes(tmp_path: Path) -> None:
    """Accept a complete interactive approval for a reviewed plan."""
    result = run_validator(tmp_path, "--approval", valid_approval())

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_approval_requires_complete_contract_fields(tmp_path: Path) -> None:
    """Reject approvals that omit mandatory identity or provenance fields."""
    for field in (
        "schema_version",
        "deck_id",
        "plan_version",
        "plan_sha256",
        "decision",
        "approved_by",
        "approved_at",
        "approval_mode",
    ):
        approval = valid_approval()
        approval.pop(field)

        result = run_validator(tmp_path, "--approval", approval)

        assert result.returncode == 1
        assert any(field in error for error in json.loads(result.stdout)["errors"])


def test_approval_rejects_invalid_provenance_values(tmp_path: Path) -> None:
    """Reject non-canonical digests, timestamps, and approval modes."""
    invalid_values = {
        "plan_version": 0,
        "plan_sha256": "A" * 64,
        "approved_at": "2026-08-08T12:30:45+00:00",
        "approval_mode": "automatic",
    }
    for field, value in invalid_values.items():
        approval = valid_approval()
        approval[field] = value

        result = run_validator(tmp_path, "--approval", approval)

        assert result.returncode == 1
        assert any(field in error for error in json.loads(result.stdout)["errors"])


def test_approval_rejects_non_scalar_decision_and_mode(tmp_path: Path) -> None:
    """Return structured errors when enum fields are YAML lists or mappings."""
    invalid_values = {
        "decision": ["approve"],
        "approval_mode": {"mode": "interactive"},
    }
    for field, value in invalid_values.items():
        approval = valid_approval()
        approval[field] = value

        result = run_validator(tmp_path, "--approval", approval)

        assert result.returncode == 1
        assert json.loads(result.stdout)["valid"] is False
        assert any(field in error for error in json.loads(result.stdout)["errors"])


def test_approval_revise_validates_each_revision_request(tmp_path: Path) -> None:
    """Reject revision evidence that omits the retained request contract."""
    approval = valid_approval()
    approval["decision"] = "revise"
    approval["revisions_requested"] = [{}]

    result = run_validator(tmp_path, "--approval", approval)

    assert result.returncode == 1
    errors = json.loads(result.stdout)["errors"]
    assert any("revisions_requested[0]" in error for error in errors)


def test_valid_approval_revise_accepts_complete_revision_request(tmp_path: Path) -> None:
    """Accept a revise decision with a complete retained Revision Request."""
    approval = valid_approval()
    approval["decision"] = "revise"
    approval["revisions_requested"] = [
        {
            "subject_type": "plan",
            "subject_id": "deck-q3-results",
            "requested_by": "user",
            "instructions": "Clarify the narrative emphasis.",
            "superseded_subject_id": None,
            "revision_kind": "change_emphasis",
        }
    ]

    result = run_validator(tmp_path, "--approval", approval)

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_approval_invalid_decision_fails(tmp_path: Path) -> None:
    """Reject decisions outside approve/revise."""
    approval = valid_approval()
    approval["decision"] = "maybe"

    result = run_validator(tmp_path, "--approval", approval)

    assert result.returncode == 1
    assert any("decision" in error for error in json.loads(result.stdout)["errors"])


def test_valid_approval_revise_requires_revisions_requested(tmp_path: Path) -> None:
    """Require concrete revision requests when the user declines approval."""
    approval = valid_approval()
    approval["decision"] = "revise"

    result = run_validator(tmp_path, "--approval", approval)

    assert result.returncode == 1
    assert any("revisions_requested" in error for error in json.loads(result.stdout)["errors"])


def test_malformed_yaml_reports_error(tmp_path: Path) -> None:
    """Return a validation result for malformed input instead of crashing."""
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("deck_id: [unterminated", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--plan", str(plan_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["valid"] is False
