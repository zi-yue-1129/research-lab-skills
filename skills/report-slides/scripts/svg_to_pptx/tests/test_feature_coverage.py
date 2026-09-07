"""Tests for hyperlinks, embedded media, and template-driven theming.

Each assertion is made against the *exported deck* rather than the helper that
produced it, because all three features failed silently before: an anchor's
contents vanished with no error, media had no representation at all, and a
house theme was simply not carried. A helper-level test would not have noticed
any of them.
"""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import pytest
from pptx import Presentation

from svg_to_pptx.converter import convert_file
from svg_to_pptx.hyperlinks import is_supported
from svg_to_pptx.media import MediaMarkerError, read_marker
from svg_to_pptx.template import TemplateError, choose_layout, open_presentation

#: Smallest bytes python-pptx will embed as an MP4 (an `ftyp` box).
_MP4 = bytes.fromhex(
    "0000001c6674797069736f6d0000020069736f6d69736f32617663316d703431"
)

#: 1x1 transparent PNG, used as a poster frame.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _slide(directory: Path, body: str) -> None:
    """Write a single slide SVG wrapping `body`."""
    (directory / "slide-01.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">'
        f"{body}</svg>",
        encoding="utf-8",
    )


def _export(directory: Path, **kwargs) -> Path:
    """Convert the directory and return the deck path."""
    deck = directory / "deck.pptx"
    convert_file(str(directory), str(deck), **kwargs)
    return deck


def _shape_link(shape) -> str | None:
    """Return a shape's click-action target, or None."""
    try:
        return shape.click_action.hyperlink.address
    except (AttributeError, NotImplementedError):
        return None


def _run_links(shape) -> list:
    """Return every run-level hyperlink target in a shape."""
    if not shape.has_text_frame:
        return []
    return [
        run.hyperlink.address
        for paragraph in shape.text_frame.paragraphs
        for run in paragraph.runs
    ]


# --- hyperlinks -----------------------------------------------------------


def test_an_anchor_no_longer_swallows_its_children(tmp_path: Path) -> None:
    """Before this, everything inside `<a>` was dropped from the deck.

    The element matched no dispatch branch, so its children were never walked:
    no link, and no shape either. This is the content-loss half of the fix.
    """
    _slide(
        tmp_path,
        '<a href="https://example.org/a">'
        '<rect x="10" y="10" width="200" height="80" fill="#123456"/></a>'
        '<rect x="300" y="10" width="200" height="80" fill="#654321"/>',
    )
    shapes = list(Presentation(str(_export(tmp_path))).slides[0].shapes)
    assert len(shapes) == 2


def test_a_linked_shape_becomes_a_click_target(tmp_path: Path) -> None:
    """A wrapped shape links through its click action."""
    _slide(
        tmp_path,
        '<a href="https://example.org/paper">'
        '<rect x="10" y="10" width="200" height="80" fill="#123456"/></a>',
    )
    shape = list(Presentation(str(_export(tmp_path))).slides[0].shapes)[0]
    assert _shape_link(shape) == "https://example.org/paper"


def test_linked_text_links_the_words_not_the_box(tmp_path: Path) -> None:
    """A citation should underline the words, which means run-level links."""
    _slide(
        tmp_path,
        '<a href="https://example.org/cite">'
        '<text x="50" y="300" font-size="24">Smith 2024</text></a>',
    )
    shape = list(Presentation(str(_export(tmp_path))).slides[0].shapes)[0]
    assert _run_links(shape) == ["https://example.org/cite"]


def test_an_unwrapped_shape_gets_no_link(tmp_path: Path) -> None:
    """Links do not leak to siblings outside the anchor."""
    _slide(tmp_path, '<rect x="10" y="10" width="200" height="80" fill="#123456"/>')
    shape = list(Presentation(str(_export(tmp_path))).slides[0].shapes)[0]
    assert _shape_link(shape) is None


