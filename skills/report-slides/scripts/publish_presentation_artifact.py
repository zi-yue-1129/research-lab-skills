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
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, MutableMapping

import yaml

from presentation_contracts import contract_sha256, load_contract
from presentation_evidence_contracts import EVIDENCE_SCHEMA_VERSION
from presentation_artifact_provenance import (
    derive_validated_published_provenance,
    MODULE_ARTIFACT_KINDS,
    REVIEW_SHEET_KIND,
    SLIDE_PNG_KIND,
    SLIDE_ARTIFACT_KINDS,
    SUPPORTED_ARTIFACT_KINDS,
    validate_artifact_subject,
    validate_review_sheet_contract,
)
from presentation_events import (
    ARTIFACTS_RELATIVE_PATH,
    canonical_relative_path,
    load_plans,
    load_assignments,
)
import presentation_events as _events
from presentation_gates import (
    PublicationGateError,
    assert_module_publishable,
    assert_production_allowed,
)
from presentation_workflow import _workflow_lock
from presentation_state import load_decks, load_slides, load_visual_modules
from validate_slide_spec import validate_slide_spec
from validate_visual_module import validate_complex_visual_spec, validate_worker_assignment

_MODULE_ARTIFACT_KINDS = MODULE_ARTIFACT_KINDS
_SLIDE_ARTIFACT_KINDS = SLIDE_ARTIFACT_KINDS
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
    try:
        validate_artifact_subject(
            artifact_kind, slide_id, module_id, reject_unknown=True
        )
    except ValueError as exc:
        _fail(deck_id, [{"reason": str(exc)}])
    _validate_inputs(root, deck_id, source, destination, artifact_kind, producer_id)
    with _workflow_lock(root):
        _assert_production(root, deck_id)
        return _publish_locked(
            root,
            deck_id,
            Path(source),
            Path(destination),
            artifact_kind,
            slide_id,
            module_id,
            producer_id,
            Path(contract_path),
        )

