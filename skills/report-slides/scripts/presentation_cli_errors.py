"""Structured JSON error payloads for presentation command-line entrypoints."""

from __future__ import annotations

from typing import Any

from presentation_evidence_workflow import MigrationRequiredError


def cli_error_payload(error: BaseException) -> dict[str, Any]:
    """Encode a typed presentation exception without losing migration metadata.

    Args:
        error: Exception raised by a command-line action.

    Returns:
        JSON-serializable error fields appropriate to the exception type.
    """
    if isinstance(error, MigrationRequiredError):
        return {
            "error": type(error).__name__,
            "message": str(error),
            "source_schema_version": error.source_schema_version,
            "target_schema_version": error.target_schema_version,
        }
    if all(hasattr(error, field) for field in ("predicate", "deck_id", "blockers")):
        return {
            "error": type(error).__name__,
            "predicate": getattr(error, "predicate"),
            "deck_id": getattr(error, "deck_id"),
            "blockers": getattr(error, "blockers"),
        }
    return {"error": type(error).__name__, "message": str(error)}
