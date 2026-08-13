"""Black-box acceptance coverage for the schema-v2 evidence workflow.

The tests deliberately use public command and workflow boundaries.  Existing
unit suites own individual validators; this module proves the durable
end-to-end behaviors that a report-slides user depends on.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

from presentation_evidence_gates import assert_current_evidence
from presentation_evidence_store import evidence_store_path
from presentation_evidence_workflow import MigrationRequiredError
from presentation_events import load_events
from presentation_gates import CompletionGateError, DraftGateError
from presentation_state import load_decks, load_visual_modules
from presentation_transactions import SimulatedProcessDeath
from presentation_workflow import register_draft_preview, request_targeted_revision
from test_migrate_presentation_state import _approved_legacy_project, _legacy_project
from test_presentation_evidence_projection import _historical_project
from test_presentation_evidence_workflow import _preview_ready_project
from test_presentation_workflow import _complete_fixture

_MIGRATION_SCRIPT = (
    Path(__file__).resolve().parents[1] / "migrate_presentation_state.py"
)


def _presentations(project_root: Path) -> Path:
    """Return the persistent presentations directory for a fixture project.

    Args:
        project_root: Root of the fixture project.

    Returns:
        Presentation state, event, evidence, and transaction root.
    """
    return project_root / ".research" / "presentations"


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes, int, int]]:
    """Capture exact visible file bytes, modes, and mtimes beneath ``root``.

    Args:
        root: Tree whose durable entries are captured.

    Returns:
        Relative-path keyed regular-file or symlink metadata.
    """
    snapshot: dict[str, tuple[str, bytes, int, int]] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path).encode("utf-8"), 0, 0)
        elif path.is_file():
            metadata = path.stat()
            snapshot[relative] = (
                "file",
                path.read_bytes(),
                stat.S_IMODE(metadata.st_mode),
                metadata.st_mtime_ns,
            )
    return snapshot


def _make_every_present_store_schema_one(project_root: Path) -> None:
    """Rewrite every extant store header to the exact legacy integer one.

    Args:
        project_root: Root of a schema-zero legacy fixture.
    """
    for store_path in sorted((_presentations(project_root) / "state").glob("*.yaml")):
        document = yaml.safe_load(store_path.read_text(encoding="utf-8"))
        assert isinstance(document, dict)
        document["version"] = 1
        store_path.write_text(
            yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
        )


def _run_migration_cli(
    project_root: Path,
    *extra_arguments: str,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the public migration command with structured JSON output.

    Args:
        project_root: Fixture project passed to ``--project-root``.
        *extra_arguments: Additional migration command-line flags.
        environment: Optional environment overrides for fault-injection tests.

    Returns:
        Completed public CLI process without raising for nonzero exit status.
    """
    return subprocess.run(
        [
            sys.executable,
            str(_MIGRATION_SCRIPT),
            "--project-root",
            str(project_root),
            "--json",
            *extra_arguments,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, **environment} if environment is not None else None,
    )


def _evidence_records(project_root: Path) -> dict[str, dict[str, Any]]:
    """Load the persisted schema-v2 evidence records through their public store.

    Args:
        project_root: Root of a completed producer fixture.

    Returns:
        Evidence record mapping keyed by immutable evidence ID.
    """
    document = yaml.safe_load(
        evidence_store_path(project_root).read_text(encoding="utf-8")
    )
    assert isinstance(document, dict)
    records = document["evidence"]
    assert isinstance(records, dict)
    return records


def _semantic_snapshot(root: Path) -> dict[str, tuple[str, bytes, int, int]]:
    """Capture durable payloads while excluding operational locks and journals.

    Args:
        root: Presentation root whose semantic payload is captured.

    Returns:
        Exact persisted non-operational state before or after one transaction.
    """
    return {
        relative: item
        for relative, item in _tree_snapshot(root).items()
        if not relative.endswith(".lock")
        and not relative.startswith("transactions/")
        and ".transaction." not in relative
    }


def _transaction_journals(project_root: Path) -> list[Path]:
    """Return durable transaction journals remaining after a public action.

    Args:
        project_root: Root of a fixture project.

    Returns:
        Sorted list of un-recovered transaction journal paths.
    """
    journal_root = _presentations(project_root) / "transactions"
    return sorted(journal_root.glob("*.json")) if journal_root.exists() else []


def test_schema_one_public_action_raises_typed_migration_error_without_writes(
    tmp_path: Path,
) -> None:
    """A schema-one project cannot start a public workflow writer pre-migration.

    Args:
        tmp_path: Isolated pytest fixture directory.
    """
    project_root, _, _ = _approved_legacy_project(tmp_path, evidence=True)
    _make_every_present_store_schema_one(project_root)
    before = _tree_snapshot(_presentations(project_root))

    with pytest.raises(MigrationRequiredError) as error:
        register_draft_preview(project_root, project_root / "preview.yaml")

    assert error.value.source_schema_version == 1
    assert error.value.target_schema_version == 2
    assert _tree_snapshot(_presentations(project_root)) == before


