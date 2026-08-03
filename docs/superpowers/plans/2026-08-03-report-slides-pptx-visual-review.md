# Report Slides PPTX Visual Review Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make a requested report-slides PPTX complete only after the actual exported PPTX is converted to one PNG per expected slide and every final PNG is directly inspected by model_vision, while retaining the existing source-pixel completion path for non-PPTX output.

**Architecture:** Keep the existing source SVG, subfigure, and complete-slide review as the independent svg_preview gate. Add a small deterministic Python record validator that checks the evidence contract and derives overall completion without merging gate evidence. Extend the report-slides skill and its focused references with the PPTX export, office conversion, direct-PNG inspection, failure, blocker, revision, and no-PPTX branches; use tracked fixture decks and a pressure eval to prove that source similarity and PPTX structure cannot mask a converted-PPTX visual defect.

**Tech Stack:** English Markdown, Python 3.8+, pytest, Pillow for PNG readability checks, Python standard-library JSON/path/ZIP validation, existing python-pptx and svg_to_pptx tooling, LibreOffice PDF/PNG or an equivalent office renderer, model_vision, and the existing read-only eval command convention.

## Global Constraints

- The approved design source is docs/superpowers/specs/2026-08-03-report-slides-pptx-visual-review-design.md, version 1.0, status Approved; every task implements that contract rather than redefining it.
- For a PPTX request, source SVG/subfigure/complete-slide review runs before export and is recorded as statuses.svg_preview; it does not establish PPTX visual correctness.
- For a PPTX request, the actual PPTX package is validated separately as statuses.pptx_structure; structure evidence is never visual evidence.
- For a PPTX request, the actual PPTX is opened by LibreOffice PDF/PNG conversion or an equivalent office renderer, exactly one inspectable PNG is produced for every expected slide, and model_vision directly inspects every final PNG.
- statuses.svg_preview, statuses.pptx_structure, and statuses.pptx_render remain independent fields with status values passed, failed, blocked, or not_applicable; in_progress is not a valid completion status.
- A PPTX request allows completion only when all three required statuses are passed; the authoritative final visual gate is pptx_render.
- Conversion failure, a missing or unreadable converted PNG, an incomplete slide set, or unavailable direct model_vision inspection produces blocked with an exact blocker and overall.completion_allowed false.
- A visual defect with evidence produces failed with a concrete finding and revision_required true; it requires a fresh downstream export, conversion, and direct inspection cycle.
- A review sheet and source PNGs remain supplemental comparison evidence; neither can satisfy statuses.pptx_render.model_vision.inspected_paths.
- A source-only request leaves statuses.pptx_structure and statuses.pptx_render as not_applicable with a non-empty reason and keeps the existing source-pixel gate authoritative.
- The implementation does not change the existing SVG-to-PPTX converter, its editability contract, animations, transitions, speaker notes, or unrelated authoring behavior.
- Future implementation changes are limited to the paths in the File Map; existing converter, review-sheet, and prior visual-authoring files named below are read-only context.
- Use existing Pillow, PyYAML, pytest, python-pptx, and lxml dependencies; do not add a new runtime dependency.
- Every public Python module, class, function, and method has complete type annotations and a Google-style docstring; comments, logs, CLI messages, and commit subjects are English.
- Missing evidence is an explicit error or blocker; no fallback may turn source SVG pixels, a review sheet, or structure validation into a final PPTX visual pass.
- Every implementation task receives two Terra checkpoints in order: specification compliance, then code/document quality, using gpt-5.6-terra with high reasoning effort. A finding returns to the task and its verification cycle.
- Do not use the sol model for worker or review dispatches. A required Terra capability that is unavailable is a go/no-go blocker.
- Do not alter files outside the File Map, do not amend unrelated work, and stage only the paths named by the current task.

---

## File Map

