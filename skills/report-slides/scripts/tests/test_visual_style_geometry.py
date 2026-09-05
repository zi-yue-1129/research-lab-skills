"""Tests for the geometry rules."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

import pytest

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from fonts import vertical_metrics
from visual_style import geometry
from visual_style.scene import Box, PathShape, Scene, TextRun


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
    """Default grid is 8; x=99 is 3 units off the nearest multiple and warns.

    Every other extent here is a multiple of 8, so the warning can only come
    from x. y=96 rather than 100 for that reason: 100 is itself 4 units off the
    grid and would make this test pass for the wrong element.
    """
    scene = _scene(boxes=[_box("b1", 99, 96, 200, 88)])
    findings = geometry.check_grid(scene, tokens)
    assert [f.rule for f in findings] == ["off-grid"]
    assert findings[0].severity == "warning"
    assert "x=99" in findings[0].message


def test_grid_tolerance_absorbs_small_drift(tokens: DesignTokens) -> None:
    """A 2-unit deviation is within tolerance and does not warn.

    x=98 sits 2 units from 96; the tolerance is 2, so it is absorbed.
    """
    scene = _scene(boxes=[_box("b1", 98, 96, 200, 88)])
    assert geometry.check_grid(scene, tokens) == []


def test_data_marks_are_exempt_from_the_grid(tokens: DesignTokens) -> None:
    """A bar's height encodes a value; the grid does not apply to it."""
    bar = Box("bar1", "rect", 103, 100, 40, 137, "#1e3a5f", None, 0, 0,
              "chart.bar", None, False)
    assert geometry.check_grid(_scene(boxes=[bar]), tokens) == []


def test_check_runs_every_geometry_rule(tokens: DesignTokens) -> None:
    """The module entry point aggregates all five rules.

    The scene trips every one of them, so a `check()` that stopped dispatching
    a rule fails here. Asserting `set(geometry.RULES)` against a hand-written
    literal, as this test used to, is a statement about a constant.

    `far` leaves the right margin, `b1` and `b2` are different nodes that
    overlap, `g1` and `g2` are 10 apart against a 24-unit floor, `label` hangs
    half out of its own node, and every box here is off the 8-unit grid.
    """
    scene = _scene(
        boxes=[_box("far", 1100, 100, 200, 90),
               _box("b1", 200, 300, 200, 90, node_id="n1"),
               _box("b2", 300, 330, 200, 90, node_id="n2"),
               _box("g1", 601, 500, 100, 50, node_id="n3"),
               _box("g2", 711, 500, 100, 50, node_id="n4")],
        texts=[_text("label", 380, 340, 120, node_id="n1")])
    rules = {f.rule for f in geometry.check(scene, tokens)}
    assert rules == set(geometry.RULES)


def test_abutting_tiles_are_not_an_overlap(tokens: DesignTokens) -> None:
    """A sliver from tiling arithmetic is not a collision.

    `render_table` lays row bands by accumulating float row heights, so band n
    can end at 209.0 while band n+1 starts at 208.9. Reporting a hard error for
    a tenth of a unit fires on every table slide and turns the rule into noise,
    which is how a gate gets switched off. Overlap must be material in both
    axes before it counts.
    """
    scene = _scene(boxes=[_box("b1", 100, 160, 400, 49.0),
                          _box("b2", 100, 208.9, 400, 49.0)])
    assert geometry.check_overlap(scene, tokens) == []


def test_one_node_swallowing_another_is_an_error(
        tokens: DesignTokens) -> None:
    """Containment is composition only inside a single node.

    `check_overlap` treated any containment as intended and `check_node_gap`
    skips pairs that intersect on the grounds that overlap covers them, so a
    node drawn wholly inside another node passed both rules. That is the
    worst-looking defect a diagram can have and it had a clear path through.
    """
    scene = _scene(boxes=[_box("b1", 96, 96, 400, 200, node_id="n1"),
                          _box("b2", 160, 128, 120, 80, node_id="n2")])
    rules = {f.rule for f in geometry.check_overlap(scene, tokens)}
    assert rules == {"element-overlap"}


