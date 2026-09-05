"""Independent review, selective retry, and revision workflow tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
from typing import Iterator

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_events import (
    create_assignment_record,
    load_artifacts,
    load_assignments,
    load_events,
    load_revision_requests,
)
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

from gate_fixture_support import publish_and_lint_slide
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


def test_a_slide_passes_only_after_all_three_current_reviews(tmp_path: Path) -> None:
    """A slide stays review-required until every current gate has passed.

    This replaces `test_scientific_pass_does_not_satisfy_visual_quality_gate`,
    whose second review was a new `visual_quality` one. That role is now
    admissible only on replay: a new deck that could still submit the legacy
    pair would skip both `render_integrity` and `art_direction` entirely, so
    the claim under test is now the three-role set.
    """
    project, slide_id = _slide_at_review_required(tmp_path)
    deck_id = load_slides(project)[slide_id]["deck_id"]
    publish_and_lint_slide(project, deck_id, slide_id)
    scientific = _review_file(project, "scientific", _passing_review("slide", slide_id, "scientific"))
    record_production_review(project, scientific)
    assert load_slides(project)[slide_id]["status"] == "review_required"

    rendering = _review_file(project, "rendering", _passing_review("slide", slide_id, "render_integrity"))
    record_production_review(project, rendering)
    assert load_slides(project)[slide_id]["status"] == "review_required"

    art = _review_file(project, "art", _passing_review("slide", slide_id, "art_direction"))
    record_production_review(project, art)
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
    for role in ("scientific", "render_integrity"):
        review = _review_file(project, f"replacement-{role}", _passing_review("module", replacement_id, role))
        record_production_review(project, review)
    set_module_status(project, downstream["id"], "assigned")
    set_module_status(project, downstream["id"], "producing")


def test_module_retry_redirects_only_current_dependents_and_assignments(tmp_path: Path) -> None:
    """Historical-slide modules and assignments retain their source dependency."""
    project, deck_id, _ = _approved_project(tmp_path)
    current_slide = create_slide(project, deck_id, "slide-current", "Current")
    historical_slide = create_slide(project, deck_id, "slide-historical", "Historical")
    source = create_visual_module(project, current_slide["id"], "source", "architecture")
    current = create_visual_module(project, current_slide["id"], "current", "architecture", [source["id"]])
    historical = create_visual_module(project, historical_slide["id"], "historical", "architecture", [source["id"]])
    for status in ("ready", "assigned", "producing", "review_required", "passed"):
        set_module_status(project, source["id"], status)
    for module_id in (current["id"], historical["id"]):
        for status in ("ready", "assigned", "producing", "review_required"):
            if status == "producing":
                break
            set_module_status(project, module_id, status)
    for status in ("ready", "assigned", "producing", "review_required", "superseded"):
        set_slide_status(project, historical_slide["id"], status)
    spec_digest = "a" * 64
    current_assignment = create_assignment_record(
        project, deck_id, module_id=current["id"], assignment_path="assignments/current.yaml",
        worker_id="worker-current", worker_type="architecture", spec_sha256=spec_digest,
        dependencies=[source["id"]],
    )
    historical_assignment = create_assignment_record(
        project, deck_id, module_id=historical["id"], assignment_path="assignments/historical.yaml",
        worker_id="worker-historical", worker_type="architecture", spec_sha256=spec_digest,
        dependencies=[source["id"]],
    )
    revision = _review_file(project, "current-module-revision", {
        "subject_type": "module", "subject_id": source["id"],
        "requested_by": "reviewer", "instructions": "Retry the source.",
        "revision_kind": "module_retry",
    })
    result = request_targeted_revision(project, revision)
    replacement_id = result["replacement"]["id"]
    modules = load_visual_modules(project)
    assignments = load_assignments(project)
    assert modules[current["id"]]["dependencies"] == [replacement_id]
    assert modules[historical["id"]]["dependencies"] == [source["id"]]
    assert assignments[current_assignment["id"]]["dependencies"] == [replacement_id]
    assert assignments[historical_assignment["id"]]["dependencies"] == [source["id"]]


@pytest.mark.parametrize("commit_position", [1, 2, 3])
def test_failed_review_transaction_rolls_back_each_commit_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_position: int
) -> None:
    """Every failed-review commit position leaves no event, request, or status change."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    review = _review_file(project, "injected-review", {
        "subject_type": "slide", "subject_id": slide["id"],
        "reviewer_id": "scientific-reviewer", "reviewer_role": "scientific",
        "status": "failed", "findings": [{"code": "unsupported-claim"}], "round": 1,
    })
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(commit_position))
    with pytest.raises(RuntimeError, match="transaction commit"):
        record_production_review(project, review)
    assert not [event for event in load_events(project, "review_result") if event.get("subject_id") == slide["id"]]
    assert load_revision_requests(project) == {}
    assert load_slides(project)[slide["id"]]["status"] == "review_required"


