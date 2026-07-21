# research-log Milestone Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a token-threshold auto-enabled milestone grouping layer to the `research-log` skill, so an agent can narrow to a relevant cluster of experiments via a compact `MILESTONES.md` before opening individual log files, instead of scanning the full flat `INDEX.md`.

**Architecture:** A new CLI script (`log_stats.py`) estimates total log token volume and reports whether the milestone-mode threshold has been crossed. `SKILL.md` is extended with a new "Milestone Mode" section documenting the `summary`/`milestone` frontmatter fields, the `MILESTONES.md` file format, and updated `add`/`index`/`amend` command instructions that call the script and drive the auto-suggest/user-confirm grouping flow.

**Tech Stack:** Python 3 (stdlib only: `argparse`, `json`, `pathlib`), pytest (subprocess-style CLI tests, matching the existing `tests/test_mark_read_args.py` pattern).

## Global Constraints

- `MILESTONE_TOKEN_THRESHOLD` default value: **6000** tokens (spec §2). Must match between `log_stats.py`'s default and the value documented in `SKILL.md`.
- Token estimate formula: `total_chars // 4` (spec §2, §"Non-goals" — no tokenizer dependency).
- Milestone mode is a **one-directional switch**: once `docs/research_log/MILESTONES.md` exists, it is always maintained; the script must never report a recommendation to "disable" it, and `SKILL.md` must never instruct deleting it (spec §2).
- `summary:` frontmatter field is added on every `add`/`amend`, regardless of whether milestone mode is active (spec §1).
- `milestone:` frontmatter field is only populated once milestone mode is active (spec §1).
- `INDEX.md`'s existing format is unchanged (spec §3) — do not add columns to it.
- All grouping/title decisions are agent-suggested, user-confirmed — never silently decided (spec §4).
- No new external dependencies (repo has no tiktoken/similar in use for this skill; spec explicitly rules it out).

---

## File Structure

- **Create** `skills/research-log/scripts/log_stats.py` — scans `docs/research_log/*.md` (excluding `INDEX.md`/`MILESTONES.md`), reports char/token totals and whether milestone mode should trigger. Mirrors `skills/research-log/scripts/git_context.py`'s CLI conventions (dual bash/PowerShell invocation blocks in `SKILL.md`, plain stdout report by default).
- **Create** `skills/research-log/scripts/tests/__init__.py` and `skills/research-log/scripts/tests/test_log_stats.py` — subprocess-based CLI tests, following the pattern in `tests/test_mark_read_args.py` (there is no importable package for scripts under a hyphenated skill directory, so tests invoke the script as a subprocess rather than importing it).
- **Modify** `skills/research-log/SKILL.md` — add a "Milestone Mode" section; extend `add`/`index`/`amend` command instructions; extend the frontmatter reference table and Notes section.

Note on `.claude/skills/research-log/`: that directory is a local `install.sh` output and is listed in `.gitignore` (`.claude/skills/` — verified via `git ls-files` returning nothing under that path). It is not part of the tracked source and is not touched by this plan.

---

## Task 1: `log_stats.py` — token-volume scanner script

**Files:**
- Create: `skills/research-log/scripts/log_stats.py`
- Create: `skills/research-log/scripts/tests/__init__.py`
- Test: `skills/research-log/scripts/tests/test_log_stats.py`

**Interfaces:**
- Produces: CLI `python log_stats.py --dir PATH [--threshold N] [--json]`.
  - JSON output keys (used by later tasks / by `SKILL.md` instructions): `file_count` (int), `total_chars` (int), `estimated_tokens` (int), `milestones_exists` (bool), `threshold` (int), `recommend_enable` (bool).
  - `recommend_enable` is `True` only when `milestones_exists` is `False` and `estimated_tokens >= threshold`.
  - Default `--dir` is `docs/research_log`; default `--threshold` is `6000`.

- [ ] **Step 1: Write the failing tests**

Create `skills/research-log/scripts/tests/__init__.py` (empty file):

```python
```

Create `skills/research-log/scripts/tests/test_log_stats.py`:

