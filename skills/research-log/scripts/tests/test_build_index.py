"""Test deterministic frontmatter-derived journal views and validation."""

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "build_index.py"


def _run(directory: Path, *arguments: str) -> tuple[int, dict[str, Any]]:
    """Run the builder and return its machine-readable report."""
    assert SCRIPT.is_file(), "Missing build_index.py feature"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dir",
            str(directory),
            "--json",
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def _entry(
    directory: Path,
    name: str = "2026-01-02_run.md",
    extra: str = "",
    summary: str = "Measured.",
) -> None:
    """Write a valid entry with caller-supplied extra frontmatter."""
    (directory / name).write_text(
        f"---\ndate: {name[:10]}\nexperiment: {name[11:-3]}\nsummary: {summary}\n{extra}---\n"
        "## Results\nBody never belongs in a table.\n",
        encoding="utf-8",
    )


def _milestones(
    directory: Path, options: str = "", status: str = "ongoing"
) -> None:
    """Write source headers plus an intentionally corrupted derived table."""
    (directory / "MILESTONES.md").write_text(
        "# Research Milestones\n" + options + "\n_Last updated: old_\n\n"
        "## M2: Current measurements\nFirst description.\n\nSecond paragraph.\n"
        f"**Date range:** obsolete · **Status:** {status}\n"
        "| corrupted | ---\ndate: 1999-01-01\n## Results\nwhole log body |\n"
        "## M1: Earlier measurements\nRetain this description.\n"
        "**Date range:** obsolete · **Status:** closed\nold table\n",
        encoding="utf-8",
    )


def test_flat_index_exact_format_and_check_without_writes(
    tmp_path: Path,
) -> None:
    """Preserve documented columns and build only the flat index without milestones."""
    _entry(
        tmp_path,
        extra="mode: exp\ntags: [training, ablation]\ngit_head: abc123\nslide_decks: [reports/deck]\nfollows: 2026-01-01_prior.md\n",
    )
    _entry(tmp_path, "2026-01-01_prior.md")
    (tmp_path / "STATE.md").write_text("Invalid entry", encoding="utf-8")
    (tmp_path / "directory.md").mkdir()
    nested = tmp_path / "archive"
    nested.mkdir()
    (nested / "bad.md").write_text("not an entry", encoding="utf-8")
    status, report = _run(tmp_path, "--check")
    assert status != 0
    assert report["stale"] == ["INDEX.md"]
    assert not (tmp_path / "INDEX.md").exists()
    status, report = _run(tmp_path)
    assert status == 0, report
    assert report["written"] == ["INDEX.md"]
    index = tmp_path / "INDEX.md"
    assert index.read_text(encoding="utf-8") == (
        "# Research Log Index\n\n_Last updated: 2026-01-02_\n\n"
        "| Date | Experiment | Mode | Tags | Follows | HEAD | Slides |\n"
        "|------|-----------|------|------|---------|------|--------|\n"
        "| 2026-01-02 | run | exp | training, ablation | prior | abc123 | ✅ reports/deck |\n"
        "| 2026-01-01 | prior | — |  | — | — | ❌ |\n"
    )
    assert not (tmp_path / "MILESTONES.md").exists()
    before = index.stat().st_mtime_ns
    status, report = _run(tmp_path, "--check")
    assert status == 0, report
    assert report["written"] == report["stale"] == []
    assert index.stat().st_mtime_ns == before
    index.write_text("stale", encoding="utf-8")
    status, report = _run(tmp_path, "--check")
    assert status != 0
    assert index.read_text(encoding="utf-8") == "stale"


