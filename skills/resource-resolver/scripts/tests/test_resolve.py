"""Tests for resolve.py -- Resource Resolver CLI (--check action)."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "resolve.py"

MINIMAL_REGISTRY = textwrap.dedent("""\
    version: 1
    roles:
      - name: research_log
        description: Structured research log entries
        aliases: [research_log, research-log]
        default_relative_path: docs/research_log
        consumed_by: [research-log]
      - name: slides
        description: Generated presentation decks
        aliases: [slides, presentations]
        default_relative_path: docs/slides
        consumed_by: [report-slides]
""")


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _make_registry(tmp_path: Path, content: str = MINIMAL_REGISTRY) -> Path:
    registry_path = tmp_path / "resolver_roles.yaml"
    registry_path.write_text(content, encoding="utf-8")
    return registry_path


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_reports_all_unconfigured_when_workspace_absent(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(project, "--check", "--json", "--registry", str(registry))
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {
        "configured": [],
        "skipped": [],
        "unconfigured": ["research_log", "slides"],
    }


def test_check_reports_configured_role(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              research_log:
                primary: docs/research_log
                readonly_sources: []
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )

    result = _run(project, "--check", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data == {
        "configured": ["research_log"],
        "skipped": [],
        "unconfigured": ["slides"],
    }


def test_check_reports_skipped_role(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              slides:
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )

    result = _run(project, "--check", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data == {
        "configured": [],
        "skipped": ["slides"],
        "unconfigured": ["research_log"],
    }


def test_check_errors_when_no_git_root(tmp_path: Path) -> None:
    no_git_dir = tmp_path / "not_a_project"
    no_git_dir.mkdir()

    # This test's premise -- "no .git anywhere in the ancestry" -- only holds if
    # nothing above tmp_path happens to contain a .git entry. /tmp is shared with
    # other concurrent processes/jobs on this host, so that is not guaranteed.
    # Detect (read-only) rather than assume, and skip with a clear diagnostic
    # instead of ever touching anything outside tmp_path.
    for ancestor in (no_git_dir, *no_git_dir.parents):
        if (ancestor / ".git").exists():
            pytest.skip(
                f"Ambient .git found at {ancestor / '.git'} -- environment not "
                "isolated enough for this test. Do not delete it; it may belong "
                "to another process."
            )

    registry = _make_registry(tmp_path)

    result = _run(no_git_dir, "--check", "--json", "--registry", str(registry))
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProjectRootNotFoundError"


def test_check_errors_on_malformed_workspace(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text("not: valid: yaml: [", encoding="utf-8")

    result = _run(project, "--check", "--json", "--registry", str(registry))
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "WorkspaceParseError"


def test_check_human_readable_output(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(project, "--check", "--registry", str(registry))
    assert result.returncode == 0, result.stderr
    assert "Unconfigured: research_log, slides" in result.stdout


def test_role_resolved_when_configured(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    log_dir = project / "docs" / "research_log"
    log_dir.mkdir(parents=True)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              research_log:
                primary: docs/research_log
                readonly_sources: []
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )

    result = _run(project, "--role", "research_log", "--json", "--registry", str(registry))
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {
        "status": "resolved",
        "role": "research_log",
        "primary": "docs/research_log",
        "readonly_sources": [],
    }


def test_role_resolved_external_uri_skips_existence_check(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              research_log:
                primary: "notion://shared-lab-library"
                readonly_sources: []
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )

    result = _run(project, "--role", "research_log", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data["status"] == "resolved"
    assert data["primary"] == "notion://shared-lab-library"


def test_role_stale_mapping_when_primary_deleted(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              research_log:
                primary: docs/research_log
                readonly_sources: []
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )
    # docs/research_log deliberately not created on disk

    result = _run(project, "--role", "research_log", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data == {
        "status": "stale_mapping",
        "role": "research_log",
        "primary": "docs/research_log",
    }


def test_role_unresolved_returns_ranked_candidates(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    (project / "docs" / "research_log").mkdir(parents=True)
    (project / "unrelated_dir").mkdir()

    result = _run(project, "--role", "research_log", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data["status"] == "unresolved"
    assert data["candidates"] == [{"path": "docs/research_log", "confidence": "exact"}]
    assert data["default_relative_path"] == "docs/research_log"


def test_role_no_candidates_suggests_default(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(project, "--role", "slides", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data == {
        "status": "no_candidates",
        "role": "slides",
        "default_relative_path": "docs/slides",
    }


def test_role_errors_on_unknown_role(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(project, "--role", "nonexistent", "--json", "--registry", str(registry))
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "UnknownRoleError"
