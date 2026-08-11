"""Exact source and target contracts for presentation state-store records."""

from __future__ import annotations

from typing import Any, Mapping

from presentation_artifact_provenance import (
    REVIEW_SHEET_KIND,
    SLIDE_PNG_KIND,
    validate_artifact_provenance,
    validate_artifact_subject,
)


_DIGEST_LENGTH = 64
_DECK_STATUSES = frozenset(
    {"planning", "content_review", "awaiting_approval", "approved", "producing",
     "draft_review", "validating", "revising", "completed", "blocked"}
)
_UNIT_STATUSES = frozenset(
    {"planned", "ready", "assigned", "producing", "review_required",
     "revision_required", "passed", "blocked", "superseded"}
)
_MODULE_TYPES = frozenset(
    {"data_visualization", "architecture", "conceptual", "annotation"}
)
_SUBJECT_TYPES = frozenset({"plan", "module", "slide", "deck"})
_REQUESTERS = frozenset({"user", "reviewer"})

_DECK_REQUIRED = frozenset({"id", "title", "status", "created_by"})
_DECK_OPTIONAL = frozenset(
    {"plan_version", "current_plan_id", "approved_plan_version",
     "approved_plan_sha256", "approval_id", "approved_by", "approved_at",
     "approval_mode", "draft_preview_id", "draft_approval_id",
     "draft_preview_evidence_id", "draft_approval_evidence_id",
     "completion_evidence_id", "required_plan_revision_id", "created_at",
     "updated_at", "identity_verifiable", "plan_revision_required",
     "required_plan_id"}
)
_PLAN_REQUIRED = frozenset({"id", "deck_id", "version", "plan_sha256"})
_PLAN_OPTIONAL = frozenset(
    {"plan_version", "sha256", "plan_path", "path", "authored_by", "created_by",
     "supersedes_plan_id", "created_at"}
)
_SLIDE_REQUIRED = frozenset(
    {"id", "deck_id", "plan_slide_id", "title", "status"}
)
_SLIDE_OPTIONAL = frozenset(
    {"created_at", "updated_at", "created_by", "approved_takeaway_sha256",
     "approved_evidence_sha256", "slide_spec_path", "slide_spec_sha256",
     "attempt", "supersedes_slide_id", "revision_request_id", "revision_kind"}
)
_MODULE_REQUIRED = frozenset(
    {"id", "slide_id", "module_key", "module_type", "dependencies", "status"}
)
_MODULE_OPTIONAL = frozenset(
    {"visual_spec_path", "visual_spec_sha256", "spec_sha256", "assignment_path",
     "artifact_manifest_path", "attempt", "supersedes_module_id", "created_at",
     "updated_at", "created_by", "revision_request_id", "revision_kind"}
)
_ASSIGNMENT_FIELDS = frozenset(
    {"id", "deck_id", "slide_id", "module_id", "assignment_path", "path",
     "relative_path", "worker_id", "worker", "worker_type", "dependencies",
     "spec_sha256", "inputs_resolved", "blocker", "assigned_at", "created_at"}
)
_ARTIFACT_BASE = frozenset(
    {"id", "deck_id", "slide_id", "module_id", "artifact_kind", "kind", "path",
     "relative_path", "sha256", "producer_id", "produced_by", "created_at"}
)
_ARTIFACT_PROVENANCE = frozenset(
    {"plan_version", "plan_sha256", "slide_record_id", "attempt", "source_paths",
     "source_sha256"}
)
_ARTIFACT_HISTORICAL = frozenset({"id", "deck_id", "artifact_kind", "path", "sha256"})
_ARTIFACT_PLURAL = frozenset({"id", "deck_id", "source_paths", "rendered_slide_paths"})
_REVISION_FIELDS = frozenset(
    {"id", "subject_type", "subject_id", "requested_by", "instructions",
     "supersedes", "created_at"}
)
_REVISION_TARGET_FIELDS = frozenset(
    {"revision_kind", "target_type", "target_id", "requested_subject_type",
     "requested_subject_id"}
)
_REVISION_PLAN_FIELDS = frozenset(
    {"plan_scoped", "scope_subject_type", "scope_subject_id", "plan_id",
     "plan_version", "plan_sha256", "current_plan_id", "current_plan_version",
     "current_plan_sha256", "next_action"}
)
_REVISION_KINDS = frozenset(
    {"revise_slide", "add_slide", "remove_slide", "reorder_slides",
     "change_emphasis", "change_audience", "change_duration",
     "review_finding", "module_retry", "slide_retry"}
)


