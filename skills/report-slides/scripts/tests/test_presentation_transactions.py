"""Deterministic lock ordering, journal recovery, and enforcement tests."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

import presentation_events
import presentation_state
from presentation_events import append_event, events_shard_path, load_events
from presentation_state import (
    create_deck,
    create_slide,
    create_visual_module,
    load_decks,
    load_slides,
    set_deck_status,
    set_module_status,
)
from presentation_transactions import (
    SimulatedProcessDeath,
    TransactionError,
    TransactionRecoveryRequiredError,
    WorkflowTransaction,
)


def _transaction_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Return representative module, assignment, artifact, and request paths."""
    state = tmp_path / ".research/presentations/state"
    return (
        state / "visual_modules.yaml",
        state / "assignments.yaml",
        state / "artifacts.yaml",
        state / "revision_requests.yaml",
    )


def test_transaction_order_matches_nested_writer_order(tmp_path: Path) -> None:
    """Visual modules precede assignments and artifacts in every phase."""
    modules, assignments, artifacts, requests = _transaction_paths(tmp_path)
    transaction = WorkflowTransaction([artifacts, requests, assignments, modules])
    assert transaction.paths == (modules, assignments, artifacts, requests)


def test_transaction_orders_canonical_cas_target_after_event_shard(tmp_path: Path) -> None:
    """A canonical CAS object locks after an event shard in durable ordering."""
    event = tmp_path / ".research/presentations/events/2026-08-09.jsonl"
    digest = "a" * 64
    cas_object = (
        tmp_path
        / ".research/presentations/evidence/sha256"
        / digest[:2]
        / digest
    )

    transaction = WorkflowTransaction([cas_object, event], tmp_path)

    assert transaction.paths == (event, cas_object)


@pytest.mark.parametrize(
    "relative",
    [
        "decks/../plans/plan-v0001.yaml",
        "decks/deck-a/plans/plan-v0001.yaml.tmp",
        "decks/deck-a/plans/not-a-plan.yaml",
        "decks/deck-a/plans/plan-v1.yaml",
    ],
)
def test_plan_destination_allowlist_rejects_traversal_and_unexpected_names(
    tmp_path: Path, relative: str
) -> None:
    """Plan destination validation fails before sidecar or target creation."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    target = project / relative

    with pytest.raises(TransactionError, match="relative|allowed|normalized|journal"):
        WorkflowTransaction([target], project)

    assert not target.exists()
    assert not target.with_suffix(target.suffix + ".lock").exists()


@pytest.mark.parametrize("layout", ["decks", "plans"])
def test_plan_destination_allowlist_rejects_symlinked_directories(
    tmp_path: Path, layout: str
) -> None:
    """Symlinked deck/plan directories cannot redirect transaction targets."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside")
    if layout == "decks":
        (project / "decks").symlink_to(outside, target_is_directory=True)
    else:
        (project / "decks" / "deck-a").mkdir(parents=True)
        (project / "decks" / "deck-a" / "plans").symlink_to(outside, target_is_directory=True)
    target = project / "decks" / "deck-a" / "plans" / "plan-v0001.yaml"

    with pytest.raises(TransactionError, match="escapes|project|symlink"):
        WorkflowTransaction([target], project)

    assert sentinel.read_bytes() == b"outside"
    assert not (outside / "plan-v0001.yaml.lock").exists()


def test_transaction_new_file_mode_honors_umask(tmp_path: Path) -> None:
    """A newly committed file follows open(0o666) and the process umask."""
    target = tmp_path / ".research/presentations/state/visual_modules.yaml"
    previous = os.umask(0o027)
    try:
        with WorkflowTransaction([target]) as transaction:
            transaction.stage_bytes(target, b"new")
            transaction.commit()
    finally:
        os.umask(previous)
    assert target.stat().st_mode & 0o777 == 0o640


