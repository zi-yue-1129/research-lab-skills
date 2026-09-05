# RETAINED AS A COUNTER-EXAMPLE. This record predates the generative contract in
# references/generative-visuals.md and is rejected by
# scripts/validate_generative_prompt.py. See WHY-THIS-FAILS.md.

purpose: Support a research report slide about researcher and AI collaboration.
composition: Wide 16:9-friendly scene with the human researcher on the left, abstract AI compute and data motifs on the right, and clean negative space along the lower third and center-right for editable SVG callouts.
subject: A researcher collaborating with an abstract AI laboratory in a calm modern workspace.
palette: Restrained blue, teal, amber, and neutral tones.
lighting: Calm, thoughtful, high-trust, softly lit.
empty_annotation_regions:
  - lower third
  - center-right
exclusions:
  - text
  - numbers
  - labels
  - legends
  - charts
  - logos
  - signatures
  - watermarks
  - factual claims embedded in pixels
  - tiny illegible details
  - busy background
  - excessive glow
  - photorealistic faces
  - cropped subjects
  - writing or glyph-like marks
aspect_ratio: 16:9
references: []
changed_regions: []

generation_prompt: >-
  Use case: productivity-visual. Asset type: project-bound hybrid presentation illustration for a research report slide. Primary request: a polished wide conceptual illustration of a researcher collaborating with an AI laboratory in a calm modern workspace, with the human researcher on the left and abstract AI compute/data motifs on the right, connected by subtle flowing light and circuit-like pathways. Composition/framing: wide 16:9-friendly scene with generous clean negative space along the lower third and around the center-right for separate editable SVG labels and callouts. Style/medium: editorial scientific illustration, restrained vector-inspired painterly forms, crisp readable silhouettes, cohesive blue/teal/amber palette. Lighting/mood: calm, thoughtful, high-trust, softly lit. Constraints: no text, no numbers, no labels, no legends, no charts, no logos, no signatures, no watermark, no factual claims embedded in pixels; keep all factual annotations for an editable overlay. Avoid: tiny illegible details, busy background, excessive glow, photorealistic faces, cropped subjects, any writing or glyph-like marks.

disclosure: The generated bitmap contains no factual labels/text/numbers; factual overlays are separate editable SVG objects.
