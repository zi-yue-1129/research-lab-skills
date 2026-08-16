# Third-Party Notices

This repository consolidates two independently-developed projects and adds
original integration work on top of both. This file records, path by path,
which parts are unmodified (or lightly modified) upstream content and which
parts were added or substantially rewritten in this repository after the
2026-06-10 merge (commit `f264da6`, "flatten academic-research-skills into
unified repo structure").

Basis for every line below: `git log` (dates, authorship, diff-filter=A),
`git show f264da6` and `51f29cb` (the import/refactor commits), and a direct
fetch of the upstream LICENSE/README from `Imbad0202/academic-research-skills`.
Where evidence was insufficient to assign a path with confidence, it is marked
`UNKNOWN` rather than guessed.

For the license text itself, see [LICENSE](LICENSE). This file is an
attribution index, not a license grant.

---

## 1. Academic Research Skills (ARS) — upstream, unmodified or lightly modified

**Upstream project:** https://github.com/Imbad0202/academic-research-skills
**Original author:** Cheng-I Wu (Imbad0202)
**Original license:** CC BY-NC 4.0 (verified directly against the upstream
`LICENSE` file, which declares "Copyright (c) 2026 Cheng-I Wu" under the
Creative Commons Attribution-NonCommercial 4.0 International License).
**Relationship:** Imported as a wholesale file copy on 2026-06-10 (commit
`f264da6`). No upstream git history was preserved — the import came from a
gitignored nested clone, not a git subtree/merge, so this repository's own
`git log` cannot show Imbad0202 as a commit author for any of this content.

| Path | Post-import activity in this repo |
|---|---|
| `skills/deep-research/`, `skills/academic-paper/`, `skills/academic-paper-reviewer/`, `skills/academic-pipeline/` | No evidence of substantial post-import rewrites found; treated as upstream. Not exhaustively diffed file-by-file. |
| `agents/`, `commands/`, `hooks/` | 0 commits since import — untouched. |
| `shared/` | 1 commit since import (`0c6ce2e`, path-fix only) — no content change. |
| `tests/` | 336 of 337 files untouched since import; 1 file touched by an unrelated fixture-sync commit. |
| `.github/workflows/` (9 files) | Imported "from ARS" per the `f264da6` commit message. 1 minor commit since import, 0 files added — treated as upstream. |
| `docs/design/*.md` (48 files) | All dated 2026-04-20 through 2026-06-08 in their own frontmatter/filenames — i.e. all predate the 2026-06-10 import. Upstream ARS design-history documents. |
| `docs/migration/v3.7.3-*.md` | Same as above — pre-import, upstream. |
| `docs/ARCHITECTURE.md`, `docs/SETUP.md`, `docs/SETUP.zh-TW.md`, `docs/PERFORMANCE.md`, `docs/PERFORMANCE.zh-TW.md` | No "Added"/rewrite commits found since import — content is the upstream version. (Note: `docs/SETUP.md`/`docs/SETUP.zh-TW.md` currently contain one stale post-import edit, a dead link to a nonexistent `research-lab-skills-codex` sibling repo — see [Known Issues](#known-issues) below.) |
| `examples/showcase/`, `examples/compliance/`, `examples/benchmark_report_template.json`, `examples/contradiction_pairs_example.md`, `examples/figure_table_trace_example.md`, `examples/passport_with_repro_lock.yaml` | Upstream ARS example/showcase artifacts. |
| `evals/calibration/`, `evals/gold/`, `evals/README.md` | Upstream ARS evaluation fixtures. |
| `scripts/` — all files **except** `scripts/generate_slides.py` (see §2) | Upstream ARS scripts (citation clients, `check_*.py`/`test_*.py` policy gates, claim-audit pipeline, etc.). 10 post-import commits touch this set, all narrow CI/lint/path fixes — not content rewrites. |

**Personal Project Statement (Cheng-I Wu, as published in the upstream repo):**
developed in personal time, on personal equipment, using self-paid AI
subscriptions; contains no confidential employer information; views and code
are the author's own.

---

## 2. Lab Skills and subsequent integration work — this repository's own

**Original author:** ZI-YUE, CHAO. GitHub identity: formerly `starpig1129`,
now `zi-yue-1129` (same person — verified via matching commit email
`james911129@gmail.com` and matching GitHub numeric user ID `102524453`
between the old and new account references; the `starpig1129` account no
longer resolves on GitHub).
**Original source (Lab Skills only, pre-merge):** the commit history of this
repository itself, starting at `f7bd69c` ("initial release of research-log
and report-slides skills"), before any ARS content existed in the repo.

| Path | Basis |
|---|---|
| `skills/research-log/`, `skills/report-slides/`, `skills/research-mode/` | Original Lab Skills, present since the repository's first commits, predating the ARS import by roughly two months. |
| `scripts/generate_slides.py` | Added in the very first commit (`f7bd69c`) — predates the ARS import entirely. Currently misfiled under a `scripts/` scope that older attribution text assigned wholesale to ARS/Imbad0202; corrected here. |
| `examples/research-log/`, `examples/report-slides/` | New subtrees created after the ARS import (first added 2026-06-12, commit `94372fb`, and expanded through 2026-08-04) — not present in, and not derived from, the ARS import. |
| `evals/report-slides-pptx-visual-review/`, `evals/report-slides-visual-authoring/` | Added 2026-08-03/2026-08-04, entirely local — report-slides visual-QA fixtures. |
| `docs/superpowers/` | 38 commits since the import (2026-06-13 through 2026-08-13) — the single most actively modified documentation path in this repository post-merge. |
| `docs/research_log/`, `docs/ROADMAP-v3.11.md` | Local project documentation, added post-import. |
| `bin/`, `bridge/`, `.claude-plugin/`, `install.sh`, `install.ps1`, `package.json` | Integration/packaging infrastructure written for the unified repo. |
| Root docs: `CHANGELOG.md`, `CONTRIBUTING.md`, `POSITIONING.md`, `QUICKSTART.md`, `SECURITY.md`, `MODE_REGISTRY.md`, `README.md` and locale variants | Written for the unified repo (some sections describing ARS features summarize upstream functionality rather than describing original work). |

### Original infrastructure created after both toolsets were merged

These three skills did not exist in either the original Lab Skills or the
original ARS import. They were built by this repository's maintainer between
2026-08-04 and 2026-08-06, entirely after the 2026-06-10 merge, to bridge the
two toolsets. They were previously **not attributed in NOTICE.md or LICENSE
at all** — that gap is corrected here.

| Path | First commit |
|---|---|
| `skills/resource-resolver/` | `312dc97`, 2026-08-04 |
| `skills/agent-state/` | `1e643af`, 2026-08-05 |
| `skills/research-project-init/` | `0b3a016`, 2026-08-06 |

---

## Known issues

- **Resolved in this pass:** `docs/SETUP.md:207` and `docs/SETUP.zh-TW.md:207`
  previously linked to `starpig1129/research-lab-skills-codex` as a "Codex
  CLI sibling distribution." Commit `686ec42` had already removed this same
  claim from `POSITIONING.md` with the note "no such repo," but the
  identical dead reference was never removed from `docs/SETUP.md`/
  `docs/SETUP.zh-TW.md` until now. Both files have been corrected to state
  plainly that no Codex plugin distribution exists and that Codex
  compatibility via manual copy is unverified.
- **Still open:** see `docs/LAUNCH_READINESS.md` for the version-string
  mismatch (package.json/npm at 1.0.0 vs. docs/badges/plugin manifest at
  1.1.0, with no matching GitHub release/tag) and the un-mirrored README
  positioning language in `README.zh-CN.md`/`README.ja-JP.md`.
- `LICENSE` line 11 names `starpig1129/claude-research-skills` as the
  historical source URL for Lab Skills — a third, distinct repository name
  from `research-lab-skills`. Its prior existence as an independent repo
  could not be confirmed or denied from available evidence (GitHub's rename
  redirect is consistent with, but does not prove, that name having existed
  under that owner). Left as-is; flagged as `UNKNOWN` in
  `docs/LAUNCH_READINESS.md`.
