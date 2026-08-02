"""Subprocess tests for research-log section discovery and search."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "section_query.py"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run section_query.py with the supplied CLI arguments."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_log(log_dir: Path, name: str, body: str) -> Path:
    """Write one UTF-8 research-log fixture."""
    path = log_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Decode a successful JSON response and expose assertion failures."""
    assert result.returncode == 0, result.stderr or result.stdout
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["ok"] is True
    return payload


def _assert_empty_types_payload(payload: dict[str, Any]) -> None:
    """Assert the successful zero-count taxonomy response contract."""
    assert payload["warnings"] == []
    assert [item["name"] for item in payload["types"]] == [
        "Goal", "Changes", "Setup", "Results", "Failures",
        "Analysis", "Charts", "Conclusion", "Next Steps",
    ]
    for type_summary in payload["types"]:
        assert type_summary["occurrence_count"] == 0
        assert type_summary["log_count"] == 0


def test_types_returns_empty_canonical_taxonomy_for_missing_directory(tmp_path: Path) -> None:
    """Return a successful zero-count taxonomy when the directory is absent."""
    payload = _payload(_run("types", "--dir", str(tmp_path / "missing")))

    _assert_empty_types_payload(payload)


def test_types_returns_empty_canonical_taxonomy_for_empty_directory(tmp_path: Path) -> None:
    """Return a successful zero-count taxonomy when the directory is empty."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()

    payload = _payload(_run("types", "--dir", str(log_dir)))

    _assert_empty_types_payload(payload)


def test_types_lists_canonical_first_and_discovers_custom(tmp_path: Path) -> None:
    """List zero-count canonical types before discovered custom headings."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(
        log_dir,
        "2026-01-02_run.md",
        """---
date: 2026-01-02
experiment: run
---
## Open Problems
Unresolved issue.
## Goal
Test a baseline.
""",
    )

    payload = _payload(_run("types", "--dir", str(log_dir)))
    names = [item["name"] for item in payload["types"]]

    assert names[:9] == [
        "Goal", "Changes", "Setup", "Results", "Failures",
        "Analysis", "Charts", "Conclusion", "Next Steps",
    ]
    assert names[9:] == ["Open Problems"]
    assert payload["types"][9]["occurrence_count"] == 1
    assert payload["types"][9]["log_count"] == 1
    assert payload["types"][9]["earliest_date"] == "2026-01-02"


def test_failure_aliases_merge_but_open_problems_stays_custom(tmp_path: Path) -> None:
    """Merge configured failure aliases without absorbing unrelated headings."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(
        log_dir,
        "2026-01-02_run.md",
        """---
date: 2026-01-02
experiment: run
---
## Failure
First failure.
## Failures / Pitfalls
Second failure.
## Open Problems
Not yet attempted.
""",
    )

    payload = _payload(_run("types", "--dir", str(log_dir)))
    by_name = {item["name"]: item for item in payload["types"]}

    assert by_name["Failures"]["occurrence_count"] == 2
    assert by_name["Failures"]["variants"] == ["Failure", "Failures / Pitfalls"]
    assert by_name["Open Problems"]["occurrence_count"] == 1


def test_scanner_excludes_indexes_ignores_fences_and_level_three_types(tmp_path: Path) -> None:
    """Ignore non-log files, fenced pseudo-headings, and nested headings."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(log_dir, "INDEX.md", "## Ignored Index\n")
    _write_log(log_dir, "MILESTONES.md", "## Ignored Milestones\n")
    _write_log(
        log_dir,
        "2026-01-02_run.md",
        """---
date: 2026-01-02
experiment: run
---
## Results
```markdown
## Not A Type
```
### Nested Detail
Still results.
""",
    )

    payload = _payload(_run("types", "--dir", str(log_dir)))
    by_name = {item["name"]: item for item in payload["types"]}

    assert by_name["Results"]["occurrence_count"] == 1
    assert "Ignored Index" not in by_name
    assert "Ignored Milestones" not in by_name
    assert "Not A Type" not in by_name
    assert "Nested Detail" not in by_name


def test_repeated_headings_receive_incrementing_occurrence_identifiers(tmp_path: Path) -> None:
    """Give repeated normalized headings stable, distinct occurrence IDs."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(
        log_dir,
        "2026-01-02_run.md",
        """## Results
