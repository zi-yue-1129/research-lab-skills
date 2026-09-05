"""Typed scene extraction from an authored slide SVG.

Rules operate on this model rather than on raw XML, so that geometry, style
roles, and measured text extents are resolved exactly once per slide.
"""
from __future__ import annotations

import re
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
        pptx_role: The nearest enclosing `data-pptx-role`, when inside one. It
            names what kind of native object the group becomes, which is how a
            rule tells chart furniture from authored layout.
        paint_order: Document position, counting from 1. SVG has no z-index:
            the element painted last is the one on top, and colour rules need
            that order to know what a point actually sits on.
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
    pptx_role: Optional[str] = None
    paint_order: int = 0

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
        min_size: The smallest font size actually rendered by this element,
            taking `<tspan>` overrides into account. `size` is the element's
            own declaration and says nothing about a span that overrides it.
        fills: Every distinct colour the element paints, the element's own
            fill plus any `<tspan>` override. Contrast has to see all of them.
        pptx_role: The nearest enclosing `data-pptx-role`, when inside one.
        paint_order: Document position, counting from 1.
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
    min_size: float = 0.0
    fills: Tuple[str, ...] = ()
    pptx_role: Optional[str] = None
    paint_order: int = 0

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
                   False, self.pptx_role, self.paint_order)


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
    style_role: Optional[str] = None


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
    stroke: Optional[str] = None
    style_role: Optional[str] = None


