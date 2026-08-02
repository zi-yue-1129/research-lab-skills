#!/usr/bin/env python3
"""Expose research-log section discovery through a JSON command-line interface."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
from typing import Any

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


def main(arguments: list[str] | None = None) -> int:
    """Run a section-query command and return its process status.

    Args:
        arguments: Optional command-line arguments excluding the executable name.

    Returns:
        Zero for a successful query and one for a typed read error.
    """
    parser = argparse.ArgumentParser(
        description="Discover and search section types used in research logs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    types_parser = subparsers.add_parser("types", help="List discovered section types.")
    types_parser.add_argument(
        "--dir", default="docs/research_log", metavar="PATH", help="Research-log directory."
    )
    search_parser = subparsers.add_parser("search", help="Search sections by type and date.")
    search_parser.add_argument(
        "--dir", default="docs/research_log", metavar="PATH", help="Research-log directory."
    )
    search_parser.add_argument(
        "--sections", nargs="+", required=True, metavar="SECTION", help="Section types to include."
    )
    search_parser.add_argument(
        "--range", choices=("all", "7d", "30d", "90d", "year"), help="Named inclusive date range."
    )
    search_parser.add_argument("--from", dest="from_text", metavar="YYYY-MM-DD", help="Inclusive ISO lower bound.")
    search_parser.add_argument("--to", dest="to_text", metavar="YYYY-MM-DD", help="Inclusive ISO upper bound.")
    search_parser.add_argument("--today", metavar="YYYY-MM-DD", help="Reference date for reproducible ranges.")
    parsed_arguments = parser.parse_args(arguments)

    try:
        scan = scan_journal(Path(parsed_arguments.dir))
    except JournalReadError as error:
        _emit({
            "ok": False,
            "error": {"code": "invalid_utf8", "path": str(error.path), "message": str(error)},
        })
        return 1
    if parsed_arguments.command == "types":
        return _run_types(scan)
    if parsed_arguments.command == "search":
        return _run_search(parser, parsed_arguments, scan)
    parser.error(f"Unsupported command: {parsed_arguments.command}")
    return 2


def _run_types(scan: ScanResult) -> int:
    """Emit the existing stable type-discovery payload.

    Args:
        scan: Scan result returned by the research-log scanner.

    Returns:
        Zero after emitting the taxonomy payload.
    """
    summaries = discover_types(scan)
    sections_by_key: dict[str, list[SectionOccurrence]] = {}
    for section in scan.sections:
        sections_by_key.setdefault(section.type_key, []).append(section)
    serialized_types: list[dict[str, Any]] = []
    for summary in summaries:
        payload = _serialize(summary)
        occurrences = sections_by_key.get(summary.key, [])
        payload["occurrence_numbers"] = [
            occurrence.occurrence_number for occurrence in occurrences
        ]
        payload["result_ids"] = [occurrence.result_id for occurrence in occurrences]
        serialized_types.append(payload)
    _emit({
        "ok": True,
        "types": serialized_types,
        "warnings": [_serialize(warning) for warning in scan.warnings],
        "journal_fingerprint": scan.journal_fingerprint,
    })
    return 0


def _run_search(
    parser: argparse.ArgumentParser,
    parsed_arguments: argparse.Namespace,
    scan: ScanResult,
) -> int:
    """Validate, execute, and emit one section search.

    Args:
        parser: Parser used to report command-line validation errors.
        parsed_arguments: Parsed search command options.
        scan: Scan result returned by the research-log scanner.

    Returns:
        Zero after emitting an unpaginated manifest payload.
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
    _emit({
        "ok": True,
        "query": {
            "sections": list(normalized_types),
            "range": bounds.range_name,
            "from": parsed_arguments.from_text,
            "to": parsed_arguments.to_text,
            "today": bounds.reference_date.isoformat(),
            "resolved_from": bounds.start.isoformat() if bounds.start is not None else None,
            "resolved_to": bounds.end.isoformat() if bounds.end is not None else None,
        },
        "warnings": [_serialize(warning) for warning in warnings],
        "journal_fingerprint": scan.journal_fingerprint,
        "total_matches": len(matches),
        "matches": [
            manifest_record(section, _MANIFEST_FETCH_BUDGET) for section in matches
        ],
    })
    return 0


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


def _serialize(value: Any) -> dict[str, Any]:
    """Convert a query dataclass into JSON-compatible primitives."""
    return {
        key: _serialize_value(item)
        for key, item in asdict(value).items()
    }


def _serialize_value(value: Any) -> Any:
    """Convert date-like values nested in dataclass output to JSON values."""
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


def _emit(payload: dict[str, Any]) -> None:
    """Print one Unicode-preserving JSON payload."""
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
