#!/usr/bin/env python3
"""Intrinsic historical conversion for immutable report-slides evidence.

This module deliberately validates only the event's own shape, canonical
digest, declared identities, ordered metadata, and frozen artifact bytes. It
does not inspect today's active slides, deck pointers, or mutable filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Mapping

from migration_scope import MigrationError, canonical_relative_path
from presentation_contracts import contract_sha256
from presentation_evidence_cas import CasObject, cas_relative_path
from presentation_evidence_contracts import (
    EvidenceContractError,
    artifact_policy_for_event,
    envelope_sha256,
    validate_envelope,
)
from presentation_evidence_snapshot import EvidenceSnapshot
from validate_deck_plan import validate_deck_approval
from validate_visual_review import derive_overall_status, validate_review_document
from presentation_active_evidence import (  # noqa: F401 - public API re-export
    ActiveEvidenceProjection,
    project_active_evidence,
)


_SHA256_HEX = frozenset("0123456789abcdef")
_PREVIEW_FIELDS = frozenset(
    {
        "schema_version",
        "deck_id",
        "plan_version",
        "plan_sha256",
        "rendered_slide_paths",
        "contact_sheet_path",
        "slides",
        "artifact_digests",
        "artifact_bindings",
    }
)
_PERSISTED_PREVIEW_FIELDS = _PREVIEW_FIELDS | frozenset(
    {"event", "id", "preview_sha256", "ts"}
)
_COMPLETION_FIELDS = frozenset(
    {
        "schema_version",
        "deck_id",
        "plan_id",
        "plan_version",
        "plan_sha256",
        "producer_id",
        "approval_evidence_id",
        "approval_evidence_sha256",
        "visual_review_evidence_id",
        "visual_review_evidence_sha256",
        "artifact_digests",
    }
)
_PERSISTED_COMPLETION_FIELDS = _COMPLETION_FIELDS | frozenset(
    {"event", "id", "completion_sha256", "ts"}
)
_VISUAL_REVIEW_SOURCE_FIELDS = frozenset(
    {
        "schema_version",
        "event",
        "id",
        "deck_id",
        "plan_id",
        "plan_version",
        "plan_sha256",
        "producer_id",
        "visual_review_path",
        "visual_review_sha256",
        "ts",
    }
)


class ProjectionError(MigrationError):
    """Raised when immutable historical evidence is structurally invalid."""


@dataclass(frozen=True)
class HistoricalProjection:
    """Intrinsic envelopes and verified CAS plans derived from history.

    Attributes:
        envelopes: Immutable schema-v2 envelopes keyed by evidence ID.
        by_source_event_id: Immutable envelopes keyed by source event ID.
        cas_objects: Digest-keyed frozen CAS objects for available envelopes.
        current_pointer_ids: Snapshot deck-pointer IDs, retained only as
            context and never used to validate a historical envelope.
    """

    envelopes: Mapping[str, Mapping[str, Any]]
    by_source_event_id: Mapping[str, Mapping[str, Any]]
    cas_objects: Mapping[str, CasObject]
    current_pointer_ids: frozenset[str]


def project_historical_evidence(snapshot: EvidenceSnapshot) -> HistoricalProjection:
    """Convert valid history without applying current-state predicates.

    Args:
        snapshot: Immutable capture built by :func:`build_snapshot`.

    Returns:
        Historical envelopes and CAS plans assembled only from the snapshot.

    Raises:
        ProjectionError: If an artifact-bearing historical event is malformed,
            forged, internally inconsistent, or declares bytes with a digest
            that differs from its frozen source snapshot.
    """
    if not isinstance(snapshot, EvidenceSnapshot):
        raise ProjectionError("snapshot must be an EvidenceSnapshot")
    envelopes: dict[str, Mapping[str, Any]] = {}
    by_source_event_id: dict[str, Mapping[str, Any]] = {}
    cas_objects: dict[str, CasObject] = {}
    for frozen_event in snapshot.events:
        event = _thaw(frozen_event)
        if not isinstance(event, dict):
            raise ProjectionError("snapshot event must be a mapping")
        event_kind = event.get("event")
        if not isinstance(event_kind, str):
            if "artifact_digests" in event or "artifact_bindings" in event:
                raise ProjectionError("unregistered event kinds cannot carry artifact maps")
            continue
        if artifact_policy_for_event(event_kind) == "none":
            if "artifact_digests" in event or "artifact_bindings" in event:
                raise ProjectionError("unregistered event kinds cannot carry artifact maps")
            continue
        if event_kind == "draft_preview":
            envelope, objects = _project_preview(snapshot, event)
        elif event_kind == "deck_completion":
            envelope, objects = _project_completion(snapshot, event)
        else:
            raise ProjectionError(f"unregistered artifact event kind {event_kind!r}")
        evidence_id = envelope["id"]
        source_event_id = envelope["source_event_id"]
        if evidence_id in envelopes:
            raise ProjectionError(f"duplicate projected evidence id {evidence_id!r}")
        if source_event_id in by_source_event_id:
            raise ProjectionError(f"duplicate projected source event id {source_event_id!r}")
        envelopes[evidence_id] = envelope
        by_source_event_id[source_event_id] = envelopes[evidence_id]
        for digest, object_ in objects.items():
            existing = cas_objects.get(digest)
            if existing is not None and existing.content != object_.content:
                raise ProjectionError(f"SHA-256 collision in historical CAS object {digest}")
            cas_objects[digest] = object_
    return HistoricalProjection(
        envelopes=MappingProxyType(dict(envelopes)),
        by_source_event_id=MappingProxyType(dict(by_source_event_id)),
        cas_objects=MappingProxyType(dict(sorted(cas_objects.items()))),
        current_pointer_ids=_current_pointer_ids(snapshot),
    )


def _project_preview(
    snapshot: EvidenceSnapshot, event: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, CasObject]]:
    """Validate and convert one exact historical draft-preview event."""
    _require_exact_fields(event, _PERSISTED_PREVIEW_FIELDS, "draft_preview")
    _require_text(event.get("id"), "draft_preview.id")
    _require_text(event.get("deck_id"), "draft_preview.deck_id")
    _require_text(event.get("ts"), "draft_preview.ts")
    if event.get("event") != "draft_preview":
        raise ProjectionError("draft_preview event is invalid")
    _require_exact_int(event.get("schema_version"), 1, "draft_preview.schema_version")
    _require_positive_int(event.get("plan_version"), "draft_preview.plan_version")
    _require_digest(event.get("plan_sha256"), "draft_preview.plan_sha256")
    payload = {field: event[field] for field in _PREVIEW_FIELDS}
    _require_digest(event.get("preview_sha256"), "draft_preview.preview_sha256")
    if event["preview_sha256"] != _canonical_digest(payload, "draft_preview"):
        raise ProjectionError("draft_preview canonical event digest mismatch")
    deck_id = event["deck_id"]
    plan_version = event["plan_version"]
    plan_sha256 = event["plan_sha256"]
    rendered_paths, subject_ids, producer_id = _validate_preview_artifacts(
        event, deck_id, plan_version, plan_sha256
    )
    plan_id = _resolve_historical_plan_id(
        snapshot, deck_id, plan_version, plan_sha256, event.get("plan_id")
    )
    artifact_refs, objects, availability = _artifact_references(
        snapshot,
        event["artifact_digests"],
        [(path, "rendered_slide", slide_id) for path, slide_id in zip(rendered_paths, subject_ids)]
        + [(event["contact_sheet_path"], "contact_sheet", deck_id)],
    )
    envelope = _base_envelope(
        event,
        evidence_kind="draft_preview",
        deck_id=deck_id,
        plan_id=plan_id,
        plan_version=plan_version,
        plan_sha256=plan_sha256,
        subject_ids=subject_ids,
        producer_id=producer_id,
        artifact_refs=artifact_refs,
        availability=availability,
    )
    return _validated_envelope(envelope), objects


def _project_completion(
    snapshot: EvidenceSnapshot, event: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, CasObject]]:
    """Validate and convert one exact historical deck-completion event."""
    _require_exact_fields(event, _PERSISTED_COMPLETION_FIELDS, "deck_completion")
    for field in (
        "id",
        "deck_id",
        "plan_id",
        "producer_id",
        "approval_evidence_id",
        "visual_review_evidence_id",
        "ts",
    ):
        _require_text(event.get(field), f"deck_completion.{field}")
    if event.get("event") != "deck_completion":
        raise ProjectionError("deck_completion event is invalid")
    _require_exact_int(
        event.get("schema_version"), 1, "deck_completion.schema_version"
    )
    _require_positive_int(event.get("plan_version"), "deck_completion.plan_version")
    for field in (
        "plan_sha256",
        "approval_evidence_sha256",
        "visual_review_evidence_sha256",
        "completion_sha256",
    ):
        _require_digest(event.get(field), f"deck_completion.{field}")
    payload = {field: event[field] for field in _COMPLETION_FIELDS}
    if event["completion_sha256"] != _canonical_digest(payload, "deck_completion"):
        raise ProjectionError("deck_completion canonical event digest mismatch")
    artifact_digests = _mapping(
        event.get("artifact_digests"), "deck_completion.artifact_digests"
    )
    _resolve_completion_sources(snapshot, event)
    final_path, rendered_paths = _review_artifact_paths(snapshot, event)
    expected_paths = [final_path, *rendered_paths]
    if set(artifact_digests) != set(expected_paths):
        raise ProjectionError(
            "deck_completion artifacts must exactly match the visual review outputs"
        )
    for path in expected_paths:
        _require_digest(artifact_digests.get(path), f"deck_completion digest {path!r}")
    bindings = [(final_path, "final_pptx", event["deck_id"])] + [
        (path, "rendered_png", event["deck_id"]) for path in rendered_paths
    ]
    _validate_completion_artifact_records(snapshot, event["deck_id"], artifact_digests, bindings)
    artifact_refs, objects, availability = _artifact_references(
        snapshot, artifact_digests, bindings
    )
    envelope = _base_envelope(
        event,
        evidence_kind="deck_completion",
        deck_id=event["deck_id"],
        plan_id=event["plan_id"],
        plan_version=event["plan_version"],
        plan_sha256=event["plan_sha256"],
        subject_ids=[event["deck_id"]],
        producer_id=event["producer_id"],
        artifact_refs=artifact_refs,
        availability=availability,
    )
    envelope.update(
        {
            "approval_evidence_id": event["approval_evidence_id"],
            "approval_evidence_sha256": event["approval_evidence_sha256"],
            "visual_review_evidence_id": event["visual_review_evidence_id"],
            "visual_review_evidence_sha256": event["visual_review_evidence_sha256"],
        }
    )
    envelope["evidence_sha256"] = envelope_sha256(envelope)
    return _validated_envelope(envelope), objects


def _resolve_completion_sources(
    snapshot: EvidenceSnapshot, completion: Mapping[str, Any]
) -> None:
    """Require exact immutable approval and review sources for completion."""
    evidence = snapshot.stores.get("evidence")
    if evidence is None:
        raise ProjectionError("deck_completion immutable evidence sources are unavailable")
    approval = _completion_source_envelope(
        evidence,
        completion,
        "approval_evidence_id",
        "approval_evidence_sha256",
        "draft_approval",
    )
    review = _completion_source_envelope(
        evidence,
        completion,
        "visual_review_evidence_id",
        "visual_review_evidence_sha256",
        "visual_review",
    )
    if approval.get("decision") != "approved":
        raise ProjectionError("deck_completion approval source must be approved")
    _validate_approval_source_event(snapshot, approval, completion)
    _validate_visual_review_source_event(snapshot, review, completion)


def _completion_source_envelope(
    evidence: Mapping[str, Mapping[str, Any]],
    completion: Mapping[str, Any],
    id_field: str,
    digest_field: str,
    expected_kind: str,
) -> dict[str, Any]:
    """Resolve one completion reference from immutable envelope state."""
    evidence_id = completion[id_field]
    assert isinstance(evidence_id, str)
    frozen_source = evidence.get(evidence_id)
    if frozen_source is None:
        raise ProjectionError(f"deck_completion {id_field} does not resolve")
    source = _thaw(frozen_source)
    if not isinstance(source, dict):
        raise ProjectionError(f"deck_completion {id_field} source must be a mapping")
    try:
        validated = validate_envelope(source)
    except EvidenceContractError as exc:
        raise ProjectionError(
            f"deck_completion {id_field} source is invalid: {exc}"
        ) from exc
    if validated["id"] != evidence_id or validated["evidence_kind"] != expected_kind:
        raise ProjectionError(f"deck_completion {id_field} has the wrong evidence kind")
    if validated["evidence_sha256"] != completion[digest_field]:
        raise ProjectionError(f"deck_completion {digest_field} does not match its source")
    for field in ("deck_id", "plan_id", "plan_version", "plan_sha256"):
        if validated[field] != completion[field]:
            raise ProjectionError(f"deck_completion {id_field} {field} does not match")
    if validated["availability"] != "available":
        raise ProjectionError(f"deck_completion {id_field} must be available")
    return validated


def _validate_approval_source_event(
    snapshot: EvidenceSnapshot,
    approval: Mapping[str, Any],
    completion: Mapping[str, Any],
) -> None:
    """Validate the immutable approval event linked by its source envelope."""
    source = _source_event(
        snapshot,
        approval["source_event_id"],
        "draft_approval",
        completion_event_id=completion["id"],
    )
    if source.get("event") != "deck_approval":
        raise ProjectionError("draft_approval source event must be deck_approval")
    errors = validate_deck_approval(source)
    if errors:
        raise ProjectionError(f"draft_approval source event is invalid: {errors[0]}")
    if source.get("decision") != "approve":
        raise ProjectionError("draft_approval source event must approve")
    for field in ("deck_id", "plan_version", "plan_sha256"):
        if source.get(field) != completion[field]:
            raise ProjectionError(f"draft_approval source event {field} does not match")


def _validate_visual_review_source_event(
    snapshot: EvidenceSnapshot,
    review: Mapping[str, Any],
    completion: Mapping[str, Any],
) -> None:
    """Validate a frozen visual-review source event without live reads."""
    source = _source_event(
        snapshot,
        review["source_event_id"],
        "visual_review",
        completion_event_id=completion["id"],
    )
    _require_exact_fields(source, _VISUAL_REVIEW_SOURCE_FIELDS, "visual_review")
    if source.get("event") != "visual_review":
        raise ProjectionError("visual_review source event is invalid")
    _require_exact_int(
        source.get("schema_version"), 1, "visual_review.schema_version"
    )
    for field in ("id", "deck_id", "plan_id", "producer_id", "ts"):
        _require_text(source.get(field), f"visual_review.{field}")
    _require_positive_int(source.get("plan_version"), "visual_review.plan_version")
    _require_digest(source.get("plan_sha256"), "visual_review.plan_sha256")
    _require_digest(source.get("visual_review_sha256"), "visual_review.visual_review_sha256")
    for field in ("deck_id", "plan_id", "plan_version", "plan_sha256"):
        if source[field] != completion[field]:
            raise ProjectionError(f"visual_review source event {field} does not match")
    _frozen_visual_review_document(snapshot, source)


def _review_artifact_paths(
    snapshot: EvidenceSnapshot, completion: Mapping[str, Any]
) -> tuple[str, list[str]]:
    """Derive final artifact paths from the frozen referenced review record."""
    evidence = snapshot.stores.get("evidence")
    if evidence is None:
        raise ProjectionError("deck_completion immutable evidence sources are unavailable")
    review_id = completion["visual_review_evidence_id"]
    assert isinstance(review_id, str)
    review = _thaw(evidence[review_id])
    if not isinstance(review, dict):
        raise ProjectionError("deck_completion visual review source must be a mapping")
    source = _source_event(
        snapshot,
        review.get("source_event_id"),
        "visual_review",
        completion_event_id=completion["id"],
    )
    document = _frozen_visual_review_document(snapshot, source)
    if document.get("deck_id") != completion["deck_id"]:
        raise ProjectionError("visual review document deck_id does not match completion")
    if document.get("output_format") != "pptx":
        raise ProjectionError("visual review document must describe PPTX output")
    artifacts = _mapping(document.get("artifacts"), "visual review artifacts")
    final_path = _canonical_path(artifacts.get("pptx"), "visual review final PPTX")
    statuses = _mapping(document.get("statuses"), "visual review statuses")
    render_status = _mapping(
        statuses.get("pptx_render"), "visual review pptx_render status"
    )
    raw_rendered = render_status.get("rendered_png_paths")
    if not isinstance(raw_rendered, list) or not raw_rendered:
        raise ProjectionError("visual review rendered_png_paths must be non-empty")
    rendered_paths = [
        _canonical_path(path, "visual review rendered PNG") for path in raw_rendered
    ]
    if len(set(rendered_paths)) != len(rendered_paths):
        raise ProjectionError("visual review rendered PNG paths must be unique")
    if any(not path.lower().endswith(".png") for path in rendered_paths):
        raise ProjectionError("visual review rendered paths must be PNG files")
    if final_path in rendered_paths:
        raise ProjectionError("visual review final PPTX overlaps rendered PNG paths")
    return final_path, rendered_paths


def _frozen_visual_review_document(
    snapshot: EvidenceSnapshot, source: Mapping[str, Any]
) -> dict[str, Any]:
    """Parse a review document only from the snapshot's retained preimage."""
    review_path = _canonical_path(
        source.get("visual_review_path"), "visual_review.visual_review_path"
    )
    content = snapshot.file_preimages.get(snapshot.project_root / review_path)
    if content is None:
        raise ProjectionError("visual_review source bytes are unavailable")
    document = _parse_frozen_json(content, review_path)
    if source["visual_review_sha256"] != _canonical_digest(document, "visual_review"):
        raise ProjectionError("visual_review source document digest mismatch")
    _validate_completion_authorizing_review(document)
    return document


