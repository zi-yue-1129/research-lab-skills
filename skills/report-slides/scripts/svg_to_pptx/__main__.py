"""__main__.py — CLI entry point for svg_to_pptx package."""
import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from presentation_gates import ProductionGateError, assert_production_allowed
from presentation_state import find_project_root

from .converter import convert_file

_MODE_HELP = """
SVG → PPTX conversion mode:

  [1] native  (default)
      Each SVG element becomes an individually editable shape — text boxes,
      rectangles, connectors, paths. Select and modify any element directly
      in PowerPoint. Best when you need to fine-tune content after export.

  [2] embed
      Each SVG is inserted as a single image object — pixel-perfect rendering.
      In PowerPoint, right-click the image → "Convert to Shapes" to ungroup
      it into editable objects (same as PowerPoint's built-in SVG conversion,
      but the result contains many small fragments).

"""


def _prompt_mode() -> str:
    print(_MODE_HELP, end="")
    while True:
        try:
            choice = input("Choose [1/2] (Enter = 1 native): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "native"
        if choice in ("", "1", "native"):
            return "native"
        if choice in ("2", "embed"):
            return "embed"
        print("  Please enter 1 or 2.")


def _resolve_mode(explicit: str | None) -> str:
    """Return the conversion mode, prompting only an interactive terminal.

    Omitting `--mode` printed a menu and called `input()`. A pipeline, a CI
    job, or an agent session has nobody to answer it: on a pipe the read
    blocks until the process is killed, and the export never finishes.

    Args:
        explicit: The `--mode` value, or None when the flag was omitted.

    Returns:
        "native" or "embed". Off a terminal the documented default is taken
        without asking.
    """
    if explicit is not None:
        return explicit
    stdin = sys.stdin
    if stdin is None or not stdin.isatty():
        return "native"
    return _prompt_mode()


def _authorize_production(deck_id: str, project_root: Path | None) -> Path | None:
    """Authorize the CLI before it enumerates inputs or creates outputs."""
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
    ap = argparse.ArgumentParser(
        description="Convert SVG slides to PPTX (native shapes or SVG embed)"
    )
    ap.add_argument("--slides", required=True,
                    help="Directory containing slide*.svg files")
    ap.add_argument("--out", required=True, help="Output .pptx file path")
    ap.add_argument("--deck-id", required=True, help="Approved presentation Deck identifier")
    ap.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root (defaults to the nearest ancestor of the current directory)",
    )
    ap.add_argument("--mode", choices=["native", "embed"], default=None,
                    help="native: editable shapes; embed: SVG blip. "
                         "Omit to be prompted with a description of each "
                         "mode at a terminal, or to take native off one.")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(arguments)

    if _authorize_production(args.deck_id, args.project_root) is None:
        return 1

    slide_dir = Path(args.slides)
    svg_files = sorted(slide_dir.glob("slide*.svg"))
    if not svg_files:
        print(f"No slide*.svg files found in {slide_dir}", file=sys.stderr)
        return 1

    mode = _resolve_mode(args.mode)

    if mode == "embed":
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from to_pptx import pack_slides
        pack_slides(svg_files, Path(args.out))
        print(f"\n{len(svg_files)} slide(s) → {args.out} (embed mode)")
    else:
        convert_file(args.slides, args.out, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
