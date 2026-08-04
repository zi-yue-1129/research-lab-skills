---
name: report-slides
description: Use when creating presentations and research reports, especially diagram-heavy decks with architecture, flowcharts, timelines, charts, conceptual illustrations, or editable PPTX output.
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Report Slides

Generates a slide deck from research log entries using three source paths:
- **[A]** `generate_slides.py` — data-driven slides (charts, tables, metrics)
- **[B]** Mermaid (`mmdc`) — diagram slides (flowcharts, architectures, state machines)
- **[C]** Claude SVG — free-form slides (conceptual layouts, text-heavy content)

Every non-trivial visual goes through the mandatory visual-authoring gate below.
After generation, slides can optionally be exported as native editable PPTX shapes,
with SVG embedding retained as the backward-compatible fallback.

---

## Setup (first use in a project)

**Resolve the slides and research-log directories first** (see
`skills/resource-resolver/SKILL.md`):

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
SLIDES_DIR=$(python "$RESOLVE" --role slides --json | python3 -c "import json,sys;print(json.load(sys.stdin).get('primary',''))")
RESEARCH_LOG_DIR=$(python "$RESOLVE" --role research_log --json | python3 -c "import json,sys;print(json.load(sys.stdin).get('primary',''))")
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
$SLIDES_DIR = (python $RESOLVE --role slides --json | ConvertFrom-Json).primary
$RESEARCH_LOG_DIR = (python $RESOLVE --role research_log --json | ConvertFrom-Json).primary
```

If either comes back empty, that role is unconfigured — follow "First-use
role confirmation" in `skills/resource-resolver/SKILL.md` before continuing.
Every `docs/slides` reference below means `$SLIDES_DIR`; every
`docs/research_log` reference means `$RESEARCH_LOG_DIR`.

**macOS / Linux / Git Bash:**
```bash
bash "$(find ~/.claude -path "*/report-slides/scripts/setup.sh" | head -1)" "$SLIDES_DIR"
```

**Windows (PowerShell):**
```powershell
& (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter setup.ps1 |
    Where-Object FullName -like "*report-slides*" | Select-Object -First 1).FullName $SLIDES_DIR
```

This copies `generate_slides.py`, `validate_diagram_manifest.py`, and `render_review_sheet.py` into `scripts/` and creates both `$SLIDES_DIR/reports/` and `$SLIDES_DIR/assets/diagrams/`. `to_pptx.py` stays in the skill bundle and is invoked directly from there.

**Auto-setup:** if you invoke `/report-slides` and `scripts/generate_slides.py` is missing, run the appropriate setup command automatically before proceeding — no need to ask the user.

Check for Mermaid (optional, for diagram slides):
```bash
# macOS / Linux
which mmdc && echo "Mermaid OK" || echo "Mermaid missing (npm i -g @mermaid-js/mermaid-cli)"
# Windows
Get-Command mmdc -ErrorAction SilentlyContinue && "Mermaid OK" || "Mermaid missing (npm i -g @mermaid-js/mermaid-cli)"
```

---

## Style system

Slides inherit colors and fonts from a **style file** — a `.md` file with YAML frontmatter.
Three built-in styles ship with this skill: `default`, `minimal`, `dark`, `paper`.
Full schema and color role descriptions are in `references/styles/STYLES.md` (read it when resolving styles).

**Project default:** if `$SLIDES_DIR/_style.md` exists it is applied automatically to every deck.

### set-style \<name\>

Copy a built-in style as the project default (one command):

```bash
# macOS / Linux / Git Bash:
bash "$(find ~/.claude -path "*/report-slides/scripts/set-style.sh" | head -1)" <name>
# Windows (PowerShell):
& (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter set-style.ps1 |
    Where-Object FullName -like "*report-slides*" | Select-Object -First 1).FullName <name>
