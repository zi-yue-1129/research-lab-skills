#!/usr/bin/env python3
"""Deterministic evidence predicates for the report-slides workflow.

The state store deliberately keeps these checks read-only.  Workflow actions
hold the workflow lock, call a predicate, and then perform the corresponding
atomic state transition.  A predicate never infers missing evidence.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import AbstractSet, Any, Mapping, NoReturn

from lint_evidence import (
    current_lint_evidence,
    current_svg_digest,
    latest_lint_tokens_digest,
    lint_blockers,
    unanswered_warnings,
)
from presentation_contracts import contract_sha256, load_contract
from presentation_events import (
    effective_review_results,
    load_artifacts,
    load_events,
    load_plans,
    load_review_results,
)
from presentation_evidence_gates import (
    final_visual_review_blockers,
    resolve_current_evidence,
)
from presentation_module_lineage import resolve_module_production_lineage
from validate_deck_plan import validate_deck_approval, validate_deck_plan
from validate_visual_module import (
    validate_complex_visual_spec,
    validate_style_tokens_resolvable,
    validate_worker_assignment,
)

_APPROVED_STATUSES = frozenset(
    {"approved", "producing", "draft_review", "revising", "validating", "completed"}
)
# Which role strings a reviewer may record itself under. This is the admissible
# set, NOT the required set: `visual_quality` is retained because it is
# persisted in existing review-result events, `render_integrity` is its current
# name, and a subject needs only one accepted *pair*. Requiring every member
# here would block every deck recorded before the split on a review nobody will
# run again. The required sets are `SLIDE_REVIEW_ROLE_SETS` and
# `MODULE_REVIEW_ROLE_SETS` below. See the Phase 4 note in
# docs/superpowers/plans/2026-09-04-report-slides-visual-review.md.
_REVIEW_ROLES = frozenset(
    {"scientific", "visual_quality", "render_integrity", "art_direction"})
# `visual_quality` remains in `_REVIEW_ROLES` so persisted pre-split events stay
# admissible on replay. It must not be writable: a new deck that could still
# submit the legacy role pair would bypass both `render_integrity` and
# `art_direction`, which is the whole of this plan.
_RETIRED_REVIEW_ROLES = frozenset({"visual_quality"})
_CONTENT_ROLES = frozenset({"content", "content_reviewer"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
class GateError(RuntimeError):
    """Base error carrying machine-readable predicate failure evidence."""

    predicate: str
    deck_id: str
    blockers: list[dict[str, Any]]

    def __init__(
        self,
        predicate: str,
        deck_id: str,
        blockers: list[dict[str, Any]],
        message: str | None = None,
    ) -> None:
        self.predicate = predicate
        self.deck_id = deck_id
        self.blockers = blockers
        detail = message or f"{predicate} blocked for deck {deck_id}"
        super().__init__(detail)


class PlanGateError(GateError):
    """Raised when a Deck Plan cannot be reviewed."""

class ApprovalGateError(GateError):
    """Raised when a Deck Plan cannot be approved."""

class ProductionGateError(GateError):
    """Raised when production evidence is not authorized."""

class AssignmentGateError(GateError):
    """Raised when a worker assignment is not admissible."""

class PublicationGateError(GateError):
    """Raised when a module artifact does not match its contract."""

class ReviewGateError(GateError):
    """Raised when a slide or module review gate is incomplete."""

class DraftGateError(GateError):
    """Raised when a complete-deck draft preview is incomplete."""

class CompletionGateError(GateError):
    """Raised when final completion evidence is incomplete."""


def _state() -> Any:
    """Import the mutable state module lazily to avoid an import cycle."""
    import presentation_state

    return presentation_state


def fail_gate(error_type: type[GateError], predicate: str, deck_id: str, blockers: list[dict[str, Any]]) -> NoReturn:
    """Raise one gate exception with a deterministic blocker message.

    Args:
        error_type: Typed gate exception to raise.
        predicate: Stable predicate name reported by the structured CLI error.
        deck_id: Deck the predicate was evaluated for.
        blockers: Machine-readable failure evidence.

    Raises:
        GateError: Always, using ``error_type``.
    """
    summary = "; ".join(f"{blocker.get('reason', blocker)}{': ' + str(blocker['message']) if isinstance(blocker, dict) and blocker.get('message') else ''}" for blocker in blockers)
    raise error_type(
        predicate,
        deck_id,
        blockers,
        f"{predicate} blocked for deck {deck_id}: {summary or 'missing evidence'}",
    )
def _deck(project_root: Path, deck_id: str) -> dict[str, Any]:
    """Return a persisted deck or raise its typed not-found error."""
    from presentation_transactions import incomplete_transaction_journals

    if incomplete_transaction_journals(project_root):
        raise RuntimeError("incomplete_transaction journal requires recovery")
    state = _state()
    decks = state.load_decks(project_root)
    if deck_id not in decks:
        raise state.DeckNotFoundError(f"Unknown deck_id: {deck_id}")
    return decks[deck_id]
def _plan_for_deck(project_root: Path, deck: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """Load the current plan record and contract without inventing one."""
    records = load_plans(project_root)
    plan_id = deck.get("current_plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        return None, None, [{"reason": "missing_current_plan_id"}]
    record = records.get(plan_id)
    if record is None:
        return None, None, [{"reason": "invalid_current_plan_id", "plan_id": plan_id}]
    if record.get("deck_id") != deck.get("id"):
        return record, None, [{"reason": "current_plan_deck_mismatch", "plan_id": plan_id}]
    raw_path = record.get("plan_path", record.get("path"))
    if not isinstance(raw_path, str) or not raw_path:
        return record, None, [{"reason": "missing_plan_path", "plan_id": record.get("id")}]
    path = project_root / raw_path
    if not path.is_file():
        return record, None, [{"reason": "missing_plan_file", "path": raw_path}]
    try:
        document = load_contract(path)
    except (OSError, ValueError) as exc:
        return record, None, [{"reason": "invalid_plan_file", "message": str(exc)}]
    return record, document, []


def _plan_blockers(project_root: Path, deck: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """Validate the current registered plan and its persisted digest."""
    record, document, blockers = _plan_for_deck(project_root, deck)
    if document is None:
        return record, document, blockers
    errors = validate_deck_plan(document)
    blockers.extend({"reason": error} for error in errors)
    if record is not None:
        version = record.get("version")
        if document.get("plan_version") != version:
            blockers.append({"reason": "plan_version_mismatch", "expected": version, "actual": document.get("plan_version")})
        digest = contract_sha256(document)
        if record.get("sha256", record.get("plan_sha256")) != digest:
            blockers.append({"reason": "plan_digest_mismatch", "expected": record.get("sha256"), "actual": digest})
    return record, document, blockers


def _review_identity(review: Mapping[str, Any]) -> bool:
    """Return whether a review contains a verifiable reviewer identity."""
    reviewer_id = review.get("reviewer_id")
    return (
        isinstance(reviewer_id, str)
        and bool(reviewer_id.strip())
        and reviewer_id == reviewer_id.strip()
        and review.get("identity_verifiable", True) is not False
    )


def _finding_codes(findings: Any) -> set[str]:
    """Collect finding codes recursively for stable blocker matching."""
    codes: set[str] = set()
    if isinstance(findings, Mapping):
        for key in ("code", "kind", "type", "id", "finding"):
            value = findings.get(key)
            if isinstance(value, str):
                codes.add(value)
        for value in findings.values():
            codes.update(_finding_codes(value))
    elif isinstance(findings, list):
        for value in findings:
            codes.update(_finding_codes(value))
    return codes


def assert_plan_reviewable(project_root: Path, deck_id: str) -> dict[str, Any]:
    """Assert that a current Deck Plan is valid and ready for content review.

    Args:
        project_root: Project root containing presentation state.
        deck_id: Deck identifier.

    Returns:
        A mapping containing the persisted deck, plan record, and plan.

    Raises:
        PlanGateError: If plan evidence is missing or invalid.
    """
    try:
        deck = _deck(project_root, deck_id)
    except Exception as exc:  # noqa: BLE001 - gated not-found becomes structured evidence
        fail_gate(PlanGateError, "plan_reviewable", deck_id, [{"reason": "unknown_deck", "message": str(exc)}])
    _, document, blockers = _plan_blockers(project_root, deck)
    if deck.get("status") not in {"planning", "content_review", "awaiting_approval"}:
        blockers.append({"reason": f"status:{deck.get('status')}"})
    if deck.get("plan_revision_required"):
        blockers.append({"reason": "replacement_plan_required", "next_action": "register_plan"})
    if blockers:
        fail_gate(PlanGateError, "plan_reviewable", deck_id, blockers)
    record, _, _ = _plan_blockers(project_root, deck)
    return {"deck": deck, "plan": document, "plan_record": record}


def assert_plan_approvable(project_root: Path, approval: dict[str, Any]) -> dict[str, Any]:
    """Assert an approval is bound to a valid plan and independent review.

    Args:
        project_root: Project root containing presentation state.
        approval: Parsed Deck Approval contract.

    Returns:
        A mapping containing deck, approval, plan record, and plan document.

    Raises:
        ApprovalGateError: If any approval evidence is absent or inconsistent.
    """
    deck_id = approval.get("deck_id") if isinstance(approval, Mapping) else ""
    if not isinstance(deck_id, str) or not deck_id:
        deck_id = "<unknown>"
    blockers: list[dict[str, Any]] = []
    if not isinstance(approval, dict):
        blockers.append({"reason": "approval must be a mapping"})
        fail_gate(ApprovalGateError, "plan_approvable", deck_id, blockers)
    blockers.extend({"reason": error} for error in validate_deck_approval(approval))
    try:
        deck = _deck(project_root, deck_id)
    except Exception as exc:  # noqa: BLE001 - gated not-found becomes structured evidence
        fail_gate(ApprovalGateError, "plan_approvable", deck_id, [{"reason": "unknown_deck", "message": str(exc)}])
    record, plan, plan_blockers = _plan_blockers(project_root, deck)
    blockers.extend(plan_blockers)
    if plan is not None and record is not None:
        if approval.get("plan_version") != record.get("version"):
            blockers.append({"reason": "plan_version_mismatch"})
        if approval.get("plan_sha256") != contract_sha256(plan):
            blockers.append({"reason": "plan_digest_mismatch"})
    if deck.get("status") not in {"planning", "content_review", "awaiting_approval"}:
        blockers.append({"reason": f"status:{deck.get('status')}"})
    authored_by = plan.get("authored_by") if isinstance(plan, dict) else None
    raw_reviews = load_review_results(project_root, {deck_id})
    raw_content = [
        review for review in raw_reviews
        if review.get("subject_type") == "deck"
        and review.get("subject_id") == deck_id
        and review.get("reviewer_role") in _CONTENT_ROLES
    ]
    current_plan_id = record.get("id") if isinstance(record, Mapping) else None
    current_plan_version = record.get("version") if isinstance(record, Mapping) else None
    current_plan_sha256 = contract_sha256(plan) if isinstance(plan, Mapping) else None
    current_bound = [
        review for review in raw_content
        if review.get("current_plan_id") == current_plan_id
        and review.get("current_plan_version") == current_plan_version
        and review.get("current_plan_sha256") == current_plan_sha256
    ]
    content = effective_review_results(current_bound or raw_content)
    bound_content = []
    for review in content:
        findings = review.get("findings", [])
        if "unsupported-claim" in _finding_codes(findings):
            blockers.append({"reason": "unsupported-claim", "findings": findings})
        if not _review_identity(review):
            blockers.append({"reason": "reviewer_identity_unverifiable"})
        if authored_by and review.get("reviewer_id") == authored_by:
            blockers.append({"reason": "reviewer must differ from plan author"})
        if (
            review.get("current_plan_id") != current_plan_id
            or review.get("current_plan_version") != current_plan_version
            or review.get("current_plan_sha256") != current_plan_sha256
        ):
            blockers.append({"reason": "content_review_plan_binding_mismatch", "review_id": review.get("id")})
            continue
        bound_content.append(review)
    content = bound_content
    if not content:
        blockers.append({"reason": "missing_content_review"})
    for review in content:
        if not _review_identity(review):
            blockers.append({"reason": "reviewer_identity_unverifiable"})
        if authored_by and review.get("reviewer_id") == authored_by:
            blockers.append({"reason": "reviewer must differ from plan author"})
        findings = review.get("findings", [])
        codes = _finding_codes(findings)
        if "unsupported-claim" in codes:
            blockers.append({"reason": "unsupported-claim", "findings": findings})
        elif review.get("status") != "passed":
            blockers.append({"reason": f"content_review:{review.get('status')}", "findings": findings})
    if approval.get("approved_by") == authored_by:
        blockers.append({"reason": "approver must differ from plan author"})
    if approval.get("decision") != "approve":
        blockers.append({"reason": "decision must be approve"})
    if blockers:
        fail_gate(ApprovalGateError, "plan_approvable", deck_id, blockers)
    return {"deck": deck, "approval": approval, "plan_record": record, "plan": plan}


def assert_production_allowed(project_root: Path, deck_id: str) -> dict[str, Any]:
    """Assert that a deck has persisted approval before artifact production.

    Args:
        project_root: Project root containing presentation state.
        deck_id: Deck identifier.

    Returns:
        The approved deck record.

    Raises:
        ProductionGateError: If approval is absent or the deck is too early.
    """
    try:
        deck = _deck(project_root, deck_id)
    except Exception as exc:  # noqa: BLE001 - gated not-found becomes structured evidence
        fail_gate(ProductionGateError, "production_allowed", deck_id, [{"reason": "unknown_deck", "message": str(exc)}])
    blockers: list[dict[str, Any]] = []
    if deck.get("status") not in _APPROVED_STATUSES:
        blockers.append({"reason": f"status:{deck.get('status')}"})
    if not deck.get("approval_id") or deck.get("approved_plan_version") is None or not deck.get("approved_plan_sha256"):
        blockers.append({"reason": "missing_approval_evidence"})
    record, plan, plan_blockers = _plan_blockers(project_root, deck)
    blockers.extend(plan_blockers)
    if record is not None and deck.get("approved_plan_version") != record.get("version"):
        blockers.append({"reason": "approved_plan_version_stale"})
    if plan is not None and deck.get("approved_plan_sha256") != contract_sha256(plan):
        blockers.append({"reason": "approved_plan_digest_stale"})
    if blockers:
        fail_gate(ProductionGateError, "production_allowed", deck_id, blockers)
    return deck


def _module_context(project_root: Path, module_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Load module, parent slide, and owning deck ID."""
    state = _state()
    modules = state.load_visual_modules(project_root)
    if module_id not in modules:
        raise state.VisualModuleNotFoundError(f"Unknown module_id: {module_id}")
    module = modules[module_id]
    slides = state.load_slides(project_root)
    slide_id = module.get("slide_id")
    if slide_id not in slides:
        raise state.SlideNotFoundError(f"Unknown slide_id: {slide_id}")
    slide = slides[slide_id]
    deck_id = str(slide.get("deck_id"))
    _deck(project_root, deck_id)
    return module, slide, deck_id
