# Research Log Section History Query and Proactive Experience Check — Design Spec

**Date:** 2026-08-02
**Status:** Approved
**Approach:** Stateless Markdown scanner with section taxonomy, budgeted retrieval, and proactive research preflight
**Version:** 1.0

---

## Problem

Research journals preserve failures, fixes, observations, results, and open
questions across many Markdown entries. The current `research-log` skill can
show recent entries and, after Milestone Mode activates, narrow reading to a
research phase. It cannot answer cross-history questions such as:

- Which experiments failed, and why?
- Which problems were already solved?
- Has this method or parameter choice already been tried?
- Which unresolved issues recur across milestones?

An agent must currently identify files and open them individually. That is
slow, consumes context, and makes it easy to repeat an unsuccessful experiment
or rediscover a known fix. The limitation also applies when a user starts
research work directly without activating a `research-mode` mode.

## Goals

1. Discover all section types in the journal while presenting a stable set of
   canonical research-log sections first.
2. Query one or more section types across the complete journal with preset or
   custom date filtering.
3. Estimate response size before returning content and keep every response
   within a configurable token budget.
4. Return a compact result manifest before any full section bodies, then let an
   agent retrieve selected results in safe batches.
5. Preserve exact source text; never silently truncate, summarize, or omit a
   requested section body.
6. Teach agents to consult relevant journal history proactively while planning,
   running, or diagnosing research, even when no mode is active.
7. Prevent accidental repetition of expensive work while still permitting
   intentional reproduction or verification.
8. Keep the query implementation read-only, stateless, deterministic, and
   testable without new dependencies.

## Non-goals

- No persistent section index or database in this version.
- No semantic embedding search or similarity model.
- No automatic rewriting or normalization of existing log files.
- No automatic conclusion that an idea is identical to prior work solely
  because its section text or tags are similar.
- No requirement to activate `exp`, `daily`, `explore`, `report`, or `publish`
  mode before historical checks can run.
- No change to `INDEX.md`, `MILESTONES.md`, or the existing `add`, `amend`, and
  `index` storage formats.

---

## Design Overview

Add a standard-library-only CLI at
`skills/research-log/scripts/section_query.py`. It scans journal Markdown files
on each invocation and exposes three operations:

1. `types` discovers canonical and custom section types.
2. `search` filters section occurrences and returns a budgeted manifest.
3. `fetch` retrieves selected source bodies after a complete response-size
   preflight.

The `research-log` skill documents the explicit query command and a proactive
Historical Experience Check protocol. `research-mode` uses the same protocol
as an additional source of context, but mode activation is never required.

The implementation is stateless so query results always reflect current files.
If journal size later makes scanning materially expensive, the CLI contract can
remain stable while its internals gain a persistent cache or index.

---

## 1. Section Taxonomy

### 1.1 Canonical types

The following canonical types are always presented first and in this order:

1. `Goal`
2. `Changes`
3. `Setup`
4. `Results`
5. `Failures`
6. `Analysis`
7. `Charts`
8. `Conclusion`
9. `Next Steps`

Canonical types remain available even when the current journal has zero
occurrences, making the agent interface stable across projects.

### 1.2 Discovered custom types

The scanner reads all level-two Markdown headings (`##`) from log entries.
Headings that do not map to a canonical type are returned as custom types after
the canonical list. Each type record includes:

- normalized type name;
- whether it is canonical or custom;
- original heading variants found in source files;
- occurrence count;
- distinct log count;
- earliest valid date;
- latest valid date.

Custom headings are not merged based on approximate wording or model judgment.
This avoids collapsing sections whose meanings only appear similar.

### 1.3 Explicit aliases

Normalization is deterministic and limited to:

- Unicode-aware case folding;
- trimming surrounding whitespace;
- collapsing repeated internal whitespace;
- an explicit alias table maintained beside the canonical taxonomy.

The initial alias table maps only clear variants such as `Failure`, `Pitfall`,
`Pitfalls`, and `Failures / Pitfalls` to `Failures`. Headings such as `Problems`
and `Open Problems` remain discovered custom types because an unresolved problem
is not necessarily a failed attempt. Approximate matching never changes a
section's type.

Every match retains its original heading for provenance.

### 1.4 Repeated headings

If a file contains the same normalized section type more than once, each
occurrence remains separate. Result IDs add a one-based occurrence suffix only
when needed:

```text
2026-05-18_bert_finetuned_full::analysis
2026-05-18_bert_finetuned_full::analysis::2
```

Bodies are never concatenated implicitly.

