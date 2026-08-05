# Unified Research State — Design Spec

- **Date**: 2026-08-06
- **Status**: Draft, pending user review
- **Author**: Claude (brainstorming session with user)

## Problem

`agent-state` (`docs/superpowers/specs/2026-08-05-agent-state-storage-design.md`)
records what the agent *did* — Questions worked on, Runs executed, Results
produced, Claims asserted. It has no notion of what the research *is*: there
is no way to express that a Run tested a specific Hypothesis, that a
Hypothesis was proposed to answer a Question, or that several Questions
belong to the same Project. Skills that want to reason about the shape of a
research effort (which hypotheses are still open, what a project has
concluded so far) have nothing machine-readable to query, and any downstream
consumer — `research-log`, `report-slides`, `academic-paper`, a review
process — would have to reconstruct that structure by hand from free text.

## Goal

Extend `agent-state`'s existing storage layer with a domain model of research
objects, layered strictly on top of the existing Question/Run/Result/Claim
entities (no changes to their storage format beyond the additive fields
below):

- **Project** — a research initiative. Exactly one `.research/` directory
  maps to one default Project unless additional Projects are created by hand.
- **Question** *(existing)* — gains a `project_id`.
- **Hypothesis** — a proposed answer to a Question, carrying a
  supported/refuted/inconclusive verdict.
- **Experiment** — a planned or executed test of a Hypothesis.
- **Run** *(existing)* — gains an `experiment_id`; this is now how a Run
  reaches its Question, not a direct `question_id` link.
- **Result** / **Claim** *(existing, unchanged)* — still attach to `run_id`.

The chain is strictly linear and always fully populated:

```
Project → Question → Hypothesis → Experiment → Run → Result
```

A caller that supplies at least a Question (new text, an existing
`--question-id`, or a `--hypothesis-id`/`--experiment-id` that implies one)
gets every missing level below it auto-filled with `synthetic: true`
placeholder records, so a Run that has *any* research context is never
missing an ancestor between it and its Project. A Run given **no** level at
all — no `--question`/`--question-id`/`--hypothesis-id`/`--experiment-id` —
stays exactly as standalone as it is today: `question_id`, `hypothesis_id`,
and `experiment_id` are all `null`, nothing is auto-created, and existing
callers that rely on this (and the test asserting it,
`test_start_run_without_question`) are unaffected. This preserves
`agent-state`'s original "Run — one execution of a skill/agent against a
Question (or standalone)" design decision rather than silently retracting
it; the chain-completeness guarantee applies to Runs that have research
context, not to every Run unconditionally.

Non-goals (explicitly out of scope for this design):

- Migrating `research-log`, `report-slides`, `academic-paper`, or any review
  workflow to actually call into this system. This design defines the schema
  and CLI contract; wiring a specific consumer to it is separate follow-up
  work — the same boundary the original `agent-state` design drew for
  `report-slides`.
- A retention/pruning policy for accumulated `synthetic: true` scaffolding
  records (they are cheap YAML rows, not `events/` volume — no different
  from any other Question/Run growth agent-state already accepts).
- Any UI or visualization of the Project→...→Result tree; this design only
  covers the storage/query/validation layer.
- Cross-Project queries or merging two Projects — each Project's chain is
  independent; `--query --project-id` scopes to one at a time.

## Architecture

```
skills/agent-state/scripts/state_store.py   ← extended: Project/Hypothesis/Experiment CRUD, FK validation
skills/agent-state/scripts/state_index.py   ← extended: 3 new tables, new query filters
skills/agent-state/scripts/state.py         ← extended: new CLI actions, --start-run auto-fill
.research/
  state/
    projects.yaml                           ← NEW, canonical, id-keyed map
    questions.yaml                          ← + project_id field
    hypotheses.yaml                         ← NEW, canonical, id-keyed map
    experiments.yaml                        ← NEW, canonical, id-keyed map
    runs.yaml                               ← + experiment_id field
  events/                                   ← unchanged (Result, Claim)
  indexes/
    index.db                                ← + projects/hypotheses/experiments tables
```

