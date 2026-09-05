"""Tests for the visual-style linter CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from design_tokens import DEFAULT_TOKENS_PATH
from validate_visual_style import RULE_MODULES, lint_paths

_SKILL_DIR = Path(__file__).resolve().parents[2]
_SCRIPTS = _SKILL_DIR / "scripts"
_CLI = _SCRIPTS / "validate_visual_style.py"
_CLEAN_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#ffffff"/>
  <g data-pptx-role="group" data-node-id="n1">
    <rect x="120" y="200" width="320" height="160" rx="8" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <text x="160" y="290" font-size="18" font-weight="600" fill="#374151"
          data-style-role="node_label">Encoder</text>
  </g>
  <g data-pptx-role="group" data-node-id="n2">
    <rect x="640" y="200" width="320" height="160" rx="8" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <text x="680" y="290" font-size="18" font-weight="600" fill="#374151"
          data-style-role="node_label">Decoder</text>
  </g>
  <line x1="440" y1="280" x2="640" y2="280" stroke="#475569" stroke-width="2"
        marker-end="url(#arrow)" data-from="n1" data-to="n2"/>
</svg>"""
_DIRTY_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
  <rect width="1200" height="675" fill="#ffffff"/>
  <g data-pptx-role="group" data-node-id="n1">
    <rect x="120" y="200" width="320" height="160" rx="8" fill="#f8fafc"
          stroke="#475569" stroke-width="1.5" data-style-role="node.primary"/>
    <text x="160" y="290" font-size="10" font-weight="400" fill="#374151"
          data-style-role="node_label">Encoder</text>
  </g>
</svg>"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    """Write an SVG fixture and return its path."""
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_real_generated_frame_passes_the_linter(tmp_path: Path) -> None:
    """The renderer's own output must satisfy the rules that lint it.

    Every other test in this plan lints a hand-written fixture, and every test in
    plan 1 asserts on a rendered string. Nothing joined the two, which is how a
    footer baseline placed exactly on the safe-area boundary shipped: plan 1
    thought it was inside, plan 2's `safe-area` rule would have reported it on
    every slide in the deck, and no test could see both.

    This is the joint. It must stay in the suite even if it looks redundant
    against the fixture tests -- it is the only one that fails when the two
    plans' models of a text box drift apart.
    """
    import generate_slides as gs

    gs.apply_tokens(DEFAULT_TOKENS_PATH)
    markup = gs.svg(gs.frame("Method Overview", footer="Internal draft, 2026"))
    path = tmp_path / "slide01.svg"
    path.write_text(markup, encoding="utf-8")

    result = lint_paths([path], DEFAULT_TOKENS_PATH)
    findings = result["files"][0]["findings"]
    errors = [f for f in findings if f["severity"] == "error"]
    assert errors == [], [f"{f['rule']}: {f['message']}" for f in errors]
    assert result["valid"] is True


def test_a_generated_frame_footer_sits_inside_the_safe_area(
    tmp_path: Path,
) -> None:
    """Pin the specific geometry, so a regression names itself.

    `canvas.h` 675 minus `safe_area.bottom` 36 is 639. The footnote role is size
    12, for which DejaVu Sans reports descent 3, so the baseline belongs at 636
    and the box bottom lands on 639 exactly.
    """
    import generate_slides as gs
    from visual_style.scene import parse_scene

    gs.apply_tokens(DEFAULT_TOKENS_PATH)
    path = tmp_path / "slide01.svg"
    path.write_text(
        gs.svg(gs.frame("T", footer="f")), encoding="utf-8")
    scene = parse_scene(path, gs.S["font_resolved"])
    footer = next(run for run in scene.texts if run.text == "f")
    assert footer.y == pytest.approx(636.0)
    assert footer.bbox().bottom == pytest.approx(639.0)


def test_rule_modules_cover_every_declared_rule() -> None:
    """The CLI wires in every rule the modules declare."""
    rules = {rule for module in RULE_MODULES for rule in module.RULES}
    assert len(rules) == 22
    assert "type-floor" in rules
    assert "hand-drawn-arrow" in rules


def test_a_clean_slide_reports_valid(tmp_path: Path) -> None:
    """A token-conformant slide passes with no errors."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    result = lint_paths([svg], DEFAULT_TOKENS_PATH)
    assert result["valid"] is True, result["files"][0]["findings"]


def test_undersized_label_fails(tmp_path: Path) -> None:
    """The 10pt label the spec documents is caught as an error."""
    svg = _write(tmp_path, "dirty.svg", _DIRTY_SVG)
    result = lint_paths([svg], DEFAULT_TOKENS_PATH)
    assert result["valid"] is False
    rules = {f["rule"] for f in result["files"][0]["findings"]}
    assert "type-floor" in rules


def test_warnings_do_not_fail_by_default(tmp_path: Path) -> None:
    """Warnings are reported without failing the gate."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    result = lint_paths([svg], DEFAULT_TOKENS_PATH)
    assert result["warning_count"] >= 1
    assert result["valid"] is True


def test_warnings_as_errors_fails(tmp_path: Path) -> None:
    """The strict flag promotes warnings into gate failures."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    result = lint_paths([svg], DEFAULT_TOKENS_PATH, warnings_as_errors=True)
    assert result["valid"] is False


def test_unreadable_file_is_a_finding_not_a_traceback(tmp_path: Path) -> None:
    """A missing SVG is reported inside the result envelope."""
    result = lint_paths([tmp_path / "absent.svg"], DEFAULT_TOKENS_PATH)
    assert result["valid"] is False
    assert result["files"][0]["findings"][0]["rule"] == "unreadable-input"


def test_cli_exits_zero_on_a_clean_slide(tmp_path: Path) -> None:
    """Exit code 0 means the gate passed."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--svg", str(svg), "--json"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["valid"] is True


def test_cli_exits_one_on_findings(tmp_path: Path) -> None:
    """Exit code 1 means the gate failed."""
    svg = _write(tmp_path, "dirty.svg", _DIRTY_SVG)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--svg", str(svg), "--json"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["error_count"] >= 1


def test_cli_rejects_an_invalid_token_file(tmp_path: Path) -> None:
    """A bad --tokens path fails loudly rather than falling back."""
    svg = _write(tmp_path, "clean.svg", _CLEAN_SVG)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--svg", str(svg),
         "--tokens", str(tmp_path / "absent.yaml"), "--json"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1
    assert "token" in proc.stdout.lower() + proc.stderr.lower()


@pytest.mark.parametrize("module", RULE_MODULES, ids=lambda m: m.__name__)
def test_every_rule_module_shares_the_entry_point(module) -> None:
    """Each module exposes check() and RULES."""
    assert callable(module.check)
    assert isinstance(module.RULES, tuple)
    assert module.RULES
