"""RED tests for immutable schema-v2 historical evidence conversion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_evidence_projection import ProjectionError, project_historical_evidence
from presentation_evidence_snapshot import build_snapshot


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


def _completion_event(project: Path) -> dict[str, Any]:
    """Create one intrinsically complete historical deck-completion event."""
    final_path = "evidence/deck.pptx"
    render_path = "evidence/deck-01.png"
    final_content = b"historical-pptx"
    render_content = b"historical-rendered-png"
    for relative_path, content in ((final_path, final_content), (render_path, render_content)):
        target = project / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    plan_digest = "1" * 64
    payload: dict[str, Any] = {
        "schema_version": 1,
        "deck_id": "deck-temporal",
        "plan_id": "plan-historical",
        "plan_version": 1,
        "plan_sha256": plan_digest,
        "producer_id": "publisher-historical",
        "approval_evidence_id": "approval-historical",
        "approval_evidence_sha256": "2" * 64,
        "visual_review_evidence_id": "review-historical",
        "visual_review_evidence_sha256": "3" * 64,
        "artifact_digests": {
            final_path: _digest(final_content),
            render_path: _digest(render_content),
        },
        "artifact_bindings": {
            final_path: {"kind": "final_pptx", "deck_id": "deck-temporal"},
            render_path: {"kind": "rendered_png", "deck_id": "deck-temporal"},
        },
    }
    return {
        **payload,
        "event": "deck_completion",
        "id": "completion-historical",
        "completion_sha256": contract_sha256(payload),
        "ts": "2026-08-09T00:05:00Z",
    }


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
        events.append(_completion_event(project))
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
