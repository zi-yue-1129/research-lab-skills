# Diagram workflow

## Required outputs

For every non-trivial visual, produce these artifacts before calling the visual
complete:

- a deck-level `diagram-plan.yaml` entry and a subfigure brief;
- a project-local asset directory under
  `docs/slides/assets/diagrams/<diagram_id>/` when the visual is reusable;
- the selected route's source files and a complete `manifest.yaml`;
- rendered subfigure and complete-slide previews;
- `review.json` for the latest passing render; and
- a completion record covering reuse, editability, review, and export checks.

The plan fixes the semantic regions and renderer before drawing. A source file
or manifest is not a substitute for rendered-pixel review.

## Diagram plan schema

Create `diagram-plan.yaml` beside the deck's slide outputs. The tested minimum
schema is:

```yaml
schema_version: 1
deck_id: weekly-progress
visuals:
  - diagram_id: training-pipeline
    slide: 4
    purpose: Explain the publishing gate.
    regions: [ingestion, training, evaluation-stage, publishing]
    route: native
    editability: native
    reuse:
      action: modify
      asset_id: training-pipeline
```

`deck_id` and every `diagram_id` use non-empty kebab-case. Each visual has a
positive slide number, a non-empty purpose, and a non-empty list of unique
region names. `route` is one of `native`, `data`, `generative`, or `hybrid`.
`editability` is one of `native`, `hybrid`, or `raster`. `reuse.action` is one
of `create`, `reuse`, `modify`, or `derive`.

`create` must omit `asset_id`. The other actions require a kebab-case
`asset_id`; for `reuse` and `modify` it must equal `diagram_id`, while `derive`
may name the earlier asset that supplied the source semantics.

## Diagram brief

Before drawing, answer all seven questions for each non-trivial visual:

1. What should the audience understand after viewing it?
2. Which subfigures or named regions are required?
3. What is the intended reading order?
4. Which elements represent facts, measured data, or precise structure?
5. Which elements may be interpreted freely by a generative image model?
6. Which elements must remain individually editable in PowerPoint?
7. Does the project asset library already contain the same semantic visual?

Use region names that can be located in a render, such as `input`,
`processing`, `model`, `evaluation-stage`, `output`, or `monitoring`. Do not
start with decoration before the semantic structure and route are decided.

## Asset discovery and identity

Search the project's `manifest.yaml` files by purpose, diagram type, and
semantic regions before creating a visual. Assets are project-local; do not
create a cross-project library. `diagram_id` identifies the semantic visual,
not a slide number, file name, or placement. Git history supplies revisions;
the asset directory does not copy every revision.

Use these observable identity predicates:

- Same core message and same model, with changed content or layout: modify the
  same ID and set `based_on_revision`.
- If either the core message or model changes: derive a new ID and set
  `derived_from` to the earlier asset.
- Only slide placement changed: reuse the asset unchanged.

## Manifest contract

Every reusable visual declares all fields below. This hybrid example shows the
full Task 2 contract, including route-specific generation provenance:

```yaml
schema_version: 1
diagram_id: researcher-lab
purpose: Explain how researchers and AI systems share an evaluation loop.
diagram_type: conceptual
authoring_route: hybrid
editability: hybrid
source_files:
  - overlay.svg
used_in:
  - deck: weekly-progress
    slide: 4
derived_from: null
based_on_revision: null
changes: []
generation:
  prompt: prompt.md
  output: generated.png
  references:
    - source-reference.png
review:
  status: passed
  artifact: review.json
```

The fields have these constraints:

- `schema_version` is `1`.
- `diagram_id` is kebab-case and matches its asset directory.
- `purpose` is a non-empty explanation. `diagram_type` is one of
  `architecture`, `flowchart`, `timeline`, `statistical`, `conceptual`,
  `hybrid`, or `status`.
- `authoring_route` is one of `native`, `data`, `generative`, or `hybrid`.
- `editability` is `native`, `hybrid`, or `raster`.
- `source_files` is a non-empty list of existing relative paths that stay
  inside the asset directory. A native route includes an SVG; a data route
  includes both `data.json` and an SVG; a hybrid route includes an editable SVG
  overlay.
- `used_in` contains `deck` and a positive `slide` for each use site.
- `derived_from` and `based_on_revision` are strings or `null`.
- `changes` is a list of entries with non-empty `region`, `change`, and
  `reason`. An optional `bbox` is `[x1, y1, x2, y2]` in the `1200 x 675`
  slide coordinate system, with finite values satisfying
  `0 <= x1 < x2 <= 1200` and `0 <= y1 < y2 <= 675`.
- `review.status` is `draft`, `failed`, or `passed`. A passed review must name
  an existing relative `review.artifact`.

