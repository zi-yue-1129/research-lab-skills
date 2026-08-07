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
