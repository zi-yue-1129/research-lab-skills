"""Tests proving state.py serializes concurrent writers instead of losing data."""
import fcntl
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "state.py"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _run(cwd: Path, *args: str, env: dict = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, check=False, env=full_env,
    )


def test_concurrent_start_run_calls_do_not_lose_data(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    def _start(_: int) -> subprocess.CompletedProcess:
        return _run(project, "--start-run", "--skill", "deep-research", "--json")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_start, range(8)))

    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    run_ids = {json.loads(r.stdout)["id"] for r in results}
    assert len(run_ids) == 8  # every run got a distinct id, none overwrote another

    runs_yaml = (project / ".research" / "state" / "runs.yaml").read_text()
    for run_id in run_ids:
        assert run_id in runs_yaml  # every run survived the concurrent writes


def test_start_run_times_out_when_runs_yaml_is_held_by_another_process(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    runs_yaml = project / ".research" / "state" / "runs.yaml"
    runs_yaml.parent.mkdir(parents=True)
    runs_yaml.touch()
    # _locked_file locks a stable sidecar file (path + ".lock"), not runs.yaml
    # itself -- see state_store.py's _locked_file docstring for why. Hold the
    # same sidecar lock here to simulate another process genuinely contending
    # for it.
    lock_path = runs_yaml.with_name(runs_yaml.name + ".lock")
    lock_path.touch()

    fd = os.open(str(lock_path), os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        started = time.monotonic()
        result = _run(
            project, "--start-run", "--skill", "deep-research", "--json",
            env={"AGENT_STATE_LOCK_TIMEOUT_SECONDS": "1"},
        )
        elapsed = time.monotonic() - started

        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["error"] == "LockTimeoutError"
        assert elapsed < 5  # bounded by the 1s override, not the 30s default
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
