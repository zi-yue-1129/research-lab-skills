"""RED tests for immutable schema-v2 historical evidence conversion."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_evidence_contracts import envelope_sha256
from presentation_evidence_projection import ProjectionError, project_historical_evidence
from presentation_evidence_snapshot import EvidenceSnapshot, SnapshotError, build_snapshot


def _project(tmp_path: Path) -> Path:
    """Create one project root that accepts report-slides state."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _write_store(
    project: Path,
    name: str,
    top_key: str,
    records: dict[str, dict[str, Any]],
) -> Path:
    """Write one immutable state-store fixture."""
    path = project / ".research" / "presentations" / "state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": 1, top_key: records}, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _write_events(project: Path, events: list[dict[str, Any]]) -> Path:
    """Write exact JSONL bytes for immutable event fixtures."""
    path = project / ".research" / "presentations" / "events" / "2026-08-09.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
            for event in events
        )
    )
    return path


def _digest(content: bytes) -> str:
    """Return a hand-checkable SHA-256 fixture digest."""
    return hashlib.sha256(content).hexdigest()


def _preview_event(project: Path, *, event_id: str = "preview-historical") -> dict[str, Any]:
    """Create one exact historical draft-preview event and artifact bytes."""
    rendered_path = "evidence/slide-01.png"
    contact_path = "evidence/contact-sheet.png"
    rendered_content = b"historical-rendered-slide"
    contact_content = b"historical-contact-sheet"
    for relative_path, content in (
        (rendered_path, rendered_content),
        (contact_path, contact_content),
    ):
        target = project / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    rendered_digest = _digest(rendered_content)
    contact_digest = _digest(contact_content)
    plan_digest = "1" * 64
    payload: dict[str, Any] = {
        "schema_version": 1,
        "deck_id": "deck-temporal",
        "plan_version": 1,
        "plan_sha256": plan_digest,
        "rendered_slide_paths": [
            {
                "slide_id": "slide-01",
                "path": rendered_path,
                "slide_record_id": "slide-historical",
                "attempt": 1,
            }
        ],
        "contact_sheet_path": contact_path,
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Historical evidence",
                "key_takeaway": "History is not current state.",
            }
        ],
        "artifact_digests": {
            rendered_path: rendered_digest,
            contact_path: contact_digest,
        },
        "artifact_bindings": {
            rendered_path: {
                "kind": "rendered_slide",
                "deck_id": "deck-temporal",
                "slide_id": "slide-01",
                "plan_version": 1,
                "plan_sha256": plan_digest,
                "producer_id": "renderer-historical",
                "slide_record_id": "slide-historical",
                "attempt": 1,
            },
            contact_path: {
                "kind": "contact_sheet",
                "deck_id": "deck-temporal",
                "plan_version": 1,
                "plan_sha256": plan_digest,
                "producer_id": "renderer-historical",
                "source_paths": [rendered_path],
                "source_sha256": contract_sha256(
                    {"paths": [rendered_path], "digests": [rendered_digest]}
                ),
            },
        },
    }
    return {
        **payload,
        "event": "draft_preview",
        "id": event_id,
        "preview_sha256": contract_sha256(payload),
        "ts": "2026-08-09T00:00:00Z",
    }


def _evidence_source(
    evidence_kind: str,
    evidence_id: str,
    source_event_id: str,
) -> dict[str, Any]:
    """Create one exact immutable source envelope for completion references."""
    envelope: dict[str, Any] = {
        "id": evidence_id,
        "schema_version": 2,
        "evidence_kind": evidence_kind,
        "deck_id": "deck-temporal",
        "plan_id": "plan-historical",
        "plan_version": 1,
        "plan_sha256": "1" * 64,
        "subject_ids": ["deck-temporal"],
        "producer_id": "reviewer-historical",
        "artifact_refs": [],
        "source_event_id": source_event_id,
        "created_at": "2026-08-09T00:04:00Z",
        "availability": "available",
    }
    if evidence_kind == "draft_approval":
        envelope.update(
            {
                "preview_evidence_id": "preview-historical",
                "preview_evidence_sha256": "4" * 64,
                "decision": "approved",
                "approval_mode": "interactive",
                "approved_by": "reviewer-historical",
            }
        )
    envelope["evidence_sha256"] = envelope_sha256(envelope)
    return envelope


