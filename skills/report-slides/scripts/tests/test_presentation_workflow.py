"""Behavioral tests for atomic report-slides workflow actions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_evidence_contracts import EvidenceContractError, validate_store_record
from presentation_events import (
    create_artifact_record,
    load_events,
    load_plans,
    load_revision_requests,
)
from presentation_events import create_assignment_record
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
from render_plan_preview import _canonical_source_digest
from render_review_sheet import compose_review_sheet


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


def _write_draft_preview(
    project: Path,
    deck_id: str,
    slide_path: Path,
    contact_path: Path,
) -> Path:
    """Write a strict draft-preview contract bound to rendered PNG evidence."""
    plan_path = project / "decks" / deck_id / "plans" / "plan-v0001.yaml"
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    slide_relative = slide_path.relative_to(project).as_posix()
    contact_relative = contact_path.relative_to(project).as_posix()
    compose_review_sheet([slide_path], contact_path, columns=1, cell_width=40, cell_height=20)
    slide_digest = hashlib.sha256(slide_path.read_bytes()).hexdigest()
    contact_digest = hashlib.sha256(contact_path.read_bytes()).hexdigest()
    slide_record = next(
        record for record in load_slides(project).values()
        if record.get("deck_id") == deck_id
        and record.get("plan_slide_id") == "slide-01"
        and record.get("status") != "superseded"
    )
    source_sha256 = _canonical_source_digest([slide_relative], [slide_digest])
    create_artifact_record(
        project, deck_id, "slide-png", slide_relative, slide_digest, "renderer",
        slide_id=slide_record["id"], plan_version=plan["plan_version"],
        plan_sha256=contract_sha256(plan), slide_record_id=slide_record["id"],
        attempt=int(slide_record.get("attempt", 1)),
    )
    create_artifact_record(
        project, deck_id, "review-sheet", contact_relative, contact_digest, "renderer",
        plan_version=plan["plan_version"], plan_sha256=contract_sha256(plan),
        source_paths=[slide_relative], source_sha256=source_sha256,
    )
    document = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": plan["plan_version"],
        "plan_sha256": contract_sha256(plan),
        "rendered_slide_paths": [{
            "slide_id": "slide-01", "path": slide_relative,
            "slide_record_id": slide_record["id"],
            "attempt": int(slide_record.get("attempt", 1)),
        }],
        "contact_sheet_path": contact_relative,
        "slides": [{
            "slide_id": "slide-01",
            "title": plan["slides"][0]["title"],
            "key_takeaway": plan["slides"][0]["key_takeaway"],
        }],
        "artifact_digests": {slide_relative: slide_digest, contact_relative: contact_digest},
        "artifact_bindings": {
            slide_relative: {
                "kind": "rendered_slide", "deck_id": deck_id, "slide_id": "slide-01",
                "plan_version": plan["plan_version"], "plan_sha256": contract_sha256(plan),
                "producer_id": "renderer",
                "slide_record_id": slide_record["id"],
                "attempt": int(slide_record.get("attempt", 1)),
            },
            contact_relative: {
                "kind": "contact_sheet", "deck_id": deck_id,
                "plan_version": plan["plan_version"], "plan_sha256": contract_sha256(plan),
                "producer_id": "renderer", "source_paths": [slide_relative],
                "source_sha256": source_sha256,
            },
        },
    }
    preview = project / "preview.yaml"
    preview.write_text(yaml.safe_dump(document), encoding="utf-8")
    return preview


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
    from PIL import Image
    Image.new("RGB", (20, 20), (1, 2, 3)).save(slide_path)
    Image.new("RGB", (20, 20), (1, 2, 3)).save(contact_path)
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
    preview = _write_draft_preview(
        project,
        deck_id,
        project / "renders/slide-01.png",
        project / "renders/contact.png",
    )
    registered = register_draft_preview(project, preview)
    decision = project / "decision.yaml"
    decision.write_text(yaml.safe_dump({
        "schema_version": 1,
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
    preview = _write_draft_preview(
        project,
        deck_id,
        project / "renders/slide-1.png",
        project / "renders/contact.png",
    )
    registered = register_draft_preview(project, preview)
    decision = project / "decision.yaml"
    decision.write_text(yaml.safe_dump({
        "schema_version": 1,
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


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_register_plan_failure_restores_plan_destination_and_all_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    """Every register-plan commit position restores exact replacement preimages."""
    project, deck_id, _ = _approved_project(tmp_path)
    second = copy.deepcopy(_plan(deck_id))
    second["plan_version"] = 2
    second["purpose"] = "Explain the updated result"
    source = project / "plan-v2.yaml"
    source.write_text(yaml.safe_dump(second), encoding="utf-8")
    state_dir = project / ".research/presentations/state"
    destination = project / "decks" / deck_id / "plans" / "plan-v0002.yaml"
    tracked = [destination, state_dir / "plans.yaml", state_dir / "decks.yaml"]
    before = {path: _file_preimage(path) for path in tracked}
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(fail_at))

    with pytest.raises(RuntimeError, match="injected transaction commit failure"):
        register_plan(project, deck_id, source, "planner-a")

    assert {path: _file_preimage(path) for path in tracked} == before
    assert load_plans(project)
    assert load_events(project)
    assert load_decks(project)[deck_id]["draft_preview_id"] is None


def test_register_plan_replacement_clears_approval_and_draft_pointers_atomically(
    tmp_path: Path,
) -> None:
    """A successful replacement enters planning with no stale approval evidence."""
    project, deck_id, _ = _approved_project(tmp_path)
    decks_path = project / ".research/presentations/state/decks.yaml"
    decks = yaml.safe_load(decks_path.read_text(encoding="utf-8"))
    decks["decks"][deck_id].update({
        "draft_preview_id": "preview-old",
        "draft_approval_id": "approval-old",
        "status": "validating",
    })
    decks_path.write_text(yaml.safe_dump(decks), encoding="utf-8")
    second = copy.deepcopy(_plan(deck_id))
    second["plan_version"] = 2
    second["purpose"] = "Explain the updated result"
    source = project / "plan-v2.yaml"
    source.write_text(yaml.safe_dump(second), encoding="utf-8")

    register_plan(project, deck_id, source, "planner-a")

    deck = load_decks(project)[deck_id]
    assert deck["status"] == "planning"
    assert deck["draft_preview_id"] is None
    assert deck["draft_approval_id"] is None
    assert deck["approval_id"] is None
    assert deck["approved_plan_version"] is None


def test_register_plan_rejects_existing_immutable_destination_without_state_change(
    tmp_path: Path,
) -> None:
    """An existing immutable copy cannot be overwritten by registration."""
    project, deck_id, _ = _approved_project(tmp_path)
    second = copy.deepcopy(_plan(deck_id))
    second["plan_version"] = 2
    source = project / "plan-v2.yaml"
    source.write_text(yaml.safe_dump(second), encoding="utf-8")
    destination = project / "decks" / deck_id / "plans" / "plan-v0002.yaml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"old-plan-copy")
    destination.chmod(0o640)
    before = _file_preimage(destination)
    before_state = {
        path: _file_preimage(path)
        for path in (
            project / ".research/presentations/state/decks.yaml",
            project / ".research/presentations/state/plans.yaml",
        )
    }
    with pytest.raises(ValueError, match="immutable|exists|overwrite"):
        register_plan(project, deck_id, source, "planner-a")

    assert _file_preimage(destination) == before
    assert {path: _file_preimage(path) for path in before_state} == before_state


def test_register_plan_new_failure_keeps_stable_sidecar_and_restores_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed first registration leaves its stable sidecar for future waiters."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck", created_by="planner-a")
    source = project / "plan.yaml"
    source.write_text(yaml.safe_dump(_plan(deck["id"])), encoding="utf-8")
    destination = project / "decks" / deck["id"] / "plans" / "plan-v0001.yaml"
    state_dir = project / ".research/presentations/state"
    before = {
        state_dir / "decks.yaml": _file_preimage(state_dir / "decks.yaml"),
        state_dir / "plans.yaml": _file_preimage(state_dir / "plans.yaml"),
    }
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", "3")

    with pytest.raises(RuntimeError, match="injected transaction commit failure"):
        register_plan(project, deck["id"], source, "planner-a")

    assert _file_preimage(destination) == (False, b"", 0)
    sidecar = destination.with_suffix(destination.suffix + ".lock")
    assert sidecar.is_file()
    assert destination.parent.exists()
    assert {path: _file_preimage(path) for path in before} == before


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
    preview = _write_draft_preview(
        project,
        deck_id,
        project / "renders/slide.png",
        project / "renders/contact.png",
    )
    first = register_draft_preview(project, preview)
    first_decision = project / "first-decision.yaml"
    first_decision.write_text(yaml.safe_dump({
        "schema_version": 1,
        "deck_id": deck_id, "preview_id": first["preview"]["id"], "preview_sha256": first["preview"]["preview_sha256"],
        "decision": "approve", "approved_by": "reviewer",
    }), encoding="utf-8")
    approve_draft(project, first_decision)
    # A new preview must clear the previous approval and require its exact digest.
    second = register_draft_preview(project, preview)
    assert load_decks(project)[deck_id]["draft_approval_id"] is None
    assert load_decks(project)[deck_id]["status"] == "draft_review"
    stale = project / "stale.yaml"
    stale.write_text(yaml.safe_dump({
        "schema_version": 1,
        "deck_id": deck_id, "preview_id": first["preview"]["id"], "preview_sha256": first["preview"]["preview_sha256"],
        "decision": "approve", "approved_by": "reviewer",
    }), encoding="utf-8")
    with pytest.raises(DraftGateError):
        approve_draft(project, stale)
    assert second["preview"]["id"] != first["preview"]["id"]


def test_targeted_revision_invalidates_draft_and_requires_replacement_preview_and_approval(
    tmp_path: Path,
) -> None:
    """A targeted slide replacement invalidates stale full-deck evidence atomically."""
    project, deck_id, plan = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    record_review(project, "slide", slide["id"], "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", slide["id"], "visual-reviewer", "visual_quality", "passed")
    set_slide_status(project, slide["id"], "passed")
    decks_path = project / ".research/presentations/state/decks.yaml"
    decks = yaml.safe_load(decks_path.read_text(encoding="utf-8"))
    decks["decks"][deck_id]["status"] = "draft_review"
    decks_path.write_text(yaml.safe_dump(decks), encoding="utf-8")
    from PIL import Image

    original_slide = project / "renders/original.png"
    original_contact = project / "renders/original-contact.png"
    original_slide.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 20), (1, 2, 3)).save(original_slide)
    Image.new("RGB", (20, 20), (1, 2, 3)).save(original_contact)
    preview_path = _write_draft_preview(project, deck_id, original_slide, original_contact)
    registered = register_draft_preview(project, preview_path)
    decision_path = project / "decision.yaml"
    decision_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "deck_id": deck_id,
        "preview_id": registered["preview"]["id"],
        "preview_sha256": registered["preview"]["preview_sha256"],
        "decision": "approve",
        "approved_by": "reviewer",
    }), encoding="utf-8")
    approve_draft(project, decision_path)
    revision_path = project / "revision.yaml"
    revision_path.write_text(yaml.safe_dump({
        "deck_id": deck_id,
        "subject_type": "slide",
        "subject_id": slide["id"],
        "requested_by": "reviewer",
        "instructions": "Fix the evidence framing.",
        "revision_kind": "slide_retry",
    }), encoding="utf-8")
    result = request_targeted_revision(project, revision_path)
    replacement = result["replacement"]
    current_deck = load_decks(project)[deck_id]
    assert current_deck["draft_preview_id"] is None
    assert current_deck["draft_approval_id"] is None
    assert current_deck["status"] == "producing"
    assert result["revision"]["id"] in load_revision_requests(project)
    completion = project / "completion.yaml"
    completion.write_text(yaml.safe_dump({}), encoding="utf-8")
    with pytest.raises(CompletionGateError):
        complete_deck(project, deck_id, completion)

    replacement_id = replacement["id"]
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, replacement_id, status)
    record_review(project, "slide", replacement_id, "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", replacement_id, "visual-reviewer", "visual_quality", "passed")
    set_slide_status(project, replacement_id, "passed")
    decks = yaml.safe_load(decks_path.read_text(encoding="utf-8"))
    decks["decks"][deck_id]["status"] = "draft_review"
    decks_path.write_text(yaml.safe_dump(decks), encoding="utf-8")
    for artifact in (original_slide, original_contact):
        artifact.unlink()
    replacement_slide = project / "renders/replacement.png"
    replacement_contact = project / "renders/replacement-contact.png"
    Image.new("RGB", (20, 20), (9, 8, 7)).save(replacement_slide)
    Image.new("RGB", (20, 20), (9, 8, 7)).save(replacement_contact)
    replacement_preview = _write_draft_preview(project, deck_id, replacement_slide, replacement_contact)
    register_draft_preview(project, replacement_preview)
    assert load_decks(project)[deck_id]["draft_approval_id"] is None
    with pytest.raises(CompletionGateError):
        complete_deck(project, deck_id, completion)


def test_targeted_module_revision_invalidates_approved_draft_and_completion(
    tmp_path: Path,
) -> None:
    """Module retries invalidate the full-deck preview and approval pointers."""
    project, deck_id, _, completion, _, module = _complete_fixture(tmp_path)
    revision_path = project / "module-revision.yaml"
    revision_path.write_text(yaml.safe_dump({
        "deck_id": deck_id,
        "subject_type": "module",
        "subject_id": module["id"],
        "requested_by": "reviewer",
        "instructions": "Retry the visual module.",
        "revision_kind": "module_retry",
    }), encoding="utf-8")

    result = request_targeted_revision(project, revision_path)
    assert result["replacement"]["supersedes_module_id"] == module["id"]
    deck = load_decks(project)[deck_id]
    assert deck["draft_preview_id"] is None
    assert deck["draft_approval_id"] is None
    assert deck["status"] == "producing"
    with pytest.raises(CompletionGateError):
        complete_deck(project, deck_id, completion)


def test_plan_revision_invalidates_approved_draft_pointers(
    tmp_path: Path,
) -> None:
    """Plan-level revisions clear draft evidence before planning restarts."""
    project, deck_id, _, _, _, _ = _complete_fixture(tmp_path)
    decks_path = project / ".research/presentations/state/decks.yaml"
    decks = yaml.safe_load(decks_path.read_text(encoding="utf-8"))
    decks["decks"][deck_id]["status"] = "content_review"
    decks_path.write_text(yaml.safe_dump(decks), encoding="utf-8")
    revision_path = project / "plan-revision.yaml"
    revision_path.write_text(yaml.safe_dump({
        "deck_id": deck_id,
        "subject_type": "deck",
        "subject_id": deck_id,
        "requested_by": "reviewer",
        "instructions": "Change the emphasis.",
        "revision_kind": "change_emphasis",
    }), encoding="utf-8")

    request_targeted_revision(project, revision_path)
    deck = load_decks(project)[deck_id]
    assert deck["draft_preview_id"] is None
    assert deck["draft_approval_id"] is None
    assert deck["status"] == "planning"


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
        "instructions": "Fix overlap", "revision_kind": "slide_retry",
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


def test_targeted_module_revision_output_satisfies_evidence_record_contract(
    tmp_path: Path,
) -> None:
    """The public retry producer emits a relation-bound module contract."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    source = create_visual_module(project, slide["id"], "module-a", "architecture")
    for status in ("ready", "assigned", "producing", "review_required", "passed"):
        set_module_status(project, source["id"], status)
    revision_path = project / "module-contract-revision.yaml"
    revision_path.write_text(
        yaml.safe_dump(
            {
                "subject_type": "module",
                "subject_id": source["id"],
                "requested_by": "reviewer",
                "instructions": "Retry the module.",
                "revision_kind": "module_retry",
            }
        ),
        encoding="utf-8",
    )

    result = request_targeted_revision(project, revision_path)
    modules = load_visual_modules(project)
    replacement = modules[result["replacement"]["id"]]
    relations = {
        "slides": load_slides(project),
        "visual_modules": modules,
        "revision_requests": load_revision_requests(project),
    }

    assert validate_store_record(
        "visual_modules", replacement, relations=relations
    ) == replacement
    alias_drift = dict(replacement)
    alias_drift["spec_sha256"] = "a" * 64
    with pytest.raises(EvidenceContractError, match="spec|path"):
        validate_store_record("visual_modules", alias_drift, relations=relations)
    relation_drift = copy.deepcopy(relations)
    relation_drift["revision_requests"][replacement["revision_request_id"]][
        "target_id"
    ] = "mod-other"
    with pytest.raises(EvidenceContractError, match="revision_request_id"):
        validate_store_record("visual_modules", replacement, relations=relation_drift)


