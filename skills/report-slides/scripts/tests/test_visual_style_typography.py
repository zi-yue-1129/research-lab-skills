"""Tests for the typography rules."""

from __future__ import annotations

from typing import Optional

import pytest

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from fonts import vertical_metrics
from visual_style import typography
from visual_style.scene import Scene, TextRun


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _text(element_id: str, size: float, role: Optional[str] = "body",
          lines: int = 1, content: str = "Label") -> TextRun:
    """Build a pre-measured text run for rule testing."""
    ascent, descent = vertical_metrics("DejaVu Sans", size)
    return TextRun(element_id, content, 100, 200, size, 400, "#374151",
                   "start", role, None, lines, 120.0,
                   ascent, descent, size * 1.45 * (lines - 1))


def _scene(texts) -> Scene:
    """Build a text-only scene."""
    return Scene(1200, 675, (), tuple(texts), (), (), "DejaVu Sans")


def test_text_at_its_role_size_is_clean(tokens: DesignTokens) -> None:
    """Body is 21 by default; 21 passes."""
    assert typography.check_type_floor(_scene([_text("t1", 21)]), tokens) == []


def test_text_below_its_role_size_is_an_error(tokens: DesignTokens) -> None:
    """The 10pt body text the spec documents is caught."""
    findings = typography.check_type_floor(_scene([_text("t1", 10)]), tokens)
    assert [f.rule for f in findings] == ["type-floor"]
    assert findings[0].severity == "error"
    assert "10" in findings[0].message
    assert "21" in findings[0].message


def test_text_above_its_role_size_is_not_a_floor_violation(
    tokens: DesignTokens,
) -> None:
    """The rule is a floor, not an equality check."""
    assert typography.check_type_floor(_scene([_text("t1", 26)]), tokens) == []


def test_undeclared_role_falls_back_to_the_smallest_role(
    tokens: DesignTokens,
) -> None:
    """Without a role, footnote's 12 is the floor."""
    scene = _scene([_text("t1", 10, role=None), _text("t2", 12, role=None)])
    findings = typography.check_type_floor(scene, tokens)
    assert [f.element_id for f in findings] == ["t1"]
    assert "no declared style role" in findings[0].message


def test_unknown_role_is_an_error(tokens: DesignTokens) -> None:
    """A role absent from the token file is a contract mismatch."""
    findings = typography.check_type_floor(
        _scene([_text("t1", 21, role="node.headline")]), tokens)
    assert [f.rule for f in findings] == ["type-floor"]
    assert "node.headline" in findings[0].message


def test_dotted_roles_resolve_to_their_typography_role(
    tokens: DesignTokens,
) -> None:
    """`node.label` resolves to the `node_label` typography role."""
    findings = typography.check_type_floor(
        _scene([_text("t1", 14, role="node.label")]), tokens)
    assert [f.rule for f in findings] == ["type-floor"]
    assert "18" in findings[0].message


def test_size_count_within_budget_is_clean(tokens: DesignTokens) -> None:
    """Default max_sizes_per_slide is 4."""
    scene = _scene([_text(f"t{i}", size)
                    for i, size in enumerate([32, 21, 18, 16])])
    assert typography.check_type_variety(scene, tokens) == []


def test_too_many_distinct_sizes_is_a_warning(tokens: DesignTokens) -> None:
    """A fifth distinct size warns."""
    scene = _scene([_text(f"t{i}", size)
                    for i, size in enumerate([32, 26, 21, 18, 16])])
    findings = typography.check_type_variety(scene, tokens)
    assert [f.rule for f in findings] == ["type-variety"]
    assert findings[0].severity == "warning"
    assert "5" in findings[0].message


def test_title_over_its_line_budget_is_a_warning(tokens: DesignTokens) -> None:
    """slide_title allows 2 lines by default."""
    scene = _scene([_text("t1", 32, role="slide_title", lines=3)])
    findings = typography.check_overlong_text(scene, tokens)
    assert [f.rule for f in findings] == ["overlong-text"]
    assert "3 lines" in findings[0].message


def test_node_label_over_its_line_budget_is_a_warning(
    tokens: DesignTokens,
) -> None:
    """node_label allows 3 lines by default."""
    scene = _scene([_text("t1", 18, role="node_label", lines=4)])
    findings = typography.check_overlong_text(scene, tokens)
    assert [f.rule for f in findings] == ["overlong-text"]


def test_body_over_the_word_budget_is_a_warning(tokens: DesignTokens) -> None:
    """Body prose beyond BODY_WORD_BUDGET words warns."""
    prose = " ".join(["word"] * (typography.BODY_WORD_BUDGET + 1))
    scene = _scene([_text("t1", 21, role="body", lines=8, content=prose)])
    findings = typography.check_overlong_text(scene, tokens)
    assert [f.rule for f in findings] == ["overlong-text"]
    assert str(typography.BODY_WORD_BUDGET) in findings[0].message


def test_body_within_the_word_budget_is_clean(tokens: DesignTokens) -> None:
    """A body run at the budget passes."""
    prose = " ".join(["word"] * typography.BODY_WORD_BUDGET)
    scene = _scene([_text("t1", 21, role="body", lines=8, content=prose)])
    assert typography.check_overlong_text(scene, tokens) == []


def test_check_runs_every_typography_rule(tokens: DesignTokens) -> None:
    """The module entry point aggregates all three rules."""
    scene = _scene([_text("t1", 10), _text("t2", 26), _text("t3", 18),
                    _text("t4", 16), _text("t5", 32)])
    rules = {f.rule for f in typography.check(scene, tokens)}
    assert rules == {"type-floor", "type-variety"}
    assert set(typography.RULES) == {
        "type-floor", "type-variety", "overlong-text",
    }
