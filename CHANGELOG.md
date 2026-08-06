# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- **`research-project-init`: new skill** — turns a preliminary research idea into a scoped project charter (problem statement, scope, exclusions, contributions, constraints, resources, milestones, success/stop conditions, risks, ethics) and registers a Project plus its Initial Research Questions in `agent-state`. Sits upstream of `deep-research`.
- **`agent-state`: Source/Evidence entities** — structured, deduplicated literature sources (dedup by DOI, then normalized URL, then a title+author+year hint) and stance-tagged Evidence Statements, registered automatically by `deep-research`'s `bibliography_agent`/`source_verification_agent`/`synthesis_agent` alongside the Markdown reports they already produce. `record_claim` can now point at a specific Evidence record via `--evidence-id`.

## [1.1.0] - 2026-08-04

### Added

- **`report-slides`: authoritative converted-PPTX visual review gate** — the rendered PPTX, not the source SVG, is now the ground truth for visual review, catching text-reflow, image-crop, and asset-drift regressions that only surface after PowerPoint conversion.
- **`report-slides`: diagram asset manifest validation** and a **visual review sheet tool** for tracking which reusable visuals have been reviewed.
- **`report-slides`: interactive, bilingual mode selection** for the `svg_to_pptx` conversion flow.
- **`research-log`: Milestone Mode** with token-budget gating (`log_stats.py`) for large research logs.
- **`research-log`: historical section queries** — discover historical section types and search sections by type/date, with safe batched fetching and budget diagnostics.
- **Onboarding demo** (`examples/`) walking through a `research-log` + `report-slides` end-to-end workflow.
- **npm package**: dual bin alias (`crs` and `research-lab-skills`) with improved install docs.
- **Native PowerShell installer** (`install.ps1`) — mirrors `install.sh` (`-Local`, `-ArsOnly`, `-LabOnly`, `-Uninstall`) so Windows users can install directly from PowerShell or cmd.exe without Git Bash or WSL.

### Fixed

- **`report-slides`**: preserve native text layout and restore accurate baseline correction, dynamic width, and z-order during SVG→PPTX conversion.
- **`report-slides`**: convert container rects to paths so regenerated decks render correctly.
- **`research-log`**: historical section queries now require type discovery before searching, surface query errors instead of failing silently, and require exact custom section names.
- **Repo layout**: path fixes across policy-anchor, skill-lint discovery, and CI spec/version consistency checks after the `skills/` subdirectory restructuring.
- **Installation**: the documented `bash <(curl -fsSL ...)` command used process substitution, which fails in PowerShell/cmd.exe and is unreliable even in Git Bash; replaced with `curl -fsSL ... | bash` across all docs.

## [1.0.0] - 2026-06-12

### Added

- **Unified `research-lab-skills` suite** — merged two independently-developed projects into a single repo with one install command. Lab-tools (experiment journal, slides, session mode routing) originally by ZI-YUE,CHAO; Academic Research Skills (deep research, paper writing, peer review, pipeline) originally by Cheng-I Wu. See [NOTICE.md](NOTICE.md) for full attribution.
- **7 skills in one install**: `research-log`, `report-slides`, `research-mode` (lab) + `deep-research`, `academic-paper`, `academic-paper-reviewer`, `academic-pipeline` (ARS).
- **Bash installer** (`install.sh`) with `--lab-only` / `--ars-only` / `uninstall` flags; works on macOS, Linux, and Git Bash.
- **npm package** (`crs` CLI) with `crs init` / `crs init --global` / `crs init --lab-only` / `crs init --ars-only`; supports Claude Code, Cursor, Windsurf, and Copilot targets.
- **Examples** for lab-tools skills: `examples/research-log/` (quick-mode + full-mode journal entries, INDEX.md) and `examples/report-slides/` (7-slide `slide_data.json`, rendered SVG samples, README).

---

*Academic Research Skills (ARS) upstream changelog: [Imbad0202/academic-research-skills](https://github.com/Imbad0202/academic-research-skills)*
