"""Regression tests for the fourth Task 7 enforcement fix round."""

from __future__ import annotations

import fcntl
import os
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from presentation_events import events_shard_path, load_events
from presentation_gates import DraftGateError, PublicationGateError
from presentation_plan_transactions import register_plan_transaction
from presentation_state import create_deck, load_decks
from presentation_transactions import TransactionError
from presentation_workflow import approve_draft, register_draft_preview
from publish_presentation_artifact import publish_artifact


def _project(tmp_path: Path) -> Path:
    """Create a temporary Git project recognized by presentation state."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _plan(deck_id: str, version: int = 1) -> dict[str, Any]:
    """Return a minimal plan document accepted by the transaction helper."""
    return {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_version": version,
        "purpose": "Explain the result",
        "audience": "Researchers",
        "estimated_duration_minutes": 5,
        "core_narrative": "Evidence changes decisions.",
        "status": "reviewed",
        "authored_by": "planner-a",
        "excluded_content": [],
        "known_gaps": [],
        "slides": [],
    }


def _canonical_destination(project: Path, deck_id: str, version: int) -> Path:
    """Return one canonical immutable plan destination."""
    return project / "decks" / deck_id / "plans" / f"plan-v{version:04d}.yaml"


def _transaction_plan_args(
    project: Path, deck_id: str, version: int = 1
) -> tuple[dict[str, Any], Path, int]:
    """Return a plan document and exact helper arguments."""
    return _plan(deck_id, version), _canonical_destination(project, deck_id, version), version


def test_failed_new_plan_keeps_one_sidecar_inode_for_a_blocked_waiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A waiter acquires the same stable sidecar inode after rollback."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck")
    document, destination, version = _transaction_plan_args(project, deck["id"])
    sidecar = destination.with_suffix(destination.suffix + ".lock")
    holder_ready = threading.Event()
    waiter_opened = threading.Event()
    waiter_acquired = threading.Event()
    release_waiter = threading.Event()
    waiter_inode: list[int] = []

    def notify_locked(self: Any) -> None:
        """Start a waiter while the transaction still owns every lock."""
        if holder_ready.is_set():
            return
        holder_ready.set()

        def waiter() -> None:
            descriptor = os.open(str(sidecar), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
            try:
                waiter_inode.append(os.fstat(descriptor).st_ino)
                waiter_opened.set()
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                waiter_acquired.set()
                release_waiter.wait(5)
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

        threading.Thread(target=waiter, daemon=True).start()
        assert waiter_opened.wait(5), "waiter did not open the sidecar"

    import presentation_transactions

    monkeypatch.setattr(presentation_transactions.WorkflowTransaction, "_notify_locked", notify_locked)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", "1")
    with pytest.raises((RuntimeError, TransactionError), match="injected transaction commit failure"):
        register_plan_transaction(
            project, deck["id"], document, "planner-a", destination.relative_to(project), version
        )
    assert waiter_acquired.wait(5), "waiter did not acquire after rollback"
    assert sidecar.is_file()
    assert waiter_inode == [sidecar.stat().st_ino]
    assert not destination.exists()
    assert load_decks(project)[deck["id"]]["current_plan_id"] is None
    release_waiter.set()


@pytest.mark.parametrize(
    ("destination", "next_version"),
    [
        ("decks/other/plans/plan-v0001.yaml", 1),
        ("decks/deck/plans/plan-v0002.yaml", 1),
        ("decks/deck/plans/plan-v1.yaml", 1),
        ("decks/deck/plans/plan-v0001.yaml", True),
        ("decks/deck/plans/plan-v0001.yaml", 0),
    ],
)
def test_plan_transaction_rejects_noncanonical_owner_or_version_before_locks(
    tmp_path: Path, destination: str, next_version: Any
) -> None:
    """Destination ownership and version shape are checked before mutation."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck")
    document = _plan(deck["id"])
    destination_path = project / destination.replace("decks/deck", f"decks/{deck['id']}", 1)
    with pytest.raises(ValueError, match="destination|deck|version|canonical|positive"):
        register_plan_transaction(
            project, deck["id"], document, "planner-a", destination_path, next_version
        )
    assert not destination_path.exists()
    assert not destination_path.with_suffix(destination_path.suffix + ".lock").exists()
    assert load_decks(project)[deck["id"]]["current_plan_id"] is None


