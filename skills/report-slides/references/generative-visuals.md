# Generative visuals

## Selection gate

The generative route is opt-in and last. Before it is available for a module,
two deterministic candidates must have been produced and ranked, and both must
have failed to carry the module's claim. Record which candidates were tried and
why they failed; that record is the `illustration_rationale` field of the prompt
record, and a generative asset without it does not pass the module gate.

Do not use an image model for statistical marks, chart values, authoritative
technical labels, legends, exact numbers, or other factual structure.

Creation and editing are runtime operations. Invoke the runtime image-generation
capability for the current visual; an existing file alone is not evidence that
the requested generation or edit occurred. Do not replace a required runtime
generation or edit with an arbitrary web image, an untracked download, or an
unrelated redraw.

**Why the default changed.** A generative illustration that could have been a
diagram costs the deck twice: it cannot be edited when the content changes, and
it drifts towards the image model's prior for "technical illustration" — glowing
networks, light ribbons, abstract data cities — which reads as generic
regardless of how well it is rendered. See
`references/style-anchors/README.md`.

## Prompt record

Store the prompt record as `prompt.md` in the asset directory. It must contain
all of these fields:

```yaml
purpose: Support the explanation of the retrieval and ranking loop.
illustration_rationale: >-
  Two deterministic candidates were produced (a staged flow diagram and a
  layered block diagram); both rendered the stages but neither carried the
  claim that ranking is continuous rather than discrete.
style_anchor: technical-schematic
composition: Three stages left to right, open annotation margin above.
subject: A retrieval pipeline and the ranked passages leaving it.
palette: Design-token roles primary, body, line, card, bg.
lighting: Flat, no directional light.
empty_annotation_regions: Upper third and lower-right margin.
exclusions:
  - prose
  - labels
  - legends
  - exact values
  - watermarks
  - signatures
aspect_ratio: 16:9
references: []
changed_regions: []

# Spec D6: three candidates, ranked blind against the anchor's reference images.
# `matches_anchor` is the ranker's verdict, not the author's preference. If the
# top-ranked candidate does not match, set `selected: null` and
# `downgraded_to: native-editorial` -- accepting the least-bad image is
# prohibited, and validate_generative_prompt.py refuses it.
candidates:
  - id: c1
    asset: renders/candidate-01.png
    rank: 1
    matches_anchor: true
  - id: c2
    asset: renders/candidate-02.png
    rank: 2
    matches_anchor: false
  - id: c3
    asset: renders/candidate-03.png
    rank: 3
    matches_anchor: false
ranking:
  blinded: true
  ranked_by: art_direction
selected: c1
```

**On "ranked blind".** The ranker must not know which candidate came from which
generation attempt, which prompt variant produced it, or which one the author
prefers. Present the three renders in a shuffled order against the anchor's
reference images and record the verdict. `ranking.blinded: false` is refused
rather than merely noted: an unblinded ranking of three images the author
already has an opinion about is a rationalisation, not a ranking, and it would
let the exact failure in spec §2.1 through with three times the paperwork.

`style_anchor` and `illustration_rationale` are required. Validate the record
before generating:

```bash
VGP="$(find ~/.claude -path "*/report-slides/scripts/validate_generative_prompt.py" | head -1)"
timeout 120 python3 "$VGP" --prompt "$ASSET_DIR/prompt.md" --json
```

The validator refuses a record that omits a required field, cites an
unregistered anchor, drops a required exclusion, or asks anywhere in its text
for a banned motif. It reads the prompt, not the produced image: a model may
still return a banned motif unasked, and that case is caught at review as an
`art_direction` `visual-cliche` finding.

For a new image, `references` and `changed_regions` may be empty. For an edit,
name the earlier image in `references` and list each requested region in
`changed_regions` with the intended change and reason. The record should make
the output reproducible enough to audit without putting factual claims into
the generated pixels.

## New image workflow

1. Decide the audience takeaway, route, and empty annotation regions.
2. Write `prompt.md` with the full prompt record, including explicit
   exclusions.
3. Call the runtime image-generation tool and save the returned raster as the
   declared `.png` or `.jpg` output.
