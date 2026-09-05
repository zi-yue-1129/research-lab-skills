"""Tests for `<path>` bounding-box extraction.

A pie chart is nothing but `<path>`, and without geometry here the linter
reports a clean gate for paths it never measured -- while the human reviewer
has been told those properties are already settled. The bound must be a
superset: over-reporting is a conversation, under-reporting is a defect that
ships.
"""

from __future__ import annotations

import math

import pytest

from visual_style.paths import path_bounds


def test_a_straight_path_is_bounded_exactly() -> None:
    """Lines, horizontals and verticals give the rectangle they draw."""
    assert path_bounds("M8 8 H1192 V667 H8Z") == (8.0, 8.0, 1184.0, 659.0)


def test_relative_commands_accumulate() -> None:
    """Lowercase commands are offsets from the current point."""
    assert path_bounds("M10 10 l20 0 l0 30 z") == (10.0, 10.0, 20.0, 30.0)


def test_a_repeated_moveto_argument_list_is_a_lineto() -> None:
    """`M` followed by extra pairs draws lines, it does not move."""
    assert path_bounds("M0 0 10 10 20 5") == (0.0, 0.0, 20.0, 10.0)


def test_a_curve_is_bounded_by_its_control_points() -> None:
    """A Bezier lies inside the hull of its control points, never outside."""
    x, y, w, h = path_bounds("M0 0 C0 -40 100 -40 100 0")
    assert (x, y) == (0.0, -40.0)
    assert (w, h) == (100.0, 40.0)


def test_a_pie_wedge_includes_the_bulge_of_its_arc() -> None:
    """The arc bulges past the chord, and the box has to contain the bulge.

    A quarter wedge of radius 100 centred at the origin runs from (100, 0) to
    (0, 100). Bounding only the endpoints gives a 100x100 box that clips the
    entire curved edge; the arc itself reaches x=100 and y=100, so the box is
    the same here -- what matters is the half-circle below, which reaches
    y=100 at a point that is neither endpoint.
    """
    x, y, w, h = path_bounds("M-100,0 A100,100 0 0,1 100,0 Z")
    assert (x, y) == pytest.approx((-100.0, -100.0))
    assert (w, h) == pytest.approx((200.0, 100.0))


def test_an_arc_that_sweeps_no_extreme_is_bounded_by_its_endpoints() -> None:
    """A short arc must not be inflated to the whole circle."""
    start = (100.0 * math.cos(math.radians(10)),
             100.0 * math.sin(math.radians(10)))
    end = (100.0 * math.cos(math.radians(40)),
           100.0 * math.sin(math.radians(40)))
    x, y, w, h = path_bounds(
        f"M{start[0]},{start[1]} A100,100 0 0,1 {end[0]},{end[1]}")
    assert x == pytest.approx(min(start[0], end[0]))
    assert x + w == pytest.approx(max(start[0], end[0]), abs=1.0)


def test_an_empty_path_has_no_bounds() -> None:
    """Nothing drawn is not a zero-sized box at the origin."""
    assert path_bounds("") is None


def test_unreadable_path_data_is_refused() -> None:
    """Anything the parser cannot read raises rather than measuring wrongly."""
    with pytest.raises(ValueError, match="unreadable"):
        path_bounds("M10 10 L20 banana")


def test_an_unsupported_command_is_refused() -> None:
    """A command outside the SVG set is an error, not a silent skip."""
    with pytest.raises(ValueError, match="unreadable"):
        path_bounds("M0 0 X10 10")
