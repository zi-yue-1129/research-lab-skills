#!/usr/bin/env python3
"""Immutable no-follow snapshots for report-slides evidence migration.

The snapshot boundary is deliberately narrow: it reads supported presentation
stores, immutable event shards, and declared historical artifact bytes once.
Consumers must use the captured values and never re-open mutable workflow
paths while projecting evidence.
"""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from migration_scope import MigrationError, canonical_relative_path
from presentation_evidence_cas import (
    CasError,
    CasObject,
    plan_cas_objects,
    read_verified_source,
)
from presentation_evidence_contracts import artifact_policy_for_event
from presentation_events import StateParseError
from presentation_no_follow import (
    MissingPathError,
    NoFollowPathError,
    open_parent_no_follow,
    read_stable_regular,
    read_regular_siblings,
)


_PRESENTATIONS_RELATIVE = Path(".research/presentations")
_STATE_RELATIVE = _PRESENTATIONS_RELATIVE / "state"
_EVENTS_RELATIVE = _PRESENTATIONS_RELATIVE / "events"
_STATE_NAMES = {
    "decks.yaml": "decks",
    "plans.yaml": "plans",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
    "assignments.yaml": "assignments",
    "artifacts.yaml": "artifacts",
    "revision_requests.yaml": "revision_requests",
    "evidence.yaml": "evidence",
}
_EVENT_SHARD_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\.jsonl$")


class SnapshotError(MigrationError):
    """Raised when an immutable evidence snapshot cannot be built safely."""


@dataclass(frozen=True)
class PlanPreimage:
    """One no-follow immutable preimage for a current approved plan.

    Attributes:
        path: Canonical project-relative plan path.
        content: Exact plan bytes captured through its retained parent.
        mode: Permission bits observed when the plan was captured.
        mtime_ns: Nanosecond modification time observed when captured.
        sha256: SHA-256 digest of ``content``.
    """

    path: str
    content: bytes
    mode: int
    mtime_ns: int
    sha256: str


