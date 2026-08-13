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
