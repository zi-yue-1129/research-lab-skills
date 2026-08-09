"""RED tests for Task 8 migration fix round two."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
from presentation_transactions import WorkflowTransaction


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


def _write_store(project: Path, name: str, records: Any, version: int) -> Path:
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
    deck_id = "deck-round2"
    _write_store(
        project,
        "decks.yaml",
        {deck_id: {"id": deck_id, "title": "Round two", "status": "planning"}},
        0,
    )
    _write_store(project, "slides.yaml", {}, 0)
    return project, deck_id


def _target_project(tmp_path: Path) -> Path:
    """Create a target-schema project with no operational files."""
    project = _project(tmp_path)
    _write_store(project, "decks.yaml", {}, 1)
    _write_store(project, "slides.yaml", {}, 1)
    return project


def _snapshot(root: Path) -> dict[str, tuple[str, bytes, int, int]]:
    """Capture all files and symlinks below a presentation root."""
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


def _write_event(project: Path, event: dict[str, Any]) -> Path:
    """Append one JSONL event to the canonical daily shard."""
    path = _presentations(project) / "events" / "2026-08-09.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return path


def test_target_schema_non_dry_noop_has_zero_filesystem_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An all-v1 migration returns before transaction, locks, or journals."""
    project = _target_project(tmp_path)
    before = _snapshot(_presentations(project))

    def fail_transaction(*_args: Any, **_kwargs: Any) -> WorkflowTransaction:
        """Fail if the no-op path attempts to construct a transaction."""
        raise AssertionError("target-schema no-op must not construct WorkflowTransaction")

    monkeypatch.setattr(migration, "WorkflowTransaction", fail_transaction)
    report = migration.migrate_state(project, dry_run=False)

    assert report["changed_paths"] == []
    assert _snapshot(_presentations(project)) == before


def test_legacy_changed_paths_include_new_operational_entries(tmp_path: Path) -> None:
    """A successful legacy migration reports newly created sidecars and journal dir."""
    project, _ = _legacy_project(tmp_path)

    report = migration.migrate_state(project)

    assert ".research/presentations/state/decks.yaml.lock" in report["changed_paths"]
    assert ".research/presentations/state/slides.yaml.lock" in report["changed_paths"]
    assert ".research/presentations/transactions" in report["changed_paths"]
    assert report["changed_paths"] == sorted(report["changed_paths"])


@pytest.mark.parametrize("dry_run", [False, True])
def test_missing_state_path_is_rejected_without_writes(tmp_path: Path, dry_run: bool) -> None:
    """A missing state path fails closed in both dry and non-dry modes."""
    project, deck_id = _legacy_project(tmp_path)
    _write_store(
        project,
        "artifacts.yaml",
        {"artifact-r2": {"id": "artifact-r2", "deck_id": deck_id, "path": "missing.bin"}},
        0,
    )
    before = _snapshot(_presentations(project))

    with pytest.raises(migration.MigrationError, match="missing|regular|path"):
        migration.migrate_state(project, dry_run=dry_run)

    assert _snapshot(_presentations(project)) == before


@pytest.mark.parametrize("dry_run", [False, True])
def test_missing_event_path_is_rejected_without_writes(tmp_path: Path, dry_run: bool) -> None:
    """A missing event path fails closed in both dry and non-dry modes."""
    project, _ = _legacy_project(tmp_path)
    _write_event(project, {"event": "artifact_registered", "id": "event-r2", "path": "missing.bin"})
    before = _snapshot(_presentations(project))

    with pytest.raises(migration.MigrationError, match="missing|regular|path"):
        migration.migrate_state(project, dry_run=dry_run)

    assert _snapshot(_presentations(project)) == before


@pytest.mark.parametrize("dry_run", [False, True])
def test_path_list_mapping_requires_canonical_member(tmp_path: Path, dry_run: bool) -> None:
    """A path-bearing list mapping without ``path`` is rejected explicitly."""
    project, deck_id = _legacy_project(tmp_path)
    _write_store(
        project,
        "artifacts.yaml",
        {
            "artifact-r2": {
                "id": "artifact-r2",
                "deck_id": deck_id,
                "rendered_slide_paths": [{}],
            }
        },
        0,
    )
    before = _snapshot(_presentations(project))

    with pytest.raises(migration.MigrationError, match="path|member|required"):
        migration.migrate_state(project, dry_run=dry_run)

    assert _snapshot(_presentations(project)) == before


@pytest.mark.parametrize(
    "relative_path",
    [
        "state/cache/fake.yaml",
        "state/orphan.lock",
        "state/decks.yaml.tmp",
        "events/transactions/fake.jsonl",
        "events/2026-08-09.jsonl.tmp",
    ],
)
def test_scope_rejects_unknown_nested_or_operational_entries(
    tmp_path: Path, relative_path: str
) -> None:
    """State/event scopes accept only canonical stores, shards, and sidecars."""
    project, _ = _legacy_project(tmp_path)
    path = _presentations(project) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("junk", encoding="utf-8")

    with pytest.raises(migration.MigrationError, match="unknown|scope|state|event"):
        migration.migrate_state(project, dry_run=True)


def test_eventful_target_rerun_accepts_canonical_stable_locks(tmp_path: Path) -> None:
    """A target-schema rerun accepts only the stable canonical sidecars."""
    project, _ = _legacy_project(tmp_path)
    first = migration.migrate_state(project)
    assert first["changed_paths"]

    report = migration.migrate_state(project)

    assert report["changed_paths"] == []


def test_backup_survives_unlock_failure_after_durable_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A release failure after commit keeps migrated state and its backup."""
    project, _ = _legacy_project(tmp_path)
    original_release = WorkflowTransaction._release_locks

    def release_then_fail(transaction: WorkflowTransaction) -> None:
        """Release real locks, then simulate an error after durable commit."""
        original_release(transaction)
        raise OSError("unlock failure after commit")

    monkeypatch.setattr(WorkflowTransaction, "_release_locks", release_then_fail)
    with pytest.raises(OSError, match="unlock failure"):
        migration.migrate_state(project)

    deck = yaml.safe_load((_state_dir(project) / "decks.yaml").read_text(encoding="utf-8"))
    assert deck["version"] == 1
    backups = sorted(_presentations(project).glob("state.backup-*"))
    assert len(backups) == 1
    assert not list((_presentations(project) / "transactions").glob("*.json"))


def test_main_docstring_documents_argument_exit_code() -> None:
    """The public CLI docstring documents structured argument exit code 2."""
    assert migration.main.__doc__ is not None
    assert "exit 2" in migration.main.__doc__.lower()
    assert "argument" in migration.main.__doc__.lower()
