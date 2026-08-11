"""Regression tests for schema-v2 evidence workflow production."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

import pytest
import yaml

from presentation_evidence_workflow import MigrationRequiredError
from presentation_events import (
    append_event,
    create_artifact_record,
    create_assignment_record,
    create_revision_request,
    load_events,
    register_plan_record,
)
from presentation_evidence_store import evidence_store_path
from presentation_state import (
    create_deck,
    create_slide,
    create_visual_module,
    load_decks,
    record_review,
    set_module_status,
    set_slide_status,
)
from presentation_transactions import SimulatedProcessDeath, WorkflowTransaction
from presentation_workflow import (
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
from test_presentation_workflow import (
    _approved_project,
    _complete_fixture,
    _write_draft_preview,
)


def _legacy_project(tmp_path: Path, version: int) -> Path:
    """Create a minimal legacy state tree without operational sidecars.

    Args:
        tmp_path: Per-test temporary directory.
        version: Legacy schema version to serialize.

    Returns:
        Project root containing a deliberately minimal legacy deck store.
    """
    project_root = tmp_path / "project"
    state_root = project_root / ".research/presentations/state"
    (project_root / ".git").mkdir(parents=True)
    state_root.mkdir(parents=True)
    (state_root / "decks.yaml").write_text(
        yaml.safe_dump({"version": version, "decks": {}}, sort_keys=True),
        encoding="utf-8",
    )
    return project_root


_STATE_TOP_KEYS = {
    "plans.yaml": "plans",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
    "assignments.yaml": "assignments",
    "artifacts.yaml": "artifacts",
    "revision_requests.yaml": "revision_requests",
}


@pytest.mark.parametrize("state_name", sorted(_STATE_TOP_KEYS))
@pytest.mark.parametrize(
    "state_document",
    [
        {"version": 0},
        {"version": 1},
        {"version": True},
        {"version": 3},
        {"version": 2, "schema_version": 1},
    ],
)
def test_any_existing_non_deck_legacy_or_unsupported_store_blocks_all_writers(
    tmp_path: Path,
    state_name: str,
    state_document: dict[str, object],
) -> None:
    """Reject every marked non-deck store before a writer creates sidecars.

    Args:
        tmp_path: Per-test temporary directory.
        state_name: Existing state document whose marker is unsafe.
        state_document: Legacy, boolean, future, or mixed schema marker.
    """
    project_root = _legacy_project(tmp_path, 2)
    state_path = project_root / ".research/presentations/state" / state_name
    document = {**state_document, _STATE_TOP_KEYS[state_name]: {}}
    state_path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
    before = _tree_preimage(project_root)

    for action in (
        lambda: create_deck(project_root, "Blocked state writer"),
        lambda: append_event(project_root, {"event": "blocked", "id": "blocked"}),
        lambda: register_draft_preview(project_root, project_root / "preview.yaml"),
    ):
        with pytest.raises(MigrationRequiredError) as error:
            action()
        assert error.value.target_schema_version == 2
        assert _tree_preimage(project_root) == before


def _tree_preimage(project_root: Path) -> dict[str, bytes]:
    """Return exact files beneath the presentation root before an action.

    Args:
        project_root: Project root whose presentation subtree is captured.

    Returns:
        Canonical relative file bytes keyed by presentation-relative path.
    """
    presentation_root = project_root / ".research/presentations"
    return {
        path.relative_to(presentation_root).as_posix(): path.read_bytes()
        for path in sorted(presentation_root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("version", [0, 1])
def test_legacy_authorized_entrypoints_require_migration_before_any_write(
    tmp_path: Path,
    version: int,
) -> None:
    """Require v2 before workflow, state, or event writers create sidecars.

    A removal of the common migration guard would make this test fail by
    creating a workflow/store lock or by raising an unrelated legacy parser
    error instead of the typed boundary error.

    Args:
        tmp_path: Per-test temporary directory.
        version: Legacy schema version under test.
    """
    project_root = _legacy_project(tmp_path, version)
    before = _tree_preimage(project_root)

    for action in (
        lambda: register_draft_preview(project_root, project_root / "preview.yaml"),
        lambda: create_deck(project_root, "Legacy deck"),
        lambda: create_slide(project_root, "deck-missing", "slide-01", "Legacy slide"),
        lambda: create_visual_module(project_root, "slide-missing", "module", "architecture"),
        lambda: set_slide_status(project_root, "slide-missing", "passed"),
        lambda: set_module_status(project_root, "module-missing", "passed"),
        lambda: record_review(project_root, "deck", "deck-missing", "reviewer", "content", "passed"),
        lambda: create_artifact_record(
            project_root,
            "deck-missing",
            "slide-png",
            "renders/slide.png",
            "0" * 64,
            "renderer",
        ),
        lambda: append_event(project_root, {"event": "test", "id": "legacy"}),
        lambda: register_plan_record(
            project_root, "deck-missing", "plans/plan.yaml", "0" * 64, "planner"
        ),
        lambda: create_assignment_record(
            project_root, "deck-missing", "slide-missing", "module-missing", "assignment.yaml", "0" * 64, "planner"
        ),
        lambda: create_revision_request(
            project_root, "deck", "deck-missing", "reviewer", "migrate first"
        ),
        lambda: register_plan(project_root, "deck-missing", project_root / "plan.yaml", "planner"),
        lambda: record_content_review(project_root, "deck-missing", project_root / "review.yaml"),
        lambda: approve_deck(project_root, project_root / "approval.yaml"),
        lambda: record_production_review(project_root, project_root / "production.yaml"),
        lambda: request_targeted_revision(project_root, project_root / "revision.yaml"),
        lambda: approve_draft(project_root, project_root / "decision.yaml"),
        lambda: complete_deck(project_root, "deck-missing", project_root / "completion.yaml"),
    ):
        with pytest.raises(MigrationRequiredError) as error:
            action()
        assert error.value.target_schema_version == 2
        assert error.value.source_schema_version == version
        assert _tree_preimage(project_root) == before


@pytest.mark.parametrize("version", [0, 1])
def test_cli_migration_error_is_structured_and_write_free(tmp_path: Path, version: int) -> None:
    """Expose legacy writer rejection as a typed JSON CLI payload.

    Args:
        tmp_path: Per-test temporary directory.
        version: Legacy schema version under test.
    """
    project_root = _legacy_project(tmp_path, version)
    before = _tree_preimage(project_root)
    script = Path(__file__).parents[1] / "presentation_state.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--create-deck", "--title", "Legacy", "--json"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["error"] == "MigrationRequiredError"
    assert payload["source_schema_version"] == version
    assert payload["target_schema_version"] == 2
    assert _tree_preimage(project_root) == before


def test_v2_producers_publish_bound_envelopes_cas_and_pointers(tmp_path: Path) -> None:
    """Publish every current v2 pointer with its source event and CAS bytes.

    Removing the evidence transition from any preview, approval, or completion
    producer would leave a missing pointer, envelope, event binding, or
    content-addressed object and make this test fail.

    Args:
        tmp_path: Per-test temporary directory.
    """
    project_root, deck_id, _, _, _, _ = _complete_fixture(tmp_path)

    deck = load_decks(project_root)[deck_id]
    evidence_document = yaml.safe_load(
        evidence_store_path(project_root).read_text(encoding="utf-8")
    )
    evidence = evidence_document["evidence"]
    pointers = (
        ("draft_preview_evidence_id", "draft_preview"),
        ("draft_approval_evidence_id", "draft_approval"),
        ("completion_evidence_id", "deck_completion"),
    )
    for pointer_field, expected_kind in pointers:
        evidence_id = deck[pointer_field]
        envelope = evidence[evidence_id]
        assert envelope["id"] == evidence_id
        assert envelope["evidence_kind"] == expected_kind
        assert any(
            event.get("id") == envelope["source_event_id"]
            for event in load_events(project_root)
        )
        for artifact_reference in envelope["artifact_refs"]:
            cas_path = project_root / artifact_reference["cas_path"]
            assert cas_path.is_file()
            assert cas_path.read_bytes() == (
                project_root / artifact_reference["original_path"]
            ).read_bytes()


def _preview_ready_project(tmp_path: Path) -> tuple[Path, str, Path]:
    """Create a current draft-ready project without a prior v2 preview.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        Project root, current deck ID, and the validated preview source path.
    """
    project_root, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project_root, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project_root, slide["id"], status)
    record_review(project_root, "slide", slide["id"], "scientific", "scientific", "passed")
    record_review(project_root, "slide", slide["id"], "visual", "visual_quality", "passed")
    set_slide_status(project_root, slide["id"], "passed")
    module = create_visual_module(project_root, slide["id"], "module-a", "architecture")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_module_status(project_root, module["id"], status)
    record_review(project_root, "module", module["id"], "scientific", "scientific", "passed")
    record_review(project_root, "module", module["id"], "visual", "visual_quality", "passed")
    set_module_status(project_root, module["id"], "passed")
    deck_path = project_root / ".research/presentations/state/decks.yaml"
    decks = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    decks["decks"][deck_id]["status"] = "draft_review"
    deck_path.write_text(yaml.safe_dump(decks), encoding="utf-8")
    from PIL import Image

    for path in (project_root / "renders/slide-1.png", project_root / "renders/contact.png"):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 20), (1, 2, 3)).save(path)
    preview = _write_draft_preview(
        project_root,
        deck_id,
        project_root / "renders/slide-1.png",
        project_root / "renders/contact.png",
    )
    return project_root, deck_id, preview


def _semantic_presentation_tree(project_root: Path) -> dict[str, bytes]:
    """Capture every persisted evidence/state payload while excluding locks.

    Args:
        project_root: Project root containing the presentation subtree.

    Returns:
        Stable relative payload bytes excluding operational sidecars/journals.
    """
    presentation_root = project_root / ".research/presentations"
    return {
        path.relative_to(presentation_root).as_posix(): path.read_bytes()
        for path in sorted(presentation_root.rglob("*"))
        if path.is_file()
        and path.suffix not in {".lock", ".tmp"}
        and "transactions" not in path.parts
    }


def _assert_no_transaction_orphans(project_root: Path) -> None:
    """Require a producer failure/recovery to leave no staged data behind.

    Args:
        project_root: Project root whose transaction subtree is checked.
    """
    presentation_root = project_root / ".research/presentations"
    assert not list(presentation_root.rglob("*.tmp"))
    journal_root = presentation_root / "transactions"
    assert not list(journal_root.glob("*.json")) if journal_root.exists() else True


def _approval_ready_project(tmp_path: Path) -> tuple[Path, str, Path]:
    """Create a draft decision source with one current v2 preview.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        Project root, deck ID, and strict draft-decision source path.
    """
    project_root, deck_id, preview = _preview_ready_project(tmp_path)
    registered = register_draft_preview(project_root, preview)
    decision = project_root / "decision.yaml"
    decision.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "deck_id": deck_id,
                "preview_id": registered["preview"]["id"],
                "preview_sha256": registered["preview"]["preview_sha256"],
                "decision": "approve",
                "approved_by": "reviewer",
            }
        ),
        encoding="utf-8",
    )
    return project_root, deck_id, decision


@pytest.mark.parametrize("replacement_position", range(1, 6))
def test_preview_failure_rolls_back_every_event_evidence_cas_pointer_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_position: int,
) -> None:
    """Restore exact state when any first-preview replacement fails.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Isolated replacement-failure injection control.
        replacement_position: Ordered staged write that must fail.
    """
    project_root, _, preview = _preview_ready_project(tmp_path)
    before = _semantic_presentation_tree(project_root)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(replacement_position))

    with pytest.raises(RuntimeError, match="transaction commit failed"):
        register_draft_preview(project_root, preview)

    assert _semantic_presentation_tree(project_root) == before
    _assert_no_transaction_orphans(project_root)


@pytest.mark.parametrize("replacement_position", range(1, 6))
def test_preview_process_death_recovers_every_visible_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_position: int,
) -> None:
    """Recover every partially visible preview transaction before republishing.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Isolated process-death injection control.
        replacement_position: Ordered staged write after which the process dies.
    """
    project_root, deck_id, preview = _preview_ready_project(tmp_path)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", str(replacement_position))

    with pytest.raises(SimulatedProcessDeath, match="simulated process death"):
        register_draft_preview(project_root, preview)
    journal_root = project_root / ".research/presentations/transactions"
    assert list(journal_root.glob("*.json"))

    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")
    result = register_draft_preview(project_root, preview)

    deck = load_decks(project_root)[deck_id]
    assert deck["draft_preview_evidence_id"] == result["evidence_id"]
    assert [event["id"] for event in load_events(project_root, "draft_preview")] == [
        result["preview"]["id"]
    ]
    _assert_no_transaction_orphans(project_root)


def test_high_level_preview_recovers_journal_before_rechecking_all_state_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover a split legacy marker before the producer's locked v2 recheck.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Isolated crash-injection control.
    """
    project_root, deck_id, preview = _preview_ready_project(tmp_path)
    plans_path = project_root / ".research/presentations/state/plans.yaml"
    assert plans_path.is_file()
    legacy_bytes = yaml.safe_dump({"version": 1, "plans": {}}).encode("utf-8")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")
    with pytest.raises(SimulatedProcessDeath, match="simulated process death"):
        with WorkflowTransaction([plans_path], project_root) as transaction_handle:
            transaction_handle.stage_bytes(plans_path, legacy_bytes)
            transaction_handle.commit()
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")

    result = register_draft_preview(project_root, preview)

    assert load_decks(project_root)[deck_id]["draft_preview_evidence_id"] == result["evidence_id"]
    assert yaml.safe_load(plans_path.read_text(encoding="utf-8"))["version"] == 2
    _assert_no_transaction_orphans(project_root)


