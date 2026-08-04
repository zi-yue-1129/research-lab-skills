---
name: research-log
description: Record, manage, and query research experiment logs. Use when the user wants to log an experiment result, amend an existing entry, view recent logs, rebuild the index, or plan, execute, repeat, or diagnose research in a project containing docs/research_log/. Triggers on phrases like "log this experiment", "record results", "add a log entry", "show recent experiments", "amend log", "try this method", "change these experiment parameters", and "why did this run fail?". Each entry creates a structured Markdown file in docs/research_log/. Suggest running this before /report-slides when new results have not been logged yet.
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Research Log

Manages a structured experiment journal as individual Markdown files.
One file per experiment; INDEX.md is a derived view rebuilt on demand.

## Storage

**Resolve the log directory first** (see `skills/resource-resolver/SKILL.md`):

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
ROLE_JSON=$(python "$RESOLVE" --role research_log --json)
RESEARCH_LOG_DIR=$(echo "$ROLE_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('primary',''))")
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
$RoleJson = python $RESOLVE --role research_log --json | ConvertFrom-Json
$RESEARCH_LOG_DIR = $RoleJson.primary
```

If `$RESEARCH_LOG_DIR` comes back empty, the role isn't configured yet: follow
"First-use role confirmation" in `skills/resource-resolver/SKILL.md` (surface
`candidates` or `default_relative_path` from `$ROLE_JSON`, get the user's
confirmation, then `--set research_log --path <path> [--create]`) before
continuing. Every `docs/research_log` path below means `$RESEARCH_LOG_DIR`.

Filename: `YYYY-MM-DD_<experiment-slug>.md`
Index: `$RESEARCH_LOG_DIR/INDEX.md` (auto-generated, never hand-edited)
Milestones: `$RESEARCH_LOG_DIR/MILESTONES.md` (auto-generated once milestone mode is active — see Milestone Mode below; never hand-edited)

---

## Milestone Mode

For journals with many entries, a lightweight grouping layer keeps lookups
token-efficient: instead of reading the full flat `INDEX.md`, an agent reads
a small `MILESTONES.md` first, picks the relevant milestone from its
description, then opens only the log file(s) that matter.

**Auto-enable, one-directional.** Milestone mode turns on by itself once total
log content crosses a token threshold — there is no command to turn it on
manually. Once `$RESEARCH_LOG_DIR/MILESTONES.md` exists, always keep
maintaining it; never delete it or stop updating it, even if log volume later
drops (e.g. old entries removed). There is no "disable" flow.

**Checking the threshold** (run this as part of `index`, and again before
finalizing any `add`):

```bash
# macOS / Linux / Git Bash:
LOG_STATS="$(find ~/.claude -path "*/research-log/scripts/log_stats.py" | head -1)"
python "$LOG_STATS" --dir "$RESEARCH_LOG_DIR" --json
```

```powershell
# Windows (PowerShell):
$LOG_STATS = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter log_stats.py |
    Where-Object FullName -like "*research-log*" | Select-Object -First 1).FullName
python $LOG_STATS --dir $RESEARCH_LOG_DIR --json
```

The script prints a JSON object: `file_count`, `total_chars`,
`estimated_tokens`, `milestones_exists`, `threshold` (default `6000`, override
with `--threshold`), and `recommend_enable` — `true` only when
`milestones_exists` is `false` and `estimated_tokens >= threshold`.

**When `recommend_enable` is `true`** (first trigger — the check itself runs
automatically; no permission prompt is needed to start this flow):

1. Scan all existing logs. For any missing a `summary:` field, draft one from
   its Goal/Conclusion sections and batch them for the user to confirm or edit.
2. Cluster logs into candidate milestones using two signals: tag overlap
   (Jaccard similarity between each log's `tags`) and date gaps between
   consecutive logs. Draft a short title and one-paragraph description per
   cluster.
3. Present the proposed grouping to the user. Let them confirm, rename, merge,
   or split clusters — never finalize a grouping silently.
4. Write `$RESEARCH_LOG_DIR/MILESTONES.md` (format below) and add a
   `milestone:` field (e.g. `M2`) to each affected log's frontmatter.

**`MILESTONES.md` format** (newest milestone first):

```markdown
# Research Milestones