def validate_additional_store_record(
    store_name: str,
    record: Mapping[str, Any],
    *,
    relations: Mapping[str, Mapping[str, Any]],
    legacy: bool,
) -> None:
    """Validate one exact store record and its ownership relations.

    Args:
        store_name: Authoritative store containing the record.
        record: Parsed record to validate without mutation.
        relations: Explicit id-keyed state-store relations.
        legacy: Whether schema-zero/one source refinements are permitted.

    Raises:
        ValueError: If shape, type, lifecycle, alias, or ownership is invalid.
    """
    if type(legacy) is not bool:
        raise ValueError("legacy must be a bool")
    validators = {
        "decks": _validate_deck,
        "plans": _validate_plan,
        "slides": _validate_slide,
        "visual_modules": _validate_module,
        "assignments": _validate_assignment,
        "artifacts": _validate_artifact,
        "revision_requests": _validate_revision,
    }
    validator = validators.get(store_name)
    if validator is None:
        raise ValueError(f"unknown authoritative store {store_name!r}")
    validator(record, relations, legacy)


def _validate_deck(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]], legacy: bool
) -> None:
    """Validate deck identity, lifecycle, and optional approval refinements."""
    del legacy
    _fields(record, _DECK_REQUIRED, _DECK_OPTIONAL, "decks")
    for field in ("id", "title", "created_by"):
        _text(record.get(field), f"decks.{field}")
    _enum(record.get("status"), _DECK_STATUSES, "decks.status")
    _optional_nonnegative_int(record, "plan_version", "decks")
    _optional_positive_int(record, "approved_plan_version", "decks")
    _optional_digest(record, "approved_plan_sha256", "decks")
    for field in (
        "current_plan_id", "approval_id", "approved_by", "approved_at",
        "draft_preview_id", "draft_approval_id", "draft_preview_evidence_id",
        "draft_approval_evidence_id", "completion_evidence_id",
        "required_plan_revision_id", "required_plan_id", "created_at", "updated_at",
    ):
        _optional_text(record, field, "decks")
    if "approval_mode" in record and record["approval_mode"] is not None:
        _enum(
            record["approval_mode"],
            frozenset({"interactive", "explicit_noninteractive"}),
            "decks.approval_mode",
        )
    if "identity_verifiable" in record and type(record["identity_verifiable"]) is not bool:
        raise ValueError("decks.identity_verifiable must be a bool")
    if "plan_revision_required" in record and type(record["plan_revision_required"]) is not bool:
        raise ValueError("decks.plan_revision_required must be a bool")
    current_plan_id = record.get("current_plan_id")
    if current_plan_id is not None:
        current_plan = _owner(relations, "plans", current_plan_id, "decks.current_plan_id")
        if current_plan.get("deck_id") != record["id"]:
            raise ValueError("decks current plan owner does not match deck id")
    required_plan_id = record.get("required_plan_id")
    if required_plan_id is not None:
        required_plan = _owner(relations, "plans", required_plan_id, "decks.required_plan_id")
        if required_plan.get("deck_id") != record["id"]:
            raise ValueError("decks required plan owner does not match deck id")
    revision_id = record.get("required_plan_revision_id")
    if revision_id is not None:
        revision = _owner(
            relations, "revision_requests", revision_id,
            "decks.required_plan_revision_id",
        )
        if _record_deck_id(relations, "revision_requests", revision) != record["id"]:
            raise ValueError("decks required revision owner does not match deck id")


