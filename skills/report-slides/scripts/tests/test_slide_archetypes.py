"""What the rule set says about six realistic slides.

These are not tests of one rule. They are the record of what the whole suite
reports about the layouts this skill produces, and they exist so that a change
to any rule shows up as a change to a slide that a person can look at.

A finding recorded here is not thereby endorsed. An entry in `_EXPECTED` with a
comment saying "false positive, rule too strict" is a legitimate state and is
better than the alternative, which is not knowing.

Five archetypes are rendered by `generate_slides.py`. The sixth, `architecture`,
has no renderer: SKILL.md Stage 9 has an agent author that SVG by hand, so the
fixture below is the hand-authored form the skill actually produces, written to
the same token contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Set

import pytest

import generate_slides as gs
from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from fonts import resolve_font_stack
from validate_visual_style import lint_svg

_ARCHETYPES = (
    "bullets", "bar_chart", "pie_chart", "two_column", "timeline", "table",
    "architecture",
)

_META = {"footer": "Lab notes 2026-09-05"}

_SLIDES: Dict[str, Dict[str, Any]] = {
    "bullets": {
        "index": 1, "type": "bullet_list", "title": "What changed",
        "bullets": ["Tokenised the renderer",
                    "Measured text with real font metrics",
                    "Exported native tables and charts"],
        "numbered": True,
    },
    "bar_chart": {
        "index": 2, "type": "bar_chart", "title": "Accuracy by split",
        "categories": ["Dev", "Test"],
        "series": [
            {"label": "baseline", "color": "#b45309", "values": [72.1, 81.6]},
            {"label": "this run", "color": "#047857", "values": [98.4, 100.0]},
        ],
        "y_max": 100, "unit": "%", "note": "Median of five runs.",
    },
    "pie_chart": {
        "index": 3, "type": "pie_chart", "title": "Where the time went",
        "categories": ["Rendering", "Linting", "Review"],
        "values": [46.0, 31.0, 23.0],
        "colors": ["#1e3a5f", "#047857", "#b45309"],
        "note": "Wall-clock across the run.",
    },
    "two_column": {
        "index": 4, "type": "two_column", "title": "Before and after",
        "left": {"title": "Problem",
                 "content": ["Prose-only gates", "No measured floors"]},
        "right": {"title": "This run",
                  "content": ["Deterministic linter", "Token contract"]},
    },
    "timeline": {
        "index": 4, "type": "timeline", "title": "Delivery",
        "events": [
            {"label": "Spec", "date": "2026-09-01", "color": "#b45309",
             "detail": "design agreed"},
            {"label": "Plan 1", "date": "2026-09-03", "color": "#1e3a5f",
             "detail": "tokens shipped"},
            {"label": "Plan 2", "date": "2026-09-05", "color": "#047857",
             "detail": "linter shipped"},
        ],
    },
    "table": {
        "index": 5, "type": "table", "title": "Results",
        "columns": ["Metric", "Before", "After", "Delta"],
        "rows": [["Accuracy", "81.6%", "100%", "+18.4%"],
                 ["Recall", "74.0%", "96.2%", "+22.2%"]],
        "highlight_col": 3,
    },
}

_ARCHITECTURE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#ffffff"/>
  <rect x="0" y="0" width="1200" height="6" fill="#1e3a5f" data-bleed="true"/>
  <text x="48" y="96" font-size="32" font-weight="700" fill="#1e3a5f"
        data-style-role="slide_title">Retrieval pipeline</text>
  <g data-pptx-role="group" data-node-id="ingest">
    <rect x="96" y="240" width="256" height="120" rx="8" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <text x="224" y="306" font-size="18" font-weight="600" fill="#374151"
          text-anchor="middle" data-style-role="node_label">Ingest</text>
  </g>
  <g data-pptx-role="group" data-node-id="index">
    <rect x="472" y="240" width="256" height="120" rx="8" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <text x="600" y="306" font-size="18" font-weight="600" fill="#374151"
          text-anchor="middle" data-style-role="node_label">Index</text>
  </g>
  <g data-pptx-role="group" data-node-id="rank">
    <rect x="848" y="240" width="256" height="120" rx="8" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <text x="976" y="306" font-size="18" font-weight="600" fill="#374151"
          text-anchor="middle" data-style-role="node_label">Rank</text>
  </g>
  <line x1="352" y1="300" x2="472" y2="300" stroke="#475569" stroke-width="2"
        marker-end="url(#arrow)" data-from="ingest" data-to="index"/>
  <line x1="728" y1="300" x2="848" y2="300" stroke="#475569" stroke-width="2"
        marker-end="url(#arrow)" data-from="index" data-to="rank"/>
  <text x="48" y="636" font-size="12" fill="#64748b"
        data-style-role="footnote">Lab notes 2026-09-05</text>
</svg>"""

