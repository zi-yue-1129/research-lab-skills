"""Focused public review-sheet provenance gate tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image

from presentation_contracts import contract_sha256
from presentation_events import create_artifact_record, load_artifacts
from presentation_gates import PublicationGateError
from presentation_state import record_review, set_deck_status, set_slide_status
from publish_presentation_artifact import publish_artifact
from render_review_sheet import compose_review_sheet
from test_publish_presentation_artifact import (
    _configure_slides_role,
    approved_assignment,
)


def _published_slide_fixture(tmp_path: Path) -> tuple[Path, str, str, Path, Path, Path]:
    """Publish one current slide PNG and prepare a review-sheet source."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide_id, status)
    record_review(project, "slide", slide_id, "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", slide_id, "visual-reviewer", "visual_quality", "passed")
    set_slide_status(project, slide_id, "passed")
    set_deck_status(project, deck_id, "producing")
    set_deck_status(project, deck_id, "draft_review")
    staged_slide = tmp_path / "staged-slide.png"
    Image.new("RGB", (40, 20), (10, 40, 90)).save(staged_slide)
    slide_destination = project / "docs/slides/rendered/slide-01.png"
    publish_artifact(
        project,
        deck_id,
        staged_slide,
        slide_destination,
        "slide-png",
        slide_id,
        None,
        "worker-a",
        project / "slide-spec.yaml",
    )
    staged_contact = tmp_path / "staged-contact.png"
    compose_review_sheet([slide_destination], staged_contact, columns=1, cell_width=40, cell_height=20)
    contact_destination = project / "docs/slides/rendered/contact-sheet.png"
    return project, deck_id, slide_id, slide_destination, staged_contact, contact_destination


def _stale_slide_fixture(tmp_path: Path, field: str) -> tuple[Path, str, Path, Path]:
    """Persist one stale slide-PNG record through the public artifact API."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project, slide_id, status)
    record_review(project, "slide", slide_id, "scientific-reviewer", "scientific", "passed")
    record_review(project, "slide", slide_id, "visual-reviewer", "visual_quality", "passed")
    set_slide_status(project, slide_id, "passed")
    set_deck_status(project, deck_id, "producing")
    set_deck_status(project, deck_id, "draft_review")
    slide_destination = project / "docs/slides/rendered/slide-01.png"
    slide_destination.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 20), (10, 40, 90)).save(slide_destination)
    digest = __import__("hashlib").sha256(slide_destination.read_bytes()).hexdigest()
    plan = yaml.safe_load((project / "plan.yaml").read_text(encoding="utf-8"))
    create_artifact_record(
        project,
        deck_id,
        "slide-png",
        slide_destination.relative_to(project).as_posix(),
        digest,
        "worker-a",
        slide_id=slide_id,
        plan_version=2 if field == "plan_version" else 1,
        plan_sha256=contract_sha256(plan) if field == "plan_version" else "0" * 64,
        slide_record_id=slide_id,
        attempt=1,
    )
    staged_contact = tmp_path / "staged-contact.png"
    compose_review_sheet([slide_destination], staged_contact, columns=1, cell_width=40, cell_height=20)
    return project, deck_id, staged_contact, project / "docs/slides/rendered/contact-sheet.png"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("plan_version", 2, "plan"),
        ("plan_sha256", "0" * 64, "plan"),
    ],
)
def test_review_sheet_publication_requires_current_slide_plan_binding(
    tmp_path: Path, field: str, value: Any, reason: str
) -> None:
    """Stale slide provenance plan fields fail before destination/state writes."""
    project, deck_id, staged_contact, contact_destination = _stale_slide_fixture(tmp_path, field)
    before_artifacts = load_artifacts(project)

    with pytest.raises(PublicationGateError, match="artifact_provenance_invalid") as raised:
        publish_artifact(
            project,
            deck_id,
            staged_contact,
            contact_destination,
            "review-sheet",
            None,
            None,
            "renderer",
            project / "plan.yaml",
        )

    assert any(reason in str(blocker.get("message", "")) for blocker in raised.value.blockers)

    assert not contact_destination.exists()
    assert load_artifacts(project) == before_artifacts
    assert not list(contact_destination.parent.glob(".*.tmp"))


@pytest.mark.parametrize("attempt", [True, 0, -1])
def test_review_sheet_publication_rejects_invalid_current_slide_attempt(
    tmp_path: Path, attempt: Any
) -> None:
    """Boolean and nonpositive current attempts fail before publication."""
    project, deck_id, slide_id, _, staged_contact, contact_destination = _published_slide_fixture(tmp_path)
    slides_path = project / ".research/presentations/state/slides.yaml"
    state = yaml.safe_load(slides_path.read_text(encoding="utf-8"))
    state["slides"][slide_id]["attempt"] = attempt
    slides_path.write_text(yaml.safe_dump(state), encoding="utf-8")
    before_artifacts = load_artifacts(project)

    with pytest.raises(PublicationGateError, match="attempt|provenance"):
        publish_artifact(
            project,
            deck_id,
            staged_contact,
            contact_destination,
            "review-sheet",
            None,
            None,
            "renderer",
            project / "plan.yaml",
        )

    assert not contact_destination.exists()
    assert load_artifacts(project) == before_artifacts
