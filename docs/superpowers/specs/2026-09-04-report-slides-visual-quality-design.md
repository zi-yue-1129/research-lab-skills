# report-slides Visual Quality Remediation — Design

**Status:** Draft
**Date:** 2026-09-04
**Skill:** `skills/report-slides` (v1.1.0 suite)
**Implements plan:** `docs/superpowers/plans/2026-09-04-report-slides-visual-quality.md`

---

## 1. Problem Statement

Decks produced by `report-slides` do not reach professional presentation quality.
Two symptoms are reported:

1. Architecture diagrams and other constructed visuals look amateur.
2. Generated imagery "smells like AI" — it reads as machine-produced stock
   illustration rather than authored art direction.

This document records the investigated causes and the design decisions taken to
address them. It is the argument the implementation plan executes.

---

## 2. Evidence

Every claim below was verified by reading the source in this repository at
commit `3041838`. Line numbers are from that revision.

### 2.1 The shipped example is itself AI stock imagery, and it passed the gate

`examples/report-slides/visual-authoring/assets/research-collaboration/generated.png`
contains: a white-lab-coat researcher at a laptop in a thoughtful pose, a glowing
network-node sphere, flowing light ribbons, an abstract "data city" skyline, in a
blue/teal/amber palette. This is the canonical AI-illustration composition.

Its `prompt.md` already excludes `busy background`, `excessive glow`,
`photorealistic faces`, and `writing or glyph-like marks`. The exclusions did not
prevent the result.

Its `review.json` records `"status": "passed"`. The only `model_vision` finding is
that CairoSVG's default external-resource policy omitted a local PNG on the first
render — a rendering-mechanics issue. No aesthetic finding was raised.

**Conclusion:** negative prompt clauses do not suppress the AI look, because the
look comes from the *composition motifs*, not from surface effects. And the
review gate has no vocabulary with which to object.

### 2.2 Typography is document-scale, not presentation-scale

Font-size literals in `skills/report-slides/scripts/generate_slides.py`:

| Size | Occurrences |
|-----:|------------:|
| 10pt | 9 |
| 13pt | 5 |
| 12pt | 4 |
| 14pt | 2 |
| 11pt | 2 |
| 20pt | 1 (slide title, `frame()`) |
| 38pt | 1 |

`svg_to_pptx/shapes.py::_apply_font` maps the SVG `font-size` number directly to
`Pt(...)`. A `font-size="10"` in the source becomes 10pt in PowerPoint. The deck
is therefore typeset at report-document scale on presentation media.

This is worse than lacking a minimum-size check: the renderer actively sets text
small.

### 2.3 Font family names are truncated by the converter

`skills/report-slides/scripts/svg_to_pptx/shapes.py:217-220`:

```python
ff = style.get("font-family", parent_style.get("font-family", ""))
if ff:
    first = re.split(r"[,\s]+", ff.strip())[0].strip("'\"")
    if first:
        run.font.name = first
```

Splitting on `[,\s]+` breaks multi-word family names. The default style font is
`'Helvetica Neue', Arial, sans-serif`, so `run.font.name` is set to `Helvetica`.
Neither `Helvetica` nor `Helvetica Neue` is normally installed on Linux, so the
PPTX silently falls back to a different face than the SVG preview showed. SVG
preview and PPTX export therefore disagree, and neither is the requested font.

### 2.4 Rounded rectangles export as sharp rectangles

`skills/report-slides/scripts/svg_to_pptx/shapes.py:29-45` always calls
`slide.shapes.add_shape(1, ...)` (`MSO_SHAPE.RECTANGLE`) and never reads the
SVG `rx`/`ry` attributes. Every rounded card authored in SVG becomes a
sharp-cornered box in the exported PPTX.

### 2.5 Connectors have no arrowheads

`skills/report-slides/scripts/svg_to_pptx/connector.py:57-68` sets only line
colour and width. `marker-start` and `marker-end` are never parsed. An
architecture diagram exports either with headless lines, or with arrowheads that
were hand-drawn as separate polygons and are therefore no longer attached to the
connector.