def _publish_locked(
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
    """Publish one artifact while holding the workflow lock."""
    slides_root = _resolved_slides_root(project_root, deck_id)
    destination_path = destination.resolve(strict=False)
    _require_contained(destination_path, slides_root, "destination", deck_id)
    state_paths = _state_paths(project_root, module_id is not None)
    with _state_locks(project_root, state_paths):
        contract = _load_contract_or_fail(contract_path, deck_id)
        context = _validate_contract_context(
            project_root, deck_id, contract, contract_path, artifact_kind,
            slide_id, module_id, producer_id,
        )
        source_path = source.resolve()
        if not source_path.is_file():
            _fail(deck_id, [{"reason": "missing_source", "path": str(source)}])
        try:
            payload = source_path.read_bytes()
        except OSError as exc:
            _fail(deck_id, [{"reason": "source_unreadable", "message": str(exc)}])
        source_digest = hashlib.sha256(payload).hexdigest()
        relative_destination = canonical_relative_path(destination_path.relative_to(project_root))
        artifact: dict[str, Any] = {
            "deck_id": deck_id,
            "slide_id": context.get("slide_id", slide_id),
            "module_id": context.get("module_id", module_id),
            "artifact_kind": artifact_kind,
            "kind": artifact_kind,
            "path": relative_destination,
            "relative_path": relative_destination,
            "sha256": source_digest,
            "producer_id": producer_id,
            "produced_by": producer_id,
        }
        try:
            artifact.update(derive_validated_published_provenance(
                project_root, deck_id, artifact_kind, context.get("slide_id", slide_id)
            ))
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            _fail(deck_id, [{"reason": "artifact_provenance_invalid", "message": str(exc)}])
        assignment = context.get("assignment")
        if isinstance(assignment, Mapping):
            artifact.update({
                "assignment_id": assignment.get("id"),
                "spec_sha256": assignment.get("spec_sha256"),
            })
        artifact.update(context.get("bindings", {}))
        state_snapshots = _snapshot_state(project_root, module_id is not None)
        destination_snapshot = _snapshot_path(destination_path)
        staged_state: dict[Path, Path] = {}
        temporary_path: Path | None = None
        try:
            staged_state = _stage_state_files(
                project_root, artifact, state_snapshots, module_id
            )
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination_path.name}.", suffix=".tmp", dir=str(destination_path.parent)
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                written = _write_payload(handle, payload)
                handle.flush()
                os.fsync(handle.fileno())
            if written != len(payload):
                _fail(deck_id, [{"reason": "short_write", "expected": len(payload), "actual": written}])
            _verify_file(temporary_path, len(payload), source_digest, "temporary", deck_id)
            os.replace(temporary_path, destination_path)
            temporary_path = None
            _fsync_directory(destination_path.parent)
            destination_size, destination_digest = _destination_digest(destination_path)
            if destination_size != len(payload) or destination_digest != source_digest:
                _fail(deck_id, [{
                    "reason": "destination_digest_mismatch", "expected": source_digest,
                    "actual": destination_digest, "expected_size": len(payload),
                    "actual_size": destination_size,
                }])
            artifact["sha256"] = destination_digest
            if module_id is not None:
                _assert_module_after_copy(project_root, module_id, artifact, deck_id)
            _commit_state_files(staged_state)
            return artifact
        except Exception as exc:  # noqa: BLE001 - publication must fail closed
            cleanup_failures = _cleanup_paths(
                [temporary_path, *staged_state.values()], deck_id
            )
            rollback_failures = _rollback_publication(
                project_root, destination_path, destination_snapshot, state_snapshots, deck_id
            )
            _raise_publication_failure(
                deck_id, exc, cleanup_failures, rollback_failures
            )

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
    if artifact_kind not in SUPPORTED_ARTIFACT_KINDS:
        _fail(deck_id, [{"reason": "unsupported_artifact_kind", "artifact_kind": artifact_kind}])
    if artifact_kind in {SLIDE_PNG_KIND, REVIEW_SHEET_KIND} and destination.suffix.lower() != ".png":
        _fail(deck_id, [{"reason": "typed PNG artifact requires a .png destination"}])
    if not isinstance(producer_id, str) or not producer_id.strip():
        _fail(deck_id, [{"reason": "producer_id_required"}])
    if not isinstance(source, Path) or not isinstance(destination, Path):
        _fail(deck_id, [{"reason": "source_and_destination_must_be_paths"}])
    try:
        destination.resolve(strict=False).relative_to(project_root)
    except ValueError:
        _fail(deck_id, [{"reason": "destination_outside_project_root"}])

def _validate_subject_kind(
    artifact_kind: str, slide_id: str | None, module_id: str | None, deck_id: str
) -> None:
    """Require each artifact kind to carry exactly its supported subject."""
    try:
        validate_artifact_subject(artifact_kind, slide_id, module_id)
    except ValueError as exc:
        _fail(deck_id, [{"reason": str(exc)}])

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
    _require_contained(candidate, project_root, "slides role", deck_id)
    return candidate

def _resolve_state_path(
    project_root: Path, raw_path: str, field: str, deck_id: str
) -> Path:
    """Resolve a persisted state path without permitting root escape."""
    try:
        relative_path = canonical_relative_path(raw_path)
    except (TypeError, ValueError) as exc:
        _fail(deck_id, [{"reason": f"{field}_invalid", "message": str(exc)}])
    candidate = (project_root / relative_path).resolve()
    _require_contained(candidate, project_root, field, deck_id)
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
    producer_id: str,
) -> dict[str, Any]:
    """Validate exact slide/module identity and return publication context."""
    if artifact_kind in _MODULE_ARTIFACT_KINDS:
        if module_id is None:
            _fail(deck_id, [{"reason": "module_subject_required", "artifact_kind": artifact_kind}])
        return _validate_module_context(
            project_root, deck_id, contract, contract_path, slide_id, module_id
        )
    if artifact_kind == REVIEW_SHEET_KIND:
        try:
            bindings = validate_review_sheet_contract(project_root, deck_id, contract, contract_path)
        except (OSError, TypeError, ValueError) as exc:
            _fail(deck_id, [{"reason": "review_sheet_plan_invalid", "message": str(exc)}])
        return {"slide_id": None, "module_id": None, "bindings": bindings}
    if slide_id is None:
        _fail(deck_id, [{"reason": "slide_subject_required", "artifact_kind": artifact_kind}])
    return _validate_slide_context(
        project_root, deck_id, contract, contract_path, slide_id, producer_id
    )