def _validate_plan(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]], legacy: bool
) -> None:
    """Validate immutable plan identity and canonical aliases."""
    historical_fields = frozenset({"id", "deck_id", "version", "plan_sha256"})
    if legacy and set(record) == historical_fields:
        _text(record.get("id"), "plans.id")
        _text(record.get("deck_id"), "plans.deck_id")
        _positive_int(record.get("version"), "plans.version")
        _digest(record.get("plan_sha256"), "plans.plan_sha256")
        _owner(relations, "decks", record["deck_id"], "plans.deck_id")
        return
    if legacy and "path" not in record:
        expected = frozenset(
            {"id", "deck_id", "version", "plan_path", "plan_sha256", "authored_by"}
        )
        if "sha256" in record:
            expected |= {"sha256"}
        if "created_at" in record:
            expected |= {"created_at"}
        _exact_fields(record, expected, "plans")
        for field in ("id", "deck_id", "authored_by"):
            _text(record.get(field), f"plans.{field}")
        _positive_int(record.get("version"), "plans.version")
        _path(record.get("plan_path"), "plans.plan_path")
        _digest(record.get("plan_sha256"), "plans.plan_sha256")
        if "sha256" in record and record["sha256"] != record["plan_sha256"]:
            raise ValueError("plans.sha256 must equal plan_sha256")
        _optional_text(record, "created_at", "plans")
        _owner(relations, "decks", record["deck_id"], "plans.deck_id")
        return
    _fields(record, _PLAN_REQUIRED, _PLAN_OPTIONAL, "plans")
    _text(record.get("id"), "plans.id")
    _text(record.get("deck_id"), "plans.deck_id")
    _positive_int(record.get("version"), "plans.version")
    _digest(record.get("plan_sha256"), "plans.plan_sha256")
    _owner(relations, "decks", record["deck_id"], "plans.deck_id")
    if "plan_version" in record and record["plan_version"] != record["version"]:
        raise ValueError("plans.plan_version must equal version")
    if "sha256" in record and record["sha256"] != record["plan_sha256"]:
        raise ValueError("plans.sha256 must equal plan_sha256")
    _equal_path_aliases(record, "plan_path", "path", "plans")
    for field in ("authored_by", "created_by", "supersedes_plan_id", "created_at"):
        _optional_text(record, field, "plans")
    predecessor = record.get("supersedes_plan_id")
    if predecessor is not None:
        prior = _owner(relations, "plans", predecessor, "plans.supersedes_plan_id")
        if prior.get("deck_id") != record["deck_id"]:
            raise ValueError("plans predecessor owner does not match deck_id")


def _validate_slide(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]], legacy: bool
) -> None:
    """Validate legacy-compatible slide identity and lifecycle fields."""
    del legacy
    _fields(record, _SLIDE_REQUIRED, _SLIDE_OPTIONAL, "slides")
    for field in ("id", "deck_id", "plan_slide_id", "title"):
        _text(record.get(field), f"slides.{field}")
    _enum(record.get("status"), _UNIT_STATUSES, "slides.status")
    _owner(relations, "decks", record["deck_id"], "slides.deck_id")
    _optional_positive_int(record, "attempt", "slides")
    for field in ("created_at", "updated_at", "created_by", "supersedes_slide_id",
                  "revision_request_id", "revision_kind"):
        _optional_text(record, field, "slides")
    for field in ("approved_takeaway_sha256", "approved_evidence_sha256",
                  "slide_spec_sha256"):
        _optional_digest(record, field, "slides")
    _optional_path(record, "slide_spec_path", "slides")
    if record.get("slide_spec_sha256") is not None and record.get("slide_spec_path") is None:
        raise ValueError("slides.slide_spec_sha256 requires slide_spec_path")
    predecessor = record.get("supersedes_slide_id")
    if predecessor is not None:
        prior = _owner(relations, "slides", predecessor, "slides.supersedes_slide_id")
        if prior.get("deck_id") != record["deck_id"]:
            raise ValueError("slides predecessor owner does not match deck_id")
    revision_id = record.get("revision_request_id")
    if revision_id is not None:
        revision = _owner(
            relations, "revision_requests", revision_id,
            "slides.revision_request_id",
        )
        if revision.get("target_type") != "slide" or revision.get("target_id") != predecessor:
            raise ValueError("slides revision request target does not match predecessor")


