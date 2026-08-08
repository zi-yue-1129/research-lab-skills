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
import fcntl
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


class WorkflowTransaction:
    """Hold ordered sidecar locks and commit a selected set of files."""

    def __init__(self, paths: Sequence[Path]) -> None:
        self.paths = tuple(sorted(set(paths), key=lambda path: str(path)))
        self._descriptors: list[int] = []
        self._snapshots: dict[Path, _FileSnapshot] = {}
        self._stages: dict[Path, _FileStage] = {}
        self._committed = False

    def __enter__(self) -> "WorkflowTransaction":
        """Acquire every sidecar lock and capture bytes before reading state."""
        try:
            for path in self.paths:
                self._descriptors.append(_acquire_sidecar(path))
            for path in self.paths:
                if path.is_file():
                    stat_result = path.stat()
                    self._snapshots[path] = _FileSnapshot(True, path.read_bytes(), stat_result.st_mode & 0o777)
                else:
                    self._snapshots[path] = _FileSnapshot(False, b"", 0)
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
        target_mode = snapshot.mode if snapshot.exists else (mode or 0o664)
        temporary = _temporary_path(path)
        try:
            descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, target_mode)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, target_mode)
            _directory_fsync(path.parent)
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
        try:
            for position, path in enumerate(sorted(self._stages), start=1):
                self._inject_failure(position, path)
                stage = self._stages[path]
                os.replace(stage.temporary, path)
                _directory_fsync(path.parent)
            cleanup_failures = self._cleanup_stages()
            if cleanup_failures:
                raise TransactionError("transaction cleanup failed: " + "; ".join(cleanup_failures))
            self._committed = True
        except BaseException as primary:
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

    def _rollback(self) -> list[str]:
        """Restore selected snapshots while all sidecar locks remain held."""
        failures: list[str] = []
        for path in sorted(self._stages):
            snapshot = self._snapshots[path]
            try:
                if snapshot.exists:
                    temporary = _temporary_path(path)
                    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, snapshot.mode)
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(snapshot.content)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.chmod(temporary, snapshot.mode)
                    os.replace(temporary, path)
                    _directory_fsync(path.parent)
                elif path.exists():
                    path.unlink()
                    _directory_fsync(path.parent)
            except Exception as exc:  # noqa: BLE001 - aggregate every recovery error
                failures.append(f"{path}: {exc}")
        failures.extend(self._cleanup_stages())
        return failures

    def _cleanup_stages(self) -> list[str]:
        """Remove staged temporary files and aggregate cleanup failures."""
        failures: list[str] = []
        for stage in tuple(self._stages.values()):
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
def transaction(paths: Sequence[Path]) -> Iterator[WorkflowTransaction]:
    """Open a selected locked transaction for one workflow action."""
    workflow = WorkflowTransaction(paths)
    with workflow:
        yield workflow
