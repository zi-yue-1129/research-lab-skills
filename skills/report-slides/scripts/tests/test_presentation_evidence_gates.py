"""Behavioral tests for schema-v2 current-evidence gate authorization.

Every fixture here is a real on-disk project produced by the schema-v2
workflow producers.  The gates under test must authorize preview, approval,
and completion exclusively from current deck evidence pointers and verified
content-addressed bytes, with no schema-v1 event fallback.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml

from presentation_evidence_cas import CasObject, cas_relative_path
from presentation_evidence_contracts import envelope_sha256
from presentation_evidence_gates import (
    _cas_blockers,
    assert_current_evidence,
    assert_draft_approvable,
)
from presentation_evidence_snapshot import (
    EvidenceCasIntegrityError,
    EvidenceSnapshot,
    build_snapshot,
)
from presentation_gates import CompletionGateError, DraftGateError, assert_deck_completable
from presentation_workflow import approve_draft
from test_presentation_evidence_workflow import _approval_ready_project
from test_presentation_workflow import _complete_fixture


_POINTER_FIELDS = {
    "draft_preview": "draft_preview_evidence_id",
    "draft_approval": "draft_approval_evidence_id",
    "deck_completion": "completion_evidence_id",
}


def _state_path(project: Path, name: str) -> Path:
    """Return one presentation state document path."""
    return project / ".research/presentations/state" / name


def _read_state(project: Path, name: str) -> dict[str, Any]:
    """Parse one presentation state document."""
    return yaml.safe_load(_state_path(project, name).read_text(encoding="utf-8"))


def _write_state(project: Path, name: str, document: dict[str, Any]) -> None:
    """Persist one presentation state document."""
    _state_path(project, name).write_text(yaml.safe_dump(document), encoding="utf-8")


def _update_deck(project: Path, deck_id: str, **fields: Any) -> None:
    """Apply exact deck-record field updates to persisted state."""
    document = _read_state(project, "decks.yaml")
    document["decks"][deck_id].update(fields)
    _write_state(project, "decks.yaml", document)


def _deck(project: Path, deck_id: str) -> dict[str, Any]:
    """Return one persisted deck record."""
    return _read_state(project, "decks.yaml")["decks"][deck_id]


def _evidence(project: Path) -> dict[str, Any]:
    """Return the persisted evidence store records."""
    path = project / ".research/presentations/state/evidence.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["evidence"]


def _write_evidence(project: Path, records: dict[str, Any]) -> None:
    """Persist an amended evidence store while keeping its schema marker."""
    path = project / ".research/presentations/state/evidence.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["evidence"] = records
    path.write_text(yaml.safe_dump(document), encoding="utf-8")


def _reasons(blockers: list[dict[str, Any]]) -> set[str]:
    """Return the reason vocabulary of one structured blocker list."""
    return {str(blocker.get("reason")) for blocker in blockers}


def _overwrite_cas_object(project: Path, digest: str, content: bytes) -> None:
    """Replace immutable CAS bytes to simulate an offline tamper."""
    path = project / cas_relative_path(digest)
    os.chmod(path, 0o644)
    path.write_bytes(content)


def _completable(tmp_path: Path) -> tuple[Path, str, Path]:
    """Return a project rewound to the exact pre-completion current state.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        Project root, deck ID, and the completion contract source path.
    """
    project, deck_id, _, completion, _, _ = _complete_fixture(tmp_path)
    _update_deck(project, deck_id, status="validating", completion_evidence_id=None)
    return project, deck_id, completion


def test_current_evidence_returns_the_pointer_selected_verified_envelope(
    tmp_path: Path,
) -> None:
    """A valid current pointer resolves to its exact verified envelope."""
    project, deck_id, _, _, _, _ = _complete_fixture(tmp_path)
    deck = _deck(project, deck_id)

    for kind, field in _POINTER_FIELDS.items():
        envelope = assert_current_evidence(project, deck_id, kind)
        assert envelope["id"] == deck[field]
        assert envelope["evidence_kind"] == kind
        assert envelope["deck_id"] == deck_id
        assert envelope["availability"] == "available"


def test_current_evidence_requires_the_pointer_instead_of_a_legacy_event(
    tmp_path: Path,
) -> None:
    """A valid schema-v1 preview event cannot authorize a cleared pointer."""
    project, deck_id, _ = _completable(tmp_path)
    before = _deck(project, deck_id)
    assert before["draft_preview_id"]
    _update_deck(project, deck_id, draft_preview_evidence_id=None)

    with pytest.raises(DraftGateError) as error:
        assert_current_evidence(project, deck_id, "draft_preview")

    assert error.value.blockers == [{"reason": "draft_preview_evidence_pointer_required"}]
    assert _deck(project, deck_id)["draft_preview_id"] == before["draft_preview_id"]


def test_current_evidence_rejects_a_wrong_kind_pointer(tmp_path: Path) -> None:
    """A preview pointer bound to approval evidence fails closed."""
    project, deck_id, _ = _completable(tmp_path)
    deck = _deck(project, deck_id)
    _update_deck(
        project, deck_id, draft_preview_evidence_id=deck["draft_approval_evidence_id"]
    )

    with pytest.raises(DraftGateError) as error:
        assert_current_evidence(project, deck_id, "draft_preview")

    assert _reasons(error.value.blockers) == {"active_preview_evidence_invalid"}


def test_current_evidence_rejects_a_cross_deck_pointer(tmp_path: Path) -> None:
    """Evidence owned by another deck can never satisfy this deck's pointer."""
    project, deck_id, _ = _completable(tmp_path)
    records = _evidence(project)
    pointer = _deck(project, deck_id)["draft_approval_evidence_id"]
    foreign = dict(records[pointer])
    foreign.update({"id": "draft-approval-other-deck", "deck_id": "deck-elsewhere"})
    foreign["subject_ids"] = ["deck-elsewhere"]
    foreign["evidence_sha256"] = envelope_sha256(foreign)
    records[foreign["id"]] = foreign
    _write_evidence(project, records)
    _update_deck(project, deck_id, draft_approval_evidence_id=foreign["id"])

    with pytest.raises(DraftGateError) as error:
        assert_current_evidence(project, deck_id, "draft_approval")

    assert _reasons(error.value.blockers) == {"active_approval_evidence_invalid"}