No new top-level directories: the three new entities are low-frequency,
mutable records, so they follow `questions.yaml`/`runs.yaml`'s existing
id-keyed-YAML-in-`state/`, advisory-locked-write pattern exactly — same
`_locked_file`/`_load_yaml_map`/`_save_yaml_map` machinery, same
`version:`/`STATE_SCHEMA_VERSION` handling, same "missing field on old data
defaults instead of erroring" backward-compatibility rule.

## Components

### `state/projects.yaml`

```yaml
version: 1
projects:
  proj_default:
    name: "Default Project"
    description: null
    status: active              # active | archived
    created_at: "2026-08-06T09:00:00Z"
    created_by: "user"           # skill name, or "user" for manual CLI calls
```

`proj_default` is created lazily the first time anything needs a Project and
none exists yet — no explicit setup step required. `--create-project` lets a
caller register additional named Projects up front for the (currently rare)
case of more than one research initiative sharing a `.research/` directory;
its generated ID follows the same `proj_YYYYMMDD_xxxxxx` shape
`generate_id` already produces for Questions and Runs — `proj_default` is
the one hardcoded exception, not a pattern other Projects follow.

### `state/questions.yaml` (extended)

```yaml
version: 1
questions:
  q_20260806_ab12cd:
    text: "Does this feature need offline support?"
    origin_skill: research-mode
    project_id: proj_default     # NEW — defaults to proj_default if omitted
    status: open
    created_at: "2026-08-06T09:12:03Z"
    updated_at: "2026-08-06T09:12:03Z"
```

### `state/hypotheses.yaml`

```yaml
version: 1
hypotheses:
  hyp_20260806_ef34gh:
    question_id: q_20260806_ab12cd   # must exist — validated at write time
    statement: "Offline support is unnecessary because usage is always online."
    status: proposed              # proposed | supported | refuted | inconclusive
    synthetic: false               # true when auto-filled by --start-run
    created_at: "2026-08-06T09:14:00Z"
    created_by: "deep-research"
```

### `state/experiments.yaml`

```yaml
version: 1
experiments:
  exp_20260806_ij56kl:
    hypothesis_id: hyp_20260806_ef34gh   # must exist — validated at write time
    description: "Survey production traffic logs for offline usage patterns."
    status: planned                # planned | running | completed | failed
    synthetic: false
    created_at: "2026-08-06T09:15:00Z"
    created_by: "deep-research"
```

### `state/runs.yaml` (extended)

```yaml
version: 1
runs:
  run_20260806_9f3a1c:
    skill: deep-research
    mode: full
    experiment_id: exp_20260806_ij56kl   # NEW — replaces question_id as the primary link
    question_id: q_20260806_ab12cd       # derived from experiment_id's chain, kept for cheap lookups
    status: running
    started_at: "2026-08-06T09:16:00Z"
    ended_at: null
```

`question_id` on a Run is no longer set directly by the caller — it is
computed by walking `experiment_id → hypothesis_id → question_id` at write
time and stored redundantly so existing single-hop queries (`--query
--question-id`) don't need a join. This keeps every consumer of the current
`agent-state` CLI contract working unchanged.

### `indexes/index.db` (SQLite, extended)

Three new tables — `projects`, `hypotheses`, `experiments` — mirroring the
YAML shapes, following the same incremental-sync-from-`state/*.yaml`
rebuild strategy the existing three tables use. No new event types in
`events/*.jsonl` — Result and Claim are unaffected.

## CLI Surface (`state.py`, additions)

All JSON on stdout, non-zero exit + `{"error": ..., "message": ...}` on
failure — same contract as every existing action.

- `--create-project --name "<text>" [--description "<text>"] --json`
- `--create-hypothesis --question-id <id> --statement "<text>" --json`
- `--create-experiment --hypothesis-id <id> --description "<text>" --json`
- `--set-hypothesis-status --hypothesis-id <id> --status supported|refuted|inconclusive --json`
- `--set-experiment-status --experiment-id <id> --status running|completed|failed --json`
- `--validate --json` — full referential-integrity scan; reports every
  dangling foreign key found across `state/*.yaml`, fixes nothing
