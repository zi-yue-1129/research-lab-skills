# report-slides: Native PPTX Objects Design

Status: Approved for planning
Date: 2026-08-13

## Problem

`report-slides` currently authors every visual element as hand-drawn SVG
primitives (`<rect>`, `<line>`, `<circle>`, `<text>`), regardless of what the
element semantically is. This happens on both generation paths:

- **Path A** (`scripts/generate_slides.py`): `render_table`, `render_bar_chart`,
  and `render_timeline` draw grid lines, bars, and timeline dots as raw SVG
  shapes.
- **Path C** (agent-authored SVG — `architecture_diagram_worker_agent`,
  `complex_visual_decomposer_agent`, `data_visualization_worker_agent`, and
  free-form Claude SVG slides): every diagram node (background box + icon +
  label) is emitted as independent, unrelated shapes.

`scripts/svg_to_pptx/converter.py` converts these SVG primitives into
individual native PPTX *shapes* (autoshapes, textboxes, connectors), but it
has no semantic layer: it cannot tell that a grid of rectangles is a table,
that a cluster of bars is a chart, or that a box+icon+label cluster is one
diagram node. The result is a PPTX where:

- Tables are a pile of disconnected rectangle + textbox shapes, not a real
  `<a:tbl>` table object.
- Charts are disconnected bar rectangles, not a real chart part with
  editable underlying data (`add_chart`).
- Diagram nodes (architecture diagrams, structural flowcharts, timeline
  events) are flat, ungrouped shapes instead of a single `Group` shape that
  can be moved/resized as one unit.

None of these are editable the way a native PowerPoint object is (double-click
a table cell, double-click a chart to edit its data series, drag a diagram
node as one piece).

Note on terminology: the pipeline's existing `editability` manifest field
already uses the word "native" to mean "editable SVG shapes converted to
individual PPTX shapes" (as opposed to a flattened raster). This design adds
a *different* tier — true PPTX table/chart/group objects — and introduces a
separate field (`pptx_construct`, see below) rather than overload `native`
further.

## Scope (confirmed)

In scope:
1. Tables → native PPTX table object.
2. Charts — bar, line, pie — → native PPTX chart object with real
   underlying data.
3. Timeline / milestone nodes → native PPTX Group shape per event.
4. Complex model architecture diagrams and complex structural flowcharts
   (priority) → native PPTX Group shape per semantic node.
5. Enforcement via both agent-facing authoring rules and an automated
   detection/validation gate that blocks production when a table/chart/node
   pattern exists without the matching native construct.

Out of scope (explicitly deferred, not part of this change):
- True Office SmartArt (`diagramData` part) — python-pptx has no public API
  for it; "SmartArt-style" diagrams stay as native Group shapes, not real
  SmartArt.
- Chart types beyond bar/line/pie (scatter, radar, area, combo) — the
  `pptx_native` module's chart-type dispatch is designed to be extended
  later, but only bar/line/pine ship in this change.
- Any change to the raster/PNG fallback embedding path (`to_pptx.py`'s
  SVG-blip packing) — that remains the backward-compatible fallback for
  viewers that don't support the native constructs.

## Architecture

Keep SVG as the pixel-preview artifact used by the mandatory Stage 9
visual-authoring gate (vision review needs pixels), but stop treating SVG
shape-flattening as how the *final* PPTX gets a table, chart, or semantic
multi-shape node. Native materialization happens in exactly one place:
`scripts/svg_to_pptx/converter.py`, the sole "native shapes (recommended)"
export path documented in `SKILL.md` § "PPTX export (optional)"
(`python3 -m svg_to_pptx --slides <dir> --out deck.pptx`). Both Path A
(`generate_slides.py`) and Path C (agent-authored SVG) write plain
`slideNN.svg` files into the same output directory and are converted by the
same `svg_to_pptx` invocation — there is no separate Path-A-only assembly
step. (`generate_slides.py`'s own `to_pptx()` and the top-level `to_pptx.py`
are the *SVG-embed* fallback mode — raster picture + SVG blip, no per-shape
conversion at all — and are unchanged by this design; see "Out of scope.")

Concretely, this means Path A's SVG renderers must emit the *same*
`data-pptx-role` marker convention Path C agents use (see Component C) —
Path A is a producer of annotated SVG, not a second consumer of
`pptx_native`.

