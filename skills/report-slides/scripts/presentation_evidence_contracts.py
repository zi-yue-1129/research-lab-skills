"""Pure schema-v2 contracts for report-slides evidence and state records.

The functions in this module validate parsed immutable values only.  Callers
must provide every authoritative relation explicitly; this layer never reads
mutable workflow files or derives missing evidence from paths.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping

from presentation_contracts import contract_sha256
from presentation_store_record_contracts import validate_additional_store_record


EVIDENCE_SCHEMA_VERSION = 2


class EvidenceContractError(ValueError):
    """Raised when a schema-v2 evidence or state contract is invalid."""


_SHA256_LENGTH = 64
_BASE_ENVELOPE_FIELDS = frozenset(
    {
        "id",
        "schema_version",
        "evidence_kind",
        "deck_id",
        "plan_id",
        "plan_version",
        "plan_sha256",
        "subject_ids",
        "producer_id",
        "artifact_refs",
        "source_event_id",
        "created_at",
        "availability",
        "evidence_sha256",
    }
)
_ARTIFACT_REF_FIELDS = frozenset(
    {"sha256", "cas_path", "artifact_kind", "subject_id", "original_path"}
)
_APPROVAL_FIELDS = frozenset(
    {
        "preview_evidence_id",
        "preview_evidence_sha256",
        "decision",
        "approval_mode",
        "approved_by",
    }
)
_COMPLETION_FIELDS = frozenset(
    {
        "approval_evidence_id",
        "approval_evidence_sha256",
        "visual_review_evidence_id",
        "visual_review_evidence_sha256",
    }
)
_EVIDENCE_KINDS = frozenset(
    {"draft_preview", "draft_approval", "visual_review", "deck_completion"}
)
_RECORD_STORES = frozenset(
    {
        "decks",
        "plans",
        "slides",
        "visual_modules",
        "assignments",
        "artifacts",
        "revision_requests",
    }
)
_MODULE_FIELDS = frozenset(
    {
        "id",
        "slide_id",
        "module_key",
        "module_type",
        "dependencies",
        "status",
        "visual_spec_path",
        "assignment_path",
        "artifact_manifest_path",
        "attempt",
        "supersedes_module_id",
        "created_at",
        "updated_at",
        "created_by",
    }
)
_MODULE_RETRY_FIELDS = (_MODULE_FIELDS - {"updated_at"}) | frozenset(
    {"revision_request_id", "revision_kind"}
)
_SLIDE_FIELDS = frozenset(
    {
        "id",
        "deck_id",
        "plan_slide_id",
        "title",
        "status",
        "created_at",
        "updated_at",
        "created_by",
        "approved_takeaway_sha256",
        "approved_evidence_sha256",
        "slide_spec_path",
        "slide_spec_sha256",
        "attempt",
    }
)
_SLIDE_RETRY_FIELDS = (_SLIDE_FIELDS - {"updated_at"}) | frozenset(
    {"supersedes_slide_id", "revision_request_id", "revision_kind"}
)
_LEGACY_SLIDE_REQUIRED_FIELDS = frozenset(
    {"id", "deck_id", "plan_slide_id", "title", "status"}
)
_LEGACY_SLIDE_OPTIONAL_FIELDS = (
    _SLIDE_FIELDS | _SLIDE_RETRY_FIELDS
) - _LEGACY_SLIDE_REQUIRED_FIELDS
_LEGACY_MODULE_REQUIRED_FIELDS = frozenset(
    {"id", "slide_id", "module_key", "module_type", "dependencies", "status"}
)
_LEGACY_MODULE_OPTIONAL_FIELDS = (
    _MODULE_FIELDS
    | _MODULE_RETRY_FIELDS
    | frozenset({"visual_spec_sha256", "spec_sha256"})
) - _LEGACY_MODULE_REQUIRED_FIELDS
_ASSIGNMENT_FIELDS = frozenset(
    {
        "id",
        "deck_id",
        "slide_id",
        "module_id",
        "assignment_path",
        "path",
        "relative_path",
        "worker_id",
        "worker",
        "worker_type",
        "dependencies",
        "spec_sha256",
        "inputs_resolved",
        "blocker",
        "assigned_at",
        "created_at",
    }
)


def envelope_sha256(envelope: Mapping[str, Any]) -> str:
    """Return the canonical digest excluding ``evidence_sha256``.

    Args:
        envelope: Parsed schema-v2 envelope candidate.

    Returns:
        The canonical lowercase SHA-256 digest of the envelope payload.

    Raises:
        EvidenceContractError: If ``envelope`` is not a mapping or cannot be
            canonically serialized.
    """
    if not isinstance(envelope, Mapping):
        raise EvidenceContractError("envelope must be a mapping")
    payload = {key: value for key, value in envelope.items() if key != "evidence_sha256"}
    try:
        return contract_sha256(payload)
    except (TypeError, ValueError, RecursionError) as exc:
        raise EvidenceContractError(f"envelope cannot be canonically hashed: {exc}") from exc


def validate_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Return a validated copy of one exact schema-v2 envelope.

    Args:
        envelope: Parsed envelope to validate without mutating it.

    Returns:
        A deep copy of the validated envelope.

    Raises:
        EvidenceContractError: If any base field, evidence-kind refinement,
            digest, artifact binding, or lifecycle declaration is invalid.
    """
    candidate = _mapping(envelope, "envelope")
    evidence_kind = candidate.get("evidence_kind")
    if evidence_kind not in _EVIDENCE_KINDS:
        raise EvidenceContractError("evidence_kind is not registered")
    expected_fields = _BASE_ENVELOPE_FIELDS | _refinement_fields(evidence_kind)
    _require_exact_fields(candidate, expected_fields, "envelope")
    _require_text(candidate.get("id"), "id")
    _require_exact_int(candidate.get("schema_version"), EVIDENCE_SCHEMA_VERSION, "schema_version")
    _require_text(candidate.get("deck_id"), "deck_id")
    _require_text(candidate.get("plan_id"), "plan_id")
    _require_positive_int(candidate.get("plan_version"), "plan_version")
    _require_digest(candidate.get("plan_sha256"), "plan_sha256")
    _validate_subject_ids(candidate.get("subject_ids"), str(candidate["deck_id"]))
    _require_text(candidate.get("producer_id"), "producer_id")
    _require_text(candidate.get("source_event_id"), "source_event_id")
    _require_rfc3339(candidate.get("created_at"), "created_at")
    if candidate.get("availability") not in {"available", "historical_unavailable"}:
        raise EvidenceContractError("availability must be available or historical_unavailable")
    artifact_refs = _validate_artifact_refs(candidate)
    _validate_kind_refinement(candidate, evidence_kind, artifact_refs)
    _require_digest(candidate.get("evidence_sha256"), "evidence_sha256")
    expected_digest = envelope_sha256(candidate)
    if candidate["evidence_sha256"] != expected_digest:
        raise EvidenceContractError("evidence_sha256 does not match the canonical envelope payload")
    return deepcopy(dict(candidate))