### 2.6 Declared style features are dead code

- `svg_to_pptx/style_parser.py:179` defines `apply_gradient_fill()`. Grep finds no
  call site outside `tests/test_style_parser.py`. It is unreachable in production.
- `stroke-dasharray` is listed in `_STYLE_ATTRS` (`style_parser.py:68`) and
  collected into every style dict, but no code path ever applies it.
- `opacity`, `fill-opacity`, and `stroke-opacity` are collected the same way and
  likewise never applied.

### 2.7 `style_tokens_ref` exists but is not enforced

`ModuleSpec` carries a `style_tokens_ref` field, and
`skills/report-slides/scripts/validate_visual_module.py:285-294` validates it:

```python
def _validate_style_tokens_ref(module, prefix, errors) -> None:
    """Require an explicit style-token path or null reference."""
    if "style_tokens_ref" not in module:
        errors.append(f"{prefix}.style_tokens_ref: required string or null")
        return
    value = module["style_tokens_ref"]
    if value is not None and (not isinstance(value, str) or not value.strip()):
        errors.append(f"{prefix}.style_tokens_ref: must be a non-empty string or null")
```

The validator checks that the field is a non-empty string or `null`. It never
resolves the path, never reads the file, and never validates its contents. `null`
is accepted. The field is therefore decorative.

### 2.8 The style system reaches only one of the two rendering routes

`generate_slides.py` accepts `--style` and applies it via `apply_style()`
(`generate_slides.py:69-94`). That is the `data` route (Path A, the deterministic
Python renderer).

Architecture diagrams take the `native` route: an agent hand-authors SVG.
`skills/report-slides/agents/architecture_diagram_worker_agent.md` never mentions
the style file, `_style.md`, or `STYLES.md`. Of the eleven agent definitions, only
`complex_visual_decomposer_agent.md` contains the string at all.

Architecture diagram colours and fonts are therefore improvised per module.

### 2.9 The style contract is a colour map, not a design system

`skills/report-slides/references/styles/STYLES.md` defines the whole schema:
`primary`, `bg`, `body`, `muted`, `border`, `card`, `positive`, `warn`, `danger`,
`font`, `top_bar_h`. Ten flat colours, one font family, one bar height. Each
built-in style file is 18–24 lines.

There is no type scale, spacing scale, baseline grid, corner radius, elevation,
stroke-weight hierarchy, chart palette derivation, icon specification, density
budget, or layout recipe. Eleven worker agents each invent geometry per module.

### 2.10 No automatic layout exists

Grep for `dagre`, `elkjs`, `graphviz`, `networkx`, `auto-layout`, and
`force-directed` across the repository returns nothing. Node coordinates are typed
by hand by the authoring agent for every diagram.

Mermaid is offered as an alternative in
`architecture_diagram_worker_agent.md` but is explicitly downgraded: Mermaid SVG
cannot carry `data-pptx-role` markers, so choosing it forfeits native PPTX
grouping and must be recorded as `pptx_construct: svg_shapes`.

### 2.11 Quality gates are prose, adjudicated by the same model

`skills/report-slides/references/visual-review.md:88-95` states the complete-slide
gate as: density and balance "support the narrative"; alignment, spacing and
margins are "consistent"; typography is "readable on a projected screen";
contrast is "sufficient".

There are numeric thresholds elsewhere in the skill —
`references/complex_visual_thresholds.yaml`, `references/native_object_thresholds.yaml`,
and example pixel-delta bounds — but none of them are aesthetic. No minimum font
size, no grid quantum, no contrast ratio, no spacing tolerance exists anywhere in
the skill.

`scripts/validate_visual_review.py` validates the *structure* of the review record
and the existence of its evidence paths. It does not inspect pixels.

### 2.12 The reviewer's remit excludes art direction

