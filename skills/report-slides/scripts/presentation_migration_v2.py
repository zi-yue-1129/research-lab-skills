"""Pure schema-v2 presentation-evidence migration planning and locking."""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping

import yaml

from migration_scope import MigrationError, validate_record_paths
from presentation_evidence_cas import CasObject, cas_relative_path
from presentation_evidence_contracts import (
    EvidenceContractError,
    envelope_sha256,
    validate_envelope,
    validate_store_record,
)
from presentation_evidence_projection import (
    HistoricalEvidenceUnavailableError,
    HistoricalProjection,
    project_historical_evidence,
    project_visual_review_evidence,
)
from presentation_evidence_snapshot import EvidenceSnapshot, freeze, thaw as _thaw
from presentation_evidence_store import evidence_store_path, serialize_evidence_store
from presentation_no_follow import NoFollowPathError, open_parent_no_follow
from validate_deck_plan import validate_deck_approval


_STATE_PATH_TO_STORE = {
    "decks.yaml": "decks",
    "plans.yaml": "plans",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
    "assignments.yaml": "assignments",
    "artifacts.yaml": "artifacts",
    "revision_requests.yaml": "revision_requests",
    "evidence.yaml": "evidence",
}
_APPROVED_STATUSES = frozenset(
    {"approved", "producing", "draft_review", "revising", "validating", "completed"}
)


@dataclass(frozen=True)
class MigrationPlan:
    """All deterministic schema-v2 replacements and report fields.

    Attributes:
        source_schema_version: Uniform source version captured in the snapshot.
        replacements: Absolute state-path replacements, sorted by caller.
        cas_objects: Absolute canonical CAS paths and their exact bytes.
        migrated_ids: Stable IDs converted without a current-evidence blocker.
        blocked_ids: Stable deck IDs whose current lifecycle cannot be trusted.
        blockers: Deterministic structured current-evidence failures by deck.
    """

    source_schema_version: int
    replacements: Mapping[Path, bytes]
    cas_objects: Mapping[Path, bytes]
    migrated_ids: tuple[str, ...]
    blocked_ids: tuple[str, ...]
    blockers: Mapping[str, tuple[Mapping[str, Any], ...]]