# built-in names: default  minimal  dark  paper
```

To **create a custom style**: make `$SLIDES_DIR/styles/<name>.md` using the schema in
`references/styles/STYLES.md`, then copy it to `$SLIDES_DIR/_style.md` to activate it as the project default.

---

## Workflow

### 1. Show available logs

```bash
cat "$RESEARCH_LOG_DIR/INDEX.md" 2>/dev/null \
  || find "$RESEARCH_LOG_DIR" -maxdepth 1 -name "*.md" ! -name "INDEX.md" | sort -r | head -20
```

Show the user which entries exist and which have already been made into slide decks.
If no log files exist, tell the user to run `/research-log add` first and stop.

---

### 1b. Academic data source (optional)

When the user passes `--source academic` or selects "academic pipeline" as source:

1. Check for a passport YAML file (default: `docs/passport.yaml`; override with `--passport <path>`)
2. Run the bridge script to extract stage data:
   ```bash
   BRIDGE="$(find ~/.claude -path "*/research-lab-skills/bridge/scripts/passport_to_log.py" 2>/dev/null | head -1)"
   python3 "$BRIDGE" --passport docs/passport.yaml
   ```
3. Use the extracted stage records as input for slide generation instead of research-log entries

If no passport file exists, fall back to research-log source and notify the user.

---

### 2. Ask (one message)

1. Source? (`research-log` = experiment logs (default) / `academic` = pipeline passport data)
   If research-log: which logs? (`all` / `recent-N` / by name / date range)
   If academic: passport file path? (default: `docs/passport.yaml`)
2. Audience? (advisor / team meeting / conference)
3. Charts? (`list` = output paths to `chart_list.md` / `embed` = base64 into SVG)
4. Language? (follow log language / force English / force another language)
5. Emphasis? (progression / final results / failure analysis / let Claude decide)
6. Style? (skip = use `$SLIDES_DIR/_style.md` if present / name a built-in / `custom` to create one)

---

### 3. Read logs and propose outline

Read the selected log files and any `CLAUDE.md` for project context and baselines.

Analyze: `follows:` chains for progression, key results, failures, narrative arc.

**Propose the outline — wait for confirmation before generating:**

```
Proposed slide structure (N slides):

#01  Title                   [C]
#02  Background & Goal       [C: two_column]
#03  Experiment Timeline     [A: bullet_list] [V:DATA]
#04  Changes                 [A: bullet_list] [V:DATA]
#05  Results                 [A: bar_chart]   [V:DATA]
#06  Comparison              [A: table]       [V:DATA]
#07  Architecture            [C: native SVG]  [V:NATIVE]
#08  Conclusion & Next Steps [C: conclusion]

[A] Python  [B] Mermaid  [C] Claude SVG