_Last updated: YYYY-MM-DD_

## M2: <short title>
<one-paragraph description>
**Date range:** YYYY-MM-DD – YYYY-MM-DD · **Status:** ongoing|closed

| Date | Experiment | Summary |
|------|-----------|---------|
| YYYY-MM-DD | <slug> | <that log's `summary:` frontmatter value> |

## M1: <short title>
...
```

**Ongoing use, once `MILESTONES.md` exists:**
- **Reading:** read `MILESTONES.md` first, pick the relevant milestone from its
  description and table, then open only the specific log file(s) needed —
  don't fall back to reading all of `INDEX.md` unless no milestone matches.
- **Writing (`add`):** compare the new entry's `tags` against the most recent
  milestone's aggregate tags (Jaccard overlap) and the date gap since that
  milestone's last entry. If overlap is low or the gap is large, suggest
  starting a new milestone with a drafted title/description; otherwise suggest
  continuing the current one. The user confirms or overrides; if the user
  gives no clear signal, default to continuing the current milestone. Update
  the log's `milestone:` field and refresh `MILESTONES.md`.

`INDEX.md`'s format is unchanged by milestone mode — it remains the complete
flat chronological reference regardless of whether milestones are active.

---

## Commands

### add

Create a new log entry.

**Step 0 — Gather git context (run silently before asking questions)**

Find the most recent prior log, then run `git_context.py` to extract recent commit history.
Use the output to pre-fill the **Changes** section and to capture the `git_head` value.

```bash
# macOS / Linux / Git Bash:
GIT_CTX="$(find ~/.claude -path "*/research-log/scripts/git_context.py" | head -1)"
PRIOR=$(ls -t "$RESEARCH_LOG_DIR"/*.md 2>/dev/null | grep -v INDEX | grep -v MILESTONES | head -1)
if [ -n "$PRIOR" ]; then
    python "$GIT_CTX" --since-log "$PRIOR"
else
    python "$GIT_CTX" --since $(date -d "14 days ago" +%Y-%m-%d 2>/dev/null \
                                 || date -v-14d +%Y-%m-%d)
fi
GIT_HEAD=$(python "$GIT_CTX" --head)
```

```powershell
# Windows (PowerShell):
$GIT_CTX = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter git_context.py |
    Where-Object FullName -like "*research-log*" | Select-Object -First 1).FullName
$PRIOR = Get-ChildItem $RESEARCH_LOG_DIR -Filter "*.md" |
    Where-Object { $_.Name -ne "INDEX.md" -and $_.Name -ne "MILESTONES.md" } |
    Sort-Object LastWriteTime -Desc |
    Select-Object -First 1 -Exp FullName
if ($PRIOR) { python $GIT_CTX --since-log $PRIOR }
else         { python $GIT_CTX --since (Get-Date).AddDays(-14).ToString("yyyy-MM-dd") }
$GIT_HEAD = python $GIT_CTX --head
```

If the script prints `(not a git repository — skipping git context)`, continue without git context.

Use the **Suggested Changes bullets** from the output as the default content for the Changes section.
Show them to the user and let them accept, edit, or ignore.
Store the **Current HEAD** value for the `git_head` frontmatter field.

---

**Step 1 — Ask mode:**
Quick (3 questions, good for in-progress runs) or Full (all sections)?

**Quick questions:**
1. Experiment name (slug for filename, e.g. `run_v2`)
2. Goal of this experiment
3. Observations / preliminary results
4. Next steps

**Full questions** (ask section by section; user may skip any):
1. Experiment name
2. Changes made — show git-suggested bullets as default; user accepts or edits
3. Setup (checkpoint, dataset, key parameters)
4. Results (numbers, tables)
5. Failures / pitfalls
6. Analysis and observations
7. Chart paths (relative paths, one per line)
8. Conclusion
9. Next steps

**After answers:** ask if this experiment follows a prior one (list existing files to help).

**Step 2 — Draft summary (always, regardless of milestone mode):**
Draft a one-sentence `summary:` from the Goal (and Conclusion, if present).
Show it to the user to accept or edit.

**Step 3 — Milestone check (only if `$RESEARCH_LOG_DIR/MILESTONES.md` already exists):**
Follow "Ongoing use" under Milestone Mode above: compare this entry's tags/date
against the most recent milestone, suggest continuing it or starting a new
one, and set the `milestone:` field to the user's choice.

**Write the file:**

```markdown
---
date: YYYY-MM-DD
experiment: <slug>
mode: <exp|daily|explore|report|publish, or omit if unknown>
tags: []
summary: <one-sentence description, always present>
milestone: <id such as M2, or omit if milestone mode is not active>
follows: <prior-filename-or-empty>
reason_follows: <one-line reason or empty>
git_head: <short SHA from git_context.py --head, or empty if not a git repo>
slide_decks: []
amended: []
---

## Goal
<content>

## Changes
<content, or omit if quick mode>

## Setup
<content, or omit>

## Results
<content, or omit>

## Failures
<content, or omit>

## Analysis
<content>

## Charts
<relative paths, one per line, or omit>

## Conclusion
<content, or omit>

## Next Steps
<content>
```

Omit any section that was skipped. Quick mode writes: Goal, Analysis, Next Steps.

Rebuild INDEX.md after saving.

If `$RESEARCH_LOG_DIR/MILESTONES.md` already exists, also update it: append
this entry's row to its milestone's table and refresh `_Last updated_`. If it
does not exist yet, run the Milestone Mode threshold check — if
`recommend_enable` is `true`, run the enable flow (see Milestone Mode above)
before finishing.

### Pre-filled add (called from research-mode)

When `/research-log add` is invoked by `research-mode` with pre-filled data:
- Skip interactive questions for fields already provided in the pre-filled draft
- Only ask for fields that are empty or marked `{{PLACEHOLDER}}`
- The `mode:` field is always set by research-mode; do not ask the user for it
- After writing the file, update `slide_decks:` in the calling log entry if applicable

Confirm: `✓ Created $RESEARCH_LOG_DIR/YYYY-MM-DD_<slug>.md`

---

### amend [name-or-date]

Update an existing entry.

If no argument, list the 5 most recent files and ask which to edit:
```bash
ls -t "$RESEARCH_LOG_DIR"/*.md | grep -v INDEX | grep -v MILESTONES | head -5
```

**Optional — show git changes since this entry was created:**
```bash
GIT_CTX="$(find ~/.claude -path "*/research-log/scripts/git_context.py" | head -1)"
python "$GIT_CTX" --since-log <target-log-file>
```
Useful when the user wants to add new results or fill in a Changes section retroactively.

Show current section headings. Ask which sections to update. Rewrite the file with new content. Append to `amended:` in frontmatter:
```yaml
amended:
  - date: YYYY-MM-DD
    summary: <one-line description of change>
```

If the amendment substantially changes the entry's content, ask (non-blocking
— skip if the user declines) whether `summary` or `milestone` membership
should be revisited.

Rebuild INDEX.md. If `$RESEARCH_LOG_DIR/MILESTONES.md` exists, rebuild it too.

---

### index

Rebuild INDEX.md by scanning all `.md` files (excluding INDEX.md and MILESTONES.md):

```bash
find "$RESEARCH_LOG_DIR" -maxdepth 1 -name "*.md" ! -name "INDEX.md" ! -name "MILESTONES.md" | sort -r
```

Read frontmatter from each file. Write:

```markdown
# Research Log Index

_Last updated: YYYY-MM-DD_

| Date | Experiment | Mode | Tags | Follows | HEAD | Slides |
|------|-----------|------|------|---------|------|--------|
| 2024-11-02 | run_v2 | exp | training, ablation | run_v1 | a1b2c3d | ✅ reports/2024-11-05 |
| 2024-10-28 | run_v1 | — | baseline | — | e4f5g6h | ❌ |
```

Rules: newest first; `Mode` = `mode` frontmatter value, or `—` if absent; `HEAD` = `git_head` value or `—`; `Slides` = ✅ with deck name if `slide_decks` non-empty, else ❌; `Follows` = experiment slug (not full filename), or `—`.

**After rebuilding INDEX.md**, run the Milestone Mode threshold check (see
above):
- If `$RESEARCH_LOG_DIR/MILESTONES.md` already exists, rebuild it too, from
  all logs' `milestone:` and `summary:` frontmatter fields.
- If it does not exist and `recommend_enable` is `true`, run the enable flow
  from Milestone Mode above.

---

### show [n]

Show the n most recent entries (default 5). For each, print a compact summary: date, experiment, goal excerpt, next steps excerpt, git_head, slide status.

---

### query

Query historical sections without modifying the journal. First locate the public
CLI; do not assume an installed skill path.

```bash
# macOS / Linux / Git Bash:
SECTION_QUERY="$(find ~/.claude -path "*/research-log/scripts/section_query.py" | head -1)"
python "$SECTION_QUERY" types --dir "$RESEARCH_LOG_DIR" --budget 4000
```

```powershell
# Windows (PowerShell):
$SECTION_QUERY = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter section_query.py |
    Where-Object FullName -like "*research-log*" | Select-Object -First 1).FullName
