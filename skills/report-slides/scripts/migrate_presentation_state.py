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
import hashlib
import json
import os
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml

from presentation_events import StateParseError
from presentation_transactions import WorkflowTransaction, incomplete_transaction_journals


STATE_VERSION = 1
LEGACY_VERSION = 0
PRESENTATIONS_RELATIVE = Path(".research/presentations")
STATE_RELATIVE = PRESENTATIONS_RELATIVE / "state"
EVENTS_RELATIVE = PRESENTATIONS_RELATIVE / "events"
STATE_NAMES: dict[str, str] = {
    "decks.yaml": "decks",
    "plans.yaml": "plans",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
    "assignments.yaml": "assignments",
    "artifacts.yaml": "artifacts",
    "revision_requests.yaml": "revision_requests",
}
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


class MigrationError(RuntimeError):
    """Raised when persisted presentation state is unsafe to migrate."""


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


def _iter_scope_entries(root: Path) -> Iterator[Path]:
    """Yield regular files below ``root`` while rejecting symlink entries."""
    if not root.exists():
        return
    try:
        root_metadata = os.lstat(root)
    except OSError as exc:
        raise MigrationError(f"unable to inspect state/event scope {root}: {exc}") from exc
    if stat.S_ISLNK(root_metadata.st_mode):
        raise MigrationError(f"state/event scope must not be a symlink: {root}")
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise MigrationError(f"state/event scope must be a directory: {root}")
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name, reverse=True)
        except OSError as exc:
            raise MigrationError(f"unable to inspect state/event scope {current}: {exc}") from exc
        for entry in entries:
            entry_path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise MigrationError(f"unable to inspect state/event entry {entry_path}: {exc}") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise MigrationError(f"state/event entry must not be a symlink: {entry_path}")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(entry_path)
            elif stat.S_ISREG(metadata.st_mode):
                yield entry_path
            else:
                raise MigrationError(f"state/event entry must be regular or directory: {entry_path}")


