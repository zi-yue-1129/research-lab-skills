#!/usr/bin/env python3
"""Expose research-log section discovery through a JSON command-line interface."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
from typing import Any

from section_query_core import JournalReadError, discover_types, scan_journal


def main(arguments: list[str] | None = None) -> int:
    """Run a section-query command and return its process status.

    Args:
        arguments: Optional command-line arguments excluding the executable name.

    Returns:
        Zero for a successful query and one for a typed read error.
    """
    parser = argparse.ArgumentParser(
        description="Discover section types used in research logs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    types_parser = subparsers.add_parser("types", help="List discovered section types.")
    types_parser.add_argument(
        "--dir", default="docs/research_log", metavar="PATH", help="Research-log directory."
    )
    parsed_arguments = parser.parse_args(arguments)
    if parsed_arguments.command != "types":
        parser.error(f"Unsupported command: {parsed_arguments.command}")

    try:
        scan = scan_journal(Path(parsed_arguments.dir))
    except JournalReadError as error:
        _emit({
            "ok": False,
            "error": {"code": "invalid_utf8", "path": str(error.path), "message": str(error)},
        })
        return 1
    summaries = discover_types(scan)
    sections_by_key: dict[str, list[Any]] = {}
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
