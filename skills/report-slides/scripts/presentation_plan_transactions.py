"""Atomic plan-version registration helpers for report-slides workflow actions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from presentation_contracts import contract_sha256
from presentation_events import _generate_id
from presentation_transactions import transaction


def _utc_now() -> str:
    """Return a UTC timestamp in the durable presentation-state format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plan_record(
    deck_id: str,
    version: int,
    destination: Path,
    plan_sha256: str,
    authored_by: str,
    supersedes_plan_id: str | None,
) -> dict[str, Any]:
    """Build one immutable persisted plan record without writing state."""
    relative_path = destination.as_posix()
    return {
        "id": _generate_id("plan"),
        "deck_id": deck_id,
        "version": version,
        "plan_path": relative_path,
        "path": relative_path,
        "sha256": plan_sha256,
        "plan_sha256": plan_sha256,
        "authored_by": authored_by,
        "created_by": authored_by,
        "supersedes_plan_id": supersedes_plan_id,
        "created_at": _utc_now(),
    }


def _clear_plan_approval(deck: dict[str, Any]) -> None:
    """Clear approval and draft-preview pointers after a plan replacement."""
    deck.update({
        "status": "planning",
        "approved_plan_version": None,
        "approved_plan_sha256": None,
        "approval_id": None,
        "approved_by": None,
        "approved_at": None,
        "approval_mode": None,
        "draft_preview_id": None,
        "draft_approval_id": None,
        "plan_revision_required": False,
        "required_plan_id": None,
        "required_plan_revision_id": None,
    })


def register_plan_transaction(
    project_root: Path,
    deck_id: str,
    document: Mapping[str, Any],
    authored_by: str,
    destination: Path,
    next_version: int,
) -> dict[str, Any]:
    """Register a plan, immutable copy, and deck pointers atomically.

    Args:
        project_root: Project root containing durable presentation state.
        deck_id: Deck identifier owning the new plan.
        document: Already validated Deck Plan mapping.
        authored_by: Trimmed planner identity.
        destination: Project-relative immutable plan destination.
        next_version: Expected next plan version for this deck.

    Returns:
        The newly persisted plan record.

    Raises:
        RuntimeError: If the transaction commit fails and is rolled back.
        ValueError: If durable state does not contain the expected deck.
    """
    state_dir = project_root / ".research/presentations/state"
    decks_path = state_dir / "decks.yaml"
    plans_path = state_dir / "plans.yaml"
    destination_path = project_root / destination
    plan_digest = contract_sha256(document)
    paths = (decks_path, plans_path, destination_path)
    destination_lock = destination_path.with_suffix(destination_path.suffix + ".lock")
    destination_lock_existed = destination_lock.exists()
    existing_directories: set[Path] = set()
    directory = destination_path.parent
    while directory != project_root and directory != project_root.parent:
        if directory.exists():
            existing_directories.add(directory.resolve())
        directory = directory.parent
    try:
        with transaction(paths, project_root) as tx:
            decks = tx.read_yaml(decks_path, "decks")
            deck = decks.get(deck_id)
            if not isinstance(deck, dict):
                raise ValueError(f"Unknown deck_id: {deck_id}")
            plans = tx.read_yaml(plans_path, "plans")
            prior = sorted(
                (record for record in plans.values() if record.get("deck_id") == deck_id),
                key=lambda record: (int(record.get("version", 0)), str(record.get("created_at", ""))),
            )
            expected_version = (int(prior[-1]["version"]) if prior else 0) + 1
            if expected_version != next_version:
                raise ValueError(
                    f"plan version changed during registration: expected {next_version}, "
                    f"current {expected_version}"
                )
            record = _plan_record(
                deck_id,
                next_version,
                destination,
                plan_digest,
                authored_by,
                prior[-1]["id"] if prior else None,
            )
            plans[record["id"]] = record
            deck.update({
                "plan_version": next_version,
                "current_plan_id": record["id"],
                "updated_at": _utc_now(),
            })
            if prior:
                _clear_plan_approval(deck)
            payload = yaml.safe_dump(
                dict(document), sort_keys=True, allow_unicode=True
            ).encode("utf-8")
            tx.stage_bytes(destination_path, payload)
            tx.stage_yaml(plans_path, "plans", plans)
            tx.stage_yaml(decks_path, "decks", decks)
            tx.commit()
            return record
    except Exception:
        if not destination_lock_existed:
            try:
                destination_lock.unlink()
            except FileNotFoundError:
                pass
        _remove_empty_plan_directories(destination_path, project_root, existing_directories)
        raise


def _remove_empty_plan_directories(
    destination: Path, project_root: Path, preserved: set[Path]
) -> None:
    """Remove directories created solely for a rolled-back new plan."""
    root = project_root.resolve()
    current = destination.parent
    while current != root and current != root.parent:
        if current.resolve() in preserved:
            break
        try:
            current.rmdir()
        except FileNotFoundError:
            current = current.parent
            continue
        except OSError:
            break
        current = current.parent
