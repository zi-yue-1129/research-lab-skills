"""Tests for the density and consistency rules."""

from __future__ import annotations

from dataclasses import replace
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
    """The module entry point aggregates all five rules.

    Four identical cards with uneven gaps trip repetition and spacing at once,
    the square box drifts from the shared corner radius, seven body runs
    exceed the bullet budget, and the whole slide is far under the occupancy
    floor.
    """
    boxes = [_box("c1", 100, 400, 100, 90), _box("c2", 350, 400, 100, 90),
             _box("c3", 600, 400, 100, 90), _box("c4", 900, 400, 100, 90),
             _box("odd", 100, 100, 200, 90, radius=0)]
    texts = [_label(f"t{i}", 100, 150 + 30 * i, role="body") for i in range(7)]
    rules = {f.rule for f in density.check(_scene(boxes, texts), tokens)}
    assert rules == set(density.RULES)



def test_table_cells_are_not_bullets(tokens: DesignTokens) -> None:
    """Eight cells in a 2x4 table are not eight bullets.

    `render_table` gives every data cell the `body` role, so the budget rule
    counted a perfectly ordinary results table as a wall of bullets and warned
    on every table slide in every deck.
    """
    cells = [replace(_label(f"t{i}", 100, 150, role="body"),
                     pptx_role="table")
             for i in range(8)]
    assert density.check_bullet_budget(_scene(texts=cells), tokens) == []
