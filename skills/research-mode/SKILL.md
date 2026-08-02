---
name: research-mode
description: "Work mode dispatcher for research workflows. 5 modes: exp (running experiments), daily (reading/notes), explore (deep-research exploration), report (slide generation), publish (academic-pipeline). Commands: /mode exp|daily|explore|report|publish|status|end. All output in English. Triggers: /mode, switch mode, start experiment, begin research session, mode status, end session."
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Research Mode

Declares work context and orchestrates session-end log drafting.
Each mode activates a set of recommended skills and a log draft template.

## Commands

| Command | Description |
|---------|-------------|
| `/mode exp` | Experiment mode — running code, recording metrics |
| `/mode daily` | Daily research — reading papers, taking notes |
| `/mode explore` | Exploration mode — systematic literature search via deep-research |
| `/mode report` | Report mode — generating slides for group meetings |
| `/mode publish` | Publication mode — full academic-pipeline workflow |
| `/mode status` | Show current mode + session activity summary |
| `/mode end` | End current mode, trigger auto-draft log entry |

---

## Mode Activation

When a mode is activated, do three things in order:

**1. Print the activation banner** (English only):

For `/mode exp`:
```
═══════════════════════════════════════
  [EXP] Experiment Mode — Active
═══════════════════════════════════════
  git HEAD : <run git_context.py --head silently>
  Tools    : /research-log add (Full mode)
  End      : /mode end → auto-draft log
═══════════════════════════════════════
```

For `/mode daily`:
```
═══════════════════════════════════════
  [DAILY] Daily Research Mode — Active
═══════════════════════════════════════
  Tools    : freeform notes, /research-log add
  End      : /mode end → lightweight log entry
═══════════════════════════════════════
```

For `/mode explore`:
```
═══════════════════════════════════════
  [EXPLORE] Exploration Mode — Active
═══════════════════════════════════════
  Tools    : deep-research (full / socratic / systematic-review / lit-review / fact-check)
  End      : /mode end → auto-draft log from report
═══════════════════════════════════════
```

For `/mode report`:
```
═══════════════════════════════════════
  [REPORT] Report Mode — Active
═══════════════════════════════════════
  Tools    : /report-slides
  End      : /mode end → log slide deck paths
═══════════════════════════════════════
```

For `/mode publish`:
```
═══════════════════════════════════════
  [PUBLISH] Publication Mode — Active
═══════════════════════════════════════
  Tools    : academic-pipeline (/ars-full, /ars-revision-coach, etc.)
  End      : /mode end → log current pipeline stage
═══════════════════════════════════════
```

**2. Route:** after the banner, recommend the primary skill to use next (one sentence).

**3. Snapshot (exp mode only):** silently run git_context.py to capture HEAD before the
user starts work. Store the HEAD value to pre-fill the log entry at `/mode end`.

```bash
GIT_CTX="$(find ~/.claude -path "*/research-log/scripts/git_context.py" | head -1)"
GIT_HEAD=$(python "$GIT_CTX" --head 2>/dev/null || echo "")
```

## Historical Experience Check

After activation routing and before research execution, apply the
`research-log` Historical Experience Check at the decision point defined for
the active mode. This adds prior evidence to the decision; it does not require
mode activation and does not replace the selected mode's primary workflow.

For direct research intent, use the `research-log` protocol even when no mode
is active. Query history only when the project has a non-empty
`docs/research_log/` journal and the next action is research planning,
recommendation, execution, repetition, or diagnosis. Follow the documented
`types → search → fetch` sequence, disclose query failures, and do not treat
an error as empty history.

Use the per-mode decision points in `references/routing_guide.md`. Keep all
banners, prompts, and user-visible research-mode output in English.

---

## `/mode status`

Print a compact summary:

```
Current mode : [MODE]
Started      : HH:MM (or "unknown")
Session work : <1-2 sentence summary of what has been done this session>
Next action  : <suggested next step>
```

---

## `/mode end` — Auto-Draft Log

When the user runs `/mode end`, collect session outputs and draft a log entry.
Read `references/mode_templates.md` for the draft template for the active mode.

### Flow

1. Collect data (see per-mode rules below)
2. Fill in the template from `references/mode_templates.md`
3. Present the draft to the user:
   ```
   ─────────────────────────────────────────
    Draft log entry — review and confirm
   ─────────────────────────────────────────
   <draft content here>
   ─────────────────────────────────────────
   Confirm? (yes / edit / skip)
   ```
4. If confirmed → call `/research-log add` with the pre-filled content
5. If edit → let user modify inline, then confirm again
6. If skip → discard draft, offer to switch modes

### Per-Mode Data Collection

**exp:**
- git HEAD: from snapshot taken at mode start (or re-run git_context.py)
- Changes: run `git_context.py --since-log <last-log-file>` and use Suggested Changes bullets
- Ask: "What were the key results? (numbers, metrics)"
- Ask: "What are the next steps?"

**daily:**
- Ask: "What did you read or work on today? (title / topic)"
- Ask: "What was the key insight or takeaway?"
- Ask: "Any open questions or follow-up items?"

**explore:**
- Extract from deep-research report (if available in session):
  - Research Question → Goal section
  - Executive Summary bullets → Analysis section
- Ask: "What are the next steps based on this research?"

**report:**
- Collect slide deck output path from report-slides (if available in session)
- Ask: "Who was the intended audience?"
- Ask: "One-sentence conclusion from the presentation?"

**publish:**
- Ask: "Which pipeline stage did you complete? (1=Research, 2=Write, 2.5=Integrity, 3=Review, 4=Revise, 4.5=Final Integrity, 5=Finalize)"
- Ask: "Stage result? (PASS / PENDING / needs-revision)"
- Ask: "Key next step?"

---

## Notes

- Mode is session-scoped. Starting a new Claude Code session clears the active mode.
- Multiple `/mode end` calls in one session are allowed — each drafts a new log entry.
- If no mode is active when `/mode end` is called, ask which mode this session was.
- All output text is English. Never output Chinese characters in banners or prompts.
