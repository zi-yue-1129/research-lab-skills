"""Typed scene extraction from an authored slide SVG.

Rules operate on this model rather than on raw XML, so that geometry, style
roles, and measured text extents are resolved exactly once per slide.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from lxml import etree

from fonts import text_width, vertical_metrics

_CANVAS_TOLERANCE = 0.5


def _local_tag(elem) -> str:
    """Return an element's tag without its namespace.

    Args:
        elem: An lxml element.

    Returns:
        The local tag name, or an empty string for comments.
    """
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    return tag.split("}")[-1] if "}" in tag else tag


def _number(value: Optional[str], default: float = 0.0) -> float:
    """Parse a numeric SVG attribute.

    Args:
        value: The raw attribute value.
        default: Value returned when the attribute is absent.

    Returns:
        The parsed number.

    Raises:
        ValueError: If the attribute is present but not numeric.
    """
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"non-numeric SVG attribute {value!r}: {exc}") from exc


@dataclass(frozen=True)
class Box:
    """An axis-aligned rectangle of slide content.

    Attributes:
        element_id: Identifier for reporting; the `id` attribute or a synthesised
            positional label.
        tag: Source SVG tag, such as `rect` or `circle`.
        x: Left edge in SVG units.
        y: Top edge in SVG units.
        w: Width in SVG units.
        h: Height in SVG units.
        fill: Fill colour, or None when unfilled.
        stroke: Stroke colour, or None when unstroked.
        stroke_width: Stroke width in SVG units.
        radius: Corner radius in SVG units.
        style_role: The `data-style-role` token role, when declared.
        node_id: The enclosing group's `data-node-id`, when inside one.
        bleed: Whether the element declares `data-bleed="true"` and is therefore
            allowed to extend past the safe area.
    """

    element_id: str
    tag: str
    x: float
    y: float
    w: float
    h: float
    fill: Optional[str]
    stroke: Optional[str]
    stroke_width: float
    radius: float
    style_role: Optional[str]
    node_id: Optional[str]
    bleed: bool = False

    @property
    def right(self) -> float:
        """Return the right edge."""
        return self.x + self.w

    @property
    def bottom(self) -> float:
        """Return the bottom edge."""
        return self.y + self.h

    @property
    def area(self) -> float:
        """Return the area in square SVG units."""
        return max(0.0, self.w) * max(0.0, self.h)

    def intersects(self, other: "Box") -> bool:
        """Return whether two boxes overlap in both axes.

        Args:
            other: The box to test against.

        Returns:
            True when the interiors overlap.
        """
        return (self.x < other.right and other.x < self.right
                and self.y < other.bottom and other.y < self.bottom)

    def gap_to(self, other: "Box") -> float:
        """Return the shortest edge-to-edge distance to another box.

        Args:
            other: The box to measure to.

        Returns:
            0.0 when the boxes touch or overlap, otherwise the gap in SVG units.
        """
        dx = max(0.0, max(self.x - other.right, other.x - self.right))
        dy = max(0.0, max(self.y - other.bottom, other.y - self.bottom))
        if dx == 0.0 and dy == 0.0:
            return 0.0
        if dx == 0.0:
            return dy
        if dy == 0.0:
            return dx
        return (dx ** 2 + dy ** 2) ** 0.5

    def contains_point(self, px: float, py: float) -> bool:
        """Return whether a point lies inside this box.

        Args:
            px: Point x coordinate.
            py: Point y coordinate.

        Returns:
            True when the point is strictly inside.
        """
        return self.x < px < self.right and self.y < py < self.bottom

    def contains_box(self, other: "Box") -> bool:
        """Return whether another box lies wholly inside this one.

        Args:
            other: The box to test.

        Returns:
            True when every edge of `other` is within this box.
        """
        return (self.x <= other.x and self.y <= other.y
                and other.right <= self.right and other.bottom <= self.bottom)


@dataclass(frozen=True)
class TextRun:
    """One measured text element.

    Attributes:
        element_id: Identifier for reporting.
        text: The concatenated text content.
        x: Anchor x coordinate.
        y: Baseline y coordinate.
        size: Font size in SVG units.
        weight: Numeric font weight.
        fill: Text colour.
        anchor: SVG `text-anchor` value.
        style_role: The `data-style-role` token role, when declared.
        node_id: The enclosing group's `data-node-id`, when inside one.
        line_count: Number of rendered lines.
        width: Measured advance width of the widest line.
        ascent: Measured distance from the baseline to the top of the em box.
        descent: Measured distance from the baseline to the bottom of it.
        line_offset: Summed `dy` of the element's `<tspan>` children, i.e. the
            distance from the first baseline to the last. Measured from the
            markup, not derived from a line-height constant.
    """

    element_id: str
    text: str
    x: float
    y: float
    size: float
    weight: int
    fill: str
    anchor: str
    style_role: Optional[str]
    node_id: Optional[str]
    line_count: int
    width: float
    ascent: float
    descent: float
    line_offset: float

    def bbox(self) -> Box:
        """Return the run's bounding box, honouring its anchor.

        Returns:
            A `Box` covering the rendered text.
        """
        if self.anchor == "middle":
            left = self.x - self.width / 2
        elif self.anchor == "end":
            left = self.x - self.width
        else:
            left = self.x
        # Every term here is measured. `ascent`/`descent` come from the face
        # via Pillow, and `line_offset` is the sum of the `dy` the renderer
        # actually wrote onto the tspans. A guessed 0.8 em ascent with no
        # descent term understates the top of the box and overstates its bottom
        # by most of a line, which is how the shipped footer slipped past this
        # rule while genuinely hanging outside the safe area.
        top = self.y - self.ascent
        height = self.ascent + self.line_offset + self.descent
        return Box(self.element_id, "text", left, top, self.width, height,
                   self.fill, None, 0.0, 0.0, self.style_role, self.node_id,
                   False)


@dataclass(frozen=True)
class Connector:
    """One straight connector segment.

    Attributes:
        element_id: Identifier for reporting.
        x1: Start x coordinate.
        y1: Start y coordinate.
        x2: End x coordinate.
        y2: End y coordinate.
        stroke: Stroke colour.
        stroke_width: Stroke width in SVG units.
        has_head: Whether `marker-start` requests an arrowhead.
        has_tail: Whether `marker-end` requests an arrowhead.
        node_id: The enclosing group's `data-node-id`, when inside one.
        from_node: The node id declared in `data-from`, when present.
        to_node: The node id declared in `data-to`, when present.
    """

    element_id: str
    x1: float
    y1: float
    x2: float
    y2: float
    stroke: Optional[str]
    stroke_width: float
    has_head: bool
    has_tail: bool
    node_id: Optional[str]
    from_node: Optional[str] = None
    to_node: Optional[str] = None


@dataclass(frozen=True)
class Polygon:
    """One polygon, retained so hand-drawn arrowheads can be detected.

    Attributes:
        element_id: Identifier for reporting.
        points: The polygon vertices.
        fill: Fill colour, or None when unfilled.
        node_id: The enclosing group's `data-node-id`, when inside one.
    """

    element_id: str
    points: Tuple[Tuple[float, float], ...]
    fill: Optional[str]
    node_id: Optional[str]


@dataclass(frozen=True)
class Scene:
    """Everything a rule needs to measure one slide.

    Attributes:
        width: Canvas width in SVG units.
        height: Canvas height in SVG units.
        boxes: Rectangular and elliptical content, background excluded.
        texts: Measured text runs.
        connectors: Straight connector segments.
        polygons: Free polygons.
        font_family: The resolved family used for measurement.
    """

    width: float
    height: float
    boxes: Tuple[Box, ...]
    texts: Tuple[TextRun, ...]
    connectors: Tuple[Connector, ...]
    polygons: Tuple[Polygon, ...]
    font_family: str

    def nodes(self) -> Dict[str, List[Box]]:
        """Group boxes by their enclosing semantic node.

        Returns:
            A mapping from `data-node-id` to the boxes inside that group.
        """
        grouped: Dict[str, List[Box]] = {}
        for box in self.boxes:
            if box.node_id is None:
                continue
            grouped.setdefault(box.node_id, []).append(box)
        return grouped


def _weight_of(raw: Optional[str]) -> int:
    """Parse an SVG font-weight into a numeric weight.

    Args:
        raw: The raw `font-weight` value.

    Returns:
        A numeric weight; `bold` maps to 700 and absence to 400.
    """
    value = (raw or "400").strip().lower()
    if value == "bold":
        return 700
    if value == "normal":
        return 400
    try:
        return int(value)
    except ValueError:
        return 400


def _line_count(elem) -> int:
    """Count rendered lines in a text element.

    Args:
        elem: The `<text>` element.

    Returns:
        The number of `<tspan>` children, or 1 when there are none.
    """
    spans = [child for child in elem if _local_tag(child) == "tspan"]
    return len(spans) or 1


def _line_offset(elem) -> float:
    """Sum the `dy` offsets of a text element's `<tspan>` children.

    This is the distance from the first baseline to the last, read from the
    markup the renderer produced rather than reconstructed from a line-height
    constant. `generate_slides.tlines` writes `dy="0"` on the first span and
    `dy="{size * lh:.1f}"` on each one after it.

    Args:
        elem: The `<text>` element.

    Returns:
        The total offset in SVG units; 0.0 for single-line text.
    """
    total = 0.0
    for child in elem:
        if _local_tag(child) == "tspan":
            total += _number(child.get("dy"), 0.0)
    return total


def _widest_line(elem, family: str, size: float, weight: int) -> Tuple[str, float]:
    """Measure a text element's widest rendered line.

    Args:
        elem: The `<text>` element.
        family: Resolved font family.
        size: Font size in SVG units.
        weight: Numeric font weight.

    Returns:
        `(text, width)` for the widest line; the text is the full content.
    """
    spans = [child for child in elem if _local_tag(child) == "tspan"]
    if spans:
        lines = ["".join(span.itertext()) for span in spans]
    else:
        lines = ["".join(elem.itertext())]
    widest = 0.0
    for line in lines:
        widest = max(widest, text_width(line, family, size, weight))
    return "".join(elem.itertext()).strip(), widest


def parse_scene(svg_path: Union[str, Path], font_family: str) -> Scene:
    """Parse an authored slide SVG into a typed scene.

    Args:
        svg_path: Path to the SVG file.
        font_family: A resolved, installed family used for text measurement.

    Returns:
        The extracted `Scene`.

    Raises:
        ValueError: If the SVG has no usable `viewBox`, or an attribute is
            malformed.
    """
    tree = etree.parse(str(svg_path))
    root = tree.getroot()
    viewbox = root.get("viewBox")
    if not viewbox:
        raise ValueError(
            f"{svg_path} has no viewBox; the scene cannot be measured"
        )
    parts = viewbox.split()
    if len(parts) != 4:
        raise ValueError(f"{svg_path} has a malformed viewBox {viewbox!r}")
    width = _number(parts[2])
    height = _number(parts[3])

    boxes: List[Box] = []
    texts: List[TextRun] = []
    connectors: List[Connector] = []
    polygons: List[Polygon] = []

    def walk(elem, node_id: Optional[str], index: List[int]) -> None:
        """Recursively collect scene content.

        Args:
            elem: Current element.
            node_id: Inherited `data-node-id`, if any.
            index: Single-element list used as a mutable counter for ids.
        """
        for child in elem:
            tag = _local_tag(child)
            if not tag:
                continue
            index[0] += 1
            element_id = child.get("id") or f"{tag}#{index[0]}"
            child_node = child.get("data-node-id") or node_id
            role = child.get("data-style-role")
            bleed = (child.get("data-bleed") or "").strip().lower() == "true"

            if tag == "g":
                walk(child, child_node, index)
                continue

            if tag == "rect":
                x = _number(child.get("x"))
                y = _number(child.get("y"))
                w = _number(child.get("width"))
                h = _number(child.get("height"))
                is_background = (
                    abs(x) < _CANVAS_TOLERANCE and abs(y) < _CANVAS_TOLERANCE
                    and abs(w - width) < _CANVAS_TOLERANCE
                    and abs(h - height) < _CANVAS_TOLERANCE
                )
                if is_background:
                    continue
                radius = max(_number(child.get("rx")), _number(child.get("ry")))
                boxes.append(Box(
                    element_id, tag, x, y, w, h,
                    child.get("fill"), child.get("stroke"),
                    _number(child.get("stroke-width")), radius, role, child_node,
                    bleed))
            elif tag in ("circle", "ellipse"):
                cx = _number(child.get("cx"))
                cy = _number(child.get("cy"))
                if tag == "circle":
                    rx = ry = _number(child.get("r"))
                else:
                    rx = _number(child.get("rx"))
                    ry = _number(child.get("ry"))
                boxes.append(Box(
                    element_id, tag, cx - rx, cy - ry, 2 * rx, 2 * ry,
                    child.get("fill"), child.get("stroke"),
                    _number(child.get("stroke-width")), min(rx, ry),
                    role, child_node, bleed))
            elif tag == "text":
                size = _number(child.get("font-size"), 0.0)
                weight = _weight_of(child.get("font-weight"))
                content, measured = _widest_line(child, font_family, size, weight)
                ascent, descent = vertical_metrics(font_family, size)
                texts.append(TextRun(
                    element_id, content,
                    _number(child.get("x")), _number(child.get("y")),
                    size, weight, child.get("fill") or "#000000",
                    child.get("text-anchor") or "start",
                    role, child_node, _line_count(child), measured,
                    ascent, descent, _line_offset(child)))
            elif tag == "line":
                if not _is_connector(child):
                    continue
                connectors.append(Connector(
                    element_id,
                    _number(child.get("x1")), _number(child.get("y1")),
                    _number(child.get("x2")), _number(child.get("y2")),
                    child.get("stroke"), _number(child.get("stroke-width"), 1.0),
                    _marker_requested(child.get("marker-start")),
                    _marker_requested(child.get("marker-end")),
                    child_node, child.get("data-from"), child.get("data-to")))
            elif tag in ("polygon", "polyline"):
                points = _parse_points(child.get("points", ""))
                if tag == "polygon":
                    polygons.append(Polygon(
                        element_id, points, child.get("fill"), child_node))
                elif not _is_connector(child):
                    continue
                else:
                    for start, end in zip(points, points[1:]):
                        connectors.append(Connector(
                            element_id, start[0], start[1], end[0], end[1],
                            child.get("stroke"),
                            _number(child.get("stroke-width"), 1.0),
                            _marker_requested(child.get("marker-start")),
                            _marker_requested(child.get("marker-end")),
                            child_node, child.get("data-from"),
                            child.get("data-to")))
            else:
                walk(child, child_node, index)

    walk(root, None, [0])
    return Scene(width, height, tuple(boxes), tuple(texts),
                 tuple(connectors), tuple(polygons), font_family)


def _marker_requested(value: Optional[str]) -> bool:
    """Return whether a marker attribute asks for an arrowhead.

    Args:
        value: The raw `marker-start` or `marker-end` value.

    Returns:
        True for a `url(#id)` reference.
    """
    text = (value or "").strip().lower()
    return bool(text) and text != "none"


def _is_connector(elem) -> bool:
    """Return whether a line-like element is a semantic connector.

    Chart gridlines, column rules, and the frame's header rule are lines that
    join nothing. Linting them for attachment would fire on every slide, so a
    line must declare its intent to be treated as a connector.

    Args:
        elem: The `<line>` or `<polyline>` element.

    Returns:
        True when the element declares endpoints, an arrowhead, or a connector
        style role.
    """
    if elem.get("data-from") or elem.get("data-to"):
        return True
    if _marker_requested(elem.get("marker-start")) or _marker_requested(
            elem.get("marker-end")):
        return True
    return (elem.get("data-style-role") or "").startswith("connector")


def _parse_points(raw: str) -> Tuple[Tuple[float, float], ...]:
    """Parse an SVG points list.

    Args:
        raw: The raw `points` attribute.

    Returns:
        The parsed vertices.

    Raises:
        ValueError: If the list contains a non-numeric entry or an odd count.
    """
    tokens = [token for token in raw.replace(",", " ").split() if token]
    try:
        numbers = [float(token) for token in tokens]
    except ValueError as exc:
        raise ValueError(f"malformed points list {raw!r}: {exc}") from exc
    if len(numbers) % 2 != 0:
        raise ValueError(f"points list {raw!r} has an odd number of values")
    return tuple(
        (numbers[i], numbers[i + 1]) for i in range(0, len(numbers), 2)
    )
