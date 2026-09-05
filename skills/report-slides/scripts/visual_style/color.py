"""Colour rules: WCAG contrast floors and design-system palette conformance."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PIL import ImageColor

from design_tokens import DesignTokens

from .report import Finding
from .scene import Box, Scene

RULES: Tuple[str, ...] = ("text-contrast", "graphic-contrast", "token-color")

_NON_COLOURS = frozenset({"none", "transparent", "currentcolor"})
_LARGE_SIZE = 24.0
_LARGE_BOLD_SIZE = 18.66
_BOLD_WEIGHT = 700


def normalize_hex(value: Optional[str]) -> Optional[str]:
    """Normalise an SVG paint value to a six-digit lowercase hex.

    Named colours are resolved, because the existing SVG in this repository uses
    `fill="white"` freely. Treating a named colour as "not a colour" would
    silently exempt it from every contrast rule, which is the failure mode this
    linter exists to remove. Pillow's `ImageColor` is used rather than the
    converter's `CSS_COLORS` table so that the linter does not acquire a
    python-pptx dependency; Pillow is already required for font metrics.

    Args:
        value: The raw paint value, such as `#FFF`, `white`, `rgb(0,0,0)`,
            `none`, or `url(#g)`.

    Returns:
        The normalised hex, or None when the value names no literal colour --
        `none`, `transparent`, `currentColor`, or a paint-server reference.
    """
    if not value:
        return None
    text = value.strip().lower()
    if text in _NON_COLOURS:
        return None
    try:
        rgb = ImageColor.getrgb(text)
    except ValueError:
        # A paint-server reference such as url(#grad1) names no single colour;
        # gradient conformance is out of this rule's scope by design.
        return None
    return "#{:02x}{:02x}{:02x}".format(*rgb[:3])


def _channel_luminance(channel: float) -> float:
    """Linearise one sRGB channel per WCAG 2.x.

    Args:
        channel: Channel value in the range 0..1.

    Returns:
        The linearised channel value.
    """
    if channel <= 0.03928:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """Return the WCAG relative luminance of a colour.

    Args:
        hex_color: A normalised six-digit hex colour.

    Returns:
        Relative luminance in the range 0..1.

    Raises:
        ValueError: If the colour is not a normalisable hex value.
    """
    normalised = normalize_hex(hex_color)
    if normalised is None:
        raise ValueError(f"cannot compute luminance of {hex_color!r}")
    channels = [int(normalised[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [_channel_luminance(channel) for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(a: str, b: str) -> float:
    """Return the WCAG contrast ratio between two colours.

    Args:
        a: First colour.
        b: Second colour.

    Returns:
        A ratio in the range 1.0..21.0.

    Raises:
        ValueError: If either colour is not a normalisable hex value.
    """
    lum_a = relative_luminance(a)
    lum_b = relative_luminance(b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def _role_index(tokens: DesignTokens) -> Dict[str, str]:
    """Build a hex-to-role-name index over the colour roles.

    Args:
        tokens: The resolved token set.

    Returns:
        A mapping from normalised hex to role name.
    """
    index: Dict[str, str] = {}
    for role, value in tokens.raw["color"]["roles"].items():
        normalised = normalize_hex(str(value))
        if normalised is not None:
            index.setdefault(normalised, role)
    return index


def color_role(hex_color: str, tokens: DesignTokens) -> Optional[str]:
    """Reverse-map a colour to its `color.roles` key.

    Args:
        hex_color: The colour to look up.
        tokens: The resolved token set.

    Returns:
        The role name, or None when the colour is not a role colour.
    """
    normalised = normalize_hex(hex_color)
    if normalised is None:
        return None
    return _role_index(tokens).get(normalised)


def _palette(tokens: DesignTokens) -> Dict[str, str]:
    """Return every colour the design system declares.

    Args:
        tokens: The resolved token set.

    Returns:
        A mapping from normalised hex to a human-readable source label.
    """
    palette: Dict[str, str] = {}
    for role, value in tokens.raw["color"]["roles"].items():
        normalised = normalize_hex(str(value))
        if normalised is not None:
            palette.setdefault(normalised, f"color.roles.{role}")
    for position, value in enumerate(tokens.raw["chart"]["palette"]):
        normalised = normalize_hex(str(value))
        if normalised is not None:
            palette.setdefault(normalised, f"chart.palette[{position}]")
    return palette


def background_at(x: float, y: float, scene: Scene, tokens: DesignTokens,
                  exclude: Optional[str] = None) -> str:
    """Return the effective background colour at a point.

    Args:
        x: Point x coordinate.
        y: Point y coordinate.
        scene: The parsed slide.
        tokens: The resolved token set.
        exclude: Element id to ignore, so an element is not its own background.

    Returns:
        A normalised hex colour; `color.roles.bg` when nothing covers the point.

    Raises:
        ValueError: If `color.roles.bg` is not a literal hex colour.
    """
    covering: List[Box] = [
        box for box in scene.boxes
        if box.element_id != exclude
        and box.contains_point(x, y)
        and normalize_hex(box.fill) is not None
    ]
    if covering:
        smallest = min(covering, key=lambda box: box.area)
        normalised = normalize_hex(smallest.fill)
        if normalised is not None:
            return normalised
    fallback = normalize_hex(tokens.color("bg"))
    if fallback is None:
        raise ValueError("color.roles.bg is not a literal hex colour")
    return fallback


def _is_large_text(size: float, weight: int) -> bool:
    """Return whether a run qualifies as WCAG large text.

    Args:
        size: Font size in SVG units.
        weight: Numeric font weight.

    Returns:
        True for large text.
    """
    if size >= _LARGE_SIZE:
        return True
    return weight >= _BOLD_WEIGHT and size >= _LARGE_BOLD_SIZE


def check_text_contrast(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report text below its WCAG contrast floor.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `text-contrast` error per offending run.
    """
    contrast = tokens.raw["color"]["contrast"]
    findings: List[Finding] = []
    for run in scene.texts:
        foreground = normalize_hex(run.fill)
        if foreground is None:
            continue
        bbox = run.bbox()
        background = background_at(bbox.x + bbox.w / 2, bbox.y + bbox.h / 2,
                                   scene, tokens, exclude=run.element_id)
        large = _is_large_text(run.size, run.weight)
        floor = float(contrast["large_text_min" if large else "text_min"])
        ratio = contrast_ratio(foreground, background)
        if ratio < floor:
            findings.append(Finding(
                rule="text-contrast", severity="error",
                message=f"{run.element_id} is {foreground} on {background} at "
                        f"{ratio:.2f}:1; the "
                        f"{'large text' if large else 'text'} floor is "
                        f"{floor:.1f}",
                element_id=run.element_id, location=(run.x, run.y)))
    return findings


