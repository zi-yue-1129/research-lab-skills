#!/usr/bin/env python3
"""Rebuild deterministic journal indexes from entry frontmatter (stdlib only)."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

from journal_common import Metadata, entry_paths, parse_frontmatter, scalar
from journal_milestones import (
    MilestoneDocument,
    MilestoneFormatError,
    read_milestones,
)


@dataclass(frozen=True)
class Entry:
    """Store one entry's filename and parsed metadata for derived views."""

    path: Path
    fields: Metadata


def _problem(
    path: str, severity: str, message: str, line: int | None = None
) -> dict[str, object]:
    """Build a machine-readable source diagnostic."""
    result: dict[str, object] = {
        "path": path,
        "severity": severity,
        "message": message,
    }
    if line is not None:
        result["line"] = line
    return result


def _read_entries(
    directory: Path, max_summary_chars: int
) -> tuple[list[Entry], list[dict[str, object]]]:
    """Read all entries and collect validation problems without hiding bad files."""
    entries: list[Entry] = []
    problems: list[dict[str, object]] = []
    follows_positions: list[tuple[int, Entry]] = []
    paths = entry_paths(directory)
    for path in paths:
        try:
            fields, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            problems.append(_problem(path.name, "error", str(error)))
            continue
        entries.append(Entry(path, fields))
        for key in ("date", "experiment", "summary"):
            if not scalar(fields, key).strip():
                problems.append(
                    _problem(
                        path.name, "error", f"Missing required {key} field"
                    )
                )
        entry_date = scalar(fields, "date")
        if entry_date:
            try:
                if date.fromisoformat(entry_date).isoformat() != entry_date:
                    raise ValueError("Expected YYYY-MM-DD")
            except ValueError:
                problems.append(
                    _problem(path.name, "error", f"Invalid date: {entry_date}")
                )
            prefix = re.match(r"^(\d{4}-\d{2}-\d{2})", path.name)
            if prefix and prefix.group(1) != entry_date:
                problems.append(
                    _problem(
                        path.name,
                        "error",
                        "Frontmatter date differs from filename date prefix",
                    )
                )
        summary = scalar(fields, "summary")
        if "\n" in summary or len(summary) > max_summary_chars:
            problems.append(
                _problem(
                    path.name,
                    "warning",
                    f"summary spans multiple lines or exceeds {max_summary_chars} characters",
                )
            )
        follows_positions.append((len(problems), entries[-1]))
    # Resolve against all parsed entries while keeping source-order diagnostics.
    for position, entry in reversed(follows_positions):
        _, warning = _resolve_follows(scalar(entry.fields, "follows"), entries)
        if warning is not None:
            problems.insert(
                position, _problem(entry.path.name, "warning", warning)
            )
    entries.sort(
        key=lambda entry: (scalar(entry.fields, "date"), entry.path.name),
        reverse=True,
    )
    return entries, problems


def _resolve_follows(
    reference: str, entries: list[Entry]
) -> tuple[Entry | None, str | None]:
    """Resolve filename, stem, then unique experiment slug with explicit warnings."""
    if not reference:
        return None, None
    for entry in entries:
        if entry.path.name == reference:
            return entry, None
    for entry in entries:
        if entry.path.stem == reference:
            return entry, None
    matches = [
        entry
        for entry in entries
        if scalar(entry.fields, "experiment") == reference
    ]
    if len(matches) == 1:
        return matches[0], None
    if matches:
        candidates = ", ".join(sorted(entry.path.name for entry in matches))
        return (
            None,
            f"follows slug is ambiguous: {reference} (matches: {candidates})",
        )
    return None, f"follows target does not exist: {reference}"


def _cell(value: str) -> str:
    """Collapse whitespace and escape table delimiter characters."""
    return " ".join(value.split()).replace("|", "\\|")


def _list_value(fields: Metadata, key: str) -> str:
    """Join an optional metadata string list for a table cell."""
    value = fields.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"Expected list metadata for {key}")
    return ", ".join(value)


def _updated(entries: list[Entry]) -> str:
    """Use the latest valid entry date, keeping rebuilds independent of the clock."""
    valid_dates: list[str] = []
    for entry in entries:
        value = scalar(entry.fields, "date")
        try:
            valid_dates.append(date.fromisoformat(value).isoformat())
        except ValueError:
            continue
    return max(valid_dates, default="—")


