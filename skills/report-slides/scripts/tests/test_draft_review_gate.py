"""Tests for complete-deck draft preview registration and approval."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image

from presentation_contracts import contract_sha256
from presentation_events import load_events
from presentation_gates import DraftGateError
from presentation_state import (
    create_deck,
    create_slide,
    load_decks,
    record_review,
    set_slide_status,
)
from presentation_workflow import (
    approve_deck,
    approve_draft,
    register_draft_preview,
    register_plan,
)
from render_review_sheet import compose_review_sheet
from render_plan_preview import _canonical_source_digest


def _project(tmp_path: Path) -> Path:
    """Create a temporary Git project for draft-gate tests."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _plan(deck_id: str) -> dict[str, Any]:
    """Return a strict reviewed one-slide plan."""
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


def _approved_project(tmp_path: Path) -> tuple[Path, str, dict[str, Any]]:
    """Create a deck with independent content approval and one passed slide."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck", created_by="planner-a")
    plan = _plan(deck["id"])
    plan_path = project / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    register_plan(project, deck["id"], plan_path, "planner-a")
    review_path = project / "content-review.yaml"
    review_path.write_text(yaml.safe_dump({
        "deck_id": deck["id"],
        "reviewer_id": "reviewer-b",
        "reviewer_role": "content",
        "status": "passed",
        "findings": [],
    }), encoding="utf-8")
    from presentation_workflow import record_content_review

    record_content_review(project, deck["id"], review_path)
    approval = {
        "schema_version": 1,
        "deck_id": deck["id"],
        "plan_version": 1,
        "plan_sha256": contract_sha256(plan),
        "decision": "approve",
        "approved_by": "reviewer-b",
        "approved_at": "2026-08-08T00:00:00Z",
        "approval_mode": "explicit_noninteractive",
        "revisions_requested": [],
    }
    approval_path = project / "approval.yaml"
    approval_path.write_text(yaml.safe_dump(approval), encoding="utf-8")
    approve_deck(project, approval_path)
    slide = create_slide(project, deck["id"], "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    record_review(project, "slide", slide["id"], "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", slide["id"], "visual-reviewer", "visual_quality", "passed")
    set_slide_status(project, slide["id"], "passed")
    deck_path = project / ".research/presentations/state/decks.yaml"
    state = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    state["decks"][deck["id"]]["status"] = "draft_review"
    deck_path.write_text(yaml.safe_dump(state), encoding="utf-8")
    return project, deck["id"], plan


def _preview(project: Path, deck_id: str, plan: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Create a current slide PNG/contact sheet and matching preview contract."""
    render_dir = project / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    slide_path = render_dir / "slide-01.png"
    contact_path = render_dir / "contact-sheet.png"
    Image.new("RGB", (40, 20), (12, 44, 88)).save(slide_path)
    compose_review_sheet([slide_path], contact_path, columns=1, cell_width=40, cell_height=20)
    slide_digest = hashlib.sha256(slide_path.read_bytes()).hexdigest()
    contact_digest = hashlib.sha256(contact_path.read_bytes()).hexdigest()
    source_sha256 = _canonical_source_digest(["renders/slide-01.png"], [slide_digest])
    preview: dict[str, Any] = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "plan_sha256": contract_sha256(plan),
        "rendered_slide_paths": [{"slide_id": "slide-01", "path": "renders/slide-01.png"}],
        "contact_sheet_path": "renders/contact-sheet.png",
        "slides": [{
            "slide_id": "slide-01",
            "title": plan["slides"][0]["title"],
            "key_takeaway": plan["slides"][0]["key_takeaway"],
        }],
        "artifact_digests": {
            "renders/slide-01.png": slide_digest,
            "renders/contact-sheet.png": contact_digest,
        },
        "artifact_bindings": {
            "renders/slide-01.png": {
                "slide_id": "slide-01", "kind": "rendered_slide", "deck_id": deck_id,
                "plan_version": 1, "plan_sha256": contract_sha256(plan), "producer_id": "renderer",
            },
            "renders/contact-sheet.png": {
                "deck_id": deck_id, "kind": "contact_sheet", "source_paths": ["renders/slide-01.png"],
                "source_sha256": source_sha256, "plan_version": 1,
                "plan_sha256": contract_sha256(plan), "producer_id": "renderer",
            },
        },
    }
    path = project / "draft-preview.yaml"
    path.write_text(yaml.safe_dump(preview), encoding="utf-8")
    return path, preview


