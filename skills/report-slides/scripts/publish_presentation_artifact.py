#!/usr/bin/env python3
"""Validate and atomically publish one report-slides artifact.

The publisher is deliberately narrower than the rendering helpers.  It is a
workflow boundary: approval, contract identity, assignment/spec integrity,
and the resolved ``slides`` resource role are checked before any destination
directory or file is created.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from presentation_contracts import contract_sha256, load_contract
from presentation_events import (
    ARTIFACTS_RELATIVE_PATH,
    canonical_relative_path,
    create_artifact_record,
    load_assignments,
)
import presentation_events as _events
from presentation_gates import (
    PublicationGateError,
    assert_module_publishable,
    assert_production_allowed,
)
from presentation_state import load_slides, load_visual_modules
from validate_slide_spec import validate_slide_spec
from validate_visual_module import validate_complex_visual_spec, validate_worker_assignment


_MODULE_ARTIFACT_KINDS = frozenset({"module-svg", "module-png", "module-pptx"})
_SLIDE_ARTIFACT_KINDS = frozenset(
    {"slide-svg", "slide-png", "slide-pptx", "deck-pptx", "review-sheet"}
)
_PROTECTED_FIELDS = (
    ("approved_takeaway", "approved_takeaway_sha256", "takeaway"),
    ("approved_evidence_refs", "approved_evidence_sha256", "evidence"),
)


def publish_artifact(
    project_root: Path,
    deck_id: str,
    source: Path,
    destination: Path,
    artifact_kind: str,
    slide_id: str | None,
    module_id: str | None,
    producer_id: str,
    contract_path: Path,
) -> dict[str, Any]:
    """Validate and atomically publish one presentation artifact.

    Args:
        project_root: Project root containing durable presentation state.
        deck_id: Approved Deck identifier owning the artifact.
        source: Existing staged artifact to copy.
        destination: Final artifact path under the resolved ``slides`` role.
        artifact_kind: Typed artifact kind, such as ``module-svg``.
        slide_id: Optional generated slide identifier.
        module_id: Optional generated visual-module identifier.
        producer_id: Worker or producer identity.
        contract_path: Exact slide/specification or worker-assignment contract.

    Returns:
        The durable artifact record, including its SHA-256 digest.

    Raises:
        PublicationGateError: If approval, contract, assignment, path, or
            publication evidence is missing or inconsistent.
    """
    root = Path(project_root).resolve()
    _assert_production(root, deck_id)
    _validate_inputs(root, deck_id, source, destination, artifact_kind, producer_id)
    slides_root = _resolved_slides_root(root, deck_id)
    destination_path = Path(destination).resolve(strict=False)
    _require_contained(destination_path, slides_root, "destination")
    contract = _load_contract_or_fail(Path(contract_path), deck_id)
    context = _validate_contract_context(
        root,
        deck_id,
        contract,
        Path(contract_path),
        artifact_kind,
        slide_id,
        module_id,
    )
    assignment = context.get("assignment")
    if isinstance(assignment, Mapping):
        expected_producer = assignment.get("worker_id", assignment.get("worker"))
        if expected_producer != producer_id:
            _fail(
                deck_id,
                [{"reason": "producer_mismatch", "expected": expected_producer}],
            )
    source_path = Path(source).resolve()
    if not source_path.is_file():
        _fail(deck_id, [{"reason": "missing_source", "path": str(source)}])
    try:
        payload = source_path.read_bytes()
    except OSError as exc:
        _fail(deck_id, [{"reason": "source_unreadable", "message": str(exc)}])
    digest = hashlib.sha256(payload).hexdigest()
    relative_destination = canonical_relative_path(destination_path.relative_to(root))
    artifact = {
        "deck_id": deck_id,
        "slide_id": context.get("slide_id", slide_id),
        "module_id": context.get("module_id", module_id),
        "artifact_kind": artifact_kind,
        "kind": artifact_kind,
        "path": relative_destination,
        "relative_path": relative_destination,
        "sha256": digest,
        "producer_id": producer_id,
        "produced_by": producer_id,
    }
    if context.get("assignment") is not None:
        assignment = context["assignment"]
        artifact["assignment_id"] = assignment.get("id")
        artifact["spec_sha256"] = assignment.get("spec_sha256")

    state_snapshots = _snapshot_state(root, bool(module_id))
    destination_snapshot = _snapshot_path(destination_path)
    temporary_path: Path | None = None
    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.name}.",
            suffix=".tmp",
            dir=str(destination_path.parent),
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination_path)
        temporary_path = None
        _fsync_directory(destination_path.parent)

        if module_id is not None:
            _assert_module_after_copy(root, module_id, artifact, deck_id)
        record = create_artifact_record(
            root,
            deck_id,
            artifact_kind,
            relative_destination,
            digest,
            producer_id,
            slide_id=artifact["slide_id"],
            module_id=module_id,
        )
        record.update(
            {
                key: value
                for key, value in artifact.items()
                if key in {"assignment_id", "spec_sha256"}
            }
        )
        if "assignment_id" in record and record.get("assignment_id") is not None:
            _persist_artifact_binding(root, record["id"], record)
        return record
    except PublicationGateError:
        _rollback_publication(root, destination_path, destination_snapshot, state_snapshots)
        raise
    except Exception as exc:  # noqa: BLE001 - publication must fail closed
        _rollback_publication(root, destination_path, destination_snapshot, state_snapshots)
        _fail(deck_id, [{"reason": "publication_failed", "message": str(exc)}])
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _assert_production(project_root: Path, deck_id: str) -> None:
    """Run the shared production predicate before reading or writing output."""
    try:
        assert_production_allowed(project_root, deck_id)
    except PublicationGateError:
        raise
    except Exception as exc:  # noqa: BLE001 - preserve a typed gate boundary
        _fail(deck_id, [{"reason": "production_not_allowed", "message": str(exc)}])


def _validate_inputs(
    project_root: Path,
    deck_id: str,
    source: Path,
    destination: Path,
    artifact_kind: str,
    producer_id: str,
) -> None:
    """Reject malformed API arguments before any filesystem mutation."""
    if artifact_kind not in _MODULE_ARTIFACT_KINDS | _SLIDE_ARTIFACT_KINDS:
        _fail(deck_id, [{"reason": "unsupported_artifact_kind", "artifact_kind": artifact_kind}])
    if not isinstance(producer_id, str) or not producer_id.strip():
        _fail(deck_id, [{"reason": "producer_id_required"}])
    if not isinstance(source, Path) or not isinstance(destination, Path):
        _fail(deck_id, [{"reason": "source_and_destination_must_be_paths"}])
    try:
        destination.resolve(strict=False).relative_to(project_root)
    except ValueError:
        _fail(deck_id, [{"reason": "destination_outside_project_root"}])


def _resolved_slides_root(project_root: Path, deck_id: str) -> Path:
    """Resolve the confirmed ``slides`` role through resource-resolver."""
    resolver_path = Path(__file__).resolve().parents[2] / "resource-resolver/scripts/resolve.py"
    if not resolver_path.is_file():
        # This project layout is fixed, but report a typed blocker if it is
        # ever packaged without the resolver instead of guessing a directory.
        _fail(deck_id, [{"reason": "slides_role_resolver_missing"}])
    specification = importlib.util.spec_from_file_location("resource_resolver", resolver_path)
    if specification is None or specification.loader is None:
        _fail(deck_id, [{"reason": "slides_role_resolver_unloadable"}])
    resolver = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(resolver)
    try:
        registry = resolver.load_role_registry(resolver._default_registry_path())
        workspace = resolver.load_workspace(project_root)
        result = resolver.resolve_role("slides", registry, workspace, project_root)
    except Exception as exc:  # noqa: BLE001 - resolver errors are gate evidence
        _fail(deck_id, [{"reason": "slides_role_resolution_failed", "message": str(exc)}])
    if result.get("status") != "resolved":
        _fail(
            deck_id,
            [{"reason": f"slides_role_{result.get('status', 'unresolved')}", "details": result}],
        )
    primary = result.get("primary")
    if not isinstance(primary, str) or "://" in primary:
        _fail(deck_id, [{"reason": "slides_role_primary_invalid"}])
    candidate = (project_root / primary).resolve()
    _require_contained(candidate, project_root, "slides role")
    return candidate


def _load_contract_or_fail(contract_path: Path, deck_id: str) -> Any:
    """Load the caller-provided contract without masking parse failures."""
    if not contract_path.is_file():
        _fail(deck_id, [{"reason": "missing_contract", "path": str(contract_path)}])
    try:
        return load_contract(contract_path)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        _fail(deck_id, [{"reason": "invalid_contract", "message": str(exc)}])


def _validate_contract_context(
    project_root: Path,
    deck_id: str,
    contract: Any,
    contract_path: Path,
    artifact_kind: str,
    slide_id: str | None,
    module_id: str | None,
) -> dict[str, Any]:
    """Validate exact slide/module identity and return publication context."""
    if artifact_kind in _MODULE_ARTIFACT_KINDS:
        if module_id is not None:
            return _validate_module_context(
                project_root, deck_id, contract, contract_path, slide_id, module_id
            )
        if slide_id is None:
            _fail(deck_id, [{"reason": "module_id_required", "artifact_kind": artifact_kind}])
    if slide_id is None:
        _fail(deck_id, [{"reason": "slide_id_required", "artifact_kind": artifact_kind}])
    return _validate_slide_context(project_root, deck_id, contract, contract_path, slide_id)


def _validate_slide_context(
    project_root: Path,
    deck_id: str,
    contract: Any,
    contract_path: Path,
    slide_id: str,
) -> dict[str, Any]:
    """Validate one exact Slide Specification and its protected content."""
    slides = load_slides(project_root)
    slide = slides.get(slide_id)
    if not isinstance(slide, Mapping) or slide.get("deck_id") != deck_id:
        _fail(deck_id, [{"reason": "slide_id_mismatch", "slide_id": slide_id}])
    errors = validate_slide_spec(contract)
    if errors:
        _fail(deck_id, [{"reason": error} for error in errors])
    _validate_protected_fields(contract, deck_id)
    expected_plan_slide_id = slide.get("plan_slide_id")
    if contract.get("slide_id") != expected_plan_slide_id:
        _fail(
            deck_id,
            [{"reason": "slide_spec_identity_mismatch", "expected": expected_plan_slide_id}],
        )
    _validate_contract_path_identity(project_root, slide, contract_path, "slide_spec_path", deck_id)
    persisted_digest = slide.get("slide_spec_sha256")
    if persisted_digest and persisted_digest != contract_sha256(contract):
        _fail(deck_id, [{"reason": "slide_spec_digest_mismatch"}])
    for field in ("approved_takeaway_sha256", "approved_evidence_sha256"):
        if slide.get(field) and slide[field] != contract.get(field):
            _fail(deck_id, [{"reason": f"{field}_mismatch"}])
    return {"slide_id": slide_id, "module_id": None, "slide": slide}


def _validate_module_context(
    project_root: Path,
    deck_id: str,
    contract: Any,
    contract_path: Path,
    slide_id: str | None,
    module_id: str,
) -> dict[str, Any]:
    """Validate a module spec, current assignment, and exact protected fields."""
    modules = load_visual_modules(project_root)
    module = modules.get(module_id)
    if not isinstance(module, Mapping):
        _fail(deck_id, [{"reason": "unknown_module", "module_id": module_id}])
    slides = load_slides(project_root)
    linked_slide_id = module.get("slide_id")
    slide = slides.get(linked_slide_id)
    if not isinstance(slide, Mapping) or slide.get("deck_id") != deck_id:
        _fail(deck_id, [{"reason": "module_slide_mismatch"}])
    if slide_id is not None and slide_id != linked_slide_id:
        _fail(deck_id, [{"reason": "slide_id_mismatch", "expected": linked_slide_id}])
    assignment = _current_assignment(project_root, module, deck_id)
    spec_document, spec_path = _module_spec_document(project_root, module, contract, contract_path, deck_id)
    spec_errors = validate_complex_visual_spec(spec_document)
    if spec_errors:
        _fail(deck_id, [{"reason": error} for error in spec_errors])
    _validate_protected_fields(spec_document, deck_id)
    module_spec = _find_module_spec(spec_document, module.get("module_key"), deck_id)
    if module_spec.get("module_type") != module.get("module_type"):
        _fail(deck_id, [{"reason": "module_type_mismatch"}])
    spec_digest = contract_sha256(spec_document)
    persisted_digest = module.get("visual_spec_sha256", module.get("spec_sha256"))
    if persisted_digest != spec_digest:
        _fail(deck_id, [{"reason": "spec_digest_mismatch"}])
    if assignment.get("spec_sha256") != spec_digest:
        _fail(deck_id, [{"reason": "assignment_spec_digest_mismatch"}])
    assignment_path = assignment.get("assignment_path", assignment.get("path"))
    assignment_contract_path = (
        project_root / assignment_path if isinstance(assignment_path, str) else None
    )
    if assignment_contract_path is None or not assignment_contract_path.is_file():
        _fail(deck_id, [{"reason": "missing_assignment_contract"}])
    if assignment_contract_path.is_file():
        assignment_contract = _load_contract_or_fail(assignment_contract_path, deck_id)
        assignment_errors = validate_worker_assignment(assignment_contract)
        if assignment_errors:
            _fail(deck_id, [{"reason": error} for error in assignment_errors])
        _compare_assignment_contract(assignment, assignment_contract, deck_id, module_spec)
    allowed_contract_paths = {
        path.resolve()
        for path in (assignment_contract_path, spec_path)
        if path is not None
    }
    if allowed_contract_paths and contract_path.resolve() not in allowed_contract_paths:
        _fail(deck_id, [{"reason": "contract_path_not_current_assignment_or_spec"}])
    _compare_module_spec_to_record(module, module_spec, deck_id)
    if spec_path is not None:
        _validate_contract_path_identity(project_root, module, spec_path, "visual_spec_path", deck_id)
    return {
        "slide_id": linked_slide_id,
        "module_id": module_id,
        "module": module,
        "assignment": assignment,
    }


def _module_spec_document(
    project_root: Path,
    module: Mapping[str, Any],
    contract: Any,
    contract_path: Path,
    deck_id: str,
) -> tuple[Any, Path | None]:
    """Resolve the exact visual spec from the module or caller contract."""
    visual_spec_path = module.get("visual_spec_path")
    expected_path = project_root / visual_spec_path if isinstance(visual_spec_path, str) else None
    if isinstance(contract, Mapping) and isinstance(contract.get("modules"), list):
        if expected_path is not None and expected_path.resolve() != contract_path.resolve():
            _fail(deck_id, [{"reason": "contract_path_not_current_visual_spec"}])
        return contract, expected_path
    if expected_path is None or not expected_path.is_file():
        _fail(deck_id, [{"reason": "missing_visual_spec"}])
    return _load_contract_or_fail(expected_path, deck_id), expected_path


def _find_module_spec(document: Any, module_key: Any, deck_id: str) -> Mapping[str, Any]:
    """Return one declared module spec by its immutable module key."""
    modules = document.get("modules", []) if isinstance(document, Mapping) else []
    matches = [entry for entry in modules if isinstance(entry, Mapping) and entry.get("id") == module_key]
    if len(matches) != 1:
        _fail(deck_id, [{"reason": "module_key_missing_or_ambiguous"}])
    return matches[0]


def _current_assignment(
    project_root: Path, module: Mapping[str, Any], deck_id: str
) -> dict[str, Any]:
    """Load exactly the assignment named by the module's current path."""
    current_path = module.get("assignment_path")
    if not isinstance(current_path, str) or not current_path:
        _fail(deck_id, [{"reason": "missing_current_assignment"}])
    matches = [
        assignment
        for assignment in load_assignments(project_root).values()
        if assignment.get("module_id") == module.get("id")
        and assignment.get("assignment_path", assignment.get("path")) == current_path
    ]
    if len(matches) != 1:
        _fail(
            deck_id,
            [{"reason": "missing_assignment" if not matches else "ambiguous_assignment"}],
        )
    return dict(matches[0])