def test_current_evidence_ignores_a_tampered_evidence_store_record(
    tmp_path: Path,
) -> None:
    """Immutable history still proves the true envelope behind a pointer."""
    project, deck_id, _ = _completable(tmp_path)
    records = _evidence(project)
    pointer = _deck(project, deck_id)["draft_preview_evidence_id"]
    records[pointer]["deck_id"] = "deck-elsewhere"
    _write_evidence(project, records)

    envelope = assert_current_evidence(project, deck_id, "draft_preview")

    assert envelope["deck_id"] == deck_id


def test_current_evidence_rejects_unavailable_source_history(tmp_path: Path) -> None:
    """Losing the immutable source event blocks the current pointer."""
    project, deck_id, _ = _completable(tmp_path)
    for shard in (project / ".research/presentations/events").glob("*.jsonl"):
        kept = [
            line
            for line in shard.read_text(encoding="utf-8").splitlines()
            if '"event": "draft_preview"' not in line
        ]
        shard.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")

    with pytest.raises(DraftGateError) as error:
        assert_current_evidence(project, deck_id, "draft_preview")

    assert _reasons(error.value.blockers) == {"active_preview_source_unavailable"}


def test_current_evidence_rejects_a_stale_slide(tmp_path: Path) -> None:
    """Reopening one current slide invalidates current preview evidence."""
    project, deck_id, _ = _completable(tmp_path)
    document = _read_state(project, "slides.yaml")
    for record in document["slides"].values():
        if record.get("deck_id") == deck_id:
            record["status"] = "review_required"
    _write_state(project, "slides.yaml", document)

    with pytest.raises(DraftGateError) as error:
        assert_current_evidence(project, deck_id, "draft_preview")

    assert _reasons(error.value.blockers) == {"active_preview_slide_not_passed"}


