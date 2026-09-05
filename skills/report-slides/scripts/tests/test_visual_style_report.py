"""Tests for the visual-style finding and report model."""

from __future__ import annotations

import pytest

from visual_style.report import Finding, LintReport, RuleError


def test_finding_rejects_an_unknown_severity() -> None:
    """A severity outside the known set is a programming error."""
    with pytest.raises(RuleError):
        Finding(rule="type-floor", severity="nit", message="too small")


def test_report_separates_errors_from_warnings() -> None:
    """Errors and warnings are retrievable independently."""
    report = LintReport()
    report.add(Finding(rule="type-floor", severity="error", message="10 < 21"))
    report.add(Finding(rule="off-grid", severity="warning", message="3 off grid"))
    assert len(report.errors) == 1
    assert len(report.warnings) == 1
    assert report.has_errors is True


def test_report_without_errors_does_not_fail_the_gate() -> None:
    """Warnings alone leave has_errors false."""
    report = LintReport()
    report.add(Finding(rule="off-grid", severity="warning", message="3 off grid"))
    assert report.has_errors is False


def test_report_ordering_is_deterministic() -> None:
    """Findings sort by severity, then rule, then element, then message."""
    report = LintReport()
    report.add(Finding(rule="off-grid", severity="warning", message="w1"))
    report.add(Finding(rule="type-floor", severity="error",
                       message="b", element_id="t2"))
    report.add(Finding(rule="type-floor", severity="error",
                       message="a", element_id="t1"))
    report.add(Finding(rule="safe-area", severity="error", message="s"))
    order = [(f.rule, f.element_id) for f in report.findings]
    assert order == [
        ("safe-area", None),
        ("type-floor", "t1"),
        ("type-floor", "t2"),
        ("off-grid", None),
    ]


def test_report_to_dict_is_json_serialisable() -> None:
    """The report serialises to a plain mapping for the CLI."""
    import json

    report = LintReport()
    report.add(Finding(rule="node-gap", severity="error",
                       message="18 < 24", element_id="n3", location=(120.0, 80.0)))
    payload = report.to_dict()
    assert payload["valid"] is False
    assert payload["error_count"] == 1
    assert payload["warning_count"] == 0
    assert payload["findings"][0]["rule"] == "node-gap"
    assert payload["findings"][0]["location"] == [120.0, 80.0]
    json.dumps(payload)


def test_empty_report_is_valid() -> None:
    """A clean run reports valid with zero findings."""
    payload = LintReport().to_dict()
    assert payload["valid"] is True
    assert payload["findings"] == []
