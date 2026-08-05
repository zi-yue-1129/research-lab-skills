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
    action.add_argument("--create-project", action="store_true")
    action.add_argument("--create-hypothesis", action="store_true")
    action.add_argument("--set-hypothesis-status", action="store_true")
    action.add_argument("--create-experiment", action="store_true")
    action.add_argument("--set-experiment-status", action="store_true")

    parser.add_argument("--skill", metavar="NAME")
    parser.add_argument("--mode", metavar="MODE")
    parser.add_argument("--name", metavar="TEXT")
    parser.add_argument("--description", metavar="TEXT")
    parser.add_argument("--question", metavar="TEXT")
    parser.add_argument("--question-id", metavar="ID")
    parser.add_argument("--hypothesis-id", metavar="ID")
    parser.add_argument("--experiment-id", metavar="ID")
    parser.add_argument("--run-id", metavar="ID")
    parser.add_argument(
        "--status",
        choices=["completed", "failed", "running", "supported", "refuted", "inconclusive"],
    )
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
    if args.start_run:
        return state_store.start_run(
            project_root, args.skill, mode=args.mode,
            question_id=args.question_id, question_text=args.question,
            hypothesis_id=args.hypothesis_id, experiment_id=args.experiment_id,
        )
    if args.complete_run:
        return state_store.complete_run(project_root, args.run_id, args.status)
    if args.answer_question:
        return state_store.set_question_status(project_root, args.question_id, "answered")
    if args.abandon_question:
        return state_store.set_question_status(project_root, args.question_id, "abandoned")
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
    if args.query:
        return state_index.query(
            project_root, run_id=args.run_id, question_id=args.question_id,
            skill=args.skill, since=args.since,
        )
    if args.rebuild_index:
        return state_index.rebuild_index(project_root, full=args.full)
    if args.create_project:
        return state_store.create_project(
            project_root, args.name,
            description=args.description, created_by=args.skill or "user",
        )
    if args.create_hypothesis:
        return state_store.create_hypothesis(
            project_root, args.question_id, args.statement,
            created_by=args.skill or "user",
        )
    if args.set_hypothesis_status:
        return state_store.set_hypothesis_status(
            project_root, args.hypothesis_id, args.status
        )
    if args.create_experiment:
        return state_store.create_experiment(
            project_root, args.hypothesis_id, args.description,
            created_by=args.skill or "user",
        )
    if args.set_experiment_status:
        return state_store.set_experiment_status(
            project_root, args.experiment_id, args.status
        )
    raise AssertionError("no action selected despite argparse required group")


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
        state_store.HypothesisNotFoundError,
        state_store.ExperimentNotFoundError,
        state_store.RunNotFoundError,
        state_store.LockTimeoutError,
        ValueError,
    ) as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if (args.json and not args.report) else f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 -- stdout must always stay parseable
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if (args.json and not args.report) else f"Error: {exc}")
        sys.exit(1)

    print(json.dumps(result) if args.json else json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