@pytest.mark.parametrize("replacement_position", range(1, 4))
def test_approval_failure_rolls_back_every_event_envelope_pointer_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_position: int,
) -> None:
    """Rollback each approval replacement without an event or envelope orphan.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Isolated replacement-failure injection control.
        replacement_position: Ordered staged approval replacement to fail.
    """
    project_root, _, decision = _approval_ready_project(tmp_path)
    before = _semantic_presentation_tree(project_root)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(replacement_position))

    with pytest.raises(RuntimeError, match="transaction commit failed"):
        approve_draft(project_root, decision)

    assert _semantic_presentation_tree(project_root) == before
    _assert_no_transaction_orphans(project_root)


@pytest.mark.parametrize("replacement_position", range(1, 4))
def test_completion_failure_rolls_back_every_event_envelope_pointer_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_position: int,
) -> None:
    """Rollback every replayed completion replacement without dangling state.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Isolated replacement-failure injection control.
        replacement_position: Ordered staged completion replacement to fail.
    """
    project_root, deck_id, _, completion, _, _ = _complete_fixture(tmp_path)
    deck_path = project_root / ".research/presentations/state/decks.yaml"
    decks = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    decks["decks"][deck_id]["status"] = "validating"
    deck_path.write_text(yaml.safe_dump(decks), encoding="utf-8")
    before = _semantic_presentation_tree(project_root)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(replacement_position))

    with pytest.raises(RuntimeError, match="transaction commit failed"):
        complete_deck(project_root, deck_id, completion)

    assert _semantic_presentation_tree(project_root) == before
    _assert_no_transaction_orphans(project_root)


