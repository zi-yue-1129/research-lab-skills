#!/usr/bin/env python3
"""Validate report-slides diagram manifests, libraries, and plans."""

import argparse
import math
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import yaml


class DiagramType(str, Enum):
    """Supported semantic diagram types."""

    ARCHITECTURE = "architecture"
    FLOWCHART = "flowchart"
    TIMELINE = "timeline"
    STATISTICAL = "statistical"
    CONCEPTUAL = "conceptual"
    HYBRID = "hybrid"
    STATUS = "status"


class AuthoringRoute(str, Enum):
    """Supported visual authoring routes."""

    NATIVE = "native"
    DATA = "data"
    GENERATIVE = "generative"
    HYBRID = "hybrid"


class Editability(str, Enum):
    """Supported PowerPoint editability levels."""

    NATIVE = "native"
    HYBRID = "hybrid"
    RASTER = "raster"


class ReviewStatus(str, Enum):
    """Supported visual review statuses."""

    DRAFT = "draft"
    FAILED = "failed"
    PASSED = "passed"


class ReuseAction(str, Enum):
    """Supported diagram-plan asset actions."""

    CREATE = "create"
    REUSE = "reuse"
    MODIFY = "modify"
    DERIVE = "derive"


@dataclass(frozen=True)
class ValidationIssue:
    """Describe one deterministic validation failure.

    Attributes:
        manifest: Manifest or plan file associated with the issue.
        path: Dot-and-index field path within the YAML document.
        message: Human-readable validation detail.
    """

    manifest: Path
    path: str
    message: str


_KEBAB_CASE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIAGRAM_TYPE_VALUES = {member.value for member in DiagramType}
_AUTHORING_ROUTE_VALUES = {member.value for member in AuthoringRoute}
_EDITABILITY_VALUES = {member.value for member in Editability}
_REVIEW_STATUS_VALUES = {member.value for member in ReviewStatus}
_REUSE_ACTION_VALUES = {member.value for member in ReuseAction}


def validate_manifest(manifest_path: Path) -> List[ValidationIssue]:
    """Validate one diagram asset manifest and its declared artifacts.

    Args:
        manifest_path: Path to an asset ``manifest.yaml`` file.

    Returns:
        All validation issues in deterministic field order. An empty list
        indicates that the manifest and its referenced files are valid.
    """
    path = Path(manifest_path)
    document, load_issues = _load_mapping_document(path, "manifest")
    if load_issues:
        return load_issues
    if document is None:
        return [_issue(path, "root", "manifest root must be a mapping")]

    issues: List[ValidationIssue] = []
    _validate_schema_version(document, path, issues)
    diagram_id = _validate_diagram_id(document, path, issues)
    _validate_required_text(document, "purpose", path, issues)
    _validate_enum_field(document, "diagram_type", _DIAGRAM_TYPE_VALUES, path, issues)
    authoring_route = _validate_enum_field(
        document, "authoring_route", _AUTHORING_ROUTE_VALUES, path, issues
    )
    _validate_enum_field(document, "editability", _EDITABILITY_VALUES, path, issues)
    source_paths = _validate_source_files(document, path, issues)
    _validate_used_in(document, path, issues)
    _validate_nullable_text(document, "derived_from", path, issues)
    based_on_revision = _validate_nullable_text(
        document, "based_on_revision", path, issues
    )
    changes = _validate_changes(document, path, issues)
    _validate_generation(
        document,
        path,
        authoring_route,
        based_on_revision,
        changes,
        issues,
    )
    _validate_review(document, path, issues)
    _validate_route_provenance(
        authoring_route,
        source_paths,
        path,
        issues,
    )

    if diagram_id is not None and diagram_id != path.parent.name:
        issues.append(
            _issue(
                path,
                "diagram_id",
                "diagram_id must match the asset directory name",
            )
        )
    return sorted(issues, key=lambda issue: issue.path)