For `generative` and `hybrid` routes, `generation` is a mapping with an
existing relative `prompt` file, an existing relative `output` ending in
`.png` or `.jpg`, and a list of relative `references`. A new generated visual
may have an empty reference list. If `based_on_revision` is set or `changes`
is non-empty on a generative or hybrid asset, `generation.references` must be
non-empty. For `native` and `data` routes, set `generation: null`.

## Reuse modify or derive

Use the plan action that matches the identity decision:

| Action | Source decision | Required provenance |
|---|---|---|
| `reuse` | Same semantic visual and no source change | Keep the ID and source unchanged. |
| `modify` | Same core message and same model with a requested revision | Keep the ID, set `based_on_revision`, and list changed regions. |
| `derive` | Either the core message or model changed, based on an earlier visual | Use a new ID and set `derived_from`. |
| `create` | No suitable project asset exists | Use a new ID and omit `asset_id` in the plan. |

Do not redraw an equivalent visual solely to change its slide placement.
Search and reuse happen before route-specific generation.

## Change disclosure

Record each modified region and its reason in the manifest. Use a Git revision
or other durable source reference in `based_on_revision`, for example:

```yaml
based_on_revision: git:4b29f2a
changes:
  - region: evaluation-stage
    bbox: [760, 180, 1080, 420]
    change: Added the human-review branch and failure return path.
    reason: Publishing now requires explicit manual approval.
```

The delivery summary repeats the reused source and every changed region with
its reason. A temporary diff outline may be used during review, but it is
removed from the final slide.

## Validation commands

Run the validator from the project root for each target:

```bash
python3 skills/report-slides/scripts/validate_diagram_manifest.py \
  --plan docs/slides/reports/<deck>/diagram-plan.yaml

python3 skills/report-slides/scripts/validate_diagram_manifest.py \
  --manifest docs/slides/assets/diagrams/<diagram_id>/manifest.yaml

python3 skills/report-slides/scripts/validate_diagram_manifest.py \
  --root docs/slides/assets/diagrams
```

To assemble already-rendered PNG or JPEG previews into a review sheet, repeat
`--input` for each image:

```bash
python3 skills/report-slides/scripts/render_review_sheet.py \
  --input docs/slides/reports/<deck>/subfigure.png \
  --input docs/slides/reports/<deck>/slide04-review.png \
  --out docs/slides/reports/<deck>/review-sheet.png \
  --columns 2 --cell-width 600 --cell-height 338
```

The validator reports every issue as `ERROR <path>:<field>: <message>` and
returns exit code `1`; a successful run identifies whether plan, manifest, or
library validation passed. The review-sheet utility accepts rendered PNG/JPEG
inputs only.

## Completion record

Report one record per visual with:

- `diagram_id`, diagram type, and slide location;
- selected authoring route and editability level;
- action: created, reused, modified, or derived;
- reused source and each changed region with its reason;
- the three independent statuses — `statuses.svg_preview`,
  `statuses.pptx_structure`, `statuses.pptx_render` — never collapsed into one
  generic status;
- for a PPTX deliverable, the direct converted PNG paths under
  `statuses.pptx_render.rendered_png_paths` and the identical set model_vision
  inspected under `statuses.pptx_render.model_vision.inspected_paths`,
  renderer metadata (`renderer.name`, `renderer.version`,
  `renderer.conversion_format`) and `conversion_artifacts`;
- review-round count per gate, every finding (`kind`, `scope`,
  `artifact_path`, `source`, `disposition`), and `revision_required`; and
- any remaining raster layers and why they remain raster, and any `blocked`
  status with its exact blocker or `not_applicable` status with its reason.

Do not collapse render review, PPTX structure, and post-export rendering into a
single generic status. `overall.completion_allowed` follows only from the
three independent statuses (`pptx-render` authority for a PPTX request,
`source-pixel` authority otherwise) — never assert completion from a subset of
them.

Validate a review record deterministically before reporting it complete:

```bash
python3 skills/report-slides/scripts/validate_visual_review.py \
  --record docs/slides/reports/2026-08-03_pptx-review-gate/review.json \
  --root docs/slides/reports/2026-08-03_pptx-review-gate
```

This validator checks the record's shape — required fields, status
independence, path safety, and the derived `overall` result — and rejects a
record whose `model_vision.inspected_paths` do not exactly match the final
converted PNG set. It does not replace direct model_vision inspection of the
rendered pixels themselves: a structurally valid record can still describe a
run where the required inspection never happened, if the runtime lied about
which paths it inspected. `render_review_sheet.py` remains the supplemental,
unchanged tool for assembling already-rendered PNG/JPEG previews into one
comparison sheet; it never substitutes for the individual paths validated
above.