# Rule ids the suite reports on each archetype, error and warning alike.
#
# Every entry below was read and judged, not merely recorded:
#
# `off-grid` on four of six archetypes is a true observation about the
# renderers and a deliberate non-fix. Timeline node circles and bullet markers
# are placed by dividing the safe area by the number of items, which lands on
# eighths only by accident. Quantising them to 8 units would visibly unbalance
# a three-item row to buy alignment nobody can see. It is a warning for exactly
# this reason: it is evidence for the art-direction reviewer, not a build
# failure. Chart plot geometry no longer appears here -- bars and bands are
# placed by the value they encode, and the rule now exempts anything inside a
# `data-pptx-role="chart"` group rather than firing once per bar.
#
# `occupancy` outside 0.30..0.78 on four archetypes is also true and also not a
# defect. A three-bullet slide and a three-event timeline are legitimately
# sparse, and a two-column slide with two full panels is legitimately dense.
# The rule exists to raise the question, and the answer here is "yes,
# deliberately".
#
# `bar_chart` reports nothing at all. That is the shape a clean slide has, and
# it is worth one line of its own: the entry is not an oversight.
#
# `pie_chart` is here because a pie is drawn entirely in `<path>`, and until
# `Scene.outline_boxes()` existed those paths were unmeasured: this slide
# unioned to 0.03 of the safe area -- the title and the legend -- and the gate
# reported a slide carrying a 400-unit disc as nearly empty. It now measures
# 0.27, still under `occupancy_min`, and that is a true observation about the
# renderer: a radius-200 pie placed left of centre leaves the right half of
# the frame to a three-row legend. It is the art-direction reviewer's question
# to answer, not a build failure, which is why it is a warning and why the
# entry is recorded rather than fixed here.
_EXPECTED: Dict[str, Set[str]] = {
    "bullets": {"occupancy", "off-grid"},
    "bar_chart": set(),
    "pie_chart": {"occupancy"},
    "two_column": {"occupancy", "off-grid"},
    "timeline": {"occupancy", "off-grid"},
    "table": {"occupancy", "off-grid"},
    "architecture": {"occupancy"},
}


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _render_archetype(archetype: str, tmp_path: Path) -> Path:
    """Render one archetype to an SVG file and return its path.

    Args:
        archetype: A key of `_ARCHETYPES`.
        tmp_path: Directory to write into.

    Returns:
        The written SVG path.
    """
    path = tmp_path / f"{archetype}.svg"
    if archetype == "architecture":
        path.write_text(_ARCHITECTURE_SVG, encoding="utf-8")
        return path
    gs.apply_tokens(DEFAULT_TOKENS_PATH)
    path.write_text(gs.generate_slide(_SLIDES[archetype], _META),
                    encoding="utf-8")
    return path


@pytest.mark.parametrize("archetype", _ARCHETYPES)
def test_the_rule_set_says_what_it_is_recorded_as_saying(
        archetype: str, tmp_path: Path, tokens: DesignTokens) -> None:
    """Lint a rendered archetype and compare against the recorded findings."""
    svg = _render_archetype(archetype, tmp_path)
    report = lint_svg(svg, tokens, resolve_font_stack(tokens.font_stack("sans")))
    assert {finding.rule for finding in report.findings} == _EXPECTED[archetype]


@pytest.mark.parametrize("archetype", _ARCHETYPES)
def test_no_archetype_carries_a_hard_error(archetype: str, tmp_path: Path,
                                           tokens: DesignTokens) -> None:
    """A slide this skill renders from its own defaults must build.

    If a renderer's own output fails a hard rule, the defect is in the renderer
    or in the rule -- not in the user's deck. Fix whichever is wrong and say
    which in the commit body. Do not downgrade the rule to a warning to make
    this pass; that is the failure this whole task exists to prevent.
    """
    svg = _render_archetype(archetype, tmp_path)
    report = lint_svg(svg, tokens, resolve_font_stack(tokens.font_stack("sans")))
    errors = [f.rule for f in report.findings if f.severity == "error"]
    assert errors == [], f"{archetype} fails: {errors}"
