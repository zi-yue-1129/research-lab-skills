#!/usr/bin/env python3
"""Deterministic visual-style gate for authored slide SVG.

Runs every rule module against a slide's design tokens and reports findings as
JSON. Exit code 0 means the gate passed; 1 means it did not.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Sequence, Tuple

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens, TokenError
from fonts import FontError, resolve_font_stack
from visual_style import color, connectors, density, geometry, typography
from visual_style.report import Finding, LintReport
from visual_style.scene import parse_scene

RULE_MODULES: Tuple[ModuleType, ...] = (
    geometry, typography, color, connectors, density,
)


def lint_svg(svg_path: Path, tokens: DesignTokens,
             font_family: str) -> LintReport:
    """Run every rule module against one slide.

    Args:
        svg_path: Path to the authored SVG.
        tokens: The resolved token set.
        font_family: An installed family used for text measurement.

    Returns:
        The report for this slide. A read or parse failure becomes an
        `unreadable-input` error rather than an exception, so one bad file does
        not hide findings in the others.
    """
    report = LintReport()
    try:
        scene = parse_scene(svg_path, font_family)
    except (OSError, ValueError) as exc:
        report.add(Finding(
            rule="unreadable-input", severity="error",
            message=f"cannot lint {svg_path}: {exc}",
            element_id=str(svg_path)))
        return report
    for module in RULE_MODULES:
        report.extend(module.check(scene, tokens))
    return report


def lint_paths(paths: Sequence[Path], tokens_path: Path,
               warnings_as_errors: bool = False) -> Dict[str, Any]:
    """Lint every given slide against one token file.

    Args:
        paths: The SVG files to lint.
        tokens_path: Path to the design-token file.
        warnings_as_errors: When true, warnings also fail the gate.

    Returns:
        A JSON-serialisable result envelope.

    Raises:
        TokenError: If the token file is missing or invalid.
        FontError: If no family in the token font stack is installed.
    """
    tokens = DesignTokens.load(tokens_path)
    font_family = resolve_font_stack(tokens.font_stack("sans"))

    files: List[Dict[str, Any]] = []
    error_count = 0
    warning_count = 0
    for path in paths:
        report = lint_svg(Path(path), tokens, font_family)
        payload = report.to_dict()
        payload["path"] = str(path)
        files.append(payload)
        error_count += payload["error_count"]
        warning_count += payload["warning_count"]

    failing = error_count > 0 or (warnings_as_errors and warning_count > 0)
    return {
        "valid": not failing,
        "tokens": str(tokens_path),
        "tokens_digest": tokens.digest,
        "font_family": font_family,
        "error_count": error_count,
        "warning_count": warning_count,
        "warnings_as_errors": warnings_as_errors,
        "files": files,
    }


def _render_text(result: Dict[str, Any]) -> str:
    """Render a result envelope for a terminal reader.

    Args:
        result: The envelope from `lint_paths`.

    Returns:
        A multi-line report.
    """
    lines: List[str] = []
    for entry in result["files"]:
        lines.append(entry["path"])
        if not entry["findings"]:
            lines.append("  clean")
        for finding in entry["findings"]:
            location = finding["location"]
            where = f" at ({location[0]:g}, {location[1]:g})" if location else ""
            lines.append(
                f"  [{finding['severity']}] {finding['rule']}: "
                f"{finding['message']}{where}")
    lines.append(
        f"{result['error_count']} error(s), {result['warning_count']} warning(s)")
    return "\n".join(lines)


def _emit(text: str) -> None:
    """Write one report to stdout.

    Args:
        text: The rendered report.
    """
    sys.stdout.write(text + "\n")


def main() -> None:
    """Run the visual-style gate over one or more slides."""
    parser = argparse.ArgumentParser(
        description="Lint authored slide SVG against its design tokens.")
    parser.add_argument("--svg", metavar="PATH", type=Path, nargs="+",
                        required=True)
    parser.add_argument("--tokens", metavar="PATH", type=Path,
                        default=DEFAULT_TOKENS_PATH)
    parser.add_argument("--warnings-as-errors", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = lint_paths(args.svg, args.tokens, args.warnings_as_errors)
    except (TokenError, FontError) as exc:
        payload = {"valid": False, "error_count": 1, "warning_count": 0,
                   "files": [], "error": str(exc)}
        _emit(json.dumps(payload) if args.json
              else json.dumps(payload, indent=2))
        sys.exit(1)

    if args.json:
        _emit(json.dumps(result))
    else:
        _emit(_render_text(result))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
