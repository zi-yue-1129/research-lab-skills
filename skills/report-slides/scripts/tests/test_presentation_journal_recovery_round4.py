"""Public migration recovery and exact journal-publication contracts."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import stat
from typing import Any

import pytest

import migrate_presentation_state as migration
from presentation_transactions import SimulatedProcessDeath, WorkflowTransaction
from test_migrate_presentation_state_v2 import _exact_regular_tree, _legacy_project


_INITIAL_BOUNDARIES = [
    "after_create",
    "after_write",
    "after_first_fsync",
    "after_chmod",
    "after_second_fsync",
    "before_rename",
    "after_rename",
]
_REWRITE_BOUNDARIES = [f"rewrite_{boundary}" for boundary in _INITIAL_BOUNDARIES]


def _v2_project(tmp_path: Path) -> tuple[Path, Path]:
    """Create a schema-v2 project and one ordinary target with stable metadata."""
    project = _legacy_project(tmp_path, version=1)
    migration.migrate_state(project)
    target = project / ".research/presentations/state/slides.yaml"
    os.chmod(target, 0o640)
    os.utime(target, ns=(1_700_000_000_000_000_123,) * 2)
    return project, target


@pytest.mark.parametrize("boundary", _INITIAL_BOUNDARIES)
def test_public_migrate_recovers_each_initial_journal_publication_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """The public entrypoint reconciles initial canonical temps before preflight."""
    project, target = _v2_project(tmp_path)
    before = _exact_regular_tree(project / ".research/presentations")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_JOURNAL_CRASH_AT", boundary)

    with pytest.raises(SimulatedProcessDeath, match="journal publication"):
        with WorkflowTransaction([target], project) as workflow:
            workflow.stage_bytes(target, b"staged")

    monkeypatch.delenv("PRESENTATION_TRANSACTION_JOURNAL_CRASH_AT")
    report = migration.migrate_state(project)

    assert report["source_schema_version"] == 2
    assert _exact_regular_tree(project / ".research/presentations") == before
    assert not list((project / ".research/presentations/transactions").iterdir())


@pytest.mark.parametrize("boundary", _REWRITE_BOUNDARIES)
def test_public_migrate_recovers_each_post_stage_journal_rewrite_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """A staged target temp never strands public migration recovery."""
    project, target = _v2_project(tmp_path)
    before = _exact_regular_tree(project / ".research/presentations")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_JOURNAL_CRASH_AT", boundary)

    with pytest.raises(SimulatedProcessDeath, match="journal publication"):
        with WorkflowTransaction([target], project) as workflow:
            workflow.stage_bytes(target, b"staged")

    monkeypatch.delenv("PRESENTATION_TRANSACTION_JOURNAL_CRASH_AT")
    report = migration.migrate_state(project)

    assert report["source_schema_version"] == 2
    assert _exact_regular_tree(project / ".research/presentations") == before
    assert not list(target.parent.glob("*.transaction.*.tmp"))
    assert not list((project / ".research/presentations/transactions").iterdir())


def _journal_document(project: Path, target: Path, transaction_id: str) -> dict[str, Any]:
    """Return one exact current journal document for a stable target."""
    metadata = target.stat()
    return {
        "transaction_id": transaction_id,
        "paths": [
            {
                "path": target.relative_to(project).as_posix(),
                "exists": True,
                "mode": metadata.st_mode & 0o777,
                "mtime_ns": metadata.st_mtime_ns,
                "content": base64.b64encode(target.read_bytes()).decode("ascii"),
            }
        ],
        "staged_paths": [],
    }


@pytest.mark.parametrize(
    "mutation",
    ["extra_preimage_key", "bool_preimage_mode", "extra_top_key"],
)
def test_public_migrate_rejects_nonexact_journal_mappings(
    tmp_path: Path, mutation: str
) -> None:
    """Journal and preimage mappings require exact keys and scalar types."""
    project, target = _v2_project(tmp_path)
    transaction_id = "a" * 32
    document = _journal_document(project, target, transaction_id)
    if mutation == "extra_preimage_key":
        document["paths"][0]["authorization"] = True
    elif mutation == "bool_preimage_mode":
        document["paths"][0]["mode"] = True
    else:
        document["authorization"] = True
    journal_dir = project / ".research/presentations/transactions"
    journal = journal_dir / f"{transaction_id}.json"
    journal.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    journal.chmod(0o600)

    with pytest.raises(Exception, match="journal|preimage|entry|field|mode"):
        migration.migrate_state(project)


@pytest.mark.parametrize("kind", ["symlink", "fifo", "socket", "wrong_mode"])
def test_public_migrate_rejects_unsafe_canonical_journal_temp(
    tmp_path: Path, kind: str
) -> None:
    """Public recovery rejects unsafe temp types and noncanonical modes."""
    project, target = _v2_project(tmp_path)
    transaction_id = "b" * 32
    journal_dir = project / ".research/presentations/transactions"
    temporary = journal_dir / f"{transaction_id}.json.tmp"
    if kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside")
        temporary.symlink_to(outside)
    elif kind == "fifo":
        os.mkfifo(temporary)
    elif kind == "socket":
        os.mknod(temporary, stat.S_IFSOCK | 0o600)
    else:
        temporary.write_text(
            json.dumps(_journal_document(project, target, transaction_id), sort_keys=True),
            encoding="utf-8",
        )
        temporary.chmod(0o640)

    with pytest.raises(Exception, match="journal|regular|temporary|mode|filename"):
        migration.migrate_state(project)


def test_published_canonical_journal_mode_is_exactly_0600(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A visible complete journal never inherits the caller's umask or mode."""
    project, target = _v2_project(tmp_path)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_JOURNAL_CRASH_AT", "after_rename")

    with pytest.raises(SimulatedProcessDeath):
        with WorkflowTransaction([target], project) as workflow:
            workflow.stage_bytes(target, b"staged")

    journal = next((project / ".research/presentations/transactions").glob("*.json"))
    assert journal.stat().st_mode & 0o777 == 0o600
