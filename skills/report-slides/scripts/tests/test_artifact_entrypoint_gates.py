"""Subprocess checks for presentation artifact producer authorization."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_events import register_plan_record
from presentation_state import create_deck, set_deck_status


SCRIPTS = Path(__file__).resolve().parents[1]


def _project(tmp_path: Path) -> Path:
    """Create a temporary project root recognized by the state store."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _plan(deck_id: str) -> dict[str, Any]:
    """Return a minimal valid reviewed plan for gate fixtures."""
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


def deck_awaiting_approval(tmp_path: Path) -> tuple[Path, str]:
    """Create a valid plan whose deck remains before production approval."""
    project = _project(tmp_path)
    deck = create_deck(project, "Awaiting approval", created_by="planner-a")
    plan_path = project / "plan.yaml"
    plan = _plan(deck["id"])
    plan_path.write_text(yaml.safe_dump(plan), encoding="utf-8")
    register_plan_record(
        project,
        deck["id"],
        "plan.yaml",
        contract_sha256(plan),
        "planner-a",
    )
    set_deck_status(project, deck["id"], "content_review")
    set_deck_status(project, deck["id"], "awaiting_approval")
    return project, deck["id"]


def _run_entrypoint(
    entrypoint: str, project: Path, deck_id: str, output: Path
) -> subprocess.CompletedProcess[str]:
    """Run one supported producer with a deliberately unauthorized deck."""
    data_path = project / "slide_data.json"
    data_path.write_text(
        json.dumps({"meta": {}, "slides": [{"index": 1, "type": "title"}]}),
        encoding="utf-8",
    )
    slides = project / "slides"
    slides.mkdir()
    (slides / "slide01_title.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675"/>',
        encoding="utf-8",
    )
    image = project / "source.png"
    image.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108020000009077" \
            "53de0000000c4944415408d763f8cfc0f0000001000100" \
            "18dd8db40000000049454e44ae426082"
        )
    )
    if entrypoint == "generate":
        command = [
            sys.executable,
            str(SCRIPTS / "generate_slides.py"),
            "--data",
            str(data_path),
            "--out",
            str(output),
        ]
    elif entrypoint == "embed-pptx":
        command = [
            sys.executable,
            str(SCRIPTS / "to_pptx.py"),
            "--slides",
            str(slides),
            "--out",
            str(output / "deck.pptx"),
        ]
    elif entrypoint == "native-pptx":
        command = [
            sys.executable,
            "-m",
            "svg_to_pptx",
            "--slides",
            str(slides),
            "--out",
            str(output / "deck.pptx"),
            "--mode",
            "native",
        ]
    elif entrypoint == "review-sheet":
        command = [
            sys.executable,
            str(SCRIPTS / "render_review_sheet.py"),
            "--input",
            str(image),
            "--out",
            str(output / "review.png"),
        ]
    else:
        raise AssertionError(f"unknown entrypoint: {entrypoint}")
    command.extend(["--deck-id", deck_id, "--project-root", str(project)])
    return subprocess.run(
        command,
        cwd=SCRIPTS,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "entrypoint", ["generate", "embed-pptx", "native-pptx", "review-sheet"]
)
def test_artifact_entrypoint_writes_nothing_before_approval(
    entrypoint: str, tmp_path: Path
) -> None:
    """Reject every supported producer before it creates output paths."""
    project, deck_id = deck_awaiting_approval(tmp_path)
    output = project / "out"

    result = _run_entrypoint(entrypoint, project, deck_id, output)

    assert result.returncode == 1
    assert not output.exists()
    error = json.loads(result.stdout)
    assert error["error"] == "ProductionGateError"