def _index(entries: list[Entry], milestone_mode: bool) -> str:
    """Render the documented index columns with an optional Milestone column."""
    columns = ["Date", "Experiment", "Mode", "Tags"]
    rules = ["------", "-----------", "------", "------"]
    if milestone_mode:
        columns.append("Milestone")
        rules.append("-----------")
    columns.extend(["Follows", "HEAD", "Slides"])
    rules.extend(["---------", "------", "--------"])
    lines = [
        "# Research Log Index",
        "",
        f"_Last updated: {_updated(entries)}_",
        "",
        "| " + " | ".join(columns) + " |",
        "|" + "|".join(rules) + "|",
    ]
    for entry in entries:
        fields = entry.fields
        follows = scalar(fields, "follows")
        target, _ = _resolve_follows(follows, entries)
        if target is not None:
            follows = scalar(target.fields, "experiment")
        slides = _list_value(fields, "slide_decks")
        row = [
            scalar(fields, "date") or "—",
            scalar(fields, "experiment") or "—",
            scalar(fields, "mode") or "—",
            _list_value(fields, "tags"),
        ]
        if milestone_mode:
            row.append(scalar(fields, "milestone") or "—")
        row.extend(
            [
                follows or "—",
                scalar(fields, "git_head") or "—",
                "✅ " + slides if slides else "❌",
            ]
        )
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    return "\n".join(lines) + "\n"


def _entry_table(entries: list[Entry], summary_chars: int) -> str:
    """Render newest-first milestone rows with bounded single-line summaries."""
    lines = [
        "| Date | Experiment | Summary |",
        "|------|-----------|---------|",
    ]
    for entry in entries:
        summary = " ".join(scalar(entry.fields, "summary").split())
        if len(summary) > summary_chars:
            summary = summary[: summary_chars - 1] + "…"
        row = [
            scalar(entry.fields, "date") or "—",
            scalar(entry.fields, "experiment") or "—",
            summary,
        ]
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    return "\n".join(lines) + "\n"


def _milestone_outputs(
    entries: list[Entry], document: MilestoneDocument
) -> dict[str, str]:
    """Generate milestone views while preserving only source descriptions and status."""
    lines = ["# Research Milestones"]
    if document.options_comment:
        lines.append(document.options_comment)
    lines.extend(["", f"_Last updated: {_updated(entries)}_", ""])
    outputs: dict[str, str] = {}
    for milestone in document.milestones:
        members = [
            entry
            for entry in entries
            if scalar(entry.fields, "milestone") == milestone.identifier
        ]
        dates = sorted(
            scalar(entry.fields, "date")
            for entry in members
            if scalar(entry.fields, "date")
        )
        first = dates[0] if dates else "—"
        last = (
            "ongoing"
            if milestone.status == "ongoing"
            else dates[-1] if dates else "—"
        )
        heading = f"## {milestone.identifier}: {milestone.title}"
        lines.extend(
            [
                heading,
                milestone.description,
                "",
                f"**Date range:** {first} – {last} · **Status:** {milestone.status}"
                f" · **Entries:** {len(members)}",
                "",
            ]
        )
        table = _entry_table(members, document.summary_chars)
        if document.split_closed and milestone.status == "closed":
            relative = f"milestones/{milestone.identifier}.md"
            outputs[relative] = (
                f"# {milestone.identifier}: {milestone.title}\n\n" + table
            )
            lines.extend([f"[Entries]({relative})", ""])
        else:
            lines.extend([table.rstrip(), ""])
    outputs["MILESTONES.md"] = "\n".join(lines).rstrip() + "\n"
    return outputs