Confirm? (say "ok" to proceed, or specify changes)
```

### 3.1 Mandatory visual-authoring gate

Immediately after outline confirmation, before drawing or generating any visual,
run this ordered gate for every non-trivial visual, including charts and
conceptual illustrations:

1. **Plan:** create `diagram-plan.yaml` with one entry per visual.
2. **Discover:** search project `manifest.yaml` files by purpose, diagram type,
   and semantic regions before drawing.
3. **Classify:** select exactly one route: native, data, generative, or hybrid,
   and record its route tag.
4. **Reference:** load only the relevant references below for the selected route.
5. **Author:** create or modify a reusable source; resolve reuse, modification,
   or derivation identity before route-specific generation.
6. **Render:** render both the subfigure and the complete slide to pixels.
7. **Review:** inspect both pixel renders with model vision, revise the source,
   and repeat the render/vision loop until both gates pass.
8. **Manifest:** validate the plan, each manifest, and the asset root:
   `python3 scripts/validate_diagram_manifest.py --plan <plan>`,
   `python3 scripts/validate_diagram_manifest.py --manifest <manifest>`, and
   `python3 scripts/validate_diagram_manifest.py --root <asset-root>`.
9. **output-format branch — export, convert, and directly inspect, or mark
   not applicable:**

   ```
   if output_format is pptx:
       require statuses.svg_preview passed before export
       export the actual deck.pptx
       validate package structure into statuses.pptx_structure
       convert the actual deck.pptx with LibreOffice or an equivalent
           office renderer (never the source SVG)
       produce exactly one final PNG for every expected slide under
           rendered_png_paths
       send every final PNG path directly to model_vision as
           model_vision.inspected_paths
       record statuses.pptx_render
       allow completion only when statuses.svg_preview,
           statuses.pptx_structure, and statuses.pptx_render are all passed
   otherwise:
       record both statuses.pptx_structure and statuses.pptx_render as
           not_applicable with a non-empty reason
       use statuses.svg_preview as the final, authoritative visual gate
   ```

   `statuses.pptx_render` is the authoritative final visual gate for a PPTX
   deliverable: a source SVG preview and a passing `statuses.pptx_structure`
   never override it. Unavailable conversion or unavailable/partial direct
   final-PNG inspection is `blocked`, not `passed` — a source PNG, a review
   sheet, or the structure report cannot satisfy the missing
   `model_vision.inspected_paths` evidence. A `blocked` or `failed` status on
   any required gate sets `overall.completion_allowed` to `false`.

Missing rendering or model-vision review is a hard blocker: retain the failing
artifact, record the blocker, and do not mark the visual or deck complete.

### 3.2 Visual routes and references

In `diagram-plan.yaml`, set the validator-facing `route` field. In
`manifest.yaml`, set the validator-facing `authoring_route` field. Both fields
must use exactly one enum value: `native`, `data`, `generative`, or `hybrid`.
The bracketed values below are display/report/outline tags, not validator enum
values:

| Display/report/outline tag | Route and default |
|---|---|
| `[V:NATIVE]` | Editable SVG shapes and connectors; default for architecture and flowcharts. |
| `[V:DATA]` | Deterministic data-driven SVG; default for timelines, statistical charts, and status/matrix views. |
| `[V:AI]` | Runtime-generated raster illustration for conceptual visuals when native shapes are not sufficient. |
| `[V:HYBRID]` | Runtime-generated raster base plus an editable SVG overlay for factual annotations and structure. |

Direct native SVG is the default for editable architecture and flow diagrams.
Mermaid is optional only when its output converts correctly; if conversion
loses editability, disclose that loss in the manifest and completion report.
Do not label an embedded or raster-only Mermaid result as `[V:NATIVE]`.

Read only the references needed for the selected route and gate:

- [diagram-workflow.md](references/diagram-workflow.md) — plans, manifests, identity, and completion records.
- [diagram-patterns.md](references/diagram-patterns.md) — route recipes and failure checks.
- [generative-visuals.md](references/generative-visuals.md) — runtime generation and reference edits.
- [visual-review.md](references/visual-review.md) — pixel rendering, vision review, and blockers.

### 3.3 Generation, reuse, and reporting contract

- `[V:AI]` and `[V:HYBRID]` require runtime image generation for creation or
  editing. For an edit, provide the earlier asset to the image-generation
  capability and name every changed region and reason. Never substitute an
  arbitrary web image or unrelated redraw.
- Search manifests before authoring. Assets remain `reused` when unchanged,
  including for placement-only changes. If the core message and model stay the same, modify
  the same `diagram_id` with `based_on_revision` only for a content/layout
  revision. A changed core message or model derives a new ID with `derived_from`.
  Missing generation capability, an edit reference, rendering, vision, or
  factual input blocks the affected visual; do not silently fall back.
- The completion report records, for every visual: `diagram_type`, `slide`,
  `authoring_route` and route tag, `diagram_id`, action (`created`, `reused`,
  `modified`, or `derived`), reused source, changed regions with reasons,
  editability, remaining raster layers, and the rationale for each raster
  layer. It records the review evidence using the exact record field names —
  `statuses.svg_preview`, `statuses.pptx_structure`, `statuses.pptx_render`,
  each with `reviewed_by`, `inspected_paths`, `findings`, `revision_required`,
  and its review-round number — never the three gates collapsed into one
  status. For a PPTX deliverable, the `statuses.pptx_render` entry also
  carries `renderer.name`, `renderer.version`, `renderer.conversion_format`,
  `conversion_artifacts`, `rendered_png_paths`, `model_vision.inspected_paths`,
  and `visual_checks`; `model_vision.inspected_paths` must equal the converted
  PNG set named in `rendered_png_paths` — `comparison_reference_paths` are
  optional diagnostics only and never substitute for that set. `overall`
  reports `overall.authority` (`pptx-render` for PPTX output,
  `source-pixel` otherwise) and `overall.completion_allowed`; an open finding
  or an incomplete direct-inspection set keeps `completion_allowed` `false`.

### 3.4 Response-facing contract

Fresh plans and completion responses must expose these required fields and
claims:

- **High-priority reuse scenario:** When the user asks whether to modify/redraw
  an existing visual, the answer **MUST** be a filled concrete record using
  `manifest_asset_search`, `slide`, `diagram_id`, `action`, `reused_source`,
  `based_on_revision`, `changes` with a numeric `bbox` expressed as
  `[x1, y1, x2, y2]` endpoint coordinates, `change`, and `reason`,
  and `delivery_summary`; do not answer with instructions such as `report
  <actual slide>`, angle-bracket placeholders, `[x,y]` placeholders, or a
  prose-only checklist. If no source or revision can actually be discovered,
  output an explicit blocker record instead of fabricating continuity. Planning
  examples may use the concrete representative record already shown.

- `regions`: Architecture and flow plans enumerate every named subfigure or
  semantic region in `diagram-plan.yaml` and repeat the same names in the
  response.
- `review`: State explicitly that each subfigure and the complete slide were
  rendered to pixels, inspected with model vision, and revised and re-rendered
  until passing; validation-status lists alone are insufficient. For a PPTX
  deliverable, additionally state that the actual `deck.pptx` was converted
  with LibreOffice (or an equivalent office renderer) and that every
  converted PNG under `rendered_png_paths` was directly inspected by
  `model_vision` before `statuses.pptx_render` was recorded — a source-pixel
  pass and a passing `statuses.pptx_structure` are not substitutes for that
  direct inspection.
- `generation` and `editability`: For `route: generative` /
  `authoring_route: generative` `[V:AI]` and `route: hybrid` /
  `authoring_route: hybrid` `[V:HYBRID]`, name `prompt.md` and report manifest
  `generation.prompt`, `generation.output`, and `generation.references`
  provenance, plus editability and any raster, embedding, or conversion-loss
  disclosures.
- Filled example: `manifest_asset_search: "found assets/diagram-library/human-review-flow.svg"; slide: 4; diagram_id: human-review-flow-v2; action: modified; reused_source: assets/diagram-library/human-review-flow.svg; based_on_revision: git:4b29f2a; changes: [{region: human-review-branch, bbox: [612, 184, 860, 316], change: "clarified approval branch", reason: "approval branch"}]; delivery_summary: "Modified slide 4 using the reused human-review flow asset."`
- `reuse.action`, `based_on_revision`, and `changes`: State that the
  asset-library/manifest search happened first. Same-core-message-and-model
  revisions use a concrete, non-placeholder `based_on_revision` value and
  list every changed `region` with its `bbox` and `reason`. Unchanged
  placement-only assets remain `reuse` in the plan and `reused` in the
  response; core-message or model changes use a new ID with `derived_from`.
  Reuse/change prompts must return a filled record (not instructions), with
  `manifest_asset_search` set to a found result or blocker and all of `slide`,
  `diagram_id`, `action`, `reused_source`, `based_on_revision`, `changes`
  (named `region`, numeric `bbox` in `[x1, y1, x2, y2]` endpoint-coordinate
  form, `change`, and `reason`), and
  `delivery_summary`.

#### Reuse/change response template

Every fresh execution answer must be a filled concrete record, not
instructions. Begin by stating the `manifest/asset-library search` result,
including the found source or blocker. Then include `slide`, `diagram_id`,
`action`, `reused_source`, and `based_on_revision`; list `changes` with a
named `region`, numeric `bbox`, `change`, and `reason` for each entry; finish
with a change-focused `delivery_summary`.
Every `bbox` is an endpoint-coordinate tuple `[x1, y1, x2, y2]` within the
1200x675 slide; never use `[x, y, width, height]`.

Planning examples may use clearly labeled representative concrete values.
Execution responses must use the discovered revision and never fabricate
continuity. An unavailable source or revision blocks completion. Placement-
only changes remain `reuse` in plans and `reused` in responses; a changed
core message or model still derives a new ID with `derived_from`.

```yaml
manifest_asset_search: "Found source via assets/manifest.yaml: assets/diagram-library/human-review-flow.svg"
slide: 4
diagram_id: human-review-flow-v2
action: modified
reused_source: assets/diagram-library/human-review-flow.svg
based_on_revision: "git:4b29f2a"
changes:
  - region: human-review-branch
    bbox: [612, 184, 860, 316]
    change: "Added the reviewer decision split."
    reason: "Make approval and rejection outcomes explicit."
  - region: failure-return-path
    bbox: [780, 356, 1084, 452]
    change: "Rerouted the return connector to the retry node."
    reason: "Show the actual failure recovery path."
