---
name: research-project-init
description: Turn a preliminary research idea into a scoped, reviewable, trackable project. Runs a lightweight guided dialogue covering problem statement, scope, exclusions, expected contributions, initial research questions, constraints, resources, milestones, success criteria, stop conditions, risks, and ethics considerations -- tagging every captured item as confirmed, assumption, suggestion, or open. Writes a project charter to .research/projects/<project_id>/charter.md and registers a Project plus its initial Questions in agent-state. Does not perform literature research or run experiments -- deep-research remains the place a research question gets sharpened. Use when the user has a rough idea and wants to formalize it into a project before research begins. Trigger directly with /research-init, or natural-language phrases like "start a new research project", "formalize this idea", "define project scope", "scope out this project", "建立研究專案", "把這個構想變成正式專案", "幫我把研究範圍定義清楚".
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Research Project Initialization

Turns a preliminary research idea into a project charter -- a reviewable
Markdown document with explicit scope, exclusions, contributions,
constraints, milestones, success/stop conditions, risks, and ethics -- plus
a Project record (and one Question record per Initial Research Question) in
`agent-state`.

Sits upstream of `deep-research`:

```
research-project-init -> deep-research (socratic/full) -> academic-paper -> ...
```

This skill formalizes the container. It does not investigate anything
inside it: no literature search, no FINER-scoring or sharpening of a
research question (that's `deep-research` socratic mode's job, run
afterward against the Question IDs this skill creates), no experiments. See
Non-goals below.

## When to use this vs. `deep-research` socratic mode

Use this skill when the user's concerns are project-shaped: scope,
exclusions, deliverables, timeline, resources, ethics, risk -- the boundary
and governance around one or more research questions. Use `deep-research`
socratic mode when the concern is a single research question that needs
sharpening. If the user has no research question at all yet and no
project-shaped concerns either, `deep-research` socratic mode's existing
"prefer socratic when ambiguous" default still applies -- this skill does
not change that default.

## Calling convention

```bash
STATE="$(find ~/.claude -path "*/agent-state/scripts/state.py" | head -1)"
```

All state changes go through `state.py`; this skill never edits
`.research/state/*.yaml` directly. See `skills/agent-state/SKILL.md` for
the full CLI contract. Every action below prints JSON on stdout, including
errors (`{"error": ..., "message": ...}`, exit 1) -- check `error` before
trusting any other field.

This skill assumes it runs with the working directory inside the target
project (the same assumption `agent-state` and `research-log` make) -- the
charter file is written to `.research/projects/<project_id>/charter.md`
relative to that directory.

## The guided dialogue

Work through these sections in order. For each one, ask what's needed to
fill it, then record every captured item as one bullet tagged with exactly
one of:

- `[confirmed]` -- the user stated it as fact or a firm decision.
- `[assumption]` -- taken as true without verification; flags it for
  `deep-research`/reviewers to check later.
- `[suggestion]` -- the skill proposed it and the user accepted it, rather
  than originating it.
- `[open]` -- raised but not resolved in this dialogue; carried forward as
  a known gap, never silently dropped.

1. **Problem Statement** -- what's actually being investigated and why it
   matters.
2. **Scope** -- what's in bounds.
3. **Exclusions (Out of Scope)** -- what's explicitly not covered, and why
   (a scope without exclusions usually hides an unexamined assumption --
   push on this if the user hasn't named any).
4. **Expected Contributions** -- what this project is meant to produce or
   show.
5. **Initial Research Questions** -- one or more rough questions. These are
   captured as-is, not sharpened (see Non-goals). If the user genuinely has
   none yet, record a single `[open]` item here instead of forcing a
   question into existence.
6. **Constraints** -- time, budget, data access, tooling, or other hard
   limits.
7. **Resources** -- what's available to do the work (people, compute,
   existing data, prior work).
8. **Milestones** -- rough checkpoints, even approximate ones.
9. **Success Criteria** -- what "this project worked" looks like.
10. **Stop Conditions** -- what would make continuing not worth it.
11. **Risks** -- what could go wrong, technically or otherwise.
12. **Ethics Considerations** -- human subjects, sensitive data, dual-use
    concerns, or "none identified" as an explicit `[confirmed]` item rather
    than a silently skipped section.

Ask one section at a time, not all twelve at once -- the same
one-topic-per-question discipline used elsewhere in this skill set. If the
user's answer to one section reveals something relevant to an earlier one,
go back and add it there rather than duplicating it out of order.

The dialogue itself follows the conversation's language. The charter
document it produces is always written in English, regardless of
conversation language -- generated file content in this skill set is
English by standing convention.

## Checking for an existing Project first

Before creating a new Project, check whether one already exists in this
`.research/` directory:

```bash
python "$STATE" --query --project-id proj_default --json
```

If it returns an existing Project (or the user mentions one), surface its
name and ID and confirm with the user that they intend a genuinely new
Project rather than duplicating an existing effort. This skill always
creates a new Project when it proceeds -- it never merges into or edits an
existing one (see Non-goals) -- so this check exists only to catch an
accidental duplicate before it happens, not to block or auto-merge.

## Registering in agent-state

Do this after the dialogue is complete, in this order:

```bash
# 1. Create the Project.
python "$STATE" --create-project --name "<short project name>" \
  --description "<one-paragraph problem statement>" \
  --skill research-project-init --json
# -> capture the returned "id" as PROJECT_ID

# 2. Register each Initial Research Question captured in section 5.
python "$STATE" --create-question --question "<question text>" \
  --skill research-project-init --project-id "$PROJECT_ID" --json
# -> capture the returned "id" as one of QUESTION_IDS, repeat per question
```

If section 5 recorded only a single `[open]` item (no real question yet),
skip step 2 entirely -- a Project can exist with zero Questions.

If step 1 fails, stop and report the error; do not write a charter file
with no `project_id` to reference. If step 2 fails partway through several
questions, stop and report which ones succeeded (with their IDs) and which
failed -- let the user decide whether to retry the failed ones or proceed
with a partial set, rather than silently continuing.

## Writing the charter

Use `references/charter_template.md` as the skeleton. Fill in the
frontmatter (`project_id`, `created_at`, `git_head` if the project is a git
repo, `status: initialized`, `question_ids`) and all twelve sections from
the dialogue, and save to `.research/projects/<project_id>/charter.md`.

## Reporting back

After the charter is written and registered, report to the user:

- The charter file path.
- The Project ID and name.
- The Question ID(s), if any were registered.
- A one-line suggestion to continue with `deep-research` (socratic mode if
  any Initial Research Question needs sharpening, full mode if the
  questions are already sharp enough to research directly).

## Non-goals

- **No literature research, source verification, or investigation of the
  Initial Research Questions' content.** That's `deep-research`'s job,
  unchanged.
- **No sharpening or FINER-scoring of a Research Question.** Initial
  Research Questions are recorded at face value.
- **No Hypothesis or Experiment creation.** Those levels of the chain stay
  untouched -- they get auto-filled later the normal way, via
  `--start-run --question-id ...`.
- **No editing or appending to an already-initialized Project.** Each run
  of this skill creates exactly one new Project. Revisiting an existing
  charter is future work.
- **No change to `deep-research`'s own socratic/full activation logic or
  trigger rules.**
