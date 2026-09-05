"""Density and consistency rules: component drift, rhythm, and slide load."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from design_tokens import DesignTokens

from .geometry import node_bounds
from .report import Finding
from .scene import Box, Scene

RULES: Tuple[str, ...] = (
    "component-drift", "spacing-variance", "bullet-budget", "occupancy",
    "equal-card-repetition",
)

SPACING_TOLERANCE = 4.0
EQUAL_CARD_THRESHOLD = 4
_METRIC_TOLERANCE = 0.5
_ROW_OVERLAP_RATIO = 0.5


def union_area(boxes: Sequence[Box]) -> float:
    """Return the area covered by a set of boxes, counting overlap once.

    The sweep compresses the x-coordinates into strips, then for each strip
    merges the y-intervals of the boxes spanning it.

    Args:
        boxes: The boxes to union.

    Returns:
        The covered area in square SVG units.
    """
    if not boxes:
        return 0.0
    xs = sorted({box.x for box in boxes} | {box.right for box in boxes})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        strip_width = right - left
        if strip_width <= 0:
            continue
        intervals = sorted(
            (box.y, box.bottom) for box in boxes
            if box.x <= left and box.right >= right and box.bottom > box.y
        )
        covered = 0.0
        current_top, current_bottom = None, None
        for top, bottom in intervals:
            if current_bottom is None or top > current_bottom:
                if current_bottom is not None:
                    covered += current_bottom - current_top
                current_top, current_bottom = top, bottom
            else:
                current_bottom = max(current_bottom, bottom)
        if current_bottom is not None:
            covered += current_bottom - current_top
        total += strip_width * covered
    return total


def _drift(values: Sequence[float]) -> float:
    """Return the spread of a metric across component instances.

    Args:
        values: The measured values.

    Returns:
        `max - min`, or 0.0 for fewer than two values.
    """
    if len(values) < 2:
        return 0.0
    return max(values) - min(values)


def check_component_drift(scene: Scene,
                          tokens: DesignTokens) -> List[Finding]:
    """Report instances of one style role that are not drawn alike.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `component-drift` error per offending role.
    """
    del tokens
    findings: List[Finding] = []

    by_role: Dict[str, List[Box]] = defaultdict(list)
    for box in scene.boxes:
        if box.style_role:
            by_role[box.style_role].append(box)
    for role, boxes in sorted(by_role.items()):
        metrics = (
            ("radius", [box.radius for box in boxes]),
            ("stroke width", [box.stroke_width for box in boxes]),
        )
        drifting = [
            f"{name} spans {min(values):g}..{max(values):g}"
            for name, values in metrics
            if _drift(values) > _METRIC_TOLERANCE
        ]
        if drifting:
            findings.append(Finding(
                rule="component-drift", severity="error",
                message=f"{len(boxes)} instances of style role {role!r} differ: "
                        + "; ".join(drifting),
                element_id=boxes[0].element_id,
                location=(boxes[0].x, boxes[0].y)))

    text_by_role: Dict[str, List[float]] = defaultdict(list)
    for run in scene.texts:
        if run.style_role:
            text_by_role[run.style_role].append(run.size)
    for role, sizes in sorted(text_by_role.items()):
        if _drift(sizes) > _METRIC_TOLERANCE:
            findings.append(Finding(
                rule="component-drift", severity="error",
                message=f"{len(sizes)} runs of style role {role!r} differ in "
                        f"label size, spanning {min(sizes):g}..{max(sizes):g}"))
    return findings


def _rows(boxes: Sequence[Box]) -> List[List[Box]]:
    """Group boxes into horizontal rows by vertical overlap.

    Args:
        boxes: The boxes to group.

    Returns:
        Rows of three or more boxes, each sorted left to right.
    """
    rows: List[List[Box]] = []
    for box in sorted(boxes, key=lambda item: (item.y, item.x)):
        placed = False
        for row in rows:
            reference = row[0]
            overlap = (min(reference.bottom, box.bottom)
                       - max(reference.y, box.y))
            if overlap >= _ROW_OVERLAP_RATIO * min(reference.h, box.h):
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])
    return [sorted(row, key=lambda item: item.x) for row in rows
            if len(row) >= 3]


def check_spacing_variance(scene: Scene,
                           tokens: DesignTokens) -> List[Finding]:
    """Report rows of nodes whose gaps are not evenly spaced.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        One `spacing-variance` warning per offending row.
    """
    del tokens
    findings: List[Finding] = []
    for row in _rows(list(node_bounds(scene).values())):
        gaps = [right.x - left.right for left, right in zip(row, row[1:])]
        if _drift(gaps) > SPACING_TOLERANCE:
            rendered = ", ".join(f"{gap:g}" for gap in gaps)
            findings.append(Finding(
                rule="spacing-variance", severity="warning",
                message=f"row starting at {row[0].element_id} has uneven gaps "
                        f"({rendered}); the tolerance is "
                        f"{SPACING_TOLERANCE:g}",
                element_id=row[0].element_id,
                location=(row[0].x, row[0].y)))
    return findings


def check_bullet_budget(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report slides carrying more body runs than the token budget allows.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        At most one `bullet-budget` warning.
    """
    budget = int(tokens.raw["density"]["max_bullets"])
    # `render_table` gives every data cell the `body` role, so a 2x4 results
    # table looked like eight bullets and warned on every table slide. Tabular
    # text is not prose and does not spend the prose budget.
    bullets = [run for run in scene.texts
               if (run.style_role or "").replace(".", "_") == "body"
               and run.pptx_role != "table"]
    if len(bullets) <= budget:
        return []
    return [Finding(
        rule="bullet-budget", severity="warning",
        message=f"slide carries {len(bullets)} body runs; density.max_bullets "
                f"is {budget}")]