def _completion_events(project: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Create source-bound historical completion events and artifact records."""
    final_path = "evidence/deck.pptx"
    render_path = "evidence/deck-01.png"
    review_path = "evidence/visual-review.json"
    final_content = b"historical-pptx"
    render_content = b"historical-rendered-png"
    for relative_path, content in ((final_path, final_content), (render_path, render_content)):
        target = project / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    review_record = {
        "schema_version": 1,
        "deck_id": "deck-temporal",
        "output_format": "pptx",
        "artifacts": {"pptx": final_path},
        "statuses": {"pptx_render": {"rendered_png_paths": [render_path]}},
    }
    review_target = project / review_path
    review_target.parent.mkdir(parents=True, exist_ok=True)
    review_target.write_text(
        json.dumps(review_record, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    plan_digest = "1" * 64
    approval_event = {
        "schema_version": 1,
        "event": "deck_approval",
        "id": "approval-source-historical",
        "deck_id": "deck-temporal",
        "plan_version": 1,
        "plan_sha256": plan_digest,
        "approved_by": "reviewer-historical",
        "approved_at": "2026-08-09T00:03:00Z",
        "approval_mode": "interactive",
        "decision": "approve",
        "ts": "2026-08-09T00:03:00Z",
    }
    review_event = {
        "schema_version": 1,
        "event": "visual_review",
        "id": "review-source-historical",
        "deck_id": "deck-temporal",
        "plan_id": "plan-historical",
        "plan_version": 1,
        "plan_sha256": plan_digest,
        "producer_id": "reviewer-historical",
        "visual_review_path": review_path,
        "visual_review_sha256": contract_sha256(review_record),
        "ts": "2026-08-09T00:04:00Z",
    }
    approval = _evidence_source(
        "draft_approval", "approval-historical", approval_event["id"]
    )
    review = _evidence_source("visual_review", "review-historical", review_event["id"])
    payload: dict[str, Any] = {
        "schema_version": 1,
        "deck_id": "deck-temporal",
        "plan_id": "plan-historical",
        "plan_version": 1,
        "plan_sha256": plan_digest,
        "producer_id": "publisher-historical",
        "approval_evidence_id": approval["id"],
        "approval_evidence_sha256": approval["evidence_sha256"],
        "visual_review_evidence_id": review["id"],
        "visual_review_evidence_sha256": review["evidence_sha256"],
        "artifact_digests": {
            final_path: _digest(final_content),
            render_path: _digest(render_content),
        },
    }
    completion = {
        **payload,
        "event": "deck_completion",
        "id": "completion-historical",
        "completion_sha256": contract_sha256(payload),
        "ts": "2026-08-09T00:05:00Z",
    }
    _write_store(
        project,
        "artifacts.yaml",
        "artifacts",
        {
            "artifact-final": {
                "id": "artifact-final",
                "deck_id": "deck-temporal",
                "artifact_kind": "deck-pptx",
                "path": final_path,
                "sha256": _digest(final_content),
            },
            "artifact-render": {
                "id": "artifact-render",
                "deck_id": "deck-temporal",
                "artifact_kind": "slide-png",
                "path": render_path,
                "sha256": _digest(render_content),
            },
        },
    )
    return [approval_event, review_event, completion], {approval["id"]: approval, review["id"]: review}


def _historical_project(tmp_path: Path, *, completion: bool = False) -> tuple[Path, dict[str, Any], Path]:
    """Create a revised project whose history binds an older slide attempt."""
    project = _project(tmp_path)
    plan_digest = "1" * 64
    _write_store(
        project,
        "plans.yaml",
        "plans",
        {
            "plan-historical": {
                "id": "plan-historical",
                "deck_id": "deck-temporal",
                "version": 1,
                "plan_sha256": plan_digest,
            }
        },
    )
    _write_store(
        project,
        "slides.yaml",
        "slides",
        {
            "slide-current": {
                "id": "slide-current",
                "deck_id": "deck-temporal",
                "plan_slide_id": "slide-01",
                "title": "Revised slide",
                "status": "passed",
                "attempt": 2,
            }
        },
    )
    preview = _preview_event(project)
    events = [preview]
    if completion:
        completion_events, evidence = _completion_events(project)
        events.extend(completion_events)
        _write_store(project, "evidence.yaml", "evidence", evidence)
    event_path = _write_events(project, events)
    return project, preview, event_path


def test_historical_preview_survives_targeted_revision_without_current_binding(
    tmp_path: Path,
) -> None:
    """A historical preview stays available after its active slide is revised."""
    project, preview, _event_path = _historical_project(tmp_path)

    projection = project_historical_evidence(build_snapshot(project))

    envelope = projection.by_source_event_id[preview["id"]]
    assert envelope["availability"] == "available"
    assert envelope["id"] not in projection.current_pointer_ids
    assert envelope["subject_ids"] == ["slide-01"]
    assert set(projection.cas_objects) == {
        reference["sha256"] for reference in envelope["artifact_refs"]
    }


def test_historical_completion_survives_revision_without_current_binding(tmp_path: Path) -> None:
    """A historical completion does not need today's deck pointers or slides."""
    project, _preview, _event_path = _historical_project(tmp_path, completion=True)

    projection = project_historical_evidence(build_snapshot(project))

    envelope = projection.by_source_event_id["completion-historical"]
    assert envelope["evidence_kind"] == "deck_completion"
    assert envelope["availability"] == "available"
    assert envelope["id"] not in projection.current_pointer_ids


def test_missing_historical_bytes_become_unavailable_without_fabrication(tmp_path: Path) -> None:
    """A missing historic artifact creates no CAS plan and remains auditable."""
    project, preview, _event_path = _historical_project(tmp_path)
    (project / "evidence" / "slide-01.png").unlink()

    projection = project_historical_evidence(build_snapshot(project))

    assert projection.by_source_event_id[preview["id"]]["availability"] == "historical_unavailable"
    assert projection.cas_objects == {}


@pytest.mark.parametrize("tampering", ["digest", "metadata_order", "binding"])
def test_historical_preview_rejects_intrinsic_tampering(
    tmp_path: Path, tampering: str
) -> None:
    """Canonical event, ordered metadata, and bindings cannot be forged."""
    project, preview, _event_path = _historical_project(tmp_path)
    if tampering == "digest":
        preview["preview_sha256"] = "0" * 64
    elif tampering == "metadata_order":
        preview["slides"][0]["slide_id"] = "slide-other"
        payload = {
            key: value
            for key, value in preview.items()
            if key not in {"event", "id", "preview_sha256", "ts"}
        }
        preview["preview_sha256"] = contract_sha256(payload)
    else:
        preview["artifact_bindings"]["evidence/slide-01.png"]["attempt"] = 2
        payload = {
            key: value
            for key, value in preview.items()
            if key not in {"event", "id", "preview_sha256", "ts"}
        }
        preview["preview_sha256"] = contract_sha256(payload)
    _write_events(project, [preview])

    with pytest.raises(ProjectionError, match="digest|metadata|binding|attempt"):
        project_historical_evidence(build_snapshot(project))


def test_snapshot_preserves_jsonl_bytes_and_never_reloads_live_artifacts(tmp_path: Path) -> None:
    """Projection consumes frozen event and artifact bytes after construction."""
    project, preview, event_path = _historical_project(tmp_path)
    original_event_bytes = event_path.read_bytes()
    snapshot = build_snapshot(project)
    (project / "evidence" / "slide-01.png").write_bytes(b"mutated-after-snapshot")
    event_path.write_bytes(b'{"event":"forged"}\n')

    projection = project_historical_evidence(snapshot)

    assert snapshot.file_preimages[event_path] == original_event_bytes
    assert projection.by_source_event_id[preview["id"]]["availability"] == "available"
    assert next(iter(projection.cas_objects.values())).content != b"mutated-after-snapshot"


def test_snapshot_and_projection_do_not_write_during_dry_analysis(tmp_path: Path) -> None:
    """Snapshot analysis leaves the project tree unchanged before migration."""
    project, _preview, _event_path = _historical_project(tmp_path)
    before = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }

    project_historical_evidence(build_snapshot(project, locked=False))

    after = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }
    assert after == before