def assert_module_assignable(project_root: Path, module_id: str, assignment: dict[str, Any]) -> dict[str, Any]:
    """Assert that a module has a valid specification and worker assignment.

    Args:
        project_root: Project root containing presentation state.
        module_id: Generated visual-module identifier.
        assignment: Worker Assignment contract mapping.

    Returns:
        A mapping containing module, assignment, and deck records.

    Raises:
        AssignmentGateError: If assignment evidence is missing or inconsistent.
    """
    try:
        module, slide, deck_id = _module_context(project_root, module_id)
    except Exception as exc:  # noqa: BLE001 - gated not-found becomes structured evidence
        fail_gate(AssignmentGateError, "module_assignable", "<unknown>", [{"reason": "unknown_module", "message": str(exc)}])
    blockers: list[dict[str, Any]] = []
    try:
        deck = assert_production_allowed(project_root, deck_id)
    except ProductionGateError as exc:
        fail_gate(AssignmentGateError, "module_assignable", deck_id, exc.blockers)
    if not isinstance(assignment, dict):
        blockers.append({"reason": "assignment must be a mapping"})
    else:
        blockers.extend({"reason": error} for error in validate_worker_assignment(assignment))
        if assignment.get("module_id") != module_id:
            blockers.append({"reason": "module_id_mismatch"})
        if assignment.get("inputs_resolved") is not True:
            blockers.append({"reason": "inputs_unresolved"})
        if assignment.get("worker_type") != module.get("module_type"):
            blockers.append({"reason": "worker_type_mismatch", "expected": module.get("module_type")})
        expected_dependencies = list(module.get("dependencies") or [])
        if assignment.get("dependencies") != expected_dependencies:
            blockers.append({
                "reason": "dependency_ids_mismatch",
                "expected": expected_dependencies,
                "actual": assignment.get("dependencies"),
            })
    if module.get("status") not in {"planned", "ready"}:
        blockers.append({"reason": f"status:{module.get('status')}"})
    dependencies = module.get("dependencies", [])
    modules = _state().load_visual_modules(project_root)
    unresolved = [dependency for dependency in dependencies if modules.get(dependency, {}).get("status") != "passed"]
    if unresolved:
        blockers.append({"reason": "unresolved_dependencies", "dependencies": unresolved})
    spec_document: dict[str, Any] | None = None
    spec_digest: str | None = None
    if module.get("module_type") in {"architecture", "data_visualization", "conceptual", "annotation"}:
        spec_path = module.get("visual_spec_path")
        if not isinstance(spec_path, str) or not (project_root / spec_path).is_file():
            blockers.append({"reason": "missing_visual_spec"})
        else:
            try:
                spec_document = load_contract(project_root / spec_path)
                blockers.extend({"reason": error} for error in validate_complex_visual_spec(spec_document))
                blockers.extend(
                    {"reason": error}
                    for error in validate_style_tokens_resolvable(
                        spec_document, (project_root / spec_path).parent
                    )
                )
                spec_digest = contract_sha256(spec_document)
                persisted_spec_digest = module.get("visual_spec_sha256", module.get("spec_sha256"))
                if not isinstance(persisted_spec_digest, str):
                    blockers.append({"reason": "missing_persisted_spec_digest"})
                elif persisted_spec_digest != spec_digest:
                    blockers.append({"reason": "persisted_spec_digest_mismatch"})
                if isinstance(assignment, dict) and assignment.get("spec_sha256") != spec_digest:
                    blockers.append({"reason": "spec_digest_mismatch", "expected": spec_digest})
                if isinstance(spec_document, Mapping):
                    spec_modules = spec_document.get("modules", [])
                    spec_module = next(
                        (entry for entry in spec_modules if isinstance(entry, Mapping) and entry.get("id") == module.get("module_key")),
                        None,
                    )
                    if spec_module is None:
                        blockers.append({"reason": "module_key_missing_from_spec"})
                    else:
                        spec_dependencies = list(spec_module.get("dependencies") or [])
                        module_by_key = {
                            item.get("module_key"): item.get("id")
                            for item in _state().load_visual_modules(project_root).values()
                            if isinstance(item, Mapping)
                        }
                        resolved_spec_dependencies = [module_by_key.get(dep, dep) for dep in spec_dependencies]
                        if resolved_spec_dependencies != list(module.get("dependencies") or []):
                            blockers.append({
                                "reason": "spec_dependency_ids_mismatch",
                                "expected": list(module.get("dependencies") or []),
                                "actual": resolved_spec_dependencies,
                            })
            except (OSError, ValueError) as exc:
                blockers.append({"reason": "invalid_visual_spec", "message": str(exc)})
    if blockers:
        fail_gate(AssignmentGateError, "module_assignable", deck_id, blockers)
    return {"deck": deck, "slide": slide, "module": module, "assignment": assignment}