def check_occupancy(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report slides whose content covers too little or too much of the frame.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        At most one `occupancy` warning.

    Raises:
        ValueError: If the safe area leaves no drawable region.
    """
    limits = tokens.raw["density"]
    safe = tokens.raw["canvas"]["safe_area"]
    safe_area = ((scene.width - float(safe["left"]) - float(safe["right"]))
                 * (scene.height - float(safe["top"]) - float(safe["bottom"])))
    if safe_area <= 0:
        raise ValueError("canvas.safe_area leaves no drawable area")
    content = [box for box in scene.boxes if not box.bleed]
    content.extend(run.bbox() for run in scene.texts)
    # `union_area` counts overlap once, so the heavily overlapping bounding
    # boxes of adjacent pie wedges inflate nothing. Leaving them out did
    # inflate something: a slide drawn entirely in `<path>` unioned to zero
    # and was told to add content it already had.
    content.extend(box for box in scene.outline_boxes() if not box.bleed)
    ratio = union_area(content) / safe_area
    minimum = float(limits["occupancy_min"])
    maximum = float(limits["occupancy_max"])
    if ratio < minimum:
        return [Finding(
            rule="occupancy", severity="warning",
            message=f"content covers {ratio:.2f} of the safe area; "
                    f"density.occupancy_min is {minimum:.2f}")]
    if ratio > maximum:
        return [Finding(
            rule="occupancy", severity="warning",
            message=f"content covers {ratio:.2f} of the safe area; "
                    f"density.occupancy_max is {maximum:.2f}")]
    return []


def check_equal_cards(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report undifferentiated repetitions of one identically sized card.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set. Unused; present for a uniform signature.

    Returns:
        At most one `equal-card-repetition` warning per size cohort.
    """
    del tokens
    cohorts: Dict[Tuple[str, float, float], List[Box]] = defaultdict(list)
    for box in scene.boxes:
        if not box.style_role:
            continue
        cohorts[(box.style_role, round(box.w, 1), round(box.h, 1))].append(box)
    findings: List[Finding] = []
    for (role, width, height), boxes in sorted(cohorts.items()):
        if len(boxes) < EQUAL_CARD_THRESHOLD:
            continue
        names = ", ".join(box.element_id for box in boxes)
        findings.append(Finding(
            rule="equal-card-repetition", severity="warning",
            message=f"{len(boxes)} cards of style role {role!r} are all "
                    f"{width:g}x{height:g} ({names}); the layout states no "
                    f"hierarchy between them",
            element_id=boxes[0].element_id,
            location=(boxes[0].x, boxes[0].y)))
    return findings


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every density and consistency rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All density findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_component_drift(scene, tokens))
    findings.extend(check_spacing_variance(scene, tokens))
    findings.extend(check_bullet_budget(scene, tokens))
    findings.extend(check_occupancy(scene, tokens))
    findings.extend(check_equal_cards(scene, tokens))
    return findings