| Path | State in the implementation plan | Responsibility |
|---|---|---|
| skills/report-slides/scripts/validate_visual_review.py | Create | Deterministically validate review-record shape, status independence, final PNG evidence, blocker semantics, and derived completion. |
| skills/report-slides/scripts/tests/test_validate_visual_review.py | Create | RED/GREEN contract tests for the eight status scenarios and record-validation rules. |
| skills/report-slides/scripts/tests/test_visual_review_docs.py | Create | Assert that the focused references contain the authoritative converted-PPTX, blocker, and no-PPTX contracts. |
| skills/report-slides/SKILL.md | Modify | Make output-format branching, actual PPTX conversion, direct model_vision inspection, status fields, and completion reporting explicit. |
| skills/report-slides/references/visual-review.md | Modify | Define source-pixel diagnostics, converted-PPTX visual authority, record evidence, revision loop, and blocked review behavior. |
| skills/report-slides/references/diagram-workflow.md | Modify | Extend completion records and validation commands without collapsing preview, structure, and render status. |
| evals/report-slides-pptx-visual-review/scenarios.yaml | Create | One PPTX authority pressure scenario and one no-PPTX control scenario with closed rubrics. |
| evals/report-slides-pptx-visual-review/baseline.md | Create | Fresh RED responses and Terra scoring against the pre-change skill/reference contract. |
| evals/report-slides-pptx-visual-review/after.md | Create | Fresh GREEN responses, raw-output hashes, Terra scoring, and baseline comparison. |
| tests/fixtures/report-slides-pptx-visual-review/README.md | Create | Fixture provenance, case semantics, render commands, and direct-inspection instructions. |
| tests/fixtures/report-slides-pptx-visual-review/fixture_manifest.yaml | Create | Deterministic mapping of six concrete visual cases to source, PPTX, converted PNG, expected statuses, and completion decisions. |
| tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/source/slide-01.svg | Create | Clean two-slide source fixture, slide 1. |
| tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/source/slide-02.svg | Create | Clean two-slide source fixture, slide 2. |
| tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/deck.pptx | Generate and track as a fixture | Clean two-slide delivered PPTX. |
| tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/renders/source/slide-01.png | Generate and track as a fixture | Source-pixel evidence for clean slide 1. |
| tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/renders/source/slide-02.png | Generate and track as a fixture | Source-pixel evidence for clean slide 2. |
| tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/renders/pptx/slide-01.png | Generate and track as a fixture | Converted-PPTX final evidence for clean slide 1. |
| tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/renders/pptx/slide-02.png | Generate and track as a fixture | Converted-PPTX final evidence for clean slide 2. |
| tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/review.json | Create | Passing three-gate record with direct final PNG paths. |
| tests/fixtures/report-slides-pptx-visual-review/native-text-reflow/source/slide-01.svg | Create | Source that is visually correct before native text conversion. |
| tests/fixtures/report-slides-pptx-visual-review/native-text-reflow/deck.pptx | Generate and track as a fixture | PPTX whose text box reflows after conversion. |
| tests/fixtures/report-slides-pptx-visual-review/native-text-reflow/renders/source/slide-01.png | Generate and track as a fixture | Passing source-pixel evidence. |
| tests/fixtures/report-slides-pptx-visual-review/native-text-reflow/renders/pptx/slide-01.png | Generate and track as a fixture | Converted PNG showing the text-reflow defect. |
| tests/fixtures/report-slides-pptx-visual-review/native-text-reflow/review.json | Create | Failed pptx_render record with an open text-reflow finding. |
| tests/fixtures/report-slides-pptx-visual-review/connector-endpoint-drift/source/slide-01.svg | Create | Source with a connector attached to a target shape. |
| tests/fixtures/report-slides-pptx-visual-review/connector-endpoint-drift/deck.pptx | Generate and track as a fixture | PPTX whose converted connector endpoint drifts. |
| tests/fixtures/report-slides-pptx-visual-review/connector-endpoint-drift/renders/source/slide-01.png | Generate and track as a fixture | Passing source-pixel evidence. |
| tests/fixtures/report-slides-pptx-visual-review/connector-endpoint-drift/renders/pptx/slide-01.png | Generate and track as a fixture | Converted PNG showing connector drift. |
| tests/fixtures/report-slides-pptx-visual-review/connector-endpoint-drift/review.json | Create | Failed pptx_render record with a connector-drift finding. |
| tests/fixtures/report-slides-pptx-visual-review/image-crop-regression/source/slide-01.svg | Create | Source containing a required image subject inside its intended crop. |
| tests/fixtures/report-slides-pptx-visual-review/image-crop-regression/deck.pptx | Generate and track as a fixture | PPTX whose converted image crop hides the required subject. |
| tests/fixtures/report-slides-pptx-visual-review/image-crop-regression/renders/source/slide-01.png | Generate and track as a fixture | Passing source-pixel evidence. |
| tests/fixtures/report-slides-pptx-visual-review/image-crop-regression/renders/pptx/slide-01.png | Generate and track as a fixture | Converted PNG showing crop regression. |
| tests/fixtures/report-slides-pptx-visual-review/image-crop-regression/review.json | Create | Failed pptx_render record with a crop finding. |
| tests/fixtures/report-slides-pptx-visual-review/missing-image-relationship/source/slide-01.svg | Create | Source containing a required image relationship. |
| tests/fixtures/report-slides-pptx-visual-review/missing-image-relationship/deck.pptx | Generate and track as a fixture | PPTX with a missing relationship that removes the image. |
| tests/fixtures/report-slides-pptx-visual-review/missing-image-relationship/renders/source/slide-01.png | Generate and track as a fixture | Passing source-pixel evidence. |
| tests/fixtures/report-slides-pptx-visual-review/missing-image-relationship/renders/pptx/slide-01.png | Generate and track as a fixture | Converted PNG showing the missing image. |
| tests/fixtures/report-slides-pptx-visual-review/missing-image-relationship/review.json | Create | Structure failure and independent render evidence for a missing image. |
| tests/fixtures/report-slides-pptx-visual-review/unreadably-small-text/source/slide-01.svg | Create | Source with presentation-scale text intended to remain readable. |
| tests/fixtures/report-slides-pptx-visual-review/unreadably-small-text/deck.pptx | Generate and track as a fixture | PPTX whose converted text is unreadably small. |
| tests/fixtures/report-slides-pptx-visual-review/unreadably-small-text/renders/source/slide-01.png | Generate and track as a fixture | Passing source-pixel evidence. |
| tests/fixtures/report-slides-pptx-visual-review/unreadably-small-text/renders/pptx/slide-01.png | Generate and track as a fixture | Converted PNG showing the text-size regression. |
| tests/fixtures/report-slides-pptx-visual-review/unreadably-small-text/review.json | Create | Failed pptx_render record with an unreadably-small-text finding. |

The implementation must not modify these existing files; they are compatibility references only:

- docs/superpowers/specs/2026-08-03-report-slides-pptx-visual-review-design.md
- skills/report-slides/scripts/svg_to_pptx/__main__.py
- skills/report-slides/scripts/svg_to_pptx/converter.py
- skills/report-slides/scripts/svg_to_pptx/tests/test_integration.py
- skills/report-slides/scripts/render_review_sheet.py
- evals/report-slides-visual-authoring/scenarios.yaml
- evals/report-slides-visual-authoring/baseline.md
- evals/report-slides-visual-authoring/after.md
- docs/superpowers/plans/2026-08-03-report-slides-visual-authoring.md

## Contract Interfaces

The new validator is evidence validation, not model_vision. It must never infer that a path was inspected merely because the file exists.

- validate_visual_review.ValidationIssue is an immutable dataclass with fields path: str and message: str.
- validate_visual_review.OverallResult is an immutable dataclass with fields status: str, completion_allowed: bool, and authority: str.
- validate_visual_review.VALID_STATUSES is the tuple passed, failed, blocked, not_applicable.
- validate_visual_review.validate_review_record(record_path: Path, artifact_root: Optional[Path] = None) -> List[ValidationIssue] loads one JSON record, validates every required field and relative artifact path, and returns issues sorted by path.
- validate_visual_review.derive_overall_status(record: Mapping[str, Any]) -> OverallResult applies failed-over-blocked precedence and the separate source-only rule; malformed records raise ValueError rather than selecting a safe-looking default.
- validate_visual_review.main(arguments: Optional[Sequence[str]] = None) -> int accepts --record and --root, prints one ERROR line per issue, prints a passing summary only when there are no issues, and returns 1 on any issue.
- Status-object validation requires status, positive round, reviewed_by, findings, revision_required, started_at, and completed_at. A blocked status requires blocker; a not_applicable status requires reason; a failed status requires an evidence-backed finding and revision_required true; a passed status has no open finding and revision_required false.
- Visual status validation requires model_vision as reviewed_by and direct inspected_paths for a pass. PPTX structure validation requires a named structural validator and may not contribute image evidence.
- PPTX render validation requires renderer.name, renderer.version, renderer.conversion_format, conversion_artifacts, rendered_png_paths, model_vision.inspected_paths, and visual_checks. rendered_png_paths must contain exactly one readable PNG per expected slide, and model_vision.inspected_paths must equal that final PNG set. A review-sheet path is supplemental only.
- Overall validation requires overall.status, overall.completion_allowed, and overall.authority to equal the value derived from the three independent gate statuses and output_format.

