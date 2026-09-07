"""Carry a slide's speaker notes into the exported PPTX.

`slide_architect_agent` is instructed to identify speaker notes as one of a
slide's content elements, and the narrative planner writes them -- but nothing
downstream ever put them anywhere, so every note the pipeline produced was
dropped at export. A research deck without its narration is materially less
useful than one with it: the notes are where the caveats, the numbers behind a
claim, and the "what to say next" live.

Two sources are read, in this order:

1. A sibling ``<stem>.notes.md`` beside the slide's SVG. This matches how the
   skill already keeps per-deck artifacts (``slide_data.json``,
   ``chart_list.md``) and is the easier surface to write and review.
2. The SVG root's ``<desc>`` element, the SVG-native place for descriptive
   text. Notes travel inside the slide file, so they cannot drift away from it.

A slide with neither gets no notes slide at all, rather than an empty one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

#: Suffix of the sibling notes file, e.g. `slide-03.svg` -> `slide-03.notes.md`.
NOTES_SUFFIX = ".notes.md"

#: SVG namespace, for locating the root `<desc>`.
_SVG_NS = "http://www.w3.org/2000/svg"


def notes_path_for(svg_path: Path) -> Path:
    """Return the sibling notes path for one slide.

    Args:
        svg_path: Path of the slide's SVG.

    Returns:
        The path a notes file would occupy, whether or not it exists.
    """
    return svg_path.with_suffix("").with_name(svg_path.stem + NOTES_SUFFIX)


def read_speaker_notes(svg_path: Path, root: Optional[Any] = None) -> Optional[str]:
    """Read one slide's speaker notes, or None when it has none.

    Args:
        svg_path: Path of the slide's SVG.
        root: The parsed SVG root, when the caller already has one. Passing it
            avoids a second parse; omitting it skips the `<desc>` fallback.

    Returns:
        The notes text with surrounding whitespace stripped, or None when the
        slide has no notes. Whitespace-only sources count as no notes -- an
        empty notes pane is worse than none, because it reads as deliberate.
    """
    sidecar = notes_path_for(svg_path)
    if sidecar.is_file():
        # `utf-8-sig` rather than `utf-8`: a notes file written by a Windows
        # tool -- PowerShell's `Out-File -Encoding utf8`, Notepad, plenty of
        # editors -- starts with a byte-order mark, and reading it as plain
        # UTF-8 carries a U+FEFF into the first line of the presenter's notes
        # where it shows up as a stray character. Decoding as `utf-8-sig` drops
        # the mark when present and is identical to `utf-8` when it is not.
        text = sidecar.read_text(encoding="utf-8-sig").strip()
        if text:
            return text

    if root is None:
        return None
    for tag in (f"{{{_SVG_NS}}}desc", "desc"):
        # Only the root's own `<desc>` is narration; a `<desc>` nested inside a
        # shape describes that shape, and pulling it up would put alt text for
        # one rectangle into the presenter's notes.
        element = root.find(tag)
        if element is not None:
            text = "".join(element.itertext()).strip()
            if text:
                return text
    return None


def apply_speaker_notes(slide: Any, notes: Optional[str]) -> bool:
    """Attach notes to a slide, creating its notes slide only when needed.

    Args:
        slide: The python-pptx slide to annotate.
        notes: Notes text, or None to leave the slide untouched.

    Returns:
        True when notes were written.
    """
    if not notes:
        return False
    slide.notes_slide.notes_text_frame.text = notes
    return True
