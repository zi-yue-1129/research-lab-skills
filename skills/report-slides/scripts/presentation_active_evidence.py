"""Current-pointer validation for immutable report-slides evidence.

Historical projection establishes whether an envelope is intrinsically valid.
This module separately evaluates only evidence explicitly selected by current
deck pointers, using the already-frozen snapshot and no live filesystem reads.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from migration_scope import MigrationError, canonical_relative_path
from presentation_contracts import contract_sha256
from presentation_evidence_cas import CasObject
from presentation_evidence_contracts import EvidenceContractError, validate_envelope
from presentation_evidence_snapshot import EvidenceSnapshot, parse_yaml_document, thaw
from validate_deck_plan import validate_deck_approval
from validate_visual_review import derive_overall_status, validate_review_document

if TYPE_CHECKING:
    from presentation_evidence_projection import HistoricalProjection


@dataclass(frozen=True)
class ActiveEvidenceProjection:
    """Current pointer updates and fail-closed blockers by deck.

    Attributes:
        pointer_updates: Deterministic deck-field updates required for a
            revision clear or unambiguous legacy completion binding.
        blockers: Deterministic current-evidence validation failures by deck.
    """

    pointer_updates: Mapping[str, Mapping[str, str | None]]
    blockers: Mapping[str, tuple[Mapping[str, Any], ...]]

    @property
    def completion_pointer_updates(self) -> Mapping[str, Mapping[str, str | None]]:
        """Return only updates that bind a completion evidence pointer.

        Returns:
            Immutable completion-pointer updates keyed by deck ID.
        """
        return MappingProxyType(
            {
                deck_id: update
                for deck_id, update in self.pointer_updates.items()
                if update.get("completion_evidence_id") is not None
            }
        )


def project_active_evidence(
    snapshot: EvidenceSnapshot,
    history: HistoricalProjection,
) -> ActiveEvidenceProjection:
    """Validate pointer-selected evidence against current frozen state.

    Args:
        snapshot: Immutable state, source bytes, and artifact capture.
        history: Historical projection exposing immutable envelopes and CAS
            objects. A structural protocol is used to avoid a circular import.

    Returns:
        Current pointer updates and deterministic fail-closed deck blockers.

    Raises:
        TypeError: If the supplied snapshot or historical projection is not
            structurally suitable for current validation.
    """
    if not isinstance(snapshot, EvidenceSnapshot):
        raise TypeError("snapshot must be an EvidenceSnapshot")
    envelopes = merged_envelopes(snapshot, history)
    objects = _cas_objects(snapshot, history)
    updates: dict[str, Mapping[str, str | None]] = {}
    blockers_by_deck: dict[str, tuple[Mapping[str, Any], ...]] = {}
    decks = snapshot.stores.get("decks", {})
    for deck_id in sorted(decks):
        deck = _mapping(decks[deck_id])
        if deck.get("id") != deck_id:
            blockers_by_deck[deck_id] = ({"reason": "active_deck_identity_mismatch"},)
            continue
        revision_clear = _revision_pointer_clear(snapshot, deck_id, deck)
        if revision_clear:
            updates[deck_id] = MappingProxyType(revision_clear)
            continue
        if not _requires_current_validation(deck):
            continue
        plan, plan_blockers = _current_plan(snapshot, deck_id, deck)
        if plan_blockers:
            blockers_by_deck[deck_id] = _ordered_blockers(plan_blockers)
            continue
        assert plan is not None
        current_slides, slide_blockers = _current_passed_slides(
            snapshot, deck_id, plan
        )
        if slide_blockers:
            blockers_by_deck[deck_id] = _ordered_blockers(slide_blockers)
            continue
        deck_blockers = _validate_selected_evidence(
            snapshot, deck_id, deck, plan, current_slides, envelopes, objects
        )
        if deck_blockers:
            blockers_by_deck[deck_id] = _ordered_blockers(deck_blockers)
            continue
        legacy_update, legacy_blockers = _legacy_completion_update(
            snapshot, deck_id, deck, plan, current_slides, envelopes, objects
        )
        if legacy_blockers:
            blockers_by_deck[deck_id] = _ordered_blockers(legacy_blockers)
        elif legacy_update:
            updates[deck_id] = MappingProxyType(legacy_update)
    return ActiveEvidenceProjection(
        pointer_updates=MappingProxyType(dict(updates)),
        blockers=MappingProxyType(dict(blockers_by_deck)),
    )


def merged_envelopes(
    snapshot: EvidenceSnapshot, history: Any
) -> Mapping[str, Mapping[str, Any]]:
    """Merge frozen persisted and historical envelopes without latest-wins.

    An envelope is retained only when every source that declares its ID agrees
    on the exact immutable content, so a disagreeing pair fails closed by
    dropping the ID entirely rather than preferring either source.

    Args:
        snapshot: Frozen state whose evidence store may hold persisted
            envelopes.
        history: Historical projection exposing an ``envelopes`` mapping.

    Returns:
        Immutable validated envelopes keyed by evidence ID.

    Raises:
        TypeError: If the historical projection or evidence store is not a
            mapping.
    """
    historical = getattr(history, "envelopes", None)
    if not isinstance(historical, Mapping):
        raise TypeError("history must expose an envelopes mapping")
    result: dict[str, Mapping[str, Any]] = {}
    for source in (snapshot.stores.get("evidence", {}), historical):
        if not isinstance(source, Mapping):
            raise TypeError("evidence stores must be mappings")
        for evidence_id in sorted(source):
            raw = source[evidence_id]
            if not isinstance(evidence_id, str) or not isinstance(raw, Mapping):
                continue
            try:
                envelope = validate_envelope(thaw(raw))
            except EvidenceContractError:
                continue
            if envelope["id"] != evidence_id:
                continue
            prior = result.get(evidence_id)
            if prior is not None and prior != envelope:
                result.pop(evidence_id, None)
                continue
            result[evidence_id] = MappingProxyType(envelope)
    return MappingProxyType(result)


def _cas_objects(snapshot: EvidenceSnapshot, history: Any) -> Mapping[str, CasObject]:
    """Return only frozen CAS objects whose digest equals their content hash."""
    historical = getattr(history, "cas_objects", None)
    if not isinstance(historical, Mapping):
        raise TypeError("history must expose a cas_objects mapping")
    result: dict[str, CasObject] = {}
    candidates = list(snapshot.artifact_objects.values()) + list(historical.values())
    for object_ in candidates:
        if not isinstance(object_, CasObject):
            continue
        if hashlib.sha256(object_.content).hexdigest() != object_.digest:
            continue
        prior = result.get(object_.digest)
        if prior is None:
            result[object_.digest] = object_
        elif prior.content != object_.content:
            result.pop(object_.digest, None)
    return MappingProxyType(result)


def _current_plan(
    snapshot: EvidenceSnapshot, deck_id: str, deck: Mapping[str, Any]
) -> tuple[Mapping[str, Any] | None, list[Mapping[str, Any]]]:
    """Validate and parse the exact snapshot-captured approved plan."""
    plan_id = deck.get("current_plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        return None, [{"reason": "active_current_plan_missing"}]
    plan_record = snapshot.stores.get("plans", {}).get(plan_id)
    if not isinstance(plan_record, Mapping) or plan_record.get("id") != plan_id:
        return None, [{"reason": "active_current_plan_missing"}]
    preimage = snapshot.active_plan_preimages.get(plan_id)
    if preimage is None:
        return None, [{"reason": "active_plan_bytes_unavailable"}]
    if (
        preimage.path != plan_record.get("plan_path")
        or hashlib.sha256(preimage.content).hexdigest() != preimage.sha256
    ):
        return None, [{"reason": "active_plan_preimage_invalid"}]
    try:
        plan = parse_yaml_document(snapshot.project_root / preimage.path, preimage.content)
    except Exception:
        return None, [{"reason": "active_plan_document_invalid"}]
    digest = contract_sha256(plan)
    expected_digest = deck.get("approved_plan_sha256")
    if (
        plan.get("deck_id") != deck_id
        or plan_record.get("deck_id") != deck_id
        or type(plan.get("plan_version")) is not int
        or plan.get("plan_version") <= 0
        or type(deck.get("approved_plan_version")) is not int
        or type(plan_record.get("version")) is not int
        or plan.get("plan_version") != deck.get("approved_plan_version")
        or plan_record.get("version") != plan.get("plan_version")
        or plan_record.get("plan_sha256") != digest
        or expected_digest != digest
    ):
        return None, [{"reason": "active_approved_plan_mismatch"}]
    return plan, []


def _current_passed_slides(
    snapshot: EvidenceSnapshot, deck_id: str, plan: Mapping[str, Any]
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Return exact active passed slides in approved plan order."""
    plan_slides = plan.get("slides")
    if not isinstance(plan_slides, list):
        return [], [{"reason": "active_approved_plan_mismatch"}]
    expected_ids: list[str] = []
    for slide in plan_slides:
        if not isinstance(slide, Mapping) or not isinstance(slide.get("slide_id"), str):
            return [], [{"reason": "active_approved_plan_mismatch"}]
        expected_ids.append(slide["slide_id"])
    active = [
        _mapping(record)
        for record in snapshot.stores.get("slides", {}).values()
        if isinstance(record, Mapping)
        and record.get("deck_id") == deck_id
        and record.get("status") != "superseded"
    ]
    by_plan_id = {record.get("plan_slide_id"): record for record in active}
    if (
        len(active) != len(expected_ids)
        or len(by_plan_id) != len(active)
        or set(by_plan_id) != set(expected_ids)
    ):
        return [], [{"reason": "active_preview_slide_set_mismatch"}]
    ordered = [by_plan_id[slide_id] for slide_id in expected_ids]
    if any(
        record.get("status") != "passed"
        or not isinstance(record.get("id"), str)
        or type(record.get("attempt")) is not int
        or record.get("attempt") <= 0
        for record in ordered
    ):
        return [], [{"reason": "active_preview_slide_not_passed"}]
    return ordered, []


