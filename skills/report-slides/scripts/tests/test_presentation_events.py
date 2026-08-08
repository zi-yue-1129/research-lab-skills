"""Persistence and event-history tests for presentation workflow state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from presentation_events import StateParseError, load_review_results
from presentation_state import (
    create_artifact_record,
    create_assignment_record,
    create_deck,
    create_slide,
    create_visual_module,
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


def test_load_review_results_preserves_legacy_event_shape(tmp_path: Path) -> None:
    """Legacy events remain unmodified instead of gaining invented identity."""
    project = make_project(tmp_path)
    events = project / ".research" / "presentations" / "events"
    events.mkdir(parents=True)
    (events / "2026-08-08.jsonl").write_text(
        json.dumps(
            {
                "event": "review_result",
                "id": "rev_legacy",
                "subject_type": "deck",
                "subject_id": "deck_legacy",
                "reviewer_role": "scientific",
                "status": "passed",
                "round": 1,
                "ts": "2026-08-08T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = load_review_results(project)

    assert "reviewer_id" not in result[0]
    assert "findings" not in result[0]


def test_assignment_rejects_cross_deck_dependency(tmp_path: Path) -> None:
    """Assignments cannot depend on a module owned by another deck."""
    project = make_project(tmp_path)
    first_deck = create_deck(project, "First")
    first_slide = create_slide(project, first_deck["id"], "slide-01", "First")
    upstream = create_visual_module(project, first_slide["id"], "upstream", "architecture")
    second_deck = create_deck(project, "Second")
    second_slide = create_slide(project, second_deck["id"], "slide-01", "Second")
    foreign = create_visual_module(project, second_slide["id"], "foreign", "architecture")

    with pytest.raises(ValueError, match="same deck"):
        create_assignment_record(
            project,
            first_deck["id"],
            module_id=upstream["id"],
            assignment_path="assignments/upstream.yaml",
            worker_id="worker",
            worker_type="architecture",
            spec_sha256="a" * 64,
            dependencies=[foreign["id"]],
        )


def test_query_does_not_fabricate_missing_draft_evidence(tmp_path: Path) -> None:
    """A dangling draft reference is reported as a blocker, not a stub."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Draft")
    decks_path = project / ".research" / "presentations" / "state" / "decks.yaml"
    document = yaml.safe_load(decks_path.read_text(encoding="utf-8"))
    document["decks"][deck["id"]]["draft_preview_id"] = "draft_missing"
    decks_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    from presentation_state import query

    result = query(project, deck["id"])

    assert result["draft_preview"] is None
    assert any(blocker["reason"] == "missing_draft_preview" for blocker in result["blockers"])


@pytest.mark.parametrize("invalid_path", ["../escape.yaml", "/absolute.yaml", "", "a/../../b.yaml"])
def test_record_paths_reject_parent_or_absolute_paths(tmp_path: Path, invalid_path: str) -> None:
    """Record creators reject paths that are not canonical project relatives."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Path")

    with pytest.raises(ValueError):
        register_plan_record(project, deck["id"], invalid_path, "a" * 64, "planner")


def test_assignment_failure_before_module_update_persists_no_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disappearing module cannot leave an orphan assignment record."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Atomic")
    slide = create_slide(project, deck["id"], "slide-01", "Atomic")
    module = create_visual_module(project, slide["id"], "module", "architecture")

    import presentation_state

    original_loader = presentation_state._load_yaml_map
    seen = {"modules": 0}

    def disappear_after_validation(path: Path, top_key: str) -> dict[str, object]:
        records = original_loader(path, top_key)
        if top_key == "visual_modules":
            seen["modules"] += 1
            if seen["modules"] >= 2:
                records = {}
        return records

    monkeypatch.setattr(presentation_state, "_load_yaml_map", disappear_after_validation)
    with pytest.raises(presentation_state.VisualModuleNotFoundError):
        create_assignment_record(
            project,
            deck["id"],
            module_id=module["id"],
            assignment_path="assignments/module.yaml",
            worker_id="worker",
            worker_type="architecture",
            spec_sha256="a" * 64,
        )

    assert not load_assignments(project)
