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
    with pytest.raises(ValueError, match="viewBox") as excinfo:
        parse_scene(path, _FAMILY)
    assert "viewBox" in str(excinfo.value)


def _parse(tmp_path: Path, body: str):
    """Parse an SVG fragment wrapped in a default canvas.

    Args:
        tmp_path: Directory to write the fixture into.
        body: Markup placed inside the root `<svg>` element.

    Returns:
        The parsed scene.
    """
    path = tmp_path / "fragment.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">'
        f"{body}</svg>", encoding="utf-8")
    return parse_scene(path, _FAMILY)


def test_a_translated_group_shifts_the_geometry_it_contains(
        tmp_path: Path) -> None:
    """A `transform` on an ancestor moves everything the rules measure.

    Without this every rule measures a translated group at its authored
    coordinates, so a node group pushed 400 units to the right is judged where
    it is not. The failure is silent, which makes it worse than a crash.
    """
    scene = _parse(tmp_path, '<g transform="translate(100, 50)">'
                             '<rect x="10" y="20" width="30" height="40"/></g>')
    assert (scene.boxes[0].x, scene.boxes[0].y) == (110.0, 70.0)


def test_nested_translations_accumulate(tmp_path: Path) -> None:
    """Transforms compose down the tree."""
    scene = _parse(tmp_path,
                   '<g transform="translate(100,0)">'
                   '<g transform="translate(0,50)">'
                   '<rect x="10" y="20" width="30" height="40"/></g></g>')
    assert (scene.boxes[0].x, scene.boxes[0].y) == (110.0, 70.0)


def test_a_transform_that_cannot_be_measured_is_refused(
        tmp_path: Path) -> None:
    """An unsupported transform raises rather than mismeasuring in silence.

    This test used to assert that `rotate(45)` was refused, and that
    expectation was wrong. `svg_to_pptx.style_parser.parse_transform` reads
    `translate`, `rotate`, `scale` and `matrix`, so a rotated group converts
    and ships; refusing it here failed the gate as `unreadable-input` on a
    slide that was perfectly fine, which is not a safe conservative default
    but a false negative dressed as caution. The linter now composes the
    matrix and measures the rotated element by its hull.

    `skewX` is the honest example: the converter does not read it either, so
    an element carrying one is drawn somewhere neither tool can predict.
    Quietly ignoring it and reporting a clean gate would be a lie.
    """
    with pytest.raises(ValueError, match="transform"):
        _parse(tmp_path, '<g transform="skewX(20)"><rect x="10" y="20" '
                         'width="30" height="40"/></g>')


def test_a_path_is_captured_for_colour_linting(tmp_path: Path) -> None:
    """Pie wedges are `<path>` elements and their fill must be linted.

    Geometry used to be deliberately absent here, on the grounds that a box
    guessed from the `d` string is wrong for arcs. `visual_style.paths` no
    longer guesses -- it solves the arc's endpoint parameterisation -- so the
    extent is now measured too and reaches `safe-area` and `occupancy`. The
    fill assertions below are unchanged and still the point of this test.
    """
    scene = _parse(tmp_path, '<path d="M0,0 L10,0 L10,10 Z" fill="#ff00ff" '
                             'data-style-role="chart.series"/>')
    assert len(scene.paths) == 1
    assert scene.paths[0].fill == "#ff00ff"
    assert scene.paths[0].style_role == "chart.series"


def test_the_canvas_background_is_kept_for_colour_resolution(
        tmp_path: Path) -> None:
    """A full-canvas rect is excluded from layout but drives contrast.

    Discarding it entirely makes every rule judge white text on a navy section
    divider against the token background, which is white: a contrast error on
    a slide that is correct.
    """
    scene = _parse(tmp_path, '<rect width="1200" height="675" fill="#1e3a5f"/>')
    assert scene.boxes == ()
    assert scene.background is not None
    assert scene.background.fill == "#1e3a5f"