def _assert_no_symlink_ancestors(path: Path, project_root: Path) -> None:
    """Reject a state/event scope whose parent path redirects elsewhere."""
    root = project_root.resolve()
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError as exc:
        raise MigrationError(f"scope escapes project root: {path}") from exc
    current = root
    for part in relative_parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise MigrationError(f"unable to inspect scope ancestor {current}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MigrationError(f"state/event scope contains a symlink ancestor: {current}")


def _canonical_project_relative(project_root: Path, raw_value: object) -> str:
    """Validate one POSIX project-relative path and reject symlink escapes."""
    if not isinstance(raw_value, str) or not raw_value or "\x00" in raw_value:
        raise MigrationError(f"path must be a non-empty relative path: {raw_value!r}")
    if raw_value.startswith("/") or "\\" in raw_value:
        raise MigrationError(f"path must be project-relative and POSIX-normalized: {raw_value!r}")
    parts = raw_value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MigrationError(f"path traversal or non-normalized path rejected: {raw_value!r}")
    root = project_root.resolve()
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise MigrationError(f"unable to inspect path {raw_value!r}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MigrationError(f"path contains a symlink and cannot be verified: {raw_value!r}")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise MigrationError(f"path escapes project root: {raw_value!r}") from exc
    return "/".join(parts)


_PATH_KEYS = frozenset(
    {
        "path",
        "relative_path",
        "plan_path",
        "assignment_path",
        "artifact_path",
        "slide_spec_path",
        "preview_path",
        "source_path",
        "output_path",
        "rendered_path",
        "source_paths",
        "rendered_slide_paths",
    }
)


def _validate_record_paths(project_root: Path, value: object, key: str | None = None) -> None:
    """Validate all persisted path-bearing fields recursively."""
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if isinstance(child_key, str) and (
                child_key in _PATH_KEYS or child_key.endswith("_path") or child_key.endswith("_paths")
            ):
                if child_value is None:
                    continue
                if isinstance(child_value, list):
                    for item in child_value:
                        if isinstance(item, Mapping):
                            _validate_record_paths(project_root, item)
                        else:
                            _canonical_project_relative(project_root, item)
                else:
                    _canonical_project_relative(project_root, child_value)
            _validate_record_paths(project_root, child_value, str(child_key))
    elif isinstance(value, list):
        for item in value:
            _validate_record_paths(project_root, item, key)


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
    """Return deterministic blockers for an approved deck's evidence chain."""
    deck_id = str(deck.get("id", "<unknown>"))
    blockers: set[str] = set()
    current_plan_id = deck.get("current_plan_id")
    if not isinstance(current_plan_id, str) or not current_plan_id:
        blockers.add("approval evidence: missing current plan id")
        plan_record: Mapping[str, Any] | None = None
    else:
        candidate = plans.get(current_plan_id)
        plan_record = candidate if isinstance(candidate, Mapping) else None
        if plan_record is None:
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
        try:
            relative_path = _canonical_project_relative(project_root, raw_path)
        except MigrationError:
            raise
        plan_path = project_root / relative_path
        raw_digest = plan_record.get("plan_sha256", plan_record.get("sha256"))
        if (
            not isinstance(raw_digest, str)
            or len(raw_digest) != SHA256_LENGTH
            or any(character not in "0123456789abcdef" for character in raw_digest)
        ):
            blockers.add("approval evidence: invalid plan digest")
        else:
            plan_digest = raw_digest
        try:
            plan_bytes, _ = _read_regular_file(plan_path)
        except MigrationError as exc:
            if "unable to read" in str(exc) or "regular file" in str(exc):
                blockers.add("approval evidence: plan document is missing or unreadable")
            else:
                raise
        else:
            actual_digest = hashlib.sha256(plan_bytes).hexdigest()
            if plan_digest is not None and actual_digest != plan_digest:
                blockers.add("approval evidence: plan digest mismatch")
            try:
                parsed_plan = _parse_yaml(plan_path, plan_bytes)
            except (MigrationError, StateParseError):
                blockers.add("approval evidence: plan document is malformed")
            else:
                if not isinstance(parsed_plan, Mapping):
                    blockers.add("approval evidence: plan document is not a mapping")
                else:
                    plan_document = parsed_plan
                    if parsed_plan.get("deck_id") != deck_id:
                        blockers.add("approval evidence: plan document deck binding mismatch")
                    document_version = parsed_plan.get("plan_version", parsed_plan.get("version"))
                    if plan_version is not None and document_version != plan_version:
                        blockers.add("approval evidence: plan document version mismatch")

    if deck.get("approved_plan_version") != plan_version:
        blockers.add("approval evidence: approved plan version mismatch")
    if deck.get("approved_plan_sha256") != plan_digest:
        blockers.add("approval evidence: approved plan digest mismatch")

    approval_id = deck.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        blockers.add("approval evidence: missing approval evidence")
    approval_events = [
        event
        for event in events
        if event.get("event") == "deck_approval"
        and event.get("deck_id") == deck_id
        and (approval_id is None or event.get("id") == approval_id)
    ]
    matching_approval = False
    for event in approval_events:
        if event.get("plan_version") != plan_version or event.get("plan_sha256") != plan_digest:
            continue
        if not isinstance(event.get("approved_by"), str) or not event.get("approved_by"):
            continue
        if event.get("approved_by") == (plan_document or {}).get("authored_by"):
            continue
        if not isinstance(event.get("approved_at"), str) or not event.get("approval_mode"):
            continue
        matching_approval = True
        break
    if not matching_approval:
        blockers.add("approval evidence: missing or unverifiable approval event")

    matching_review = False
    for event in events:
        if (
            event.get("event") == "review_result"
            and event.get("subject_type") == "deck"
            and event.get("subject_id") == deck_id
            and event.get("reviewer_role") in {"content", "content_reviewer"}
            and event.get("status") == "passed"
            and event.get("current_plan_id") == current_plan_id
            and event.get("current_plan_version") == plan_version
            and event.get("current_plan_sha256") == plan_digest
            and isinstance(event.get("reviewer_id"), str)
            and bool(event.get("reviewer_id"))
            and event.get("reviewer_id") != (plan_document or {}).get("authored_by")
        ):
            matching_review = True
            break
    if not matching_review:
        blockers.add("approval evidence: missing or unverifiable content review")
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
    except BaseException:
        try:
            destination.unlink()
        except OSError:
            pass
        raise


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
    try:
        for source_path in sorted(preimages, key=lambda item: item.relative_to(project_root).as_posix()):
            relative = source_path.relative_to(presentations)
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _backup_file(destination, preimages[source_path][0], preimages[source_path][1])
        _fsync_directory(temporary)
        os.replace(temporary, final)
        _fsync_directory(presentations)
        return final
    except BaseException:
        if temporary.exists() or temporary.is_symlink():
            _remove_backup_tree(temporary)
        raise


def _scope_files(project_root: Path) -> tuple[dict[Path, tuple[bytes, int]], dict[Path, tuple[bytes, int]]]:
    """Collect state and event preimages using no-follow reads."""
    state_root = project_root / STATE_RELATIVE
    events_root = project_root / EVENTS_RELATIVE
    _assert_no_symlink_ancestors(state_root, project_root)
    _assert_no_symlink_ancestors(events_root, project_root)
    state_files: dict[Path, tuple[bytes, int]] = {}
    event_files: dict[Path, tuple[bytes, int]] = {}
    for path in _iter_scope_entries(state_root):
        if path.name.endswith(".lock") or path.name.endswith(".tmp"):
            continue
        if path.suffix != ".yaml" or path.name not in STATE_NAMES:
            raise MigrationError(f"unknown presentation state store: {path}")
        state_files[path] = _read_regular_file(path)
    for path in _iter_scope_entries(events_root):
        if path.suffix != ".jsonl":
            raise MigrationError(f"unknown presentation event file: {path}")
        event_files[path] = _read_regular_file(path)
    return state_files, event_files


def _restore_mtimes(mtimes: Mapping[Path, int]) -> None:
    """Restore exact pre-transaction mtimes after an in-process rollback."""
    failures: list[str] = []
    for path, modified_ns in sorted(mtimes.items(), key=lambda item: item[0].as_posix()):
        try:
            os.utime(path, ns=(modified_ns, modified_ns), follow_symlinks=False)
        except OSError as exc:
            failures.append(f"{path}: {exc}")
    if failures:
        raise MigrationError("transaction rollback mtime restoration failed: " + "; ".join(failures))


def _dump_state(top_key: str, records: Mapping[str, Any]) -> bytes:
    """Serialize a deterministic target-schema state document."""
    return yaml.safe_dump(
        {"version": STATE_VERSION, top_key: dict(records)},
        sort_keys=True,
        allow_unicode=True,
    ).encode("utf-8")


def migrate_state(project_root: Path | str, dry_run: bool = False) -> dict[str, Any]:
    """Migrate legacy presentation state under ``project_root``.

    Args:
        project_root: Root containing ``.research/presentations``.
        dry_run: Validate and report without creating any directory, lock,
            backup, temporary file, or other filesystem side effect.

    Returns:
        A deterministic report with source/target versions, migrated IDs,
        blocked IDs, blockers, and changed paths.

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
        # Recover a journal left by a process death before parsing.  Otherwise
        # a partially replaced v1/v0 set would be rejected as mixed schema
        # before WorkflowTransaction gets a chance to restore its preimages.
        with WorkflowTransaction([], root):
            pass
    state_files, event_files = _scope_files(root)
    parsed: dict[Path, tuple[int, str, dict[str, Any]]] = {}
    versions: set[int] = set()
    all_ids: set[str] = set()
    for path, (content, _) in sorted(state_files.items(), key=lambda item: item[0].name):
        top_key = STATE_NAMES[path.name]
        document = _parse_yaml(path, content)
        version = _schema_version(path, document)
        records = _records_from_document(path, document, top_key, version)
        _validate_record_paths(root, records)
        if top_key == "decks":
            for record in records.values():
                status = record.get("status")
                if status is not None and status not in DECK_STATUSES:
                    raise StateParseError(f"Invalid deck status {status!r} in {path}")
        for record_id in records:
            if record_id in all_ids:
                raise MigrationError(f"duplicate id {record_id!r} across state stores")
            all_ids.add(record_id)
        parsed[path] = (version, top_key, records)
        versions.add(version)
    if len(versions) > 1:
        raise MigrationError("mixed schema versions across presentation state stores")
    events = _validate_events(root, event_files)
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
        return report

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
            deck_blockers = _safe_plan_evidence(root, deck, plans, events)
            if deck_blockers:
                blockers[deck_id] = deck_blockers
                deck["status"] = "blocked"
    report["blocked_ids"] = sorted(blockers)
    report["blockers"] = {deck_id: blockers[deck_id] for deck_id in sorted(blockers)}
    report["migrated_ids"] = sorted(all_ids - set(blockers))
    if dry_run:
        return report

    preimages: dict[Path, tuple[bytes, int]] = {}
    preimages.update(state_files)
    preimages.update(event_files)
    original_mtimes = {
        path: os.stat(path, follow_symlinks=False).st_mtime_ns for path in preimages
    }
    backup_path = _build_backup(root, preimages)
    transaction_paths = sorted(preimages, key=lambda item: item.as_posix())
    try:
        with WorkflowTransaction(transaction_paths, root) as transaction_handle:
            for path, (version, top_key, records) in sorted(parsed.items(), key=lambda item: item[0].name):
                del version
                transaction_handle.stage_bytes(path, _dump_state(top_key, records))
            for path, (content, mode) in sorted(event_files.items(), key=lambda item: item[0].as_posix()):
                transaction_handle.stage_bytes(path, content, mode=mode)
            transaction_handle.commit()
    except Exception:
        try:
            _restore_mtimes(original_mtimes)
            _remove_backup_tree(backup_path)
        except Exception as cleanup_error:
            raise MigrationError(f"migration failed and backup cleanup failed: {cleanup_error}") from cleanup_error
        raise
    changed_paths = [path.relative_to(root).as_posix() for path in transaction_paths]
    changed_paths.append(backup_path.relative_to(root).as_posix())
    report["changed_paths"] = sorted(changed_paths)
    return report


def _main(argv: list[str] | None = None) -> int:
    """Run the migration CLI and emit JSON on success or failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        report = migrate_state(args.project_root, dry_run=args.dry_run)
    except (MigrationError, StateParseError, OSError, ValueError) as exc:
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
        migration error.
    """
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
