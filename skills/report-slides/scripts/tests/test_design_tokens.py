"""Tests for the design-token contract and its loader."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from design_tokens import DesignTokens, TokenError, semantic_errors

_SKILL_DIR = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _SKILL_DIR / "references" / "design-tokens.schema.json"
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"


def test_schema_file_exists_and_is_valid_json_schema() -> None:
    """The token schema must exist and be a usable Draft 2020-12 schema."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


def test_default_tokens_validate_against_schema() -> None:
    """The shipped default token file must satisfy the schema."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    tokens = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(tokens)


@pytest.mark.parametrize(
    "role,minimum",
    [
        ("slide_title", 30),
        ("takeaway", 24),
        ("body", 20),
        ("node_label", 18),
        ("axis", 16),
        ("caption", 16),
        ("footnote", 12),
    ],
)
def test_default_typography_meets_presentation_floors(role: str, minimum: int) -> None:
    """Default type roles must not fall below the presentation-scale floors."""
    tokens = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    assert tokens["typography"]["roles"][role]["size"] >= minimum


def test_schema_rejects_typography_below_floor() -> None:
    """A token file setting body text to document scale must fail validation."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    tokens = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    tokens["typography"]["roles"]["body"]["size"] = 10
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(tokens)


def test_loader_reads_default_tokens() -> None:
    """The loader returns typed roles and colours from the default file."""
    tokens = DesignTokens.load(_DEFAULT_TOKENS)
    assert tokens.type_role("slide_title").size == 32
    assert tokens.type_role("slide_title").weight == 700
    assert tokens.color("primary") == "#1e3a5f"
    assert tokens.is_decorative("divider") is True
    assert tokens.is_decorative("line") is False
    assert tokens.surface("node")["radius"] == 8
    assert "Inter" in tokens.font_stack("sans")


def test_loader_digest_is_content_sensitive_not_whitespace_sensitive(
    tmp_path: Path,
) -> None:
    """The digest tracks token content, ignoring trailing whitespace."""
    original = _DEFAULT_TOKENS.read_text(encoding="utf-8")
    same = tmp_path / "same.tokens.yaml"
    same.write_text(original + "\n\n", encoding="utf-8")
    changed = tmp_path / "changed.tokens.yaml"
    changed.write_text(original.replace("size: 32", "size: 34"), encoding="utf-8")

    baseline = DesignTokens.load(_DEFAULT_TOKENS).digest
    assert DesignTokens.load(same).digest == baseline
    assert DesignTokens.load(changed).digest != baseline


def test_the_shipped_default_is_semantically_coherent() -> None:
    """The token file this plan ships passes its own cross-field checks."""
    assert semantic_errors(
        yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))) == []


def test_an_inverted_occupancy_range_is_reported() -> None:
    """A range no slide can satisfy is schema-valid and unusable.

    Both bounds are numbers in [0, 1], so JSON Schema is content. Nothing else
    in the pipeline compares them, so the failure would surface as every slide
    reporting both `underfilled` and `overfilled` at once.
    """
    data = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    data["density"]["occupancy_min"] = 0.9
    errors = semantic_errors(data)
    assert any("occupancy_min" in error for error in errors)


def test_a_surface_naming_an_unknown_colour_role_is_reported() -> None:
    """`fill: cardd` is a string, and a string is all the schema requires."""
    data = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    data["surfaces"]["node"]["fill"] = "cardd"
    errors = semantic_errors(data)
    assert any("surfaces.node.fill" in error for error in errors)


def test_a_type_role_naming_an_unknown_family_is_reported() -> None:
    """A role pointing at a font family that does not exist is caught early."""
    data = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    data["typography"]["roles"]["body"]["family"] = "serif"
    errors = semantic_errors(data)
    assert any("typography.roles.body.family" in error for error in errors)


def test_an_unordered_spacing_scale_is_reported() -> None:
    """A spacing scale is an ordered vocabulary, not a bag of numbers."""
    data = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    data["spacing"]["scale"] = [8, 4, 12]
    errors = semantic_errors(data)
    assert any("spacing.scale" in error for error in errors)


def test_loader_raises_on_schema_violation(tmp_path: Path) -> None:
    """An invalid token file raises TokenError instead of falling back."""
    bad = tmp_path / "bad.tokens.yaml"
    bad.write_text(
        _DEFAULT_TOKENS.read_text(encoding="utf-8").replace("size: 21", "size: 9"),
        encoding="utf-8",
    )
    with pytest.raises(TokenError) as excinfo:
        DesignTokens.load(bad)
    assert "typography" in str(excinfo.value)


def test_loader_raises_on_missing_file(tmp_path: Path) -> None:
    """A missing token file raises TokenError, never a silent default."""
    with pytest.raises(TokenError):
        DesignTokens.load(tmp_path / "does-not-exist.yaml")


def test_unknown_role_raises() -> None:
    """Requesting an undefined type role or colour raises TokenError."""
    tokens = DesignTokens.load(_DEFAULT_TOKENS)
    with pytest.raises(TokenError):
        tokens.type_role("subtitle")
    with pytest.raises(TokenError):
        tokens.color("accent")
