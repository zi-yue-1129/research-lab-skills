"""Behavioral tests for atomic report-slides workflow actions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_events import create_artifact_record, load_revision_requests
from presentation_state import create_deck, create_slide, create_visual_module, load_decks, load_slides, load_visual_modules, record_review, set_module_status, set_slide_status
from presentation_workflow import (
    ApprovalGateError,
    CompletionGateError,
    DraftGateError,
    approve_deck,
    approve_draft,
    complete_deck,
    record_content_review,
    record_production_review,
    register_draft_preview,
    register_plan,
    request_targeted_revision,
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
        "preview_sha256": registered["preview"]["preview_sha256"],
        "decision": "approve", "approved_by": "user",
    }), encoding="utf-8")
    approve_draft(project, decision)
    visual_review = _materialize_visual_review(project, deck_id)
    for relative in ("deck/final.pptx", "renders/source/slide-1.png", "renders/pptx/slide-1.png"):
        path = project / relative
        create_artifact_record(
            project, deck_id, "completion", relative,
            hashlib.sha256(path.read_bytes()).hexdigest(), "reviewer",
            slide_id=slide["id"] if relative.endswith(".png") else None,
        )
    completion = project / "completion.yaml"
    completion.write_text(yaml.safe_dump({"visual_review_path": str(visual_review.relative_to(project))}), encoding="utf-8")
    complete_deck(project, deck_id, completion)
    assert load_decks(project)[deck_id]["status"] == "completed"


def _passing_visual_review(deck_id: str) -> dict:
    """Build the complete visual-review contract expected at completion."""
    source_png = "renders/source/slide-1.png"
    rendered_png = "renders/pptx/slide-1.png"
    return {
        "schema_version": 1,
        "deck_id": deck_id,
        "output_format": "pptx",
        "expected_slides": [1],
        "source_artifacts": ["slides/slide-1.svg", source_png],
        "artifacts": {"pptx": "deck/final.pptx", "review_record": "visual-review.json"},
        "statuses": {
            "svg_preview": {
                "status": "passed", "round": 1, "reviewed_by": "model_vision",
                "inspected_paths": [source_png], "findings": [], "revision_required": False,
                "started_at": "2026-08-08T00:00:00Z", "completed_at": "2026-08-08T00:00:00Z",
            },
            "pptx_structure": {
                "status": "passed", "round": 1, "reviewed_by": "model_vision",
                "inspected_paths": ["deck/final.pptx"], "findings": [], "revision_required": False,
                "started_at": "2026-08-08T00:00:00Z", "completed_at": "2026-08-08T00:00:00Z",
            },
            "pptx_render": {
                "status": "passed", "round": 1, "reviewed_by": "model_vision",
                "inspected_paths": [rendered_png], "findings": [], "revision_required": False,
                "started_at": "2026-08-08T00:00:00Z", "completed_at": "2026-08-08T00:00:00Z",
                "renderer": {"name": "LibreOffice", "version": "25", "conversion_format": "pdf-to-png"},
                "conversion_artifacts": ["renders/pptx/final.pdf"],
                "rendered_png_paths": [rendered_png],
                "model_vision": {"inspected_paths": [rendered_png], "comparison_reference_paths": [source_png]},
                "visual_checks": {"clipping": "passed"},
            },
        },
        "overall": {"status": "passed", "completion_allowed": True, "authority": "pptx-render"},
        "history": [{"round": 1, "result": "passed", "revision": "Final review"}],
    }


def _materialize_visual_review(project: Path, deck_id: str) -> Path:
    """Persist a valid review record and the files it names."""
    from PIL import Image

    record = _passing_visual_review(deck_id)
    for relative in (
        "slides/slide-1.svg", "deck/final.pptx", "visual-review.json",
        "renders/pptx/final.pdf",
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")
    for relative in ("renders/source/slide-1.png", "renders/pptx/slide-1.png"):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 20), (20, 80, 120)).save(path)
    path = project / "visual-review.json"
    record["artifact_digests"] = {
        "deck/final.pptx": hashlib.sha256(b"artifact").hexdigest(),
        "renders/source/slide-1.png": hashlib.sha256((project / "renders/source/slide-1.png").read_bytes()).hexdigest(),
        "renders/pptx/slide-1.png": hashlib.sha256((project / "renders/pptx/slide-1.png").read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_completion_rejects_status_stubs_and_requires_visual_review_record(tmp_path: Path) -> None:
    """Caller-authored status strings cannot substitute for final evidence."""
    project, deck_id, _ = _approved_project(tmp_path)
    completion = project / "completion.yaml"
    completion.write_text(yaml.safe_dump({
        "statuses": {"svg_preview": "passed", "pptx_structure": "passed", "pptx_render": "passed"},
        "overall": {"completion_allowed": True},
    }), encoding="utf-8")
    with pytest.raises(CompletionGateError):
        complete_deck(project, deck_id, completion)


def _complete_fixture(tmp_path: Path) -> tuple[Path, str, Path, Path, str, dict]:
    """Materialize a deck that demonstrably completes before mutation tests."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    record_review(project, "slide", slide["id"], "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", slide["id"], "visual-reviewer", "visual_quality", "passed")
    set_slide_status(project, slide["id"], "passed")
    module = create_visual_module(project, slide["id"], "module-a", "architecture")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_module_status(project, module["id"], status)
    record_review(project, "module", module["id"], "scientific-reviewer", "scientific", "passed")
    record_review(project, "module", module["id"], "visual-reviewer", "visual_quality", "passed")
    set_module_status(project, module["id"], "passed")
    state_path = project / ".research/presentations/state/decks.yaml"
    state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_doc["decks"][deck_id]["status"] = "draft_review"
    state_path.write_text(yaml.safe_dump(state_doc), encoding="utf-8")
    from PIL import Image
    for path in (project / "renders/slide-1.png", project / "renders/contact.png"):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 20), (1, 2, 3)).save(path)
    preview = project / "preview.yaml"
    preview.write_text(yaml.safe_dump({
        "deck_id": deck_id, "rendered_slide_paths": [{"slide_id": "slide-01", "path": "renders/slide-1.png"}],
        "contact_sheet_path": "renders/contact.png", "slides": [{"slide_id": "slide-01", "title": "Evidence changes decisions", "key_takeaway": "Evidence changes decisions."}],
    }), encoding="utf-8")
    registered = register_draft_preview(project, preview)
    decision = project / "decision.yaml"
    decision.write_text(yaml.safe_dump({
        "deck_id": deck_id, "preview_id": registered["preview"]["id"], "preview_sha256": registered["preview"]["preview_sha256"],
        "decision": "approve", "approved_by": "reviewer",
    }), encoding="utf-8")
    approve_draft(project, decision)
    visual_review = _materialize_visual_review(project, deck_id)
    for relative in ("deck/final.pptx", "renders/source/slide-1.png", "renders/pptx/slide-1.png"):
        path = project / relative
        create_artifact_record(
            project, deck_id, "completion", relative,
            hashlib.sha256(path.read_bytes()).hexdigest(), "reviewer",
            slide_id=slide["id"] if relative.endswith(".png") else None,
        )
    # The remaining workflow preparation is deliberately explicit: no status stub is accepted.
    completion = project / "completion.yaml"
    completion.write_text(yaml.safe_dump({"visual_review_path": str(visual_review.relative_to(project))}), encoding="utf-8")
    complete_deck(project, deck_id, completion)
    return project, deck_id, visual_review, completion, slide["id"], module


