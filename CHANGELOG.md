# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- **`report-slides`: PowerPoint as a native Windows renderer** (`scripts/pptx_com.py`) — a stock Windows install has neither `libreoffice` nor `pdftoppm`, so the authoritative `pptx_render` gate was permanently `blocked` there and no deck could reach `completed`. On a machine with Office, `--render` drives PowerPoint over COM and exports one PNG per slide directly, with no PDF intermediate, rendering with the same engine the reader will open the deck in. It emits the `renderer` / `conversion_artifacts` / `rendered_png_paths` fields ready to merge into a review record, and exits 2 with the exact missing capability when the host cannot render, which is the cue to fall back to LibreOffice.
- **`report-slides`: post-layout geometry oracle** (`pptx_com.py --layout`) — reports the height text *actually* occupies after PowerPoint lays the deck out, a fact `python-pptx` structurally cannot supply because it has no font metrics. Distinguishes text that is cut off (`clipped`) from text that stays legible while growing past its declared bounds (`overflows_box`), turning clipping and text-reflow findings into measurements rather than inferences.
- **`install.ps1 -Doctor`** — reports every runtime dependency the skills shell out to (python-pptx, lxml, the renderer chain, `mmdc`) with the command that fixes each gap. Copying skill directories was never a complete install, and each missing piece previously surfaced as a silent no-op mid-deck.
- **`docs/SETUP.md`: `report-slides` dependency section** — the skill's Python, renderer, and diagram dependencies were undocumented. Also records that Windows must run the skills' `python3 ...` commands as `python ...`, because `python3` there resolves to a Microsoft Store stub that exits without output.

## [1.1.0] - 2026-08-16

### Added

- **`research-project-init`: new skill** — turns a preliminary research idea into a scoped project charter (problem statement, scope, exclusions, contributions, constraints, resources, milestones, success/stop conditions, risks, ethics) and registers a Project plus its Initial Research Questions in `agent-state`. Sits upstream of `deep-research`.
- **`agent-state`: Source/Evidence entities** — structured, deduplicated literature sources (dedup by DOI, then normalized URL, then a title+author+year hint) and stance-tagged Evidence Statements, registered automatically by `deep-research`'s `bibliography_agent`/`source_verification_agent`/`synthesis_agent` alongside the Markdown reports they already produce. `record_claim` can now point at a specific Evidence record via `--evidence-id`.
- **`report-slides`: authoritative converted-PPTX visual review gate** — the rendered PPTX, not the source SVG, is now the ground truth for visual review, catching text-reflow, image-crop, and asset-drift regressions that only surface after PowerPoint conversion.
- **`report-slides`: diagram asset manifest validation** and a **visual review sheet tool** for tracking which reusable visuals have been reviewed.
- **`report-slides`: interactive, bilingual mode selection** for the `svg_to_pptx` conversion flow.
- **`report-slides`: native PPTX table/chart/group construction** — tables and charts render as native, editable PowerPoint objects (not flattened images), with a safety-net validation gate (`validate_native_objects.py`), hard authoring rules for `data-pptx-role` marker placement (including `x`/`y` on `<text>`), and line/pie chart renderers.
- **`research-log`: Milestone Mode** with token-budget gating (`log_stats.py`) for large research logs.
- **`research-log`: historical section queries** — discover historical section types and search sections by type/date, with safe batched fetching and budget diagnostics.
- **Onboarding demo** (`examples/`) walking through a `research-log` + `report-slides` end-to-end workflow.
- **npm package**: dual bin alias (`crs` and `research-lab-skills`) with improved install docs.
- **Native PowerShell installer** (`install.ps1`) — mirrors `install.sh` (`-Local`, `-ArsOnly`, `-LabOnly`, `-Uninstall`) so Windows users can install directly from PowerShell or cmd.exe without Git Bash or WSL.
- **`THIRD_PARTY_NOTICES.md`** — path-by-path attribution splitting upstream Academic Research Skills content from original lab-workflow/infrastructure work added in this repository.

### Changed

- **Installation docs no longer recommend npm.** `npm install -g research-lab-skills` / `npx` instructions and the npm badge have been removed from the README variants and `QUICKSTART.md`; `curl`/PowerShell/`git clone` (`install.sh` / `install.ps1`) are the supported install paths going forward. The `crs` CLI source (`bin/crs.js`) remains in the repository but is no longer documented as a primary install method, and its `--ai cursor/windsurf/copilot` flags — which had no verified runtime-compatibility evidence — are no longer advertised.
- **Attribution corrected.** `NOTICE.md` and the new `THIRD_PARTY_NOTICES.md` replace the previous blanket per-directory attribution with a path-level breakdown; `skills/resource-resolver`, `skills/agent-state`, and `skills/research-project-init` are now attributed (previously unattributed anywhere).

### Fixed

- **`report-slides`**: preserve native text layout and restore accurate baseline correction, dynamic width, and z-order during SVG→PPTX conversion.
- **`report-slides`**: convert container rects to paths so regenerated decks render correctly.
- **`research-log`**: historical section queries now require type discovery before searching, surface query errors instead of failing silently, and require exact custom section names.
- **Repo layout**: path fixes across policy-anchor, skill-lint discovery, and CI spec/version consistency checks after the `skills/` subdirectory restructuring.
- **Installation**: the documented `bash <(curl -fsSL ...)` command used process substitution, which fails in PowerShell/cmd.exe and is unreliable even in Git Bash; replaced with `curl -fsSL ... | bash` across all docs.
- **Identity/URL consistency**: canonicalized operational repository URLs from the renamed `starpig1129` GitHub account to `zi-yue-1129` across install scripts, all README locales, and other docs; removed a dead `research-lab-skills-codex` link from `docs/SETUP.md`/`docs/SETUP.zh-TW.md`.

## [1.0.0] - 2026-06-12

### Added

- **Unified `research-lab-skills` suite** — merged two independently-developed projects into a single repo with one install command. Lab-tools (experiment journal, slides, session mode routing) originally by ZI-YUE,CHAO; Academic Research Skills (deep research, paper writing, peer review, pipeline) originally by Cheng-I Wu. See [NOTICE.md](NOTICE.md) for full attribution.
- **7 skills in one install**: `research-log`, `report-slides`, `research-mode` (lab) + `deep-research`, `academic-paper`, `academic-paper-reviewer`, `academic-pipeline` (ARS).
- **Bash installer** (`install.sh`) with `--lab-only` / `--ars-only` / `uninstall` flags; works on macOS, Linux, and Git Bash.
- **npm package** (`crs` CLI) with `crs init` / `crs init --global` / `crs init --lab-only` / `crs init --ars-only`; supports Claude Code, Cursor, Windsurf, and Copilot targets.
- **Examples** for lab-tools skills: `examples/research-log/` (quick-mode + full-mode journal entries, INDEX.md) and `examples/report-slides/` (7-slide `slide_data.json`, rendered SVG samples, README).

---

*Academic Research Skills (ARS) upstream changelog: [Imbad0202/academic-research-skills](https://github.com/Imbad0202/academic-research-skills)*
