"""RED tests for Task 8 migration fix round six."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

import migrate_presentation_state as migration
from migration_scope import MigrationError, validate_record_paths
from presentation_evidence_contracts import legacy_nullable_path_fields


STORE_TOP_KEYS = {
    "decks.yaml": "decks",
    "slides.yaml": "slides",
    "visual_modules.yaml": "visual_modules",
    "assignments.yaml": "assignments",
}


def _project(tmp_path: Path) -> Path:
    """Create one minimal project root for migration fixtures."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _presentations(project: Path) -> Path:
    """Return the presentation-state root."""
    return project / ".research" / "presentations"


def _write_store(
    project: Path,
    name: str,
    records: dict[str, dict[str, Any]],
    *,
    version: int = 1,
) -> Path:
    """Write one canonical presentation state store."""
    path = _presentations(project) / "state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"version": version, STORE_TOP_KEYS[name]: records},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_event(project: Path, event: dict[str, Any]) -> Path:
    """Write one immutable event shard."""
    path = _presentations(project) / "events" / "2026-08-09.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _snapshot(root: Path) -> dict[str, tuple[str, bytes, int, int]]:
    """Capture exact file, directory, link, mode, and mtime evidence."""
    result: dict[str, tuple[str, bytes, int, int]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = ("symlink", os.readlink(path).encode(), 0, 0)
        elif path.is_file():
            metadata = path.stat()
            result[relative] = (
                "file",
                path.read_bytes(),
                metadata.st_mode & 0o777,
                metadata.st_mtime_ns,
            )
        elif path.is_dir():
            metadata = path.stat()
            result[relative] = (
                "directory",
                b"",
                metadata.st_mode & 0o777,
                metadata.st_mtime_ns,
            )
    return result


def _canonical_digest(value: dict[str, Any]) -> str:
    """Compute the producer contract digest without migration helpers."""
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _public_slide_record(
    *,
    slide_id: str = "sld-current",
    deck_id: str = "deck-round6",
    status: str = "planned",
    slide_spec_path: str | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """Return the exact public ``create_slide`` record shape."""
    return {
        "id": slide_id,
        "deck_id": deck_id,
        "plan_slide_id": "slide-01",
        "title": "Evidence changes decisions",
        "status": status,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
        "created_by": "user",
        "approved_takeaway_sha256": None,
        "approved_evidence_sha256": None,
        "slide_spec_path": slide_spec_path,
        "slide_spec_sha256": None,
        "attempt": attempt,
    }


def _public_module_record() -> dict[str, Any]:
    """Return the exact public ``create_visual_module`` record shape."""
    return {
        "id": "mod-current",
        "slide_id": "sld-current",
        "module_key": "observation-input",
        "module_type": "architecture",
        "dependencies": [],
        "status": "planned",
        "visual_spec_path": None,
        "assignment_path": None,
        "artifact_manifest_path": None,
        "attempt": 1,
        "supersedes_module_id": None,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
        "created_by": "user",
    }


def _replacement_slide_record() -> dict[str, Any]:
    """Return the exact public targeted-revision slide replacement shape."""
    record = _public_slide_record(attempt=2)
    record.pop("updated_at")
    record.update(
        {
            "supersedes_slide_id": "sld-prior",
            "revision_request_id": "rev-round6",
            "revision_kind": "slide_retry",
        }
    )
    return record


def _replacement_module_record() -> dict[str, Any]:
    """Return the exact public targeted-revision module replacement shape."""
    record = _public_module_record()
    record.pop("updated_at")
    record.update(
        {
            "attempt": 2,
            "supersedes_module_id": "mod-prior",
            "revision_request_id": "rev-round6",
            "revision_kind": "module_retry",
        }
    )
    return record


def _forged_assignment_record() -> dict[str, Any]:
    """Return an assignment record carrying spoofed module identity fields."""
    return {
        "id": "asn-forged",
        "deck_id": "deck-round6",
        "slide_id": "sld-current",
        "module_id": "mod-current",
        "assignment_path": None,
        "path": "contracts/assignment.yaml",
        "relative_path": "contracts/assignment.yaml",
        "worker_id": "worker-a",
        "worker": "worker-a",
        "worker_type": "architecture",
        "dependencies": [],
        "spec_sha256": "1" * 64,
        "inputs_resolved": True,
        "blocker": None,
        "assigned_at": "2026-08-09T00:00:00Z",
        "created_at": "2026-08-09T00:00:00Z",
        "module_key": "spoofed-module",
        "module_type": "architecture",
        "status": "planned",
    }


def _draft_preview_fixture(project: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create an exact producer-shaped persisted draft preview and current slide."""
    render_dir = project / "renders"
    contract_dir = project / "contracts"
    render_dir.mkdir(parents=True)
    contract_dir.mkdir(parents=True)
    slide_path = render_dir / "slide-01.png"
    contact_path = render_dir / "contact-sheet.png"
    slide_spec = contract_dir / "slide-spec.yaml"
    slide_path.write_bytes(b"slide-png-round6")
    contact_path.write_bytes(b"contact-png-round6")
    slide_spec.write_text("schema_version: 1\n", encoding="utf-8")
    slide_relative = "renders/slide-01.png"
    contact_relative = "renders/contact-sheet.png"
    slide_digest = hashlib.sha256(slide_path.read_bytes()).hexdigest()
    contact_digest = hashlib.sha256(contact_path.read_bytes()).hexdigest()
    source_sha256 = _canonical_digest(
        {"paths": [slide_relative], "digests": [slide_digest]}
    )
    plan_sha256 = "1" * 64
    slide = _public_slide_record(
        status="passed",
        slide_spec_path="contracts/slide-spec.yaml",
    )
    preview = {
        "schema_version": 1,
        "deck_id": "deck-round6",
        "plan_version": 1,
        "plan_sha256": plan_sha256,
        "rendered_slide_paths": [
            {
                "slide_id": "slide-01",
                "path": slide_relative,
                "slide_record_id": slide["id"],
                "attempt": slide["attempt"],
            }
        ],
        "contact_sheet_path": contact_relative,
        "slides": [
            {
                "slide_id": "slide-01",
                "title": "Evidence changes decisions",
                "key_takeaway": "Evidence changes decisions.",
            }
        ],
        "artifact_digests": {
            slide_relative: slide_digest,
            contact_relative: contact_digest,
        },
        "artifact_bindings": {
            slide_relative: {
                "kind": "rendered_slide",
                "deck_id": "deck-round6",
                "slide_id": "slide-01",
                "plan_version": 1,
                "plan_sha256": plan_sha256,
                "producer_id": "renderer",
                "slide_record_id": slide["id"],
                "attempt": slide["attempt"],
            },
            contact_relative: {
                "kind": "contact_sheet",
                "deck_id": "deck-round6",
                "plan_version": 1,
                "plan_sha256": plan_sha256,
                "producer_id": "renderer",
                "source_paths": [slide_relative],
                "source_sha256": source_sha256,
            },
        },
    }
    event = {
        **preview,
        "event": "draft_preview",
        "id": "draft-round6",
        "preview_sha256": _canonical_digest(preview),
        "ts": "2026-08-09T00:00:00Z",
    }
    return event, slide


def _draft_preview_project(tmp_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Create a target-schema project containing one persisted draft preview."""
    project = _project(tmp_path)
    event, slide = _draft_preview_fixture(project)
    _write_store(
        project,
        "decks.yaml",
        {
            "deck-round6": {
                "id": "deck-round6",
                "title": "Round six",
                "status": "planning",
            }
        },
    )
    _write_store(project, "slides.yaml", {slide["id"]: slide})
    _write_event(project, event)
    return project, event, slide


def _path_keyed_files(project: Path) -> list[str]:
    """Create three ordered artifact paths for mapping validation."""
    paths = ["artifacts/first.bin", "artifacts/middle.bin", "artifacts/last.bin"]
    for index, relative in enumerate(paths):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"artifact-{index}".encode())
    return paths


def _artifact_binding(path_index: int) -> dict[str, Any]:
    """Return one structurally exact non-draft rendered-artifact binding."""
    return {
        "kind": "rendered_slide",
        "deck_id": "deck-round6",
        "slide_id": f"slide-{path_index + 1:02d}",
        "plan_version": 1,
        "plan_sha256": "1" * 64,
        "producer_id": "renderer",
        "slide_record_id": f"sld-{path_index + 1}",
        "attempt": 1,
    }


def _completion_event(project: Path) -> dict[str, Any]:
    """Return a current deck-completion event with canonical digest evidence."""
    paths = _path_keyed_files(project)
    return {
        "event": "deck_completion",
        "id": "completion-round6",
        "deck_id": "deck-round6",
        "ts": "2026-08-09T00:00:00Z",
        "artifact_digests": {
            relative: hashlib.sha256((project / relative).read_bytes()).hexdigest()
            for relative in paths
        },
    }


def test_store_context_rejects_assignment_spoofing_module_nullability(
    tmp_path: Path,
) -> None:
    """An assignments-store record cannot spoof a planned module schema."""
    project = _project(tmp_path)
    assignment_path = project / "contracts" / "assignment.yaml"
    assignment_path.parent.mkdir()
    assignment_path.write_text("schema_version: 1\n", encoding="utf-8")

    with pytest.raises(MigrationError, match="assignment_path|assignments|schema"):
        validate_record_paths(
            project,
            _forged_assignment_record(),
            store_name="assignments",
        )


def test_mixed_slide_module_identity_cannot_grant_misplaced_nullable_path(
    tmp_path: Path,
) -> None:
    """Extra module identity fields cannot widen one slide record's schema."""
    project = _project(tmp_path)
    record = _public_slide_record()
    record.update(
        {
            "module_key": "spoofed-module",
            "module_type": "architecture",
            "assignment_path": None,
        }
    )

    with pytest.raises(MigrationError, match="assignment_path|mixed|schema"):
        validate_record_paths(project, record, store_name="slides")


@pytest.mark.parametrize("dry_run", [False, True])
def test_assignment_store_spoofing_is_rejected_end_to_end(
    tmp_path: Path,
    dry_run: bool,
) -> None:
    """Migration rejects forged assignment nullability before any mutation."""
    project = _project(tmp_path)
    assignment_path = project / "contracts" / "assignment.yaml"
    assignment_path.parent.mkdir()
    assignment_path.write_text("schema_version: 1\n", encoding="utf-8")
    forged = _forged_assignment_record()
    _write_store(project, "assignments.yaml", {forged["id"]: forged})
    before = _snapshot(_presentations(project))

    with pytest.raises(MigrationError, match="assignment_path|assignments|schema"):
        migration.migrate_state(project, dry_run=dry_run)

    assert _snapshot(_presentations(project)) == before


def test_exact_public_planned_slide_and_module_records_keep_nullable_paths(
    tmp_path: Path,
) -> None:
    """Authoritative planned public records retain only documented nulls."""
    project = _project(tmp_path)
    slide = _public_slide_record()
    module = _public_module_record()

    assert legacy_nullable_path_fields("slides", slide) == {"slide_spec_path"}
    assert legacy_nullable_path_fields("visual_modules", module) == {
        "visual_spec_path",
        "assignment_path",
        "artifact_manifest_path",
    }
    validate_record_paths(project, slide, store_name="slides")
    validate_record_paths(
        project,
        module,
        store_name="visual_modules",
    )


@pytest.mark.parametrize(
    "alias_fields",
    [
        {"visual_spec_sha256": "1" * 64},
        {"visual_spec_sha256": None, "spec_sha256": "1" * 64},
        {"visual_spec_sha256": True, "spec_sha256": True},
    ],
)
def test_migration_scope_rejects_invalid_planned_module_alias_path_combinations(
    tmp_path: Path,
    alias_fields: dict[str, Any],
) -> None:
    """Nullable paths cannot hide invalid visual-spec digest alias state."""
    project = _project(tmp_path)
    record = _public_module_record()
    record.update(alias_fields)

    with pytest.raises(MigrationError, match="visual_modules|spec|schema|digest"):
        validate_record_paths(project, record, store_name="visual_modules")


@pytest.mark.parametrize(
    ("store_name", "record"),
    [
        ("slides", _replacement_slide_record()),
        ("visual_modules", _replacement_module_record()),
    ],
)
def test_exact_public_revision_replacements_keep_nullable_paths(
    tmp_path: Path,
    store_name: str,
    record: dict[str, Any],
) -> None:
    """Current targeted-revision replacement schemas remain migratable."""
    project = _project(tmp_path)

    validate_record_paths(project, record, store_name=store_name)


def test_draft_preview_requires_current_identity_pair(tmp_path: Path) -> None:
    """Every persisted rendered entry includes current record and attempt."""
    project, event, _slide = _draft_preview_project(tmp_path)
    entry = event["rendered_slide_paths"][0]
    entry.pop("slide_record_id")
    entry.pop("attempt")
    payload = {
        key: value
        for key, value in event.items()
        if key not in {"event", "id", "preview_sha256", "ts"}
    }
    event["preview_sha256"] = _canonical_digest(payload)
    _write_event(project, event)

    with pytest.raises(MigrationError, match="slide_record_id|attempt|identity"):
        migration.migrate_state(project, dry_run=True)


@pytest.mark.parametrize("mutation", ["missing", "forged", "wrong_type", "extra_field"])
def test_draft_preview_requires_exact_recomputed_producer_digest(
    tmp_path: Path,
    mutation: str,
) -> None:
    """Persisted preview metadata must match the exact pre-event payload."""
    project, event, _slide = _draft_preview_project(tmp_path)
    if mutation == "missing":
        event.pop("preview_sha256")
    elif mutation == "forged":
        event["preview_sha256"] = "0" * 64
    elif mutation == "wrong_type":
        event["preview_sha256"] = True
    else:
        event["unexpected_persisted_field"] = "forged"
    _write_event(project, event)

    with pytest.raises(MigrationError, match="preview_sha256|persisted|canonical|field"):
        migration.migrate_state(project, dry_run=True)


def test_draft_preview_rejects_internally_consistent_stale_slide_identity(
    tmp_path: Path,
) -> None:
    """Preview identity is bound to the current slide store, not itself."""
    project, event, _slide = _draft_preview_project(tmp_path)
    event["rendered_slide_paths"][0].update(
        {"slide_record_id": "sld-stale", "attempt": 2}
    )
    event["artifact_bindings"]["renders/slide-01.png"].update(
        {"slide_record_id": "sld-stale", "attempt": 2}
    )
    payload = {
        key: value
        for key, value in event.items()
        if key not in {"event", "id", "preview_sha256", "ts"}
    }
    event["preview_sha256"] = _canonical_digest(payload)
    _write_event(project, event)

    with pytest.raises(MigrationError, match="current|stale|slide_record_id|attempt"):
        migration.migrate_state(project, dry_run=True)


def test_exact_producer_shaped_draft_preview_migrates_without_event_rewrite(
    tmp_path: Path,
) -> None:
    """An exact legacy producer event reaches v2 without an audit-byte rewrite."""
    project, _event, _slide = _draft_preview_project(tmp_path)
    before = _snapshot(_presentations(project))
    event_path = _presentations(project) / "events" / "2026-08-09.jsonl"

    report = migration.migrate_state(project, dry_run=False)

    assert report["source_schema_version"] == 1
    assert report["target_schema_version"] == 2
    assert report["migrated_ids"] == ["deck-round6", "sld-current"]
    assert report["blocked_ids"] == []
    assert report["changed_paths"]
    assert event_path.read_bytes() == before["events/2026-08-09.jsonl"][1]


def test_legacy_deck_completion_is_preserved_without_event_rewrite(tmp_path: Path) -> None:
    """An unprojectable legacy completion stays immutable while schema state advances."""
    project = _project(tmp_path)
    _write_event(project, _completion_event(project))
    before = _snapshot(_presentations(project))
    event_path = _presentations(project) / "events" / "2026-08-09.jsonl"

    report = migration.migrate_state(project, dry_run=False)

    assert report["source_schema_version"] == 0
    assert report["target_schema_version"] == 2
    assert report["changed_paths"]
    assert event_path.read_bytes() == before["events/2026-08-09.jsonl"][1]


@pytest.mark.parametrize("position", [0, 1, 2])
def test_every_non_draft_artifact_digest_is_validated(
    tmp_path: Path,
    position: int,
) -> None:
    """Malformed first, middle, and last digests identify their own path."""
    project = _project(tmp_path)
    event = _completion_event(project)
    bad_path = list(event["artifact_digests"])[position]
    event["artifact_digests"][bad_path] = "not-a-digest"

    with pytest.raises(MigrationError, match=bad_path):
        validate_record_paths(project, event)


@pytest.mark.parametrize("position", [0, 1, 2])
def test_every_non_draft_artifact_binding_is_validated(
    tmp_path: Path,
    position: int,
) -> None:
    """Malformed first, middle, and last bindings identify their own path."""
    project = _project(tmp_path)
    paths = _path_keyed_files(project)
    event = {
        "event": "artifact_batch",
        "id": "artifact-batch-round6",
        "artifact_bindings": {
            path: _artifact_binding(index) for index, path in enumerate(paths)
        },
    }
    bad_path = paths[position]
    event["artifact_bindings"][bad_path]["attempt"] = 0

    with pytest.raises(MigrationError, match=bad_path):
        validate_record_paths(project, event)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("traversal_key", "path|traversal|relative"),
        ("missing_key", "path|target|exist"),
        ("uppercase_digest", "digest|SHA-256"),
        ("short_digest", "digest|SHA-256"),
    ],
)
def test_non_draft_digest_mapping_keeps_exact_path_and_digest_safety(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    """Completion evidence retains canonical paths and exact digest syntax."""
    project = _project(tmp_path)
    event = _completion_event(project)
    first_path = next(iter(event["artifact_digests"]))
    if mutation == "traversal_key":
        event["artifact_digests"]["../outside.bin"] = event["artifact_digests"].pop(
            first_path
        )
    elif mutation == "missing_key":
        event["artifact_digests"]["artifacts/missing.bin"] = event[
            "artifact_digests"
        ].pop(first_path)
    elif mutation == "uppercase_digest":
        event["artifact_digests"][first_path] = "A" * 64
    else:
        event["artifact_digests"][first_path] = "0" * 63

    with pytest.raises(MigrationError, match=expected):
        validate_record_paths(project, event)
