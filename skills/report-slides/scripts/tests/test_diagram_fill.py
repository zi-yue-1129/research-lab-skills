"""A page is enlarged to fill its canvas, and each page is fitted on its own.

The token sizes are floors, not fixed values. A composition with three boxes on
it was drawn at exactly the same size as one with forty, which left the three
sitting in a small island surrounded by white -- correct by every gate and
useless as a figure. These tests fix the two properties that make the scaling
safe to have: it never goes below the floors, and it never trades legibility of
one page for the density of another sharing the deck.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from diagram_builder import Diagram  # noqa: E402

TOKENS_DIR = SCRIPTS.parent / "references" / "tokens"


@pytest.fixture
def figure_tokens() -> dict:
    """The shipped figure token set, whose canvas has room to grow into."""
    return yaml.safe_load(
        (TOKENS_DIR / "figure.tokens.yaml").read_text(encoding="utf-8")
    )


@pytest.fixture
def slide_tokens() -> dict:
    """The shipped slide token set."""
    return yaml.safe_load(
        (TOKENS_DIR / "default.tokens.yaml").read_text(encoding="utf-8")
    )


def _sparse(tokens: dict) -> Diagram:
    """Compose three boxes -- far less than the canvas holds.

    Args:
        tokens: The token set to compose against.

    Returns:
        The composed diagram, not yet laid out.
    """
    d = Diagram(tokens, title="Sparse", subtitle="three boxes", footnote="a note")
    s = d.section("p", "Pipeline", flow="row")
    a = d.node(s, "a", ["Input"], shape="(B, L)", kind="data")
    b = d.node(s, "b", ["Model"], shape="(B, d)")
    c = d.node(s, "c", ["Output"], shape="(B, C)", kind="data")
    d.connect(a, b)
    d.connect(b, c)
    return d


def _dense(tokens: dict, sections: int = 8, per_section: int = 6) -> Diagram:
    """Compose enough blocks to leave a canvas with nothing spare.

    Args:
        tokens: The token set to compose against.
        sections: How many sections to add.
        per_section: How many nodes in each.

    Returns:
        The composed diagram, not yet laid out.
    """
    d = Diagram(tokens, title="Dense", subtitle="many blocks", footnote="a note")
    for i in range(sections):
        section = d.section(f"s{i}", f"{i}. Stage", flow="row")
        for j in range(per_section):
            d.node(section, f"n{j}", [f"Component {j}", "a line of detail"],
                   shape="(B, L, d)")
    return d


def test_a_sparse_page_is_enlarged(figure_tokens: dict) -> None:
    """Three boxes on a figure canvas grow past the token sizes."""
    d = _sparse(figure_tokens)
    d.layout()

    floor = figure_tokens["typography"]["roles"]["node_label"]["size"]
    assert d.slide_fill[0] > 1.0
    assert d.label_size > floor


def test_a_full_page_barely_grows(figure_tokens: dict) -> None:
    """A page with nothing spare is left near the token sizes.

    Near, not exactly at: sizes are snapped onto the layout grid, so a full
    page usually has a few units of slack that the search will take. What
    matters is the contrast with a page that is genuinely empty, which grows
    until it hits the cap.
    """
    full = _dense(figure_tokens)
    full.layout()
    sparse = _sparse(figure_tokens)
    sparse.layout()

    assert full.slide_fill[0] < 1.25
    assert sparse.slide_fill[0] > 2.0


def test_scaling_never_goes_below_the_floors(figure_tokens: dict) -> None:
    """Whatever the composition, type never drops under its declared size.

    Shrinking to fit would be the easy answer to an over-full page and the
    wrong one: the floors are what makes a deck readable at the back of a room.
    Overflow pages instead.
    """
    for diagram in (_sparse(figure_tokens), _dense(figure_tokens, sections=20)):
        diagram.layout()
        assert min(diagram.slide_fill) >= 1.0
        assert diagram.label_size >= (
            figure_tokens["typography"]["roles"]["node_label"]["size"]
        )


def test_each_page_is_fitted_on_its_own(slide_tokens: dict) -> None:
    """A crowded page does not hold a sparse one down to its own scale.

    This is the whole reason the factor is per page. A deck built from one
    dense section and one small one used to draw both at the dense page's
    scale, so the small page came out as an island in the middle of an empty
    slide.
    """
    d = Diagram(slide_tokens, title="Mixed", subtitle="one full, one not")
    for i in range(4):
        crowded = d.section(f"s{i}", f"{i}. Crowded", flow="row")
        for j in range(4):
            d.node(crowded, f"n{j}", [f"Component {j}", "a line of detail"],
                   shape="(B, L, d)")
    small = d.section("small", "Small", flow="row")
    d.node(small, "one", ["Only this"], shape="(B, d)")
    d.layout()

    assert len(d.slides) > 1, "the fixture must page for this test to mean anything"
    assert d.slide_fill[-1] > d.slide_fill[0]


def test_the_leftover_space_is_split_around_the_content(figure_tokens: dict) -> None:
    """Space the scaling could not take is centred, not left at the bottom."""
    d = _sparse(figure_tokens)
    d.layout()

    sections = [s for band in d.slides[0] for s in band]
    top = min(s.y for s in sections)
    bottom = max(s.y + s.height for s in sections)
    room_above = top - d._content_top()
    room_below = d.canvas_h - d.safe["bottom"] - 24 - bottom
    assert abs(room_above - room_below) <= d.grid


def test_page_chrome_keeps_the_token_size(figure_tokens: dict) -> None:
    """The subtitle and footnote do not scale with the page's content.

    Both sit on baselines fixed against the safe area, so growing them pushed
    the footnote's descenders outside it -- caught by the style gate, and the
    reason they are drawn at the token size whatever the page's scale.
    """
    d = _sparse(figure_tokens)
    d.layout()
    svg = d.to_svg(0)

    caption = figure_tokens["typography"]["roles"]["caption"]["size"]
    assert d.slide_fill[0] > 1.0, "the fixture must scale for this test to bite"
    assert f'font-size="{caption}" fill="#64748b">a note</text>' in svg


def test_an_arc_clears_the_tallest_node_it_passes(figure_tokens: dict) -> None:
    """A residual arc is routed above everything under it, not just its ends.

    The tall box usually sits between the two ends -- a scaled dot-product
    block between a LayerNorm and its adder -- and a lane measured from the
    endpoints alone was drawn straight through it.
    """
    d = Diagram(figure_tokens, title="Residual", subtitle="one skip path")
    s = d.section("b", "Block", flow="row")
    start = d.node(s, "ln", ["LayerNorm"], shape="(B, L, d)")
    tall = d.node(s, "tall", ["Scaled dot-product", "causal mask", "dropout 0.1"],
                  shape="(B, H, L, L)")
    add = d.op(s, "add", "+")
    d.connect(start, tall)
    d.connect(tall, add)
    d.connect(start, add, route="over")
    d.layout()

    lane_conn = next(c for c in d.connections if c["route"] == "over")
    points = d._route(lane_conn)
    lane = min(y for _, y in points)
    clearance = int(figure_tokens["spacing"]["connector_clearance_min"])
    assert tall.y - lane >= clearance