First.
## results
Second.
""",
    )

    payload = _payload(_run("types", "--dir", str(log_dir)))
    results = next(item for item in payload["types"] if item["name"] == "Results")

    assert results["occurrence_count"] == 2
    assert results["occurrence_numbers"] == [1, 2]
    assert results["result_ids"] == [
        "2026-01-02_run::results",
        "2026-01-02_run::results::2",
    ]


def test_missing_experiment_warns_without_filename_fallback(tmp_path: Path) -> None:
    """Surface missing experiment metadata without inventing a value."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(log_dir, "2026-01-02_run.md", "## Goal\nTest.\n")

    payload = _payload(_run("types", "--dir", str(log_dir)))

    assert payload["warnings"] == [{
        "code": "missing_experiment",
        "path": "2026-01-02_run.md",
        "message": "Missing experiment frontmatter field.",
    }]
    assert payload["types"][0]["log_count"] == 1


def test_invalid_date_log_remains_visible_to_types(tmp_path: Path) -> None:
    """Keep sections from logs with malformed date metadata discoverable."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(
        log_dir,
        "2026-01-02_run.md",
        """---
date: not-a-date
experiment: run
---
## Goal
Test.
""",
    )

    payload = _payload(_run("types", "--dir", str(log_dir)))

    assert payload["types"][0]["occurrence_count"] == 1
    assert payload["types"][0]["earliest_date"] is None
    assert payload["warnings"][0]["code"] == "invalid_date"


def test_invalid_utf8_returns_json_error(tmp_path: Path) -> None:
    """Report invalid log encodings as typed CLI errors."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    (log_dir / "2026-01-02_run.md").write_bytes(b"## Goal\n\xff\n")

    result = _run("types", "--dir", str(log_dir))

    assert result.returncode != 0
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_utf8"


def test_search_multiple_types_with_inclusive_custom_bounds(tmp_path: Path) -> None:
    """Return every requested type inside inclusive custom date bounds."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    for day in ("2025-12-31", "2026-01-01", "2026-06-30", "2026-07-01"):
        _write_log(
            log_dir,
            f"{day}_run.md",
            f"""---
date: {day}
experiment: run-{day}
---
## Failures
Failure on {day}.
## Analysis
Analysis on {day}.
""",
        )

    payload = _payload(_run(
        "search", "--dir", str(log_dir), "--sections", "Failures", "Analysis",
        "--from", "2026-01-01", "--to", "2026-06-30",
    ))

    assert payload["total_matches"] == 4
    assert [item["date"] for item in payload["matches"]] == [
        "2026-06-30", "2026-06-30", "2026-01-01", "2026-01-01",
    ]
    assert payload["query"]["resolved_from"] == "2026-01-01"
    assert payload["query"]["resolved_to"] == "2026-06-30"


def test_year_range_uses_explicit_today_for_reproducibility(tmp_path: Path) -> None:
    """Resolve year ranges from an explicit reference date."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(log_dir, "2026-01-01_run.md", "---\ndate: 2026-01-01\nexperiment: run\n---\n## Goal\nIncluded.\n")
    _write_log(log_dir, "2025-12-31_old.md", "---\ndate: 2025-12-31\nexperiment: old\n---\n## Goal\nExcluded.\n")

    payload = _payload(_run(
        "search", "--dir", str(log_dir), "--sections", "Goal", "--range", "year",
        "--today", "2026-08-02",
    ))

    assert payload["total_matches"] == 1
    assert payload["query"]["resolved_from"] == "2026-01-01"
    assert payload["query"]["resolved_to"] == "2026-08-02"


