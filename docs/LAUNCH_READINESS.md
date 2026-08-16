# Launch Readiness

Provenance, attribution, licensing, identity, and compatibility audit ahead of
public posting (Reddit / Hacker News / GitHub). Method: `git log`/`git blame`
history, a direct fetch of the upstream `Imbad0202/academic-research-skills`
LICENSE, and `gh api` checks against GitHub for repo/account/release/tag
state. Full per-path attribution is in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Blocking

- **Version claims have no corresponding release.** `package.json` (`1.0.0`)
  matches the npm registry's published `dist-tags.latest` (`1.0.0`), but
  `CHANGELOG.md`'s latest dated entry, `.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, and all four README version badges all
  say `1.1.0`. There is no `v1.1.0` tag or release on GitHub. The only
  GitHub release that exists, `v1.0.0`, is marked `draft: true` — it is not
  actually visible to the public despite the repo being public. Net effect:
  a visitor who clicks the README's version badge or npm badge gets a
  404/mismatch, and `npm install -g research-lab-skills` installs a version
  that predates most of what the README currently describes. This needs a
  real decision (cut and publish `v1.1.0`, or roll every "1.1.0" reference
  back to "1.0.0") before a public launch post links to any of these badges.
  Not fixed in this pass per instruction — versioning is out of scope here.

## Important

- **`research-project-init` is not wired into the plugin manifests.**
  `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` list
  skills for the `lab-tools` and `academic-research-skills` plugin bundles,
  but neither list includes `skills/research-project-init` (added
  2026-08-06). Anyone installing via `/plugin install` (Method 0 in
  `docs/SETUP.md`) will not get this skill even though it exists in the
  repo and is documented in `CHANGELOG.md`.
- **`README.zh-CN.md` and `README.ja-JP.md` still carry the old
  positioning language.** Their operational URLs (install commands, badges,
  author links) were corrected in this pass, but the "what this is for" /
  "sources" prose was only rewritten in `README.md` and `README.zh-TW.md`
  per the explicit scope of this task. The Simplified Chinese and Japanese
  READMEs still read as if the whole suite, including ARS, was built by one
  author. `CONTRIBUTING.md` already asks contributors to "keep READMEs in
  sync" — this pass leaves that sync incomplete for two of the four locales.
- **`LICENSE` line 11's historical source URL is unverifiable.**
  `Source: https://github.com/starpig1129/claude-research-skills` — a third,
  distinct repository name (neither `research-lab-skills` nor any Codex
  variant). GitHub's rename-redirect behavior is consistent with this name
  having existed under the `starpig1129` account at some point, but does not
  prove it. Left untouched per instruction (no rewriting of unverifiable
  historical claims, and LICENSE is not to be edited absent a concrete
  correctness issue). If this can be confirmed or denied from the
  maintainer's own records, it's worth a one-line fix later.
- **No test evidence for Cursor/Windsurf/Copilot compatibility.** The `crs`
  npm CLI does have real `--ai cursor|windsurf|copilot` logic (confirmed in
  `bin/crs.js`) that copies skill files into each tool's directory, but
  there is no CI job, example output, or changelog entry showing any of
  these tools actually running a skill successfully. The compatibility text
  in `README.md`/`README.zh-TW.md` now says this explicitly rather than
  implying parity with Claude Code, but the underlying gap (zero verification)
  remains — worth an actual smoke test before advertising these flags
  further.
- **Local `git remote origin` still points at the old owner**
  (`git@github.com:starpig1129/research-lab-skills.git`). GitHub's redirect
  currently makes push/pull continue to work, but this is local dev
  configuration, not a repo file, and wasn't changed in this pass — the
  maintainer should update it directly rather than rely on the redirect
  indefinitely.
