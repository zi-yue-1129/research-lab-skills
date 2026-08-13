"""Tests for the strict Slide Specification validator."""

from datetime import date
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from presentation_contracts import contract_sha256
from validate_slide_spec import validate_slide_spec


SCRIPT = Path(__file__).resolve().parent.parent / "validate_slide_spec.py"


def valid_slide_spec() -> dict[str, Any]:
    """Return a complete Slide Specification fixture."""
    return {
        "schema_version": 1,
        "slide_id": "slide-01",
        "information_hierarchy": ["approved takeaway", "supporting evidence"],
        "reading_order": ["title", "visual"],
        "layout_regions": [
            {"region_id": "title", "bbox": [0, 0, 1200, 100]},
            {"region_id": "visual", "bbox": [0, 100, 1200, 675]},
        ],
        "text_to_visual_ratio": 0.3,
        "visual_emphasis": "Emphasize the approved takeaway before supporting detail.",
        "expected_complexity": "medium",
        "reusable_components": [],
        "requires_complex_workflow": None,
        "complexity_signals": {
            "region_count": 2,
            "route_count": 1,
            "multi_stage": False,
            "mixed_technique": False,
            "heavy_cross_region_connections": False,
            "expected_reuse": False,
            "not_atomic": False,
        },
        "approved_takeaway": "Action commands join observation features before prediction.",
        "approved_takeaway_sha256": contract_sha256(
            "Action commands join observation features before prediction."
        ),
        "approved_evidence_refs": ["E-OBS", "E-CMD"],
        "approved_evidence_sha256": contract_sha256(["E-OBS", "E-CMD"]),
    }


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the Slide Specification validator CLI."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_valid_slide_spec_passes() -> None:
    """Accept a complete Slide Specification before detector execution."""
    assert validate_slide_spec(valid_slide_spec()) == []


def test_slide_spec_requires_protected_content_and_complete_regions() -> None:
    """Reject incomplete reading order and every protected content field."""
    spec = valid_slide_spec()
    spec["reading_order"] = ["missing-region"]
    errors = validate_slide_spec(spec)
    assert any("reading_order" in error for error in errors)

    for field in (
        "approved_takeaway",
        "approved_takeaway_sha256",
        "approved_evidence_refs",
        "approved_evidence_sha256",
    ):
        missing = valid_slide_spec()
        missing.pop(field)
        assert any(field in error for error in validate_slide_spec(missing))


def test_slide_spec_rejects_duplicate_or_out_of_bounds_regions() -> None:
    """Reject duplicate region IDs and coordinates outside the slide canvas."""
    duplicate = valid_slide_spec()
    duplicate["layout_regions"][1]["region_id"] = "title"
    assert any("duplicate" in error for error in validate_slide_spec(duplicate))

    outside = valid_slide_spec()
    outside["layout_regions"][1]["bbox"] = [0, 100, 1201, 675]
    assert any("bbox" in error and "1200" in error for error in validate_slide_spec(outside))


def test_slide_spec_rejects_non_numeric_ratio_and_incomplete_signals() -> None:
    """Reject ratios outside the unit interval and missing complexity signals."""
    bad_ratio = valid_slide_spec()
    bad_ratio["text_to_visual_ratio"] = 1.1
    assert any("text_to_visual_ratio" in error for error in validate_slide_spec(bad_ratio))

    missing_signal = valid_slide_spec()
    missing_signal["complexity_signals"].pop("not_atomic")
    assert any("not_atomic" in error for error in validate_slide_spec(missing_signal))


def test_slide_spec_requires_detector_field_to_be_nullable_or_boolean() -> None:
    """Reject a detector result whose workflow decision has the wrong type."""
    invalid = valid_slide_spec()
    invalid["requires_complex_workflow"] = "yes"
    assert any(
        "requires_complex_workflow" in error
        for error in validate_slide_spec(invalid)
    )


def test_slide_spec_protected_digests_match_approved_content() -> None:
    """Reject protected content mutations when their digests are unchanged."""
    takeaway_mutation = valid_slide_spec()
    takeaway_mutation["approved_takeaway"] += " Changed."
    takeaway_errors = validate_slide_spec(takeaway_mutation)
    assert any("approved_takeaway_sha256" in error for error in takeaway_errors)

    evidence_mutation = valid_slide_spec()
    evidence_mutation["approved_evidence_refs"] = ["E-OBS", "E-LATENT"]
    evidence_errors = validate_slide_spec(evidence_mutation)
    assert any("approved_evidence_sha256" in error for error in evidence_errors)


def test_slide_spec_cli_rejects_yaml_date_protected_value_without_traceback(
    tmp_path: Path,
) -> None:
    """Return structured JSON when YAML parses protected content as a date."""
    spec = valid_slide_spec()
    spec["approved_takeaway"] = date(2026, 8, 8)
    path = tmp_path / "date-slide-spec.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")

    result = _run("--spec", str(path), "--json")

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    data = json.loads(result.stdout)
    assert data["valid"] is False
    assert any("approved_takeaway" in error for error in data["errors"])


def test_slide_spec_cli_reports_json_result(tmp_path: Path) -> None:
    """Validate a YAML specification through the documented JSON CLI."""
    path = tmp_path / "slide-spec.yaml"
    path.write_text(yaml.safe_dump(valid_slide_spec()), encoding="utf-8")

    result = _run("--spec", str(path), "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"valid": True, "errors": []}
