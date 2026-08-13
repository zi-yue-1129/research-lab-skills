"""Shared fixtures for producing realistic visual-module state in tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from presentation_events import create_artifact_record, create_assignment_record


def record_module_production(
    project: Path, deck_id: str, slide_id: str, module_id: str
) -> None:
    """Record the assignment and artifact a produced module really carries.

    ``presentation_state.set_module_status`` is a bare state-machine
    transition with no assignment awareness, so advancing a module without
    this leaves ``assignment_path`` and ``artifact_manifest_path`` null --
    state that the completion gate and the schema-v2 store contract both
    reject once the module leaves ``planned``.

    Args:
        project: Project root containing presentation state.
        deck_id: Deck owning the module.
        slide_id: Slide record the module belongs to.
        module_id: Module receiving the assignment and artifact.
    """
    assignment_relative = "assignments/module-a.yaml"
    assignment_path = project / assignment_relative
    assignment_path.parent.mkdir(parents=True, exist_ok=True)
    assignment_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "module_id": module_id,
                "worker_type": "architecture",
                "dependencies": [],
                "spec_sha256": "a" * 64,
                "inputs_resolved": True,
                "assigned_at": "2026-08-08T00:00:00Z",
                "blocker": None,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    create_assignment_record(
        project,
        deck_id,
        module_id=module_id,
        assignment_path=assignment_relative,
        worker_id="worker-a",
        worker_type="architecture",
        spec_sha256="a" * 64,
        slide_id=slide_id,
    )
    artifact_relative = "modules/module-a.svg"
    artifact_bytes = b"module-a"
    artifact_path = project / artifact_relative
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(artifact_bytes)
    create_artifact_record(
        project,
        deck_id,
        "module-svg",
        artifact_relative,
        hashlib.sha256(artifact_bytes).hexdigest(),
        "worker-a",
        module_id=module_id,
        slide_id=slide_id,
    )