def _validate_slide_context(
    project_root: Path,
    deck_id: str,
    contract: Any,
    contract_path: Path,
    slide_id: str,
    producer_id: str,
) -> dict[str, Any]:
    """Validate one exact Slide Specification and its protected content."""
    slides = load_slides(project_root)
    slide = slides.get(slide_id)
    if not isinstance(slide, Mapping) or slide.get("deck_id") != deck_id:
        _fail(deck_id, [{"reason": "slide_id_mismatch", "slide_id": slide_id}])
    raw_spec_path = slide.get("slide_spec_path")
    persisted_digest = slide.get("slide_spec_sha256")
    if not isinstance(raw_spec_path, str) or not raw_spec_path:
        _fail(deck_id, [{"reason": "slide_spec_path_missing"}])
    if not isinstance(persisted_digest, str) or len(persisted_digest) != 64:
        _fail(deck_id, [{"reason": "slide_spec_sha256_missing"}])
    expected_spec_path = _resolve_state_path(project_root, raw_spec_path, "slide_spec_path", deck_id)
    if expected_spec_path != contract_path.resolve():
        _fail(deck_id, [{"reason": "slide_spec_path_identity_mismatch"}])
    if not expected_spec_path.is_file():
        _fail(deck_id, [{"reason": "slide_spec_file_missing"}])
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
    if persisted_digest != contract_sha256(contract):
        _fail(deck_id, [{"reason": "slide_spec_digest_mismatch"}])
    for field in ("approved_takeaway_sha256", "approved_evidence_sha256"):
        state_digest = slide.get(field)
        if not isinstance(state_digest, str) or state_digest != contract.get(field):
            _fail(deck_id, [{"reason": f"{field}_mismatch"}])
    _validate_slide_plan_binding(project_root, deck_id, slide, contract)
    assignment_binding = _validate_slide_producer(project_root, deck_id, slide, producer_id)
    spec_path = canonical_relative_path(raw_spec_path)
    spec_digest = contract_sha256(contract)
    return {
        "slide_id": slide_id,
        "module_id": None,
        "slide": slide,
        "bindings": {
            "assignment_path": assignment_binding["path"],
            "assignment_sha256": assignment_binding["sha256"],
            "assignment_contract_sha256": assignment_binding["sha256"],
            "slide_spec_path": spec_path,
            "slide_spec_sha256": persisted_digest,
            "slide_spec_contract_sha256": spec_digest,
            "contract_sha256": spec_digest,
        },
    }

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
    persisted_path = module.get("visual_spec_path")
    persisted_digest = module.get("visual_spec_sha256", module.get("spec_sha256"))
    if not isinstance(persisted_path, str) or not persisted_path:
        _fail(deck_id, [{"reason": "visual_spec_path_missing"}])
    if not isinstance(persisted_digest, str) or len(persisted_digest) != 64:
        _fail(deck_id, [{"reason": "visual_spec_sha256_missing"}])
    if persisted_digest != spec_digest:
        _fail(deck_id, [{"reason": "spec_digest_mismatch"}])
    if assignment.get("spec_sha256") != spec_digest:
        _fail(deck_id, [{"reason": "assignment_spec_digest_mismatch"}])
    assignment_path = assignment.get("assignment_path", assignment.get("path"))
    assignment_contract_path = (
        _resolve_state_path(project_root, assignment_path, "assignment_path", deck_id)
        if isinstance(assignment_path, str)
        else None
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
        "bindings": {
            "assignment_path": canonical_relative_path(assignment["assignment_path"]),
            "assignment_sha256": contract_sha256(assignment_contract),
            "assignment_contract_sha256": contract_sha256(assignment_contract),
            "visual_spec_path": canonical_relative_path(persisted_path),
            "visual_spec_sha256": persisted_digest,
            "visual_spec_contract_sha256": spec_digest,
        },
    }