```python
"""Tests for log_stats.py — research log token-volume scanner (milestone gating)."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "log_stats.py"


def _write(dir_path: Path, name: str, num_chars: int) -> None:
    (dir_path / name).write_text("x" * num_chars, encoding="utf-8")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_counts_chars_excluding_index_and_milestones(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 400)
    _write(log_dir, "2026-01-02_run_b.md", 600)
    _write(log_dir, "INDEX.md", 999_999)
    _write(log_dir, "MILESTONES.md", 999_999)

    result = _run("--dir", str(log_dir), "--json")
    assert result.returncode == 0, result.stderr
    stats = json.loads(result.stdout)

    assert stats["file_count"] == 2
    assert stats["total_chars"] == 1000
    assert stats["estimated_tokens"] == 250  # 1000 // 4


def test_recommend_enable_false_below_threshold(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 400)  # 100 estimated tokens

    result = _run("--dir", str(log_dir), "--threshold", "6000", "--json")
    stats = json.loads(result.stdout)
    assert stats["recommend_enable"] is False


def test_recommend_enable_true_at_threshold(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 24_000)  # exactly 6000 estimated tokens

    result = _run("--dir", str(log_dir), "--threshold", "6000", "--json")
    stats = json.loads(result.stdout)
    assert stats["estimated_tokens"] == 6000
    assert stats["recommend_enable"] is True


def test_recommend_enable_false_when_milestones_already_exists(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 24_000)
    _write(log_dir, "MILESTONES.md", 10)  # already active

    result = _run("--dir", str(log_dir), "--threshold", "6000", "--json")
    stats = json.loads(result.stdout)
    assert stats["milestones_exists"] is True
    assert stats["recommend_enable"] is False


def test_missing_directory_returns_zero_stats(tmp_path: Path) -> None:
    missing_dir = tmp_path / "does_not_exist"

    result = _run("--dir", str(missing_dir), "--json")
    assert result.returncode == 0, result.stderr
    stats = json.loads(result.stdout)
    assert stats == {
        "file_count": 0,
        "total_chars": 0,
        "estimated_tokens": 0,
        "milestones_exists": False,
        "threshold": 6000,
        "recommend_enable": False,
    }


def test_text_report_format(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 400)

    result = _run("--dir", str(log_dir))
    assert result.returncode == 0, result.stderr
    assert "1 entry" in result.stdout
    assert "400 chars" in result.stdout
    assert "below threshold" in result.stdout


def test_default_threshold_is_6000_when_flag_omitted(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write(log_dir, "2026-01-01_run_a.md", 400)

    result = _run("--dir", str(log_dir), "--json")
    stats = json.loads(result.stdout)
    assert stats["threshold"] == 6000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest skills/research-log/scripts/tests/test_log_stats.py -v`
Expected: FAIL — `log_stats.py` does not exist yet (`FileNotFoundError` / non-zero exit from the subprocess, surfaced as assertion failures on `result.returncode == 0`).

- [ ] **Step 3: Write the implementation**

Create `skills/research-log/scripts/log_stats.py`:

```python
#!/usr/bin/env python3
"""log_stats.py — Estimate research log token volume for milestone-mode gating.

Usage:
    # Human-readable report
    python log_stats.py --dir docs/research_log

    # Machine-readable JSON (used by SKILL.md instructions)
    python log_stats.py --dir docs/research_log --threshold 6000 --json
"""

import argparse
import json
from pathlib import Path

DEFAULT_THRESHOLD = 6000
EXCLUDED_NAMES = frozenset({"INDEX.md", "MILESTONES.md"})
CHARS_PER_TOKEN = 4


def scan_logs(log_dir: Path) -> dict:
    """Scan research log entries and estimate total token volume.

    Returns a dict with `file_count`, `total_chars`, `estimated_tokens`,
    and `milestones_exists` (whether MILESTONES.md is present in log_dir).
    Does not raise if log_dir is missing — returns zeroed stats instead,
    matching research-log's existing "create docs/research_log silently
    if absent" behavior.
    """
    if not log_dir.is_dir():
        return {
            "file_count": 0,
            "total_chars": 0,
            "estimated_tokens": 0,
            "milestones_exists": False,
        }

    total_chars = 0
    file_count = 0
    for path in sorted(log_dir.glob("*.md")):
        if path.name in EXCLUDED_NAMES:
            continue
        total_chars += len(path.read_text(encoding="utf-8"))
        file_count += 1

    return {
        "file_count": file_count,
        "total_chars": total_chars,
        "estimated_tokens": total_chars // CHARS_PER_TOKEN,
        "milestones_exists": (log_dir / "MILESTONES.md").is_file(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Estimate research log token volume for milestone-mode gating"
    )
    ap.add_argument("--dir", default="docs/research_log", metavar="PATH",
                     help="Research log directory (default: docs/research_log)")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, metavar="N",
                     help=f"Token threshold for recommending milestone mode "
                          f"(default: {DEFAULT_THRESHOLD})")
    ap.add_argument("--json", action="store_true",
                     help="Output machine-readable JSON instead of a text report")
    args = ap.parse_args()

    stats = scan_logs(Path(args.dir))
    stats["threshold"] = args.threshold
    stats["recommend_enable"] = (
        not stats["milestones_exists"] and stats["estimated_tokens"] >= args.threshold
    )

    if args.json:
        print(json.dumps(stats))
        return

    plural = "y" if stats["file_count"] == 1 else "ies"
    print(f"Log stats for {args.dir}:")
    print(f"  {stats['file_count']} entr{plural} · {stats['total_chars']} chars"
          f" · ~{stats['estimated_tokens']} tokens (est.)")
    print(f"  Threshold: {args.threshold} tokens")
    if stats["milestones_exists"]:
        print("  Milestone mode: already active (MILESTONES.md present)")
    elif stats["recommend_enable"]:
        print("  Milestone mode: THRESHOLD CROSSED — enable milestone grouping")
    else:
        print("  Milestone mode: below threshold (not yet enabled)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest skills/research-log/scripts/tests/test_log_stats.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add skills/research-log/scripts/log_stats.py skills/research-log/scripts/tests/
git commit -m "feat(research-log): add log_stats.py for milestone-mode token gating"
```