def _validate_selected_evidence(
    snapshot: EvidenceSnapshot,
    deck_id: str,
    deck: Mapping[str, Any],
    plan: Mapping[str, Any],
    slides: list[Mapping[str, Any]],
    envelopes: Mapping[str, Mapping[str, Any]],
    objects: Mapping[str, CasObject],
) -> list[Mapping[str, Any]]:
    """Validate only pointers explicitly stored on one current deck."""
    plan_id = deck.get("current_plan_id")
    if not isinstance(plan_id, str) or not plan_id or plan_id != plan_id.strip():
        return [{"reason": "active_current_plan_missing"}]
    preview_id = deck.get("draft_preview_evidence_id")
    approval_id = deck.get("draft_approval_evidence_id")
    completion_id = deck.get("completion_evidence_id")
    if preview_id is None and approval_id is None and completion_id is None:
        return []
    preview = _selected_envelope(envelopes, preview_id, "draft_preview", deck_id)
    if preview is None:
        return [{"reason": "active_preview_evidence_invalid"}]
    if not _exact_plan_binding(preview, plan, deck_id, plan_id):
        return [{"reason": "active_preview_plan_mismatch"}]
    preview_blockers = _validate_preview(snapshot, preview, plan, slides, objects)
    if preview_blockers:
        return preview_blockers
    if approval_id is None and completion_id is None:
        return []
    approval = _selected_envelope(envelopes, approval_id, "draft_approval", deck_id)
    if approval is None or not _exact_plan_binding(
        approval, plan, deck_id, plan_id
    ):
        return [{"reason": "active_approval_evidence_invalid"}]
    if (
        approval.get("decision") != "approved"
        or approval.get("preview_evidence_id") != preview["id"]
        or approval.get("preview_evidence_sha256") != preview["evidence_sha256"]
    ):
        return [{"reason": "active_approval_preview_mismatch"}]
    if not _approval_source_valid(snapshot, approval, plan, plan_id):
        return [{"reason": "active_approval_source_invalid"}]
    if completion_id is None:
        return []
    completion = _selected_envelope(envelopes, completion_id, "deck_completion", deck_id)
    if completion is None or not _exact_plan_binding(
        completion, plan, deck_id, plan_id
    ):
        return [{"reason": "active_completion_evidence_invalid"}]
    if (
        completion.get("approval_evidence_id") != approval["id"]
        or completion.get("approval_evidence_sha256") != approval["evidence_sha256"]
    ):
        return [{"reason": "active_completion_approval_mismatch"}]
    review = _selected_envelope(
        envelopes,
        completion.get("visual_review_evidence_id"),
        "visual_review",
        deck_id,
    )
    if review is None or not _exact_plan_binding(review, plan, deck_id, plan_id):
        return [{"reason": "active_completion_visual_review_invalid"}]
    if completion.get("visual_review_evidence_sha256") != review["evidence_sha256"]:
        return [{"reason": "active_completion_visual_review_mismatch"}]
    if not _completion_source_valid(snapshot, completion, plan, plan_id):
        return [{"reason": "active_completion_evidence_invalid"}]
    review_paths = _completion_review_paths(snapshot, review, plan, plan_id)
    if review_paths is None:
        return [{"reason": "active_completion_visual_review_invalid"}]
    if not _completion_artifacts_valid(snapshot, completion, objects, review_paths):
        return [{"reason": "active_completion_artifacts_invalid"}]
    return []


