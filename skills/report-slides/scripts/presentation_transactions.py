#!/usr/bin/env python3
"""Locked multi-file transactions for gated presentation workflow actions.

The workflow lock serializes high-level actions, while this module also holds
all affected state/event sidecar locks before reading.  A commit stages every
replacement first, then atomically replaces files in deterministic order.  A
failure restores the captured bytes and modes while those same sidecar locks
remain held, so unrelated low-level writers cannot be lost during rollback.
"""

from __future__ import annotations

import errno
import base64
import fcntl
import json
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import yaml

from presentation_evidence_contracts import EVIDENCE_SCHEMA_VERSION
from presentation_no_follow import (
    AnchoredPath,
    NoFollowPathError,
    acquire_sidecar as acquire_anchored_sidecar,
    fsync_directory as _directory_fsync,
    fsync_regular_file as _file_fsync,
    open_parent_beneath,
    open_parent_no_follow,
    read_regular_siblings,
    read_stable_regular,
    release_sidecar as _release_sidecar,
    restore_regular,
    sidecar_path as _sidecar,
    temporary_path as _temporary_path,
    write_bytes_at,
)


class TransactionError(RuntimeError):
    """Raised when a multi-file commit or rollback cannot complete safely."""


class TransactionRecoveryRequiredError(TransactionError):
    """Raised when a low-level writer runs before a durable journal is recovered."""


MAX_MTIME_NS = 9_223_372_036_854_775_807


class SimulatedProcessDeath(BaseException):
    """Test-only process-death signal that bypasses in-process rollback."""


class _FileSnapshot:
    """Immutable bytes, mode, and optional mtime captured under a sidecar lock."""

    def __init__(self, exists: bool, content: bytes, mode: int, mtime_ns: int | None = None) -> None:
        self.exists = exists
        self.content = content
        self.mode = mode
        self.mtime_ns = mtime_ns


class _FileStage:
    """One staged replacement and its destination mode."""

    def __init__(self, path: Path, temporary: Path, mode: int) -> None:
        self.path = path
        self.temporary = temporary
        self.mode = mode


def _open_sidecar(path: Path) -> int:
    """Open or create a regular sidecar without following symlinks.

    Args:
        path: Data file whose ``.lock`` sidecar should be opened.

    Returns:
        An open descriptor for the sidecar lock file.

    Raises:
        TransactionError: If the sidecar is a symlink or unsafe file type, or
            the platform does not provide ``os.O_NOFOLLOW``.
    """
    lock_path = _sidecar(path)
    if not hasattr(os, "O_NOFOLLOW"):
        raise TransactionError(
            f"sidecar locking requires os.O_NOFOLLOW; refusing unsafe lock: {lock_path}"
        )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = os.lstat(lock_path)
    except FileNotFoundError:
        existing = None
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise TransactionError(f"sidecar lock must be a regular file, not symlink or special type: {lock_path}")
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    try:
        descriptor = os.open(str(lock_path), flags, 0o666)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EISDIR):
            raise TransactionError(f"sidecar lock must be a regular file, not symlink or directory: {lock_path}") from exc
        raise
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise TransactionError(f"sidecar lock must be a regular file, not special type: {lock_path}")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _acquire_sidecar(path: Path) -> int:
    """Acquire one exclusive sidecar lock and return its descriptor."""
    descriptor = _open_sidecar(path)
    timeout = int(os.environ.get("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS", "30"))
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return descriptor
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise TransactionError(f"Could not acquire sidecar lock {_sidecar(path)} within {timeout}s")
                time.sleep(0.05)
    except BaseException:
        os.close(descriptor)
        raise


def _path_key(path: Path) -> tuple[int, str]:
    """Return the repository-wide lock/write order for one data path."""
    priorities = {
        "workflow.lock": 0, "decks.yaml": 10, "plans.yaml": 20,
        "slides.yaml": 30, "visual_modules.yaml": 40, "assignments.yaml": 50,
        "artifacts.yaml": 60, "revision_requests.yaml": 70,
        ".gitignore": 90,
    }
    cas_parts = path.parts
    is_cas_object = len(cas_parts) >= 6 and cas_parts[-6:-2] == (
        ".research", "presentations", "evidence", "sha256"
    )
    priority = priorities.get(path.name, 85 if is_cas_object else 80 if path.suffix == ".jsonl" else 100)
    return priority, str(path)


