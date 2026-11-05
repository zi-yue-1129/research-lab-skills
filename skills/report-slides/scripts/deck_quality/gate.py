"""Run the checks, apply explicit exceptions, and decide pass or fail."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pptx import Presentation

from .config import Config, Exception_, load_exceptions, load_preset
from .fix import apply_font_pairing
from .rules import Finding, check_output_name, run_checks


class DeckQualityError(RuntimeError):
    """Raised by ``enforce`` when unwaived findings remain."""

    def __init__(self, report: "Report"):
        super().__init__(report.text())
        self.report = report


@dataclass
class Report:
    deck: str
    preset: str
    findings: list[Finding] = field(default_factory=list)
    waived: list[tuple[Finding, Exception_]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict:
        return {
            "deck": self.deck,
            "preset": self.preset,
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
            "waived": [{**f.to_dict(), "reason": e.reason} for f, e in self.waived],
        }

    def text(self) -> str:
        lines = [f"deck-quality ({self.preset}): {self.deck}"]
        lines += [f"  {f}" for f in self.findings]
        lines += [f"  waived {f} — {e.reason}" for f, e in self.waived]
        verdict = "PASS" if self.passed else "FAIL"
        lines.append(f"{verdict}: {len(self.findings)} finding(s), "
                     f"{len(self.waived)} waived by listed exceptions")
        return "\n".join(lines)


def apply_exceptions(findings: list[Finding], exceptions: list[Exception_]):
    """Split findings into (open, waived); report unused exceptions as EX."""
    open_, waived = [], []
    for f in findings:
        match = next((e for e in exceptions if e.covers(f)), None)
        if match is None:
            open_.append(f)
        else:
            match.used += 1
            waived.append((f, match))
    for e in exceptions:
        if not e.used:
            open_.append(Finding("EX", e.slide, f"exception {e.describe()} matches no "
                                 "finding; remove it", e.describe()))
    return open_, waived


def check_deck(path: str | Path, cfg: Config | None = None,
               exceptions: list[Exception_] | None = None,
               check_name: bool = False, check_siblings: bool = True) -> Report:
    """Check a saved ``.pptx`` and return the report (does not raise)."""
    cfg = cfg or Config()
    path = Path(path)
    prs = Presentation(str(path))
    findings = run_checks(prs, cfg)
    if check_name:
        findings += check_output_name(path, siblings=check_siblings)
    open_, waived = apply_exceptions(findings, list(exceptions or []))
    return Report(deck=str(path), preset=cfg.name, findings=open_, waived=waived)


def enforce(path: str | Path, preset: str | Path | None = None,
            exceptions: str | Path | None = None, fix_fonts: bool = True,
            check_name: bool = False, check_siblings: bool = True) -> Report:
    """The end-of-generation gate for deck scripts.

    With a preset that sets a font pairing and ``fix_fonts``, the pairing is
    applied to the saved file first. Raises ``DeckQualityError`` if any
    finding is not covered by an exception in ``exceptions``.
    """
    cfg = load_preset(preset)
    if fix_fonts and cfg.has_font_pairing:
        prs = Presentation(str(path))
        apply_font_pairing(prs, cfg)
        prs.save(str(path))
    report = check_deck(path, cfg, load_exceptions(exceptions), check_name=check_name,
                        check_siblings=check_siblings)
    if not report.passed:
        raise DeckQualityError(report)
    return report


def gate_cli_output(out: Path, preset, exceptions, as_json: bool = False,
                    check_name: bool = False, check_siblings: bool = True) -> int:
    """Shared by the deck generators: run ``enforce`` on a freshly saved deck.

    On failure the deck is renamed ``<name>.rejected.pptx`` so a failed build
    is never mistaken for a deliverable. Returns the process exit code.
    """
    try:
        report = enforce(out, preset, exceptions, check_name=check_name,
                         check_siblings=check_siblings)
        code = 0
    except DeckQualityError as exc:
        report = exc.report
        rejected = out.with_name(out.stem + ".rejected.pptx")
        out.replace(rejected)
        report.deck = str(rejected)
        code = 1
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if as_json
          else report.text())
    return code


# ── generator CLI wiring ──────────────────────────────────────────────────

def _preset_arg(value: str) -> str:
    import argparse

    try:
        load_preset(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return value


def _exceptions_arg(value: str) -> Path:
    import argparse

    try:
        load_exceptions(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return Path(value)


def add_gate_arguments(ap) -> None:
    """Add the quality-gate options to a deck generator's argument parser.

    The preset and exceptions file are validated while parsing, so a typo
    stops the generator before it writes anything.
    """
    ap.add_argument("--quality-preset", type=_preset_arg, default=None,
                    help="deck-quality preset (e.g. zh-kai-times) or path; "
                         "default: the core rules with no font pairing")
    ap.add_argument("--quality-exceptions", type=_exceptions_arg, default=None,
                    help="YAML of findings to allow, each with a reason; any other "
                         "finding fails the build")
    ap.add_argument("--timestamp", action="store_true",
                    help="write <stem>-YYYYMMDDTHHMMSS.pptx beside --out, delete "
                         "older timestamped copies once it passes, and check G1")


def resolve_output(out: str | Path, timestamp: bool) -> Path:
    """The path a generator should save to, honouring ``--timestamp``."""
    from .fix import timestamped_output

    out = Path(out)
    return timestamped_output(out.parent, out.stem) if timestamp else out


def finish_build(out: Path, args) -> int:
    """Run the gate on a saved deck. With ``--timestamp``, older copies are
    deleted only once the new one passes. Returns the generator's exit code."""
    from .fix import prune_older

    code = gate_cli_output(out, args.quality_preset, args.quality_exceptions,
                           check_name=args.timestamp, check_siblings=False)
    if code == 0 and args.timestamp:
        for old in prune_older(out):
            print(f"removed older copy {old.name}")
    return code