python $SECTION_QUERY types --dir $RESEARCH_LOG_DIR --budget 4000
```

Use the strict `types → search → fetch` sequence. `types` discovers the stable
canonical taxonomy and any custom headings before selecting a query. The agent
must run `types` before every query, including a canonical-only request, then
use the result without asking the user again. If `types` returns `next_cursor`,
perform full type-cursor traversal with the same directory and budget before
claiming that a custom type does not exist:

```bash
python "$SECTION_QUERY" types --dir "$RESEARCH_LOG_DIR" --budget 4000 --cursor "<opaque-cursor>"
```

Then search the selected types to receive a manifest, never full bodies:

```bash
python "$SECTION_QUERY" search \
  --dir "$RESEARCH_LOG_DIR" \
  --sections Failures Analysis "Open Problems" \
  --range 90d \
  --budget 4000
```

The named presets are `all`, `7d`, `30d`, `90d`, and `year`; omitting a range
uses `all`. Use inclusive custom dates when the request supplies a meaningful
boundary, not as a substitute for history-wide repetition checks:

```bash
python "$SECTION_QUERY" search \
  --dir "$RESEARCH_LOG_DIR" \
  --sections Changes Setup Results Analysis \
  --from 2026-01-01 --to 2026-06-30 \
  --budget 4000
