"""Subprocess tests for state.py -- Agent State CLI."""
import datetime as _datetime
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


def test_errors_on_unrecognized_event_type(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    events_dir = project / ".research" / "events"
    events_dir.mkdir(parents=True)

    # Create a shard with an unrecognized event type.
    shard_file = events_dir / "2026-08-05.jsonl"
    shard_file.write_text('{"event": "unknown_type", "id": "test_123"}\n')

    result = _run(project, "--rebuild-index", "--json")

    assert result.returncode == 1, result.stderr
    data = json.loads(result.stdout)
    assert data["error"] == "StateParseError"
    assert "unknown_type" in data["message"]
    assert "2026-08-05.jsonl" in data["message"]


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


def test_start_run_creates_research_gitignore(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--start-run", "--skill", "deep-research", "--json")

    _assert_valid_research_gitignore(project)


def test_start_run_does_not_overwrite_existing_gitignore(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir(parents=True)
    gitignore_path = research_dir / ".gitignore"
    gitignore_path.write_text("# custom, do not touch\n")

    _run(project, "--start-run", "--skill", "deep-research", "--json")

    assert gitignore_path.read_text() == "# custom, do not touch\n"


def _assert_valid_research_gitignore(project: Path) -> None:
    """Assert .research/.gitignore exists with the expected ignore patterns.

    Args:
        project: The fake project's root directory.
    """
    gitignore_path = project / ".research" / ".gitignore"
    assert gitignore_path.is_file()
    contents = gitignore_path.read_text()
    assert "state/*.lock" in contents
    assert "events/" in contents
    assert "indexes/" in contents
    assert "cache/" in contents
    assert "*.tmp" in contents


def test_rebuild_index_as_first_ever_action_creates_research_gitignore(tmp_path: Path) -> None:
    # No prior --start-run or any other write -- --rebuild-index is the
    # very first thing this project ever does with the skill. index.db
    # (created by state_index._connect) must not land ungitignored.
    project = _make_project(tmp_path)

    result = _run(project, "--rebuild-index", "--json")

    assert result.returncode == 0, result.stderr
    _assert_valid_research_gitignore(project)


def test_report_as_first_ever_action_creates_research_gitignore(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--report")

    assert result.returncode == 0, result.stderr
    _assert_valid_research_gitignore(project)


def test_query_as_first_ever_action_creates_research_gitignore(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--query", "--skill", "deep-research", "--json")

    assert result.returncode == 0, result.stderr
    _assert_valid_research_gitignore(project)


def test_start_run_without_skill_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--start-run", "--json")

    assert result.returncode == 1, result.stderr
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    assert not (project / ".research" / "state" / "runs.yaml").exists()


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


def test_record_result_without_summary_errors_and_writes_no_event(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)

    result = _run(project, "--record-result", "--run-id", run_id, "--json")

    assert result.returncode == 1, result.stderr
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    # An append-only event log can never be corrected once a null-summary
    # Result is written, so this must fail before any shard file is touched.
    events_dir = project / ".research" / "events"
    assert not events_dir.exists() or not any(events_dir.glob("*.jsonl"))


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


def test_record_claim_without_statement_errors_and_writes_no_event(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)

    result = _run(project, "--record-claim", "--run-id", run_id, "--json")

    assert result.returncode == 1, result.stderr
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    events_dir = project / ".research" / "events"
    assert not events_dir.exists() or not any(events_dir.glob("*.jsonl"))


def test_record_claim_invalid_confidence_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)

    result = _run(
        project, "--record-claim", "--run-id", run_id, "--statement", "x",
        "--confidence", "extreme", "--json",
    )

    assert result.returncode == 2  # argparse rejects choices before we ever see it


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


def test_incremental_rebuild_does_not_reingest_same_lines_twice(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)

    # Manually write a valid result event to today's shard.
    today = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y-%m-%d")
    events_dir = project / ".research" / "events"
    events_dir.mkdir(parents=True)
    shard_file = events_dir / f"{today}.jsonl"

    result_event = {
        "event": "result",
        "id": "result_123",
        "run_id": run_id,
        "summary": "First result",
        "ts": "2026-08-05T10:00:00Z",
    }
    shard_file.write_text(json.dumps(result_event) + "\n")

    _run(project, "--rebuild-index", "--json")  # incremental, picks up result_event

    # Corrupt the first line in place with invalid JSON.
    # This is the key: if checkpoint dedup is broken (always re-ingests from start),
    # the next rebuild will try to parse this corrupted line and fail loudly.
    shard_file.write_text("not valid json at all\n" + json.dumps(result_event) + "\n")

    # Append a second valid claim event.
    claim_event = {
        "event": "claim",
        "id": "claim_456",
        "run_id": run_id,
        "statement": "Second event after corruption",
        "ts": "2026-08-05T10:01:00Z",
    }
    shard_file.write_text(
        "not valid json at all\n" + json.dumps(result_event) + "\n" + json.dumps(claim_event) + "\n"
    )

    # Run rebuild again (incremental). Should succeed because checkpoint skips line 1.
    # If checkpoint logic is broken (always re-ingests from start), this would fail
    # when it tries to parse the corrupted first line.
    result = _run(project, "--rebuild-index", "--json")
    assert result.returncode == 0, f"Rebuild failed (checkpoint dedup likely broken): {result.stderr}"
    data = json.loads(result.stdout)
    assert data["rebuilt"] == "incremental", "Should be incremental rebuild"

    # Query results and claims: should have the one result + the one new claim.
    query_result = _run(project, "--query", "--run-id", run_id, "--json")
    query_data = json.loads(query_result.stdout)
    assert len(query_data["results"]) == 1, "First result should still exist (not duplicated)"
    assert query_data["results"][0]["summary"] == "First result"
    assert len(query_data["claims"]) == 1, "New claim should have been ingested"
    assert query_data["claims"][0]["statement"] == "Second event after corruption"


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

    conn = sqlite3.connect(str(index_db))
    try:
        # The rebuilt database went through the same _fresh_connection path
        # as a schema-version mismatch, so it must also come out re-stamped.
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()


def test_query_recovers_from_corrupted_index(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)
    _run(project, "--record-result", "--run-id", run_id, "--summary", "s1", "--json")

    index_db = project / ".research" / "indexes" / "index.db"
    index_db.parent.mkdir(parents=True, exist_ok=True)
    index_db.write_bytes(b"not a sqlite db")

    # --query only ever does an incremental (full=False) sync internally --
    # the design spec says a corrupted index self-heals transparently on
    # --query regardless, with no --full/--rebuild-index required by the user.
    result = _run(project, "--query", "--run-id", run_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["runs"][0]["id"] == run_id
    assert data["results"][0]["summary"] == "s1"


def test_report_recovers_from_corrupted_index(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project, skill="deep-research")
    _run(project, "--record-result", "--run-id", run_id, "--summary", "s1", "--json")

    index_db = project / ".research" / "indexes" / "index.db"
    index_db.parent.mkdir(parents=True, exist_ok=True)
    index_db.write_bytes(b"not a sqlite db")

    result = _run(project, "--report")

    assert result.returncode == 0, result.stderr
    assert "1 run(s)" in result.stdout
    assert run_id in result.stdout
    assert "1 result(s)" in result.stdout


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


def test_report_with_json_flag_outside_git_prints_plain_text_error(tmp_path: Path) -> None:
    no_git_dir = tmp_path / "not_a_project"
    no_git_dir.mkdir()

    # This test's premise -- "no .git anywhere in the ancestry" -- only holds
    # if nothing above tmp_path happens to contain a .git entry. /tmp is
    # shared with other processes on this machine, so skip rather than
    # assert a false positive if that premise doesn't hold here.
    for candidate in (no_git_dir, *no_git_dir.parents):
        if (candidate / ".git").exists():
            pytest.skip("A .git directory exists above tmp_path on this machine")

    result = _run(no_git_dir, "--report", "--json")

    assert result.returncode == 1
    # --report always prints plain text, even with --json flag
    assert not result.stdout.startswith("{")
    assert "Error:" in result.stdout


def test_start_run_writes_schema_version_to_runs_yaml(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _start_run(project)

    runs_yaml = yaml.safe_load(
        (project / ".research" / "state" / "runs.yaml").read_text()
    )
    assert runs_yaml["version"] == 1


def test_start_run_with_question_writes_schema_version_to_questions_yaml(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)

    _create_question(project)

    questions_yaml = yaml.safe_load(
        (project / ".research" / "state" / "questions.yaml").read_text()
    )
    assert questions_yaml["version"] == 1


def test_record_result_includes_schema_version_in_returned_event(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project)

    result = _run(
        project, "--record-result", "--run-id", run_id, "--summary", "s", "--json"
    )

    data = json.loads(result.stdout)
    assert data["schema_version"] == 1


def test_load_yaml_map_rejects_mismatched_schema_version(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    runs_yaml_path = project / ".research" / "state" / "runs.yaml"
    runs_yaml_path.parent.mkdir(parents=True)
    runs_yaml_path.write_text(yaml.safe_dump({"version": 2, "runs": {}}))

    result = _run(project, "--start-run", "--skill", "deep-research", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "StateParseError"
    assert "unsupported schema version" in data["message"]


def test_load_yaml_map_accepts_missing_version_for_backward_compat(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    runs_yaml_path = project / ".research" / "state" / "runs.yaml"
    runs_yaml_path.parent.mkdir(parents=True)
    # No "version" key at all -- exactly what agent-state wrote before
    # schema versioning existed.
    runs_yaml_path.write_text(yaml.safe_dump({"runs": {}}))

    result = _run(project, "--start-run", "--skill", "deep-research", "--json")

    assert result.returncode == 0, result.stderr


def test_ingest_shard_rejects_mismatched_schema_version(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    today = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y-%m-%d")
    events_dir = project / ".research" / "events"
    events_dir.mkdir(parents=True)
    bad_event = {
        "event": "result", "id": "res_x", "run_id": "run_x", "summary": "s",
        "artifact_ref": None, "ts": "2026-08-05T00:00:00Z", "schema_version": 2,
    }
    (events_dir / f"{today}.jsonl").write_text(json.dumps(bad_event) + "\n")

    result = _run(project, "--rebuild-index", "--full", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "StateParseError"
    assert "schema_version" in data["message"]


def test_ingest_shard_accepts_missing_schema_version_for_backward_compat(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)
    today = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y-%m-%d")
    events_dir = project / ".research" / "events"
    events_dir.mkdir(parents=True)
    # No "schema_version" key -- exactly what agent-state wrote before
    # schema versioning existed.
    old_event = {
        "event": "claim", "id": "clm_x", "run_id": "run_x", "statement": "s",
        "confidence": None, "evidence_ref": None, "ts": "2026-08-05T00:00:00Z",
    }
    (events_dir / f"{today}.jsonl").write_text(json.dumps(old_event) + "\n")

    result = _run(project, "--rebuild-index", "--full", "--json")

    assert result.returncode == 0, result.stderr


def test_connect_stamps_fresh_database_with_user_version(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--rebuild-index", "--json")

    conn = sqlite3.connect(str(project / ".research" / "indexes" / "index.db"))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()


def test_connect_recovers_from_mismatched_user_version(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run_id = _start_run(project, skill="deep-research")
    _run(project, "--rebuild-index", "--full", "--json")

    index_db = project / ".research" / "indexes" / "index.db"
    conn = sqlite3.connect(str(index_db))
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()

    result = _run(project, "--query", "--run-id", run_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["runs"][0]["id"] == run_id  # data survived the wipe+rebuild

    conn = sqlite3.connect(str(index_db))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()


def test_create_project_returns_active_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-project", "--name", "Offline Support Initiative", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["name"] == "Offline Support Initiative"
    assert data["description"] is None
    assert data["status"] == "active"
    assert data["created_by"] == "user"
    assert data["id"].startswith("proj_")


def test_create_project_with_description_and_skill(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-project", "--name", "Offline Support Initiative",
        "--description", "Investigate offline usage patterns.",
        "--skill", "deep-research", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["description"] == "Investigate offline usage patterns."
    assert data["created_by"] == "deep-research"


def test_create_project_without_name_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-project", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_start_run_with_question_defaults_to_default_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--start-run", "--skill", "research-mode", "--question", "Q?", "--json")

    questions_yaml = (project / ".research" / "state" / "questions.yaml").read_text()
    assert "project_id: proj_default" in questions_yaml
    projects_yaml = (project / ".research" / "state" / "projects.yaml").read_text()
    assert "proj_default" in projects_yaml
    assert "Default Project" in projects_yaml


def test_default_project_is_created_lazily_only_once(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--start-run", "--skill", "research-mode", "--question", "Q1?", "--json")
    _run(project, "--start-run", "--skill", "research-mode", "--question", "Q2?", "--json")

    doc = yaml.safe_load((project / ".research" / "state" / "projects.yaml").read_text())
    assert list(doc["projects"].keys()) == ["proj_default"]


def _create_question_id(project: Path, text: str = "Needs offline support?") -> str:
    result = _run(
        project, "--start-run", "--skill", "research-mode", "--question", text, "--json"
    )
    return json.loads(result.stdout)["question_id"]


def test_create_hypothesis_returns_proposed_hypothesis(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)

    result = _run(
        project, "--create-hypothesis", "--question-id", question_id,
        "--statement", "Offline support is unnecessary.",
        "--skill", "deep-research", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["question_id"] == question_id
    assert data["statement"] == "Offline support is unnecessary."
    assert data["status"] == "proposed"
    assert data["synthetic"] is False
    assert data["created_by"] == "deep-research"
    assert data["id"].startswith("hyp_")


def test_create_hypothesis_without_statement_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)

    result = _run(project, "--create-hypothesis", "--question-id", question_id, "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_hypothesis_unknown_question_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-hypothesis", "--question-id", "q_missing",
        "--statement", "x", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "QuestionNotFoundError"


def test_set_hypothesis_status_updates_status(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = json.loads(
        _run(
            project, "--create-hypothesis", "--question-id", question_id,
            "--statement", "x", "--json",
        ).stdout
    )["id"]

    result = _run(
        project, "--set-hypothesis-status", "--hypothesis-id", hypothesis_id,
        "--status", "supported", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "supported"


def test_set_hypothesis_status_unknown_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--set-hypothesis-status", "--hypothesis-id", "hyp_missing",
        "--status", "refuted", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "HypothesisNotFoundError"


def _create_hypothesis_id(project: Path, question_id: str, statement: str = "H1") -> str:
    result = _run(
        project, "--create-hypothesis", "--question-id", question_id,
        "--statement", statement, "--json",
    )
    return json.loads(result.stdout)["id"]


def test_create_experiment_returns_planned_experiment(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)

    result = _run(
        project, "--create-experiment", "--hypothesis-id", hypothesis_id,
        "--description", "Survey production traffic logs.",
        "--skill", "deep-research", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["hypothesis_id"] == hypothesis_id
    assert data["description"] == "Survey production traffic logs."
    assert data["status"] == "planned"
    assert data["synthetic"] is False
    assert data["created_by"] == "deep-research"
    assert data["id"].startswith("exp_")


def test_create_experiment_without_description_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)

    result = _run(project, "--create-experiment", "--hypothesis-id", hypothesis_id, "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_experiment_unknown_hypothesis_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-experiment", "--hypothesis-id", "hyp_missing",
        "--description", "x", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "HypothesisNotFoundError"


def test_set_experiment_status_updates_status(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    experiment_id = json.loads(
        _run(
            project, "--create-experiment", "--hypothesis-id", hypothesis_id,
            "--description", "x", "--json",
        ).stdout
    )["id"]

    result = _run(
        project, "--set-experiment-status", "--experiment-id", experiment_id,
        "--status", "running", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "running"


def test_set_experiment_status_unknown_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--set-experiment-status", "--experiment-id", "exp_missing",
        "--status", "completed", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ExperimentNotFoundError"


def test_start_run_without_any_level_stays_fully_standalone(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--start-run", "--skill", "deep-research", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["question_id"] is None
    assert data["experiment_id"] is None
    assert not (project / ".research" / "state" / "hypotheses.yaml").exists()
    assert not (project / ".research" / "state" / "experiments.yaml").exists()


def test_start_run_with_question_creates_synthetic_hypothesis_and_experiment(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--question", "Does this need offline support?", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["question_id"].startswith("q_")
    assert data["experiment_id"].startswith("exp_")

    hyp_doc = yaml.safe_load(
        (project / ".research" / "state" / "hypotheses.yaml").read_text()
    )
    assert len(hyp_doc["hypotheses"]) == 1
    hypothesis = next(iter(hyp_doc["hypotheses"].values()))
    assert hypothesis["question_id"] == data["question_id"]
    assert hypothesis["synthetic"] is True

    exp_doc = yaml.safe_load(
        (project / ".research" / "state" / "experiments.yaml").read_text()
    )
    experiment = exp_doc["experiments"][data["experiment_id"]]
    assert experiment["hypothesis_id"] == hypothesis["id"]
    assert experiment["synthetic"] is True


def test_start_run_with_hypothesis_id_creates_synthetic_experiment(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--hypothesis-id", hypothesis_id, "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["experiment_id"].startswith("exp_")
    assert data["question_id"] == question_id

    exp_doc = yaml.safe_load(
        (project / ".research" / "state" / "experiments.yaml").read_text()
    )
    experiment = exp_doc["experiments"][data["experiment_id"]]
    assert experiment["hypothesis_id"] == hypothesis_id
    assert experiment["synthetic"] is True


def test_start_run_with_unknown_hypothesis_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--hypothesis-id", "hyp_missing", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "HypothesisNotFoundError"


def test_start_run_with_experiment_id_links_directly(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    # _create_question_id itself goes through --start-run --question, which
    # (per Branch 3) auto-creates its own synthetic Hypothesis+Experiment --
    # so the experiment count baseline below is taken after setup, not at 0.
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    experiment_id = json.loads(
        _run(
            project, "--create-experiment", "--hypothesis-id", hypothesis_id,
            "--description", "E1", "--json",
        ).stdout
    )["id"]
    experiment_count_before = len(
        yaml.safe_load(
            (project / ".research" / "state" / "experiments.yaml").read_text()
        )["experiments"]
    )

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--experiment-id", experiment_id, "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["experiment_id"] == experiment_id
    assert data["question_id"] == question_id

    exp_doc = yaml.safe_load(
        (project / ".research" / "state" / "experiments.yaml").read_text()
    )
    # no extra synthetic experiment created by the --start-run call itself
    assert len(exp_doc["experiments"]) == experiment_count_before


def test_start_run_with_unknown_experiment_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--experiment-id", "exp_missing", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ExperimentNotFoundError"


def test_query_by_project_id_returns_project_and_questions(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    started = json.loads(
        _run(project, "--start-run", "--skill", "research-mode", "--question", "Q?", "--json").stdout
    )

    result = _run(project, "--query", "--project-id", "proj_default", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["projects"][0]["id"] == "proj_default"
    assert data["questions"][0]["id"] == started["question_id"]


def test_query_by_hypothesis_id_returns_hypothesis_and_experiments(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    experiment_id = json.loads(
        _run(
            project, "--create-experiment", "--hypothesis-id", hypothesis_id,
            "--description", "E1", "--json",
        ).stdout
    )["id"]

    result = _run(project, "--query", "--hypothesis-id", hypothesis_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["hypotheses"][0]["id"] == hypothesis_id
    assert data["experiments"][0]["id"] == experiment_id


def test_query_by_experiment_id_returns_experiment_and_runs(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    started = json.loads(
        _run(
            project, "--start-run", "--skill", "deep-research",
            "--hypothesis-id", hypothesis_id, "--json",
        ).stdout
    )

    result = _run(project, "--query", "--experiment-id", started["experiment_id"], "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["experiments"][0]["id"] == started["experiment_id"]
    assert data["runs"][0]["id"] == started["id"]


def test_query_requires_exactly_one_filter_still_rejects_zero_and_many(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    zero = _run(project, "--query", "--json")
    many = _run(
        project, "--query", "--project-id", "proj_default",
        "--hypothesis-id", "hyp_x", "--json",
    )

    assert zero.returncode == 1
    assert json.loads(zero.stdout)["error"] == "ValueError"
    assert many.returncode == 1
    assert json.loads(many.stdout)["error"] == "ValueError"


def test_index_rebuild_recovers_from_pre_experiment_id_schema(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--start-run", "--skill", "deep-research", "--json")
    index_path = project / ".research" / "indexes" / "index.db"
    # --start-run alone never touches indexes/index.db -- only --query,
    # --report, and --rebuild-index do. Build it once on the current
    # (post-Task-6) schema first, so the hand-edit below has a real file to
    # downgrade rather than failing to open a nonexistent one.
    _run(project, "--rebuild-index", "--json")

    # Simulate an index.db built before this task's runs.experiment_id
    # column existed: drop it back to schema version 1 with the old runs
    # table shape.
    conn = sqlite3.connect(str(index_path))
    conn.execute("PRAGMA user_version = 1")
    conn.execute("DROP TABLE runs")
    conn.execute(
        "CREATE TABLE runs (id TEXT PRIMARY KEY, skill TEXT, mode TEXT, "
        "question_id TEXT, status TEXT, started_at TEXT, ended_at TEXT)"
    )
    conn.commit()
    conn.close()

    result = _run(project, "--rebuild-index", "--json")

    assert result.returncode == 0, result.stderr
    conn = sqlite3.connect(str(index_path))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    assert "experiment_id" in columns
    conn.close()


def test_index_rebuild_recovers_from_unversioned_pre_experiment_id_schema(
    tmp_path: Path,
) -> None:
    # Distinct from the test above: that one covers user_version == 1, an
    # index stamped by a *later* build. This one covers user_version == 0 --
    # a database from before user_version stamping existed at all, which is
    # indistinguishable from a brand-new file by version alone and so used
    # to fall straight through to executescript(_SCHEMA), dying permanently
    # on CREATE INDEX ... ON runs(experiment_id).
    project = _make_project(tmp_path)
    _run(project, "--start-run", "--skill", "deep-research", "--json")
    index_path = project / ".research" / "indexes" / "index.db"
    _run(project, "--rebuild-index", "--json")

    conn = sqlite3.connect(str(index_path))
    conn.execute("PRAGMA user_version = 0")
    conn.execute("DROP TABLE runs")
    conn.execute(
        "CREATE TABLE runs (id TEXT PRIMARY KEY, skill TEXT, mode TEXT, "
        "question_id TEXT, status TEXT, started_at TEXT, ended_at TEXT)"
    )
    conn.commit()
    conn.close()

    result = _run(project, "--rebuild-index", "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    conn = sqlite3.connect(str(index_path))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
        assert "experiment_id" in columns
    finally:
        conn.close()


def test_start_run_rejects_experiment_id_combined_with_question_text(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    experiment_id = json.loads(
        _run(
            project, "--create-experiment", "--hypothesis-id", hypothesis_id,
            "--description", "E1", "--json",
        ).stdout
    )["id"]
    questions_before = yaml.safe_load(
        (project / ".research" / "state" / "questions.yaml").read_text()
    )["questions"]

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--question", "This text would have been silently discarded",
        "--experiment-id", experiment_id, "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    assert "mutually exclusive" in data["message"]
    # The discarded-Question scenario the error exists to prevent: nothing
    # was created from the ignored --question text.
    questions_after = yaml.safe_load(
        (project / ".research" / "state" / "questions.yaml").read_text()
    )["questions"]
    assert questions_after.keys() == questions_before.keys()


def test_start_run_rejects_hypothesis_id_combined_with_question_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--question-id", question_id, "--hypothesis-id", hypothesis_id, "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    assert "mutually exclusive" in data["message"]


def test_start_run_with_project_id_puts_new_question_in_that_project(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)
    project_id = json.loads(
        _run(project, "--create-project", "--name", "Offline Support", "--json").stdout
    )["id"]

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--question", "Does this need offline support?",
        "--project-id", project_id, "--json",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    started = json.loads(result.stdout)
    doc = yaml.safe_load(
        (project / ".research" / "state" / "questions.yaml").read_text()
    )
    assert doc["questions"][started["question_id"]]["project_id"] == project_id
    assert project_id != "proj_default"


def test_query_returns_synthetic_as_a_json_boolean(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    _run(
        project, "--create-experiment", "--hypothesis-id", hypothesis_id,
        "--description", "E1", "--json",
    )

    result = _run(project, "--query", "--hypothesis-id", hypothesis_id, "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    # `0 is False` is False in Python, so this discriminates a real bool
    # from the int SQLite would otherwise hand back.
    assert data["hypotheses"][0]["synthetic"] is False
    assert data["experiments"][0]["synthetic"] is False


def test_start_run_with_experiment_pointing_at_missing_hypothesis_errors(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)
    started = json.loads(
        _run(
            project, "--start-run", "--skill", "deep-research", "--question", "Q?", "--json"
        ).stdout
    )
    experiment_id = started["experiment_id"]
    experiments_path = project / ".research" / "state" / "experiments.yaml"
    doc = yaml.safe_load(experiments_path.read_text())
    doc["experiments"][experiment_id]["hypothesis_id"] = "hyp_does_not_exist"
    experiments_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(
        project, "--start-run", "--skill", "deep-research",
        "--experiment-id", experiment_id, "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "HypothesisNotFoundError"
    assert "hyp_does_not_exist" in data["message"]


def test_query_by_question_id_returns_its_hypotheses(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(
        project, question_id, statement="Offline support is unnecessary."
    )

    result = _run(project, "--query", "--question-id", question_id, "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["questions"][0]["id"] == question_id
    assert hypothesis_id in {h["id"] for h in data["hypotheses"]}
    # the pre-existing "runs" key is still there alongside the new one
    assert "runs" in data


def test_validate_detects_dangling_run_experiment_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    question_id = _create_question_id(project)
    hypothesis_id = _create_hypothesis_id(project, question_id)
    experiment_id = json.loads(
        _run(
            project, "--create-experiment", "--hypothesis-id", hypothesis_id,
            "--description", "E1", "--json",
        ).stdout
    )["id"]
    started = json.loads(
        _run(
            project, "--start-run", "--skill", "deep-research",
            "--experiment-id", experiment_id, "--json",
        ).stdout
    )
    runs_path = project / ".research" / "state" / "runs.yaml"
    doc = yaml.safe_load(runs_path.read_text())
    doc["runs"][started["id"]]["experiment_id"] = "exp_does_not_exist"
    runs_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {
        "entity": "run", "id": started["id"],
        "field": "experiment_id", "missing_id": "exp_does_not_exist",
    } in data["violations"]


def test_validate_on_clean_project_reports_no_violations(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--start-run", "--skill", "deep-research", "--question", "Q?", "--json")

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"violations": [], "clean": True}


def test_validate_detects_dangling_hypothesis_question_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--start-run", "--skill", "deep-research", "--question", "Q?", "--json")
    hypotheses_path = project / ".research" / "state" / "hypotheses.yaml"
    doc = yaml.safe_load(hypotheses_path.read_text())
    only_hypothesis = next(iter(doc["hypotheses"].values()))
    only_hypothesis["question_id"] = "q_does_not_exist"
    hypotheses_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert data["violations"] == [{
        "entity": "hypothesis", "id": only_hypothesis["id"],
        "field": "question_id", "missing_id": "q_does_not_exist",
    }]


def test_validate_detects_dangling_experiment_hypothesis_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--start-run", "--skill", "deep-research", "--question", "Q?", "--json")
    experiments_path = project / ".research" / "state" / "experiments.yaml"
    doc = yaml.safe_load(experiments_path.read_text())
    only_experiment = next(iter(doc["experiments"].values()))
    only_experiment["hypothesis_id"] = "hyp_does_not_exist"
    experiments_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {
        "entity": "experiment", "id": only_experiment["id"],
        "field": "hypothesis_id", "missing_id": "hyp_does_not_exist",
    } in data["violations"]


def test_validate_detects_dangling_question_project_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    started = json.loads(
        _run(project, "--start-run", "--skill", "deep-research", "--question", "Q?", "--json").stdout
    )
    questions_path = project / ".research" / "state" / "questions.yaml"
    doc = yaml.safe_load(questions_path.read_text())
    doc["questions"][started["question_id"]]["project_id"] = "proj_does_not_exist"
    questions_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {
        "entity": "question", "id": started["question_id"],
        "field": "project_id", "missing_id": "proj_does_not_exist",
    } in data["violations"]


def test_create_question_returns_open_question(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-question", "--question", "Does this need offline support?",
        "--skill", "research-project-init", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["text"] == "Does this need offline support?"
    assert data["origin_skill"] == "research-project-init"
    assert data["project_id"] == "proj_default"
    assert data["status"] == "open"
    assert data["id"].startswith("q_")


def test_create_question_without_skill_defaults_to_user(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-question", "--question", "Q?", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["origin_skill"] == "user"


def test_create_question_with_explicit_project_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    created = _run(project, "--create-project", "--name", "Offline Support Initiative", "--json")
    project_id = json.loads(created.stdout)["id"]

    result = _run(
        project, "--create-question", "--question", "Does this need offline support?",
        "--skill", "research-project-init", "--project-id", project_id, "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["project_id"] == project_id


def test_create_question_unknown_project_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-question", "--question", "Q?",
        "--project-id", "proj_missing", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProjectNotFoundError"


def test_create_question_without_question_text_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-question", "--skill", "research-project-init", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_question_does_not_create_a_run(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(
        project, "--create-question", "--question", "Does this need offline support?",
        "--skill", "research-project-init", "--json",
    )

    assert not (project / ".research" / "state" / "runs.yaml").exists()


def test_create_source_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-source", "--title", "Offline-First Mobile UX Patterns",
        "--authors", "Ng T, Osei K", "--year", "2025", "--doi", "10.1000/xyz123",
        "--venue", "Journal of Mobile Computing", "--skill", "bibliography_agent", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("src_")
    assert data["title"] == "Offline-First Mobile UX Patterns"
    assert data["doi"] == "10.1000/xyz123"
    assert data["screening_status"] == "pending"
    assert data["exclusion_reason"] is None
    assert data["created_by"] == "bibliography_agent"
    assert data["duplicate_hint"] is None
    assert data["project_id"] == "proj_default"


def test_create_source_without_title_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-source", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_source_with_unknown_project_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-source", "--title", "Some Title",
        "--project-id", "proj_does_not_exist", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProjectNotFoundError"


def test_create_source_deduplicates_by_exact_doi(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    first = json.loads(_run(
        project, "--create-source", "--title", "First Title",
        "--doi", "10.1000/same-doi", "--json",
    ).stdout)

    second = json.loads(_run(
        project, "--create-source", "--title", "Different Title Entirely",
        "--doi", "10.1000/same-doi", "--json",
    ).stdout)

    assert second["id"] == first["id"]
    assert second["title"] == "First Title"
    sources_yaml = (project / ".research" / "state" / "sources.yaml").read_text()
    assert sources_yaml.count("id: src_") == 1


def test_create_source_deduplicates_by_normalized_url(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    first = json.loads(_run(
        project, "--create-source", "--title", "A Title",
        "--url", "https://example.com/paper?utm_source=x", "--json",
    ).stdout)

    second = json.loads(_run(
        project, "--create-source", "--title", "A Title",
        "--url", "http://example.com/paper/", "--json",
    ).stdout)

    assert second["id"] == first["id"]


def test_create_source_does_not_deduplicate_urls_differing_by_document_id(
    tmp_path: Path,
) -> None:
    project = _make_project(tmp_path)
    first = json.loads(_run(
        project, "--create-source", "--title", "First PLOS Paper",
        "--url",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0111111",
        "--json",
    ).stdout)

    second = json.loads(_run(
        project, "--create-source", "--title", "Second PLOS Paper",
        "--url",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0222222",
        "--json",
    ).stdout)

    assert second["id"] != first["id"]
    sources_yaml = (project / ".research" / "state" / "sources.yaml").read_text()
    assert sources_yaml.count("id: src_") == 2


def test_create_source_surfaces_duplicate_hint_without_merging(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    first = json.loads(_run(
        project, "--create-source", "--title", "Offline Caching Patterns",
        "--authors", "Ng T", "--year", "2025", "--json",
    ).stdout)

    second = json.loads(_run(
        project, "--create-source", "--title", "Offline Caching Patterns",
        "--authors", "Ng T", "--year", "2025", "--json",
    ).stdout)

    assert second["id"] != first["id"]
    assert second["duplicate_hint"] == {
        "source_id": first["id"], "reason": "title+author+year match",
    }
    sources_yaml = (project / ".research" / "state" / "sources.yaml").read_text()
    assert sources_yaml.count("id: src_") == 2


def test_set_source_screening_records_status_and_reason(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)

    result = _run(
        project, "--set-source-screening", "--source-id", source["id"],
        "--screening-status", "excluded", "--exclusion-reason", "Predatory journal", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["screening_status"] == "excluded"
    assert data["exclusion_reason"] == "Predatory journal"


def test_set_source_screening_invalid_status_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)

    result = _run(
        project, "--set-source-screening", "--source-id", source["id"],
        "--screening-status", "maybe", "--json",
    )

    assert result.returncode == 2  # argparse rejects the choice before dispatch


def test_set_source_screening_unknown_source_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--set-source-screening", "--source-id", "src_does_not_exist",
        "--screening-status", "included", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SourceNotFoundError"


def test_set_source_evidence_tier_updates_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)

    result = _run(
        project, "--set-source-evidence-tier", "--source-id", source["id"],
        "--evidence-tier", "Level II - Randomized Controlled Trial", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["evidence_tier"] == "Level II - Randomized Controlled Trial"


def test_set_source_evidence_tier_without_value_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)

    result = _run(
        project, "--set-source-evidence-tier", "--source-id", source["id"], "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def _make_source_and_question(project: Path) -> tuple:
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)
    question = json.loads(_run(
        project, "--create-question", "--question", "Does X help Y?", "--json",
    ).stdout)
    return source["id"], question["id"]


def test_create_evidence_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id,
        "--statement", "Offline caching reduced reported friction by 40%",
        "--stance", "supports", "--limitations", "Single-region sample",
        "--skill", "synthesis_agent", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("evd_")
    assert data["source_id"] == source_id
    assert data["question_id"] == question_id
    assert data["hypothesis_id"] is None
    assert data["stance"] == "supports"
    assert data["limitations"] == "Single-region sample"
    assert data["uncertainty_note"] is None
    assert data["created_by"] == "synthesis_agent"


def test_create_evidence_with_hypothesis_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    hypothesis = json.loads(_run(
        project, "--create-hypothesis", "--question-id", question_id,
        "--statement", "X helps Y", "--json",
    ).stdout)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--hypothesis-id", hypothesis["id"],
        "--statement", "A finding", "--stance", "refutes", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["hypothesis_id"] == hypothesis["id"]
    assert data["stance"] == "refutes"


def test_create_evidence_without_statement_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--stance", "mixed", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_evidence_invalid_stance_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "neutral", "--json",
    )

    assert result.returncode == 2  # argparse rejects the choice before dispatch


def test_create_evidence_unknown_source_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", "src_does_not_exist",
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SourceNotFoundError"


def test_create_evidence_unknown_question_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, _ = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", "q_does_not_exist", "--statement", "A finding",
        "--stance", "supports", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "QuestionNotFoundError"


def test_create_evidence_unknown_hypothesis_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--hypothesis-id", "hyp_does_not_exist",
        "--statement", "A finding", "--stance", "supports", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "HypothesisNotFoundError"


def test_record_claim_with_evidence_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    ).stdout)
    run = json.loads(_run(
        project, "--start-run", "--skill", "deep-research", "--json",
    ).stdout)

    result = _run(
        project, "--record-claim", "--run-id", run["id"],
        "--statement", "Ship offline caching for v2", "--confidence", "high",
        "--evidence-id", evidence["id"], "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["evidence_id"] == evidence["id"]


def test_record_claim_with_unknown_evidence_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run = json.loads(_run(
        project, "--start-run", "--skill", "deep-research", "--json",
    ).stdout)

    result = _run(
        project, "--record-claim", "--run-id", run["id"],
        "--statement", "A claim", "--evidence-id", "evd_does_not_exist", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "EvidenceNotFoundError"


def test_validate_catches_dangling_source_project_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(project, "--create-source", "--title", "T", "--json").stdout)
    sources_path = project / ".research" / "state" / "sources.yaml"
    data = yaml.safe_load(sources_path.read_text())
    data["sources"][source["id"]]["project_id"] = "proj_does_not_exist"
    sources_path.write_text(yaml.safe_dump(data))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {
        "entity": "source", "id": source["id"],
        "field": "project_id", "missing_id": "proj_does_not_exist",
    } in data["violations"]


def test_validate_catches_dangling_evidence_foreign_keys(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    hypothesis = json.loads(_run(
        project, "--create-hypothesis", "--question-id", question_id,
        "--statement", "X helps Y", "--json",
    ).stdout)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--hypothesis-id", hypothesis["id"],
        "--statement", "A finding", "--stance", "supports", "--json",
    ).stdout)
    evidence_path = project / ".research" / "state" / "evidence.yaml"
    data = yaml.safe_load(evidence_path.read_text())
    data["evidence"][evidence["id"]]["source_id"] = "src_does_not_exist"
    data["evidence"][evidence["id"]]["question_id"] = "q_does_not_exist"
    data["evidence"][evidence["id"]]["hypothesis_id"] = "hyp_does_not_exist"
    evidence_path.write_text(yaml.safe_dump(data))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {
        "entity": "evidence", "id": evidence["id"],
        "field": "source_id", "missing_id": "src_does_not_exist",
    } in data["violations"]
    assert {
        "entity": "evidence", "id": evidence["id"],
        "field": "question_id", "missing_id": "q_does_not_exist",
    } in data["violations"]
    assert {
        "entity": "evidence", "id": evidence["id"],
        "field": "hypothesis_id", "missing_id": "hyp_does_not_exist",
    } in data["violations"]


def test_query_source_id_returns_source_and_its_evidence(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    ).stdout)

    result = _run(project, "--query", "--source-id", source_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["sources"][0]["id"] == source_id
    assert [e["id"] for e in data["evidence"]] == [evidence["id"]]


def test_query_question_id_includes_linked_evidence(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    ).stdout)

    result = _run(project, "--query", "--question-id", question_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert [e["id"] for e in data["evidence"]] == [evidence["id"]]


def test_query_claims_include_evidence_id_column(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    ).stdout)
    run = json.loads(_run(project, "--start-run", "--skill", "deep-research", "--json").stdout)
    _run(
        project, "--record-claim", "--run-id", run["id"], "--statement", "A claim",
        "--evidence-id", evidence["id"], "--json",
    )

    result = _run(project, "--query", "--run-id", run["id"], "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["claims"][0]["evidence_id"] == evidence["id"]


def test_rebuild_index_full_picks_up_sources_and_evidence(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    )

    result = _run(project, "--rebuild-index", "--full", "--json")

    assert result.returncode == 0, result.stderr
    conn = sqlite3.connect(str(project / ".research" / "indexes" / "index.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    finally:
        conn.close()


def test_index_schema_version_is_stamped_as_3(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--rebuild-index", "--json")

    conn = sqlite3.connect(str(project / ".research" / "indexes" / "index.db"))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()
