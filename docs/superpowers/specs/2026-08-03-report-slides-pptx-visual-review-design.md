# Report Slides PPTX Visual Review Gate - Design Spec

- **Date:** 2026-08-03
- **Status:** Approved
- **Approach:** Option A: source-pixel diagnostics followed by an authoritative converted-PPTX visual gate
- **Version:** 1.0

## Goal

Define a deterministic completion gate for report-slides tasks that request PPTX
output. Source SVG, subfigure, and complete-slide pixel renders remain required
early checks for semantic correctness, style, hierarchy, and source layout.
After those checks pass, the workflow exports the PPTX, validates its structure,
converts the actual PPTX to pixels with LibreOffice PDF/PNG or an equivalent
available office renderer, and requires model_vision to inspect the resulting
PNG files themselves.

The converted-PPTX render is the authoritative final visual gate. The source
SVG is a diagnostic and reference comparison only; it cannot establish that
the delivered PPTX is visually correct. A PPTX-only defect fails the gate even
when the source SVG preview and PPTX structure validation pass.

When PPTX output is not requested, the existing source-pixel review remains the
final visual gate and the PPTX-specific statuses are explicitly marked
not_applicable.

## Non-goals

- This design does not replace semantic or style review of source subfigures and
  complete-slide renders.
- This design does not require one particular office renderer when an available
  equivalent can open the produced PPTX and rasterize every slide.
- This design does not define a new SVG-to-PPTX conversion implementation or
  change the existing converter's editability contract.
- This design does not use source SVG pixels as a substitute for converted-PPTX
  pixels, including when the source and PPTX appear visually similar.
- This design does not require pixel-for-pixel identity between SVG and PPTX
  renders. It requires that the converted PPTX preserve the intended semantic
  and visual result at presentation scale.
- This design does not add animations, transitions, speaker notes, or unrelated
  presentation-authoring features.
- This design does not allow a contact sheet, source screenshot, or structural
  report to substitute for direct inspection of each final PPTX PNG.

## Design principles

1. Inspect the delivered representation. A requested PPTX is complete only
   after the actual PPTX has been converted and its rendered pixels have been
   inspected.
2. Keep gate dimensions separate. SVG preview, PPTX structure, and PPTX render
   results answer different questions and must remain separate fields.
3. Treat unavailable evidence as blocked. Missing conversion or visual
   inspection capability is an environment blocker, not a passing result.
4. Revise the responsible source. A failed converted render requires a revision
   and a fresh export, conversion, and inspection cycle.
5. Preserve the no-PPTX path. A task that does not request PPTX continues to
   finish at the existing source-pixel gate.

## Status model

Each review record contains these independent statuses:

| Field | Meaning when PPTX is requested | Meaning when PPTX is not requested |
|---|---|---|
| statuses.svg_preview | Source subfigure and complete-slide pixels were reviewed before PPTX export. | Existing final source-pixel gate. |
| statuses.pptx_structure | The produced PPTX package and required editable or asset structure were validated. | not_applicable. |
| statuses.pptx_render | The produced PPTX was converted to pixels and every final PNG was inspected by model_vision. | not_applicable. |

The persisted status values are:

- passed: the evidence for that gate exists and all required checks passed;
- failed: evidence exists and a review or validation finding requires revision;
- blocked: a required capability, artifact, or inspection step was unavailable
  or could not be completed;
- not_applicable: the gate is intentionally outside the requested output
  contract, used only for PPTX-specific gates when PPTX was not requested.

in_progress may be used by an orchestration runtime while a run is active,
but it is not a valid completion status. A completion record must not leave a
required status unset or in progress.

The overall result is derived rather than used to collapse the three gates:

- For a PPTX request, overall.status is passed only when
  statuses.svg_preview, statuses.pptx_structure, and statuses.pptx_render are
  all passed.
- For a non-PPTX request, overall.status is passed only when
  statuses.svg_preview is passed and both PPTX statuses are not_applicable.
