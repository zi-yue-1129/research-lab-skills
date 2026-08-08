"""Independent review, selective retry, and revision workflow tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_events import load_events, load_revision_requests
from presentation_state import (
    create_slide,
    create_visual_module,
    load_decks,
    load_plans,
    load_slides,
    load_visual_modules,
    set_module_status,
    set_slide_status,
)
from presentation_workflow import (
    ReviewGateError,
    register_plan,
    record_production_review,
    request_targeted_revision,
)

from test_presentation_workflow import _approved_project


def _review_file(project: Path, name: str, document: dict) -> Path:
    """Write one review contract in a temporary project."""
    path = project / f"{name}.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _slide_at_review_required(tmp_path: Path) -> tuple[Path, str]:
    """Create an approved deck with one slide awaiting production reviews."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    return project, slide["id"]


def _passing_review(subject_type: str, subject_id: str, role: str) -> dict:
    """Build a passing independent production-review contract."""
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reviewer_id": f"{role}-reviewer",
        "reviewer_role": role,
        "status": "passed",
        "findings": [],
        "round": 1,
    }


def test_scientific_pass_does_not_satisfy_visual_quality_gate(tmp_path: Path) -> None:
    """A scientific pass leaves a slide review-required until visual pass."""
    project, slide_id = _slide_at_review_required(tmp_path)
    scientific = _review_file(project, "scientific", _passing_review("slide", slide_id, "scientific"))
    record_production_review(project, scientific)
    assert load_slides(project)[slide_id]["status"] == "review_required"

    visual = _review_file(project, "visual", _passing_review("slide", slide_id, "visual_quality"))
    record_production_review(project, visual)
    assert load_slides(project)[slide_id]["status"] == "passed"


def _reviewed_modules(tmp_path: Path) -> tuple[Path, str, str, Path]:
    """Create one failed and one passed module with an immutable sibling artifact."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    failed = create_visual_module(project, slide["id"], "failed", "architecture")
    sibling = create_visual_module(project, slide["id"], "sibling", "architecture")
    for module in (failed, sibling):
        for status in ("ready", "assigned", "producing", "review_required"):
            set_module_status(project, module["id"], status)
    set_module_status(project, sibling["id"], "passed")
    sibling_path = project / "artifacts" / "sibling.yaml"
    sibling_path.parent.mkdir(parents=True, exist_ok=True)
    sibling_path.write_text(yaml.safe_dump({"module_id": sibling["id"], "value": "stable"}), encoding="utf-8")
    return project, failed["id"], sibling["id"], sibling_path


def test_failed_module_retry_preserves_sibling_artifact(tmp_path: Path) -> None:
    """Retriying one module supersedes only that target and preserves its sibling."""
    project, failed_id, sibling_id, sibling_path = _reviewed_modules(tmp_path)
    before = (sibling_path.stat().st_mtime_ns, contract_sha256(yaml.safe_load(sibling_path.read_text(encoding="utf-8"))))
    revision = _review_file(project, "revision", {
        "subject_type": "module",
        "subject_id": failed_id,
        "requested_by": "reviewer",
        "instructions": "Fix the failed module.",
        "revision_kind": "module_retry",
    })
    result = request_targeted_revision(project, revision)
    after = (sibling_path.stat().st_mtime_ns, contract_sha256(yaml.safe_load(sibling_path.read_text(encoding="utf-8"))))
    assert load_visual_modules(project)[failed_id]["status"] == "superseded"
    assert result["replacement"]["supersedes_module_id"] == failed_id
    assert result["replacement"]["attempt"] == 2
    assert load_visual_modules(project)[sibling_id]["status"] == "passed"
    assert after == before


def test_failed_review_creates_exact_linked_revision_request(tmp_path: Path) -> None:
    """A failed review links exactly one request to its current module target."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    module = create_visual_module(project, slide["id"], "failed", "architecture")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_module_status(project, module["id"], status)
    review = _review_file(project, "failed-review", {
        "subject_type": "module", "subject_id": module["id"],
        "reviewer_id": "scientific-reviewer", "reviewer_role": "scientific",
        "status": "failed", "findings": [{"code": "unsupported-claim"}], "round": 1,
        "instructions": "Correct the unsupported claim.",
    })
    result = record_production_review(project, review)
    request = load_revision_requests(project)[result["revision_request"]["id"]]
    assert request["subject_type"] == "module"
    assert request["subject_id"] == module["id"]
    assert request["target_id"] == module["id"]
    assert request["revision_kind"] == "review_finding"
    assert request["review_id"] == result["review"]["id"]
    assert [event for event in load_events(project, "review_result") if event["id"] == result["review"]["id"]][0]["revision_request_id"] == request["id"]


