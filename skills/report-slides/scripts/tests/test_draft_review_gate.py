"""Tests for complete-deck draft preview registration and approval."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image

from presentation_contracts import contract_sha256
from presentation_events import create_artifact_record, load_events
from presentation_gates import DraftGateError
from presentation_state import (
    create_deck,
    create_slide,
    load_slides,
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


def _preview(
    project: Path,
    deck_id: str,
    plan: dict[str, Any],
    *,
    persist_contact: bool = True,
) -> tuple[Path, dict[str, Any]]:
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
    slide_record = next(
        record for record in load_slides(project).values()
        if record.get("deck_id") == deck_id
        and record.get("plan_slide_id") == "slide-01"
        and record.get("status") != "superseded"
    )
    create_artifact_record(
        project, deck_id, "slide-png", "renders/slide-01.png", slide_digest, "renderer",
        slide_id=slide_record["id"], plan_version=1, plan_sha256=contract_sha256(plan),
        slide_record_id=slide_record["id"], attempt=int(slide_record.get("attempt", 1)),
    )
    if persist_contact:
        create_artifact_record(
            project, deck_id, "review-sheet", "renders/contact-sheet.png", contact_digest, "renderer",
            plan_version=1, plan_sha256=contract_sha256(plan),
            source_paths=["renders/slide-01.png"], source_sha256=source_sha256,
        )
    preview: dict[str, Any] = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "plan_sha256": contract_sha256(plan),
        "rendered_slide_paths": [{
            "slide_id": "slide-01", "path": "renders/slide-01.png",
            "slide_record_id": slide_record["id"],
            "attempt": int(slide_record.get("attempt", 1)),
        }],
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
                "slide_record_id": slide_record["id"],
                "attempt": int(slide_record.get("attempt", 1)),
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


@pytest.mark.parametrize("fail_at", [1, 2])
def test_draft_approval_is_atomic_on_transaction_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
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
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(fail_at))

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
    approve_draft(project, decision_path, yes_draft=True)
    assert load_decks(project)[deck_id]["status"] == "validating"


def test_yes_draft_in_yaml_cannot_authorize_direct_api(tmp_path: Path) -> None:
    """Only the explicit API/CLI flag may authorize non-interactive approval."""
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
        "approval_mode": "explicit_noninteractive",
        "yes_draft": True,
    }), encoding="utf-8")

    with pytest.raises(DraftGateError, match="explicit --yes-draft"):
        approve_draft(project, decision_path)
    assert load_decks(project)[deck_id]["status"] == "draft_review"


def test_draft_decision_schema_version_rejects_bool(tmp_path: Path) -> None:
    """Draft decisions require integer schema version one, never boolean true."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    registered = register_draft_preview(project, preview_path)
    decision_path = project / "draft-decision.yaml"
    decision_path.write_text(yaml.safe_dump({
        "schema_version": True,
        "deck_id": deck_id,
        "preview_id": registered["preview"]["id"],
        "preview_sha256": registered["preview"]["preview_sha256"],
        "decision": "approve",
        "approval_mode": "interactive",
        "approved_by": "reviewer",
    }), encoding="utf-8")

    with pytest.raises(DraftGateError, match="schema_version"):
        approve_draft(project, decision_path)


def test_interactive_draft_identity_is_trimmed_before_persisting(tmp_path: Path) -> None:
    """Interactive approval records a canonical trimmed identity."""
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
        "approved_by": "  reviewer  ",
    }), encoding="utf-8")

    result = approve_draft(project, decision_path)

    assert result["decision"]["approved_by"] == "reviewer"


def test_preview_requires_current_generated_slide_record_binding(tmp_path: Path) -> None:
    """A plan-slide ID alone cannot bind a stale generated slide render."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["rendered_slide_paths"][0]["slide_record_id"] = "sld_stale"
    preview["rendered_slide_paths"][0]["attempt"] = 1
    preview["artifact_bindings"]["renders/slide-01.png"].update({
        "slide_record_id": "sld_stale", "attempt": 1,
    })
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="slide_record_id"):
        register_draft_preview(project, preview_path)


def test_preview_schema_version_rejects_boolean(tmp_path: Path) -> None:
    """Canonical preview schema version is an integer, never a YAML boolean."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["schema_version"] = True
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="schema_version_required"):
        register_draft_preview(project, preview_path)


