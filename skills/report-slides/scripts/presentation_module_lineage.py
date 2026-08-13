"""Resolve persisted production lineage for current visual modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from presentation_artifact_provenance import MODULE_ARTIFACT_KINDS
from presentation_events import load_artifacts, load_assignments
from presentation_evidence_cas import CasError, read_verified_source
from presentation_evidence_contracts import (
    EvidenceContractError,
    validate_store_record,
)
from validate_visual_module import validate_worker_assignment


def resolve_module_production_lineage(
    project_root: Path,
    module: Mapping[str, Any],
    deck_id: str,
    relations: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Resolve one persisted assignment and verified module artifact.

    Args:
        project_root: Project root containing presentation state and artifacts.
        module: Current visual-module record.
        deck_id: Deck owning the module through its parent slide.
        relations: Current authoritative deck, slide, and module maps.

    Returns:
        Resolved lineage records and deterministic named blockers.
    """
    blockers: list[dict[str, Any]] = []
    assignment_path = module.get("assignment_path")
    if not isinstance(assignment_path, str) or not assignment_path:
        blockers.append({"reason": "missing_assignment_path"})
    assignment_matches = (
        [
            (record_id, record)
            for record_id, record in load_assignments(project_root).items()
            if record.get("deck_id") == deck_id
            and record.get("module_id") == module.get("id")
            and record.get("assignment_path") == assignment_path
        ]
        if isinstance(assignment_path, str) and assignment_path
        else []
    )
    assignment = _validated_module_assignment(
        project_root,
        assignment_matches,
        module,
        relations,
        blockers,
        path_present=isinstance(assignment_path, str) and bool(assignment_path),
    )
    artifact_path = module.get("artifact_manifest_path")
    if not isinstance(artifact_path, str) or not artifact_path:
        blockers.append({"reason": "missing_artifact_manifest_path"})
    artifact_matches = (
        [
            (record_id, record)
            for record_id, record in load_artifacts(project_root).items()
            if record.get("deck_id") == deck_id
            and record.get("module_id") == module.get("id")
            and record.get("path") == artifact_path
        ]
        if isinstance(artifact_path, str) and artifact_path
        else []
    )
    artifact = _validated_module_artifact(
        project_root,
        artifact_matches,
        assignment,
        relations,
        blockers,
        path_present=isinstance(artifact_path, str) and bool(artifact_path),
    )
    lineage: dict[str, dict[str, Any]] = {}
    if assignment is not None:
        lineage["assignment"] = assignment
    if artifact is not None:
        lineage["artifact"] = artifact
    return lineage, blockers


def _validated_module_assignment(
    project_root: Path,
    matches: list[tuple[str, dict[str, Any]]],
    module: Mapping[str, Any],
    relations: Mapping[str, Mapping[str, Any]],
    blockers: list[dict[str, Any]],
    *,
    path_present: bool,
) -> dict[str, Any] | None:
    """Return one relation-valid assignment or append its named blocker."""
    if len(matches) != 1:
        if path_present:
            reason = (
                "module_assignment_record_missing"
                if not matches
                else "module_assignment_record_ambiguous"
            )
            blockers.append({"reason": reason})
        return None
    record_id, record = matches[0]
    try:
        if record.get("id") != record_id:
            raise EvidenceContractError("assignment record id does not match map key")
        validate_store_record("assignments", record, relations=relations)
        if record.get("dependencies") != module.get("dependencies"):
            raise EvidenceContractError("assignment dependencies do not match module")
        if record.get("worker_type") != module.get("module_type"):
            raise EvidenceContractError("assignment worker_type does not match module")
    except EvidenceContractError:
        blockers.append({"reason": "module_assignment_record_invalid"})
        return None
    contract = _assignment_contract(project_root, record, blockers)
    if contract is None:
        return None
    protected_fields = (
        "module_id",
        "worker_type",
        "dependencies",
        "spec_sha256",
        "inputs_resolved",
        "blocker",
    )
    if any(contract.get(field) != record.get(field) for field in protected_fields):
        blockers.append({"reason": "module_assignment_file_invalid"})
        return None
    return dict(record)


def _assignment_contract(
    project_root: Path,
    record: Mapping[str, Any],
    blockers: list[dict[str, Any]],
) -> Mapping[str, Any] | None:
    """Read and validate the exact no-follow worker-assignment bytes."""
    try:
        source = read_verified_source(project_root, record["assignment_path"])
    except (CasError, KeyError):
        blockers.append({"reason": "module_assignment_file_unreadable"})
        return None
    try:
        text = source.content.decode("utf-8")
        suffix = Path(record["assignment_path"]).suffix.lower()
        if suffix in {".yaml", ".yml"}:
            contract = yaml.safe_load(text)
        elif suffix == ".json":
            contract = json.loads(text)
        else:
            raise ValueError("unsupported assignment contract extension")
    except (UnicodeError, ValueError, yaml.YAMLError):
        blockers.append({"reason": "module_assignment_file_invalid"})
        return None
    if validate_worker_assignment(contract):
        blockers.append({"reason": "module_assignment_file_invalid"})
        return None
    if not isinstance(contract, Mapping):
        blockers.append({"reason": "module_assignment_file_invalid"})
        return None
    return contract


def _validated_module_artifact(
    project_root: Path,
    matches: list[tuple[str, dict[str, Any]]],
    assignment: Mapping[str, Any] | None,
    relations: Mapping[str, Mapping[str, Any]],
    blockers: list[dict[str, Any]],
    *,
    path_present: bool,
) -> dict[str, Any] | None:
    """Return one current verified module artifact or append its blocker."""
    if len(matches) != 1:
        if path_present:
            reason = (
                "module_artifact_record_missing"
                if not matches
                else "module_artifact_record_ambiguous"
            )
            blockers.append({"reason": reason})
        return None
    record_id, record = matches[0]
    try:
        if record.get("id") != record_id:
            raise EvidenceContractError("artifact record id does not match map key")
        validate_store_record("artifacts", record, relations=relations)
        if record.get("artifact_kind") not in MODULE_ARTIFACT_KINDS:
            raise EvidenceContractError("artifact kind is not module-bearing")
        if assignment is not None and record.get("producer_id") != assignment.get(
            "worker_id"
        ):
            raise EvidenceContractError("artifact producer does not match assignment")
    except EvidenceContractError:
        blockers.append({"reason": "module_artifact_record_invalid"})
        return None
    try:
        actual_digest = read_verified_source(project_root, record["path"]).digest
    except (CasError, KeyError):
        blockers.append({"reason": "module_artifact_file_unreadable"})
        return None
    if actual_digest != record.get("sha256"):
        blockers.append({"reason": "module_artifact_digest_mismatch"})
        return None
    return dict(record)