def test_completion_fixture_succeeds_before_each_required_evidence_mutation(tmp_path: Path) -> None:
    """A complete current-record fixture proves the completion path is live."""
    project, deck_id, visual_review, _, _, _ = _complete_fixture(tmp_path)
    assert load_decks(project)[deck_id]["status"] == "completed"
    assert visual_review.is_file()


def test_completion_rejects_one_removed_or_mutated_current_record(tmp_path: Path) -> None:
    """Removing one persisted final record or digest blocks completion by name."""
    project, deck_id, visual_review, completion, slide_id, _ = _complete_fixture(tmp_path)
    # Restore validating status to replay the gate against mutations.
    deck_path = project / ".research/presentations/state/decks.yaml"
    deck_doc = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    deck_doc["decks"][deck_id]["status"] = "validating"
    deck_path.write_text(yaml.safe_dump(deck_doc), encoding="utf-8")
    visual_review.unlink()
    with pytest.raises(CompletionGateError):
        complete_deck(project, deck_id, completion)


def test_completion_rejects_mutated_rendered_png_digest(tmp_path: Path) -> None:
    """Replacing one inspected PNG fails its persisted artifact digest gate."""
    project, deck_id, _, completion, _, _ = _complete_fixture(tmp_path)
    deck_path = project / ".research/presentations/state/decks.yaml"
    deck_doc = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    deck_doc["decks"][deck_id]["status"] = "validating"
    deck_path.write_text(yaml.safe_dump(deck_doc), encoding="utf-8")
    (project / "renders/pptx/slide-1.png").write_bytes(b"replaced")
    with pytest.raises(CompletionGateError, match="artifact_digest_mismatch"):
        complete_deck(project, deck_id, completion)


