#!/usr/bin/env python3
"""Render deterministic Deck Plan previews and validate draft evidence.

The formatter is intentionally stdout-only.  Draft validation lives beside
the formatter so the workflow action can keep its state transition small while
sharing one strict interpretation of rendered-slide and contact-sheet paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from presentation_contracts import contract_sha256, load_contract
from presentation_events import load_artifacts, load_plans
from presentation_gates import DraftGateError, assert_draft_reviewable
from presentation_state import load_slides


_SHA256_LENGTH = 64
_PLAN_FIELDS: tuple[tuple[str, str], ...] = (
    ("schema_version", "Schema version"),
    ("deck_id", "Deck ID"),
    ("plan_version", "Plan version"),
    ("status", "Status"),
    ("authored_by", "Authored by"),
    ("purpose", "Purpose"),
    ("audience", "Audience"),
    ("estimated_duration_minutes", "Duration"),
    ("core_narrative", "Core narrative"),
)


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    """Require a mapping while preserving a useful public error message."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _require_plan_field(plan: Mapping[str, Any], field: str) -> Any:
    """Return one required plan field or fail closed."""
    if field not in plan:
        raise ValueError(f"plan field is required: {field}")
    return plan[field]


def _format_list(value: Any, field: str) -> list[str]:
    """Validate one textual list field for deterministic display."""
    if not isinstance(value, list):
        raise ValueError(f"plan field must be a list: {field}")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"plan field list must contain non-empty strings: {field}")
        result.append(item)
    return result


def _display_lines(label: str, values: list[str]) -> list[str]:
    """Format a list field while retaining an explicit empty declaration."""
    if not values:
        return [f"{label}: (none declared)"]
    return [f"{label}:", *[f"  - {value}" for value in values]]


def format_plan_preview(plan: dict[str, Any]) -> str:
    """Format every approval-relevant plan field as deterministic text.

    Args:
        plan: Validated Deck Plan mapping.

    Returns:
        A stable human-readable preview string.  The function does not create
        directories or files.

    Raises:
        ValueError: If the plan is not a mapping with the required fields.
    """
    document = _require_mapping(plan, "plan")
    lines = ["Deck Plan Preview"]
    for field, label in _PLAN_FIELDS:
        value = _require_plan_field(document, field)
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"plan field must be non-empty: {field}")
        if field == "estimated_duration_minutes":
            value = f"{value} minutes"
        lines.append(f"{label}: {value}")
    known_gaps = _format_list(_require_plan_field(document, "known_gaps"), "known_gaps")
    excluded_content = _format_list(
        _require_plan_field(document, "excluded_content"), "excluded_content"
    )
    lines.extend(_display_lines("Known gaps", known_gaps))
    lines.extend(_display_lines("Excluded content", excluded_content))
    slides = _require_plan_field(document, "slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("plan field must be a non-empty list: slides")
    lines.append(f"Slides: {len(slides)}")
    for index, raw_slide in enumerate(slides, start=1):
        slide = _require_mapping(raw_slide, f"slides[{index}]")
        for field in (
            "slide_id",
            "title",
            "key_takeaway",
            "evidence_refs",
            "intended_visual_type",
            "visual_rationale",
            "purpose",
            "speaker_message",
            "dependencies",
            "open_questions",
        ):
            _require_plan_field(slide, field)
        slide_id = slide["slide_id"]
        title = slide["title"]
        if not isinstance(slide_id, str) or not slide_id.strip():
            raise ValueError(f"slides[{index}].slide_id must be non-empty")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"slides[{index}].title must be non-empty")
        evidence = _format_list(slide["evidence_refs"], f"slides[{index}].evidence_refs")
        dependencies = _format_list(slide["dependencies"], f"slides[{index}].dependencies")
        open_questions = _format_list(slide["open_questions"], f"slides[{index}].open_questions")
        lines.extend(("", f"[{slide_id}] {title}"))
        lines.append(f"  Purpose: {slide['purpose']}")
        lines.append(f"  Key takeaway: {slide['key_takeaway']}")
        lines.append(f"  Evidence: {', '.join(evidence) if evidence else '(none declared)'}")
        lines.append(f"  Planned visual: {slide['intended_visual_type']}")
        lines.append(f"  Visual rationale: {slide['visual_rationale']}")
        lines.append(f"  Speaker message: {slide['speaker_message']}")
        lines.append(f"  Dependencies: {', '.join(dependencies) if dependencies else '(none)'}")
        lines.append(f"  Open questions: {', '.join(open_questions) if open_questions else '(none)'}")
    return "\n".join(lines) + "\n"


