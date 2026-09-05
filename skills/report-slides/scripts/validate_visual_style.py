#!/usr/bin/env python3
"""Deterministic visual-style gate for authored slide SVG.

Runs every rule module against a slide's design tokens and reports findings as
JSON. Exit code 0 means the gate passed; 1 means it did not.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Sequence, Tuple

from lxml.etree import LxmlError

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens, TokenError
from fonts import FontError, resolve_font_stack
from lint_evidence import record_lint_evidence
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
    # `XMLSyntaxError` derives from `SyntaxError`, not from `ValueError`, so a
    # malformed file used to escape this guard entirely: the run died on a
    # traceback and every later file in the same invocation went unlinted.
    except (OSError, ValueError, LxmlError) as exc:
        report.add(Finding(
            rule="unreadable-input", severity="error",
            message=f"cannot lint {svg_path}: {exc}",
            element_id=str(svg_path)))
        return report
    for module in RULE_MODULES:
        report.extend(module.check(scene, tokens))
    return report


def lint_reports(
    paths: Sequence[Path], tokens_path: Path,
    warnings_as_errors: bool = False,
) -> Tuple[Dict[str, Any], List[Tuple[Path, str, LintReport]]]:
    """Lint every given slide and return both the envelope and the reports.

    The envelope is what a reader wants; the reports are what
    `lint_evidence.record_lint_evidence` wants. Producing both from one pass
    keeps `--record` from linting every file a second time.

    Args:
        paths: The SVG files to lint.
        tokens_path: Path to the design-token file.
        warnings_as_errors: When true, warnings also fail the gate.

    Returns:
        The JSON-serialisable envelope, and one `(path, sha256, report)` triple
        per input in the order given. The digest is of the bytes the run
        actually measured: each file is hashed before and after its rules run,
        and a file that changed in between is reported as `unstable-input`
        rather than credited with a result describing bytes that are gone.

    Raises:
        TokenError: If the token file is missing or invalid.
        FontError: If no family in the token font stack is installed.
    """
    tokens = DesignTokens.load(tokens_path)
    font_family = resolve_font_stack(tokens.font_stack("sans"))

    files: List[Dict[str, Any]] = []
    reports: List[Tuple[Path, str, LintReport]] = []
    error_count = 0
    warning_count = 0
    for path in paths:
        svg_path = Path(path)
        before = _sha256_or_none(svg_path)
        report = lint_svg(svg_path, tokens, font_family)
        after = _sha256_or_none(svg_path)
        if before is not None and after is not None and before != after:
            report = LintReport()
            report.add(Finding(
                rule="unstable-input", severity="error",
                message=(f"{svg_path} changed while it was being linted; "
                         "the result would describe bytes that no longer "
                         "exist. Re-run the linter."),
                element_id=str(svg_path)))
        payload = report.to_dict()
        payload["path"] = str(path)
        files.append(payload)
        # An unreadable file has no digest to record; the empty string matches
        # no published artifact, so the gate reports it as unlinted rather than
        # crediting a result for bytes nobody could read.
        reports.append((svg_path, after or "", report))
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
    }, reports


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
    return lint_reports(paths, tokens_path, warnings_as_errors)[0]


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


def _sha256_of(path: Path) -> str:
    """Return the SHA-256 of a file's bytes.

    Args:
        path: The file to digest.

    Returns:
        The lowercase hexadecimal digest.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_or_none(path: Path) -> str | None:
    """Return a file's digest, or `None` when it cannot be read.

    A missing or unreadable input is reported as an `unreadable-input` finding
    by `lint_svg`, which is how the run stays alive for the other files. Letting
    the digest step raise first would turn that designed finding back into the
    traceback it replaced.

    Args:
        path: The file to digest.

    Returns:
        The lowercase hexadecimal digest, or `None` if the read failed.
    """
    try:
        return _sha256_of(path)
    except OSError:
        return None


def _recorded_tokens_path(tokens_path: Path, project_root: Path) -> str:
    """Return a token-file reference the gate can resolve from anywhere.

    The gate re-reads this path to check the token file has not changed under
    the recorded result, and it runs from whatever directory the caller
    happens to be in. A path relative to the caller's shell would silently
    resolve to nothing there, and "not found" would read as "no drift" -- a
    check that passes precisely when it cannot run.

    Args:
        tokens_path: The token file as given on the command line.
        project_root: The project the evidence is recorded into.

    Returns:
        The path relative to the project root when the token file lives inside
        it, and the resolved absolute path otherwise.
    """
    resolved = Path(tokens_path).resolve()
    try:
        return str(resolved.relative_to(Path(project_root).resolve()))
    except ValueError:
        # The shipped token sets live in the installed skill bundle, outside
        # any project; an absolute path is the only reference that resolves.
        return str(resolved)


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
    # Recording is opt-in because the linter is also run outside a project, on
    # a scratch file, while authoring -- but Stage 10 always passes --record.
    parser.add_argument(
        "--record", type=Path, default=None, metavar="PROJECT_ROOT",
        help="persist each result as lint evidence under this project root")
    parser.add_argument(
        "--subject-type", choices=("slide", "module"), default="slide",
        help="the subject kind the linted files belong to")
    parser.add_argument(
        "--subject-id", default=None,
        help="the generated subject id; required with --record")
    args = parser.parse_args()
    if args.record is not None and args.subject_id is None:
        parser.error("--record requires --subject-id")

    try:
        result, reports = lint_reports(
            args.svg, args.tokens, args.warnings_as_errors)
    except (TokenError, FontError) as exc:
        payload = {"valid": False, "error_count": 1, "warning_count": 0,
                   "files": [], "error": str(exc)}
        _emit(json.dumps(payload) if args.json
              else json.dumps(payload, indent=2))
        sys.exit(1)

    if args.record is not None:
        # The canonicalised token digest, not the file's bytes: the gate
        # resolves the deck's declared token set through `DesignTokens.digest`,
        # and a raw-file digest would never match it.
        tokens_digest = result["tokens_digest"]
        tokens_ref = _recorded_tokens_path(args.tokens, args.record)
        for svg_path, svg_digest, report in reports:
            record_lint_evidence(
                args.record, args.subject_type, args.subject_id,
                svg_digest, tokens_digest, report, tokens_path=tokens_ref)

    if args.json:
        _emit(json.dumps(result))
    else:
        _emit(_render_text(result))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