- **`LICENSE`'s attribution scope is coarser than `NOTICE.md`'s.**
  `LICENSE` still lists `scripts/`, `evals/`, `examples/`, and ARS `docs/`
  wholesale under Cheng-I Wu's copyright block, which is no longer precisely
  accurate now that `NOTICE.md`/`THIRD_PARTY_NOTICES.md` document the local
  additions inside those directories (e.g. `scripts/generate_slides.py`,
  `examples/research-log/`, `docs/superpowers/`). Both scopes carry the same
  CC BY-NC 4.0 license, so this doesn't change what governs the code — but
  it means `LICENSE` and `NOTICE.md` now disagree on precision. Intentionally
  left as-is per instruction (prefer not to touch `LICENSE`); the precise
  version lives in `NOTICE.md`/`THIRD_PARTY_NOTICES.md`.

## Nice-to-have

- Once a real `v1.1.0` (or whatever version) is cut, update the citation
  string in `POSITIONING.md` (currently `"(Version 1.0.0)"`), which was left
  untouched since it matches the current `package.json` and no version
  change was made in this pass.
- `scripts/check_version_consistency.py` exists in the ARS script set but
  its scope wasn't checked against README-badge-vs-`package.json` drift
  specifically — worth confirming whether it would have caught the mismatch
  above, or extending it to.
- Showcase/demo discoverability is already reasonable: `examples/showcase/`
  (ARS pipeline artifacts), `examples/report-slides/`, and
  `examples/research-log/` are all linked from `README.md`. No action taken.

## Resolved (this pass)

- All **operational/current** `starpig1129` → `zi-yue-1129` references
  corrected: install commands and badges in `README.md`,
  `README.zh-CN.md`, `README.ja-JP.md`, `README.zh-TW.md`, `QUICKSTART.md`;
  `install.sh`, `install.ps1`; `docs/SETUP.md`, `docs/SETUP.zh-TW.md`;
  `SECURITY.md`, `CONTRIBUTING.md` (fork target + maintainer link);
  `.github/pull_request_template.md`; `POSITIONING.md` (citation URL);
  `package.json` (`homepage`, `bugs.url`, `repository.url`); and
  `.claude-plugin/marketplace.json` (`owner.name`).
  **Not** rewritten: `LICENSE` (historical author/source lines, left as
  originally recorded) and the historical framing inside
  `THIRD_PARTY_NOTICES.md` itself, per instruction to preserve historical
  provenance rather than erase the rename.
- Confirmed `starpig1129` → `zi-yue-1129` is the same person renaming their
  GitHub account (matching commit email `james911129@gmail.com` and GitHub
  numeric user ID `102524453` on both sides; the `starpig1129` account no
  longer resolves) — not an ownership transfer, no provenance concern.
- Verified the upstream `Imbad0202/academic-research-skills` `LICENSE` file
  directly: it does declare CC BY-NC 4.0 with Cheng-I Wu as copyright
  holder, matching this repo's existing claim — the prior attribution was
  not fabricated.
- Removed the dead `research-lab-skills-codex` link from `docs/SETUP.md`
  and `docs/SETUP.zh-TW.md`, replacing it with an accurate statement that no
  Codex plugin distribution exists and that Codex compatibility via manual
  file copy is unverified.
- `README.md`/`README.zh-TW.md` Cursor/Windsurf/Copilot install-flag
  documentation now distinguishes "copies skill files into the tool's
  directory" (verified, real installer behavior) from "the tool actually
  interprets Claude Code's `SKILL.md` format the same way" (unverified) —
  no more implied parity with Claude Code.
- `NOTICE.md` rewritten to stop blanket-attributing all of `scripts/`,
  `examples/`, `evals/`, and `docs/` to upstream ARS; it now points to the
  new `THIRD_PARTY_NOTICES.md` for the precise per-path split (which
  directories are pure upstream, which are pure local, and which are mixed).
- `skills/resource-resolver/`, `skills/agent-state/`, and
  `skills/research-project-init/` — built 2026-08-04 through 2026-08-06,
  entirely after both source projects were already merged — are now
  attributed in `NOTICE.md`, `THIRD_PARTY_NOTICES.md`, and `README.md`.
  Previously they had no attribution anywhere.
- `README.md` and `README.zh-TW.md` top-of-file positioning rewritten:
  upstream ARS attribution is now stated in the first section, before any
  feature description, rather than only appearing in a "Sources" section at
  the bottom of the file.
