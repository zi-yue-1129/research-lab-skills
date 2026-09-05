"""Tests for the connector rules."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

import pytest

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from visual_style import connectors
from visual_style.scene import Box, Connector, Polygon, Scene


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _box(node_id: str, x: float, y: float, w: float = 200,
         h: float = 90) -> Box:
    """Build a node box for rule testing."""
    return Box(f"rect-{node_id}", "rect", x, y, w, h, "#f8fafc", "#475569",
               1.5, 8, "node.primary", node_id, False)


def _conn(element_id: str, x1: float, y1: float, x2: float, y2: float,
          from_node: Optional[str] = None, to_node: Optional[str] = None,
          has_tail: bool = True) -> Connector:
    """Build a connector for rule testing."""
    return Connector(element_id, x1, y1, x2, y2, "#475569", 2.0, False,
                     has_tail, None, from_node, to_node)


def _scene(boxes=(), conns=(), polys=()) -> Scene:
    """Build a scene from boxes, connectors, and polygons."""
    return Scene(1200, 675, tuple(boxes), (), tuple(conns), tuple(polys),
                 "DejaVu Sans")


_A = _box("n1", 100, 100)
_B = _box("n2", 500, 100)


def test_edge_distance_is_zero_on_the_boundary() -> None:
    """A point on an edge is at distance zero."""
    assert connectors.edge_distance(300, 145, _A) == pytest.approx(0.0)


def test_edge_distance_measures_inward_and_outward() -> None:
    """Inside and outside points both measure to the nearest edge."""
    assert connectors.edge_distance(310, 145, _A) == pytest.approx(10.0)
    assert connectors.edge_distance(290, 145, _A) == pytest.approx(10.0)


def test_connector_attached_at_both_ends_is_clean(tokens: DesignTokens) -> None:
    """A connector touching both node boundaries is well formed."""
    scene = _scene(boxes=[_A, _B], conns=[_conn("c1", 300, 145, 500, 145)])
    assert connectors.check_dangling(scene, tokens) == []


def test_connector_touching_nothing_is_dangling(tokens: DesignTokens) -> None:
    """An endpoint in empty space is a dangling connector."""
    scene = _scene(boxes=[_A, _B], conns=[_conn("c1", 300, 145, 420, 400)])
    findings = connectors.check_dangling(scene, tokens)
    assert [f.rule for f in findings] == ["connector-dangling"]
    assert "end" in findings[0].message


def test_declared_node_that_does_not_exist_is_dangling(
    tokens: DesignTokens,
) -> None:
    """A connector naming an absent node cannot be resolved."""
    scene = _scene(boxes=[_A], conns=[_conn("c1", 300, 145, 500, 145,
                                            from_node="n1", to_node="n9")])
    findings = connectors.check_dangling(scene, tokens)
    assert [f.rule for f in findings] == ["connector-dangling"]
    assert "n9" in findings[0].message


def test_endpoint_on_its_declared_port_is_clean(tokens: DesignTokens) -> None:
    """An endpoint on the declared node's boundary does not drift."""
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 300, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    assert connectors.check_port_drift(scene, tokens) == []


def test_endpoint_far_from_its_declared_port_is_an_error(
    tokens: DesignTokens,
) -> None:
    """ATTACH_TOLERANCE is 4; a 12-unit drift fails."""
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 312, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    findings = connectors.check_port_drift(scene, tokens)
    assert [f.rule for f in findings] == ["connector-port-drift"]
    assert "12" in findings[0].message


def test_connector_crossing_an_unrelated_node_is_an_error(
    tokens: DesignTokens,
) -> None:
    """A line ploughing through a third node is a routing defect."""
    middle = _box("n3", 330, 120, 100, 50)
    scene = _scene(boxes=[_A, _B, middle],
                   conns=[_conn("c1", 300, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    findings = connectors.check_through_node(scene, tokens)
    assert [f.rule for f in findings] == ["connector-through-node"]
    assert "n3" in findings[0].message


def test_connector_entering_its_own_endpoints_is_not_a_defect(
    tokens: DesignTokens,
) -> None:
    """A connector may touch the nodes it joins."""
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 290, 145, 510, 145,
                                from_node="n1", to_node="n2")])
    assert connectors.check_through_node(scene, tokens) == []


