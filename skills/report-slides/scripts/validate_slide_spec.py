#!/usr/bin/env python3
"""Validate strict report-slides Slide Specification contracts."""

from __future__ import annotations

import argparse
import json
import math
import numbers
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from presentation_contracts import contract_sha256, load_contract, validate_schema_version


_CANVAS_WIDTH = 1200
_CANVAS_HEIGHT = 675
_EXPECTED_COMPLEXITIES = frozenset({"low", "medium", "high"})
_COMPLEXITY_SIGNALS = {
    "region_count": "integer",
    "route_count": "integer",
    "multi_stage": "boolean",
    "mixed_technique": "boolean",
    "heavy_cross_region_connections": "boolean",
    "expected_reuse": "boolean",
    "not_atomic": "boolean",
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_slide_spec(doc: Any) -> list[str]:
    """Validate one complete Slide Specification document.

    Args:
        doc: Parsed YAML or JSON Slide Specification.

    Returns:
        Deterministically ordered human-readable validation errors. An empty
        list means that the specification is valid for the detector or a
        downstream workflow stage.
    """
    if not isinstance(doc, dict):
        return ["document must be a mapping"]

    errors: list[str] = []
    errors.extend(validate_schema_version(doc))
    _require_nonempty_string(doc, "slide_id", errors)
    _validate_string_list(doc, "information_hierarchy", errors, allow_empty=False)

    region_ids = _validate_regions(doc, errors)
    _validate_reading_order(doc, region_ids, errors)

    ratio = doc.get("text_to_visual_ratio")
    if not _is_finite_number(ratio) or not 0 <= ratio <= 1:
        errors.append("text_to_visual_ratio: required number from 0 through 1")

    _require_nonempty_string(doc, "visual_emphasis", errors)
    expected_complexity = doc.get("expected_complexity")
    if expected_complexity not in _EXPECTED_COMPLEXITIES:
        errors.append(
            "expected_complexity: must be one of "
            f"{sorted(_EXPECTED_COMPLEXITIES)}, got {expected_complexity!r}"
        )
    _validate_string_list(doc, "reusable_components", errors, allow_empty=True)
    _validate_detector_field(doc, errors)
    _validate_complexity_signals(doc, len(region_ids), errors)
    _require_nonempty_string(doc, "approved_takeaway", errors)
    _validate_protected_digest(
        doc, "approved_takeaway", "approved_takeaway_sha256", errors
    )
    _validate_string_list(doc, "approved_evidence_refs", errors, allow_empty=False)
    _validate_protected_digest(
        doc, "approved_evidence_refs", "approved_evidence_sha256", errors
    )
    return errors


def _validate_regions(doc: dict[str, Any], errors: list[str]) -> set[str]:
    """Validate layout regions and return their declared IDs."""
    regions = doc.get("layout_regions")
    if not isinstance(regions, list) or not regions:
        errors.append("layout_regions: required non-empty list")
        return set()

    region_ids: set[str] = set()
    for index, region in enumerate(regions):
        prefix = f"layout_regions[{index}]"
        if not isinstance(region, dict):
            errors.append(f"{prefix}: must be a mapping")
            continue
        region_id = region.get("region_id")
        if not isinstance(region_id, str) or not region_id.strip():
            errors.append(f"{prefix}.region_id: required non-empty string")
        elif region_id in region_ids:
            errors.append(f"{prefix}.region_id: duplicate region id {region_id!r}")
        else:
            region_ids.add(region_id)
        _validate_bbox(region.get("bbox"), prefix, errors)
    return region_ids


def _validate_bbox(value: Any, prefix: str, errors: list[str]) -> None:
    """Validate one region's endpoint-coordinate bounding box."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        errors.append(
            f"{prefix}.bbox: required numeric [x1, y1, x2, y2] inside "
            f"{_CANVAS_WIDTH}x{_CANVAS_HEIGHT}"
        )
        return
    if any(not _is_finite_number(coordinate) for coordinate in value):
        errors.append(f"{prefix}.bbox: every coordinate must be a finite number")
        return
    x1, y1, x2, y2 = value
    if not (0 <= x1 < x2 <= _CANVAS_WIDTH and 0 <= y1 < y2 <= _CANVAS_HEIGHT):
        errors.append(
            f"{prefix}.bbox: bounds must satisfy 0 <= x1 < x2 <= {_CANVAS_WIDTH} "
            f"and 0 <= y1 < y2 <= {_CANVAS_HEIGHT}"
        )


def _validate_reading_order(
    doc: dict[str, Any], region_ids: set[str], errors: list[str]
) -> None:
    """Require reading order to cover every declared region exactly once."""
    value = doc.get("reading_order")
    if not isinstance(value, list) or not value:
        errors.append("reading_order: required non-empty list of region IDs")
        return
    if any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append("reading_order: every value must be a non-empty region ID")
        return
    if len(set(value)) != len(value):
        errors.append("reading_order: region IDs must be unique")
    unknown = sorted(set(value) - region_ids)
    missing = sorted(region_ids - set(value))
    if unknown:
        errors.append(f"reading_order: undeclared region ID(s) {unknown!r}")
    if missing:
        errors.append(f"reading_order: missing region ID(s) {missing!r}")


def _validate_complexity_signals(
    doc: dict[str, Any], region_count: int, errors: list[str]
) -> None:
    """Validate the seven explicit inputs consumed by the complexity detector."""
    signals = doc.get("complexity_signals")
    if not isinstance(signals, dict):
        errors.append("complexity_signals: required mapping with all seven signals")
        return
    for field, expected_type in _COMPLEXITY_SIGNALS.items():
        if field not in signals:
            errors.append(f"complexity_signals.{field}: required {expected_type} value")
            continue
        value = signals[field]
        if expected_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"complexity_signals.{field}: required non-negative integer")
            elif field == "region_count" and value != region_count:
                errors.append(
                    "complexity_signals.region_count: must equal "
                    f"the number of layout_regions ({region_count})"
                )
        elif not isinstance(value, bool):
            errors.append(f"complexity_signals.{field}: required boolean value")


def _validate_detector_field(doc: dict[str, Any], errors: list[str]) -> None:
    """Allow the detector result to be absent, null, or a boolean."""
    if "requires_complex_workflow" not in doc:
        return
    value = doc["requires_complex_workflow"]
    if value is not None and not isinstance(value, bool):
        errors.append("requires_complex_workflow: must be a boolean or null")


def _validate_protected_digest(
    doc: dict[str, Any], value_field: str, digest_field: str, errors: list[str]
) -> None:
    """Require a canonical digest that matches its protected contract value."""
    digest = doc.get(digest_field)
    if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
        errors.append(
            f"{digest_field}: required 64-character lowercase hexadecimal digest"
        )
        return
    value = doc.get(value_field)
    if value is None:
        return
    expected_digest = contract_sha256(value)
    if digest != expected_digest:
        errors.append(
            f"{digest_field}: does not match canonical digest of {value_field}"
        )


def _validate_string_list(
    doc: dict[str, Any], field: str, errors: list[str], allow_empty: bool
) -> None:
    """Require a list containing only non-empty strings."""
    value = doc.get(field)
    if not isinstance(value, list) or (not allow_empty and not value):
        qualifier = "list" if allow_empty else "non-empty list"
        errors.append(f"{field}: required {qualifier}")
        return
    if any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{field}: every value must be a non-empty string")


def _require_nonempty_string(
    doc: dict[str, Any], field: str, errors: list[str]
) -> None:
    """Require one non-empty string field."""
    value = doc.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field}: required non-empty string")


def _is_finite_number(value: Any) -> bool:
    """Return whether ``value`` is a finite real number but not a boolean."""
    return isinstance(value, numbers.Real) and not isinstance(value, bool) and math.isfinite(value)


def main() -> None:
    """Run Slide Specification validation from the command line."""
    parser = argparse.ArgumentParser(description="Validate a report-slides Slide Specification.")
    parser.add_argument("--spec", metavar="PATH", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        document = load_contract(args.spec)
        errors = validate_slide_spec(document)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        errors = [f"failed to read/parse {args.spec}: {exc}"]

    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