## Test and Evaluation Matrix

| Contract or evaluation | Evidence that must be asserted |
|---|---|
| PPTX happy path | Two expected slides, three passed statuses, matching final PNG and direct-inspection sets, overall passed and completion_allowed true. |
| PPTX-only regression | svg_preview passed and pptx_structure passed remain unchanged; converted text-reflow finding is open; pptx_render failed; completion is false. |
| Conversion blocker | pptx_render blocked with the exact missing-renderer blocker and no completion claim. |
| Direct-inspection blocker | Two final PNGs exist but model_vision.inspected_paths contains one; the result is blocked even when a review sheet exists. |
| Missing-slide blocker | expected_slides is [1, 2] while the converted PNG set contains only slide 1; the result is blocked. |
| No-PPTX path | svg_preview remains the final gate; both PPTX statuses are not_applicable with reasons; a passed source gate allows completion. |
| Independent statuses | Structure failure preserves svg_preview; render failure preserves pptx_structure; evidence and findings do not migrate between fields. |
| Revision cycle | A failed round is closed as fixed or rechecked, a new round inspects a new converted PNG set, and only the new passed round allows completion. |
| Fixture visual cases | Reflow, connector drift, crop, missing image, unreadably small text, and clean two-slide outputs are recorded with source path, PPTX path, converted PNG path, direct model_vision path, per-gate status, and overall decision. |
| Pressure eval | A worker must reject a source-only or structure-only pass when the converted PNG has a PPTX-only defect and must keep the no-PPTX branch source-authoritative. |

---

### Task 0: Establish the execution and review gate

**Files:**
- None.

**Interfaces:**
- Consumes: current branch, approved design spec, and repository test environment.
- Produces: a clean implementation baseline and a confirmed Terra reviewer capability.

- [ ] **Step 1: Verify the implementation checkout before any future change**

Run:

    git status --short --branch
    git rev-parse HEAD
    test -z "$(git status --porcelain)"

Expected: branch report-slides-pptx-review-gate is current, the working tree is empty, and the approved spec commit is HEAD.

- [ ] **Step 2: Run the existing report-slides script tests as a baseline**

Run:

    pytest skills/report-slides/scripts/tests -q

Expected: the existing suite completes without changes from this plan. Record the count and any environment-only limitation in the implementation log.

- [ ] **Step 3: Probe the required Terra reviewer**

Run:

    codex exec --ephemeral --model gpt-5.6-terra --config model_reasoning_effort=high --sandbox read-only --ignore-rules --color never "Reply with exactly READY. Do not inspect or modify files."

Expected: READY. If Terra is unavailable, stop before implementation and report the review gate as blocked.

- [ ] **Step 4: Preserve the approved spec as the single design authority**

Read docs/superpowers/specs/2026-08-03-report-slides-pptx-visual-review-design.md and map each of its ten acceptance criteria to the Task 3, Task 4, Task 5, or Task 6 evidence below.

- [ ] **Step 5: Complete the Task 0 Terra checkpoint**

Ask Terra to review the baseline command output and the acceptance-criteria mapping for scope and sequencing. Expected: APPROVED with no request to modify files.

---

### Task 1: Capture RED contract tests and the pressure scenario

**Files:**
- Create: evals/report-slides-pptx-visual-review/scenarios.yaml
- Create: evals/report-slides-pptx-visual-review/baseline.md
- Create: skills/report-slides/scripts/tests/test_validate_visual_review.py

**Interfaces:**
- Consumes: the current skills/report-slides/SKILL.md, references/visual-review.md, and references/diagram-workflow.md.
- Produces: a failing deterministic test module and a rubric-driven baseline that demonstrate the missing authoritative converted-PPTX gate.

- [ ] **Step 1: Write the pressure and control scenarios before documentation changes**

Write evals/report-slides-pptx-visual-review/scenarios.yaml with this concrete content:

    schema_version: 1
    skill_path: skills/report-slides/SKILL.md
    reference_paths:
      - skills/report-slides/references/visual-review.md
      - skills/report-slides/references/diagram-workflow.md
    scenarios:
      - id: pptx-converted-png-authority
        prompt: >-
          Use report-slides to complete a two-slide deck requested as PPTX.
          The source slide PNGs pass model_vision review and the PPTX package
          passes structural validation. LibreOffice converts the actual PPTX
          into renders/pptx/libreoffice/slide-1.png and
          renders/pptx/libreoffice/slide-2.png. Direct model_vision inspection
          finds text reflow on slide 2 in the converted PNG, while the source
          SVG and a review sheet look correct. Return the complete review
          record and the next action. State every independent status and
          whether completion is allowed.
        required:
          - statuses.svg_preview is passed
          - statuses.pptx_structure is passed
          - statuses.pptx_render is failed
          - the open finding has kind text-reflow and the converted slide-2 path
          - overall.completion_allowed is false
          - the source SVG and structure pass do not override the render failure
          - a fresh export, conversion, and direct PNG inspection are required
      - id: no-pptx-source-gate
        prompt: >-
          Use report-slides for a source-only SVG deliverable with a passing
          source subfigure and complete-slide pixel review. No PPTX was
          requested and no office renderer is installed. Return the complete
          review record and completion decision.
        required:
          - statuses.svg_preview is passed
          - statuses.pptx_structure is not_applicable with a non-empty reason
          - statuses.pptx_render is not_applicable with a non-empty reason
          - overall.authority is source-pixel
          - overall.completion_allowed is true
          - the missing office renderer is not invoked for this output contract