- Any required failed status makes the overall result failed.
- Any required blocked status makes the overall result blocked unless a failure
  is already present. The record preserves the individual status that explains
  the reason.

## Workflow and data flow

The workflow evaluates the output contract before choosing its final gate:

Request and deck brief
-> generate source SVG subfigures and complete slides
-> render source subfigures and complete slides to pixels
-> model_vision inspects source pixels
-> source-pixel decision
-> if no PPTX was requested, complete at the source-pixel gate
-> if PPTX was requested, export the actual PPTX
-> validate PPTX structure
-> convert the actual PPTX with LibreOffice or an equivalent office renderer
-> write one PNG for every PPTX slide
-> model_vision directly inspects every post-conversion PNG
-> authoritative PPTX-render decision
-> complete only when every required status is passed.

### Phase 1: Establish the review contract

The run records the deck identifier, requested output format, source artifact
paths, and expected slide numbers. output_format: pptx activates all three
gates. A source-only output leaves the PPTX gates not_applicable and uses the
existing source-pixel gate as final.

The expected slide list is authoritative for render completeness. A PPTX render
cannot pass if a slide is missing from the converted PNG set, if an expected
slide is silently omitted, or if the conversion produces an unreadable image.

### Phase 2: Review source pixels

The workflow renders each non-trivial source subfigure and each complete source
slide. model_vision inspects those pixels for:

- semantic completeness and factual fidelity;
- intended reading order and visual hierarchy;
- alignment, spacing, margins, and deck-style consistency;
- connector direction and attachment;
- typography, contrast, projected-screen readability, clipping, and overlap.

This phase is required before PPTX export for a PPTX request. A source-pixel
pass means that the source is ready to export; it does not mean that the PPTX
has passed.

### Phase 3: Validate PPTX structure

The workflow validates the actual exported PPTX package separately from its
appearance. Structural checks include:

- the package opens and contains the expected slide count;
- each expected slide has its required relationships and assets;
- expected editable text, shapes, connectors, and overlays exist;
- required image resources are present and referenced;
- declared native, hybrid, or raster editability is consistent with the
  exported object structure.

Structural validation does not inspect visual placement. A structural pass may
coexist with a failed PPTX render, and neither status may be rewritten to imply
the other.

### Phase 4: Convert and inspect the delivered PPTX

The workflow uses LibreOffice PDF/PNG conversion or an equivalent available
office renderer that opens the produced PPTX rather than the source SVG. It
records the renderer name, version, conversion result, and all conversion
artifacts. The final render set contains one inspectable PNG per expected slide.

model_vision must inspect each post-conversion PNG directly. A review sheet may
make comparison easier, but it is supplemental evidence and does not replace
the individual PNG paths in model_vision.inspected_paths.

The inspection compares the converted PPTX result with the intended source
design while judging the converted result on its own. It checks for clipping,
overlap, text reflow, connector drift, crop, unreadably small text, missing
images, incorrect z-order, broken alignment, unexpected whitespace, and any
other PPTX-only layout regression. Any such finding fails pptx_render and
requires revision.

### Phase 5: Revise and repeat

When a gate fails, the workflow identifies the responsible source or export
condition, revises it, and reruns every downstream step affected by the
revision:

- A source or semantic failure reruns source rendering, source review, PPTX
  export, structure validation, conversion, and final inspection when PPTX is
  requested.
- A structure failure reruns export and all downstream checks after the
  structural issue is corrected.
- A PPTX-render failure reruns PPTX export, structure validation, conversion,
  and direct PNG inspection. If the source changes, source review also reruns.

The workflow cannot mark the run passed by editing the review record, replacing
the converted PNG with a source render, accepting an uninspected image, or
waiving a PPTX-only defect.

## Review record fields

The review record is stored with the deck artifacts and contains enough
evidence for another reviewer to identify what was inspected and why the run
passed, failed, or blocked.

### Required top-level fields

