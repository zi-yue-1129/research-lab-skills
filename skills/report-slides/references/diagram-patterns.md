# Diagram patterns

Choose the route from the semantic job, then keep factual content in editable
objects. The required route defaults are native SVG for architecture and flow,
deterministic data-driven SVG for timeline, statistical, and status views, and
a raster base plus native SVG overlay for hybrid visuals.

## Architecture

- **Default route:** `native` with native SVG.
- **Editable elements:** nodes, labels, groups, boundaries, interfaces, and
  connectors.
- **Semantic inputs:** system boundaries, components, ownership, inputs and
  outputs, interfaces, dependencies, and hierarchy.
- **Layout recipe:** place the main reading direction left-to-right or
  top-to-bottom; group components inside explicit boundaries; align equivalent
  nodes to shared lanes; route connectors around unrelated groups.
- **Failure checks:** every connector has a clear source and destination;
  direction and hierarchy are visible; labels stay attached to their nodes;
  unrelated nodes are not crossed; and no component or interface is implied
  only by color.

## Flowchart

- **Default route:** `native` with native SVG.
- **Editable elements:** steps, decisions, branch labels, terminal states, and
  connectors.
- **Semantic inputs:** ordered actions, decision predicates, branch outcomes,
  success and failure terminals, retry loops, and return paths.
- **Layout recipe:** use one dominant reading direction; give decisions a
  consistent shape; place `yes`/`no` or equivalent labels beside their branches;
  use orthogonal routing and keep return paths outside the main path.
- **Failure checks:** every branch is labeled; no step is orphaned; loops have
  an explicit return target; connectors do not cross unrelated nodes; and the
  reading order remains unambiguous at slide scale.

## Timeline

- **Default route:** `data` with deterministic data-driven SVG.
- **Editable elements:** dates, event labels, intervals, milestones, axis,
  and dependency markers.
- **Semantic inputs:** ordered dates, durations, event text, milestones,
  dependencies, and the time unit or calendar basis.
- **Layout recipe:** use a visible axis and aligned event lanes; use
  proportional spacing when dates carry duration meaning; if spacing is
  intentionally compressed or categorical, disclose that choice in the
  caption or annotation.
- **Failure checks:** event order and dates match the source data; intervals do
  not imply false duration; labels do not collide; milestones are distinct from
  intervals; and compressed spacing is disclosed.

## Statistical

- **Default route:** `data` with deterministic data-driven SVG.
- **Editable elements:** source-data labels, axes, units, ticks, legend,
  series, marks, annotations, and uncertainty indicators.
- **Semantic inputs:** reconstructable source data, units, denominators, series
  names, sample sizes, uncertainty or error definitions, and the intended
  comparison.
- **Layout recipe:** choose a chart form that matches the data; fix the scale
  and units before drawing; keep marks and labels aligned to the same coordinate
  system; include a legend only when it resolves a real mapping.
- **Failure checks:** every mark agrees with source data; axes and units are
  present and honest; scale choices do not mislead; labels and legends match
  the series; uncertainty is not omitted when it changes interpretation; and
  color is not the only carrier of meaning.

## Conceptual

- **Default route:** `generative` for an illustrative image, or native SVG
  when a simple editable metaphor is sufficient.
- **Editable elements:** at least the annotation layer; any factual arrows,
  boxes, labels, legends, and values must be native objects.
- **Semantic inputs:** the audience takeaway, metaphor, subjects, factual
  claims, annotation regions, palette, aspect ratio, and elements that must not
  be interpreted as literal data.
- **Layout recipe:** reserve calm empty regions for factual annotations;
  establish one focal subject and a clear visual hierarchy; keep the generated
  composition supportive of the surrounding slide rather than carrying exact
  claims.
- **Failure checks:** generated pixels contain no fake text or precise values;
  the metaphor does not imply a false scientific structure; annotations remain
  editable and aligned; and image artifacts do not become the slide's factual
  evidence.

## Hybrid

- **Default route:** `hybrid` with a raster base plus native SVG overlay.
- **Editable elements:** factual text, arrows, boxes, callouts, legends,
  labels, values, and any structural guides.
- **Semantic inputs:** the illustrative base, factual overlay content, target
  regions, callout relationships, source data, and image-generation provenance.
- **Layout recipe:** compose the raster base first, then place the SVG overlay
  in the same `1200 x 675` coordinate system; use reserved empty regions for
  annotations; keep all information needed for interpretation out of the
  raster layer.
- **Failure checks:** overlay and raster are aligned; every factual annotation
  is editable; no generated text, legend, or exact value remains in the image;
  the overlay is legible at slide scale; and the manifest declares `hybrid`
  provenance and remaining raster content.

## Status or matrix

- **Default route:** `data` with deterministic data-driven SVG.
- **Editable elements:** rows, columns, cards, state labels, dates, owners,
  symbols, and legend.
- **Semantic inputs:** entities, criteria, state values, dates, owners,
  transitions, and the meaning of each status.
- **Layout recipe:** align entities as rows and criteria as columns, or use
  consistently sized cards; show a text or shape state cue in every cell; keep
  the legend close to the matrix and reserve space for long labels.
- **Failure checks:** statuses and dates match the source; the legend maps to
  every state; stale or missing values are explicit; text remains readable;
  and no decision-critical meaning is conveyed by color alone.