def test_reviewer_cannot_review_slide_owned_by_same_identity(tmp_path: Path) -> None:
    """A slide author cannot submit an independent production review."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions", created_by="author-a")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    review = _review_file(project, "self-review", {
        "subject_type": "slide", "subject_id": slide["id"],
        "reviewer_id": "author-a", "reviewer_role": "scientific",
        "status": "passed", "findings": [], "round": 1,
    })
    with pytest.raises(ReviewGateError, match="self_review"):
        record_production_review(project, review)


@pytest.mark.parametrize(
    "revision_kind",
    [
        "revise_slide",
        "add_slide",
        "remove_slide",
        "reorder_slides",
        "change_emphasis",
        "change_audience",
        "change_duration",
    ],
)
def test_user_plan_revision_actions_create_new_reviewable_plan(
    tmp_path: Path, revision_kind: str
) -> None:
    """Every user plan revision returns a new reviewable plan request."""
    project, deck_id, _ = _approved_project(tmp_path)
    deck_path = project / ".research/presentations/state/decks.yaml"
    document = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    document["decks"][deck_id]["status"] = "awaiting_approval"
    deck_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    revision = _review_file(project, "plan-revision", {
        "subject_type": "deck",
        "subject_id": deck_id,
        "requested_by": "user",
        "instructions": "Update the plan.",
        "revision_kind": revision_kind,
    })
    result = request_targeted_revision(project, revision)
    assert result["revision"]["revision_kind"] == revision_kind
    assert load_decks(project)[deck_id]["status"] == "planning"
    assert result["next_action"] == "register_plan"
    assert len(load_plans(project)) == 1


def test_duplicate_role_and_round_review_is_rejected(tmp_path: Path) -> None:
    """One reviewer role may not submit the same production round twice."""
    project, slide_id = _slide_at_review_required(tmp_path)
    first = _review_file(project, "first", _passing_review("slide", slide_id, "scientific"))
    record_production_review(project, first)
    duplicate = _review_file(project, "duplicate", _passing_review("slide", slide_id, "scientific"))
    with pytest.raises(ReviewGateError, match="duplicate"):
        record_production_review(project, duplicate)


def test_review_findings_must_match_status(tmp_path: Path) -> None:
    """A passed review carrying blocking findings fails closed."""
    project, slide_id = _slide_at_review_required(tmp_path)
    review = _review_file(project, "invalid", {
        "subject_type": "slide",
        "subject_id": slide_id,
        "reviewer_id": "scientific-reviewer",
        "reviewer_role": "scientific",
        "status": "passed",
        "findings": [{"code": "overlap", "severity": "blocking"}],
        "round": 1,
    })
    with pytest.raises(ReviewGateError, match="findings"):
        record_production_review(project, review)


@pytest.mark.parametrize("subject_type", ["slide", "module"])
@pytest.mark.parametrize("revision_kind", sorted({
    "revise_slide", "add_slide", "remove_slide", "reorder_slides",
    "change_emphasis", "change_audience", "change_duration",
}))
def test_plan_revision_kinds_reject_production_unit_subjects_without_mutation(
    tmp_path: Path, subject_type: str, revision_kind: str
) -> None:
    """Plan-only revision kinds cannot target slides or modules."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    subject_id = slide["id"]
    if subject_type == "module":
        subject_id = create_visual_module(project, slide["id"], "module-a", "architecture")["id"]
    before = {path: path.read_bytes() for path in (project / ".research/presentations/state").glob("*.yaml")}
    revision = _review_file(project, "invalid-plan-revision", {
        "subject_type": subject_type, "subject_id": subject_id,
        "requested_by": "user", "instructions": "Change the plan.",
        "revision_kind": revision_kind,
    })
    with pytest.raises(ReviewGateError, match="plan_revision"):
        request_targeted_revision(project, revision)
    assert load_revision_requests(project) == {}
    assert {path: path.read_bytes() for path in before} == before