delivery_summary: "Modified slide 4 from git:4b29f2a; changed two regions and preserved placement-only reuse."
```

**Dynamic inclusion rules:**
- Timeline: only with ≥2 entries linked via `follows:`
- Architecture: only if logs describe structural/model changes
- Failure slide: only if logs have content under `## Failures`
- Fewer slides (4–5) for single-entry logs; more for conference talks

---

### 3.5 Resolve style

Before generating, determine which style file to use and export `STYLE_FILE`:

```bash
STYLE_FILE=""
[ -f "$SLIDES_DIR/_style.md" ] && STYLE_FILE="$SLIDES_DIR/_style.md"
```

If the user named a style in Q6, search in order:
1. `$SLIDES_DIR/styles/<name>.md` (project-local)
2. Skill bundle `styles/<name>.md` (built-in)

Set `STYLE_FILE` to whichever path exists. If the user chose `custom`, read `references/styles/STYLES.md`
and ask for the required frontmatter values, then write `$SLIDES_DIR/styles/<name>.md`.

---

### 4. Generate slides

Output directory: `$SLIDES_DIR/reports/YYYY-MM-DD_<name>/`

---

#### [A] Python renderer — usually [V:DATA]

**Supported types:** `title` `bullet_list` `bar_chart` `table` `metric_cards` `two_column` `timeline` `conclusion` `score_trajectory` `pipeline_status`

