"""Geometry rules: safe area, overlap, node spacing, and grid alignment."""
from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Optional, Tuple

from design_tokens import DesignTokens

from .report import Finding
from .scene import Box, Scene, TextRun

RULES: Tuple[str, ...] = (
    "safe-area", "element-overlap", "node-gap", "node-padding", "off-grid",
)

_EDGE_TOLERANCE = 0.5
_GRID_TOLERANCE = 2.0
_OVERLAP_TOLERANCE = 0.5


def _safe_bounds(scene: Scene, tokens: DesignTokens
                 ) -> Tuple[float, float, float, float]:
    """Return the safe-area rectangle as `(left, top, right, bottom)`.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        Absolute edge coordinates in SVG units.
    """
    safe = tokens.raw["canvas"]["safe_area"]
    return (float(safe["left"]), float(safe["top"]),
            scene.width - float(safe["right"]),
            scene.height - float(safe["bottom"]))


def check_safe_area(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report content that leaves the safe area without declaring bleed.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `safe-area` error per offending element.
    """
    left, top, right, bottom = _safe_bounds(scene, tokens)
    findings: List[Finding] = []
    candidates: List[Box] = [box for box in scene.boxes if not box.bleed]
    candidates.extend(run.bbox() for run in scene.texts)
    for box in candidates:
        breaches: List[str] = []
        if box.x < left - _EDGE_TOLERANCE:
            breaches.append(f"left {box.x:g} < {left:g}")
        if box.y < top - _EDGE_TOLERANCE:
            breaches.append(f"top {box.y:g} < {top:g}")
        if box.right > right + _EDGE_TOLERANCE:
            breaches.append(f"right {box.right:g} > {right:g}")
        if box.bottom > bottom + _EDGE_TOLERANCE:
            breaches.append(f"bottom {box.bottom:g} > {bottom:g}")
        if breaches:
            findings.append(Finding(
                rule="safe-area", severity="error",
                message=f"{box.element_id} leaves the safe area: "
                        + "; ".join(breaches),
                element_id=box.element_id, location=(box.x, box.y)))
    return findings


def _material_overlap(a: Box, b: Box) -> bool:
    """Return whether two boxes overlap by more than tiling noise.

    Renderers place abutting bands by accumulating float heights, so one band
    can end at 209.0 while the next starts at 208.9. A tenth of a unit is not a
    collision, and reporting it as a hard error on every table slide is how a
    gate earns the reputation that gets it switched off. Overlap has to be
    material on both axes before it counts.

    Args:
        a: First box.
        b: Second box.

    Returns:
        True when the intersection exceeds `_OVERLAP_TOLERANCE` in x and in y.
    """
    x_depth = min(a.right, b.right) - max(a.x, b.x)
    y_depth = min(a.bottom, b.bottom) - max(a.y, b.y)
    return x_depth > _OVERLAP_TOLERANCE and y_depth > _OVERLAP_TOLERANCE


def _same_node(a: Box, b: Box) -> bool:
    """Return whether two boxes belong to the same semantic node.

    Args:
        a: First box.
        b: Second box.

    Returns:
        True when both carry the same non-null node id.
    """
    return a.node_id is not None and a.node_id == b.node_id


def _intended_containment(inner: Box, outer: Box) -> bool:
    """Return whether one box containing another is deliberate composition.

    A label inside its own node, or a card inside an unscoped panel, is how
    slides are built. Two *different* semantic nodes where one swallows the
    other is not composition, it is the worst-looking defect a diagram can
    carry -- and it used to pass, because `check_overlap` waved containment
    through and `check_node_gap` skips pairs that intersect on the grounds
    that overlap covers them.

    Args:
        inner: The contained box.
        outer: The containing box.

    Returns:
        True unless both boxes carry different non-null node ids.
    """
    if inner.node_id is None or outer.node_id is None:
        return True
    return inner.node_id == outer.node_id


def _overlap_finding(first: str, second: str, x: float, y: float) -> Finding:
    """Build one overlap finding.

    Args:
        first: Identifier of the first element.
        second: Identifier of the second element.
        x: Report location x.
        y: Report location y.

    Returns:
        The finding.
    """
    return Finding(
        rule="element-overlap", severity="error",
        message=f"{first} overlaps {second} with neither containing the other",
        element_id=first, location=(x, y))


def check_overlap(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report unintended overlap between shapes and text.

    Containment is intended composition, as is a label inside its own node.
    Text overlapping text is never intended.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `element-overlap` error per offending pair.
    """
    del tokens
    findings: List[Finding] = []
    text_boxes = [(run, run.bbox()) for run in scene.texts]

    for a, b in combinations(scene.boxes, 2):
        if not _material_overlap(a, b):
            continue
        if _same_node(a, b):
            continue
        if a.contains_box(b) and _intended_containment(b, a):
            continue
        if b.contains_box(a) and _intended_containment(a, b):
            continue
        findings.append(_overlap_finding(a.element_id, b.element_id, a.x, a.y))

    for run, bbox in text_boxes:
        for box in scene.boxes:
            if not _material_overlap(bbox, box):
                continue
            if box.contains_box(bbox) or _same_node(bbox, box):
                continue
            findings.append(
                _overlap_finding(run.element_id, box.element_id, bbox.x, bbox.y))

    for (run_a, box_a), (run_b, box_b) in combinations(text_boxes, 2):
        if _material_overlap(box_a, box_b):
            findings.append(_overlap_finding(
                run_a.element_id, run_b.element_id, box_a.x, box_a.y))
    return findings


def node_bounds(scene: Scene) -> Dict[str, Box]:
    """Return the union bounding box of each semantic node.

    Args:
        scene: The parsed slide.

    Returns:
        A mapping from node id to its union box.
    """
    bounds: Dict[str, Box] = {}
    for node_id, boxes in scene.nodes().items():
        left = min(box.x for box in boxes)
        top = min(box.y for box in boxes)
        right = max(box.right for box in boxes)
        bottom = max(box.bottom for box in boxes)
        bounds[node_id] = Box(node_id, "group", left, top, right - left,
                              bottom - top, None, None, 0.0, 0.0, None,
                              node_id, False)
    return bounds


def check_node_gap(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report node pairs closer than `spacing.node_gap_min`.

    Overlapping nodes are left to `element-overlap`; reporting both would
    double-count one defect.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `node-gap` error per offending pair.
    """
    minimum = float(tokens.raw["spacing"]["node_gap_min"])
    findings: List[Finding] = []
    bounds = node_bounds(scene)
    for (id_a, box_a), (id_b, box_b) in combinations(sorted(bounds.items()), 2):
        if box_a.intersects(box_b):
            continue
        gap = box_a.gap_to(box_b)
        if gap < minimum - _EDGE_TOLERANCE:
            findings.append(Finding(
                rule="node-gap", severity="error",
                message=f"nodes {id_a} and {id_b} are {gap:g} apart; "
                        f"spacing.node_gap_min is {minimum:g}",
                element_id=id_a, location=(box_a.right, box_a.y)))
    return findings


def _enclosing_box(run: TextRun, scene: Scene) -> Optional[Box]:
    """Return the smallest box of the run's own node that encloses its centre.

    Args:
        run: The text run.
        scene: The parsed slide.

    Returns:
        The enclosing box, or None when the run sits in no node box.
    """
    if run.node_id is None:
        return None
    bbox = run.bbox()
    cx = bbox.x + bbox.w / 2
    cy = bbox.y + bbox.h / 2
    own = [box for box in scene.boxes if box.node_id == run.node_id]
    if not own:
        return None
    candidates = [box for box in own if box.contains_point(cx, cy)]
    if candidates:
        return min(candidates, key=lambda box: box.area)
    # The label's centre is outside every box of its node. Half in and half out
    # is a label that has escaped the surface it is meant to sit on, and
    # returning None there meant the further it drifted the more certainly it
    # was ignored. Wholly outside is a different idiom, not a defect: a
    # timeline's node is a ten-unit dot with its label deliberately placed
    # beyond it on a stem, and holding that to node padding reports every
    # event on every timeline slide.
    overlapping = [box for box in own if box.intersects(bbox)]
    if not overlapping:
        return None
    return max(overlapping, key=lambda box: box.area)


def check_node_padding(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report labels inset less than `spacing.node_padding` from their node.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `node-padding` error per offending label.
    """
    padding = tokens.raw["spacing"]["node_padding"]
    pad_x = float(padding["x"])
    pad_y = float(padding["y"])
    findings: List[Finding] = []
    for run in scene.texts:
        host = _enclosing_box(run, scene)
        if host is None:
            continue
        bbox = run.bbox()
        insets = (
            ("left", bbox.x - host.x, pad_x),
            ("right", host.right - bbox.right, pad_x),
            ("top", bbox.y - host.y, pad_y),
            ("bottom", host.bottom - bbox.bottom, pad_y),
        )
        breaches = [
            f"{edge} inset {value:g} < {required:g}"
            for edge, value, required in insets
            if value < required - _EDGE_TOLERANCE
        ]
        if breaches:
            findings.append(Finding(
                rule="node-padding", severity="error",
                message=f"{run.element_id} inside {host.element_id}: "
                        + "; ".join(breaches),
                element_id=run.element_id, location=(bbox.x, bbox.y)))
    return findings


def _is_data_mark(box: Box) -> bool:
    """Return whether a box is a data mark rather than a laid-out element.

    A bar's height and a marker's position come from the value they encode, not
    from the layout grid. Holding them to `canvas.grid` would emit a warning per
    bar on every chart slide.

    Args:
        box: The box to classify.

    Returns:
        True for boxes whose style role marks them as chart geometry.
    """
    role = box.style_role or ""
    if role.startswith("chart") or role.startswith("mark"):
        return True
    # The renderers do not put a style role on generated bars and plot bands;
    # they wrap the whole plot in `data-pptx-role="chart"`. Keying only on the
    # style role produced an `off-grid` warning per bar on every chart slide.
    return box.pptx_role == "chart"


def _grid_delta(value: float, grid: float) -> float:
    """Return the distance from a value to the nearest grid multiple.

    Args:
        value: The measured coordinate or extent.
        grid: The grid quantum.

    Returns:
        The absolute deviation in SVG units.
    """
    remainder = abs(value) % grid
    return min(remainder, grid - remainder)


def check_grid(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report box geometry that is not aligned to `canvas.grid`.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `off-grid` warning per offending box.
    """
    grid = float(tokens.raw["canvas"]["grid"])
    findings: List[Finding] = []
    for box in scene.boxes:
        if box.bleed or _is_data_mark(box):
            continue
        offenders = [
            f"{name}={value:g} (off by {_grid_delta(value, grid):g})"
            for name, value in (("x", box.x), ("y", box.y),
                                ("width", box.w), ("height", box.h))
            if _grid_delta(value, grid) > _GRID_TOLERANCE
        ]
        if offenders:
            findings.append(Finding(
                rule="off-grid", severity="warning",
                message=f"{box.element_id} is off the {grid:g}-unit grid: "
                        + ", ".join(offenders),
                element_id=box.element_id, location=(box.x, box.y)))
    return findings


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every geometry rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All geometry findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_safe_area(scene, tokens))
    findings.extend(check_overlap(scene, tokens))
    findings.extend(check_node_gap(scene, tokens))
    findings.extend(check_node_padding(scene, tokens))
    findings.extend(check_grid(scene, tokens))
    return findings
