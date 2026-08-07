"""Contract tests for the converted-PPTX visual review record validator."""

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image

from validate_visual_review import (
    OverallResult,
    _ALLOWED_FINDING_KINDS,
    derive_overall_status,
    validate_review_record,
    validate_review_result,
    validate_review_result_findings,
)


TIMESTAMP = "2026-08-03T10:00:00Z"


def _status(
    status: str,
    reviewed_by: str,
    inspected_paths: Sequence[str],
    *,
    findings: Optional[Sequence[Dict[str, Any]]] = None,
    round_number: int = 1,
    revision_required: bool = False,
    blocker: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one status object with deterministic review timestamps."""
    payload: Dict[str, Any] = {
        "status": status,
        "round": round_number,
        "reviewed_by": reviewed_by,
        "inspected_paths": list(inspected_paths),
        "findings": list(findings or []),
        "revision_required": revision_required,
        "started_at": TIMESTAMP,
        "completed_at": TIMESTAMP,
    }
    if blocker is not None:
        payload["blocker"] = blocker
    if reason is not None:
        payload["reason"] = reason
    return payload


def _finding(
    kind: str,
    artifact_path: str,
    *,
    source: str = "pptx-render",
    disposition: str = "open",
) -> Dict[str, Any]:
    """Build a concrete visual finding for a review record."""
    return {
        "kind": kind,
        "scope": {"slide": 2, "region": "body-copy"},
        "artifact_path": artifact_path,
        "description": "The converted slide reflows the body copy into an unintended line.",
        "source": source,
        "disposition": disposition,
    }


def _base_record(
    output_format: str = "pptx", expected_slides: Sequence[int] = (1, 2)
) -> Dict[str, Any]:
    """Return a complete passing PPTX or source-only review record."""
    slides = list(expected_slides)
    source_png_paths = [f"renders/source/slide-{slide}.png" for slide in slides]
    source_svg_paths = [f"slides/slide-{slide}.svg" for slide in slides]
    final_png_paths = [
        f"renders/pptx/libreoffice/slide-{slide}.png" for slide in slides
    ]
    structure_paths = ["deck/visual-review.pptx", "deck/structure.json"]
    statuses: Dict[str, Any] = {
        "svg_preview": _status("passed", "model_vision", source_png_paths),
    }
    if output_format == "pptx":
        statuses["pptx_structure"] = _status(
            "passed", "pptx_structure_validator", structure_paths
        )
        render_status = _status("passed", "model_vision", final_png_paths)
        render_status.update(
            {
                "renderer": {
                    "name": "LibreOffice",
                    "version": "25.2.3.2",
                    "conversion_format": "pdf-to-png",
                },
                "conversion_artifacts": [
                    "renders/pptx/libreoffice/visual-review.pdf"
                ],
                "rendered_png_paths": final_png_paths,
                "model_vision": {
                    "inspected_paths": final_png_paths,
                    "comparison_reference_paths": source_png_paths,
                },
                "visual_checks": {
                    "clipping": "passed",
                    "overlap": "passed",
                    "text_reflow": "passed",
                    "connector_drift": "passed",
                    "crop": "passed",
                    "unreadably_small_text": "passed",
                    "missing_image": "passed",
                    "other_layout_regressions": "passed",
                },
            }
        )
        statuses["pptx_render"] = render_status
        artifacts: Dict[str, Any] = {
            "pptx": "deck/visual-review.pptx",
            "review_record": "review.json",
        }
        overall = {
            "status": "passed",
            "completion_allowed": True,
            "authority": "pptx-render",
        }
    else:
        source_reason = "PPTX was not requested for this source-only SVG output contract."
        statuses["pptx_structure"] = _status(
            "not_applicable",
            "workflow",
            [],
            reason=source_reason,
        )
        statuses["pptx_render"] = _status(
            "not_applicable",
            "workflow",
            [],
            reason=source_reason,
        )
        artifacts = {"pptx": None, "review_record": "review.json"}
        overall = {
            "status": "passed",
            "completion_allowed": True,
            "authority": "source-pixel",
        }
    return {
        "schema_version": 1,
        "deck_id": "pptx-visual-review-contract",
        "output_format": output_format,
        "expected_slides": slides,
        "source_artifacts": source_svg_paths + source_png_paths,
        "artifacts": artifacts,
        "statuses": statuses,
        "overall": overall,
        "history": [
            {
                "round": 1,
                "result": "passed",
                "revision": "Initial review completed with the required evidence.",
            }
        ],
    }


def _set_overall(record: Dict[str, Any]) -> OverallResult:
    """Replace the stored overall result with its deterministic derivation."""
    result = derive_overall_status(record)
    record["overall"] = {
        "status": result.status,
        "completion_allowed": result.completion_allowed,
        "authority": result.authority,
    }
    return result


def _materialize_paths(root: Path, record: Dict[str, Any]) -> None:
    """Create readable fixture artifacts named by a review record."""
    paths: List[str] = list(record.get("source_artifacts", []))
    artifacts = record.get("artifacts", {})
    paths.extend(
        value for value in artifacts.values() if isinstance(value, str)
    )
    for status in record.get("statuses", {}).values():
        if not isinstance(status, dict):
            continue
        paths.extend(
            value
            for value in status.get("inspected_paths", [])
            if isinstance(value, str)
        )
        paths.extend(
            value
            for value in status.get("conversion_artifacts", [])
            if isinstance(value, str)
        )
        paths.extend(
            value
            for value in status.get("rendered_png_paths", [])
            if isinstance(value, str)
        )
        model_vision = status.get("model_vision", {})
        if isinstance(model_vision, dict):
            paths.extend(
                value
                for value in model_vision.get("inspected_paths", [])
                if isinstance(value, str)
            )
            paths.extend(
                value
                for value in model_vision.get("comparison_reference_paths", [])
                if isinstance(value, str)
            )
    for path_text in sorted(set(paths)):
        path = root / path_text
        if path == root / "review.json":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".png":
            Image.new("RGB", (320, 180), (32, 96, 160)).save(path)
        elif not path.exists():
            path.write_text("fixture artifact", encoding="utf-8")


def _write_record(root: Path, record: Dict[str, Any]) -> Path:
    """Materialize artifacts and persist one JSON review record."""
    _materialize_paths(root, record)
    record_path = root / "review.json"
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record_path


def _mapping_bytes(value: Any) -> bytes:
    """Encode a mapping deterministically for byte-for-byte comparisons."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_pptx_happy_path_allows_completion(tmp_path: Path) -> None:
    """Allow completion only when all three PPTX gates pass."""
    record = _base_record()

    result = derive_overall_status(record)

    assert result.status == "passed"
    assert result.completion_allowed is True
    assert result.authority == "pptx-render"
    assert validate_review_record(_write_record(tmp_path, record), tmp_path) == []


def test_pptx_only_text_reflow_fails_render(tmp_path: Path) -> None:
    """Keep a converted-PPTX text-reflow finding authoritative over source passes."""
    record = _base_record()
    render_status = record["statuses"]["pptx_render"]
    render_status["status"] = "failed"
    render_status["revision_required"] = True
    render_status["findings"] = [
        _finding(
            "text-reflow",
            "renders/pptx/libreoffice/slide-2.png",
        )
    ]
    record["history"] = [
        {
            "round": 1,
            "result": "failed",
            "revision": "Correct the native text box before a fresh export.",
        }
    ]

    result = _set_overall(record)

    assert result.status == "failed"
    assert result.completion_allowed is False
    assert record["statuses"]["svg_preview"]["status"] == "passed"
    assert record["statuses"]["pptx_structure"]["status"] == "passed"
    assert validate_review_record(_write_record(tmp_path, record), tmp_path) == []


def test_missing_renderer_blocks_completion() -> None:
    """Block completion when no office renderer can produce final PNGs."""
    record = _base_record()
    render_status = record["statuses"]["pptx_render"]
    render_status["status"] = "blocked"
    render_status["blocker"] = (
        "LibreOffice is unavailable; the actual PPTX cannot be converted to PNG."
    )
    render_status.pop("renderer")
    render_status.pop("conversion_artifacts")
    render_status.pop("rendered_png_paths")
    render_status.pop("model_vision")

    result = _set_overall(record)

    assert result.status == "blocked"
    assert result.completion_allowed is False
    assert "renderer" in render_status["blocker"] or "LibreOffice" in render_status["blocker"]


def test_partial_direct_inspection_blocks_completion(tmp_path: Path) -> None:
    """Reject a passing render whose model_vision set omits a final PNG."""
    record = _base_record()
    render_status = record["statuses"]["pptx_render"]
    render_status["model_vision"]["inspected_paths"] = [
        render_status["rendered_png_paths"][0]
    ]
    record_path = _write_record(tmp_path, record)

    issues = validate_review_record(record_path, tmp_path)

    assert any(
        issue.path == "statuses.pptx_render.model_vision.inspected_paths"
        for issue in issues
    )
    assert any("direct" in issue.message.lower() for issue in issues)


def test_missing_expected_slide_blocks_completion(tmp_path: Path) -> None:
    """Reject conversion evidence that omits one expected slide."""
    record = _base_record()
    render_status = record["statuses"]["pptx_render"]
    first_png = render_status["rendered_png_paths"][0]
    render_status["rendered_png_paths"] = [first_png]
    render_status["model_vision"]["inspected_paths"] = [first_png]
    record_path = _write_record(tmp_path, record)

    issues = validate_review_record(record_path, tmp_path)

    assert any(
        issue.path.startswith("statuses.pptx_render.rendered_png_paths")
        and "slide" in issue.message.lower()
        for issue in issues
    )


def test_non_pptx_marks_pptx_gates_not_applicable(tmp_path: Path) -> None:
    """Keep source-pixel review authoritative for a source-only deliverable."""
    record = _base_record(output_format="svg", expected_slides=(1,))

    result = derive_overall_status(record)

    assert result.status == "passed"
    assert result.completion_allowed is True
    assert result.authority == "source-pixel"
    assert record["statuses"]["pptx_structure"]["status"] == "not_applicable"
    assert record["statuses"]["pptx_render"]["status"] == "not_applicable"
    assert validate_review_record(_write_record(tmp_path, record), tmp_path) == []


def test_gate_statuses_remain_independent() -> None:
    """Preserve each gate's evidence when another gate changes state."""
    record = _base_record()
    original_svg = _mapping_bytes(record["statuses"]["svg_preview"])
    original_structure = _mapping_bytes(record["statuses"]["pptx_structure"])

    structure_failure = copy.deepcopy(record)
    structure_failure["statuses"]["pptx_structure"]["status"] = "failed"
    structure_failure["statuses"]["pptx_structure"]["revision_required"] = True
    structure_failure["statuses"]["pptx_structure"]["findings"] = [
        _finding(
            "missing-image",
            "deck/structure.json",
            source="pptx-structure",
        )
    ]
    assert _mapping_bytes(structure_failure["statuses"]["svg_preview"]) == original_svg

    render_failure = copy.deepcopy(record)
    render_failure["statuses"]["pptx_render"]["status"] = "failed"
    render_failure["statuses"]["pptx_render"]["revision_required"] = True
    render_failure["statuses"]["pptx_render"]["findings"] = [
        _finding("connector-drift", "renders/pptx/libreoffice/slide-2.png")
    ]
    assert (
        _mapping_bytes(render_failure["statuses"]["pptx_structure"])
        == original_structure
    )


def test_revision_round_rechecks_converted_pngs(tmp_path: Path) -> None:
    """Require a new converted PNG set after a failed render round."""
    record = _base_record()
    source_paths = record["statuses"]["svg_preview"]["inspected_paths"]
    structure_paths = record["statuses"]["pptx_structure"]["inspected_paths"]
    render_status = record["statuses"]["pptx_render"]
    new_png_paths = [
        f"renders/pptx/libreoffice/round-2/slide-{slide}.png"
        for slide in record["expected_slides"]
    ]
    render_status["round"] = 2
    render_status["rendered_png_paths"] = new_png_paths
    render_status["model_vision"]["inspected_paths"] = new_png_paths
    render_status["conversion_artifacts"] = [
        "renders/pptx/libreoffice/round-2/visual-review.pdf"
    ]
    record["statuses"]["svg_preview"]["round"] = 2
    record["statuses"]["pptx_structure"]["round"] = 2
    record["history"] = [
        {
            "round": 1,
            "result": "failed",
            "revision": "Corrected the text box sizing.",
        },
        {
            "round": 2,
            "result": "passed",
            "revision": "Re-exported and directly inspected both final PNGs.",
        },
    ]
    result = _set_overall(record)

    assert result.status == "passed"
    assert render_status["model_vision"]["inspected_paths"] == new_png_paths
    assert source_paths == record["statuses"]["svg_preview"]["inspected_paths"]
    assert structure_paths == record["statuses"]["pptx_structure"]["inspected_paths"]
    assert validate_review_record(_write_record(tmp_path, record), tmp_path) == []


def test_passing_render_requires_renderer_metadata(tmp_path: Path) -> None:
    """Reject a passing render without the renderer identity and version."""
    record = _base_record()
    del record["statuses"]["pptx_render"]["renderer"]["version"]
    record_path = _write_record(tmp_path, record)

    issues = validate_review_record(record_path, tmp_path)

    assert any(
        issue.path == "statuses.pptx_render.renderer.version" for issue in issues
    )


def test_passing_render_requires_exact_png_set(tmp_path: Path) -> None:
    """Reject duplicate or incomplete final PNG sets for a passing render."""
    record = _base_record()
    first_png = record["statuses"]["pptx_render"]["rendered_png_paths"][0]
    render_status = record["statuses"]["pptx_render"]
    render_status["rendered_png_paths"] = [first_png, first_png]
    render_status["model_vision"]["inspected_paths"] = [first_png, first_png]
    record_path = _write_record(tmp_path, record)

    issues = validate_review_record(record_path, tmp_path)

    assert any(
        issue.path.startswith("statuses.pptx_render.rendered_png_paths")
        for issue in issues
    )


def test_passing_render_rejects_review_sheet_only(tmp_path: Path) -> None:
    """Reject a contact sheet when final PNGs were not inspected directly."""
    record = _base_record()
    review_sheet = "renders/pptx/review-sheet.png"
    record["artifacts"]["review_sheet"] = review_sheet
    record["statuses"]["pptx_render"]["model_vision"]["inspected_paths"] = [
        review_sheet
    ]
    record_path = _write_record(tmp_path, record)

    issues = validate_review_record(record_path, tmp_path)

    assert any(
        issue.path == "statuses.pptx_render.model_vision.inspected_paths"
        and "direct" in issue.message.lower()
        for issue in issues
    )


def test_passing_render_rejects_open_finding(tmp_path: Path) -> None:
    """Reject a passing render that still contains an open visual finding."""
    record = _base_record()
    record["statuses"]["pptx_render"]["findings"] = [
        _finding("text-reflow", "renders/pptx/libreoffice/slide-2.png")
    ]
    record_path = _write_record(tmp_path, record)

    issues = validate_review_record(record_path, tmp_path)

    assert any(
        issue.path.startswith("statuses.pptx_render.findings")
        and "open" in issue.message.lower()
        for issue in issues
    )


def test_passing_visual_gate_requires_inspected_paths(tmp_path: Path) -> None:
    """Reject a passing visual gate that names no directly inspected path."""
    record = _base_record()
    record["statuses"]["svg_preview"]["inspected_paths"] = []
    record_path = _write_record(tmp_path, record)

    issues = validate_review_record(record_path, tmp_path)

    assert any(
        issue.path == "statuses.svg_preview.inspected_paths"
        and "inspected" in issue.message.lower()
        for issue in issues
    )


def test_unsupported_claim_is_an_allowed_finding_kind() -> None:
    """Allow the plan-level unsupported-claim finding kind."""
    assert "unsupported-claim" in _ALLOWED_FINDING_KINDS


def test_all_new_plan_level_finding_kinds_are_allowed() -> None:
    """Allow every new plan-level finding kind added for Stage 4 review."""
    for kind in (
        "unsupported-claim", "duplicated-content", "missing-limitation",
        "excessive-background", "unnecessary-visual", "weak-continuity",
    ):
        assert kind in _ALLOWED_FINDING_KINDS


def test_plan_review_finding_does_not_require_scope_or_artifact_path() -> None:
    """Validate plan-level findings without scope or artifact_path."""
    findings = [
        {
            "kind": "unsupported-claim",
            "description": "Slide 3 claims a 40% speedup with no cited benchmark.",
            "source": "plan_review",
            "disposition": "open",
        }
    ]
    issues = validate_review_result_findings(findings)
    assert issues == []


def test_plan_review_finding_rejects_unknown_kind() -> None:
    """Reject plan-level findings with unknown kinds."""
    findings = [
        {
            "kind": "not-a-real-kind",
            "description": "x",
            "source": "plan_review",
            "disposition": "open",
        }
    ]
    issues = validate_review_result_findings(findings)
    assert any(issue.path.endswith(".kind") for issue in issues)


def test_visual_gate_finding_still_requires_scope_and_artifact_path() -> None:
    """Require scope and artifact_path for visual-gate findings."""
    findings = [
        {
            "kind": "clipping",
            "description": "Text clipped in the top-right region.",
            "source": "svg-preview",
            "disposition": "open",
        }
    ]
    issues = validate_review_result_findings(findings)
    paths = {issue.path for issue in issues}
    assert any(p.endswith(".scope") for p in paths)


def test_validate_review_result_accepts_a_well_formed_plan_review() -> None:
    """Accept well-formed plan-level review documents."""
    doc = {
        "subject_type": "plan",
        "subject_id": "deck_20260808_ab12cd",
        "reviewer_role": "content_reviewer",
        "status": "failed",
        "round": 1,
        "findings": [
            {
                "kind": "duplicated-content",
                "description": "Slides 5 and 7 both restate the same limitation.",
                "source": "plan_review",
                "disposition": "open",
            }
        ],
    }
    assert validate_review_result(doc) == []


def test_validate_review_result_rejects_bad_subject_type() -> None:
    """Reject review results with invalid subject_type."""
    doc = {
        "subject_type": "not-a-type",
        "subject_id": "x",
        "reviewer_role": "content_reviewer",
        "status": "failed",
        "round": 1,
        "findings": [],
    }
    issues = validate_review_result(doc)
    assert any(issue.path == "subject_type" for issue in issues)
