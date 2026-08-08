"""Shared loading, canonicalization, and integrity helpers for contracts.

The report-slides workflow stores contracts as either YAML or JSON.  These
helpers keep source-format handling separate from contract-specific schema
validation while giving every workflow action one deterministic digest and
dependency-integrity implementation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def load_contract(path: Path) -> Any:
    """Load a YAML or JSON contract document from ``path``.

    Args:
        path: Contract path.  ``.yaml``/``.yml`` and ``.json`` are supported.

    Returns:
        The parsed contract value.

    Raises:
        ValueError: If ``path`` has an unsupported extension.
        OSError: If the path cannot be read.
        json.JSONDecodeError: If a JSON document is malformed.
        yaml.YAMLError: If a YAML document is malformed.
    """
    suffix = path.suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        raise ValueError(f"unsupported contract file extension: {path.suffix or '<none>'}")

    text = path.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    return json.loads(text)


def canonical_json_bytes(document: Any) -> bytes:
    """Serialize a contract deterministically for digest calculation.

    Args:
        document: JSON-compatible contract value.

    Returns:
        UTF-8 encoded canonical JSON bytes.

    Raises:
        TypeError: If ``document`` contains a value unsupported by JSON.
        ValueError: If ``document`` contains a non-finite number.
    """
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def contract_sha256(document: Any) -> str:
    """Return the canonical SHA-256 digest for a contract document.

    Args:
        document: JSON-compatible contract value.

    Returns:
        Lowercase hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def validate_schema_version(document: Any) -> list[str]:
    """Validate that a contract declares schema version ``1``.

    Args:
        document: Parsed contract value.

    Returns:
        A list containing a schema-version error, or an empty list when the
        document declares the supported version.
    """
    if not isinstance(document, dict):
        return ["schema_version: required integer value 1"]
    value = document.get("schema_version")
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        return ["schema_version: required integer value 1"]
    return []


def validate_acyclic_dependencies(
    nodes: set[str], edges: dict[str, list[str]], field: str
) -> list[str]:
    """Validate declared dependency IDs and detect directed cycles.

    Args:
        nodes: IDs declared by the contract.
        edges: Mapping from each node ID to its dependency IDs.
        field: Contract field name used in human-readable errors.

    Returns:
        Deterministically ordered dependency-integrity errors.
    """
    errors: list[str] = []
    declared_nodes = set(nodes)
    unknown_edges: set[tuple[str, str]] = set()
    for source in sorted(edges, key=str):
        if source not in declared_nodes:
            errors.append(f"{field}: undeclared node {source!r}")
            continue
        dependencies = edges[source]
        if not isinstance(dependencies, list):
            errors.append(f"{field}: dependencies for {source!r} must be a list")
            continue
        for dependency in dependencies:
            if not isinstance(dependency, str) or not dependency.strip():
                errors.append(f"{field}: dependency for {source!r} must be a non-empty string")
            elif dependency not in declared_nodes:
                unknown_edges.add((source, dependency))
    for source, dependency in sorted(unknown_edges, key=lambda pair: (str(pair[0]), str(pair[1]))):
        errors.append(f"{field}: undeclared dependency {dependency!r} for {source!r}")

    adjacency: dict[str, list[str]] = {
        node: [
            dependency
            for dependency in edges.get(node, [])
            if isinstance(dependency, str) and dependency in declared_nodes
        ]
        for node in declared_nodes
    }
    visit_state: dict[str, int] = {}
    stack: list[str] = []
    cycle_signatures: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        """Visit one node and record any cycle reachable from it."""
        state = visit_state.get(node, 0)
        if state == 1:
            cycle_start = stack.index(node)
            cycle = stack[cycle_start:] + [node]
            cycle_signatures.add(_canonical_cycle_signature(cycle))
            return
        if state == 2:
            return
        visit_state[node] = 1
        stack.append(node)
        for dependency in sorted(adjacency[node], key=str):
            visit(dependency)
        stack.pop()
        visit_state[node] = 2

    for node in sorted(declared_nodes, key=str):
        if visit_state.get(node, 0) == 0:
            visit(node)

    for signature in sorted(cycle_signatures, key=lambda value: tuple(map(str, value))):
        errors.append(f"{field}: dependency cycle detected: {' -> '.join(signature)}")
    return errors


def _canonical_cycle_signature(cycle: list[str]) -> tuple[str, ...]:
    """Rotate a closed cycle to its lexicographically smallest start ID."""
    if len(cycle) <= 1:
        return tuple(cycle)
    ring = cycle[:-1]
    rotations = [ring[index:] + ring[:index] for index in range(len(ring))]
    canonical = min(rotations, key=lambda value: tuple(map(str, value)))
    return tuple(canonical + [canonical[0]])