def test_milestone_repair_preserves_sources_and_sorts_entries(
    tmp_path: Path,
) -> None:
    """Discard corrupt derived text, retain descriptions/status, and warn on empty groups."""
    _milestones(tmp_path)
    _entry(tmp_path, extra="milestone: M2\n", summary='"A | result measured."')
    _entry(tmp_path, "2026-01-01_old.md", extra="milestone: M2\n")
    status, report = _run(tmp_path)
    assert status == 0, report
    assert report["milestones"] == [
        {"id": "M2", "status": "ongoing", "entries": 2},
        {"id": "M1", "status": "closed", "entries": 0},
    ]
    assert any(
        problem["severity"] == "warning" and "M1" in problem["message"]
        for problem in report["problems"]
    )
    text = (tmp_path / "MILESTONES.md").read_text(encoding="utf-8")
    assert (
        "## M2: Current measurements\nFirst description.\n\nSecond paragraph.\n"
        in text
    )
    assert "**Date range:** 2026-01-01 – ongoing · **Status:** ongoing" in text
    assert "**Entries:** 2" in text
    assert "A \\| result measured." in text
    assert "corrupted" not in text and "whole log body" not in text
    assert text.index("| 2026-01-02 |") < text.index("| 2026-01-01 |")
    assert "## M1: Earlier measurements" in text
    index = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
    assert (
        "| Date | Experiment | Mode | Tags | Milestone | Follows | HEAD | Slides |"
        in index
    )
    snapshots = {path.name: path.read_bytes() for path in tmp_path.glob("*.md")}
    status, report = _run(tmp_path, "--check")
    assert status == 0, report
    assert snapshots == {
        path.name: path.read_bytes() for path in tmp_path.glob("*.md")
    }


def test_split_closed_options_and_summary_truncation(tmp_path: Path) -> None:
    """Split closed tables with working relative links and bounded single-line cells."""
    options = "<!-- research-log: summary_chars=20 split_closed=true -->\n"
    _milestones(tmp_path, options, status="closed")
    _entry(
        tmp_path,
        extra="milestone: M2\n",
        summary="|\n  First long measurement\n  continued after wrapping.",
    )
    status, report = _run(tmp_path)
    assert status == 0, report
    text = (tmp_path / "MILESTONES.md").read_text(encoding="utf-8")
    assert text.splitlines()[1] == options.strip()
    assert "milestones/M2.md" in text
    assert "| Date |" not in text
    split = tmp_path / "milestones" / "M2.md"
    table = split.read_text(encoding="utf-8")
    assert "| First long measurem… |" in table
    assert "Body never" not in table and "continued" not in table
    assert "**Date range:** 2026-01-02 – 2026-01-02" in text
    assert any(
        problem["severity"] == "warning" for problem in report["problems"]
    )
    status, report = _run(tmp_path, "--check")
    assert status == 0, report
    split.write_text("stale", encoding="utf-8")
    status, report = _run(tmp_path, "--check")
    assert status != 0
    assert "milestones/M2.md" in report["stale"]


@pytest.mark.parametrize(
    "option", ["unknown=1", "summary_chars=0", "split_closed=perhaps"]
)
def test_invalid_options_are_explicit(tmp_path: Path, option: str) -> None:
    """Reject unknown keys and invalid journal options without writing files."""
    _milestones(tmp_path, f"<!-- research-log: {option} -->\n")
    status, report = _run(tmp_path)
    assert status != 0
    assert any(problem["severity"] == "error" for problem in report["problems"])
    assert not (tmp_path / "INDEX.md").exists()


def test_invalid_description_heading_reports_source_line(
    tmp_path: Path,
) -> None:
    """Reject non-milestone level-two headings before the derived boundary."""
    path = tmp_path / "MILESTONES.md"
    path.write_text(
        "# Research Milestones\n\n## M1: Title\nDescription\n## Unexpected\n"
        "**Date range:** old · **Status:** ongoing\n",
        encoding="utf-8",
    )
    status, report = _run(tmp_path, "--check")
    assert status != 0
    assert any(
        problem["path"] == "MILESTONES.md" and problem["line"] == 5
        for problem in report["problems"]
    )


