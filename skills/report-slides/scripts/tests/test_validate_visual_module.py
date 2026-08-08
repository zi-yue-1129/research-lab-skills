"""Tests for strict Complex Visual Specification and Worker Assignment validation."""
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from validate_visual_module import (
    validate_complex_visual_spec,
    validate_module_spec,
    validate_worker_assignment,
)

SCRIPT = Path(__file__).resolve().parent.parent / "validate_visual_module.py"

_MODULE_DEFAULTS = {
    "semantic_responsibility": "Represent one semantically independent visual module",
    "input_anchors": [],
    "output_anchors": [],
    "dependencies": [],
    "dimensions": {"width": 320, "height": 180},
    "style_tokens_ref": None,
    "editability": "native",
    "annotation_requirements": [],
    "reuse_of": None,
}


def _module(module_id: str, **overrides: Any) -> dict[str, Any]:
    """Build a complete ModuleSpec fixture with explicit contract fields."""
    module: dict[str, Any] = {
        "id": module_id,
        "purpose": "Represent one semantically independent visual module",
        "semantic_responsibility": "Represent one semantically independent visual module",
        "route": "native",
        "module_type": "architecture",
        **_MODULE_DEFAULTS,
    }
    module.update(overrides)
    return module


_VALID_SPEC = {
    "schema_version": 1,
    "visual_id": "model-architecture-01",
    "message": "Show how action conditioning affects latent-state prediction",
    "modules": [
        _module("observation-input", purpose="Represent visual observation input", output_anchors=["observation-embedding"]),
        _module("command-input", purpose="Represent velocity and angular-velocity commands", output_anchors=["command-embedding"]),
        _module(
            "latent-dynamics",
            purpose="Represent action-conditioned latent transition",
            input_anchors=["observation-embedding", "command-embedding"],
            output_anchors=["predicted-latent"],
            dependencies=["observation-input", "command-input"],
        ),
        _module(
            "decoder-output",
            purpose="Represent decoded predicted state",
            input_anchors=["predicted-latent"],
            dependencies=["latent-dynamics"],
        ),
    ],
    "connections": [
        {"from": "observation-input.observation-embedding", "to": "latent-dynamics.observation-embedding"},
        {"from": "command-input.command-embedding", "to": "latent-dynamics.command-embedding"},
        {"from": "latent-dynamics.predicted-latent", "to": "decoder-output.predicted-latent"},
    ],
    "layout": {"direction": "left-to-right", "hierarchy": ["observation-input", "command-input", "latent-dynamics", "decoder-output"]},
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the visual-module validator CLI."""
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_valid_spec_passes(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(_VALID_SPEC))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_spec_missing_modules_fails(tmp_path: Path) -> None:
    spec = {**_VALID_SPEC, "modules": []}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("modules" in err for err in data["errors"])


def test_spec_duplicate_module_id_fails(tmp_path: Path) -> None:
    spec = {**_VALID_SPEC, "modules": [_VALID_SPEC["modules"][0], {**_VALID_SPEC["modules"][0]}]}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("duplicate module id" in err for err in data["errors"])


def test_spec_connection_referencing_unknown_module_fails(tmp_path: Path) -> None:
    spec = {**_VALID_SPEC, "connections": [{"from": "nonexistent.out", "to": "latent-dynamics.observation_embedding"}]}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("does not reference a declared module" in err for err in data["errors"])


def test_complex_spec_requires_exact_connection_anchors() -> None:
    """Reject a connection endpoint that names no declared output anchor."""
    spec = {**_VALID_SPEC, "connections": [{
        "from": "observation-input.not-declared",
        "to": "latent-dynamics.observation-embedding",
    }]}
    errors = validate_complex_visual_spec(spec)
    assert any("not-declared" in error and "output anchor" in error for error in errors)


def test_module_dependencies_are_declared_and_acyclic() -> None:
    """Reject unknown dependencies and a cycle in the module graph."""
    spec = {**_VALID_SPEC, "modules": [dict(module) for module in _VALID_SPEC["modules"]]}
    spec["modules"][0]["dependencies"] = ["decoder-output"]
    spec["modules"][3]["dependencies"] = ["observation-input"]
    errors = validate_complex_visual_spec(spec)
    assert any("cycle" in error for error in errors)


def test_module_spec_requires_complete_contract_fields() -> None:
    """Reject every omitted field that workers need to render a module."""
    required = (
        "id", "purpose", "semantic_responsibility", "route", "module_type",
        "input_anchors", "output_anchors", "dependencies", "dimensions",
        "style_tokens_ref", "editability", "annotation_requirements", "reuse_of",
    )
    for field in required:
        module = _module("one")
        module.pop(field)
        errors = validate_module_spec(module, 0)
        assert any(field in error for error in errors), field


def test_module_spec_rejects_unhashable_anchor_values_without_crashing() -> None:
    """Return a validation error for malformed anchor values."""
    module = _module("one", input_anchors=[{"anchor": "bad"}])

    errors = validate_module_spec(module, 0)

    assert any("input_anchors" in error for error in errors)


def test_spec_invalid_route_fails(tmp_path: Path) -> None:
    bad_module = {**_VALID_SPEC["modules"][0], "route": "not-a-real-route"}
    spec = {**_VALID_SPEC, "modules": [bad_module]}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any(".route:" in err for err in data["errors"])


def test_spec_invalid_module_type_fails(tmp_path: Path) -> None:
    bad_module = {**_VALID_SPEC["modules"][0], "module_type": "not-a-real-type"}
    spec = {**_VALID_SPEC, "modules": [bad_module]}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any(".module_type:" in err for err in data["errors"])


def test_spec_missing_layout_fails(tmp_path: Path) -> None:
    spec = {k: v for k, v in _VALID_SPEC.items() if k != "layout"}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("layout" in err for err in data["errors"])


def test_valid_worker_assignment_passes(tmp_path: Path) -> None:
    assignment = {
        "schema_version": 1,
        "module_id": "mod_20260806_ab12cd", "worker_type": "architecture",
        "dependencies": [], "spec_sha256": "a" * 64,
        "assigned_at": "2026-08-06T00:00:00Z", "inputs_resolved": True, "blocker": None,
    }
    assignment_path = tmp_path / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump(assignment))

    result = _run("--assignment", str(assignment_path), "--json")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_worker_assignment_missing_inputs_resolved_fails(tmp_path: Path) -> None:
    assignment = {
        "schema_version": 1,
        "module_id": "mod_20260806_ab12cd", "worker_type": "architecture",
        "dependencies": [], "spec_sha256": "a" * 64,
        "assigned_at": "2026-08-06T00:00:00Z",
    }
    assignment_path = tmp_path / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump(assignment))

    result = _run("--assignment", str(assignment_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("inputs_resolved" in err for err in data["errors"])


def test_worker_assignment_invalid_worker_type_fails(tmp_path: Path) -> None:
    assignment = {
        "schema_version": 1,
        "module_id": "mod_20260806_ab12cd", "worker_type": "not-a-real-worker",
        "dependencies": [], "spec_sha256": "a" * 64,
        "assigned_at": "2026-08-06T00:00:00Z", "inputs_resolved": True, "blocker": None,
    }
    assignment_path = tmp_path / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump(assignment))

    result = _run("--assignment", str(assignment_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("worker_type" in err for err in data["errors"])


def test_worker_assignment_requires_schema_version_one() -> None:
    """Reject assignments with a missing or incompatible schema version."""
    assignment = {
        "schema_version": 1,
        "module_id": "mod_20260806_ab12cd",
        "worker_type": "architecture",
        "dependencies": [],
        "spec_sha256": "a" * 64,
        "assigned_at": "2026-08-06T00:00:00Z",
        "inputs_resolved": True,
        "blocker": None,
    }
    for invalid_version in (None, 2, True):
        candidate = dict(assignment)
        if invalid_version is None:
            candidate.pop("schema_version")
        else:
            candidate["schema_version"] = invalid_version
        errors = validate_worker_assignment(candidate)
        assert any("schema_version" in error for error in errors), invalid_version
