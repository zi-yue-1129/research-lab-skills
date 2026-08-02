"""Subprocess tests for budgeted research-log section-query responses."""

import json
import re
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


def _estimated_tokens(payload: dict[str, Any]) -> int:
    """Calculate the documented JSON-size token estimate for one payload."""
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (len(serialized) + 3) // 4


def test_default_budget_is_4000_and_maximum_is_8000(tmp_path: Path) -> None:
    """Expose the default budget and reject values over the hard maximum."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()

    default_result = _payload(_run("types", "--dir", str(log_dir)))
    assert default_result["budget"]["limit"] == 4000

    rejected = _run("types", "--dir", str(log_dir), "--budget", "8001")
    assert rejected.returncode != 0
    error = json.loads(rejected.stdout)
    assert error["ok"] is False
    assert error["error"]["code"] == "budget_above_maximum"


def test_search_cursor_returns_every_match_without_duplicates(tmp_path: Path) -> None:
    """Continue a budgeted search until every match is returned exactly once."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    for index in range(40):
        day = index % 28 + 1
        _write_log(
            log_dir,
            f"2026-01-{day:02d}_run_{index:02d}.md",
            f"---\ndate: 2026-01-{day:02d}\nexperiment: run-{index}\n---\n"
            f"## Failures\n{'x' * 300}\n",
        )

    first = _payload(
        _run(
            "search", "--dir", str(log_dir), "--sections", "Failures",
            "--budget", "600",
        )
    )
    assert first["returned_matches"] < first["total_matches"]
    seen = [item["id"] for item in first["matches"]]
    cursor = first["next_cursor"]

    while cursor:
        page = _payload(
            _run(
                "search", "--dir", str(log_dir), "--sections", "Failures",
                "--budget", "600", "--cursor", cursor,
            )
        )
        seen.extend(item["id"] for item in page["matches"])
        cursor = page["next_cursor"]

    assert len(seen) == 40
    assert len(set(seen)) == 40


def test_types_pages_keep_canonical_records_first_and_fit_budget(tmp_path: Path) -> None:
    """Page type summaries in canonical-first order within the selected budget."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(log_dir, "run.md", "## Zebra\nBody.\n## Alpha\nBody.\n")

    page = _payload(_run("types", "--dir", str(log_dir), "--budget", "600"))
    names = [item["name"] for item in page["types"]]

    canonical_names = [
        "Goal", "Changes", "Setup", "Results", "Failures", "Analysis", "Charts",
        "Conclusion", "Next Steps",
    ]
    assert names == canonical_names[:len(names)]
    assert page["returned_types"] == len(names)
    assert page["total_types"] == 11
    assert page["next_cursor"]
    assert page["budget"]["estimated_tokens"] == _estimated_tokens(page)
    assert page["budget"]["estimated_tokens"] <= page["budget"]["limit"]
    cursor = page["next_cursor"]
    while cursor:
        page = _payload(_run(
            "types", "--dir", str(log_dir), "--budget", "600", "--cursor", cursor,
        ))
        names.extend(item["name"] for item in page["types"])
        assert page["budget"]["estimated_tokens"] == _estimated_tokens(page)
        assert page["budget"]["estimated_tokens"] <= page["budget"]["limit"]
        cursor = page["next_cursor"]
    assert names == canonical_names + ["Alpha", "Zebra"]


def test_lower_budget_and_metadata_overflow_are_typed(tmp_path: Path) -> None:
    """Allow lower budgets when metadata fits and reject impossible metadata."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()

    response = _payload(_run("types", "--dir", str(log_dir), "--budget", "500"))
    assert response["budget"]["limit"] == 500
    assert response["budget"]["estimated_tokens"] <= 500

    rejected = _run("types", "--dir", str(log_dir), "--budget", "1")
    assert rejected.returncode != 0
    error = json.loads(rejected.stdout)
    assert error["ok"] is False
    assert error["error"]["code"] == "metadata_exceeds_budget"


def test_cursors_are_opaque_and_reject_changed_query_or_journal(tmp_path: Path) -> None:
    """Bind cursors to their resolved query and the scanned journal state."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    for index in range(15):
        _write_log(
            log_dir,
            f"run-{index:02d}.md",
            f"---\ndate: 2026-01-01\nexperiment: run-{index}\n---\n"
            f"## Failures\n{'x' * 300}\n## Analysis\n{'y' * 300}\n",
        )

    search = _payload(_run(
        "search", "--dir", str(log_dir), "--sections", "Failures", "--budget", "600",
    ))
    search_cursor = search["next_cursor"]
    assert isinstance(search_cursor, str)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", search_cursor)
    changed_query = _run(
        "search", "--dir", str(log_dir), "--sections", "Analysis", "--budget", "600",
        "--cursor", search_cursor,
    )
    assert changed_query.returncode != 0
    assert json.loads(changed_query.stdout)["error"]["code"] == "cursor_query_mismatch"

    taxonomy = _payload(_run("types", "--dir", str(log_dir), "--budget", "600"))
    taxonomy_cursor = taxonomy["next_cursor"]
    _write_log(log_dir, "changed.md", "## Goal\nChanged.\n")
    stale_types = _run(
        "types", "--dir", str(log_dir), "--budget", "600", "--cursor", taxonomy_cursor,
    )
    stale_search = _run(
        "search", "--dir", str(log_dir), "--sections", "Failures", "--budget", "600",
        "--cursor", search_cursor,
    )
    assert stale_types.returncode != 0
    assert stale_search.returncode != 0
    assert json.loads(stale_types.stdout)["error"]["code"] == "cursor_journal_mismatch"
    assert json.loads(stale_search.stdout)["error"]["code"] == "cursor_journal_mismatch"
