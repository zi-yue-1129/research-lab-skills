"""converter.py — orchestration layer for SVG → native PPTX conversion."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree
from pptx import Presentation
from pptx.util import Emu

PPTX_W = 12_192_000
PPTX_H = 6_858_000
_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_CANVAS_TOLERANCE = 1e-6


@dataclass
class CoordSystem:
    svg_w: float
    svg_h: float

    def x(self, v: float) -> int:
        return round(float(v) / self.svg_w * PPTX_W)

    def y(self, v: float) -> int:
        return round(float(v) / self.svg_h * PPTX_H)

    @classmethod
    def from_viewbox(cls, viewbox: str) -> "CoordSystem":
        parts = viewbox.strip().split()
        if len(parts) == 4:
            try:
                return cls(svg_w=float(parts[2]), svg_h=float(parts[3]))
            except ValueError:
                pass
        return cls(svg_w=1200.0, svg_h=675.0)


def _local_tag(elem: Any) -> str:
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    return tag.split("}")[-1] if "}" in tag else tag


class SvgConverter:
    """Converts one SVG file into one PPTX slide."""

    def __init__(self, svg_path: str, verbose: bool = False) -> None:
        self.svg_path = svg_path
        self.verbose = verbose
        tree = etree.parse(svg_path)
        self.root = tree.getroot()
        vb = self.root.get("viewBox", "0 0 1200 675")
        self.cs = CoordSystem.from_viewbox(vb)
        self._shape_labels: Dict[int, List[Any]] = {}
        self._text_to_shape: Dict[int, Any] = {}
        self._defs: Dict[str, Any] = {}
        self._connector_registry: List = []
        self._shape_registry: List = []
        self._pending_texts: List = []
        self._group_collect: Optional[List[Any]] = None

    def convert(self, prs: Presentation, slide_layout: Any) -> Any:
        self._connector_registry = []
        self._shape_registry = []
        self._shape_labels = {}
        self._text_to_shape = {}
        self._pending_texts = []
        self._group_collect = None
        slide = prs.slides.add_slide(slide_layout)
        self._resolve_defs()
        self._resolve_use_elements()
        self._compute_text_attachments()
        self._dispatch_children(slide, self.root, {})
        # Add all text boxes after shapes so they appear on top
        from .text_converter import add_textbox
        for text_elem, text_style in self._pending_texts:
            add_textbox(slide, text_elem, text_style, self.cs)
        self._bind_connectors(slide)
        return slide

    def _resolve_defs(self) -> None:
        for elem in self.root.iter():
            if _local_tag(elem) == "defs":
                for child in elem:
                    eid = child.get("id")
                    if eid:
                        self._defs[eid] = child

    def _resolve_use_elements(self) -> None:
        from copy import deepcopy
        for use_elem in list(self.root.iter()):
            if _local_tag(use_elem) != "use":
                continue
            href = use_elem.get("href") or use_elem.get(
                "{http://www.w3.org/1999/xlink}href", "")
            if not href.startswith("#"):
                continue
            ref_id = href[1:]
            ref = self._defs.get(ref_id)
            if ref is None:
                continue
            clone = deepcopy(ref)
            use_x = use_elem.get("x", "0")
            use_y = use_elem.get("y", "0")
            if use_x != "0" or use_y != "0":
                existing = clone.get("transform", "")
                clone.set("transform",
                          f"translate({use_x},{use_y}) {existing}".strip())
            parent = use_elem.getparent()
            if parent is not None:
                idx = list(parent).index(use_elem)
                parent.insert(idx, clone)
                parent.remove(use_elem)

    def _compute_text_attachments(self) -> None:
        """Attach text to the smallest semantic shape containing its baseline.

        A full-canvas rectangle is commonly emitted as a rendering background.
        It remains a native PPTX shape, but is deliberately excluded from this
        semantic attachment pass so labels outside smaller shapes stay editable
        standalone textboxes. Positions are still conservatively based on the
        SVG ``x``/``y`` attributes; transformed text is not inferred here.
        """
        shape_bboxes: List[Tuple[Any, float, float, float, float]] = []
        for elem in self.root.iter():
            tag = _local_tag(elem)
            try:
                if tag == "rect":
                    x = float(elem.get("x", 0))
                    y = float(elem.get("y", 0))
                    w = float(elem.get("width", 0))
                    h = float(elem.get("height", 0))
                    if self._is_canvas_background(x, y, w, h):
                        continue
                    shape_bboxes.append((elem, x, y, w, h))
                elif tag == "circle":
                    cx = float(elem.get("cx", 0))
                    cy = float(elem.get("cy", 0))
                    r = float(elem.get("r", 0))
                    shape_bboxes.append((elem, cx - r, cy - r, 2 * r, 2 * r))
                elif tag == "ellipse":
                    cx = float(elem.get("cx", 0))
                    cy = float(elem.get("cy", 0))
                    rx = float(elem.get("rx", 0))
                    ry = float(elem.get("ry", 0))
                    shape_bboxes.append((elem, cx - rx, cy - ry, 2 * rx, 2 * ry))
            except ValueError:
                pass

        for text_elem in self.root.iter():
            if _local_tag(text_elem) != "text":
                continue
            try:
                tx = float(text_elem.get("x", 0))
                ty = float(text_elem.get("y", 0))
            except ValueError:
                continue
            candidates = []
            for shape_elem, sx, sy, sw, sh in shape_bboxes:
                if sx <= tx <= sx + sw and sy <= ty <= sy + sh:
                    candidates.append((sw * sh, shape_elem))
            if not candidates:
                continue
            candidates.sort(key=lambda c: c[0])
            best_shape = candidates[0][1]
            self._shape_labels.setdefault(id(best_shape), []).append(text_elem)
            self._text_to_shape[id(text_elem)] = best_shape

    def _is_canvas_background(self, x: float, y: float,
                              width: float, height: float) -> bool:
        """Return whether a rectangle covers the converter's SVG canvas.

        The tolerance absorbs harmless decimal serialization noise while
        keeping rectangles that are materially smaller than the viewBox
        eligible as semantic text containers.
        """
        return all(
            math.isclose(value, expected, rel_tol=1e-9,
                         abs_tol=_CANVAS_TOLERANCE)
            for value, expected in (
                (x, 0.0),
                (y, 0.0),
                (width, self.cs.svg_w),
                (height, self.cs.svg_h),
            )
        )

    def _dispatch_children(self, slide: Any, parent: Any, inherited: Dict) -> None:
        from .style_parser import compute_style
        for elem in parent:
            tag = _local_tag(elem)
            try:
                style = compute_style(elem, inherited)
                self._dispatch_element(slide, elem, style)
            except Exception as exc:
                if self.verbose:
                    print(f"  [warn] {tag}: {exc}")

    def _dispatch_element(self, slide: Any, elem: Any, style: Dict) -> None:
        tag = _local_tag(elem)
        if tag in ("rect", "circle", "ellipse", "image"):
            from .shapes import dispatch_shape
            shape = dispatch_shape(
                slide, elem, style, self.cs, self._shape_labels.get(id(elem))
            )
            if shape is not None and self._group_collect is not None:
                self._group_collect.append(shape)
            if shape is not None and tag in ("rect", "circle", "ellipse"):
                try:
                    if tag == "rect":
                        bx = float(elem.get("x", 0))
                        by = float(elem.get("y", 0))
                        bw = float(elem.get("width", 0))
                        bh = float(elem.get("height", 0))
                    elif tag == "circle":
                        cx = float(elem.get("cx", 0))
                        cy = float(elem.get("cy", 0))
                        r = float(elem.get("r", 0))
                        bx, by, bw, bh = cx - r, cy - r, 2 * r, 2 * r
                    else:
                        cx = float(elem.get("cx", 0))
                        cy = float(elem.get("cy", 0))
                        rx = float(elem.get("rx", 0))
                        ry = float(elem.get("ry", 0))
                        bx, by, bw, bh = cx - rx, cy - ry, 2 * rx, 2 * ry
                    self._shape_registry.append((elem, bx, by, bw, bh, shape.shape_id))
                except Exception:
                    pass
        elif tag == "text":
            if id(elem) not in self._text_to_shape:
                self._pending_texts.append((elem, style))
        elif tag in ("line", "polyline", "polygon"):
            from .connector import dispatch_connector
            conns = dispatch_connector(slide, elem, style, self.cs)
            self._connector_registry.extend(
                [(conn, elem) for conn in conns]
            )
            if self._group_collect is not None:
                self._group_collect.extend(conns)
        elif tag == "path":
            from .path_parser import parse_path
            from .path_to_pptx import add_path_shape
            d = elem.get("d", "")
            if d:
                path_shape = add_path_shape(slide, parse_path(d), self.cs, style)
                if path_shape is not None and self._group_collect is not None:
                    self._group_collect.append(path_shape)
        elif tag == "g":
            role = elem.get("data-pptx-role")
            if role in ("table", "chart"):
                self._dispatch_native_data(slide, elem, role)
            elif role == "group":
                self._dispatch_native_group(slide, elem, style)
            else:
                self._dispatch_children(slide, elem, style)

    def _bind_connectors(self, slide: Any) -> None:
        from .connector import build_anchor_map
        if not self._connector_registry or not self._shape_registry:
            return
        anchor_map = build_anchor_map(self._shape_registry)
        for conn, conn_elem in self._connector_registry:
            tag = _local_tag(conn_elem)
            if tag == "line":
                try:
                    begin_pt = (float(conn_elem.get("x1", 0)), float(conn_elem.get("y1", 0)))
                    end_pt = (float(conn_elem.get("x2", 0)), float(conn_elem.get("y2", 0)))
                    _try_bind(conn, begin_pt, end_pt, anchor_map)
                except Exception:
                    pass

    def _dispatch_native_data(self, slide: Any, elem: Any, role: str) -> None:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import pptx_native

        source = elem.get("data-pptx-source")
        bbox_raw = elem.get("data-pptx-bbox")
        if not source or not bbox_raw:
            raise ValueError(
                f'data-pptx-role="{role}" requires both data-pptx-source and '
                f"data-pptx-bbox (svg={self.svg_path})"
            )
        data = self._load_pptx_source(source)
        bx, by, bw, bh = (float(v) for v in bbox_raw.split(","))
        bbox = (self.cs.x(bx), self.cs.y(by), self.cs.x(bw), self.cs.y(bh))
        style = self._pptx_style(elem)

        if role == "table":
            pptx_native.add_native_table(
                slide, data["columns"], data["rows"], bbox, style,
                highlight_col=data.get("highlight_col"),
            )
            return

        chart_type = {"bar_chart": "bar", "line_chart": "line",
                     "pie_chart": "pie"}.get(data.get("type"), "bar")
        if chart_type == "pie":
            series = [{"label": data.get("title", ""), "values": data.get("values", [])}]
            pptx_native.add_native_chart(
                slide, "pie", data["categories"], series, bbox, style,
                colors=data.get("colors"),
            )
        else:
            pptx_native.add_native_chart(
                slide, chart_type, data["categories"], data["series"], bbox,
                style, y_max=data.get("y_max"),
            )

    def _dispatch_native_group(self, slide: Any, elem: Any, inherited_style: Dict) -> None:
        from .style_parser import compute_style
        from .text_converter import add_textbox

        collected: List[Any] = []
        previous_sink = self._group_collect
        self._group_collect = collected
        local_texts: List = []
        try:
            for child in elem:
                tag = _local_tag(child)
                style = compute_style(child, inherited_style)
                if tag == "text" and id(child) not in self._text_to_shape:
                    local_texts.append((child, style))
                    continue
                self._dispatch_element(slide, child, style)
            for text_elem, text_style in local_texts:
                box = add_textbox(slide, text_elem, text_style, self.cs)
                if box is not None:
                    collected.append(box)
        finally:
            self._group_collect = previous_sink

        if len(collected) >= 2:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            import pptx_native
            pptx_native.add_native_group(slide, collected)

    def _load_pptx_source(self, source: str) -> Dict[str, Any]:
        import json
        from pathlib import Path
        base_dir = Path(self.svg_path).resolve().parent
        if "#" in source:
            filename, _, index_str = source.partition("#")
            payload = json.loads((base_dir / filename).read_text(encoding="utf-8"))
            target_index = int(index_str)
            for entry in payload.get("slides", []):
                if entry.get("index") == target_index:
                    return entry
            raise ValueError(f"slide index {target_index} not found in {filename}")
        return json.loads((base_dir / source).read_text(encoding="utf-8"))

    def _pptx_style(self, elem: Any) -> Dict[str, str]:
        """Resolve the color/font style for a native table or chart.

        Prefers an explicit ``data-pptx-style`` JSON attribute (the SVG
        producer's already-resolved style values, so custom project styles
        carry through); falls back to generate_slides.py's built-in
        defaults when absent.
        """
        import json
        defaults = {
            "accent": "#1e3a5f", "white": "#ffffff", "card": "#f8fafc",
            "bg": "#ffffff", "body": "#374151", "good": "#059669",
            "danger": "#dc2626", "font": "'Helvetica Neue', Arial, sans-serif",
        }
        raw = elem.get("data-pptx-style")
        if not raw:
            return defaults
        try:
            overrides = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return defaults
        merged = dict(defaults)
        merged.update({k: v for k, v in overrides.items() if v})
        return merged


def _try_bind(conn: Any, begin_pt: tuple, end_pt: tuple, anchor_map: Dict) -> None:
    import math
    from .connector import THRESHOLD, bind_connector_end
    for is_begin, pt in [(True, begin_pt), (False, end_pt)]:
        best_dist = float("inf")
        best_sp_id = None
        best_idx = None
        for sp_id, anchors in anchor_map.items():
            for ax, ay, aidx in anchors:
                d = math.hypot(pt[0] - ax, pt[1] - ay)
                if d < best_dist:
                    best_dist = d
                    best_sp_id = sp_id
                    best_idx = aidx
        if best_dist <= THRESHOLD and best_sp_id is not None:
            bind_connector_end(conn, is_begin, best_sp_id, best_idx)


def convert_file(slides_dir: str, out_path: str, verbose: bool = False) -> None:
    prs = Presentation()
    prs.slide_width = Emu(PPTX_W)
    prs.slide_height = Emu(PPTX_H)
    layout = prs.slide_layouts[6]

    svg_files = sorted(Path(slides_dir).glob("slide*.svg"))
    if not svg_files:
        raise ValueError(f"No slide*.svg files found in {slides_dir}")

    for svg_path in svg_files:
        conv = SvgConverter(str(svg_path), verbose=verbose)
        conv.convert(prs, layout)
        if verbose:
            print(f"  + {svg_path.name}")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    prs.save(out_path)
    print(f"\n{len(svg_files)} slide(s) → {out_path}")
