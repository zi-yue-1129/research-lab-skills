#!/usr/bin/env python3
"""validate_pptx_layout.py -- measure the exported deck, not the SVG behind it.

Every measurable check in this skill runs against the authored SVG.
`visual_style.typography.check_overlong_text` is the closest thing to a
clipping check, and it counts *lines and words in the source* against a budget
-- a proxy, chosen because nothing in the pipeline could do better. `python-pptx`
has no font metrics, so it cannot know how tall a paragraph becomes; the SVG
scene knows only what the author wrote. Whether text actually overflows its box
depends on the layout engine that finally draws it, and until now nothing asked
that engine.

`pptx_com.layout` does. This gate turns its measurements into the same findings
the style linter produces, so a clipped label is reported as a measured fact
about the deck a reader will open rather than an inference about its source.

Two distinct defects are reported, because they fail differently:

* `pptx-clipped-text` (error) -- the text is cut off. A fixed-size box whose
  content exceeds it; the reader loses words.
* `pptx-overflowing-text` (warning) -- the text stays legible but its shape
  grew past the bounds the layout assumed, so it may now collide with whatever
  sits below. Legible, but no longer laid out as designed.

Windows only, because it needs a real PowerPoint. Elsewhere -- and on a Windows
host without Office -- it exits 2 and names the missing capability, which is
the same "blocked" signal `references/visual-review.md` already defines. It is
an additional gate, never a replacement for the model-vision review.

Usage:
    python validate_pptx_layout.py --pptx deck.pptx --json
    python validate_pptx_layout.py --pptx deck.pptx --tolerance 2.0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pptx_com

#: Points of overflow tolerated before a shape is reported. `pptx_com` applies
#: its own sub-point tolerance for rounding; this one is the *design* margin,
#: separately adjustable because a deck with tight leading may legitimately sit
#: a point or two over without a reader ever seeing it.
DEFAULT_TOLERANCE_PT = 1.0


def findings_for(layout_report: Dict[str, Any], tolerance_pt: float) -> List[Dict[str, Any]]:
    """Turn a layout report into style-linter-shaped findings.

    Args:
        layout_report: The mapping returned by `pptx_com.layout`.
        tolerance_pt: Overflow, in points, to tolerate before reporting.

    Returns:
        Findings ordered by slide then shape, each carrying the measured and
        expected values so it is falsifiable without rerunning the gate.
    """
    findings: List[Dict[str, Any]] = []
    for slide in layout_report.get("slides", []):
        number = slide.get("slide")
        for shape in slide.get("shapes", []):
            overflow = shape.get("text_overflow_pt")
            if overflow is None or overflow <= tolerance_pt:
                continue
            clipped = bool(shape.get("clipped"))
            findings.append(
                {
                    "rule": "pptx-clipped-text" if clipped else "pptx-overflowing-text",
                    "severity": "error" if clipped else "warning",
                    "message": (
                        f"slide {number} {shape.get('name')!r}: text occupies "
                        f"{shape.get('text_bound_height'):.1f}pt in a "
                        f"{shape.get('height'):.1f}pt shape, "
                        f"{overflow:.1f}pt over"
                        + ("" if clipped else "; the shape grows to fit, so it may overlap below")
                    ),
                    "element_id": shape.get("name"),
                    "slide": number,
                    "overflow_pt": overflow,
                }
            )
    return findings


def validate(pptx: Path, tolerance_pt: float = DEFAULT_TOLERANCE_PT) -> Dict[str, Any]:
    """Measure one exported deck and report its layout findings.

    Args:
        pptx: The exported deck. Measure the deck, never the source SVG --
            that distinction is the whole point of this gate.
        tolerance_pt: Overflow, in points, to tolerate before reporting.

    Returns:
        `{status, renderer, slide_count, findings}` where `status` is `passed`
        when nothing was found, and `failed` otherwise.

    Raises:
        pptx_com.PowerPointUnavailable: If this host cannot drive PowerPoint.
    """
    report = pptx_com.layout(pptx)
    findings = findings_for(report, tolerance_pt)
    return {
        "status": "failed" if findings else "passed",
        "reviewed_by": "pptx_layout_oracle",
        "renderer": {"name": pptx_com.RENDERER_NAME},
        "source_pptx": report.get("source_pptx"),
        "slide_count": report.get("slide_count"),
        "tolerance_pt": tolerance_pt,
        "findings": findings,
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Run the command-line entrypoint.

    Args:
        argv: Argument vector; defaults to `sys.argv[1:]`.

    Returns:
        `0` when the deck passes, `1` when findings were measured, and `2`
        when the host cannot render -- the same code `pptx_com` uses, so a
        caller can record `blocked` rather than mistaking it for a failure.
    """
    parser = argparse.ArgumentParser(
        description="Measure an exported PPTX's real text layout (Windows only).",
    )
    parser.add_argument("--pptx", type=Path, required=True, help="the exported deck")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE_PT,
        help=f"points of overflow to tolerate (default: {DEFAULT_TOLERANCE_PT})",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON on stdout")
    args = parser.parse_args(argv)

    try:
        result = validate(args.pptx, args.tolerance)
    except pptx_com.PowerPointUnavailable as exc:
        payload = {"status": "blocked", "blocker": str(exc)}
        if args.json:
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"blocked: {exc}", file=sys.stderr)
        return 2

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(
            f"{result['status']}: {len(result['findings'])} finding(s) "
            f"across {result['slide_count']} slide(s)"
        )
        for finding in result["findings"]:
            print(f"  [{finding['severity']}] {finding['message']}")

    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