- `--query` gains `--project-id <id>`, `--hypothesis-id <id>`,
  `--experiment-id <id>` as additional single-filter options (still exactly
  one filter per call, per the existing contract)

### `--start-run` (extended resolution)

```
python state.py --start-run --skill <name> [--mode <mode>] \
  [--experiment-id <id> | --hypothesis-id <id> | --question-id <id> | --question "<text>"] \
  --json
```

Resolution, most-specific first, auto-filling every level below what was
given:

1. `--experiment-id` given → validate it exists → use directly.
2. `--hypothesis-id` given (no `--experiment-id`) → validate it exists →
   create a `synthetic: true` Experiment under it.
3. Neither given, but `--question-id` or `--question` given → resolve the
   Question exactly as today (`--question-id` validated to exist, or
   `--question` text creates a new one) → create a `synthetic: true`
   Hypothesis under it → create a `synthetic: true` Experiment under that.
4. Nothing given at all → unchanged from current behavior: the Run is
   created standalone, with `question_id`, `hypothesis_id`, and
   `experiment_id` all `null`. No Question, Hypothesis, or Experiment is
   created. This is the one branch that does *not* auto-fill — see "Goal"
   above for why.

`synthetic: true` records are functionally identical to hand-created ones —
they can be queried, reported on, and have their status changed later — the
flag only exists so `--report`/`--query` output can visually separate
deliberate hypothesis-testing chains from auto-completed scaffolding.

## Provenance

Every new entity carries `created_by`: the `--skill` value passed to the
creating call, or the literal string `"user"` when invoked without one
(i.e. a human running `state.py` directly). Combined with `created_at`, this
answers "which skill/run produced this object" for Project, Hypothesis, and
Experiment without needing to cross-reference `events/*.jsonl`. This mirrors
the provenance `Result.artifact_role`/`artifact_path` and
`Claim.evidence_ref` already provide one level down; no changes to those two
event shapes.

## Error Handling and Edge Cases

- **Dangling foreign key at write time**: `--create-hypothesis` with a
  `question_id` that doesn't exist, or `--create-experiment` with a
  `hypothesis_id` that doesn't exist, fails loudly — new
  `HypothesisNotFoundError`/`ExperimentNotFoundError` exceptions alongside
  the existing `QuestionNotFoundError`/`RunNotFoundError`, same JSON-error
  CLI contract. No partial write.
- **`--validate` on a clean store**: reports zero violations; this is the
  expected steady state, since write-time validation should make dangling
  references unreachable in normal operation.
- **`--validate` after manual YAML edits**: hand-edited
  `state/hypotheses.yaml`/`experiments.yaml` can introduce dangling
  references outside the CLI's control (same class of risk
  `--rebuild-index --full` exists for on the index side). `--validate` finds
  and reports every such record by ID; it does not repair anything —
  repair is a human decision.
- **Missing `project_id`/`experiment_id` on old records**: treated as
  missing-field backward compatibility, not an error — `project_id` defaults
  to `proj_default`, `experiment_id` absent means the Run predates this
  feature and has no Experiment ancestry (reported as `null`, not
  auto-backfilled).
- **Status transitions**: no enforced state machine in this design (e.g.
  nothing stops setting a `completed` Experiment back to `planned`) — status
  is a label a caller sets, not a guarded lifecycle. Adding transition
  guards is future work if a real misuse case shows up.

## Testing Plan

Deferred to the implementation plan in detail, but scope includes: each new
`--create-*` action's success and FK-rejection paths; all three
`--start-run` auto-fill branches producing correct `synthetic: true` chains;
`--validate` against both a clean store and a hand-corrupted one;
`--query`'s three new filters syncing and reading correctly through the
index; full regression of the existing 49 `agent-state` tests.