---

## 2. Query Interface

### 2.1 `types`

```bash
python section_query.py types --dir docs/research_log --budget 4000
python section_query.py types --dir docs/research_log --cursor "<opaque-cursor>"
```

This operation returns the selectable taxonomy as stable JSON. An agent normally
calls it before selecting section types. It may be skipped only when the user's
request already names valid canonical types and no discovery of custom
problem-oriented types is needed.

The `types` response uses the same response budget as the other operations.
Canonical types are returned first. If discovered custom types do not all fit,
the response includes `total_types`, `returned_types`, and an opaque next-page
cursor. The agent follows all type pages before claiming that no relevant custom
type exists.

### 2.2 `search`

```bash
python section_query.py search \
  --dir docs/research_log \
  --sections Failures Analysis \
  --range 90d \
  --budget 4000
```

Custom dates use inclusive bounds:

```bash
python section_query.py search \
  --dir docs/research_log \
  --sections Failures \
  --from 2026-01-01 \
  --to 2026-06-30
```

Supported time filters are:

- `all`;
- `7d`;
- `30d`;
- `90d`;
- `year` for January 1 through the current date;
- inclusive `--from` and/or `--to` ISO dates.

Preset ranges use the current local calendar date supplied by the runtime. The
CLI output records the resolved start and end dates so the result is auditable.
Custom dates and `--range` are mutually exclusive. An optional
`--today YYYY-MM-DD` override supplies the reference date for deterministic
testing and reproducible automation; normal agent use omits it.

When a manifest is paginated, the next page uses the original normalized query
arguments plus `--cursor "<opaque-cursor>"`. Omitting both a range and custom
bounds defaults to `--range all`.

Results sort by valid frontmatter date descending, then file name ascending,
then source occurrence order. Undated entries in an `all` query sort after all
valid dates, then by file name and source order.

### 2.3 Search manifest

`search` never includes complete section bodies. Each manifest entry contains:

- stable result ID;
- frontmatter date and experiment name;
- source file path;
- normalized type and original heading;
- occurrence number;
- body character count and estimated tokens;
- bounded plain-text preview;
- whether the item can fit by itself in the active fetch budget.

The response also contains:

- normalized query conditions;
- `total_matches` and `returned_matches`;
- response-size estimate and active budget;
- warnings;
- a next-page cursor when additional manifest entries remain;
- suggested fetch batches whose estimated complete responses fit the active
  budget.

The manifest itself is budgeted. Pagination is determined by serialized output
size rather than an arbitrary fixed item count.

### 2.4 Search cursor

A cursor contains enough opaque state to resume after the final returned
result and a fingerprint of normalized query conditions. A cursor is rejected
when section types, date bounds, directory identity, or ordering semantics no
longer match. It does not need to remain valid after journal files change.

The cursor format is an implementation detail and must not be parsed or edited
by an agent.

### 2.5 `fetch`

```bash
python section_query.py fetch \
  --dir docs/research_log \
  --ids "2026-05-18_bert_finetuned_full::failures" \
  --budget 4000

python section_query.py fetch \
  --dir docs/research_log \
  --chunk-cursor "<opaque-chunk-cursor>" \
  --budget 4000
```

`fetch` accepts one or more exact result IDs. Successful output preserves:

- result ID;
- date and experiment;
- source file path;
- normalized and original headings;
- exact section body.

IDs use the log filename stem rather than mutable experiment text. The section
component is the normalized type name encoded as a lowercase URL-safe key;
non-ASCII custom names use UTF-8 percent encoding. An occurrence suffix is
added only for the second and later occurrence. Missing or ambiguous IDs are
errors; the CLI does not use fuzzy lookup.

---

## 3. Response Budget and Retrieval Safety

### 3.1 Budget values

- Default response budget: **4,000 estimated tokens**.
- Agent may request a lower positive budget.
- Hard maximum: **8,000 estimated tokens**.
- A request above 8,000 fails explicitly.
- A budget too small to hold required response metadata fails explicitly.

Token estimation follows the repository's existing approximation of four
characters per token. Preflight uses the entire serialized response and rounds
up so metadata and JSON structure are included rather than only section bodies.

### 3.2 Atomic full-body return

Before `fetch` emits any selected body, it constructs or equivalently measures
the complete prospective response.

- If the full response fits, all requested bodies are returned.
- If it does not fit, no partial body from that selection is returned.
- The overflow response contains item sizes and safe batch suggestions.

This prevents consumers from mistaking a partial response for complete
historical evidence.

