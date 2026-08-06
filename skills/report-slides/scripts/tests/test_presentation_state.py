"""Subprocess tests for presentation_state.py -- Deck/Slide state CLI."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "presentation_state.py"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, check=False,
    )


def test_create_deck_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-deck", "--title", "Q3 Results Deck", "--skill", "research_narrative_planner", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("deck_")
    assert data["title"] == "Q3 Results Deck"
    assert data["status"] == "planning"
    assert data["plan_version"] == 0
    assert data["created_by"] == "research_narrative_planner"


def test_create_deck_without_title_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-deck", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_set_deck_status_legal_transition(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "content_review", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "content_review"


def test_set_deck_status_illegal_transition_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    # planning -> approved directly is illegal; must pass through
    # content_review and awaiting_approval first.
    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "approved", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    assert "Illegal deck transition" in data["message"]


def test_set_deck_status_unrecognized_status_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "not-a-real-status", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_set_deck_status_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--set-deck-status", "--deck-id", "deck_does_not_exist", "--status", "content_review", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "DeckNotFoundError"


def test_deck_can_be_blocked_from_any_active_state(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "blocked", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "blocked"


def test_deck_can_resume_from_blocked_to_prior_active_state(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "blocked", "--json")

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "content_review", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "content_review"


def test_create_slide_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01",
        "--title", "Action conditioning improves command sensitivity", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("sld_")
    assert data["deck_id"] == deck["id"]
    assert data["plan_slide_id"] == "slide-01"
    assert data["status"] == "planned"


def test_create_slide_without_title_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_slide_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-slide", "--deck-id", "deck_does_not_exist",
        "--plan-slide-id", "slide-01", "--title", "T", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "DeckNotFoundError"


def test_set_slide_status_legal_transition(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    slide = json.loads(_run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--title", "T", "--json",
    ).stdout)

    result = _run(project, "--set-slide-status", "--slide-id", slide["id"], "--status", "ready", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "ready"


def test_set_slide_status_illegal_transition_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    slide = json.loads(_run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--title", "T", "--json",
    ).stdout)

    # planned -> passed directly is illegal.
    result = _run(project, "--set-slide-status", "--slide-id", slide["id"], "--status", "passed", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_set_slide_status_unknown_slide_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--set-slide-status", "--slide-id", "sld_does_not_exist", "--status", "ready", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SlideNotFoundError"


def test_bootstraps_own_gitignore_not_shared_one(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--create-deck", "--title", "T", "--json")

    assert (project / ".research" / "presentations" / ".gitignore").is_file()
    assert not (project / ".research" / ".gitignore").exists()