def _validate_module(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]], legacy: bool
) -> None:
    """Validate legacy-compatible visual-module identity and lifecycle."""
    del legacy
    _fields(record, _MODULE_REQUIRED, _MODULE_OPTIONAL, "visual_modules")
    for field in ("id", "slide_id", "module_key"):
        _text(record.get(field), f"visual_modules.{field}")
    _enum(record.get("module_type"), _MODULE_TYPES, "visual_modules.module_type")
    _enum(record.get("status"), _UNIT_STATUSES, "visual_modules.status")
    _text_list(record.get("dependencies"), "visual_modules.dependencies")
    slide = _owner(relations, "slides", record["slide_id"], "visual_modules.slide_id")
    if not isinstance(slide.get("deck_id"), str):
        raise ValueError("visual_modules slide owner is invalid")
    for dependency_id in record["dependencies"]:
        dependency = _owner(
            relations, "visual_modules", dependency_id, "visual_modules.dependencies"
        )
        dependency_slide = _owner(
            relations, "slides", dependency.get("slide_id"),
            "visual_modules dependency slide_id",
        )
        if dependency_slide.get("deck_id") != slide.get("deck_id"):
            raise ValueError("visual_modules dependency deck owner does not match")
    _optional_positive_int(record, "attempt", "visual_modules")
    for field in ("visual_spec_path", "assignment_path", "artifact_manifest_path"):
        _optional_path(record, field, "visual_modules")
    for field in ("visual_spec_sha256", "spec_sha256"):
        _optional_digest(record, field, "visual_modules")
    if record.get("visual_spec_sha256") is not None and record.get("spec_sha256") is not None:
        if record["visual_spec_sha256"] != record["spec_sha256"]:
            raise ValueError("visual_modules.spec_sha256 digest aliases must match")
    for field in ("supersedes_module_id", "created_at", "updated_at", "created_by",
                  "revision_request_id", "revision_kind"):
        _optional_text(record, field, "visual_modules")
    predecessor = record.get("supersedes_module_id")
    if predecessor is not None:
        source = _owner(
            relations, "visual_modules", predecessor,
            "visual_modules.supersedes_module_id",
        )
        source_slide = _owner(
            relations, "slides", source.get("slide_id"),
            "visual_modules predecessor slide_id",
        )
        if source_slide.get("deck_id") != slide.get("deck_id"):
            raise ValueError("visual_modules predecessor owner does not match deck")
    revision_id = record.get("revision_request_id")
    if revision_id is not None:
        revision = _owner(
            relations, "revision_requests", revision_id,
            "visual_modules.revision_request_id",
        )
        if revision.get("target_type") != "module" or revision.get("target_id") != predecessor:
            raise ValueError(
                "visual_modules.revision_request_id target does not match predecessor"
            )


def _validate_assignment(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]], legacy: bool
) -> None:
    """Validate an exact public assignment and its ownership chain."""
    del legacy
    _exact_fields(record, _ASSIGNMENT_FIELDS, "assignments")
    for field in ("id", "deck_id", "slide_id", "module_id", "worker_id", "worker",
                  "worker_type", "assigned_at", "created_at"):
        _text(record.get(field), f"assignments.{field}")
    _equal_path_aliases(record, "assignment_path", "path", "assignments")
    if record["relative_path"] != record["assignment_path"]:
        raise ValueError("assignments path aliases must match")
    _path(record["relative_path"], "assignments.relative_path")
    if record["worker"] != record["worker_id"]:
        raise ValueError("assignments worker aliases must match")
    _digest(record.get("spec_sha256"), "assignments.spec_sha256")
    if type(record.get("inputs_resolved")) is not bool:
        raise ValueError("assignments.inputs_resolved must be a bool")
    _optional_text(record, "blocker", "assignments")
    _text_list(record.get("dependencies"), "assignments.dependencies")
    deck = _owner(relations, "decks", record["deck_id"], "assignments.deck_id")
    slide = _owner(relations, "slides", record["slide_id"], "assignments.slide_id")
    module = _owner(relations, "visual_modules", record["module_id"], "assignments.module_id")
    if slide.get("deck_id") != deck.get("id") or module.get("slide_id") != slide.get("id"):
        raise ValueError("assignments relation owners do not match")
    for dependency_id in record["dependencies"]:
        dependency = _owner(
            relations, "visual_modules", dependency_id,
            "assignments.dependencies",
        )
        dependency_slide = _owner(
            relations, "slides", dependency.get("slide_id"),
            "assignments dependency slide_id",
        )
        if dependency_slide.get("deck_id") != record["deck_id"]:
            raise ValueError("assignments dependency owner does not match deck_id")


