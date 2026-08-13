"""Typed errors shared by presentation transaction implementation modules."""

from __future__ import annotations


class TransactionError(RuntimeError):
    """Raised when a multi-file commit or rollback cannot complete safely."""


class TransactionRecoveryRequiredError(TransactionError):
    """Raised when a low-level writer runs before recovery is complete."""
