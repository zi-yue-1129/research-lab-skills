"""The automatic rules of the research deck quality standard.

Each ``check_*`` function takes the opened presentation and a ``Config`` and
returns ``Finding`` objects. Rule ids match
``references/deck-quality/standard.md``.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Config
from .ooxml import NS, Box, font_scheme, geometry, local, placeholder_type, q, theme_parts, theme_root, walk
from .text import em_width, scripts_in

EMU_PER_PT = 12700
EMU_PER_IN = 914400


@dataclass
class Finding:
    rule: str
    slide: int | None
    message: str
    subject: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        where = f"slide {self.slide}" if self.slide is not None else "deck"
        return f"[{self.rule}] {where}: {self.message}"


def _snip(text: str, n: int = 24) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _paragraph_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(q("a:t")))


def slide_paragraphs(slide):
    """Yield the text of every paragraph drawn on the slide (not the notes)."""
    for p in slide.shapes._spTree.iter(q("a:p")):
        text = _paragraph_text(p)
        if text.strip():
            yield text


def notes_text(slide) -> str:
    if not slide.has_notes_slide:
        return ""
    frame = slide.notes_slide.notes_text_frame
    return frame.text if frame is not None else ""


# ── A. fonts ──────────────────────────────────────────────────────────────

def _theme_faces(prs) -> dict:
    for part in theme_parts(prs):
        return font_scheme(theme_root(part))
    return {"major": {"latin": None, "ea": None}, "minor": {"latin": None, "ea": None}}


def _resolve_face(rpr, lst_rpr, script: str, theme: dict, kind: str) -> str | None:
    """Effective face for ``script`` (``latin`` or ``ea``) of one run.

    Looks at the run, then the text body's list style, then the theme. Master
    text styles are not followed; the theme fonts are what A3 pins down.
    """
    for props in (rpr, lst_rpr):
        if props is None:
            continue
        node = props.find(f"a:{script}", NS)
        if node is not None and node.get("typeface"):
            face = node.get("typeface")
            if face.startswith("+mj"):
                return theme["major"]["latin" if face.endswith("lt") else "ea"]
            if face.startswith("+mn"):
                return theme["minor"]["latin" if face.endswith("lt") else "ea"]
            return face
    return theme[kind][script]


def check_fonts(prs, cfg: Config) -> list[Finding]:
    """A1 and A2: one script per run, and the right face for each script."""
    if not cfg.has_font_pairing:
        return []
    theme = _theme_faces(prs)
    found: list[Finding] = []
    for n, slide in enumerate(prs.slides, 1):
        for el, _ in walk(slide.shapes._spTree):
            kind = "major" if placeholder_type(el) in ("title", "ctrTitle") else "minor"
            for body in el.iter(q("a:txBody"), q("p:txBody")):
                for p in body.iter(q("a:p")):
                    level = int((p.find("a:pPr", NS).get("lvl", 0)
                                 if p.find("a:pPr", NS) is not None else 0)) + 1
                    lst = body.find(f"a:lstStyle/a:lvl{level}pPr/a:defRPr", NS)
                    for run in p:
                        if local(run) not in ("r", "fld"):
                            continue
                        t = run.find("a:t", NS)
                        text = t.text if t is not None and t.text else ""
                        scripts = scripts_in(text)
                        if not scripts:
                            continue
                        if len(scripts) > 1:
                            found.append(Finding(
                                "A2", n, f"run mixes CJK and Latin text: {_snip(text)!r}; "
                                "split it so each script gets its own face", text))
                            continue
                        rpr = run.find("a:rPr", NS)
                        latin = _resolve_face(rpr, lst, "latin", theme, kind)
                        ea = _resolve_face(rpr, lst, "ea", theme, kind)
                        if "cjk" in scripts:
                            if ea != cfg.cjk_font:
                                found.append(Finding(
                                    "A1", n, f"CJK run {_snip(text)!r} uses ea face "
                                    f"{ea!r}, expected {cfg.cjk_font!r}", text))
                            elif latin != cfg.cjk_font:
                                found.append(Finding(
                                    "A2", n, f"CJK run {_snip(text)!r} sets only the ea face; "
                                    f"latin is {latin!r}, expected {cfg.cjk_font!r}", text))
                        elif latin != cfg.latin_font:
                            found.append(Finding(
                                "A1", n, f"Latin run {_snip(text)!r} uses {latin!r}, "
                                f"expected {cfg.latin_font!r}", text))
    return found


def check_theme_fonts(prs, cfg: Config) -> list[Finding]:
    """A3: theme major and minor fonts both carry the pairing."""
    if not cfg.has_font_pairing:
        return []
    found: list[Finding] = []
    want = {"latin": cfg.latin_font, "ea": cfg.cjk_font}
    for part in theme_parts(prs):
        scheme = font_scheme(theme_root(part))
        for kind, faces in scheme.items():
            for script, face in faces.items():
                if face != want[script]:
                    found.append(Finding(
                        "A3", None, f"theme {kind} {script} font is {face!r}, "
                        f"expected {want[script]!r}", f"{kind}-{script}"))
    return found


# ── B. wording ────────────────────────────────────────────────────────────

_GREEK = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu "
          "xi pi rho sigma tau upsilon phi chi psi omega").split()
B1_PATTERNS = (
    (re.compile(r"`[^`]+`"), "code in backticks"),
    (re.compile(r"(?<![\w/.])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b"), "snake_case identifier"),
    (re.compile(r"\b[A-Za-z_]\w*(?:\.\w+)*\(\)"), "function call"),
    (re.compile(r"\b(?:" + "|".join(_GREEK) + r")\b"), "spelled-out Greek letter"),
    (re.compile(r"\bd[xyzt]\b"), "differential written as a variable"),
)
B2_PATTERNS = (
    (re.compile(r"\b[vV]\d+(?:\.\d+)*\b"), "internal version number"),
    (re.compile(r"\b[A-Z]{1,2}\d{1,3}\b"), "experiment or run code"),
    (re.compile(r"\b(?:run|exp|trial|ckpt)[-_ #]?\d+\b", re.IGNORECASE), "run id"),
    (re.compile(r"(?<![\d.,])\d{6,}\b(?![.,]\d)"), "long numeric id"),
    (re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"), "commit hash"),
)
_EXTS = "py|ipynb|csv|tsv|json|ya?ml|txt|md|log|sh|pt|pth|ckpt|npy|npz|h5|pkl|parquet|mat|pptx|xlsx|svg"
B4_PATH_PATTERNS = (
    (re.compile(r"\b[A-Za-z]:\\"), "Windows path"),
    (re.compile(r"(?:~|\.{1,2})?/?(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,6}\b"), "file path"),
    (re.compile(rf"\b[\w-]+\.(?:{_EXTS})\b"), "file name"),
)


def _term_findings(rule, n, text, patterns, allow) -> list[Finding]:
    out, taken = [], []
    for rx, what in patterns:
        for m in rx.finditer(text):
            term = m.group(0)
            if term in allow or any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append(m.span())
            out.append(Finding(rule, n, f"{what} {term!r} in {_snip(text)!r}", term))
    return out


def check_wording(prs, cfg: Config) -> list[Finding]:
    """B1, B2, B4 on the text drawn on each slide."""
    allow = set(cfg.allow)
    labels = "|".join(re.escape(lbl) for lbl in sorted(cfg.source_labels, key=len, reverse=True))
    source_rx = re.compile(rf"(?<!\w)(?:{labels})\s*[:：]", re.IGNORECASE)
    found: list[Finding] = []
    for n, slide in enumerate(prs.slides, 1):
        for text in slide_paragraphs(slide):
            if "B1" in cfg.rules:
                found += _term_findings("B1", n, text, B1_PATTERNS, allow)
            if "B2" in cfg.rules:
                found += _term_findings("B2", n, text, B2_PATTERNS, allow)
            if "B4" in cfg.rules:
                m = source_rx.search(text)
                if m:
                    found.append(Finding("B4", n, f"source line on the slide: {_snip(text)!r}; "
                                         "move it to the speaker notes", m.group(0)))
                found += _term_findings("B4", n, text, B4_PATH_PATTERNS, allow)
    return found


# ── E. layout ─────────────────────────────────────────────────────────────

def _has_arrowhead(el) -> bool:
    ln = el.find("p:spPr/a:ln", NS)
    if ln is None:
        return False
    return any(end is not None and end.get("type", "none") != "none"
               for end in (ln.find("a:headEnd", NS), ln.find("a:tailEnd", NS)))


def _diagonal(dx: float, dy: float, rot: int, tol: float) -> bool:
    if math.hypot(dx, dy) <= tol:
        return False
    if rot % 5400000:
        return True
    return abs(dx) > tol and abs(dy) > tol


def check_connectors(prs, cfg: Config) -> list[Finding]:
    """E1: straight connectors, line shapes, and arrowed open paths run
    horizontally or vertically; elbow connectors pass, curves fail."""
    tol = 1.0 * EMU_PER_PT
    found: list[Finding] = []
    for n, slide in enumerate(prs.slides, 1):
        for el, tf in walk(slide.shapes._spTree):
            tag = local(el)
            geom = geometry(el, tf)
            if geom is None or tag not in ("sp", "cxnSp"):
                continue
            name = (el.find(".//p:cNvPr", NS).get("name", "") if el.find(".//p:cNvPr", NS)
                    is not None else "")
            prst = el.find("p:spPr/a:prstGeom", NS)
            prst_name = prst.get("prst", "") if prst is not None else ""
            is_line = tag == "cxnSp" or prst_name == "line"
            if is_line:
                if prst_name.startswith("curvedConnector"):
                    found.append(Finding("E1", n, f"curved connector {name!r}; use an "
                                         "elbow connector", name))
                elif prst_name.startswith("bentConnector"):
                    if geom.rot % 5400000:
                        found.append(Finding("E1", n, f"rotated elbow connector {name!r}", name))
                elif _diagonal(geom.box.w, geom.box.h, geom.rot, tol):
                    found.append(Finding("E1", n, f"diagonal line {name!r} "
                                         f"({geom.box.w / EMU_PER_IN:.2f} × "
                                         f"{geom.box.h / EMU_PER_IN:.2f} in); route it "
                                         "with horizontal and vertical segments", name))
                continue
            cust = el.find("p:spPr/a:custGeom", NS)
            if cust is None or not _has_arrowhead(el):
                continue
            for path in cust.iter(q("a:path")):
                if path.find("a:close", NS) is not None:
                    continue
                pw = float(path.get("w", 0)) or geom.box.w
                ph = float(path.get("h", 0)) or geom.box.h
                sx = geom.box.w / pw if pw else 1.0
                sy = geom.box.h / ph if ph else 1.0
                prev = None
                for cmd in path:
                    kind = local(cmd)
                    pts = [(float(pt.get("x")), float(pt.get("y")))
                           for pt in cmd.findall("a:pt", NS)]
                    if kind in ("cubicBezTo", "quadBezTo", "arcTo"):
                        found.append(Finding("E1", n, f"curved arrow path {name!r}", name))
                        break
                    if kind == "lnTo" and prev and pts:
                        dx, dy = (pts[0][0] - prev[0]) * sx, (pts[0][1] - prev[1]) * sy
                        if _diagonal(dx, dy, geom.rot, tol):
                            found.append(Finding("E1", n, f"diagonal segment in arrow "
                                                 f"path {name!r}", name))
                            break
                    if pts:
                        prev = pts[-1]
    return found


def _text_box(el, geom, theme_size=1800) -> tuple[Box, str] | None:
    """Estimated rectangle the text of a shape occupies, plus its text."""
    body = el.find("p:txBody", NS)
    if body is None:
        return None
    paras = body.findall("a:p", NS)
    texts = [_paragraph_text(p) for p in paras]
    if not any(t.strip() for t in texts):
        return None
    bpr = body.find("a:bodyPr", NS)
    get = (lambda k, d: float(bpr.get(k, d))) if bpr is not None else (lambda k, d: float(d))
    l_ins, r_ins = get("lIns", 91440), get("rIns", 91440)
    t_ins, b_ins = get("tIns", 45720), get("bIns", 45720)
    wrap = bpr is None or bpr.get("wrap", "square") != "none"
    anchor = bpr.get("anchor", "t") if bpr is not None else "t"
    scale = 1.0
    auto = bpr.find("a:normAutofit", NS) if bpr is not None else None
    if auto is not None and auto.get("fontScale"):
        scale = float(auto.get("fontScale")) / 100000
    box = geom.box
    inner_w = max(box.w - l_ins - r_ins, 1.0)
    lst = body.find("a:lstStyle/a:lvl1pPr/a:defRPr", NS)
    default_sz = float(lst.get("sz")) if lst is not None and lst.get("sz") else theme_size
    widest, height = 0.0, 0.0
    algn = "l"
    for i, (p, text) in enumerate(zip(paras, texts)):
        sizes = [float(r.get("sz")) for r in p.iter(q("a:rPr"), q("a:endParaRPr"))
                 if r.get("sz")]
        size_emu = (max(sizes) if sizes else default_sz) / 100 * EMU_PER_PT * scale
        width = em_width(text) * size_emu
        lines = max(1, math.ceil(width / inner_w)) if wrap and width else 1
        widest = max(widest, min(width, inner_w) if wrap else width)
        # Ink height: one em for the first line, 1.2 em leading for each next.
        height += (lines - 1) * size_emu * 1.2 + size_emu * (1.0 if i == 0 else 1.2)
        if i == 0 and p.find("a:pPr", NS) is not None:
            algn = p.find("a:pPr", NS).get("algn", "l")
    left = box.x + l_ins
    if algn == "ctr":
        x = box.x + box.w / 2 - widest / 2
    elif algn == "r":
        x = box.right - r_ins - widest
    else:
        x = left
    top_room = box.h - t_ins - b_ins
    if anchor == "ctr":
        y = box.y + t_ins + (top_room - height) / 2
    elif anchor == "b":
        y = box.bottom - b_ins - height
    else:
        y = box.y + t_ins
    return Box(x, y, widest, height), " ".join(t for t in texts if t.strip())


def check_layout(prs, cfg: Config) -> list[Finding]:
    """E2 (screening): estimated text extents must not overlap or leave the page.

    Widths are estimated (CJK 1 em, other 0.5 em), so this flags likely
    problems; the exported page images are the final word.
    """
    sw, sh = float(prs.slide_width), float(prs.slide_height)
    tol = 0.02 * EMU_PER_IN
    found: list[Finding] = []
    for n, slide in enumerate(prs.slides, 1):
        rects: list[tuple[Box, str]] = []
        for el, tf in walk(slide.shapes._spTree):
            geom = geometry(el, tf)
            if geom is None or geom.rot:
                continue
            est = _text_box(el, geom) if local(el) == "sp" else None
            if local(el) == "graphicFrame" and el.find(".//a:tbl", NS) is not None:
                est = (geom.box, " ".join(_paragraph_text(p) for p in el.iter(q("a:p"))))
            if est is None:
                continue
            rect, text = est
            rects.append((rect, text))
            if (rect.x < -tol or rect.y < -tol or rect.right > sw + tol
                    or rect.bottom > sh + tol):
                found.append(Finding("E2", n, f"text {_snip(text)!r} runs off the page",
                                     text))
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                w, h = rects[i][0].intersection(rects[j][0])
                if w > tol and h > tol:
                    a, b = _snip(rects[i][1]), _snip(rects[j][1])
                    found.append(Finding("E2", n, f"text {a!r} overlaps text {b!r}",
                                         f"{rects[i][1]} | {rects[j][1]}"))
    return found


# ── F. speaker notes ──────────────────────────────────────────────────────

def click_count(slide) -> int:
    """Number of on-click animation steps in the slide's main sequence."""
    return sum(1 for ctn in slide._element.iter(q("p:cTn"))
               if ctn.get("nodeType") == "clickEffect")


