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
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

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


def _load_yaml_map(path: Path, top_key: str) -> Dict[str, Any]:
    """Load an id-keyed YAML document, defaulting to an empty map.

    Args:
        path: Path to the YAML file (e.g. state/questions.yaml).
        top_key: The top-level key holding the id -> record map
            ("questions" or "runs").

    Returns:
        The parsed id -> record map ({} if the file doesn't exist yet).

    Raises:
        StateParseError: If the file exists but isn't valid YAML, or its
            top-level structure isn't a mapping with `top_key` holding a map.
    """
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise StateParseError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict) or not isinstance(data.get(top_key), dict):
        raise StateParseError(
            f"{path} must be a mapping with a top-level '{top_key}' map."
        )
    return data[top_key]


def _save_yaml_map(path: Path, top_key: str, records: Dict[str, Any]) -> None:
    """Write an id-keyed YAML document, replacing the file atomically.

    Args:
        path: Destination YAML path.
        top_key: Top-level key to nest `records` under.
        records: The full id -> record map to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        yaml.safe_dump({top_key: records}, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def load_questions(project_root: Path) -> Dict[str, Any]:
    """Load all Question records.

    Args:
        project_root: The project's root directory (see find_project_root).

    Returns:
        id -> Question record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / QUESTIONS_RELATIVE_PATH, "questions")


def load_runs(project_root: Path) -> Dict[str, Any]:
    """Load all Run records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Run record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / RUNS_RELATIVE_PATH, "runs")


def create_question(project_root: Path, text: str, origin_skill: str) -> Dict[str, Any]:
    """Create a new Question record with status "open".

    Args:
        project_root: The project's root directory.
        text: The request or sub-task text.
        origin_skill: Name of the skill that raised this Question.

    Returns:
        The full new Question record, including its generated "id".
    """
    path = project_root / QUESTIONS_RELATIVE_PATH
    with _locked_file(path):
        questions = _load_yaml_map(path, "questions")
        question_id = generate_id("q")
        now = _utc_now_iso()
        record = {
            "id": question_id,
            "text": text,
            "origin_skill": origin_skill,
            "status": "open",
            "created_at": now,
            "updated_at": now,
        }
        questions[question_id] = record
        _save_yaml_map(path, "questions", questions)
    return record


def set_question_status(project_root: Path, question_id: str, status: str) -> Dict[str, Any]:
    """Transition a Question's status.

    Args:
        project_root: The project's root directory.
        question_id: The Question to update.
        status: New status, must be "answered" or "abandoned".

    Returns:
        The updated Question record.

    Raises:
        QuestionNotFoundError: If question_id doesn't exist.
        ValueError: If status isn't "answered" or "abandoned".
    """
    if status not in _QUESTION_STATUSES:
        raise ValueError(f"status must be 'answered' or 'abandoned', got {status!r}")
    path = project_root / QUESTIONS_RELATIVE_PATH
    with _locked_file(path):
        questions = _load_yaml_map(path, "questions")
        if question_id not in questions:
            raise QuestionNotFoundError(f"Unknown question_id: {question_id}")
        questions[question_id]["status"] = status
        questions[question_id]["updated_at"] = _utc_now_iso()
        _save_yaml_map(path, "questions", questions)
        return questions[question_id]


def start_run(
    project_root: Path,
    skill: str,
    mode: Optional[str] = None,
    question_id: Optional[str] = None,
    question_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Start a new Run, optionally creating or linking a Question.

    Args:
        project_root: The project's root directory.
        skill: Name of the skill executing this Run.
        mode: Optional mode name within that skill.
        question_id: Link to an existing Question. Mutually exclusive with
            question_text.
        question_text: Create a new Question (status "open") and link this
            Run to it. Mutually exclusive with question_id.

    Returns:
        The full new Run record, including its generated "id".

    Raises:
        QuestionNotFoundError: If question_id is given but doesn't exist.
        ValueError: If skill is empty/missing, or if both question_id and
            question_text are given.
    """
    if not skill:
        raise ValueError("skill is required")
    if question_id and question_text:
        raise ValueError("question_id and question_text are mutually exclusive")
    if question_text:
        question = create_question(project_root, question_text, origin_skill=skill)
        question_id = question["id"]
    elif question_id and question_id not in load_questions(project_root):
        raise QuestionNotFoundError(f"Unknown question_id: {question_id}")

    path = project_root / RUNS_RELATIVE_PATH
    with _locked_file(path):
        runs = _load_yaml_map(path, "runs")
        run_id = generate_id("run")
        record = {
            "id": run_id,
            "skill": skill,
            "mode": mode,
            "question_id": question_id,
            "status": "running",
            "started_at": _utc_now_iso(),
            "ended_at": None,
        }
        runs[run_id] = record
        _save_yaml_map(path, "runs", runs)
    return record