def check_graphic_contrast(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report non-decorative graphics below the WCAG non-text floor.

    The judged colour is the stroke when a shape has one, otherwise the fill:
    an outlined node is read by its outline.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `graphic-contrast` error per offending shape.
    """
    floor = float(tokens.raw["color"]["contrast"]["graphic_min"])
    findings: List[Finding] = []
    for box in scene.boxes:
        paint = normalize_hex(box.stroke) or normalize_hex(box.fill)
        if paint is None:
            continue
        role = color_role(paint, tokens)
        if role is not None and tokens.is_decorative(role):
            continue
        background = background_at(box.x + box.w / 2, box.y + box.h / 2,
                                   scene, tokens, exclude=box.element_id)
        ratio = contrast_ratio(paint, background)
        if ratio < floor:
            findings.append(Finding(
                rule="graphic-contrast", severity="error",
                message=f"{box.element_id} is {paint} on {background} at "
                        f"{ratio:.2f}:1; the graphic floor is {floor:.1f}",
                element_id=box.element_id, location=(box.x, box.y)))
    return findings


def check_token_colors(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report colours that are not declared anywhere in the token file.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `token-color` error per offending element.
    """
    palette = _palette(tokens)
    findings: List[Finding] = []
    used: List[Tuple[str, str, float, float]] = []
    for box in scene.boxes:
        for paint in (box.fill, box.stroke):
            normalised = normalize_hex(paint)
            if normalised is not None:
                used.append((box.element_id, normalised, box.x, box.y))
    for run in scene.texts:
        normalised = normalize_hex(run.fill)
        if normalised is not None:
            used.append((run.element_id, normalised, run.x, run.y))
    for element_id, paint, x, y in used:
        if paint in palette:
            continue
        findings.append(Finding(
            rule="token-color", severity="error",
            message=f"{element_id} uses {paint}, which is in neither "
                    f"color.roles nor chart.palette",
            element_id=element_id, location=(x, y)))
    return findings


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every colour rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All colour findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_text_contrast(scene, tokens))
    findings.extend(check_graphic_contrast(scene, tokens))
    findings.extend(check_token_colors(scene, tokens))
    return findings
