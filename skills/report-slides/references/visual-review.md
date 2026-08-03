# Visual review

## Render before review

Render every individual visual or subfigure and every complete slide to PNG or
JPEG before review. Inspect the visible pixels with model vision at both levels;
do not infer visual quality from SVG markup, source code, manifest fields, or a
PPTX object tree. A review sheet may arrange already-rendered images, but it
does not replace inspection of those images.

Review the subfigure and complete-slide renders after every revision. Preserve
the failing render when a finding needs diagnosis.

## PPTX visual review: converted-PPTX authority

Source-pixel review above is a required early diagnostic for a PPTX request,
not the final visual gate. When PPTX output is requested, this exact sequence
runs after the source-pixel decision:

```
source subfigure and complete-slide PNG review
-> source-pixel decision
-> actual PPTX export
-> independent PPTX package validation
-> office-renderer conversion of the actual PPTX
-> one PNG for every expected slide
-> direct model_vision inspection of every final PNG
-> authoritative pptx_render decision
```

Each stage records an independent status: `statuses.svg_preview`,
`statuses.pptx_structure`, and `statuses.pptx_render`. Every status is one of
`passed`, `failed`, `blocked`, or `not_applicable`; `in_progress` is never a
valid completion value. `overall.completion_allowed` is derived from all three
statuses for a PPTX request — it is never set independently of them.

Source PNGs and any comparison references remain diagnostic only.
`statuses.pptx_structure` validates the PPTX package (relationships, editable
objects, image references); it does not inspect visual placement, so a
structural pass never establishes that anything looks correct. Only
`statuses.pptx_render` — direct model_vision inspection of the converted PPTX
pixels — is authoritative for final visual completion. A PPTX-only clipping,
overlap, text reflow, connector drift, crop, unreadably small text, missing
image, z-order, alignment, margin, or other layout regression fails
`pptx_render` even when both the source review and the structure validation
passed; neither passing status may be used to override or substitute for a
`pptx_render` finding.

Convert the actual exported PPTX — never the source SVG — with LibreOffice or
an equivalent available office renderer:

```bash
python3 -m svg_to_pptx --slides docs/slides/reports/2026-08-03_pptx-review-gate \
    --out docs/slides/reports/2026-08-03_pptx-review-gate/deck.pptx
mkdir -p docs/slides/reports/2026-08-03_pptx-review-gate/renders/pptx/libreoffice
libreoffice --headless --convert-to pdf \
    --outdir docs/slides/reports/2026-08-03_pptx-review-gate/renders/pptx/libreoffice \
    docs/slides/reports/2026-08-03_pptx-review-gate/deck.pptx
pdftoppm -png -r 150 \
    docs/slides/reports/2026-08-03_pptx-review-gate/renders/pptx/libreoffice/deck.pdf \
    docs/slides/reports/2026-08-03_pptx-review-gate/renders/pptx/libreoffice/slide
```

Record the renderer's actual name, version, and conversion format, the PDF
path when one was produced, and every final PNG path — never the example
values above. If an equivalent office renderer is used instead, record its
actual identity and output format the same way. `model_vision` must inspect
each final PNG directly; a review sheet built with
`render_review_sheet.py` may sit alongside the final PNGs for easier
comparison, but it is supplemental evidence and never substitutes for the
individual PNG paths in `model_vision.inspected_paths`. If neither LibreOffice
nor an equivalent renderer can open the produced PPTX, record `blocked` and
stop — do not fall back to the source render or the structure result.

## Subfigure gate

The subfigure passes only when all of these are true:

- semantic content is correct and complete;
- reading order and visual hierarchy are clear;
- connector direction, attachment, and crossings are correct;
- labels, legends, scale, and proportions are placed and readable;
- visual focus is intentional and decoration is necessary; and
- generated imagery has no artifacts, fake text, or misleading structures.

## Complete-slide gate

The complete slide passes only when all of these are true:

- density and balance support the narrative;
- alignment, spacing, and margins are consistent;
- typography is readable on a projected screen;
- contrast is sufficient and meaning is not carried by color alone;
- styling matches the deck and equivalent visuals; and
- there is no clipping, overlap, overflow, or unintended empty region.

The following conditions always fail the gate:

- clipped, overlapping, truncated, or unreadably small text;
- arrows with incorrect direction or connectors crossing unrelated nodes;
- chart marks that disagree with their source data;
- color as the only carrier of meaning;
- fake text or misleading scientific structure in generated imagery;
- inconsistent styling among equivalent visual elements;
- a modified reused visual without region-level change disclosure; and
- undisclosed rasterization of information expected to be editable.

## Revision loop

For every failed finding, identify the responsible source file or layer and
revise it. Re-render both the subfigure and complete slide, then inspect both
pixel outputs again. Continue until both gates pass. Keep the source, manifest,
and review record aligned with the final render; remove temporary review marks
from the delivered slide.

## Review record

Write `review.json` beside the deck artifacts. For a PPTX request, it carries
the three independent statuses and every direct evidence path. This example
shows the required separation, including a failed round followed by a
corrected round — populate every field from the current run; never copy this
example's timestamps, renderer version, or status values:

```json
{
  "schema_version": 1,
  "deck_id": "pptx-review-gate-example",
  "output_format": "pptx",
  "expected_slides": [1, 2],
  "source_artifacts": ["slides/slide-01.svg", "slides/slide-02.svg"],
  "artifacts": {
    "pptx": "deck/pptx-review-gate-example.pptx",
    "review_record": "review.json"
  },
  "statuses": {
    "svg_preview": {
      "status": "passed",
      "round": 2,
      "reviewed_by": "model_vision",
      "inspected_paths": ["renders/source/slide-01.png", "renders/source/slide-02.png"],
      "findings": [],
      "revision_required": false,
      "started_at": "2026-08-03T09:00:00Z",
      "completed_at": "2026-08-03T09:04:00Z"
    },
    "pptx_structure": {
      "status": "passed",
      "round": 2,
      "reviewed_by": "pptx_structure_validator",
      "inspected_paths": ["deck/pptx-review-gate-example.pptx"],
      "findings": [],
      "revision_required": false,
      "started_at": "2026-08-03T09:05:00Z",
      "completed_at": "2026-08-03T09:05:30Z"
    },
    "pptx_render": {
      "status": "passed",
      "round": 2,
      "reviewed_by": "model_vision",
      "inspected_paths": ["renders/pptx/libreoffice/slide-01.png", "renders/pptx/libreoffice/slide-02.png"],
      "findings": [],
      "revision_required": false,
      "started_at": "2026-08-03T09:06:00Z",
      "completed_at": "2026-08-03T09:09:00Z",
      "renderer": {
        "name": "LibreOffice",
        "version": "25.2.3.2",
        "conversion_format": "pdf-to-png"
      },
      "conversion_artifacts": ["renders/pptx/libreoffice/pptx-review-gate-example.pdf"],
      "rendered_png_paths": ["renders/pptx/libreoffice/slide-01.png", "renders/pptx/libreoffice/slide-02.png"],
      "model_vision": {
        "inspected_paths": ["renders/pptx/libreoffice/slide-01.png", "renders/pptx/libreoffice/slide-02.png"],
        "comparison_reference_paths": ["renders/source/slide-01.png", "renders/source/slide-02.png"]
      },
      "visual_checks": {
        "clipping": "passed", "overlap": "passed", "text_reflow": "passed",
        "connector_drift": "passed", "crop": "passed", "unreadably_small_text": "passed",
        "missing_image": "passed", "other_layout_regressions": "passed"
      }
    }
  },
  "overall": {
    "status": "passed",
    "completion_allowed": true,
    "authority": "pptx-render"
  },
  "history": [
    { "round": 1, "result": "failed", "revision": "Corrected native text box sizing before re-export." },
    { "round": 2, "result": "passed", "revision": "Re-exported, reconverted, and directly re-inspected both final PNGs." }
  ]
}
```

`blocker` is required whenever a status is `blocked`, naming the missing
capability or artifact and its effect; `reason` is required whenever a status
is `not_applicable`, naming the output contract that excludes the gate.
`revision_required` is `true` for a `failed` status and `false` for a `passed`
status.

### Finding fields

Every entry in a gate's `findings` list is a mapping with exactly these
fields:

| Field | Requirement |
|---|---|
| `kind` | One of `clipping`, `overlap`, `text-reflow`, `connector-drift`, `crop`, `unreadably-small-text`, `missing-image`, `z-order`, `alignment`, or `other`. No other value is accepted. |
| `scope` | A mapping naming at least the affected `slide`, and a `region` when known. |
| `artifact_path` | The rendered or source artifact where the finding is visible. |
| `description` | A concrete, specific observation — not a generic quality label. |
| `source` | One of `svg-preview`, `pptx-structure`, or `pptx-render`: the gate that observed the finding. |
| `disposition` | One of `open`, `fixed`, or `rechecked`. |

A `failed` status requires at least one finding with `disposition: open`.
A `passed` status must not retain any `open` finding. State every field by
name — a prose description of the defect is not a substitute for the
literal `kind` value. For example, a failed `pptx_render` round with a
converted-only text overflow records:

```json
"findings": [
  {
    "kind": "text-reflow",
    "scope": { "slide": 2, "region": "title" },
    "artifact_path": "renders/pptx/libreoffice/slide-02.png",
    "description": "The native textbox width estimate is narrower than the actual rendered run, so the title overruns the slide's right edge instead of remaining a single fully visible line.",
    "source": "pptx-render",
    "disposition": "open"
  }
]
```

**Source-only record rule (adjacent to the example above):** when PPTX was
not requested, both `statuses.pptx_structure` and `statuses.pptx_render` are
`not_applicable` with an explicit, non-empty `reason`, `overall.authority` is
`source-pixel`, and `statuses.svg_preview` alone decides
`overall.completion_allowed`. Do not invoke LibreOffice or any other office
renderer for a source-only request.

Source-markup inspection is not visual review. Structural manifest validation,
PPTX package validation, and pixel review (source or converted) are always
separate completion signals — never collapsed into one generic status.

## Blocked review

Missing rendering, missing vision capability, unavailable required tools, or an
environment failure that prevents inspection is an explicit blocker. Missing
factual inputs is also a blocker for the affected visual. Record the blocker,
retain any failing render, and do not mark `review.json` as passed, export the
visual as final, or call the deck complete. A blocked review must resume with
the missing evidence or capability; it is not completion.
