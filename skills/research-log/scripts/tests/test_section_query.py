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
