"""Read-only journal admission checks used before presentation mutations."""

from __future__ import annotations

from pathlib import Path

from presentation_no_follow import NoFollowPathError
from presentation_transaction_errors import (
    TransactionError,
    TransactionRecoveryRequiredError,
)
from presentation_transaction_files import durable_journal_names


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