def _validate_artifact(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]], legacy: bool
) -> None:
    """Validate public, projected-history, or documented plural artifact shape."""
    fields = set(record)
    if legacy and fields == _ARTIFACT_PLURAL:
        _text(record.get("id"), "artifacts.id")
        _text(record.get("deck_id"), "artifacts.deck_id")
        _owner(relations, "decks", record["deck_id"], "artifacts.deck_id")
        _path_list(record.get("source_paths"), "artifacts.source_paths")
        rendered = record.get("rendered_slide_paths")
        if not isinstance(rendered, list) or not rendered:
            raise ValueError("artifacts.rendered_slide_paths must be a nonempty list")
        for entry in rendered:
            if not isinstance(entry, Mapping) or set(entry) != {"path", "slide_id"}:
                raise ValueError("artifacts rendered entry fields are invalid")
            _path(entry.get("path"), "artifacts.rendered path")
            _text(entry.get("slide_id"), "artifacts.rendered slide_id")
        return
    if fields == _ARTIFACT_HISTORICAL:
        _validate_historical_artifact(record, relations)
        return
    _exact_fields(record, _ARTIFACT_BASE | (fields & _ARTIFACT_PROVENANCE), "artifacts")
    for field in ("id", "deck_id", "artifact_kind", "kind", "producer_id",
                  "produced_by", "created_at"):
        _text(record.get(field), f"artifacts.{field}")
    if record["kind"] != record["artifact_kind"]:
        raise ValueError("artifacts kind aliases must match")
    if record["produced_by"] != record["producer_id"]:
        raise ValueError("artifacts producer aliases must match")
    try:
        validate_artifact_subject(
            record["artifact_kind"], record.get("slide_id"), record.get("module_id")
        )
        normalized_provenance = validate_artifact_provenance(
            record["artifact_kind"],
            deck_id=record["deck_id"],
            slide_id=record.get("slide_id"),
            module_id=record.get("module_id"),
            plan_version=record.get("plan_version"),
            plan_sha256=record.get("plan_sha256"),
            slide_record_id=record.get("slide_record_id"),
            attempt=record.get("attempt"),
            source_paths=record.get("source_paths"),
            source_sha256=record.get("source_sha256"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"artifacts provenance is invalid: {exc}") from exc
    declared_provenance = {
        field: record[field] for field in _ARTIFACT_PROVENANCE if field in record
    }
    if declared_provenance != normalized_provenance:
        raise ValueError("artifacts provenance fields do not match artifact kind")
    _equal_path_aliases(record, "path", "relative_path", "artifacts")
    _digest(record.get("sha256"), "artifacts.sha256")
    _owner(relations, "decks", record["deck_id"], "artifacts.deck_id")
    slide = None
    if record.get("slide_id") is not None:
        slide = _owner(relations, "slides", record["slide_id"], "artifacts.slide_id")
        if slide.get("deck_id") != record["deck_id"]:
            raise ValueError("artifacts slide owner does not match deck_id")
    if record.get("module_id") is not None:
        module = _owner(
            relations, "visual_modules", record["module_id"], "artifacts.module_id"
        )
        module_slide = _owner(
            relations, "slides", module.get("slide_id"), "artifacts module slide_id"
        )
        if module_slide.get("deck_id") != record["deck_id"]:
            raise ValueError("artifacts module owner does not match deck_id")
        if slide is not None and module.get("slide_id") != slide.get("id"):
            raise ValueError("artifacts module owner does not match slide_id")
    _optional_positive_int(record, "plan_version", "artifacts")
    _optional_digest(record, "plan_sha256", "artifacts")
    _optional_text(record, "slide_record_id", "artifacts")
    _optional_positive_int(record, "attempt", "artifacts")
    if "source_paths" in record:
        _path_list(record["source_paths"], "artifacts.source_paths")
    _optional_digest(record, "source_sha256", "artifacts")
    if record["artifact_kind"] in {SLIDE_PNG_KIND, REVIEW_SHEET_KIND}:
        _validate_artifact_plan_relation(record, relations)
    if record["artifact_kind"] == SLIDE_PNG_KIND:
        slide_record = _owner(
            relations, "slides", record.get("slide_record_id"),
            "artifacts.slide_record_id",
        )
        if (
            slide_record.get("id") != record.get("slide_id")
            or slide_record.get("deck_id") != record["deck_id"]
            or slide_record.get("attempt") != record.get("attempt")
        ):
            raise ValueError("artifacts slide provenance does not match slide relation")


def _validate_artifact_plan_relation(
    record: Mapping[str, Any],
    relations: Mapping[str, Mapping[str, Any]],
) -> None:
    """Resolve typed artifact provenance to one immutable same-deck plan.

    Args:
        record: Exact typed artifact record carrying historical plan provenance.
        relations: Explicit ID-keyed state-store relations.

    Raises:
        ValueError: If no unique persisted plan matches the artifact's owning
            deck, plan version, and canonical plan digest.
    """
    plans = relations.get("plans")
    if not isinstance(plans, Mapping):
        raise ValueError("artifacts plan provenance does not resolve in relation plans")
    matches: list[Mapping[str, Any]] = []
    for plan_id, candidate in plans.items():
        if not isinstance(candidate, Mapping):
            continue
        if (
            candidate.get("deck_id") == record["deck_id"]
            and type(candidate.get("version")) is int
            and candidate.get("version") == record.get("plan_version")
            and candidate.get("plan_sha256") == record.get("plan_sha256")
        ):
            if not isinstance(plan_id, str) or candidate.get("id") != plan_id:
                raise ValueError("artifacts plan provenance relation identity is invalid")
            matches.append(candidate)
    if len(matches) != 1:
        raise ValueError(
            "artifacts plan provenance must resolve to exactly one same-deck plan"
        )


def _validate_historical_artifact(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]]
) -> None:
    """Validate the exact historical artifact-record refinement."""
    for field in ("id", "deck_id", "artifact_kind"):
        _text(record.get(field), f"artifacts.{field}")
    _path(record.get("path"), "artifacts.path")
    _digest(record.get("sha256"), "artifacts.sha256")
    _owner(relations, "decks", record["deck_id"], "artifacts.deck_id")