def test_boxes_record_the_order_they_are_painted_in(tmp_path: Path) -> None:
    """Paint order decides which fill a point actually sits on."""
    scene = _parse(tmp_path,
                   '<rect x="0" y="0" width="100" height="100" fill="#ffffff"/>'
                   '<rect x="0" y="0" width="100" height="100" fill="#1e3a5f"/>')
    assert scene.boxes[0].paint_order < scene.boxes[1].paint_order


def test_a_tspan_smaller_than_its_parent_is_recorded(tmp_path: Path) -> None:
    """The type floor has to see the smallest size actually rendered.

    A 21-unit `<text>` carrying an 8-unit `<tspan>` renders 8-unit glyphs. The
    element's own `font-size` says nothing about them.
    """
    scene = _parse(tmp_path,
                   '<text x="10" y="20" font-size="21" fill="#374151">'
                   'big<tspan font-size="8">tiny</tspan></text>')
    assert scene.texts[0].size == 21.0
    assert scene.texts[0].min_size == 8.0


def test_tspan_fills_are_collected(tmp_path: Path) -> None:
    """Contrast has to see every colour the element actually paints."""
    scene = _parse(tmp_path,
                   '<text x="10" y="20" font-size="21" fill="#374151">'
                   'a<tspan fill="#e2e8f0">b</tspan></text>')
    assert set(scene.texts[0].fills) == {"#374151", "#e2e8f0"}


def test_the_marker_role_is_inherited_from_the_wrapping_group(
        tmp_path: Path) -> None:
    """`data-pptx-role` tells a rule whether it is looking at chart furniture."""
    scene = _parse(tmp_path, '<g data-pptx-role="chart">'
                             '<rect x="10" y="20" width="30" height="40"/></g>')
    assert scene.boxes[0].pptx_role == "chart"


def test_an_elbow_polyline_only_attaches_at_its_two_ends(
        tmp_path: Path) -> None:
    """A routed connector's corners are not attachment points.

    Every segment used to inherit both `data-from` and `data-to`, so a
    three-segment elbow produced four spurious `connector-port-drift` errors
    for corners that are not meant to touch a node at all.
    """
    scene = _parse(tmp_path,
                   '<polyline points="0,0 100,0 100,100 200,100" '
                   'stroke="#475569" marker-end="url(#a)" '
                   'data-from="n1" data-to="n2"/>')
    assert len(scene.connectors) == 3
    assert [c.from_node for c in scene.connectors] == ["n1", None, None]
    assert [c.to_node for c in scene.connectors] == [None, None, "n2"]


def test_a_tspan_is_measured_at_its_own_size(tmp_path: Path) -> None:
    """Line width has to use the size each line is actually set in.

    Measuring an 8-unit span at the parent's 21 units overstates its advance
    by more than a factor of two, which pushes the run's bounding box far to
    one side and invents overlap that is not there.
    """
    wide = _parse(tmp_path,
                  '<text x="10" y="20" font-size="21" fill="#374151">'
                  '<tspan font-size="21">MMMMM</tspan></text>')
    narrow = _parse(tmp_path,
                    '<text x="10" y="20" font-size="21" fill="#374151">'
                    '<tspan font-size="8">MMMMM</tspan></text>')
    assert narrow.texts[0].width < wide.texts[0].width / 2


def test_a_translate_in_scientific_notation_is_honoured(
        tmp_path: Path) -> None:
    """`translate(1e2,0)` is a hundred units, not nothing.

    The first argument matcher accepted only digits and dots, so an exponent
    made the whole call fail to match and the translation was silently dropped
    -- the element was then measured a hundred units from where it is drawn,
    and the linter reported a clean slide. Silently mismeasuring is the one
    outcome this parser must never have.
    """
    scene = _parse(tmp_path, '<g transform="translate(1e2,0)">'
                             '<rect x="10" y="20" width="30" height="40"/></g>')
    assert scene.boxes[0].x == 110.0


