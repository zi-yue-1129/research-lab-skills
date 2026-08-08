"""Tests for guarded, atomic presentation artifact publication."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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
    spec_path = project / "slide-spec.yaml"
    spec_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    assignment_path = project / "slide-assignment.yaml"
    assignment_path.write_text(
        yaml.safe_dump({"schema_version": 1, "producer_id": "worker-a"}),
        encoding="utf-8",
    )
    slide_state_path = project / ".research/presentations/state/slides.yaml"
    slide_state = yaml.safe_load(slide_state_path.read_text(encoding="utf-8"))
    slide_state["slides"][slide["id"]].update(
        {
            "slide_spec_path": "slide-spec.yaml",
            "slide_spec_sha256": contract_sha256(contract),
            "approved_takeaway_sha256": contract["approved_takeaway_sha256"],
            "approved_evidence_sha256": contract["approved_evidence_sha256"],
            "assignment_path": "slide-assignment.yaml",
            "owner_id": "worker-a",
        }
    )
    slide_state_path.write_text(yaml.safe_dump(slide_state), encoding="utf-8")
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
    return project / "docs/slides/deck/module.svg"


def _configure_slides_role(project: Path) -> None:
    """Configure a project-local slides role for destination checks."""
    (project / "docs/slides").mkdir(parents=True, exist_ok=True)
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
    contract_path = project / "slide-spec.yaml"
    contract_path.write_text(yaml.safe_dump(assignment), encoding="utf-8")

    with pytest.raises(PublicationGateError, match="takeaway"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            final_svg(project),
            "slide-svg",
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
    contract_path = project / "slide-spec.yaml"
    source = staged_svg(tmp_path)
    destination = final_svg(project)

    result = publish_artifact(
        project,
        deck_id,
        source,
        destination,
        "slide-svg",
        slide_id,
        None,
        "worker-a",
        contract_path,
    )

    assert destination.read_bytes() == source.read_bytes()
    assert result["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert load_artifacts(project)[result["id"]]["sha256"] == result["sha256"]


def test_publish_persists_slide_assignment_and_spec_bindings(tmp_path: Path) -> None:
    """Persist slide assignment and specification identity on the artifact."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    result = publish_artifact(
        project,
        deck_id,
        staged_svg(tmp_path),
        final_svg(project),
        "slide-svg",
        slide_id,
        None,
        "worker-a",
        project / "slide-spec.yaml",
    )

    assignment_path = project / "slide-assignment.yaml"
    assignment = yaml.safe_load(assignment_path.read_text(encoding="utf-8"))
    persisted = load_artifacts(project)[result["id"]]
    assert persisted["assignment_path"] == "slide-assignment.yaml"
    assert persisted["assignment_sha256"] == contract_sha256(assignment)
    assert persisted["assignment_contract_sha256"] == persisted["assignment_sha256"]
    assert persisted["slide_spec_path"] == "slide-spec.yaml"
    assert persisted["slide_spec_sha256"] == persisted["slide_spec_contract_sha256"]
    assert persisted["contract_sha256"] == persisted["slide_spec_contract_sha256"]