def _validate_completion_authorizing_review(document: Mapping[str, Any]) -> None:
    """Require every intrinsic visual-review predicate needed for completion."""
    try:
        issues = validate_review_document(document)
    except ValueError as exc:
        raise ProjectionError(f"visual review document is invalid: {exc}") from exc
    if issues:
        first_issue = issues[0]
        raise ProjectionError(
            f"visual review document is invalid: {first_issue.path}: "
            f"{first_issue.message}"
        )
    try:
        result = derive_overall_status(document)
    except ValueError as exc:
        raise ProjectionError(
            f"visual review document cannot derive completion status: {exc}"
        ) from exc
    statuses = _mapping(document.get("statuses"), "visual review statuses")
    render_status = _mapping(
        statuses.get("pptx_render"), "visual review pptx_render status"
    )
    if (
        result.status != "passed"
        or not result.completion_allowed
        or result.authority != "pptx-render"
        or render_status.get("status") != "passed"
    ):
        raise ProjectionError("visual review is not completion-authorizing")


def _parse_frozen_json(content: bytes, relative_path: str) -> dict[str, Any]:
    """Parse one frozen JSON object while rejecting duplicate keys."""
    def pairs(pairs_list: list[tuple[str, Any]]) -> dict[str, Any]:
        """Build a mapping without allowing duplicate JSON keys."""
        parsed: dict[str, Any] = {}
        for key, value in pairs_list:
            if key in parsed:
                raise ProjectionError(
                    f"visual review {relative_path} has duplicate JSON key {key!r}"
                )
            parsed[key] = value
        return parsed

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    except ProjectionError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectionError(
            f"visual review {relative_path} is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ProjectionError(f"visual review {relative_path} must be a mapping")
    return value


def _validate_completion_artifact_records(
    snapshot: EvidenceSnapshot,
    deck_id: str,
    artifact_digests: Mapping[str, Any],
    bindings: list[tuple[str, str, str]],
) -> None:
    """Require exactly one immutable persisted record per completion artifact."""
    records = snapshot.stores.get("artifacts")
    if records is None:
        raise ProjectionError("deck_completion artifact records are unavailable")
    record_kinds = {"final_pptx": "deck-pptx", "rendered_png": "slide-png"}
    for path, evidence_kind, _subject_id in bindings:
        matches: list[dict[str, Any]] = []
        for frozen_record in records.values():
            record = _thaw(frozen_record)
            if not isinstance(record, dict) or record.get("deck_id") != deck_id:
                continue
            if record.get("path") != path:
                continue
            matches.append(record)
        if len(matches) != 1:
            raise ProjectionError(
                f"deck_completion requires exactly one artifact record for {path!r}"
            )
        record = matches[0]
        if record.get("artifact_kind") != record_kinds[evidence_kind]:
            raise ProjectionError(f"deck_completion artifact record kind mismatch for {path!r}")
        if record.get("sha256") != artifact_digests[path]:
            raise ProjectionError(
                f"deck_completion artifact record digest mismatch for {path!r}"
            )


def _source_event(
    snapshot: EvidenceSnapshot,
    source_event_id: object,
    label: str,
    *,
    completion_event_id: object | None = None,
) -> dict[str, Any]:
    """Resolve one immutable raw event and enforce completion causality.

    Args:
        snapshot: Frozen event order and source values.
        source_event_id: Event identifier declared by an immutable envelope.
        label: Stable source category for typed diagnostics.
        completion_event_id: Optional completion event that the source must
            precede in the frozen audit sequence.

    Returns:
        The unique thawed source event.

    Raises:
        ProjectionError: If either event is ambiguous, unresolved, or ordered
            at or after the completion event.
    """
    _require_text(source_event_id, f"{label}.source_event_id")
    assert isinstance(source_event_id, str)
    matches = [
        (index, _thaw(event))
        for index, event in enumerate(snapshot.events)
        if isinstance(event, Mapping) and event.get("id") == source_event_id
    ]
    if len(matches) != 1 or not isinstance(matches[0][1], dict):
        raise ProjectionError(f"{label}.source_event_id does not resolve")
    source_index, source = matches[0]
    if completion_event_id is not None:
        _require_text(completion_event_id, "deck_completion.id")
        assert isinstance(completion_event_id, str)
        completion_indices = [
            index
            for index, event in enumerate(snapshot.events)
            if isinstance(event, Mapping) and event.get("id") == completion_event_id
        ]
        if len(completion_indices) != 1:
            raise ProjectionError("deck_completion event must resolve uniquely")
        if source_index >= completion_indices[0]:
            raise ProjectionError(f"{label}.source_event_id must precede deck_completion")
    return source


def _validate_preview_artifacts(
    event: Mapping[str, Any], deck_id: str, plan_version: int, plan_sha256: str
) -> tuple[list[str], list[str], str]:
    """Validate intrinsic draft-preview ordering, bindings, and declarations."""
    rendered = event.get("rendered_slide_paths")
    metadata = event.get("slides")
    artifact_digests = _mapping(event.get("artifact_digests"), "draft_preview.artifact_digests")
    artifact_bindings = _mapping(event.get("artifact_bindings"), "draft_preview.artifact_bindings")
    if not isinstance(rendered, list) or not rendered:
        raise ProjectionError("draft_preview.rendered_slide_paths must be non-empty")
    if not isinstance(metadata, list) or not metadata:
        raise ProjectionError("draft_preview.slides must be non-empty")
    rendered_paths: list[str] = []
    subject_ids: list[str] = []
    rendered_entries: dict[str, Mapping[str, Any]] = {}
    for index, entry in enumerate(rendered):
        entry_map = _mapping(entry, f"draft_preview rendered entry {index}")
        _require_exact_fields(
            entry_map,
            frozenset({"slide_id", "path", "slide_record_id", "attempt"}),
            "draft_preview rendered entry",
        )
        for field in ("slide_id", "slide_record_id"):
            _require_text(entry_map.get(field), f"draft_preview rendered {field}")
        _require_positive_int(entry_map.get("attempt"), "draft_preview rendered attempt")
        path = _canonical_path(entry_map.get("path"), "draft_preview rendered path")
        if path in rendered_entries or entry_map["slide_id"] in subject_ids:
            raise ProjectionError("draft_preview contains duplicate rendered slide identity")
        rendered_paths.append(path)
        subject_ids.append(entry_map["slide_id"])
        rendered_entries[path] = entry_map
    metadata_ids: list[str] = []
    for index, entry in enumerate(metadata):
        entry_map = _mapping(entry, f"draft_preview metadata {index}")
        _require_exact_fields(
            entry_map,
            frozenset({"slide_id", "title", "key_takeaway"}),
            "draft_preview metadata",
        )
        for field in ("slide_id", "title", "key_takeaway"):
            _require_text(entry_map.get(field), f"draft_preview metadata {field}")
        metadata_ids.append(entry_map["slide_id"])
    if metadata_ids != subject_ids:
        raise ProjectionError("draft_preview ordered metadata does not match rendered slides")
    contact_path = _canonical_path(event.get("contact_sheet_path"), "draft_preview contact sheet")
    expected_paths = set(rendered_paths) | {contact_path}
    if set(artifact_digests) != expected_paths or set(artifact_bindings) != expected_paths:
        raise ProjectionError("draft_preview artifact declaration paths are inconsistent")
    producer_id: str | None = None
    for path in rendered_paths:
        _require_digest(artifact_digests[path], f"draft_preview digest {path!r}")
        binding = _mapping(artifact_bindings[path], f"draft_preview binding {path!r}")
        _require_exact_fields(
            binding,
            frozenset(
                {
                    "kind",
                    "deck_id",
                    "slide_id",
                    "plan_version",
                    "plan_sha256",
                    "producer_id",
                    "slide_record_id",
                    "attempt",
                }
            ),
            "draft_preview rendered binding",
        )
        if binding.get("kind") != "rendered_slide":
            raise ProjectionError(f"draft_preview rendered binding kind mismatch for {path!r}")
        if binding.get("deck_id") != deck_id or binding.get("slide_id") != rendered_entries[path]["slide_id"]:
            raise ProjectionError(f"draft_preview rendered binding identity mismatch for {path!r}")
        if binding.get("plan_version") != plan_version or binding.get("plan_sha256") != plan_sha256:
            raise ProjectionError(f"draft_preview rendered binding plan mismatch for {path!r}")
        if binding.get("slide_record_id") != rendered_entries[path]["slide_record_id"] or binding.get("attempt") != rendered_entries[path]["attempt"]:
            raise ProjectionError(f"draft_preview rendered binding attempt mismatch for {path!r}")
        _require_text(binding.get("producer_id"), f"draft_preview producer {path!r}")
        if producer_id is None:
            producer_id = binding["producer_id"]
        elif producer_id != binding["producer_id"]:
            raise ProjectionError("draft_preview producer bindings are inconsistent")
    _require_digest(artifact_digests[contact_path], f"draft_preview digest {contact_path!r}")
    contact = _mapping(artifact_bindings[contact_path], "draft_preview contact binding")
    _require_exact_fields(
        contact,
        frozenset(
            {
                "kind",
                "deck_id",
                "plan_version",
                "plan_sha256",
                "producer_id",
                "source_paths",
                "source_sha256",
            }
        ),
        "draft_preview contact binding",
    )
    if contact.get("kind") != "contact_sheet" or contact.get("deck_id") != deck_id:
        raise ProjectionError("draft_preview contact binding identity mismatch")
    if contact.get("plan_version") != plan_version or contact.get("plan_sha256") != plan_sha256:
        raise ProjectionError("draft_preview contact binding plan mismatch")
    if contact.get("source_paths") != rendered_paths:
        raise ProjectionError("draft_preview contact source path order mismatch")
    _require_text(contact.get("producer_id"), "draft_preview contact producer")
    if producer_id != contact["producer_id"]:
        raise ProjectionError("draft_preview contact producer binding mismatch")
    _require_digest(contact.get("source_sha256"), "draft_preview contact source_sha256")
    expected_source_sha256 = _canonical_digest(
        {"paths": rendered_paths, "digests": [artifact_digests[path] for path in rendered_paths]},
        "draft_preview contact source",
    )
    if contact["source_sha256"] != expected_source_sha256:
        raise ProjectionError("draft_preview contact source digest mismatch")
    assert producer_id is not None
    return rendered_paths, subject_ids, producer_id


def _resolve_historical_plan_id(
    snapshot: EvidenceSnapshot,
    deck_id: str,
    plan_version: int,
    plan_sha256: str,
    declared_plan_id: object,
) -> str:
    """Resolve one existing historical plan identity without using active state."""
    if declared_plan_id is not None:
        _require_text(declared_plan_id, "historical plan_id")
    plans = snapshot.stores.get("plans", {})
    matches: list[str] = []
    for plan_id, frozen_plan in plans.items():
        plan = _thaw(frozen_plan)
        if not isinstance(plan, dict):
            raise ProjectionError("historical plan store record must be a mapping")
        version = plan.get("version", plan.get("plan_version"))
        digest = plan.get("plan_sha256", plan.get("sha256"))
        if (
            plan.get("deck_id") == deck_id
            and version == plan_version
            and digest == plan_sha256
        ):
            matches.append(plan_id)
    if declared_plan_id is not None:
        if declared_plan_id not in matches:
            raise ProjectionError("declared historical plan_id has no matching immutable record")
        return declared_plan_id
    if len(matches) != 1:
        raise ProjectionError("historical event requires exactly one matching plan record")
    return matches[0]


def _artifact_references(
    snapshot: EvidenceSnapshot,
    artifact_digests: Mapping[str, Any],
    bindings: list[tuple[str, str, str]],
) -> tuple[list[dict[str, str]], dict[str, CasObject], str]:
    """Build references from frozen bytes without loading source paths again."""
    artifact_refs: list[dict[str, str]] = []
    event_objects: dict[str, CasObject] = {}
    availability = "available"
    for path, artifact_kind, subject_id in bindings:
        declared_digest = artifact_digests.get(path)
        _require_digest(declared_digest, f"artifact digest {path!r}")
        object_ = snapshot.artifact_objects.get(path)
        if object_ is None:
            availability = "historical_unavailable"
        elif object_.digest != declared_digest:
            raise ProjectionError(f"historical artifact digest mismatch for {path!r}")
        else:
            event_objects[object_.digest] = object_
        artifact_refs.append(
            {
                "sha256": declared_digest,
                "cas_path": cas_relative_path(declared_digest).as_posix(),
                "artifact_kind": artifact_kind,
                "subject_id": subject_id,
                "original_path": path,
            }
        )
    if availability == "historical_unavailable":
        return artifact_refs, {}, availability
    return artifact_refs, event_objects, availability


def _base_envelope(
    event: Mapping[str, Any],
    *,
    evidence_kind: str,
    deck_id: str,
    plan_id: str,
    plan_version: int,
    plan_sha256: str,
    subject_ids: list[str],
    producer_id: str,
    artifact_refs: list[dict[str, str]],
    availability: str,
) -> dict[str, Any]:
    """Build and validate one envelope through the shared contract authority."""
    envelope: dict[str, Any] = {
        "id": event["id"],
        "schema_version": 2,
        "evidence_kind": evidence_kind,
        "deck_id": deck_id,
        "plan_id": plan_id,
        "plan_version": plan_version,
        "plan_sha256": plan_sha256,
        "subject_ids": subject_ids,
        "producer_id": producer_id,
        "artifact_refs": artifact_refs,
        "source_event_id": event["id"],
        "created_at": event["ts"],
        "availability": availability,
    }
    envelope["evidence_sha256"] = envelope_sha256(envelope)
    return envelope


def _validated_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the shared contract's typed error at the projection boundary."""
    try:
        return validate_envelope(envelope)
    except EvidenceContractError as exc:
        raise ProjectionError(f"invalid projected evidence envelope: {exc}") from exc


def _current_pointer_ids(snapshot: EvidenceSnapshot) -> frozenset[str]:
    """Return declared current pointer IDs without validating current state."""
    pointer_fields = (
        "draft_preview_evidence_id",
        "draft_approval_evidence_id",
        "completion_evidence_id",
    )
    pointer_ids: set[str] = set()
    for frozen_deck in snapshot.stores.get("decks", {}).values():
        deck = _thaw(frozen_deck)
        if not isinstance(deck, dict):
            raise ProjectionError("deck store record must be a mapping")
        for field in pointer_fields:
            value = deck.get(field)
            if value is None:
                continue
            _require_text(value, f"deck.{field}")
            pointer_ids.add(value)
    return frozenset(pointer_ids)


def _require_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str], label: str
) -> None:
    """Require one historical event or binding to use its exact field set."""
    actual = set(value)
    if actual != expected:
        raise ProjectionError(
            f"{label} fields are invalid: missing {sorted(expected - actual)}, "
            f"unknown {sorted(actual - expected)}"
        )


