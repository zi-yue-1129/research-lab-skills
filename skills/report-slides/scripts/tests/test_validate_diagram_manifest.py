"""Tests for diagram asset manifest, library, and plan validation."""

import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest
import yaml

from validate_diagram_manifest import (
    ValidationIssue,
    validate_asset_library,
    validate_diagram_plan,
    validate_manifest,
)


SCRIPT = Path(__file__).resolve().parent.parent / "validate_diagram_manifest.py"


def _complete_payload(asset_dir: Path) -> Dict[str, Any]:
    """Return a complete native manifest payload for one asset directory."""
    return {
        "schema_version": 1,
        "diagram_id": asset_dir.name,
        "purpose": "Explain training and evaluation.",
        "diagram_type": "architecture",
        "authoring_route": "native",
        "editability": "native",
        "source_files": ["source.svg"],
        "used_in": [{"deck": "weekly-progress", "slide": 4}],
        "derived_from": None,
        "based_on_revision": None,
        "changes": [],
        "generation": None,
        "review": {"status": "passed", "artifact": "review.json"},
    }


def _write_asset(
    root: Path,
    asset_id: str = "training-pipeline",
    payload: Optional[Dict[str, Any]] = None,
    source_files: Optional[Sequence[str]] = None,
) -> Path:
    """Write a manifest fixture and its declared native source artifacts."""
    asset_dir = root / asset_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    manifest_payload = payload or _complete_payload(asset_dir)
    declared_sources = source_files
    if declared_sources is None:
        declared_sources = manifest_payload.get("source_files", [])
    for source_file in declared_sources:
        source_path = asset_dir / source_file
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("artifact", encoding="utf-8")
    (asset_dir / "review.json").write_text("{}", encoding="utf-8")
    manifest_path = asset_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest_payload), encoding="utf-8")
    return manifest_path


def _write_plan(path: Path, payload: Dict[str, Any]) -> Path:
    """Write a diagram-plan YAML fixture."""
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _valid_plan_payload() -> Dict[str, Any]:
    """Return the complete plan payload from the Task 2 contract."""
    return {
        "schema_version": 1,
        "deck_id": "weekly-progress",
        "visuals": [
            {
                "diagram_id": "training-pipeline",
                "slide": 4,
                "purpose": "Explain the publishing gate.",
                "regions": [
                    "ingestion",
                    "training",
                    "evaluation-stage",
                    "publishing",
                ],
                "route": "native",
                "editability": "native",
                "reuse": {
                    "action": "modify",
                    "asset_id": "training-pipeline",
                },
            }
        ],
    }


def _issue_paths(issues: Sequence[ValidationIssue]) -> List[str]:
    """Return issue field paths in validator order."""
    return [issue.path for issue in issues]


def _run_cli(*arguments: str) -> subprocess.CompletedProcess:
    """Run the validator CLI with the supplied arguments."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_complete_asset_manifest_returns_no_issues(tmp_path: Path) -> None:
    """Accept a complete native asset manifest and its artifacts."""
    manifest_path = _write_asset(tmp_path)

    assert validate_manifest(manifest_path) == []


def test_validation_issue_is_immutable() -> None:
    """Keep the public validation issue value object immutable."""
    issue = ValidationIssue(Path("manifest.yaml"), "purpose", "invalid")

    with pytest.raises(FrozenInstanceError):
        issue.path = "other"


def test_missing_source_reports_indexed_source_field(tmp_path: Path) -> None:
    """Report a missing source file at its source-files list position."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    manifest_path = _write_asset(
        tmp_path,
        payload=payload,
        source_files=[],
    )
    payload["source_files"] = ["missing.svg"]
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    issues = validate_manifest(manifest_path)

    assert "source_files[0]" in _issue_paths(issues)