def build(
    directory: Path, check: bool, no_strict: bool, max_summary_chars: int
) -> dict[str, Any]:
    """Validate entries and rebuild or compare all active derived views.

    Args:
        directory: Existing top-level journal directory.
        check: Compare generated content without any filesystem writes.
        no_strict: Allow entry validation errors; structural errors remain fatal.
        max_summary_chars: Warning threshold for source summaries.

    Returns:
        Report with success, written/stale paths, source problems and group counts.
    """
    report: dict[str, Any] = {
        "ok": False,
        "written": [],
        "stale": [],
        "problems": [],
        "milestones": [],
    }
    if not directory.is_dir():
        report["problems"].append(
            _problem(
                str(directory), "error", "Journal directory does not exist"
            )
        )
        return report
    entries, problems = _read_entries(directory, max_summary_chars)
    report["problems"] = problems
    milestone_path = directory / "MILESTONES.md"
    document: MilestoneDocument | None = None
    if milestone_path.exists():
        try:
            document = read_milestones(milestone_path)
            if not milestone_path.read_text(encoding="utf-8").startswith(
                "# Research Milestones\n"
            ):
                raise MilestoneFormatError(
                    "Expected # Research Milestones title", 1
                )
        except (OSError, UnicodeError, ValueError) as error:
            problems.append(
                _problem(
                    "MILESTONES.md",
                    "error",
                    str(error),
                    getattr(error, "line", None),
                )
            )
            return report
        counts = Counter(scalar(entry.fields, "milestone") for entry in entries)
        for milestone in document.milestones:
            count = counts[milestone.identifier]
            report["milestones"].append(
                {
                    "id": milestone.identifier,
                    "status": milestone.status,
                    "entries": count,
                }
            )
            if count == 0:
                problems.append(
                    _problem(
                        "MILESTONES.md",
                        "warning",
                        f"Milestone {milestone.identifier} has no entries",
                    )
                )
    known_ids = (
        {milestone.identifier for milestone in document.milestones}
        if document
        else set()
    )
    for entry in entries:
        identifier = scalar(entry.fields, "milestone")
        if identifier and identifier not in known_ids:
            problems.append(
                _problem(
                    entry.path.name,
                    "error",
                    f"Unknown milestone header: {identifier}",
                )
            )
    outputs = {"INDEX.md": _index(entries, document is not None)}
    if document is not None:
        outputs.update(_milestone_outputs(entries, document))
    for relative, content in outputs.items():
        path = directory / relative
        if not path.is_file() or path.read_bytes() != content.encode("utf-8"):
            report["stale"].append(relative)
    valid = no_strict or not any(
        problem["severity"] == "error" for problem in problems
    )
    if check:
        report["ok"] = valid and not report["stale"]
    elif valid:
        for relative in report["stale"]:
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(outputs[relative].encode("utf-8"))
            report["written"].append(relative)
        report["ok"] = True
    return report


def _warning_group(message: str) -> tuple[str, str]:
    """Separate warning kinds from reference details for concise text output."""
    if message.startswith("follows "):
        kind, _, detail = message.partition(": ")
        return kind, detail
    empty_milestone = re.fullmatch(r"Milestone (M\d+) has no entries", message)
    if empty_milestone is not None:
        return "milestone has no entries", empty_milestone.group(1)
    return message, ""


def _print_problems(problems: list[dict[str, Any]], verbose: bool) -> None:
    """Print every error and either individual or grouped warning diagnostics."""
    groups: dict[str, list[str]] = {}
    for problem in problems:
        if problem["severity"] == "warning" and not verbose:
            kind, detail = _warning_group(problem["message"])
            groups.setdefault(kind, []).append(detail)
            continue
        line = f":{problem['line']}" if "line" in problem else ""
        print(
            f"{problem['path']}{line}: {problem['severity']}: {problem['message']}"
        )
    for kind, details in groups.items():
        references = sorted({detail for detail in details if detail})
        suffix = ": " + "; ".join(references) if references else ""
        unit = "milestones" if kind == "milestone has no entries" else "entries"
        print(f"{len(details)} {unit}: {kind}{suffix}")


def main(arguments: list[str] | None = None) -> int:
    """Run the builder CLI and print a readable or machine-readable report.

    Args:
        arguments: Optional command arguments excluding the executable name.

    Returns:
        Zero on successful rebuild/check; nonzero for stale files or errors.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="List each warning instead of grouping text warnings by kind.",
    )
    parser.add_argument("--no-strict", action="store_true")
    parser.add_argument("--max-summary-chars", type=int, default=300)
    args = parser.parse_args(arguments)
    if args.max_summary_chars < 1:
        parser.error("--max-summary-chars must be positive")
    try:
        report = build(
            args.dir, args.check, args.no_strict, args.max_summary_chars
        )
    except (OSError, UnicodeError, ValueError) as error:
        report = {
            "ok": False,
            "written": [],
            "stale": [],
            "milestones": [],
            "problems": [_problem(str(args.dir), "error", str(error))],
        }
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        _print_problems(report["problems"], args.verbose)
        print(f"Written: {', '.join(report['written']) or 'none'}")
        print(f"Stale: {', '.join(report['stale']) or 'none'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