def test_a_translate_with_unreadable_arguments_is_refused(
        tmp_path: Path) -> None:
    """Arguments that are not plain numbers are refused, not ignored."""
    with pytest.raises(ValueError, match="transform"):
        _parse(tmp_path, '<g transform="translate(10px, 20px)">'
                         '<rect x="10" y="20" width="30" height="40"/></g>')


def test_trailing_junk_after_a_transform_is_refused(tmp_path: Path) -> None:
    """Anything the parser cannot account for has to raise."""
    with pytest.raises(ValueError, match="transform"):
        _parse(tmp_path, '<g transform="translate(10,20) 3 4">'
                         '<rect x="10" y="20" width="30" height="40"/></g>')


_OUTLINE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#ffffff"/>
  <path id="wedge" d="M600 337 L600 137 A200 200 0 0 1 800 337 Z"
        fill="#1e3a5f"/>
  <polygon id="head" points="700,145 720,140 720,150" fill="#475569"/>
</svg>"""


def test_a_path_carries_its_measured_extent(tmp_path: Path) -> None:
    """A `<path>` is measured, not merely catalogued for its fill.

    A pie chart is nothing but `<path>`, so while paths had no geometry a
    wedge could run off the canvas and every geometric rule reported a clean
    slide -- and `visual-review.md` tells the human reviewer those properties
    are already settled, so nobody was looking.
    """
    path = tmp_path / "outline.svg"
    path.write_text(_OUTLINE_SVG, encoding="utf-8")
    scene = parse_scene(path, _FAMILY)
    wedge = next(shape for shape in scene.paths if shape.element_id == "wedge")
    assert wedge.extent is not None
    assert (wedge.extent.x, wedge.extent.y) == pytest.approx((600.0, 137.0))
    assert (wedge.extent.w, wedge.extent.h) == pytest.approx((200.0, 200.0))


def test_outline_boxes_covers_paths_and_polygons(tmp_path: Path) -> None:
    """Both free-form shape kinds reach the rules through one accessor."""
    path = tmp_path / "outline.svg"
    path.write_text(_OUTLINE_SVG, encoding="utf-8")
    scene = parse_scene(path, _FAMILY)
    outlines = {box.element_id: box for box in scene.outline_boxes()}
    assert set(outlines) == {"wedge", "head"}
    head = outlines["head"]
    assert (head.x, head.y, head.w, head.h) == pytest.approx(
        (700.0, 140.0, 20.0, 10.0))


def test_outlines_stay_out_of_the_box_list(tmp_path: Path) -> None:
    """Outlines are a separate channel, not extra `boxes`.

    `off-grid`, `node-gap`, `component-drift` and `equal-card-repetition` all
    reason about authored rectangles. A wedge is not a card and its bounding
    box has no business being compared to one, so the extents travel in their
    own accessor and each rule opts in.
    """
    path = tmp_path / "outline.svg"
    path.write_text(_OUTLINE_SVG, encoding="utf-8")
    scene = parse_scene(path, _FAMILY)
    assert scene.boxes == ()


def test_a_path_whose_data_is_unreadable_is_refused(tmp_path: Path) -> None:
    """An unparseable `d` raises rather than silently measuring nothing."""
    path = tmp_path / "bad.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">'
        '<path id="p" d="M10 10 L20 banana"/></svg>', encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable"):
        parse_scene(path, _FAMILY)


_DEFS_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1200 675">
  <defs>
    <rect id="tile" x="0" y="0" width="120" height="60" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <marker id="arrow" markerWidth="10" markerHeight="10">
      <polygon points="0,0 10,5 0,10" fill="#475569"/>
    </marker>
  </defs>
  <use href="#tile" x="200" y="300"/>
  <use xlink:href="#tile" x="500" y="300"/>
</svg>"""


