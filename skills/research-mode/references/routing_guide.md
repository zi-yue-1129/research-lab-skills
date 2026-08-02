# Research Mode — Routing Guide

Maps each work mode to the skills it uses and the behaviors it expects.

## Mode × Skills Matrix

| Mode | Primary Skill | Secondary Skills | Blocked Unless Asked |
|------|--------------|-----------------|----------------------|
| `exp` | research-log (Full) | report-slides | deep-research, academic-pipeline |
| `daily` | — (freeform) | research-log (Quick) | deep-research, academic-pipeline |
| `explore` | deep-research | research-log | academic-pipeline |
| `report` | report-slides | research-log | academic-pipeline |
| `publish` | academic-pipeline | research-log | — |

## Historical Experience Check

Direct research intent triggers the `research-log` protocol even when no mode
is active. When the project has a non-empty `docs/research_log/` journal and
the next action is research planning, recommendation, execution, repetition,
or diagnosis, use `types → search → fetch` before the relevant decision. This
is an evidence check, not a prerequisite for activating a mode.

| Mode | History-check decision point |
|------|------------------------------|
| `exp` | Check before a new setup, run, failure, or rerun. |
| `daily` | Check only when notes lead to a proposed research action. |
| `explore` | Check before committing to a research direction already investigated. |
| `report` | Check only when evidence or decision provenance must be recovered. |
| `publish` | Check when reconstructing decisions, limitations, fixes, or prior evidence. |

For a costly or long-running operation, the history check is a preflight gate:
complete it before execution and disclose a query failure instead of calling it
empty history. General research discussion remains advisory. A missing or empty
journal passes the check. An explicit reproduction, verification, or
changed-condition request may proceed after prior history and its rationale are
made visible.

## Mode Transition Recommendations

| From | To | Trigger |
|------|----|---------|
| `explore` | `publish` | deep-research report complete, ready to write |
| `exp` | `report` | experiment results ready to present |
| `exp` | `publish` | experiment supports a paper submission |
| `publish` | `report` | paper milestone ready for group presentation |
| any | `daily` | no structured output goal, just reading |

## deep-research Sub-Mode Routing

When in `explore` mode, select the deep-research sub-mode based on intent:

| User intent | deep-research mode |
|------------|-------------------|
| "I want to explore / understand this topic" | `socratic` or `full` |
| "I need a systematic review with PRISMA" | `systematic-review` |
| "I need a literature review section" | `lit-review` |
| "I need to verify a specific claim" | `fact-check` |

## ARS Slash Command → Mode Mapping (Phase 3)

When these commands are invoked, auto-activate `publish` mode:

| Command | Pipeline entry point |
|---------|---------------------|
| `/ars-full` | Stage 1 (fresh start) |
| `/ars-plan` | Stage 2 (plan mode) |
| `/ars-outline` | Stage 2 (outline only) |
| `/ars-revision` | Stage 4 (revision) |
| `/ars-revision-coach` | Stage 4 (coached revision) |
| `/ars-abstract` | Stage 2 (abstract only) |
| `/ars-lit-review` | Stage 1 (lit-review mode) |
| `/ars-format` | Stage 5 (format convert) |
| `/ars-citation-check` | Stage 2.5 |
| `/ars-disclosure` | Stage 5 (disclosure) |

Note: ARS command hooks are implemented in Phase 3. This file documents the intended mapping.