def test_manifest_issues_are_sorted_by_path_stably(tmp_path: Path) -> None:
    """Sort manifest issues by path while preserving equal-path order."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["schema_version"] = 2
    payload["purpose"] = ""
    payload["source_files"] = []
    manifest_path = _write_asset(tmp_path, payload=payload, source_files=[])

    issues = validate_manifest(manifest_path)

    assert _issue_paths(issues) == [
        "purpose",
        "schema_version",
        "source_files",
        "source_files",
    ]
    assert [
        issue.message for issue in issues if issue.path == "source_files"
    ] == [
        "source_files must not be empty",
        "native route requires an SVG source",
    ]


def test_asset_library_reports_invalid_ids_in_directory_order(tmp_path: Path) -> None:
    """Return invalid asset IDs ordered by their manifest paths."""
    for asset_id in ("a-asset", "z-asset"):
        payload = _complete_payload(tmp_path / asset_id)
        payload["diagram_id"] = "invalid ID"
        _write_asset(tmp_path, asset_id=asset_id, payload=payload)

    issues = validate_asset_library(tmp_path)

    assert [issue.manifest.parent.name for issue in issues] == [
        "a-asset",
        "z-asset",
    ]
    assert all(issue.path == "diagram_id" for issue in issues)


def test_malformed_yaml_root_reports_root_field(tmp_path: Path) -> None:
    """Reject a manifest whose YAML root is not a mapping."""
    asset_dir = tmp_path / "training-pipeline"
    asset_dir.mkdir()
    manifest_path = asset_dir / "manifest.yaml"
    manifest_path.write_text("- not-a-mapping\n", encoding="utf-8")

    issues = validate_manifest(manifest_path)

    assert any(issue.path == "root" for issue in issues)


def test_malformed_yaml_reports_yaml_error(tmp_path: Path) -> None:
    """Report malformed YAML without raising a parser exception."""
    asset_dir = tmp_path / "training-pipeline"
    asset_dir.mkdir()
    manifest_path = asset_dir / "manifest.yaml"
    manifest_path.write_text("schema_version: [\n", encoding="utf-8")

    issues = validate_manifest(manifest_path)

    assert len(issues) == 1
    assert issues[0].path == "yaml"


def test_manifest_id_must_match_directory(tmp_path: Path) -> None:
    """Reject a manifest ID that does not match its asset directory."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["diagram_id"] = "other-diagram"
    manifest_path = _write_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    assert any(issue.path == "diagram_id" for issue in issues)
    assert any("directory" in issue.message for issue in issues)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("diagram_type", "unknown"),
        ("authoring_route", "unknown"),
        ("editability", "unknown"),
        ("review", {"status": "unknown", "artifact": "review.json"}),
    ],
)
def test_unknown_or_invalid_enum_values_are_reported(
    tmp_path: Path, field: str, value: Any
) -> None:
    """Collect schema and enum contract violations by their field."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload[field] = value
    manifest_path = _write_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    expected_path = "review.status" if field == "review" else field
    assert expected_path in _issue_paths(issues)


def test_source_paths_must_be_relative_and_stay_inside_asset_directory(
    tmp_path: Path,
) -> None:
    """Reject absolute and parent-traversing source paths."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["source_files"] = ["../outside.svg", "/tmp/absolute.svg"]
    manifest_path = _write_asset(
        tmp_path,
        payload=payload,
        source_files=[],
    )
    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    issues = validate_manifest(manifest_path)

    assert "source_files[0]" in _issue_paths(issues)
    assert "source_files[1]" in _issue_paths(issues)


def test_used_in_slide_must_be_positive(tmp_path: Path) -> None:
    """Reject zero and negative slide locations."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["used_in"] = [
        {"deck": "weekly-progress", "slide": 0},
        {"deck": "weekly-progress", "slide": -2},
    ]
    manifest_path = _write_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    assert "used_in[0].slide" in _issue_paths(issues)
    assert "used_in[1].slide" in _issue_paths(issues)


def test_derivation_fields_must_be_strings_or_null(tmp_path: Path) -> None:
    """Reject non-string provenance revision and derivation values."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["derived_from"] = 7
    payload["based_on_revision"] = {"revision": "abc"}
    manifest_path = _write_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    assert "derived_from" in _issue_paths(issues)
    assert "based_on_revision" in _issue_paths(issues)