def _validate_preview(
    snapshot: EvidenceSnapshot,
    preview: Mapping[str, Any],
    plan: Mapping[str, Any],
    slides: list[Mapping[str, Any]],
    objects: Mapping[str, CasObject],
) -> list[Mapping[str, Any]]:
    """Validate preview source metadata, artifacts, records, and CAS bytes."""
    source = _source_event(snapshot, preview.get("source_event_id"), "draft_preview")
    if source is None:
        return [{"reason": "active_preview_source_unavailable"}]
    from presentation_evidence_projection import ProjectionError, project_preview_evidence

    if (
        source.get("deck_id") != preview.get("deck_id")
        or type(source.get("plan_version")) is not int
        or source.get("plan_version") != plan.get("plan_version")
        or source.get("plan_sha256") != contract_sha256(plan)
    ):
        return [{"reason": "active_preview_source_invalid"}]
    entries = source.get("rendered_slide_paths")
    metadata = source.get("slides")
    if not isinstance(entries, (list, tuple)) or not isinstance(
        metadata, (list, tuple)
    ):
        return [{"reason": "active_preview_source_invalid"}]
    expected_ids = [record["plan_slide_id"] for record in slides]
    if [entry.get("slide_id") if isinstance(entry, Mapping) else None for entry in entries] != expected_ids:
        return [{"reason": "active_preview_slide_set_mismatch"}]
    if [entry.get("slide_id") if isinstance(entry, Mapping) else None for entry in metadata] != expected_ids:
        return [{"reason": "active_preview_slide_set_mismatch"}]
    planned = {item.get("slide_id"): item for item in plan.get("slides", []) if isinstance(item, Mapping)}
    for entry, meta, record in zip(entries, metadata, slides):
        if not isinstance(entry, Mapping) or not isinstance(meta, Mapping):
            return [{"reason": "active_preview_source_invalid"}]
        if (
            entry.get("slide_record_id") != record["id"]
            or entry.get("attempt") != record["attempt"]
            or meta.get("title") != planned[record["plan_slide_id"]].get("title")
            or meta.get("key_takeaway") != planned[record["plan_slide_id"]].get("key_takeaway")
        ):
            return [{"reason": "active_preview_metadata_mismatch"}]
    references = preview.get("artifact_refs")
    if not isinstance(references, list) or len(references) != len(slides) + 1:
        return [{"reason": "active_preview_artifacts_invalid"}]
    if not _preview_source_artifacts_valid(source, preview, entries, references):
        return [{"reason": "active_preview_source_artifacts_invalid"}]
    try:
        projected_source = project_preview_evidence(snapshot, source)
    except ProjectionError:
        return [{"reason": "active_preview_source_invalid"}]
    comparable_fields = (
        "evidence_kind", "deck_id", "plan_id", "plan_version", "plan_sha256",
        "subject_ids", "producer_id", "artifact_refs", "source_event_id",
        "created_at", "availability",
    )
    if any(projected_source[field] != preview[field] for field in comparable_fields):
        return [{"reason": "active_preview_source_invalid"}]
    for index, record in enumerate(slides):
        ref = references[index]
        if not _artifact_valid(
            snapshot, ref, objects, record, "rendered_slide", "slide-png", preview["deck_id"]
        ):
            return [{"reason": "active_preview_artifacts_invalid"}]
    if not _artifact_valid(
        snapshot, references[-1], objects, None, "contact_sheet", "review-sheet", preview["deck_id"]
    ):
        return [{"reason": "active_preview_artifacts_invalid"}]
    return []


