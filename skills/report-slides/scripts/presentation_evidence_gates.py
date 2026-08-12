#!/usr/bin/env python3
"""Current-pointer and CAS-verified evidence authorization for gates.

Gate entrypoints authorize preview, approval, and completion exclusively from
the evidence pointers stored on a current deck.  One immutable snapshot is
read per authorization; the pointer-selected envelope is validated by the
shared active-evidence projection and its content-addressed bytes are verified
from that same frozen capture.  There is deliberately no schema-v1 event
fallback and no second authorization path.

Completion additionally requires a byte-verified final visual review, which is
validated here so the gate layer never re-reads a raw artifact by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, NoReturn, Sequence

from migration_scope import MigrationError
from presentation_active_evidence import (
    ActiveEvidenceProjection,
    merged_envelopes,
    project_active_evidence,
    thaw_frozen,
)
from presentation_evidence_cas import CasError, read_verified_source
from presentation_evidence_projection import ProjectionError, project_historical_evidence
from presentation_evidence_snapshot import (
    EvidenceCasIntegrityError,
    EvidenceSnapshot,
    SnapshotError,
    build_snapshot,
)
from presentation_events import StateParseError, load_artifacts
from validate_visual_review import derive_overall_status, validate_review_record


EVIDENCE_POINTER_FIELDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "draft_preview": "draft_preview_evidence_id",
        "draft_approval": "draft_approval_evidence_id",
        "deck_completion": "completion_evidence_id",
    }
)
_POINTER_REQUIRED_REASONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "draft_preview": "draft_preview_evidence_pointer_required",
        "draft_approval": "draft_approval_evidence_pointer_required",
        "deck_completion": "completion_evidence_pointer_required",
    }
)
_POINTER_INVALID_REASONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "draft_preview": "draft_preview_evidence_pointer_invalid",
        "draft_approval": "draft_approval_evidence_pointer_invalid",
        "deck_completion": "completion_evidence_pointer_invalid",
    }
)
_GATE_ERROR_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "draft_preview": "DraftGateError",
        "draft_approval": "DraftGateError",
        "deck_completion": "CompletionGateError",
    }
)
_PREDICATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "draft_preview": "current_draft_preview_evidence",
        "draft_approval": "current_draft_approval_evidence",
        "deck_completion": "current_completion_evidence",
    }
)
_SHA256_HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class CurrentEvidence:
    """Pointer-selected verified evidence for one deck in one snapshot.

    Attributes:
        deck: Frozen current deck record, or None when it does not resolve.
        envelopes: Verified envelopes keyed by requested evidence kind. A kind
            is absent whenever it produced any blocker.
        blockers: Deterministic structured gate blockers in requested-kind
            order. A nonempty value always means at least one kind is absent.
    """

    deck: Mapping[str, Any] | None
    envelopes: Mapping[str, Mapping[str, Any]]
    blockers: tuple[dict[str, Any], ...]


def resolve_current_evidence(
    project_root: Path,
    deck_id: str,
    evidence_kinds: Sequence[str],
) -> CurrentEvidence:
    """Resolve every requested current evidence pointer from one snapshot.

    Args:
        project_root: Project root containing schema-v2 presentation state.
        deck_id: Deck whose current evidence pointers authorize the caller.
        evidence_kinds: Registered evidence kinds to resolve, in report order.

    Returns:
        The frozen deck, its verified envelopes, and any structured blockers.

    Raises:
        ValueError: If an evidence kind is not a registered pointer kind.
    """
    kinds = tuple(evidence_kinds)
    for kind in kinds:
        if kind not in EVIDENCE_POINTER_FIELDS:
            raise ValueError(f"unsupported evidence kind: {kind!r}")
    try:
        snapshot = build_snapshot(project_root)
    except EvidenceCasIntegrityError as exc:
        return _unresolved("evidence_cas_digest_mismatch", exc)
    except (SnapshotError, StateParseError, MigrationError) as exc:
        return _unresolved("evidence_snapshot_unavailable", exc)
    try:
        history = project_historical_evidence(snapshot)
    except ProjectionError as exc:
        return _unresolved("evidence_history_unavailable", exc)
    deck = snapshot.stores.get("decks", {}).get(deck_id)
    if not isinstance(deck, Mapping):
        return CurrentEvidence(
            None, MappingProxyType({}), ({"reason": "unknown_deck", "deck_id": deck_id},)
        )
    active = project_active_evidence(snapshot, history)
    invalidation = _revision_invalidation(active, deck_id)
    if invalidation is not None:
        return CurrentEvidence(deck, MappingProxyType({}), (invalidation,))
    absent = tuple(
        {"reason": _POINTER_REQUIRED_REASONS[kind]}
        for kind in kinds
        if not _is_text(deck.get(EVIDENCE_POINTER_FIELDS[kind]))
    )
    if absent:
        return CurrentEvidence(deck, MappingProxyType({}), absent)
    deck_blockers = [dict(blocker) for blocker in active.blockers.get(deck_id, ())]
    if deck_blockers:
        return CurrentEvidence(deck, MappingProxyType({}), tuple(deck_blockers))
    available = merged_envelopes(snapshot, history)
    envelopes: dict[str, Mapping[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    for kind in kinds:
        envelope, kind_blockers = _selected_envelope(
            snapshot, deck, deck_id, kind, available
        )
        if envelope is None:
            blockers.extend(kind_blockers)
            continue
        envelopes[kind] = envelope
    return CurrentEvidence(deck, MappingProxyType(envelopes), tuple(blockers))


def assert_current_evidence(
    project_root: Path,
    deck_id: str,
    evidence_kind: str,
) -> dict[str, Any]:
    """Return one current verified envelope or raise its named gate error.

    Args:
        project_root: Project root containing schema-v2 presentation state.
        deck_id: Deck whose current evidence pointer authorizes the caller.
        evidence_kind: Registered pointer kind to authorize.

    Returns:
        The exact pointer-selected, CAS-verified schema-v2 envelope.

    Raises:
        ValueError: If ``evidence_kind`` is not a registered pointer kind.
        DraftGateError: If current preview or approval evidence is absent,
            stale, mismatched, or byte-unverifiable.
        CompletionGateError: If current completion evidence is absent, stale,
            mismatched, or byte-unverifiable.
    """
    current = resolve_current_evidence(project_root, deck_id, (evidence_kind,))
    envelope = current.envelopes.get(evidence_kind)
    if envelope is None:
        _fail_current(evidence_kind, deck_id, list(current.blockers))
    return thaw_frozen(envelope)


def assert_draft_approvable(
    project_root: Path,
    deck_id: str,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    """Assert a draft decision is bound to current preview evidence.

    Authorization comes only from the deck's ``draft_preview_evidence_id``
    pointer and the immutable source event that pointer selects. A schema-v1
    preview event that is no longer the current pointer never authorizes an
    approval.

    Args:
        project_root: Project root containing schema-v2 presentation state.
        deck_id: Deck whose current draft preview is being approved.
        decision: Parsed Draft Decision contract mapping.

    Returns:
        A mapping containing the deck, decision, and current preview envelope.

    Raises:
        DraftGateError: If the decision or current preview evidence is absent,
            inconsistent, stale, or byte-unverifiable.
    """
    blockers: list[dict[str, Any]] = []
    if not isinstance(decision, Mapping):
        _fail_current("draft_preview", deck_id, [{"reason": "decision must be a mapping"}])
    if decision.get("deck_id") != deck_id:
        blockers.append({"reason": "deck_id_mismatch"})
    if decision.get("decision") != "approve":
        blockers.append({"reason": "draft_decision_not_approve"})
    current = resolve_current_evidence(project_root, deck_id, ("draft_preview",))
    blockers.extend(current.blockers)
    preview = current.envelopes.get("draft_preview")
    if preview is not None and decision.get("preview_id") != preview["source_event_id"]:
        blockers.append(
            {
                "reason": "draft_decision_preview_binding_mismatch",
                "expected": preview["source_event_id"],
            }
        )
    if blockers or preview is None or current.deck is None:
        _fail_current("draft_preview", deck_id, blockers)
    return {
        "deck": thaw_frozen(current.deck),
        "decision": dict(decision),
        "preview": thaw_frozen(preview),
    }


def final_visual_review_blockers(
    project_root: Path,
    deck_id: str,
    completion: Mapping[str, Any],
    blockers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Validate the persisted visual review and every final artifact it names.

    Every declared artifact digest is compared against a no-follow verified
    read of its bytes, so a completion gate never trusts a caller-declared
    digest or a followed symlink.

    Args:
        project_root: Project root containing the review record and outputs.
        deck_id: Deck whose completion is being authorized.
        completion: Completion contract naming the visual-review record.
        blockers: Accumulating structured blocker list, extended in place.

    Returns:
        The parsed review document, or None when it cannot be read.
    """
    resolved = _review_record_path(project_root, completion, blockers)
    if resolved is None:
        return None
    artifact_root = _artifact_root(project_root, completion, blockers)
    try:
        issues = validate_review_record(resolved, artifact_root)
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        blockers.append({"reason": "invalid_visual_review_record", "message": str(exc)})
        return None
    blockers.extend({"reason": f"visual_review:{issue.path}:{issue.message}"} for issue in issues)
    if not isinstance(document, Mapping):
        blockers.append({"reason": "visual_review_root_not_mapping"})
        return None
    if document.get("deck_id") != deck_id:
        blockers.append({"reason": "visual_review_deck_id_mismatch"})
    if document.get("output_format") != "pptx":
        blockers.append({"reason": "output_format_pptx_required"})
    _verify_persisted_png_records(project_root, deck_id, document, blockers)
    try:
        derived = derive_overall_status(document)
        if derived.status != "passed" or not derived.completion_allowed:
            blockers.append({"reason": "visual_review_not_passing"})
    except ValueError as exc:
        blockers.append({"reason": "visual_review_overall_invalid", "message": str(exc)})
    digest_map = completion.get("artifact_digests", document.get("artifact_digests"))
    if not isinstance(digest_map, Mapping):
        blockers.append({"reason": "final_artifact_digests_required"})
    else:
        for png_path in sorted(_png_paths(document)):
            if png_path not in digest_map:
                blockers.append({"reason": "final_png_digest_required", "path": png_path})
    _verify_final_outputs(project_root, document, digest_map, artifact_root, resolved, blockers)
    _verify_artifact_digests(project_root, digest_map, blockers, "completion_artifact")
    return dict(document)