def validate_store_record(
    store_name: str,
    record: Mapping[str, Any],
    *,
    relations: Mapping[str, Mapping[str, Any]],
    legacy: bool = False,
) -> dict[str, Any]:
    """Validate one record using authoritative store and relation context.

    Args:
        store_name: Name of the authoritative record store.
        record: Parsed record to validate without mutation.
        relations: Explicit id-keyed maps for stores and auxiliary contracts.
        legacy: Whether the record is an exact schema-zero/one migration input.

    Returns:
        A deep copy of the validated record.

    Raises:
        EvidenceContractError: If the store is unsupported, a record field is
            malformed, or an explicit relation does not match.
    """
    if store_name not in _RECORD_STORES:
        raise EvidenceContractError(f"unknown authoritative store {store_name!r}")
    candidate = _mapping(record, f"{store_name} record")
    relation_maps = _relation_maps(relations)
    if type(legacy) is not bool:
        raise EvidenceContractError("legacy must be a bool")
    if legacy:
        try:
            validate_additional_store_record(store_name, candidate)
        except ValueError as exc:
            raise EvidenceContractError(str(exc)) from exc
        return deepcopy(dict(candidate))
    if store_name == "visual_modules":
        _validate_visual_module(candidate, relation_maps)
    elif store_name == "assignments":
        _validate_assignment(candidate, relation_maps)
    elif store_name == "slides":
        _validate_slide(candidate, relation_maps)
    else:
        try:
            validate_additional_store_record(store_name, candidate)
        except ValueError as exc:
            raise EvidenceContractError(str(exc)) from exc
    return deepcopy(dict(candidate))


