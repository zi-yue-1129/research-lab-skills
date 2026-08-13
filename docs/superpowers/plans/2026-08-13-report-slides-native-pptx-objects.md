# report-slides Native PPTX Objects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `report-slides` materialize real, editable PPTX table/chart/group objects for tables, bar/line/pie charts, timeline events, and complex architecture-diagram/flowchart nodes — instead of the flattened, disconnected SVG-derived shapes it produces today.

**Architecture:** Both existing SVG-authoring paths (the deterministic `generate_slides.py` and agent-authored SVG) keep producing the same hand-drawn preview markup for the Stage 9 vision-review gate, but now wrap the table/chart/node content in a `data-pptx-role` marker convention (`table`, `chart`, `group`). `scripts/svg_to_pptx/converter.py` — the sole native-shapes export entrypoint (`python3 -m svg_to_pptx`) — gets a new dispatch branch that recognizes these markers and calls a new `scripts/pptx_native.py` helper library to build real python-pptx `GraphicFrame` table/chart objects and `GroupShape` objects, instead of flattening the marked subtree into individual shapes. A new safety-net script, `validate_native_objects.py`, statically scans SVG for unmarked hand-drawn patterns and, post-conversion, scans the produced `.pptx` for the same patterns without an accompanying native construct.

**Tech Stack:** Python 3, `python-pptx>=0.6.21`, `lxml`, `pyyaml`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-08-13-report-slides-native-pptx-objects-design.md`

## Global Constraints

- Native materialization happens in exactly one place: `scripts/svg_to_pptx/converter.py`. `generate_slides.py`'s own `to_pptx()` and the top-level `to_pptx.py` are the unrelated SVG-embed fallback and are never touched by this plan.
- `data-pptx-bbox` is always `"x,y,w,h"` in the SVG's own user units (same coordinate system as every other SVG element in the file); `data-pptx-source` is either a sidecar JSON filename or `slide_data.json#<slide_index>` (the slide's own `index` field, not its array position).
- `pptx_construct` (manifest field: `native_table`/`native_chart`/`native_group`/`svg_shapes`) is additive and optional — its absence in an existing manifest is not a validation error.
- `validate_diagram_manifest.py` and the new `validate_native_objects.py` are CLI scripts with meaningful process exit codes (0 = pass, non-zero = hard blocker), invoked directly from `SKILL.md` prose and interpreted by the orchestrator agent — neither is a Python-level import into `presentation_evidence_gates.py`/`presentation_gates.py`, and this plan does not change that.
- Follow existing code conventions exactly: inline `from .module import name` imports inside functions (not module-level) throughout `svg_to_pptx/`; `Path(__file__).resolve().parent.parent` + `sys.path.insert(0, ...)` for cross-directory imports of top-level `scripts/` modules (mirrors `svg_to_pptx/__main__.py`); dataclass-based `ValidationIssue`/`Finding` result objects; `sorted(...)`/deterministic output ordering.

---

### Task 1: `scripts/pptx_native.py` — native table/chart/group construction

**Files:**
- Create: `skills/report-slides/scripts/pptx_native.py`
- Test: `skills/report-slides/scripts/tests/test_pptx_native.py`

**Interfaces:**
- Produces: `add_native_table(slide, columns: List[str], rows: List[List[Any]], bbox: Tuple[int,int,int,int], style: Dict[str,str], highlight_col: Optional[int] = None) -> GraphicFrame`
- Produces: `add_native_chart(slide, chart_type: str, categories: List[str], series: List[Dict[str,Any]], bbox: Tuple[int,int,int,int], style: Dict[str,str], y_max: Optional[float] = None, colors: Optional[List[str]] = None) -> GraphicFrame` (`chart_type` one of `"bar"`, `"line"`, `"pie"`; for `"pie"`, `series` has exactly one entry and `colors` supplies per-category slice colors)
- Produces: `add_native_group(slide, shapes: Sequence[Any]) -> Optional[GroupShape]` (returns `None` and groups nothing if `len(shapes) < 2`)

- [ ] **Step 1: Write the failing tests**

```python
# skills/report-slides/scripts/tests/test_pptx_native.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pptx import Presentation
from pptx.util import Emu

from pptx_native import add_native_table, add_native_chart, add_native_group

STYLE = {
    "accent": "#1e3a5f", "white": "#ffffff", "card": "#f8fafc",
    "bg": "#ffffff", "body": "#374151", "good": "#059669",
    "danger": "#dc2626", "font": "'Helvetica Neue', Arial, sans-serif",
}


def _new_slide():
    prs = Presentation()
    return prs.slides.add_slide(prs.slide_layouts[6])


def test_add_native_table_creates_real_table_with_header_and_rows():
    slide = _new_slide()
    frame = add_native_table(
        slide,
        columns=["Model", "QWK"],
        rows=[["GPT-4", "0.671"], ["ZH-BERT-FT", "0.828"]],
        bbox=(Emu(600000), Emu(750000), Emu(10800000), Emu(4500000)),
        style=STYLE,
    )
    assert frame.has_table
    table = frame.table
    assert len(table.rows) == 3
    assert len(table.columns) == 2
    assert table.cell(0, 0).text_frame.paragraphs[0].runs[0].text == "Model"
    assert table.cell(1, 0).text_frame.paragraphs[0].runs[0].text == "GPT-4"


def test_add_native_table_highlight_col_colors_plus_minus():
    slide = _new_slide()
    frame = add_native_table(
        slide,
        columns=["Model", "Delta"],
        rows=[["A", "+0.05"], ["B", "-0.03"]],
        bbox=(Emu(600000), Emu(750000), Emu(10800000), Emu(4500000)),
        style=STYLE,
        highlight_col=1,
    )
    table = frame.table
    good_run = table.cell(1, 1).text_frame.paragraphs[0].runs[0]
    danger_run = table.cell(2, 1).text_frame.paragraphs[0].runs[0]
    assert str(good_run.font.color.rgb) == "059669"
    assert str(danger_run.font.color.rgb) == "DC2626"


def test_add_native_chart_bar_creates_real_chart():
    slide = _new_slide()
    frame = add_native_chart(
        slide, "bar",
        categories=["Q1", "Q2"],
        series=[{"label": "EN", "color": "#1e3a5f", "values": [0.85, 0.83]}],
        bbox=(Emu(1200000), Emu(900000), Emu(9000000), Emu(4200000)),
        style=STYLE,
        y_max=1.0,
    )
    assert frame.has_chart
    chart = frame.chart
    assert list(chart.plots[0].categories) == ["Q1", "Q2"]
    assert len(chart.series) == 1


def test_add_native_chart_pie_colors_each_point():
    slide = _new_slide()
    frame = add_native_chart(
        slide, "pie",
        categories=["A", "B", "C"],
        series=[{"label": "Share", "values": [50, 30, 20]}],
        bbox=(Emu(1200000), Emu(900000), Emu(9000000), Emu(4200000)),
        style=STYLE,
        colors=["#ff0000", "#00ff00", "#0000ff"],
    )
    assert frame.has_chart
    points = frame.chart.series[0].points
    assert str(points[0].format.fill.fore_color.rgb) == "FF0000"
    assert str(points[2].format.fill.fore_color.rgb) == "0000FF"


def test_add_native_group_groups_two_or_more_shapes():
    slide = _new_slide()
    rect = slide.shapes.add_shape(1, Emu(0), Emu(0), Emu(100000), Emu(100000))
    oval = slide.shapes.add_shape(9, Emu(0), Emu(0), Emu(100000), Emu(100000))
    group = add_native_group(slide, [rect, oval])
    assert group is not None
    assert group.shape_type == 6  # MSO_SHAPE_TYPE.GROUP


def test_add_native_group_returns_none_for_single_shape():
    slide = _new_slide()
    rect = slide.shapes.add_shape(1, Emu(0), Emu(0), Emu(100000), Emu(100000))
    assert add_native_group(slide, [rect]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_pptx_native.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pptx_native'`

- [ ] **Step 3: Write the implementation**