def _compare_assignment_contract(
    persisted: Mapping[str, Any],
    contract: Mapping[str, Any],
    deck_id: str,
    module_spec: Mapping[str, Any],
) -> None:
    """Require assignment identity and protected fields to match exactly."""
    for field in ("module_id", "worker_type", "dependencies", "spec_sha256", "inputs_resolved", "blocker"):
        if field in contract and contract.get(field) != persisted.get(field):
            _fail(deck_id, [{"reason": f"assignment_{field}_mismatch"}])
    for field in (
        "input_anchors",
        "output_anchors",
        "dimensions",
        "style_tokens_ref",
        "editability",
    ):
        if field in contract and contract.get(field) != module_spec.get(field):
            _fail(deck_id, [{"reason": f"assignment_{field}_mismatch"}])


def _compare_module_spec_to_record(
    module: Mapping[str, Any], spec: Mapping[str, Any], deck_id: str
) -> None:
    """Compare module type, anchors, dimensions, style, and editability."""
    checks = (
        ("module_type", "module_type"),
        ("input_anchors", "input_anchors"),
        ("output_anchors", "output_anchors"),
        ("dimensions", "dimensions"),
        ("style_tokens_ref", "style_tokens_ref"),
        ("editability", "editability"),
    )
    for spec_field, record_field in checks:
        if record_field in module and spec.get(spec_field) != module.get(record_field):
            _fail(deck_id, [{"reason": f"{spec_field}_mismatch"}])