@dataclass(frozen=True)
class PathShape:
    """One `<path>`, captured for colour linting only.

    Pie wedges and any hand-authored curve arrive as `<path>`, and until this
    existed their fills were invisible to every rule: an off-palette wedge
    passed the gate untouched.

    Geometry is deliberately absent. A bounding box reconstructed from the `d`
    string is wrong for arcs -- bounding the control points overstates it and
    bounding the endpoints understates it -- and a wrong box either invents
    findings or hides them. A declared absence is honest; a guess is not.

    Attributes:
        element_id: Identifier for reporting.
        fill: Fill colour, or None when unfilled.
        stroke: Stroke colour, or None when unstroked.
        stroke_width: Stroke width in SVG units.
        style_role: The `data-style-role` token role, when declared.
        node_id: The enclosing group's `data-node-id`, when inside one.
        pptx_role: The nearest enclosing `data-pptx-role`, when inside one.
    """

    element_id: str
    fill: Optional[str]
    stroke: Optional[str]
    stroke_width: float
    style_role: Optional[str]
    node_id: Optional[str]
    pptx_role: Optional[str] = None


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
        paths: `<path>` elements, retained for colour linting only.
        background: The last full-canvas rectangle, kept out of `boxes` so it
            cannot trip layout rules but available to colour rules. Dropping it
            made every rule judge white text on a navy section divider against
            the token background, which is white.
    """

    width: float
    height: float
    boxes: Tuple[Box, ...]
    texts: Tuple[TextRun, ...]
    connectors: Tuple[Connector, ...]
    polygons: Tuple[Polygon, ...]
    font_family: str
    paths: Tuple[PathShape, ...] = ()
    background: Optional[Box] = None

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


_TRANSFORM_CALL_RE = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")
_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARGUMENT_SEPARATORS = " \t\r\n,"


def _parse_transform(raw: Optional[str], element_id: str
                     ) -> Tuple[float, float]:
    """Resolve a `transform` attribute into a translation.

    Only `translate` is supported. Anything else changes the shape of what is
    drawn, and measuring a rotated group at its authored coordinates reports a
    clean gate for a slide nobody checked.

    Every character of the attribute has to be accounted for. An earlier
    version matched translate arguments with a digits-and-dots pattern, so
    `translate(1e2,0)` matched nothing at all and the translation was silently
    dropped -- the element was then measured a hundred units from where it is
    drawn and the slide passed. Refusing is the honest outcome for anything
    this parser cannot read: the linter turns the error into
    `unreadable-input`, which names the file.

    Args:
        raw: The raw `transform` attribute, or None.
        element_id: Identifier used in the error message.

    Returns:
        `(dx, dy)` in SVG units.

    Raises:
        ValueError: If the transform uses anything other than `translate`, or
            carries anything this parser cannot read as a number.
    """
    if not raw or not raw.strip():
        return 0.0, 0.0
    dx = dy = 0.0
    seen = False
    for match in _TRANSFORM_CALL_RE.finditer(raw):
        seen = True
        name, arguments = match.group(1), match.group(2)
        if name != "translate":
            raise ValueError(
                f"{element_id} carries an unsupported transform {name}; "
                f"only translate can be measured")
        numbers = _NUMBER_RE.findall(arguments)
        residue = _NUMBER_RE.sub("", arguments).strip(_ARGUMENT_SEPARATORS)
        if residue or not 1 <= len(numbers) <= 2:
            raise ValueError(
                f"{element_id} has a transform this parser cannot read: "
                f"translate({arguments})")
        dx += float(numbers[0])
        dy += float(numbers[1]) if len(numbers) > 1 else 0.0
    outside = _TRANSFORM_CALL_RE.sub("", raw).strip()
    if outside or not seen:
        raise ValueError(
            f"{element_id} has a transform this parser cannot read: {raw!r}")
    return dx, dy


def _tspan_styling(elem, base_size: float, base_fill: str
                   ) -> Tuple[float, Tuple[str, ...]]:
    """Return the smallest size and every fill the element renders.

    Args:
        elem: The `<text>` element.
        base_size: The element's own `font-size`.
        base_fill: The element's own `fill`.

    Returns:
        `(min_size, fills)` over the element and its `<tspan>` children.
    """
    sizes = [base_size] if base_size > 0 else []
    fills = [base_fill]
    for child in elem:
        if _local_tag(child) != "tspan":
            continue
        raw_size = child.get("font-size")
        if raw_size:
            sizes.append(_number(raw_size))
        raw_fill = child.get("fill")
        if raw_fill:
            fills.append(raw_fill)
    return (min(sizes) if sizes else base_size,
            tuple(dict.fromkeys(fills)))


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
        # A span may override the element's size and weight, and measuring it
        # at the parent's numbers overstates or understates its advance by
        # whatever the ratio happens to be.
        lines = [("".join(span.itertext()),
                  _number(span.get("font-size"), size),
                  _weight_of(span.get("font-weight"))
                  if span.get("font-weight") else weight)
                 for span in spans]
    else:
        lines = [("".join(elem.itertext()), size, weight)]
    widest = 0.0
    for line, line_size, line_weight in lines:
        widest = max(widest, text_width(line, family, line_size, line_weight))
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
    paths: List[PathShape] = []
    backgrounds: List[Box] = []

    def walk(elem, node_id: Optional[str], pptx_role: Optional[str],
             dx: float, dy: float, index: List[int]) -> None:
        """Recursively collect scene content.

        Args:
            elem: Current element.
            node_id: Inherited `data-node-id`, if any.
            pptx_role: Inherited `data-pptx-role`, if any.
            dx: Accumulated x translation from enclosing transforms.
            dy: Accumulated y translation from enclosing transforms.
            index: Single-element list used as a mutable counter for ids.

        Raises:
            ValueError: If an element carries a transform that cannot be
                resolved to a translation.
        """
        for child in elem:
            tag = _local_tag(child)
            if not tag:
                continue
            index[0] += 1
            order = index[0]
            element_id = child.get("id") or f"{tag}#{order}"
            tdx, tdy = _parse_transform(child.get("transform"), element_id)
            cdx, cdy = dx + tdx, dy + tdy
            child_node = child.get("data-node-id") or node_id
            child_role = child.get("data-pptx-role") or pptx_role
            role = child.get("data-style-role")
            bleed = (child.get("data-bleed") or "").strip().lower() == "true"

            if tag == "g":
                walk(child, child_node, child_role, cdx, cdy, index)
                continue

            if tag == "rect":
                x = _number(child.get("x")) + cdx
                y = _number(child.get("y")) + cdy
                w = _number(child.get("width"))
                h = _number(child.get("height"))
                box = Box(
                    element_id, tag, x, y, w, h,
                    child.get("fill"), child.get("stroke"),
                    _number(child.get("stroke-width")),
                    max(_number(child.get("rx")), _number(child.get("ry"))),
                    role, child_node, bleed, child_role, order)
                is_background = (
                    abs(x) < _CANVAS_TOLERANCE and abs(y) < _CANVAS_TOLERANCE
                    and abs(w - width) < _CANVAS_TOLERANCE
                    and abs(h - height) < _CANVAS_TOLERANCE
                )
                # The canvas fill is not layout -- it must not trip safe area,
                # overlap, or occupancy -- but it is what every glyph on the
                # slide is actually drawn on, so the colour rules need it.
                (backgrounds if is_background else boxes).append(box)
            elif tag in ("circle", "ellipse"):
                cx = _number(child.get("cx")) + cdx
                cy = _number(child.get("cy")) + cdy
                if tag == "circle":
                    rx = ry = _number(child.get("r"))
                else:
                    rx = _number(child.get("rx"))
                    ry = _number(child.get("ry"))
                boxes.append(Box(
                    element_id, tag, cx - rx, cy - ry, 2 * rx, 2 * ry,
                    child.get("fill"), child.get("stroke"),
                    _number(child.get("stroke-width")), min(rx, ry),
                    role, child_node, bleed, child_role, order))
            elif tag == "path":
                paths.append(PathShape(
                    element_id, child.get("fill"), child.get("stroke"),
                    _number(child.get("stroke-width")), role, child_node,
                    child_role))
            elif tag == "text":
                size = _number(child.get("font-size"), 0.0)
                weight = _weight_of(child.get("font-weight"))
                content, measured = _widest_line(child, font_family, size, weight)
                ascent, descent = vertical_metrics(font_family, size)
                fill = child.get("fill") or "#000000"
                min_size, fills = _tspan_styling(child, size, fill)
                texts.append(TextRun(
                    element_id, content,
                    _number(child.get("x")) + cdx, _number(child.get("y")) + cdy,
                    size, weight, fill,
                    child.get("text-anchor") or "start",
                    role, child_node, _line_count(child), measured,
                    ascent, descent, _line_offset(child),
                    min_size, fills, child_role, order))
            elif tag == "line":
                if not _is_connector(child):
                    continue
                connectors.append(Connector(
                    element_id,
                    _number(child.get("x1")) + cdx, _number(child.get("y1")) + cdy,
                    _number(child.get("x2")) + cdx, _number(child.get("y2")) + cdy,
                    child.get("stroke"), _number(child.get("stroke-width"), 1.0),
                    _marker_requested(child.get("marker-start")),
                    _marker_requested(child.get("marker-end")),
                    child_node, child.get("data-from"), child.get("data-to"),
                    role))
            elif tag in ("polygon", "polyline"):
                points = tuple((px + cdx, py + cdy)
                               for px, py in _parse_points(child.get("points", "")))
                if tag == "polygon":
                    polygons.append(Polygon(
                        element_id, points, child.get("fill"), child_node,
                        child.get("stroke"), role))
                elif not _is_connector(child):
                    continue
                else:
                    # Only the two ends of a routed connector are attachment
                    # points. Giving every segment both node ids made each
                    # corner of an elbow report `connector-port-drift` for a
                    # port it was never meant to touch.
                    segments = list(zip(points, points[1:]))
                    for position, (start, end) in enumerate(segments):
                        connectors.append(Connector(
                            element_id, start[0], start[1], end[0], end[1],
                            child.get("stroke"),
                            _number(child.get("stroke-width"), 1.0),
                            _marker_requested(child.get("marker-start")),
                            _marker_requested(child.get("marker-end")),
                            child_node,
                            child.get("data-from") if position == 0 else None,
                            (child.get("data-to")
                             if position == len(segments) - 1 else None),
                            role))
            else:
                walk(child, child_node, child_role, cdx, cdy, index)

    walk(root, None, None, 0.0, 0.0, [0])
    return Scene(width, height, tuple(boxes), tuple(texts),
                 tuple(connectors), tuple(polygons), font_family,
                 tuple(paths), backgrounds[-1] if backgrounds else None)


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