def validate_deck_evidence_pointers(
    deck: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
) -> None:
    """Validate pointer ownership, kind, lifecycle, and availability.

    Args:
        deck: Current deck record containing evidence-pointer fields.
        evidence: Immutable evidence envelopes keyed by envelope ID.

    Raises:
        EvidenceContractError: If a pointer is malformed, unresolved, owned by
            another deck, of the wrong kind, unavailable, or lifecycle-invalid.
    """
    deck_record = _mapping(deck, "deck")
    deck_id = deck_record.get("id")
    _require_text(deck_id, "deck.id")
    status = deck_record.get("status")
    _require_text(status, "deck.status")
    evidence_map = _mapping(evidence, "evidence")
    pointers = (
        ("draft_preview_evidence_id", "draft_preview"),
        ("draft_approval_evidence_id", "draft_approval"),
        ("completion_evidence_id", "deck_completion"),
    )
    resolved: dict[str, dict[str, Any] | None] = {}
    for field, kind in pointers:
        value = deck_record.get(field)
        if value is None:
            resolved[field] = None
            continue
        _require_text(value, field)
        raw_envelope = evidence_map.get(value)
        if raw_envelope is None:
            raise EvidenceContractError(f"{field} does not resolve")
        validated = validate_envelope(raw_envelope)
        if validated["id"] != value:
            raise EvidenceContractError(f"{field} must match its evidence map key")
        if validated["deck_id"] != deck_id:
            raise EvidenceContractError(f"{field} evidence deck_id does not match deck.id")
        if validated["evidence_kind"] != kind:
            raise EvidenceContractError(f"{field} must reference {kind} evidence")
        if validated["availability"] != "available":
            raise EvidenceContractError(f"{field} evidence availability must be available")
        resolved[field] = validated
    if resolved["draft_approval_evidence_id"] is not None:
        preview = resolved["draft_preview_evidence_id"]
        if preview is None:
            raise EvidenceContractError("draft_approval_evidence_id requires draft_preview_evidence_id")
        approval = resolved["draft_approval_evidence_id"]
        if approval["preview_evidence_id"] != preview["id"]:
            raise EvidenceContractError("draft approval preview_evidence_id does not match current preview")
        if approval["preview_evidence_sha256"] != preview["evidence_sha256"]:
            raise EvidenceContractError("draft approval preview_evidence_sha256 does not match current preview")
        if approval["decision"] != "approved":
            raise EvidenceContractError("draft approval pointer requires an approved decision")
    completion = resolved["completion_evidence_id"]
    if completion is not None:
        if status != "completed":
            raise EvidenceContractError("completion_evidence_id is only valid for a completed deck")
        approval = resolved["draft_approval_evidence_id"]
        if approval is None:
            raise EvidenceContractError("completion_evidence_id requires draft_approval_evidence_id")
        if completion["approval_evidence_id"] != approval["id"]:
            raise EvidenceContractError("completion approval_evidence_id does not match current approval")
        if completion["approval_evidence_sha256"] != approval["evidence_sha256"]:
            raise EvidenceContractError("completion approval_evidence_sha256 does not match current approval")
        review_id = completion["visual_review_evidence_id"]
        review = evidence_map.get(review_id)
        if review is None:
            raise EvidenceContractError("completion visual_review_evidence_id does not resolve")
        validated_review = validate_envelope(review)
        if validated_review["id"] != review_id or validated_review["evidence_kind"] != "visual_review":
            raise EvidenceContractError("completion visual_review_evidence_id has the wrong evidence kind")
        if validated_review["deck_id"] != deck_id:
            raise EvidenceContractError("completion visual review deck_id does not match deck.id")
        if validated_review["availability"] != "available":
            raise EvidenceContractError("completion visual review must be available")
        if completion["visual_review_evidence_sha256"] != validated_review["evidence_sha256"]:
            raise EvidenceContractError("completion visual_review_evidence_sha256 does not match visual review")
    elif status == "completed":
        raise EvidenceContractError("completed deck requires completion_evidence_id")


def artifact_policy_for_event(event_kind: str) -> str:
    """Return ``draft_preview``, ``deck_completion``, or ``none``.

    Args:
        event_kind: Immutable workflow event name.

    Returns:
        The registered artifact policy for ``event_kind``.
    """
    if event_kind == "draft_preview":
        return "draft_preview"
    if event_kind == "deck_completion":
        return "deck_completion"
    return "none"


def legacy_nullable_path_fields(
    store_name: str | None, record: Mapping[object, object]
) -> frozenset[str]:
    """Return nullable paths for documented schema-0 and schema-1 records.

    Schema-v2 records retain their exact intrinsic validation. The explicitly
    legacy branch accepts only a required identity/status schema plus a closed
    set of known optional fields; it never infers a record kind from a key
    subset. Migration still validates non-null paths against the filesystem.

    Args:
        store_name: Legacy top-level store name, if known.
        record: Parsed legacy record to classify.

    Returns:
        The documented path fields that may be null for this exact record.

    Raises:
        EvidenceContractError: If a record has an unknown, mixed, or invalid
            documented legacy field/path/digest combination.
    """
    candidate = _mapping(record, f"{store_name} record")
    if store_name == "slides":
        if set(candidate) in {_SLIDE_FIELDS, _SLIDE_RETRY_FIELDS}:
            _validate_slide_intrinsic(candidate)
            if candidate.get("status") != "planned":
                return frozenset()
        else:
            _validate_legacy_planned_slide(candidate)
        return frozenset({"slide_spec_path"})
    if store_name == "visual_modules":
        if set(candidate) - {"spec_sha256", "visual_spec_sha256"} in {
            _MODULE_FIELDS,
            _MODULE_RETRY_FIELDS,
        }:
            _validate_visual_module_intrinsic(candidate)
            if candidate.get("status") != "planned":
                return frozenset()
        else:
            _validate_legacy_planned_module(candidate)
        return frozenset(
            {"visual_spec_path", "assignment_path", "artifact_manifest_path"}
        )
    return frozenset()