def _validate_slide_plan_binding(
    project_root: Path,
    deck_id: str,
    slide: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    """Require protected slide values to match the currently approved plan."""
    deck = load_decks(project_root).get(deck_id)
    plan_id = deck.get("current_plan_id") if isinstance(deck, Mapping) else None
    plans = load_plans(project_root)
    plan_record = plans.get(plan_id) if isinstance(plan_id, str) else None
    if not isinstance(plan_record, Mapping):
        _fail(deck_id, [{"reason": "current_plan_missing"}])
    if plan_record.get("deck_id") != deck_id:
        _fail(deck_id, [{"reason": "current_plan_deck_mismatch"}])
    plan_path = plan_record.get("plan_path", plan_record.get("path"))
    if not isinstance(plan_path, str):
        _fail(deck_id, [{"reason": "current_plan_path_missing"}])
    plan_document_path = _resolve_state_path(project_root, plan_path, "current_plan_path", deck_id)
    try:
        plan = load_contract(plan_document_path)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        _fail(deck_id, [{"reason": "current_plan_invalid", "message": str(exc)}])
    persisted_digest = plan_record.get("sha256", plan_record.get("plan_sha256"))
    if persisted_digest != contract_sha256(plan):
        _fail(deck_id, [{"reason": "current_plan_digest_mismatch"}])
    plan_slide_id = slide.get("plan_slide_id")
    entries = [
        entry
        for entry in plan.get("slides", [])
        if isinstance(entry, Mapping) and entry.get("slide_id") == plan_slide_id
    ] if isinstance(plan, Mapping) else []
    if len(entries) != 1:
        _fail(deck_id, [{"reason": "slide_plan_binding_missing"}])
    plan_slide = entries[0]
    for field in ("approved_takeaway", "approved_evidence_refs"):
        if contract.get(field) != plan_slide.get("key_takeaway" if field == "approved_takeaway" else "evidence_refs"):
            _fail(deck_id, [{"reason": f"{field}_plan_mismatch"}])

def _validate_slide_producer(
    project_root: Path,
    deck_id: str,
    slide: Mapping[str, Any],
    producer_id: str,
) -> dict[str, str]:
    """Require producer identity from persisted slide ownership or assignment."""
    identities: list[tuple[str, str]] = []
    for field in ("producer_id", "owner_id", "assigned_to", "worker_id", "producer"):
        value = slide.get(field)
        if isinstance(value, str) and value.strip():
            identities.append((field, value.strip()))
    assignment_path = slide.get("assignment_path")
    if not isinstance(assignment_path, str) or not assignment_path:
        _fail(deck_id, [{"reason": "slide_assignment_path_missing"}])
    assignment_file = _resolve_state_path(
        project_root, assignment_path, "slide_assignment_path", deck_id
    )
    try:
        assignment = load_contract(assignment_file)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        _fail(deck_id, [{"reason": "slide_assignment_invalid", "message": str(exc)}])
    if not isinstance(assignment, Mapping):
        _fail(deck_id, [{"reason": "slide_assignment_invalid"}])
    for field in ("producer_id", "owner_id", "assigned_to", "worker_id", "worker"):
        value = assignment.get(field)
        if isinstance(value, str) and value.strip():
            identities.append((f"assignment.{field}", value.strip()))
    if not identities:
        _fail(deck_id, [{"reason": "slide_producer_binding_missing"}])
    persisted_identities = {identity for _, identity in identities}
    if len(persisted_identities) != 1:
        _fail(
            deck_id,
            [{
                "reason": "slide_producer_binding_conflict",
                "identities": sorted(persisted_identities),
            }],
        )
    owner = next(iter(persisted_identities))
    if owner != producer_id:
        _fail(deck_id, [{"reason": "producer_mismatch", "expected": owner}])
    return {
        "path": canonical_relative_path(assignment_path),
        "sha256": contract_sha256(assignment),
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
    if not isinstance(visual_spec_path, str) or not visual_spec_path:
        _fail(deck_id, [{"reason": "visual_spec_path_missing"}])
    expected_path = _resolve_state_path(project_root, visual_spec_path, "visual_spec_path", deck_id)
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
    persisted_worker = next(
        (
            persisted.get(field)
            for field in ("worker_id", "worker", "producer_id")
            if isinstance(persisted.get(field), str) and persisted.get(field).strip()
        ),
        None,
    )
    contract_workers = {
        contract.get(field).strip()
        for field in ("worker_id", "worker", "producer_id")
        if isinstance(contract.get(field), str) and contract.get(field).strip()
    }
    if contract_workers and (len(contract_workers) != 1 or persisted_worker not in contract_workers):
        _fail(deck_id, [{"reason": "assignment_worker_mismatch"}])
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

def _state_paths(project_root: Path, include_modules: bool) -> tuple[Path, ...]:
    """Return affected state files in deterministic lock order."""
    artifacts_path = project_root / ARTIFACTS_RELATIVE_PATH
    if include_modules:
        return (project_root / ".research/presentations/state/visual_modules.yaml", artifacts_path)
    return (artifacts_path,)

@contextmanager
def _state_locks(project_root: Path, paths: tuple[Path, ...]) -> Iterator[None]:
    """Hold every affected state sidecar lock in deterministic order."""
    with ExitStack() as stack:
        for path in paths:
            stack.enter_context(_events._locked_file(project_root, path))
        yield

def _stage_state_files(
    project_root: Path,
    artifact: MutableMapping[str, Any],
    snapshots: Mapping[Path, tuple[bytes | None, int | None]],
    module_id: str | None,
) -> dict[Path, Path]:
    """Build and fsync complete state files before destination replacement."""
    artifacts_path = project_root / ARTIFACTS_RELATIVE_PATH
    records = _events._load_yaml_map(artifacts_path, "artifacts")
    slide_ref, module_ref = _events._references(project_root, str(artifact["deck_id"]), artifact.get("slide_id"), module_id)
    record = dict(artifact)
    record.update({"id": _events._generate_id("art"), "slide_id": slide_ref, "module_id": module_ref, "created_at": _events._utc_now_iso()})
    records[record["id"]] = record
    staged: dict[Path, Path] = {}
    try:
        if module_id is not None:
            modules_path = project_root / ".research/presentations/state/visual_modules.yaml"
            modules = _events._load_yaml_map(modules_path, "visual_modules")
            if module_id not in modules:
                _fail(str(artifact["deck_id"]), [{"reason": "unknown_module"}])
            modules[module_id]["artifact_manifest_path"] = record["relative_path"]
            modules[module_id]["updated_at"] = _events._utc_now_iso()
            staged[modules_path] = _stage_yaml_map(modules_path, "visual_modules", modules, snapshots[modules_path][1], str(artifact["deck_id"]))
        staged[artifacts_path] = _stage_yaml_map(artifacts_path, "artifacts", records, snapshots[artifacts_path][1], str(artifact["deck_id"]))
    except Exception as exc:  # noqa: BLE001 - staged siblings must never leak
        cleanup_failures = _cleanup_paths(list(staged.values()), str(artifact["deck_id"]))
        if cleanup_failures:
            raise PublicationGateError(
                "artifact_publishable", str(artifact["deck_id"]),
                [{"reason": "publication_failed", "message": str(exc)}, *cleanup_failures],
                "artifact_publishable state staging recovery failed",
            ) from exc
        raise
    artifact["id"] = record["id"]
    artifact["created_at"] = record["created_at"]
    return staged

def _stage_yaml_map(
    path: Path,
    top_key: str,
    records: Mapping[str, Any],
    mode: int | None,
    deck_id: str,
) -> Path:
    """Write, fsync, and verify one complete state snapshot sibling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(
        {"version": EVIDENCE_SCHEMA_VERSION, top_key: dict(records)},
        sort_keys=True,
        allow_unicode=True,
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.stage.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            written = _write_payload(handle, payload)
            if mode is not None:
                os.chmod(temporary, mode)
            handle.flush()
            os.fsync(handle.fileno())
        if written != len(payload):
            raise OSError(f"short state write for {path}: {written}/{len(payload)}")
        _verify_file(temporary, len(payload), hashlib.sha256(payload).hexdigest(), "state", "<unknown>")
        return temporary
    except Exception as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as cleanup_error:
            raise PublicationGateError(
                "artifact_publishable", deck_id,
                [
                    {"reason": "publication_failed", "message": str(exc)},
                    {"reason": "temp_cleanup_failed", "path": str(temporary), "message": str(cleanup_error)},
                ],
                "artifact_publishable state staging cleanup failed",
            ) from exc
        raise

def _commit_state_files(staged: Mapping[Path, Path]) -> None:
    """Atomically replace each pre-staged state file and sync its directory."""
    for path, temporary in staged.items():
        os.replace(temporary, path)
        _fsync_directory(path.parent)

def _write_payload(handle: Any, payload: bytes) -> int:
    """Write all bytes through the descriptor, returning accepted length."""
    offset = 0
    while offset < len(payload):
        written = os.write(handle.fileno(), payload[offset:])
        if not isinstance(written, int) or written <= 0:
            return offset
        offset += written
    return offset

def _destination_digest(path: Path) -> tuple[int, str]:
    """Return stable byte length and SHA-256 digest for one file."""
    before = path.stat().st_size
    payload = path.read_bytes()
    after = path.stat().st_size
    if before != after or before != len(payload):
        raise OSError(f"file size changed while reading {path}")
    return len(payload), hashlib.sha256(payload).hexdigest()

def _verify_file(
    path: Path, expected_size: int, expected_digest: str, label: str, deck_id: str
) -> None:
    """Verify one staged file before it becomes visible."""
    actual_size, actual_digest = _destination_digest(path)
    if actual_size != expected_size or actual_digest != expected_digest:
        _fail(
            deck_id,
            [{
                "reason": f"{label}_digest_mismatch",
                "expected": expected_digest,
                "actual": actual_digest,
                "expected_size": expected_size,
                "actual_size": actual_size,
            }],
        )

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
    expected = _resolve_state_path(project_root, raw_path, field, deck_id)
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

def _require_contained(candidate: Path, root: Path, label: str, deck_id: str) -> None:
    """Require one resolved path to remain below a resolved root."""
    try:
        candidate.relative_to(root)
    except ValueError:
        _fail(deck_id, [{"reason": f"{label}_outside_root"}])

def _fail(deck_id: str, blockers: list[dict[str, Any]]) -> None:
    """Raise one structured publication gate failure."""
    summary = "; ".join(str(blocker.get("reason", blocker)) for blocker in blockers)
    raise PublicationGateError(
        "artifact_publishable",
        deck_id,
        blockers,
        f"artifact_publishable blocked for deck {deck_id}: {summary or 'missing evidence'}",
    )

def _snapshot_path(path: Path) -> tuple[bytes | None, int | None]:
    """Capture one path's existence, bytes, and permission mode."""
    if not os.path.lexists(path):
        return None, None
    stat = path.stat()
    return path.read_bytes(), stat.st_mode & 0o777

def _snapshot_state(project_root: Path, include_modules: bool) -> dict[Path, tuple[bytes | None, int | None]]:
    """Capture every mutable state file touched by artifact registration."""
    return {path: _snapshot_path(path) for path in _state_paths(project_root, include_modules)}

def _rollback_publication(project_root: Path, destination: Path, destination_snapshot: tuple[bytes | None, int | None], state_snapshots: Mapping[Path, tuple[bytes | None, int | None]], deck_id: str) -> list[dict[str, Any]]:
    """Restore all state first, then destination, and return every failure."""
    failures: list[dict[str, Any]] = []
    for path, snapshot in state_snapshots.items():
        try:
            _restore_path_atomic(path, snapshot)
        except PublicationGateError as exc:
            failures.extend(_contextualize_recovery_blockers(exc, path, "state"))
        except Exception as exc:  # noqa: BLE001 - recovery must remain explicit
            failures.append(_rollback_failure(exc, path, "state"))
    try:
        _restore_path_atomic(destination, destination_snapshot)
    except PublicationGateError as exc:
        failures.extend(_contextualize_recovery_blockers(exc, destination, "destination"))
    except Exception as exc:  # noqa: BLE001 - recovery must remain explicit
        failures.append(_rollback_failure(exc, destination, "destination"))
    return failures

def _contextualize_recovery_blockers(error: PublicationGateError, path: Path, scope: str) -> list[dict[str, Any]]:
    """Attach recovery phase, path, predicate, and deck context to blockers."""
    return [{**blocker, "scope": blocker.get("scope", scope), "phase": blocker.get("phase", "rollback"),
             "path": blocker.get("path", str(path)), "predicate": blocker.get("predicate", error.predicate),
             "deck_id": blocker.get("deck_id", error.deck_id)} for blocker in error.blockers]
def _rollback_failure(error: Exception, path: Path, scope: str) -> dict[str, Any]:
    """Return one structured blocker for a non-gate rollback exception."""
    return {"reason": "rollback_failed", "scope": scope, "phase": "rollback", "path": str(path), "message": str(error)}
def _restore_path_atomic(path: Path, snapshot: tuple[bytes | None, int | None]) -> None:
    """Restore one path atomically, preserving bytes, existence, and mode."""
    payload, mode = snapshot
    if payload is None:
        if os.path.lexists(path):
            path.unlink()
            _fsync_directory(path.parent)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.rollback.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    failure: Exception | None = None
    try:
        with os.fdopen(descriptor, "wb") as handle:
            written = _write_payload(handle, payload)
            if mode is not None:
                os.chmod(temporary, mode)
            handle.flush()
            os.fsync(handle.fileno())
        if written != len(payload):
            raise OSError(f"short rollback write for {path}: {written}/{len(payload)}")
        _verify_file(temporary, len(payload), hashlib.sha256(payload).hexdigest(), "rollback", "<unknown>")
        os.replace(temporary, path)
        temporary = None
        _fsync_directory(path.parent)
    except Exception as exc:  # noqa: BLE001 - preserve the operation failure
        failure = exc
    cleanup_failure: Exception | None = None
    if temporary is not None:
        try:
            temporary.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - report cleanup with operation failure
            cleanup_failure = exc
    if isinstance(failure, PublicationGateError):
        blockers = _contextualize_recovery_blockers(failure, path, "rollback")
    elif failure is not None:
        blockers = [_rollback_failure(failure, path, "rollback_temp")]
    else:
        blockers = []
    if cleanup_failure is not None:
        blockers.append({"reason": "rollback_cleanup_failed", "scope": "rollback_temp", "phase": "rollback_cleanup",
                         "path": str(temporary), "message": str(cleanup_failure)})
    if blockers:
        summary = "; ".join(f"{blocker.get('reason', blocker)}: {blocker.get('message', '')}" for blocker in blockers)
        raise PublicationGateError(
            "artifact_publishable", "<unknown>", blockers,
            f"artifact_publishable rollback recovery failed: {summary}",
        ) from failure

def _cleanup_paths(paths: list[Path | None], deck_id: str) -> list[dict[str, Any]]:
    """Remove every unpublished temporary and report each failure."""
    failures: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in paths:
        if path is None or path in seen:
            continue
        seen.add(path)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            failures.append({"reason": "temp_cleanup_failed", "path": str(path), "message": str(exc)})
    return failures

def _raise_publication_failure(
    deck_id: str,
    primary: Exception,
    cleanup_failures: list[dict[str, Any]],
    rollback_failures: list[dict[str, Any]],
) -> None:
    """Aggregate primary, cleanup, and recovery blockers without masking."""
    blockers = list(primary.blockers) if isinstance(primary, PublicationGateError) else [
        {
            "reason": "short_write" if "short" in str(primary).lower() else "publication_failed",
            "message": str(primary),
        }
    ]
    blockers.extend(cleanup_failures)
    blockers.extend(rollback_failures)
    if len(blockers) > 1 or cleanup_failures or rollback_failures:
        summary = "; ".join(
            f"{item.get('reason')}: {item.get('message', '')}" for item in blockers
        )
        raise PublicationGateError(
            "artifact_publishable", deck_id, blockers,
            f"artifact_publishable recovery required for deck {deck_id}: {summary}",
        ) from primary
    if isinstance(primary, PublicationGateError):
        raise primary
    raise PublicationGateError(
        "artifact_publishable", deck_id, blockers,
        f"artifact_publishable blocked for deck {deck_id}: {blockers[0].get('reason')}: {primary}",
    ) from primary

def _fsync_directory(directory: Path) -> None:
    """Synchronize a directory entry after atomic replacement on POSIX."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