| Field | Type | Requirement |
|---|---|---|
| schema_version | positive integer | Identifies the review-record schema. |
| deck_id | string | Stable deck identifier. |
| output_format | enum | Uses pptx when PPTX was requested; otherwise records the requested non-PPTX format. |
| expected_slides | list of positive integers | Slides that the review expects to render. |
| source_artifacts | list of relative paths | Source SVG, subfigure, and complete-slide artifacts used for the run. |
| artifacts.pptx | relative path or null | The actual exported PPTX when requested. |
| artifacts.review_record | relative path | Path to the persisted review record. |
| statuses.svg_preview | status object | Independent source-pixel status. |
| statuses.pptx_structure | status object | Independent PPTX package status. |
| statuses.pptx_render | status object | Independent converted-PPTX visual status. |
| overall | result object | Derived status and completion decision. |
| history | list of round objects | Ordered review rounds with findings and revisions. |

### Status object fields

Each status object includes:

| Field | Requirement |
|---|---|
| status | One of passed, failed, blocked, or not_applicable. |
| round | Positive review-round number. |
| reviewed_by | Records model_vision for visual gates or the named structural validator for pptx_structure. |
| inspected_paths | Relative paths directly inspected for that gate; required for visual gates that pass. |
| findings | Structured findings, including an empty list for a clean pass. |
| started_at and completed_at | Timestamps for the review interval. |
| blocker | Required for blocked, with the missing capability or artifact and its effect. |
| reason | Required for not_applicable, with the output contract that excludes the gate. |
| revision_required | Boolean; true for a failed gate that cannot be completed without revision. |

### PPTX render fields

statuses.pptx_render includes these additional fields when PPTX is requested:

| Field | Requirement |
|---|---|
| renderer.name | Renderer used to open and rasterize the PPTX, such as LibreOffice. |
| renderer.version | Detected renderer version. |
| renderer.conversion_format | Conversion path, such as pdf-to-png or direct PNG export. |
| conversion_artifacts | Relative paths to the conversion output, including PDF when one was produced. |
| rendered_png_paths | Exactly one relative PNG path for every expected slide. |
| model_vision.inspected_paths | Exactly the final PNG paths inspected directly by model_vision; a contact sheet alone is invalid. |
| model_vision.comparison_reference_paths | Optional source-pixel paths used for diagnostic comparison. These paths do not satisfy inspected_paths. |
| visual_checks | Named checks for clipping, overlap, reflow, connector drift, crop, text size, images, and other observed regressions. |

For a passing PPTX render, rendered_png_paths and
model_vision.inspected_paths contain the same set of final PNG paths. The
record may also contain a review-sheet path, but the sheet is explicitly
supplemental.

### Finding fields

Each finding contains:

| Field | Requirement |
|---|---|
| kind | One of clipping, overlap, text-reflow, connector-drift, crop, unreadably-small-text, missing-image, z-order, alignment, or other. |
| scope | Slide number and, when known, the affected region or object. |
| artifact_path | Rendered image or source artifact where the finding is visible. |
| description | Concrete observation, not a generic quality label. |
| source | svg-preview, pptx-structure, or pptx-render. |
| disposition | open, fixed, or rechecked. |

An open finding in a required gate prevents a passing status. A PPTX-render
finding remains a PPTX-render finding even when the same region looked correct
in the SVG comparison.

### Concrete record shape