```

`--range` and custom `--from` / `--to` bounds are mutually exclusive. Normal
use obtains the current date from the runtime; `--today YYYY-MM-DD` is only for
reproducible automation. Follow every manifest `next_cursor` with the same
normalized search conditions, directory, and budget before making a claim about
the searched scope.

```bash
python "$SECTION_QUERY" search \
  --dir "$RESEARCH_LOG_DIR" \
  --sections Failures Analysis "Open Problems" \
  --range 90d \
  --budget 4000 \
  --cursor "<opaque-cursor>"
```

The default response budget is 4,000 estimated tokens. A lower positive
`--budget` is allowed; 8,000 is the hard maximum. Every response includes its
budget estimate. A budget error, malformed command, unreadable source, or stale
cursor is an explicit query failure, not an empty result.

Fetch only selected manifest IDs. `fetch` returns every requested body
atomically when the selection fits:

```bash
python "$SECTION_QUERY" fetch \
  --dir "$RESEARCH_LOG_DIR" \
  --ids "2026-05-18_bert_finetuned_full::failures" \
  --budget 4000
```

If the result has `status: overflow`, fetch each listed `suggested_batches` in
separate calls. It deliberately returns no partial bodies. If one body is too
large, the result has `status: chunk_required`; follow `chunk_cursor` using
`--chunk-cursor` and then every `next_chunk_cursor`. Complete full chunk
traversal before claiming the oversized section was reviewed. Preserve chunks
in order to reconstruct the exact source body: never silently truncate,
summarize, or omit a requested section.

```bash
python "$SECTION_QUERY" fetch \
  --dir "$RESEARCH_LOG_DIR" \
  --chunk-cursor "<opaque-chunk-cursor>" \
  --budget 4000