def test_preview_requires_mapping_rendered_paths_without_aliases(tmp_path: Path) -> None:
    """Rendered paths and contact sheet use only canonical mapping fields."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["rendered_slide_paths"] = ["renders/slide-01.png"]
    preview["contact_sheet"] = preview.pop("contact_sheet_path")
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="rendered slide entry must be a mapping"):
        register_draft_preview(project, preview_path)


def test_preview_requires_rendered_entries_in_current_plan_order(tmp_path: Path) -> None:
    """Rendered metadata order must equal the current approved slide order."""
    from render_plan_preview import _normalize_rendered_paths

    project = _project(tmp_path)
    render_dir = project / "renders"
    render_dir.mkdir()
    for name in ("slide-01.png", "slide-02.png"):
        Image.new("RGB", (10, 10), (1, 2, 3)).save(render_dir / name)
    blockers: list[dict[str, Any]] = []
    _normalize_rendered_paths(
        project,
        [
            {"slide_id": "slide-02", "path": "renders/slide-02.png", "slide_record_id": "sld-2", "attempt": 1},
            {"slide_id": "slide-01", "path": "renders/slide-01.png", "slide_record_id": "sld-1", "attempt": 1},
        ],
        ["slide-01", "slide-02"],
        {},
        blockers,
    )

    assert any(blocker["reason"] == "rendered slide set order mismatch" for blocker in blockers)


def test_preview_rejects_legacy_aliases_and_ambiguous_metadata(tmp_path: Path) -> None:
    """Legacy field aliases cannot be upgraded into approval-grade evidence."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["rendered_slides"] = preview.pop("slides")
    preview["rendered_slides"][0]["takeaway"] = preview["rendered_slides"][0].pop("key_takeaway")
    preview["artifact_bindings"]["renders/contact-sheet.png"]["source_set_sha256"] = preview[
        "artifact_bindings"
    ]["renders/contact-sheet.png"].pop("source_sha256")
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError):
        register_draft_preview(project, preview_path)


def test_preview_rejects_uppercase_extra_png(tmp_path: Path) -> None:
    """The exact rendered set rejects extra PNG files regardless of case."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    (project / "renders/extra.PNG").write_bytes(b"extra")

    with pytest.raises(DraftGateError, match="extra rendered PNG"):
        register_draft_preview(project, preview_path)


def test_preview_rejects_symlink_escape(tmp_path: Path) -> None:
    """Rendered evidence may not resolve through a symlink outside the project."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    rendered = project / "renders/escape.png"
    rendered.symlink_to(outside)
    preview["rendered_slide_paths"][0]["path"] = "renders/escape.png"
    preview["artifact_digests"]["renders/escape.png"] = hashlib.sha256(outside.read_bytes()).hexdigest()
    preview["artifact_digests"].pop("renders/slide-01.png")
    preview["artifact_bindings"]["renders/escape.png"] = preview["artifact_bindings"].pop("renders/slide-01.png")
    preview["artifact_bindings"]["renders/escape.png"]["slide_id"] = "slide-01"
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="project-relative PNG"):
        register_draft_preview(project, preview_path)


def test_preview_requires_exactly_one_current_persisted_artifact_record(tmp_path: Path) -> None:
    """Every current slide and contact sheet must have one matching record."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan, persist_contact=False)

    with pytest.raises(DraftGateError, match="persisted_artifact"):
        register_draft_preview(project, preview_path)


def test_preview_rejects_ambiguous_persisted_artifact_records(tmp_path: Path) -> None:
    """Duplicate current artifact records fail closed rather than selecting one."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    slide_record = next(
        record for record in load_slides(project).values()
        if record.get("deck_id") == deck_id and record.get("plan_slide_id") == "slide-01"
        and record.get("status") != "superseded"
    )
    slide_digest = hashlib.sha256((project / "renders/slide-01.png").read_bytes()).hexdigest()
    contact_digest = hashlib.sha256((project / "renders/contact-sheet.png").read_bytes()).hexdigest()
    create_artifact_record(
        project, deck_id, "slide-png", "renders/slide-01.png", slide_digest, "renderer",
        slide_id=slide_record["id"], plan_version=1, plan_sha256=contract_sha256(plan),
        slide_record_id=slide_record["id"], attempt=int(slide_record.get("attempt", 1)),
    )
    create_artifact_record(
        project, deck_id, "review-sheet", "renders/contact-sheet.png", contact_digest, "renderer",
        plan_version=1, plan_sha256=contract_sha256(plan),
        source_paths=["renders/slide-01.png"],
        source_sha256=_canonical_source_digest(["renders/slide-01.png"], [slide_digest]),
    )

    with pytest.raises(DraftGateError, match="ambiguous_persisted_artifact"):
        register_draft_preview(project, preview_path)