class _UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML loader that rejects duplicate mapping keys."""

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        """Construct one YAML mapping while rejecting repeated keys."""
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise SnapshotError(f"duplicate YAML key {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


@dataclass(frozen=True)
class EvidenceSnapshot:
    """Locked or dry-run immutable presentation state and audit history.

    Attributes:
        project_root: Canonical project root used for the no-follow capture.
        schema_version: One verified shared presentation-state version.
        stores: Frozen records keyed first by authoritative store name.
        events: Frozen JSONL events in deterministic shard and line order.
        file_preimages: Exact no-follow bytes keyed by absolute source path.
        artifact_objects: Historical source snapshots keyed by provenance path.
    """

    project_root: Path
    schema_version: int
    stores: Mapping[str, Mapping[str, Mapping[str, Any]]]
    events: tuple[Mapping[str, Any], ...]
    file_preimages: Mapping[Path, bytes]
    artifact_objects: Mapping[str, CasObject] = field(default_factory=dict)
    active_plan_preimages: Mapping[str, PlanPreimage] = field(default_factory=dict)


def build_snapshot(project_root: Path, *, locked: bool = False) -> EvidenceSnapshot:
    """Read one no-follow immutable snapshot without mutating state.

    Args:
        project_root: Existing project root containing presentation state.
        locked: Whether the caller already holds the migration sidecar locks.
            The value documents the calling phase; this function never creates
            or acquires a lock in either mode.

    Returns:
        A frozen snapshot of state, JSONL bytes, and readable artifact bytes.

    Raises:
        SnapshotError: If scope, schemas, JSONL, or artifact capture is unsafe.
        StateParseError: If a state document or event shard is malformed.
    """
    if not isinstance(locked, bool):
        raise SnapshotError("locked must be a boolean")
    root = _project_root(project_root)
    state_bytes = _read_scope(root, _STATE_RELATIVE, _STATE_NAMES, "state")
    event_bytes = _read_event_scope(root)
    stores, schema_version = _parse_stores(root, state_bytes)
    events = _parse_event_shards(root, event_bytes)
    frozen_stores = _freeze(stores)
    frozen_events = tuple(_freeze(event) for event in events)
    file_preimages: dict[Path, bytes] = {}
    for relative_path, content in state_bytes.items():
        file_preimages[root / relative_path] = content
    for relative_path, content in event_bytes.items():
        file_preimages[root / relative_path] = content
    artifact_objects = _capture_artifact_objects(root, events, file_preimages)
    _capture_visual_review_preimages(root, events, file_preimages)
    active_plan_preimages = _capture_active_plan_preimages(
        root, stores, file_preimages
    )
    return EvidenceSnapshot(
        project_root=root,
        schema_version=schema_version,
        stores=frozen_stores,
        events=frozen_events,
        file_preimages=MappingProxyType(dict(file_preimages)),
        artifact_objects=MappingProxyType(dict(artifact_objects)),
        active_plan_preimages=MappingProxyType(dict(active_plan_preimages)),
    )


def parse_event_line(path: Path, line_number: int, line: str) -> dict[str, Any]:
    """Parse one JSONL event line and reject duplicate object keys.

    Args:
        path: Immutable shard path used only for diagnostics.
        line_number: One-based source line number.
        line: Decoded JSON object line.

    Returns:
        The parsed event mapping.

    Raises:
        MigrationError: If an object key is repeated.
        StateParseError: If JSON is malformed or is not an object.
    """

    def pairs(pairs_list: list[tuple[str, Any]]) -> dict[str, Any]:
        """Construct a JSON object while rejecting repeated keys."""
        result: dict[str, Any] = {}
        for key, value in pairs_list:
            if key in result:
                raise SnapshotError(
                    f"duplicate JSON key {key!r} in {path} line {line_number}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(line, object_pairs_hook=pairs)
    except SnapshotError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise StateParseError(
            f"Malformed JSON in event shard {path} line {line_number}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise StateParseError(
            f"Malformed event in event shard {path} line {line_number}: expected object"
        )
    return value


def parse_state_document(
    path: Path, content: bytes, top_key: str
) -> tuple[int, dict[str, dict[str, Any]]]:
    """Parse one immutable presentation store without touching its path again.

    Args:
        path: Source path used only for stable diagnostics.
        content: Exact already-captured YAML bytes.
        top_key: Authoritative record-map key for this store.

    Returns:
        The verified schema version and ID-keyed record mapping.

    Raises:
        SnapshotError: If marker and record identities are inconsistent.
        StateParseError: If YAML or the versioned record representation is
            malformed.
    """
    document = parse_yaml_document(path, content)
    version = _schema_version(path, document)
    return version, _records_from_document(path, document, top_key, version)


def parse_yaml_document(path: Path, content: bytes) -> dict[str, Any]:
    """Parse one captured YAML mapping with duplicate-key rejection.

    Args:
        path: Source path used only for stable diagnostics.
        content: Exact already-captured YAML bytes.

    Returns:
        The parsed YAML mapping, or an empty mapping for an empty document.

    Raises:
        SnapshotError: If a YAML key occurs more than once.
        StateParseError: If bytes cannot form a YAML mapping.
    """
    return _parse_yaml(path, content)


def parse_event_shard(path: Path, content: bytes) -> list[dict[str, Any]]:
    """Parse exact captured JSONL bytes while preserving source line order.

    Args:
        path: Source shard path used only for stable diagnostics.
        content: Exact already-captured JSONL bytes.

    Returns:
        Parsed object events in source line order. Blank lines are excluded.

    Raises:
        SnapshotError: If a JSON object repeats a key.
        StateParseError: If UTF-8 or JSON object structure is malformed.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeError as exc:
        raise StateParseError(f"Malformed JSON in event shard {path}: invalid UTF-8") from exc
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            events.append(parse_event_line(path, line_number, line))
    return events