def test_draft_preview_requires_every_rendered_slide(tmp_path: Path) -> None:
    """Removing one current slide from the preview fails closed."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["rendered_slide_paths"].pop()
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="rendered slide set"):
        register_draft_preview(project, preview_path)

    assert load_decks(project)[deck_id]["draft_preview_id"] is None


def test_draft_preview_requires_canonical_contract_metadata(tmp_path: Path) -> None:
    """A legacy preview without schema, digests, or bindings cannot pass."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    for field in ("schema_version", "plan_version", "plan_sha256", "artifact_digests", "artifact_bindings"):
        preview.pop(field, None)
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="schema_version_required"):
        register_draft_preview(project, preview_path)
    assert load_decks(project)[deck_id]["draft_preview_id"] is None


def test_draft_preview_rejects_stale_or_tampered_artifacts(tmp_path: Path) -> None:
    """A changed PNG or an extra PNG cannot be registered as current evidence."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    (project / "renders/extra.png").write_bytes(b"not-current")
    with pytest.raises(DraftGateError):
        register_draft_preview(project, preview_path)
    assert load_decks(project)[deck_id]["draft_preview_id"] is None
    (project / "renders/extra.png").unlink()
    (project / "renders/slide-01.png").write_bytes(b"tampered")
    with pytest.raises(DraftGateError, match="digest"):
        register_draft_preview(project, preview_path)
    assert load_decks(project)[deck_id]["draft_preview_id"] is None


def test_draft_preview_rejects_title_or_contact_source_mismatch(tmp_path: Path) -> None:
    """Title/takeaway and contact source bindings remain plan- and order-bound."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["slides"][0]["title"] = "A stale title"
    preview["artifact_bindings"]["renders/contact-sheet.png"]["source_paths"] = ["renders/other.png"]
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="preview title/takeaway mismatch"):
        register_draft_preview(project, preview_path)
    assert load_decks(project)[deck_id]["draft_preview_id"] is None


def test_draft_registration_is_atomic_on_transaction_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit failure leaves no draft event or mutable approval pointer."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", "2")

    with pytest.raises(RuntimeError, match="injected transaction commit failure"):
        register_draft_preview(project, preview_path)

    assert load_decks(project)[deck_id]["draft_preview_id"] is None
    assert not [event for event in load_events(project, "draft_preview") if event.get("deck_id") == deck_id]


def test_draft_approval_is_atomic_on_transaction_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed draft-decision commit leaves status, pointer, and event history unchanged."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    registered = register_draft_preview(project, preview_path)
    decision_path = project / "draft-decision.yaml"
    decision_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "deck_id": deck_id,
        "preview_id": registered["preview"]["id"],
        "preview_sha256": registered["preview"]["preview_sha256"],
        "decision": "approve",
        "approval_mode": "interactive",
        "approved_by": "reviewer",
    }), encoding="utf-8")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", "2")

    with pytest.raises(RuntimeError, match="injected transaction commit failure"):
        approve_draft(project, decision_path)

    deck = load_decks(project)[deck_id]
    assert deck["status"] == "draft_review"
    assert deck["draft_approval_id"] is None
    assert not [event for event in load_events(project, "draft_decision") if event.get("deck_id") == deck_id]

def test_initial_yes_does_not_approve_draft(tmp_path: Path) -> None:
    """Plan approval mode never creates a draft decision implicitly."""
    project, deck_id, _ = _approved_project(tmp_path)

    assert load_decks(project)[deck_id]["draft_approval_id"] is None


def test_draft_approval_requires_identity_or_explicit_noninteractive_flag(tmp_path: Path) -> None:
    """Draft approval cannot infer a user identity and advances only after registration."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    registered = register_draft_preview(project, preview_path)
    decision_path = project / "draft-decision.yaml"
    decision_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "deck_id": deck_id,
        "preview_id": registered["preview"]["id"],
        "preview_sha256": registered["preview"]["preview_sha256"],
        "decision": "approve",
        "approval_mode": "interactive",
    }), encoding="utf-8")
    with pytest.raises(DraftGateError, match="approved_by"):
        approve_draft(project, decision_path)
    assert load_decks(project)[deck_id]["status"] == "draft_review"

    decision_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "deck_id": deck_id,
        "preview_id": registered["preview"]["id"],
        "preview_sha256": registered["preview"]["preview_sha256"],
        "decision": "approve",
        "approval_mode": "explicit_noninteractive",
        "yes_draft": True,
    }), encoding="utf-8")
    approve_draft(project, decision_path)
    assert load_decks(project)[deck_id]["status"] == "validating"
