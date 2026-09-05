# ARS Shared Resources

Cross-skill resources that no single skill owns. Everything here is referenced by
path from `skills/*/`, `scripts/*`, and `.github/workflows/*`, so **moving a file
in this tree is a breaking change** — grep the repo before you do it.

## Layout

| Directory | Holds | Rule |
|-----------|-------|------|
| `schemas/` | Standalone JSON Schema definitions (`*.schema.json`) not scoped to one producer domain | A schema validated by a `scripts/check_*.py` and referenced from more than one skill |
| `contracts/` | Domain-scoped contract artifacts: `audit/`, `evaluator/`, `passport/`, `reviewer/`, `writer/` | Grouped by the agent family that produces or consumes them. See `contracts/README.md` |
| `patterns/` | ARS-authored design patterns (`*_pattern.md`) | Narrative hub docs explaining *why* a mechanism exists |
| `protocols/` | ARS-authored operating protocols (`*_protocol.md` and equivalents) | Normative "how agents must behave" specs |
| `external/` | Vendored upstream snapshots | Anything with `upstream_source` / `snapshot_date` / `license` frontmatter |
| `references/` | Lookup material: glossaries, phrase lists, conventions, taxonomies | Data an agent consults, not behaviour it follows |
| `agents/` | Agent definitions shared across skills | |
| `templates/` | Fill-in templates emitted by tooling | |
| `policy_data/` | Publisher / venue policy source data | |

Two files stay at the top level on purpose:

- `README.md` — this file.
- `handoff_schemas.md` — the cross-skill data contract every pipeline stage reads.
  It is the entry point to this tree, so it does not live under a category.

## Precedence when a file could fit two categories

1. **`external/` wins over everything.** A vendored snapshot goes in `external/`
   even when its filename ends in `_protocol.md` (e.g. `external/prisma_trAIce_protocol.md`)
   and even when its content is normative. The distinguishing property is that ARS
   does not own the text and must re-sync it — `.github/workflows/freshness-check.yml`
   watches this directory.
2. **`protocols/` over `patterns/`** when the doc tells an agent what it MUST do.
   `patterns/` is for explanatory hub docs.
3. **`references/` over `protocols/`** when the file is a lookup table or vocabulary
   rather than a behavioural rule.

## Known inconsistency (follow-up)

`contracts/passport/` and `contracts/audit/` hold `*.schema.json` files that by the
rule above would sit in `schemas/`. They stay in `contracts/` because they are
domain-scoped and heavily referenced; splitting them is a separate change. The
working rule is: **a schema scoped to one agent family lives under
`contracts/<family>/`; a schema shared across families lives in `schemas/`.**

Also pre-existing, not introduced by the reorganization: several relative links in
`handoff_schemas.md` and `agents/compliance_agent.md` point at `../academic-pipeline/`
and `../academic-paper/` rather than `../skills/...`, and resolve nowhere.
