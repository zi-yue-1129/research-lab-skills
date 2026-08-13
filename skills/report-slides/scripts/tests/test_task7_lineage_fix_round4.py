"""RED regressions for Task 7 production-lineage fix round four."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

import migrate_presentation_state as migration
from migration_scope import MigrationError, validate_record_paths
from presentation_evidence_contracts import (
    EvidenceContractError,
    validate_store_record,
)
from presentation_evidence_snapshot import build_snapshot
from presentation_gates import ReviewGateError, assert_module_passable
from presentation_migration_v2 import build_migration_plan
from test_migrate_presentation_state_v2 import _exact_regular_tree
from test_presentation_evidence_contracts import (
    _real_assignment_record,
    _relations,
)
from test_presentation_evidence_gates import (
    _completable,
    _read_state,
    _write_state,
)
from test_presentation_workflow import _complete_fixture


_STATUSES = (
    "planned",
    "ready",
    "assigned",
    "producing",
    "review_required",
    "revision_required",
    "passed",
    "blocked",
    "superseded",
)
_DIGEST = "a" * 64
_SECOND_DIGEST = "b" * 64


def _module_id(project: Path) -> str:
    """Return the sole visual-module ID in a completed fixture."""
    return str(next(iter(_read_state(project, "visual_modules.yaml")["visual_modules"])))


def _reason_set(error: ReviewGateError) -> set[str]:
    """Return stable blocker reasons from one module gate failure."""
    return {str(blocker.get("reason")) for blocker in error.blockers}


def _mutate_first_record(
    project: Path,
    store_name: str,
    top_key: str,
    mutation: Callable[[dict[str, Any], str], None],
) -> None:
    """Mutate the first persisted record in one temporary state store.

    Args:
        project: Temporary project root.
        store_name: State-store filename.
        top_key: Record-map key in the YAML document.
        mutation: Mutation receiving the record and its map key.
    """
    document = _read_state(project, store_name)
    record_key = next(iter(document[top_key]))
    mutation(document[top_key][record_key], record_key)
    _write_state(project, store_name, document)


def _delete_module_lineage(project: Path, top_key: str) -> None:
    """Delete assignment or module-artifact records while retaining path strings."""
    store_name = f"{top_key}.yaml"
    document = _read_state(project, store_name)
    if top_key == "assignments":
        document[top_key] = {}
    else:
        document[top_key] = {
            key: record
            for key, record in document[top_key].items()
            if record.get("module_id") is None
        }
    _write_state(project, store_name, document)


def _completion_cli(project: Path, deck_id: str, completion_path: Path) -> dict[str, Any]:
    """Run the public completion CLI and return its structured result.

    Args:
        project: Temporary Git project used as the CLI working directory.
        deck_id: Deck submitted for completion.
        completion_path: Existing completion contract source.

    Returns:
        The exit code and parsed JSON standard output.
    """
    script = Path(__file__).resolve().parents[1] / "presentation_state.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--complete-deck",
            "--deck-id",
            deck_id,
            "--completion",
            str(completion_path),
            "--json",
        ],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.stderr == ""
    return {"returncode": result.returncode, "payload": json.loads(result.stdout)}


@pytest.mark.parametrize(
    ("top_key", "expected_reason"),
    [
        ("assignments", "module_assignment_record_missing"),
        ("artifacts", "module_artifact_record_missing"),
    ],
)
def test_public_completion_cli_resolves_persisted_module_lineage(
    tmp_path: Path, top_key: str, expected_reason: str
) -> None:
    """Deleting persisted lineage blocks completion despite retained paths.

    Args:
        tmp_path: Pytest-owned temporary directory.
        top_key: Persisted lineage record map to delete.
        expected_reason: Deterministic blocker required from the public CLI.
    """
    project, deck_id, completion_path = _completable(tmp_path)
    module = next(
        iter(_read_state(project, "visual_modules.yaml")["visual_modules"].values())
    )
    assert module["assignment_path"] and module["artifact_manifest_path"]
    _delete_module_lineage(project, top_key)

    result = _completion_cli(project, deck_id, completion_path)

    assert result["returncode"] == 1
    assert result["payload"]["predicate"] == "deck_completable"
    assert any(
        blocker["reason"].endswith(expected_reason)
        for blocker in result["payload"]["blockers"]
    )


@pytest.mark.parametrize(
    ("lineage", "expected_reason"),
    [
        ("assignment", "module_assignment_file_unreadable"),
        ("artifact", "module_artifact_file_unreadable"),
    ],
)
def test_public_completion_cli_rejects_missing_module_lineage_bytes(
    tmp_path: Path, lineage: str, expected_reason: str
) -> None:
    """Deleting assignment or artifact bytes blocks the public completion CLI.

    Args:
        tmp_path: Pytest-owned temporary directory.
        lineage: Module lineage file to delete.
        expected_reason: Deterministic blocker required from the public CLI.
    """
    project, deck_id, completion_path = _completable(tmp_path)
    module = next(
        iter(_read_state(project, "visual_modules.yaml")["visual_modules"].values())
    )
    path_field = (
        "assignment_path" if lineage == "assignment" else "artifact_manifest_path"
    )
    (project / module[path_field]).unlink()

    result = _completion_cli(project, deck_id, completion_path)

    assert result["returncode"] == 1
    assert any(
        blocker["reason"].endswith(expected_reason)
        for blocker in result["payload"]["blockers"]
    )


def _assignment_mutation(
    record: dict[str, Any], record_key: str, mutation: str
) -> None:
    """Apply one assignment-lineage attack to a persisted record.

    Args:
        record: Persisted assignment record to mutate.
        record_key: Authoritative record-map key.
        mutation: Named attack to apply.
    """
    if mutation == "cross_deck":
        record["deck_id"] = "deck-other"
    elif mutation == "cross_module":
        record["module_id"] = "mod-other"
    elif mutation == "path":
        record["assignment_path"] = "assignments/other.yaml"
        record["path"] = "assignments/other.yaml"
        record["relative_path"] = "assignments/other.yaml"
    elif mutation == "id":
        record["id"] = f"{record_key}-other"
    elif mutation == "dependencies":
        record["dependencies"] = ["mod-other"]
    elif mutation == "missing_digest":
        record.pop("spec_sha256")
    elif mutation == "bool_digest":
        record["spec_sha256"] = True
    else:
        raise AssertionError(f"unsupported assignment mutation: {mutation}")


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("cross_deck", "module_assignment_record_missing"),
        ("cross_module", "module_assignment_record_missing"),
        ("path", "module_assignment_record_missing"),
        ("id", "module_assignment_record_invalid"),
        ("dependencies", "module_assignment_record_invalid"),
        ("missing_digest", "module_assignment_record_invalid"),
        ("bool_digest", "module_assignment_record_invalid"),
    ],
)
def test_module_gate_rejects_substituted_assignment_lineage(
    tmp_path: Path, mutation: str, expected_reason: str
) -> None:
    """Assignment ownership, identity, dependencies, path, and digest stay bound.

    Args:
        tmp_path: Pytest-owned temporary directory.
        mutation: Persisted assignment attack to apply.
        expected_reason: Exact stable gate blocker.
    """
    project, _, _ = _completable(tmp_path)
    _mutate_first_record(
        project,
        "assignments.yaml",
        "assignments",
        lambda record, key: _assignment_mutation(record, key, mutation),
    )

    with pytest.raises(ReviewGateError) as error:
        assert_module_passable(project, _module_id(project))

    assert _reason_set(error.value) == {expected_reason}


def test_module_gate_rejects_ambiguous_assignment_lineage(tmp_path: Path) -> None:
    """Two same-owner assignment records cannot satisfy one module path."""
    project, _, _ = _completable(tmp_path)
    document = _read_state(project, "assignments.yaml")
    record = deepcopy(next(iter(document["assignments"].values())))
    record["id"] = "asn-duplicate"
    document["assignments"][record["id"]] = record
    _write_state(project, "assignments.yaml", document)

    with pytest.raises(ReviewGateError) as error:
        assert_module_passable(project, _module_id(project))

    assert _reason_set(error.value) == {"module_assignment_record_ambiguous"}


def test_module_gate_rejects_substituted_assignment_contract_bytes(
    tmp_path: Path,
) -> None:
    """Persisted assignment metadata cannot substitute for mismatched bytes."""
    project, _, _ = _completable(tmp_path)
    module = next(
        iter(_read_state(project, "visual_modules.yaml")["visual_modules"].values())
    )
    assignment_path = project / module["assignment_path"]
    assignment = yaml.safe_load(assignment_path.read_text(encoding="utf-8"))
    assignment["spec_sha256"] = _SECOND_DIGEST
    assignment_path.write_text(
        yaml.safe_dump(assignment, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ReviewGateError) as error:
        assert_module_passable(project, module["id"])

    assert _reason_set(error.value) == {"module_assignment_file_invalid"}


def _artifact_mutation(
    project: Path, record: dict[str, Any], record_key: str, mutation: str
) -> None:
    """Apply one artifact-lineage attack to a persisted record.

    Args:
        project: Temporary project root containing artifact bytes.
        record: Persisted artifact record to mutate.
        record_key: Authoritative record-map key.
        mutation: Named attack to apply.
    """
    if mutation == "cross_deck":
        record["deck_id"] = "deck-other"
    elif mutation == "cross_module":
        record["module_id"] = "mod-other"
    elif mutation == "path":
        record["path"] = "modules/other.svg"
        record["relative_path"] = "modules/other.svg"
    elif mutation == "id":
        record["id"] = f"{record_key}-other"
    elif mutation == "producer":
        record["producer_id"] = "worker-other"
        record["produced_by"] = "worker-other"
    elif mutation == "kind":
        record["artifact_kind"] = "slide-svg"
        record["kind"] = "slide-svg"
    elif mutation == "digest":
        record["sha256"] = _SECOND_DIGEST
    elif mutation == "missing_file":
        (project / str(record["path"])).unlink()
    else:
        raise AssertionError(f"unsupported artifact mutation: {mutation}")


def _mutate_module_artifact(project: Path, mutation: str) -> None:
    """Mutate the sole persisted module artifact, independent of ID ordering.

    Args:
        project: Temporary project root.
        mutation: Named artifact-lineage attack to apply.
    """
    document = _read_state(project, "artifacts.yaml")
    matches = [
        (record_id, record)
        for record_id, record in document["artifacts"].items()
        if record.get("module_id") is not None
    ]
    assert len(matches) == 1
    record_id, record = matches[0]
    _artifact_mutation(project, record, record_id, mutation)
    _write_state(project, "artifacts.yaml", document)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("cross_deck", "module_artifact_record_missing"),
        ("cross_module", "module_artifact_record_missing"),
        ("path", "module_artifact_record_missing"),
        ("id", "module_artifact_record_invalid"),
        ("producer", "module_artifact_record_invalid"),
        ("kind", "module_artifact_record_invalid"),
        ("digest", "module_artifact_digest_mismatch"),
        ("missing_file", "module_artifact_file_unreadable"),
    ],
)
def test_module_gate_rejects_substituted_artifact_lineage(
    tmp_path: Path, mutation: str, expected_reason: str
) -> None:
    """Artifact ownership, identity, path, kind, producer, and bytes stay bound.

    Args:
        tmp_path: Pytest-owned temporary directory.
        mutation: Persisted artifact attack to apply.
        expected_reason: Exact stable gate blocker.
    """
    project, _, _ = _completable(tmp_path)
    _mutate_module_artifact(project, mutation)

    with pytest.raises(ReviewGateError) as error:
        assert_module_passable(project, _module_id(project))

    assert _reason_set(error.value) == {expected_reason}


def test_module_gate_rejects_ambiguous_artifact_lineage(tmp_path: Path) -> None:
    """Two same-owner module artifacts cannot satisfy one manifest path."""
    project, _, _ = _completable(tmp_path)
    document = _read_state(project, "artifacts.yaml")
    module_record = next(
        record
        for record in document["artifacts"].values()
        if record.get("module_id") is not None
    )
    duplicate = deepcopy(module_record)
    duplicate["id"] = "art-duplicate"
    document["artifacts"][duplicate["id"]] = duplicate
    _write_state(project, "artifacts.yaml", document)

    with pytest.raises(ReviewGateError) as error:
        assert_module_passable(project, _module_id(project))

    assert _reason_set(error.value) == {"module_artifact_record_ambiguous"}


def test_module_gate_accepts_one_fully_resolved_lineage(tmp_path: Path) -> None:
    """One real assignment and one current verified artifact authorize review."""
    project, _, _ = _completable(tmp_path)

    result = assert_module_passable(project, _module_id(project))

    assert result["assignment"]["module_id"] == result["module"]["id"]
    assert result["artifact"]["module_id"] == result["module"]["id"]


def test_assignment_digest_is_required_without_a_module_spec() -> None:
    """A valid assignment digest remains mandatory when module spec is absent."""
    relations = _relations()
    module = relations["visual_modules"]["mod-source"]
    module["visual_spec_path"] = None
    module.pop("visual_spec_sha256")
    record = _real_assignment_record()

    assert validate_store_record("assignments", record, relations=relations) == record


@pytest.mark.parametrize("digest", [None, True, "a" * 63])
def test_assignment_rejects_missing_boolean_or_malformed_digest(digest: object) -> None:
    """Assignment digest syntax is never relaxed when module spec is absent.

    Args:
        digest: Invalid assignment digest candidate.
    """
    relations = _relations()
    module = relations["visual_modules"]["mod-source"]
    module["visual_spec_path"] = None
    module.pop("visual_spec_sha256")
    record = _real_assignment_record()
    if digest is None:
        record.pop("spec_sha256")
    else:
        record["spec_sha256"] = digest

    with pytest.raises(EvidenceContractError, match="spec_sha256|digest|fields"):
        validate_store_record("assignments", record, relations=relations)


def test_assignment_digest_matches_a_real_module_spec_when_present() -> None:
    """Equal non-null assignment and module spec digests remain valid."""
    record = _real_assignment_record()

    assert validate_store_record("assignments", record, relations=_relations()) == record


def test_assignment_digest_mismatch_with_a_real_module_spec_is_rejected() -> None:
    """Two present spec digests must remain equal."""
    record = _real_assignment_record()
    record["spec_sha256"] = _SECOND_DIGEST

    with pytest.raises(EvidenceContractError, match="does not match module relation"):
        validate_store_record("assignments", record, relations=_relations())


def test_assignment_digest_matches_legacy_module_digest_alias_when_present() -> None:
    """A present legacy module digest alias still binds the assignment digest."""
    relations = _relations()
    module = relations["visual_modules"]["mod-source"]
    module["visual_spec_sha256"] = None
    module["spec_sha256"] = _DIGEST
    record = _real_assignment_record()
    record["spec_sha256"] = _SECOND_DIGEST

    with pytest.raises(EvidenceContractError, match="does not match module relation"):
        validate_store_record("assignments", record, relations=relations)


def _tree_entries(root: Path) -> tuple[tuple[str, int, int, int], ...]:
    """Capture every project-tree entry's type, mode, and mtime."""
    return tuple(
        (
            path.relative_to(root).as_posix(),
            stat.S_IFMT(os.lstat(path).st_mode),
            stat.S_IMODE(os.lstat(path).st_mode),
            os.lstat(path).st_mtime_ns,
        )
        for path in sorted(root.rglob("*"))
    )


