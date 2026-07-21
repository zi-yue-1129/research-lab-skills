"""Tests for log_stats.py — research log token-volume scanner (milestone gating)."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "log_stats.py"


def _write(dir_path: Path, name: str, num_chars: int) -> None:
    (dir_path / name).write_text("x" * num_chars, encoding="utf-8")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_counts_chars_excluding_index_and_milestones(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 400)
    _write(log_dir, "2026-01-02_run_b.md", 600)
    _write(log_dir, "INDEX.md", 999_999)
    _write(log_dir, "MILESTONES.md", 999_999)

    result = _run("--dir", str(log_dir), "--json")
    assert result.returncode == 0, result.stderr
    stats = json.loads(result.stdout)

    assert stats["file_count"] == 2
    assert stats["total_chars"] == 1000
    assert stats["estimated_tokens"] == 250  # 1000 // 4


def test_recommend_enable_false_below_threshold(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 400)  # 100 estimated tokens

    result = _run("--dir", str(log_dir), "--threshold", "6000", "--json")
    stats = json.loads(result.stdout)
    assert stats["recommend_enable"] is False


def test_recommend_enable_true_at_threshold(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 24_000)  # exactly 6000 estimated tokens

    result = _run("--dir", str(log_dir), "--threshold", "6000", "--json")
    stats = json.loads(result.stdout)
    assert stats["estimated_tokens"] == 6000
    assert stats["recommend_enable"] is True


def test_recommend_enable_false_when_milestones_already_exists(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 24_000)
    _write(log_dir, "MILESTONES.md", 10)  # already active

    result = _run("--dir", str(log_dir), "--threshold", "6000", "--json")
    stats = json.loads(result.stdout)
    assert stats["milestones_exists"] is True
    assert stats["recommend_enable"] is False


def test_missing_directory_returns_zero_stats(tmp_path: Path) -> None:
    missing_dir = tmp_path / "does_not_exist"

    result = _run("--dir", str(missing_dir), "--json")
    assert result.returncode == 0, result.stderr
    stats = json.loads(result.stdout)
    assert stats == {
        "file_count": 0,
        "total_chars": 0,
        "estimated_tokens": 0,
        "milestones_exists": False,
        "threshold": 6000,
        "recommend_enable": False,
    }


def test_text_report_format(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 400)

    result = _run("--dir", str(log_dir))
    assert result.returncode == 0, result.stderr
    assert "1 entry" in result.stdout
    assert "400 chars" in result.stdout
    assert "below threshold" in result.stdout


def test_default_threshold_is_6000_when_flag_omitted(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 400)

    result = _run("--dir", str(log_dir), "--json")
    stats = json.loads(result.stdout)
    assert stats["threshold"] == 6000
