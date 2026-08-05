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


PROJECTS_RELATIVE_PATH = Path(".research/state/projects.yaml")
QUESTIONS_RELATIVE_PATH = Path(".research/state/questions.yaml")
HYPOTHESES_RELATIVE_PATH = Path(".research/state/hypotheses.yaml")
EXPERIMENTS_RELATIVE_PATH = Path(".research/state/experiments.yaml")
RUNS_RELATIVE_PATH = Path(".research/state/runs.yaml")
EVENTS_RELATIVE_DIR = Path(".research/events")
STATE_SCHEMA_VERSION = 1
DEFAULT_PROJECT_ID = "proj_default"
LOCK_TIMEOUT_SECONDS = int(os.environ.get("AGENT_STATE_LOCK_TIMEOUT_SECONDS", "30"))
LOCK_POLL_INTERVAL_SECONDS = 0.1
_CLOSING_RUN_STATUSES = frozenset({"completed", "failed"})
_QUESTION_STATUSES = frozenset({"answered", "abandoned"})
_HYPOTHESIS_STATUSES = frozenset({"supported", "refuted", "inconclusive"})
_EXPERIMENT_STATUSES = frozenset({"running", "completed", "failed"})


class ProjectRootNotFoundError(RuntimeError):
    """Raised when no ancestor directory containing a .git entry can be found."""


class StateParseError(ValueError):
    """Raised when a state/*.yaml file exists but cannot be parsed as valid YAML."""


class QuestionNotFoundError(ValueError):
    """Raised when a question_id does not exist in state/questions.yaml."""


class ProjectNotFoundError(ValueError):
    """Raised when a project_id does not exist in state/projects.yaml."""


class HypothesisNotFoundError(ValueError):
    """Raised when a hypothesis_id does not exist in state/hypotheses.yaml."""


class ExperimentNotFoundError(ValueError):
    """Raised when an experiment_id does not exist in state/experiments.yaml."""


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


_RESEARCH_GITIGNORE_CONTENTS = (
    "state/*.lock\n"
    "events/\n"
    "indexes/\n"
    "cache/\n"
    "*.tmp\n"
)


def _ensure_research_gitignore(project_root: Path) -> None:
    """Ensure .research/.gitignore exists, creating it on first write only.

    `.research/state/*.yaml` is canonical and git-tracked by design, but the
    lock sidecar files that live alongside it (state/*.lock), plus the
    events/, indexes/, and cache/ directories, are disposable/generated and
    should never show up as git diff noise. Nothing else in this project
    creates `.research/.gitignore` (resource-resolver, which also writes
    under `.research/`, doesn't add one either), so this skill bootstraps it
    itself the first time it actually writes anything.

    Never overwrites an existing `.gitignore` -- a user or another skill may
    have customized it, and clobbering that would be its own kind of
    surprising data loss.

    Args:
        project_root: The project's root directory.
    """
    gitignore_path = project_root / ".research" / ".gitignore"
    if gitignore_path.exists():
        return
    gitignore_path.parent.mkdir(parents=True, exist_ok=True)
    gitignore_path.write_text(_RESEARCH_GITIGNORE_CONTENTS, encoding="utf-8")


