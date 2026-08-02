"""Build atomic full-text and chunked research-log fetch responses."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
from pathlib import Path

from section_query_budget import (
    BudgetError,
    ChunkPlan,
    CursorError,
    decode_cursor,
    encode_cursor,
    estimate_json_tokens,
    plan_batches,
    plan_chunks,
)
from section_query_core import (
    QueryInputError,
    ScanResult,
    SectionOccurrence,
    manifest_record,
)


def build_fetch_response(
    item_ids: Sequence[str] | None,
    chunk_cursor: str | None,
    scan: ScanResult,
    log_directory: Path,
    budget: int,
) -> dict[str, object]:
    """Build one budget-safe atomic fetch or exact chunk response.

    Args:
        item_ids: Exact result IDs requested in caller-provided order.
        chunk_cursor: Optional oversized-section continuation cursor.
        scan: Current journal scan used to resolve IDs and validate freshness.
        log_directory: Resolved journal directory bound into cursors.
        budget: Active response token budget.

    Returns:
        Complete, overflow, chunk-required, or exact chunk response.

    Raises:
        QueryInputError: IDs are absent, duplicated, or unknown.
        CursorError: A chunk cursor is malformed, stale, or mismatched.
        BudgetError: Required control metadata cannot fit the budget.
    """
    if chunk_cursor is not None:
        return _fetch_chunk_response(chunk_cursor, scan, log_directory, budget)
    if item_ids is None:
        raise QueryInputError("invalid_arguments", "Fetch requires exact result IDs.")

    requested_ids = tuple(item_ids)
    _validate_fetch_ids(requested_ids, scan)
    sections_by_id = {section.result_id: section for section in scan.sections}
    requested_sections = tuple(sections_by_id[item_id] for item_id in requested_ids)

    def complete_response(batch_ids: Sequence[str]) -> dict[str, object]:
        """Build the complete response a caller would receive for one batch."""
        batch_sections = tuple(sections_by_id[item_id] for item_id in batch_ids)
        return _complete_fetch_payload(batch_sections, scan.journal_fingerprint, budget)

    complete_payload = complete_response(requested_ids)
    if estimate_json_tokens(complete_payload) <= budget:
        return complete_payload

    single_sizes = {
        section.result_id: estimate_json_tokens(
            complete_response((section.result_id,))
        )
        for section in requested_sections
    }
    oversized_ids = {
        item_id for item_id, estimated_tokens in single_sizes.items()
        if estimated_tokens > budget
    }
    if oversized_ids:
        if len(requested_ids) == 1:
            return _chunk_required_payload(
                requested_sections[0], scan, log_directory, budget
            )
        return _mixed_overflow_payload(
            requested_sections,
            oversized_ids,
            single_sizes,
            complete_response,
            scan,
            log_directory,
            budget,
        )

    batches = plan_batches(requested_ids, complete_response, budget)
    payload = _sized_payload(lambda estimated_tokens: {
        "ok": True,
        "status": "overflow",
        "requested_ids": list(requested_ids),
        "item_sizes": _item_size_records(requested_sections, single_sizes),
        "suggested_batches": list(batches),
        "journal_fingerprint": scan.journal_fingerprint,
        "budget": {"limit": budget, "estimated_tokens": estimated_tokens},
    })
    _require_budget(payload, budget)
    return payload


def manifest_record_for_budget(
    section: SectionOccurrence,
    journal_fingerprint: str,
    budget: int,
) -> dict[str, object]:
    """Build a manifest using the complete single-item fetch response size.

    Args:
        section: Section occurrence to summarize without its body.
        journal_fingerprint: Fingerprint included in a full fetch response.
        budget: Active search and prospective fetch token budget.

    Returns:
        Source-preserving manifest with an exact fetch-fit indicator.
    """
    fits_budget = _single_item_fits_fetch_budget(
        section, journal_fingerprint, budget
    )
    return manifest_record(section, fits_budget)


def _single_item_fits_fetch_budget(
    section: SectionOccurrence,
    journal_fingerprint: str,
    budget: int,
) -> bool:
    """Return whether the complete compact single-item response fits."""
    item = _full_item(section, True)
    payload = _complete_fetch_payload_from_items(
        (section.result_id,), (item,), journal_fingerprint, budget
    )
    return estimate_json_tokens(payload) <= budget


def _validate_fetch_ids(item_ids: Sequence[str], scan: ScanResult) -> None:
    """Reject duplicate or unknown full-text section identifiers."""
    if len(set(item_ids)) != len(item_ids):
        raise QueryInputError("duplicate_ids", "Fetch requests must not repeat an ID.")
    known_ids = {section.result_id for section in scan.sections}
    unknown_ids = [item_id for item_id in item_ids if item_id not in known_ids]
    if unknown_ids:
        raise QueryInputError(
            "invalid_result_id", f"Unknown section IDs: {', '.join(unknown_ids)}."
        )


def _complete_fetch_payload(
    sections: Sequence[SectionOccurrence], journal_fingerprint: str, budget: int
) -> dict[str, object]:
    """Build one fixed-point-sized complete full-text fetch response."""
    items = [
        _full_item(
            section,
            _single_item_fits_fetch_budget(section, journal_fingerprint, budget),
        )
        for section in sections
    ]
    return _complete_fetch_payload_from_items(
        tuple(section.result_id for section in sections),
        tuple(items),
        journal_fingerprint,
        budget,
    )


def _complete_fetch_payload_from_items(
    requested_ids: Sequence[str],
    items: Sequence[dict[str, object]],
    journal_fingerprint: str,
    budget: int,
) -> dict[str, object]:
    """Build a complete response from already-sized full-text items."""
    return _sized_payload(lambda estimated_tokens: {
        "ok": True,
        "status": "complete",
        "requested_ids": list(requested_ids),
        "items": list(items),
        "journal_fingerprint": journal_fingerprint,
        "budget": {"limit": budget, "estimated_tokens": estimated_tokens},
    })


def _full_item(
    section: SectionOccurrence, fits_fetch_budget: bool
) -> dict[str, object]:
    """Build a full-text item with its exact single-fetch fit indicator."""
    item = manifest_record(section, fits_fetch_budget)
    item["body"] = section.body
    return item


def _item_size_records(
    sections: Sequence[SectionOccurrence], single_sizes: Mapping[str, int]
) -> list[dict[str, object]]:
    """Return request-order single-item response sizes."""
    return [
        {"id": section.result_id, "estimated_tokens": single_sizes[section.result_id]}
        for section in sections
    ]


def _mixed_overflow_payload(
    sections: Sequence[SectionOccurrence],
    oversized_ids: set[str],
    single_sizes: Mapping[str, int],
    complete_response: Callable[[Sequence[str]], dict[str, object]],
    scan: ScanResult,
    log_directory: Path,
    budget: int,
) -> dict[str, object]:
    """Account for every mixed request ID with a cursor or safe batch."""
    fitting_ids = [
        section.result_id
        for section in sections
        if section.result_id not in oversized_ids
    ]
    batches = plan_batches(fitting_ids, complete_response, budget)
    batch_indices = {
        item_id: batch_index
        for batch_index, batch in enumerate(batches)
        for item_id in batch["ids"]
    }
    dispositions: list[dict[str, object]] = []
    for section in sections:
        if section.result_id in oversized_ids:
            dispositions.append({
                "id": section.result_id,
                "status": "chunk_required",
                "chunk_cursor": _initial_chunk_cursor(
                    section, scan, log_directory, budget
                ),
            })
        else:
            dispositions.append({
                "id": section.result_id,
                "status": "suggested_batch",
                "batch_index": batch_indices[section.result_id],
            })

    payload = _sized_payload(lambda estimated_tokens: {
        "ok": True,
        "status": "overflow",
        "requested_ids": [section.result_id for section in sections],
        "item_sizes": _item_size_records(sections, single_sizes),
        "item_dispositions": dispositions,
        "suggested_batches": list(batches),
        "journal_fingerprint": scan.journal_fingerprint,
        "budget": {"limit": budget, "estimated_tokens": estimated_tokens},
    })
    _require_budget(payload, budget)
    return payload


def _chunk_required_payload(
    section: SectionOccurrence,
    scan: ScanResult,
    log_directory: Path,
    budget: int,
) -> dict[str, object]:
    """Build a body-free control response for one oversized section."""
    chunk_cursor = _initial_chunk_cursor(section, scan, log_directory, budget)
    payload = _sized_payload(lambda estimated_tokens: {
        "ok": True,
        "status": "chunk_required",
        "requested_ids": [section.result_id],
        "item": manifest_record_for_budget(
            section, scan.journal_fingerprint, budget
        ),
        "chunk_cursor": chunk_cursor,
        "journal_fingerprint": scan.journal_fingerprint,
        "budget": {"limit": budget, "estimated_tokens": estimated_tokens},
    })
    _require_budget(payload, budget)
    return payload


def _initial_chunk_cursor(
    section: SectionOccurrence,
    scan: ScanResult,
    log_directory: Path,
    budget: int,
) -> str:
    """Encode the first exact-chunk cursor for an oversized section."""
    return _encode_chunk_cursor(
        section.result_id,
        _body_fingerprint(section.body),
        log_directory,
        scan.journal_fingerprint,
        0,
        budget,
    )


def _fetch_chunk_response(
    cursor_text: str, scan: ScanResult, log_directory: Path, budget: int
) -> dict[str, object]:
    """Validate a chunk cursor and build its exact source substring."""
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
            section.result_id,
            body_fingerprint,
            log_directory,
            scan.journal_fingerprint,
            range_index + 1,
            budget,
        )
        if range_index + 1 < total_chunks
        else None
    )
    payload = _chunk_payload(
        section,
        start,
        end,
        range_index,
        total_chunks,
        next_cursor,
        scan.journal_fingerprint,
        budget,
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
    """Plan exact source ranges using the complete retrieval response."""
    def build_chunk(
        start: int, end: int, chunk_index: int, total_chunks: int
    ) -> dict[str, object]:
        """Build the precise response candidate used for budget planning."""
        next_cursor = (
            _encode_chunk_cursor(
                section.result_id,
                body_fingerprint,
                log_directory,
                scan.journal_fingerprint,
                chunk_index + 1,
                budget,
            )
            if chunk_index + 1 < total_chunks
            else None
        )
        return _chunk_payload(
            section,
            start,
            end,
            chunk_index,
            total_chunks,
            next_cursor,
            scan.journal_fingerprint,
            budget,
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
    """Build a response whose embedded token estimate reaches a fixed point."""
    estimated_tokens = 0
    while True:
        payload = payload_builder(estimated_tokens)
        calculated_tokens = estimate_json_tokens(payload)
        if calculated_tokens == estimated_tokens:
            return payload
        estimated_tokens = calculated_tokens


def _require_budget(payload: Mapping[str, object], budget: int) -> None:
    """Raise a typed error when a body-free control response is too large."""
    estimated_tokens = estimate_json_tokens(payload)
    if estimated_tokens > budget:
        raise BudgetError(
            "metadata_exceeds_budget",
            "Fetch response metadata exceeds the requested budget.",
            {"budget": budget, "estimated_tokens": estimated_tokens},
        )