def check_notes(prs, cfg: Config) -> list[Finding]:
    """F2 and F3."""
    found: list[Finding] = []
    marker = cfg.click_marker
    for n, slide in enumerate(prs.slides, 1):
        notes = notes_text(slide)
        if "F2" in cfg.rules and not notes.strip():
            found.append(Finding("F2", n, "no speaker notes"))
            continue
        if "F3" in cfg.rules:
            marks, clicks = notes.count(marker), click_count(slide)
            if marks != clicks:
                found.append(Finding("F3", n, f"notes have {marks} × {marker} but the "
                                     f"slide has {clicks} click animation(s)",
                                     f"{marks}/{clicks}"))
    return found


# ── G. output file ────────────────────────────────────────────────────────

TIMESTAMPED = re.compile(r"^(?P<stem>.+)-(?P<ts>\d{8}T\d{6})\.pptx$")


def check_output_name(path: Path, siblings: bool = True) -> list[Finding]:
    """G1: ``<stem>-YYYYMMDDTHHMMSS.pptx``, and (with ``siblings``) no older
    copy beside it."""
    path = Path(path)
    m = TIMESTAMPED.match(path.name)
    if not m:
        return [Finding("G1", None, f"{path.name} has no timestamp; expected "
                        "<name>-YYYYMMDDTHHMMSS.pptx", path.name)]
    if not siblings:
        return []
    others = sorted(p.name for p in path.parent.glob(f"{m['stem']}-*.pptx")
                    if p != path and TIMESTAMPED.match(p.name)
                    and TIMESTAMPED.match(p.name)["stem"] == m["stem"])
    if others:
        return [Finding("G1", None, f"older copies kept beside {path.name}: "
                        f"{', '.join(others)}", path.name)]
    return []


CHECKS = (
    ("A1", check_fonts),
    ("A3", check_theme_fonts),
    ("B1", check_wording),
    ("E1", check_connectors),
    ("E2", check_layout),
    ("F2", check_notes),
)


def run_checks(prs, cfg: Config) -> list[Finding]:
    found: list[Finding] = []
    for _, check in CHECKS:
        found += check(prs, cfg)
    return [f for f in found if f.rule in cfg.rules]
