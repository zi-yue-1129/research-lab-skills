#!/usr/bin/env python3
"""Expose budgeted research-log section queries through a JSON CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from section_query_budget import (
    DEFAULT_BUDGET,
    MAX_BUDGET,
    BudgetError,
    ChunkPlan,
    CursorError,
    Page,
    decode_cursor,
    encode_cursor,
    estimate_json_tokens,
    paginate_records,
    plan_batches,
    plan_chunks,
    query_fingerprint,
    serialize_json,
)
from section_query_core import (
    JournalReadError,
    QueryWarning,
    ScanResult,
    SectionOccurrence,
    discover_types,
    manifest_record,
    normalize_heading,
    resolve_date_bounds,
    scan_journal,
    search_sections,
)

_MANIFEST_FETCH_BUDGET = 1_000


class FetchRequestError(ValueError):
    """Report invalid full-text retrieval identifiers."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize a machine-readable full-text retrieval error.

        Args:
            code: Stable code identifying the invalid fetch request.
            message: Human-readable explanation of the failure.
        """
        super().__init__(message)
        self.code = code


def main(arguments: list[str] | None = None) -> int:
    """Run a section-query command and return its process status.

    Args:
        arguments: Optional command-line arguments excluding the executable name.

    Returns:
        Zero for a successful query and one for a typed JSON error.
    """
    parser = argparse.ArgumentParser(
        description="Discover and search section types used in research logs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    types_parser = subparsers.add_parser("types", help="List discovered section types.")
    _add_pagination_arguments(types_parser)
    search_parser = subparsers.add_parser("search", help="Search sections by type and date.")
    _add_pagination_arguments(search_parser)
    search_parser.add_argument(
        "--sections", nargs="+", required=True, metavar="SECTION", help="Section types to include."
    )
    search_parser.add_argument(
        "--range", choices=("all", "7d", "30d", "90d", "year"), help="Named inclusive date range."
    )
    search_parser.add_argument("--from", dest="from_text", metavar="YYYY-MM-DD", help="Inclusive ISO lower bound.")
    search_parser.add_argument("--to", dest="to_text", metavar="YYYY-MM-DD", help="Inclusive ISO upper bound.")
    search_parser.add_argument("--today", metavar="YYYY-MM-DD", help="Reference date for reproducible ranges.")
    fetch_parser = subparsers.add_parser("fetch", help="Fetch exact full-text section occurrences.")
    _add_fetch_arguments(fetch_parser)
    parsed_arguments = parser.parse_args(arguments)
    try:
        budget = _validate_budget(parsed_arguments.budget)
        log_directory = Path(parsed_arguments.dir).resolve()
        scan = scan_journal(log_directory)
        if parsed_arguments.command == "types":
            return _run_types(scan, log_directory, budget, parsed_arguments.cursor)
        if parsed_arguments.command == "search":
            return _run_search(
                parser, parsed_arguments, scan, log_directory, budget
            )
        if parsed_arguments.command == "fetch":
            return _run_fetch(parsed_arguments, scan, log_directory, budget)
    except JournalReadError as error:
        _emit({
            "ok": False,
            "error": {"code": "invalid_utf8", "path": str(error.path), "message": str(error)},
        })
        return 1
    except BudgetError as error:
        _emit_budget_error(error)
        return 1
    except CursorError as error:
        _emit({
            "ok": False,
            "error": {"code": error.code, "message": str(error)},
        })
        return 1
    except FetchRequestError as error:
        _emit({
            "ok": False,
            "error": {"code": error.code, "message": str(error)},
        })
        return 1
    parser.error(f"Unsupported command: {parsed_arguments.command}")
    return 2


def _add_pagination_arguments(parser: argparse.ArgumentParser) -> None:
    """Add common directory, response-budget, and cursor CLI arguments.

    Args:
        parser: Subcommand parser that accepts a paginated response request.
    """
    parser.add_argument(
        "--dir", default="docs/research_log", metavar="PATH", help="Research-log directory."
    )
    parser.add_argument(
        "--budget", type=int, default=DEFAULT_BUDGET, metavar="TOKENS",
        help=f"Maximum response tokens (default {DEFAULT_BUDGET}, maximum {MAX_BUDGET}).",
    )
    parser.add_argument("--cursor", metavar="CURSOR", help="Opaque continuation cursor.")


def _add_fetch_arguments(parser: argparse.ArgumentParser) -> None:
    """Add exact-ID full-text retrieval arguments.

    Args:
        parser: Subcommand parser that accepts a full-text fetch request.
    """
    parser.add_argument(
        "--dir", default="docs/research_log", metavar="PATH", help="Research-log directory."
    )
    parser.add_argument(
        "--budget", type=int, default=DEFAULT_BUDGET, metavar="TOKENS",
        help=f"Maximum response tokens (default {DEFAULT_BUDGET}, maximum {MAX_BUDGET}).",
    )
    fetch_mode = parser.add_mutually_exclusive_group(required=True)
    fetch_mode.add_argument("--ids", nargs="+", metavar="ID", help="Exact section result IDs.")
    fetch_mode.add_argument(
        "--chunk-cursor", metavar="CURSOR", help="Opaque oversized-section continuation cursor."
    )


def _validate_budget(budget: int) -> int:
    """Return a supported positive response budget.

    Args:
        budget: Requested response token ceiling.

    Returns:
        The validated requested budget.

    Raises:
        BudgetError: The requested budget is non-positive or over the hard maximum.
    """
    if budget <= 0:
        raise BudgetError(
            "budget_below_minimum", "Budget must be a positive integer.", {"budget": budget}
        )
    if budget > MAX_BUDGET:
        raise BudgetError(
            "budget_above_maximum",
            f"Budget must not exceed {MAX_BUDGET}.",
            {"budget": budget, "maximum": MAX_BUDGET},
        )
    return budget


def _emit_budget_error(error: BudgetError) -> None:
    """Print a compact control-plane diagnostic for a budget failure.

    Successful data responses are budgeted by their complete serialized JSON.
    An insufficient requested budget cannot represent its own useful JSON error,
    so failure diagnostics retain only the stable code and machine-useful details.

    Args:
        error: Typed budget failure to expose to the command caller.
    """
    _emit({
        "ok": False,
        "error": {"code": error.code, "details": error.details},
    })


def _run_types(
    scan: ScanResult,
    log_directory: Path,
    budget: int,
    cursor_text: str | None,
) -> int:
    """Emit one budgeted canonical-first type-discovery page.

    Args:
        scan: Scan result returned by the research-log scanner.
        log_directory: Resolved research-log directory bound into cursors.
        budget: Valid response budget.
        cursor_text: Optional opaque continuation cursor.

    Returns:
        Zero after emitting the taxonomy page.
    """
    summaries = discover_types(scan)
    sections_by_key: dict[str, list[SectionOccurrence]] = {}
    for section in scan.sections:
        sections_by_key.setdefault(section.type_key, []).append(section)
    serialized_types: list[dict[str, object]] = []
    for summary in summaries:
        record = _serialize(summary)
        occurrences = sections_by_key.get(summary.key, [])
        record["occurrence_numbers"] = [
            occurrence.occurrence_number for occurrence in occurrences
        ]
        record["result_ids"] = [occurrence.result_id for occurrence in occurrences]
        serialized_types.append(record)

    conditions = {"command": "types"}
    start_index = _cursor_start_index(
        cursor_text,
        "types",
        log_directory,
        conditions,
        scan.journal_fingerprint,
        budget,
    )
    base_payload: dict[str, object] = {
        "ok": True,
        "warnings": [_serialize(warning) for warning in scan.warnings],
        "journal_fingerprint": scan.journal_fingerprint,
        "total_types": len(serialized_types),
    }
    page = _paginate_response(
        serialized_types, start_index, budget, base_payload, "types", log_directory,
        conditions, scan.journal_fingerprint, "types", "returned_types",
    )
    _emit(_build_budgeted_payload(
        base_payload, "types", "returned_types", page.records, page.next_cursor, budget
    ))
    return 0


def _run_search(
    parser: argparse.ArgumentParser,
    parsed_arguments: argparse.Namespace,
    scan: ScanResult,
    log_directory: Path,
    budget: int,
) -> int:
    """Validate, execute, and emit one budgeted section-search page.

    Args:
        parser: Parser used to report command-line validation errors.
        parsed_arguments: Parsed search command options.
        scan: Scan result returned by the research-log scanner.
        log_directory: Resolved research-log directory bound into cursors.
        budget: Valid response budget.

    Returns:
        Zero after emitting the requested manifest page.
    """
    try:
        reference_date = _resolve_reference_date(parsed_arguments.today)
        bounds = resolve_date_bounds(
            parsed_arguments.range,
            parsed_arguments.from_text,
            parsed_arguments.to_text,
            reference_date,
        )
    except ValueError as error:
        parser.error(str(error))
    normalized_types = _validate_requested_types(
        parser, tuple(parsed_arguments.sections), scan
    )
    matches = search_sections(scan, normalized_types, bounds)
    warnings = list(scan.warnings)
    warnings.extend(_undated_exclusion_warnings(scan, normalized_types, bounds.range_name))
    query: dict[str, object] = {
        "sections": list(normalized_types),
        "range": bounds.range_name,
        "from": parsed_arguments.from_text,
        "to": parsed_arguments.to_text,
        "today": bounds.reference_date.isoformat(),
        "resolved_from": bounds.start.isoformat() if bounds.start is not None else None,
        "resolved_to": bounds.end.isoformat() if bounds.end is not None else None,
    }
    conditions = {"command": "search", "query": query}
    start_index = _cursor_start_index(
        parsed_arguments.cursor,
        "search",
        log_directory,
        conditions,
        scan.journal_fingerprint,
        budget,
    )
    records = [manifest_record(section, _MANIFEST_FETCH_BUDGET) for section in matches]
    base_payload: dict[str, object] = {
        "ok": True,
        "query": query,
        "warnings": [_serialize(warning) for warning in warnings],
        "journal_fingerprint": scan.journal_fingerprint,
        "total_matches": len(records),
    }
    page = _paginate_response(
        records, start_index, budget, base_payload, "search", log_directory,
        conditions, scan.journal_fingerprint, "matches", "returned_matches",
    )
    _emit(_build_budgeted_payload(
        base_payload, "matches", "returned_matches", page.records, page.next_cursor, budget
    ))
    return 0


def _run_fetch(
    parsed_arguments: argparse.Namespace,
    scan: ScanResult,
    log_directory: Path,
    budget: int,
) -> int:
    """Fetch full source bodies atomically or serve one oversized chunk.

    Args:
        parsed_arguments: Parsed exact-ID or chunk-cursor request arguments.
        scan: Scan result returned by the research-log scanner.
        log_directory: Resolved journal directory bound into cursors.
        budget: Valid response budget.

    Returns:
        Zero after emitting a budget-safe fetch control or data response.

    Raises:
        FetchRequestError: IDs are duplicated or do not exist in the journal.
        CursorError: A chunk cursor is malformed, stale, or mismatched.
        BudgetError: Required fetch control metadata cannot fit the budget.
    """
    if parsed_arguments.chunk_cursor is not None:
        _emit(_fetch_chunk_response(
            parsed_arguments.chunk_cursor, scan, log_directory, budget
        ))
        return 0

    requested_ids = tuple(parsed_arguments.ids)
    _validate_fetch_ids(requested_ids, scan)
    sections_by_id = {section.result_id: section for section in scan.sections}
    requested_sections = tuple(sections_by_id[item_id] for item_id in requested_ids)

    def complete_response(item_ids: Sequence[str]) -> dict[str, object]:
        """Build the complete response a caller would receive for one batch."""
        batch_sections = tuple(sections_by_id[item_id] for item_id in item_ids)
        return _complete_fetch_payload(batch_sections, scan.journal_fingerprint, budget)

    complete_payload = complete_response(requested_ids)
    if estimate_json_tokens(complete_payload) <= budget:
        _emit(complete_payload)
        return 0

    for section in requested_sections:
        if estimate_json_tokens(complete_response((section.result_id,))) > budget:
            _emit(_chunk_required_payload(section, scan, log_directory, budget))
            return 0

    batches = plan_batches(requested_ids, complete_response, budget)
    item_sizes = [
        {
            "id": section.result_id,
            "estimated_tokens": estimate_json_tokens(complete_response((section.result_id,))),
        }
        for section in requested_sections
    ]
    overflow_payload = _sized_payload(lambda estimated_tokens: {
        "ok": True,
        "status": "overflow",
        "requested_ids": list(requested_ids),
        "item_sizes": item_sizes,
        "suggested_batches": list(batches),
        "journal_fingerprint": scan.journal_fingerprint,
        "budget": {"limit": budget, "estimated_tokens": estimated_tokens},
    })
    _require_budget(overflow_payload, budget)
    _emit(overflow_payload)
    return 0


def _validate_fetch_ids(item_ids: Sequence[str], scan: ScanResult) -> None:
    """Reject duplicate or unknown full-text section identifiers.

    Args:
        item_ids: Requested IDs in caller-provided order.
        scan: Current journal scan used as the authoritative ID source.

    Raises:
        FetchRequestError: The request contains duplicate or unknown IDs.
    """
    if len(set(item_ids)) != len(item_ids):
        raise FetchRequestError("duplicate_ids", "Fetch requests must not repeat an ID.")
    known_ids = {section.result_id for section in scan.sections}
    unknown_ids = [item_id for item_id in item_ids if item_id not in known_ids]
    if unknown_ids:
        raise FetchRequestError(
            "unknown_ids", f"Unknown section IDs: {', '.join(unknown_ids)}."
        )


def _complete_fetch_payload(
    sections: Sequence[SectionOccurrence], journal_fingerprint: str, budget: int
) -> dict[str, object]:
    """Build one fixed-point-sized complete full-text fetch response.

    Args:
        sections: Exact source occurrences to include in requested order.
        journal_fingerprint: Fingerprint of the scan that supplied the bodies.
        budget: Active response budget.

    Returns:
        Complete response containing every requested body and its provenance.
    """
    items = [_full_item(section, budget) for section in sections]
    requested_ids = [section.result_id for section in sections]
    return _sized_payload(lambda estimated_tokens: {
        "ok": True,
        "status": "complete",
        "requested_ids": requested_ids,
        "items": items,
        "journal_fingerprint": journal_fingerprint,
        "budget": {"limit": budget, "estimated_tokens": estimated_tokens},
    })


def _full_item(section: SectionOccurrence, budget: int) -> dict[str, object]:
    """Build a full-text item while preserving manifest provenance.

    Args:
        section: Exact source occurrence to return.
        budget: Active budget used for the provenance fit indicator.

    Returns:
        Manifest provenance augmented with the exact unmodified section body.
    """
    item = manifest_record(section, budget)
    item["body"] = section.body
    return item


def _chunk_required_payload(
    section: SectionOccurrence,
    scan: ScanResult,
    log_directory: Path,
    budget: int,
) -> dict[str, object]:
    """Build a body-free control response for one oversized section.

    Args:
        section: Oversized occurrence that requires exact chunks.
        scan: Current journal scan bound into the chunk cursor.
        log_directory: Resolved journal directory bound into the cursor.
        budget: Active response budget.

    Returns:
        Budget-safe control response with the initial chunk cursor.
    """
    body_fingerprint = _body_fingerprint(section.body)
    chunk_cursor = _encode_chunk_cursor(
        section.result_id, body_fingerprint, log_directory, scan.journal_fingerprint, 0, budget
    )
    payload = _sized_payload(lambda estimated_tokens: {
        "ok": True,
        "status": "chunk_required",
        "requested_ids": [section.result_id],
        "item": manifest_record(section, budget),
        "chunk_cursor": chunk_cursor,
        "journal_fingerprint": scan.journal_fingerprint,
        "budget": {"limit": budget, "estimated_tokens": estimated_tokens},
    })
    _require_budget(payload, budget)
    return payload


def _fetch_chunk_response(
    cursor_text: str, scan: ScanResult, log_directory: Path, budget: int
) -> dict[str, object]:
    """Validate a chunk cursor and emit its exact source substring.

    Args:
        cursor_text: Opaque chunk cursor supplied by the caller.
        scan: Current scan used to validate source freshness and resolve IDs.
        log_directory: Resolved journal directory bound into cursors.
        budget: Active response budget.

    Returns:
        One budget-safe exact body chunk and an optional continuation cursor.

    Raises:
        CursorError: Cursor binding or continuation index is not valid.
        BudgetError: Chunk response metadata cannot fit the active budget.
    """
    cursor = decode_cursor(cursor_text)
    if cursor["kind"] != "fetch_chunk":
        raise CursorError("cursor_kind_mismatch", "Cursor belongs to a different command.")
    if cursor["directory"] != str(log_directory):
        raise CursorError("cursor_directory_mismatch", "Cursor belongs to a different directory.")
    if cursor["journal_fingerprint"] != scan.journal_fingerprint:
        raise CursorError("cursor_journal_mismatch", "Journal contents changed after cursor creation.")
    if cursor["budget"] != budget:
        raise CursorError("cursor_budget_mismatch", "Cursor budget does not match the request.")
    sections_by_id = {section.result_id: section for section in scan.sections}
    result_id = cursor["result_id"]
    section = sections_by_id.get(result_id)
    if section is None:
        raise CursorError("cursor_journal_mismatch", "Cursor section no longer exists.")
    body_fingerprint = _body_fingerprint(section.body)
    if cursor["body_fingerprint"] != body_fingerprint:
        raise CursorError("cursor_body_mismatch", "Section body changed after cursor creation.")
    chunk_plan = _chunk_plan(section, scan, log_directory, budget, body_fingerprint)
    range_index = cursor["range_index"]
    if range_index >= len(chunk_plan.ranges):
        raise CursorError("cursor_invalid", "Cursor continuation index is out of range.")
    start, end = chunk_plan.ranges[range_index]
    total_chunks = len(chunk_plan.ranges)
    next_cursor = (
        _encode_chunk_cursor(
            section.result_id, body_fingerprint, log_directory, scan.journal_fingerprint,
            range_index + 1, budget,
        )
        if range_index + 1 < total_chunks else None
    )
    payload = _chunk_payload(
        section, start, end, range_index, total_chunks, next_cursor,
        scan.journal_fingerprint, budget,
    )
    _require_budget(payload, budget)
    return payload


def _chunk_plan(
    section: SectionOccurrence,
    scan: ScanResult,
    log_directory: Path,
    budget: int,
    body_fingerprint: str,
) -> ChunkPlan:
    """Plan exact source ranges using the same complete response as retrieval.

    Args:
        section: Oversized source occurrence to partition.
        scan: Current scan bound into continuation cursors.
        log_directory: Resolved journal directory bound into cursors.
        budget: Active response budget.
        body_fingerprint: SHA-256 fingerprint of the exact section body.

    Returns:
        Stable exact source ranges for the oversized body.
    """
    def build_chunk(
        start: int, end: int, chunk_index: int, total_chunks: int
    ) -> dict[str, object]:
        """Build the precise response candidate used for budget planning."""
        next_cursor = (
            _encode_chunk_cursor(
                section.result_id, body_fingerprint, log_directory, scan.journal_fingerprint,
                chunk_index + 1, budget,
            )
            if chunk_index + 1 < total_chunks else None
        )
        return _chunk_payload(
            section, start, end, chunk_index, total_chunks, next_cursor,
            scan.journal_fingerprint, budget,
        )

    return plan_chunks(section.body, build_chunk, budget)


def _chunk_payload(
    section: SectionOccurrence,
    start: int,
    end: int,
    chunk_index: int,
    total_chunks: int,
    next_cursor: str | None,
    journal_fingerprint: str,
    budget: int,
) -> dict[str, object]:
    """Build one fixed-point-sized exact source chunk response."""
    return _sized_payload(lambda estimated_tokens: {
        "ok": True,
        "status": "chunk",
        "id": section.result_id,
        "journal_fingerprint": journal_fingerprint,
        "chunk": {
            "label": f"chunk {chunk_index + 1}/{total_chunks}",
            "start": start,
            "end": end,
            "text": section.body[start:end],
        },
        "next_chunk_cursor": next_cursor,
        "budget": {"limit": budget, "estimated_tokens": estimated_tokens},
    })


def _encode_chunk_cursor(
    result_id: str,
    body_fingerprint: str,
    log_directory: Path,
    journal_fingerprint: str,
    range_index: int,
    budget: int,
) -> str:
    """Encode a cursor bound to exact content, source state, and budget."""
    return encode_cursor({
        "version": 1,
        "kind": "fetch_chunk",
        "result_id": result_id,
        "body_fingerprint": body_fingerprint,
        "directory": str(log_directory),
        "journal_fingerprint": journal_fingerprint,
        "range_index": range_index,
        "budget": budget,
    })


def _body_fingerprint(body: str) -> str:
    """Return the SHA-256 digest of exact UTF-8 section source text."""
    return sha256(body.encode("utf-8")).hexdigest()


def _sized_payload(
    payload_builder: Callable[[int], dict[str, object]],
) -> dict[str, object]:
    """Build a response whose embedded token estimate reaches a fixed point.

    Args:
        payload_builder: Callable accepting the current estimate and returning a payload.

    Returns:
        Complete JSON-compatible payload with an exact size estimate.
    """
    estimated_tokens = 0
    while True:
        payload = payload_builder(estimated_tokens)
        calculated_tokens = estimate_json_tokens(payload)
        if calculated_tokens == estimated_tokens:
            return payload
        estimated_tokens = calculated_tokens


def _require_budget(payload: Mapping[str, object], budget: int) -> None:
    """Raise a typed error when a body-free fetch control response is too large."""
    estimated_tokens = estimate_json_tokens(payload)
    if estimated_tokens > budget:
        raise BudgetError(
            "metadata_exceeds_budget",
            "Fetch response metadata exceeds the requested budget.",
            {"budget": budget, "estimated_tokens": estimated_tokens},
        )


def _cursor_start_index(
    cursor_text: str | None,
    kind: str,
    log_directory: Path,
    conditions: Mapping[str, object],
    journal_fingerprint: str,
    budget: int,
) -> int:
    """Validate an optional cursor and return its record continuation index.

    Args:
        cursor_text: Optional encoded cursor supplied by the caller.
        kind: Current query kind.
        log_directory: Resolved journal directory.
        conditions: Normalized query conditions.
        journal_fingerprint: Fingerprint of the currently scanned journal.
        budget: Current requested response budget.

    Returns:
        Zero without a cursor or the validated next record index.

    Raises:
        CursorError: The cursor does not exactly match current query conditions.
    """
    if cursor_text is None:
        return 0
    cursor = decode_cursor(cursor_text)
    if cursor["kind"] != kind:
        raise CursorError("cursor_kind_mismatch", "Cursor belongs to a different command.")
    if cursor["directory"] != str(log_directory):
        raise CursorError("cursor_directory_mismatch", "Cursor belongs to a different directory.")
    if cursor["query_fingerprint"] != query_fingerprint(conditions):
        raise CursorError("cursor_query_mismatch", "Cursor query conditions do not match.")
    if cursor["journal_fingerprint"] != journal_fingerprint:
        raise CursorError("cursor_journal_mismatch", "Journal contents changed after cursor creation.")
    if cursor["budget"] != budget:
        raise CursorError("cursor_budget_mismatch", "Cursor budget does not match the request.")
    return cursor["next_index"]


def _paginate_response(
    records: Sequence[dict[str, object]],
    start_index: int,
    budget: int,
    base_payload: Mapping[str, object],
    kind: str,
    log_directory: Path,
    conditions: Mapping[str, object],
    journal_fingerprint: str,
    record_key: str,
    returned_key: str,
) -> Page:
    """Paginate records using a complete-response builder and bound cursor.

    Args:
        records: Fully ordered response records.
        start_index: Index from which to begin this page.
        budget: Valid response budget.
        base_payload: Static response metadata.
        kind: Current query kind.
        log_directory: Resolved research-log directory.
        conditions: Normalized query conditions.
        journal_fingerprint: Fingerprint of the currently scanned journal.
        record_key: JSON field containing the record sequence.
        returned_key: JSON field containing the page record count.

    Returns:
        Budget-safe page returned by :func:`paginate_records`.
    """
    fingerprint = query_fingerprint(conditions)

    def build_cursor(next_index: int) -> str:
        """Encode a continuation bound to the active response conditions."""
        return encode_cursor({
            "version": 1,
            "kind": kind,
            "next_index": next_index,
            "directory": str(log_directory),
            "query_fingerprint": fingerprint,
            "journal_fingerprint": journal_fingerprint,
            "budget": budget,
        })

    def build_response(
        page_records: Sequence[dict[str, object]], next_cursor: str | None
    ) -> dict[str, object]:
        """Build the exact budgeted JSON response for one candidate page."""
        return _build_budgeted_payload(
            base_payload, record_key, returned_key, page_records, next_cursor, budget
        )

    return paginate_records(records, start_index, budget, build_response, build_cursor)


def _build_budgeted_payload(
    base_payload: Mapping[str, object],
    record_key: str,
    returned_key: str,
    records: Sequence[dict[str, object]],
    next_cursor: str | None,
    budget: int,
) -> dict[str, object]:
    """Build a response whose embedded estimate equals its serialized size.

    Args:
        base_payload: Static JSON response metadata.
        record_key: JSON field containing the page records.
        returned_key: JSON field containing the page record count.
        records: Records included on the page.
        next_cursor: Optional opaque continuation cursor.
        budget: Active response budget.

    Returns:
        Complete JSON-compatible response with a fixed-point size estimate.
    """
    estimated_tokens = 0
    while True:
        payload = dict(base_payload)
        payload[record_key] = list(records)
        payload[returned_key] = len(records)
        payload["next_cursor"] = next_cursor
        payload["budget"] = {"limit": budget, "estimated_tokens": estimated_tokens}
        calculated_tokens = estimate_json_tokens(payload)
        if calculated_tokens == estimated_tokens:
            return payload
        estimated_tokens = calculated_tokens


def _resolve_reference_date(today_text: str | None) -> date:
    """Return an explicit ISO date or the current local date.

    Args:
        today_text: Optional reproducible ISO reference date.

    Returns:
        The parsed supplied date or today's date when not supplied.

    Raises:
        ValueError: The supplied reference date is not valid ISO format.
    """
    if today_text is None:
        return date.today()
    try:
        return date.fromisoformat(today_text)
    except ValueError as error:
        raise ValueError("--today must be an ISO date (YYYY-MM-DD).") from error


def _validate_requested_types(
    parser: argparse.ArgumentParser,
    requested_types: tuple[str, ...],
    scan: ScanResult,
) -> tuple[str, ...]:
    """Return normalized requested names or report grouped unknown types.

    Args:
        parser: Parser used to report command-line validation errors.
        requested_types: Raw requested section type names.
        scan: Scan result used to discover current custom types.

    Returns:
        Canonical or discovered display names in request order.
    """
    summaries = discover_types(scan)
    canonical_names_by_key = {
        summary.key: summary.name for summary in summaries if summary.canonical
    }
    custom_names = {
        summary.name for summary in summaries if not summary.canonical
    }
    unknown_names: list[str] = []
    normalized_names: list[str] = []
    for requested_type in requested_types:
        _, normalized_key = normalize_heading(requested_type)
        canonical_name = canonical_names_by_key.get(normalized_key)
        if canonical_name is not None:
            resolved_name = canonical_name
        elif requested_type in custom_names:
            resolved_name = requested_type
        else:
            unknown_names.append(requested_type)
            continue
        if resolved_name not in normalized_names:
            normalized_names.append(resolved_name)
    if unknown_names:
        valid_names = ", ".join(summary.name for summary in summaries)
        parser.error(
            f"Unknown section types: {', '.join(unknown_names)}. Valid types: {valid_names}."
        )
    return tuple(normalized_names)


def _undated_exclusion_warnings(
    scan: ScanResult,
    requested_types: tuple[str, ...],
    range_name: str,
) -> tuple[QueryWarning, ...]:
    """Return one warning per matching undated log omitted by bounded search.

    Args:
        scan: Parsed research-log result.
        requested_types: Valid normalized requested type names.
        range_name: Resolved range name.

    Returns:
        Stable warnings for omitted matching undated logs.
    """
    if range_name == "all":
        return ()
    requested_keys = {normalize_heading(type_name)[1] for type_name in requested_types}
    omitted_paths = sorted({
        section.path.as_posix()
        for section in scan.sections
        if section.type_key in requested_keys and section.log_date is None
    })
    return tuple(
        QueryWarning(
            "undated_excluded",
            path,
            "Excluded from bounded search because date frontmatter is missing or invalid.",
        )
        for path in omitted_paths
    )


def _serialize(value: Any) -> dict[str, object]:
    """Convert a query dataclass into JSON-compatible primitives.

    Args:
        value: Dataclass value emitted by the query interface.

    Returns:
        JSON-compatible dataclass field mapping.
    """
    return {key: _serialize_value(item) for key, item in asdict(value).items()}


def _serialize_value(value: Any) -> object:
    """Convert date-like values nested in dataclass output to JSON values.

    Args:
        value: Potentially nested dataclass field value.

    Returns:
        JSON-compatible primitive, list, or mapping.
    """
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value


def _emit(payload: Mapping[str, Any]) -> None:
    """Print one compact Unicode-preserving JSON payload.

    Args:
        payload: JSON-compatible output response.
    """
    print(serialize_json(payload))


if __name__ == "__main__":
    raise SystemExit(main())