def test_completion_requires_pptx_visual_review_output_format(tmp_path: Path) -> None:
    """A source-only visual review with not-applicable PPTX gates cannot complete."""
    project, deck_id, visual_review, completion, _, _ = _complete_fixture(tmp_path)
    deck_path = project / ".research/presentations/state/decks.yaml"
    deck_doc = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    deck_doc["decks"][deck_id]["status"] = "validating"
    deck_path.write_text(yaml.safe_dump(deck_doc), encoding="utf-8")
    record = json.loads(visual_review.read_text(encoding="utf-8"))
    record["output_format"] = "svg"
    record["artifacts"]["pptx"] = None
    record["statuses"]["pptx_structure"] = dict(record["statuses"]["pptx_structure"], status="not_applicable", reason="PPTX omitted", reviewed_by="workflow", inspected_paths=[])
    record["statuses"]["pptx_render"] = dict(record["statuses"]["pptx_render"], status="not_applicable", reason="PPTX omitted", reviewed_by="workflow", inspected_paths=[])
    record["overall"] = {"status": "passed", "completion_allowed": True, "authority": "source-pixel"}
    visual_review.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(CompletionGateError, match="output_format_pptx"):
        complete_deck(project, deck_id, completion)


def test_completion_rejects_removed_png_artifact_record(tmp_path: Path) -> None:
    """Removing one persisted PNG artifact record blocks completion."""
    project, deck_id, _, completion, _, _ = _complete_fixture(tmp_path)
    deck_path = project / ".research/presentations/state/decks.yaml"
    deck_doc = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    deck_doc["decks"][deck_id]["status"] = "validating"
    deck_path.write_text(yaml.safe_dump(deck_doc), encoding="utf-8")
    artifacts_path = project / ".research/presentations/state/artifacts.yaml"
    artifacts = yaml.safe_load(artifacts_path.read_text(encoding="utf-8"))
    artifacts["artifacts"] = {
        key: value for key, value in artifacts["artifacts"].items()
        if value.get("path") != "renders/pptx/slide-1.png"
    }
    artifacts_path.write_text(yaml.safe_dump(artifacts), encoding="utf-8")
    with pytest.raises(CompletionGateError, match="missing_persisted_artifact"):
        complete_deck(project, deck_id, completion)


