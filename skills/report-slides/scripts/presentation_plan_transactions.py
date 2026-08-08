"""Atomic plan-version registration helpers for report-slides workflow actions."""

from __future__ import annotations

from datetime import datetime, timezone
import os
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


def _canonical_plan_destination(
    project_root: Path,
    deck_id: str,
    next_version: int,
    destination: Path,
) -> tuple[Path, str]:
    """Validate and normalize the one immutable destination for a plan.

    Args:
        project_root: Resolved project root.
        deck_id: Existing safe deck identifier.
        next_version: Exact next positive integer version.
        destination: Caller-provided destination, relative or project-absolute.

    Returns:
        The canonical destination path and its project-relative POSIX spelling.

    Raises:
        ValueError: If any destination or version invariant is violated.
    """
    if not isinstance(deck_id, str) or not deck_id or deck_id != deck_id.strip():
        raise ValueError("deck_id must be a non-empty trimmed string")
    deck_parts = Path(deck_id).parts
    if len(deck_parts) != 1 or deck_parts[0] in {".", ".."} or "/" in deck_id or "\\" in deck_id:
        raise ValueError("deck_id must be one safe path component")
    if type(next_version) is not int or next_version <= 0:
        raise ValueError("next_version must be a positive integer")
    expected_relative = Path("decks") / deck_id / "plans" / f"plan-v{next_version:04d}.yaml"
    raw_destination = destination.as_posix() if isinstance(destination, Path) else str(destination)
    if Path(raw_destination).is_absolute():
        try:
            supplied_relative = Path(raw_destination).relative_to(project_root)
        except ValueError as exc:
            raise ValueError("destination must be inside project root") from exc
    else:
        supplied_relative = Path(raw_destination)
    if supplied_relative.as_posix() != expected_relative.as_posix():
        raise ValueError(
            "destination must equal canonical deck plan path "
            f"{expected_relative.as_posix()}"
        )
    destination_path = project_root / expected_relative
    cursor = project_root
    for component in expected_relative.parts[:-1]:
        cursor /= component
        if cursor.is_symlink():
            raise ValueError(f"destination parent must not be a symlink: {cursor}")
    if os.path.lexists(destination_path):
        raise ValueError(f"immutable plan destination already exists: {destination_path}")
    return destination_path, expected_relative.as_posix()


def _load_state_map(path: Path, top_key: str) -> dict[str, Any]:
    """Read one unlocked state map for pre-lock input validation."""
    if not path.exists():
        return {}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid state YAML in {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("version", 1) != 1:
        raise ValueError(f"invalid state document in {path}")
    records = document.get(top_key, {}) or {}
    if not isinstance(records, dict) or any(not isinstance(record, dict) for record in records.values()):
        raise ValueError(f"invalid {top_key} map in {path}")
    return records


def _validate_plan_versions(plans: Mapping[str, Any]) -> None:
    """Require every stored plan version to be an exact positive integer."""
    for plan_id, record in plans.items():
        version = record.get("version") if isinstance(record, Mapping) else None
        if type(version) is not int or version <= 0:
            raise ValueError(f"stored plan {plan_id!r} version must be a positive integer")


def _validate_document_identity(
    document: object,
    deck_id: object,
    next_version: object,
) -> None:
    """Validate plan ownership and version before any filesystem access.

    Args:
        document: Caller-provided Deck Plan mapping.
        deck_id: Deck identifier supplied to the registration helper.
        next_version: Version supplied to the registration helper.

    Raises:
        ValueError: If the document is not a mapping or its identity does not
            exactly match the helper arguments.
    """
    if not isinstance(document, Mapping):
        raise ValueError("document must be a mapping")
    if not isinstance(deck_id, str) or not deck_id:
        raise ValueError("deck_id must be a non-empty string")
    if type(next_version) is not int or next_version <= 0:
        raise ValueError("next_version must be a positive integer")
    document_deck_id = document.get("deck_id")
    if (
        type(document_deck_id) is not str
        or not document_deck_id
        or document_deck_id != deck_id
    ):
        raise ValueError("document deck_id must be a non-empty string matching deck_id")
    document_version = document.get("plan_version")
    if type(document_version) is not int or document_version <= 0:
        raise ValueError("document plan_version must be a positive integer")
    if document_version != next_version:
        raise ValueError(
            "document plan_version must match next_version "
            f"({next_version})"
        )


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
    _validate_document_identity(document, deck_id, next_version)
    root = project_root.resolve()
    state_dir = root / ".research/presentations/state"
    decks_path = state_dir / "decks.yaml"
    plans_path = state_dir / "plans.yaml"
    destination_path, relative_destination = _canonical_plan_destination(
        root, deck_id, next_version, destination
    )
    initial_decks = _load_state_map(decks_path, "decks")
    if deck_id not in initial_decks:
        raise ValueError(f"Unknown deck_id: {deck_id}")
    initial_plans = _load_state_map(plans_path, "plans")
    _validate_plan_versions(initial_plans)
    prior_initial = [
        record for record in initial_plans.values()
        if record.get("deck_id") == deck_id
    ]
    expected_initial = max((record["version"] for record in prior_initial), default=0) + 1
    if expected_initial != next_version:
        raise ValueError(
            f"plan version changed during registration: expected {next_version}, "
            f"current {expected_initial}"
        )
    plan_digest = contract_sha256(document)
    paths = (decks_path, plans_path, destination_path)
    with transaction(paths, root) as tx:
        if os.path.lexists(destination_path):
            raise ValueError(
                "immutable plan destination appeared while acquiring its lock: "
                f"{destination_path}"
            )
        decks = tx.read_yaml(decks_path, "decks")
        deck = decks.get(deck_id)
        if not isinstance(deck, dict):
            raise ValueError(f"Unknown deck_id: {deck_id}")
        plans = tx.read_yaml(plans_path, "plans")
        _validate_plan_versions(plans)
        prior = sorted(
            (record for record in plans.values() if record.get("deck_id") == deck_id),
            key=lambda record: (record["version"], str(record.get("created_at", ""))),
        )
        expected_version = (prior[-1]["version"] if prior else 0) + 1
        if expected_version != next_version:
            raise ValueError(
                f"plan version changed during registration: expected {next_version}, "
                f"current {expected_version}"
            )
        record = _plan_record(
            deck_id,
            next_version,
            Path(relative_destination),
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