def _validate_revision(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]], legacy: bool
) -> None:
    """Validate a public revision request and its typed subject relation."""
    del legacy
    fields = set(record)
    expected = _REVISION_FIELDS
    if fields != expected:
        expected = _REVISION_FIELDS | _REVISION_TARGET_FIELDS
    if fields != expected:
        expected = _REVISION_FIELDS | _REVISION_TARGET_FIELDS | _REVISION_PLAN_FIELDS
    _exact_fields(record, expected, "revision_requests")
    for field in ("id", "subject_id", "instructions", "created_at"):
        _text(record.get(field), f"revision_requests.{field}")
    _enum(record.get("subject_type"), _SUBJECT_TYPES, "revision_requests.subject_type")
    _enum(record.get("requested_by"), _REQUESTERS, "revision_requests.requested_by")
    _optional_text(record, "supersedes", "revision_requests")
    relation_store = {
        "deck": "decks", "plan": "plans", "slide": "slides", "module": "visual_modules"
    }[record["subject_type"]]
    subject = _owner(
        relations, relation_store, record["subject_id"],
        "revision_requests.subject_id",
    )
    if _REVISION_TARGET_FIELDS.issubset(record):
        _validate_revision_target(record, relations)
    supersedes = record.get("supersedes")
    if supersedes is not None:
        predecessor = _owner(
            relations, relation_store, supersedes,
            "revision_requests.supersedes",
        )
        if (
            _record_deck_id(relations, relation_store, predecessor)
            != _record_deck_id(relations, relation_store, subject)
        ):
            raise ValueError("revision_requests supersedes owner does not match subject deck")


