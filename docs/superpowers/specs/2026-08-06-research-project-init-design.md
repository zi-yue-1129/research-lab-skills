# Research Project Initialization — Design Spec

- **Date**: 2026-08-06
- **Status**: Draft, pending user review
- **Author**: Claude (brainstorming session with user)

## Problem

A researcher's first artifact is usually a scattered idea, not a scoped
project: a rough topic, a hunch about what might be worth studying, no
explicit boundaries. Nothing in this repo's skill set turns that idea into
something reviewable and trackable before real work starts. `deep-research`
sharpens a *single* research question (FINER scoring, methodology
blueprint) once one exists, but assumes the user already knows roughly what
question they're asking. There is no step that captures the *project*-level
shape around one or more questions — scope, exclusions, expected
contributions, constraints, resources, milestones, success/stop conditions,
risks, ethics — and nothing separates what the user has *confirmed* from
what is merely *assumed*, *suggested*, or still *open*. `agent-state`
(`docs/superpowers/specs/2026-08-06-unified-research-state-design.md`)
already models a `Project` entity for exactly this purpose, but
`--create-project` has no caller anywhere in the skill set — it is
functional, tested, and unused.

## Goal

A new, independent skill, `research-project-init`, that runs a lightweight
guided dialogue to turn a preliminary idea into:

1. A **project charter** — a Markdown document capturing Problem Statement,
   Scope, Exclusions, Expected Contributions, Initial Research Questions,
   Constraints, Resources, Milestones, Success Criteria, Stop Conditions,
   Risks, and Ethics Considerations, with every item tagged `[confirmed]`,
   `[assumption]`, `[suggestion]`, or `[open]`.
2. A **Project record** in `agent-state`, created via `--create-project`,
   plus one **Question record** per Initial Research Question, created via
   a new `--create-question` action (see below).

The skill sits upstream of `deep-research` in the pipeline:

```
research-project-init → deep-research (socratic/full) → academic-paper → ...
```

It formalizes the container; it does not do the research inside it.
`deep-research` remains the only place a Question gets sharpened
(FINER-scored, given a methodology). This spec treats that boundary as
fixed, not something this design revisits.

Non-goals (explicitly out of scope for this design):

- Literature research, source verification, or any investigation of the
  Initial Research Questions' content. That is `deep-research`'s job,
  unchanged.
- Sharpening or FINER-scoring a Research Question. The Initial Research
  Questions this skill registers are taken at face value; refining them is
  `deep-research` socratic mode's job, run afterward against the Question
  IDs this skill creates.
- Running or planning Experiments. `agent-state`'s Hypothesis/Experiment
  levels are untouched by this skill — they get auto-filled later, the same
  way any other `--start-run --question-id ...` call triggers them.
- Editing or appending to an already-initialized Project. Each run of this
  skill creates exactly one new Project. Revisiting an existing charter is
  future work.
- Any change to `deep-research`'s own socratic/full activation logic. This
  design adds an earlier routing entry point in `.claude/CLAUDE.md`; it does
  not modify `deep-research`'s internal trigger rules.

## Architecture

```
skills/research-project-init/
  SKILL.md                          ← NEW: guided-dialogue skill definition
  references/
    charter_template.md             ← NEW: charter Markdown structure + tag legend

skills/agent-state/scripts/state_store.py   ← extended: create_question() gets a bare CLI entry point
skills/agent-state/scripts/state.py         ← extended: new --create-question CLI action

.research/
  projects/
    <project_id>/
      charter.md                    ← NEW: one per initialized project

.claude/CLAUDE.md                   ← extended: routing entry + Skills Overview row
```

No sub-agent team. Unlike `deep-research`'s 13-agent pipeline, this skill's
job is narrow enough — ask, tag, write, register — to run as a single
guided flow, the same shape as `research-log`'s and `report-slides`' prose-
driven skills.

## Components

### `skills/research-project-init/SKILL.md`

Defines the guided dialogue: one section at a time (see charter structure
below), asking the questions needed to fill it, and — for every captured
item — deciding its tag:

- `[confirmed]` — the user stated it as fact or a firm decision.
- `[assumption]` — the user or the skill is taking it as true without
  verification (flagged so `deep-research`/reviewers know to check it).
- `[suggestion]` — the skill proposed it and the user accepted it, rather
  than the user originating it.
- `[open]` — raised but not resolved during the dialogue; carried forward
  as a known gap rather than silently dropped.

The skill's own text (prompts, questions to the user) follows the
conversation's language, matching the existing "Default output language
matches user input" rule. All *generated file content* — the charter
document itself — is written in English, per the standing rule that
generated artifacts (logs, slides, templates) are always English regardless
of conversation language.

### `skills/research-project-init/references/charter_template.md`

The Markdown skeleton the dialogue fills in, in this fixed section order:

1. Problem Statement
2. Scope
3. Exclusions (Out of Scope)
4. Expected Contributions
5. Initial Research Questions
6. Constraints
7. Resources
8. Milestones
9. Success Criteria
10. Stop Conditions
11. Risks
12. Ethics Considerations

Frontmatter adopts `research-log`'s `git_head` convention, with an
ISO-8601 `created_at` in place of its date-only `date` field, plus this
skill's own fields:

```yaml
---
project_id: proj_20260806_ab12cd
created_at: "2026-08-06T09:00:00Z"
git_head: <sha>
status: initialized
question_ids: [q_20260806_cd34ef, q_20260806_gh56ij]
---
```