def test_a_box_inside_an_unscoped_container_is_still_composition(
        tokens: DesignTokens) -> None:
    """A card inside a panel that carries no node id stays exempt.

    Panels, plates and backing shapes are laid out without a `data-node-id`.
    Reporting those would fire on every two-column and metric-card slide.
    """
    scene = _scene(boxes=[_box("panel", 96, 96, 400, 200),
                          _box("card", 160, 128, 120, 80, node_id="n2")])
    assert geometry.check_overlap(scene, tokens) == []


def test_chart_furniture_is_exempt_from_the_grid(
        tokens: DesignTokens) -> None:
    """Bars are placed by the value they encode, not by the layout grid.

    The exemption keyed on `data-style-role` starting with `chart`, but the
    renderers do not put a style role on generated bars -- they wrap the whole
    plot in `data-pptx-role="chart"`. Every bar on every chart slide therefore
    produced an `off-grid` warning, which is the noise that gets a rule muted.
    """
    bar = _box("rect#21", 163, 211.4, 47, 268.6)
    plain = _scene(boxes=[bar])
    assert {f.rule for f in geometry.check_grid(plain, tokens)} == {"off-grid"}
    charted = _scene(boxes=[replace(bar, pptx_role="chart")])
    assert geometry.check_grid(charted, tokens) == []


def test_a_label_that_escapes_its_node_is_reported(
        tokens: DesignTokens) -> None:
    """A label hanging outside its own box is the defect padding exists for.

    `_enclosing_box` returned None when no box of the node contained the
    label's centre, and the rule then skipped the run entirely. The further
    the label escaped, the more certainly it was ignored.

    Half in and half out is the shape of the defect. A label placed wholly
    outside its node is a different idiom -- a timeline dot with its label on
    a stem -- and is checked by `test_a_label_placed_beside_its_node_is_fine`.
    """
    scene = _scene(
        boxes=[_box("plate", 96, 96, 200, 88, node_id="n1")],
        texts=[_text("label", 280, 175, 120, node_id="n1")])
    findings = geometry.check_node_padding(scene, tokens)
    assert {f.rule for f in findings} == {"node-padding"}


def test_a_label_placed_beside_its_node_is_fine(tokens: DesignTokens) -> None:
    """A timeline dot carries its label outside itself, on purpose."""
    scene = _scene(
        boxes=[_box("dot", 300, 300, 20, 20, node_id="n1")],
        texts=[_text("label", 260, 260, 100, node_id="n1")])
    assert geometry.check_node_padding(scene, tokens) == []


def _outline(element_id: str, x: float, y: float, w: float, h: float,
             bleed: bool = False) -> PathShape:
    """Build a measured `<path>` for rule testing."""
    extent = Box(element_id, "path", x, y, w, h, "#1e3a5f", None, 0.0, 0.0,
                 None, None, bleed)
    return PathShape(element_id, "#1e3a5f", None, 0.0, None, None, None,
                     extent)


def _outline_scene(paths) -> Scene:
    """Build a scene whose only content is free-form shapes."""
    return Scene(1200, 675, (), (), (), (), "DejaVu Sans", tuple(paths))


def test_a_wedge_that_leaves_the_safe_area_is_an_error(
        tokens: DesignTokens) -> None:
    """Free-form shapes are held to the margins like everything else.

    A pie chart is drawn entirely in `<path>`, so while paths were unmeasured
    a wedge could run past the right margin and the gate reported the slide
    clean -- and the human reviewer had been told the margins were already
    checked by the linter.
    """
    scene = _outline_scene([_outline("wedge", 900, 100, 260, 90)])
    findings = geometry.check_safe_area(scene, tokens)
    assert [f.rule for f in findings] == ["safe-area"]
    assert findings[0].element_id == "wedge"