def _persist_artifact_binding(
    project_root: Path, artifact_id: str, record: Mapping[str, Any]
) -> None:
    """Persist assignment/spec identity alongside the durable artifact row."""
    path = project_root / ARTIFACTS_RELATIVE_PATH
    with _events._locked_file(project_root, path):
        records = _events._load_yaml_map(path, "artifacts")
        if artifact_id not in records:
            raise PublicationGateError(
                "artifact_publishable",
                str(record.get("deck_id", "<unknown>")),
                [{"reason": "artifact_record_missing_after_create"}],
            )
        records[artifact_id].update(
            {
                key: record[key]
                for key in ("assignment_id", "spec_sha256")
                if key in record
            }
        )
        _events._save_yaml_map(path, "artifacts", records)


def _validate_protected_fields(contract: Any, deck_id: str) -> None:
    """Require every declared protected value to match its canonical digest."""
    if not isinstance(contract, Mapping):
        return
    for value_field, digest_field, label in _PROTECTED_FIELDS:
        if digest_field not in contract:
            continue
        digest = contract.get(digest_field)
        try:
            expected = contract_sha256(contract.get(value_field))
        except (TypeError, ValueError) as exc:
            _fail(deck_id, [{"reason": f"{label}_protected_value_invalid", "message": str(exc)}])
        if not isinstance(digest, str) or digest != expected:
            _fail(deck_id, [{"reason": f"{label}_digest_mismatch", "field": digest_field}])


