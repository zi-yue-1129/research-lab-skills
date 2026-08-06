#!/usr/bin/env python3
"""validate_visual_module.py -- Schema validator for the Complex Visual
Specification (with its embedded ModuleSpec list) and Worker Assignment
contracts, used at Stages 7-9 of the report-slides multi-agent workflow.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Set

import yaml

_ROUTES = frozenset({"native", "data", "generative", "hybrid"})
_MODULE_TYPES = frozenset({"data_visualization", "architecture", "conceptual", "annotation"})
_EDITABILITY = frozenset({"native", "hybrid", "raster"})


def _load_document(path: Path) -> Any:
    """Load a YAML or JSON document by file extension."""
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


def validate_module_spec(module: Any, index: int) -> List[str]:
    """Validate one ModuleSpec embedded in a Complex Visual Specification.

    Args:
        module: The parsed module mapping.
        index: Its position in the spec's "modules" list.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    prefix = f"modules[{index}]"
    if not isinstance(module, dict):
        return [f"{prefix}: must be a mapping"]
    for field in ("id", "purpose"):
        value = module.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}.{field}: required non-empty string")
    route = module.get("route")
    if route not in _ROUTES:
        errors.append(f"{prefix}.route: must be one of {sorted(_ROUTES)}, got {route!r}")
    module_type = module.get("module_type")
    if module_type not in _MODULE_TYPES:
        errors.append(f"{prefix}.module_type: must be one of {sorted(_MODULE_TYPES)}, got {module_type!r}")
    editability = module.get("editability")
    if editability is not None and editability not in _EDITABILITY:
        errors.append(f"{prefix}.editability: must be one of {sorted(_EDITABILITY)} if given, got {editability!r}")
    for key in ("input_anchors", "output_anchors", "dependencies"):
        if key in module and not isinstance(module[key], list):
            errors.append(f"{prefix}.{key}: must be a list if present")
    return errors


def validate_complex_visual_spec(doc: Any) -> List[str]:
    """Validate a full Complex Visual Specification document.

    Args:
        doc: The parsed Complex Visual Specification mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]
    for field in ("visual_id", "message"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")
    modules = doc.get("modules")
    module_ids: Set[str] = set()
    if not isinstance(modules, list) or not modules:
        errors.append("modules: required non-empty list")
    else:
        for i, module in enumerate(modules):
            errors.extend(validate_module_spec(module, i))
            module_id = module.get("id") if isinstance(module, dict) else None
            if module_id:
                if module_id in module_ids:
                    errors.append(f"modules[{i}].id: duplicate module id {module_id!r}")
                module_ids.add(module_id)
    connections = doc.get("connections", [])
    if not isinstance(connections, list):
        errors.append("connections: must be a list if present")
    else:
        for i, conn in enumerate(connections):
            if not isinstance(conn, dict) or "from" not in conn or "to" not in conn:
                errors.append(f"connections[{i}]: must be a mapping with 'from' and 'to'")
                continue
            for end in ("from", "to"):
                endpoint = conn[end]
                owner = endpoint.split(".", 1)[0] if isinstance(endpoint, str) else None
                if owner not in module_ids:
                    errors.append(f"connections[{i}].{end}: {endpoint!r} does not reference a declared module")
    layout = doc.get("layout")
    if not isinstance(layout, dict) or not layout.get("direction") or not isinstance(layout.get("hierarchy"), list):
        errors.append("layout: required mapping with 'direction' (str) and 'hierarchy' (list)")
    return errors


def validate_worker_assignment(doc: Any) -> List[str]:
    """Validate a Worker Assignment document.

    Args:
        doc: The parsed Worker Assignment mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]
    for field in ("module_id", "worker_type", "assigned_at"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")
    if doc.get("worker_type") not in _MODULE_TYPES:
        errors.append(f"worker_type: must be one of {sorted(_MODULE_TYPES)}, got {doc.get('worker_type')!r}")
    if not isinstance(doc.get("inputs_resolved"), bool):
        errors.append("inputs_resolved: required bool")
    if "blocker" in doc and doc["blocker"] is not None and not isinstance(doc["blocker"], str):
        errors.append("blocker: must be a string or null")
    return errors


def main() -> None:
    """CLI entry point for validate_visual_module.py."""
    parser = argparse.ArgumentParser(description="Validate Complex Visual Specification / Worker Assignment documents.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--spec", metavar="PATH", type=Path)
    group.add_argument("--assignment", metavar="PATH", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    target = args.spec or args.assignment
    try:
        doc = _load_document(target)
    except (OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        errors = [f"failed to read/parse {target}: {exc}"]
    else:
        errors = validate_complex_visual_spec(doc) if args.spec else validate_worker_assignment(doc)

    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
