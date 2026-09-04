"""path_to_pptx.py — Convert normalized path commands to PPTX shapes."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree
from pptx.util import Emu

from .converter import CoordSystem
from .style_parser import apply_alpha, apply_dash, apply_fill, apply_stroke

_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def add_path_shape(slide: Any, commands: List[Tuple],
                   cs: CoordSystem, style: Dict) -> Optional[Any]:
    if not commands:
        return None
    expanded = _expand_arcs(commands)
    xs, ys = _all_coords(expanded)
    if not xs:
        return None
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    x_emu = cs.x(min_x)
    y_emu = cs.y(min_y)
    w_emu = max(1, cs.x(max_x) - x_emu)
    h_emu = max(1, cs.y(max_y) - y_emu)
    shape = _build_custgeom(slide, expanded, cs, x_emu, y_emu, w_emu, h_emu)
    if shape is None:
        return None
    apply_fill(shape, style.get("fill", "none"))
    apply_stroke(shape, style)
    apply_dash(shape, style)
    apply_alpha(shape, style)
    return shape


def _expand_arcs(commands: List[Tuple]) -> List[Tuple]:
    result: List[Tuple] = []
    prev_x, prev_y = 0.0, 0.0
    for cmd in commands:
        if cmd[0] == 'A':
            rx, ry, phi, large, sweep, ex, ey = cmd[1:]
            segs = arc_to_beziers(prev_x, prev_y, rx, ry, phi, large, sweep, ex, ey)
            for cp1, cp2, end in segs:
                result.append(('C', cp1[0], cp1[1], cp2[0], cp2[1], end[0], end[1]))
            prev_x, prev_y = ex, ey
        else:
            result.append(cmd)
            if cmd[0] in ('M', 'L', 'C', 'Q'):
                prev_x, prev_y = cmd[-2], cmd[-1]
    return result


def _all_coords(commands: List[Tuple]) -> Tuple[List[float], List[float]]:
    xs: List[float] = []
    ys: List[float] = []
    for cmd in commands:
        if cmd[0] in ('M', 'L'):
            xs.append(cmd[1]); ys.append(cmd[2])
        elif cmd[0] == 'C':
            xs += [cmd[1], cmd[3], cmd[5]]
            ys += [cmd[2], cmd[4], cmd[6]]
        elif cmd[0] == 'Q':
            xs += [cmd[1], cmd[3]]
            ys += [cmd[2], cmd[4]]
    return xs, ys


def _build_custgeom(slide: Any, commands: List[Tuple],
                    cs: CoordSystem, x_emu: int, y_emu: int,
                    w_emu: int, h_emu: int) -> Optional[Any]:
    from pptx.oxml.ns import qn
    shape = slide.shapes.add_shape(1, Emu(x_emu), Emu(y_emu), Emu(w_emu), Emu(h_emu))
    sp = shape._element
    spPr = sp.find(qn("p:spPr"))

    prstGeom = spPr.find(f"{{{_A_NS}}}prstGeom")
    if prstGeom is not None:
        spPr.remove(prstGeom)

    cg = etree.SubElement(spPr, f"{{{_A_NS}}}custGeom")
    for sub in ("avLst", "gdLst", "ahLst", "cxnLst"):
        etree.SubElement(cg, f"{{{_A_NS}}}{sub}")
    rect_el = etree.SubElement(cg, f"{{{_A_NS}}}rect")
    rect_el.set("l", "0"); rect_el.set("t", "0")
    rect_el.set("r", "r"); rect_el.set("b", "b")
    pathLst = etree.SubElement(cg, f"{{{_A_NS}}}pathLst")
    path = etree.SubElement(pathLst, f"{{{_A_NS}}}path")
    path.set("w", str(w_emu)); path.set("h", str(h_emu))

    def pt(parent: Any, svg_x: float, svg_y: float) -> Any:
        p = etree.SubElement(parent, f"{{{_A_NS}}}pt")
        p.set("x", str(cs.x(svg_x) - x_emu))
        p.set("y", str(cs.y(svg_y) - y_emu))
        return p

    for cmd in commands:
        if cmd[0] == 'M':
            mo = etree.SubElement(path, f"{{{_A_NS}}}moveTo")
            pt(mo, cmd[1], cmd[2])
        elif cmd[0] == 'L':
            ln = etree.SubElement(path, f"{{{_A_NS}}}lnTo")
            pt(ln, cmd[1], cmd[2])
        elif cmd[0] == 'C':
            bz = etree.SubElement(path, f"{{{_A_NS}}}cubicBezTo")
            pt(bz, cmd[1], cmd[2]); pt(bz, cmd[3], cmd[4]); pt(bz, cmd[5], cmd[6])
        elif cmd[0] == 'Q':
            bz = etree.SubElement(path, f"{{{_A_NS}}}quadBezTo")
            pt(bz, cmd[1], cmd[2]); pt(bz, cmd[3], cmd[4])
        elif cmd[0] == 'Z':
            etree.SubElement(path, f"{{{_A_NS}}}close")

    return shape


def arc_to_beziers(x1: float, y1: float, rx: float, ry: float,
                   phi_deg: float, large_arc: int, sweep: int,
                   x2: float, y2: float) -> List[Tuple]:
    if x1 == x2 and y1 == y2:
        return []
    if rx == 0 or ry == 0:
        return [((x2, y2), (x2, y2), (x2, y2))]

    phi = math.radians(phi_deg)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    dx = (x1 - x2) / 2.0
    dy = (y1 - y2) / 2.0
    x1p = cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy

    rx = abs(rx); ry = abs(ry)
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1.0:
        sq = math.sqrt(lam)
        rx *= sq; ry *= sq

    num = max(0.0, (rx * ry) ** 2 - (rx * y1p) ** 2 - (ry * x1p) ** 2)
    den = (rx * y1p) ** 2 + (ry * x1p) ** 2
    sq = math.sqrt(num / den) if den != 0 else 0.0
    if large_arc == sweep:
        sq = -sq

    cxp = sq * rx * y1p / ry
    cyp = -sq * ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2.0

    def _angle(ux: float, uy: float, vx: float, vy: float) -> float:
        n = math.sqrt(ux * ux + uy * uy) * math.sqrt(vx * vx + vy * vy)
        if n == 0:
            return 0.0
        c = max(-1.0, min(1.0, (ux * vx + uy * vy) / n))
        a = math.acos(c)
        return -a if (ux * vy - uy * vx) < 0 else a

    theta1 = _angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = _angle((x1p - cxp) / rx, (y1p - cyp) / ry,
                    (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    n_segs = max(1, math.ceil(abs(dtheta) / (math.pi / 2)))
    d_seg = dtheta / n_segs
    alpha = 4.0 / 3.0 * math.tan(d_seg / 4.0)

    result = []
    for seg in range(n_segs):
        t1 = theta1 + seg * d_seg
        t2 = theta1 + (seg + 1) * d_seg
        sx = cx + rx * math.cos(t1) * cos_phi - ry * math.sin(t1) * sin_phi
        sy = cy + rx * math.cos(t1) * sin_phi + ry * math.sin(t1) * cos_phi
        ex = cx + rx * math.cos(t2) * cos_phi - ry * math.sin(t2) * sin_phi
        ey = cy + rx * math.cos(t2) * sin_phi + ry * math.sin(t2) * cos_phi
        dx1 = -rx * math.sin(t1) * cos_phi - ry * math.cos(t1) * sin_phi
        dy1 = -rx * math.sin(t1) * sin_phi + ry * math.cos(t1) * cos_phi
        dx2 = -rx * math.sin(t2) * cos_phi - ry * math.cos(t2) * sin_phi
        dy2 = -rx * math.sin(t2) * sin_phi + ry * math.cos(t2) * cos_phi
        cp1 = (sx + alpha * dx1, sy + alpha * dy1)
        cp2 = (ex - alpha * dx2, ey - alpha * dy2)
        result.append((cp1, cp2, (ex, ey)))

    return result
