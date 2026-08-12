"""Schema-v2 migration RED matrix for report-slides evidence state."""

from __future__ import annotations

import json
import os
import stat
import hashlib
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
import presentation_transactions as transactions
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
    "evidence.yaml": "evidence",
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


def _exact_regular_tree(root: Path) -> dict[str, tuple[bytes, int, int, int]]:
    """Capture exact bytes, modes, mtimes, and inodes for regular files."""
    captured: dict[str, tuple[bytes, int, int, int]] = {}
    for relative, (content, mode, mtime_ns) in _regular_tree(root).items():
        metadata = (root / relative).stat()
        captured[relative] = (content, mode, mtime_ns, metadata.st_ino)
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
    before = _exact_regular_tree(presentations)

    report = migration.migrate_state(project, dry_run=True)

    assert report["target_schema_version"] == 2
    assert report["changed_paths"] == []
    assert _exact_regular_tree(presentations) == before
    assert not (_state(project) / "evidence.yaml").exists()
    assert not (presentations / "transactions").exists()
    assert not list(presentations.glob("state.backup-*"))


def test_v2_noop_preserves_every_existing_byte_mode_mtime_and_lock_inode(tmp_path: Path) -> None:
    """A v2 rerun preserves every canonical operational lock exactly."""
    project = _legacy_project(tmp_path)
    migration.migrate_state(project)
    presentations = project / ".research" / "presentations"
    event = presentations / "events" / "2026-08-09.jsonl"
    event.parent.mkdir(parents=True)
    event.write_bytes(b'{"event":"review_result","id":"v2-lock-order"}\n')
    cas_content = b"already-present-cas"
    cas_digest = hashlib.sha256(cas_content).hexdigest()
    cas_object = project / cas_relative_path(cas_digest)
    cas_object.parent.mkdir(parents=True)
    cas_object.write_bytes(cas_content)
    lock_paths = (
        _state(project) / "workflow.lock",
        _state(project) / "decks.yaml.lock",
        _state(project) / "evidence.yaml.lock",
        event.with_suffix(event.suffix + ".lock"),
        cas_object.with_suffix(cas_object.suffix + ".lock"),
    )
    for index, lock_path in enumerate(lock_paths):
        lock_path.write_bytes(f"stable lock {index}".encode("utf-8"))
        os.chmod(lock_path, 0o600 + index)
        timestamp = 1_700_000_000_000_000_000 + index
        os.utime(lock_path, ns=(timestamp, timestamp))
    before = _exact_regular_tree(presentations)
    before_entries = sorted(
        path.relative_to(presentations).as_posix() for path in presentations.rglob("*")
    )
    before_backups = sorted(presentations.glob("state.backup-*"))

    report = migration.migrate_state(project)

    assert report == {
        "source_schema_version": 2,
        "target_schema_version": 2,
        "migrated_ids": [],
        "blocked_ids": [],
        "blockers": {},
        "changed_paths": [],
    }
    assert _exact_regular_tree(presentations) == before
    assert sorted(
        path.relative_to(presentations).as_posix() for path in presentations.rglob("*")
    ) == before_entries
    assert not list(presentations.rglob("*.transaction.*.tmp"))
    assert not list((presentations / "transactions").glob("*.json"))
    assert sorted(presentations.glob("state.backup-*")) == before_backups


