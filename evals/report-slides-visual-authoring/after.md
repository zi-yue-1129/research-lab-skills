# Report-slides Visual Authoring GREEN Forward Evaluation

This GREEN evaluation reruns the five Task 1 prompts with fresh
`gpt-5.6-luna` agents against the updated `skills/report-slides/SKILL.md`.
The rubric is not shown to the workers. The canonical raw response bytes are the
five listed `/tmp/report-slides-after-*.txt` files, and the SHA-256 values in the
execution manifest are computed from those files. The responses are presented
below in Markdown fenced blocks. The canonical `/tmp` raw files and hashes
remain authoritative; Markdown fence delimiters are presentation syntax, and
the structural newline before each closing fence is outside the payload. The
content inside each fenced block is byte-for-byte equivalent to its mapped
canonical raw file. Responses are scored only for behavior stated in the
response. The reuse case was rerun after the observed-gap contract was
tightened and uses the final blocker-aware response.

## Execution manifest

- Candidate skill base before the Task 6 observed-gap fixes: `e37277c`
- Final Task 6 skill SHA-256 before commit: `9b4ae655deef1419984aef8fdc71c99186a81537b44b82cf1d7108b2918947fc`
- Agent command template:
  `codex exec --ephemeral --model gpt-5.6-luna --config model_reasoning_effort=max --sandbox read-only --ignore-rules --color never -o <raw-output> 'Act as a bounded luna_worker. Read only skills/report-slides/SKILL.md from the current checkout. Do not inspect or modify any other files, do not launch nested Codex, and return only the substantive answer to this scenario: <scenario prompt>'`
- Raw capture SHA-256 values:
  - architecture: `/tmp/report-slides-after-v2-architecture.txt` — `816710a2399413139b9a990cd15e81cd6aab00b176ebc79ac51090ac39501651`
  - hybrid: `/tmp/report-slides-after-v2-hybrid.txt` — `2be7c8fd6ecf498854bcc5940e8b4fe7758c03f729bac489d45e88fe20eb05f7`
  - statistics: `/tmp/report-slides-after-statistics.txt` — `4306f4cdc0f76641210c70ee316f408da805147d5acc3d6bbbe84a8acf29d44e`
  - reuse: `/tmp/report-slides-after-v7-reuse.txt` — `705e4ed7d6e904cb3628311d8f6a4aa0a9b1c2c56189819b5b05302ea4b61f3e`
  - completion: `/tmp/report-slides-after-completion.txt` — `7cb2ff8c63b6ab255a9dee1ba2b14ae9c51e364e1177a57765cc01a49d9cc597`

## architecture-planning

Prompt: Use report-slides to plan one slide explaining ingestion, feature processing, training, evaluation, human approval, and publishing. Describe artifacts created before drawing and how PPTX stays editable.

### Raw response

````text
Use one 16:9 `[V:NATIVE]` pipeline slide titled “From Raw Inputs to Published Model.”

Before drawing:

```yaml
# diagram-plan.yaml
visuals:
  - diagram_id: ingestion-feature-training-publishing-v1
    slide: 1
    diagram_type: pipeline
    route: native
    regions:
      - Ingestion
      - Feature Processing
      - Training
      - Evaluation
      - Human Approval
      - Publishing
    reuse:
      action: created
      based_on_revision: null
      derived_from: null
```

Also search existing `manifest.yaml` files for reusable pipeline assets, then record the decision in the visual manifest:

```yaml
authoring_route: native
diagram_id: ingestion-feature-training-publishing-v1
action: created
reused_source: null
editability: native SVG shapes
```

Load only the native-route workflow, pattern, and visual-review references before authoring the reusable SVG source.

Slide structure:

`Ingestion → Feature Processing → Training → Evaluation → Human Approval → Publishing`

Each card should show its principal artifact:

- Ingestion: raw data plus ingestion manifest
- Feature Processing: validated feature set plus feature schema/version
- Training: model checkpoint plus training metadata
- Evaluation: metrics, quality, and safety report
- Human Approval: reviewer decision and approval record
- Publishing: versioned package, registry entry, and deployment manifest

Use solid arrows for the main path and a dashed “reject / retrain” loop from Evaluation or Human Approval back to Training. Render the diagram as direct SVG using rectangles, text, paths, and connectors—no `<image>` elements.

Export with native `svg_to_pptx` mode. Each SVG shape becomes an editable PowerPoint shape, text remains directly editable, and connectors can reroute when shapes move. SVG embedding is only a fallback and must disclose that shapes are no longer individually editable.

