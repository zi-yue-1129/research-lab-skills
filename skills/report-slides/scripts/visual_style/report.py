"""Finding and report model for the visual-style linter."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

SEVERITIES: Tuple[str, ...] = ("error", "warning")
_SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES)}


class RuleError(ValueError):
    """Raised when a rule is constructed or configured incorrectly.

    Distinct from a finding: a finding describes a defect in the reviewed slide,
    while this describes a defect in the linter's own inputs.
    """


@dataclass(frozen=True)
class Finding:
    """One measured defect in a slide.

    Attributes:
        rule: Stable rule identifier, such as `type-floor`.
        severity: One of `SEVERITIES`.
        message: Human-readable statement naming the measured and expected
            values, so the finding is falsifiable without rerunning the linter.
        element_id: Identifier of the offending element, when one is known.
        location: `(x, y)` in SVG units, when a point is meaningful.
    """

    rule: str
    severity: str
    message: str
    element_id: Optional[str] = None
    location: Optional[Tuple[float, float]] = None

    def __post_init__(self) -> None:
        """Validate the severity.

        Raises:
            RuleError: If the severity is not one of `SEVERITIES`.
        """
        if self.severity not in _SEVERITY_RANK:
            raise RuleError(
                f"unknown severity {self.severity!r}; expected one of {SEVERITIES}"
            )

    def sort_key(self) -> Tuple[int, str, str, str]:
        """Return the deterministic ordering key for this finding."""
        return (
            _SEVERITY_RANK[self.severity],
            self.rule,
            self.element_id or "",
            self.message,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable mapping for this finding."""
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "element_id": self.element_id,
            "location": list(self.location) if self.location else None,
        }


@dataclass
class LintReport:
    """An ordered collection of findings from one linting run."""

    _findings: List[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        """Record one finding.

        Args:
            finding: The finding to record.
        """
        self._findings.append(finding)

    def extend(self, findings: Iterable[Finding]) -> None:
        """Record several findings.

        Args:
            findings: The findings to record.
        """
        self._findings.extend(findings)

    @property
    def findings(self) -> Tuple[Finding, ...]:
        """Return every finding in deterministic order."""
        return tuple(sorted(self._findings, key=Finding.sort_key))

    @property
    def errors(self) -> Tuple[Finding, ...]:
        """Return only the error-severity findings."""
        return tuple(f for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> Tuple[Finding, ...]:
        """Return only the warning-severity findings."""
        return tuple(f for f in self.findings if f.severity == "warning")

    @property
    def has_errors(self) -> bool:
        """Return whether any error-severity finding was recorded."""
        return bool(self.errors)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable summary of the run."""
        findings = self.findings
        return {
            "valid": not self.has_errors,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [finding.to_dict() for finding in findings],
        }