def test_current_evidence_rejects_approved_plan_drift(tmp_path: Path) -> None:
    """Editing the approved plan file invalidates every current pointer."""
    project, deck_id, _ = _completable(tmp_path)
    plan_record = next(
        record
        for record in _read_state(project, "plans.yaml")["plans"].values()
        if record.get("deck_id") == deck_id
    )
    plan_path = project / plan_record["plan_path"]
    document = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    document["slides"][0]["title"] = "A drifted title"
    plan_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(DraftGateError) as error:
        assert_current_evidence(project, deck_id, "draft_preview")

    assert _reasons(error.value.blockers) == {"active_approved_plan_mismatch"}


def test_current_evidence_rejects_revision_invalidated_pointers(tmp_path: Path) -> None:
    """A required plan revision invalidates all current evidence pointers."""
    project, deck_id, _ = _completable(tmp_path)
    _update_deck(project, deck_id, required_plan_revision_id="revision-1")

    with pytest.raises(DraftGateError) as error:
        assert_current_evidence(project, deck_id, "draft_preview")

    assert _reasons(error.value.blockers) == {"active_evidence_invalidated_by_revision"}


@pytest.mark.parametrize("reference_index", [0, -1])
def test_current_evidence_rejects_a_deleted_cas_object(
    tmp_path: Path, reference_index: int
) -> None:
    """Deleting any ordered CAS object blocks its current evidence.

    Args:
        tmp_path: Per-test temporary directory.
        reference_index: First or final artifact reference to delete.
    """
    project, deck_id, _, _, _, _ = _complete_fixture(tmp_path)
    pointer = _deck(project, deck_id)["completion_evidence_id"]
    reference = _evidence(project)[pointer]["artifact_refs"][reference_index]
    (project / reference["cas_path"]).unlink()

    with pytest.raises(CompletionGateError) as error:
        assert_current_evidence(project, deck_id, "deck_completion")

    assert _reasons(error.value.blockers) == {"evidence_cas_object_missing"}
    assert error.value.blockers[0]["cas_path"] == reference["cas_path"]


def test_current_evidence_rejects_snapshot_intercepted_cas_tamper(
    tmp_path: Path,
) -> None:
    """Tampered CAS bytes fail closed at the snapshot capture boundary.

    ``_capture_persisted_cas_objects`` re-hashes every persisted CAS object
    while building the snapshot, so a tamper raises
    ``EvidenceCasIntegrityError`` before ``_cas_blockers`` ever compares
    references. This test pins that interception and the gate's translation of
    it, not the gate's own digest-mismatch branch (see
    ``test_cas_blockers_reports_unverified_object_digest_mismatch``).
    """
    project, deck_id, _, _, _, _ = _complete_fixture(tmp_path)
    pointer = _deck(project, deck_id)["completion_evidence_id"]
    reference = _evidence(project)[pointer]["artifact_refs"][0]
    _overwrite_cas_object(project, reference["sha256"], b"tampered-cas-bytes")

    with pytest.raises(EvidenceCasIntegrityError):
        build_snapshot(project)
    with pytest.raises(CompletionGateError) as error:
        assert_current_evidence(project, deck_id, "deck_completion")

    assert _reasons(error.value.blockers) == {"evidence_cas_digest_mismatch"}


def _snapshot_with_object(project: Path, cas_path: str, object_: CasObject) -> EvidenceSnapshot:
    """Build a minimal frozen snapshot carrying one hand-made CAS object."""
    return EvidenceSnapshot(
        project_root=project,
        schema_version=2,
        stores=MappingProxyType({}),
        events=(),
        file_preimages=MappingProxyType({}),
        artifact_objects=MappingProxyType({cas_path: object_}),
    )


