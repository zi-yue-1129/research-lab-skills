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
    # cell(0, 0) is the header row (column name "A"); cell(1, 0) is the data
    # row that proves the correct slide entry (index 4, not index 0) was
    # resolved from slide_data.json.
    assert table_frames[0].table.cell(1, 0).text_frame.text == "1"


def test_group_role_wraps_child_shapes_in_native_group(tmp_path: Path):
    # The text sits below the rect's bbox (rect spans y=100..180) rather than
    # inside it: the pre-existing _compute_text_attachments pass embeds any
    # text whose baseline falls inside a sibling shape's bbox as that shape's
    # own label (a single autoshape, by design, for labeled-box content), so
    # an overlapping text here would collapse to 1 collected shape and never
    # exercise the 2-shapes-grouped path this test targets.
    svg_path = _write_svg(tmp_path, (
        '<g data-pptx-role="group" data-node-id="node1">'
        '<rect x="100" y="100" width="200" height="80" fill="#f8fafc"/>'
        '<text x="200" y="200">Encoder</text>'
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