def _preview_source_artifacts_valid(
    source: Mapping[str, Any],
    preview: Mapping[str, Any],
    entries: list[Any] | tuple[Any, ...],
    references: list[Any],
) -> bool:
    """Require exact source paths, digests, and preview artifact bindings."""
    try:
        rendered_paths = [canonical_relative_path(entry.get("path")) for entry in entries]
        contact_path = canonical_relative_path(source.get("contact_sheet_path"))
    except (AttributeError, MigrationError):
        return False
    expected_paths = [*rendered_paths, contact_path]
    if [reference.get("original_path") for reference in references] != expected_paths:
        return False
    digests = source.get("artifact_digests")
    bindings = source.get("artifact_bindings")
    if not isinstance(digests, Mapping) or not isinstance(bindings, Mapping):
        return False
    if set(digests) != set(expected_paths) or set(bindings) != set(expected_paths):
        return False
    if any(digests[path] != reference.get("sha256") for path, reference in zip(expected_paths, references)):
        return False
    for path, entry in zip(rendered_paths, entries):
        expected = {
            "kind": "rendered_slide",
            "deck_id": preview["deck_id"],
            "slide_id": entry["slide_id"],
            "plan_version": preview["plan_version"],
            "plan_sha256": preview["plan_sha256"],
            "producer_id": preview["producer_id"],
            "slide_record_id": entry["slide_record_id"],
            "attempt": entry["attempt"],
        }
        if bindings[path] != expected:
            return False
    contact_binding = bindings[contact_path]
    if not isinstance(contact_binding, Mapping):
        return False
    contact_expected = {
        "kind": "contact_sheet",
        "deck_id": preview["deck_id"],
        "plan_version": preview["plan_version"],
        "plan_sha256": preview["plan_sha256"],
        "producer_id": preview["producer_id"],
        "source_sha256": contract_sha256(
            {"paths": rendered_paths, "digests": [digests[path] for path in rendered_paths]}
        ),
    }
    if set(contact_binding) != {*contact_expected, "source_paths"}:
        return False
    if contact_binding.get("source_paths") not in (rendered_paths, tuple(rendered_paths)):
        return False
    return all(contact_binding.get(key) == value for key, value in contact_expected.items())


