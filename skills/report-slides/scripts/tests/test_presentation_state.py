"""Subprocess tests for presentation_state.py -- Deck/Slide state CLI."""
import json
import subprocess
import sys
import yaml
import pytest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "presentation_state.py"
from presentation_state import record_review


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, check=False,
    )


def test_create_deck_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-deck", "--title", "Q3 Results Deck", "--skill", "research_narrative_planner", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("deck_")
    assert data["title"] == "Q3 Results Deck"
    assert data["status"] == "planning"
    assert data["plan_version"] == 0
    assert data["created_by"] == "research_narrative_planner"


def test_create_deck_without_title_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-deck", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_set_deck_status_legal_transition(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "content_review", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "content_review"


def test_set_deck_status_illegal_transition_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    # Generic status cannot bypass the approval evidence action.
    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "approved", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ApprovalGateError"
    assert data["predicate"] == "plan_approvable"
    assert data["deck_id"] == deck["id"]
    assert data["blockers"]


def test_set_deck_status_unrecognized_status_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "not-a-real-status", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_set_deck_status_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--set-deck-status", "--deck-id", "deck_does_not_exist", "--status", "content_review", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "DeckNotFoundError"


def test_deck_can_be_blocked_from_any_active_state(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "blocked", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "blocked"


def test_deck_can_resume_from_blocked_to_prior_active_state(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "blocked", "--json")

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "content_review", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "content_review"


def test_create_slide_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01",
        "--title", "Action conditioning improves command sensitivity", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("sld_")
    assert data["deck_id"] == deck["id"]
    assert data["plan_slide_id"] == "slide-01"
    assert data["status"] == "planned"


def test_create_slide_without_title_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_slide_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-slide", "--deck-id", "deck_does_not_exist",
        "--plan-slide-id", "slide-01", "--title", "T", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "DeckNotFoundError"


def test_set_slide_status_legal_transition(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    slide = json.loads(_run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--title", "T", "--json",
    ).stdout)

    result = _run(project, "--set-slide-status", "--slide-id", slide["id"], "--status", "ready", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "ready"


def test_set_slide_status_illegal_transition_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    slide = json.loads(_run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--title", "T", "--json",
    ).stdout)

    # Generic status cannot bypass independent production reviews.
    result = _run(project, "--set-slide-status", "--slide-id", slide["id"], "--status", "passed", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ReviewGateError"
    assert data["predicate"] == "slide_passable"
    assert data["deck_id"] == deck["id"]
    assert data["blockers"]


def test_set_slide_status_unknown_slide_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--set-slide-status", "--slide-id", "sld_does_not_exist", "--status", "ready", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SlideNotFoundError"


def test_bootstraps_own_gitignore_not_shared_one(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--create-deck", "--title", "T", "--json")

    assert (project / ".research" / "presentations" / ".gitignore").is_file()
    assert not (project / ".research" / ".gitignore").exists()


def _make_deck_and_slide(project: Path) -> tuple:
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    slide = json.loads(_run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--title", "T", "--json",
    ).stdout)
    return deck["id"], slide["id"]


def test_create_visual_module_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)

    result = _run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "observation-input", "--module-type", "architecture",
        "--skill", "architecture_diagram_worker", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("mod_")
    assert data["slide_id"] == slide_id
    assert data["module_key"] == "observation-input"
    assert data["module_type"] == "architecture"
    assert data["status"] == "planned"
    assert data["dependencies"] == []


def test_create_visual_module_invalid_type_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)

    result = _run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "m1", "--module-type", "not-a-real-type", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_visual_module_unknown_slide_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-visual-module", "--slide-id", "sld_does_not_exist",
        "--module-key", "m1", "--module-type", "architecture", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SlideNotFoundError"


def test_create_visual_module_unknown_dependency_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)

    result = _run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "m1", "--module-type", "architecture",
        "--dependencies", "mod_does_not_exist", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "VisualModuleNotFoundError"


