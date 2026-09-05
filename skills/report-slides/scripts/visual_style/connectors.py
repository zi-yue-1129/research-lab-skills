"""Connector rules: attachment, routing, clearance, and arrowhead provenance."""
from __future__ import annotations

import math
from itertools import combinations
from typing import Dict, List, Tuple

from design_tokens import DesignTokens

from .geometry import node_bounds
from .report import Finding
from .scene import Box, Connector, Scene

RULES: Tuple[str, ...] = (
    "connector-dangling", "connector-port-drift", "connector-through-node",
    "connector-clearance", "hand-drawn-arrow", "connector-crossing",
)

ATTACH_TOLERANCE = 4.0
ARROW_PROXIMITY = 12.0
_CROSSING_BUDGET = 1
_SHARED_ENDPOINT_TOLERANCE = 1.0


def edge_distance(px: float, py: float, box: Box) -> float:
    """Return the distance from a point to a box's boundary.

    Args:
        px: Point x coordinate.
        py: Point y coordinate.
        box: The box.

    Returns:
        0.0 on the boundary; the inward distance to the nearest edge when the
        point is inside; the outward Euclidean distance when it is outside.
    """
    if box.x <= px <= box.right and box.y <= py <= box.bottom:
        return min(px - box.x, box.right - px, py - box.y, box.bottom - py)
    dx = max(box.x - px, 0.0, px - box.right)
    dy = max(box.y - py, 0.0, py - box.bottom)
    return math.hypot(dx, dy)


def _outside_distance(px: float, py: float, box: Box) -> float:
    """Return the distance from a point to a box, zero when inside.

    Args:
        px: Point x coordinate.
        py: Point y coordinate.
        box: The box.

    Returns:
        The outward Euclidean distance in SVG units.
    """
    dx = max(box.x - px, 0.0, px - box.right)
    dy = max(box.y - py, 0.0, py - box.bottom)
    return math.hypot(dx, dy)


def _point_segment_distance(px: float, py: float, x1: float, y1: float,
                            x2: float, y2: float) -> float:
    """Return the distance from a point to a segment.

    Args:
        px: Point x coordinate.
        py: Point y coordinate.
        x1: Segment start x.
        y1: Segment start y.
        x2: Segment end x.
        y2: Segment end y.

    Returns:
        The shortest distance in SVG units.
    """
    dx, dy = x2 - x1, y2 - y1
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _orientation(ax: float, ay: float, bx: float, by: float,
                 cx: float, cy: float) -> float:
    """Return the signed area of the triangle `abc`.

    Args:
        ax: First point x.
        ay: First point y.
        bx: Second point x.
        by: Second point y.
        cx: Third point x.
        cy: Third point y.

    Returns:
        Positive for a counter-clockwise turn, negative for clockwise.
    """
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _segments_intersect(x1: float, y1: float, x2: float, y2: float,
                        x3: float, y3: float, x4: float, y4: float) -> bool:
    """Return whether two segments properly intersect.

    Args:
        x1: First segment start x.
        y1: First segment start y.
        x2: First segment end x.
        y2: First segment end y.
        x3: Second segment start x.
        y3: Second segment start y.
        x4: Second segment end x.
        y4: Second segment end y.

    Returns:
        True when the segments cross at an interior point of both.
    """
    d1 = _orientation(x3, y3, x4, y4, x1, y1)
    d2 = _orientation(x3, y3, x4, y4, x2, y2)
    d3 = _orientation(x1, y1, x2, y2, x3, y3)
    d4 = _orientation(x1, y1, x2, y2, x4, y4)
    # Strict opposite signs. A zero determinant means an endpoint lies exactly
    # on the other segment, which is a T-junction -- a deliberate join in any
    # routed diagram, and not a crossing. Comparing `d > 0` puts zero on the
    # negative side and counted every such join against the crossing budget.
    return d1 * d2 < 0 and d3 * d4 < 0


def segment_crosses_box(x1: float, y1: float, x2: float, y2: float,
                        box: Box) -> bool:
    """Return whether a segment enters a box's interior.

    Args:
        x1: Segment start x.
        y1: Segment start y.
        x2: Segment end x.
        y2: Segment end y.
        box: The box.

    Returns:
        True when either endpoint is inside, or the segment crosses an edge.
    """
    if box.contains_point(x1, y1) or box.contains_point(x2, y2):
        return True
    corners = ((box.x, box.y), (box.right, box.y),
               (box.right, box.bottom), (box.x, box.bottom))
    for index in range(4):
        ax, ay = corners[index]
        bx, by = corners[(index + 1) % 4]
        if _segments_intersect(x1, y1, x2, y2, ax, ay, bx, by):
            return True
    return False


