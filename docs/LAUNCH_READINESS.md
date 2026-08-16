# Launch Readiness

Provenance, attribution, licensing, identity, and compatibility audit ahead of
public posting (Reddit / Hacker News / GitHub). This is the second pass —
every item below was re-verified against the current public repository
state (`gh api`, `gh release`, `gh issue`, direct file reads), not copied
forward from the first audit. Full per-path attribution is in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Blocking

None currently open.

## Important

- **Issue #8 is open and confirms a real Codex compatibility gap.**
  A user installed via `install.ps1`, imported the skills into Codex, and
  reported that `/report-slides` does not generate an architecture diagram
  from a README — it only echoes the repo's file/directory structure. This
  is not a theoretical "unverified" concern anymore; it's a reported
  failure. `docs/SETUP.md`'s plugin-platform-scope note and the removed
  `codex` repository topic already reflect "unverified/no packaged
  distribution," which is consistent with this report, but the issue itself
  is still open with no maintainer reply. A factual response has been
  drafted for review (not posted — see the accompanying report) but the
  issue was intentionally **not** closed or auto-answered.
- **`LICENSE` line 11's historical source URL remains unverifiable.**
  `Source: https://github.com/starpig1129/claude-research-skills` — a
  third, distinct repository name from `research-lab-skills`. Still cannot
  be confirmed or denied from available evidence. `LICENSE` was not
  modified this pass either (no concrete correctness issue found, per
  standing instruction not to touch it absent one).
- **Local `git remote origin` still points at the old owner**
  (`git@github.com:starpig1129/research-lab-skills.git`). Unchanged since
  the last audit — GitHub's redirect keeps push/pull working, but this is
  local dev configuration the maintainer should update directly.
- **`LICENSE`'s attribution scope is still coarser than `NOTICE.md`'s.**
  Unchanged since the last audit and intentionally left as-is: `LICENSE`
  lists `scripts/`, `evals/`, `examples/`, and ARS `docs/` wholesale under
  Cheng-I Wu's copyright block; `NOTICE.md`/`THIRD_PARTY_NOTICES.md` carry
  the precise path-level split. Both scopes carry the same CC BY-NC 4.0
  license, so this doesn't change what governs the code.
- **`bin/crs.js`'s `--ai cursor/windsurf/copilot` code path is now fully
  undocumented, not just downgraded.** The prior pass marked it
  "experimental, unverified" in README; this pass removed the entire npm
  install section (including that table row) from every README locale.
  The code itself is unchanged and still runs if someone finds `crs`
  directly — it's just no longer discoverable from any doc. Not a
  correctness problem, just worth knowing before deciding whether to
  restore documentation for it later.
- **`README.zh-CN.md`/`README.ja-JP.md` still don't mention
  `resource-resolver`/`agent-state`/`research-project-init` outside the
  positioning section and license block** (their skill tables and
  install-options tables were not touched — out of scope, since this pass
  and the last one were both explicitly told not to redesign README
  content beyond attribution/positioning). `README.md`/`README.zh-TW.md`
  have the same gap in their skill tables. Tracked as a README-redesign
  item, not a provenance/attribution one.

## Nice-to-have

- Once there's bandwidth, mirror `research-project-init` into the skill
  tables of all four README locales now that it's plugin-installable
  (currently plugin-discoverable but not listed as a row in any README
  skill table).
- `scripts/check_version_consistency.py` — still not confirmed whether it
  would catch a future README-badge-vs-`package.json` drift; not
  investigated this pass either.
- Showcase/demo discoverability remains reasonable; no action needed.

## Resolved

**This pass:**

- **Version alignment shipped.** `package.json` is `1.1.0`, matching
  `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
  `v1.1.0` is a real, non-draft GitHub release
  (https://github.com/zi-yue-1129/research-lab-skills/releases/tag/v1.1.0)
  with a `v1.1.0` git tag, and `CHANGELOG.md` now has one consolidated
  `[1.1.0] - 2026-08-16` entry (including the native-PPTX report-slides
  work that had been merged from a separate branch and was initially
  missing from the changelog). The stale draft `v1.0.0` GitHub release was
  deleted; the `v1.0.0` tag was kept as a historical record.
- **`research-project-init` is now wired into the plugin marketplace.**
  Added to `.claude-plugin/marketplace.json`'s `academic-research-skills`
  bundle (not `lab-tools`) — this follows `install.sh`'s own architecture,
  which already groups `research-project-init` inside its `ARS_SKILLS`
  array alongside `deep-research`/`academic-paper`/
  `academic-paper-reviewer`/`academic-pipeline`. Bundle description updated
  to mention project scoping. Verified: `skills/research-project-init/SKILL.md`
  exists with valid `name`/`description` frontmatter, so `/plugin install
  academic-research-skills` will now actually surface it.
- **`README.zh-CN.md`/`README.ja-JP.md` positioning synced.** Both now
  state, in their own language, that ARS is upstream work by Cheng-I Wu
  (with the upstream repo link) and that the lab workflow/infrastructure
  (including `resource-resolver`/`agent-state`/`research-project-init`) is
  this repository's own work — matching `README.md`/`README.zh-TW.md`.
  Their license/credit sections were updated the same way, including a
  link to `THIRD_PARTY_NOTICES.md`. Translation credit line in
  `README.ja-JP.md` (eltociear) preserved untouched.
- **`POSITIONING.md` corrected.** Citation version bumped to 1.1.0 and
  split into two citations (research-lab-skills as a whole vs. the
  upstream ARS methodology specifically) instead of one citation that
  named "ARS" but credited only the local maintainer. Added an explicit
  terminology note distinguishing "research-lab-skills" (whole repo) from
  "ARS" (upstream component only) at the top of the document. The
  "Prohibited uses" section, which restricts commercial use, now states
  plainly that both parts of the repo share the same CC BY-NC 4.0 license
  and that the maintainer can only grant commercial permission for content
  they own (the lab/infrastructure work) — not for the upstream ARS
  content, which requires permission from Cheng-I Wu directly. `LICENSE`
  was not modified.
- **GitHub repository topics no longer imply Codex/Copilot support.**
  Removed `codex` and `github-copilot` from the repo's topics (verified via
  `gh api .../topics` before and after). `claude-code` remains, accurately
  reflecting the actually-supported reference platform.

**Prior pass (see git history for detail):** operational URL/identity
canonicalization, dead Codex sibling-repo link removal, `NOTICE.md`
path-level attribution rewrite, `THIRD_PARTY_NOTICES.md` creation,
attribution for `resource-resolver`/`agent-state`/`research-project-init`,
and `README.md`/`README.zh-TW.md` positioning rewrite.