def test_transaction_journal_recovers_after_process_death(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A partial replace leaves a journal that the next transaction restores."""
    first = tmp_path / ".research/presentations/state/visual_modules.yaml"
    second = tmp_path / ".research/presentations/state/assignments.yaml"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first-before")
    second.write_bytes(b"second-before")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "2")
    with pytest.raises(BaseException, match="simulated process death"):
        with WorkflowTransaction([first, second]) as transaction:
            transaction.stage_bytes(first, b"first-after")
            transaction.stage_bytes(second, b"second-after")
            transaction.commit()
    journals = list((tmp_path / ".research/presentations/transactions").glob("*.json"))
    assert journals
    journal = json.loads(journals[0].read_text(encoding="utf-8"))
    assert [entry["path"] for entry in journal["paths"]] == [
        ".research/presentations/state/visual_modules.yaml",
        ".research/presentations/state/assignments.yaml",
    ]
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")
    with WorkflowTransaction([first, second]):
        pass
    assert first.read_bytes() == b"first-before"
    assert second.read_bytes() == b"second-before"
    assert not list((tmp_path / ".research/presentations/transactions").glob("*.json"))


def test_transaction_rollback_restores_exact_mtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An injected replacement failure restores bytes, mode, and mtime."""
    project = tmp_path / "project"
    target = project / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    target.chmod(0o640)
    original_mtime = target.stat().st_mtime_ns - 1_234_567
    os.utime(target, ns=(original_mtime, original_mtime))
    before = (target.read_bytes(), target.stat().st_mode & 0o777, target.stat().st_mtime_ns)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", "1")
    with pytest.raises(RuntimeError, match="transaction commit failed"):
        with WorkflowTransaction([target], project) as transaction:
            transaction.stage_bytes(target, b"after")
            transaction.commit()
    assert (target.read_bytes(), target.stat().st_mode & 0o777, target.stat().st_mtime_ns) == before


def test_transaction_journal_recovery_restores_exact_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process-death journal restores the original mtime on recovery."""
    project = tmp_path / "project"
    target = project / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    target.chmod(0o600)
    original_mtime = target.stat().st_mtime_ns - 2_345_678
    os.utime(target, ns=(original_mtime, original_mtime))
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")
    with pytest.raises(SimulatedProcessDeath, match="simulated process death"):
        with WorkflowTransaction([target], project) as transaction:
            transaction.stage_bytes(target, b"after")
            transaction.commit()
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")
    with WorkflowTransaction([], project):
        pass
    assert target.read_bytes() == b"before"
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.stat().st_mtime_ns == original_mtime


def _write_journal(project: Path, entries: list[dict[str, object]]) -> Path:
    """Write a crafted durable journal for recovery validation tests."""
    journal_dir = project / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True, exist_ok=True)
    transaction_id = "a" * 32
    journal = journal_dir / f"{transaction_id}.json"
    journal.write_text(
        json.dumps({"transaction_id": transaction_id, "paths": entries}),
        encoding="utf-8",
    )
    return journal


def _journal_entry(path: str, *, exists: bool = False, mode: int = 0o644) -> dict[str, object]:
    """Build one minimally encoded journal entry."""
    return {
        "path": path,
        "exists": exists,
        "mode": mode if exists else 0,
        "content": base64.b64encode(b"before").decode("ascii") if exists else "",
    }


def test_legacy_journal_without_mtime_metadata_remains_recoverable(tmp_path: Path) -> None:
    """Older journals without ``mtime_ns`` are accepted without invention."""
    target = tmp_path / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"after")
    _write_journal(
        tmp_path,
        [_journal_entry(".research/presentations/state/slides.yaml", exists=True, mode=0o644)],
    )
    with WorkflowTransaction([], tmp_path):
        pass
    assert target.read_bytes() == b"before"
    assert target.stat().st_mode & 0o777 == 0o644


def _write_malformed_journal(project: Path) -> Path:
    """Write a validly named transaction journal with malformed JSON."""
    journal_dir = project / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal = journal_dir / ("d" * 32 + ".json")
    journal.write_text("{malformed", encoding="utf-8")
    return journal


def _prepare_state_write_target(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a deck and remove its sidecar so the next write starts absent."""
    project = tmp_path / "state-project"
    project.mkdir()
    (project / ".git").mkdir()
    create_deck(project, "Sidecar guard")
    target = project / ".research/presentations/state/decks.yaml"
    sidecar = target.with_suffix(target.suffix + ".lock")
    sidecar.unlink()
    return project, target, sidecar


def _prepare_event_write_target(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create an empty event target and leave its sidecar absent."""
    project = tmp_path / "event-project"
    project.mkdir()
    (project / ".git").mkdir()
    target = events_shard_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    sidecar = target.with_suffix(target.suffix + ".lock")
    assert not target.exists()
    assert not sidecar.exists()
    return project, target, sidecar


@pytest.mark.parametrize("journal_kind", ["malformed", "unexpected"])
def test_state_write_rejects_journal_before_absent_sidecar_creation(
    tmp_path: Path, journal_kind: str
) -> None:
    """Malformed or unexpected journals fail before a YAML sidecar is created."""
    project, target, sidecar = _prepare_state_write_target(tmp_path)
    if journal_kind == "malformed":
        _write_malformed_journal(project)
    else:
        journal_dir = project / ".research/presentations/transactions"
        journal_dir.mkdir(parents=True, exist_ok=True)
        (journal_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    deck_id = next(iter(load_decks(project)))
    with pytest.raises(TransactionError, match="journal|filename|suffix|JSON|recovery required"):
        set_deck_status(project, deck_id, "content_review")

    assert not sidecar.exists()
    assert target.exists()


@pytest.mark.parametrize("journal_kind", ["malformed", "unexpected"])
def test_event_append_rejects_journal_before_absent_sidecar_creation(
    tmp_path: Path, journal_kind: str
) -> None:
    """Malformed or unexpected journals fail before an event sidecar is created."""
    project, target, sidecar = _prepare_event_write_target(tmp_path)
    if journal_kind == "malformed":
        _write_malformed_journal(project)
    else:
        journal_dir = project / ".research/presentations/transactions"
        journal_dir.mkdir(parents=True, exist_ok=True)
        (journal_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(TransactionError, match="journal|filename|suffix|JSON|recovery required"):
        append_event(project, {"event": "guarded", "id": "guarded"})

    assert not sidecar.exists()
    assert not target.exists()


def _sentinel_snapshot(path: Path) -> tuple[bytes, int, int]:
    """Capture bytes, mode, and mtime without following a sidecar symlink."""
    stat_result = path.stat()
    return path.read_bytes(), stat_result.st_mode & 0o777, stat_result.st_mtime_ns


def test_state_write_rejects_sidecar_symlink_without_touching_outside_sentinel(tmp_path: Path) -> None:
    """A YAML sidecar symlink cannot redirect locking to an outside inode."""
    project, target, sidecar = _prepare_state_write_target(tmp_path)
    outside = tmp_path / "outside-state-sentinel"
    outside.write_bytes(b"state-sentinel")
    outside.chmod(0o640)
    before = _sentinel_snapshot(outside)
    sidecar.symlink_to(outside)
    link_target = os.readlink(sidecar)

    deck_id = next(iter(load_decks(project)))
    with pytest.raises(TransactionError, match="sidecar|symlink|regular"):
        set_deck_status(project, deck_id, "content_review")

    assert sidecar.is_symlink()
    assert os.readlink(sidecar) == link_target
    assert _sentinel_snapshot(outside) == before
    assert target.exists()


def test_event_append_rejects_sidecar_symlink_without_touching_outside_sentinel(tmp_path: Path) -> None:
    """An event sidecar symlink cannot redirect locking to an outside inode."""
    project, target, sidecar = _prepare_event_write_target(tmp_path)
    outside = tmp_path / "outside-event-sentinel"
    outside.write_bytes(b"event-sentinel")
    outside.chmod(0o600)
    before = _sentinel_snapshot(outside)
    sidecar.symlink_to(outside)
    link_target = os.readlink(sidecar)

    with pytest.raises(TransactionError, match="sidecar|symlink|regular"):
        append_event(project, {"event": "guarded", "id": "guarded"})

    assert sidecar.is_symlink()
    assert os.readlink(sidecar) == link_target
    assert _sentinel_snapshot(outside) == before
    assert not target.exists()


def test_state_write_fails_closed_when_no_follow_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A state writer refuses mutation when the platform lacks ``O_NOFOLLOW``."""
    project = tmp_path / "state-no-follow-project"
    project.mkdir()
    (project / ".git").mkdir()
    deck = create_deck(project, "No-follow guard")
    target = project / ".research/presentations/state/decks.yaml"
    sidecar = target.with_suffix(target.suffix + ".lock")
    outside = tmp_path / "outside-state-no-follow-sentinel"
    outside.write_bytes(b"outside-state-sentinel")
    before_target = _sentinel_snapshot(target)
    before_sidecar = _sentinel_snapshot(sidecar)
    before_outside = _sentinel_snapshot(outside)

    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    with pytest.raises(TransactionError, match="O_NOFOLLOW"):
        set_deck_status(project, deck["id"], "content_review")

    assert _sentinel_snapshot(target) == before_target
    assert _sentinel_snapshot(sidecar) == before_sidecar
    assert _sentinel_snapshot(outside) == before_outside


def test_event_append_fails_closed_when_no_follow_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An event writer refuses mutation when the platform lacks ``O_NOFOLLOW``."""
    project = tmp_path / "event-no-follow-project"
    project.mkdir()
    (project / ".git").mkdir()
    target = events_shard_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'{"event":"before"}\n')
    sidecar = target.with_suffix(target.suffix + ".lock")
    sidecar.touch()
    outside = tmp_path / "outside-event-no-follow-sentinel"
    outside.write_bytes(b"outside-event-sentinel")
    before_target = _sentinel_snapshot(target)
    before_sidecar = _sentinel_snapshot(sidecar)
    before_outside = _sentinel_snapshot(outside)

    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    with pytest.raises(TransactionError, match="O_NOFOLLOW"):
        append_event(project, {"event": "guarded", "id": "guarded"})

    assert _sentinel_snapshot(target) == before_target
    assert _sentinel_snapshot(sidecar) == before_sidecar
    assert _sentinel_snapshot(outside) == before_outside


def test_state_write_rechecks_journal_after_lock_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A journal appearing during lock acquisition blocks YAML mutation."""
    project, target, sidecar = _prepare_state_write_target(tmp_path)
    sidecar.touch()
    before = target.read_bytes()
    deck_id = next(iter(load_decks(project)))
    original_flock = presentation_state.fcntl.flock
    injected = False

    def flock_with_pending_journal(descriptor: int, operation: int) -> None:
        """Publish a valid journal immediately before the first exclusive flock."""
        nonlocal injected
        if operation & presentation_state.fcntl.LOCK_EX and not injected:
            _write_journal(project, [_journal_entry(".research/presentations/state/decks.yaml")])
            injected = True
        original_flock(descriptor, operation)

    monkeypatch.setattr(presentation_state.fcntl, "flock", flock_with_pending_journal)
    with pytest.raises(TransactionRecoveryRequiredError, match="recovery required"):
        set_deck_status(project, deck_id, "content_review")

    assert target.read_bytes() == before
    assert sidecar.exists()


def test_event_append_rechecks_journal_after_lock_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A journal appearing during lock acquisition blocks event mutation."""
    project, target, sidecar = _prepare_event_write_target(tmp_path)
    sidecar.touch()
    original_flock = presentation_events.fcntl.flock
    injected = False

    def flock_with_pending_journal(descriptor: int, operation: int) -> None:
        """Publish a valid journal immediately before the first exclusive flock."""
        nonlocal injected
        if operation & presentation_events.fcntl.LOCK_EX and not injected:
            _write_journal(project, [_journal_entry(".research/presentations/events/" + target.name)])
            injected = True
        original_flock(descriptor, operation)

    monkeypatch.setattr(presentation_events.fcntl, "flock", flock_with_pending_journal)
    with pytest.raises(TransactionRecoveryRequiredError, match="recovery required"):
        append_event(project, {"event": "guarded", "id": "guarded"})

    assert not target.exists()
    assert sidecar.exists()


@pytest.mark.parametrize(
    "journal_path",
    [
        "../outside.txt",
        "/tmp/outside.txt",
        "./.research/presentations/state/slides.yaml",
        ".research//presentations/state/slides.yaml",
        ".research/presentations/state/../slides.yaml",
        ".research/presentations/state/workflow.lock",
        ".research/presentations/transactions/evil.json",
        ".research/presentations/state/not-a-store.yaml",
        ".research/presentations/events/2026-08-08.jsonl.tmp",
        ".research/presentations/events/not-a-day.jsonl",
        ".research/presentations/state",
    ],
)
def test_crafted_journal_paths_fail_closed_without_outside_mutation(
    tmp_path: Path, journal_path: str
) -> None:
    """Malformed or unallowlisted journal paths cannot escape the project."""
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"sentinel")
    _write_journal(tmp_path, [_journal_entry(journal_path)])

    with pytest.raises(TransactionError, match="journal|path|allow|relative|normalized"):
        with WorkflowTransaction([], tmp_path):
            pass

    assert outside.read_bytes() == b"sentinel"
    assert not (outside.parent / "outside.txt.lock").exists()


@pytest.mark.parametrize("mode", [-1, 0o1000, 0o7777, True])
def test_crafted_journal_rejects_non_permission_modes(tmp_path: Path, mode: int) -> None:
    """Recovery accepts only ordinary permission-bit modes."""
    _write_journal(
        tmp_path,
        [_journal_entry(".research/presentations/state/slides.yaml", exists=True, mode=mode)],
    )

    with pytest.raises(TransactionError, match="mode|metadata|journal"):
        with WorkflowTransaction([], tmp_path):
            pass


def test_crafted_journal_rejects_symlink_escape_without_touching_target(tmp_path: Path) -> None:
    """An allowlisted name cannot resolve through a symlink outside the project."""
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_bytes(b"sentinel")
    state = tmp_path / ".research/presentations/state"
    state.mkdir(parents=True)
    target = state / "slides.yaml"
    target.symlink_to(outside)
    _write_journal(tmp_path, [_journal_entry(".research/presentations/state/slides.yaml")])

    with pytest.raises(TransactionError, match="symlink|project|path|journal"):
        with WorkflowTransaction([], tmp_path):
            pass

    assert outside.read_bytes() == b"sentinel"
    assert target.is_symlink()


def test_low_level_state_and_event_writes_require_journal_recovery(tmp_path: Path) -> None:
    """Pending durable journals block every low-level state/event mutation."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    deck = create_deck(project, "Guard")
    slide = create_slide(project, deck["id"], "slide-01", "Guard")
    module = create_visual_module(project, slide["id"], "module", "architecture")
    state_path = project / ".research/presentations/state/visual_modules.yaml"
    state_before = state_path.read_bytes()
    event_path = events_shard_path(project, datetime.now(timezone.utc))
    _write_journal(
        project,
        [
            _journal_entry(
                ".research/presentations/state/visual_modules.yaml",
                exists=True,
                mode=state_path.stat().st_mode & 0o777,
            ),
            _journal_entry(
                ".research/presentations/events/" + event_path.name,
                exists=False,
            ),
        ],
    )

    with pytest.raises(TransactionRecoveryRequiredError, match="recovery required"):
        set_module_status(project, module["id"], "ready")
    with pytest.raises(TransactionRecoveryRequiredError, match="recovery required"):
        append_event(project, {"event": "guarded", "id": "guarded"})

    assert state_path.read_bytes() == state_before
    assert not event_path.exists()


def test_crash_split_state_blocks_writes_then_workflow_recovers_exact_preimages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first-replacement crash leaves a split state until workflow recovery."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    deck = create_deck(project, "Crash")
    slide = create_slide(project, deck["id"], "slide-01", "Crash")
    module = create_visual_module(project, slide["id"], "module", "architecture")
    first = project / ".research/presentations/state/visual_modules.yaml"
    second = events_shard_path(project, datetime.now(timezone.utc))
    first_before = first.read_bytes()
    first_mode = first.stat().st_mode & 0o777
    second_mode = 0o640
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")
    with pytest.raises(SimulatedProcessDeath, match="simulated process death"):
        with WorkflowTransaction([first, second], project) as transaction:
            transaction.stage_bytes(first, b"first-after")
            transaction.stage_bytes(second, b"second-after", mode=second_mode)
            transaction.commit()
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")

    assert first.read_bytes() == b"first-after"
    assert not second.exists()  # The first visible replacement split the transaction.
    assert list((project / ".research/presentations/transactions").glob("*.json"))
    assert load_slides(project)[slide["id"]]["status"] == "planned"
    from presentation_state import query

    assert any(blocker["reason"] == "incomplete_transaction" for blocker in query(project, deck["id"])["blockers"])

    with pytest.raises(TransactionRecoveryRequiredError, match="recovery required"):
        set_module_status(project, module["id"], "ready")
    with pytest.raises(RuntimeError, match="recovery"):
        from presentation_gates import assert_production_allowed

        assert_production_allowed(project, deck["id"])

    from presentation_workflow import _workflow_lock

    with _workflow_lock(project):
        pass
    assert first.read_bytes() == first_before
    assert not second.exists()
    assert (first.stat().st_mode & 0o777) == first_mode
    assert not list((project / ".research/presentations/transactions").glob("*.json"))

    set_module_status(project, module["id"], "ready")
    append_event(project, {"event": "recovered", "id": "recovered"})


def test_non_directory_transaction_path_fails_before_target_lock(tmp_path: Path) -> None:
    """A transactions path that is a file blocks before any target lock."""
    target = tmp_path / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"target-before")
    journal_path = tmp_path / ".research/presentations/transactions"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_bytes(b"not-a-directory")

    with pytest.raises(TransactionError, match="journal|directory"):
        with WorkflowTransaction([target], tmp_path):
            pass

    assert target.read_bytes() == b"target-before"
    assert not target.with_suffix(target.suffix + ".lock").exists()


@pytest.mark.parametrize(
    "entry_name",
    [
        "unexpected.txt",
        "a" * 32 + ".json.tmp",
        "A" * 32 + ".json",
        "a" * 31 + ".json",
        "g" * 32 + ".json",
    ],
)
def test_unexpected_journal_children_fail_before_target_lock(
    tmp_path: Path, entry_name: str
) -> None:
    """Every unexpected journal child is rejected rather than ignored."""
    target = tmp_path / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"target-before")
    journal_dir = tmp_path / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    (journal_dir / entry_name).write_text("unexpected", encoding="utf-8")

    with pytest.raises(TransactionError, match="journal|filename|regular|directory|suffix"):
        with WorkflowTransaction([target], tmp_path):
            pass

    assert target.read_bytes() == b"target-before"
    assert not target.with_suffix(target.suffix + ".lock").exists()
    assert (journal_dir / entry_name).read_text(encoding="utf-8") == "unexpected"