@pytest.mark.parametrize("source_kind", ["symlink", "fifo"])
def test_preview_rejects_unsafe_source_files_without_publishing_state(
    tmp_path: Path,
    source_kind: str,
) -> None:
    """Reject symlink and special preview inputs before any evidence publication.

    Args:
        tmp_path: Per-test temporary directory.
        source_kind: Unsafe source-file kind to substitute for a rendered PNG.
    """
    project_root, _, preview = _preview_ready_project(tmp_path)
    source = project_root / "renders/slide-1.png"
    before = _semantic_presentation_tree(project_root)
    source.unlink()
    if source_kind == "symlink":
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"external-bytes")
        source.symlink_to(outside)
    else:
        os.mkfifo(source)

    with pytest.raises(DraftGateError):
        register_draft_preview(project_root, preview)

    assert _semantic_presentation_tree(project_root) == before


def test_preview_uses_pre_snapshot_cas_capture_after_source_toctou(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep captured bytes authoritative when a source changes at snapshot time.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Snapshot hook used to simulate a concurrent source writer.
    """
    project_root, deck_id, preview = _preview_ready_project(tmp_path)
    source = project_root / "renders/slide-1.png"
    original = source.read_bytes()
    import presentation_evidence_producers

    original_snapshot = presentation_evidence_producers.build_snapshot

    def mutate_then_snapshot(root: Path, *, locked: bool) -> Any:
        """Change the live source after pre-snapshot CAS capture."""
        source.write_bytes(b"changed-after-capture")
        return original_snapshot(root, locked=locked)

    monkeypatch.setattr(presentation_evidence_producers, "build_snapshot", mutate_then_snapshot)
    result = register_draft_preview(project_root, preview)

    envelope = yaml.safe_load(evidence_store_path(project_root).read_text(encoding="utf-8"))["evidence"][
        result["evidence_id"]
    ]
    slide_reference = next(
        reference
        for reference in envelope["artifact_refs"]
        if reference["original_path"] == "renders/slide-1.png"
    )
    assert (project_root / slide_reference["cas_path"]).read_bytes() == original
    assert load_decks(project_root)[deck_id]["draft_preview_evidence_id"] == result["evidence_id"]


def test_concurrent_draft_approvals_serialize_to_one_current_pointer(tmp_path: Path) -> None:
    """Serialize concurrent high-level writers through the workflow lock.

    Args:
        tmp_path: Per-test temporary directory.
    """
    project_root, deck_id, decision = _approval_ready_project(tmp_path)
    approvals_before = len(load_events(project_root, "deck_approval"))
    barrier = threading.Barrier(2)

    def approve_once() -> str:
        """Attempt one simultaneous approval and classify its valid outcome."""
        barrier.wait(timeout=5)
        try:
            approve_draft(project_root, decision)
        except DraftGateError:
            return "blocked"
        return "approved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(approve_once) for _ in range(2)]
        outcomes = [future.result(timeout=10) for future in futures]

    assert outcomes.count("approved") == 1
    assert outcomes.count("blocked") == 1
    deck = load_decks(project_root)[deck_id]
    approval_id = deck["draft_approval_evidence_id"]
    assert isinstance(approval_id, str)
    assert len(load_events(project_root, "deck_approval")) == approvals_before + 1


def test_targeted_revision_clears_all_current_pointers_but_preserves_history(
    tmp_path: Path,
) -> None:
    """Clear all current v2 pointers atomically without deleting evidence history.

    Args:
        tmp_path: Per-test temporary directory.
    """
    project_root, deck_id, _, _, _, module = _complete_fixture(tmp_path)
    history_before = evidence_store_path(project_root).read_bytes()
    revision = project_root / "module-revision.yaml"
    revision.write_text(
        yaml.safe_dump(
            {
                "deck_id": deck_id,
                "subject_type": "module",
                "subject_id": module["id"],
                "requested_by": "reviewer",
                "instructions": "Retry the visual module.",
                "revision_kind": "module_retry",
            }
        ),
        encoding="utf-8",
    )

    request_targeted_revision(project_root, revision)

    deck = load_decks(project_root)[deck_id]
    assert all(
        deck[field] is None
        for field in (
            "draft_preview_evidence_id",
            "draft_approval_evidence_id",
            "completion_evidence_id",
        )
    )
    assert evidence_store_path(project_root).read_bytes() == history_before