def _require_text(value: object, field: str) -> None:
    """Require one trimmed, non-empty text value."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProjectionError(f"{field} must be a trimmed non-empty string")


def _require_positive_int(value: object, field: str) -> None:
    """Require one positive integral field while rejecting booleans."""
    if type(value) is not int or value <= 0:
        raise ProjectionError(f"{field} must be a positive integer")


def _require_exact_int(value: object, expected: int, field: str) -> None:
    """Require one exact integer while rejecting booleans and other types."""
    if type(value) is not int or value != expected:
        raise ProjectionError(f"{field} must be integer {expected}")


def _require_digest(value: object, field: str) -> None:
    """Require one lowercase hexadecimal SHA-256 digest."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _SHA256_HEX for character in value)
    ):
        raise ProjectionError(f"{field} must be a lowercase SHA-256 digest")


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    """Require one string-keyed mapping value."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ProjectionError(f"{field} must be a string-keyed mapping")
    return value


def _canonical_path(value: object, field: str) -> str:
    """Validate one intrinsic event path without requiring its live bytes."""
    try:
        return canonical_relative_path(value)
    except MigrationError as exc:
        raise ProjectionError(f"{field} is invalid: {exc}") from exc


def _canonical_digest(value: Mapping[str, Any], label: str) -> str:
    """Return one canonical payload digest or raise a typed projection error."""
    try:
        return contract_sha256(value)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProjectionError(f"{label} cannot be canonically hashed: {exc}") from exc


def _thaw(value: Any) -> Any:
    """Return a mutable local copy of a frozen snapshot value."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return {_thaw(item) for item in value}
    return value
