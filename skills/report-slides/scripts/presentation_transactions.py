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
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import yaml


class TransactionError(RuntimeError):
    """Raised when a multi-file commit or rollback cannot complete safely."""


class SimulatedProcessDeath(BaseException):
    """Test-only process-death signal that bypasses in-process rollback."""


class _FileSnapshot:
    """Immutable bytes, existence, and mode captured under a sidecar lock."""

    def __init__(self, exists: bool, content: bytes, mode: int) -> None:
        self.exists = exists
        self.content = content
        self.mode = mode


class _FileStage:
    """One staged replacement and its destination mode."""

    def __init__(self, path: Path, temporary: Path, mode: int) -> None:
        self.path = path
        self.temporary = temporary
        self.mode = mode


def _sidecar(path: Path) -> Path:
    """Return the repository-standard sidecar path for a data file."""
    return path.with_suffix(path.suffix + ".lock")


def _acquire_sidecar(path: Path) -> int:
    """Acquire one exclusive sidecar lock and return its descriptor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _sidecar(path)
    lock_path.touch(exist_ok=True)
    descriptor = os.open(str(lock_path), os.O_RDWR)
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


def _release_sidecar(descriptor: int) -> None:
    """Release one sidecar descriptor."""
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def _directory_fsync(path: Path) -> None:
    """Fsync a parent directory after replacing a file."""
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _temporary_path(path: Path) -> Path:
    """Return a unique same-directory staging path."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return path.with_name(f".{path.name}.transaction.{stamp}.{uuid.uuid4().hex[:8]}.tmp")


def _path_key(path: Path) -> tuple[int, str]:
    """Return the repository-wide lock/write order for one data path."""
    priorities = {
        "workflow.lock": 0, "decks.yaml": 10, "plans.yaml": 20,
        "slides.yaml": 30, "visual_modules.yaml": 40, "assignments.yaml": 50,
        "artifacts.yaml": 60, "revision_requests.yaml": 70,
        ".gitignore": 90,
    }
    priority = priorities.get(path.name, 80 if path.suffix == ".jsonl" else 100)
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


def incomplete_transaction_journals(project_root: Path) -> list[Path]:
    """List incomplete transaction journals without changing state."""
    directory = _journal_dir(project_root)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"), key=lambda path: path.name)


def _journal_path(project_root: Path, transaction_id: str) -> Path:
    """Return the durable journal path for one transaction identifier."""
    return _journal_dir(project_root) / f"{transaction_id}.json"


def _encode_snapshot(path: Path, snapshot: _FileSnapshot) -> dict[str, Any]:
    """Encode one exact preimage for durable recovery."""
    return {
        "path": str(path),
        "exists": snapshot.exists,
        "mode": snapshot.mode,
        "content": base64.b64encode(snapshot.content).decode("ascii"),
    }


def _decode_journal(path: Path) -> tuple[str, list[tuple[Path, _FileSnapshot]]]:
    """Decode one journal and reject malformed recovery metadata."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransactionError(f"invalid transaction journal {path}: {exc}") from exc
    transaction_id = document.get("transaction_id")
    entries = document.get("paths")
    if not isinstance(transaction_id, str) or not transaction_id or not isinstance(entries, list):
        raise TransactionError(f"invalid transaction journal shape: {path}")
    decoded: list[tuple[Path, _FileSnapshot]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise TransactionError(f"invalid transaction journal entry: {path}")
        try:
            content = base64.b64decode(entry.get("content", ""), validate=True)
        except (ValueError, TypeError) as exc:
            raise TransactionError(f"invalid transaction journal bytes: {path}") from exc
        exists = entry.get("exists")
        mode = entry.get("mode")
        if not isinstance(exists, bool) or not isinstance(mode, int) or mode < 0:
            raise TransactionError(f"invalid transaction journal metadata: {path}")
        decoded.append((Path(entry["path"]), _FileSnapshot(exists, content, mode)))
    return transaction_id, decoded


def _write_fsync(path: Path, content: bytes, mode: int) -> None:
    """Write bytes to a fresh path, fsyncing data and parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    _directory_fsync(path.parent)