```
        generate_slides.py                architecture_diagram_worker_agent,
        render_table / render_bar_chart /  complex_visual_decomposer_agent,
        render_line_chart / render_pie_chart /   data_visualization_worker_agent,
        render_timeline                     free-form Claude SVG (Path C)
        — emits <g data-pptx-role=...>      — emits <g data-pptx-role=...>
          wrapping existing hand-drawn        wrapping node/table/chart
          preview markup (Path A)             markup
                 │                                    │
                 └───────────────┬────────────────────┘
                                  ▼
                     slideNN.svg files in one output dir
                     (existing SVG still used unchanged for
                      the Stage 9 vision-review preview)
                                  │
                                  ▼
                 python3 -m svg_to_pptx --slides <dir> --out deck.pptx
                 scripts/svg_to_pptx/converter.py
                 (existing shape/connector dispatch, + NEW
                  data-pptx-role branch: table/chart roles call
                  scripts/pptx_native.py instead of flattening the
                  subtree; group roles flatten as today then wrap
                  the result in add_native_group)
                                  │
                                  ▼
                     scripts/validate_native_objects.py
                   (NEW gate: static SVG scan + post-conversion
                    PPTX assertions, wired into Stage 9/15 and
                    presentation_evidence_gates.py)
```

## Components

### A. `scripts/pptx_native.py` (new)

A small library wrapping python-pptx's native object construction. Used
exclusively by `svg_to_pptx/converter.py`'s new `data-pptx-role` dispatch
branch (Component C) — the single materialization point for both Path A and
Path C output.

```python
def add_native_table(
    slide: Slide,
    columns: list[str],
    rows: list[list[str]],
    bbox: tuple[int, int, int, int],   # EMU: left, top, width, height
    style: dict[str, str],
    highlight_col: int | None = None,
) -> GraphicFrame: ...

def add_native_chart(
    slide: Slide,
    chart_type: str,                    # "bar" | "line" | "pie"
    categories: list[str],
    series: list[dict],                 # [{"label": str, "values": list[float], "color": str}]
    bbox: tuple[int, int, int, int],
    style: dict[str, str],
    y_max: float | None = None,
) -> GraphicFrame: ...

def add_native_group(
    slide: Slide,
    shapes: list[BaseShape],
) -> GroupShape: ...
```

`add_native_table` / `add_native_chart` consume the *same* JSON schema Path
A's `render_table` / `render_bar_chart` already use (`columns`/`rows`/
`highlight_col`; `categories`/`series`/`y_max`) — no new data schema for
Path A. Style mapping (see "Style mapping" below) is internal to this
module.

### B. Path A — marker-annotated SVG output in `generate_slides.py`