@contextmanager
def _locked_file(project_root: Path, path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock guarding `path` for the block's duration.

    POSIX: fcntl.flock(LOCK_EX | LOCK_NB), retried on a short poll interval
    up to LOCK_TIMEOUT_SECONDS. Non-POSIX (no fcntl module, e.g. Windows)
    fails loudly with LockTimeoutError rather than silently proceeding
    unprotected -- mirrors the "Non-POSIX (Windows)" rule in
    skills/academic-pipeline/references/passport_as_reset_boundary.md.

    Importantly, the lock is NOT taken on `path` itself -- it's taken on a
    stable sidecar file at `path` + ".lock". `_save_yaml_map` and callers of
    `_append_event`'s shard writer do their read-modify-write by atomically
    replacing `path` (write to a temp file, then `os.replace`/`Path.replace`
    onto `path`). flock() locks are bound to the underlying inode of the
    open file description, not to the path string, so if we locked `path`
    directly, an atomic replace performed *inside* the locked critical
    section would silently swap in a fresh, never-locked inode at that same
    path -- any process that opens `path` afterward gets that new inode and
    sails past the lock with zero contention, racing whoever is still
    mid-write. (Confirmed by reproduction: 8 concurrent `--start-run` calls
    lost 2 of 8 records to exactly this race before this fix.) The sidecar
    lock file sidesteps this because nothing ever renames or replaces it --
    it is only ever touch()'d once, then opened/flocked/unflocked -- so its
    identity (inode) never changes across the critical section. Do NOT let
    any code atomically replace the lock file itself; that would reintroduce
    the same race this function exists to prevent.

    Every call site of this function is a write choke point for
    `.research/`, so it's also where `.research/.gitignore` gets bootstrapped
    on first use (see `_ensure_research_gitignore`) -- this keeps that
    one-line concern out of every individual public function.

    Args:
        project_root: The project's root directory; used only to locate
            `.research/.gitignore` for the one-time bootstrap check.
        path: The data file being protected. Its sidecar lock file
            (`path` + ".lock") is created (empty) if it doesn't exist yet,
            so the lock has something stable to hold onto even before
            `path`'s real content is first written.

    Yields:
        None. The caller does its read-modify-write inside the `with` block.

    Raises:
        LockTimeoutError: If the lock isn't acquired within
            LOCK_TIMEOUT_SECONDS, or if OS-level exclusion isn't available
            on this platform.
    """
    _ensure_research_gitignore(project_root)
    try:
        import fcntl as _fcntl
    except ImportError as exc:
        raise LockTimeoutError(
            "Concurrency protection unavailable on this platform: the "
            f"fcntl module is POSIX-only. Refusing to write {path} "
            "without an exclusive lock."
        ) from exc

    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR)
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
        StateParseError: If the file exists but isn't valid YAML, its
            top-level structure isn't a mapping with `top_key` holding a
            map, or its "version" doesn't match STATE_SCHEMA_VERSION. A
            missing "version" key is treated as version 1 rather than an
            error -- files written before schema versioning existed never
            had one, and 1 is the format they were actually written in.
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
    version = data.get("version", 1)
    if version != STATE_SCHEMA_VERSION:
        raise StateParseError(
            f"{path} has unsupported schema version {version!r} "
            f"(expected {STATE_SCHEMA_VERSION}); this file was written by "
            "an incompatible version of agent-state and needs a manual "
            "migration before it can be read."
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
        yaml.safe_dump(
            {"version": STATE_SCHEMA_VERSION, top_key: records},
            sort_keys=True, allow_unicode=True,
        ),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def load_projects(project_root: Path) -> Dict[str, Any]:
    """Load all Project records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Project record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / PROJECTS_RELATIVE_PATH, "projects")


def create_project(
    project_root: Path,
    name: str,
    description: Optional[str] = None,
    created_by: str = "user",
) -> Dict[str, Any]:
    """Create a new Project record with status "active".

    Args:
        project_root: The project's root directory.
        name: Human-readable Project name.
        description: Optional longer description.
        created_by: Name of the skill creating this Project, or "user" for
            a direct CLI call.

    Returns:
        The full new Project record, including its generated "id".

    Raises:
        ValueError: If name is empty/missing.
    """
    if not name:
        raise ValueError("name is required")
    path = project_root / PROJECTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        projects = _load_yaml_map(path, "projects")
        project_id = generate_id("proj")
        record = {
            "id": project_id,
            "name": name,
            "description": description,
            "status": "active",
            "created_at": _utc_now_iso(),
            "created_by": created_by,
        }
        projects[project_id] = record
        _save_yaml_map(path, "projects", projects)
    return record


