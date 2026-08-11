"""RED tests for Task 8 migration fix round three."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration


STORE_TOP_KEYS = {
    "decks.yaml": "decks",
    "plans.yaml": "plans",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
    "assignments.yaml": "assignments",
    "artifacts.yaml": "artifacts",
    "revision_requests.yaml": "revision_requests",
}


def _project(tmp_path: Path) -> Path:
    """Create a minimal project root for migration fix-round fixtures."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _presentations(project: Path) -> Path:
    """Return the presentation root."""
    return project / ".research" / "presentations"


def _state_dir(project: Path) -> Path:
    """Return the presentation state directory."""
    return _presentations(project) / "state"


def _write_store(project: Path, name: str, records: Any, version: int = 0) -> Path:
    """Write one state store fixture."""
    path = _state_dir(project) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": version, STORE_TOP_KEYS[name]: records}, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _legacy_project(tmp_path: Path) -> tuple[Path, str]:
    """Create a minimal legacy project."""
    project = _project(tmp_path)
    deck_id = "deck-round3"
    _write_store(
        project,
        "decks.yaml",
        {deck_id: {"id": deck_id, "title": "Round three", "status": "planning",
                   "created_by": "test"}},
    )
    _write_store(project, "slides.yaml", {})
    return project, deck_id


def _write_event(project: Path, shard: str, event: dict[str, Any]) -> Path:
    """Append one JSONL event to a named daily shard."""
    path = _presentations(project) / "events" / f"{shard}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return path


