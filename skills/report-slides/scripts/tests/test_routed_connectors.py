"""A routed connector's interior corners are not attachment points.

`diagram-patterns.md` tells the Architecture route to "route connectors around
unrelated groups", but the scene parser splits a routed polyline into one
segment per leg, and `check_dangling` then checked every segment endpoint. An
elbow's interior corners touch nothing by construction, so following the
instruction produced errors -- the pattern and the linter contradicted each
other, and the linter won.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from design_tokens import default_tokens
from visual_style.connectors import check_dangling
from visual_style.scene import parse_scene

_ELBOW = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
  <g data-pptx-role="group" data-node-id="a">
    <rect x="48" y="100" width="200" height="64" fill="#f8fafc" stroke="#475569"/>
  </g>
  <g data-pptx-role="group" data-node-id="b">
    <rect x="600" y="400" width="200" height="64" fill="#f8fafc" stroke="#475569"/>
  </g>
  <polyline points="248,132 424,132 424,432 600,432" fill="none" stroke="#475569"
            stroke-width="2" data-from="a" data-to="b" marker-end="url(#arrow)"/>
</svg>
"""


@pytest.fixture
def tokens():
    """The default token set."""
    return default_tokens()


def _findings(tmp_path: Path, svg: str, tokens):
    """Parse one SVG and run the dangling check over it."""
    path = tmp_path / "slide-01.svg"
    path.write_text(svg, encoding="utf-8")
    scene = parse_scene(path, "DejaVu Sans")
    return check_dangling(scene, tokens)


def test_an_elbow_between_two_nodes_is_not_dangling(tmp_path: Path, tokens) -> None:
    """Routing around an obstacle must not itself be an error."""
    assert _findings(tmp_path, _ELBOW, tokens) == []


def test_a_connector_that_truly_dangles_is_still_reported(tmp_path: Path, tokens) -> None:
    """The exemption covers interior corners only, never a loose end.

    Without this the previous fix would have silenced the check entirely, which
    is worse than the contradiction it resolved.
    """
    loose = _ELBOW.replace('data-from="a" data-to="b" ', "").replace(
        "600,432", "900,600"
    )
    findings = _findings(tmp_path, loose, tokens)
    assert findings, "a connector ending in empty space must still be reported"
    assert all(f.rule == "connector-dangling" for f in findings)


def test_a_straight_connector_between_nodes_still_passes(tmp_path: Path, tokens) -> None:
    """The single-segment case, unchanged by the exemption."""
    straight = _ELBOW.replace(
        '<polyline points="248,132 424,132 424,432 600,432"',
        '<polyline points="248,132 600,132"',
    ).replace('y="400"', 'y="100"')
    assert _findings(tmp_path, straight, tokens) == []