def _project_root(project_root: Path) -> Path:
    """Resolve one existing project root without accepting a file target."""
    if not isinstance(project_root, Path):
        raise SnapshotError("project_root must be a pathlib.Path")
    try:
        root = project_root.resolve(strict=True)
    except OSError as exc:
        raise SnapshotError(f"project root cannot be resolved: {project_root}") from exc
    if not root.is_dir():
        raise SnapshotError(f"project root must be a directory: {project_root}")
    return root


def _read_scope(
    project_root: Path,
    relative_directory: Path,
    names: Mapping[str, str],
    scope: str,
) -> dict[str, bytes]:
    """Read one known state-like directory through a retained descriptor."""
    try:
        anchor = open_parent_no_follow(
            project_root,
            (relative_directory / "snapshot-probe").as_posix(),
            create_parents=False,
        )
    except MissingPathError:
        return {}
    except NoFollowPathError as exc:
        raise SnapshotError(f"unsafe presentation {scope} scope") from exc
    try:
        contents = read_regular_siblings(anchor)
    except NoFollowPathError as exc:
        raise SnapshotError(f"unsafe presentation {scope} scope entry") from exc
    finally:
        anchor.close()
    data: dict[str, bytes] = {}
    for name, content in sorted(contents.items()):
        if name.endswith(".lock"):
            target_name = name.removesuffix(".lock")
            if name != "workflow.lock" and target_name not in names:
                raise SnapshotError(f"unknown presentation {scope} sidecar: {name}")
            continue
        if name.endswith(".tmp") or name not in names:
            raise SnapshotError(f"unknown presentation {scope} file: {name}")
        data[(relative_directory / name).as_posix()] = content
    return data


def _read_event_scope(project_root: Path) -> dict[str, bytes]:
    """Read valid daily JSONL shards through a retained events descriptor."""
    try:
        anchor = open_parent_no_follow(
            project_root,
            (_EVENTS_RELATIVE / "snapshot-probe").as_posix(),
            create_parents=False,
        )
    except MissingPathError:
        return {}
    except NoFollowPathError as exc:
        raise SnapshotError("unsafe presentation event scope") from exc
    try:
        contents = read_regular_siblings(anchor)
    except NoFollowPathError as exc:
        raise SnapshotError("unsafe presentation event scope entry") from exc
    finally:
        anchor.close()
    data: dict[str, bytes] = {}
    for name, content in sorted(contents.items()):
        if name.endswith(".lock"):
            target_name = name.removesuffix(".lock")
            if _EVENT_SHARD_PATTERN.fullmatch(target_name) is None:
                raise SnapshotError(f"unknown presentation event sidecar: {name}")
            _validate_event_shard_date(target_name)
            continue
        if _EVENT_SHARD_PATTERN.fullmatch(name) is None:
            raise SnapshotError(f"unknown presentation event file: {name}")
        _validate_event_shard_date(name)
        data[(_EVENTS_RELATIVE / name).as_posix()] = content
    return data


def _validate_event_shard_date(name: str) -> None:
    """Require one event shard filename to encode a real calendar date."""
    try:
        datetime.strptime(Path(name).stem, "%Y-%m-%d")
    except ValueError as exc:
        raise SnapshotError(f"invalid presentation event shard date: {name}") from exc


def _parse_stores(
    project_root: Path, state_bytes: Mapping[str, bytes]
) -> tuple[dict[str, dict[str, dict[str, Any]]], int]:
    """Parse one exact versioned record map from each captured store."""
    stores: dict[str, dict[str, dict[str, Any]]] = {}
    versions: set[int] = set()
    all_ids: set[str] = set()
    for relative_path, content in sorted(state_bytes.items()):
        name = Path(relative_path).name
        top_key = _STATE_NAMES[name]
        version, records = parse_state_document(
            project_root / relative_path, content, top_key
        )
        for record_id in records:
            if record_id in all_ids:
                raise SnapshotError(f"duplicate id {record_id!r} across state stores")
            all_ids.add(record_id)
        stores[top_key] = records
        versions.add(version)
    if len(versions) > 1:
        raise SnapshotError("mixed schema versions across presentation state stores")
    return stores, next(iter(versions), 0)


