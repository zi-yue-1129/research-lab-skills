"""Tests for the timeline renderer's vertical accounting.

The timeline is the only archetype that lays text out in both directions from a
central axis, so it is the only one whose capacity arithmetic can quietly claim
space that belongs to something else. Two things have to be true: the densest
layout it accepts must still leave the deck footer's band clear, and a block
must hang off the end of its own stem rather than float above it.

A review flagged `half_band` for measuring down to the safe area's own bottom
edge, below the footer, and predicted both failures. Neither reproduces: each
block's height ends in a full line advance rather than the last line's descent,
and that surplus is what keeps the footer clear and the block on its stem. The
invariants hold today with about three units to spare. These tests exist
because three units is not much of a margin for something nothing was checking
-- a change to `footnote` line height or to the footer role would consume it
silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

import generate_slides as gs
from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from fonts import resolve_font_stack
from visual_style.scene import Scene, parse_scene

_FOOTER = "Lab notes 2026-09-05"
_META = {"footer": _FOOTER}


@pytest.fixture(scope="module")
def family() -> str:
    """Resolve the family the renderer measures with."""
    tokens = DesignTokens.load(DEFAULT_TOKENS_PATH)
    return resolve_font_stack(tokens.font_stack("sans"))


def _timeline(detail: str, count: int = 3) -> Dict[str, Any]:
    """Build a timeline slide spec whose events share one detail string."""
    return {
        "index": 1, "type": "timeline", "title": "Delivery",
        "events": [{"label": f"Stage {i}", "date": "2026-09-01",
                    "detail": detail} for i in range(count)],
    }


def _render(slide: Dict[str, Any], tmp_path: Path, family: str) -> Scene:
    """Render a slide spec and parse the result into a scene."""
    gs.apply_tokens(DEFAULT_TOKENS_PATH)
    path = tmp_path / "timeline.svg"
    path.write_text(gs.generate_slide(slide, _META), encoding="utf-8")
    return parse_scene(path, family)


def _densest_accepted(tmp_path: Path, family: str) -> Scene:
    """Return the densest timeline this renderer will still lay out.

    Capacity is what the arithmetic under test decides, so the test has to
    find it rather than assume it: it grows the detail text one word at a time
    until `SlideCapacityError` is raised, and measures the last slide that was
    accepted.
    """
    gs.apply_tokens(DEFAULT_TOKENS_PATH)
    accepted: List[str] = []
    words: List[str] = []
    for _ in range(60):
        words.append("measurement")
        try:
            markup = gs.generate_slide(_timeline(" ".join(words)), _META)
        except gs.SlideCapacityError:
            break
        accepted.append(markup)
    assert accepted, "no timeline was accepted at all"
    path = tmp_path / "densest.svg"
    path.write_text(accepted[-1], encoding="utf-8")
    return parse_scene(path, family)


def test_the_densest_accepted_timeline_still_clears_the_footer(
        tmp_path: Path, family: str) -> None:
    """No accepted layout may put text into the band the footer occupies.

    `half_band` measures down to the safe area's own bottom edge, which is
    below the footer, so the arithmetic does claim that band. It gets away
    with it because every block's height ends in a full line advance while
    the ink ends at the last line's descent, and that surplus is larger than
    the footer band. The margin measured here is about three units.
    """
    scene = _densest_accepted(tmp_path, family)
    footer = next(run for run in scene.texts if run.text == _FOOTER)
    lowest = max(run.bbox().bottom for run in scene.texts
                 if run.element_id != footer.element_id)
    assert lowest <= footer.bbox().y + 0.5


def test_a_block_above_the_axis_hangs_from_its_own_stem(
        tmp_path: Path, family: str) -> None:
    """The last line of an upward block ends where its stem ends.

    An upward block is positioned by subtracting its height from the stem end,
    so any error in that height shows up as a visible gap between a stem and
    the label it carries. There is none: the block lands on its stem within a
    unit, and this pins it there.
    """
    scene = _render(_timeline("one detail line"), tmp_path, family)
    above = [run for run in scene.texts if run.node_id == "event-0"]
    assert above, "the first event should be laid out above the axis"
    lowest = max(run.bbox().bottom for run in above)
    # The stem is a plain `<line>` with no marker and no `data-from`, so it is
    # not a connector; it is measured from the dot it grows out of.
    dot = next(box for box in scene.boxes
               if box.node_id == "event-0" and box.tag == "circle")
    stem_end = dot.y - gs.S["spacing"][4]
    assert lowest == pytest.approx(stem_end, abs=1.0)