def _validate_contract_path_identity(
    project_root: Path,
    record: Mapping[str, Any],
    contract_path: Path,
    field: str,
    deck_id: str,
) -> None:
    """Require a supplied contract path to match a persisted current path."""
    raw_path = record.get(field)
    if not isinstance(raw_path, str) or not raw_path:
        return
    expected = (project_root / raw_path).resolve()
    if expected != contract_path.resolve():
        _fail(deck_id, [{"reason": f"{field}_identity_mismatch"}])


def _assert_module_after_copy(
    project_root: Path, module_id: str, artifact: Mapping[str, Any], deck_id: str
) -> None:
    """Re-run the shared publication predicate after the destination exists."""
    try:
        assert_module_publishable(project_root, module_id, dict(artifact))
    except PublicationGateError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize every gate failure
        _fail(deck_id, [{"reason": "module_publication_not_allowed", "message": str(exc)}])


def _require_contained(candidate: Path, root: Path, label: str) -> None:
    """Require one resolved path to remain below a resolved root."""
    try:
        candidate.relative_to(root)
    except ValueError:
        raise PublicationGateError(
            "artifact_publishable",
            "<unknown>",
            [{"reason": f"{label}_outside_root"}],
            f"{label} is outside its permitted root",
        )


def _fail(deck_id: str, blockers: list[dict[str, Any]]) -> None:
    """Raise one structured publication gate failure."""
    summary = "; ".join(str(blocker.get("reason", blocker)) for blocker in blockers)
    raise PublicationGateError(
        "artifact_publishable",
        deck_id,
        blockers,
        f"artifact_publishable blocked for deck {deck_id}: {summary or 'missing evidence'}",
    )


