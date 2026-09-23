# Style profile: CM-SAC supervisor rewrite (observed 2026-09-20)

Derived from a sentence-level diff of `CM-SAC_manuscript_en_v3.docx` against
the Markdown sources it was built from. Every pattern below is backed by at
least two instances in that diff. Treat it as a checklist for drafting, and as
a prior for what the same supervisor will change next time.

This is a worked example of the derivation process, kept as the reference
implementation for `SKILL.md`'s "Refreshing this profile" section. It is one
advisor's calibration, not a template to fill in with a different advisor's
name — build a fresh file of this shape from your own advisor's edits instead
of editing this one in place.

## Voice

- **Claim the contribution in the first person.** "Motivated by complementary
  learning systems theory, Cognitive Memory (CM) splits..." became "To address
  this limitation, we propose Cognitive Memory (CM) inspired by complementary
  learning systems theory." Also "Our distance metric", "In our framework".
- **Name the acronym once, then use it.** "interquartile mean" became
  "interquartile mean (IQM)"; "temporal-difference error" became
  "temporal-difference (TD) errors"; "first-in-first-out" became
  "first-in, first-out (FIFO)"; "Cognitive Memory does not alter" became "CM
  does not alter". Method names take title case as proper nouns: "prioritized
  experience replay" became "Prioritized Experience Replay (PER)".

## Sentence construction

- **Open with an explicit connective.** Added: To address this limitation ·
  Nevertheless · Consequently · Similarly · Alternatively · In contrast ·
  However · Notably · Although · While · Since · Finally · Building on this
  architectural design · In terms of computational realizations · Regarding
  memory overhead.
- **Subordinate rather than juxtapose.** Two short independent sentences
  become one complex sentence: "Sampling from the short-term branch weights
  updates toward recently visited states. Sampling from the episodic branch
  broadens geometric coverage..." became "While sampling from the short-term
  branch biases updates toward recently visited states, sampling from the
  episodic branch broadens geometric coverage, albeit at the cost of...".
- **Demote a short sentence to a parenthesis.** "The three arms differ only in
  memory management and sampling. Supplementary Material S8 lists them side by
  side." became "...and sampling (Supplementary Material S8 lists them side by
  side)." Also "(with the full proof deferred to the Supplementary Material)".
- **Announce the next object.** "The proposition below connects the second to
  the memory's geometric coverage." became "To evaluate how effectively the
  episodic memory bounds this extrapolation error across the reachable state
  space, we introduce the geometric notion of a covering radius, formalized in
  the following proposition." Also "formalized by the following".

## Typography and numbers

- **Numerals, not words**: "thirty-five runs" became "35 runs" everywhere.
- **Colon at a run-in list head**: "**Direct measurement of memory
  coverage.**" became "**Direct measurement of memory coverage:**", for every
  contribution item.
- **No colon before a display equation**: "maximizes expected return and
  policy entropy jointly:" became "...jointly", the equation carrying the
  sentence's punctuation instead.

## Verb register

Raised throughout: use → utilize · places → instantiates · steers → guides ·
rests on → hinges on · meets → suffers from · weights → biases · balances →
dynamically balances · acts on → targets.

## What to watch for, every time

- **Hedges get compressed away.** This rewrite dropped: the matched-capacity
  control still to be run (abstract), the note that $\lambda = 0.5$ follows
  from symmetry rather than a sweep, and the rationale for never putting
  success rate and episode return on one figure. Surface each one. The author
  decides.
- **Numbers are as old as the build.** This `.docx` carried a superseded
  Acrobot-swingup row and had no section for the newest experiments.
- **Slips arrive with the rewrite.** Observed: "keep the only the",
  "log-term coverage", "traditional lookup table suffer", "Since, the critic",
  "Let ... denotes", "representing recent data term", "CM mechanism",
  "While Sampling", "all experiments fixe", "DMControl task", "Finaly".
  Fix them, and list every fix.
- **Inline editorial notes are tasks.** This rewrite carried
  "Supplementary Material S9(改成表格)" in the body text, meaning "turn S9
  into a table". That is a to-do, not manuscript prose.
