# Formal explicit voice

Prescriptive rules for formal academic English in which every sentence states
its relation to the last, claims are made in the first person, and the verb
register is raised. Each rule was observed at least twice in one supervisor's
rewrites of a manuscript; the evidence is in `derivation_evidence.md`. Apply
the rules when drafting, and run the checklist at the end when revising.

Rules 6 to 8 (acronyms, numerals, punctuation) are close to conventions most
venues share. Rules 1 to 5, 9 and 10 are this voice's habits: use them because
this voice is the one wanted, not as general advice.

The `writing-voice` guardrails (never drop a limitation, never let a
strengthened verb outrun its evidence, never let style touch a number) outrank
every rule below.

---

## 1. Claim the work in the first person

The contribution belongs to the authors, so say so. Impersonal constructions
that hide the agent get rewritten.

> **Instead of:** Motivated by complementary learning systems theory,
> Tiered Replay Memory (TRM) splits the buffer into two tiers.
> **Write:** To address this limitation, we propose Tiered Replay Memory (TRM)
> inspired by complementary learning systems theory.

Also "Our distance metric is most closely related to...", "In our framework,
the same quantity serves a different end."

Keep the first person for what the authors did. Results still speak in the
third person: "TRM-SAC's point estimate exceeds the baseline's on six of seven
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
- After Section III, "Tiered Replay Memory does not alter..." → "TRM does not
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
> reduced budget. The loss-based prioritization baseline, at the same slots, rules transition-slot capacity out
> but also changes the sampling rule.
> **Write:** While the baseline comparison demonstrates the efficacy of
> geometric retention under a constrained budget, evaluating against a loss-based
> prioritization baseline (at the same $3 \times 10^6$ slots) conflates capacity constraints with altered
> sampling rules.

---

## Revision checklist

Run over a draft, in order, before `writing-voice`'s guardrail checks:

1. Does each paragraph's first sentence say how it follows from the last?
2. Any two adjacent short sentences on one idea? Subordinate one.
3. Any pointer sentence? Make it a parenthesis.
4. Every acronym expanded exactly once, at first use?
5. Any spelled-out number? Any semicolon? Any em dash? Any colon before a
   display equation? Any run-in list head ending in a period?
6. Is every proposition, table and figure announced before it appears?
