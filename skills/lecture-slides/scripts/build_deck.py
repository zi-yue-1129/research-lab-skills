#!/usr/bin/env python3
"""Build an editable lecture deck (.pptx) from a YAML deck spec.

Every element is a native PowerPoint shape or text box, so the teacher can
edit any number, label, or colour afterwards. The core is course-agnostic:
layouts, chrome (title, section chips, footnote source, ``n / N``), speaker
notes, and a neutral default theme. A named *preset* under ``presets/``
supplies one course's look: its themes, fonts, strings, and title motifs.

Usage:
    python3 build_deck.py deck.yaml -o out.pptx [--preset NAME] [--theme NAME]

The spec format is documented in ``references/deck-spec.md``; presets in
``presets/README.md``.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

import yaml
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

SKILL_DIR = Path(__file__).resolve().parent.parent
THEME_DIR = SKILL_DIR / "references" / "themes"
PRESET_DIR = SKILL_DIR / "presets"

# Course-agnostic defaults; a preset overrides them, and a theme overrides both.
CORE_FONTS = {"latin": "Calibri", "east_asian": None, "mono": "Courier New"}
CORE_STRINGS = {"image_placeholder": "[Image] ", "meta_separator": " · "}

SLIDE_W, SLIDE_H = 13.333, 7.5
LEFT, RIGHT = 0.8, 12.53
CONTENT_W = RIGHT - LEFT
BODY_TOP, BODY_BOTTOM = 1.3, 5.95
TAKEAWAY_Y = 6.1
FOOTER_Y = 6.98

TONES = ("positive", "alert", "info", "highlight", "neutral")
LAYOUTS = (
    "title", "agenda", "cards", "numbers", "facts", "formula", "table",
    "bars", "flow", "image", "code", "compare", "sources",
)

# `{tone:text}` colours a span with a tone accent; `**text**` is shorthand for
# `{alert:text}`, the deck's single emphasis colour.
_MARKUP = re.compile(r"\{(\w+):([^{}]+)\}|\*\*(.+?)\*\*")


class SpecError(ValueError):
    """The deck spec is malformed."""


def available_presets() -> list[str]:
    return sorted(d.name for d in PRESET_DIR.iterdir() if (d / "preset.yaml").is_file())


def load_preset(name_or_path: str | None) -> dict:
    """Load a preset by name (``presets/<name>``) or by path to its folder.

    Returns an empty preset when ``name_or_path`` is None. The result carries
    ``_dir`` (the preset folder) and ``_motifs`` (name -> draw function).
    """
    if not name_or_path:
        return {"_dir": None, "_motifs": {}}
    folder = Path(name_or_path)
    if not (folder / "preset.yaml").is_file():
        folder = PRESET_DIR / str(name_or_path)
    manifest = folder / "preset.yaml"
    if not manifest.is_file():
        raise SpecError(f"preset not found: {name_or_path}; available: "
                        f"{', '.join(available_presets()) or 'none'}")
    preset = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    preset["_dir"] = folder
    preset["_motifs"] = {}
    if preset.get("motifs"):
        module_path = folder / preset["motifs"]
        spec = importlib.util.spec_from_file_location(
            f"lecture_preset_{folder.name.replace('-', '_')}_motifs", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        preset["_motifs"] = dict(module.MOTIFS)
    return preset


def load_theme(name_or_path: str, preset: dict | None = None) -> dict:
    """Load a theme by name (the preset's themes first, then the core's) or path."""
    path = Path(name_or_path)
    if not path.suffix:
        folders = [preset["_dir"] / "themes"] if preset and preset.get("_dir") else []
        folders.append(THEME_DIR)
        path = next((f / f"{name_or_path}.yaml" for f in folders
                     if (f / f"{name_or_path}.yaml").is_file()), path)
    if not path.is_file():
        raise SpecError(f"theme not found: {name_or_path}")
    theme = yaml.safe_load(path.read_text(encoding="utf-8"))
    for tone in TONES:
        if tone not in theme.get("tones", {}):
            raise SpecError(f"theme {path.name} is missing tone '{tone}'")
    return theme


def rgb(hex_str: str) -> RGBColor:
    return RGBColor.from_string(hex_str.lstrip("#").upper())


def visual_width(text: str) -> float:
    """Approximate text width in em: CJK/full-width counts 1, others 0.5."""
    return sum(1.0 if ord(ch) > 0x2E7F else 0.5 for ch in text)


class Builder:
    """Draws slides onto a Presentation using one theme."""

    def __init__(self, theme: dict, spec: dict, base_dir: Path, preset: dict | None = None):
        preset = preset or {"_motifs": {}}
        self.t = theme
        self.fonts = {**CORE_FONTS, **(preset.get("fonts") or {}), **(theme.get("fonts") or {})}
        self.strings = {**CORE_STRINGS, **(preset.get("strings") or {})}
        self.motifs = preset["_motifs"]
        self.preset_name = preset.get("name")
        self.spec = spec
        self.deck = spec.get("deck", {})
        self.base_dir = base_dir
        self.prs = Presentation()
        self.prs.slide_width = Inches(SLIDE_W)
        self.prs.slide_height = Inches(SLIDE_H)
        self.blank = self.prs.slide_layouts[6]
        self.warnings: list[str] = []
        self.slide_no = 0
        self.total = len(spec.get("slides", []))

    # ── colour helpers ────────────────────────────────────────────────────
    def color(self, role: str) -> str:
        if role in self.t["colors"]:
            return self.t["colors"][role]
        if role in self.t["tones"]:
            return self.t["tones"][role]["accent"]
        raise SpecError(f"unknown colour role '{role}'")

    def accent(self, tone: str | None) -> str:
        return self.t["tones"].get(tone or "neutral", self.t["tones"]["neutral"])["accent"]

    def tint(self, tone: str | None) -> str:
        if not tone or tone == "neutral":
            return self.t["colors"]["card"]
        return self.t["tones"][tone]["tint"]

    # ── primitives ────────────────────────────────────────────────────────
    def _style_run(self, run, size, color, bold=False, mono=False):
        f = run.font
        f.size = Pt(size)
        f.bold = bold
        f.color.rgb = rgb(color)
        fonts = self.fonts
        latin = fonts["mono"] if mono else fonts["latin"]
        f.name = latin
        rpr = run._r.get_or_add_rPr()
        # With no east-Asian face set, PowerPoint uses the theme's own.
        faces = {"a:ea": fonts.get("east_asian"), "a:cs": latin}
        for tag, face in faces.items():
            if not face:
                continue
            el = rpr.find(qn(tag))
            if el is None:
                el = rpr.makeelement(qn(tag), {})
                rpr.append(el)
            el.set("typeface", face)

    def _fill_paragraph(self, para, text, size, color, bold=False, mono=False):
        pos = 0
        for m in _MARKUP.finditer(text):
            if m.start() > pos:
                self._style_run(para.add_run(), size, color, bold, mono)
                para.runs[-1].text = text[pos:m.start()]
            if m.group(3) is not None:
                tone, span = "alert", m.group(3)
            else:
                tone, span = m.group(1), m.group(2)
                if tone not in self.t["tones"]:
                    raise SpecError(f"unknown tone '{tone}' in markup: {text!r}")
            run = para.add_run()
            run.text = span
            self._style_run(run, size, self.accent(tone), bold, mono)
            pos = m.end()
        if pos < len(text) or not text:
            run = para.add_run()
            run.text = text[pos:]
            self._style_run(run, size, color, bold, mono)

    def text(self, slide, x, y, w, h, content, size=None, color="text",
             bold=False, align="l", anchor="t", mono=False, spacing=None):
        """Add a text box. ``content`` is a string (``\\n`` splits lines) or list."""
        size = size or self.t["sizes"]["body"]
        lines = content if isinstance(content, list) else str(content).split("\n")
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame
        tf.word_wrap = True
        for side in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
            setattr(tf, side, 0)
        tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE,
                              "b": MSO_ANCHOR.BOTTOM}[anchor]
        hexcolor = self.color(color) if not re.fullmatch(r"[0-9A-Fa-f]{6}", color) else color
        for i, line in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER,
                              "r": PP_ALIGN.RIGHT}[align]
            if spacing:
                para.space_after = Pt(spacing)
            self._fill_paragraph(para, str(line), size, hexcolor, bold, mono)
        widest = max((visual_width(_MARKUP.sub(lambda m: m.group(2) or m.group(3), str(l)))
                      for l in lines), default=0)
        per_line = max(1, int(widest * size / 72 / max(w, 0.1)) + 1)
        needed = sum(per_line for _ in lines) * size * 1.3 / 72
        if needed > h + 0.35 and w > 0.5:
            self.warnings.append(
                f"slide {self.slide_no}: text may overflow its box: {str(lines[0])[:30]!r}")
        return box

    def box(self, slide, x, y, w, h, fill=None, border=None, rounded=True,
            shadow=True, radius=0.12, border_w=1.25):
        shape = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
            Inches(x), Inches(y), Inches(w), Inches(h))
        if rounded:
            shape.adjustments[0] = min(0.5, radius / max(min(w, h), 0.01))
        if fill:
            shape.fill.solid()
            shape.fill.fore_color.rgb = rgb(fill)
        else:
            shape.fill.background()
        if border:
            shape.line.color.rgb = rgb(border)
            shape.line.width = Pt(border_w)
        else:
            shape.line.fill.background()
        if not shadow:
            # Drop the theme effect reference that python-pptx's default
            # shape style carries; that reference is what renders the shadow.
            sppr = shape._element.spPr
            sppr.append(sppr.makeelement(qn("a:effectLst"), {}))
        return shape

    def dot(self, slide, x, y, d, fill, border=None):
        shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y),
                                       Inches(d), Inches(d))
        shape.fill.solid()
        shape.fill.fore_color.rgb = rgb(fill)
        if border:
            shape.line.color.rgb = rgb(border)
            shape.line.width = Pt(1)
        else:
            shape.line.fill.background()
        sppr = shape._element.spPr
        sppr.append(sppr.makeelement(qn("a:effectLst"), {}))
        return shape

    def line(self, slide, x1, y1, x2, y2, color=None, width=1.0):
        """Plain straight line; ``color`` is a hex string or a colour role."""
        hexcolor = color if color and re.fullmatch(r"[0-9A-Fa-f]{6}", color) \
            else self.color(color or "line")
        conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1),
                                          Inches(x2), Inches(y2))
        conn.line.color.rgb = rgb(hexcolor)
        conn.line.width = Pt(width)
        return conn

    def arrow(self, slide, x1, y1, x2, y2, color="muted", width=1.75):
        line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1),
                                          Inches(y1), Inches(x2), Inches(y2))
        line.line.color.rgb = rgb(self.color(color))
        line.line.width = Pt(width)
        ln = line.line._get_or_add_ln()
        ln.append(ln.makeelement(qn("a:tailEnd"), {"type": "triangle"}))
        return line

    def image(self, slide, path, x, y, w, h, label=""):
        """Place an image fitted inside (x, y, w, h); draw a placeholder if missing."""
        p = (self.base_dir / path) if path else None
        if p and p.is_file():
            pic = slide.shapes.add_picture(str(p), Inches(x), Inches(y))
            ratio = min(Inches(w) / pic.width, Inches(h) / pic.height)
            pic.width, pic.height = int(pic.width * ratio), int(pic.height * ratio)
            pic.left = int(Inches(x) + (Inches(w) - pic.width) / 2)
            pic.top = int(Inches(y) + (Inches(h) - pic.height) / 2)
            return pic
        self.warnings.append(f"slide {self.slide_no}: image placeholder for {path or label!r}")
        ph = self.box(slide, x, y, w, h, fill=self.t["colors"]["panel"],
                      border=self.t["colors"]["line"], rounded=False, shadow=False)
        ph.line.dash_style = 4  # dash
        self.text(slide, x + 0.2, y, w - 0.4, h, f"{self.strings['image_placeholder']}{label or path or ''}",
                  size=self.t["sizes"]["small"], color="faint", align="c", anchor="m")
        return ph

    # ── slide chrome ──────────────────────────────────────────────────────
    def new_slide(self, s: dict):
        self.slide_no += 1
        slide = self.prs.slides.add_slide(self.blank)
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb(self.t["colors"]["bg"])
        if s.get("notes"):
            slide.notes_slide.notes_text_frame.text = str(s["notes"]).strip()
        else:
            self.warnings.append(f"slide {self.slide_no}: no speaker notes")
        return slide

    def chrome(self, slide, s: dict):
        title = s.get("title", "")
        if self.t.get("title_style") == "bar":
            self.box(slide, LEFT - 0.12, 0.42, 0.08, 0.52,
                     fill=self.t["colors"]["bar"], rounded=False, shadow=False)
            self.text(slide, LEFT + 0.12, 0.38, 9.0, 0.6, title,
                      size=self.t["sizes"]["title"], anchor="m")
        else:
            self.text(slide, LEFT, 0.38, 8.6 if self.deck.get("sections") else CONTENT_W,
                      0.6, title, size=self.t["sizes"]["title"], anchor="m")
        if visual_width(title) > 22:
            self.warnings.append(f"slide {self.slide_no}: title is long ({title[:20]}…)")
        self.nav(slide, s.get("section"))
        if s.get("takeaway"):
            self.text(slide, LEFT + 0.2, TAKEAWAY_Y, CONTENT_W - 0.4, 0.55,
                      s["takeaway"], size=self.t["sizes"]["body"], color="muted",
                      align="c", anchor="m")
        if s.get("source"):
            self.text(slide, LEFT, FOOTER_Y, 10.4, 0.35, s["source"],
                      size=self.t["sizes"]["footer"], color="muted")
        self.text(slide, RIGHT - 1.1, FOOTER_Y + 0.05, 1.1, 0.25,
                  f"{self.slide_no} / {self.total}", size=self.t["sizes"]["footer"],
                  color="muted", align="r")

    def nav(self, slide, current):
        sections = self.deck.get("sections") or []
        if not sections or current is None:
            return
        if current not in sections:
            raise SpecError(f"slide {self.slide_no}: section {current!r} not in deck.sections")
        widths = [max(0.62, visual_width(n) * 0.17 + 0.25) for n in sections]
        x = RIGHT - sum(widths) - 0.06 * (len(sections) - 1)
        for name, w in zip(sections, widths):
            active = name == current
            self.box(slide, x, 0.45, w, 0.29,
                     fill=self.tint("alert") if active else self.t["colors"]["panel"],
                     radius=0.09)
            self.text(slide, x, 0.45, w, 0.29, name, size=11,
                      color="alert" if active else "muted", align="c", anchor="m")
            x += w + 0.06

    # ── layouts ───────────────────────────────────────────────────────────
    def layout_title(self, slide, s):
        sz = self.t["sizes"]
        d = self.deck
        meta = self.strings["meta_separator"].join(v for v in (d.get("course"), d.get("week")) if v)
        if s.get("image"):
            self.image(slide, s["image"], 0, 0, 5.6, SLIDE_H, s.get("image_label", ""))
            x, w, align = 6.3, 6.2, "l"
        else:
            x, w, align = LEFT, CONTENT_W, "c"
            if s.get("motif"):
                draw = self.motifs.get(s["motif"])
                if draw is None:
                    raise SpecError(
                        f"slide {self.slide_no}: motif {s['motif']!r} is not provided by "
                        f"preset {self.preset_name or '(none)'}; motifs come from presets")
                draw(self, slide, SLIDE_W / 2, 0.9)
        top = 2.55 if s.get("image") or not s.get("motif") else 3.0
        self.text(slide, x, top - 0.5, w, 0.35, meta, size=sz["small"], color="muted", align=align)
        self.text(slide, x, top, w, 1.0, s.get("title", d.get("title", "")), size=36,
                  align=align, anchor="m")
        if s.get("subtitle"):
            self.text(slide, x, top + 1.05, w, 0.5, s["subtitle"], size=sz["body"],
                      color="alert", align=align)
        if d.get("author"):
            self.text(slide, x, top + 1.9, w, 0.4, d["author"], size=sz["small"],
                      color="muted", align=align)

    def layout_agenda(self, slide, s):
        items = s.get("items") or []
        cur = s.get("current")
        h = min(0.62, (BODY_BOTTOM - BODY_TOP) / max(len(items), 1) - 0.12)
        x, w = 3.0, 7.3
        for i, it in enumerate(items):
            y = BODY_TOP + i * (h + 0.14)
            active = cur is not None and i + 1 == cur
            tone = it.get("tone") or ("alert" if active else None)
            self.box(slide, x, y, w, h, fill=self.tint(tone) if tone else self.t["colors"]["card"],
                     border=self.t["colors"]["line"], radius=0.08)
            self.text(slide, x + 0.3, y, 0.5, h, str(i + 1), size=self.t["sizes"]["body"],
                      color=tone or "info", anchor="m")
            self.text(slide, x + 0.8, y, 2.8, h, it.get("label", ""),
                      size=self.t["sizes"]["body"], anchor="m")
            if it.get("note"):
                self.text(slide, x + 3.6, y, w - 3.8, h, it["note"],
                          size=self.t["sizes"]["caption"] + 1, color="muted", anchor="m")

    def card(self, slide, x, y, w, h, c):
        """One card: heading, optional dot row, lines, and an optional value."""
        tone = c.get("tone")
        sz = self.t["sizes"]
        self.box(slide, x, y, w, h, fill=self.tint(c.get("fill_tone", None)) if c.get("fill_tone")
                 else self.t["colors"]["card"],
                 border=self.accent(tone) if tone else self.t["colors"]["line"],
                 border_w=1.5 if tone else 1.0)
        cy = y + 0.15
        if c.get("heading"):
            self.text(slide, x + 0.2, cy, w - 0.4, 0.42, c["heading"], size=sz["body"] + 1,
                      color=tone or "text", align=c.get("align", "c" if c.get("dots") else "l"))
            cy += 0.5
        if c.get("dots"):
            filled, total = int(c["dots"][0]), int(c["dots"][1])
            per_row = min(total, 5 if total <= 10 else 10)
            d = min(0.3, (w - 0.8) / per_row * 0.62)
            gap = d * 1.65
            start = x + (w - gap * (per_row - 1) - d) / 2
            for k in range(total):
                r, col = divmod(k, per_row)
                self.dot(slide, start + col * gap, cy + r * gap, d,
                         self.accent("positive") if k < filled else self.t["colors"]["card"],
                         border=None if k < filled else self.t["colors"]["line"])
            cy += ((total - 1) // per_row + 1) * gap + 0.05
        lines = c.get("lines") or []
        if lines:
            room = y + h - cy - (0.65 if c.get("value") else 0.1)
            self.text(slide, x + 0.2, cy, w - 0.4, max(room, 0.3), lines, size=sz["small"] + 1,
                      color="muted" if c.get("value") else "text",
                      align=c.get("align", "l"), spacing=4)
        if c.get("value") is not None:
            label = f"　{c['value_label']}" if c.get("value_label") else ""
            self.text(slide, x + 0.2, y + h - 0.6, w - 0.4, 0.5, f"{c['value']}{label}",
                      size=sz["stat"] - 6, color=tone or "text",
                      align=c.get("align", "c" if c.get("dots") else "l"), anchor="m")

    def card_height(self, c, w) -> float:
        """Natural height of a card: just tall enough for what it holds."""
        h = 0.3 + (0.5 if c.get("heading") else 0)
        if c.get("dots"):
            total = int(c["dots"][1])
            per_row = min(total, 5 if total <= 10 else 10)
            gap = min(0.3, (w - 0.8) / per_row * 0.62) * 1.65
            h += ((total - 1) // per_row + 1) * gap + 0.05
        lines = c.get("lines") or []
        size = self.t["sizes"]["small"] + 1
        for line in lines:
            per = max(1, int(visual_width(str(line)) * size / 72 / max(w - 0.4, 0.1)) + 1)
            h += per * size * 1.25 / 72 + 4 / 72
        if c.get("value") is not None:
            h += 0.65
        return max(h, 1.3)

    def layout_cards(self, slide, s):
        cards = s.get("cards") or []
        if not 1 <= len(cards) <= 4:
            raise SpecError(f"slide {self.slide_no}: cards layout needs 1–4 cards")
        gap = 0.35
        w = (CONTENT_W - gap * (len(cards) - 1)) / len(cards)
        bottom = (TAKEAWAY_Y - 0.15) if s.get("takeaway") else BODY_BOTTOM
        h = s.get("card_height") or min(bottom - BODY_TOP,
                                        max(self.card_height(c, w) for c in cards))
        for i, c in enumerate(cards):
            self.card(slide, LEFT + i * (w + gap), BODY_TOP, w, h, c)
        if s.get("band"):
            self.band(slide, BODY_TOP + h + 0.2, s["band"])

    def band(self, slide, y, b, h=None):
        """Full-width highlight band: an expression, its plain reading, an aside."""
        sz = self.t["sizes"]
        h = h or (1.0 if b.get("plain") else 0.6)
        self.box(slide, LEFT, y, CONTENT_W, h, fill=self.tint(b.get("tone", "highlight")))
        main_w = CONTENT_W - (3.2 if b.get("aside") else 0.5)
        self.text(slide, LEFT + 0.3, y + 0.1, main_w, 0.5, b.get("expr", ""),
                  size=sz["body"] + 3, align=b.get("align", "l"),
                  anchor="m" if not b.get("plain") else "t")
        if b.get("plain"):
            self.text(slide, LEFT + 0.3, y + 0.58, main_w, 0.35, b["plain"],
                      size=sz["small"] + 1, color="muted")
        if b.get("aside"):
            self.text(slide, RIGHT - 3.1, y + 0.1, 2.9, h - 0.2, b["aside"],
                      size=sz["small"] + 1, color="muted", align="c", anchor="m")

    def layout_formula(self, slide, s):
        y = BODY_TOP
        if s.get("cards"):
            n = len(s["cards"])
            w = (CONTENT_W - 0.35 * (n - 1)) / n
            for i, c in enumerate(s["cards"]):
                self.card(slide, LEFT + i * (w + 0.35), y, w, 1.85, c)
            y += 2.05
        self.band(slide, y, s.get("band") or {})
        y += 1.2 if (s.get("band") or {}).get("plain") else 0.8
        steps = s.get("steps") or []
        if steps:
            n = len(steps)
            arrow_w = 0.5
            w = (CONTENT_W - arrow_w * (n - 1)) / n
            for i, c in enumerate(steps):
                x = LEFT + i * (w + arrow_w)
                self.card(slide, x, y, w, 1.25, {**c, "align": "l"})
                if i < n - 1:
                    self.arrow(slide, x + w + 0.08, y + 0.62, x + w + arrow_w - 0.08, y + 0.62)
            y += 1.4
        if s.get("result"):
            self.band(slide, y, {"tone": "highlight", "align": "c", **s["result"]}, h=0.6)

    def layout_numbers(self, slide, s):
        stats = s.get("stats") or []
        has_visual = s.get("image") or s.get("panel")
        sx = 8.9 if has_visual else LEFT
        sw = RIGHT - sx if has_visual else CONTENT_W
        bottom = (TAKEAWAY_Y - 0.15) if s.get("takeaway") else BODY_BOTTOM
        if s.get("image"):
            self.image(slide, s["image"], LEFT, BODY_TOP, 7.6, bottom - BODY_TOP - 0.35,
                       s.get("image_label", ""))
            if s.get("caption"):
                self.text(slide, LEFT, bottom - 0.3, 7.6, 0.3, s["caption"],
                          size=self.t["sizes"]["caption"], color="muted", align="c")
        elif s.get("panel"):
            self.card(slide, LEFT, BODY_TOP, 7.6,
                      min(bottom - BODY_TOP, self.card_height(s["panel"], 7.6) + 0.3), s["panel"])
        if has_visual:
            h = (bottom - BODY_TOP) / max(len(stats), 1)
            for i, st in enumerate(stats):
                y = BODY_TOP + i * h
                self.text(slide, sx, y + 0.05, sw, 0.6, st["value"], size=self.t["sizes"]["stat"],
                          color=st.get("tone", "alert"), align="c", anchor="m")
                self.text(slide, sx, y + 0.65, sw, 0.5, st.get("label", ""),
                          size=self.t["sizes"]["caption"] + 1, color="muted", align="c")
        else:
            w = CONTENT_W / max(len(stats), 1)
            for i, st in enumerate(stats):
                x = LEFT + i * w
                self.text(slide, x, 2.6, w, 0.9, st["value"], size=self.t["sizes"]["stat"] + 10,
                          color=st.get("tone", "alert"), align="c", anchor="m")
                self.text(slide, x + 0.3, 3.6, w - 0.6, 0.8, st.get("label", ""),
                          size=self.t["sizes"]["small"] + 1, color="muted", align="c")

    def layout_facts(self, slide, s):
        sz = self.t["sizes"]
        self.image(slide, s.get("image"), LEFT, BODY_TOP, 5.8, 4.2, s.get("image_label", ""))
        if s.get("caption"):
            self.text(slide, LEFT, BODY_TOP + 4.3, 5.8, 0.3, s["caption"],
                      size=sz["caption"], color="muted", align="c")
        x, w = 7.2, RIGHT - 7.2
        facts = s.get("facts") or []
        h = 0.65 + 0.55 * len(facts)
        self.box(slide, x, BODY_TOP, w, h, fill=self.tint(s.get("tone", "highlight")))
        if s.get("heading"):
            self.text(slide, x + 0.3, BODY_TOP + 0.12, w - 0.6, 0.4, s["heading"],
                      size=sz["small"], color="muted")
        for i, (k, v) in enumerate((list(f.items())[0] for f in facts)):
            self.text(slide, x + 0.3, BODY_TOP + 0.6 + i * 0.55, w - 0.6, 0.5,
                      f"{k}　{v}", size=sz["body"] + 1, anchor="m")
        if s.get("question"):
            self.text(slide, x, BODY_TOP + h + 0.15, w, 0.8, s["question"],
                      size=sz["body"], color="alert", align="c")

    def layout_table(self, slide, s):
        headers = s.get("headers") or []
        rows = s.get("rows") or []
        hl = s.get("highlight_col")
        sz = self.t["sizes"]
        bottom = (TAKEAWAY_Y - 0.4) if s.get("takeaway") else BODY_BOTTOM
        row_h = min(0.45, (bottom - BODY_TOP) / (len(rows) + 1))
        w = s.get("width", min(CONTENT_W, 1.9 * len(headers)))
        x = LEFT + (CONTENT_W - w) / 2
        shape = slide.shapes.add_table(len(rows) + 1, len(headers), Inches(x), Inches(BODY_TOP),
                                       Inches(w), Inches(row_h * (len(rows) + 1)))
        tbl = shape.table
        tbl_pr = shape._element.graphic.graphicData.tbl.tblPr
        tbl_pr.set("bandRow", "0")
        tbl_pr.set("firstRow", "0")
        for r, row in enumerate([headers] + rows):
            for c, val in enumerate(row):
                cell = tbl.cell(r, c)
                is_hl = hl is not None and c == hl
                fill = (self.tint("info") if r == 0 else self.t["colors"]["card"])
                if is_hl:
                    fill = self.tint("highlight")
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(fill)
                cell.margin_top = cell.margin_bottom = Emu(0)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                para = cell.text_frame.paragraphs[0]
                para.alignment = PP_ALIGN.CENTER
                self._fill_paragraph(para, str(val), sz["small"],
                                     self.color("info") if r == 0 else self.color("text"))
        if s.get("caption"):
            self.text(slide, x, BODY_TOP + row_h * (len(rows) + 1) + 0.1, w, 0.3, s["caption"],
                      size=sz["caption"], color="muted", align="c")

    def layout_bars(self, slide, s):
        items = s.get("items") or []
        sz = self.t["sizes"]
        vmax = s.get("max") or max(float(i["value"]) for i in items)
        best = s.get("best")
        label_w, bar_x = 3.2, LEFT + 3.5
        bar_w = RIGHT - bar_x - 1.6
        bottom = (TAKEAWAY_Y - 0.2) if s.get("takeaway") else BODY_BOTTOM
        if s.get("axis_label"):
            self.text(slide, bar_x, BODY_TOP - 0.05, bar_w, 0.3, s["axis_label"],
                      size=sz["caption"], color="muted")
        step = (bottom - BODY_TOP - 0.3) / max(len(items), 1)
        for i, it in enumerate(items):
            y = BODY_TOP + 0.3 + i * step
            is_best = best is not None and i == best
            tone = "alert" if is_best else None
            self.text(slide, LEFT + 0.2, y, label_w, 0.4, it["label"], size=sz["body"],
                      color=tone or "text", anchor="m")
            frac = float(it["value"]) / vmax if vmax else 0
            self.box(slide, bar_x, y + 0.08, max(bar_w * frac, 0.05), 0.24,
                     fill=self.tint("alert") if is_best else self.t["colors"]["panel"],
                     border=self.accent("alert") if is_best else None, rounded=False,
                     shadow=False, border_w=1)
            note = f"{it['value']}" + (f"　{it['note']}" if it.get("note") else "")
            self.text(slide, bar_x + bar_w * frac + 0.1, y, 2.6, 0.4, note,
                      size=sz["caption"] + 1, color=tone or "muted", anchor="m")

    def layout_flow(self, slide, s):
        steps = s.get("steps") or []
        n = len(steps)
        arrow_w = 0.45
        w = (CONTENT_W - arrow_w * (n - 1)) / n
        bottom = (TAKEAWAY_Y - 0.15) if s.get("takeaway") else BODY_BOTTOM
        natural = max(self.card_height({"heading": 1, **c, "lines": c.get("lines") or []}, w)
                      for c in steps) + (2.2 if any(c.get("image") for c in steps) else 0.2)
        h = s.get("card_height") or min(natural, bottom - BODY_TOP)
        for i, c in enumerate(steps):
            x = LEFT + i * (w + arrow_w)
            fill = self.tint(c.get("tone")) if c.get("tone") else self.t["colors"]["card"]
            self.box(slide, x, BODY_TOP, w, h, fill=fill, border=self.t["colors"]["line"])
            self.text(slide, x + 0.2, BODY_TOP + 0.15, w - 0.4, 0.45,
                      f"{i + 1}. {c.get('heading', '')}", size=self.t["sizes"]["body"],
                      color=c.get("tone") or "info")
            if c.get("image"):
                self.image(slide, c["image"], x + 0.2, BODY_TOP + 0.7, w - 0.4, h - 1.6,
                           c.get("image_label", ""))
            self.text(slide, x + 0.2, BODY_TOP + (h - 0.85 if c.get("image") else 0.75),
                      w - 0.4, 0.8 if c.get("image") else h - 0.9, c.get("lines") or [],
                      size=self.t["sizes"]["small"], color="muted",
                      align="c" if c.get("image") else "l", spacing=4)
            if i < n - 1:
                self.arrow(slide, x + w + 0.06, BODY_TOP + h / 2, x + w + arrow_w - 0.06,
                           BODY_TOP + h / 2)

    def layout_image(self, slide, s):
        bottom = BODY_BOTTOM - (0.85 if s.get("quote") else 0.35)
        self.image(slide, s.get("image"), LEFT + 0.6, BODY_TOP - 0.1, CONTENT_W - 1.2,
                   bottom - BODY_TOP, s.get("image_label", ""))
        if s.get("caption"):
            self.text(slide, LEFT, bottom + 0.0, CONTENT_W, 0.3, s["caption"],
                      size=self.t["sizes"]["caption"], color="muted", align="c")
        if s.get("quote"):
            self.box(slide, LEFT + 0.6, BODY_BOTTOM - 0.55, CONTENT_W - 1.2, 0.6,
                     fill=self.t["colors"]["panel"])
            self.text(slide, LEFT + 0.8, BODY_BOTTOM - 0.55, CONTENT_W - 1.6, 0.6,
                      f"“{s['quote']}”", size=self.t["sizes"]["small"] + 2, color="muted",
                      align="c", anchor="m")

    def layout_code(self, slide, s):
        sz = self.t["sizes"]
        code = s.get("code", "").rstrip("\n").split("\n")
        notes = s.get("points") or []
        code_w = CONTENT_W if not notes else 7.6
        bottom = (TAKEAWAY_Y - 0.15) if s.get("takeaway") else BODY_BOTTOM
        natural = 0.75 + len(code) * (sz["small"] - 1) * 1.3 / 72
        bottom = min(bottom, BODY_TOP + max(natural, 1.05 * len(notes)))
        self.box(slide, LEFT, BODY_TOP, code_w, bottom - BODY_TOP,
                 fill=self.t["colors"]["panel"], border=self.t["colors"]["line"], radius=0.06)
        if s.get("label"):
            self.text(slide, LEFT + 0.25, BODY_TOP + 0.12, code_w - 0.5, 0.3, s["label"],
                      size=sz["caption"], color="muted")
        self.text(slide, LEFT + 0.25, BODY_TOP + 0.45, code_w - 0.5, bottom - BODY_TOP - 0.6,
                  code, size=sz["small"] - 1, mono=True)
        for i, p in enumerate(notes):
            y = BODY_TOP + i * 1.05
            tone = p.get("tone", "info")
            self.box(slide, LEFT + code_w + 0.35, y, RIGHT - LEFT - code_w - 0.35, 0.9,
                     fill=self.tint(tone))
            self.text(slide, LEFT + code_w + 0.55, y + 0.08, RIGHT - LEFT - code_w - 0.75, 0.3,
                      p.get("heading", ""), size=sz["small"], color=tone)
            self.text(slide, LEFT + code_w + 0.55, y + 0.4, RIGHT - LEFT - code_w - 0.75, 0.45,
                      p.get("text", ""), size=sz["small"] - 1, color="muted")

    def layout_compare(self, slide, s):
        panels = s.get("panels") or []
        if len(panels) != 2:
            raise SpecError(f"slide {self.slide_no}: compare layout needs exactly 2 panels")
        bottom = (TAKEAWAY_Y - 0.15) if s.get("takeaway") else BODY_BOTTOM
        w = (CONTENT_W - 0.35) / 2
        if not any(p.get("image") for p in panels):
            natural = max(self.card_height({"heading": 1, "lines": p.get("lines") or []}, w)
                          for p in panels) + 0.3
            bottom = min(bottom, BODY_TOP + natural)
        for i, p in enumerate(panels):
            x = LEFT + i * (w + 0.35)
            tone = p.get("tone", "info" if i == 0 else "positive")
            self.box(slide, x, BODY_TOP, w, bottom - BODY_TOP, fill=self.tint(tone))
            self.text(slide, x + 0.3, BODY_TOP + 0.15, w - 0.6, 0.45, p.get("heading", ""),
                      size=self.t["sizes"]["body"] + 1, color=tone)
            if p.get("image"):
                self.image(slide, p["image"], x + 0.3, BODY_TOP + 0.75, w - 0.6,
                           bottom - BODY_TOP - 1.9, p.get("image_label", ""))
            self.text(slide, x + 0.3, bottom - (1.05 if p.get("image") else
                                                bottom - BODY_TOP - 0.75),
                      w - 0.6, 1.0 if p.get("image") else bottom - BODY_TOP - 0.9,
                      p.get("lines") or [], size=self.t["sizes"]["small"] + 1, spacing=6)

    def layout_sources(self, slide, s):
        items = s.get("items") or []
        half = (len(items) + 1) // 2 if len(items) > 12 else len(items)
        cols = [items[:half], items[half:]] if half < len(items) else [items]
        w = CONTENT_W / len(cols) - 0.2
        for i, col in enumerate(cols):
            self.text(slide, LEFT + i * (w + 0.4), BODY_TOP, w, BODY_BOTTOM - BODY_TOP + 0.5,
                      [f"{half * i + k + 1}. {line}" for k, line in enumerate(col)],
                      size=self.t["sizes"]["caption"] + 1, color="muted", spacing=5)

    # ── driver ────────────────────────────────────────────────────────────
    def build(self) -> Presentation:
        for s in self.spec.get("slides", []):
            layout = s.get("layout")
            if layout not in LAYOUTS:
                raise SpecError(f"slide {self.slide_no + 1}: unknown layout {layout!r}; "
                                f"expected one of {', '.join(LAYOUTS)}")
            slide = self.new_slide(s)
            getattr(self, f"layout_{layout}")(slide, s)
            if layout != "title":
                self.chrome(slide, s)
                if not s.get("source") and layout != "sources":
                    self.warnings.append(f"slide {self.slide_no}: no source footnote")
        return self.prs


def build(spec_path: Path, out: Path, theme_override: str | None = None,
          preset_override: str | None = None) -> list[str]:
    """Build ``spec_path`` into ``out`` and return the lint warnings."""
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("slides"):
        raise SpecError("spec must be a mapping with a non-empty 'slides' list")
    deck = spec.get("deck") or {}
    preset = load_preset(preset_override or deck.get("preset"))
    theme_name = theme_override or deck.get("theme") or preset.get("default_theme") or "default"
    theme = load_theme(theme_name, preset)
    builder = Builder(theme, spec, spec_path.parent, preset)
    prs = builder.build()
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    return builder.warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--preset", help="preset name under presets/, or path to a preset folder")
    ap.add_argument("--theme", help="theme name (preset's, then core) or path to a theme YAML")
    args = ap.parse_args(argv)
    try:
        warnings = build(args.spec, args.out, args.theme, args.preset)
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"warning: {w}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
