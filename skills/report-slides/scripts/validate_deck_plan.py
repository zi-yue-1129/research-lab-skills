#!/usr/bin/env python3
"""Validate strict Deck Plan and Deck Approval contracts.

The validator is intentionally small and deterministic so workflow gates can
reuse it without depending on a specific contract source format.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from presentation_contracts import (
    load_contract,
    validate_acyclic_dependencies,
    validate_schema_version,
)

_VISUAL_TYPES = frozenset({"native", "data", "generative", "hybrid", "none"})
_DECK_APPROVAL_DECISIONS = frozenset({"approve", "revise"})
_APPROVAL_MODES = frozenset({"interactive", "explicit_noninteractive", "preapproved"})
_RFC3339_Z = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


def _load_document(path: Path) -> Any:
    """Load a YAML or JSON document by file extension.

    Args:
        path: Path to a .yaml/.yml or .json file.

    Returns:
        The parsed document.
    """
    return load_contract(path)


def validate_slide_plan_entry(entry: Any, index: int) -> list[str]:
    """Validate one SlidePlanEntry embedded in a Deck Plan.

    Args:
        entry: The parsed entry mapping.
        index: Its position in the plan's "slides" list, used to prefix
            error messages so multiple bad entries are all reported.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: list[str] = []
    prefix = f"slides[{index}]"
    if not isinstance(entry, dict):
        return [f"{prefix}: must be a mapping"]
    for field in (
        "slide_id", "title", "purpose", "key_takeaway",
        "intended_visual_type", "visual_rationale", "speaker_message",
    ):
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}.{field}: required non-empty string")
    evidence_refs = entry.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        errors.append(f"{prefix}.evidence_refs: required non-empty list")
    elif any(not isinstance(reference, str) or not reference.strip() for reference in evidence_refs):
        errors.append(f"{prefix}.evidence_refs: every reference must be a non-empty string")
    for key in ("dependencies", "open_questions"):
        if key not in entry:
            errors.append(f"{prefix}.{key}: required list")
        elif not isinstance(entry[key], list):
            errors.append(f"{prefix}.{key}: required list")
        elif any(not isinstance(value, str) or not value.strip() for value in entry[key]):
            errors.append(f"{prefix}.{key}: every value must be a non-empty string")
    visual_type = entry.get("intended_visual_type")
    if isinstance(visual_type, str) and visual_type not in _VISUAL_TYPES:
        errors.append(f"{prefix}.intended_visual_type: must be one of {sorted(_VISUAL_TYPES)}, got {visual_type!r}")
    return errors


def validate_deck_plan(doc: Any) -> list[str]:
    """Validate a full Deck Plan document.

    Args:
        doc: The parsed Deck Plan mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]

    errors.extend(validate_schema_version(doc))
    for field in ("deck_id", "purpose", "audience", "core_narrative", "authored_by"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")

    plan_version = doc.get("plan_version")
    if (
        isinstance(plan_version, bool)
        or not isinstance(plan_version, int)
        or plan_version <= 0
    ):
        errors.append("plan_version: required positive integer")

    status = doc.get("status")
    if status != "reviewed":
        errors.append(f"status: must be 'reviewed', got {status!r}")

    duration = doc.get("estimated_duration_minutes")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        errors.append("estimated_duration_minutes: required positive number")

    slides = doc.get("slides")
    if not isinstance(slides, list) or not slides:
        errors.append("slides: required non-empty list")
    else:
        seen_ids: set[str] = set()
        dependency_edges: dict[str, list[str]] = {}
        for i, entry in enumerate(slides):
            errors.extend(validate_slide_plan_entry(entry, i))
            slide_id = entry.get("slide_id") if isinstance(entry, dict) else None
            if isinstance(slide_id, str) and slide_id.strip():
                if slide_id in seen_ids:
                    errors.append(f"slides[{i}].slide_id: duplicate slide_id {slide_id!r}")
                seen_ids.add(slide_id)
                dependencies = entry.get("dependencies")
                if isinstance(dependencies, list):
                    dependency_edges[slide_id] = dependencies
        errors.extend(validate_acyclic_dependencies(seen_ids, dependency_edges, "dependencies"))

    for field in ("excluded_content", "known_gaps"):
        value = doc.get(field)
        if not isinstance(value, list):
            errors.append(f"{field}: required list")
        elif any(not isinstance(item, str) or not item.strip() for item in value):
            errors.append(f"{field}: every value must be a non-empty string")
    return errors


def validate_deck_approval(doc: Any) -> list[str]:
    """Validate a Deck Approval document.

    Args:
        doc: The parsed Deck Approval mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]

    errors.extend(validate_schema_version(doc))
    for field in ("deck_id", "approved_by"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")

    plan_version = doc.get("plan_version")
    if (
        isinstance(plan_version, bool)
        or not isinstance(plan_version, int)
        or plan_version <= 0
    ):
        errors.append("plan_version: required positive integer")

    plan_sha256 = doc.get("plan_sha256")
    if not isinstance(plan_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", plan_sha256) is None:
        errors.append("plan_sha256: required 64-character lowercase hexadecimal digest")

    decision = doc.get("decision")
    if decision not in _DECK_APPROVAL_DECISIONS:
        errors.append(f"decision: must be one of {sorted(_DECK_APPROVAL_DECISIONS)}, got {decision!r}")
    if decision == "revise":
        revisions = doc.get("revisions_requested")
        if not isinstance(revisions, list) or not revisions:
            errors.append("revisions_requested: required non-empty list when decision is 'revise'")
    elif decision == "approve" and doc.get("revisions_requested"):
        errors.append("revisions_requested: must be empty when decision is 'approve'")

    approved_at = doc.get("approved_at")
    if not isinstance(approved_at, str) or not _is_rfc3339_z(approved_at):
        errors.append("approved_at: required RFC3339 timestamp ending in Z")

    approval_mode = doc.get("approval_mode")
    if approval_mode not in _APPROVAL_MODES:
        errors.append(
            f"approval_mode: must be one of {sorted(_APPROVAL_MODES)}, got {approval_mode!r}"
        )
    return errors


def _is_rfc3339_z(value: str) -> bool:
    """Return whether ``value`` is a valid UTC RFC3339 timestamp with ``Z``."""
    if _RFC3339_Z.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def main() -> None:
    """CLI entry point for validate_deck_plan.py."""
    parser = argparse.ArgumentParser(description="Validate Deck Plan / Deck Approval documents for report-slides.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", metavar="PATH", type=Path)
    group.add_argument("--approval", metavar="PATH", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    target = args.plan or args.approval
    try:
        doc = _load_document(target)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        errors = [f"failed to read/parse {target}: {exc}"]
    else:
        errors = validate_deck_plan(doc) if args.plan else validate_deck_approval(doc)

    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