- [ ] **Step 2: Write the RED contract tests with exact scenario names**

Create skills/report-slides/scripts/tests/test_validate_visual_review.py. The first version imports the future public interfaces so collection fails until Task 2 creates the module. The test module must contain these exact test functions:

    test_pptx_happy_path_allows_completion
    test_pptx_only_text_reflow_fails_render
    test_missing_renderer_blocks_completion
    test_partial_direct_inspection_blocks_completion
    test_missing_expected_slide_blocks_completion
    test_non_pptx_marks_pptx_gates_not_applicable
    test_gate_statuses_remain_independent
    test_revision_round_rechecks_converted_pngs
    test_passing_render_requires_renderer_metadata
    test_passing_render_requires_exact_png_set
    test_passing_render_rejects_review_sheet_only
    test_passing_render_rejects_open_finding

Use a fixed 2026-08-03T10:00:00Z timestamp in the record factory, create readable RGB PNGs with Pillow in tmp_path, and write JSON records under tmp_path. The core assertions must be concrete:

    result = derive_overall_status(record)
    assert result.status == "passed"
    assert result.completion_allowed is True
    assert result.authority == "pptx-render"

    issues = validate_review_record(record_path, tmp_path)
    assert any(issue.path == "statuses.pptx_render.model_vision.inspected_paths" for issue in issues)
    assert any("direct" in issue.message for issue in issues)

For the independence test, mutate only statuses.pptx_structure.status to failed and assert the original svg_preview mapping is byte-for-byte equal; then construct a separate render-failure record and assert the original pptx_structure mapping is byte-for-byte equal.

- [ ] **Step 3: Run the RED contract test command**

Run:

    pytest skills/report-slides/scripts/tests/test_validate_visual_review.py -q

Expected: collection fails because validate_visual_review is not present. Do not hide the import failure or replace the test with a weaker smoke test.

- [ ] **Step 4: Run the RED pressure workers without showing the rubric**

For each scenario, run a fresh read-only worker against only the current skill and named references. Use:

    codex exec --ephemeral --model gpt-5.6-luna --config model_reasoning_effort=max --sandbox read-only --ignore-rules --color never -o /tmp/report-slides-pptx-visual-review-baseline-authority.txt "Act as a bounded report-slides worker. Read only the named report-slides skill and references from the current checkout. Do not inspect or modify other files. Return only the substantive answer to the pptx-converted-png-authority scenario."

    codex exec --ephemeral --model gpt-5.6-luna --config model_reasoning_effort=max --sandbox read-only --ignore-rules --color never -o /tmp/report-slides-pptx-visual-review-baseline-source-only.txt "Act as a bounded report-slides worker. Read only the named report-slides skill and references from the current checkout. Do not inspect or modify other files. Return only the substantive answer to the no-pptx-source-gate scenario."

The scenario text in scenarios.yaml is the authoritative prompt text; the two output paths are the canonical raw captures for baseline.md.

- [ ] **Step 5: Score the RED responses with Terra**

For each raw response, record Raw response, Score, and Observed failure pattern in baseline.md. Mark a requirement pass only when the response states the required field and consequence. The PPTX pressure scenario must expose at least one failure in the pre-change contract; the control scenario must reveal whether the existing source-only behavior is preserved.

- [ ] **Step 6: Run the first Terra task review**

Run two reviews in order: specification compliance against the approved spec and evidence quality of the RED test/eval. Expected: both Terra reviews return APPROVED. Fix only paths in this task if either review finds a defect, rerun the RED command, and repeat both reviews.

- [ ] **Step 7: Commit the RED task**

Run:

    git diff --check
    git add evals/report-slides-pptx-visual-review/scenarios.yaml evals/report-slides-pptx-visual-review/baseline.md skills/report-slides/scripts/tests/test_validate_visual_review.py
    git commit -m "test(report-slides): add PPTX visual review RED contract"

Expected: only the three task paths are staged.

---

### Task 2: Implement deterministic review-record validation

**Files:**
- Create: skills/report-slides/scripts/validate_visual_review.py
- Modify: skills/report-slides/scripts/tests/test_validate_visual_review.py

**Interfaces:**
- Consumes: the RED records and fixture helpers from Task 1.
- Produces: ValidationIssue, OverallResult, validate_review_record, derive_overall_status, and a CLI that rejects incomplete PPTX evidence.

- [ ] **Step 1: Define the public value objects and status constants**

Add the following typed interfaces at module scope:

    VALID_STATUSES: Tuple[str, ...] = (
        "passed",
        "failed",
        "blocked",
        "not_applicable",
    )

    @dataclass(frozen=True)
    class ValidationIssue:
        """One deterministic review-record validation issue."""

        path: str
        message: str

    @dataclass(frozen=True)
    class OverallResult:
        """Derived completion result for one review record."""

        status: str
        completion_allowed: bool
        authority: str

The module docstring must state that record validation does not prove that model_vision inspected an image; it verifies that the record names the exact paths the runtime inspected.

- [ ] **Step 2: Implement record loading and structural validation**

Implement:

    def validate_review_record(
        record_path: Path,
        artifact_root: Optional[Path] = None,
    ) -> List[ValidationIssue]:
        """Validate one report-slides visual review record."""

Load JSON with an explicit error for malformed JSON or a non-mapping root. Validate schema_version, deck_id, output_format, expected_slides, source_artifacts, artifacts, statuses, overall, and history. Validate all relative paths against artifact_root, reject absolute paths and path traversal, and use Pillow Image.open followed by image.verify for every final PNG. Return issues sorted by path without hiding any issue.

Implement one helper per contract boundary: _validate_status_object for the common fields, _validate_pptx_render_status for renderer and final PNG evidence, _validate_findings for finding kind/source/disposition, _validate_history for round progression, and _validate_overall for derived-result equality. Keep these helpers private but typed.

- [ ] **Step 3: Encode independent status and output-format rules**

For output_format pptx, require svg_preview, pptx_structure, and pptx_render to be present and never not_applicable. Require model_vision for visual statuses, a named structural validator for pptx_structure, and separate findings under each status. Require the PPTX render path to contain one final PNG per expected slide and require the model_vision path list to equal the final PNG set.

