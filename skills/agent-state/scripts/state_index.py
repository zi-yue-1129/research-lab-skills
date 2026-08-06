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

from state_store import (
    EVENTS_RELATIVE_DIR,
    STATE_SCHEMA_VERSION,
    StateParseError,
    _ensure_research_gitignore,
)

INDEX_RELATIVE_PATH = Path(".research/indexes/index.db")
INDEX_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT, description TEXT, status TEXT,
    created_at TEXT, created_by TEXT
);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, text TEXT, origin_skill TEXT, project_id TEXT,
    status TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY, question_id TEXT, statement TEXT, status TEXT,
    synthetic INTEGER, created_at TEXT, created_by TEXT
);
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY, hypothesis_id TEXT, description TEXT, status TEXT,
    synthetic INTEGER, created_at TEXT, created_by TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, skill TEXT, mode TEXT, question_id TEXT,
    experiment_id TEXT, status TEXT, started_at TEXT, ended_at TEXT
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
CREATE INDEX IF NOT EXISTS idx_questions_project_id ON questions(project_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_question_id ON hypotheses(question_id);
CREATE INDEX IF NOT EXISTS idx_experiments_hypothesis_id ON experiments(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_runs_skill ON runs(skill);
CREATE INDEX IF NOT EXISTS idx_runs_question_id ON runs(question_id);
CREATE INDEX IF NOT EXISTS idx_runs_experiment_id ON runs(experiment_id);
CREATE INDEX IF NOT EXISTS idx_results_run_id ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_claims_run_id ON claims(run_id);
"""


def _fresh_connection(index_path: Path) -> sqlite3.Connection:
    """Delete `index_path` if present and open a freshly schema'd database.

    Used both by genuine-corruption recovery and by schema-version-mismatch
    recovery in `_connect` -- in both cases the right move is the same: this
    file is fully disposable, so throw it away and rebuild rather than
    attempting any in-place repair or migration.

    Args:
        index_path: Path to indexes/index.db.

    Returns:
        A fresh connection with row_factory set, the schema applied, and
        `PRAGMA user_version` stamped to INDEX_SCHEMA_VERSION.
    """
    if index_path.exists():
        index_path.unlink()
    conn = sqlite3.connect(str(index_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}")
    return conn


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

    Separately, this also detects a schema-version mismatch via SQLite's
    built-in `PRAGMA user_version` (an integer stamped into the database
    file itself, exactly designed for this purpose). A database stamped
    with some *other*, non-zero version is treated the same as corruption:
    deleted and rebuilt fresh via `_fresh_connection`, since index.db is
    always fully disposable and rebuildable from state/*.yaml +
    events/*.jsonl -- there is never a need for an in-place migration here,
    only a full reconstruction.

    Version 0 needs a second discriminator, because two very different
    databases both read back 0: a genuinely brand-new file (SQLite's
    default for a database that has never been stamped or written to), and
    an *old pre-versioning* database that predates this stamping and can
    therefore carry an arbitrarily stale table shape. Those two are
    indistinguishable from the version alone, so the table count settles
    it: `SELECT COUNT(*) FROM sqlite_master` is 0 for the genuinely fresh
    file, which falls through to normal schema application and then gets
    stamped, and is non-zero for a database that already has tables, which
    is routed to `_fresh_connection` exactly like any other version
    mismatch. That second case matters: a pre-versioning database whose
    `runs` table lacks `experiment_id` would otherwise reach
    `conn.executescript(_SCHEMA)` and die permanently on `CREATE INDEX ...
    ON runs(experiment_id)` (see the paragraph below), leaving every
    subsequent --query/--report/--rebuild-index failing identically until a
    human deleted index.db by hand. Wiping is always safe here for the same
    reason it is everywhere else in this module: this file is a disposable
    cache, never a source of truth.

    The version check runs BEFORE `_SCHEMA` is applied, not after. Once
    `_SCHEMA` itself started widening already-existing tables (e.g. adding
    `runs.experiment_id` and an index on it), applying it in place against
    an old-shape table can itself raise -- `CREATE INDEX ... ON
    runs(experiment_id)` fails with `sqlite3.OperationalError: no such
    column: experiment_id` when `runs` still has its pre-migration shape,
    since `CREATE TABLE IF NOT EXISTS` silently no-ops on an
    already-existing table rather than adding the missing column. If that
    were left to surface after `conn.executescript(_SCHEMA)`, as before this
    reordering, it would hit the OperationalError handler below -- meant for
    lock contention -- and get re-raised as-is instead of ever reaching the
    version check that should have caught it. Reading `PRAGMA user_version`
    first sidesteps this: a stale version is detected and recovered from
    without ever attempting to apply `_SCHEMA` to the mismatched tables.
    (Reading `PRAGMA user_version` also faithfully reproduces the two
    outcomes it replaces reordering for: on genuine lock contention it likewise
    raises `sqlite3.OperationalError` while another connection holds an
    exclusive transaction, and on corruption ("file is not a database") it
    likewise raises a plain `sqlite3.DatabaseError` -- both verified
    empirically, not assumed.)

    Args:
        project_root: The project's root directory.

    Returns:
        An open connection with row_factory set to sqlite3.Row, guaranteed
        to have the schema successfully applied and `PRAGMA user_version`
        equal to INDEX_SCHEMA_VERSION.

    Raises:
        sqlite3.OperationalError: If the database can't be opened/written to
            due to lock contention (e.g. a concurrent writer holds it).
            Never treated as corruption.
    """
    # This is the single common entry point for every read path (--query,
    # --report, --rebuild-index), so it's also where .research/.gitignore
    # gets bootstrapped for those paths -- mirroring how state_store's
    # _locked_file bootstraps it for every write path. Without this, a
    # project whose very first interaction with this skill is --query/
    # --report/--rebuild-index (no prior --start-run etc.) would get
    # .research/indexes/index.db created before .research/.gitignore
    # exists, contradicting SKILL.md's "bootstraps it on first write" claim.
    _ensure_research_gitignore(project_root)
    index_path = project_root / INDEX_RELATIVE_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(index_path))
    conn.row_factory = sqlite3.Row
    try:
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.OperationalError:
        # Lock contention, not corruption -- must be caught before the
        # broader DatabaseError handler below, since OperationalError IS-A
        # DatabaseError and except clauses are matched in order.
        conn.close()
        raise
    except sqlite3.DatabaseError:
        conn.close()
        return _fresh_connection(index_path)

    if current_version == 0:
        # Ambiguous: either a genuinely brand-new file or a stale
        # pre-versioning database. Existing tables settle it (see docstring).
        try:
            table_count = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        except sqlite3.OperationalError:
            conn.close()
            raise
        except sqlite3.DatabaseError:
            conn.close()
            return _fresh_connection(index_path)
        is_stale = table_count > 0
    else:
        is_stale = current_version != INDEX_SCHEMA_VERSION

    if is_stale:
        # Stale version: don't attempt to apply _SCHEMA to tables whose
        # on-disk shape may not match it (see docstring above).
        conn.close()
        return _fresh_connection(index_path)

    try:
        conn.executescript(_SCHEMA)
    except sqlite3.OperationalError:
        conn.close()
        raise
    except sqlite3.DatabaseError:
        conn.close()
        return _fresh_connection(index_path)

    if current_version == 0:
        conn.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}")
    return conn


