"""CLI: ``python3 -m deck_quality deck.pptx [--preset NAME] [--exceptions FILE]``.

Exit codes: 0 pass, 1 unwaived findings, 2 bad preset or exceptions file.
Checking never modifies the deck; pass ``--fix-fonts`` to apply the preset's
font pairing first.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from pptx import Presentation

from .config import ConfigError, available_presets, load_exceptions, load_preset
from .fix import apply_font_pairing
from .gate import check_deck


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deck_quality",
                                 description="Check a .pptx against the research deck "
                                 "quality standard")
    ap.add_argument("deck", type=Path)
    ap.add_argument("--preset", help=f"preset name ({', '.join(available_presets())}) "
                    "or path to a preset YAML; default: core rules, no font pairing")
    ap.add_argument("--exceptions", type=Path,
                    help="YAML listing waived findings, each with a reason")
    ap.add_argument("--check-name", action="store_true",
                    help="also check G1 (timestamped name, no older copies)")
    ap.add_argument("--fix-fonts", action="store_true",
                    help="apply the preset's font pairing to the deck before checking")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        cfg = load_preset(args.preset)
        exceptions = load_exceptions(args.exceptions)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.fix_fonts:
        prs = Presentation(str(args.deck))
        apply_font_pairing(prs, cfg)
        prs.save(str(args.deck))
    report = check_deck(args.deck, cfg, exceptions, check_name=args.check_name)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if args.json
          else report.text())
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