For a non-PPTX output, require pptx_structure.status and pptx_render.status to be not_applicable, require both reason fields to name the source-only output contract, and reject any attempt to invoke or record a renderer. Leave svg_preview as the only visual completion gate.

- [ ] **Step 4: Implement deterministic overall derivation**

Implement:

    def derive_overall_status(
        record: Mapping[str, Any],
    ) -> OverallResult:
        """Derive completion from independent gate statuses."""

Use authority pptx-render for output_format pptx and source-pixel for every other output format. For PPTX, return failed when any required status is failed, blocked when no required status is failed and at least one is blocked, and passed only when all three statuses are passed. For source-only output, return failed or blocked from svg_preview and passed only when svg_preview is passed and both PPTX statuses are not_applicable. Raise ValueError for unset, in_progress, or unknown statuses; do not use a passing default.

- [ ] **Step 5: Add the command-line contract**

Implement:

    def main(arguments: Optional[Sequence[str]] = None) -> int:
        """Validate a review record from the command line."""

Support --record and --root. Print errors as ERROR path: message and return 1 for any issue. Print the derived status, authority, and completion_allowed only when validation returns no issues, then return 0. Add a __main__ guard that exits with main().

- [ ] **Step 6: Run the GREEN contract suite**

Run:

    pytest skills/report-slides/scripts/tests/test_validate_visual_review.py -q

Expected: all twelve named tests pass. Also run one CLI pass and one CLI failure:

    python3 skills/report-slides/scripts/validate_visual_review.py --record tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/review.json --root tests/fixtures/report-slides-pptx-visual-review
    python3 skills/report-slides/scripts/validate_visual_review.py --record tests/fixtures/report-slides-pptx-visual-review/native-text-reflow/review.json --root tests/fixtures/report-slides-pptx-visual-review

Expected: the clean record returns 0 with passed and pptx-render; the regression record returns 1 with an open text-reflow issue.

- [ ] **Step 7: Complete both Terra reviews before committing**

Run the specification-compliance Terra review against all status rules in the approved spec, then the code-quality Terra review against type annotations, docstrings, deterministic ordering, path safety, and explicit failures. For every finding, amend only this task's files, rerun the full task suite, and repeat both reviews until both return APPROVED.

- [ ] **Step 8: Commit the validator task**

Run:

    git diff --check
    git add skills/report-slides/scripts/validate_visual_review.py skills/report-slides/scripts/tests/test_validate_visual_review.py
    git commit -m "feat(report-slides): validate PPTX visual review records"

Expected: the prior RED files remain committed and no unrelated path is staged.

---

### Task 3: Update the focused visual-review references

**Files:**
- Modify: skills/report-slides/references/visual-review.md
- Modify: skills/report-slides/references/diagram-workflow.md
- Create: skills/report-slides/scripts/tests/test_visual_review_docs.py

**Interfaces:**
- Consumes: the validator contract from Task 2 and existing source-pixel guidance.
- Produces: documentation that makes converted-PPTX PNG inspection authoritative and machine-checkable without replacing source diagnostics.

- [ ] **Step 1: Write documentation contract tests**

Create typed tests that read the two reference files and assert these exact phrases or field names are present: statuses.svg_preview, statuses.pptx_structure, statuses.pptx_render, rendered_png_paths, model_vision.inspected_paths, conversion_artifacts, overall.completion_allowed, blocked, not_applicable, and source-pixel. Add a test that asserts the references distinguish a review sheet from direct final PNG inspection and state that structure validation does not establish visual placement.

- [ ] **Step 2: Extend visual-review.md after Render before review**

Add a PPTX-specific section that defines this exact sequence:

    source subfigure and complete-slide PNG review
    -> source-pixel decision
    -> actual PPTX export
    -> independent PPTX package validation
    -> office-renderer conversion of the actual PPTX
    -> one PNG for every expected slide
    -> direct model_vision inspection of every final PNG
    -> authoritative pptx_render decision

Document that source PNGs and comparison references remain diagnostic. State that a PPTX-only clipping, overlap, text reflow, connector drift, crop, unreadably small text, missing image, z-order, alignment, margin, or other layout regression fails pptx_render even when the source review and structure review pass.

Document the standard conversion commands with a concrete deck path:

    python3 -m svg_to_pptx --slides docs/slides/reports/2026-08-03_pptx-review-gate --out docs/slides/reports/2026-08-03_pptx-review-gate/deck.pptx
    mkdir -p docs/slides/reports/2026-08-03_pptx-review-gate/renders/pptx/libreoffice
    libreoffice --headless --convert-to pdf --outdir docs/slides/reports/2026-08-03_pptx-review-gate/renders/pptx/libreoffice docs/slides/reports/2026-08-03_pptx-review-gate/deck.pptx
    pdftoppm -png -r 150 docs/slides/reports/2026-08-03_pptx-review-gate/renders/pptx/libreoffice/deck.pdf docs/slides/reports/2026-08-03_pptx-review-gate/renders/pptx/libreoffice/slide

Require the record to use the actual renderer name, version, conversion format, PDF path when produced, and final PNG paths. If an equivalent office renderer is used, record its actual identity and output format. If neither renderer can open the PPTX, record blocked and stop.

- [ ] **Step 3: Replace the generic review-record example**

In the Review record section, show a concrete top-level JSON example with schema_version 1, output_format pptx, expected_slides [1, 2], separate status objects, a PPTX path, two converted PNG paths, identical rendered_png_paths and model_vision.inspected_paths, optional comparison_reference_paths, visual_checks, overall authority pptx-render, and a failed round followed by a corrected round. Include started_at, completed_at, blocker/reason rules, and revision_required values.

Keep the source-only record rule adjacent to the example: both PPTX statuses are not_applicable with explicit reasons, and overall authority is source-pixel.

- [ ] **Step 4: Extend diagram-workflow.md**

Update Completion record to list the three independent statuses, direct converted PNG paths, renderer metadata, conversion artifacts, review rounds, findings, blocker, and revision semantics. Add the validator command:

    python3 skills/report-slides/scripts/validate_visual_review.py --record docs/slides/reports/2026-08-03_pptx-review-gate/review.json --root docs/slides/reports/2026-08-03_pptx-review-gate

