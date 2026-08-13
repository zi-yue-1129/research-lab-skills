"""RED matrix for Task 8 migration fix round one."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
import presentation_transactions as transactions
from presentation_contracts import contract_sha256
from presentation_transactions import TransactionError, WorkflowTransaction


SCRIPT = Path(migration.__file__).resolve()


def _project(tmp_path: Path) -> Path:
    """Create a minimal project root for migration fix-round fixtures."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _state_dir(project: Path) -> Path:
    """Return the presentation state directory."""
    return project / ".research" / "presentations" / "state"


def _write_store(project: Path, name: str, records: Any, version: int = 0) -> Path:
    """Write one versioned state fixture."""
    top_key = name.removesuffix(".yaml")
    path = _state_dir(project) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"version": version, top_key: records}, sort_keys=False), encoding="utf-8")
    return path


def _write_deck(project: Path, *, status: str = "planning") -> str:
    """Write a minimal legacy deck and return its stable ID."""
    deck_id = "deck_round1"
    _write_store(
        project,
        "decks.yaml",
        {deck_id: {"id": deck_id, "title": "Round one", "status": status,
                   "created_by": "test"}},
    )
    _write_store(project, "slides.yaml", {})
    return deck_id


def _write_event(project: Path, event: dict[str, Any]) -> Path:
    """Write one JSONL event shard."""
    path = project / ".research" / "presentations" / "events" / "2026-08-09.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return path