def test_change_entries_require_region_change_reason_and_valid_bbox(
    tmp_path: Path,
) -> None:
    """Collect malformed change fields and out-of-bounds bounding boxes."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["changes"] = [
        {"region": "", "change": "", "reason": "", "bbox": [0, 0, 1201, 675]},
        {"region": "evaluation", "change": "Added branch", "reason": "New gate", "bbox": [2, 4, 1, 5]},
    ]
    manifest_path = _write_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    assert "changes[0].region" in _issue_paths(issues)
    assert "changes[0].change" in _issue_paths(issues)
    assert "changes[0].reason" in _issue_paths(issues)
    assert "changes[0].bbox" in _issue_paths(issues)
    assert "changes[1].bbox" in _issue_paths(issues)


@pytest.mark.parametrize("bbox", [[0, 0, 1200], [0, 0, 1, 2, 3], [0, 0, float("nan"), 10]])
def test_change_bbox_must_be_finite_four_coordinates(
    tmp_path: Path, bbox: List[Any]
) -> None:
    """Reject malformed or non-finite change bounding boxes."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["changes"] = [
        {
            "region": "evaluation",
            "change": "Added branch",
            "reason": "New gate",
            "bbox": bbox,
        }
    ]
    manifest_path = _write_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    assert "changes[0].bbox" in _issue_paths(issues)


def test_passed_review_requires_relative_existing_artifact(tmp_path: Path) -> None:
    """Require a review artifact for a manifest with a passing review."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["review"] = {"status": "passed", "artifact": "missing.json"}
    manifest_path = _write_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    assert "review.artifact" in _issue_paths(issues)


def test_empty_asset_library_reports_missing_manifests(tmp_path: Path) -> None:
    """Report an empty asset library explicitly."""
    issues = validate_asset_library(tmp_path)

    assert len(issues) == 1
    assert issues[0].path == "root"
    assert issues[0].message == "no manifest.yaml files found"


def _generative_payload(asset_dir: Path) -> Dict[str, Any]:
    """Return a valid generative manifest payload and its artifact names."""
    payload = _complete_payload(asset_dir)
    payload.update(
        {
            "authoring_route": "generative",
            "editability": "raster",
            "source_files": ["prompt.md"],
            "generation": {
                "prompt": "prompt.md",
                "output": "generated.png",
                "references": ["reference.png"],
            },
        }
    )
    return payload


def _write_generative_asset(
    root: Path,
    asset_id: str = "conceptual-lab",
    payload: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write a generative manifest and its provenance artifacts."""
    asset_dir = root / asset_id
    manifest_payload = payload or _generative_payload(asset_dir)
    manifest_path = _write_asset(root, asset_id, manifest_payload)
    for artifact_name in ("prompt.md", "generated.png", "reference.png"):
        (asset_dir / artifact_name).write_text("artifact", encoding="utf-8")
    return manifest_path


def test_native_route_requires_an_svg_source(tmp_path: Path) -> None:
    """Require an SVG source for the native authoring route."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["source_files"] = ["source.json"]
    manifest_path = _write_asset(tmp_path, payload=payload, source_files=["source.json"])

    issues = validate_manifest(manifest_path)

    assert any("SVG" in issue.message for issue in issues if issue.path == "source_files")


def test_data_route_requires_data_json_and_an_svg_source(tmp_path: Path) -> None:
    """Require both reconstructable data and an SVG render source."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["authoring_route"] = "data"
    payload["source_files"] = ["source.json"]
    manifest_path = _write_asset(tmp_path, payload=payload, source_files=["source.json"])

    issues = validate_manifest(manifest_path)

    assert any("data.json" in issue.message for issue in issues)
    assert any("SVG" in issue.message for issue in issues)


def test_valid_generative_route_passes(tmp_path: Path) -> None:
    """Accept a generative manifest with complete provenance artifacts."""
    manifest_path = _write_generative_asset(tmp_path)

    assert validate_manifest(manifest_path) == []


def test_valid_data_route_passes(tmp_path: Path) -> None:
    """Accept a data route with reconstructable data and an SVG renderer."""
    asset_dir = tmp_path / "training-pipeline"
    payload = _complete_payload(asset_dir)
    payload["authoring_route"] = "data"
    payload["source_files"] = ["data.json", "source.svg"]
    manifest_path = _write_asset(tmp_path, payload=payload)

    assert validate_manifest(manifest_path) == []