`skills/report-slides/agents/visual_quality_reviewer_agent.md:20-30` enumerates the
complete finding vocabulary: `clipping`, `overlap`, `text-reflow`,
`connector-drift`, `crop`, `unreadably-small-text`, `missing-image`, `z-order`,
`alignment`.

Every one of these is a rendering defect. The agent has no category for weak
composition, visual cliché, decorative noise, stock-AI imagery, style drift, or
absent typographic hierarchy. A slide can be competently rendered and still be
mediocre, and this rubric will pass it. Replacing the model behind the agent would
not change that — the rubric is the limit.

### 2.13 Modules are composed, never re-laid-out

`skills/report-slides/agents/visual_integration_agent.md:8` instructs the
integration stage to "compose, do not create", and forbids reworking modules.

Modules are therefore designed independently and assembled afterwards. No stage
holds authority to reflow a slide after seeing it whole. Professional slide design
works in the opposite order: whole-slide composition first, components second.

### 2.14 Route guidance is internally inconsistent

`skills/report-slides/agents/research_narrative_planner_agent.md:38` describes the
`generative` route as suitable for "diagrams". `references/diagram-patterns.md`
and `architecture_diagram_worker_agent.md` state that architecture and flow
default to `native` SVG. A planner following the former will route diagrams into
image generation.

### 2.15 Silent failures in the style path

- `generate_slides.py::apply_style` (line 69) returns silently when frontmatter
  parses empty, leaving built-in defaults in place with no error. A typo in a style
  file is indistinguishable from success.
- `style_parser.py::apply_gradient_fill` returns silently when `spPr` is absent.

Both violate the repository's no-silent-failures rule in `~/.claude/CLAUDE.md`.

---

## 3. Evaluation: skechu-ppt integration

**Question asked:** would deeply integrating
`https://github.com/evan6007/skechu-ppt` improve output quality?

**Answer: no. Reject deep integration.**

### 3.1 What the project is

Verified by reading a clone of the repository:

- A dependency-vendored, no-build, browser-based **interactive vector tracing
  editor**. A human imports a raster reference and traces it with magnetic edge
  snapping, or runs auto-trace (centreline for line art, closed outlines for
  logos). Output is SVG or a `.skc` project file.
- `app/bridge.py` (1029 LOC, `pywin32`) is the only server-side automatable
  component. It drives **Windows COM** against desktop PowerPoint to build native
  shapes: `BuildFreeform`/`AddNodes` Bézier freeforms, `Line.BeginArrowheadStyle`,
  `Line.EndArrowheadStyle`, `Line.DashStyle`, `Fill.Transparency`, groups, and a
  small `latex_to_unicode` regex table.
- There is no headless mode, no CLI, and no HTTP API for diagram *generation*.
  The tool generates nothing; it digitises what a human draws.

### 3.2 Why deep integration is rejected

1. **It does not address the diagnosed cause.** The defects in §2 are art
   direction, typography, token enforcement, and review rubric. Tracing does not
   fix a crowded diagram, a 10pt label, or an AI-cliché illustration.
2. **It requires a human at a GUI.** `report-slides` is an autonomous agent
   pipeline. Introducing a mandatory interactive step inverts its design.
3. **Its unique capability is already implemented, better.**
   `skills/report-slides/scripts/svg_to_pptx/` (1774 LOC, python-pptx + lxml) is a
   headless, cross-platform, unit-tested SVG → native PPTX converter that already
   materialises `data-pptx-role` markers into real PPTX Group, Table, and Chart
   objects.
4. **The native path is Windows-only.** It requires Windows COM and desktop
   PowerPoint. The target environment is Linux, where that path cannot run at all.

### 3.3 What is adopted instead

The *capabilities* `bridge.py` demonstrates are worth having; the *code* is not
transplantable. Implement them natively in the existing converter:

