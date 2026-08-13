"""Read-only journal admission checks used before presentation mutations."""

from __future__ import annotations

import errno
import fcntl
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from presentation_no_follow import NoFollowPathError, open_parent_no_follow
from presentation_transaction_errors import (
    TransactionError,
    TransactionRecoveryRequiredError,
)
from presentation_transaction_files import durable_journal_names


_PROCESS_GUARD = threading.RLock()
_THREAD_STATE = threading.local()


def acquire_journal_admission(project_root: Path, timeout: int) -> int:
    """Acquire the project-wide journal guard without creating a lock file.

    Args:
        project_root: Existing project root whose directory is the guard inode.
        timeout: Maximum seconds to wait for another process.

    Returns:
        Locked directory descriptor; the caller must unlock and close it.

    Raises:
        TransactionError: If the root is unsafe or the guard times out.
    """
    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")
    if type(timeout) is not int or timeout < 0:
        raise TypeError("timeout must be a non-negative int")
    try:
        anchor = open_parent_no_follow(
            project_root, ".journal-admission-anchor", create_parents=False
        )
    except NoFollowPathError as exc:
        raise TransactionError(f"journal admission root is unsafe: {exc}") from exc
    descriptor = os.dup(anchor.parent_fd)
    anchor.close()
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return descriptor
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise TransactionError(
                        "journal admission guard acquisition timed out"
                    ) from exc
                time.sleep(0.01)
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def journal_admission_guard(project_root: Path, timeout: int) -> Iterator[None]:
    """Hold a thread-reentrant, process-wide journal admission guard.

    Args:
        project_root: Existing project root serialized by the guard.
        timeout: Maximum seconds for the outermost acquisition.

    Yields:
        Nothing while journal admission and target locking are serialized.
    """
    with _PROCESS_GUARD:
        depth = getattr(_THREAD_STATE, "depth", 0)
        if depth == 0:
            _THREAD_STATE.descriptor = acquire_journal_admission(
                project_root, timeout
            )
            _THREAD_STATE.project_root = project_root.resolve()
        elif _THREAD_STATE.project_root != project_root.resolve():
            raise TransactionError(
                "nested journal admission must use the same project root"
            )
        _THREAD_STATE.depth = depth + 1
        try:
            yield
        finally:
            _THREAD_STATE.depth -= 1
            if _THREAD_STATE.depth == 0:
                descriptor = _THREAD_STATE.descriptor
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
                del _THREAD_STATE.descriptor
                del _THREAD_STATE.project_root


def incomplete_transaction_journals(
    project_root: Path, *, allow_publication_temporary: bool = False
) -> list[Path]:
    """List durable journals without changing state or following a path.

    Args:
        project_root: Existing project root containing transaction journals.
        allow_publication_temporary: Whether a lock-free preflight may defer a
            canonical in-progress journal publication until it acquires its
            target sidecar lock.

    Returns:
        Durable canonical journal paths requiring recovery.

    Raises:
        TransactionError: If journal material is malformed, unsafe, or cannot
            be deferred safely.
    """
    if type(allow_publication_temporary) is not bool:
        raise TypeError("allow_publication_temporary must be a bool")
    try:
        names = durable_journal_names(
            project_root, allow_publication_temporary=allow_publication_temporary
        )
    except (NoFollowPathError, ValueError) as exc:
        raise TransactionError(f"transaction journal preflight failed: {exc}") from exc
    directory = project_root / ".research/presentations/transactions"
    return [directory / name for name in names]


def require_transaction_recovery(
    project_root: Path, *, allow_publication_temporary: bool = False
) -> None:
    """Validate durable journals before a low-level mutation.

    Args:
        project_root: Existing project root owning transaction journals.
        allow_publication_temporary: Whether a first pre-lock probe may defer
            one canonical active journal temporary until lock acquisition.

    Raises:
        TransactionRecoveryRequiredError: If a durable journal remains.
        TransactionError: If journal material is malformed or unsafe.
    """
    if type(allow_publication_temporary) is not bool:
        raise TypeError("allow_publication_temporary must be a bool")
    journals = incomplete_transaction_journals(
        project_root, allow_publication_temporary=allow_publication_temporary
    )
    if journals:
        names = ", ".join(str(path) for path in journals)
        raise TransactionRecoveryRequiredError(
            f"transaction recovery required before write: {names}"
        )
