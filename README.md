# research-lab-skills

[![npm](https://img.shields.io/npm/v/research-lab-skills)](https://www.npmjs.com/package/research-lab-skills)
[![Version](https://img.shields.io/badge/version-v1.1.0-blue)](https://github.com/starpig1129/research-lab-skills/releases/tag/v1.1.0)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/license-CC%20BY--NC%204.0-lightgrey)](https://creativecommons.org/licenses/by-nc/4.0/)

[简体中文版](README.zh-CN.md) | [繁體中文版](README.zh-TW.md) | [日本語版](README.ja-JP.md)

---

## What this is for

I built research-lab-skills as a Claude Code skill suite covering the full academic research lifecycle — from daily experiment journals and progress presentations to systematic literature review, paper writing, and peer review simulation. It integrates two complementary toolsets:

- **Lab skills** (`research-log`, `report-slides`, `research-mode`) — experiment journals, progress slides, session mode routing
- **Academic Research Skills** (`deep-research`, `academic-paper`, `academic-paper-reviewer`, `academic-pipeline`) — literature review, paper writing, peer review, full-pipeline orchestration

See the detailed sections below for each skill.

## Why you need it

Research labs spend enormous amounts of time making slides for weekly meetings. The problem isn't slide design — most presentation tools handle that fine. The problem is they have no idea **what belongs in this week's slides**. You end up staring at a blank deck, trying to remember what you actually did.

That's why I built the research journal mechanism first. When you log your experiments in a structured format, the AI already knows what ran this week, what failed, what the numbers look like, and what needs to be communicated. The slides are a natural output of that record — not a separate task on top of your research.

The same problem runs deeper. The daily process of research — the experiments that didn't pan out, the architectural pivots, the decisions made between runs — vanishes long before the paper gets written. By the time you're writing the methodology section, you're reconstructing from memory what you actually did and why. The formal output pipeline often starts from scratch, disconnected from the months of work that produced the insight.

This suite keeps the thread intact. Your journal records the *why* behind every decision; the lab-meeting slides come from those logs; the methodology section comes from those logs too. The session modes (`exp` → `explore` → `publish`) track which phase of research you're in and route you to the right tools automatically.

Nothing gets lost between the bench and the bibliography.

---

| Skill | Command | Purpose |
|-------|---------|---------|
| `research-log` | `/research-log` | Structured experiment journal (daily logs, amendments, index) |
| `report-slides` | `/report-slides` | SVG + PPTX progress presentations from journal entries |
| `research-mode` | `/mode` | Session mode routing (exp / daily / explore / report / publish) |
| `deep-research` | `/ars-full`, `/ars-lit-review`, … | 13-agent research team with Socratic mode, PRISMA, fact-check |
| `academic-paper` | `/ars-plan`, `/ars-outline`, … | 12-agent paper writing with citation verification |
| `academic-paper-reviewer` | `/ars-review`, `/ars-re-review` | Multi-perspective peer review (EIC + 3 reviewers + DA) |
| `academic-pipeline` | `/ars-pipeline` | Full 10-stage pipeline orchestrator |

---

## The integrated research lifecycle

These skills are not a feature list — they're a workflow. Each one was designed for a specific phase of research and hands off naturally to the next.

**Phase 1 — Daily experiment work** (`/mode exp`)

```bash
/mode exp                       # start an experiment session
/research-log add               # log today's work (quick: 3 questions; full: 9 sections)
/report-slides                  # turn this week's journal into a progress presentation
/mode end                       # draft the next entry from today's git diff
```

The journal's `follows:` field links experiments into a traceable timeline. `amended:` records post-hoc corrections. `slide_decks:` updates automatically when slides are generated. These entries are the raw material for your methodology section when you eventually write the paper — capturing not just what worked, but why you tried it and what failed first.

**Phase 2 — Literature exploration** (`/mode explore`)

```bash
/mode explore
/ars-lit-review "your topic"    # 13-agent literature review with PRISMA support
/ars-socratic                   # Socratic dialogue to sharpen your research question
/mode end                       # extract RQ + key findings into the log
```

**Phase 3 — Writing and publication** (`/mode publish`)

```bash
/mode publish
/ars-plan                       # Socratic-guided chapter planning
/ars-full                       # 12-agent paper writing + citation verification
/ars-review                     # multi-perspective peer review (EIC + 3 reviewers + DA)
/ars-re-review                  # post-revision acceptance check
/ars-pipeline                   # full 10-stage orchestrated pipeline with integrity gates
```

**How the journal connects to the paper**

| Journal field | Paper section |
|--------------|--------------|
| `Goal` + `Setup` | Methodology |
| `Results` + `Charts` | Results & Figures |
| `Failures` + `Analysis` | Discussion / Limitations |
| `slide_decks:` links | Figure sources |
| `follows:` timeline | Research design narrative |

→ See **[examples/](examples/)** for a complete worked example: three journal entries showing the messy week-by-week process (failures, `amended:` corrections, unresolved problems), a 7-slide lab-meeting progress deck generated from those logs, and the JSON data file that drove the charts. The SVG slides also ship as a `deck.pptx` — every element editable in PowerPoint or Keynote.

---

## Installation

### curl / PowerShell (recommended, no npm account needed)

**macOS / Linux / Git Bash / WSL:**

```bash
# All skills (global)
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash

# Project-local
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- --local

# ARS skills only
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- --ars-only

# Lab skills only
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- --lab-only

# Uninstall
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- uninstall
```

**Windows (PowerShell)** — native, no Git Bash or WSL required:

```powershell
# All skills (global)
irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1 | iex

# Flags require the script body, not a piped invocation — wrap it in a scriptblock:
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -Local
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -ArsOnly
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -LabOnly
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -Uninstall
```

**Windows (cmd.exe)** — wrap the PowerShell command:

```bat
powershell -Command "irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1 | iex"
```

Both `install.sh` and `install.ps1` just need `git` on `PATH` (no npm account, no login).

### npm

```bash
npm install -g research-lab-skills
crs init --global          # install all 7 skills globally
```

Or one-shot with npx (no permanent npm install):

```bash
npx research-lab-skills init --global
```

**Options:**

| Flag | What installs |
|------|---------------|
| _(none)_ | All 7 skills (project-local `.claude/skills/`) |
| `--global` | All 7 skills globally (`~/.claude/skills/`) |
| `--lab-only` | `research-log`, `report-slides`, `research-mode` |
| `--ars-only` | `deep-research`, `academic-paper`, `academic-paper-reviewer`, `academic-pipeline` |
| `--ai cursor` | Install for Cursor instead of Claude Code |

```bash
crs update --global        # reinstall after npm upgrade
crs uninstall --global     # remove skills
```

Restart Claude Code after install.
Lab skills: `/research-log`, `/report-slides`, `/mode`
Academic skills: `/ars-plan`, `/ars-full`, `/ars-lit-review`, `/ars-review`, and more.

---

## Lab Skills

### `/research-log` — Experiment Journal

Manages a structured journal in `docs/research_log/` (one `.md` file per experiment).

| Command | Description |
|---------|-------------|
| `/research-log add` | Start quick (3 questions) or full (9 sections) guided entry |
| `/research-log amend` | Edit sections of an existing entry |
| `/research-log index` | Rebuild `docs/research_log/INDEX.md` from frontmatter |
| `/research-log show [n]` | Show compact summary of the last n entries (default 5) |
| `/research-log query` | Find section types, search history by section/date, then fetch selected results within a safe token budget |

Each entry is a Markdown file with YAML frontmatter tracking `follows:` links between experiments and `slide_decks:` updated automatically when slides are generated.

Agents proactively consult relevant history before starting new experiments, diagnosing anomalies, changing parameters, or launching costly reruns, even when `/mode` is not active.

---

### `/report-slides` — Presentation Generator

Reads journal entries, proposes a slide outline for confirmation, then generates slides via three rendering paths:

- **[A] Python script** — data-driven slides: bar charts, tables, metric cards, timelines
- **[B] Mermaid** — diagram slides: flowcharts, architecture diagrams, state machines
- **[C] Claude SVG** — free-form slides: conceptual layouts, text-heavy content

Output: `docs/slides/reports/YYYY-MM-DD_<deck-name>/`
- `slide01_title.svg`, `slide02_bar_chart.svg`, … (editable SVG source files)
- **`deck.pptx`** — 16:9 PPTX with native SVG embedding. Every title, number, colour, and layout element is directly editable in PowerPoint or Keynote — no roundtripping back to source code.
- `slide_data.json` (Path A source, use `--slide N` to re-render one slide)

**First-time project setup:**

```bash
bash "$(find ~/.claude -path "*/report-slides/scripts/setup.sh" | head -1)"
```

**Dependencies:**

```bash
pip install python-pptx
npm install -g @mermaid-js/mermaid-cli   # optional, Mermaid diagrams only
```

**Slide styles:** `default`, `minimal`, `dark`, `paper`

```bash
bash "$(find ~/.claude -path "*/report-slides/scripts/set-style.sh" | head -1)" paper
```

---

### `/mode` — Session Mode Routing

Declares active research mode to adjust which skills are prioritized and how sessions end:

| Mode | Primary Skills | Use when |
|------|---------------|----------|
| `exp` | `research-log` (Full) | Running experiments, want auto-log at session end |
| `daily` | none (freeform) | Lightweight notes, reading |
| `explore` | `deep-research` | Literature exploration |
| `report` | `report-slides` | Generating progress presentations |
| `publish` | `academic-pipeline` | Writing and submitting a paper |

End a session with `/mode end` to get a pre-filled journal entry draft.

---

## Academic Research Skills

> **AI is your copilot, not the pilot.** This tool won't write your paper for you. It handles the grunt work — hunting down references, formatting citations, verifying data, checking logical consistency — so you can focus on the parts that actually require your brain.

**👉 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — full pipeline view: flow diagram, stage-by-stage matrix, quality gates, and mode list.

**👉 [docs/SETUP.md](docs/SETUP.md)** — full setup guide: API keys, optional Pandoc/tectonic for DOCX/PDF, cross-model verification.

**👉 [docs/PERFORMANCE.md](docs/PERFORMANCE.md)** — per-mode token budgets, full-pipeline cost estimate (~$4–6 for a 15k-word paper).

### Features at a glance

- **Deep Research** (`/ars-full`, `/ars-lit-review`, `/ars-systematic-review`) — 13-agent research team. Socratic guided mode, PRISMA systematic review, four-index citation triangulation (Semantic Scholar + OpenAlex + Crossref + arXiv), cross-model DA critique.
- **Academic Paper** (`/ars-plan`, `/ars-outline`, `/ars-abstract`) — 12-agent paper writing. Style Calibration, Writing Quality Check, three-layer citation anchors, LaTeX hardening, VLM figure verification, revision coaching.
- **Academic Paper Reviewer** (`/ars-review`, `/ars-re-review`) — 7-agent peer review. EIC + 3 dynamic reviewers + Devil's Advocate, concession threshold protocol, opt-in calibration mode, R&R traceability matrix.
- **Academic Pipeline** (`/ars-pipeline`) — 10-stage end-to-end orchestrator. Integrity gates at Stage 2.5 + 4.5, Material Passport, citation existence gate, Collaboration Depth Observer, score trajectory tracking.

### Full pipeline

```
deep-research (socratic/full)
  → academic-paper (plan/full)
    → integrity check (Stage 2.5)
      → academic-paper-reviewer (full/guided)
        → academic-paper (revision)
          → academic-paper-reviewer (re-review, max 2 loops)
            → final integrity check (Stage 4.5)
              → academic-paper (format-convert → final output)
```

See **[examples/showcase/](examples/showcase/)** for artifacts from a complete 10-stage pipeline run (peer review reports, integrity checks, final papers).

---

## Examples

The [`examples/`](examples/) directory contains a complete worked scenario — an NLP researcher working on cross-lingual automated essay scoring across three weeks of experiments.

**Research journal** ([`examples/research-log/`](examples/research-log/)) — three entries showing the full arc: a quick baseline log on day one, a full entry mid-project with failures and a post-hoc `amended:` correction, and a final-week entry with two amendments and open questions. The `follows:` chain links them into a traceable timeline.

**Progress slides** ([`examples/report-slides/`](examples/report-slides/)) — a 7-slide weekly lab-meeting presentation generated from those journal entries. Slides cover: title, problem/approach, timeline (with `amended` badges), grouped bar chart, model comparison table (with DIF fairness markers), metric cards, and conclusion + next steps. All slides are SVG source files convertible to an editable `deck.pptx` — see [`examples/report-slides/README.md`](examples/report-slides/README.md) for the generation command.

---

## File Structure

```
docs/research_log/
  INDEX.md                              ← auto-generated (do not edit)
  2026-05-15_backbone_v3.md

docs/slides/
  _style.md                             ← project default style (optional)
  reports/
    2026-05-19_weekly/
      slide01_title.svg
      deck.pptx
      slide_data.json

scripts/
  generate_slides.py                    ← copied from skill on first use
  to_pptx.py
```

---

## Sources

- Lab skills (`research-log`, `report-slides`, `research-mode`) — [`starpig1129/research-lab-skills`](https://github.com/starpig1129/research-lab-skills) (CC BY-NC 4.0)
- Academic Research Skills (`deep-research`, `academic-paper`, `academic-paper-reviewer`, `academic-pipeline`) — originally [`Imbad0202/academic-research-skills`](https://github.com/Imbad0202/academic-research-skills) (CC BY-NC 4.0)

See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md) for licensing details.