```python
# skills/report-slides/scripts/pptx_native.py
"""pptx_native.py -- construct real PPTX table, chart, and group objects.

Used exclusively by svg_to_pptx/converter.py's data-pptx-role dispatch
branch, so both the deterministic Python renderer (generate_slides.py) and
agent-authored SVG materialize true native PowerPoint objects instead of
disconnected shapes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Pt

_DEFAULT_SERIES_COLORS = ("#3b82f6", "#059669", "#d97706", "#dc2626", "#8a2be2")


def _rgb(hex_value: Optional[str], fallback: str = "#000000") -> RGBColor:
    value = (hex_value or fallback).lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _font_family(css_font: str) -> str:
    first = css_font.split(",")[0].strip().strip("'\"")
    return first or "Calibri"


def add_native_table(
    slide: Any,
    columns: List[str],
    rows: List[List[Any]],
    bbox: Tuple[int, int, int, int],
    style: Dict[str, str],
    highlight_col: Optional[int] = None,
) -> Any:
    """Create a real PPTX table (``GraphicFrame.has_table``) at ``bbox`` (EMU)."""
    left, top, width, height = bbox
    n_cols = len(columns)
    n_rows = len(rows) + 1
    graphic_frame = slide.shapes.add_table(
        n_rows, n_cols, Emu(left), Emu(top), Emu(width), Emu(height)
    )
    table = graphic_frame.table
    table.first_row = False
    table.horz_banding = False

    header_fill = _rgb(style.get("accent"), "#1e3a5f")
    header_text = _rgb(style.get("white"), "#ffffff")
    card_fill = _rgb(style.get("card"), "#f8fafc")
    bg_fill = _rgb(style.get("bg"), "#ffffff")
    body_text = _rgb(style.get("body"), "#374151")
    good_text = _rgb(style.get("good"), "#059669")
    danger_text = _rgb(style.get("danger"), "#dc2626")
    font_name = _font_family(style.get("font", "Calibri"))

    for col_index, column_title in enumerate(columns):
        _set_cell_text(table.cell(0, col_index), str(column_title),
                       header_fill, header_text, font_name, bold=True)

    for row_index, row in enumerate(rows):
        fill = card_fill if row_index % 2 == 0 else bg_fill
        for col_index, value in enumerate(row):
            text_color = body_text
            cell_text = str(value)
            if highlight_col is not None and col_index == highlight_col:
                if "+" in cell_text:
                    text_color = good_text
                elif "-" in cell_text:
                    text_color = danger_text
            _set_cell_text(table.cell(row_index + 1, col_index), cell_text,
                           fill, text_color, font_name)

    return graphic_frame


def _set_cell_text(cell: Any, text: str, fill: RGBColor, text_color: RGBColor,
                   font_name: str, bold: bool = False) -> None:
    cell.fill.solid()
    cell.fill.fore_color.rgb = fill
    text_frame = cell.text_frame
    text_frame.clear()
    paragraph = text_frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = text
    run.font.size = Pt(13)
    run.font.bold = bold
    run.font.color.rgb = text_color
    if font_name:
        run.font.name = font_name


def add_native_chart(
    slide: Any,
    chart_type: str,
    categories: List[str],
    series: List[Dict[str, Any]],
    bbox: Tuple[int, int, int, int],
    style: Dict[str, str],
    y_max: Optional[float] = None,
    colors: Optional[List[str]] = None,
) -> Any:
    """Create a real PPTX chart (``GraphicFrame.has_chart``) at ``bbox`` (EMU).

    ``chart_type`` is one of "bar", "line", "pie". For "pie", ``series`` must
    contain exactly one entry and ``colors`` (one hex color per category) is
    used instead of per-series coloring.
    """
    left, top, width, height = bbox
    chart_data = CategoryChartData()
    chart_data.categories = categories
    for series_index, entry in enumerate(series):
        values = [float(v) for v in entry.get("values", [])]
        chart_data.add_series(entry.get("label", f"Series {series_index + 1}"), values)

    xl_type = {
        "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
        "line": XL_CHART_TYPE.LINE_MARKERS,
        "pie": XL_CHART_TYPE.PIE,
    }[chart_type]

    graphic_frame = slide.shapes.add_chart(
        xl_type, Emu(left), Emu(top), Emu(width), Emu(height), chart_data
    )
    chart = graphic_frame.chart
    chart.has_title = False
    chart.font.name = _font_family(style.get("font", "Calibri"))
    chart.has_legend = len(series) > 1 or chart_type == "pie"
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False

    if chart_type == "pie":
        point_colors = colors or [
            _DEFAULT_SERIES_COLORS[i % len(_DEFAULT_SERIES_COLORS)]
            for i in range(len(categories))
        ]
        for point_index, point in enumerate(chart.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = _rgb(point_colors[point_index])
    else:
        for series_index, (entry, chart_series) in enumerate(zip(series, chart.series)):
            color = entry.get("color") or _DEFAULT_SERIES_COLORS[
                series_index % len(_DEFAULT_SERIES_COLORS)
            ]
            if chart_type == "bar":
                chart_series.format.fill.solid()
                chart_series.format.fill.fore_color.rgb = _rgb(color)
            else:  # line
                chart_series.format.line.color.rgb = _rgb(color)
                chart_series.format.line.width = Pt(2.25)

    if y_max is not None and chart_type != "pie":
        chart.value_axis.maximum_scale = float(y_max)
        chart.value_axis.minimum_scale = 0.0

    return graphic_frame


def add_native_group(slide: Any, shapes: Sequence[Any]) -> Optional[Any]:
    """Group already-placed shapes into one native PPTX Group shape.

    Returns None (and groups nothing) for fewer than 2 shapes -- grouping a
    single shape has no PowerPoint-visible effect and is not a meaningful
    semantic unit for this design.
    """
    if len(shapes) < 2:
        return None
    return slide.shapes.add_group_shape(shapes)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_pptx_native.py -v`
Expected: PASS (all 6 tests). If any python-pptx API call in Step 3 raises `AttributeError`, check the installed `python-pptx` version's API for that call (e.g. `chart.font`, `points[i].format.fill`) and adjust — the tests, not this plan, are the source of truth for correctness.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/pptx_native.py skills/report-slides/scripts/tests/test_pptx_native.py
git commit -m "feat(report-slides): add pptx_native table/chart/group construction"
```

---

### Task 2: `references/native_object_thresholds.yaml` — detector configuration

**Files:**
- Create: `skills/report-slides/references/native_object_thresholds.yaml`

- [ ] **Step 1: Write the file**

```yaml
# Configurable heuristic thresholds for validate_native_objects.py's
# safety-net scan. These are deliberately loose -- the primary defense is
# the data-pptx-role authoring rule in SKILL.md Stage 9.1 and the worker
# agent instructions; this script only catches patterns the rule missed.
min_grid_rows: 2
min_grid_cols: 2
min_bar_count: 3
min_cluster_shapes: 2
position_tolerance_px: 2
```

- [ ] **Step 2: Commit**

```bash
git add skills/report-slides/references/native_object_thresholds.yaml
git commit -m "feat(report-slides): add native_object_thresholds.yaml"
```

---

### Task 3: `svg_to_pptx/converter.py` — `data-pptx-role` dispatch branch

**Files:**
- Modify: `skills/report-slides/scripts/svg_to_pptx/converter.py`
- Test: `skills/report-slides/scripts/svg_to_pptx/tests/test_native_roles.py`

**Interfaces:**
- Consumes: `pptx_native.add_native_table`, `pptx_native.add_native_chart`, `pptx_native.add_native_group` (Task 1)
- Produces: `SvgConverter._dispatch_native_data(slide, elem, role)`, `SvgConverter._dispatch_native_group(slide, elem, inherited_style)`, `SvgConverter._load_pptx_source(source: str) -> Dict[str, Any]`, `SvgConverter._pptx_style() -> Dict[str, str]` — consumed by Task 11's integration test and by any future SVG-source producer relying on the marker convention.

- [ ] **Step 1: Write the failing tests**

```python
# skills/report-slides/scripts/svg_to_pptx/tests/test_native_roles.py
import json
from pathlib import Path

from pptx import Presentation

from svg_to_pptx.converter import SvgConverter


def _write_svg(tmp_path: Path, body: str) -> Path:
    svg_path = tmp_path / "slide01_table.svg"
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">'
        f'{body}</svg>',
        encoding="utf-8",
    )
    return svg_path


def test_table_role_creates_native_table_and_skips_children(tmp_path: Path):
    (tmp_path / "table_data.json").write_text(json.dumps({
        "columns": ["Model", "QWK"],
        "rows": [["GPT-4", "0.671"]],
    }), encoding="utf-8")
    svg_path = _write_svg(tmp_path, (
        '<g data-pptx-role="table" data-pptx-source="table_data.json" '
        'data-pptx-bbox="60,75,1080,100">'
        '<rect x="60" y="75" width="1080" height="50" fill="#1e3a5f"/>'
        '<text x="600" y="100">Model</text>'
        '</g>'
    ))
    prs = Presentation()
    layout = prs.slide_layouts[6]
    conv = SvgConverter(str(svg_path))
    slide = conv.convert(prs, layout)

    table_frames = [s for s in slide.shapes if getattr(s, "has_table", False)]
    assert len(table_frames) == 1
    assert table_frames[0].table.cell(0, 0).text_frame.text == "Model"
    # The hand-drawn preview rect/text inside the marker must not also be
    # converted into a plain autoshape/textbox.
    assert len(slide.shapes) == 1


def test_chart_role_creates_native_chart(tmp_path: Path):
    (tmp_path / "chart_data.json").write_text(json.dumps({
        "type": "bar_chart",
        "categories": ["Q1", "Q2"],
        "series": [{"label": "EN", "color": "#1e3a5f", "values": [0.8, 0.9]}],
        "y_max": 1.0,
    }), encoding="utf-8")
    svg_path = _write_svg(tmp_path, (
        '<g data-pptx-role="chart" data-pptx-source="chart_data.json" '
        'data-pptx-bbox="130,100,970,420">'
        '<rect x="130" y="300" width="100" height="120" fill="#1e3a5f"/>'
        '</g>'
    ))
    prs = Presentation()
    layout = prs.slide_layouts[6]
    conv = SvgConverter(str(svg_path))
    slide = conv.convert(prs, layout)

    chart_frames = [s for s in slide.shapes if getattr(s, "has_chart", False)]
    assert len(chart_frames) == 1


def test_source_fragment_resolves_slide_data_json_by_index(tmp_path: Path):
    (tmp_path / "slide_data.json").write_text(json.dumps({
        "meta": {},
        "slides": [
            {"index": 0, "type": "bullet_list"},
            {"index": 4, "type": "table", "columns": ["A"], "rows": [["1"]]},
        ],
    }), encoding="utf-8")
    svg_path = _write_svg(tmp_path, (
        '<g data-pptx-role="table" data-pptx-source="slide_data.json#4" '
        'data-pptx-bbox="60,75,300,100">'
        '<rect x="60" y="75" width="300" height="50" fill="#1e3a5f"/>'
        '</g>'
    ))
    prs = Presentation()
    layout = prs.slide_layouts[6]
    conv = SvgConverter(str(svg_path))
    slide = conv.convert(prs, layout)

    table_frames = [s for s in slide.shapes if getattr(s, "has_table", False)]
    assert table_frames[0].table.cell(0, 0).text_frame.text == "1"