State that the validator checks evidence shape and paths but does not replace direct model_vision inspection. Keep render_review_sheet.py as a supplemental comparison tool and leave its contract unchanged.

- [ ] **Step 5: Run the reference tests and text checks**

Run:

    pytest skills/report-slides/scripts/tests/test_visual_review_docs.py -q
    rg -n "statuses\\.svg_preview|statuses\\.pptx_structure|statuses\\.pptx_render|model_vision\\.inspected_paths|not_applicable|blocked" skills/report-slides/references/visual-review.md skills/report-slides/references/diagram-workflow.md

Expected: tests pass and every required contract token appears in the focused references.

- [ ] **Step 6: Complete both Terra reviews and commit**

Run the specification-compliance review first, then the documentation-quality review. Check for contradictory statements, source-SVG substitution, review-sheet substitution, missing blocker consequences, and loss of the no-PPTX path. Fix only the two references and their test file, rerun the tests, then run:

    git diff --check
    git add skills/report-slides/references/visual-review.md skills/report-slides/references/diagram-workflow.md skills/report-slides/scripts/tests/test_visual_review_docs.py
    git commit -m "docs(report-slides): define PPTX visual review evidence"

---

### Task 4: Make SKILL.md enforce the output-format branch

**Files:**
- Modify: skills/report-slides/SKILL.md
- Modify: skills/report-slides/scripts/tests/test_visual_review_docs.py

**Interfaces:**
- Consumes: the reference contract from Task 3 and validator CLI from Task 2.
- Produces: a user-facing report-slides workflow that cannot call a source preview or structure pass a final PPTX visual pass.

- [ ] **Step 1: Add skill-level contract assertions**

Extend test_visual_review_docs.py to read SKILL.md and assert that it names actual PPTX conversion, direct inspection of every post-conversion PNG, rendered_png_paths, model_vision.inspected_paths, statuses.pptx_render as authoritative, completion_allowed false for blockers, and not_applicable for both PPTX statuses when PPTX was not requested. Assert that the existing svg_to_pptx module and native editability wording remain present.

- [ ] **Step 2: Rewrite the Mandatory visual-authoring gate branch**

In section 3.1, retain the existing plan, discover, classify, reference, author, source-render, source-review, and manifest steps. Replace the generic ninth step with an explicit branch:

    if output_format is pptx:
        require statuses.svg_preview before export
        export the actual deck.pptx
        validate package structure into statuses.pptx_structure
        convert deck.pptx with LibreOffice or an equivalent office renderer
        produce one final PNG for each expected slide
        send every final PNG path to model_vision
        record statuses.pptx_render
        allow completion only when all three statuses are passed
    otherwise:
        record both PPTX statuses as not_applicable with reasons
        use statuses.svg_preview as the final visual gate

State that unavailable conversion or direct final inspection is blocked, not passed, and that the source PNG, review sheet, and structure report cannot satisfy the missing final evidence.

- [ ] **Step 3: Update the reporting contract**

In sections 3.3 and 3.4, require every completion record to include the exact field names statuses.svg_preview, statuses.pptx_structure, statuses.pptx_render, reviewed_by, inspected_paths, findings, revision_required, and review rounds. For PPTX records, require renderer.name, renderer.version, renderer.conversion_format, conversion_artifacts, rendered_png_paths, model_vision.inspected_paths, and visual_checks.

State that model_vision.inspected_paths must equal the converted PNG set, comparison_reference_paths are optional diagnostics only, and overall.authority is pptx-render for PPTX output or source-pixel for source-only output. An open finding or incomplete direct-inspection set prevents completion.

- [ ] **Step 4: Update the PPTX export section**

Keep native svg_to_pptx as the existing export command and preserve the embed mode as its disclosed fallback. Immediately after export, require separate structure validation, office conversion of the produced PPTX, direct PNG inspection, and review-record validation. Do not describe an SVG preview or PPTX object tree as a final visual check. Do not change the converter implementation or editability claims.

- [ ] **Step 5: Run the skill contract tests and pressure worker**

Run:

    pytest skills/report-slides/scripts/tests/test_validate_visual_review.py skills/report-slides/scripts/tests/test_visual_review_docs.py -q

Then rerun the PPTX authority and no-PPTX control workers from Task 1 against the updated SKILL.md and references. Expected: the pressure response states a failed pptx_render with an open converted-PNG finding and false completion; the control response states two not_applicable PPTX statuses and source-pixel authority.

- [ ] **Step 6: Complete both Terra reviews and commit**

Have Terra review the changed skill against every approved-spec acceptance criterion, then review wording for operational clarity and contradictory fallback language. Fix only SKILL.md and the named docs test, rerun both tests and both workers, then run:

    git diff --check
    git add skills/report-slides/SKILL.md skills/report-slides/scripts/tests/test_visual_review_docs.py
    git commit -m "docs(report-slides): enforce converted-PPTX visual gate"

---

### Task 5: Add deterministic fixture records and real converted-PPTX visual cases

**Files:**
- Create: tests/fixtures/report-slides-pptx-visual-review/README.md
- Create: tests/fixtures/report-slides-pptx-visual-review/fixture_manifest.yaml
- Create: the six concrete fixture subtrees listed in the File Map
- Create: skills/report-slides/scripts/tests/test_visual_review_fixtures.py

**Interfaces:**
- Consumes: the source rendering/export commands and validator from Tasks 2–4.
- Produces: six auditable cases whose records distinguish source pixels, PPTX structure, converted PNGs, and direct model_vision evidence.

- [ ] **Step 1: Write the fixture contract test**

Create test_visual_review_fixtures.py with a typed parametrization over these exact case IDs:

    clean-two-slide
    native-text-reflow
    connector-endpoint-drift
    image-crop-regression
    missing-image-relationship
    unreadably-small-text

For each case, load review.json through validate_review_record and assert the expected statuses from fixture_manifest.yaml. Assert that every PPTX case records a deck.pptx path, at least one conversion artifact, one rendered PNG per expected slide, and an equal model_vision.inspected_paths list only when pptx_render is passed. Assert that failure fixtures retain their finding under the gate where it was observed.