def segment_box_distance(x1: float, y1: float, x2: float, y2: float,
                         box: Box) -> float:
    """Return the shortest distance from a segment to a box.

    For two disjoint convex shapes the minimum is attained either at a box
    corner or at a segment endpoint, so both families are tested.

    Args:
        x1: Segment start x.
        y1: Segment start y.
        x2: Segment end x.
        y2: Segment end y.
        box: The box.

    Returns:
        0.0 when the segment touches or enters the box.
    """
    if segment_crosses_box(x1, y1, x2, y2, box):
        return 0.0
    corners = ((box.x, box.y), (box.right, box.y),
               (box.right, box.bottom), (box.x, box.bottom))
    corner_distance = min(
        _point_segment_distance(cx, cy, x1, y1, x2, y2) for cx, cy in corners
    )
    endpoint_distance = min(
        _outside_distance(px, py, box) for px, py in ((x1, y1), (x2, y2))
    )
    return min(corner_distance, endpoint_distance)


def segments_cross(a: Connector, b: Connector) -> bool:
    """Return whether two connectors cross away from a shared endpoint.

    Args:
        a: First connector.
        b: Second connector.

    Returns:
        True for a genuine crossing.
    """
    ends_a = ((a.x1, a.y1), (a.x2, a.y2))
    ends_b = ((b.x1, b.y1), (b.x2, b.y2))
    for ax, ay in ends_a:
        for bx, by in ends_b:
            if math.hypot(ax - bx, ay - by) <= _SHARED_ENDPOINT_TOLERANCE:
                return False
    return _segments_intersect(a.x1, a.y1, a.x2, a.y2,
                               b.x1, b.y1, b.x2, b.y2)


def _endpoints(conn: Connector) -> Tuple[Tuple[str, float, float], ...]:
    """Return a connector's endpoints tagged `start` and `end`.

    Args:
        conn: The connector.

    Returns:
        Two `(label, x, y)` triples.
    """
    return (("start", conn.x1, conn.y1), ("end", conn.x2, conn.y2))


