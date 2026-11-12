"""Check that journal scanners share the uppercase meta-file boundary."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script", ["section_query.py", "log_stats.py"])
def test_reserved_meta_and_directories_are_not_entries(
    tmp_path: Path, script: str
) -> None:
    """Exclude uppercase stems and nested logs while keeping mixed-case entries."""
    entry = (
        "---\ndate: 2026-01-01\nexperiment: run\n---\n## Results\nmeasured\n"
    )
    for name in ("STATE.md", "PROTOCOL.md", "A1_B2.md", "INDEX.md"):
        (tmp_path / name).write_text(
            "## Phantom\n" + "x" * 10000, encoding="utf-8"
        )
    for name in ("2026-01-01_run.md", "MixedCase.md", "UPPER-case.md"):
        (tmp_path / name).write_text(entry, encoding="utf-8")
    nested = tmp_path / "milestones"
    nested.mkdir()
    (nested / "M1.md").write_text(entry, encoding="utf-8")
    (tmp_path / "directory.md").mkdir()
    arguments = ["types"] if script == "section_query.py" else ["--json"]
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / script),
            *arguments,
            "--dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    if script == "section_query.py":
        by_name = {item["name"]: item for item in payload["types"]}
        assert "Phantom" not in by_name
        assert by_name["Results"]["occurrence_count"] == 3
    else:
        assert payload["file_count"] == 3
        assert payload["total_chars"] == 3 * len(entry)