def _validate_legacy_planned_slide(record: Mapping[str, Any]) -> None:
    """Validate the closed schema-0/1 planned-slide compatibility shape."""
    _require_legacy_record_fields(
        record,
        _LEGACY_SLIDE_REQUIRED_FIELDS,
        _LEGACY_SLIDE_OPTIONAL_FIELDS,
        "slides",
    )
    for field in ("id", "deck_id", "plan_slide_id", "title"):
        _require_text(record.get(field), f"slides.{field}")
    _require_legacy_planned_status(record, "slides")
    _validate_legacy_optional_texts(
        record, ("created_at", "updated_at", "created_by"), "slides"
    )
    _validate_legacy_optional_positive_int(record, "attempt", "slides")
    _validate_legacy_optional_digest_fields(
        record, ("approved_takeaway_sha256", "approved_evidence_sha256"), "slides"
    )
    _validate_legacy_retry_fields(
        record, ("supersedes_slide_id", "revision_request_id", "revision_kind"), "slides"
    )
    path = record.get("slide_spec_path")
    digest = record.get("slide_spec_sha256")
    if path is None:
        if digest is not None:
            raise EvidenceContractError("slides.slide_spec_sha256 requires slide_spec_path")
        return
    _canonical_relative_path(path, "slides.slide_spec_path")
    if digest is not None:
        _require_digest(digest, "slides.slide_spec_sha256")


def _validate_legacy_planned_module(record: Mapping[str, Any]) -> None:
    """Validate the closed schema-0/1 planned-module compatibility shape."""
    _require_legacy_record_fields(
        record,
        _LEGACY_MODULE_REQUIRED_FIELDS,
        _LEGACY_MODULE_OPTIONAL_FIELDS,
        "visual_modules",
    )
    for field in ("id", "slide_id", "module_key", "module_type"):
        _require_text(record.get(field), f"visual_modules.{field}")
    _require_legacy_planned_status(record, "visual_modules")
    _validate_text_list(record.get("dependencies"), "visual_modules.dependencies")
    _validate_legacy_optional_texts(
        record, ("created_at", "updated_at", "created_by"), "visual_modules"
    )
    _validate_legacy_optional_positive_int(record, "attempt", "visual_modules")
    if "supersedes_module_id" in record and record["supersedes_module_id"] is not None:
        _require_text(record["supersedes_module_id"], "visual_modules.supersedes_module_id")
    _validate_legacy_retry_fields(
        record, ("revision_request_id", "revision_kind"), "visual_modules"
    )
    _validate_legacy_module_spec(record)
    for field in ("assignment_path", "artifact_manifest_path"):
        if record.get(field) is not None:
            _canonical_relative_path(record[field], f"visual_modules.{field}")


def _require_legacy_record_fields(
    record: Mapping[str, Any],
    required_fields: frozenset[str],
    optional_fields: frozenset[str],
    store_name: str,
) -> None:
    """Require documented legacy fields and reject all unknown/mixed fields."""
    actual_fields = set(record)
    missing_fields = sorted(required_fields - actual_fields)
    unknown_fields = sorted(actual_fields - required_fields - optional_fields)
    if not missing_fields and not unknown_fields:
        return
    details: list[str] = []
    if missing_fields:
        details.append(f"missing {missing_fields}")
    if unknown_fields:
        details.append(f"unknown {unknown_fields}")
    raise EvidenceContractError(f"{store_name} legacy fields are invalid: {', '.join(details)}")


def _require_legacy_planned_status(record: Mapping[str, Any], store_name: str) -> None:
    """Require the sole lifecycle that can use legacy nullable paths."""
    if record.get("status") != "planned":
        raise EvidenceContractError(f"{store_name} legacy nullable paths require planned status")


def _validate_legacy_optional_texts(
    record: Mapping[str, Any], fields: tuple[str, ...], store_name: str
) -> None:
    """Validate any declared optional legacy text values."""
    for field in fields:
        if field in record:
            _require_text(record[field], f"{store_name}.{field}")


def _validate_legacy_optional_positive_int(
    record: Mapping[str, Any], field: str, store_name: str
) -> None:
    """Validate one declared optional positive integer legacy value."""
    if field in record:
        _require_positive_int(record[field], f"{store_name}.{field}")


def _validate_legacy_optional_digest_fields(
    record: Mapping[str, Any], fields: tuple[str, ...], store_name: str
) -> None:
    """Validate non-null optional legacy digest values."""
    for field in fields:
        if field in record and record[field] is not None:
            _require_digest(record[field], f"{store_name}.{field}")


def _validate_legacy_retry_fields(
    record: Mapping[str, Any], fields: tuple[str, ...], store_name: str
) -> None:
    """Reject partial retry refinements that cannot bind authoritative relations."""
    if any(field in record for field in fields):
        raise EvidenceContractError(
            f"{store_name} legacy records cannot mix partial retry fields with placeholder paths"
        )


