"""Behavioral tests for report-slides gate predicates."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_gates import (
    AssignmentGateError,
    ApprovalGateError,
    CompletionGateError,
    PublicationGateError,
    ProductionGateError,
    assert_module_assignable,
    assert_module_publishable,
    assert_deck_completable,
    assert_plan_approvable,
    assert_production_allowed,
)
from presentation_state import create_deck, create_slide, create_visual_module, load_visual_modules, record_review, set_deck_status, set_module_status
from presentation_events import create_assignment_record, load_events, load_plans, append_event
from presentation_events import register_plan_record

_DEFAULT_TOKENS = (
    Path(__file__).resolve().parents[2] / "references" / "tokens" / "default.tokens.yaml"
)


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
    assert set(error) == {"error", "predicate", "deck_id", "blockers"}

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--set-deck-status", "--deck-id", deck["id"],
         "--status", "completed", "--json"],
        cwd=project, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 1
    completed_error = json.loads(completed.stdout)
    assert completed_error["error"] == "CompletionGateError"
    assert set(completed_error) == {"error", "predicate", "deck_id", "blockers"}


def test_generic_record_review_cannot_bypass_atomic_production_review(tmp_path: Path) -> None:
    """The legacy review CLI cannot create pass evidence outside workflow actions."""
    project = _project(tmp_path)
    deck = create_deck(project, "Test deck")
    slide = create_slide(project, deck["id"], "slide-01", "Evidence")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--record-review", "--subject-type", "slide",
         "--subject-id", slide["id"], "--reviewer-id", "reviewer",
         "--reviewer-role", "scientific", "--status", "passed", "--json"],
        cwd=project, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    error = json.loads(result.stdout)
    assert error["error"] == "ReviewGateError"
    assert set(error) == {"error", "predicate", "deck_id", "blockers"}


@pytest.mark.parametrize("review_status", ["passed", "failed", "blocked"])
def test_generic_module_review_gate_reports_known_deck_without_mutation(
    tmp_path: Path, review_status: str
) -> None:
    """Generic module review gates identify the module's owning deck."""
    project = _project(tmp_path)
    deck = create_deck(project, "Test deck")
    slide = create_slide(project, deck["id"], "slide-01", "Evidence")
    module = create_visual_module(project, slide["id"], "module-a", "architecture")
    before = load_visual_modules(project)[module["id"]]
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--record-review", "--subject-type", "module",
         "--subject-id", module["id"], "--reviewer-id", "reviewer",
         "--reviewer-role", "visual_quality", "--status", review_status, "--json"],
        cwd=project, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    error = json.loads(result.stdout)
    assert error["error"] == "ReviewGateError"
    assert set(error) == {"error", "predicate", "deck_id", "blockers"}
    assert error["deck_id"] == deck["id"]
    assert load_events(project) == []
    assert load_visual_modules(project)[module["id"]] == before


@pytest.mark.parametrize("review_status", ["failed", "blocked"])
def test_generic_failed_or_blocked_review_cannot_write_low_level_evidence(tmp_path: Path, review_status: str) -> None:
    """Incomplete generic production reviews fail closed without state events."""
    project = _project(tmp_path)
    deck = create_deck(project, "Test deck")
    slide = create_slide(project, deck["id"], "slide-01", "Evidence")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--record-review", "--subject-type", "slide",
         "--subject-id", slide["id"], "--reviewer-id", "reviewer",
         "--reviewer-role", "scientific", "--status", review_status, "--json"],
        cwd=project, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    error = json.loads(result.stdout)
    assert error["error"] == "ReviewGateError"
    assert set(error) == {"error", "predicate", "deck_id", "blockers"}
    assert load_events(project) == []


def test_unknown_generic_slide_pass_returns_exact_gate_json(tmp_path: Path) -> None:
    """Unknown gated slide pass attempts use the four-key gate contract."""
    project = _project(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--set-slide-status", "--slide-id", "sld_missing",
         "--status", "passed", "--json"],
        cwd=project, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    error = json.loads(result.stdout)
    assert set(error) == {"error", "predicate", "deck_id", "blockers"}
    assert error["error"] == "ReviewGateError"


def _append_bound_content_review(
    project: Path,
    deck_id: str,
    review_id: str,
    round_number: int,
    status: str,
    plan_id: str,
    plan_version: int,
    plan_sha256: str,
    ts: str,
) -> None:
    """Append one content review event with explicit plan identity."""
    append_event(project, {
        "event": "review_result", "id": review_id, "subject_type": "deck", "subject_id": deck_id,
        "reviewer_id": "reviewer-b", "reviewer_role": "content", "identity_verifiable": True,
        "status": status, "findings": [], "round": round_number, "ts": ts,
        "current_plan_id": plan_id, "current_plan_version": plan_version,
        "current_plan_sha256": plan_sha256,
    })


