"""Tests that the deterministic renderer typesets at presentation scale."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import generate_slides as gs
from design_tokens import TokenError

_SKILL_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"
_FONT_SIZE_RE = re.compile(r'font-size="([0-9.]+)"')


@pytest.fixture(autouse=True)
def _tokens_applied() -> None:
    """Apply the default token file before each test."""
    gs.apply_tokens(_DEFAULT_TOKENS)


def test_apply_tokens_populates_type_roles() -> None:
    """Type roles become available with presentation-scale sizes."""
    assert gs.t_size("slide_title") == 32
    assert gs.t_size("body") == 21
    assert gs.t_size("footnote") == 12
    assert gs.t_weight("slide_title") == 700


def test_apply_tokens_resolves_an_installed_font() -> None:
    """The resolved font family is one that is actually installed."""
    assert gs.S["font_resolved"]
    assert "sans-serif" not in gs.S["font_resolved"]


def test_frame_title_is_at_presentation_scale() -> None:
    """The slide title uses the slide_title role, not a 20pt literal."""
    markup = gs.frame("Experiment Overview", footer="deck 1/8")
    sizes = {float(m) for m in _FONT_SIZE_RE.findall(markup)}
    assert 32 in sizes
    assert 20 not in sizes


def test_frame_footer_is_not_below_the_footnote_floor() -> None:
    """No text in the frame falls below the footnote floor of 12."""
    markup = gs.frame("Experiment Overview", footer="deck 1/8")
    sizes = [float(m) for m in _FONT_SIZE_RE.findall(markup)]
    assert sizes
    assert min(sizes) >= 12


def test_frame_left_variant_is_not_centred() -> None:
    """The default frame variant left-aligns the title inside the safe area."""
    markup = gs.frame("Experiment Overview")
    assert 'text-anchor="middle"' not in markup
    assert 'x="48"' in markup


def test_frame_centered_variant_is_available() -> None:
    """A centred variant remains available for section dividers."""
    markup = gs.frame("Part II", variant="centered")
    assert 'text-anchor="middle"' in markup


def test_frame_rejects_unknown_variant() -> None:
    """An unknown frame variant raises rather than silently picking a default."""
    with pytest.raises(ValueError, match="unknown frame variant"):
        gs.frame("Experiment Overview", variant="diagonal")


def test_apply_tokens_defaults_to_shipped_contract() -> None:
    """Passing None loads the shipped default token file."""
    gs.apply_tokens(None)
    assert gs.t_size("body") == 21


def test_apply_tokens_raises_on_invalid_file(tmp_path: Path) -> None:
    """An invalid token file raises instead of leaving built-in defaults."""
    bad = tmp_path / "bad.tokens.yaml"
    bad.write_text(
        _DEFAULT_TOKENS.read_text(encoding="utf-8").replace("size: 21", "size: 9"),
        encoding="utf-8",
    )
    with pytest.raises(TokenError):
        gs.apply_tokens(bad)


def test_apply_style_raises_on_unparsable_frontmatter(tmp_path: Path) -> None:
    """A style file with no usable frontmatter is an error, not a no-op."""
    broken = tmp_path / "broken.md"
    broken.write_text("no frontmatter here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable YAML frontmatter") as excinfo:
        gs.apply_style(str(broken))
    assert "broken.md" in str(excinfo.value)
