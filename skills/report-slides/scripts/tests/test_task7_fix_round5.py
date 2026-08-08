"""Regression tests for the final Task 7 plan-transaction hardening."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import pytest

from presentation_plan_transactions import register_plan_transaction
from presentation_state import create_deck


def _project(tmp_path: Path) -> Path:
    """Create a temporary project recognized by presentation state."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _plan(deck_id: str, version: int = 1) -> dict[str, Any]:
    """Return a minimal plan document for transaction tests."""
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


def _destination(project: Path, deck_id: str, version: int = 1) -> Path:
    """Return the canonical immutable destination for one plan version."""
    return project / "decks" / deck_id / "plans" / f"plan-v{version:04d}.yaml"


def _preimage(path: Path) -> tuple[bool, bytes, int, int | None]:
    """Capture exact existence, bytes, mode, and inode without following links."""
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return False, b"", 0, None
    if not os.path.isfile(path):
        return True, b"", metadata.st_mode & 0o777, metadata.st_ino
    return True, path.read_bytes(), metadata.st_mode & 0o777, metadata.st_ino


def _state_preimages(project: Path) -> dict[Path, tuple[bool, bytes, int, int | None]]:
    """Capture the mutable plan/deck stores before a direct registration."""
    state = project / ".research/presentations/state"
    return {
        path: _preimage(path)
        for path in (state / "decks.yaml", state / "plans.yaml")
    }


@pytest.mark.parametrize(
    ("document_factory", "message"),
    [
        (lambda deck_id: {**_plan(deck_id), "deck_id": "deck-other"}, "deck_id"),
        (lambda deck_id: {**_plan(deck_id), "plan_version": 2}, "plan_version"),
        (lambda deck_id: {**_plan(deck_id), "plan_version": True}, "plan_version"),
        (lambda deck_id: {key: value for key, value in _plan(deck_id).items() if key != "deck_id"}, "deck_id"),
        (lambda deck_id: {**_plan(deck_id), "deck_id": ""}, "deck_id"),
        (lambda deck_id: {**_plan(deck_id), "plan_version": 0}, "plan_version"),
    ],
)
def test_plan_transaction_rejects_document_identity_before_any_write(
    tmp_path: Path,
    document_factory: Callable[[str], Any],
    message: str,
) -> None:
    """Reject mismatched document identity without creating state or locks."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck")
    deck_id = deck["id"]
    destination = _destination(project, deck_id)
    sidecar = destination.with_suffix(destination.suffix + ".lock")
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-before")
    before_state = _state_preimages(project)
    document = document_factory(deck_id)

    with pytest.raises(ValueError, match=message):
        register_plan_transaction(
            project,
            deck_id,
            document,
            "planner-a",
            destination,
            1,
        )

    assert _state_preimages(project) == before_state
    assert _preimage(destination) == (False, b"", 0, None)
    assert _preimage(sidecar) == (False, b"", 0, None)
    assert outside.read_bytes() == b"outside-before"
    assert not list((project / ".research/presentations/transactions").glob("*.json"))
    assert not list(project.rglob("*.transaction.*"))


def test_plan_transaction_rejects_non_mapping_document_before_any_write(
    tmp_path: Path,
) -> None:
    """Reject a non-mapping document before calculating a digest or locking."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck")
    destination = _destination(project, deck["id"])
    before_state = _state_preimages(project)

    with pytest.raises(ValueError, match="mapping|document"):
        register_plan_transaction(
            project,
            deck["id"],
            ["not", "a", "mapping"],  # type: ignore[arg-type]
            "planner-a",
            destination,
            1,
        )

    assert _state_preimages(project) == before_state
    assert _preimage(destination) == (False, b"", 0, None)
    assert not list(project.rglob("*.transaction.*"))


def test_plan_transaction_rechecks_destination_absence_after_lock_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a destination created while its canonical sidecar is acquired."""
    project = _project(tmp_path)
    deck = create_deck(project, "Evidence deck")
    deck_id = deck["id"]
    destination = _destination(project, deck_id)
    before_state = _state_preimages(project)
    raced_bytes = b"raced immutable plan\n"
    raced_mode = 0o640
    raced_preimage: dict[str, tuple[bool, bytes, int, int | None]] = {}

    import presentation_transactions

    original_open_sidecar = presentation_transactions._open_sidecar

    def create_raced_destination(path: Path) -> int:
        """Create the immutable destination in the lock-acquisition gap."""
        descriptor = original_open_sidecar(path)
        if path.resolve() == destination.resolve() and not destination.exists():
            destination.write_bytes(raced_bytes)
            destination.chmod(raced_mode)
            raced_preimage["destination"] = _preimage(destination)
        return descriptor

    monkeypatch.setattr(presentation_transactions, "_open_sidecar", create_raced_destination)

    with pytest.raises(ValueError, match="exists|immutable|destination"):
        register_plan_transaction(
            project,
            deck_id,
            _plan(deck_id),
            "planner-a",
            destination,
            1,
        )

    assert raced_preimage["destination"][:3] == (True, raced_bytes, raced_mode)
    assert raced_preimage["destination"][3] is not None
    assert _preimage(destination) == raced_preimage["destination"]
    assert _state_preimages(project) == before_state
    assert not list((project / ".research/presentations/transactions").glob("*.json"))
    assert not list(project.rglob("*.transaction.*"))
