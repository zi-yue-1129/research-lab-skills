import pytest
from lxml import etree
from pptx import Presentation
from pptx.util import Emu
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

from svg_to_pptx.converter import CoordSystem
from svg_to_pptx.shapes import dispatch_shape
from svg_to_pptx.style_parser import compute_style

CS = CoordSystem(svg_w=1200.0, svg_h=675.0)


def _blank_slide():
    prs = Presentation()
    prs.slide_width = Emu(12_192_000)
    prs.slide_height = Emu(6_858_000)
    return prs.slides.add_slide(prs.slide_layouts[6]), prs


def test_rect_creates_one_shape():
    slide, _ = _blank_slide()
    elem = etree.fromstring('<rect x="100" y="50" width="200" height="100" fill="#3b82f6"/>')
    style = compute_style(elem, {})
    dispatch_shape(slide, elem, style, CS, None)
    assert len(slide.shapes) == 1


def test_rect_position_and_size():
    slide, _ = _blank_slide()
    elem = etree.fromstring('<rect x="0" y="0" width="1200" height="675" fill="#fff"/>')
    style = compute_style(elem, {})
    dispatch_shape(slide, elem, style, CS, None)
    shape = slide.shapes[0]
    assert shape.left == 0
    assert shape.top == 0
    assert shape.width == 12_192_000
    assert shape.height == 6_858_000


def test_circle_creates_oval():
    slide, _ = _blank_slide()
    elem = etree.fromstring('<circle cx="600" cy="337" r="100" fill="#10b981"/>')
    style = compute_style(elem, {})
    dispatch_shape(slide, elem, style, CS, None)
    assert len(slide.shapes) == 1
    shape = slide.shapes[0]
    expected_w = CS.x(200)
    assert abs(shape.width - expected_w) <= 1


def test_rect_with_label_writes_text_in_shape():
    slide, _ = _blank_slide()
    rect_elem = etree.fromstring('<rect x="40" y="80" width="160" height="70" fill="#3b82f6"/>')
    text_elem = etree.fromstring('<text x="120" y="115" fill="white">Hello</text>')
    style = compute_style(rect_elem, {})
    dispatch_shape(slide, rect_elem, style, CS, text_elem)
    shape = slide.shapes[0]
    assert shape.has_text_frame
    assert shape.text_frame.paragraphs[0].runs[0].text == "Hello"


def test_rect_with_tspan_only_label_still_writes_text_in_shape():
    """Regression: a <text> with coordinates only on its <tspan> (valid SVG,
    but violates this repo's own x/y-on-<text> authoring convention) must
    still resolve its position via _text_xy's fallback and embed correctly
    -- not silently anchor at (0, 0) and miss the shape entirely."""
    slide, _ = _blank_slide()
    rect_elem = etree.fromstring('<rect x="40" y="80" width="160" height="70" fill="#3b82f6"/>')
    text_elem = etree.fromstring(
        '<text fill="white" text-anchor="middle">'
        '<tspan x="120" y="108">Multi-Head</tspan>'
        '<tspan x="120" dy="15">Attention</tspan></text>'
    )
    style = compute_style(rect_elem, {})
    dispatch_shape(slide, rect_elem, style, CS, text_elem)
    shape = slide.shapes[0]
    assert shape.has_text_frame
    paragraphs = shape.text_frame.paragraphs
    assert paragraphs[0].runs[0].text == "Multi-Head"
    assert paragraphs[1].runs[0].text == "Attention"