def test_preset_ranges_and_all_default_are_inclusive(tmp_path: Path) -> None:
    """Resolve each preset range to its inclusive calendar-day interval."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    for day in ("2026-05-05", "2026-05-06", "2026-07-04", "2026-07-05", "2026-07-26", "2026-07-27", "2026-08-02"):
        _write_log(log_dir, f"{day}.md", f"---\ndate: {day}\nexperiment: run\n---\n## Goal\n{day}\n")

    expected_counts = {"7d": 2, "30d": 5, "90d": 7}
    for range_name, expected_count in expected_counts.items():
        payload = _payload(_run(
            "search", "--dir", str(log_dir), "--sections", "Goal", "--range", range_name,
            "--today", "2026-08-02",
        ))
        assert payload["total_matches"] == expected_count
    all_payload = _payload(_run("search", "--dir", str(log_dir), "--sections", "Goal"))
    assert all_payload["total_matches"] == 7
    assert all_payload["query"]["range"] == "all"


def test_search_accepts_one_sided_bounds_and_rejects_conflicts(tmp_path: Path) -> None:
    """Support a single custom bound but reject mixed range selection."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(log_dir, "old.md", "---\ndate: 2026-01-01\nexperiment: old\n---\n## Goal\nOld.\n")
    _write_log(log_dir, "new.md", "---\ndate: 2026-08-02\nexperiment: new\n---\n## Goal\nNew.\n")

    payload = _payload(_run("search", "--dir", str(log_dir), "--sections", "Goal", "--from", "2026-08-01"))
    assert [item["experiment"] for item in payload["matches"]] == ["new"]
    result = _run("search", "--dir", str(log_dir), "--sections", "Goal", "--range", "7d", "--from", "2026-08-01")
    assert result.returncode != 0
    assert "cannot be combined" in result.stderr


def test_search_rejects_invalid_dates_and_unknown_sections(tmp_path: Path) -> None:
    """Return useful parser errors for invalid dates and grouped unknown types."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(log_dir, "run.md", "## Goal\nBody.\n")

    invalid_date = _run("search", "--dir", str(log_dir), "--sections", "Goal", "--from", "not-a-date")
    assert invalid_date.returncode != 0
    assert "ISO" in invalid_date.stderr
    unknown = _run("search", "--dir", str(log_dir), "--sections", "Missing", "Absent")
    assert unknown.returncode != 0
    assert "Missing, Absent" in unknown.stderr
    assert "Goal" in unknown.stderr


def test_search_rejects_case_variant_of_discovered_custom_type(tmp_path: Path) -> None:
    """Require the exact discovered display name for custom section types."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(log_dir, "run.md", "## My Custom\nBody.\n")

    result = _run("search", "--dir", str(log_dir), "--sections", "my custom")

    assert result.returncode != 0
    assert "Unknown section types: my custom" in result.stderr
    assert "My Custom" in result.stderr


def test_search_manifests_preserve_provenance_without_body(tmp_path: Path) -> None:
    """Emit stable manifest summaries with source and nested-content provenance."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    long_text = " ".join(["word"] * 40)
    _write_log(
        log_dir,
        "2026-08-02_run.md",
        f"---\ndate: 2026-08-02\nexperiment: run\n---\n## results\n{long_text}\n### Detail\nNested text.\n## results\nSecond.\n",
    )

    payload = _payload(_run("search", "--dir", str(log_dir), "--sections", "Results"))
    matches = payload["matches"]
    assert [item["id"] for item in matches] == [
        "2026-08-02_run::results", "2026-08-02_run::results::2",
    ]
    first_match = matches[0]
    assert first_match["path"] == "2026-08-02_run.md"
    assert first_match["original_heading"] == "results"
    assert first_match["occurrence"] == 1
    assert first_match["body_chars"] == len(f"{long_text}\n### Detail\nNested text.\n")
    assert first_match["preview"] == long_text[:160]
    assert "body" not in first_match
    assert first_match["fits_fetch_budget"] is True


def test_search_undated_records_sort_last_for_all_and_warn_when_bounded(tmp_path: Path) -> None:
    """Keep undated logs only in all-time searches and report bounded omissions."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(log_dir, "undated.md", "---\nexperiment: unknown\n---\n## Goal\nUndated.\n")
    _write_log(log_dir, "dated.md", "---\ndate: 2026-08-02\nexperiment: dated\n---\n## Goal\nDated.\n")

    all_payload = _payload(_run("search", "--dir", str(log_dir), "--sections", "Goal"))
    assert [item["path"] for item in all_payload["matches"]] == ["dated.md", "undated.md"]
    bounded_payload = _payload(_run(
        "search", "--dir", str(log_dir), "--sections", "Goal", "--from", "2026-01-01",
    ))
    assert [item["path"] for item in bounded_payload["matches"]] == ["dated.md"]
    assert any(warning["code"] == "undated_excluded" for warning in bounded_payload["warnings"])