def _snapshot(root: Path) -> dict[str, tuple[bytes, int, int]]:
    """Capture regular non-lock files, modes, and mtimes below a scope."""
    result: dict[str, tuple[bytes, int, int]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink() and not path.name.endswith(".lock"):
            result[path.relative_to(root).as_posix()] = (
                path.read_bytes(),
                path.stat().st_mode & 0o777,
                path.stat().st_mtime_ns,
            )
    return result


def test_non_dry_migration_locks_before_parse_and_preserves_writer_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real sidecar writer cannot be overwritten by stale migration bytes."""
    project = _project(tmp_path)
    deck_id = _write_deck(project)
    target = _state_dir(project) / "decks.yaml"
    writer_document = {
        "version": 0,
        "decks": {deck_id: {"id": deck_id, "title": "writer", "status": "planning",
                            "created_by": "test"}},
    }
    writer_bytes = yaml.safe_dump(writer_document, sort_keys=False).encode("utf-8")
    writer_started = threading.Event()
    writer_done = threading.Event()
    commit_done = threading.Event()
    acquired_before_commit: list[bool] = []
    original_scope = migration._scope_paths
    original_commit = WorkflowTransaction.commit
    writer_thread_started = False

    def writer() -> None:
        """Acquire the canonical sidecar and replace the writer-owned bytes."""
        lock_path = target.with_suffix(target.suffix + ".lock")
        descriptor = os.open(str(lock_path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
        try:
            writer_started.set()
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
            acquired_before_commit.append(not commit_done.is_set())
            target.write_bytes(writer_bytes)
            target.chmod(0o640)
        finally:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            writer_done.set()

    def scope_with_writer(root: Path) -> Any:
        """Start a writer after initial scope discovery but before parsing."""
        nonlocal writer_thread_started
        result = original_scope(root)
        if not writer_thread_started:
            writer_thread_started = True
            threading.Thread(target=writer, daemon=True).start()
            assert writer_started.wait(2)
        time.sleep(0.05)
        return result

    def commit_with_marker(transaction: WorkflowTransaction) -> None:
        """Mark the durable commit boundary for writer ordering evidence."""
        original_commit(transaction)
        commit_done.set()

    monkeypatch.setattr(migration, "_scope_paths", scope_with_writer)
    monkeypatch.setattr(WorkflowTransaction, "commit", commit_with_marker)
    migration.migrate_state(project)
    assert writer_done.wait(2)
    assert acquired_before_commit
    final_document = yaml.safe_load(target.read_text(encoding="utf-8"))
    if acquired_before_commit[0]:
        assert final_document["version"] == 2
        assert final_document["decks"][deck_id]["title"] == "writer"
    else:
        assert target.read_bytes() == writer_bytes
    assert target.with_suffix(target.suffix + ".lock").is_file()


def test_eventful_target_rerun_is_noop_with_operational_entries(tmp_path: Path) -> None:
    """Eventful migrations ignore stable locks and operational directories on rerun."""
    project = _project(tmp_path)
    _write_deck(project)
    _write_event(project, {"event": "review_result", "id": "event-r1"})
    first = migration.migrate_state(project)
    before = _snapshot(project / ".research" / "presentations")
    (project / ".research" / "presentations" / "transactions").mkdir(exist_ok=True)
    second = migration.migrate_state(project)
    assert first["changed_paths"]
    assert second["changed_paths"] == []
    assert _snapshot(project / ".research" / "presentations") == before


def test_crash_recovery_with_event_shard_completes_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A process-death journal recovers an eventful migration before rerun."""
    project = _project(tmp_path)
    _write_deck(project)
    event_path = _write_event(project, {"event": "review_result", "id": "event-r1"})
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")
    with pytest.raises(BaseException, match="simulated process death"):
        migration.migrate_state(project)
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")
    report = migration.migrate_state(project)
    assert report["target_schema_version"] == 2
    assert json.loads(event_path.read_text(encoding="utf-8"))[
        "id"
    ] == "event-r1"
    assert not list((project / ".research" / "presentations" / "transactions").glob("*.json"))


def test_strict_contract_rejects_invalid_approval_document(tmp_path: Path) -> None:
    """Approval evidence must satisfy the persisted Deck Approval contract."""
    project = _project(tmp_path)
    deck_id = _write_deck(project, status="approved")
    plan = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "purpose": "Purpose",
        "audience": "Audience",
        "core_narrative": "Narrative",
        "authored_by": "planner",
        "status": "reviewed",
        "estimated_duration_minutes": 5,
        "excluded_content": [],
        "known_gaps": [],
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Title",
                "purpose": "Purpose",
                "key_takeaway": "Takeaway",
                "intended_visual_type": "none",
                "visual_rationale": "Rationale",
                "speaker_message": "Message",
                "evidence_refs": ["E1"],
                "dependencies": [],
                "open_questions": [],
            }
        ],
    }
    plan_path = project / "plans" / "strict.yaml"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=True), encoding="utf-8")
    digest = contract_sha256(plan)
    _write_store(project, "plans.yaml", {"plan-r1": {"id": "plan-r1", "deck_id": deck_id, "version": 1, "plan_path": "plans/strict.yaml", "plan_sha256": digest, "sha256": digest, "authored_by": "planner"}})
    _write_event(project, {"event": "review_result", "id": "review-r1", "subject_type": "deck", "subject_id": deck_id, "current_plan_id": "plan-r1", "current_plan_version": 1, "current_plan_sha256": digest, "reviewer_id": "reviewer", "reviewer_role": "content", "identity_verifiable": True, "status": "passed", "findings": [], "round": 1, "ts": "2026-08-09T00:00:00Z"})
    approval = {"schema_version": 1, "event": "deck_approval", "id": "approval-r1", "deck_id": deck_id, "plan_version": 1, "plan_sha256": digest, "approved_by": "reviewer", "approved_at": "2026-08-09T00:01:00Z", "approval_mode": "interactive", "decision": "revise", "identity_verifiable": True}
    _write_event(project, approval)
    decks = yaml.safe_load((_state_dir(project) / "decks.yaml").read_text(encoding="utf-8"))
    decks["decks"][deck_id].update({"current_plan_id": "plan-r1", "approved_plan_version": 1, "approved_plan_sha256": digest, "approval_id": "approval-r1", "approved_by": "reviewer", "approved_at": "2026-08-09T00:01:00Z", "approval_mode": "interactive", "identity_verifiable": True})
    (_state_dir(project) / "decks.yaml").write_text(yaml.safe_dump(decks, sort_keys=False), encoding="utf-8")
    report = migration.migrate_state(project)
    assert deck_id in report["blocked_ids"]
    assert any(
        "contract" in blocker["reason"] or "approval" in blocker["reason"]
        for blocker in report["blockers"][deck_id]
    )