def test_valid_hybrid_route_passes(tmp_path: Path) -> None:
    """Accept a generative base paired with an editable SVG overlay."""
    asset_dir = tmp_path / "hybrid-lab"
    payload = _generative_payload(asset_dir)
    payload["authoring_route"] = "hybrid"
    payload["editability"] = "hybrid"
    payload["source_files"] = ["overlay.svg"]
    manifest_path = _write_generative_asset(
        tmp_path, asset_id="hybrid-lab", payload=payload
    )
    (manifest_path.parent / "overlay.svg").write_text("artifact", encoding="utf-8")

    assert validate_manifest(manifest_path) == []


def test_new_generative_route_may_have_no_reference_inputs(tmp_path: Path) -> None:
    """Allow a new generative asset to declare an empty reference list."""
    asset_dir = tmp_path / "conceptual-lab"
    payload = _generative_payload(asset_dir)
    payload["generation"] = {
        "prompt": "prompt.md",
        "output": "generated.png",
        "references": [],
    }
    manifest_path = _write_generative_asset(tmp_path, payload=payload)

    assert validate_manifest(manifest_path) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt", "missing.md"),
        ("output", "missing.png"),
        ("output", "generated.svg"),
        ("references", ["../outside.png"]),
    ],
)
def test_generative_contract_validates_prompt_output_and_reference_paths(
    tmp_path: Path, field: str, value: Any
) -> None:
    """Reject missing, invalid, or escaping generative provenance paths."""
    payload = _generative_payload(tmp_path / "conceptual-lab")
    generation = dict(payload["generation"])
    generation[field] = value
    payload["generation"] = generation
    manifest_path = _write_generative_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    assert any(issue.path.startswith("generation") for issue in issues)


def test_hybrid_route_requires_editable_svg_overlay(tmp_path: Path) -> None:
    """Require an SVG overlay source for a hybrid generative visual."""
    payload = _generative_payload(tmp_path / "hybrid-lab")
    payload["authoring_route"] = "hybrid"
    payload["editability"] = "hybrid"
    payload["source_files"] = ["overlay.json"]
    manifest_path = _write_generative_asset(
        tmp_path,
        asset_id="hybrid-lab",
        payload=payload,
    )
    (manifest_path.parent / "overlay.json").write_text("artifact", encoding="utf-8")

    issues = validate_manifest(manifest_path)

    assert any("overlay" in issue.message or "SVG" in issue.message for issue in issues)


@pytest.mark.parametrize("route", ["generative", "hybrid"])
def test_edited_generative_routes_require_generation_references(
    tmp_path: Path, route: str
) -> None:
    """Require generation references when generative provenance is edited."""
    asset_dir = tmp_path / "conceptual-lab"
    payload = _generative_payload(asset_dir)
    payload["authoring_route"] = route
    payload["editability"] = "hybrid" if route == "hybrid" else "raster"
    payload["generation"] = {
        "prompt": "prompt.md",
        "output": "generated.png",
        "references": [],
    }
    if route == "hybrid":
        payload["source_files"] = ["overlay.svg"]
    else:
        payload["source_files"] = []
    payload["based_on_revision"] = "git:abc123"
    manifest_path = _write_generative_asset(tmp_path, payload=payload)
    if route == "hybrid":
        (manifest_path.parent / "overlay.svg").write_text("artifact", encoding="utf-8")

    issues = validate_manifest(manifest_path)

    assert "generation.references" in _issue_paths(issues)


def test_changed_generative_asset_requires_references_without_revision(
    tmp_path: Path,
) -> None:
    """Require references for changes even without a base revision."""
    asset_dir = tmp_path / "conceptual-lab"
    payload = _generative_payload(asset_dir)
    payload["based_on_revision"] = None
    payload["changes"] = [
        {
            "region": "composition",
            "change": "Adjusted composition",
            "reason": "Improve visual balance",
        }
    ]
    payload["generation"] = {
        "prompt": "prompt.md",
        "output": "generated.png",
        "references": [],
    }
    manifest_path = _write_generative_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    assert "generation.references" in _issue_paths(issues)