def test_cli_dry_run_wet_run_and_second_run_have_durable_noop_boundary(
    tmp_path: Path,
) -> None:
    """The migration CLI is write-free dry, durable wet, then byte-exact noop.

    Args:
        tmp_path: Isolated pytest fixture directory.
    """
    project_root, _, _ = _approved_legacy_project(tmp_path, evidence=True)
    _make_every_present_store_schema_one(project_root)
    before_dry_run = _tree_snapshot(_presentations(project_root))

    dry_run = _run_migration_cli(project_root, "--dry-run")

    assert dry_run.returncode == 0, dry_run.stderr
    assert json.loads(dry_run.stdout)["changed_paths"] == []
    assert _tree_snapshot(_presentations(project_root)) == before_dry_run

    wet_run = _run_migration_cli(project_root)

    assert wet_run.returncode == 0, wet_run.stderr
    wet_report = json.loads(wet_run.stdout)
    assert wet_report["source_schema_version"] == 1
    assert wet_report["target_schema_version"] == 2
    assert wet_report["changed_paths"]
    after_wet_run = _tree_snapshot(_presentations(project_root))

    rerun = _run_migration_cli(project_root)

    assert rerun.returncode == 0, rerun.stderr
    assert json.loads(rerun.stdout)["changed_paths"] == []
    assert _tree_snapshot(_presentations(project_root)) == after_wet_run


def test_public_producers_publish_current_evidence_pointers_and_cas_bytes(
    tmp_path: Path,
) -> None:
    """Preview, approval, and completion publish a verifiable evidence chain.

    Args:
        tmp_path: Isolated pytest fixture directory.
    """
    project_root, deck_id, _, _, _, _ = _complete_fixture(tmp_path)

    deck = load_decks(project_root)[deck_id]
    records = _evidence_records(project_root)
    for pointer_field, evidence_kind in (
        ("draft_preview_evidence_id", "draft_preview"),
        ("draft_approval_evidence_id", "draft_approval"),
        ("completion_evidence_id", "deck_completion"),
    ):
        evidence_id = deck[pointer_field]
        assert isinstance(evidence_id, str)
        record = records[evidence_id]
        assert record["evidence_kind"] == evidence_kind
        assert (
            assert_current_evidence(project_root, deck_id, evidence_kind)["id"]
            == evidence_id
        )
        for reference in record["artifact_refs"]:
            cas_path = project_root / reference["cas_path"]
            source_path = project_root / reference["original_path"]
            assert cas_path.read_bytes() == source_path.read_bytes()


def test_targeted_revision_preserves_evidence_history_and_opens_a_retry(
    tmp_path: Path,
) -> None:
    """A module revision retains history, clears current authority, and retries.

    Args:
        tmp_path: Isolated pytest fixture directory.
    """
    project_root, deck_id, _, _, _, module = _complete_fixture(tmp_path)
    history_before = evidence_store_path(project_root).read_bytes()
    revision_path = project_root / "module-revision.yaml"
    revision_path.write_text(
        yaml.safe_dump(
            {
                "deck_id": deck_id,
                "subject_type": "module",
                "subject_id": module["id"],
                "requested_by": "reviewer",
                "instructions": "Retry the visual module.",
                "revision_kind": "module_retry",
            }
        ),
        encoding="utf-8",
    )

    result = request_targeted_revision(project_root, revision_path)

    deck = load_decks(project_root)[deck_id]
    assert all(
        deck[field] is None
        for field in (
            "draft_preview_evidence_id",
            "draft_approval_evidence_id",
            "completion_evidence_id",
        )
    )
    assert evidence_store_path(project_root).read_bytes() == history_before
    replacement = result["replacement"]
    assert replacement["attempt"] == module["attempt"] + 1
    assert replacement["supersedes_module_id"] == module["id"]
    assert replacement["status"] == "planned"
    assert load_visual_modules(project_root)[module["id"]]["status"] == "superseded"


def test_active_cas_tamper_blocks_completion_authorization(
    tmp_path: Path,
) -> None:
    """Changing a pointed-to immutable object cannot authorize completion.

    Args:
        tmp_path: Isolated pytest fixture directory.
    """
    project_root, deck_id, _, _, _, _ = _complete_fixture(tmp_path)
    deck = load_decks(project_root)[deck_id]
    record = _evidence_records(project_root)[deck["completion_evidence_id"]]
    reference = record["artifact_refs"][0]
    cas_path = project_root / reference["cas_path"]
    os.chmod(cas_path, 0o644)
    cas_path.write_bytes(b"offline-tamper")

    with pytest.raises(CompletionGateError, match="evidence_cas_digest_mismatch"):
        assert_current_evidence(project_root, deck_id, "deck_completion")