def test_plan_transaction_rejects_malformed_existing_version_before_writes(tmp_path: Path) -> None:
    """Boolean or string stored versions cannot determine a new version."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck")
    state_dir = project / ".research/presentations/state"
    plans_path = state_dir / "plans.yaml"
    plans_path.parent.mkdir(parents=True, exist_ok=True)
    plans_path.write_text(
        yaml.safe_dump({"version": 2, "plans": {"plan-old": {"id": "plan-old", "deck_id": deck["id"], "version": True}}}),
        encoding="utf-8",
    )
    destination = _canonical_destination(project, deck["id"], 2)
    with pytest.raises(ValueError, match="version"):
        register_plan_transaction(project, deck["id"], _plan(deck["id"], 2), "planner-a", destination, 2)
    assert not destination.exists()
    assert plans_path.read_text(encoding="utf-8")


def test_plan_transaction_rejects_existing_immutable_destination(tmp_path: Path) -> None:
    """An immutable plan copy cannot be overwritten by a later transaction."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck")
    destination = _canonical_destination(project, deck["id"], 1)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    before = destination.read_bytes()
    with pytest.raises(ValueError, match="exists|immutable|overwrite"):
        register_plan_transaction(project, deck["id"], _plan(deck["id"]), "planner-a", destination, 1)
    assert destination.read_bytes() == before
    assert not destination.with_suffix(destination.suffix + ".lock").exists()


