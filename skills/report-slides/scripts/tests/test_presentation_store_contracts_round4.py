"""Reviewer counterexamples for complete schema-v2 store contracts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
from presentation_evidence_contracts import EvidenceContractError, validate_store_record
from presentation_events import (
    create_artifact_record,
    create_revision_request,
    load_artifacts,
    load_plans,
    load_revision_requests,
    register_plan_record,
)
from presentation_state import (
    create_deck,
    create_slide,
    create_visual_module,
    load_decks,
    load_slides,
    load_visual_modules,
)
from test_evidence_v2_migration_review import _v2_completed_project
from test_presentation_store_contracts_round3 import _DIGEST, _records, _relations


def _full_status_record(store_name: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return a full record whose non-status lifecycle fields are valid."""
    record = deepcopy(_records()[store_name])
    relations = _relations()
    if store_name == "slides":
        record.update({"slide_spec_path": "specs/slide.yaml", "slide_spec_sha256": _DIGEST})
    else:
        record.update(
            {
                "visual_spec_path": "specs/module.yaml",
                "visual_spec_sha256": _DIGEST,
                "assignment_path": "work/assignment.yaml",
                "artifact_manifest_path": "artifacts/module.yaml",
            }
        )
    return record, relations


@pytest.mark.parametrize("store_name", ["slides", "visual_modules"])
def test_v2_full_shape_rejects_invalid_unit_status(store_name: str) -> None:
    """The target-schema branch must apply the real lifecycle enum."""
    record, relations = _full_status_record(store_name)
    record["status"] = "forged-authorization"

    with pytest.raises(EvidenceContractError, match="status|lifecycle|invalid"):
        validate_store_record(store_name, record, relations=relations)


def test_public_v2_noop_rejects_full_shape_invalid_slide_status(tmp_path: Path) -> None:
    """Public migration cannot report a clean no-op for an invalid full slide."""
    project = _v2_completed_project(tmp_path)
    slides_path = project / ".research/presentations/state/slides.yaml"
    document = yaml.safe_load(slides_path.read_text(encoding="utf-8"))
    document["slides"]["slide-record-1"]["status"] = "forged-authorization"
    slides_path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")

    with pytest.raises(Exception, match="status|lifecycle|invalid"):
        migration.migrate_state(project)


@pytest.mark.parametrize(
    "mutation",
    [
        "forged_kind",
        "missing_review_sheet_provenance",
        "dangling_slide_record",
    ],
)
def test_v2_artifact_contract_rejects_kind_specific_provenance(mutation: str) -> None:
    """Artifact kind and provenance cannot be selected by a loose field subset."""
    record = deepcopy(_records()["artifacts"])
    relations = _relations()
    if mutation == "forged_kind":
        record["artifact_kind"] = record["kind"] = "forged-authorization"
    elif mutation == "missing_review_sheet_provenance":
        record.pop("source_sha256")
    else:
        record.update(
            {
                "artifact_kind": "slide-png",
                "kind": "slide-png",
                "slide_id": "slide-1",
                "slide_record_id": "slide-missing",
                "attempt": 1,
            }
        )
        record.pop("source_paths")
        record.pop("source_sha256")

    with pytest.raises(EvidenceContractError, match="artifact|kind|provenance|slide"):
        validate_store_record("artifacts", record, relations=relations)


def _slide_retry_with_missing_revision() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return a valid-shaped slide retry with one dangling revision request."""
    record = deepcopy(_records()["slides"])
    record.pop("updated_at")
    record.update(
        {
            "id": "slide-retry",
            "attempt": 2,
            "supersedes_slide_id": "slide-1",
            "revision_request_id": "revision-missing",
            "revision_kind": "slide_retry",
        }
    )
    return record, _relations()


@pytest.mark.parametrize(
    ("store_name", "mutation"),
    [
        ("decks", "dangling_current_plan"),
        ("slides", "dangling_revision"),
        ("visual_modules", "dangling_dependency"),
        ("assignments", "dangling_dependency"),
        ("revision_requests", "dangling_supersedes"),
    ],
)
def test_v2_contract_rejects_every_dangling_relation(
    store_name: str, mutation: str
) -> None:
    """Every declared state identifier must resolve in its authoritative store."""
    relations = _relations()
    if store_name == "slides":
        record, relations = _slide_retry_with_missing_revision()
    else:
        record = deepcopy(_records()[store_name])
        if mutation == "dangling_current_plan":
            record["current_plan_id"] = "plan-missing"
        elif mutation == "dangling_dependency":
            record["dependencies"] = ["module-missing"]
        else:
            record["supersedes"] = "slide-missing"

    with pytest.raises(EvidenceContractError, match="relation|resolve|owner|missing"):
        validate_store_record(store_name, record, relations=relations)


@pytest.mark.parametrize("store_name", ["visual_modules", "assignments", "revision_requests"])
def test_v2_contract_rejects_resolved_cross_deck_secondary_relations(
    store_name: str,
) -> None:
    """Secondary dependency and supersession links cannot cross deck ownership."""
    relations = _relations()
    relations["decks"]["deck-cross"] = {
        "id": "deck-cross",
        "title": "Cross",
        "status": "planning",
        "created_by": "producer",
    }
    relations["slides"]["slide-cross"] = {
        "id": "slide-cross",
        "deck_id": "deck-cross",
        "plan_slide_id": "slide-cross",
        "title": "Cross",
        "status": "planned",
    }
    relations["visual_modules"]["module-cross"] = {
        "id": "module-cross",
        "slide_id": "slide-cross",
        "module_key": "cross",
        "module_type": "architecture",
        "dependencies": [],
        "status": "planned",
    }
    record = deepcopy(_records()[store_name])
    if store_name in {"visual_modules", "assignments"}:
        record["dependencies"] = ["module-cross"]
    else:
        record["supersedes"] = "slide-cross"

    with pytest.raises(EvidenceContractError, match="owner|deck|relation"):
        validate_store_record(store_name, record, relations=relations)


def test_public_schema_v2_producer_shapes_validate_without_defaults(tmp_path: Path) -> None:
    """Records returned by public producers remain positive target-schema examples."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    deck = create_deck(project, "Producer deck", created_by="producer")
    plan = register_plan_record(
        project,
        deck["id"],
        "decks/producer/plan-v0001.yaml",
        _DIGEST,
        "producer",
    )
    slide = create_slide(project, deck["id"], "slide-01", "Producer slide", "producer")
    module = create_visual_module(
        project, slide["id"], "hero", "architecture", created_by="producer"
    )
    artifact = create_artifact_record(
        project,
        deck["id"],
        "module-svg",
        "artifacts/module.svg",
        _DIGEST,
        "producer",
        module_id=module["id"],
    )
    revision = create_revision_request(
        project, "slide", slide["id"], "reviewer", "Revise labels."
    )
    relations = {
        "decks": load_decks(project),
        "plans": load_plans(project),
        "slides": load_slides(project),
        "visual_modules": load_visual_modules(project),
        "artifacts": load_artifacts(project),
        "revision_requests": load_revision_requests(project),
    }
    records = {
        "decks": relations["decks"][deck["id"]],
        "plans": relations["plans"][plan["id"]],
        "slides": relations["slides"][slide["id"]],
        "visual_modules": relations["visual_modules"][module["id"]],
        "artifacts": relations["artifacts"][artifact["id"]],
        "revision_requests": relations["revision_requests"][revision["id"]],
    }

    for store_name, record in records.items():
        assert validate_store_record(store_name, record, relations=relations) == record