def test_artifact_maps_on_unregistered_event_kinds_fail_closed(tmp_path: Path) -> None:
    """An unregistered event cannot hide declared artifact provenance."""
    project = _project(tmp_path)
    _write_events(
        project,
        [
            {
                "event": "review_result",
                "id": "review-with-artifact-map",
                "artifact_digests": {"evidence/hidden.png": "0" * 64},
            }
        ],
    )

    with pytest.raises(SnapshotError, match="artifact maps"):
        build_snapshot(project)


def test_projection_rejects_artifact_maps_on_unregistered_event_kinds(
    tmp_path: Path,
) -> None:
    """Projection independently rejects a malformed prebuilt snapshot event."""
    project = _project(tmp_path).resolve()
    snapshot = EvidenceSnapshot(
        project_root=project,
        schema_version=0,
        stores=MappingProxyType({}),
        events=(
            MappingProxyType(
                {
                    "event": "review_result",
                    "id": "review-with-artifact-map",
                    "artifact_bindings": {"evidence/hidden.png": {}},
                }
            ),
        ),
        file_preimages=MappingProxyType({}),
    )

    with pytest.raises(ProjectionError, match="artifact maps"):
        project_historical_evidence(snapshot)


@pytest.mark.parametrize(
    ("reference_field", "expected_source"),
    [
        ("approval_evidence_id", "approval"),
        ("visual_review_evidence_id", "visual_review"),
    ],
)
def test_completion_rejects_nonexistent_referenced_evidence(
    tmp_path: Path, reference_field: str, expected_source: str
) -> None:
    """Completion links must resolve immutable historical evidence sources."""
    project, preview, _event_path = _historical_project(tmp_path, completion=True)
    completion_events, evidence = _completion_events(project)
    completion = completion_events[-1]
    completion[reference_field] = f"missing-{expected_source}"
    _refresh_completion_digest(completion)
    _write_events(project, [preview, *completion_events])
    _write_store(project, "evidence.yaml", "evidence", evidence)

    with pytest.raises(ProjectionError, match=f"{expected_source}.*resolve"):
        project_historical_evidence(build_snapshot(project))


