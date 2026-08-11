"""Deterministic schema-v2 evidence-store serialization utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from presentation_evidence_contracts import EvidenceContractError, validate_envelope


EVIDENCE_STORE_RELATIVE_PATH = Path(".research/presentations/state/evidence.yaml")


def evidence_store_path(project_root: Path) -> Path:
    """Return the canonical schema-v2 evidence-store path.

    Args:
        project_root: Project root containing report-slides state.

    Returns:
        The lexical path for the authoritative evidence YAML store.

    Raises:
        TypeError: If ``project_root`` is not a path.
    """
    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")
    return project_root / EVIDENCE_STORE_RELATIVE_PATH


def serialize_evidence_store(evidence: Mapping[str, Mapping[str, Any]]) -> bytes:
    """Serialize deterministic schema-v2 evidence YAML.

    Args:
        evidence: Exact schema-v2 envelopes keyed by their immutable IDs.

    Returns:
        UTF-8 YAML bytes with canonical top-level ordering.

    Raises:
        EvidenceContractError: If any key or envelope is not exact and valid.
    """
    if not isinstance(evidence, Mapping):
        raise EvidenceContractError("evidence store must be a mapping")
    records: dict[str, dict[str, Any]] = {}
    for evidence_id in sorted(evidence):
        if not isinstance(evidence_id, str) or not evidence_id:
            raise EvidenceContractError("evidence store keys must be nonempty strings")
        record = validate_envelope(evidence[evidence_id])
        if record["id"] != evidence_id:
            raise EvidenceContractError("evidence store key must match envelope id")
        records[evidence_id] = record
    return yaml.safe_dump(
        {"version": 2, "evidence": records},
        allow_unicode=True,
        sort_keys=True,
    ).encode("utf-8")
