#!/usr/bin/env python3
"""diagram_builder.py -- compose dense technical architecture diagrams.

Hand-authoring a diagram at the density a paper or design review expects means
computing a few hundred coordinates. Doing that twice produced the same defect
both times: a box guessed slightly too narrow for the label it holds, invisible
until the deck was exported and measured.

This module removes the guessing. Every box is sized from the *measured* width
of the text it contains, so a node cannot be too small for its label -- its size
is derived from the label. Coordinates snap to `canvas.grid`, colours come from
`color.roles`, surfaces from `surfaces.*`, and connectors bind to named ports on
real nodes, so off-grid placement, palette drift and dangling connectors are
unrepresentable rather than merely discouraged.

Structure is recursive, which is what carries the density: a **band** is a
horizontal strip of the slide, a **section** is a titled dashed container inside
a band, and a section holds either nodes or further titled groups, flowing in a
row or a column. Nesting a group inside a section is how a diagram shows the
internals of one block without leaving the page it belongs to.

Beyond plain nodes there are three primitives that dense diagrams need and
generic ones do not: an **operator** (a small circle carrying an arithmetic
glyph, for residual adds and gates), an **ellipsis** (for a repeated block whose
copies are not worth drawing), and **over/under** routing (a connector that arcs
clear of the blocks between its ends rather than through them).

What this does not do is decide composition. Which blocks exist, how they nest,
and which band they occupy stay with the author -- that is the part carrying
meaning, and automating it would produce diagrams that are correct and say
nothing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import fonts

#: Node kinds and the surface/accent each maps to. Kinds carry meaning, so a
#: diagram states what a block *is* rather than picking a colour: `data` for
#: tensors and files, `module` for learned or executable components, `accent`
#: for the component a section is about, and `aux` for anything active only in
#: one regime -- a training-only branch, an optional path -- which a legend
#: then explains once.
KINDS: Dict[str, Dict[str, str]] = {
    "data": {"surface": "bg", "border": "muted"},
    "module": {"surface": "card", "border": "line"},
    "accent": {"surface": "card", "border": "primary"},
    "aux": {"surface": "bg", "border": "warn"},
}

#: Width PowerPoint reserves inside a shape's text frame, in canvas units. Its
#: default inset is 0.1in each side -- 14.4pt over a 960pt slide mapped onto a
#: 1200-unit canvas. Reserving it is why a node sized from measured text still
#: holds that text once exported; without it the rendered-deck gate reported
#: labels finishing outside their boxes by 2 to 13pt.
_PPTX_TEXT_INSET = 18

#: Safety margin over the derived render scale, for the small differences
#: between these metrics and PowerPoint's own layout of the same string.
_RENDER_SAFETY = 1.04



def _snap(value: float, grid: int, *, up: bool = True) -> int:
    """Round a coordinate onto the token grid.

    Args:
        value: The raw coordinate or length.
        grid: The grid quantum from `canvas.grid`.
        up: Round away from zero, so a size derived from measured text is never
            rounded down into the text it has to hold.

    Returns:
        The snapped integer.
    """
    return int((math.ceil if up else math.floor)(value / grid) * grid)


@dataclass
class Node:
    """One block, operator, or ellipsis placed in a flow."""

    id: str
    lines: List[str]
    shape: Optional[str] = None
    kind: str = "module"
    role: str = "node"
    glyph: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    @property
    def right(self) -> int:
        """Right edge."""
        return self.x + self.width

    @property
    def bottom(self) -> int:
        """Bottom edge."""
        return self.y + self.height

    @property
    def mid_x(self) -> int:
        """Horizontal centre."""
        return self.x + self.width // 2

    @property
    def mid_y(self) -> int:
        """Vertical centre."""
        return self.y + self.height // 2

    def port(self, side: str) -> Tuple[int, int]:
        """Return the attachment point on one side.

        Connectors bind to ports rather than free coordinates, which is what
        makes a dangling or drifted connector impossible to author.

        Args:
            side: `left`, `right`, `top` or `bottom`.

        Returns:
            The `(x, y)` of that side's midpoint.

        Raises:
            ValueError: If the side is not one of the four.
        """
        sides = {
            "left": (self.x, self.mid_y),
            "right": (self.right, self.mid_y),
            "top": (self.mid_x, self.y),
            "bottom": (self.mid_x, self.bottom),
        }
        if side not in sides:
            raise ValueError(f"unknown port side: {side!r}")
        return sides[side]


@dataclass
class Container:
    """A titled dashed box holding nodes or further containers.

    Attributes:
        id: Stable identifier, prefixed onto the ids of what it holds.
        title: Caption at the top-left, or empty for an untitled grouping.
        flow: `row` lays children left to right, `column` top to bottom.
        children: Nodes and nested containers, in flow order.
        band: Which horizontal strip of the slide this sits in. Meaningful only
            on a top-level section.
        rows: How the children were wrapped at measurement time, so placement
            follows the same breaks rather than recomputing them.
    """

    id: str
    title: str
    flow: str = "column"
    children: List[Union[Node, "Container"]] = field(default_factory=list)
    band: Optional[int] = None
    rows: List[List[Union[Node, "Container"]]] = field(default_factory=list)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


Item = Union[Node, Container]


class Diagram:
    """Compose a token-compliant architecture diagram and emit it as SVG."""

    def __init__(
        self,
        tokens: Dict[str, Any],
        *,
        title: str,
        subtitle: str = "",
        footnote: str = "",
    ) -> None:
        """Initialize a diagram bound to one token set.

        Args:
            tokens: The parsed design-token mapping.
            title: Slide title.
            subtitle: Optional line under the title.
            footnote: Optional line along the bottom.
        """
        self.t = tokens
        self.title = title
        self.subtitle = subtitle
        self.footnote = footnote
        self.grid: int = tokens["canvas"]["grid"]
        self.canvas_w: int = tokens["canvas"]["width"]
        self.canvas_h: int = tokens["canvas"]["height"]
        self.safe = tokens["canvas"]["safe_area"]
        self.colors: Dict[str, str] = tokens["color"]["roles"]
        self.node_pad = tokens["spacing"]["node_padding"]
        self.gap: int = _snap(tokens["spacing"]["node_gap_min"], self.grid)
        self.family = fonts.resolve_font_stack(tokens["typography"]["family"]["sans"])
        self.label_role = tokens["typography"]["roles"]["node_label"]
        self.caption_role = tokens["typography"]["roles"]["caption"]
        self.render_scale = self._render_scale()
        # Line advance and annotation room come from the type roles rather
        # than from constants: a denser token set with a smaller scale would
        # otherwise be drawn with the leading of a presentation slide, and the
        # boxes would be padded out with air the smaller type does not need.
        self.line_step = _snap(
            self.label_role["size"] * self.label_role["line_height"], self.grid
        )
        self.shape_step = _snap(
            self.caption_role["size"] * self.caption_role["line_height"], self.grid
        )
        # Large enough that the glyph clears the token insets on every side.
        self.op_size = _snap(
            max(
                self.label_role["size"] + 2 * self.node_pad["x"],
                self.label_role["size"] + 2 * self.node_pad["y"],
            )
            + self.grid,
            self.grid,
        )
        self.sections: List[Container] = []
        #: Sections grouped by slide, then by band, filled during layout.
        self.slides: List[List[List[Container]]] = []
        self.connections: List[Dict[str, Any]] = []
        self.notes: List[Dict[str, Any]] = []

    def _render_scale(self) -> float:
        """How much wider text renders in the deck than on this canvas.

        `svg_to_pptx` passes an SVG `font-size` through as points rather than
        scaling it by the canvas-to-slide ratio, so text set at 18 units on a
        1200-unit canvas arrives as 18pt on a 960pt slide -- 1.25x larger than
        the layout here assumes. Sizing boxes without accounting for it left
        labels finishing outside their shapes, which the rendered-deck gate
        caught and these metrics alone could not.

        Derived rather than hardcoded, so a later change to that mapping is
        picked up instead of leaving a stale constant behind.

        Returns:
            The factor to widen measured text by, never below 1.
        """
        from svg_to_pptx.converter import PPTX_W, CoordSystem

        points_per_unit = (PPTX_W / 12700) / self.canvas_w
        # The converter scales a declared size against its 1200-unit reference,
        # so the two factors together are what a label actually renders at.
        # Asking the converter keeps this correct on any canvas rather than
        # baking in the ratio of one.
        emitted = CoordSystem(self.canvas_w, self.canvas_h).font_scale()
        return max(1.0, emitted / points_per_unit)

    # --- authoring ------------------------------------------------------

    def section(
        self, ident: str, title: str, *, band: Optional[int] = None,
        flow: str = "column"
    ) -> Container:
        """Add a top-level titled container.

        Args:
            ident: Stable identifier.
            title: Caption.
            band: Horizontal strip to pin this section to. Leave it None -- the
                usual case -- and sections fill bands automatically in
                declaration order, so the author states what the figure
                contains and not where it packs.
            flow: `column` or `row`.

        Returns:
            The new section.
        """
        c = Container(id=ident, title=title, flow=flow, band=band)
        self.sections.append(c)
        return c

    def group(
        self, parent: Container, ident: str, title: str = "", *, flow: str = "row"
    ) -> Container:
        """Nest a titled container inside another.

        Args:
            parent: The container to nest inside.
            ident: Identifier, unique within the parent.
            title: Caption, or empty for an untitled grouping.
            flow: `row` or `column`.

        Returns:
            The new group.
        """
        c = Container(id=f"{parent.id}-{ident}", title=title, flow=flow)
        parent.children.append(c)
        return c

    def node(
        self,
        parent: Container,
        ident: str,
        lines: Sequence[str],
        *,
        shape: Optional[str] = None,
        kind: str = "module",
    ) -> Node:
        """Add a block.

        Args:
            parent: The container to place it in.
            ident: Identifier, unique within the parent.
            lines: Label lines, one per line. Lines after the first are set in
                the caption role, which is where a block's parameters go -- and
                that detail is most of what makes a diagram dense.
            shape: Optional tensor-shape annotation beneath the label.
            kind: One of `KINDS`.

        Returns:
            The new node.

        Raises:
            ValueError: If the kind is unknown, since a typo would otherwise
                paint a block in a semantic colour that says nothing.
        """
        if kind not in KINDS:
            raise ValueError(
                f"unknown node kind {kind!r}; expected one of {sorted(KINDS)}"
            )
        n = Node(id=f"{parent.id}-{ident}", lines=list(lines), shape=shape, kind=kind)
        parent.children.append(n)
        return n

    def op(self, parent: Container, ident: str, glyph: str) -> Node:
        """Add an operator: a small circle carrying an arithmetic glyph.

        Args:
            parent: The container to place it in.
            ident: Identifier.
            glyph: The symbol, such as `+` for a residual add or `x` for a gate.

        Returns:
            The operator node.
        """
        n = Node(id=f"{parent.id}-{ident}", lines=[], role="operator", glyph=glyph)
        parent.children.append(n)
        return n

    def ellipsis(self, parent: Container, ident: str = "more") -> Node:
        """Add a repeated-block ellipsis.

        Drawing every copy of a repeated block spends the reader's attention on
        the repetition rather than on what repeats.

        Args:
            parent: The container to place it in.
            ident: Identifier.

        Returns:
            The ellipsis node.
        """
        n = Node(id=f"{parent.id}-{ident}", lines=[], role="ellipsis")
        parent.children.append(n)
        return n

    def connect(
        self,
        source: Node,
        target: Node,
        *,
        label: str = "",
        style: str = "solid",
        route: str = "auto",
        kind: str = "line",
    ) -> None:
        """Join two nodes port to port.

        Args:
            source: Node the arrow leaves.
            target: Node the arrow enters.
            label: Optional text along the connector.
            style: A key of `connectors.dash_patterns`.
            route: `auto` picks a straight run when the ports align and an elbow
                otherwise; `over` and `under` arc clear of everything between
                the two ends, which is what a skip or identity path needs.
            kind: `line`, or `aux` to draw it in the training-only accent.
        """
        self.connections.append(
            {"source": source, "target": target, "label": label,
             "style": style, "route": route, "kind": kind, "lane": None}
        )

    def note(self, text: str, x: int, y: int, *, color: str = "muted") -> None:
        """Place a free annotation, such as a legend line.

        Args:
            text: The annotation.
            x: Left coordinate, snapped to the grid.
            y: Baseline, snapped to the grid.
            color: A key of `color.roles`.
        """
        self.notes.append({"text": text, "x": _snap(x, self.grid),
                           "y": _snap(y, self.grid), "color": color})

    # --- measurement ----------------------------------------------------

    def _text_width(self, text: str, role: Dict[str, Any]) -> float:
        """Measure one string in a type role.

        Args:
            text: The string.
            role: A `typography.roles` entry.

        Returns:
            Advance width in canvas units.
        """
        return fonts.text_width(text, self.family, role["size"], role["weight"])

    def _measure(self, item: Item, max_width: Optional[int] = None) -> Tuple[int, int]:
        """Compute an item's size, wrapping a row that will not fit.

        Sizes are derived bottom-up: a node from its text, a container from its
        children. Nothing is guessed at any level.

        A row wider than the space it has is **wrapped into several rows**
        rather than reported as an error. Composing this by hand meant a dozen
        rounds of "48 units too wide" followed by trimming a label, which is
        work the tool can do and the author should not have to: the author is
        describing an architecture, not packing boxes.

        Args:
            item: A node or container.
            max_width: Width available to it, or None for unconstrained.

        Returns:
            Its `(width, height)`.
        """
        if isinstance(item, Node):
            return self._measure_node(item)

        title_room = 32 if item.title else 0
        inner_limit = None if max_width is None else max_width - self.gap * 2
        sizes = [self._measure(child, inner_limit) for child in item.children]

        if item.flow == "row":
            item.rows = self._wrap(item.children, sizes, inner_limit)
            widths = [
                sum(c.width for c in row) + self.gap * (len(row) - 1)
                for row in item.rows
            ]
            heights = [max(c.height for c in row) for row in item.rows]
            inner_w = max(widths)
            inner_h = sum(heights) + self.gap * (len(heights) - 1)
        else:
            item.rows = [[child] for child in item.children]
            inner_w = max(w for w, _ in sizes)
            inner_h = sum(h for _, h in sizes) + self.gap * (len(sizes) - 1)

        item.width = _snap(inner_w + self.gap * 2, self.grid)
        item.height = _snap(inner_h + self.gap * 2 + title_room, self.grid)
        return item.width, item.height

    def _wrap(
        self, children: Sequence[Item], sizes: Sequence[Tuple[int, int]],
        limit: Optional[int],
    ) -> List[List[Item]]:
        """Break a row into as many rows as its width demands.

        Args:
            children: The row's children, in flow order.
            sizes: Their measured sizes, positionally matched.
            limit: Width available, or None to keep one row.

        Returns:
            The children grouped into rows, order preserved so the reading
            sequence survives the wrap.
        """
        if limit is None:
            return [list(children)]
        rows: List[List[Item]] = [[]]
        used = 0
        for child, (width, _) in zip(children, sizes):
            addition = width if not rows[-1] else width + self.gap
            if rows[-1] and used + addition > limit:
                rows.append([child])
                used = width
            else:
                rows[-1].append(child)
                used += addition
        return rows

    def _measure_node(self, node: Node) -> Tuple[int, int]:
        """Size one node from the text it must hold.

        Args:
            node: The node to size.

        Returns:
            Its `(width, height)`.
        """
        if node.role == "operator":
            node.width = node.height = self.op_size
            return node.width, node.height
        if node.role == "ellipsis":
            # Sized from its glyph plus the token insets, for the same reason an
            # operator circle is: it is a shape holding text, so `node-padding`
            # is measured on it.
            glyph = self._text_width("• • •", self.label_role)
            node.width = _snap(
                glyph * self.render_scale + 2 * self.node_pad["x"] + _PPTX_TEXT_INSET,
                self.grid,
            )
            node.height = self.op_size
            return node.width, node.height

        label_widths = [self._text_width(node.lines[0], self.label_role)] if node.lines else [0.0]
        detail_widths = [self._text_width(t, self.caption_role) for t in node.lines[1:]]
        if node.shape:
            detail_widths.append(self._text_width(node.shape, self.caption_role))
        widest = max(label_widths + detail_widths + [0.0])
        node.width = _snap(
            widest * self.render_scale * _RENDER_SAFETY
            + 2 * self.node_pad["x"]
            + _PPTX_TEXT_INSET,
            self.grid,
        )
        height = 2 * self.node_pad["y"] + self.line_step * len(node.lines)
        if node.shape:
            height += self.shape_step
        node.height = _snap(max(height, self.line_step * 2 + 8), self.grid)
        return node.width, node.height

    # --- placement ------------------------------------------------------

    def _place(self, item: Item, x: int, y: int) -> None:
        """Assign absolute positions, following the wrap chosen at measurement.

        Children are centred on the cross axis of the row they landed in, so a
        row of differing heights shares one centre line rather than sitting on
        a ragged top edge.

        Args:
            item: The node or container to place.
            x: Left coordinate.
            y: Top coordinate.
        """
        item.x, item.y = x, y
        if isinstance(item, Node):
            return

        title_room = 32 if item.title else 0
        cy = y + self.gap + title_room
        span_w = item.width - self.gap * 2

        for row in item.rows:
            row_h = max(child.height for child in row)
            row_w = sum(child.width for child in row) + self.gap * (len(row) - 1)
            cx = x + self.gap + max(0, _snap((span_w - row_w) / 2, self.grid, up=False))
            for child in row:
                offset = max(0, _snap((row_h - child.height) / 2, self.grid, up=False))
                self._place(child, cx, cy + offset)
                cx += child.width + self.gap
            cy += row_h + self.gap

    def layout(self) -> None:
        """Measure every section and assign each to a slide and a band.

        A section is measured against the usable width, so an over-long row
        wraps rather than overflowing. Sections then fill bands greedily in
        declaration order, and **bands that no longer fit the canvas continue
        onto the next slide** -- because this is a deck generator, and an
        architecture too detailed for one page is a normal outcome for real
        research rather than an error to hand back.

        An explicit `band` still pins a section to a band on the first slide,
        for the cases where the author does want to control the packing.

        Raises:
            ValueError: Only when a single section is itself taller than a whole
                canvas, which no packing or paging can recover.
        """
        usable = self.canvas_w - self.safe["left"] - self.safe["right"]
        for section in self.sections:
            self._measure(section, usable)

        content_top = _snap(self.safe["top"] + 92, self.grid)
        content_bottom = self.canvas_h - self.safe["bottom"] - (
            24 if self.footnote else 0
        )
        available = content_bottom - content_top

        for section in self.sections:
            if section.height > available:
                raise ValueError(
                    f"section {section.id!r} is {section.height - available} units "
                    "taller than a whole canvas on its own; shorten its labels or "
                    "split it into two sections"
                )

        self.slides = [[]]
        band: List[Container] = []
        used_height = 0
        for section in sorted(
            self.sections, key=lambda s: (s.band is None, s.band or 0)
        ):
            row_w = sum(s.width for s in band) + self.gap * len(band)
            fits_band = band and row_w + section.width <= usable
            if fits_band:
                band.append(section)
                continue
            # Close the current band and start a new one, paging when the slide
            # has no room left for it.
            if band:
                used_height += max(s.height for s in band) + self.gap
            if used_height + section.height > available:
                self.slides.append([])
                used_height = 0
            band = [section]
            self.slides[-1].append(band)

        self._position()

    def _position(self) -> None:
        """Place every section from its slide and band assignment."""
        top_start = _snap(self.safe["top"] + 92, self.grid)
        for bands in self.slides:
            top = top_start
            for band in bands:
                x = self.safe["left"]
                for section in band:
                    self._place(section, x, top)
                    x += section.width + self.gap
                top += max(s.height for s in band) + self.gap

    # --- emission -------------------------------------------------------

    def _route(self, conn: Dict[str, Any]) -> List[Tuple[int, int]]:
        """Compute a connector's path between two node ports.

        Args:
            conn: One entry from `self.connections`.

        Returns:
            The polyline points: two for a straight run, four for an elbow or
            for an arc that clears what lies between the ends.
        """
        s, t = conn["source"], conn["target"]
        if conn["route"] in ("over", "under"):
            side = "top" if conn["route"] == "over" else "bottom"
            sp, tp = s.port(side), t.port(side)
            # Just clear of the nodes, not clear of everything: a taller lane
            # bought nothing and cost enough height to split the figure across
            # an extra slide. `connector_clearance_min` is the floor it has to
            # beat, and a container's title sits above this.
            reach = max(
                self.grid * 2,
                int(self.t["spacing"]["connector_clearance_min"]) + self.grid,
            )
            lane = (min(sp[1], tp[1]) - reach if conn["route"] == "over"
                    else max(sp[1], tp[1]) + reach)
            conn["lane"] = lane
            return [sp, (sp[0], lane), (tp[0], lane), tp]

        rightward = t.x >= s.right
        downward = t.y >= s.bottom
        sp = s.port("right" if rightward else "bottom" if downward else "left")
        tp = t.port("left" if rightward else "top" if downward else "right")
        if conn["route"] == "straight" or (
            conn["route"] == "auto" and (sp[1] == tp[1] or sp[0] == tp[0])
        ):
            return [sp, tp]
        if rightward:
            mid = _snap((sp[0] + tp[0]) / 2, self.grid, up=False)
            return [sp, (mid, sp[1]), (mid, tp[1]), tp]
        mid = _snap((sp[1] + tp[1]) / 2, self.grid, up=False)
        return [sp, (sp[0], mid), (tp[0], mid), tp]

    def to_svg(self, index: int = 0) -> str:
        """Render one slide of the composed diagram as SVG.

        Args:
            index: Which slide, zero-based. Call `layout` first, or use
                `write`, which handles paging for you.

        Returns:
            The complete document for that slide.
        """
        c = self.colors
        stack = self.t["typography"]["family"]["sans"]
        title_role = self.t["typography"]["roles"]["slide_title"]
        out = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {self.canvas_w} {self.canvas_h}" font-family="{stack}">',
            f"  <desc>{self.title}. {self.subtitle}</desc>",
            f'  <rect x="0" y="0" width="{self.canvas_w}" height="{self.canvas_h}" '
            f'fill="{c["bg"]}"/>',
            f'  <text x="{self.safe["left"]}" y="{self.safe["top"] + 48}" '
            f'font-size="{title_role["size"]}" font-weight="{title_role["weight"]}" '
            f'fill="{c["primary"]}">{self._slide_title(index)}</text>',
        ]
        if self.subtitle:
            out.append(
                f'  <text x="{self.safe["left"]}" y="{self.safe["top"] + 78}" '
                f'font-size="{self.caption_role["size"]}" fill="{c["muted"]}">'
                f"{self.subtitle}</text>"
            )
        on_slide = {s.id for band in self.slides[index] for s in band}
        for band in self.slides[index]:
            for section in band:
                out.extend(self._container_svg(section, depth=0))
        out.extend(self._connectors_svg(on_slide))
        for note in self.notes:
            out.append(
                f'  <text x="{note["x"]}" y="{note["y"]}" '
                f'font-size="{self.caption_role["size"]}" '
                f'fill="{c[note["color"]]}">{note["text"]}</text>'
            )
        if self.footnote:
            out.append(
                f'  <text x="{self.safe["left"]}" '
                f'y="{self.canvas_h - self.safe["bottom"] - 4}" '
                f'font-size="{self.caption_role["size"]}" fill="{c["muted"]}">'
                f"{self.footnote}</text>"
            )
        out.append("</svg>")
        return "\n".join(out) + "\n"

    def _slide_title(self, index: int) -> str:
        """Title for one slide, numbered only when the figure needed paging.

        Args:
            index: Zero-based slide index.

        Returns:
            The title, suffixed with "(2 of 3)" and so on when relevant.
        """
        if len(self.slides) == 1:
            return self.title
        return f"{self.title}  ({index + 1} of {len(self.slides)})"

    def _container_svg(self, box: Container, *, depth: int) -> List[str]:
        """Emit a container and everything inside it.

        Args:
            box: The placed container.
            depth: Nesting depth. A nested group is drawn in a lighter, tighter
                dash so a reader can tell an inner grouping from an outer one
                without either competing with the blocks themselves.

        Returns:
            SVG lines.
        """
        c = self.colors
        dash = "8 4" if depth == 0 else "4 3"
        stroke = c["divider"] if depth == 0 else c["muted"]
        out = [
            f'  <rect x="{box.x}" y="{box.y}" width="{box.width}" '
            f'height="{box.height}" rx="8" fill="none" stroke="{stroke}" '
            f'stroke-width="1.5" stroke-dasharray="{dash}"/>'
        ]
        if box.title:
            out.append(
                f'  <text x="{box.x + 16}" y="{box.y + 26}" '
                f'font-size="{self.caption_role["size"]}" font-weight="600" '
                f'fill="{c["muted"]}">{box.title}</text>'
            )
        for child in box.children:
            if isinstance(child, Container):
                out.extend(self._container_svg(child, depth=depth + 1))
            else:
                out.extend(self._node_svg(child))
        return out

    def _node_svg(self, n: Node) -> List[str]:
        """Emit one node, operator, or ellipsis.

        Args:
            n: The placed node.

        Returns:
            SVG lines.
        """
        c = self.colors
        if n.role == "ellipsis":
            # The glyph needs a shape of its own. A bare `<text>` inside a
            # section was adopted by that section's boundary rect on export and
            # arrived as a second line of its title -- present in the file,
            # invisible where it belonged.
            return [
                f'  <g data-pptx-role="group" data-node-id="{n.id}">',
                f'    <rect x="{n.x}" y="{n.y}" width="{n.width}" '
                f'height="{n.height}" fill="{c["bg"]}" stroke="none"/>',
                f'    <text x="{n.mid_x}" y="{n.mid_y + self.label_role["size"] // 2}" '
                f'text-anchor="middle" font-size="{self.label_role["size"]}" '
                f'font-weight="700" fill="{c["muted"]}">• • •</text>',
                "  </g>",
            ]
        if n.role == "operator":
            return [
                f'  <g data-pptx-role="group" data-node-id="{n.id}">',
                f'    <circle cx="{n.mid_x}" cy="{n.mid_y}" r="{n.width // 2}" '
                f'fill="{c["bg"]}" stroke="{c["line"]}" stroke-width="1.5"/>',
                f'    <text x="{n.mid_x}" y="{n.mid_y + self.label_role["size"] // 2 - 2}" text-anchor="middle" '
                f'font-size="{self.label_role["size"]}" font-weight="700" fill="{c["line"]}">'
                f"{n.glyph}</text>",
                "  </g>",
            ]

        kind = KINDS[n.kind]
        surface = self.t["surfaces"]["node"]
        first = n.y + self.node_pad["y"] + self.label_role["size"]
        tx = n.x + self.node_pad["x"]
        out = [
            f'  <g data-pptx-role="group" data-node-id="{n.id}">',
            f'    <rect x="{n.x}" y="{n.y}" width="{n.width}" height="{n.height}" '
            f'rx="{surface["radius"]}" fill="{c[kind["surface"]]}" '
            f'stroke="{c[kind["border"]]}" stroke-width="{surface["border_width"]}"/>',
        ]
        for i, line in enumerate(n.lines):
            weight = self.label_role["weight"] if i == 0 else 400
            size = self.label_role["size"] if i == 0 else self.caption_role["size"]
            fill = c["body"] if i == 0 else c["muted"]
            out.append(
                f'    <text x="{tx}" y="{first + i * self.line_step}" '
                f'font-size="{size}" font-weight="{weight}" fill="{fill}">{line}</text>'
            )
        if n.shape:
            out.append(
                f'    <text x="{tx}" y="{first + len(n.lines) * self.line_step + 2}" '
                f'font-size="{self.caption_role["size"]}" fill="{c["muted"]}">'
                f"{n.shape}</text>"
            )
        out.append("  </g>")
        return out

    def _section_of(self, node: Node) -> str:
        """Return the id of the top-level section a node belongs to.

        Args:
            node: Any placed node.

        Returns:
            The section id, taken from the node id's first segment.
        """
        return node.id.split("-", 1)[0]

    def _connectors_svg(self, on_slide: Optional[set] = None) -> List[str]:
        """Emit the connectors whose two ends share this slide.

        A connector spanning a page break is omitted rather than drawn to a
        node that is not there. `spanning_connections` lists them, so the
        author can caption the join instead of silently losing it.

        Args:
            on_slide: Section ids present on the slide being rendered, or None
                to draw everything.

        Returns:
            SVG lines.
        """
        if not self.connections:
            return []
        c = self.colors
        dashes = self.t["connectors"]["dash_patterns"]
        width = self.t["connectors"]["stroke_width"]
        markers = "".join(
            f'<marker id="arrow-{name}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c[role]}"/></marker>'
            for name, role in (("line", "line"), ("aux", "warn"))
        )
        out = [f"  <defs>{markers}</defs>"]
        for conn in self.connections:
            if on_slide is not None and not {
                self._section_of(conn["source"]), self._section_of(conn["target"])
            } <= on_slide:
                continue
            pts = self._route(conn)
            stroke = c["warn"] if conn["kind"] == "aux" else c["line"]
            dash = dashes.get(conn["style"], "")
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            coords = " ".join(f"{x},{y}" for x, y in pts)
            # `data-from`/`data-to` state which nodes the connector joins. The
            # scene parser reads them directly, so an elbow's interior corners
            # -- which touch nothing by construction -- are not mistaken for
            # dangling ends, and the intent is recorded rather than inferred.
            out.append(
                f'  <polyline points="{coords}" fill="none" stroke="{stroke}" '
                f'stroke-width="{width}"{dash_attr} '
                f'data-from="{conn["source"].id}" data-to="{conn["target"].id}" '
                f'marker-end="url(#arrow-{conn["kind"]})"/>'
            )
            if conn["label"]:
                mx = (pts[0][0] + pts[-1][0]) // 2
                if conn["lane"] is not None:
                    # Sit on the lane the route already cleared. Placing the
                    # label at the path's extreme instead put a band-crossing
                    # connector's caption up inside the band above it.
                    my = (conn["lane"] - self.grid if conn["route"] == "over"
                          else conn["lane"] + self.caption_role["size"])
                else:
                    my = min(p[1] for p in pts) - self.caption_role["size"]
                out.append(
                    f'  <text x="{mx}" y="{my}" text-anchor="middle" '
                    f'font-size="{self.caption_role["size"]}" '
                    f'fill="{c["muted"]}">{conn["label"]}</text>'
                )
        return out

    def spanning_connections(self) -> List[Tuple[str, str]]:
        """Connections whose ends landed on different slides.

        Returns:
            `(source id, target id)` pairs that could not be drawn, so a caller
            can caption them rather than lose them silently.
        """
        where = {
            section.id: index
            for index, bands in enumerate(self.slides)
            for band in bands
            for section in band
        }
        spanning = []
        for conn in self.connections:
            a = where.get(self._section_of(conn["source"]))
            b = where.get(self._section_of(conn["target"]))
            if a is not None and b is not None and a != b:
                spanning.append((conn["source"].id, conn["target"].id))
        return spanning

    def write(self, path: Path) -> List[Path]:
        """Write the diagram, paging onto extra slides when it does not fit.

        Args:
            path: Destination for the first slide. Later slides take the same
                stem with an incrementing number, matching the `slide*.svg`
                names the converter looks for.

        Returns:
            Every path written, in order.
        """
        self.layout()
        path = Path(path)
        written = []
        for index in range(len(self.slides)):
            target = (
                path if index == 0
                else path.with_name(f"slide-{index + 1:02d}{path.suffix}")
            )
            target.write_text(self.to_svg(index), encoding="utf-8")
            written.append(target)
        return written
