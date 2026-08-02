# Visual review

## Render before review

Render every individual visual or subfigure and every complete slide to PNG or
JPEG before review. Inspect the visible pixels with model vision at both levels;
do not infer visual quality from SVG markup, source code, manifest fields, or a
PPTX object tree. A review sheet may arrange already-rendered images, but it
does not replace inspection of those images.

Review the subfigure and complete-slide renders after every revision. Preserve
the failing render when a finding needs diagnosis.

## Subfigure gate

The subfigure passes only when all of these are true:

- semantic content is correct and complete;
- reading order and visual hierarchy are clear;
- connector direction, attachment, and crossings are correct;
- labels, legends, scale, and proportions are placed and readable;
- visual focus is intentional and decoration is necessary; and
- generated imagery has no artifacts, fake text, or misleading structures.

## Complete-slide gate

The complete slide passes only when all of these are true:

- density and balance support the narrative;
- alignment, spacing, and margins are consistent;
- typography is readable on a projected screen;
- contrast is sufficient and meaning is not carried by color alone;
- styling matches the deck and equivalent visuals; and
- there is no clipping, overlap, overflow, or unintended empty region.

The following conditions always fail the gate:

- clipped, overlapping, truncated, or unreadably small text;
- arrows with incorrect direction or connectors crossing unrelated nodes;
- chart marks that disagree with their source data;
- color as the only carrier of meaning;
- fake text or misleading scientific structure in generated imagery;
- inconsistent styling among equivalent visual elements;
- a modified reused visual without region-level change disclosure; and
- undisclosed rasterization of information expected to be editable.

## Revision loop

For every failed finding, identify the responsible source file or layer and
revise it. Re-render both the subfigure and complete slide, then inspect both
pixel outputs again. Continue until both gates pass. Keep the source, manifest,
and review record aligned with the final render; remove temporary review marks
from the delivered slide.

## Review record

Write `review.json` beside the visual's manifest and point to it from
`review.artifact`. Record the rendered artifacts, number of revision rounds,
and each finding with its level, region, issue, and corrective action. A
passing record for the latest render has this shape:

```json
{
  "status": "passed",
  "artifacts": ["subfigure.png", "slide04-review.png"],
  "rounds": 2,
  "findings": [{
    "round": 1,
    "level": "slide",
    "region": "evaluation-stage",
    "issue": "Connector crossed the publishing label.",
    "action": "Routed the connector below the label."
  }]
}
```

Source-markup inspection is not visual review. Structural manifest validation,
PPTX validation, and pixel review are separate completion signals.

## Blocked review

Missing rendering, missing vision capability, unavailable required tools, or an
environment failure that prevents inspection is an explicit blocker. Missing
factual inputs is also a blocker for the affected visual. Record the blocker,
retain any failing render, and do not mark `review.json` as passed, export the
visual as final, or call the deck complete. A blocked review must resume with
the missing evidence or capability; it is not completion.