def test_defs_are_a_library_not_content(tmp_path: Path) -> None:
    """Nothing inside `<defs>` is drawn where it sits.

    Every deck this skill renders defines its arrowhead as a `<marker>` at the
    origin. Walking into `<defs>` measured that arrowhead as a real element at
    (0, 0) -- outside the safe area on every slide -- so the rule that should
    have caught a genuine margin breach was drowning in one guaranteed false
    error per slide instead.
    """
    path = tmp_path / "defs.svg"
    path.write_text(_DEFS_SVG, encoding="utf-8")
    scene = parse_scene(path, _FAMILY)
    assert all(box.element_id != "arrow" for box in scene.outline_boxes())
    assert not any(box.x == 0.0 and box.y == 0.0 for box in scene.boxes)


def test_use_draws_the_referenced_element_at_its_offset(
        tmp_path: Path) -> None:
    """`<use>` is how a deck reuses a shape, and the converter honours it.

    `svg_to_pptx` splices the referenced element in with a prepended
    `translate(x, y)`, so a `<use>` becomes a real shape in the PPTX. A linter
    that ignores `<use>` measures a different slide from the one that ships.
    """
    path = tmp_path / "defs.svg"
    path.write_text(_DEFS_SVG, encoding="utf-8")
    scene = parse_scene(path, _FAMILY)
    placed = sorted((box.x, box.y, box.w, box.h) for box in scene.boxes)
    assert placed == [(200.0, 300.0, 120.0, 60.0),
                      (500.0, 300.0, 120.0, 60.0)]


def test_a_use_of_a_missing_id_is_refused(tmp_path: Path) -> None:
    """A dangling reference draws nothing and must not pass silently."""
    path = tmp_path / "dangling.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">'
        '<use href="#nowhere" x="10" y="10"/></svg>', encoding="utf-8")
    with pytest.raises(ValueError, match="nowhere"):
        parse_scene(path, _FAMILY)


_TRANSFORM_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
  <g transform="scale(2)">
    <rect id="scaled" x="100" y="50" width="60" height="30" fill="#f8fafc"/>
    <text id="grown" x="120" y="70" font-size="12" fill="#374151">Legend</text>
  </g>
  <g transform="translate(100,100) rotate(90)">
    <rect id="turned" x="0" y="0" width="40" height="20" fill="#f8fafc"/>
  </g>
</svg>"""


def test_a_scaled_group_is_measured_at_its_drawn_size(tmp_path: Path) -> None:
    """`scale` is one of the four functions the converter reads.

    Refusing it made a convertible slide fail the gate as `unreadable-input`,
    which is a worse answer than measuring it: the deck ships either way, and
    only one of the two outcomes tells the author anything true.
    """
    path = tmp_path / "transform.svg"
    path.write_text(_TRANSFORM_SVG, encoding="utf-8")
    scene = parse_scene(path, _FAMILY)
    box = next(b for b in scene.boxes if b.element_id == "scaled")
    assert (box.x, box.y, box.w, box.h) == pytest.approx(
        (200.0, 100.0, 120.0, 60.0))


def test_a_scaled_text_run_carries_its_drawn_size(tmp_path: Path) -> None:
    """12pt inside `scale(2)` is 24pt on the slide, and the floors know it."""
    path = tmp_path / "transform.svg"
    path.write_text(_TRANSFORM_SVG, encoding="utf-8")
    scene = parse_scene(path, _FAMILY)
    run = next(t for t in scene.texts if t.element_id == "grown")
    assert run.size == pytest.approx(24.0)
    assert (run.x, run.y) == pytest.approx((240.0, 140.0))


def test_a_rotated_group_is_measured_by_its_hull(tmp_path: Path) -> None:
    """A quarter-turned 40x20 rect occupies 20x40 where it is drawn."""
    path = tmp_path / "transform.svg"
    path.write_text(_TRANSFORM_SVG, encoding="utf-8")
    scene = parse_scene(path, _FAMILY)
    box = next(b for b in scene.boxes if b.element_id == "turned")
    assert (box.x, box.y, box.w, box.h) == pytest.approx(
        (80.0, 100.0, 20.0, 40.0))
