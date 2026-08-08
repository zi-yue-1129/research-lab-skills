#!/usr/bin/env python3
"""Atomic high-level actions for the report-slides workflow.

Each public action acquires one workflow-level lock before reading evidence,
appending immutable events, and mutating state.  Low-level state helpers stay
available for backwards-compatible diagnostics, but gated transitions enter
the persisted workflow only through this module.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml

from presentation_contracts import contract_sha256, load_contract
from presentation_events import (
    append_event,
    create_revision_request,
    effective_review_results,
    load_events,
    load_plans,
    load_review_results,
    register_plan_record,
)
from presentation_gates import (
    ApprovalGateError,
    CompletionGateError,
    DraftGateError,
    GateError,
    PlanGateError,
    ProductionGateError,
    ReviewGateError,
    assert_deck_completable,
    assert_draft_reviewable,
    assert_plan_approvable,
    assert_plan_reviewable,
    assert_production_allowed,
    assert_slide_passable,
)
from validate_deck_plan import validate_deck_plan


WORKFLOW_LOCK_RELATIVE_PATH = Path(".research/presentations/state/workflow.lock")
_REVISION_KINDS = frozenset(
    {
        "revise_slide", "add_slide", "remove_slide", "reorder_slides",
        "change_emphasis", "change_audience", "change_duration",
        "review_finding", "module_retry", "slide_retry",
    }
)


def _state() -> Any:
    """Import presentation_state lazily to avoid its workflow import cycle."""
    import presentation_state

    return presentation_state


@contextmanager
def _workflow_lock(project_root: Path) -> Iterator[None]:
    """Hold the stable workflow lock for one complete state transition."""
    path = project_root / WORKFLOW_LOCK_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    descriptor = os.open(str(path), os.O_RDWR)
    timeout = int(os.environ.get("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS", "30"))
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Could not acquire workflow lock {path} within {timeout}s")
                time.sleep(0.05)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _now() -> str:
    """Return a UTC timestamp in the state format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _id(prefix: str) -> str:
    """Generate a deterministic-shape workflow event identifier."""
    return f"{prefix}_{datetime.now(timezone.utc):%Y%m%d}_{uuid.uuid4().hex[:6]}"


def _document(path_or_document: Path | Mapping[str, Any]) -> dict[str, Any]:
    """Load one workflow contract from a path or copy a mapping."""
    if not isinstance(path_or_document, (Path, Mapping)):
        raise ValueError("workflow document path or mapping is required")
    value: Any = load_contract(path_or_document) if isinstance(path_or_document, Path) else dict(path_or_document)
    if not isinstance(value, dict):
        raise ValueError("workflow document must be a mapping")
    return value


def _action_document(
    path_or_document: Path | Mapping[str, Any],
    error_type: type[GateError],
    predicate: str,
    deck_id: str,
) -> dict[str, Any]:
    """Load an action document or expose parse failures as gate evidence."""
    try:
        return _document(path_or_document)
    except Exception as exc:  # noqa: BLE001 - every CLI failure is structured
        raise error_type(
            predicate,
            deck_id,
            [{"reason": "invalid_evidence_document", "message": str(exc)}],
            f"{predicate} blocked for deck {deck_id}: invalid evidence document",
        ) from exc


def _save_document(path: Path, document: Mapping[str, Any]) -> None:
    """Atomically write a YAML workflow contract."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(yaml.safe_dump(dict(document), sort_keys=True, allow_unicode=True), encoding="utf-8")
    temporary.replace(path)


def _deck(project_root: Path, deck_id: str) -> dict[str, Any]:
    """Return one persisted deck or raise its typed not-found error."""
    decks = _state().load_decks(project_root)
    if deck_id not in decks:
        raise _state().DeckNotFoundError(f"Unknown deck_id: {deck_id}")
    return decks[deck_id]


def _save_deck(project_root: Path, deck_id: str, updates: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one update mapping to a deck under its mutable-file lock."""
    state = _state()
    path = project_root / state.DECKS_RELATIVE_PATH
    with state._locked_file(project_root, path):
        decks = state._load_yaml_map(path, "decks")
        if deck_id not in decks:
            raise state.DeckNotFoundError(f"Unknown deck_id: {deck_id}")
        decks[deck_id].update(dict(updates))
        decks[deck_id]["updated_at"] = _now()
        state._save_yaml_map(path, "decks", decks)
        return decks[deck_id]


