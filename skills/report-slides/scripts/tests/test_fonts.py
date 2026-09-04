"""Tests for font stack resolution and text metrics."""

from __future__ import annotations

import shutil

import pytest

from fonts import (
    FontError,
    font_file_for,
    is_family_available,
    parse_font_stack,
    resolve_font_stack,
    text_width,
    vertical_metrics,
)

# Requires fontconfig; the whole module is meaningless without it.
pytestmark = pytest.mark.skipif(
    shutil.which("fc-match") is None,
    reason="fontconfig (fc-match) is not installed",
)


def test_parse_font_stack_preserves_multi_word_families() -> None:
    """Multi-word quoted families survive parsing intact."""
    stack = parse_font_stack("'Helvetica Neue', Arial, sans-serif")
    assert stack == ["Helvetica Neue", "Arial", "sans-serif"]


def test_parse_font_stack_handles_double_quotes_and_spacing() -> None:
    """Double-quoted names and irregular spacing parse correctly."""
    stack = parse_font_stack('Inter ,  "DejaVu Sans Mono" , monospace')
    assert stack == ["Inter", "DejaVu Sans Mono", "monospace"]


def test_dejavu_sans_is_available() -> None:
    """DejaVu Sans ships with essentially every Linux image."""
    assert is_family_available("DejaVu Sans") is True


def test_absent_family_is_not_available() -> None:
    """A nonsense family name is reported unavailable, not silently substituted."""
    assert is_family_available("Totally Not A Real Font 9x7") is False


def test_resolve_skips_uninstalled_first_choice() -> None:
    """Resolution returns the first installed family, not the first listed."""
    resolved = resolve_font_stack(
        "Totally Not A Real Font 9x7, 'DejaVu Sans', sans-serif"
    )
    assert resolved == "DejaVu Sans"


def test_resolve_raises_when_nothing_is_installed() -> None:
    """A stack with no installed family raises instead of guessing."""
    with pytest.raises(FontError) as excinfo:
        resolve_font_stack("Nope One 9x7, 'Nope Two 9x7'")
    assert "Nope One 9x7" in str(excinfo.value)


def test_generic_keyword_alone_raises() -> None:
    """A stack of only CSS generic keywords cannot be resolved to a face."""
    with pytest.raises(FontError):
        resolve_font_stack("sans-serif")


def test_text_width_scales_with_size_and_length() -> None:
    """Measured width grows with both font size and string length."""
    narrow = text_width("Model", "DejaVu Sans", 18)
    wide = text_width("Model", "DejaVu Sans", 36)
    longer = text_width("Model architecture", "DejaVu Sans", 18)
    assert wide > narrow > 0
    assert longer > narrow
    assert 1.8 < wide / narrow < 2.2


def test_bold_is_measured_with_the_bold_face() -> None:
    """A weight that selects a different face must measure differently.

    `text_width` accepted a `weight` argument and threw it away, so every one of
    the four token roles at weight 600 or 700 -- `deck_title`, `slide_title`,
    `takeaway`, `node_label` -- was measured with the regular face. On this
    machine that under-measures by 12.9%, which is roughly one character in
    eight: enough to decide whether a title fits on two lines.

    The assertion is an inequality rather than a number because face metrics are
    a property of the installed font, not of this code.
    """
    family = resolve_font_stack("DejaVu Sans, sans-serif")
    text = "Token contract and enforcement"
    regular = text_width(text, family, 32, weight=400)
    bold = text_width(text, family, 32, weight=700)
    assert bold > regular, (
        f"weight is being ignored: {family} measures {bold} at 700 and "
        f"{regular} at 400"
    )


def test_a_weight_between_the_css_steps_still_resolves() -> None:
    """An unusual but schema-legal weight rounds rather than raising."""
    family = resolve_font_stack("DejaVu Sans, sans-serif")
    assert font_file_for(family, 650) == font_file_for(family, 700)


def test_vertical_metrics_are_measured_not_assumed() -> None:
    """Ascent is near a full em and descent is non-zero, unlike the 0.8/0 guess.

    The exact values are DejaVu Sans on the reference image; assert them so a
    font update that shifts every text extent is noticed, not absorbed.
    """
    assert vertical_metrics("DejaVu Sans", 32) == (30.0, 8.0)
    assert vertical_metrics("DejaVu Sans", 12) == (12.0, 3.0)


def test_vertical_metrics_scale_with_size() -> None:
    """A larger size reserves more space above and below the baseline."""
    small_ascent, small_descent = vertical_metrics("DejaVu Sans", 12)
    large_ascent, large_descent = vertical_metrics("DejaVu Sans", 36)
    assert large_ascent > small_ascent
    assert large_descent > small_descent


def test_vertical_metrics_reject_unavailable_family() -> None:
    """An uninstalled family is an error, not a silently substituted face."""
    with pytest.raises(FontError):
        vertical_metrics("Nonexistent Face 12345", 20)


def test_text_width_rejects_unavailable_family() -> None:
    """Measuring with an uninstalled family raises rather than approximating."""
    with pytest.raises(FontError):
        text_width("Model", "Totally Not A Real Font 9x7", 18)
