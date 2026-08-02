"""Budget JSON responses and encode stateless research-log cursors."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any

DEFAULT_BUDGET = 4000
MAX_BUDGET = 8000
CHARS_PER_TOKEN = 4
CURSOR_VERSION = 1

_QUERY_CURSOR_FIELDS = frozenset({
    "version", "kind", "next_index", "directory", "query_fingerprint",
    "journal_fingerprint", "budget",
})
_CHUNK_CURSOR_FIELDS = frozenset({
    "version", "kind", "result_id", "body_fingerprint", "directory",
    "journal_fingerprint", "range_index", "budget",
})
_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")
_CURSOR_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class Page:
    """Contain one budget-safe prefix and its continuation cursor."""

    records: tuple[dict[str, object], ...]
    next_cursor: str | None
    estimated_tokens: int


@dataclass(frozen=True)
class ChunkPlan:
    """Describe exact source ranges for one oversized section body."""

    ranges: tuple[tuple[int, int], ...]


class BudgetError(ValueError):
    """Report an invalid or insufficient response budget."""

    def __init__(self, code: str, message: str, details: dict[str, object]) -> None:
        """Initialize a machine-readable budget error.

        Args:
            code: Stable code identifying the failed budget validation.
            message: Human-readable explanation of the failure.
            details: JSON-compatible diagnostic values.
        """
        super().__init__(message)
        self.code = code
        self.details = details


class CursorError(ValueError):
    """Report a malformed, mismatched, or stale opaque cursor."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize a machine-readable cursor error.

        Args:
            code: Stable code identifying the cursor validation failure.
            message: Human-readable explanation of the failure.
        """
        super().__init__(message)
        self.code = code


def serialize_json(payload: Mapping[str, Any]) -> str:
    """Serialize output exactly as the CLI writes it.

    Args:
        payload: JSON-compatible response object.

    Returns:
        Compact Unicode-preserving JSON text.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def estimate_json_tokens(payload: Mapping[str, Any]) -> int:
    """Return ceil(serialized character count divided by four).

    Args:
        payload: JSON-compatible response object.

    Returns:
        Conservative token estimate for the serialized response.
    """
    return (len(serialize_json(payload)) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def query_fingerprint(query: Mapping[str, object]) -> str:
    """Hash normalized query conditions deterministically.

    Args:
        query: Fully normalized query conditions.

    Returns:
        Lowercase SHA-256 digest of canonical compact JSON.
    """
    serialized = json.dumps(
        query, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def encode_cursor(payload: Mapping[str, object]) -> str:
    """Encode versioned JSON as unpadded URL-safe base64 text.

    Args:
        payload: Complete cursor payload to encode.

    Returns:
        Opaque URL-safe cursor text without base64 padding.
    """
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(serialized.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, object]:
    """Decode and validate the shape and version of an opaque cursor.

    Args:
        cursor: Opaque unpadded URL-safe base64 cursor text.

    Returns:
        Validated cursor fields.

    Raises:
        CursorError: The cursor is malformed or has an unsupported shape/version.
    """
    if not _CURSOR_PATTERN.fullmatch(cursor):
        raise CursorError("cursor_invalid", "Cursor must be unpadded URL-safe base64 text.")
    padded_cursor = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded_cursor.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise CursorError("cursor_invalid", "Cursor is not valid encoded JSON.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("kind"), str):
        raise CursorError("cursor_invalid", "Cursor has an invalid field set.")
    if payload["kind"] in {"types", "search"}:
        expected_fields = _QUERY_CURSOR_FIELDS
    elif payload["kind"] == "fetch_chunk":
        expected_fields = _CHUNK_CURSOR_FIELDS
    else:
        raise CursorError("cursor_invalid", "Cursor has an invalid query kind.")
    if set(payload) != expected_fields:
        raise CursorError("cursor_invalid", "Cursor has an invalid field set.")
    if payload["version"] != CURSOR_VERSION or isinstance(payload["version"], bool):
        raise CursorError("cursor_version_mismatch", "Cursor version is not supported.")
    if not isinstance(payload["directory"], str) or not payload["directory"]:
        raise CursorError("cursor_invalid", "Cursor has an invalid directory.")
    fingerprint_names = ["journal_fingerprint"]
    if payload["kind"] in {"types", "search"}:
        fingerprint_names.append("query_fingerprint")
    else:
        fingerprint_names.append("body_fingerprint")
    for fingerprint_name in fingerprint_names:
        fingerprint = payload[fingerprint_name]
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise CursorError("cursor_invalid", "Cursor has an invalid fingerprint.")
    index_name = "next_index" if payload["kind"] in {"types", "search"} else "range_index"
    if (
        not isinstance(payload[index_name], int)
        or isinstance(payload[index_name], bool)
        or payload[index_name] < 0
    ):
        raise CursorError("cursor_invalid", "Cursor has an invalid continuation index.")
    if payload["kind"] == "fetch_chunk" and (
        not isinstance(payload["result_id"], str) or not payload["result_id"]
    ):
        raise CursorError("cursor_invalid", "Cursor has an invalid result ID.")
    if (
        not isinstance(payload["budget"], int)
        or isinstance(payload["budget"], bool)
        or payload["budget"] <= 0
    ):
        raise CursorError("cursor_invalid", "Cursor has an invalid budget.")
    return payload


def plan_batches(
    item_ids: Sequence[str],
    item_response_builder: Callable[[Sequence[str]], dict[str, object]],
    budget: int,
) -> tuple[dict[str, object], ...]:
    """Greedily pack request-order IDs into independently safe fetch batches.

    Args:
        item_ids: Ordered, unique identifiers requested for full-text retrieval.
        item_response_builder: Builds the complete successful response for IDs.
        budget: Maximum estimated response tokens for every returned batch.

    Returns:
        Ordered batch dictionaries with identifiers and exact response estimates.

    Raises:
        BudgetError: The budget is invalid or an individual item cannot fit.
    """
    if budget <= 0:
        raise BudgetError(
            "budget_below_minimum", "Budget must be a positive integer.", {"budget": budget}
        )
    batches: list[dict[str, object]] = []
    current_ids: list[str] = []
    for item_id in item_ids:
        candidate_ids = [*current_ids, item_id]
        candidate_tokens = estimate_json_tokens(item_response_builder(candidate_ids))
        if candidate_tokens <= budget:
            current_ids = candidate_ids
            continue
        if not current_ids:
            raise BudgetError(
                "item_exceeds_budget",
                "A requested item exceeds the response budget.",
                {"id": item_id, "budget": budget, "estimated_tokens": candidate_tokens},
            )
        batches.append(_batch_record(current_ids, item_response_builder))
        current_ids = [item_id]
        single_tokens = estimate_json_tokens(item_response_builder(current_ids))
        if single_tokens > budget:
            raise BudgetError(
                "item_exceeds_budget",
                "A requested item exceeds the response budget.",
                {"id": item_id, "budget": budget, "estimated_tokens": single_tokens},
            )
    if current_ids:
        batches.append(_batch_record(current_ids, item_response_builder))
    return tuple(batches)


def plan_chunks(
    body: str,
    chunk_response_builder: Callable[[int, int, int, int], dict[str, object]],
    budget: int,
) -> ChunkPlan:
    """Partition a body into exact budget-safe ranges, preferring paragraphs.

    Args:
        body: Exact section body to partition without normalization.
        chunk_response_builder: Builds a complete response for one candidate range.
        budget: Maximum estimated response tokens for every chunk response.

    Returns:
        Exact contiguous body ranges that cover the supplied body once.

    Raises:
        BudgetError: Metadata cannot fit, or the budget is not positive.
    """
    if budget <= 0:
        raise BudgetError(
            "budget_below_minimum", "Budget must be a positive integer.", {"budget": budget}
        )
    if not body:
        return ChunkPlan(())
    total_hint = 1
    for _ in range(len(body) + 1):
        ranges = _plan_chunk_ranges(body, chunk_response_builder, budget, total_hint)
        actual_count = len(ranges)
        if actual_count == total_hint:
            return ChunkPlan(tuple(ranges))
        total_hint = actual_count
    raise BudgetError(
        "chunk_plan_unstable",
        "Could not create a stable chunk plan within the response budget.",
        {"budget": budget},
    )


def _batch_record(
    item_ids: Sequence[str],
    item_response_builder: Callable[[Sequence[str]], dict[str, object]],
) -> dict[str, object]:
    """Build one externally visible independently safe batch record."""
    return {
        "ids": list(item_ids),
        "estimated_tokens": estimate_json_tokens(item_response_builder(item_ids)),
    }


def _plan_chunk_ranges(
    body: str,
    chunk_response_builder: Callable[[int, int, int, int], dict[str, object]],
    budget: int,
    total_chunks: int,
) -> list[tuple[int, int]]:
    """Build ranges using one fixed total-count hypothesis."""
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(body):
        chunk_index = len(ranges)
        if estimate_json_tokens(
            chunk_response_builder(start, start, chunk_index, total_chunks)
        ) > budget:
            raise BudgetError(
                "metadata_exceeds_budget",
                "Chunk response metadata exceeds the requested budget.",
                {"budget": budget},
            )
        lower_bound = start + 1
        if estimate_json_tokens(
            chunk_response_builder(start, lower_bound, chunk_index, total_chunks)
        ) > budget:
            raise BudgetError(
                "metadata_exceeds_budget",
                "Chunk response metadata leaves no room for source text.",
                {"budget": budget},
            )
        maximum_end = _maximum_fitting_chunk_end(
            start, len(body), chunk_index, total_chunks, chunk_response_builder, budget
        )
        paragraph_start = body.rfind("\n\n", start + 1, maximum_end)
        paragraph_end = paragraph_start + 2
        end = paragraph_end if paragraph_end > start else maximum_end
        if end <= start:
            raise BudgetError(
                "chunk_plan_unstable",
                "Chunk planning failed to make forward progress.",
                {"budget": budget},
            )
        ranges.append((start, end))
        start = end
    return ranges


def _maximum_fitting_chunk_end(
    start: int,
    body_length: int,
    chunk_index: int,
    total_chunks: int,
    chunk_response_builder: Callable[[int, int, int, int], dict[str, object]],
    budget: int,
) -> int:
    """Return the furthest endpoint whose complete chunk response fits."""
    lower_bound = start + 1
    upper_bound = body_length
    best_end = start
    while lower_bound <= upper_bound:
        midpoint = (lower_bound + upper_bound) // 2
        estimated_tokens = estimate_json_tokens(
            chunk_response_builder(start, midpoint, chunk_index, total_chunks)
        )
        if estimated_tokens <= budget:
            best_end = midpoint
            lower_bound = midpoint + 1
        else:
            upper_bound = midpoint - 1
    return best_end


def paginate_records(
    records: Sequence[dict[str, object]],
    start_index: int,
    budget: int,
    response_builder: Callable[[Sequence[dict[str, object]], str | None], dict[str, object]],
    cursor_builder: Callable[[int], str],
) -> Page:
    """Return the largest non-empty record prefix whose full JSON fits.

    Args:
        records: Fully ordered records available to the query.
        start_index: Index at which this page begins.
        budget: Maximum estimated response tokens.
        response_builder: Builds the complete response for a candidate page.
        cursor_builder: Encodes a cursor that resumes at a record index.

    Returns:
        Largest contiguous fitting page and its optional continuation cursor.

    Raises:
        BudgetError: Metadata cannot fit or the requested budget is invalid.
    """
    if budget <= 0:
        raise BudgetError(
            "budget_below_minimum", "Budget must be a positive integer.", {"budget": budget}
        )
    if start_index < 0 or start_index > len(records):
        raise CursorError("cursor_invalid", "Cursor continuation index is out of range.")

    metadata_cursor = cursor_builder(start_index) if start_index < len(records) else None
    metadata_payload = response_builder((), metadata_cursor)
    metadata_tokens = estimate_json_tokens(metadata_payload)
    if metadata_tokens > budget:
        raise BudgetError(
            "metadata_exceeds_budget",
            "Response metadata exceeds the requested budget.",
            {"budget": budget, "estimated_tokens": metadata_tokens},
        )

    end_index = start_index
    best_cursor = metadata_cursor
    best_tokens = metadata_tokens
    while end_index < len(records):
        candidate_end = end_index + 1
        candidate_cursor = (
            cursor_builder(candidate_end) if candidate_end < len(records) else None
        )
        candidate_payload = response_builder(
            records[start_index:candidate_end], candidate_cursor
        )
        candidate_tokens = estimate_json_tokens(candidate_payload)
        if candidate_tokens > budget:
            break
        end_index = candidate_end
        best_cursor = candidate_cursor
        best_tokens = candidate_tokens
    if end_index == start_index and start_index < len(records):
        raise BudgetError(
            "record_exceeds_budget",
            "The next record exceeds the requested response budget.",
            {"budget": budget, "estimated_tokens": best_tokens},
        )
    return Page(tuple(records[start_index:end_index]), best_cursor, best_tokens)
