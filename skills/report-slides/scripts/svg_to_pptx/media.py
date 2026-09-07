"""Embed audio and video into a slide from an SVG placeholder.

SVG has no element for a movie, so the deck declares one the same way it
declares a native table or chart: a `data-pptx-role` marker. A `<rect>` carries
the marker because a rect already states the geometry the player should occupy:

    <rect x="120" y="80" width="640" height="360"
          data-pptx-role="media"
          data-pptx-src="interview.mp4"
          data-pptx-poster="interview-frame.png"/>

`data-pptx-poster` is optional but strongly worth supplying. Without a poster
frame PowerPoint shows a plain grey rectangle in the slide, which reads as a
missing image to anyone reviewing the deck before it is presented -- and to the
model-vision gate, which cannot tell a deliberate player from a broken picture.

Media is embedded, not linked, so the deck stays a single file that can be
forwarded. That also means it carries the file's full weight; a large clip
belongs in a link (see `hyperlinks`) rather than inside the deck.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

#: `data-pptx-role` value that turns a rect into a media player.
MEDIA_ROLE = "media"

#: Container formats PowerPoint plays without an extra codec on a stock
#: install. Anything else is refused at export rather than producing a deck
#: that fails to play on the presenting machine.
SUPPORTED_SUFFIXES = frozenset({".mp4", ".m4v", ".mov", ".mp3", ".m4a", ".wav"})


class MediaMarkerError(ValueError):
    """Raised when a media marker cannot be honoured."""


def is_media_marker(element: Any) -> bool:
    """Report whether an element declares embedded media.

    Args:
        element: Any SVG element.

    Returns:
        True when the element carries the media role marker.
    """
    return element.get("data-pptx-role") == MEDIA_ROLE


def read_marker(element: Any) -> Dict[str, Optional[str]]:
    """Extract a media marker's source and optional poster frame.

    Args:
        element: The SVG element carrying the marker.

    Returns:
        `{"src": str, "poster": str | None}`.

    Raises:
        MediaMarkerError: If no source is named, or its format is unsupported.
    """
    src = (element.get("data-pptx-src") or "").strip()
    if not src:
        raise MediaMarkerError(
            'a data-pptx-role="media" element requires data-pptx-src naming the '
            "audio or video file to embed"
        )
    suffix = Path(src).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise MediaMarkerError(
            f"data-pptx-src {src!r} has an unsupported format {suffix!r}; "
            f"PowerPoint plays {', '.join(sorted(SUPPORTED_SUFFIXES))} without "
            "an additional codec"
        )
    poster = (element.get("data-pptx-poster") or "").strip() or None
    return {"src": src, "poster": poster}


def add_media(
    slide: Any,
    movie_path: Path,
    box: tuple,
    poster_path: Optional[Path] = None,
) -> Any:
    """Add one embedded player to a slide.

    Args:
        slide: The python-pptx slide.
        movie_path: The audio or video file, already resolved and verified to
            sit beside the deck's own sources.
        box: `(left, top, width, height)` in EMU.
        poster_path: Optional still shown before playback.

    Returns:
        The created movie shape.

    Raises:
        MediaMarkerError: If the file is missing or cannot be embedded.
    """
    if not movie_path.is_file():
        raise MediaMarkerError(f"media source not found: {movie_path}")
    if poster_path is not None and not poster_path.is_file():
        raise MediaMarkerError(f"media poster frame not found: {poster_path}")

    left, top, width, height = box
    try:
        return slide.shapes.add_movie(
            str(movie_path),
            left,
            top,
            width,
            height,
            poster_frame_image=None if poster_path is None else str(poster_path),
        )
    except Exception as exc:  # noqa: BLE001 - surface any embed failure as one type
        raise MediaMarkerError(
            f"could not embed {movie_path.name}: {exc}"
        ) from exc