def test_real_module_completed_v2_project_is_an_exact_two_to_two_noop(
    tmp_path: Path,
) -> None:
    """Real module assignment, artifact, reviews, and completion survive 2->2."""
    project, deck_id, _, _, _, _ = _complete_fixture(tmp_path)
    modules = _read_state(project, "visual_modules.yaml")["visual_modules"]
    assignments = _read_state(project, "assignments.yaml")["assignments"]
    artifacts = _read_state(project, "artifacts.yaml")["artifacts"]
    assert len(modules) == 1
    assert len(assignments) == 1
    assert len(
        [record for record in artifacts.values() if record.get("module_id")]
    ) == 1
    assert next(iter(modules.values()))["visual_spec_path"] is None
    before_files = _exact_regular_tree(project)
    before_entries = _tree_entries(project)

    plan = build_migration_plan(build_snapshot(project))
    report = migration.migrate_state(project)

    assert plan.blocked_ids == ()
    assert dict(plan.blockers) == {}
    assert report == {
        "source_schema_version": 2,
        "target_schema_version": 2,
        "migrated_ids": [],
        "blocked_ids": [],
        "blockers": {},
        "changed_paths": [],
    }
    assert deck_id not in report["blockers"]
    assert _exact_regular_tree(project) == before_files
    assert _tree_entries(project) == before_entries


