"""Schema-v2 guards and immutable transaction-staging primitives.

High-level preview, approval, and completion source construction belongs in
``presentation_evidence_producers``.  This module owns the narrow shared
boundary that validates candidate evidence and stages one atomic transition.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

import yaml

from presentation_evidence_cas import CasObject, plan_cas_objects, stage_cas_objects
from presentation_evidence_contracts import (
    EVIDENCE_SCHEMA_VERSION,
    EvidenceContractError,
    validate_deck_evidence_pointers,
    validate_envelope,
)
from presentation_evidence_projection import ProjectionError
from presentation_evidence_snapshot import EvidenceSnapshot, freeze, thaw
from presentation_evidence_store import evidence_store_path, serialize_evidence_store
from presentation_no_follow import (
    MissingPathError,
    NoFollowPathError,
    open_parent_no_follow,
    read_stable_regular,
)
from presentation_transactions import (
    TransactionError,
    WorkflowTransaction,
    incomplete_transaction_journals,
    require_transaction_recovery,
)


_STATE_FILES: Final[tuple[str, ...]] = (
    "decks.yaml",
    "plans.yaml",
    "slides.yaml",
    "visual_modules.yaml",
    "assignments.yaml",
    "artifacts.yaml",
    "revision_requests.yaml",
    "evidence.yaml",
)
_STATE_PREFIX: Final[str] = ".research/presentations/state/"


class MigrationRequiredError(RuntimeError):
    """Raised when a workflow writer is invoked before schema-v2 migration.

    Attributes:
        source_schema_version: Observed legacy state version requiring a
            migration.
        target_schema_version: Required schema version for workflow writes.
    """

    def __init__(self, source_schema_version: int | str) -> None:
        """Initialize a typed legacy-workflow boundary error.

        Args:
            source_schema_version: Exact legacy marker or an unsupported
                marker category that requires migration.
        """
        self.source_schema_version = source_schema_version
        self.target_schema_version = EVIDENCE_SCHEMA_VERSION
        super().__init__(
            "presentation workflow requires migration from schema "
            f"{source_schema_version} to {EVIDENCE_SCHEMA_VERSION}"
        )


def require_schema_v2(project_root: Path, *, check_recovery: bool = True) -> None:
    """Reject schema-zero/one workflow writes before any operational mutation.

    Args:
        project_root: Existing project root that may contain state documents.
        check_recovery: Whether a low-level writer must reject an incomplete
            transaction before probing the schema.

    Raises:
        MigrationRequiredError: If any existing state header is not one exact
            supported schema-two marker.
    """
    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")
    if type(check_recovery) is not bool:
        raise TypeError("check_recovery must be a bool")
    if check_recovery:
        require_transaction_recovery(project_root, allow_publication_temporary=True)
    elif incomplete_transaction_journals(project_root):
        return
    versions: set[int] = set()
    try:
        for name in _STATE_FILES:
            relative_path = f"{_STATE_PREFIX}{name}"
            try:
                anchored = open_parent_no_follow(
                    project_root, relative_path, create_parents=False
                )
            except MissingPathError:
                continue
            try:
                if anchored.stat_leaf() is None:
                    continue
                content, _ = read_stable_regular(anchored)
            finally:
                anchored.close()
            version = _state_version(content, relative_path)
            if version is not None:
                versions.add(version)
    except NoFollowPathError as exc:
        raise TransactionError(f"schema-v2 guard requires no-follow access: {exc}") from exc
    if not versions:
        return
    if len(versions) != 1:
        raise MigrationRequiredError("mixed")
    version = next(iter(versions))
    if version != EVIDENCE_SCHEMA_VERSION:
        raise MigrationRequiredError(version)


def _state_version(content: bytes, relative_path: str) -> int:
    """Parse one exact integer state marker from immutable YAML bytes.

    Args:
        content: Exact no-follow bytes from a known state document.
        relative_path: Canonical path used only for stable diagnostics.

    Returns:
        One exact integer schema marker from the state mapping.

    Raises:
        MigrationRequiredError: If the header is empty, malformed, nonmapping,
            recursive, mixed, boolean, or otherwise not an exact integer.
    """
    try:
        document = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise MigrationRequiredError("invalid") from exc
    if not isinstance(document, dict):
        raise MigrationRequiredError("invalid")
    has_version = "version" in document
    has_schema_version = "schema_version" in document
    if has_version and has_schema_version:
        raise MigrationRequiredError("mixed")
    if not has_version and not has_schema_version:
        raise MigrationRequiredError("invalid")
    marker = document.get("version", document.get("schema_version"))
    if type(marker) is bool:
        raise MigrationRequiredError("bool")
    if type(marker) is not int:
        raise MigrationRequiredError("invalid")
    return marker


def stage_evidence_transition(
    transaction: WorkflowTransaction,
    snapshot: EvidenceSnapshot,
    *,
    event: Mapping[str, Any],
    envelope: Mapping[str, Any],
    cas_objects: Mapping[str, CasObject],
    pointer_field: str,
) -> None:
    """Stage one event, envelope, CAS set, and current deck pointer together.

    Args:
        transaction: Active transaction with every required target selected
            before its locks were acquired.
        snapshot: Immutable v2 state captured after those locks were held.
        event: Exact immutable source event for the new envelope.
        envelope: Exact schema-v2 envelope bound to ``event``.
        cas_objects: Digest-keyed immutable source bytes to materialize.
        pointer_field: Current deck pointer field owned by ``envelope``.
    """
    _stage_evidence_batch(
        transaction,
        snapshot,
        events=(event,),
        envelopes=(envelope,),
        cas_objects=cas_objects,
        pointer_field=pointer_field,
    )


def _stage_evidence_batch(
    transaction_handle: WorkflowTransaction,
    snapshot: EvidenceSnapshot,
    *,
    events: Sequence[Mapping[str, Any]],
    envelopes: Sequence[Mapping[str, Any]],
    cas_objects: Mapping[str, CasObject],
    pointer_field: str,
) -> None:
    """Stage a producer-compatible transition with optional support events."""
    if not isinstance(transaction_handle, WorkflowTransaction):
        raise TypeError("transaction_handle must be a WorkflowTransaction")
    if not isinstance(snapshot, EvidenceSnapshot):
        raise TypeError("snapshot must be an EvidenceSnapshot")
    if transaction_handle.project_root != snapshot.project_root:
        raise ValueError("transaction project root does not match snapshot project root")
    expected_kinds = {
        "draft_preview_evidence_id": "draft_preview",
        "draft_approval_evidence_id": "draft_approval",
        "completion_evidence_id": "deck_completion",
    }
    expected_kind = expected_kinds.get(pointer_field)
    if expected_kind is None:
        raise ValueError(f"unsupported evidence pointer field {pointer_field!r}")
    if not events or not envelopes:
        raise ValueError("evidence transition requires events and envelopes")
    event_records = [_event_record(event) for event in events]
    envelope_records = [validate_envelope(envelope) for envelope in envelopes]
    event_ids = [record["id"] for record in event_records]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("evidence transition event ids must be unique")
    for envelope in envelope_records:
        if envelope["source_event_id"] not in event_ids:
            raise EvidenceContractError("envelope source_event_id must be staged in the transition")
    pointer_envelope = envelope_records[-1]
    if pointer_envelope["evidence_kind"] != expected_kind:
        raise EvidenceContractError(f"{pointer_field} must select {expected_kind} evidence")
    root = snapshot.project_root
    event_path = _event_shard_path(root)
    existing_evidence = {
        evidence_id: _mutable(record)
        for evidence_id, record in snapshot.stores.get("evidence", {}).items()
    }
    for envelope in envelope_records:
        existing = existing_evidence.get(envelope["id"])
        if existing is not None and existing != envelope:
            raise EvidenceContractError("evidence id is already bound to different immutable content")
        existing_evidence[envelope["id"]] = envelope
    decks = {
        deck_id: _mutable(record)
        for deck_id, record in snapshot.stores.get("decks", {}).items()
    }
    deck = decks.get(pointer_envelope["deck_id"])
    if deck is None:
        raise EvidenceContractError("evidence deck_id does not resolve")
    deck[pointer_field] = pointer_envelope["id"]
    validate_deck_evidence_pointers(deck, existing_evidence)
    event_payload = b"".join(
        json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
        for record in event_records
    )
    transaction_handle.stage_bytes(
        event_path, transaction_handle.read_bytes(event_path) + event_payload
    )
    transaction_handle.stage_bytes(
        evidence_store_path(root), serialize_evidence_store(existing_evidence)
    )
    transaction_handle.stage_yaml(root / _STATE_PREFIX / "decks.yaml", "decks", decks)
    stage_cas_objects(transaction_handle, root, cas_objects)


def _event_record(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return one JSON-serializable immutable event with an exact id."""
    if not isinstance(event, Mapping):
        raise TypeError("event must be a mapping")
    record = dict(event)
    identifier = record.get("id")
    if not isinstance(identifier, str) or not identifier or identifier != identifier.strip():
        raise ValueError("event id must be a nonempty trimmed string")
    try:
        json.dumps(record, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("event must be JSON serializable") from exc
    return record


def _transition_paths(
    project_root: Path, cas_objects: Mapping[str, CasObject]
) -> list[Path]:
    """Select every frozen state, event, and CAS target before locking."""
    state_root = project_root / _STATE_PREFIX
    paths = [state_root / name for name in _STATE_FILES]
    events_root = project_root / ".research/presentations/events"
    if events_root.exists():
        paths.extend(path for path in events_root.iterdir() if path.name.endswith(".jsonl"))
    paths.append(_event_shard_path(project_root))
    paths.extend(project_root / object_.relative_path for object_ in cas_objects.values())
    return sorted(set(paths), key=lambda path: path.as_posix())


def _planned_source_objects(
    project_root: Path, artifact_digests: Mapping[str, Any]
) -> dict[str, CasObject]:
    """Capture all declared source artifacts before immutable state capture."""
    if not isinstance(artifact_digests, Mapping):
        raise ValueError("artifact_digests must be a mapping")
    source_paths: dict[str, Path] = {}
    for raw_path in artifact_digests:
        if not isinstance(raw_path, str):
            raise ValueError("artifact_digests keys must be strings")
        source_paths[raw_path] = project_root / raw_path
    planned = plan_cas_objects(project_root, source_paths)
    for raw_path, declared_digest in artifact_digests.items():
        object_ = planned.get(declared_digest)
        if object_ is None:
            raise ProjectionError(f"declared artifact digest does not match source {raw_path!r}")
    return planned


def _objects_by_provenance(
    artifact_digests: Mapping[str, Any], cas_objects: Mapping[str, CasObject]
) -> dict[str, CasObject]:
    """Bind each immutable source object to its declared provenance path."""
    result: dict[str, CasObject] = {}
    for raw_path, digest in artifact_digests.items():
        if not isinstance(raw_path, str) or not isinstance(digest, str):
            raise ValueError("artifact declarations must use string paths and digests")
        object_ = cas_objects.get(digest)
        if object_ is None:
            raise ProjectionError(f"declared artifact digest does not resolve for {raw_path!r}")
        result[raw_path] = object_
    return result


def _candidate_snapshot(
    snapshot: EvidenceSnapshot,
    *,
    events: Sequence[Mapping[str, Any]] = (),
    source_objects: Mapping[str, CasObject] = MappingProxyType({}),
    file_preimages: Mapping[Path, bytes] = MappingProxyType({}),
    evidence_updates: Mapping[str, Mapping[str, Any]] = MappingProxyType({}),
    deck_updates: Mapping[str, Mapping[str, Any]] = MappingProxyType({}),
) -> EvidenceSnapshot:
    """Overlay planned immutable producer values on a frozen state snapshot."""
    stores: dict[str, dict[str, Mapping[str, Any]]] = {
        store_name: {record_id: _mutable(record) for record_id, record in records.items()}
        for store_name, records in snapshot.stores.items()
    }
    evidence = stores.setdefault("evidence", {})
    for evidence_id, envelope in evidence_updates.items():
        evidence[evidence_id] = _mutable(envelope)
    decks = stores.get("decks")
    if decks is None:
        raise ValueError("candidate snapshot requires a deck store")
    for deck_id, updates in deck_updates.items():
        record = decks.get(deck_id)
        if record is None:
            raise ValueError(f"candidate deck does not resolve: {deck_id}")
        amended = _mutable(record)
        amended.update(_mutable(updates))
        decks[deck_id] = amended
    # Freeze deeply through the shared helper: a candidate snapshot must be
    # indistinguishable in container types from one built by build_snapshot,
    # otherwise validation that passes here can still fail on real state.
    frozen_stores = freeze(stores)
    frozen_events = tuple(snapshot.events) + tuple(
        freeze(_event_record(event)) for event in events
    )
    objects = dict(snapshot.artifact_objects)
    objects.update(source_objects)
    preimages = dict(snapshot.file_preimages)
    preimages.update(file_preimages)
    return replace(
        snapshot,
        stores=frozen_stores,
        events=frozen_events,
        artifact_objects=MappingProxyType(objects),
        file_preimages=MappingProxyType(preimages),
    )


def _event_shard_path(project_root: Path) -> Path:
    """Return the current shard without importing presentation-events eagerly."""
    from presentation_events import events_shard_path

    return events_shard_path(project_root)


def _load_deck_after_commit(project_root: Path, deck_id: str) -> dict[str, Any]:
    """Load one committed deck result through the established public store API."""
    from presentation_state import load_decks

    deck = load_decks(project_root).get(deck_id)
    if not isinstance(deck, dict):
        raise ValueError(f"committed deck does not resolve: {deck_id}")
    return deck


def _mutable(value: Any) -> Any:
    """Return a recursively mutable copy of one frozen snapshot value.

    Args:
        value: Any frozen or mutable snapshot value.

    Returns:
        A deeply mutable copy produced by the shared snapshot thaw helper.
    """
    return thaw(value)