@pytest.mark.parametrize("commit_position", [1, 2, 3])
def test_targeted_revision_transaction_rolls_back_each_commit_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_position: int
) -> None:
    """Every targeted-revision commit position leaves source and request unchanged."""
    project, failed_id, _, _ = _reviewed_modules(tmp_path)
    sibling = next(module for module in load_visual_modules(project).values() if module["id"] != failed_id)
    dependent = create_visual_module(
        project, sibling["slide_id"], "dependent", "architecture", [failed_id]
    )
    create_assignment_record(
        project, load_slides(project)[dependent["slide_id"]]["deck_id"], module_id=dependent["id"],
        assignment_path="assignments/dependent.yaml", worker_id="worker-dependent",
        worker_type="architecture", spec_sha256="a" * 64, dependencies=[failed_id],
    )
    revision = _review_file(project, "injected-revision", {
        "subject_type": "module", "subject_id": failed_id,
        "requested_by": "reviewer", "instructions": "Retry the module.",
        "revision_kind": "module_retry",
    })
    before = load_visual_modules(project)
    before_slides = load_slides(project)
    before_assignments = load_assignments(project)
    before_artifacts = load_artifacts(project)
    before_events = load_events(project)
    before_requests = load_revision_requests(project)
    state_root = project / ".research/presentations/state"
    tracked_paths = [
        state_root / "slides.yaml",
        state_root / "visual_modules.yaml",
        state_root / "assignments.yaml",
        state_root / "revision_requests.yaml",
    ]
    before_files = {
        path: (path.exists(), path.read_bytes() if path.exists() else b"", path.stat().st_mode & 0o777 if path.exists() else None)
        for path in tracked_paths
    }
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(commit_position))
    with pytest.raises(RuntimeError, match="transaction commit"):
        request_targeted_revision(project, revision)
    assert load_revision_requests(project) == {}
    assert load_visual_modules(project)[failed_id] == before[failed_id]
    assert load_visual_modules(project) == before
    assert load_slides(project) == before_slides
    assert load_assignments(project) == before_assignments
    assert load_artifacts(project) == before_artifacts
    assert load_events(project) == before_events
    assert load_revision_requests(project) == before_requests
    for path, snapshot in before_files.items():
        assert path.exists() == snapshot[0]
        if snapshot[0]:
            assert path.read_bytes() == snapshot[1]
            assert path.stat().st_mode & 0o777 == snapshot[2]


def test_transaction_rollback_releases_sidecar_for_waiting_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A low-level writer waits through rollback and persists afterward."""
    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    review = _review_file(project, "concurrent-review", {
        "subject_type": "slide", "subject_id": slide["id"],
        "reviewer_id": "scientific-reviewer", "reviewer_role": "scientific",
        "status": "failed", "findings": [{"code": "unsupported-claim"}], "round": 1,
    })
    import presentation_state
    import presentation_transactions

    locked = threading.Event()
    allow_commit = threading.Event()
    original_notify = presentation_transactions.WorkflowTransaction._notify_locked

    def notify_locked(handle: object) -> None:
        """Signal the action has acquired all sidecar locks."""
        original_notify(handle)
        locked.set()

    monkeypatch.setattr(presentation_transactions.WorkflowTransaction, "_notify_locked", notify_locked)

    def before_commit(handle: object) -> None:
        """Pause commit until the competing writer has attempted its lock."""
        assert allow_commit.wait(timeout=3)

    monkeypatch.setattr(presentation_transactions.WorkflowTransaction, "_before_commit", before_commit)
    writer_lock_attempted = threading.Event()
    writer_finished = threading.Event()
    writer_thread_id: list[int] = []
    original_guard = presentation_state.journal_admission_guard

    @contextmanager
    def guard_with_writer_barrier(project_root: Path, timeout: int) -> Iterator[None]:
        """Observe the competing thread's journal-guard acquisition attempt."""
        if writer_thread_id and threading.get_ident() == writer_thread_id[0]:
            writer_lock_attempted.set()
        with original_guard(project_root, timeout):
            yield

    monkeypatch.setattr(
        presentation_state, "journal_admission_guard", guard_with_writer_barrier
    )

    def write_after_lock() -> None:
        """Persist an unrelated low-level state update once the sidecar is free."""
        writer_thread_id.append(threading.get_ident())
        presentation_state.set_slide_status(project, slide["id"], "blocked")
        writer_finished.set()

    action_error: list[BaseException] = []

    def run_action() -> None:
        """Run the gated action while the sidecar writer contends."""
        try:
            record_production_review(project, review)
        except BaseException as exc:  # noqa: BLE001 - test captures injected failure
            action_error.append(exc)

    action = threading.Thread(target=run_action)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", "2")
    action.start()
    assert locked.wait(timeout=2)
    writer = threading.Thread(target=write_after_lock)
    writer.start()
    assert writer_lock_attempted.wait(timeout=2)
    assert not writer_finished.is_set()
    allow_commit.set()
    action.join(timeout=3)
    writer.join(timeout=3)
    assert action_error and "transaction commit" in str(action_error[0])
    assert writer_finished.is_set()
    assert load_slides(project)[slide["id"]]["status"] == "blocked"
    assert load_revision_requests(project) == {}
    assert not [event for event in load_events(project, "review_result") if event.get("subject_id") == slide["id"]]


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
