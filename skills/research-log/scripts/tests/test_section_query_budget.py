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


def _error_payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Decode and validate a standard structured CLI error response."""
    assert result.returncode != 0
    assert result.stderr == ""
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["ok"] is False
    assert isinstance(payload["error"]["code"], str)
    assert isinstance(payload["error"]["message"], str)
    assert isinstance(payload["error"]["details"], dict)
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
    error = _error_payload(rejected)
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
    assert rejected.stderr == ""
    error = json.loads(rejected.stdout)
    assert error["ok"] is False
    diagnostic = error["error"]
    assert diagnostic["code"] == "metadata_exceeds_budget"
    assert set(diagnostic) == {"code", "message", "details"}
    assert isinstance(diagnostic["message"], str)
    assert diagnostic["message"]
    assert diagnostic["details"]["budget"] == 1
    assert diagnostic["details"]["estimated_tokens"] > 1


def test_search_fit_indicator_matches_single_fetch_at_multiple_budgets(
    tmp_path: Path,
) -> None:
    """Calculate fetch fit from the active search budget and full response."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(
        log_dir,
        "large.md",
        "---\ndate: 2026-08-02\nexperiment: large\n---\n## Analysis\n"
        + ("x" * 7_500)
        + "\n",
    )

    for budget, expected_fit in ((1_000, False), (4_000, True)):
        search = _payload(
            _run(
                "search",
                "--dir",
                str(log_dir),
                "--sections",
                "Analysis",
                "--budget",
                str(budget),
            )
        )
        fetch = _payload(
            _run(
                "fetch",
                "--dir",
                str(log_dir),
                "--ids",
                "large::analysis",
                "--budget",
                str(budget),
            )
        )

        assert search["matches"][0]["fits_fetch_budget"] is expected_fit
        assert (fetch["status"] == "complete") is expected_fit


def test_search_fit_indicator_includes_single_fetch_metadata(tmp_path: Path) -> None:
    """Mark a body as oversized when its complete fetch envelope cannot fit."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    body = ("x" * 2_400) + "\n"
    _write_log(
        log_dir,
        "metadata-boundary.md",
        "---\ndate: 2026-08-02\nexperiment: boundary\n---\n## Analysis\n" + body,
    )

    search = _payload(
        _run(
            "search",
            "--dir",
            str(log_dir),
            "--sections",
            "Analysis",
            "--budget",
            "700",
        )
    )
    fetch = _payload(
        _run(
            "fetch",
            "--dir",
            str(log_dir),
            "--ids",
            "metadata-boundary::analysis",
            "--budget",
            "700",
        )
    )

    assert search["matches"][0]["estimated_body_tokens"] < 700
    assert search["matches"][0]["fits_fetch_budget"] is False
    assert fetch["status"] == "chunk_required"


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
    changed_query_error = _error_payload(changed_query)
    assert changed_query_error["error"]["code"] == "cursor_query_mismatch"

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
    stale_types_error = _error_payload(stale_types)
    stale_search_error = _error_payload(stale_search)
    assert stale_types_error["error"]["code"] == "cursor_journal_mismatch"
    assert stale_search_error["error"]["code"] == "cursor_journal_mismatch"


def test_fetch_returns_requested_exact_bodies_and_provenance(tmp_path: Path) -> None:
    """Fetch exact requested occurrences in request order with provenance."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    first_body = "First body.\n"
    second_body = "Second body.\n"
    _write_log(
        log_dir,
        "2026-01-01_run.md",
        "---\ndate: 2026-01-01\nexperiment: run\n---\n"
        f"## Results\n{first_body}## results\n{second_body}",
    )

    payload = _payload(_run(
        "fetch", "--dir", str(log_dir),
        "--ids", "2026-01-01_run::results::2", "2026-01-01_run::results",
        "--budget", "1200",
    ))

    assert payload["status"] == "complete"
    assert payload["requested_ids"] == [
        "2026-01-01_run::results::2", "2026-01-01_run::results",
    ]
    assert [item["id"] for item in payload["items"]] == payload["requested_ids"]
    assert [item["body"] for item in payload["items"]] == [second_body, first_body]
    assert payload["items"][0]["path"] == "2026-01-01_run.md"
    assert payload["items"][0]["occurrence"] == 2
    assert payload["budget"]["estimated_tokens"] == _estimated_tokens(payload)
    assert payload["budget"]["estimated_tokens"] <= payload["budget"]["limit"]


