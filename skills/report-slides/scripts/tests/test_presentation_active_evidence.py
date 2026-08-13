"""Behavioral tests for schema-v2 current evidence projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
import pytest

from presentation_contracts import contract_sha256
from presentation_evidence_cas import CasObject, cas_relative_path
from presentation_evidence_contracts import envelope_sha256
from presentation_evidence_projection import HistoricalProjection
import presentation_evidence_projection
from presentation_evidence_snapshot import EvidenceSnapshot, PlanPreimage, build_snapshot
from presentation_active_evidence_fixtures import (
    make_two_slide_preview,
    project_real_historical_preview,
    substitute_cas_backed_preview_artifact,
    with_preview_source,
)


def _digest(content: bytes) -> str:
    """Return the fixture SHA-256 digest."""
    return hashlib.sha256(content).hexdigest()


def _envelope(
    evidence_id: str,
    evidence_kind: str,
    deck_id: str,
    plan_id: str,
    plan_sha256: str,
    artifact_refs: list[dict[str, str]],
    **refinement: str,
) -> dict[str, Any]:
    """Create one hand-shaped available envelope for a projection fixture."""
    envelope: dict[str, Any] = {
        "id": evidence_id,
        "schema_version": 2,
        "evidence_kind": evidence_kind,
        "deck_id": deck_id,
        "plan_id": plan_id,
        "plan_version": 1,
        "plan_sha256": plan_sha256,
        "subject_ids": ["slide-01"] if evidence_kind == "draft_preview" else [deck_id],
        "producer_id": "test-producer",
        "artifact_refs": artifact_refs,
        "source_event_id": f"event-{evidence_id}",
        "created_at": "2026-08-09T00:00:00Z",
        "availability": "available",
        **refinement,
    }
    envelope["evidence_sha256"] = envelope_sha256(envelope)
    return envelope


def _artifact_ref(
    content: bytes,
    artifact_kind: str,
    subject_id: str,
    original_path: str,
) -> tuple[dict[str, str], CasObject]:
    """Create one matching artifact reference and immutable CAS object."""
    digest = _digest(content)
    return (
        {
            "sha256": digest,
            "cas_path": cas_relative_path(digest).as_posix(),
            "artifact_kind": artifact_kind,
            "subject_id": subject_id,
            "original_path": original_path,
        },
        CasObject(digest, cas_relative_path(digest), content, 0o444),
    )


def _review_status(
    reviewed_by: str, inspected_paths: list[str]
) -> dict[str, Any]:
    """Create one passed visual-review gate status for a frozen fixture."""
    return {
        "status": "passed",
        "round": 1,
        "reviewed_by": reviewed_by,
        "inspected_paths": inspected_paths,
        "findings": [],
        "revision_required": False,
        "started_at": "2026-08-09T00:00:00Z",
        "completed_at": "2026-08-09T00:00:00Z",
    }


def _completion_review_document(
    final_path: str, rendered_paths: list[str], review_path: str
) -> dict[str, Any]:
    """Create one valid completion-authorizing review with exact outputs."""
    source_png = "output/source-01.png"
    render = _review_status("model_vision", rendered_paths)
    render.update(
        {
            "renderer": {
                "name": "LibreOffice",
                "version": "25.0",
                "conversion_format": "pdf-to-png",
            },
            "conversion_artifacts": ["output/deck.pdf"],
            "rendered_png_paths": rendered_paths,
            "model_vision": {
                "inspected_paths": rendered_paths,
                "comparison_reference_paths": [source_png],
            },
            "visual_checks": {"clipping": "passed"},
        }
    )
    return {
        "schema_version": 1,
        "deck_id": "deck-1",
        "output_format": "pptx",
        "expected_slides": [1],
        "source_artifacts": ["output/source-01.svg", source_png],
        "artifacts": {"pptx": final_path, "review_record": review_path},
        "statuses": {
            "svg_preview": _review_status("model_vision", [source_png]),
            "pptx_structure": _review_status("pptx_structure_validator", [final_path]),
            "pptx_render": render,
        },
        "overall": {
            "status": "passed",
            "completion_allowed": True,
            "authority": "pptx-render",
        },
        "history": [
            {"round": 1, "result": "passed", "revision": "Initial review"}
        ],
    }


def _approved_snapshot(*, include_extra_active_slide: bool = False) -> tuple[
    EvidenceSnapshot, HistoricalProjection
]:
    """Build current approved state and a pointer-selected preview envelope."""
    project_root = Path("/active-evidence-project")
    deck_id = "deck-1"
    plan_id = "plan-1"
    plan = {
        "deck_id": deck_id,
        "plan_version": 1,
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Exact current title",
                "key_takeaway": "Exact current takeaway.",
            }
        ],
    }
    plan_sha256 = contract_sha256(plan)
    rendered_ref, rendered_object = _artifact_ref(
        b"rendered-slide", "rendered_slide", "slide-01", "renders/slide-01.png"
    )
    contact_ref, contact_object = _artifact_ref(
        b"contact-sheet", "contact_sheet", deck_id, "renders/contact-sheet.png"
    )
    preview = _envelope(
        "preview-1",
        "draft_preview",
        deck_id,
        plan_id,
        plan_sha256,
        [rendered_ref, contact_ref],
    )
    slides: dict[str, dict[str, Any]] = {
        "slide-record-1": {
            "id": "slide-record-1",
            "deck_id": deck_id,
            "plan_slide_id": "slide-01",
            "title": "Exact current title",
            "status": "passed",
            "attempt": 1,
        }
    }
    if include_extra_active_slide:
        slides["slide-record-extra"] = {
            "id": "slide-record-extra",
            "deck_id": deck_id,
            "plan_slide_id": "slide-extra",
            "title": "Unexpected active slide",
            "status": "passed",
            "attempt": 1,
        }
    snapshot = EvidenceSnapshot(
        project_root=project_root,
        schema_version=2,
        stores=MappingProxyType(
            {
                "decks": MappingProxyType(
                    {
                        deck_id: MappingProxyType(
                            {
                                "id": deck_id,
                                "status": "draft_review",
                                "current_plan_id": plan_id,
                                "approved_plan_version": 1,
                                "approved_plan_sha256": plan_sha256,
                                "draft_preview_evidence_id": preview["id"],
                                "draft_approval_evidence_id": None,
                                "completion_evidence_id": None,
                            }
                        )
                    }
                ),
                "plans": MappingProxyType(
                    {
                        plan_id: MappingProxyType(
                            {
                                "id": plan_id,
                                "deck_id": deck_id,
                                "version": 1,
                                "plan_sha256": plan_sha256,
                                "plan_path": "decks/deck-1/plans/plan-v0001.yaml",
                            }
                        )
                    }
                ),
                "slides": MappingProxyType(
                    {key: MappingProxyType(value) for key, value in slides.items()}
                ),
                "artifacts": MappingProxyType(
                    {
                        "artifact-render": MappingProxyType(
                            {
                                "id": "artifact-render",
                                "deck_id": deck_id,
                                "artifact_kind": "slide-png",
                                "path": "renders/slide-01.png",
                                "sha256": rendered_ref["sha256"],
                                "slide_record_id": "slide-record-1",
                                "attempt": 1,
                            }
                        ),
                        "artifact-contact": MappingProxyType(
                            {
                                "id": "artifact-contact",
                                "deck_id": deck_id,
                                "artifact_kind": "review-sheet",
                                "path": "renders/contact-sheet.png",
                                "sha256": contact_ref["sha256"],
                            }
                        ),
                    }
                ),
            }
        ),
        events=(),
        file_preimages=MappingProxyType(
            {
                project_root / "decks/deck-1/plans/plan-v0001.yaml": (
                    b"deck_id: deck-1\nplan_version: 1\nslides:\n"
                    b"  - slide_id: slide-01\n"
                    b"    title: Exact current title\n"
                    b"    key_takeaway: Exact current takeaway.\n"
                )
            }
        ),
        active_plan_preimages=MappingProxyType(
            {
                plan_id: PlanPreimage(
                    path="decks/deck-1/plans/plan-v0001.yaml",
                    content=(
                        b"deck_id: deck-1\nplan_version: 1\nslides:\n"
                        b"  - slide_id: slide-01\n"
                        b"    title: Exact current title\n"
                        b"    key_takeaway: Exact current takeaway.\n"
                    ),
                    mode=0o644,
                    mtime_ns=0,
                    sha256=_digest(
                        b"deck_id: deck-1\nplan_version: 1\nslides:\n"
                        b"  - slide_id: slide-01\n"
                        b"    title: Exact current title\n"
                        b"    key_takeaway: Exact current takeaway.\n"
                    ),
                )
            }
        ),
    )
    history = HistoricalProjection(
        envelopes=MappingProxyType({preview["id"]: MappingProxyType(preview)}),
        by_source_event_id=MappingProxyType({}),
        cas_objects=MappingProxyType(
            {
                rendered_object.digest: rendered_object,
                contact_object.digest: contact_object,
            }
        ),
        current_pointer_ids=frozenset(),
    )
    return snapshot, history


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", 2), ("preview_sha256", "0" * 64), ("ts", None)],
)
def test_active_preview_rejects_nonexact_source_event_contract(
    field: str, value: Any
) -> None:
    """Active preview selection reuses the exact historical source contract."""
    snapshot, seed_history = _approved_snapshot()
    snapshot, history = project_real_historical_preview(
        with_preview_source(snapshot), seed_history
    )
    source = dict(snapshot.events[0])
    if value is None:
        source.pop(field)
    else:
        source[field] = value
    tampered = replace(snapshot, events=(MappingProxyType(source),))

    projection = presentation_evidence_projection.project_active_evidence(
        tampered, history
    )

    assert projection.blockers["deck-1"] == (
        {"reason": "active_preview_source_invalid"},
    )


def test_active_preview_requires_exact_ordered_passed_slide_set() -> None:
    """An unexpected active slide cannot authorize a current preview."""
    snapshot, history = _approved_snapshot(include_extra_active_slide=True)

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == (
        {"reason": "active_preview_slide_set_mismatch"},
    )


def test_snapshot_captures_current_approved_plan_bytes(tmp_path: Path) -> None:
    """Current plan metadata remains available after snapshot construction."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    state = project / ".research/presentations/state"
    state.mkdir(parents=True)
    plan_path = project / "decks/deck-1/plans/plan-v0001.yaml"
    plan_path.parent.mkdir(parents=True)
    plan_bytes = b"deck_id: deck-1\nplan_version: 1\nslides: []\n"
    plan_path.write_bytes(plan_bytes)
    (state / "decks.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "decks": {
                    "deck-1": {
                        "id": "deck-1",
                        "status": "approved",
                        "current_plan_id": "plan-1",
                        "approved_plan_version": 1,
                        "approved_plan_sha256": "1" * 64,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (state / "plans.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "plans": {
                    "plan-1": {
                        "id": "plan-1",
                        "deck_id": "deck-1",
                        "version": 1,
                        "plan_sha256": "1" * 64,
                        "plan_path": "decks/deck-1/plans/plan-v0001.yaml",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    snapshot = build_snapshot(project)

    assert snapshot.file_preimages[plan_path] == plan_bytes


def _legacy_completed_projection(
    candidate_count: int,
) -> tuple[EvidenceSnapshot, HistoricalProjection]:
    """Build one completed legacy deck with a chosen completion candidate count."""
    snapshot, history = _approved_snapshot()
    deck = dict(snapshot.stores["decks"]["deck-1"])
    deck.update(
        {
            "status": "completed",
            "draft_preview_evidence_id": None,
            "draft_approval_evidence_id": None,
            "completion_evidence_id": None,
        }
    )
    final_ref, final_object = _artifact_ref(
        b"final-pptx", "final_pptx", "deck-1", "output/deck.pptx"
    )
    render_ref, render_object = _artifact_ref(
        b"final-render", "rendered_png", "deck-1", "output/deck-01.png"
    )
    artifacts = dict(snapshot.stores["artifacts"])
    artifacts.update(
        {
            "artifact-final": MappingProxyType(
                {
                    "id": "artifact-final",
                    "deck_id": "deck-1",
                    "artifact_kind": "deck-pptx",
                    "path": "output/deck.pptx",
                    "sha256": final_ref["sha256"],
                }
            ),
            "artifact-final-render": MappingProxyType(
                {
                    "id": "artifact-final-render",
                    "deck_id": "deck-1",
                    "artifact_kind": "slide-png",
                    "path": "output/deck-01.png",
                    "sha256": render_ref["sha256"],
                }
            ),
        }
    )
    stores = dict(snapshot.stores)
    stores["decks"] = MappingProxyType({"deck-1": MappingProxyType(deck)})
    stores["artifacts"] = MappingProxyType(artifacts)
    snapshot = replace(snapshot, stores=MappingProxyType(stores))
    envelopes = dict(history.envelopes)
    objects = dict(history.cas_objects)
    objects.update({final_object.digest: final_object, render_object.digest: render_object})
    approval = _envelope(
        "approval-1",
        "draft_approval",
        "deck-1",
        "plan-1",
        snapshot.stores["decks"]["deck-1"]["approved_plan_sha256"],
        [],
        preview_evidence_id="preview-1",
        preview_evidence_sha256=envelopes["preview-1"]["evidence_sha256"],
        decision="approved",
        approval_mode="interactive",
        approved_by="reviewer-1",
    )
    review = _envelope(
        "review-1",
        "visual_review",
        "deck-1",
        "plan-1",
        snapshot.stores["decks"]["deck-1"]["approved_plan_sha256"],
        [],
    )
    review_path = "output/visual-review.json"
    review_document = _completion_review_document(
        "output/deck.pptx", ["output/deck-01.png"], review_path
    )
    approval_event = MappingProxyType(
        {
            "id": "event-approval-1",
            "event": "deck_approval",
            "schema_version": 1,
            "deck_id": "deck-1",
            "plan_id": "plan-1",
            "plan_version": 1,
            "plan_sha256": snapshot.stores["decks"]["deck-1"]["approved_plan_sha256"],
            "decision": "approve",
            "approved_by": "reviewer-1",
            "approved_at": "2026-08-09T00:00:00Z",
            "approval_mode": "interactive",
            "revisions_requested": [],
            "ts": "2026-08-09T00:00:00Z",
        }
    )
    review_event = MappingProxyType(
        {
            "id": "event-review-1",
            "event": "visual_review",
            "schema_version": 1,
            "deck_id": "deck-1",
            "plan_id": "plan-1",
            "plan_version": 1,
            "plan_sha256": snapshot.stores["decks"]["deck-1"]["approved_plan_sha256"],
            "producer_id": "reviewer-1",
            "visual_review_path": review_path,
            "visual_review_sha256": contract_sha256(review_document),
            "ts": "2026-08-09T00:00:00Z",
        }
    )
    envelopes.update(
        {
            approval["id"]: MappingProxyType(approval),
            review["id"]: MappingProxyType(review),
        }
    )
    completion_events: list[MappingProxyType] = []
    for index in range(candidate_count):
        completion = _envelope(
            f"completion-{index + 1}",
            "deck_completion",
            "deck-1",
            "plan-1",
            snapshot.stores["decks"]["deck-1"]["approved_plan_sha256"],
            [final_ref, render_ref],
            approval_evidence_id="approval-1",
            approval_evidence_sha256=approval["evidence_sha256"],
            visual_review_evidence_id="review-1",
            visual_review_evidence_sha256=review["evidence_sha256"],
        )
        envelopes[completion["id"]] = MappingProxyType(completion)
        completion_events.append(
            MappingProxyType(
                {
                    "id": f"event-completion-{index + 1}",
                    "event": "deck_completion",
                    "deck_id": "deck-1",
                    "plan_id": "plan-1",
                    "plan_version": 1,
                    "plan_sha256": snapshot.stores["decks"]["deck-1"][
                        "approved_plan_sha256"
                    ],
                }
            )
        )
    preimages = dict(snapshot.file_preimages)
    preimages[snapshot.project_root / review_path] = json.dumps(
        review_document, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    snapshot = replace(
        snapshot,
        events=(approval_event, review_event, *completion_events),
        file_preimages=MappingProxyType(preimages),
    )
    snapshot = with_preview_source(snapshot)
    return snapshot, HistoricalProjection(
        envelopes=MappingProxyType(envelopes),
        by_source_event_id=MappingProxyType({}),
        cas_objects=MappingProxyType(objects),
        current_pointer_ids=frozenset(),
    )


def test_ambiguous_legacy_completion_blocks_without_latest_wins() -> None:
    """Two valid legacy completion candidates cannot choose the later record."""
    snapshot, history = _legacy_completed_projection(2)

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.completion_pointer_updates == {}
    assert active.blockers["deck-1"] == (
        {"reason": "ambiguous_completion_evidence"},
    )


def test_one_legacy_completion_candidate_creates_only_its_pointer_update() -> None:
    """One verified legacy completion candidate is safe to bind explicitly."""
    snapshot, history = _legacy_completed_projection(1)

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers == {}
    assert active.completion_pointer_updates == {
        "deck-1": {"completion_evidence_id": "completion-1"}
    }


def test_missing_legacy_completion_blocks_instead_of_inventing_evidence() -> None:
    """A completed legacy deck without candidates receives no synthetic pointer."""
    snapshot, history = _legacy_completed_projection(0)

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.completion_pointer_updates == {}
    assert active.blockers["deck-1"] == ({"reason": "missing_completion_evidence"},)


def test_revision_clears_all_current_pointers_atomically() -> None:
    """A replacement slide invalidates preview, approval, and completion together."""
    snapshot, history = _approved_snapshot()
    deck = dict(snapshot.stores["decks"]["deck-1"])
    deck.update(
        {
            "draft_approval_evidence_id": "approval-1",
            "completion_evidence_id": "completion-1",
        }
    )
    replacement = dict(snapshot.stores["slides"]["slide-record-1"])
    replacement["revision_request_id"] = "revision-1"
    stores = dict(snapshot.stores)
    stores["decks"] = MappingProxyType({"deck-1": MappingProxyType(deck)})
    stores["slides"] = MappingProxyType(
        {"slide-record-1": MappingProxyType(replacement)}
    )
    snapshot = replace(snapshot, stores=MappingProxyType(stores))

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers == {}
    assert active.pointer_updates == {
        "deck-1": {
            "draft_preview_evidence_id": None,
            "draft_approval_evidence_id": None,
            "completion_evidence_id": None,
        }
    }


def test_pointerless_early_draft_does_not_require_an_approved_plan() -> None:
    """Current validation ignores a deck without any evidence pointer."""
    snapshot = EvidenceSnapshot(
        project_root=Path("/pointerless-draft"),
        schema_version=2,
        stores=MappingProxyType(
            {
                "decks": MappingProxyType(
                    {
                        "deck-draft": MappingProxyType(
                            {
                                "id": "deck-draft",
                                "status": "planning",
                                "current_plan_id": None,
                                "draft_preview_evidence_id": None,
                                "draft_approval_evidence_id": None,
                                "completion_evidence_id": None,
                            }
                        )
                    }
                )
            }
        ),
        events=(),
        file_preimages=MappingProxyType({}),
    )
    history = HistoricalProjection(
        envelopes=MappingProxyType({}),
        by_source_event_id=MappingProxyType({}),
        cas_objects=MappingProxyType({}),
        current_pointer_ids=frozenset(),
    )

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers == {}


def test_active_preview_rejects_legacy_plan_digest_alias() -> None:
    """A pointer-selected preview requires canonical plan_sha256, never sha256."""
    snapshot, history = _approved_snapshot()
    snapshot = with_preview_source(snapshot)
    stores = dict(snapshot.stores)
    plan = dict(stores["plans"]["plan-1"])
    plan["sha256"] = plan.pop("plan_sha256")
    stores["plans"] = MappingProxyType({"plan-1": MappingProxyType(plan)})
    snapshot = replace(snapshot, stores=MappingProxyType(stores))

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == ({"reason": "active_approved_plan_mismatch"},)


def test_active_approval_requires_a_valid_frozen_source_decision() -> None:
    """An approval pointer cannot rely on envelope-only identity metadata."""
    snapshot, history = _approved_snapshot()
    snapshot = with_preview_source(snapshot)
    preview = history.envelopes["preview-1"]
    approval = _envelope(
        "approval-1",
        "draft_approval",
        "deck-1",
        "plan-1",
        snapshot.stores["decks"]["deck-1"]["approved_plan_sha256"],
        [],
        preview_evidence_id="preview-1",
        preview_evidence_sha256=preview["evidence_sha256"],
        decision="approved",
        approval_mode="interactive",
        approved_by="reviewer-1",
    )
    deck = dict(snapshot.stores["decks"]["deck-1"])
    deck["draft_approval_evidence_id"] = "approval-1"
    stores = dict(snapshot.stores)
    stores["decks"] = MappingProxyType({"deck-1": MappingProxyType(deck)})
    snapshot = replace(snapshot, stores=MappingProxyType(stores))
    envelopes = dict(history.envelopes)
    envelopes["approval-1"] = MappingProxyType(approval)
    history = replace(history, envelopes=MappingProxyType(envelopes))

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == ({"reason": "active_approval_source_invalid"},)


def _selected_completion_projection() -> tuple[EvidenceSnapshot, HistoricalProjection]:
    """Build a fully source-bound pointer-selected completion fixture."""
    snapshot, history = _legacy_completed_projection(1)
    deck = dict(snapshot.stores["decks"]["deck-1"])
    deck.update(
        {
            "draft_preview_evidence_id": "preview-1",
            "draft_approval_evidence_id": "approval-1",
            "completion_evidence_id": "completion-1",
        }
    )
    stores = dict(snapshot.stores)
    stores["decks"] = MappingProxyType({"deck-1": MappingProxyType(deck)})
    return replace(snapshot, stores=MappingProxyType(stores)), history


def test_active_completion_rejects_a_surplus_render_not_authorized_by_review() -> None:
    """A completion cannot add a matching CAS PNG beyond review output paths."""
    snapshot, history = _selected_completion_projection()
    extra_ref, extra_object = _artifact_ref(
        b"surplus-render", "rendered_png", "deck-1", "output/deck-extra.png"
    )
    completion = dict(history.envelopes["completion-1"])
    completion["artifact_refs"] = [*completion["artifact_refs"], extra_ref]
    completion["evidence_sha256"] = envelope_sha256(completion)
    artifacts = dict(snapshot.stores["artifacts"])
    artifacts["artifact-extra-render"] = MappingProxyType(
        {
            "id": "artifact-extra-render",
            "deck_id": "deck-1",
            "artifact_kind": "slide-png",
            "path": "output/deck-extra.png",
            "sha256": extra_ref["sha256"],
        }
    )
    stores = dict(snapshot.stores)
    stores["artifacts"] = MappingProxyType(artifacts)
    snapshot = replace(snapshot, stores=MappingProxyType(stores))
    envelopes = dict(history.envelopes)
    envelopes["completion-1"] = MappingProxyType(completion)
    objects = dict(history.cas_objects)
    objects[extra_object.digest] = extra_object
    history = replace(
        history,
        envelopes=MappingProxyType(envelopes),
        cas_objects=MappingProxyType(objects),
    )

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == (
        {"reason": "active_completion_artifacts_invalid"},
    )


def test_active_completion_rejects_a_non_authorizing_frozen_visual_review() -> None:
    """An otherwise linked completion needs a passed authoritative review."""
    snapshot, history = _selected_completion_projection()
    review_path = snapshot.project_root / "output/visual-review.json"
    review_document = json.loads(snapshot.file_preimages[review_path])
    review_document["statuses"]["pptx_render"]["status"] = "failed"
    review_document["statuses"]["pptx_render"]["revision_required"] = True
    review_document["statuses"]["pptx_render"]["findings"] = [
        {
            "kind": "clipping",
            "source": "pptx-render",
            "scope": {"slide": 1},
            "artifact_path": "output/deck-01.png",
            "description": "Clipped label.",
            "disposition": "open",
        }
    ]
    review_document["overall"] = {
        "status": "failed",
        "completion_allowed": False,
        "authority": "pptx-render",
    }
    events = list(snapshot.events)
    for index, event in enumerate(events):
        if event["id"] == "event-review-1":
            changed = dict(event)
            changed["visual_review_sha256"] = contract_sha256(review_document)
            events[index] = MappingProxyType(changed)
    preimages = dict(snapshot.file_preimages)
    preimages[review_path] = json.dumps(
        review_document, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    snapshot = replace(
        snapshot,
        events=tuple(events),
        file_preimages=MappingProxyType(preimages),
    )

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == (
        {"reason": "active_completion_visual_review_invalid"},
    )


@pytest.mark.parametrize(
    ("evidence_id", "expected_reason"),
    [
        ("preview-1", "active_preview_plan_mismatch"),
        ("approval-1", "active_approval_evidence_invalid"),
        ("review-1", "active_completion_visual_review_invalid"),
        ("completion-1", "active_completion_evidence_invalid"),
    ],
)
def test_selected_evidence_requires_exact_current_plan_id(
    evidence_id: str, expected_reason: str
) -> None:
    """Same-version/digest evidence for another plan ID cannot authorize."""
    snapshot, history = _selected_completion_projection()
    envelopes = dict(history.envelopes)
    changed = dict(envelopes[evidence_id])
    changed["plan_id"] = "plan-attacker"
    changed["evidence_sha256"] = envelope_sha256(changed)
    envelopes[evidence_id] = MappingProxyType(changed)
    history = replace(history, envelopes=MappingProxyType(envelopes))

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == ({"reason": expected_reason},)


def test_selected_evidence_accepts_exact_current_plan_id_chain() -> None:
    """An exact source-bound preview/approval/review/completion chain passes."""
    snapshot, history = _selected_completion_projection()

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers == {}


def test_real_historical_preview_authorizes_current_preview() -> None:
    """A projected legacy source binds through version, digest, and envelope."""
    snapshot, seed_history = _approved_snapshot()
    snapshot = with_preview_source(snapshot)
    snapshot, history = project_real_historical_preview(snapshot, seed_history)

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers == {}


@pytest.mark.parametrize(
    ("tampering", "reason"),
    [
        ("envelope_plan_id", "active_preview_plan_mismatch"),
        ("source_version", "active_preview_source_invalid"),
        ("source_digest", "active_preview_source_invalid"),
        ("source_event_id", "active_preview_source_unavailable"),
    ],
)
def test_real_historical_preview_requires_exact_source_link(
    tampering: str, reason: str
) -> None:
    """The selected envelope and its legacy source must bind exactly."""
    snapshot, seed_history = _approved_snapshot()
    snapshot, history = project_real_historical_preview(
        with_preview_source(snapshot), seed_history
    )
    if tampering.startswith("source_") and tampering != "source_event_id":
        source = dict(snapshot.events[0])
        source["plan_version" if tampering == "source_version" else "plan_sha256"] = (
            2 if tampering == "source_version" else "0" * 64
        )
        snapshot = replace(snapshot, events=(MappingProxyType(source),))
    else:
        envelope = dict(history.envelopes["event-preview-1"])
        envelope["plan_id" if tampering == "envelope_plan_id" else "source_event_id"] = (
            "plan-attacker" if tampering == "envelope_plan_id" else "event-missing"
        )
        envelope["evidence_sha256"] = envelope_sha256(envelope)
        history = replace(
            history,
            envelopes=MappingProxyType({envelope["id"]: MappingProxyType(envelope)}),
        )

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == ({"reason": reason},)


def test_active_preview_accepts_immutable_snapshot_collections() -> None:
    """Frozen tuple and mapping collections retain exact source bindings."""
    snapshot, history = _approved_snapshot()
    snapshot = with_preview_source(snapshot)
    source = dict(snapshot.events[-1])
    source["rendered_slide_paths"] = tuple(
        MappingProxyType(entry) for entry in source["rendered_slide_paths"]
    )
    source["slides"] = tuple(MappingProxyType(entry) for entry in source["slides"])
    source["artifact_digests"] = MappingProxyType(source["artifact_digests"])
    source["artifact_bindings"] = MappingProxyType(
        {
            path: MappingProxyType(
                {
                    **binding,
                    **(
                        {"source_paths": tuple(binding["source_paths"])}
                        if "source_paths" in binding
                        else {}
                    ),
                }
            )
            for path, binding in source["artifact_bindings"].items()
        }
    )
    snapshot = replace(snapshot, events=(*snapshot.events[:-1], MappingProxyType(source)))

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers == {}


@pytest.mark.parametrize("tampering", ["path", "digest", "binding", "extra", "missing"])
def test_active_preview_binds_exact_source_artifact_declarations(
    tampering: str,
) -> None:
    """Source paths, digests, and bindings must match selected artifact refs."""
    snapshot, history = _approved_snapshot()
    snapshot = with_preview_source(snapshot)
    events = list(snapshot.events)
    source = dict(events[-1])
    if tampering == "path":
        source["rendered_slide_paths"][0]["path"] = "renders/substituted.png"
    elif tampering == "digest":
        source["artifact_digests"]["renders/slide-01.png"] = "0" * 64
    elif tampering == "binding":
        source["artifact_bindings"]["renders/slide-01.png"]["attempt"] = 2
    elif tampering == "missing":
        source["artifact_digests"].pop("renders/slide-01.png")
    else:
        source["artifact_digests"]["renders/extra.png"] = "0" * 64
    events[-1] = MappingProxyType(source)
    snapshot = replace(snapshot, events=tuple(events))

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == (
        {"reason": "active_preview_source_artifacts_invalid"},
    )


def test_active_preview_rejects_reordered_two_slide_source_paths() -> None:
    """Two-slide source paths must preserve selected artifact order."""
    snapshot, history = _approved_snapshot()
    snapshot, history = make_two_slide_preview(with_preview_source(snapshot), history)
    source = dict(snapshot.events[-1])
    source["rendered_slide_paths"][0]["path"], source["rendered_slide_paths"][1]["path"] = (
        source["rendered_slide_paths"][1]["path"], source["rendered_slide_paths"][0]["path"]
    )
    snapshot = replace(snapshot, events=(*snapshot.events[:-1], MappingProxyType(source)))

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == (
        {"reason": "active_preview_source_artifacts_invalid"},
    )


def test_active_preview_rejects_genuine_cas_backed_artifact_substitution() -> None:
    """Real attacker bytes cannot replace the source-declared preview bytes."""
    snapshot, history = _approved_snapshot()
    snapshot = with_preview_source(snapshot)
    snapshot, history = substitute_cas_backed_preview_artifact(snapshot, history)

    active = presentation_evidence_projection.project_active_evidence(snapshot, history)

    assert active.blockers["deck-1"] == (
        {"reason": "active_preview_source_artifacts_invalid"},
    )
