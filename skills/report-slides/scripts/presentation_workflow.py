#!/usr/bin/env python3
"""Atomic high-level actions for the report-slides workflow.

Each public action acquires one workflow-level lock before reading evidence,
appending immutable events, and mutating state.  Low-level state helpers stay
available for backwards-compatible diagnostics, but gated transitions enter
the persisted workflow only through this module.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from presentation_contracts import contract_sha256, load_contract
from presentation_evidence_workflow import MigrationRequiredError, require_schema_v2
from presentation_workflow_lock import workflow_lock as _workflow_lock
from presentation_events import (
    append_event,
    effective_review_results,
    events_shard_path,
    load_review_results,
    load_plans,
)
from presentation_transactions import transaction
from presentation_plan_transactions import register_plan_transaction
from presentation_gates import (
    ApprovalGateError,
    CompletionGateError,
    DraftGateError,
    GateError,
    PlanGateError,
    ProductionGateError,
    ReviewGateError,
    assert_plan_approvable,
    assert_plan_reviewable,
    assert_production_allowed,
    module_reviews_complete,
    review_result_blockers,
    slide_reviews_complete,
)
from validate_deck_plan import validate_deck_plan


_REVISION_KINDS = frozenset(
    {
        "revise_slide", "add_slide", "remove_slide", "reorder_slides",
        "change_emphasis", "change_audience", "change_duration",
        "review_finding", "module_retry", "slide_retry",
    }
)
_USER_PLAN_REVISION_KINDS = frozenset({
    "revise_slide", "add_slide", "remove_slide", "reorder_slides",
    "change_emphasis", "change_audience", "change_duration",
})
def translate_cli_gate_error(args: Any, error: BaseException) -> BaseException:
    """Translate gated CLI not-found/parse errors into named gate errors.

    Args:
        args: Parsed presentation-state CLI arguments.
        error: Original low-level exception.

    Returns:
        The original error when it is already structured, otherwise a named
        gate error for a gated action.
    """
    if isinstance(error, (GateError, MigrationRequiredError)):
        return error
    names = (
        "check_production_allowed", "register_plan", "record_content_review", "approve_deck",
        "record_production_review", "request_targeted_revision", "register_draft_preview",
        "approve_draft", "complete_deck",
    )
    selected = next((name for name in names if getattr(args, name, False)), None)
    if selected is None:
        return error
    labels = {
        "check_production_allowed": (ProductionGateError, "production_allowed"),
        "register_plan": (PlanGateError, "plan_registerable"),
        "record_content_review": (ReviewGateError, "content_review_recordable"),
        "approve_deck": (ApprovalGateError, "plan_approvable"),
        "record_production_review": (ReviewGateError, "production_review_recordable"),
        "request_targeted_revision": (ReviewGateError, "revision_requestable"),
        "register_draft_preview": (DraftGateError, "draft_reviewable"),
        "approve_draft": (DraftGateError, "draft_approvable"),
        "complete_deck": (CompletionGateError, "deck_completable"),
    }
    error_type, predicate = labels[selected]
    return error_type(predicate, getattr(args, "deck_id", None) or "<unknown>", [{"reason": type(error).__name__, "message": str(error)}])


def _state() -> Any:
    """Import presentation_state lazily to avoid its workflow import cycle."""
    import presentation_state

    return presentation_state


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
    require_schema_v2(project_root, check_recovery=False)
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
        return register_plan_transaction(
            project_root,
            deck_id,
            document,
            authored_by.strip(),
            destination,
            next_version,
        )


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
    require_schema_v2(project_root, check_recovery=False)
    with _workflow_lock(project_root):
        checked_plan = assert_plan_reviewable(project_root, deck_id)
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
        plan_record = checked_plan["plan_record"]
        plan_document = checked_plan["plan"]
        event = _record_review_event(
            project_root,
            "deck",
            deck_id,
            review,
            {
                "current_plan_id": plan_record["id"],
                "current_plan_version": plan_record["version"],
                "current_plan_sha256": contract_sha256(plan_document),
            },
        )
        status = "awaiting_approval" if review["status"] == "passed" else "content_review"
        _save_deck(project_root, deck_id, {"status": status})
        return event


def _update_revision_request(
    project_root: Path, request_id: str, updates: Mapping[str, Any]
) -> dict[str, Any]:
    """Normalize request updates without reacquiring a transaction lock.

    The legacy private hook remains available for deterministic failure
    injection; callers own the in-memory request map and stage it atomically.
    """
    del project_root, request_id
    return dict(updates)


def _record_review_event(
    project_root: Path,
    subject_type: str,
    subject_id: str,
    review: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one normalized Review Result event."""
    event = {
        "event": "review_result", "id": _id("rev"), "subject_type": subject_type,
        "subject_id": subject_id, "reviewer_id": review.get("reviewer_id"),
        "reviewer_role": review.get("reviewer_role", "content"),
        "identity_verifiable": review.get("identity_verifiable", True), "status": review.get("status"),
        "findings": review.get("findings", []), "round": review.get("round", 1),
        "ts": review.get("reviewed_at", _now()),
    }
    if extra:
        event.update(dict(extra))
    append_event(project_root, event)
    return event