def build_migration_plan(snapshot: EvidenceSnapshot) -> MigrationPlan:
    """Build a schema-v2 conversion plan without filesystem mutation.

    Args:
        snapshot: Immutable state, history, and artifact capture.

    Returns:
        Deterministic replacement bytes, CAS bytes, and current blockers.

    Raises:
        MigrationError: If source state cannot be converted without inventing
            evidence or if a target schema-two store is malformed.
    """
    if not isinstance(snapshot, EvidenceSnapshot):
        raise TypeError("snapshot must be an EvidenceSnapshot")
    source_version = snapshot.schema_version
    if type(source_version) is not int or source_version not in {0, 1, 2}:
        raise MigrationError(f"unsupported source schema version: {source_version!r}")
    if source_version == 2:
        _validate_target_store(snapshot)
        history = project_historical_evidence(snapshot)
        active = _active_projection(snapshot, history)
        blockers = {
            deck_id: tuple(dict(item) for item in items)
            for deck_id, items in active.blockers.items()
        }
        return MigrationPlan(
            source_schema_version=2,
            replacements=MappingProxyType({}),
            cas_objects=MappingProxyType({}),
            migrated_ids=(),
            blocked_ids=tuple(sorted(blockers)),
            blockers=MappingProxyType(dict(sorted(blockers.items()))),
        )

    stores = _mutable_stores(snapshot)
    _validate_snapshot_scope(snapshot, stores)
    _validate_migrated_records(stores)
    preliminary = _snapshot_with_stores(snapshot, stores)
    history_without_completion = _available_historical_projection(
        replace(
            preliminary,
            events=tuple(
                event for event in preliminary.events if event.get("event") != "deck_completion"
            ),
        )
    )
    evidence = _supporting_envelopes(preliminary, history_without_completion.envelopes)
    full_snapshot = _snapshot_with_stores(preliminary, {**stores, "evidence": evidence})
    history = _available_historical_projection(full_snapshot)
    evidence.update(history.envelopes)
    decks = _apply_preview_pointers(stores.get("decks", {}), history.by_source_event_id)
    full_snapshot = _snapshot_with_stores(
        full_snapshot,
        {**stores, "decks": decks, "evidence": evidence},
    )
    active = _active_projection(full_snapshot, history)
    blockers = _legacy_blockers(full_snapshot, active.blockers)
    decks = _apply_pointer_updates(decks, active.pointer_updates)
    for deck_id in blockers:
        deck = decks.get(deck_id)
        if deck is not None:
            deck["status"] = "blocked"
    stores["decks"] = decks
    stores["evidence"] = evidence

    replacements = _state_replacements(snapshot, stores)
    cas_objects = {
        snapshot.project_root / cas_relative_path(digest): object_.content
        for digest, object_ in sorted(history.cas_objects.items())
    }
    all_ids = {
        record_id
        for store_name, records in stores.items()
        if store_name != "evidence"
        for record_id in records
    }
    blocked_ids = tuple(sorted(blockers))
    return MigrationPlan(
        source_schema_version=source_version,
        replacements=MappingProxyType(dict(sorted(replacements.items(), key=lambda item: item[0].as_posix()))),
        cas_objects=MappingProxyType(dict(sorted(cas_objects.items(), key=lambda item: item[0].as_posix()))),
        migrated_ids=tuple(sorted(all_ids - set(blocked_ids))),
        blocked_ids=blocked_ids,
        blockers=MappingProxyType(
            {
                deck_id: tuple(MappingProxyType(dict(item)) for item in blockers[deck_id])
                for deck_id in sorted(blockers)
            }
        ),
    )


@contextmanager
def migration_workflow_lock(project_root: Path) -> Iterator[None]:
    """Hold the stable no-follow workflow lock for a wet migration.

    Args:
        project_root: Existing project root whose state is being migrated.

    Yields:
        ``None`` while the stable regular lock is held.

    Raises:
        MigrationError: If the lock is unsafe or cannot be acquired before the
            configured timeout.
    """
    try:
        anchor = open_parent_no_follow(
            project_root,
            ".research/presentations/state/workflow.lock",
            create_parents=True,
        )
    except NoFollowPathError as exc:
        raise MigrationError("unsafe workflow lock path") from exc
    descriptor: int | None = None
    try:
        metadata = anchor.stat_leaf()
        if metadata is not None and not stat.S_ISREG(metadata.st_mode):
            raise MigrationError(f"workflow lock must be a regular file: {anchor.display_path}")
        try:
            descriptor = anchor.open_leaf(os.O_RDWR | os.O_CREAT, 0o666)
        except OSError as exc:
            raise MigrationError(f"unable to open workflow lock: {anchor.display_path}: {exc}") from exc
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise MigrationError(f"workflow lock must be a regular file: {anchor.display_path}")
        timeout = int(os.environ.get("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS", "30"))
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                if time.monotonic() >= deadline:
                    raise MigrationError(
                        f"could not acquire workflow lock within {timeout}s: {anchor.display_path}"
                    ) from exc
                time.sleep(0.05)
        yield
    finally:
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        anchor.close()


def cas_objects_for_plan(plan: MigrationPlan) -> Mapping[str, CasObject]:
    """Convert planned path bytes into validated CAS objects for staging.

    Args:
        plan: Immutable migration conversion plan.

    Returns:
        Digest-keyed immutable CAS objects with exact read-only modes.

    Raises:
        MigrationError: If a plan contains a noncanonical CAS target.
    """
    objects: dict[str, CasObject] = {}
    for path, content in plan.cas_objects.items():
        digest = path.name
        relative = cas_relative_path(digest)
        if tuple(path.parts[-6:]) != (
            ".research",
            "presentations",
            "evidence",
            "sha256",
            digest[:2],
            digest,
        ):
            raise MigrationError(f"migration CAS path is not canonical: {path}")
        objects[digest] = CasObject(digest, relative, content, 0o444)
    return MappingProxyType(objects)