def test_module_cannot_start_producing_with_unresolved_dependency(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    upstream = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "upstream", "--module-type", "architecture", "--json",
    ).stdout)
    downstream = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "downstream", "--module-type", "architecture",
        "--dependencies", upstream["id"], "--json",
    ).stdout)
    for status in ("ready", "assigned"):
        _run(project, "--set-module-status", "--module-id", downstream["id"], "--status", status, "--json")

    result = _run(project, "--set-module-status", "--module-id", downstream["id"], "--status", "producing", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    assert "unresolved dependencies" in data["message"]


def test_module_cannot_be_marked_passed_without_review_evidence(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, slide_id = _make_deck_and_slide(project)
    upstream = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "upstream", "--module-type", "architecture", "--json",
    ).stdout)
    downstream = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "downstream", "--module-type", "architecture",
        "--dependencies", upstream["id"], "--json",
    ).stdout)
    for status in ("ready", "assigned", "producing", "review_required"):
        _run(project, "--set-module-status", "--module-id", upstream["id"], "--status", status, "--json")
    for status in ("ready", "assigned"):
        _run(project, "--set-module-status", "--module-id", downstream["id"], "--status", status, "--json")

    result = _run(project, "--set-module-status", "--module-id", upstream["id"], "--status", "passed", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ReviewGateError"
    assert data["predicate"] == "module_passable"
    assert data["deck_id"] == deck_id
    assert data["blockers"]


def test_two_independent_modules_can_both_reach_producing(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, slide_id = _make_deck_and_slide(project)
    a = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "a", "--module-type", "data_visualization", "--json",
    ).stdout)
    b = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "b", "--module-type", "conceptual", "--json",
    ).stdout)

    for module_id in (a["id"], b["id"]):
        for status in ("ready", "assigned", "producing"):
            result = _run(project, "--set-module-status", "--module-id", module_id, "--status", status, "--json")
            assert result.returncode == 0, result.stderr

    queried = json.loads(_run(project, "--query", "--deck-id", deck_id, "--json").stdout)
    statuses = {m["id"]: m["status"] for m in queried["visual_modules"]}
    assert statuses[a["id"]] == "producing"
    assert statuses[b["id"]] == "producing"


