"""Documentation contract tests for the converted-PPTX visual review gate.

These tests assert that the focused report-slides references name the exact
tokens the runtime and the validator rely on, so the documentation cannot
silently drift away from the machine-checkable contract in
``validate_visual_review.py``.
"""

from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parents[2]
_VISUAL_REVIEW_DOC = _SKILL_ROOT / "references" / "visual-review.md"
_DIAGRAM_WORKFLOW_DOC = _SKILL_ROOT / "references" / "diagram-workflow.md"

_REQUIRED_TOKENS = (
    "statuses.svg_preview",
    "statuses.pptx_structure",
    "statuses.pptx_render",
    "rendered_png_paths",
    "model_vision.inspected_paths",
    "conversion_artifacts",
    "overall.completion_allowed",
    "blocked",
    "not_applicable",
    "source-pixel",
)


def _read(doc_path: Path) -> str:
    """Return the full text of one reference document."""
    return doc_path.read_text(encoding="utf-8")


def _read_normalized(doc_path: Path) -> str:
    """Return one reference document's text with whitespace collapsed.

    Markdown prose wraps a required phrase across source lines; normalizing
    whitespace lets a phrase-level assertion survive that wrapping without
    being sensitive to exactly where a line breaks.
    """
    return " ".join(_read(doc_path).split())


def test_visual_review_doc_names_every_required_token() -> None:
    """Require visual-review.md to name every contract token."""
    text = _read(_VISUAL_REVIEW_DOC)
    missing = [token for token in _REQUIRED_TOKENS if token not in text]
    assert not missing, f"visual-review.md is missing required tokens: {missing}"


def test_diagram_workflow_doc_names_every_required_token() -> None:
    """Require diagram-workflow.md to name every contract token."""
    text = _read(_DIAGRAM_WORKFLOW_DOC)
    missing = [token for token in _REQUIRED_TOKENS if token not in text]
    assert not missing, f"diagram-workflow.md is missing required tokens: {missing}"


def test_visual_review_doc_distinguishes_review_sheet_from_direct_inspection() -> None:
    """Require the docs to keep a review sheet supplemental to direct PNG paths."""
    normalized = _read_normalized(_VISUAL_REVIEW_DOC)
    assert "supplemental" in normalized
    assert "review sheet" in normalized
    assert "model_vision.inspected_paths" in normalized
    assert "never substitutes for the individual PNG paths" in normalized


def test_visual_review_doc_states_structure_does_not_prove_visual_placement() -> None:
    """Require the docs to state that structure validation is not visual evidence."""
    normalized = _read_normalized(_VISUAL_REVIEW_DOC)
    assert "does not inspect visual placement" in normalized
    assert "never establishes that anything looks correct" in normalized


def test_diagram_workflow_doc_states_validator_does_not_replace_direct_inspection() -> None:
    """Require diagram-workflow.md to state the validator's limits explicitly."""
    normalized = _read_normalized(_DIAGRAM_WORKFLOW_DOC)
    assert "does not replace direct model_vision inspection" in normalized
    assert "render_review_sheet.py" in normalized
    assert "supplemental" in normalized