def test_connector_too_close_to_an_unrelated_node_is_an_error(
    tokens: DesignTokens,
) -> None:
    """Default connector_clearance_min is 12; a 6-unit pass fails."""
    below = _box("n3", 330, 151, 100, 50)
    scene = _scene(boxes=[_A, _B, below],
                   conns=[_conn("c1", 300, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    findings = connectors.check_clearance(scene, tokens)
    assert [f.rule for f in findings] == ["connector-clearance"]
    assert "12" in findings[0].message


def test_sufficient_clearance_is_clean(tokens: DesignTokens) -> None:
    """A node 20 units clear of the line passes."""
    below = _box("n3", 330, 165, 100, 50)
    scene = _scene(boxes=[_A, _B, below],
                   conns=[_conn("c1", 300, 145, 500, 145,
                                from_node="n1", to_node="n2")])
    assert connectors.check_clearance(scene, tokens) == []


def test_triangle_near_a_connector_endpoint_is_an_error(
    tokens: DesignTokens,
) -> None:
    """A polygon arrowhead is the workaround this rule exists to stop."""
    head = Polygon("p1", ((500, 145), (488, 139), (488, 151)), "#475569", None)
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 300, 145, 500, 145, has_tail=False)],
                   polys=[head])
    findings = connectors.check_hand_drawn_arrows(scene, tokens)
    assert [f.rule for f in findings] == ["hand-drawn-arrow"]
    assert "marker-end" in findings[0].message


def test_triangle_far_from_any_connector_is_allowed(
    tokens: DesignTokens,
) -> None:
    """A triangle used as a chart glyph is not an arrowhead."""
    glyph = Polygon("p1", ((900, 500), (880, 540), (920, 540)), "#475569", None)
    scene = _scene(boxes=[_A, _B],
                   conns=[_conn("c1", 300, 145, 500, 145)], polys=[glyph])
    assert connectors.check_hand_drawn_arrows(scene, tokens) == []


def test_one_crossing_is_tolerated(tokens: DesignTokens) -> None:
    """A single crossing may be inherent to the graph."""
    scene = _scene(conns=[_conn("c1", 100, 100, 400, 400),
                          _conn("c2", 100, 400, 400, 100)])
    assert connectors.check_crossings(scene, tokens) == []


def test_several_crossings_are_a_warning(tokens: DesignTokens) -> None:
    """Two or more crossings point at the layout, not the graph."""
    scene = _scene(conns=[_conn("c1", 100, 100, 400, 400),
                          _conn("c2", 100, 400, 400, 100),
                          _conn("c3", 100, 250, 400, 250)])
    findings = connectors.check_crossings(scene, tokens)
    assert [f.rule for f in findings] == ["connector-crossing"]
    assert findings[0].severity == "warning"
    assert "3" in findings[0].message


def test_connectors_sharing_an_endpoint_do_not_cross(
    tokens: DesignTokens,
) -> None:
    """A fan-out from one port is not a crossing."""
    scene = _scene(conns=[_conn("c1", 300, 145, 500, 100),
                          _conn("c2", 300, 145, 500, 200),
                          _conn("c3", 300, 145, 500, 300)])
    assert connectors.check_crossings(scene, tokens) == []


def test_check_runs_every_connector_rule(tokens: DesignTokens) -> None:
    """The module entry point aggregates all six rules.

    `c1` ends in open space, `c2` claims a port it does not touch, `c3` runs
    straight through `n3`, `c4` skims six units past it, the polygon is a
    hand-drawn arrowhead beside a connector end, and the three connectors on
    the right cross each other three times against a budget of one.
    """
    node_c = _box("n3", 350, 300)
    scene = _scene(
        boxes=[_A, _B, node_c],
        conns=[_conn("c1", 300, 145, 420, 260),
               _conn("c2", 320, 145, 500, 145, from_node="n1", to_node="n2"),
               _conn("c3", 400, 250, 400, 450),
               _conn("c4", 360, 396, 540, 396),
               _conn("c5", 800, 100, 900, 200),
               _conn("c6", 800, 200, 900, 100),
               _conn("c7", 790, 150, 910, 150)],
        polys=[Polygon("poly1", ((420, 260), (410, 250), (430, 250)),
                       "#475569", None)])
    rules = {f.rule for f in connectors.check(scene, tokens)}
    assert rules == set(connectors.RULES)



def test_a_t_junction_is_not_a_crossing() -> None:
    """A connector ending on another connector is a join, not a crossing.

    The orientation test treated a zero determinant -- an endpoint lying
    exactly on the other segment -- as being on the far side, so every
    deliberate T-junction in a routed diagram counted towards the crossing
    budget and pushed a clean layout over it.
    """
    assert not connectors.segments_cross(
        Connector("a", 0, 0, 10, 0, "#475569", 2.0, False, True, None),
        Connector("b", 5, 0, 5, 5, "#475569", 2.0, False, True, None))