def _fresh_slide(status: str) -> dict[str, Any]:
    """Return one producer-shaped slide at a specified lifecycle status."""
    return {
        "id": "sld-1",
        "deck_id": "deck-1",
        "plan_slide_id": "slide-01",
        "title": "Evidence changes decisions",
        "status": status,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
        "created_by": "workflow",
        "approved_takeaway_sha256": None,
        "approved_evidence_sha256": None,
        "slide_spec_path": None,
        "slide_spec_sha256": None,
        "attempt": 1,
    }


def _fresh_module(status: str) -> dict[str, Any]:
    """Return one producer-shaped module at a specified lifecycle status."""
    produced = status != "planned"
    return {
        "id": "mod-1",
        "slide_id": "sld-1",
        "module_key": "module-a",
        "module_type": "architecture",
        "dependencies": [],
        "status": status,
        "visual_spec_path": None,
        "assignment_path": "assignments/module-a.yaml" if produced else None,
        "artifact_manifest_path": "modules/module-a.svg" if produced else None,
        "attempt": 1,
        "supersedes_module_id": None,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:00:00Z",
        "created_by": "workflow",
    }


def _materialize_module_paths(project: Path) -> None:
    """Create regular assignment and module-artifact files for path validation."""
    for relative, content in (
        ("assignments/module-a.yaml", b"schema_version: 1\n"),
        ("modules/module-a.svg", b"module-a"),
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


@pytest.mark.parametrize("status", _STATUSES)
def test_migration_scope_accepts_null_slide_spec_at_every_lifecycle(
    tmp_path: Path, status: str
) -> None:
    """Fresh slide records may retain a null spec path in every lifecycle.

    Args:
        tmp_path: Pytest-owned temporary directory.
        status: Valid fresh-record lifecycle status.
    """
    project = tmp_path / "project"
    project.mkdir()

    validate_record_paths(project, _fresh_slide(status), store_name="slides")


@pytest.mark.parametrize("status", _STATUSES)
def test_migration_scope_accepts_null_module_spec_at_every_lifecycle(
    tmp_path: Path, status: str
) -> None:
    """Fresh modules may retain null specs while written paths remain required.

    Args:
        tmp_path: Pytest-owned temporary directory.
        status: Valid fresh-record lifecycle status.
    """
    project = tmp_path / "project"
    project.mkdir()
    _materialize_module_paths(project)

    validate_record_paths(
        project, _fresh_module(status), store_name="visual_modules"
    )


def _write_legacy_store(
    project: Path,
    filename: str,
    top_key: str,
    records: dict[str, dict[str, Any]],
    version: int,
) -> None:
    """Write one schema-zero/one state store for end-to-end migration.

    Args:
        project: Temporary project root.
        filename: State-store filename.
        top_key: Record-map key in the YAML document.
        records: Producer-shaped records keyed by ID.
        version: Legacy schema marker.
    """
    path = project / ".research/presentations/state" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": version, top_key: records}, sort_keys=False),
        encoding="utf-8",
    )


