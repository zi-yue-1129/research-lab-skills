# report-slides Visual Review and Art Direction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace prose-only visual gates with a deterministic linter that measures against the design tokens, split the review stage so that art-direction defects have a name and an owner, and stop the generative route producing AI stock imagery.

**Architecture:** A new `visual_style/` package parses an authored SVG into a typed scene (boxes, text runs, connectors), then runs rule modules against the resolved token set, emitting findings with `error` or `warning` severity. `validate_visual_style.py` is the CLI gate. The existing `visual_quality_reviewer_agent` is renamed to `render_integrity_reviewer_agent` with its defect vocabulary unchanged, and a new `art_direction_reviewer_agent` judges the whole slide with authority to require re-layout. Generative illustration becomes opt-in, anchored to curated reference styles rather than adjective lists.

**Tech Stack:** Python 3.11 (`.github/workflows/pytest.yml` pins 3.11; existing modules such as `presentation_gates.py` already use 3.10+ syntax, so new code may too), lxml, PyYAML, Pillow (font metrics via `fonts.py`, and colour-name resolution in `visual_style/color.py`), pytest. The linter deliberately does **not** depend on python-pptx: it measures authored SVG, not exported PPTX.

**Spec:** `docs/superpowers/specs/2026-09-04-report-slides-visual-quality-design.md`

**Prerequisite:** `docs/superpowers/plans/2026-09-04-report-slides-visual-quality.md` must be complete. This plan imports `design_tokens.py` and `fonts.py` from it, and its rules assume the token contract exists.

## Global Constraints

- All code comments, docstrings, log messages, and commit subjects in English.
- Every function signature carries type hints; every public module/function/class/method carries a Google-style docstring.
- No silent failures. No bare `except:`. `except Exception` only when it re-raises or logs with `exc_info=True` plus a comment stating why execution continues. Never `except ...: pass`. Never add `# noqa`, `# type: ignore`, or `# pragma: no cover`.
- Keep files under ~1000 lines; the linter is split into rule modules for this reason.
- Red before green: run each new test and see it FAIL for the intended reason before implementing, then see it pass. Report both runs.
- Never weaken a test to make it green.
- Every command is time-bound: `timeout <secs> python3 -m pytest ...`.
- Canvas is fixed at `1200 × 675`. SVG `font-size` maps 1:1 to PowerPoint points.
- Tests live in `skills/report-slides/scripts/tests/`. Run pytest from the repository root.
- Linter thresholds come from the token file. A rule must never hard-code a number the token contract already carries.
- Text extents are measured with real font metrics via `fonts.text_width`. Character-count estimates are not acceptable.

---

## File Map

| File | Action | Phase |
|------|--------|-------|
| `skills/report-slides/scripts/visual_style/__init__.py` | Create | 1 |
| `skills/report-slides/scripts/visual_style/report.py` | Create | 1 |
| `skills/report-slides/scripts/tests/test_visual_style_report.py` | Create | 1 |
| `skills/report-slides/scripts/visual_style/scene.py` | Create | 1 |
| `skills/report-slides/scripts/tests/test_visual_style_scene.py` | Create | 1 |
| `skills/report-slides/scripts/visual_style/geometry.py` | Create | 2 |
| `skills/report-slides/scripts/tests/test_visual_style_geometry.py` | Create | 2 |
| `skills/report-slides/scripts/visual_style/typography.py` | Create | 2 |
| `skills/report-slides/scripts/tests/test_visual_style_typography.py` | Create | 2 |
| `skills/report-slides/scripts/visual_style/color.py` | Create | 2 |
| `skills/report-slides/scripts/tests/test_visual_style_color.py` | Create | 2 |
| `skills/report-slides/scripts/visual_style/connectors.py` | Create | 2 |
| `skills/report-slides/scripts/tests/test_visual_style_connectors.py` | Create | 2 |
| `skills/report-slides/scripts/visual_style/density.py` | Create | 2 |
| `skills/report-slides/scripts/tests/test_visual_style_density.py` | Create | 2 |
| `skills/report-slides/scripts/validate_visual_style.py` | Create | 3 |
| `skills/report-slides/scripts/tests/test_validate_visual_style.py` | Create | 3 |
| `skills/report-slides/scripts/tests/test_slide_archetypes.py` | Create | 3 |
| `skills/report-slides/references/visual-review.md` | Modify (defer measurable checks to the linter) | 3 |
| `skills/report-slides/SKILL.md` | Modify (Stage 10 gate, Stage 12 split) | 3, 4 |
| `skills/report-slides/agents/visual_quality_reviewer_agent.md` | Rename → `render_integrity_reviewer_agent.md`, narrow remit | 4 |
| `skills/report-slides/agents/art_direction_reviewer_agent.md` | Create | 4 |
| `skills/report-slides/agents/scientific_visual_reviewer_agent.md` | Modify (line 12 cross-reference) | 4 |
| `skills/report-slides/scripts/presentation_gates.py` | Modify (roles, finding kinds, completion predicate) | 4 |
| `skills/report-slides/scripts/presentation_workflow.py` | Modify (separate slide and module completion predicates) | 4 |
| `skills/report-slides/scripts/presentation_events.py` | Modify (next-action derivation) | 4 |
| `skills/report-slides/scripts/validate_visual_review.py` | Modify (accept the art-direction finding kinds) | 4 |
| `skills/report-slides/scripts/tests/test_reviewer_roles.py` | Create | 4 |
| `skills/report-slides/scripts/tests/test_agent_persona_docs.py` | Modify (renamed and new personas) | 4, 5 |
| `skills/report-slides/scripts/tests/test_presentation_state.py` | Modify (next-action label rename) | 4 |
| `skills/report-slides/references/style-anchors/README.md` | Create | 5 |
| `skills/report-slides/references/style-anchors/anchors.yaml` | Create (ships empty, per spec §D6) | 5 |
| `skills/report-slides/scripts/style_anchors.py` | Create | 5 |
| `skills/report-slides/scripts/tests/test_style_anchors.py` | Create | 5 |
| `skills/report-slides/scripts/validate_generative_prompt.py` | Create | 5 |
| `skills/report-slides/scripts/tests/test_validate_generative_prompt.py` | Create | 5 |
| `skills/report-slides/references/generative-visuals.md` | Modify (opt-in gate, anchored prompts, validation) | 5 |
| `skills/report-slides/agents/conceptual_illustration_worker_agent.md` | Modify (route default inverted, downgrade rule) | 5 |
| `skills/report-slides/agents/research_narrative_planner_agent.md` | Modify (line 38 route guidance) | 5 |
| `skills/report-slides/scripts/tests/test_shipped_examples.py` | Create | 5 |
| `examples/report-slides/visual-authoring/assets/research-collaboration/WHY-THIS-FAILS.md` | Create | 5 |
| `examples/report-slides/visual-authoring/assets/research-collaboration/{prompt.md,review.json,source.svg}` | Modify (counter-example record, downgrade) | 5 |
| `examples/report-slides/visual-authoring/slides/*.svg` | Modify (remove the raster layer, bring onto tokens) | 5 |
| `skills/report-slides/scripts/lint_evidence.py` | Create | 6 |
| `skills/report-slides/scripts/tests/test_lint_evidence.py` | Create | 6 |
| `skills/report-slides/scripts/validate_visual_style.py` | Modify (`--record` writes lint evidence) | 6 |
| `skills/report-slides/scripts/presentation_gates.py` | Modify (require current lint evidence; retire `visual_quality` writes) | 4, 6 |

---

## Phase Overview

| Phase | Theme | Tasks |
|-------|-------|-------|
| 1 | Scene model and finding report | 1–2 |
| 2 | Measurable rules | 3–7 |
| 3 | Linter CLI and workflow gate | 8 |
| 4 | Review split and art direction | 9–10 |
| 5 | Generative art direction | 11–13 |
| 6 | Lint evidence and the enforced gate | 14 |

## Rule Inventory

Spec §D4 fixes the rule set. Every rule below is implemented in Phase 2 and named
in its task. Hard errors fail the build; warnings are reported to the
art-direction reviewer for judgement.

**Hard errors**

| Rule id | Check | Task |
|---|---|---|
| `safe-area` | Non-bleed content outside the token safe area | 3 |
| `element-overlap` | Unintended shape or text overlap | 3 |
| `node-gap` | Node-to-node gap below `spacing.node_gap_min` | 3 |
| `node-padding` | Internal padding below `spacing.node_padding` | 3 |
| `type-floor` | Text below its role minimum | 4 |
| `text-contrast` | Text contrast below `color.contrast.text_min` (or `large_text_min`) | 5 |
| `graphic-contrast` | Non-decorative graphic below `color.contrast.graphic_min` | 5 |
| `token-color` | A colour absent from `color.roles` | 5 |
| `component-drift` | Instances of one style role differing in radius, stroke width, or label size | 7 |
| `connector-dangling` | A connector endpoint attached to nothing | 6 |
| `connector-port-drift` | An endpoint more than 4 units from its declared port | 6 |
| `connector-through-node` | A connector crossing a node interior | 6 |
| `connector-clearance` | Clearance below `spacing.connector_clearance_min` | 6 |
| `hand-drawn-arrow` | An arrow polygon where an arrowheaded connector is required | 6 |

**Warnings**

| Rule id | Check | Task |
|---|---|---|
| `off-grid` | Eligible edges more than 2 units off `canvas.grid` | 3 |
| `spacing-variance` | Repeated gap or size variance greater than 4 units | 7 |
| `type-variety` | More than `typography.max_sizes_per_slide` distinct sizes | 4 |
| `overlong-text` | Title over 2 lines, body over ~90 words, node label over `max_lines` | 4 |
| `bullet-budget` | More than `density.max_bullets` bullets | 7 |
| `connector-crossing` | More than one unintended connector crossing | 6 |
| `occupancy` | Content occupancy outside `density.occupancy_min`..`occupancy_max` | 7 |
| `equal-card-repetition` | Undifferentiated equal cards where hierarchy is called for | 7 |

The CLI adds one rule of its own, `unreadable-input` (Task 8), for a slide that
cannot be parsed at all. It belongs to no module and is deliberately excluded
from the module rule count of 22.

**Out of scope of both plans (separate design required):** automatic graph layout
via ELK/Graphviz/dagre. See spec §5.

---

## Phase 1: Scene Model and Finding Report

---

### Task 1: Finding and report model

**Files:**
- Create: `skills/report-slides/scripts/visual_style/__init__.py`
- Create: `skills/report-slides/scripts/visual_style/report.py`
- Test: `skills/report-slides/scripts/tests/test_visual_style_report.py`

**Interfaces:**
- Consumes: nothing.
- Produces, imported by every later task:
  - `SEVERITIES: tuple` — `("error", "warning")`
  - `@dataclass(frozen=True) class Finding` — `rule: str`, `severity: str`,
    `message: str`, `element_id: Optional[str] = None`,
    `location: Optional[Tuple[float, float]] = None`
  - `class LintReport` with `add(finding: Finding) -> None`,
    `extend(findings: Iterable[Finding]) -> None`, `findings -> Tuple[Finding, ...]`,
    `errors -> Tuple[Finding, ...]`, `warnings -> Tuple[Finding, ...]`,
    `has_errors -> bool`, `to_dict() -> Dict[str, Any]`
  - `class RuleError(ValueError)`

The report is ordered deterministically so a run is reproducible and diffable:
errors before warnings, then by rule id, then by element id, then by message.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_visual_style_report.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visual_style'`.

- [ ] **Step 3: Create the package and report model**

Create `skills/report-slides/scripts/visual_style/__init__.py`:

```python
"""Deterministic visual-style linting for report-slides.

Rules measure an authored SVG against a resolved design-token set. Prose review
judges what the measurements cannot; this package judges what they can.
"""
```

Create `skills/report-slides/scripts/visual_style/report.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_report.py -v`
Expected: PASS — 6 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/visual_style/ \
        skills/report-slides/scripts/tests/test_visual_style_report.py
git commit -m "feat(report-slides): add visual-style finding and report model"
```

---

### Task 2: SVG scene extraction

**Files:**
- Create: `skills/report-slides/scripts/visual_style/scene.py`
- Test: `skills/report-slides/scripts/tests/test_visual_style_scene.py`

**Interfaces:**
- Consumes: `visual_style.report.RuleError` (Task 1); `fonts.text_width`,
  `fonts.resolve_font_stack` (plan 1, Task 5);
  `svg_to_pptx.style_parser.compute_style`.
- Produces, imported by Tasks 3–7:
  - `@dataclass(frozen=True) class Box` — `element_id`, `tag`, `x`, `y`, `w`,
    `h`, `fill`, `stroke`, `stroke_width`, `radius`, `style_role`, `node_id`,
    `bleed`; plus `right`, `bottom`, `area` properties and
    `intersects(other) -> bool`, `gap_to(other) -> float`,
    `contains_point(px, py) -> bool`, `contains_box(other) -> bool`
  - `@dataclass(frozen=True) class TextRun` — `element_id`, `text`, `x`, `y`,
    `size`, `weight`, `fill`, `anchor`, `style_role`, `node_id`, `line_count`,
    `ascent`, `descent`, `line_offset`,
    `width`; plus a `bbox() -> Box` method
  - `@dataclass(frozen=True) class Connector` — `element_id`, `x1`, `y1`, `x2`,
    `y2`, `stroke`, `stroke_width`, `has_head`, `has_tail`, `node_id`,
    `from_node`, `to_node`
  - `@dataclass(frozen=True) class Polygon` — `element_id`, `points`, `fill`,
    `node_id`
  - `@dataclass(frozen=True) class Scene` — `width`, `height`, `boxes`, `texts`,
    `connectors`, `polygons`, `font_family`; plus `nodes() -> Dict[str, List[Box]]`
  - `parse_scene(svg_path: Union[str, Path], font_family: str) -> Scene`
  - `_is_connector(elem) -> bool` — internal, but the rule it encodes is part of
    the authoring contract: a line joins nodes only when it says so

**Design notes.**

- `node_id` is inherited from the nearest enclosing
  `<g data-pptx-role="group" data-node-id="...">`. Rules that compare "the same
  semantic component" group by it.
- `style_role` comes from a `data-style-role` attribute. Spec §D1 requires every
  generated element to carry one; the linter reports its absence only where a
  rule needs it, so hand-authored SVG is not rejected wholesale on day one.
- The full-canvas background rect is excluded from the scene: it legitimately
  covers the whole slide and would otherwise trip `safe-area` and
  `element-overlap` on every run.
- `bleed` records `data-bleed="true"`. The frame's top bar and header rule run
  edge to edge by design; without this marker `safe-area` would fire on every
  slide and the rule would be trained away as noise.
- `from_node` and `to_node` record `data-from` and `data-to`: the node ids a
  connector claims to join. They are what makes `connector-port-drift`
  falsifiable — without a declared intent, a drifted endpoint is
  indistinguishable from a deliberate one.
- **Not every `<line>` is a connector.** Chart gridlines, column rules, and the
  frame's own header rule (`generate_slides.py` draws
  `<line x1="40" y1="54" x2="1160" y2="54">` on every slide) are lines that
  join nothing. A line is admitted as a `Connector` only when it declares
  `data-from`/`data-to`, carries `marker-start`/`marker-end`, or declares a
  `data-style-role` beginning with `connector`. Everything else is a rule, and
  rules are not linted for attachment. Without this, `connector-dangling` would
  fire on every slide in the deck and the rule would be switched off within a
  day.
- The text box is measured in both axes. `ascent` and `descent` come from
  `fonts.vertical_metrics`; `line_offset` sums the `dy` the renderer wrote onto
  the tspans. No line-height or ascent constant appears in this module — a
  guessed one is what let the shipped footer sit outside the safe area
  undetected.
- Text width is measured, never estimated. `line_count` counts `<tspan>` children,
  defaulting to 1.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_visual_style_scene.py`:

```python
"""Tests for SVG scene extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from visual_style.scene import Box, parse_scene

_FAMILY = "DejaVu Sans"
_SCENE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#ffffff"/>
  <g data-pptx-role="group" data-node-id="n1">
    <rect x="100" y="100" width="200" height="90" rx="8"
          fill="#f8fafc" stroke="#475569" stroke-width="1.5"
          data-style-role="node.primary"/>
    <text x="200" y="150" font-size="18" font-weight="600" fill="#374151"
          text-anchor="middle" data-style-role="node.label">Encoder</text>
  </g>
  <g data-pptx-role="group" data-node-id="n2">
    <rect x="500" y="100" width="200" height="90" rx="8"
          fill="#f8fafc" stroke="#475569" stroke-width="1.5"
          data-style-role="node.primary"/>
    <text x="600" y="150" font-size="18" font-weight="600" fill="#374151"
          text-anchor="middle" data-style-role="node.label">Decoder</text>
  </g>
  <line x1="300" y1="145" x2="500" y2="145" stroke="#475569" stroke-width="2"
        marker-end="url(#arrow)" data-from="n1" data-to="n2"/>
  <line x1="40" y1="54" x2="1160" y2="54" stroke="#e2e8f0" stroke-width="1.5"/>
  <polygon points="700,145 720,140 720,150" fill="#475569"/>
</svg>"""


@pytest.fixture()
def scene(tmp_path: Path):
    """Parse the shared fixture SVG into a scene."""
    path = tmp_path / "slide.svg"
    path.write_text(_SCENE_SVG, encoding="utf-8")
    return parse_scene(path, _FAMILY)


def test_canvas_dimensions_come_from_the_viewbox(scene) -> None:
    """Scene dimensions match the SVG viewBox."""
    assert scene.width == 1200
    assert scene.height == 675


def test_full_canvas_background_is_excluded(scene) -> None:
    """The background rect is not treated as slide content."""
    assert all(not (box.w == 1200 and box.h == 675) for box in scene.boxes)
    assert len(scene.boxes) == 2


def test_boxes_carry_geometry_and_style(scene) -> None:
    """Box geometry, radius, stroke, and style role are extracted."""
    box = next(b for b in scene.boxes if b.x == 100)
    assert (box.w, box.h) == (200, 90)
    assert box.radius == 8
    assert box.stroke == "#475569"
    assert box.stroke_width == 1.5
    assert box.style_role == "node.primary"
    assert box.node_id == "n1"


def test_text_runs_are_measured_not_estimated(scene) -> None:
    """Text width comes from real font metrics."""
    run = next(t for t in scene.texts if t.text == "Encoder")
    assert run.size == 18
    assert run.weight == 600
    assert run.anchor == "middle"
    assert run.node_id == "n1"
    assert run.width > 0
    assert run.width == pytest.approx(
        __import__("fonts").text_width("Encoder", _FAMILY, 18, 600), rel=1e-6
    )


def test_text_bbox_respects_the_anchor(scene) -> None:
    """A middle-anchored run's bbox is centred on its x coordinate."""
    run = next(t for t in scene.texts if t.text == "Encoder")
    bbox = run.bbox()
    assert bbox.x == pytest.approx(200 - run.width / 2, abs=0.5)
    assert bbox.right == pytest.approx(200 + run.width / 2, abs=0.5)


def test_text_bbox_is_measured_vertically(scene) -> None:
    """The box spans the face's real ascent and descent, not a guessed 0.8 em.

    DejaVu Sans at size 18 reports ascent 17 and descent 5. A model that assumed
    0.8 em of ascent and a full 1.2 em line-height below the baseline would put
    the box at top 135.6 with bottom 157.2 -- 2.6 units too low at the top and
    2.2 too low at the bottom, which is exactly the error that let a footer
    baseline on the safe-area boundary look compliant.
    """
    run = next(t for t in scene.texts if t.text == "Encoder")
    assert (run.ascent, run.descent, run.line_offset) == (17.0, 5.0, 0.0)
    bbox = run.bbox()
    assert bbox.y == pytest.approx(133.0)
    assert bbox.bottom == pytest.approx(155.0)


def test_multiline_text_measures_the_dy_the_renderer_wrote(
    tmp_path: Path,
) -> None:
    """Line spacing is read from the markup, not reconstructed from a constant.

    `generate_slides.tlines` writes `dy="0"` on the first span and
    `dy="{size * lh:.1f}"` on the rest, so the distance between the first and
    last baseline is already in the file.
    """
    markup = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">\n'
        '  <text x="100" y="200" font-size="20" fill="#374151">'
        '<tspan x="100" dy="0">one</tspan>'
        '<tspan x="100" dy="29.0">two</tspan>'
        '<tspan x="100" dy="29.0">three</tspan></text>\n'
        '</svg>'
    )
    path = tmp_path / "multiline.svg"
    path.write_text(markup, encoding="utf-8")
    run = parse_scene(path, _FAMILY).texts[0]
    assert run.line_count == 3
    assert run.line_offset == pytest.approx(58.0)
    ascent, descent = run.ascent, run.descent
    assert run.bbox().h == pytest.approx(ascent + 58.0 + descent)


def test_a_plain_rule_is_not_a_connector(scene) -> None:
    """The frame's header rule joins nothing and must not be linted as a link."""
    assert len(scene.connectors) == 1
    assert all(conn.y1 != 54 for conn in scene.connectors)


def test_connectors_record_their_arrowheads(scene) -> None:
    """marker-end sets has_tail; marker-start sets has_head."""
    conn = scene.connectors[0]
    assert (conn.x1, conn.y1, conn.x2, conn.y2) == (300, 145, 500, 145)
    assert conn.has_tail is True
    assert conn.has_head is False
    assert (conn.from_node, conn.to_node) == ("n1", "n2")


def test_polygons_are_captured_for_arrow_detection(scene) -> None:
    """Free polygons are retained so hand-drawn arrows can be detected."""
    assert len(scene.polygons) == 1
    assert len(scene.polygons[0].points) == 3


def test_nodes_groups_boxes_by_node_id(scene) -> None:
    """Scene.nodes() indexes content by its enclosing group."""
    nodes = scene.nodes()
    assert set(nodes) == {"n1", "n2"}
    assert len(nodes["n1"]) == 1


def test_box_gap_and_intersection() -> None:
    """Gap and intersection maths behave on simple boxes."""
    a = Box("a", "rect", 0, 0, 100, 100, None, None, 0, 0, None, None, False)
    b = Box("b", "rect", 130, 0, 100, 100, None, None, 0, 0, None, None, False)
    c = Box("c", "rect", 50, 50, 100, 100, None, None, 0, 0, None, None, False)
    assert a.gap_to(b) == pytest.approx(30)
    assert a.intersects(b) is False
    assert a.intersects(c) is True
    assert a.gap_to(c) == 0
    inner = Box("i", "rect", 10, 10, 20, 20, None, None, 0, 0, None, None, False)
    assert a.contains_box(inner) is True
    assert a.contains_box(c) is False


def test_bleed_marker_is_recorded(tmp_path: Path) -> None:
    """data-bleed marks an element that is exempt from the safe area."""
    path = tmp_path / "bleed.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">'
        '<rect x="0" y="0" width="1200" height="6" fill="#1e3a5f" '
        'data-bleed="true"/>'
        '<rect x="100" y="100" width="80" height="40" fill="#f8fafc"/>'
        '</svg>',
        encoding="utf-8",
    )
    scene = parse_scene(path, _FAMILY)
    bars = [box for box in scene.boxes if box.h == 6]
    assert len(bars) == 1
    assert bars[0].bleed is True
    assert all(not b.bleed for b in scene.boxes if b.h != 6)


def test_parse_scene_raises_on_missing_viewbox(tmp_path: Path) -> None:
    """An SVG without a viewBox cannot be measured and is rejected."""
    path = tmp_path / "bad.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as excinfo:
        parse_scene(path, _FAMILY)
    assert "viewBox" in str(excinfo.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_scene.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'visual_style.scene'`.

- [ ] **Step 3: Write the scene model**

Create `skills/report-slides/scripts/visual_style/scene.py`:

```python
"""Typed scene extraction from an authored slide SVG.

Rules operate on this model rather than on raw XML, so that geometry, style
roles, and measured text extents are resolved exactly once per slide.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from lxml import etree

from fonts import text_width, vertical_metrics

_CANVAS_TOLERANCE = 0.5


def _local_tag(elem) -> str:
    """Return an element's tag without its namespace.

    Args:
        elem: An lxml element.

    Returns:
        The local tag name, or an empty string for comments.
    """
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    return tag.split("}")[-1] if "}" in tag else tag


def _number(value: Optional[str], default: float = 0.0) -> float:
    """Parse a numeric SVG attribute.

    Args:
        value: The raw attribute value.
        default: Value returned when the attribute is absent.

    Returns:
        The parsed number.

    Raises:
        ValueError: If the attribute is present but not numeric.
    """
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"non-numeric SVG attribute {value!r}: {exc}") from exc


@dataclass(frozen=True)
class Box:
    """An axis-aligned rectangle of slide content.

    Attributes:
        element_id: Identifier for reporting; the `id` attribute or a synthesised
            positional label.
        tag: Source SVG tag, such as `rect` or `circle`.
        x: Left edge in SVG units.
        y: Top edge in SVG units.
        w: Width in SVG units.
        h: Height in SVG units.
        fill: Fill colour, or None when unfilled.
        stroke: Stroke colour, or None when unstroked.
        stroke_width: Stroke width in SVG units.
        radius: Corner radius in SVG units.
        style_role: The `data-style-role` token role, when declared.
        node_id: The enclosing group's `data-node-id`, when inside one.
        bleed: Whether the element declares `data-bleed="true"` and is therefore
            allowed to extend past the safe area.
    """

    element_id: str
    tag: str
    x: float
    y: float
    w: float
    h: float
    fill: Optional[str]
    stroke: Optional[str]
    stroke_width: float
    radius: float
    style_role: Optional[str]
    node_id: Optional[str]
    bleed: bool = False

    @property
    def right(self) -> float:
        """Return the right edge."""
        return self.x + self.w

    @property
    def bottom(self) -> float:
        """Return the bottom edge."""
        return self.y + self.h

    @property
    def area(self) -> float:
        """Return the area in square SVG units."""
        return max(0.0, self.w) * max(0.0, self.h)

    def intersects(self, other: "Box") -> bool:
        """Return whether two boxes overlap in both axes.

        Args:
            other: The box to test against.

        Returns:
            True when the interiors overlap.
        """
        return (self.x < other.right and other.x < self.right
                and self.y < other.bottom and other.y < self.bottom)

    def gap_to(self, other: "Box") -> float:
        """Return the shortest edge-to-edge distance to another box.

        Args:
            other: The box to measure to.

        Returns:
            0.0 when the boxes touch or overlap, otherwise the gap in SVG units.
        """
        dx = max(0.0, max(self.x - other.right, other.x - self.right))
        dy = max(0.0, max(self.y - other.bottom, other.y - self.bottom))
        if dx == 0.0 and dy == 0.0:
            return 0.0
        if dx == 0.0:
            return dy
        if dy == 0.0:
            return dx
        return (dx ** 2 + dy ** 2) ** 0.5

    def contains_point(self, px: float, py: float) -> bool:
        """Return whether a point lies inside this box.

        Args:
            px: Point x coordinate.
            py: Point y coordinate.

        Returns:
            True when the point is strictly inside.
        """
        return self.x < px < self.right and self.y < py < self.bottom

    def contains_box(self, other: "Box") -> bool:
        """Return whether another box lies wholly inside this one.

        Args:
            other: The box to test.

        Returns:
            True when every edge of `other` is within this box.
        """
        return (self.x <= other.x and self.y <= other.y
                and other.right <= self.right and other.bottom <= self.bottom)


@dataclass(frozen=True)
class TextRun:
    """One measured text element.

    Attributes:
        element_id: Identifier for reporting.
        text: The concatenated text content.
        x: Anchor x coordinate.
        y: Baseline y coordinate.
        size: Font size in SVG units.
        weight: Numeric font weight.
        fill: Text colour.
        anchor: SVG `text-anchor` value.
        style_role: The `data-style-role` token role, when declared.
        node_id: The enclosing group's `data-node-id`, when inside one.
        line_count: Number of rendered lines.
        ascent: Measured distance from the baseline to the top of the em box.
        descent: Measured distance from the baseline to the bottom of it.
        line_offset: Summed `dy` of the element's `<tspan>` children, i.e. the
            distance from the first baseline to the last. Measured from the
            markup, not derived from a line-height constant.
        width: Measured advance width of the widest line.
    """

    element_id: str
    text: str
    x: float
    y: float
    size: float
    weight: int
    fill: str
    anchor: str
    style_role: Optional[str]
    node_id: Optional[str]
    line_count: int
    width: float
    ascent: float
    descent: float
    line_offset: float

    def bbox(self) -> Box:
        """Return the run's bounding box, honouring its anchor.

        Returns:
            A `Box` covering the rendered text.
        """
        if self.anchor == "middle":
            left = self.x - self.width / 2
        elif self.anchor == "end":
            left = self.x - self.width
        else:
            left = self.x
        # Every term here is measured. `ascent`/`descent` come from the face
        # via Pillow, and `line_offset` is the sum of the `dy` the renderer
        # actually wrote onto the tspans. A guessed 0.8 em ascent with no
        # descent term understates the top of the box and overstates its bottom
        # by most of a line, which is how the shipped footer slipped past this
        # rule while genuinely hanging outside the safe area.
        top = self.y - self.ascent
        height = self.ascent + self.line_offset + self.descent
        return Box(self.element_id, "text", left, top, self.width, height,
                   self.fill, None, 0.0, 0.0, self.style_role, self.node_id,
                   False)


@dataclass(frozen=True)
class Connector:
    """One straight connector segment.

    Attributes:
        element_id: Identifier for reporting.
        x1: Start x coordinate.
        y1: Start y coordinate.
        x2: End x coordinate.
        y2: End y coordinate.
        stroke: Stroke colour.
        stroke_width: Stroke width in SVG units.
        has_head: Whether `marker-start` requests an arrowhead.
        has_tail: Whether `marker-end` requests an arrowhead.
        node_id: The enclosing group's `data-node-id`, when inside one.
        from_node: The node id declared in `data-from`, when present.
        to_node: The node id declared in `data-to`, when present.
    """

    element_id: str
    x1: float
    y1: float
    x2: float
    y2: float
    stroke: Optional[str]
    stroke_width: float
    has_head: bool
    has_tail: bool
    node_id: Optional[str]
    from_node: Optional[str] = None
    to_node: Optional[str] = None


@dataclass(frozen=True)
class Polygon:
    """One polygon, retained so hand-drawn arrowheads can be detected.

    Attributes:
        element_id: Identifier for reporting.
        points: The polygon vertices.
        fill: Fill colour, or None when unfilled.
        node_id: The enclosing group's `data-node-id`, when inside one.
    """

    element_id: str
    points: Tuple[Tuple[float, float], ...]
    fill: Optional[str]
    node_id: Optional[str]


@dataclass(frozen=True)
class Scene:
    """Everything a rule needs to measure one slide.

    Attributes:
        width: Canvas width in SVG units.
        height: Canvas height in SVG units.
        boxes: Rectangular and elliptical content, background excluded.
        texts: Measured text runs.
        connectors: Straight connector segments.
        polygons: Free polygons.
        font_family: The resolved family used for measurement.
    """

    width: float
    height: float
    boxes: Tuple[Box, ...]
    texts: Tuple[TextRun, ...]
    connectors: Tuple[Connector, ...]
    polygons: Tuple[Polygon, ...]
    font_family: str

    def nodes(self) -> Dict[str, List[Box]]:
        """Group boxes by their enclosing semantic node.

        Returns:
            A mapping from `data-node-id` to the boxes inside that group.
        """
        grouped: Dict[str, List[Box]] = {}
        for box in self.boxes:
            if box.node_id is None:
                continue
            grouped.setdefault(box.node_id, []).append(box)
        return grouped


def _weight_of(raw: Optional[str]) -> int:
    """Parse an SVG font-weight into a numeric weight.

    Args:
        raw: The raw `font-weight` value.

    Returns:
        A numeric weight; `bold` maps to 700 and absence to 400.
    """
    value = (raw or "400").strip().lower()
    if value == "bold":
        return 700
    if value == "normal":
        return 400
    try:
        return int(value)
    except ValueError:
        return 400


def _line_count(elem) -> int:
    """Count rendered lines in a text element.

    Args:
        elem: The `<text>` element.

    Returns:
        The number of `<tspan>` children, or 1 when there are none.
    """
    spans = [child for child in elem if _local_tag(child) == "tspan"]
    return len(spans) or 1


def _line_offset(elem) -> float:
    """Sum the `dy` offsets of a text element's `<tspan>` children.

    This is the distance from the first baseline to the last, read from the
    markup the renderer produced rather than reconstructed from a line-height
    constant. `generate_slides.tlines` writes `dy="0"` on the first span and
    `dy="{size * lh:.1f}"` on each one after it.

    Args:
        elem: The `<text>` element.

    Returns:
        The total offset in SVG units; 0.0 for single-line text.
    """
    total = 0.0
    for child in elem:
        if _local_tag(child) == "tspan":
            total += _number(child.get("dy"), 0.0)
    return total


def _widest_line(elem, family: str, size: float, weight: int) -> Tuple[str, float]:
    """Measure a text element's widest rendered line.

    Args:
        elem: The `<text>` element.
        family: Resolved font family.
        size: Font size in SVG units.
        weight: Numeric font weight.

    Returns:
        `(text, width)` for the widest line; the text is the full content.
    """
    spans = [child for child in elem if _local_tag(child) == "tspan"]
    if spans:
        lines = ["".join(span.itertext()) for span in spans]
    else:
        lines = ["".join(elem.itertext())]
    widest = 0.0
    for line in lines:
        widest = max(widest, text_width(line, family, size, weight))
    return "".join(elem.itertext()).strip(), widest


def parse_scene(svg_path: Union[str, Path], font_family: str) -> Scene:
    """Parse an authored slide SVG into a typed scene.

    Args:
        svg_path: Path to the SVG file.
        font_family: A resolved, installed family used for text measurement.

    Returns:
        The extracted `Scene`.

    Raises:
        ValueError: If the SVG has no usable `viewBox`, or an attribute is
            malformed.
    """
    tree = etree.parse(str(svg_path))
    root = tree.getroot()
    viewbox = root.get("viewBox")
    if not viewbox:
        raise ValueError(
            f"{svg_path} has no viewBox; the scene cannot be measured"
        )
    parts = viewbox.split()
    if len(parts) != 4:
        raise ValueError(f"{svg_path} has a malformed viewBox {viewbox!r}")
    width = _number(parts[2])
    height = _number(parts[3])

    boxes: List[Box] = []
    texts: List[TextRun] = []
    connectors: List[Connector] = []
    polygons: List[Polygon] = []

    def walk(elem, node_id: Optional[str], index: List[int]) -> None:
        """Recursively collect scene content.

        Args:
            elem: Current element.
            node_id: Inherited `data-node-id`, if any.
            index: Single-element list used as a mutable counter for ids.
        """
        for child in elem:
            tag = _local_tag(child)
            if not tag:
                continue
            index[0] += 1
            element_id = child.get("id") or f"{tag}#{index[0]}"
            child_node = child.get("data-node-id") or node_id
            role = child.get("data-style-role")
            bleed = (child.get("data-bleed") or "").strip().lower() == "true"

            if tag == "g":
                walk(child, child_node, index)
                continue

            if tag == "rect":
                x = _number(child.get("x"))
                y = _number(child.get("y"))
                w = _number(child.get("width"))
                h = _number(child.get("height"))
                is_background = (
                    abs(x) < _CANVAS_TOLERANCE and abs(y) < _CANVAS_TOLERANCE
                    and abs(w - width) < _CANVAS_TOLERANCE
                    and abs(h - height) < _CANVAS_TOLERANCE
                )
                if is_background:
                    continue
                radius = max(_number(child.get("rx")), _number(child.get("ry")))
                boxes.append(Box(
                    element_id, tag, x, y, w, h,
                    child.get("fill"), child.get("stroke"),
                    _number(child.get("stroke-width")), radius, role, child_node,
                    bleed))
            elif tag in ("circle", "ellipse"):
                cx = _number(child.get("cx"))
                cy = _number(child.get("cy"))
                if tag == "circle":
                    rx = ry = _number(child.get("r"))
                else:
                    rx = _number(child.get("rx"))
                    ry = _number(child.get("ry"))
                boxes.append(Box(
                    element_id, tag, cx - rx, cy - ry, 2 * rx, 2 * ry,
                    child.get("fill"), child.get("stroke"),
                    _number(child.get("stroke-width")), min(rx, ry),
                    role, child_node, bleed))
            elif tag == "text":
                size = _number(child.get("font-size"), 0.0)
                weight = _weight_of(child.get("font-weight"))
                content, measured = _widest_line(child, font_family, size, weight)
                ascent, descent = vertical_metrics(font_family, size)
                texts.append(TextRun(
                    element_id, content,
                    _number(child.get("x")), _number(child.get("y")),
                    size, weight, child.get("fill") or "#000000",
                    child.get("text-anchor") or "start",
                    role, child_node, _line_count(child), measured,
                    ascent, descent, _line_offset(child)))
            elif tag == "line":
                if not _is_connector(child):
                    continue
                connectors.append(Connector(
                    element_id,
                    _number(child.get("x1")), _number(child.get("y1")),
                    _number(child.get("x2")), _number(child.get("y2")),
                    child.get("stroke"), _number(child.get("stroke-width"), 1.0),
                    _marker_requested(child.get("marker-start")),
                    _marker_requested(child.get("marker-end")),
                    child_node, child.get("data-from"), child.get("data-to")))
            elif tag in ("polygon", "polyline"):
                points = _parse_points(child.get("points", ""))
                if tag == "polygon":
                    polygons.append(Polygon(
                        element_id, points, child.get("fill"), child_node))
                elif not _is_connector(child):
                    continue
                else:
                    for start, end in zip(points, points[1:]):
                        connectors.append(Connector(
                            element_id, start[0], start[1], end[0], end[1],
                            child.get("stroke"),
                            _number(child.get("stroke-width"), 1.0),
                            _marker_requested(child.get("marker-start")),
                            _marker_requested(child.get("marker-end")),
                            child_node, child.get("data-from"),
                            child.get("data-to")))
            else:
                walk(child, child_node, index)

    walk(root, None, [0])
    return Scene(width, height, tuple(boxes), tuple(texts),
                 tuple(connectors), tuple(polygons), font_family)


def _marker_requested(value: Optional[str]) -> bool:
    """Return whether a marker attribute asks for an arrowhead.

    Args:
        value: The raw `marker-start` or `marker-end` value.

    Returns:
        True for a `url(#id)` reference.
    """
    text = (value or "").strip().lower()
    return bool(text) and text != "none"


def _is_connector(elem) -> bool:
    """Return whether a line-like element is a semantic connector.

    Chart gridlines, column rules, and the frame's header rule are lines that
    join nothing. Linting them for attachment would fire on every slide, so a
    line must declare its intent to be treated as a connector.

    Args:
        elem: The `<line>` or `<polyline>` element.

    Returns:
        True when the element declares endpoints, an arrowhead, or a connector
        style role.
    """
    if elem.get("data-from") or elem.get("data-to"):
        return True
    if _marker_requested(elem.get("marker-start")) or _marker_requested(
            elem.get("marker-end")):
        return True
    return (elem.get("data-style-role") or "").startswith("connector")


def _parse_points(raw: str) -> Tuple[Tuple[float, float], ...]:
    """Parse an SVG points list.

    Args:
        raw: The raw `points` attribute.

    Returns:
        The parsed vertices.

    Raises:
        ValueError: If the list contains a non-numeric entry or an odd count.
    """
    tokens = [token for token in raw.replace(",", " ").split() if token]
    try:
        numbers = [float(token) for token in tokens]
    except ValueError as exc:
        raise ValueError(f"malformed points list {raw!r}: {exc}") from exc
    if len(numbers) % 2 != 0:
        raise ValueError(f"points list {raw!r} has an odd number of values")
    return tuple(
        (numbers[i], numbers[i + 1]) for i in range(0, len(numbers), 2)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_scene.py -v`
Expected: PASS — 14 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/visual_style/scene.py \
        skills/report-slides/scripts/tests/test_visual_style_scene.py
git commit -m "feat(report-slides): extract typed scenes from authored slide SVG"
```

---

## Phase 2: Measurable Rules

Every rule module in this phase exposes the same entry point:

```python
def check(scene: Scene, tokens: DesignTokens) -> List[Finding]
```

Task 8 calls them in a fixed order. A module never prints, never exits, and never
hard-codes a threshold the token file already carries.

---

### Task 3: Geometry rules

**Files:**
- Create: `skills/report-slides/scripts/visual_style/geometry.py`
- Test: `skills/report-slides/scripts/tests/test_visual_style_geometry.py`

**Interfaces:**
- Consumes: `visual_style.scene.{Scene, Box, TextRun}` (Task 2);
  `visual_style.report.Finding` (Task 1); `design_tokens.DesignTokens` (plan 1,
  Task 2).
- Produces, imported by Task 8:
  - `RULES: Tuple[str, ...]` — `("safe-area", "element-overlap", "node-gap",
    "node-padding", "off-grid")`
  - `check(scene: Scene, tokens: DesignTokens) -> List[Finding]`
  - `check_safe_area`, `check_overlap`, `check_node_gap`, `check_node_padding`,
    `check_grid` — each with the same signature as `check`
  - `node_bounds(scene: Scene) -> Dict[str, Box]` — the union bounding box of
    each semantic node, reused by Task 6

**Which overlaps are intended.** A card containing an icon plate, and a label
sitting inside its own node, are both correct composition. The rule therefore
reports an overlap only when neither box contains the other *and* the two belong
to different semantic nodes. Two text runs overlapping is always a defect.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_visual_style_geometry.py`:

```python
"""Tests for the geometry rules."""

from __future__ import annotations

from typing import Optional

import pytest

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from fonts import vertical_metrics
from visual_style import geometry
from visual_style.scene import Box, Scene, TextRun


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _box(element_id: str, x: float, y: float, w: float, h: float,
         node_id: Optional[str] = None, bleed: bool = False) -> Box:
    """Build a plain box for rule testing."""
    return Box(element_id, "rect", x, y, w, h, "#f8fafc", "#475569", 1.5, 8,
               "node.primary", node_id, bleed)


def _text(element_id: str, x: float, y: float, width: float,
          node_id: Optional[str] = None, size: float = 18) -> TextRun:
    """Build a pre-measured text run for rule testing."""
    ascent, descent = vertical_metrics("DejaVu Sans", size)
    return TextRun(element_id, "Label", x, y, size, 600, "#374151", "start",
                   "node.label", node_id, 1, width, ascent, descent, 0.0)


def _scene(boxes=(), texts=()) -> Scene:
    """Build a scene from boxes and texts alone."""
    return Scene(1200, 675, tuple(boxes), tuple(texts), (), (), "DejaVu Sans")


def test_content_inside_the_safe_area_is_clean(tokens: DesignTokens) -> None:
    """A box well inside the margins produces no finding."""
    scene = _scene(boxes=[_box("b1", 100, 100, 200, 90)])
    assert geometry.check_safe_area(scene, tokens) == []


def test_content_past_the_right_margin_is_an_error(tokens: DesignTokens) -> None:
    """Safe area is 48 units; a box reaching 1160 breaks it."""
    scene = _scene(boxes=[_box("b1", 900, 100, 260, 90)])
    findings = geometry.check_safe_area(scene, tokens)
    assert [f.rule for f in findings] == ["safe-area"]
    assert findings[0].severity == "error"
    assert "1160" in findings[0].message


def test_bleed_elements_are_exempt_from_the_safe_area(tokens: DesignTokens) -> None:
    """A declared bleed element may run edge to edge."""
    scene = _scene(boxes=[_box("bar", 0, 0, 1200, 6, bleed=True)])
    assert geometry.check_safe_area(scene, tokens) == []


def test_text_past_the_bottom_margin_is_an_error(tokens: DesignTokens) -> None:
    """Text bounding boxes are checked, not just shapes."""
    scene = _scene(texts=[_text("t1", 100, 670, 120)])
    findings = geometry.check_safe_area(scene, tokens)
    assert [f.rule for f in findings] == ["safe-area"]
    assert findings[0].element_id == "t1"


def test_unrelated_boxes_that_overlap_are_an_error(tokens: DesignTokens) -> None:
    """Two nodes sharing pixels is a layout defect."""
    scene = _scene(boxes=[_box("b1", 100, 100, 200, 90, node_id="n1"),
                          _box("b2", 250, 120, 200, 90, node_id="n2")])
    findings = geometry.check_overlap(scene, tokens)
    assert [f.rule for f in findings] == ["element-overlap"]


def test_a_contained_box_is_intended_composition(tokens: DesignTokens) -> None:
    """An icon plate inside a card is not an overlap defect."""
    scene = _scene(boxes=[_box("card", 100, 100, 300, 200, node_id="n1"),
                          _box("plate", 120, 120, 40, 40, node_id="n1")])
    assert geometry.check_overlap(scene, tokens) == []


def test_a_label_inside_its_own_node_is_intended(tokens: DesignTokens) -> None:
    """A node label overlapping its own node box is correct."""
    scene = _scene(boxes=[_box("b1", 100, 100, 200, 90, node_id="n1")],
                   texts=[_text("t1", 120, 150, 120, node_id="n1")])
    assert geometry.check_overlap(scene, tokens) == []


def test_a_label_spilling_onto_another_node_is_an_error(
    tokens: DesignTokens,
) -> None:
    """A label crossing into a different node is a defect."""
    scene = _scene(boxes=[_box("b2", 300, 100, 200, 90, node_id="n2")],
                   texts=[_text("t1", 250, 150, 120, node_id="n1")])
    findings = geometry.check_overlap(scene, tokens)
    assert [f.rule for f in findings] == ["element-overlap"]


def test_two_overlapping_texts_are_always_an_error(tokens: DesignTokens) -> None:
    """Text on text is never intended, even inside one node."""
    scene = _scene(texts=[_text("t1", 100, 150, 200, node_id="n1"),
                          _text("t2", 180, 152, 200, node_id="n1")])
    findings = geometry.check_overlap(scene, tokens)
    assert [f.rule for f in findings] == ["element-overlap"]


def test_nodes_closer_than_the_minimum_gap_are_an_error(
    tokens: DesignTokens,
) -> None:
    """Default node_gap_min is 24; an 18-unit gap fails."""
    scene = _scene(boxes=[_box("b1", 100, 100, 200, 90, node_id="n1"),
                          _box("b2", 318, 100, 200, 90, node_id="n2")])
    findings = geometry.check_node_gap(scene, tokens)
    assert [f.rule for f in findings] == ["node-gap"]
    assert "18" in findings[0].message
    assert "24" in findings[0].message


def test_nodes_at_the_minimum_gap_are_clean(tokens: DesignTokens) -> None:
    """A gap exactly equal to the minimum passes."""
    scene = _scene(boxes=[_box("b1", 100, 100, 200, 90, node_id="n1"),
                          _box("b2", 324, 100, 200, 90, node_id="n2")])
    assert geometry.check_node_gap(scene, tokens) == []


def test_label_too_close_to_its_node_edge_is_an_error(
    tokens: DesignTokens,
) -> None:
    """Default node_padding is x=16, y=12; a 4-unit inset fails."""
    scene = _scene(boxes=[_box("b1", 100, 100, 200, 90, node_id="n1")],
                   texts=[_text("t1", 104, 150, 100, node_id="n1")])
    findings = geometry.check_node_padding(scene, tokens)
    assert [f.rule for f in findings] == ["node-padding"]
    assert findings[0].element_id == "t1"


def test_label_with_sufficient_padding_is_clean(tokens: DesignTokens) -> None:
    """A label inset past the padding minimum passes."""
    scene = _scene(boxes=[_box("b1", 100, 100, 200, 90, node_id="n1")],
                   texts=[_text("t1", 120, 150, 100, node_id="n1")])
    assert geometry.check_node_padding(scene, tokens) == []


def test_off_grid_geometry_is_a_warning(tokens: DesignTokens) -> None:
    """Default grid is 8; x=103 is 3 units off and warns."""
    scene = _scene(boxes=[_box("b1", 103, 100, 200, 88)])
    findings = geometry.check_grid(scene, tokens)
    assert [f.rule for f in findings] == ["off-grid"]
    assert findings[0].severity == "warning"
    assert "x" in findings[0].message


def test_grid_tolerance_absorbs_small_drift(tokens: DesignTokens) -> None:
    """A 2-unit deviation is within tolerance and does not warn."""
    scene = _scene(boxes=[_box("b1", 102, 100, 200, 88)])
    assert geometry.check_grid(scene, tokens) == []


def test_data_marks_are_exempt_from_the_grid(tokens: DesignTokens) -> None:
    """A bar's height encodes a value; the grid does not apply to it."""
    bar = Box("bar1", "rect", 103, 100, 40, 137, "#1e3a5f", None, 0, 0,
              "chart.bar", None, False)
    assert geometry.check_grid(_scene(boxes=[bar]), tokens) == []


def test_check_runs_every_geometry_rule(tokens: DesignTokens) -> None:
    """The module entry point aggregates all five rules."""
    scene = _scene(boxes=[_box("b1", 900, 100, 260, 90, node_id="n1"),
                          _box("b2", 1010, 120, 100, 50, node_id="n2")])
    rules = {f.rule for f in geometry.check(scene, tokens)}
    assert "safe-area" in rules
    assert "element-overlap" in rules
    assert set(geometry.RULES) == {
        "safe-area", "element-overlap", "node-gap", "node-padding", "off-grid",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_geometry.py -v`
Expected: FAIL — `ImportError: cannot import name 'geometry' from 'visual_style'`.

- [ ] **Step 3: Write the geometry rules**

Create `skills/report-slides/scripts/visual_style/geometry.py`:

```python
"""Geometry rules: safe area, overlap, node spacing, and grid alignment."""
from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Optional, Tuple

from design_tokens import DesignTokens

from .report import Finding
from .scene import Box, Scene, TextRun

RULES: Tuple[str, ...] = (
    "safe-area", "element-overlap", "node-gap", "node-padding", "off-grid",
)

_EDGE_TOLERANCE = 0.5
_GRID_TOLERANCE = 2.0


def _safe_bounds(scene: Scene, tokens: DesignTokens
                 ) -> Tuple[float, float, float, float]:
    """Return the safe-area rectangle as `(left, top, right, bottom)`.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        Absolute edge coordinates in SVG units.
    """
    safe = tokens.raw["canvas"]["safe_area"]
    return (float(safe["left"]), float(safe["top"]),
            scene.width - float(safe["right"]),
            scene.height - float(safe["bottom"]))


def check_safe_area(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report content that leaves the safe area without declaring bleed.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `safe-area` error per offending element.
    """
    left, top, right, bottom = _safe_bounds(scene, tokens)
    findings: List[Finding] = []
    candidates: List[Box] = [box for box in scene.boxes if not box.bleed]
    candidates.extend(run.bbox() for run in scene.texts)
    for box in candidates:
        breaches: List[str] = []
        if box.x < left - _EDGE_TOLERANCE:
            breaches.append(f"left {box.x:g} < {left:g}")
        if box.y < top - _EDGE_TOLERANCE:
            breaches.append(f"top {box.y:g} < {top:g}")
        if box.right > right + _EDGE_TOLERANCE:
            breaches.append(f"right {box.right:g} > {right:g}")
        if box.bottom > bottom + _EDGE_TOLERANCE:
            breaches.append(f"bottom {box.bottom:g} > {bottom:g}")
        if breaches:
            findings.append(Finding(
                rule="safe-area", severity="error",
                message=f"{box.element_id} leaves the safe area: "
                        + "; ".join(breaches),
                element_id=box.element_id, location=(box.x, box.y)))
    return findings


def _same_node(a: Box, b: Box) -> bool:
    """Return whether two boxes belong to the same semantic node.

    Args:
        a: First box.
        b: Second box.

    Returns:
        True when both carry the same non-null node id.
    """
    return a.node_id is not None and a.node_id == b.node_id


def _overlap_finding(first: str, second: str, x: float, y: float) -> Finding:
    """Build one overlap finding.

    Args:
        first: Identifier of the first element.
        second: Identifier of the second element.
        x: Report location x.
        y: Report location y.

    Returns:
        The finding.
    """
    return Finding(
        rule="element-overlap", severity="error",
        message=f"{first} overlaps {second} with neither containing the other",
        element_id=first, location=(x, y))


def check_overlap(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report unintended overlap between shapes and text.

    Containment is intended composition, as is a label inside its own node.
    Text overlapping text is never intended.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `element-overlap` error per offending pair.
    """
    del tokens
    findings: List[Finding] = []
    text_boxes = [(run, run.bbox()) for run in scene.texts]

    for a, b in combinations(scene.boxes, 2):
        if not a.intersects(b):
            continue
        if a.contains_box(b) or b.contains_box(a) or _same_node(a, b):
            continue
        findings.append(_overlap_finding(a.element_id, b.element_id, a.x, a.y))

    for run, bbox in text_boxes:
        for box in scene.boxes:
            if not bbox.intersects(box):
                continue
            if box.contains_box(bbox) or _same_node(bbox, box):
                continue
            findings.append(
                _overlap_finding(run.element_id, box.element_id, bbox.x, bbox.y))

    for (run_a, box_a), (run_b, box_b) in combinations(text_boxes, 2):
        if box_a.intersects(box_b):
            findings.append(_overlap_finding(
                run_a.element_id, run_b.element_id, box_a.x, box_a.y))
    return findings


def node_bounds(scene: Scene) -> Dict[str, Box]:
    """Return the union bounding box of each semantic node.

    Args:
        scene: The parsed slide.

    Returns:
        A mapping from node id to its union box.
    """
    bounds: Dict[str, Box] = {}
    for node_id, boxes in scene.nodes().items():
        left = min(box.x for box in boxes)
        top = min(box.y for box in boxes)
        right = max(box.right for box in boxes)
        bottom = max(box.bottom for box in boxes)
        bounds[node_id] = Box(node_id, "group", left, top, right - left,
                              bottom - top, None, None, 0.0, 0.0, None,
                              node_id, False)
    return bounds


def check_node_gap(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report node pairs closer than `spacing.node_gap_min`.

    Overlapping nodes are left to `element-overlap`; reporting both would
    double-count one defect.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `node-gap` error per offending pair.
    """
    minimum = float(tokens.raw["spacing"]["node_gap_min"])
    findings: List[Finding] = []
    bounds = node_bounds(scene)
    for (id_a, box_a), (id_b, box_b) in combinations(sorted(bounds.items()), 2):
        if box_a.intersects(box_b):
            continue
        gap = box_a.gap_to(box_b)
        if gap < minimum - _EDGE_TOLERANCE:
            findings.append(Finding(
                rule="node-gap", severity="error",
                message=f"nodes {id_a} and {id_b} are {gap:g} apart; "
                        f"spacing.node_gap_min is {minimum:g}",
                element_id=id_a, location=(box_a.right, box_a.y)))
    return findings


def _enclosing_box(run: TextRun, scene: Scene) -> Optional[Box]:
    """Return the smallest box of the run's own node that encloses its centre.

    Args:
        run: The text run.
        scene: The parsed slide.

    Returns:
        The enclosing box, or None when the run sits in no node box.
    """
    if run.node_id is None:
        return None
    bbox = run.bbox()
    cx = bbox.x + bbox.w / 2
    cy = bbox.y + bbox.h / 2
    candidates = [box for box in scene.boxes
                  if box.node_id == run.node_id and box.contains_point(cx, cy)]
    if not candidates:
        return None
    return min(candidates, key=lambda box: box.area)


def check_node_padding(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report labels inset less than `spacing.node_padding` from their node.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `node-padding` error per offending label.
    """
    padding = tokens.raw["spacing"]["node_padding"]
    pad_x = float(padding["x"])
    pad_y = float(padding["y"])
    findings: List[Finding] = []
    for run in scene.texts:
        host = _enclosing_box(run, scene)
        if host is None:
            continue
        bbox = run.bbox()
        insets = (
            ("left", bbox.x - host.x, pad_x),
            ("right", host.right - bbox.right, pad_x),
            ("top", bbox.y - host.y, pad_y),
            ("bottom", host.bottom - bbox.bottom, pad_y),
        )
        breaches = [
            f"{edge} inset {value:g} < {required:g}"
            for edge, value, required in insets
            if value < required - _EDGE_TOLERANCE
        ]
        if breaches:
            findings.append(Finding(
                rule="node-padding", severity="error",
                message=f"{run.element_id} inside {host.element_id}: "
                        + "; ".join(breaches),
                element_id=run.element_id, location=(bbox.x, bbox.y)))
    return findings


def _is_data_mark(box: Box) -> bool:
    """Return whether a box is a data mark rather than a laid-out element.

    A bar's height and a marker's position come from the value they encode, not
    from the layout grid. Holding them to `canvas.grid` would emit a warning per
    bar on every chart slide.

    Args:
        box: The box to classify.

    Returns:
        True for boxes whose style role marks them as chart geometry.
    """
    role = box.style_role or ""
    return role.startswith("chart") or role.startswith("mark")


def _grid_delta(value: float, grid: float) -> float:
    """Return the distance from a value to the nearest grid multiple.

    Args:
        value: The measured coordinate or extent.
        grid: The grid quantum.

    Returns:
        The absolute deviation in SVG units.
    """
    remainder = abs(value) % grid
    return min(remainder, grid - remainder)


def check_grid(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report box geometry that is not aligned to `canvas.grid`.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `off-grid` warning per offending box.
    """
    grid = float(tokens.raw["canvas"]["grid"])
    findings: List[Finding] = []
    for box in scene.boxes:
        if box.bleed or _is_data_mark(box):
            continue
        offenders = [
            f"{name}={value:g} (off by {_grid_delta(value, grid):g})"
            for name, value in (("x", box.x), ("y", box.y),
                                ("width", box.w), ("height", box.h))
            if _grid_delta(value, grid) > _GRID_TOLERANCE
        ]
        if offenders:
            findings.append(Finding(
                rule="off-grid", severity="warning",
                message=f"{box.element_id} is off the {grid:g}-unit grid: "
                        + ", ".join(offenders),
                element_id=box.element_id, location=(box.x, box.y)))
    return findings


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every geometry rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All geometry findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_safe_area(scene, tokens))
    findings.extend(check_overlap(scene, tokens))
    findings.extend(check_node_gap(scene, tokens))
    findings.extend(check_node_padding(scene, tokens))
    findings.extend(check_grid(scene, tokens))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_geometry.py -v`
Expected: PASS — 17 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/visual_style/geometry.py \
        skills/report-slides/scripts/tests/test_visual_style_geometry.py
git commit -m "feat(report-slides): add geometry rules for safe area, overlap, and spacing"
```

---

### Task 4: Typography rules

**Files:**
- Create: `skills/report-slides/scripts/visual_style/typography.py`
- Test: `skills/report-slides/scripts/tests/test_visual_style_typography.py`

**Interfaces:**
- Consumes: `visual_style.scene.{Scene, TextRun}` (Task 2);
  `visual_style.report.Finding` (Task 1); `design_tokens.{DesignTokens,
  TokenError}` (plan 1, Task 2).
- Produces, imported by Task 8:
  - `RULES: Tuple[str, ...]` — `("type-floor", "type-variety", "overlong-text")`
  - `BODY_WORD_BUDGET: int` — `90`
  - `check(scene: Scene, tokens: DesignTokens) -> List[Finding]`
  - `check_type_floor`, `check_type_variety`, `check_overlong_text` — each with
    the same signature as `check`

**Where the floor comes from.** A run's `data-style-role` names a typography
role; the floor is that role's declared `size`. A run with no declared role is
held to the smallest size in the token file — `footnote`, 12 by default — so
hand-authored SVG is still caught at the 10pt failure the spec documents (§2.2),
without pretending the linter knows which role the author intended.

A role name that is not in the token file is itself an error: it means the SVG
and the token contract disagree, and silently ignoring it would let any typo
disable the rule.

`BODY_WORD_BUDGET` is a module constant, not a token: the token contract
deliberately carries no word budget, and inventing a token for one number the
design system does not own would be worse than naming it here.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_visual_style_typography.py`:

```python
"""Tests for the typography rules."""

from __future__ import annotations

from typing import Optional

import pytest

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from fonts import vertical_metrics
from visual_style import typography
from visual_style.scene import Scene, TextRun


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _text(element_id: str, size: float, role: Optional[str] = "body",
          lines: int = 1, content: str = "Label") -> TextRun:
    """Build a pre-measured text run for rule testing."""
    ascent, descent = vertical_metrics("DejaVu Sans", size)
    return TextRun(element_id, content, 100, 200, size, 400, "#374151",
                   "start", role, None, lines, 120.0,
                   ascent, descent, size * 1.45 * (lines - 1))


def _scene(texts) -> Scene:
    """Build a text-only scene."""
    return Scene(1200, 675, (), tuple(texts), (), (), "DejaVu Sans")


def test_text_at_its_role_size_is_clean(tokens: DesignTokens) -> None:
    """Body is 21 by default; 21 passes."""
    assert typography.check_type_floor(_scene([_text("t1", 21)]), tokens) == []


def test_text_below_its_role_size_is_an_error(tokens: DesignTokens) -> None:
    """The 10pt body text the spec documents is caught."""
    findings = typography.check_type_floor(_scene([_text("t1", 10)]), tokens)
    assert [f.rule for f in findings] == ["type-floor"]
    assert findings[0].severity == "error"
    assert "10" in findings[0].message
    assert "21" in findings[0].message


def test_text_above_its_role_size_is_not_a_floor_violation(
    tokens: DesignTokens,
) -> None:
    """The rule is a floor, not an equality check."""
    assert typography.check_type_floor(_scene([_text("t1", 26)]), tokens) == []


def test_undeclared_role_falls_back_to_the_smallest_role(
    tokens: DesignTokens,
) -> None:
    """Without a role, footnote's 12 is the floor."""
    scene = _scene([_text("t1", 10, role=None), _text("t2", 12, role=None)])
    findings = typography.check_type_floor(scene, tokens)
    assert [f.element_id for f in findings] == ["t1"]
    assert "no declared style role" in findings[0].message


def test_unknown_role_is_an_error(tokens: DesignTokens) -> None:
    """A role absent from the token file is a contract mismatch."""
    findings = typography.check_type_floor(
        _scene([_text("t1", 21, role="node.headline")]), tokens)
    assert [f.rule for f in findings] == ["type-floor"]
    assert "node.headline" in findings[0].message


def test_dotted_roles_resolve_to_their_typography_role(
    tokens: DesignTokens,
) -> None:
    """`node.label` resolves to the `node_label` typography role."""
    findings = typography.check_type_floor(
        _scene([_text("t1", 14, role="node.label")]), tokens)
    assert [f.rule for f in findings] == ["type-floor"]
    assert "18" in findings[0].message


def test_size_count_within_budget_is_clean(tokens: DesignTokens) -> None:
    """Default max_sizes_per_slide is 4."""
    scene = _scene([_text(f"t{i}", size)
                    for i, size in enumerate([32, 21, 18, 16])])
    assert typography.check_type_variety(scene, tokens) == []


def test_too_many_distinct_sizes_is_a_warning(tokens: DesignTokens) -> None:
    """A fifth distinct size warns."""
    scene = _scene([_text(f"t{i}", size)
                    for i, size in enumerate([32, 26, 21, 18, 16])])
    findings = typography.check_type_variety(scene, tokens)
    assert [f.rule for f in findings] == ["type-variety"]
    assert findings[0].severity == "warning"
    assert "5" in findings[0].message


def test_title_over_its_line_budget_is_a_warning(tokens: DesignTokens) -> None:
    """slide_title allows 2 lines by default."""
    scene = _scene([_text("t1", 32, role="slide_title", lines=3)])
    findings = typography.check_overlong_text(scene, tokens)
    assert [f.rule for f in findings] == ["overlong-text"]
    assert "3 lines" in findings[0].message


def test_node_label_over_its_line_budget_is_a_warning(
    tokens: DesignTokens,
) -> None:
    """node_label allows 3 lines by default."""
    scene = _scene([_text("t1", 18, role="node_label", lines=4)])
    findings = typography.check_overlong_text(scene, tokens)
    assert [f.rule for f in findings] == ["overlong-text"]


def test_body_over_the_word_budget_is_a_warning(tokens: DesignTokens) -> None:
    """Body prose beyond BODY_WORD_BUDGET words warns."""
    prose = " ".join(["word"] * (typography.BODY_WORD_BUDGET + 1))
    scene = _scene([_text("t1", 21, role="body", lines=8, content=prose)])
    findings = typography.check_overlong_text(scene, tokens)
    assert [f.rule for f in findings] == ["overlong-text"]
    assert str(typography.BODY_WORD_BUDGET) in findings[0].message


def test_body_within_the_word_budget_is_clean(tokens: DesignTokens) -> None:
    """A body run at the budget passes."""
    prose = " ".join(["word"] * typography.BODY_WORD_BUDGET)
    scene = _scene([_text("t1", 21, role="body", lines=8, content=prose)])
    assert typography.check_overlong_text(scene, tokens) == []


def test_check_runs_every_typography_rule(tokens: DesignTokens) -> None:
    """The module entry point aggregates all three rules."""
    scene = _scene([_text("t1", 10), _text("t2", 26), _text("t3", 18),
                    _text("t4", 16), _text("t5", 32)])
    rules = {f.rule for f in typography.check(scene, tokens)}
    assert rules == {"type-floor", "type-variety"}
    assert set(typography.RULES) == {
        "type-floor", "type-variety", "overlong-text",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_typography.py -v`
Expected: FAIL — `ImportError: cannot import name 'typography' from 'visual_style'`.

- [ ] **Step 3: Write the typography rules**

Create `skills/report-slides/scripts/visual_style/typography.py`:

```python
"""Typography rules: size floors, size variety, and text length budgets."""
from __future__ import annotations

from typing import List, Optional, Tuple

from design_tokens import DesignTokens, TokenError, TypeRole

from .report import Finding
from .scene import Scene, TextRun

RULES: Tuple[str, ...] = ("type-floor", "type-variety", "overlong-text")

BODY_WORD_BUDGET = 90
_SIZE_TOLERANCE = 0.5


def _role_name(run: TextRun) -> Optional[str]:
    """Map a run's style role onto a typography role name.

    Authoring roles are dotted, such as `node.label`; typography roles are
    underscored, such as `node_label`. A single-segment role is used as is.

    Args:
        run: The text run.

    Returns:
        The typography role name, or None when the run declares no role.
    """
    if not run.style_role:
        return None
    return run.style_role.replace(".", "_")


def _smallest_role(tokens: DesignTokens) -> Tuple[str, float]:
    """Return the smallest declared typography role and its size.

    Args:
        tokens: The resolved token set.

    Returns:
        `(role_name, size)` for the smallest role.
    """
    roles = tokens.raw["typography"]["roles"]
    name = min(roles, key=lambda key: float(roles[key]["size"]))
    return name, float(roles[name]["size"])


def check_type_floor(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report text rendered below the floor its role sets.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `type-floor` error per offending run.
    """
    fallback_name, fallback_size = _smallest_role(tokens)
    findings: List[Finding] = []
    for run in scene.texts:
        name = _role_name(run)
        if name is None:
            if run.size < fallback_size - _SIZE_TOLERANCE:
                findings.append(Finding(
                    rule="type-floor", severity="error",
                    message=f"{run.element_id} is {run.size:g} with no declared "
                            f"style role; the smallest role {fallback_name} is "
                            f"{fallback_size:g}",
                    element_id=run.element_id, location=(run.x, run.y)))
            continue
        try:
            role: TypeRole = tokens.type_role(name)
        except TokenError:
            findings.append(Finding(
                rule="type-floor", severity="error",
                message=f"{run.element_id} declares style role "
                        f"{run.style_role!r}, which resolves to {name!r} and is "
                        f"not defined in the token file",
                element_id=run.element_id, location=(run.x, run.y)))
            continue
        if run.size < role.size - _SIZE_TOLERANCE:
            findings.append(Finding(
                rule="type-floor", severity="error",
                message=f"{run.element_id} is {run.size:g}; role {name} "
                        f"requires at least {role.size:g}",
                element_id=run.element_id, location=(run.x, run.y)))
    return findings


def check_type_variety(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report slides using more distinct sizes than the token budget allows.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        At most one `type-variety` warning.
    """
    budget = int(tokens.raw["typography"]["max_sizes_per_slide"])
    sizes = sorted({round(run.size, 2) for run in scene.texts})
    if len(sizes) <= budget:
        return []
    rendered = ", ".join(f"{size:g}" for size in sizes)
    return [Finding(
        rule="type-variety", severity="warning",
        message=f"slide uses {len(sizes)} distinct font sizes ({rendered}); "
                f"typography.max_sizes_per_slide is {budget}")]


def check_overlong_text(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report text exceeding its line budget or the body word budget.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `overlong-text` warning per offending run.
    """
    findings: List[Finding] = []
    for run in scene.texts:
        name = _role_name(run)
        if name is None:
            continue
        try:
            role = tokens.type_role(name)
        except TokenError:
            # Unknown roles are already reported by check_type_floor; reporting
            # them twice would inflate one defect into two.
            continue
        if run.line_count > role.max_lines:
            findings.append(Finding(
                rule="overlong-text", severity="warning",
                message=f"{run.element_id} runs to {run.line_count} lines; "
                        f"role {name} allows {role.max_lines}",
                element_id=run.element_id, location=(run.x, run.y)))
        if name == "body":
            words = len(run.text.split())
            if words > BODY_WORD_BUDGET:
                findings.append(Finding(
                    rule="overlong-text", severity="warning",
                    message=f"{run.element_id} carries {words} words; the body "
                            f"budget is {BODY_WORD_BUDGET}",
                    element_id=run.element_id, location=(run.x, run.y)))
    return findings


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every typography rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All typography findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_type_floor(scene, tokens))
    findings.extend(check_type_variety(scene, tokens))
    findings.extend(check_overlong_text(scene, tokens))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_typography.py -v`
Expected: PASS — 13 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/visual_style/typography.py \
        skills/report-slides/scripts/tests/test_visual_style_typography.py
git commit -m "feat(report-slides): add typography rules for size floors and budgets"
```

---

### Task 5: Colour and contrast rules

**Files:**
- Create: `skills/report-slides/scripts/visual_style/color.py`
- Test: `skills/report-slides/scripts/tests/test_visual_style_color.py`

**Interfaces:**
- Consumes: `visual_style.scene.{Scene, Box, TextRun}` (Task 2);
  `visual_style.report.Finding` (Task 1); `design_tokens.DesignTokens` (plan 1,
  Task 2).
- Produces, imported by Tasks 7 and 8:
  - `RULES: Tuple[str, ...]` — `("text-contrast", "graphic-contrast",
    "token-color")`
  - `normalize_hex(value: str) -> Optional[str]`
  - `relative_luminance(hex_color: str) -> float`
  - `contrast_ratio(a: str, b: str) -> float`
  - `color_role(hex_color: str, tokens: DesignTokens) -> Optional[str]`
  - `background_at(x: float, y: float, scene: Scene, tokens: DesignTokens,
    exclude: Optional[str] = None) -> str`
  - `check(scene: Scene, tokens: DesignTokens) -> List[Finding]`
  - `check_text_contrast`, `check_graphic_contrast`, `check_token_colors` —
    each with the same signature as `check`

**How the background is resolved.** A colour has no contrast on its own. For any
point, the background is the fill of the smallest filled box containing it,
excluding the element being judged; when no box contains it, the background is
`color.roles.bg`. This is what makes the rule measurable without rendering.

**Which colours are exempt.** Decorativeness is a property of the *colour*, not
of the shape: the linter reverse-maps a hex to its `color.roles` key and
consults `tokens.is_decorative`. A `#e2e8f0` divider is exempt from the graphic
floor because `divider` is listed in `color.decorative_roles`; the same hex used
as body text is not exempt from the text floor, because text is never
decorative.

**Large text** follows WCAG: at least 24 units, or at least 18.66 units at
weight 700 or above. Those runs are held to `contrast.large_text_min`.

Verified against the default palette (all ratios computed with the WCAG formula
against `#ffffff`): `#374151` 10.31, `#475569` 7.58, `#64748b` 4.76,
`#e2e8f0` 1.23, `#94a3b8` 2.56.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_visual_style_color.py`:

```python
"""Tests for the colour and contrast rules."""

from __future__ import annotations

from typing import Optional

import pytest

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from fonts import vertical_metrics
from visual_style import color
from visual_style.scene import Box, Scene, TextRun


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _box(element_id: str, fill: Optional[str], stroke: Optional[str] = None,
         x: float = 100, y: float = 100, w: float = 200, h: float = 100) -> Box:
    """Build a box with the given paint for rule testing."""
    return Box(element_id, "rect", x, y, w, h, fill, stroke, 1.5, 8,
               "node.primary", None, False)


def _text(element_id: str, fill: str, size: float = 21,
          weight: int = 400, x: float = 120, y: float = 150) -> TextRun:
    """Build a text run with the given paint for rule testing."""
    ascent, descent = vertical_metrics("DejaVu Sans", size)
    return TextRun(element_id, "Label", x, y, size, weight, fill, "start",
                   "body", None, 1, 80.0, ascent, descent, 0.0)


def _scene(boxes=(), texts=()) -> Scene:
    """Build a scene from boxes and texts alone."""
    return Scene(1200, 675, tuple(boxes), tuple(texts), (), (), "DejaVu Sans")


def test_contrast_ratio_matches_the_wcag_formula() -> None:
    """Black on white is 21:1 and a colour against itself is 1:1."""
    assert color.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert color.contrast_ratio("#374151", "#374151") == pytest.approx(1.0, abs=1e-9)
    assert color.contrast_ratio("#374151", "#ffffff") == pytest.approx(10.31, abs=0.01)
    assert color.contrast_ratio("#ffffff", "#374151") == pytest.approx(10.31, abs=0.01)


def test_normalize_hex_expands_shorthand_and_resolves_names() -> None:
    """Shorthand expands and CSS names resolve; non-colours return None."""
    assert color.normalize_hex("#FFF") == "#ffffff"
    assert color.normalize_hex("#1E3A5F") == "#1e3a5f"
    assert color.normalize_hex("white") == "#ffffff"
    assert color.normalize_hex("WHITE") == "#ffffff"
    assert color.normalize_hex("none") is None
    assert color.normalize_hex("transparent") is None
    assert color.normalize_hex("url(#grad1)") is None


def test_named_white_text_is_still_contrast_checked(
    tokens: DesignTokens,
) -> None:
    """fill="white" on a white ground must not slip through as "not a colour"."""
    scene = _scene(texts=[_text("t1", "white")])
    findings = color.check_text_contrast(scene, tokens)
    assert [f.rule for f in findings] == ["text-contrast"]
    assert "1.00" in findings[0].message


def test_color_role_reverse_maps_a_hex(tokens: DesignTokens) -> None:
    """A palette hex resolves back to its role name."""
    assert color.color_role("#e2e8f0", tokens) == "divider"
    assert color.color_role("#94a3b8", tokens) is None


def test_background_defaults_to_the_bg_role(tokens: DesignTokens) -> None:
    """A point over nothing sits on the canvas background."""
    assert color.background_at(600, 600, _scene(), tokens) == "#ffffff"


def test_background_uses_the_smallest_containing_box(
    tokens: DesignTokens,
) -> None:
    """A card over a panel gives the card's fill."""
    scene = _scene(boxes=[_box("panel", "#e2e8f0", x=50, y=50, w=600, h=400),
                          _box("card", "#f8fafc", x=100, y=100, w=200, h=100)])
    assert color.background_at(150, 150, scene, tokens) == "#f8fafc"


def test_body_text_on_white_passes(tokens: DesignTokens) -> None:
    """#374151 on white is 10.31, above the 4.5 floor."""
    scene = _scene(texts=[_text("t1", "#374151")])
    assert color.check_text_contrast(scene, tokens) == []


def test_low_contrast_text_is_an_error(tokens: DesignTokens) -> None:
    """#e2e8f0 on white is 1.23 and fails the text floor."""
    scene = _scene(texts=[_text("t1", "#e2e8f0")])
    findings = color.check_text_contrast(scene, tokens)
    assert [f.rule for f in findings] == ["text-contrast"]
    assert findings[0].severity == "error"
    assert "1.23" in findings[0].message
    assert "4.5" in findings[0].message


def test_large_text_uses_the_relaxed_floor(tokens: DesignTokens) -> None:
    """#94a3b8 on white is 2.56: fails at 21, still fails at 32."""
    small = _scene(texts=[_text("t1", "#94a3b8", size=21)])
    large = _scene(texts=[_text("t1", "#94a3b8", size=32)])
    assert len(color.check_text_contrast(small, tokens)) == 1
    assert "4.5" in color.check_text_contrast(small, tokens)[0].message
    assert "3.0" in color.check_text_contrast(large, tokens)[0].message


def test_bold_text_at_1866_counts_as_large(tokens: DesignTokens) -> None:
    """WCAG treats bold text at 18.66 units and above as large."""
    scene = _scene(texts=[_text("t1", "#94a3b8", size=19, weight=700)])
    findings = color.check_text_contrast(scene, tokens)
    assert "3.0" in findings[0].message


def test_text_contrast_is_measured_against_its_own_card(
    tokens: DesignTokens,
) -> None:
    """A label on a card is compared with the card, not the canvas."""
    scene = _scene(boxes=[_box("card", "#1e3a5f")],
                   texts=[_text("t1", "#374151")])
    findings = color.check_text_contrast(scene, tokens)
    assert [f.rule for f in findings] == ["text-contrast"]


def test_node_stroke_below_the_graphic_floor_is_an_error(
    tokens: DesignTokens,
) -> None:
    """#94a3b8 on white is 2.56, below the 3.0 graphic floor."""
    scene = _scene(boxes=[_box("b1", "#ffffff", stroke="#94a3b8")])
    findings = color.check_graphic_contrast(scene, tokens)
    assert [f.rule for f in findings] == ["graphic-contrast"]
    assert "2.56" in findings[0].message


def test_decorative_colours_are_exempt_from_the_graphic_floor(
    tokens: DesignTokens,
) -> None:
    """A #e2e8f0 divider is 1.23 but is a declared decorative role."""
    scene = _scene(boxes=[_box("d1", "#ffffff", stroke="#e2e8f0")])
    assert color.check_graphic_contrast(scene, tokens) == []


def test_palette_colours_are_accepted(tokens: DesignTokens) -> None:
    """Role colours and chart palette entries are in the design system."""
    scene = _scene(boxes=[_box("b1", "#f8fafc", stroke="#475569"),
                          _box("b2", "#0f766e")],
                   texts=[_text("t1", "#374151")])
    assert color.check_token_colors(scene, tokens) == []


def test_off_palette_colour_is_an_error(tokens: DesignTokens) -> None:
    """A colour absent from the token file is reported once per element."""
    scene = _scene(boxes=[_box("b1", "#ff00aa")])
    findings = color.check_token_colors(scene, tokens)
    assert [f.rule for f in findings] == ["token-color"]
    assert "#ff00aa" in findings[0].message
    assert findings[0].element_id == "b1"


def test_none_and_gradient_paints_are_not_colour_violations(
    tokens: DesignTokens,
) -> None:
    """Unfilled shapes and gradient references are out of this rule's scope."""
    scene = _scene(boxes=[_box("b1", "none", stroke="url(#grad1)")])
    assert color.check_token_colors(scene, tokens) == []


def test_check_runs_every_colour_rule(tokens: DesignTokens) -> None:
    """The module entry point aggregates all three rules."""
    scene = _scene(boxes=[_box("b1", "#ffffff", stroke="#94a3b8")],
                   texts=[_text("t1", "#e2e8f0")])
    rules = {f.rule for f in color.check(scene, tokens)}
    assert rules == {"text-contrast", "graphic-contrast", "token-color"}
    assert set(color.RULES) == {
        "text-contrast", "graphic-contrast", "token-color",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_color.py -v`
Expected: FAIL — `ImportError: cannot import name 'color' from 'visual_style'`.

- [ ] **Step 3: Write the colour rules**

Create `skills/report-slides/scripts/visual_style/color.py`:

```python
"""Colour rules: WCAG contrast floors and design-system palette conformance."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PIL import ImageColor

from design_tokens import DesignTokens

from .report import Finding
from .scene import Box, Scene

RULES: Tuple[str, ...] = ("text-contrast", "graphic-contrast", "token-color")

_NON_COLOURS = frozenset({"none", "transparent", "currentcolor"})
_LARGE_SIZE = 24.0
_LARGE_BOLD_SIZE = 18.66
_BOLD_WEIGHT = 700


def normalize_hex(value: Optional[str]) -> Optional[str]:
    """Normalise an SVG paint value to a six-digit lowercase hex.

    Named colours are resolved, because the existing SVG in this repository uses
    `fill="white"` freely. Treating a named colour as "not a colour" would
    silently exempt it from every contrast rule, which is the failure mode this
    linter exists to remove. Pillow's `ImageColor` is used rather than the
    converter's `CSS_COLORS` table so that the linter does not acquire a
    python-pptx dependency; Pillow is already required for font metrics.

    Args:
        value: The raw paint value, such as `#FFF`, `white`, `rgb(0,0,0)`,
            `none`, or `url(#g)`.

    Returns:
        The normalised hex, or None when the value names no literal colour —
        `none`, `transparent`, `currentColor`, or a paint-server reference.
    """
    if not value:
        return None
    text = value.strip().lower()
    if text in _NON_COLOURS:
        return None
    try:
        rgb = ImageColor.getrgb(text)
    except ValueError:
        # A paint-server reference such as url(#grad1) names no single colour;
        # gradient conformance is out of this rule's scope by design.
        return None
    return "#{:02x}{:02x}{:02x}".format(*rgb[:3])


def _channel_luminance(channel: float) -> float:
    """Linearise one sRGB channel per WCAG 2.x.

    Args:
        channel: Channel value in the range 0..1.

    Returns:
        The linearised channel value.
    """
    if channel <= 0.03928:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """Return the WCAG relative luminance of a colour.

    Args:
        hex_color: A normalised six-digit hex colour.

    Returns:
        Relative luminance in the range 0..1.

    Raises:
        ValueError: If the colour is not a normalisable hex value.
    """
    normalised = normalize_hex(hex_color)
    if normalised is None:
        raise ValueError(f"cannot compute luminance of {hex_color!r}")
    channels = [int(normalised[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [_channel_luminance(channel) for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(a: str, b: str) -> float:
    """Return the WCAG contrast ratio between two colours.

    Args:
        a: First colour.
        b: Second colour.

    Returns:
        A ratio in the range 1.0..21.0.

    Raises:
        ValueError: If either colour is not a normalisable hex value.
    """
    lum_a = relative_luminance(a)
    lum_b = relative_luminance(b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def _role_index(tokens: DesignTokens) -> Dict[str, str]:
    """Build a hex-to-role-name index over the colour roles.

    Args:
        tokens: The resolved token set.

    Returns:
        A mapping from normalised hex to role name.
    """
    index: Dict[str, str] = {}
    for role, value in tokens.raw["color"]["roles"].items():
        normalised = normalize_hex(str(value))
        if normalised is not None:
            index.setdefault(normalised, role)
    return index


def color_role(hex_color: str, tokens: DesignTokens) -> Optional[str]:
    """Reverse-map a colour to its `color.roles` key.

    Args:
        hex_color: The colour to look up.
        tokens: The resolved token set.

    Returns:
        The role name, or None when the colour is not a role colour.
    """
    normalised = normalize_hex(hex_color)
    if normalised is None:
        return None
    return _role_index(tokens).get(normalised)


def _palette(tokens: DesignTokens) -> Dict[str, str]:
    """Return every colour the design system declares.

    Args:
        tokens: The resolved token set.

    Returns:
        A mapping from normalised hex to a human-readable source label.
    """
    palette: Dict[str, str] = {}
    for role, value in tokens.raw["color"]["roles"].items():
        normalised = normalize_hex(str(value))
        if normalised is not None:
            palette.setdefault(normalised, f"color.roles.{role}")
    for position, value in enumerate(tokens.raw["chart"]["palette"]):
        normalised = normalize_hex(str(value))
        if normalised is not None:
            palette.setdefault(normalised, f"chart.palette[{position}]")
    return palette


def background_at(x: float, y: float, scene: Scene, tokens: DesignTokens,
                  exclude: Optional[str] = None) -> str:
    """Return the effective background colour at a point.

    Args:
        x: Point x coordinate.
        y: Point y coordinate.
        scene: The parsed slide.
        tokens: The resolved token set.
        exclude: Element id to ignore, so an element is not its own background.

    Returns:
        A normalised hex colour; `color.roles.bg` when nothing covers the point.
    """
    covering: List[Box] = [
        box for box in scene.boxes
        if box.element_id != exclude
        and box.contains_point(x, y)
        and normalize_hex(box.fill) is not None
    ]
    if covering:
        smallest = min(covering, key=lambda box: box.area)
        normalised = normalize_hex(smallest.fill)
        if normalised is not None:
            return normalised
    fallback = normalize_hex(tokens.color("bg"))
    if fallback is None:
        raise ValueError("color.roles.bg is not a literal hex colour")
    return fallback


def _is_large_text(size: float, weight: int) -> bool:
    """Return whether a run qualifies as WCAG large text.

    Args:
        size: Font size in SVG units.
        weight: Numeric font weight.

    Returns:
        True for large text.
    """
    if size >= _LARGE_SIZE:
        return True
    return weight >= _BOLD_WEIGHT and size >= _LARGE_BOLD_SIZE


def check_text_contrast(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report text below its WCAG contrast floor.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `text-contrast` error per offending run.
    """
    contrast = tokens.raw["color"]["contrast"]
    findings: List[Finding] = []
    for run in scene.texts:
        foreground = normalize_hex(run.fill)
        if foreground is None:
            continue
        bbox = run.bbox()
        background = background_at(bbox.x + bbox.w / 2, bbox.y + bbox.h / 2,
                                   scene, tokens, exclude=run.element_id)
        large = _is_large_text(run.size, run.weight)
        floor = float(contrast["large_text_min" if large else "text_min"])
        ratio = contrast_ratio(foreground, background)
        if ratio < floor:
            findings.append(Finding(
                rule="text-contrast", severity="error",
                message=f"{run.element_id} is {foreground} on {background} at "
                        f"{ratio:.2f}:1; the "
                        f"{'large text' if large else 'text'} floor is "
                        f"{floor:.1f}",
                element_id=run.element_id, location=(run.x, run.y)))
    return findings


def check_graphic_contrast(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report non-decorative graphics below the WCAG non-text floor.

    The judged colour is the stroke when a shape has one, otherwise the fill:
    an outlined node is read by its outline.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `graphic-contrast` error per offending shape.
    """
    floor = float(tokens.raw["color"]["contrast"]["graphic_min"])
    findings: List[Finding] = []
    for box in scene.boxes:
        paint = normalize_hex(box.stroke) or normalize_hex(box.fill)
        if paint is None:
            continue
        role = color_role(paint, tokens)
        if role is not None and tokens.is_decorative(role):
            continue
        background = background_at(box.x + box.w / 2, box.y + box.h / 2,
                                   scene, tokens, exclude=box.element_id)
        ratio = contrast_ratio(paint, background)
        if ratio < floor:
            findings.append(Finding(
                rule="graphic-contrast", severity="error",
                message=f"{box.element_id} is {paint} on {background} at "
                        f"{ratio:.2f}:1; the graphic floor is {floor:.1f}",
                element_id=box.element_id, location=(box.x, box.y)))
    return findings


def check_token_colors(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report colours that are not declared anywhere in the token file.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `token-color` error per offending element.
    """
    palette = _palette(tokens)
    findings: List[Finding] = []
    used: List[Tuple[str, str, float, float]] = []
    for box in scene.boxes:
        for paint in (box.fill, box.stroke):
            normalised = normalize_hex(paint)
            if normalised is not None:
                used.append((box.element_id, normalised, box.x, box.y))
    for run in scene.texts:
        normalised = normalize_hex(run.fill)
        if normalised is not None:
            used.append((run.element_id, normalised, run.x, run.y))
    for element_id, paint, x, y in used:
        if paint in palette:
            continue
        findings.append(Finding(
            rule="token-color", severity="error",
            message=f"{element_id} uses {paint}, which is in neither "
                    f"color.roles nor chart.palette",
            element_id=element_id, location=(x, y)))
    return findings


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every colour rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All colour findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_text_contrast(scene, tokens))
    findings.extend(check_graphic_contrast(scene, tokens))
    findings.extend(check_token_colors(scene, tokens))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_color.py -v`
Expected: PASS — 17 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/visual_style/color.py \
        skills/report-slides/scripts/tests/test_visual_style_color.py
git commit -m "feat(report-slides): add WCAG contrast and palette conformance rules"
```

---

### Task 6: Connector rules

**Files:**
- Create: `skills/report-slides/scripts/visual_style/connectors.py`
- Test: `skills/report-slides/scripts/tests/test_visual_style_connectors.py`

**Interfaces:**
- Consumes: `visual_style.scene.{Scene, Box, Connector, Polygon}` (Task 2);
  `visual_style.report.Finding` (Task 1); `visual_style.geometry.node_bounds`
  (Task 3); `design_tokens.DesignTokens` (plan 1, Task 2).
- Produces, imported by Task 8:
  - `RULES: Tuple[str, ...]` — `("connector-dangling", "connector-port-drift",
    "connector-through-node", "connector-clearance", "hand-drawn-arrow",
    "connector-crossing")`
  - `ATTACH_TOLERANCE: float` — `4.0`
  - `ARROW_PROXIMITY: float` — `12.0`
  - `edge_distance(px: float, py: float, box: Box) -> float`
  - `segment_box_distance(x1, y1, x2, y2, box: Box) -> float`
  - `segment_crosses_box(x1, y1, x2, y2, box: Box) -> bool`
  - `segments_cross(a: Connector, b: Connector) -> bool`
  - `check(scene: Scene, tokens: DesignTokens) -> List[Finding]`
  - `check_dangling`, `check_port_drift`, `check_through_node`,
    `check_clearance`, `check_hand_drawn_arrows`, `check_crossings` — each with
    the same signature as `check`

**Why `hand-drawn-arrow` is a hard error.** Spec §2.5 documents that
`marker-end` is silently dropped by the PPTX exporter, so authors have been
drawing arrowheads as filled triangles. Plan 1 Task 12 makes `marker-end`
export natively; this rule stops the workaround coming back, because a polygon
arrowhead does not move when the connector is edited in PowerPoint. A triangle
near a connector endpoint is the signature.

**Why `connector-crossing` is a warning, not an error.** Some graphs genuinely
cannot be drawn planar. One crossing is a fact about the graph; several are
usually a fact about the layout, so the rule fires above one and hands the
judgement to the art-direction reviewer (Task 10).

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_visual_style_connectors.py`:

```python
"""Tests for the connector rules."""

from __future__ import annotations

from typing import Optional

import pytest

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from visual_style import connectors
from visual_style.scene import Box, Connector, Polygon, Scene


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _box(node_id: str, x: float, y: float, w: float = 200,
         h: float = 90) -> Box:
    """Build a node box for rule testing."""
    return Box(f"rect-{node_id}", "rect", x, y, w, h, "#f8fafc", "#475569",
               1.5, 8, "node.primary", node_id, False)


def _conn(element_id: str, x1: float, y1: float, x2: float, y2: float,
          from_node: Optional[str] = None, to_node: Optional[str] = None,
          has_tail: bool = True) -> Connector:
    """Build a connector for rule testing."""
    return Connector(element_id, x1, y1, x2, y2, "#475569", 2.0, False,
                     has_tail, None, from_node, to_node)


def _scene(boxes=(), conns=(), polys=()) -> Scene:
    """Build a scene from boxes, connectors, and polygons."""
    return Scene(1200, 675, tuple(boxes), (), tuple(conns), tuple(polys),
                 "DejaVu Sans")


_A = _box("n1", 100, 100)
_B = _box("n2", 500, 100)


def test_edge_distance_is_zero_on_the_boundary() -> None:
    """A point on an edge is at distance zero."""
    assert connectors.edge_distance(300, 145, _A) == pytest.approx(0.0)


def test_edge_distance_measures_inward_and_outward() -> None:
    """Inside and outside points both measure to the nearest edge."""
    assert connectors.edge_distance(310, 145, _A) == pytest.approx(10.0)
    assert connectors.edge_distance(290, 145, _A) == pytest.approx(10.0)


def test_connector_attached_at_both_ends_is_clean(tokens: DesignTokens) -> None:
    """A connector touching both node boundaries is well formed."""
    scene = _scene(boxes=[_A, _B], conns=[_conn("c1", 300, 145, 500, 145)])
    assert connectors.check_dangling(scene, tokens) == []


def test_connector_touching_nothing_is_dangling(tokens: DesignTokens) -> None:
    """An endpoint in empty space is a dangling connector."""
    scene = _scene(boxes=[_A, _B], conns=[_conn("c1", 300, 145, 420, 400)])
    findings = connectors.check_dangling(scene, tokens)
    assert [f.rule for f in findings] == ["connector-dangling"]
    assert "end" in findings[0].message


def test_declared_node_that_does_not_exist_is_dangling(
    tokens: DesignTokens,
) -> None:
    """A connector naming an absent node cannot be resolved."""
    scene = _scene(boxes=[_A], conns=[_conn("c1", 300, 145, 500, 145,
                                            from_node="n1", to_node="n9")])
    findings = connectors.check_dangling(scene, tokens)
    assert [f.rule for f in findings] == ["connector-dangling"]
    assert "n9" in findings[0].message


def test_endpoint_on_its_declared_port_is_clean(tokens: DesignTokens) -> None:
    """An endpoint on the declared node's boundary does not drift."""
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 300, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    assert connectors.check_port_drift(scene, tokens) == []


def test_endpoint_far_from_its_declared_port_is_an_error(
    tokens: DesignTokens,
) -> None:
    """ATTACH_TOLERANCE is 4; a 12-unit drift fails."""
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 312, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    findings = connectors.check_port_drift(scene, tokens)
    assert [f.rule for f in findings] == ["connector-port-drift"]
    assert "12" in findings[0].message


def test_connector_crossing_an_unrelated_node_is_an_error(
    tokens: DesignTokens,
) -> None:
    """A line ploughing through a third node is a routing defect."""
    middle = _box("n3", 330, 120, 100, 50)
    scene = _scene(boxes=[_A, _B, middle],
                   conns=[_conn("c1", 300, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    findings = connectors.check_through_node(scene, tokens)
    assert [f.rule for f in findings] == ["connector-through-node"]
    assert "n3" in findings[0].message


def test_connector_entering_its_own_endpoints_is_not_a_defect(
    tokens: DesignTokens,
) -> None:
    """A connector may touch the nodes it joins."""
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 290, 145, 510, 145,
                                from_node="n1", to_node="n2")])
    assert connectors.check_through_node(scene, tokens) == []


def test_connector_too_close_to_an_unrelated_node_is_an_error(
    tokens: DesignTokens,
) -> None:
    """Default connector_clearance_min is 12; a 6-unit pass fails."""
    below = _box("n3", 330, 151, 100, 50)
    scene = _scene(boxes=[_A, _B, below],
                   conns=[_conn("c1", 300, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    findings = connectors.check_clearance(scene, tokens)
    assert [f.rule for f in findings] == ["connector-clearance"]
    assert "12" in findings[0].message


def test_sufficient_clearance_is_clean(tokens: DesignTokens) -> None:
    """A node 20 units clear of the line passes."""
    below = _box("n3", 330, 165, 100, 50)
    scene = _scene(boxes=[_A, _B, below],
                   conns=[_conn("c1", 300, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    assert connectors.check_clearance(scene, tokens) == []


def test_triangle_near_a_connector_endpoint_is_an_error(
    tokens: DesignTokens,
) -> None:
    """A polygon arrowhead is the workaround this rule exists to stop."""
    head = Polygon("p1", ((500, 145), (488, 139), (488, 151)), "#475569", None)
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 300, 145, 500, 145, has_tail=False)],
                   polys=[head])
    findings = connectors.check_hand_drawn_arrows(scene, tokens)
    assert [f.rule for f in findings] == ["hand-drawn-arrow"]
    assert "marker-end" in findings[0].message


def test_triangle_far_from_any_connector_is_allowed(
    tokens: DesignTokens,
) -> None:
    """A triangle used as a chart glyph is not an arrowhead."""
    glyph = Polygon("p1", ((900, 500), (880, 540), (920, 540)), "#475569", None)
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 300, 145, 500, 145)], polys=[glyph])
    assert connectors.check_hand_drawn_arrows(scene, tokens) == []


def test_one_crossing_is_tolerated(tokens: DesignTokens) -> None:
    """A single crossing may be inherent to the graph."""
    scene = _scene(conns=[_conn("c1", 100, 100, 400, 400),
                          _conn("c2", 100, 400, 400, 100)])
    assert connectors.check_crossings(scene, tokens) == []


def test_several_crossings_are_a_warning(tokens: DesignTokens) -> None:
    """Two or more crossings point at the layout, not the graph."""
    scene = _scene(conns=[_conn("c1", 100, 100, 400, 400),
                          _conn("c2", 100, 400, 400, 100),
                          _conn("c3", 100, 250, 400, 250)])
    findings = connectors.check_crossings(scene, tokens)
    assert [f.rule for f in findings] == ["connector-crossing"]
    assert findings[0].severity == "warning"
    assert "3" in findings[0].message


def test_connectors_sharing_an_endpoint_do_not_cross(
    tokens: DesignTokens,
) -> None:
    """A fan-out from one port is not a crossing."""
    scene = _scene(conns=[_conn("c1", 300, 145, 500, 100),
                          _conn("c2", 300, 145, 500, 200),
                          _conn("c3", 300, 145, 500, 300)])
    assert connectors.check_crossings(scene, tokens) == []


def test_check_runs_every_connector_rule(tokens: DesignTokens) -> None:
    """The module entry point aggregates all six rules."""
    scene = _scene(boxes=[_A], conns=[_conn("c1", 300, 145, 420, 400)])
    rules = {f.rule for f in connectors.check(scene, tokens)}
    assert "connector-dangling" in rules
    assert set(connectors.RULES) == {
        "connector-dangling", "connector-port-drift", "connector-through-node",
        "connector-clearance", "hand-drawn-arrow", "connector-crossing",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_connectors.py -v`
Expected: FAIL — `ImportError: cannot import name 'connectors' from 'visual_style'`.

- [ ] **Step 3: Write the connector rules**

Create `skills/report-slides/scripts/visual_style/connectors.py`:

```python
"""Connector rules: attachment, routing, clearance, and arrowhead provenance."""
from __future__ import annotations

import math
from itertools import combinations
from typing import Dict, List, Tuple

from design_tokens import DesignTokens

from .geometry import node_bounds
from .report import Finding
from .scene import Box, Connector, Scene

RULES: Tuple[str, ...] = (
    "connector-dangling", "connector-port-drift", "connector-through-node",
    "connector-clearance", "hand-drawn-arrow", "connector-crossing",
)

ATTACH_TOLERANCE = 4.0
ARROW_PROXIMITY = 12.0
_CROSSING_BUDGET = 1
_SHARED_ENDPOINT_TOLERANCE = 1.0


def edge_distance(px: float, py: float, box: Box) -> float:
    """Return the distance from a point to a box's boundary.

    Args:
        px: Point x coordinate.
        py: Point y coordinate.
        box: The box.

    Returns:
        0.0 on the boundary; the inward distance to the nearest edge when the
        point is inside; the outward Euclidean distance when it is outside.
    """
    if box.x <= px <= box.right and box.y <= py <= box.bottom:
        return min(px - box.x, box.right - px, py - box.y, box.bottom - py)
    dx = max(box.x - px, 0.0, px - box.right)
    dy = max(box.y - py, 0.0, py - box.bottom)
    return math.hypot(dx, dy)


def _outside_distance(px: float, py: float, box: Box) -> float:
    """Return the distance from a point to a box, zero when inside.

    Args:
        px: Point x coordinate.
        py: Point y coordinate.
        box: The box.

    Returns:
        The outward Euclidean distance in SVG units.
    """
    dx = max(box.x - px, 0.0, px - box.right)
    dy = max(box.y - py, 0.0, py - box.bottom)
    return math.hypot(dx, dy)


def _point_segment_distance(px: float, py: float, x1: float, y1: float,
                            x2: float, y2: float) -> float:
    """Return the distance from a point to a segment.

    Args:
        px: Point x coordinate.
        py: Point y coordinate.
        x1: Segment start x.
        y1: Segment start y.
        x2: Segment end x.
        y2: Segment end y.

    Returns:
        The shortest distance in SVG units.
    """
    dx, dy = x2 - x1, y2 - y1
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _orientation(ax: float, ay: float, bx: float, by: float,
                 cx: float, cy: float) -> float:
    """Return the signed area of the triangle `abc`.

    Args:
        ax: First point x.
        ay: First point y.
        bx: Second point x.
        by: Second point y.
        cx: Third point x.
        cy: Third point y.

    Returns:
        Positive for a counter-clockwise turn, negative for clockwise.
    """
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _segments_intersect(x1: float, y1: float, x2: float, y2: float,
                        x3: float, y3: float, x4: float, y4: float) -> bool:
    """Return whether two segments properly intersect.

    Args:
        x1: First segment start x.
        y1: First segment start y.
        x2: First segment end x.
        y2: First segment end y.
        x3: Second segment start x.
        y3: Second segment start y.
        x4: Second segment end x.
        y4: Second segment end y.

    Returns:
        True when the segments cross at an interior point of both.
    """
    d1 = _orientation(x3, y3, x4, y4, x1, y1)
    d2 = _orientation(x3, y3, x4, y4, x2, y2)
    d3 = _orientation(x1, y1, x2, y2, x3, y3)
    d4 = _orientation(x1, y1, x2, y2, x4, y4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def segment_crosses_box(x1: float, y1: float, x2: float, y2: float,
                        box: Box) -> bool:
    """Return whether a segment enters a box's interior.

    Args:
        x1: Segment start x.
        y1: Segment start y.
        x2: Segment end x.
        y2: Segment end y.
        box: The box.

    Returns:
        True when either endpoint is inside, or the segment crosses an edge.
    """
    if box.contains_point(x1, y1) or box.contains_point(x2, y2):
        return True
    corners = ((box.x, box.y), (box.right, box.y),
               (box.right, box.bottom), (box.x, box.bottom))
    for index in range(4):
        ax, ay = corners[index]
        bx, by = corners[(index + 1) % 4]
        if _segments_intersect(x1, y1, x2, y2, ax, ay, bx, by):
            return True
    return False


def segment_box_distance(x1: float, y1: float, x2: float, y2: float,
                         box: Box) -> float:
    """Return the shortest distance from a segment to a box.

    Args:
        x1: Segment start x.
        y1: Segment start y.
        x2: Segment end x.
        y2: Segment end y.
        box: The box.

    For two disjoint convex shapes the minimum is attained either at a box
    corner or at a segment endpoint, so both families are tested.

    Returns:
        0.0 when the segment touches or enters the box.
    """
    if segment_crosses_box(x1, y1, x2, y2, box):
        return 0.0
    corners = ((box.x, box.y), (box.right, box.y),
               (box.right, box.bottom), (box.x, box.bottom))
    corner_distance = min(
        _point_segment_distance(cx, cy, x1, y1, x2, y2) for cx, cy in corners
    )
    endpoint_distance = min(
        _outside_distance(px, py, box) for px, py in ((x1, y1), (x2, y2))
    )
    return min(corner_distance, endpoint_distance)


def segments_cross(a: Connector, b: Connector) -> bool:
    """Return whether two connectors cross away from a shared endpoint.

    Args:
        a: First connector.
        b: Second connector.

    Returns:
        True for a genuine crossing.
    """
    ends_a = ((a.x1, a.y1), (a.x2, a.y2))
    ends_b = ((b.x1, b.y1), (b.x2, b.y2))
    for ax, ay in ends_a:
        for bx, by in ends_b:
            if math.hypot(ax - bx, ay - by) <= _SHARED_ENDPOINT_TOLERANCE:
                return False
    return _segments_intersect(a.x1, a.y1, a.x2, a.y2,
                               b.x1, b.y1, b.x2, b.y2)


def _endpoints(conn: Connector) -> Tuple[Tuple[str, float, float], ...]:
    """Return a connector's endpoints tagged `start` and `end`.

    Args:
        conn: The connector.

    Returns:
        Two `(label, x, y)` triples.
    """
    return (("start", conn.x1, conn.y1), ("end", conn.x2, conn.y2))


def check_dangling(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report connector endpoints that attach to nothing.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `connector-dangling` error per offending endpoint.
    """
    del tokens
    bounds = node_bounds(scene)
    findings: List[Finding] = []
    for conn in scene.connectors:
        declared = {"start": conn.from_node, "end": conn.to_node}
        for label, px, py in _endpoints(conn):
            node = declared[label]
            if node is not None and node not in bounds:
                findings.append(Finding(
                    rule="connector-dangling", severity="error",
                    message=f"{conn.element_id} declares its {label} on node "
                            f"{node!r}, which is not in the scene",
                    element_id=conn.element_id, location=(px, py)))
                continue
            if node is not None:
                continue
            attached = any(
                edge_distance(px, py, box) <= ATTACH_TOLERANCE
                for box in scene.boxes
            )
            if not attached:
                findings.append(Finding(
                    rule="connector-dangling", severity="error",
                    message=f"{conn.element_id} has its {label} at "
                            f"({px:g}, {py:g}), which touches no shape and "
                            f"declares no node",
                    element_id=conn.element_id, location=(px, py)))
    return findings


def check_port_drift(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report endpoints that miss the node they claim to attach to.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `connector-port-drift` error per offending endpoint.
    """
    del tokens
    bounds = node_bounds(scene)
    findings: List[Finding] = []
    for conn in scene.connectors:
        declared = {"start": conn.from_node, "end": conn.to_node}
        for label, px, py in _endpoints(conn):
            node = declared[label]
            if node is None or node not in bounds:
                # An absent or unresolvable node is check_dangling's finding.
                continue
            drift = edge_distance(px, py, bounds[node])
            if drift > ATTACH_TOLERANCE:
                findings.append(Finding(
                    rule="connector-port-drift", severity="error",
                    message=f"{conn.element_id} {label} is {drift:g} from the "
                            f"boundary of node {node}; the tolerance is "
                            f"{ATTACH_TOLERANCE:g}",
                    element_id=conn.element_id, location=(px, py)))
    return findings


def _unrelated_nodes(conn: Connector, bounds: Dict[str, Box]) -> Dict[str, Box]:
    """Return the nodes a connector does not itself join.

    A node counts as joined when the connector declares it, and also when an
    endpoint lands on its boundary within `ATTACH_TOLERANCE`. Without the second
    case an undeclared but correctly attached connector would be reported as
    violating the clearance of the very node it terminates on.

    Args:
        conn: The connector.
        bounds: Node bounding boxes.

    Returns:
        The subset of `bounds` the connector neither declares nor touches.
    """
    declared = {conn.from_node, conn.to_node}
    unrelated: Dict[str, Box] = {}
    for node_id, box in bounds.items():
        if node_id in declared:
            continue
        touching = any(edge_distance(px, py, box) <= ATTACH_TOLERANCE
                       for _, px, py in _endpoints(conn))
        if touching:
            continue
        unrelated[node_id] = box
    return unrelated


def check_through_node(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report connectors routed through a node they do not join.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `connector-through-node` error per offending pair.
    """
    del tokens
    bounds = node_bounds(scene)
    findings: List[Finding] = []
    for conn in scene.connectors:
        for node_id, box in sorted(_unrelated_nodes(conn, bounds).items()):
            if segment_crosses_box(conn.x1, conn.y1, conn.x2, conn.y2, box):
                findings.append(Finding(
                    rule="connector-through-node", severity="error",
                    message=f"{conn.element_id} passes through node {node_id}, "
                            f"which it does not join",
                    element_id=conn.element_id, location=(box.x, box.y)))
    return findings


def check_clearance(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report connectors passing closer to a node than the token minimum.

    Connectors that enter a node are reported by `connector-through-node`;
    reporting both would double-count one defect.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `connector-clearance` error per offending pair.
    """
    minimum = float(tokens.raw["spacing"]["connector_clearance_min"])
    bounds = node_bounds(scene)
    findings: List[Finding] = []
    for conn in scene.connectors:
        for node_id, box in sorted(_unrelated_nodes(conn, bounds).items()):
            if segment_crosses_box(conn.x1, conn.y1, conn.x2, conn.y2, box):
                continue
            clearance = segment_box_distance(conn.x1, conn.y1,
                                             conn.x2, conn.y2, box)
            if clearance < minimum:
                findings.append(Finding(
                    rule="connector-clearance", severity="error",
                    message=f"{conn.element_id} passes {clearance:g} from node "
                            f"{node_id}; spacing.connector_clearance_min is "
                            f"{minimum:g}",
                    element_id=conn.element_id, location=(box.x, box.y)))
    return findings


def check_hand_drawn_arrows(scene: Scene,
                            tokens: DesignTokens) -> List[Finding]:
    """Report triangles drawn as arrowheads instead of markers.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `hand-drawn-arrow` error per offending polygon.
    """
    del tokens
    findings: List[Finding] = []
    for polygon in scene.polygons:
        if len(polygon.points) != 3:
            continue
        cx = sum(point[0] for point in polygon.points) / 3.0
        cy = sum(point[1] for point in polygon.points) / 3.0
        for conn in scene.connectors:
            near = any(math.hypot(cx - px, cy - py) <= ARROW_PROXIMITY
                       for _, px, py in _endpoints(conn))
            if near:
                findings.append(Finding(
                    rule="hand-drawn-arrow", severity="error",
                    message=f"{polygon.element_id} is a triangle within "
                            f"{ARROW_PROXIMITY:g} units of {conn.element_id}'s "
                            f"endpoint; use marker-end so the arrowhead "
                            f"survives the PPTX export",
                    element_id=polygon.element_id, location=(cx, cy)))
                break
    return findings


def check_crossings(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report slides with more connector crossings than the budget allows.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        At most one `connector-crossing` warning.
    """
    del tokens
    crossings = [
        (a.element_id, b.element_id)
        for a, b in combinations(scene.connectors, 2)
        if segments_cross(a, b)
    ]
    if len(crossings) <= _CROSSING_BUDGET:
        return []
    rendered = ", ".join(f"{a}×{b}" for a, b in crossings)
    return [Finding(
        rule="connector-crossing", severity="warning",
        message=f"{len(crossings)} connector crossings ({rendered}); more than "
                f"{_CROSSING_BUDGET} usually indicates the layout, not the graph")]


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every connector rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All connector findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_dangling(scene, tokens))
    findings.extend(check_port_drift(scene, tokens))
    findings.extend(check_through_node(scene, tokens))
    findings.extend(check_clearance(scene, tokens))
    findings.extend(check_hand_drawn_arrows(scene, tokens))
    findings.extend(check_crossings(scene, tokens))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_connectors.py -v`
Expected: PASS — 17 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/visual_style/connectors.py \
        skills/report-slides/scripts/tests/test_visual_style_connectors.py
git commit -m "feat(report-slides): add connector attachment, routing, and arrowhead rules"
```

---

### Task 7: Density and consistency rules

**Files:**
- Create: `skills/report-slides/scripts/visual_style/density.py`
- Test: `skills/report-slides/scripts/tests/test_visual_style_density.py`

**Interfaces:**
- Consumes: `visual_style.scene.{Scene, Box}` (Task 2);
  `visual_style.report.Finding` (Task 1); `visual_style.geometry.node_bounds`
  (Task 3); `design_tokens.DesignTokens` (plan 1, Task 2).
- Produces, imported by Task 8:
  - `RULES: Tuple[str, ...]` — `("component-drift", "spacing-variance",
    "bullet-budget", "occupancy", "equal-card-repetition")`
  - `SPACING_TOLERANCE: float` — `4.0`
  - `EQUAL_CARD_THRESHOLD: int` — `4`
  - `union_area(boxes: Sequence[Box]) -> float`
  - `check(scene: Scene, tokens: DesignTokens) -> List[Finding]`
  - `check_component_drift`, `check_spacing_variance`, `check_bullet_budget`,
    `check_occupancy`, `check_equal_cards` — each with the same signature as
    `check`

**Occupancy is measured as a union, not a sum.** Adding box areas double-counts
every nested card and reports a densely layered slide as over-full. `union_area`
sweeps the compressed x-coordinates, so an overlap contributes once. Occupancy
is that union divided by the safe area, and the rule is a warning because both
a sparse hero slide and a deliberately dense appendix table are legitimate —
the judgement belongs to the art-direction reviewer (Task 10).

**`equal-card-repetition` is a prompt, not a verdict.** Four identically sized
cards carrying identically sized labels is exactly the shape the spec calls out
(§2.13): a layout that states no hierarchy because none was decided. Sometimes
that is right. The rule surfaces it as a warning and names the cards, so the
reviewer either justifies the grid or breaks it.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_visual_style_density.py`:

```python
"""Tests for the density and consistency rules."""

from __future__ import annotations

from typing import Optional

import pytest

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from fonts import vertical_metrics
from visual_style import density
from visual_style.scene import Box, Scene, TextRun


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _box(element_id: str, x: float, y: float, w: float = 200, h: float = 90,
         radius: float = 8, stroke_width: float = 1.5,
         role: Optional[str] = "node.primary",
         node_id: Optional[str] = None) -> Box:
    """Build a node box for rule testing."""
    return Box(element_id, "rect", x, y, w, h, "#f8fafc", "#475569",
               stroke_width, radius, role, node_id or element_id, False)


def _label(element_id: str, x: float, y: float, size: float = 18,
           node_id: Optional[str] = None,
           role: str = "node.label") -> TextRun:
    """Build a label for rule testing."""
    ascent, descent = vertical_metrics("DejaVu Sans", size)
    return TextRun(element_id, "Label", x, y, size, 600, "#374151", "start",
                   role, node_id, 1, 60.0, ascent, descent, 0.0)


def _scene(boxes=(), texts=()) -> Scene:
    """Build a scene from boxes and texts alone."""
    return Scene(1200, 675, tuple(boxes), tuple(texts), (), (), "DejaVu Sans")


def test_union_area_counts_overlap_once() -> None:
    """Two half-overlapping 100x100 boxes cover 15000, not 20000."""
    boxes = [_box("a", 0, 0, 100, 100), _box("b", 50, 0, 100, 100)]
    assert density.union_area(boxes) == pytest.approx(15000.0)


def test_union_area_of_disjoint_boxes_is_the_sum() -> None:
    """Disjoint boxes add up."""
    boxes = [_box("a", 0, 0, 100, 100), _box("b", 300, 0, 100, 100)]
    assert density.union_area(boxes) == pytest.approx(20000.0)


def test_consistent_components_are_clean(tokens: DesignTokens) -> None:
    """Instances of one role sharing geometry do not drift."""
    scene = _scene(boxes=[_box("a", 100, 100), _box("b", 400, 100)])
    assert density.check_component_drift(scene, tokens) == []


def test_radius_drift_between_instances_is_an_error(
    tokens: DesignTokens,
) -> None:
    """One rounded and one sharp card of the same role is drift."""
    scene = _scene(boxes=[_box("a", 100, 100, radius=8),
                          _box("b", 400, 100, radius=0)])
    findings = density.check_component_drift(scene, tokens)
    assert [f.rule for f in findings] == ["component-drift"]
    assert "radius" in findings[0].message


def test_stroke_width_drift_is_an_error(tokens: DesignTokens) -> None:
    """Differing outline weights across one role is drift."""
    scene = _scene(boxes=[_box("a", 100, 100, stroke_width=1.5),
                          _box("b", 400, 100, stroke_width=3.0)])
    findings = density.check_component_drift(scene, tokens)
    assert "stroke width" in findings[0].message


def test_label_size_drift_is_an_error(tokens: DesignTokens) -> None:
    """Labels of one role rendered at different sizes is drift."""
    scene = _scene(texts=[_label("t1", 100, 150, size=18),
                          _label("t2", 400, 150, size=21)])
    findings = density.check_component_drift(scene, tokens)
    assert [f.rule for f in findings] == ["component-drift"]
    assert "label size" in findings[0].message


def test_boxes_without_a_style_role_are_not_compared(
    tokens: DesignTokens,
) -> None:
    """Drift is defined within a declared role, not across the slide."""
    scene = _scene(boxes=[_box("a", 100, 100, radius=8, role=None),
                          _box("b", 400, 100, radius=0, role=None)])
    assert density.check_component_drift(scene, tokens) == []


def test_even_row_spacing_is_clean(tokens: DesignTokens) -> None:
    """Three cards with equal gaps have no spacing variance."""
    scene = _scene(boxes=[_box("a", 100, 100, 200, 90),
                          _box("b", 340, 100, 200, 90),
                          _box("c", 580, 100, 200, 90)])
    assert density.check_spacing_variance(scene, tokens) == []


def test_uneven_row_spacing_is_a_warning(tokens: DesignTokens) -> None:
    """A 40-unit and a 100-unit gap in one row is a rhythm defect."""
    scene = _scene(boxes=[_box("a", 100, 100, 200, 90),
                          _box("b", 340, 100, 200, 90),
                          _box("c", 640, 100, 200, 90)])
    findings = density.check_spacing_variance(scene, tokens)
    assert [f.rule for f in findings] == ["spacing-variance"]
    assert findings[0].severity == "warning"


def test_bullets_within_budget_are_clean(tokens: DesignTokens) -> None:
    """Default max_bullets is 6."""
    texts = [_label(f"t{i}", 100, 100 + 40 * i, role="body") for i in range(6)]
    assert density.check_bullet_budget(_scene(texts=texts), tokens) == []


def test_too_many_bullets_is_a_warning(tokens: DesignTokens) -> None:
    """A seventh bullet warns."""
    texts = [_label(f"t{i}", 100, 100 + 40 * i, role="body") for i in range(7)]
    findings = density.check_bullet_budget(_scene(texts=texts), tokens)
    assert [f.rule for f in findings] == ["bullet-budget"]
    assert "7" in findings[0].message
    assert "6" in findings[0].message


def test_occupancy_in_range_is_clean(tokens: DesignTokens) -> None:
    """Safe area is 1104x603; ~45% coverage sits inside 0.30..0.78."""
    scene = _scene(boxes=[_box("a", 60, 50, 800, 380)])
    assert density.check_occupancy(scene, tokens) == []


def test_sparse_slide_is_a_warning(tokens: DesignTokens) -> None:
    """A nearly empty slide falls below occupancy_min."""
    scene = _scene(boxes=[_box("a", 60, 50, 120, 60)])
    findings = density.check_occupancy(scene, tokens)
    assert [f.rule for f in findings] == ["occupancy"]
    assert "0.30" in findings[0].message


def test_overstuffed_slide_is_a_warning(tokens: DesignTokens) -> None:
    """A slide filling the safe area exceeds occupancy_max."""
    scene = _scene(boxes=[_box("a", 48, 36, 1104, 603)])
    findings = density.check_occupancy(scene, tokens)
    assert [f.rule for f in findings] == ["occupancy"]
    assert "0.78" in findings[0].message


def test_four_identical_cards_are_a_warning(tokens: DesignTokens) -> None:
    """Undifferentiated equal cards state no hierarchy."""
    boxes = [_box(f"c{i}", 100 + 260 * i, 200, 200, 90) for i in range(4)]
    texts = [_label(f"t{i}", 120 + 260 * i, 250, node_id=f"c{i}")
             for i in range(4)]
    findings = density.check_equal_cards(_scene(boxes, texts), tokens)
    assert [f.rule for f in findings] == ["equal-card-repetition"]
    assert findings[0].severity == "warning"


def test_three_identical_cards_are_tolerated(tokens: DesignTokens) -> None:
    """The threshold is four; three is a normal triad."""
    boxes = [_box(f"c{i}", 100 + 260 * i, 200, 200, 90) for i in range(3)]
    assert density.check_equal_cards(_scene(boxes), tokens) == []


def test_differentiated_cards_are_not_flagged(tokens: DesignTokens) -> None:
    """One card larger than the rest is a stated hierarchy."""
    boxes = [_box("c0", 100, 200, 320, 140)]
    boxes += [_box(f"c{i}", 100 + 260 * i, 400, 200, 90) for i in range(1, 4)]
    assert density.check_equal_cards(_scene(boxes), tokens) == []


def test_check_runs_every_density_rule(tokens: DesignTokens) -> None:
    """The module entry point aggregates all five rules."""
    scene = _scene(boxes=[_box("a", 100, 100, radius=8),
                          _box("b", 400, 100, radius=0)])
    rules = {f.rule for f in density.check(scene, tokens)}
    assert "component-drift" in rules
    assert "occupancy" in rules
    assert set(density.RULES) == {
        "component-drift", "spacing-variance", "bullet-budget", "occupancy",
        "equal-card-repetition",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_density.py -v`
Expected: FAIL — `ImportError: cannot import name 'density' from 'visual_style'`.

- [ ] **Step 3: Write the density rules**

Create `skills/report-slides/scripts/visual_style/density.py`:

```python
"""Density and consistency rules: component drift, rhythm, and slide load."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from design_tokens import DesignTokens

from .geometry import node_bounds
from .report import Finding
from .scene import Box, Scene

RULES: Tuple[str, ...] = (
    "component-drift", "spacing-variance", "bullet-budget", "occupancy",
    "equal-card-repetition",
)

SPACING_TOLERANCE = 4.0
EQUAL_CARD_THRESHOLD = 4
_METRIC_TOLERANCE = 0.5
_ROW_OVERLAP_RATIO = 0.5


def union_area(boxes: Sequence[Box]) -> float:
    """Return the area covered by a set of boxes, counting overlap once.

    The sweep compresses the x-coordinates into strips, then for each strip
    merges the y-intervals of the boxes spanning it.

    Args:
        boxes: The boxes to union.

    Returns:
        The covered area in square SVG units.
    """
    if not boxes:
        return 0.0
    xs = sorted({box.x for box in boxes} | {box.right for box in boxes})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        strip_width = right - left
        if strip_width <= 0:
            continue
        intervals = sorted(
            (box.y, box.bottom) for box in boxes
            if box.x <= left and box.right >= right and box.bottom > box.y
        )
        covered = 0.0
        current_top, current_bottom = None, None
        for top, bottom in intervals:
            if current_bottom is None or top > current_bottom:
                if current_bottom is not None:
                    covered += current_bottom - current_top
                current_top, current_bottom = top, bottom
            else:
                current_bottom = max(current_bottom, bottom)
        if current_bottom is not None:
            covered += current_bottom - current_top
        total += strip_width * covered
    return total


def _drift(values: Sequence[float]) -> float:
    """Return the spread of a metric across component instances.

    Args:
        values: The measured values.

    Returns:
        `max - min`, or 0.0 for fewer than two values.
    """
    if len(values) < 2:
        return 0.0
    return max(values) - min(values)


def check_component_drift(scene: Scene,
                          tokens: DesignTokens) -> List[Finding]:
    """Report instances of one style role that are not drawn alike.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `component-drift` error per offending role.
    """
    del tokens
    findings: List[Finding] = []

    by_role: Dict[str, List[Box]] = defaultdict(list)
    for box in scene.boxes:
        if box.style_role:
            by_role[box.style_role].append(box)
    for role, boxes in sorted(by_role.items()):
        metrics = (
            ("radius", [box.radius for box in boxes]),
            ("stroke width", [box.stroke_width for box in boxes]),
        )
        drifting = [
            f"{name} spans {min(values):g}..{max(values):g}"
            for name, values in metrics
            if _drift(values) > _METRIC_TOLERANCE
        ]
        if drifting:
            findings.append(Finding(
                rule="component-drift", severity="error",
                message=f"{len(boxes)} instances of style role {role!r} differ: "
                        + "; ".join(drifting),
                element_id=boxes[0].element_id,
                location=(boxes[0].x, boxes[0].y)))

    text_by_role: Dict[str, List[float]] = defaultdict(list)
    for run in scene.texts:
        if run.style_role:
            text_by_role[run.style_role].append(run.size)
    for role, sizes in sorted(text_by_role.items()):
        if _drift(sizes) > _METRIC_TOLERANCE:
            findings.append(Finding(
                rule="component-drift", severity="error",
                message=f"{len(sizes)} runs of style role {role!r} differ in "
                        f"label size, spanning {min(sizes):g}..{max(sizes):g}"))
    return findings


def _rows(boxes: Sequence[Box]) -> List[List[Box]]:
    """Group boxes into horizontal rows by vertical overlap.

    Args:
        boxes: The boxes to group.

    Returns:
        Rows of three or more boxes, each sorted left to right.
    """
    rows: List[List[Box]] = []
    for box in sorted(boxes, key=lambda item: (item.y, item.x)):
        placed = False
        for row in rows:
            reference = row[0]
            overlap = (min(reference.bottom, box.bottom)
                       - max(reference.y, box.y))
            if overlap >= _ROW_OVERLAP_RATIO * min(reference.h, box.h):
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])
    return [sorted(row, key=lambda item: item.x) for row in rows
            if len(row) >= 3]


def check_spacing_variance(scene: Scene,
                           tokens: DesignTokens) -> List[Finding]:
    """Report rows of nodes whose gaps are not evenly spaced.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `spacing-variance` warning per offending row.
    """
    del tokens
    findings: List[Finding] = []
    for row in _rows(list(node_bounds(scene).values())):
        gaps = [right.x - left.right for left, right in zip(row, row[1:])]
        if _drift(gaps) > SPACING_TOLERANCE:
            rendered = ", ".join(f"{gap:g}" for gap in gaps)
            findings.append(Finding(
                rule="spacing-variance", severity="warning",
                message=f"row starting at {row[0].element_id} has uneven gaps "
                        f"({rendered}); the tolerance is "
                        f"{SPACING_TOLERANCE:g}",
                element_id=row[0].element_id,
                location=(row[0].x, row[0].y)))
    return findings


def check_bullet_budget(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report slides carrying more body runs than the token budget allows.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        At most one `bullet-budget` warning.
    """
    budget = int(tokens.raw["density"]["max_bullets"])
    bullets = [run for run in scene.texts
               if (run.style_role or "").replace(".", "_") == "body"]
    if len(bullets) <= budget:
        return []
    return [Finding(
        rule="bullet-budget", severity="warning",
        message=f"slide carries {len(bullets)} body runs; density.max_bullets "
                f"is {budget}")]


def check_occupancy(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report slides whose content covers too little or too much of the frame.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        At most one `occupancy` warning.
    """
    limits = tokens.raw["density"]
    safe = tokens.raw["canvas"]["safe_area"]
    safe_area = ((scene.width - float(safe["left"]) - float(safe["right"]))
                 * (scene.height - float(safe["top"]) - float(safe["bottom"])))
    if safe_area <= 0:
        raise ValueError("canvas.safe_area leaves no drawable area")
    content = [box for box in scene.boxes if not box.bleed]
    content.extend(run.bbox() for run in scene.texts)
    ratio = union_area(content) / safe_area
    minimum = float(limits["occupancy_min"])
    maximum = float(limits["occupancy_max"])
    if ratio < minimum:
        return [Finding(
            rule="occupancy", severity="warning",
            message=f"content covers {ratio:.2f} of the safe area; "
                    f"density.occupancy_min is {minimum:.2f}")]
    if ratio > maximum:
        return [Finding(
            rule="occupancy", severity="warning",
            message=f"content covers {ratio:.2f} of the safe area; "
                    f"density.occupancy_max is {maximum:.2f}")]
    return []


def check_equal_cards(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report undifferentiated repetitions of one identically sized card.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        At most one `equal-card-repetition` warning per size cohort.
    """
    del tokens
    cohorts: Dict[Tuple[str, float, float], List[Box]] = defaultdict(list)
    for box in scene.boxes:
        if not box.style_role:
            continue
        cohorts[(box.style_role, round(box.w, 1), round(box.h, 1))].append(box)
    findings: List[Finding] = []
    for (role, width, height), boxes in sorted(cohorts.items()):
        if len(boxes) < EQUAL_CARD_THRESHOLD:
            continue
        names = ", ".join(box.element_id for box in boxes)
        findings.append(Finding(
            rule="equal-card-repetition", severity="warning",
            message=f"{len(boxes)} cards of style role {role!r} are all "
                    f"{width:g}x{height:g} ({names}); the layout states no "
                    f"hierarchy between them",
            element_id=boxes[0].element_id,
            location=(boxes[0].x, boxes[0].y)))
    return findings


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every density and consistency rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All density findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_component_drift(scene, tokens))
    findings.extend(check_spacing_variance(scene, tokens))
    findings.extend(check_bullet_budget(scene, tokens))
    findings.extend(check_occupancy(scene, tokens))
    findings.extend(check_equal_cards(scene, tokens))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_visual_style_density.py -v`
Expected: PASS — 18 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/visual_style/density.py \
        skills/report-slides/scripts/tests/test_visual_style_density.py
git commit -m "feat(report-slides): add density and component-consistency rules"
```

---

## Phase 3: Linter CLI and Workflow Gate

---

### Task 8: `validate_visual_style.py` and the blocking gate

**Files:**
- Create: `skills/report-slides/scripts/validate_visual_style.py`
- Test: `skills/report-slides/scripts/tests/test_validate_visual_style.py`
- Test: `skills/report-slides/scripts/tests/test_slide_archetypes.py`
- Modify: `skills/report-slides/SKILL.md` — end of `### 10. Visual integration`
  (currently `SKILL.md:687-693`)
- Modify: `skills/report-slides/references/visual-review.md` — `## Complete-slide
  gate` (currently `visual-review.md:86-107`)

**Interfaces:**
- Consumes: `visual_style.report.LintReport` (Task 1);
  `visual_style.scene.parse_scene` (Task 2); the five rule modules (Tasks 3–7);
  `design_tokens.{DEFAULT_TOKENS_PATH, DesignTokens, TokenError}` (plan 1,
  Task 2); `fonts.{FontError, resolve_font_stack}` (plan 1, Task 5).
- Produces:
  - `RULE_MODULES: Tuple[ModuleType, ...]` — the five modules in fixed order
  - `lint_svg(svg_path: Path, tokens: DesignTokens, font_family: str)
    -> LintReport`
  - `lint_paths(paths: Sequence[Path], tokens_path: Path,
    warnings_as_errors: bool = False) -> Dict[str, Any]`
  - `main() -> None`

This task also carries the only test in either plan that runs the linter over
markup the renderer actually produced. Keep it even when it looks redundant
against the fixture tests: those use hand-written SVG, plan 1's renderer tests
assert on strings, and neither can detect that the two plans disagree about
where a text box is. That disagreement is exactly what put the footer baseline
on the safe-area boundary. It adds `generate_slides.{apply_tokens, frame, svg,
S}` (plan 1, Task 6) to this task's consumed interfaces.

**Why the stage numbering does not change.** `SKILL.md` advertises a 15-stage
pipeline and the design spec, the agent docs, and `presentation_module_lineage.py`
all reference those numbers. The gate is therefore added as a blocking step at
the end of Stage 10 rather than as a new Stage 10.5. It runs before any reviewer
is dispatched, which is what spec §D4 requires: a human-judgement reviewer should
never spend its attention on a defect a ruler could have caught.

**Exit codes** follow the house convention set by `validate_visual_module.py`:
`0` clean, `1` findings, and a read or token failure is reported as a finding
rather than a traceback.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_validate_visual_style.py`:

```python
"""Tests for the visual-style linter CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from design_tokens import DEFAULT_TOKENS_PATH
from validate_visual_style import RULE_MODULES, lint_paths

_SKILL_DIR = Path(__file__).resolve().parents[2]
_SCRIPTS = _SKILL_DIR / "scripts"
_CLI = _SCRIPTS / "validate_visual_style.py"
_CLEAN_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#ffffff"/>
  <g data-pptx-role="group" data-node-id="n1">
    <rect x="120" y="200" width="320" height="160" rx="8" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <text x="160" y="290" font-size="18" font-weight="600" fill="#374151"
          data-style-role="node_label">Encoder</text>
  </g>
  <g data-pptx-role="group" data-node-id="n2">
    <rect x="640" y="200" width="320" height="160" rx="8" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <text x="680" y="290" font-size="18" font-weight="600" fill="#374151"
          data-style-role="node_label">Decoder</text>
  </g>
  <line x1="440" y1="280" x2="640" y2="280" stroke="#475569" stroke-width="2"
        marker-end="url(#arrow)" data-from="n1" data-to="n2"/>
</svg>"""
_DIRTY_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#ffffff"/>
  <g data-pptx-role="group" data-node-id="n1">
    <rect x="120" y="200" width="320" height="160" rx="8" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <text x="160" y="290" font-size="10" font-weight="400" fill="#374151"
          data-style-role="node_label">Encoder</text>
  </g>
</svg>"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    """Write an SVG fixture and return its path."""
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_real_generated_frame_passes_the_linter(tmp_path: Path) -> None:
    """The renderer's own output must satisfy the rules that lint it.

    Every other test in this plan lints a hand-written fixture, and every test in
    plan 1 asserts on a rendered string. Nothing joined the two, which is how a
    footer baseline placed exactly on the safe-area boundary shipped: plan 1
    thought it was inside, plan 2's `safe-area` rule would have reported it on
    every slide in the deck, and no test could see both.

    This is the joint. It must stay in the suite even if it looks redundant
    against the fixture tests -- it is the only one that fails when the two
    plans' models of a text box drift apart.
    """
    import generate_slides as gs

    gs.apply_tokens(DEFAULT_TOKENS_PATH)
    markup = gs.svg(gs.frame("Method Overview", footer="Internal draft, 2026"))
    path = tmp_path / "slide01.svg"
    path.write_text(markup, encoding="utf-8")

    result = lint_paths([path], DEFAULT_TOKENS_PATH)
    findings = result["files"][0]["findings"]
    errors = [f for f in findings if f["severity"] == "error"]
    assert errors == [], [f"{f['rule']}: {f['message']}" for f in errors]
    assert result["valid"] is True


def test_a_generated_frame_footer_sits_inside_the_safe_area(
    tmp_path: Path,
) -> None:
    """Pin the specific geometry, so a regression names itself.

    `canvas.h` 675 minus `safe_area.bottom` 36 is 639. The footnote role is size
    12, for which DejaVu Sans reports descent 3, so the baseline belongs at 636
    and the box bottom lands on 639 exactly.
    """
    import generate_slides as gs
    from visual_style.scene import parse_scene

    gs.apply_tokens(DEFAULT_TOKENS_PATH)
    path = tmp_path / "slide01.svg"
    path.write_text(
        gs.svg(gs.frame("T", footer="f")), encoding="utf-8")
    scene = parse_scene(path, gs.S["font_resolved"])
    footer = next(run for run in scene.texts if run.text == "f")
    assert footer.y == pytest.approx(636.0)
    assert footer.bbox().bottom == pytest.approx(639.0)


def test_rule_modules_cover_every_declared_rule() -> None:
    """The CLI wires in every rule the modules declare."""
    rules = {rule for module in RULE_MODULES for rule in module.RULES}
    assert len(rules) == 22
    assert "type-floor" in rules
    assert "hand-drawn-arrow" in rules


def test_a_clean_slide_reports_valid(tmp_path: Path) -> None:
    """A token-conformant slide passes with no errors."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    result = lint_paths([svg], DEFAULT_TOKENS_PATH)
    assert result["valid"] is True, result["files"][0]["findings"]


def test_undersized_label_fails(tmp_path: Path) -> None:
    """The 10pt label the spec documents is caught as an error."""
    svg = _write(tmp_path, "dirty.svg", _DIRTY_SVG)
    result = lint_paths([svg], DEFAULT_TOKENS_PATH)
    assert result["valid"] is False
    rules = {f["rule"] for f in result["files"][0]["findings"]}
    assert "type-floor" in rules


def test_warnings_do_not_fail_by_default(tmp_path: Path) -> None:
    """Warnings are reported without failing the gate."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    result = lint_paths([svg], DEFAULT_TOKENS_PATH)
    assert result["warning_count"] >= 1
    assert result["valid"] is True


def test_warnings_as_errors_fails(tmp_path: Path) -> None:
    """The strict flag promotes warnings into gate failures."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    result = lint_paths([svg], DEFAULT_TOKENS_PATH, warnings_as_errors=True)
    assert result["valid"] is False


def test_unreadable_file_is_a_finding_not_a_traceback(tmp_path: Path) -> None:
    """A missing SVG is reported inside the result envelope."""
    result = lint_paths([tmp_path / "absent.svg"], DEFAULT_TOKENS_PATH)
    assert result["valid"] is False
    assert result["files"][0]["findings"][0]["rule"] == "unreadable-input"


def test_cli_exits_zero_on_a_clean_slide(tmp_path: Path) -> None:
    """Exit code 0 means the gate passed."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--svg", str(svg), "--json"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["valid"] is True


def test_cli_exits_one_on_findings(tmp_path: Path) -> None:
    """Exit code 1 means the gate failed."""
    svg = _write(tmp_path, "dirty.svg", _DIRTY_SVG)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--svg", str(svg), "--json"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["error_count"] >= 1


def test_cli_rejects_an_invalid_token_file(tmp_path: Path) -> None:
    """A bad --tokens path fails loudly rather than falling back."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--svg", str(svg),
         "--tokens", str(tmp_path / "absent.yaml"), "--json"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1
    assert "token" in proc.stdout.lower() + proc.stderr.lower()


@pytest.mark.parametrize("module", RULE_MODULES, ids=lambda m: m.__name__)
def test_every_rule_module_shares_the_entry_point(module) -> None:
    """Each module exposes check() and RULES."""
    assert callable(module.check)
    assert isinstance(module.RULES, tuple)
    assert module.RULES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 600 python3 -m pytest skills/report-slides/scripts/tests/test_validate_visual_style.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'validate_visual_style'`.

- [ ] **Step 3: Write the CLI**

Create `skills/report-slides/scripts/validate_visual_style.py`:

```python
#!/usr/bin/env python3
"""Deterministic visual-style gate for authored slide SVG.

Runs every rule module against a slide's design tokens and reports findings as
JSON. Exit code 0 means the gate passed; 1 means it did not.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Sequence, Tuple

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens, TokenError
from fonts import FontError, resolve_font_stack
from visual_style import color, connectors, density, geometry, typography
from visual_style.report import Finding, LintReport
from visual_style.scene import parse_scene

RULE_MODULES: Tuple[ModuleType, ...] = (
    geometry, typography, color, connectors, density,
)


def lint_svg(svg_path: Path, tokens: DesignTokens,
             font_family: str) -> LintReport:
    """Run every rule module against one slide.

    Args:
        svg_path: Path to the authored SVG.
        tokens: The resolved token set.
        font_family: An installed family used for text measurement.

    Returns:
        The report for this slide. A read or parse failure becomes an
        `unreadable-input` error rather than an exception, so one bad file does
        not hide findings in the others.
    """
    report = LintReport()
    try:
        scene = parse_scene(svg_path, font_family)
    except (OSError, ValueError) as exc:
        report.add(Finding(
            rule="unreadable-input", severity="error",
            message=f"cannot lint {svg_path}: {exc}",
            element_id=str(svg_path)))
        return report
    for module in RULE_MODULES:
        report.extend(module.check(scene, tokens))
    return report


def lint_paths(paths: Sequence[Path], tokens_path: Path,
               warnings_as_errors: bool = False) -> Dict[str, Any]:
    """Lint every given slide against one token file.

    Args:
        paths: The SVG files to lint.
        tokens_path: Path to the design-token file.
        warnings_as_errors: When true, warnings also fail the gate.

    Returns:
        A JSON-serialisable result envelope.

    Raises:
        TokenError: If the token file is missing or invalid.
        FontError: If no family in the token font stack is installed.
    """
    tokens = DesignTokens.load(tokens_path)
    font_family = resolve_font_stack(tokens.font_stack("sans"))

    files: List[Dict[str, Any]] = []
    error_count = 0
    warning_count = 0
    for path in paths:
        report = lint_svg(Path(path), tokens, font_family)
        payload = report.to_dict()
        payload["path"] = str(path)
        files.append(payload)
        error_count += payload["error_count"]
        warning_count += payload["warning_count"]

    failing = error_count > 0 or (warnings_as_errors and warning_count > 0)
    return {
        "valid": not failing,
        "tokens": str(tokens_path),
        "tokens_digest": tokens.digest,
        "font_family": font_family,
        "error_count": error_count,
        "warning_count": warning_count,
        "warnings_as_errors": warnings_as_errors,
        "files": files,
    }


def _render_text(result: Dict[str, Any]) -> str:
    """Render a result envelope for a terminal reader.

    Args:
        result: The envelope from `lint_paths`.

    Returns:
        A multi-line report.
    """
    lines: List[str] = []
    for entry in result["files"]:
        lines.append(entry["path"])
        if not entry["findings"]:
            lines.append("  clean")
        for finding in entry["findings"]:
            location = finding["location"]
            where = f" at ({location[0]:g}, {location[1]:g})" if location else ""
            lines.append(
                f"  [{finding['severity']}] {finding['rule']}: "
                f"{finding['message']}{where}")
    lines.append(
        f"{result['error_count']} error(s), {result['warning_count']} warning(s)")
    return "\n".join(lines)


def main() -> None:
    """Run the visual-style gate over one or more slides."""
    parser = argparse.ArgumentParser(
        description="Lint authored slide SVG against its design tokens.")
    parser.add_argument("--svg", metavar="PATH", type=Path, nargs="+",
                        required=True)
    parser.add_argument("--tokens", metavar="PATH", type=Path,
                        default=DEFAULT_TOKENS_PATH)
    parser.add_argument("--warnings-as-errors", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = lint_paths(args.svg, args.tokens, args.warnings_as_errors)
    except (TokenError, FontError) as exc:
        payload = {"valid": False, "error_count": 1, "warning_count": 0,
                   "files": [], "error": str(exc)}
        print(json.dumps(payload) if args.json
              else json.dumps(payload, indent=2))
        sys.exit(1)

    if args.json:
        print(json.dumps(result))
    else:
        print(_render_text(result))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `timeout 600 python3 -m pytest skills/report-slides/scripts/tests/test_validate_visual_style.py -v`
Expected: PASS — 16 passed.

If `test_a_clean_slide_reports_valid` fails on `occupancy`, that is the rule
working: the fixture is deliberately sparse. `occupancy` is a *warning*, so it
must not affect `valid`; if it does, the bug is in `lint_paths`, not the fixture.
Do not relax the fixture to make the assertion pass.

- [ ] **Step 5: Lint six real slide archetypes and record what they say**

Every rule so far was written against a fixture built to exercise it. None has
been run over a whole realistic slide, so nothing yet establishes what this rule
set actually says about the layouts users produce. Turning twenty-two blocking
rules on without knowing that is how a linter loses its authority in its first
week: the first hard error nobody believes gets the rule relaxed, and a relaxed
rule does not come back.

Render one slide of each archetype with `generate_slides.py` on the default
tokens, lint it, and record the result. Create
`skills/report-slides/scripts/tests/test_slide_archetypes.py`:

```python
"""What the rule set says about six realistic slides.

These are not tests of one rule. They are the record of what the whole suite
reports about the layouts this skill produces, and they exist so that a change
to any rule shows up as a change to a slide that a person can look at.

A finding recorded here is not thereby endorsed. An entry in `_EXPECTED` with a
comment saying "false positive, rule too strict" is a legitimate state and is
better than the alternative, which is not knowing.
"""
_ARCHETYPES = (
    "bullets", "bar_chart", "two_column", "timeline", "table", "architecture",
)

# rule ids the suite reports on each archetype, error and warning alike.
_EXPECTED: Dict[str, Set[str]] = {
    "bullets": set(),
    "bar_chart": set(),
    "two_column": set(),
    "timeline": set(),
    "table": set(),
    "architecture": set(),
}


@pytest.mark.parametrize("archetype", _ARCHETYPES)
def test_the_rule_set_says_what_it_is_recorded_as_saying(
        archetype: str, tmp_path: Path) -> None:
    """Lint a rendered archetype and compare against the recorded findings."""
    svg = _render_archetype(archetype, tmp_path)
    report = lint_svg(svg, DesignTokens.load(DEFAULT_TOKENS_PATH),
                      resolve_font_stack("sans-serif"))
    assert {finding.rule for finding in report.findings} == _EXPECTED[archetype]


@pytest.mark.parametrize("archetype", _ARCHETYPES)
def test_no_archetype_carries_a_hard_error(archetype: str,
                                           tmp_path: Path) -> None:
    """A slide this skill renders from its own defaults must build.

    If a renderer's own output fails a hard rule, the defect is in the renderer
    or in the rule -- not in the user's deck. Fix whichever is wrong and say
    which in the commit body. Do not downgrade the rule to a warning to make
    this pass; that is the failure this whole task exists to prevent.
    """
    svg = _render_archetype(archetype, tmp_path)
    report = lint_svg(svg, DesignTokens.load(DEFAULT_TOKENS_PATH),
                      resolve_font_stack("sans-serif"))
    errors = [f.rule for f in report.findings if f.severity == "error"]
    assert errors == [], f"{archetype} fails: {errors}"
```

`_render_archetype` writes a `slide_data.json` for that slide type into
`tmp_path`, runs `generate_slides.py` over it, and returns the SVG path. Reuse
the `slide_data.json` shapes documented in `SKILL.md` § "Generate slides"; one
representative slide each, not a corpus.

Fill `_EXPECTED` with what the suite actually reports on the first run, then read
every entry. For each one decide, and write down in a comment beside it, whether
it is a real defect in the renderer, a real defect in the token defaults, or a
false positive. Fix the first two. Leave the third recorded with its reason —
`{"occupancy"}` on a section divider is honest and useful; an empty set you never
verified is neither.

Run: `timeout 600 python3 -m pytest skills/report-slides/scripts/tests/test_slide_archetypes.py -v`
Expected: PASS — 12 passed (two tests parametrised six ways each). The first run
will not pass; it is how you learn what to write into `_EXPECTED` and which
renderers or defaults need fixing.

- [ ] **Step 6: Wire the gate into the workflow**

In `skills/report-slides/SKILL.md`, append to `### 10. Visual integration`
(after the paragraph ending "per §5 of the design spec)."):

````markdown
**Visual-style gate (deterministic, blocking).** Before any reviewer is
dispatched for a slide, run the linter over that slide's authored SVG:

```bash
timeout 120 python3 "$SCRIPTS/validate_visual_style.py" \
  --svg "$SLIDE_SVG" --tokens "$STYLE_TOKENS_REF" --json
```

Exit code 1 blocks the slide: the module returns to `revision_required` with the
findings attached, and Stages 11–12 are not entered. This gate is deterministic
and measures only what a ruler can settle — safe area, overlap, spacing,
type floors, contrast, palette conformance, connector attachment and routing,
component consistency, and slide load. It replaces no human judgement; it
removes from human judgement the defects that never needed it. Warnings do not
block, and are passed to the art-direction reviewer as context.
````

In `skills/report-slides/references/visual-review.md`, replace the opening of
`## Complete-slide gate` — the sentence "The complete slide passes only when all
of these are true:" and its six bullets — with:

```markdown
## Complete-slide gate

Measurable conditions are settled before this gate by
`scripts/validate_visual_style.py` (SKILL.md Stage 10). A slide that has not
passed that linter does not reach visual review at all, so do not re-litigate
safe area, overlap, spacing, type size, contrast, palette conformance,
connector attachment, or component consistency here — those have already been
measured, and a prose opinion cannot overturn a measurement.

What this gate judges is what the linter cannot:

- whether the visual states the slide's claim, or merely decorates it;
- whether the hierarchy directs the eye to what matters first;
- whether the composition reads at projection distance and at thumbnail size;
- whether meaning survives without colour; and
- whether the imagery is specific to this subject rather than generically
  "technical".

The linter's warnings are handed to this gate as context, not as verdicts: an
`occupancy`, `equal-card-repetition`, `spacing-variance`, or
`connector-crossing` warning is a question for the reviewer to answer, and the
answer is recorded in the review.
```

Leave the "The following conditions always fail the gate:" list in place; it
still names defects that require pixels to see.

- [ ] **Step 7: Verify the docs still validate**

Run: `timeout 600 python3 -m pytest skills/report-slides/scripts/tests/ -v`
Expected: PASS — the whole suite, including the doc-consistency tests.

- [ ] **Step 8: Commit**

```bash
git add skills/report-slides/scripts/validate_visual_style.py \
        skills/report-slides/scripts/tests/test_validate_visual_style.py \
        skills/report-slides/SKILL.md \
        skills/report-slides/references/visual-review.md
git commit -m "feat(report-slides): gate slides on a deterministic visual-style linter"
```

---

## Phase 4: Review Split and Art Direction

Spec §D5 splits one overloaded reviewer into two with different remits. Stage 12
currently asks a single agent to catch both "the arrow is clipped" and "this
slide has no point of view", and the second question loses every time.

**The role strings are additive, never renamed.** `visual_quality` is persisted
in every existing `.research/presentations/**/review_results` event and is
referenced by `presentation_gates.py`, `presentation_events.py`,
`presentation_workflow.py`, `presentation_state.py`, and roughly thirty tests.
Renaming it would be a state migration with no user-visible benefit. Instead
`render_integrity` and `art_direction` are added, and a single predicate decides
whether a slide's reviews are complete, accepting the legacy pair so decks
recorded before this change still reach `passed`.

---

### Task 9: Rename the rendering reviewer and centralise the role predicate

**Files:**
- Rename: `skills/report-slides/agents/visual_quality_reviewer_agent.md` →
  `skills/report-slides/agents/render_integrity_reviewer_agent.md`
- Modify: `skills/report-slides/scripts/presentation_gates.py:35` (`_REVIEW_ROLES`)
  and `presentation_gates.py:524-527` (`_FINDING_ROLE_KINDS`)
- Modify: `skills/report-slides/scripts/presentation_workflow.py:519` and `:525`
- Modify: `skills/report-slides/scripts/presentation_events.py:337-339`
- Modify: `skills/report-slides/SKILL.md:707-712` (`### 12. Visual quality review`)
- Modify: `skills/report-slides/agents/scientific_visual_reviewer_agent.md:12`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py:131-142`
- Test: `skills/report-slides/scripts/tests/test_reviewer_roles.py`

**Interfaces:**
- Consumes: nothing new.
- Produces, used by Task 10:
  - `presentation_gates.SLIDE_REVIEW_ROLE_SETS: Tuple[FrozenSet[str], ...]` —
    the accepted complete role sets for a **slide**, most current first
  - `presentation_gates.MODULE_REVIEW_ROLE_SETS: Tuple[FrozenSet[str], ...]` —
    the same for a **module**. Identical to the slide sets today; they diverge in
    Task 10, and naming them apart now is what stops that divergence from
    silently stalling every module
  - `presentation_gates.module_reviews_complete(roles: AbstractSet[str]) -> bool`
  - `presentation_gates.SLIDE_REVIEW_ROLE_ORDER: Tuple[str, ...]` — the current
    roles in the order the workflow runs them, so a "what next" suggestion
    follows the pipeline rather than the alphabet
  - `presentation_gates.slide_reviews_complete(roles: AbstractSet[str]) -> bool`
  - `presentation_gates.missing_slide_review_roles(roles: AbstractSet[str])
    -> Tuple[str, ...]` — the outstanding roles, in workflow order

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_reviewer_roles.py`:

```python
"""Tests for the reviewer-role contract shared by the review stages."""

from __future__ import annotations

from pathlib import Path

import presentation_gates as gates

_SKILL_DIR = Path(__file__).resolve().parents[2]
_AGENTS = _SKILL_DIR / "agents"


def test_render_integrity_is_an_accepted_review_role() -> None:
    """The new role is admissible wherever reviewer roles are validated."""
    assert "render_integrity" in gates._REVIEW_ROLES
    assert "visual_quality" in gates._REVIEW_ROLES


def test_render_integrity_keeps_the_rendering_finding_vocabulary() -> None:
    """The remit is unchanged; only the name and the neighbours changed."""
    assert (gates._FINDING_ROLE_KINDS["render_integrity"]
            == gates._FINDING_ROLE_KINDS["visual_quality"])
    assert "clipping" in gates._FINDING_ROLE_KINDS["render_integrity"]


def test_current_role_set_completes_a_slide() -> None:
    """Scientific plus render integrity is the new complete set."""
    assert gates.slide_reviews_complete({"scientific", "render_integrity"})


def test_legacy_role_set_still_completes_a_slide() -> None:
    """Decks recorded before the split must still reach passed."""
    assert gates.slide_reviews_complete({"scientific", "visual_quality"})


def test_module_completion_matches_slide_completion_today() -> None:
    """The two predicates agree until Task 10 deliberately parts them."""
    for roles in ({"scientific", "render_integrity"},
                  {"scientific", "visual_quality"}):
        assert gates.module_reviews_complete(roles)
    assert not gates.module_reviews_complete({"scientific"})


def test_a_partial_role_set_does_not_complete_a_slide() -> None:
    """One passing reviewer is not a complete review."""
    assert not gates.slide_reviews_complete({"scientific"})
    assert not gates.slide_reviews_complete({"render_integrity"})
    assert not gates.slide_reviews_complete(set())


def test_missing_roles_names_what_is_outstanding_in_workflow_order() -> None:
    """The caller can tell the user which review to run next."""
    assert gates.missing_slide_review_roles({"scientific"}) == (
        "render_integrity",)
    assert gates.missing_slide_review_roles({}) == gates.SLIDE_REVIEW_ROLE_ORDER
    assert gates.missing_slide_review_roles(
        {"scientific", "render_integrity"}) == ()


def test_the_renamed_agent_doc_exists_and_the_old_one_does_not() -> None:
    """The rename is complete, not additive."""
    assert (_AGENTS / "render_integrity_reviewer_agent.md").is_file()
    assert not (_AGENTS / "visual_quality_reviewer_agent.md").exists()


def test_the_renamed_agent_defers_measurable_defects_to_the_linter() -> None:
    """The doc must say what it no longer owns, or the remit will not shrink."""
    text = (_AGENTS / "render_integrity_reviewer_agent.md").read_text(
        encoding="utf-8")
    assert "name: render_integrity_reviewer_agent" in text
    assert "reviewer_role: render_integrity" in text
    assert "validate_visual_style.py" in text
    assert "art_direction_reviewer_agent" in text
```

Also update `skills/report-slides/scripts/tests/test_agent_persona_docs.py`,
replacing `test_visual_quality_reviewer_agent_names_stage_and_finding_kinds`
with:

```python
def test_render_integrity_reviewer_agent_names_stage_and_finding_kinds() -> None:
    text = _read("render_integrity_reviewer_agent.md")
    assert "name: render_integrity_reviewer_agent" in text
    assert "Stage 12" in text
    assert "Stage Boundary" in text
    assert "scientific" in text.lower() and "semantic" in text.lower()
    for kind in (
        "clipping", "overlap", "text-reflow", "connector-drift", "crop",
        "unreadably-small-text", "missing-image", "z-order", "alignment",
    ):
        assert kind in text, f"missing finding kind: {kind}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 600 python3 -m pytest skills/report-slides/scripts/tests/test_reviewer_roles.py skills/report-slides/scripts/tests/test_agent_persona_docs.py -v`
Expected: FAIL — `AttributeError: module 'presentation_gates' has no attribute
'slide_reviews_complete'`, and a `FileNotFoundError` for the renamed doc.

- [ ] **Step 3: Add the role and the predicate**

In `skills/report-slides/scripts/presentation_gates.py`, replace line 35:

```python
_REVIEW_ROLES = frozenset({"scientific", "visual_quality"})
```

with:

```python
# `visual_quality` is retained because it is persisted in existing review-result
# events; `render_integrity` is its current name. See the Phase 4 note in
# docs/superpowers/plans/2026-09-04-report-slides-visual-review.md.
_REVIEW_ROLES = frozenset({"scientific", "visual_quality", "render_integrity"})
```

In the same file, replace the `_FINDING_ROLE_KINDS` block:

```python
_FINDING_ROLE_KINDS = {
    "scientific": frozenset({"unsupported-claim", "other"}),
    "visual_quality": frozenset(_FINDING_KINDS - {"unsupported-claim", "duplicated-content", "missing-limitation", "excessive-background", "unnecessary-visual", "weak-continuity"}),
}
```

with:

```python
_RENDERING_KINDS = frozenset(_FINDING_KINDS - {"unsupported-claim", "duplicated-content", "missing-limitation", "excessive-background", "unnecessary-visual", "weak-continuity"})
_FINDING_ROLE_KINDS = {
    "scientific": frozenset({"unsupported-claim", "other"}),
    "visual_quality": _RENDERING_KINDS,
    "render_integrity": _RENDERING_KINDS,
}

# Workflow order, not alphabetical order: a "what next" suggestion should send
# the operator to the next stage, and `art_direction` sorts before `scientific`.
SLIDE_REVIEW_ROLE_ORDER: tuple[str, ...] = (
    "scientific", "render_integrity",
)
SLIDE_REVIEW_ROLE_SETS: tuple[frozenset[str], ...] = (
    frozenset(SLIDE_REVIEW_ROLE_ORDER),
    frozenset({"scientific", "visual_quality"}),
)
# A module is a fragment, not a composition. Spec D5 scopes the art-direction
# review to the complete slide, so the module set never gains that role. The two
# tuples are equal today and are deliberately kept separate: making them one
# name is how a module ends up waiting on a gate nothing will ever dispatch.
MODULE_REVIEW_ROLE_SETS: tuple[frozenset[str], ...] = (
    frozenset({"scientific", "render_integrity"}),
    frozenset({"scientific", "visual_quality"}),
)


def module_reviews_complete(roles: AbstractSet[str]) -> bool:
    """Return whether a module's passing reviewer roles complete its review.

    Args:
        roles: Reviewer roles that have recorded a passing review.

    Returns:
        True when any accepted module role set is satisfied.
    """
    return any(roles >= required for required in MODULE_REVIEW_ROLE_SETS)


def slide_reviews_complete(roles: AbstractSet[str]) -> bool:
    """Return whether a subject's passing reviewer roles complete its review.

    Args:
        roles: Reviewer roles that have recorded a passing review.

    Returns:
        True when any accepted role set is satisfied. The legacy
        ``visual_quality`` pair is accepted so decks recorded before the review
        split still reach ``passed``.
    """
    return any(roles >= required for required in SLIDE_REVIEW_ROLE_SETS)


def missing_slide_review_roles(roles: AbstractSet[str]) -> tuple[str, ...]:
    """Return the roles still outstanding, in the order the workflow runs them.

    Args:
        roles: Reviewer roles that have recorded a passing review.

    Returns:
        The unmet roles of ``SLIDE_REVIEW_ROLE_ORDER``, or an empty tuple when
        the review is complete under any accepted set.
    """
    if slide_reviews_complete(roles):
        return ()
    return tuple(role for role in SLIDE_REVIEW_ROLE_ORDER if role not in roles)
```

Add `AbstractSet` to the module's `typing` import at the top of the file.

- [ ] **Step 4: Route the workflow and events through the predicate**

In `skills/report-slides/scripts/presentation_workflow.py`, replace both
occurrences of:

```python
            if roles >= {"scientific", "visual_quality"}:
```

The two branches take **different** predicates. In the `subject_type == "slide"`
branch (line 519):

```python
            if _gates().slide_reviews_complete(roles):
```

and in the module branch (line 525):

```python
            if _gates().module_reviews_complete(roles):
```

Use whichever accessor the surrounding code already uses to reach
`presentation_gates`; if the module is imported directly, call
`presentation_gates.slide_reviews_complete(roles)`.

**Why two predicates and not one.** The literal set is currently duplicated on
lines 519 and 525, which is how the two branches drift. Collapsing them to a
single predicate removes that risk and creates a worse one: Task 10 adds
`art_direction` to the slide set, and spec §D5 scopes that reviewer to the
"**complete slide**, not isolated modules". A single shared predicate would then
demand a whole-slide art-direction review of a fragment, and since nothing
dispatches that reviewer for a module, every module would stop at `in_review`
permanently. Two named predicates state the difference once; one predicate hides
it until Task 10 turns it into a deadlock.

In `skills/report-slides/scripts/presentation_events.py`, replace:

```python
        if "scientific" in roles and "visual_quality" not in roles:
            return ["record_visual_quality_review"]
        if "visual_quality" in roles and "scientific" not in roles:
            return ["record_scientific_review"]
```

with:

```python
        outstanding = _gates_missing_slide_review_roles(roles)
        if outstanding and roles:
            return [f"record_{outstanding[0]}_review"]
```

where `_gates_missing_slide_review_roles` is
`presentation_gates.missing_slide_review_roles`, imported the same way the
module already reaches its siblings. The `and roles` guard preserves the
existing behaviour that a slide with no recorded review at all falls through to
the later checks rather than being reported as awaiting a specific reviewer.

Update `skills/report-slides/scripts/tests/test_presentation_state.py:614` from
`["record_visual_quality_review"]` to `["record_render_integrity_review"]`, and
line 712's inequality assertion to match. This is a rename of a next-action
label, not a weakening: the assertion still requires exactly one specific
action.

- [ ] **Step 5: Rename and narrow the agent doc**

```bash
git mv skills/report-slides/agents/visual_quality_reviewer_agent.md \
       skills/report-slides/agents/render_integrity_reviewer_agent.md
```

In the renamed file, set `name: render_integrity_reviewer_agent`, change the
heading to `# Render Integrity Review — Rendering Defect Gate`, set
`reviewer_role: render_integrity` in the Output Format block, and insert this
section immediately after `## Stage Boundary`:

```markdown
## What has already been measured

Before this stage, `scripts/validate_visual_style.py` has measured the slide's
source geometry against its design tokens: safe area, element overlap, node
spacing and padding, type-size floors, WCAG contrast, palette conformance,
connector attachment and routing, component consistency, and slide load. A
slide that failed those checks never reached you.

You are looking at pixels, which is the one thing that linter cannot do. Report
a defect the linter also names — overlap, alignment, unreadably small text —
only when the *render* disagrees with the *source*: a substituted font that
reflows a label, a rasteriser that clips a glyph, a converted PPTX that moves a
shape. Say which render you saw it in. Do not re-report a source-geometry
opinion; it has already been settled with a ruler.

Composition, hierarchy, imagery, and whether the slide states its claim belong
to `art_direction_reviewer_agent`, an independent gate at the same stage. A
slide reaches `passed` only when the scientific, render-integrity, and
art-direction reviews all pass.
```

- [ ] **Step 6: Update the cross-references**

In `skills/report-slides/agents/scientific_visual_reviewer_agent.md:12`, replace
`visual_quality_reviewer_agent` with `render_integrity_reviewer_agent`.

In `skills/report-slides/SKILL.md`, replace `### 12. Visual quality review` and
its paragraph with:

```markdown
### 12. Visual review (two independent gates)

Dispatch `render_integrity_reviewer_agent` with `--reviewer-role
render_integrity`, same mechanics as Stage 11. It judges the rendered pixels
against the source and nothing else; the deterministic gate at the end of Stage
10 has already settled every measurable property.

Dispatch `art_direction_reviewer_agent` with `--reviewer-role art_direction`
(Task 10). It judges composition, hierarchy, imagery, and whether the slide
states its claim, and it receives the linter's warnings as context.

All three reviews — scientific, render integrity, art direction — are
independent. A slide reaches `passed` only when all three pass; any one failing
triggers the `revision_required` path scoped to that reviewer's findings.
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -v`
Expected: PASS — the whole suite. The ~30 existing tests recording
`visual_quality` still pass, because the legacy role set is still accepted.

- [ ] **Step 8: Commit**

```bash
git add -A skills/report-slides/agents skills/report-slides/scripts \
        skills/report-slides/SKILL.md
git commit -m "refactor(report-slides): rename the rendering reviewer and centralise the role predicate"
```

---

### Task 10: The art-direction reviewer

**Files:**
- Create: `skills/report-slides/agents/art_direction_reviewer_agent.md`
- Modify: `skills/report-slides/scripts/validate_visual_review.py:31-46`
  (`_ALLOWED_FINDING_KINDS`)
- Modify: `skills/report-slides/scripts/presentation_gates.py`
  (`_FINDING_KINDS`, `_REVIEW_ROLES`, `_FINDING_ROLE_KINDS`,
  `SLIDE_REVIEW_ROLE_SETS`)
- Modify: `skills/report-slides/scripts/presentation_events.py` (next actions)
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py` (new
  persona test)
- Test: `skills/report-slides/scripts/tests/test_reviewer_roles.py` (extend)

**Interfaces:**
- Consumes: `presentation_gates.{SLIDE_REVIEW_ROLE_SETS,
  slide_reviews_complete, missing_slide_review_roles}` (Task 9).
- Produces: the `art_direction` reviewer role and the eight finding kinds spec
  §D5 names: `visual-cliche`, `decorative-noise`, `style-drift`,
  `synthetic-detail`, `meaningless-interface`, `stock-ai-composition`,
  `weak-hierarchy`, `undifferentiated-repetition`.

**Why new finding kinds rather than `other`.** Spec §2.12 records that the
current vocabulary has no word for the defect the user actually reported — the
output looks generically "AI". A defect with no name is a defect that cannot be
tracked, counted, or fixed on purpose. Each kind below is falsifiable by looking
at the slide.

**The vocabulary is the spec's, verbatim.** Spec §D5 names these eight kinds.
Do not add to the list, rename an entry, or substitute a synonym: the reviewer
persona, `presentation_gates`, `validate_visual_review.py`, and the spec must
agree on one string per defect, or a finding recorded under one name cannot be
counted under another.

| Kind | The reviewer can point at |
|---|---|
| `visual-cliche` | A composition the field has seen a thousand times: glowing brains, neural globes, ambient circuitry, flowing data streams |
| `decorative-noise` | Elements carrying no information — gradient washes, floating translucent panels, ornamental glyphs, background texture |
| `style-drift` | This slide's visual language does not match the rest of the deck: different radii, icon language, or illustration style |
| `synthetic-detail` | Detail that was rendered rather than drawn — fake specular highlights, invented UI microcopy, texture with no referent |
| `meaningless-interface` | A depicted screen, dashboard, or console whose contents say nothing and cannot be read |
| `stock-ai-composition` | The framing itself is a generator default: centred hero object, teal-orange haze, lens flare, isometric server city, anonymous person at a laptop |
| `weak-hierarchy` | Nothing on the slide is visually first; every element competes equally |
| `undifferentiated-repetition` | The same card, shape, or icon repeated without the repetition encoding anything |

**Three kinds an earlier draft of this plan proposed are deliberately absent**,
because spec §D5 does not name them and §D5 also freezes the `render_integrity`
vocabulary, so they cannot be moved there either:

- `claim-not-stated` — "the visual decorates the title rather than showing what
  it asserts" is the scientific reviewer's remit; it records `unsupported-claim`.
- `illegible-at-distance` — the deterministic linter's `type-floor` and
  `text-contrast` rules (Tasks 3–5) measure this before any reviewer is
  dispatched, and `render_integrity` keeps `unreadably-small-text`.
- `meaning-by-color-only` — **this concern currently has no owner.** Neither the
  linter nor either reviewer covers "removing colour removes a distinction the
  slide relies on". Do not smuggle it in under `other`: raise it as a spec
  amendment so it gets a name, an owner, and a rubric.

**The linter's warnings arrive as context.** `occupancy`,
`equal-card-repetition`, `spacing-variance`, and `connector-crossing` are
questions, and this reviewer answers them in the record. Answering "yes, the
grid is right here" is a valid outcome; leaving them unanswered is not.

- [ ] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/tests/test_reviewer_roles.py`:

```python
def test_art_direction_is_an_accepted_review_role() -> None:
    """The new gate's role is admissible."""
    assert "art_direction" in gates._REVIEW_ROLES


def test_art_direction_owns_its_own_finding_vocabulary() -> None:
    """The art-direction kinds are not shared with the rendering gate."""
    art = gates._FINDING_ROLE_KINDS["art_direction"]
    assert "visual-cliche" in art
    assert "weak-hierarchy" in art
    assert "clipping" not in art
    assert "visual-cliche" not in gates._FINDING_ROLE_KINDS["render_integrity"]


def test_all_three_roles_are_now_required() -> None:
    """A slide is complete only when every current gate has passed."""
    assert not gates.slide_reviews_complete({"scientific", "render_integrity"})
    assert gates.slide_reviews_complete(
        {"scientific", "render_integrity", "art_direction"})


def test_legacy_role_set_is_still_accepted() -> None:
    """Pre-split decks must not become permanently incomplete."""
    assert gates.slide_reviews_complete({"scientific", "visual_quality"})


def test_missing_roles_reports_the_current_set_in_order() -> None:
    """The outstanding roles are named against the current expectation."""
    assert gates.missing_slide_review_roles(
        {"scientific", "render_integrity"}) == ("art_direction",)
    assert gates.missing_slide_review_roles({"scientific"}) == (
        "render_integrity", "art_direction")


def test_the_art_direction_agent_doc_states_its_remit() -> None:
    """The doc must name its kinds and its boundary, or the gate is decorative."""
    text = (_AGENTS / "art_direction_reviewer_agent.md").read_text(
        encoding="utf-8")
    assert "name: art_direction_reviewer_agent" in text
    assert "reviewer_role: art_direction" in text
    assert "render_integrity_reviewer_agent" in text
    for kind in gates._ART_DIRECTION_KINDS - {"other"}:
        assert kind in text, f"missing finding kind: {kind}"
```

Note that `test_current_role_set_completes_a_slide` from Task 9 is *replaced* by
`test_all_three_roles_are_now_required`, which asserts the opposite. That is
intentional and is a claim about correctness: after Task 10 the two-role set is
no longer complete, because the art-direction gate now exists and a slide that
has not passed it has not been reviewed for the defect class this whole plan
exists to catch. Delete the superseded test in the same commit and say so in the
commit body.

Also append to `skills/report-slides/scripts/tests/test_agent_persona_docs.py`:

```python
def test_art_direction_reviewer_agent_names_stage_and_finding_kinds() -> None:
    text = _read("art_direction_reviewer_agent.md")
    assert "name: art_direction_reviewer_agent" in text
    assert "Stage 12" in text
    assert "Stage Boundary" in text
    assert "validate_visual_style.py" in text
    for kind in ("visual-cliche", "decorative-noise", "style-drift",
                 "synthetic-detail", "meaningless-interface",
                 "stock-ai-composition", "weak-hierarchy",
                 "undifferentiated-repetition"):
        assert kind in text, f"missing finding kind: {kind}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 600 python3 -m pytest skills/report-slides/scripts/tests/test_reviewer_roles.py skills/report-slides/scripts/tests/test_agent_persona_docs.py -v`
Expected: FAIL — `KeyError: 'art_direction'` and a `FileNotFoundError` for the
new doc.

- [ ] **Step 3: Register the role and its finding kinds**

In `skills/report-slides/scripts/presentation_gates.py`, extend `_FINDING_KINDS`
with the eight new kinds, then replace the role tables:

```python
# Spec D5, verbatim and in the spec's order, plus the repository-wide "other".
_ART_DIRECTION_KINDS = frozenset({
    "visual-cliche", "decorative-noise", "style-drift",
    "synthetic-detail", "meaningless-interface", "stock-ai-composition",
    "weak-hierarchy", "undifferentiated-repetition", "other",
})
_FINDING_KINDS = frozenset(_FINDING_KINDS | _ART_DIRECTION_KINDS)
_REVIEW_ROLES = frozenset({
    "scientific", "visual_quality", "render_integrity", "art_direction",
})
_RENDERING_KINDS = frozenset(
    _FINDING_KINDS
    - {"unsupported-claim", "duplicated-content", "missing-limitation",
       "excessive-background", "unnecessary-visual", "weak-continuity"}
    - (_ART_DIRECTION_KINDS - {"other"})
)
_FINDING_ROLE_KINDS = {
    "scientific": frozenset({"unsupported-claim", "other"}),
    "visual_quality": _RENDERING_KINDS,
    "render_integrity": _RENDERING_KINDS,
    "art_direction": _ART_DIRECTION_KINDS,
}

SLIDE_REVIEW_ROLE_ORDER: tuple[str, ...] = (
    "scientific", "render_integrity", "art_direction",
)
SLIDE_REVIEW_ROLE_SETS: tuple[frozenset[str], ...] = (
    frozenset(SLIDE_REVIEW_ROLE_ORDER),
    frozenset({"scientific", "visual_quality"}),
)
```

Define `_ART_DIRECTION_KINDS` and the widened `_FINDING_KINDS` *before*
`_RENDERING_KINDS`, so the subtraction removes the art-direction kinds from the
rendering set. Keep `slide_reviews_complete`, `module_reviews_complete`, and
`missing_slide_review_roles` from Task 9 unchanged — they read
`SLIDE_REVIEW_ROLE_ORDER`, `SLIDE_REVIEW_ROLE_SETS`, and
`MODULE_REVIEW_ROLE_SETS`, which is the whole point of routing the branches
through them. Extending the pipeline to a fourth slide gate later is then a
one-line change to the order tuple.

**`MODULE_REVIEW_ROLE_SETS` does not change in this task.** This is the point
where the slide and module sets part, and the reason is spec §D5: the
art-direction reviewer "judges the **complete slide**, not isolated modules".
Adding `art_direction` to the module set — or, equivalently, pointing the module
branch of `presentation_workflow.py` at `slide_reviews_complete` — puts every
visual module into a permanent `in_review` state, because no dispatcher ever
requests an art-direction review of a fragment. The regression test below is the
guard.

```python
def test_modules_are_not_held_to_the_art_direction_gate() -> None:
    """Spec D5 scopes art direction to the complete slide, not a fragment."""
    assert gates.module_reviews_complete({"scientific", "render_integrity"})
    assert "art_direction" not in set().union(*gates.MODULE_REVIEW_ROLE_SETS)
    assert not gates.slide_reviews_complete({"scientific", "render_integrity"})
```

The last assertion is the pair to the first: the same role set that completes a
module must *not* complete a slide after this task, or the art-direction gate is
not actually gating anything.

In `skills/report-slides/scripts/validate_visual_review.py`, add the eight kinds
to `_ALLOWED_FINDING_KINDS` with a comment naming their owner:

```python
    # Art-direction finding kinds (art_direction_reviewer_agent, Stage 12).
    "visual-cliche",
    "decorative-noise",
    "style-drift",
    "synthetic-detail",
    "meaningless-interface",
    "stock-ai-composition",
    "weak-hierarchy",
    "undifferentiated-repetition",
```

- [ ] **Step 4: Route the next action**

`presentation_events.py` needs no further change: the block Task 9 introduced
already reads `missing_slide_review_roles`, and extending
`SLIDE_REVIEW_ROLE_ORDER` with `art_direction` extends the suggestion chain
automatically. Confirm the fixture at
`skills/report-slides/scripts/tests/test_presentation_state.py:614` still
expects `record_render_integrity_review` — a slide with only `scientific`
recorded is still sent to the rendering review next, because the order is the
workflow's, not the alphabet's.

- [ ] **Step 5: Write the agent doc**

Create `skills/report-slides/agents/art_direction_reviewer_agent.md`:

````markdown
---
name: art_direction_reviewer_agent
description: "Judges whether a slide states its claim, directs the eye, and looks specific to its subject -- hierarchy, composition, imagery, and deck coherence -- independent of rendering correctness and scientific accuracy"
---

# Art Direction Review — Composition and Specificity Gate

## Role Definition

You judge whether the slide is designed, not whether it is drawn correctly.
Three questions decide it: does the visual state the slide's claim, does the
composition tell the eye where to look first, and does the slide look like it
was made for this subject rather than for any technical deck.

You have the authority to require a re-layout. A slide that measures correctly
and renders correctly can still be a bad slide, and this is the only gate that
can say so.

## Stage Boundary

**Assignment:** Stage 12 of the report-slides workflow, independent of both
`scientific_visual_reviewer_agent` (Stage 11) and
`render_integrity_reviewer_agent` (Stage 12).

**You MUST NOT:**
- Judge scientific or semantic correctness — that is Stage 11's gate.
- Report rendering defects — clipping, reflow, crop, missing images, z-order —
  those belong to `render_integrity_reviewer_agent`.
- Re-report anything `scripts/validate_visual_style.py` already measured: safe
  area, overlap, spacing, type size, contrast, palette, connector attachment,
  or component consistency. Those were settled with a ruler before you saw the
  slide, and a prose opinion cannot overturn a measurement.
- Modify the visual you are reviewing — report findings only.

## What the linter hands you

The linter's **warnings** are questions for you, not verdicts:

- `occupancy` — the slide is unusually sparse or unusually full. Is that the
  intent, or is it an unfinished layout?
- `equal-card-repetition` — several identical cards. Is the equality a claim
  that these items rank equally, or an absence of a decision?
- `spacing-variance` — uneven rhythm in a row. Deliberate grouping, or drift?
- `connector-crossing` — several crossings. Inherent to the graph, or fixable
  by reordering the nodes?

Answer each warning that was raised. An unanswered warning is an incomplete
review.

## Review Checklist

- **Hierarchy** — Look at the slide for two seconds. What did you see first? If
  the answer is "nothing in particular" or "the decoration", that is
  `weak-hierarchy`.
- **Specificity** — Would this imagery serve an unrelated deck without change?
  Glowing neural spheres, abstract data cities, light ribbons, ambient
  circuitry, and flowing data streams are the signature of `visual-cliche`.
- **Framing** — Ask where the composition came from rather than what it shows. A
  centred hero object on a teal-orange haze, a lens flare, an isometric server
  city, or an anonymous person at a laptop is `stock-ai-composition`: the
  *framing* is the generator's default, whatever the subject.
- **Information density** — Point at each element and say what it tells the
  reader. Gradient washes, floating translucent panels, ornamental glyphs, and
  background texture that survive this question unanswered are
  `decorative-noise`.
- **Drawn or rendered** — Look for detail nobody decided on: fake specular
  highlights, invented UI microcopy, texture with no referent. That is
  `synthetic-detail`, and it is the most reliable tell that an image was
  generated rather than authored.
- **Depicted interfaces** — If the slide shows a screen, dashboard, or console,
  read it. If its contents say nothing, or cannot be read at all, that is
  `meaningless-interface`. A screenshot that carries no information is worse
  than no screenshot.
- **Repetition** — Count the repeated cards, shapes, or icons, then ask what the
  repetition encodes. If the answer is "nothing, there were four points", that
  is `undifferentiated-repetition`.
- **Deck coherence** — Compare with the neighbouring slides. Different corner
  radii, icon language, or illustration style across the deck is `style-drift`.

## Output Format

```yaml
subject_type: slide | module
subject_id: <slide_id or module_id>
reviewer_role: art_direction
status: passed | failed
round: <int>
linter_warnings_answered:
  - rule: occupancy | equal-card-repetition | spacing-variance | connector-crossing
    answer: <string, why the warning is or is not a defect here>
findings:
  - kind: visual-cliche | decorative-noise | style-drift | synthetic-detail | meaningless-interface | stock-ai-composition | weak-hierarchy | undifferentiated-repetition | other
    description: <string, specific and falsifiable, naming what you looked at and what you saw>
    remedy: <string, the change you are asking for, at the level of layout or art direction>
    source: svg-preview | pptx-render
    scope: {slide: <slide_id>, region: <region_id or module_id>}
    artifact_path: <path to the rendered png this finding refers to>
    disposition: open
```

A finding must name what you looked at. "Feels AI-generated" is not reviewable;
"the illustration is a glowing network sphere that would suit any deck about any
model" is.
````

- [ ] **Step 6: Run tests to verify they pass**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -v`
Expected: PASS — the whole suite.

Existing tests that record only `scientific` + `visual_quality` still complete
via the legacy role set. If any test recorded `scientific` +
`render_integrity` and expected `passed`, it must now also record
`art_direction`; update the fixture, not the assertion.

- [ ] **Step 7: Commit**

```bash
git add -A skills/report-slides/agents skills/report-slides/scripts
git commit -m "feat(report-slides): add an independent art-direction review gate

Replaces test_current_role_set_completes_a_slide: after this change the
scientific + render_integrity pair is deliberately no longer a complete review,
because a slide that has not passed art direction has not been reviewed for
composition, hierarchy, or imagery specificity. The legacy scientific +
visual_quality pair is still accepted so pre-split decks still complete."
```

---

## Phase 5: Generative Art Direction

Spec §2.1 records the finding this phase exists for: the deck's own shipped
example illustration — a lab-coated figure at a laptop, a glowing neural sphere,
light ribbons, an abstract data city — passed visual review with `"status":
"passed"` and one unrelated rendering note. Its `prompt.md` already excluded
`busy background`, `excessive glow`, and `photorealistic faces`. Excluding
adjectives did not work, because the problem was never an adjective.

The remedy in spec §D6 has three parts: generative illustration becomes opt-in
rather than a default route (Task 12); prompts are anchored to a named,
curated style rather than assembled from adjectives (Task 11); and the motifs
that constitute the failure mode are named and refused (Task 11), not merely
discouraged.

---

### Task 11: The style-anchor registry and the banned-motif scan

**Files:**
- Create: `skills/report-slides/references/style-anchors/anchors.yaml`
- Create: `skills/report-slides/references/style-anchors/README.md`
- Create: `skills/report-slides/scripts/style_anchors.py`
- Test: `skills/report-slides/scripts/tests/test_style_anchors.py`

**Interfaces:**
- Consumes: `design_tokens.DesignTokens` (plan 1, Task 2).
- Produces, used by Tasks 12 and 13:
  - `ANCHORS_PATH: Path`
  - `class AnchorError(ValueError)`
  - `@dataclass(frozen=True) class ReferenceImage` — `path: Path`,
    `sha256: str`
  - `@dataclass(frozen=True) class StyleAnchor` — `anchor_id`, `name`,
    `summary`, `applies_to`, `composition`, `line_treatment`, `palette_roles`,
    `forbidden`, `reference_images: Tuple[ReferenceImage, ...]` (never empty)
  - `load_anchors(path: Union[str, Path] = ANCHORS_PATH)
    -> Dict[str, StyleAnchor]` — returns `{}` for the shipped empty registry
  - `get_anchor(anchor_id: str, path: Union[str, Path] = ANCHORS_PATH)
    -> StyleAnchor`
  - `anchor_available(path: Union[str, Path] = ANCHORS_PATH) -> bool` — whether
    the generative route is open at all
  - `CANDIDATE_COUNT: int = 3` — spec D6's blind-ranking width, so Task 12
    validates against one constant rather than a literal
  - `BANNED_MOTIFS: Tuple[Tuple[str, Tuple[str, ...]], ...]` — `(motif_id,
    trigger phrases)`
  - `scan_for_banned_motifs(text: str) -> List[str]`
  - `prompt_fragment(anchor: StyleAnchor, tokens: DesignTokens) -> str`

**An anchor is a reference image, not a description.** Spec §D6 is explicit:
the registry holds styles "each identified by **actual reference images with
recorded digests** — not adjective lists". §2.1 is the evidence for that
wording. The prompt behind the shipped counter-example already excluded `busy
background`, `excessive glow`, and `photorealistic faces`, and still produced a
lab-coated figure at a laptop under a glowing neural sphere. Adjectives — even
negative ones — are read by the model as a region of its own prior, and that
prior *is* the look being rejected. An image is not.

So `reference_images` is a required, non-empty field, and each entry records a
SHA-256 digest that `load_anchors` verifies against the file on disk. A digest
mismatch is an error, not a warning: an anchor whose reference has been swapped
underneath it is no longer the anchor the deck's earlier illustrations were
ranked against, and `style-drift` is precisely the finding that produces.

The prose fields stay — `composition`, `line_treatment`, `palette_roles`,
`forbidden` — but they are *subordinate* to the images. They say what to attend
to in the reference and bind the anchor to the token palette. They are not the
anchor's identity, and an entry that carries only prose is refused.

**The registry ships empty.** Spec §D6: "Populating the anchor registry with
reference images is a human action; this design specifies the mechanism and
ships the registry empty with a documented procedure." That is not a gap in this
task, it is the task's contract. Until a human curates references, `get_anchor`
raises and the generative route is closed — which routes every module to the
native editorial composition, exactly as D6's last clause requires. Do **not**
seed the registry with prose anchors to make the route work: that reinstates the
failure this phase exists to remove, and the test below asserts the registry is
empty on a fresh checkout.

**What the scan can and cannot do.** `scan_for_banned_motifs` reads *prompt
text*. It catches an author asking for a glowing neural sphere; it cannot catch
a model producing one unasked. That residual case is the art-direction
reviewer's `visual-cliche` finding (Task 10). Both are needed; neither is
sufficient. Do not present the scan as a guarantee.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_style_anchors.py`:

```python
"""Tests for the style-anchor registry and the banned-motif scan."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Tuple

import pytest
import yaml
from PIL import Image

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from style_anchors import (
    ANCHORS_PATH, CANDIDATE_COUNT, AnchorError, BANNED_MOTIFS,
    anchor_available, get_anchor, load_anchors, prompt_fragment,
    scan_for_banned_motifs,
)


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _write_reference(directory: Path, name: str) -> Tuple[Path, str]:
    """Write a small PNG and return its path and digest.

    A four-pixel image is enough: the registry checks file integrity, not
    picture content. The digest is computed here rather than hard-coded, because
    a literal would pin this test to one Pillow release's PNG encoder.

    Args:
        directory: Where to write the file.
        name: File name to use.

    Returns:
        `(path, sha256_hex)`.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (30, 58, 95)).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())
    return path, hashlib.sha256(buffer.getvalue()).hexdigest()


def _registry(tmp_path: Path, **overrides: object) -> Path:
    """Write a one-anchor registry with a real reference image.

    Args:
        tmp_path: Test temporary directory.
        **overrides: Entry fields to replace or, when the value is None, drop.

    Returns:
        Path to the written `anchors.yaml`.
    """
    reference, digest = _write_reference(tmp_path / "refs", "schematic-01.png")
    entry = {
        "id": "technical-schematic",
        "name": "Technical schematic",
        "summary": "A flat drafted diagram in the manner of a paper figure.",
        "applies_to": ["system architectures"],
        "composition": "Orthogonal arrangement on a single plane.",
        "line_treatment": "Uniform-weight outlines, flat fills.",
        "palette_roles": ["primary", "body", "line", "bg"],
        "forbidden": ["glow or bloom", "photographic texture"],
        "reference_images": [
            {"path": reference.name, "sha256": digest},
        ],
    }
    for key, value in overrides.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    path = tmp_path / "refs" / "anchors.yaml"
    path.write_text(yaml.safe_dump({"anchors": [entry]}), encoding="utf-8")
    return path


def test_the_shipped_registry_is_empty_by_design() -> None:
    """Spec D6 ships the registry empty; populating it is a human action.

    Seeding it with prose anchors is what this phase exists to prevent, so the
    emptiness is asserted rather than left to convention. If this test fails
    because someone added an anchor with real curated references, that is the
    intended workflow -- update the test in the same commit and say whose
    references were added.
    """
    assert ANCHORS_PATH.is_file()
    assert load_anchors() == {}
    assert anchor_available() is False


def test_an_empty_registry_closes_the_generative_route() -> None:
    """With no anchor, `get_anchor` refuses and names the procedure."""
    with pytest.raises(AnchorError) as excinfo:
        get_anchor("technical-schematic")
    message = str(excinfo.value)
    assert "empty" in message
    assert "style-anchors/README.md" in message


def test_a_populated_anchor_declares_its_full_contract(tmp_path: Path) -> None:
    """A partial anchor cannot direct an illustration."""
    anchors = load_anchors(_registry(tmp_path))
    anchor = anchors["technical-schematic"]
    assert anchor.anchor_id == "technical-schematic"
    assert anchor.summary
    assert anchor.composition
    assert anchor.line_treatment
    assert anchor.applies_to
    assert anchor.palette_roles
    assert anchor.forbidden
    assert anchor.reference_images


def test_an_anchor_without_reference_images_is_rejected(
    tmp_path: Path,
) -> None:
    """Prose alone is the adjective list spec D6 refuses."""
    with pytest.raises(AnchorError) as excinfo:
        load_anchors(_registry(tmp_path, reference_images=None))
    assert "reference_images" in str(excinfo.value)


def test_an_empty_reference_image_list_is_rejected(tmp_path: Path) -> None:
    """An empty list is the same defect as a missing field."""
    with pytest.raises(AnchorError):
        load_anchors(_registry(tmp_path, reference_images=[]))


def test_a_missing_reference_file_is_rejected(tmp_path: Path) -> None:
    """A registry may not cite a reference that is not on disk."""
    path = _registry(tmp_path)
    (tmp_path / "refs" / "schematic-01.png").unlink()
    with pytest.raises(AnchorError) as excinfo:
        load_anchors(path)
    assert "schematic-01.png" in str(excinfo.value)


def test_a_stale_reference_digest_is_rejected(tmp_path: Path) -> None:
    """A reference swapped underneath the anchor is a different anchor.

    Two illustrations ranked against different references do not belong to the
    same deck, which is exactly the `style-drift` finding the art-direction
    reviewer reports. Failing closed here is cheaper than finding it at review.
    """
    path = _registry(tmp_path)
    reference = tmp_path / "refs" / "schematic-01.png"
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buffer, format="PNG")
    reference.write_bytes(buffer.getvalue())
    with pytest.raises(AnchorError) as excinfo:
        load_anchors(path)
    message = str(excinfo.value)
    assert "digest" in message
    assert "schematic-01.png" in message


def test_anchor_palette_roles_exist_in_the_token_file(
    tokens: DesignTokens, tmp_path: Path,
) -> None:
    """An anchor may only name colour roles the design system defines."""
    for anchor in load_anchors(_registry(tmp_path)).values():
        for role in anchor.palette_roles:
            assert tokens.color(role)


def test_get_anchor_rejects_an_unknown_id(tmp_path: Path) -> None:
    """An unknown anchor fails loudly rather than falling back to a default."""
    with pytest.raises(AnchorError) as excinfo:
        get_anchor("vibes", _registry(tmp_path))
    assert "vibes" in str(excinfo.value)


def test_a_malformed_registry_is_rejected(tmp_path: Path) -> None:
    """A registry missing required fields is an error, not a partial load."""
    bad = tmp_path / "anchors.yaml"
    bad.write_text("anchors:\n  - id: broken\n    name: Broken\n",
                   encoding="utf-8")
    with pytest.raises(AnchorError):
        load_anchors(bad)


def test_the_candidate_count_matches_the_spec() -> None:
    """Spec D6 requires three candidates ranked blind; Task 12 reads this."""
    assert CANDIDATE_COUNT == 3


def test_banned_motifs_name_the_documented_failure_mode() -> None:
    """The registry must name the motifs the shipped example actually used."""
    motif_ids = {motif_id for motif_id, _ in BANNED_MOTIFS}
    for expected in ("glowing-neural-sphere", "light-ribbons",
                     "abstract-data-city", "anonymous-figure-at-laptop"):
        assert expected in motif_ids


def test_the_scan_catches_the_shipped_examples_prompt() -> None:
    """The prompt that produced the documented failure must not pass."""
    prompt = ("A researcher in a white lab coat at a laptop, with a glowing "
              "neural network sphere and flowing light ribbons above an "
              "abstract data city skyline.")
    hits = scan_for_banned_motifs(prompt)
    assert "glowing-neural-sphere" in hits
    assert "light-ribbons" in hits
    assert "abstract-data-city" in hits
    assert "anonymous-figure-at-laptop" in hits


def test_the_scan_is_case_insensitive() -> None:
    """Capitalisation must not be an escape hatch."""
    assert scan_for_banned_motifs("A GLOWING NEURAL NETWORK sphere")


def test_a_specific_prompt_passes_the_scan() -> None:
    """A prompt about the actual subject is not penalised."""
    prompt = ("A cross-section of a three-stage retrieval pipeline showing "
              "document chunks entering an index and ranked passages leaving "
              "it, drawn as a flat schematic.")
    assert scan_for_banned_motifs(prompt) == []


def test_prompt_fragment_binds_the_anchor_to_the_tokens(
    tokens: DesignTokens, tmp_path: Path,
) -> None:
    """The generated fragment carries concrete hex values, not role names."""
    anchor = get_anchor("technical-schematic", _registry(tmp_path))
    fragment = prompt_fragment(anchor, tokens)
    assert "technical-schematic" in fragment
    assert "#" in fragment
    for role in anchor.palette_roles:
        assert tokens.color(role) in fragment
    for forbidden in anchor.forbidden:
        assert forbidden in fragment


def test_prompt_fragment_cites_the_reference_images(
    tokens: DesignTokens, tmp_path: Path,
) -> None:
    """The fragment must point at the reference, not only describe it.

    A prompt that carries the prose but drops the reference is the adjective
    list again. The digest travels with it so the record says which reference
    the illustration was directed against.
    """
    anchor = get_anchor("technical-schematic", _registry(tmp_path))
    fragment = prompt_fragment(anchor, tokens)
    for reference in anchor.reference_images:
        assert reference.path.name in fragment
        assert reference.sha256[:12] in fragment


def test_prompt_fragment_is_itself_clean(
    tokens: DesignTokens, tmp_path: Path,
) -> None:
    """The registry must not smuggle a banned motif into its own output."""
    for anchor in load_anchors(_registry(tmp_path)).values():
        assert scan_for_banned_motifs(
            prompt_fragment(anchor, tokens)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_style_anchors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'style_anchors'`.

- [ ] **Step 3: Write the registry**

Create `skills/report-slides/references/style-anchors/anchors.yaml`:

```yaml
# Style anchors for generative illustration.
#
# THIS REGISTRY SHIPS EMPTY, BY DESIGN. Spec D6: "Populating the anchor registry
# with reference images is a human action; this design specifies the mechanism
# and ships the registry empty with a documented procedure."
#
# While it is empty, `scripts/style_anchors.py` refuses every anchor lookup and
# the generative illustration route is closed: modules downgrade to a native
# editorial composition. That is the intended state, not a defect.
#
# An anchor is identified by ACTUAL REFERENCE IMAGES with recorded digests, not
# by an adjective list. See README.md for the procedure and for the three
# candidate anchors this deck expects to curate first.
#
# Entry shape:
#
#   - id: technical-schematic
#     name: Technical schematic
#     summary: >-
#       One sentence saying what the anchor is.
#     applies_to: [system architectures, data pipelines]
#     composition: >-
#       What to attend to in the frame arrangement of the references.
#     line_treatment: >-
#       How lines, fills, and light behave in the references.
#     palette_roles: [primary, body, line, bg]   # roles the token file defines
#     forbidden: [glow or bloom, photographic texture]
#     reference_images:                          # required, never empty
#       - path: technical-schematic/01-retrieval-pipeline.png
#         sha256: <64 hex characters, verified on load>

anchors: []
```

Create `skills/report-slides/references/style-anchors/README.md`:

```markdown
# Style anchors

A style anchor is the visual language an illustration must belong to, and it is
identified by **reference images**, not by words. Spec §D6 requires this, and
§2.1 is the evidence: the prompt behind this deck's own failed illustration
already excluded `busy background`, `excessive glow`, and `photorealistic
faces`, and still produced a lab-coated figure at a laptop beneath a glowing
neural sphere. Adjective lists — even lists of exclusions — name a region of the
image model's prior, and that prior is the look being rejected. An image is not.

## This registry ships empty

`anchors.yaml` contains `anchors: []`. While it is empty:

- `style_anchors.get_anchor(...)` raises `AnchorError`;
- `anchor_available()` returns `False`;
- `scripts/validate_generative_prompt.py` rejects every generative record;
- every module that would have used generative illustration downgrades to a
  native editorial composition, per spec §D6's final clause.

That is the designed resting state. **Do not seed the registry with prose-only
entries to reopen the route** — an entry without `reference_images` is refused
by the loader, and `tests/test_style_anchors.py` asserts the shipped registry is
empty.

## Procedure for adding an anchor

1. **Curate 3–5 reference images.** They must be images this project is licensed
   to keep, and they must agree with one another: an anchor whose references
   disagree cannot rank a candidate. Do not use generated images as references —
   that closes the loop this registry exists to open.
2. **Commit them** under
   `references/style-anchors/<anchor-id>/`, using stable, descriptive names.
3. **Record each digest**:
   `sha256sum references/style-anchors/<anchor-id>/*.png`
4. **Write the entry** in `anchors.yaml` with every required field, listing each
   reference under `reference_images` with its `path` (relative to
   `references/style-anchors/`) and `sha256`.
5. **Write the prose fields against the images.** `composition` and
   `line_treatment` say what to attend to *in those references*; they do not
   stand in for them. `palette_roles` must name roles the design-token file
   defines; `forbidden` names what the anchor refuses.
6. **Update `test_the_shipped_registry_is_empty_by_design`** in the same commit,
   and say in the commit body whose references were added and under what
   licence.
7. Run `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_style_anchors.py -v`.

A digest mismatch is a hard error on load. If a reference is legitimately
replaced, update its digest in the same commit — an anchor whose references
changed silently is a different anchor, and every illustration ranked against
the old one now belongs to a different deck. That is the `style-drift` finding.

## Candidate anchors to curate first

These are the three visual languages this deck's subject matter calls for. They
are recorded here as *briefs for a curator*, deliberately not as registry
entries: without reference images they would be exactly the adjective lists §D6
refuses.

| The slide is about | Candidate anchor | What the references should show |
|---|---|---|
| How a system is structured, or how data moves through it | `technical-schematic` | Flat drafted diagrams in the manner of a paper figure: orthogonal arrangement on one plane, a single dominant flow direction, generous margin, uniform-weight outlines, flat fills, no perspective, no glow, no shadow |
| A concrete object, sample, or apparatus | `annotated-specimen` | Scientific plates: one centred subject at consistent scale, callout lines to a few labelled parts, plain ground, fine contour lines with restrained flat shading, no rim lighting, no background scenery |
| A relationship between measured quantities | `quantitative-abstract` | Non-figurative compositions built only from the quantities under discussion, one clear reading order, flat marks and rules, no texture, no illumination, no human figures, no imaginary interfaces |

If no candidate fits a slide, that is a signal the slide may not need a
generative illustration at all. Reach for a deterministic diagram first; see
`references/diagram-patterns.md`.

Anchors are deck-wide, and spec §D6 allows **at most one generative style per
deck**. Adding a second is a design-system decision, not a per-slide
convenience: two overlapping anchors produce a deck that drifts, which is the
`style-drift` finding the art-direction reviewer reports.

## Banned motifs

`scripts/style_anchors.py` also carries `BANNED_MOTIFS`: the specific imagery
that constitutes the failure mode this registry exists to prevent — glowing
neural spheres, flowing light ribbons, abstract data cities, anonymous figures
at laptops, and their neighbours. `scan_for_banned_motifs` refuses a prompt that
asks for one.

The scan reads prompts, not images. A model can still produce a banned motif
unasked; that case is caught at review as a `visual-cliche` or
`stock-ai-composition` finding. The scan is a floor, not a guarantee.
```

- [ ] **Step 4: Write the loader**

Create `skills/report-slides/scripts/style_anchors.py`:

```python
#!/usr/bin/env python3
"""Style-anchor registry and banned-motif scan for generative illustration."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple, Union

import yaml

from design_tokens import DesignTokens

ANCHORS_PATH = (Path(__file__).resolve().parent.parent
                / "references" / "style-anchors" / "anchors.yaml")

_REQUIRED_FIELDS = ("id", "name", "summary", "applies_to", "composition",
                    "line_treatment", "palette_roles", "forbidden",
                    "reference_images")

# Spec D6: "Three candidates are generated and ranked blind against the anchor."
# Task 12 validates the generative record against this constant rather than a
# literal, so the width is stated once.
CANDIDATE_COUNT: int = 3

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

BANNED_MOTIFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("glowing-neural-sphere",
     ("glowing neural", "neural network sphere", "glowing brain",
      "luminous network", "glowing orb of nodes")),
    ("light-ribbons",
     ("light ribbon", "flowing light", "light stream", "energy ribbon",
      "swirling light")),
    ("abstract-data-city",
     ("data city", "city of data", "digital cityscape", "skyline of data",
      "abstract cityscape")),
    ("anonymous-figure-at-laptop",
     ("lab coat", "figure at a laptop", "researcher at a laptop",
      "person at a laptop", "silhouette at a computer")),
    ("circuit-board-metaphor",
     ("glowing circuit", "circuit board background", "circuitry pattern",
      "circuit-like", "circuit pathway")),
    ("holographic-interface",
     ("holographic", "floating ui panel", "futuristic interface",
      "translucent dashboard floating")),
    ("binary-rain",
     ("binary rain", "falling ones and zeros", "cascading code")),
    ("handshake-of-human-and-machine",
     ("robot hand", "human hand touching", "handshake with a robot")),
    ("idea-lightbulb",
     ("lightbulb moment", "glowing lightbulb", "bulb of ideas")),
    ("gears-as-thinking",
     ("gears turning in", "cogs in the mind", "gears as thought")),
)


class AnchorError(ValueError):
    """Raised when the anchor registry is malformed or an anchor is unknown."""


@dataclass(frozen=True)
class ReferenceImage:
    """One curated reference image, pinned by content.

    Attributes:
        path: Resolved path to the image on disk.
        sha256: The digest recorded in the registry, verified on load.
    """

    path: Path
    sha256: str


@dataclass(frozen=True)
class StyleAnchor:
    """One bounded visual language an illustration must belong to.

    The anchor's identity is `reference_images`. The prose fields say what to
    attend to in those references and bind the anchor to the token palette; they
    do not stand in for the images. Spec D6 requires this: an anchor described
    only in words is the adjective list that produced the failure in spec 2.1.

    Attributes:
        anchor_id: Stable identifier cited by prompts.
        name: Human-readable name.
        summary: What the anchor is, in one sentence.
        applies_to: Subject kinds this anchor suits.
        composition: What to attend to in the references' frame arrangement.
        line_treatment: How lines, fills, and light behave in the references.
        palette_roles: Colour roles from the design-token file that may appear.
        forbidden: What this anchor refuses.
        reference_images: The curated references. Never empty.
    """

    anchor_id: str
    name: str
    summary: str
    applies_to: Tuple[str, ...]
    composition: str
    line_treatment: str
    palette_roles: Tuple[str, ...]
    forbidden: Tuple[str, ...]
    reference_images: Tuple[ReferenceImage, ...]


def _load_reference_images(entry: Mapping[str, Any], anchor_id: str,
                           base_dir: Path) -> Tuple[ReferenceImage, ...]:
    """Resolve and verify one anchor's reference images.

    Args:
        entry: The raw registry entry.
        anchor_id: The anchor being loaded, for error messages.
        base_dir: Directory the registry's relative paths resolve against.

    Returns:
        The verified references, in registry order.

    Raises:
        AnchorError: If the list is empty or malformed, a digest is not a
            64-character hex string, a file is missing, or a file's content does
            not match its recorded digest.
    """
    raw = entry.get("reference_images")
    if not isinstance(raw, list) or not raw:
        raise AnchorError(
            f"anchor {anchor_id!r} must list at least one entry under "
            f"'reference_images'; an anchor described only in prose is the "
            f"adjective list spec D6 refuses")
    references: List[ReferenceImage] = []
    for position, item in enumerate(raw):
        if not isinstance(item, dict) or not item.get("path") \
                or not item.get("sha256"):
            raise AnchorError(
                f"anchor {anchor_id!r} reference {position} must be a mapping "
                f"with 'path' and 'sha256'")
        digest = str(item["sha256"]).strip().lower()
        if not _SHA256_RE.match(digest):
            raise AnchorError(
                f"anchor {anchor_id!r} reference {item['path']!r} records "
                f"{digest!r}, which is not a SHA-256 digest")
        image_path = (base_dir / str(item["path"])).resolve()
        try:
            content = image_path.read_bytes()
        except OSError as exc:
            raise AnchorError(
                f"anchor {anchor_id!r} cites reference {item['path']!r} which "
                f"cannot be read at {image_path}: {exc}") from exc
        actual = hashlib.sha256(content).hexdigest()
        if actual != digest:
            raise AnchorError(
                f"anchor {anchor_id!r} reference {item['path']!r} has digest "
                f"{actual} but the registry records {digest}. A reference "
                f"swapped underneath an anchor is a different anchor: every "
                f"illustration ranked against the old one now belongs to a "
                f"different deck. Update the digest deliberately, in the same "
                f"commit as the replacement.")
        references.append(ReferenceImage(path=image_path, sha256=digest))
    return tuple(references)


def load_anchors(path: Union[str, Path] = ANCHORS_PATH
                 ) -> Dict[str, StyleAnchor]:
    """Load and validate the anchor registry.

    Args:
        path: Path to an `anchors.yaml` registry.

    Returns:
        A mapping from anchor id to anchor.

    Raises:
        AnchorError: If the file is missing, unparsable, an entry omits a
            required field, or a reference image is missing or does not match
            its recorded digest.
    """
    registry_path = Path(path)
    try:
        raw_text = registry_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AnchorError(f"cannot read anchor registry {registry_path}: {exc}"
                          ) from exc
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise AnchorError(f"cannot parse anchor registry {registry_path}: {exc}"
                          ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("anchors"), list):
        raise AnchorError(
            f"{registry_path} must contain a top-level 'anchors' list")

    anchors: Dict[str, StyleAnchor] = {}
    for position, entry in enumerate(data["anchors"]):
        if not isinstance(entry, dict):
            raise AnchorError(f"{registry_path} anchor {position} is not a mapping")
        missing = [field for field in _REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            raise AnchorError(
                f"{registry_path} anchor {entry.get('id', position)!r} omits "
                f"required field(s): {', '.join(missing)}")
        anchor_id = str(entry["id"])
        if anchor_id in anchors:
            raise AnchorError(f"{registry_path} declares {anchor_id!r} twice")
        anchors[anchor_id] = StyleAnchor(
            anchor_id=anchor_id,
            name=str(entry["name"]),
            summary=str(entry["summary"]).strip(),
            applies_to=tuple(str(item) for item in entry["applies_to"]),
            composition=str(entry["composition"]).strip(),
            line_treatment=str(entry["line_treatment"]).strip(),
            palette_roles=tuple(str(item) for item in entry["palette_roles"]),
            forbidden=tuple(str(item) for item in entry["forbidden"]),
            reference_images=_load_reference_images(
                entry, anchor_id, registry_path.parent),
        )
    # An empty registry is the shipped state, not an error: spec D6 ships it
    # empty and makes populating it a human action. `get_anchor` is where that
    # state becomes a refusal, so the caller learns it at the point of use.
    return anchors


def anchor_available(path: Union[str, Path] = ANCHORS_PATH) -> bool:
    """Return whether any anchor is registered.

    Args:
        path: Path to the registry.

    Returns:
        True when at least one anchor is curated. False means the generative
        illustration route is closed and modules downgrade to a native
        editorial composition.

    Raises:
        AnchorError: If the registry exists but is malformed.
    """
    return bool(load_anchors(path))


def get_anchor(anchor_id: str,
               path: Union[str, Path] = ANCHORS_PATH) -> StyleAnchor:
    """Return one anchor by id.

    Args:
        anchor_id: The anchor to fetch.
        path: Path to the registry.

    Returns:
        The anchor.

    Raises:
        AnchorError: If the id is not registered. There is deliberately no
            default anchor: silently substituting one would reintroduce the
            unanchored prompt this registry exists to prevent.
    """
    anchors = load_anchors(path)
    if not anchors:
        raise AnchorError(
            f"the style-anchor registry at {Path(path)} is empty, so the "
            f"generative illustration route is closed and this module must "
            f"downgrade to a native editorial composition. Populating the "
            f"registry with curated reference images is a human action: see "
            f"references/style-anchors/README.md.")
    if anchor_id not in anchors:
        raise AnchorError(
            f"unknown style anchor {anchor_id!r}; registered anchors: "
            f"{', '.join(sorted(anchors))}")
    return anchors[anchor_id]


def scan_for_banned_motifs(text: str) -> List[str]:
    """Return the banned motifs a prompt asks for.

    Args:
        text: Prompt text.

    Returns:
        The ids of every banned motif whose trigger phrases appear, in registry
        order. An empty list is not a guarantee that the produced image is
        clean; it only means the prompt did not ask for a known motif.
    """
    haystack = re.sub(r"\s+", " ", text.lower())
    hits: List[str] = []
    for motif_id, phrases in BANNED_MOTIFS:
        if any(phrase in haystack for phrase in phrases):
            hits.append(motif_id)
    return hits


def prompt_fragment(anchor: StyleAnchor, tokens: DesignTokens) -> str:
    """Render an anchor as the art-direction block of a prompt.

    Args:
        anchor: The anchor to render.
        tokens: The resolved token set, used to expand palette roles into hex.

    Returns:
        A prompt fragment naming the anchor, the reference images the candidate
        will be ranked against, its composition and line treatment, its concrete
        palette, and what it refuses.

    Raises:
        TokenError: If the anchor names a colour role the token file lacks.
    """
    palette = ", ".join(
        f"{role} {tokens.color(role)}" for role in anchor.palette_roles)
    refusals = "; ".join(anchor.forbidden)
    # The references are named, with a digest prefix, so the recorded prompt
    # says which images the candidate was directed against. A fragment carrying
    # only the prose is the adjective list again.
    references = "; ".join(
        f"{reference.path.name} ({reference.sha256[:12]})"
        for reference in anchor.reference_images)
    return (
        f"style_anchor: {anchor.anchor_id} ({anchor.name}). "
        f"{anchor.summary} "
        f"Match these reference images: {references}. "
        f"Composition: {anchor.composition} "
        f"Line treatment: {anchor.line_treatment} "
        f"Palette, and no colour outside it: {palette}. "
        f"Do not include: {refusals}."
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_style_anchors.py -v`
Expected: PASS — 18 passed.

`test_prompt_fragment_is_itself_clean` is the sharp one: if an anchor's own
`forbidden` list phrases a refusal using a banned trigger — writing "no glowing
neural sphere" rather than "no glow or bloom" — the fragment fails its own scan.
Fix the anchor wording, not the scan.

- [ ] **Step 6: Commit**

```bash
git add skills/report-slides/references/style-anchors \
        skills/report-slides/scripts/style_anchors.py \
        skills/report-slides/scripts/tests/test_style_anchors.py
git commit -m "feat(report-slides): add a style-anchor registry and banned-motif scan"
```

---

### Task 12: Make generative illustration opt-in and anchor its prompts

**Files:**
- Create: `skills/report-slides/scripts/validate_generative_prompt.py`
- Test: `skills/report-slides/scripts/tests/test_validate_generative_prompt.py`
- Modify: `skills/report-slides/references/generative-visuals.md` —
  `## Selection gate` (lines 3-14) and `## Prompt record` (lines 16-46)
- Modify: `skills/report-slides/agents/conceptual_illustration_worker_agent.md`
  — the `Classify` step of the Production Procedure
- Modify: `skills/report-slides/agents/research_narrative_planner_agent.md:38`
  — the `intended_visual_type` guidance
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py:94-101`

**Interfaces:**
- Consumes: `style_anchors.{AnchorError, get_anchor, load_anchors,
  prompt_fragment, scan_for_banned_motifs}` (Task 11);
  `design_tokens.{DEFAULT_TOKENS_PATH, DesignTokens}` (plan 1, Task 2).
- Produces, used by Task 13:
  - `REQUIRED_FIELDS: Tuple[str, ...]`
  - `parse_prompt_record(path: Union[str, Path]) -> Dict[str, Any]`
  - `validate_prompt_record(record: Mapping[str, Any],
    anchors_path: Path = ANCHORS_PATH) -> List[str]`
  - `main() -> None`

**The route default is inverted.** `conceptual_illustration_worker_agent.md`
currently states that "`generative` ([V:AI]) is the default for conceptual
illustrations". Spec §D6 makes it the last resort: a deterministic diagram is
tried first, and the generative route requires a recorded justification naming
what a diagram could not carry. This is the single highest-leverage change in
this phase — the shipped failure was produced by a route that nobody had to
choose.

**The prompt record grows two required fields.** `style_anchor` names a
registered anchor; `illustration_rationale` states what a deterministic diagram
could not have carried. Both are validated. A record whose free text asks for a
banned motif is rejected outright.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_validate_generative_prompt.py`:

```python
"""Tests for the generative prompt-record contract."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml
from PIL import Image

from style_anchors import CANDIDATE_COUNT
from validate_generative_prompt import (
    parse_prompt_record, validate_prompt_record,
)

_SKILL_DIR = Path(__file__).resolve().parents[2]
_SCRIPTS = _SKILL_DIR / "scripts"
_CLI = _SCRIPTS / "validate_generative_prompt.py"


@pytest.fixture()
def anchors(tmp_path: Path) -> Path:
    """Write a one-anchor registry with a real reference image.

    The shipped registry is empty by design (spec D6), so a test that needs a
    resolvable anchor must supply one. Building it here also keeps the test
    independent of whichever anchors a human later curates.
    """
    directory = tmp_path / "anchors"
    directory.mkdir()
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (30, 58, 95)).save(buffer, format="PNG")
    (directory / "schematic-01.png").write_bytes(buffer.getvalue())
    registry = directory / "anchors.yaml"
    registry.write_text(yaml.safe_dump({"anchors": [{
        "id": "technical-schematic",
        "name": "Technical schematic",
        "summary": "A flat drafted diagram in the manner of a paper figure.",
        "applies_to": ["system architectures"],
        "composition": "Orthogonal arrangement on a single plane.",
        "line_treatment": "Uniform-weight outlines, flat fills.",
        "palette_roles": ["primary", "body", "line", "bg"],
        "forbidden": ["glow or bloom"],
        "reference_images": [{
            "path": "schematic-01.png",
            "sha256": hashlib.sha256(buffer.getvalue()).hexdigest(),
        }],
    }]}), encoding="utf-8")
    return registry


def _candidates(count: int = CANDIDATE_COUNT,
                matching: int = 1) -> List[Dict[str, Any]]:
    """Build a ranked candidate list.

    Args:
        count: How many candidates to produce.
        matching: How many of them match the anchor, taken from the top rank
            downwards.

    Returns:
        Candidate entries in rank order.
    """
    return [
        {"id": f"c{index + 1}",
         "asset": f"renders/candidate-{index + 1:02d}.png",
         "rank": index + 1,
         "matches_anchor": index < matching}
        for index in range(count)
    ]


def _record(**overrides: Any) -> Dict[str, Any]:
    """Build a valid prompt record, then apply overrides."""
    record: Dict[str, Any] = {
        "purpose": "Show how retrieved passages enter the ranking stage.",
        "illustration_rationale": (
            "The claim is about the shape of the flow, which the deterministic "
            "diagram route cannot render at the required level of abstraction."),
        "style_anchor": "technical-schematic",
        "composition": "Three stages left to right, open margin above.",
        "subject": "A retrieval pipeline and its ranked output.",
        "palette": "Design-token roles primary, body, line, card, bg.",
        "lighting": "Flat, no directional light.",
        "empty_annotation_regions": "Upper third.",
        "exclusions": ["prose", "labels", "legends", "exact values",
                       "watermarks", "signatures"],
        "aspect_ratio": "16:9",
        "references": [],
        "changed_regions": [],
        "candidates": _candidates(),
        "ranking": {"blinded": True, "ranked_by": "art_direction"},
        "selected": "c1",
    }
    record.update(overrides)
    return record


def test_a_complete_record_validates(anchors: Path) -> None:
    """The reference record passes."""
    assert validate_prompt_record(_record(), anchors) == []


def test_a_missing_style_anchor_is_rejected(anchors: Path) -> None:
    """An unanchored prompt is the failure mode; it cannot be optional."""
    record = _record()
    del record["style_anchor"]
    errors = validate_prompt_record(record, anchors)
    assert any("style_anchor" in error for error in errors)


def test_an_unknown_style_anchor_is_rejected(anchors: Path) -> None:
    """Citing an anchor that does not exist is not anchoring."""
    errors = validate_prompt_record(_record(style_anchor="vibes"), anchors)
    assert any("vibes" in error for error in errors)


def test_an_empty_registry_rejects_every_record() -> None:
    """With no curated anchor the generative route is closed, not permissive."""
    errors = validate_prompt_record(_record())
    assert errors
    assert any("empty" in error for error in errors)


def test_a_missing_rationale_is_rejected(anchors: Path) -> None:
    """The generative route must be justified, not merely chosen."""
    record = _record()
    del record["illustration_rationale"]
    errors = validate_prompt_record(record, anchors)
    assert any("illustration_rationale" in error for error in errors)


def test_a_banned_motif_anywhere_in_the_record_is_rejected(
    anchors: Path,
) -> None:
    """The scan reads the whole record, not just one field."""
    errors = validate_prompt_record(_record(
        subject="A glowing neural network sphere above a data city."), anchors)
    assert any("glowing-neural-sphere" in error for error in errors)
    assert any("abstract-data-city" in error for error in errors)


def test_the_shipped_examples_prompt_would_now_be_rejected(
    anchors: Path,
) -> None:
    """The documented failure must not be able to recur through this path."""
    errors = validate_prompt_record(_record(
        composition=("One focal researcher in a lab coat at left, a glowing "
                     "neural network sphere at right, flowing light above.")),
        anchors)
    assert errors


def test_required_exclusions_must_be_present(anchors: Path) -> None:
    """The pre-existing exclusion contract is still enforced."""
    errors = validate_prompt_record(_record(exclusions=["prose"]), anchors)
    assert any("exclusions" in error for error in errors)


def test_fewer_than_three_candidates_is_rejected(anchors: Path) -> None:
    """Spec D6 requires three candidates, not the first image that arrived."""
    errors = validate_prompt_record(
        _record(candidates=_candidates(count=2)), anchors)
    assert any("candidates" in error and "3" in error for error in errors)


def test_unblinded_ranking_is_rejected(anchors: Path) -> None:
    """A ranker who knows which candidate is which is not ranking blind.

    This is the assertion that carries the requirement. Without it the field is
    documentation: a record could set `blinded: false` and still validate, and
    "ranked blind" would mean whatever the author felt it meant.
    """
    errors = validate_prompt_record(
        _record(ranking={"blinded": False, "ranked_by": "art_direction"}),
        anchors)
    assert any("blinded" in error for error in errors)


def test_duplicate_or_gapped_ranks_are_rejected(anchors: Path) -> None:
    """Ranks must be a permutation of 1..n, or the ordering means nothing."""
    broken = _candidates()
    broken[1]["rank"] = 1
    errors = validate_prompt_record(_record(candidates=broken), anchors)
    assert any("rank" in error for error in errors)


def test_selecting_a_candidate_that_does_not_match_is_rejected(
    anchors: Path,
) -> None:
    """Spec D6: "Accepting the least-bad image is prohibited."

    When the top-ranked candidate still does not match the anchor, the module
    downgrades. Selecting it anyway is the exact behaviour the spec forbids, so
    it must fail validation rather than depend on the author's restraint.
    """
    errors = validate_prompt_record(
        _record(candidates=_candidates(matching=0)), anchors)
    assert any("downgrade" in error for error in errors)


def test_a_clean_downgrade_validates(anchors: Path) -> None:
    """No candidate matched, and the record says so instead of selecting one."""
    record = _record(candidates=_candidates(matching=0), selected=None,
                     downgraded_to="native-editorial")
    assert validate_prompt_record(record, anchors) == []


def test_selecting_an_unknown_candidate_id_is_rejected(anchors: Path) -> None:
    """`selected` must name one of the candidates that were actually ranked."""
    errors = validate_prompt_record(_record(selected="c9"), anchors)
    assert any("c9" in error for error in errors)


def test_parse_reads_the_yaml_block_from_a_prompt_markdown(
    tmp_path: Path,
) -> None:
    """prompt.md carries the record in a fenced yaml block."""
    path = tmp_path / "prompt.md"
    path.write_text(
        "# Prompt\n\n```yaml\npurpose: A\nstyle_anchor: technical-schematic\n```\n",
        encoding="utf-8")
    record = parse_prompt_record(path)
    assert record["style_anchor"] == "technical-schematic"


def test_parse_accepts_a_plain_yaml_record(tmp_path: Path) -> None:
    """Records predating the fenced-block convention still validate."""
    path = tmp_path / "prompt.md"
    path.write_text("purpose: A\nstyle_anchor: technical-schematic\n",
                    encoding="utf-8")
    assert parse_prompt_record(path)["style_anchor"] == "technical-schematic"


def test_parse_rejects_a_record_that_is_not_a_mapping(tmp_path: Path) -> None:
    """A record that cannot be read is an error, not an empty record."""
    path = tmp_path / "prompt.md"
    path.write_text("# Prompt\n\nsome prose\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_prompt_record(path)


def test_cli_exits_one_on_an_invalid_record(tmp_path: Path) -> None:
    """The CLI is usable as a gate."""
    path = tmp_path / "prompt.md"
    path.write_text("```yaml\npurpose: A\n```\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--prompt", str(path), "--json"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["valid"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_validate_generative_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'validate_generative_prompt'`.

- [ ] **Step 3: Write the validator**

Create `skills/report-slides/scripts/validate_generative_prompt.py`:

```python
#!/usr/bin/env python3
"""Validate a generative illustration's prompt record.

Enforces that a generative image is anchored to a registered style, justified
against the deterministic diagram route, and does not ask for a banned motif.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Union

import yaml

from style_anchors import (
    ANCHORS_PATH, CANDIDATE_COUNT, AnchorError, get_anchor,
    scan_for_banned_motifs,
)

# `candidates`, `ranking`, and `selected` are deliberately absent here and
# checked by `_candidate_errors` instead: a valid downgrade record sets
# `selected: null`, which this list's truthiness test would reject.
REQUIRED_FIELDS = (
    "purpose", "illustration_rationale", "style_anchor", "composition",
    "subject", "palette", "lighting", "empty_annotation_regions",
    "exclusions", "aspect_ratio",
)
REQUIRED_EXCLUSIONS = (
    "prose", "labels", "legends", "exact values", "watermarks", "signatures",
)
_YAML_BLOCK = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)


def parse_prompt_record(path: Union[str, Path]) -> Dict[str, Any]:
    """Read the YAML record out of a `prompt.md`.

    Args:
        path: Path to the prompt record.

    Returns:
        The parsed mapping.

    Raises:
        ValueError: If the file cannot be read, carries no fenced YAML block,
            or that block is not a mapping.
    """
    record_path = Path(path)
    try:
        text = record_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read prompt record {record_path}: {exc}") from exc
    match = _YAML_BLOCK.search(text)
    # Records predating the fenced-block convention are plain YAML documents;
    # both forms are accepted so existing assets can be validated in place.
    payload = match.group(1) if match else text
    try:
        data = yaml.safe_load(payload)
    except yaml.YAMLError as exc:
        raise ValueError(f"cannot parse {record_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"{record_path} does not contain a prompt-record mapping, either as "
            f"a fenced yaml block or as a plain yaml document")
    return data


def _record_text(record: Mapping[str, Any]) -> str:
    """Flatten a record's values into one searchable string.

    Args:
        record: The prompt record.

    Returns:
        Every scalar value in the record, joined by spaces.
    """
    parts: List[str] = []

    def walk(value: Any) -> None:
        """Append every scalar reachable from a value."""
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif value is not None:
            parts.append(str(value))

    walk(dict(record))
    return " ".join(parts)


def _candidate_errors(record: Mapping[str, Any]) -> List[str]:
    """Check spec D6's three-candidate blind-ranking requirement.

    Spec D6 requires that "Three candidates are generated and ranked blind
    against the anchor", and that "If no candidate matches the anchor, the
    module downgrades to a native editorial composition. Accepting the least-bad
    image is prohibited."

    Both halves are checked here rather than left to the author, because a
    record that merely *describes* a blind ranking is indistinguishable from one
    that accepted the first image the model returned -- and that is the
    behaviour spec 2.1 documents failing.

    Args:
        record: The parsed prompt record.

    Returns:
        Human-readable errors; empty when the record satisfies D6.
    """
    errors: List[str] = []
    candidates = record.get("candidates")
    if not isinstance(candidates, list):
        return ["candidates must be a list of "
                f"{CANDIDATE_COUNT} ranked entries"]
    if len(candidates) != CANDIDATE_COUNT:
        errors.append(
            f"candidates must hold exactly {CANDIDATE_COUNT} entries; "
            f"found {len(candidates)}. Spec D6 requires three candidates "
            f"ranked blind against the anchor.")

    ranks: List[Any] = []
    identifiers: List[str] = []
    matching: List[str] = []
    for position, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f"candidate {position} is not a mapping")
            continue
        if not candidate.get("id"):
            errors.append(f"candidate {position} omits 'id'")
            continue
        identifier = str(candidate["id"])
        identifiers.append(identifier)
        ranks.append(candidate.get("rank"))
        if candidate.get("matches_anchor") is True:
            matching.append(identifier)

    if len(identifiers) == len(candidates):
        expected = list(range(1, len(candidates) + 1))
        if sorted(rank for rank in ranks if isinstance(rank, int)) != expected:
            errors.append(
                f"candidate 'rank' values must be a permutation of "
                f"{expected}; found {ranks}")

    ranking = record.get("ranking")
    if not isinstance(ranking, dict):
        errors.append("ranking must be a mapping with 'blinded' and 'ranked_by'")
    elif ranking.get("blinded") is not True:
        errors.append(
            "ranking.blinded must be true: spec D6 requires the candidates be "
            "ranked blind against the anchor, and a ranker who knows which "
            "candidate is which is not ranking blind")

    selected = record.get("selected")
    if selected is None:
        if record.get("downgraded_to") != "native-editorial":
            errors.append(
                "a record that selects no candidate must set "
                "downgraded_to: native-editorial")
    elif str(selected) not in identifiers:
        errors.append(
            f"selected {str(selected)!r} is not one of the ranked candidates: "
            f"{', '.join(identifiers) or '(none)'}")
    elif str(selected) not in matching:
        errors.append(
            f"selected candidate {str(selected)!r} does not match the anchor. "
            f"Spec D6: accepting the least-bad image is prohibited; downgrade "
            f"to a native editorial composition instead.")
    return errors


def validate_prompt_record(record: Mapping[str, Any],
                           anchors_path: Path = ANCHORS_PATH) -> List[str]:
    """Validate one prompt record against the generative contract.

    Args:
        record: The parsed prompt record.
        anchors_path: Path to the style-anchor registry.

    Returns:
        Human-readable errors; an empty list means the record is admissible.
    """
    errors: List[str] = []
    for field in REQUIRED_FIELDS:
        if not record.get(field):
            errors.append(f"missing required field: {field}")

    anchor_id = record.get("style_anchor")
    if anchor_id:
        try:
            get_anchor(str(anchor_id), anchors_path)
        except AnchorError as exc:
            errors.append(str(exc))

    errors.extend(_candidate_errors(record))

    exclusions = record.get("exclusions") or []
    if isinstance(exclusions, (list, tuple)):
        present = {str(item).strip().lower() for item in exclusions}
        absent = [item for item in REQUIRED_EXCLUSIONS if item not in present]
        if absent:
            errors.append(
                f"exclusions omit required entries: {', '.join(absent)}")
    else:
        errors.append("exclusions must be a list")

    for motif in scan_for_banned_motifs(_record_text(record)):
        errors.append(
            f"prompt asks for banned motif {motif!r}; see "
            f"references/style-anchors/README.md")
    return errors


def main() -> None:
    """Validate one prompt record from the command line."""
    parser = argparse.ArgumentParser(
        description="Validate a generative illustration prompt record.")
    parser.add_argument("--prompt", metavar="PATH", type=Path, required=True)
    parser.add_argument("--anchors", metavar="PATH", type=Path,
                        default=ANCHORS_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        record = parse_prompt_record(args.prompt)
        errors = validate_prompt_record(record, args.anchors)
    except ValueError as exc:
        errors = [str(exc)]

    result = {"valid": not errors, "prompt": str(args.prompt), "errors": errors}
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_validate_generative_prompt.py -v`
Expected: PASS — 18 passed.

- [ ] **Step 5: Invert the route default**

In `skills/report-slides/agents/conceptual_illustration_worker_agent.md`,
replace the `Classify` step:

```markdown
3. **Classify:** Select exactly one route: `generative` ([V:AI]) is the default for conceptual illustrations when native shapes or data-driven routes cannot adequately represent the idea.
```

with:

````markdown
3. **Classify:** Select exactly one route. `generative` ([V:AI]) is the **last**
   route, not the default. Produce at least two deterministic candidates first —
   a diagram from `references/diagram-patterns.md` and one alternative
   composition — and rank them against the module's `purpose`. Take the
   generative route only when both candidates fail to carry the claim, and
   record why in the prompt record's `illustration_rationale`.

   **Downgrade rule.** If, at any point after generation, the illustration is
   found to carry no information a deterministic diagram could not carry, the
   module is downgraded to the deterministic candidate. This is not a failure
   of the module; it is the route correcting itself. A generative asset that
   survives is one that earned its place.

   **The registry may be empty, and that is a valid answer.** Spec D6 ships the
   style-anchor registry unpopulated, because curating reference images is a
   human action. While it is empty, every generative record is refused and the
   module downgrades to a native editorial composition. Do not add a prose-only
   anchor to reopen the route: `style_anchors.load_anchors` refuses an entry
   without verified `reference_images`. See
   `references/style-anchors/README.md` for the population procedure.

   Every generative prompt record must name a registered style anchor, carry
   three candidates ranked blind against that anchor's reference images, and
   pass:

   ```bash
   timeout 120 python3 "$SCRIPTS/validate_generative_prompt.py" \
     --prompt "$ASSET_DIR/prompt.md" --json
   ```

   Anchors are listed in `references/style-anchors/README.md`. There is no
   default anchor: if no anchor fits the subject, that is evidence the slide
   does not need a generative illustration.
````

In `skills/report-slides/agents/research_narrative_planner_agent.md:38`, replace
the `intended_visual_type` bullet with:

```markdown
   - An `intended_visual_type` that accurately reflects how this content should be visualized: `native` (text/simple formatting), `data` (charts, graphs, tables), `generative` (runtime-generated illustration), `hybrid` (mix of data and visuals), or `none` (text-only). Prefer `native` for structural diagrams: a deterministic diagram is authored, reviewable, and editable, and a generated raster is none of those. Choose `generative` only when the slide's claim needs imagery that no diagram can carry, and say so in `visual_rationale` — that sentence becomes the `illustration_rationale` the prompt record requires.
```

- [ ] **Step 6: Rewrite the selection gate and the prompt record**

In `skills/report-slides/references/generative-visuals.md`, replace
`## Selection gate` with:

```markdown
## Selection gate

The generative route is opt-in and last. Before it is available for a module,
two deterministic candidates must have been produced and ranked, and both must
have failed to carry the module's claim. Record which candidates were tried and
why they failed; that record is the `illustration_rationale` field of the prompt
record, and a generative asset without it does not pass the module gate.

Do not use an image model for statistical marks, chart values, authoritative
technical labels, legends, exact numbers, or other factual structure.

Creation and editing are runtime operations. Invoke the runtime image-generation
capability for the current visual; an existing file alone is not evidence that
the requested generation or edit occurred. Do not replace a required runtime
generation or edit with an arbitrary web image, an untracked download, or an
unrelated redraw.

**Why the default changed.** A generative illustration that could have been a
diagram costs the deck twice: it cannot be edited when the content changes, and
it drifts towards the image model's prior for "technical illustration" — glowing
networks, light ribbons, abstract data cities — which reads as generic
regardless of how well it is rendered. See
`references/style-anchors/README.md`.
```

Replace the `## Prompt record` example block with one carrying the two new
fields and citing an anchor:

```yaml
purpose: Support the explanation of the retrieval and ranking loop.
illustration_rationale: >-
  Two deterministic candidates were produced (a staged flow diagram and a
  layered block diagram); both rendered the stages but neither carried the
  claim that ranking is continuous rather than discrete.
style_anchor: technical-schematic
composition: Three stages left to right, open annotation margin above.
subject: A retrieval pipeline and the ranked passages leaving it.
palette: Design-token roles primary, body, line, card, bg.
lighting: Flat, no directional light.
empty_annotation_regions: Upper third and lower-right margin.
exclusions:
  - prose
  - labels
  - legends
  - exact values
  - watermarks
  - signatures
aspect_ratio: 16:9
references: []
changed_regions: []

# Spec D6: three candidates, ranked blind against the anchor's reference images.
# `matches_anchor` is the ranker's verdict, not the author's preference. If the
# top-ranked candidate does not match, set `selected: null` and
# `downgraded_to: native-editorial` -- accepting the least-bad image is
# prohibited, and validate_generative_prompt.py refuses it.
candidates:
  - id: c1
    asset: renders/candidate-01.png
    rank: 1
    matches_anchor: true
  - id: c2
    asset: renders/candidate-02.png
    rank: 2
    matches_anchor: false
  - id: c3
    asset: renders/candidate-03.png
    rank: 3
    matches_anchor: false
ranking:
  blinded: true
  ranked_by: art_direction
selected: c1
```

**On "ranked blind".** The ranker must not know which candidate came from which
generation attempt, which prompt variant produced it, or which one the author
prefers. Present the three renders in a shuffled order against the anchor's
reference images and record the verdict. `ranking.blinded: false` is refused
rather than merely noted: an unblinded ranking of three images the author
already has an opinion about is a rationalisation, not a ranking, and it would
let the exact failure in spec §2.1 through with three times the paperwork.

Add immediately below it:

````markdown
`style_anchor` and `illustration_rationale` are required. Validate the record
before generating:

```bash
timeout 120 python3 "$SCRIPTS/validate_generative_prompt.py" \
  --prompt "$ASSET_DIR/prompt.md" --json
```

The validator refuses a record that omits a required field, cites an
unregistered anchor, drops a required exclusion, or asks anywhere in its text
for a banned motif. It reads the prompt, not the produced image: a model may
still return a banned motif unasked, and that case is caught at review as an
`art_direction` `visual-cliche` finding.
````

- [ ] **Step 7: Update the persona test**

In `skills/report-slides/scripts/tests/test_agent_persona_docs.py`, extend
`test_conceptual_illustration_worker_agent_names_stage_and_route`:

```python
def test_conceptual_illustration_worker_agent_names_stage_and_route() -> None:
    text = _read("conceptual_illustration_worker_agent.md")
    assert "name: conceptual_illustration_worker_agent" in text
    assert "Stage 9" in text
    assert "Stage Boundary" in text
    assert "modify scientific content" in text.lower()
    assert "generative" in text
    assert "last" in text.lower()
    assert "style anchor" in text.lower()
    assert "validate_generative_prompt.py" in text
    assert "Downgrade rule" in text
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -v`
Expected: PASS — the whole suite.

- [ ] **Step 9: Commit**

```bash
git add skills/report-slides/scripts/validate_generative_prompt.py \
        skills/report-slides/scripts/tests/test_validate_generative_prompt.py \
        skills/report-slides/scripts/tests/test_agent_persona_docs.py \
        skills/report-slides/references/generative-visuals.md \
        skills/report-slides/agents/conceptual_illustration_worker_agent.md \
        skills/report-slides/agents/research_narrative_planner_agent.md
git commit -m "feat(report-slides): make generative illustration opt-in and anchor its prompts"
```

---

### Task 13: Apply the new gate to the deck's own shipped example

**Files:**
- Create: `examples/report-slides/visual-authoring/assets/research-collaboration/WHY-THIS-FAILS.md`
- Modify: `examples/report-slides/visual-authoring/assets/research-collaboration/review.json`
- Modify: `examples/report-slides/visual-authoring/assets/research-collaboration/prompt.md`
- Modify: `examples/report-slides/visual-authoring/slides/slide02-hybrid.svg:11-15`
  (remove the `<image id="generated-raster-background">` layer)
- Modify: `examples/report-slides/visual-authoring/assets/research-collaboration/source.svg`
  (same layer)
- Modify: `examples/report-slides/visual-authoring/slides/slide01-architecture.svg`,
  `slide02-hybrid.svg`, `slide03-chart.svg` (token conformance)
- Test: `skills/report-slides/scripts/tests/test_shipped_examples.py`

**Interfaces:**
- Consumes: `validate_generative_prompt.{parse_prompt_record,
  validate_prompt_record}` (Task 12); `validate_visual_style.lint_paths`
  (Task 8).
- Produces: nothing imported elsewhere.

**Why this task exists.** Spec §2.1's evidence is this repository's own example:
a generated illustration whose `review.json` records `"status": "passed"`, whose
`prompt.md` already excluded `busy background`, `excessive glow`, and
`photorealistic faces`, and whose `remaining_raster_layers` entry states in
plain words that "the bitmap is illustrative atmosphere only". That sentence is
the downgrade rule's trigger condition, written by the pipeline about itself,
and nothing acted on it. A gate that its author's own shipped example fails is
not credible until the example is fixed.

**What "fixed" means here.** Not a better prompt. Under Task 12's downgrade
rule, an illustration that carries no information a deterministic diagram could
not carry is removed. The raster layer goes; the SVG overlay that carried every
factual mark stays and is now the whole slide. The asset directory is retained,
not deleted, because it is the evidence — with a `WHY-THIS-FAILS.md` that names
the verdict in the Task 10 vocabulary.

**A limitation this task makes visible.** The shipped prompt never asked for a
lab coat, yet the delivered image contains one. `scan_for_banned_motifs` reads
prompts and would not have caught it; only the art-direction reviewer's
`visual-cliche` finding would. Record that in `WHY-THIS-FAILS.md` rather than
overstating what the scan buys.

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_shipped_examples.py`:

```python
"""The shipped examples must satisfy the gates this skill enforces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from design_tokens import DEFAULT_TOKENS_PATH
from validate_generative_prompt import (
    parse_prompt_record, validate_prompt_record,
)
from validate_visual_style import lint_paths

_REPO = Path(__file__).resolve().parents[4]
_EXAMPLE = _REPO / "examples/report-slides/visual-authoring"
_COUNTER = _EXAMPLE / "assets/research-collaboration"


def test_the_example_deck_directory_is_where_the_test_expects() -> None:
    """Guard the path arithmetic, so a miss is not a silent pass."""
    assert _EXAMPLE.is_dir()
    assert (_EXAMPLE / "slides").is_dir()


def test_the_counter_example_prompt_is_rejected() -> None:
    """The prompt that produced the documented failure must not validate."""
    record = parse_prompt_record(_COUNTER / "prompt.md")
    errors = validate_prompt_record(record)
    assert errors
    assert any("banned motif" in error for error in errors)


def test_the_counter_example_is_documented_as_one() -> None:
    """A retained failure must say why it is retained."""
    text = (_COUNTER / "WHY-THIS-FAILS.md").read_text(encoding="utf-8")
    assert "visual-cliche" in text
    assert "stock-ai-composition" in text
    assert "decorative-noise" in text
    assert "downgrade" in text.lower()


def test_the_counter_example_review_records_the_failure() -> None:
    """review.json must no longer claim this asset passed."""
    review = json.loads((_COUNTER / "review.json").read_text(encoding="utf-8"))
    assert review["status"] == "failed"
    kinds = {finding["kind"]
             for finding in review["art_direction"]["findings"]}
    assert {"visual-cliche", "stock-ai-composition",
            "decorative-noise"} <= kinds


def test_the_raster_layer_was_downgraded_out_of_the_deck() -> None:
    """The atmosphere-only bitmap is no longer referenced by any slide."""
    review = json.loads((_COUNTER / "review.json").read_text(encoding="utf-8"))
    assert review["remaining_raster_layers"] == []
    for svg in sorted((_EXAMPLE / "slides").glob("*.svg")):
        assert "research-collaboration/generated.png" not in svg.read_text(
            encoding="utf-8")


@pytest.mark.parametrize(
    "slide_name",
    ["slide01-architecture.svg", "slide02-hybrid.svg", "slide03-chart.svg"])
def test_every_shipped_slide_passes_the_visual_style_gate(
    slide_name: str,
) -> None:
    """The examples must satisfy the gate this skill applies to users' decks."""
    result = lint_paths([_EXAMPLE / "slides" / slide_name],
                        DEFAULT_TOKENS_PATH)
    assert result["valid"] is True, json.dumps(
        result["files"][0]["findings"], indent=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `timeout 600 python3 -m pytest skills/report-slides/scripts/tests/test_shipped_examples.py -v`
Expected: FAIL — `FileNotFoundError` for `WHY-THIS-FAILS.md`, `review["status"]`
still `"passed"`, and the three slide-gate cases failing with concrete findings.

Capture that findings JSON. It is the work list for Step 5, and it is also the
first honest measurement of how far the pre-token examples sit from the
contract.

- [ ] **Step 3: Record the verdict**

Create `examples/report-slides/visual-authoring/assets/research-collaboration/WHY-THIS-FAILS.md`:

```markdown
# Why this asset fails, and why it is kept

This directory is a counter-example. It is retained because it is the evidence
behind the visual-quality redesign, not because it is a model to follow.

## What was shipped

A generated illustration: a figure in a white lab coat at a laptop, a glowing
neural-network sphere, flowing light ribbons, and an abstract data-city skyline,
in blue, teal, and amber. Its `review.json` recorded `"status": "passed"` with a
single finding, and that finding was about CairoSVG's external-resource policy —
a rendering note, not a judgement about the picture.

## The verdict under the art-direction vocabulary

- **`visual-cliche`** — the glowing neural sphere, the flowing light ribbons,
  and the abstract data-city skyline would serve any deck about any AI system.
  Nothing in them is specific to this deck's subject.
- **`stock-ai-composition`** — the framing is a generator default. "Anonymous
  person at a laptop" is on the banned-motif list in spec §D6 by name, and the
  lab coat was never asked for: the model supplied it because that is what its
  prior returns for "researcher".
- **`decorative-noise`** — the slide's factual content lived entirely in the SVG
  overlay. The bitmap carried no information, and the asset's own `review.json`
  said so, recording that "the bitmap is illustrative atmosphere only".

## What was done about it

The raster layer was **downgraded** out of the deck under the rule in
`agents/conceptual_illustration_worker_agent.md`: an illustration that carries
no information a deterministic diagram could not carry is removed. The SVG
overlay, which carried every factual mark, is now the whole slide.

## What the automated checks would and would not have caught

`scripts/validate_generative_prompt.py` rejects this `prompt.md`, because the
prompt asked for "subtle flowing light and circuit-like pathways".

It would **not** have caught the lab coat. The prompt never asked for one; the
image model supplied it, because a figure in a lab coat is what its prior
returns for "researcher". No prompt-text scan can catch that. Only the
art-direction reviewer, looking at the delivered pixels, can — which is why
`art_direction_reviewer_agent` exists as an independent gate rather than as a
lint rule.
```

- [ ] **Step 4: Update the records and apply the downgrade**

In `assets/research-collaboration/prompt.md`, add at the top of the file:

```yaml
# RETAINED AS A COUNTER-EXAMPLE. This record predates the generative contract in
# references/generative-visuals.md and is rejected by
# scripts/validate_generative_prompt.py. See WHY-THIS-FAILS.md.
```

In `assets/research-collaboration/review.json`:
- change `"status": "passed"` to `"status": "failed"` at the top level;
- set `"remaining_raster_layers": []`;
- add an `art_direction` block recording the verdict:

```json
  "art_direction": {
    "status": "failed",
    "reviewer_role": "art_direction",
    "round": 3,
    "findings": [
      {
        "kind": "visual-cliche",
        "description": "The illustration is a lab-coated figure at a laptop with a glowing neural sphere, light ribbons, and an abstract data-city skyline; every element would serve any deck about any AI system.",
        "remedy": "Downgrade to the deterministic SVG overlay, which already carries every factual mark.",
        "source": "svg-preview",
        "artifact_path": "renders/source.png",
        "disposition": "fixed"
      },
      {
        "kind": "stock-ai-composition",
        "description": "The framing is a generator default: an anonymous person at a laptop, a motif spec D6 bans by name. The lab coat was never requested; the model supplied it.",
        "remedy": "Downgrade to the deterministic SVG overlay.",
        "source": "svg-preview",
        "artifact_path": "renders/source.png",
        "disposition": "fixed"
      },
      {
        "kind": "decorative-noise",
        "description": "The bitmap carries no information; this record's own remaining_raster_layers entry described it as illustrative atmosphere only.",
        "remedy": "Remove the raster layer from the slide.",
        "source": "svg-preview",
        "artifact_path": "renders/source.png",
        "disposition": "fixed"
      }
    ]
  },
```

Leave the existing `model_vision`, `pptx_render`, and `pixel_vs_structure`
blocks in place. They record what was measured at the time and are still true;
the top-level status changes because the *art-direction* gate, which did not
exist then, fails.

Remove the raster layer from both
`examples/report-slides/visual-authoring/slides/slide02-hybrid.svg` (the
`<image id="generated-raster-background" ... href="../assets/research-collaboration/generated.png"/>`
element at lines 11-15) and the corresponding element in
`assets/research-collaboration/source.svg`.

Keep `generated.png` on disk. `WHY-THIS-FAILS.md` refers to it, and deleting the
evidence would leave the counter-example unreadable.

- [ ] **Step 5: Bring the example slides onto the tokens**

For each of `slide01-architecture.svg`, `slide02-hybrid.svg`, and
`slide03-chart.svg`, iterate until clean:

```bash
timeout 300 python3 skills/report-slides/scripts/validate_visual_style.py \
  --svg examples/report-slides/visual-authoring/slides/slide01-architecture.svg
```

Fix every reported error in the SVG source — each finding names the element, the
measured value, and the required value, so no judgement is needed about what to
change. Work in this order, because later fixes depend on earlier geometry:

1. `token-color` — replace off-palette colours with the nearest role in
   `default.tokens.yaml`. If no role is close, the slide needs a token, not a
   one-off colour; add it to the token file in a separate commit with its
   contrast ratio recorded.
2. `type-floor` — raise each run to its role size, then re-measure: larger text
   changes widths and will surface new geometry findings.
3. `safe-area`, `element-overlap`, `node-gap`, `node-padding` — reflow.
4. `graphic-contrast`, `text-contrast` — these usually resolve with step 1; any
   residue means a light role is being used on a light ground.
5. `connector-dangling`, `connector-port-drift`, `hand-drawn-arrow` — add
   `data-from`/`data-to` and convert polygon arrowheads to `marker-end`.

Add `data-style-role` and `data-node-id` attributes as the rules require them;
that is the same authoring contract users' decks are now held to, and the
examples are how users learn it.

Re-render the affected previews so the committed PNGs match the SVG. The
existing renders were produced with CairoSVG at the approved preview size, as
each `review.json` records:

```bash
timeout 600 python3 -c "
import cairosvg, sys
src, dst = sys.argv[1], sys.argv[2]
cairosvg.svg2png(url=src, write_to=dst, output_width=1200, output_height=675,
                 unsafe=True)
" examples/report-slides/visual-authoring/slides/slide01-architecture.svg \
  examples/report-slides/visual-authoring/assets/system-pipeline/renders/slide01-architecture.png
```

Repeat per slide and per render path listed in that slide's asset
`review.json` `artifacts` array. The PPTX renders under `renders/lo-rendered/`
come from LibreOffice; regenerate them by re-exporting the deck through the
skill's existing PPTX path. If the LibreOffice version present differs from the
`7.3.7.2` recorded in `review.json`, update that field to the version actually
used and say so in the commit body — never leave a version recorded that did not
produce the file.

Warnings are expected on these slides and do not block: record the answers to
any `occupancy` or `equal-card-repetition` warning in the deck-level
`examples/report-slides/visual-authoring/review.json`, in the
`linter_warnings_answered` shape from `art_direction_reviewer_agent.md`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -v`
Expected: PASS — the whole suite, including the six new shipped-example tests.

If a slide cannot be brought to clean without changing what it communicates,
stop and say so: that is a finding about the token defaults, not a reason to
weaken `test_every_shipped_slide_passes_the_visual_style_gate`. Do not add an
`xfail`, do not narrow the parametrisation, and do not relax a token to fit one
slide without recording the contrast measurement that justifies it.

- [ ] **Step 7: Commit**

```bash
git add examples/report-slides/visual-authoring \
        skills/report-slides/scripts/tests/test_shipped_examples.py
git commit -m "fix(report-slides): downgrade the shipped generative example and gate the example deck

The research-collaboration raster was atmosphere only, as its own review record
stated. It is removed from the deck under the downgrade rule and retained as a
documented counter-example. The three example slides are brought onto the design
tokens so the shipped examples satisfy the gate users' decks are held to."
```

---

## Phase 6: Lint Evidence and the Enforced Gate

### Task 14: Persist the lint result and bind the gate to it

Task 8 built the linter and documented it as blocking. It is not blocking.
`SKILL.md` tells an agent to run `validate_visual_style.py` and treat a non-zero
exit as a hard failure, but nothing in `presentation_gates.py`,
`presentation_events.py`, or `presentation_workflow.py` reads that exit code. A
slide can be recorded as passed by three reviewers without the linter ever
having run, and a slide that passed the linter yesterday still counts as passed
after its SVG is rewritten today.

That is exactly the defect spec §2.11 exists to remove: a gate that lives in
prose, where compliance is asserted rather than shown. Shipping a 22-rule linter
behind a prose gate reproduces the problem with more machinery.

The same gap makes `linter_warnings_answered` decorative.
`art_direction_reviewer_agent.md` says an art-direction review is incomplete
until every linter warning is answered, and Task 10 validates nothing of the
kind: a review passes with the field absent, or with answers to warnings that no
run ever produced. Both ends of that contract need the same missing thing — a
persisted lint result with a digest — so they are fixed in one task.

**Files:**
- Create: `skills/report-slides/scripts/lint_evidence.py`
- Test: `skills/report-slides/scripts/tests/test_lint_evidence.py`
- Modify: `skills/report-slides/scripts/validate_visual_style.py` — `main`, from
  Task 8
- Modify: `skills/report-slides/scripts/presentation_gates.py` —
  `review_result_blockers` (currently line 529) and `assert_slide_passable`
  (currently line 615)
- Modify: `skills/report-slides/SKILL.md` — the Stage 10 gate paragraph Task 8
  wrote

**Interfaces:**
- Consumes: `visual_style.report.LintReport` (Task 1);
  `validate_visual_style.lint_svg` (Task 8);
  `presentation_events.{append_event, load_events, load_artifacts}`;
  `presentation_artifact_provenance.{MODULE_ARTIFACT_KINDS, SLIDE_ARTIFACT_KINDS}`.
- Produces:
  - `LINT_EVENT_TYPE: str` — `"visual_style_lint"`
  - `record_lint_evidence(project_root: Path, subject_type: str,
    subject_id: str, artifact_sha256: str, tokens_sha256: str,
    report: LintReport) -> Dict[str, Any]`
  - `current_lint_evidence(project_root: Path, subject_type: str,
    subject_id: str, artifact_sha256: str, tokens_sha256: str)
    -> Optional[Dict[str, Any]]`
  - `current_svg_digest(project_root: Path, subject_type: str,
    subject_id: str) -> Optional[str]`
  - `lint_blockers(project_root: Path, subject_type: str, subject_id: str,
    tokens_sha256: str) -> List[Dict[str, Any]]`
  - `unanswered_warnings(evidence: Mapping[str, Any],
    review: Mapping[str, Any]) -> List[str]`

- [ ] **Step 1: Write the failing tests**

Create `skills/report-slides/scripts/tests/test_lint_evidence.py`:

```python
"""Lint results are evidence, not console output.

A gate that reads a shell exit code enforces nothing: the exit code is gone by
the time anything decides whether a slide may pass. These tests pin the three
properties that make the linter an actual gate -- the result is persisted, it is
bound to the exact bytes it examined, and a review cannot claim to have answered
warnings that no run produced.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

import lint_evidence as le
import presentation_events as events
from visual_style.report import Finding, LintReport


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """An empty project root, which is already an admissible event target.

    `presentation_evidence_workflow.require_schema_v2` -- which `append_event`
    calls first -- collects the schema markers of the state documents that
    exist and returns without complaint when there are none. A fresh directory
    is therefore a valid schema-v2 project, and no initialiser call is needed.
    """
    return tmp_path


def _publish_svg(project_root: Path, slide_id: str, sha256: str) -> None:
    """Record a slide-svg artifact so the gate has bytes to reason about."""
    events.create_artifact_record(
        project_root, deck_id="dk-1", artifact_kind="slide-svg",
        artifact_path=f"slides/{slide_id}.svg", sha256=sha256,
        producer_id="test", slide_id=slide_id)


def _report(errors: int = 0, warnings: Tuple[str, ...] = ()) -> LintReport:
    """Build a report with the requested error count and warning rules."""
    findings = [
        Finding(rule="safe-area", severity="error", message=f"e{index}",
                element_id=f"e{index}", location=(0.0, 0.0))
        for index in range(errors)
    ]
    findings.extend(
        Finding(rule=rule, severity="warning", message=rule,
                element_id=rule, location=(0.0, 0.0))
        for rule in warnings
    )
    return LintReport(path=Path("slide-01.svg"), findings=findings)


def test_a_recorded_result_is_found_again_by_its_digests(project: Path) -> None:
    """The evidence is keyed by what it examined, not by when it ran."""
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report())
    found = le.current_lint_evidence(project, "slide", "sl-1", "a" * 64,
                                     "b" * 64)
    assert found is not None
    assert found["errors"] == []


def test_a_result_for_different_bytes_is_not_current(project: Path) -> None:
    """Editing the SVG invalidates the evidence, silently or not at all."""
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report())
    assert le.current_lint_evidence(project, "slide", "sl-1", "c" * 64,
                                    "b" * 64) is None


def test_a_result_for_different_tokens_is_not_current(project: Path) -> None:
    """A token change re-opens every colour and type question on the slide."""
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report())
    assert le.current_lint_evidence(project, "slide", "sl-1", "a" * 64,
                                    "d" * 64) is None


def test_the_latest_result_for_one_digest_pair_wins(project: Path) -> None:
    """A re-run after a fix supersedes the failing result it replaces."""
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report(errors=2))
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report())
    found = le.current_lint_evidence(project, "slide", "sl-1", "a" * 64,
                                     "b" * 64)
    assert found is not None and found["errors"] == []


def test_no_evidence_at_all_is_a_blocker(project: Path) -> None:
    """The default is refusal. A linter nobody ran must not read as a pass."""
    _publish_svg(project, "sl-1", "a" * 64)
    reasons = {b["reason"] for b in
               le.lint_blockers(project, "slide", "sl-1", "b" * 64)}
    assert reasons == {"lint_evidence_missing"}


def test_evidence_for_older_bytes_is_a_blocker(project: Path) -> None:
    """Stale evidence is worse than none: it looks like a pass."""
    le.record_lint_evidence(project, "slide", "sl-1", "0" * 64, "b" * 64,
                            _report())
    _publish_svg(project, "sl-1", "a" * 64)
    reasons = {b["reason"] for b in
               le.lint_blockers(project, "slide", "sl-1", "b" * 64)}
    assert reasons == {"lint_evidence_stale"}


def test_a_failing_result_is_a_blocker(project: Path) -> None:
    """A hard error blocks the slide whatever the three reviewers concluded."""
    _publish_svg(project, "sl-1", "a" * 64)
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report(errors=1))
    blockers = le.lint_blockers(project, "slide", "sl-1", "b" * 64)
    assert [b["reason"] for b in blockers] == ["lint_failed"]
    assert blockers[0]["rules"] == ["safe-area"]


def test_a_passing_result_blocks_nothing(project: Path) -> None:
    """Warnings are for the art director to answer, not for the gate."""
    _publish_svg(project, "sl-1", "a" * 64)
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report(warnings=("occupancy",)))
    assert le.lint_blockers(project, "slide", "sl-1", "b" * 64) == []


def test_unanswered_warnings_are_named(project: Path) -> None:
    """The reviewer must answer the warnings this run produced."""
    evidence = le.record_lint_evidence(
        project, "slide", "sl-1", "a" * 64, "b" * 64,
        _report(warnings=("occupancy", "equal-card-repetition")))
    review: Dict[str, Any] = {
        "reviewer_role": "art_direction", "status": "passed",
        "linter_warnings_answered": [
            {"rule": "occupancy", "answer": "the slide is a section divider"},
        ],
    }
    assert le.unanswered_warnings(evidence, review) == ["equal-card-repetition"]


def test_answering_a_warning_that_was_not_raised_is_unanswered(
        project: Path) -> None:
    """Answers copied from another slide do not discharge this slide's warnings.

    Without this, `linter_warnings_answered` degrades into a field that is
    filled in because it is required, which is the failure mode the whole task
    exists to remove.
    """
    evidence = le.record_lint_evidence(
        project, "slide", "sl-1", "a" * 64, "b" * 64,
        _report(warnings=("occupancy",)))
    review: Dict[str, Any] = {
        "reviewer_role": "art_direction", "status": "passed",
        "linter_warnings_answered": [
            {"rule": "connector-crossing", "answer": "deliberate"},
        ],
    }
    assert le.unanswered_warnings(evidence, review) == ["occupancy"]


def test_an_empty_answer_does_not_count(project: Path) -> None:
    """A blank string is not an answer."""
    evidence = le.record_lint_evidence(
        project, "slide", "sl-1", "a" * 64, "b" * 64,
        _report(warnings=("occupancy",)))
    review: Dict[str, Any] = {
        "reviewer_role": "art_direction", "status": "passed",
        "linter_warnings_answered": [{"rule": "occupancy", "answer": "  "}],
    }
    assert le.unanswered_warnings(evidence, review) == ["occupancy"]


def test_a_module_is_linted_under_its_own_subject_type(project: Path) -> None:
    """Modules and slides do not share an evidence namespace."""
    le.record_lint_evidence(project, "module", "sl-1", "a" * 64, "b" * 64,
                            _report())
    assert le.current_lint_evidence(project, "slide", "sl-1", "a" * 64,
                                    "b" * 64) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_lint_evidence.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'lint_evidence'`.

- [ ] **Step 3: Write `lint_evidence.py`**

Create `skills/report-slides/scripts/lint_evidence.py`:

```python
"""Persisted evidence that the visual-style linter ran, and on what.

The linter's exit code is not a gate. It exists for the length of one shell
command, in a process nothing else observes, and by the time
`assert_slide_passable` decides whether a slide may pass, the only honest answer
available to it is "no idea". This module gives that question an answer that
survives: an append-only event recording which rules fired, over which bytes,
under which token set.

Binding the result to both digests is the point. A lint result is a statement
about a specific SVG under a specific token file; change either and the
statement is not false, it is about something else. Evidence that no longer
matches is therefore treated as absent -- and reported distinctly, because
"nobody linted this" and "this was linted before it was rewritten" call for
different actions from the person reading the blocker.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import presentation_events as events
from visual_style.report import LintReport

LINT_EVENT_TYPE = "visual_style_lint"

_ARTIFACT_KIND_FOR_SUBJECT = {"slide": "slide-svg", "module": "module-svg"}


def record_lint_evidence(
    project_root: Path,
    subject_type: str,
    subject_id: str,
    artifact_sha256: str,
    tokens_sha256: str,
    report: LintReport,
) -> Dict[str, Any]:
    """Persist one lint result as an immutable event.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.
        artifact_sha256: Digest of the exact SVG bytes that were linted.
        tokens_sha256: Digest of the resolved token file the rules read.
        report: The result of `validate_visual_style.lint_svg`.

    Returns:
        The persisted event mapping.

    Raises:
        ValueError: If `subject_type` is not a linted subject type.
    """
    if subject_type not in _ARTIFACT_KIND_FOR_SUBJECT:
        raise ValueError(
            f"subject_type must be slide or module, got {subject_type!r}")
    event: Dict[str, Any] = {
        "event": LINT_EVENT_TYPE,
        "id": f"lint-{uuid.uuid4().hex[:12]}",
        "ts": datetime.now(timezone.utc).isoformat(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "artifact_sha256": artifact_sha256,
        "tokens_sha256": tokens_sha256,
        "errors": sorted(
            {f.rule for f in report.findings if f.severity == "error"}),
        "warnings": sorted(
            {f.rule for f in report.findings if f.severity == "warning"}),
    }
    events.append_event(project_root, event)
    return event


def current_lint_evidence(
    project_root: Path,
    subject_type: str,
    subject_id: str,
    artifact_sha256: str,
    tokens_sha256: str,
) -> Optional[Dict[str, Any]]:
    """Return the most recent evidence matching both digests exactly.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.
        artifact_sha256: Digest of the SVG as it stands now.
        tokens_sha256: Digest of the token file as it stands now.

    Returns:
        The latest matching event, or `None` when the subject has never been
        linted in this exact configuration.
    """
    matches = [
        event
        for event in events.load_events(project_root, event_type=LINT_EVENT_TYPE)
        if event.get("subject_type") == subject_type
        and event.get("subject_id") == subject_id
        and event.get("artifact_sha256") == artifact_sha256
        and event.get("tokens_sha256") == tokens_sha256
    ]
    # `load_events` returns chronological order, so the last match is current.
    return matches[-1] if matches else None


def current_svg_digest(
    project_root: Path, subject_type: str, subject_id: str
) -> Optional[str]:
    """Return the digest of the subject's current published SVG artifact.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.

    Returns:
        The `sha256` of the most recent `slide-svg` or `module-svg` artifact
        record for this subject, or `None` if none has been published.
    """
    kind = _ARTIFACT_KIND_FOR_SUBJECT.get(subject_type)
    if kind is None:
        return None
    key = "slide_id" if subject_type == "slide" else "module_id"
    records = [
        record for record in events.load_artifacts(project_root).values()
        if record.get("artifact_kind") == kind and record.get(key) == subject_id
    ]
    if not records:
        return None
    latest = max(records, key=lambda record: str(record.get("created_at", "")))
    digest = latest.get("sha256")
    return str(digest) if digest else None


def lint_blockers(
    project_root: Path, subject_type: str, subject_id: str, tokens_sha256: str
) -> List[Dict[str, Any]]:
    """Report why the linter does not currently clear this subject.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.
        tokens_sha256: Digest of the token file the subject is held to.

    Returns:
        Machine-readable blockers; empty means the linter passes on the current
        bytes. `lint_artifact_missing` means no SVG has been published at all,
        `lint_evidence_missing` that it has never been linted,
        `lint_evidence_stale` that the evidence predates the current bytes or
        token set, and `lint_failed` that hard errors are outstanding.
    """
    artifact_sha256 = current_svg_digest(project_root, subject_type, subject_id)
    if artifact_sha256 is None:
        return [{"reason": "lint_artifact_missing"}]
    evidence = current_lint_evidence(
        project_root, subject_type, subject_id, artifact_sha256, tokens_sha256)
    if evidence is None:
        prior = [
            event
            for event in events.load_events(
                project_root, event_type=LINT_EVENT_TYPE)
            if event.get("subject_type") == subject_type
            and event.get("subject_id") == subject_id
        ]
        reason = "lint_evidence_stale" if prior else "lint_evidence_missing"
        return [{"reason": reason}]
    if evidence["errors"]:
        return [{"reason": "lint_failed", "rules": list(evidence["errors"])}]
    return []


def unanswered_warnings(
    evidence: Mapping[str, Any], review: Mapping[str, Any]
) -> List[str]:
    """Return the warning rules this review has not answered.

    A warning is answered only by a non-empty answer naming that exact rule.
    Answers naming rules the run did not raise are ignored rather than credited:
    otherwise a reviewer could discharge every warning by pasting the answers
    from a different slide.

    Args:
        evidence: A lint event from `current_lint_evidence`.
        review: A Review Result mapping.

    Returns:
        The unanswered warning rules, sorted.
    """
    answered = {
        str(entry.get("rule"))
        for entry in review.get("linter_warnings_answered", [])
        if isinstance(entry, Mapping) and str(entry.get("answer", "")).strip()
    }
    return sorted(set(evidence.get("warnings", [])) - answered)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_lint_evidence.py -v`
Expected: PASS — 12 passed.

- [ ] **Step 5: Record evidence from the CLI**

`validate_visual_style.py` currently prints and exits. Give it the option to
write down what it found. In `main`, add to the argument parser, beside the
existing `--tokens` and `--warnings-as-errors`:

```python
    parser.add_argument(
        "--record", type=Path, default=None, metavar="PROJECT_ROOT",
        help="persist each result as lint evidence under this project root")
    parser.add_argument(
        "--subject-type", choices=("slide", "module"), default="slide",
        help="the subject kind the linted files belong to")
    parser.add_argument(
        "--subject-id", default=None,
        help="the generated subject id; required with --record")
```

and, after the report for one path is built and before the exit code is
computed:

```python
    if args.record is not None:
        if args.subject_id is None:
            parser.error("--record requires --subject-id")
        record_lint_evidence(
            args.record, args.subject_type, args.subject_id,
            _sha256_of(svg_path), _sha256_of(tokens_path), report)
```

`_sha256_of` is a four-line helper reading the file in binary and returning
`hashlib.sha256(data).hexdigest()`; put it beside `main`. Recording is opt-in
because the linter is also run outside a project, on a scratch file, while
authoring — but Stage 10 always passes `--record`.

- [ ] **Step 6: Write the failing gate tests**

Append to `skills/report-slides/scripts/tests/test_reviewer_roles.py`, the file
Task 9 created:

```python
def test_a_slide_cannot_pass_without_a_current_lint_result(
        project: Path) -> None:
    """Three passing reviewers do not substitute for a measurement.

    This is the property that distinguishes a gate from a paragraph. Before it,
    `validate_visual_style.py` could have been deleted and every deck would
    still have completed.
    """
    slide_id = _slide_with_three_passing_reviews(project)
    with pytest.raises(gates.ReviewGateError) as caught:
        gates.assert_slide_passable(project, slide_id)
    assert any(b["reason"].startswith("lint_") for b in caught.value.blockers)


def test_an_art_direction_pass_must_answer_the_warnings(project: Path) -> None:
    """`linter_warnings_answered` is checked against the warnings raised."""
    slide_id = _slide_with_three_passing_reviews(project, answer_warnings=False)
    _lint_clean_with_warnings(project, slide_id, ("occupancy",))
    with pytest.raises(gates.ReviewGateError) as caught:
        gates.assert_slide_passable(project, slide_id)
    reasons = [b["reason"] for b in caught.value.blockers]
    assert "art_direction:linter_warnings_unanswered" in reasons


def test_a_slide_with_answered_warnings_and_clean_errors_passes(
        project: Path) -> None:
    """The gate is passable. A gate nothing can satisfy is not a gate."""
    slide_id = _slide_with_three_passing_reviews(project, answer_warnings=True)
    _lint_clean_with_warnings(project, slide_id, ("occupancy",))
    passed = gates.assert_slide_passable(project, slide_id)
    assert passed["slide"]["id"] == slide_id


def test_a_new_visual_quality_review_is_refused(project: Path) -> None:
    """The legacy role is grandfathered for replay, not for new writes.

    `SLIDE_REVIEW_ROLE_SETS` still accepts `{scientific, visual_quality}` so
    decks recorded before the split can complete. Without this check, that
    concession is permanent and universal: any new deck could submit the legacy
    pair and skip both `render_integrity` and `art_direction` forever, which
    would make the entire art-direction gate optional by omission.
    """
    review = _review("visual_quality", "passed")
    fresh = gates.review_result_blockers(project, "slide", "sl-1", review, None)
    assert {"reason": "retired_reviewer_role"} in fresh
    replayed = gates.review_result_blockers(
        project, "slide", "sl-1", review, "ev-legacy-1")
    assert {"reason": "retired_reviewer_role"} not in replayed
```

Write `_slide_with_three_passing_reviews`, `_lint_clean_with_warnings`, and
`_review` as helpers in the same file, following the fixtures Task 9 already
established there; `answer_warnings` controls whether the `art_direction` review
carries a `linter_warnings_answered` entry for `occupancy`.

- [ ] **Step 7: Run them to verify they fail**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_reviewer_roles.py -v`
Expected: FAIL — `assert_slide_passable` returns normally in the first three,
and `review_result_blockers` reports no `retired_reviewer_role` in the fourth.

- [ ] **Step 8: Wire the gate**

In `presentation_gates.py`, add beside the other module-level constants:

```python
# `visual_quality` remains in `_REVIEW_ROLES` so persisted pre-split events stay
# admissible on replay. It must not be writable: a new deck that could still
# submit the legacy role pair would bypass both `render_integrity` and
# `art_direction`, which is the whole of this plan.
_RETIRED_REVIEW_ROLES = frozenset({"visual_quality"})
```

In `review_result_blockers`, immediately after the existing role check at
line 548:

```python
    if role in _RETIRED_REVIEW_ROLES and persisted_id is None:
        blockers.append({"reason": "retired_reviewer_role"})
```

and, at the end of the same function, the warning check:

```python
    if role == "art_direction" and review.get("status") == "passed":
        digest = current_svg_digest(project_root, subject_type, subject_id)
        evidence = None if digest is None else current_lint_evidence(
            project_root, subject_type, subject_id, digest,
            _tokens_digest(project_root))
        if evidence is None:
            blockers.append({"reason": "art_direction:lint_evidence_missing"})
        else:
            unanswered = unanswered_warnings(evidence, review)
            if unanswered:
                blockers.append({
                    "reason": "art_direction:linter_warnings_unanswered",
                    "rules": unanswered,
                })
```

In `assert_slide_passable`, after the role loop and before the status check:

```python
    blockers.extend(lint_blockers(
        project_root, "slide", slide_id, _tokens_digest(project_root)))
```

`_tokens_digest(project_root)` returns the digest of the deck's *effective*
token set — the `_effective.tokens.yaml` plan 1 Task 16 writes, which is the
composition of the token file and the deck's style Markdown, not the file passed
to `--tokens`. Resolve it through the same `style_tokens_ref` path
`validate_style_tokens_resolvable` uses in plan 1 Task 4, and return
`DesignTokens.load(path).digest`. Raise rather than defaulting if it cannot be
resolved: a gate that falls back to a built-in token set when it cannot find the
deck's own is comparing the slide against the wrong contract, which is worse
than refusing.

Import `current_lint_evidence`, `current_svg_digest`, `lint_blockers`, and
`unanswered_warnings` from `lint_evidence` at the top of the module.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -v`
Expected: PASS — the whole suite.

Existing tests that call `assert_slide_passable` on a fixture with no artifact
and no lint evidence will now fail with `lint_artifact_missing`. Give those
fixtures a published `slide-svg` artifact and a recorded clean lint result;
do not relax the gate to accommodate a fixture that predates it. If a test
existed specifically to assert that three reviews are sufficient, its claim has
changed and it should be rewritten to assert the new rule, with the reason
stated in the commit body.

- [ ] **Step 10: Say so in `SKILL.md`**

Replace the Stage 10 paragraph Task 8 wrote with the enforced version:

````markdown
Run the visual-style linter over every slide SVG, recording the result:

```bash
python3 "$SCRIPTS/validate_visual_style.py" "$SLIDES_DIR"/*.svg \
    --tokens "$STYLE_TOKENS_REF" \
    --record "$PROJECT_ROOT" --subject-type slide --subject-id "$SLIDE_ID"
```

The exit code is not the gate; the recorded result is. `assert_slide_passable`
refuses a slide with no lint evidence, with evidence older than the current SVG
or token file, or with outstanding hard errors — so re-running the linter after
every edit is not diligence, it is the only way the slide ever passes.

Warnings do not block. They are handed to the art-direction reviewer, who must
answer each one by rule id in `linter_warnings_answered`; an `art_direction`
review that passes with a warning unanswered is refused.
````

- [ ] **Step 11: Re-verify the shipped example under the enforced gate**

Task 13 rebuilt `examples/report-slides/visual-authoring` and verified it with
the linter alone — which, at the time, was all there was. The example deck is
what a user reads to learn what "good" means here, so it must satisfy the gate
their own decks are held to, not a weaker one.

For each of the three example slides:

1. Publish its `slide-svg` artifact, so `current_svg_digest` has bytes to name.
2. Run `validate_visual_style.py` with `--record`, so there is current evidence.
3. Record an `art_direction` review that answers every warning that run raised,
   by rule id, in `linter_warnings_answered`. Answer them from the slide, not
   from Task 13's commit message: an answer that does not describe the slide in
   front of you is the failure mode this field exists to expose.
4. Assert the whole thing:

```python
@pytest.mark.parametrize("slide_id", _EXAMPLE_SLIDE_IDS)
def test_every_shipped_slide_passes_the_enforced_gate(
        slide_id: str, example_project: Path) -> None:
    """The example deck clears the gate a user's deck must clear.

    Task 13 verified these slides with the linter alone. That was the strongest
    check available then and is not the check users face now: an example that
    passes a weaker gate than the product teaches the wrong thing twice over --
    once about the slide, once about what counts as done.
    """
    assert gates.assert_slide_passable(example_project, slide_id)
```

Add it to `skills/report-slides/scripts/tests/test_shipped_examples.py`, the
file Task 13 created. If a slide cannot clear the gate, that is a finding about
Task 13's redesign or about the token defaults — say which, and fix it. Do not
record an art-direction pass to make this green.

- [ ] **Step 12: Commit**

```bash
git add skills/report-slides/scripts/lint_evidence.py \
        skills/report-slides/scripts/tests/test_lint_evidence.py \
        skills/report-slides/scripts/tests/test_reviewer_roles.py \
        skills/report-slides/scripts/validate_visual_style.py \
        skills/report-slides/scripts/presentation_gates.py \
        skills/report-slides/scripts/tests/test_shipped_examples.py \
        skills/report-slides/SKILL.md
git commit -m "feat(report-slides): make the visual-style linter an enforced gate

The linter was documented as blocking and enforced nothing: its exit code was
gone before any gate ran, so a slide could pass three reviews without it. Lint
results are now persisted as events bound to the SVG and token digests they
examined, assert_slide_passable requires a current passing result, and an
art-direction pass must answer every warning that result raised by rule id.

Also refuses new visual_quality reviews. The legacy role pair stays admissible
on replay so pre-split decks complete, but a new deck submitting it would have
bypassed both render_integrity and art_direction permanently."
```

---

## Final Verification

- [ ] **Whole suite**

Run: `timeout 1800 python3 -m pytest skills/report-slides/scripts/tests/ -v`
Expected: PASS, no skips added by this plan, no xfail.

- [ ] **The linter runs on a real deck end to end**

Run:
```bash
timeout 300 python3 skills/report-slides/scripts/validate_visual_style.py \
  --svg examples/report-slides/visual-authoring/slides/*.svg
```
Expected: exit 0, with any warnings printed and answered in the deck's
`review.json`.

- [ ] **Every rule in the inventory is implemented and reachable**

Run:
```bash
timeout 120 python3 -c "
import sys; sys.path.insert(0, 'skills/report-slides/scripts')
from validate_visual_style import RULE_MODULES
rules = sorted({r for m in RULE_MODULES for r in m.RULES})
print(len(rules)); print('\n'.join(rules))
"
```
Expected: `22`, and the printed list matches the Rule Inventory tables above
exactly. A rule in the inventory that is not in this list is an unimplemented
requirement, not a documentation slip.

- [ ] **The generative route is genuinely opt-in**

Run: `grep -n "default" skills/report-slides/agents/conceptual_illustration_worker_agent.md`
Expected: no line asserting that the generative route is the default.

- [ ] **The three review roles are all reachable**

Run:
```bash
timeout 120 python3 -c "
import sys; sys.path.insert(0, 'skills/report-slides/scripts')
import presentation_gates as g
print(sorted(g._REVIEW_ROLES))
print(g.slide_reviews_complete({'scientific','render_integrity','art_direction'}))
print(g.slide_reviews_complete({'scientific','visual_quality'}))
print(g.slide_reviews_complete({'scientific','render_integrity'}))
"
```
Expected: all four roles listed, then `True`, `True`, `False`.

---

## Self-Review

**Spec coverage.** §D4 (deterministic linter) → Tasks 1–8. §D5 (review split) →
Tasks 9–10. §D6 (generative art direction) → Tasks 11–13. §2.1 (the shipped
example) → Task 13. §2.11 (prose gates) → Task 8 Step 5. §2.12 (reviewer remit)
→ Task 10. §2.13 (compose, don't create) → Tasks 10 and 12. §2.2–§2.10 and
§2.14–§2.15 are plan 1's, and are listed there.

**Not covered by either plan, and deliberately so.** Automatic graph layout
(spec §5): the linter reports that a layout is wrong, and the art-direction
reviewer can require a re-layout, but neither produces one. That remains an
authoring task. Naming it here rather than leaving it implicit is the point: a
reader should not finish these two plans expecting the deck to lay itself out.

**Two tests are deliberately replaced, not weakened.**
`test_current_role_set_completes_a_slide` (Task 9) is superseded by
`test_all_three_roles_are_now_required` (Task 10) — the claim genuinely changes
when the third gate exists. `test_parse_rejects_a_prompt_with_no_yaml_block` is
replaced by a pair covering both accepted record forms, because the shipped
counter-example is a plain YAML document and had to be validatable in place.
Both changes are stated in the tasks that make them, with the reason.

**Two spec requirements the first draft got wrong, and how they are now read.**
§D5 names eight art-direction finding kinds; the first draft invented six of its
own. The spec's eight are now used verbatim, in `presentation_gates.py`, in the
reviewer persona, and in the re-reading of the shipped counter-example. §D6 says
the registry "ships empty" and that anchors are "identified by actual reference
images with recorded digests — not adjective lists"; the first draft shipped
three prose anchors with `reference_image: null`. The registry is now empty,
`reference_images` is mandatory and SHA-256-verified, and the three prose
descriptions live in the README as briefs for whoever curates the images. While
the registry is empty every generative record is refused and every conceptual
module downgrades to a native editorial composition — which is the spec's
intended default, not a gap.

**Scope of the art-direction gate.** §D5 scopes that reviewer to the "complete
slide, not isolated modules". `SLIDE_REVIEW_ROLE_SETS` and
`MODULE_REVIEW_ROLE_SETS` are therefore separate, and
`presentation_workflow.py`'s two completion branches take different predicates.
Collapsing them — which the first draft did — would have left every module at
`in_review` permanently the moment Task 10 added `art_direction` to the slide
set, because nothing dispatches that reviewer for a fragment.
`test_modules_are_not_held_to_the_art_direction_gate` pins this.

**Measurement.** `TextRun.bbox()` is `ascent + line_offset + descent`, where the
first and last come from `fonts.vertical_metrics` — plan 1 Task 5, the same
function the renderer uses — and `line_offset` sums the `dy` the renderer
actually wrote onto the tspans. Nothing here estimates a text box from an em
fraction. Task 8's end-to-end test renders a real frame with `generate_slides`
and lints the result, which is what caught the footer sitting three units below
the safe area on every slide that has one.

**Ordering constraints.** Task 3 must precede Tasks 6 and 7 (`node_bounds`).
Tasks 1 and 2 precede everything. Task 8 needs Tasks 3–7. Task 10 needs Task 9's
`SLIDE_REVIEW_ROLE_SETS`. Task 12 needs Task 11's registry. Task 13 needs
Tasks 8, 10, and 12. Plan 1 must be complete before Task 1, because
`design_tokens.py` and `fonts.py` are imported from its Tasks 2 and 5.

**Type consistency.** Every rule module exposes exactly
`RULES: Tuple[str, ...]` and `check(scene: Scene, tokens: DesignTokens)
-> List[Finding]`; Task 8's `RULE_MODULES` and its parametrised test enforce it.
`Box` carries twelve positional fields plus `bleed`, and every construction site
in Tasks 2, 3, and 6 passes all thirteen. `Connector` carries eleven fields plus
`from_node` and `to_node`, both defaulted, and the two construction sites in
Task 2 pass them explicitly.

---

## Revision, after review

Reviewed together with plan 1; that document carries the shared findings and the
rejections. What follows is this plan's own.

**Defects fixed in this plan:**

| Defect | Evidence | Where it landed |
|---|---|---|
| The linter was documented as blocking and enforced nothing | Task 8's Files block touched the linter, its tests, `SKILL.md`, and `visual-review.md` — no `presentation_*` file. A shell exit code is gone by the time `assert_slide_passable` runs, so a slide could pass three reviews with the linter never having run, and a slide that passed yesterday still counted as passed after its SVG was rewritten | **Task 14** |
| `linter_warnings_answered` was decorative | The art-director persona said an unanswered warning makes a review incomplete; nothing validated the field, bound it to a run, or noticed it was absent | Task 14 Step 8 |
| The legacy role pair was a permanent bypass | `SLIDE_REVIEW_ROLE_SETS` accepts `{scientific, visual_quality}` with no version gate, so a new deck could submit it forever and skip both `render_integrity` and `art_direction` — the whole of this plan. `review_result_blockers` already takes `persisted_id`, which distinguishes a replay from a new write | `_RETIRED_REVIEW_ROLES`, Task 14 |
| The art-direction vocabulary contradicted the spec | Spec §D5 names eight kinds: `visual-cliche`, `decorative-noise`, `style-drift`, `synthetic-detail`, `meaningless-interface`, `stock-ai-composition`, `weak-hierarchy`, `undifferentiated-repetition`. This plan had invented six others | Task 10, and the counter-example re-read in Task 13 |
| The style-anchor registry was the thing the spec rejects | §D6 requires anchors "identified by actual reference images with recorded digests — not adjective lists", and says the design "ships the registry empty with a documented procedure". The plan shipped three prose anchors with `reference_image: null` and asserted `len(anchors) >= 3` | Task 11 |
| §D6's three-candidate blind ranking was documented nowhere and enforced nowhere | The spec requires three candidates ranked blind against the anchor, and prohibits accepting the least-bad image | Task 12's `_candidate_errors` |
| Modules would have been held to a whole-slide art-direction gate | §D5 scopes that reviewer to the "complete slide, not isolated modules". Task 9 replaced *both* completion branches with one predicate; once Task 10 added `art_direction`, every module would have stopped at `in_review` permanently, because nothing dispatches that reviewer for a fragment | `MODULE_REVIEW_ROLE_SETS`, Task 9 |
| The text box was modelled from guessed constants | `bbox()` used `y − 0.8 · size` and `size · line_count · 1.2`. It is now `ascent + line_offset + descent`, from the same `fonts.vertical_metrics` the renderer uses, with `line_offset` summing the `dy` the renderer wrote onto the tspans | Task 2 |
| Nothing ran the linter over markup the renderer produced | Every linter test used hand-written fixtures and every renderer test asserted on strings, so plan 1's footer defect was invisible to both plans | Task 8's end-to-end test |
| Twenty-two rules would have started blocking with no corpus | Every rule was written against a fixture built to exercise it; none had been run over a whole realistic slide. The recorded response to a hard error nobody believes is to relax the rule, and a relaxed rule does not come back | Task 8 Step 5 |
| The shipped example was verified against a weaker gate than users face | Task 13 verified the rebuilt example deck with the linter alone, which was all there was at the time | Task 14 Step 11 |

**Ordering note.** Task 14 is last because it depends on everything: Task 8's
linter, Task 10's roles, and Task 13's rebuilt example, which it re-verifies
under the gate it installs. Plan 1's Task 16 must land before Task 14 runs,
because `_tokens_digest` reads the composed `_effective.tokens.yaml` rather than
the base token file.
