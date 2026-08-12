"""Security and concurrency regressions for evidence-v2 workflow producers."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import threading
import tempfile
from typing import Any

import pytest
import yaml

from presentation_evidence_workflow import MigrationRequiredError
from presentation_state import create_deck, set_slide_status
from presentation_transactions import (
    SimulatedProcessDeath,
    TransactionError,
    WorkflowTransaction,
)
from presentation_workflow import CompletionGateError, _workflow_lock, complete_deck
from test_presentation_evidence_workflow import _legacy_project, _tree_preimage
from test_presentation_workflow import _complete_fixture


@pytest.mark.parametrize(
    ("header_name", "content"),
    [
        ("mapping_without_marker", b"plans: {}\n"),
        ("list", b"[]\n"),
        ("scalar", b"not-a-state-document\n"),
        ("null", b"null\n"),
        ("empty", b""),
        ("malformed", b"plans: [\n"),
        ("alias_cycle", b"version: &loop {self: *loop}\nplans: {}\n"),
        ("mixed", b"version: 2\nschema_version: 1\nplans: {}\n"),
    ],
)
def test_malformed_or_nonmapping_store_header_requires_typed_migration_before_write(
    tmp_path: Path,
    header_name: str,
    content: bytes,
) -> None:
    """Reject every unsafe header before a writer creates a sidecar.

    Removing strict state-header parsing would let one malformed or nonmapping
    store fall through to ``create_deck`` and mutate the captured tree.

    Args:
        tmp_path: Per-test temporary project directory.
        header_name: Human-readable malformed-header category.
        content: Exact untrusted bytes in the plans state store.
    """
    project_root = _legacy_project(tmp_path, 2)
    plans_path = project_root / ".research/presentations/state/plans.yaml"
    plans_path.write_bytes(content)
    before = _tree_preimage(project_root)

    with pytest.raises(MigrationRequiredError) as error:
        create_deck(project_root, f"Blocked {header_name}")

    assert error.value.target_schema_version == 2
    assert _tree_preimage(project_root) == before


@pytest.mark.parametrize("unsafe_kind", ["symlink", "fifo", "directory", "socket"])
def test_workflow_lock_rejects_unsafe_sidecar_without_touching_outside_sentinel(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    """Refuse nonregular workflow sidecars without following their target.

    Replacing the no-follow lock acquisition with path-based ``open`` would
    either lock an outside sentinel or create transaction artifacts instead.

    Args:
        tmp_path: Per-test temporary project directory.
        unsafe_kind: Unsafe filesystem object substituted for workflow.lock.
    """
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    if unsafe_kind == "socket":
        temporary_directory = tempfile.TemporaryDirectory(dir="/tmp", prefix="pew-")
        project_root = _legacy_project(Path(temporary_directory.name), 2)
    else:
        project_root = _legacy_project(tmp_path, 2)
    lock_path = project_root / ".research/presentations/state/workflow.lock"
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-before")
    bound_socket: socket.socket | None = None
    if unsafe_kind == "symlink":
        lock_path.symlink_to(outside)
    elif unsafe_kind == "fifo":
        os.mkfifo(lock_path)
    elif unsafe_kind == "directory":
        lock_path.mkdir()
    else:
        bound_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            bound_socket.bind(str(lock_path))
        except PermissionError:
            bound_socket.close()
            if temporary_directory is not None:
                temporary_directory.cleanup()
            pytest.skip("sandbox forbids filesystem UNIX sockets")
    before = _tree_preimage(project_root)
    try:
        with pytest.raises(TransactionError):
            with _workflow_lock(project_root):
                pass
        assert outside.read_bytes() == b"outside-before"
        assert _tree_preimage(project_root) == before
    finally:
        if bound_socket is not None:
            bound_socket.close()
        if temporary_directory is not None:
            temporary_directory.cleanup()


def test_workflow_lock_rejects_state_directory_rebind_before_workflow_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a lexical state-directory swap after acquiring the retained lock.

    A fresh path lookup after ``workflow.lock`` is acquired can write the
    gitignore into an attacker-provided replacement directory.  The lock must
    prove its retained parent is still the current lexical workflow sidecar
    before any owned workflow write.

    Args:
        tmp_path: Per-test temporary project directory.
        monkeypatch: Lock-acquisition hook that performs the directory swap.
    """
    project_root = _legacy_project(tmp_path, 2)
    state_root = project_root / ".research/presentations/state"
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-before")
    import presentation_workflow_lock as workflow_lock_module

    original_acquire = workflow_lock_module._acquire_workflow_sidecar

    def acquire_then_rebind(*args: Any, **kwargs: Any) -> int:
        """Acquire the real lock then replace its lexical parent directory."""
        descriptor = original_acquire(*args, **kwargs)
        detached_state = tmp_path / "detached-state"
        state_root.rename(detached_state)
        state_root.mkdir()
        return descriptor

    monkeypatch.setattr(
        workflow_lock_module, "_acquire_workflow_sidecar", acquire_then_rebind
    )

    with pytest.raises(TransactionError, match="rebound|current|sidecar"):
        with _workflow_lock(project_root):
            pass

    assert outside.read_bytes() == b"outside-before"
    assert not (project_root / ".research/presentations/.gitignore").exists()