### 3.3 Oversized individual sections

When one section cannot fit by itself, `fetch` returns a chunk cursor rather
than a truncated body. Chunk retrieval:

- prefers paragraph boundaries;
- labels every result as `chunk X/N`;
- records exact source character offsets;
- preserves all source characters across ordered chunks;
- allows concatenation of all chunks to reconstruct the complete body;
- never substitutes an automatic summary for source content.

A changed source file invalidates outstanding chunk cursors rather than mixing
chunks from different file versions.

---

## 4. Markdown and Frontmatter Parsing

The scanner processes `docs/research_log/*.md` and excludes `INDEX.md` and
`MILESTONES.md`.

It parses only the fields required by this feature:

- `date`;
- `experiment`.

The section parser recognizes level-two ATX headings (`## Heading`). Level-three
and deeper headings remain part of the current section body. Content before the
first level-two heading is not a selectable section.

Frontmatter `date` is authoritative:

- Missing or invalid dates are warnings, not silently replaced with filename
  dates.
- An `all` query may include undated entries and labels their date invalid.
- Any bounded time query excludes undated entries and reports them in warnings.

Files must decode as UTF-8. A decoding or read failure is a surfaced file error,
not a skipped result.

The query feature is read-only. It never creates the journal directory or
modifies a log.

---

## 5. Proactive Historical Experience Check

### 5.1 Trigger boundary

The protocol activates when both conditions are true:

1. The current project contains a non-empty `docs/research_log/` journal.
2. The agent is about to plan, recommend, execute, repeat, or diagnose research
   work.

It applies whether or not `research-mode` is active. Direct requests such as
"try this method," "change these experiment parameters," or "why did this run
fail?" are sufficient research intent.

It does not trigger for unrelated software maintenance, simple conceptual
questions, prose editing, formatting, or slide layout work unless those tasks
require a research decision or evidence reconstruction.

### 5.2 Event-driven checks

Checks occur at meaningful decision boundaries rather than before every action:

- at the start of a new research objective;
- before proposing a new experimental method or configuration;
- before a costly or long-running experiment;
- when an error, anomalous result, or research blockage appears;
- before repeating an experiment or operation that may already exist in the
  journal.

Within a session, the agent records normalized query conditions and a journal
state fingerprint. It does not repeat an identical query while the relevant
files remain unchanged. This is session-local decision state, not a persistent
index written into the project.

### 5.3 Intent-to-section routing

The default routing is:

| Research intent | Initial section types |
|-----------------|-----------------------|
| New method or experiment | Goal, Setup, Results, Failures, Conclusion |
| Error or anomalous outcome | Failures, Analysis, Next Steps, discovered problem-oriented custom types |
| Parameter or implementation change | Changes, Setup, Results, Analysis |
| Costly rerun | Goal, Setup, Results, Failures |

The agent first reads `types` so custom headings such as `Open Problems` can be
included when relevant. It narrows the time range only when the user's request
or project context supplies a reason; avoiding repetition normally requires an
`all` query.

### 5.4 Interpretation categories

After retrieval, the agent distinguishes:

- previously attempted and unsuccessful;
- previously solved with an effective fix;
- attempted with inconclusive results;
- similar but materially different in data, code version, parameters, or goal;
- no relevant record found.

"No relevant record found" is limited to the successfully searched journal and
query scope. It is not evidence that no prior attempt exists elsewhere.

Historical records inform decisions but do not automatically prohibit work.
An intentional reproduction, verification, or changed-condition experiment may
proceed after the agent states the prior result and the reason the new run is
still useful.

### 5.5 Advisory and gate behavior

- General research discussion uses the check as an advisory. A query failure is
  disclosed, and discussion may continue with that limitation.
- A costly or long-running operation uses the check as a preflight gate. The
  agent must complete the check before execution.
- If the query mechanism fails during a gated operation, execution pauses and
  the agent reports the failure. It must not reinterpret the error as an empty
  history.
- If the journal is missing or contains no log entries, the check passes without
  requiring the user to create one.
- An explicit user request to reproduce or verify prior work permits execution
  after the history and rerun rationale are surfaced.

---

## 6. Skill Integration

### 6.1 `research-log`

Update the skill description so it activates not only for explicit log
management but also when an agent working in a project with a research journal
is planning, executing, repeating, or diagnosing research.

Add a `query` command that teaches the strict flow:

1. `types` unless valid types are already explicit and custom discovery is not
   relevant;
