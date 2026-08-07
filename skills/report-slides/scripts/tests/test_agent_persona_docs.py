"""Documentation contract tests for the report-slides agent persona files.

Each test asserts that one persona file names the exact stage number(s),
MUST-NOT boundary, and contract field names its role requires -- so an
agent file cannot silently drift away from the design spec's Agent Roster
and Contract tables.
"""

from pathlib import Path


_AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"


def _read(name: str) -> str:
    return (_AGENTS_DIR / name).read_text(encoding="utf-8")


def test_research_narrative_planner_agent_names_stage_and_boundary() -> None:
    text = _read("research_narrative_planner_agent.md")
    assert "name: research_narrative_planner_agent" in text
    assert "Stage 3" in text
    assert "Stage Boundary" in text
    assert "approve its own plan" in text
    for field in (
        "deck_id", "purpose", "audience", "estimated_duration_minutes", "status",
        "excluded_content", "known_gaps",
        "slide_id", "title", "key_takeaway", "evidence_refs", "intended_visual_type",
        "visual_rationale", "speaker_message", "dependencies", "open_questions",
    ):
        assert field in text, f"missing contract field: {field}"


def test_content_reviewer_agent_names_stage_and_finding_kinds() -> None:
    text = _read("content_reviewer_agent.md")
    assert "name: content_reviewer_agent" in text
    assert "Stage 4" in text
    assert "Stage Boundary" in text
    assert "approve a plan it authored" in text or "approve a plan it reviewed" in text
    for kind in (
        "unsupported-claim", "duplicated-content", "missing-limitation",
        "excessive-background", "unnecessary-visual", "weak-continuity",
    ):
        assert kind in text, f"missing finding kind: {kind}"
    assert "plan_review" in text


def test_slide_architect_agent_names_stages_and_complexity_signals() -> None:
    text = _read("slide_architect_agent.md")
    assert "name: slide_architect_agent" in text
    assert "Stage 6" in text and "Stage 7" in text
    assert "Stage Boundary" in text
    assert "change an approved takeaway" in text or "an approved evidence reference" in text
    for field in (
        "information_hierarchy", "reading_order", "layout_regions", "text_to_visual_ratio",
        "visual_emphasis", "expected_complexity", "reusable_components", "requires_complex_workflow",
        "region_count", "route_count", "multi_stage", "mixed_technique",
        "heavy_cross_region_connections", "expected_reuse", "not_atomic",
    ):
        assert field in text, f"missing contract field: {field}"


def test_complex_visual_decomposer_agent_names_stage_and_module_fields() -> None:
    text = _read("complex_visual_decomposer_agent.md")
    assert "name: complex_visual_decomposer_agent" in text
    assert "Stage 8" in text
    assert "Stage Boundary" in text
    assert "author any visual asset itself" in text
    for field in (
        "visual_id", "message", "modules", "connections", "layout",
        "route", "module_type", "input_anchors", "output_anchors",
        "dependencies", "style_tokens_ref", "editability", "reuse_of",
    ):
        assert field in text, f"missing contract field: {field}"


def test_data_visualization_worker_agent_names_stage_and_route() -> None:
    text = _read("data_visualization_worker_agent.md")
    assert "name: data_visualization_worker_agent" in text
    assert "Stage 9" in text
    assert "Stage Boundary" in text
    assert "Modify scientific content" in text or "modify scientific content" in text
    assert "data" in text and "route" in text


def test_architecture_diagram_worker_agent_names_stage_and_route() -> None:
    text = _read("architecture_diagram_worker_agent.md")
    assert "name: architecture_diagram_worker_agent" in text
    assert "Stage 9" in text
    assert "Stage Boundary" in text
    assert "modify scientific content" in text.lower()
    assert "native" in text
