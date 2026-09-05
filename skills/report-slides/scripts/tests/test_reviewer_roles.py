"""Tests for the reviewer-role contract shared by the review stages."""

from __future__ import annotations

from pathlib import Path

import presentation_gates as gates

_SKILL_DIR = Path(__file__).resolve().parents[2]
_AGENTS = _SKILL_DIR / "agents"


def test_render_integrity_is_an_accepted_review_role() -> None:
    """The new role is admissible wherever reviewer roles are validated."""
    assert "render_integrity" in gates._REVIEW_ROLES
    assert "visual_quality" in gates._REVIEW_ROLES


def test_render_integrity_keeps_the_rendering_finding_vocabulary() -> None:
    """The remit is unchanged; only the name and the neighbours changed."""
    assert (gates._FINDING_ROLE_KINDS["render_integrity"]
            == gates._FINDING_ROLE_KINDS["visual_quality"])
    assert "clipping" in gates._FINDING_ROLE_KINDS["render_integrity"]


def test_current_role_set_completes_a_slide() -> None:
    """Scientific plus render integrity is the new complete set."""
    assert gates.slide_reviews_complete({"scientific", "render_integrity"})


def test_legacy_role_set_still_completes_a_slide() -> None:
    """Decks recorded before the split must still reach passed."""
    assert gates.slide_reviews_complete({"scientific", "visual_quality"})


def test_module_completion_matches_slide_completion_today() -> None:
    """The two predicates agree until Task 10 deliberately parts them."""
    for roles in ({"scientific", "render_integrity"},
                  {"scientific", "visual_quality"}):
        assert gates.module_reviews_complete(roles)
    assert not gates.module_reviews_complete({"scientific"})


def test_a_partial_role_set_does_not_complete_a_slide() -> None:
    """One passing reviewer is not a complete review."""
    assert not gates.slide_reviews_complete({"scientific"})
    assert not gates.slide_reviews_complete({"render_integrity"})
    assert not gates.slide_reviews_complete(set())


def test_missing_roles_names_what_is_outstanding_in_workflow_order() -> None:
    """The caller can tell the user which review to run next."""
    assert gates.missing_slide_review_roles({"scientific"}) == (
        "render_integrity",)
    assert gates.missing_slide_review_roles(set()) == (
        gates.SLIDE_REVIEW_ROLE_ORDER)
    assert gates.missing_slide_review_roles(
        {"scientific", "render_integrity"}) == ()


def test_a_legacy_slide_is_not_blocked_on_the_renamed_role() -> None:
    """Admissible is not the same as required.

    `_REVIEW_ROLES` validates what a reviewer may call itself, and three
    separate gate sites used it as the set of reviews a subject must have. Once
    `render_integrity` joined it, every deck already recorded under
    `visual_quality` would have been blocked on a review nobody will ever run
    again. The required set is the role-set predicate, not the admissible set.
    """
    assert gates.missing_slide_review_roles(
        {"scientific", "visual_quality"}) == ()
    assert gates.missing_module_review_roles(
        {"scientific", "visual_quality"}) == ()


def test_the_renamed_agent_doc_exists_and_the_old_one_does_not() -> None:
    """The rename is complete, not additive."""
    assert (_AGENTS / "render_integrity_reviewer_agent.md").is_file()
    assert not (_AGENTS / "visual_quality_reviewer_agent.md").exists()


def test_the_renamed_agent_defers_measurable_defects_to_the_linter() -> None:
    """The doc must say what it no longer owns, or the remit will not shrink."""
    text = (_AGENTS / "render_integrity_reviewer_agent.md").read_text(
        encoding="utf-8")
    assert "name: render_integrity_reviewer_agent" in text
    assert "reviewer_role: render_integrity" in text
    assert "validate_visual_style.py" in text
    assert "art_direction_reviewer_agent" in text