def _validate_legacy_module_spec(record: Mapping[str, Any]) -> None:
    """Validate a schema-0/1 module path and its optional digest aliases."""
    canonical_present = "visual_spec_sha256" in record
    legacy_present = "spec_sha256" in record
    canonical_digest = record.get("visual_spec_sha256")
    legacy_digest = record.get("spec_sha256")
    if canonical_present and legacy_present and canonical_digest != legacy_digest:
        raise EvidenceContractError("visual_modules.spec_sha256 conflicts with visual_spec_sha256")
    _validate_legacy_optional_digest_fields(
        record, ("visual_spec_sha256", "spec_sha256"), "visual_modules"
    )
    if record.get("visual_spec_path") is None:
        if canonical_digest is not None or legacy_digest is not None:
            raise EvidenceContractError(
                "visual_modules visual_spec digest requires visual_spec_path"
            )
        return
    _canonical_relative_path(record["visual_spec_path"], "visual_modules.visual_spec_path")


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    """Return a string-keyed mapping or raise a typed contract error."""
    if not isinstance(value, Mapping):
        raise EvidenceContractError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise EvidenceContractError(f"{field} keys must be strings")
    return value


def _refinement_fields(evidence_kind: str) -> frozenset[str]:
    """Return the exact additional fields for one registered evidence kind."""
    if evidence_kind == "draft_approval":
        return _APPROVAL_FIELDS
    if evidence_kind == "deck_completion":
        return _COMPLETION_FIELDS
    return frozenset()


def _require_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str], field: str
) -> None:
    """Reject missing or unknown mapping fields with a stable typed error."""
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing {missing}")
    if unknown:
        details.append(f"unknown {unknown}")
    raise EvidenceContractError(f"{field} fields are invalid: {', '.join(details)}")


def _require_text(value: object, field: str) -> None:
    """Require one nonempty trimmed text value."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise EvidenceContractError(f"{field} must be a nonempty trimmed string")


def _require_digest(value: object, field: str) -> None:
    """Require one lowercase hexadecimal SHA-256 digest."""
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvidenceContractError(f"{field} must be a lowercase SHA-256 digest")


def _require_exact_int(value: object, expected: int, field: str) -> None:
    """Require an exact integer while rejecting Python booleans."""
    if type(value) is not int or value != expected:
        raise EvidenceContractError(f"{field} must be integer {expected}")


def _require_positive_int(value: object, field: str) -> None:
    """Require a positive integer while rejecting Python booleans."""
    if type(value) is not int or value <= 0:
        raise EvidenceContractError(f"{field} must be a positive integer")


def _require_rfc3339(value: object, field: str) -> None:
    """Require a timezone-aware RFC3339 timestamp."""
    _require_text(value, field)
    assert isinstance(value, str)
    if "T" not in value:
        raise EvidenceContractError(f"{field} must be RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceContractError(f"{field} must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise EvidenceContractError(f"{field} must include a timezone")


def _canonical_relative_path(value: object, field: str) -> str:
    """Validate one lexically canonical project-relative POSIX path."""
    _require_text(value, field)
    assert isinstance(value, str)
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise EvidenceContractError(f"{field} must be a canonical project-relative POSIX path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise EvidenceContractError(f"{field} must be a canonical project-relative POSIX path")
    return value


def _validate_subject_ids(value: object, deck_id: str) -> list[str]:
    """Validate a nonempty, ordered, de-duplicated subject ID list."""
    if not isinstance(value, list) or not value:
        raise EvidenceContractError("subject_ids must be a nonempty list")
    subject_ids: list[str] = []
    for index, subject_id in enumerate(value):
        _require_text(subject_id, f"subject_ids[{index}]")
        assert isinstance(subject_id, str)
        if subject_id in subject_ids:
            raise EvidenceContractError("subject_ids must contain unique identifiers")
        subject_ids.append(subject_id)
    return subject_ids


def _validate_artifact_refs(envelope: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Validate exact CAS references and return them in declared order."""
    value = envelope.get("artifact_refs")
    if not isinstance(value, list):
        raise EvidenceContractError("artifact_refs must be a list")
    refs: list[Mapping[str, Any]] = []
    seen_paths: set[str] = set()
    for index, raw_ref in enumerate(value):
        ref = _mapping(raw_ref, f"artifact_refs[{index}]")
        _require_exact_fields(ref, _ARTIFACT_REF_FIELDS, f"artifact_refs[{index}]")
        digest = ref.get("sha256")
        _require_digest(digest, f"artifact_refs[{index}].sha256")
        assert isinstance(digest, str)
        expected_cas = f".research/presentations/evidence/sha256/{digest[:2]}/{digest}"
        if ref.get("cas_path") != expected_cas:
            raise EvidenceContractError(f"artifact_refs[{index}].cas_path does not match SHA-256 CAS location")
        _require_text(ref.get("artifact_kind"), f"artifact_refs[{index}].artifact_kind")
        _require_text(ref.get("subject_id"), f"artifact_refs[{index}].subject_id")
        original_path = _canonical_relative_path(
            ref.get("original_path"), f"artifact_refs[{index}].original_path"
        )
        if original_path in seen_paths:
            raise EvidenceContractError("artifact_refs original_path values must be unique")
        seen_paths.add(original_path)
        refs.append(ref)
    return refs