def _parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    """Parse the stdout-only preview CLI arguments."""
    parser = argparse.ArgumentParser(description="Print a deterministic Deck Plan preview.")
    parser.add_argument("--plan", required=True, type=Path, help="Deck Plan YAML or JSON path.")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Print one plan preview to stdout without writing presentation artifacts.

    Args:
        arguments: Optional argument sequence; defaults to ``sys.argv``.

    Returns:
        Zero when the plan is formatted, otherwise one after an error on
        stderr.  The CLI never creates output files.
    """
    parsed = _parse_arguments(arguments)
    try:
        plan = load_contract(parsed.plan)
        sys.stdout.write(format_plan_preview(plan))
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 1
    return 0


def _is_sha256(value: Any) -> bool:
    """Return whether a value is a lowercase hexadecimal SHA-256 digest."""
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _relative_path(project_root: Path, value: Any, field: str) -> tuple[str | None, Path | None]:
    """Resolve one project-relative evidence path without following escapes."""
    if not isinstance(value, str) or not value or "\\" in value:
        return None, None
    lexical = Path(value)
    if lexical.is_absolute() or ".." in lexical.parts or "." in lexical.parts:
        return None, None
    candidate = project_root / lexical
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(project_root.resolve())
    except (OSError, ValueError):
        return value, None
    if candidate.is_symlink() or not resolved.is_file():
        return value, None
    return lexical.as_posix(), resolved


def _canonical_source_digest(paths: Sequence[str], digests: Sequence[str]) -> str:
    """Digest an ordered rendered-slide path/digest binding."""
    return contract_sha256({"paths": list(paths), "digests": list(digests)})


def _raise_draft(deck_id: str, blockers: list[dict[str, Any]]) -> None:
    """Raise a structured DraftGateError with deterministic blocker detail."""
    if blockers:
        summary = "; ".join(str(blocker.get("reason", blocker)) for blocker in blockers)
    else:
        summary = "missing evidence"
    raise DraftGateError(
        "draft_reviewable",
        deck_id,
        blockers,
        f"draft_reviewable blocked for deck {deck_id}: {summary}",
    )


def _approved_plan(project_root: Path, deck: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """Load and bind the immutable plan approved for one deck."""
    blockers: list[dict[str, Any]] = []
    deck_id = str(deck.get("id", "<unknown>"))
    records = load_plans(project_root)
    current_id = deck.get("current_plan_id")
    record = records.get(current_id) if isinstance(current_id, str) else None
    if record is None:
        blockers.append({"reason": "missing_current_plan_id"})
        return None, None, blockers
    raw_path = record.get("plan_path", record.get("path"))
    if not isinstance(raw_path, str) or Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
        blockers.append({"reason": "invalid_plan_path"})
        return record, None, blockers
    plan_path = project_root / raw_path
    if not plan_path.is_file():
        blockers.append({"reason": "missing_plan_file", "path": raw_path})
        return record, None, blockers
    try:
        plan = load_contract(plan_path)
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        blockers.append({"reason": "invalid_plan_file", "message": str(error)})
        return record, None, blockers
    if not isinstance(plan, dict):
        blockers.append({"reason": "plan_not_mapping"})
        return record, None, blockers
    plan_sha = contract_sha256(plan)
    if plan.get("deck_id") != deck_id:
        blockers.append({"reason": "plan_deck_id_mismatch"})
    if deck.get("approved_plan_version") != record.get("version"):
        blockers.append({"reason": "approved_plan_version_stale"})
    if deck.get("approved_plan_sha256") != plan_sha:
        blockers.append({"reason": "approved_plan_digest_stale"})
    if record.get("sha256", record.get("plan_sha256")) != plan_sha:
        blockers.append({"reason": "plan_digest_mismatch"})
    return record, plan, blockers


def _current_slide_order(project_root: Path, deck_id: str, plan: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str], dict[str, dict[str, Any]]]:
    """Return current slide records in approved plan order."""
    records = [
        dict(slide)
        for slide in load_slides(project_root).values()
        if slide.get("deck_id") == deck_id and slide.get("status") != "superseded"
    ]
    by_plan_id: dict[str, dict[str, Any]] = {}
    by_record_id: dict[str, dict[str, Any]] = {}
    for slide in records:
        plan_id = slide.get("plan_slide_id")
        record_id = slide.get("id")
        if isinstance(plan_id, str) and plan_id:
            by_plan_id[plan_id] = slide
        if isinstance(record_id, str) and record_id:
            by_record_id[record_id] = slide
    ordered: list[dict[str, Any]] = []
    expected_ids: list[str] = []
    for raw_plan_slide in plan.get("slides", []):
        if not isinstance(raw_plan_slide, Mapping):
            continue
        plan_id = raw_plan_slide.get("slide_id")
        if not isinstance(plan_id, str) or not plan_id:
            continue
        expected_ids.append(plan_id)
        if plan_id in by_plan_id:
            ordered.append(by_plan_id[plan_id])
    return ordered, expected_ids, {**by_plan_id, **by_record_id}


def _normalize_rendered_paths(
    project_root: Path,
    rendered: Any,
    expected_ids: Sequence[str],
    lookup: Mapping[str, Mapping[str, Any]],
    blockers: list[dict[str, Any]],
) -> tuple[list[str], dict[str, str], list[dict[str, Any]]]:
    """Validate and canonicalize the ordered rendered-slide path list."""
    if not isinstance(rendered, list) or not rendered:
        blockers.append({"reason": "rendered slide set"})
        return [], {}, []
    if len(rendered) != len(expected_ids):
        blockers.append({"reason": "rendered slide set", "expected": len(expected_ids), "actual": len(rendered)})
    paths: list[str] = []
    slide_for_path: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(rendered):
        if isinstance(raw_entry, str):
            raw_path = raw_entry
            raw_slide_id = expected_ids[index] if index < len(expected_ids) else None
            entry: dict[str, Any] = {"slide_id": raw_slide_id, "path": raw_path}
        elif isinstance(raw_entry, Mapping):
            raw_path = raw_entry.get("path")
            raw_slide_id = raw_entry.get("slide_id", raw_entry.get("plan_slide_id"))
            entry = dict(raw_entry)
        else:
            blockers.append({"reason": "rendered slide entry must be a mapping", "index": index})
            continue
        if not isinstance(raw_slide_id, str) or raw_slide_id not in lookup:
            blockers.append({"reason": "rendered slide set contains unknown slide", "slide_id": raw_slide_id})
            continue
        plan_slide_id = str(lookup[raw_slide_id].get("plan_slide_id", raw_slide_id))
        if plan_slide_id not in expected_ids:
            blockers.append({"reason": "rendered slide set contains extra slide", "slide_id": raw_slide_id})
        relative, resolved = _relative_path(project_root, raw_path, "rendered_slide_path")
        if relative is None or resolved is None or Path(relative).suffix.lower() != ".png":
            blockers.append({"reason": "rendered slide path must be a project-relative PNG", "path": raw_path})
            continue
        if relative in slide_for_path:
            blockers.append({"reason": "rendered slide set contains duplicate path", "path": relative})
        if plan_slide_id in slide_for_path.values():
            blockers.append({"reason": "rendered slide set contains duplicate slide", "slide_id": plan_slide_id})
        paths.append(relative)
        slide_for_path[relative] = plan_slide_id
        entry["slide_id"] = plan_slide_id
        entry["path"] = relative
        entries.append(entry)
        expected_index = expected_ids.index(plan_slide_id) if plan_slide_id in expected_ids else -1
        if expected_index != index:
            blockers.append({"reason": "rendered slide set order mismatch", "slide_id": plan_slide_id})
    if set(slide_for_path.values()) != set(expected_ids):
        blockers.append({
            "reason": "rendered slide set",
            "missing": sorted(set(expected_ids) - set(slide_for_path.values())),
            "extra": sorted(set(slide_for_path.values()) - set(expected_ids)),
        })
    return paths, slide_for_path, entries


def _check_extra_pngs(
    project_root: Path,
    paths: Sequence[str],
    contact_path: str,
    blockers: list[dict[str, Any]],
) -> None:
    """Reject unregistered PNGs in the rendered-slide/contact-sheet folders."""
    folders = {(project_root / Path(path)).parent for path in (*paths, contact_path)}
    allowed = set(paths) | {contact_path}
    for folder in sorted(folders, key=str):
        if not folder.is_dir():
            continue
        for candidate in sorted(folder.rglob("*.png"), key=str):
            try:
                relative = candidate.resolve().relative_to(project_root.resolve()).as_posix()
            except ValueError:
                blockers.append({"reason": "rendered artifact outside project", "path": str(candidate)})
                continue
            if relative not in allowed:
                blockers.append({"reason": "extra rendered PNG", "path": relative})


def _artifact_digest_map(
    project_root: Path,
    paths: Sequence[str],
    contact_path: str,
    raw_digests: Any,
    strict: bool,
    blockers: list[dict[str, Any]],
) -> dict[str, str]:
    """Validate canonical artifact digests and return actual digests."""
    expected = set(paths) | {contact_path}
    supplied = raw_digests if isinstance(raw_digests, Mapping) else {}
    if strict and not isinstance(raw_digests, Mapping):
        blockers.append({"reason": "artifact_digests_required"})
    if isinstance(raw_digests, Mapping):
        extras = set(raw_digests) - expected
        missing = expected - set(raw_digests)
        if extras:
            blockers.append({"reason": "extra_artifact_digest", "paths": sorted(extras)})
        if missing:
            blockers.append({"reason": "missing_artifact_digest", "paths": sorted(missing)})
    actual: dict[str, str] = {}
    for relative in sorted(expected):
        path = project_root / relative
        if not path.is_file():
            blockers.append({"reason": "missing_rendered_artifact", "path": relative})
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        actual[relative] = digest
        supplied_digest = supplied.get(relative)
        if strict and not _is_sha256(supplied_digest):
            blockers.append({"reason": "invalid_artifact_digest", "path": relative})
        elif isinstance(supplied_digest, str) and supplied_digest != digest:
            blockers.append({"reason": "artifact_digest_mismatch", "path": relative, "actual": digest})
    return actual


def _binding_blockers(
    project_root: Path,
    deck_id: str,
    record: Mapping[str, Any] | None,
    plan: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    paths: Sequence[str],
    contact_path: str,
    actual_digests: Mapping[str, str],
    raw_bindings: Any,
    strict: bool,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Validate artifact bindings and derive the contact-sheet source digest."""
    blockers: list[dict[str, Any]] = []
    bindings = raw_bindings if isinstance(raw_bindings, Mapping) else {}
    if strict and not isinstance(raw_bindings, Mapping):
        blockers.append({"reason": "artifact_bindings_required"})
    expected_keys = set(paths) | {contact_path}
    if isinstance(raw_bindings, Mapping):
        if set(raw_bindings) - expected_keys:
            blockers.append({"reason": "extra_artifact_binding", "paths": sorted(set(raw_bindings) - expected_keys)})
        if expected_keys - set(raw_bindings):
            blockers.append({"reason": "missing_artifact_binding", "paths": sorted(expected_keys - set(raw_bindings))})
    plan_version = plan.get("plan_version")
    plan_sha256 = contract_sha256(plan)
    normalized: dict[str, dict[str, Any]] = {}
    for entry in entries:
        path = str(entry["path"])
        slide_id = str(entry["slide_id"])
        binding = bindings.get(path)
        if not isinstance(binding, Mapping):
            binding = {}
        normalized_binding = dict(binding)
        normalized_binding.update({
            "kind": "rendered_slide",
            "deck_id": deck_id,
            "slide_id": slide_id,
            "plan_version": plan_version,
            "plan_sha256": plan_sha256,
            "producer_id": binding.get("producer_id", binding.get("producer", "renderer")),
        })
        if strict:
            for field, expected in (("kind", "rendered_slide"), ("deck_id", deck_id), ("slide_id", slide_id), ("plan_version", plan_version), ("plan_sha256", plan_sha256)):
                if binding.get(field) != expected:
                    blockers.append({"reason": "artifact_binding_mismatch", "path": path, "field": field})
            producer = binding.get("producer_id", binding.get("producer"))
            if not isinstance(producer, str) or not producer.strip():
                blockers.append({"reason": "artifact_binding_producer_required", "path": path})
        slide_record = next((slide for slide in load_slides(project_root).values() if slide.get("deck_id") == deck_id and slide.get("plan_slide_id") == slide_id and slide.get("status") != "superseded"), None)
        if slide_record:
            for field in ("slide_spec_sha256", "approved_takeaway_sha256", "approved_evidence_sha256"):
                expected_value = slide_record.get(field)
                if expected_value is not None and binding.get(field) != expected_value:
                    blockers.append({"reason": "artifact_binding_mismatch", "path": path, "field": field})
                if expected_value is not None:
                    normalized_binding[field] = expected_value
        normalized[path] = normalized_binding
    source_digests = [actual_digests.get(path, "") for path in paths]
    source_sha256 = _canonical_source_digest(paths, source_digests)
    contact_binding = bindings.get(contact_path)
    if not isinstance(contact_binding, Mapping):
        contact_binding = {}
    normalized_contact = dict(contact_binding)
    normalized_contact.update({
        "kind": "contact_sheet",
        "deck_id": deck_id,
        "plan_version": plan_version,
        "plan_sha256": plan_sha256,
        "producer_id": contact_binding.get("producer_id", contact_binding.get("producer", "renderer")),
        "source_paths": list(paths),
        "source_sha256": source_sha256,
    })
    if strict:
        for field, expected in (("kind", "contact_sheet"), ("deck_id", deck_id), ("plan_version", plan_version), ("plan_sha256", plan_sha256)):
            if contact_binding.get(field) != expected:
                blockers.append({"reason": "contact_sheet_binding_mismatch", "field": field})
        if contact_binding.get("source_paths") != list(paths):
            blockers.append({"reason": "contact_sheet_source_set_mismatch"})
        supplied_source_sha = contact_binding.get("source_sha256", contact_binding.get("source_set_sha256"))
        if supplied_source_sha != source_sha256:
            blockers.append({"reason": "contact_sheet_source_digest_mismatch"})
        producer = contact_binding.get("producer_id", contact_binding.get("producer"))
        if not isinstance(producer, str) or not producer.strip():
            blockers.append({"reason": "contact_sheet_binding_producer_required"})
    normalized[contact_path] = normalized_contact
    return blockers, normalized