| Capability | Decision |
|---|---|
| Arrowhead styles | Implement by parsing SVG `marker-start`/`marker-end` into OOXML `a:headEnd`/`a:tailEnd`. Task 8. |
| Dash styles | Implement by parsing `stroke-dasharray` into OOXML `a:prstDash`. Task 9. |
| Fill transparency | Implement by parsing `opacity`/`fill-opacity`/`stroke-opacity` into `a:alpha`. Task 9. |
| Bézier freeform construction | **Not adopted.** `svg_to_pptx/path_parser.py` and `path_to_pptx.py` already build native custom geometry with curves. |
| `latex_to_unicode` | **Not adopted.** It is a small regex substitution table adequate for `σ` and subscripts, not robust equation rendering. If maths support is needed, use LaTeX → OMML/MathML or LaTeX → SVG path. Out of scope here. |

### 3.4 Retained role for skechu-ppt

A documented **manual asset-intake adapter**, not a pipeline dependency: when the
diagnosed need is "a human must trace or repair complex reference geometry"
(a logo, a line-art figure, an organic contour from a scan or micrograph), a human
may use the web editor, export SVG, and feed it to the existing converter,
preserving the `.skc` source in the asset manifest.

The trigger is the *diagnosis*, not a failure count. "Visual review failed twice"
is explicitly rejected as a routing condition: crowded layout, weak hierarchy, and
small type are not repaired by tracing.

On Linux the usable path is browser editor → SVG → existing converter. Native
PowerPoint copying remains unavailable and is not planned for.

---

## 4. Design Decisions

### D1 — A validated design-token contract replaces the colour map

Markdown frontmatter is retained only as human documentation. The machine contract
becomes a YAML token file validated against a JSON Schema.

The contract covers:

- **Typography roles** — deck title, slide title, takeaway, body, node label,
  axis, caption, footnote; family, weight, size, line height, max lines.
- **Spacing scale** — `4, 8, 12, 16, 24, 32, 48, 64`.
- **Canvas** — dimensions, safe area, grid quantum.
- **Surfaces** — node/card/callout padding, radius, border width, fill roles.
- **Connectors** — stroke width, arrowhead style and size, dash patterns, minimum
  clearance.
- **Colour roles** — semantic roles plus derived tints, with contrast floors.
- **Chart** — categorical palette, chart-specific type roles.
- **Icons** — family, optical size, stroke width, and the conditions under which
  icons are *forbidden*.
- **Density budgets** — occupancy bounds, max distinct type sizes per slide, max
  bullets.

Rationale for a schema rather than more Markdown: §2.7 shows an unvalidated
reference field is equivalent to no field. The contract must be machine-checkable
or it will not be honoured.

### D2 — Typography floors are set for presentation media

For the fixed `1200 × 675` canvas, exported 1:1 as PowerPoint points:

| Role | Size |
|---|---|
| Slide title | 30–36 |
| Takeaway | 24–30 |
| Body | 20–24 |
| Node label | ≥ 18 |
| Axis / legend | ≥ 16 |
| Footnote | ≥ 12, exceptional |

These become both renderer defaults (§2.2) and linter hard errors (D4).

### D3 — `style_tokens_ref` becomes mandatory and resolved

`null` is no longer accepted. The validator resolves the path, parses the token
file, validates it against the schema, and records its digest. A missing or
malformed token file is a hard error, not a fallback to built-in defaults. This
closes §2.7 and §2.15.

### D4 — A measurable visual linter, separate from the prose gate

A new deterministic checker operates on the authored SVG plus the resolved token
set. Hard errors fail the build; warnings are reported to the art-direction
reviewer for judgement.

**Hard errors**

- Non-bleed content outside the safe area (48px horizontal, 36px vertical).
- Text below the role minimum in D2.
- Text contrast below 4.5:1; large text and non-text graphics below 3:1.
- Unintended shape or text overlap.
- Connector crossing a node interior; dangling endpoint; endpoint more than 4px
  from its declared port.
- Node internal padding below 16px horizontal or 12px vertical.
- Node-to-node gap below 24px; connector clearance below 12px.
- A colour not present in, or derivable from, the active token set.
- Repeated semantic components differing in radius, stroke, type role, or padding.
- A hand-drawn arrow polygon where a connector with an arrowhead is required.