def test_module_retry_redirects_current_dependents_and_unblocks_after_pass(tmp_path: Path) -> None:
    """Replacing a module rewrites each current downstream dependency exactly once."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    source = create_visual_module(project, slide["id"], "source", "architecture")
    downstream = create_visual_module(project, slide["id"], "downstream", "architecture", [source["id"]])
    for status in ("ready", "assigned", "producing", "review_required", "passed"):
        set_module_status(project, source["id"], status)
    set_module_status(project, downstream["id"], "ready")
    revision = _review_file(project, "module-revision", {
        "subject_type": "module", "subject_id": source["id"],
        "requested_by": "reviewer", "instructions": "Retry the source.",
        "revision_kind": "module_retry",
    })
    result = request_targeted_revision(project, revision)
    replacement_id = result["replacement"]["id"]
    modules = load_visual_modules(project)
    assert modules[downstream["id"]]["dependencies"] == [replacement_id]
    assert len(modules[downstream["id"]]["dependencies"]) == len(set(modules[downstream["id"]]["dependencies"]))
    for status in ("ready", "assigned", "producing", "review_required"):
        set_module_status(project, replacement_id, status)
    for role in ("scientific", "visual_quality"):
        review = _review_file(project, f"replacement-{role}", _passing_review("module", replacement_id, role))
        record_production_review(project, review)
    set_module_status(project, downstream["id"], "assigned")
    set_module_status(project, downstream["id"], "producing")


def test_plan_revision_requires_current_plan_and_validates_digest(tmp_path: Path) -> None:
    """Historical IDs and stale current-plan files fail before any mutation."""
    project, deck_id, plan = _approved_project(tmp_path)
    second = dict(plan)
    second["plan_version"] = 2
    second_path = project / "plan-v2.yaml"
    second_path.write_text(yaml.safe_dump(second), encoding="utf-8")
    register_plan(project, deck_id, second_path, "planner-a")
    deck_path = project / ".research/presentations/state/decks.yaml"
    deck_document = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    deck_document["decks"][deck_id]["status"] = "awaiting_approval"
    deck_path.write_text(yaml.safe_dump(deck_document), encoding="utf-8")
    current_id = load_decks(project)[deck_id]["current_plan_id"]
    historical = next(plan_id for plan_id in load_plans(project) if plan_id != current_id)
    stale = _review_file(project, "stale-plan", {
        "subject_type": "plan", "subject_id": historical, "requested_by": "user",
        "instructions": "Update the old plan.", "revision_kind": "change_duration",
    })
    with pytest.raises(ReviewGateError, match="current_plan"):
        request_targeted_revision(project, stale)
    assert load_revision_requests(project) == {}

    current_document = project / load_plans(project)[current_id]["plan_path"]
    drifted_document = yaml.safe_load(current_document.read_text(encoding="utf-8"))
    drifted_document["purpose"] = "Drifted purpose"
    current_document.write_text(yaml.safe_dump(drifted_document), encoding="utf-8")
    current = _review_file(project, "drifted-plan", {
        "subject_type": "plan", "subject_id": current_id, "requested_by": "user",
        "instructions": "Update the current plan.", "revision_kind": "change_duration",
    })
    with pytest.raises(ReviewGateError, match="digest"):
        request_targeted_revision(project, current)
    assert load_revision_requests(project) == {}


def test_candidate_review_id_cannot_bypass_duplicate_role_round(tmp_path: Path) -> None:
    """A candidate-supplied ID never exempts an existing role/round duplicate."""
    project, slide_id = _slide_at_review_required(tmp_path)
    first = _review_file(project, "first-review", _passing_review("slide", slide_id, "scientific"))
    persisted = record_production_review(project, first)["review"]
    duplicate_document = _passing_review("slide", slide_id, "scientific")
    duplicate_document["id"] = persisted["id"]
    duplicate = _review_file(project, "duplicate-review", duplicate_document)
    with pytest.raises(ReviewGateError, match="duplicate"):
        record_production_review(project, duplicate)
    assert len([
        event for event in load_events(project, "review_result")
        if event.get("subject_type") == "slide" and event.get("subject_id") == slide_id
    ]) == 1


@pytest.mark.parametrize(
    ("status", "findings", "role"),
    [
        ("passed", [{"kind": "other", "description": "stale"}], "scientific"),
        ("failed", [{"kind": "unsupported-claim", "disposition": "fixed"}], "scientific"),
        ("failed", [{"code": "overlap", "disposition": "closed"}], "visual_quality"),
        ("blocked", [{"code": "overlap", "disposition": "accepted"}], "visual_quality"),
        ("failed", [{"kind": "overlap"}], "scientific"),
    ],
)
def test_finding_status_and_role_validation_fails_closed(
    tmp_path: Path, status: str, findings: list[dict], role: str
) -> None:
    """Passed findings, terminal failed findings, and cross-role kinds are rejected."""
    project, slide_id = _slide_at_review_required(tmp_path)
    review = _review_file(project, "finding-invalid", {
        "subject_type": "slide", "subject_id": slide_id,
        "reviewer_id": f"{role}-reviewer", "reviewer_role": role,
        "status": status, "findings": findings, "round": 1,
    })
    with pytest.raises(ReviewGateError, match="finding|status"):
        record_production_review(project, review)
    assert [
        event for event in load_events(project, "review_result")
        if event.get("subject_type") == "slide" and event.get("subject_id") == slide_id
    ] == []


def test_failed_review_transaction_rolls_back_request_and_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after request/event writes restores every affected file."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    review = _review_file(project, "failed-transaction", {
        "subject_type": "slide", "subject_id": slide["id"],
        "reviewer_id": "scientific-reviewer", "reviewer_role": "scientific",
        "status": "failed", "findings": [{"code": "unsupported-claim"}], "round": 1,
    })
    import presentation_workflow

    def fail_update(*args: object, **kwargs: object) -> dict:
        """Inject a deterministic failure after the event/request pair exists."""
        raise RuntimeError("injected revision annotation failure")

    monkeypatch.setattr(presentation_workflow, "_update_revision_request", fail_update)
    with pytest.raises(RuntimeError, match="injected"):
        record_production_review(project, review)
    assert [
        event for event in load_events(project, "review_result")
        if event.get("subject_type") == "slide" and event.get("subject_id") == slide["id"]
    ] == []
    assert load_revision_requests(project) == {}
    assert load_slides(project)[slide["id"]]["status"] == "review_required"
