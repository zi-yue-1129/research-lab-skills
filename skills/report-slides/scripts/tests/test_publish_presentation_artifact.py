"""Tests for guarded, atomic presentation artifact publication."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_events import create_assignment_record, load_artifacts, register_plan_record
from presentation_gates import PublicationGateError
from presentation_state import create_deck, create_slide, set_deck_status
from presentation_state import set_module_status
from test_presentation_gates import _approved_module_project

from publish_presentation_artifact import publish_artifact


def _project(tmp_path: Path) -> Path:
    """Create a temporary project root recognized by the state store."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _plan(deck_id: str) -> dict[str, Any]:
    """Return a minimal reviewed plan contract."""
    return {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "purpose": "Explain the result",
        "audience": "Researchers",
        "estimated_duration_minutes": 5,
        "core_narrative": "Evidence changes the decision.",
        "status": "reviewed",
        "authored_by": "planner-a",
        "excluded_content": [],
        "known_gaps": [],
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Evidence",
                "purpose": "State the result",
                "key_takeaway": "Evidence changes the decision.",
                "evidence_refs": ["paper:1"],
                "intended_visual_type": "native",
                "visual_rationale": "A simple visual clarifies the result.",
                "speaker_message": "The evidence is actionable.",
                "dependencies": [],
                "open_questions": [],
            }
        ],
    }


def approved_assignment(tmp_path: Path) -> tuple[Path, str, str, dict[str, Any]]:
    """Create an approved deck and protected slide contract fixture."""
    project = _project(tmp_path)
    deck = create_deck(project, "Approved deck", created_by="planner-a")
    plan = _plan(deck["id"])
    plan_path = project / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    register_plan_record(
        project, deck["id"], "plan.yaml", contract_sha256(plan), "planner-a"
    )
    set_deck_status(project, deck["id"], "content_review")
    set_deck_status(project, deck["id"], "awaiting_approval")
    state_path = project / ".research/presentations/state/decks.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["decks"][deck["id"]].update(
        {
            "status": "approved",
            "approval_id": "approval-test",
            "approved_plan_version": 1,
            "approved_plan_sha256": contract_sha256(plan),
        }
    )
    state_path.write_text(yaml.safe_dump(state), encoding="utf-8")
    slide = create_slide(project, deck["id"], "slide-01", "Evidence")
    contract = {
        "schema_version": 1,
        "slide_id": "slide-01",
        "information_hierarchy": ["approved takeaway", "supporting evidence"],
        "reading_order": ["title", "visual"],
        "layout_regions": [
            {"region_id": "title", "bbox": [0, 0, 1200, 100]},
            {"region_id": "visual", "bbox": [0, 100, 1200, 675]},
        ],
        "text_to_visual_ratio": 0.3,
        "visual_emphasis": "Emphasize the approved takeaway.",
        "expected_complexity": "medium",
        "reusable_components": [],
        "requires_complex_workflow": None,
        "complexity_signals": {
            "region_count": 2,
            "route_count": 1,
            "multi_stage": False,
            "mixed_technique": False,
            "heavy_cross_region_connections": False,
            "expected_reuse": False,
            "not_atomic": False,
        },
        "approved_takeaway": "Evidence changes the decision.",
        "approved_takeaway_sha256": contract_sha256(
            "Evidence changes the decision."
        ),
        "approved_evidence_refs": ["paper:1"],
        "approved_evidence_sha256": contract_sha256(["paper:1"]),
        "dimensions": {"width": 1200, "height": 675},
        "style_tokens_ref": None,
        "editability": "native",
        "input_anchors": [],
        "output_anchors": [],
    }
    contract_path = project / "assignment.yaml"
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    return project, deck["id"], slide["id"], contract


def staged_svg(tmp_path: Path) -> Path:
    """Create a deterministic staged SVG source."""
    source = tmp_path / "staged.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675"/>',
        encoding="utf-8",
    )
    return source


def final_svg(project: Path) -> Path:
    """Return the destination path under the configured slides role."""
    destination = project / "docs/slides/deck/module.svg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _configure_slides_role(project: Path) -> None:
    """Configure a project-local slides role for destination checks."""
    workspace = project / ".research/workspace.yaml"
    workspace.parent.mkdir(parents=True, exist_ok=True)
    workspace.write_text(
        yaml.safe_dump({"version": 1, "roles": {"slides": {"primary": "docs/slides"}}}),
        encoding="utf-8",
    )


def test_publish_rejects_modified_protected_digest(tmp_path: Path) -> None:
    """Reject a contract whose protected takeaway digest no longer matches."""
    project, deck_id, slide_id, assignment = approved_assignment(tmp_path)
    _configure_slides_role(project)
    assignment["approved_takeaway_sha256"] = "0" * 64
    contract_path = tmp_path / "assignment.yaml"
    contract_path.write_text(yaml.safe_dump(assignment), encoding="utf-8")

    with pytest.raises(PublicationGateError, match="takeaway"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            final_svg(project),
            "module-svg",
            slide_id,
            None,
            "worker-a",
            contract_path,
        )

    assert not final_svg(project).exists()
    assert load_artifacts(project) == {}


def test_publish_atomically_records_digest_after_replace(tmp_path: Path) -> None:
    """Copy a validated source atomically before persisting its digest record."""
    project, deck_id, slide_id, assignment = approved_assignment(tmp_path)
    _configure_slides_role(project)
    contract_path = project / "assignment.yaml"
    contract_path.write_text(yaml.safe_dump(assignment), encoding="utf-8")
    source = staged_svg(tmp_path)
    destination = final_svg(project)

    result = publish_artifact(
        project,
        deck_id,
        source,
        destination,
        "module-svg",
        slide_id,
        None,
        "worker-a",
        contract_path,
    )

    assert destination.read_bytes() == source.read_bytes()
    assert result["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert load_artifacts(project)[result["id"]]["sha256"] == result["sha256"]


def test_publish_module_binds_current_assignment_and_spec(tmp_path: Path) -> None:
    """Publish a module only when assignment and visual-spec identities agree."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    _configure_slides_role(project)
    (project / "docs/slides").mkdir(parents=True)
    set_module_status(project, module_id, "assigned")
    assignment_path = project / "assignment.yaml"
    persisted_assignment = create_assignment_record(
        project,
        deck_id,
        module_id=module_id,
        assignment_path="assignment.yaml",
        worker_id="worker-a",
        worker_type="architecture",
        spec_sha256=contract_sha256(spec),
        dependencies=[],
        inputs_resolved=True,
        slide_id=module["slide_id"],
    )
    assignment = {
        "schema_version": 1,
        "module_id": module_id,
        "worker_type": "architecture",
        "dependencies": [],
        "spec_sha256": contract_sha256(spec),
        "inputs_resolved": True,
        "assigned_at": "2026-08-08T00:00:00Z",
        "blocker": None,
    }
    assignment_path.write_text(yaml.safe_dump(assignment), encoding="utf-8")
    source = staged_svg(tmp_path)
    destination = project / "docs/slides/module.svg"

    result = publish_artifact(
        project,
        deck_id,
        source,
        destination,
        "module-svg",
        module["slide_id"],
        module_id,
        "worker-a",
        assignment_path,
    )

    assert destination.read_bytes() == source.read_bytes()
    persisted = load_artifacts(project)[result["id"]]
    assert persisted["assignment_id"] == persisted_assignment["id"]
    assert persisted["spec_sha256"] == contract_sha256(spec)
