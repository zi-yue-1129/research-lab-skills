"""Lint results are evidence, not console output.

A gate that reads a shell exit code enforces nothing: the exit code is gone by
the time anything decides whether a slide may pass. These tests pin the three
properties that make the linter an actual gate -- the result is persisted, it is
bound to the exact bytes it examined, and a review cannot claim to have answered
warnings that no run produced.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

import lint_evidence as le
import presentation_events as events
import presentation_state as state
from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from visual_style.report import Finding, LintReport

_SCRIPTS = Path(__file__).resolve().parent.parent


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """An empty project root, which is already an admissible event target.

    `presentation_evidence_workflow.require_schema_v2` -- which `append_event`
    calls first -- collects the schema markers of the state documents that
    exist and returns without complaint when there are none. A fresh directory
    is therefore a valid schema-v2 project, and no initialiser call is needed.
    """
    return tmp_path


def _publish_svg(project_root: Path, sha256: str) -> str:
    """Record a slide-svg artifact so the gate has bytes to reason about.

    An artifact record is refused unless its deck and slide exist, so the
    subject is created here and its generated id returned; the evidence
    functions themselves take the id as an opaque string.

    Args:
        project_root: Project root owning the presentation state.
        sha256: Digest to publish as the slide's current SVG.

    Returns:
        The generated slide identifier the artifact was recorded against.
    """
    deck = state.create_deck(project_root, "Lint evidence deck")
    slide = state.create_slide(project_root, deck["id"], "slide-01", "A slide")
    events.create_artifact_record(
        project_root, deck_id=deck["id"], artifact_kind="slide-svg",
        artifact_path="slides/slide-01.svg", sha256=sha256,
        producer_id="test", slide_id=slide["id"])
    return str(slide["id"])


def _report(errors: int = 0, warnings: Tuple[str, ...] = ()) -> LintReport:
    """Build a report with the requested error count and warning rules."""
    report = LintReport()
    report.extend(
        Finding(rule="safe-area", severity="error", message=f"e{index}",
                element_id=f"e{index}", location=(0.0, 0.0))
        for index in range(errors)
    )
    report.extend(
        Finding(rule=rule, severity="warning", message=rule,
                element_id=rule, location=(0.0, 0.0))
        for rule in warnings
    )
    return report


def test_a_recorded_result_is_found_again_by_its_digests(project: Path) -> None:
    """The evidence is keyed by what it examined, not by when it ran."""
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report())
    found = le.current_lint_evidence(project, "slide", "sl-1", "a" * 64,
                                     "b" * 64)
    assert found is not None and found["errors"] == []
    assert found["warnings"] == []
    assert found["subject_id"] == "sl-1"


def test_a_result_for_different_bytes_is_not_current(project: Path) -> None:
    """Editing the SVG invalidates the evidence, silently or not at all."""
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report())
    assert le.current_lint_evidence(project, "slide", "sl-1", "c" * 64,
                                    "b" * 64) is None


def test_a_result_for_different_tokens_is_not_current(project: Path) -> None:
    """A token change re-opens every colour and type question on the slide."""
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report())
    assert le.current_lint_evidence(project, "slide", "sl-1", "a" * 64,
                                    "d" * 64) is None


def test_the_latest_result_for_one_digest_pair_wins(project: Path) -> None:
    """A re-run after a fix supersedes the failing result it replaces."""
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report(errors=2))
    le.record_lint_evidence(project, "slide", "sl-1", "a" * 64, "b" * 64,
                            _report())
    found = le.current_lint_evidence(project, "slide", "sl-1", "a" * 64,
                                     "b" * 64)
    assert found is not None and found["errors"] == []


def test_no_evidence_at_all_is_a_blocker(project: Path) -> None:
    """The default is refusal. A linter nobody ran must not read as a pass."""
    slide_id = _publish_svg(project, "a" * 64)
    reasons = {blocker["reason"] for blocker in
               le.lint_blockers(project, "slide", slide_id, "b" * 64)}
    assert reasons == {"lint_evidence_missing"}


def test_evidence_for_older_bytes_is_a_blocker(project: Path) -> None:
    """Stale evidence is worse than none: it looks like a pass."""
    slide_id = _publish_svg(project, "a" * 64)
    le.record_lint_evidence(project, "slide", slide_id, "0" * 64, "b" * 64,
                            _report())
    reasons = {blocker["reason"] for blocker in
               le.lint_blockers(project, "slide", slide_id, "b" * 64)}
    assert reasons == {"lint_evidence_stale"}


def test_an_unpublished_svg_is_its_own_blocker(project: Path) -> None:
    """Nothing to lint is a different problem from nothing having linted it."""
    reasons = {blocker["reason"] for blocker in
               le.lint_blockers(project, "slide", "sl-1", "b" * 64)}
    assert reasons == {"lint_artifact_missing"}


def test_a_failing_result_is_a_blocker(project: Path) -> None:
    """A hard error blocks the slide whatever the three reviewers concluded."""
    slide_id = _publish_svg(project, "a" * 64)
    le.record_lint_evidence(project, "slide", slide_id, "a" * 64, "b" * 64,
                            _report(errors=1))
    blockers = le.lint_blockers(project, "slide", slide_id, "b" * 64)
    assert [blocker["reason"] for blocker in blockers] == ["lint_failed"]
    assert blockers[0]["rules"] == ["safe-area"]


def test_a_passing_result_blocks_nothing(project: Path) -> None:
    """Warnings are for the art director to answer, not for the gate."""
    slide_id = _publish_svg(project, "a" * 64)
    le.record_lint_evidence(project, "slide", slide_id, "a" * 64, "b" * 64,
                            _report(warnings=("occupancy",)))
    assert le.lint_blockers(project, "slide", slide_id, "b" * 64) == []


def test_unanswered_warnings_are_named(project: Path) -> None:
    """The reviewer must answer the warnings this run produced."""
    evidence = le.record_lint_evidence(
        project, "slide", "sl-1", "a" * 64, "b" * 64,
        _report(warnings=("occupancy", "equal-card-repetition")))
    review: Dict[str, Any] = {
        "reviewer_role": "art_direction", "status": "passed",
        "linter_warnings_answered": [
            {"rule": "occupancy", "answer": "the slide is a section divider"},
        ],
    }
    assert le.unanswered_warnings(evidence, review) == ["equal-card-repetition"]


def test_answering_a_warning_that_was_not_raised_is_unanswered(
        project: Path) -> None:
    """Answers copied from another slide do not discharge this slide's warnings.

    Without this, `linter_warnings_answered` degrades into a field that is
    filled in because it is required, which is the failure mode the whole task
    exists to remove.
    """
    evidence = le.record_lint_evidence(
        project, "slide", "sl-1", "a" * 64, "b" * 64,
        _report(warnings=("occupancy",)))
    review: Dict[str, Any] = {
        "reviewer_role": "art_direction", "status": "passed",
        "linter_warnings_answered": [
            {"rule": "connector-crossing", "answer": "deliberate"},
        ],
    }
    assert le.unanswered_warnings(evidence, review) == ["occupancy"]


def test_an_empty_answer_does_not_count(project: Path) -> None:
    """A blank string is not an answer."""
    evidence = le.record_lint_evidence(
        project, "slide", "sl-1", "a" * 64, "b" * 64,
        _report(warnings=("occupancy",)))
    review: Dict[str, Any] = {
        "reviewer_role": "art_direction", "status": "passed",
        "linter_warnings_answered": [{"rule": "occupancy", "answer": "  "}],
    }
    assert le.unanswered_warnings(evidence, review) == ["occupancy"]


def test_a_module_is_linted_under_its_own_subject_type(project: Path) -> None:
    """Modules and slides do not share an evidence namespace."""
    le.record_lint_evidence(project, "module", "sl-1", "a" * 64, "b" * 64,
                            _report())
    assert le.current_lint_evidence(project, "slide", "sl-1", "a" * 64,
                                    "b" * 64) is None


def test_an_unknown_subject_type_is_refused(project: Path) -> None:
    """A typo must not create a namespace nothing ever reads."""
    with pytest.raises(ValueError, match="subject_type"):
        le.record_lint_evidence(project, "deck", "dk-1", "a" * 64, "b" * 64,
                                _report())


def test_the_cli_records_evidence_the_gate_accepts(
        project: Path, tmp_path: Path) -> None:
    """`--record` must write the digest the gate resolves, not the file's bytes.

    `DesignTokens.digest` is taken over canonicalised token content, while the
    token file on disk has its own byte digest. Recording the latter produces
    evidence that can never match a deck's declared token set, so every slide
    would be refused as unlinted no matter how often the linter ran.
    """
    svg = tmp_path / "slide.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" '
        'viewBox="0 0 1200 675">'
        '<rect x="0" y="0" width="1200" height="675" fill="#ffffff"/>'
        '</svg>\n', encoding="utf-8")
    slide_id = _publish_svg(
        project, hashlib.sha256(svg.read_bytes()).hexdigest())
    completed = subprocess.run(
        [sys.executable, str(_SCRIPTS / "validate_visual_style.py"),
         "--svg", str(svg), "--tokens", str(DEFAULT_TOKENS_PATH), "--json",
         "--record", str(project), "--subject-type", "slide",
         "--subject-id", slide_id],
        capture_output=True, text=True, timeout=120, check=False)
    assert completed.returncode == 0, completed.stderr

    tokens_digest = DesignTokens.load(DEFAULT_TOKENS_PATH).digest
    assert le.lint_blockers(project, "slide", slide_id, tokens_digest) == []


def test_two_publications_in_one_second_are_ambiguous(project: Path) -> None:
    """Unordered publications are refused rather than resolved by guesswork.

    The artifact store is keyed by generated id and `created_at` resolves to
    the second, so two publications inside one second carry no order. Picking
    either would let the gate judge a slide against bytes it may no longer
    have; the state itself is what needs fixing.
    """
    slide_id = _publish_svg(project, "a" * 64)
    deck_id = next(iter(state.load_decks(project)))
    events.create_artifact_record(
        project, deck_id=deck_id, artifact_kind="slide-svg",
        artifact_path="slides/slide-01.svg", sha256="c" * 64,
        producer_id="test", slide_id=slide_id)
    blockers = le.lint_blockers(project, "slide", slide_id, "b" * 64)
    assert [blocker["reason"] for blocker in blockers] == [
        "lint_artifact_ambiguous"]
    assert blockers[0]["digests"] == ["a" * 64, "c" * 64]
    assert le.current_svg_digest(project, "slide", slide_id) is None