def _verify_final_outputs(
    project_root: Path,
    document: Mapping[str, Any],
    digest_map: Any,
    artifact_root: Path,
    review_record: Path,
    blockers: list[dict[str, Any]],
) -> None:
    """Require a declared, present, and digest-bound final PPTX artifact."""
    artifacts = document.get("artifacts", {})
    if not isinstance(artifacts, Mapping):
        return
    pptx_path = artifacts.get("pptx")
    if not isinstance(pptx_path, str) or not pptx_path:
        blockers.append({"reason": "final_pptx_artifact_required"})
    else:
        _, failure = _verified_digest(artifact_root, pptx_path)
        if failure == "missing":
            blockers.append({"reason": "missing_final_pptx", "path": pptx_path})
        elif failure is not None:
            blockers.append(
                {"reason": "unreadable_final_pptx", "path": pptx_path, "message": failure}
            )
        elif not isinstance(digest_map, Mapping) or pptx_path not in digest_map:
            blockers.append({"reason": "final_pptx_digest_required", "path": pptx_path})
    declared_review = artifacts.get("review_record")
    if isinstance(declared_review, str) and (artifact_root / declared_review).resolve() != review_record:
        blockers.append({"reason": "visual_review_record_binding_mismatch"})


def _review_record_path(
    project_root: Path, completion: Mapping[str, Any], blockers: list[dict[str, Any]]
) -> Path | None:
    """Resolve the declared review-record path inside the project root."""
    raw_path = completion.get("visual_review_path", completion.get("review_record_path"))
    if not isinstance(raw_path, str) or not raw_path:
        blockers.append({"reason": "visual_review_path_required"})
        return None
    review_path = Path(raw_path)
    if review_path.is_absolute():
        resolved = review_path.resolve()
        try:
            resolved.relative_to(project_root.resolve())
        except ValueError:
            blockers.append({"reason": "visual_review_path_outside_project"})
            return None
    else:
        if ".." in review_path.parts:
            blockers.append({"reason": "visual_review_path_invalid"})
            return None
        resolved = (project_root / review_path).resolve()
    if not resolved.is_file():
        blockers.append({"reason": "missing_visual_review_record", "path": raw_path})
        return None
    return resolved


