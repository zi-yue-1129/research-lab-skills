"""Persistence and event-history tests for presentation workflow state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from presentation_events import StateParseError, effective_review_results, load_review_results
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


def test_slide_png_artifact_requires_complete_typed_provenance(tmp_path: Path) -> None:
    """Slide PNG records require exact plan, generated-slide, and attempt bindings."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Evidence")
    slide = create_slide(project, deck["id"], "slide-01", "Takeaway")

    with pytest.raises((TypeError, ValueError), match="provenance|plan_version|slide_record_id"):
        create_artifact_record(
            project,
            deck["id"],
            "slide-png",
            "renders/slide-01.png",
            "d" * 64,
            "renderer",
            slide_id=slide["id"],
            plan_version=1,
        )


def test_artifact_provenance_rejects_boolean_versions_and_forbidden_subjects(
    tmp_path: Path,
) -> None:
    """Kind-specific provenance rejects bool versions and slide subjects on sheets."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Evidence")
    slide = create_slide(project, deck["id"], "slide-01", "Takeaway")
    artifacts_path = project / ".research/presentations/state/artifacts.yaml"
    prior_exists = artifacts_path.exists()
    prior_bytes = artifacts_path.read_bytes() if prior_exists else b""

    with pytest.raises((TypeError, ValueError), match="plan_version"):
        create_artifact_record(
            project,
            deck["id"],
            "slide-png",
            "renders/slide-01.png",
            "d" * 64,
            "renderer",
            slide_id=slide["id"],
            plan_version=True,
            plan_sha256="a" * 64,
            slide_record_id=slide["id"],
            attempt=1,
        )

    with pytest.raises((TypeError, ValueError), match="review-sheet|slide_id"):
        create_artifact_record(
            project,
            deck["id"],
            "review-sheet",
            "renders/contact-sheet.png",
            "e" * 64,
            "renderer",
            slide_id=slide["id"],
            plan_version=1,
            plan_sha256="a" * 64,
            source_paths=["renders/slide-01.png"],
            source_sha256="s" * 64,
        )
    assert artifacts_path.exists() is prior_exists
    if prior_exists:
        assert artifacts_path.read_bytes() == prior_bytes


def test_slide_png_forbidden_module_subject_precedes_invalid_attempt_without_writes(
    tmp_path: Path,
) -> None:
    """Forbidden slide-PNG subjects fail before invalid provenance or state writes."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Evidence")
    slide = create_slide(project, deck["id"], "slide-01", "Takeaway")
    artifacts_path = project / ".research/presentations/state/artifacts.yaml"
    prior_exists = artifacts_path.exists()
    prior_bytes = artifacts_path.read_bytes() if prior_exists else b""

    with pytest.raises(ValueError, match="module_id"):
        create_artifact_record(
            project,
            deck["id"],
            "slide-png",
            "renders/slide-01.png",
            "d" * 64,
            "renderer",
            slide_id=slide["id"],
            module_id="mod-forbidden",
            plan_version=1,
            plan_sha256="a" * 64,
            slide_record_id=slide["id"],
            attempt=True,
        )
    assert artifacts_path.exists() is prior_exists
    if prior_exists:
        assert artifacts_path.read_bytes() == prior_bytes


