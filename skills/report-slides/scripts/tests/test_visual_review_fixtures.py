"""Contract tests for the six real converted-PPTX visual review fixtures."""

import json
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from validate_visual_review import validate_review_record

_FIXTURES_ROOT = Path(__file__).resolve().parents[4] / "tests/fixtures/report-slides-pptx-visual-review"
_MANIFEST = yaml.safe_load((_FIXTURES_ROOT / "fixture_manifest.yaml").read_text(encoding="utf-8"))
_CASES: Dict[str, Dict[str, Any]] = {entry["deck_id"]: entry for entry in _MANIFEST["cases"]}

_CASE_IDS = (
    "clean-two-slide",
    "native-text-reflow",
    "connector-endpoint-drift",
    "image-crop-regression",
    "missing-image-relationship",
    "unreadably-small-text",
)


def _load_record(case_id: str) -> Dict[str, Any]:
    record_path = _FIXTURES_ROOT / case_id / "review.json"
    return json.loads(record_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case_id", _CASE_IDS)
def test_fixture_manifest_covers_every_case(case_id: str) -> None:
    """Require fixture_manifest.yaml to define an entry for every case."""
    assert case_id in _CASES


@pytest.mark.parametrize("case_id", _CASE_IDS)
def test_fixture_record_validates_with_no_issues(case_id: str) -> None:
    """Require every fixture's review.json to be a structurally valid record."""
    record_path = _FIXTURES_ROOT / case_id / "review.json"
    issues = validate_review_record(record_path, _FIXTURES_ROOT)
    assert issues == []


@pytest.mark.parametrize("case_id", _CASE_IDS)
def test_fixture_record_matches_expected_statuses(case_id: str) -> None:
    """Require each gate's status to match the manifest's expectation."""
    expected = _CASES[case_id]["expected_statuses"]
    record = _load_record(case_id)
    for gate, expected_status in expected.items():
        assert record["statuses"][gate]["status"] == expected_status


@pytest.mark.parametrize("case_id", _CASE_IDS)
def test_fixture_record_matches_expected_completion(case_id: str) -> None:
    """Require the derived completion decision to match the manifest."""
    expected_completion = _CASES[case_id]["expected_completion_allowed"]
    record = _load_record(case_id)
    assert record["overall"]["completion_allowed"] == expected_completion
    assert record["overall"]["authority"] == "pptx-render"


@pytest.mark.parametrize("case_id", _CASE_IDS)
def test_pptx_case_records_deck_and_conversion_evidence(case_id: str) -> None:
    """Require every PPTX case to name its deck, conversion artifacts, and PNG set."""
    record = _load_record(case_id)
    expected_slides = record["expected_slides"]

    assert record["artifacts"]["pptx"] == f"{case_id}/deck.pptx"

    render_status = record["statuses"]["pptx_render"]
    if render_status["status"] not in ("passed", "failed"):
        return

    assert render_status["conversion_artifacts"]
    assert len(render_status["rendered_png_paths"]) == len(expected_slides)

    if render_status["status"] == "passed":
        assert set(render_status["model_vision"]["inspected_paths"]) == set(
            render_status["rendered_png_paths"]
        )


@pytest.mark.parametrize("case_id", _CASE_IDS)
def test_failure_fixture_retains_finding_under_observed_gate(case_id: str) -> None:
    """Require a failing case's finding to stay under the gate that observed it."""
    expected_kind = _CASES[case_id]["expected_finding_kind"]
    record = _load_record(case_id)

    if expected_kind is None:
        for gate in ("svg_preview", "pptx_structure", "pptx_render"):
            assert record["statuses"][gate]["findings"] == []
        return

    failing_gates = [
        gate
        for gate in ("svg_preview", "pptx_structure", "pptx_render")
        if record["statuses"][gate]["status"] == "failed"
    ]
    assert failing_gates

    for gate in failing_gates:
        findings = record["statuses"][gate]["findings"]
        assert any(finding["kind"] == expected_kind for finding in findings)
        for finding in findings:
            assert finding["source"] == gate.replace("_", "-")


def test_missing_image_case_fails_independently_at_two_gates() -> None:
    """Require the missing-image case to fail structure and render separately."""
    record = _load_record("missing-image-relationship")
    assert record["statuses"]["pptx_structure"]["status"] == "failed"
    assert record["statuses"]["pptx_render"]["status"] == "failed"
    structure_findings = record["statuses"]["pptx_structure"]["findings"]
    render_findings = record["statuses"]["pptx_render"]["findings"]
    assert structure_findings and render_findings
    assert structure_findings[0]["artifact_path"] != render_findings[0]["artifact_path"]
