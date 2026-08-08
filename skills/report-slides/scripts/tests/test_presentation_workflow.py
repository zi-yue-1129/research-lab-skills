"""Behavioral tests for atomic report-slides workflow actions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_state import create_deck, create_slide, load_decks, record_review
from presentation_workflow import (
    ApprovalGateError,
    approve_deck,
    approve_draft,
    complete_deck,
    record_content_review,
    register_draft_preview,
    register_plan,
)


def test_workflow_actions_are_not_available_before_implementation() -> None:
    """The RED test suite intentionally imports the Task 4 API."""
    assert Path("presentation_workflow.py").exists()


def test_approval_action_requires_an_evidence_document(tmp_path: Path) -> None:
    """An approval action fails closed when its source is missing."""
    with pytest.raises((ApprovalGateError, FileNotFoundError)):
        approve_deck(tmp_path, tmp_path / "missing-approval.yaml")


def _project(tmp_path: Path) -> Path:
    """Create a temporary Git project for workflow action tests."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _plan(deck_id: str) -> dict:
    """Return the smallest strict reviewed plan used by action tests."""
    return {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "purpose": "Explain the result",
        "audience": "Researchers",
        "estimated_duration_minutes": 5,
        "core_narrative": "Evidence changes decisions.",
        "status": "reviewed",
        "authored_by": "planner-a",
        "excluded_content": [],
        "known_gaps": [],
        "slides": [{
            "slide_id": "slide-01",
            "title": "Evidence changes decisions",
            "purpose": "State the result",
            "key_takeaway": "Evidence changes decisions.",
            "evidence_refs": ["paper:1"],
            "intended_visual_type": "native",
            "visual_rationale": "A flow makes the result clear.",
            "speaker_message": "The result is actionable.",
            "dependencies": [],
            "open_questions": [],
        }],
    }


def _approved_project(tmp_path: Path) -> tuple[Path, str, dict]:
    """Register a plan, record independent content review, and approve it."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck", created_by="planner-a")
    plan = _plan(deck["id"])
    source = project / "source-plan.yaml"
    source.write_text(yaml.safe_dump(plan), encoding="utf-8")
    register_plan(project, deck["id"], source, "planner-a")
    review = project / "content-review.yaml"
    review.write_text(yaml.safe_dump({
        "deck_id": deck["id"], "reviewer_id": "reviewer-b",
        "reviewer_role": "content", "status": "passed", "findings": [],
    }), encoding="utf-8")
    record_content_review(project, deck["id"], review)
    approval = project / "approval.yaml"
    approval_doc = {
        "schema_version": 1, "deck_id": deck["id"], "plan_version": 1,
        "plan_sha256": contract_sha256(plan), "decision": "approve",
        "approved_by": "reviewer-b", "approved_at": "2026-08-08T00:00:00Z",
        "approval_mode": "interactive", "revisions_requested": [],
    }
    approval.write_text(yaml.safe_dump(approval_doc), encoding="utf-8")
    approve_deck(project, approval)
    return project, deck["id"], plan


def test_approval_copies_plan_and_persists_digest_bound_state(tmp_path: Path) -> None:
    """Approval records the exact version and immutable destination copy."""
    project, deck_id, plan = _approved_project(tmp_path)
    deck = load_decks(project)[deck_id]
    copied = project / "decks" / deck_id / "plans" / "plan-v0001.yaml"
    assert copied.is_file()
    assert deck["status"] == "approved"
    assert deck["approved_plan_version"] == 1
    assert deck["approved_plan_sha256"] == contract_sha256(plan)
    assert (project / ".research/presentations/state/workflow.lock").is_file()


def test_draft_and_completion_actions_require_persisted_current_evidence(tmp_path: Path) -> None:
    """Draft approval advances only after preview and final gates are present."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    slide_path = project / "renders" / "slide-01.png"
    contact_path = project / "renders" / "contact.png"
    slide_path.parent.mkdir(parents=True, exist_ok=True)
    slide_path.write_bytes(b"png")
    contact_path.write_bytes(b"png")
    state_path = project / ".research/presentations/state/decks.yaml"
    state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_doc["decks"][deck_id]["status"] = "draft_review"
    state_doc["decks"][deck_id]["approved_plan_version"] = 1
    state_doc["decks"][deck_id]["approved_plan_sha256"] = contract_sha256(_plan(deck_id))
    state_doc["decks"][deck_id]["approval_id"] = "approval-test"
    state_path.write_text(yaml.safe_dump(state_doc), encoding="utf-8")
    slide_state = project / ".research/presentations/state/slides.yaml"
    slide_doc = yaml.safe_load(slide_state.read_text(encoding="utf-8"))
    slide_doc["slides"][slide["id"]]["status"] = "passed"
    slide_state.write_text(yaml.safe_dump(slide_doc), encoding="utf-8")
    record_review(project, "slide", slide["id"], "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", slide["id"], "visual-reviewer", "visual_quality", "passed")
    preview = project / "preview.yaml"
    preview.write_text(yaml.safe_dump({
        "deck_id": deck_id,
        "rendered_slide_paths": [{"slide_id": "slide-01", "path": "renders/slide-01.png"}],
        "contact_sheet_path": "renders/contact.png",
        "slides": [{"slide_id": "slide-01", "title": "Evidence changes decisions", "key_takeaway": "Evidence changes decisions."}],
    }), encoding="utf-8")
    registered = register_draft_preview(project, preview)
    decision = project / "decision.yaml"
    decision.write_text(yaml.safe_dump({
        "deck_id": deck_id, "preview_id": registered["preview"]["id"],
        "decision": "approve", "approved_by": "user",
    }), encoding="utf-8")
    approve_draft(project, decision)
    completion = project / "completion.yaml"
    completion.write_text(yaml.safe_dump({
        "statuses": {
            "svg_preview": {"status": "passed"},
            "pptx_structure": {"status": "passed"},
            "pptx_render": {"status": "passed"},
        },
        "overall": {"completion_allowed": True},
    }), encoding="utf-8")
    complete_deck(project, deck_id, completion)
    assert load_decks(project)[deck_id]["status"] == "completed"