def _sync_state_tables(conn: sqlite3.Connection, project_root: Path) -> None:
    """Replace the projects/questions/hypotheses/experiments/runs tables
    with the current YAML contents.

    Args:
        conn: Open connection (schema already applied).
        project_root: The project's root directory.
    """
    # Imported here, not at module scope, so this module never needs
    # state_store's YAML-loading functions except at rebuild time.
    from state_store import (
        DEFAULT_PROJECT_ID,
        EXPERIMENTS_RELATIVE_PATH,
        HYPOTHESES_RELATIVE_PATH,
        PROJECTS_RELATIVE_PATH,
        QUESTIONS_RELATIVE_PATH,
        RUNS_RELATIVE_PATH,
        _load_yaml_map,
    )

    projects = _load_yaml_map(project_root / PROJECTS_RELATIVE_PATH, "projects")
    questions = _load_yaml_map(project_root / QUESTIONS_RELATIVE_PATH, "questions")
    hypotheses = _load_yaml_map(project_root / HYPOTHESES_RELATIVE_PATH, "hypotheses")
    experiments = _load_yaml_map(project_root / EXPERIMENTS_RELATIVE_PATH, "experiments")
    runs = _load_yaml_map(project_root / RUNS_RELATIVE_PATH, "runs")

    conn.execute("DELETE FROM projects")
    if projects:
        conn.executemany(
            "INSERT INTO projects (id, name, description, status, created_at, created_by) "
            "VALUES (:id, :name, :description, :status, :created_at, :created_by)",
            list(projects.values()),
        )
    conn.execute("DELETE FROM questions")
    if questions:
        # Questions written before Task 2 have no "project_id" key at all --
        # default them to DEFAULT_PROJECT_ID, matching create_question's own
        # default, rather than letting the missing key raise a
        # sqlite3.ProgrammingError from executemany's named-parameter binding.
        conn.executemany(
            "INSERT INTO questions "
            "(id, text, origin_skill, project_id, status, created_at, updated_at) "
            "VALUES (:id, :text, :origin_skill, :project_id, :status, :created_at, :updated_at)",
            [{**q, "project_id": q.get("project_id", DEFAULT_PROJECT_ID)} for q in questions.values()],
        )
    conn.execute("DELETE FROM hypotheses")
    if hypotheses:
        conn.executemany(
            "INSERT INTO hypotheses "
            "(id, question_id, statement, status, synthetic, created_at, created_by) "
            "VALUES (:id, :question_id, :statement, :status, :synthetic, :created_at, :created_by)",
            list(hypotheses.values()),
        )
    conn.execute("DELETE FROM experiments")
    if experiments:
        conn.executemany(
            "INSERT INTO experiments "
            "(id, hypothesis_id, description, status, synthetic, created_at, created_by) "
            "VALUES (:id, :hypothesis_id, :description, :status, :synthetic, :created_at, :created_by)",
            list(experiments.values()),
        )
    conn.execute("DELETE FROM runs")
    if runs:
        # Runs written before Task 5 have no "experiment_id" key -- default
        # to None (no ancestry), same reasoning as the questions.project_id
        # default above but with a different fallback value, since a
        # pre-existing standalone Run genuinely has no Experiment to point
        # to (see the design spec's Error Handling section).
        conn.executemany(
            "INSERT INTO runs "
            "(id, skill, mode, question_id, experiment_id, status, started_at, ended_at) "
            "VALUES (:id, :skill, :mode, :question_id, :experiment_id, :status, :started_at, :ended_at)",
            [{**r, "experiment_id": r.get("experiment_id")} for r in runs.values()],
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
        # A missing "schema_version" means this line was written before
        # schema versioning existed -- treat that as version 1, the format
        # it was actually written in, same grandfathering rule state_store's
        # _load_yaml_map applies to state/*.yaml.
        schema_version = event.get("schema_version", 1)
        if schema_version != STATE_SCHEMA_VERSION:
            raise StateParseError(
                f"Unsupported schema_version {schema_version!r} in "
                f"{shard_name}:{line_num} (expected {STATE_SCHEMA_VERSION}): {line}"
            )
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

    A "synthetic" column, if the row shape has one (hypotheses and
    experiments do; questions/runs/results/claims don't), is coerced back to
    a real Python `bool`. SQLite has no boolean type -- it stores these as
    INTEGER 0/1 and hands them back as Python `int` -- so without this
    coercion every --query response would report `"synthetic": 0` where the
    YAML, the --create-hypothesis/--create-experiment responses, and
    SKILL.md's documented shape all say `false`. This is the single
    chokepoint every query branch returning those two entities goes through.

    Args:
        conn: Open connection with row_factory set to sqlite3.Row.
        sql: A SELECT statement with `?` placeholders.
        params: Values to bind to the placeholders.

    Returns:
        Each matching row as a dict.
    """
    rows: List[Dict[str, Any]] = []
    for row in conn.execute(sql, params).fetchall():
        record = dict(row)
        if "synthetic" in record:
            record["synthetic"] = bool(record["synthetic"])
        rows.append(record)
    return rows


def query(
    project_root: Path,
    *,
    run_id: Optional[str] = None,
    question_id: Optional[str] = None,
    project_id: Optional[str] = None,
    hypothesis_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    skill: Optional[str] = None,
    since: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Sync the index incrementally, then return records for exactly one filter.

    Args:
        project_root: The project's root directory.
        run_id: Return this Run plus its Results and Claims.
        question_id: Return this Question plus its Hypotheses and the Runs
            linked to it.
        project_id: Return this Project plus Questions linked to it.
        hypothesis_id: Return this Hypothesis plus Experiments linked to it.
        experiment_id: Return this Experiment plus Runs linked to it.
        skill: Return Runs executed by this skill.
        since: ISO-8601 date/datetime string; return Runs started at or
            after it.

    Returns:
        A dict with whichever result keys are relevant to the filter used,
        each a list of row dicts.

    Raises:
        ValueError: If zero or more than one filter is given.
    """
    filters = [
        f for f in
        (run_id, question_id, project_id, hypothesis_id, experiment_id, skill, since)
        if f is not None
    ]
    if len(filters) != 1:
        raise ValueError(
            "query requires exactly one of "
            "run_id/question_id/project_id/hypothesis_id/experiment_id/skill/since"
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
            # Both children are returned: "hypotheses" completes the
            # Project -> Question -> Hypothesis chain (the middle link was
            # otherwise unwalkable, even though idx_hypotheses_question_id
            # exists for exactly this lookup), and "runs" is kept alongside
            # it since Runs also carry a direct question_id and existing
            # consumers already read that key.
            return {
                "questions": _rows(
                    conn, "SELECT * FROM questions WHERE id = ?", (question_id,)
                ),
                "hypotheses": _rows(
                    conn,
                    "SELECT * FROM hypotheses WHERE question_id = ? ORDER BY created_at",
                    (question_id,),
                ),
                "runs": _rows(
                    conn,
                    "SELECT * FROM runs WHERE question_id = ? ORDER BY started_at",
                    (question_id,),
                ),
            }
        if project_id is not None:
            return {
                "projects": _rows(
                    conn, "SELECT * FROM projects WHERE id = ?", (project_id,)
                ),
                "questions": _rows(
                    conn,
                    "SELECT * FROM questions WHERE project_id = ? ORDER BY created_at",
                    (project_id,),
                ),
            }
        if hypothesis_id is not None:
            return {
                "hypotheses": _rows(
                    conn, "SELECT * FROM hypotheses WHERE id = ?", (hypothesis_id,)
                ),
                "experiments": _rows(
                    conn,
                    "SELECT * FROM experiments WHERE hypothesis_id = ? ORDER BY created_at",
                    (hypothesis_id,),
                ),
            }
        if experiment_id is not None:
            return {
                "experiments": _rows(
                    conn, "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
                ),
                "runs": _rows(
                    conn,
                    "SELECT * FROM runs WHERE experiment_id = ? ORDER BY started_at",
                    (experiment_id,),
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