def test_nested_anchors_use_the_innermost_target(tmp_path: Path) -> None:
    """The nearest enclosing anchor wins, as in a browser."""
    _slide(
        tmp_path,
        '<a href="https://example.org/outer">'
        '<a href="https://example.org/inner">'
        '<rect x="10" y="10" width="200" height="80" fill="#123456"/></a></a>',
    )
    shape = list(Presentation(str(_export(tmp_path))).slides[0].shapes)[0]
    assert _shape_link(shape) == "https://example.org/inner"


@pytest.mark.parametrize(
    "href",
    ["javascript:alert(1)", "file:///etc/passwd", "//example.org/x", "data:text/html,x"],
)
def test_unsupported_schemes_are_refused(tmp_path: Path, href: str) -> None:
    """A deck is forwarded; it must not carry a link the reader cannot trust.

    The shape still exports -- refusing the scheme must not cost the artwork.
    """
    assert is_supported(href) is False
    _slide(
        tmp_path,
        f'<a href="{href}">'
        '<rect x="10" y="10" width="200" height="80" fill="#123456"/></a>',
    )
    shapes = list(Presentation(str(_export(tmp_path))).slides[0].shapes)
    assert len(shapes) == 1
    assert _shape_link(shapes[0]) is None


@pytest.mark.parametrize(
    "href", ["https://example.org", "http://example.org", "mailto:a@example.org"]
)
def test_supported_schemes_are_accepted(href: str) -> None:
    """The three schemes a slide legitimately links to."""
    assert is_supported(href) is True


# --- embedded media -------------------------------------------------------


def _media_fixture(directory: Path, *, poster: bool = True) -> None:
    """Write a slide declaring embedded media, plus its source files."""
    (directory / "clip.mp4").write_bytes(_MP4)
    if poster:
        (directory / "poster.png").write_bytes(_PNG)
    poster_attr = ' data-pptx-poster="poster.png"' if poster else ""
    _slide(
        directory,
        '<rect x="120" y="80" width="640" height="360" '
        f'data-pptx-role="media" data-pptx-src="clip.mp4"{poster_attr}/>',
    )


def test_media_is_embedded_not_linked(tmp_path: Path) -> None:
    """The deck stays one forwardable file, so the bytes travel inside it."""
    _media_fixture(tmp_path)
    deck = _export(tmp_path)

    parts = [n for n in zipfile.ZipFile(deck).namelist() if "/media/" in n]
    assert any(name.endswith(".mp4") for name in parts)
    assert any(name.endswith(".png") for name in parts)


def test_a_media_rect_becomes_a_player_not_a_rectangle(tmp_path: Path) -> None:
    """The marker replaces the placeholder rather than drawing over it."""
    _media_fixture(tmp_path)
    shapes = list(Presentation(str(_export(tmp_path))).slides[0].shapes)
    assert len(shapes) == 1
    assert shapes[0].shape_type == 16  # MSO_SHAPE_TYPE.MEDIA


def test_media_without_a_poster_still_embeds(tmp_path: Path) -> None:
    """The poster is optional, though a deck without one reviews poorly."""
    _media_fixture(tmp_path, poster=False)
    deck = _export(tmp_path)
    assert any(
        n.endswith(".mp4") for n in zipfile.ZipFile(deck).namelist()
    )


def test_a_marker_without_a_source_is_refused() -> None:
    """A silent no-op would leave a hole where the player should be."""
    class _Element:
        def get(self, key, default=None):
            return {"data-pptx-role": "media"}.get(key, default)

    with pytest.raises(MediaMarkerError, match="data-pptx-src"):
        read_marker(_Element())


def test_an_unsupported_format_is_refused_at_export() -> None:
    """Better to fail here than to ship a deck that will not play."""
    class _Element:
        def get(self, key, default=None):
            return {
                "data-pptx-role": "media",
                "data-pptx-src": "clip.mkv",
            }.get(key, default)

    with pytest.raises(MediaMarkerError, match="unsupported format"):
        read_marker(_Element())


def test_a_media_source_outside_the_slide_directory_is_refused(tmp_path: Path) -> None:
    """The existing sidecar path policy applies to media too."""
    (tmp_path / "clip.mp4").write_bytes(_MP4)
    _slide(
        tmp_path,
        '<rect x="120" y="80" width="640" height="360" '
        'data-pptx-role="media" data-pptx-src="../clip.mp4"/>',
    )
    with pytest.raises(Exception, match="outside"):
        _export(tmp_path)