def test_a_bleeding_wedge_is_exempt_like_any_other_bleed(
        tokens: DesignTokens) -> None:
    """`data-bleed` means the same thing on a path as on a rect."""
    scene = _outline_scene([_outline("wedge", 0, 0, 1200, 40, bleed=True)])
    assert geometry.check_safe_area(scene, tokens) == []


def test_outline_extents_do_not_trip_element_overlap(
        tokens: DesignTokens) -> None:
    """A bounding box is not the shape, so it cannot arbitrate collisions.

    Adjacent pie wedges share a centre: their bounding boxes overlap almost
    completely while the wedges themselves do not touch, and an arrowhead is
    drawn deliberately against the node edge it points at. Feeding either into
    `element-overlap` would manufacture errors on every correct chart, so the
    extents reach `safe-area` and `occupancy` -- where a superset is a safe
    over-estimate -- and stop there.
    """
    scene = _outline_scene([_outline("w1", 400, 200, 200, 200),
                            _outline("w2", 450, 200, 200, 200)])
    assert geometry.check_overlap(scene, tokens) == []


def test_a_label_stranded_far_from_a_plate_that_could_hold_it_is_an_error(
        tokens: DesignTokens) -> None:
    """Escaping a surface that had room for you is a defect, not an idiom.

    The wholly-outside exemption was written for the timeline dot, and as
    written it exempted everything: a label 400 units clear of the 200x88
    plate it belongs to passed silently, which is the single most visible way
    an architecture diagram can break. The discriminator is capacity, not
    distance -- a node big enough to seat the label with its padding was
    supposed to be seating it.
    """
    scene = _scene(
        boxes=[_box("plate", 96, 96, 200, 88, node_id="n1")],
        texts=[_text("label", 700, 400, 120, node_id="n1")])
    findings = geometry.check_node_padding(scene, tokens)
    assert [f.rule for f in findings] == ["node-padding"]
    assert "plate" in findings[0].message


def test_a_label_beside_a_node_too_small_to_seat_it_is_still_fine(
        tokens: DesignTokens) -> None:
    """A 20x20 dot cannot hold a 100-unit label, so its label sits outside.

    This is the case the exemption exists for and it must keep passing: every
    event on every timeline slide is drawn this way.
    """
    scene = _scene(
        boxes=[_box("dot", 300, 300, 20, 20, node_id="n1")],
        texts=[_text("label", 260, 500, 100, node_id="n1")])
    assert geometry.check_node_padding(scene, tokens) == []


def test_nodes_that_graze_are_caught_by_one_rule_or_the_other(
        tokens: DesignTokens) -> None:
    """Two tolerances that disagree leave a band where nothing is checked.

    `element-overlap` ignores intersections shallower than half a unit, which
    is right: renderers tile abutting bands with accumulated floats. But
    `node-gap` skipped every pair that merely `intersects`, so a 0.3-unit
    overlap between two nodes fell between the two rules -- overlapping enough
    for the gap rule to stand aside, not enough for the overlap rule to speak.
    Two nodes touching each other at all are certainly not 24 units apart.
    """
    scene = _scene(boxes=[_box("a", 100, 100, 200, 90, node_id="n1"),
                          _box("b", 299.7, 100, 200, 90, node_id="n2")])
    assert geometry.check_overlap(scene, tokens) == []
    findings = geometry.check_node_gap(scene, tokens)
    assert [f.rule for f in findings] == ["node-gap"]


def test_materially_overlapping_nodes_are_still_left_to_the_overlap_rule(
        tokens: DesignTokens) -> None:
    """One defect, one finding: a real collision is not also a gap error."""
    scene = _scene(boxes=[_box("a", 100, 100, 200, 90, node_id="n1"),
                          _box("b", 250, 100, 200, 90, node_id="n2")])
    assert [f.rule for f in geometry.check_overlap(scene, tokens)] == [
        "element-overlap"]
    assert geometry.check_node_gap(scene, tokens) == []