def test_journal_subdirectory_fails_before_target_lock(tmp_path: Path) -> None:
    """A subdirectory in the journal directory cannot be skipped."""
    target = tmp_path / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"target-before")
    journal_dir = tmp_path / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    child = journal_dir / ("b" * 32 + ".json")
    child.mkdir()

    with pytest.raises(TransactionError, match="journal|regular|directory"):
        with WorkflowTransaction([target], tmp_path):
            pass

    assert target.read_bytes() == b"target-before"
    assert child.is_dir()
    assert not target.with_suffix(target.suffix + ".lock").exists()


def test_journal_symlink_fails_before_target_lock(tmp_path: Path) -> None:
    """A symlink journal child is rejected even when its name is valid."""
    target = tmp_path / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"target-before")
    journal_dir = tmp_path / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    outside = tmp_path / "outside-journal.json"
    outside.write_text("outside", encoding="utf-8")
    child = journal_dir / ("c" * 32 + ".json")
    child.symlink_to(outside)

    with pytest.raises(TransactionError, match="journal|symlink|regular"):
        with WorkflowTransaction([target], tmp_path):
            pass

    assert target.read_bytes() == b"target-before"
    assert child.is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside"
    assert not target.with_suffix(target.suffix + ".lock").exists()


def test_journal_transaction_id_must_match_filename_stem(tmp_path: Path) -> None:
    """A valid journal filename cannot carry a different transaction ID."""
    journal = _write_journal(tmp_path, [_journal_entry(".research/presentations/state/slides.yaml")])
    document = json.loads(journal.read_text(encoding="utf-8"))
    document["transaction_id"] = "b" * 32
    journal.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(TransactionError, match="transaction_id|journal"):
        with WorkflowTransaction([], tmp_path):
            pass


