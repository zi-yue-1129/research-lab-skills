"""Fixture support for the enforced visual-style gate.

`assert_slide_passable` refuses a slide that has no published SVG or no current
lint evidence. Fixtures written before that gate existed describe decks the
pipeline could not have produced: Stage 10 writes both for every slide it
integrates.

Supplying them here keeps those fixtures honest without each one growing its own
copy, and without relaxing the gate to accommodate a fixture that predates it.
The SVG is real and is really linted, so a fixture that stops being clean says
so instead of recording a pass nobody measured.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from lint_evidence import record_lint_evidence
from presentation_events import create_artifact_record
from validate_visual_style import lint_reports

# A slide that satisfies every rule module: full-canvas background, one title at
# the `slide_title` size, one card, one body run, everything on the 8px grid and
# inside the safe area.
FIXTURE_SLIDE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" \
height="675" viewBox="0 0 1200 675">
  <rect x="0" y="0" width="1200" height="675" fill="#ffffff"/>
  <text x="48" y="104" font-size="32" fill="#1e3a5f" \
data-style-role="slide_title">Fixture slide</text>
  <rect x="48" y="160" width="1104" height="400" fill="#f8fafc" \
data-style-role="card"/>
  <text x="80" y="240" font-size="21" fill="#374151" \
data-style-role="body">A measured slide, not a placeholder.</text>
</svg>
"""


def publish_and_lint_slide(
    project_root: Path,
    deck_id: str,
    slide_id: str,
    tokens_path: Path | None = None,
    producer_id: str = "fixture-producer",
) -> str:
    """Publish a slide's SVG and record the lint result the gate reads.

    Args:
        project_root: Project root owning the presentation state.
        deck_id: The deck the slide belongs to.
        slide_id: The slide to make gate-ready.
        tokens_path: Token file to lint against; the shipped default when the
            deck declares none of its own.
        producer_id: Producer identity recorded on the artifact; must differ
            from every reviewer id, or the self-review check fires.

    Returns:
        The generated slide identifier, for call-site chaining.

    Raises:
        AssertionError: If the fixture slide stops linting clean, which would
            otherwise be recorded as a pass nobody measured.
    """
    tokens_path = tokens_path or DEFAULT_TOKENS_PATH
    tokens_digest = DesignTokens.load(tokens_path).digest
    svg_relative = f"slides/{slide_id}.svg"
    svg_path = project_root / svg_relative
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(FIXTURE_SLIDE_SVG, encoding="utf-8")
    create_artifact_record(
        project_root, deck_id=deck_id, artifact_kind="slide-svg",
        artifact_path=svg_relative,
        sha256=hashlib.sha256(svg_path.read_bytes()).hexdigest(),
        producer_id=producer_id, slide_id=slide_id)
    _, reports = lint_reports([svg_path], tokens_path)
    report = reports[0][1]
    assert not [finding for finding in report.findings
                if finding.severity == "error"], (
        f"the fixture slide no longer lints clean: {report.to_dict()}")
    record_lint_evidence(
        project_root, "slide", slide_id,
        hashlib.sha256(svg_path.read_bytes()).hexdigest(), tokens_digest,
        report, tokens_path=str(tokens_path))
    return slide_id