Write `slide_data.json` then run:
```bash
python3 scripts/generate_slides.py --data <dir>/slide_data.json --out <dir>/ \
    ${STYLE_FILE:+--style "$STYLE_FILE"}
# Re-render one slide:
python3 scripts/generate_slides.py --data <dir>/slide_data.json --out <dir>/ --slide N \
    ${STYLE_FILE:+--style "$STYLE_FILE"}
```

**JSON format:**
```json
{
  "meta": {
    "experiment": "<deck-name>",
    "date": "YYYY-MM-DD",
    "footer": "<name> · YYYY-MM-DD"
  },
  "slides": [
    { "index": 1, "type": "title",
      "title": "...", "subtitle": "...", "author": "...", "date": "YYYY-MM-DD" },

    { "index": 2, "type": "bar_chart",
      "title": "...", "categories": ["A", "B"],
      "series": [
        { "label": "baseline", "color": "#d97706", "values": [72.1, 81.6] },
        { "label": "this run", "color": "#059669", "values": [98.4, 100.0] }
      ],
      "y_max": 100, "note": "n=..." },

    { "index": 3, "type": "table",
      "title": "...", "columns": ["Metric", "Before", "After", "Delta"],
      "rows": [["Accuracy", "81.6%", "100%", "+18.4%"]],
      "highlight_col": 3 },

    { "index": 4, "type": "metric_cards",
      "title": "...", "metrics": [
        { "label": "Overall", "value": "99.8%", "color": "#059669", "change": "+27%" }
      ]},

    { "index": 5, "type": "timeline",
      "title": "...", "events": [
        { "label": "v1 baseline", "date": "2024-10-01", "color": "#d97706", "detail": "72%" },
        { "label": "v2 final",    "date": "2024-11-02", "color": "#059669", "detail": "100%" }
      ]},

    { "index": 6, "type": "two_column",
      "title": "...",
      "left":  { "title": "Problem",      "content": ["point 1", "point 2"] },
      "right": { "title": "This Run",     "content": ["point 1", "point 2"] } },

    { "index": 7, "type": "bullet_list",
      "title": "...", "bullets": ["item 1", "item 2"], "numbered": true },

    { "index": 8, "type": "conclusion",
      "title": "...",
      "conclusions": ["finding 1", "finding 2"],
      "next_steps":  ["step 1", "step 2"] },

    { "index": 9, "type": "score_trajectory",
      "title": "Review Score Progression",
      "dimensions": ["Originality", "Methodology", "Clarity", "Citations", "Contribution"],
      "rounds": [
        { "label": "Round 1", "scores": [3, 4, 3, 2, 3] },
        { "label": "Round 2", "scores": [4, 4, 4, 4, 4] }
      ],
      "note": "D1-D5 rubric, scale 1-5" },

    { "index": 10, "type": "pipeline_status",
      "title": "Pipeline Progress",
      "stages": [
        { "number": 1, "name": "RESEARCH", "status": "PASS", "date": "2026-06-08" },
        { "number": 2, "name": "WRITE",    "status": "PASS", "date": "2026-06-10" },
        { "number": 2.5, "name": "INTEGRITY", "status": "PENDING", "date": null }
      ]}
  ]
}
```

