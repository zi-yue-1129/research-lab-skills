#!/usr/bin/env python3
"""Migrate legacy report-slides presentation state to schema version one.

The migration is deliberately conservative.  A legacy record is copied with
its existing identity and values; the only semantic change is replacing the
legacy schema marker and, when approval evidence cannot be verified, moving an
approved deck to ``blocked``.  Approval events and plan documents are never
invented or rewritten.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from presentation_events import StateParseError
from presentation_contracts import contract_sha256
from presentation_events import effective_review_results
from presentation_transactions import WorkflowTransaction, incomplete_transaction_journals
from validate_deck_plan import validate_deck_approval, validate_deck_plan
from migration_scope import (
    MigrationError,
    PLURAL_PATH_KEYS as _PLURAL_PATH_KEYS,
    SINGULAR_PATH_KEYS as _SINGULAR_PATH_KEYS,
    assert_no_symlink_ancestors as _assert_no_symlink_ancestors,
    canonical_project_relative as _canonical_project_relative,
    iter_scope_entries as _iter_scope_entries,
    validate_record_paths as _validate_record_paths,
)


STATE_VERSION = 1
LEGACY_VERSION = 0
PRESENTATIONS_RELATIVE = Path(".research/presentations")
STATE_RELATIVE = PRESENTATIONS_RELATIVE / "state"
EVENTS_RELATIVE = PRESENTATIONS_RELATIVE / "events"
TRANSACTIONS_RELATIVE = PRESENTATIONS_RELATIVE / "transactions"
STATE_NAMES: dict[str, str] = {
    "decks.yaml": "decks",
    "plans.yaml": "plans",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
    "assignments.yaml": "assignments",
    "artifacts.yaml": "artifacts",
    "revision_requests.yaml": "revision_requests",
}
EVENT_SHARD_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\.jsonl$")
APPROVED_STATUSES = frozenset(
    {"approved", "producing", "draft_review", "revising", "validating", "completed"}
)
DECK_STATUSES = frozenset(
    {
        "planning",
        "content_review",
        "awaiting_approval",
        "approved",
        "producing",
        "draft_review",
        "validating",
        "revising",
        "completed",
        "blocked",
    }
)
SHA256_LENGTH = 64


class _UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML loader that rejects duplicate mapping keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        """Construct a mapping while rejecting repeated keys."""
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise MigrationError(f"duplicate YAML key {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _utc_timestamp() -> str:
    """Return a UTC timestamp suitable for a backup directory name."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _backup_timestamp() -> str:
    """Return the migration backup timestamp.

    This wrapper is intentionally separate so tests and embedding callers can
    provide a deterministic clock without patching the system clock globally.
    """
    return _utc_timestamp()


def _backup_identifier() -> str:
    """Return a unique backup suffix, replaceable by deterministic tests."""
    return uuid.uuid4().hex


def _read_regular_file(path: Path) -> tuple[bytes, int]:
    """Read one regular file without following a symlink.

    Args:
        path: File to read.

    Returns:
        Exact bytes and Unix permission bits.

    Raises:
        MigrationError: If the path is a symlink, non-regular file, or cannot
            be opened with no-follow semantics.
    """
    if not hasattr(os, "O_NOFOLLOW"):
        raise MigrationError(f"no-follow regular-file reads are unavailable: {path}")
    try:
        descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise MigrationError(f"unable to read regular file without following symlink: {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise MigrationError(f"expected regular file, not directory or special file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), stat.S_IMODE(metadata.st_mode)
    finally:
        os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    """Flush one directory entry operation to stable storage."""
    try:
        descriptor = os.open(str(directory), os.O_RDONLY)
    except OSError as exc:
        raise MigrationError(f"unable to open directory for fsync: {directory}: {exc}") from exc
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


_PATH_KEYS = _SINGULAR_PATH_KEYS | _PLURAL_PATH_KEYS