# --- template, master and theme -------------------------------------------


def _house_template(directory: Path) -> Path:
    """Build a template with a distinctive master name and a sample slide."""
    template = Presentation()
    template.slide_masters[0].name = "House Master"
    template.slides.add_slide(template.slide_layouts[0])
    path = directory / "house.potx"
    template.save(str(path))
    return path


def test_a_template_carries_its_master_into_the_deck(tmp_path: Path) -> None:
    """Without this the deck shipped python-pptx's default theme."""
    template = _house_template(tmp_path)
    _slide(tmp_path, '<rect x="10" y="10" width="200" height="80" fill="#123456"/>')

    deck = Presentation(str(_export(tmp_path, template=str(template))))
    assert deck.slide_masters[0].name == "House Master"


def test_the_templates_own_slides_are_removed(tmp_path: Path) -> None:
    """A template's example slides must not open the exported deck."""
    template = _house_template(tmp_path)
    _slide(tmp_path, '<rect x="10" y="10" width="200" height="80" fill="#123456"/>')

    deck = Presentation(str(_export(tmp_path, template=str(template))))
    assert len(deck.slides._sldIdLst) == 1


def test_a_named_layout_is_selected(tmp_path: Path) -> None:
    """Naming a layout picks it rather than the blank default."""
    presentation = open_presentation(None)
    assert choose_layout(presentation, "Title Slide").name == "Title Slide"


def test_layout_selection_is_case_insensitive() -> None:
    """Layout names are typed by humans."""
    presentation = open_presentation(None)
    assert choose_layout(presentation, "  title slide  ").name == "Title Slide"


def test_an_unknown_layout_names_what_is_available() -> None:
    """Silently falling back would build the deck on the wrong master."""
    presentation = open_presentation(None)
    with pytest.raises(TemplateError, match="available layouts"):
        choose_layout(presentation, "Nonexistent")


def test_the_default_layout_is_blank() -> None:
    """Slides are painted whole from SVG; placeholders would sit behind them."""
    assert choose_layout(open_presentation(None)).name == "Blank"


def test_a_missing_template_is_reported(tmp_path: Path) -> None:
    """A typo in the path must not silently produce an unthemed deck."""
    with pytest.raises(TemplateError, match="template not found"):
        open_presentation(tmp_path / "absent.potx")


def test_without_a_template_the_skill_canvas_is_used(tmp_path: Path) -> None:
    """The 16:9 canvas still applies when no template states a page size."""
    _slide(tmp_path, '<rect x="10" y="10" width="200" height="80" fill="#123456"/>')
    deck = Presentation(str(_export(tmp_path)))
    assert deck.slide_width > deck.slide_height


def test_a_template_with_a_different_aspect_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Slides are painted from a fixed canvas, so a mismatched page warns.

    Found by exporting a real deck rather than by reading the code: a 4:3
    template silently mapped 16:9 artwork onto a page it was not composed for.
    Nothing errored; the deck just came out subtly wrong, which is the failure
    mode hardest to catch in review.
    """
    template = _house_template(tmp_path)  # python-pptx's default is 4:3
    _slide(tmp_path, '<rect x="10" y="10" width="200" height="80" fill="#123456"/>')
    _export(tmp_path, template=str(template))

    output = capsys.readouterr().out
    assert "1.333:1" in output and "1.778:1" in output
    assert "not composed for" in output


def test_a_matching_template_aspect_is_silent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A correct template must not produce a warning to learn to ignore."""
    from pptx.util import Emu

    template = Presentation()
    template.slide_width, template.slide_height = Emu(12192000), Emu(6858000)
    path = tmp_path / "wide.potx"
    template.save(str(path))

    _slide(tmp_path, '<rect x="10" y="10" width="200" height="80" fill="#123456"/>')
    _export(tmp_path, template=str(path))

    assert "not composed for" not in capsys.readouterr().out
