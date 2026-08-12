"""Anchored workflow serialization for presentation state transitions.

This module owns only the outer workflow lock.  It deliberately retains the
lock parent directory descriptor while recovery and schema checks run, leaving
state/event/CAS ordering to ``presentation_transactions``.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from presentation_evidence_workflow import require_schema_v2
from presentation_no_follow import (
    AnchoredPath,
    MissingPathError,
    NoFollowPathError,
    open_parent_no_follow,
    read_regular_siblings,
    temporary_path,
    write_bytes_at,
)
from presentation_transactions import TransactionError, WorkflowTransaction


WORKFLOW_LOCK_RELATIVE_PATH = ".research/presentations/state/workflow.lock"
_WORKFLOW_GITIGNORE_RELATIVE_PATH = ".research/presentations/.gitignore"
_WORKFLOW_GITIGNORE_CONTENT = b"state/*.lock\nstate/*.tmp\nevents/\ncache/\n"


@contextmanager
def workflow_lock(project_root: Path) -> Iterator[None]:
    """Hold one anchored workflow lock around a complete high-level action.

    Clean projects are schema-checked before this function creates the lock.
    A durable journal instead requires an already-existing regular lock, then
    recovers under that lock before schema validation resumes.

    Args:
        project_root: Existing project root containing presentation state.

    Yields:
        Nothing while the outer workflow serialization lock is held.

    Raises:
        TransactionError: If journal/sidecar traversal is unsafe or recovery
            needs a missing workflow lock.
    """
    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")
    root = project_root.resolve()
    journal_pending = _journal_preflight(root)
    if not journal_pending:
        require_schema_v2(root)
    anchored = _workflow_anchor(root, create_parents=not journal_pending)
    descriptor = _acquire_workflow_sidecar(
        anchored, create=not journal_pending
    )
    try:
        _require_current_workflow_sidecar(root, anchored, descriptor)
        if journal_pending:
            with WorkflowTransaction([], root):
                pass
        require_schema_v2(root)
        _ensure_workflow_gitignore(root)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        anchored.close()


def _require_current_workflow_sidecar(
    project_root: Path, anchored: AnchoredPath, descriptor: int
) -> None:
    """Verify a retained workflow descriptor still names the lexical sidecar.

    Args:
        project_root: Existing project root containing presentation state.
        anchored: Retained parent and workflow sidecar leaf.
        descriptor: Locked workflow sidecar descriptor.

    Raises:
        TransactionError: If a directory or sidecar replacement rebinds the
            lexical workflow path after the descriptor was acquired.
    """
    expected = os.fstat(descriptor)
    fresh = _workflow_anchor(project_root, create_parents=False)
    try:
        current = fresh.stat_leaf()
    finally:
        fresh.close()
    if (
        current is None
        or not stat.S_ISREG(current.st_mode)
        or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino)
    ):
        raise TransactionError(
            "workflow sidecar was rebound while acquiring the workflow lock"
        )


def _journal_preflight(project_root: Path) -> bool:
    """Return whether recovery material exists without creating any directory.

    Args:
        project_root: Existing project root to inspect through no-follow paths.

    Returns:
        Whether any canonical-or-fail-closed transaction journal material is
        already present.

    Raises:
        TransactionError: If the journal hierarchy cannot be inspected safely.
    """
    try:
        anchored = open_parent_no_follow(
            project_root,
            ".research/presentations/transactions/.workflow-journal-probe",
            create_parents=False,
        )
    except MissingPathError:
        return False
    except NoFollowPathError as exc:
        raise TransactionError(
            f"workflow journal preflight requires no-follow access: {exc}"
        ) from exc
    try:
        return bool(read_regular_siblings(anchored))
    except NoFollowPathError as exc:
        raise TransactionError(
            f"workflow journal preflight requires regular files: {exc}"
        ) from exc
    finally:
        anchored.close()


def _workflow_anchor(project_root: Path, *, create_parents: bool) -> AnchoredPath:
    """Open the retained parent directory for the workflow sidecar.

    Args:
        project_root: Existing project root containing presentation state.
        create_parents: Whether a clean action may create the state hierarchy.

    Returns:
        An anchored ``workflow.lock`` leaf.

    Raises:
        TransactionError: If recovery requires a missing workflow sidecar or
            any parent component is unsafe.
    """
    try:
        anchored = open_parent_no_follow(
            project_root,
            WORKFLOW_LOCK_RELATIVE_PATH,
            create_parents=create_parents,
        )
    except MissingPathError as exc:
        raise TransactionError(
            "pending transaction journal requires an existing regular workflow sidecar"
        ) from exc
    except NoFollowPathError as exc:
        raise TransactionError(
            f"workflow sidecar requires no-follow access: {exc}"
        ) from exc
    return anchored


def _acquire_workflow_sidecar(anchored: AnchoredPath, *, create: bool) -> int:
    """Open, fsync, and exclusively lock one regular no-follow workflow file.

    Args:
        anchored: Retained parent directory and ``workflow.lock`` leaf.
        create: Whether a clean action may create the previously absent leaf.

    Returns:
        Locked workflow sidecar descriptor.

    Raises:
        TransactionError: If the leaf is absent during recovery, nonregular,
            cannot be no-follow opened, or cannot be locked before timeout.
    """
    try:
        existing = anchored.stat_leaf()
    except OSError as exc:
        raise TransactionError(
            f"cannot stat workflow sidecar safely: {anchored.display_path}"
        ) from exc
    if existing is None and not create:
        raise TransactionError(
            "pending transaction journal requires an existing regular workflow sidecar"
        )
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise TransactionError(
            f"workflow sidecar must be a regular no-follow file: {anchored.display_path}"
        )
    flags = os.O_RDWR | (os.O_CREAT if create else 0)
    try:
        descriptor = anchored.open_leaf(flags, 0o666)
    except (NoFollowPathError, OSError) as exc:
        raise TransactionError(
            f"workflow sidecar must be a regular no-follow file: {anchored.display_path}"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise TransactionError(
                f"workflow sidecar must be a regular no-follow file: {anchored.display_path}"
            )
        if existing is None:
            os.fsync(descriptor)
            anchored.fsync_parent()
        _flock_with_timeout(descriptor, anchored.display_path)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _flock_with_timeout(descriptor: int, path: Path) -> None:
    """Acquire one descriptor lock using the shared presentation timeout.

    Args:
        descriptor: Open regular workflow sidecar descriptor.
        path: Diagnostic workflow sidecar path.

    Raises:
        TransactionError: If the exclusive lock cannot be acquired in time.
    """
    try:
        timeout = int(os.environ.get("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise TransactionError("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS must be an integer") from exc
    if timeout < 0:
        raise TransactionError("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS must be nonnegative")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise TransactionError(f"could not acquire workflow sidecar {path}") from exc
            if time.monotonic() >= deadline:
                raise TransactionError(
                    f"could not acquire workflow sidecar {path} within {timeout}s"
                ) from exc
            time.sleep(0.05)


def _ensure_workflow_gitignore(project_root: Path) -> None:
    """Create the workflow-owned ignore file through a retained parent FD.

    Args:
        project_root: Existing project root containing presentation state.

    Raises:
        TransactionError: If the gitignore path is unsafe or cannot be staged.
    """
    try:
        anchored = open_parent_no_follow(
            project_root,
            _WORKFLOW_GITIGNORE_RELATIVE_PATH,
            create_parents=True,
        )
    except NoFollowPathError as exc:
        raise TransactionError(
            f"workflow gitignore requires no-follow access: {exc}"
        ) from exc
    try:
        existing = anchored.stat_leaf()
        if existing is not None:
            if not stat.S_ISREG(existing.st_mode):
                raise TransactionError(
                    f"workflow gitignore must be a regular file: {anchored.display_path}"
                )
            return
        temporary = temporary_path(anchored.display_path)
        write_bytes_at(
            anchored,
            temporary.name,
            _WORKFLOW_GITIGNORE_CONTENT,
            0o666,
            exact_mode=False,
        )
        anchored.replace_leaf(temporary.name)
        anchored.fsync_parent()
    except NoFollowPathError as exc:
        raise TransactionError(
            f"workflow gitignore must be a regular no-follow file: {anchored.display_path}"
        ) from exc
    finally:
        anchored.close()
