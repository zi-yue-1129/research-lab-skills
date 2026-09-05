# Why this asset fails, and why it is kept

This directory is a counter-example. It is retained because it is the evidence
behind the visual-quality redesign, not because it is a model to follow.

## What was shipped

A generated illustration: a figure in a white lab coat at a laptop, a glowing
neural-network sphere, flowing light ribbons, and an abstract data-city skyline,
in blue, teal, and amber. Its `review.json` recorded `"status": "passed"` with a
single finding, and that finding was about CairoSVG's external-resource policy —
a rendering note, not a judgement about the picture.

## The verdict under the art-direction vocabulary

- **`visual-cliche`** — the glowing neural sphere, the flowing light ribbons,
  and the abstract data-city skyline would serve any deck about any AI system.
  Nothing in them is specific to this deck's subject.
- **`stock-ai-composition`** — the framing is a generator default. "Anonymous
  person at a laptop" is on the banned-motif list in spec §D6 by name, and the
  lab coat was never asked for: the model supplied it because that is what its
  prior returns for "researcher".
- **`decorative-noise`** — the slide's factual content lived entirely in the SVG
  overlay. The bitmap carried no information, and the asset's own `review.json`
  said so, recording that "the bitmap is illustrative atmosphere only".

## What was done about it

The raster layer was **downgraded** out of the deck under the rule in
`agents/conceptual_illustration_worker_agent.md`: an illustration that carries
no information a deterministic diagram could not carry is removed. The SVG
overlay, which carried every factual mark, is now the whole slide.

`generated.png` is kept on disk. This file refers to it, and deleting the
evidence would leave the counter-example unreadable.

## What the automated checks would and would not have caught

`scripts/validate_generative_prompt.py` rejects this `prompt.md`. Run against
the record as shipped it reports six errors, two of which are banned motifs:

```
missing required field: illustration_rationale
missing required field: style_anchor
candidates must be a list of 3 ranked entries
exclusions omit required entries: prose, exact values
prompt asks for banned motif 'light-ribbons'
prompt asks for banned motif 'circuit-board-metaphor'
```

Both motif hits come from one clause of the generation prompt: "connected by
subtle flowing light and circuit-like pathways".

It would **not** have caught the lab coat. The prompt never asked for one; the
image model supplied it, because a figure in a lab coat is what its prior
returns for "researcher". No prompt-text scan can catch that. Only the
art-direction reviewer, looking at the delivered pixels, can — which is why
`art_direction_reviewer_agent` exists as an independent gate rather than as a
lint rule.
