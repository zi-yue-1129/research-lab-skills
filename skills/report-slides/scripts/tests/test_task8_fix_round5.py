"""RED tests for Task 8 migration evidence binding and nullability scope."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
from migration_scope import MigrationError, validate_record_paths
from render_plan_preview import _canonical_source_digest


STORE_TOP_KEYS = {
    "decks.yaml": "decks",
    "plans.yaml": "plans",
    "slides.yaml": "slides",
}


def _project(tmp_path: Path) -> Path:
    """Create a minimal Git project recognized by migration."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _presentations(project: Path) -> Path:
    """Return the presentation-state root."""
    return project / ".research" / "presentations"


def _write_store(project: Path, name: str, records: Any, version: int = 0) -> None:
    """Write one minimal migration state store."""
    path = _presentations(project) / "state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": version, STORE_TOP_KEYS[name]: records}, sort_keys=False),
        encoding="utf-8",
    )


def _canonical_digest(value: dict[str, Any]) -> str:
    """Compute one canonical producer contract digest independently."""
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _slide_record(
    *,
    status: str = "passed",
    slide_spec_path: str | None = "contracts/slide-spec.yaml",
) -> dict[str, Any]:
    """Return the exact public slide record shape used by the state API."""
    return {
        "id": "sld-round5",
        "deck_id": "deck-round5",
        "plan_slide_id": "slide-01",
        "title": "Evidence changes decisions",
        "status": status,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
        "created_by": "user",
        "approved_takeaway_sha256": None,
        "approved_evidence_sha256": None,
        "slide_spec_path": slide_spec_path,
        "slide_spec_sha256": None,
        "attempt": 1,
    }


def _module_record() -> dict[str, Any]:
    """Return the exact public visual-module record shape."""
    return {
        "id": "mod-round5",
        "slide_id": "sld-round5",
        "module_key": "input",
        "module_type": "architecture",
        "dependencies": [],
        "status": "planned",
        "visual_spec_path": None,
        "assignment_path": None,
        "artifact_manifest_path": None,
        "attempt": 1,
        "supersedes_module_id": None,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
        "created_by": "user",
    }


def _draft_event(project: Path) -> dict[str, Any]:
    """Create one current workflow-shaped draft-preview event and files."""
    render_dir = project / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    slide_path = render_dir / "slide-01.png"
    contact_path = render_dir / "contact-sheet.png"
    slide_path.write_bytes(b"slide-png")
    contact_path.write_bytes(b"contact-png")
    slide_relative = "renders/slide-01.png"
    contact_relative = "renders/contact-sheet.png"
    slide_digest = hashlib.sha256(slide_path.read_bytes()).hexdigest()
    contact_digest = hashlib.sha256(contact_path.read_bytes()).hexdigest()
    source_sha256 = _canonical_source_digest([slide_relative], [slide_digest])
    plan_sha256 = "1" * 64
    deck_id = "deck-round5"
    preview = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "plan_sha256": plan_sha256,
        "rendered_slide_paths": [{
            "slide_id": "slide-01",
            "path": slide_relative,
            "slide_record_id": "sld-round5",
            "attempt": 1,
        }],
        "contact_sheet_path": contact_relative,
        "slides": [{
            "slide_id": "slide-01",
            "title": "Evidence changes decisions",
            "key_takeaway": "Evidence changes decisions.",
        }],
        "artifact_digests": {
            slide_relative: slide_digest,
            contact_relative: contact_digest,
        },
        "artifact_bindings": {
            slide_relative: {
                "kind": "rendered_slide",
                "deck_id": deck_id,
                "slide_id": "slide-01",
                "plan_version": 1,
                "plan_sha256": plan_sha256,
                "producer_id": "renderer",
                "slide_record_id": "sld-round5",
                "attempt": 1,
            },
            contact_relative: {
                "kind": "contact_sheet",
                "deck_id": deck_id,
                "plan_version": 1,
                "plan_sha256": plan_sha256,
                "producer_id": "renderer",
                "source_paths": [slide_relative],
                "source_sha256": source_sha256,
            },
        },
    }
    return {
        **preview,
        "event": "draft_preview",
        "id": "draft-round5",
        "preview_sha256": _canonical_digest(preview),
        "ts": "2026-08-09T00:00:00Z",
    }


def _write_event(project: Path, event: dict[str, Any]) -> None:
    """Write one event shard containing the supplied event."""
    path = _presentations(project) / "events" / "2026-08-09.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")


