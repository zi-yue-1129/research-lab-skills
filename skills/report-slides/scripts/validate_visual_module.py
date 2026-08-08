#!/usr/bin/env python3
"""Validate modular visual and worker-assignment contracts."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import numbers
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from presentation_contracts import (
    load_contract,
    validate_acyclic_dependencies,
    validate_schema_version,
)


_ROUTES = frozenset({"native", "data", "generative", "hybrid"})
_MODULE_TYPES = frozenset({"data_visualization", "architecture", "conceptual", "annotation"})
_EDITABILITY = frozenset({"native", "hybrid", "raster"})
_MODULE_ID_PATTERN = re.compile(r"^mod_\d{8}_[0-9a-f]{6}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def _load_document(path: Path) -> Any:
    """Load a supported YAML or JSON contract document."""
    return load_contract(path)


def validate_module_spec(module: Any, index: int) -> list[str]:
    """Validate one complete ModuleSpec embedded in a visual specification.

    Args:
        module: Parsed ModuleSpec mapping.
        index: Position in the parent ``modules`` list for error context.

    Returns:
        Deterministically ordered human-readable validation errors.
    """
    prefix = f"modules[{index}]"
    if not isinstance(module, dict):
        return [f"{prefix}: must be a mapping"]

    errors: list[str] = []
    for field in ("id", "purpose", "semantic_responsibility"):
        _require_nonempty_string(module, field, f"{prefix}.{field}", errors)

    route = module.get("route")
    if route not in _ROUTES:
        errors.append(f"{prefix}.route: must be one of {sorted(_ROUTES)}, got {route!r}")
    module_type = module.get("module_type")
    if module_type not in _MODULE_TYPES:
        errors.append(
            f"{prefix}.module_type: must be one of {sorted(_MODULE_TYPES)}, got {module_type!r}"
        )

    _validate_anchor_list(module, "input_anchors", prefix, errors)
    _validate_anchor_list(module, "output_anchors", prefix, errors)
    _validate_dependency_list(module, prefix, errors)
    _validate_dimensions(module, prefix, errors)
    _validate_style_tokens_ref(module, prefix, errors)

    editability = module.get("editability")
    if editability not in _EDITABILITY:
        errors.append(
            f"{prefix}.editability: must be one of {sorted(_EDITABILITY)}, got {editability!r}"
        )
    annotation_requirements = module.get("annotation_requirements")
    if not isinstance(annotation_requirements, list):
        errors.append(f"{prefix}.annotation_requirements: required list")
    elif any(
        not isinstance(requirement, str) or not requirement.strip()
        for requirement in annotation_requirements
    ):
        errors.append(
            f"{prefix}.annotation_requirements: every value must be a non-empty string"
        )
    _validate_nullable_text(module, "reuse_of", prefix, errors)
    return errors


def validate_complex_visual_spec(doc: Any) -> list[str]:
    """Validate a complete Complex Visual Specification.

    Args:
        doc: Parsed Complex Visual Specification mapping.

    Returns:
        Deterministically ordered human-readable validation errors.
    """
    if not isinstance(doc, dict):
        return ["document must be a mapping"]

    errors: list[str] = []
    errors.extend(validate_schema_version(doc))
    for field in ("visual_id", "message"):
        _require_nonempty_string(doc, field, field, errors)

    modules = doc.get("modules")
    module_ids: set[str] = set()
    if not isinstance(modules, list) or not modules:
        errors.append("modules: required non-empty list")
    else:
        dependency_edges: dict[str, list[str]] = {}
        for index, module in enumerate(modules):
            errors.extend(validate_module_spec(module, index))
            if not isinstance(module, dict):
                continue
            module_id = module.get("id")
            if isinstance(module_id, str) and module_id.strip():
                if module_id in module_ids:
                    errors.append(f"modules[{index}].id: duplicate module id {module_id!r}")
                module_ids.add(module_id)
                dependencies = module.get("dependencies")
                dependency_edges[module_id] = dependencies if isinstance(dependencies, list) else []
        errors.extend(validate_acyclic_dependencies(module_ids, dependency_edges, "dependencies"))

    connections = doc.get("connections")
    if not isinstance(connections, list):
        errors.append("connections: required list")
    else:
        for index, connection in enumerate(connections):
            prefix = f"connections[{index}]"
            if not isinstance(connection, dict) or "from" not in connection or "to" not in connection:
                errors.append(f"{prefix}: must be a mapping with 'from' and 'to'")
                continue
            _validate_endpoint(connection["from"], "from", prefix, module_ids, modules, errors)
            _validate_endpoint(connection["to"], "to", prefix, module_ids, modules, errors)

    layout = doc.get("layout")
    if not isinstance(layout, dict):
        errors.append("layout: required mapping with 'direction' (str) and 'hierarchy' (list)")
    else:
        direction = layout.get("direction")
        if not isinstance(direction, str) or not direction.strip():
            errors.append("layout.direction: required non-empty string")
        hierarchy = layout.get("hierarchy")
        if not isinstance(hierarchy, list) or not hierarchy:
            errors.append("layout.hierarchy: required non-empty list")
        elif any(not isinstance(item, str) or not item.strip() for item in hierarchy):
            errors.append("layout.hierarchy: every value must be a non-empty module ID")
        else:
            unknown = sorted(set(hierarchy) - module_ids)
            missing = sorted(module_ids - set(hierarchy))
            if unknown:
                errors.append(f"layout.hierarchy: undeclared module ID(s) {unknown!r}")
            if missing:
                errors.append(f"layout.hierarchy: missing module ID(s) {missing!r}")
    return errors


def validate_worker_assignment(doc: Any) -> list[str]:
    """Validate one Worker Assignment contract.

    Args:
        doc: Parsed Worker Assignment mapping.

    Returns:
        Deterministically ordered human-readable validation errors.
    """
    if not isinstance(doc, dict):
        return ["document must be a mapping"]

    errors: list[str] = []
    module_id = doc.get("module_id")
    if not isinstance(module_id, str) or not module_id.strip():
        errors.append("module_id: required generated module ID")
    elif _MODULE_ID_PATTERN.fullmatch(module_id) is None:
        errors.append("module_id: required generated module ID matching mod_YYYYMMDD_xxxxxx")

    worker_type = doc.get("worker_type")
    if worker_type not in _MODULE_TYPES:
        errors.append(f"worker_type: must be one of {sorted(_MODULE_TYPES)}, got {worker_type!r}")

    dependencies = doc.get("dependencies")
    if not isinstance(dependencies, list):
        errors.append("dependencies: required list of generated module IDs")
    else:
        for dependency in dependencies:
            if not isinstance(dependency, str) or _MODULE_ID_PATTERN.fullmatch(dependency) is None:
                errors.append(
                    "dependencies: every value must be a generated module ID "
                    "matching mod_YYYYMMDD_xxxxxx"
                )
                break

    spec_sha256 = doc.get("spec_sha256")
    if not isinstance(spec_sha256, str) or _SHA256_PATTERN.fullmatch(spec_sha256) is None:
        errors.append("spec_sha256: required 64-character lowercase hexadecimal digest")

    if not isinstance(doc.get("inputs_resolved"), bool):
        errors.append("inputs_resolved: required bool")
    assigned_at = doc.get("assigned_at")
    if not isinstance(assigned_at, str) or not _is_rfc3339_z(assigned_at):
        errors.append("assigned_at: required RFC3339 timestamp ending in Z")

    if "blocker" not in doc:
        errors.append("blocker: required string or null")
    elif doc["blocker"] is not None and (
        not isinstance(doc["blocker"], str) or not doc["blocker"].strip()
    ):
        errors.append("blocker: must be a non-empty string or null")
    return errors


def _validate_endpoint(
    endpoint: Any,
    direction: str,
    prefix: str,
    module_ids: set[str],
    modules: Any,
    errors: list[str],
) -> None:
    """Validate one exact ``module-id.anchor`` connection endpoint."""
    endpoint_prefix = f"{prefix}.{direction}"
    if not isinstance(endpoint, str) or endpoint.count(".") != 1:
        errors.append(f"{endpoint_prefix}: must be an exact <module-id>.<anchor> pair")
        return
    module_id, anchor = endpoint.split(".")
    if module_id not in module_ids:
        errors.append(f"{endpoint_prefix}: {endpoint!r} does not reference a declared module")
        return
    module = next(
        (candidate for candidate in modules if isinstance(candidate, dict) and candidate.get("id") == module_id),
        None,
    )
    anchors_key = "output_anchors" if direction == "from" else "input_anchors"
    anchors = module.get(anchors_key, []) if isinstance(module, dict) else []
    if anchor not in anchors:
        anchor_label = "output anchor" if direction == "from" else "input anchor"
        errors.append(
            f"{endpoint_prefix}: {module_id!r} does not declare {anchor_label} {anchor!r}"
        )


def _validate_anchor_list(
    module: dict[str, Any], field: str, prefix: str, errors: list[str]
) -> None:
    """Require a unique list of non-empty anchor names."""
    value = module.get(field)
    if not isinstance(value, list):
        errors.append(f"{prefix}.{field}: required list")
        return
    invalid_values = any(not isinstance(anchor, str) or not anchor.strip() for anchor in value)
    if invalid_values:
        errors.append(f"{prefix}.{field}: every value must be a non-empty string")
    if not invalid_values and len(set(value)) != len(value):
        errors.append(f"{prefix}.{field}: anchor names must be unique")


def _validate_dependency_list(
    module: dict[str, Any], prefix: str, errors: list[str]
) -> None:
    """Require a list of non-empty dependency IDs."""
    value = module.get("dependencies")
    if not isinstance(value, list):
        errors.append(f"{prefix}.dependencies: required list")
    elif any(not isinstance(dependency, str) or not dependency.strip() for dependency in value):
        errors.append(f"{prefix}.dependencies: every value must be a non-empty string")


def _validate_dimensions(
    module: dict[str, Any], prefix: str, errors: list[str]
) -> None:
    """Require positive finite width and height dimensions."""
    dimensions = module.get("dimensions")
    if not isinstance(dimensions, dict):
        errors.append(f"{prefix}.dimensions: required mapping with positive width and height")
        return
    for field in ("width", "height"):
        value = dimensions.get(field)
        if not _is_finite_number(value) or value <= 0:
            errors.append(f"{prefix}.dimensions.{field}: required positive number")


def _validate_style_tokens_ref(
    module: dict[str, Any], prefix: str, errors: list[str]
) -> None:
    """Require an explicit style-token path or null reference."""
    if "style_tokens_ref" not in module:
        errors.append(f"{prefix}.style_tokens_ref: required string or null")
        return
    value = module["style_tokens_ref"]
    if value is not None and (not isinstance(value, str) or not value.strip()):
        errors.append(f"{prefix}.style_tokens_ref: must be a non-empty string or null")


def _validate_nullable_text(
    module: dict[str, Any], field: str, prefix: str, errors: list[str]
) -> None:
    """Require an explicit string-or-null field."""
    if field not in module:
        errors.append(f"{prefix}.{field}: required string or null")
        return
    value = module[field]
    if value is not None and (not isinstance(value, str) or not value.strip()):
        errors.append(f"{prefix}.{field}: must be a non-empty string or null")


def _require_nonempty_string(
    document: dict[str, Any], field: str, prefix: str, errors: list[str]
) -> None:
    """Require one non-empty string field."""
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{prefix}: required non-empty string")


def _is_finite_number(value: Any) -> bool:
    """Return whether ``value`` is a finite real number but not a boolean."""
    return isinstance(value, numbers.Real) and not isinstance(value, bool) and math.isfinite(value)


def _is_rfc3339_z(value: str) -> bool:
    """Return whether ``value`` is a valid UTC RFC3339 timestamp ending in Z."""
    if _RFC3339_Z.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def main() -> None:
    """Run Complex Visual Specification or Worker Assignment validation."""
    parser = argparse.ArgumentParser(
        description="Validate Complex Visual Specification / Worker Assignment documents."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--spec", metavar="PATH", type=Path)
    group.add_argument("--assignment", metavar="PATH", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    target = args.spec or args.assignment
    try:
        document = _load_document(target)
        errors = validate_complex_visual_spec(document) if args.spec else validate_worker_assignment(document)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        errors = [f"failed to read/parse {target}: {exc}"]

    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
