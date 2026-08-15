from lxml import etree

from svg_to_pptx.converter import _text_xy


def test_text_xy_reads_coordinates_from_the_text_element():
    elem = etree.fromstring('<text x="120" y="45">Hello</text>')
    assert _text_xy(elem) == (120.0, 45.0)


def test_text_xy_falls_back_to_first_tspan_when_text_element_has_no_coords():
    elem = etree.fromstring(
        '<text><tspan x="120" y="45">Line 1</tspan>'
        '<tspan x="120" dy="15">Line 2</tspan></text>'
    )
    assert _text_xy(elem) == (120.0, 45.0)


def test_text_xy_fills_in_only_the_missing_coordinate():
    elem = etree.fromstring('<text y="45"><tspan x="120" y="45">Hello</tspan></text>')
    assert _text_xy(elem) == (120.0, 45.0)


def test_text_xy_defaults_to_zero_when_nothing_is_resolvable():
    elem = etree.fromstring('<text>Hello</text>')
    assert _text_xy(elem) == (0.0, 0.0)


def test_text_xy_ignores_malformed_numeric_values():
    elem = etree.fromstring('<text x="not-a-number" y="45">Hello</text>')
    assert _text_xy(elem) == (0.0, 45.0)