def test_group_role_wraps_child_shapes_in_native_group(tmp_path: Path):
    svg_path = _write_svg(tmp_path, (
        '<g data-pptx-role="group" data-node-id="node1">'
        '<rect x="100" y="100" width="200" height="80" fill="#f8fafc"/>'
        '<text x="200" y="140">Encoder</text>'
        '</g>'
    ))
    prs = Presentation()
    layout = prs.slide_layouts[6]
    conv = SvgConverter(str(svg_path))
    slide = conv.convert(prs, layout)

    from pptx.enum.shapes import MSO_SHAPE_TYPE
    groups = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.GROUP]
    assert len(groups) == 1
    assert len(groups[0].shapes) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest svg_to_pptx/tests/test_native_roles.py -v`
Expected: FAIL — the `<g data-pptx-role="table">` currently recurses into `_dispatch_children` like any other `<g>`, so `test_table_role_creates_native_table_and_skips_children` fails on `len(slide.shapes) == 1` (it will be 2: a rect and a textbox, no table); the group test fails because no `MSO_SHAPE_TYPE.GROUP` shape exists.

- [ ] **Step 3: Modify `__init__` to add the group-collection sink**

In `skills/report-slides/scripts/svg_to_pptx/converter.py`:

```python
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
```

(Replace the existing `__init__` body — the only change is the added final line.)

- [ ] **Step 4: Reset the sink in `convert()`**

```python
    def convert(self, prs: Presentation, slide_layout: Any) -> Any:
        self._connector_registry = []
        self._shape_registry = []
        self._shape_labels = {}
        self._text_to_shape = {}
        self._pending_texts = []
        self._group_collect = None
        slide = prs.slides.add_slide(slide_layout)
```

(Replace the existing `convert()` reset block — the only change is the added `self._group_collect = None` line before `slide = prs.slides.add_slide(...)`.)

- [ ] **Step 5: Route created shapes into the sink and dispatch the new roles**

Replace the entire `_dispatch_element` method:

```python
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
```

- [ ] **Step 6: Add the native-role handler methods**

Insert these new methods immediately after `_bind_connectors` (before the module-level `_try_bind` function):

```python
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
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest svg_to_pptx/tests/test_native_roles.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 8: Run the full existing `svg_to_pptx` test suite to confirm no regression**

Run: `cd skills/report-slides/scripts && python3 -m pytest svg_to_pptx/tests/ -v`
Expected: PASS (all existing tests plus the 4 new ones)

- [ ] **Step 9: Commit**

```bash
git add skills/report-slides/scripts/svg_to_pptx/converter.py skills/report-slides/scripts/svg_to_pptx/tests/test_native_roles.py
git commit -m "feat(report-slides): dispatch data-pptx-role markers to native objects"
```

---

### Task 4: `generate_slides.py` — emit `data-pptx-role` markers, add line/pie chart renderers

**Files:**
- Modify: `skills/report-slides/scripts/generate_slides.py`
- Test: `skills/report-slides/scripts/tests/test_generate_slides_markers.py`

