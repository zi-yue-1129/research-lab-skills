"""Schema-two publisher state-store compatibility regressions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from presentation_gates import PublicationGateError
from publish_presentation_artifact import publish_artifact
from test_publish_presentation_artifact import (
    _configure_slides_role,
    approved_assignment,
    final_svg,
    staged_svg,
)


@pytest.mark.parametrize("version", [True, 1])
def test_publish_rejects_non_v2_existing_artifact_store(
    tmp_path: Path, version: object
) -> None:
    """Publication does not overwrite a boolean or legacy artifact store marker."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    artifacts_path = project / ".research" / "presentations" / "state" / "artifacts.yaml"
    artifacts_path.write_text(
        yaml.safe_dump({"version": version, "artifacts": {}}, sort_keys=True),
        encoding="utf-8",
    )
    destination = final_svg(project)

    with pytest.raises(PublicationGateError, match="schema version|publication_failed"):
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
    assert yaml.safe_load(artifacts_path.read_text(encoding="utf-8"))["version"] == version