def test_publish_requires_persisted_slide_assignment_even_with_owner_id(
    tmp_path: Path,
) -> None:
    """Reject owner-only slide state without a persisted assignment contract."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    state_path = project / ".research/presentations/state/slides.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["slides"][slide_id]["assignment_path"] = None
    state_path.write_text(yaml.safe_dump(state), encoding="utf-8")

    with pytest.raises(PublicationGateError, match="slide_assignment"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            final_svg(project),
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert not final_svg(project).exists()
    assert load_artifacts(project) == {}


def test_publish_requires_persisted_visual_spec_path_before_caller_document(
    tmp_path: Path,
) -> None:
    """Reject a caller visual document when module state omits its spec path."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    _configure_slides_role(project)
    set_module_status(project, module_id, "assigned")
    assignment_path = project / "assignment.yaml"
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
    create_assignment_record(
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
    state_path = project / ".research/presentations/state/visual_modules.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["visual_modules"][module_id]["visual_spec_path"] = None
    state_path.write_text(yaml.safe_dump(state), encoding="utf-8")

    with pytest.raises(PublicationGateError, match="visual_spec_path"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            project / "docs/slides/module.svg",
            "module-svg",
            module["slide_id"],
            module_id,
            "worker-a",
            project / "spec.yaml",
        )
    assert not (project / "docs/slides/module.svg").exists()
    assert load_artifacts(project) == {}


def test_publish_acquires_workflow_lock_before_production_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evaluate production state only after entering the workflow lock."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    import publish_presentation_artifact as publisher

    events: list[str] = []
    original_gate = publisher._assert_production

    @contextmanager
    def observed_lock(root: Path) -> Iterator[None]:
        events.append("lock")
        yield

    def observed_gate(root: Path, current_deck_id: str) -> None:
        events.append("production")
        original_gate(root, current_deck_id)

    monkeypatch.setattr(publisher, "_workflow_lock", observed_lock)
    monkeypatch.setattr(publisher, "_assert_production", observed_gate)
    publish_artifact(
        project,
        deck_id,
        staged_svg(tmp_path),
        final_svg(project),
        "slide-svg",
        slide_id,
        None,
        "worker-a",
        project / "slide-spec.yaml",
    )
    assert events[:2] == ["lock", "production"]


def test_publish_restores_existing_destination_and_state_mode_on_state_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore prior bytes and permission modes after a real state replace failure."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    first_source = staged_svg(tmp_path)
    publish_artifact(
        project,
        deck_id,
        first_source,
        destination,
        "slide-svg",
        slide_id,
        None,
        "worker-a",
        project / "slide-spec.yaml",
    )
    artifacts_path = project / ".research/presentations/state/artifacts.yaml"
    destination.chmod(0o640)
    artifacts_path.chmod(0o640)
    prior_destination = destination.read_bytes()
    prior_artifacts = artifacts_path.read_bytes()
    prior_destination_mode = destination.stat().st_mode & 0o777
    prior_artifacts_mode = artifacts_path.stat().st_mode & 0o777
    second_source = tmp_path / "staged-second.svg"
    second_source.write_bytes(b"changed")

    import publish_presentation_artifact as publisher
    original_replace = publisher.os.replace

    def fail_state_replace(path: Path, target: Path) -> None:
        if Path(target) == artifacts_path:
            raise OSError("state replace")
        original_replace(path, target)

    monkeypatch.setattr(publisher.os, "replace", fail_state_replace)
    with pytest.raises(PublicationGateError):
        publish_artifact(
            project,
            deck_id,
            second_source,
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )

    assert destination.read_bytes() == prior_destination
    assert artifacts_path.read_bytes() == prior_artifacts
    assert destination.stat().st_mode & 0o777 == prior_destination_mode
    assert artifacts_path.stat().st_mode & 0o777 == prior_artifacts_mode


def test_publish_reports_primary_and_rollback_directory_fsync_distinctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recover cleanly when the primary directory fsync fails once."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    import publish_presentation_artifact as publisher

    original_fsync = publisher.os.fsync
    calls = 0

    def fail_primary(file_descriptor: int) -> None:
        nonlocal calls
        try:
            target = Path(os.readlink(f"/proc/self/fd/{file_descriptor}"))
        except OSError:
            original_fsync(file_descriptor)
            return
        if target.resolve() == destination.parent.resolve():
            calls += 1
            if calls == 1:
                raise OSError("primary directory fsync")
        original_fsync(file_descriptor)

    monkeypatch.setattr(publisher.os, "fsync", fail_primary)
    with pytest.raises(PublicationGateError, match="fsync"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert calls >= 2
    assert not destination.exists()
    assert load_artifacts(project) == {}


def test_publish_aggregates_cleanup_and_rollback_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report both temporary-cleanup and rollback failures from one attempt."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    publish_artifact(
        project,
        deck_id,
        staged_svg(tmp_path),
        destination,
        "slide-svg",
        slide_id,
        None,
        "worker-a",
        project / "slide-spec.yaml",
    )
    import publish_presentation_artifact as publisher

    original_replace = publisher.os.replace
    replace_calls = 0

    def fail_publish_and_rollback(source: Path, target: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls <= 2:
            raise OSError("replace failure")
        original_replace(source, target)

    original_unlink = Path.unlink

    def fail_publication_temp_cleanup(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name.startswith(f".{destination.name}.") and ".rollback." not in path.name:
            raise OSError("cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(publisher.os, "replace", fail_publish_and_rollback)
    monkeypatch.setattr(Path, "unlink", fail_publication_temp_cleanup)
    with pytest.raises(PublicationGateError) as raised:
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    blockers = raised.value.blockers
    reasons = {str(blocker.get("reason")) for blocker in blockers}
    assert "temp_cleanup_failed" in reasons
    assert "rollback_failed" in reasons


def test_publish_module_binds_current_assignment_and_spec(tmp_path: Path) -> None:
    """Publish a module only when assignment and visual-spec identities agree."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    _configure_slides_role(project)
    (project / "docs/slides").mkdir(parents=True, exist_ok=True)
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


def test_publish_cleans_all_staged_state_temps_on_module_stage_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean artifact and module siblings when the second state stage fails."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    _configure_slides_role(project)
    set_module_status(project, module_id, "assigned")
    assignment_path = project / "assignment.yaml"
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
    create_assignment_record(
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
    import publish_presentation_artifact as publisher

    original_write = publisher.os.write

    def fail_module_stage(file_descriptor: int, payload: bytes) -> int:
        target = Path(os.readlink(f"/proc/self/fd/{file_descriptor}"))
        if target.name.startswith(".visual_modules.yaml.stage."):
            return 0
        return original_write(file_descriptor, payload)

    monkeypatch.setattr(publisher.os, "write", fail_module_stage)
    destination = project / "docs/slides/module.svg"
    with pytest.raises(PublicationGateError, match="short_write"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "module-svg",
            module["slide_id"],
            module_id,
            "worker-a",
            assignment_path,
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}
    state_dir = project / ".research/presentations/state"
    assert not list(state_dir.glob("*.stage.*.tmp"))


def test_publish_rejects_missing_persisted_module_spec(tmp_path: Path) -> None:
    """Reject a module whose persisted visual-spec binding is missing."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    _configure_slides_role(project)
    set_module_status(project, module_id, "assigned")
    assignment_path = project / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "module_id": module_id,
        "worker_type": "architecture",
        "dependencies": [],
        "spec_sha256": contract_sha256(spec),
        "inputs_resolved": True,
        "assigned_at": "2026-08-08T00:00:00Z",
        "blocker": None,
    }), encoding="utf-8")
    create_assignment_record(
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
    state_path = project / ".research/presentations/state/visual_modules.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["visual_modules"][module_id]["visual_spec_path"] = None
    state_path.write_text(yaml.safe_dump(state), encoding="utf-8")
    destination = project / "docs/slides/module.svg"
    with pytest.raises(PublicationGateError, match="visual_spec"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "module-svg",
            module["slide_id"],
            module_id,
            "worker-a",
            assignment_path,
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}


def test_publish_rejects_missing_current_module_assignment(tmp_path: Path) -> None:
    """Reject a module that has no persisted current assignment path."""
    project, deck_id, module_id, _, _ = _approved_module_project(tmp_path)
    _configure_slides_role(project)
    state_path = project / ".research/presentations/state/visual_modules.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["visual_modules"][module_id]["assignment_path"] = None
    state_path.write_text(yaml.safe_dump(state), encoding="utf-8")
    destination = project / "docs/slides/module.svg"
    with pytest.raises(PublicationGateError, match="current_assignment"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "module-svg",
            None,
            module_id,
            "worker-a",
            project / "spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}


@pytest.mark.parametrize(
    ("artifact_kind", "slide_id", "module_id"),
    [
        ("module-svg", "sld_slide", None),
        ("slide-svg", "sld_slide", "mod_20260808_abcdef"),
    ],
)
def test_publish_rejects_kind_subject_mismatch_before_writes(
    artifact_kind: str,
    slide_id: str,
    module_id: str | None,
    tmp_path: Path,
) -> None:
    """Reject artifact kinds whose subject identity is not exact."""
    project, deck_id, valid_slide_id, assignment = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    with pytest.raises(PublicationGateError, match="subject"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            artifact_kind,
            valid_slide_id if slide_id == "sld_slide" else slide_id,
            module_id,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}


def test_publish_requires_persisted_slide_spec_binding(tmp_path: Path) -> None:
    """Reject a valid caller contract when slide state omits its spec path."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    path = project / ".research/presentations/state/slides.yaml"
    state = yaml.safe_load(path.read_text(encoding="utf-8"))
    state["slides"][slide_id]["slide_spec_path"] = None
    path.write_text(yaml.safe_dump(state), encoding="utf-8")
    destination = final_svg(project)
    with pytest.raises(PublicationGateError, match="slide_spec_path"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}


def test_publish_requires_persisted_slide_digest_binding(tmp_path: Path) -> None:
    """Reject a valid caller contract when slide state omits its digest."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    path = project / ".research/presentations/state/slides.yaml"
    state = yaml.safe_load(path.read_text(encoding="utf-8"))
    state["slides"][slide_id]["slide_spec_sha256"] = None
    path.write_text(yaml.safe_dump(state), encoding="utf-8")
    destination = final_svg(project)
    with pytest.raises(PublicationGateError, match="slide_spec_sha256"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}


def test_publish_rejects_slide_producer_mismatch(tmp_path: Path) -> None:
    """Reject a producer that differs from persisted slide ownership."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    with pytest.raises(PublicationGateError, match="producer"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-b",
            project / "slide-spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}
