"""Regression coverage for lock-free transaction journal admission."""

from __future__ import annotations

import fcntl
import errno
import os
import threading
from pathlib import Path

import pytest

import presentation_no_follow
from presentation_transaction_journal_admission import (
    acquire_journal_admission,
    journal_admission_guard,
)
from presentation_transaction_errors import TransactionError
from presentation_transaction_files import durable_journal_names


def test_prelock_admission_does_not_read_active_publication_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canonical publication temporary is classified without reading bytes."""
    project = tmp_path / "project"
    transaction_directory = project / ".research/presentations/transactions"
    transaction_directory.mkdir(parents=True)
    temporary = transaction_directory / ("a" * 32 + ".json.tmp")
    temporary.write_bytes(b"publication in progress")
    temporary.chmod(0o400)

    def reject_content_read(*_args: object, **_kwargs: object) -> object:
        """Fail if lock-free admission attempts a stable content read."""
        raise AssertionError("lock-free admission read active publication bytes")

    monkeypatch.setattr(
        presentation_no_follow,
        "read_stable_regular",
        reject_content_read,
    )

    assert durable_journal_names(
        project, allow_publication_temporary=True
    ) == ()


def test_journal_admission_waits_for_active_publisher(tmp_path: Path) -> None:
    """A competing admission cannot inspect journals until publication ends."""
    project = tmp_path / "project"
    project.mkdir()
    publisher_descriptor = acquire_journal_admission(project, 1)
    entered = threading.Event()

    def competing_admission() -> None:
        """Record entry only after the publisher releases the root guard."""
        with journal_admission_guard(project, 1):
            entered.set()

    writer = threading.Thread(target=competing_admission)
    writer.start()
    assert not entered.wait(timeout=0.05)
    fcntl.flock(publisher_descriptor, fcntl.LOCK_UN)
    os.close(publisher_descriptor)
    writer.join(timeout=2)

    assert entered.is_set()
    assert not writer.is_alive()


def test_journal_admission_wraps_unsupported_flock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unsupported directory flock fails through the typed transaction API."""
    project = tmp_path / "project"
    project.mkdir()

    def unsupported_flock(_descriptor: int, _operation: int) -> None:
        """Simulate a filesystem that rejects directory advisory locks."""
        raise OSError(errno.EOPNOTSUPP, "operation not supported")

    monkeypatch.setattr(
        "presentation_transaction_journal_admission.fcntl.flock",
        unsupported_flock,
    )

    with pytest.raises(TransactionError, match="journal admission guard failed"):
        acquire_journal_admission(project, 1)