def test_plan_review_selection_filters_current_identity_before_latest_round(tmp_path: Path) -> None:
    """A stale round two cannot mask a valid current-plan round one."""
    project, deck_id, plan_path = _registered_plan(tmp_path)
    current = next(record for record in load_plans(project).values() if record["deck_id"] == deck_id)
    current_digest = contract_sha256(yaml.safe_load(plan_path.read_text(encoding="utf-8")))
    _append_bound_content_review(project, deck_id, "rev-current", 1, "passed", current["id"], 1, current_digest, "2026-08-08T00:00:01Z")
    _append_bound_content_review(project, deck_id, "rev-stale", 2, "failed", current["id"], 1, "f" * 64, "2026-08-08T00:00:02Z")
    assert assert_plan_approvable(project, _approval(project, deck_id, plan_path))["deck"]["id"] == deck_id


def test_plan_review_selection_keeps_current_failure_blocking_against_stale_pass(tmp_path: Path) -> None:
    """A stale pass cannot mask a failing review bound to the current plan."""
    project, deck_id, plan_path = _registered_plan(tmp_path)
    current = next(record for record in load_plans(project).values() if record["deck_id"] == deck_id)
    current_digest = contract_sha256(yaml.safe_load(plan_path.read_text(encoding="utf-8")))
    _append_bound_content_review(project, deck_id, "rev-current", 1, "failed", current["id"], 1, current_digest, "2026-08-08T00:00:01Z")
    _append_bound_content_review(project, deck_id, "rev-stale", 2, "passed", current["id"], 1, "f" * 64, "2026-08-08T00:00:02Z")
    with pytest.raises(ApprovalGateError, match="content_review:failed"):
        assert_plan_approvable(project, _approval(project, deck_id, plan_path))


def _approved_module_project(tmp_path: Path) -> tuple[Path, str, str, dict, dict]:
    """Create an approved deck and one ready module with a persisted spec."""
    project, deck_id, plan_path = _registered_plan(tmp_path)
    deck_state = project / ".research/presentations/state/decks.yaml"
    state = yaml.safe_load(deck_state.read_text(encoding="utf-8"))
    state["decks"][deck_id].update({
        "status": "approved", "approval_id": "approval-test", "approved_plan_version": 1,
        "approved_plan_sha256": contract_sha256(yaml.safe_load(plan_path.read_text(encoding="utf-8"))),
    })
    deck_state.write_text(yaml.safe_dump(state), encoding="utf-8")
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes the decision")
    module = create_visual_module(project, slide["id"], "module-a", "architecture")
    spec = {
        "schema_version": 1, "visual_id": "visual-a", "message": "Explain evidence",
        "modules": [{
            "id": "module-a", "purpose": "Show evidence", "semantic_responsibility": "Evidence",
            "route": "native", "module_type": "architecture", "input_anchors": [],
            "output_anchors": [], "dependencies": [], "dimensions": {"width": 4, "height": 3},
            "style_tokens_ref": "deck.tokens.yaml", "editability": "native", "annotation_requirements": [], "reuse_of": None,
        }],
        "connections": [], "layout": {"direction": "TB", "hierarchy": ["module-a"]},
    }
    spec_path = project / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    # `style_tokens_ref` must now resolve to a valid token file beside the spec:
    # an unresolved style reference is indistinguishable from an applied one.
    shutil.copy(_DEFAULT_TOKENS, project / "deck.tokens.yaml")
    module_state = project / ".research/presentations/state/visual_modules.yaml"
    modules = yaml.safe_load(module_state.read_text(encoding="utf-8"))
    modules["visual_modules"][module["id"]].update({"visual_spec_path": "spec.yaml", "visual_spec_sha256": contract_sha256(spec)})
    module_state.write_text(yaml.safe_dump(modules), encoding="utf-8")
    set_module_status(project, module["id"], "ready")
    return project, deck_id, module["id"], module, spec


