#!/usr/bin/env python3
"""generate_slides.py — Research Report SVG Slide Generator (Path A)

Usage:
    python scripts/generate_slides.py --data slide_data.json --out ./output/
    python scripts/generate_slides.py --data slide_data.json --out ./output/ --slide 5

Slide types:
    title, bullet_list, bar_chart, table, metric_cards, two_column, timeline, conclusion
"""

import json
import argparse
import os
from pathlib import Path
from typing import Dict, Optional, Sequence

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens, TokenError, TypeRole
from fonts import resolve_font_stack, text_width, vertical_metrics
from presentation_gates import ProductionGateError, assert_production_allowed
from presentation_state import find_project_root


# ── Style constants ───────────────────────────────────────────────────────────

S = {
    "w":      1200,
    "h":      675,
    "bg":     "#ffffff",
    "accent": "#1e3a5f",
    "good":   "#059669",
    "warn":   "#d97706",
    "danger": "#dc2626",
    "blue":   "#3b82f6",
    "card":   "#f8fafc",
    "border": "#e2e8f0",
    "body":   "#374151",
    "muted":  "#64748b",
    "white":  "#ffffff",
    "font":   "'Helvetica Neue', Arial, sans-serif",
    "top_bar_h": 6,
}

TYPE: Dict[str, TypeRole] = {}
_TOKENS: Optional[DesignTokens] = None


def apply_tokens(tokens_path: Optional[Path]) -> None:
    """Load a design-token file into the module-level style state.

    Args:
        tokens_path: Path to a `.tokens.yaml` file, or None for the shipped
            default contract.

    Raises:
        TokenError: If the token file is missing or schema-invalid.
        FontError: If no family in the token font stack is installed.
    """
    global _TOKENS
    _TOKENS = DesignTokens.load(tokens_path or DEFAULT_TOKENS_PATH)
    TYPE.clear()
    for role in _TOKENS.raw["typography"]["roles"]:
        TYPE[role] = _TOKENS.type_role(role)
    S["w"] = _TOKENS.raw["canvas"]["width"]
    S["h"] = _TOKENS.raw["canvas"]["height"]
    S["grid"] = _TOKENS.raw["canvas"]["grid"]
    S["safe"] = dict(_TOKENS.raw["canvas"]["safe_area"])
    S["spacing"] = list(_TOKENS.raw["spacing"]["scale"])
    for role in ("bg", "body", "muted", "card", "primary",
                 "positive", "warn", "danger", "line", "divider"):
        S[role] = _TOKENS.color(role)
    # Legacy key names still referenced by the renderers.
    S["accent"] = _TOKENS.color("primary")
    S["good"] = _TOKENS.color("positive")
    S["border"] = _TOKENS.color("divider")
    S["blue"] = _TOKENS.raw["chart"]["palette"][0]
    S["white"] = "#ffffff"
    S["font"] = _TOKENS.font_stack("sans")
    S["font_resolved"] = resolve_font_stack(S["font"])
    S["top_bar_h"] = 0


def _role(role: str) -> TypeRole:
    """Return one resolved type role.

    Args:
        role: Role key such as `body`.

    Returns:
        The resolved `TypeRole`.

    Raises:
        RuntimeError: If `apply_tokens` has not been called.
        TokenError: If the role is undefined.
    """
    if not TYPE:
        raise RuntimeError(
            "apply_tokens() must be called before rendering; "
            "type roles are not loaded"
        )
    if role not in TYPE:
        raise TokenError(
            f"undefined type role {role!r}; defined roles: {sorted(TYPE)}"
        )
    return TYPE[role]


def t_size(role: str) -> float:
    """Return the font size for a type role.

    Args:
        role: Role key such as `body`.

    Returns:
        The role's font size in SVG units.
    """
    return _role(role).size


def t_weight(role: str) -> int:
    """Return the numeric font weight for a type role.

    Args:
        role: Role key such as `body`.

    Returns:
        The role's CSS numeric font weight.
    """
    return _role(role).weight


def t_lh(role: str) -> float:
    """Return the line-height multiplier for a type role.

    Args:
        role: Role key such as `body`.

    Returns:
        The role's line-height multiplier.
    """
    return _role(role).line_height


# ── Style loading ─────────────────────────────────────────────────────────────