def complete_run(project_root: Path, run_id: str, status: str) -> Dict[str, Any]:
    """Transition a Run to a terminal status.

    Args:
        project_root: The project's root directory.
        run_id: The Run to update.
        status: New status, must be "completed" or "failed".

    Returns:
        The updated Run record.

    Raises:
        RunNotFoundError: If run_id doesn't exist.
        ValueError: If status isn't "completed" or "failed".
    """
    if status not in _CLOSING_RUN_STATUSES:
        raise ValueError(f"status must be 'completed' or 'failed', got {status!r}")
    path = project_root / RUNS_RELATIVE_PATH
    with _locked_file(path):
        runs = _load_yaml_map(path, "runs")
        if run_id not in runs:
            raise RunNotFoundError(f"Unknown run_id: {run_id}")
        runs[run_id]["status"] = status
        runs[run_id]["ended_at"] = _utc_now_iso()
        _save_yaml_map(path, "runs", runs)
        return runs[run_id]


def _events_shard_path(project_root: Path, when: datetime) -> Path:
    """Return the JSONL shard path for the UTC day containing `when`.

    Args:
        project_root: The project's root directory.
        when: A timezone-aware datetime; only its UTC date is used.

    Returns:
        `.research/events/<YYYY-MM-DD>.jsonl` under project_root.
    """
    utc_date = when.astimezone(timezone.utc).date()
    return project_root / EVENTS_RELATIVE_DIR / f"{utc_date:%Y-%m-%d}.jsonl"


def _append_event(project_root: Path, event: Dict[str, Any]) -> None:
    """Append one JSON line to today's event shard under an exclusive lock.

    Args:
        project_root: The project's root directory.
        event: The fully populated event dict to serialize (including "ts").
    """
    shard_path = _events_shard_path(project_root, datetime.now(timezone.utc))
    with _locked_file(shard_path):
        with shard_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True))
            f.write("\n")


def record_result(
    project_root: Path,
    run_id: str,
    summary: str,
    artifact_role: Optional[str] = None,
    artifact_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a Result event for an existing Run.

    Args:
        project_root: The project's root directory.
        run_id: The Run this Result belongs to; must already exist.
        summary: Short description of what was produced.
        artifact_role: Optional resource-resolver role name the artifact
            lives under. Must be given together with artifact_path or not
            at all.
        artifact_path: Optional path relative to that role's resolved
            directory.

    Returns:
        The full Result event, including its generated "id" and "ts".

    Raises:
        RunNotFoundError: If run_id doesn't exist in state/runs.yaml.
        ValueError: If exactly one of artifact_role/artifact_path is given.
    """
    if bool(artifact_role) != bool(artifact_path):
        raise ValueError("artifact_role and artifact_path must be given together")
    if run_id not in load_runs(project_root):
        raise RunNotFoundError(f"Unknown run_id: {run_id}")
    event: Dict[str, Any] = {
        "event": "result",
        "id": generate_id("res"),
        "run_id": run_id,
        "summary": summary,
        "artifact_ref": (
            {"role": artifact_role, "path": artifact_path} if artifact_role else None
        ),
        "ts": _utc_now_iso(),
    }
    _append_event(project_root, event)
    return event


def record_claim(
    project_root: Path,
    run_id: str,
    statement: str,
    confidence: Optional[str] = None,
    evidence_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a Claim event for an existing Run.

    Args:
        project_root: The project's root directory.
        run_id: The Run this Claim belongs to; must already exist.
        statement: The assertion or decision text.
        confidence: Optional "low", "medium", or "high".
        evidence_ref: Optional supporting reference (path, quote, URL).

    Returns:
        The full Claim event, including its generated "id" and "ts".

    Raises:
        RunNotFoundError: If run_id doesn't exist in state/runs.yaml.
    """
    if run_id not in load_runs(project_root):
        raise RunNotFoundError(f"Unknown run_id: {run_id}")
    event: Dict[str, Any] = {
        "event": "claim",
        "id": generate_id("clm"),
        "run_id": run_id,
        "statement": statement,
        "confidence": confidence,
        "evidence_ref": evidence_ref,
        "ts": _utc_now_iso(),
    }
    _append_event(project_root, event)
    return event
