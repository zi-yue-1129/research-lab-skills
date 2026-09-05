"""Deterministically validate report-slides PPTX visual review records.

This module checks the *shape* of a review record: required fields, the
independence of the svg_preview / pptx_structure / pptx_render gates, path
safety, and the derived overall completion decision. It never claims that
model_vision actually inspected an image; it verifies that the record names
the exact paths the runtime says were inspected, and that those paths exist
and are readable. Direct model_vision inspection itself happens outside this
module, in the report-slides workflow.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml
from PIL import Image, UnidentifiedImageError

VALID_STATUSES: Tuple[str, ...] = (
    "passed",
    "failed",
    "blocked",
    "not_applicable",
)

_REQUIRED_GATES: Tuple[str, ...] = ("svg_preview", "pptx_structure", "pptx_render")
_VISUAL_GATES: Tuple[str, ...] = ("svg_preview", "pptx_render")

_ALLOWED_FINDING_KINDS: Tuple[str, ...] = (
    "clipping",
    "overlap",
    "text-reflow",
    "connector-drift",
    "crop",
    "unreadably-small-text",
    "missing-image",
    "z-order",
    "alignment",
    "other",
    # Plan-level finding kinds (Content Reviewer, Stage 4) -- reusing this
    # same findings[].kind vocabulary rather than a parallel one.
    "unsupported-claim",
    "duplicated-content",
    "missing-limitation",
    "excessive-background",
    "unnecessary-visual",
    "weak-continuity",
    # Art-direction finding kinds (art_direction_reviewer_agent, Stage 12).
    "visual-cliche",
    "decorative-noise",
    "style-drift",
    "synthetic-detail",
    "meaningless-interface",
    "stock-ai-composition",
    "weak-hierarchy",
    "undifferentiated-repetition",
)
_ALLOWED_FINDING_SOURCES: Tuple[str, ...] = (
    "svg-preview",
    "pptx-structure",
    "pptx-render",
    # Plan-level review source (Content Reviewer, Stage 4) -- findings from
    # this source describe the Deck Plan itself, not a rendered artifact, so
    # `scope`/`artifact_path` are optional rather than required for them.
    "plan_review",
)
_PLAN_LEVEL_FINDING_SOURCE = "plan_review"
_ALLOWED_FINDING_DISPOSITIONS: Tuple[str, ...] = ("open", "fixed", "rechecked")


@dataclass(frozen=True)
class ValidationIssue:
    """One deterministic review-record validation issue.

    Attributes:
        path: Dotted field path the issue refers to, e.g.
            ``statuses.pptx_render.model_vision.inspected_paths``.
        message: Human-readable description of the defect.
    """

    path: str
    message: str


@dataclass(frozen=True)
class OverallResult:
    """Derived completion result for one review record.

    Attributes:
        status: One of ``passed``, ``failed``, or ``blocked``.
        completion_allowed: Whether the record permits a completion claim.
        authority: ``pptx-render`` for a PPTX request, ``source-pixel``
            otherwise.
    """

    status: str
    completion_allowed: bool
    authority: str


def _is_relative_and_safe(path_text: str) -> bool:
    """Return whether ``path_text`` is a safe relative path.

    A safe path is not absolute and does not escape its root through a
    ``..`` component.
    """
    if not path_text or PurePosixPath(path_text).is_absolute() or path_text.startswith("/"):
        return False
    return ".." not in PurePosixPath(path_text).parts


def _check_artifact_path(
    field_path: str,
    path_text: Any,
    artifact_root: Optional[Path],
) -> List[ValidationIssue]:
    """Validate one relative artifact path and its readability.

    Rejects absolute paths and path traversal. When ``artifact_root`` is
    given, also requires the path to exist and, for a ``.png`` suffix, to be
    a readable image verified with Pillow.
    """
    if not isinstance(path_text, str):
        return [ValidationIssue(field_path, "path must be a string")]
    if not _is_relative_and_safe(path_text):
        return [
            ValidationIssue(
                field_path,
                f"path {path_text!r} must be relative and must not traverse outside its root",
            )
        ]
    if artifact_root is None:
        return []
    resolved = artifact_root / path_text
    if not resolved.is_file():
        return [ValidationIssue(field_path, f"artifact not found: {path_text}")]
    if resolved.suffix.lower() == ".png":
        try:
            with Image.open(resolved) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as error:
            return [ValidationIssue(field_path, f"unreadable PNG {path_text}: {error}")]
    return []


def _check_artifact_paths(
    field_path: str,
    paths: Any,
    artifact_root: Optional[Path],
) -> List[ValidationIssue]:
    """Validate every path in a list field."""
    if not isinstance(paths, list):
        return [ValidationIssue(field_path, "must be a list of relative paths")]
    issues: List[ValidationIssue] = []
    for index, path_text in enumerate(paths):
        issues.extend(_check_artifact_path(f"{field_path}[{index}]", path_text, artifact_root))
    return issues


def _validate_finding_entry(
    finding_path: str,
    finding: Any,
    artifact_root: Optional[Path],
) -> List[ValidationIssue]:
    """Validate one finding entry, shared by gate-level and plan-level review.

    Args:
        finding_path: Dotted path to this finding, for error messages.
        finding: The parsed finding mapping.
        artifact_root: Artifact root for `artifact_path` resolution, or
            ``None`` when the caller has no artifact root (plan-level
            review results, which have no rendered artifact).

    Returns:
        A list of validation issues; empty if the finding is valid.
    """
    issues: List[ValidationIssue] = []
    if not isinstance(finding, Mapping):
        return [ValidationIssue(finding_path, "must be a mapping")]
    kind = finding.get("kind")
    if kind not in _ALLOWED_FINDING_KINDS:
        issues.append(ValidationIssue(f"{finding_path}.kind", f"unknown finding kind: {kind!r}"))
    source = finding.get("source")
    if source not in _ALLOWED_FINDING_SOURCES:
        issues.append(
            ValidationIssue(f"{finding_path}.source", f"unknown finding source: {source!r}")
        )
    is_plan_level = source == _PLAN_LEVEL_FINDING_SOURCE
    if not is_plan_level:
        if not isinstance(finding.get("scope"), Mapping):
            issues.append(ValidationIssue(f"{finding_path}.scope", "must be a mapping"))
        artifact_path = finding.get("artifact_path")
        issues.extend(
            _check_artifact_path(f"{finding_path}.artifact_path", artifact_path, artifact_root)
        )
    else:
        if "scope" in finding and not isinstance(finding["scope"], Mapping):
            issues.append(ValidationIssue(f"{finding_path}.scope", "must be a mapping if present"))
        if "artifact_path" in finding and finding["artifact_path"] is not None:
            issues.extend(
                _check_artifact_path(
                    f"{finding_path}.artifact_path", finding["artifact_path"], artifact_root
                )
            )
    description = finding.get("description")
    if not isinstance(description, str) or not description.strip():
        issues.append(ValidationIssue(f"{finding_path}.description", "must be a non-empty string"))
    disposition = finding.get("disposition")
    if disposition not in _ALLOWED_FINDING_DISPOSITIONS:
        issues.append(
            ValidationIssue(f"{finding_path}.disposition", f"unknown disposition: {disposition!r}")
        )
    return issues


def _validate_findings(
    gate_path: str,
    status: Mapping[str, Any],
    artifact_root: Optional[Path],
) -> List[ValidationIssue]:
    """Validate the findings list for one status object."""
    issues: List[ValidationIssue] = []
    findings_path = f"{gate_path}.findings"
    findings = status.get("findings")
    if not isinstance(findings, list):
        return [ValidationIssue(findings_path, "must be a list (use [] for a clean pass)")]

    has_open_finding = False
    for index, finding in enumerate(findings):
        finding_path = f"{findings_path}[{index}]"
        issues.extend(_validate_finding_entry(finding_path, finding, artifact_root))
        if isinstance(finding, Mapping) and finding.get("disposition") == "open":
            has_open_finding = True

    status_value = status.get("status")
    if status_value == "passed" and has_open_finding:
        issues.append(
            ValidationIssue(findings_path, "a passing status must not retain an open finding")
        )
    if status_value == "failed" and not findings:
        issues.append(
            ValidationIssue(findings_path, "a failed status requires at least one evidence-backed finding")
        )
    return issues


def _validate_status_object(
    gate: str,
    status: Any,
    artifact_root: Optional[Path],
) -> List[ValidationIssue]:
    """Validate the fields common to every status object."""
    gate_path = f"statuses.{gate}"
    if not isinstance(status, Mapping):
        return [ValidationIssue(gate_path, "must be a mapping")]

    issues: List[ValidationIssue] = []
    status_value = status.get("status")
    if status_value not in VALID_STATUSES:
        issues.append(
            ValidationIssue(f"{gate_path}.status", f"must be one of {VALID_STATUSES}, got {status_value!r}")
        )

    round_number = status.get("round")
    if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
        issues.append(ValidationIssue(f"{gate_path}.round", "must be a positive integer"))

    reviewed_by = status.get("reviewed_by")
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        issues.append(ValidationIssue(f"{gate_path}.reviewed_by", "must be a non-empty string"))
    elif status_value == "passed" and gate in _VISUAL_GATES and reviewed_by != "model_vision":
        issues.append(
            ValidationIssue(
                f"{gate_path}.reviewed_by",
                "a passing visual gate must be reviewed_by model_vision",
            )
        )

    inspected_paths = status.get("inspected_paths")
    issues.extend(_check_artifact_paths(f"{gate_path}.inspected_paths", inspected_paths, artifact_root))
    if status_value == "passed" and gate in _VISUAL_GATES and not inspected_paths:
        issues.append(
            ValidationIssue(
                f"{gate_path}.inspected_paths",
                "a passing visual gate requires at least one directly inspected path",
            )
        )

    if not isinstance(status.get("revision_required"), bool):
        issues.append(ValidationIssue(f"{gate_path}.revision_required", "must be a boolean"))
    elif status_value == "passed" and status.get("revision_required") is not False:
        issues.append(ValidationIssue(f"{gate_path}.revision_required", "must be false for a passed status"))
    elif status_value == "failed" and status.get("revision_required") is not True:
        issues.append(ValidationIssue(f"{gate_path}.revision_required", "must be true for a failed status"))

    for timestamp_field in ("started_at", "completed_at"):
        value = status.get(timestamp_field)
        if not isinstance(value, str) or not value.strip():
            issues.append(ValidationIssue(f"{gate_path}.{timestamp_field}", "must be a non-empty timestamp string"))

    if status_value == "blocked":
        blocker = status.get("blocker")
        if not isinstance(blocker, str) or not blocker.strip():
            issues.append(ValidationIssue(f"{gate_path}.blocker", "a blocked status requires a non-empty blocker"))
    if status_value == "not_applicable":
        reason = status.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            issues.append(ValidationIssue(f"{gate_path}.reason", "a not_applicable status requires a non-empty reason"))

    issues.extend(_validate_findings(gate_path, status, artifact_root))
    return issues


def _validate_pptx_render_status(
    status: Mapping[str, Any],
    expected_slides: Sequence[int],
    artifact_root: Optional[Path],
) -> List[ValidationIssue]:
    """Validate the PPTX-render-only fields when the gate has evidence."""
    gate_path = "statuses.pptx_render"
    status_value = status.get("status")
    if status_value not in ("passed", "failed"):
        return []

    issues: List[ValidationIssue] = []
    renderer = status.get("renderer")
    if not isinstance(renderer, Mapping):
        issues.append(ValidationIssue(f"{gate_path}.renderer", "must be a mapping"))
        renderer = {}
    for field in ("name", "version", "conversion_format"):
        value = renderer.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(ValidationIssue(f"{gate_path}.renderer.{field}", "must be a non-empty string"))

    conversion_artifacts = status.get("conversion_artifacts")
    if not isinstance(conversion_artifacts, list) or not conversion_artifacts:
        issues.append(
            ValidationIssue(f"{gate_path}.conversion_artifacts", "must be a non-empty list of conversion outputs")
        )
    else:
        issues.extend(_check_artifact_paths(f"{gate_path}.conversion_artifacts", conversion_artifacts, artifact_root))

    rendered_png_paths = status.get("rendered_png_paths")
    if not isinstance(rendered_png_paths, list):
        issues.append(ValidationIssue(f"{gate_path}.rendered_png_paths", "must be a list of PNG paths"))
        rendered_png_paths = []
    else:
        issues.extend(_check_artifact_paths(f"{gate_path}.rendered_png_paths", rendered_png_paths, artifact_root))
        if len(rendered_png_paths) != len(expected_slides) or len(set(rendered_png_paths)) != len(expected_slides):
            issues.append(
                ValidationIssue(
                    f"{gate_path}.rendered_png_paths",
                    f"must contain exactly one PNG per expected slide ({len(expected_slides)} expected)",
                )
            )

    model_vision = status.get("model_vision")
    if not isinstance(model_vision, Mapping):
        issues.append(ValidationIssue(f"{gate_path}.model_vision", "must be a mapping"))
        model_vision = {}
    inspected_paths = model_vision.get("inspected_paths")
    if not isinstance(inspected_paths, list):
        issues.append(ValidationIssue(f"{gate_path}.model_vision.inspected_paths", "must be a list of PNG paths"))
    else:
        issues.extend(
            _check_artifact_paths(f"{gate_path}.model_vision.inspected_paths", inspected_paths, artifact_root)
        )
        if set(inspected_paths) != set(rendered_png_paths):
            issues.append(
                ValidationIssue(
                    f"{gate_path}.model_vision.inspected_paths",
                    "model_vision must directly inspect exactly the rendered final PNG set; "
                    "a review sheet or partial set is not direct evidence",
                )
            )

    comparison_reference_paths = model_vision.get("comparison_reference_paths", [])
    if comparison_reference_paths:
        issues.extend(
            _check_artifact_paths(
                f"{gate_path}.model_vision.comparison_reference_paths",
                comparison_reference_paths,
                artifact_root,
            )
        )

    if not isinstance(status.get("visual_checks"), Mapping):
        issues.append(ValidationIssue(f"{gate_path}.visual_checks", "must be a mapping of named checks"))

    return issues


def _validate_history(history: Any) -> List[ValidationIssue]:
    """Validate the ordered list of review rounds."""
    if not isinstance(history, list) or not history:
        return [ValidationIssue("history", "must be a non-empty list of review rounds")]
    issues: List[ValidationIssue] = []
    for index, round_entry in enumerate(history):
        round_path = f"history[{index}]"
        if not isinstance(round_entry, Mapping):
            issues.append(ValidationIssue(round_path, "must be a mapping"))
            continue
        round_number = round_entry.get("round")
        if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
            issues.append(ValidationIssue(f"{round_path}.round", "must be a positive integer"))
        result = round_entry.get("result")
        if not isinstance(result, str) or not result.strip():
            issues.append(ValidationIssue(f"{round_path}.result", "must be a non-empty string"))
        revision = round_entry.get("revision")
        if not isinstance(revision, str) or not revision.strip():
            issues.append(ValidationIssue(f"{round_path}.revision", "must be a non-empty string"))
    return issues


def derive_overall_status(record: Mapping[str, Any]) -> OverallResult:
    """Derive completion from the three independent gate statuses.

    Args:
        record: A review record mapping with an ``output_format`` field and
            a ``statuses`` mapping containing ``svg_preview``,
            ``pptx_structure``, and ``pptx_render`` status objects.

    Returns:
        The derived :class:`OverallResult`.

    Raises:
        ValueError: If ``output_format`` is missing, if a required status is
            missing or holds an unset/``in_progress``/unknown value, or if a
            source-only record uses anything other than ``not_applicable``
            for the PPTX-specific gates.
    """
    output_format = record.get("output_format")
    if not isinstance(output_format, str) or not output_format:
        raise ValueError("output_format is required to derive an overall result")

    statuses = record.get("statuses")
    if not isinstance(statuses, Mapping):
        raise ValueError("statuses mapping is required to derive an overall result")

    resolved: Dict[str, str] = {}
    for gate in _REQUIRED_GATES:
        gate_status = statuses.get(gate)
        if not isinstance(gate_status, Mapping):
            raise ValueError(f"statuses.{gate} is required to derive an overall result")
        value = gate_status.get("status")
        if value not in VALID_STATUSES:
            raise ValueError(f"statuses.{gate}.status is unset or unknown: {value!r}")
        resolved[gate] = value

    if output_format == "pptx":
        authority = "pptx-render"
        values = (resolved["svg_preview"], resolved["pptx_structure"], resolved["pptx_render"])
        if any(value == "not_applicable" for value in values):
            raise ValueError("a PPTX request must not mark a required gate not_applicable")
        if any(value == "failed" for value in values):
            return OverallResult("failed", False, authority)
        if any(value == "blocked" for value in values):
            return OverallResult("blocked", False, authority)
        if all(value == "passed" for value in values):
            return OverallResult("passed", True, authority)
        raise ValueError(f"unresolvable PPTX gate combination: {values!r}")

    authority = "source-pixel"
    svg_status = resolved["svg_preview"]
    if resolved["pptx_structure"] != "not_applicable" or resolved["pptx_render"] != "not_applicable":
        raise ValueError("a non-PPTX request must mark both PPTX-specific gates not_applicable")
    if svg_status == "failed":
        return OverallResult("failed", False, authority)
    if svg_status == "blocked":
        return OverallResult("blocked", False, authority)
    if svg_status == "passed":
        return OverallResult("passed", True, authority)
    raise ValueError(f"unresolvable source-only status: {svg_status!r}")


def _validate_overall(record: Mapping[str, Any]) -> List[ValidationIssue]:
    """Validate that the stored overall result matches its derivation."""
    overall = record.get("overall")
    if not isinstance(overall, Mapping):
        return [ValidationIssue("overall", "must be a mapping")]

    try:
        derived = derive_overall_status(record)
    except ValueError as error:
        return [ValidationIssue("overall", f"cannot derive overall result: {error}")]

    issues: List[ValidationIssue] = []
    if overall.get("status") != derived.status:
        issues.append(
            ValidationIssue("overall.status", f"must equal the derived status {derived.status!r}")
        )
    if overall.get("completion_allowed") != derived.completion_allowed:
        issues.append(
            ValidationIssue(
                "overall.completion_allowed",
                f"must equal the derived value {derived.completion_allowed!r}",
            )
        )
    if overall.get("authority") != derived.authority:
        issues.append(
            ValidationIssue("overall.authority", f"must equal the derived authority {derived.authority!r}")
        )
    return issues


def validate_review_record(
    record_path: Path,
    artifact_root: Optional[Path] = None,
) -> List[ValidationIssue]:
    """Read and validate one report-slides visual review record.

    This is the path-reading wrapper around :func:`validate_review_document`.
    It exists for command-line and workflow callers whose evidence has not
    already been captured into an immutable snapshot.

    Args:
        record_path: Path to the JSON review record.
        artifact_root: Root directory that relative artifact paths are
            resolved against. When ``None``, only the record's shape and
            path safety are checked; file existence and PNG readability are
            skipped.

    Returns:
        A list of :class:`ValidationIssue`, sorted by path. Empty when valid.

    Raises:
        ValueError: If the record is not valid JSON or its root is not a
            mapping.
    """
    try:
        text = record_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read review record {record_path}: {error}") from error
    try:
        record = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"malformed JSON in review record {record_path}: {error}") from error
    return validate_review_document(record, artifact_root)


def validate_review_document(
    record: Mapping[str, Any],
    artifact_root: Optional[Path] = None,
) -> List[ValidationIssue]:
    """Validate one parsed report-slides visual review record.

    This is the authoritative pure form of visual-review validation. It
    validates record shape, safe artifact declarations, every required gate,
    and the derived completion decision without reading ``record`` from disk.
    When ``artifact_root`` is ``None``, only lexical path validation occurs;
    callers that have frozen artifact bytes validate those bytes separately.

    Args:
        record: Parsed JSON review record with a mapping root.
        artifact_root: Optional root used to check declared artifact files.

    Returns:
        A list of :class:`ValidationIssue`, sorted by path. Empty when the
        parsed record is fully valid.

    Raises:
        ValueError: If ``record`` does not have a mapping root.
    """
    if not isinstance(record, Mapping):
        raise ValueError("review record must have a mapping root")

    issues: List[ValidationIssue] = []

    schema_version = record.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
        issues.append(ValidationIssue("schema_version", "must be a positive integer"))

    deck_id = record.get("deck_id")
    if not isinstance(deck_id, str) or not deck_id.strip():
        issues.append(ValidationIssue("deck_id", "must be a non-empty string"))

    output_format = record.get("output_format")
    if not isinstance(output_format, str) or not output_format:
        issues.append(ValidationIssue("output_format", "must be a non-empty string"))

    expected_slides = record.get("expected_slides")
    if (
        not isinstance(expected_slides, list)
        or not expected_slides
        or not all(isinstance(slide, int) and not isinstance(slide, bool) and slide > 0 for slide in expected_slides)
        or len(set(expected_slides)) != len(expected_slides)
    ):
        issues.append(ValidationIssue("expected_slides", "must be a non-empty list of unique positive integers"))
        expected_slides = []

    issues.extend(_check_artifact_paths("source_artifacts", record.get("source_artifacts"), artifact_root))

    artifacts = record.get("artifacts")
    if not isinstance(artifacts, Mapping):
        issues.append(ValidationIssue("artifacts", "must be a mapping"))
        artifacts = {}
    pptx_path = artifacts.get("pptx")
    if pptx_path is not None:
        issues.extend(_check_artifact_path("artifacts.pptx", pptx_path, artifact_root))
    review_record_path = artifacts.get("review_record")
    issues.extend(_check_artifact_path("artifacts.review_record", review_record_path, artifact_root))

    statuses = record.get("statuses")
    if not isinstance(statuses, Mapping):
        issues.append(ValidationIssue("statuses", "must be a mapping"))
        statuses = {}
    for gate in _REQUIRED_GATES:
        if gate not in statuses:
            issues.append(ValidationIssue(f"statuses.{gate}", "is required"))
            continue
        issues.extend(_validate_status_object(gate, statuses[gate], artifact_root))
        if gate == "pptx_render" and isinstance(statuses[gate], Mapping):
            issues.extend(_validate_pptx_render_status(statuses[gate], expected_slides, artifact_root))

    if isinstance(statuses.get("pptx_structure"), Mapping) and isinstance(statuses.get("pptx_render"), Mapping):
        if output_format != "pptx":
            for gate in ("pptx_structure", "pptx_render"):
                if statuses[gate].get("status") != "not_applicable":
                    issues.append(
                        ValidationIssue(
                            f"statuses.{gate}.status",
                            "must be not_applicable when PPTX was not requested",
                        )
                    )
        else:
            for gate in ("pptx_structure", "pptx_render"):
                if statuses[gate].get("status") == "not_applicable":
                    issues.append(
                        ValidationIssue(
                            f"statuses.{gate}.status",
                            "must not be not_applicable for a PPTX request",
                        )
                    )

    issues.extend(_validate_history(record.get("history")))
    issues.extend(_validate_overall(record))

    return sorted(issues, key=lambda issue: issue.path)


def validate_review_result_findings(
    findings: Any,
    artifact_root: Optional[Path] = None,
) -> List[ValidationIssue]:
    """Validate the findings list of a standalone Review Result document.

    Used for Review Result records that are not one of the three PPTX
    visual-inspection gates (svg_preview/pptx_structure/pptx_render) --
    currently, the Content Reviewer's plan-level review at Stage 4.

    Args:
        findings: The parsed `findings` list.
        artifact_root: Optional artifact root for `artifact_path`
            resolution; plan-level findings normally omit `artifact_path`
            entirely, so this is usually ``None``.

    Returns:
        A list of validation issues; empty if every finding is valid.
    """
    if not isinstance(findings, list):
        return [ValidationIssue("findings", "must be a list (use [] for a clean pass)")]
    issues: List[ValidationIssue] = []
    for index, finding in enumerate(findings):
        issues.extend(_validate_finding_entry(f"findings[{index}]", finding, artifact_root))
    return issues


_REVIEW_RESULT_SUBJECT_TYPES = frozenset({"plan", "module", "slide", "deck"})


def validate_review_result(
    doc: Mapping[str, Any],
    artifact_root: Optional[Path] = None,
) -> List[ValidationIssue]:
    """Validate a standalone Review Result document.

    Args:
        doc: The parsed Review Result mapping (`presentation_state.py`'s
            `record_review` contract: `subject_type`, `subject_id`,
            `reviewer_role`, `status`, `findings`, `round`).
        artifact_root: Passed through to `validate_review_result_findings`.

    Returns:
        A list of validation issues; empty if the document is valid.
    """
    issues: List[ValidationIssue] = []
    if not isinstance(doc, Mapping):
        return [ValidationIssue("<root>", "must be a mapping")]
    subject_type = doc.get("subject_type")
    if subject_type not in _REVIEW_RESULT_SUBJECT_TYPES:
        issues.append(
            ValidationIssue(
                "subject_type",
                f"must be one of {sorted(_REVIEW_RESULT_SUBJECT_TYPES)}, got {subject_type!r}",
            )
        )
    for field in ("subject_id", "reviewer_role"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(ValidationIssue(field, "required non-empty string"))
    status = doc.get("status")
    if status not in VALID_STATUSES:
        issues.append(ValidationIssue("status", f"must be one of {sorted(VALID_STATUSES)}, got {status!r}"))
    round_number = doc.get("round")
    if not isinstance(round_number, int) or isinstance(round_number, bool):
        issues.append(ValidationIssue("round", "required int"))
    issues.extend(validate_review_result_findings(doc.get("findings"), artifact_root))
    return sorted(issues, key=lambda issue: issue.path)


def main(arguments: Optional[Sequence[str]] = None) -> int:
    """Validate a review record or standalone Review Result from the command line.

    For PPTX visual review records (--record), this doubles as a completion
    gate: it exits non-zero both when the record is structurally invalid and
    when it is well-formed but does not (yet) permit a completion claim.

    For standalone Review Result documents (--review-result), this is a pure
    validation gate: it exits non-zero only when the document is structurally
    invalid.

    Args:
        arguments: Command-line arguments, excluding the program name.
            Defaults to ``sys.argv[1:]`` when ``None``.

    Returns:
        ``0`` only when the input has no structural issues (and, for
        --record, its derived ``completion_allowed`` is ``True``);
        ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description="Validate a report-slides PPTX visual review record or standalone Review Result.")
    parser.add_argument(
        "--record", type=Path, help="Path to a PPTX visual-review.json record."
    )
    parser.add_argument(
        "--review-result", type=Path, help="Path to a standalone Review Result YAML or JSON document."
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="Artifact root for relative paths in --record. Ignored for --review-result.",
    )
    parsed = parser.parse_args(arguments)

    if bool(parsed.record) == bool(parsed.review_result):
        parser.error("exactly one of --record or --review-result is required")
    if parsed.record and not parsed.root:
        parser.error("--root is required with --record")

    if parsed.review_result:
        try:
            text = parsed.review_result.read_text(encoding="utf-8")
            if parsed.review_result.suffix in (".yaml", ".yml"):
                doc = yaml.safe_load(text)
            else:
                doc = json.loads(text)
        except (OSError, json.JSONDecodeError, yaml.YAMLError) as error:
            print(f"ERROR {parsed.review_result}: {error}")
            return 1
        issues = validate_review_result(doc)
        if issues:
            for issue in issues:
                print(f"ERROR {issue.path}: {issue.message}")
            return 1
        return 0

    issues = validate_review_record(parsed.record, parsed.root)
    if issues:
        for issue in issues:
            print(f"ERROR {issue.path}: {issue.message}")
        return 1

    record = json.loads(parsed.record.read_text(encoding="utf-8"))
    result = derive_overall_status(record)
    print(f"status={result.status} authority={result.authority} completion_allowed={result.completion_allowed}")
    return 0 if result.completion_allowed else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
