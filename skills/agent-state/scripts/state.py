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
    if args.start_run:
        return state_store.start_run(
            project_root, args.skill, mode=args.mode,
            question_id=args.question_id, question_text=args.question,
        )
    if args.complete_run:
        return state_store.complete_run(project_root, args.run_id, args.status)
    if args.answer_question:
        return state_store.set_question_status(project_root, args.question_id, "answered")
    if args.abandon_question:
        return state_store.set_question_status(project_root, args.question_id, "abandoned")
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
