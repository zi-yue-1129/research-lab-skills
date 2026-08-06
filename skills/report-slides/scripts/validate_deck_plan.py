#!/usr/bin/env python3
"""validate_deck_plan.py -- Schema validator for the Deck Plan (with its
embedded SlidePlanEntry list) and Deck Approval contracts, used at
Stages 3-5 of the report-slides multi-agent workflow.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, List

import yaml

_VISUAL_TYPES = frozenset({"native", "data", "generative", "hybrid", "none"})
_DECK_APPROVAL_DECISIONS = frozenset({"approve", "revise"})


def _load_document(path: Path) -> Any:
    """Load a YAML or JSON document by file extension.

    Args:
        path: Path to a .yaml/.yml or .json file.

    Returns:
        The parsed document.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


def validate_slide_plan_entry(entry: Any, index: int) -> List[str]:
    """Validate one SlidePlanEntry embedded in a Deck Plan.

    Args:
        entry: The parsed entry mapping.
        index: Its position in the plan's "slides" list, used to prefix
            error messages so multiple bad entries are all reported.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
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
    if not isinstance(entry.get("evidence_refs"), list):
        errors.append(f"{prefix}.evidence_refs: required list")
    for key in ("dependencies", "open_questions"):
        if key in entry and not isinstance(entry[key], list):
            errors.append(f"{prefix}.{key}: must be a list if present")
    visual_type = entry.get("intended_visual_type")
    if isinstance(visual_type, str) and visual_type not in _VISUAL_TYPES:
        errors.append(f"{prefix}.intended_visual_type: must be one of {sorted(_VISUAL_TYPES)}, got {visual_type!r}")
    return errors


def validate_deck_plan(doc: Any) -> List[str]:
    """Validate a full Deck Plan document.

    Args:
        doc: The parsed Deck Plan mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]
    for field in ("deck_id", "purpose", "audience"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")
    duration = doc.get("estimated_duration_minutes")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        errors.append("estimated_duration_minutes: required positive number")
    slides = doc.get("slides")
    if not isinstance(slides, list) or not slides:
        errors.append("slides: required non-empty list")
    else:
        seen_ids: set = set()
        for i, entry in enumerate(slides):
            errors.extend(validate_slide_plan_entry(entry, i))
            slide_id = entry.get("slide_id") if isinstance(entry, dict) else None
            if slide_id:
                if slide_id in seen_ids:
                    errors.append(f"slides[{i}].slide_id: duplicate slide_id {slide_id!r}")
                seen_ids.add(slide_id)
    for field in ("excluded_content", "known_gaps"):
        if field in doc and not isinstance(doc[field], list):
            errors.append(f"{field}: must be a list if present")
    return errors


def validate_deck_approval(doc: Any) -> List[str]:
    """Validate a Deck Approval document.

    Args:
        doc: The parsed Deck Approval mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]
    for field in ("deck_id", "approved_by"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")
    decision = doc.get("decision")
    if decision not in _DECK_APPROVAL_DECISIONS:
        errors.append(f"decision: must be one of {sorted(_DECK_APPROVAL_DECISIONS)}, got {decision!r}")
    if decision == "revise":
        revisions = doc.get("revisions_requested")
        if not isinstance(revisions, list) or not revisions:
            errors.append("revisions_requested: required non-empty list when decision is 'revise'")
    if "plan_version" in doc and not isinstance(doc["plan_version"], int):
        errors.append("plan_version: must be an int if present")
    return errors


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
    except (OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        errors = [f"failed to read/parse {target}: {exc}"]
    else:
        errors = validate_deck_plan(doc) if args.plan else validate_deck_approval(doc)

    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