def assert_module_publishable(project_root: Path, module_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
    """Assert that a module artifact matches its current assignment.

    Args:
        project_root: Project root containing presentation state.
        module_id: Generated visual-module identifier.
        artifact: Artifact record or publication manifest mapping.

    Returns:
        A mapping containing deck, module, assignment, and artifact records.

    Raises:
        PublicationGateError: If artifact evidence does not match assignment.
    """
    try:
        module, slide, deck_id = _module_context(project_root, module_id)
    except Exception as exc:  # noqa: BLE001 - gated not-found becomes structured evidence
        fail_gate(PublicationGateError, "module_publishable", "<unknown>", [{"reason": "unknown_module", "message": str(exc)}])
    try:
        deck = assert_production_allowed(project_root, deck_id)
    except ProductionGateError as exc:
        fail_gate(PublicationGateError, "module_publishable", deck_id, exc.blockers)
    blockers: list[dict[str, Any]] = []
    assignment_records = _state().load_assignments(project_root)
    current_path = module.get("assignment_path")
    assignments = [
        record for record in assignment_records.values()
        if record.get("module_id") == module_id
        and record.get("assignment_path", record.get("path")) == current_path
    ] if isinstance(current_path, str) and current_path else []
    assignment = assignments[0] if len(assignments) == 1 else None
    if not isinstance(current_path, str) or not current_path:
        blockers.append({"reason": "missing_current_assignment"})
    elif not assignments:
        blockers.append({"reason": "missing_assignment"})
    elif len(assignments) > 1:
        blockers.append({"reason": "ambiguous_assignment", "path": current_path})
    elif assignment.get("status") in {"stale", "superseded", "revoked"} or assignment.get("superseded") is True:
        blockers.append({"reason": "stale_assignment", "assignment_id": assignment.get("id")})
    if module.get("status") not in {"assigned", "producing", "review_required"}:
        blockers.append({"reason": f"status:{module.get('status')}"})
    if not isinstance(artifact, dict):
        blockers.append({"reason": "artifact must be a mapping"})
    else:
        if artifact.get("module_id") != module_id:
            blockers.append({"reason": "module_id_mismatch"})
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            blockers.append({"reason": "invalid_artifact_digest"})
        path = artifact.get("path", artifact.get("relative_path"))
        if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
            blockers.append({"reason": "invalid_artifact_path"})
        if assignment is not None and artifact.get("producer_id", artifact.get("produced_by")) != assignment.get("worker_id", assignment.get("worker")):
            blockers.append({"reason": "producer_mismatch"})
        if assignment is not None:
            if artifact.get("assignment_id") != assignment.get("id"):
                blockers.append({"reason": "assignment_binding_required"})
            if artifact.get("spec_sha256") != assignment.get("spec_sha256"):
                blockers.append({"reason": "spec_digest_mismatch"})
            if isinstance(path, str) and _SHA256.fullmatch(str(artifact.get("sha256", "")) or ""):
                resolved = project_root / path
                if not resolved.is_file():
                    blockers.append({"reason": "missing_artifact", "path": path})
                else:
                    actual_digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
                    if actual_digest != artifact.get("sha256"):
                        blockers.append({"reason": "artifact_digest_mismatch", "expected": artifact.get("sha256"), "actual": actual_digest})
    if blockers:
        fail_gate(PublicationGateError, "module_publishable", deck_id, blockers)
    return {"deck": deck, "slide": slide, "module": module, "assignment": assignment, "artifact": artifact}

_FINDING_KINDS = frozenset({"clipping", "overlap", "text-reflow", "connector-drift", "crop", "unreadably-small-text", "missing-image", "z-order", "alignment", "other", "unsupported-claim", "duplicated-content", "missing-limitation", "excessive-background", "unnecessary-visual", "weak-continuity"})
# Spec D5, verbatim and in the spec's order, plus the repository-wide "other".
# A defect with no name cannot be tracked, counted, or fixed on purpose, and
# "the output looks generically AI" had no name in this vocabulary at all.
_ART_DIRECTION_KINDS = frozenset({
    "visual-cliche", "decorative-noise", "style-drift",
    "synthetic-detail", "meaningless-interface", "stock-ai-composition",
    "weak-hierarchy", "undifferentiated-repetition", "other",
})
_FINDING_KINDS = frozenset(_FINDING_KINDS | _ART_DIRECTION_KINDS)
_RENDERING_KINDS = frozenset(
    _FINDING_KINDS
    - {"unsupported-claim", "duplicated-content", "missing-limitation",
       "excessive-background", "unnecessary-visual", "weak-continuity"}
    - (_ART_DIRECTION_KINDS - {"other"})
)
_FINDING_ROLE_KINDS = {
    "scientific": frozenset({"unsupported-claim", "other"}),
    "visual_quality": _RENDERING_KINDS,
    "render_integrity": _RENDERING_KINDS,
    "art_direction": _ART_DIRECTION_KINDS,
}

# Workflow order, not alphabetical order: a "what next" suggestion should send
# the operator to the next stage, and `art_direction` sorts before `scientific`.
SLIDE_REVIEW_ROLE_ORDER: tuple[str, ...] = (
    "scientific", "render_integrity", "art_direction",
)
SLIDE_REVIEW_ROLE_SETS: tuple[frozenset[str], ...] = (
    frozenset(SLIDE_REVIEW_ROLE_ORDER),
    frozenset({"scientific", "visual_quality"}),
)
# A module is a fragment, not a composition. Spec D5 scopes the art-direction
# review to the complete slide, so the module set never gains that role. The two
# tuples are equal today and are deliberately kept separate: making them one
# name is how a module ends up waiting on a gate nothing will ever dispatch.
MODULE_REVIEW_ROLE_ORDER: tuple[str, ...] = (
    "scientific", "render_integrity",
)
MODULE_REVIEW_ROLE_SETS: tuple[frozenset[str], ...] = (
    frozenset(MODULE_REVIEW_ROLE_ORDER),
    frozenset({"scientific", "visual_quality"}),
)


def module_reviews_complete(roles: AbstractSet[str]) -> bool:
    """Return whether a module's passing reviewer roles complete its review.

    Args:
        roles: Reviewer roles that have recorded a passing review.

    Returns:
        True when any accepted module role set is satisfied.
    """
    return any(roles >= required for required in MODULE_REVIEW_ROLE_SETS)


def slide_reviews_complete(roles: AbstractSet[str]) -> bool:
    """Return whether a subject's passing reviewer roles complete its review.

    Args:
        roles: Reviewer roles that have recorded a passing review.

    Returns:
        True when any accepted role set is satisfied. The legacy
        ``visual_quality`` pair is accepted so decks recorded before the review
        split still reach ``passed``.
    """
    return any(roles >= required for required in SLIDE_REVIEW_ROLE_SETS)


def _missing_roles(roles: AbstractSet[str], complete: bool,
                   order: tuple[str, ...]) -> tuple[str, ...]:
    """Return the outstanding roles of one ordering.

    Args:
        roles: Reviewer roles that have recorded a passing review.
        complete: Whether the review is already complete under any accepted set.
        order: The workflow ordering to report against.

    Returns:
        The unmet roles, or an empty tuple when the review is complete.
    """
    if complete:
        return ()
    return tuple(role for role in order if role not in roles)


def missing_slide_review_roles(roles: AbstractSet[str]) -> tuple[str, ...]:
    """Return the slide roles still outstanding, in workflow order.

    Args:
        roles: Reviewer roles that have recorded a passing review.

    Returns:
        The unmet roles of ``SLIDE_REVIEW_ROLE_ORDER``, or an empty tuple when
        the review is complete under any accepted set.
    """
    return _missing_roles(roles, slide_reviews_complete(roles),
                          SLIDE_REVIEW_ROLE_ORDER)


def missing_module_review_roles(roles: AbstractSet[str]) -> tuple[str, ...]:
    """Return the module roles still outstanding, in workflow order.

    Args:
        roles: Reviewer roles that have recorded a passing review.

    Returns:
        The unmet roles of ``MODULE_REVIEW_ROLE_ORDER``, or an empty tuple when
        the review is complete under any accepted set.
    """
    return _missing_roles(roles, module_reviews_complete(roles),
                          MODULE_REVIEW_ROLE_ORDER)

def _subject_tokens_digest(
    project_root: Path, deck_id: str, subject_type: str, subject_id: str
) -> str:
    """Return the token digest one subject's lint evidence must carry.

    Nothing in the state store records which token set a deck is held to. The
    module record's `visual_spec_path` looks like such a record and is not one:
    the store contract notes that no writer ever assigns it. So the contract is
    the token set the subject's own most recent run measured against, and
    `lint_evidence` separately refuses evidence whose token file has been
    edited since. That binds a result to its bytes, which is the property this
    gate exists for; verifying the token choice itself needs a deck-level token
    record the data model does not yet have.

    Args:
        project_root: Project root containing persisted state.
        deck_id: The deck the subject belongs to, kept for the day that record
            exists.
        subject_type: `slide` or `module`.
        subject_id: The subject being judged.

    Returns:
        The digest the subject's latest lint run recorded, or the empty string
        when it has never been linted -- which matches no evidence and so
        surfaces as `lint_evidence_missing` rather than as a token problem.
    """
    del deck_id
    return latest_lint_tokens_digest(project_root, subject_type, subject_id) or ""
_TERMINAL_DISPOSITIONS = frozenset({"fixed", "resolved", "closed", "accepted", "rechecked", "done", "dismissed"})

def review_result_blockers(
    project_root: Path, subject_type: str, subject_id: str, review: Mapping[str, Any], persisted_id: str | None = None,
    is_effective: bool = True,
) -> list[dict[str, Any]]:
    """Validate one production review and its independence constraints.

    Args:
        project_root: Project root containing persisted state.
        subject_type: ``slide`` or ``module``.
        subject_id: Target production-unit ID.
        review: Candidate Review Result mapping.
        persisted_id: Existing event ID when validating persisted history.
        is_effective: Whether this review is the current one for its role.
            A superseded review answered the warnings of the run it saw;
            holding it to a later run's warnings would deadlock the deck,
            because events are append-only and no new review can repair a
            round that has already been written.

    Returns:
        Machine-readable blockers; an empty list means admissible.
    """
    blockers: list[dict[str, Any]] = []
    if review.get("subject_type") != subject_type or review.get("subject_id") != subject_id:
        blockers.append({"reason": "review_subject_mismatch"})
    role = review.get("reviewer_role")
    if role not in _REVIEW_ROLES:
        blockers.append({"reason": "invalid_reviewer_role"})
    if role in _RETIRED_REVIEW_ROLES and persisted_id is None:
        blockers.append({"reason": "retired_reviewer_role"})
    reviewer_id = review.get("reviewer_id")
    if not _review_identity(review):
        blockers.append({"reason": "reviewer_identity_unverifiable"})
    if review.get("status") not in {"passed", "failed", "blocked"}:
        blockers.append({"reason": "invalid_review_status"})
    round_number = review.get("round", 1)
    if isinstance(round_number, bool) or not isinstance(round_number, int) or round_number < 1:
        blockers.append({"reason": "invalid_review_round"})
    findings = review.get("findings", [])
    if not isinstance(findings, list):
        blockers.append({"reason": "findings_must_be_list"})
        findings = []
    unresolved = 0
    for finding in findings:
        if not isinstance(finding, Mapping):
            blockers.append({"reason": "finding_must_be_mapping"})
            continue
        kind = finding.get("kind")
        code = finding.get("code")
        if (kind is None) == (code is None):
            blockers.append({"reason": "finding_kind_or_code_required"})
            continue
        finding_name = kind if kind is not None else code
        if not isinstance(finding_name, str) or finding_name not in _FINDING_ROLE_KINDS.get(str(role), set()):
            blockers.append({"reason": "finding_role_mismatch", "finding": finding_name})
        disposition = finding.get("disposition")
        if disposition is not None and (not isinstance(disposition, str) or disposition not in {"open"} | _TERMINAL_DISPOSITIONS):
            blockers.append({"reason": "invalid_finding_disposition"})
        if review.get("status") == "passed":
            blockers.append({"reason": "findings_inconsistent_with_passed_status"})
        elif disposition not in _TERMINAL_DISPOSITIONS:
            unresolved += 1
        elif review.get("status") in {"failed", "blocked"}:
            blockers.append({"reason": "findings_inconsistent_with_failed_status"})
    if review.get("status") in {"failed", "blocked"} and not unresolved:
        blockers.append({"reason": "failed_review_requires_unresolved_findings"})
    state = _state()
    target = (state.load_slides(project_root) if subject_type == "slide" else state.load_visual_modules(project_root)).get(subject_id)
    if target is None:
        blockers.append({"reason": "unknown_subject"})
    else:
        owner_ids = {str(target.get("created_by"))}
        for record in load_events(project_root, "review_result"):
            if record.get("subject_type") == subject_type and record.get("subject_id") == subject_id:
                if record.get("id") != persisted_id and record.get("reviewer_role") == role and record.get("round", 1) == round_number:
                    blockers.append({"reason": "duplicate_review_role_round"})
        for assignment in state.load_assignments(project_root).values():
            if assignment.get("module_id" if subject_type == "module" else "slide_id") == subject_id:
                owner_ids.add(str(assignment.get("worker_id", assignment.get("worker"))))
        for artifact in load_artifacts(project_root).values():
            if artifact.get("module_id" if subject_type == "module" else "slide_id") == subject_id:
                owner_ids.add(str(artifact.get("producer_id", artifact.get("produced_by"))))
        if isinstance(reviewer_id, str) and reviewer_id in owner_ids:
            blockers.append({"reason": "reviewer_self_review_prohibited"})
        if (role == "art_direction" and review.get("status") == "passed"
                and is_effective):
            blockers.extend(_art_direction_warning_blockers(
                project_root, subject_type, subject_id, target, review))
    return blockers
def _art_direction_warning_blockers(
    project_root: Path, subject_type: str, subject_id: str,
    target: Mapping[str, Any], review: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Check that a passing art-direction review answers the warnings raised.

    The persona says an art-direction review is incomplete until every linter
    warning is answered. Without this the field is decorative: a review passes
    with it absent, or with answers to warnings no run ever produced.

    Args:
        project_root: Project root containing persisted state.
        subject_type: ``slide`` or ``module``.
        subject_id: Target production-unit ID.
        target: The persisted slide or module record.
        review: The candidate Review Result mapping.

    Returns:
        Machine-readable blockers; empty when every raised warning is answered.
    """
    state = _state()
    if subject_type == "slide":
        deck_id = str(target.get("deck_id"))
    else:
        slide = state.load_slides(project_root).get(str(target.get("slide_id")), {})
        deck_id = str(slide.get("deck_id"))
    tokens_digest = _subject_tokens_digest(
        project_root, deck_id, subject_type, subject_id)
    artifact_sha256 = current_svg_digest(project_root, subject_type, subject_id)
    evidence = None if artifact_sha256 is None else current_lint_evidence(
        project_root, subject_type, subject_id, artifact_sha256, tokens_digest)
    if evidence is None:
        return [{"reason": "art_direction:lint_evidence_missing"}]
    if evidence["errors"]:
        # A pass recorded over outstanding hard errors is how a slide
        # reaches `passed` without anything calling `assert_slide_passable`:
        # the promotion in `record_production_review` counts roles, not
        # measurements.
        return [{
            "reason": "art_direction:lint_errors_outstanding",
            "rules": list(evidence["errors"]),
        }]
    review_ts = str(review.get("ts") or "")
    if review_ts and review_ts < str(evidence.get("ts") or ""):
        # Answers written before the measurement are not answers to it.
        # They match by rule name alone, which a later run reproduces for
        # free, so an old review would silently discharge new warnings.
        return [{"reason": "art_direction:review_predates_lint_run"}]
    unanswered = unanswered_warnings(evidence, review)
    if unanswered:
        return [{
            "reason": "art_direction:linter_warnings_unanswered",
            "rules": unanswered,
        }]
    return []
def assert_slide_passable(project_root: Path, slide_id: str) -> dict[str, Any]:
    """Assert independent scientific and visual-quality slide reviews pass.

    Args:
        project_root: Project root containing presentation state.
        slide_id: Generated slide identifier.

    Returns:
        The slide and its effective role-specific reviews.

    Raises:
        ReviewGateError: If either review role is absent or failing.
    """
    state = _state()
    slides = state.load_slides(project_root)
    if slide_id not in slides:
        fail_gate(ReviewGateError, "slide_passable", "<unknown>", [{"reason": "unknown_slide", "slide_id": slide_id}])
    slide = slides[slide_id]
    deck_id = str(slide.get("deck_id"))
    _deck(project_root, deck_id)
    blockers: list[dict[str, Any]] = []
    raw_reviews = load_review_results(project_root, {slide_id})
    reviews = effective_review_results(raw_reviews)
    # Only the current review of each role is held to the current lint
    # run. A superseded round answered the warnings it was shown, and the
    # event log is append-only, so judging it against a later run would
    # leave the slide permanently unpassable with no write that repairs
    # it.
    effective_ids = {str(review.get("id")) for review in reviews}
    for review in raw_reviews:
        review_id = str(review.get("id"))
        blockers.extend(review_result_blockers(
            project_root, "slide", slide_id, review, review_id,
            is_effective=review_id in effective_ids))
    by_role = {review.get("reviewer_role"): review for review in reviews}
    # `_REVIEW_ROLES` is the admissible set, not the required one. A slide
    # recorded before the review split carries `visual_quality` and will never
    # carry `render_integrity`, so iterating the admissible set as if it were
    # required would block every such slide forever. Judge the reviews that
    # exist, then ask the role-set predicate what is still outstanding.
    passing: set[str] = set()
    for role in sorted(by_role, key=str):
        review = by_role[role]
        name = str(role)
        if not _review_identity(review):
            blockers.append({"reason": f"{name}:reviewer_identity_unverifiable"})
        elif review.get("status") != "passed":
            blockers.append({"reason": f"{name}:{review.get('status')}", "findings": review.get("findings", [])})
        else:
            passing.add(name)
    blockers.extend({"reason": role} for role in missing_slide_review_roles(passing))
    # The linter's exit code is gone by the time anything asks this question,
    # so the gate reads the recorded result instead: no evidence, evidence
    # older than the current SVG or token set, and outstanding hard errors all
    # refuse the slide however many reviewers signed it off.
    blockers.extend(lint_blockers(
        project_root, "slide", slide_id,
        _subject_tokens_digest(project_root, deck_id, "slide", slide_id)))
    if slide.get("status") not in {"review_required", "passed"}:
        blockers.append({"reason": f"status:{slide.get('status')}"})
    if blockers:
        fail_gate(ReviewGateError, "slide_passable", deck_id, blockers)
    return {"slide": slide, "reviews": reviews}
def assert_module_passable(project_root: Path, module_id: str) -> dict[str, Any]:
    """Assert a module has real production provenance and passing reviews.

    Reviews and non-empty paths are not sufficient. The gate resolves exactly
    one current assignment and module artifact, validates their persisted
    ownership and integrity, and rejects path strings whose records or bytes no
    longer exist.

    Args:
        project_root: Project root containing presentation state.
        module_id: Generated visual-module identifier.

    Returns:
        The module record and its effective role-specific reviews.

    Raises:
        ReviewGateError: If provenance is absent or either review role is
            missing or failing.
    """
    modules = _state().load_visual_modules(project_root)
    module = modules.get(module_id)
    if module is None:
        fail_gate(ReviewGateError, "module_passable", "<unknown>", [{"reason": "unknown_module", "module_id": module_id}])
    slides = _state().load_slides(project_root)
    deck_id = str(slides.get(module.get("slide_id"), {}).get("deck_id"))
    _deck(project_root, deck_id)
    blockers: list[dict[str, Any]] = []
    raw_reviews = load_review_results(project_root, {module_id})
    for review in raw_reviews:
        blockers.extend(review_result_blockers(project_root, "module", module_id, review, str(review.get("id"))))
    reviews = effective_review_results(raw_reviews)
    roles = {review.get("reviewer_role") for review in reviews if review.get("status") == "passed"}
    blockers.extend({"reason": role} for role in missing_module_review_roles({str(role) for role in roles}))
    if module.get("status") not in {"review_required", "passed"}:
        blockers.append({"reason": f"status:{module.get('status')}"})
    state = _state()
    lineage, lineage_blockers = resolve_module_production_lineage(
        project_root,
        module,
        deck_id,
        {
            "decks": state.load_decks(project_root),
            "slides": slides,
            "visual_modules": modules,
        },
    )
    blockers.extend(lineage_blockers)
    if blockers:
        fail_gate(ReviewGateError, "module_passable", deck_id, blockers)
    return {"module": module, "reviews": reviews, **lineage}
def assert_draft_reviewable(project_root: Path, deck_id: str, preview: dict[str, Any]) -> dict[str, Any]:
    """Assert a complete rendered slide set is available for draft review.

    Args:
        project_root: Project root containing presentation state.
        deck_id: Deck identifier.
        preview: Draft Preview contract mapping.

    Returns:
        The deck, preview, and current slide records.

    Raises:
        DraftGateError: If any slide or contact-sheet evidence is missing.
    """
    try:
        deck = _deck(project_root, deck_id)
    except Exception as exc:  # noqa: BLE001 - gated not-found becomes structured evidence
        fail_gate(DraftGateError, "draft_reviewable", deck_id, [{"reason": "unknown_deck", "message": str(exc)}])
    blockers: list[dict[str, Any]] = []
    try:
        assert_production_allowed(project_root, deck_id)
    except ProductionGateError as exc:
        blockers.extend(exc.blockers)
    if deck.get("status") not in {"draft_review", "validating"}:
        blockers.append({"reason": f"status:{deck.get('status')}"})
    if not isinstance(preview, dict):
        blockers.append({"reason": "preview must be a mapping"})
        fail_gate(DraftGateError, "draft_reviewable", deck_id, blockers)
    if preview.get("deck_id") != deck_id:
        blockers.append({"reason": "deck_id_mismatch"})
    rendered = preview.get("rendered_slide_paths")
    if not isinstance(rendered, list) or not rendered:
        blockers.append({"reason": "rendered slide set"})
    else:
        slides = [
            slide for slide in _state().load_slides(project_root).values()
            if slide.get("deck_id") == deck_id and slide.get("status") != "superseded"
        ]
        for slide in slides:
            if slide.get("status") != "passed":
                blockers.append({"reason": f"slide:{slide.get('id')}:not_passed"})
        expected = {slide.get("plan_slide_id", slide.get("id")) for slide in slides}
        supplied = set()
        for item in rendered:
            if isinstance(item, Mapping):
                slide_key = item.get("slide_id", item.get("plan_slide_id"))
                supplied.add(slide_key)
                item_path = item.get("path")
            elif isinstance(item, str):
                item_path = item
                supplied.add(Path(item).stem)
            else:
                item_path = None
            if not isinstance(item_path, str) or not item_path.lower().endswith(".png"):
                blockers.append({"reason": "rendered slide path must be a PNG"})
            elif not Path(item_path).is_absolute() and ".." not in Path(item_path).parts and not (project_root / item_path).is_file():
                blockers.append({"reason": "missing_rendered_slide", "path": item_path})
        if expected and not expected <= supplied:
            blockers.append({"reason": "rendered slide set", "missing": sorted(expected - supplied)})
        if len(supplied) != len(rendered):
            blockers.append({"reason": "rendered slide set contains duplicates"})
    contact_sheet = preview.get("contact_sheet_path", preview.get("contact_sheet"))
    if not isinstance(contact_sheet, str) or not contact_sheet:
        blockers.append({"reason": "missing_contact_sheet"})
    elif Path(contact_sheet).is_absolute() or ".." in Path(contact_sheet).parts:
        blockers.append({"reason": "invalid_contact_sheet_path"})
    elif not (project_root / contact_sheet).is_file():
        blockers.append({"reason": "missing_contact_sheet", "path": contact_sheet})
    _, plan, plan_blockers = _plan_blockers(project_root, deck)
    if plan_blockers:
        blockers.extend(plan_blockers)
    if isinstance(plan, Mapping):
        expected_fields = {
            entry.get("slide_id"): (entry.get("title"), entry.get("key_takeaway"))
            for entry in plan.get("slides", []) if isinstance(entry, Mapping)
        }
        preview_slides = preview.get("slides", preview.get("rendered_slides", []))
        if isinstance(preview_slides, list):
            for entry in preview_slides:
                if not isinstance(entry, Mapping):
                    blockers.append({"reason": "preview slide must be a mapping"})
                    continue
                slide_key = entry.get("slide_id", entry.get("plan_slide_id"))
                expected = expected_fields.get(slide_key)
                if expected is None:
                    blockers.append({"reason": "preview slide is not in approved plan", "slide_id": slide_key})
                elif (entry.get("title"), entry.get("key_takeaway", entry.get("takeaway"))) != expected:
                    blockers.append({"reason": "preview title/takeaway mismatch", "slide_id": slide_key})
    digests = preview.get("artifact_digests", preview.get("artifacts", {}))
    if digests and isinstance(digests, Mapping):
        for artifact_path, digest in digests.items():
            if not isinstance(artifact_path, str) or Path(artifact_path).is_absolute() or ".." in Path(artifact_path).parts:
                blockers.append({"reason": "invalid_preview_artifact_path", "path": artifact_path})
            if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
                blockers.append({"reason": "invalid_preview_artifact_digest", "path": artifact_path})
    if blockers:
        fail_gate(DraftGateError, "draft_reviewable", deck_id, blockers)
    return {
        "deck": deck,
        "preview": preview,
        "slides": [
            slide for slide in _state().load_slides(project_root).values()
            if slide.get("deck_id") == deck_id and slide.get("status") != "superseded"
        ],
    }



def assert_deck_completable(project_root: Path, deck_id: str, completion: dict[str, Any]) -> dict[str, Any]:
    """Assert all persisted current evidence required for completion exists.

    ``completion_allowed`` and similar caller booleans are intentionally
    ignored; every gate is derived from persisted records and current files.

    Args:
        project_root: Project root containing presentation state.
        deck_id: Deck identifier.
        completion: Completion record supplied by the final validator.

    Returns:
        A mapping containing deck, completion record, and final evidence.

    Raises:
        CompletionGateError: If any required evidence is missing or failing.
    """
    try:
        deck = _deck(project_root, deck_id)
    except Exception as exc:  # noqa: BLE001 - gated not-found becomes structured evidence
        fail_gate(CompletionGateError, "deck_completable", deck_id, [{"reason": "unknown_deck", "message": str(exc)}])
    blockers: list[dict[str, Any]] = []
    try:
        assert_production_allowed(project_root, deck_id)
    except ProductionGateError as exc:
        blockers.extend(exc.blockers)
    if deck.get("status") != "validating":
        blockers.append({"reason": f"status:{deck.get('status')}"})
    if not isinstance(completion, dict):
        blockers.append({"reason": "completion must be a mapping"})
    slides = [
        dict(record)
        for record in _state().load_slides(project_root).values()
        if isinstance(record, Mapping)
        and record.get("deck_id") == deck_id
        and record.get("status") != "superseded"
    ]
    slide_ids = {slide.get("id") for slide in slides}
    modules = [
        dict(module)
        for module in _state().load_visual_modules(project_root).values()
        if module.get("status") != "superseded" and module.get("slide_id") in slide_ids
    ]
    if not slides:
        blockers.extend({"reason": role} for role in SLIDE_REVIEW_ROLE_ORDER)
    for slide in slides:
        if slide.get("status") != "passed":
            blockers.append({"reason": f"slide:{slide.get('id')}:status:{slide.get('status')}"})
        try:
            assert_slide_passable(project_root, str(slide.get("id")))
        except ReviewGateError as exc:
            blockers.extend(exc.blockers)
    for module in modules:
        if module.get("status") != "passed":
            blockers.append({"reason": f"module:{module.get('id')}:status:{module.get('status')}"})
        try:
            assert_module_passable(project_root, str(module.get("id")))
        except ReviewGateError as exc:
            blockers.extend({"reason": f"module:{module.get('id')}:{item.get('reason', item)}"} for item in exc.blockers)
    current = resolve_current_evidence(
        project_root, deck_id, ("draft_preview", "draft_approval")
    )
    blockers.extend(dict(blocker) for blocker in current.blockers)
    visual_review = (
        final_visual_review_blockers(project_root, deck_id, completion, blockers)
        if isinstance(completion, Mapping)
        else None
    )
    if blockers:
        fail_gate(CompletionGateError, "deck_completable", deck_id, blockers)
    return {"deck": deck, "completion": completion, "slides": slides, "modules": modules, "visual_review": visual_review}