**Warnings**

- Eligible edges more than 2px off the 8px grid.
- Repeated gap or size variance greater than 4px.
- More than four distinct type sizes on one slide.
- Title over two lines; body over ~90 words; more than six bullets; node label
  over three lines.
- More than one unintended connector crossing.
- Content occupancy below 30% or above 78%.
- Excessive equal-card repetition where hierarchy calls for differentiated
  emphasis.

Text extents are measured with real font metrics, not character-count estimates.

### D5 — The review stage is split in two

`visual_quality_reviewer_agent` is renamed `render_integrity_reviewer_agent`,
keeping its existing defect vocabulary unchanged (§2.12 shows the rubric is
correct for what it covers; the problem is that nothing covers the rest).

A new `art_direction_reviewer_agent` judges the **complete slide**, not isolated
modules, and — unlike the integration stage (§2.13) — is permitted to require
re-layout, removal of decoration, or a different visual representation.

Its finding vocabulary: `visual-cliche`, `decorative-noise`, `style-drift`,
`synthetic-detail`, `meaningless-interface`, `stock-ai-composition`,
`weak-hierarchy`, `undifferentiated-repetition`.

### D6 — Generative imagery becomes opt-in and anchored

- Generative illustration is no longer a default method for filling an empty
  slide. It requires an explicit justification recorded in the module spec.
- A banned-motif list is enforced by the reviewer, naming the actual cliché
  compositions rather than surface effects: glowing brains, neural globes,
  holographic interfaces, ambient circuitry, flowing data streams, floating
  translucent panels, isometric server cities, lens flare, teal-orange haze, and
  anonymous "person at a laptop" scenes.
- A **style anchor registry** holds 2–3 curated house illustration styles, each
  identified by actual reference images with recorded digests — not adjective
  lists. §2.1 shows adjective exclusions do not work.
- Three candidates are generated and ranked blind against the anchor.
- At most one generative style per deck.
- If no candidate matches the anchor, the module downgrades to a native editorial
  composition. Accepting the least-bad image is prohibited.

Populating the anchor registry with reference images is a human action; this
design specifies the mechanism and ships the registry empty with a documented
procedure.

### D7 — Route guidance is made consistent

`research_narrative_planner_agent.md:38` is corrected so that `generative` is not
offered for diagrams, matching `diagram-patterns.md`.

---

## 5. Non-Goals

- **Automatic graph layout (ELK/Graphviz/dagre).** §2.10 is a real defect and
  auto-layout is the right eventual answer, but it is a distinct subsystem: it
  needs a semantic scene-graph schema, a new external runtime dependency, and a
  re-rendering adapter that preserves `data-pptx-role` grouping (engine-produced
  SVG must never be consumed directly). It should be designed against the token
  contract established here, not in parallel with it. Deferred to a separate
  design and plan.
- **Equation rendering.** Noted in §3.3; out of scope.
- **Replacing the evidence, manifest, transaction, or provenance machinery.** It
  is not implicated in any defect in §2.
- **Changing the `1200 × 675` canvas or the PPTX export pipeline.**
- **Icon asset library.** The token contract specifies icon *rules*, including
  when icons are forbidden. Shipping an icon set is separate work; mandatory
  decorative icons are themselves a generated-deck signature and are not desired.

---

## 6. Success Criteria

1. A deck rendered by the deterministic renderer uses no text below the D2 floors.
2. `style_tokens_ref` cannot be `null`; an invalid token file fails the build.
3. The native SVG route resolves the same token set as the deterministic route.
4. Arrowheads, dash patterns, opacity, rounded corners, and multi-word font
   families survive SVG → PPTX export.
5. The visual linter runs in the workflow and fails a deck that violates any D4
   hard error.
6. A slide that renders cleanly but is compositionally weak can be failed, by an
   agent with a finding vocabulary that can name the problem.
7. The example asset in §2.1 either passes an explicit anchor comparison or is
   replaced. It cannot pass silently.