SVG rendering (`render_table`, `render_bar_chart`, `render_timeline`)
continues to render the same hand-drawn preview markup, unchanged, so the
Stage 9 vision-review gate keeps working exactly as today. What changes is
that each function additionally wraps its content in the `data-pptx-role`
marker (Component C's convention) so the *shared* `svg_to_pptx` converter
materializes a native object instead of flattening shapes:

- `render_table`: wraps its table markup in
  `<g data-pptx-role="table" data-pptx-source="slide_data.json#<slide_index>"
  data-pptx-bbox="...">`. The sidecar reference is the already-written
  `slide_data.json` itself (Path A never needs a separate sidecar file — it
  already has the structured data on hand) qualified with a `#<slide_index>`
  fragment so the converter knows which slide entry to read.
- `render_bar_chart` (and new `render_line_chart`, `render_pie_chart`):
  same pattern with `data-pptx-role="chart"`.
- `render_timeline`: each event's circle + connector + label(s) is wrapped
  in `<g data-pptx-role="group" data-node-id="event-<i>">` — no
  `data-pptx-source`/`data-pptx-bbox` needed, per Component C's rule that
  `group` markers derive their extent from their actual children.

Title/footer chrome (the `frame()` header/footer bar) stays outside any
`data-pptx-role` marker and converts as ordinary shapes today, since it's
decorative, not data.

`line_chart` and `pie_chart` are new `slide_data.json` slide types, added
alongside `bar_chart` with an equivalent schema (`categories`/`series` for
line; `categories`/single `series` of values for pie). Their SVG preview
renderers (`render_line_chart`, `render_pie_chart`) are new, minimal, and
only need to be good enough for the vision-review gate — the converter
replaces their content with a real native chart on export.

`slide_data.json#<slide_index>` resolution and the `pptx_native` calls
themselves live entirely in `scripts/svg_to_pptx/converter.py` (Component
C) — Path A does not import or call `pptx_native` directly.

### C. Path C — semantic markers + converter branch

Agents cannot call python-pptx directly; they only produce SVG. This design
adds a marker convention agents wrap around semantic subtrees:

```xml
<g data-pptx-role="table" data-pptx-source="table_data.json"
   data-pptx-bbox="60,75,1080,450">
  ... existing hand-drawn preview markup (unchanged, used for vision review) ...
</g>

<g data-pptx-role="chart" data-pptx-source="chart_data.json"
   data-pptx-bbox="130,100,970,420">
  ...
</g>

<g data-pptx-role="group" data-node-id="encoder_block">
  ... box + icon + label shapes for one diagram node ...
</g>
```

`data-pptx-source` resolves one of two ways, both loaded by the same helper
(`converter.py`'s new `_load_pptx_source(base_dir, value) -> dict`):
- A plain filename (`table_data.json`) — a sidecar JSON file in the same
  directory as the `.svg`, using the identical schema as Path A's
  `slide_data.json` table/chart entries. This is the form Path C agents use.
- `slide_data.json#<slide_index>` — read `slide_data.json` from the same
  directory and index into its `slides` array at `<slide_index>` (0-based,
  matching the SVG's own `slideNN` numbering minus one). This is the form
  Path A's renderers use, since the structured data already exists there
  and a per-slide sidecar file would just be a redundant copy.

`data-pptx-bbox` is `"x,y,w,h"` in the SVG's own user units (the
same `viewBox`-relative coordinates every other element in the file already
uses) — it is **required** on `table`/`chart` markers so the converter never
has to infer a bounding box from the (skipped) preview children; it is
converted to EMU via the same `CoordSystem.x()`/`y()` the rest of the
converter already uses. `group` markers do not need `data-pptx-bbox` — the
group's extent is simply the union of the child shapes actually placed.

`svg_to_pptx/converter.py` gets one new dispatch branch in
`_dispatch_element` (checked before the existing `tag == "g"` fallthrough):

- `data-pptx-role="table"` / `"chart"`: load `data-pptx-source`, resolve
  `data-pptx-bbox` through `CoordSystem`, call `pptx_native.add_native_table`
  / `add_native_chart`, and **do not recurse into the subtree** — the
  hand-drawn preview children are skipped entirely for the final PPTX (they
  still exist in the SVG file for the vision-review step, which runs before
  conversion). Missing or malformed `data-pptx-source`/`data-pptx-bbox` is a
  hard conversion error, not a silent fallback to shape-flattening.
- `data-pptx-role="group"`: recurse into children via the existing dispatch
  (so individual shapes/connectors are created exactly as today), then pass
  the resulting shape objects to `pptx_native.add_native_group` before
  returning to the parent's iteration.

Groups may nest only one level deep for this change (a `group` role
containing further `group` roles is not required — architecture diagram
nodes are flat clusters of primitive shapes, not nested groups).

### D. Agent rule updates

`architecture_diagram_worker_agent.md`, `complex_visual_decomposer_agent.md`,
`data_visualization_worker_agent.md`, and the relevant sections of
`SKILL.md` (§9 mandatory visual-authoring gate) and
`references/diagram-patterns.md` / `references/generative-visuals.md` get an
explicit, non-negotiable rule:

> Any element that is one semantic visual unit — a diagram/flowchart node
> (background shape + icon + label), a timeline/milestone event, a legend
> entry — MUST be wrapped in `<g data-pptx-role="group" data-node-id="...">`.
> Tabular data MUST be authored as `data-pptx-role="table"` with a
> `data-pptx-source` sidecar file, never as hand-drawn grid rects/lines.
> Chart data MUST be authored as `data-pptx-role="chart"` with a
> `data-pptx-source` sidecar file, never as hand-drawn bars/lines/pie
> wedges. Producing a table or chart without these markers, or a diagram
> node as ungrouped loose shapes, is a hard blocker at Stage 9 — not a style
> preference.

This is the *primary* enforcement mechanism. The detector below is a safety
net, not the main line of defense.

### E. Enforcement gate — `scripts/validate_native_objects.py` (new)

Mirrors the existing `complex_visual_detector.py` pattern (deterministic,
configurable, used by the orchestrator as a gate, not a suggestion).

Two checks:

1. **Static SVG-source scan** (pre-conversion, catches missing markers):
   for each `slideNN.svg`, detect shape patterns that look like a hand-drawn
   table (≥2×2 grid of axis-aligned, similarly-sized rects arranged in rows
   and columns) or a hand-drawn bar/pie chart (≥2 axis-aligned rects sharing
   a baseline with varying heights; or ≥2 `path`/wedge-like shapes sharing a
   common center) that are **not** inside a `data-pptx-role="table"/"chart"`
   ancestor. Also detect ≥2 shapes forming a visually clustered
   box+icon+label pattern (bounding-box containment/adjacency heuristic,
   reusing the existing `_compute_text_attachments` containment logic from
   `converter.py`) that are not inside a `data-pptx-role="group"` ancestor.
   Any hit is a hard blocker with a specific remediation message naming the
   offending slide and the required marker.
2. **Post-conversion PPTX assertion** (catches marker/converter bugs): open
   the produced `.pptx` with python-pptx; for every slide the plan records
   as `table`/`bar_chart`/`line_chart`/`pie_chart`, assert a `GraphicFrame`
   with `.has_table` / `.has_chart` is present; for every
   architecture/flow/timeline module, assert its shapes are
   `MSO_SHAPE_TYPE.GROUP`, not N ungrouped top-level shapes at the module's
   region.

Both checks plug into the existing Stage 9 gate and
`presentation_evidence_gates.py` the same way `complex_visual_detector.py`
and `validate_diagram_manifest.py` already do: failure raises
`ProductionGateError` and blocks the workflow transition.

### Manifest schema addition

Add `pptx_construct` to the module manifest schema (`manifest.yaml`),
alongside the existing `editability` field:

| Value | Meaning |
|---|---|
| `native_table` | Real `<a:tbl>` table (`GraphicFrame.has_table`) |
| `native_chart` | Real chart part (`GraphicFrame.has_chart`) |
| `native_group` | Real `MSO_SHAPE_TYPE.GROUP` shape |
| `svg_shapes` | Legacy/fallback — individual ungrouped shapes (pre-existing modules; treated as needing remediation, not a validation crash) |

This is additive: existing manifests without the field default to
`svg_shapes` and are flagged by the new gate for remediation rather than
causing a schema-validation failure.

### Style mapping

`pptx_native.add_native_table` / `add_native_chart` read the same resolved
style dict already used by `generate_slides.py` (`accent`, `card`, `border`,
`good`, `warn`, `danger`, `font`):

- Table: header row fill = `accent`, header text = `white`, alternating row
  fill = `card`/`bg`, borders = `border`, `highlight_col` conditional text
  color = `good`/`danger` (same +/- convention as the existing SVG
  renderer).
- Chart: series colors default to each series' own `color` field (falls
  back to `accent`/`blue` order), gridlines/axis text = `border`/`muted`,
  font = `font`.

Native table/chart styling is constrained to what PowerPoint's table style
and chart style APIs expose — it will not be pixel-identical to the
hand-designed SVG. This trade-off is intentional (per user decision) and is
disclosed via `pptx_construct`, mirroring how `editability` is already
disclosed for hybrid/raster modules.

## Testing

- Unit tests for `pptx_native.py`: table/chart/group construction, style
  mapping, EMU bbox conversion — new `scripts/tests/test_pptx_native.py`.
- Unit tests for the new `data-pptx-role` converter branch — added to
  `scripts/svg_to_pptx/tests/` alongside existing shape/connector tests.
- Unit tests for `validate_native_objects.py` detection heuristics: positive
  fixtures (hand-drawn table/chart/node grids that should be caught) and
  negative fixtures (correctly marked-up SVGs that should pass) —
  `scripts/tests/test_validate_native_objects.py`.
- Extend `evals/report-slides-visual-authoring` and
  `evals/report-slides-pptx-visual-review` with a sample deck containing a
  table slide, a bar/line/pie chart slide, and a complex architecture
  diagram, asserting the gate only passes when native constructs are
  present in the output `.pptx`.

## Non-goals / risks carried forward

- The static SVG-source heuristic (table/chart/node-cluster pattern
  detection) is inherently approximate. It exists only as a safety net for
  forgotten markers, not as the mechanism agents are expected to rely on —
  agents are expected to mark up correctly from the rule change in
  Component D. False negatives here (an unmarked pattern the heuristic
  doesn't catch) are an accepted residual risk, consistent with how
  `complex_visual_detector.py` already accepts threshold-based
  approximation for complexity detection.
- Nested/grouped-within-grouped diagram structures beyond one level are out
  of scope; if a future diagram needs it, the `add_native_group` helper
  already accepts arbitrary shape lists so nesting is a straightforward
  follow-up, not a redesign.