def _validate_kind_refinement(
    envelope: Mapping[str, Any], evidence_kind: str, refs: list[Mapping[str, Any]]
) -> None:
    """Validate the closed kind-specific evidence policy."""
    deck_id = envelope["deck_id"]
    subject_ids = envelope["subject_ids"]
    assert isinstance(deck_id, str)
    assert isinstance(subject_ids, list)
    if evidence_kind == "draft_preview":
        if len(refs) < 2:
            raise EvidenceContractError("draft_preview artifact_refs require rendered slides and a contact sheet")
        rendered_refs = refs[:-1]
        if [ref["artifact_kind"] for ref in rendered_refs] != ["rendered_slide"] * len(rendered_refs):
            raise EvidenceContractError("draft_preview rendered artifact kinds are invalid")
        if refs[-1]["artifact_kind"] != "contact_sheet":
            raise EvidenceContractError("draft_preview requires a final contact_sheet artifact")
        if [ref["subject_id"] for ref in rendered_refs] != subject_ids:
            raise EvidenceContractError("draft_preview rendered artifacts must match ordered subject_ids")
        if refs[-1]["subject_id"] != deck_id:
            raise EvidenceContractError("draft_preview contact sheet must belong to the deck")
    elif evidence_kind == "draft_approval":
        if refs:
            raise EvidenceContractError("draft_approval cannot carry artifact_refs")
        _require_text(envelope.get("preview_evidence_id"), "preview_evidence_id")
        _require_digest(envelope.get("preview_evidence_sha256"), "preview_evidence_sha256")
        if envelope.get("decision") not in {"approved", "rejected"}:
            raise EvidenceContractError("decision must be approved or rejected")
        if envelope.get("approval_mode") not in {"interactive", "explicit_noninteractive"}:
            raise EvidenceContractError("approval_mode is invalid")
        _require_text(envelope.get("approved_by"), "approved_by")
    elif evidence_kind == "visual_review":
        if refs:
            raise EvidenceContractError("visual_review cannot carry artifact_refs")
    elif evidence_kind == "deck_completion":
        if envelope["subject_ids"] != [deck_id]:
            raise EvidenceContractError("deck_completion subject_ids must contain only deck_id")
        if len(refs) < 2 or refs[0]["artifact_kind"] != "final_pptx":
            raise EvidenceContractError("deck_completion requires a first final_pptx artifact")
        if any(ref["artifact_kind"] != "rendered_png" for ref in refs[1:]):
            raise EvidenceContractError("deck_completion requires rendered_png artifacts after final_pptx")
        if any(ref["subject_id"] != deck_id for ref in refs):
            raise EvidenceContractError("deck_completion artifacts must belong to the deck")
        _require_text(envelope.get("approval_evidence_id"), "approval_evidence_id")
        _require_digest(envelope.get("approval_evidence_sha256"), "approval_evidence_sha256")
        _require_text(envelope.get("visual_review_evidence_id"), "visual_review_evidence_id")
        _require_digest(
            envelope.get("visual_review_evidence_sha256"), "visual_review_evidence_sha256"
        )


def _relation_maps(relations: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Mapping[str, Any]]:
    """Validate explicit relation-map structure without inventing defaults."""
    result = _mapping(relations, "relations")
    for name, value in result.items():
        _mapping(value, f"relations[{name!r}]")
    return result


def _relation_record(
    relations: Mapping[str, Mapping[str, Any]], store_name: str, record_id: object, field: str
) -> Mapping[str, Any]:
    """Return one required authoritative relation record."""
    _require_text(record_id, field)
    assert isinstance(record_id, str)
    records = relations.get(store_name)
    if records is None:
        raise EvidenceContractError(f"relations must provide {store_name}")
    record = records.get(record_id)
    if record is None:
        raise EvidenceContractError(f"{field} does not resolve in {store_name}")
    return _mapping(record, f"relations[{store_name!r}][{record_id!r}]")


def _validate_visual_module(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]]
) -> None:
    """Validate a fresh or targeted module-replacement record explicitly."""
    retry = _validate_visual_module_intrinsic(record, relations)
    _relation_record(relations, "slides", record.get("slide_id"), "visual_modules.slide_id")
    if retry:
        _validate_module_retry(record, relations)