def test_latest_failed_content_review_blocks_approved_deck(tmp_path: Path) -> None:
    """An older passed review cannot override the latest bound failed round."""
    project = _project(tmp_path)
    deck_id = _write_deck(project, status="approved")
    plan = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "purpose": "Purpose",
        "audience": "Audience",
        "core_narrative": "Narrative",
        "authored_by": "planner",
        "status": "reviewed",
        "estimated_duration_minutes": 5,
        "excluded_content": [],
        "known_gaps": [],
        "slides": [{
            "slide_id": "slide-01",
            "title": "Title",
            "purpose": "Purpose",
            "key_takeaway": "Takeaway",
            "intended_visual_type": "none",
            "visual_rationale": "Rationale",
            "speaker_message": "Message",
            "evidence_refs": ["E1"],
            "dependencies": [],
            "open_questions": [],
        }],
    }
    plan_path = project / "plans" / "latest-review.yaml"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=True), encoding="utf-8")
    digest = contract_sha256(plan)
    _write_store(project, "plans.yaml", {"plan-r1": {"id": "plan-r1", "deck_id": deck_id, "version": 1, "plan_path": "plans/latest-review.yaml", "plan_sha256": digest, "sha256": digest, "authored_by": "planner"}})
    _write_event(project, {"event": "review_result", "id": "review-old", "subject_type": "deck", "subject_id": deck_id, "current_plan_id": "plan-r1", "current_plan_version": 1, "current_plan_sha256": digest, "reviewer_id": "reviewer", "reviewer_role": "content", "status": "passed", "findings": [], "round": 1, "ts": "2026-08-09T00:00:00Z"})
    _write_event(project, {"event": "review_result", "id": "review-new", "subject_type": "deck", "subject_id": deck_id, "current_plan_id": "plan-r1", "current_plan_version": 1, "current_plan_sha256": digest, "reviewer_id": "reviewer", "reviewer_role": "content", "status": "failed", "findings": [{"code": "unsupported-claim"}], "round": 2, "ts": "2026-08-09T00:01:00Z"})
    decks = yaml.safe_load((_state_dir(project) / "decks.yaml").read_text(encoding="utf-8"))
    decks["decks"][deck_id].update({"current_plan_id": "plan-r1", "approved_plan_version": 1, "approved_plan_sha256": digest, "approval_id": "missing", "approved_by": "reviewer", "approved_at": "2026-08-09T00:01:00Z", "approval_mode": "interactive"})
    (_state_dir(project) / "decks.yaml").write_text(yaml.safe_dump(decks, sort_keys=False), encoding="utf-8")
    report = migration.migrate_state(project)
    assert deck_id in report["blocked_ids"]