def _infer_project_root(paths: Sequence[Path]) -> Path:
    """Infer a project root for direct transaction tests without one supplied."""
    for path in paths:
        for ancestor in path.parents:
            if ancestor.name == ".research":
                return ancestor.parent
    common = Path(os.path.commonpath([str(path.parent) for path in paths]))
    return common.parent if common.name == "state" else common


def _journal_dir(project_root: Path) -> Path:
    """Return the durable incomplete-transaction journal directory."""
    return project_root / ".research/presentations/transactions"


_ALLOWED_STATE_NAMES = frozenset({
    "decks.yaml", "plans.yaml", "slides.yaml", "visual_modules.yaml", "assignments.yaml",
    "artifacts.yaml", "revision_requests.yaml", "evidence.yaml",
})
_EVENT_SHARD_PATTERN = re.compile(r"\.research/presentations/events/(\d{4}-\d{2}-\d{2})\.jsonl")
_PLAN_DESTINATION_PATTERN = re.compile(r"decks/[^/]+/plans/plan-v\d{4}\.yaml")
_CAS_DESTINATION_PATTERN = re.compile(
    r"\.research/presentations/evidence/sha256/([0-9a-f]{2})/([0-9a-f]{64})"
)
_JOURNAL_FILENAME_PATTERN = re.compile(r"[0-9a-f]{32}\.json")


def _validate_mode(mode: object, source: Path) -> int:
    """Validate and return ordinary Unix permission bits from journal metadata."""
    if isinstance(mode, bool) or not isinstance(mode, int) or mode < 0 or mode & ~0o777:
        raise TransactionError(f"invalid journal mode for {source}: {mode!r}")
    return mode


def _canonical_journal_relative_path(raw_path: object) -> str:
    """Validate the lexical form of one project-relative journal path."""
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        raise TransactionError(f"journal path must be a non-empty relative path: {raw_path!r}")
    if raw_path.startswith("/") or "\\" in raw_path:
        raise TransactionError(f"journal path must be project-relative and POSIX-normalized: {raw_path!r}")
    parts = raw_path.split("/")
    if any(part in {"", ".", ".."} for part in parts) or "/".join(parts) != raw_path:
        raise TransactionError(f"journal path is not normalized: {raw_path!r}")
    return raw_path


def _validate_journal_target(project_root: Path, raw_path: object) -> Path:
    """Validate an allowlisted state, event, plan, or CAS target."""
    relative = _canonical_journal_relative_path(raw_path)
    state_prefix = ".research/presentations/state/"
    cas_match = _CAS_DESTINATION_PATTERN.fullmatch(relative)
    if relative.startswith(state_prefix):
        name = relative[len(state_prefix):]
        if name not in _ALLOWED_STATE_NAMES:
            raise TransactionError(f"journal path is not an allowed state store: {relative}")
    elif _PLAN_DESTINATION_PATTERN.fullmatch(relative):
        pass
    elif cas_match is not None:
        shard, digest = cas_match.groups()
        if shard != digest[:2]:
            raise TransactionError(f"journal CAS path shard does not match digest: {relative}")
    else:
        match = _EVENT_SHARD_PATTERN.fullmatch(relative)
        if match is None:
            raise TransactionError(f"journal path is not an allowed event shard: {relative}")
        try:
            datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError as exc:
            raise TransactionError(f"journal event shard has invalid date: {relative}") from exc
    root = project_root.resolve()
    candidate = root / relative
    if cas_match is not None:
        return candidate
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise TransactionError(f"journal path escapes project root: {relative}") from exc
    if candidate.exists() and candidate.is_dir():
        raise TransactionError(f"journal path must name a file: {relative}")
    return candidate


def _project_relative_path(project_root: Path, path: Path) -> str:
    """Return a canonical lexical path relative to a project root."""
    root = project_root.resolve()
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise TransactionError(f"transaction path escapes project root: {path}") from exc
    _validate_journal_target(root, relative)
    return relative


def _is_cas_transaction_path(project_root: Path, path: Path) -> bool:
    """Return whether one lexical transaction path is a canonical CAS object."""
    try:
        relative = path.relative_to(project_root).as_posix()
    except ValueError:
        return False
    return _CAS_DESTINATION_PATTERN.fullmatch(relative) is not None


def _validate_journal_filename(path: Path) -> None:
    """Reject journal names that do not use the generated transaction ID form."""
    if _JOURNAL_FILENAME_PATTERN.fullmatch(path.name) is None:
        raise TransactionError(
            "transaction journal filename must be 32 lowercase hexadecimal characters plus .json: "
            f"{path}"
        )