def _validate_visual_module_intrinsic(
    record: Mapping[str, Any],
    relations: Mapping[str, Mapping[str, Any]] | None = None,
) -> bool:
    """Validate intrinsic module shape and lifecycle without inventing relations."""
    actual_fields = set(record)
    retry = "revision_request_id" in record or "revision_kind" in record
    expected_fields = _MODULE_RETRY_FIELDS if retry else _MODULE_FIELDS
    if actual_fields - {"spec_sha256", "visual_spec_sha256"} != expected_fields:
        raise EvidenceContractError("visual_modules fields are not an exact public record schema")
    for field in ("id", "slide_id", "module_key", "module_type", "status", "created_at", "created_by"):
        _require_text(record.get(field), f"visual_modules.{field}")
    _require_positive_int(record.get("attempt"), "visual_modules.attempt")
    _validate_text_list(record.get("dependencies"), "visual_modules.dependencies")
    _validate_module_spec(record, relations)
    if retry:
        _validate_module_retry_intrinsic(record)
    else:
        _require_text(record.get("updated_at"), "visual_modules.updated_at")
        if record.get("supersedes_module_id") is not None:
            _require_text(record.get("supersedes_module_id"), "visual_modules.supersedes_module_id")
    return retry


def _validate_module_spec(
    record: Mapping[str, Any],
    relations: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    """Validate visual-spec path, digest aliases, and placeholder nullability."""
    path = record.get("visual_spec_path")
    canonical_digest = record.get("visual_spec_sha256")
    legacy_digest = record.get("spec_sha256")
    canonical_present = "visual_spec_sha256" in record
    legacy_present = "spec_sha256" in record
    if canonical_present and legacy_present and canonical_digest != legacy_digest:
        raise EvidenceContractError(
            "visual_modules.spec_sha256 conflicts with visual_spec_sha256"
        )
    if canonical_digest is not None:
        _require_digest(canonical_digest, "visual_modules.visual_spec_sha256")
    if legacy_digest is not None:
        _require_digest(legacy_digest, "visual_modules.spec_sha256")
    resolved_digest = canonical_digest if canonical_digest is not None else legacy_digest
    if path is None:
        if record.get("status") != "planned":
            raise EvidenceContractError("visual_modules visual_spec_path is required outside planned lifecycle")
        if resolved_digest is not None:
            raise EvidenceContractError("visual_modules visual_spec digest requires visual_spec_path")
    else:
        canonical_path = _canonical_relative_path(path, "visual_modules.visual_spec_path")
        if resolved_digest is None:
            raise EvidenceContractError("visual_modules visual_spec_path requires a digest alias")
        if relations is not None:
            specs = relations.get("visual_specs")
            if specs is None:
                raise EvidenceContractError("relations must provide visual_specs for visual_spec_path")
            spec = specs.get(canonical_path)
            if spec is None:
                raise EvidenceContractError("visual_modules visual_spec_path does not resolve")
            spec_record = _mapping(spec, "visual_specs record")
            if spec_record.get("sha256") != resolved_digest:
                raise EvidenceContractError("visual_modules visual spec digest does not match relation")
    for field in ("assignment_path", "artifact_manifest_path"):
        value = record.get(field)
        if value is None:
            if record.get("status") != "planned":
                raise EvidenceContractError(f"visual_modules.{field} is required outside planned lifecycle")
        else:
            _canonical_relative_path(value, f"visual_modules.{field}")


def _validate_module_retry(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]]
) -> None:
    """Validate the exact targeted module-retry replacement relation."""
    source = _relation_record(
        relations,
        "visual_modules",
        record.get("supersedes_module_id"),
        "visual_modules.supersedes_module_id",
    )
    for field in ("slide_id", "module_key", "module_type", "dependencies"):
        if record.get(field) != source.get(field):
            raise EvidenceContractError(f"visual_modules module retry must preserve source {field}")
    source_attempt = source.get("attempt")
    _require_positive_int(source_attempt, "source visual_modules.attempt")
    if record["attempt"] != source_attempt + 1:
        raise EvidenceContractError("visual_modules module retry attempt must increment source attempt")
    revision = _relation_record(
        relations,
        "revision_requests",
        record.get("revision_request_id"),
        "visual_modules.revision_request_id",
    )
    source_id = record["supersedes_module_id"]
    expected = {
        "subject_type": "module",
        "subject_id": source_id,
        "target_type": "module",
        "target_id": source_id,
        "revision_kind": "module_retry",
    }
    for field, value in expected.items():
        if revision.get(field) != value:
            raise EvidenceContractError(f"visual_modules.revision_request_id has wrong {field}")


def _validate_module_retry_intrinsic(record: Mapping[str, Any]) -> None:
    """Validate retry lifecycle fields before resolving authoritative relations."""
    if record.get("status") != "planned" or record.get("revision_kind") != "module_retry":
        raise EvidenceContractError(
            "visual_modules module retry must be planned with revision_kind module_retry"
        )
    if record.get("assignment_path") is not None or record.get("artifact_manifest_path") is not None:
        raise EvidenceContractError(
            "visual_modules module retry must reset assignment and artifact paths"
        )
    _require_text(
        record.get("supersedes_module_id"), "visual_modules.supersedes_module_id"
    )
    _require_text(
        record.get("revision_request_id"), "visual_modules.revision_request_id"
    )


