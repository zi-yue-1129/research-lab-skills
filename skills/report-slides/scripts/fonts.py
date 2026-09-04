"""Font stack resolution and text metrics for report-slides.

Two jobs. First, pick the font family that is actually installed, so the SVG
preview and the PPTX export render with the same face. Second, measure real
glyph advance widths, so overflow checks do not rely on character counts.
"""
from __future__ import annotations

import functools
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import ImageFont

_GENERIC_FAMILIES = frozenset(
    {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"}
)
_FC_TIMEOUT_SECONDS = 15


class FontError(RuntimeError):
    """Raised when no requested font family is installed, or metrics fail.

    Never caught in order to fall back to an arbitrary face: a substituted font
    changes every text extent on the slide, so the caller must be told.
    """


def parse_font_stack(css_family: str) -> List[str]:
    """Split a CSS `font-family` value into ordered family names.

    Multi-word names keep their spaces; surrounding quotes are stripped. This is
    the behaviour `svg_to_pptx/shapes.py` lacked, where splitting on whitespace
    turned `'Helvetica Neue'` into `Helvetica`.

    Args:
        css_family: A CSS `font-family` value.

    Returns:
        Family names in declaration order, including generic keywords.
    """
    families: List[str] = []
    for part in css_family.split(","):
        name = part.strip().strip("'\"").strip()
        name = re.sub(r"\s+", " ", name)
        if name:
            families.append(name)
    return families


@functools.lru_cache(maxsize=256)
def is_family_available(family: str) -> bool:
    """Return whether fontconfig resolves a family to itself.

    `fc-match` always returns some face, so availability is determined by
    comparing the resolved family against the requested one.

    Args:
        family: A concrete family name, not a CSS generic keyword.

    Returns:
        True when the family is installed.

    Raises:
        FontError: If fontconfig is unavailable or fails to run.
    """
    if family.lower() in _GENERIC_FAMILIES:
        return False
    if shutil.which("fc-match") is None:
        raise FontError("fontconfig (fc-match) is required to resolve font families")
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{family}", family],
            capture_output=True, text=True, timeout=_FC_TIMEOUT_SECONDS, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise FontError(f"fc-match failed for {family!r}: {exc}") from exc
    resolved = {alias.strip().lower() for alias in result.stdout.split(",")}
    return family.strip().lower() in resolved


def resolve_font_stack(css_family: str) -> str:
    """Return the first installed family in a CSS font stack.

    Args:
        css_family: A CSS `font-family` value.

    Returns:
        The first family name in the stack that is installed.

    Raises:
        FontError: If no concrete family in the stack is installed.
    """
    families = parse_font_stack(css_family)
    for family in families:
        if is_family_available(family):
            return family
    raise FontError(
        f"no installed font family in stack {css_family!r}; "
        f"tried {families}. Install one of them or change the token font stack."
    )


# fontconfig has its own weight scale and does not accept CSS numbers. Without
# this map every weight resolves to the same face, and a bold title is measured
# with the regular one -- on this machine that under-measures by 12.9%, which is
# the difference between a title that fits on two lines and one that does not.
FC_WEIGHT_NAMES: Dict[int, str] = {
    100: "thin", 200: "extralight", 300: "light", 400: "regular",
    500: "medium", 600: "demibold", 700: "bold", 800: "extrabold",
    900: "black",
}


def _fc_weight(weight: int) -> str:
    """Return the fontconfig weight constant nearest a CSS numeric weight.

    Args:
        weight: A CSS numeric font weight.

    Returns:
        The fontconfig weight constant, e.g. `bold` for 700. Values between the
        nine CSS steps round to the nearest step rather than raising: a token
        file is validated against the 100-900 range by the schema, and an
        unusual-but-legal 650 should resolve to a face, not fail the render.
    """
    return FC_WEIGHT_NAMES[min(FC_WEIGHT_NAMES, key=lambda step: abs(step - weight))]


@functools.lru_cache(maxsize=256)
def font_file_for(family: str, weight: int = 400) -> Path:
    """Return the font file backing a family at a weight.

    Args:
        family: A concrete, installed family name.
        weight: CSS numeric font weight. Cached as part of the key, so regular
            and bold never share an entry.

    Returns:
        Path to the font file.

    Raises:
        FontError: If the family is not installed or has no file.
    """
    if not is_family_available(family):
        raise FontError(f"font family {family!r} is not installed")
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{file}", f"{family}:weight={_fc_weight(weight)}"],
            capture_output=True, text=True, timeout=_FC_TIMEOUT_SECONDS, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise FontError(f"fc-match failed for {family!r}: {exc}") from exc
    path = Path(result.stdout.strip())
    if not path.is_file():
        raise FontError(f"font family {family!r} resolved to missing file {path}")
    return path


def text_width(text: str, family: str, size: float, weight: int = 400) -> float:
    """Measure the advance width of a string in SVG units.

    Args:
        text: The string to measure.
        family: A concrete, installed family name.
        size: Font size in SVG units, which map 1:1 to PowerPoint points.
        weight: CSS numeric weight. Selects the concrete face, because a bold
            face is materially wider than its regular sibling and measuring one
            with the other is how a title silently overflows.

    Returns:
        The advance width in SVG units.

    Raises:
        FontError: If the family is not installed or the face cannot be loaded.
    """
    return float(_face(family, size, weight).getlength(text))


def vertical_metrics(
    family: str, size: float, weight: int = 400
) -> Tuple[float, float]:
    """Measure a face's ascent and descent in SVG units.

    These are the face's own design metrics, not the ink extent of a particular
    string: they are what a renderer must reserve above and below a baseline for
    *any* text at this size, which is what a safe-area or overlap check needs.

    They are measured rather than assumed because the assumption is wrong. A
    common guess is 0.8 em of ascent and no descent; DejaVu Sans actually
    reports ascent 30 / descent 8 at size 32, and ascent 12 / descent 3 at
    size 12. A footer baseline placed on the safe-area boundary therefore hangs
    three units outside it.

    Args:
        family: A concrete, installed family name.
        size: Font size in SVG units, which map 1:1 to PowerPoint points.
        weight: CSS numeric font weight. A bold face can carry a taller ascent
            than its regular sibling; on this machine DejaVu Sans does not, but
            that is a property of one family and not a rule.

    Returns:
        `(ascent, descent)`, both positive, in SVG units. `ascent` is the
        distance from the baseline to the top of the em box; `descent` the
        distance from the baseline down to its bottom.

    Raises:
        FontError: If the family is not installed or the face cannot be loaded.
    """
    ascent, descent = _face(family, size, weight).getmetrics()
    return float(ascent), float(descent)


def _face(family: str, size: float, weight: int = 400) -> "ImageFont.FreeTypeFont":
    """Load a Pillow face for a family at a size and weight.

    Args:
        family: A concrete, installed family name.
        size: Font size in SVG units.
        weight: CSS numeric font weight.

    Returns:
        The loaded face.

    Raises:
        FontError: If the family is not installed or the face cannot be loaded.
    """
    font_path = font_file_for(family, weight)
    try:
        return ImageFont.truetype(str(font_path), size=max(1, int(round(size))))
    except OSError as exc:
        raise FontError(
            f"cannot load face {font_path} for {family!r} at size {size}: {exc}"
        ) from exc