def test_unexpected_journal_entry_blocks_query_gate_and_low_level_writer(tmp_path: Path) -> None:
    """An ignored-looking journal child cannot bypass any workflow guard."""
    from presentation_gates import ProductionGateError, assert_production_allowed
    from presentation_state import query, set_deck_status

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    deck = create_deck(project, "Malformed journal")
    decks_path = project / ".research/presentations/state/decks.yaml"
    decks_before = decks_path.read_bytes()
    journal_dir = project / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    unexpected = journal_dir / "ignored.json.tmp"
    unexpected.write_bytes(b"unexpected")

    with pytest.raises(TransactionError, match="journal|filename|suffix"):
        query(project, deck["id"])
    with pytest.raises(ProductionGateError, match="journal|recovery"):
        assert_production_allowed(project, deck["id"])
    with pytest.raises(TransactionError, match="journal|filename|suffix"):
        set_deck_status(project, deck["id"], "content_review")

    assert decks_path.read_bytes() == decks_before
    assert unexpected.read_bytes() == b"unexpected"


def test_real_three_target_crash_blocks_writes_and_recovers_exact_preimages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A BaseException after two replaces leaves a real split journal to recover."""
    from presentation_gates import ProductionGateError, assert_production_allowed
    from presentation_state import query, set_deck_status

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    deck = create_deck(project, "Three targets")

    state_dir = project / ".research/presentations/state"
    assignments = state_dir / "assignments.yaml"
    artifacts = state_dir / "artifacts.yaml"
    revision_requests = state_dir / "revision_requests.yaml"
    assert not assignments.exists()
    artifacts_before = b"artifacts-before"
    revisions_before = b"revisions-before"
    artifacts.write_bytes(artifacts_before)
    revision_requests.write_bytes(revisions_before)
    artifacts.chmod(0o640)
    revision_requests.chmod(0o600)
    artifacts_mode = artifacts.stat().st_mode & 0o777
    revisions_mode = revision_requests.stat().st_mode & 0o777

    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "2")
    with pytest.raises(BaseException, match="simulated process death"):
        with WorkflowTransaction([assignments, artifacts, revision_requests], project) as transaction:
            transaction.stage_bytes(assignments, b"assignments-created", mode=0o600)
            transaction.stage_bytes(artifacts, b"artifacts-after", mode=0o644)
            transaction.stage_bytes(revision_requests, b"revisions-after", mode=0o644)
            transaction.commit()
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")

    assert assignments.read_bytes() == b"assignments-created"
    assert artifacts.read_bytes() == b"artifacts-after"
    assert revision_requests.read_bytes() == revisions_before
    assert (artifacts.stat().st_mode & 0o777) == 0o644
    assert (revision_requests.stat().st_mode & 0o777) == revisions_mode
    journals = list((project / ".research/presentations/transactions").iterdir())
    assert len(journals) == 1
    assert query(project, deck["id"])["blockers"][0]["reason"] == "incomplete_transaction"
    with pytest.raises(ProductionGateError, match="incomplete_transaction|recovery"):
        assert_production_allowed(project, deck["id"])

    decks_path = project / ".research/presentations/state/decks.yaml"
    decks_before = decks_path.read_bytes()
    event_path = events_shard_path(project, datetime.now(timezone.utc))
    event_before_exists = event_path.exists()
    event_before = event_path.read_bytes() if event_before_exists else b""
    with pytest.raises(TransactionRecoveryRequiredError, match="recovery required"):
        set_deck_status(project, deck["id"], "content_review")
    with pytest.raises(TransactionRecoveryRequiredError, match="recovery required"):
        append_event(project, {"event": "blocked", "id": "blocked"})
    assert decks_path.read_bytes() == decks_before
    assert event_path.exists() is event_before_exists
    if event_before_exists:
        assert event_path.read_bytes() == event_before

    with WorkflowTransaction([], project):
        pass
    assert not assignments.exists()
    assert artifacts.read_bytes() == artifacts_before
    assert revision_requests.read_bytes() == revisions_before
    assert (artifacts.stat().st_mode & 0o777) == artifacts_mode
    assert (revision_requests.stat().st_mode & 0o777) == revisions_mode
    assert not list((project / ".research/presentations/transactions").iterdir())

    set_deck_status(project, deck["id"], "content_review")
    append_event(project, {"event": "recovered", "id": "recovered"})
    assert load_decks(project)[deck["id"]]["status"] == "content_review"
    assert load_events(project, "recovered") == [{"event": "recovered", "id": "recovered"}]