def _artifact_valid(
    snapshot: EvidenceSnapshot,
    reference: object,
    objects: Mapping[str, CasObject],
    slide: Mapping[str, Any] | None,
    evidence_kind: str,
    record_kind: str,
    deck_id: str,
) -> bool:
    """Require one artifact reference, persisted record, and CAS byte match."""
    if not isinstance(reference, Mapping) or reference.get("artifact_kind") != evidence_kind:
        return False
    digest = reference.get("sha256")
    path = reference.get("original_path")
    if not isinstance(digest, str) or not isinstance(path, str):
        return False
    object_ = objects.get(digest)
    if object_ is None or object_.digest != digest:
        return False
    matches = [
        record
        for record in snapshot.stores.get("artifacts", {}).values()
        if isinstance(record, Mapping)
        and record.get("deck_id") == deck_id
        and record.get("artifact_kind") == record_kind
        and record.get("path") == path
        and record.get("sha256") == digest
    ]
    if len(matches) != 1:
        return False
    if slide is not None:
        record = matches[0]
        return (
            reference.get("subject_id") == slide.get("plan_slide_id")
            and record.get("slide_record_id") == slide.get("id")
            and record.get("attempt") == slide.get("attempt")
        )
    return True


def _completion_artifacts_valid(
    snapshot: EvidenceSnapshot,
    completion: Mapping[str, Any],
    objects: Mapping[str, CasObject],
    review_paths: tuple[str, tuple[str, ...]],
) -> bool:
    """Require the exact review-authorized completion artifact set.

    Args:
        snapshot: Frozen state containing persisted artifact records.
        completion: Pointer-selected completion envelope.
        objects: Digest-keyed frozen CAS objects.
        review_paths: Authoritative final-PPTX and rendered-PNG paths derived
            from a completion-authorizing frozen visual review.

    Returns:
        True only when record, reference, order, and CAS bytes exactly match
        the review-authorized final output set.
    """
    references = completion.get("artifact_refs")
    final_path, rendered_paths = review_paths
    if not isinstance(references, list) or len(references) != len(rendered_paths) + 1:
        return False
    deck_id = completion.get("deck_id")
    if not isinstance(deck_id, str):
        return False
    if (
        not isinstance(references[0], Mapping)
        or references[0].get("original_path") != final_path
        or not _artifact_valid(
            snapshot,
            references[0],
            objects,
            None,
            "final_pptx",
            "deck-pptx",
            deck_id,
        )
    ):
        return False
    for reference, expected_path in zip(references[1:], rendered_paths):
        if (
            not isinstance(reference, Mapping)
            or reference.get("original_path") != expected_path
            or not _artifact_valid(
                snapshot,
                reference,
                objects,
                None,
                "rendered_png",
                "slide-png",
                deck_id,
            )
        ):
            return False
    return True


