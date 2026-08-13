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
visual-authoring gate (vision review needs pixels), but stop treating SVG as
the source of truth for the *final* PPTX when the content is a table, chart,
or a semantic multi-shape node. Add a second, structured path that builds
these constructs directly with python-pptx's native APIs.

```
                    ┌─────────────────────┐
                    │  slide_data.json     │  (Path A, existing schema)
                    │  or *.svg + sidecar  │  (Path C, new convention)
                    │  data-pptx-role=...  │
                    └──────────┬───────────┘
                               │
                 ┌─────────────┴──────────────┐
                 │                             │
        preview / vision review        final PPTX assembly
        (existing SVG renderer,        (NEW: scripts/pptx_native.py)
         unchanged)                     add_native_table / add_native_chart
                                         / add_native_group
                                                │
                                                ▼
                                   scripts/svg_to_pptx/converter.py
                                   (existing shape/connector dispatch,
                                    + NEW data-pptx-role branch that
                                    calls pptx_native instead of
                                    flattening the subtree)
                                                │
                                                ▼
                                     validate_native_objects.py
                                   (NEW gate: static SVG scan +
                                    post-conversion PPTX assertions)
```

## Components

### A. `scripts/pptx_native.py` (new)

A small library wrapping python-pptx's native object construction. Used
directly by Path A's PPTX assembly step and by the converter's new
`data-pptx-role` branch in Path C.

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

### B. Path A — dual output in `generate_slides.py`

SVG rendering (`render_table`, `render_bar_chart`, `render_timeline`)
continues unchanged and remains the Stage 9 preview/vision-review artifact.

The PPTX assembly step (currently `to_pptx()` / the `svg_to_pptx` converter
run over Path A's SVGs) changes per slide type:

- `table`, `bar_chart`, `line_chart` (new), `pie_chart` (new): do not convert
  the SVG's shapes for these slides. Instead, read the slide's entry from
  `slide_data.json` and call `pptx_native.add_native_table` /
  `add_native_chart` directly, placed at the SVG frame's content bbox
  (the existing `CL, CR, CT, CB` / table `tl, tr, top_y` constants, converted
  to EMU). Title/footer chrome (the `frame()` header/footer bar) still comes
  from the SVG conversion as ordinary shapes, since that part is decorative,
  not data.
- `timeline`: SVG conversion proceeds as today (dots, connectors, labels as
  individual shapes), but immediately after each event's shapes are placed,
  `add_native_group` wraps that event's circle + connector + label(s) into
  one Group. Event boundaries are known because Path A's assembly step has
  the same `events` list used to render the SVG — it doesn't need to infer
  grouping from pixels.

`line_chart` and `pie_chart` are new `slide_data.json` slide types, added
alongside `bar_chart` with an equivalent schema (`categories`/`series` for
line; `categories`/single `series` of values for pie). Their SVG preview
renderers (`render_line_chart`, `render_pie_chart`) are new, minimal, and
only need to be good enough for the vision-review gate — they are not the
final output.

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

`data-pptx-source` points to a sidecar JSON file (same directory as the
`.svg`) using the identical schema as Path A's `slide_data.json` table/chart
entries. `data-pptx-bbox` is `"x,y,w,h"` in the SVG's own user units (the
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