def _validate_assignment(
    record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]]
) -> None:
    """Validate one exact persisted assignment without path-nullability reuse."""
    _require_exact_fields(record, _ASSIGNMENT_FIELDS, "assignments")
    for field in (
        "id",
        "deck_id",
        "slide_id",
        "module_id",
        "worker_id",
        "worker",
        "worker_type",
        "assigned_at",
        "created_at",
    ):
        _require_text(record.get(field), f"assignments.{field}")
    for field in ("assignment_path", "path", "relative_path"):
        _canonical_relative_path(record.get(field), f"assignments.{field}")
    if not (
        record["assignment_path"] == record["path"] == record["relative_path"]
    ):
        raise EvidenceContractError("assignments path aliases must be equal")
    _require_digest(record.get("spec_sha256"), "assignments.spec_sha256")
    if type(record.get("inputs_resolved")) is not bool:
        raise EvidenceContractError("assignments.inputs_resolved must be a bool")
    if record.get("blocker") is not None:
        _require_text(record.get("blocker"), "assignments.blocker")
    _validate_text_list(record.get("dependencies"), "assignments.dependencies")
    deck = _relation_record(relations, "decks", record.get("deck_id"), "assignments.deck_id")
    slide = _relation_record(relations, "slides", record.get("slide_id"), "assignments.slide_id")
    module = _relation_record(
        relations, "visual_modules", record.get("module_id"), "assignments.module_id"
    )
    if slide.get("deck_id") != deck.get("id") or module.get("slide_id") != slide.get("id"):
        raise EvidenceContractError("assignments relations do not describe one deck/slide/module chain")
    if module.get("assignment_path") != record["assignment_path"]:
        raise EvidenceContractError("assignments assignment_path does not match module relation")
    module_digest = module.get("visual_spec_sha256", module.get("spec_sha256"))
    if module_digest != record["spec_sha256"]:
        raise EvidenceContractError("assignments spec_sha256 does not match module relation")


def _validate_slide(record: Mapping[str, Any], relations: Mapping[str, Mapping[str, Any]]) -> None:
    """Validate the public fresh or targeted slide-replacement schema."""
    retry = _validate_slide_intrinsic(record)
    _relation_record(relations, "decks", record.get("deck_id"), "slides.deck_id")
    if retry:
        source = _relation_record(
            relations, "slides", record.get("supersedes_slide_id"), "slides.supersedes_slide_id"
        )
        if source.get("deck_id") != record["deck_id"] or source.get("plan_slide_id") != record["plan_slide_id"]:
            raise EvidenceContractError("slides retry must preserve source deck and plan slide")
        _require_positive_int(source.get("attempt"), "source slides.attempt")
        if record["attempt"] != source["attempt"] + 1:
            raise EvidenceContractError("slides retry attempt must increment source attempt")


def _validate_slide_intrinsic(record: Mapping[str, Any]) -> bool:
    """Validate intrinsic slide shape and lifecycle without relation context."""
    retry = "revision_request_id" in record or "revision_kind" in record
    expected_fields = _SLIDE_RETRY_FIELDS if retry else _SLIDE_FIELDS
    _require_exact_fields(record, expected_fields, "slides")
    for field in ("id", "deck_id", "plan_slide_id", "title", "status", "created_at", "created_by"):
        _require_text(record.get(field), f"slides.{field}")
    _require_positive_int(record.get("attempt"), "slides.attempt")
    path = record.get("slide_spec_path")
    if path is None:
        if record.get("status") != "planned":
            raise EvidenceContractError("slides.slide_spec_path is required outside planned lifecycle")
        if record.get("slide_spec_sha256") is not None:
            raise EvidenceContractError("slides.slide_spec_sha256 requires slide_spec_path")
    else:
        _canonical_relative_path(path, "slides.slide_spec_path")
        _require_digest(record.get("slide_spec_sha256"), "slides.slide_spec_sha256")
    if retry:
        if record.get("status") != "planned" or record.get("revision_kind") != "slide_retry":
            raise EvidenceContractError("slides retry must be planned with revision_kind slide_retry")
        _require_text(record.get("supersedes_slide_id"), "slides.supersedes_slide_id")
        _require_text(record.get("revision_request_id"), "slides.revision_request_id")
    else:
        _require_text(record.get("updated_at"), "slides.updated_at")
    return retry


def _validate_text_list(value: object, field: str) -> None:
    """Validate a de-duplicated list of trimmed textual identifiers."""
    if not isinstance(value, list):
        raise EvidenceContractError(f"{field} must be a list")
    values: set[str] = set()
    for index, item in enumerate(value):
        _require_text(item, f"{field}[{index}]")
        assert isinstance(item, str)
        if item in values:
            raise EvidenceContractError(f"{field} must not contain duplicate identifiers")
        values.add(item)
