"""Schema-v2 migration RED matrix for report-slides evidence state."""

from __future__ import annotations

import json
import os
import stat
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
from presentation_migration_v2 import MigrationPlan, build_migration_plan
from presentation_evidence_cas import cas_relative_path
from presentation_evidence_snapshot import SnapshotError, build_snapshot
from presentation_transactions import WorkflowTransaction


_STORE_NAMES = {
    "decks.yaml": "decks",
    "plans.yaml": "plans",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
    "assignments.yaml": "assignments",
    "artifacts.yaml": "artifacts",
    "revision_requests.yaml": "revision_requests",
}


def _project(tmp_path: Path) -> Path:
    """Create a project root recognized by presentation-state tooling."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _state(project: Path) -> Path:
    """Return the presentation state directory without creating it."""
    return project / ".research" / "presentations" / "state"


def _write_store(
    project: Path,
    name: str,
    records: dict[str, dict[str, Any]],
    version: int = 0,
) -> Path:
    """Write one exact legacy state-store fixture."""
    path = _state(project) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        yaml.safe_dump(
            {"version": version, _STORE_NAMES[name]: records},
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8")
    )
    return path


def _legacy_project(tmp_path: Path, version: int = 0) -> Path:
    """Create a minimal valid schema-zero or schema-one planning project."""
    project = _project(tmp_path)
    _write_store(
        project,
        "decks.yaml",
        {
            "deck-1": {
                "id": "deck-1",
                "title": "Evidence v2",
                "status": "planning",
                "created_by": "planner",
            }
        },
        version,
    )
    _write_store(project, "slides.yaml", {}, version)
    return project


def _regular_tree(root: Path) -> dict[str, tuple[bytes, int, int]]:
    """Capture exact bytes, modes, and mtimes for every regular file."""
    captured: dict[str, tuple[bytes, int, int]] = {}
    if not root.exists():
        return captured
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            captured[path.relative_to(root).as_posix()] = (
                os.readlink(path).encode("utf-8"),
                0,
                0,
            )
        elif path.is_file():
            metadata = path.stat()
            captured[path.relative_to(root).as_posix()] = (
                path.read_bytes(),
                stat.S_IMODE(metadata.st_mode),
                metadata.st_mtime_ns,
            )
    return captured


def _semantic_tree(root: Path) -> dict[str, tuple[bytes, int, int]]:
    """Capture regular content while excluding stable operational lock files."""
    return {
        relative: value
        for relative, value in _regular_tree(root).items()
        if not relative.endswith(".lock")
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping from an asserted regular fixture path."""
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize("source_version", [0, 1])
def test_migration_writes_v2_evidence_store_and_exact_report(
    tmp_path: Path, source_version: int
) -> None:
    """Schema-zero and schema-one stores atomically become schema two."""
    project = _legacy_project(tmp_path, source_version)

    report = migration.migrate_state(project)

    assert set(report) == {
        "source_schema_version",
        "target_schema_version",
        "migrated_ids",
        "blocked_ids",
        "blockers",
        "changed_paths",
    }
    assert report["source_schema_version"] == source_version
    assert report["target_schema_version"] == 2
    assert _read_yaml(_state(project) / "decks.yaml")["version"] == 2
    evidence = _read_yaml(_state(project) / "evidence.yaml")
    assert evidence == {"version": 2, "evidence": {}}
    assert report["migrated_ids"] == ["deck-1"]
    assert report["blocked_ids"] == []
    assert report["blockers"] == {}
    assert report["changed_paths"] == sorted(report["changed_paths"])


def test_dry_run_is_zero_write_even_when_target_outputs_are_absent(tmp_path: Path) -> None:
    """Dry-run analysis cannot create locks, stores, journals, or backups."""
    project = _legacy_project(tmp_path)
    presentations = project / ".research" / "presentations"
    before = _regular_tree(presentations)

    report = migration.migrate_state(project, dry_run=True)

    assert report["target_schema_version"] == 2
    assert report["changed_paths"] == []
    assert _regular_tree(presentations) == before
    assert not (_state(project) / "evidence.yaml").exists()
    assert not (presentations / "transactions").exists()
    assert not list(presentations.glob("state.backup-*"))


def test_v2_noop_preserves_every_existing_byte_mode_and_mtime(tmp_path: Path) -> None:
    """A valid schema-two rerun has no filesystem or lock side effects."""
    project = _legacy_project(tmp_path)
    migration.migrate_state(project)
    workflow_lock = _state(project) / "workflow.lock"
    workflow_lock.write_bytes(b"stable workflow lock")
    orphan_lock = _state(project) / "decks.yaml.lock"
    orphan_lock.write_bytes(b"stable sidecar")
    before = _semantic_tree(project / ".research" / "presentations")

    report = migration.migrate_state(project)

    assert report == {
        "source_schema_version": 2,
        "target_schema_version": 2,
        "migrated_ids": [],
        "blocked_ids": [],
        "blockers": {},
        "changed_paths": [],
    }
    assert _semantic_tree(project / ".research" / "presentations") == before


