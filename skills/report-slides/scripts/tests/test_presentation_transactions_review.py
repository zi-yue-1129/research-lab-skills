"""Review-regression tests for anchored and durable workflow transactions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

import presentation_transactions as transactions
from presentation_transactions import SimulatedProcessDeath, WorkflowTransaction


def _project(tmp_path: Path) -> Path:
    """Create one project with an ordinary state target."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    target = project / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")
    return project


def test_state_directory_rebind_cannot_redirect_locked_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All ordinary reads and replacements stay on the retained parent inode."""
    project = _project(tmp_path)
    target = project / ".research/presentations/state/slides.yaml"
    state = target.parent
    detached = state.with_name("state-detached")
    replacement_bytes = b"replacement-tree"

    def rebind(_transaction: WorkflowTransaction) -> None:
        """Swap the pathname after locks and parent descriptors are retained."""
        os.rename(state, detached)
        state.mkdir()
        (state / target.name).write_bytes(replacement_bytes)

    monkeypatch.setattr(WorkflowTransaction, "_notify_locked", rebind)
    with WorkflowTransaction([target], project) as workflow:
        assert workflow.read_bytes(target) == b"original"
        workflow.stage_bytes(target, b"committed")
        workflow.commit()

    assert (detached / target.name).read_bytes() == b"committed"
    assert target.read_bytes() == replacement_bytes


def test_journal_is_durable_before_first_staged_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process death during first staging leaves recoverable preimages."""
    project = _project(tmp_path)
    target = project / ".research/presentations/state/slides.yaml"
    original_write = transactions.write_bytes_at

    def crash_on_stage(
        anchored: Any,
        leaf_name: str,
        content: bytes,
        mode: int,
        *,
        exact_mode: bool = False,
    ) -> None:
        """Crash at the first target-temp write after asserting journal durability."""
        if anchored.display_path == target and ".transaction." in leaf_name:
            journals = list(
                (project / ".research/presentations/transactions").glob("*.json")
            )
            assert journals
            raise SimulatedProcessDeath("simulated process death during staging")
        original_write(
            anchored, leaf_name, content, mode, exact_mode=exact_mode
        )

    monkeypatch.setattr(transactions, "write_bytes_at", crash_on_stage)
    with pytest.raises(SimulatedProcessDeath, match="during staging"):
        with WorkflowTransaction([target], project) as workflow:
            workflow.stage_bytes(target, b"new")

    monkeypatch.setattr(transactions, "write_bytes_at", original_write)
    with WorkflowTransaction([target], project):
        pass
    assert target.read_bytes() == b"original"
    assert not list(
        (project / ".research/presentations/transactions").glob("*.json")
    )
    assert not list(target.parent.glob("*.transaction.*.tmp"))