@pytest.mark.parametrize("special", ["broken_symlink", "fifo"])
def test_plan_transaction_rejects_unsafe_preexisting_sidecar_without_mutation(
    tmp_path: Path, special: str
) -> None:
    """A broken symlink or special sidecar remains byte/link/mode identical."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck")
    destination = _canonical_destination(project, deck["id"], 1)
    destination.parent.mkdir(parents=True)
    sidecar = destination.with_suffix(destination.suffix + ".lock")
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside")
    if special == "broken_symlink":
        sidecar.symlink_to(tmp_path / "does-not-exist")
        before_link = os.readlink(sidecar)
        before_mode = os.lstat(sidecar).st_mode
    else:
        os.mkfifo(sidecar, 0o640)
        before_link = None
        before_mode = os.lstat(sidecar).st_mode
    with pytest.raises(TransactionError, match="sidecar|regular|special|symlink"):
        register_plan_transaction(project, deck["id"], _plan(deck["id"]), "planner-a", destination, 1)
    assert outside.read_bytes() == b"outside"
    assert os.lstat(sidecar).st_mode == before_mode
    if before_link is not None:
        assert os.readlink(sidecar) == before_link


@pytest.mark.parametrize("attempt", [True, "1", 0, -1])
def test_review_sheet_source_attempt_type_is_checked_before_equality(
    tmp_path: Path, attempt: Any
) -> None:
    """Malformed persisted slide attempts cannot publish a review sheet."""
    from test_review_sheet_provenance import _published_slide_fixture

    project, deck_id, slide_id, _, staged_contact, contact_destination = _published_slide_fixture(tmp_path)
    artifacts_path = project / ".research/presentations/state/artifacts.yaml"
    artifacts = yaml.safe_load(artifacts_path.read_text(encoding="utf-8"))
    artifact = next(
        record for record in artifacts["artifacts"].values()
        if record.get("artifact_kind") == "slide-png" and record.get("slide_id") == slide_id
    )
    artifact["attempt"] = attempt
    artifacts_path.write_text(yaml.safe_dump(artifacts), encoding="utf-8")
    before = artifacts_path.read_bytes()
    with pytest.raises(PublicationGateError, match="attempt|provenance"):
        publish_artifact(
            project, deck_id, staged_contact, contact_destination, "review-sheet", None, None,
            "renderer", project / "plan.yaml",
        )
    assert artifacts_path.read_bytes() == before
    assert not contact_destination.exists()


def test_draft_decision_heterogeneous_keys_return_structured_error_without_writes(
    tmp_path: Path,
) -> None:
    """Unknown integer/null decision keys must not reach sorted/set operations."""
    from test_draft_review_gate import _approved_project, _preview

    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    registered = register_draft_preview(project, preview_path)
    decision_path = project / "decision.yaml"
    decision_path.write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "deck_id": deck_id,
            "preview_id": registered["preview"]["id"],
            "preview_sha256": registered["preview"]["preview_sha256"],
            "decision": "approve",
            7: "unknown",
            None: "unknown-null",
        }),
        encoding="utf-8",
    )
    decks_path = project / ".research/presentations/state/decks.yaml"
    before = decks_path.read_bytes()
    with pytest.raises(DraftGateError, match="mapping keys|unexpected"):
        approve_draft(project, decision_path)
    assert decks_path.read_bytes() == before


def test_public_subject_validation_precedes_unrelated_publish_inputs(tmp_path: Path) -> None:
    """Publisher reports subject mismatch before producer/path/contract checks."""
    project = _project(tmp_path)
    source = tmp_path / "source.svg"
    source.write_text("<svg/>", encoding="utf-8")
    destination = tmp_path / "outside.svg"
    with pytest.raises(PublicationGateError, match="subject"):
        publish_artifact(
            project, "missing-deck", source, destination, "slide-svg", None, "forbidden-module",
            "", project / "missing-contract.yaml",
        )
    assert not destination.exists()
    assert not (project / ".research").exists()


def test_public_subject_validation_precedes_deck_and_provenance_reads(tmp_path: Path) -> None:
    """Artifact record subject mismatch fails before deck/state/provenance validation."""
    from presentation_events import create_artifact_record

    project = _project(tmp_path)
    with pytest.raises(ValueError, match="review-sheet|slide_id|subject"):
        create_artifact_record(
            project, "missing-deck", "review-sheet", "renders/contact-sheet.png", "d" * 64,
            "", slide_id="forbidden-slide", plan_version=True, plan_sha256="invalid",
        )
    assert not (project / ".research").exists()


@pytest.mark.parametrize("fail_at", [1, 2])
def test_draft_reregistration_restores_event_and_deck_preimages_with_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    """Every re-registration commit position restores bytes, modes, and no orphan."""
    from test_draft_review_gate import _approved_project, _preview, _file_preimage

    project, deck_id, plan = _approved_project(tmp_path)
    preview_path, _ = _preview(project, deck_id, plan)
    first = register_draft_preview(project, preview_path)
    decision_path = project / "decision.yaml"
    decision_path.write_text(yaml.safe_dump({
        "schema_version": 1, "deck_id": deck_id, "preview_id": first["preview"]["id"],
        "preview_sha256": first["preview"]["preview_sha256"], "decision": "approve",
        "approved_by": "reviewer",
    }), encoding="utf-8")
    approve_draft(project, decision_path)
    decks_path = project / ".research/presentations/state/decks.yaml"
    event_path = events_shard_path(project)
    decks_path.chmod(0o640)
    event_path.chmod(0o600)
    before = {path: _file_preimage(path) for path in (decks_path, event_path)}
    before_events = load_events(project)
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", str(fail_at))
    with pytest.raises(RuntimeError, match="injected transaction commit failure"):
        register_draft_preview(project, preview_path)
    assert {path: _file_preimage(path) for path in (decks_path, event_path)} == before
    assert load_events(project) == before_events
    assert not list((project / ".research/presentations/events").glob("*.transaction.*"))