def test_preview_rejects_boolean_plan_version(tmp_path: Path) -> None:
    """Preview plan versions require an exact positive integer."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["plan_version"] = True
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="plan_version"):
        register_draft_preview(project, preview_path)


def test_preview_rejects_extra_slide_metadata_fields(tmp_path: Path) -> None:
    """Slide metadata uses an exact canonical nested key set."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["slides"][0]["legacy_takeaway"] = preview["slides"][0]["key_takeaway"]
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="slide metadata"):
        register_draft_preview(project, preview_path)


def test_preview_rejects_extra_artifact_binding_fields(tmp_path: Path) -> None:
    """Artifact bindings use exact canonical fields without legacy aliases."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["artifact_bindings"]["renders/slide-01.png"]["producer"] = "renderer"
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")

    with pytest.raises(DraftGateError, match="artifact binding"):
        register_draft_preview(project, preview_path)


@pytest.mark.parametrize("identity", ["auto", "system", "agent", "unknown", "--yes-draft", "  "])
def test_interactive_draft_rejects_reserved_identity_placeholders(
    tmp_path: Path, identity: str
) -> None:
    """Interactive approvals require a real human reviewer identity."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    registered = register_draft_preview(project, preview_path)
    decision_path = project / "decision.yaml"
    decision_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "deck_id": deck_id,
        "preview_id": registered["preview"]["id"],
        "preview_sha256": registered["preview"]["preview_sha256"],
        "decision": "approve",
        "approval_mode": "interactive",
        "approved_by": identity,
    }), encoding="utf-8")

    with pytest.raises(DraftGateError, match="approved_by"):
        approve_draft(project, decision_path)


def test_draft_decision_rejects_unverifiable_identity_and_unknown_fields(tmp_path: Path) -> None:
    """Decision contracts reject unverifiable identities and ambiguous fields."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    registered = register_draft_preview(project, preview_path)
    decision_path = project / "decision.yaml"
    decision_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "deck_id": deck_id,
        "preview_id": registered["preview"]["id"],
        "preview_sha256": registered["preview"]["preview_sha256"],
        "decision": "approve",
        "approval_mode": "interactive",
        "approved_by": "reviewer",
        "identity_verifiable": False,
        "unexpected": "legacy",
    }), encoding="utf-8")

    with pytest.raises(DraftGateError, match="identity_verifiable|unexpected"):
        approve_draft(project, decision_path)


def test_invalid_contact_path_fails_before_recursive_extra_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid contact paths must not trigger recursive scans or outside reads."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["contact_sheet_path"] = str(tmp_path / "outside" / "sentinel.png")
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")
    import render_plan_preview as module

    scanned: list[bool] = []
    monkeypatch.setattr(module, "_check_extra_pngs", lambda *args: scanned.append(True))

    with pytest.raises(DraftGateError):
        register_draft_preview(project, preview_path)
    assert scanned == []


def test_invalid_rendered_path_fails_before_recursive_extra_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid rendered paths must fail before any directory traversal."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, preview = _preview(project, deck_id, plan)
    preview["rendered_slide_paths"][0]["path"] = str(tmp_path / "outside" / "sentinel.png")
    preview_path.write_text(yaml.safe_dump(preview), encoding="utf-8")
    import render_plan_preview as module

    scanned: list[bool] = []
    monkeypatch.setattr(module, "_check_extra_pngs", lambda *args: scanned.append(True))

    with pytest.raises(DraftGateError):
        register_draft_preview(project, preview_path)
    assert scanned == []


@pytest.mark.parametrize("fail_at", [1, 2])
def test_draft_reregistration_failure_restores_preview_and_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    """Every staged registration replacement restores exact pointers/events on failure."""
    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    first = register_draft_preview(project, preview_path)
    decision_path = project / "decision.yaml"
    decision_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "deck_id": deck_id,
        "preview_id": first["preview"]["id"],
        "preview_sha256": first["preview"]["preview_sha256"],
        "decision": "approve",
        "approved_by": "reviewer",
    }), encoding="utf-8")
    approve_draft(project, decision_path)
    before_deck = load_decks(project)[deck_id]
    before_events = load_events(project)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(fail_at))

    with pytest.raises(RuntimeError, match="injected transaction commit failure"):
        register_draft_preview(project, preview_path)

    assert load_decks(project)[deck_id] == before_deck
    assert load_events(project) == before_events