def _crash_pending_deck_transaction(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leave a real durable journal for workflow-lock recovery checks.

    Args:
        project_root: Project containing a schema-v2 deck store.
        monkeypatch: Isolated process-death injection control.
    """
    decks_path = project_root / ".research/presentations/state/decks.yaml"
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")
    with pytest.raises(SimulatedProcessDeath, match="simulated process death"):
        with WorkflowTransaction([decks_path], project_root) as transaction_handle:
            transaction_handle.stage_bytes(decks_path, decks_path.read_bytes())
            transaction_handle.commit()
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")


def test_pending_journal_does_not_create_missing_workflow_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require an existing stable workflow sidecar before journal recovery.

    A path-based workflow lock creates this sidecar before it can authenticate
    recovery, which masks a journal-plus-missing-lock tampering condition.

    Args:
        tmp_path: Per-test temporary project directory.
        monkeypatch: Isolated process-death injection control.
    """
    project_root = _legacy_project(tmp_path, 2)
    _crash_pending_deck_transaction(project_root, monkeypatch)
    lock_path = project_root / ".research/presentations/state/workflow.lock"
    assert not lock_path.exists()

    with pytest.raises(TransactionError, match="workflow|sidecar|journal"):
        with _workflow_lock(project_root):
            pass

    assert not lock_path.exists()
    assert list((project_root / ".research/presentations/transactions").glob("*.json"))


def test_existing_regular_workflow_sidecar_serializes_journal_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse an existing regular sidecar while recovering a durable journal.

    Args:
        tmp_path: Per-test temporary project directory.
        monkeypatch: Isolated process-death injection control.
    """
    project_root = _legacy_project(tmp_path, 2)
    lock_path = project_root / ".research/presentations/state/workflow.lock"
    lock_path.touch()
    inode_before = lock_path.stat().st_ino
    _crash_pending_deck_transaction(project_root, monkeypatch)

    with _workflow_lock(project_root):
        pass

    assert lock_path.stat().st_ino == inode_before
    assert not list((project_root / ".research/presentations/transactions").glob("*.json"))


def _mutate_completion_authorization(
    project_root: Path,
    deck_id: str,
    slide_id: str,
    module_id: str,
    mutation: str,
) -> None:
    """Directly model an external state replacement after completion precheck.

    Args:
        project_root: Project whose state store is replaced by the adversary.
        deck_id: Current deck identifier.
        slide_id: Current slide identifier.
        module_id: Current visual-module identifier.
        mutation: Current authorization record class to invalidate.
    """
    state_root = project_root / ".research/presentations/state"
    if mutation == "slide":
        path, top_key, record_id, updates = state_root / "slides.yaml", "slides", slide_id, {"status": "blocked"}
    elif mutation == "module":
        path, top_key, record_id, updates = state_root / "visual_modules.yaml", "visual_modules", module_id, {"status": "blocked"}
    elif mutation == "plan":
        deck = yaml.safe_load((state_root / "decks.yaml").read_text(encoding="utf-8"))["decks"][deck_id]
        path, top_key, record_id, updates = state_root / "plans.yaml", "plans", deck["current_plan_id"], {"plan_sha256": "0" * 64}
    elif mutation == "artifact":
        path = state_root / "artifacts.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        document["artifacts"].pop(next(iter(document["artifacts"])))
        path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
        return
    else:
        path, top_key, record_id, updates = state_root / "decks.yaml", "decks", deck_id, {"draft_approval_evidence_id": None}
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document[top_key][record_id].update(updates)
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("mutation", ["slide", "module", "plan", "artifact", "pointer"])
def test_completion_rechecks_every_current_authorization_after_state_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """Reject a current-record change inserted after completion precomputation.

    Calling only the pre-lock completion gate lets a stale slide, module,
    plan, artifact, or approval pointer authorize the newly committed event.

    Args:
        tmp_path: Per-test temporary project directory.
        monkeypatch: Snapshot hook used to model the post-lock adversary.
        mutation: Current authorization record class invalidated after precheck.
    """
    project_root, deck_id, _, completion, slide_id, module = _complete_fixture(tmp_path)
    deck_path = project_root / ".research/presentations/state/decks.yaml"
    decks = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    decks["decks"][deck_id]["status"] = "validating"
    deck_path.write_text(yaml.safe_dump(decks, sort_keys=True), encoding="utf-8")
    import presentation_evidence_producers as producers

    original_snapshot = producers.build_snapshot
    mutated = False

    def mutate_then_snapshot(root: Path, *, locked: bool = False) -> Any:
        """Replace one current authorization record after all target locks hold."""
        nonlocal mutated
        if locked and not mutated:
            mutated = True
            _mutate_completion_authorization(project_root, deck_id, slide_id, module["id"], mutation)
        return original_snapshot(root, locked=locked)

    monkeypatch.setattr(producers, "build_snapshot", mutate_then_snapshot)

    with pytest.raises(CompletionGateError):
        complete_deck(project_root, deck_id, completion)


def test_completion_rechecks_after_real_low_level_writer_between_precheck_and_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Block a real low-level slide update completed between high-level phases.

    Args:
        tmp_path: Per-test temporary project directory.
        monkeypatch: Source-capture barrier that permits the low-level writer.
    """
    project_root, deck_id, _, completion, slide_id, _ = _complete_fixture(tmp_path)
    deck_path = project_root / ".research/presentations/state/decks.yaml"
    decks = yaml.safe_load(deck_path.read_text(encoding="utf-8"))
    decks["decks"][deck_id]["status"] = "validating"
    deck_path.write_text(yaml.safe_dump(decks, sort_keys=True), encoding="utf-8")
    import presentation_evidence_producers as producers

    writer_started = threading.Event()
    writer_finished = threading.Event()

    def writer() -> None:
        """Perform one supported low-level transition outside the workflow lock."""
        writer_started.wait(timeout=5)
        set_slide_status(project_root, slide_id, "blocked")
        writer_finished.set()

    worker = threading.Thread(target=writer)
    worker.start()
    original_sources = producers._completion_sources

    def allow_writer(*args: Any, **kwargs: Any) -> Any:
        """Open a deterministic gap after precheck and before target locking."""
        writer_started.set()
        assert writer_finished.wait(timeout=5)
        return original_sources(*args, **kwargs)

    monkeypatch.setattr(producers, "_completion_sources", allow_writer)
    try:
        with pytest.raises(CompletionGateError):
            complete_deck(project_root, deck_id, completion)
    finally:
        worker.join(timeout=5)
    assert not worker.is_alive()