def test_v2_noop_never_uses_relaxed_legacy_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid target snapshot remains entirely on the fail-closed path."""
    project = _legacy_project(tmp_path)
    migration.migrate_state(project)

    def unexpected_legacy_snapshot(*args: Any, **kwargs: Any) -> Any:
        """Fail if target-schema migration attempts legacy-only capture."""
        raise AssertionError("target-schema migration used legacy snapshot")

    monkeypatch.setattr(
        migration, "build_legacy_migration_snapshot", unexpected_legacy_snapshot
    )

    report = migration.migrate_state(project)

    assert report["source_schema_version"] == 2
    assert report["changed_paths"] == []


@pytest.mark.parametrize("source_version", [0, 1])
def test_missing_legacy_current_plan_blocks_without_relaxing_normal_snapshot(
    tmp_path: Path, source_version: int
) -> None:
    """Legacy missing plans are blocked, while ordinary snapshots still reject them."""
    project = _legacy_project(tmp_path, source_version)
    deck_path = _state(project) / "decks.yaml"
    document = _read_yaml(deck_path)
    document["decks"]["deck-1"].update(
        {
            "status": "approved",
            "current_plan_id": "missing-plan",
            "approved_plan_version": 1,
            "approved_plan_sha256": "0" * 64,
        }
    )
    deck_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    _write_store(project, "plans.yaml", {}, source_version)

    with pytest.raises(SnapshotError, match="current plan .* unavailable"):
        build_snapshot(project)

    report = migration.migrate_state(project)
    stored_deck = _read_yaml(deck_path)["decks"]["deck-1"]

    assert report["target_schema_version"] == 2
    assert report["blocked_ids"] == ["deck-1"]
    assert any(
        "missing plan record" in blocker["reason"]
        for blocker in report["blockers"]["deck-1"]
    )
    assert stored_deck["status"] == "blocked"
    assert "draft_preview_evidence_id" not in stored_deck
    assert _read_yaml(_state(project) / "evidence.yaml") == {
        "version": 2,
        "evidence": {},
    }


@pytest.mark.parametrize("version", [3, -1, True, False, "2"])
def test_mixed_future_and_boolean_versions_fail_before_any_mutation(
    tmp_path: Path, version: object
) -> None:
    """Unknown, mixed, and boolean schema markers cannot be guessed."""
    project = _legacy_project(tmp_path)
    path = _state(project) / "decks.yaml"
    path.write_text(
        yaml.safe_dump({"version": version, "decks": {}}, sort_keys=False),
        encoding="utf-8",
    )
    before = _semantic_tree(project / ".research" / "presentations")

    with pytest.raises(Exception, match="schema|version|Unsupported"):
        migration.migrate_state(project)

    assert _semantic_tree(project / ".research" / "presentations") == before


def test_mixed_store_versions_fail_before_locks_and_backups(tmp_path: Path) -> None:
    """All authoritative stores must declare one identical source version."""
    project = _legacy_project(tmp_path, 0)
    _write_store(project, "slides.yaml", {}, 1)
    before = _regular_tree(project / ".research" / "presentations")

    with pytest.raises(Exception, match="mixed"):
        migration.migrate_state(project)

    assert _regular_tree(project / ".research" / "presentations") == before


def test_canonical_orphan_operational_locks_are_accepted_and_excluded(
    tmp_path: Path,
) -> None:
    """Regular canonical lock sidecars are operational, even when orphaned."""
    project = _legacy_project(tmp_path)
    events = project / ".research" / "presentations" / "events"
    events.mkdir(parents=True)
    for path in (
        _state(project) / "workflow.lock",
        _state(project) / "plans.yaml.lock",
        events / "2026-08-09.jsonl.lock",
    ):
        path.write_bytes(b"stable lock")
    before_locks = {
        path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
        for path in (_state(project)).glob("*.lock")
    }

    report = migration.migrate_state(project)

    assert report["target_schema_version"] == 2
    assert not [path for path in report["changed_paths"] if path.endswith(".lock")]
    for path, expected in before_locks.items():
        assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == expected


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_unsafe_operational_lock_fails_closed_before_writes(
    tmp_path: Path, kind: str
) -> None:
    """Symlink and special-file lock lookalikes are never accepted."""
    project = _legacy_project(tmp_path)
    lock = _state(project) / "decks.yaml.lock"
    if kind == "symlink":
        outside = tmp_path / "outside.lock"
        outside.write_bytes(b"outside")
        lock.symlink_to(outside)
    else:
        os.mkfifo(lock)
    before = _regular_tree(project / ".research" / "presentations")

    with pytest.raises(Exception, match="lock|regular|unsafe|sidecar"):
        migration.migrate_state(project)

    assert _regular_tree(project / ".research" / "presentations") == before


def test_build_plan_is_pure_and_creates_v2_replacements_only(tmp_path: Path) -> None:
    """Migration planning reads immutable snapshots and never mutates a tree."""
    project = _legacy_project(tmp_path)
    before = _regular_tree(project / ".research" / "presentations")

    plan = build_migration_plan(build_snapshot(project))

    assert isinstance(plan, MigrationPlan)
    assert plan.source_schema_version == 0
    assert plan.replacements
    assert plan.cas_objects == {}
    assert _regular_tree(project / ".research" / "presentations") == before


def test_backup_never_overwrites_existing_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A colliding backup name stops migration before any replacement commits."""
    project = _legacy_project(tmp_path)
    monkeypatch.setattr(migration, "_backup_timestamp", lambda: "20260811T000000.000000Z")
    monkeypatch.setattr(migration, "_backup_identifier", lambda: "known")
    existing = project / ".research" / "presentations" / "state.backup-20260811T000000.000000Z-known"
    existing.mkdir()
    (existing / "sentinel").write_bytes(b"do not replace")
    before = _semantic_tree(project / ".research" / "presentations")

    with pytest.raises(Exception, match="backup destination already exists"):
        migration.migrate_state(project)

    assert _semantic_tree(project / ".research" / "presentations") == before