def _validate_target_store(snapshot: EvidenceSnapshot) -> None:
    """Validate that a schema-two snapshot has the authoritative store."""
    evidence = snapshot.stores.get("evidence")
    if evidence is None:
        raise MigrationError("schema-two state requires evidence.yaml")
    try:
        # Snapshot stores are frozen, so every list is a tuple. The evidence
        # contract requires exact list types, so the store must be thawed
        # before validation; _mutable_stores deliberately excludes evidence.
        serialize_evidence_store(
            {evidence_id: _thaw(record) for evidence_id, record in evidence.items()}
        )
        mutable_stores = _mutable_stores(snapshot)
        for store_name, records in mutable_stores.items():
            for record in records.values():
                validate_store_record(
                    store_name, record, relations=mutable_stores
                )
    except EvidenceContractError as exc:
        raise MigrationError(f"schema-two state is invalid: {exc}") from exc


def _mutable_stores(snapshot: EvidenceSnapshot) -> dict[str, dict[str, dict[str, Any]]]:
    """Copy frozen snapshot stores into mutable conversion records."""
    return {
        store_name: {record_id: _thaw(record) for record_id, record in records.items()}
        for store_name, records in snapshot.stores.items()
        if store_name != "evidence"
    }




def _validate_snapshot_scope(
    snapshot: EvidenceSnapshot, stores: Mapping[str, Mapping[str, Mapping[str, Any]]]
) -> None:
    """Apply the established no-follow path contracts before conversion."""
    current_slides = stores.get("slides", {})
    for store_name, records in stores.items():
        for record in records.values():
            validate_record_paths(
                snapshot.project_root,
                record,
                store_name=store_name,
                current_slides=current_slides,
            )
    for event in snapshot.events:
        if event.get("event") in {"draft_preview", "deck_completion", "visual_review"}:
            continue
        validate_record_paths(
            snapshot.project_root,
            _thaw(event),
            store_name="events",
            current_slides=current_slides,
        )


def _validate_migrated_records(
    stores: Mapping[str, Mapping[str, Mapping[str, Any]]]
) -> None:
    """Validate every mutable migration record through the shared contracts."""
    for store_name, records in stores.items():
        for record in records.values():
            try:
                validate_store_record(
                    store_name, record, relations=stores, legacy=True
                )
            except EvidenceContractError as exc:
                raise MigrationError(
                    f"invalid {store_name} migration record: {exc}"
                ) from exc


def _available_historical_projection(snapshot: EvidenceSnapshot) -> HistoricalProjection:
    """Project only legacy history whose immutable identity is provable.

    Every source event remains in its original JSONL shard.  This migration
    helper merely avoids creating a schema-two envelope when an old artifact
    event lacks a uniquely captured historical plan or evidence chain.  The
    shared Task 1 projector remains the only projection validator.

    Args:
        snapshot: Immutable migration snapshot containing source audit events.

    Returns:
        The shared historical projection over only provably projectable events.
    """
    selected_events: list[Mapping[str, Any]] = []
    for event in snapshot.events:
        event_kind = event.get("event")
        if event_kind not in {"draft_preview", "deck_completion"}:
            selected_events.append(event)
            continue
        if (
            event_kind == "deck_completion"
            and "schema_version" not in event
            and "completion_sha256" not in event
        ):
            continue
        candidate = replace(snapshot, events=tuple([*selected_events, event]))
        try:
            project_historical_evidence(candidate)
        except HistoricalEvidenceUnavailableError:
            continue
        selected_events.append(event)
    return project_historical_evidence(replace(snapshot, events=tuple(selected_events)))


