"""RED tests for deterministic legacy presentation-state migration."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_events import load_events
from presentation_state import load_decks, load_slides, load_visual_modules


SCRIPT = Path(__file__).resolve().parents[1] / "migrate_presentation_state.py"
STORE_TOP_KEYS = {
    "decks.yaml": "decks",
    "plans.yaml": "plans",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
    "assignments.yaml": "assignments",
    "artifacts.yaml": "artifacts",
    "revision_requests.yaml": "revision_requests",
}


def _make_project(tmp_path: Path) -> Path:
    """Create a project root recognized by the presentation state tools."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _state_dir(project: Path) -> Path:
    """Return the presentation state directory without creating it."""
    return project / ".research" / "presentations" / "state"


def _write_store(project: Path, name: str, records: Any, *, version: Any = 0) -> Path:
    """Write one legacy state store fixture."""
    path = _state_dir(project) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {"version": version, STORE_TOP_KEYS[name]: records}
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _write_events(project: Path, events: list[dict[str, Any]], *, shard: str = "2026-08-08") -> Path:
    """Write one legacy JSONL event shard fixture."""
    path = project / ".research" / "presentations" / "events" / f"{shard}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return path


def _legacy_project(tmp_path: Path, *, deck_status: str = "planning") -> tuple[Path, str]:
    """Create a minimal version-zero project and return its deck ID."""
    project = _make_project(tmp_path)
    deck_id = "deck_legacy"
    _write_store(
        project,
        "decks.yaml",
        {
            deck_id: {
                "id": deck_id,
                "title": "Legacy deck",
                "status": deck_status,
                "plan_version": 0,
                "created_by": "planner",
            }
        },
    )
    _write_store(project, "slides.yaml", {})
    return project, deck_id


def _approved_legacy_project(tmp_path: Path, *, evidence: bool) -> tuple[Path, str, dict[str, Any]]:
    """Create an approved legacy deck with optionally verifiable evidence."""
    project, deck_id = _legacy_project(tmp_path, deck_status="approved")
    plan_path = project / "plans" / "legacy-plan.yaml"
    plan = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": 1,
        "purpose": "A verifiable plan",
        "audience": "Research audience",
        "core_narrative": "Evidence changes decisions.",
        "authored_by": "planner",
        "status": "reviewed",
        "estimated_duration_minutes": 10,
        "excluded_content": [],
        "known_gaps": [],
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Evidence",
                "purpose": "Orient the audience",
                "key_takeaway": "Evidence changes decisions.",
                "intended_visual_type": "none",
                "visual_rationale": "No visual needed",
                "speaker_message": "Evidence changes decisions.",
                "evidence_refs": ["E-1"],
                "dependencies": [],
                "open_questions": [],
            }
        ],
    }
    if evidence:
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(yaml.safe_dump(plan, sort_keys=True), encoding="utf-8")
        plan_digest = contract_sha256(plan)
        _write_store(
            project,
            "plans.yaml",
            {
                "plan_legacy": {
                    "id": "plan_legacy",
                    "deck_id": deck_id,
                    "version": 1,
                    "plan_path": "plans/legacy-plan.yaml",
                    "plan_sha256": plan_digest,
                    "authored_by": "planner",
                }
            },
        )
        _write_events(
            project,
            [
                {
                    "schema_version": 1,
                    "event": "review_result",
                    "id": "review_content",
                    "subject_type": "deck",
                    "subject_id": deck_id,
                    "current_plan_id": "plan_legacy",
                    "current_plan_version": 1,
                    "current_plan_sha256": plan_digest,
                    "reviewer_id": "reviewer",
                    "reviewer_role": "content",
                    "status": "passed",
                    "findings": [],
                    "identity_verifiable": True,
                    "round": 1,
                    "ts": "2026-08-08T00:00:00Z",
                },
                {
                    "schema_version": 1,
                    "event": "deck_approval",
                    "id": "approval_legacy",
                    "deck_id": deck_id,
                    "plan_version": 1,
                    "plan_sha256": plan_digest,
                    "approved_by": "reviewer",
                    "approved_at": "2026-08-08T00:01:00Z",
                    "approval_mode": "interactive",
                    "decision": "approve",
                    "identity_verifiable": True,
                    "ts": "2026-08-08T00:01:00Z",
                },
            ],
        )
        decks = yaml.safe_load((_state_dir(project) / "decks.yaml").read_text(encoding="utf-8"))
        decks["decks"][deck_id].update(
            {
                "plan_version": 1,
                "current_plan_id": "plan_legacy",
                "approved_plan_version": 1,
                "approved_plan_sha256": plan_digest,
                "approval_id": "approval_legacy",
                "approved_by": "reviewer",
                "approved_at": "2026-08-08T00:01:00Z",
                "approval_mode": "interactive",
            }
        )
        (_state_dir(project) / "decks.yaml").write_text(
            yaml.safe_dump(decks, sort_keys=False), encoding="utf-8"
        )
    return project, deck_id, plan


