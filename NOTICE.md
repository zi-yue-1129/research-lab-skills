# NOTICE

## Copyright and Attribution

This repository consolidates two independently-developed projects and adds
original integration/infrastructure work built after they were combined.
This is a summary; **for the precise, path-by-path breakdown (including the
directories that are split between upstream and local content), see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).**

### 1. Lab Skills and integration infrastructure (CC BY-NC 4.0)

**Scope:**
- `skills/research-log/`, `skills/report-slides/`, `skills/research-mode/`
- `skills/resource-resolver/`, `skills/agent-state/`, `skills/research-project-init/`
  (built 2026-08-04 through 2026-08-06, after both toolsets below were
  already merged — original bridging infrastructure, not part of either
  source project)
- `scripts/generate_slides.py` (predates the ARS import; do not confuse with
  the rest of `scripts/`, which is upstream — see §2)
- `examples/research-log/`, `examples/report-slides/`
- `evals/report-slides-pptx-visual-review/`, `evals/report-slides-visual-authoring/`
- `docs/superpowers/`, `docs/research_log/`, `docs/ROADMAP-v3.11.md`
- `bin/`, `bridge/`, `.claude-plugin/`, `install.sh`, `install.ps1`, `package.json`
- Root docs (`CHANGELOG.md`, `CONTRIBUTING.md`, `POSITIONING.md`,
  `QUICKSTART.md`, `SECURITY.md`, `MODE_REGISTRY.md`) and `README*.md`

Copyright (c) 2026 ZI-YUE, CHAO (formerly published under the GitHub
identity `starpig1129`; current identity `zi-yue-1129` — same person,
confirmed by matching commit author email and GitHub numeric user ID).
Currently published at: https://github.com/zi-yue-1129/research-lab-skills

Licensed under Creative Commons Attribution-NonCommercial 4.0 International
(CC BY-NC 4.0). See [LICENSE](LICENSE) for terms.

### 2. Academic Research Skills — ARS (CC BY-NC 4.0)

**Scope:** `skills/deep-research/`, `skills/academic-paper/`,
`skills/academic-paper-reviewer/`, `skills/academic-pipeline/`, `agents/`,
`commands/`, `hooks/`, `shared/`, `tests/`, `.github/workflows/`, and the
upstream-originated portions of `scripts/`, `evals/`, `examples/`, and
`docs/` — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for exactly
which paths within those four mixed directories this covers (they also
contain material added in this repository after the import, which is
**not** in scope here).

Copyright (c) 2026 Cheng-I Wu (Imbad0202)
Originally published at: https://github.com/Imbad0202/academic-research-skills

Imported into this repository as a wholesale file copy on 2026-06-10; no
upstream git history is preserved in this repository's commit log.

Licensed under Creative Commons Attribution-NonCommercial 4.0 International
(CC BY-NC 4.0). See [LICENSE](LICENSE) for terms.

**Personal Project Statement (Cheng-I Wu):**
- Developed in personal time using personal equipment
- Uses personal AI subscriptions (self-paid)
- Does not contain confidential information from any employer
- Views and code are the author's own, not the employer's

---

## License

See [LICENSE](LICENSE) for the full text of both licenses. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for per-path attribution
detail and a record of known open questions (e.g. one historical source URL
in `LICENSE` that could not be independently verified).