Only include [A] slides in `slide_data.json`.

---

#### [B] Mermaid (optional source for [V:NATIVE])

Write a `.mmd` file then convert:
```bash
cat > <dir>/slideNN.mmd << 'EOF'
flowchart LR
  A["Input"] --> B["Model"] --> C["Output"]
EOF
mmdc -i <dir>/slideNN.mmd -o <dir>/slideNN_diagram.svg \
     --theme neutral --width 1200 --height 675
```

Use Mermaid only when its output converts correctly to the selected editable
route. If `mmdc` is unavailable, fall back to [C] for that slide and note the
route and editability in the summary. If the conversion yields only an
embedded or raster result, disclose the editability loss instead of calling it
`[V:NATIVE]`.

Prefer `flowchart LR` for pipelines, `flowchart TD` for training stages, `stateDiagram-v2` for state machines.

---

#### [C] Claude SVG — [V:NATIVE], [V:AI], or [V:HYBRID] source

Write SVG directly. If `STYLE_FILE` is set, read it and load `references/styles/STYLES.md` for the full
role descriptions; otherwise use the defaults in the table below.

| Style key | SVG usage | Default |
|-----------|-----------|---------|
| — | Canvas: `viewBox="0 0 1200 675"` | fixed |
| `bg` | Slide background `<rect fill="..."/>` | `#ffffff` |
| `primary` | Top bar, title text, bullet markers | `#1e3a5f` |
| `top_bar_h` | Top bar `height` in px | `6` |
| `border` | Divider line, card borders | `#e2e8f0` |
| `body` | Main paragraph text | `#374151` |
| `muted` | Footer, axis labels, captions | `#64748b` |
| `font` | `font-family` attribute | `'Helvetica Neue', Arial, sans-serif` |
| `positive` | Success / improvement values | `#059669` |
| `warn` | Caution values | `#d97706` |
| `danger` | Error / regression values | `#dc2626` |

Rules for `[V:NATIVE]`: no `<image>` tags; escape `&` `<` `>` in text; split long text with `<tspan dy="...">`. `[V:AI]` keeps the generated PNG/JPG as a separate raster base. `[V:HYBRID]` composes that raster base with an editable SVG overlay in the same `1200x675` coordinate system. For `[V:AI]` and `[V:HYBRID]`, do not put factual labels, legends, or values in generated pixels. Native PPTX exports overlay elements as separate shapes when supported, while embed/fallback output must disclose remaining raster layers and editability loss.

---

#### Charts

