"""Stable identifiers and UTC values shared by presentation workflow writers."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid


def generate_workflow_id(prefix: str, random_length: int = 6) -> str:
    """Return one sortable, collision-resistant workflow identifier.

    Args:
        prefix: Short immutable record or event category.
        random_length: Exact number of hexadecimal random characters.

    Returns:
        An identifier containing the UTC date and random suffix.

    Raises:
        ValueError: If the prefix or requested suffix length is invalid.
    """
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("workflow id prefix must be a nonempty string")
    if type(random_length) is not int or random_length < 1 or random_length > 32:
        raise ValueError("workflow id random_length must be an integer from 1 to 32")
    return f"{prefix}_{datetime.now(timezone.utc):%Y%m%d}_{uuid.uuid4().hex[:random_length]}"


def utc_now() -> str:
    """Return the current UTC time as an RFC3339 Z-suffixed string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