def _save_unit(project_root: Path, kind: str, record_id: str, updates: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one update mapping to a slide/module under its file lock."""
    state = _state()
    path, top_key, not_found = {
        "slide": (state.SLIDES_RELATIVE_PATH, "slides", state.SlideNotFoundError),
        "module": (state.VISUAL_MODULES_RELATIVE_PATH, "visual_modules", state.VisualModuleNotFoundError),
    }[kind]
    path = project_root / path
    with state._locked_file(project_root, path):
        records = state._load_yaml_map(path, top_key)
        if record_id not in records:
            raise not_found(f"Unknown {kind}_id: {record_id}")
        records[record_id].update(dict(updates))
        records[record_id]["updated_at"] = _now()
        state._save_yaml_map(path, top_key, records)
        return records[record_id]


def register_plan(
    project_root: Path, deck_id: str, plan_path: Path, authored_by: str
) -> dict[str, Any]:
    """Validate and atomically register the next immutable Deck Plan version.

    Args:
        project_root: Project root containing presentation state.
        deck_id: Deck identifier.
        plan_path: Source YAML/JSON Deck Plan.
        authored_by: Planner identity.

    Returns:
        The persisted plan-version record.

    Raises:
        PlanGateError: If the source contract cannot be registered.
    """
    with _workflow_lock(project_root):
        document = _action_document(plan_path, PlanGateError, "plan_registerable", deck_id)
        errors = validate_deck_plan(document)
        blockers = [{"reason": error} for error in errors]
        if document.get("deck_id") != deck_id:
            blockers.append({"reason": "deck_id_mismatch"})
        existing = [record for record in load_plans(project_root).values() if record.get("deck_id") == deck_id]
        next_version = max((int(record.get("version", 0)) for record in existing), default=0) + 1
        if document.get("plan_version") != next_version:
            blockers.append({"reason": "plan_version_mismatch", "expected": next_version})
        if not isinstance(authored_by, str) or not authored_by.strip():
            blockers.append({"reason": "authored_by_required"})
        if blockers:
            raise PlanGateError("plan_registerable", deck_id, blockers, f"plan_registerable blocked for deck {deck_id}: " + "; ".join(str(item["reason"]) for item in blockers))
        destination = Path("decks") / deck_id / "plans" / f"plan-v{next_version:04d}.yaml"
        _save_document(project_root / destination, document)
        record = register_plan_record(project_root, deck_id, destination, contract_sha256(document), authored_by.strip())
        if existing:
            _save_deck(
                project_root,
                deck_id,
                {
                    "status": "planning", "approved_plan_version": None,
                    "approved_plan_sha256": None, "approval_id": None,
                    "approved_by": None, "approved_at": None, "approval_mode": None,
                    "draft_preview_id": None, "draft_approval_id": None,
                },
            )
        return record


def record_content_review(
    project_root: Path, deck_id: str, review_path: Path
) -> dict[str, Any]:
    """Persist a typed content review and advance only its owning deck.

    Args:
        project_root: Project root containing presentation state.
        deck_id: Deck identifier.
        review_path: Source Content Review Result contract.

    Returns:
        The persisted review event.

    Raises:
        PlanGateError: If the current plan is absent or invalid.
        ReviewGateError: If the review document is malformed.
    """
    with _workflow_lock(project_root):
        assert_plan_reviewable(project_root, deck_id)
        review = _action_document(review_path, ReviewGateError, "content_review_recordable", deck_id)
        blockers: list[dict[str, Any]] = []
        if review.get("deck_id", review.get("subject_id")) != deck_id:
            blockers.append({"reason": "deck_id_mismatch"})
        if review.get("reviewer_role", "content") not in {"content", "content_reviewer"}:
            blockers.append({"reason": "reviewer_role must be content"})
        if not isinstance(review.get("reviewer_id"), str) or not review["reviewer_id"].strip():
            blockers.append({"reason": "reviewer_id_required"})
        if review.get("status") not in {"passed", "failed", "blocked"}:
            blockers.append({"reason": "invalid_review_status"})
        if blockers:
            raise ReviewGateError("content_review_recordable", deck_id, blockers)
        event = _record_review_event(project_root, "deck", deck_id, review)
        status = "awaiting_approval" if review["status"] == "passed" else "content_review"
        _save_deck(project_root, deck_id, {"status": status})
        return event


def _record_review_event(project_root: Path, subject_type: str, subject_id: str, review: Mapping[str, Any]) -> dict[str, Any]:
    """Append one normalized Review Result event."""
    event = {
        "event": "review_result", "id": _id("rev"), "subject_type": subject_type,
        "subject_id": subject_id, "reviewer_id": review.get("reviewer_id"),
        "reviewer_role": review.get("reviewer_role", "content"),
        "identity_verifiable": True, "status": review.get("status"),
        "findings": review.get("findings", []), "round": review.get("round", 1),
        "ts": review.get("reviewed_at", _now()),
    }
    append_event(project_root, event)
    return event


def approve_deck(project_root: Path, approval_path: Path) -> dict[str, Any]:
    """Atomically approve the exact validated plan version named by approval.

    Args:
        project_root: Project root containing presentation state.
        approval_path: Source Deck Approval contract.

    Returns:
        The updated approved Deck record and approval event.

    Raises:
        ApprovalGateError: If approval evidence is absent or inconsistent.
    """
    with _workflow_lock(project_root):
        approval = _action_document(approval_path, ApprovalGateError, "plan_approvable", "<unknown>")
        checked = assert_plan_approvable(project_root, approval)
        deck_id = approval["deck_id"]
        plan_record = checked["plan_record"]
        plan_document = checked["plan"]
        if isinstance(plan_record, dict) and isinstance(plan_document, dict):
            destination = Path("decks") / deck_id / "plans" / f"plan-v{int(plan_record['version']):04d}.yaml"
            _save_document(project_root / destination, plan_document)
            if plan_record.get("plan_path") != destination.as_posix():
                import presentation_events
                plan_path = project_root / presentation_events.PLANS_RELATIVE_PATH
                with presentation_events._locked_file(project_root, plan_path):
                    records = presentation_events._load_yaml_map(plan_path, "plans")
                    persisted = records.get(plan_record["id"])
                    if persisted is not None:
                        persisted["plan_path"] = destination.as_posix()
                        persisted["path"] = destination.as_posix()
                        presentation_events._save_yaml_map(plan_path, "plans", records)
                    plan_record = persisted or plan_record
        approval_id = _id("approval")
        event = dict(approval)
        event.update({"event": "deck_approval", "id": approval_id, "ts": _now()})
        append_event(project_root, event)
        deck = _save_deck(
            project_root,
            deck_id,
            {
                "status": "approved", "approved_plan_version": approval["plan_version"],
                "approved_plan_sha256": approval["plan_sha256"], "approval_id": approval_id,
                "approved_by": approval["approved_by"], "approved_at": approval["approved_at"],
                "approval_mode": approval["approval_mode"],
            },
        )
        return {"deck": deck, "approval": event, "plan": checked["plan"]}


def record_production_review(project_root: Path, review_path: Path) -> dict[str, Any]:
    """Record an independent scientific or visual-quality production review.

    Args:
        project_root: Project root containing presentation state.
        review_path: Source Review Result contract.

    Returns:
        The persisted review event and updated target record.

    Raises:
        ReviewGateError: If the review target or role is invalid.
    """
    with _workflow_lock(project_root):
        review = _action_document(review_path, ReviewGateError, "production_review_recordable", "<unknown>")
        subject_type = review.get("subject_type")
        subject_id = review.get("subject_id")
        if subject_type not in {"slide", "module"} or not isinstance(subject_id, str):
            raise ReviewGateError("production_review_recordable", str(review.get("deck_id", "<unknown>")), [{"reason": "invalid_subject"}])
        state = _state()
        if subject_type == "slide":
            target = state.load_slides(project_root).get(subject_id)
        else:
            target = state.load_visual_modules(project_root).get(subject_id)
        if target is None:
            raise ReviewGateError("production_review_recordable", str(review.get("deck_id", "<unknown>")), [{"reason": "unknown_subject"}])
        deck_id = str(target.get("deck_id")) if subject_type == "slide" else str(state.load_slides(project_root)[target["slide_id"]].get("deck_id"))
        try:
            assert_production_allowed(project_root, deck_id)
        except ProductionGateError as exc:
            raise ReviewGateError("production_review_recordable", deck_id, exc.blockers) from exc
        if review.get("reviewer_role") not in {"scientific", "visual_quality"}:
            raise ReviewGateError("production_review_recordable", deck_id, [{"reason": "invalid_reviewer_role"}])
        if not isinstance(review.get("reviewer_id"), str) or not review["reviewer_id"].strip():
            raise ReviewGateError("production_review_recordable", deck_id, [{"reason": "reviewer_id_required"}])
        if review.get("status") not in {"passed", "failed", "blocked"}:
            raise ReviewGateError("production_review_recordable", deck_id, [{"reason": "invalid_review_status"}])
        event = _record_review_event(project_root, subject_type, subject_id, review)
        if review["status"] in {"failed", "blocked"}:
            _save_unit(project_root, subject_type, subject_id, {"status": "revision_required"})
        elif subject_type == "slide":
            try:
                assert_slide_passable(project_root, subject_id)
            except ReviewGateError:
                pass
            else:
                _save_unit(project_root, "slide", subject_id, {"status": "passed"})
        else:
            reviews = effective_review_results(load_review_results(project_root, {subject_id}))
            roles = {
                review.get("reviewer_role")
                for review in reviews
                if review.get("status") == "passed"
                and isinstance(review.get("reviewer_id"), str)
                and review.get("reviewer_role") in {"scientific", "visual_quality"}
            }
            if roles == {"scientific", "visual_quality"}:
                _save_unit(project_root, "module", subject_id, {"status": "passed"})
        return {"review": event, "target": _state().load_slides(project_root).get(subject_id) if subject_type == "slide" else _state().load_visual_modules(project_root).get(subject_id)}


def request_targeted_revision(project_root: Path, revision_path: Path) -> dict[str, Any]:
    """Persist a targeted Revision Request without resetting siblings.

    Args:
        project_root: Project root containing presentation state.
        revision_path: Source Revision Request contract.

    Returns:
        The persisted Revision Request and any replacement record.

    Raises:
        ReviewGateError: If the request target or revision kind is invalid.
    """
    with _workflow_lock(project_root):
        revision = _action_document(revision_path, ReviewGateError, "revision_requestable", "<unknown>")
        subject_type = revision.get("subject_type")
        subject_id = revision.get("subject_id")
        deck_id = str(revision.get("deck_id", "<unknown>"))
        if subject_type not in {"deck", "plan", "slide", "module"} or not isinstance(subject_id, str):
            raise ReviewGateError("revision_requestable", deck_id, [{"reason": "invalid_subject"}])
        if revision.get("revision_kind") not in _REVISION_KINDS:
            raise ReviewGateError("revision_requestable", deck_id, [{"reason": "invalid_revision_kind"}])
        state = _state()
        if subject_type in {"deck", "plan"}:
            deck_id = subject_id
        elif subject_type == "slide":
            target = state.load_slides(project_root).get(subject_id)
            if target is None:
                raise ReviewGateError("revision_requestable", deck_id, [{"reason": "unknown_subject"}])
            deck_id = str(target["deck_id"])
        else:
            target = state.load_visual_modules(project_root).get(subject_id)
            if target is None:
                raise ReviewGateError("revision_requestable", deck_id, [{"reason": "unknown_subject"}])
            deck_id = str(state.load_slides(project_root)[target["slide_id"]]["deck_id"])
        try:
            record = create_revision_request(
                project_root, subject_type, subject_id, revision.get("requested_by", "reviewer"),
                revision.get("instructions", "Targeted revision"), supersedes=revision.get(
                    "supersedes", revision.get("superseded_subject_id", subject_id if subject_type in {"slide", "module"} else None)
                ),
            )
        except Exception as exc:  # noqa: BLE001 - map low-level rejection to gate JSON
            raise ReviewGateError(
                "revision_requestable", deck_id,
                [{"reason": "invalid_revision_request", "message": str(exc)}],
            ) from exc
        replacement: dict[str, Any] | None = None
        if subject_type in {"slide", "module"}:
            source = state.load_slides(project_root).get(subject_id) if subject_type == "slide" else state.load_visual_modules(project_root).get(subject_id)
            if source is not None:
                replacement = dict(source)
                replacement["id"] = _id("sld" if subject_type == "slide" else "mod")
                replacement["status"] = "planned"
                replacement["attempt"] = int(source.get("attempt", 1)) + 1
                replacement["supersedes_slide_id" if subject_type == "slide" else "supersedes_module_id"] = subject_id
                if subject_type == "slide":
                    replacement["slide_spec_path"] = None
                    replacement["slide_spec_sha256"] = None
                else:
                    replacement["assignment_path"] = None
                    replacement["artifact_manifest_path"] = None
                replacement.pop("updated_at", None)
                replacement["created_at"] = _now()
                path = state.SLIDES_RELATIVE_PATH if subject_type == "slide" else state.VISUAL_MODULES_RELATIVE_PATH
                top = "slides" if subject_type == "slide" else "visual_modules"
                with state._locked_file(project_root, project_root / path):
                    records = state._load_yaml_map(project_root / path, top)
                    records[replacement["id"]] = replacement
                    state._save_yaml_map(project_root / path, top, records)
        else:
            _save_deck(
                project_root,
                deck_id,
                {
                    "status": "planning", "approved_plan_version": None,
                    "approved_plan_sha256": None, "approval_id": None,
                    "approved_by": None, "approved_at": None, "approval_mode": None,
                    "draft_preview_id": None, "draft_approval_id": None,
                },
            )
        return {"revision": record, "replacement": replacement}


def register_draft_preview(project_root: Path, preview_path: Path) -> dict[str, Any]:
    """Validate and persist a complete-deck Draft Preview record."""
    with _workflow_lock(project_root):
        preview = _action_document(preview_path, DraftGateError, "draft_reviewable", "<unknown>")
        deck_id = preview.get("deck_id")
        if not isinstance(deck_id, str):
            raise DraftGateError("draft_reviewable", "<unknown>", [{"reason": "deck_id_required"}])
        checked = assert_draft_reviewable(project_root, deck_id, preview)
        event = dict(preview)
        event.update({"event": "draft_preview", "id": _id("draft"), "ts": _now()})
        append_event(project_root, event)
        deck = _save_deck(project_root, deck_id, {"draft_preview_id": event["id"]})
        return {"deck": deck, "preview": event, "slides": checked["slides"]}


def approve_draft(project_root: Path, decision_path: Path) -> dict[str, Any]:
    """Persist an explicit Draft Approval and advance to final validation.

    Args:
        project_root: Project root containing presentation state.
        decision_path: Source Draft Decision contract.

    Returns:
        The updated deck, decision event, and reviewed preview.

    Raises:
        DraftGateError: If the current preview or decision is incomplete.
    """
    with _workflow_lock(project_root):
        decision = _action_document(decision_path, DraftGateError, "draft_approvable", "<unknown>")
        deck_id = decision.get("deck_id")
        if not isinstance(deck_id, str):
            raise DraftGateError("draft_approvable", "<unknown>", [{"reason": "deck_id_required"}])
        deck = _deck(project_root, deck_id)
        previews = [event for event in load_events(project_root, "draft_preview") if event.get("deck_id") == deck_id]
        preview_id = decision.get("preview_id", deck.get("draft_preview_id"))
        preview = next((event for event in previews if event.get("id") == preview_id), None)
        if preview is None:
            raise DraftGateError("draft_approvable", deck_id, [{"reason": "missing_draft_preview"}])
        assert_draft_reviewable(project_root, deck_id, preview)
        blockers: list[dict[str, Any]] = []
        if decision.get("decision", "approve") != "approve":
            blockers.append({"reason": "decision must be approve"})
        if not isinstance(decision.get("approved_by"), str) or not decision["approved_by"].strip():
            blockers.append({"reason": "approved_by_required"})
        if blockers:
            raise DraftGateError("draft_approvable", deck_id, blockers)
        event = dict(decision)
        event.update({"event": "draft_decision", "id": _id("draft-approval"), "preview_id": preview_id, "ts": _now()})
        append_event(project_root, event)
        deck = _save_deck(project_root, deck_id, {"draft_approval_id": event["id"], "status": "validating"})
        return {"deck": deck, "decision": event, "preview": preview}


def complete_deck(project_root: Path, deck_id: str, completion_record_path: Path) -> dict[str, Any]:
    """Validate persisted final evidence and atomically mark a deck complete.

    Args:
        project_root: Project root containing presentation state.
        deck_id: Deck identifier.
        completion_record_path: Source final visual-review/completion record.

    Returns:
        The updated completed deck, completion event, and validated evidence.

    Raises:
        CompletionGateError: If any current review or final validation is absent.
    """
    with _workflow_lock(project_root):
        completion = _action_document(completion_record_path, CompletionGateError, "deck_completable", deck_id)
        checked = assert_deck_completable(project_root, deck_id, completion)
        event = dict(completion)
        event.update({"event": "deck_completion", "id": _id("completion"), "deck_id": deck_id, "ts": _now()})
        append_event(project_root, event)
        deck = _save_deck(project_root, deck_id, {"status": "completed"})
        return {"deck": deck, "completion": event, "evidence": checked}