@pytest.mark.parametrize("lying_digest_field", [True, False])
def test_cas_blockers_reports_unverified_object_digest_mismatch(
    tmp_path: Path, lying_digest_field: bool
) -> None:
    """The gate's own digest branch rejects objects that skipped verification.

    This branch is unreachable through the producer pipeline because the
    snapshot layer verifies persisted CAS objects first, so it is exercised
    directly with hand-constructed inputs to pin it as defensive code.

    Args:
        tmp_path: Per-test temporary directory.
        lying_digest_field: Whether ``CasObject.digest`` itself disagrees with
            the reference, or agrees while the bytes underneath do not.
    """
    declared = hashlib.sha256(b"authorized-artifact").hexdigest()
    other = hashlib.sha256(b"attacker-artifact").hexdigest()
    cas_path = cas_relative_path(declared).as_posix()
    object_ = CasObject(
        digest=other if lying_digest_field else declared,
        relative_path=cas_relative_path(declared),
        content=b"attacker-artifact",
        mode=0o444,
    )
    snapshot = _snapshot_with_object(tmp_path, cas_path, object_)
    envelope = {
        "artifact_refs": [
            {"sha256": declared, "cas_path": cas_path, "artifact_kind": "final_pptx"}
        ]
    }

    blockers = _cas_blockers(snapshot, envelope)

    assert blockers == [
        {
            "reason": "evidence_cas_digest_mismatch",
            "cas_path": cas_path,
            "sha256": declared,
        }
    ]


def test_cas_blockers_accepts_a_verified_object(tmp_path: Path) -> None:
    """A genuinely verified CAS object produces no blocker."""
    content = b"authorized-artifact"
    declared = hashlib.sha256(content).hexdigest()
    cas_path = cas_relative_path(declared).as_posix()
    object_ = CasObject(
        digest=declared,
        relative_path=cas_relative_path(declared),
        content=content,
        mode=0o444,
    )
    snapshot = _snapshot_with_object(tmp_path, cas_path, object_)
    envelope = {"artifact_refs": [{"sha256": declared, "cas_path": cas_path}]}

    assert _cas_blockers(snapshot, envelope) == []


def test_current_evidence_rejects_an_unknown_deck(tmp_path: Path) -> None:
    """An unresolved deck produces a structured gate error, not a crash."""
    project, _, _ = _completable(tmp_path)

    with pytest.raises(DraftGateError) as error:
        assert_current_evidence(project, "deck-missing", "draft_preview")

    assert _reasons(error.value.blockers) == {"unknown_deck"}


def test_current_evidence_rejects_an_unsupported_evidence_kind(tmp_path: Path) -> None:
    """An unregistered evidence kind is a programming error, not a blocker."""
    project, deck_id, _ = _completable(tmp_path)

    with pytest.raises(ValueError, match="unsupported evidence kind"):
        assert_current_evidence(project, deck_id, "visual_review")


def _decision(project: Path, deck_id: str) -> dict[str, Any]:
    """Build a canonical draft decision bound to the current preview."""
    return {
        "schema_version": 1,
        "deck_id": deck_id,
        "preview_id": _deck(project, deck_id)["draft_preview_id"],
        "decision": "approve",
        "approval_mode": "interactive",
        "approved_by": "reviewer",
    }


def test_draft_approvable_accepts_the_current_preview_pointer(tmp_path: Path) -> None:
    """A decision bound to current preview evidence is authorized."""
    project, deck_id, _ = _completable(tmp_path)

    checked = assert_draft_approvable(project, deck_id, _decision(project, deck_id))

    assert checked["preview"]["id"] == _deck(project, deck_id)["draft_preview_evidence_id"]
    assert checked["deck"]["id"] == deck_id


def test_draft_approvable_does_not_fall_back_to_a_legacy_preview_event(
    tmp_path: Path,
) -> None:
    """A legacy preview event cannot authorize approval without a pointer."""
    project, deck_id, _ = _completable(tmp_path)
    decision = _decision(project, deck_id)
    _update_deck(project, deck_id, draft_preview_evidence_id=None)

    with pytest.raises(DraftGateError) as error:
        assert_draft_approvable(project, deck_id, decision)

    assert error.value.blockers == [{"reason": "draft_preview_evidence_pointer_required"}]