def incomplete_transaction_journals(project_root: Path) -> list[Path]:
    """List incomplete transaction journals without changing state."""
    directory = _journal_dir(project_root)
    if directory.is_symlink():
        raise TransactionError(f"transaction journal directory must not be a symlink: {directory}")
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise TransactionError(f"transaction journal path must be a directory: {directory}")
    journals: list[Path] = []
    for child in sorted(directory.iterdir(), key=lambda path: path.name):
        _validate_journal_filename(child)
        if child.is_symlink() or not child.is_file():
            raise TransactionError(f"transaction journal must be a regular file: {child}")
        journals.append(child)
    return journals


def require_transaction_recovery(project_root: Path) -> None:
    """Validate journals and raise before a low-level mutation if any remain."""
    journals = _load_validated_journals(project_root)
    if journals:
        names = ", ".join(str(path) for path in journals)
        raise TransactionRecoveryRequiredError(f"transaction recovery required before write: {names}")


def _journal_path(project_root: Path, transaction_id: str) -> Path:
    """Return the durable journal path for one transaction identifier."""
    return _journal_dir(project_root) / f"{transaction_id}.json"


def _encode_snapshot(project_root: Path, path: Path, snapshot: _FileSnapshot) -> dict[str, Any]:
    """Encode one exact preimage for durable recovery."""
    encoded = {
        "path": _project_relative_path(project_root, path),
        "exists": snapshot.exists,
        "mode": snapshot.mode,
        "content": base64.b64encode(snapshot.content).decode("ascii"),
    }
    if snapshot.mtime_ns is not None:
        encoded["mtime_ns"] = snapshot.mtime_ns
    return encoded


