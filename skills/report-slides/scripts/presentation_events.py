#!/usr/bin/env python3
"""Append-only event storage for the report-slides workflow.

Events are sharded by UTC date and are deliberately kept separate from the
mutable YAML state records.  This module owns both sides of the event I/O
contract so every reader reports malformed JSONL with enough context to repair
the offending shard instead of silently dropping history.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

import yaml

from presentation_contracts import contract_sha256, load_contract
from presentation_evidence_contracts import EVIDENCE_SCHEMA_VERSION
from presentation_artifact_provenance import (
    validate_artifact_provenance,
    validate_artifact_subject,
)
from presentation_transactions import _open_sidecar, require_transaction_recovery


EVENTS_RELATIVE_DIR = Path(".research/presentations/events")
PLANS_RELATIVE_PATH = Path(".research/presentations/state/plans.yaml")
ASSIGNMENTS_RELATIVE_PATH = Path(".research/presentations/state/assignments.yaml")
ARTIFACTS_RELATIVE_PATH = Path(".research/presentations/state/artifacts.yaml")
REVISION_REQUESTS_RELATIVE_PATH = Path(".research/presentations/state/revision_requests.yaml")
STATE_SCHEMA_VERSION = EVIDENCE_SCHEMA_VERSION
LOCK_TIMEOUT_SECONDS = int(os.environ.get("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS", "30"))
LOCK_POLL_INTERVAL_SECONDS = 0.1


class StateParseError(ValueError):
    """Raised when a persisted presentation event cannot be parsed safely."""


class LockTimeoutError(RuntimeError):
    """Raised when an event-shard lock cannot be acquired in time."""


def _ensure_research_gitignore(project_root: Path) -> None:
    """Create the presentation subtree ignore rules on the first event write.

    Args:
        project_root: Root directory of the project owning the state.
    """
    gitignore_path = project_root / ".research" / "presentations" / ".gitignore"
    if gitignore_path.exists():
        return
    gitignore_path.parent.mkdir(parents=True, exist_ok=True)
    gitignore_path.write_text("state/*.lock\nstate/*.tmp\nevents/\ncache/\n", encoding="utf-8")


@contextmanager
def _locked_file(project_root: Path, path: Path) -> Iterator[None]:
    """Lock one event shard through a stable sidecar inode.

    Args:
        project_root: Root directory of the project owning the state.
        path: Event shard or related file being protected.

    Raises:
        LockTimeoutError: If another process holds the lock too long.
    """
    require_transaction_recovery(project_root, allow_publication_temporary=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    descriptor = _open_sidecar(path)
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"Could not acquire lock on {lock_path} within {LOCK_TIMEOUT_SECONDS}s"
                    )
                time.sleep(LOCK_POLL_INTERVAL_SECONDS)
        require_transaction_recovery(project_root)
        _ensure_research_gitignore(project_root)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def events_shard_path(project_root: Path, when: datetime | None = None) -> Path:
    """Return the UTC-date JSONL shard path for an event.

    Args:
        project_root: Root directory of the project owning the state.
        when: Optional UTC datetime; current UTC time is used by default.

    Returns:
        Absolute or project-relative path to the date shard.
    """
    timestamp = when or datetime.now(timezone.utc)
    return project_root / EVENTS_RELATIVE_DIR / f"{timestamp:%Y-%m-%d}.jsonl"


def append_event(project_root: Path, event: dict[str, Any]) -> None:
    """Append one JSON-serializable immutable event atomically under a lock.

    Args:
        project_root: Root directory of the project owning the state.
        event: Event mapping to append.

    Raises:
        TypeError: If the event is not JSON serializable.
        ValueError: If ``event`` is not a mapping.
    """
    from presentation_evidence_workflow import require_schema_v2

    require_schema_v2(project_root)
    if not isinstance(event, dict):
        raise ValueError("event must be a mapping")
    encoded = json.dumps(event, sort_keys=True, ensure_ascii=False)
    shard_path = events_shard_path(project_root)
    with _locked_file(project_root, shard_path):
        with shard_path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.write("\n")


def _read_event_shard(shard_path: Path) -> list[dict[str, Any]]:
    """Read one JSONL shard and identify its first malformed line.

    Args:
        shard_path: JSONL shard to read.

    Returns:
        Parsed event mappings in file order.

    Raises:
        StateParseError: If any line is malformed or is not an object.
    """
    events: list[dict[str, Any]] = []
    try:
        lines = shard_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise StateParseError(f"Unable to read event shard {shard_path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StateParseError(
                f"Malformed JSON in event shard {shard_path} line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(value, dict):
            raise StateParseError(
                f"Malformed event in event shard {shard_path} line {line_number}: expected object"
            )
        events.append(value)
    return events


def load_events(project_root: Path, event_type: str | None = None) -> list[dict[str, Any]]:
    """Load all event records in deterministic shard and line order.

    Args:
        project_root: Root directory of the project owning the state.
        event_type: Optional event name to retain.

    Returns:
        Parsed immutable event records, sorted by timestamp and ID where
        available.

    Raises:
        StateParseError: If any JSONL shard is malformed.
    """
    events_root = project_root / EVENTS_RELATIVE_DIR
    if not events_root.exists():
        return []
    records: list[dict[str, Any]] = []
    for shard_path in sorted(events_root.glob("*.jsonl"), key=lambda path: path.name):
        records.extend(_read_event_shard(shard_path))
    if event_type is not None:
        records = [event for event in records if event.get("event") == event_type]
    return sorted(records, key=lambda event: (str(event.get("ts", "")), str(event.get("id", ""))))


def load_review_results(
    project_root: Path, subject_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    """Load persisted review-result events for selected subjects.

    Args:
        project_root: Root directory of the project owning the state.
        subject_ids: Optional set of deck, slide, or module IDs to include.

    Returns:
        Review result mappings in deterministic chronological order.  Legacy
        records are returned exactly as persisted so unverifiable evidence is
        never upgraded into an approval-grade identity.

    Raises:
        StateParseError: If any event shard contains malformed JSONL.
    """
    reviews = load_events(project_root, event_type="review_result")
    if subject_ids is not None:
        reviews = [review for review in reviews if review.get("subject_id") in subject_ids]
    return reviews


def effective_review_results(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select the latest review round for each typed subject and reviewer role.

    Full history remains available to callers through ``load_review_results``;
    workflow predicates consume only this deterministic effective view.
    """
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for review in reviews:
        subject_type = review.get("subject_type")
        subject_id = review.get("subject_id")
        role = review.get("reviewer_role")
        if (
            not isinstance(subject_type, str)
            or not subject_type.strip()
            or not isinstance(subject_id, str)
            or not isinstance(role, str)
        ):
            continue
        key = (subject_type, subject_id, role)
        previous = latest.get(key)
        current_order = (
            int(review.get("round", 1)) if isinstance(review.get("round", 1), int) else 1,
            str(review.get("ts", "")),
            str(review.get("id", "")),
        )
        previous_order = (
            int(previous.get("round", 1)) if previous and isinstance(previous.get("round", 1), int) else 1,
            str(previous.get("ts", "")) if previous else "",
            str(previous.get("id", "")) if previous else "",
        )
        if previous is None or current_order > previous_order:
            latest[key] = review
    return sorted(
        latest.values(),
        key=lambda review: (
            str(review.get("subject_type", "")),
            str(review.get("subject_id", "")),
            str(review.get("reviewer_role", "")),
        ),
    )