def _approval_source_valid(
    snapshot: EvidenceSnapshot,
    approval: Mapping[str, Any],
    plan: Mapping[str, Any],
    plan_id: str,
) -> bool:
    """Validate the immutable source decision for an active approval.

    Args:
        snapshot: Frozen events used to resolve the approval source.
        approval: Pointer-selected draft-approval envelope.
        plan: Frozen current approved plan.

    Returns:
        True when the source decision is explicit, identity-valid, and binds
        the exact envelope and current plan.
    """
    source = _event_by_id(snapshot, approval.get("source_event_id"))
    if source is None or source.get("event") != "deck_approval":
        return False
    if validate_deck_approval(dict(source)) or source.get("decision") != "approve":
        return False
    approved_by = source.get("approved_by")
    approval_mode = source.get("approval_mode")
    if (
        approved_by != approval.get("approved_by")
        or approval_mode != approval.get("approval_mode")
        or source.get("deck_id") != approval.get("deck_id")
        or source.get("plan_id") != approval.get("plan_id")
        or source.get("plan_id") != plan_id
        or source.get("plan_version") != plan.get("plan_version")
        or source.get("plan_sha256") != contract_sha256(plan)
    ):
        return False
    if approval_mode == "interactive":
        return (
            isinstance(approved_by, str)
            and approved_by == approved_by.strip()
            and approved_by.casefold()
            not in {"auto", "system", "agent", "unknown", "--yes-draft", "workflow"}
        )
    return approval_mode == "explicit_noninteractive"


def _completion_review_paths(
    snapshot: EvidenceSnapshot,
    review: Mapping[str, Any],
    plan: Mapping[str, Any],
    plan_id: str,
) -> tuple[str, tuple[str, ...]] | None:
    """Return exact final/render paths from a completion-authorizing review.

    Args:
        snapshot: Frozen source events and review-document bytes.
        review: Pointer-selected visual-review envelope.
        plan: Frozen current approved plan.

    Returns:
        The final PPTX followed by ordered rendered PNG paths, or None when
        the source event/document cannot authorize completion.
    """
    source = _event_by_id(snapshot, review.get("source_event_id"))
    if source is None or source.get("event") != "visual_review":
        return None
    if (
        source.get("deck_id") != review.get("deck_id")
        or source.get("plan_id") != review.get("plan_id")
        or source.get("plan_id") != plan_id
        or source.get("plan_version") != plan.get("plan_version")
        or source.get("plan_sha256") != contract_sha256(plan)
    ):
        return None
    try:
        review_path = canonical_relative_path(source.get("visual_review_path"))
    except MigrationError:
        return None
    content = snapshot.file_preimages.get(snapshot.project_root / review_path)
    if content is None:
        return None
    try:
        document = _parse_review_document(content)
        if source.get("visual_review_sha256") != contract_sha256(document):
            return None
        issues = validate_review_document(document)
        status = derive_overall_status(document)
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        issues
        or status.status != "passed"
        or not status.completion_allowed
        or status.authority != "pptx-render"
        or document.get("deck_id") != review.get("deck_id")
        or document.get("output_format") != "pptx"
    ):
        return None
    try:
        artifacts = _mapping(document.get("artifacts"))
        statuses = _mapping(document.get("statuses"))
        render_status = _mapping(statuses.get("pptx_render"))
        final_path = canonical_relative_path(artifacts.get("pptx"))
        rendered = render_status.get("rendered_png_paths")
        if not isinstance(rendered, list) or not rendered:
            return None
        rendered_paths = tuple(canonical_relative_path(path) for path in rendered)
    except MigrationError:
        return None
    if (
        render_status.get("status") != "passed"
        or len(set(rendered_paths)) != len(rendered_paths)
        or any(not path.endswith(".png") for path in rendered_paths)
        or final_path in rendered_paths
    ):
        return None
    return final_path, rendered_paths