@pytest.mark.parametrize("field", ["date", "experiment", "summary"])
def test_missing_required_fields_are_errors(tmp_path: Path, field: str) -> None:
    """Report each missing field per entry and never write in strict mode."""
    _entry(tmp_path)
    path = tmp_path / "2026-01-02_run.md"
    path.write_text(
        "\n".join(
            line
            for line in path.read_text(encoding="utf-8").split("\n")
            if not line.startswith(field + ":")
        ),
        encoding="utf-8",
    )
    status, report = _run(tmp_path)
    assert status != 0
    assert any(
        problem["path"] == path.name
        and field in problem["message"]
        and problem["severity"] == "error"
        for problem in report["problems"]
    )
    assert not (tmp_path / "INDEX.md").exists()
    status, report = _run(tmp_path, "--no-strict")
    assert status == 0, report
    assert (tmp_path / "INDEX.md").exists()


def test_date_mismatch_unknown_milestone_and_warning_validation(
    tmp_path: Path,
) -> None:
    """Differentiate invalid metadata from legacy summary/follows warnings."""
    _milestones(tmp_path)
    _entry(
        tmp_path, extra="milestone: M99\nfollows: absent.md\n", summary="x" * 40
    )
    path = tmp_path / "2026-01-02_run.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "date: 2026-01-02", "date: 2026-01-03"
        ),
        encoding="utf-8",
    )
    status, report = _run(tmp_path, "--max-summary-chars", "30")
    assert status != 0
    errors = [
        problem["message"]
        for problem in report["problems"]
        if problem["severity"] == "error"
    ]
    warnings = [
        problem["message"]
        for problem in report["problems"]
        if problem["severity"] == "warning"
    ]
    assert any(
        "date" in message and "filename" in message for message in errors
    )
    assert any("M99" in message for message in errors)
    assert any("summary" in message for message in warnings)
    assert any("follows" in message for message in warnings)


def test_common_frontmatter_lists_and_multiline_summary(tmp_path: Path) -> None:
    """Support ordinary block lists and preserve multiline summary warnings."""
    _entry(
        tmp_path,
        extra="tags:\n- baseline\n- 'arm, control'\nslide_decks:\n- reports/deck\n",
        summary='"Wrapped\n  summary sentence."',
    )
    status, report = _run(tmp_path)
    assert status == 0, report
    text = (tmp_path / "INDEX.md").read_text(encoding="utf-8")
    assert "| baseline, arm, control |" in text
    assert "✅ reports/deck" in text
    assert any(
        problem["severity"] == "warning" and "summary" in problem["message"]
        for problem in report["problems"]
    )


def test_split_ongoing_inline_and_ignore_options_in_corrupt_body(
    tmp_path: Path,
) -> None:
    """Keep ongoing rows inline while discarding all corrupted derived body text."""
    _milestones(tmp_path, "<!-- research-log: split_closed=true -->\n")
    path = tmp_path / "MILESTONES.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "whole log body |",
            "whole log body |\n<!-- research-log: invalid=1 -->",
        ),
        encoding="utf-8",
    )
    _entry(tmp_path, extra="milestone: M2\n")
    status, report = _run(tmp_path)
    assert status == 0, report
    text = path.read_text(encoding="utf-8")
    assert "| 2026-01-02 | run | Measured. |" in text
    assert "milestones/M1.md" in text
    assert not (tmp_path / "milestones/M2.md").exists()
    assert "invalid=1" not in text


def test_milestone_reference_requires_a_header_even_without_mode(
    tmp_path: Path,
) -> None:
    """Reject orphaned milestone IDs rather than silently hiding them in a flat index."""
    _entry(tmp_path, extra="milestone: M9\n")
    status, report = _run(tmp_path, "--check")
    assert status != 0
    assert any(
        problem["path"] == "2026-01-02_run.md"
        and "M9" in problem["message"]
        and problem["severity"] == "error"
        for problem in report["problems"]
    )


def test_quoted_flow_list_items_keep_commas_and_apostrophes(
    tmp_path: Path,
) -> None:
    """Keep valid quoted list items intact instead of splitting their commas."""
    _entry(tmp_path, extra="tags: ['arm, control', 'observer''s check']\n")
    status, report = _run(tmp_path)
    assert status == 0, report
    assert "| arm, control, observer's check |" in (
        tmp_path / "INDEX.md"
    ).read_text(encoding="utf-8")


