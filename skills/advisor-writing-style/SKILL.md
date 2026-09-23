---
name: advisor-writing-style
description: "Write academic English in a lab advisor's voice. A prescriptive style guide distilled from a professor's own rewrites of one lab's manuscripts: first-person contribution claims, explicit connectives, subordinated clauses, acronym discipline, numerals, run-in list colons, and a raised verb register. Apply when drafting or revising a paper, abstract, response letter, or supplementary section for a lab that has calibrated this profile against its own advisor's edits. Triggers: write in the professor's style, advisor style, lab writing style, 教授的寫法, 教授風格, 用教授的風格改寫, polish this paragraph, academic English polish."
metadata:
  version: "1.0.0"
  last_updated: "2026-09-20"
  status: active
  data_access_level: verified_only
  task_type: open-ended
  related_skills:
    - academic-paper
    - academic-paper-reviewer
    - academic-pipeline
---

# Advisor Writing Style

How one lab's advisor writes academic English, stated as rules you can draft
against. Every rule below is taken from that professor's own edits to the
lab's manuscripts, with the real before and after. Apply it when drafting, and
run it as a checklist when revising.

`references/derivation_evidence.md` holds the raw observations and the
instances each rule rests on, for the profile this skill ships with.

## Calibrating this to your own advisor

This profile is one lab's calibration, not a universal house style. Two
advisors do not write alike. Before applying rule 9 (raised verb register) or
rule 3 (subordination) to your own manuscript, confirm they hold for your own
advisor's edits — see "Refreshing this profile" below for how to derive your
own version of `references/derivation_evidence.md` from a `.docx` your
advisor returned. Rules 6 through 8 (acronym discipline, numerals,
punctuation) are closer to house-style conventions most venues share, and are
a reasonable default even before calibration.

---

## 1. Claim the work in the first person

The contribution belongs to the authors, so say so. Impersonal constructions
that hide the agent get rewritten.

> **Instead of:** Motivated by complementary learning systems theory,
> Cognitive Memory (CM) splits the buffer into two tiers.
> **Write:** To address this limitation, we propose Cognitive Memory (CM)
> inspired by complementary learning systems theory.

Also "Our distance metric is most closely related to...", "In our framework,
the same quantity serves a different end."

Keep the first person for what the authors did. Results still speak in the
third person: "CM-SAC's point estimate exceeds the baseline's on six of seven
tasks."

## 2. Open with an explicit connective

Nearly every sentence after the first announces its relation to the one
before. The reader should never have to infer the turn.

Use: *To address this limitation · Nevertheless · Consequently · Similarly ·
Alternatively · In contrast · However · Notably · Although · While · Since ·
Finally · Building on this · In terms of · Regarding ·*

> **Instead of:** All alter how a sample is used. The retention rule remains
> first-in-first-out.
> **Write:** Although these approaches effectively optimize how samples are
> utilized, the underlying memory management still strictly adheres to a
> simple first-in, first-out (FIFO) retention policy.

## 3. Subordinate, do not juxtapose

Two short independent sentences on one idea become one complex sentence, the
weaker clause subordinated.

> **Instead of:** Sampling from the short-term branch weights updates toward
> recently visited states. Sampling from the episodic branch broadens
> geometric coverage, at the cost of drawing on transitions collected under
> older policies.
> **Write:** While sampling from the short-term branch biases updates toward
> recently visited states, sampling from the episodic branch broadens
> geometric coverage, albeit at the cost of drawing on transitions collected
> under historical policies.

## 4. Demote a housekeeping sentence to a parenthesis

A sentence that only points somewhere does not deserve to be a sentence.

> **Instead of:** The three arms differ only in memory management and
> sampling. Supplementary Material S8 lists them side by side.
> **Write:** The three arms differ only in memory management and sampling
> (Supplementary Material S8 lists them side by side).

Also "...follows that argument's form (with the full proof deferred to the
Supplementary Material)."

## 5. Announce the next object before it arrives

A proposition, table or figure is introduced by a sentence that says what it
is for.