def _legacy_project(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Create a legacy project with one current draft-preview event."""
    project = _project(tmp_path)
    event = _draft_event(project)
    _write_store(project, "decks.yaml", {
        event["deck_id"]: {
            "id": event["deck_id"],
            "title": "Round five",
            "status": "planning",
            "created_by": "test",
        },
    })
    slide_spec = project / "contracts" / "slide-spec.yaml"
    slide_spec.parent.mkdir(parents=True)
    slide_spec.write_text("schema_version: 1\n", encoding="utf-8")
    slide = _slide_record()
    _write_store(project, "slides.yaml", {slide["id"]: slide})
    _write_event(project, event)
    return project, event


@pytest.mark.parametrize("mutation", [
    "digest_mismatch",
    "missing_digest",
    "extra_digest",
    "binding_deck",
    "binding_slide",
    "binding_plan",
    "binding_record",
    "source_paths",
    "source_digest",
    "tampered_source",
])
def test_draft_preview_evidence_is_bound_and_recomputed(
    tmp_path: Path, mutation: str
) -> None:
    """Forged or internally inconsistent draft-preview evidence is rejected."""
    project, event = _legacy_project(tmp_path)
    slide_path = "renders/slide-01.png"
    contact_path = "renders/contact-sheet.png"
    if mutation == "digest_mismatch":
        event["artifact_digests"][slide_path] = "0" * 64
    elif mutation == "missing_digest":
        event["artifact_digests"].pop(contact_path)
    elif mutation == "extra_digest":
        event["artifact_digests"]["renders/extra.png"] = "0" * 64
    elif mutation == "binding_deck":
        event["artifact_bindings"][slide_path]["deck_id"] = "deck-forged"
    elif mutation == "binding_slide":
        event["artifact_bindings"][slide_path]["slide_id"] = "slide-forged"
    elif mutation == "binding_plan":
        event["artifact_bindings"][slide_path]["plan_sha256"] = "2" * 64
    elif mutation == "binding_record":
        event["artifact_bindings"][slide_path]["slide_record_id"] = "sld-stale"
    elif mutation == "source_paths":
        event["artifact_bindings"][contact_path]["source_paths"] = [contact_path]
    elif mutation == "source_digest":
        event["artifact_bindings"][contact_path]["source_sha256"] = "3" * 64
    elif mutation == "tampered_source":
        (project / slide_path).write_bytes(b"tampered-slide")
    _write_event(project, event)

    with pytest.raises(MigrationError, match="digest|binding|source|artifact|path"):
        migration.migrate_state(project, dry_run=True)


@pytest.mark.parametrize("dry_run", [False, True])
def test_current_workflow_shaped_draft_preview_is_migration_compatible(
    tmp_path: Path, dry_run: bool
) -> None:
    """A complete canonical draft-preview event remains valid for migration."""
    project, event = _legacy_project(tmp_path)

    report = migration.migrate_state(project, dry_run=dry_run)

    assert report["migrated_ids"] == [event["deck_id"], "sld-round5"]
    assert report["blocked_ids"] == []


def test_assignment_record_rejects_null_assignment_path(tmp_path: Path) -> None:
    """An assignment record cannot claim a missing assignment document."""
    project = _project(tmp_path)
    with pytest.raises(MigrationError, match="assignment_path"):
        validate_record_paths(project, {
            "id": "asn-1",
            "deck_id": "deck-1",
            "module_id": "mod-1",
            "assignment_path": None,
            "status": "assigned",
        })


def test_assignment_event_rejects_null_assignment_path(tmp_path: Path) -> None:
    """An immutable assignment event cannot contain a null assignment path."""
    project = _project(tmp_path)
    with pytest.raises(MigrationError, match="assignment_path"):
        validate_record_paths(project, {
            "event": "assignment_created",
            "id": "evt-1",
            "deck_id": "deck-1",
            "module_id": "mod-1",
            "assignment_path": None,
        })


@pytest.mark.parametrize("field", [
    "slide_spec_path",
    "visual_spec_path",
    "assignment_path",
    "artifact_manifest_path",
])
def test_nullable_path_is_rejected_outside_planned_slide_or_module(
    tmp_path: Path, field: str
) -> None:
    """A nullable path name alone does not grant permission to use null."""
    project = _project(tmp_path)
    with pytest.raises(MigrationError, match=field):
        validate_record_paths(project, {"id": "record-1", "status": "planned", field: None})


def test_planned_slide_and_module_placeholders_retain_documented_nulls(tmp_path: Path) -> None:
    """Public planned slide/module records may retain documented null paths."""
    project = _project(tmp_path)
    validate_record_paths(
        project,
        _slide_record(status="planned", slide_spec_path=None),
        store_name="slides",
    )
    validate_record_paths(
        project,
        _module_record(),
        store_name="visual_modules",
    )


@pytest.mark.parametrize("record", [
    {
        "id": "sld-1",
        "deck_id": "deck-1",
        "plan_slide_id": "slide-01",
        "title": "Evidence",
        "status": "producing",
        "slide_spec_path": None,
    },
    {
        "id": "mod-1",
        "slide_id": "sld-1",
        "module_key": "input",
        "module_type": "architecture",
        "status": "review_required",
        "visual_spec_path": None,
        "assignment_path": None,
        "artifact_manifest_path": None,
    },
])
def test_later_slide_or_module_lifecycle_requires_paths(
    tmp_path: Path, record: dict[str, Any]
) -> None:
    """Once production starts, previously nullable evidence paths are required."""
    project = _project(tmp_path)
    with pytest.raises(MigrationError, match="path|nullable"):
        validate_record_paths(project, record)