def _ensure_default_project(project_root: Path) -> str:
    """Return "proj_default", creating it if it doesn't exist yet.

    Args:
        project_root: The project's root directory.

    Returns:
        The literal string "proj_default".
    """
    path = project_root / PROJECTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        projects = _load_yaml_map(path, "projects")
        if DEFAULT_PROJECT_ID not in projects:
            now = _utc_now_iso()
            projects[DEFAULT_PROJECT_ID] = {
                "id": DEFAULT_PROJECT_ID,
                "name": "Default Project",
                "description": None,
                "status": "active",
                "created_at": now,
                "created_by": "user",
            }
            _save_yaml_map(path, "projects", projects)
    return DEFAULT_PROJECT_ID


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


def create_question(
    project_root: Path,
    text: str,
    origin_skill: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new Question record with status "open".

    Args:
        project_root: The project's root directory.
        text: The request or sub-task text.
        origin_skill: Name of the skill that raised this Question.
        project_id: Project this Question belongs to. Defaults to the
            lazily-created "proj_default" if omitted.

    Returns:
        The full new Question record, including its generated "id".

    Raises:
        ProjectNotFoundError: If project_id is given but doesn't exist.
    """
    if project_id is None:
        project_id = _ensure_default_project(project_root)
    elif project_id not in load_projects(project_root):
        raise ProjectNotFoundError(f"Unknown project_id: {project_id}")
    path = project_root / QUESTIONS_RELATIVE_PATH
    with _locked_file(project_root, path):
        questions = _load_yaml_map(path, "questions")
        question_id = generate_id("q")
        now = _utc_now_iso()
        record = {
            "id": question_id,
            "text": text,
            "origin_skill": origin_skill,
            "project_id": project_id,
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
    with _locked_file(project_root, path):
        questions = _load_yaml_map(path, "questions")
        if question_id not in questions:
            raise QuestionNotFoundError(f"Unknown question_id: {question_id}")
        questions[question_id]["status"] = status
        questions[question_id]["updated_at"] = _utc_now_iso()
        _save_yaml_map(path, "questions", questions)
        return questions[question_id]


def load_hypotheses(project_root: Path) -> Dict[str, Any]:
    """Load all Hypothesis records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Hypothesis record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / HYPOTHESES_RELATIVE_PATH, "hypotheses")


def create_hypothesis(
    project_root: Path,
    question_id: str,
    statement: str,
    created_by: str = "user",
    synthetic: bool = False,
) -> Dict[str, Any]:
    """Create a new Hypothesis record with status "proposed".

    Args:
        project_root: The project's root directory.
        question_id: The Question this Hypothesis proposes to answer; must
            already exist.
        statement: The hypothesis text.
        created_by: Name of the skill creating this Hypothesis, or "user"
            for a direct CLI call.
        synthetic: True if this record was auto-created by start_run's
            chain-completion logic rather than deliberately declared.

    Returns:
        The full new Hypothesis record, including its generated "id".

    Raises:
        QuestionNotFoundError: If question_id doesn't exist.
        ValueError: If statement is empty/missing.
    """
    if not statement:
        raise ValueError("statement is required")
    if question_id not in load_questions(project_root):
        raise QuestionNotFoundError(f"Unknown question_id: {question_id}")
    path = project_root / HYPOTHESES_RELATIVE_PATH
    with _locked_file(project_root, path):
        hypotheses = _load_yaml_map(path, "hypotheses")
        hypothesis_id = generate_id("hyp")
        record = {
            "id": hypothesis_id,
            "question_id": question_id,
            "statement": statement,
            "status": "proposed",
            "synthetic": synthetic,
            "created_at": _utc_now_iso(),
            "created_by": created_by,
        }
        hypotheses[hypothesis_id] = record
        _save_yaml_map(path, "hypotheses", hypotheses)
    return record


def set_hypothesis_status(project_root: Path, hypothesis_id: str, status: str) -> Dict[str, Any]:
    """Transition a Hypothesis's verdict status.

    Args:
        project_root: The project's root directory.
        hypothesis_id: The Hypothesis to update.
        status: New status, must be "supported", "refuted", or "inconclusive".

    Returns:
        The updated Hypothesis record.

    Raises:
        HypothesisNotFoundError: If hypothesis_id doesn't exist.
        ValueError: If status isn't one of the allowed values.
    """
    if status not in _HYPOTHESIS_STATUSES:
        raise ValueError(
            f"status must be 'supported', 'refuted', or 'inconclusive', got {status!r}"
        )
    path = project_root / HYPOTHESES_RELATIVE_PATH
    with _locked_file(project_root, path):
        hypotheses = _load_yaml_map(path, "hypotheses")
        if hypothesis_id not in hypotheses:
            raise HypothesisNotFoundError(f"Unknown hypothesis_id: {hypothesis_id}")
        hypotheses[hypothesis_id]["status"] = status
        _save_yaml_map(path, "hypotheses", hypotheses)
        return hypotheses[hypothesis_id]