- [ ] **Step 2: Author the clean two-slide source fixture**

Use direct SVG with a 1200 by 675 viewBox. Slide 1 contains a title, a three-node pipeline, readable labels, and correctly attached connectors. Slide 2 contains an editable text box and a required image with its subject fully inside the intended crop. Render both source SVGs to source PNGs, export them with python3 -m svg_to_pptx, convert the resulting deck.pptx through LibreOffice, and inspect both converted PNGs directly with model_vision.

Write review.json with svg_preview passed, pptx_structure passed, pptx_render passed, identical final rendered_png_paths and model_vision.inspected_paths, empty findings, renderer metadata, and overall authority pptx-render.

- [ ] **Step 3: Author the five regression fixtures with controlled defects**

Create the following source-to-delivery differences and retain the source PNG, deck.pptx, converted PNG, and review record for each:

    native-text-reflow:
        source text is one line; converted PPTX wraps or truncates it.
        finding kind is text-reflow on slide 1.

    connector-endpoint-drift:
        source connector terminates on the target shape; converted PNG moves
        the endpoint away from that shape.
        finding kind is connector-drift on slide 1.

    image-crop-regression:
        source crop includes the required subject; converted PNG clips the
        subject or applies the wrong crop.
        finding kind is crop on slide 1.

    missing-image-relationship:
        source and source PNG contain the required image; the PPTX package
        loses the relationship and the converted PNG omits the image.
        pptx_structure is failed with an open missing-image finding, and any
        independently observed render consequence remains under pptx_render.

    unreadably-small-text:
        source text is readable at presentation scale; converted PNG renders
        it below the readable threshold.
        finding kind is unreadably-small-text on slide 1.

Each failed visual record sets revision_required true for the failed gate, keeps all unrelated gate evidence in its original status field, and sets overall.completion_allowed false. Do not repair a fixture by editing its review record without a new source/export/conversion/inspection round.

- [ ] **Step 4: Write fixture_manifest.yaml with expected evidence**

Use schema_version 1 and one entry per case. Each entry must state deck_id, output_format pptx, expected_slides, source_artifacts, artifacts.pptx, artifacts.review_record, expected statuses, expected finding kind, renderer conversion format, and expected completion_allowed. Use the exact relative paths from the File Map; do not use generated timestamps or environment-dependent renderer versions as expected values.

- [ ] **Step 5: Run conversion, direct inspection, and fixture validation**

For each fixture, run the actual export and office conversion command from Task 3 against the case's deck.pptx. Record the detected renderer version in review.json. Have model_vision inspect every converted PNG path separately; a review sheet can be created with the existing render_review_sheet.py only as a supplemental comparison.