def test_draft_approvable_binds_the_decision_to_the_current_preview(
    tmp_path: Path,
) -> None:
    """A decision naming a different preview source fails closed."""
    project, deck_id, _ = _completable(tmp_path)
    decision = _decision(project, deck_id)
    decision["preview_id"] = "draft_other"

    with pytest.raises(DraftGateError) as error:
        assert_draft_approvable(project, deck_id, decision)

    assert _reasons(error.value.blockers) == {"draft_decision_preview_binding_mismatch"}


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("deck_id", "deck_id_mismatch"),
        ("decision", "draft_decision_not_approve"),
    ],
)
def test_draft_approvable_rejects_an_inconsistent_decision(
    tmp_path: Path, field: str, reason: str
) -> None:
    """Decision identity and verdict remain explicit gate requirements.

    Args:
        tmp_path: Per-test temporary directory.
        field: Decision field replaced with an inconsistent value.
        reason: Exact structured blocker the gate must report.
    """
    project, deck_id, _ = _completable(tmp_path)
    decision = _decision(project, deck_id)
    decision[field] = "other"

    with pytest.raises(DraftGateError) as error:
        assert_draft_approvable(project, deck_id, decision)

    assert reason in _reasons(error.value.blockers)


def test_approve_draft_producer_enforces_the_same_gate_as_assert_draft_approvable(
    tmp_path: Path,
) -> None:
    """The producer must reject what the gate rejects, not diverge from it.

    Before this was wired up, deleting a CAS object backing the current preview
    left the gate raising ``evidence_cas_object_missing`` while
    ``approve_draft`` cheerfully wrote a ``draft_approval`` envelope and moved
    the deck to ``validating`` -- a dead-end the completion gate could never
    accept.
    """
    project, deck_id, decision_path = _approval_ready_project(tmp_path)
    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    pointer = _deck(project, deck_id)["draft_preview_evidence_id"]
    reference = _evidence(project)[pointer]["artifact_refs"][0]
    (project / reference["cas_path"]).unlink()

    with pytest.raises(DraftGateError) as gate_error:
        assert_draft_approvable(project, deck_id, decision)
    with pytest.raises(DraftGateError) as producer_error:
        approve_draft(project, decision_path)

    assert _reasons(gate_error.value.blockers) == {"evidence_cas_object_missing"}
    assert _reasons(producer_error.value.blockers) == {"evidence_cas_object_missing"}
    after = _deck(project, deck_id)
    assert after["draft_approval_evidence_id"] is None
    assert after["status"] == "draft_review"


def test_approve_draft_producer_accepts_intact_current_preview_evidence(
    tmp_path: Path,
) -> None:
    """The new gate call does not block a legitimate approval."""
    project, deck_id, decision_path = _approval_ready_project(tmp_path)

    result = approve_draft(project, decision_path)

    assert result["evidence_id"]
    assert _deck(project, deck_id)["draft_approval_evidence_id"] == result["evidence_id"]


def test_completion_gate_accepts_current_pointer_selected_evidence(
    tmp_path: Path,
) -> None:
    """The completion gate authorizes a fully current pointer-selected deck."""
    project, deck_id, completion_path = _completable(tmp_path)
    completion = yaml.safe_load(completion_path.read_text(encoding="utf-8"))

    checked = assert_deck_completable(project, deck_id, completion)

    assert checked["deck"]["id"] == deck_id
    assert checked["visual_review"]["deck_id"] == deck_id


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("draft_preview_evidence_id", "draft_preview_evidence_pointer_required"),
        ("draft_approval_evidence_id", "draft_approval_evidence_pointer_required"),
    ],
)
def test_completion_gate_requires_each_current_evidence_pointer(
    tmp_path: Path, field: str, reason: str
) -> None:
    """Completion requires both current draft pointers by exact name.

    Args:
        tmp_path: Per-test temporary directory.
        field: Current deck evidence pointer cleared before the gate runs.
        reason: Exact structured blocker the completion gate must report.
    """
    project, deck_id, completion_path = _completable(tmp_path)
    completion = yaml.safe_load(completion_path.read_text(encoding="utf-8"))
    _update_deck(project, deck_id, **{field: None})

    with pytest.raises(CompletionGateError) as error:
        assert_deck_completable(project, deck_id, completion)

    assert reason in _reasons(error.value.blockers)