def test_fetch_rejects_duplicate_and_unknown_ids(tmp_path: Path) -> None:
    """Reject ambiguous duplicate and unknown full-text fetch requests."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(log_dir, "run.md", "## Goal\nKnown.\n")

    duplicate = _run(
        "fetch", "--dir", str(log_dir), "--ids", "run::goal", "run::goal",
    )
    unknown = _run("fetch", "--dir", str(log_dir), "--ids", "missing::goal")

    duplicate_error = _error_payload(duplicate)
    unknown_error = _error_payload(unknown)
    assert duplicate_error["error"]["code"] == "duplicate_ids"
    assert unknown_error["error"]["code"] == "invalid_result_id"


def test_fetch_overflow_returns_no_partial_body_and_safe_batches(tmp_path: Path) -> None:
    """Suggest independently safe batches instead of returning partial bodies."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    ids: list[str] = []
    for index in range(3):
        stem = f"2026-01-0{index + 1}_run_{index}"
        ids.append(f"{stem}::failures")
        _write_log(
            log_dir,
            f"{stem}.md",
            f"---\ndate: 2026-01-0{index + 1}\nexperiment: run-{index}\n---\n"
            f"## Failures\n{'failure ' * 500}\n",
        )

    payload = _payload(_run(
        "fetch", "--dir", str(log_dir), "--ids", *ids, "--budget", "1800",
    ))

    assert payload["status"] == "overflow"
    assert "items" not in payload
    assert payload["requested_ids"] == ids
    assert payload["suggested_batches"]
    assert [item["id"] for item in payload["item_sizes"]] == ids
    assert all(batch["estimated_tokens"] <= 1800 for batch in payload["suggested_batches"])
    flattened_ids = [item_id for batch in payload["suggested_batches"] for item_id in batch["ids"]]
    assert flattened_ids == ids
    for batch in payload["suggested_batches"]:
        response = _payload(_run(
            "fetch", "--dir", str(log_dir), "--ids", *batch["ids"], "--budget", "1800",
        ))
        assert response["status"] == "complete"
        assert response["budget"]["estimated_tokens"] == batch["estimated_tokens"]


def test_mixed_fetch_disposes_every_requested_id_without_partial_bodies(
    tmp_path: Path,
) -> None:
    """Return a chunk cursor or safe batch disposition for every mixed ID."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(
        log_dir,
        "mixed.md",
        "---\ndate: 2026-08-02\nexperiment: mixed\n---\n"
        f"## Goal\n{'x' * 10_000}\n"
        "## Analysis\nSmall analysis.\n",
    )
    requested_ids = ["mixed::goal", "mixed::analysis"]

    payload = _payload(
        _run(
            "fetch",
            "--dir",
            str(log_dir),
            "--ids",
            *requested_ids,
            "--budget",
            "1800",
        )
    )

    assert payload["status"] == "overflow"
    assert payload["requested_ids"] == requested_ids
    assert "items" not in payload
    dispositions = payload["item_dispositions"]
    assert [item["id"] for item in dispositions] == requested_ids
    assert dispositions[0]["status"] == "chunk_required"
    assert isinstance(dispositions[0]["chunk_cursor"], str)
    assert dispositions[1] == {
        "id": "mixed::analysis",
        "status": "suggested_batch",
        "batch_index": 0,
    }
    assert payload["suggested_batches"][0]["ids"] == ["mixed::analysis"]


def test_oversized_section_chunks_reconstruct_exact_body(tmp_path: Path) -> None:
    """Return contiguous paragraph-aware chunks that exactly reconstruct a body."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    body = "\n\n".join(
        f"Paragraph {index}: " + "x" * 700 for index in range(12)
    ) + "\n"
    _write_log(
        log_dir,
        "2026-01-01_large.md",
        "---\ndate: 2026-01-01\nexperiment: large\n---\n## Analysis\n" + body,
    )

    first = _payload(_run(
        "fetch", "--dir", str(log_dir),
        "--ids", "2026-01-01_large::analysis", "--budget", "600",
    ))
    assert first["status"] == "chunk_required"
    assert "items" not in first

    chunks: list[str] = []
    ranges: list[tuple[int, int]] = []
    cursor = first["chunk_cursor"]
    while cursor:
        page = _payload(_run(
            "fetch", "--dir", str(log_dir), "--chunk-cursor", cursor,
            "--budget", "600",
        ))
        chunks.append(page["chunk"]["text"])
        ranges.append((page["chunk"]["start"], page["chunk"]["end"]))
        assert page["chunk"]["label"].startswith("chunk ")
        assert page["budget"]["estimated_tokens"] == _estimated_tokens(page)
        assert page["budget"]["estimated_tokens"] <= 600
        cursor = page["next_chunk_cursor"]

    assert "".join(chunks) == body
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(body)
    assert all(previous[1] == following[0] for previous, following in zip(ranges, ranges[1:]))
    assert any(body[end - 2:end] == "\n\n" for _, end in ranges[:-1])


def test_chunk_cursor_rejects_source_or_budget_changes(tmp_path: Path) -> None:
    """Bind a chunk cursor to both source content and the active budget."""
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    path = _write_log(
        log_dir,
        "large.md",
        "## Analysis\n" + ("Paragraph.\n\n" * 600),
    )
    initial = _payload(_run(
        "fetch", "--dir", str(log_dir), "--ids", "large::analysis", "--budget", "600",
    ))
    cursor = initial["chunk_cursor"]

    different_budget = _run(
        "fetch", "--dir", str(log_dir), "--chunk-cursor", cursor, "--budget", "601",
    )
    different_budget_error = _error_payload(different_budget)
    assert different_budget_error["error"]["code"] == "cursor_budget_mismatch"

    path.write_text("## Analysis\nChanged.\n", encoding="utf-8")
    changed_source = _run(
        "fetch", "--dir", str(log_dir), "--chunk-cursor", cursor, "--budget", "600",
    )
    changed_source_error = _error_payload(changed_source)
    assert changed_source_error["error"]["code"] == "cursor_journal_mismatch"