def test_latest_review_is_selected_before_current_plan_binding(tmp_path: Path) -> None:
    """A newer stale-plan review cannot be hidden by an older current-plan pass."""
    project = _project(tmp_path)
    deck_id = _write_deck(project, status="approved")
    plan = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "purpose": "Purpose",
        "audience": "Audience",
        "core_narrative": "Narrative",
        "authored_by": "planner",
        "status": "reviewed",
        "estimated_duration_minutes": 5,
        "excluded_content": [],
        "known_gaps": [],
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Title",
                "purpose": "Purpose",
                "key_takeaway": "Takeaway",
                "intended_visual_type": "none",
                "visual_rationale": "Rationale",
                "speaker_message": "Message",
                "evidence_refs": ["E1"],
                "dependencies": [],
                "open_questions": [],
            }
        ],
    }
    plan_path = project / "plans" / "current.yaml"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=True), encoding="utf-8")
    digest = contract_sha256(plan)
    _write_store(
        project,
        "plans.yaml",
        {
            "plan-r1": {
                "id": "plan-r1",
                "deck_id": deck_id,
                "version": 1,
                "plan_path": "plans/current.yaml",
                "plan_sha256": digest,
                "sha256": digest,
                "authored_by": "planner",
            }
        },
    )
    _write_event(
        project,
        {
            "event": "review_result",
            "id": "review-current",
            "subject_type": "deck",
            "subject_id": deck_id,
            "current_plan_id": "plan-r1",
            "current_plan_version": 1,
            "current_plan_sha256": digest,
            "reviewer_id": "reviewer",
            "reviewer_role": "content",
            "identity_verifiable": True,
            "status": "passed",
            "findings": [],
            "round": 1,
            "ts": "2026-08-09T00:00:00Z",
        },
    )
    _write_event(
        project,
        {
            "event": "review_result",
            "id": "review-stale",
            "subject_type": "deck",
            "subject_id": deck_id,
            "current_plan_id": "old-plan",
            "current_plan_version": 1,
            "current_plan_sha256": "0" * 64,
            "reviewer_id": "reviewer",
            "reviewer_role": "content",
            "identity_verifiable": True,
            "status": "failed",
            "findings": [{"code": "unsupported-claim"}],
            "round": 2,
            "ts": "2026-08-09T00:01:00Z",
        },
    )
    _write_event(
        project,
        {
            "schema_version": 1,
            "event": "deck_approval",
            "id": "approval-r1",
            "deck_id": deck_id,
            "plan_version": 1,
            "plan_sha256": digest,
            "approved_by": "reviewer",
            "approved_at": "2026-08-09T00:01:00Z",
            "approval_mode": "interactive",
            "decision": "approve",
            "identity_verifiable": True,
        },
    )
    decks = yaml.safe_load((_state_dir(project) / "decks.yaml").read_text(encoding="utf-8"))
    decks["decks"][deck_id].update(
        {
            "current_plan_id": "plan-r1",
            "approved_plan_version": 1,
            "approved_plan_sha256": digest,
            "approval_id": "approval-r1",
            "approved_by": "reviewer",
            "approved_at": "2026-08-09T00:01:00Z",
            "approval_mode": "interactive",
        }
    )
    (_state_dir(project) / "decks.yaml").write_text(yaml.safe_dump(decks, sort_keys=False), encoding="utf-8")

    report = migration.migrate_state(project)

    assert deck_id in report["blocked_ids"]
    assert any(
        "content review" in blocker["reason"]
        for blocker in report["blockers"][deck_id]
    )


@pytest.mark.parametrize("status", ["producing", "draft_review", "validating", "completed"])
def test_later_status_requires_status_specific_evidence(tmp_path: Path, status: str) -> None:
    """Core approval alone cannot preserve a later production status."""
    project = _project(tmp_path)
    deck_id = _write_deck(project, status=status)
    report = migration.migrate_state(project)
    assert deck_id in report["blocked_ids"]
    assert any("status" in blocker["reason"] for blocker in report["blockers"][deck_id])


@pytest.mark.parametrize("path_value", [None, "/etc/passwd", "special-node"])
def test_present_path_like_values_fail_before_backup_or_lock(tmp_path: Path, path_value: Any) -> None:
    """Missing, absolute, and special-file paths fail before mutation."""
    project = _project(tmp_path)
    deck_id = _write_deck(project)
    if path_value == "special-node":
        os.mkfifo(project / path_value)
    _write_store(project, "artifacts.yaml", {"artifact-r1": {"id": "artifact-r1", "deck_id": deck_id, "path": path_value}})
    before = _snapshot(project / ".research" / "presentations")
    with pytest.raises(migration.MigrationError, match="path|special"):
        migration.migrate_state(project, dry_run=True)
    with pytest.raises(migration.MigrationError, match="path|special"):
        migration.migrate_state(project, dry_run=False)
    assert _snapshot(project / ".research" / "presentations") == before


def test_recursive_yaml_alias_is_structured_error(tmp_path: Path) -> None:
    """Recursive YAML aliases fail as MigrationError rather than RecursionError."""
    project = _project(tmp_path)
    path = _state_dir(project) / "decks.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("version: 0\ndecks:\n  deck-r1: &deck\n    id: deck-r1\n    status: planning\n    nested: *deck\n", encoding="utf-8")
    with pytest.raises(migration.MigrationError, match="cycle|recursive|alias"):
        migration.migrate_state(project, dry_run=True)


