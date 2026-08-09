"""Tests for the schema-v2 presentation evidence contract kernel."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from presentation_contracts import contract_sha256
from presentation_evidence_contracts import (
    EVIDENCE_SCHEMA_VERSION,
    EvidenceContractError,
    artifact_policy_for_event,
    envelope_sha256,
    legacy_nullable_path_fields,
    validate_deck_evidence_pointers,
    validate_envelope,
    validate_store_record,
)


_DIGEST = "a" * 64
_SECOND_DIGEST = "b" * 64


def _relations() -> dict[str, dict[str, Any]]:
    """Return authoritative relations for one deck workflow snapshot."""
    return {
        "decks": {"deck-1": {"id": "deck-1"}},
        "slides": {
            "sld-1": {
                "id": "sld-1",
                "deck_id": "deck-1",
                "status": "passed",
                "attempt": 1,
            }
        },
        "visual_modules": {
            "mod-source": {
                "id": "mod-source",
                "slide_id": "sld-1",
                "module_key": "hero",
                "module_type": "architecture",
                "dependencies": [],
                "status": "revision_required",
                "visual_spec_path": "contracts/hero.yaml",
                "visual_spec_sha256": _DIGEST,
                "assignment_path": "contracts/assignment.yaml",
                "artifact_manifest_path": "artifacts/hero.yaml",
                "attempt": 1,
                "supersedes_module_id": None,
                "created_at": "2026-08-09T00:00:00Z",
                "updated_at": "2026-08-09T00:00:00Z",
                "created_by": "workflow",
            }
        },
        "revision_requests": {
            "rev-1": {
                "id": "rev-1",
                "deck_id": "deck-1",
                "subject_type": "module",
                "subject_id": "mod-source",
                "target_type": "module",
                "target_id": "mod-source",
                "revision_kind": "module_retry",
            }
        },
        "visual_specs": {"contracts/hero.yaml": {"sha256": _DIGEST}},
    }


def _real_module_retry_record() -> dict[str, Any]:
    """Return the exact module-replacement shape emitted by the workflow."""
    return {
        "id": "mod-retry",
        "slide_id": "sld-1",
        "module_key": "hero",
        "module_type": "architecture",
        "dependencies": [],
        "status": "planned",
        "visual_spec_path": "contracts/hero.yaml",
        "visual_spec_sha256": _DIGEST,
        "assignment_path": None,
        "artifact_manifest_path": None,
        "attempt": 2,
        "supersedes_module_id": "mod-source",
        "created_at": "2026-08-09T00:01:00Z",
        "created_by": "workflow",
        "revision_request_id": "rev-1",
        "revision_kind": "module_retry",
    }


def _real_assignment_record() -> dict[str, Any]:
    """Return the exact assignment record emitted by the workflow."""
    return {
        "id": "asn-1",
        "deck_id": "deck-1",
        "slide_id": "sld-1",
        "module_id": "mod-source",
        "assignment_path": "contracts/assignment.yaml",
        "path": "contracts/assignment.yaml",
        "relative_path": "contracts/assignment.yaml",
        "worker_id": "worker-a",
        "worker": "worker-a",
        "worker_type": "architecture",
        "dependencies": [],
        "spec_sha256": _DIGEST,
        "inputs_resolved": True,
        "blocker": None,
        "assigned_at": "2026-08-09T00:00:00Z",
        "created_at": "2026-08-09T00:00:00Z",
    }


def _public_planned_module_record() -> dict[str, Any]:
    """Return the exact planned module shape emitted by the public constructor."""
    record = deepcopy(_relations()["visual_modules"]["mod-source"])
    record.update(
        {
            "status": "planned",
            "visual_spec_path": None,
            "assignment_path": None,
            "artifact_manifest_path": None,
        }
    )
    record.pop("visual_spec_sha256")
    return record


def _artifact_ref(
    digest: str,
    artifact_kind: str,
    subject_id: str,
    original_path: str,
) -> dict[str, str]:
    """Return one exact content-addressed artifact reference."""
    return {
        "sha256": digest,
        "cas_path": f".research/presentations/evidence/sha256/{digest[:2]}/{digest}",
        "artifact_kind": artifact_kind,
        "subject_id": subject_id,
        "original_path": original_path,
    }


def _envelope(evidence_kind: str = "draft_preview") -> dict[str, Any]:
    """Return one valid schema-v2 envelope for ``evidence_kind``."""
    envelope: dict[str, Any] = {
        "id": f"evidence-{evidence_kind}",
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_kind": evidence_kind,
        "deck_id": "deck-1",
        "plan_id": "plan-1",
        "plan_version": 1,
        "plan_sha256": _DIGEST,
        "subject_ids": ["sld-1"],
        "producer_id": "renderer",
        "artifact_refs": [],
        "source_event_id": f"event-{evidence_kind}",
        "created_at": "2026-08-09T00:00:00Z",
        "availability": "available",
    }
    if evidence_kind == "draft_preview":
        envelope["artifact_refs"] = [
            _artifact_ref(_DIGEST, "rendered_slide", "sld-1", "renders/slide-01.png"),
            _artifact_ref(_SECOND_DIGEST, "contact_sheet", "deck-1", "renders/contact.png"),
        ]
    elif evidence_kind == "draft_approval":
        envelope.update(
            {
                "preview_evidence_id": "evidence-draft_preview",
                "preview_evidence_sha256": _DIGEST,
                "decision": "approved",
                "approval_mode": "interactive",
                "approved_by": "reviewer-a",
            }
        )
    elif evidence_kind == "deck_completion":
        envelope["subject_ids"] = ["deck-1"]
        envelope["artifact_refs"] = [
            _artifact_ref(_DIGEST, "final_pptx", "deck-1", "out/deck.pptx"),
            _artifact_ref(_SECOND_DIGEST, "rendered_png", "deck-1", "renders/slide-01.png"),
        ]
        envelope.update(
            {
                "approval_evidence_id": "evidence-draft_approval",
                "approval_evidence_sha256": _DIGEST,
                "visual_review_evidence_id": "evidence-visual_review",
                "visual_review_evidence_sha256": _SECOND_DIGEST,
            }
        )
    elif evidence_kind == "visual_review":
        envelope["subject_ids"] = ["deck-1"]
    else:
        raise ValueError(f"unsupported test evidence kind: {evidence_kind}")
    envelope["evidence_sha256"] = envelope_sha256(envelope)
    return envelope


def test_envelope_sha256_excludes_the_declared_digest() -> None:
    """The envelope digest is canonical and excludes only its self-reference."""
    envelope = _envelope()
    expected = contract_sha256(
        {key: value for key, value in envelope.items() if key != "evidence_sha256"}
    )

    assert envelope_sha256(envelope) == expected


def test_validate_envelope_accepts_exact_preview_base_and_refinement() -> None:
    """A complete preview envelope is copied without mutation."""
    envelope = _envelope()

    result = validate_envelope(envelope)

    assert result == envelope
    assert result is not envelope
    assert result["artifact_refs"] is not envelope["artifact_refs"]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("unknown", "unknown"),
        ("bool_version", "schema_version"),
        ("bool_plan_version", "plan_version"),
        ("bad_digest", "evidence_sha256"),
        ("bad_cas", "cas_path"),
    ],
)
def test_validate_envelope_fails_closed_for_invalid_base_contract(
    mutation: str,
    expected: str,
) -> None:
    """Base envelope fields reject unknown, bool, and noncanonical values."""
    envelope = _envelope()
    if mutation == "unknown":
        envelope["unexpected"] = "value"
    elif mutation == "bool_version":
        envelope["schema_version"] = True
    elif mutation == "bool_plan_version":
        envelope["plan_version"] = True
    elif mutation == "bad_digest":
        envelope["evidence_sha256"] = "0" * 64
    else:
        envelope["artifact_refs"][0]["cas_path"] = "evidence/not-cas"
    if mutation != "bad_digest":
        envelope["evidence_sha256"] = envelope_sha256(envelope)

    with pytest.raises(EvidenceContractError, match=expected):
        validate_envelope(envelope)


@pytest.mark.parametrize(
    ("evidence_kind", "missing_field", "expected"),
    [
        ("draft_preview", "artifact_refs", "artifact_refs"),
        ("draft_approval", "preview_evidence_id", "preview_evidence_id"),
        ("deck_completion", "approval_evidence_id", "approval_evidence_id"),
    ],
)
def test_validate_envelope_requires_exact_kind_refinements(
    evidence_kind: str,
    missing_field: str,
    expected: str,
) -> None:
    """Each registered evidence kind has an exact additional schema."""
    envelope = _envelope(evidence_kind)
    envelope.pop(missing_field)
    envelope["evidence_sha256"] = envelope_sha256(envelope)

    with pytest.raises(EvidenceContractError, match=expected):
        validate_envelope(envelope)


def test_artifact_policy_is_registered_and_closed() -> None:
    """Only event kinds with defined artifact contracts receive a policy."""
    assert artifact_policy_for_event("draft_preview") == "draft_preview"
    assert artifact_policy_for_event("deck_completion") == "deck_completion"
    assert artifact_policy_for_event("review_result") == "none"


def test_module_retry_accepts_equal_digest_aliases_from_real_workflow() -> None:
    """Module retries accept equal legacy and canonical visual-spec aliases."""
    record = _real_module_retry_record()
    record["spec_sha256"] = record["visual_spec_sha256"]

    result = validate_store_record("visual_modules", record, relations=_relations())

    assert result == record
    assert result is not record


def test_module_retry_rejects_conflicting_digest_aliases() -> None:
    """A canonical visual-spec digest cannot conflict with the legacy alias."""
    record = _real_module_retry_record()
    record["spec_sha256"] = _SECOND_DIGEST

    with pytest.raises(EvidenceContractError, match="spec_sha256"):
        validate_store_record("visual_modules", record, relations=_relations())


@pytest.mark.parametrize(
    ("canonical_digest", "legacy_digest"),
    [
        (None, _DIGEST),
        (_DIGEST, None),
        (True, True),
        (7, 7),
        (None, None),
    ],
)
def test_module_retry_rejects_invalid_present_digest_alias_pairs(
    canonical_digest: object,
    legacy_digest: object,
) -> None:
    """Present aliases must be equal valid digests for a non-null spec path."""
    record = _real_module_retry_record()
    record["visual_spec_sha256"] = canonical_digest
    record["spec_sha256"] = legacy_digest

    with pytest.raises(EvidenceContractError, match="spec_sha256|digest"):
        validate_store_record("visual_modules", record, relations=_relations())


@pytest.mark.parametrize(
    "mutation",
    [
        {"visual_spec_sha256": _DIGEST},
        {"visual_spec_sha256": None, "spec_sha256": _DIGEST},
        {"unexpected_nullable_shape": True},
    ],
)
def test_nullable_bridge_rejects_invalid_planned_module_contracts(
    mutation: dict[str, Any],
) -> None:
    """The nullable bridge rejects invalid aliases and non-public record shapes."""
    record = _public_planned_module_record()
    record.update(mutation)

    with pytest.raises(EvidenceContractError, match="visual_modules|spec|schema"):
        legacy_nullable_path_fields("visual_modules", record)


def test_nullable_bridge_accepts_exact_public_planned_module_shape() -> None:
    """The nullable bridge accepts the unmodified public module constructor shape."""
    assert legacy_nullable_path_fields(
        "visual_modules", _public_planned_module_record()
    ) == {"visual_spec_path", "assignment_path", "artifact_manifest_path"}


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("attempt", 1, "attempt"),
        ("supersedes_module_id", "mod-other", "supersedes_module_id"),
        ("revision_request_id", "rev-other", "revision_request_id"),
    ],
)
def test_module_retry_requires_source_attempt_and_revision_relation(
    field: str,
    value: str | int,
    expected: str,
) -> None:
    """A replacement must bind its exact source and revision request."""
    record = _real_module_retry_record()
    record[field] = value

    with pytest.raises(EvidenceContractError, match=expected):
        validate_store_record("visual_modules", record, relations=_relations())


def test_assignment_cannot_spoof_module_nullable_paths() -> None:
    """Assignment fields cannot borrow module planned-record nullability."""
    record = _real_assignment_record()
    record.update(
        {"status": "planned", "module_key": "hero", "assignment_path": None}
    )

    with pytest.raises(EvidenceContractError, match="assignments"):
        validate_store_record("assignments", record, relations=_relations())


def test_unregistered_store_record_schema_fails_closed() -> None:
    """A store without an exact v2 record schema cannot use generic validation."""
    record = {"id": "deck-1", "status": "planning"}

    with pytest.raises(EvidenceContractError, match="decks"):
        validate_store_record("decks", record, relations=_relations())


def test_validate_deck_evidence_pointers_requires_current_compatible_chain() -> None:
    """A completed deck requires owned, available preview, approval, and completion evidence."""
    preview = _envelope("draft_preview")
    approval = _envelope("draft_approval")
    approval["preview_evidence_sha256"] = preview["evidence_sha256"]
    approval["evidence_sha256"] = envelope_sha256(approval)
    completion = _envelope("deck_completion")
    completion["approval_evidence_sha256"] = approval["evidence_sha256"]
    completion["evidence_sha256"] = envelope_sha256(completion)
    visual_review = _envelope("visual_review")
    visual_review["evidence_sha256"] = envelope_sha256(visual_review)
    completion["visual_review_evidence_sha256"] = visual_review["evidence_sha256"]
    completion["evidence_sha256"] = envelope_sha256(completion)
    evidence = {
        preview["id"]: preview,
        approval["id"]: approval,
        completion["id"]: completion,
        visual_review["id"]: visual_review,
    }
    deck = {
        "id": "deck-1",
        "status": "completed",
        "draft_preview_evidence_id": preview["id"],
        "draft_approval_evidence_id": approval["id"],
        "completion_evidence_id": completion["id"],
    }

    validate_deck_evidence_pointers(deck, evidence)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("wrong_owner", "deck_id"),
        ("wrong_kind", "draft_preview_evidence_id"),
        ("unavailable", "availability"),
        ("noncompleted_pointer", "completion_evidence_id"),
    ],
)
def test_validate_deck_evidence_pointers_rejects_invalid_current_evidence(
    mutation: str,
    expected: str,
) -> None:
    """Pointers fail closed for wrong ownership, kind, availability, and lifecycle."""
    preview = _envelope("draft_preview")
    evidence = {preview["id"]: preview}
    deck = {
        "id": "deck-1",
        "status": "producing",
        "draft_preview_evidence_id": preview["id"],
        "draft_approval_evidence_id": None,
        "completion_evidence_id": None,
    }
    if mutation == "wrong_owner":
        preview["deck_id"] = "deck-other"
        preview["artifact_refs"][-1]["subject_id"] = "deck-other"
    elif mutation == "wrong_kind":
        preview = _envelope("draft_approval")
        preview["id"] = "evidence-draft_preview"
        preview["evidence_sha256"] = envelope_sha256(preview)
        evidence = {preview["id"]: preview}
    elif mutation == "unavailable":
        preview["availability"] = "historical_unavailable"
    else:
        deck["completion_evidence_id"] = preview["id"]
    if mutation != "wrong_kind":
        preview["evidence_sha256"] = envelope_sha256(preview)

    with pytest.raises(EvidenceContractError, match=expected):
        validate_deck_evidence_pointers(deck, deepcopy(evidence))