def _parse_yaml(path: Path, content: bytes) -> dict[str, Any]:
    """Parse one captured YAML document with duplicate-key rejection."""
    try:
        value = yaml.load(content.decode("utf-8"), Loader=_UniqueKeyLoader)
    except SnapshotError:
        raise
    except (UnicodeError, TypeError, yaml.YAMLError) as exc:
        raise StateParseError(f"Invalid YAML in {path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise StateParseError(f"Invalid state document in {path}: expected mapping")
    return value


def _schema_version(path: Path, document: Mapping[str, Any]) -> int:
    """Read exactly one supported legacy or schema-v2 version marker."""
    has_version = "version" in document
    has_schema_version = "schema_version" in document
    if has_version and has_schema_version:
        raise SnapshotError(f"mixed schema keys in {path}: version and schema_version")
    marker = document.get("version", document.get("schema_version", 0))
    if type(marker) is not int or marker not in {0, 1, 2}:
        raise StateParseError(f"Unsupported schema version {marker!r} in {path}")
    return marker


def _records_from_document(
    path: Path, document: Mapping[str, Any], top_key: str, version: int
) -> dict[str, dict[str, Any]]:
    """Extract exact ID-keyed records while retaining legacy list support."""
    raw_records = document.get(top_key, {})
    if raw_records is None:
        raw_records = {}
    if version in {1, 2} and not isinstance(raw_records, dict):
        raise StateParseError(f"Invalid {top_key} map in {path}: expected mapping")
    if not isinstance(raw_records, (dict, list)):
        raise StateParseError(
            f"Invalid {top_key} records in {path}: expected mapping or list"
        )
    records: dict[str, dict[str, Any]] = {}
    raw_items = raw_records.items() if isinstance(raw_records, dict) else ()
    if isinstance(raw_records, dict):
        for record_key, record in raw_items:
            if not isinstance(record_key, str) or not record_key:
                raise StateParseError(
                    f"Invalid {top_key} record id in {path}: {record_key!r}"
                )
            if not isinstance(record, dict):
                raise StateParseError(
                    f"Invalid {top_key} record {record_key!r} in {path}: expected mapping"
                )
            records[record_key] = record
    else:
        for record in raw_records:
            if not isinstance(record, dict):
                raise StateParseError(
                    f"Invalid {top_key} record in {path}: expected mapping"
                )
            record_id = record.get("id")
            if not isinstance(record_id, str) or not record_id:
                raise StateParseError(
                    f"Invalid {top_key} record id in {path}: {record_id!r}"
                )
            if record_id in records:
                raise SnapshotError(f"duplicate id {record_id!r} in {path}")
            records[record_id] = record
    for record_key, record in records.items():
        if record.get("id") != record_key:
            raise SnapshotError(
                f"record id/key mismatch in {path}: {record_key!r} != {record.get('id')!r}"
            )
    return records


def _parse_event_shards(
    project_root: Path, event_bytes: Mapping[str, bytes]
) -> list[dict[str, Any]]:
    """Parse captured JSONL shards in deterministic source order."""
    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for relative_path, content in sorted(event_bytes.items()):
        path = project_root / relative_path
        for event in parse_event_shard(path, content):
            event_id = event.get("id")
            if event_id is not None:
                if not isinstance(event_id, str) or not event_id:
                    raise StateParseError(f"Invalid event id in event shard {path}")
                if event_id in seen_ids:
                    raise SnapshotError(f"duplicate event id {event_id!r}")
                seen_ids.add(event_id)
            events.append(event)
    return events


def _capture_active_plan_preimages(
    project_root: Path,
    stores: Mapping[str, Mapping[str, Mapping[str, Any]]],
    file_preimages: dict[Path, bytes],
) -> dict[str, PlanPreimage]:
    """Capture every canonical plan selected by an approved current deck.

    Args:
        project_root: Canonical root used for no-follow plan reads.
        stores: Parsed presentation-state stores from the same snapshot.
        file_preimages: Mutable preimage map extended with plan bytes.

    Returns:
        Plan-ID-keyed no-follow preimages for active approved plans.

    Raises:
        SnapshotError: If an approved plan identity, path, or source file is
            missing, noncanonical, special, symlinked, or changes while read.
    """
    decks = stores.get("decks", {})
    plans = stores.get("plans", {})
    preimages: dict[str, PlanPreimage] = {}
    for deck_id in sorted(decks):
        deck = decks[deck_id]
        if not _has_approved_plan_context(deck):
            continue
        plan_id = deck.get("current_plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            raise SnapshotError(f"approved deck {deck_id!r} requires current_plan_id")
        plan = plans.get(plan_id)
        if not isinstance(plan, Mapping):
            raise SnapshotError(
                f"approved deck {deck_id!r} current plan {plan_id!r} is unavailable"
            )
        if plan.get("id") != plan_id or plan.get("deck_id") != deck_id:
            raise SnapshotError(f"approved deck {deck_id!r} plan identity is invalid")
        try:
            relative_path = canonical_relative_path(plan.get("plan_path"))
        except MigrationError as exc:
            raise SnapshotError(
                f"approved plan {plan_id!r} path must be canonical"
            ) from exc
        existing = preimages.get(plan_id)
        if existing is not None:
            if existing.path != relative_path:
                raise SnapshotError(f"approved plan {plan_id!r} paths are inconsistent")
            continue
        try:
            anchored = open_parent_no_follow(
                project_root, relative_path, create_parents=False
            )
            try:
                content, metadata = read_stable_regular(anchored)
            finally:
                anchored.close()
        except (MissingPathError, NoFollowPathError, OSError) as exc:
            raise SnapshotError(
                f"cannot snapshot current approved plan {relative_path}: {exc}"
            ) from exc
        preimage = PlanPreimage(
            path=relative_path,
            content=content,
            mode=metadata.st_mode & 0o777,
            mtime_ns=metadata.st_mtime_ns,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        preimages[plan_id] = preimage
        file_preimages[project_root / relative_path] = content
    return preimages


def _has_approved_plan_context(deck: Mapping[str, Any]) -> bool:
    """Return whether a deck declares any active approved-plan state.

    Args:
        deck: One parsed deck record from immutable state.

    Returns:
        True when the deck requires an immutable current plan capture.

    Raises:
        SnapshotError: If the approval fields use booleans or invalid types.
    """
    version = deck.get("approved_plan_version")
    digest = deck.get("approved_plan_sha256")
    if version is None and digest is None:
        return False
    if type(version) is not int or version <= 0:
        raise SnapshotError("approved_plan_version must be a positive integer")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise SnapshotError("approved_plan_sha256 must be a SHA-256 digest")
    return True


def _capture_artifact_objects(
    project_root: Path,
    events: list[dict[str, Any]],
    file_preimages: dict[Path, bytes],
) -> dict[str, CasObject]:
    """Capture available historical artifacts with the shared CAS planner."""
    objects: dict[str, CasObject] = {}
    candidate_paths = sorted(
        {
            relative_path
            for event in events
            for relative_path in _declared_artifact_paths(event)
        }
    )
    for relative_path in candidate_paths:
        try:
            planned = plan_cas_objects(
                project_root, {relative_path: project_root / relative_path}
            )
        except CasError as exc:
            if str(exc).startswith("missing source artifact:"):
                continue
            raise SnapshotError(
                f"cannot snapshot historical artifact {relative_path}: {exc}"
            ) from exc
        object_ = next(iter(planned.values()))
        objects[relative_path] = object_
        file_preimages[project_root / relative_path] = object_.content
    return objects


def _capture_visual_review_preimages(
    project_root: Path,
    events: list[dict[str, Any]],
    file_preimages: dict[Path, bytes],
) -> None:
    """Freeze review-record bytes required by visual-review source events."""
    source_paths: set[str] = set()
    for event in events:
        if event.get("event") != "visual_review":
            continue
        try:
            source_paths.add(canonical_relative_path(event.get("visual_review_path")))
        except MigrationError as exc:
            raise SnapshotError("visual_review_path must be a canonical path") from exc
    for relative_path in sorted(source_paths):
        try:
            object_ = read_verified_source(project_root, relative_path)
        except CasError as exc:
            raise SnapshotError(
                f"cannot snapshot historical visual review {relative_path}: {exc}"
            ) from exc
        file_preimages[project_root / relative_path] = object_.content


def _declared_artifact_paths(event: Mapping[str, Any]) -> tuple[str, ...]:
    """Return lexically safe artifact paths that may be captured before projection."""
    event_kind = event.get("event")
    has_artifact_maps = (
        "artifact_digests" in event or "artifact_bindings" in event
    )
    if not isinstance(event_kind, str) or (
        has_artifact_maps and artifact_policy_for_event(event_kind) == "none"
    ):
        if has_artifact_maps:
            raise SnapshotError("unregistered event kinds cannot carry artifact maps")
    raw_paths: list[object] = []
    if event_kind == "draft_preview":
        rendered = event.get("rendered_slide_paths")
        if isinstance(rendered, list):
            raw_paths.extend(
                entry.get("path") for entry in rendered if isinstance(entry, Mapping)
            )
        raw_paths.append(event.get("contact_sheet_path"))
    elif event_kind == "deck_completion":
        digests = event.get("artifact_digests")
        if isinstance(digests, Mapping):
            raw_paths.extend(digests)
    paths: list[str] = []
    for raw_path in raw_paths:
        try:
            paths.append(canonical_relative_path(raw_path))
        except MigrationError:
            continue
    return tuple(paths)


def _freeze(value: Any, active_ids: set[int] | None = None) -> Any:
    """Freeze parsed values while rejecting only active YAML alias cycles.

    Args:
        value: Parsed YAML or JSON value to make immutable.
        active_ids: Object identities on the current recursive path. Repeated
            aliases outside that path are valid and are frozen independently.

    Returns:
        An immutable copy of ``value``.

    Raises:
        SnapshotError: If a mapping, list, or set aliases itself through the
            active recursive path.
    """
    active = set() if active_ids is None else active_ids
    if isinstance(value, Mapping):
        return _freeze_mapping(value, active)
    if isinstance(value, list):
        return _freeze_list(value, active)
    if isinstance(value, set):
        return _freeze_set(value, active)
    return value


def _freeze_mapping(value: Mapping[Any, Any], active_ids: set[int]) -> Mapping[Any, Any]:
    """Freeze one mapping after detecting active YAML alias recursion."""
    _enter_freeze(value, active_ids)
    try:
        return MappingProxyType(
            {key: _freeze(item, active_ids) for key, item in value.items()}
        )
    finally:
        active_ids.remove(id(value))


def _freeze_list(value: list[Any], active_ids: set[int]) -> tuple[Any, ...]:
    """Freeze one list after detecting active YAML alias recursion."""
    _enter_freeze(value, active_ids)
    try:
        return tuple(_freeze(item, active_ids) for item in value)
    finally:
        active_ids.remove(id(value))


def _freeze_set(value: set[Any], active_ids: set[int]) -> frozenset[Any]:
    """Freeze one set after detecting active YAML alias recursion."""
    _enter_freeze(value, active_ids)
    try:
        return frozenset(_freeze(item, active_ids) for item in value)
    finally:
        active_ids.remove(id(value))


def _enter_freeze(value: object, active_ids: set[int]) -> None:
    """Register one container on the active freeze stack or reject a cycle."""
    identity = id(value)
    if identity in active_ids:
        raise SnapshotError("cyclic YAML alias is not supported in snapshots")
    active_ids.add(identity)