def _parse_yaml(path: Path, content: bytes) -> dict[str, Any]:
    """Parse one YAML state document using the duplicate-key loader."""
    try:
        value = yaml.load(content.decode("utf-8"), Loader=_UniqueKeyLoader)
    except MigrationError:
        raise
    except (UnicodeError, TypeError, yaml.YAMLError) as exc:
        raise StateParseError(f"Invalid YAML in {path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise StateParseError(f"Invalid state document in {path}: expected mapping")
    return value


def _schema_version(path: Path, document: Mapping[str, Any]) -> int:
    """Read and validate one legacy/target schema marker."""
    has_version = "version" in document
    has_schema_version = "schema_version" in document
    if has_version and has_schema_version:
        raise MigrationError(f"mixed schema keys in {path}: version and schema_version")
    marker = document.get("version", document.get("schema_version", LEGACY_VERSION))
    if isinstance(marker, bool) or not isinstance(marker, int) or marker not in {LEGACY_VERSION, STATE_VERSION}:
        raise StateParseError(f"Unsupported schema version {marker!r} in {path}")
    return marker


def _records_from_document(path: Path, document: Mapping[str, Any], top_key: str, version: int) -> dict[str, Any]:
    """Extract records, converting legacy lists to an ID-keyed map."""
    raw_records = document.get(top_key, {})
    if raw_records is None:
        raw_records = {}
    if version == STATE_VERSION and not isinstance(raw_records, dict):
        raise StateParseError(f"Invalid {top_key} map in {path}: expected mapping")
    if not isinstance(raw_records, (dict, list)):
        raise StateParseError(f"Invalid {top_key} records in {path}: expected mapping or list")
    records: dict[str, Any] = {}
    if isinstance(raw_records, dict):
        for record_key, record in raw_records.items():
            if not isinstance(record_key, str) or not record_key:
                raise StateParseError(f"Invalid {top_key} record id in {path}: {record_key!r}")
            if not isinstance(record, dict):
                raise StateParseError(f"Invalid {top_key} record {record_key!r} in {path}: expected mapping")
            records[record_key] = record
    else:
        for record in raw_records:
            if not isinstance(record, dict):
                raise StateParseError(f"Invalid {top_key} record in {path}: expected mapping")
            record_id = record.get("id")
            if not isinstance(record_id, str) or not record_id:
                raise StateParseError(f"Invalid {top_key} record id in {path}: {record_id!r}")
            if record_id in records:
                raise MigrationError(f"duplicate id {record_id!r} in {path}")
            records[record_id] = record
    for record_key, record in records.items():
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise StateParseError(f"Invalid {top_key} record {record_key!r} in {path}: missing id")
        if record_id != record_key:
            raise MigrationError(f"record id/key mismatch in {path}: {record_key!r} != {record_id!r}")
    return records


def _parse_event_line(path: Path, line_number: int, line: str) -> dict[str, Any]:
    """Parse one JSONL event line and reject duplicate object keys."""
    def pairs(pairs_list: list[tuple[str, Any]]) -> dict[str, Any]:
        """Construct a JSON object while rejecting repeated keys."""
        result: dict[str, Any] = {}
        for key, value in pairs_list:
            if key in result:
                raise MigrationError(f"duplicate JSON key {key!r} in {path} line {line_number}")
            result[key] = value
        return result

    try:
        value = json.loads(line, object_pairs_hook=pairs)
    except MigrationError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise StateParseError(f"Malformed JSON in event shard {path} line {line_number}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateParseError(f"Malformed event in event shard {path} line {line_number}: expected object")
    return value


def _validate_events(
    project_root: Path, event_files: Mapping[Path, tuple[bytes, int]]
) -> list[dict[str, Any]]:
    """Parse all event shards and reject duplicate immutable event IDs."""
    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in sorted(event_files, key=lambda item: item.relative_to(item.parents[2]).as_posix()):
        try:
            text = event_files[path][0].decode("utf-8")
        except UnicodeError as exc:
            raise StateParseError(f"Malformed JSON in event shard {path}: invalid UTF-8") from exc
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            event = _parse_event_line(path, line_number, line)
            event_id = event.get("id")
            if event_id is not None:
                if not isinstance(event_id, str) or not event_id:
                    raise StateParseError(f"Invalid event id in {path} line {line_number}")
                if event_id in seen_ids:
                    raise MigrationError(f"duplicate event id {event_id!r}")
                seen_ids.add(event_id)
            _validate_record_paths(project_root, event)
            events.append(event)
    return events


def _safe_plan_evidence(
    project_root: Path,
    deck: Mapping[str, Any],
    plans: Mapping[str, Any],
    events: list[Mapping[str, Any]],
) -> list[str]:
    """Return deterministic blockers for an approved deck's evidence chain.

    The migration deliberately consumes the same contracts as the workflow
    gates.  It never repairs an incomplete document by inferring a digest,
    approval identity, or review result.
    """
    deck_id = str(deck.get("id", "<unknown>"))
    blockers: set[str] = set()
    current_plan_id = deck.get("current_plan_id")
    plan_record: Mapping[str, Any] | None = None
    if not isinstance(current_plan_id, str) or not current_plan_id:
        blockers.add("approval evidence: missing current plan id")
    else:
        candidate = plans.get(current_plan_id)
        if isinstance(candidate, Mapping):
            plan_record = candidate
        else:
            blockers.add("approval evidence: missing plan record")

    plan_document: Mapping[str, Any] | None = None
    plan_digest: str | None = None
    plan_version: int | None = None
    if plan_record is not None:
        if plan_record.get("deck_id") != deck_id:
            blockers.add("approval evidence: plan deck binding mismatch")
        raw_version = plan_record.get("version", plan_record.get("plan_version"))
        if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 1:
            blockers.add("approval evidence: invalid plan version")
        else:
            plan_version = raw_version
        raw_path = plan_record.get("plan_path", plan_record.get("path"))
        relative_path = _canonical_project_relative(project_root, raw_path)
        plan_path = project_root / relative_path
        raw_digest = plan_record.get("sha256", plan_record.get("plan_sha256"))
        if isinstance(raw_digest, str) and len(raw_digest) == SHA256_LENGTH and all(
            character in "0123456789abcdef" for character in raw_digest
        ):
            plan_digest = raw_digest
        else:
            blockers.add("approval evidence: invalid plan digest")
        try:
            plan_bytes, _ = _read_regular_file(plan_path)
        except MigrationError as exc:
            if "unable to read" in str(exc) or "regular file" in str(exc):
                blockers.add("approval evidence: plan document is missing or unreadable")
            else:
                raise
        else:
            try:
                parsed_plan = _parse_yaml(plan_path, plan_bytes)
            except (MigrationError, StateParseError):
                blockers.add("approval evidence: plan document is malformed")
            else:
                plan_document = parsed_plan
                contract_errors = validate_deck_plan(parsed_plan)
                blockers.update(f"approval evidence: plan contract: {error}" for error in contract_errors)
                try:
                    canonical_digest = contract_sha256(parsed_plan)
                except (TypeError, ValueError, RecursionError):
                    canonical_digest = None
                    blockers.add("approval evidence: plan canonical digest is unavailable")
                if plan_digest != canonical_digest:
                    blockers.add("approval evidence: plan digest mismatch")
                if parsed_plan.get("deck_id") != deck_id:
                    blockers.add("approval evidence: plan document deck binding mismatch")
                if plan_version is not None and parsed_plan.get("plan_version") != plan_version:
                    blockers.add("approval evidence: plan document version mismatch")

    if deck.get("approved_plan_version") != plan_version:
        blockers.add("approval evidence: approved plan version mismatch")
    if deck.get("approved_plan_sha256") != plan_digest:
        blockers.add("approval evidence: approved plan digest mismatch")
    deck_identity = deck.get("identity_verifiable", True)
    if type(deck_identity) is not bool or deck_identity is False:
        blockers.add("approval evidence: deck identity is unverifiable")

    approval_id = deck.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        blockers.add("approval evidence: missing approval evidence")
    approval_candidates = [
        event
        for event in events
        if event.get("event") == "deck_approval"
        and event.get("deck_id") == deck_id
        and event.get("id") == approval_id
    ]
    matching_approval = False
    for event in approval_candidates:
        contract_errors = validate_deck_approval(event)
        if contract_errors:
            blockers.update(f"approval evidence: approval contract: {error}" for error in contract_errors)
            continue
        if event.get("decision") != "approve":
            blockers.add("approval evidence: decision must be approve")
            continue
        identity_flag = event.get("identity_verifiable", True)
        if type(identity_flag) is not bool or identity_flag is False:
            blockers.add("approval evidence: approver identity is unverifiable")
            continue
        approved_by = event.get("approved_by")
        if not isinstance(approved_by, str) or not approved_by.strip() or approved_by != approved_by.strip():
            blockers.add("approval evidence: approver identity is invalid")
            continue
        if (
            event.get("plan_version") != plan_version
            or event.get("plan_sha256") != plan_digest
            or event.get("approved_by") != deck.get("approved_by")
            or event.get("approved_at") != deck.get("approved_at")
            or event.get("approval_mode") != deck.get("approval_mode")
        ):
            blockers.add("approval evidence: approval binding mismatch")
            continue
        if plan_document is not None and event.get("approved_by") == plan_document.get("authored_by"):
            blockers.add("approval evidence: approver must differ from plan author")
            continue
        matching_approval = True
        break
    if not matching_approval:
        blockers.add("approval evidence: missing or unverifiable approval event")

    candidate_reviews = [
        event
        for event in events
        if event.get("event") == "review_result"
        and event.get("subject_type") == "deck"
        and event.get("subject_id") == deck_id
        and event.get("reviewer_role") in {"content", "content_reviewer"}
    ]
    # Select the effective review round before checking the current-plan
    # binding.  Filtering by plan first would let an older passing review for
    # the current plan hide a newer failed or stale-plan review.
    effective_reviews = effective_review_results(candidate_reviews)
    if len(effective_reviews) > 1:
        effective_reviews = [
            max(
                effective_reviews,
                key=lambda review: (
                    review.get("round") if type(review.get("round")) is int else 1,
                    str(review.get("ts", "")),
                    str(review.get("id", "")),
                ),
            )
        ]
    valid_review = False
    for review in effective_reviews:
        identity_flag = review.get("identity_verifiable", True)
        if type(identity_flag) is not bool or identity_flag is False:
            blockers.add("approval evidence: content reviewer identity is unverifiable")
            continue
        raw_round = review.get("round", 1)
        if type(raw_round) is not int or raw_round < 1:
            blockers.add("approval evidence: content review round is invalid")
            continue
        reviewer_id = review.get("reviewer_id")
        if (
            not isinstance(reviewer_id, str)
            or not reviewer_id.strip()
            or reviewer_id != reviewer_id.strip()
            or (plan_document is not None and reviewer_id == plan_document.get("authored_by"))
        ):
            blockers.add("approval evidence: content reviewer identity is invalid")
            continue
        if (
            review.get("current_plan_id") != current_plan_id
            or review.get("current_plan_version") != plan_version
            or review.get("current_plan_sha256") != plan_digest
        ):
            blockers.add("approval evidence: content review binding mismatch")
            continue
        if review.get("status") != "passed" or review.get("findings") != []:
            blockers.add("approval evidence: latest content review did not pass with no findings")
            continue
        valid_review = True
    if not effective_reviews:
        blockers.add("approval evidence: missing or unverifiable content review")
    elif not valid_review:
        blockers.add("approval evidence: missing or unverifiable content review")

    status = deck.get("status")
    if status in APPROVED_STATUSES and status != "approved":
        blockers.add(f"status evidence: missing target evidence for {status}")
    return sorted(blockers)


def _backup_file(destination: Path, content: bytes, mode: int) -> None:
    """Write one backup file with no replacement and durable bytes."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise MigrationError(f"no-follow backup writes are unavailable: {destination}")
    if destination.exists() or destination.is_symlink():
        raise MigrationError(f"backup destination already exists: {destination}")
    descriptor = os.open(
        str(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(destination, mode)
        descriptor = os.open(str(destination), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException:
        try:
            destination.unlink()
        except OSError:
            pass
        raise


def _publish_backup_no_replace(temporary: Path, final: Path) -> None:
    """Atomically publish a backup directory without replacing a raced name."""
    if final.exists() or final.is_symlink():
        raise FileExistsError(errno.EEXIST, "backup destination already exists", str(final))
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(temporary),
            -100,
            os.fsencode(final),
            1,
        )
        if result != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number), str(final))
        return
    raise MigrationError("atomic no-overwrite backup publication is unavailable on this platform")


def _remove_backup_tree(path: Path) -> None:
    """Remove a migration backup only when it is a known private directory."""
    if not path.exists() and not path.is_symlink():
        return
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise MigrationError(f"unable to inspect backup cleanup path {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MigrationError(f"refusing unsafe backup cleanup path: {path}")
    shutil.rmtree(path)


def _build_backup(
    project_root: Path,
    preimages: Mapping[Path, tuple[bytes, int]],
) -> Path:
    """Build and atomically publish a timestamped sibling backup directory."""
    presentations = project_root / PRESENTATIONS_RELATIVE
    timestamp = _backup_timestamp()
    identifier = _backup_identifier()
    final = presentations / f"state.backup-{timestamp}-{identifier}"
    temporary = presentations / f".state.backup-{timestamp}-{identifier}.tmp"
    if final.exists() or final.is_symlink() or temporary.exists() or temporary.is_symlink():
        raise MigrationError(f"backup destination already exists: {final}")
    temporary.mkdir(mode=0o700)
    published = False
    try:
        for source_path in sorted(preimages, key=lambda item: item.relative_to(project_root).as_posix()):
            relative = source_path.relative_to(presentations)
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _backup_file(destination, preimages[source_path][0], preimages[source_path][1])
        created_directories = {
            destination.parent
            for source_path in preimages
            for destination in [temporary / source_path.relative_to(presentations)]
        }
        for directory in sorted(created_directories, key=lambda item: (len(item.parts), item.as_posix()), reverse=True):
            _fsync_directory(directory)
        _fsync_directory(temporary)
        _publish_backup_no_replace(temporary, final)
        published = True
        _fsync_directory(presentations)
        return final
    except BaseException as primary_error:
        cleanup_failures: list[str] = []
        removed_backup = False
        for candidate in (temporary, final if published else None):
            if candidate is None:
                continue
            try:
                if candidate.exists() or candidate.is_symlink():
                    _remove_backup_tree(candidate)
                    removed_backup = True
            except Exception as exc:  # noqa: BLE001 - aggregate cleanup evidence
                cleanup_failures.append(f"{candidate}: {exc}")
        if removed_backup:
            try:
                _fsync_directory(presentations)
            except Exception as exc:  # noqa: BLE001 - aggregate cleanup evidence
                cleanup_failures.append(f"{presentations}: {exc}")
        if cleanup_failures:
            raise MigrationError("backup cleanup failed: " + "; ".join(cleanup_failures)) from primary_error
        raise


def _scope_paths(project_root: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Discover state and event files using metadata-only, no-follow checks."""
    state_root = project_root / STATE_RELATIVE
    events_root = project_root / EVENTS_RELATIVE
    _assert_no_symlink_ancestors(state_root, project_root)
    _assert_no_symlink_ancestors(events_root, project_root)
    state_paths: list[Path] = []
    event_paths: list[Path] = []
    for path in _iter_scope_entries(state_root):
        if path.name.endswith(".lock"):
            data_name = path.name.removesuffix(".lock")
            if data_name in STATE_NAMES:
                _assert_sidecar_target(path, state_root / data_name, "state")
                continue
            raise MigrationError(f"unknown presentation state sidecar: {path}")
        if path.name.endswith(".tmp"):
            raise MigrationError(f"temporary presentation state file is not allowed: {path}")
        if path.suffix != ".yaml" or path.name not in STATE_NAMES:
            raise MigrationError(f"unknown presentation state store: {path}")
        state_paths.append(path)
    for path in _iter_scope_entries(events_root):
        if path.name.endswith(".lock"):
            data_name = path.name.removesuffix(".lock")
            if EVENT_SHARD_PATTERN.fullmatch(data_name):
                _parse_event_shard_date(data_name, path)
                _assert_sidecar_target(path, events_root / data_name, "event")
                continue
            raise MigrationError(f"unknown presentation event sidecar: {path}")
        if path.name.endswith(".tmp"):
            raise MigrationError(f"temporary presentation event file is not allowed: {path}")
        if EVENT_SHARD_PATTERN.fullmatch(path.name) is None:
            raise MigrationError(f"unknown presentation event file: {path}")
        _parse_event_shard_date(path.name, path)
        event_paths.append(path)
    return tuple(sorted(state_paths)), tuple(sorted(event_paths))


def _assert_sidecar_target(sidecar: Path, target: Path, scope: str) -> None:
    """Require a canonical sidecar target to exist as a regular file."""
    if not os.path.lexists(target):
        raise MigrationError(f"orphan {scope} sidecar without canonical data file: {sidecar}")
    try:
        metadata = os.lstat(target)
    except OSError as exc:
        raise MigrationError(f"unable to inspect {scope} sidecar target {target}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MigrationError(f"{scope} sidecar target must be a regular file: {target}")


def _parse_event_shard_date(name: str, path: Path) -> None:
    """Require an event shard name to encode a real calendar date."""
    try:
        datetime.strptime(Path(name).stem, "%Y-%m-%d")
    except ValueError as exc:
        raise MigrationError(f"invalid presentation event shard date: {path}") from exc


def _scope_files(
    project_root: Path,
    state_paths: tuple[Path, ...] | None = None,
    event_paths: tuple[Path, ...] | None = None,
) -> tuple[dict[Path, tuple[bytes, int]], dict[Path, tuple[bytes, int]]]:
    """Read discovered state/event files with no-follow descriptors.

    Discovery itself is metadata-only.  Non-dry migration invokes this helper
    only after a transaction has acquired every discovered sidecar lock.
    """
    if state_paths is None or event_paths is None:
        discovered_state, discovered_events = _scope_paths(project_root)
    else:
        discovered_state, discovered_events = state_paths, event_paths
    state_files: dict[Path, tuple[bytes, int]] = {}
    event_files: dict[Path, tuple[bytes, int]] = {}
    selected_state_paths = discovered_state if state_paths is None else state_paths
    selected_event_paths = discovered_events if event_paths is None else event_paths
    for path in selected_state_paths:
        state_files[path] = _read_regular_file(path)
    for path in selected_event_paths:
        event_files[path] = _read_regular_file(path)
    return state_files, event_files


def _dump_state(top_key: str, records: Mapping[str, Any]) -> bytes:
    """Serialize a deterministic target-schema state document."""
    return yaml.safe_dump(
        {"version": STATE_VERSION, top_key: dict(records)},
        sort_keys=True,
        allow_unicode=True,
    ).encode("utf-8")


def _analyze_migration(
    project_root: Path,
    state_files: Mapping[Path, tuple[bytes, int]],
    event_files: Mapping[Path, tuple[bytes, int]],
) -> tuple[
    dict[str, Any],
    dict[Path, tuple[int, str, dict[str, Any]]],
    list[dict[str, Any]],
    int,
]:
    """Parse read-only preimages and construct a deterministic report."""
    parsed: dict[Path, tuple[int, str, dict[str, Any]]] = {}
    versions: set[int] = set()
    all_ids: set[str] = set()
    for path, (content, _) in sorted(state_files.items(), key=lambda item: item[0].as_posix()):
        top_key = STATE_NAMES[path.name]
        document = _parse_yaml(path, content)
        version = _schema_version(path, document)
        records = _records_from_document(path, document, top_key, version)
        _validate_record_paths(project_root, records)
        if top_key == "decks":
            for record in records.values():
                status = record.get("status")
                if status is not None and (not isinstance(status, str) or status not in DECK_STATUSES):
                    raise StateParseError(f"Invalid deck status {status!r} in {path}")
        for record_id in records:
            if record_id in all_ids:
                raise MigrationError(f"duplicate id {record_id!r} across state stores")
            all_ids.add(record_id)
        parsed[path] = (version, top_key, records)
        versions.add(version)
    if len(versions) > 1:
        raise MigrationError("mixed schema versions across presentation state stores")
    events = _validate_events(project_root, event_files)
    source_version = next(iter(versions), STATE_VERSION)
    report: dict[str, Any] = {
        "source_schema_version": source_version,
        "target_schema_version": STATE_VERSION,
        "migrated_ids": [],
        "blocked_ids": [],
        "blockers": {},
        "changed_paths": [],
    }
    if source_version == STATE_VERSION:
        return report, parsed, events, source_version

    decks: dict[str, Any] = {}
    plans: dict[str, Any] = {}
    for _, top_key, records in parsed.values():
        if top_key == "decks":
            decks = records
        elif top_key == "plans":
            plans = records
    blockers: dict[str, list[str]] = {}
    for deck_id in sorted(decks):
        deck = decks[deck_id]
        if deck.get("status") in APPROVED_STATUSES:
            deck_blockers = _safe_plan_evidence(project_root, deck, plans, events)
            if deck_blockers:
                blockers[deck_id] = deck_blockers
                deck["status"] = "blocked"
    report["blocked_ids"] = sorted(blockers)
    report["blockers"] = {deck_id: blockers[deck_id] for deck_id in sorted(blockers)}
    report["migrated_ids"] = sorted(all_ids - set(blockers))
    return report, parsed, events, source_version


def migrate_state(project_root: Path | str, dry_run: bool = False) -> dict[str, Any]:
    """Migrate legacy presentation state while locking before reads.

    Args:
        project_root: Root containing ``.research/presentations``.
        dry_run: Validate and report without filesystem writes or locks.

    Returns:
        A deterministic migration report.

    Raises:
        MigrationError: If state, events, paths, or evidence are unsafe.
        StateParseError: If a YAML/JSONL document is malformed.
    """
    root = Path(project_root).resolve()
    pending_journals = incomplete_transaction_journals(root)
    if dry_run and pending_journals:
        raise MigrationError(
            "transaction recovery required before dry-run: "
            + ", ".join(path.name for path in pending_journals)
        )
    if not dry_run and pending_journals:
        with WorkflowTransaction([], root):
            pass

    state_paths, event_paths = _scope_paths(root)
    state_files, event_files = _scope_files(root, state_paths, event_paths)
    initial_report, _, _, initial_source_version = _analyze_migration(root, state_files, event_files)
    if dry_run or initial_source_version == STATE_VERSION:
        return initial_report

    transaction_paths = tuple(sorted(state_paths + event_paths, key=lambda item: item.as_posix()))
    if not transaction_paths:
        return initial_report

    preexisting_sidecars = {
        path.with_suffix(path.suffix + ".lock")
        for path in transaction_paths
        if path.with_suffix(path.suffix + ".lock").exists()
    }
    transactions_directory = root / TRANSACTIONS_RELATIVE
    transactions_directory_preexisting = transactions_directory.exists()
    backup_path: Path | None = None
    commit_completed = False
    try:
        with WorkflowTransaction(transaction_paths, root) as transaction_handle:
            locked_state_paths, locked_event_paths = _scope_paths(root)
            if locked_state_paths != state_paths or locked_event_paths != event_paths:
                raise MigrationError("state/event scope changed while sidecar locks were held")
            state_files: dict[Path, tuple[bytes, int]] = {}
            event_files: dict[Path, tuple[bytes, int]] = {}
            preimages: dict[Path, tuple[bytes, int]] = {}
            for path in locked_state_paths + locked_event_paths:
                content, mode, _ = transaction_handle.snapshot(path)
                preimages[path] = (content, mode)
                if path in locked_state_paths:
                    state_files[path] = (content, mode)
                else:
                    event_files[path] = (content, mode)
            report, parsed, _, source_version = _analyze_migration(root, state_files, event_files)
            if source_version == STATE_VERSION:
                return report

            backup_path = _build_backup(root, preimages)
            for path, (_, top_key, records) in sorted(parsed.items(), key=lambda item: item[0].as_posix()):
                transaction_handle.stage_bytes(path, _dump_state(top_key, records))
            for path, (content, mode) in sorted(event_files.items(), key=lambda item: item[0].as_posix()):
                transaction_handle.stage_bytes(path, content, mode=mode)
            transaction_handle.commit()
            commit_completed = True
    except Exception:
        if backup_path is not None and not commit_completed:
            try:
                _remove_backup_tree(backup_path)
                _fsync_directory(backup_path.parent)
            except Exception as cleanup_error:
                raise MigrationError(f"migration failed and backup cleanup failed: {cleanup_error}") from cleanup_error
        raise
    changed_paths = [path.relative_to(root).as_posix() for path in transaction_paths]
    if backup_path is not None:
        changed_paths.append(backup_path.relative_to(root).as_posix())
    changed_paths.extend(
        sidecar.relative_to(root).as_posix()
        for sidecar in sorted(
            {
                path.with_suffix(path.suffix + ".lock")
                for path in transaction_paths
                if path.with_suffix(path.suffix + ".lock").exists()
                and path.with_suffix(path.suffix + ".lock") not in preexisting_sidecars
            },
            key=lambda item: item.as_posix(),
        )
    )
    if not transactions_directory_preexisting and transactions_directory.exists():
        changed_paths.append(transactions_directory.relative_to(root).as_posix())
    report["changed_paths"] = sorted(changed_paths)
    return report


class _ArgumentError(ValueError):
    """Raised for command-line errors that should be JSON-serializable."""


class _MigrationArgumentParser(argparse.ArgumentParser):
    """Argument parser that reports errors to the migration caller."""

    def error(self, message: str) -> None:
        """Raise a typed error instead of exiting with a traceback."""
        raise _ArgumentError(message)


def _main(argv: list[str] | None = None) -> int:
    """Run the migration CLI and emit JSON on success or failure."""
    parser = _MigrationArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    try:
        args = parser.parse_args(argv)
    except _ArgumentError as exc:
        payload = {"error": "ArgumentError", "message": str(exc)}
        print(json.dumps(payload, sort_keys=True))
        return 2
    try:
        report = migrate_state(args.project_root, dry_run=args.dry_run)
    except (MigrationError, StateParseError, OSError, ValueError, TypeError, RuntimeError, RecursionError) as exc:
        payload = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(payload, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True) if args.as_json else json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the migration command-line interface.

    Args:
        argv: Optional argument vector; process arguments are used by default.

    Returns:
        Zero on a successful migration or validation, one on a structured
        migration error, or exit 2 for structured argument errors.
    """
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