def validate_draft_preview(
    project_root: Path,
    deck_id: str,
    preview: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a complete draft preview against current approved evidence.

    Args:
        project_root: Project root containing presentation state and renders.
        deck_id: Deck identifier to validate.
        preview: Draft Preview contract mapping.

    Returns:
        A mapping containing the normalized preview, approved plan, current
        slides, and canonical artifact digests.

    Raises:
        DraftGateError: If the rendered set, contact sheet, plan binding, or
            artifact evidence is missing, stale, extra, or tampered.
    """
    if not isinstance(preview, Mapping):
        _raise_draft(deck_id, [{"reason": "preview must be a mapping"}])
    blockers: list[dict[str, Any]] = []
    try:
        checked = assert_draft_reviewable(project_root, deck_id, dict(preview))
        deck = checked["deck"]
    except DraftGateError as error:
        blockers.extend(error.blockers)
        decks = __import__("presentation_state").load_decks(project_root)
        deck = decks.get(deck_id, {"id": deck_id})
        checked = {"deck": deck, "slides": []}
    record, plan, plan_blockers = _approved_plan(project_root, deck)
    blockers.extend(plan_blockers)
    if plan is None:
        _raise_draft(deck_id, blockers)
    strict = True
    if preview.get("schema_version") != 1:
        blockers.append({"reason": "schema_version_required"})
    if preview.get("deck_id") != deck_id:
        blockers.append({"reason": "deck_id_mismatch"})
    if strict:
        if preview.get("plan_version") != plan.get("plan_version"):
            blockers.append({"reason": "preview_plan_version_mismatch"})
        if preview.get("plan_sha256") != contract_sha256(plan):
            blockers.append({"reason": "preview_plan_digest_mismatch"})
    ordered_slides, expected_ids, lookup = _current_slide_order(project_root, deck_id, plan)
    if len(ordered_slides) != len(expected_ids):
        blockers.append({"reason": "current slide set does not match approved plan"})
    for slide in ordered_slides:
        if slide.get("status") != "passed":
            blockers.append({"reason": f"slide:{slide.get('id')}:not_passed"})
    paths, slide_for_path, entries = _normalize_rendered_paths(
        project_root,
        preview.get("rendered_slide_paths"),
        expected_ids,
        lookup,
        blockers,
    )
    contact_value = preview.get("contact_sheet_path", preview.get("contact_sheet"))
    contact_path, _ = _relative_path(project_root, contact_value, "contact_sheet_path")
    if contact_path is None or Path(contact_path).suffix.lower() != ".png":
        blockers.append({"reason": "contact sheet path must be a project-relative PNG"})
        contact_path = str(contact_value) if isinstance(contact_value, str) else ""
    else:
        contact_resolved = project_root / contact_path
        if not contact_resolved.is_file():
            blockers.append({"reason": "missing_contact_sheet", "path": contact_path})
    _check_extra_pngs(project_root, paths, contact_path, blockers)
    plan_slides = {
        slide.get("slide_id"): slide
        for slide in plan.get("slides", [])
        if isinstance(slide, Mapping) and isinstance(slide.get("slide_id"), str)
    }
    preview_slides = preview.get("slides", preview.get("rendered_slides", []))
    if strict and (not isinstance(preview_slides, list) or len(preview_slides) != len(expected_ids)):
        blockers.append({"reason": "preview slide set mismatch"})
    seen_preview_ids: set[str] = set()
    if isinstance(preview_slides, list):
        for entry in preview_slides:
            if not isinstance(entry, Mapping):
                blockers.append({"reason": "preview slide must be a mapping"})
                continue
            slide_id = entry.get("slide_id", entry.get("plan_slide_id"))
            expected = plan_slides.get(slide_id)
            if expected is None:
                blockers.append({"reason": "preview slide is not in approved plan", "slide_id": slide_id})
                continue
            seen_preview_ids.add(str(slide_id))
            if entry.get("title") != expected.get("title"):
                blockers.append({"reason": "preview title/takeaway mismatch", "slide_id": slide_id})
            if entry.get("key_takeaway", entry.get("takeaway")) != expected.get("key_takeaway"):
                blockers.append({"reason": "preview title/takeaway mismatch", "slide_id": slide_id})
            if "evidence_refs" in entry and entry.get("evidence_refs") != expected.get("evidence_refs"):
                blockers.append({"reason": "preview evidence mismatch", "slide_id": slide_id})
    if strict and seen_preview_ids != set(expected_ids):
        blockers.append({"reason": "preview slide set mismatch", "missing": sorted(set(expected_ids) - seen_preview_ids)})
    actual_digests = _artifact_digest_map(
        project_root,
        paths,
        contact_path,
        preview.get("artifact_digests", preview.get("artifacts")),
        strict,
        blockers,
    )
    binding_blockers, normalized_bindings = _binding_blockers(
        project_root,
        deck_id,
        record,
        plan,
        entries,
        paths,
        contact_path,
        actual_digests,
        preview.get("artifact_bindings"),
        strict,
    )
    blockers.extend(binding_blockers)
    try:
        persisted_artifacts = load_artifacts(project_root)
    except Exception as error:  # noqa: BLE001 - malformed stores are gate blockers
        blockers.append({"reason": "artifact_store_invalid", "message": str(error)})
        persisted_artifacts = {}
    for relative, digest in actual_digests.items():
        matches = [
            artifact for artifact in persisted_artifacts.values()
            if artifact.get("deck_id") == deck_id and artifact.get("path", artifact.get("relative_path")) == relative
        ]
        if matches and any(artifact.get("sha256") != digest for artifact in matches):
            blockers.append({"reason": "persisted_artifact_digest_mismatch", "path": relative})
    if blockers:
        _raise_draft(deck_id, blockers)
    normalized = dict(preview)
    normalized.update({
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": plan.get("plan_version"),
        "plan_sha256": contract_sha256(plan),
        "rendered_slide_paths": entries,
        "contact_sheet_path": contact_path,
        "artifact_digests": actual_digests,
        "artifact_bindings": normalized_bindings,
    })
    return {
        "deck": deck,
        "plan": dict(plan),
        "plan_record": record,
        "preview": normalized,
        "slides": ordered_slides,
        "artifact_digests": actual_digests,
    }


if __name__ == "__main__":
    raise SystemExit(main())
