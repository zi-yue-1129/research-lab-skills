---
name: agent-state
description: Records what the agent does as it drives other skills -- Questions worked on, Runs executed, Results produced, Claims asserted -- in .research/state (canonical, low-frequency) and .research/events (canonical, append-only). Use when a skill wants to track its own execution history instead of writing one file per run, or when a user wants to see what the agent has been doing. Triggers on phrases like "what have you been running", "log this run", "show agent activity".
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Agent State

Stores four cross-skill entities without one file per record: Question and
Run are low-frequency, mutable, and live in id-keyed YAML maps under
`.research/state/`; Result and Claim are immutable facts appended to daily
JSONL shards under `.research/events/`. A SQLite index under
`.research/indexes/` gives fast filtered queries and is rebuilt on demand --
it is never a source of truth and can be deleted at any time.

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

## Querying

```bash
python "$STATE" --query --run-id run_20260805_9f3a1c --json      # run + its results + claims
python "$STATE" --query --question-id q_20260805_ab12cd --json   # question + its runs
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
