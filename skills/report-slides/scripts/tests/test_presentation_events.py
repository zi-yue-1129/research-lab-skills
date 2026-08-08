"""Persistence and event-history tests for presentation workflow state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from presentation_events import StateParseError, load_review_results
from presentation_state import (
    create_artifact_record,
    create_assignment_record,
    create_deck,
    create_slide,
    load_artifacts,
    load_assignments,
    load_plans,
    register_plan_record,
)


def make_project(tmp_path: Path) -> Path:
    """Create a minimal project root for persistence tests."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def test_registering_plan_versions_preserves_prior_digest(tmp_path: Path) -> None:
    """Plan registration increments versions and links superseded records."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Example")

    first = register_plan_record(
        project, deck["id"], "plans/plan-v0001.yaml", "a" * 64, "planner"
    )
    second = register_plan_record(
        project, deck["id"], "plans/plan-v0002.yaml", "b" * 64, "planner"
    )

    assert first["version"] == 1
    assert second["version"] == 2
    assert second["supersedes_plan_id"] == first["id"]
    assert load_plans(project)[first["id"]]["sha256"] == "a" * 64


def test_review_loader_fails_closed_with_shard_and_line(tmp_path: Path) -> None:
    """Malformed JSONL identifies the exact shard and line that failed."""
    project = make_project(tmp_path)
    events = project / ".research" / "presentations" / "events"
    events.mkdir(parents=True)
    shard = events / "2026-08-08.jsonl"
    shard.write_text('{"event":"review_result"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(StateParseError, match=r"2026-08-08\.jsonl.*line 2"):
        load_review_results(project)


def test_assignment_and_artifact_paths_are_canonical_and_referential(tmp_path: Path) -> None:
    """Assignment and artifact records retain canonical relative paths."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Example")
    slide = create_slide(project, deck["id"], "slide-01", "Takeaway")

    assignment = create_assignment_record(
        project,
        deck["id"],
        slide_id=slide["id"],
        module_id=None,
        assignment_path=Path("assignments/module.yaml"),
        worker_id="worker-a",
        worker_type="architecture",
        spec_sha256="c" * 64,
    )
    artifact = create_artifact_record(
        project,
        deck["id"],
        artifact_kind="slide-svg",
        artifact_path=Path("slides/slide-01.svg"),
        sha256="d" * 64,
        producer_id="worker-a",
        slide_id=slide["id"],
    )

    assert assignment["assignment_path"] == "assignments/module.yaml"
    assert artifact["path"] == "slides/slide-01.svg"
    assert assignment["id"] in load_assignments(project)
    assert artifact["id"] in load_artifacts(project)

