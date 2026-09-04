"""Tests that the native SVG route documents its token obligations."""
from __future__ import annotations

from pathlib import Path

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[2]
_AGENTS = _SKILL_DIR / "agents"
_REFERENCES = _SKILL_DIR / "references"

_NATIVE_ROUTE_AGENTS = (
    "architecture_diagram_worker_agent.md",
    "annotation_worker_agent.md",
    "data_visualization_worker_agent.md",
    "conceptual_illustration_worker_agent.md",
)


@pytest.mark.parametrize("agent_file", _NATIVE_ROUTE_AGENTS)
def test_worker_agents_reference_the_token_contract(agent_file: str) -> None:
    """Every module worker is told to resolve style_tokens_ref."""
    text = (_AGENTS / agent_file).read_text(encoding="utf-8")
    assert "style_tokens_ref" in text, (
        f"{agent_file} does not tell the worker to resolve its design tokens"
    )
    assert "design-tokens" in text or "tokens.yaml" in text


@pytest.mark.parametrize("agent_file", _NATIVE_ROUTE_AGENTS)
def test_worker_agents_require_the_linter_markers(agent_file: str) -> None:
    """Hand-authored SVG must declare what the linter needs to read.

    These workers are the primary producers of the markup plan 2's node,
    connector, and clearance rules exist for. An element with no
    `data-style-role` or `data-node-id` is skipped by those rules, not flagged,
    so a diagram that omits them passes by never being examined -- which is
    strictly worse than having no linter, because the report says "clean".
    """
    text = (_AGENTS / agent_file).read_text(encoding="utf-8")
    for marker in ("data-style-role", "data-node-id", "data-bleed"):
        assert marker in text, f"{agent_file} does not require {marker}"


def test_the_diagram_worker_requires_declared_connector_endpoints() -> None:
    """A connector without declared endpoints cannot be checked for drift."""
    text = (_AGENTS / "architecture_diagram_worker_agent.md").read_text(
        encoding="utf-8")
    assert "data-from" in text
    assert "data-to" in text
    assert "marker-end" in text


def test_diagram_patterns_requires_token_driven_geometry() -> None:
    """diagram-patterns.md names the token surfaces and roles."""
    text = (_REFERENCES / "diagram-patterns.md").read_text(encoding="utf-8")
    for expected in ("style_tokens_ref", "node_label", "node_gap_min",
                     "surfaces", "connectors"):
        assert expected in text, f"diagram-patterns.md omits {expected}"


def test_styles_md_defers_to_the_token_contract() -> None:
    """STYLES.md states that tokens, not frontmatter, are the machine contract."""
    text = (_REFERENCES / "styles" / "STYLES.md").read_text(encoding="utf-8")
    assert "design-tokens.schema.json" in text
    assert "documentation" in text.lower()


def test_styles_md_no_longer_prescribes_the_old_skeleton() -> None:
    """The 20pt centred title and top accent bar are gone from the guidance."""
    text = (_REFERENCES / "styles" / "STYLES.md").read_text(encoding="utf-8")
    assert 'font-size="20"' not in text
    assert "top_bar_h" not in text


def test_skill_md_documents_the_tokens_flag() -> None:
    """SKILL.md tells the operator how to select a token file."""
    text = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "--tokens" in text
    assert "validate_design_tokens.py" in text
