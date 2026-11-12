"""Exercise literal historical searches through the public manifest/fetch CLI."""

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "section_query.py"


def _run(
    directory: Path, command: str, *arguments: str
) -> tuple[int, dict[str, Any]]:
    """Return the exit status and decoded public response."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            command,
            "--dir",
            str(directory),
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def _write(directory: Path, name: str, summary: str, body: str) -> None:
    """Write a dated entry with a summary and arbitrary section bodies."""
    (directory / name).write_text(
        f"---\ndate: 2026-01-01\nexperiment: run\nsummary: {summary}\n---\n{body}",
        encoding="utf-8",
    )


def test_grep_any_all_literal_heading_context_and_fetch(tmp_path: Path) -> None:
    """Find literals in headings and bodies with counted, bounded context."""
    _write(
        tmp_path,
        "run.md",
        "unrelated",
        "## Arm [A]\n"
        + "prefix " * 45
        + "Factor.*\nmeasured factor.* twice.\n## Analysis\nFactor.* alone.\n",
    )
    status, response = _run(tmp_path, "search", "--grep", "FACTOR.*", "arm [a]")
    assert status == 0, response
    assert response["total_matches"] == 2
    first = response["matches"][0]
    assert first["match_count"] == 3
    assert "Arm [A]" in first["snippet"]
    assert len(first["snippet"]) <= 160
    assert "\n" not in first["snippet"]
    status, both = _run(
        tmp_path, "search", "--grep", "factor.*", "arm [a]", "--grep-all"
    )
    assert status == 0, both
    assert both["total_matches"] == 1
    status, restricted = _run(
        tmp_path, "search", "--sections", "Analysis", "--grep", "factor.*"
    )
    assert status == 0, restricted
    assert restricted["total_matches"] == 1
    assert "Factor.*" in restricted["matches"][0]["snippet"]
    status, fetched = _run(tmp_path, "fetch", "--ids", first["id"])
    assert status == 0, fetched
    assert fetched["items"][0]["body"].endswith("measured factor.* twice.\n")


def test_summary_only_is_fetchable_without_changing_types(
    tmp_path: Path,
) -> None:
    """Expose frontmatter summaries without adding them to section discovery."""
    _write(
        tmp_path,
        "summary.md",
        '"Distinctive FACTOR measured."',
        "## Results\nOther data.\n",
    )
    status, response = _run(tmp_path, "search", "--grep", "factor")
    assert status == 0, response
    assert response["total_matches"] == 1
    record = response["matches"][0]
    assert record["type_key"] == "summary"
    assert record["match_count"] == 1
    status, fetched = _run(tmp_path, "fetch", "--ids", record["id"])
    assert status == 0, fetched
    assert fetched["items"][0]["body"] == "Distinctive FACTOR measured."
    status, types = _run(tmp_path, "types")
    assert status == 0
    assert "summary" not in [item["key"] for item in types["types"]]
    status, bounded = _run(
        tmp_path, "search", "--grep", "factor", "--from", "2026-01-02"
    )
    assert status == 0
    assert bounded["total_matches"] == 0


def test_summary_and_summary_heading_have_distinct_ids(tmp_path: Path) -> None:
    """Keep a real Summary heading and the frontmatter summary independently fetchable."""
    _write(
        tmp_path, "run.md", "needle metadata", "## Summary\nneedle section\n"
    )
    status, response = _run(tmp_path, "search", "--grep", "needle")
    assert status == 0, response
    ids = [item["id"] for item in response["matches"]]
    assert len(ids) == len(set(ids)) == 2
    status, fetched = _run(tmp_path, "fetch", "--ids", *ids)
    assert status == 0
    assert {item["body"] for item in fetched["items"]} == {
        "needle metadata",
        "needle section\n",
    }


def test_grep_budget_pagination_and_query_binding(tmp_path: Path) -> None:
    """Account for grep metadata on every page and reject changed grep cursors."""
    for index in range(16):
        _write(
            tmp_path,
            f"run-{index:02}.md",
            "unrelated",
            "## Results\n" + "context " * 40 + "needle beta\n",
        )
    arguments = (
        "--grep",
        "Needle",
        "beta",
        "--budget",
        "700",
        "--today",
        "2026-01-01",
    )
    status, response = _run(tmp_path, "search", *arguments)
    assert status == 0, response
    assert response["next_cursor"]
    original_cursor = response["next_cursor"]
    seen: list[str] = []
    while True:
        assert (
            response["budget"]["estimated_tokens"]
            == (
                len(
                    json.dumps(
                        response, ensure_ascii=False, separators=(",", ":")
                    )
                )
                + 3
            )
            // 4
        )
        assert response["budget"]["estimated_tokens"] <= 700
        for record in response["matches"]:
            assert record["match_count"] == 2
            assert "needle" in record["snippet"]
            seen.append(record["id"])
        if response["next_cursor"] is None:
            break
        status, response = _run(
            tmp_path, "search", *arguments, "--cursor", response["next_cursor"]
        )
        assert status == 0, response
    assert len(seen) == len(set(seen)) == 16
    for changed in (
        ("--grep", "other"),
        ("--grep", "needle", "beta", "--grep-all"),
    ):
        status, error = _run(
            tmp_path,
            "search",
            *changed,
            "--budget",
            "700",
            "--today",
            "2026-01-01",
            "--cursor",
            original_cursor,
        )
        assert status != 0
        assert error["error"]["code"] == "cursor_query_mismatch"
    status, normalized = _run(
        tmp_path,
        "search",
        "--grep",
        "BETA",
        "needle",
        "needle",
        "--budget",
        "700",
        "--today",
        "2026-01-01",
        "--cursor",
        original_cursor,
    )
    assert status == 0, normalized


@pytest.mark.parametrize("arguments", [(), ("--grep-all",)])
def test_sections_required_without_grep(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    """Retain the existing missing-sections error when no grep is supplied."""
    status, error = _run(tmp_path, "search", *arguments)
    assert status != 0
    assert error["error"]["code"] == "invalid_arguments"
    assert (
        error["error"]["message"]
        == "the following arguments are required: --sections"
    )