def test_completion_rejects_artifacts_not_derived_from_visual_review(tmp_path: Path) -> None:
    """A completion cannot add bytes beyond its referenced review outputs."""
    project, preview, _event_path = _historical_project(tmp_path, completion=True)
    completion_events, evidence = _completion_events(project)
    completion = completion_events[-1]
    extra_path = "evidence/arbitrary.png"
    extra_content = b"not-reviewed"
    (project / extra_path).write_bytes(extra_content)
    completion["artifact_digests"][extra_path] = _digest(extra_content)
    _refresh_completion_digest(completion)
    _write_events(project, [preview, *completion_events])
    _write_store(project, "evidence.yaml", "evidence", evidence)

    with pytest.raises(ProjectionError, match="artifact.*visual review"):
        project_historical_evidence(build_snapshot(project))


def test_completion_rejects_preview_style_artifact_bindings(tmp_path: Path) -> None:
    """Completion evidence must derive outputs rather than accept preview bindings."""
    project, preview, _event_path = _historical_project(tmp_path, completion=True)
    completion_events, evidence = _completion_events(project)
    completion = completion_events[-1]
    completion["artifact_bindings"] = {
        "evidence/deck.pptx": {"kind": "final_pptx", "deck_id": "deck-temporal"},
        "evidence/deck-01.png": {
            "kind": "rendered_png",
            "deck_id": "deck-temporal",
        },
    }
    _refresh_completion_digest(completion)
    _write_events(project, [preview, *completion_events])
    _write_store(project, "evidence.yaml", "evidence", evidence)

    with pytest.raises(ProjectionError, match="artifact_bindings"):
        project_historical_evidence(build_snapshot(project))


def _refresh_completion_digest(completion: dict[str, Any]) -> None:
    """Recompute a mutated fixture's intrinsic completion digest."""
    payload = {
        key: value
        for key, value in completion.items()
        if key not in {"event", "id", "completion_sha256", "ts"}
    }
    completion["completion_sha256"] = contract_sha256(payload)


@pytest.mark.parametrize(
    "relative_lock",
    [
        ".research/presentations/state/workflow.lock",
        ".research/presentations/state/decks.yaml.lock",
        ".research/presentations/events/2026-08-09.jsonl.lock",
    ],
)
def test_snapshot_accepts_canonical_operational_locks(
    tmp_path: Path, relative_lock: str
) -> None:
    """Regular canonical locks remain operational even when their target is absent."""
    project = _project(tmp_path)
    lock = project / relative_lock
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("held", encoding="utf-8")

    snapshot = build_snapshot(project)

    assert snapshot.events == ()
    assert snapshot.stores == {}


@pytest.mark.parametrize(
    "relative_lock",
    [
        ".research/presentations/state/unknown.yaml.lock",
        ".research/presentations/events/not-a-date.jsonl.lock",
    ],
)
def test_snapshot_rejects_malformed_operational_locks(
    tmp_path: Path, relative_lock: str
) -> None:
    """Locks outside the canonical state or shard grammar fail closed."""
    project = _project(tmp_path)
    lock = project / relative_lock
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("held", encoding="utf-8")

    with pytest.raises(SnapshotError, match="sidecar|shard"):
        build_snapshot(project)


def test_snapshot_rejects_symlink_operational_lock(tmp_path: Path) -> None:
    """A canonical lock name cannot bypass no-follow capture through a symlink."""
    project = _project(tmp_path)
    target = tmp_path / "outside.lock"
    target.write_text("outside", encoding="utf-8")
    lock = project / ".research/presentations/state/workflow.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.symlink_to(target)

    with pytest.raises(SnapshotError, match="unsafe presentation state scope entry"):
        build_snapshot(project)


def test_snapshot_rejects_special_operational_lock(tmp_path: Path) -> None:
    """A FIFO lock is never treated as a regular operational sidecar."""
    project = _project(tmp_path)
    lock = project / ".research/presentations/events/2026-08-09.jsonl.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(lock)

    with pytest.raises(SnapshotError, match="unsafe presentation event scope entry"):
        build_snapshot(project)