def test_production_gate_and_dependency_assignment_succeed_with_current_evidence(tmp_path: Path) -> None:
    """An approved deck and exact dependency/spec assignment satisfy the gates."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    assert assert_production_allowed(project, deck_id)["id"] == deck_id
    assignment = {
        "schema_version": 1, "module_id": module_id, "worker_type": "architecture",
        "dependencies": [], "spec_sha256": contract_sha256(spec), "inputs_resolved": True,
        "assigned_at": "2026-08-08T00:00:00Z", "blocker": None,
    }
    assert assert_module_assignable(project, module_id, assignment)["module"]["id"] == module_id


def test_assignment_rejects_worker_dependency_and_spec_binding_mutations(tmp_path: Path) -> None:
    """Assignment predicates reject worker, dependency, and spec digest drift."""
    project, _, module_id, module, spec = _approved_module_project(tmp_path)
    assignment = {
        "schema_version": 1, "module_id": module_id, "worker_type": "conceptual",
        "dependencies": ["mod_20260101_deadbe"], "spec_sha256": "0" * 64, "inputs_resolved": True,
        "assigned_at": "2026-08-08T00:00:00Z", "blocker": None,
    }
    with pytest.raises(AssignmentGateError, match="worker_type_mismatch"):
        assert_module_assignable(project, module_id, assignment)


def test_publication_requires_existing_matching_artifact_and_assignment_binding(tmp_path: Path) -> None:
    """Publication verifies assignment identity, path existence, and actual bytes."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    assignment_path = project / "assignment.yaml"
    assignment_path.write_text("assignment", encoding="utf-8")
    assignment = create_assignment_record(
        project, deck_id, module_id=module_id, assignment_path="assignment.yaml", worker_id="worker-a",
        worker_type="architecture", spec_sha256=contract_sha256(spec), dependencies=[], inputs_resolved=True,
        slide_id=module["slide_id"],
    )
    set_module_status(project, module_id, "assigned")
    artifact = {"module_id": module_id, "assignment_id": assignment["id"], "producer_id": "worker-a", "spec_sha256": contract_sha256(spec), "path": "artifacts/module.svg", "sha256": "0" * 64}
    with pytest.raises(PublicationGateError, match="missing_artifact"):
        assert_module_publishable(project, module_id, artifact)
    output = project / "artifacts/module.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("published", encoding="utf-8")
    with pytest.raises(PublicationGateError, match="artifact_digest_mismatch"):
        assert_module_publishable(project, module_id, artifact)
    import hashlib
    artifact["sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    assert assert_module_publishable(project, module_id, artifact)["artifact"]["module_id"] == module_id


def test_publication_resolves_explicit_current_assignment_not_insertion_order(tmp_path: Path) -> None:
    """A stale later assignment cannot mask the module's explicit current one."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    first = create_assignment_record(
        project, deck_id, module_id=module_id, assignment_path="assignment-current.yaml",
        worker_id="worker-current", worker_type="architecture", spec_sha256=contract_sha256(spec),
        dependencies=[], inputs_resolved=True, slide_id=module["slide_id"],
    )
    second = create_assignment_record(
        project, deck_id, module_id=module_id, assignment_path="assignment-stale.yaml",
        worker_id="worker-stale", worker_type="architecture", spec_sha256=contract_sha256(spec),
        dependencies=[], inputs_resolved=True, slide_id=module["slide_id"],
    )
    assignments_path = project / ".research/presentations/state/assignments.yaml"
    assignment_document = yaml.safe_load(assignments_path.read_text(encoding="utf-8"))
    assignment_document["assignments"] = {
        "asn_0001_current": dict(assignment_document["assignments"][first["id"]], id="asn_0001_current"),
        "asn_9999_stale": dict(assignment_document["assignments"][second["id"]], id="asn_9999_stale"),
    }
    assignments_path.write_text(yaml.safe_dump(assignment_document), encoding="utf-8")
    first["id"], second["id"] = "asn_0001_current", "asn_9999_stale"
    modules_path = project / ".research/presentations/state/visual_modules.yaml"
    modules = yaml.safe_load(modules_path.read_text(encoding="utf-8"))
    modules["visual_modules"][module_id]["assignment_path"] = "assignment-current.yaml"
    modules_path.write_text(yaml.safe_dump(modules), encoding="utf-8")
    set_module_status(project, module_id, "assigned")
    output = project / "artifacts/current.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("current", encoding="utf-8")
    import hashlib
    artifact = {
        "module_id": module_id, "assignment_id": first["id"], "producer_id": "worker-current",
        "spec_sha256": contract_sha256(spec), "path": "artifacts/current.svg",
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    assert assert_module_publishable(project, module_id, artifact)["assignment"]["id"] == first["id"]
    assert second["id"] != first["id"]


def test_publication_rejects_ambiguous_current_assignment(tmp_path: Path) -> None:
    """Duplicate current assignment references fail closed."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    first = create_assignment_record(
        project, deck_id, module_id=module_id, assignment_path="same.yaml", worker_id="worker-a",
        worker_type="architecture", spec_sha256=contract_sha256(spec), dependencies=[], inputs_resolved=True,
        slide_id=module["slide_id"],
    )
    second = create_assignment_record(
        project, deck_id, module_id=module_id, assignment_path="same.yaml", worker_id="worker-b",
        worker_type="architecture", spec_sha256=contract_sha256(spec), dependencies=[], inputs_resolved=True,
        slide_id=module["slide_id"],
    )
    set_module_status(project, module_id, "assigned")
    with pytest.raises(PublicationGateError, match="ambiguous_assignment"):
        assert_module_publishable(project, module_id, {"module_id": module_id})
    assert first["id"] != second["id"]