def _reviewer_identity_is_verifiable(review: dict[str, Any]) -> bool:
    """Return whether a persisted review has a canonical reviewer identity."""
    reviewer_id = review.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not reviewer_id or reviewer_id != reviewer_id.strip():
        return False
    identity_flag = review.get("identity_verifiable")
    return identity_flag is None or identity_flag is True


def workflow_blockers(
    deck: dict[str, Any],
    slides: list[dict[str, Any]],
    modules: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    draft_preview: dict[str, Any] | None,
    draft_decision: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Collect explicit state, review, identity, and missing-evidence blockers."""
    blockers: list[dict[str, Any]] = []
    if deck.get("status") == "blocked":
        blockers.append({"subject_type": "deck", "subject_id": deck["id"], "reason": "status:blocked"})
    for record_type, records in (("slide", slides), ("module", modules)):
        for record in records:
            if record.get("status") == "blocked":
                blockers.append({"subject_type": record_type, "subject_id": record["id"], "reason": "status:blocked"})
    for assignment in assignments:
        if assignment.get("blocker"):
            blockers.append({
                "subject_type": "module" if assignment.get("module_id") else "slide",
                "subject_id": assignment.get("module_id") or assignment.get("slide_id"),
                "reason": assignment["blocker"],
            })
    for review in effective_review_results(reviews):
        if not _reviewer_identity_is_verifiable(review):
            blockers.append({"subject_type": review.get("subject_type"), "subject_id": review.get("subject_id"), "reason": "reviewer_identity_unverifiable"})
        if review.get("status") in {"failed", "blocked"}:
            blockers.append({
                "subject_type": review.get("subject_type"), "subject_id": review.get("subject_id"),
                "reason": f"review:{review.get('status')}", "findings": review.get("findings", []),
            })
    if deck.get("draft_preview_id") and draft_preview is None:
        blockers.append({"subject_type": "deck", "subject_id": deck["id"], "reason": "missing_draft_preview"})
    if deck.get("draft_approval_id") and draft_decision is None:
        blockers.append({"subject_type": "deck", "subject_id": deck["id"], "reason": "missing_draft_decision"})
    return sorted(blockers, key=lambda blocker: (str(blocker.get("subject_id", "")), str(blocker.get("reason", ""))))


def next_actions(
    deck: dict[str, Any],
    plans: list[dict[str, Any]],
    slides: list[dict[str, Any]],
    modules: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    approval: dict[str, Any] | None,
    draft_preview: dict[str, Any] | None,
) -> list[str]:
    """Compute legal next workflow actions from effective review outcomes."""
    roles_by_subject: dict[tuple[str, str], set[str]] = {}
    for review in effective_review_results(reviews):
        subject_type = review.get("subject_type")
        subject_id = review.get("subject_id")
        role = review.get("reviewer_role")
        if not isinstance(subject_type, str) or not isinstance(subject_id, str) or not isinstance(role, str):
            continue
        subject_key = (subject_type, subject_id)
        if review.get("status") == "passed" and _reviewer_identity_is_verifiable(review):
            roles_by_subject.setdefault(subject_key, set()).add(role)
        if review.get("status") in {"failed", "blocked"}:
            roles_by_subject.setdefault(subject_key, set()).discard(role)
    for slide in slides:
        roles = roles_by_subject.get(("slide", slide["id"]), set())
        if "scientific" in roles and "visual_quality" not in roles:
            return ["record_visual_quality_review"]
        if "visual_quality" in roles and "scientific" not in roles:
            return ["record_scientific_review"]
    if not plans:
        return ["register_plan"]
    if deck.get("status") == "planning":
        deck_roles = roles_by_subject.get(("deck", deck["id"]), set())
        if "content" not in deck_roles and "content_reviewer" not in deck_roles:
            return ["record_content_review"]
        return ["approve_deck"]
    if deck.get("status") == "awaiting_approval" and approval is None:
        return ["approve_deck"]
    if deck.get("status") in {"approved", "producing"} and any(module.get("status") == "planned" for module in modules):
        return ["assign_visual_modules"]
    if deck.get("status") == "draft_review" and draft_preview is None:
        return ["register_draft_preview"]
    if deck.get("status") == "validating":
        return ["complete_deck"]
    return []


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical_contract_digest(document: Any) -> str:
    """Return the shared canonical SHA-256 digest for a contract mapping."""
    return contract_sha256(document)


def load_contract_document(path: Path) -> Any:
    """Load a YAML/JSON contract through the shared contract loader."""
    return load_contract(path)


def _utc_now_iso() -> str:
    """Return the current UTC timestamp in the state format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_id(prefix: str) -> str:
    """Generate a sortable workflow record ID."""
    return f"{prefix}_{datetime.now(timezone.utc):%Y%m%d}_{uuid.uuid4().hex[:6]}"


def _load_yaml_map(path: Path, top_key: str) -> dict[str, Any]:
    """Load one versioned id-keyed state document."""
    if not path.exists():
        return {}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise StateParseError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise StateParseError(f"Invalid state document in {path}: expected mapping")
    version = document.get("version", 1)
    if type(version) is not int or version != STATE_SCHEMA_VERSION:
        raise StateParseError(
            f"Unsupported schema version {version!r} in {path} "
            f"(expected {STATE_SCHEMA_VERSION})"
        )
    records = document.get(top_key, {}) or {}
    if not isinstance(records, dict):
        raise StateParseError(f"Invalid {top_key} map in {path}: expected mapping")
    if any(not isinstance(record, dict) for record in records.values()):
        raise StateParseError(f"Invalid {top_key} map in {path}: records must be mappings")
    return records


def _save_yaml_map(path: Path, top_key: str, records: dict[str, Any]) -> None:
    """Atomically persist one id-keyed state document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump(
            {"version": STATE_SCHEMA_VERSION, top_key: records},
            sort_keys=True,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _state_module() -> Any:
    """Import presentation_state lazily to avoid an extraction cycle."""
    import presentation_state

    return presentation_state


def _deck(project_root: Path, deck_id: str) -> dict[str, Any]:
    """Return one existing deck through the public state loader."""
    state = _state_module()
    decks = state.load_decks(project_root)
    if deck_id not in decks:
        raise state.DeckNotFoundError(f"Unknown deck_id: {deck_id}")
    return decks[deck_id]


def canonical_relative_path(value: Path | str) -> str:
    """Normalize one path while rejecting absolute or parent traversal paths."""
    raw = value.as_posix() if isinstance(value, Path) else str(value).replace("\\", "/")
    if not raw or raw.startswith("/") or "\x00" in raw:
        raise ValueError(f"path must be a non-empty relative path: {value!r}")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"path must remain within the project root: {value!r}")
    return "/".join(parts)


def _digest(value: str, field: str) -> str:
    """Validate a lowercase SHA-256 digest."""
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a 64-character lowercase SHA-256 digest")
    return value


def load_plans(project_root: Path) -> dict[str, Any]:
    """Load immutable plan-version records."""
    return _load_yaml_map(project_root / PLANS_RELATIVE_PATH, "plans")


def register_plan_record(
    project_root: Path,
    deck_id: str,
    plan_path: Path | str,
    plan_sha256: str,
    authored_by: str,
) -> dict[str, Any]:
    """Register the next versioned plan and preserve its predecessor."""
    from presentation_evidence_workflow import require_schema_v2

    require_schema_v2(project_root)
    state = _state_module()
    _deck(project_root, deck_id)
    if not isinstance(authored_by, str) or not authored_by.strip():
        raise ValueError("authored_by is required")
    relative_path = canonical_relative_path(plan_path)
    digest = _digest(plan_sha256, "plan_sha256")
    path = project_root / PLANS_RELATIVE_PATH
    with _locked_file(project_root, path):
        plans = _load_yaml_map(path, "plans")
        prior = sorted(
            (record for record in plans.values() if record.get("deck_id") == deck_id),
            key=lambda record: (int(record.get("version", 0)), str(record.get("created_at", ""))),
        )
        version = (int(prior[-1]["version"]) if prior else 0) + 1
        record: dict[str, Any] = {
            "id": _generate_id("plan"), "deck_id": deck_id, "version": version,
            "plan_path": relative_path, "path": relative_path, "sha256": digest,
            "plan_sha256": digest,
            "authored_by": authored_by, "created_by": authored_by,
            "supersedes_plan_id": prior[-1]["id"] if prior else None,
            "created_at": _utc_now_iso(),
        }
        plans[record["id"]] = record
        _save_yaml_map(path, "plans", plans)
    decks_path = project_root / state.DECKS_RELATIVE_PATH
    with state._locked_file(project_root, decks_path):
        decks = state._load_yaml_map(decks_path, "decks")
        if deck_id not in decks:
            raise state.DeckNotFoundError(f"Unknown deck_id: {deck_id}")
        decks[deck_id]["plan_version"] = version
        decks[deck_id]["current_plan_id"] = record["id"]
        decks[deck_id]["updated_at"] = _utc_now_iso()
        state._save_yaml_map(decks_path, "decks", decks)
    return record


def _references(
    project_root: Path, deck_id: str, slide_id: str | None, module_id: str | None
) -> tuple[str | None, str | None]:
    """Validate optional slide/module references against one deck."""
    state = _state_module()
    slides = state.load_slides(project_root)
    modules = state.load_visual_modules(project_root)
    if slide_id is not None:
        if slide_id not in slides:
            raise state.SlideNotFoundError(f"Unknown slide_id: {slide_id}")
        if slides[slide_id].get("deck_id") != deck_id:
            raise ValueError(f"slide_id {slide_id!r} does not belong to deck {deck_id!r}")
    if module_id is not None:
        if module_id not in modules:
            raise state.VisualModuleNotFoundError(f"Unknown module_id: {module_id}")
        linked_slide = modules[module_id].get("slide_id")
        if linked_slide not in slides:
            raise state.SlideNotFoundError(f"Unknown slide_id: {linked_slide}")
        if slides[linked_slide].get("deck_id") != deck_id:
            raise ValueError(f"module_id {module_id!r} does not belong to deck {deck_id!r}")
        if slide_id is not None and linked_slide != slide_id:
            raise ValueError(f"module_id {module_id!r} does not belong to slide {slide_id!r}")
        slide_id = linked_slide
    return slide_id, module_id


def load_assignments(project_root: Path) -> dict[str, Any]:
    """Load immutable worker-assignment records."""
    return _load_yaml_map(project_root / ASSIGNMENTS_RELATIVE_PATH, "assignments")


def create_assignment_record(
    project_root: Path,
    deck_id: str,
    module_id: str | None = None,
    assignment_path: Path | str | None = None,
    worker_id: str = "",
    worker_type: str = "",
    spec_sha256: str = "",
    dependencies: list[str] | None = None,
    inputs_resolved: bool = True,
    blocker: str | None = None,
    slide_id: str | None = None,
) -> dict[str, Any]:
    """Persist a worker assignment with path and foreign-key validation."""
    from presentation_evidence_workflow import require_schema_v2

    require_schema_v2(project_root)
    state = _state_module()
    _deck(project_root, deck_id)
    if assignment_path is None:
        raise ValueError("assignment_path is required")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ValueError("worker_id is required")
    if not isinstance(worker_type, str) or not worker_type.strip():
        raise ValueError("worker_type is required")
    if not isinstance(inputs_resolved, bool):
        raise ValueError("inputs_resolved must be a bool")
    if blocker is not None and (not isinstance(blocker, str) or not blocker.strip()):
        raise ValueError("blocker must be a non-empty string or null")
    slide_id, module_id = _references(project_root, deck_id, slide_id, module_id)
    if dependencies is not None and not isinstance(dependencies, list):
        raise ValueError("dependencies must be a list")
    dependency_ids = list(dependencies or [])
    modules = state.load_visual_modules(project_root)
    slides = state.load_slides(project_root)
    if any(dependency not in modules for dependency in dependency_ids):
        unknown = next(dependency for dependency in dependency_ids if dependency not in modules)
        raise state.VisualModuleNotFoundError(f"Unknown dependency module id: {unknown}")
    for dependency in dependency_ids:
        dependency_slide = modules[dependency].get("slide_id")
        if dependency_slide not in slides:
            raise state.SlideNotFoundError(f"Unknown slide_id: {dependency_slide}")
        if slides[dependency_slide].get("deck_id") != deck_id:
            raise ValueError("assignment dependencies must belong to the same deck")
    path = project_root / ASSIGNMENTS_RELATIVE_PATH
    relative_path = canonical_relative_path(assignment_path)
    now = _utc_now_iso()
    record: dict[str, Any] = {
        "id": _generate_id("asn"), "deck_id": deck_id, "slide_id": slide_id,
        "module_id": module_id, "assignment_path": relative_path, "path": relative_path,
        "relative_path": relative_path, "worker_id": worker_id, "worker": worker_id,
        "worker_type": worker_type, "dependencies": dependency_ids,
        "spec_sha256": _digest(spec_sha256, "spec_sha256"),
        "inputs_resolved": inputs_resolved, "blocker": blocker,
        "assigned_at": now, "created_at": now,
    }
    if module_id is not None:
        modules_path = project_root / state.VISUAL_MODULES_RELATIVE_PATH
        with state._locked_file(project_root, modules_path):
            modules = state._load_yaml_map(modules_path, "visual_modules")
            if module_id not in modules:
                raise state.VisualModuleNotFoundError(f"Unknown module_id: {module_id}")
            with _locked_file(project_root, path):
                records = _load_yaml_map(path, "assignments")
                records[record["id"]] = record
                _save_yaml_map(path, "assignments", records)
                modules[module_id]["assignment_path"] = relative_path
                modules[module_id]["updated_at"] = _utc_now_iso()
                state._save_yaml_map(modules_path, "visual_modules", modules)
    else:
        with _locked_file(project_root, path):
            records = _load_yaml_map(path, "assignments")
            records[record["id"]] = record
            _save_yaml_map(path, "assignments", records)
    return record


def register_assignment_record(
    project_root: Path, *args: Any, **kwargs: Any
) -> dict[str, Any]:
    """Register an assignment using deck-oriented or module-oriented inputs.

    The module-oriented shorthand is ``(module_id, path, worker_id,
    worker_type, spec_sha256)``; the full keyword form is delegated to
    :func:`create_assignment_record`.
    """
    if "deck_id" in kwargs or (args and len(args) >= 2 and args[0] in _state_module().load_decks(project_root)):
        return create_assignment_record(project_root, *args, **kwargs)
    if len(args) < 5:
        raise TypeError("register_assignment_record requires deck_id or module shorthand")
    module_id, assignment_path, worker_id, worker_type, spec_sha256 = args[:5]
    state = _state_module()
    modules = state.load_visual_modules(project_root)
    if module_id not in modules:
        raise state.VisualModuleNotFoundError(f"Unknown module_id: {module_id}")
    slide_id = modules[module_id]["slide_id"]
    deck_id = state.load_slides(project_root)[slide_id]["deck_id"]
    return create_assignment_record(
        project_root, deck_id, module_id=module_id, assignment_path=assignment_path,
        worker_id=worker_id, worker_type=worker_type, spec_sha256=spec_sha256,
        dependencies=kwargs.get("dependencies"), inputs_resolved=kwargs.get("inputs_resolved", True),
        blocker=kwargs.get("blocker"), slide_id=slide_id,
    )


def load_artifacts(project_root: Path) -> dict[str, Any]:
    """Load immutable artifact records."""
    return _load_yaml_map(project_root / ARTIFACTS_RELATIVE_PATH, "artifacts")


def create_artifact_record(
    project_root: Path,
    deck_id: str,
    artifact_kind: str,
    artifact_path: Path | str,
    sha256: str,
    producer_id: str,
    slide_id: str | None = None,
    module_id: str | None = None,
    plan_version: int | None = None,
    plan_sha256: str | None = None,
    slide_record_id: str | None = None,
    attempt: int | None = None,
    source_paths: Sequence[str] | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Persist one artifact digest with canonical path and typed provenance.

    Args:
        project_root: Project root containing presentation state.
        deck_id: Owning deck identifier.
        artifact_kind: Canonical artifact kind.
        artifact_path: Project-relative artifact path.
        sha256: Artifact SHA-256 digest.
        producer_id: Trimmed producer identity.
        slide_id: Optional generated slide record identifier.
        module_id: Optional generated visual-module identifier.
        plan_version: Positive approved plan version for typed artifacts.
        plan_sha256: Approved plan digest for typed artifacts.
        slide_record_id: Current generated slide record identifier.
        attempt: Current generated slide attempt number.
        source_paths: Ordered source paths for a review sheet.
        source_sha256: Canonical ordered source digest for a review sheet.

    Returns:
        The persisted canonical artifact record.

    Raises:
        ValueError: If kind-specific provenance is incomplete or malformed.
    """
    from presentation_evidence_workflow import require_schema_v2

    require_schema_v2(project_root)
    # Subject cardinality is pure and must fail before any deck/state reads or
    # unrelated producer/path/provenance validation.
    validate_artifact_subject(artifact_kind, slide_id, module_id)
    state = _state_module()
    _deck(project_root, deck_id)
    if not isinstance(producer_id, str) or not producer_id.strip():
        raise ValueError("producer_id is required")
    provenance = validate_artifact_provenance(
        artifact_kind,
        deck_id=deck_id,
        slide_id=slide_id,
        module_id=module_id,
        plan_version=plan_version,
        plan_sha256=plan_sha256,
        slide_record_id=slide_record_id,
        attempt=attempt,
        source_paths=source_paths,
        source_sha256=source_sha256,
    )
    slide_id, module_id = _references(project_root, deck_id, slide_id, module_id)
    relative_path = canonical_relative_path(artifact_path)
    digest = _digest(sha256, "sha256")
    path = project_root / ARTIFACTS_RELATIVE_PATH
    record: dict[str, Any] = {
        "id": _generate_id("art"), "deck_id": deck_id, "slide_id": slide_id,
        "module_id": module_id, "artifact_kind": artifact_kind, "kind": artifact_kind,
        "path": relative_path, "relative_path": relative_path, "sha256": digest,
        "producer_id": producer_id, "produced_by": producer_id,
        "created_at": _utc_now_iso(),
    }
    record.update(provenance)
    if module_id is not None:
        modules_path = project_root / state.VISUAL_MODULES_RELATIVE_PATH
        with state._locked_file(project_root, modules_path):
            modules = state._load_yaml_map(modules_path, "visual_modules")
            if module_id not in modules:
                raise state.VisualModuleNotFoundError(f"Unknown module_id: {module_id}")
            with _locked_file(project_root, path):
                records = _load_yaml_map(path, "artifacts")
                records[record["id"]] = record
                _save_yaml_map(path, "artifacts", records)
                modules[module_id]["artifact_manifest_path"] = relative_path
                modules[module_id]["updated_at"] = _utc_now_iso()
                state._save_yaml_map(modules_path, "visual_modules", modules)
    else:
        with _locked_file(project_root, path):
            records = _load_yaml_map(path, "artifacts")
            records[record["id"]] = record
            _save_yaml_map(path, "artifacts", records)
    return record


register_artifact_record = create_artifact_record
create_plan_record = register_plan_record
create_assignment = create_assignment_record
create_artifact = create_artifact_record


def load_revision_requests(project_root: Path) -> dict[str, Any]:
    """Load id-keyed Revision Request records."""
    return _load_yaml_map(project_root / REVISION_REQUESTS_RELATIVE_PATH, "revision_requests")


def create_revision_request(
    project_root: Path,
    subject_type: str,
    subject_id: str,
    requested_by: str,
    instructions: str,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Persist a revision request and optionally supersede a passed unit."""
    from presentation_evidence_workflow import require_schema_v2

    require_schema_v2(project_root)
    state = _state_module()
    if subject_type not in state._REVIEW_SUBJECT_TYPES:
        raise ValueError(f"subject_type must be one of {sorted(state._REVIEW_SUBJECT_TYPES)}, got {subject_type!r}")
    if requested_by not in state._REVISION_REQUESTERS:
        raise ValueError(f"requested_by must be one of {sorted(state._REVISION_REQUESTERS)}, got {requested_by!r}")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError("instructions is required")
    if subject_type in ("plan", "deck"):
        _deck(project_root, subject_id)
    elif subject_type == "slide":
        if subject_id not in state.load_slides(project_root):
            raise state.SlideNotFoundError(f"Unknown slide_id: {subject_id}")
    elif subject_id not in state.load_visual_modules(project_root):
        raise state.VisualModuleNotFoundError(f"Unknown module_id: {subject_id}")
    supersede_kind: str | None = None
    if supersedes:
        slides = state.load_slides(project_root)
        modules = state.load_visual_modules(project_root)
        if supersedes in slides:
            supersede_kind, current = "slide", slides[supersedes]["status"]
        elif supersedes in modules:
            supersede_kind, current = "module", modules[supersedes]["status"]
        else:
            raise ValueError(f"Unknown supersedes id: {supersedes}")
        if "superseded" not in state._PRODUCTION_UNIT_TRANSITIONS[current]:
            raise ValueError(
                f"Cannot supersede {supersedes!r}: illegal transition {current!r} -> 'superseded'"
            )
    path = project_root / REVISION_REQUESTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        records = _load_yaml_map(path, "revision_requests")
        record: dict[str, Any] = {
            "id": _generate_id("rvq"), "subject_type": subject_type, "subject_id": subject_id,
            "requested_by": requested_by, "instructions": instructions,
            "supersedes": supersedes, "created_at": _utc_now_iso(),
        }
        records[record["id"]] = record
        _save_yaml_map(path, "revision_requests", records)
    if supersede_kind == "slide":
        state.set_slide_status(project_root, supersedes, "superseded")
    elif supersede_kind == "module":
        state.set_module_status(project_root, supersedes, "superseded")
    return record


# Compatibility aliases make the extraction explicit to callers that used the
# private names in the original state module while keeping one implementation.
_events_shard_path = events_shard_path
_append_event = append_event