def _transaction_paths(project_root: Path, action: Mapping[str, Any], review: bool) -> list[Path]:
    """Select only stores an action can mutate before acquiring sidecar locks."""
    state = _state()
    state_dir = project_root / ".research/presentations/state"
    paths: list[Path] = []
    subject_type = action.get("subject_type")
    if review:
        paths.extend((state_dir / "decks.yaml", state_dir / "plans.yaml", state_dir / "assignments.yaml", state_dir / "artifacts.yaml"))
        if subject_type == "slide":
            paths.append(project_root / state.SLIDES_RELATIVE_PATH)
        elif subject_type == "module":
            paths.extend((project_root / state.VISUAL_MODULES_RELATIVE_PATH, project_root / state.SLIDES_RELATIVE_PATH))
        paths.append(project_root / events_shard_path(project_root).relative_to(project_root))
        if action.get("status") in {"failed", "blocked"}:
            paths.append(state_dir / "revision_requests.yaml")
    elif subject_type == "deck" or subject_type == "plan":
        paths.extend((state_dir / "decks.yaml", state_dir / "plans.yaml", state_dir / "revision_requests.yaml"))
    elif subject_type == "slide":
        paths.extend((state_dir / "decks.yaml", project_root / state.SLIDES_RELATIVE_PATH, state_dir / "revision_requests.yaml"))
    elif subject_type == "module":
        paths.extend((
            state_dir / "decks.yaml",
            project_root / state.VISUAL_MODULES_RELATIVE_PATH,
            project_root / state.SLIDES_RELATIVE_PATH,
            state_dir / "assignments.yaml",
            state_dir / "revision_requests.yaml",
        ))
    return sorted(set(paths), key=lambda path: str(path))


def _revision_record(
    project_root: Path, records: dict[str, Any], subject_type: str, subject_id: str,
    requested_by: str, instructions: str, supersedes: str | None = None,
) -> dict[str, Any]:
    """Create one validated revision record in an in-memory request map."""
    if subject_type not in {"deck", "plan", "slide", "module"}:
        raise ValueError(f"invalid revision subject_type: {subject_type}")
    if requested_by not in {"user", "reviewer"}:
        raise ValueError(f"invalid revision requester: {requested_by}")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError("instructions is required")
    record = {
        "id": _id("rvq"), "subject_type": subject_type, "subject_id": subject_id,
        "requested_by": requested_by, "instructions": instructions,
        "supersedes": supersedes, "created_at": _now(),
    }
    records[record["id"]] = record
    return record


