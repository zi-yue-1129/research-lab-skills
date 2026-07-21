# research-log Milestone Layer — Design Spec
**Date:** 2026-07-22
**Status:** Approved
**Approach:** Token-threshold auto-enable + hybrid auto-suggest/user-confirm milestone grouping
**Version:** 1.0

---

## Problem

`research-log` stores one Markdown file per experiment, with `INDEX.md` as a flat,
chronological table (Date / Experiment / Mode / Tags / Follows / HEAD / Slides).
As the number of log entries grows, an agent that needs to find relevant prior work
has to either read the entire flat index or open files one by one — both consume
tokens proportional to total log volume and give no shortcut for "which cluster of
experiments is this new question actually about."

There is currently no summary of an individual log's content available without
opening the file, and no way to group related entries into a higher-level phase of
work ("the BERT fine-tuning phase," "the cross-lingual evaluation phase").

## Goals

1. Give each log entry a one-line `summary:` so its content is visible without opening the file.
2. Introduce an optional **milestone** layer that groups related log entries under a short description, so an agent can narrow down to a relevant cluster before opening any individual file.
3. Auto-enable the milestone layer once total log volume passes a token threshold — no manual toggle needed for the common case.
4. Keep grouping and titling decisions in the user's hands (auto-suggest, never silently decide).
5. Zero impact on projects with few log entries: behavior stays exactly as today until the threshold is crossed.
6. Zero breaking changes to existing `INDEX.md` behavior or log file format beyond additive frontmatter fields.

## Non-goals

- No manual on/off command. Enabling is automatic and, in practice, one-directional (see below) — no disable path is designed in this version.
- No exact tokenizer dependency (e.g. tiktoken). A char-count/4 estimate is sufficient for a threshold decision.

---

## Design

### 1. Frontmatter additions

| Field | Added by | When | Notes |
|-------|----------|------|-------|
| `summary` | `add` / `amend` | Always, regardless of milestone state | One sentence, agent-drafted from Goal/Conclusion, user confirms or edits |
| `milestone` | `add` / backfill | Only once milestone mode is active | ID like `M2`; empty/omitted before milestone mode is enabled |

`summary` is added unconditionally because it is cheap and useful in `INDEX.md`
on its own, independent of whether milestones are active.

### 2. Token-threshold computation

- New script `skills/research-log/scripts/log_stats.py` (sibling to the existing
  `git_context.py`, following its CLI conventions and macOS/Linux + PowerShell
  dual invocation pattern already documented in SKILL.md).
- Scans `docs/research_log/*.md`, excluding `INDEX.md` and `MILESTONES.md`.
- Reports total character count and an estimated token count (`chars / 4`).
- Constant `MILESTONE_TOKEN_THRESHOLD = 6000` (tokens), documented in SKILL.md as
  an adjustable value.
- Checked as part of the `index` command's rebuild step: if `MILESTONES.md` does
  not yet exist and estimated tokens ≥ threshold, the enable flow (section 4)
  triggers automatically.
- **One-directional switch:** once `MILESTONES.md` exists, it is always
  maintained going forward. The system never deletes or stops updating it even
  if log volume later drops below the threshold (e.g. old entries removed by the
  user). This avoids having to design a "what happens to user-authored milestone
  descriptions on disable" path, since log volume only realistically grows over
  time.

### 3. `MILESTONES.md` structure

Single file at `docs/research_log/MILESTONES.md`, newest milestone first:

```markdown
# Research Milestones

_Last updated: YYYY-MM-DD_

## M2: BERT Fine-tuning Phase
Cross-lingual ESA fine-tuning phase; addressed gradient explosion and rubric truncation issues.
**Date range:** 2026-05-18 – 2026-05-25 · **Status:** ongoing

| Date | Experiment | Summary |
|------|-----------|---------|
| 2026-05-25 | crosslingual_eval | Cross-lingual eval across zh-TW/en; QWK gap narrowed to 0.04 |
| 2026-05-18 | bert_finetuned | Fine-tuned BERT baseline; P7 gradient explosion fixed via LR=1e-5 |

## M1: Baseline
...
```

`INDEX.md` is unchanged in format and continues to be rebuilt on every `index`
call — it remains the complete flat chronological reference. `MILESTONES.md` is
an additional, smaller-footprint entry point layered on top, not a replacement.

**Agent reading flow once `MILESTONES.md` exists:**
1. Read `MILESTONES.md` (small — descriptions + one-line summaries only).
2. Identify the relevant milestone(s) for the current question.
3. From that milestone's table, identify the relevant log file(s) by summary.
4. Open only those specific log files.

### 4. Enable / update flow

**First enable (threshold crossed during `index` rebuild):**
Triggers automatically (no permission prompt to "turn the feature on"). The agent:
1. Scans all existing logs; for any missing `summary`, drafts one from
   Goal/Conclusion and batches them for user confirmation/edits.
2. Auto-clusters existing logs into candidate milestones using tag-overlap and
   date-gap heuristics (see below), drafts a title + description per cluster.
3. Presents the proposed grouping to the user for confirmation or adjustment
   (merge/split/rename clusters).
4. Writes `MILESTONES.md` and backfills each log's `milestone:` frontmatter field.

**Ongoing (`add` command) once milestone mode is active:**
1. After writing the new entry, compare its tags against the most recent
   milestone's logs (Jaccard tag overlap) and the date gap since that
   milestone's last entry.
2. If overlap is low or the gap is large, suggest starting a new milestone with
   a drafted title/description; otherwise suggest continuing the current one.
3. User confirms, edits the suggestion, or overrides. If the user gives no clear
   signal, default to continuing the current milestone (least disruptive).
4. Update the log's `milestone:` field and rebuild `MILESTONES.md`.

**`amend`:** if the amendment substantially changes the entry's content, prompt
(non-blocking) whether `summary` or milestone membership should be revisited.

**Clustering heuristic (used both for backfill and ongoing suggestions):**
- Tag overlap: Jaccard similarity between the new/candidate entry's `tags` and
  the comparison milestone's aggregate tag set.
- Date gap: days between the candidate entry's date and the milestone's most
  recent entry date.
- Both are signals for a *suggestion*, never an automatic silent decision — the
  user always confirms or adjusts the grouping and its title/description.

### 5. Edge cases

- 0–2 log entries: behavior identical to today; milestone flow never triggers.
- `docs/research_log/` absent: created silently as today.
- A log's `follows:` chain crossing a milestone boundary is allowed and not
  flagged — milestones are a content-grouping convenience, not a hard timeline
  partition.

---

## Files touched

- `skills/research-log/SKILL.md` — document `summary`/`milestone` frontmatter
  fields, the threshold constant, `MILESTONES.md` format, and updated
  `add`/`index`/`amend` command instructions.
- `skills/research-log/scripts/log_stats.py` — new script for token estimation.
- `.claude/skills/research-log/` mirror — kept in sync with `skills/research-log/`
  per existing project convention (installed copy).