Run:

    pytest skills/report-slides/scripts/tests/test_visual_review_fixtures.py -q
    for record in tests/fixtures/report-slides-pptx-visual-review/*/review.json; do
      python3 skills/report-slides/scripts/validate_visual_review.py --record "$record" --root tests/fixtures/report-slides-pptx-visual-review
    done

Expected: the clean case validates with exit 0; failed and blocked cases validate their evidence and reject any attempt to claim completion. The visual evaluations must show that source SVG similarity cannot mask the five converted-PPTX defects.

- [ ] **Step 6: Complete Terra visual and contract reviews**

Terra first checks that each converted PNG was visually inspected and that the reported finding is visible in the delivered representation. Terra then checks the record fields, status independence, and blocker/revision semantics. Correct fixture source or evidence, never the status text alone, when a review finds a mismatch. Rerun conversion, direct inspection, and tests after each correction.

- [ ] **Step 7: Commit the fixture task**

Because PPTX files are ignored outside the repository's example exception, force-add only the six PPTX fixture files named in the File Map together with their allowlisted source, PNG, JSON, manifest, README, and test paths:

    git diff --check
    git add tests/fixtures/report-slides-pptx-visual-review/README.md tests/fixtures/report-slides-pptx-visual-review/fixture_manifest.yaml skills/report-slides/scripts/tests/test_visual_review_fixtures.py
    git add -f tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/deck.pptx tests/fixtures/report-slides-pptx-visual-review/native-text-reflow/deck.pptx tests/fixtures/report-slides-pptx-visual-review/connector-endpoint-drift/deck.pptx tests/fixtures/report-slides-pptx-visual-review/image-crop-regression/deck.pptx tests/fixtures/report-slides-pptx-visual-review/missing-image-relationship/deck.pptx tests/fixtures/report-slides-pptx-visual-review/unreadably-small-text/deck.pptx
    git commit -m "test(report-slides): add converted-PPTX visual fixtures"

Expected: git diff --cached --name-only contains only fixture and test paths in this task.

---

### Task 6: Produce the GREEN pressure eval and final status contract

**Files:**
- Modify: evals/report-slides-pptx-visual-review/after.md
- Modify: evals/report-slides-pptx-visual-review/scenarios.yaml

**Interfaces:**
- Consumes: final SKILL.md, focused references, validator, tests, and fixture records.
- Produces: fresh model behavior evidence that the converted-PPTX PNG gate is authoritative and the no-PPTX path remains unchanged.

- [ ] **Step 1: Rerun both scenarios with fresh read-only workers**

Use the same worker command form and scenario text as Task 1, but capture:

    /tmp/report-slides-pptx-visual-review-green-authority.txt
    /tmp/report-slides-pptx-visual-review-green-source-only.txt

Workers may read only skills/report-slides/SKILL.md, skills/report-slides/references/visual-review.md, and skills/report-slides/references/diagram-workflow.md. They must not read the rubric, baseline, fixture records, or implementation source.

- [ ] **Step 2: Score the GREEN pressure response**

The PPTX response passes only if it states all of the following: source preview passed; PPTX structure passed; converted render failed; the open finding is text-reflow on the converted slide-2 PNG; overall.completion_allowed is false; the final authority is pptx-render; the source SVG and structure pass are not substitutes; and a new export, conversion, and direct inspection are required.

- [ ] **Step 3: Score the GREEN no-PPTX control response**

The source-only response passes only if it states svg_preview passed, both PPTX statuses not_applicable with non-empty reasons, source-pixel authority, completion_allowed true, and no office conversion attempt. A response that blocks solely because an office renderer is absent fails this control.

- [ ] **Step 4: Record raw-output provenance and Terra scores**

Write after.md with the two exact raw paths, SHA-256 values, worker command, response text, requirement-by-requirement scores, observed failure patterns, fixture validation command output summary, and the final comparison to baseline.md. Do not copy renderer versions, timestamps, or status values from the design-spec example.

- [ ] **Step 5: Run the final Terra reviews**

Run a full specification review against all ten acceptance criteria, followed by a separate document-quality review of the skill, references, eval, validator, tests, and fixture records. Expected: both return APPROVED. Any finding requires a targeted correction, the affected tests and pressure worker rerun, and another pair of Terra reviews.

- [ ] **Step 6: Commit the GREEN eval**

Run:

    git diff --check
    git add evals/report-slides-pptx-visual-review/scenarios.yaml evals/report-slides-pptx-visual-review/after.md
    git commit -m "test(report-slides): verify PPTX visual review pressure gate"

Expected: only the two eval files are staged.

---

### Task 7: Perform final verification and handoff

**Files:**
- None.

**Interfaces:**
- Consumes: all implementation-task commits and verification outputs.
- Produces: evidence that the complete change stays inside the allowed scope and satisfies the approved design.

- [ ] **Step 1: Run the focused implementation tests**

Run:

    pytest skills/report-slides/scripts/tests/test_validate_visual_review.py skills/report-slides/scripts/tests/test_visual_review_docs.py skills/report-slides/scripts/tests/test_visual_review_fixtures.py -q

Expected: every focused test passes, including all eight contract scenarios, record-validation rejection cases, documentation assertions, and six fixture cases.

- [ ] **Step 2: Validate the clean and blocked fixture records**

Run:

    python3 skills/report-slides/scripts/validate_visual_review.py --record tests/fixtures/report-slides-pptx-visual-review/clean-two-slide/review.json --root tests/fixtures/report-slides-pptx-visual-review
    python3 skills/report-slides/scripts/validate_visual_review.py --record tests/fixtures/report-slides-pptx-visual-review/native-text-reflow/review.json --root tests/fixtures/report-slides-pptx-visual-review

Expected: clean returns 0 with completion_allowed true; the regression returns 1 and names the open PPTX-render finding.

- [ ] **Step 3: Run the full report-slides script suite**

Run:

    pytest skills/report-slides/scripts/tests -q

Expected: the pre-existing tests and the new focused tests pass together.

- [ ] **Step 4: Run scope and documentation checks**

Run:

    git diff --check
    git diff --name-only base..HEAD
    rg -n "statuses\\.svg_preview|statuses\\.pptx_structure|statuses\\.pptx_render|rendered_png_paths|model_vision\\.inspected_paths|completion_allowed|not_applicable|blocked" skills/report-slides/SKILL.md skills/report-slides/references/visual-review.md skills/report-slides/references/diagram-workflow.md evals/report-slides-pptx-visual-review tests/fixtures/report-slides-pptx-visual-review

Expected: every changed path is in the File Map, no whitespace errors exist, all contract tokens are present, and no source-only instruction invokes a PPTX renderer.

- [ ] **Step 5: Complete the final Terra sign-off**

Terra verifies the implementation against the approved spec line by line, checks that the final converted PNG is the authority for PPTX, checks that blocked evidence cannot pass, checks that each gate retains independent evidence, and checks that the no-PPTX source path remains available. Require APPROVED from both specification and quality reviews.

- [ ] **Step 6: Confirm the implementation handoff**

Report the focused test command, fixture validation results, GREEN pressure-eval result, final Terra approvals, changed-path list, and the exact implementation commit subjects. Do not report PPTX completion for any fixture whose final converted PNG inspection is blocked or failed.

## Acceptance Criteria

The implementation is accepted only when all of these are evidenced:

1. A PPTX-requested report-slides run reviews source SVG, subfigure, and complete-slide pixels before export and records statuses.svg_preview.
2. The run validates PPTX package structure separately as statuses.pptx_structure; structure status is never used as visual evidence.
3. The run converts the actual PPTX to PNGs through LibreOffice PDF/PNG or an equivalent available office renderer and records renderer metadata and output paths.
4. model_vision directly inspects every post-conversion PNG, and those exact paths appear under statuses.pptx_render.model_vision.inspected_paths.
5. The converted-PPTX render is the authoritative final visual gate; SVG remains an early diagnostic and optional comparison reference.
6. Clipping, overlap, text reflow, connector drift, crop, unreadably small text, missing image, or another PPTX-only layout regression sets statuses.pptx_render to failed and requires revision.
7. Missing PPTX conversion or final visual inspection sets statuses.pptx_render to blocked, sets overall.completion_allowed false, and prevents a completion claim.
8. A non-PPTX request keeps the existing source-pixel gate final and sets both PPTX-specific statuses to not_applicable with reasons.
9. Review records preserve separate gate evidence, direct paths, findings, renderer metadata, review rounds, blocker details, and revision semantics.
10. Deterministic tests and fixture evaluations cover passing and failing PPTX-only cases, unavailable renderer, incomplete direct inspection, missing expected slide, independent status preservation, revision cycles, and the unchanged source-only path.

## Plan Self-Review

- Every future-modified file is named in the File Map with a section or symbol boundary.
- Every task has a Files block, Interfaces block, checkbox steps, commands, expected outcomes, and an independent verification cycle.
- Every contract test names its expected status, finding, path, and completion result.
- Every fixture has a concrete defect or clean outcome and a concrete review-record path.
- The source-only branch never depends on office-renderer availability.
- The validator never claims that path existence proves model_vision inspection.
- The plan contains no open-ended implementation decision, unassigned file, or unrecorded acceptance criterion.

## Execution Handoff

Plan complete and saved to docs/superpowers/plans/2026-08-03-report-slides-pptx-visual-review.md. Two execution options are available:

1. Subagent-driven execution: use superpowers:subagent-driven-development, dispatching one bounded worker per task with Terra review between tasks.
2. Inline execution: use superpowers:executing-plans and execute the tasks in order with the listed review checkpoints.

