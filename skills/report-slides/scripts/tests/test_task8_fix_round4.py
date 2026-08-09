"""Regression tests for Task 8 migration fix rounds four and five."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
from migration_scope import validate_record_paths
from presentation_state import create_deck, create_slide, create_visual_module
from render_plan_preview import _canonical_source_digest


STORE_TOP_KEYS = {
    "decks.yaml": "decks",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
}


def _project(tmp_path: Path) -> Path:
    """Create a minimal Git project recognized by the migration."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _presentations(project: Path) -> Path:
    """Return the presentation state root."""
    return project / ".research" / "presentations"


def _state_dir(project: Path) -> Path:
    """Return the mutable state directory."""
    return _presentations(project) / "state"


def _write_store(project: Path, name: str, records: Any, version: int = 0) -> Path:
    """Write one migration state store fixture."""
    path = _state_dir(project) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": version, STORE_TOP_KEYS[name]: records}, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _snapshot(root: Path) -> dict[str, tuple[str, bytes, int, int]]:
    """Capture exact files, links, modes, and mtimes below a root."""
    result: dict[str, tuple[str, bytes, int, int]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = ("symlink", os.readlink(path).encode(), 0, 0)
        elif path.is_file():
            metadata = path.stat()
            result[relative] = (
                "file",
                path.read_bytes(),
                metadata.st_mode & 0o777,
                metadata.st_mtime_ns,
            )
        elif path.is_dir():
            metadata = path.stat()
            result[relative] = ("directory", b"", metadata.st_mode & 0o777, metadata.st_mtime_ns)
    return result


def _canonical_digest(value: dict[str, Any]) -> str:
    """Compute one canonical producer contract digest independently."""
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _current_slide_record(deck_id: str = "deck-round4") -> dict[str, Any]:
    """Return the exact current public slide record bound by the preview."""
    return {
        "id": "sld-round4",
        "deck_id": deck_id,
        "plan_slide_id": "slide-01",
        "title": "Evidence changes decisions",
        "status": "passed",
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
        "created_by": "user",
        "approved_takeaway_sha256": None,
        "approved_evidence_sha256": None,
        "slide_spec_path": "contracts/slide-spec.yaml",
        "slide_spec_sha256": None,
        "attempt": 1,
    }


def _draft_preview_event(project: Path, *, deck_id: str = "deck-round4") -> dict[str, Any]:
    """Create one current workflow-shaped draft-preview event and its files."""
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
    plan_digest = "1" * 64
    source_digest = _canonical_source_digest([slide_relative], [slide_digest])
    preview = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "plan_sha256": plan_digest,
        "rendered_slide_paths": [{
            "slide_id": "slide-01",
            "path": slide_relative,
            "slide_record_id": "sld-round4",
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
                "plan_sha256": plan_digest,
                "producer_id": "renderer",
                "slide_record_id": "sld-round4",
                "attempt": 1,
            },
            contact_relative: {
                "kind": "contact_sheet",
                "deck_id": deck_id,
                "plan_version": 1,
                "plan_sha256": plan_digest,
                "producer_id": "renderer",
                "source_paths": [slide_relative],
                "source_sha256": source_digest,
            },
        },
    }
    return {
        **preview,
        "event": "draft_preview",
        "id": "draft-round4",
        "preview_sha256": _canonical_digest(preview),
        "ts": "2026-08-09T00:00:00Z",
    }


def _write_event(project: Path, event: dict[str, Any]) -> Path:
    """Write one JSONL draft-preview event shard."""
    path = _presentations(project) / "events" / "2026-08-09.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _legacy_event_project(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Create a legacy state project containing a real draft-preview event."""
    project = _project(tmp_path)
    deck_id = "deck-round4"
    _write_store(project, "decks.yaml", {
        deck_id: {"id": deck_id, "title": "Round four", "status": "planning"},
    })
    slide_spec = project / "contracts" / "slide-spec.yaml"
    slide_spec.parent.mkdir(parents=True)
    slide_spec.write_text("schema_version: 1\n", encoding="utf-8")
    slide = _current_slide_record(deck_id)
    _write_store(project, "slides.yaml", {slide["id"]: slide})
    event = _draft_preview_event(project, deck_id=deck_id)
    _write_event(project, event)
    return project, event


