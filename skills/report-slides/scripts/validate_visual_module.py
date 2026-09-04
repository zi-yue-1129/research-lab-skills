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

from design_tokens import DesignTokens, TokenError
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
    errors.extend(validate_schema_version(doc))
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
    """Require a non-empty design-token path.

    `null` is no longer accepted. An unresolved style reference is
    indistinguishable from a correctly applied style at render time, so the
    reference must always name a token file. Whether that file exists and
    validates is checked separately by `validate_style_tokens_resolvable`,
    which needs the document's directory.

    Args:
        module: Parsed ModuleSpec mapping.
        prefix: Error-message prefix identifying the module position.
        errors: Accumulator appended to in place.
    """
    if "style_tokens_ref" not in module:
        errors.append(f"{prefix}.style_tokens_ref: required non-empty string")
        return
    value = module["style_tokens_ref"]
    if not isinstance(value, str) or not value.strip():
        errors.append(
            f"{prefix}.style_tokens_ref: must be a non-empty string "
            f"naming a design-token file, got {value!r}"
        )


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


def _resolve_token_ref(doc_or_module: Any, base_dir: Path) -> Path:
    """Resolve a spec's style_tokens_ref against its own directory.

    Args:
        doc_or_module: A ModuleSpec mapping carrying `style_tokens_ref`.
        base_dir: Directory the specification was loaded from.

    Returns:
        The resolved token-file path.

    Raises:
        TokenError: If the reference is absent, empty, or escapes `base_dir`.
    """
    ref = doc_or_module.get("style_tokens_ref") if isinstance(doc_or_module, dict) else None
    if not isinstance(ref, str) or not ref.strip():
        raise TokenError(f"style_tokens_ref: required non-empty string, got {ref!r}")
    resolved_base = base_dir.resolve()
    candidate = (resolved_base / ref.strip()).resolve()
    try:
        candidate.relative_to(resolved_base)
    except ValueError as exc:
        raise TokenError(
            f"style_tokens_ref: {ref!r} resolves outside the specification directory"
        ) from exc
    return candidate


def validate_style_tokens_resolvable(doc: Any, base_dir: Path) -> list[str]:
    """Check that every module's style_tokens_ref resolves to valid tokens.

    Args:
        doc: Parsed Complex Visual Specification mapping.
        base_dir: Directory the specification was loaded from; references
            resolve relative to it and may not escape it.

    Returns:
        Deterministically ordered human-readable validation errors.
    """
    from validate_design_tokens import validate_token_file

    errors: list[str] = []
    modules = doc.get("modules") if isinstance(doc, dict) else None
    if not isinstance(modules, list):
        return errors
    resolved_base = base_dir.resolve()
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        ref = module.get("style_tokens_ref")
        if not isinstance(ref, str) or not ref.strip():
            continue  # already reported by _validate_style_tokens_ref
        prefix = f"modules[{index}].style_tokens_ref"
        candidate = (resolved_base / ref.strip()).resolve()
        try:
            candidate.relative_to(resolved_base)
        except ValueError:
            errors.append(
                f"{prefix}: {ref!r} resolves outside the specification directory"
            )
            continue
        for error in validate_token_file(candidate):
            errors.append(f"{prefix}: {error}")
    return errors


def resolved_token_digest(doc: Any, base_dir: Path) -> str:
    """Return the digest of the token set a module spec resolves to.

    Args:
        doc: A module or complex-visual specification mapping.
        base_dir: Directory the spec's relative paths resolve against.

    Returns:
        The `DesignTokens.digest` of the resolved file.

    Raises:
        TokenError: If the reference does not resolve or does not validate.
            Callers must not substitute a default: a module validated against
            the wrong token set is worse than one validated against none, since
            the record then asserts something false.
    """
    return DesignTokens.load(_resolve_token_ref(doc, base_dir)).digest


def _module_token_digests(doc: Any, base_dir: Path) -> dict[str, str]:
    """Map each module id to the digest of the token set it resolves to.

    Args:
        doc: Parsed Complex Visual Specification mapping.
        base_dir: Directory the specification was loaded from.

    Returns:
        Module id to token digest. Callers reach this only after
        `validate_style_tokens_resolvable` reported no errors, so every
        reference here is known to resolve.
    """
    digests: dict[str, str] = {}
    modules = doc.get("modules") if isinstance(doc, dict) else None
    if not isinstance(modules, list):
        return digests
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        # The Complex Visual Specification names the field `id`; the flatter
        # ModuleSpec mapping used by callers names it `module_id`.
        key = str(module.get("module_id") or module.get("id") or index)
        digests[key] = resolved_token_digest(module, base_dir)
    return digests


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
    token_digests: dict[str, str] = {}
    try:
        document = _load_document(target)
        if args.spec:
            errors = validate_complex_visual_spec(document)
            errors.extend(validate_style_tokens_resolvable(document, target.parent))
            if not errors:
                token_digests = _module_token_digests(document, target.parent)
        else:
            errors = validate_worker_assignment(document)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        errors = [f"failed to read/parse {target}: {exc}"]

    # `token_digests` names the token set each module was held to, so a caller
    # persisting the module spec can record which tokens it validated against.
    # "Resolved" alone only says some file was fine at some past moment.
    result = {"valid": not errors, "errors": errors}
    if args.spec:
        result["token_digests"] = token_digests
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