def test_route_contract_rejects_missing_generation_mapping(tmp_path: Path) -> None:
    """Reject generative routes without a generation mapping."""
    payload = _generative_payload(tmp_path / "conceptual-lab")
    payload["generation"] = None
    manifest_path = _write_generative_asset(tmp_path, payload=payload)

    issues = validate_manifest(manifest_path)

    assert "generation" in _issue_paths(issues)


def test_valid_plan_passes(tmp_path: Path) -> None:
    """Accept the complete diagram plan contract."""
    plan_path = _write_plan(tmp_path / "diagram-plan.yaml", _valid_plan_payload())

    assert validate_diagram_plan(plan_path) == []


def test_plan_issues_are_sorted_by_path(tmp_path: Path) -> None:
    """Sort diagram-plan issues by their field paths."""
    payload = _valid_plan_payload()
    payload["schema_version"] = 2
    payload["deck_id"] = "Weekly Progress"
    payload["visuals"][0]["purpose"] = ""
    payload["visuals"][0]["slide"] = 0
    plan_path = _write_plan(tmp_path / "diagram-plan.yaml", payload)

    issues = validate_diagram_plan(plan_path)

    assert _issue_paths(issues) == [
        "deck_id",
        "schema_version",
        "visuals[0].purpose",
        "visuals[0].slide",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("deck_id", "Weekly Progress"),
        ("visuals", {}),
    ],
)
def test_plan_root_and_deck_contract_is_validated(
    tmp_path: Path, field: str, value: Any
) -> None:
    """Report malformed plan schema, deck ID, and visual collection values."""
    payload = _valid_plan_payload()
    payload[field] = value
    plan_path = _write_plan(tmp_path / "diagram-plan.yaml", payload)

    issues = validate_diagram_plan(plan_path)

    assert field in _issue_paths(issues)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("diagram_id", "Training Pipeline"),
        ("slide", 0),
        ("purpose", ""),
        ("regions", ["ingestion", "ingestion"]),
        ("route", "unknown"),
        ("editability", "unknown"),
    ],
)
def test_plan_visual_fields_are_validated(tmp_path: Path, field: str, value: Any) -> None:
    """Report invalid visual IDs, slide, purpose, regions, and enums."""
    payload = _valid_plan_payload()
    payload["visuals"][0][field] = value
    plan_path = _write_plan(tmp_path / "diagram-plan.yaml", payload)

    issues = validate_diagram_plan(plan_path)

    assert any(issue.path.startswith("visuals[0]." + field) for issue in issues)


@pytest.mark.parametrize("action", ["reuse", "modify", "derive"])
def test_plan_reuse_actions_require_asset_id(tmp_path: Path, action: str) -> None:
    """Require an asset ID for every action that uses an existing asset."""
    payload = _valid_plan_payload()
    payload["visuals"][0]["reuse"] = {"action": action}
    plan_path = _write_plan(tmp_path / "diagram-plan.yaml", payload)

    issues = validate_diagram_plan(plan_path)

    assert "visuals[0].reuse.asset_id" in _issue_paths(issues)


def test_plan_create_forbids_asset_id(tmp_path: Path) -> None:
    """Reject an asset ID attached to a create action."""
    payload = _valid_plan_payload()
    payload["visuals"][0]["reuse"] = {"action": "create", "asset_id": "other"}
    plan_path = _write_plan(tmp_path / "diagram-plan.yaml", payload)

    issues = validate_diagram_plan(plan_path)

    assert "visuals[0].reuse.asset_id" in _issue_paths(issues)


@pytest.mark.parametrize("action", ["reuse", "modify"])
def test_plan_reuse_and_modify_require_matching_asset_identity(
    tmp_path: Path, action: str
) -> None:
    """Require reuse and modify actions to preserve diagram identity."""
    payload = _valid_plan_payload()
    payload["visuals"][0]["reuse"] = {"action": action, "asset_id": "other-diagram"}
    plan_path = _write_plan(tmp_path / "diagram-plan.yaml", payload)

    issues = validate_diagram_plan(plan_path)

    assert any("must equal diagram_id" in issue.message for issue in issues)


