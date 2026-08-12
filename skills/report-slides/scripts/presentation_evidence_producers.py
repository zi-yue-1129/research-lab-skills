"""Atomic schema-v2 producers for preview, approval, and completion evidence.

This module owns the high-level workflow cutover.  It captures and validates
legacy source documents, then delegates immutable transaction serialization to
``presentation_evidence_workflow``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from presentation_artifact_provenance import mapping_key_blockers
from presentation_contracts import contract_sha256
from presentation_evidence_cas import CasObject, read_verified_source
from presentation_evidence_contracts import (
    EVIDENCE_SCHEMA_VERSION,
    envelope_sha256,
    validate_envelope,
)
from presentation_evidence_projection import (
    HistoricalEvidenceUnavailableError,
    ProjectionError,
    project_historical_evidence,
    project_preview_evidence,
    project_visual_review_evidence,
)
from presentation_evidence_snapshot import build_snapshot
from presentation_events import load_events
from presentation_evidence_gates import assert_draft_approvable
from presentation_gates import assert_deck_completable
from presentation_evidence_workflow import (
    _candidate_snapshot,
    _load_deck_after_commit,
    _mutable,
    _objects_by_provenance,
    _planned_source_objects,
    _stage_evidence_batch,
    _transition_paths,
    require_schema_v2,
    stage_evidence_transition,
)
from presentation_transactions import transaction
from presentation_workflow_values import generate_workflow_id, utc_now
from render_plan_preview import validate_draft_decision_flags, validate_draft_preview


_DRAFT_DECISION_FIELDS = frozenset({
    "schema_version", "deck_id", "preview_id", "preview_sha256", "decision",
    "approval_mode", "approved_by", "identity_verifiable", "yes_draft",
})
_RESERVED_REVIEWER_IDENTITIES = frozenset({
    "auto", "system", "agent", "unknown", "--yes-draft", "workflow",
})


def register_draft_preview_v2(project_root: Path, preview_path: Path) -> dict[str, Any]:
    """Register a preview event and v2 evidence in one durable transition.

    Args:
        project_root: Project root containing schema-v2 presentation state.
        preview_path: Exact draft-preview contract path.

    Returns:
        Legacy-compatible preview result enriched with ``evidence_id``.

    Raises:
        ProjectionError: If the frozen candidate cannot form valid evidence.
    """
    require_schema_v2(project_root, check_recovery=False)
    workflow = _workflow_module()
    with workflow._workflow_lock(project_root):
        source = workflow._action_document(
            preview_path, workflow.DraftGateError, "draft_reviewable", "<unknown>"
        )
        deck_id = source.get("deck_id")
        if not isinstance(deck_id, str) or not deck_id:
            raise workflow.DraftGateError(
                "draft_reviewable", "<unknown>", [{"reason": "deck_id_required"}]
            )
        checked = validate_draft_preview(project_root, deck_id, source)
        preview = dict(checked["preview"])
        event = dict(preview)
        event.update(
            {
                "event": "draft_preview",
                "id": _identifier("draft"),
                "preview_sha256": contract_sha256(preview),
                "ts": _utc_now(),
            }
        )
        cas_objects = _planned_source_objects(project_root, event["artifact_digests"])
        paths = _transition_paths(project_root, cas_objects)
        with transaction(paths, project_root) as transaction_handle:
            require_schema_v2(project_root)
            snapshot = build_snapshot(project_root, locked=True)
            candidate = _candidate_snapshot(
                snapshot,
                events=(event,),
                source_objects=_objects_by_provenance(event["artifact_digests"], cas_objects),
                deck_updates={
                    deck_id: {
                        "draft_preview_id": event["id"],
                        "draft_approval_id": None,
                        "draft_approval_evidence_id": None,
                        "completion_evidence_id": None,
                        "status": "draft_review",
                        "updated_at": _utc_now(),
                    }
                },
            )
            try:
                envelope = dict(project_preview_evidence(candidate, event))
            except (ProjectionError, HistoricalEvidenceUnavailableError) as exc:
                raise workflow.DraftGateError(
                    "draft_reviewable", deck_id, [{"reason": "v2_projection", "message": str(exc)}]
                ) from exc
            stage_evidence_transition(
                transaction_handle,
                candidate,
                event=event,
                envelope=envelope,
                cas_objects=cas_objects,
                pointer_field="draft_preview_evidence_id",
            )
            transaction_handle.commit()
        return {
            "deck": _load_deck_after_commit(project_root, deck_id),
            "preview": event,
            "slides": checked["slides"],
            "evidence_id": envelope["id"],
        }


def approve_draft_v2(
    project_root: Path,
    decision_path: Path,
    *,
    yes_draft: bool = False,
) -> dict[str, Any]:
    """Publish a draft decision and its immutable v2 approval evidence.

    Args:
        project_root: Project root containing schema-v2 presentation state.
        decision_path: Exact draft-decision contract path.
        yes_draft: Explicit non-interactive approval authorization.

    Returns:
        Legacy-compatible decision result enriched with ``evidence_id``.
    """
    require_schema_v2(project_root, check_recovery=False)
    workflow = _workflow_module()
    if type(yes_draft) is not bool:
        validate_draft_decision_flags({"yes_draft": yes_draft}, "<unknown>")
    decision = workflow._action_document(
        decision_path, workflow.DraftGateError, "draft_approvable", "<unknown>"
    )
    key_blockers = mapping_key_blockers(decision, "decision")
    if key_blockers:
        deck_hint = decision.get("deck_id") if isinstance(decision.get("deck_id"), str) else "<unknown>"
        raise workflow.DraftGateError(
            "draft_approvable",
            deck_hint,
            key_blockers,
            f"draft_approvable blocked for deck {deck_hint}: mapping keys must be strings",
        )
    deck_id = decision.get("deck_id")
    if not isinstance(deck_id, str) or not deck_id:
        raise workflow.DraftGateError(
            "draft_approvable", "<unknown>", [{"reason": "deck_id_required"}]
        )
    with workflow._workflow_lock(project_root):
        deck = _state_decks(project_root).get(deck_id)
        if deck is None:
            raise workflow.DraftGateError(
                "draft_approvable", deck_id, [{"reason": "unknown_deck"}]
            )
        if deck.get("draft_approval_evidence_id") is not None:
            raise workflow.DraftGateError(
                "draft_approvable",
                deck_id,
                [{"reason": "current_draft_approval_already_exists"}],
            )
        _validate_draft_decision(workflow, decision, deck_id, yes_draft)
        preview_id = decision.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id:
            raise workflow.DraftGateError(
                "draft_approvable", deck_id, [{"reason": "preview_id_required"}]
            )
        previews = [
            event
            for event in load_events(project_root, "draft_preview")
            if event.get("deck_id") == deck_id
        ]
        preview = next((event for event in previews if event.get("id") == preview_id), None)
        if preview is None:
            raise workflow.DraftGateError(
                "draft_approvable", deck_id, [{"reason": "missing_draft_preview"}]
            )
        checked = validate_draft_preview(project_root, deck_id, preview)
        blockers, approval_mode, approved_by = _draft_approval_blockers(
            workflow, decision, preview, yes_draft
        )
        if blockers:
            summary = "; ".join(str(item.get("reason", item)) for item in blockers)
            raise workflow.DraftGateError(
                "draft_approvable",
                deck_id,
                blockers,
                f"draft_approvable blocked for deck {deck_id}: {summary}",
            )
        # Authorize from the current evidence pointer and its verified CAS
        # bytes before any event is constructed. Without this the producer
        # would happily bind an approval to a preview whose artifacts no
        # longer exist, leaving a deck the completion gate can never accept.
        assert_draft_approvable(project_root, deck_id, decision)
        plan_id = deck.get("current_plan_id")
        plan_version = deck.get("approved_plan_version")
        plan_sha256 = deck.get("approved_plan_sha256")
        if (
            not isinstance(plan_id, str)
            or type(plan_version) is not int
            or not isinstance(plan_sha256, str)
        ):
            raise workflow.DraftGateError(
                "draft_approvable", deck_id, [{"reason": "approved_plan_binding_required"}]
            )
        decision_event = dict(decision)
        decision_event.update(
            {
                "event": "draft_decision",
                "id": _identifier("draft-decision"),
                "preview_id": preview_id,
                "preview_sha256": preview["preview_sha256"],
                "approval_mode": approval_mode,
                "approved_by": approved_by,
                "ts": _utc_now(),
            }
        )
        approval_event = {
            "schema_version": 1,
            "deck_id": deck_id,
            "plan_id": plan_id,
            "plan_version": plan_version,
            "plan_sha256": plan_sha256,
            "decision": "approve",
            "approved_by": approved_by,
            "approved_at": _utc_now(),
            "approval_mode": approval_mode,
            "revisions_requested": [],
            "preview_id": preview_id,
            "event": "deck_approval",
            "id": _identifier("draft-approval"),
            "ts": _utc_now(),
        }
        paths = _transition_paths(project_root, {})
        with transaction(paths, project_root) as transaction_handle:
            require_schema_v2(project_root)
            snapshot = build_snapshot(project_root, locked=True)
            preview_evidence = snapshot.stores.get("evidence", {}).get(
                deck.get("draft_preview_evidence_id")
            )
            if preview_evidence is None:
                raise workflow.DraftGateError(
                    "draft_approvable",
                    deck_id,
                    [{"reason": "current_preview_evidence_required"}],
                )
            envelope = _approval_envelope(approval_event, _mutable(preview_evidence))
            candidate = _candidate_snapshot(
                snapshot,
                events=(decision_event, approval_event),
                deck_updates={
                    deck_id: {
                        "draft_approval_id": decision_event["id"],
                        "completion_evidence_id": None,
                        "status": "validating",
                        "updated_at": _utc_now(),
                    }
                },
            )
            _stage_evidence_batch(
                transaction_handle,
                candidate,
                events=(decision_event, approval_event),
                envelopes=(envelope,),
                cas_objects={},
                pointer_field="draft_approval_evidence_id",
            )
            transaction_handle.commit()
        return {
            "deck": _load_deck_after_commit(project_root, deck_id),
            "decision": decision_event,
            "preview": checked["preview"],
            "evidence_id": envelope["id"],
        }


def complete_deck_v2(
    project_root: Path, deck_id: str, completion_record_path: Path
) -> dict[str, Any]:
    """Publish completion and visual-review v2 evidence atomically.

    Args:
        project_root: Project root containing schema-v2 presentation state.
        deck_id: Deck whose current approved draft is completing.
        completion_record_path: Completion contract naming visual-review data.

    Returns:
        Legacy-compatible completion result enriched with ``evidence_id``.
    """
    require_schema_v2(project_root, check_recovery=False)
    workflow = _workflow_module()
    with workflow._workflow_lock(project_root):
        precheck_snapshot = build_snapshot(project_root)
        completion = workflow._action_document(
            completion_record_path, workflow.CompletionGateError, "deck_completable", deck_id
        )
        checked = assert_deck_completable(project_root, deck_id, completion)
        review_path, review_document, review_bytes, artifact_digests, cas_objects = _completion_sources(
            project_root, completion, checked
        )
        paths = _transition_paths(project_root, cas_objects)
        with transaction(paths, project_root) as transaction_handle:
            require_schema_v2(project_root)
            snapshot = build_snapshot(project_root, locked=True)
            _require_frozen_completion_authorization(
                workflow, deck_id, precheck_snapshot, snapshot
            )
            deck = snapshot.stores.get("decks", {}).get(deck_id)
            if deck is None:
                raise workflow.CompletionGateError(
                    "deck_completable", deck_id, [{"reason": "unknown_deck"}]
                )
            plan_id = deck.get("current_plan_id")
            plan_version = deck.get("approved_plan_version")
            plan_sha256 = deck.get("approved_plan_sha256")
            approval_id = deck.get("draft_approval_evidence_id")
            approval = snapshot.stores.get("evidence", {}).get(approval_id)
            if (
                not isinstance(plan_id, str)
                or type(plan_version) is not int
                or not isinstance(plan_sha256, str)
                or approval is None
            ):
                raise workflow.CompletionGateError(
                    "deck_completable",
                    deck_id,
                    [{"reason": "current_v2_approval_binding_required"}],
                )
            review_event = {
                "schema_version": 1,
                "event": "visual_review",
                "id": _identifier("visual-review"),
                "deck_id": deck_id,
                "plan_id": plan_id,
                "plan_version": plan_version,
                "plan_sha256": plan_sha256,
                "producer_id": "workflow",
                "visual_review_path": review_path,
                "visual_review_sha256": contract_sha256(review_document),
                "ts": _utc_now(),
            }
            review_snapshot = _candidate_snapshot(
                snapshot,
                events=(review_event,),
                file_preimages={project_root / review_path: review_bytes},
            )
            try:
                review_envelope = dict(project_visual_review_evidence(review_snapshot, review_event))
            except (ProjectionError, HistoricalEvidenceUnavailableError) as exc:
                raise workflow.CompletionGateError(
                    "deck_completable",
                    deck_id,
                    [{"reason": "v2_visual_review_projection", "message": str(exc)}],
                ) from exc
            approval_envelope = _mutable(approval)
            completion_event = _completion_event(
                deck_id,
                plan_id,
                plan_version,
                plan_sha256,
                approval_envelope,
                review_envelope,
                artifact_digests,
            )
            candidate = _candidate_snapshot(
                review_snapshot,
                events=(completion_event,),
                source_objects=_objects_by_provenance(artifact_digests, cas_objects),
                evidence_updates={review_envelope["id"]: review_envelope},
                deck_updates={
                    deck_id: {"status": "completed", "updated_at": _utc_now()}
                },
            )
            try:
                history = project_historical_evidence(candidate)
                completion_envelope = _mutable(
                    history.by_source_event_id[completion_event["id"]]
                )
            except (KeyError, ProjectionError, HistoricalEvidenceUnavailableError) as exc:
                raise workflow.CompletionGateError(
                    "deck_completable",
                    deck_id,
                    [{"reason": "v2_completion_projection", "message": str(exc)}],
                ) from exc
            _stage_evidence_batch(
                transaction_handle,
                candidate,
                events=(review_event, completion_event),
                envelopes=(review_envelope, completion_envelope),
                cas_objects=cas_objects,
                pointer_field="completion_evidence_id",
            )
            transaction_handle.commit()
        return {
            "deck": _load_deck_after_commit(project_root, deck_id),
            "completion": completion_event,
            "evidence": checked,
            "evidence_id": completion_envelope["id"],
        }


def _require_frozen_completion_authorization(
    workflow: Any,
    deck_id: str,
    precheck_snapshot: Any,
    locked_snapshot: Any,
) -> None:
    """Prove completion predicates still refer to the retained locked snapshot.

    The complete legacy predicate is evaluated before source capture.  Every
    store, event shard, and snapshot-captured source preimage used by that
    predicate must then be byte-identical after workflow and target locks are
    held.  This is a revalidation without reopening a mutable path after the
    locked snapshot boundary.

    Args:
        workflow: Lazily imported workflow module defining gate exceptions.
        deck_id: Deck whose completion authorization is being revalidated.
        precheck_snapshot: Frozen state captured immediately before precheck.
        locked_snapshot: Frozen state captured after all transaction locks.

    Raises:
        CompletionGateError: If any completion authorization input changed.
    """
    if _completion_snapshot_digest(precheck_snapshot) != _completion_snapshot_digest(
        locked_snapshot
    ):
        raise workflow.CompletionGateError(
            "deck_completable",
            deck_id,
            [{"reason": "completion_authorization_changed_during_locking"}],
        )


def _completion_snapshot_digest(snapshot: Any) -> str:
    """Return an immutable digest of every current completion predicate input.

    Args:
        snapshot: Evidence snapshot captured without a subsequent live read.

    Returns:
        SHA-256 digest of frozen stores, events, and captured source bytes.
    """
    file_preimages = {
        path.relative_to(snapshot.project_root).as_posix(): hashlib.sha256(content).hexdigest()
        for path, content in snapshot.file_preimages.items()
    }
    artifact_objects = {
        path: {
            "sha256": object_.digest,
            "content_sha256": hashlib.sha256(object_.content).hexdigest(),
        }
        for path, object_ in snapshot.artifact_objects.items()
    }
    return contract_sha256(
        {
            "schema_version": snapshot.schema_version,
            "stores": _mutable(snapshot.stores),
            "events": _mutable(snapshot.events),
            "file_preimages": file_preimages,
            "artifact_objects": artifact_objects,
        }
    )


def _completion_sources(
    project_root: Path,
    completion: Mapping[str, Any],
    checked: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any], bytes, dict[str, str], dict[str, CasObject]]:
    """Capture exact review and completion artifact inputs before state locking."""
    raw_review_path = completion.get("visual_review_path", completion.get("review_record_path"))
    review_path = _canonical_project_path(project_root, raw_review_path)
    review_object = read_verified_source(project_root, review_path)
    try:
        document = json.loads(review_object.content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectionError("visual review source is not valid UTF-8 JSON") from exc
    if not isinstance(document, Mapping):
        raise ProjectionError("visual review source must be a mapping")
    checked_document = checked.get("visual_review")
    if not isinstance(checked_document, Mapping) or dict(document) != dict(checked_document):
        raise ProjectionError("visual review changed between gate validation and source capture")
    artifacts = document.get("artifacts")
    statuses = document.get("statuses")
    if not isinstance(artifacts, Mapping) or not isinstance(statuses, Mapping):
        raise ProjectionError("visual review artifacts and statuses must be mappings")
    final_path = artifacts.get("pptx")
    render_status = statuses.get("pptx_render")
    if not isinstance(render_status, Mapping):
        raise ProjectionError("visual review pptx_render status is required")
    rendered_paths = render_status.get("rendered_png_paths")
    if not isinstance(rendered_paths, list):
        raise ProjectionError("visual review rendered_png_paths is required")
    expected_paths = [
        _canonical_project_path(project_root, final_path),
        *[_canonical_project_path(project_root, path) for path in rendered_paths],
    ]
    raw_digests = document.get("artifact_digests")
    if not isinstance(raw_digests, Mapping):
        raise ProjectionError("visual review artifact_digests is required")
    artifact_digests: dict[str, str] = {}
    for path in expected_paths:
        digest = raw_digests.get(path)
        if not isinstance(digest, str):
            raise ProjectionError(f"visual review digest is required for {path!r}")
        artifact_digests[path] = digest
    cas_objects = _planned_source_objects(project_root, artifact_digests)
    return review_path, dict(document), review_object.content, artifact_digests, cas_objects


def _completion_event(
    deck_id: str,
    plan_id: str,
    plan_version: int,
    plan_sha256: str,
    approval: Mapping[str, Any],
    review: Mapping[str, Any],
    artifact_digests: Mapping[str, str],
) -> dict[str, Any]:
    """Build the exact immutable completion source from frozen prerequisites."""
    event: dict[str, Any] = {
        "schema_version": 1,
        "deck_id": deck_id,
        "plan_id": plan_id,
        "plan_version": plan_version,
        "plan_sha256": plan_sha256,
        "producer_id": "workflow",
        "approval_evidence_id": approval["id"],
        "approval_evidence_sha256": approval["evidence_sha256"],
        "visual_review_evidence_id": review["id"],
        "visual_review_evidence_sha256": review["evidence_sha256"],
        "artifact_digests": dict(artifact_digests),
        "event": "deck_completion",
        "id": _identifier("completion"),
        "ts": _utc_now(),
    }
    payload = {
        key: event[key]
        for key in (
            "schema_version",
            "deck_id",
            "plan_id",
            "plan_version",
            "plan_sha256",
            "producer_id",
            "approval_evidence_id",
            "approval_evidence_sha256",
            "visual_review_evidence_id",
            "visual_review_evidence_sha256",
            "artifact_digests",
        )
    }
    event["completion_sha256"] = contract_sha256(payload)
    return event


def _canonical_project_path(project_root: Path, value: object) -> str:
    """Return one canonical project-relative path without trusting symlinks."""
    if not isinstance(value, str) or not value:
        raise ProjectionError("project artifact path must be a nonempty string")
    raw_path = Path(value)
    if raw_path.is_absolute():
        try:
            value = raw_path.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError as exc:
            raise ProjectionError("artifact path must remain within the project root") from exc
    from presentation_events import canonical_relative_path

    try:
        return canonical_relative_path(str(value))
    except ValueError as exc:
        raise ProjectionError("artifact path must be canonical and project-relative") from exc


def _validate_draft_decision(
    workflow: Any,
    decision: Mapping[str, Any],
    deck_id: str,
    yes_draft: bool,
) -> None:
    """Reject schema or field-shape errors before any evidence transaction."""
    if type(decision.get("schema_version")) is not int or decision.get("schema_version") != 1:
        raise workflow.DraftGateError(
            "draft_approvable",
            deck_id,
            [{"reason": "schema_version_required"}],
            f"draft_approvable blocked for deck {deck_id}: schema_version_required",
        )
    unexpected = sorted(set(decision) - _DRAFT_DECISION_FIELDS)
    if unexpected:
        raise workflow.DraftGateError(
            "draft_approvable",
            deck_id,
            [{"reason": "unexpected_decision_field", "field": field} for field in unexpected],
            "draft_approvable blocked for deck "
            f"{deck_id}: unexpected_decision_field ({', '.join(unexpected)})",
        )
    validate_draft_decision_flags(dict(decision), deck_id)
    if type(yes_draft) is not bool:
        raise workflow.DraftGateError(
            "draft_approvable", deck_id, [{"reason": "yes_draft_must_be_bool"}]
        )


def _draft_approval_blockers(
    workflow: Any,
    decision: Mapping[str, Any],
    preview: Mapping[str, Any],
    yes_draft: bool,
) -> tuple[list[dict[str, Any]], str, str]:
    """Validate decision shape, digest binding, and explicit approver identity.

    Pointer currency is deliberately not checked here: ``assert_draft_approvable``
    authorizes it against ``draft_preview_evidence_id``, so comparing the legacy
    ``draft_preview_id`` would be a redundant second authorization path.

    Args:
        workflow: Lazily imported workflow module, retained for call symmetry.
        decision: Parsed Draft Decision contract mapping.
        preview: Immutable preview source event selected by the current pointer.
        yes_draft: Explicit non-interactive approval authorization.

    Returns:
        Structured blockers, the resolved approval mode, and the approver.
    """
    blockers: list[dict[str, Any]] = []
    if decision.get("preview_sha256") != preview.get("preview_sha256"):
        blockers.append({"reason": "preview_digest_mismatch"})
    if decision.get("decision") != "approve":
        blockers.append({"reason": "decision must be approve"})
    declared_mode = decision.get("approval_mode", "interactive")
    if declared_mode not in {"interactive", "explicit_noninteractive"}:
        blockers.append({"reason": "invalid approval_mode"})
    mode = "explicit_noninteractive" if yes_draft else declared_mode
    approved_by = decision.get("approved_by")
    if mode == "interactive":
        if not isinstance(approved_by, str) or not approved_by.strip():
            blockers.append({"reason": "approved_by_required"})
            approved_by = ""
        else:
            approved_by = approved_by.strip()
            if approved_by.casefold() in _RESERVED_REVIEWER_IDENTITIES:
                blockers.append({"reason": "approved_by must identify a real reviewer"})
    elif not yes_draft:
        blockers.append({"reason": "explicit --yes-draft is required"})
    if not isinstance(approved_by, str) or not approved_by:
        approved_by = "auto (--yes-draft)" if yes_draft else ""
    return blockers, str(mode), approved_by


def _approval_envelope(
    event: Mapping[str, Any], preview: Mapping[str, Any]
) -> dict[str, Any]:
    """Build one exact draft-approval envelope from its source event."""
    required_preview = validate_envelope(preview)
    envelope: dict[str, Any] = {
        "id": event["id"],
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_kind": "draft_approval",
        "deck_id": event["deck_id"],
        "plan_id": event["plan_id"],
        "plan_version": event["plan_version"],
        "plan_sha256": event["plan_sha256"],
        "subject_ids": [event["deck_id"]],
        "producer_id": event["approved_by"],
        "artifact_refs": [],
        "source_event_id": event["id"],
        "created_at": event["ts"],
        "availability": "available",
        "preview_evidence_id": required_preview["id"],
        "preview_evidence_sha256": required_preview["evidence_sha256"],
        "decision": "approved",
        "approval_mode": event["approval_mode"],
        "approved_by": event["approved_by"],
    }
    envelope["evidence_sha256"] = envelope_sha256(envelope)
    return validate_envelope(envelope)


def _state_decks(project_root: Path) -> dict[str, Any]:
    """Load a copied deck map through the current state-store public API."""
    from presentation_state import load_decks

    return {deck_id: _mutable(record) for deck_id, record in load_decks(project_root).items()}


def _workflow_module() -> Any:
    """Import legacy workflow utilities only during a producer invocation."""
    import presentation_workflow

    return presentation_workflow


def _identifier(prefix: str) -> str:
    """Return one collision-resistant immutable workflow event identifier."""
    return generate_workflow_id(prefix, random_length=8)


def _utc_now() -> str:
    """Return an RFC3339 UTC timestamp accepted by the evidence contract."""
    return utc_now()