@pytest.mark.parametrize("version", [0, 1])
def test_passed_slide_and_module_with_null_specs_migrate_to_v2(
    tmp_path: Path, version: int
) -> None:
    """Producer-shaped passed records with null specs migrate from v0 and v1.

    Args:
        tmp_path: Pytest-owned temporary directory.
        version: Supported legacy source schema.
    """
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    _materialize_module_paths(project)
    slide = _fresh_slide("passed")
    module = _fresh_module("passed")
    assignment = {
        "id": "asn-1",
        "deck_id": "deck-1",
        "slide_id": slide["id"],
        "module_id": module["id"],
        "assignment_path": module["assignment_path"],
        "path": module["assignment_path"],
        "relative_path": module["assignment_path"],
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
    artifact_bytes = (project / str(module["artifact_manifest_path"])).read_bytes()
    artifact = {
        "id": "art-1",
        "deck_id": "deck-1",
        "slide_id": slide["id"],
        "module_id": module["id"],
        "artifact_kind": "module-svg",
        "kind": "module-svg",
        "path": module["artifact_manifest_path"],
        "relative_path": module["artifact_manifest_path"],
        "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "producer_id": "worker-a",
        "produced_by": "worker-a",
        "created_at": "2026-08-09T00:00:00Z",
    }
    _write_legacy_store(
        project,
        "decks.yaml",
        "decks",
        {
            "deck-1": {
                "id": "deck-1",
                "title": "Evidence v2",
                "status": "planning",
                "created_by": "planner",
            }
        },
        version,
    )
    _write_legacy_store(project, "slides.yaml", "slides", {slide["id"]: slide}, version)
    _write_legacy_store(
        project, "visual_modules.yaml", "visual_modules", {module["id"]: module}, version
    )
    _write_legacy_store(
        project, "assignments.yaml", "assignments", {assignment["id"]: assignment}, version
    )
    _write_legacy_store(
        project, "artifacts.yaml", "artifacts", {artifact["id"]: artifact}, version
    )

    report = migration.migrate_state(project)

    assert report["source_schema_version"] == version
    assert report["target_schema_version"] == 2
    assert report["blocked_ids"] == []
    assert yaml.safe_load(
        (project / ".research/presentations/state/slides.yaml").read_text(encoding="utf-8")
    )["slides"][slide["id"]]["slide_spec_path"] is None
    assert yaml.safe_load(
        (project / ".research/presentations/state/visual_modules.yaml").read_text(
            encoding="utf-8"
        )
    )["visual_modules"][module["id"]]["visual_spec_path"] is None


@pytest.mark.parametrize("field", ["assignment_path", "artifact_manifest_path"])
def test_passed_module_still_rejects_null_written_provenance_paths(
    tmp_path: Path, field: str
) -> None:
    """Null assignment and artifact paths remain invalid after planning.

    Args:
        tmp_path: Pytest-owned temporary directory.
        field: Real-writer path cleared before scope validation.
    """
    project = tmp_path / "project"
    project.mkdir()
    _materialize_module_paths(project)
    module = _fresh_module("passed")
    module[field] = None

    with pytest.raises(MigrationError, match=field):
        validate_record_paths(project, module, store_name="visual_modules")


@pytest.mark.parametrize("store_name", ["slides", "visual_modules"])
@pytest.mark.parametrize("hazard", ["traversal", "absolute", "symlink", "directory", "wrong_type"])
def test_non_null_spec_paths_remain_fail_closed(
    tmp_path: Path, store_name: str, hazard: str
) -> None:
    """Unsafe or wrongly typed non-null spec paths remain rejected.

    Args:
        tmp_path: Pytest-owned temporary directory.
        store_name: Slide or visual-module authoritative store.
        hazard: Unsafe path case under test.
    """
    project = tmp_path / "project"
    project.mkdir()
    _materialize_module_paths(project)
    outside = tmp_path / "outside.yaml"
    outside.write_bytes(b"outside")
    if hazard == "traversal":
        value: object = "../outside.yaml"
    elif hazard == "absolute":
        value = str(outside)
    elif hazard == "symlink":
        link = project / "spec-link.yaml"
        link.symlink_to(outside)
        value = "spec-link.yaml"
    elif hazard == "directory":
        directory = project / "spec-dir"
        directory.mkdir()
        value = "spec-dir"
    else:
        value = True
    if store_name == "slides":
        record = _fresh_slide("passed")
        record["slide_spec_path"] = value
        record["slide_spec_sha256"] = _DIGEST
    else:
        record = _fresh_module("passed")
        record["visual_spec_path"] = value
        record["visual_spec_sha256"] = _DIGEST

    with pytest.raises(MigrationError, match="path|spec|regular|symlink"):
        validate_record_paths(project, record, store_name=store_name)
