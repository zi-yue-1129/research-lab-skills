# Agent Internal Storage and UX Architecture — Design Spec

- **Date**: 2026-08-05
- **Status**: Draft, pending user review
- **Author**: Claude (brainstorming session with user)

## Problem

`skills/resource-resolver` reserves four empty directories — `.research/state/`,
`.research/events/`, `.research/indexes/`, `.research/cache/` — for "future
subsystems" and explicitly defers their internal design
(`docs/superpowers/specs/2026-08-04-resource-resolver-design.md:34-37`). No
mechanism exists yet for tracking what the LLM does as it drives skills across
a project: what request it was working on, which skill/mode executed, what it
produced, and what it asserted along the way.

The naive approach — one file per Question, one per Run, one per Result, one
per Claim — does not scale: it pollutes the repo with a growing number of
small files, creates git diff noise, invites merge conflicts when parallel
sessions or worktrees write concurrently, and forces users to look at files
that are not theirs to manage.

## Goal

Design the internal structure of `.research/state|events|indexes|cache` as a
storage layer for four generic, cross-skill entities:

- **Question** — a request or sub-task the agent is working on.
- **Run** — one execution of a skill/agent against a Question (or standalone).
- **Result** — an immutable output produced by a Run.
- **Claim** — an immutable assertion or decision the agent made during a Run.

Non-goals (explicitly out of scope for this design):

- Migrating existing skills (`deep-research`, `research-log`,
  `report-slides`, etc.) to call into this system. This design defines the
  storage format and CLI contract; adoption is separate follow-up work, the
  same boundary `resource-resolver`'s design drew for its own consumers.
- Retention or pruning policy for `events/` (how/when old shards are archived
  or deleted).
- The exact SQLite table DDL (columns are implied by the record shapes below;
  finalizing DDL is an implementation-time detail, not a design decision).
- Any code change to `skills/report-slides`. The mapping in "Second consumer"
  below is illustrative — it validates the design against a real, already
  file-heavy skill, but does not alter `report-slides`'s paths or behavior.

## Data Classification

Nothing under `.research/` is human-authored. User-authored content (research
log entries, papers, slide decks) already lives at locations resolved through
`resource-resolver` (`docs/research_log/`, `docs/papers/`, `docs/slides/`) and
this system never writes there. Within `.research/`, the four reserved
directories split as follows:

| Directory | Contains | Frequency | Git | Role |
|---|---|---|---|---|
| `state/` | Question, Run — mutable lifecycle records | Low (2–3 writes per record) | Tracked | Canonical — directly written, source of truth |
| `events/` | Result, Claim — immutable facts | High (many per Run) | gitignored | Canonical for these two types — the JSONL line *is* the record, no separate copy exists |
| `indexes/` | Cross-entity query index | Rebuilt on demand | gitignored | Generated + Cache — never authoritative, safe to delete |
| `cache/` | Scratch data unrelated to these four entities (e.g. resource-resolver discovery candidates) | Arbitrary | gitignored | Cache |

`state/` and `events/` are both "Canonical" for the entity types they hold —
being canonical is about being the single source of truth for that data, not
about being human-editable. Neither is meant for direct hand-editing; the CLI
below is the only sanctioned write path, and `--report` is the sanctioned way
for a user to look without touching the files.

## Architecture

```
skills/agent-state/scripts/state.py     ← CLI: writes state/+events/, reads via indexes/
skills/agent-state/scripts/tests/       ← pytest coverage, mirrors resource-resolver's layout
.research/
  state/
    questions.yaml                      ← canonical, id-keyed map
    runs.yaml                           ← canonical, id-keyed map
  events/
    2026-08-05.jsonl                    ← append-only, one shard per UTC day
    2026-08-06.jsonl
  indexes/
    index.db                            ← SQLite, rebuilt from state/+events/, gitignored
  cache/                                ← untouched by this design; existing reserved scratch space
```

Skills that later adopt this system call `state.py` the same way they call
`resolve.py` today — as a subprocess, reading JSON off stdout. `agent-state`
sits alongside `resource-resolver` as shared infrastructure, not on top of it;
the two skills don't depend on each other, though `state.py`'s `artifact_ref`
field (see below) is intended to hold a resource-resolver role name plus a
relative path, so a Result can point at where its real output lives without
duplicating it.

## Components

### `state/questions.yaml`

An id-keyed map, not a list — concurrent writers touch different keys, which
most merge tools resolve as non-overlapping line ranges instead of a
conflict.

```yaml
questions:
  q_20260805_ab12cd:
    text: "Does this feature need offline support?"
    origin_skill: research-mode
    status: open              # open | answered | abandoned
    created_at: "2026-08-05T09:12:03Z"
    updated_at: "2026-08-05T09:12:03Z"
```

Written twice in a Question's life at most: creation, and the transition to
`answered`/`abandoned`.

### `state/runs.yaml`

```yaml
runs:
  run_20260805_9f3a:
    skill: deep-research
    mode: full
    question_id: q_20260805_ab12cd   # nullable — not every run answers a Question
    status: running                   # running | completed | failed
    started_at: "2026-08-05T09:13:00Z"
    ended_at: null
```

Written twice per Run: start and completion/failure. Result and Claim counts
are deliberately **not** stored here — that would make a low-frequency
canonical file mutate on every high-frequency event. Anything that needs an
aggregate (e.g. "how many Results has this Run produced") is a job for
`indexes/`, computed from `events/`.

