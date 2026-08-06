---
name: agent-state
description: Records what the agent does as it drives other skills -- Questions worked on, Runs executed, Results produced, Claims asserted -- in .research/state (canonical, low-frequency) and .research/events (canonical, append-only). Also models the research itself as Project/Hypothesis/Experiment, layered above Question/Run, with write-time referential integrity checks. Use when a skill wants to track its own execution history instead of writing one file per run, or when a user wants to see what the agent has been doing. Triggers on phrases like "what have you been running", "log this run", "show agent activity".
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Agent State

Stores seven cross-skill entities without one file per record. Project,
Question, Hypothesis, Experiment, and Run are low-frequency, mutable, and
live in id-keyed YAML maps under `.research/state/`; Result and Claim are
immutable facts appended to daily JSONL shards under `.research/events/`.
A SQLite index under `.research/indexes/` gives fast filtered queries and is
rebuilt on demand -- it is never a source of truth and can be deleted at any
time.

The research entities form a strict linear chain -- Project -> Question ->
Hypothesis -> Experiment -> Run -> Result -- with a foreign key validated at
write time on every link. A Run that supplies at least a Question (directly
or via `--hypothesis-id`/`--experiment-id`) gets any missing levels below it
auto-filled with `synthetic: true` placeholder records, so the chain is
never broken. A Run given none of `--question`/`--question-id`/
`--hypothesis-id`/`--experiment-id` stays fully standalone, exactly as
before this chain existed: `question_id`, `hypothesis_id`, and
`experiment_id` are all `null`, and nothing is auto-created.

Full design rationale: `docs/superpowers/specs/2026-08-05-agent-state-storage-design.md`.

This skill has no slash command -- it's infrastructure other skills call
into, the same way `resource-resolver` is. It does not depend on
`resource-resolver` and isn't depended on by it; `--artifact-role`/
`--artifact-path` on `--record-result` are conventionally a resource-resolver
role name and a path relative to it, but this skill never calls `resolve.py`
itself.

## Calling convention

```bash
STATE="$(find ~/.claude -path "*/agent-state/scripts/state.py" | head -1)"

# Start a Run, optionally creating a new Question or linking an existing one
python "$STATE" --start-run --skill deep-research --mode full \
  --question "Does this need offline support?" --json
python "$STATE" --start-run --skill deep-research --question-id q_20260805_ab12cd --json

# Close it out
python "$STATE" --complete-run --run-id run_20260805_9f3a1c --status completed --json

# Record what it produced and asserted along the way
python "$STATE" --record-result --run-id run_20260805_9f3a1c \
  --summary "Found 3 sources" --artifact-role bibliography --artifact-path sources.bib --json
python "$STATE" --record-claim --run-id run_20260805_9f3a1c \
  --statement "Region X diverges from the plan" --confidence high --json

# Close a Question once its Runs have answered it
python "$STATE" --answer-question --question-id q_20260805_ab12cd --json

# Or abandon it if it turned out not to need an answer
python "$STATE" --abandon-question --question-id q_20260805_ab12cd --json
```

`--evidence` is the CLI flag for `--record-claim`'s supporting reference; it
is stored on the Claim event as `evidence_ref` (path, quote, or URL) --
the flag and field names differ deliberately, `--evidence` reads better on
the command line while `evidence_ref` makes clear in the record itself that
it's a reference, not the evidence content.

**Every action except `--report` prints JSON on stdout, including errors**
(exit code 1, a `{"error": ..., "message": ...}` payload) -- never a raw
traceback. Check `error` before trusting any other field, the same rule
`resource-resolver`'s `SKILL.md` states for its own JSON output.

## Research chain

```bash
# Register a Project by hand (optional -- proj_default is created lazily
# the first time any Question needs a Project, and covers the common
# single-Project case with no setup step).
python "$STATE" --create-project --name "Offline Support Initiative" \
  --description "Investigate offline usage patterns." --json

# Declare a Hypothesis under an existing Question, and an Experiment under it.
python "$STATE" --create-hypothesis --question-id q_20260806_ab12cd \
  --statement "Offline support is unnecessary." --skill deep-research --json
python "$STATE" --create-experiment --hypothesis-id hyp_20260806_ef34gh \
  --description "Survey production traffic logs." --skill deep-research --json

# Start a Run against that Experiment directly...
python "$STATE" --start-run --skill deep-research --experiment-id exp_20260806_ij56kl --json
# ...or let --start-run auto-fill a synthetic Hypothesis+Experiment from
# just a Question, the same as before this feature existed:
python "$STATE" --start-run --skill deep-research --question "New question text" --json

# Record a verdict once the Experiment concludes.
python "$STATE" --set-hypothesis-status --hypothesis-id hyp_20260806_ef34gh --status supported --json
python "$STATE" --set-experiment-status --experiment-id exp_20260806_ij56kl --status completed --json
```