class WorkflowTransaction:
    """Hold ordered sidecar locks and commit a selected set of files."""

    def __init__(self, paths: Sequence[Path], project_root: Path | None = None) -> None:
        """Create a transaction for selected paths.

        Args:
            paths: Data files this action may replace.
            project_root: Optional root used to locate crash-recovery journals.
        """
        self.paths = tuple(sorted(set(paths), key=_path_key))
        self.project_root = project_root or _infer_project_root(self.paths)
        self._lock_paths: tuple[Path, ...] = self.paths
        self._descriptors: list[int] = []
        self._snapshots: dict[Path, _FileSnapshot] = {}
        self._stages: dict[Path, _FileStage] = {}
        self._journal: Path | None = None
        self._committed = False

    def __enter__(self) -> "WorkflowTransaction":
        """Acquire every sidecar lock and capture bytes before reading state."""
        try:
            journals = self._load_incomplete_journals()
            journal_paths = [path for _, entries in journals for path, _ in entries]
            self._lock_paths = tuple(sorted(set(self.paths) | set(journal_paths), key=_path_key))
            for path in self._lock_paths:
                self._descriptors.append(_acquire_sidecar(path))
            self._recover_journals(journals)
            for path in self.paths:
                if path.is_file():
                    stat_result = path.stat()
                    self._snapshots[path] = _FileSnapshot(True, path.read_bytes(), stat_result.st_mode & 0o777)
                else:
                    self._snapshots[path] = _FileSnapshot(False, b"", 0)
            if self.paths or journals:
                self._notify_locked()
            return self
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
        """Read all pending journals before acquiring any data locks."""
        journals: list[tuple[Path, list[tuple[Path, _FileSnapshot]]]] = []
        for journal in incomplete_transaction_journals(self.project_root):
            _, entries = _decode_journal(journal)
            journals.append((journal, entries))
        return journals

    def _recover_journals(self, journals: Sequence[tuple[Path, list[tuple[Path, _FileSnapshot]]]]) -> None:
        """Restore and remove pending journal preimages under held locks."""
        failures: list[str] = []
        for journal, entries in journals:
            try:
                for path, snapshot in sorted(entries, key=lambda item: _path_key(item[0])):
                    self._restore_snapshot(path, snapshot)
                journal.unlink()
                _directory_fsync(journal.parent)
            except Exception as exc:  # noqa: BLE001 - report every recovery failure
                failures.append(f"{journal}: {exc}")
        if failures:
            raise TransactionError("incomplete transaction recovery failed: " + "; ".join(failures))

    def read_bytes(self, path: Path) -> bytes:
        """Read one locked transaction file, returning empty bytes when absent."""
        self._assert_path(path)
        return path.read_bytes() if path.is_file() else b""

    def read_yaml(self, path: Path, top_key: str) -> dict[str, Any]:
        """Read one locked versioned YAML map without reacquiring its lock."""
        raw = self.read_bytes(path)
        if not raw:
            return {}
        document = yaml.safe_load(raw.decode("utf-8")) or {}
        if not isinstance(document, dict) or document.get("version", 1) != 1:
            raise ValueError(f"Invalid transaction YAML in {path}")
        records = document.get(top_key, {}) or {}
        if not isinstance(records, dict) or any(not isinstance(value, dict) for value in records.values()):
            raise ValueError(f"Invalid {top_key} map in {path}")
        return records

    def stage_bytes(self, path: Path, content: bytes, mode: int | None = None) -> None:
        """Stage bytes for one selected file with fsync and its original mode."""
        self._assert_path(path)
        snapshot = self._snapshots[path]
        target_mode = snapshot.mode if snapshot.exists else 0o666
        temporary = _temporary_path(path)
        try:
            _write_fsync(temporary, content, target_mode)
            if snapshot.exists:
                os.chmod(temporary, target_mode)
        except BaseException:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
        old = self._stages.get(path)
        if old is not None:
            try:
                self._remove_temporary(old.temporary)
            except BaseException:
                self._remove_temporary(temporary)
                raise
        self._stages[path] = _FileStage(path, temporary, target_mode)

    def stage_yaml(self, path: Path, top_key: str, records: Mapping[str, Any]) -> None:
        """Stage a complete versioned YAML map for one selected store."""
        content = yaml.safe_dump(
            {"version": 1, top_key: dict(records)}, sort_keys=True, allow_unicode=True
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
        try:
            self._before_commit()
            self._write_journal(ordered_stages)
            for position, stage in enumerate(ordered_stages, start=1):
                path = stage.path
                self._inject_failure(position, path)
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
        try:
            self._remove_journal()
        except Exception as exc:  # noqa: BLE001 - aggregate journal cleanup failures
            failures.append(f"{self._journal or 'transaction journal'}: {exc}")
        failures.extend(self._cleanup_stages())
        return failures

    def _restore_snapshot(self, path: Path, snapshot: _FileSnapshot) -> None:
        """Restore one preimage exactly, including existence and mode."""
        if not snapshot.exists:
            if path.exists():
                path.unlink()
                _directory_fsync(path.parent)
            return
        temporary = _temporary_path(path)
        _write_fsync(temporary, snapshot.content, snapshot.mode)
        os.chmod(temporary, snapshot.mode)
        os.replace(temporary, path)
        _directory_fsync(path.parent)

    def _write_journal(self, stages: Sequence[_FileStage]) -> None:
        """Persist exact preimages before the first visible replacement."""
        if self._journal is not None:
            return
        transaction_id = uuid.uuid4().hex
        journal = _journal_path(self.project_root, transaction_id)
        document = {
            "transaction_id": transaction_id,
            "paths": [_encode_snapshot(stage.path, self._snapshots[stage.path]) for stage in stages],
        }
        temporary = _temporary_path(journal)
        _write_fsync(temporary, json.dumps(document, sort_keys=True).encode("utf-8"), 0o666)
        os.replace(temporary, journal)
        _directory_fsync(journal.parent)
        self._journal = journal

    def _remove_journal(self) -> None:
        """Delete this transaction journal after durable commit or rollback."""
        if self._journal is None:
            return
        journal = self._journal
        if journal.exists():
            journal.unlink()
            _directory_fsync(journal.parent)
        self._journal = None

    def _cleanup_stages(self) -> list[str]:
        """Remove staged temporary files and aggregate cleanup failures."""
        failures: list[str] = []
        for path in sorted(self._stages, key=_path_key):
            stage = self._stages[path]
            try:
                self._remove_temporary(stage.temporary)
            except Exception as exc:  # noqa: BLE001 - recovery must be explicit
                failures.append(f"{stage.temporary}: {exc}")
        return failures

    @staticmethod
    def _remove_temporary(path: Path) -> None:
        """Remove one temporary path when it still exists."""
        if path.exists():
            path.unlink()

    def _release_locks(self) -> None:
        """Release held descriptors in reverse deterministic order."""
        for descriptor in reversed(self._descriptors):
            _release_sidecar(descriptor)
        self._descriptors.clear()


@contextmanager
def transaction(paths: Sequence[Path], project_root: Path | None = None) -> Iterator[WorkflowTransaction]:
    """Open a selected locked transaction for one workflow action."""
    workflow = WorkflowTransaction(paths, project_root)
    with workflow:
        yield workflow