def _completed_v2_project(tmp_path: Path) -> tuple[Path, str]:
    """Complete a deck through the real v2 producers and patch nothing after.

    This drives the genuine pipeline -- ``register_draft_preview`` ->
    ``approve_draft`` -> ``complete_deck`` -- so the resulting state is exactly
    what the Task 6 producers create: four persisted envelopes and all three
    current evidence pointers, with ``slides.slide_spec_path`` left null
    because no writer in the system ever assigns it.

    No visual module is created. ``_complete_fixture`` adds one purely to
    exercise module review, but it never records an assignment or an artifact
    manifest for it, so that module is genuinely invalid state rather than a
    validator problem: real writers do populate
    ``visual_modules.assignment_path`` (``presentation_events.create_assignment_record``)
    and ``artifact_manifest_path`` (``publish_presentation_artifact``), and
    those contract checks are correct. A deck of native slides with no complex
    visuals is an ordinary, fully realistic deck.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        The project root and its completed deck ID.
    """
    from PIL import Image

    from presentation_events import create_artifact_record
    from presentation_state import create_slide, record_review, set_slide_status
    from presentation_workflow import approve_draft, complete_deck, register_draft_preview
    from test_presentation_workflow import (
        _approved_project,
        _materialize_visual_review,
        _plan,
        _write_draft_preview,
    )
    from presentation_contracts import contract_sha256

    project, deck_id, _ = _approved_project(tmp_path)
    slide = create_slide(project, deck_id, "slide-01", "Evidence changes decisions")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide["id"], status)
    record_review(project, "slide", slide["id"], "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", slide["id"], "visual-reviewer", "visual_quality", "passed")
    set_slide_status(project, slide["id"], "passed")
    decks_path = _state(project) / "decks.yaml"
    decks = _read_yaml(decks_path)
    decks["decks"][deck_id]["status"] = "draft_review"
    decks_path.write_text(yaml.safe_dump(decks), encoding="utf-8")
    for path in (project / "renders/slide-1.png", project / "renders/contact.png"):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (20, 20), (1, 2, 3)).save(path)
    registered = register_draft_preview(
        project,
        _write_draft_preview(
            project,
            deck_id,
            project / "renders/slide-1.png",
            project / "renders/contact.png",
        ),
    )
    decision = project / "decision.yaml"
    decision.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "deck_id": deck_id,
                "preview_id": registered["preview"]["id"],
                "preview_sha256": registered["preview"]["preview_sha256"],
                "decision": "approve",
                "approved_by": "reviewer",
            }
        ),
        encoding="utf-8",
    )
    approve_draft(project, decision)
    visual_review = _materialize_visual_review(project, deck_id)
    for relative in ("deck/final.pptx", "renders/source/slide-1.png", "renders/pptx/slide-1.png"):
        artifact_kind = "deck-pptx" if relative.endswith(".pptx") else "slide-png"
        provenance = (
            {}
            if artifact_kind == "deck-pptx"
            else {
                "plan_version": 1,
                "plan_sha256": contract_sha256(_plan(deck_id)),
                "slide_record_id": slide["id"],
                "attempt": int(slide.get("attempt", 1)),
            }
        )
        create_artifact_record(
            project,
            deck_id,
            artifact_kind,
            relative,
            hashlib.sha256((project / relative).read_bytes()).hexdigest(),
            "reviewer",
            slide_id=slide["id"],
            **provenance,
        )
    completion = project / "completion.yaml"
    completion.write_text(
        yaml.safe_dump({"visual_review_path": str(visual_review.relative_to(project))}),
        encoding="utf-8",
    )
    complete_deck(project, deck_id, completion)
    return project, deck_id


def test_v2_noop_on_a_genuinely_completed_deck_reports_no_blocked_ids(
    tmp_path: Path,
) -> None:
    """Rerunning migration on real completed v2 evidence stays an exact no-op.

    Every other v2 no-op fixture carries an empty ``evidence.yaml``, so none of
    them validates persisted ``draft_approval`` and ``visual_review``
    envelopes, which exist only in the store and are never reprojected from
    events. This test covers the plan-level "schema 2 to 2 exact no-op"
    constraint for a project that actually holds them.
    """
    project, deck_id = _completed_v2_project(tmp_path)
    evidence = _read_yaml(_state(project) / "evidence.yaml")["evidence"]
    assert {record["evidence_kind"] for record in evidence.values()} == {
        "draft_preview",
        "draft_approval",
        "visual_review",
        "deck_completion",
    }
    # The producers really do leave this null; the store contract must accept it.
    assert all(
        record["slide_spec_path"] is None
        for record in _read_yaml(_state(project) / "slides.yaml")["slides"].values()
    )
    presentations = project / ".research" / "presentations"
    before = _exact_regular_tree(presentations)

    plan = build_migration_plan(build_snapshot(project))
    report = migration.migrate_state(project)

    assert plan.source_schema_version == 2
    assert plan.blocked_ids == ()
    assert dict(plan.blockers) == {}
    assert report == {
        "source_schema_version": 2,
        "target_schema_version": 2,
        "migrated_ids": [],
        "blocked_ids": [],
        "blockers": {},
        "changed_paths": [],
    }
    assert deck_id not in report["blockers"]
    assert _exact_regular_tree(presentations) == before
    assert not list((presentations / "transactions").glob("*.json"))
    assert not list(presentations.glob("state.backup-*"))


def test_v2_target_store_validation_thaws_frozen_evidence_records(
    tmp_path: Path,
) -> None:
    """Frozen snapshot evidence must be thawed before contract validation.

    Snapshot capture freezes every list into a tuple, but the evidence
    contract requires exact list types. Validating the frozen store directly
    rejects every persisted envelope, so a schema-2 project holding any
    evidence could not be planned at all.
    """
    project, _ = _completed_v2_project(tmp_path)
    snapshot = build_snapshot(project)
    frozen = snapshot.stores["evidence"]
    assert frozen
    assert all(
        isinstance(record["subject_ids"], tuple) for record in frozen.values()
    )

    plan = build_migration_plan(snapshot)

    assert plan.source_schema_version == 2
    assert plan.blocked_ids == ()