def test_attached_labels_use_explicit_svg_text_layout() -> None:
    """Verify attached labels use a frame offset and preserve paragraph layout."""
    slide, _ = _blank_slide()
    rect_elem = etree.fromstring(
        '<rect x="40" y="80" width="160" height="70" fill="#3b82f6"/>'
    )
    label_elems = [
        etree.fromstring(
            '<text x="120" y="112" fill="white" text-anchor="middle" '
            'font-size="14">Title</text>'
        ),
        etree.fromstring(
            '<text x="180" y="132" fill="white" text-anchor="end" '
            'font-size="11">Subtitle</text>'
        ),
    ]
    style = compute_style(rect_elem, {})
    dispatch_shape(slide, rect_elem, style, CS, label_elems)

    tf = slide.shapes[0].text_frame
    assert tf.margin_left == Emu(0)
    assert tf.margin_right == Emu(0)
    assert tf.margin_bottom == Emu(0)
    assert tf.vertical_anchor == MSO_ANCHOR.TOP

    paragraphs = tf.paragraphs
    assert [paragraph.alignment for paragraph in paragraphs] == [
        PP_ALIGN.CENTER,
        PP_ALIGN.RIGHT,
    ]
    assert [
        run.text
        for paragraph in paragraphs
        for run in paragraph.runs
    ] == ["Title", "Subtitle"]
    expected_top_margin = CS.y(112 - 80 - 14 * 0.75 + 4.0)
    assert tf.margin_top == Emu(expected_top_margin)
    assert tf.margin_top > Emu(0)
    assert paragraphs[0].space_before == Emu(0)
    assert paragraphs[0].space_after == Emu(0)
    assert paragraphs[0].line_spacing == Emu(CS.y(14 * 1.2))
    assert paragraphs[1].space_before == Emu(CS.y(132 - 112 - 14 * 1.2))
    assert paragraphs[1].space_after == Emu(0)
    assert paragraphs[1].line_spacing == Emu(CS.y(11 * 1.2))


def test_attached_label_top_margin_is_bounded_by_shape_slack() -> None:
    """Verify the attached frame offset cannot consume later-line space."""
    slide, _ = _blank_slide()
    rect_elem = etree.fromstring(
        '<rect x="40" y="80" width="160" height="40" fill="#3b82f6"/>'
    )
    label_elems = [
        etree.fromstring(
            '<text x="120" y="112" fill="white" text-anchor="middle" '
            'font-size="14">Title</text>'
        ),
        etree.fromstring(
            '<text x="180" y="132" fill="white" text-anchor="end" '
            'font-size="11">Subtitle</text>'
        ),
    ]
    style = compute_style(rect_elem, {})
    dispatch_shape(slide, rect_elem, style, CS, label_elems)

    tf = slide.shapes[0].text_frame
    paragraphs = tf.paragraphs
    expected_bounded_margin = CS.y(40.0 - (16.8 + 3.2 + 13.2))
    assert tf.margin_top == Emu(expected_bounded_margin)
    assert tf.margin_top > Emu(0)
    assert tf.margin_top < Emu(CS.y(21.5 + 4.0))
    assert paragraphs[0].space_before == Emu(0)
    assert paragraphs[1].space_before == Emu(CS.y(3.2))
    assert (
        tf.margin_top
        + paragraphs[0].line_spacing
        + paragraphs[1].space_before
        + paragraphs[1].line_spacing
        <= Emu(CS.y(40.0))
    )


def test_ellipse_creates_oval():
    slide, _ = _blank_slide()
    elem = etree.fromstring('<ellipse cx="300" cy="200" rx="80" ry="40" fill="#f00"/>')
    style = compute_style(elem, {})
    dispatch_shape(slide, elem, style, CS, None)
    assert len(slide.shapes) == 1


from svg_to_pptx.converter import SvgConverter
import os, tempfile
from pptx import Presentation
from pptx.util import Emu

_ATTACHMENT_SVG = """<svg viewBox="0 0 1200 675" xmlns="http://www.w3.org/2000/svg">
  <rect x="40" y="80" width="160" height="70" fill="#3b82f6"/>
  <text x="120" y="115" fill="white" text-anchor="middle" font-size="14">Deep Research</text>
  <rect x="300" y="80" width="160" height="70" fill="#10b981"/>
  <text x="380" y="115" fill="white" text-anchor="middle" font-size="14">Academic Paper</text>
</svg>"""


def test_text_attaches_to_enclosing_rect():
    with tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False) as f:
        f.write(_ATTACHMENT_SVG)
        svg_path = f.name
    try:
        prs = Presentation()
        prs.slide_width = Emu(12_192_000)
        prs.slide_height = Emu(6_858_000)
        conv = SvgConverter(svg_path)
        slide = conv.convert(prs, prs.slide_layouts[6])
        assert len(slide.shapes) == 2
        texts = [sh.text_frame.paragraphs[0].runs[0].text
                 for sh in slide.shapes if sh.has_text_frame
                 and sh.text_frame.paragraphs[0].runs]
        assert "Deep Research" in texts
        assert "Academic Paper" in texts
    finally:
        os.unlink(svg_path)