**Interfaces:**
- Consumes: nothing new (pure SVG string generation; no dependency on Task 1/3's runtime code)
- Produces: `render_line_chart(sl, meta) -> str`, `render_pie_chart(sl, meta) -> str`, registered in `RENDERERS` under `"line_chart"` / `"pie_chart"`; every `render_table`/`render_bar_chart`/`render_line_chart`/`render_pie_chart`/`render_timeline` output now contains `data-pptx-role` markers per Task 3's contract.

- [ ] **Step 1: Write the failing tests**

```python
# skills/report-slides/scripts/tests/test_generate_slides_markers.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import etree

from generate_slides import (
    render_table, render_bar_chart, render_line_chart, render_pie_chart,
    render_timeline, RENDERERS,
)

META = {"footer": ""}


def _find_role(svg_text: str, role: str):
    root = etree.fromstring(svg_text.encode("utf-8"))
    return root.find(f'.//{{http://www.w3.org/2000/svg}}g[@data-pptx-role="{role}"]')


def test_render_table_emits_table_marker_with_bbox_and_source():
    sl = {"index": 5, "type": "table", "title": "T",
         "columns": ["A", "B"], "rows": [["1", "2"]]}
    svg_text = render_table(sl, META)
    g = _find_role(svg_text, "table")
    assert g is not None
    assert g.get("data-pptx-source") == "slide_data.json#5"
    assert len(g.get("data-pptx-bbox").split(",")) == 4


def test_render_bar_chart_emits_chart_marker():
    sl = {"index": 4, "type": "bar_chart", "title": "C",
         "categories": ["Q1"], "series": [{"label": "S", "values": [1]}]}
    svg_text = render_bar_chart(sl, META)
    g = _find_role(svg_text, "chart")
    assert g is not None
    assert g.get("data-pptx-source") == "slide_data.json#4"


def test_render_line_chart_emits_chart_marker():
    sl = {"index": 6, "type": "line_chart", "title": "L",
         "categories": ["Q1", "Q2"],
         "series": [{"label": "S", "values": [1, 2]}]}
    svg_text = render_line_chart(sl, META)
    g = _find_role(svg_text, "chart")
    assert g is not None


def test_render_pie_chart_emits_chart_marker():
    sl = {"index": 7, "type": "pie_chart", "title": "P",
         "categories": ["A", "B"], "values": [60, 40]}
    svg_text = render_pie_chart(sl, META)
    g = _find_role(svg_text, "chart")
    assert g is not None


def test_render_timeline_emits_one_group_marker_per_event():
    sl = {"index": 8, "type": "timeline", "title": "TL", "events": [
        {"label": "A", "date": "2024"}, {"label": "B", "date": "2025"},
    ]}
    svg_text = render_timeline(sl, META)
    root = etree.fromstring(svg_text.encode("utf-8"))
    groups = root.findall('.//{http://www.w3.org/2000/svg}g[@data-pptx-role="group"]')
    assert len(groups) == 2
    assert groups[0].get("data-node-id") == "event-0"


def test_renderers_dict_includes_new_chart_types():
    assert "line_chart" in RENDERERS
    assert "pie_chart" in RENDERERS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_generate_slides_markers.py -v`
Expected: FAIL — `render_line_chart`/`render_pie_chart` don't exist yet, and existing renderers don't emit `data-pptx-role` markers.

- [ ] **Step 3: Wrap `render_table`'s content in the `table` marker**

Replace the entire `render_table` function:

```python
def render_table(sl: dict, meta: dict) -> str:
    title         = sl.get("title", "")
    columns       = sl.get("columns", [])
    rows          = sl.get("rows", [])
    highlight_col = sl.get("highlight_col")   # 0-indexed; colorizes +/- values
    footer        = meta.get("footer", "")
    slide_index   = sl.get("index", 0)

    parts = [frame(title, footer)]

    n_cols = len(columns)
    if not n_cols:
        return svg("\n  ".join(parts))

    tl, tr = 60, 1140
    tw      = tr - tl
    col_w   = tw / n_cols
    row_h   = min(50, 450 / (len(rows) + 1))
    top_y   = 75
    table_h = row_h * (len(rows) + 1)

    table_parts = [
        f'<rect x="{tl}" y="{top_y}" width="{tw}" '
        f'height="{row_h}" fill="{S["accent"]}"/>'
    ]
    for ci, col in enumerate(columns):
        cx = tl + ci * col_w + col_w / 2
        table_parts.append(f'<text x="{cx:.1f}" y="{top_y + row_h * 0.63:.1f}" '
                     f'font-size="13" font-weight="700" fill="{S["white"]}" '
                     f'text-anchor="middle">{esc(col)}</text>')

    for ri, row in enumerate(rows):
        ry = top_y + (ri + 1) * row_h
        bg = S["card"] if ri % 2 == 0 else S["bg"]
        table_parts.append(f'<rect x="{tl}" y="{ry:.1f}" width="{tw}" '
                     f'height="{row_h:.1f}" fill="{bg}" '
                     f'stroke="{S["border"]}" stroke-width="0.5"/>')
        for ci, cell in enumerate(row):
            cx    = tl + ci * col_w + col_w / 2
            cy    = ry + row_h * 0.63
            color = S["body"]
            if highlight_col is not None and ci == highlight_col:
                cs = str(cell)
                if "+" in cs:
                    color = S["good"]
                elif "-" in cs:
                    color = S["danger"]
            table_parts.append(f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="13" '
                         f'fill="{color}" text-anchor="middle">{esc(cell)}</text>')

    table_parts.append(f'<rect x="{tl}" y="{top_y}" width="{tw}" '
                 f'height="{table_h:.1f}" fill="none" '
                 f'stroke="{S["border"]}" stroke-width="1.5"/>')

    parts.append(_wrap_pptx_role(
        "table", slide_index, table_parts,
        bbox=(tl, top_y, tw, table_h),
        style_keys=("accent", "white", "card", "bg", "body", "good", "danger", "font"),
    ))

    return svg("\n  ".join(parts))
```

- [ ] **Step 4: Add the shared `_wrap_pptx_role` helper**

Insert this function directly above `render_table` (after the `frame()` function, before the `# Chart drawing area` section):

```python
def _wrap_pptx_role(role: str, slide_index: int, inner_parts: list,
                    bbox: tuple, style_keys: tuple, node_id: str = "") -> str:
    """Wrap hand-drawn preview markup in the data-pptx-role marker so
    svg_to_pptx/converter.py materializes a real native PPTX object instead
    of flattening these shapes. bbox is (x, y, w, h) in SVG user units."""
    style_json = esc(json.dumps({k: S[k] for k in style_keys if k in S}))
    bx, by, bw, bh = bbox
    attrs = [
        f'data-pptx-role="{role}"',
        f'data-pptx-source="slide_data.json#{slide_index}"',
        f'data-pptx-bbox="{bx:.1f},{by:.1f},{bw:.1f},{bh:.1f}"',
        f'data-pptx-style="{style_json}"',
    ]
    if node_id:
        attrs.append(f'data-node-id="{esc(node_id)}"')
    return (f'<g {" ".join(attrs)}>\n  ' + "\n  ".join(inner_parts) + '\n  </g>')
```

- [ ] **Step 5: Wrap `render_bar_chart`'s content in the `chart` marker**

Replace the entire `render_bar_chart` function's body from `parts = [frame(title, footer)]` onward — keep the gridline/axis/bar/legend drawing logic identical, but accumulate into `chart_parts` instead of `parts`, then wrap:

```python
def render_bar_chart(sl: dict, meta: dict) -> str:
    title      = sl.get("title", "")
    categories = sl.get("categories", [])
    series     = sl.get("series", [])
    y_max      = float(sl.get("y_max", 100))
    note       = sl.get("note", "")
    footer     = meta.get("footer", "")
    slide_index = sl.get("index", 0)

    parts = [frame(title, footer)]
    chart_parts = []

    for i in range(6):
        val = y_max * i / 5
        y   = CB - (val / y_max) * CH
        chart_parts.append(f'<line x1="{CL}" y1="{y:.1f}" x2="{CR}" y2="{y:.1f}" '
                     f'stroke="{S["border"]}" stroke-width="1"/>')
        chart_parts.append(f'<text x="{CL - 8}" y="{y + 4:.1f}" font-size="10" '
                     f'fill="{S["muted"]}" text-anchor="end">{val:.0f}%</text>')

    chart_parts.append(f'<line x1="{CL}" y1="{CT}" x2="{CL}" y2="{CB}" '
                 f'stroke="{S["muted"]}" stroke-width="1.5"/>')
    chart_parts.append(f'<line x1="{CL}" y1="{CB}" x2="{CR}" y2="{CB}" '
                 f'stroke="{S["muted"]}" stroke-width="1.5"/>')

    n_cats = len(categories)
    n_ser  = len(series)
    if not n_cats or not n_ser:
        parts.append(_wrap_pptx_role("chart", slide_index, chart_parts,
                                     bbox=(60, 70, 1080, 500),
                                     style_keys=("font",)))
        return svg("\n  ".join(parts))

    cat_slot = CW / n_cats
    group_w  = cat_slot * 0.70
    bar_w    = group_w / n_ser
    pad      = cat_slot * 0.15

    for ci, cat in enumerate(categories):
        gx = CL + ci * cat_slot + pad
        lx = gx + group_w / 2
        chart_parts.append(f'<text x="{lx:.1f}" y="{CB + 20}" font-size="12" font-weight="600" '
                     f'fill="{S["body"]}" text-anchor="middle">{esc(cat)}</text>')

        for si, ser in enumerate(series):
            vals  = ser.get("values", [])
            if ci >= len(vals):
                continue
            val   = float(vals[ci])
            color = ser.get("color", S["blue"])
            bx    = gx + si * bar_w
            bh    = max((val / y_max) * CH, 2)
            by    = CB - bh

            chart_parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" '
                         f'width="{bar_w - 3:.1f}" height="{bh:.1f}" fill="{color}"/>')
            if bh > 16:
                chart_parts.append(f'<text x="{bx + (bar_w - 3) / 2:.1f}" y="{by - 4:.1f}" '
                             f'font-size="11" font-weight="700" fill="{color}" '
                             f'text-anchor="middle">{val:.1f}%</text>')

    lx = CL
    for si, ser in enumerate(series):
        color = ser.get("color", S["blue"])
        chart_parts.append(f'<rect x="{lx + si * 230}" y="{CB + 40}" '
                     f'width="16" height="12" fill="{color}"/>')
        chart_parts.append(f'<text x="{lx + si * 230 + 22}" y="{CB + 51}" '
                     f'font-size="12" fill="{S["body"]}">{esc(ser.get("label", ""))}</text>')

    if note:
        chart_parts.append(f'<text x="{CR}" y="{CB + 51}" font-size="10" '
                     f'fill="{S["muted"]}" text-anchor="end">{esc(note)}</text>')

    parts.append(_wrap_pptx_role("chart", slide_index, chart_parts,
                                 bbox=(60, 70, 1080, 500),
                                 style_keys=("font",)))
    return svg("\n  ".join(parts))
```

- [ ] **Step 6: Add `render_line_chart` and `render_pie_chart`**

Insert directly after `render_bar_chart`:

```python
def render_line_chart(sl: dict, meta: dict) -> str:
    """SVG preview for a line chart. Same slide_data.json schema as
    bar_chart (categories/series/y_max/note); svg_to_pptx/converter.py
    replaces this hand-drawn preview with a real native line chart."""
    title      = sl.get("title", "")
    categories = sl.get("categories", [])
    series     = sl.get("series", [])
    y_max      = float(sl.get("y_max", 100))
    note       = sl.get("note", "")
    footer     = meta.get("footer", "")
    slide_index = sl.get("index", 0)

    parts = [frame(title, footer)]
    chart_parts = []

    for i in range(6):
        val = y_max * i / 5
        y   = CB - (val / y_max) * CH
        chart_parts.append(f'<line x1="{CL}" y1="{y:.1f}" x2="{CR}" y2="{y:.1f}" '
                     f'stroke="{S["border"]}" stroke-width="1"/>')
        chart_parts.append(f'<text x="{CL - 8}" y="{y + 4:.1f}" font-size="10" '
                     f'fill="{S["muted"]}" text-anchor="end">{val:.0f}%</text>')
    chart_parts.append(f'<line x1="{CL}" y1="{CT}" x2="{CL}" y2="{CB}" '
                 f'stroke="{S["muted"]}" stroke-width="1.5"/>')
    chart_parts.append(f'<line x1="{CL}" y1="{CB}" x2="{CR}" y2="{CB}" '
                 f'stroke="{S["muted"]}" stroke-width="1.5"/>')

    n_cats = len(categories)
    if n_cats:
        step = CW / max(n_cats - 1, 1)
        for ci, cat in enumerate(categories):
            x = CL + ci * step
            chart_parts.append(f'<text x="{x:.1f}" y="{CB + 20}" font-size="12" '
                         f'fill="{S["body"]}" text-anchor="middle">{esc(cat)}</text>')
        for ser in series:
            vals = ser.get("values", [])
            color = ser.get("color", S["blue"])
            points = []
            for ci, val in enumerate(vals[:n_cats]):
                x = CL + ci * step
                y = CB - (float(val) / y_max) * CH
                points.append(f"{x:.1f},{y:.1f}")
                chart_parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
            if len(points) > 1:
                chart_parts.append(f'<polyline points="{" ".join(points)}" '
                             f'fill="none" stroke="{color}" stroke-width="2.5"/>')

    if note:
        chart_parts.append(f'<text x="{CR}" y="{CB + 51}" font-size="10" '
                     f'fill="{S["muted"]}" text-anchor="end">{esc(note)}</text>')

    parts.append(_wrap_pptx_role("chart", slide_index, chart_parts,
                                 bbox=(60, 70, 1080, 500),
                                 style_keys=("font",)))
    return svg("\n  ".join(parts))


def render_pie_chart(sl: dict, meta: dict) -> str:
    """SVG preview for a pie chart. Schema: categories/values/colors(optional)/
    note. svg_to_pptx/converter.py replaces this preview with a real native
    pie chart."""
    import math
    title      = sl.get("title", "")
    categories = sl.get("categories", [])
    values     = sl.get("values", [])
    colors     = sl.get("colors") or [S["blue"], S["good"], S["warn"], S["danger"], S["accent"]]
    note       = sl.get("note", "")
    footer     = meta.get("footer", "")
    slide_index = sl.get("index", 0)

    parts = [frame(title, footer)]
    if not categories or not values:
        return svg("\n  ".join(parts))

    cx, cy, r = 420, 340, 200
    total = sum(values) or 1
    chart_parts = []
    angle = -math.pi / 2
    for i, val in enumerate(values):
        frac = val / total
        end_angle = angle + frac * 2 * math.pi
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(end_angle), cy + r * math.sin(end_angle)
        large_arc = 1 if (end_angle - angle) > math.pi else 0
        color = colors[i % len(colors)]
        chart_parts.append(
            f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} '
            f'A{r},{r} 0 {large_arc} 1 {x2:.1f},{y2:.1f} Z" fill="{color}"/>'
        )
        angle = end_angle

    for i, cat in enumerate(categories):
        ly = 160 + i * 32
        color = colors[i % len(colors)]
        chart_parts.append(f'<rect x="700" y="{ly}" width="16" height="16" fill="{color}"/>')
        chart_parts.append(f'<text x="724" y="{ly + 13}" font-size="13" '
                     f'fill="{S["body"]}">{esc(cat)}</text>')

    if note:
        chart_parts.append(f'<text x="1100" y="600" font-size="10" fill="{S["muted"]}" '
                     f'text-anchor="end">{esc(note)}</text>')

    parts.append(_wrap_pptx_role("chart", slide_index, chart_parts,
                                 bbox=(140, 90, 900, 480),
                                 style_keys=("font",)))
    return svg("\n  ".join(parts))
```

- [ ] **Step 7: Wrap each `render_timeline` event in a `group` marker**

Replace the entire `render_timeline` function's event loop. The full function becomes:

```python
def render_timeline(sl: dict, meta: dict) -> str:
    title  = sl.get("title", "")
    events = sl.get("events", [])
    footer = meta.get("footer", "")

    parts = [frame(title, footer)]
    if not events:
        return svg("\n  ".join(parts))

    n  = len(events)
    y0 = 370
    x0, x1 = 100, 1100
    xs = [x0 + i * (x1 - x0) / max(n - 1, 1) for i in range(n)]

    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" '
                 f'stroke="{S["border"]}" stroke-width="3"/>')

    for i, (ev, x) in enumerate(zip(events, xs)):
        color = ev.get("color", S["accent"])
        above = i % 2 == 0
        event_parts = []

        event_parts.append(f'<circle cx="{x:.1f}" cy="{y0}" r="10" '
                     f'fill="{color}" stroke="{S["bg"]}" stroke-width="2"/>')

        if above:
            event_parts.append(f'<line x1="{x:.1f}" y1="{y0 - 10}" x2="{x:.1f}" y2="{y0 - 28}" '
                         f'stroke="{color}" stroke-width="1.5" stroke-dasharray="3,2"/>')
            ty = y0 - 46
        else:
            event_parts.append(f'<line x1="{x:.1f}" y1="{y0 + 10}" x2="{x:.1f}" y2="{y0 + 28}" '
                         f'stroke="{color}" stroke-width="1.5" stroke-dasharray="3,2"/>')
            ty = y0 + 42

        label = ev.get("label", "")
        label_lines = wrap(label, 18)
        event_parts.append(tlines(label_lines, x, ty, 13, S["accent"], "middle", "700"))

        date_str = ev.get("date", "")
        if date_str:
            dy = y0 + 28 if above else y0 - 20
            event_parts.append(f'<text x="{x:.1f}" y="{dy}" font-size="10" '
                         f'fill="{S["muted"]}" text-anchor="middle">{esc(date_str)}</text>')

        detail = ev.get("detail", "")
        if detail:
            det_y = ty + len(label_lines) * 18 + 6
            event_parts.append(tlines(wrap(detail, 20), x, det_y, 11, S["muted"], "middle"))

        parts.append(f'<g data-pptx-role="group" data-node-id="event-{i}">\n    '
                    + "\n    ".join(event_parts) + '\n  </g>')

    return svg("\n  ".join(parts))
```

- [ ] **Step 8: Register the two new slide types**

```python
RENDERERS = {
    "title":         render_title,
    "bullet_list":   render_bullet_list,
    "bar_chart":     render_bar_chart,
    "line_chart":    render_line_chart,
    "pie_chart":     render_pie_chart,
    "table":         render_table,
    "metric_cards":  render_metric_cards,
    "two_column":    render_two_column,
    "timeline":      render_timeline,
    "conclusion":    render_conclusion,
}
```

(Replace the existing `RENDERERS` dict — adds the two new entries in the same alphabetical-ish position as `bar_chart`.)

- [ ] **Step 9: Copy `slide_data.json` into the SVG output directory**

In `main()`, in the "Mode: generate SVGs from JSON" branch, after the slide-generation loop and before the final `print`/`return`:

```python
    print(f"\n{generated} slide(s) written to {args.out}")

    import shutil
    shutil.copy2(args.data, os.path.join(args.out, "slide_data.json"))

    return 0
```

(This replaces the existing `print(f"\n{generated} slide(s) written to {args.out}")` / `return 0` tail of `main()` — the copy step runs unconditionally whenever SVGs were generated, so `data-pptx-source="slide_data.json#N"` markers always resolve relative to the SVG directory regardless of the original `--data` path/filename.)

- [ ] **Step 10: Run tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_generate_slides_markers.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 11: Run the full existing `generate_slides.py` test suite to confirm no regression**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/ -k generate_slides -v`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add skills/report-slides/scripts/generate_slides.py skills/report-slides/scripts/tests/test_generate_slides_markers.py
git commit -m "feat(report-slides): emit data-pptx-role markers, add line/pie chart renderers"
```

---

### Task 5: `validate_diagram_manifest.py` — add optional `pptx_construct` field

**Files:**
- Modify: `skills/report-slides/scripts/validate_diagram_manifest.py`
- Modify: `skills/report-slides/scripts/tests/test_validate_diagram_manifest.py`

**Interfaces:**
- Produces: `PptxConstruct` enum, `_PPTX_CONSTRUCT_VALUES`, `_validate_pptx_construct(document, path, issues) -> None`

- [ ] **Step 1: Write the failing tests**

Add to `skills/report-slides/scripts/tests/test_validate_diagram_manifest.py`, reusing its existing `_complete_payload(asset_dir) -> Dict[str, Any]` and `_write_asset(root, asset_id="training-pipeline", payload=None, source_files=None) -> Path` fixture helpers (defined near the top of the file and used by every existing test in it):

```python
def test_manifest_without_pptx_construct_is_valid(tmp_path: Path) -> None:
    # A manifest with no pptx_construct key at all must still pass -- the
    # field is additive, not required.
    manifest_path = _write_asset(tmp_path)
    assert validate_manifest(manifest_path) == []


def test_manifest_with_invalid_pptx_construct_is_rejected(tmp_path: Path) -> None:
    asset_dir = tmp_path / "training-pipeline"
    payload = _complete_payload(asset_dir)
    payload["pptx_construct"] = "not_a_real_value"
    manifest_path = _write_asset(tmp_path, payload=payload)
    issues = validate_manifest(manifest_path)
    assert "pptx_construct" in _issue_paths(issues)


def test_manifest_with_valid_pptx_construct_passes(tmp_path: Path) -> None:
    asset_dir = tmp_path / "training-pipeline"
    payload = _complete_payload(asset_dir)
    payload["pptx_construct"] = "native_table"
    manifest_path = _write_asset(tmp_path, payload=payload)
    assert validate_manifest(manifest_path) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_diagram_manifest.py -k pptx_construct -v`
Expected: FAIL on `test_manifest_with_invalid_pptx_construct_is_rejected` and `test_manifest_with_valid_pptx_construct_passes` (no issue reported / `pptx_construct` silently ignored); `test_manifest_without_pptx_construct_is_valid` passes trivially already (documents current behavior, guards the "additive" requirement going forward).

- [ ] **Step 3: Add the enum**

In `skills/report-slides/scripts/validate_diagram_manifest.py`, immediately after the existing `class ReuseAction(str, Enum): ...` block:

```python
class PptxConstruct(str, Enum):
    NATIVE_TABLE = "native_table"
    NATIVE_CHART = "native_chart"
    NATIVE_GROUP = "native_group"
    SVG_SHAPES = "svg_shapes"


_PPTX_CONSTRUCT_VALUES = {member.value for member in PptxConstruct}
```

- [ ] **Step 4: Add the validator function and call it**

Add this function near the other `_validate_*` helpers (e.g. directly above `_validate_route_provenance`):

```python
def _validate_pptx_construct(document: Dict[str, Any], path: Path,
                             issues: List[ValidationIssue]) -> None:
    """Validate the optional pptx_construct field.

    Unlike editability (required), pptx_construct is additive: manifests
    written before this field existed simply don't have it, and that is
    not itself a validation error -- absence just means the module has not
    been migrated to a native PPTX construct yet.
    """
    if "pptx_construct" not in document:
        return
    value = document.get("pptx_construct")
    if value not in _PPTX_CONSTRUCT_VALUES:
        issues.append(_issue(
            path, "pptx_construct",
            f"must be one of {sorted(_PPTX_CONSTRUCT_VALUES)}, got {value!r}",
        ))
```

Inside `validate_manifest()`, add the call right after the existing `_validate_review(document, path, issues)` line and before `_validate_route_provenance(...)`:

```python
    _validate_review(document, path, issues)
    _validate_pptx_construct(document, path, issues)
    _validate_route_provenance(
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_diagram_manifest.py -v`
Expected: PASS (all tests in the file, including the 3 new ones)

- [ ] **Step 6: Commit**

```bash
git add skills/report-slides/scripts/validate_diagram_manifest.py skills/report-slides/scripts/tests/test_validate_diagram_manifest.py
git commit -m "feat(report-slides): add optional pptx_construct manifest field"
```

---

### Task 6: `validate_native_objects.py` — safety-net detection gate

**Files:**
- Create: `skills/report-slides/scripts/validate_native_objects.py`
- Test: `skills/report-slides/scripts/tests/test_validate_native_objects.py`

**Interfaces:**
- Consumes: `references/native_object_thresholds.yaml` (Task 2)
- Produces: CLI `python3 validate_native_objects.py --svg-dir <dir> | --pptx <file> [--thresholds <path>]`, exit 0/1; `scan_svg(svg_path, thresholds) -> List[Finding]`, `scan_pptx(pptx_path, thresholds) -> List[Finding]`

- [ ] **Step 1: Write the failing tests**

```python
# skills/report-slides/scripts/tests/test_validate_native_objects.py
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "validate_native_objects.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
    )


def _write_svg(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">{body}</svg>',
        encoding="utf-8",
    )
    return path


def test_unmarked_table_grid_is_flagged(tmp_path: Path):
    grid = "".join(
        f'<rect x="{60 + c * 200}" y="{75 + r * 50}" width="190" height="45" fill="#eee"/>'
        for r in range(3) for c in range(3)
    )
    _write_svg(tmp_path, "slide01_table.svg", grid)
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 1
    assert "table_like" in result.stderr


def test_marked_table_is_not_flagged(tmp_path: Path):
    grid = "".join(
        f'<rect x="{60 + c * 200}" y="{75 + r * 50}" width="190" height="45" fill="#eee"/>'
        for r in range(3) for c in range(3)
    )
    _write_svg(
        tmp_path, "slide01_table.svg",
        f'<g data-pptx-role="table" data-pptx-source="d.json" '
        f'data-pptx-bbox="60,75,600,150">{grid}</g>',
    )
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 0


def test_unmarked_bar_cluster_is_flagged(tmp_path: Path):
    bars = "".join(
        f'<rect x="{130 + i * 100}" y="{500 - i * 40}" width="60" height="{20 + i * 40}" fill="#369"/>'
        for i in range(4)
    )
    _write_svg(tmp_path, "slide02_bar.svg", bars)
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 1
    assert "chart_like" in result.stderr


def test_unmarked_node_cluster_is_flagged(tmp_path: Path):
    cluster = (
        '<g><rect x="100" y="100" width="200" height="80" fill="#eee"/>'
        '<circle cx="120" y="120" r="10" fill="#333"/>'
        '<text x="200" y="140">Encoder</text></g>'
    )
    _write_svg(tmp_path, "slide03_arch.svg", cluster)
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 1
    assert "node_cluster_like" in result.stderr


def test_clean_svg_passes(tmp_path: Path):
    _write_svg(tmp_path, "slide04_title.svg",
              '<text x="600" y="300">Just a title</text>')
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_pptx_mode_requires_svg_dir_or_pptx_exclusively():
    result = _run()
    assert result.returncode != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_native_objects.py -v`
Expected: FAIL with `FileNotFoundError`/non-zero from a missing script (the `SCRIPT` path doesn't exist yet, so `subprocess.run` on `sys.executable <missing file>` fails with a Python-level "can't open file" error, non-zero exit but not matching the intended assertions).

- [ ] **Step 3: Write the implementation**

```python
# skills/report-slides/scripts/validate_native_objects.py
#!/usr/bin/env python3
"""validate_native_objects.py -- safety-net gate for native PPTX table/chart/
group objects.

The primary defense is the agent-authoring rule (SKILL.md Stage 9.1 and the
data_visualization_worker_agent / architecture_diagram_worker_agent
instructions): author tables/charts/semantic node clusters with the
data-pptx-role SVG marker so svg_to_pptx/converter.py materializes real
PPTX objects. This script catches the two ways that rule can be missed:

  --svg-dir DIR   static pre-conversion scan: flags hand-drawn SVG shape
                  patterns (table grids, bar clusters, box+icon+label node
                  clusters) that are NOT wrapped in a data-pptx-role marker.
  --pptx FILE     post-conversion scan: opens the produced .pptx and flags
                  slides with an autoshape cluster matching those same
                  patterns and no accompanying native table/chart/group
                  object -- catching a converter bug that silently fell
                  through to shape-flattening despite a correctly
                  marked-up source SVG.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import yaml
from lxml import etree

DEFAULT_THRESHOLDS_PATH = (
    Path(__file__).resolve().parent.parent / "references" / "native_object_thresholds.yaml"
)


@dataclass(frozen=True)
class Finding:
    slide: str
    kind: str
    message: str


def load_thresholds(path: Path = DEFAULT_THRESHOLDS_PATH) -> Dict[str, float]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    required = ("min_grid_rows", "min_grid_cols", "min_bar_count",
                "min_cluster_shapes", "position_tolerance_px")
    thresholds: Dict[str, float] = {}
    for key in required:
        if key not in doc:
            raise ValueError(f"{path}: missing required key {key!r}")
        thresholds[key] = doc[key]
    return thresholds


def _local_tag(elem: Any) -> str:
    tag = elem.tag
    return tag.split("}")[-1] if isinstance(tag, str) and "}" in tag else str(tag)


def _has_pptx_role_ancestor(elem: Any) -> bool:
    node = elem.getparent()
    while node is not None:
        if node.get("data-pptx-role") in ("table", "chart", "group"):
            return True
        node = node.getparent()
    return False


def _close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance


def _rect_box(elem: Any) -> Tuple[float, float, float, float]:
    return (
        float(elem.get("x", 0)), float(elem.get("y", 0)),
        float(elem.get("width", 0)), float(elem.get("height", 0)),
    )


def scan_svg(svg_path: Path, thresholds: Dict[str, float]) -> List[Finding]:
    """Flag hand-drawn table/chart/node patterns missing a data-pptx-role marker."""
    tree = etree.parse(str(svg_path))
    root = tree.getroot()
    tol = thresholds["position_tolerance_px"]

    rects = [
        elem for elem in root.iter()
        if _local_tag(elem) == "rect" and not _has_pptx_role_ancestor(elem)
    ]

    findings: List[Finding] = []
    findings.extend(_scan_table_like(svg_path.name, rects, thresholds, tol))
    findings.extend(_scan_bar_like(svg_path.name, rects, thresholds, tol))
    findings.extend(_scan_node_clusters(svg_path.name, root, thresholds))
    return findings


def _scan_table_like(slide_name: str, rects: List[Any],
                     thresholds: Dict[str, float], tol: float) -> List[Finding]:
    boxes = [_rect_box(r) for r in rects if r.get("width") and r.get("height")]
    row_groups: Dict[float, List[Tuple[float, float, float, float]]] = {}
    for x, y, w, h in boxes:
        matched_key = next((key for key in row_groups if _close(key, y, tol)), None)
        row_groups.setdefault(matched_key if matched_key is not None else y, []).append((x, y, w, h))

    grid_rows = [row for row in row_groups.values()
                if len(row) >= thresholds["min_grid_cols"]]
    if len(grid_rows) >= thresholds["min_grid_rows"]:
        return [Finding(
            slide_name, "table_like",
            f"{len(grid_rows)} rows of >= {thresholds['min_grid_cols']} aligned "
            "rects look like a hand-drawn table. Wrap the table in "
            '<g data-pptx-role="table" data-pptx-source="..." data-pptx-bbox="...">.',
        )]
    return []


def _scan_bar_like(slide_name: str, rects: List[Any],
                   thresholds: Dict[str, float], tol: float) -> List[Finding]:
    boxes = [_rect_box(r) for r in rects if r.get("width") and r.get("height")]
    baseline_groups: Dict[float, List[Tuple[float, float, float, float]]] = {}
    for x, y, w, h in boxes:
        baseline = y + h
        matched_key = next((key for key in baseline_groups if _close(key, baseline, tol)), None)
        baseline_groups.setdefault(
            matched_key if matched_key is not None else baseline, []
        ).append((x, y, w, h))

    for baseline, group in baseline_groups.items():
        heights = {round(h, 1) for _, _, _, h in group}
        if len(group) >= thresholds["min_bar_count"] and len(heights) > 1:
            return [Finding(
                slide_name, "chart_like",
                f"{len(group)} rects sharing baseline y={baseline:.0f} with "
                "varying heights look like a hand-drawn bar chart. Wrap the "
                'chart in <g data-pptx-role="chart" data-pptx-source="..." '
                'data-pptx-bbox="...">.',
            )]
    return []


def _scan_node_clusters(slide_name: str, root: Any,
                        thresholds: Dict[str, float]) -> List[Finding]:
    findings: List[Finding] = []
    for g in root.iter():
        if _local_tag(g) != "g" or g.get("data-pptx-role") is not None:
            continue
        if _has_pptx_role_ancestor(g):
            continue
        shape_children = [c for c in g if _local_tag(c) in
                         ("rect", "circle", "ellipse", "path", "image")]
        text_children = [c for c in g if _local_tag(c) == "text"]
        if len(shape_children) >= thresholds["min_cluster_shapes"] and text_children:
            findings.append(Finding(
                slide_name, "node_cluster_like",
                f"<g> with {len(shape_children)} shapes and a label looks like "
                "an unmarked diagram node. Wrap it in "
                '<g data-pptx-role="group" data-node-id="...">.',
            ))
    return findings


def scan_pptx(pptx_path: Path, thresholds: Dict[str, float]) -> List[Finding]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(pptx_path))
    findings: List[Finding] = []
    tol = thresholds["position_tolerance_px"]

    for slide_index, slide in enumerate(prs.slides, start=1):
        has_native_table = any(getattr(s, "has_table", False) for s in slide.shapes)
        has_native_chart = any(getattr(s, "has_chart", False) for s in slide.shapes)
        has_group = any(s.shape_type == MSO_SHAPE_TYPE.GROUP for s in slide.shapes)
        rect_like = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE]

        row_groups: Dict[int, int] = {}
        for shape in rect_like:
            matched_key = next(
                (key for key in row_groups if abs(key - shape.top) <= tol), None
            )
            key = matched_key if matched_key is not None else shape.top
            row_groups[key] = row_groups.get(key, 0) + 1
        grid_rows = sum(1 for count in row_groups.values()
                       if count >= thresholds["min_grid_cols"])

        slide_label = f"slide{slide_index}"
        if grid_rows >= thresholds["min_grid_rows"] and not has_native_table:
            findings.append(Finding(
                slide_label, "table_like",
                f"{grid_rows} rows of aligned autoshapes and no native table "
                "object -- converter likely fell through to shape-flattening.",
            ))
        if (len(rect_like) >= thresholds["min_cluster_shapes"] and not has_group
                and not has_native_table and not has_native_chart):
            findings.append(Finding(
                slide_label, "node_cluster_like",
                f"{len(rect_like)} ungrouped autoshapes -- if these form one "
                "semantic diagram node, they should be a native Group.",
            ))

    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect hand-drawn table/chart/node patterns missing "
                     "native PPTX table/chart/group objects."
    )
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--svg-dir", type=Path,
                         help="Directory of slide*.svg files (pre-conversion scan).")
    targets.add_argument("--pptx", type=Path,
                         help="Produced .pptx file (post-conversion scan).")
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS_PATH)
    args = parser.parse_args(argv)

    thresholds = load_thresholds(args.thresholds)

    if args.svg_dir is not None:
        findings: List[Finding] = []
        for svg_path in sorted(args.svg_dir.glob("slide*.svg")):
            findings.extend(scan_svg(svg_path, thresholds))
    else:
        findings = scan_pptx(args.pptx, thresholds)

    if findings:
        for finding in findings:
            print(f"ERROR {finding.slide} [{finding.kind}]: {finding.message}",
                 file=sys.stderr)
        return 1

    print("OK: no unmarked table/chart/node patterns found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_native_objects.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/validate_native_objects.py skills/report-slides/scripts/tests/test_validate_native_objects.py
git commit -m "feat(report-slides): add validate_native_objects.py safety-net gate"
```

---

### Task 7: `architecture_diagram_worker_agent.md` — group-marker authoring rule

**Files:**
- Modify: `skills/report-slides/agents/architecture_diagram_worker_agent.md`

- [ ] **Step 1: Update the Render step (step 6) to require the group marker**

Old:
```
6. **Render:** Render the module to pixels. For `native` route ([V:NATIVE]), author SVG directly with editable shapes and connector elements. For Mermaid (optional, [B]): use the Mermaid rendering gate — check for `mmdc` availability, convert the `.mmd` source to SVG, and verify the output is fully editable; if `mmdc` is unavailable or conversion loses editability, fall back to native SVG and disclose the editability loss in the manifest.
```

New:
```
6. **Render:** Render the module to pixels. For `native` route ([V:NATIVE]), author SVG directly with editable shapes and connector elements. **Every semantic node — a background shape plus its icon and label, a boundary group, any cluster that represents one thing in the diagram — MUST be wrapped in `<g data-pptx-role="group" data-node-id="<stable-id>">` so `svg_to_pptx/converter.py` materializes it as one native PPTX Group shape instead of leaving its parts as disconnected shapes. This is a hard requirement enforced by `validate_native_objects.py` (see "Before Returning"), not a style choice.** For Mermaid (optional, [B]): use the Mermaid rendering gate — check for `mmdc` availability, convert the `.mmd` source to SVG, and verify the output is fully editable; if `mmdc` is unavailable or conversion loses editability, fall back to native SVG and disclose the editability loss in the manifest. Mermaid-sourced SVG cannot carry `data-pptx-role` markers, so a module rendered via Mermaid is exempt from the grouping requirement but must record `pptx_construct: svg_shapes` in its manifest.
```

- [ ] **Step 2: Update the manifest field list in Output Format**

Old:
```
1. **Module manifest** (`manifest.yaml`) with the existing schema (fields: `schema_version`, `diagram_id`, `purpose`, `diagram_type`, `authoring_route`, `editability`, `source_files`, `used_in`, `derived_from`, `based_on_revision`, `changes`, `generation`, `review`). Do not create a new schema variant.
```

New:
```
1. **Module manifest** (`manifest.yaml`) with the existing schema plus the additive `pptx_construct` field (fields: `schema_version`, `diagram_id`, `purpose`, `diagram_type`, `authoring_route`, `editability`, `source_files`, `used_in`, `derived_from`, `based_on_revision`, `changes`, `generation`, `review`, `pptx_construct`). Set `pptx_construct` to `native_group` when every semantic node was wrapped in a `data-pptx-role="group"` marker, or `svg_shapes` when it was not (e.g. a Mermaid-sourced module). Do not create a new schema variant beyond this one additive field.
```

- [ ] **Step 3: Add the native-object check to "Before Returning"**

Old:
```
## Before Returning

Verify:
1. **Manifest validity:** The module's manifest passes `python3 scripts/validate_diagram_manifest.py --manifest <path>` with no errors.
2. **Visual review:** The module's rendered pixels passed the mandatory pixel-vision review per the existing gate (§9.1–9.4 in `SKILL.md`).
3. **Render artifact:** A pixel rendering (SVG preview or final PNG) exists and is named in the manifest's review records.

Missing manifest validity or visual review is a hard blocker — do not return a module that fails either check.
```

New:
```
## Before Returning

Verify:
1. **Manifest validity:** The module's manifest passes `python3 scripts/validate_diagram_manifest.py --manifest <path>` with no errors.
2. **Visual review:** The module's rendered pixels passed the mandatory pixel-vision review per the existing gate (§9.1–9.4 in `SKILL.md`).
3. **Render artifact:** A pixel rendering (SVG preview or final PNG) exists and is named in the manifest's review records.
4. **Native object check:** `python3 scripts/validate_native_objects.py --svg-dir <dir containing this module's SVG>` reports no unmarked node-cluster patterns for this module's source file.

Missing manifest validity, visual review, or the native object check is a hard blocker — do not return a module that fails any of them.
```

- [ ] **Step 4: Commit**

```bash
git add skills/report-slides/agents/architecture_diagram_worker_agent.md
git commit -m "docs(report-slides): require group markers in architecture_diagram_worker_agent"
```

---

### Task 8: `data_visualization_worker_agent.md` — table/chart-marker authoring rule

**Files:**
- Modify: `skills/report-slides/agents/data_visualization_worker_agent.md`

- [ ] **Step 1: Update the Render step (step 6)**

Old:
```
6. **Render:** Render the module to pixels. For `data` route ([V:DATA]), use the existing `[A] Python renderer` — `generate_slides.py` — with `slide_data.json` following the schema documented in `SKILL.md` § "Generate slides" § "[A] Python renderer". For chart types not supported by the Python renderer, use `[V:NATIVE]` SVG (editable SVG shapes and connectors).
```

New:
```
6. **Render:** Render the module to pixels. For `data` route ([V:DATA]), use the existing `[A] Python renderer` — `generate_slides.py` — with `slide_data.json` following the schema documented in `SKILL.md` § "Generate slides" § "[A] Python renderer". `generate_slides.py` automatically wraps table/bar_chart/line_chart/pie_chart/timeline output in the `data-pptx-role` marker required by `svg_to_pptx/converter.py` — no extra action needed from you for this route. For chart types not supported by the Python renderer, use `[V:NATIVE]` SVG (editable SVG shapes and connectors); in that case you MUST hand-author the same `data-pptx-role="table"`/`"chart"` marker (with `data-pptx-source` and `data-pptx-bbox`) around any tabular or chart content yourself — a hand-drawn grid of rects or bars with no marker is a hard blocker enforced by `validate_native_objects.py`, not a style choice.
```

- [ ] **Step 2: Update the manifest field list in Output Format**

Old:
```
1. **Module manifest** (`manifest.yaml`) with the existing schema (fields: `schema_version`, `diagram_id`, `purpose`, `diagram_type`, `authoring_route`, `editability`, `source_files`, `used_in`, `derived_from`, `based_on_revision`, `changes`, `generation`, `review`). Do not create a new schema variant.
```

New:
```
1. **Module manifest** (`manifest.yaml`) with the existing schema plus the additive `pptx_construct` field (fields: `schema_version`, `diagram_id`, `purpose`, `diagram_type`, `authoring_route`, `editability`, `source_files`, `used_in`, `derived_from`, `based_on_revision`, `changes`, `generation`, `review`, `pptx_construct`). Set `pptx_construct` to `native_table`/`native_chart` for the `data` route (the marker is emitted automatically), or based on your own marker use for `[V:NATIVE]`; use `svg_shapes` only when no marker could be applied. Do not create a new schema variant beyond this one additive field.
```

- [ ] **Step 3: Add the native-object check to "Before Returning"**

Old:
```
## Before Returning

Verify:
1. **Manifest validity:** The module's manifest passes `python3 scripts/validate_diagram_manifest.py --manifest <path>` with no errors.
2. **Visual review:** The module's rendered pixels passed the mandatory pixel-vision review per the existing gate (§9.1–9.4 in `SKILL.md`).
3. **Render artifact:** A pixel rendering (SVG preview or final PNG) exists and is named in the manifest's review records.

Missing manifest validity or visual review is a hard blocker — do not return a module that fails either check.
```

New:
```
## Before Returning

Verify:
1. **Manifest validity:** The module's manifest passes `python3 scripts/validate_diagram_manifest.py --manifest <path>` with no errors.
2. **Visual review:** The module's rendered pixels passed the mandatory pixel-vision review per the existing gate (§9.1–9.4 in `SKILL.md`).
3. **Render artifact:** A pixel rendering (SVG preview or final PNG) exists and is named in the manifest's review records.
4. **Native object check:** `python3 scripts/validate_native_objects.py --svg-dir <dir containing this module's SVG>` reports no unmarked table/chart patterns for this module's source file.

Missing manifest validity, visual review, or the native object check is a hard blocker — do not return a module that fails any of them.
```

- [ ] **Step 4: Commit**

```bash
git add skills/report-slides/agents/data_visualization_worker_agent.md
git commit -m "docs(report-slides): require table/chart markers in data_visualization_worker_agent"
```

---

### Task 9: `references/diagram-patterns.md` — document the marker requirement per diagram type

**Files:**
- Modify: `skills/report-slides/references/diagram-patterns.md`

- [ ] **Step 1: Architecture section**

Old:
```
- **Editable elements:** nodes, labels, groups, boundaries, interfaces, and
  connectors.
```

New:
```
- **Editable elements:** nodes, labels, groups, boundaries, interfaces, and
  connectors. Every node (background shape + icon + label) MUST be a native
  PPTX Group shape — wrap it in `<g data-pptx-role="group"
  data-node-id="...">` — not a pile of ungrouped shapes.
```

- [ ] **Step 2: Flowchart section**

Old:
```
- **Editable elements:** steps, decisions, branch labels, terminal states, and
  connectors.
```

New:
```
- **Editable elements:** steps, decisions, branch labels, terminal states, and
  connectors. Every step/decision node MUST be a native PPTX Group shape —
  wrap it in `<g data-pptx-role="group" data-node-id="...">` — not a pile of
  ungrouped shapes.
```

- [ ] **Step 3: Timeline section**

Old:
```
- **Editable elements:** dates, event labels, intervals, milestones, axis,
  and dependency markers.
```

New:
```
- **Editable elements:** dates, event labels, intervals, milestones, axis,
  and dependency markers. Every event/milestone node MUST be a native PPTX
  Group shape — wrap it in `<g data-pptx-role="group" data-node-id="...">`
  — not a pile of ungrouped shapes.
```

- [ ] **Step 4: Statistical section**

Old:
```
- **Editable elements:** source-data labels, axes, units, ticks, legend,
  series, marks, annotations, and uncertainty indicators.
```

New:
```
- **Editable elements:** source-data labels, axes, units, ticks, legend,
  series, marks, annotations, and uncertainty indicators. Chart marks MUST
  be a native PPTX chart object (`<g data-pptx-role="chart"
  data-pptx-source="..." data-pptx-bbox="...">`) and tabular views MUST be a
  native PPTX table object (`data-pptx-role="table"`) — not hand-drawn bars,
  lines, or grid rects.
```

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/references/diagram-patterns.md
git commit -m "docs(report-slides): document native-object marker requirement per diagram type"
```

---

### Task 10: `SKILL.md` — wire the marker requirement and gate into Stage 9.1

**Files:**
- Modify: `skills/report-slides/SKILL.md`

- [ ] **Step 1: Update §9.1 steps 5 and 8**

Old:
```
5. **Author:** create or modify a reusable source; resolve reuse, modification,
   or derivation identity before route-specific generation.
6. **Render:** render both the subfigure and the complete slide to pixels.
7. **Review:** inspect both pixel renders with model vision, revise the source,
   and repeat the render/vision loop until both gates pass.
8. **Manifest:** validate the plan, each manifest, and the asset root:
   `python3 scripts/validate_diagram_manifest.py --plan <plan>`,
   `python3 scripts/validate_diagram_manifest.py --manifest <manifest>`, and
   `python3 scripts/validate_diagram_manifest.py --root <asset-root>`.
```

New:
```
5. **Author:** create or modify a reusable source; resolve reuse, modification,
   or derivation identity before route-specific generation. **Tabular data and
   charts MUST be authored as `<g data-pptx-role="table"|"chart"
   data-pptx-source="..." data-pptx-bbox="x,y,w,h">` around the preview
   markup, never as hand-drawn grid rects or bars — see
   `references/diagram-patterns.md`. Any semantic diagram node (a box plus
   icon plus label, a timeline event, a legend entry) MUST be wrapped in
   `<g data-pptx-role="group" data-node-id="...">`. These are hard
   requirements enforced by `validate_native_objects.py` (step 8), not style
   preferences.**
6. **Render:** render both the subfigure and the complete slide to pixels.
7. **Review:** inspect both pixel renders with model vision, revise the source,
   and repeat the render/vision loop until both gates pass.
8. **Manifest:** validate the plan, each manifest, and the asset root:
   `python3 scripts/validate_diagram_manifest.py --plan <plan>`,
   `python3 scripts/validate_diagram_manifest.py --manifest <manifest>`, and
   `python3 scripts/validate_diagram_manifest.py --root <asset-root>`. Also
   run the native-object safety net against the slide's SVG directory:
   `python3 scripts/validate_native_objects.py --svg-dir <dir>` — a non-zero
   exit is a hard blocker; fix the missing marker and re-render.
```

- [ ] **Step 2: Add the post-export scan to the output-format branch**

Old:
```
   ```
   if output_format is pptx:
       require statuses.svg_preview passed before export
       export the actual deck.pptx
       validate package structure into statuses.pptx_structure
       convert the actual deck.pptx with LibreOffice or an equivalent
           office renderer (never the source SVG)
       produce exactly one final PNG for every expected slide under
           rendered_png_paths
       send every final PNG path directly to model_vision as
           model_vision.inspected_paths
       record statuses.pptx_render
       allow completion only when statuses.svg_preview,
           statuses.pptx_structure, and statuses.pptx_render are all passed
   otherwise:
       record both statuses.pptx_structure and statuses.pptx_render as
           not_applicable with a non-empty reason
       use statuses.svg_preview as the final, authoritative visual gate
   ```
```

New:
```
   ```
   if output_format is pptx:
       require statuses.svg_preview passed before export
       export the actual deck.pptx
       run `python3 scripts/validate_native_objects.py --pptx <deck.pptx>` as
           a hard blocker before validating package structure -- a non-zero
           exit means a table/chart/node pattern reached the PPTX without
           its native construct; fix the source marker or converter branch
           and re-export
       validate package structure into statuses.pptx_structure
       convert the actual deck.pptx with LibreOffice or an equivalent
           office renderer (never the source SVG)
       produce exactly one final PNG for every expected slide under
           rendered_png_paths
       send every final PNG path directly to model_vision as
           model_vision.inspected_paths
       record statuses.pptx_render
       allow completion only when statuses.svg_preview,
           statuses.pptx_structure, and statuses.pptx_render are all passed
   otherwise:
       record both statuses.pptx_structure and statuses.pptx_render as
           not_applicable with a non-empty reason
       use statuses.svg_preview as the final, authoritative visual gate
   ```
```

- [ ] **Step 3: Update the "Native mode converts" sentence in the PPTX export section**

Old (line ~919):
```
Native mode converts every SVG element to editable shapes: rectangles, ovals, text boxes, connectors, and paths (including Bézier curves). Text labels inside shapes are embedded directly — double-click a shape in PowerPoint to edit its text. Connectors re-route when shapes are moved.
```

New:
```
Native mode converts every SVG element to editable shapes: rectangles, ovals, text boxes, connectors, and paths (including Bézier curves). Text labels inside shapes are embedded directly — double-click a shape in PowerPoint to edit its text. Connectors re-route when shapes are moved. Content wrapped in a `data-pptx-role="table"`/`"chart"` marker becomes a real PPTX table or chart object (double-click to edit cell text or the chart's underlying data series, exactly like a manually-inserted PowerPoint table/chart); content wrapped in `data-pptx-role="group"` becomes one native Group shape.
```

- [ ] **Step 4: Run the SKILL.md documentation test suite**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/ -k skill_md -v`

Expected: PASS. If a test (e.g. a `test_visual_review_docs.py`-style check) asserts §9.1's exact step text verbatim, update that test's expected string to match the new step 5/8 text from this task — the test should assert the *presence* of the new marker/gate requirements, not fail because the prose grew.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/SKILL.md
git commit -m "docs(report-slides): wire data-pptx-role markers and validate_native_objects.py into Stage 9.1"
```

---

### Task 11: End-to-end integration test

**Files:**
- Create: `skills/report-slides/scripts/tests/test_native_objects_integration.py`

**Interfaces:**
- Consumes: `generate_slides.render_table`, `render_bar_chart`, `render_pie_chart` (Task 4); `svg_to_pptx.converter.convert_file` (Task 3, pre-existing signature); `validate_native_objects.scan_pptx` (Task 6)

- [ ] **Step 1: Write the test**

```python
# skills/report-slides/scripts/tests/test_native_objects_integration.py
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pptx import Presentation

from generate_slides import render_table, render_bar_chart, render_pie_chart
from svg_to_pptx.converter import convert_file
from validate_native_objects import scan_pptx, load_thresholds


SLIDE_DATA = {
    "meta": {"footer": "Integration test"},
    "slides": [
        {"index": 0, "type": "table", "title": "Results",
         "columns": ["Model", "QWK"], "rows": [["GPT-4", "0.671"], ["BERT", "0.836"]]},
        {"index": 1, "type": "bar_chart", "title": "Scores",
         "categories": ["Q1", "Q2"],
         "series": [{"label": "EN", "color": "#1e3a5f", "values": [0.8, 0.9]}],
         "y_max": 1.0},
        {"index": 2, "type": "pie_chart", "title": "Share",
         "categories": ["A", "B", "C"], "values": [50, 30, 20]},
    ],
}


def test_end_to_end_table_and_chart_slides_produce_native_objects(tmp_path: Path):
    out_dir = tmp_path / "svgs"
    out_dir.mkdir()
    (out_dir / "slide_data.json").write_text(json.dumps(SLIDE_DATA), encoding="utf-8")

    renderers = {"table": render_table, "bar_chart": render_bar_chart,
                "pie_chart": render_pie_chart}
    meta = SLIDE_DATA["meta"]
    for sl in SLIDE_DATA["slides"]:
        svg_text = renderers[sl["type"]](sl, meta)
        (out_dir / f'slide{sl["index"]:02d}_{sl["type"]}.svg').write_text(
            svg_text, encoding="utf-8"
        )

    pptx_path = tmp_path / "deck.pptx"
    convert_file(str(out_dir), str(pptx_path))

    prs = Presentation(str(pptx_path))
    assert len(prs.slides) == 3
    has_table = any(getattr(s, "has_table", False) for s in prs.slides[0].shapes)
    has_bar_chart = any(getattr(s, "has_chart", False) for s in prs.slides[1].shapes)
    has_pie_chart = any(getattr(s, "has_chart", False) for s in prs.slides[2].shapes)
    assert has_table
    assert has_bar_chart
    assert has_pie_chart

    thresholds = load_thresholds()
    findings = scan_pptx(pptx_path, thresholds)
    assert findings == []
```

- [ ] **Step 2: Run the test**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_native_objects_integration.py -v`
Expected: PASS. If it fails, the failure will point at whichever task's contract (Task 3's `_load_pptx_source`, Task 4's marker emission, or Task 6's detector) is inconsistent — fix that task's code, not this test, unless the test itself has a mistake.

- [ ] **Step 3: Run the entire `report-slides` scripts test suite**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/ svg_to_pptx/tests/ -v`
Expected: PASS (no regressions across the whole skill)

- [ ] **Step 4: Commit**

```bash
git add skills/report-slides/scripts/tests/test_native_objects_integration.py
git commit -m "test(report-slides): end-to-end table/chart native-object integration test"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 → Component A; Task 3 → Component C (converter dispatch); Task 4 → Component B (Path A marker emission + new chart types); Task 5 → the manifest `pptx_construct` addition; Task 2 + Task 6 → Component E (enforcement gate + its config); Tasks 7–10 → Component D (agent/reference/SKILL.md rule updates); Task 11 → the spec's "Testing" section's end-to-end requirement. All five in-scope items (table, bar/line/pie chart, timeline grouping, architecture/flowchart node grouping, enforcement) have a task.
- **Deferred by spec, correctly excluded from this plan:** true Office SmartArt, chart types beyond bar/line/pie, and any change to `to_pptx.py`'s embed-mode packing.
- **Type consistency check:** `add_native_table`/`add_native_chart`/`add_native_group` signatures in Task 1 match every call site in Task 3's `_dispatch_native_data`/`_dispatch_native_group` exactly (same parameter names and order). `_wrap_pptx_role`'s marker attribute names (`data-pptx-role`, `data-pptx-source`, `data-pptx-bbox`, `data-pptx-style`, `data-node-id`) in Task 4 match the attribute names Task 3's `_dispatch_native_data`/`_dispatch_native_group`/`_pptx_style`/`_load_pptx_source` read, and match Task 6's detector's `data-pptx-role` ancestor check.
