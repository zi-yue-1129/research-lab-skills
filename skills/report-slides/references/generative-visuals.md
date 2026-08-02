# Generative visuals

## Selection gate

Use a generative image only when illustration adds explanatory value that
native shapes or deterministic SVG cannot provide efficiently. Do not use an
image model for statistical marks, chart values, authoritative technical
labels, legends, exact numbers, or other factual structure.

Creation and editing are runtime operations. Invoke the runtime image-generation
capability for the current visual; an existing file alone is not evidence that
the requested generation or edit occurred. Do not replace a required runtime
generation or edit with an arbitrary web image, an untracked download, or an
unrelated redraw.

## Prompt record

Store the prompt record as `prompt.md` in the asset directory. It must contain
all of these fields:

```yaml
purpose: Support the explanation of the researcher and AI evaluation loop.
composition: One focal researcher at left, abstract model activity at right, open space above.
subject: Researcher, lab environment, and non-literal machine-learning forms.
palette: Deep navy, warm amber, muted teal, and neutral background.
lighting: Soft directional light with a calm, readable center.
empty_annotation_regions: Upper third and lower-right margin.
exclusions:
  - prose
  - labels
  - legends
  - exact values
  - watermarks
  - signatures
aspect_ratio: 16:9
references:
  - source-reference.png
changed_regions: []
```

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
source_files:
  - overlay.svg
generation:
  prompt: prompt.md
  output: generated.png
  references: []
```

The overlay and raster use the same `1200 x 675` coordinate system. The
manifest and completion record disclose which pixels remain raster and why.

## Failure handling

- Missing image-generation capability: record a blocker and stop the visual.
- Safety or runtime generation failure: keep the issue explicit and do not
  silently substitute another image.
- Missing reference for an edit: stop until the earlier image and changed
  regions are available.
- Factual data or labels requested inside the image: move them to native SVG;
  do not ask the image model to draw them.
- Generated fake text, misleading structure, or visible artifacts: retain the
  failing render for diagnosis, revise the prompt or source, and repeat visual
  review.
- If the result cannot preserve the agreed semantics, quality, or editability,
  report the failure instead of presenting a different asset as equivalent.
