# research-lab-skills — Project Routing Rules

## Research Mode Routing

Active mode is declared by `/mode <name>`. When a mode is active, use it to adjust
which skills to prioritize and how session endings are handled.

| Mode | Primary Skills | Do NOT auto-trigger |
|------|---------------|---------------------|
| `exp` | `research-log` (Full mode) | deep-research, academic-pipeline |
| `daily` | none (freeform) | deep-research, academic-pipeline |
| `explore` | `deep-research` | academic-pipeline |
| `report` | `report-slides` | academic-pipeline |
| `publish` | `academic-pipeline` | — |

**Rules:**

- **exp**: Run `git_context.py` silently at mode start. On `/mode end`, draft a Full-mode
  research-log entry pre-filled with git diff bullets and git HEAD.

- **daily**: Lightweight notes only. Do NOT invoke deep-research or academic-pipeline
  unless the user explicitly asks. On `/mode end`, draft a minimal log entry asking
  for reading topics and key insights.

- **explore**: Route first to `deep-research`. When deep-research produces a report,
  offer `/mode end` to draft a log entry extracting the Research Question and key findings.
  Sub-modes (systematic-review, lit-review, fact-check) get their own templates — see
  `skills/research-mode/references/mode_templates.md`.

- **report**: Route to `report-slides`. After deck generation, suggest `/mode end` to
  log the slide deck paths and audience.

- **publish**: Route to `academic-pipeline`. After each stage completes, offer `/mode end`
  to log the stage status. `/ars-*` commands automatically activate publish mode (Phase 3).

**If no mode is active:** apply the Academic Research Skills Routing Discipline below.

---

## Installation

Skills installed here are available globally after `bash install.sh`.
To install locally only: `bash install.sh --local`

---

## Academic Research Skills Routing Discipline (v3.9.2)

**Routing precedence:** This section runs BEFORE Routing Rules 1-5. Once this section settles on a destination, Rules 1-5 apply within that destination's skill family.

**Step 0 — Escape hatch check (before any classification):** If the user's first message begins with `[direct-mode]` (case-insensitive byte-0 token, optionally preceded by whitespace/newlines that are stripped on parse), record this fact, strip the prefix and surrounding whitespace from the message, and skip directly to **Step 1 explicit-intent handling** on the stripped content. The literal `[direct-mode]` is NOT passed through to the dispatched agent. If the stripped message itself has no clear skill named, Step 1 falls through to Step 3 clarification (the escape hatch bypasses cross-phase clarification (Step 2), not all routing).

Otherwise, classify the user's input:

1. **Explicit clear intent** — user invokes a specific skill via `/ars-*` slash command, or uses an unambiguous trigger keyword that maps to a single skill (e.g., "lit-review this", "review my paper", "draft an abstract"):
   → Route directly; no clarification, no orchestrator detour.

2. **Cross-phase materials detected** — user provides artifacts spanning ≥ 2 pipeline phases without naming a specific skill (e.g., pre-written abstract + pre-collected literature; full draft + reviewer comments + bibliography):
   → **Clarify**. Do NOT auto-route to a single-phase agent. List candidate workflows as a-d options in markdown body (NOT via AskUserQuestion tool). See `shared/protocols/intent_clarification_protocol.md` for the message template.
   → Reason: clarification is the safest action when materials don't unambiguously identify intent.

3. **Ambiguous intent, no materials** — user provides no artifacts and no clear request:
   → Clarify per `shared/protocols/intent_clarification_protocol.md`.

## Routing Rules

1. **academic-pipeline vs individual skills**: academic-pipeline = full pipeline orchestrator (research → write → integrity → review → revise → final integrity → finalize). If the user only needs a single function (just research, just write, just review), trigger the corresponding skill directly without the pipeline.

2. **deep-research vs academic-paper**: Complementary. deep-research = upstream research engine (investigation + fact-checking), academic-paper = downstream publication engine (paper writing + bilingual abstracts). Recommended flow: deep-research → academic-paper.

3. **deep-research socratic vs full**: socratic = guided Socratic dialogue to help users clarify their research question. full = direct production of research report. When the user's research question is unclear, suggest socratic mode.

4. **academic-paper plan vs full**: plan = chapter-by-chapter guided planning via Socratic dialogue. full = direct paper production. When the user wants to think through their paper structure, suggest plan mode.

5. **academic-paper-reviewer guided vs full**: guided = Socratic review that engages the author in dialogue about issues. full = standard multi-perspective review report. When the user wants to learn from the review, suggest guided mode.

6. **research-project-init vs deep-research socratic**: research-project-init = scopes a *project* (problem statement, scope, exclusions, contributions, constraints, resources, milestones, success/stop conditions, risks, ethics) and registers it in agent-state, without sharpening any research question or doing research. deep-research socratic = sharpens a *single* research question (FINER scoring, methodology blueprint) once one exists. When the user's request is about project-level scope/governance rather than one question, prefer research-project-init; when it's about clarifying one question, prefer deep-research socratic (unchanged default). Recommended flow: research-project-init → deep-research (socratic/full).

## Key Rules

- All claims must have citations
- Evidence hierarchy respected (meta-analyses > RCTs > cohort > case reports > expert opinion)
- Contradictions disclosed with evidence quality comparison
- AI disclosure in all reports
- Default output language matches user input (Traditional Chinese or English)

## Full Academic Pipeline

```
research-project-init (optional)
  → deep-research (socratic/full)
    → academic-paper (plan/full)
      → integrity check (Stage 2.5)
        → academic-paper-reviewer (full/guided)
          → academic-paper (revision)
            → academic-paper-reviewer (re-review, max 2 loops)
              → final integrity check (Stage 4.5)
                → academic-paper (format-convert → final output)
                  → Process Summary + AI Self-Reflection Report
```

- **Suite version**: 1.1.0

## Skills Overview

| Skill | Description |
|-------|-------------|
| `research-project-init` v1.0.0 | Project scoping (upstream of deep-research) |
| `deep-research` v2.9.4 | Research engine |
| `academic-paper` v3.2.0 | Paper writer |
| `academic-paper-reviewer` v1.10.0 | Peer reviewer |
| `academic-pipeline` v3.11.1 | Pipeline orchestrator |

## Handoff Protocol

### research-project-init → deep-research
Materials: Project ID, Initial Research Question ID(s), charter file path
(`.research/projects/<project_id>/charter.md`).

### deep-research → academic-paper
Materials: RQ Brief, Methodology Blueprint, Annotated Bibliography, Synthesis Report, INSIGHT Collection

### academic-paper → academic-paper-reviewer
Materials: Complete paper text. field_analyst_agent auto-detects domain and configures reviewers.

### academic-paper-reviewer → academic-paper (revision)
Materials: Editorial Decision Letter, Revision Roadmap, Per-reviewer detailed comments