def _migrate(project: Path, dry_run: bool = False) -> dict[str, Any]:
    """Import the migration API lazily so this file is RED before implementation."""
    from migrate_presentation_state import migrate_state

    return migrate_state(project, dry_run=dry_run)


def _snapshot_tree(root: Path) -> dict[str, tuple[str, bytes, int, int]]:
    """Capture relative bytes, modes, and mtimes for every regular file."""
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[str, bytes, int, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            if path.name.endswith(".lock"):
                continue
            relative = path.relative_to(root).as_posix()
            mode = stat.S_IMODE(path.stat().st_mode)
            snapshot[relative] = ("file", path.read_bytes(), mode, path.stat().st_mtime_ns)
        elif path.is_symlink():
            snapshot[path.relative_to(root).as_posix()] = ("symlink", os.readlink(path).encode(), 0, 0)
    return snapshot


def test_migration_blocks_unverifiable_approved_deck(tmp_path: Path) -> None:
    """Approved legacy decks without persisted evidence become blocked."""
    project, deck_id = _legacy_project(tmp_path, deck_status="approved")

    report = _migrate(project)

    assert deck_id in report["blocked_ids"]
    assert load_decks(project)[deck_id]["status"] == "blocked"
    assert "approval evidence" in " ".join(report["blockers"][deck_id]).lower()


def test_verifiable_approved_deck_preserves_ids_digest_and_history(tmp_path: Path) -> None:
    """Verifiable approval evidence survives migration without replacement IDs."""
    project, deck_id, plan = _approved_legacy_project(tmp_path, evidence=True)
    before_events = load_events(project)
    plan_digest = contract_sha256(plan)

    report = _migrate(project)

    deck = load_decks(project)[deck_id]
    assert report["blocked_ids"] == []
    assert deck["status"] == "approved"
    assert deck["id"] == deck_id
    assert deck["current_plan_id"] == "plan_legacy"
    assert deck["approved_plan_sha256"] == plan_digest
    assert load_events(project) == before_events
    assert plan["deck_id"] == deck_id


def test_planning_state_maps_directly_and_preserves_child_ids(tmp_path: Path) -> None:
    """Planning, slide, and module IDs map directly into target stores."""
    project, deck_id = _legacy_project(tmp_path)
    slide_id = "slide_legacy"
    module_id = "module_legacy"
    _write_store(
        project,
        "slides.yaml",
        {slide_id: {"id": slide_id, "deck_id": deck_id, "plan_slide_id": "slide-01", "title": "T", "status": "planned"}},
    )
    _write_store(
        project,
        "visual_modules.yaml",
        {module_id: {"id": module_id, "slide_id": slide_id, "module_key": "input", "module_type": "architecture", "status": "planned", "dependencies": []}},
    )

    report = _migrate(project)

    assert report["migrated_ids"] == [deck_id, module_id, slide_id]
    assert load_decks(project)[deck_id]["status"] == "planning"
    assert load_slides(project)[slide_id]["id"] == slide_id
    assert load_visual_modules(project)[module_id]["id"] == module_id


def test_dry_run_changes_no_files_or_directories(tmp_path: Path) -> None:
    """Dry-run migration leaves bytes, modes, mtimes, and tree shape untouched."""
    project, _ = _legacy_project(tmp_path)
    presentations = project / ".research" / "presentations"
    before = _snapshot_tree(presentations)

    report = _migrate(project, dry_run=True)

    assert report["changed_paths"] == []
    assert _snapshot_tree(presentations) == before
    assert not (presentations / "state.backup").exists()
    assert not (presentations / "transactions").exists()


def test_target_schema_rerun_is_idempotent_without_backup_or_write(tmp_path: Path) -> None:
    """A second target-schema migration is a deterministic no-op."""
    project, _ = _legacy_project(tmp_path)
    first = _migrate(project)
    after_first = _snapshot_tree(project / ".research" / "presentations")
    backups = sorted((project / ".research" / "presentations").glob("state.backup-*"))

    second = _migrate(project)

    assert first["changed_paths"]
    assert second == {
        "source_schema_version": 1,
        "target_schema_version": 1,
        "migrated_ids": [],
        "blocked_ids": [],
        "blockers": {},
        "changed_paths": [],
    }
    assert _snapshot_tree(project / ".research" / "presentations") == after_first
    assert sorted((project / ".research" / "presentations").glob("state.backup-*")) == backups


def test_report_ordering_is_deterministic(tmp_path: Path) -> None:
    """IDs, blockers, and changed paths use stable lexical ordering."""
    project = _make_project(tmp_path)
    _write_store(
        project,
        "decks.yaml",
        {
            "deck-z": {"id": "deck-z", "title": "Z", "status": "approved"},
            "deck-a": {"id": "deck-a", "title": "A", "status": "planning"},
        },
    )
    _write_store(project, "slides.yaml", {})

    report = _migrate(project)

    assert report["migrated_ids"] == sorted(report["migrated_ids"])
    assert report["blocked_ids"] == sorted(report["blocked_ids"])
    assert list(report["blockers"]) == sorted(report["blockers"])
    assert report["changed_paths"] == sorted(report["changed_paths"])


def test_cli_json_success_and_structured_schema_error(tmp_path: Path) -> None:
    """CLI emits JSON for both a migration report and a rejected schema."""
    project, _ = _legacy_project(tmp_path)
    success = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(project), "--dry-run", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert success.returncode == 0
    assert set(json.loads(success.stdout)) == {
        "source_schema_version", "target_schema_version", "migrated_ids",
        "blocked_ids", "blockers", "changed_paths",
    }

    _write_store(project, "decks.yaml", {}, version=2)
    failure = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(project), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert failure.returncode != 0
    error = json.loads(failure.stdout)
    assert error["error"] in {"MigrationError", "StateParseError"}
    assert "message" in error


def test_backup_contains_exact_preimages_and_modes(tmp_path: Path) -> None:
    """Non-dry-run backup preserves every migrated file's bytes and mode."""
    project, _ = _legacy_project(tmp_path)
    events = _write_events(project, [{"event": "review_result", "id": "r1"}])
    decks = _state_dir(project) / "decks.yaml"
    os.chmod(decks, 0o640)
    os.chmod(events, 0o600)
    before = {
        decks.relative_to(project).as_posix(): (decks.read_bytes(), stat.S_IMODE(decks.stat().st_mode)),
        events.relative_to(project).as_posix(): (events.read_bytes(), stat.S_IMODE(events.stat().st_mode)),
    }

    report = _migrate(project)

    backups = sorted((project / ".research" / "presentations").glob("state.backup-*"))
    assert len(backups) == 1
    backup = backups[0]
    for relative, (content, mode) in before.items():
        backup_path = backup / relative.removeprefix(".research/presentations/")
        assert backup_path.read_bytes() == content
        assert stat.S_IMODE(backup_path.stat().st_mode) == mode
    assert backup.relative_to(project).as_posix() in report["changed_paths"]


def test_transaction_failure_at_each_commit_position_restores_preimage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every injected replacement failure leaves all stores byte-identical."""
    project, _ = _legacy_project(tmp_path)
    events = _write_events(project, [{"event": "review_result", "id": "r1"}])
    tracked = [_state_dir(project) / "decks.yaml", _state_dir(project) / "slides.yaml", events]
    before = _snapshot_tree(project / ".research" / "presentations")
    stable_sidecars: dict[Path, int] = {}

    for position in range(1, len(tracked) + 1):
        monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(position))
        with pytest.raises((RuntimeError, OSError)):
            _migrate(project)
        assert _snapshot_tree(project / ".research" / "presentations") == before
        for path in tracked:
            sidecar = path.with_suffix(path.suffix + ".lock")
            assert sidecar.is_file()
            inode = sidecar.stat().st_ino
            if sidecar not in stable_sidecars:
                stable_sidecars[sidecar] = inode
            assert stable_sidecars[sidecar] == inode
        monkeypatch.delenv("PRESENTATION_TRANSACTION_FAIL_AT")


def test_crash_journal_recovers_to_complete_target_on_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A simulated process death is recovered before the next migration."""
    project, _ = _legacy_project(tmp_path)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")
    with pytest.raises(BaseException, match="simulated process death"):
        _migrate(project)
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")

    report = _migrate(project)

    assert report["target_schema_version"] == 1
    assert load_decks(project)
    assert not list((project / ".research" / "presentations" / "transactions").glob("*.json"))


@pytest.mark.parametrize("version", [2, -1, True, False, "1"])
def test_unknown_future_and_bool_schema_versions_are_rejected(
    tmp_path: Path, version: Any
) -> None:
    """Unsupported and boolean-as-int schema versions fail closed."""
    project = _make_project(tmp_path)
    _write_store(project, "decks.yaml", {}, version=version)

    with pytest.raises(Exception, match="schema|version"):
        _migrate(project)


def test_malformed_yaml_jsonl_and_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    """Malformed stores and duplicate immutable IDs produce explicit errors."""
    project = _make_project(tmp_path)
    path = _state_dir(project) / "decks.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("version: 0\ndecks: [broken", encoding="utf-8")
    with pytest.raises(Exception, match="YAML|mapping|parse"):
        _migrate(project)

    path.write_text(
        yaml.safe_dump(
            {
                "version": 0,
                "decks": [
                    {"id": "deck-1", "title": "one", "status": "planning"},
                    {"id": "deck-1", "title": "two", "status": "planning"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="duplicate|id"):
        _migrate(project)

    path.write_text(yaml.safe_dump({"version": 0, "decks": {}}), encoding="utf-8")
    _write_events(project, [{"event": "review_result", "id": "r1"}])
    (project / ".research" / "presentations" / "events" / "2026-08-09.jsonl").write_text(
        '{"event":"review_result","id":"r1"}\n', encoding="utf-8"
    )
    with pytest.raises(Exception, match="duplicate|id"):
        _migrate(project)


def test_mixed_schema_keys_are_rejected(tmp_path: Path) -> None:
    """A store mixing version keys cannot be guessed safely."""
    project = _make_project(tmp_path)
    path = _state_dir(project) / "decks.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("version: 0\nschema_version: 0\ndecks: {}\n", encoding="utf-8")

    with pytest.raises(Exception, match="mixed|schema"):
        _migrate(project)


def test_path_traversal_and_symlink_escape_are_rejected(tmp_path: Path) -> None:
    """Legacy canonical paths cannot escape through lexical traversal or symlinks."""
    project, deck_id = _legacy_project(tmp_path)
    plans = _state_dir(project) / "plans.yaml"
    plans.write_text(
        yaml.safe_dump(
            {
                "version": 0,
                "plans": {
                    "plan-1": {
                        "id": "plan-1",
                        "deck_id": deck_id,
                        "version": 1,
                        "plan_path": "../outside.yaml",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="path|escape|project"):
        _migrate(project)

    outside = tmp_path / "outside.yaml"
    outside.write_text("outside", encoding="utf-8")
    safe_name = project / "safe.yaml"
    safe_name.symlink_to(outside)
    plans.write_text(
        yaml.safe_dump(
            {
                "version": 0,
                "plans": {
                    "plan-1": {
                        "id": "plan-1",
                        "deck_id": deck_id,
                        "version": 1,
                        "plan_path": "safe.yaml",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="symlink|escape|path"):
        _migrate(project)


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize(
    ("nested_path", "expected"),
    [("../outside.yaml", "traversal"), ("safe/nested.yaml", "symlink")],
)
def test_nested_path_mapping_rejects_escape_before_mutation(
    tmp_path: Path, dry_run: bool, nested_path: str, expected: str
) -> None:
    """Nested path-bearing mappings fail closed before backup or locks."""
    project, deck_id = _legacy_project(tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text("outside", encoding="utf-8")
    if expected == "symlink":
        (project / "safe").symlink_to(outside)
    _write_store(
        project,
        "artifacts.yaml",
        {
            "artifact-legacy": {
                "id": "artifact-legacy",
                "deck_id": deck_id,
                "rendered_slide_paths": [{"path": nested_path}],
            }
        },
    )
    presentations = project / ".research" / "presentations"
    before = _snapshot_tree(presentations)
    with pytest.raises(Exception, match=expected):
        _migrate(project, dry_run=dry_run)
    assert _snapshot_tree(presentations) == before
    assert outside.read_text(encoding="utf-8") == "outside"
    assert not list(presentations.glob("state.backup-*"))
    assert not (presentations / "transactions").exists()


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize(
    ("event_path", "expected"),
    [("../outside.yaml", "traversal"), ("safe.yaml", "symlink")],
)
def test_event_payload_path_rejects_escape_before_mutation(
    tmp_path: Path, dry_run: bool, event_path: str, expected: str
) -> None:
    """Event payload paths fail closed before migration side effects."""
    project, _ = _legacy_project(tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text("outside", encoding="utf-8")
    if expected == "symlink":
        (project / "safe.yaml").symlink_to(outside)
    _write_events(project, [{"event": "artifact_registered", "id": "event-legacy", "path": event_path}])
    presentations = project / ".research" / "presentations"
    before = _snapshot_tree(presentations)
    with pytest.raises(Exception, match=expected):
        _migrate(project, dry_run=dry_run)
    assert _snapshot_tree(presentations) == before
    assert outside.read_text(encoding="utf-8") == "outside"
    assert not list(presentations.glob("state.backup-*"))
    assert not (presentations / "transactions").exists()
