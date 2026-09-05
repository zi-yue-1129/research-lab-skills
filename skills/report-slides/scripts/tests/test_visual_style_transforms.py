"""Tests for affine `transform` resolution.

The converter reads `translate`, `rotate`, `scale` and `matrix`. A linter that
refuses three of those blocks decks that convert perfectly well, and a linter
that silently ignores them measures a slide nobody is going to see. Both are
worse than composing the matrix and measuring the result.
"""

from __future__ import annotations

import math

import pytest

from visual_style.transforms import IDENTITY, parse_transform


def test_no_transform_is_the_identity() -> None:
    """An absent or empty attribute leaves coordinates alone."""
    assert parse_transform(None, "e1") == IDENTITY
    assert parse_transform("   ", "e1") == IDENTITY


def test_translate_moves_a_point() -> None:
    """The common case stays exactly as accurate as it was."""
    matrix = parse_transform("translate(40, 25)", "e1")
    assert matrix.apply(10.0, 10.0) == pytest.approx((50.0, 35.0))


def test_translate_accepts_exponent_notation() -> None:
    """`translate(1e2,0)` is a hundred units, not a silently dropped move.

    A digits-and-dots pattern matched nothing here and the translation was
    dropped without a word, so the element was measured a hundred units from
    where it is drawn and the gate reported the slide clean.
    """
    matrix = parse_transform("translate(1e2,0)", "e1")
    assert matrix.apply(0.0, 0.0) == pytest.approx((100.0, 0.0))


def test_scale_multiplies_both_axes() -> None:
    """One argument scales uniformly; two scale independently."""
    assert parse_transform("scale(2)", "e1").apply(3.0, 5.0) == pytest.approx(
        (6.0, 10.0))
    assert parse_transform("scale(2,0.5)", "e1").apply(
        3.0, 5.0) == pytest.approx((6.0, 2.5))


def test_rotate_turns_about_the_origin() -> None:
    """A quarter turn sends the x axis onto the y axis."""
    matrix = parse_transform("rotate(90)", "e1")
    assert matrix.apply(10.0, 0.0) == pytest.approx((0.0, 10.0), abs=1e-9)


def test_rotate_about_a_centre_leaves_that_centre_fixed() -> None:
    """The three-argument form pins its own centre."""
    matrix = parse_transform("rotate(37, 600, 337)", "e1")
    assert matrix.apply(600.0, 337.0) == pytest.approx((600.0, 337.0))


def test_matrix_is_taken_verbatim() -> None:
    """`matrix(a b c d e f)` is the affine it names."""
    matrix = parse_transform("matrix(1 0 0 1 30 -12)", "e1")
    assert matrix.apply(5.0, 5.0) == pytest.approx((35.0, -7.0))


def test_a_transform_list_composes_left_to_right() -> None:
    """SVG applies the leftmost function last, as in matrix multiplication.

    `translate(100,0) scale(2)` maps 5 to 110, not to 210: the point is scaled
    first and the result is then moved. Composing in the other order is a
    common and entirely silent error.
    """
    matrix = parse_transform("translate(100,0) scale(2)", "e1")
    assert matrix.apply(5.0, 0.0) == pytest.approx((110.0, 0.0))


def test_a_parent_transform_composes_with_its_child() -> None:
    """Nesting is composition, with the parent applied last."""
    parent = parse_transform("translate(100,100)", "g1")
    child = parse_transform("scale(3)", "e1")
    assert parent.compose(child).apply(2.0, 2.0) == pytest.approx(
        (106.0, 106.0))


def test_a_rotated_box_is_measured_by_its_axis_aligned_hull() -> None:
    """A rotated rectangle is reported by the box that contains it.

    That box is larger than the shape, deliberately. `safe-area` and
    `element-overlap` may over-report on a rotated element and start a
    conversation; measuring the untransformed coordinates instead reports a
    slide that is not the one being drawn.
    """
    matrix = parse_transform("rotate(45)", "e1")
    x, y, w, h = matrix.bounds(0.0, 0.0, 10.0, 10.0)
    half_diagonal = 10.0 * math.sqrt(2.0) / 2.0
    assert (x, y) == pytest.approx((-half_diagonal, 0.0))
    assert (w, h) == pytest.approx((2 * half_diagonal, 2 * half_diagonal))


def test_an_axis_aligned_box_is_measured_exactly() -> None:
    """Translation and scaling must not inflate anything."""
    matrix = parse_transform("translate(10,20) scale(2)", "e1")
    assert matrix.bounds(5.0, 5.0, 10.0, 10.0) == pytest.approx(
        (20.0, 30.0, 20.0, 20.0))


def test_the_scale_factor_is_the_root_of_the_determinant() -> None:
    """Font sizes travel through a transform by area, not by axis."""
    assert parse_transform("scale(2)", "e1").scale_factor() == pytest.approx(2.0)
    assert parse_transform("rotate(30)", "e1").scale_factor() == pytest.approx(
        1.0)


def test_an_unsupported_function_is_refused() -> None:
    """`skewX` is not something the converter draws; refuse rather than guess."""
    with pytest.raises(ValueError, match="skewX"):
        parse_transform("skewX(20)", "e1")


def test_unreadable_arguments_are_refused() -> None:
    """Anything left over after the numbers means the parse was wrong."""
    with pytest.raises(ValueError, match="cannot read"):
        parse_transform("translate(10 banana)", "e1")


def test_text_outside_a_call_is_refused() -> None:
    """A stray token means the attribute was not understood."""
    with pytest.raises(ValueError, match="cannot read"):
        parse_transform("translate(10,10) oops", "e1")


def test_the_wrong_number_of_arguments_is_refused() -> None:
    """`rotate` takes one or three arguments, never two."""
    with pytest.raises(ValueError, match="cannot read"):
        parse_transform("rotate(30, 600)", "e1")