def _validate_revision_target(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]]
) -> None:
    """Validate one workflow-targeted revision refinement."""
    _enum(record.get("revision_kind"), _REVISION_KINDS, "revision_requests.revision_kind")
    _enum(record.get("target_type"), _SUBJECT_TYPES, "revision_requests.target_type")
    _enum(
        record.get("requested_subject_type"), _SUBJECT_TYPES,
        "revision_requests.requested_subject_type",
    )
    for field in ("target_id", "requested_subject_id"):
        _text(record.get(field), f"revision_requests.{field}")
    target_store = {
        "deck": "decks", "plan": "plans", "slide": "slides",
        "module": "visual_modules",
    }[record["target_type"]]
    target = _owner(
        relations, target_store, record["target_id"],
        "revision_requests.target_id",
    )
    if record["requested_subject_id"] != record["target_id"]:
        raise ValueError("revision_requests requested subject must match target")
    if record["requested_subject_type"] != record["target_type"]:
        raise ValueError("revision_requests requested subject type must match target")
    if _record_deck_id(relations, target_store, target) != _record_deck_id(
        relations,
        {
            "deck": "decks", "plan": "plans", "slide": "slides",
            "module": "visual_modules",
        }[record["subject_type"]],
        _owner(
            relations,
            {
                "deck": "decks", "plan": "plans", "slide": "slides",
                "module": "visual_modules",
            }[record["subject_type"]],
            record["subject_id"],
            "revision_requests.subject_id",
        ),
    ):
        raise ValueError("revision_requests target owner does not match subject deck")
    if _REVISION_PLAN_FIELDS.issubset(record):
        if type(record.get("plan_scoped")) is not bool or not record["plan_scoped"]:
            raise ValueError("revision_requests.plan_scoped must be true")
        if record.get("scope_subject_type") != "plan" or record.get("next_action") != "register_plan":
            raise ValueError("revision_requests plan scope is invalid")
        plan = _owner(relations, "plans", record.get("plan_id"), "revision_requests.plan_id")
        for field in ("scope_subject_id", "current_plan_id"):
            if record.get(field) != plan.get("id"):
                raise ValueError(f"revision_requests.{field} must match plan_id")
        for field in ("plan_version", "current_plan_version"):
            _positive_int(record.get(field), f"revision_requests.{field}")
            if record[field] != plan.get("version"):
                raise ValueError(f"revision_requests.{field} must match plan version")
        for field in ("plan_sha256", "current_plan_sha256"):
            _digest(record.get(field), f"revision_requests.{field}")
            if record[field] != plan.get("plan_sha256"):
                raise ValueError(f"revision_requests.{field} must match plan digest")


def _record_deck_id(
    relations: Mapping[str, Mapping[str, Any]],
    store: str,
    record: Mapping[str, Any],
) -> object:
    """Return the owning deck identifier for one resolved relation record."""
    if store == "decks":
        return record.get("id")
    if store in {"plans", "slides"}:
        return record.get("deck_id")
    if store == "visual_modules":
        slide = _owner(
            relations, "slides", record.get("slide_id"),
            "visual_modules.slide_id",
        )
        return slide.get("deck_id")
    if store == "revision_requests":
        subject_store = {
            "deck": "decks", "plan": "plans", "slide": "slides",
            "module": "visual_modules",
        }.get(record.get("subject_type"))
        if subject_store is None:
            raise ValueError("revision_requests subject type is invalid")
        subject = _owner(
            relations, subject_store, record.get("subject_id"),
            "revision_requests.subject_id",
        )
        return _record_deck_id(relations, subject_store, subject)
    raise ValueError(f"cannot derive deck owner for store {store!r}")


def _fields(
    record: Mapping[str, Any], required: frozenset[str], optional: frozenset[str], label: str
) -> None:
    """Require all identity fields and reject every unknown field."""
    missing = sorted(required - set(record))
    unknown = sorted(set(record) - required - optional)
    if missing or unknown:
        raise ValueError(f"{label} fields are invalid: missing {missing}, unknown {unknown}")