def _file_preimage(path: Path) -> tuple[bool, bytes, int]:
    """Capture exact file existence, bytes, and mode for rollback assertions."""
    if not path.exists():
        return False, b"", 0
    return True, path.read_bytes(), path.stat().st_mode & 0o777


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_slide_revision_failure_restores_every_staged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    """Every slide-revision commit position restores exact state preimages."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    record_review(project, "slide", slide["id"], "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", slide["id"], "visual-reviewer", "visual_quality", "passed")
    set_slide_status(project, slide["id"], "passed")
    state_dir = project / ".research/presentations/state"
    tracked = [state_dir / name for name in ("decks.yaml", "slides.yaml", "revision_requests.yaml")]
    before = {path: _file_preimage(path) for path in tracked}
    before_events = load_events(project)
    revision = project / "revision.yaml"
    revision.write_text(yaml.safe_dump({
        "deck_id": deck_id,
        "subject_type": "slide",
        "subject_id": slide["id"],
        "requested_by": "reviewer",
        "instructions": "Refresh the evidence framing.",
        "revision_kind": "slide_retry",
    }), encoding="utf-8")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(fail_at))

    with pytest.raises(RuntimeError, match="injected transaction commit failure"):
        request_targeted_revision(project, revision)

    assert {path: _file_preimage(path) for path in tracked} == before
    assert load_events(project) == before_events
    assert load_revision_requests(project) == {}
    assert set(load_slides(project)) == {slide["id"]}


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_module_revision_failure_restores_assignment_and_all_state_preimages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    """Module retries restore decks, slides, modules, assignments, and requests."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    module = create_visual_module(project, slide["id"], "module-a", "architecture")
    dependent = create_visual_module(
        project, slide["id"], "module-b", "architecture", dependencies=[module["id"]]
    )
    create_assignment_record(
        project,
        deck_id,
        module_id=dependent["id"],
        assignment_path="assignments/module-b.yaml",
        worker_id="worker-a",
        worker_type="architecture",
        spec_sha256="a" * 64,
        dependencies=[module["id"]],
        slide_id=slide["id"],
    )
    for status in ("ready", "assigned", "producing", "review_required"):
        set_module_status(project, module["id"], status)
    record_review(project, "module", module["id"], "scientific-reviewer", "scientific", "passed")
    record_review(project, "module", module["id"], "visual-reviewer", "visual_quality", "passed")
    set_module_status(project, module["id"], "passed")
    state_dir = project / ".research/presentations/state"
    tracked = [
        state_dir / name
        for name in ("decks.yaml", "slides.yaml", "visual_modules.yaml", "assignments.yaml", "revision_requests.yaml")
    ]
    before = {path: _file_preimage(path) for path in tracked}
    before_events = load_events(project)
    revision = project / "module-revision.yaml"
    revision.write_text(yaml.safe_dump({
        "deck_id": deck_id,
        "subject_type": "module",
        "subject_id": module["id"],
        "requested_by": "reviewer",
        "instructions": "Retry the visual module.",
        "revision_kind": "module_retry",
    }), encoding="utf-8")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(fail_at))

    with pytest.raises(RuntimeError, match="injected transaction commit failure"):
        request_targeted_revision(project, revision)

    assert {path: _file_preimage(path) for path in tracked} == before
    assert load_events(project) == before_events
    assert load_revision_requests(project) == {}
    assert set(load_visual_modules(project)) == {module["id"], dependent["id"]}