def test_record_review_returns_new_event(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    data = record_review(
        project, "deck", deck_id, reviewer_id="reviewer", reviewer_role="content_reviewer",
        status="failed", findings=[{"kind": "unsupported-claim", "description": "Slide 2 claims X without a citation"}],
        round_number=1,
    )

    assert data["id"].startswith("rev_")
    assert data["subject_type"] == "deck"
    assert data["subject_id"] == deck_id
    assert data["status"] == "failed"
    assert data["findings"][0]["kind"] == "unsupported-claim"
    assert data["round"] == 1


def test_record_review_invalid_subject_type_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    result = _run(
        project, "--record-review", "--subject-type", "not-a-real-type", "--subject-id", deck_id,
        "--reviewer-role", "content_reviewer", "--status", "passed", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ReviewGateError"


def test_record_review_invalid_status_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    result = _run(
        project, "--record-review", "--subject-type", "deck", "--subject-id", deck_id,
        "--reviewer-role", "content_reviewer", "--status", "not-a-real-status", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_record_review_unknown_subject_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--record-review", "--subject-type", "slide", "--subject-id", "sld_does_not_exist",
        "--reviewer-role", "content_reviewer", "--status", "passed", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ReviewGateError"
    assert set(data) == {"error", "predicate", "deck_id", "blockers"}


def test_create_revision_request_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    result = _run(
        project, "--create-revision-request", "--subject-type", "deck", "--subject-id", deck_id,
        "--requested-by", "user", "--instructions", "Shorten the introduction slide.", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("rvq_")
    assert data["requested_by"] == "user"
    assert data["instructions"] == "Shorten the introduction slide."
    assert data["supersedes"] is None


def test_create_revision_request_supersedes_marks_prior_slide_superseded(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    for status in ("ready", "assigned", "producing", "review_required", "passed"):
        _run(project, "--set-slide-status", "--slide-id", slide_id, "--status", status, "--json")

    result = _run(
        project, "--create-revision-request", "--subject-type", "slide", "--subject-id", slide_id,
        "--requested-by", "reviewer", "--instructions", "Re-run with corrected data.",
        "--supersedes", slide_id, "--json",
    )

    assert result.returncode == 0, result.stderr
    result = _run(project, "--set-slide-status", "--slide-id", slide_id, "--status", "blocked", "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"] == "ValueError"


def test_create_revision_request_rejects_illegal_supersede_without_persisting(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    # slide_id is still "planned" -- "superseded" is only legal from "passed",
    # so this supersede attempt must be rejected, and the request itself
    # must never be written to disk.

    result = _run(
        project, "--create-revision-request", "--subject-type", "slide", "--subject-id", slide_id,
        "--requested-by", "reviewer", "--instructions", "Try to supersede too early.",
        "--supersedes", slide_id, "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    requests_path = project / ".research" / "presentations" / "state" / "revision_requests.yaml"
    if requests_path.exists():
        doc = yaml.safe_load(requests_path.read_text())
        assert not (doc or {}).get("revision_requests")


def test_create_revision_request_invalid_requested_by_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    result = _run(
        project, "--create-revision-request", "--subject-type", "deck", "--subject-id", deck_id,
        "--requested-by", "not-a-real-requester", "--instructions", "X", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_check_production_allowed_blocks_before_approved(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "content_review", "--json")
    _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "awaiting_approval", "--json")

    result = _run(project, "--check-production-allowed", "--deck-id", deck["id"], "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProductionGateError"
    assert data["predicate"] == "production_allowed"
    assert data["deck_id"] == deck["id"]
    assert data["blockers"]


def test_check_production_allowed_passes_at_approved(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    for status in ("content_review", "awaiting_approval"):
        _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", status, "--json")

    approve = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "approved", "--json")
    assert approve.returncode == 1
    assert json.loads(approve.stdout)["error"] == "ApprovalGateError"

    result = _run(project, "--check-production-allowed", "--deck-id", deck["id"], "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProductionGateError"
    assert data["predicate"] == "production_allowed"
    assert data["deck_id"] == deck["id"]


def test_check_production_allowed_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--check-production-allowed", "--deck-id", "deck_does_not_exist", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProductionGateError"
    assert set(data) == {"error", "predicate", "deck_id", "blockers"}


def test_query_returns_deck_with_slides_modules_and_revisions(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, slide_id = _make_deck_and_slide(project)
    module = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "m1", "--module-type", "architecture", "--json",
    ).stdout)
    _run(
        project, "--create-revision-request", "--subject-type", "slide", "--subject-id", slide_id,
        "--requested-by", "user", "--instructions", "Shorten.", "--json",
    )

    result = _run(project, "--query", "--deck-id", deck_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["deck"]["id"] == deck_id
    assert [s["id"] for s in data["slides"]] == [slide_id]
    assert [m["id"] for m in data["visual_modules"]] == [module["id"]]
    assert len(data["revision_requests"]) == 1


def test_query_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--query", "--deck-id", "deck_does_not_exist", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "DeckNotFoundError"


def test_query_after_reinvocation_reflects_durable_state_with_no_duplicates(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, slide_id = _make_deck_and_slide(project)
    _run(project, "--set-slide-status", "--slide-id", slide_id, "--status", "ready", "--json")

    # Simulate resuming an interrupted workflow: a brand-new process
    # re-queries the same deck_id with no in-memory state carried over.
    first = json.loads(_run(project, "--query", "--deck-id", deck_id, "--json").stdout)
    second = json.loads(_run(project, "--query", "--deck-id", deck_id, "--json").stdout)

    assert first == second
    assert len(second["slides"]) == 1
    assert second["slides"][0]["status"] == "ready"


def test_query_includes_review_history_and_next_actions(tmp_path: Path) -> None:
    """Query exposes role-specific review history and the next legal action."""
    project = _make_project(tmp_path)
    deck_id, slide_id = _make_deck_and_slide(project)

    from presentation_state import record_review
    record_review(project, "slide", slide_id, "scientific-reviewer", "scientific", "passed")

    resumed = json.loads(_run(project, "--query", "--deck-id", deck_id, "--json").stdout)
    assert resumed["review_results"][0]["reviewer_role"] == "scientific"
    assert resumed["next_actions"] == ["record_visual_quality_review"]


def test_query_has_exact_resume_key_set(tmp_path: Path) -> None:
    """Resume snapshots expose the complete stable public key set."""
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)
    snapshot = json.loads(_run(project, "--query", "--deck-id", deck_id, "--json").stdout)

    assert set(snapshot) == {
        "deck",
        "plans",
        "approval",
        "slides",
        "visual_modules",
        "assignments",
        "artifacts",
        "review_results",
        "revision_requests",
        "draft_preview",
        "draft_decision",
        "blockers",
        "next_actions",
    }


def test_legacy_keyword_review_call_persists_unverifiable_identity(tmp_path: Path) -> None:
    """Legacy keyword calls remain valid without inventing reviewer identity."""
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)
    from presentation_state import load_review_results, record_review

    result = record_review(
        project,
        "deck",
        deck_id,
        reviewer_role="content_reviewer",
        status="passed",
    )

    assert result["reviewer_id"] is None
    assert load_review_results(project)[0]["reviewer_id"] is None


@pytest.mark.parametrize("reviewer_id", ["", "   ", 123, object()])
def test_record_review_rejects_invalid_reviewer_identity(
    tmp_path: Path, reviewer_id: object
) -> None:
    """Invalid reviewer IDs are rejected before an event can be persisted."""
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)
    from presentation_state import load_review_results, record_review

    with pytest.raises(ValueError, match="reviewer_id"):
        record_review(
            project,
            "deck",
            deck_id,
            reviewer_id=reviewer_id,
            reviewer_role="content_reviewer",
            status="passed",
        )

    assert load_review_results(project) == []


def test_plan_review_does_not_satisfy_deck_review_action(tmp_path: Path) -> None:
    """A plan review cannot satisfy the deck review requirement for its ID."""
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)
    from presentation_state import query, record_review, register_plan_record

    register_plan_record(project, deck_id, "plans/plan.yaml", "a" * 64, "planner")
    record_review(
        project,
        "plan",
        deck_id,
        reviewer_id="reviewer",
        reviewer_role="content_reviewer",
        status="passed",
    )

    snapshot = query(project, deck_id)

    assert snapshot["next_actions"] == ["record_content_review"]


def test_latest_review_round_controls_effective_next_action(tmp_path: Path) -> None:
    """A later failed role review supersedes an earlier passing round."""
    project = _make_project(tmp_path)
    deck_id, slide_id = _make_deck_and_slide(project)
    from presentation_state import record_review
    record_review(project, "slide", slide_id, "scientific-a", "scientific", "passed", round_number=1)
    record_review(project, "slide", slide_id, "scientific-a", "scientific", "failed", round_number=2)

    snapshot = json.loads(_run(project, "--query", "--deck-id", deck_id, "--json").stdout)

    assert len(snapshot["review_results"]) == 2
    assert snapshot["next_actions"] != ["record_visual_quality_review"]
    assert any(blocker["reason"] == "review:failed" for blocker in snapshot["blockers"])


def test_integrity_scan_catches_supersession_dependency_and_ownership_drift(tmp_path: Path) -> None:
    """Integrity diagnostics cover all new record foreign keys."""
    project = _make_project(tmp_path)
    deck_id, slide_id = _make_deck_and_slide(project)
    other_deck = json.loads(_run(project, "--create-deck", "--title", "Other", "--json").stdout)
    plans_path = project / ".research" / "presentations" / "state" / "plans.yaml"
    assignments_path = project / ".research" / "presentations" / "state" / "assignments.yaml"
    plans_path.parent.mkdir(parents=True, exist_ok=True)
    plans_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "plans": {
                    "wrong-key": {
                        "id": "plan-real",
                        "deck_id": deck_id,
                        "version": 1,
                        "supersedes_plan_id": "plan-missing",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assignments_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "assignments": {
                    "assignment-real": {
                        "id": "assignment-real",
                        "deck_id": deck_id,
                        "slide_id": slide_id,
                        "module_id": None,
                        "dependencies": ["module-missing"],
                    },
                    "assignment-other": {
                        "id": "assignment-other",
                        "deck_id": other_deck["id"],
                        "slide_id": slide_id,
                        "module_id": None,
                        "dependencies": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    violations = json.loads(result.stdout)["violations"]
    assert any(v["field"] == "id" and v["entity"] == "plan" for v in violations)
    assert any(v["field"] == "supersedes_plan_id" for v in violations)
    assert any(v["field"] == "dependencies" for v in violations)
    assert any(v["field"] == "slide_id" and v["entity"] == "assignment" for v in violations)


def test_validate_on_clean_project_reports_no_violations(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _make_deck_and_slide(project)

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"violations": [], "clean": True}


def test_validate_catches_dangling_slide_deck_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    slides_path = project / ".research" / "presentations" / "state" / "slides.yaml"
    doc = yaml.safe_load(slides_path.read_text())
    doc["slides"][slide_id]["deck_id"] = "deck_does_not_exist"
    slides_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {"entity": "slide", "id": slide_id, "field": "deck_id", "missing_id": "deck_does_not_exist"} in data["violations"]


def test_validate_catches_dangling_module_slide_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    module = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "m1", "--module-type", "architecture", "--json",
    ).stdout)
    modules_path = project / ".research" / "presentations" / "state" / "visual_modules.yaml"
    doc = yaml.safe_load(modules_path.read_text())
    doc["visual_modules"][module["id"]]["slide_id"] = "sld_does_not_exist"
    modules_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {"entity": "visual_module", "id": module["id"], "field": "slide_id", "missing_id": "sld_does_not_exist"} in data["violations"]


def test_validate_catches_dangling_revision_subject_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)
    request = json.loads(_run(
        project, "--create-revision-request", "--subject-type", "deck", "--subject-id", deck_id,
        "--requested-by", "user", "--instructions", "X", "--json",
    ).stdout)
    requests_path = project / ".research" / "presentations" / "state" / "revision_requests.yaml"
    doc = yaml.safe_load(requests_path.read_text())
    doc["revision_requests"][request["id"]]["subject_id"] = "deck_does_not_exist"
    requests_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {"entity": "revision_request", "id": request["id"], "field": "subject_id", "missing_id": "deck_does_not_exist"} in data["violations"]
