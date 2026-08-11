"""Schema-two compatibility regressions for state and plan transactions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from presentation_events import load_plans
from presentation_plan_transactions import _load_state_map
from presentation_state import StateParseError, create_deck, load_decks
from presentation_transactions import WorkflowTransaction
from presentation_workflow import register_plan


def _project(tmp_path: Path) -> Path:
    """Create a project root recognized by all presentation state helpers."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _write_store(
    project: Path, name: str, top_key: str, version: object
) -> Path:
    """Write one empty state store with a caller-selected schema marker."""
    path = project / ".research" / "presentations" / "state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": version, top_key: {}}, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _plan_document(deck_id: str) -> dict[str, Any]:
    """Return the smallest reviewed plan accepted by the registration gate."""
    return {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "purpose": "Explain schema migration.",
        "audience": "Maintainers",
        "core_narrative": "State schemas evolve safely.",
        "authored_by": "planner",
        "status": "reviewed",
        "estimated_duration_minutes": 5,
        "excluded_content": [],
        "known_gaps": [],
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Schema two",
                "purpose": "Describe the transition.",
                "key_takeaway": "Schema state is strict.",
                "intended_visual_type": "none",
                "visual_rationale": "No visual is required.",
                "speaker_message": "The marker is exact.",
                "evidence_refs": ["evidence:1"],
                "dependencies": [],
                "open_questions": [],
            }
        ],
    }


@pytest.mark.parametrize("version", [0, 1, 3, True, False, 2.0, "2"])
def test_state_plan_and_transaction_readers_reject_non_exact_schema_two(
    tmp_path: Path, version: object
) -> None:
    """All state reader boundaries reject legacy, future, bool, and float markers."""
    project = _project(tmp_path)
    decks_path = _write_store(project, "decks.yaml", "decks", version)
    plans_path = _write_store(project, "plans.yaml", "plans", version)

    with pytest.raises(StateParseError, match="Unsupported schema version"):
        load_decks(project)
    with pytest.raises(ValueError, match="invalid state document"):
        _load_state_map(plans_path, "plans")
    with WorkflowTransaction((plans_path,), project) as transaction:
        with pytest.raises(ValueError, match="Invalid transaction YAML"):
            transaction.read_yaml(plans_path, "plans")
    assert decks_path.is_file()


def test_register_plan_reads_and_writes_exact_schema_two_state(tmp_path: Path) -> None:
    """Plan registration interoperates with the schema-two state writers."""
    project = _project(tmp_path)
    deck = create_deck(project, "Schema compatibility", created_by="planner")
    source = project / "plan.yaml"
    source.write_text(
        yaml.safe_dump(_plan_document(deck["id"]), sort_keys=True), encoding="utf-8"
    )

    registered = register_plan(project, deck["id"], source, "planner")
    stored = load_plans(project)
    plans_document = yaml.safe_load(
        (project / ".research" / "presentations" / "state" / "plans.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert registered["id"] in stored
    assert plans_document["version"] == 2
