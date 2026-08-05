"""Subprocess tests for state.py -- Agent State CLI."""
import datetime as _datetime
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