def test_scalar_trailing_whitespace_is_not_metadata(tmp_path: Path) -> None:
    """Ignore whitespace outside plain and quoted scalar values."""
    _entry(tmp_path)
    path = tmp_path / "2026-01-02_run.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "date: 2026-01-02", 'date: "2026-01-02"  '
        ),
        encoding="utf-8",
    )
    status, report = _run(tmp_path)
    assert status == 0, report


@pytest.mark.parametrize("combined", [False, True])
def test_round2_layout_separates_description_and_combines_metadata(
    tmp_path: Path, combined: bool
) -> None:
    """Read both layouts and rebuild one blank separator without accumulating it."""
    source = tmp_path / "MILESTONES.md"
    suffix = " · **Entries:** 99" if combined else "\n**Entries:** 99"
    source.write_text(
        "# Research Milestones\n\n## M1: Measurements\n"
        "First paragraph.\n\nFinal paragraph.\n\n\n"
        "**Date range:** obsolete · **Status:** closed" + suffix + "\n",
        encoding="utf-8",
    )
    _entry(tmp_path, extra="milestone: M1\n")
    status, report = _run(tmp_path)
    assert status == 0, report
    expected = (
        "Final paragraph.\n\n"
        "**Date range:** 2026-01-02 – 2026-01-02 · **Status:** closed"
        " · **Entries:** 1\n\n"
    )
    rendered = source.read_bytes()
    assert expected in rendered.decode("utf-8")
    assert "Final paragraph.\n\n\n" not in rendered.decode("utf-8")
    status, rebuilt = _run(tmp_path)
    assert status == 0, rebuilt
    assert rebuilt["written"] == []
    assert source.read_bytes() == rendered
    status, checked = _run(tmp_path, "--check")
    assert status == 0, checked


@pytest.mark.parametrize(
    "reference,resolved",
    [
        ("2026-01-01_target.md", "resolved-target"),
        ("2026-01-01_target", "resolved-target"),
        ("legacy-slug", "legacy-slug"),
    ],
)
def test_round2_follows_forms_and_precedence(
    tmp_path: Path, reference: str, resolved: str
) -> None:
    """Resolve filename before stem before unique slug, without false warnings."""
    for name, experiment in (
        ("target", "resolved-target"),
        ("filename-collision", "2026-01-01_target.md"),
        ("stem-collision", "2026-01-01_target"),
        ("slug-target", "legacy-slug"),
    ):
        filename = f"2026-01-01_{name}.md"
        _entry(tmp_path, filename)
        path = tmp_path / filename
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                f"experiment: {name}\n", f"experiment: {experiment}\n"
            ),
            encoding="utf-8",
        )
    _entry(tmp_path, extra=f"follows: {reference}\n")
    status, report = _run(tmp_path)
    assert status == 0, report
    assert report["problems"] == []
    rows = (tmp_path / "INDEX.md").read_text(encoding="utf-8").splitlines()
    row = next(line for line in rows if line.startswith("| 2026-01-02 |"))
    assert [cell.strip() for cell in row.split("|")[1:-1]][4] == resolved


def test_round2_follows_distinguishes_missing_and_ambiguous_slugs(
    tmp_path: Path,
) -> None:
    """Name ambiguous slugs and their candidate files separately from missing targets."""
    for name in ("first", "second"):
        filename = f"2026-01-01_{name}.md"
        _entry(tmp_path, filename)
        path = tmp_path / filename
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                f"experiment: {name}\n", "experiment: duplicate\n"
            ),
            encoding="utf-8",
        )
    _entry(tmp_path, extra="follows: duplicate\n")
    _entry(tmp_path, "2026-01-03_missing.md", extra="follows: absent\n")
    status, report = _run(tmp_path)
    assert status == 0, report
    assert len(report["problems"]) == 2
    by_path = {problem["path"]: problem for problem in report["problems"]}
    ambiguous = by_path["2026-01-02_run.md"]
    assert ambiguous["severity"] == "warning"
    assert "follows slug is ambiguous: duplicate" in ambiguous["message"]
    assert "2026-01-01_first.md" in ambiguous["message"]
    assert "2026-01-01_second.md" in ambiguous["message"]
    assert by_path["2026-01-03_missing.md"]["message"] == (
        "follows target does not exist: absent"
    )


