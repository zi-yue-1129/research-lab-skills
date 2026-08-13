"""Temporal store-contract regressions for historical artifact provenance."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
from presentation_contracts import contract_sha256
from presentation_evidence_contracts import EvidenceContractError, validate_store_record
from presentation_evidence_snapshot import EvidenceSnapshot, PlanPreimage
import presentation_evidence_projection
from presentation_active_evidence_fixtures import (
    project_real_historical_preview,
    with_preview_source,
)
from test_presentation_active_evidence import _approved_snapshot
from test_presentation_store_contracts_round3 import _DIGEST, _records, _relations


_PLAN_TWO_PATH = "decks/deck-1/plans/plan-v0002.yaml"


def _write_store(
    project: Path,
    name: str,
    records: dict[str, dict[str, Any]],
    version: int,
) -> Path:
    """Write one exact versioned presentation state store.

    Args:
        project: Fixture project root.
        name: State-store filename.
        records: ID-keyed records for the store.
        version: Exact source schema marker.

    Returns:
        The written store path.
    """
    path = project / ".research/presentations/state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    top_key = name.removesuffix(".yaml")
    path.write_text(
        yaml.safe_dump({"version": version, top_key: records}, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _artifact_records() -> dict[str, dict[str, Any]]:
    """Return plan-v1 slide and review artifacts with exact typed provenance."""
    slide_content = b"historical-plan-v1-slide"
    review_content = b"historical-plan-v1-review"
    slide_digest = hashlib.sha256(slide_content).hexdigest()
    review_digest = hashlib.sha256(review_content).hexdigest()
    slide_path = "renders/plan-v1-slide.png"
    source_sha256 = contract_sha256(
        {"paths": [slide_path], "digests": [slide_digest]}
    )
    return {
        "artifact-plan-v1-slide": {
            "id": "artifact-plan-v1-slide",
            "deck_id": "deck-1",
            "slide_id": "slide-record-v1",
            "module_id": None,
            "artifact_kind": "slide-png",
            "kind": "slide-png",
            "path": slide_path,
            "relative_path": slide_path,
            "sha256": slide_digest,
            "producer_id": "renderer",
            "produced_by": "renderer",
            "created_at": "2026-08-09T00:00:00Z",
            "plan_version": 1,
            "plan_sha256": _DIGEST,
            "slide_record_id": "slide-record-v1",
            "attempt": 1,
        },
        "artifact-plan-v1-review": {
            "id": "artifact-plan-v1-review",
            "deck_id": "deck-1",
            "slide_id": None,
            "module_id": None,
            "artifact_kind": "review-sheet",
            "kind": "review-sheet",
            "path": "renders/plan-v1-review.png",
            "relative_path": "renders/plan-v1-review.png",
            "sha256": review_digest,
            "producer_id": "renderer",
            "produced_by": "renderer",
            "created_at": "2026-08-09T00:01:00Z",
            "plan_version": 1,
            "plan_sha256": _DIGEST,
            "source_paths": [slide_path],
            "source_sha256": source_sha256,
        },
    }


def _historical_artifact_project(tmp_path: Path, version: int) -> Path:
    """Create a deck approved on plan v2 while retaining plan-v1 artifacts.

    Args:
        tmp_path: Pytest temporary directory.
        version: Uniform schema marker for every state store.

    Returns:
        The complete fixture project root.
    """
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    plan_two = {"deck_id": "deck-1", "plan_version": 2, "slides": []}
    plan_two_content = yaml.safe_dump(plan_two, sort_keys=False).encode("utf-8")
    plan_two_digest = contract_sha256(plan_two)
    plan_two_path = project / _PLAN_TWO_PATH
    plan_two_path.parent.mkdir(parents=True)
    plan_two_path.write_bytes(plan_two_content)
    deck = {
        "id": "deck-1",
        "title": "Historical provenance",
        "status": "approved",
        "created_by": "planner",
        "plan_version": 2,
        "current_plan_id": "plan-v2",
        "approved_plan_version": 2,
        "approved_plan_sha256": plan_two_digest,
    }
    plans = {
        "plan-v1": {
            "id": "plan-v1",
            "deck_id": "deck-1",
            "version": 1,
            "plan_sha256": _DIGEST,
        },
        "plan-v2": {
            "id": "plan-v2",
            "deck_id": "deck-1",
            "version": 2,
            "plan_sha256": plan_two_digest,
            "plan_path": _PLAN_TWO_PATH,
            "path": _PLAN_TWO_PATH,
            "sha256": plan_two_digest,
            "authored_by": "planner",
        },
    }
    slides = {
        "slide-record-v1": {
            "id": "slide-record-v1",
            "deck_id": "deck-1",
            "plan_slide_id": "slide-01",
            "title": "Historical slide",
            "status": "superseded",
            "created_at": "2026-08-09T00:00:00Z",
            "updated_at": "2026-08-09T00:02:00Z",
            "created_by": "producer",
            "approved_takeaway_sha256": None,
            "approved_evidence_sha256": None,
            "slide_spec_path": "specs/plan-v1-slide.yaml",
            "slide_spec_sha256": "c" * 64,
            "attempt": 1,
        }
    }
    artifact_contents = {
        "renders/plan-v1-slide.png": b"historical-plan-v1-slide",
        "renders/plan-v1-review.png": b"historical-plan-v1-review",
        "specs/plan-v1-slide.yaml": b"schema_version: 1\n",
    }
    for relative_path, content in artifact_contents.items():
        artifact_path = project / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(content)
    _write_store(project, "decks.yaml", {deck["id"]: deck}, version)
    _write_store(project, "plans.yaml", plans, version)
    _write_store(project, "slides.yaml", slides, version)
    _write_store(project, "artifacts.yaml", _artifact_records(), version)
    if version == 2:
        _write_store(project, "evidence.yaml", {}, version)
    return project


def _presentation_tree(root: Path) -> dict[str, tuple[bytes, int, int, int]]:
    """Capture exact regular-file bytes, modes, mtimes, and inodes."""
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(),
            path.stat().st_mode,
            path.stat().st_mtime_ns,
            path.stat().st_ino,
        )
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


@pytest.mark.parametrize("source_version", [0, 1, 2])
def test_migration_retains_plan_v1_artifacts_after_plan_v2_approval(
    tmp_path: Path,
    source_version: int,
) -> None:
    """Legacy conversion and v2 no-op preserve immutable plan-v1 artifacts."""
    project = _historical_artifact_project(tmp_path, source_version)
    presentations = project / ".research/presentations"
    before = _presentation_tree(presentations)
    expected_artifacts = _artifact_records()

    report = migration.migrate_state(project)

    artifact_document = yaml.safe_load(
        (presentations / "state/artifacts.yaml").read_text(encoding="utf-8")
    )
    deck_document = yaml.safe_load(
        (presentations / "state/decks.yaml").read_text(encoding="utf-8")
    )
    assert artifact_document["version"] == 2
    assert artifact_document["artifacts"] == expected_artifacts
    assert deck_document["decks"]["deck-1"]["current_plan_id"] == "plan-v2"
    assert deck_document["decks"]["deck-1"]["approved_plan_version"] == 2
    assert report["target_schema_version"] == 2
    if source_version == 2:
        assert report["changed_paths"] == []
        assert _presentation_tree(presentations) == before


def _historical_relations() -> dict[str, dict[str, Any]]:
    """Return plan-v1 artifact relations with plan v2 kept current."""
    relations = _relations()
    relations["plans"]["plan-v2"] = {
        "id": "plan-v2",
        "deck_id": "deck-1",
        "version": 2,
        "plan_sha256": "b" * 64,
    }
    relations["decks"]["deck-1"].update(
        {
            "plan_version": 2,
            "current_plan_id": "plan-v2",
            "approved_plan_version": 2,
            "approved_plan_sha256": "b" * 64,
        }
    )
    return relations


def _record_for_kind(artifact_kind: str) -> dict[str, Any]:
    """Return one exact plan-v1 artifact record of the requested kind."""
    record = deepcopy(_records()["artifacts"])
    if artifact_kind == "review-sheet":
        return record
    record.update(
        {
            "artifact_kind": "slide-png",
            "kind": "slide-png",
            "slide_id": "slide-1",
            "slide_record_id": "slide-1",
            "attempt": 1,
        }
    )
    record.pop("source_paths")
    record.pop("source_sha256")
    return record


@pytest.mark.parametrize("artifact_kind", ["slide-png", "review-sheet"])
def test_artifact_plan_provenance_resolves_historical_plan_not_current_plan(
    artifact_kind: str,
) -> None:
    """A typed artifact binds its unique immutable plan-v1 record intrinsically."""
    record = _record_for_kind(artifact_kind)

    validated = validate_store_record(
        "artifacts", record, relations=_historical_relations()
    )

    assert validated == record


@pytest.mark.parametrize("artifact_kind", ["slide-png", "review-sheet"])
@pytest.mark.parametrize(
    "mutation", ["missing", "wrong_deck", "ambiguous", "boolean_version"]
)
def test_artifact_plan_provenance_rejects_unresolved_or_ambiguous_history(
    artifact_kind: str,
    mutation: str,
) -> None:
    """Historical plan provenance must resolve uniquely within the owning deck."""
    relations = _historical_relations()
    relations["plans"].pop("plan-1")
    if mutation == "wrong_deck":
        relations["decks"]["deck-other"] = {
            "id": "deck-other",
            "title": "Other deck",
            "status": "planning",
            "created_by": "planner",
        }
        relations["plans"]["plan-v1-other"] = {
            "id": "plan-v1-other",
            "deck_id": "deck-other",
            "version": 1,
            "plan_sha256": _DIGEST,
        }
    elif mutation == "ambiguous":
        for plan_id in ("plan-v1-a", "plan-v1-b"):
            relations["plans"][plan_id] = {
                "id": plan_id,
                "deck_id": "deck-1",
                "version": 1,
                "plan_sha256": _DIGEST,
            }
    elif mutation == "boolean_version":
        relations["plans"]["plan-v1-bool"] = {
            "id": "plan-v1-bool",
            "deck_id": "deck-1",
            "version": True,
            "plan_sha256": _DIGEST,
        }

    with pytest.raises(
        EvidenceContractError,
        match="artifact|plan|provenance|resolve|unique|deck|ambiguous",
    ):
        validate_store_record(
            "artifacts",
            _record_for_kind(artifact_kind),
            relations=relations,
        )


def _advance_snapshot_to_plan_two(snapshot: EvidenceSnapshot) -> EvidenceSnapshot:
    """Advance only current plan state while retaining plan-v1 evidence."""
    plan = {
        "deck_id": "deck-1",
        "plan_version": 2,
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Exact current title",
                "key_takeaway": "Exact current takeaway.",
            }
        ],
    }
    plan_content = yaml.safe_dump(plan, sort_keys=False).encode("utf-8")
    plan_digest = contract_sha256(plan)
    stores = {name: dict(records) for name, records in snapshot.stores.items()}
    deck = dict(stores["decks"]["deck-1"])
    deck.update(
        {
            "current_plan_id": "plan-2",
            "approved_plan_version": 2,
            "approved_plan_sha256": plan_digest,
        }
    )
    stores["decks"]["deck-1"] = MappingProxyType(deck)
    stores["plans"]["plan-2"] = MappingProxyType(
        {
            "id": "plan-2",
            "deck_id": "deck-1",
            "version": 2,
            "plan_sha256": plan_digest,
            "plan_path": _PLAN_TWO_PATH,
        }
    )
    preimages = dict(snapshot.active_plan_preimages)
    preimages["plan-2"] = PlanPreimage(
        path=_PLAN_TWO_PATH,
        content=plan_content,
        mode=0o644,
        mtime_ns=0,
        sha256=hashlib.sha256(plan_content).hexdigest(),
    )
    files = dict(snapshot.file_preimages)
    files[snapshot.project_root / _PLAN_TWO_PATH] = plan_content
    return replace(
        snapshot,
        stores=MappingProxyType(
            {
                name: MappingProxyType(records)
                for name, records in stores.items()
            }
        ),
        file_preimages=MappingProxyType(files),
        active_plan_preimages=MappingProxyType(preimages),
    )


def test_active_pointer_rejects_plan_v1_artifacts_after_plan_v2_approval() -> None:
    """A retained historical preview cannot authorize the new current plan."""
    snapshot, seed_history = _approved_snapshot()
    snapshot, history = project_real_historical_preview(
        with_preview_source(snapshot), seed_history
    )
    advanced = _advance_snapshot_to_plan_two(snapshot)

    active = presentation_evidence_projection.project_active_evidence(
        advanced, history
    )

    assert active.blockers["deck-1"] == (
        {"reason": "active_preview_plan_mismatch"},
    )
