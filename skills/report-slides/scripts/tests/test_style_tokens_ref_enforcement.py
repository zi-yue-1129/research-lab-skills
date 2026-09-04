"""Tests that ModuleSpec style_tokens_ref is mandatory and resolvable."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from design_tokens import DesignTokens, TokenError
from validate_visual_module import (
    resolved_token_digest,
    validate_module_spec,
    validate_style_tokens_resolvable,
)

_SKILL_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"


def _module(style_tokens_ref: object) -> dict:
    """Build a minimal ModuleSpec carrying the given style_tokens_ref.

    Args:
        style_tokens_ref: The value to place in the spec's style_tokens_ref.

    Returns:
        A ModuleSpec mapping valid in every field except the one under test.
    """
    return {
        "module_id": "m1",
        "module_type": "architecture",
        "purpose": "test",
        "authoring_route": "native",
        "editability": "native",
        "style_tokens_ref": style_tokens_ref,
        "annotation_requirements": [],
        "dimensions": {"width": 1200, "height": 675},
        "input_anchors": [],
        "output_anchors": [],
        "dependencies": [],
        "reuse_of": None,
    }


def test_null_style_tokens_ref_is_rejected() -> None:
    """A null style_tokens_ref is no longer an accepted value."""
    errors = validate_module_spec(_module(None), 0)
    assert any("style_tokens_ref" in error for error in errors)


def test_empty_style_tokens_ref_is_rejected() -> None:
    """An empty or whitespace-only reference is rejected."""
    errors = validate_module_spec(_module("   "), 0)
    assert any("style_tokens_ref" in error for error in errors)


def test_valid_reference_passes_syntactic_check() -> None:
    """A non-empty string reference passes the syntactic check."""
    errors = validate_module_spec(_module("tokens/default.tokens.yaml"), 0)
    assert not any("style_tokens_ref" in error for error in errors)


def test_resolvable_check_accepts_present_token_file(tmp_path: Path) -> None:
    """A reference resolving to a valid token file yields no errors."""
    shutil.copy(_DEFAULT_TOKENS, tmp_path / "deck.tokens.yaml")
    doc = {"modules": [_module("deck.tokens.yaml")]}
    assert validate_style_tokens_resolvable(doc, tmp_path) == []


def test_resolvable_check_rejects_missing_token_file(tmp_path: Path) -> None:
    """A reference pointing at nothing is a hard error, not a fallback."""
    doc = {"modules": [_module("absent.tokens.yaml")]}
    errors = validate_style_tokens_resolvable(doc, tmp_path)
    assert len(errors) == 1
    assert "absent.tokens.yaml" in errors[0]


def test_resolvable_check_rejects_invalid_token_file(tmp_path: Path) -> None:
    """A reference to a schema-invalid token file is a hard error."""
    bad = tmp_path / "deck.tokens.yaml"
    bad.write_text(
        _DEFAULT_TOKENS.read_text(encoding="utf-8").replace("size: 21", "size: 9"),
        encoding="utf-8",
    )
    doc = {"modules": [_module("deck.tokens.yaml")]}
    errors = validate_style_tokens_resolvable(doc, tmp_path)
    assert len(errors) == 1
    assert "typography" in errors[0]


def test_resolvable_check_rejects_escape_from_base_dir(tmp_path: Path) -> None:
    """A reference must not escape the document's directory."""
    doc = {"modules": [_module("../outside.tokens.yaml")]}
    errors = validate_style_tokens_resolvable(doc, tmp_path)
    assert len(errors) == 1
    assert "outside" in errors[0]


def test_resolved_token_digest_names_the_token_set(tmp_path: Path) -> None:
    """The digest identifies which token set a module is held to.

    A record saying only "resolved" asserts that some file was fine at some
    past moment; it cannot answer whether the tokens changed afterwards, and
    that is precisely what a stale-evidence check has to ask.
    """
    shutil.copy(_DEFAULT_TOKENS, tmp_path / "deck.tokens.yaml")
    digest = resolved_token_digest(_module("deck.tokens.yaml"), tmp_path)
    assert digest == DesignTokens.load(_DEFAULT_TOKENS).digest


def test_resolved_token_digest_refuses_to_guess(tmp_path: Path) -> None:
    """An unresolvable reference raises rather than yielding a default digest.

    A module recorded against the wrong token set is worse than one recorded
    against none, because the record then asserts something false.
    """
    with pytest.raises(TokenError):
        resolved_token_digest(_module("absent.tokens.yaml"), tmp_path)