def test_missing_historical_bytes_remain_auditable_but_cannot_authorize(
    tmp_path: Path,
) -> None:
    """Missing legacy bytes become unavailable history, never a current pointer.

    Args:
        tmp_path: Isolated pytest fixture directory.
    """
    project_root, preview, _ = _historical_project(tmp_path)
    (project_root / "evidence" / "slide-01.png").unlink()
    (project_root / "evidence" / "contact-sheet.png").unlink()

    migration = _run_migration_cli(project_root)

    assert migration.returncode == 0, migration.stderr
    record = next(
        item
        for item in _evidence_records(project_root).values()
        if item["source_event_id"] == preview["id"]
    )
    assert record["availability"] == "historical_unavailable"
    with pytest.raises(DraftGateError, match="draft_preview_evidence_pointer_required"):
        assert_current_evidence(project_root, "deck-temporal", "draft_preview")


def test_migration_preserves_existing_canonical_locks_as_operational_entries(
    tmp_path: Path,
) -> None:
    """Regular canonical state and event sidecars survive a public migration.

    Args:
        tmp_path: Isolated pytest fixture directory.
    """
    project_root, _ = _legacy_project(tmp_path)
    _make_every_present_store_schema_one(project_root)
    state_root = _presentations(project_root) / "state"
    event_root = _presentations(project_root) / "events"
    event_root.mkdir(parents=True)
    locks = (
        state_root / "workflow.lock",
        state_root / "decks.yaml.lock",
        state_root / "plans.yaml.lock",
        event_root / "2024-02-29.jsonl.lock",
    )
    expected: dict[Path, tuple[bytes, int, int]] = {}
    for position, lock_path in enumerate(locks):
        lock_path.write_bytes(f"stable canonical lock {position}".encode("utf-8"))
        os.chmod(lock_path, 0o600 + position)
        timestamp = 1_700_000_000_000_000_000 + position
        os.utime(lock_path, ns=(timestamp, timestamp))
        metadata = lock_path.stat()
        expected[lock_path] = (
            lock_path.read_bytes(),
            stat.S_IMODE(metadata.st_mode),
            metadata.st_mtime_ns,
        )

    migration = _run_migration_cli(project_root)

    assert migration.returncode == 0, migration.stderr
    for lock_path, prior in expected.items():
        metadata = lock_path.stat()
        assert (
            lock_path.read_bytes(),
            stat.S_IMODE(metadata.st_mode),
            metadata.st_mtime_ns,
        ) == prior


@pytest.mark.parametrize("failure_position", range(1, 4))
def test_migration_ordinary_commit_failures_restore_payload_before_a_clean_rerun(
    tmp_path: Path,
    failure_position: int,
) -> None:
    """Each ordinary migration replacement failure rolls back before retry.

    Args:
        tmp_path: Isolated pytest fixture directory.
        failure_position: Ordered replacement configured to fail.
    """
    project_root, _ = _legacy_project(tmp_path)
    _make_every_present_store_schema_one(project_root)
    before = _semantic_snapshot(_presentations(project_root))

    failed = _run_migration_cli(
        project_root,
        environment={"PRESENTATION_TRANSACTION_FAIL_AT": str(failure_position)},
    )

    assert failed.returncode == 1
    assert json.loads(failed.stdout)["error"] == "RuntimeError"
    assert _semantic_snapshot(_presentations(project_root)) == before
    assert _transaction_journals(project_root) == []

    rerun = _run_migration_cli(project_root)

    assert rerun.returncode == 0, rerun.stderr
    assert json.loads(rerun.stdout)["target_schema_version"] == 2


def test_migration_process_death_recovers_durably_before_public_rerun(
    tmp_path: Path,
) -> None:
    """A crash journal is recovered before the same migration is retried.

    Args:
        tmp_path: Isolated pytest fixture directory.
    """
    project_root, _ = _legacy_project(tmp_path)
    _make_every_present_store_schema_one(project_root)

    crashed = _run_migration_cli(
        project_root,
        environment={"PRESENTATION_TRANSACTION_CRASH_AT": "1"},
    )

    assert crashed.returncode != 0
    assert _transaction_journals(project_root)

    rerun = _run_migration_cli(project_root)

    assert rerun.returncode == 0, rerun.stderr
    assert json.loads(rerun.stdout)["target_schema_version"] == 2
    assert _transaction_journals(project_root) == []


@pytest.mark.parametrize("crash_position", range(1, 6))
def test_preview_producer_recovers_after_every_crash_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_position: int,
) -> None:
    """A public preview producer recovers its journal and publishes once.

    Args:
        tmp_path: Isolated pytest fixture directory.
        monkeypatch: Per-test crash-injection environment control.
        crash_position: Ordered preview replacement after which to crash.
    """
    project_root, deck_id, preview_path = _preview_ready_project(tmp_path)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", str(crash_position))

    with pytest.raises(SimulatedProcessDeath, match="simulated process death"):
        register_draft_preview(project_root, preview_path)

    assert _transaction_journals(project_root)
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")
    result = register_draft_preview(project_root, preview_path)

    deck = load_decks(project_root)[deck_id]
    assert deck["draft_preview_evidence_id"] == result["evidence_id"]
    assert [event["id"] for event in load_events(project_root, "draft_preview")] == [
        result["preview"]["id"]
    ]
    assert _transaction_journals(project_root) == []
