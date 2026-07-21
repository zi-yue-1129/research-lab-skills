---
name: research-log
description: Record, manage, and query research experiment logs. Use when the user wants to log an experiment result, amend an existing entry, view recent logs, or rebuild the index. Triggers on phrases like "log this experiment", "record results", "add a log entry", "show recent experiments", "amend log". Each entry creates a structured Markdown file in docs/research_log/. Suggest running this before /report-slides when new results have not been logged yet.
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Research Log

Manages a structured experiment journal as individual Markdown files.
One file per experiment; INDEX.md is a derived view rebuilt on demand.

## Storage

All files in `docs/research_log/` (relative to project root). Create it if absent.

Filename: `YYYY-MM-DD_<experiment-slug>.md`
Index: `docs/research_log/INDEX.md` (auto-generated, never hand-edited)
Milestones: `docs/research_log/MILESTONES.md` (auto-generated once milestone mode is active — see Milestone Mode below; never hand-edited)

---

## Milestone Mode

For journals with many entries, a lightweight grouping layer keeps lookups
token-efficient: instead of reading the full flat `INDEX.md`, an agent reads
a small `MILESTONES.md` first, picks the relevant milestone from its
description, then opens only the log file(s) that matter.

**Auto-enable, one-directional.** Milestone mode turns on by itself once total
log content crosses a token threshold — there is no command to turn it on
manually. Once `docs/research_log/MILESTONES.md` exists, always keep
maintaining it; never delete it or stop updating it, even if log volume later
drops (e.g. old entries removed). There is no "disable" flow.

**Checking the threshold** (run this as part of `index`, and again before
finalizing any `add`):

```bash
# macOS / Linux / Git Bash:
LOG_STATS="$(find ~/.claude -path "*/research-log/scripts/log_stats.py" | head -1)"
python "$LOG_STATS" --dir docs/research_log --json
```

```powershell
# Windows (PowerShell):
$LOG_STATS = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter log_stats.py |
    Where-Object FullName -like "*research-log*" | Select-Object -First 1).FullName
python $LOG_STATS --dir docs\research_log --json
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
4. Write `docs/research_log/MILESTONES.md` (format below) and add a
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
PRIOR=$(ls -t docs/research_log/*.md 2>/dev/null | grep -v INDEX | grep -v MILESTONES | head -1)
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
$PRIOR = Get-ChildItem docs\research_log -Filter "*.md" |
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

**Step 3 — Milestone check (only if `docs/research_log/MILESTONES.md` already exists):**
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

If `docs/research_log/MILESTONES.md` already exists, also update it: append
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

Confirm: `✓ Created docs/research_log/YYYY-MM-DD_<slug>.md`

---

### amend [name-or-date]

Update an existing entry.

If no argument, list the 5 most recent files and ask which to edit:
```bash
ls -t docs/research_log/*.md | grep -v INDEX | grep -v MILESTONES | head -5
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

Rebuild INDEX.md. If `docs/research_log/MILESTONES.md` exists, rebuild it too.

---

### index

Rebuild INDEX.md by scanning all `.md` files (excluding INDEX.md and MILESTONES.md):

```bash
find docs/research_log -maxdepth 1 -name "*.md" ! -name "INDEX.md" ! -name "MILESTONES.md" | sort -r
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
- If `docs/research_log/MILESTONES.md` already exists, rebuild it too, from
  all logs' `milestone:` and `summary:` frontmatter fields.
- If it does not exist and `recommend_enable` is `true`, run the enable flow
  from Milestone Mode above.

---

### show [n]

Show the n most recent entries (default 5). For each, print a compact summary: date, experiment, goal excerpt, next steps excerpt, git_head, slide status.

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

- If `docs/research_log/` does not exist, create it silently.
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
