"""The shipped examples must satisfy the gates this skill enforces."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Dict

import pytest
import yaml

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from lint_evidence import record_lint_evidence
from presentation_events import create_artifact_record
from presentation_gates import assert_slide_passable
from presentation_state import (
    VISUAL_MODULES_RELATIVE_PATH,
    create_deck,
    create_slide,
    create_visual_module,
    record_review,
    set_slide_status,
)
from validate_generative_prompt import (
    parse_prompt_record, validate_prompt_record,
)
from validate_visual_style import lint_paths, lint_reports

_REPO = Path(__file__).resolve().parents[4]
_EXAMPLE = _REPO / "examples/report-slides/visual-authoring"
_COUNTER = _EXAMPLE / "assets/research-collaboration"


def test_the_example_deck_directory_is_where_the_test_expects() -> None:
    """Guard the path arithmetic, so a miss is not a silent pass."""
    assert _EXAMPLE.is_dir()
    assert (_EXAMPLE / "slides").is_dir()


def test_the_counter_example_prompt_is_rejected() -> None:
    """The prompt that produced the documented failure must not validate."""
    record = parse_prompt_record(_COUNTER / "prompt.md")
    errors = validate_prompt_record(record)
    assert errors
    assert any("banned motif" in error for error in errors)


def test_the_counter_example_is_documented_as_one() -> None:
    """A retained failure must say why it is retained."""
    text = (_COUNTER / "WHY-THIS-FAILS.md").read_text(encoding="utf-8")
    assert "visual-cliche" in text
    assert "stock-ai-composition" in text
    assert "decorative-noise" in text
    assert "downgrade" in text.lower()


def test_the_counter_example_review_records_the_failure() -> None:
    """review.json must no longer claim this asset passed."""
    review = json.loads((_COUNTER / "review.json").read_text(encoding="utf-8"))
    assert review["status"] == "failed"
    kinds = {finding["kind"]
             for finding in review["art_direction"]["findings"]}
    assert {"visual-cliche", "stock-ai-composition",
            "decorative-noise"} <= kinds


def test_the_raster_layer_was_downgraded_out_of_the_deck() -> None:
    """The atmosphere-only bitmap is no longer referenced by any slide."""
    review = json.loads((_COUNTER / "review.json").read_text(encoding="utf-8"))
    assert review["remaining_raster_layers"] == []
    for svg in sorted((_EXAMPLE / "slides").glob("*.svg")):
        assert "research-collaboration/generated.png" not in svg.read_text(
            encoding="utf-8")


@pytest.mark.parametrize(
    "slide_name",
    ["slide01-architecture.svg", "slide02-hybrid.svg", "slide03-chart.svg"])
def test_every_shipped_slide_passes_the_visual_style_gate(
    slide_name: str,
) -> None:
    """The examples must satisfy the gate this skill applies to users' decks."""
    result = lint_paths([_EXAMPLE / "slides" / slide_name],
                        DEFAULT_TOKENS_PATH)
    assert result["valid"] is True, json.dumps(
        result["files"][0]["findings"], indent=2)


_SLIDE_NAMES = (
    "slide01-architecture.svg", "slide02-hybrid.svg", "slide03-chart.svg")


def _publish_example_slide(
    project_root: Path, deck_id: str, slide_name: str, spec_relative: str,
    module_key: str,
) -> str:
    """Register one shipped slide as a production unit under review.

    Args:
        project_root: Project root owning the presentation state.
        deck_id: The deck the slide belongs to.
        slide_name: File name under the example's `slides/` directory.
        spec_relative: Project-relative path of the shared visual spec.
        module_key: The spec module id this slide's module carries.

    Returns:
        The generated slide identifier.
    """
    source = _EXAMPLE / "slides" / slide_name
    target = project_root / "slides" / slide_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, target)
    slide = create_slide(project_root, deck_id, slide_name, slide_name)
    slide_id = str(slide["id"])
    module = create_visual_module(
        project_root, slide_id, module_key, "architecture")
    modules_path = project_root / VISUAL_MODULES_RELATIVE_PATH
    document = yaml.safe_load(modules_path.read_text(encoding="utf-8"))
    document["visual_modules"][module["id"]]["visual_spec_path"] = spec_relative
    modules_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    for status in ("ready", "assigned", "producing", "review_required"):
        set_slide_status(project_root, slide_id, status)
    create_artifact_record(
        project_root, deck_id=deck_id, artifact_kind="slide-svg",
        artifact_path=f"slides/{slide_name}",
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        producer_id="example-producer", slide_id=slide_id)
    return slide_id


@pytest.fixture(scope="module")
def example_project(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, str]:
    """Stage the shipped example as a project held to the enforced gate.

    Args:
        tmp_path_factory: Session temporary-directory factory.

    Returns:
        A mapping with the project root under `root` and each slide file name
        mapped to its generated slide id.
    """
    project_root = tmp_path_factory.mktemp("shipped-example")
    spec_dir = project_root / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(DEFAULT_TOKENS_PATH, spec_dir / "tokens.yaml")
    (spec_dir / "visual.yaml").write_text(
        yaml.safe_dump({"modules": [
            {"id": f"module-{index}", "style_tokens_ref": "tokens.yaml"}
            for index in range(len(_SLIDE_NAMES))
        ]}), encoding="utf-8")
    tokens_digest = DesignTokens.load(spec_dir / "tokens.yaml").digest
    deck = create_deck(project_root, "Visual authoring example")
    staged: Dict[str, str] = {"root": str(project_root)}
    for index, slide_name in enumerate(_SLIDE_NAMES):
        slide_id = _publish_example_slide(
            project_root, str(deck["id"]), slide_name, "specs/visual.yaml",
            f"module-{index}")
        staged[slide_name] = slide_id
        tokens_file = spec_dir / "tokens.yaml"
        _, reports = lint_reports(
            [project_root / "slides" / slide_name], tokens_file)
        _, svg_digest, report = reports[0]
        evidence = record_lint_evidence(
            project_root, "slide", slide_id, svg_digest, tokens_digest,
            report, tokens_path=str(tokens_file))
        # The shipped slides raise no warnings. If one appears, the answer must
        # be written from the slide in front of you -- an answer invented here
        # to keep the fixture green is the exact failure `linter_warnings_
        # answered` exists to expose.
        assert evidence["warnings"] == [], (
            f"{slide_name} now raises {evidence['warnings']}; answer each rule "
            f"from the slide before re-recording the art-direction review")
        record_review(project_root, "slide", slide_id, "example-scientific",
                      "scientific", "passed")
        record_review(project_root, "slide", slide_id, "example-render",
                      "render_integrity", "passed")
        record_review(project_root, "slide", slide_id, "example-art",
                      "art_direction", "passed", linter_warnings_answered=[])
    return staged


@pytest.mark.parametrize("slide_name", _SLIDE_NAMES)
def test_every_shipped_slide_passes_the_enforced_gate(
    slide_name: str, example_project: Dict[str, str],
) -> None:
    """The example deck clears the gate a user's deck must clear.

    Task 13 verified these slides with the linter alone. That was the strongest
    check available then and is not the check users face now: an example that
    passes a weaker gate than the product teaches the wrong thing twice over --
    once about the slide, once about what counts as done.
    """
    project_root = Path(example_project["root"])
    slide_id = example_project[slide_name]
    assert assert_slide_passable(project_root, slide_id)["slide"]["id"] == slide_id
