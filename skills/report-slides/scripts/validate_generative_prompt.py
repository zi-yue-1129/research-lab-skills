#!/usr/bin/env python3
"""Validate a generative illustration's prompt record.

Enforces that a generative image is anchored to a registered style, justified
against the deterministic diagram route, and does not ask for a banned motif.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Union

import yaml

from style_anchors import (
    ANCHORS_PATH, CANDIDATE_COUNT, AnchorError, get_anchor,
    scan_for_banned_motifs,
)

# `candidates`, `ranking`, and `selected` are deliberately absent here and
# checked by `_candidate_errors` instead: a valid downgrade record sets
# `selected: null`, which this list's truthiness test would reject.
REQUIRED_FIELDS = (
    "purpose", "illustration_rationale", "style_anchor", "composition",
    "subject", "palette", "lighting", "empty_annotation_regions",
    "exclusions", "aspect_ratio",
)
REQUIRED_EXCLUSIONS = (
    "prose", "labels", "legends", "exact values", "watermarks", "signatures",
)
_YAML_BLOCK = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)


def parse_prompt_record(path: Union[str, Path]) -> Dict[str, Any]:
    """Read the YAML record out of a `prompt.md`.

    Args:
        path: Path to the prompt record.

    Returns:
        The parsed mapping.

    Raises:
        ValueError: If the file cannot be read, carries no fenced YAML block,
            or that block is not a mapping.
    """
    record_path = Path(path)
    try:
        text = record_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"cannot read prompt record {record_path}: {exc}") from exc
    match = _YAML_BLOCK.search(text)
    # Records predating the fenced-block convention are plain YAML documents;
    # both forms are accepted so existing assets can be validated in place.
    payload = match.group(1) if match else text
    try:
        data = yaml.safe_load(payload)
    except yaml.YAMLError as exc:
        raise ValueError(f"cannot parse {record_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"{record_path} does not contain a prompt-record mapping, either "
            f"as a fenced yaml block or as a plain yaml document")
    return data


def _record_text(record: Mapping[str, Any]) -> str:
    """Flatten a record's values into one searchable string.

    Args:
        record: The prompt record.

    Returns:
        Every scalar value in the record, joined by spaces.
    """
    parts: List[str] = []

    def walk(value: Any) -> None:
        """Append every scalar reachable from a value."""
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif value is not None:
            parts.append(str(value))

    walk(dict(record))
    return " ".join(parts)


def _candidate_errors(record: Mapping[str, Any]) -> List[str]:
    """Check spec D6's three-candidate blind-ranking requirement.

    Spec D6 requires that "Three candidates are generated and ranked blind
    against the anchor", and that "If no candidate matches the anchor, the
    module downgrades to a native editorial composition. Accepting the
    least-bad image is prohibited."

    Both halves are checked here rather than left to the author, because a
    record that merely *describes* a blind ranking is indistinguishable from one
    that accepted the first image the model returned -- and that is the
    behaviour spec 2.1 documents failing.

    Args:
        record: The parsed prompt record.

    Returns:
        Human-readable errors; empty when the record satisfies D6.
    """
    errors: List[str] = []
    candidates = record.get("candidates")
    if not isinstance(candidates, list):
        return ["candidates must be a list of "
                f"{CANDIDATE_COUNT} ranked entries"]
    if len(candidates) != CANDIDATE_COUNT:
        errors.append(
            f"candidates must hold exactly {CANDIDATE_COUNT} entries; "
            f"found {len(candidates)}. Spec D6 requires three candidates "
            f"ranked blind against the anchor.")

    ranks: List[Any] = []
    identifiers: List[str] = []
    matching: List[str] = []
    for position, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f"candidate {position} is not a mapping")
            continue
        if not candidate.get("id"):
            errors.append(f"candidate {position} omits 'id'")
            continue
        identifier = str(candidate["id"])
        identifiers.append(identifier)
        ranks.append(candidate.get("rank"))
        if candidate.get("matches_anchor") is True:
            matching.append(identifier)

    if len(identifiers) == len(candidates):
        expected = list(range(1, len(candidates) + 1))
        if sorted(rank for rank in ranks if isinstance(rank, int)) != expected:
            errors.append(
                f"candidate 'rank' values must be a permutation of "
                f"{expected}; found {ranks}")

    ranking = record.get("ranking")
    if not isinstance(ranking, dict):
        errors.append("ranking must be a mapping with 'blinded' and 'ranked_by'")
    elif ranking.get("blinded") is not True:
        errors.append(
            "ranking.blinded must be true: spec D6 requires the candidates be "
            "ranked blind against the anchor, and a ranker who knows which "
            "candidate is which is not ranking blind")

    selected = record.get("selected")
    if selected is None:
        if record.get("downgraded_to") != "native-editorial":
            errors.append(
                "a record that selects no candidate must set "
                "downgraded_to: native-editorial")
    elif str(selected) not in identifiers:
        errors.append(
            f"selected {str(selected)!r} is not one of the ranked candidates: "
            f"{', '.join(identifiers) or '(none)'}")
    elif str(selected) not in matching:
        errors.append(
            f"selected candidate {str(selected)!r} does not match the anchor. "
            f"Spec D6: accepting the least-bad image is prohibited; downgrade "
            f"to a native editorial composition instead.")
    return errors


def validate_prompt_record(record: Mapping[str, Any],
                           anchors_path: Path = ANCHORS_PATH) -> List[str]:
    """Validate one prompt record against the generative contract.

    Args:
        record: The parsed prompt record.
        anchors_path: Path to the style-anchor registry.

    Returns:
        Human-readable errors; an empty list means the record is admissible.
    """
    errors: List[str] = []
    for field in REQUIRED_FIELDS:
        if not record.get(field):
            errors.append(f"missing required field: {field}")

    anchor_id = record.get("style_anchor")
    if anchor_id:
        try:
            get_anchor(str(anchor_id), anchors_path)
        except AnchorError as exc:
            errors.append(str(exc))

    errors.extend(_candidate_errors(record))

    exclusions = record.get("exclusions") or []
    if isinstance(exclusions, (list, tuple)):
        present = {str(item).strip().lower() for item in exclusions}
        absent = [item for item in REQUIRED_EXCLUSIONS if item not in present]
        if absent:
            errors.append(
                f"exclusions omit required entries: {', '.join(absent)}")
    else:
        errors.append("exclusions must be a list")

    for motif in scan_for_banned_motifs(_record_text(record)):
        errors.append(
            f"prompt asks for banned motif {motif!r}; see "
            f"references/style-anchors/README.md")
    return errors


def main() -> None:
    """Validate one prompt record from the command line."""
    parser = argparse.ArgumentParser(
        description="Validate a generative illustration prompt record.")
    parser.add_argument("--prompt", metavar="PATH", type=Path, required=True)
    parser.add_argument("--anchors", metavar="PATH", type=Path,
                        default=ANCHORS_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        record = parse_prompt_record(args.prompt)
        errors = validate_prompt_record(record, args.anchors)
    except ValueError as exc:
        errors = [str(exc)]

    result = {"valid": not errors, "prompt": str(args.prompt), "errors": errors}
    sys.stdout.write(
        (json.dumps(result) if args.json else json.dumps(result, indent=2))
        + "\n")
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
