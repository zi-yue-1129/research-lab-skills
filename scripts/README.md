# scripts

Repo-wide tooling: the spec linters CI runs, the claim-audit and provenance
pipeline, the literature API clients, and the one-shot corpus migrations.

## Layout

| Directory | Holds |
|-----------|-------|
| `checks/` | `check_*.py` — the spec and consistency linters, the largest family by far |
| `audit/` | the claim-audit, citation-provenance, verification and passport pipeline |
| `clients/` | the literature API clients (arXiv, Crossref, OpenAlex, Semantic Scholar) |
| `evals/` | the eval harness and its threshold gate |
| `migrations/` | `migrate_*.py` — one-shot corpus migrations, historical after they run |
| `tooling/` | everything else: CLI entry points, manifest runners, shared helpers |
| `adapters/` | the literature-corpus adapter package, with its own tests inside it |

A module's group is the same as its test's: `scripts/<group>/x.py` is tested by
`tests/<group>/test_x.py`. Adding a module means picking the group its test will
live in. Add a new group only when an existing one would need a qualifier to
describe it.

Non-`.py` files stay at the top level. `ars_phase_scope_manifest.json`,
`corpus_consumer_manifest.json`, the two `v3_6_*_inversion_manifest.json` files
and `_ci_pytest_manifest.toml` are spec data read by more than one consumer and
referenced by path from workflows and tests; they are not owned by any one
group.

## Importing across groups

Anything importing one of these modules — another module here, a test, a
workflow step — uses the package form:

```python
from scripts.checks import check_pipeline_integrity
from scripts.audit._claim_audit_constants import RE_CLAIM_ID
```

This resolves against the **repo root**, which is not on `sys.path` when a file
is run directly as `python3 scripts/<group>/x.py` — only when run as
`python3 -m`. Both invocation styles are in use, so every module that imports
across groups puts the root on the path itself:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
```

`parents[2]` is the repo root from `scripts/<group>/x.py`. Anything computing a
path from `__file__` — a schema location, a fixture root, a sibling module —
must count from that depth. Getting it wrong does not raise at import time; it
silently resolves to `scripts/` and the tool reads the wrong tree.

Before the regrouping a bare `import _skill_lint` worked, because running a file
in `scripts/` put that directory on `sys.path`. It no longer does. A bare import
of a module in this tree is a bug even if a whole-suite run happens to pass on
some earlier test's `sys.path` insert.

## Two ways these are invoked

1. Directly, by path — `.github/workflows/spec-consistency.yml` and agent
   `SKILL.md` instructions both do this.
2. As a module — `python3 -m scripts.evals.run_evals`, and the ~25
   `python3 -m unittest tests.<group>.test_*` steps in `spec-consistency.yml`.

`conftest.py` is **not** loaded under `unittest`, so path setup has to live in
the module, never in a fixture or conftest hook.

## Dated documents name the old paths

`docs/design/`, `docs/superpowers/plans/`, `docs/superpowers/specs/` and
`docs/migration/` are records of what was decided on their date, and were left
untouched by the regrouping — as they were by the earlier `skills/` path
migration. A `scripts/<name>.py` in one of those is the path as it stood then.
Living documentation (`docs/ARCHITECTURE.md`, `docs/SETUP*.md`, the READMEs,
skill and agent definitions) carries the current paths.

## Attribution note

`tooling/generate_slides.py` is licensed separately from the rest of this tree —
it predates the ARS import and is covered by §1 of `NOTICE.md`, not the upstream
`scripts/` scope. Both `NOTICE.md` and `THIRD_PARTY_NOTICES.md` carve it out by
path, so its path has to stay accurate in them. It is also **not** the slide
generator `report-slides` runs: that one is
`skills/report-slides/scripts/generate_slides.py`, a different and much larger
file that happens to share the name.
