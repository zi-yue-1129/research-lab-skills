"""Reusable exact-source fixtures for active evidence tests."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from types import MappingProxyType

from presentation_contracts import contract_sha256
from presentation_evidence_cas import CasObject, cas_relative_path
from presentation_evidence_contracts import envelope_sha256
from presentation_evidence_projection import HistoricalProjection, project_historical_evidence
from presentation_evidence_snapshot import EvidenceSnapshot, PlanPreimage


def with_preview_source(snapshot: EvidenceSnapshot) -> EvidenceSnapshot:
    """Add a frozen legacy source event matching the default current preview.

    Args:
        snapshot: One-slide active snapshot without a preview audit event.

    Returns:
        The snapshot with a matching legacy preview source appended.
    """
    plan_sha256 = snapshot.stores["decks"]["deck-1"]["approved_plan_sha256"]
    rendered_digest = snapshot.stores["artifacts"]["artifact-render"]["sha256"]
    contact_digest = snapshot.stores["artifacts"]["artifact-contact"]["sha256"]
    source_paths = ["renders/slide-01.png"]
    source = {
        "id": "event-preview-1",
        "event": "draft_preview",
        "deck_id": "deck-1",
        "plan_version": 1,
        "plan_sha256": plan_sha256,
        "rendered_slide_paths": [
            {
                "slide_id": "slide-01",
                "path": source_paths[0],
                "slide_record_id": "slide-record-1",
                "attempt": 1,
            }
        ],
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Exact current title",
                "key_takeaway": "Exact current takeaway.",
            }
        ],
        "contact_sheet_path": "renders/contact-sheet.png",
        "artifact_digests": {
            source_paths[0]: rendered_digest,
            "renders/contact-sheet.png": contact_digest,
        },
        "artifact_bindings": {
            source_paths[0]: {
                "kind": "rendered_slide",
                "deck_id": "deck-1",
                "slide_id": "slide-01",
                "plan_version": 1,
                "plan_sha256": plan_sha256,
                "producer_id": "test-producer",
                "slide_record_id": "slide-record-1",
                "attempt": 1,
            },
            "renders/contact-sheet.png": {
                "kind": "contact_sheet",
                "deck_id": "deck-1",
                "plan_version": 1,
                "plan_sha256": plan_sha256,
                "producer_id": "test-producer",
                "source_paths": source_paths,
                "source_sha256": contract_sha256(
                    {"paths": source_paths, "digests": [rendered_digest]}
                ),
            },
        },
    }
    return replace(snapshot, events=(*snapshot.events, MappingProxyType(source)))


def project_real_historical_preview(
    snapshot: EvidenceSnapshot, history: HistoricalProjection
) -> tuple[EvidenceSnapshot, HistoricalProjection]:
    """Project a legacy preview event through the real historical converter.

    Args:
        snapshot: One-slide active snapshot containing a complete preview source.
        history: Hand fixture supplying the source artifact bytes.

    Returns:
        The snapshot with an exact schema-v1 event and its real projection.
    """
    source = dict(snapshot.events[-1])
    source.pop("plan_id", None)
    source.update(
        {
            "schema_version": 1,
            "event": "draft_preview",
            "id": "event-preview-1",
            "ts": "2026-08-09T00:00:00Z",
        }
    )
    payload = {
        key: value
        for key, value in source.items()
        if key not in {"event", "id", "preview_sha256", "ts"}
    }
    source["preview_sha256"] = contract_sha256(payload)
    deck = dict(snapshot.stores["decks"]["deck-1"])
    deck["draft_preview_evidence_id"] = source["id"]
    stores = dict(snapshot.stores)
    stores["decks"] = MappingProxyType({"deck-1": MappingProxyType(deck)})
    source_objects = {
        reference["original_path"]: history.cas_objects[reference["sha256"]]
        for reference in history.envelopes["preview-1"]["artifact_refs"]
    }
    updated = replace(
        snapshot,
        stores=MappingProxyType(stores),
        events=(MappingProxyType(source),),
        artifact_objects=MappingProxyType(source_objects),
    )
    return updated, project_historical_evidence(updated)


def make_two_slide_preview(
    snapshot: EvidenceSnapshot, history: HistoricalProjection
) -> tuple[EvidenceSnapshot, HistoricalProjection]:
    """Extend a valid active preview fixture to two authoritative slides.

    Args:
        snapshot: One-slide active snapshot with its preview source event.
        history: Matching one-slide historical projection fixture.

    Returns:
        Updated snapshot and history containing a valid two-slide preview.
    """
    plan = {
        "deck_id": "deck-1",
        "plan_version": 1,
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Exact current title",
                "key_takeaway": "Exact current takeaway.",
            },
            {
                "slide_id": "slide-02",
                "title": "Second exact title",
                "key_takeaway": "Second exact takeaway.",
            },
        ],
    }
    plan_digest = contract_sha256(plan)
    plan_content = (
        b"deck_id: deck-1\nplan_version: 1\nslides:\n"
        b"  - slide_id: slide-01\n    title: Exact current title\n"
        b"    key_takeaway: Exact current takeaway.\n"
        b"  - slide_id: slide-02\n    title: Second exact title\n"
        b"    key_takeaway: Second exact takeaway.\n"
    )
    second_content = b"rendered-slide-two"
    second_digest = hashlib.sha256(second_content).hexdigest()
    second_path = "renders/slide-02.png"
    second_ref = {
        "sha256": second_digest,
        "cas_path": cas_relative_path(second_digest).as_posix(),
        "artifact_kind": "rendered_slide",
        "subject_id": "slide-02",
        "original_path": second_path,
    }
    second_object = CasObject(
        second_digest, cas_relative_path(second_digest), second_content, 0o444
    )
    stores = {name: dict(records) for name, records in snapshot.stores.items()}
    deck = dict(stores["decks"]["deck-1"])
    deck["approved_plan_sha256"] = plan_digest
    stores["decks"]["deck-1"] = MappingProxyType(deck)
    plan_record = dict(stores["plans"]["plan-1"])
    plan_record["plan_sha256"] = plan_digest
    stores["plans"]["plan-1"] = MappingProxyType(plan_record)
    stores["slides"]["slide-record-2"] = MappingProxyType(
        {
            "id": "slide-record-2",
            "deck_id": "deck-1",
            "plan_slide_id": "slide-02",
            "title": "Second exact title",
            "status": "passed",
            "attempt": 1,
        }
    )
    stores["artifacts"]["artifact-render-2"] = MappingProxyType(
        {
            "id": "artifact-render-2",
            "deck_id": "deck-1",
            "artifact_kind": "slide-png",
            "path": second_path,
            "sha256": second_digest,
            "slide_record_id": "slide-record-2",
            "attempt": 1,
        }
    )
    source = dict(snapshot.events[-1])
    source["plan_sha256"] = plan_digest
    source["rendered_slide_paths"] = [
        dict(source["rendered_slide_paths"][0]),
        {
            "slide_id": "slide-02",
            "path": second_path,
            "slide_record_id": "slide-record-2",
            "attempt": 1,
        },
    ]
    source["slides"] = [
        dict(source["slides"][0]),
        {
            "slide_id": "slide-02",
            "title": "Second exact title",
            "key_takeaway": "Second exact takeaway.",
        },
    ]
    source["artifact_digests"] = {
        **source["artifact_digests"],
        second_path: second_digest,
    }
    first_path = source["rendered_slide_paths"][0]["path"]
    contact_path = source["contact_sheet_path"]
    bindings = {path: dict(binding) for path, binding in source["artifact_bindings"].items()}
    bindings[first_path]["plan_sha256"] = plan_digest
    bindings[second_path] = {
        "kind": "rendered_slide",
        "deck_id": "deck-1",
        "slide_id": "slide-02",
        "plan_version": 1,
        "plan_sha256": plan_digest,
        "producer_id": "test-producer",
        "slide_record_id": "slide-record-2",
        "attempt": 1,
    }
    source_paths = [first_path, second_path]
    bindings[contact_path].update(
        {
            "plan_sha256": plan_digest,
            "source_paths": source_paths,
            "source_sha256": contract_sha256(
                {
                    "paths": source_paths,
                    "digests": [source["artifact_digests"][path] for path in source_paths],
                }
            ),
        }
    )
    source["artifact_bindings"] = bindings
    preview = dict(history.envelopes["preview-1"])
    preview.update(
        {
            "plan_sha256": plan_digest,
            "subject_ids": ["slide-01", "slide-02"],
            "artifact_refs": [preview["artifact_refs"][0], second_ref, preview["artifact_refs"][1]],
        }
    )
    preview["evidence_sha256"] = envelope_sha256(preview)
    objects = dict(history.cas_objects)
    objects[second_digest] = second_object
    preimages = dict(snapshot.active_plan_preimages)
    preimages["plan-1"] = PlanPreimage(
        path=preimages["plan-1"].path,
        content=plan_content,
        mode=0o644,
        mtime_ns=0,
        sha256=hashlib.sha256(plan_content).hexdigest(),
    )
    return (
        replace(
            snapshot,
            stores=MappingProxyType(
                {name: MappingProxyType(records) for name, records in stores.items()}
            ),
            events=(*snapshot.events[:-1], MappingProxyType(source)),
            active_plan_preimages=MappingProxyType(preimages),
        ),
        replace(
            history,
            envelopes=MappingProxyType({"preview-1": MappingProxyType(preview)}),
            cas_objects=MappingProxyType(objects),
        ),
    )


def substitute_cas_backed_preview_artifact(
    snapshot: EvidenceSnapshot, history: HistoricalProjection
) -> tuple[EvidenceSnapshot, HistoricalProjection]:
    """Replace a selected ref with genuine attacker bytes and records.

    Args:
        snapshot: Active snapshot whose source declaration stays unchanged.
        history: Projection whose selected reference will be substituted.

    Returns:
        Updated snapshot/history with a fully CAS-backed attacker artifact.
    """
    attacker_content = b"attacker-rendered-slide"
    attacker_digest = hashlib.sha256(attacker_content).hexdigest()
    attacker_object = CasObject(
        attacker_digest, cas_relative_path(attacker_digest), attacker_content, 0o444
    )
    preview = dict(history.envelopes["preview-1"])
    substituted = dict(preview["artifact_refs"][0])
    substituted["sha256"] = attacker_digest
    substituted["cas_path"] = cas_relative_path(attacker_digest).as_posix()
    preview["artifact_refs"] = [substituted, *preview["artifact_refs"][1:]]
    preview["evidence_sha256"] = envelope_sha256(preview)
    stores = {name: dict(records) for name, records in snapshot.stores.items()}
    artifact = dict(stores["artifacts"]["artifact-render"])
    artifact["sha256"] = attacker_digest
    stores["artifacts"]["artifact-render"] = MappingProxyType(artifact)
    objects = dict(history.cas_objects)
    objects[attacker_digest] = attacker_object
    return (
        replace(
            snapshot,
            stores=MappingProxyType(
                {name: MappingProxyType(records) for name, records in stores.items()}
            ),
        ),
        replace(
            history,
            envelopes=MappingProxyType({"preview-1": MappingProxyType(preview)}),
            cas_objects=MappingProxyType(objects),
        ),
    )
