# Agent State Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `skills/agent-state`, a shared skill that stores Question/Run
(canonical, low-frequency) in `.research/state/*.yaml` and Result/Claim
(canonical, high-frequency, immutable) in `.research/events/*.jsonl`, with a
rebuildable SQLite query index and a CLI other skills can eventually call.

**Architecture:** Three flat Python scripts under `skills/agent-state/scripts/`
(no subpackages, so the skill remains a portable, self-contained directory
after `install.sh` copies it to `~/.claude/skills/`): `state_store.py` (project
root discovery, id generation, file locking, Question/Run CRUD, Result/Claim
event append), `state_index.py` (SQLite schema, incremental/full rebuild,
filtered queries), and `state.py` (the CLI entry point, argparse-based,
JSON-on-stdout, mirroring `skills/resource-resolver/scripts/resolve.py`'s
conventions). Tests are subprocess-based against `state.py`, matching how
`resolve.py` and `research-log/scripts/section_query.py` are tested elsewhere
in this repo — no internal-module unit tests, no new import-path machinery.

**Tech Stack:** Python 3, PyYAML (already a repo dependency), `sqlite3`
(stdlib), `argparse` (stdlib), `pytest` + `subprocess` for tests.

## Global Constraints

- Every function signature has type hints; every public function/class has a
  Google-style docstring (user's global code-style standard — non-negotiable
  even where the code is self-explanatory).
- No file in this plan exceeds ~1000 lines; the three-file split keeps each
  well under that.
- No silent failures: invalid input raises a named exception; nothing is
  masked with a default value. Every CLI error path still prints valid JSON
  to stdout when `--json` is given and exits non-zero — never an uncaught
  traceback (`skills/resource-resolver/scripts/resolve.py:481-497` is the
  precedent).
- File locking on `state/*.yaml` and `events/*.jsonl` follows
  `skills/academic-pipeline/references/passport_as_reset_boundary.md`'s
  "Concurrency model" section: POSIX `fcntl.flock(fd, fcntl.LOCK_EX)`, a
  bounded timeout (30s default), timeout is a hard error with no automatic
  retry, and a platform without `fcntl` fails loudly rather than degrading
  to unprotected writes.
- All code comments, docstrings, commit subjects, and log/error messages are
  in English regardless of conversation language.
- No new pip dependencies. PyYAML is already required repo-wide; `sqlite3`
  and `argparse` are stdlib.
- Every code snippet below is the actual content to write — no
  "implement later", no "similar to Task N" shorthand.

---

### Task 1: Scaffold + `--rebuild-index`

**Files:**
- Create: `skills/agent-state/scripts/state_store.py`
- Create: `skills/agent-state/scripts/state_index.py`
- Create: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Produces (used by every later task):
  - `state_store.find_project_root(start: Path) -> Path`
  - `state_store.ProjectRootNotFoundError(RuntimeError)`
  - `state_store.StateParseError(ValueError)`
  - `state_store.QuestionNotFoundError(ValueError)`
  - `state_store.RunNotFoundError(ValueError)`
  - `state_store.LockTimeoutError(RuntimeError)`
  - `state_index.INDEX_RELATIVE_PATH: Path` = `.research/indexes/index.db`
  - `state_index.rebuild_index(project_root: Path, full: bool = False) -> Dict[str, Any]`
    returning `{"rebuilt": "full" | "incremental", "shards_scanned": int}`
  - `state.py` CLI: `--rebuild-index [--full] [--json]`

- [ ] **Step 1: Write the failing CLI test**

Create `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
"""Subprocess tests for state.py -- Agent State CLI."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "state.py"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def test_rebuild_index_on_fresh_project_creates_empty_db(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--rebuild-index", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"rebuilt": "full", "shards_scanned": 0}
    assert (project / ".research" / "indexes" / "index.db").is_file()


def test_rebuild_index_incremental_by_default(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--rebuild-index", "--full", "--json")

    result = _run(project, "--rebuild-index", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"rebuilt": "incremental", "shards_scanned": 0}


def test_errors_when_no_git_root(tmp_path: Path) -> None:
    no_git_dir = tmp_path / "not_a_project"
    no_git_dir.mkdir()

    # This test's premise -- "no .git anywhere in the ancestry" -- only holds
    # if nothing above tmp_path happens to contain a .git entry. /tmp is
    # shared with other processes on this machine, so skip rather than
    # assert a false positive if that premise doesn't hold here.
    for candidate in (no_git_dir, *no_git_dir.parents):
        if (candidate / ".git").exists():
            pytest.skip("A .git directory exists above tmp_path on this machine")

    result = _run(no_git_dir, "--rebuild-index", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProjectRootNotFoundError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: FAIL (`state.py` does not exist / `ModuleNotFoundError` or
`FileNotFoundError` from `subprocess.run`).

- [ ] **Step 3: Write `state_store.py`'s foundational pieces**

Create `skills/agent-state/scripts/state_store.py`:

```python
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
```

- [ ] **Step 4: Write `state_index.py`'s schema and rebuild**

Create `skills/agent-state/scripts/state_index.py`:

```python
#!/usr/bin/env python3
"""state_index.py -- SQLite query index rebuilt from state/*.yaml and events/*.jsonl.

Never a source of truth: indexes/index.db is safe to delete at any time and
rebuild from state_store's canonical files. Provides fast filtered queries
over Questions, Runs, Results, and Claims without scanning every JSONL
shard on every call.
"""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from state_store import EVENTS_RELATIVE_DIR