def _completion_source_valid(
    snapshot: EvidenceSnapshot,
    completion: Mapping[str, Any],
    plan: Mapping[str, Any],
    plan_id: str,
) -> bool:
    """Require one completion source event bound to the exact current plan."""
    source = _event_by_id(snapshot, completion.get("source_event_id"))
    return bool(
        source is not None
        and source.get("event") == "deck_completion"
        and source.get("deck_id") == completion.get("deck_id")
        and source.get("plan_id") == completion.get("plan_id")
        and source.get("plan_id") == plan_id
        and type(source.get("plan_version")) is int
        and source.get("plan_version") == plan.get("plan_version")
        and source.get("plan_sha256") == contract_sha256(plan)
    )


def _parse_review_document(content: bytes) -> Mapping[str, Any]:
    """Parse frozen JSON review bytes while rejecting duplicate keys.

    Args:
        content: Exact immutable review-document bytes.

    Returns:
        The parsed mapping.

    Raises:
        ValueError: If the bytes are not a duplicate-free JSON object.
    """
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        """Build a JSON mapping while rejecting duplicate keys."""
        parsed: dict[str, Any] = {}
        for key, value in items:
            if key in parsed:
                raise ValueError(f"duplicate JSON key {key!r}")
            parsed[key] = value
        return parsed

    value = json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    if not isinstance(value, Mapping):
        raise ValueError("visual review document must be a mapping")
    return value


def _event_by_id(
    snapshot: EvidenceSnapshot, event_id: object
) -> Mapping[str, Any] | None:
    """Resolve one frozen audit event by exact ID without fallback selection."""
    if not isinstance(event_id, str) or not event_id:
        return None
    for event in snapshot.events:
        if event.get("id") == event_id:
            return event
    return None


def _legacy_completion_update(
    snapshot: EvidenceSnapshot,
    deck_id: str,
    deck: Mapping[str, Any],
    plan: Mapping[str, Any],
    slides: list[Mapping[str, Any]],
    envelopes: Mapping[str, Mapping[str, Any]],
    objects: Mapping[str, CasObject],
) -> tuple[dict[str, str | None], list[Mapping[str, Any]]]:
    """Infer exactly one legacy completion candidate without latest-wins."""
    if deck.get("status") != "completed" or deck.get("completion_evidence_id") is not None:
        return {}, []
    plan_id = deck.get("current_plan_id")
    if not isinstance(plan_id, str) or not plan_id or plan_id != plan_id.strip():
        return {}, [{"reason": "missing_completion_evidence"}]
    candidates = [
        envelope
        for envelope in envelopes.values()
        if envelope.get("evidence_kind") == "deck_completion"
        and envelope.get("deck_id") == deck_id
        and _exact_plan_binding(envelope, plan, deck_id, plan_id)
        and _legacy_completion_valid(
            snapshot, envelope, envelopes, plan, plan_id, slides, deck_id, objects
        )
    ]
    if len(candidates) == 1:
        return {"completion_evidence_id": candidates[0]["id"]}, []
    if not candidates:
        return {}, [{"reason": "missing_completion_evidence"}]
    return {}, [{"reason": "ambiguous_completion_evidence"}]


def _legacy_completion_valid(
    snapshot: EvidenceSnapshot,
    completion: Mapping[str, Any],
    envelopes: Mapping[str, Mapping[str, Any]],
    plan: Mapping[str, Any],
    plan_id: str,
    slides: list[Mapping[str, Any]],
    deck_id: str,
    objects: Mapping[str, CasObject],
) -> bool:
    """Return whether a legacy completion is fully current-verifiable."""
    approval = _selected_envelope(
        envelopes, completion.get("approval_evidence_id"), "draft_approval", deck_id
    )
    review = _selected_envelope(
        envelopes,
        completion.get("visual_review_evidence_id"),
        "visual_review",
        deck_id,
    )
    if approval is None or review is None:
        return False
    preview = _selected_envelope(
        envelopes, approval.get("preview_evidence_id"), "draft_preview", deck_id
    )
    if preview is None:
        return False
    if not _exact_plan_binding(preview, plan, deck_id, plan_id):
        return False
    if _validate_preview(snapshot, preview, plan, slides, objects):
        return False
    if not (
        _exact_plan_binding(approval, plan, deck_id, plan_id)
        and _exact_plan_binding(review, plan, deck_id, plan_id)
        and approval.get("decision") == "approved"
        and approval.get("preview_evidence_sha256") == preview.get("evidence_sha256")
        and completion.get("approval_evidence_sha256") == approval.get("evidence_sha256")
        and completion.get("visual_review_evidence_sha256") == review.get("evidence_sha256")
        and _approval_source_valid(snapshot, approval, plan, plan_id)
        and _completion_source_valid(snapshot, completion, plan, plan_id)
    ):
        return False
    review_paths = _completion_review_paths(snapshot, review, plan, plan_id)
    return review_paths is not None and _completion_artifacts_valid(
        snapshot, completion, objects, review_paths
    )