def validate_asset_library(root: Path) -> List[ValidationIssue]:
    """Validate every diagram manifest below an asset-library root.

    Args:
        root: Directory containing per-diagram directories and manifests.

    Returns:
        All manifest issues in lexicographic manifest-path order. An empty
        library is reported as one issue rather than being treated as valid.
    """
    root_path = Path(root)
    manifest_paths = sorted(
        (candidate for candidate in root_path.rglob("manifest.yaml") if candidate.is_file()),
        key=lambda candidate: candidate.as_posix(),
    )
    if not manifest_paths:
        return [_issue(root_path, "root", "no manifest.yaml files found")]

    issues: List[ValidationIssue] = []
    for manifest_path in manifest_paths:
        issues.extend(validate_manifest(manifest_path))
    return issues


def validate_diagram_plan(plan_path: Path) -> List[ValidationIssue]:
    """Validate a deck-level diagram plan and its asset identity rules.

    Args:
        plan_path: Path to a ``diagram-plan.yaml`` file.

    Returns:
        All validation issues in deterministic field order.
    """
    path = Path(plan_path)
    document, load_issues = _load_mapping_document(path, "plan")
    if load_issues:
        return load_issues
    if document is None:
        return [_issue(path, "root", "plan root must be a mapping")]

    issues: List[ValidationIssue] = []
    _validate_schema_version(document, path, issues)
    _validate_kebab_id_field(document, "deck_id", path, issues)

    visuals = document.get("visuals")
    if not isinstance(visuals, Sequence) or isinstance(visuals, (str, bytes)):
        issues.append(_issue(path, "visuals", "visuals must be a list"))
        return sorted(issues, key=lambda issue: issue.path)

    for index, visual in enumerate(visuals):
        visual_path = "visuals[{}]".format(index)
        if not isinstance(visual, Mapping):
            issues.append(_issue(path, visual_path, "visual must be a mapping"))
            continue
        _validate_plan_visual(visual, visual_path, path, issues)
    return sorted(issues, key=lambda issue: issue.path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run manifest, library, or plan validation from the command line.

    Args:
        argv: Optional command-line arguments excluding the executable name.

    Returns:
        Zero when the selected target is valid, otherwise one. Argparse
        returns its normal non-zero status for missing or conflicting targets.
    """
    parser = argparse.ArgumentParser(
        description="Validate report-slides diagram manifests and plans."
    )
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--manifest", type=Path, help="Manifest YAML path.")
    targets.add_argument("--root", type=Path, help="Diagram asset-library root.")
    targets.add_argument("--plan", type=Path, help="Diagram plan YAML path.")
    arguments = parser.parse_args(argv)

    if arguments.manifest is not None:
        label = "manifest"
        target = arguments.manifest
        issues = validate_manifest(target)
    elif arguments.root is not None:
        label = "library"
        target = arguments.root
        issues = validate_asset_library(target)
    else:
        label = "plan"
        target = arguments.plan
        issues = validate_diagram_plan(target)

    if issues:
        for issue in issues:
            print(
                "ERROR {}:{}: {}".format(issue.manifest, issue.path, issue.message),
                file=sys.stderr,
            )
        return 1

    print("OK: {} validation passed: {}".format(label, target))
    return 0


def _load_mapping_document(
    path: Path, document_label: str
) -> Tuple[Optional[Mapping[str, Any]], List[ValidationIssue]]:
    """Load one YAML file and require a mapping root.

    Args:
        path: YAML file to read.
        document_label: Human-readable document type for root diagnostics.

    Returns:
        A typed mapping and no issues, or no mapping and one or more issues.
    """
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        return None, [_issue(path, "file", "cannot read file: {}".format(error))]
    except yaml.YAMLError as error:
        return None, [_issue(path, "yaml", "invalid YAML: {}".format(error))]

    if not isinstance(document, Mapping):
        return None, [
            _issue(path, "root", "{} root must be a mapping".format(document_label))
        ]
    return document, []


def _issue(path: Path, field_path: str, message: str) -> ValidationIssue:
    """Construct one immutable validation issue."""
    return ValidationIssue(path, field_path, message)


def _validate_schema_version(
    document: Mapping[str, Any], path: Path, issues: List[ValidationIssue]
) -> None:
    """Require the supported integer schema version."""
    value = document.get("schema_version")
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        issues.append(_issue(path, "schema_version", "schema_version must be 1"))


def _validate_required_text(
    document: Mapping[str, Any],
    field_name: str,
    path: Path,
    issues: List[ValidationIssue],
) -> Optional[str]:
    """Require one non-empty string field and return its value."""
    value = document.get(field_name)
    if not isinstance(value, str) or not value.strip():
        issues.append(
            _issue(path, field_name, "{} must be a non-empty string".format(field_name))
        )
        return None
    return value


def _validate_nullable_text(
    document: Mapping[str, Any],
    field_name: str,
    path: Path,
    issues: List[ValidationIssue],
) -> Optional[str]:
    """Require a string-or-null provenance field and return strings."""
    if field_name not in document:
        issues.append(_issue(path, field_name, "{} is required".format(field_name)))
        return None
    value = document[field_name]
    if value is not None and not isinstance(value, str):
        issues.append(
            _issue(path, field_name, "{} must be a string or null".format(field_name))
        )
        return None
    return value


def _validate_kebab_id_field(
    document: Mapping[str, Any],
    field_name: str,
    path: Path,
    issues: List[ValidationIssue],
) -> Optional[str]:
    """Require a non-empty kebab-case ID field and return its value."""
    value = document.get(field_name)
    if not isinstance(value, str) or not _KEBAB_CASE_ID.fullmatch(value):
        issues.append(
            _issue(
                path,
                field_name,
                "{} must be a non-empty kebab-case ID".format(field_name),
            )
        )
        return None
    return value


def _validate_diagram_id(
    document: Mapping[str, Any], path: Path, issues: List[ValidationIssue]
) -> Optional[str]:
    """Validate a manifest diagram ID before checking directory identity."""
    return _validate_kebab_id_field(document, "diagram_id", path, issues)


def _validate_enum_field(
    document: Mapping[str, Any],
    field_name: str,
    allowed_values: Set[str],
    path: Path,
    issues: List[ValidationIssue],
) -> Optional[str]:
    """Require one string value from an enumerated set."""
    value = document.get(field_name)
    if not isinstance(value, str) or value not in allowed_values:
        issues.append(
            _issue(
                path,
                field_name,
                "{} must be one of: {}".format(
                    field_name, ", ".join(sorted(allowed_values))
                ),
            )
        )
        return None
    return value


def _validate_source_files(
    document: Mapping[str, Any], path: Path, issues: List[ValidationIssue]
) -> List[Tuple[str, Path]]:
    """Validate source file paths and return safe declared paths."""
    value = document.get("source_files")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        issues.append(_issue(path, "source_files", "source_files must be a list"))
        return []
    if not value:
        issues.append(_issue(path, "source_files", "source_files must not be empty"))
        return []

    valid_paths: List[Tuple[str, Path]] = []
    for index, source_file in enumerate(value):
        field_path = "source_files[{}]".format(index)
        if not isinstance(source_file, str) or not source_file.strip():
            issues.append(
                _issue(path, field_path, "source file must be a non-empty string")
            )
            continue
        resolved, path_error = _resolve_relative_path(path.parent, source_file)
        if path_error is not None or resolved is None:
            issues.append(_issue(path, field_path, path_error or "invalid source path"))
            continue
        if not resolved.is_file():
            issues.append(_issue(path, field_path, "source file does not exist"))
        valid_paths.append((source_file, resolved))
    return valid_paths


def _validate_used_in(
    document: Mapping[str, Any], path: Path, issues: List[ValidationIssue]
) -> None:
    """Validate deck references and positive slide numbers."""
    value = document.get("used_in")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        issues.append(_issue(path, "used_in", "used_in must be a list"))
        return

    for index, usage in enumerate(value):
        usage_path = "used_in[{}]".format(index)
        if not isinstance(usage, Mapping):
            issues.append(_issue(path, usage_path, "used_in entry must be a mapping"))
            continue
        deck = usage.get("deck")
        if not isinstance(deck, str) or not deck.strip():
            issues.append(
                _issue(path, usage_path + ".deck", "deck must be a non-empty string")
            )
        slide = usage.get("slide")
        if isinstance(slide, bool) or not isinstance(slide, int) or slide <= 0:
            issues.append(
                _issue(path, usage_path + ".slide", "slide must be a positive integer")
            )


def _validate_changes(
    document: Mapping[str, Any], path: Path, issues: List[ValidationIssue]
) -> List[Any]:
    """Validate change descriptions and optional slide-coordinate boxes."""
    value = document.get("changes")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        issues.append(_issue(path, "changes", "changes must be a list"))
        return []

    entries: List[Any] = []
    for index, change in enumerate(value):
        change_path = "changes[{}]".format(index)
        if not isinstance(change, Mapping):
            issues.append(_issue(path, change_path, "change must be a mapping"))
            entries.append(change)
            continue
        entries.append(change)
        for field_name in ("region", "change", "reason"):
            field_value = change.get(field_name)
            if not isinstance(field_value, str) or not field_value.strip():
                issues.append(
                    _issue(
                        path,
                        change_path + "." + field_name,
                        "{} must be a non-empty string".format(field_name),
                    )
                )
        if "bbox" in change and not _valid_bbox(change["bbox"]):
            issues.append(
                _issue(
                    path,
                    change_path + ".bbox",
                    "bbox must be finite and satisfy 0 <= x1 < x2 <= 1200 and 0 <= y1 < y2 <= 675",
                )
            )
    return entries


def _valid_bbox(value: Any) -> bool:
    """Return whether a value is a finite, in-bounds four-number box."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return False
    if len(value) != 4:
        return False
    if any(not _finite_number(coordinate) for coordinate in value):
        return False
    x1, y1, x2, y2 = value
    return 0 <= x1 < x2 <= 1200 and 0 <= y1 < y2 <= 675


def _finite_number(value: Any) -> bool:
    """Return whether a value is a finite non-boolean number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _validate_generation(
    document: Mapping[str, Any],
    path: Path,
    authoring_route: Optional[str],
    based_on_revision: Optional[str],
    changes: Sequence[Any],
    issues: List[ValidationIssue],
) -> None:
    """Validate generative provenance and its declared reference paths."""
    value = document.get("generation")
    if value is None:
        if authoring_route in (AuthoringRoute.GENERATIVE.value, AuthoringRoute.HYBRID.value):
            issues.append(
                _issue(path, "generation", "generation is required for this route")
            )
        return
    if not isinstance(value, Mapping):
        issues.append(_issue(path, "generation", "generation must be a mapping or null"))
        return

    _validate_generation_file(value, "prompt", path, path.parent, issues)
    output_path = _validate_generation_file(value, "output", path, path.parent, issues)
    if output_path is not None and output_path.suffix.lower() not in (".png", ".jpg"):
        issues.append(
            _issue(path, "generation.output", "generation output must be a .png or .jpg file")
        )

    references = value.get("references")
    declared_references: List[str] = []
    if not isinstance(references, Sequence) or isinstance(references, (str, bytes)):
        issues.append(_issue(path, "generation.references", "references must be a list"))
    else:
        for index, reference in enumerate(references):
            field_path = "generation.references[{}]".format(index)
            if not isinstance(reference, str) or not reference.strip():
                issues.append(
                    _issue(path, field_path, "reference path must be a non-empty string")
                )
                continue
            _, path_error = _resolve_relative_path(path.parent, reference)
            if path_error is not None:
                issues.append(_issue(path, field_path, path_error))
                continue
            declared_references.append(reference)

    if (
        authoring_route in (AuthoringRoute.GENERATIVE.value, AuthoringRoute.HYBRID.value)
        and (based_on_revision is not None or len(changes) > 0)
        and not declared_references
    ):
        issues.append(
            _issue(
                path,
                "generation.references",
                "edited generative assets must declare at least one generation reference",
            )
        )
def _validate_generation_file(
    generation: Mapping[str, Any],
    field_name: str,
    manifest_path: Path,
    asset_directory: Path,
    issues: List[ValidationIssue],
) -> Optional[Path]:
    """Validate one required existing relative generation artifact."""
    value = generation.get(field_name)
    field_path = "generation." + field_name
    if not isinstance(value, str) or not value.strip():
        issues.append(
            _issue(manifest_path, field_path, "{} must be a non-empty path".format(field_name))
        )
        return None
    resolved, path_error = _resolve_relative_path(asset_directory, value)
    if path_error is not None or resolved is None:
        issues.append(_issue(manifest_path, field_path, path_error or "invalid path"))
        return None
    if not resolved.is_file():
        issues.append(_issue(manifest_path, field_path, "generation file does not exist"))
    return resolved


def _validate_review(
    document: Mapping[str, Any], path: Path, issues: List[ValidationIssue]
) -> None:
    """Validate review status and the artifact required for passed reviews."""
    value = document.get("review")
    if not isinstance(value, Mapping):
        issues.append(_issue(path, "review", "review must be a mapping"))
        return
    status = value.get("status")
    if not isinstance(status, str) or status not in _REVIEW_STATUS_VALUES:
        issues.append(
            _issue(
                path,
                "review.status",
                "review.status must be one of: {}".format(
                    ", ".join(sorted(_REVIEW_STATUS_VALUES))
                ),
            )
        )
        return

    artifact = value.get("artifact")
    if artifact is None and status != ReviewStatus.PASSED.value:
        return
    if not isinstance(artifact, str) or not artifact.strip():
        issues.append(
            _issue(path, "review.artifact", "review artifact must be a relative path")
        )
        return
    resolved, path_error = _resolve_relative_path(path.parent, artifact)
    if path_error is not None or resolved is None:
        issues.append(_issue(path, "review.artifact", path_error or "invalid review path"))
        return
    if status == ReviewStatus.PASSED.value and not resolved.is_file():
        issues.append(_issue(path, "review.artifact", "review artifact does not exist"))


def _validate_route_provenance(
    authoring_route: Optional[str],
    source_paths: Sequence[Tuple[str, Path]],
    path: Path,
    issues: List[ValidationIssue],
) -> None:
    """Enforce the source and overlay contract for each authoring route."""
    source_names = [source_name.replace("\\", "/").lower() for source_name, _ in source_paths]
    has_svg = any(source_name.endswith(".svg") for source_name in source_names)

    if authoring_route == AuthoringRoute.NATIVE.value and not has_svg:
        issues.append(_issue(path, "source_files", "native route requires an SVG source"))
    elif authoring_route == AuthoringRoute.DATA.value:
        if not any(
            PurePosixPath(source_name).name == "data.json" for source_name in source_names
        ):
            issues.append(_issue(path, "source_files", "data route requires data.json"))
        if not has_svg:
            issues.append(_issue(path, "source_files", "data route requires an SVG source"))
    elif authoring_route == AuthoringRoute.HYBRID.value and not has_svg:
        issues.append(_issue(path, "source_files", "hybrid route requires an editable SVG overlay"))

def _validate_plan_visual(
    visual: Mapping[str, Any],
    visual_path: str,
    path: Path,
    issues: List[ValidationIssue],
) -> None:
    """Validate one visual entry in a diagram plan."""
    diagram_id_path = visual_path + ".diagram_id"
    diagram_id = visual.get("diagram_id")
    if not isinstance(diagram_id, str) or not _KEBAB_CASE_ID.fullmatch(diagram_id):
        issues.append(
            _issue(path, diagram_id_path, "diagram_id must be a non-empty kebab-case ID")
        )

    slide = visual.get("slide")
    if isinstance(slide, bool) or not isinstance(slide, int) or slide <= 0:
        issues.append(_issue(path, visual_path + ".slide", "slide must be a positive integer"))

    purpose = visual.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip():
        issues.append(
            _issue(path, visual_path + ".purpose", "purpose must be a non-empty string")
        )

    _validate_regions(visual.get("regions"), visual_path, path, issues)
    _validate_enum_value(
        visual.get("route"), visual_path + ".route", _AUTHORING_ROUTE_VALUES, path, issues
    )
    _validate_enum_value(
        visual.get("editability"),
        visual_path + ".editability",
        _EDITABILITY_VALUES,
        path,
        issues,
    )
    _validate_reuse(visual.get("reuse"), visual_path, diagram_id, path, issues)


def _validate_regions(
    value: Any, visual_path: str, path: Path, issues: List[ValidationIssue]
) -> None:
    """Require non-empty unique named regions for one planned visual."""
    field_path = visual_path + ".regions"
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        issues.append(_issue(path, field_path, "regions must be a list"))
        return
    if not value:
        issues.append(_issue(path, field_path, "regions must not be empty"))
        return

    seen: Dict[str, bool] = {}
    for index, region in enumerate(value):
        region_path = "{}[{}]".format(field_path, index)
        if not isinstance(region, str) or not region.strip():
            issues.append(_issue(path, region_path, "region must be a non-empty string"))
            continue
        if region in seen:
            issues.append(_issue(path, region_path, "regions must be unique"))
        seen[region] = True


def _validate_enum_value(
    value: Any,
    field_path: str,
    allowed_values: Set[str],
    path: Path,
    issues: List[ValidationIssue],
) -> Optional[str]:
    """Validate one plan enum value and return it when valid."""
    if not isinstance(value, str) or value not in allowed_values:
        issues.append(
            _issue(
                path,
                field_path,
                "value must be one of: {}".format(", ".join(sorted(allowed_values))),
            )
        )
        return None
    return value


def _validate_reuse(
    value: Any,
    visual_path: str,
    diagram_id: Any,
    path: Path,
    issues: List[ValidationIssue],
) -> None:
    """Validate plan reuse action and asset identity constraints."""
    reuse_path = visual_path + ".reuse"
    if not isinstance(value, Mapping):
        issues.append(_issue(path, reuse_path, "reuse must be a mapping"))
        return
    action = value.get("action")
    if not isinstance(action, str) or action not in _REUSE_ACTION_VALUES:
        issues.append(
            _issue(
                path,
                reuse_path + ".action",
                "action must be one of: {}".format(
                    ", ".join(sorted(_REUSE_ACTION_VALUES))
                ),
            )
        )
        return

    has_asset_id = "asset_id" in value
    asset_id = value.get("asset_id")
    asset_id_valid = isinstance(asset_id, str) and bool(_KEBAB_CASE_ID.fullmatch(asset_id))
    if action == ReuseAction.CREATE.value:
        if has_asset_id:
            issues.append(
                _issue(path, reuse_path + ".asset_id", "create action must not set asset_id")
            )
        return

    if not has_asset_id:
        issues.append(
            _issue(path, reuse_path + ".asset_id", "asset_id is required for this action")
        )
        return
    if not asset_id_valid:
        issues.append(
            _issue(path, reuse_path + ".asset_id", "asset_id must be a kebab-case ID")
        )
        return
    if action in (ReuseAction.REUSE.value, ReuseAction.MODIFY.value) and asset_id != diagram_id:
        issues.append(
            _issue(
                path,
                reuse_path + ".asset_id",
                "asset_id must equal diagram_id for reuse and modify actions",
            )
        )


def _resolve_relative_path(
    base_directory: Path, value: str
) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a declared path while preventing escape from its base."""
    normalized = value.replace("\\", "/")
    posix_value = PurePosixPath(normalized)
    windows_value = PureWindowsPath(value)
    if posix_value.is_absolute() or windows_value.is_absolute() or bool(windows_value.drive):
        return None, "path must be relative"
    try:
        candidate = base_directory / Path(normalized)
        resolved = candidate.resolve()
        resolved.relative_to(base_directory.resolve())
    except (OSError, ValueError):
        return None, "path must stay inside the asset directory"
    return resolved, None


if __name__ == "__main__":
    sys.exit(main())