def _artifact_root(
    project_root: Path, completion: Mapping[str, Any], blockers: list[dict[str, Any]]
) -> Path:
    """Resolve the root that final review artifact paths are relative to."""
    raw_root = completion.get("artifact_root")
    if not isinstance(raw_root, str) or not raw_root:
        return project_root
    candidate = Path(raw_root)
    if candidate.is_absolute():
        return candidate.resolve()
    if ".." in candidate.parts:
        blockers.append({"reason": "artifact_root_invalid"})
        return project_root
    return (project_root / candidate).resolve()


def _verify_artifact_digests(
    project_root: Path, digests: Any, blockers: list[dict[str, Any]], reason_prefix: str
) -> None:
    """Verify caller-declared artifact digests against verified source bytes."""
    if digests is None:
        return
    if not isinstance(digests, Mapping):
        blockers.append({"reason": f"{reason_prefix}_digests_must_be_mapping"})
        return
    for raw_path, digest in digests.items():
        if not isinstance(raw_path, str) or Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
            blockers.append({"reason": f"{reason_prefix}_digest_path_invalid", "path": raw_path})
            continue
        if not _is_sha256(digest):
            blockers.append({"reason": f"{reason_prefix}_digest_invalid", "path": raw_path})
            continue
        actual, failure = _verified_digest(project_root, raw_path)
        if failure == "missing":
            blockers.append({"reason": f"{reason_prefix}_digest_file_missing", "path": raw_path})
        elif failure is not None:
            blockers.append(
                {"reason": f"{reason_prefix}_digest_file_unreadable", "path": raw_path, "message": failure}
            )
        elif actual != digest:
            blockers.append({"reason": f"{reason_prefix}_digest_mismatch", "path": raw_path, "actual": actual})


