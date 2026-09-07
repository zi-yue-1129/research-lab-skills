#!/usr/bin/env python3
"""pptx_com.py -- drive an installed Microsoft PowerPoint as a native Windows
renderer and post-layout geometry oracle.

Why this exists
---------------
The PPTX visual gate (references/visual-review.md) requires converting the
*actual* exported deck with "LibreOffice or an equivalent available office
renderer" and inspecting one PNG per slide. On Windows that documented path
needs two Unix tools -- `libreoffice` and `pdftoppm` -- that are not present on
a stock Windows install, so `statuses.pptx_render` is permanently `blocked`
there and no deck can legally reach `completed`.

A Windows box that has PowerPoint already has a better renderer than either:
PowerPoint itself. `Slide.Export()` writes PNG at an arbitrary resolution with
no PDF intermediate, and it is the same layout engine that will draw the deck
when the reader opens it.

This module is therefore the "equivalent office renderer" for Windows. It is
*additive*: LibreOffice remains the cross-platform default and the only path on
macOS/Linux, and nothing here is imported at module scope, so this file stays
importable (and testable) on a machine with no COM, no pywin32, and no Office.

Second capability: a layout oracle
----------------------------------
`python-pptx` writes OOXML but cannot lay it out -- it has no font metrics, so
it structurally cannot know that a paragraph will reflow past the box it was
put in. PowerPoint can: `TextFrame2.TextRange.BoundHeight` is the height the
text *actually* occupies after layout. `--layout` exposes that, which turns the
skill's clipping / text-reflow checks from an inference over SVG source into a
measurement of the real thing.

Usage
-----
    python pptx_com.py --probe --json
    python pptx_com.py --render --pptx deck.pptx --out renders/pptx/powerpoint
    python pptx_com.py --layout --pptx deck.pptx --json

`--render` prints a JSON object shaped to drop straight into a review record's
`statuses.pptx_render` renderer evidence (`renderer.name` / `.version` /
`.conversion_format`, `conversion_artifacts`, `rendered_png_paths`).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

#: Per-thread record of whether this module has initialized the COM apartment.
#: See `_session` for why it is initialized once and never uninitialized.
_APARTMENT = threading.local()

#: Renderer identity recorded in `statuses.pptx_render.renderer.name`.
RENDERER_NAME = "Microsoft PowerPoint (COM)"

#: No PDF sits between the deck and the reviewed pixels, unlike LibreOffice's
#: `pdf-to-png`. Recorded verbatim in `renderer.conversion_format`.
CONVERSION_FORMAT = "direct-png"

#: Default export size. 1920x1080 is 16:9 at a resolution where 12pt body text
#: is legible to model vision without the files becoming unwieldy.
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080

#: `Presentation.SaveAs` format code for PDF (ppSaveAsPDF).
_PP_SAVE_AS_PDF = 32

#: msoAutoSizeNone -- the only autosize mode under which a text run exceeding
#: its shape is a genuine clip rather than the shape being about to grow.
_MSO_AUTOSIZE_NONE = 0

#: Points of overflow tolerated before a shape is called clipped. Below roughly
#: a third of a line the difference is descender/leading rounding, not a defect.
_OVERFLOW_TOLERANCE_PT = 0.5


class PowerPointUnavailable(RuntimeError):
    """Raised when this host cannot drive PowerPoint over COM.

    Carries the specific missing capability so a caller can record it verbatim
    as the `statuses.pptx_render` blocker instead of a generic failure.
    """


def probe() -> Dict[str, Any]:
    """Report whether this host can render through PowerPoint.

    Never raises: a caller uses this to *choose* a renderer, so an unavailable
    host is an answer, not an error.

    Returns:
        `{"available": bool, "name": str, "version": str|None, "reason": str|None}`
        where `reason` explains the unavailability and is `None` when available.
    """
    result: Dict[str, Any] = {
        "available": False,
        "name": RENDERER_NAME,
        "version": None,
        "reason": None,
    }
    if sys.platform != "win32":
        result["reason"] = f"PowerPoint COM automation requires Windows (host platform: {sys.platform})"
        return result
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        result["reason"] = "pywin32 is not installed (pip install pywin32)"
        return result
    try:
        with _session() as (app, _):
            result["available"] = True
            result["version"] = str(app.Version)
    except PowerPointUnavailable as exc:
        result["reason"] = str(exc)
    return result


@contextlib.contextmanager
def _session(pptx: Optional[Path] = None) -> Iterator[Tuple[Any, Any]]:
    """Yield a live `(Application, Presentation|None)` pair and always clean up.

    Two hazards this closes over:

    * PowerPoint is single-instance per user, so `Dispatch` may hand back the
      instance the user already has open with their own work in it. Quitting
      that would close their decks. The app is therefore only quit when it held
      no presentations before this call -- i.e. when we started it.
    * A COM object left un-closed leaves an orphan POWERPNT.EXE holding a file
      lock on the deck, which the next export then fails to overwrite.

    Args:
        pptx: Deck to open read-only and without a window. `None` opens no deck,
            which is what `probe` needs.

    Yields:
        The `Application` object and the opened `Presentation` (or `None`).

    Raises:
        PowerPointUnavailable: COM is unreachable or the deck cannot be opened.
    """
    import pythoncom
    import win32com.client

    # Initialize the apartment once per thread and never tear it down. A
    # matching CoUninitialize() here would run while the *caller* still has the
    # `app` proxy bound in its frame -- the `with ... as (app, presentation)`
    # names outlive the block -- and releasing a proxy to an already-quit
    # PowerPoint during apartment teardown raises RPC_E_DISCONNECTED
    # (0x80010108). The apartment is per-thread and these entrypoints are
    # short-lived, so letting process exit reclaim it is the correct trade.
    # (PowerPoint's own shutdown still reports that code once per quit under a
    # faulthandler-enabled runner such as pytest -- measured identically when
    # releasing the proxy instead of calling Quit, and it leaves no orphan
    # process either way, so it is noise with nothing behind it to fix.)
    if not getattr(_APARTMENT, "initialized", False):
        pythoncom.CoInitialize()
        _APARTMENT.initialized = True

    app = None
    presentation = None
    started_by_us = False
    try:
        try:
            app = win32com.client.Dispatch("PowerPoint.Application")
            # Read before opening our own deck, so it counts only the user's.
            started_by_us = int(app.Presentations.Count) == 0
        except Exception as exc:  # pragma: no cover - host-dependent
            raise PowerPointUnavailable(
                f"could not start PowerPoint over COM: {exc}"
            ) from exc

        if pptx is not None:
            target = Path(pptx).resolve()
            if not target.is_file():
                raise PowerPointUnavailable(f"deck not found: {target}")
            try:
                # WithWindow=0 keeps the render off-screen; ReadOnly=1 makes an
                # export incapable of mutating the artifact under review.
                presentation = app.Presentations.Open(
                    str(target), ReadOnly=1, Untitled=0, WithWindow=0
                )
            except Exception as exc:  # pragma: no cover - host-dependent
                raise PowerPointUnavailable(
                    f"PowerPoint could not open {target}: {exc}"
                ) from exc

        yield app, presentation
    finally:
        if presentation is not None:
            with contextlib.suppress(Exception):
                presentation.Close()
        if app is not None and started_by_us:
            with contextlib.suppress(Exception):
                app.Quit()


def render(
    pptx: Path,
    out_dir: Path,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    prefix: str = "slide",
    pdf: bool = True,
) -> Dict[str, Any]:
    """Export one PNG per slide straight from PowerPoint.

    Args:
        pptx: The exported deck to convert. Convert the actual deck, never the
            source SVG -- that distinction is the whole point of the gate.
        out_dir: Directory for the PNGs; created if absent.
        width: Export width in pixels.
        height: Export height in pixels.
        prefix: PNG basename stem; files are `<prefix>-01.png`, zero-padded to
            two digits so a 10+ slide deck still sorts lexicographically.
        pdf: Also save a PDF beside the PNGs. On by default because the review
            record's `conversion_artifacts` must be a non-empty list of
            conversion outputs, and a PDF is the honest one for that field.

    Returns:
        Renderer evidence ready to merge into `statuses.pptx_render`.

    Raises:
        PowerPointUnavailable: This host cannot drive PowerPoint.
    """
    deck = Path(pptx).resolve()
    destination = Path(out_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    png_paths: List[str] = []
    pdf_path: Optional[Path] = None
    with _session(deck) as (app, presentation):
        version = str(app.Version)
        slide_count = int(presentation.Slides.Count)
        for index in range(1, slide_count + 1):
            png = destination / f"{prefix}-{index:02d}.png"
            presentation.Slides(index).Export(str(png), "PNG", width, height)
            png_paths.append(str(png))
        if pdf:
            pdf_path = destination / f"{deck.stem}.pdf"
            presentation.SaveAs(str(pdf_path), _PP_SAVE_AS_PDF)

    conversion_artifacts = [str(pdf_path)] if pdf_path is not None else list(png_paths)
    return {
        "renderer": {
            "name": RENDERER_NAME,
            "version": version,
            "conversion_format": CONVERSION_FORMAT,
        },
        "source_pptx": str(deck),
        "slide_count": slide_count,
        "export_size": {"width": width, "height": height},
        "conversion_artifacts": conversion_artifacts,
        "rendered_png_paths": png_paths,
    }


def layout(pptx: Path) -> Dict[str, Any]:
    """Report each shape's geometry *after* PowerPoint has laid the deck out.

    Every measurement is in points, PowerPoint's own unit, matching the type
    sizes in the design tokens so an overflow is directly comparable to the
    type scale that caused it.

    `text_bound_height` is the height the laid-out text occupies, which is the
    fact `python-pptx` cannot supply. Text exceeding its shape is reported two
    ways, because the two failures are different: `clipped` means the text is
    cut off (a fixed-size box, `msoAutoSizeNone`), while `overflows_box` also
    covers an auto-sizing box that stays legible but silently grows past its
    declared bounds and can collide with whatever sits below it.

    Note: `Shapes` does not recurse into groups, so a grouped child is measured
    as part of its group's bounding box rather than individually.

    Args:
        pptx: The deck to measure.

    Returns:
        `{"source_pptx", "slide_count", "slides": [{"slide", "shapes": [...]}]}`.

    Raises:
        PowerPointUnavailable: This host cannot drive PowerPoint.
    """
    deck = Path(pptx).resolve()
    slides: List[Dict[str, Any]] = []
    with _session(deck) as (_, presentation):
        slide_count = int(presentation.Slides.Count)
        for index in range(1, slide_count + 1):
            shapes: List[Dict[str, Any]] = []
            for shape in presentation.Slides(index).Shapes:
                shapes.append(_measure_shape(shape))
            slides.append({"slide": index, "shapes": shapes})
    return {
        "source_pptx": str(deck),
        "slide_count": slide_count,
        "slides": slides,
    }


def _measure_shape(shape: Any) -> Dict[str, Any]:
    """Measure one laid-out shape.

    Args:
        shape: A live PowerPoint `Shape`.

    Returns:
        Geometry, plus text-extent fields when the shape holds text. A shape
        whose text frame cannot be read reports geometry alone rather than
        failing the whole measurement.
    """
    measured: Dict[str, Any] = {
        "name": str(shape.Name),
        "left": float(shape.Left),
        "top": float(shape.Top),
        "width": float(shape.Width),
        "height": float(shape.Height),
        "has_text": False,
    }
    try:
        if not shape.HasTextFrame:
            return measured
        frame = shape.TextFrame2
        if not frame.HasText:
            return measured
        text_range = frame.TextRange
        bound_height = float(text_range.BoundHeight)
        autosize = int(frame.AutoSize)
        overflow = bound_height - measured["height"]
        measured.update(
            {
                "has_text": True,
                "text": str(text_range.Text),
                "text_bound_left": float(text_range.BoundLeft),
                "text_bound_top": float(text_range.BoundTop),
                "text_bound_width": float(text_range.BoundWidth),
                "text_bound_height": bound_height,
                "autosize": autosize,
                "text_overflow_pt": round(overflow, 2),
                "overflows_box": overflow > _OVERFLOW_TOLERANCE_PT,
                "clipped": (
                    overflow > _OVERFLOW_TOLERANCE_PT and autosize == _MSO_AUTOSIZE_NONE
                ),
            }
        )
    except Exception as exc:  # pragma: no cover - host-dependent
        measured["text_measurement_error"] = str(exc)
    return measured


def clipped_shapes(layout_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pull just the clipped shapes out of a `layout` report.

    Args:
        layout_report: The mapping returned by `layout`.

    Returns:
        One entry per clipped shape, each carrying its slide number.
    """
    findings: List[Dict[str, Any]] = []
    for slide in layout_report.get("slides", []):
        for shape in slide.get("shapes", []):
            if shape.get("clipped"):
                findings.append({"slide": slide.get("slide"), **shape})
    return findings


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Render and measure a PPTX through the installed PowerPoint (Windows only).",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--probe", action="store_true", help="report renderer availability and exit")
    action.add_argument("--render", action="store_true", help="export one PNG per slide")
    action.add_argument("--layout", action="store_true", help="report post-layout geometry")

    parser.add_argument("--pptx", type=Path, help="deck to render or measure")
    parser.add_argument("--out", type=Path, help="output directory for --render")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="export width in pixels")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="export height in pixels")
    parser.add_argument("--prefix", default="slide", help="PNG basename stem (default: slide)")
    parser.add_argument(
        "--no-pdf",
        dest="pdf",
        action="store_false",
        help="skip the companion PDF (leaves conversion_artifacts as the PNG list)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON on stdout")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Run the command-line entrypoint.

    Args:
        argv: Argument vector; defaults to `sys.argv[1:]`.

    Returns:
        `0` on success, `1` for a usage error, `2` when the host cannot render.
        The distinct code lets a caller tell "no PowerPoint here, fall back to
        LibreOffice" apart from "the deck is broken".
    """
    args = _build_parser().parse_args(argv)

    if args.probe:
        report = probe()
        _emit(report, args.json)
        return 0

    if args.pptx is None:
        print("--pptx is required for --render and --layout", file=sys.stderr)
        return 1
    if args.render and args.out is None:
        print("--out is required for --render", file=sys.stderr)
        return 1

    try:
        if args.render:
            report = render(
                args.pptx,
                args.out,
                width=args.width,
                height=args.height,
                prefix=args.prefix,
                pdf=args.pdf,
            )
        else:
            report = layout(args.pptx)
    except PowerPointUnavailable as exc:
        payload = {"error": type(exc).__name__, "message": str(exc)}
        if args.json:
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"blocked: {exc}", file=sys.stderr)
        return 2

    _emit(report, args.json)
    return 0


def _emit(report: Dict[str, Any], as_json: bool) -> None:
    """Write a report to stdout as JSON or as a short human summary.

    Args:
        report: A `probe`, `render`, or `layout` result.
        as_json: Emit the full JSON document when true.
    """
    if as_json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    if "available" in report:
        state = "available" if report["available"] else "unavailable"
        detail = report.get("version") or report.get("reason")
        print(f"{report['name']}: {state} ({detail})")
    elif "rendered_png_paths" in report:
        print(f"rendered {report['slide_count']} slide(s) via {report['renderer']['name']}")
        for path in report["rendered_png_paths"]:
            print(f"  {path}")
    else:
        clipped = clipped_shapes(report)
        print(f"measured {report['slide_count']} slide(s); clipped shapes: {len(clipped)}")
        for shape in clipped:
            print(
                f"  slide {shape['slide']} {shape['name']!r}: "
                f"text overflows by {shape['text_overflow_pt']}pt"
            )


if __name__ == "__main__":
    raise SystemExit(main())