def test_content_review_is_bound_to_current_plan_and_new_plan_invalidates_old_review(tmp_path: Path) -> None:
    """A content review only applies to the exact immutable current plan."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck", created_by="planner-a")
    source = project / "plan.yaml"
    source.write_text(yaml.safe_dump(_plan(deck["id"])), encoding="utf-8")
    register_plan(project, deck["id"], source, "planner-a")
    review = project / "content.yaml"
    review.write_text(yaml.safe_dump({
        "deck_id": deck["id"], "reviewer_id": "reviewer-b", "reviewer_role": "content", "status": "passed", "findings": [],
    }), encoding="utf-8")
    event = record_content_review(project, deck["id"], review)
    assert event["current_plan_id"]
    assert event["current_plan_version"] == 1
    assert event["current_plan_sha256"] == contract_sha256(_plan(deck["id"]))

    second = copy.deepcopy(_plan(deck["id"]))
    second["plan_version"] = 2
    second["purpose"] = "Explain the updated result"
    second_path = project / "plan-v2.yaml"
    second_path.write_text(yaml.safe_dump(second), encoding="utf-8")
    register_plan(project, deck["id"], second_path, "planner-a")
    approval = project / "approval.yaml"
    approval.write_text(yaml.safe_dump({
        "schema_version": 1, "deck_id": deck["id"], "plan_version": 2,
        "plan_sha256": contract_sha256(second), "decision": "approve", "approved_by": "reviewer-b",
        "approved_at": "2026-08-08T00:00:00Z", "approval_mode": "interactive", "revisions_requested": [],
    }), encoding="utf-8")
    with pytest.raises(ApprovalGateError):
        approve_deck(project, approval)


def test_draft_decision_requires_explicit_current_preview_identity(tmp_path: Path) -> None:
    """Missing decisions and stale preview IDs fail closed."""
    project, deck_id, _ = _approved_project(tmp_path)
    # We only need to prove the decision parser does not infer an approval.
    decision = project / "decision.yaml"
    decision.write_text(yaml.safe_dump({"deck_id": deck_id, "approved_by": "reviewer"}), encoding="utf-8")
    with pytest.raises(DraftGateError):
        approve_draft(project, decision)


def test_new_preview_clears_old_approval_and_stale_decision_cannot_apply(tmp_path: Path) -> None:
    """A replacement preview invalidates the prior approval identity and digest."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    record_review(project, "slide", slide["id"], "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", slide["id"], "visual-reviewer", "visual_quality", "passed")
    set_slide_status(project, slide["id"], "passed")
    state_path = project / ".research/presentations/state/decks.yaml"
    state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_doc["decks"][deck_id]["status"] = "draft_review"
    state_path.write_text(yaml.safe_dump(state_doc), encoding="utf-8")
    from PIL import Image
    for path in (project / "renders/slide.png", project / "renders/contact.png"):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (10, 10), (1, 2, 3)).save(path)
    preview = project / "preview.yaml"
    preview.write_text(yaml.safe_dump({
        "deck_id": deck_id, "rendered_slide_paths": [{"slide_id": "slide-01", "path": "renders/slide.png"}],
        "contact_sheet_path": "renders/contact.png", "slides": [{"slide_id": "slide-01", "title": "Evidence changes decisions", "key_takeaway": "Evidence changes decisions."}],
    }), encoding="utf-8")
    first = register_draft_preview(project, preview)
    first_decision = project / "first-decision.yaml"
    first_decision.write_text(yaml.safe_dump({
        "deck_id": deck_id, "preview_id": first["preview"]["id"], "preview_sha256": first["preview"]["preview_sha256"],
        "decision": "approve", "approved_by": "reviewer",
    }), encoding="utf-8")
    approve_draft(project, first_decision)
    # A new preview must clear the previous approval and require its exact digest.
    second = register_draft_preview(project, preview)
    assert load_decks(project)[deck_id]["draft_approval_id"] is None
    stale = project / "stale.yaml"
    stale.write_text(yaml.safe_dump({
        "deck_id": deck_id, "preview_id": first["preview"]["id"], "preview_sha256": first["preview"]["preview_sha256"],
        "decision": "approve", "approved_by": "reviewer",
    }), encoding="utf-8")
    with pytest.raises(DraftGateError):
        approve_draft(project, stale)
    assert second["preview"]["id"] != first["preview"]["id"]


def test_failed_production_review_links_revision_and_targeted_revision_supersedes_exact_source(tmp_path: Path) -> None:
    """Failed evidence creates a request; targeted revision supersedes only its source."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    review = project / "production.yaml"
    review.write_text(yaml.safe_dump({
        "subject_type": "slide", "subject_id": slide["id"], "reviewer_id": "visual-reviewer",
        "reviewer_role": "visual_quality", "status": "failed", "findings": [{"code": "overlap"}],
    }), encoding="utf-8")
    failed = record_production_review(project, review)
    requests = load_revision_requests(project)
    assert failed["revision_request"]["id"] in requests
    assert requests[failed["revision_request"]["id"]]["supersedes"] is None
    revision = project / "revision.yaml"
    revision.write_text(yaml.safe_dump({
        "subject_type": "slide", "subject_id": slide["id"], "requested_by": "reviewer",
        "instructions": "Fix overlap", "revision_kind": "revise_slide",
    }), encoding="utf-8")
    result = request_targeted_revision(project, revision)
    assert result["replacement"]["supersedes_slide_id"] == slide["id"]
    assert load_slides(project)[slide["id"]]["status"] == "superseded"
    assert load_slides(project)[result["replacement"]["id"]]["status"] == "planned"


def test_targeted_revision_supersedes_passed_module_without_restarting_it(tmp_path: Path) -> None:
    """A replacement preserves the passed source as superseded, never producing."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    module = create_visual_module(project, slide["id"], "module-a", "architecture")
    for status in ("ready", "assigned", "producing", "review_required", "passed"):
        set_module_status(project, module["id"], status)
    revision = project / "module-revision.yaml"
    revision.write_text(yaml.safe_dump({
        "subject_type": "module", "subject_id": module["id"], "requested_by": "reviewer",
        "instructions": "Retry the module.", "revision_kind": "module_retry",
    }), encoding="utf-8")
    result = request_targeted_revision(project, revision)
    records = load_visual_modules(project)
    assert records[module["id"]]["status"] == "superseded"
    assert records[result["replacement"]["id"]]["status"] == "planned"