INDEX_RELATIVE_PATH = Path(".research/indexes/index.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, text TEXT, origin_skill TEXT, status TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, skill TEXT, mode TEXT, question_id TEXT,
    status TEXT, started_at TEXT, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS results (
    id TEXT PRIMARY KEY, run_id TEXT, summary TEXT,
    artifact_role TEXT, artifact_path TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY, run_id TEXT, statement TEXT,
    confidence TEXT, evidence_ref TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS shard_checkpoints (
    shard_name TEXT PRIMARY KEY, lines_ingested INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_skill ON runs(skill);
CREATE INDEX IF NOT EXISTS idx_runs_question_id ON runs(question_id);
CREATE INDEX IF NOT EXISTS idx_results_run_id ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_claims_run_id ON claims(run_id);
"""


def _connect(project_root: Path) -> sqlite3.Connection:
    """Open (creating if needed) the index database with its schema applied.

    Args:
        project_root: The project's root directory.

    Returns:
        An open connection with row_factory set to sqlite3.Row.
    """
    index_path = project_root / INDEX_RELATIVE_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(index_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _sync_state_tables(conn: sqlite3.Connection, project_root: Path) -> None:
    """Replace the questions and runs tables with the current YAML contents.

    Args:
        conn: Open connection (schema already applied).
        project_root: The project's root directory.
    """
    # Imported here, not at module scope, so this module never needs
    # state_store's YAML-loading functions except at rebuild time.
    from state_store import QUESTIONS_RELATIVE_PATH, RUNS_RELATIVE_PATH, _load_yaml_map

    questions = _load_yaml_map(project_root / QUESTIONS_RELATIVE_PATH, "questions")
    runs = _load_yaml_map(project_root / RUNS_RELATIVE_PATH, "runs")

    conn.execute("DELETE FROM questions")
    if questions:
        conn.executemany(
            "INSERT INTO questions (id, text, origin_skill, status, created_at, updated_at) "
            "VALUES (:id, :text, :origin_skill, :status, :created_at, :updated_at)",
            list(questions.values()),
        )
    conn.execute("DELETE FROM runs")
    if runs:
        conn.executemany(
            "INSERT INTO runs (id, skill, mode, question_id, status, started_at, ended_at) "
            "VALUES (:id, :skill, :mode, :question_id, :status, :started_at, :ended_at)",
            list(runs.values()),
        )


def _ingest_shard(conn: sqlite3.Connection, shard_path: Path) -> None:
    """Ingest not-yet-checkpointed lines from one JSONL shard.

    Whether this ingests from the beginning or resumes from a prior
    checkpoint depends entirely on whether rebuild_index already cleared
    shard_checkpoints for a full rebuild -- this function always just
    catches up from whatever checkpoint (or none) it finds.

    Args:
        conn: Open connection.
        shard_path: Path to one events/YYYY-MM-DD.jsonl shard.
    """
    shard_name = shard_path.name
    row = conn.execute(
        "SELECT lines_ingested FROM shard_checkpoints WHERE shard_name = ?",
        (shard_name,),
    ).fetchone()
    already_ingested = row["lines_ingested"] if row else 0

    lines = shard_path.read_text(encoding="utf-8").splitlines()
    for line in lines[already_ingested:]:
        event = json.loads(line)
        if event["event"] == "result":
            artifact_ref = event.get("artifact_ref") or {}
            conn.execute(
                "INSERT OR REPLACE INTO results "
                "(id, run_id, summary, artifact_role, artifact_path, ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event["id"], event["run_id"], event["summary"],
                    artifact_ref.get("role"), artifact_ref.get("path"), event["ts"],
                ),
            )
        elif event["event"] == "claim":
            conn.execute(
                "INSERT OR REPLACE INTO claims "
                "(id, run_id, statement, confidence, evidence_ref, ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event["id"], event["run_id"], event["statement"],
                    event.get("confidence"), event.get("evidence_ref"), event["ts"],
                ),
            )
    conn.execute(
        "INSERT OR REPLACE INTO shard_checkpoints (shard_name, lines_ingested) VALUES (?, ?)",
        (shard_name, len(lines)),
    )


def rebuild_index(project_root: Path, full: bool = False) -> Dict[str, Any]:
    """Sync the SQLite index from state/*.yaml and events/*.jsonl.

    Args:
        project_root: The project's root directory.
        full: If True, discard all shard checkpoints and re-ingest every
            event from scratch (needed after manual edits to state/*.yaml,
            or if the index looks corrupted). If False (default), only new
            lines since each shard's last recorded checkpoint are ingested.

    Returns:
        {"rebuilt": "full" | "incremental", "shards_scanned": <int>}.
    """
    conn = _connect(project_root)
    try:
        if full:
            conn.execute("DELETE FROM results")
            conn.execute("DELETE FROM claims")
            conn.execute("DELETE FROM shard_checkpoints")
        _sync_state_tables(conn, project_root)
        events_dir = project_root / EVENTS_RELATIVE_DIR
        shard_paths = sorted(events_dir.glob("*.jsonl")) if events_dir.is_dir() else []
        for shard_path in shard_paths:
            _ingest_shard(conn, shard_path)
        conn.commit()
        return {
            "rebuilt": "full" if full else "incremental",
            "shards_scanned": len(shard_paths),
        }
    finally:
        conn.close()


def _rows(conn: sqlite3.Connection, sql: str, params: tuple) -> List[Dict[str, Any]]:
    """Run a parameterized SELECT and return rows as plain dicts.

    Args:
        conn: Open connection with row_factory set to sqlite3.Row.
        sql: A SELECT statement with `?` placeholders.
        params: Values to bind to the placeholders.

    Returns:
        Each matching row as a dict.
    """
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def query(
    project_root: Path,
    *,
    run_id: Optional[str] = None,
    question_id: Optional[str] = None,
    skill: Optional[str] = None,
    since: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Sync the index incrementally, then return records for exactly one filter.

    Args:
        project_root: The project's root directory.
        run_id: Return this Run plus its Results and Claims.
        question_id: Return this Question plus Runs linked to it.
        skill: Return Runs executed by this skill.
        since: ISO-8601 date/datetime string; return Runs started at or
            after it.

    Returns:
        A dict with whichever of "questions", "runs", "results", "claims"
        keys are relevant to the filter used, each a list of row dicts.

    Raises:
        ValueError: If zero or more than one filter is given.
    """
    filters = [f for f in (run_id, question_id, skill, since) if f is not None]
    if len(filters) != 1:
        raise ValueError(
            "query requires exactly one of run_id/question_id/skill/since"
        )

    rebuild_index(project_root, full=False)
    conn = _connect(project_root)
    try:
        if run_id is not None:
            return {
                "runs": _rows(conn, "SELECT * FROM runs WHERE id = ?", (run_id,)),
                "results": _rows(
                    conn, "SELECT * FROM results WHERE run_id = ? ORDER BY ts", (run_id,)
                ),
                "claims": _rows(
                    conn, "SELECT * FROM claims WHERE run_id = ? ORDER BY ts", (run_id,)
                ),
            }
        if question_id is not None:
            return {
                "questions": _rows(
                    conn, "SELECT * FROM questions WHERE id = ?", (question_id,)
                ),
                "runs": _rows(
                    conn,
                    "SELECT * FROM runs WHERE question_id = ? ORDER BY started_at",
                    (question_id,),
                ),
            }
        if skill is not None:
            return {
                "runs": _rows(
                    conn, "SELECT * FROM runs WHERE skill = ? ORDER BY started_at", (skill,)
                )
            }
        return {
            "runs": _rows(
                conn,
                "SELECT * FROM runs WHERE started_at >= ? ORDER BY started_at",
                (since,),
            )
        }
    finally:
        conn.close()
```

- [ ] **Step 5: Write `state.py`'s CLI skeleton with `--rebuild-index`**

Create `skills/agent-state/scripts/state.py`:

```python
#!/usr/bin/env python3
"""state.py -- Agent State CLI: record and query Question/Run/Result/Claim.

Usage:
    python state.py --start-run --skill deep-research [--mode full] \
        [--question "..." | --question-id Q_ID] [--json]
    python state.py --complete-run --run-id RUN_ID --status completed|failed [--json]
    python state.py --answer-question --question-id Q_ID [--json]
    python state.py --abandon-question --question-id Q_ID [--json]
    python state.py --record-result --run-id RUN_ID --summary "..." \
        [--artifact-role ROLE --artifact-path PATH] [--json]
    python state.py --record-claim --run-id RUN_ID --statement "..." \
        [--confidence low|medium|high] [--evidence "..."] [--json]
    python state.py --query (--run-id ID | --question-id ID | --skill NAME | --since DATE) [--json]
    python state.py --rebuild-index [--full] [--json]
    python state.py --report [--since DATE]
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import state_index
import state_store


def _build_parser() -> argparse.ArgumentParser:
    """Construct the state.py argument parser.

    Returns:
        A configured ArgumentParser with a required, mutually exclusive
        action group plus the shared value flags each action consumes.
    """
    parser = argparse.ArgumentParser(
        description="Agent State: record and query Question/Run/Result/Claim."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--start-run", action="store_true")
    action.add_argument("--complete-run", action="store_true")
    action.add_argument("--answer-question", action="store_true")
    action.add_argument("--abandon-question", action="store_true")
    action.add_argument("--record-result", action="store_true")
    action.add_argument("--record-claim", action="store_true")
    action.add_argument("--query", action="store_true")
    action.add_argument("--rebuild-index", action="store_true")
    action.add_argument("--report", action="store_true")

    parser.add_argument("--skill", metavar="NAME")
    parser.add_argument("--mode", metavar="MODE")
    parser.add_argument("--question", metavar="TEXT")
    parser.add_argument("--question-id", metavar="ID")
    parser.add_argument("--run-id", metavar="ID")
    parser.add_argument("--status", choices=["completed", "failed"])
    parser.add_argument("--summary", metavar="TEXT")
    parser.add_argument("--artifact-role", metavar="ROLE")
    parser.add_argument("--artifact-path", metavar="PATH")
    parser.add_argument("--statement", metavar="TEXT")
    parser.add_argument("--confidence", choices=["low", "medium", "high"])
    parser.add_argument("--evidence", metavar="TEXT")
    parser.add_argument("--since", metavar="DATE")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _dispatch(args: argparse.Namespace, project_root: Path) -> Dict[str, Any]:
    """Route parsed CLI args (other than --report) to the matching call.

    Args:
        args: Parsed argparse namespace.
        project_root: The project's root directory.

    Returns:
        The JSON-serializable result of the selected action.
    """
    if args.rebuild_index:
        return state_index.rebuild_index(project_root, full=args.full)
    raise AssertionError("no action selected despite argparse required group")


def main() -> None:
    """CLI entry point for state.py."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        project_root = state_store.find_project_root(Path.cwd())
        result = _dispatch(args, project_root)
    except (
        state_store.ProjectRootNotFoundError,
        state_store.StateParseError,
        state_store.QuestionNotFoundError,
        state_store.RunNotFoundError,
        state_store.LockTimeoutError,
        ValueError,
    ) as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 -- stdout must always stay parseable
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)

    print(json.dumps(result) if args.json else json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add skills/agent-state/scripts/state_store.py \
        skills/agent-state/scripts/state_index.py \
        skills/agent-state/scripts/state.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): scaffold CLI with --rebuild-index"
```

---

### Task 2: `--start-run` and `--complete-run`

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_store.generate_id`, `state_store._locked_file`,
  `state_store._utc_now_iso`, `state_store.QuestionNotFoundError`,
  `state_store.RunNotFoundError` from Task 1.
- Produces (used by Task 3, 4, 5, 7):
  - `state_store._load_yaml_map(path: Path, top_key: str) -> Dict[str, Any]`
  - `state_store._save_yaml_map(path: Path, top_key: str, records: Dict[str, Any]) -> None`
  - `state_store.load_questions(project_root: Path) -> Dict[str, Any]`
  - `state_store.load_runs(project_root: Path) -> Dict[str, Any]`
  - `state_store.create_question(project_root: Path, text: str, origin_skill: str) -> Dict[str, Any]`
  - `state_store.start_run(project_root: Path, skill: str, mode: Optional[str] = None, question_id: Optional[str] = None, question_text: Optional[str] = None) -> Dict[str, Any]`
  - `state_store.complete_run(project_root: Path, run_id: str, status: str) -> Dict[str, Any]`
  - `state.py` CLI: `--start-run --skill NAME [--mode MODE] [--question TEXT | --question-id ID]`,
    `--complete-run --run-id ID --status completed|failed`

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_start_run_without_question(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--start-run", "--skill", "deep-research", "--mode", "full", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["skill"] == "deep-research"
    assert data["mode"] == "full"
    assert data["question_id"] is None
    assert data["status"] == "running"
    assert data["ended_at"] is None
    assert data["id"].startswith("run_")


def test_start_run_with_new_question_creates_and_links_it(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--start-run", "--skill", "research-mode",
        "--question", "Does this need offline support?", "--json",
    )

    data = json.loads(result.stdout)
    assert data["question_id"].startswith("q_")
    questions_yaml = (project / ".research" / "state" / "questions.yaml").read_text()
    assert "Does this need offline support?" in questions_yaml


def test_start_run_with_unknown_question_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--question-id", "q_does_not_exist", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "QuestionNotFoundError"


def test_complete_run_updates_status_and_ended_at(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    started = json.loads(_run(project, "--start-run", "--skill", "deep-research", "--json").stdout)

    result = _run(
        project, "--complete-run", "--run-id", started["id"], "--status", "completed", "--json"
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "completed"
    assert data["ended_at"] is not None


def test_complete_run_unknown_run_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--complete-run", "--run-id", "run_missing", "--status", "failed", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "RunNotFoundError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k "start_run or complete_run"`
Expected: FAIL (`AssertionError: no action selected` surfaced as an
`AssertionError` JSON payload, or a KeyError on `data["skill"]`).

- [ ] **Step 3: Implement Question/Run CRUD in `state_store.py`**

Add to `skills/agent-state/scripts/state_store.py` (after `_locked_file`):

```python
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
        ValueError: If both question_id and question_text are given.
    """
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
```

- [ ] **Step 4: Wire the CLI actions in `state.py`**

In `skills/agent-state/scripts/state.py`, replace `_dispatch`'s body:

```python
def _dispatch(args: argparse.Namespace, project_root: Path) -> Dict[str, Any]:
    """Route parsed CLI args (other than --report) to the matching call.

    Args:
        args: Parsed argparse namespace.
        project_root: The project's root directory.

    Returns:
        The JSON-serializable result of the selected action.
    """
    if args.start_run:
        return state_store.start_run(
            project_root, args.skill, mode=args.mode,
            question_id=args.question_id, question_text=args.question,
        )
    if args.complete_run:
        return state_store.complete_run(project_root, args.run_id, args.status)
    if args.rebuild_index:
        return state_index.rebuild_index(project_root, full=args.full)
    raise AssertionError("no action selected despite argparse required group")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (8 tests total: 3 from Task 1 + 5 new).

- [ ] **Step 6: Commit**

```bash
git add skills/agent-state/scripts/state_store.py \
        skills/agent-state/scripts/state.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add --start-run and --complete-run"
```

---

### Task 3: `--answer-question` and `--abandon-question`

**Files:**
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_store.set_question_status` (Task 2), `state_store.create_question`.
- Produces: `state.py` CLI: `--answer-question --question-id ID`,
  `--abandon-question --question-id ID`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def _create_question(project: Path, text: str = "Needs offline support?") -> str:
    result = _run(
        project, "--start-run", "--skill", "research-mode", "--question", text, "--json"
    )
    return json.loads(result.stdout)["question_id"]


def test_answer_question_sets_status(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question(project)

    result = _run(project, "--answer-question", "--question-id", question_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "answered"


def test_abandon_question_sets_status(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question(project)

    result = _run(project, "--abandon-question", "--question-id", question_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "abandoned"


def test_answer_unknown_question_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--answer-question", "--question-id", "q_missing", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "QuestionNotFoundError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k question`
Expected: FAIL (`AssertionError: no action selected`).

- [ ] **Step 3: Wire the two actions in `state.py`**

In `skills/agent-state/scripts/state.py`'s `_dispatch`, add before the
`--rebuild-index` branch:

```python
    if args.answer_question:
        return state_store.set_question_status(project_root, args.question_id, "answered")
    if args.abandon_question:
        return state_store.set_question_status(project_root, args.question_id, "abandoned")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (11 tests total).

- [ ] **Step 5: Commit**

```bash
git add skills/agent-state/scripts/state.py skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add --answer-question and --abandon-question"
```

---

### Task 4: `--record-result` and `--record-claim`

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_store.load_runs`, `state_store._locked_file`,
  `state_store.generate_id`, `state_store.RunNotFoundError` (Task 1-2).
- Produces (used by Task 5, 6, 7):
  - `state_store._events_shard_path(project_root: Path, when: datetime) -> Path`
  - `state_store.record_result(project_root: Path, run_id: str, summary: str, artifact_role: Optional[str] = None, artifact_path: Optional[str] = None) -> Dict[str, Any]`
  - `state_store.record_claim(project_root: Path, run_id: str, statement: str, confidence: Optional[str] = None, evidence_ref: Optional[str] = None) -> Dict[str, Any]`
  - `state.py` CLI: `--record-result --run-id ID --summary TEXT [--artifact-role ROLE --artifact-path PATH]`,
    `--record-claim --run-id ID --statement TEXT [--confidence low|medium|high] [--evidence TEXT]`

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
import datetime as _datetime


def _start_run(project: Path, skill: str = "deep-research") -> str:
    result = _run(project, "--start-run", "--skill", skill, "--json")
    return json.loads(result.stdout)["id"]


def test_record_result_appends_to_todays_shard(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)

    result = _run(
        project, "--record-result", "--run-id", run_id, "--summary", "Found 3 sources",
        "--artifact-role", "bibliography", "--artifact-path", "sources.bib", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["event"] == "result"
    assert data["run_id"] == run_id
    assert data["artifact_ref"] == {"role": "bibliography", "path": "sources.bib"}

    today = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y-%m-%d")
    shard = project / ".research" / "events" / f"{today}.jsonl"
    assert shard.is_file()
    assert json.loads(shard.read_text().splitlines()[-1])["id"] == data["id"]


def test_record_result_requires_both_artifact_fields_together(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)

    result = _run(
        project, "--record-result", "--run-id", run_id, "--summary", "x",
        "--artifact-role", "bibliography", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_record_result_unknown_run_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--record-result", "--run-id", "run_missing", "--summary", "x", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "RunNotFoundError"


def test_record_claim_appends_event(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)

    result = _run(
        project, "--record-claim", "--run-id", run_id,
        "--statement", "Region X diverges from the plan",
        "--confidence", "high", "--evidence", "review.json:findings[2]", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["event"] == "claim"
    assert data["confidence"] == "high"
    assert data["evidence_ref"] == "review.json:findings[2]"


def test_record_claim_invalid_confidence_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)

    result = _run(
        project, "--record-claim", "--run-id", run_id, "--statement", "x",
        "--confidence", "extreme", "--json",
    )

    assert result.returncode == 2  # argparse rejects choices before we ever see it
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k record`
Expected: FAIL (`AssertionError: no action selected`; the invalid-confidence
test may already pass since it only depends on argparse `choices`, added in
Task 1 — that's fine, it's asserting existing behavior).

- [ ] **Step 3: Implement event append in `state_store.py`**

Add to `skills/agent-state/scripts/state_store.py` (after `complete_run`):

```python
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
```

`--confidence`'s value set is already enforced by argparse's `choices=["low",
"medium", "high"]` from Task 1, so `record_claim` doesn't re-validate it —
only the CLI path constrains it; a direct Python caller is trusted the same
way `complete_run`'s `status` argument isn't re-validated against argparse
choices either.

- [ ] **Step 4: Wire the two actions in `state.py`**

In `skills/agent-state/scripts/state.py`'s `_dispatch`, add before the
`--rebuild-index` branch:

```python
    if args.record_result:
        return state_store.record_result(
            project_root, args.run_id, args.summary,
            artifact_role=args.artifact_role, artifact_path=args.artifact_path,
        )
    if args.record_claim:
        return state_store.record_claim(
            project_root, args.run_id, args.statement,
            confidence=args.confidence, evidence_ref=args.evidence,
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (16 tests total).

- [ ] **Step 6: Commit**

```bash
git add skills/agent-state/scripts/state_store.py \
        skills/agent-state/scripts/state.py \
        skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add --record-result and --record-claim"
```

---

### Task 5: `--query`

**Files:**
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_index.query` (already implemented in Task 1).
- Produces: `state.py` CLI: `--query (--run-id ID | --question-id ID | --skill NAME | --since DATE)`.

`state_index.query` was already written in full in Task 1 (it only needed
`state_store.load_runs`/`load_questions`... actually it queries the SQLite
tables directly, which Task 1's `rebuild_index` already populates from
`state_store._load_yaml_map`, added in Task 2 — this task only has to wire
the CLI branch and prove the whole path end-to-end).

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_query_by_run_id_returns_run_results_and_claims(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project, skill="deep-research")
    _run(project, "--record-result", "--run-id", run_id, "--summary", "s1", "--json")
    _run(project, "--record-claim", "--run-id", run_id, "--statement", "c1", "--json")

    result = _run(project, "--query", "--run-id", run_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert len(data["runs"]) == 1 and data["runs"][0]["id"] == run_id
    assert len(data["results"]) == 1 and data["results"][0]["summary"] == "s1"
    assert len(data["claims"]) == 1 and data["claims"][0]["statement"] == "c1"


def test_query_by_question_id_returns_question_and_runs(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    started = json.loads(
        _run(project, "--start-run", "--skill", "research-mode", "--question", "Q?", "--json").stdout
    )

    result = _run(project, "--query", "--question-id", started["question_id"], "--json")

    data = json.loads(result.stdout)
    assert data["questions"][0]["id"] == started["question_id"]
    assert data["runs"][0]["id"] == started["id"]


def test_query_by_skill_filters_runs(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _start_run(project, skill="deep-research")
    _start_run(project, skill="report-slides")

    result = _run(project, "--query", "--skill", "report-slides", "--json")

    data = json.loads(result.stdout)
    assert len(data["runs"]) == 1
    assert data["runs"][0]["skill"] == "report-slides"


def test_query_incremental_sees_events_recorded_after_last_rebuild(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)
    _run(project, "--rebuild-index", "--json")  # index built before the result exists
    _run(project, "--record-result", "--run-id", run_id, "--summary", "late", "--json")

    result = _run(project, "--query", "--run-id", run_id, "--json")

    data = json.loads(result.stdout)
    assert data["results"][0]["summary"] == "late"


def test_query_requires_exactly_one_filter(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--query", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k query`
Expected: FAIL (`AssertionError: no action selected`).

- [ ] **Step 3: Wire `--query` in `state.py`**

In `skills/agent-state/scripts/state.py`'s `_dispatch`, add before the
`--rebuild-index` branch:

```python
    if args.query:
        return state_index.query(
            project_root, run_id=args.run_id, question_id=args.question_id,
            skill=args.skill, since=args.since,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (21 tests total).

- [ ] **Step 5: Commit**

```bash
git add skills/agent-state/scripts/state.py skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add --query"
```

---

### Task 6: `--rebuild-index --full` and checkpoint correctness

**Files:**
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_index.rebuild_index` (Task 1), `--record-result`/`--record-claim`
  (Task 4). No production code changes — this task is pure verification of a
  correctness property already implemented, split out because a reviewer
  could accept Task 5's filters while rejecting a checkpoint double-count bug.

- [ ] **Step 1: Write the failing (well, currently-unverified) tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_incremental_rebuild_does_not_reingest_same_lines_twice(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)
    _run(project, "--record-result", "--run-id", run_id, "--summary", "s1", "--json")
    _run(project, "--rebuild-index", "--json")  # incremental, picks up s1
    _run(project, "--rebuild-index", "--json")  # incremental again, no new lines

    result = _run(project, "--query", "--run-id", run_id, "--json")

    data = json.loads(result.stdout)
    assert len(data["results"]) == 1  # not duplicated


def test_full_rebuild_recovers_from_manually_corrupted_index(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)
    _run(project, "--record-result", "--run-id", run_id, "--summary", "s1", "--json")
    _run(project, "--rebuild-index", "--json")

    index_db = project / ".research" / "indexes" / "index.db"
    index_db.write_bytes(b"not a real sqlite file")

    result = _run(project, "--rebuild-index", "--full", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"rebuilt": "full", "shards_scanned": 1}
    query_result = _run(project, "--query", "--run-id", run_id, "--json")
    assert json.loads(query_result.stdout)["results"][0]["summary"] == "s1"
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k "rebuild_does_not or full_rebuild"`
Expected: PASS. If `test_full_rebuild_recovers_from_manually_corrupted_index`
fails, the bug is that `sqlite3.connect` on a non-SQLite file doesn't raise
until first query/write — in that case, wrap `_connect`'s
`conn.executescript(_SCHEMA)` call is exactly where the corruption surfaces
(`sqlite3.DatabaseError: file is not a database`); if it doesn't propagate as
expected, this is where to look, but the code in Task 1 already lets it
propagate uncaught into `state.py`'s catch-all `Exception` handler, which is
correct: a corrupted index is a real error, not something to swallow.

- [ ] **Step 3: Commit**

```bash
git add skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "test(agent-state): verify incremental/full index-rebuild correctness"
```

---

### Task 7: Locking under concurrent writers

**Files:**
- Test: `skills/agent-state/scripts/tests/test_state_locking.py`

**Interfaces:**
- Consumes: `state_store._locked_file`, `state_store.LOCK_TIMEOUT_SECONDS`,
  `state_store.LockTimeoutError` (Task 1), the `AGENT_STATE_LOCK_TIMEOUT_SECONDS`
  environment override (Task 1).

- [ ] **Step 1: Write the failing tests**

Create `skills/agent-state/scripts/tests/test_state_locking.py`:

```python
"""Tests proving state.py serializes concurrent writers instead of losing data."""
import fcntl
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "state.py"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _run(cwd: Path, *args: str, env: dict = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, check=False, env=full_env,
    )


def test_concurrent_start_run_calls_do_not_lose_data(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    def _start(_: int) -> subprocess.CompletedProcess:
        return _run(project, "--start-run", "--skill", "deep-research", "--json")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_start, range(8)))

    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    run_ids = {json.loads(r.stdout)["id"] for r in results}
    assert len(run_ids) == 8  # every run got a distinct id, none overwrote another

    runs_yaml = (project / ".research" / "state" / "runs.yaml").read_text()
    for run_id in run_ids:
        assert run_id in runs_yaml  # every run survived the concurrent writes


def test_start_run_times_out_when_runs_yaml_is_held_by_another_process(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    runs_yaml = project / ".research" / "state" / "runs.yaml"
    runs_yaml.parent.mkdir(parents=True)
    runs_yaml.touch()

    fd = os.open(str(runs_yaml), os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        started = time.monotonic()
        result = _run(
            project, "--start-run", "--skill", "deep-research", "--json",
            env={"AGENT_STATE_LOCK_TIMEOUT_SECONDS": "1"},
        )
        elapsed = time.monotonic() - started

        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["error"] == "LockTimeoutError"
        assert elapsed < 5  # bounded by the 1s override, not the 30s default
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
```

- [ ] **Step 2: Run the tests to verify their current status**

Run: `pytest skills/agent-state/scripts/tests/test_state_locking.py -v`
Expected: PASS. Task 1-2 already implemented `_locked_file` with the
`AGENT_STATE_LOCK_TIMEOUT_SECONDS` override, so this task adds no production
code — it exists to give the locking design its own explicit, reviewable
proof, exactly like Task 6 does for index-rebuild correctness. If either
test fails, the bug is in `_locked_file`'s `LOCK_EX | LOCK_NB` retry loop
(Task 1, `state_store.py`) or in how `start_run` picks
`RUNS_RELATIVE_PATH` before acquiring the lock — fix there, not here.

- [ ] **Step 3: Commit**

```bash
git add skills/agent-state/scripts/tests/test_state_locking.py
git commit -m "test(agent-state): prove concurrent writers are serialized, not lost"
```

---

### Task 8: `--report`

**Files:**
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: `state_index.rebuild_index`, `state_index._connect`, `state_index._rows`
  (Task 1).
- Produces: `state.py` CLI: `--report [--since DATE]` (plain text, not JSON —
  the one sanctioned way for a user to see agent activity without opening
  `state/`, `events/`, or `index.db` directly, per the design spec's UX
  boundary).

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_report_lists_runs_with_result_and_claim_counts(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project, skill="deep-research")
    _run(project, "--record-result", "--run-id", run_id, "--summary", "s1", "--json")
    _run(project, "--record-claim", "--run-id", run_id, "--statement", "c1", "--json")
    _run(project, "--complete-run", "--run-id", run_id, "--status", "completed", "--json")

    result = _run(project, "--report")

    assert result.returncode == 0, result.stderr
    assert "1 run(s)" in result.stdout
    assert "deep-research" in result.stdout
    assert run_id in result.stdout
    assert "1 result(s)" in result.stdout
    assert "1 claim(s)" in result.stdout


def test_report_on_empty_project_says_zero_runs(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--report")

    assert result.returncode == 0, result.stderr
    assert "0 run(s)" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v -k report`
Expected: FAIL (`AssertionError: no action selected`).

- [ ] **Step 3: Implement `_report` and wire it in `main()`**

In `skills/agent-state/scripts/state.py`, add before `main`:

```python
def _report(project_root: Path, since: Any = None) -> str:
    """Build the plain-text --report summary.

    Args:
        project_root: The project's root directory.
        since: Optional ISO-8601 date/datetime string; if given, restrict
            to Runs started at or after it.

    Returns:
        A multi-line human-readable summary of Runs, newest first, with
        per-Run Result/Claim counts.
    """
    state_index.rebuild_index(project_root, full=False)
    conn = state_index._connect(project_root)
    try:
        sql = "SELECT * FROM runs"
        params: tuple = ()
        if since:
            sql += " WHERE started_at >= ?"
            params = (since,)
        sql += " ORDER BY started_at DESC"
        runs = state_index._rows(conn, sql, params)

        suffix = f" since {since}" if since else ""
        lines = [f"{len(runs)} run(s){suffix}:"]
        for run in runs:
            result_count = state_index._rows(
                conn, "SELECT COUNT(*) AS n FROM results WHERE run_id = ?", (run["id"],)
            )[0]["n"]
            claim_count = state_index._rows(
                conn, "SELECT COUNT(*) AS n FROM claims WHERE run_id = ?", (run["id"],)
            )[0]["n"]
            lines.append(
                f"  [{run['status']:>9}] {run['skill']} ({run['id']}) "
                f"started {run['started_at']} -- "
                f"{result_count} result(s), {claim_count} claim(s)"
            )
        return "\n".join(lines)
    finally:
        conn.close()
```

Replace `main`'s body with a branch for `--report` before the try/except
covers everything else:

```python
def main() -> None:
    """CLI entry point for state.py."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        project_root = state_store.find_project_root(Path.cwd())

        if args.report:
            print(_report(project_root, since=args.since))
            return

        result = _dispatch(args, project_root)
    except (
        state_store.ProjectRootNotFoundError,
        state_store.StateParseError,
        state_store.QuestionNotFoundError,
        state_store.RunNotFoundError,
        state_store.LockTimeoutError,
        ValueError,
    ) as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 -- stdout must always stay parseable
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)

    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest skills/agent-state/scripts/tests/test_state_cli.py -v`
Expected: PASS (23 tests total).

- [ ] **Step 5: Run the full test suite for the skill**

Run: `pytest skills/agent-state/scripts/tests/ -v`
Expected: PASS (25 tests: 23 in `test_state_cli.py` + 2 in
`test_state_locking.py`).

- [ ] **Step 6: Commit**

```bash
git add skills/agent-state/scripts/state.py skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add --report"
```

---

### Task 9: `SKILL.md`

**Files:**
- Create: `skills/agent-state/SKILL.md`

**Interfaces:**
- Consumes: every CLI verb from Tasks 1-8, to document accurately.

- [ ] **Step 1: Write `SKILL.md`**

Create `skills/agent-state/SKILL.md`:

```markdown
---
name: agent-state
description: Records what the agent does as it drives other skills -- Questions worked on, Runs executed, Results produced, Claims asserted -- in .research/state (canonical, low-frequency) and .research/events (canonical, append-only). Use when a skill wants to track its own execution history instead of writing one file per run, or when a user wants to see what the agent has been doing. Triggers on phrases like "what have you been running", "log this run", "show agent activity".
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Agent State

Stores four cross-skill entities without one file per record: Question and
Run are low-frequency, mutable, and live in id-keyed YAML maps under
`.research/state/`; Result and Claim are immutable facts appended to daily
JSONL shards under `.research/events/`. A SQLite index under
`.research/indexes/` gives fast filtered queries and is rebuilt on demand --
it is never a source of truth and can be deleted at any time.

Full design rationale: `docs/superpowers/specs/2026-08-05-agent-state-storage-design.md`.

This skill has no slash command -- it's infrastructure other skills call
into, the same way `resource-resolver` is. It does not depend on
`resource-resolver` and isn't depended on by it; `--artifact-role`/
`--artifact-path` on `--record-result` are conventionally a resource-resolver
role name and a path relative to it, but this skill never calls `resolve.py`
itself.

## Calling convention

```bash
STATE="$(find ~/.claude -path "*/agent-state/scripts/state.py" | head -1)"

# Start a Run, optionally creating a new Question or linking an existing one
python "$STATE" --start-run --skill deep-research --mode full \
  --question "Does this need offline support?" --json
python "$STATE" --start-run --skill deep-research --question-id q_20260805_ab12cd --json

# Close it out
python "$STATE" --complete-run --run-id run_20260805_9f3a1c --status completed --json

# Record what it produced and asserted along the way
python "$STATE" --record-result --run-id run_20260805_9f3a1c \
  --summary "Found 3 sources" --artifact-role bibliography --artifact-path sources.bib --json
python "$STATE" --record-claim --run-id run_20260805_9f3a1c \
  --statement "Region X diverges from the plan" --confidence high --json

# Close a Question once its Runs have answered it
python "$STATE" --answer-question --question-id q_20260805_ab12cd --json
```

**Every action prints JSON on stdout, including errors** (exit code 1, a
`{"error": ..., "message": ...}` payload) -- never a raw traceback. Check
`error` before trusting any other field, the same rule
`resource-resolver`'s `SKILL.md` states for its own JSON output.

## Querying

```bash
python "$STATE" --query --run-id run_20260805_9f3a1c --json      # run + its results + claims
python "$STATE" --query --question-id q_20260805_ab12cd --json   # question + its runs
python "$STATE" --query --skill deep-research --json             # that skill's runs
python "$STATE" --query --since 2026-08-01 --json                # runs started since then
```

Exactly one filter is required per call. `--query` incrementally syncs the
SQLite index before reading, so results always reflect the latest recorded
state without needing an explicit `--rebuild-index` first.

## User-facing visibility

```bash
python "$STATE" --report                    # everything
python "$STATE" --report --since 2026-08-01
```

`--report` is the one non-JSON, plain-text action -- the sanctioned way for a
user to see what the agent has been doing. Nothing under `.research/state/`,
`.research/events/`, or `.research/indexes/` is meant to be opened or
hand-edited directly; if a user asks what's been happening, run `--report`
instead of reading those files for them.

## Rebuilding the index

```bash
python "$STATE" --rebuild-index --json          # incremental (default via any --query too)
python "$STATE" --rebuild-index --full --json    # full rescan, e.g. after hand-editing state/*.yaml
```

`.research/indexes/index.db` is gitignored and disposable. If it's ever
missing, corrupted, or just looks wrong, `--rebuild-index --full` regenerates
it from `.research/state/*.yaml` and `.research/events/*.jsonl` -- the only
two locations that are ever authoritative.

## Non-goals

- Does not migrate any existing skill (`deep-research`, `research-log`,
  `report-slides`, etc.) to call into this system. Adoption is separate,
  per-skill follow-up work.
- Does not define a retention or pruning policy for `.research/events/` --
  old shards accumulate indefinitely under this design.
- Does not copy artifact content. `--artifact-role`/`--artifact-path` record
  where a Result's output lives; the content itself stays wherever the
  producing skill wrote it.
```

- [ ] **Step 2: Commit**

```bash
git add skills/agent-state/SKILL.md
git commit -m "docs(agent-state): add SKILL.md"
```

---

### Task 10: Register `agent-state` across all distribution channels

**Files:**
- Modify: `install.sh`
- Modify: `install.ps1`
- Modify: `bin/crs.js`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `README.md`
- Modify: `QUICKSTART.md`

**Interfaces:** None (packaging only; no code from earlier tasks is touched).
Mirrors commit `46f6954` ("install resource-resolver via all distribution
channels") and `becee57` ("correct installed skill counts after
resource-resolver became shared") exactly, for the same reason: every other
skill in this repo is reachable through all four install channels, and the
skill counts in the docs must stay in sync with them or the exact bug those
two commits fixed for `resource-resolver` comes right back for `agent-state`.

No automated test covers this (matching the precedent: neither commit added
one). Verification is manual, listed in Step 2.

- [ ] **Step 1: Update all six files**

In `install.sh`, change:

```bash
RESOLVER_SKILLS=("resource-resolver")
```

to:

```bash
# Shared foundation both lab and ARS skills depend on -- always installed
RESOLVER_SKILLS=("resource-resolver" "agent-state")
```

In `install.ps1`, change:

```powershell
$ResolverSkills = @("resource-resolver")
```

to:

```powershell
$ResolverSkills = @("resource-resolver", "agent-state")
```

In `bin/crs.js`, change:

```javascript
const RESOLVER_SKILLS = ['resource-resolver'];
```

to:

```javascript
const RESOLVER_SKILLS = ['resource-resolver', 'agent-state'];
```

and in the same file's `cmdHelp()`, change:

```
8 Claude Code skills for research teams:
  Lab:      /research-log  /report-slides  /mode
  Academic: /ars-full  /ars-plan  /ars-lit-review  /ars-review  and more
  Shared:   resource-resolver (always installed; other skills depend on it)
```

to:

```
9 Claude Code skills for research teams:
  Lab:      /research-log  /report-slides  /mode
  Academic: /ars-full  /ars-plan  /ars-lit-review  /ars-review  and more
  Shared:   resource-resolver, agent-state (always installed foundation)
```

and further down:

```
  crs init                        Install all 8 skills (project-local)
  crs init --global               Install all 8 skills globally
```

to:

```
  crs init                        Install all 9 skills (project-local)
  crs init --global               Install all 9 skills globally
```

In `.claude-plugin/marketplace.json`, add `"./skills/agent-state"` next to
`"./skills/resource-resolver"` in both plugin bundles (`lab-tools` and
`academic-research-skills`):

```json
      "skills": [
        "./skills/resource-resolver",
        "./skills/agent-state",
        "./skills/research-log",
        "./skills/report-slides",
        "./skills/research-mode"
      ]
```

```json
      "skills": [
        "./skills/resource-resolver",
        "./skills/agent-state",
        "./skills/deep-research",
        "./skills/academic-paper",
        "./skills/academic-paper-reviewer",
        "./skills/academic-pipeline"
      ]
```

In `README.md`, change every `8 skills` / `All 8 skills` occurrence to `9`
(lines matching `crs init --global`'s comment and the two table rows), and
add `agent-state` alongside `resource-resolver` in the `--lab-only`/
`--ars-only` table rows:

```
crs init --global          # install all 9 skills globally
```

```
| _(none)_ | All 9 skills (project-local `.claude/skills/`) |
| `--global` | All 9 skills globally (`~/.claude/skills/`) |
| `--lab-only` | `research-log`, `report-slides`, `research-mode` (+ `resource-resolver`, `agent-state`) |
| `--ars-only` | `deep-research`, `academic-paper`, `academic-paper-reviewer`, `academic-pipeline` (+ `resource-resolver`, `agent-state`) |
```

In `QUICKSTART.md`, change:

```
# Install all 8 skills globally (macOS / Linux / Git Bash / WSL)
```

to:

```
# Install all 9 skills globally (macOS / Linux / Git Bash / WSL)
```

- [ ] **Step 2: Manually verify each channel**

Run these from the repo root and confirm the output includes `agent-state`:

```bash
bash -c 'source install.sh; printf "%s\n" "${SKILLS[@]}"'
grep -n "agent-state" install.ps1 bin/crs.js .claude-plugin/marketplace.json README.md QUICKSTART.md
```

Expected: every file shows at least one `agent-state` match; the `install.sh`
sourcing prints `resource-resolver`, `agent-state`, and every lab/ARS skill
name exactly once each.

- [ ] **Step 3: Commit**

```bash
git add install.sh install.ps1 bin/crs.js .claude-plugin/marketplace.json README.md QUICKSTART.md
git commit -m "feat(install): register agent-state across all distribution channels"
```

---

## Self-Review Notes

- **Spec coverage:** Data Classification table -> Task 1-4 (state/ vs
  events/ split); `state/questions.yaml`/`runs.yaml` schemas -> Task 2;
  `events/*.jsonl` schema -> Task 4; `indexes/index.db` rebuild strategy ->
  Task 1 (schema, full rebuild) + Task 5/6 (incremental sync, checkpoint
  correctness); CLI surface -> Tasks 1-5, 8; advisory locking -> Task 1
  (implementation) + Task 7 (proof); `--report` UX boundary -> Task 8;
  report-slides mapping is explicitly illustrative-only in the spec, so no
  task implements it (correctly — the spec's own Non-goals rule this out);
  SKILL.md -> Task 9; installability -> Task 10.
- **Gap found and closed:** the spec's CLI list (design spec, "Components"
  section) never named a way to transition a Question's status, even though
  its own `state/questions.yaml` schema requires `status: open | answered |
  abandoned` to be settable. Task 3 (`--answer-question`/`--abandon-question`)
  closes that gap; it's implied by the committed schema, not a scope addition.
- **Type consistency check:** `record_claim`'s parameter is `evidence_ref`
  (matching the JSONL field name in the spec's `events/` example) while its
  CLI flag stays `--evidence` (matching the spec's own CLI section) — this
  mismatch is intentional and spec-derived, not a typo; called out explicitly
  in Task 4 so an implementer doesn't "fix" it into a naming inconsistency
  the other direction. `RunNotFoundError`/`QuestionNotFoundError` names are
  used identically in `state_store.py` (Task 1 declares them, Tasks 2 and 4
  raise them) and in `state.py`'s `except` tuple (Task 1, never modified
  after). `rebuild_index(project_root, full=...)`'s signature is identical
  everywhere it's called (Task 1's CLI wiring, Task 5's `query`, Task 8's
  `_report`).