def _snapshot_with_stores(
    snapshot: EvidenceSnapshot, stores: Mapping[str, Mapping[str, Mapping[str, Any]]]
) -> EvidenceSnapshot:
    """Return a frozen snapshot view with supplied immutable store records.

    Freezing goes through the shared deep helper so a derived snapshot has
    exactly the container types ``build_snapshot`` produces; a shallow wrap
    here would leave nested lists as ``list`` and let code validate cleanly
    against a derived snapshot yet fail against a real one.
    """
    return replace(snapshot, stores=freeze(stores))


def _supporting_envelopes(
    snapshot: EvidenceSnapshot,
    previews: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Convert only explicitly linked approval and review source events."""
    result: dict[str, dict[str, Any]] = {}
    previews_by_source = {
        envelope["source_event_id"]: envelope for envelope in previews.values()
    }
    for event in snapshot.events:
        if event.get("event") == "deck_approval":
            envelope = _approval_envelope(event, previews_by_source)
        elif event.get("event") == "visual_review":
            try:
                envelope = dict(project_visual_review_evidence(snapshot, event))
            except HistoricalEvidenceUnavailableError:
                envelope = None
        else:
            envelope = None
        if envelope is not None:
            result[envelope["id"]] = envelope
    return result


def _approval_envelope(
    event: Mapping[str, Any], previews: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    """Convert one exact legacy approval only when its preview link is explicit."""
    if validate_deck_approval(dict(event)) or event.get("decision") != "approve":
        return None
    preview_id = event.get("preview_id")
    preview = previews.get(preview_id)
    required = ("id", "deck_id", "plan_id", "plan_version", "plan_sha256", "approved_by", "approval_mode", "ts")
    if preview is None or any(not isinstance(event.get(field), str) or not event[field] for field in required if field not in {"plan_version"}):
        return None
    if type(event.get("plan_version")) is not int or event["plan_version"] <= 0:
        return None
    if any(event[field] != preview[field] for field in ("deck_id", "plan_id", "plan_version", "plan_sha256")):
        return None
    envelope = _base_envelope(event, "draft_approval", [])
    envelope.update(
        {
            "preview_evidence_id": preview["id"],
            "preview_evidence_sha256": preview["evidence_sha256"],
            "decision": "approved",
            "approval_mode": event["approval_mode"],
            "approved_by": event["approved_by"],
        }
    )
    return _validated_envelope(envelope)


def _visual_review_envelope(
    snapshot: EvidenceSnapshot, event: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Convert one exact visual-review source without inventing availability."""
    required = ("id", "deck_id", "plan_id", "producer_id", "visual_review_path", "visual_review_sha256", "ts")
    if any(not isinstance(event.get(field), str) or not event[field] for field in required):
        return None
    if type(event.get("schema_version")) is not int or event["schema_version"] != 1:
        return None
    if type(event.get("plan_version")) is not int or event["plan_version"] <= 0:
        return None
    availability = "available" if snapshot.project_root / event["visual_review_path"] in snapshot.file_preimages else "historical_unavailable"
    envelope = _base_envelope(event, "visual_review", [], availability=availability)
    return _validated_envelope(envelope)


def _base_envelope(
    event: Mapping[str, Any],
    evidence_kind: str,
    artifact_refs: list[Mapping[str, Any]],
    *,
    availability: str = "available",
) -> dict[str, Any]:
    """Build the shared immutable envelope fields from an exact source event."""
    envelope = {
        "id": event["id"],
        "schema_version": 2,
        "evidence_kind": evidence_kind,
        "deck_id": event["deck_id"],
        "plan_id": event["plan_id"],
        "plan_version": event["plan_version"],
        "plan_sha256": event["plan_sha256"],
        "subject_ids": [event["deck_id"]],
        "producer_id": event.get("producer_id", event.get("approved_by")),
        "artifact_refs": artifact_refs,
        "source_event_id": event["id"],
        "created_at": event["ts"],
        "availability": availability,
    }
    envelope["evidence_sha256"] = envelope_sha256(envelope)
    return envelope


def _validated_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Validate one derived immutable envelope or raise a migration error."""
    try:
        return validate_envelope(envelope)
    except EvidenceContractError as exc:
        raise MigrationError(f"derived schema-two evidence is invalid: {exc}") from exc


def _apply_preview_pointers(
    decks: Mapping[str, Mapping[str, Any]],
    by_source: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Map only explicit legacy preview IDs to exact projected envelopes."""
    result = {deck_id: dict(deck) for deck_id, deck in decks.items()}
    for deck_id, deck in result.items():
        legacy_preview_id = deck.get("draft_preview_id")
        envelope = by_source.get(legacy_preview_id)
        if envelope is not None and envelope.get("deck_id") == deck_id:
            deck["draft_preview_evidence_id"] = envelope["id"]
    return result


def _active_projection(snapshot: EvidenceSnapshot, history: Any) -> Any:
    """Call the Task 4 active projection without importing it at module load."""
    from presentation_active_evidence import project_active_evidence

    return project_active_evidence(snapshot, history)


def _legacy_blockers(
    snapshot: EvidenceSnapshot, active_blockers: Mapping[str, tuple[Mapping[str, Any], ...]]
) -> dict[str, list[Mapping[str, Any]]]:
    """Retain fail-closed lifecycle blocking for legacy approval states."""
    blockers = {deck_id: [dict(item) for item in values] for deck_id, values in active_blockers.items()}
    from migrate_presentation_state import _safe_plan_evidence

    plans = snapshot.stores.get("plans", {})
    events = [_thaw(event) for event in snapshot.events]
    for deck_id, deck in snapshot.stores.get("decks", {}).items():
        if deck.get("status") not in _APPROVED_STATUSES:
            continue
        reasons = _safe_plan_evidence(
            snapshot.project_root,
            _thaw(deck),
            _thaw(plans),
            events,
        )
        if reasons:
            blockers.setdefault(deck_id, []).extend({"reason": reason} for reason in reasons)
    return {
        deck_id: sorted(items, key=lambda item: str(item.get("reason", "")))
        for deck_id, items in sorted(blockers.items())
    }


def _apply_pointer_updates(
    decks: Mapping[str, Mapping[str, Any]],
    updates: Mapping[str, Mapping[str, str | None]],
) -> dict[str, dict[str, Any]]:
    """Apply deterministic Task 4 pointer updates to copied deck records."""
    result = {deck_id: dict(deck) for deck_id, deck in decks.items()}
    for deck_id, update in updates.items():
        if deck_id in result:
            result[deck_id].update(update)
    return result


def _state_replacements(
    snapshot: EvidenceSnapshot, stores: Mapping[str, Mapping[str, Mapping[str, Any]]]
) -> dict[Path, bytes]:
    """Serialize all existing state stores plus the authoritative evidence store."""
    replacements: dict[Path, bytes] = {}
    state_root = snapshot.project_root / ".research/presentations/state"
    for name, store_name in _STATE_PATH_TO_STORE.items():
        path = state_root / name
        if path not in snapshot.file_preimages and name != "evidence.yaml":
            continue
        if store_name == "evidence":
            replacements[path] = serialize_evidence_store(stores.get("evidence", {}))
        else:
            replacements[path] = yaml.safe_dump(
                {"version": 2, store_name: dict(stores.get(store_name, {}))},
                allow_unicode=True,
                sort_keys=True,
            ).encode("utf-8")
    evidence_path = evidence_store_path(snapshot.project_root)
    replacements[evidence_path] = serialize_evidence_store(stores.get("evidence", {}))
    return replacements