After authoring, render both the pipeline subfigure and the complete slide to pixels, inspect them with model vision, revise and re-render until they pass, then report `SVG-preview`, `PPTX-structure`, and `PPTX-render` as separate validation stages.
````

### Requirement scores

- [pass] Named subfigures or regions — `diagram-plan.yaml` enumerates six named regions.
- [pass] Editable nodes, labels, and connectors — direct SVG rectangles, text, paths, and connectors are converted to editable PPTX shapes.
- [pass] Rendered-pixel review before completion — both subfigure and complete-slide pixels are reviewed with model vision and revised until passing.

Observed failure pattern: none.

## hybrid-generative-visual

Prompt: Plan a conceptual researcher-and-AI-lab slide. Use generated imagery where useful, keep factual annotations editable, and state files and disclosures.

### Raw response

````text
Plan one 16:9 conceptual slide using `[V:HYBRID]` / `route: hybrid`.

- Title: “The Researcher–AI Lab Loop”
- `researcher zone`: editable role label and short description.
- `AI lab zone`: generated atmospheric imagery of an AI research workspace—screens, model abstractions, and light/data motifs, without embedded text or factual claims.
- `collaboration loop`: editable SVG arrows connecting question → experiment → AI assistance → researcher judgment → new question.
- `evidence callout`: editable factual annotations, metrics, citations, or limitations.
- `disclosure footer`: editable note identifying generated imagery and separating illustration from evidence.

Files:

- `diagram-plan.yaml` — regions, route, IDs, and review plan.
- `prompt.md` — exact image-generation prompt.
- `generated/researcher-ai-lab-base.png` — raster image output.
- `slide01.svg` — editable overlay and composition.
- `manifest.yaml` — `authoring_route: hybrid`, generation prompt/output/references, provenance, editability, and raster-layer rationale.
- `renders/slide01.png` and `renders/researcher-ai-lab-base.png` — pixel-review outputs.
- `deck.pptx` — optional native-shape export.

Disclosure: the atmospheric lab image is AI-generated and illustrative; all factual text, arrows, labels, values, and citations remain editable SVG/PPTX elements. No factual annotations should be baked into the generated pixels. Report any remaining raster layer, SVG embedding, or PPTX conversion loss explicitly. Before completion, render both the subfigure and full slide, inspect them with model vision, revise and re-render until passing, then validate the plan, manifest, and asset root.
````

### Requirement scores

- [pass] Raster illustration separated from editable factual overlays — the atmospheric image is isolated and the SVG supplies labels, arrows, and evidence callouts.
- [pass] No generated prose labels, legends, or precise values — generated imagery excludes embedded text and factual claims.
- [pass] Prompt sources and editability recorded — `prompt.md`, generated output, manifest generation prompt/output/references, provenance, and editability are named.

Observed failure pattern: none.

## statistical-integrity

Prompt: Plan an accuracy chart from 72.1, 81.6, 98.4, and 100.0. Explain how data integrity and rendered visual quality are verified.

### Raw response

````text
Use a deterministic `[A]` Python `bar_chart` with the `[V:DATA]` route, assuming the values represent an ordered progression:

```json
{
  "type": "bar_chart",
  "title": "Accuracy Progression",
  "categories": ["Point 1", "Point 2", "Point 3", "Point 4"],
  "series": [
    {
      "label": "Accuracy (%)",
      "color": "#059669",
      "values": [72.1, 81.6, 98.4, 100.0]
    }
  ],
  "y_max": 100,
  "note": "Exact accuracy values"
}
```

Replace the neutral category labels with verified names if they are available; do not infer them.

Data integrity is verified by preserving the values as exact numeric inputs, checking that every value is between 0 and 100, confirming category/value counts match, comparing the serialized `slide_data.json` back to the source values, and inspecting the rendered SVG for correct ordering and labels. The plan and manifest are then validated with the report-slides validators.

Rendered quality is verified by rendering both the chart and complete slide to pixels, checking that all bars—including the 100.0% bar—fit within the axis, labels remain legible, decimal precision is clear, contrast and spacing are adequate, and no text overlaps or clips. Revise and rerender until both pixel reviews pass. If PPTX export is requested, report `SVG-preview`, `PPTX-structure`, and `PPTX-render` as separate validation results; otherwise mark those stages not requested.
````

### Requirement scores

