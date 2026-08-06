"""Tests for validate_visual_module.py."""
import json
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parent.parent / "validate_visual_module.py"

_VALID_SPEC = {
    "visual_id": "model-architecture-01",
    "message": "Show how action conditioning affects latent-state prediction",
    "modules": [
        {
            "id": "observation-input", "purpose": "Represent visual observation input",
            "route": "native", "module_type": "architecture", "output_anchors": ["observation_embedding"],
        },
        {
            "id": "command-input", "purpose": "Represent velocity and angular-velocity commands",
            "route": "native", "module_type": "architecture", "output_anchors": ["command_embedding"],
        },
        {
            "id": "latent-dynamics", "purpose": "Represent action-conditioned latent transition",
            "route": "native", "module_type": "architecture",
            "input_anchors": ["observation_embedding", "command_embedding"],
            "output_anchors": ["predicted_latent"],
        },
    ],
    "connections": [
        {"from": "observation-input.observation_embedding", "to": "latent-dynamics.observation_embedding"},
        {"from": "command-input.command_embedding", "to": "latent-dynamics.command_embedding"},
    ],
    "layout": {"direction": "left-to-right", "hierarchy": ["inputs", "latent transition"]},
}


def _run(*args: str) -> subprocess.CompletedProcess:
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
        "module_id": "mod_20260806_ab12cd", "worker_type": "architecture",
        "assigned_at": "2026-08-06T00:00:00Z", "inputs_resolved": True, "blocker": None,
    }
    assignment_path = tmp_path / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump(assignment))

    result = _run("--assignment", str(assignment_path), "--json")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_worker_assignment_missing_inputs_resolved_fails(tmp_path: Path) -> None:
    assignment = {"module_id": "mod_20260806_ab12cd", "worker_type": "architecture", "assigned_at": "2026-08-06T00:00:00Z"}
    assignment_path = tmp_path / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump(assignment))

    result = _run("--assignment", str(assignment_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("inputs_resolved" in err for err in data["errors"])


def test_worker_assignment_invalid_worker_type_fails(tmp_path: Path) -> None:
    assignment = {
        "module_id": "mod_20260806_ab12cd", "worker_type": "not-a-real-worker",
        "assigned_at": "2026-08-06T00:00:00Z", "inputs_resolved": True,
    }
    assignment_path = tmp_path / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump(assignment))

    result = _run("--assignment", str(assignment_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("worker_type" in err for err in data["errors"])
