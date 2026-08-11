"""Exact refinements for presentation stores outside production-unit records."""

from __future__ import annotations

from typing import Any, Mapping


_FIELDS = {
    "slides": frozenset(
        {"id", "deck_id", "plan_slide_id", "title", "status", "created_at",
         "updated_at", "created_by", "approved_takeaway_sha256",
         "approved_evidence_sha256", "slide_spec_path", "slide_spec_sha256",
         "attempt", "supersedes_slide_id", "revision_request_id", "revision_kind"}
    ),
    "visual_modules": frozenset(
        {"id", "slide_id", "module_key", "module_type", "dependencies", "status",
         "visual_spec_path", "visual_spec_sha256", "spec_sha256", "assignment_path",
         "artifact_manifest_path", "attempt", "supersedes_module_id", "created_at",
         "updated_at", "created_by", "revision_request_id", "revision_kind"}
    ),
    "assignments": frozenset(
        {"id", "deck_id", "slide_id", "module_id", "assignment_path", "path",
         "relative_path", "worker_id", "worker", "worker_type", "dependencies",
         "spec_sha256", "inputs_resolved", "blocker", "assigned_at", "created_at"}
    ),
    "decks": frozenset(
        {
            "id", "title", "status", "plan_version", "current_plan_id",
            "approved_plan_version", "approved_plan_sha256", "approval_id",
            "approved_by", "approved_at", "approval_mode", "draft_preview_id",
            "draft_approval_id", "draft_preview_evidence_id",
            "draft_approval_evidence_id", "completion_evidence_id",
            "required_plan_revision_id", "created_at", "updated_at", "created_by",
            "identity_verifiable",
        }
    ),
    "plans": frozenset(
        {"id", "deck_id", "version", "plan_version", "plan_sha256", "sha256",
         "plan_path", "path", "created_at", "created_by", "authored_by"}
    ),
    "artifacts": frozenset(
        {"id", "deck_id", "slide_id", "module_id", "artifact_kind", "kind",
         "path", "relative_path", "sha256", "producer_id", "produced_by",
         "plan_version", "plan_sha256", "slide_record_id", "attempt",
         "source_paths", "source_sha256", "created_at"}
        | {"rendered_slide_paths"}
    ),
    "revision_requests": frozenset(
        {"id", "subject_type", "subject_id", "requested_by", "instructions",
         "supersedes", "created_at"}
    ),
}


def validate_additional_store_record(
    store_name: str, record: Mapping[str, Any]
) -> None:
    """Validate a closed record shape and intrinsic scalar identities.

    Args:
        store_name: Authoritative presentation store name.
        record: Parsed record candidate.

    Raises:
        ValueError: If the store is unsupported or the record is not exact.
    """
    allowed = _FIELDS.get(store_name)
    if allowed is None:
        raise ValueError(f"{store_name} has no exact schema-v2 record contract")
    unknown = sorted(set(record) - allowed)
    if unknown:
        raise ValueError(f"{store_name} fields are invalid: unknown {unknown}")
    record_id = record.get("id")
    if not isinstance(record_id, str) or not record_id or record_id != record_id.strip():
        raise ValueError(f"{store_name}.id must be a nonempty trimmed string")
    for field in ("version", "plan_version", "approved_plan_version", "attempt"):
        value = record.get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{store_name}.{field} must be a nonnegative integer")
