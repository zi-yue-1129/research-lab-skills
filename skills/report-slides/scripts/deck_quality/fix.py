"""Generator-side helpers that make a deck satisfy the automatic rules by
construction, rather than by fixing findings afterwards.

* ``apply_font_pairing`` (A1–A3): split every run by script and set its
  faces; set the theme's major and minor fonts to the same pairing.
* ``orthogonal_segments`` (E1): turn a polyline into segments, raising on any
  diagonal step, so a generator fails at the line that is wrong.
* ``timestamped_output`` / ``prune_older`` (G1).
"""
from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path

from lxml import etree

from .config import Config
from .ooxml import NS, local, q, theme_parts, theme_root
from .rules import TIMESTAMPED
from .text import split_by_script


# ── A. fonts ──────────────────────────────────────────────────────────────

_AFTER_FACES = ("a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst")


def style_run(run_el, script: str, cfg: Config) -> None:
    """Set the latin/ea/cs faces of one ``a:r`` for its script (A2).

    A CJK run gets the CJK face for latin and ea (some viewers draw CJK with
    the latin face); every other run gets the Latin face throughout.
    """
    rpr = run_el.find("a:rPr", NS)
    if rpr is None:
        rpr = etree.Element(q("a:rPr"))
        run_el.insert(0, rpr)
    face = cfg.cjk_font if script == "cjk" else cfg.latin_font
    for tag in ("latin", "ea", "cs"):
        old = rpr.find(f"a:{tag}", NS)
        if old is not None:
            rpr.remove(old)
    # Schema order inside rPr: ..., latin, ea, cs, sym, hlinkClick, ...
    anchor = next((rpr.find(t, NS) for t in _AFTER_FACES if rpr.find(t, NS) is not None), None)
    for tag in ("latin", "ea", "cs"):
        node = etree.Element(q(f"a:{tag}"), typeface=face)
        if anchor is not None:
            anchor.addprevious(node)
        else:
            rpr.append(node)


def split_and_style_runs(root, cfg: Config) -> int:
    """Split every run under ``root`` by script and style it. Returns runs written."""
    written = 0
    for p in list(root.iter(q("a:p"))):
        for run in [r for r in p if local(r) == "r"]:
            t = run.find("a:t", NS)
            text = t.text if t is not None and t.text else ""
            if not text:
                continue
            segments = split_by_script(text)
            previous = run
            for i, (script, segment) in enumerate(segments):
                target = run if i == 0 else copy.deepcopy(run)
                target.find("a:t", NS).text = segment
                if i:
                    previous.addnext(target)
                style_run(target, script, cfg)
                previous = target
                written += 1
    return written


def set_theme_fonts(prs, cfg: Config) -> None:
    """A3: theme major and minor fonts both become the pairing."""
    for part in theme_parts(prs):
        root = theme_root(part)
        for kind in ("majorFont", "minorFont"):
            node = root.find(f".//a:fontScheme/a:{kind}", NS)
            if node is None:
                continue
            for script, face in (("latin", cfg.latin_font), ("ea", cfg.cjk_font)):
                el = node.find(f"a:{script}", NS)
                if el is None:
                    el = etree.SubElement(node, q(f"a:{script}"))
                el.set("typeface", face)
                for attr in ("panose", "pitchFamily", "charset"):
                    el.attrib.pop(attr, None)
        part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                                    standalone=True)


def apply_font_pairing(prs, cfg: Config) -> int:
    """Apply A1–A3 to every slide and the theme. A no-op without a pairing."""
    if not cfg.has_font_pairing:
        return 0
    written = 0
    for slide in prs.slides:
        written += split_and_style_runs(slide.shapes._spTree, cfg)
    set_theme_fonts(prs, cfg)
    return written


# ── E. connectors ─────────────────────────────────────────────────────────

class DiagonalLineError(ValueError):
    """A generator asked for a connector segment that is not axis-aligned."""


def orthogonal_segments(points, tol: float = 1e-6):
    """Return consecutive ``((x1, y1), (x2, y2))`` segments of a polyline.

    Raises ``DiagonalLineError`` on the first segment that moves in both x and
    y, so a deck generator stops at the line that breaks E1. Insert an elbow
    point (``(x2, y1)`` or ``(x1, y2)``) to route around it.
    """
    pts = list(points)
    segments = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if abs(x2 - x1) > tol and abs(y2 - y1) > tol:
            raise DiagonalLineError(
                f"diagonal segment ({x1}, {y1}) → ({x2}, {y2}); add an elbow at "
                f"({x2}, {y1}) or ({x1}, {y2})")
        segments.append(((x1, y1), (x2, y2)))
    return segments


# ── G. output file ────────────────────────────────────────────────────────

def timestamped_output(out_dir: str | Path, stem: str = "deck",
                       now: datetime | None = None) -> Path:
    """``<out_dir>/<stem>-YYYYMMDDTHHMMSS.pptx`` for this run (G1)."""
    stamp = (now or datetime.now()).strftime("%Y%m%dT%H%M%S")
    return Path(out_dir) / f"{stem}-{stamp}.pptx"


def prune_older(keep: str | Path) -> list[Path]:
    """Delete older ``<stem>-<timestamp>.pptx`` copies beside ``keep``."""
    keep = Path(keep)
    m = TIMESTAMPED.match(keep.name)
    if not m:
        return []
    removed = []
    for p in keep.parent.glob(f"{m['stem']}-*.pptx"):
        other = TIMESTAMPED.match(p.name)
        if p != keep and other and other["stem"] == m["stem"]:
            p.unlink()
            removed.append(p)
    return sorted(removed)