---

## Task 2: `SKILL.md` — document Milestone Mode and update commands

**Files:**
- Modify: `skills/research-log/SKILL.md` (full replacement shown in Step 1)

**Interfaces:**
- Consumes: `log_stats.py --dir docs/research_log --json` (Task 1), specifically the `recommend_enable`, `milestones_exists`, `estimated_tokens`, `threshold` keys.
- Produces: none (this is the terminal task; the plan ends here).

- [ ] **Step 1: Replace the file content**

Replace the full contents of `skills/research-log/SKILL.md` with:

```markdown
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
```

- [ ] **Step 2: Verify the edit — structural sanity checks**

Run:
```bash
grep -c "^## " skills/research-log/SKILL.md
grep -n "MILESTONE_TOKEN_THRESHOLD\|threshold" skills/research-log/SKILL.md | head -5
grep -n "^summary:\|^milestone:" skills/research-log/SKILL.md
python3 -c "
import yaml, re
text = open('skills/research-log/SKILL.md', encoding='utf-8').read()
m = re.match(r'^---\n(.*?)\n---\n', text, re.S)
assert m, 'frontmatter fence not found'
fm = yaml.safe_load(m.group(1))
assert fm['name'] == 'research-log'
assert fm['metadata']['data_access_level'] == 'raw'
assert fm['metadata']['task_type'] == 'open-ended'
print('frontmatter OK')
"
```
Expected: the yaml frontmatter check prints `frontmatter OK` (confirms the
existing frontmatter block — unchanged by this task — still parses, since the
rest of the file was hand-written inline in this step and a broken fence would
break skill loading). The `grep` calls are eyeballed against the section list:
`## Storage`, `## Milestone Mode`, `## Commands`, `## Frontmatter reference`,
`## Notes` plus the `### add` / `### amend` / `### index` / `### show`
subsections should all be present.

- [ ] **Step 3: Commit**

```bash
git add skills/research-log/SKILL.md
git commit -m "docs(research-log): add Milestone Mode section and update add/index/amend flows"
```

---

## Task 3: Full verification pass

**Files:** none created/modified — this task only runs checks across Tasks 1-2.

- [ ] **Step 1: Run the full project test suite to confirm no regressions**

```bash
python3 -m pytest -q
```
Expected: all tests pass, including the 7 new tests from Task 1
(`skills/research-log/scripts/tests/test_log_stats.py`).

- [ ] **Step 2: Dry-run `log_stats.py` against the real example logs**

```bash
python3 skills/research-log/scripts/log_stats.py --dir examples/research-log --json
```
Expected: a JSON object with `file_count: 4` (the 4 example `.md` logs,
excluding `INDEX.md`; `MILESTONES.md` does not exist in `examples/research-log/`
so `milestones_exists` is `false`), plus non-zero `total_chars`/`estimated_tokens`
and a `recommend_enable` boolean (whether it is `true` depends on the actual
combined size of the 4 example files relative to the 6000-token default — either
outcome is correct behavior, this step is a smoke test, not an assertion on the
specific example content).

- [ ] **Step 3: Push the branch and open a draft PR**

```bash
git push -u origin worktree-research-log-milestones
gh pr create --draft --title "Add milestone layer to research-log" --body "$(cat <<'EOF'
## Summary
- Adds `log_stats.py` to estimate research-log token volume and gate an auto-enabled, one-directional "milestone mode"
- Adds `summary`/`milestone` frontmatter fields and a `MILESTONES.md` grouping layer, documented in `SKILL.md`, so agents can narrow to a relevant cluster of experiments before opening individual log files

## Test plan
- [x] `python3 -m pytest skills/research-log/scripts/tests/test_log_stats.py -v` — 7 passed
- [x] `python3 -m pytest -q` — full suite passes
- [x] `python3 skills/research-log/scripts/log_stats.py --dir examples/research-log --json` — smoke test against real example logs

Design spec: `docs/superpowers/specs/2026-07-22-research-log-milestones-design.md`
EOF
)"
```

Report the PR URL back to the user once created.