def load_experiments(project_root: Path) -> Dict[str, Any]:
    """Load all Experiment records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Experiment record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / EXPERIMENTS_RELATIVE_PATH, "experiments")


def create_experiment(
    project_root: Path,
    hypothesis_id: str,
    description: str,
    created_by: str = "user",
    synthetic: bool = False,
) -> Dict[str, Any]:
    """Create a new Experiment record with status "planned".

    Args:
        project_root: The project's root directory.
        hypothesis_id: The Hypothesis this Experiment tests; must already
            exist.
        description: What the experiment does.
        created_by: Name of the skill creating this Experiment, or "user"
            for a direct CLI call.
        synthetic: True if this record was auto-created by start_run's
            chain-completion logic rather than deliberately declared.

    Returns:
        The full new Experiment record, including its generated "id".

    Raises:
        HypothesisNotFoundError: If hypothesis_id doesn't exist.
        ValueError: If description is empty/missing.
    """
    if not description:
        raise ValueError("description is required")
    if hypothesis_id not in load_hypotheses(project_root):
        raise HypothesisNotFoundError(f"Unknown hypothesis_id: {hypothesis_id}")
    path = project_root / EXPERIMENTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        experiments = _load_yaml_map(path, "experiments")
        experiment_id = generate_id("exp")
        record = {
            "id": experiment_id,
            "hypothesis_id": hypothesis_id,
            "description": description,
            "status": "planned",
            "synthetic": synthetic,
            "created_at": _utc_now_iso(),
            "created_by": created_by,
        }
        experiments[experiment_id] = record
        _save_yaml_map(path, "experiments", experiments)
    return record


def set_experiment_status(project_root: Path, experiment_id: str, status: str) -> Dict[str, Any]:
    """Transition an Experiment's status.

    Args:
        project_root: The project's root directory.
        experiment_id: The Experiment to update.
        status: New status, must be "running", "completed", or "failed".

    Returns:
        The updated Experiment record.

    Raises:
        ExperimentNotFoundError: If experiment_id doesn't exist.
        ValueError: If status isn't one of the allowed values.
    """
    if status not in _EXPERIMENT_STATUSES:
        raise ValueError(
            f"status must be 'running', 'completed', or 'failed', got {status!r}"
        )
    path = project_root / EXPERIMENTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        experiments = _load_yaml_map(path, "experiments")
        if experiment_id not in experiments:
            raise ExperimentNotFoundError(f"Unknown experiment_id: {experiment_id}")
        experiments[experiment_id]["status"] = status
        _save_yaml_map(path, "experiments", experiments)
        return experiments[experiment_id]


def _question_id_for_experiment(project_root: Path, experiment_id: str) -> str:
    """Walk experiment_id -> hypothesis_id -> question_id to find the owning Question.

    Args:
        project_root: The project's root directory.
        experiment_id: An Experiment id already known to exist.

    Returns:
        The question_id of the Hypothesis the Experiment belongs to.
    """
    experiments = load_experiments(project_root)
    hypothesis_id = experiments[experiment_id]["hypothesis_id"]
    hypotheses = load_hypotheses(project_root)
    return hypotheses[hypothesis_id]["question_id"]


def start_run(
    project_root: Path,
    skill: str,
    mode: Optional[str] = None,
    question_id: Optional[str] = None,
    question_text: Optional[str] = None,
    hypothesis_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Start a new Run, auto-completing its research chain as needed.

    Resolution, most specific first:
      1. experiment_id given -- validated to exist, used directly.
      2. hypothesis_id given (no experiment_id) -- validated to exist, a
         synthetic Experiment is created under it.
      3. question_id or question_text given (no hypothesis_id/experiment_id)
         -- resolved exactly as before, then a synthetic Hypothesis and a
         synthetic Experiment are created under it.
      4. Nothing given at all -- unchanged standalone behavior: question_id,
         hypothesis_id, and experiment_id are all left None. No Question,
         Hypothesis, or Experiment is created.

    Args:
        project_root: The project's root directory.
        skill: Name of the skill executing this Run.
        mode: Optional mode name within that skill.
        question_id: Link to an existing Question. Mutually exclusive with
            question_text.
        question_text: Create a new Question (status "open") and link this
            Run to it. Mutually exclusive with question_id.
        hypothesis_id: Link to an existing Hypothesis; a synthetic
            Experiment is created under it.
        experiment_id: Link directly to an existing Experiment.

    Returns:
        The full new Run record, including its generated "id". Its
        "question_id" is always derived by walking "experiment_id"'s chain
        when an experiment is involved, rather than taken from the
        question_id/question_text arguments directly.

    Raises:
        QuestionNotFoundError: If question_id is given but doesn't exist.
        HypothesisNotFoundError: If hypothesis_id is given but doesn't exist.
        ExperimentNotFoundError: If experiment_id is given but doesn't exist.
        ValueError: If skill is empty/missing, or if both question_id and
            question_text are given.
    """
    if not skill:
        raise ValueError("skill is required")
    if question_id and question_text:
        raise ValueError("question_id and question_text are mutually exclusive")

    if experiment_id:
        if experiment_id not in load_experiments(project_root):
            raise ExperimentNotFoundError(f"Unknown experiment_id: {experiment_id}")
    elif hypothesis_id:
        if hypothesis_id not in load_hypotheses(project_root):
            raise HypothesisNotFoundError(f"Unknown hypothesis_id: {hypothesis_id}")
        experiment = create_experiment(
            project_root, hypothesis_id,
            description=f"Auto-created for run started by {skill}",
            created_by=skill, synthetic=True,
        )
        experiment_id = experiment["id"]
    elif question_id or question_text:
        if question_text:
            question = create_question(project_root, question_text, origin_skill=skill)
            question_id = question["id"]
        elif question_id not in load_questions(project_root):
            raise QuestionNotFoundError(f"Unknown question_id: {question_id}")
        hypothesis = create_hypothesis(
            project_root, question_id,
            statement=f"Auto-created for run started by {skill}",
            created_by=skill, synthetic=True,
        )
        experiment = create_experiment(
            project_root, hypothesis["id"],
            description=f"Auto-created for run started by {skill}",
            created_by=skill, synthetic=True,
        )
        experiment_id = experiment["id"]

    resolved_question_id = (
        _question_id_for_experiment(project_root, experiment_id) if experiment_id else None
    )

    path = project_root / RUNS_RELATIVE_PATH
    with _locked_file(project_root, path):
        runs = _load_yaml_map(path, "runs")
        run_id = generate_id("run")
        record = {
            "id": run_id,
            "skill": skill,
            "mode": mode,
            "question_id": resolved_question_id,
            "experiment_id": experiment_id,
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
    with _locked_file(project_root, path):
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

    Stamps `event["schema_version"] = STATE_SCHEMA_VERSION` in place before
    writing, so the caller's dict (which record_result/record_claim return
    to their own caller) reflects exactly what was persisted to disk.

    Args:
        project_root: The project's root directory.
        event: The fully populated event dict to serialize (including "ts").
            Mutated in place to add "schema_version".
    """
    event["schema_version"] = STATE_SCHEMA_VERSION
    shard_path = _events_shard_path(project_root, datetime.now(timezone.utc))
    with _locked_file(project_root, shard_path):
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
        ValueError: If summary is empty/missing, or if exactly one of
            artifact_role/artifact_path is given.
    """
    if not summary:
        raise ValueError("summary is required")
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
        ValueError: If statement is empty/missing.
    """
    if not statement:
        raise ValueError("statement is required")
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
