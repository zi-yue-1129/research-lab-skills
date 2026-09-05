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