def _verify_persisted_png_records(
    project_root: Path, deck_id: str, document: Mapping[str, Any], blockers: list[dict[str, Any]]
) -> None:
    """Require one persisted, byte-matching artifact record per named PNG."""
    try:
        records = load_artifacts(project_root)
    except Exception as exc:  # noqa: BLE001 - malformed stores are gate blockers
        blockers.append({"reason": "persisted_artifact_store_invalid", "message": str(exc)})
        return
    for raw_path in sorted(_png_paths(document)):
        path = Path(raw_path)
        if path.is_absolute() or ".." in path.parts:
            blockers.append({"reason": "inspected_png_path_invalid", "path": raw_path})
            continue
        matches = [
            record for record in records.values()
            if record.get("deck_id") == deck_id
            and record.get("path", record.get("relative_path")) == raw_path
        ]
        if not matches:
            blockers.append({"reason": "missing_persisted_artifact", "path": raw_path})
            continue
        if len(matches) != 1:
            blockers.append({"reason": "ambiguous_persisted_artifact", "path": raw_path})
            continue
        digest = matches[0].get("sha256")
        actual, failure = _verified_digest(project_root, raw_path)
        if failure == "missing":
            blockers.append({"reason": "missing_persisted_artifact_file", "path": raw_path})
        elif failure is not None:
            blockers.append({"reason": "unreadable_persisted_artifact", "path": raw_path, "message": failure})
        elif not _is_sha256(digest):
            blockers.append({"reason": "invalid_persisted_artifact_digest", "path": raw_path})
        elif actual != digest:
            blockers.append({"reason": "persisted_artifact_digest_mismatch", "path": raw_path})


def _png_paths(value: Any) -> set[str]:
    """Collect every PNG path named by a visual-review document."""
    if isinstance(value, str):
        return {value} if value.lower().endswith(".png") else set()
    if isinstance(value, Mapping):
        paths: set[str] = set()
        for child in value.values():
            paths.update(_png_paths(child))
        return paths
    if isinstance(value, list):
        paths = set()
        for child in value:
            paths.update(_png_paths(child))
        return paths
    return set()


def _verified_digest(project_root: Path, relative_path: str) -> tuple[str | None, str | None]:
    """Return one no-follow verified digest, or a stable failure category.

    Args:
        project_root: Root the artifact path is interpreted against.
        relative_path: Canonical project-relative artifact path.

    Returns:
        The verified digest with a None failure, or None with either
        ``"missing"`` or the exact unreadable-source diagnostic.
    """
    try:
        return read_verified_source(project_root, relative_path).digest, None
    except CasError as exc:
        message = str(exc)
        if message.startswith("missing source artifact:"):
            return None, "missing"
        return None, message