`synthetic: true` on an auto-created Hypothesis/Experiment marks it as
chain-completion scaffolding rather than a deliberately declared one --
`--query`/`--report` output can filter on it, but it behaves identically to
a hand-created record otherwise (queryable, its status can be changed).

## Querying

```bash
python "$STATE" --query --run-id run_20260805_9f3a1c --json      # run + its results + claims
python "$STATE" --query --question-id q_20260805_ab12cd --json   # question + its runs
python "$STATE" --query --project-id proj_default --json      # project + its questions
python "$STATE" --query --hypothesis-id hyp_20260806_ef34gh --json  # hypothesis + its experiments
python "$STATE" --query --experiment-id exp_20260806_ij56kl --json  # experiment + its runs
python "$STATE" --query --skill deep-research --json             # that skill's runs
python "$STATE" --query --since 2026-08-01 --json                # runs started since then
```

Exactly one filter is required per call. `--query` incrementally syncs the
SQLite index before reading, so results always reflect the latest recorded
state without needing an explicit `--rebuild-index` first.

## User-facing visibility

```bash
python "$STATE" --report                    # everything
python "$STATE" --report --since 2026-08-01
```

`--report` is the one non-JSON, plain-text action -- the sanctioned way for a
user to see what the agent has been doing. Nothing under `.research/state/`,
`.research/events/`, or `.research/indexes/` is meant to be opened or
hand-edited directly; if a user asks what's been happening, run `--report`
instead of reading those files for them.

## Rebuilding the index

```bash
python "$STATE" --rebuild-index --json          # incremental (default via any --query too)
python "$STATE" --rebuild-index --full --json    # full rescan, e.g. after hand-editing state/*.yaml
```

`.research/indexes/index.db` is disposable, and gitignored via a
`.research/.gitignore` this skill bootstraps itself on first write (along
with `state/*.lock`, `events/`, and `cache/`) -- there's nothing to set up
by hand. If the index is ever missing or corrupted, `--query` and `--report`
already self-heal it transparently (a full rebuild happens automatically, no
user action required); run `--rebuild-index --full` yourself when you want
to force that regeneration on demand, e.g. right after hand-editing
`state/*.yaml`, from `.research/state/*.yaml` and `.research/events/*.jsonl`
-- the only two locations that are ever authoritative.

## Validating referential integrity

```bash
python "$STATE" --validate --json
```

Every `--create-hypothesis`/`--create-experiment`/`--start-run` call already
rejects a dangling foreign key at write time -- `--validate` exists for the
case where `state/*.yaml` was hand-edited afterward. It reports every
dangling reference it finds (`{"entity": ..., "id": ..., "field": ...,
"missing_id": ...}` per violation) and repairs nothing; a clean project
returns `{"violations": [], "clean": true}`.

## Schema versioning

`state/questions.yaml` and `state/runs.yaml` each carry a top-level
`version:` field; every `events/*.jsonl` line carries a `schema_version`
field; `indexes/index.db` carries its version in SQLite's own
`PRAGMA user_version`. All three currently read `1`.

A file with no version field at all (written before this mechanism existed)
is treated as version 1 -- the format it was actually written in -- not an
error. A file whose version field is present but doesn't match what this
code understands raises a loud `StateParseError` naming the mismatch, rather
than silently misreading it; `indexes/index.db` is the one exception, since
it's fully disposable -- a version mismatch there is treated the same as
corruption and triggers an automatic wipe-and-rebuild, no user action
required.

This is detection, not migration: if a future schema change needs old
`state/*.yaml`/`events/*.jsonl` data actually converted to a new shape, that
conversion logic doesn't exist yet and would need to be written when that
change happens. What exists today is the guarantee that an incompatible file
is never silently misread as if it were current.

## Non-goals

- Does not migrate any existing skill (`deep-research`, `research-log`,
  `report-slides`, etc.) to call into this system. Adoption is separate,
  per-skill follow-up work.
- Does not define a retention or pruning policy for `.research/events/` --
  old shards accumulate indefinitely under this design.
- Does not copy artifact content. `--artifact-role`/`--artifact-path` record
  where a Result's output lives; the content itself stays wherever the
  producing skill wrote it.
- Does not implement actual cross-version data migration for `state/*.yaml`
  or `events/*.jsonl` -- only version detection (see "Schema versioning"
  above). Writing a real migration is future work, once there's a second
  schema version to migrate to or from.
- Does not migrate `research-log`, `report-slides`, `academic-paper`, or any
  review workflow to actually call into the Project/Hypothesis/Experiment
  layer -- this defines the schema and CLI contract; wiring a specific
  consumer to it is separate follow-up work.
- Does not enforce a status state machine on Hypothesis/Experiment (e.g.
  nothing stops moving a `completed` Experiment back to `running`) -- status
  is a label a caller sets, not a guarded lifecycle.