def test_typed_artifact_provenance_is_persisted_without_aliases(tmp_path: Path) -> None:
    """Valid typed provenance persists canonical fields exactly once."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Evidence")
    slide = create_slide(project, deck["id"], "slide-01", "Takeaway")
    record = create_artifact_record(
        project,
        deck["id"],
        "slide-png",
        "renders/slide-01.png",
        "d" * 64,
        "renderer",
        slide_id=slide["id"],
        plan_version=1,
        plan_sha256="a" * 64,
        slide_record_id=slide["id"],
        attempt=1,
    )

    persisted = load_artifacts(project)[record["id"]]
    assert persisted["artifact_kind"] == "slide-png"
    assert persisted["plan_version"] == 1
    assert persisted["slide_record_id"] == slide["id"]
    assert persisted["attempt"] == 1
    assert "producer" not in persisted


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


def test_integrity_scan_rejects_cross_slide_assignment_and_artifact_pairing(
    tmp_path: Path,
) -> None:
    """Validation rejects same-deck records pairing a module with another slide."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Coherence")
    first_slide = create_slide(project, deck["id"], "slide-01", "First")
    second_slide = create_slide(project, deck["id"], "slide-02", "Second")
    module = create_visual_module(project, first_slide["id"], "module", "architecture")
    assignment = create_assignment_record(
        project,
        deck["id"],
        slide_id=first_slide["id"],
        module_id=module["id"],
        assignment_path="assignments/module.yaml",
        worker_id="worker",
        worker_type="architecture",
        spec_sha256="a" * 64,
    )
    artifact = create_artifact_record(
        project,
        deck["id"],
        artifact_kind="slide-svg",
        artifact_path="slides/module.svg",
        sha256="b" * 64,
        producer_id="worker",
        slide_id=first_slide["id"],
        module_id=module["id"],
    )

    state_root = project / ".research" / "presentations" / "state"
    assignments_path = state_root / "assignments.yaml"
    assignments_doc = yaml.safe_load(assignments_path.read_text(encoding="utf-8"))
    assignments_doc["assignments"][assignment["id"]]["slide_id"] = second_slide["id"]
    assignments_path.write_text(yaml.safe_dump(assignments_doc), encoding="utf-8")
    artifacts_path = state_root / "artifacts.yaml"
    artifacts_doc = yaml.safe_load(artifacts_path.read_text(encoding="utf-8"))
    artifacts_doc["artifacts"][artifact["id"]]["slide_id"] = second_slide["id"]
    artifacts_path.write_text(yaml.safe_dump(artifacts_doc), encoding="utf-8")

    from presentation_state import validate_referential_integrity

    violations = validate_referential_integrity(project)

    assert any(
        violation["entity"] == "assignment"
        and violation["field"] == "slide_id"
        and violation["missing_id"] == first_slide["id"]
        for violation in violations
    )
    assert any(
        violation["entity"] == "artifact"
        and violation["field"] == "slide_id"
        and violation["missing_id"] == first_slide["id"]
        for violation in violations
    )


@pytest.mark.parametrize("record_kind", ["assignment", "artifact"])
def test_records_reject_same_deck_cross_slide_pairing(
    tmp_path: Path, record_kind: str
) -> None:
    """Record writers reject a module paired with a different same-deck slide."""
    project = make_project(tmp_path)
    deck = create_deck(project, "Coherence")
    first_slide = create_slide(project, deck["id"], "slide-01", "First")
    second_slide = create_slide(project, deck["id"], "slide-02", "Second")
    module = create_visual_module(project, first_slide["id"], "module", "architecture")

    with pytest.raises(ValueError, match="does not belong to slide"):
        if record_kind == "assignment":
            create_assignment_record(
                project,
                deck["id"],
                slide_id=second_slide["id"],
                module_id=module["id"],
                assignment_path="assignments/module.yaml",
                worker_id="worker",
                worker_type="architecture",
                spec_sha256="a" * 64,
            )
        else:
            create_artifact_record(
                project,
                deck["id"],
                artifact_kind="slide-svg",
                artifact_path="slides/module.svg",
                sha256="b" * 64,
                producer_id="worker",
                slide_id=second_slide["id"],
                module_id=module["id"],
            )


def test_effective_reviews_keep_subject_types_separate() -> None:
    """Plan and deck reviews sharing an ID do not supersede one another."""
    reviews = [
        {
            "id": "review-plan",
            "subject_type": "plan",
            "subject_id": "deck-1",
            "reviewer_role": "content",
            "reviewer_id": "reviewer",
            "status": "passed",
            "round": 1,
            "ts": "2026-08-08T00:00:00Z",
        },
        {
            "id": "review-deck",
            "subject_type": "deck",
            "subject_id": "deck-1",
            "reviewer_role": "content",
            "reviewer_id": "reviewer",
            "status": "failed",
            "round": 2,
            "ts": "2026-08-08T00:01:00Z",
        },
    ]

    effective = effective_review_results(reviews)

    assert {review["id"] for review in effective} == {"review-plan", "review-deck"}
