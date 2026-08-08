"""Deterministic lock ordering, journal recovery, and umask tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from presentation_transactions import WorkflowTransaction


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


def test_transaction_new_file_mode_honors_umask(tmp_path: Path) -> None:
    """A newly committed file follows open(0o666) and the process umask."""
    target = tmp_path / "state" / "new.yaml"
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
    first = tmp_path / "state" / "first.yaml"
    second = tmp_path / "state" / "second.yaml"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first-before")
    second.write_bytes(b"second-before")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "2")
    with pytest.raises(BaseException, match="simulated process death"):
        with WorkflowTransaction([first, second]) as transaction:
            transaction.stage_bytes(first, b"first-after")
            transaction.stage_bytes(second, b"second-after")
            transaction.commit()
    assert list((tmp_path / ".research/presentations/transactions").glob("*.json"))
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")
    with WorkflowTransaction([first, second]):
        pass
    assert first.read_bytes() == b"first-before"
    assert second.read_bytes() == b"second-before"
    assert not list((tmp_path / ".research/presentations/transactions").glob("*.json"))
