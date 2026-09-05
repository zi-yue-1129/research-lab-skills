# Style anchors

A style anchor is the visual language an illustration must belong to, and it is
identified by **reference images**, not by words. Spec §D6 requires this, and
§2.1 is the evidence: the prompt behind this deck's own failed illustration
already excluded `busy background`, `excessive glow`, and `photorealistic
faces`, and still produced a lab-coated figure at a laptop beneath a glowing
neural sphere. Adjective lists — even lists of exclusions — name a region of the
image model's prior, and that prior is the look being rejected. An image is not.

## This registry ships empty

`anchors.yaml` contains `anchors: []`. While it is empty:

- `style_anchors.get_anchor(...)` raises `AnchorError`;
- `anchor_available()` returns `False`;
- `scripts/validate_generative_prompt.py` rejects every generative record;
- every module that would have used generative illustration downgrades to a
  native editorial composition, per spec §D6's final clause.

That is the designed resting state. **Do not seed the registry with prose-only
entries to reopen the route** — an entry without `reference_images` is refused
by the loader, and `tests/test_style_anchors.py` asserts the shipped registry is
empty.

## Procedure for adding an anchor

1. **Curate 3–5 reference images.** They must be images this project is licensed
   to keep, and they must agree with one another: an anchor whose references
   disagree cannot rank a candidate. Do not use generated images as references —
   that closes the loop this registry exists to open.
2. **Commit them** under
   `references/style-anchors/<anchor-id>/`, using stable, descriptive names.
3. **Record each digest**:
   `sha256sum references/style-anchors/<anchor-id>/*.png`
4. **Write the entry** in `anchors.yaml` with every required field, listing each
   reference under `reference_images` with its `path` (relative to
   `references/style-anchors/`) and `sha256`.
5. **Write the prose fields against the images.** `composition` and
   `line_treatment` say what to attend to *in those references*; they do not
   stand in for them. `palette_roles` must name roles the design-token file
   defines; `forbidden` names what the anchor refuses.
6. **Update `test_the_shipped_registry_is_empty_by_design`** in the same commit,
   and say in the commit body whose references were added and under what
   licence.
7. Run `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_style_anchors.py -v`.

A digest mismatch is a hard error on load. If a reference is legitimately
replaced, update its digest in the same commit — an anchor whose references
changed silently is a different anchor, and every illustration ranked against
the old one now belongs to a different deck. That is the `style-drift` finding.

## Candidate anchors to curate first

These are the three visual languages this deck's subject matter calls for. They
are recorded here as *briefs for a curator*, deliberately not as registry
entries: without reference images they would be exactly the adjective lists §D6
refuses.

| The slide is about | Candidate anchor | What the references should show |
|---|---|---|
| How a system is structured, or how data moves through it | `technical-schematic` | Flat drafted diagrams in the manner of a paper figure: orthogonal arrangement on one plane, a single dominant flow direction, generous margin, uniform-weight outlines, flat fills, no perspective, no glow, no shadow |
| A concrete object, sample, or apparatus | `annotated-specimen` | Scientific plates: one centred subject at consistent scale, callout lines to a few labelled parts, plain ground, fine contour lines with restrained flat shading, no rim lighting, no background scenery |
| A relationship between measured quantities | `quantitative-abstract` | Non-figurative compositions built only from the quantities under discussion, one clear reading order, flat marks and rules, no texture, no illumination, no human figures, no imaginary interfaces |

If no candidate fits a slide, that is a signal the slide may not need a
generative illustration at all. Reach for a deterministic diagram first; see
`references/diagram-patterns.md`.

Anchors are deck-wide, and spec §D6 allows **at most one generative style per
deck**. Adding a second is a design-system decision, not a per-slide
convenience: two overlapping anchors produce a deck that drifts, which is the
`style-drift` finding the art-direction reviewer reports.

## Banned motifs

`scripts/style_anchors.py` also carries `BANNED_MOTIFS`: the specific imagery
that constitutes the failure mode this registry exists to prevent — glowing
neural spheres, flowing light ribbons, abstract data cities, anonymous figures
at laptops, and their neighbours. `scan_for_banned_motifs` refuses a prompt that
asks for one.

The scan reads prompts, not images. A model can still produce a banned motif
unasked; that case is caught at review as a `visual-cliche` or
`stock-ai-composition` finding. The scan is a floor, not a guarantee.
