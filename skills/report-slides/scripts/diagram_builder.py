#!/usr/bin/env python3
"""diagram_builder.py -- compose dense technical architecture diagrams.

Hand-authoring an architecture diagram at the density a paper or design review
expects -- nested boundaries, tensor shapes under every block, multi-line
operator descriptions, elbow-routed connectors, repeated-block ellipsis -- means
computing a few hundred coordinates by hand. Doing that produced two rounds of
defects in practice, both of the same kind: a box guessed slightly too narrow
for the label it holds, caught only after export by measuring the rendered deck.

The fix is not more care. It is to stop guessing: this module sizes every box
from the *measured* width of the text it contains, using the same font metrics
the style linter checks against. A node cannot be too small for its label,
because its size is derived from the label.

Everything else follows the same principle. Coordinates snap to `canvas.grid`,
so nothing lands off-grid. Colours come from `color.roles` and surfaces from
`surfaces.*`, so no palette drift is possible. Connectors attach to named ports
on real nodes, so none can dangle. The token file is the single source of
truth, exactly as `references/diagram-patterns.md` requires.

What this does not do is decide composition. Which blocks exist, how they group,
and which column and row each occupies stay with the author -- that is the part
that carries meaning, and automating it would produce diagrams that are correct
and say nothing.

Usage sketch:

    d = Diagram(tokens, title="...", subtitle="...")
    enc = d.boundary("encoder", "1. Encoding", column=0)
    x = enc.node("x", ["Input frames"], shape="(B, T, 3, H, W)", kind="data")
    e = enc.node("e", ["Encoder", "Conv × 4, stride 2"], shape="(B, T, 512)")
    d.connect(x, e)
    d.write("slide-01.svg")
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import fonts

#: Node kinds and the surface/accent each maps to. Kinds carry meaning, so a
#: diagram states what a block *is* rather than picking a colour: `data` for
#: tensors and files, `module` for learned or executable components, `accent`
#: for the component a section is about, and `aux` for anything active only in
#: one regime (training-only branches, optional paths), which a legend explains.
KINDS: Dict[str, Dict[str, str]] = {
    "data": {"surface": "bg", "border": "muted"},
    "module": {"surface": "card", "border": "line"},
    "accent": {"surface": "card", "border": "primary"},
    "aux": {"surface": "bg", "border": "warn"},
}

#: Extra height per label line beyond the first, and the vertical room a shape
#: annotation needs under the label.
_LINE_STEP = 22
_SHAPE_STEP = 20

#: Width PowerPoint reserves inside a shape's text frame, in canvas units.
#: Its default inset is 0.1in on each side -- 14.4pt over a 960pt slide mapped
#: onto a 1200-unit canvas. Reserving it here is why a node sized from measured
#: text still holds that text once exported; a guessed safety factor did not,
#: and the rendered-deck gate reported five labels finishing outside their
#: boxes by 2 to 13pt.
_PPTX_TEXT_INSET = 18

#: Safety margin on top of the derived render scale, for the small differences
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
    """One block: a box, its label lines, and an optional shape annotation."""

    id: str
    lines: List[str]
    shape: Optional[str]
    kind: str
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
    def mid_y(self) -> int:
        """Vertical centre."""
        return self.y + self.height // 2

    @property
    def mid_x(self) -> int:
        """Horizontal centre."""
        return self.x + self.width // 2

    def port(self, side: str) -> Tuple[int, int]:
        """Return the attachment point on one side.

        Connectors bind to ports rather than to free coordinates, which is what
        makes a dangling or drifted connector impossible to author.

        Args:
            side: `left`, `right`, `top` or `bottom`.

        Returns:
            The `(x, y)` of that side's midpoint.

        Raises:
            ValueError: If the side is not one of the four.
        """
        if side == "left":
            return self.x, self.mid_y
        if side == "right":
            return self.right, self.mid_y
        if side == "top":
            return self.mid_x, self.y
        if side == "bottom":
            return self.mid_x, self.bottom
        raise ValueError(f"unknown port side: {side!r}")


@dataclass
class Boundary:
    """A labelled dashed container holding nodes, laid out in one column."""

    id: str
    title: str
    nodes: List[Node] = field(default_factory=list)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


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
        self.node_gap: int = tokens["spacing"]["node_gap_min"]
        self.family = fonts.resolve_font_stack(
            tokens["typography"]["family"]["sans"]
        )
        self.label_role = tokens["typography"]["roles"]["node_label"]
        self.render_scale = self._render_scale()
        self.caption_role = tokens["typography"]["roles"]["caption"]
        self.boundaries: List[Boundary] = []
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
        picked up instead of silently leaving a stale constant behind.

        Returns:
            The factor to widen measured text by, never below 1.
        """
        from svg_to_pptx.converter import PPTX_W

        points_per_unit = (PPTX_W / 12700) / self.canvas_w
        return max(1.0, 1.0 / points_per_unit)

    # --- authoring ------------------------------------------------------

    def boundary(self, ident: str, title: str) -> Boundary:
        """Add a labelled container. Containers lay out left to right.

        Args:
            ident: Stable identifier, used for node ids.
            title: The container's caption.

        Returns:
            The new boundary.
        """
        b = Boundary(id=ident, title=title)
        self.boundaries.append(b)
        return b

    def node(
        self,
        boundary: Boundary,
        ident: str,
        lines: Sequence[str],
        *,
        shape: Optional[str] = None,
        kind: str = "module",
    ) -> Node:
        """Add a block to a container.

        Args:
            boundary: The container to place it in.
            ident: Identifier, unique within the boundary.
            lines: Label lines, rendered one per line.
            shape: Optional tensor-shape annotation shown beneath the label.
            kind: One of `KINDS`, which decides surface and accent.

        Returns:
            The new node.

        Raises:
            ValueError: If the kind is unknown -- a typo would otherwise paint
                a block in the wrong semantic colour and say nothing about it.
        """
        if kind not in KINDS:
            raise ValueError(
                f"unknown node kind {kind!r}; expected one of {sorted(KINDS)}"
            )
        n = Node(id=f"{boundary.id}-{ident}", lines=list(lines), shape=shape, kind=kind)
        boundary.nodes.append(n)
        return n

    def connect(
        self,
        source: Node,
        target: Node,
        *,
        label: str = "",
        style: str = "solid",
        route: str = "auto",
    ) -> None:
        """Join two nodes port to port.

        Args:
            source: Node the arrow leaves.
            target: Node the arrow enters.
            label: Optional text along the connector.
            style: A key of `connectors.dash_patterns`.
            route: `auto` picks a straight line when the ports share an axis and
                an elbow otherwise; `straight` and `elbow` force one.
        """
        self.connections.append(
            {"source": source, "target": target, "label": label,
             "style": style, "route": route}
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

    # --- measurement and layout ----------------------------------------

    def _text_width(self, text: str, role: Dict[str, Any]) -> float:
        """Measure one string in a type role.

        Args:
            text: The string.
            role: A `typography.roles` entry.

        Returns:
            Advance width in canvas units.
        """
        return fonts.text_width(text, self.family, role["size"], role["weight"])

    def _size_node(self, node: Node) -> None:
        """Derive a node's box from the text it must hold.

        This is the whole point of the module: the box cannot be too small for
        its label, because the label determines the box. A generous allowance is
        added on top of the token padding because PowerPoint lays text out
        slightly wider than these metrics predict, and it insets the text frame
        -- measured on a real deck, a label that fitted by 6.7pt here still
        finished 8pt outside its shape once rendered.

        Args:
            node: The node to size.
        """
        widest = max(
            [self._text_width(line, self.label_role) for line in node.lines]
            + ([self._text_width(node.shape, self.caption_role)] if node.shape else [0.0])
        )
        content = (
            widest * self.render_scale * _RENDER_SAFETY
            + 2 * self.node_pad["x"]
            + _PPTX_TEXT_INSET
        )
        node.width = _snap(content, self.grid)

        height = 2 * self.node_pad["y"] + _LINE_STEP * len(node.lines)
        if node.shape:
            height += _SHAPE_STEP
        node.height = _snap(max(height, 48), self.grid)

    def _column_gap(self) -> int:
        """Width of every empty column between boundaries.

        One width for all of them, not one per gap. A connector label sits
        centred in a gap, so the widest label sets the distance -- the same
        principle that sizes a node from its own text. Varying the gap per
        column would fit each label individually and read as uneven rhythm,
        which is exactly what the linter's `spacing-variance` check reports.

        Returns:
            The gap width, snapped to the grid.
        """
        labels = [c["label"] for c in self.connections if c["label"]]
        needed = max(
            [self._text_width(text, self.caption_role) for text in labels] + [0.0]
        )
        return _snap(max(self.node_gap * 2, needed + self.grid * 2), self.grid)

    def layout(self) -> None:
        """Place every boundary and node, snapped to the grid.

        Boundaries run left to right and are sized to their widest node; nodes
        stack top to bottom inside, separated by at least `spacing.node_gap_min`.

        Raises:
            ValueError: If the composition cannot fit the safe area, rather than
                silently producing a diagram that runs off the slide.
        """
        for b in self.boundaries:
            for n in b.nodes:
                self._size_node(n)

        pad = _snap(self.node_gap, self.grid)
        gap = self._column_gap()
        x = self.safe["left"]
        top = _snap(self.safe["top"] + 96, self.grid)
        bottom_limit = self.canvas_h - self.safe["bottom"] - 40

        for b in self.boundaries:
            inner = max(n.width for n in b.nodes)
            b.x, b.y = x, top
            b.width = inner + 2 * pad
            stack = sum(n.height for n in b.nodes) + pad * (len(b.nodes) - 1)
            b.height = _snap(stack + pad * 2 + 32, self.grid)

            ny = b.y + pad + 32
            for n in b.nodes:
                n.x = b.x + pad
                n.width = inner          # one width per column reads as a column
                n.y = ny
                ny += n.height + pad
            x = b.x + b.width + gap

        right = max(b.x + b.width for b in self.boundaries)
        if right > self.canvas_w - self.safe["right"]:
            raise ValueError(
                f"composition is {right - (self.canvas_w - self.safe['right'])} "
                "units wider than the safe area; use fewer columns or shorter labels"
            )
        deepest = max(b.y + b.height for b in self.boundaries)
        if deepest > bottom_limit:
            raise ValueError(
                f"composition is {deepest - bottom_limit} units taller than the "
                "safe area; use fewer rows per column"
            )

    # --- emission -------------------------------------------------------

    def _connector_points(self, conn: Dict[str, Any]) -> List[Tuple[int, int]]:
        """Compute a connector's path between two node ports.

        Args:
            conn: One entry from `self.connections`.

        Returns:
            Two points for a straight run, or four for an elbow.
        """
        s, t = conn["source"], conn["target"]
        rightward = t.x >= s.right
        sp = s.port("right" if rightward else "bottom")
        tp = t.port("left" if rightward else "top")
        if conn["route"] == "straight" or (
            conn["route"] == "auto" and (sp[1] == tp[1] or sp[0] == tp[0])
        ):
            return [sp, tp]
        mid = _snap((sp[0] + tp[0]) / 2, self.grid, up=False)
        return [sp, (mid, sp[1]), (mid, tp[1]), tp]

    def to_svg(self) -> str:
        """Render the composed diagram as SVG.

        Returns:
            The complete document.
        """
        self.layout()
        c = self.colors
        stack = self.t["typography"]["family"]["sans"]
        out: List[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {self.canvas_w} {self.canvas_h}" font-family="{stack}">',
            f"  <desc>{self.title}. {self.subtitle}</desc>",
            f'  <rect x="0" y="0" width="{self.canvas_w}" height="{self.canvas_h}" '
            f'fill="{c["bg"]}"/>',
        ]
        title_role = self.t["typography"]["roles"]["slide_title"]
        out.append(
            f'  <text x="{self.safe["left"]}" y="{self.safe["top"] + 52}" '
            f'font-size="{title_role["size"]}" font-weight="{title_role["weight"]}" '
            f'fill="{c["primary"]}">{self.title}</text>'
        )
        if self.subtitle:
            out.append(
                f'  <text x="{self.safe["left"]}" y="{self.safe["top"] + 86}" '
                f'font-size="{self.caption_role["size"]}" fill="{c["muted"]}">'
                f"{self.subtitle}</text>"
            )

        for b in self.boundaries:
            out.append(
                f'  <rect x="{b.x}" y="{b.y}" width="{b.width}" height="{b.height}" '
                f'rx="8" fill="none" stroke="{c["divider"]}" stroke-width="1.5" '
                f'stroke-dasharray="8 4"/>'
            )
            out.append(
                f'  <text x="{b.x + 16}" y="{b.y + 28}" '
                f'font-size="{self.caption_role["size"]}" font-weight="600" '
                f'fill="{c["muted"]}">{b.title}</text>'
            )
            for n in b.nodes:
                out.extend(self._node_svg(n))

        out.extend(self._connectors_svg())
        for note in self.notes:
            out.append(
                f'  <text x="{note["x"]}" y="{note["y"]}" '
                f'font-size="{self.caption_role["size"]}" '
                f'fill="{c[note["color"]]}">{note["text"]}</text>'
            )
        if self.footnote:
            out.append(
                f'  <text x="{self.safe["left"]}" '
                f'y="{self.canvas_h - self.safe["bottom"] - 8}" '
                f'font-size="{self.caption_role["size"]}" fill="{c["muted"]}">'
                f"{self.footnote}</text>"
            )
        out.append("</svg>")
        return "\n".join(out) + "\n"

    def _node_svg(self, n: Node) -> List[str]:
        """Emit one node as a native-group-marked box with its text.

        Args:
            n: The placed node.

        Returns:
            SVG lines.
        """
        c = self.colors
        kind = KINDS[n.kind]
        surface = self.t["surfaces"]["node"]
        first = n.y + self.node_pad["y"] + self.label_role["size"]
        lines = [f'  <g data-pptx-role="group" data-node-id="{n.id}">',
                 f'    <rect x="{n.x}" y="{n.y}" width="{n.width}" '
                 f'height="{n.height}" rx="{surface["radius"]}" '
                 f'fill="{c[kind["surface"]]}" stroke="{c[kind["border"]]}" '
                 f'stroke-width="{surface["border_width"]}"/>']
        tx = n.x + self.node_pad["x"]
        for i, line in enumerate(n.lines):
            lines.append(
                f'    <text x="{tx}" y="{first + i * _LINE_STEP}" '
                f'font-size="{self.label_role["size"]}" '
                f'font-weight="{self.label_role["weight"]}" '
                f'fill="{c["body"]}">{line}</text>'
            )
        if n.shape:
            lines.append(
                f'    <text x="{tx}" '
                f'y="{first + len(n.lines) * _LINE_STEP + 2}" '
                f'font-size="{self.caption_role["size"]}" '
                f'fill="{c["muted"]}">{n.shape}</text>'
            )
        lines.append("  </g>")
        return lines

    def _connectors_svg(self) -> List[str]:
        """Emit every connector plus the shared arrowhead marker.

        Returns:
            SVG lines.
        """
        if not self.connections:
            return []
        c = self.colors
        dashes = self.t["connectors"]["dash_patterns"]
        width = self.t["connectors"]["stroke_width"]
        out = [
            f'  <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c["line"]}"/></marker></defs>'
        ]
        for conn in self.connections:
            pts = self._connector_points(conn)
            dash = dashes.get(conn["style"], "")
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            coords = " ".join(f"{x},{y}" for x, y in pts)
            # `data-from`/`data-to` state which nodes the connector joins. The
            # scene parser reads them directly, so an elbow's interior corners
            # -- which touch nothing by construction -- cannot be mistaken for
            # dangling ends, and the intent is recorded rather than inferred
            # from pixel proximity.
            out.append(
                f'  <polyline points="{coords}" fill="none" stroke="{c["line"]}" '
                f'stroke-width="{width}"{dash_attr} '
                f'data-from="{conn["source"].id}" data-to="{conn["target"].id}" '
                f'marker-end="url(#arrow)"/>'
            )
            if conn["label"]:
                # Centred on the gap the label was measured into, so it cannot
                # land on a boundary it does not belong to.
                mx = (pts[0][0] + pts[-1][0]) // 2
                my = min(p[1] for p in pts) - 10
                out.append(
                    f'  <text x="{mx}" y="{my}" text-anchor="middle" '
                    f'font-size="{self.caption_role["size"]}" '
                    f'fill="{c["muted"]}">{conn["label"]}</text>'
                )
        return out

    def write(self, path: Path) -> Path:
        """Write the diagram to disk.

        Args:
            path: Destination `.svg`.

        Returns:
            The path written.
        """
        path = Path(path)
        path.write_text(self.to_svg(), encoding="utf-8")
        return path
