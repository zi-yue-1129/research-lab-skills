"""Exercise milestone size recommendations without changing volume statistics."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "log_stats.py"


@pytest.mark.parametrize(
    "count,limit,expected", [(29, 30, False), (30, 30, True), (3, 3, True)]
)
def test_newest_ongoing_size_signal(
    tmp_path: Path, count: int, limit: int, expected: bool
) -> None:
    """Choose the newest ongoing milestone, ignoring larger older groups."""
    (tmp_path / "MILESTONES.md").write_text(
        "# Research Milestones\n\n## M3: Completed\nDescription.\n"
        "**Date range:** 2026-01-01 – 2026-01-02 · **Status:** closed\n"
        "## M2: Current\nDescription.\n**Date range:** 2026-01-01 – ongoing · **Status:** ongoing\n"
        "## M1: Earlier\nDescription.\n**Date range:** 2025-01-01 – ongoing · **Status:** ongoing\n",
        encoding="utf-8",
    )
    for milestone, size in (("M1", 35), ("M2", count), ("M3", 40)):
        for index in range(size):
            (tmp_path / f"2026-01-01_{milestone}-{index}.md").write_text(
                f"---\ndate: 2026-01-01\nexperiment: run\nsummary: Measured.\nmilestone: {milestone}\n---\n",
                encoding="utf-8",
            )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dir",
            str(tmp_path),
            "--json",
            "--milestone-max-entries",
            str(limit),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["milestones"] == [
        {"id": "M3", "status": "closed", "entries": 40},
        {"id": "M2", "status": "ongoing", "entries": count},
        {"id": "M1", "status": "ongoing", "entries": 35},
    ]
    assert payload["recommend_new_milestone"] is expected
    assert payload["file_count"] == 75 + count
    assert payload["recommend_enable"] is False


@pytest.mark.parametrize("count,recommended", [(1, "no"), (2, "yes")])
def test_round2_text_reports_newest_ongoing_milestone(
    tmp_path: Path, count: int, recommended: str
) -> None:
    """Expose the newest ongoing count, configured limit and size recommendation."""
    (tmp_path / "MILESTONES.md").write_text(
        "# Research Milestones\n\n## M1: Earlier\nDescription.\n"
        "**Date range:** old · **Status:** ongoing\n"
        "## M3: Completed\nDescription.\n"
        "**Date range:** old · **Status:** closed\n"
        "## M2: Current\nDescription.\n"
        "**Date range:** old · **Status:** ongoing\n",
        encoding="utf-8",
    )
    for index in range(count):
        (tmp_path / f"2026-01-01_run-{index}.md").write_text(
            "---\ndate: 2026-01-01\nexperiment: run\nsummary: Measured.\n"
            "milestone: M2\n---\n",
            encoding="utf-8",
        )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dir",
            str(tmp_path),
            "--milestone-max-entries",
            "2",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (
        f"  Newest ongoing milestone: M2 · {count} entries · threshold: 2 entries"
        f" · recommend new milestone: {recommended}"
    ) in result.stdout.splitlines()
