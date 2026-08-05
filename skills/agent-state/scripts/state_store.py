#!/usr/bin/env python3
"""state_store.py -- Canonical Question/Run state and Result/Claim event log.

Backs the four cross-skill entities (Question, Run, Result, Claim) described
in docs/superpowers/specs/2026-08-05-agent-state-storage-design.md. Question
and Run are low-frequency, mutable records held in id-keyed YAML maps under
.research/state/. Result and Claim are immutable facts appended to daily
JSONL shards under .research/events/ -- the JSONL line itself is the record,
there is no separate canonical copy.
"""
import errno
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator

try:
    import yaml
except ImportError:
    import sys
    print("Error: PyYAML required. Run: pip install pyyaml", file=sys.stderr)
    raise SystemExit(1)


QUESTIONS_RELATIVE_PATH = Path(".research/state/questions.yaml")
RUNS_RELATIVE_PATH = Path(".research/state/runs.yaml")
EVENTS_RELATIVE_DIR = Path(".research/events")
LOCK_TIMEOUT_SECONDS = int(os.environ.get("AGENT_STATE_LOCK_TIMEOUT_SECONDS", "30"))
LOCK_POLL_INTERVAL_SECONDS = 0.1
_CLOSING_RUN_STATUSES = frozenset({"completed", "failed"})
_QUESTION_STATUSES = frozenset({"answered", "abandoned"})


class ProjectRootNotFoundError(RuntimeError):
    """Raised when no ancestor directory containing a .git entry can be found."""


class StateParseError(ValueError):
    """Raised when a state/*.yaml file exists but cannot be parsed as valid YAML."""


class QuestionNotFoundError(ValueError):
    """Raised when a question_id does not exist in state/questions.yaml."""


class RunNotFoundError(ValueError):
    """Raised when a run_id does not exist in state/runs.yaml."""


class LockTimeoutError(RuntimeError):
    """Raised when an exclusive lock can't be acquired, or isn't available at all."""


def find_project_root(start: Path) -> Path:
    """Find the nearest ancestor directory containing a .git entry.

    Args:
        start: Directory to begin the upward search from.

    Returns:
        The absolute path of the first directory (start or an ancestor)
        that contains a .git file or directory.

    Raises:
        ProjectRootNotFoundError: If no ancestor up to the filesystem root
            contains a .git entry.
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise ProjectRootNotFoundError(
        f"No .git found in {start} or any parent directory."
    )


def generate_id(prefix: str) -> str:
    """Generate a sortable, human-scannable record id.

    Args:
        prefix: Short entity tag, e.g. "q", "run", "res", "clm".

    Returns:
        An id of the form "<prefix>_<UTC-date>_<6-hex-chars>", e.g.
        "run_20260805_9f3a1c". The date groups ids visually by day; the hex
        suffix disambiguates ids created on the same day.
    """
    now = datetime.now(timezone.utc)
    return f"{prefix}_{now:%Y%m%d}_{uuid.uuid4().hex[:6]}"


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a Z suffix.

    Returns:
        A string like "2026-08-05T09:12:03Z".
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@contextmanager
def _locked_file(path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on `path` for the duration of the block.

    POSIX: fcntl.flock(LOCK_EX | LOCK_NB), retried on a short poll interval
    up to LOCK_TIMEOUT_SECONDS. Non-POSIX (no fcntl module, e.g. Windows)
    fails loudly with LockTimeoutError rather than silently proceeding
    unprotected -- mirrors the "Non-POSIX (Windows)" rule in
    skills/academic-pipeline/references/passport_as_reset_boundary.md.

    Args:
        path: The file to lock. Created (empty) if it doesn't exist yet, so
            the lock has something to hold onto even before the real
            content is first written.

    Yields:
        None. The caller does its read-modify-write inside the `with` block.

    Raises:
        LockTimeoutError: If the lock isn't acquired within
            LOCK_TIMEOUT_SECONDS, or if OS-level exclusion isn't available
            on this platform.
    """
    try:
        import fcntl as _fcntl
    except ImportError as exc:
        raise LockTimeoutError(
            "Concurrency protection unavailable on this platform: the "
            f"fcntl module is POSIX-only. Refusing to write {path} "
            "without an exclusive lock."
        ) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    fd = os.open(str(path), os.O_RDWR)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    try:
        while True:
            try:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"Timed out after {LOCK_TIMEOUT_SECONDS}s waiting "
                        f"for an exclusive lock on {path}."
                    ) from exc
                time.sleep(LOCK_POLL_INTERVAL_SECONDS)
        yield
    finally:
        _fcntl.flock(fd, _fcntl.LOCK_UN)
        os.close(fd)


def _load_yaml_map(path: Path, entity_name: str) -> Dict[str, Any]:
    """Load a YAML file as a dict, returning empty dict if file doesn't exist.

    Args:
        path: Path to the YAML file.
        entity_name: Descriptive name for error messages (e.g. "questions").

    Returns:
        The parsed YAML dict, or an empty dict if the file doesn't exist.

    Raises:
        StateParseError: If the file exists but cannot be parsed as valid YAML.
    """
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return data if data is not None else {}
    except (yaml.YAMLError, OSError) as exc:
        raise StateParseError(
            f"Failed to parse {entity_name} from {path}: {exc}"
        ) from exc