def test_each_commit_position_rolls_back_and_keeps_stable_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any ordinary failure restores exact preimages while locks persist."""
    project = _legacy_project(tmp_path)
    original = _semantic_tree(project / ".research" / "presentations")
    for position in range(1, 4):
        monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(position))
        with pytest.raises((OSError, RuntimeError)):
            migration.migrate_state(project)
        assert _semantic_tree(project / ".research" / "presentations") == original
        assert (_state(project) / "decks.yaml.lock").is_file()
        assert (_state(project) / "slides.yaml.lock").is_file()
        monkeypatch.delenv("PRESENTATION_TRANSACTION_FAIL_AT")


def test_base_exception_crash_recovers_before_a_v2_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Durable journals recover process-death preimages before a rerun."""
    project = _legacy_project(tmp_path)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")
    with pytest.raises(BaseException, match="simulated process death"):
        migration.migrate_state(project)
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")

    report = migration.migrate_state(project)

    assert report["target_schema_version"] == 2
    assert not list((project / ".research" / "presentations" / "transactions").glob("*.json"))


def test_event_shards_remain_byte_identical_and_changed_paths_are_deterministic(
    tmp_path: Path,
) -> None:
    """Immutable audit bytes are neither reparsed nor rewritten during cutover."""
    project = _legacy_project(tmp_path)
    event_path = project / ".research" / "presentations" / "events" / "2026-08-09.jsonl"
    event_path.parent.mkdir(parents=True)
    event_bytes = json.dumps({"event": "review_result", "id": "review-1"}, sort_keys=True).encode("utf-8") + b"\n"
    event_path.write_bytes(event_bytes)

    report = migration.migrate_state(project)

    assert event_path.read_bytes() == event_bytes
    assert report["changed_paths"] == sorted(report["changed_paths"])
    assert all(not path.endswith(".lock") for path in report["changed_paths"])


def test_cas_stage_failure_rolls_back_migration_preimages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CAS staging failure rolls back every migration-owned replacement."""
    project = _legacy_project(tmp_path)
    before = _semantic_tree(project / ".research" / "presentations")
    original = WorkflowTransaction.stage_bytes
    original_plan = migration.build_migration_plan
    cas_content = b"migration-cas-bytes"
    cas_digest = hashlib.sha256(cas_content).hexdigest()

    def plan_with_cas(snapshot: Any) -> MigrationPlan:
        """Add one otherwise valid immutable CAS target to the real plan."""
        plan = original_plan(snapshot)
        return replace(
            plan,
            cas_objects={snapshot.project_root / cas_relative_path(cas_digest): cas_content},
        )

    def fail_cas(self: WorkflowTransaction, path: Path, content: bytes, mode: int | None = None) -> None:
        """Inject one stage failure only for the canonical CAS namespace."""
        if "/evidence/sha256/" in path.as_posix():
            raise OSError("injected CAS stage failure")
        original(self, path, content, mode)

    monkeypatch.setattr(WorkflowTransaction, "stage_bytes", fail_cas)
    monkeypatch.setattr(migration, "build_migration_plan", plan_with_cas)
    with pytest.raises(OSError, match="injected CAS"):
        migration.migrate_state(project)
    assert _semantic_tree(project / ".research" / "presentations") == before