def test_migration_acquires_workflow_then_state_event_and_cas_locks_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration takes the global lock order, including a new evidence store."""
    project = _legacy_project(tmp_path)
    for name in (
        "plans.yaml",
        "visual_modules.yaml",
        "assignments.yaml",
        "artifacts.yaml",
        "revision_requests.yaml",
    ):
        _write_store(project, name, {}, 0)
    event = project / ".research" / "presentations" / "events" / "2026-08-09.jsonl"
    event.parent.mkdir(parents=True)
    event.write_bytes(b'{"event":"review_result","id":"lock-order"}\n')
    cas_content = b"lock-order-cas"
    cas_digest = hashlib.sha256(cas_content).hexdigest()
    cas_object = project / cas_relative_path(cas_digest)
    original_plan = migration.build_migration_plan
    original_workflow_lock = migration.migration_workflow_lock
    original_sidecar = transactions._acquire_sidecar
    original_cas_sidecar = transactions.acquire_anchored_sidecar
    acquired: list[str] = []

    def plan_with_cas(snapshot: Any) -> MigrationPlan:
        """Add one valid CAS object to each immutable migration plan."""
        return replace(
            original_plan(snapshot),
            cas_objects={cas_object: cas_content},
        )

    @contextmanager
    def record_workflow_lock(root: Path) -> Any:
        """Record the already-acquired outer workflow lock."""
        with original_workflow_lock(root):
            acquired.append(".research/presentations/state/workflow.lock")
            yield

    def record_sidecar(path: Path) -> int:
        """Record one ordinary state or event sidecar acquisition."""
        acquired.append(path.relative_to(project).as_posix() + ".lock")
        return original_sidecar(path)

    def record_cas_sidecar(anchored: Any, timeout_seconds: int) -> int:
        """Record one anchored CAS sidecar acquisition."""
        acquired.append(anchored.display_path.relative_to(project).as_posix() + ".lock")
        return original_cas_sidecar(anchored, timeout_seconds)

    monkeypatch.setattr(migration, "build_migration_plan", plan_with_cas)
    monkeypatch.setattr(migration, "migration_workflow_lock", record_workflow_lock)
    monkeypatch.setattr(transactions, "_acquire_sidecar", record_sidecar)
    monkeypatch.setattr(transactions, "acquire_anchored_sidecar", record_cas_sidecar)

    report = migration.migrate_state(project)

    assert report["target_schema_version"] == 2
    assert acquired == [
        ".research/presentations/state/workflow.lock",
        ".research/presentations/state/decks.yaml.lock",
        ".research/presentations/state/plans.yaml.lock",
        ".research/presentations/state/slides.yaml.lock",
        ".research/presentations/state/visual_modules.yaml.lock",
        ".research/presentations/state/assignments.yaml.lock",
        ".research/presentations/state/artifacts.yaml.lock",
        ".research/presentations/state/revision_requests.yaml.lock",
        ".research/presentations/state/evidence.yaml.lock",
        ".research/presentations/events/2026-08-09.jsonl.lock",
        cas_object.relative_to(project).as_posix() + ".lock",
    ]


def test_transaction_locks_new_evidence_store_as_a_state_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new evidence-only target uses an ordinary stable state sidecar."""
    project = _project(tmp_path)
    evidence = _state(project) / "evidence.yaml"
    acquired: list[Path] = []
    original_sidecar = transactions.acquire_anchored_sidecar

    def record_sidecar(anchored: Any, timeout_seconds: int) -> int:
        """Record the evidence target before acquiring its real lock."""
        acquired.append(anchored.display_path)
        return original_sidecar(anchored, timeout_seconds)

    monkeypatch.setattr(transactions, "acquire_anchored_sidecar", record_sidecar)

    with WorkflowTransaction([evidence], project):
        pass

    assert acquired == [evidence]
    assert evidence.with_suffix(evidence.suffix + ".lock").is_file()


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
def test_missing_legacy_current_plan_is_rejected_without_mutation(
    tmp_path: Path, source_version: int
) -> None:
    """Legacy migration cannot preserve a dangling current-plan relation in v2."""
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

    before = _regular_tree(project / ".research/presentations")
    with pytest.raises(Exception, match="current_plan_id|relation|resolve"):
        migration.migrate_state(project)

    assert _regular_tree(project / ".research/presentations") == before
    assert not (_state(project) / "evidence.yaml").exists()


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
