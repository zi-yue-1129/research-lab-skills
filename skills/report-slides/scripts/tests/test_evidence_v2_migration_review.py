"""Review-regression tests for schema-v2 evidence migration validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
from presentation_contracts import contract_sha256
from presentation_evidence_cas import cas_relative_path
from presentation_evidence_contracts import envelope_sha256
from presentation_evidence_projection import ProjectionError
from presentation_evidence_snapshot import build_snapshot


def _project(tmp_path: Path) -> Path:
    """Create one recognized project root."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _write_store(
    project: Path, name: str, records: dict[str, dict[str, Any]], version: int
) -> Path:
    """Write one versioned presentation store."""
    top_key = name.removesuffix(".yaml")
    path = project / ".research/presentations/state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": version, top_key: records}, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _tree(root: Path) -> dict[str, tuple[bytes, int, int, int]]:
    """Capture exact regular-file identity and metadata beneath a root."""
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(),
            path.stat().st_mode,
            path.stat().st_mtime_ns,
            path.stat().st_ino,
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def _v2_completed_project(tmp_path: Path) -> Path:
    """Create valid current plan state with no completion pointer."""
    project = _project(tmp_path)
    plan = {
        "deck_id": "deck-1",
        "plan_version": 1,
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Current",
                "key_takeaway": "Exact.",
            }
        ],
    }
    digest = contract_sha256(plan)
    plan_path = project / "decks/deck-1/plans/plan-v0001.yaml"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    _write_store(
        project,
        "decks.yaml",
        {
            "deck-1": {
                "id": "deck-1",
                "title": "Deck",
                "status": "completed",
                "current_plan_id": "plan-1",
                "approved_plan_version": 1,
                "approved_plan_sha256": digest,
                "draft_preview_evidence_id": None,
                "draft_approval_evidence_id": None,
                "completion_evidence_id": None,
            }
        },
        2,
    )
    _write_store(
        project,
        "plans.yaml",
        {
            "plan-1": {
                "id": "plan-1",
                "deck_id": "deck-1",
                "version": 1,
                "plan_sha256": digest,
                "plan_path": "decks/deck-1/plans/plan-v0001.yaml",
            }
        },
        2,
    )
    _write_store(
        project,
        "slides.yaml",
        {
            "slide-record-1": {
                "id": "slide-record-1",
                "deck_id": "deck-1",
                "plan_slide_id": "slide-01",
                "title": "Current",
                "status": "passed",
                "created_at": "2026-08-09T00:00:00Z",
                "updated_at": "2026-08-09T00:00:00Z",
                "created_by": "producer",
                "approved_takeaway_sha256": None,
                "approved_evidence_sha256": None,
                "slide_spec_path": "specs/slide-01.yaml",
                "slide_spec_sha256": "2" * 64,
                "attempt": 1,
            }
        },
        2,
    )
    _write_store(project, "evidence.yaml", {}, 2)
    return project


def test_v2_completed_missing_pointer_is_blocked_without_tree_mutation(
    tmp_path: Path,
) -> None:
    """Target-schema analysis validates current state while remaining read-only."""
    project = _v2_completed_project(tmp_path)
    presentations = project / ".research/presentations"
    before = _tree(presentations)

    report = migration.migrate_state(project)

    assert report["blocked_ids"] == ["deck-1"]
    assert any(
        blocker["reason"] == "missing_completion_evidence"
        for blocker in report["blockers"]["deck-1"]
    )
    assert report["changed_paths"] == []
    assert _tree(presentations) == before


def test_migration_rejects_unknown_legacy_record_field(tmp_path: Path) -> None:
    """Every migrated mutable record uses an exact shared record contract."""
    project = _project(tmp_path)
    _write_store(
        project,
        "decks.yaml",
        {
            "deck-1": {
                "id": "deck-1",
                "title": "Deck",
                "status": "planning",
                "created_by": "planner",
                "forged_authorization": True,
            }
        },
        1,
    )
    _write_store(project, "slides.yaml", {}, 1)

    with pytest.raises(Exception, match="forged_authorization|unknown|field"):
        migration.migrate_state(project)


def test_legacy_missing_preview_bytes_become_unavailable_not_invalid(
    tmp_path: Path,
) -> None:
    """Missing historical bytes preserve intrinsic history as unavailable."""
    from test_presentation_evidence_projection import _historical_project

    project, preview, _ = _historical_project(tmp_path)
    for relative in ("evidence/slide-01.png", "evidence/contact-sheet.png"):
        (project / relative).unlink()

    report = migration.migrate_state(project)
    evidence = yaml.safe_load(
        (project / ".research/presentations/state/evidence.yaml").read_text(
            encoding="utf-8"
        )
    )["evidence"]

    projected = next(
        item for item in evidence.values() if item["source_event_id"] == preview["id"]
    )
    assert projected["availability"] == "historical_unavailable"
    assert report["target_schema_version"] == 2


def test_migration_rejects_forged_completion_digest(tmp_path: Path) -> None:
    """Malformed historical completion identity is never silently omitted."""
    from test_presentation_evidence_projection import _historical_project

    project, _, event_path = _historical_project(tmp_path, completion=True)
    events = [json.loads(line) for line in event_path.read_text().splitlines()]
    completion = next(event for event in events if event["event"] == "deck_completion")
    completion["completion_sha256"] = "0" * 64
    event_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(ProjectionError, match="completion_sha256|digest"):
        migration.migrate_state(project)


def test_migration_rejects_non_json_visual_review(tmp_path: Path) -> None:
    """Standalone review evidence requires authoritative parsed review bytes."""
    from test_presentation_evidence_projection import _historical_project

    project, _, event_path = _historical_project(tmp_path, completion=True)
    events = [json.loads(line) for line in event_path.read_text().splitlines()]
    review = next(event for event in events if event["event"] == "visual_review")
    content = b"not-json"
    (project / review["visual_review_path"]).write_bytes(content)
    review["visual_review_sha256"] = hashlib.sha256(content).hexdigest()
    event_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(ProjectionError, match="visual review|JSON|json"):
        migration.migrate_state(project)


def test_v2_snapshot_reads_existing_canonical_cas_without_mutation(
    tmp_path: Path,
) -> None:
    """Target-schema validation captures persisted CAS references read-only."""
    project = _project(tmp_path)
    content = b"persisted-cas"
    digest = hashlib.sha256(content).hexdigest()
    reference = {
        "sha256": digest,
        "cas_path": cas_relative_path(digest).as_posix(),
        "artifact_kind": "rendered_slide",
        "subject_id": "slide-01",
        "original_path": "renders/slide-01.png",
    }
    envelope: dict[str, Any] = {
        "id": "preview-1", "schema_version": 2,
        "evidence_kind": "draft_preview", "deck_id": "deck-1",
        "plan_id": "plan-1", "plan_version": 1, "plan_sha256": "1" * 64,
        "subject_ids": ["slide-01"], "producer_id": "producer",
        "artifact_refs": [reference], "source_event_id": "event-preview-1",
        "created_at": "2026-08-09T00:00:00Z", "availability": "available",
    }
    envelope["evidence_sha256"] = envelope_sha256(envelope)
    _write_store(project, "evidence.yaml", {"preview-1": envelope}, 2)
    cas_path = project / cas_relative_path(digest)
    cas_path.parent.mkdir(parents=True)
    cas_path.write_bytes(content)
    before = _tree(project / ".research/presentations")

    snapshot = build_snapshot(project)

    assert snapshot.artifact_objects[reference["cas_path"]].content == content
    assert _tree(project / ".research/presentations") == before