Each section is a bulleted list; each bullet is prefixed with its tag:

```markdown
## Scope

- [confirmed] Covers offline-first sync for the mobile client only.
- [assumption] Desktop client already has adequate offline support.
- [open] Whether tablet form factors count as "mobile" here.
```

### `.research/projects/<project_id>/charter.md`

Written after the Project record exists (so the file can be named by
`project_id` and its frontmatter can reference it), following the same
`.research/` root convention `agent-state` already owns and documents —
not resolved through `resource-resolver`. `resource-resolver`'s six fixed
roles (`research_log`, `experiment_config`, `results`, `slides`, `paper`,
`bibliography`) have no slot for a project charter, and `agent-state`
already bootstraps and manages `.research/` directly (see
`state_store.py`'s `.research/.gitignore` handling), so this file follows
that existing precedent instead of adding a seventh resolver role.

### `skills/agent-state/scripts/state.py` / `state_store.py` (extended)

`create_question()` already exists and already accepts `project_id`
(shipped in the unified-research-state work). The only gap is a CLI entry
point that calls it directly, without going through `--start-run`'s
Run-creation side effect — needed because registering an Initial Research
Question is bookkeeping, not "a skill attempting to answer it," and
`--start-run` always creates a Run record that implies the latter.

```
python state.py --create-question --question "<text>" --skill <name> \
  [--project-id <id>] --json
```

Reuses the existing `--question`, `--skill`, and `--project-id` flag names
— no new flag vocabulary. Dispatch calls `create_question(project_root,
text=..., origin_skill=..., project_id=...)` directly and prints its JSON
result, following the exact pattern `--create-project`/`--create-hypothesis`
already use. No schema change — `state/questions.yaml`'s shape and
`create_question()`'s signature are both already final.

## Data Flow

1. User triggers the skill (`/research-init`, or a natural-language phrase
   matched by the new routing entry — see below).
2. Guided dialogue collects each charter section, tagging every item as it
   goes. The dialogue may reference `agent-state --query` output if the
   user is initializing a project inside a `.research/` directory that
   already has state (informational only — this skill does not merge into
   or reuse an existing Project).
3. `--create-project --name "<text>" --description "<text>" --json` →
   capture returned `id`.
4. For each Initial Research Question captured in step 2:
   `--create-question --question "<text>" --skill research-project-init
   --project-id <id> --json` → capture returned `id`.
5. Write `.research/projects/<project_id>/charter.md` with the frontmatter
   from step 3–4's IDs and the full tagged section content from step 2.
6. Report the charter path and the Project/Question IDs back to the user.

## Routing

New slash command: `/research-init`.

New entry in `.claude/CLAUDE.md`'s "Academic Research Skills Routing
Discipline", Step 1 (explicit clear intent) trigger list — phrases like
"start a new research project", "formalize this idea", "define project
scope", "建立研究專案", "把這個構想變成正式專案" route directly to this
skill, no clarification needed, per the existing Rule 1 pattern.

A second, narrower rule handles the ambiguous case: when the user's request
describes project-level concerns (scope, exclusions, deliverables,
timeline, ethics, risk) rather than a single research question, **and**
`.research/` has no existing Project yet, prefer `research-project-init`
over `deep-research` socratic mode. This is an additive routing entry
point — it does not alter `deep-research`'s own socratic/full trigger
rules or its "prefer socratic when ambiguous" default, which stay exactly
as they are today. When `.research/` already has a Project, or the request
is clearly about a single question rather than a project's shape, routing
is unaffected and falls through to the existing rules.

New row in `.claude/CLAUDE.md`'s Skills Overview table alongside the four
existing academic-pipeline skills.

## Error Handling and Edge Cases

- **`--create-project` fails** (e.g. `.research/` unwritable): dialogue
  stops immediately, reports the JSON error, and does not write a charter
  file. No orphaned charter without a `project_id`.
- **`--create-question` fails for one of several Initial Research
  Questions**: dialogue stops immediately and reports which questions were
  already registered (with their IDs) and which failed, rather than
  silently writing a charter that references Question IDs that don't all
  exist. The user decides whether to retry or proceed with a partial set.
- **User has no Initial Research Questions yet** (only a problem area, not
  even a rough question): the Initial Research Questions section is
  recorded as a single `[open]` item; step 4 of the data flow is skipped —
  a Project can exist with zero Questions, same as `agent-state` already
  allows.
- **Re-running the skill in a `.research/` directory that already has
  Projects**: always creates a new Project (per Non-goals); the dialogue
  surfaces existing Project names/IDs via `--query --project-id` so the
  user can confirm they intend a genuinely new one rather than duplicating
  an existing effort by mistake, but does not block or merge automatically.

## Testing Plan

Deferred to the implementation plan in detail, but scope includes: the new
`--create-question` action's success path (with and without `--project-id`,
defaulting to `proj_default`), its `ProjectNotFoundError` rejection path
for an explicit nonexistent `--project-id`, and confirmation that it does
**not** create a Run record (only a Question) — asserting the pre- and
post-call Run count is unchanged. Full regression of `agent-state`'s
existing test suite. The skill's own dialogue behavior is validated by
scenario walkthrough, consistent with how `research-log`, `report-slides`,
and `deep-research` are validated today — none of them carry automated
tests for their prose-driven dialogue flow.
