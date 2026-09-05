"""Tests for the colour and contrast rules."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

import pytest

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from fonts import vertical_metrics
from visual_style import color
from visual_style.scene import (Box, Connector, PathShape, Polygon, Scene,
                                TextRun)


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


def test_background_uses_the_last_painted_containing_box(
    tokens: DesignTokens,
) -> None:
    """A card drawn over a panel gives the card's fill.

    This used to pick the smallest containing box, which happens to agree with
    paint order for a nested card and disagrees with it whenever a small shape
    is painted underneath a larger one. Document order is what SVG actually
    defines, and the parser now records it.
    """
    scene = _scene(boxes=[
        replace(_box("panel", "#e2e8f0", x=50, y=50, w=600, h=400),
                paint_order=1),
        replace(_box("card", "#f8fafc", x=100, y=100, w=200, h=100),
                paint_order=2)])
    assert color.background_at(150, 150, scene, tokens) == "#f8fafc"


def test_body_text_on_white_passes(tokens: DesignTokens) -> None:
    """#374151 on white is 10.31, above the 4.5 floor."""
    scene = _scene(texts=[_text("t1", "#374151")])
    assert color.check_text_contrast(scene, tokens) == []


def test_low_contrast_text_is_an_error(tokens: DesignTokens) -> None:
    """#e2e8f0 on white is 1.23 and fails the text floor.

    Set at 16 so the run is small text: 18 and above is WCAG large text in
    these units, and this test is about the small-text floor.
    """
    scene = _scene(texts=[_text("t1", "#e2e8f0", size=16)])
    findings = color.check_text_contrast(scene, tokens)
    assert [f.rule for f in findings] == ["text-contrast"]
    assert findings[0].severity == "error"
    assert "1.23" in findings[0].message
    assert "4.5" in findings[0].message


def test_large_text_uses_the_relaxed_floor(tokens: DesignTokens) -> None:
    """#94a3b8 on white is 2.56: fails at 16, still fails at 32.

    The small case was written at 21, which is above WCAG's 18pt large-text
    threshold, so it asserted the small-text floor for text that qualifies as
    large. These units are points -- the plan fixes SVG `font-size` as mapping
    1:1 to PowerPoint points and the converter passes it straight to `Pt()` --
    and 24 is the CSS-pixel equivalent at 96dpi, not the point threshold. The
    `body` role is 21, so the wrong threshold mis-classified the most common
    text on every slide in the deck.
    """
    small = _scene(texts=[_text("t1", "#94a3b8", size=16)])
    large = _scene(texts=[_text("t1", "#94a3b8", size=32)])
    assert len(color.check_text_contrast(small, tokens)) == 1
    assert "4.5" in color.check_text_contrast(small, tokens)[0].message
    assert "3.0" in color.check_text_contrast(large, tokens)[0].message


def test_bold_text_at_fourteen_points_counts_as_large(
        tokens: DesignTokens) -> None:
    """WCAG treats bold text at 14pt and above as large.

    18.66 is that threshold expressed in CSS pixels; these units are points.
    """
    scene = _scene(texts=[_text("t1", "#94a3b8", size=15, weight=700)])
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
                   texts=[_text("t1", "#e2e8f0", size=16)])
    rules = {f.rule for f in color.check(scene, tokens)}
    assert rules == set(color.RULES)


def _scene_with(boxes=(), texts=(), connectors=(), polygons=(), paths=(),
                background: Optional[Box] = None) -> Scene:
    """Build a scene including the non-box content the colour rules read."""
    return Scene(1200, 675, tuple(boxes), tuple(texts), tuple(connectors),
                 tuple(polygons), "DejaVu Sans", tuple(paths), background)


def test_the_background_is_the_last_box_painted_over_the_point(
        tokens: DesignTokens) -> None:
    """SVG has no z-index: the element painted last is the one on top.

    Picking the smallest containing box instead gets this backwards whenever a
    small shape is painted *under* a larger one, and reports the contrast of a
    colour the viewer never sees.
    """
    under = replace(_box("under", "#1e3a5f", x=100, y=100, w=100, h=100),
                    paint_order=1)
    over = replace(_box("over", "#ffffff", x=0, y=0, w=600, h=400),
                   paint_order=2)
    scene = _scene(boxes=[under, over])
    assert color.background_at(150, 150, scene, tokens) == "#ffffff"


def test_the_canvas_fill_is_the_background_when_nothing_covers_the_point(
        tokens: DesignTokens) -> None:
    """A full-canvas divider is what the text on it is actually read against.

    The parser keeps the canvas rect out of `boxes` so it cannot trip layout
    rules. Dropping it from the colour rules too made every white heading on a
    navy section divider report a contrast error against white.
    """
    canvas = _box("bg", "#1e3a5f", x=0, y=0, w=1200, h=675)
    scene = _scene_with(background=canvas)
    assert color.background_at(600, 300, scene, tokens) == "#1e3a5f"


def test_white_text_on_a_full_canvas_divider_passes(
        tokens: DesignTokens) -> None:
    """The whole point of keeping the canvas fill."""
    canvas = _box("bg", "#1e3a5f", x=0, y=0, w=1200, h=675)
    scene = _scene_with(texts=[_text("t1", "#ffffff", size=32)],
                        background=canvas)
    assert color.check_text_contrast(scene, tokens) == []


def test_connector_and_polygon_and_path_colours_are_linted(
        tokens: DesignTokens) -> None:
    """Every painted thing on the slide has to answer to the palette.

    Only boxes and text were checked, so an off-palette arrow, arrowhead or
    pie wedge passed the gate untouched -- and a pie chart is nothing but
    `<path>` elements.
    """
    scene = _scene_with(
        connectors=[Connector("line#1", 0, 0, 10, 10, "#ff00ff", 2.0,
                              False, True, None)],
        polygons=[Polygon("polygon#2", ((0, 0), (5, 5), (0, 5)), "#00ff00",
                          None)],
        paths=[PathShape("path#3", "#0000ff", None, 0.0, None, None)])
    offenders = {f.element_id for f in color.check_token_colors(scene, tokens)}
    assert offenders == {"line#1", "polygon#2", "path#3"}


def test_a_tspan_fill_is_linted(tokens: DesignTokens) -> None:
    """A span can override its parent's fill, and often does."""
    run = replace(_text("t1", "#374151"), fills=("#374151", "#ff00ff"))
    findings = color.check_token_colors(_scene(texts=[run]), tokens)
    assert [f.element_id for f in findings] == ["t1"]
    assert "#ff00ff" in findings[0].message


def test_a_connector_below_the_graphic_floor_is_an_error(
        tokens: DesignTokens) -> None:
    """A connector is load-bearing: it says which node feeds which."""
    scene = _scene_with(
        connectors=[Connector("line#1", 0, 0, 10, 10, "#e2e8f0", 2.0,
                              False, True, None)])
    rules = {f.rule for f in color.check_graphic_contrast(scene, tokens)}
    assert rules == {"graphic-contrast"}