**list:** Collect chart paths from `## Charts` sections in the selected log files. Write `chart_list.md` grouped by slide.

**embed:** Base64-encode each PNG and insert as `<image>` in the relevant SVG.

---

### 5. Update logs and rebuild index

Add the deck path to `slide_decks:` in each included log file's frontmatter. Rebuild INDEX.md.

---

## PPTX export (optional)

After slides are generated:

**Native shapes (recommended) — fully editable in PowerPoint:**
```bash
# macOS / Linux / Git Bash:
cd "$(find ~/.claude -path "*/report-slides/scripts" -type d | head -1)"
python3 -m svg_to_pptx \
    --slides "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/" \
    --out    "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/deck.pptx"
```

Native mode converts every SVG element to editable shapes: rectangles, ovals, text boxes, connectors, and paths (including Bézier curves). Text labels inside shapes are embedded directly — double-click a shape in PowerPoint to edit its text. Connectors re-route when shapes are moved.

**SVG embed (backward-compatible, viewable but shapes are not individually editable):**
```bash
python3 -m svg_to_pptx --slides output/ --out deck.pptx --mode embed
# or equivalently:
python3 to_pptx.py \
    --slides "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/" \
    --out    "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/deck.pptx"
```

Only `python-pptx` and `lxml` required — no cairosvg, Pillow, or image converter needed.

**A PPTX export is not the final visual check.** Exporting `deck.pptx` only
produces the artifact `statuses.pptx_render` will judge — it is not itself
evidence that the deck looks correct, and neither is inspecting the SVG
source or the PPTX's internal object tree. Immediately after export:

1. Validate the produced package's structure (relationships, editable
   objects, image references) into `statuses.pptx_structure`. This never
   inspects visual placement.
2. Convert the actual `deck.pptx` — never the source SVG — with LibreOffice
   or an equivalent available office renderer, producing exactly one PNG per
   expected slide (see `references/visual-review.md` for the concrete
   `libreoffice`/`pdftoppm` commands).
3. Send every converted PNG path directly to model vision as
   `model_vision.inspected_paths` and record the outcome as
   `statuses.pptx_render` — the authoritative final visual gate.
4. Validate the resulting review record with
   `python3 skills/report-slides/scripts/validate_visual_review.py --record <path> --root <path>`
   (see `references/diagram-workflow.md`).

If LibreOffice or an equivalent renderer is unavailable, or the direct
final-PNG inspection cannot be completed, record `statuses.pptx_render` as
`blocked` with the exact missing capability and set
`overall.completion_allowed` to `false` — do not report the deck complete
from the SVG preview, the review sheet, or the PPTX structure result alone.

---

## Summary output

After all slides are generated, print:
- Output directory and slide list with rendering path tags ([A] / [B] / [C])
- One completion record per non-trivial visual with its route tag, `diagram_id`,
  type, slide, action, reused source, changed regions and reasons, editability,
  `statuses.svg_preview`, `statuses.pptx_structure`, and `statuses.pptx_render`
  (each with `reviewed_by`, `inspected_paths`, `findings`, `revision_required`,
  and round count — for PPTX, also `renderer.name`/`version`/
  `conversion_format`, `conversion_artifacts`, `rendered_png_paths`, and
  `model_vision.inspected_paths`), `overall.authority` and
  `overall.completion_allowed`, and remaining raster layers with their
  rationale
- `slide_data.json` re-render tip for [A] slides
- `chart_list.md` note if applicable
- Updated log files
- PPTX path if exported
- Import tips: drag SVG into Keynote (macOS); LibreOffice Impress opens SVG natively

---

## Edge cases

| Situation | Handling |
|-----------|---------|
| No log files exist | Stop; instruct user to run `/research-log add` |
| No numeric data in logs | Use `bullet_list` or `two_column` instead of charts |
| No `follows:` chain | Skip timeline slide |
| `mmdc` not found | Fall back to [C]; note in summary |
| Only 1 log entry | Limit to 4–5 slides |
| Chart file paths missing | Mark with ⚠ in `chart_list.md` |
| No baseline data | Skip comparison table |