def _review_event(
    review: Mapping[str, Any], subject_type: str, subject_id: str,
    revision_request_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a production review event without performing I/O."""
    event: dict[str, Any] = {
        "event": "review_result", "id": _id("rev"), "subject_type": subject_type,
        "subject_id": subject_id, "reviewer_id": review.get("reviewer_id"),
        "reviewer_role": review.get("reviewer_role", "content"),
        "identity_verifiable": review.get("identity_verifiable", True),
        "status": review.get("status"), "findings": review.get("findings", []),
        "round": review.get("round", 1), "ts": review.get("reviewed_at", _now()),
    }
    if revision_request_id is not None:
        event["revision_request_id"] = revision_request_id
    return event


def _stage_gitignore(transaction_handle: Any, path: Path) -> None:
    """Stage the presentation ignore file only when this action creates it."""
    del transaction_handle, path


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
    require_schema_v2(project_root, check_recovery=False)
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
    require_schema_v2(project_root, check_recovery=False)
    try:
        hint = _document(review_path)
    except Exception:
        hint = {}
    paths = _transaction_paths(project_root, hint, review=True)
    with _workflow_lock(project_root), transaction(paths, project_root) as tx:
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
        blockers = review_result_blockers(project_root, subject_type, subject_id, review)
        for persisted in load_review_results(project_root, {subject_id}):
            blockers.extend(review_result_blockers(
                project_root, subject_type, subject_id, persisted, str(persisted.get("id"))
            ))
        if target.get("status") != "review_required":
            blockers.append({"reason": f"status:{target.get('status')}:review_required_expected"})
        if blockers:
            reasons = "; ".join(str(item.get("reason", item)) for item in blockers)
            raise ReviewGateError("production_review_recordable", deck_id, blockers, f"production_review_recordable blocked for deck {deck_id}: {reasons}")
        state_path = project_root / (state.SLIDES_RELATIVE_PATH if subject_type == "slide" else state.VISUAL_MODULES_RELATIVE_PATH)
        top_key = "slides" if subject_type == "slide" else "visual_modules"
        target_records = tx.read_yaml(state_path, top_key)
        request_path = project_root / ".research/presentations/state/revision_requests.yaml"
        event_path = project_root / events_shard_path(project_root).relative_to(project_root)
        revision_request: dict[str, Any] | None = None
        if review["status"] in {"failed", "blocked"}:
            request_records = tx.read_yaml(request_path, "revision_requests")
            try:
                revision_request = _revision_record(
                    project_root, request_records, subject_type, subject_id, "reviewer",
                    str(review.get("instructions") or "Address production review findings"),
                )
            except Exception as exc:  # noqa: BLE001 - expose typed gate evidence
                raise ReviewGateError(
                    "production_review_recordable", deck_id,
                    [{"reason": "revision_request_creation_failed", "message": str(exc)}],
                ) from exc
        event = _review_event(review, subject_type, subject_id, revision_request["id"] if revision_request else None)
        if revision_request is not None:
            revision_updates = {
                "revision_kind": "review_finding", "target_type": subject_type,
                "target_id": subject_id, "review_id": event["id"],
            }
            revision_request.update(_update_revision_request(project_root, revision_request["id"], revision_updates))
            tx.stage_yaml(request_path, "revision_requests", request_records)
        tx.stage_append(event_path, json.dumps(event, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        if review["status"] in {"failed", "blocked"}:
            target_records[subject_id].update({"status": "revision_required", "updated_at": _now()})
            tx.stage_yaml(state_path, top_key, target_records)
        elif subject_type == "slide":
            raw_reviews = load_review_results(project_root, {subject_id}) + [event]
            roles = {item.get("reviewer_role") for item in effective_review_results(raw_reviews) if item.get("status") == "passed"}
            if slide_reviews_complete({str(role) for role in roles}):
                target_records[subject_id].update({"status": "passed", "updated_at": _now()})
                tx.stage_yaml(state_path, top_key, target_records)
        else:
            # A module is a fragment, not a composition, and Task 10 gives the
            # slide an art-direction gate that no module will ever be given.
            # Two named predicates state that difference once; one shared
            # predicate would hide it until it became a permanent stall.
            raw_reviews = load_review_results(project_root, {subject_id}) + [event]
            roles = {item.get("reviewer_role") for item in effective_review_results(raw_reviews) if item.get("status") == "passed"}
            if module_reviews_complete({str(role) for role in roles}):
                target_records[subject_id].update({"status": "passed", "updated_at": _now()})
                tx.stage_yaml(state_path, top_key, target_records)
        _stage_gitignore(tx, project_root / ".research/presentations/.gitignore")
        tx.commit()
        return {
            "review": event,
            "revision_request": revision_request,
            "target": _state().load_slides(project_root).get(subject_id) if subject_type == "slide" else _state().load_visual_modules(project_root).get(subject_id),
        }


def _redirect_dependency_ids(dependencies: list[Any], source_id: str, replacement_id: str) -> list[str]:
    """Replace one dependency while preserving order and removing duplicates."""
    redirected: list[str] = []
    for dependency in dependencies:
        value = replacement_id if dependency == source_id else dependency
        if value not in redirected:
            redirected.append(value)
    return redirected


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
    require_schema_v2(project_root, check_recovery=False)
    try:
        hint = _document(revision_path)
    except Exception:
        hint = {}
    paths = _transaction_paths(project_root, hint, review=False)
    with _workflow_lock(project_root), transaction(paths, project_root) as tx:
        revision = _action_document(revision_path, ReviewGateError, "revision_requestable", "<unknown>")
        subject_type = revision.get("subject_type")
        subject_id = revision.get("subject_id")
        deck_id = str(revision.get("deck_id", "<unknown>"))
        if subject_type not in {"deck", "plan", "slide", "module"} or not isinstance(subject_id, str):
            raise ReviewGateError("revision_requestable", deck_id, [{"reason": "invalid_subject"}])
        revision_kind = revision.get("revision_kind")
        if revision_kind not in _REVISION_KINDS:
            raise ReviewGateError("revision_requestable", deck_id, [{"reason": "invalid_revision_kind"}])
        requested_by = revision.get("requested_by", "reviewer")
        if revision_kind in _USER_PLAN_REVISION_KINDS and subject_type not in {"deck", "plan"}:
            raise ReviewGateError(
                "revision_requestable", deck_id, [{"reason": "plan_revision_requires_deck_or_plan_subject"}],
                "revision_requestable blocked: plan_revision requires deck or plan subject",
            )
        if subject_type in {"deck", "plan"} and requested_by == "user" and revision_kind not in _USER_PLAN_REVISION_KINDS:
            raise ReviewGateError("revision_requestable", deck_id, [{"reason": "invalid_user_plan_revision_kind"}])
        state = _state()
        state_dir = project_root / ".research/presentations/state"
        decks_path = state_dir / "decks.yaml"
        slides_path = project_root / state.SLIDES_RELATIVE_PATH
        modules_path = project_root / state.VISUAL_MODULES_RELATIVE_PATH
        assignments_path = state_dir / "assignments.yaml"
        request_path = state_dir / "revision_requests.yaml"
        decks = tx.read_yaml(decks_path, "decks")
        slides = tx.read_yaml(slides_path, "slides") if subject_type in {"slide", "module"} else {}
        modules = tx.read_yaml(modules_path, "visual_modules") if subject_type == "module" else {}
        assignments = tx.read_yaml(assignments_path, "assignments") if subject_type == "module" else {}
        source: dict[str, Any] | None = None
        if subject_type == "deck":
            deck_id = subject_id
            if deck_id not in decks:
                raise ReviewGateError("revision_requestable", deck_id, [{"reason": "unknown_subject"}])
        elif subject_type == "plan":
            plan_record = tx.read_yaml(state_dir / "plans.yaml", "plans").get(subject_id)
            if plan_record is None:
                raise ReviewGateError("revision_requestable", deck_id, [{"reason": "unknown_subject"}])
            deck_id = str(plan_record.get("deck_id"))
        elif subject_type == "slide":
            source = slides.get(subject_id)
            if source is None:
                raise ReviewGateError("revision_requestable", deck_id, [{"reason": "unknown_subject"}])
            deck_id = str(source["deck_id"])
        else:
            source = modules.get(subject_id)
            if source is None:
                raise ReviewGateError("revision_requestable", deck_id, [{"reason": "unknown_subject"}])
            deck_id = str(slides[source["slide_id"]]["deck_id"])
        blockers: list[dict[str, Any]] = []
        plan_binding: dict[str, Any] = {}
        if subject_type in {"deck", "plan"}:
            if revision.get("deck_id") not in {None, deck_id}:
                blockers.append({"reason": "deck_id_mismatch"})
            try:
                checked_plan = assert_plan_reviewable(project_root, deck_id)
            except PlanGateError as exc:
                blockers.extend(exc.blockers)
                checked_plan = None
            if checked_plan is None:
                blockers.append({"reason": "missing_or_invalid_current_plan"})
            else:
                plan_record = checked_plan["plan_record"]
                current_plan_id = plan_record["id"]
                current_plan = checked_plan["plan"]
                if subject_type == "plan" and subject_id != current_plan_id:
                    blockers.append({"reason": "current_plan_id_required", "expected": current_plan_id, "actual": subject_id})
                if subject_type == "plan" and revision.get("target_id") != current_plan_id:
                    blockers.append({"reason": "target_id_required", "expected": current_plan_id, "actual": revision.get("target_id")})
                elif revision.get("target_id") not in {None, current_plan_id}:
                    blockers.append({"reason": "target_id_mismatch", "expected": current_plan_id, "actual": revision.get("target_id")})
                plan_binding = {
                    "plan_scoped": True,
                    "scope_subject_type": "plan",
                    "scope_subject_id": current_plan_id,
                    "plan_id": current_plan_id,
                    "plan_version": plan_record["version"],
                    "plan_sha256": contract_sha256(current_plan),
                    "current_plan_id": current_plan_id,
                    "current_plan_version": plan_record["version"],
                    "current_plan_sha256": contract_sha256(current_plan),
                    "next_action": "register_plan",
                }
        if source is not None:
            supersedes = revision.get("supersedes", revision.get("superseded_subject_id", subject_id))
            if supersedes != subject_id:
                blockers.append({"reason": "supersedes_target_mismatch", "expected": subject_id, "actual": supersedes})
            source_attempt = source.get("attempt")
            if subject_type in {"slide", "module"} and (type(source_attempt) is not int or source_attempt <= 0):
                blockers.append({"reason": "current slide attempt required"})
            if source.get("status") not in {"review_required", "revision_required", "passed"}:
                blockers.append({"reason": f"status:{source.get('status')}:not_revisionable"})
            if revision_kind == "slide_retry" and subject_type != "slide":
                blockers.append({"reason": "slide_retry_requires_slide_subject"})
            if revision_kind == "module_retry" and subject_type != "module":
                blockers.append({"reason": "module_retry_requires_module_subject"})
            if subject_type == "module" and slides.get(source.get("slide_id"), {}).get("status") == "superseded":
                blockers.append({"reason": "historical_slide_not_revisionable"})
        if blockers:
            summary = "; ".join(str(item.get("reason", item)) for item in blockers)
            raise ReviewGateError(
                "revision_requestable", deck_id, blockers,
                f"revision_requestable blocked for deck {deck_id}: {summary}",
            )
        request_subject_type = "deck" if subject_type == "plan" else subject_type
        request_subject_id = deck_id if subject_type == "plan" else subject_id
        request_records = tx.read_yaml(request_path, "revision_requests")
        try:
            record = _revision_record(
                project_root, request_records, request_subject_type, request_subject_id,
                requested_by, revision.get("instructions", "Targeted revision"), supersedes=None,
            )
        except Exception as exc:  # noqa: BLE001 - map low-level rejection to gate JSON
            raise ReviewGateError(
                "revision_requestable", deck_id,
                [{"reason": "invalid_revision_request", "message": str(exc)}],
            ) from exc
        record.update({
            "revision_kind": revision_kind, "target_type": subject_type,
            "target_id": subject_id, "requested_subject_type": subject_type,
            "requested_subject_id": subject_id, **plan_binding,
        })
        replacement: dict[str, Any] | None = None
        if subject_type in {"slide", "module"} and source is not None:
            replacement = dict(source)
            replacement["id"] = _id("sld" if subject_type == "slide" else "mod")
            replacement["status"] = "planned"
            if subject_type in {"slide", "module"}:
                replacement["attempt"] = source["attempt"] + 1
            replacement["supersedes_slide_id" if subject_type == "slide" else "supersedes_module_id"] = subject_id
            replacement["revision_request_id"] = record["id"]
            replacement["revision_kind"] = revision_kind
            if subject_type == "slide":
                replacement["slide_spec_path"] = None
                replacement["slide_spec_sha256"] = None
            else:
                replacement["assignment_path"] = None
                replacement["artifact_manifest_path"] = None
            replacement.pop("updated_at", None)
            replacement["created_at"] = _now()
            record["supersedes"] = subject_id
            if subject_type == "slide":
                slides[subject_id].update({"status": "superseded", "updated_at": _now()})
                slides[replacement["id"]] = replacement
                tx.stage_yaml(slides_path, "slides", slides)
            else:
                modules[subject_id].update({"status": "superseded", "updated_at": _now()})
                for dependent_id, dependent in modules.items():
                    if dependent_id == subject_id or dependent.get("status") == "superseded":
                        continue
                    dependent_slide = slides.get(dependent.get("slide_id"), {})
                    if not dependent_slide or dependent_slide.get("status") == "superseded":
                        continue
                    dependencies = list(dependent.get("dependencies", dependent.get("dependency_ids", [])) or [])
                    if subject_id not in dependencies:
                        continue
                    redirected = _redirect_dependency_ids(dependencies, subject_id, replacement["id"])
                    if "dependencies" in dependent or "dependency_ids" not in dependent:
                        dependent["dependencies"] = list(redirected)
                    if "dependency_ids" in dependent:
                        dependent["dependency_ids"] = list(redirected)
                    dependent["updated_at"] = _now()
                    for assignment in assignments.values():
                        if (
                            assignment.get("module_id") == dependent_id
                            and assignment.get("assignment_path", assignment.get("path")) == dependent.get("assignment_path")
                            and assignment.get("status") not in {"stale", "superseded", "revoked"}
                            and assignment.get("superseded") is not True
                        ):
                            if "dependencies" in assignment:
                                assignment["dependencies"] = list(redirected)
                            if "dependency_ids" in assignment:
                                assignment["dependency_ids"] = list(redirected)
                modules[replacement["id"]] = replacement
                tx.stage_yaml(modules_path, "visual_modules", modules)
                original_assignments = tx.read_yaml(assignments_path, "assignments")
                if assignments != original_assignments:
                    tx.stage_yaml(assignments_path, "assignments", assignments)
            deck = decks.get(deck_id)
            if not isinstance(deck, dict):
                raise ReviewGateError("revision_requestable", deck_id, [{"reason": "unknown_subject"}])
            deck.update({
                "status": "producing",
                "draft_preview_id": None,
                "draft_approval_id": None,
                "draft_preview_evidence_id": None,
                "draft_approval_evidence_id": None,
                "completion_evidence_id": None,
                "updated_at": _now(),
            })
            tx.stage_yaml(decks_path, "decks", decks)
        else:
            decks[deck_id].update({
                "status": "planning", "approved_plan_version": None,
                "approved_plan_sha256": None, "approval_id": None,
                "approved_by": None, "approved_at": None, "approval_mode": None,
                "draft_preview_id": None, "draft_approval_id": None,
                "draft_preview_evidence_id": None,
                "draft_approval_evidence_id": None,
                "completion_evidence_id": None,
                "plan_revision_required": True,
                "required_plan_id": plan_binding.get("plan_id"),
                "required_plan_revision_id": record["id"], "updated_at": _now(),
            })
            tx.stage_yaml(decks_path, "decks", decks)
        tx.stage_yaml(request_path, "revision_requests", request_records)
        _stage_gitignore(tx, project_root / ".research/presentations/.gitignore")
        tx.commit()
        result: dict[str, Any] = {"revision": record, "replacement": replacement, "revision_kind": revision_kind, **plan_binding}
        if replacement is not None:
            result.update(replacement)
        return result


def register_draft_preview(project_root: Path, preview_path: Path) -> dict[str, Any]:
    """Validate and atomically persist a complete-deck Draft Preview record.

    Args:
        project_root: Project root containing presentation state.
        preview_path: Draft Preview YAML/JSON contract path.

    Returns:
        The updated deck, immutable preview event, and current slides.

    Raises:
        DraftGateError: If any current rendered-slide or contact-sheet
            evidence is missing, stale, extra, or tampered.
    """
    require_schema_v2(project_root, check_recovery=False)
    from presentation_evidence_producers import register_draft_preview_v2

    return register_draft_preview_v2(project_root, preview_path)


def approve_draft(
    project_root: Path,
    decision_path: Path,
    *,
    yes_draft: bool = False,
) -> dict[str, Any]:
    """Persist an explicit Draft Approval and advance to final validation.

    Args:
        project_root: Project root containing presentation state.
        decision_path: Source Draft Decision contract.
        yes_draft: Explicit caller authorization for non-interactive approval.

    Returns:
        The updated deck, decision event, and reviewed preview.

    Raises:
        DraftGateError: If the current preview or decision is incomplete.
    """
    require_schema_v2(project_root, check_recovery=False)
    from presentation_evidence_producers import approve_draft_v2

    return approve_draft_v2(project_root, decision_path, yes_draft=yes_draft)


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
    require_schema_v2(project_root, check_recovery=False)
    from presentation_evidence_producers import complete_deck_v2

    return complete_deck_v2(project_root, deck_id, completion_record_path)
