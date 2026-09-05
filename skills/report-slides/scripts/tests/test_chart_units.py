"""Tests that chart axis and value labels carry the series' own unit.

`render_bar_chart` and `render_line_chart` appended a literal `%` to every
tick and every value label, so a throughput series of 340 requests/s was
labelled `340.0%`. A percentage suffix on non-percentage data is not a styling
choice; it states something false about the numbers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import generate_slides as gs

_SKILL_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"

_AXIS_TICK_RE = re.compile(
    r'data-style-role="axis"[^>]*text-anchor="end">([^<]*)</text>')
_VALUE_LABEL_RE = re.compile(
    r'data-style-role="footnote"[^>]*text-anchor="middle">([^<]*)</text>')

_META = {"footer": "deck 1/1"}


@pytest.fixture(autouse=True)
def _tokens_applied() -> None:
    """Apply the default token file before each test."""
    gs.apply_tokens(_DEFAULT_TOKENS)


def _throughput_slide(chart_type: str, **extra: object) -> dict:
    """Return a chart slide whose numbers are not percentages.

    Args:
        chart_type: Either `bar_chart` or `line_chart`.
        **extra: Additional slide keys, such as `unit`.

    Returns:
        A slide dict for the renderer.
    """
    slide = {
        "index": 2,
        "type": chart_type,
        "title": "Sustained throughput",
        "categories": ["p50", "p99"],
        "series": [{"label": "after", "color": "#059669",
                    "values": [340.0, 210.0]}],
        "y_max": 400,
    }
    slide.update(extra)
    return slide


@pytest.mark.parametrize("renderer,chart_type", [
    (gs.render_bar_chart, "bar_chart"),
    (gs.render_line_chart, "line_chart"),
])
def test_axis_ticks_carry_no_unit_by_default(renderer: object,
                                             chart_type: str) -> None:
    """A chart that declares no unit gets bare numbers.

    A bare number is never wrong. `%` on a request rate is.
    """
    markup = renderer(_throughput_slide(chart_type), _META)
    ticks = _AXIS_TICK_RE.findall(markup)
    assert ticks == ["0", "80", "160", "240", "320", "400"]


@pytest.mark.parametrize("renderer,chart_type", [
    (gs.render_bar_chart, "bar_chart"),
    (gs.render_line_chart, "line_chart"),
])
def test_axis_ticks_use_the_declared_unit(renderer: object,
                                          chart_type: str) -> None:
    """A percentage deck keeps its `%` by declaring it."""
    markup = renderer(_throughput_slide(chart_type, unit="%"), _META)
    ticks = _AXIS_TICK_RE.findall(markup)
    assert ticks == ["0%", "80%", "160%", "240%", "320%", "400%"]


def test_bar_value_labels_carry_no_unit_by_default() -> None:
    """The number above a bar is the value, not a percentage of anything."""
    markup = gs.render_bar_chart(_throughput_slide("bar_chart"), _META)
    assert "340.0" in _VALUE_LABEL_RE.findall(markup)
    assert "340.0%" not in markup


def test_bar_value_labels_use_the_declared_unit() -> None:
    """A declared unit reaches the value labels as well as the axis."""
    markup = gs.render_bar_chart(_throughput_slide("bar_chart", unit="%"), _META)
    assert "340.0%" in _VALUE_LABEL_RE.findall(markup)


def test_a_multi_character_unit_is_kept_whole() -> None:
    """A unit is a string, not a single symbol."""
    markup = gs.render_bar_chart(
        _throughput_slide("bar_chart", unit=" req/s"), _META)
    assert _AXIS_TICK_RE.findall(markup)[-1] == "400 req/s"


def test_the_y_gutter_is_measured_from_the_widest_tick() -> None:
    """The plot area clears the labels actually drawn beside it.

    The gutter was measured from a hardcoded `100%`, so a wide unit ran its
    ticks into the slide's left margin.
    """
    narrow_left, _, _, _ = gs.chart_area("400")
    wide_left, _, _, _ = gs.chart_area("400 req/s")
    assert wide_left > narrow_left


def test_a_wide_unit_widens_the_rendered_plot_gutter() -> None:
    """The renderer passes its own ticks to the plot-area calculation."""
    bare = gs.render_bar_chart(_throughput_slide("bar_chart"), _META)
    wide = gs.render_bar_chart(
        _throughput_slide("bar_chart", unit=" requests/second"), _META)
    assert _plot_left(wide) > _plot_left(bare)


_LINE_RE = re.compile(
    r'<line x1="([0-9.]+)" y1="([0-9.]+)" x2="([0-9.]+)" y2="([0-9.]+)"')


def _plot_left(markup: str) -> float:
    """Return the x of the chart's vertical axis.

    Args:
        markup: Rendered slide SVG.

    Returns:
        The x shared by both ends of the only vertical rule in the chart.
    """
    verticals = [float(x1) for x1, y1, x2, y2 in _LINE_RE.findall(markup)
                 if x1 == x2 and y1 != y2]
    assert verticals, "no vertical axis in the rendered chart"
    return min(verticals)


def _qwk_slide(**extra: object) -> dict:
    """Return a chart slide on a 0-1 axis, as the example deck plots QWK.

    Args:
        **extra: Additional slide keys.

    Returns:
        A slide dict for the renderer.
    """
    slide = {
        "index": 2,
        "type": "bar_chart",
        "title": "Cross-lingual QWK",
        "categories": ["zero-shot", "fine-tuned"],
        "series": [{"label": "zh-TW", "color": "#059669",
                    "values": [0.541, 0.853]}],
        "y_max": 1.0,
    }
    slide.update(extra)
    return slide


def test_a_sub_unit_axis_gets_decimal_ticks() -> None:
    """Six ticks on a 0-1 axis must be six different numbers.

    At `{val:.0f}` they read 0, 0, 0, 1, 1, 1: three pairs of identical labels
    against six different grid lines.
    """
    markup = gs.render_bar_chart(_qwk_slide(), _META)
    ticks = _AXIS_TICK_RE.findall(markup)
    assert ticks == ["0.0", "0.2", "0.4", "0.6", "0.8", "1.0"]


def test_value_labels_keep_one_place_beyond_the_axis() -> None:
    """A bar's label resolves finer than the axis it is measured against.

    At `{val:.1f}` a QWK of 0.853 was labelled 0.9.
    """
    markup = gs.render_bar_chart(_qwk_slide(), _META)
    assert "0.85" in _VALUE_LABEL_RE.findall(markup)


def test_a_percentage_axis_keeps_whole_number_ticks() -> None:
    """The common 0-100 axis is unchanged: whole ticks, one decimal on bars."""
    slide = _throughput_slide("bar_chart", unit="%")
    slide["y_max"] = 100
    slide["series"] = [{"label": "after", "values": [98.4, 100.0]}]
    markup = gs.render_bar_chart(slide, _META)
    assert _AXIS_TICK_RE.findall(markup) == [
        "0%", "20%", "40%", "60%", "80%", "100%"]
    assert "98.4%" in _VALUE_LABEL_RE.findall(markup)


_LINE_Y_RE = re.compile(r'<line [^>]*y1="([-\d.]+)"')


def _lowest_gridline(markup: str) -> float:
    """Return the lowest horizontal rule in a rendered chart.

    Args:
        markup: The rendered SVG.

    Returns:
        The largest `y1` of any `<line>`, which is the plot's baseline axis.
    """
    return max(float(value) for value in _LINE_Y_RE.findall(markup))


def test_chart_area_only_reserves_the_footer_band_when_there_is_a_footer(
) -> None:
    """A deck with no footer gets that band back.

    `chart_area()` subtracted `footer_band_height()` unconditionally, so a
    slide with no footer shrank its plot to clear a row nothing occupies. The
    reservation follows the footer.
    """
    gs.apply_tokens(_DEFAULT_TOKENS)
    _, _, _, with_footer = gs.chart_area(has_footer=True)
    _, _, _, without_footer = gs.chart_area(has_footer=False)
    assert without_footer - with_footer == pytest.approx(
        gs.footer_band_height())


def test_a_chart_with_no_footer_draws_a_taller_plot() -> None:
    """The renderers pass what they know: whether a footer was asked for.

    Without this the argument would exist and never be used, which is a worse
    state than not having it: the code would claim to reserve conditionally
    while reserving unconditionally.
    """
    gs.apply_tokens(_DEFAULT_TOKENS)
    slide = {"index": 1, "type": "bar_chart", "title": "Accuracy",
             "categories": ["Dev"], "y_max": 100, "unit": "%",
             "series": [{"label": "run", "color": "#047857",
                         "values": [80.0]}]}
    footed = _lowest_gridline(gs.generate_slide(slide, {"footer": "Notes"}))
    bare = _lowest_gridline(gs.generate_slide(slide, {}))
    assert bare > footed
