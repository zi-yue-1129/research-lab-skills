"""Subprocess tests for state.py -- Agent State CLI."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "state.py"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def test_rebuild_index_on_fresh_project_creates_empty_db(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--rebuild-index", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"rebuilt": "full", "shards_scanned": 0}
    assert (project / ".research" / "indexes" / "index.db").is_file()


def test_rebuild_index_incremental_by_default(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run(project, "--rebuild-index", "--full", "--json")

    result = _run(project, "--rebuild-index", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"rebuilt": "incremental", "shards_scanned": 0}


def test_errors_when_no_git_root(tmp_path: Path) -> None:
    no_git_dir = tmp_path / "not_a_project"
    no_git_dir.mkdir()

    # This test's premise -- "no .git anywhere in the ancestry" -- only holds
    # if nothing above tmp_path happens to contain a .git entry. /tmp is
    # shared with other processes on this machine, so skip rather than
    # assert a false positive if that premise doesn't hold here.
    for candidate in (no_git_dir, *no_git_dir.parents):
        if (candidate / ".git").exists():
            pytest.skip("A .git directory exists above tmp_path on this machine")

    result = _run(no_git_dir, "--rebuild-index", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProjectRootNotFoundError"