### `events/YYYY-MM-DD.jsonl`

One shard per UTC day, append-only. Two event types:

```jsonl
{"event":"result","id":"res_...","run_id":"run_20260805_9f3a","skill":"deep-research","summary":"...","artifact_ref":{"role":"bibliography","path":"sources.bib"},"ts":"2026-08-05T09:20:11Z"}
{"event":"claim","id":"clm_...","run_id":"run_20260805_9f3a","statement":"...","confidence":"high","evidence_ref":"...","ts":"2026-08-05T09:21:00Z"}
```

`artifact_ref` names a `resource-resolver` role plus a path relative to it —
this system records that an artifact exists and where, never a copy of its
content.

### `indexes/index.db` (SQLite)

Four tables (`questions`, `runs`, `results`, `claims`) mirroring the record
shapes above, indexed on `run_id`, `skill`, and `ts`. Rebuild strategy:

- Every `--query` performs an incremental sync first: for each `events/*.jsonl`
  shard, compare its line count against a stored checkpoint and ingest only
  new lines; re-read `state/*.yaml` in full (it's small).
- `--rebuild-index --full` discards `index.db` and rescans everything from
  scratch — needed after manual edits to `state/*.yaml` or if the index file
  is corrupted or deleted.
- If `index.db` is missing, a `--query` lazily triggers a full rebuild rather
  than failing.

This mirrors `research-log`'s existing "auto-generated, rebuilt on demand"
convention for `INDEX.md`, so the repo has one rebuild philosophy, not two.

### `skills/agent-state/scripts/state.py`

Same conventions as `resolve.py`: JSON on stdout for every path including
errors, non-zero exit on failure, pytest-covered.

- `--start-run --skill <name> [--mode <mode>] [--question "<text>" | --question-id <id>] --json`
- `--complete-run --run-id <id> --status completed|failed --json`
- `--record-result --run-id <id> --summary "<text>" [--artifact-role <role> --artifact-path <path>] --json`
- `--record-claim --run-id <id> --statement "<text>" [--confidence low|medium|high] [--evidence "<text>"] --json`
- `--query [--run-id <id> | --question-id <id> | --skill <name> | --since <date>] --json`
- `--rebuild-index [--full] --json`
- `--report [--since <date>]` — the one non-JSON, human-readable subcommand;
  the sanctioned way for a user to see what the agent has been doing without
  opening `state/`, `events/`, or `index.db` directly.

Writes to `state/*.yaml` go through a read-modify-write guarded by an advisory
file lock (lock file + atomic write-temp-then-rename), because this repo's
actual usage pattern includes concurrent background jobs and worktrees writing
to the same project — a single-writer assumption would not hold.

## Second consumer: report-slides diagram review artifacts (illustrative mapping only)

`skills/report-slides/references/diagram-workflow.md` currently has every
diagram-review cycle write its process artifacts into
`docs/slides/reports/<deck>/`, alongside the deck's actual deliverables. That
directory mixes final output with a lot of transient review material — a
concrete example of the file-explosion problem this design solves. Mapping it
onto the entities above, without changing any `report-slides` code:

| Current artifact | Nature | Target under this design |
|---|---|---|
| `subfigure.png`, `slideNN-review.png`, `review-sheet.png`, temporary diff outlines | Regenerable from source SVG/manifest; disposable once the review gate passes | `cache/report-slides/<deck>/<diagram_id>/...` |
| `review.json` overall record (`statuses.svg_preview/pptx_structure/pptx_render`, `overall.completion_allowed`, `revision_required`) | The outcome of one review cycle | A **Result** on the Run for that cycle (`skill: report-slides`, `mode: diagram-review`, identified by `diagram_id` + revision) |
| `review.json.findings[]` (`kind`, `scope`, `artifact_path`, `source`, `disposition` per entry) | Individual judgments made during the review | One **Claim** per finding |

Deliberately untouched: `diagram-plan.yaml` (deck-scoped planning document,
stays in `docs/slides/reports/<deck>/`) and
`docs/slides/assets/diagrams/<diagram_id>/manifest.yaml` plus its source files
(a deliberately cross-deck, reusable asset library — durable by design, not
transient). Wiring `report-slides` to actually call `state.py` is future work.

## Error Handling and Edge Cases

- **Concurrent writers to `state/*.yaml`**: guarded by the advisory lock
  described above; a writer that cannot acquire the lock within a short
  timeout fails loudly with a JSON error rather than silently skipping the
  write.
- **`--complete-run` for a `run_id` that doesn't exist**: JSON error, no
  partial write.
- **`--record-result`/`--record-claim` for a `run_id` not in `state/runs.yaml`**:
  JSON error — Results and Claims always belong to a known Run.
  Orphaned/dangling `run_id` should never be able to enter `events/`.
- **Corrupted or hand-edited `state/*.yaml`**: `state.py` fails loudly on
  invalid YAML or a record missing required fields, rather than silently
  dropping the offending record (no-silent-failures, matching this project's
  global code-style standard).
- **`indexes/index.db` missing or corrupted**: `--query` transparently
  triggers a full rebuild; this is expected, not an error condition.

## Testing Plan

Deferred to the implementation plan (this spec covers format and contract,
not test cases). At minimum, `writing-plans` should scope: id-keyed YAML
read-modify-write under concurrent writers, JSONL shard rollover at a UTC day
boundary, incremental vs. full index rebuild correctness, and the
`--record-result`/`--record-claim` orphan-`run_id` rejection path.