The following fields show the required separation for a passing PPTX run:

    schema_version: 1
    deck_id: quarterly-training-update
    output_format: pptx
    expected_slides: [1, 2]
    source_artifacts:
      - slides/slide-01.svg
      - slides/slide-02.svg
      - slides/subfigures/training-pipeline.svg
    artifacts:
      pptx: deck/quarterly-training-update.pptx
      review_record: deck/review.json
    statuses:
      svg_preview:
        status: passed
        round: 2
        reviewed_by: model_vision
        inspected_paths:
          - renders/source/slide-01.png
          - renders/source/slide-02.png
          - renders/source/training-pipeline.png
        findings: []
        revision_required: false
      pptx_structure:
        status: passed
        round: 2
        reviewed_by: pptx_structure_validator
        inspected_paths:
          - deck/quarterly-training-update.pptx
          - deck/structure.json
        findings: []
        revision_required: false
      pptx_render:
        status: passed
        round: 2
        reviewed_by: model_vision
        inspected_paths:
          - renders/pptx/libreoffice/slide-01.png
          - renders/pptx/libreoffice/slide-02.png
        findings: []
        revision_required: false
        renderer:
          name: LibreOffice
          version: 25.2.3.2
          conversion_format: pdf-to-png
        conversion_artifacts:
          - renders/pptx/libreoffice/quarterly-training-update.pdf
        rendered_png_paths:
          - renders/pptx/libreoffice/slide-01.png
          - renders/pptx/libreoffice/slide-02.png
        model_vision:
          inspected_paths:
            - renders/pptx/libreoffice/slide-01.png
            - renders/pptx/libreoffice/slide-02.png
          comparison_reference_paths:
            - renders/source/slide-01.png
            - renders/source/slide-02.png
        visual_checks:
          clipping: passed
          overlap: passed
          text_reflow: passed
          connector_drift: passed
          crop: passed
          unreadably_small_text: passed
          missing_image: passed
          other_layout_regressions: passed
    overall:
      status: passed
      completion_allowed: true
      authority: pptx-render
    history:
      - round: 1
        result: failed
        revision: Corrected native text box sizing before re-export.

The example uses concrete artifact paths and values to demonstrate the record
contract. An implementation must populate the fields from the current run and
must not copy the example's timestamps, renderer version, or status values.

## Failure and blocker semantics

### Failed gate

failed means the workflow has evidence and found a defect. The responsible
source must be revised. The gate remains failed until the revised artifact is
rendered and inspected in a new round.

The following findings always fail the relevant visual gate:

- any clipping, overlap, or crop that changes or hides intended content;
- text reflow, truncation, line wrapping, or font substitution that changes
  the intended layout;
- connector drift, wrong attachment, wrong direction, or a new crossing that
  changes the diagram's reading path;
- unreadably small text at the intended presentation size;
- a missing, substituted, distorted, or incorrectly cropped image;
- an incorrect z-order, alignment, margin, or unexpected layout shift;
- any other PPTX-only layout regression visible in the converted PNG.

An SVG-preview pass and a PPTX-structure pass do not override a failed
PPTX-render status. A failed PPTX render requires a new PPTX export and a new
conversion before the final gate can be evaluated again.

### Blocked review

blocked means the workflow cannot obtain required evidence. It is not a
quality pass and it does not permit completion. Examples include:

- LibreOffice or an equivalent office renderer is unavailable;
- the office renderer cannot open or convert the produced PPTX;
- conversion completes without a PNG for every expected slide;
- a converted PNG is missing, unreadable, or cannot be supplied to model_vision;
- model_vision is unavailable or cannot inspect the final PNG itself;
- the run records only a contact sheet or source SVG for the final gate;
- a required structural artifact is unavailable for the PPTX structure gate.

When conversion or visual inspection is unavailable, set
statuses.pptx_render.status to blocked, record the exact blocker, set
overall.completion_allowed to false, and stop. Do not claim the deck is
complete. The workflow may report the source and structure statuses already
obtained, but they remain non-authoritative for final visual completion.

### Not applicable

When PPTX was not requested, set both statuses.pptx_structure.status and
statuses.pptx_render.status to not_applicable, record the output contract in
their reason field, and use the source-pixel status as the final visual
decision. Do not invoke a missing PPTX renderer for a task that did not request
PPTX.

## Tests and evaluations

The implementation must include deterministic contract tests and fixture-based
visual evaluations. These tests validate status semantics; they do not replace
the required model inspection of real output pixels.

### Contract tests

