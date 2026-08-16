# Positioning

## What this is

research-lab-skills is **stateful research workflow infrastructure**, source-available for noncommercial scholarly use: it keeps experiments, decisions, and evidence connected across AI sessions instead of resetting every time, from daily experiment logs and progress slides to full academic paper pipelines. It is built as [Agent Skills](https://agentskills.io/specification); Claude Code is currently the verified reference client (see [README.md § Platform status](README.md#platform-status)). Community ports to other agent platforms are accepted; see [CONTRIBUTING.md § Platform ports](CONTRIBUTING.md#platform-ports-community-maintained-only).

It is licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). This is not an open source license — it restricts commercial use by design, to keep the tool free for academic communities.

**Terminology used throughout this document:** "research-lab-skills" refers to this whole repository. "ARS" (Academic Research Skills — `deep-research`, `academic-paper`, `academic-paper-reviewer`, `academic-pipeline`) refers specifically to the upstream research/writing/review framework originally developed by Cheng-I Wu ([`Imbad0202/academic-research-skills`](https://github.com/Imbad0202/academic-research-skills)) and imported into this repository largely as-is. It is not this repository's own work — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the full attribution. Where a statement below is scoped to ARS specifically, it says "ARS"; where it applies to the whole repository (including the `research-log`/`report-slides`/`research-mode` lab workflow and integration infrastructure built in this repo), it says "research-lab-skills."

## What this is not

ARS is not an autonomous paper-writing system. It is not a replacement for the researcher. It does not claim authorship, and its outputs are not submission-ready without human review.

## Allowed uses

- Research assistance: literature search, source verification, citation checking
- Teaching: demonstrating research methodology, peer review processes, academic writing standards
- Method training: using Socratic modes to develop research question formulation and argumentation skills
- Noncommercial academic collaboration: research groups, labs, departments using the tool for shared workflows

## Discouraged uses

- Submitting AI-generated papers as solely human-authored without disclosing AI assistance
- Using the tool to produce papers without engaging with the content (the pipeline has mandatory checkpoints specifically to prevent this)
- Treating AI-generated review feedback as a substitute for actual peer review

## Prohibited uses (per license)

Both parts of this repository — the original lab workflow/infrastructure and the upstream ARS content — are licensed CC BY-NC 4.0 (see [NOTICE.md](NOTICE.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)), so these restrictions apply to research-lab-skills as a whole, not only to ARS:

- Commercial SaaS or hosted services built on research-lab-skills (including its ARS component)
- Consulting or freelance services that package research-lab-skills as a paid product
- Enterprise or institutional paid deployments without separate licensing
- Commercial API wrappers or resale of research-lab-skills' functionality

These reflect our policy intent. See the [CC BY-NC 4.0 license](https://creativecommons.org/licenses/by-nc/4.0/) for the precise legal terms.

**On commercial licensing inquiries:** this repository's maintainer (ZI-YUE, CHAO) can only grant commercial permission for the content they own the copyright to — the original lab workflow/infrastructure listed in [NOTICE.md](NOTICE.md) §1 (`research-log`, `report-slides`, `research-mode`, `resource-resolver`, `agent-state`, `research-project-init`, and the packaging/integration layer). The maintainer does **not** hold copyright over the upstream ARS content (`deep-research`, `academic-paper`, `academic-paper-reviewer`, `academic-pipeline`, and their supporting `agents/`/`shared/`/`commands/`/`hooks/`) and cannot grant commercial rights to it. Commercial use of the ARS component requires separate permission from its original rights holder, Cheng-I Wu ([`Imbad0202/academic-research-skills`](https://github.com/Imbad0202/academic-research-skills)).

## Design philosophy (Academic Research Skills / ARS)

The design principles below describe ARS specifically — the upstream research/writing/review framework — not this repository's own infrastructure work.

**Assistive, not deceptive.** ARS helps you write better, not hide that you used AI.

- Style Calibration learns your voice from past papers — so the output sounds like you, not like a machine
- Writing Quality Check catches AI-typical patterns — to improve prose quality, not evade detection
- Disclosure Mode generates venue-specific or policy-anchor AI usage statements — because transparency is the standard

**Human-in-the-loop, always.** The pipeline's checkpoint system is mandatory by design:

- FULL checkpoints present all deliverables and require explicit user confirmation
- MANDATORY checkpoints at integrity gates and review decisions cannot be skipped
- "Full mode" means full-pipeline execution, not full autonomy — the human decides at every gate
- Max 2 revision loops, after which remaining issues become "Acknowledged Limitations" rather than being silently resolved

**Failure modes are made visible, not hidden.** The 7-mode AI Research Failure Mode Checklist (v3.2) and Reviewer Calibration Mode exist so that users can see where the AI might be wrong — not so that the AI can claim it's always right. The v3.7.3 + v3.8 L3 claim-faithfulness gate adds per-citation locator anchors and an opt-in audit pass that verifies whether each cited source actually supports the claim made of it.

**Boundaries are recorded, not improvised.** When adopting a capability from a published system would touch a load-bearing boundary — who ranks, what propagates, who writes state — the decision of whether and how to adopt it is written down as a design-lesson doc, so the same boundary is applied consistently later. The Co-Scientist (Gottweis et al. 2026) analysis is recorded in four such docs: hidden-ranking vs. advisory ranking ([L1](docs/design/2026-06-02-co-scientist-220-l1-hidden-ranking.md)), unapproved feedback propagation ([L2](docs/design/2026-06-02-co-scientist-221-l2-feedback-propagation.md)), which mechanisms transfer to ARS and which do not ([L3](docs/design/2026-06-02-co-scientist-222-l3-transfer-matrix.md)), and control-plane ownership — who may write, rank, or route ([L4](docs/design/2026-06-02-co-scientist-223-l4-control-plane-ownership.md)).

## Citing this tool

If you use research-lab-skills as a whole (the integrated environment: lab workflow, session-mode routing, and the ARS integration), please cite:

```
CHAO, Z.-Y. (2026). research-lab-skills (Version 1.1.0) [Computer software]. https://github.com/zi-yue-1129/research-lab-skills
```

If you specifically want to credit the upstream Academic Research Skills methodology (`deep-research`/`academic-paper`/`academic-paper-reviewer`/`academic-pipeline`), cite the upstream project directly:

```
Wu, C.-I. (2026). academic-research-skills [Computer software]. https://github.com/Imbad0202/academic-research-skills
```