> **Instead of:** The proposition below connects the second to the memory's
> geometric coverage.
> **Write:** To evaluate how effectively the episodic memory bounds this
> extrapolation error across the reachable state space, we introduce the
> geometric notion of a covering radius, formalized in the following
> proposition.

Also "...formalized by the following."

## 6. Acronym discipline

Expand once with the acronym in parentheses, then use the acronym only.
Method names are proper nouns and take title case.

- "interquartile mean" → "interquartile mean (IQM)", then "IQM"
- "absolute temporal-difference error" → "absolute temporal-difference (TD)
  errors"
- "first-in-first-out" → "first-in, first-out (FIFO)"
- "prioritized experience replay (PER)" → "Prioritized Experience Replay
  (PER)"
- After Section III, "Cognitive Memory does not alter..." → "CM does not
  alter..."

## 7. Numerals, not words

"thirty-five runs" → "35 runs". Applies everywhere, including counts inside
prose.

## 8. Punctuation conventions

- **Run-in list heads take a colon**, not a period:
  `**Direct measurement of memory coverage:** A Voronoi Monte Carlo
  estimate...`
- **No colon before a display equation.** The equation carries the sentence's
  punctuation: "...SAC maximizes expected return and policy entropy jointly"
  followed by the equation.
- **No semicolons and no em dashes** in the English edition. Split into
  sentences instead.

## 9. Raised verb register

use → utilize · places → instantiates · steers → guides · rests on → hinges
on · meets → suffers from · weights → biases · balances → dynamically
balances · acts on → targets · is → acts as

Do not let this reach the results. A measurement still "is" what it is.

## 10. Frame a comparison by what it establishes

State the conclusion of a comparison, then its limit, in one sentence.

> **Instead of:** The baseline comparison bears on geometric retention at a
> reduced budget. ReLo, at the same slots, rules transition-slot capacity out
> but also changes the sampling rule.
> **Write:** While the baseline comparison demonstrates the efficacy of
> geometric retention under a constrained budget, evaluating against ReLo (at
> the same $3 \times 10^6$ slots) conflates capacity constraints with altered
> sampling rules.

---

## Guardrails

The style is a way of writing, not a licence to change what the paper claims.
Three of the advisor's habits conflict with research integrity, and the rules
above stop at each one.

- **IRON RULE — never drop a limitation to tighten a sentence.** Compression
  is where hedges die. Observed losses in one rewrite: a control still to be
  run, the note that a hyperparameter was fixed by symmetry rather than swept,
  and the rationale for keeping two metrics on separate figures. If the style
  makes a caveat awkward, give the caveat its own sentence. Then tell the
  author what you moved.
- **IRON RULE — "demonstrates the efficacy" needs the statistics to say so.**
  The raised register makes claims sound stronger. Check each strengthened
  verb against the test that backs it. If nothing survives correction, the
  sentence says so.
- **IRON RULE — style never touches a number.** Numerals replace spelled-out
  words; they never replace a value. Figures come from the analysis pipeline.

## Revision checklist

Run over a draft, in order:

1. Does each paragraph's first sentence say how it follows from the last?
2. Any two adjacent short sentences on one idea? Subordinate one.
3. Any pointer sentence? Make it a parenthesis.
4. Every acronym expanded exactly once, at first use?
5. Any spelled-out number? Any semicolon? Any em dash? Any colon before a
   display equation? Any run-in list head ending in a period?
6. Is every proposition, table and figure announced before it appears?
7. **Is every caveat still present and still true?**
8. Does any strengthened verb outrun its evidence?

## Refreshing this profile

When the advisor returns a newly edited `.docx`, `scripts/docx_text.py` and
`scripts/sentence_diff.py` extract its text and align it against the Markdown
sources sentence by sentence. Add whatever recurs to
`references/derivation_evidence.md` and promote it to a rule here once it has
two instances.

Starting this profile fresh for a different advisor: keep this file's
structure and the two scripts, replace the rules above and
`references/derivation_evidence.md` with what the new diff actually shows,
and drop any rule that does not recur at least twice. Do not carry a rule
across advisors on the assumption that academic style is universal — rules 1
through 5, 9 and 10 here are this one advisor's habits, confirmed by their own
edits, not a general prescription.