def _run_text(
    directory: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    """Run the builder's human-readable CLI without suppressing diagnostics."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--dir", str(directory), *arguments],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_round2_warning_output_groups_kinds_and_retains_json(
    tmp_path: Path,
) -> None:
    """Keep per-entry JSON while grouping summary and missing-target text warnings."""
    for day in range(1, 4):
        _entry(tmp_path, f"2026-01-0{day}_run.md", summary="x" * 301)
    for day in range(4, 6):
        _entry(
            tmp_path, f"2026-01-0{day}_run.md", extra=f"follows: absent-{day}\n"
        )
    result = _run_text(tmp_path, "--check")
    assert result.returncode == 1
    lines = result.stdout.splitlines()
    summary_lines = [line for line in lines if "summary spans" in line]
    assert summary_lines == [
        "3 entries: summary spans multiple lines or exceeds 300 characters"
    ]
    follows_lines = [line for line in lines if "follows target" in line]
    assert len(follows_lines) == 1
    assert follows_lines[0].startswith(
        "2 entries: follows target does not exist"
    )
    assert "absent-4" in follows_lines[0] and "absent-5" in follows_lines[0]
    verbose = _run_text(tmp_path, "--check", "--verbose")
    assert verbose.returncode == 1
    warnings = [
        line for line in verbose.stdout.splitlines() if ": warning:" in line
    ]
    assert len(warnings) == 5
    assert all(
        any(f"2026-01-0{day}_run.md" in line for line in warnings)
        for day in range(1, 6)
    )
    status, normal_json = _run(tmp_path, "--check")
    assert status == 1
    status, verbose_json = _run(tmp_path, "--check", "--verbose")
    assert status == 1
    assert normal_json == verbose_json
    assert len(normal_json["problems"]) == 5
    assert all(
        problem["severity"] == "warning" for problem in normal_json["problems"]
    )


def test_round2_warning_output_keeps_errors_individual(tmp_path: Path) -> None:
    """Group warnings without hiding any individual entry error."""
    for day in (1, 2):
        filename = f"2026-01-0{day}_run.md"
        _entry(tmp_path, filename, summary="x" * 301)
        path = tmp_path / filename
        path.write_text(
            path.read_text(encoding="utf-8").replace("experiment: run\n", ""),
            encoding="utf-8",
        )
    result = _run_text(tmp_path)
    assert result.returncode == 1
    error_lines = [
        line for line in result.stdout.splitlines() if ": error:" in line
    ]
    assert error_lines == [
        "2026-01-01_run.md: error: Missing required experiment field",
        "2026-01-02_run.md: error: Missing required experiment field",
    ]
    assert result.stdout.count("summary spans") == 1
    assert "2 entries: summary spans" in result.stdout


def test_round2_warning_json_preserves_diagnostic_order(tmp_path: Path) -> None:
    """Preserve source-order JSON diagnostics when text warnings are grouped."""
    for day in (1, 2):
        _entry(
            tmp_path,
            f"2026-01-0{day}_run.md",
            extra=f"follows: absent-{day}\n",
            summary="x" * 301,
        )
    status, report = _run(tmp_path, "--check")
    assert status == 1
    assert [
        (problem["path"], problem["message"]) for problem in report["problems"]
    ] == [
        (f"2026-01-0{day}_run.md", message)
        for day in (1, 2)
        for message in (
            "summary spans multiple lines or exceeds 300 characters",
            f"follows target does not exist: absent-{day}",
        )
    ]