- [pass] Deterministic rendering rather than image generation — the response selects the Python bar-chart renderer and `[V:DATA]`.
- [pass] Reconstructable source data — the complete JSON payload preserves all four values and chart settings.
- [pass] Chart and complete-slide pixel review — both chart and complete slide are rendered and reviewed, with revision until passing.

Observed failure pattern: none.

## reuse-and-change-disclosure

Prompt: A project training-pipeline diagram gains a human-review branch and failure return path. Explain whether to redraw or modify and how to report location.

### Raw response

````text
Modify the existing diagram if the core training-pipeline message and model remain unchanged. Add two named regions: `human-review-branch` and `failure-return-path`. Create a new derived diagram only if the core model changes.

Report each location as a slide number plus an endpoint-coordinate bounding box `[x1, y1, x2, y2]` within the 1200×675 canvas—not width/height values or vague prose.

```yaml
manifest_asset_search: "BLOCKED: source manifest, slide, and revision were not inspected"
slide: null
diagram_id: null
action: blocked
reused_source: null
based_on_revision: null
changes:
  - region: human-review-branch
    bbox: null
    change: "Add the human-review decision branch."
    reason: "Make manual review explicit."
  - region: failure-return-path
    bbox: null
    change: "Add the failure connector returning to the retry/training step."
    reason: "Show failure recovery explicitly."
delivery_summary: "Modify the existing asset after discovering its manifest entry, slide, diagram_id, revision, and numeric region bboxes; do not fabricate those values."
```
````

### Requirement scores

- [pass] Asset-library search first — manifest/asset discovery is the blocking first condition and the response records that assets were not inspected.
- [pass] Previous source modified instead of unrelated regeneration — it directs modification with the same ID when the model is unchanged and derives only when core semantics change.
- [pass] `based_on_revision`, region bbox, change, and reason — all fields are present; revision and bboxes are correctly null because discovery is blocked, while concrete named changes and reasons are retained. The response defines bbox as endpoint coordinates `[x1, y1, x2, y2]` and rejects width/height values.
- [pass] Change-focused delivery summary — `delivery_summary` states what must be discovered before modification and forbids fabricated continuity.

Observed failure pattern: none; the actual source, revision, slide, and numeric bboxes remain an explicit external blocker.

## completion-report

Prompt: A deck contains a native architecture diagram, a hybrid conceptual image, and a data chart. Show the per-visual completion report you would return after export and validation.

### Raw response

````text
```yaml
visuals:
  - diagram_type: architecture
    slide: 7
    authoring_route: native
    route_tag: "[V:NATIVE]"
    diagram_id: architecture-v1
    action: created
    reused_source: null
    changed_regions: []
    editability: fully editable SVG/PPTX shapes and connectors
    review_rounds: 2
    validation:
      SVG-preview: PASS
      PPTX-structure: PASS
      PPTX-render: PASS
    remaining_raster_layers: none

  - diagram_type: conceptual_image
    slide: 8
    authoring_route: hybrid
    route_tag: "[V:HYBRID]"
    diagram_id: conceptual-image-v1
    action: created
    reused_source: null
    changed_regions:
      - region: annotation_overlay
        reason: added editable factual labels and structural callouts
    editability: SVG overlay editable; generated visual base remains raster
    review_rounds: 2
    validation:
      SVG-preview: PASS
      PPTX-structure: PASS
      PPTX-render: PASS
    remaining_raster_layers:
      - generated conceptual image base
        rationale: preserves the intended illustrative appearance; factual content is editable in the SVG overlay

  - diagram_type: data_chart
    slide: 9
    authoring_route: data
    route_tag: "[V:DATA]"
    diagram_id: results-chart-v1
    action: created
    reused_source: null
    changed_regions: []
    editability: fully editable deterministic SVG/PPTX shapes and text
    review_rounds: 2
    validation:
      SVG-preview: PASS
      PPTX-structure: PASS
      PPTX-render: PASS
    remaining_raster_layers: none
```
````

### Requirement scores

- [pass] Diagram type, slide location, route, ID, and action — all are present per visual.
- [pass] Reused source and changed regions with reasons — `reused_source` and the hybrid changed region/reason are present.
- [pass] Editability and review rounds — present per visual.
- [pass] Separate SVG preview, PPTX structure, and PPTX render validation — each is separately recorded.
- [pass] Remaining raster layers and rationale — the hybrid base and rationale are explicitly recorded.

Observed failure pattern: none.

## GREEN conclusion

All five scenarios pass their explicit requirements. The reuse scenario is
correctly reported as blocked because the bounded worker was not allowed to
inspect project assets; it does not invent a source, revision, slide, or bbox.