def _parse_frontmatter(path: str) -> dict:
    """Parse YAML frontmatter from a .md file without requiring PyYAML."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"  [style] Cannot read {path}: {e}")
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict = {}
    for line in lines[1:]:
        stripped = line.rstrip("\n")
        if stripped.strip() == "---":
            break
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val:
            fm[key] = val
    return fm


def apply_style(style_path: str) -> None:
    """Load a style .md file and override colour keys in the global S dict.

    Style Markdown remains a colour override for backwards compatibility; sizes
    and spacing come from the token contract. An unparsable or empty style file
    raises: a silently ignored style is indistinguishable from an applied one.

    Args:
        style_path: Path to a style `.md` file with YAML frontmatter.

    Raises:
        ValueError: If the file has no usable frontmatter keys.
    """
    fm = _parse_frontmatter(style_path)
    if not fm:
        raise ValueError(
            f"style file {style_path} has no usable YAML frontmatter; "
            f"expected keys such as primary/bg/body (see references/styles/STYLES.md)"
        )
    key_map = {
        "primary":  "accent",
        "bg":       "bg",
        "body":     "body",
        "muted":    "muted",
        "border":   "border",
        "card":     "card",
        "positive": "good",
        "warn":     "warn",
        "danger":   "danger",
        "font":     "font",
    }
    for style_key, s_key in key_map.items():
        if style_key in fm:
            S[s_key] = fm[style_key]
    if "primary" in fm:
        S["primary"] = fm["primary"]
    if "font" in fm:
        S["font_resolved"] = resolve_font_stack(fm["font"])
    # `top_bar_h` is deliberately no longer read: the top accent bar is gone,
    # so honouring the key would silently do nothing.
    print(f"  [style] Applied: {style_path}")


# Chart drawing area
CL, CR, CT, CB = 130, 1100, 100, 520
CW, CH = CR - CL, CB - CT


# ── Text helpers ──────────────────────────────────────────────────────────────

def esc(v) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def wrap(text: str, max_chars: int = 60) -> list:
    words = str(text).split()
    lines, cur, n = [], [], 0
    for w in words:
        if n + len(w) + 1 > max_chars and cur:
            lines.append(" ".join(cur))
            cur, n = [w], len(w)
        else:
            cur.append(w)
            n += len(w) + 1
    if cur:
        lines.append(" ".join(cur))
    return lines or [""]


def tlines(lines: list, x, y, size, color, anchor="start", weight="normal",
           lh=1.45, *, role: str) -> str:
    """Render a multi-line text element.

    Args:
        lines: Already-wrapped lines, one per rendered line.
        x: Left, centre, or right coordinate, per `anchor`.
        y: Baseline of the first line.
        size: Font size in SVG units.
        color: Fill colour.
        anchor: SVG `text-anchor` value.
        weight: SVG `font-weight` value.
        lh: Line-height multiplier, applied to `size` for each `dy` after the
            first line.
        role: The typography role this text realises. Keyword-only and
            mandatory: the visual linter skips a `<text>` with no
            `data-style-role`, so an optional marker with a default would let a
            caller silently disable the type-floor and colour rules for its
            text.

    Returns:
        SVG markup for one `<text>` element.
    """
    spans = []
    for i, line in enumerate(lines):
        dy = "0" if i == 0 else f"{size * lh:.1f}"
        spans.append(f'<tspan x="{x}" dy="{dy}">{esc(line)}</tspan>')
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" text-anchor="{anchor}" '
            f'data-style-role="{role}">{"".join(spans)}</text>')


def measured_width(text: str, role: str) -> float:
    """Measure a string's advance width at a type role's size.

    Args:
        text: The string to measure.
        role: Type role key, such as `body`.

    Returns:
        Advance width in SVG units.
    """
    return text_width(text, S["font_resolved"], t_size(role), t_weight(role))


def wrap_to_width(text: str, max_width: float, role: str) -> list:
    """Wrap text to a pixel budget using real font metrics.

    Character-count wrapping cannot survive a size change: 88 characters at 14
    units and at 21 units occupy different widths. A word wider than the budget
    is kept on its own line rather than dropped.

    Args:
        text: The string to wrap.
        max_width: Available width in SVG units.
        role: Type role key used for measurement.

    Returns:
        Wrapped lines; always at least one entry.
    """
    words = str(text).split()
    if not words:
        return [""]
    lines: list = []
    current: list = []
    for word in words:
        candidate = " ".join(current + [word])
        if current and measured_width(candidate, role) > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


# ── Common slide frame ────────────────────────────────────────────────────────

_FRAME_VARIANTS = ("left", "centered")


def frame(title: str, footer: str = "", *, variant: str = "left") -> str:
    """Render the shared slide frame: title, rule, and footer.

    The former 6px top accent bar and centred 20pt title are gone. The title now
    uses the `slide_title` role inside the token safe area, and the rule sits
    under the title's baseline rather than at a fixed y=54.

    Args:
        title: Slide title text.
        footer: Optional footer text, rendered at the `footnote` role.
        variant: `left` for the standard left-aligned title, `centered` for
            section dividers.

    Returns:
        SVG markup for the frame elements.

    Raises:
        ValueError: If `variant` is not a known frame variant.
    """
    if variant not in _FRAME_VARIANTS:
        raise ValueError(
            f"unknown frame variant {variant!r}; expected one of {_FRAME_VARIANTS}"
        )
    safe = S["safe"]
    size = t_size("slide_title")
    # `size` is used here, not the measured ascent, because three later tasks
    # place their content against `rule_y = safe.top + slide_title + 16`. It is
    # a conservative proxy: DejaVu Sans reports ascent 30 at size 32, so the
    # title's em box starts 2 units *inside* the safe area. Task 6's test pins
    # that, so a font whose ascent exceeds its em size fails loudly rather than
    # clipping silently.
    baseline = safe["top"] + size
    rule_y = baseline + 16
    x = S["w"] / 2 if variant == "centered" else safe["left"]
    anchor = "middle" if variant == "centered" else "start"

    parts = [
        f'<rect width="{S["w"]}" height="{S["h"]}" fill="{S["bg"]}" '
        f'data-bleed="true"/>',
        f'<text x="{x:g}" y="{baseline:g}" font-size="{size:g}" '
        f'font-weight="{t_weight("slide_title")}" fill="{S["accent"]}" '
        f'data-style-role="slide_title" '
        f'text-anchor="{anchor}">{esc(title)}</text>',
        f'<line x1="{safe["left"]}" y1="{rule_y:g}" '
        f'x2="{S["w"] - safe["right"]}" y2="{rule_y:g}" '
        f'stroke="{S["divider"]}" stroke-width="1.5" '
        f'data-bleed="true" data-style-role="divider"/>',
    ]
    if footer:
        fs = t_size("footnote")
        # The baseline is lifted by the measured descent so the footer's
        # descenders end *on* the safe-area boundary rather than three units
        # past it. Placing the baseline on the boundary is the obvious-looking
        # choice and is wrong: plan 2's `safe-area` rule reports it on every
        # slide that carries a footer.
        _, descent = vertical_metrics(
            S["font_resolved"], fs, t_weight("footnote"))
        baseline_y = S["h"] - safe["bottom"] - descent
        parts.append(
            f'<text x="{S["w"] - safe["right"]}" y="{baseline_y:g}" '
            f'font-size="{fs:g}" fill="{S["muted"]}" '
            f'data-style-role="footnote" '
            f'text-anchor="end">{esc(footer)}</text>'
        )
    return "\n  ".join(parts)


def svg(body: str) -> str:
    """Wrap slide body markup in the root SVG element.

    Args:
        body: Slide content markup.

    Returns:
        A complete SVG document string.
    """
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {S["w"]} {S["h"]}" '
            f'font-family="{S["font_resolved"]}">\n'
            f'  {body}\n</svg>\n')


# ── Renderers ─────────────────────────────────────────────────────────────────

def render_title(sl: dict, meta: dict) -> str:
    title    = sl.get("title",    meta.get("experiment", "Research Report"))
    subtitle = sl.get("subtitle", "")
    author   = sl.get("author",   "")
    date     = sl.get("date",     meta.get("date", ""))
    footer   = meta.get("footer", "")
    cx       = 600

    # The two 8px accent bars that used to run the full width at y=0 and y=667
    # are gone with the rest of the templated signature removed in Task 6.
    parts = [
        f'<rect width="{S["w"]}" height="{S["h"]}" fill="{S["bg"]}" '
        f'data-bleed="true"/>',
    ]

    title_role = "deck_title"
    title_lines = wrap_to_width(title, S["w"] - 2 * S["safe"]["left"] - 160, title_role)
    title_adv = t_size(title_role) * t_lh(title_role)
    title_y = 255 - (len(title_lines) - 1) * (title_adv / 2)
    parts.append(tlines(title_lines, cx, title_y, t_size(title_role),
                        S["accent"], "middle", str(t_weight(title_role)),
                        t_lh(title_role), role=title_role))

    div_y = title_y + len(title_lines) * title_adv
    parts.append(f'<line x1="200" y1="{div_y:g}" x2="1000" y2="{div_y:g}" '
                 f'stroke="{S["divider"]}" stroke-width="1.5"/>')

    base_y = div_y + 40
    if subtitle:
        sub_role = "takeaway"
        sub_lines = wrap_to_width(subtitle, S["w"] - 2 * S["safe"]["left"] - 120,
                                  sub_role)
        parts.append(tlines(sub_lines, cx, base_y, t_size(sub_role),
                            S["muted"], "middle", str(t_weight(sub_role)),
                            t_lh(sub_role), role=sub_role))
        base_y += len(sub_lines) * t_size(sub_role) * t_lh(sub_role) + 12

    meta_str = "  ·  ".join(filter(None, [author, date]))
    if meta_str:
        parts.append(f'<text x="{cx}" y="{base_y + t_size("caption"):g}" '
                     f'font-size="{t_size("caption"):g}" '
                     f'data-style-role="caption" '
                     f'fill="{S["muted"]}" text-anchor="middle">{esc(meta_str)}</text>')
    if footer:
        # Same lift as `frame()`: the baseline sits a measured descent
        # above the safe-area boundary, not on it.
        fs = t_size("footnote")
        _, descent = vertical_metrics(
            S["font_resolved"], fs, t_weight("footnote"))
        parts.append(f'<text x="{S["w"] - S["safe"]["right"]}" '
                     f'y="{S["h"] - S["safe"]["bottom"] - descent:g}" '
                     f'font-size="{fs:g}" fill="{S["muted"]}" '
                     f'data-style-role="footnote" '
                     f'text-anchor="end">{esc(footer)}</text>')

    return svg("\n  ".join(parts))


def render_bullet_list(sl: dict, meta: dict) -> str:
    title    = sl.get("title", "")
    bullets  = sl.get("bullets", [])
    numbered = sl.get("numbered", False)
    footer   = meta.get("footer", "")

    parts = [frame(title, footer)]
    safe = S["safe"]
    x_dot = safe["left"] + 14
    x_text = safe["left"] + 52
    text_budget = S["w"] - x_text - safe["right"]
    body_adv = t_size("body") * t_lh("body")
    y = t_size("slide_title") + safe["top"] + 56
    for i, item in enumerate(bullets):
        lines = wrap_to_width(str(item), text_budget, "body")
        if numbered:
            r = t_size("footnote") * 0.75
            parts.append(f'<circle cx="{x_dot}" cy="{y - t_size("body") * 0.32:g}" '
                         f'r="{r:g}" fill="{S["accent"]}"/>')
            parts.append(f'<text x="{x_dot}" '
                         f'y="{y - t_size("body") * 0.32 + r * 0.55:g}" '
                         f'font-size="{t_size("footnote"):g}" font-weight="700" '
                         f'data-style-role="footnote" '
                         f'fill="{S["white"]}" text-anchor="middle">{i + 1}</text>')
        else:
            parts.append(f'<circle cx="{x_dot}" cy="{y - t_size("body") * 0.30:g}" '
                         f'r="{t_size("body") * 0.28:g}" fill="{S["accent"]}"/>')
        parts.append(tlines(lines, x_text, y, t_size("body"), S["body"],
                            "start", str(t_weight("body")), t_lh("body"),
                            role="body"))
        y += len(lines) * body_adv + S["spacing"][2]

    return svg("\n  ".join(parts))


def render_bar_chart(sl: dict, meta: dict) -> str:
    title      = sl.get("title", "")
    categories = sl.get("categories", [])
    series     = sl.get("series", [])
    y_max      = float(sl.get("y_max", 100))
    note       = sl.get("note", "")
    footer     = meta.get("footer", "")
    slide_index = sl.get("index", 0)

    parts = [frame(title, footer)]
    chart_parts = []

    for i in range(6):
        val = y_max * i / 5
        y   = CB - (val / y_max) * CH
        chart_parts.append(f'<line x1="{CL}" y1="{y:.1f}" x2="{CR}" y2="{y:.1f}" '
                     f'stroke="{S["border"]}" stroke-width="1"/>')
        chart_parts.append(f'<text x="{CL - 8}" y="{y + 4:.1f}" font-size="10" '
                     f'fill="{S["muted"]}" text-anchor="end">{val:.0f}%</text>')

    chart_parts.append(f'<line x1="{CL}" y1="{CT}" x2="{CL}" y2="{CB}" '
                 f'stroke="{S["muted"]}" stroke-width="1.5"/>')
    chart_parts.append(f'<line x1="{CL}" y1="{CB}" x2="{CR}" y2="{CB}" '
                 f'stroke="{S["muted"]}" stroke-width="1.5"/>')

    n_cats = len(categories)
    n_ser  = len(series)
    if not n_cats or not n_ser:
        parts.append(_wrap_pptx_role("chart", slide_index, chart_parts,
                                     bbox=(60, 70, 1080, 500),
                                     style_keys=("font",)))
        return svg("\n  ".join(parts))

    cat_slot = CW / n_cats
    group_w  = cat_slot * 0.70
    bar_w    = group_w / n_ser
    pad      = cat_slot * 0.15

    for ci, cat in enumerate(categories):
        gx = CL + ci * cat_slot + pad
        lx = gx + group_w / 2
        chart_parts.append(f'<text x="{lx:.1f}" y="{CB + 20}" font-size="12" font-weight="600" '
                     f'fill="{S["body"]}" text-anchor="middle">{esc(cat)}</text>')

        for si, ser in enumerate(series):
            vals  = ser.get("values", [])
            if ci >= len(vals):
                continue
            val   = float(vals[ci])
            color = ser.get("color", S["blue"])
            bx    = gx + si * bar_w
            bh    = max((val / y_max) * CH, 2)
            by    = CB - bh

            chart_parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" '
                         f'width="{bar_w - 3:.1f}" height="{bh:.1f}" fill="{color}"/>')
            if bh > 16:
                chart_parts.append(f'<text x="{bx + (bar_w - 3) / 2:.1f}" y="{by - 4:.1f}" '
                             f'font-size="11" font-weight="700" fill="{color}" '
                             f'text-anchor="middle">{val:.1f}%</text>')

    lx = CL
    for si, ser in enumerate(series):
        color = ser.get("color", S["blue"])
        chart_parts.append(f'<rect x="{lx + si * 230}" y="{CB + 40}" '
                     f'width="16" height="12" fill="{color}"/>')
        chart_parts.append(f'<text x="{lx + si * 230 + 22}" y="{CB + 51}" '
                     f'font-size="12" fill="{S["body"]}">{esc(ser.get("label", ""))}</text>')

    if note:
        chart_parts.append(f'<text x="{CR}" y="{CB + 51}" font-size="10" '
                     f'fill="{S["muted"]}" text-anchor="end">{esc(note)}</text>')

    parts.append(_wrap_pptx_role("chart", slide_index, chart_parts,
                                 bbox=(60, 70, 1080, 500),
                                 style_keys=("font",)))
    return svg("\n  ".join(parts))


def render_line_chart(sl: dict, meta: dict) -> str:
    """SVG preview for a line chart. Same slide_data.json schema as
    bar_chart (categories/series/y_max/note); svg_to_pptx/converter.py
    replaces this hand-drawn preview with a real native line chart."""
    title      = sl.get("title", "")
    categories = sl.get("categories", [])
    series     = sl.get("series", [])
    y_max      = float(sl.get("y_max", 100))
    note       = sl.get("note", "")
    footer     = meta.get("footer", "")
    slide_index = sl.get("index", 0)

    parts = [frame(title, footer)]
    chart_parts = []

    for i in range(6):
        val = y_max * i / 5
        y   = CB - (val / y_max) * CH
        chart_parts.append(f'<line x1="{CL}" y1="{y:.1f}" x2="{CR}" y2="{y:.1f}" '
                     f'stroke="{S["border"]}" stroke-width="1"/>')
        chart_parts.append(f'<text x="{CL - 8}" y="{y + 4:.1f}" font-size="10" '
                     f'fill="{S["muted"]}" text-anchor="end">{val:.0f}%</text>')
    chart_parts.append(f'<line x1="{CL}" y1="{CT}" x2="{CL}" y2="{CB}" '
                 f'stroke="{S["muted"]}" stroke-width="1.5"/>')
    chart_parts.append(f'<line x1="{CL}" y1="{CB}" x2="{CR}" y2="{CB}" '
                 f'stroke="{S["muted"]}" stroke-width="1.5"/>')

    n_cats = len(categories)
    if n_cats:
        step = CW / max(n_cats - 1, 1)
        for ci, cat in enumerate(categories):
            x = CL + ci * step
            chart_parts.append(f'<text x="{x:.1f}" y="{CB + 20}" font-size="12" '
                         f'fill="{S["body"]}" text-anchor="middle">{esc(cat)}</text>')
        for ser in series:
            vals = ser.get("values", [])
            color = ser.get("color", S["blue"])
            points = []
            for ci, val in enumerate(vals[:n_cats]):
                x = CL + ci * step
                y = CB - (float(val) / y_max) * CH
                points.append(f"{x:.1f},{y:.1f}")
                chart_parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
            if len(points) > 1:
                chart_parts.append(f'<polyline points="{" ".join(points)}" '
                             f'fill="none" stroke="{color}" stroke-width="2.5"/>')

    if note:
        chart_parts.append(f'<text x="{CR}" y="{CB + 51}" font-size="10" '
                     f'fill="{S["muted"]}" text-anchor="end">{esc(note)}</text>')

    parts.append(_wrap_pptx_role("chart", slide_index, chart_parts,
                                 bbox=(60, 70, 1080, 500),
                                 style_keys=("font",)))
    return svg("\n  ".join(parts))


def render_pie_chart(sl: dict, meta: dict) -> str:
    """SVG preview for a pie chart. Schema: categories/values/colors(optional)/
    note. svg_to_pptx/converter.py replaces this preview with a real native
    pie chart."""
    import math
    title      = sl.get("title", "")
    categories = sl.get("categories", [])
    values     = sl.get("values", [])
    colors     = sl.get("colors") or [S["blue"], S["good"], S["warn"], S["danger"], S["accent"]]
    note       = sl.get("note", "")
    footer     = meta.get("footer", "")
    slide_index = sl.get("index", 0)

    parts = [frame(title, footer)]
    if not categories or not values:
        return svg("\n  ".join(parts))

    cx, cy, r = 420, 340, 200
    total = sum(values) or 1
    chart_parts = []
    angle = -math.pi / 2
    for i, val in enumerate(values):
        frac = val / total
        end_angle = angle + frac * 2 * math.pi
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(end_angle), cy + r * math.sin(end_angle)
        large_arc = 1 if (end_angle - angle) > math.pi else 0
        color = colors[i % len(colors)]
        chart_parts.append(
            f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} '
            f'A{r},{r} 0 {large_arc} 1 {x2:.1f},{y2:.1f} Z" fill="{color}"/>'
        )
        angle = end_angle

    for i, cat in enumerate(categories):
        ly = 160 + i * 32
        color = colors[i % len(colors)]
        chart_parts.append(f'<rect x="700" y="{ly}" width="16" height="16" fill="{color}"/>')
        chart_parts.append(f'<text x="724" y="{ly + 13}" font-size="13" '
                     f'fill="{S["body"]}">{esc(cat)}</text>')

    if note:
        chart_parts.append(f'<text x="1100" y="600" font-size="10" fill="{S["muted"]}" '
                     f'text-anchor="end">{esc(note)}</text>')

    parts.append(_wrap_pptx_role("chart", slide_index, chart_parts,
                                 bbox=(140, 90, 900, 480),
                                 style_keys=("font",)))
    return svg("\n  ".join(parts))


def _wrap_pptx_role(role: str, slide_index: int, inner_parts: list,
                    bbox: tuple, style_keys: tuple, node_id: str = "") -> str:
    """Wrap hand-drawn preview markup in the data-pptx-role marker so
    svg_to_pptx/converter.py materializes a real native PPTX object instead
    of flattening these shapes. bbox is (x, y, w, h) in SVG user units."""
    style_json = esc(json.dumps({k: S[k] for k in style_keys if k in S}))
    bx, by, bw, bh = bbox
    attrs = [
        f'data-pptx-role="{role}"',
        f'data-pptx-source="slide_data.json#{slide_index}"',
        f'data-pptx-bbox="{bx:.1f},{by:.1f},{bw:.1f},{bh:.1f}"',
        f'data-pptx-style="{style_json}"',
    ]
    if node_id:
        attrs.append(f'data-node-id="{esc(node_id)}"')
    return (f'<g {" ".join(attrs)}>\n  ' + "\n  ".join(inner_parts) + '\n  </g>')


def render_table(sl: dict, meta: dict) -> str:
    title         = sl.get("title", "")
    columns       = sl.get("columns", [])
    rows          = sl.get("rows", [])
    highlight_col = sl.get("highlight_col")   # 0-indexed; colorizes +/- values
    footer        = meta.get("footer", "")
    slide_index   = sl.get("index", 0)

    parts = [frame(title, footer)]

    n_cols = len(columns)
    if not n_cols:
        return svg("\n  ".join(parts))

    tl, tr = 60, 1140
    tw      = tr - tl
    col_w   = tw / n_cols
    row_h   = min(50, 450 / (len(rows) + 1))
    top_y   = 75
    table_h = row_h * (len(rows) + 1)

    table_parts = [
        f'<rect x="{tl}" y="{top_y}" width="{tw}" '
        f'height="{row_h}" fill="{S["accent"]}"/>'
    ]
    for ci, col in enumerate(columns):
        cx = tl + ci * col_w + col_w / 2
        table_parts.append(f'<text x="{cx:.1f}" y="{top_y + row_h * 0.63:.1f}" '
                     f'font-size="13" font-weight="700" fill="{S["white"]}" '
                     f'text-anchor="middle">{esc(col)}</text>')

    for ri, row in enumerate(rows):
        ry = top_y + (ri + 1) * row_h
        bg = S["card"] if ri % 2 == 0 else S["bg"]
        table_parts.append(f'<rect x="{tl}" y="{ry:.1f}" width="{tw}" '
                     f'height="{row_h:.1f}" fill="{bg}" '
                     f'stroke="{S["border"]}" stroke-width="0.5"/>')
        for ci, cell in enumerate(row):
            cx    = tl + ci * col_w + col_w / 2
            cy    = ry + row_h * 0.63
            color = S["body"]
            if highlight_col is not None and ci == highlight_col:
                cs = str(cell)
                if "+" in cs:
                    color = S["good"]
                elif "-" in cs:
                    color = S["danger"]
            table_parts.append(f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="13" '
                         f'fill="{color}" text-anchor="middle">{esc(cell)}</text>')

    table_parts.append(f'<rect x="{tl}" y="{top_y}" width="{tw}" '
                 f'height="{table_h:.1f}" fill="none" '
                 f'stroke="{S["border"]}" stroke-width="1.5"/>')

    parts.append(_wrap_pptx_role(
        "table", slide_index, table_parts,
        bbox=(tl, top_y, tw, table_h),
        style_keys=("accent", "white", "card", "bg", "body", "good", "danger", "font"),
    ))

    return svg("\n  ".join(parts))


def render_metric_cards(sl: dict, meta: dict) -> str:
    title   = sl.get("title", "")
    metrics = sl.get("metrics", [])
    footer  = meta.get("footer", "")

    parts = [frame(title, footer)]
    n = len(metrics)
    if not n:
        return svg("\n  ".join(parts))

    cols = 2 if n == 4 else min(n, 3)
    rows = (n + cols - 1) // cols
    pad  = 40
    gap  = 20
    cw   = (S["w"] - 2 * pad - (cols - 1) * gap) / cols
    ch   = (S["h"] - 80 - 2 * pad - (rows - 1) * gap) / rows

    for i, m in enumerate(metrics):
        col   = i % cols
        row   = i // cols
        cx    = pad + col * (cw + gap)
        cy    = 80 + pad + row * (ch + gap)
        color = m.get("color", S["blue"])
        label = m.get("label", "")
        value = m.get("value", "")
        change = m.get("change", "")

        parts.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cw:.1f}" height="{ch:.1f}" '
                     f'rx="8" fill="{S["card"]}" stroke="{S["border"]}" stroke-width="1.5"/>')
        parts.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cw:.1f}" height="5" '
                     f'rx="4" fill="{color}"/>')
        parts.append(f'<text x="{cx + cw/2:.1f}" y="{cy + 36:.1f}" font-size="13" '
                     f'fill="{S["muted"]}" text-anchor="middle">{esc(label)}</text>')
        parts.append(f'<text x="{cx + cw/2:.1f}" y="{cy + ch/2 + 16:.1f}" font-size="38" '
                     f'font-weight="700" fill="{color}" text-anchor="middle">{esc(value)}</text>')
        if change:
            cc = S["good"] if "+" in str(change) else (S["danger"] if "-" in str(change) else S["muted"])
            parts.append(f'<text x="{cx + cw/2:.1f}" y="{cy + ch - 18:.1f}" '
                         f'font-size="12" fill="{cc}" text-anchor="middle">{esc(change)}</text>')

    return svg("\n  ".join(parts))


def render_two_column(sl: dict, meta: dict) -> str:
    title  = sl.get("title", "")
    left   = sl.get("left",  {})
    right  = sl.get("right", {})
    footer = meta.get("footer", "")

    parts = [frame(title, footer)]

    def panel(p: dict, px, py, pw, ph) -> list:
        out = []
        out.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" '
                   f'rx="6" fill="{S["card"]}" stroke="{S["border"]}" stroke-width="1.5"/>')
        pt = p.get("title", "")
        if pt:
            out.append(f'<text x="{px + 20}" y="{py + 30}" font-size="14" font-weight="700" '
                       f'fill="{S["accent"]}">{esc(pt)}</text>')
            out.append(f'<line x1="{px + 20}" y1="{py + 38}" x2="{px + pw - 20}" y2="{py + 38}" '
                       f'stroke="{S["border"]}" stroke-width="1"/>')

        content = p.get("content", [])
        ty = py + 60
        max_c = int(pw / 9)

        if isinstance(content, str):
            out.append(tlines(wrap(content, max_c), px + 20, ty, 13, S["body"],
                              role="body"))
        else:
            for item in content:
                lines = wrap(str(item), max_c - 4)
                out.append(f'<circle cx="{px + 28}" cy="{ty + 3}" r="4" fill="{S["accent"]}"/>')
                out.append(tlines(lines, px + 44, ty, 13, S["body"],
                                  role="body"))
                ty += 24 * len(lines) + 8
        return out

    parts += panel(left,  60,  66, 500, 562)
    parts += panel(right, 640, 66, 500, 562)

    return svg("\n  ".join(parts))


def render_timeline(sl: dict, meta: dict) -> str:
    title  = sl.get("title", "")
    events = sl.get("events", [])
    footer = meta.get("footer", "")

    parts = [frame(title, footer)]
    if not events:
        return svg("\n  ".join(parts))

    n  = len(events)
    y0 = 370
    x0, x1 = 100, 1100
    xs = [x0 + i * (x1 - x0) / max(n - 1, 1) for i in range(n)]

    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y0}" '
                 f'stroke="{S["border"]}" stroke-width="3"/>')

    for i, (ev, x) in enumerate(zip(events, xs)):
        color = ev.get("color", S["accent"])
        above = i % 2 == 0
        event_parts = []

        event_parts.append(f'<circle cx="{x:.1f}" cy="{y0}" r="10" '
                     f'fill="{color}" stroke="{S["bg"]}" stroke-width="2"/>')

        if above:
            event_parts.append(f'<line x1="{x:.1f}" y1="{y0 - 10}" x2="{x:.1f}" y2="{y0 - 28}" '
                         f'stroke="{color}" stroke-width="1.5" stroke-dasharray="3,2"/>')
            ty = y0 - 46
        else:
            event_parts.append(f'<line x1="{x:.1f}" y1="{y0 + 10}" x2="{x:.1f}" y2="{y0 + 28}" '
                         f'stroke="{color}" stroke-width="1.5" stroke-dasharray="3,2"/>')
            ty = y0 + 42

        label = ev.get("label", "")
        label_lines = wrap(label, 18)
        event_parts.append(tlines(label_lines, x, ty, 13, S["accent"], "middle",
                                  "700", role="node_label"))

        date_str = ev.get("date", "")
        if date_str:
            dy = y0 + 28 if above else y0 - 20
            event_parts.append(f'<text x="{x:.1f}" y="{dy}" font-size="10" '
                         f'fill="{S["muted"]}" text-anchor="middle">{esc(date_str)}</text>')

        detail = ev.get("detail", "")
        if detail:
            det_y = ty + len(label_lines) * 18 + 6
            event_parts.append(tlines(wrap(detail, 20), x, det_y, 11, S["muted"],
                                      "middle", role="caption"))

        parts.append(f'<g data-pptx-role="group" data-node-id="event-{i}">\n    '
                    + "\n    ".join(event_parts) + '\n  </g>')

    return svg("\n  ".join(parts))


def render_conclusion(sl: dict, meta: dict) -> str:
    title       = sl.get("title", "Conclusion & Next Steps")
    conclusions = sl.get("conclusions", [])
    next_steps  = sl.get("next_steps", [])
    footer      = meta.get("footer", "")
    c_head      = sl.get("conclusions_heading", "Conclusions")
    n_head      = sl.get("next_steps_heading",  "Next Steps")

    parts = [frame(title, footer)]

    def block(items, px, py, pw, ph, color, heading, numbered=True) -> list:
        out = []
        out.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" '
                   f'rx="6" fill="{S["card"]}" stroke="{S["border"]}" stroke-width="1.5"/>')
        out.append(f'<rect x="{px}" y="{py}" width="{pw}" height="5" rx="4" fill="{color}"/>')
        out.append(f'<text x="{px + 24}" y="{py + 24 + t_size("takeaway"):g}" '
                   f'font-size="{t_size("takeaway"):g}" '
                   f'font-weight="{t_weight("takeaway")}" '
                   f'data-style-role="takeaway" '
                   f'fill="{color}">{esc(heading)}</text>')
        rule_y = py + 24 + t_size("takeaway") + 14
        out.append(f'<line x1="{px + 24}" y1="{rule_y:g}" '
                   f'x2="{px + pw - 24}" y2="{rule_y:g}" '
                   f'stroke="{S["divider"]}" stroke-width="1"/>')

        iy = rule_y + 24 + t_size("body")
        body_adv = t_size("body") * t_lh("body")
        for idx, item in enumerate(items):
            lines = wrap_to_width(str(item), pw - 96, "body")
            if numbered:
                r = t_size("footnote") * 0.85
                out.append(f'<circle cx="{px + 32}" '
                           f'cy="{iy - t_size("body") * 0.32:g}" '
                           f'r="{r:g}" fill="{color}"/>')
                out.append(f'<text x="{px + 32}" '
                           f'y="{iy - t_size("body") * 0.32 + r * 0.55:g}" '
                           f'font-size="{t_size("footnote"):g}" font-weight="700" '
                           f'data-style-role="footnote" '
                           f'fill="{S["white"]}" text-anchor="middle">{idx + 1}</text>')
                out.append(tlines(lines, px + 32 + r + 16, iy, t_size("body"),
                                  S["body"], "start", str(t_weight("body")),
                                  t_lh("body"), role="body"))
            else:
                out.append(f'<circle cx="{px + 32}" '
                           f'cy="{iy - t_size("body") * 0.30:g}" '
                           f'r="{t_size("body") * 0.28:g}" fill="{color}"/>')
                out.append(tlines(lines, px + 32 + t_size("body") * 0.28 + 16, iy,
                                  t_size("body"), S["body"], "start",
                                  str(t_weight("body")), t_lh("body"),
                                  role="body"))
            iy += len(lines) * body_adv + S["spacing"][2]
        return out

    panel_top = S["safe"]["top"] + t_size("slide_title") + 40
    panel_h = S["h"] - panel_top - S["safe"]["bottom"] - 16
    panel_w = (S["w"] - 2 * S["safe"]["left"] - 40) / 2
    parts += block(conclusions, S["safe"]["left"], panel_top, panel_w, panel_h,
                   S["accent"], c_head, numbered=False)
    parts += block(next_steps, S["safe"]["left"] + panel_w + 40, panel_top,
                   panel_w, panel_h, S["good"], n_head, numbered=True)

    return svg("\n  ".join(parts))


# ── Dispatch ──────────────────────────────────────────────────────────────────

RENDERERS = {
    "title":         render_title,
    "bullet_list":   render_bullet_list,
    "bar_chart":     render_bar_chart,
    "line_chart":    render_line_chart,
    "pie_chart":     render_pie_chart,
    "table":         render_table,
    "metric_cards":  render_metric_cards,
    "two_column":    render_two_column,
    "timeline":      render_timeline,
    "conclusion":    render_conclusion,
}


def generate_slide(sl: dict, meta: dict) -> str:
    renderer = RENDERERS.get(sl["type"])
    if not renderer:
        raise ValueError(
            f"Unknown type: {sl['type']!r}. Available: {list(RENDERERS)}")
    return renderer(sl, meta)


# ── SVG → PNG conversion (fallback chain) ────────────────────────────────────

def svg_to_png(svg_path: str, png_path: str, width: int = 2400, height: int = 1350) -> bool:
    """Convert one SVG to PNG. Tries cairosvg → inkscape → rsvg-convert."""
    # 1. cairosvg (pip install cairosvg)
    try:
        import cairosvg
        cairosvg.svg2png(url=svg_path, write_to=png_path,
                         output_width=width, output_height=height)
        return True
    except ImportError:
        pass
    except Exception as e:
        print(f"    cairosvg error: {e}")

    import subprocess, shutil

    # 2. inkscape (system package)
    if shutil.which("inkscape"):
        r = subprocess.run(
            ["inkscape", svg_path,
             f"--export-filename={png_path}",
             f"--export-width={width}", f"--export-height={height}"],
            capture_output=True,
        )
        if r.returncode == 0:
            return True

    # 3. rsvg-convert (librsvg)
    if shutil.which("rsvg-convert"):
        r = subprocess.run(
            ["rsvg-convert", svg_path,
             "-w", str(width), "-h", str(height), "-o", png_path],
            capture_output=True,
        )
        if r.returncode == 0:
            return True

    return False


# ── SVG dir → PPTX ───────────────────────────────────────────────────────────

def to_pptx(svg_dir: str, output_path: str) -> None:
    """Convert all slide*.svg in svg_dir (sorted) into a single PPTX file."""
    try:
        from pptx import Presentation
        from pptx.util import Inches
    except ImportError:
        print("Missing dependency: python-pptx")
        print("Install with: pip install python-pptx")
        return

    import glob, tempfile

    svgs = sorted(glob.glob(os.path.join(svg_dir, "slide*.svg")))
    if not svgs:
        print(f"No slide*.svg found in {svg_dir}")
        return

    # Check at least one PNG converter is available before starting
    import shutil
    has_converter = (
        _try_import("cairosvg")
        or shutil.which("inkscape")
        or shutil.which("rsvg-convert")
    )
    if not has_converter:
        print("No SVG→PNG converter found. Install one of:")
        print("  pip install cairosvg")
        print("  sudo apt install inkscape   (or librsvg2-bin for rsvg-convert)")
        return

    prs = Presentation()
    prs.slide_width  = Inches(13.333)   # 16:9, matches 1200px wide
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]        # blank layout

    print(f"Converting {len(svgs)} slides → {output_path}")

    with tempfile.TemporaryDirectory() as tmp:
        for svg_path in svgs:
            name     = os.path.basename(svg_path).replace(".svg", ".png")
            png_path = os.path.join(tmp, name)

            ok = svg_to_png(svg_path, png_path)
            if not ok:
                print(f"  ✗ {os.path.basename(svg_path)} (conversion failed, skipped)")
                continue

            slide = prs.slides.add_slide(blank)
            slide.shapes.add_picture(
                png_path,
                left=0, top=0,
                width=prs.slide_width,
                height=prs.slide_height,
            )
            print(f"  ✓ {os.path.basename(svg_path)}")

    prs.save(output_path)
    size_kb = os.path.getsize(output_path) // 1024
    print(f"\n✅ PPTX saved: {output_path}  ({size_kb} KB, {len(prs.slides)} slides)")
    print("\nNote: each slide in the PPTX is an embedded image; elements cannot be edited individually in PowerPoint.")
    print("To edit a single slide, modify the corresponding SVG and re-run with --to-pptx.")


def _try_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────

def _authorize_production(deck_id: str, project_root: Path | None) -> Path | None:
    """Authorize the CLI before it reads inputs or creates output paths."""
    try:
        root = (
            Path(project_root).resolve()
            if project_root is not None
            else find_project_root(Path.cwd())
        )
        assert_production_allowed(root, deck_id)
    except ProductionGateError as exc:
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "predicate": exc.predicate,
                    "deck_id": exc.deck_id,
                    "blockers": exc.blockers,
                }
            )
        )
        return None
    except Exception as exc:  # noqa: BLE001 - CLI failures stay machine-readable
        print(
            json.dumps(
                {
                    "error": "ProductionGateError",
                    "predicate": "production_allowed",
                    "deck_id": deck_id,
                    "blockers": [{"reason": "project_root_invalid", "message": str(exc)}],
                }
            )
        )
        return None
    return root


def main(arguments: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate SVG research slides from JSON")
    ap.add_argument("--data",     help="Path to slide_data.json")
    ap.add_argument("--out",      help="Output directory for SVG files")
    ap.add_argument("--deck-id", required=True, help="Approved presentation Deck identifier")
    ap.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root (defaults to the nearest ancestor of the current directory)",
    )
    ap.add_argument("--slide",    type=int, default=None, help="Render only slide N")
    ap.add_argument("--style",    metavar="FILE",      default=None,
                    help="Style .md file to override colors/fonts (see references/styles/STYLES.md in skill bundle)")
    ap.add_argument("--tokens", metavar="FILE", type=Path, default=None,
                    help="Design-token .tokens.yaml file "
                         "(default: references/tokens/default.tokens.yaml)")
    ap.add_argument("--to-pptx",  metavar="SVG_DIR",
                    help="Convert all slide*.svg in SVG_DIR to PPTX (skips SVG generation)")
    ap.add_argument("--pptx-out", metavar="FILE", default=None,
                    help="Output PPTX path (default: SVG_DIR/deck.pptx)")
    args = ap.parse_args(arguments)

    project_root = _authorize_production(args.deck_id, args.project_root)
    if project_root is None:
        return 1

    # ── Mode: convert existing SVGs to PPTX ──
    if args.to_pptx:
        out = args.pptx_out or os.path.join(args.to_pptx, "deck.pptx")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        to_pptx(args.to_pptx, out)
        return 0

    # ── Mode: generate SVGs from JSON ──
    if not args.data or not args.out:
        ap.error("--data and --out are required when not using --to-pptx")

    # `apply_tokens` runs first: it establishes sizes, spacing, and the
    # resolved font, and `apply_style` then overrides colours only.
    apply_tokens(args.tokens)
    if args.style:
        apply_style(args.style)

    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)

    meta   = data.get("meta", {})
    slides = data.get("slides", [])
    os.makedirs(args.out, exist_ok=True)

    generated = 0
    for sl in slides:
        if args.slide is not None and sl.get("index") != args.slide:
            continue
        content  = generate_slide(sl, meta)
        idx      = sl.get("index", 0)
        filename = f"slide{idx:02d}_{sl['type']}.svg"
        path     = os.path.join(args.out, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  ✓ {filename}")
        generated += 1

    print(f"\n{generated} slide(s) written to {args.out}")

    import shutil
    shutil.copy2(args.data, os.path.join(args.out, "slide_data.json"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