1. PPTX happy path: A two-slide PPTX request with source preview, structure,
   conversion, and direct PNG inspection produces three passed statuses and
   overall.completion_allowed: true.
2. PPTX-only regression: Source preview passes and PPTX structure passes, but
   the converted slide contains text reflow. The expected result is
   pptx_render: failed, an open text-reflow finding, and
   overall.completion_allowed: false.
3. Conversion blocker: LibreOffice and the equivalent renderer are absent. The
   expected result is pptx_render: blocked, a concrete blocker message, and no
   completion claim.
4. Inspection blocker: Conversion produces two PNGs but model_vision inspects
   only one. The expected result is pptx_render: blocked; a review sheet or
   source PNG cannot satisfy the missing direct path.
5. Missing-slide blocker: The expected slide list contains slides 1 and 2,
   but conversion produces only slide-01.png. The expected result is
   pptx_render: blocked.
6. No-PPTX path: A source-only request with a passing source-pixel review sets
   both PPTX statuses to not_applicable and allows completion from the source
   gate.
7. Independent status preservation: A PPTX structure failure does not rewrite
   svg_preview; a PPTX render failure does not rewrite pptx_structure; each
   status retains its own evidence and findings.
8. Revision cycle: A failed render round followed by a corrected render creates
   a new round, closes the prior finding as fixed or rechecked, and allows
   completion only from the new converted PNG inspection.

### Fixture-based visual evaluations

The evaluation deck contains concrete cases for:

- a native text box whose line reflows only after PPTX conversion;
- a connector whose endpoint shifts away from its target shape;
- an image whose PPTX crop clips a required subject;
- a slide with a missing relationship that removes an image;
- a complete source slide that passes but becomes unreadably small after
  conversion;
- a clean two-slide deck that passes all three gates.

For each case, the evaluator records the source PNG path, PPTX path, converted
PNG path, model_vision.inspected_paths, the expected status of each gate, and
the final completion decision. The regression fixtures must demonstrate that
source SVG similarity cannot mask a PPTX-only failure.

### Record validation

Automated validation rejects a passing PPTX render when:

- renderer.name or renderer.version is missing;
- rendered_png_paths does not contain exactly one path per expected slide;
- any rendered PNG path is absent or unreadable;
- model_vision.inspected_paths does not match the final PNG set;
- the record contains only a review-sheet path for final inspection;
- a required finding is open;
- any required gate is not_applicable, unset, or still in_progress.

## Acceptance criteria

The design is accepted when all of the following are true:

1. A PPTX-requested report-slides run performs source SVG, subfigure, and
   complete-slide pixel review before export and records it as
   statuses.svg_preview.
2. The run validates PPTX package structure and records it separately as
   statuses.pptx_structure; structure status is never used as visual evidence.
3. The run converts the actual PPTX to PNGs through LibreOffice PDF/PNG or an
   equivalent available office renderer and records the renderer and output
   paths.
4. model_vision directly inspects every post-conversion PNG, and those paths
   are present under statuses.pptx_render.model_vision.inspected_paths.
5. The converted-PPTX render is the authoritative final visual gate. SVG is
   retained only as an early diagnostic and comparison reference.
6. Any clipping, overlap, text reflow, connector drift, crop, unreadably small
   text, missing image, or other PPTX-only layout regression sets
   statuses.pptx_render to failed and requires revision.
7. If PPTX conversion or final visual inspection is unavailable, the status is
   blocked, completion_allowed is false, and completion cannot be claimed.
8. If PPTX was not requested, the existing source-pixel gate remains final and
   both PPTX-specific statuses are not_applicable.
9. Review records preserve separate SVG-preview, PPTX-structure, and
   PPTX-render statuses, direct inspected paths, findings, renderer metadata,
   review rounds, and blocker or revision semantics.
10. The implementation's contract tests and fixture evaluations cover both
    passing and failing PPTX-only cases, unavailable-renderer blockers, missing
    PNG inspection, and the unchanged source-only path.