```

## Historical Experience Check

Run this protocol when both conditions are true:

1. The current project contains a non-empty research log journal (see the resolved `$RESEARCH_LOG_DIR` from Storage above).
2. The agent is about to plan, recommend, execute, repeat, or diagnose research work.

Mode activation is not required. A direct research request such as "try this
method", "change these experiment parameters", or "why did this run fail?" is
sufficient intent even without an active `research-mode`. Do not run the check
for unrelated maintenance, simple conceptual questions, prose editing,
formatting, or slide layout unless a research decision or evidence
reconstruction is required.

Use checks at decision boundaries, not before every action:

- at the start of a new research objective;
- before proposing a new experimental method or configuration;
- before a costly or long-running experiment;
- when an error, anomalous result, or research blockage appears; and
- before repeating an experiment or operation that may already exist in the journal.

| Research intent | Initial types |
|---|---|
| New method or experiment | Goal, Setup, Results, Failures, Conclusion |
| Error or anomaly | Failures, Analysis, Next Steps, discovered problem-oriented custom types |
| Parameter or implementation change | Changes, Setup, Results, Analysis |
| Costly rerun | Goal, Setup, Results, Failures |

Start with `types` so discovered problem-oriented custom types, for example
`Open Problems`, are included when relevant. Use the `query` flow above and
retrieve only the selected source bodies. Within one session, record normalized
query conditions and the journal state fingerprint. This is session-local
decision state, not a persistent index: the agent does not repeat an identical
query while the relevant files remain unchanged.

After retrieval, classify the evidence without collapsing distinct cases:

- previously attempted and unsuccessful;
- previously solved with an effective fix;
- attempted with inconclusive results;
- similar but materially different in data, code version, parameters, or goal;
- no relevant record found.

"No relevant record found" applies only to the successfully searched journal
and query scope; it is not evidence that no prior attempt exists elsewhere.
Historical records inform a decision but do not automatically prohibit work.

- **General research discussion: advisory.** Disclose a query failure and
  continue the discussion with that limitation.
- **Costly or long-running operation: preflight gate.** Complete the check
  before execution. If the query mechanism fails, pause execution and disclose
  the failure; the agent must not report a query failure as empty history.
- If the journal is missing or contains no log entries, the check passes
  without requiring the user to create one.
- An explicit user request to reproduce or verify prior work permits execution
  after the history and rerun rationale are surfaced. A changed-condition
  experiment follows the same disclosure rule.

---

## Frontmatter reference

| Field | Description |
|-------|-------------|
| `date` | YYYY-MM-DD |
| `experiment` | slug used in filename |
| `tags` | free-form list |
| `summary` | one-sentence description of this entry's content; always present, drafted by the agent and confirmed by the user on every `add`/`amend` |
| `milestone` | milestone ID this entry belongs to (e.g. `M2`); only set once milestone mode is active (see Milestone Mode) |
| `follows` | filename of prior experiment (optional) |
| `reason_follows` | why this follows from the prior (optional) |
| `git_head` | short SHA of HEAD commit when this entry was written (optional) |
| `slide_decks` | paths added by /report-slides (do not edit manually) |
| `amended` | change records added by amend command |

## Notes

- If `$RESEARCH_LOG_DIR` does not exist, create it silently — the directory itself was already confirmed by the user during role resolution; this only covers the directory not yet existing on disk.
- If a `follows:` target file is not found, warn but continue.
- `slide_decks` and `amended` are managed by skills only — never ask the user to set them.
- `git_head` enables reconstructing the exact commit range for any experiment:
  given two consecutive entries with `git_head` values A and B, run `git log A..B` to see all changes.
- `summary` is drafted by the agent and confirmed by the user on every `add`; never left blank.
- Milestone mode (`MILESTONES.md`) auto-enables once total log content crosses
  the token threshold reported by `log_stats.py` (default 6000 tokens) and,
  once created, is always kept up to date — there is no auto-disable.
- Milestone grouping and titles are always agent-suggested and user-confirmed,
  never decided silently.
- A `follows:` chain crossing a milestone boundary is fine and not flagged —
  milestones are a content-grouping convenience, not a hard timeline
  partition.
