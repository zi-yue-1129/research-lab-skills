"""Tests for the reviewer-role contract shared by the review stages."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple

import pytest
import yaml

import lint_evidence
import presentation_gates as gates
import presentation_state as state
from design_tokens import DesignTokens
from presentation_events import create_artifact_record
from visual_style.report import Finding, LintReport

_SKILL_DIR = Path(__file__).resolve().parents[2]
_AGENTS = _SKILL_DIR / "agents"
_DEFAULT_TOKENS = _SKILL_DIR / "references/tokens/default.tokens.yaml"

# Any digest will do for the published SVG: the gate compares the artifact
# record against the lint evidence, and never opens the file.
_SVG_SHA256 = "1" * 64


def test_render_integrity_is_an_accepted_review_role() -> None:
    """The new role is admissible wherever reviewer roles are validated."""
    assert "render_integrity" in gates._REVIEW_ROLES
    assert "visual_quality" in gates._REVIEW_ROLES


def test_render_integrity_keeps_the_rendering_finding_vocabulary() -> None:
    """The remit is unchanged; only the name and the neighbours changed."""
    assert (gates._FINDING_ROLE_KINDS["render_integrity"]
            == gates._FINDING_ROLE_KINDS["visual_quality"])
    assert "clipping" in gates._FINDING_ROLE_KINDS["render_integrity"]


def test_art_direction_is_an_accepted_review_role() -> None:
    """The new gate's role is admissible."""
    assert "art_direction" in gates._REVIEW_ROLES


def test_art_direction_owns_its_own_finding_vocabulary() -> None:
    """The art-direction kinds are not shared with the rendering gate."""
    art = gates._FINDING_ROLE_KINDS["art_direction"]
    assert "visual-cliche" in art
    assert "weak-hierarchy" in art
    assert "clipping" not in art
    assert "visual-cliche" not in gates._FINDING_ROLE_KINDS["render_integrity"]


def test_all_three_roles_are_now_required() -> None:
    """A slide is complete only when every current gate has passed.

    This replaces `test_current_role_set_completes_a_slide`, which asserted the
    opposite. The two-role set is no longer complete: the art-direction gate
    now exists, and a slide that has not passed it has not been reviewed for
    the defect class this plan exists to catch.
    """
    assert not gates.slide_reviews_complete({"scientific", "render_integrity"})
    assert gates.slide_reviews_complete(
        {"scientific", "render_integrity", "art_direction"})


def test_legacy_role_set_still_completes_a_slide() -> None:
    """Decks recorded before the split must still reach passed."""
    assert gates.slide_reviews_complete({"scientific", "visual_quality"})


def test_module_completion_accepts_both_role_sets() -> None:
    """Modules keep the two-role contract the slide gate has outgrown."""
    for roles in ({"scientific", "render_integrity"},
                  {"scientific", "visual_quality"}):
        assert gates.module_reviews_complete(roles)
    assert not gates.module_reviews_complete({"scientific"})


def test_modules_are_not_held_to_the_art_direction_gate() -> None:
    """Spec D5 scopes art direction to the complete slide, not a fragment.

    Nothing dispatches an art-direction review of a module, so adding the role
    to the module set -- or pointing the module branch of the workflow at the
    slide predicate -- would park every visual module in `in_review` forever.
    """
    assert gates.module_reviews_complete({"scientific", "render_integrity"})
    assert "art_direction" not in set().union(*gates.MODULE_REVIEW_ROLE_SETS)
    assert not gates.slide_reviews_complete({"scientific", "render_integrity"})


def test_a_partial_role_set_does_not_complete_a_slide() -> None:
    """One passing reviewer is not a complete review."""
    assert not gates.slide_reviews_complete({"scientific"})
    assert not gates.slide_reviews_complete({"render_integrity"})
    assert not gates.slide_reviews_complete(set())