def _snapshot(root: Path) -> dict[str, tuple[str, bytes, int, int]]:
    """Capture files, directories, links, modes, and mtimes below a root."""
    result: dict[str, tuple[str, bytes, int, int]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = ("symlink", os.readlink(path).encode(), 0, 0)
        elif path.is_file():
            metadata = path.stat()
            result[relative] = ("file", path.read_bytes(), metadata.st_mode & 0o777, metadata.st_mtime_ns)
        elif path.is_dir():
            metadata = path.stat()
            result[relative] = ("directory", b"", metadata.st_mode & 0o777, metadata.st_mtime_ns)
    return result


@pytest.mark.parametrize("dry_run", [False, True])
def test_orphan_state_canonical_lock_is_stable_operational_entry(
    tmp_path: Path, dry_run: bool
) -> None:
    """A regular canonical state lock is accepted even without its data store."""
    project, _ = _legacy_project(tmp_path)
    orphan = _state_dir(project) / "plans.yaml.lock"
    orphan.write_text("orphan", encoding="utf-8")
    expected = (orphan.read_bytes(), orphan.stat().st_mode & 0o777, orphan.stat().st_mtime_ns)

    report = migration.migrate_state(project, dry_run=dry_run)

    assert (orphan.read_bytes(), orphan.stat().st_mode & 0o777, orphan.stat().st_mtime_ns) == expected
    assert all(not path.endswith(".lock") for path in report["changed_paths"])
    if dry_run:
        assert report["changed_paths"] == []
    else:
        assert report["target_schema_version"] == 2


@pytest.mark.parametrize("dry_run", [False, True])
def test_orphan_event_canonical_lock_is_stable_operational_entry(
    tmp_path: Path, dry_run: bool
) -> None:
    """A regular canonical event lock is accepted without its daily shard."""
    project, _ = _legacy_project(tmp_path)
    events = _presentations(project) / "events"
    events.mkdir(parents=True)
    orphan = events / "2026-08-09.jsonl.lock"
    orphan.write_text("orphan", encoding="utf-8")
    expected = (orphan.read_bytes(), orphan.stat().st_mode & 0o777, orphan.stat().st_mtime_ns)

    report = migration.migrate_state(project, dry_run=dry_run)

    assert (orphan.read_bytes(), orphan.stat().st_mode & 0o777, orphan.stat().st_mtime_ns) == expected
    assert all(not path.endswith(".lock") for path in report["changed_paths"])
    if dry_run:
        assert report["changed_paths"] == []
    else:
        assert report["target_schema_version"] == 2


@pytest.mark.parametrize("name", ["2026-99-99.jsonl", "2026-02-29.jsonl.lock"])
def test_invalid_event_calendar_date_rejected(tmp_path: Path, name: str) -> None:
    """Event shard and canonical lock names must encode real calendar dates."""
    project, _ = _legacy_project(tmp_path)
    events = _presentations(project) / "events"
    events.mkdir(parents=True)
    invalid = events / name
    invalid.write_text("{}\n", encoding="utf-8")

    with pytest.raises(migration.MigrationError, match="date|calendar|event"):
        migration.migrate_state(project, dry_run=True)


def test_valid_leap_day_event_lock_is_stable_across_rerun(tmp_path: Path) -> None:
    """A real leap-day shard and its stable sidecar survive an eventful rerun."""
    project, _ = _legacy_project(tmp_path)
    event_path = _write_event(project, "2024-02-29", {"event": "review_result", "id": "event-round3"})
    lock_path = event_path.with_suffix(event_path.suffix + ".lock")
    lock_path.write_text("stable", encoding="utf-8")
    lock_inode = lock_path.stat().st_ino

    first = migration.migrate_state(project)
    second = migration.migrate_state(project)

    assert first["changed_paths"]
    assert second["changed_paths"] == []
    assert lock_path.is_file()
    assert lock_path.stat().st_ino == lock_inode


@pytest.mark.parametrize("field", ["path", "plan_path", "contact_sheet_path"])
@pytest.mark.parametrize("bad_value", [["assets/file.bin"], {"path": "assets/file.bin"}])
@pytest.mark.parametrize("dry_run", [False, True])
def test_singular_state_path_fields_reject_list_or_mapping_before_writes(
    tmp_path: Path, field: str, bad_value: object, dry_run: bool
) -> None:
    """Singular state path fields accept one string only."""
    project, deck_id = _legacy_project(tmp_path)
    asset = project / "assets" / "file.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"asset")
    _write_store(
        project,
        "artifacts.yaml",
        {"artifact-round3": {"id": "artifact-round3", "deck_id": deck_id, field: bad_value}},
    )
    before = _snapshot(_presentations(project))

    with pytest.raises(migration.MigrationError, match="path|list|mapping|singular"):
        migration.migrate_state(project, dry_run=dry_run)

    assert _snapshot(_presentations(project)) == before


@pytest.mark.parametrize("field", ["path", "plan_path"])
@pytest.mark.parametrize("bad_value", [["assets/file.bin"], {"path": "assets/file.bin"}])
@pytest.mark.parametrize("dry_run", [False, True])
def test_singular_event_path_fields_reject_list_or_mapping_before_writes(
    tmp_path: Path, field: str, bad_value: object, dry_run: bool
) -> None:
    """Singular event payload path fields accept one string only."""
    project, _ = _legacy_project(tmp_path)
    asset = project / "assets" / "file.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"asset")
    _write_event(project, "2026-08-09", {"event": "artifact_registered", "id": "event-round3", field: bad_value})
    before = _snapshot(_presentations(project))

    with pytest.raises(migration.MigrationError, match="path|list|mapping|singular"):
        migration.migrate_state(project, dry_run=dry_run)

    assert _snapshot(_presentations(project)) == before


def test_unknown_plural_path_field_is_rejected_fail_closed(tmp_path: Path) -> None:
    """Unknown plural path-like fields cannot bypass canonical validation."""
    project, deck_id = _legacy_project(tmp_path)
    asset = project / "assets" / "file.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"asset")
    _write_store(
        project,
        "artifacts.yaml",
        {"artifact-round3": {"id": "artifact-round3", "deck_id": deck_id, "unknown_paths": ["assets/file.bin"]}},
    )

    with pytest.raises(migration.MigrationError, match="unknown|path|plural"):
        migration.migrate_state(project, dry_run=True)


def test_explicit_plural_path_fields_accept_documented_shapes(tmp_path: Path) -> None:
    """Canonical plural path fields accept their documented list shapes."""
    project, deck_id = _legacy_project(tmp_path)
    asset = project / "assets" / "file.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"asset")
    _write_store(
        project,
        "artifacts.yaml",
        {
            "artifact-round3": {
                "id": "artifact-round3",
                "deck_id": deck_id,
                "source_paths": ["assets/file.bin"],
                "rendered_slide_paths": [{"path": "assets/file.bin", "slide_id": "slide-1"}],
            }
        },
    )

    report = migration.migrate_state(project, dry_run=True)

    assert report["changed_paths"] == []


@pytest.mark.parametrize("field", ["source_paths", "rendered_slide_paths"])
def test_explicit_plural_path_fields_reject_wrong_entry_shape(tmp_path: Path, field: str) -> None:
    """Canonical plural path fields reject mappings or scalars in the wrong shape."""
    project, deck_id = _legacy_project(tmp_path)
    asset = project / "assets" / "file.bin"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"asset")
    bad_entry: object = {"path": "assets/file.bin"} if field == "source_paths" else "assets/file.bin"
    _write_store(
        project,
        "artifacts.yaml",
        {"artifact-round3": {"id": "artifact-round3", "deck_id": deck_id, field: [bad_entry]}},
    )

    with pytest.raises(migration.MigrationError, match="path|shape|list|mapping"):
        migration.migrate_state(project, dry_run=True)
