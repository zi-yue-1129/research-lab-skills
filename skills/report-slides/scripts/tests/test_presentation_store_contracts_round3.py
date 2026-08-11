"""Exact schema-zero/one and schema-two store-record contract matrix."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from presentation_evidence_contracts import EvidenceContractError, validate_store_record


_DIGEST = "a" * 64
_NOW = "2026-08-09T00:00:00Z"


def _records() -> dict[str, dict[str, Any]]:
    """Return exact public-producer records for every authoritative store."""
    return {
        "decks": {
            "id": "deck-1", "title": "Deck", "status": "planning",
            "plan_version": 0, "current_plan_id": None,
            "approved_plan_version": None, "approved_plan_sha256": None,
            "approval_id": None, "approved_by": None, "approved_at": None,
            "approval_mode": None, "draft_preview_id": None,
            "draft_approval_id": None, "created_at": _NOW, "updated_at": _NOW,
            "created_by": "user",
        },
        "plans": {
            "id": "plan-1", "deck_id": "deck-1", "version": 1,
            "plan_path": "plans/plan.yaml", "path": "plans/plan.yaml",
            "sha256": _DIGEST, "plan_sha256": _DIGEST,
            "authored_by": "planner", "created_by": "planner",
            "supersedes_plan_id": None, "created_at": _NOW,
        },
        "slides": {
            "id": "slide-1", "deck_id": "deck-1", "plan_slide_id": "slide-01",
            "title": "Slide", "status": "planned", "created_at": _NOW,
            "updated_at": _NOW, "created_by": "user",
            "approved_takeaway_sha256": None, "approved_evidence_sha256": None,
            "slide_spec_path": None, "slide_spec_sha256": None, "attempt": 1,
        },
        "visual_modules": {
            "id": "module-1", "slide_id": "slide-1", "module_key": "hero",
            "module_type": "architecture", "dependencies": [], "status": "planned",
            "visual_spec_path": None, "assignment_path": None,
            "artifact_manifest_path": None, "attempt": 1,
            "supersedes_module_id": None, "created_at": _NOW,
            "updated_at": _NOW, "created_by": "user",
        },
        "assignments": {
            "id": "assignment-1", "deck_id": "deck-1", "slide_id": "slide-1",
            "module_id": "module-1", "assignment_path": "work/assignment.yaml",
            "path": "work/assignment.yaml", "relative_path": "work/assignment.yaml",
            "worker_id": "worker", "worker": "worker", "worker_type": "diagram",
            "dependencies": [], "spec_sha256": _DIGEST, "inputs_resolved": True,
            "blocker": None, "assigned_at": _NOW, "created_at": _NOW,
        },
        "artifacts": {
            "id": "artifact-1", "deck_id": "deck-1", "slide_id": None,
            "module_id": None, "artifact_kind": "review-sheet", "kind": "review-sheet",
            "path": "renders/review.png", "relative_path": "renders/review.png",
            "sha256": _DIGEST, "producer_id": "renderer", "produced_by": "renderer",
            "plan_version": 1, "plan_sha256": _DIGEST,
            "source_paths": ["renders/slide.png"], "source_sha256": _DIGEST,
            "created_at": _NOW,
        },
        "revision_requests": {
            "id": "revision-1", "subject_type": "slide", "subject_id": "slide-1",
            "requested_by": "reviewer", "instructions": "Revise labels.",
            "supersedes": None, "created_at": _NOW,
        },
    }


def _relations() -> dict[str, dict[str, Any]]:
    """Return exact id-keyed relation maps for the producer records."""
    records = _records()
    records["visual_modules"]["assignment_path"] = "work/assignment.yaml"
    records["visual_modules"]["visual_spec_path"] = "specs/module.yaml"
    records["visual_modules"]["visual_spec_sha256"] = _DIGEST
    relations = {name: {record["id"]: record} for name, record in records.items()}
    relations["visual_specs"] = {"specs/module.yaml": {"sha256": _DIGEST}}
    return relations


@pytest.mark.parametrize("store_name", sorted(_records()))
@pytest.mark.parametrize("legacy", [False, True])
def test_real_public_store_records_pass_exact_contracts(
    store_name: str, legacy: bool
) -> None:
    """Every public producer shape is valid as target or full legacy input."""
    record = _records()[store_name]

    assert validate_store_record(
        store_name, record, relations=_relations(), legacy=legacy
    ) == record


_REQUIRED_FIELDS = {
    "decks": {"id", "title", "status", "created_by"},
    "plans": {"id", "deck_id", "version", "plan_sha256"},
    "slides": {"id", "deck_id", "plan_slide_id", "title", "status"},
    "visual_modules": {
        "id", "slide_id", "module_key", "module_type", "dependencies", "status",
    },
    "assignments": set(_records()["assignments"]),
    "artifacts": {
        "id", "deck_id", "slide_id", "module_id", "artifact_kind", "kind",
        "path", "relative_path", "sha256", "producer_id", "produced_by", "created_at",
    },
    "revision_requests": set(_records()["revision_requests"]),
}
_WRONG_FIELD = {
    "decks": "title", "plans": "version", "slides": "attempt",
    "visual_modules": "dependencies", "assignments": "inputs_resolved",
    "artifacts": "sha256", "revision_requests": "requested_by",
}
_WRONG_VALUE: dict[str, object] = {
    store_name: ("true" if store_name == "assignments" else True)
    for store_name in _WRONG_FIELD
}


@pytest.mark.parametrize(
    ("store_name", "field"),
    [
        (store_name, field)
        for store_name, fields in sorted(_REQUIRED_FIELDS.items())
        for field in sorted(fields)
    ],
)
def test_legacy_contract_rejects_missing_required_fields(
    store_name: str, field: str
) -> None:
    """Legacy mode cannot turn a partial known-field map into a valid record."""
    record = deepcopy(_records()[store_name])
    record.pop(field)

    with pytest.raises(EvidenceContractError, match="missing|required|fields"):
        validate_store_record(store_name, record, relations=_relations(), legacy=True)


@pytest.mark.parametrize("store_name", sorted(_records()))
def test_legacy_contract_rejects_known_field_boolean_or_wrong_type(
    store_name: str,
) -> None:
    """Known fields reject booleans and wrong scalar/container types."""
    record = deepcopy(_records()[store_name])
    record[_WRONG_FIELD[store_name]] = _WRONG_VALUE[store_name]

    with pytest.raises(EvidenceContractError, match="must|invalid|type|integer|digest"):
        validate_store_record(store_name, record, relations=_relations(), legacy=True)


@pytest.mark.parametrize(
    ("store_name", "field"),
    [("decks", "status"), ("slides", "status"), ("visual_modules", "status")],
)
def test_store_contract_rejects_invalid_lifecycle_status(
    store_name: str, field: str
) -> None:
    """Lifecycle fields accept only their documented state-machine enums."""
    record = deepcopy(_records()[store_name])
    record[field] = "forged-complete"

    with pytest.raises(EvidenceContractError, match="status|lifecycle|invalid"):
        validate_store_record(store_name, record, relations=_relations(), legacy=True)


@pytest.mark.parametrize("store_name", sorted(_records()))
def test_store_contract_rejects_unknown_alias_field(store_name: str) -> None:
    """No store accepts an unregistered alias or authorization field."""
    record = deepcopy(_records()[store_name])
    record["forged_authorization"] = "yes"

    with pytest.raises(EvidenceContractError, match="unknown|fields"):
        validate_store_record(store_name, record, relations=_relations(), legacy=True)


@pytest.mark.parametrize(
    ("store_name", "field", "forged"),
    [
        ("plans", "deck_id", "deck-other"),
        ("slides", "deck_id", "deck-other"),
        ("visual_modules", "slide_id", "slide-other"),
        ("assignments", "module_id", "module-other"),
        ("artifacts", "deck_id", "deck-other"),
        ("revision_requests", "subject_id", "slide-other"),
    ],
)
def test_store_contract_rejects_unresolved_or_cross_owner_relations(
    store_name: str, field: str, forged: str
) -> None:
    """Ownership identities must resolve through the supplied state snapshot."""
    record = deepcopy(_records()[store_name])
    record[field] = forged

    with pytest.raises(EvidenceContractError, match="relation|resolve|owner|deck|slide|module"):
        validate_store_record(store_name, record, relations=_relations(), legacy=True)


@pytest.mark.parametrize(
    "record",
    [
        {"id": "deck-1", "title": True, "status": "planning", "created_by": "user"},
        {
            "id": "slide-1", "deck_id": "deck-1", "plan_slide_id": "slide-01",
            "title": "Slide", "status": "passed", "attempt": True,
        },
    ],
)
def test_sol_deck_and_slide_counterexamples_fail_closed(
    record: dict[str, Any]
) -> None:
    """The exact reviewer probes cannot pass through legacy compatibility."""
    store_name = "decks" if record["id"].startswith("deck") else "slides"

    with pytest.raises(EvidenceContractError):
        validate_store_record(store_name, record, relations=_relations(), legacy=True)


@pytest.mark.parametrize(
    ("store_name", "field", "value"),
    [
        ("decks", "plan_version", True),
        ("plans", "created_at", True),
        ("slides", "created_at", True),
        ("visual_modules", "attempt", True),
        ("assignments", "blocker", True),
        ("artifacts", "source_paths", True),
        ("revision_requests", "supersedes", True),
    ],
)
def test_store_contract_rejects_wrong_optional_field_types(
    store_name: str, field: str, value: object
) -> None:
    """Every store rejects a known optional field with the wrong exact type."""
    record = deepcopy(_records()[store_name])
    record[field] = value

    with pytest.raises(EvidenceContractError, match="must|invalid|integer|list"):
        validate_store_record(store_name, record, relations=_relations(), legacy=True)


@pytest.mark.parametrize(
    ("store_name", "first", "second"),
    [
        ("plans", "path", "plans/other.yaml"),
        ("assignments", "worker", "other-worker"),
        ("artifacts", "kind", "other-kind"),
        ("visual_modules", "spec_sha256", "b" * 64),
    ],
)
def test_store_contract_rejects_mismatched_aliases(
    store_name: str, first: str, second: str
) -> None:
    """Canonical aliases must be present in an exact matching pair."""
    record = deepcopy(_records()[store_name])
    if store_name == "visual_modules":
        record["visual_spec_sha256"] = _DIGEST
    record[first] = second

    with pytest.raises(EvidenceContractError, match="alias|match|digest"):
        validate_store_record(store_name, record, relations=_relations(), legacy=True)


@pytest.mark.parametrize(
    ("store_name", "field", "cross_id"),
    [
        ("decks", "current_plan_id", "plan-cross"),
        ("slides", "supersedes_slide_id", "slide-cross"),
        ("visual_modules", "dependencies", ["module-cross"]),
        ("artifacts", "slide_id", "slide-cross"),
    ],
)
def test_store_contract_rejects_resolved_cross_owner_relations(
    store_name: str, field: str, cross_id: object
) -> None:
    """Resolved relations still reject a different deck or slide owner."""
    relations = _relations()
    relations["decks"]["deck-cross"] = {
        "id": "deck-cross", "title": "Cross", "status": "planning",
        "created_by": "test",
    }
    relations["slides"]["slide-cross"] = {
        "id": "slide-cross", "deck_id": "deck-cross",
        "plan_slide_id": "slide-cross", "title": "Cross", "status": "planned",
    }
    relations["visual_modules"]["module-cross"] = {
        "id": "module-cross", "slide_id": "slide-cross", "module_key": "cross",
        "module_type": "architecture", "dependencies": [], "status": "planned",
    }
    relations["plans"]["plan-cross"] = {
        "id": "plan-cross", "deck_id": "deck-cross", "version": 1,
        "plan_sha256": _DIGEST,
    }
    record = deepcopy(_records()[store_name])
    record[field] = cross_id

    with pytest.raises(EvidenceContractError, match="owner|deck|slide|relation"):
        validate_store_record(store_name, record, relations=relations, legacy=True)