def _exact_fields(record: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    """Require one exact mapping field set."""
    if set(record) != expected:
        raise ValueError(
            f"{label} fields are invalid: missing {sorted(expected - set(record))}, "
            f"unknown {sorted(set(record) - expected)}"
        )


def _text(value: object, field: str) -> None:
    """Require trimmed nonempty text."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be nonempty trimmed text")


def _optional_text(record: Mapping[str, Any], field: str, label: str) -> None:
    """Validate one nullable optional text field when declared."""
    if field in record and record[field] is not None:
        _text(record[field], f"{label}.{field}")


def _positive_int(value: object, field: str) -> None:
    """Require a positive integer while rejecting booleans."""
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


def _optional_positive_int(record: Mapping[str, Any], field: str, label: str) -> None:
    """Validate one nullable optional positive integer."""
    if field in record and record[field] is not None:
        _positive_int(record[field], f"{label}.{field}")


def _optional_nonnegative_int(record: Mapping[str, Any], field: str, label: str) -> None:
    """Validate one nullable optional nonnegative integer."""
    if field not in record or record[field] is None:
        return
    value = record[field]
    if type(value) is not int or value < 0:
        raise ValueError(f"{label}.{field} must be a nonnegative integer")


def _digest(value: object, field: str) -> None:
    """Require a lowercase SHA-256 digest."""
    if (not isinstance(value, str) or len(value) != _DIGEST_LENGTH
            or any(character not in "0123456789abcdef" for character in value)):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _optional_digest(record: Mapping[str, Any], field: str, label: str) -> None:
    """Validate one nullable optional digest."""
    if field in record and record[field] is not None:
        _digest(record[field], f"{label}.{field}")


def _enum(value: object, allowed: frozenset[str], field: str) -> None:
    """Require one exact documented enum value."""
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field} is invalid")


def _path(value: object, field: str) -> None:
    """Require one canonical project-relative POSIX path."""
    _text(value, field)
    assert isinstance(value, str)
    if value.startswith("/") or "\\" in value or any(
        part in {"", ".", ".."} for part in value.split("/")
    ):
        raise ValueError(f"{field} must be a canonical relative path")


def _optional_path(record: Mapping[str, Any], field: str, label: str) -> None:
    """Validate one nullable optional path."""
    if field in record and record[field] is not None:
        _path(record[field], f"{label}.{field}")


def _path_list(value: object, field: str) -> None:
    """Require a nonempty unique list of canonical paths."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a nonempty list")
    for item in value:
        _path(item, field)
    if len(set(value)) != len(value):
        raise ValueError(f"{field} must not contain duplicates")


def _text_list(value: object, field: str) -> None:
    """Require a unique list of trimmed identifiers."""
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    for item in value:
        _text(item, field)
    if len(set(value)) != len(value):
        raise ValueError(f"{field} must not contain duplicates")


def _equal_path_aliases(
    record: Mapping[str, Any], first: str, second: str, label: str
) -> None:
    """Validate two optional path aliases as an all-or-none equal pair."""
    present = (first in record, second in record)
    if present == (False, False):
        return
    if present != (True, True) or record[first] != record[second]:
        raise ValueError(f"{label} path aliases must both exist and match")
    _path(record[first], f"{label}.{first}")


def _owner(
    relations: Mapping[str, Mapping[str, Any]], store: str, record_id: object, field: str
) -> Mapping[str, Any]:
    """Resolve one required relation by exact identifier."""
    _text(record_id, field)
    assert isinstance(record_id, str)
    records = relations.get(store)
    if not isinstance(records, Mapping) or record_id not in records:
        raise ValueError(f"{field} does not resolve in relation {store}")
    related = records[record_id]
    if not isinstance(related, Mapping) or related.get("id") != record_id:
        raise ValueError(f"{field} relation identity is invalid")
    return related


def _optional_owner(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]], field: str,
    store: str, label: str
) -> None:
    """Resolve one nullable optional owner relation."""
    value = record.get(field)
    if value is not None:
        _owner(relations, store, value, f"{label}.{field}")