def _snapshot_path(path: Path) -> bytes | None:
    """Capture an existing file for rollback without creating it."""
    if not path.exists():
        return None
    return path.read_bytes()


def _snapshot_state(project_root: Path, include_modules: bool) -> dict[Path, bytes | None]:
    """Capture mutable state files touched by artifact registration."""
    files: dict[Path, bytes | None] = {
        project_root / ARTIFACTS_RELATIVE_PATH: _snapshot_path(
            project_root / ARTIFACTS_RELATIVE_PATH
        )
    }
    if include_modules:
        modules_path = project_root / ".research/presentations/state/visual_modules.yaml"
        files[modules_path] = _snapshot_path(modules_path)
    return files


def _rollback_publication(
    project_root: Path,
    destination: Path,
    destination_snapshot: bytes | None,
    state_snapshots: Mapping[Path, bytes | None],
) -> None:
    """Restore destination and durable state after any publication failure."""
    try:
        if destination_snapshot is None:
            destination.unlink(missing_ok=True)
        else:
            destination.write_bytes(destination_snapshot)
    except OSError:
        pass
    for path, snapshot in state_snapshots.items():
        try:
            if snapshot is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(snapshot)
        except OSError:
            pass


def _fsync_directory(directory: Path) -> None:
    """Synchronize a directory entry after atomic replacement on POSIX."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
