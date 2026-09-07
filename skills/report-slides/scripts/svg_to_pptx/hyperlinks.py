"""Carry SVG anchors through to clickable PPTX hyperlinks.

A research deck cites things, and a citation the reader cannot follow is worth
much less than one they can. SVG already has the right authoring surface for
this -- `<a href="...">` wrapping whatever should be clickable -- and it needs
no new convention to learn.

Until now the converter had no branch for `<a>` at all. Its children matched
nothing in the element dispatch, so **everything inside an anchor was silently
dropped from the exported deck**: no link, and no shape either. Handling the
element fixes the content loss and adds the link in the same move.

PowerPoint attaches links two different ways, and which one applies depends on
what was wrapped:

* a text run gets `run.hyperlink`, so only the linked words are clickable and
  PowerPoint styles them as a link;
* any other shape gets `shape.click_action.hyperlink`, making the whole shape a
  click target.

Only `http`, `https` and `mailto` are accepted. A deck is a file that gets
forwarded, and a `file:` link resolving on the author's machine -- or a
`javascript:` URI arriving from generated SVG -- is not something to hand a
reader silently.
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlsplit

#: Schemes a slide may link to. Everything else is refused rather than exported
#: as a link the reader cannot trust.
ALLOWED_SCHEMES = frozenset({"http", "https", "mailto"})

#: XLink namespace, for the `xlink:href` form older SVG generators still emit.
_XLINK_NS = "http://www.w3.org/1999/xlink"


def anchor_href(element: Any) -> Optional[str]:
    """Return an anchor's target, or None when it has none worth following.

    Args:
        element: An SVG `<a>` element.

    Returns:
        The href when it is present and uses an allowed scheme, else None.
    """
    href = element.get("href") or element.get(f"{{{_XLINK_NS}}}href")
    if not href:
        return None
    href = href.strip()
    if not href:
        return None
    return href if is_supported(href) else None


def is_supported(href: str) -> bool:
    """Report whether a target is safe to export as a link.

    Args:
        href: The candidate target.

    Returns:
        True for `http`, `https` and `mailto`. A scheme-relative `//host/path`
        is refused too: it inherits whatever scheme the opening application
        picks, which is not a decision to leave to chance in a file that
        travels.
    """
    if href.startswith("//"):
        return False
    scheme = urlsplit(href).scheme.lower()
    return scheme in ALLOWED_SCHEMES


def apply_to_shape(shape: Any, href: Optional[str]) -> bool:
    """Make a whole shape a click target.

    Args:
        shape: A python-pptx shape.
        href: The target, or None to leave the shape alone.

    Returns:
        True when a link was attached.
    """
    if not href or shape is None:
        return False
    try:
        shape.click_action.hyperlink.address = href
    except (AttributeError, NotImplementedError):
        # Connectors and a few autoshape subclasses expose no click action.
        # A missing link is a smaller defect than a failed export, and the
        # summary reports how many links were attached, so a silent shortfall
        # is still visible.
        return False
    return True


def apply_to_text(text_box: Any, href: Optional[str]) -> bool:
    """Link every run in a text box, so only the words are clickable.

    Args:
        text_box: A python-pptx textbox shape.
        href: The target, or None to leave the text alone.

    Returns:
        True when at least one run was linked.
    """
    if not href or text_box is None:
        return False
    linked = False
    for paragraph in text_box.text_frame.paragraphs:
        for run in paragraph.runs:
            run.hyperlink.address = href
            linked = True
    if not linked:
        # A textbox whose text was set without runs has nothing to link;
        # falling back to the shape keeps the target reachable.
        return apply_to_shape(text_box, href)
    return linked