def test_missing_roles_reports_the_current_set_in_order() -> None:
    """The outstanding roles are named against the current expectation."""
    assert gates.missing_slide_review_roles(
        {"scientific", "render_integrity"}) == ("art_direction",)
    assert gates.missing_slide_review_roles({"scientific"}) == (
        "render_integrity", "art_direction")
    assert gates.missing_slide_review_roles(set()) == (
        gates.SLIDE_REVIEW_ROLE_ORDER)
    assert gates.missing_slide_review_roles(
        {"scientific", "render_integrity", "art_direction"}) == ()


def test_a_legacy_slide_is_not_blocked_on_the_renamed_role() -> None:
    """Admissible is not the same as required.

    `_REVIEW_ROLES` validates what a reviewer may call itself, and three
    separate gate sites also used it as the set of reviews a subject must have.
    Once `render_integrity` joined it, every deck already recorded under
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


def test_the_art_direction_agent_doc_states_its_remit() -> None:
    """The doc must name its kinds and its boundary, or the gate is decorative."""
    text = (_AGENTS / "art_direction_reviewer_agent.md").read_text(
        encoding="utf-8")
    assert "name: art_direction_reviewer_agent" in text
    assert "reviewer_role: art_direction" in text
    assert "render_integrity_reviewer_agent" in text
    for kind in gates._ART_DIRECTION_KINDS - {"other"}:
        assert kind in text, f"missing finding kind: {kind}"


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """An empty project root, which is already a valid schema-v2 target.

    `require_schema_v2` collects the markers of the state documents that exist
    and returns without complaint when there are none, so a fresh directory
    needs no initialiser.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        The project root.
    """
    return tmp_path


def _stage_token_file(project_root: Path) -> Path:
    """Copy the shipped tokens into the project and return their path.

    Nothing in the state store records which token set a deck is held to, so
    the file a lint run reads is the contract. Staging a project-local copy is
    what lets a test edit it afterwards and observe the drift check fire.

    Args:
        project_root: Project root owning the presentation state.

    Returns:
        Path to the staged token file.
    """
    spec_dir = project_root / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    tokens_path = spec_dir / "tokens.yaml"
    shutil.copy(_DEFAULT_TOKENS, tokens_path)
    return tokens_path


def _review(role: str, status: str,
            answers: Sequence[Dict[str, str]] = ()) -> Dict[str, Any]:
    """Build one Review Result mapping for the blocker predicate.

    Args:
        role: Reviewer role string.
        status: `passed`, `failed`, or `blocked`.
        answers: Entries for `linter_warnings_answered`.

    Returns:
        The candidate review mapping.
    """
    return {
        "subject_type": "slide", "subject_id": "sl-1", "reviewer_role": role,
        "reviewer_id": f"{role}-reviewer", "status": status,
        "findings": [], "round": 1,
        "linter_warnings_answered": list(answers),
    }


def _slide_with_three_passing_reviews(
        project_root: Path, answer_warnings: bool = True) -> str:
    """Build a slide that clears every check this task did not add.

    Three passing reviews and a published SVG: what a slide looked like before
    the linter became a gate. What it lacks is a lint result, which is exactly
    what the tests below are about.

    Args:
        project_root: Project root owning the presentation state.
        answer_warnings: Whether the art-direction review answers the
            `occupancy` warning `_lint_clean_with_warnings` raises.

    Returns:
        The generated slide identifier.
    """
    deck = state.create_deck(project_root, "Gate deck")
    slide = state.create_slide(
        project_root, deck["id"], "slide-01", "A slide")
    slide_id = str(slide["id"])
    _stage_token_file(project_root)
    for status in ("ready", "assigned", "producing", "review_required"):
        state.set_slide_status(project_root, slide_id, status)
    create_artifact_record(
        project_root, deck_id=deck["id"], artifact_kind="slide-svg",
        artifact_path="slides/slide-01.svg", sha256=_SVG_SHA256,
        producer_id="slide-producer", slide_id=slide_id)
    state.record_review(project_root, "slide", slide_id,
                        "scientific-reviewer", "scientific", "passed")
    state.record_review(project_root, "slide", slide_id,
                        "render-reviewer", "render_integrity", "passed")
    answers = ([{"rule": "occupancy",
                 "answer": "a section divider is sparse on purpose"}]
               if answer_warnings else [])
    state.record_review(project_root, "slide", slide_id,
                        "art-reviewer", "art_direction", "passed",
                        linter_warnings_answered=answers)
    return slide_id


def _lint_clean_with_warnings(
        project_root: Path, slide_id: str, rules: Tuple[str, ...]) -> None:
    """Record a lint result with no errors and the named warnings.

    Args:
        project_root: Project root owning the presentation state.
        slide_id: The linted slide.
        rules: Warning rule ids the run raised.
    """
    report = LintReport()
    report.extend(
        Finding(rule=rule, severity="warning", message=rule,
                element_id=rule, location=(0.0, 0.0))
        for rule in rules
    )
    tokens_path = project_root / "specs/tokens.yaml"
    lint_evidence.record_lint_evidence(
        project_root, "slide", slide_id, _SVG_SHA256,
        DesignTokens.load(tokens_path).digest, report,
        tokens_path=str(tokens_path))


def test_a_slide_cannot_pass_without_a_current_lint_result(
        project: Path) -> None:
    """Three passing reviewers do not substitute for a measurement.

    This is the property that distinguishes a gate from a paragraph. Before it,
    `validate_visual_style.py` could have been deleted and every deck would
    still have completed.
    """
    slide_id = _slide_with_three_passing_reviews(project)
    with pytest.raises(gates.ReviewGateError) as caught:
        gates.assert_slide_passable(project, slide_id)
    assert any(str(blocker["reason"]).startswith("lint_")
               for blocker in caught.value.blockers)


def test_an_art_direction_pass_must_answer_the_warnings(project: Path) -> None:
    """`linter_warnings_answered` is checked against the warnings raised."""
    slide_id = _slide_with_three_passing_reviews(project, answer_warnings=False)
    _lint_clean_with_warnings(project, slide_id, ("occupancy",))
    with pytest.raises(gates.ReviewGateError) as caught:
        gates.assert_slide_passable(project, slide_id)
    reasons = [blocker["reason"] for blocker in caught.value.blockers]
    assert "art_direction:linter_warnings_unanswered" in reasons


def test_a_slide_with_answered_warnings_and_clean_errors_passes(
        project: Path) -> None:
    """The gate is passable. A gate nothing can satisfy is not a gate."""
    slide_id = _slide_with_three_passing_reviews(project, answer_warnings=True)
    _lint_clean_with_warnings(project, slide_id, ("occupancy",))
    passed = gates.assert_slide_passable(project, slide_id)
    assert passed["slide"]["id"] == slide_id


def test_editing_the_token_file_after_the_run_invalidates_it(
        project: Path) -> None:
    """The contract is a file on disk, so the gate checks it has not moved.

    No state record names the token set a deck is held to, which leaves the
    file the run read as the whole contract. Editing it afterwards silently
    changes what every recorded result means: the same digest now describes a
    measurement taken under rules nobody can reconstruct. The gate refuses
    rather than reporting a pass it can no longer account for.
    """
    slide_id = _slide_with_three_passing_reviews(project)
    _lint_clean_with_warnings(project, slide_id, ())
    assert gates.assert_slide_passable(project, slide_id)

    tokens_path = project / "specs/tokens.yaml"
    tokens = yaml.safe_load(tokens_path.read_text(encoding="utf-8"))
    tokens["grid"] = 16
    tokens_path.write_text(yaml.safe_dump(tokens), encoding="utf-8")
    with pytest.raises(gates.ReviewGateError) as caught:
        gates.assert_slide_passable(project, slide_id)
    reasons = [blocker["reason"] for blocker in caught.value.blockers]
    assert "lint_tokens_changed" in reasons


def test_a_slide_is_bound_to_the_bytes_it_linted(project: Path) -> None:
    """Evidence is a statement about specific bytes, not about a slide.

    The gate holds a slide to the token set its own lint run recorded, which is
    weaker than an independent declaration -- no writer produces one -- and is
    still enough to refuse evidence that predates the current SVG.
    """
    deck = state.create_deck(project, "Simple deck")
    slide = state.create_slide(project, deck["id"], "slide-01", "A slide")
    slide_id = str(slide["id"])
    for status in ("ready", "assigned", "producing", "review_required"):
        state.set_slide_status(project, slide_id, status)
    create_artifact_record(
        project, deck_id=deck["id"], artifact_kind="slide-svg",
        artifact_path="slides/slide-01.svg", sha256=_SVG_SHA256,
        producer_id="slide-producer", slide_id=slide_id)
    for reviewer, role in (("scientific-reviewer", "scientific"),
                           ("render-reviewer", "render_integrity"),
                           ("art-reviewer", "art_direction")):
        state.record_review(project, "slide", slide_id, reviewer, role,
                            "passed", linter_warnings_answered=[])
    lint_evidence.record_lint_evidence(
        project, "slide", slide_id, _SVG_SHA256, "b" * 64, LintReport())
    assert gates.assert_slide_passable(project, slide_id)["slide"]["id"] == slide_id

    # Rewrite the published bytes in place rather than adding a second record:
    # two records inside one clock second are unordered, which is a different
    # blocker with a different meaning.
    artifacts_path = project / ".research/presentations/state/artifacts.yaml"
    artifacts = yaml.safe_load(artifacts_path.read_text(encoding="utf-8"))
    for record in artifacts["artifacts"].values():
        if record.get("artifact_kind") == "slide-svg":
            record["sha256"] = "2" * 64
    artifacts_path.write_text(yaml.safe_dump(artifacts), encoding="utf-8")
    with pytest.raises(gates.ReviewGateError) as caught:
        gates.assert_slide_passable(project, slide_id)
    assert [blocker["reason"] for blocker in caught.value.blockers
            if str(blocker["reason"]).startswith("lint_")] == [
        "lint_evidence_stale"]


def test_a_new_visual_quality_review_is_refused(project: Path) -> None:
    """The legacy role is grandfathered for replay, not for new writes.

    `SLIDE_REVIEW_ROLE_SETS` still accepts `{scientific, visual_quality}` so
    decks recorded before the split can complete. Without this check, that
    concession is permanent and universal: any new deck could submit the legacy
    pair and skip both `render_integrity` and `art_direction` forever, which
    would make the entire art-direction gate optional by omission.
    """
    review = _review("visual_quality", "passed")
    fresh = gates.review_result_blockers(project, "slide", "sl-1", review, None)
    assert {"reason": "retired_reviewer_role"} in fresh
    replayed = gates.review_result_blockers(
        project, "slide", "sl-1", review, "ev-legacy-1")
    assert {"reason": "retired_reviewer_role"} not in replayed


def test_the_persisted_review_keeps_its_warning_answers(project: Path) -> None:
    """An answer the event drops is an answer the gate can never read.

    `record_review` and the workflow's own event builder both normalise a
    review into a fixed field set. If `linter_warnings_answered` is not among
    them, every art-direction review reaches the gate with no answers at all
    and no slide raising a warning can ever pass.
    """
    deck = state.create_deck(project, "Answer deck")
    slide = state.create_slide(project, deck["id"], "slide-01", "A slide")
    answers = [{"rule": "occupancy", "answer": "deliberately sparse"}]
    event = state.record_review(
        project, "slide", str(slide["id"]), "art-reviewer", "art_direction",
        "passed", linter_warnings_answered=answers)
    assert event["linter_warnings_answered"] == answers