def _selected_envelope(
    envelopes: Mapping[str, Mapping[str, Any]],
    evidence_id: object,
    kind: str,
    deck_id: str,
) -> Mapping[str, Any] | None:
    """Resolve one available typed envelope without fallback selection."""
    if not isinstance(evidence_id, str) or not evidence_id:
        return None
    envelope = envelopes.get(evidence_id)
    if envelope is None:
        return None
    if (
        envelope.get("evidence_kind") != kind
        or envelope.get("deck_id") != deck_id
        or envelope.get("availability") != "available"
    ):
        return None
    return envelope


def _exact_plan_binding(
    envelope: Mapping[str, Any],
    plan: Mapping[str, Any],
    deck_id: str,
    plan_id: str,
) -> bool:
    """Return whether one envelope binds the exact selected approved plan."""
    return (
        envelope.get("deck_id") == deck_id
        and isinstance(envelope.get("plan_id"), str)
        and envelope.get("plan_id") == plan_id
        and envelope.get("plan_id") == str(envelope.get("plan_id")).strip()
        and type(envelope.get("plan_version")) is int
        and envelope.get("plan_version") == plan.get("plan_version")
        and envelope.get("plan_sha256") == contract_sha256(plan)
    )


def _source_event(
    snapshot: EvidenceSnapshot, event_id: object, kind: str
) -> Mapping[str, Any] | None:
    """Return one exact frozen source event by ID and registered kind."""
    if not isinstance(event_id, str):
        return None
    for event in snapshot.events:
        if event.get("id") == event_id and event.get("event") == kind:
            return event
    return None


def _revision_pointer_clear(
    snapshot: EvidenceSnapshot, deck_id: str, deck: Mapping[str, Any]
) -> dict[str, str | None]:
    """Return atomic pointer clears for an explicit current revision.

    Args:
        snapshot: Immutable stores used to identify replacement slide records.
        deck_id: Deck whose pointers may require invalidation.
        deck: Current deck record.

    Returns:
        Every current evidence pointer set to None, or an empty mapping when
        no revision invalidation is present.
    """
    pointers = (
        "draft_preview_evidence_id",
        "draft_approval_evidence_id",
        "completion_evidence_id",
    )
    if not any(deck.get(field) is not None for field in pointers):
        return {}
    if deck.get("required_plan_revision_id") is not None:
        return {field: None for field in pointers}
    for slide in snapshot.stores.get("slides", {}).values():
        if (
            isinstance(slide, Mapping)
            and slide.get("deck_id") == deck_id
            and slide.get("status") != "superseded"
            and slide.get("revision_request_id") is not None
        ):
            return {field: None for field in pointers}
    return {}


def _requires_current_validation(deck: Mapping[str, Any]) -> bool:
    """Return whether a deck selects evidence or requires legacy inference.

    Args:
        deck: One current frozen deck record.

    Returns:
        True only for a pointer-selected deck or a completed legacy deck with
        no completion pointer to infer.
    """
    pointer_fields = (
        "draft_preview_evidence_id",
        "draft_approval_evidence_id",
        "completion_evidence_id",
    )
    if any(deck.get(field) is not None for field in pointer_fields):
        return True
    return deck.get("status") == "completed"


def _mapping(value: object) -> Mapping[str, Any]:
    """Return a mapping or an empty mapping for a malformed frozen record."""
    return value if isinstance(value, Mapping) else MappingProxyType({})


def _ordered_blockers(
    blockers: list[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Return deterministic reason-sorted immutable blocker records."""
    return tuple(
        MappingProxyType(dict(blocker))
        for blocker in sorted(blockers, key=lambda item: str(item.get("reason", "")))
    )
