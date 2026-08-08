"""Behavioral tests for report-slides gate predicates."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_gates import (
    ApprovalGateError,
    CompletionGateError,
    assert_deck_completable,
    assert_plan_approvable,
)
from presentation_state import create_deck, record_review, set_deck_status
from presentation_events import register_plan_record


SCRIPT = Path(__file__).resolve().parents[1] / "presentation_state.py"


def _project(tmp_path: Path) -> Path:
    """Create a temporary project root recognized by presentation_state."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _plan(deck_id: str, authored_by: str = "planner-a") -> dict:
    """Return a strict, reviewable one-slide plan contract."""
    return {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "purpose": "Explain the result",
        "audience": "Researchers",
        "estimated_duration_minutes": 5,
        "core_narrative": "Evidence changes the decision.",
        "status": "reviewed",
        "authored_by": authored_by,
        "excluded_content": [],
        "known_gaps": [],
        "slides": [{
            "slide_id": "slide-01",
            "title": "Evidence changes the decision",
            "purpose": "State the result",
            "key_takeaway": "Evidence changes the decision.",
            "evidence_refs": ["paper:1"],
            "intended_visual_type": "native",
            "visual_rationale": "A simple flow clarifies the result.",
            "speaker_message": "The evidence is actionable.",
            "dependencies": [],
            "open_questions": [],
        }],
    }


def _registered_plan(tmp_path: Path, authored_by: str = "planner-a") -> tuple[Path, str, Path]:
    """Create a deck and persist one plan record for gate tests."""
    project = _project(tmp_path)
    deck = create_deck(project, "Test deck", created_by=authored_by)
    source = project / "plan.yaml"
    source.write_text(yaml.safe_dump(_plan(deck["id"], authored_by)), encoding="utf-8")
    digest = contract_sha256(yaml.safe_load(source.read_text(encoding="utf-8")))
    register_plan_record(project, deck["id"], "plan.yaml", digest, authored_by)
    return project, deck["id"], source


def _approval(project: Path, deck_id: str, plan_path: Path, approved_by: str = "reviewer-b") -> dict:
    """Build an approval document bound to the registered plan."""
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": plan["plan_version"],
        "plan_sha256": contract_sha256(plan),
        "decision": "approve",
        "approved_by": approved_by,
        "approved_at": "2026-08-08T00:00:00Z",
        "approval_mode": "interactive",
        "revisions_requested": [],
    }


def test_approval_requires_independent_passing_review(tmp_path: Path) -> None:
    """Reject plan approval when the reviewer is the planner."""
    project, deck_id, plan_path = _registered_plan(tmp_path)
    record_review(project, "deck", deck_id, "planner-a", "content", "passed")
    with pytest.raises(ApprovalGateError, match="reviewer must differ"):
        assert_plan_approvable(project, _approval(project, deck_id, plan_path))


def test_unsupported_claim_blocks_approval(tmp_path: Path) -> None:
    """Reject approval when the current content review has an unsupported claim."""
    project, deck_id, plan_path = _registered_plan(tmp_path)
    record_review(
        project,
        "deck",
        deck_id,
        "reviewer-b",
        "content",
        "failed",
        findings=[{"code": "unsupported-claim", "message": "Unsupported claim"}],
    )
    with pytest.raises(ApprovalGateError, match="unsupported-claim"):
        assert_plan_approvable(project, _approval(project, deck_id, plan_path))


def test_completion_requires_both_review_roles_and_final_pptx_gates(tmp_path: Path) -> None:
    """Reject completion when one required final review is absent."""
    project = _project(tmp_path)
    deck = create_deck(project, "Test deck")
    set_deck_status(project, deck["id"], "content_review")
    set_deck_status(project, deck["id"], "awaiting_approval")
    state_path = project / ".research/presentations/state/decks.yaml"
    document = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    document["decks"][deck["id"]]["status"] = "validating"
    state_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(CompletionGateError, match="visual_quality"):
        assert_deck_completable(
            project,
            deck["id"],
            {
                "scientific": "passed",
                "visual_quality": "passed",
                "pptx_structure": "passed",
                "pptx_render": "passed",
                "completion_allowed": True,
            },
        )


def test_generic_status_cli_cannot_bypass_approval_or_completion(tmp_path: Path) -> None:
    """Require evidence documents for gated generic status transitions."""
    project = _project(tmp_path)
    deck = create_deck(project, "Test deck")
    set_deck_status(project, deck["id"], "content_review")
    set_deck_status(project, deck["id"], "awaiting_approval")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--set-deck-status", "--deck-id", deck["id"],
         "--status", "approved", "--json"],
        cwd=project, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    error = json.loads(result.stdout)
    assert error["error"] == "ApprovalGateError"
    assert set(("error", "predicate", "deck_id", "blockers")) <= set(error)
