"""Shared fixtures for producing realistic visual-module state in tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

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
    create_assignment_record(
        project,
        deck_id,
        module_id=module_id,
        assignment_path="assignments/module-a.yaml",
        worker_id="worker-a",
        worker_type="architecture",
        spec_sha256="a" * 64,
        slide_id=slide_id,
    )
    create_artifact_record(
        project,
        deck_id,
        "module-svg",
        "modules/module-a.svg",
        hashlib.sha256(b"module-a").hexdigest(),
        "worker-a",
        module_id=module_id,
        slide_id=slide_id,
    )