def test_plan_derive_may_use_a_different_asset_identity(tmp_path: Path) -> None:
    """Allow derive to point at an earlier asset while introducing a new ID."""
    payload = _valid_plan_payload()
    payload["visuals"][0]["diagram_id"] = "publishing-gate"
    payload["visuals"][0]["reuse"] = {
        "action": "derive",
        "asset_id": "training-pipeline",
    }
    plan_path = _write_plan(tmp_path / "diagram-plan.yaml", payload)

    assert validate_diagram_plan(plan_path) == []


def test_plan_reuse_and_modify_may_use_matching_identity(tmp_path: Path) -> None:
    """Allow reuse and modify when the asset identity is retained."""
    for action in ("reuse", "modify"):
        payload = _valid_plan_payload()
        payload["visuals"][0]["reuse"]["action"] = action
        plan_path = _write_plan(tmp_path / (action + ".yaml"), payload)

        assert validate_diagram_plan(plan_path) == []


def test_plan_create_may_omit_asset_identity(tmp_path: Path) -> None:
    """Allow a create action without an existing asset ID."""
    payload = _valid_plan_payload()
    payload["visuals"][0]["reuse"] = {"action": "create"}
    plan_path = _write_plan(tmp_path / "create.yaml", payload)

    assert validate_diagram_plan(plan_path) == []


def test_plan_rejects_unknown_reuse_action(tmp_path: Path) -> None:
    """Reject reuse actions outside the four supported lifecycle actions."""
    payload = _valid_plan_payload()
    payload["visuals"][0]["reuse"] = {"action": "replace"}
    plan_path = _write_plan(tmp_path / "invalid-action.yaml", payload)

    issues = validate_diagram_plan(plan_path)

    assert "visuals[0].reuse.action" in _issue_paths(issues)


@pytest.mark.parametrize("regions", [[], ["ingestion", ""]])
def test_plan_regions_must_be_non_empty(
    tmp_path: Path, regions: List[str]
) -> None:
    """Reject an empty region collection or an empty region name."""
    payload = _valid_plan_payload()
    payload["visuals"][0]["regions"] = regions
    plan_path = _write_plan(tmp_path / "regions.yaml", payload)

    issues = validate_diagram_plan(plan_path)

    assert any(issue.path.startswith("visuals[0].regions") for issue in issues)


def test_cli_manifest_success_identifies_manifest_validation(tmp_path: Path) -> None:
    """Print a successful manifest validation result from the CLI."""
    manifest_path = _write_asset(tmp_path)

    result = _run_cli("--manifest", str(manifest_path))

    assert result.returncode == 0
    assert "manifest validation passed" in result.stdout


def test_cli_root_success_identifies_library_validation(tmp_path: Path) -> None:
    """Print a successful asset-library validation result from the CLI."""
    _write_asset(tmp_path)

    result = _run_cli("--root", str(tmp_path))

    assert result.returncode == 0
    assert "library validation passed" in result.stdout


def test_cli_plan_success_identifies_plan_validation(tmp_path: Path) -> None:
    """Print a successful diagram-plan validation result from the CLI."""
    plan_path = _write_plan(tmp_path / "diagram-plan.yaml", _valid_plan_payload())

    result = _run_cli("--plan", str(plan_path))

    assert result.returncode == 0
    assert "plan validation passed" in result.stdout


def test_cli_invalid_output_has_path_field_message_and_exit_one(tmp_path: Path) -> None:
    """Format invalid CLI output as the required path-field diagnostic."""
    payload = _complete_payload(tmp_path / "training-pipeline")
    payload["purpose"] = ""
    manifest_path = _write_asset(tmp_path, payload=payload)

    result = _run_cli("--manifest", str(manifest_path))

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR " + str(manifest_path) + ":purpose:")


def test_cli_requires_exactly_one_validation_target(tmp_path: Path) -> None:
    """Reject missing and multiple mutually exclusive CLI targets."""
    manifest_path = _write_asset(tmp_path)

    missing = _run_cli()
    multiple = _run_cli("--manifest", str(manifest_path), "--root", str(tmp_path))

    assert missing.returncode != 0
    assert multiple.returncode != 0
