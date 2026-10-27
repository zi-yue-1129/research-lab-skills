#!/usr/bin/env python3
"""Render a .pptx to per-slide PNGs and a contact sheet for visual review.

Usage:
    python3 render_preview.py deck.pptx [--out preview_dir] [--dpi 60]

Needs LibreOffice (``soffice``) and Poppler (``pdftoppm``) on PATH, plus
Pillow for the contact sheet. LibreOffice substitutes fonts it lacks (for
example 標楷體), so check layout and overflow here, not exact typography.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def render(pptx: Path, out: Path, dpi: int = 60, cols: int = 4) -> Path:
    for tool in ("soffice", "pdftoppm"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} not found on PATH")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp,
                        str(pptx)], check=True, capture_output=True, timeout=300)
        pdf = Path(tmp) / f"{pptx.stem}.pdf"
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(out / "slide")],
                       check=True, timeout=300)
    pages = sorted(out.glob("slide-*.png"))
    from PIL import Image

    first = Image.open(pages[0])
    w, h = first.size
    rows = (len(pages) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, h * rows), "white")
    for i, p in enumerate(pages):
        sheet.paste(Image.open(p), ((i % cols) * w, (i // cols) * h))
    path = out / "contact-sheet.png"
    sheet.save(path)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pptx", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dpi", type=int, default=60)
    args = ap.parse_args(argv)
    out = args.out or args.pptx.with_name(f"{args.pptx.stem}_preview")
    try:
        sheet = render(args.pptx, out, args.dpi)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"slides: {out}\ncontact sheet: {sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