def _decode_journal(
    project_root: Path,
    path: Path,
    raw_content: bytes | None = None,
) -> tuple[str, list[tuple[Path, _FileSnapshot]]]:
    """Decode one journal and reject malformed recovery metadata."""
    try:
        text = path.read_text(encoding="utf-8") if raw_content is None else raw_content.decode("utf-8")
        document = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransactionError(f"invalid transaction journal {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise TransactionError(f"invalid transaction journal shape: {path}")
    transaction_id = document.get("transaction_id")
    entries = document.get("paths")
    if not isinstance(transaction_id, str) or not transaction_id or not isinstance(entries, list):
        raise TransactionError(f"invalid transaction journal shape: {path}")
    if not entries:
        raise TransactionError(f"invalid transaction journal entries: {path}")
    decoded: list[tuple[Path, _FileSnapshot]] = []
    seen_paths: set[Path] = set()
    for entry in entries:
        required_fields = {"path", "exists", "mode", "content"}
        if not isinstance(entry, dict) or not required_fields.issubset(entry):
            raise TransactionError(f"invalid transaction journal entry: {path}")
        if not isinstance(entry["path"], str):
            raise TransactionError(f"invalid transaction journal entry: {path}")
        target = _validate_journal_target(project_root, entry["path"])
        if target in seen_paths:
            raise TransactionError(f"duplicate transaction journal path: {path}")
        seen_paths.add(target)
        try:
            encoded_content = entry["content"]
            if not isinstance(encoded_content, str):
                raise TypeError("content must be base64 text")
            content = base64.b64decode(encoded_content, validate=True)
        except (ValueError, TypeError) as exc:
            raise TransactionError(f"invalid transaction journal bytes: {path}") from exc
        exists = entry.get("exists")
        mode = entry.get("mode")
        if not isinstance(exists, bool):
            raise TransactionError(f"invalid transaction journal metadata: {path}")
        if "mtime_ns" in entry:
            mtime_ns = entry["mtime_ns"]
            if (
                mtime_ns is None
                or isinstance(mtime_ns, bool)
                or not isinstance(mtime_ns, int)
                or mtime_ns < 0
                or mtime_ns > MAX_MTIME_NS
            ):
                raise TransactionError(f"invalid transaction journal mtime metadata: {path}")
        else:
            # Journals written before mtime support intentionally omit this
            # field; recovery must preserve that legacy behavior.
            mtime_ns = None
        validated_mode = _validate_mode(mode, path)
        if not exists and (content or validated_mode != 0 or "mtime_ns" in entry):
            raise TransactionError(
                f"non-existent transaction snapshot carries metadata: {path}"
            )
        decoded.append((target, _FileSnapshot(exists, content, validated_mode, mtime_ns)))
    return transaction_id, decoded


def _load_validated_journals(
    project_root: Path,
    anchored_documents: Mapping[str, bytes] | None = None,
) -> list[tuple[Path, list[tuple[Path, _FileSnapshot]]]]:
    """Read and validate every pending journal before data locking.

    Args:
        project_root: Project root containing the presentation stores.

    Returns:
        Journal paths paired with their exact decoded preimages.

    Raises:
        TransactionError: If any journal path, file, or payload is unsafe.
    """
    journals: list[tuple[Path, list[tuple[Path, _FileSnapshot]]]] = []
    journal_directory = _journal_dir(project_root)
    journal_names = (
        [journal.name for journal in incomplete_transaction_journals(project_root)]
        if anchored_documents is None
        else sorted(anchored_documents)
    )
    for journal_name in journal_names:
        journal = journal_directory / journal_name
        _validate_journal_filename(journal)
        if journal.parent != journal_directory:
            raise TransactionError(f"transaction journal is outside its directory: {journal}")
        if anchored_documents is None:
            try:
                journal.resolve(strict=True).relative_to(journal_directory.resolve())
            except (OSError, ValueError) as exc:
                raise TransactionError(f"transaction journal escapes its directory: {journal}") from exc
        transaction_id, entries = _decode_journal(
            project_root,
            journal,
            None if anchored_documents is None else anchored_documents[journal_name],
        )
        if transaction_id != journal.stem:
            raise TransactionError(
                f"transaction journal transaction_id does not match filename stem: {journal}"
            )
        journals.append((journal, entries))
    return journals


def _write_fsync(
    path: Path,
    content: bytes,
    mode: int,
    *,
    exact_mode: bool = False,
) -> None:
    """Write bytes to a fresh path, fsyncing data and parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError(f"short write while staging {path}")
            offset += written
        applied_mode = mode if exact_mode else os.fstat(descriptor).st_mode & 0o777
        os.fchmod(descriptor, applied_mode)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            path.unlink()
        except OSError:
            pass
        raise
    os.close(descriptor)
    _directory_fsync(path.parent)


class WorkflowTransaction:
    """Hold ordered sidecar locks and commit a selected set of files."""

    def __init__(self, paths: Sequence[Path], project_root: Path | None = None) -> None:
        """Create a transaction for selected paths.

        Args:
            paths: Data files this action may replace.
            project_root: Optional root used to locate crash-recovery journals.
        """
        self.project_root = (project_root or _infer_project_root(paths)).resolve()
        selected_paths: set[Path] = set()
        for raw_path in paths:
            supplied = Path(raw_path)
            candidate = supplied if supplied.is_absolute() else self.project_root / supplied
            _project_relative_path(self.project_root, candidate)
            if _is_cas_transaction_path(self.project_root, candidate):
                selected_paths.add(candidate)
            else:
                selected_paths.add(candidate.resolve())
        self.paths = tuple(sorted(selected_paths, key=_path_key))
        for path in self.paths:
            _project_relative_path(self.project_root, path)
        self._lock_paths: tuple[Path, ...] = self.paths
        self._descriptors: list[int] = []
        self._snapshots: dict[Path, _FileSnapshot] = {}
        self._stages: dict[Path, _FileStage] = {}
        self._unsafe_cas_paths: set[Path] = set()
        self._cas_anchors: dict[Path, AnchoredPath] = {}
        self._recovery_anchors: dict[Path, AnchoredPath] = {}
        self._root_anchor: AnchoredPath | None = None
        self._presentations_anchor: AnchoredPath | None = None
        self._journal_anchor: AnchoredPath | None = None
        self._journal: Path | None = None
        self._committed = False

    def __enter__(self) -> "WorkflowTransaction":
        """Acquire every sidecar lock and capture bytes before reading state."""
        try:
            self._root_anchor = open_parent_no_follow(
                self.project_root,
                ".transaction-root-anchor",
                create_parents=False,
            )
            self._presentations_anchor = open_parent_beneath(
                self._root_anchor,
                ".research/presentations/.presentations-anchor",
                create_parents=True,
            )
            self._journal_anchor = open_parent_beneath(
                self._presentations_anchor,
                "transactions/.journal-anchor",
                create_parents=True,
            )
            journals = self._load_incomplete_journals()
            journal_paths = [path for _, entries in journals for path, _ in entries]
            self._lock_paths = tuple(sorted(set(self.paths) | set(journal_paths), key=_path_key))
            for path in journal_paths:
                anchored = self._anchor_recovery_path(path)
                if _is_cas_transaction_path(self.project_root, path):
                    self._cas_anchors[path] = anchored
                else:
                    self._recovery_anchors[path] = anchored
            for path in self._lock_paths:
                if _is_cas_transaction_path(self.project_root, path):
                    anchored = self._cas_anchors.get(path)
                    if anchored is None:
                        anchored = self._anchor_recovery_path(path)
                        self._cas_anchors[path] = anchored
                    timeout = int(
                        os.environ.get("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS", "30")
                    )
                    self._descriptors.append(acquire_anchored_sidecar(anchored, timeout))
                elif path in self._recovery_anchors:
                    timeout = int(
                        os.environ.get("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS", "30")
                    )
                    self._descriptors.append(acquire_anchored_sidecar(self._recovery_anchors[path], timeout))
                else:
                    self._descriptors.append(_acquire_sidecar(path))
            self._recover_journals(journals)
            for path in self.paths:
                if _is_cas_transaction_path(self.project_root, path):
                    self._snapshots[path] = self._capture_cas_snapshot(path)
                elif path.is_file():
                    stat_result = path.stat()
                    self._snapshots[path] = _FileSnapshot(
                        True, path.read_bytes(), stat_result.st_mode & 0o777, stat_result.st_mtime_ns
                    )
                else:
                    self._snapshots[path] = _FileSnapshot(False, b"", 0)
            if self.paths or journals:
                self._notify_locked()
            return self
        except NoFollowPathError as exc:
            self._release_locks()
            raise TransactionError(f"unsafe no-follow transaction path: {exc}") from exc
        except BaseException:
            self._release_locks()
            raise

    def __exit__(self, error_type: Any, error: BaseException | None, traceback: Any) -> None:
        """Clean staged files and release sidecar locks in reverse order."""
        cleanup_failures: list[str] = []
        if not self._committed:
            cleanup_failures = self._cleanup_stages()
        self._release_locks()
        if cleanup_failures:
            detail = "; ".join(cleanup_failures)
            if error is not None:
                raise TransactionError(f"{error}; rollback_cleanup_failed: {detail}") from error
            raise TransactionError(f"rollback_cleanup_failed: {detail}")

    def _load_incomplete_journals(self) -> list[tuple[Path, list[tuple[Path, _FileSnapshot]]]]:
        """Read pending journals through the retained journal directory."""
        if self._journal_anchor is None:
            raise TransactionError("journal directory must be anchored before loading")
        documents = read_regular_siblings(self._journal_anchor)
        return _load_validated_journals(self.project_root, documents)

    def _anchor_recovery_path(self, path: Path) -> AnchoredPath:
        """Anchor a recovery target beneath the retained project hierarchy."""
        relative = path.relative_to(self.project_root).as_posix()
        prefix = ".research/presentations/"
        if relative.startswith(prefix):
            if self._presentations_anchor is None:
                raise TransactionError("presentations directory is not anchored")
            return open_parent_beneath(
                self._presentations_anchor,
                relative[len(prefix):],
                create_parents=True,
            )
        if self._root_anchor is None:
            raise TransactionError("project directory is not anchored")
        return open_parent_beneath(
            self._root_anchor,
            relative,
            create_parents=True,
        )

    def _recover_journals(self, journals: Sequence[tuple[Path, list[tuple[Path, _FileSnapshot]]]]) -> None:
        """Restore and remove pending journal preimages under held locks."""
        failures: list[str] = []
        for journal, entries in journals:
            try:
                for path, snapshot in sorted(entries, key=lambda item: _path_key(item[0])):
                    anchored = self._cas_anchors.get(path) or self._recovery_anchors[path]
                    self._restore_anchored_snapshot(path, snapshot, anchored)
                if self._journal_anchor is not None:
                    os.unlink(journal.name, dir_fd=self._journal_anchor.parent_fd)
                    self._journal_anchor.fsync_parent()
                else:
                    journal.unlink()
                    _directory_fsync(journal.parent)
            except Exception as exc:  # noqa: BLE001 - report every recovery failure
                failures.append(f"{journal}: {exc}")
        if failures:
            raise TransactionError("incomplete transaction recovery failed: " + "; ".join(failures))

    def read_bytes(self, path: Path) -> bytes:
        """Read one locked transaction file, returning empty bytes when absent."""
        self._assert_path(path)
        if _is_cas_transaction_path(self.project_root, path):
            return self._snapshots[path].content
        return path.read_bytes() if path.is_file() else b""

    def snapshot(self, path: Path) -> tuple[bytes, int, int | None]:
        """Return the exact preimage captured while this transaction held locks.

        Args:
            path: Selected transaction target.

        Returns:
            A tuple of exact bytes, permission bits, and optional nanosecond
            mtime.  The returned values are immutable preimages, not a fresh
            unlocked filesystem read.
        """
        self._assert_path(path)
        snapshot = self._snapshots[path]
        return snapshot.content, snapshot.mode, snapshot.mtime_ns

    def cas_snapshot(self, path: Path) -> tuple[bool, bytes]:
        """Return existence and anchored bytes for one selected CAS target.

        Args:
            path: Selected canonical CAS object path.

        Returns:
            A pair containing exact preimage existence and content bytes.

        Raises:
            TransactionError: If the selected CAS leaf is unsafe.
            ValueError: If ``path`` is unselected or not a canonical CAS path.
        """
        self._assert_path(path)
        if not _is_cas_transaction_path(self.project_root, path):
            raise ValueError(f"Path is not a CAS transaction target: {path}")
        if path in self._unsafe_cas_paths:
            raise TransactionError(f"unsafe CAS target cannot be read: {path}")
        snapshot = self._snapshots[path]
        return snapshot.exists, snapshot.content

    def read_yaml(self, path: Path, top_key: str) -> dict[str, Any]:
        """Read one locked versioned YAML map without reacquiring its lock."""
        raw = self.read_bytes(path)
        if not raw:
            return {}
        document = yaml.safe_load(raw.decode("utf-8")) or {}
        version = document.get("version", 1) if isinstance(document, dict) else None
        if type(version) is not int or version != EVIDENCE_SCHEMA_VERSION:
            raise ValueError(f"Invalid transaction YAML in {path}")
        records = document.get(top_key, {}) or {}
        if not isinstance(records, dict) or any(not isinstance(value, dict) for value in records.values()):
            raise ValueError(f"Invalid {top_key} map in {path}")
        return records

    def stage_bytes(self, path: Path, content: bytes, mode: int | None = None) -> None:
        """Stage bytes for one selected file with fsync and its original mode."""
        self._assert_path(path)
        if path in self._unsafe_cas_paths:
            raise TransactionError(f"unsafe CAS target cannot be staged: {path}")
        snapshot = self._snapshots[path]
        target_mode = _validate_mode(mode, path) if mode is not None else (snapshot.mode if snapshot.exists else 0o666)
        temporary = _temporary_path(path)
        try:
            if _is_cas_transaction_path(self.project_root, path):
                write_bytes_at(
                    self._cas_anchors[path],
                    temporary.name,
                    content,
                    target_mode,
                    exact_mode=True,
                )
            else:
                _write_fsync(
                    temporary,
                    content,
                    target_mode,
                    exact_mode=mode is not None or snapshot.exists,
                )
        except BaseException:
            self._remove_temporary_for_path(path, temporary)
            raise
        old = self._stages.get(path)
        if old is not None:
            try:
                self._remove_temporary_for_path(path, old.temporary)
            except BaseException:
                self._remove_temporary_for_path(path, temporary)
                raise
        self._stages[path] = _FileStage(path, temporary, target_mode)

    def stage_yaml(self, path: Path, top_key: str, records: Mapping[str, Any]) -> None:
        """Stage a complete versioned YAML map for one selected store."""
        content = yaml.safe_dump(
            {"version": EVIDENCE_SCHEMA_VERSION, top_key: dict(records)},
            sort_keys=True,
            allow_unicode=True,
        ).encode("utf-8")
        self.stage_bytes(path, content)

    def stage_append(self, path: Path, line: bytes) -> None:
        """Stage one append-only JSONL shard with a trailing newline."""
        previous = self.read_bytes(path)
        self.stage_bytes(path, previous + line + b"\n")

    def commit(self) -> None:
        """Atomically replace staged files and restore all files on failure."""
        if self._committed:
            raise TransactionError("transaction already committed")
        ordered_stages = [self._stages[path] for path in sorted(self._stages, key=_path_key)]
        if not ordered_stages:
            self._committed = True
            return
        try:
            self._before_commit()
            self._write_journal(ordered_stages)
            for position, stage in enumerate(ordered_stages, start=1):
                path = stage.path
                self._inject_failure(position, path)
                if _is_cas_transaction_path(self.project_root, path):
                    anchored = self._cas_anchors[path]
                    anchored.replace_leaf(stage.temporary.name)
                    anchored.fsync_parent()
                else:
                    os.replace(stage.temporary, path)
                    _directory_fsync(path.parent)
                self._inject_process_death(position, path)
            self._remove_journal()
            cleanup_failures = self._cleanup_stages()
            if cleanup_failures:
                raise TransactionError("transaction cleanup failed: " + "; ".join(cleanup_failures))
            self._committed = True
        except Exception as primary:
            rollback_failures = self._rollback()
            detail = "; ".join(rollback_failures)
            if detail:
                raise TransactionError(f"transaction commit failed: {primary}; rollback_failed: {detail}") from primary
            raise RuntimeError(f"transaction commit failed: {primary}") from primary

    def _assert_path(self, path: Path) -> None:
        """Reject unselected files before reading or staging them."""
        if path not in self._snapshots:
            raise ValueError(f"Path is outside transaction: {path}")

    def _capture_cas_snapshot(self, path: Path) -> _FileSnapshot:
        """Capture a CAS preimage without following an unsafe object symlink."""
        anchored = self._cas_anchors[path]
        metadata = anchored.stat_leaf()
        if metadata is None:
            return _FileSnapshot(False, b"", 0)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            self._unsafe_cas_paths.add(path)
            return _FileSnapshot(False, b"", 0)
        try:
            content, opened = read_stable_regular(anchored)
        except NoFollowPathError as exc:
            raise TransactionError(
                f"CAS object changed while capturing preimage: {path}"
            ) from exc
        return _FileSnapshot(True, content, opened.st_mode & 0o777, opened.st_mtime_ns)

    def _notify_locked(self) -> None:
        """Provide a deterministic test hook after all locks are held."""

    def _before_commit(self) -> None:
        """Provide a deterministic test hook immediately before journaling."""

    def _inject_failure(self, position: int, path: Path) -> None:
        """Apply deterministic test failure injection at one commit position."""
        raw = os.environ.get("PRESENTATION_TRANSACTION_FAIL_AT")
        if raw is None:
            return
        try:
            requested = int(raw)
        except ValueError as exc:
            raise ValueError("PRESENTATION_TRANSACTION_FAIL_AT must be an integer") from exc
        if requested == position:
            raise OSError(f"injected transaction commit failure at position {position}: {path}")

    def _inject_process_death(self, position: int, path: Path) -> None:
        """Raise a BaseException after a selected visible replacement."""
        raw = os.environ.get("PRESENTATION_TRANSACTION_CRASH_AT")
        if raw is None:
            return
        try:
            requested = int(raw)
        except ValueError as exc:
            raise ValueError("PRESENTATION_TRANSACTION_CRASH_AT must be an integer") from exc
        if requested == position:
            raise SimulatedProcessDeath(f"simulated process death after position {position}: {path}")

    def _rollback(self) -> list[str]:
        """Restore selected snapshots while all sidecar locks remain held."""
        failures: list[str] = []
        for path in sorted(self._stages, key=_path_key):
            try:
                self._restore_snapshot(path, self._snapshots[path])
            except Exception as exc:  # noqa: BLE001 - aggregate every recovery error
                failures.append(f"{path}: {exc}")
        if not failures:
            try:
                self._remove_journal()
            except Exception as exc:  # noqa: BLE001 - aggregate journal cleanup failures
                failures.append(f"{self._journal or 'transaction journal'}: {exc}")
        failures.extend(self._cleanup_stages())
        return failures

    def _restore_snapshot(self, path: Path, snapshot: _FileSnapshot) -> None:
        """Restore one preimage exactly, including existence and mode."""
        if _is_cas_transaction_path(self.project_root, path):
            self._restore_anchored_snapshot(path, snapshot, self._cas_anchors[path])
            return
        if not snapshot.exists:
            if path.exists():
                path.unlink()
                _directory_fsync(path.parent)
            return
        temporary = _temporary_path(path)
        try:
            _write_fsync(
                temporary,
                snapshot.content,
                snapshot.mode,
                exact_mode=True,
            )
            os.replace(temporary, path)
        except BaseException:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
            raise
        _directory_fsync(path.parent)
        if snapshot.mtime_ns is not None:
            os.utime(path, ns=(snapshot.mtime_ns, snapshot.mtime_ns), follow_symlinks=False)
            _file_fsync(path)
            _directory_fsync(path.parent)

    def _restore_anchored_snapshot(
        self,
        path: Path,
        snapshot: _FileSnapshot,
        anchored: AnchoredPath,
    ) -> None:
        """Restore one preimage through the retained parent descriptor."""
        try:
            restore_regular(
                anchored,
                _temporary_path(path).name,
                exists=snapshot.exists,
                content=snapshot.content,
                mode=snapshot.mode,
                mtime_ns=snapshot.mtime_ns,
            )
        except NoFollowPathError as exc:
            target_kind = (
                "CAS recovery target"
                if _is_cas_transaction_path(self.project_root, path)
                else "recovery target"
            )
            raise TransactionError(
                f"{target_kind} must be a regular no-follow file: {path}"
            ) from exc

    def _write_journal(self, stages: Sequence[_FileStage]) -> None:
        """Persist exact preimages before the first visible replacement."""
        if self._journal is not None:
            return
        transaction_id = uuid.uuid4().hex
        journal = _journal_path(self.project_root, transaction_id)
        document = {
            "transaction_id": transaction_id,
            "paths": [
                _encode_snapshot(self.project_root, stage.path, self._snapshots[stage.path])
                for stage in stages
            ],
        }
        temporary = _temporary_path(journal)
        content = json.dumps(document, sort_keys=True).encode("utf-8")
        if self._journal_anchor is not None:
            write_bytes_at(
                self._journal_anchor,
                temporary.name,
                content,
                0o666,
                exact_mode=False,
            )
            os.replace(
                temporary.name,
                journal.name,
                src_dir_fd=self._journal_anchor.parent_fd,
                dst_dir_fd=self._journal_anchor.parent_fd,
            )
            self._journal_anchor.fsync_parent()
        else:
            _write_fsync(temporary, content, 0o666)
            os.replace(temporary, journal)
            _directory_fsync(journal.parent)
        self._journal = journal

    def _remove_journal(self) -> None:
        """Delete this transaction journal after durable commit or rollback."""
        if self._journal is None:
            return
        journal = self._journal
        if self._journal_anchor is not None:
            try:
                os.stat(
                    journal.name,
                    dir_fd=self._journal_anchor.parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                os.unlink(journal.name, dir_fd=self._journal_anchor.parent_fd)
                self._journal_anchor.fsync_parent()
        elif journal.exists():
            journal.unlink()
            _directory_fsync(journal.parent)
        self._journal = None

    def _cleanup_stages(self) -> list[str]:
        """Remove staged temporary files and aggregate cleanup failures."""
        failures: list[str] = []
        for path in sorted(self._stages, key=_path_key):
            stage = self._stages[path]
            try:
                self._remove_temporary_for_path(path, stage.temporary)
            except Exception as exc:  # noqa: BLE001 - recovery must be explicit
                failures.append(f"{stage.temporary}: {exc}")
        return failures

    def _remove_temporary_for_path(self, target: Path, temporary: Path) -> None:
        """Remove one staged sibling through its target's retained directory."""
        if _is_cas_transaction_path(self.project_root, target):
            anchored = self._cas_anchors[target]
            try:
                os.stat(
                    temporary.name,
                    dir_fd=anchored.parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return
            os.unlink(temporary.name, dir_fd=anchored.parent_fd)
        elif temporary.exists():
            temporary.unlink()

    def _release_locks(self) -> None:
        """Release held descriptors in reverse deterministic order."""
        for descriptor in reversed(self._descriptors):
            _release_sidecar(descriptor)
        self._descriptors.clear()
        for anchored in self._cas_anchors.values():
            anchored.close()
        self._cas_anchors.clear()
        for anchored in self._recovery_anchors.values():
            anchored.close()
        self._recovery_anchors.clear()
        if self._journal_anchor is not None:
            self._journal_anchor.close()
            self._journal_anchor = None
        if self._presentations_anchor is not None:
            self._presentations_anchor.close()
            self._presentations_anchor = None
        if self._root_anchor is not None:
            self._root_anchor.close()
            self._root_anchor = None


@contextmanager
def transaction(paths: Sequence[Path], project_root: Path | None = None) -> Iterator[WorkflowTransaction]:
    """Open a selected locked transaction for one workflow action."""
    workflow = WorkflowTransaction(paths, project_root)
    with workflow:
        yield workflow
