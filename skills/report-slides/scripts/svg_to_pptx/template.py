"""Build a deck on an organisation's own master, layouts and theme.

Every deck the converter produced started from python-pptx's built-in default
presentation and used its blank layout, so the exported file carried the
default theme: default fonts, default colour scheme, default master. Anyone
with a house template had to restyle the deck by hand after export, which is
exactly the work a template exists to avoid, and which cannot survive a
re-export.

A `.pptx` or `.potx` opened as the starting presentation brings its masters,
layouts and theme with it. Slides added afterwards inherit them, so the deck
carries the organisation's identity without the converter needing to know
anything about that identity.

The template's own slides are removed first. A template usually ships example
slides to show the intended styling; leaving them would put someone else's
placeholder content at the front of the deck.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from pptx import Presentation

#: Layout used when a template names none. A blank layout is the right default
#: for this converter specifically: it paints whole slides from SVG, so a
#: layout carrying title and body placeholders would leave empty prompt boxes
#: sitting behind the artwork.
BLANK_LAYOUT_NAME = "Blank"


class TemplateError(ValueError):
    """Raised when a template cannot be used as given."""


def open_presentation(template: Optional[Path]) -> Any:
    """Open a template as the starting presentation, or a default one.

    Args:
        template: A `.pptx` or `.potx` whose master, layouts and theme the deck
            should inherit. None starts from python-pptx's default.

    Returns:
        A presentation with no slides, ready to receive the deck's own.

    Raises:
        TemplateError: If the template is missing or cannot be opened.
    """
    if template is None:
        return Presentation()

    path = Path(template)
    if not path.is_file():
        raise TemplateError(f"template not found: {path}")
    try:
        presentation = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001 - any open failure is one condition
        raise TemplateError(f"could not open template {path}: {exc}") from exc

    _remove_all_slides(presentation)
    return presentation


def _remove_all_slides(presentation: Any) -> None:
    """Drop every slide a template shipped, keeping its masters and theme.

    python-pptx exposes no slide deletion, so the slide id list and its
    relationships are edited directly. Removing the relationship as well as the
    id matters: an orphaned relationship leaves the part in the package, and
    PowerPoint reports the file as needing repair.

    Args:
        presentation: The presentation to empty.
    """
    slide_id_list = presentation.slides._sldIdLst
    part = presentation.part
    for slide_id in list(slide_id_list):
        part.drop_rel(slide_id.rId)
        slide_id_list.remove(slide_id)


def layout_names(presentation: Any) -> List[str]:
    """List every layout name the presentation offers.

    Args:
        presentation: The opened presentation.

    Returns:
        Layout names in the order the template declares them.
    """
    return [layout.name for layout in presentation.slide_layouts]


def choose_layout(presentation: Any, name: Optional[str] = None) -> Any:
    """Pick the layout new slides are built on.

    Args:
        presentation: The opened presentation.
        name: Layout name to use, matched case-insensitively. None selects a
            blank layout when the template has one, and otherwise the last
            layout -- which is where the blank layout conventionally sits.

    Returns:
        The chosen slide layout.

    Raises:
        TemplateError: If a name was given and no layout matches. The message
            lists what the template does offer, because the alternative is a
            deck silently built on the wrong master.
    """
    layouts = list(presentation.slide_layouts)
    if not layouts:
        raise TemplateError("the template declares no slide layouts")

    if name is None:
        for layout in layouts:
            if layout.name.strip().casefold() == BLANK_LAYOUT_NAME.casefold():
                return layout
        return layouts[-1]

    wanted = name.strip().casefold()
    for layout in layouts:
        if layout.name.strip().casefold() == wanted:
            return layout
    available = ", ".join(repr(layout.name) for layout in layouts)
    raise TemplateError(
        f"no layout named {name!r} in the template; available layouts: {available}"
    )
