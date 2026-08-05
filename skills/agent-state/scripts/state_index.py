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

from state_store import EVENTS_RELATIVE_DIR, StateParseError

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

    Corruption recovery is unconditional here: if the existing index.db file
    is not a valid SQLite database (or fails to accept the schema), it is
    deleted and recreated fresh, regardless of whether the caller wanted a
    "full" or "incremental" rebuild. Those two concepts are independent --
    `full` (see rebuild_index) is about whether to re-ingest
    already-checkpointed JSONL lines from source, a purely logical concept.
    Corruption is a physical fact about the on-disk file, and per the design
    spec ("indexes/index.db missing or corrupted ... is expected, not an
    error condition"), it must self-heal on ANY read/write path that opens
    the index -- including the incremental syncs that --query and --report
    perform on every call -- not just when --rebuild-index --full happened
    to already be requested.

    Corruption recovery must NOT trigger on lock contention, though.
    `sqlite3.OperationalError` (e.g. "database is locked", raised when a
    concurrent writer holds a transaction on index.db) is a *subclass* of
    `sqlite3.DatabaseError` in Python's sqlite3 module. If it were caught by
    the same handler as genuine corruption, a reader colliding with a
    concurrent writer would delete a perfectly healthy index.db out from
    under that writer's in-flight transaction -- a false-positive
    "corruption recovery" triggered by ordinary, transient lock contention,
    in exactly the concurrent-usage scenario (background jobs, worktrees)
    this design cares about most. So `OperationalError` is caught first and
    re-raised as-is: it's a real, transient condition the caller/user should
    see and can retry, not something to paper over by deleting the
    disposable cache. Only a `DatabaseError` that is NOT also an
    `OperationalError` (e.g. "file is not a database") is treated as actual
    corruption and triggers delete-and-recreate.

    Args:
        project_root: The project's root directory.

    Returns:
        An open connection with row_factory set to sqlite3.Row, guaranteed
        to have the schema successfully applied.

    Raises:
        sqlite3.OperationalError: If the database can't be opened/written to
            due to lock contention (e.g. a concurrent writer holds it).
            Never treated as corruption.
    """
    index_path = project_root / INDEX_RELATIVE_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(index_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
    except sqlite3.OperationalError:
        # Lock contention, not corruption -- must be caught before the
        # broader DatabaseError handler below, since OperationalError IS-A
        # DatabaseError and except clauses are matched in order.
        conn.close()
        raise
    except sqlite3.DatabaseError:
        conn.close()
        # Delete the corrupted file and retry once with a fresh database.
        index_path.unlink()
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
    for line_num, line in enumerate(lines[already_ingested:], start=already_ingested + 1):
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
        else:
            raise StateParseError(
                f"Unrecognized event type '{event.get('event')}' in {shard_name}:{line_num}: {line}"
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
    index_path = project_root / INDEX_RELATIVE_PATH
    # Detect if this is the first rebuild: database doesn't exist yet.
    is_first_rebuild = not index_path.exists()

    # _connect self-heals from a corrupted index.db unconditionally (see its
    # docstring), independent of whether `full` was requested here.
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

        # A rebuild is "full" if --full was passed OR if this is the first rebuild.
        is_full_rebuild = full or is_first_rebuild
        return {
            "rebuilt": "full" if is_full_rebuild else "incremental",
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
