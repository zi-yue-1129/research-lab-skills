"""connector.py — line/polyline/polygon connectors with anchor binding."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from lxml import etree
from pptx.util import Emu, Pt
from pptx.oxml.ns import qn

from .style_parser import (apply_alpha, apply_dash, apply_line_ends,
                           resolve_color)
from .converter import CoordSystem, _local_tag

_ANCHOR_RECT = [
    (0.0, 0.0, 0),
    (0.5, 0.0, 1),
    (1.0, 0.0, 2),
    (1.0, 0.5, 3),
    (1.0, 1.0, 4),
    (0.5, 1.0, 5),
    (0.0, 1.0, 6),
    (0.0, 0.5, 7),
]
_ANCHOR_OVAL = [
    (0.5, 0.0, 1),
    (1.0, 0.5, 3),
    (0.5, 1.0, 5),
    (0.0, 0.5, 7),
]
THRESHOLD = 10.0


def dispatch_connector(slide: Any, elem: Any, style: Dict,
                       cs: CoordSystem) -> List[Any]:
    tag = _local_tag(elem)
    if tag == "line":
        x1 = float(elem.get("x1", 0))
        y1 = float(elem.get("y1", 0))
        x2 = float(elem.get("x2", 0))
        y2 = float(elem.get("y2", 0))
        conn = _add_line(slide, cs.x(x1), cs.y(y1), cs.x(x2), cs.y(y2), style)
        apply_line_ends(conn, style)
        return [conn]
    elif tag in ("polyline", "polygon"):
        pts = _parse_points(elem.get("points", ""))
        closed = tag == "polygon"
        connectors = []
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            connectors.append(_add_line(slide, cs.x(x1), cs.y(y1), cs.x(x2), cs.y(y2), style))
        if closed and len(pts) >= 3:
            x1, y1 = pts[-1]
            x2, y2 = pts[0]
            connectors.append(_add_line(slide, cs.x(x1), cs.y(y1), cs.x(x2), cs.y(y2), style))
        if connectors and not closed:
            # A polyline is one connector drawn as many segments; only its two
            # ends carry arrowheads. Applying them inside `_add_line` would put
            # one at every bend of every elbow connector on the slide. A closed
            # polygon has no ends at all, so a marker on it declares nothing.
            apply_line_ends(connectors[0], style, head=True, tail=False)
            apply_line_ends(connectors[-1], style, head=False, tail=True)
        return connectors
    return []


def _add_line(slide: Any, x1: int, y1: int, x2: int, y2: int,
              style: Dict) -> Any:
    conn = slide.shapes.add_connector(1, Emu(x1), Emu(y1), Emu(x2), Emu(y2))
    stroke = style.get("stroke", "none")
    rgb = resolve_color(stroke)
    if rgb:
        conn.line.color.rgb = rgb
    width_raw = style.get("stroke-width", "1.5")
    try:
        conn.line.width = Pt(float(width_raw))
    except ValueError:
        conn.line.width = Pt(1.5)
    apply_dash(conn, style)
    apply_alpha(conn, style)
    return conn


def _parse_points(pts_str: str) -> List[Tuple[float, float]]:
    nums = [float(n) for n in pts_str.replace(",", " ").split() if n]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def build_anchor_map(
    shapes_info: List[Tuple[Any, float, float, float, float, int]]
) -> Dict[int, List[Tuple[float, float, int]]]:
    result: Dict[int, List[Tuple[float, float, int]]] = {}
    for shape_elem, sx, sy, sw, sh, sp_id in shapes_info:
        tag = _local_tag(shape_elem) if shape_elem is not None else "rect"
        template = _ANCHOR_OVAL if tag in ("circle", "ellipse") else _ANCHOR_RECT
        anchors = []
        for fx, fy, idx in template:
            anchors.append((sx + fx * sw, sy + fy * sh, idx))
        result[sp_id] = anchors
    return result


def bind_connector_end(connector: Any, is_begin: bool,
                       shape_sp_id: int, anchor_idx: int) -> None:
    cxnSp = connector._element
    nvCxnSpPr = cxnSp.find(qn("p:nvCxnSpPr"))
    cNvCxnSpPr = nvCxnSpPr.find(qn("p:cNvCxnSpPr"))
    if cNvCxnSpPr is None:
        cNvCxnSpPr = etree.SubElement(nvCxnSpPr, qn("p:cNvCxnSpPr"))
    tag = qn("a:stCxn") if is_begin else qn("a:endCxn")
    existing = cNvCxnSpPr.find(tag)
    if existing is not None:
        cNvCxnSpPr.remove(existing)
    cxn = etree.SubElement(cNvCxnSpPr, tag)
    cxn.set("id", str(shape_sp_id))
    cxn.set("idx", str(anchor_idx))
