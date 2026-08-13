"""Schema-two publisher state-store compatibility regressions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from presentation_evidence_workflow import MigrationRequiredError
from publish_presentation_artifact import publish_artifact
from test_presentation_evidence_workflow import _tree_preimage
from test_publish_presentation_artifact import (
    _configure_slides_role,
    approved_assignment,
    final_svg,
    staged_svg,
)


@pytest.mark.parametrize(
    ("marker", "expected_source"),
    [
        (0, 0),
        (1, 1),
        (True, "bool"),
        (3, 3),
        ({"version": 2, "schema_version": 1}, "mixed"),
    ],
)
def test_publish_propagates_typed_migration_error_without_writing(
    tmp_path: Path, marker: object, expected_source: int | str
) -> None:
    """Propagate schema migration metadata before publisher side effects.

    Translating this boundary into ``PublicationGateError`` hides the required
    source/target versions and permits a CLI wrapper to lose typed metadata.

    Args:
        tmp_path: Per-test temporary project directory.
        marker: Legacy, boolean, future, or mixed artifact-store header.
        expected_source: Exact typed source marker expected by callers.
    """
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    document = marker if isinstance(marker, dict) else {"version": marker}
    state_root = project / ".research" / "presentations" / "state"
    for state_path in sorted(state_root.glob("*.yaml")):
        state_document = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        assert isinstance(state_document, dict)
        state_document.pop("version", None)
        state_document.pop("schema_version", None)
        state_path.write_text(
            yaml.safe_dump({**state_document, **document}, sort_keys=True),
            encoding="utf-8",
        )
    destination = final_svg(project)
    before = _tree_preimage(project)

    with pytest.raises(MigrationRequiredError) as error:
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

    assert error.value.source_schema_version == expected_source
    assert error.value.target_schema_version == 2
    assert not destination.exists()
    assert _tree_preimage(project) == before