4. Inspect the rendered image for artifacts and misleading structure.
5. If factual annotations are needed, add them as native SVG objects and
   declare the composition `hybrid`; otherwise disclose the raster editability
   level in the manifest.

The generation provenance in `manifest.yaml` points `generation.prompt` to the
prompt record, `generation.output` to the generated raster, and
`generation.references` to the declared reference paths. A new image may have
an empty `generation.references` list.

## Reference-edit workflow

When revising an existing image, provide the earlier image to the runtime
image-generation tool and name the changed regions before calling it. State
what must remain stable as well as what changes. Preserve the same asset ID
only when both the core message and the model are unchanged; in that case, set
`based_on_revision` and record each region and reason in `changes`. If either
the core message or model changes, derive a new asset with a new ID and set
`derived_from` to the earlier asset. The edited asset's
`generation.references` must be non-empty.

Do not generate an unrelated replacement when a region-level edit is required.
If the earlier image or the requested region cannot be supplied, stop with an
explicit blocker rather than claiming continuity.

## Editable overlay contract

Generated pixels contain illustration only. Exclude prose, labels, legends,
exact values, watermarks, and signatures from the image output. Put every
factual annotation, axis, arrow, box, callout, legend, and precise numeric
claim into a native SVG overlay so it remains individually editable.

For a raster base plus overlay, declare:

```yaml
authoring_route: hybrid
editability: hybrid
pptx_construct: native_group
source_files:
  - overlay.svg
generation:
  prompt: prompt.md
  output: generated.png
  references: []
```

The overlay and raster use the same `1200 x 675` coordinate system. The
manifest and completion record disclose which pixels remain raster and why.

### Native PPTX object markers in the overlay

The overlay SVG is converted to individual native PowerPoint shapes by
`svg_to_pptx/converter.py`, so it carries the same non-negotiable marker rule
as any other hand-authored SVG in this skill:

> Any element that is one semantic visual unit — a diagram/flowchart node
> (background shape + icon + label), a timeline/milestone event, a legend
> entry, a callout box with its leader and text — MUST be wrapped in
> `<g data-pptx-role="group" data-node-id="...">`. Tabular data MUST be
> authored as `data-pptx-role="table"` with a `data-pptx-source` sidecar file,
> never as hand-drawn grid rects/lines. Chart data MUST be authored as
> `data-pptx-role="chart"` with a `data-pptx-source` sidecar file, never as
> hand-drawn bars/lines/pie wedges. Producing a table or chart without these
> markers, or a diagram node as ungrouped loose shapes, is a hard blocker at
> Stage 9 — not a style preference.

This matters more here than elsewhere: the "Editable overlay contract" already
forces every legend, callout, axis, and numeric claim out of the pixels and
into the overlay, so the overlay is precisely where unmarked hand-drawn
legends and value tables would otherwise accumulate. `data-pptx-bbox`
("x,y,w,h") is required on `table`/`chart` markers and uses the same
`1200 x 675` coordinate system as the rest of the overlay; `group` markers
derive their extent from their children and need no bbox.

Record the resulting construct as `pptx_construct` in `manifest.yaml`
(`native_table` / `native_chart` / `native_group` / `svg_shapes`). Verify with:

```bash
python3 scripts/validate_native_objects.py --svg-dir <dir containing overlay.svg>
```

A non-zero exit is a hard blocker; fix the markup rather than lowering
`pptx_construct` to `svg_shapes`.

## Failure handling

- Missing image-generation capability: record a blocker and stop the visual.
- Safety or runtime generation failure: keep the issue explicit and do not
  silently substitute another image.
- Missing reference for an edit: stop until the earlier image and changed
  regions are available.
- Factual data or labels requested inside the image: move them to native SVG;
  do not ask the image model to draw them.
- Unmarked table, chart, or node-cluster markup in the overlay
  (`validate_native_objects.py` exits non-zero): add the required
  `data-pptx-role` marker and re-run the check; do not proceed with the
  finding outstanding.
- Generated fake text, misleading structure, or visible artifacts: retain the
  failing render for diagnosis, revise the prompt or source, and repeat visual
  review.
- If the result cannot preserve the agreed semantics, quality, or editability,
  report the failure instead of presenting a different asset as equivalent.