@pytest.mark.parametrize("error", [TransactionError("bad journal"), RuntimeError("recovery required")])
def test_cli_structures_transaction_and_recovery_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: BaseException
) -> None:
    """JSON CLI returns structured transaction/recovery errors without traceback."""
    monkeypatch.setattr(migration, "migrate_state", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    assert migration.main(["--project-root", ".", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] in {"TransactionError", "RuntimeError"}
    assert "message" in payload


def test_cli_json_argparse_error_is_structured(capsys: pytest.CaptureFixture[str]) -> None:
    """Missing required CLI arguments return JSON rather than argparse traceback."""
    result = migration.main(["--json"])
    assert result != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "ArgumentError"
    assert "message" in payload


@pytest.mark.parametrize("failure", ["backup_file", "backup_fsync", "backup_dir_fsync", "rename", "parent_fsync"])
def test_backup_failure_never_leaves_partial_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Injected backup durability failures leave source and temp/final clean."""
    project = _project(tmp_path)
    _write_deck(project)
    presentations = project / ".research" / "presentations"
    before = _snapshot(presentations)
    original_fsync_directory = migration._fsync_directory
    calls = {"directory": 0}

    if failure == "backup_file":
        monkeypatch.setattr(migration, "_backup_file", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("write")))
    elif failure == "backup_fsync":
        monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("file fsync")))
    elif failure in {"backup_dir_fsync", "parent_fsync"}:
        def fail_directory(path: Path) -> None:
            calls["directory"] += 1
            if failure == "backup_dir_fsync" or calls["directory"] == 2:
                raise OSError("directory fsync")
            original_fsync_directory(path)
        monkeypatch.setattr(migration, "_fsync_directory", fail_directory)
    elif failure == "rename":
        monkeypatch.setattr(
            migration,
            "_publish_backup_no_replace",
            lambda *_args: (_ for _ in ()).throw(OSError("rename")),
        )
    with pytest.raises(Exception):
        migration.migrate_state(project)
    assert _snapshot(presentations) == before
    assert not list(presentations.glob("state.backup-*"))
    assert not list(presentations.glob(".state.backup-*.tmp"))


def test_backup_publish_race_does_not_overwrite_existing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raced backup destination is never overwritten by publication."""
    project = _project(tmp_path)
    _write_deck(project)
    original_publish = migration._publish_backup_no_replace
    raced: list[Path] = []

    def race(temporary: Path, destination: Path) -> None:
        if destination.name.startswith("state.backup-") and not destination.exists():
            destination.write_bytes(b"existing sentinel")
            raced.append(destination)
        original_publish(temporary, destination)

    monkeypatch.setattr(migration, "_publish_backup_no_replace", race)
    with pytest.raises(Exception, match="backup|exists|overwrite"):
        migration.migrate_state(project)
    assert raced and raced[0].read_bytes() == b"existing sentinel"


@pytest.mark.parametrize("mtime_value", [None, -1, True, 2**80])
def test_journal_mtime_metadata_rejects_null_bool_negative_and_overflow(
    tmp_path: Path, mtime_value: Any
) -> None:
    """Journal mtime metadata is omitted for legacy, but invalid when present."""
    project = _project(tmp_path)
    target = _state_dir(project) / "slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    journal_dir = project / ".research" / "presentations" / "transactions"
    journal_dir.mkdir(parents=True)
    journal_id = "a" * 32
    journal = journal_dir / f"{journal_id}.json"
    entry: dict[str, Any] = {"path": ".research/presentations/state/slides.yaml", "exists": True, "mode": 0o644, "content": "YmVmb3Jl", "mtime_ns": mtime_value}
    journal.write_text(json.dumps({"transaction_id": journal_id, "paths": [entry]}), encoding="utf-8")
    with pytest.raises(TransactionError, match="mtime|metadata|journal"):
        with WorkflowTransaction([], project):
            pass


@pytest.mark.parametrize(
    ("field", "value"),
    [("content", "YmVmb3Jl"), ("mode", 0o644), ("mtime_ns", 0)],
)
def test_journal_missing_snapshot_rejects_extra_metadata(
    tmp_path: Path, field: str, value: Any
) -> None:
    """A non-existent preimage must not carry bytes, mode, or mtime metadata."""
    project = _project(tmp_path)
    target = _state_dir(project) / "slides.yaml"
    target.parent.mkdir(parents=True)
    journal_dir = project / ".research" / "presentations" / "transactions"
    journal_dir.mkdir(parents=True)
    journal_id = "c" * 32
    journal = journal_dir / f"{journal_id}.json"
    entry: dict[str, Any] = {
        "path": ".research/presentations/state/slides.yaml",
        "exists": False,
        "mode": 0,
        "content": "",
    }
    entry[field] = value
    journal.write_text(json.dumps({"transaction_id": journal_id, "paths": [entry]}), encoding="utf-8")
    with pytest.raises(TransactionError, match="metadata|snapshot|journal"):
        with WorkflowTransaction([], project):
            pass


def test_restore_snapshot_fsyncs_file_after_mtime_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restored mtime metadata is followed by an inode fsync before unlock."""
    project = _project(tmp_path)
    target = _state_dir(project) / "slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"after")
    old_mtime = target.stat().st_mtime_ns - 1_000_000
    events: list[tuple[str, str]] = []
    original_fsync = transactions.os.fsync
    original_utime = transactions.os.utime

    def tracked_fsync(descriptor: int) -> None:
        """Record whether fsync targets the restored file or its directory."""
        try:
            descriptor_path = os.readlink(f"/proc/self/fd/{descriptor}")
        except OSError:
            descriptor_path = "<unknown>"
        events.append(("fsync", descriptor_path))
        original_fsync(descriptor)

    def tracked_utime(path: Path, **kwargs: Any) -> None:
        """Record the mtime restoration boundary."""
        events.append(("utime", os.fspath(path)))
        original_utime(path, **kwargs)

    monkeypatch.setattr(transactions.os, "fsync", tracked_fsync)
    monkeypatch.setattr(transactions.os, "utime", tracked_utime)
    snapshot = transactions._FileSnapshot(True, b"before", 0o644, old_mtime)
    with WorkflowTransaction([target], project) as transaction:
        transaction._restore_snapshot(target, snapshot)

    utime_index = next(index for index, event in enumerate(events) if event[0] == "utime")
    assert any(
        index > utime_index and event[0] == "fsync" and event[1].endswith("slides.yaml")
        for index, event in enumerate(events)
    )


def test_backup_cleanup_fsyncs_parent_after_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing a published backup after parent fsync failure is durable."""
    project = _project(tmp_path)
    _write_deck(project)
    presentations = project / ".research" / "presentations"
    source = _state_dir(project) / "decks.yaml"
    calls: list[Path] = []
    original_fsync_directory = migration._fsync_directory

    def fail_once(path: Path) -> None:
        """Fail the first parent fsync and permit cleanup fsync evidence."""
        calls.append(path)
        if path == presentations and calls.count(path) == 1:
            raise OSError("publish parent fsync")
        original_fsync_directory(path)

    monkeypatch.setattr(migration, "_fsync_directory", fail_once)
    with pytest.raises(OSError, match="publish parent fsync"):
        migration._build_backup(project, {source: (source.read_bytes(), 0o644)})
    assert calls.count(presentations) >= 2
    assert not list(presentations.glob("state.backup-*"))


def test_cli_malformed_recovery_journal_is_json(tmp_path: Path) -> None:
    """Malformed recovery journals do not leak a traceback through JSON CLI."""
    project = _project(tmp_path)
    journal_dir = project / ".research" / "presentations" / "transactions"
    journal_dir.mkdir(parents=True)
    (journal_dir / ("b" * 32 + ".json")).write_text("{broken", encoding="utf-8")
    result = subprocess.run([os.fspath(os.sys.executable), os.fspath(SCRIPT), "--project-root", os.fspath(project), "--json"], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["error"] in {"TransactionError", "MigrationError"}
    assert "message" in payload