def check_dangling(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report connector endpoints that attach to nothing.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `connector-dangling` error per offending endpoint.
    """
    del tokens
    bounds = node_bounds(scene)
    findings: List[Finding] = []
    for conn in scene.connectors:
        declared = {"start": conn.from_node, "end": conn.to_node}
        for label, px, py in _endpoints(conn):
            node = declared[label]
            if node is not None and node not in bounds:
                findings.append(Finding(
                    rule="connector-dangling", severity="error",
                    message=f"{conn.element_id} declares its {label} on node "
                            f"{node!r}, which is not in the scene",
                    element_id=conn.element_id, location=(px, py)))
                continue
            if node is not None:
                continue
            attached = any(
                edge_distance(px, py, box) <= ATTACH_TOLERANCE
                for box in scene.boxes
            )
            if not attached:
                findings.append(Finding(
                    rule="connector-dangling", severity="error",
                    message=f"{conn.element_id} has its {label} at "
                            f"({px:g}, {py:g}), which touches no shape and "
                            f"declares no node",
                    element_id=conn.element_id, location=(px, py)))
    return findings


def check_port_drift(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report endpoints that miss the node they claim to attach to.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `connector-port-drift` error per offending endpoint.
    """
    del tokens
    bounds = node_bounds(scene)
    findings: List[Finding] = []
    for conn in scene.connectors:
        declared = {"start": conn.from_node, "end": conn.to_node}
        for label, px, py in _endpoints(conn):
            node = declared[label]
            if node is None or node not in bounds:
                # An absent or unresolvable node is check_dangling's finding.
                continue
            drift = edge_distance(px, py, bounds[node])
            if drift > ATTACH_TOLERANCE:
                findings.append(Finding(
                    rule="connector-port-drift", severity="error",
                    message=f"{conn.element_id} {label} is {drift:g} from the "
                            f"boundary of node {node}; the tolerance is "
                            f"{ATTACH_TOLERANCE:g}",
                    element_id=conn.element_id, location=(px, py)))
    return findings


def _unrelated_nodes(conn: Connector, bounds: Dict[str, Box]) -> Dict[str, Box]:
    """Return the nodes a connector does not itself join.

    A node counts as joined when the connector declares it, and also when an
    endpoint lands on its boundary within `ATTACH_TOLERANCE`. Without the second
    case an undeclared but correctly attached connector would be reported as
    violating the clearance of the very node it terminates on.

    Args:
        conn: The connector.
        bounds: Node bounding boxes.

    Returns:
        The subset of `bounds` the connector neither declares nor touches.
    """
    declared = {conn.from_node, conn.to_node}
    unrelated: Dict[str, Box] = {}
    for node_id, box in bounds.items():
        if node_id in declared:
            continue
        touching = any(edge_distance(px, py, box) <= ATTACH_TOLERANCE
                       for _, px, py in _endpoints(conn))
        if touching:
            continue
        unrelated[node_id] = box
    return unrelated


def check_through_node(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report connectors routed through a node they do not join.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `connector-through-node` error per offending pair.
    """
    del tokens
    bounds = node_bounds(scene)
    findings: List[Finding] = []
    for conn in scene.connectors:
        for node_id, box in sorted(_unrelated_nodes(conn, bounds).items()):
            if segment_crosses_box(conn.x1, conn.y1, conn.x2, conn.y2, box):
                findings.append(Finding(
                    rule="connector-through-node", severity="error",
                    message=f"{conn.element_id} passes through node {node_id}, "
                            f"which it does not join",
                    element_id=conn.element_id, location=(box.x, box.y)))
    return findings


def check_clearance(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report connectors passing closer to a node than the token minimum.

    Connectors that enter a node are reported by `connector-through-node`;
    reporting both would double-count one defect.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `connector-clearance` error per offending pair.
    """
    minimum = float(tokens.raw["spacing"]["connector_clearance_min"])
    bounds = node_bounds(scene)
    findings: List[Finding] = []
    for conn in scene.connectors:
        for node_id, box in sorted(_unrelated_nodes(conn, bounds).items()):
            if segment_crosses_box(conn.x1, conn.y1, conn.x2, conn.y2, box):
                continue
            clearance = segment_box_distance(conn.x1, conn.y1,
                                             conn.x2, conn.y2, box)
            if clearance < minimum:
                findings.append(Finding(
                    rule="connector-clearance", severity="error",
                    message=f"{conn.element_id} passes {clearance:g} from node "
                            f"{node_id}; spacing.connector_clearance_min is "
                            f"{minimum:g}",
                    element_id=conn.element_id, location=(box.x, box.y)))
    return findings


def check_hand_drawn_arrows(scene: Scene,
                            tokens: DesignTokens) -> List[Finding]:
    """Report triangles drawn as arrowheads instead of markers.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `hand-drawn-arrow` error per offending polygon.
    """
    del tokens
    findings: List[Finding] = []
    for polygon in scene.polygons:
        if len(polygon.points) != 3:
            continue
        cx = sum(point[0] for point in polygon.points) / 3.0
        cy = sum(point[1] for point in polygon.points) / 3.0
        for conn in scene.connectors:
            near = any(math.hypot(cx - px, cy - py) <= ARROW_PROXIMITY
                       for _, px, py in _endpoints(conn))
            if near:
                findings.append(Finding(
                    rule="hand-drawn-arrow", severity="error",
                    message=f"{polygon.element_id} is a triangle within "
                            f"{ARROW_PROXIMITY:g} units of {conn.element_id}'s "
                            f"endpoint; use marker-end so the arrowhead "
                            f"survives the PPTX export",
                    element_id=polygon.element_id, location=(cx, cy)))
                break
    return findings


def check_crossings(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report slides with more connector crossings than the budget allows.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        At most one `connector-crossing` warning.
    """
    del tokens
    crossings = [
        (a.element_id, b.element_id)
        for a, b in combinations(scene.connectors, 2)
        if segments_cross(a, b)
    ]
    if len(crossings) <= _CROSSING_BUDGET:
        return []
    rendered = ", ".join(f"{a}x{b}" for a, b in crossings)
    return [Finding(
        rule="connector-crossing", severity="warning",
        message=f"{len(crossings)} connector crossings ({rendered}); more than "
                f"{_CROSSING_BUDGET} usually indicates the layout, not the "
                f"graph")]


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every connector rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All connector findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_dangling(scene, tokens))
    findings.extend(check_port_drift(scene, tokens))
    findings.extend(check_through_node(scene, tokens))
    findings.extend(check_clearance(scene, tokens))
    findings.extend(check_hand_drawn_arrows(scene, tokens))
    findings.extend(check_crossings(scene, tokens))
    return findings
