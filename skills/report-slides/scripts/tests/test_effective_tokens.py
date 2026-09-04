"""One slide, one token set, one digest.

A style Markdown file that changes a colour after the tokens are loaded creates
a second description of the same slide -- and the linter reads the first one.
These tests pin the composition order and the artifact that records the result.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import generate_slides as gs
from design_tokens import DesignTokens, TokenError

_SKILL_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"
_BUILT_IN_STYLES = _SKILL_DIR / "references" / "styles"

_NEEDS_FONTCONFIG = pytest.mark.skipif(
    shutil.which("fc-match") is None,
    # fontconfig is an optional external binary; resolving a family name has no
    # meaning without it, so this test cannot run on a box that lacks it.
    reason="fontconfig (fc-match) is not installed",
)


def _style(tmp_path: Path, body: str) -> Path:
    """Write a style Markdown file with the given frontmatter body.

    Args:
        tmp_path: Directory to write into.
        body: YAML lines to place between the frontmatter fences.

    Returns:
        Path to the written style file.
    """
    path = tmp_path / "custom.md"
    path.write_text(f"---\n{body}\n---\n\n# Custom\n", encoding="utf-8")
    return path


def test_an_override_reaches_the_token_set(tmp_path: Path) -> None:
    """The style file's primary colour becomes the token role's value."""
    style = _style(tmp_path, 'primary: "#7B2D8E"')
    path, _ = gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)
    assert DesignTokens.load(path).color("primary") == "#7B2D8E"


def test_the_effective_file_is_what_the_renderer_used(tmp_path: Path) -> None:
    """`S` and the written artifact agree, so the linter sees what was drawn.

    This is the whole point. Before this task the renderer used the override and
    the linter used the file, and `token-color` -- a hard error -- fired on
    every element painted in the deck's own accent colour.
    """
    style = _style(tmp_path, 'primary: "#7B2D8E"')
    path, _ = gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)
    gs.apply_tokens(path)
    assert gs.S["primary"] == "#7B2D8E"
    assert gs.S["accent"] == "#7B2D8E"


def test_the_digest_changes_with_the_style(tmp_path: Path) -> None:
    """A different palette is a different contract and gets a different digest."""
    _, plain = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path / "a")
    _, styled = gs.effective_tokens(
        _DEFAULT_TOKENS, str(_style(tmp_path, 'primary: "#7B2D8E"')),
        tmp_path / "b")
    assert plain != styled


def test_the_digest_is_the_written_sets_own_digest(tmp_path: Path) -> None:
    """One token set, one digest: reloading the file reproduces it.

    `DesignTokens.digest` already identifies a token set by content. Minting a
    second, byte-level digest here would give the system two answers to "which
    tokens is this slide held to", which is the defect this task removes, one
    level up.
    """
    path, digest = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path)
    assert DesignTokens.load(path).digest == digest


def test_the_same_inputs_produce_the_same_digest(tmp_path: Path) -> None:
    """Composition is deterministic; the digest identifies inputs, not runs."""
    _, first = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path / "a")
    _, second = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path / "b")
    assert first == second


def test_a_style_key_with_no_role_is_refused(tmp_path: Path) -> None:
    """A style file may set a role's value; it may not invent a role.

    The role names are the vocabulary the renderer, the worker agents, the
    linter, and the PPTX converter are all written against. Accepting an unknown
    key would put a colour in the effective token set that nothing can refer to,
    and the failure would surface much later as an unexplained hard error.
    """
    style = _style(tmp_path, 'chartreuse: "#7FFF00"')
    with pytest.raises(TokenError) as caught:
        gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)
    assert "chartreuse" in str(caught.value)


def test_a_malformed_colour_is_refused(tmp_path: Path) -> None:
    """The composed set is validated, not merely merged."""
    style = _style(tmp_path, 'primary: "not a colour"')
    with pytest.raises(TokenError):
        gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)


@_NEEDS_FONTCONFIG
def test_a_font_override_is_resolved_into_the_token_set(tmp_path: Path) -> None:
    """The font the renderer measures with is the font the linter measures with."""
    style = _style(tmp_path, 'font: "DejaVu Sans, sans-serif"')
    path, _ = gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)
    assert "DejaVu Sans" in DesignTokens.load(path).font_stack("sans")


def test_no_style_still_writes_an_effective_file(tmp_path: Path) -> None:
    """Every deck has an effective token set, so the gate has one thing to read."""
    path, digest = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path)
    assert path.is_file() and len(digest) == 64


@pytest.mark.parametrize(
    "style_name", ["default.md", "minimal.md", "dark.md", "paper.md"])
def test_every_built_in_style_composes(style_name: str, tmp_path: Path) -> None:
    """The four shipped styles must survive composition.

    Refusing a key that names no colour role is only safe if the keys the
    shipped styles actually use all name one. Two do not: `name` and
    `description` are metadata, documented in the same frontmatter table, and
    `border` has always meant the `divider` role -- `apply_tokens` set
    `S["border"]` from `color.roles.divider` long before this task. A
    role-name-per-style-key map would reject `bash set-style.sh dark` with a
    hard error, which is a worse failure than the one this task removes.
    """
    path, _ = gs.effective_tokens(
        _DEFAULT_TOKENS, str(_BUILT_IN_STYLES / style_name), tmp_path)
    assert DesignTokens.load(path).color("primary").startswith("#")
