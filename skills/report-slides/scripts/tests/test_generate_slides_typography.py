"""Tests that the deterministic renderer typesets at presentation scale."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import generate_slides as gs
from design_tokens import TokenError

_SKILL_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"
_FONT_SIZE_RE = re.compile(r'font-size="([0-9.]+)"')


@pytest.fixture(autouse=True)
def _tokens_applied() -> None:
    """Apply the default token file before each test."""
    gs.apply_tokens(_DEFAULT_TOKENS)


def test_apply_tokens_populates_type_roles() -> None:
    """Type roles become available with presentation-scale sizes."""
    assert gs.t_size("slide_title") == 32
    assert gs.t_size("body") == 21
    assert gs.t_size("footnote") == 12
    assert gs.t_weight("slide_title") == 700


def test_apply_tokens_resolves_an_installed_font() -> None:
    """The resolved font family is one that is actually installed."""
    assert gs.S["font_resolved"]
    assert "sans-serif" not in gs.S["font_resolved"]


def test_frame_title_is_at_presentation_scale() -> None:
    """The slide title uses the slide_title role, not a 20pt literal."""
    markup = gs.frame("Experiment Overview", footer="deck 1/8")
    sizes = {float(m) for m in _FONT_SIZE_RE.findall(markup)}
    assert 32 in sizes
    assert 20 not in sizes


def test_frame_footer_is_not_below_the_footnote_floor() -> None:
    """No text in the frame falls below the footnote floor of 12."""
    markup = gs.frame("Experiment Overview", footer="deck 1/8")
    sizes = [float(m) for m in _FONT_SIZE_RE.findall(markup)]
    assert sizes
    assert min(sizes) >= 12


def test_frame_left_variant_is_not_centred() -> None:
    """The default frame variant left-aligns the title inside the safe area."""
    markup = gs.frame("Experiment Overview")
    assert 'text-anchor="middle"' not in markup
    assert 'x="48"' in markup


def test_frame_centered_variant_is_available() -> None:
    """A centred variant remains available for section dividers."""
    markup = gs.frame("Part II", variant="centered")
    assert 'text-anchor="middle"' in markup


def test_frame_rejects_unknown_variant() -> None:
    """An unknown frame variant raises rather than silently picking a default."""
    with pytest.raises(ValueError, match="unknown frame variant"):
        gs.frame("Experiment Overview", variant="diagonal")


def test_apply_tokens_defaults_to_shipped_contract() -> None:
    """Passing None loads the shipped default token file."""
    gs.apply_tokens(None)
    assert gs.t_size("body") == 21


def test_apply_tokens_raises_on_invalid_file(tmp_path: Path) -> None:
    """An invalid token file raises instead of leaving built-in defaults."""
    bad = tmp_path / "bad.tokens.yaml"
    bad.write_text(
        _DEFAULT_TOKENS.read_text(encoding="utf-8").replace("size: 21", "size: 9"),
        encoding="utf-8",
    )
    with pytest.raises(TokenError):
        gs.apply_tokens(bad)


def test_apply_style_raises_on_unparsable_frontmatter(tmp_path: Path) -> None:
    """A style file with no usable frontmatter is an error, not a no-op."""
    broken = tmp_path / "broken.md"
    broken.write_text("no frontmatter here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable YAML frontmatter") as excinfo:
        gs.apply_style(str(broken))
    assert "broken.md" in str(excinfo.value)


def test_wrap_to_width_respects_measured_width() -> None:
    """Wrapping breaks lines by measured width, not character count."""
    text = "Model architecture and evaluation protocol for the ablation study"
    narrow = gs.wrap_to_width(text, 300, "body")
    wide = gs.wrap_to_width(text, 900, "body")
    assert len(narrow) > len(wide)
    for line in narrow:
        assert gs.measured_width(line, "body") <= 300


def test_wrap_to_width_never_drops_words() -> None:
    """Every input word survives wrapping."""
    text = "alpha beta gamma delta epsilon zeta eta theta"
    joined = " ".join(gs.wrap_to_width(text, 200, "body"))
    assert joined.split() == text.split()


def test_wrap_to_width_keeps_overlong_word_on_its_own_line() -> None:
    """A single word wider than the budget is not silently dropped."""
    lines = gs.wrap_to_width("supercalifragilisticexpialidocious", 40, "body")
    assert lines == ["supercalifragilisticexpialidocious"]


def _sizes(markup: str) -> set:
    """Collect every font-size value present in SVG markup.

    Args:
        markup: SVG markup to scan.

    Returns:
        The distinct font-size values found.
    """
    return {float(m) for m in _FONT_SIZE_RE.findall(markup)}


def test_title_slide_uses_deck_title_role() -> None:
    """The title slide headline uses deck_title, not a 30pt literal."""
    markup = gs.render_title(
        {"title": "Ablation Study", "subtitle": "Round 3",
         "author": "Lab", "date": "2026-09-04"},
        {"footer": "1/8"},
    )
    sizes = _sizes(markup)
    assert 44 in sizes
    assert 30 not in sizes
    assert min(sizes) >= 12


def test_bullet_list_body_is_at_least_twenty() -> None:
    """Bullet body text sits at the body role, never at 14."""
    markup = gs.render_bullet_list(
        {"title": "Findings", "bullets": ["one finding", "another finding"]},
        {"footer": "2/8"},
    )
    sizes = _sizes(markup)
    assert 21 in sizes
    assert 14 not in sizes
    assert min(sizes) >= 12


def test_numbered_bullets_stay_inside_the_canvas() -> None:
    """Six numbered bullets still fit within the canvas height."""
    markup = gs.render_bullet_list(
        {"title": "Findings", "numbered": True,
         "bullets": [f"finding number {i}" for i in range(6)]},
        {},
    )
    ys = [float(m) for m in re.findall(r'<circle cx="[0-9.]+" cy="([0-9.]+)"', markup)]
    assert ys
    assert max(ys) <= gs.S["h"] - gs.S["safe"]["bottom"]


def test_conclusion_blocks_use_roles() -> None:
    """Conclusion headings and items use takeaway and body roles."""
    markup = gs.render_conclusion(
        {"title": "Conclusion", "conclusions": ["it worked"],
         "next_steps": ["scale it up"]},
        {},
    )
    sizes = _sizes(markup)
    assert 26 in sizes
    assert 21 in sizes
    assert 13 not in sizes


def test_chart_area_clears_the_title_rule() -> None:
    """The plot top sits below the frame rule, not at the old y=100."""
    left, right, top, bottom = gs.chart_area()
    rule_y = gs.S["safe"]["top"] + gs.t_size("slide_title") + 16
    assert top > rule_y
    assert bottom < gs.S["h"] - gs.S["safe"]["bottom"]
    assert right <= gs.S["w"] - gs.S["safe"]["right"]


def test_chart_area_left_margin_fits_axis_labels() -> None:
    """The left margin clears the widest tick label at the axis role."""
    left, _, _, _ = gs.chart_area()
    assert left >= gs.measured_width("100%", "axis") + gs.S["safe"]["left"] + 8


def test_bar_chart_axis_labels_are_at_least_sixteen() -> None:
    """Bar chart axis and category labels use the axis role."""
    markup = gs.render_bar_chart(
        {"index": 1, "title": "Throughput",
         "categories": ["1k", "4k", "8k", "16k"],
         "series": [{"label": "sparse", "values": [10, 40, 70, 95]},
                    {"label": "dense", "values": [30, 45, 50, 52]}],
         "y_max": 100, "note": "higher is better"},
        {"footer": "3/8"},
    )
    sizes = _sizes(markup)
    assert 16 in sizes
    assert 10 not in sizes
    assert min(sizes) >= 12


def test_line_chart_axis_labels_are_at_least_sixteen() -> None:
    """Line chart axis labels use the axis role."""
    markup = gs.render_line_chart(
        {"index": 2, "title": "Loss",
         "categories": ["e1", "e2", "e3"],
         "series": [{"label": "train", "values": [90, 50, 30]}],
         "y_max": 100},
        {},
    )
    sizes = _sizes(markup)
    assert 16 in sizes
    assert 10 not in sizes
    assert min(sizes) >= 12


def test_pie_chart_legend_is_at_least_sixteen() -> None:
    """Pie chart legend labels use the axis role."""
    markup = gs.render_pie_chart(
        {"index": 3, "title": "Budget",
         "categories": ["compute", "storage", "network"],
         "values": [60, 25, 15]},
        {},
    )
    sizes = _sizes(markup)
    assert 16 in sizes
    assert 13 not in sizes
    assert min(sizes) >= 12


def test_bar_chart_legend_entries_do_not_collide() -> None:
    """Legend entries are spaced by measured label width, not a fixed 230.

    The swatch dimensions come from the axis role rather than the plan's
    literal 16x12: the swatch scales with the label it sits beside, so a
    hard-coded size in the pattern would match nothing once the role changed.
    """
    markup = gs.render_bar_chart(
        {"index": 4, "title": "Comparison",
         "categories": ["a", "b"],
         "series": [
             {"label": "an extremely long series label that overruns", "values": [1, 2]},
             {"label": "second", "values": [3, 4]},
         ],
         "y_max": 10},
        {},
    )
    swatch = gs.t_size("axis") * 0.75
    xs = sorted(
        float(m) for m in re.findall(
            rf'<rect x="([0-9.]+)" y="[0-9.]+" '
            rf'width="{swatch:.1f}" height="{swatch:.1f}"',
            markup)
    )
    assert len(xs) == 2
    first_label = "an extremely long series label that overruns"
    assert xs[1] - xs[0] >= gs.measured_width(first_label, "axis") + 22


def test_bar_chart_note_sits_below_the_legend() -> None:
    """The chart note has its own row, so it cannot collide with a legend.

    The note used to share the legend's baseline at CB+51 and was right
    anchored, so a wide last legend entry ran straight into it.
    """
    markup = gs.render_bar_chart(
        {"index": 5, "title": "Comparison",
         "categories": ["a"],
         "series": [{"label": "one", "values": [1]}],
         "y_max": 10, "note": "higher is better"},
        {},
    )
    _, _, _, bottom = gs.chart_area()
    legend_y = bottom + gs.t_size("axis") * gs.t_lh("axis") + 16
    note_y = float(
        re.search(r'y="([0-9.]+)"[^>]*data-style-role="footnote"[^>]*>higher',
                  markup).group(1)
    )
    assert note_y > legend_y
    assert note_y <= gs.S["h"] - gs.S["safe"]["bottom"]


_TWO_SERIES = {
    "index": 6, "title": "Comparison",
    "categories": ["1k", "4k"],
    "series": [
        {"label": "sparse", "values": [10, 40]},
        {"label": "dense", "values": [30, 45]},
    ],
    "y_max": 100,
}


def test_bar_chart_series_get_distinct_colours() -> None:
    """Two series with no explicit colour must not render identically.

    Every series fell back to the same single colour, so a two-series bar
    chart drew both groups and both legend swatches in one ink. The chart was
    then unreadable, and the legend actively misleading -- it claimed to
    distinguish two things it rendered the same. The token file ships a chart
    palette precisely so this does not happen.
    """
    markup = gs.render_bar_chart(_TWO_SERIES, {})
    # Only the legend swatches: matching every <rect> would also catch the
    # frame's white background and pass for the wrong reason.
    swatch = gs.t_size("axis") * 0.75
    fills = re.findall(
        rf'<rect x="[0-9.]+" y="[0-9.]+" width="{swatch:.1f}" '
        rf'height="{swatch:.1f}" fill="(#[0-9a-fA-F]{{6}})"',
        markup,
    )
    assert len(fills) == 2
    assert len(set(fills)) == 2, f"all series share one colour: {set(fills)}"


def test_line_chart_series_get_distinct_colours() -> None:
    """Two line series with no explicit colour must not render identically."""
    markup = gs.render_line_chart(_TWO_SERIES, {})
    strokes = re.findall(r'<polyline [^>]*stroke="(#[0-9a-fA-F]{6})"', markup)
    assert len(strokes) == 2
    assert len(set(strokes)) == 2, f"both lines share one colour: {set(strokes)}"


def test_series_colours_come_from_the_token_palette() -> None:
    """The colours used are the token palette's, in order."""
    markup = gs.render_line_chart(_TWO_SERIES, {})
    strokes = re.findall(r'<polyline [^>]*stroke="(#[0-9a-fA-F]{6})"', markup)
    assert strokes == gs.S["chart_palette"][:2]


def test_an_explicit_series_colour_still_wins() -> None:
    """A series that names its own colour keeps it."""
    payload = {**_TWO_SERIES, "series": [
        {"label": "sparse", "values": [10, 40], "color": "#123456"},
        {"label": "dense", "values": [30, 45]},
    ]}
    markup = gs.render_line_chart(payload, {})
    strokes = re.findall(r'<polyline [^>]*stroke="(#[0-9a-fA-F]{6})"', markup)
    assert strokes[0] == "#123456"


def test_line_chart_labels_its_series() -> None:
    """A multi-series line chart must say which line is which.

    `chart_area` reserves a legend row in its bottom budget, but the line
    renderer never drew one, so two distinguishable lines were still
    unlabelled -- the reader could see there were two and not which was which.
    """
    markup = gs.render_line_chart(_TWO_SERIES, {})
    swatch = gs.t_size("axis") * 0.75
    fills = re.findall(
        rf'<rect x="[0-9.]+" y="[0-9.]+" width="{swatch:.1f}" '
        rf'height="{swatch:.1f}" fill="(#[0-9a-fA-F]{{6}})"',
        markup,
    )
    assert fills == gs.S["chart_palette"][:2]
    assert "sparse" in markup
    assert "dense" in markup
