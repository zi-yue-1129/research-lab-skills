#!/usr/bin/env python3
"""state.py -- Agent State CLI for the Project/Question/Hypothesis/Experiment/
Run/Result/Claim research chain.

Usage:
    python state.py --create-project --name "..." [--description "..."] \
        [--skill NAME] [--json]

    python state.py --create-question --question "..." [--skill NAME] \
        [--project-id PROJ_ID] [--json]

    python state.py --start-run --skill NAME [--mode MODE] \
        [--question "..." [--project-id PROJ_ID] | --question-id Q_ID \
         | --hypothesis-id HYP_ID | --experiment-id EXP_ID] [--json]
        (at most one chain level; --project-id only applies to --question)
    python state.py --complete-run --run-id RUN_ID --status completed|failed [--json]

    python state.py --answer-question --question-id Q_ID [--json]
    python state.py --abandon-question --question-id Q_ID [--json]

    python state.py --create-hypothesis --question-id Q_ID --statement "..." \
        [--skill NAME] [--json]
    python state.py --set-hypothesis-status --hypothesis-id HYP_ID \
        --status supported|refuted|inconclusive [--json]

    python state.py --create-experiment --hypothesis-id HYP_ID --description "..." \
        [--skill NAME] [--json]
    python state.py --set-experiment-status --experiment-id EXP_ID \
        --status running|completed|failed [--json]

    python state.py --create-source --title "..." [--authors "..."] [--year YEAR] \
        [--doi "..."] [--url "..."] [--venue "..."] [--evidence-tier "..."] \
        [--project-id PROJ_ID] [--skill NAME] [--json]
    python state.py --set-source-screening --source-id SRC_ID \
        --screening-status included|excluded|pending [--exclusion-reason "..."] [--json]
    python state.py --set-source-evidence-tier --source-id SRC_ID \
        --evidence-tier "..." [--json]

    python state.py --create-evidence --source-id SRC_ID --question-id Q_ID \
        [--hypothesis-id HYP_ID] --statement "..." --stance supports|refutes|mixed \
        [--limitations "..."] [--uncertainty-note "..."] [--skill NAME] [--json]

    python state.py --record-result --run-id RUN_ID --summary "..." \
        [--artifact-role ROLE --artifact-path PATH] [--json]
    python state.py --record-claim --run-id RUN_ID --statement "..." \
        [--confidence low|medium|high] [--evidence "..."] [--evidence-id EVD_ID] [--json]

    python state.py --query (--run-id ID | --question-id ID | --project-id ID \
        | --hypothesis-id ID | --experiment-id ID | --skill NAME | --since DATE) [--json]
        (exactly one filter; each returns the named record plus its children)
    python state.py --validate [--json]
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
        description=(
            "Agent State: record and query the research chain -- Project, "
            "Question, Hypothesis, Experiment, Run, Result, and Claim -- "
            "plus referential-integrity validation (--validate) and the "
            "rebuildable SQLite query index (--query/--report/--rebuild-index)."
        )
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
    action.add_argument("--create-question", action="store_true")
    action.add_argument("--create-hypothesis", action="store_true")
    action.add_argument("--set-hypothesis-status", action="store_true")
    action.add_argument("--create-experiment", action="store_true")
    action.add_argument("--set-experiment-status", action="store_true")
    action.add_argument("--create-source", action="store_true")
    action.add_argument("--set-source-screening", action="store_true")
    action.add_argument("--set-source-evidence-tier", action="store_true")
    action.add_argument("--create-evidence", action="store_true")
    action.add_argument("--validate", action="store_true")

    parser.add_argument("--skill", metavar="NAME")
    parser.add_argument("--mode", metavar="MODE")
    parser.add_argument("--name", metavar="TEXT")
    parser.add_argument("--description", metavar="TEXT")
    parser.add_argument("--title", metavar="TEXT")
    parser.add_argument("--authors", metavar="TEXT")
    parser.add_argument("--year", type=int, metavar="YEAR")
    parser.add_argument("--doi", metavar="TEXT")
    parser.add_argument("--url", metavar="TEXT")
    parser.add_argument("--venue", metavar="TEXT")
    parser.add_argument("--evidence-tier", metavar="TEXT")
    parser.add_argument(
        "--screening-status", choices=["included", "excluded", "pending"]
    )
    parser.add_argument("--exclusion-reason", metavar="TEXT")
    parser.add_argument("--stance", choices=["supports", "refutes", "mixed"])
    parser.add_argument("--limitations", metavar="TEXT")
    parser.add_argument("--uncertainty-note", metavar="TEXT")
    parser.add_argument("--evidence-id", metavar="ID")
    parser.add_argument("--question", metavar="TEXT")
    parser.add_argument("--question-id", metavar="ID")
    parser.add_argument("--project-id", metavar="ID")
    parser.add_argument("--hypothesis-id", metavar="ID")
    parser.add_argument("--experiment-id", metavar="ID")
    parser.add_argument("--source-id", metavar="ID")
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
            project_id=args.project_id,
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
            evidence_id=args.evidence_id,
        )
    if args.query:
        return state_index.query(
            project_root, run_id=args.run_id, question_id=args.question_id,
            project_id=args.project_id, hypothesis_id=args.hypothesis_id,
            experiment_id=args.experiment_id, skill=args.skill, since=args.since,
        )
    if args.rebuild_index:
        return state_index.rebuild_index(project_root, full=args.full)
    if args.create_project:
        return state_store.create_project(
            project_root, args.name,
            description=args.description, created_by=args.skill or "user",
        )
    if args.create_question:
        return state_store.create_question(
            project_root, args.question, args.skill or "user",
            project_id=args.project_id,
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
    if args.create_source:
        return state_store.create_source(
            project_root, args.title,
            authors=args.authors, year=args.year, doi=args.doi, url=args.url,
            venue=args.venue, evidence_tier=args.evidence_tier,
            project_id=args.project_id, created_by=args.skill or "user",
        )
    if args.set_source_screening:
        return state_store.set_source_screening(
            project_root, args.source_id, args.screening_status,
            exclusion_reason=args.exclusion_reason,
        )
    if args.set_source_evidence_tier:
        return state_store.set_source_evidence_tier(
            project_root, args.source_id, args.evidence_tier,
        )
    if args.create_evidence:
        return state_store.create_evidence(
            project_root, args.source_id, args.question_id, args.statement,
            args.stance, hypothesis_id=args.hypothesis_id,
            limitations=args.limitations, uncertainty_note=args.uncertainty_note,
            created_by=args.skill or "user",
        )
    if args.validate:
        violations = state_store.validate_referential_integrity(project_root)
        return {"violations": violations, "clean": len(violations) == 0}
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
        state_store.SourceNotFoundError,
        state_store.EvidenceNotFoundError,
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