@pytest.mark.parametrize("field", ["artifact_digests", "artifact_bindings"])
@pytest.mark.parametrize(
    "bad_key",
    ["../outside.png", "/etc/passwd", "renders/missing.png", "renders/escape.png"],
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_draft_preview_path_keyed_fields_reject_unsafe_keys_before_mutation(
    tmp_path: Path,
    field: str,
    bad_key: str,
    dry_run: bool,
) -> None:
    """Draft-preview mapping keys must be existing canonical project files."""
    project, event = _legacy_event_project(tmp_path)
    if bad_key == "renders/escape.png":
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"outside")
        (project / bad_key).symlink_to(outside)
    mapping = event[field]
    original_key = next(iter(mapping))
    mapping[bad_key] = mapping.pop(original_key)
    (_presentations(project) / "events" / "2026-08-09.jsonl").write_text(
        json.dumps(event, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = _snapshot(_presentations(project))

    with pytest.raises(migration.MigrationError, match="path|canonical|symlink|target"):
        migration.migrate_state(project, dry_run=dry_run)

    assert _snapshot(_presentations(project)) == before


@pytest.mark.parametrize("field", ["artifact_digests", "artifact_bindings"])
def test_draft_preview_path_keyed_fields_reject_non_string_keys(tmp_path: Path, field: str) -> None:
    """Path-keyed mappings reject non-string keys without relying on JSON coercion."""
    project, event = _legacy_event_project(tmp_path)
    mapping = dict(event[field])
    original_key = next(iter(mapping))
    mapping[1] = mapping.pop(original_key)
    event[field] = mapping
    with pytest.raises(migration.MigrationError, match="mapping key|path|canonical"):
        validate_record_paths(
            project,
            event,
            store_name="events",
            current_slides={"sld-round4": _current_slide_record()},
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("artifact_digests", "not-a-digest"),
        ("artifact_bindings", []),
    ],
)
def test_draft_preview_mapping_values_keep_structural_validation(
    tmp_path: Path, field: str, bad_value: Any
) -> None:
    """Path-key validation must not bypass digest/binding value checks."""
    project, event = _legacy_event_project(tmp_path)
    key = next(iter(event[field]))
    event[field][key] = bad_value
    with pytest.raises(migration.MigrationError, match="digest|binding|mapping|shape"):
        validate_record_paths(
            project,
            event,
            store_name="events",
            current_slides={"sld-round4": _current_slide_record()},
        )


def test_unknown_mapping_fields_do_not_gain_path_key_semantics(tmp_path: Path) -> None:
    """Only explicitly named mapping fields interpret keys as paths."""
    project, _ = _legacy_event_project(tmp_path)
    value = {"unknown_mapping": {"../not-a-path-key": "opaque"}}
    validate_record_paths(project, value)


@pytest.mark.parametrize("dry_run", [False, True])
def test_valid_draft_preview_path_keyed_event_migrates_without_false_positive(
    tmp_path: Path, dry_run: bool
) -> None:
    """A complete current draft-preview event remains migration-compatible."""
    project, _event = _legacy_event_project(tmp_path)
    before = _snapshot(_presentations(project))

    report = migration.migrate_state(project, dry_run=dry_run)

    assert report["source_schema_version"] == 0
    assert report["target_schema_version"] == 1
    assert report["migrated_ids"] == ["deck-round4", "sld-round4"]
    assert report["blocked_ids"] == []
    assert report["blockers"] == {}
    if dry_run:
        assert report["changed_paths"] == []
        assert _snapshot(_presentations(project)) == before
    else:
        assert report["changed_paths"]
        migrated = yaml.safe_load((_state_dir(project) / "decks.yaml").read_text(encoding="utf-8"))
        assert migrated["version"] == 1


def test_public_state_constructors_with_nullable_paths_are_target_noops(tmp_path: Path) -> None:
    """Current public constructors retain nullable paths on exact v1 no-op migration."""
    project = _project(tmp_path)
    deck = create_deck(project, "Compatibility deck")
    slide = create_slide(project, deck["id"], "slide-01", "Evidence")
    module = create_visual_module(project, slide["id"], "observation-input", "architecture")
    assert slide["slide_spec_path"] is None
    assert module["visual_spec_path"] is None
    assert module["assignment_path"] is None
    assert module["artifact_manifest_path"] is None
    for path in (project / ".research/presentations/state").glob("*.lock"):
        path.unlink()
    before = _snapshot(_presentations(project))

    dry_report = migration.migrate_state(project, dry_run=True)
    non_dry_report = migration.migrate_state(project, dry_run=False)

    expected = {
        "source_schema_version": 1,
        "target_schema_version": 1,
        "migrated_ids": [],
        "blocked_ids": [],
        "blockers": {},
        "changed_paths": [],
    }
    assert dry_report == expected
    assert non_dry_report == expected
    assert _snapshot(_presentations(project)) == before
    assert not list(_presentations(project).rglob("*.lock"))


def test_later_status_cannot_preserve_nullable_evidence_fields(tmp_path: Path) -> None:
    """A later deck status remains blocked when required evidence is absent."""
    project = _project(tmp_path)
    deck_id = "deck-later-round4"
    _write_store(project, "decks.yaml", {
        deck_id: {
            "id": deck_id,
            "title": "Later status",
            "status": "producing",
            "current_plan_id": None,
            "approved_plan_version": None,
            "approved_plan_sha256": None,
            "approval_id": None,
            "approved_by": None,
            "approved_at": None,
            "approval_mode": None,
        },
    })
    _write_store(project, "slides.yaml", {})

    report = migration.migrate_state(project, dry_run=True)

    assert deck_id in report["blocked_ids"]
    assert any("status" in reason or "evidence" in reason for reason in report["blockers"][deck_id])