2. `search` for a manifest;
3. `fetch` selected IDs or suggested batches;
4. follow all chunk cursors before claiming a retrieved oversized section was
   fully reviewed.

Add the Historical Experience Check protocol and intent routing table.

### 6.2 `research-mode`

Add history checks at mode-relevant decision points:

- `exp`: new setup, run, failure, or rerun;
- `daily`: only when notes lead to a proposed research action;
- `explore`: before committing to a research direction already investigated;
- `publish`: when reconstructing decisions, limitations, fixes, or prior
  evidence;
- `report`: only when evidence or decision provenance must be recovered.

These rules enhance context but do not make mode activation a prerequisite.

---

## 7. Error Contract

The CLI returns stable JSON errors with a non-zero exit status for:

- unknown section type, accompanied by currently valid types;
- conflicting or malformed date filters;
- invalid result ID;
- stale or mismatched search cursor;
- stale chunk cursor;
- requested budget above 8,000 or below metadata minimum;
- unreadable or non-UTF-8 source file;
- malformed required command arguments.

A missing directory and an existing empty directory are successful empty
results. Warnings and errors are distinct. Agents must not translate a command
error into an empty-history statement.

Every JSON response contains `ok`. Successful responses use `ok: true` and an
operation-specific payload. Errors use `ok: false` plus a stable machine-readable
`error.code`, a human-readable `error.message`, and structured `error.details`
when applicable.

---

## 8. Testing Strategy

Tests follow the existing subprocess-style CLI pattern used by
`test_log_stats.py`.

### 8.1 Taxonomy and parsing

- canonical ordering and zero-occurrence canonical types;
- custom heading discovery;
- taxonomy pagination within budget and complete traversal through its cursor;
- case, whitespace, singular/plural, and explicit alias normalization;
- no approximate merging of custom headings;
- repeated normalized headings and occurrence suffixes;
- level-three headings retained inside section bodies;
- pre-heading content excluded;
- invalid dates and UTF-8 failures.

### 8.2 Filtering and identity

- multi-type queries;
- `all`, `7d`, `30d`, `90d`, and `year` ranges with deterministic `--today`;
- inclusive custom bounds and year boundaries;
- resolved runtime dates in output;
- stable result ordering and IDs;
- unknown types and missing IDs.

### 8.3 Budgeting and pagination

- 4,000-token default;
- lower agent-selected budgets;
- 8,000-token hard maximum;
- whole serialized response included in estimation;
- manifest pagination within budget;
- cursor fingerprint validation and invalidation after journal changes;
- overflow fetch returns no partial body;
- safe batch recommendations;
- oversized section chunks reconstruct exact original content.

### 8.4 Skill behavior

Instruction-level checks cover:

- direct research intent without an active mode triggers a history check;
- unrelated coding and prose work do not trigger it;
- method design, anomaly diagnosis, parameter changes, and costly reruns route
  to the intended section sets;
- solved problems, failed attempts, inconclusive attempts, and materially
  different experiments remain distinct;
- general query failure is advisory while costly execution failure gates;
- explicit reproduction requests may proceed with prior-history disclosure.

Research-log-specific tests and the repository's broader suite are reported
separately during implementation verification.

---

## 9. Files in Scope

- Create `skills/research-log/scripts/section_query.py`.
- Create `skills/research-log/scripts/tests/test_section_query.py`.
- Modify `skills/research-log/SKILL.md`.
- Modify `skills/research-mode/SKILL.md`.
- Modify `skills/research-mode/references/routing_guide.md` if the final plan
  places intent routing in the shared routing reference.
- Update the research-log example documentation with a Failures query and a
  budget-overflow batch retrieval example.
- Update user-facing command tables in the repository README translations when
  the `query` command becomes available.

No generated installed copy under `.claude/skills/` is tracked or modified.

---

## 10. Acceptance Criteria

1. An agent can enumerate canonical and discovered section types without
   opening every log itself.
2. An agent can query multiple section types over presets or inclusive custom
   dates and receive deterministic source references.
3. Search manifests and fetched bodies never exceed the active response budget.
4. Overflow never appears as a successful partial full-text response.
5. All chunks of an oversized section reconstruct its exact body.
6. Invalid dates, unreadable files, stale cursors, and tool failures are visible
   and never misreported as absent history.
7. A direct research request triggers a historical check without requiring
   `research-mode`.
8. Agents surface prior failures and solved problems before avoidable costly
   repetition.
9. Intentional reproduction remains possible with an explicit rationale.
10. Existing log, index, milestone, add, amend, and show behavior remains
    backward compatible.