def test_completion_gate_does_not_fall_back_to_legacy_draft_events(
    tmp_path: Path,
) -> None:
    """Intact schema-v1 draft history cannot authorize completion alone."""
    project, deck_id, completion_path = _completable(tmp_path)
    completion = yaml.safe_load(completion_path.read_text(encoding="utf-8"))
    before = _deck(project, deck_id)
    _update_deck(
        project,
        deck_id,
        draft_preview_evidence_id=None,
        draft_approval_evidence_id=None,
    )

    with pytest.raises(CompletionGateError) as error:
        assert_deck_completable(project, deck_id, completion)

    assert {
        "draft_preview_evidence_pointer_required",
        "draft_approval_evidence_pointer_required",
    } <= _reasons(error.value.blockers)
    after = _deck(project, deck_id)
    assert after["draft_preview_id"] == before["draft_preview_id"]
    assert after["draft_approval_id"] == before["draft_approval_id"]


def test_completion_gate_rejects_snapshot_intercepted_preview_cas_tamper(
    tmp_path: Path,
) -> None:
    """Tampered current preview CAS bytes block completion authorization.

    As above, the tamper is intercepted while the snapshot is captured and the
    completion gate translates it; this pins the end-to-end completion path,
    not ``_cas_blockers``' own digest comparison.
    """
    project, deck_id, completion_path = _completable(tmp_path)
    completion = yaml.safe_load(completion_path.read_text(encoding="utf-8"))
    pointer = _deck(project, deck_id)["draft_preview_evidence_id"]
    reference = _evidence(project)[pointer]["artifact_refs"][0]
    _overwrite_cas_object(project, reference["sha256"], b"tampered-preview-bytes")

    with pytest.raises(CompletionGateError) as error:
        assert_deck_completable(project, deck_id, completion)

    assert "evidence_cas_digest_mismatch" in _reasons(error.value.blockers)


@pytest.mark.parametrize(
    "relative", ["deck/final.pptx", "renders/pptx/slide-1.png"]
)
def test_completion_gate_rejects_a_mutated_final_artifact(
    tmp_path: Path, relative: str
) -> None:
    """Every final artifact remains byte-verified before completion.

    Args:
        tmp_path: Per-test temporary directory.
        relative: Final artifact replaced with unauthorized bytes.
    """
    project, deck_id, completion_path = _completable(tmp_path)
    completion = yaml.safe_load(completion_path.read_text(encoding="utf-8"))
    (project / relative).write_bytes(b"unauthorized-final-artifact")

    with pytest.raises(CompletionGateError, match="digest_mismatch"):
        assert_deck_completable(project, deck_id, completion)


def test_completion_gate_rejects_a_removed_final_artifact_record(
    tmp_path: Path,
) -> None:
    """A missing persisted artifact record still blocks completion by name."""
    project, deck_id, completion_path = _completable(tmp_path)
    completion = yaml.safe_load(completion_path.read_text(encoding="utf-8"))
    document = _read_state(project, "artifacts.yaml")
    document["artifacts"] = {
        key: value
        for key, value in document["artifacts"].items()
        if value.get("path") != "renders/pptx/slide-1.png"
    }
    _write_state(project, "artifacts.yaml", document)

    with pytest.raises(CompletionGateError, match="missing_persisted_artifact"):
        assert_deck_completable(project, deck_id, completion)
