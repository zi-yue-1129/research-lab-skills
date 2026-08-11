"""Crash and recovery matrix for anchored transaction-journal publication."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from presentation_transactions import SimulatedProcessDeath, TransactionError, WorkflowTransaction


def _project(tmp_path: Path) -> tuple[Path, Path]:
    """Create one project and exact ordinary transaction target."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    target = project / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")
    os.chmod(target, 0o640)
    os.utime(target, ns=(1_700_000_000_000_000_000,) * 2)
    return project, target


def _identity(path: Path) -> tuple[bytes, int, int, int]:
    """Return exact bytes, mode, mtime, and inode for one regular file."""
    metadata = path.stat()
    return path.read_bytes(), metadata.st_mode & 0o777, metadata.st_mtime_ns, metadata.st_ino


def _journal_document(project: Path, target: Path, transaction_id: str) -> bytes:
    """Encode one exact complete journal fixture with an absent mutation."""
    document = {
        "transaction_id": transaction_id,
        "paths": [{
            "path": target.relative_to(project).as_posix(), "exists": True,
            "mode": target.stat().st_mode & 0o777,
            "mtime_ns": target.stat().st_mtime_ns,
            "content": base64.b64encode(target.read_bytes()).decode("ascii"),
        }],
    }
    return json.dumps(document, sort_keys=True).encode("utf-8")


@pytest.mark.parametrize(
    "boundary",
    ["after_create", "after_write", "after_fsync", "before_rename", "after_rename"],
)
def test_initial_journal_publication_crash_recovers_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """Every publication boundary leaves a recoverable or provably clean state."""
    project, target = _project(tmp_path)
    before = _identity(target)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_JOURNAL_CRASH_AT", boundary)

    with pytest.raises(SimulatedProcessDeath, match="journal publication"):
        with WorkflowTransaction([target], project) as workflow:
            workflow.stage_bytes(target, b"new")

    monkeypatch.delenv("PRESENTATION_TRANSACTION_JOURNAL_CRASH_AT")
    with WorkflowTransaction([target], project):
        pass

    assert _identity(target) == before
    journal_dir = project / ".research/presentations/transactions"
    assert not list(journal_dir.iterdir())
    assert not list(target.parent.glob("*.transaction.*.tmp"))


def test_complete_journal_temp_without_canonical_is_promoted_and_recovered(
    tmp_path: Path,
) -> None:
    """A complete fsynced initial temp is sufficient durable recovery proof."""
    project, target = _project(tmp_path)
    before = _identity(target)
    transaction_id = "a" * 32
    journal_dir = project / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    temporary = journal_dir / f"{transaction_id}.json.tmp"
    temporary.write_bytes(_journal_document(project, target, transaction_id))
    temporary.chmod(0o600)

    with WorkflowTransaction([target], project):
        pass

    assert _identity(target) == before
    assert not list(journal_dir.iterdir())


def test_valid_rewrite_temp_is_discarded_when_canonical_journal_exists(
    tmp_path: Path,
) -> None:
    """A canonical journal remains authoritative over its validated rewrite temp."""
    project, target = _project(tmp_path)
    transaction_id = "b" * 32
    journal_dir = project / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    content = _journal_document(project, target, transaction_id)
    (journal_dir / f"{transaction_id}.json").write_bytes(content)
    temporary = journal_dir / f"{transaction_id}.json.tmp"
    temporary.write_bytes(content)
    temporary.chmod(0o600)

    with WorkflowTransaction([target], project):
        pass

    assert not list(journal_dir.iterdir())


@pytest.mark.parametrize(
    "kind", ["malformed", "malformed_unfsynced", "wrong_mode", "symlink", "fifo"]
)
def test_unsafe_journal_temp_fails_closed(
    tmp_path: Path, kind: str
) -> None:
    """Unsafe or unverifiable canonical-looking journal temps are rejected."""
    project, target = _project(tmp_path)
    transaction_id = "c" * 32
    journal_dir = project / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    temporary = journal_dir / f"{transaction_id}.json.tmp"
    if kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside")
        temporary.symlink_to(outside)
    elif kind == "fifo":
        os.mkfifo(temporary)
    else:
        temporary.write_bytes(
            b"not-json" if kind.startswith("malformed")
            else _journal_document(project, target, transaction_id)
        )
        temporary.chmod(
            0o644 if kind == "wrong_mode" else (0o400 if kind.endswith("unfsynced") else 0o600)
        )

    with pytest.raises(TransactionError, match="journal|temporary|regular|mode"):
        with WorkflowTransaction([target], project):
            pass


def test_multiple_journal_temps_are_ambiguous(tmp_path: Path) -> None:
    """More than one pending publication temp is rejected without cleanup."""
    project, target = _project(tmp_path)
    journal_dir = project / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    for transaction_id in ("d" * 32, "e" * 32):
        temporary = journal_dir / f"{transaction_id}.json.tmp"
        temporary.write_bytes(_journal_document(project, target, transaction_id))
        temporary.chmod(0o600)

    with pytest.raises(TransactionError, match="ambiguous|multiple|journal"):
        with WorkflowTransaction([target], project):
            pass


@pytest.mark.parametrize(
    "boundary",
    [
        "rewrite_after_create", "rewrite_after_write", "rewrite_after_fsync",
        "rewrite_before_rename", "rewrite_after_rename",
    ],
)
def test_later_journal_rewrite_crash_recovers_staged_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """Every post-stage journal rewrite boundary recovers without pollution."""
    project, target = _project(tmp_path)
    before = _identity(target)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_JOURNAL_CRASH_AT", boundary)

    with pytest.raises(SimulatedProcessDeath, match="journal publication"):
        with WorkflowTransaction([target], project) as workflow:
            workflow.stage_bytes(target, b"staged")

    monkeypatch.delenv("PRESENTATION_TRANSACTION_JOURNAL_CRASH_AT")
    with WorkflowTransaction([target], project):
        pass

    assert _identity(target) == before
    assert not list((project / ".research/presentations/transactions").iterdir())
    assert not list(target.parent.glob("*.transaction.*.tmp"))