def _selected_envelope(
    snapshot: EvidenceSnapshot,
    deck: Mapping[str, Any],
    deck_id: str,
    evidence_kind: str,
    available: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, list[dict[str, Any]]]:
    """Resolve and byte-verify one pointer-selected envelope for a deck.

    The caller has already established that the deck stores a nonempty pointer
    for ``evidence_kind``.
    """
    field = EVIDENCE_POINTER_FIELDS[evidence_kind]
    evidence_id = deck.get(field)
    envelope = available.get(evidence_id)
    if (
        envelope is None
        or envelope.get("evidence_kind") != evidence_kind
        or envelope.get("deck_id") != deck_id
        or envelope.get("availability") != "available"
    ):
        return None, [{"reason": _POINTER_INVALID_REASONS[evidence_kind], field: evidence_id}]
    cas_blockers = _cas_blockers(snapshot, envelope)
    if cas_blockers:
        return None, cas_blockers
    return envelope, []


def _cas_blockers(
    snapshot: EvidenceSnapshot, envelope: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Verify every referenced CAS object from the frozen snapshot capture.

    ``evidence_cas_object_missing`` is the live path: a deleted CAS object is
    skipped by ``_capture_persisted_cas_objects`` and simply never appears in
    ``snapshot.artifact_objects``.

    ``evidence_cas_digest_mismatch`` is deliberate defense in depth and is
    unreachable through the normal pipeline. Objects keyed by ``cas_path`` can
    only come from ``_capture_persisted_cas_objects``, which already proves
    ``object_.digest == reference["sha256"]`` and raises
    ``EvidenceCasIntegrityError`` otherwise, and ``read_verified_source``
    always derives ``digest`` from the bytes it just read. The branch therefore
    only fires for an object that reached this function without that
    verification -- a hand-constructed ``CasObject``, or a future caller
    sourcing objects from somewhere other than the snapshot capture. It is
    covered directly by unit tests rather than through the producer pipeline.

    Args:
        snapshot: Frozen capture whose ``artifact_objects`` hold verified bytes.
        envelope: Pointer-selected envelope whose references are checked.

    Returns:
        Structured blockers for every unverifiable reference, in declared order.
    """
    blockers: list[dict[str, Any]] = []
    for reference in envelope.get("artifact_refs", ()):
        digest = reference.get("sha256")
        cas_path = reference.get("cas_path")
        object_ = snapshot.artifact_objects.get(cas_path)
        if object_ is None:
            blockers.append(
                {"reason": "evidence_cas_object_missing", "cas_path": cas_path, "sha256": digest}
            )
        elif (
            object_.digest != digest
            or hashlib.sha256(object_.content).hexdigest() != digest
        ):
            blockers.append(
                {"reason": "evidence_cas_digest_mismatch", "cas_path": cas_path, "sha256": digest}
            )
    return blockers


def _revision_invalidation(
    active: ActiveEvidenceProjection, deck_id: str
) -> dict[str, Any] | None:
    """Return a blocker when a current revision cleared this deck's pointers."""
    updates = active.pointer_updates.get(deck_id, {})
    cleared = sorted(
        field
        for field in EVIDENCE_POINTER_FIELDS.values()
        if field in updates and updates[field] is None
    )
    if not cleared:
        return None
    return {"reason": "active_evidence_invalidated_by_revision", "pointers": cleared}


def _unresolved(reason: str, exc: Exception) -> CurrentEvidence:
    """Return one fail-closed result for an unreadable evidence source."""
    return CurrentEvidence(
        None, MappingProxyType({}), ({"reason": reason, "message": str(exc)},)
    )


def _is_text(value: object) -> bool:
    """Return whether a value is a nonempty string pointer identifier."""
    return isinstance(value, str) and bool(value)


def _is_sha256(value: object) -> bool:
    """Return whether a value is exactly one lowercase SHA-256 digest."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _SHA256_HEX for character in value)
    )


def _fail_current(
    evidence_kind: str, deck_id: str, blockers: list[dict[str, Any]]
) -> NoReturn:
    """Raise the gate error registered for one current evidence kind.

    Args:
        evidence_kind: Registered pointer kind whose gate failed.
        deck_id: Deck reported by the structured CLI error.
        blockers: Structured blockers explaining the failure.

    Raises:
        GateError: The typed subclass registered for ``evidence_kind``.
    """
    import presentation_gates

    error_type = getattr(presentation_gates, _GATE_ERROR_NAMES[evidence_kind])
    presentation_gates.fail_gate(
        error_type,
        _PREDICATES[evidence_kind],
        deck_id,
        blockers or [{"reason": _POINTER_REQUIRED_REASONS[evidence_kind]}],
    )
