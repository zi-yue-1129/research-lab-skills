# Tests

Tests for the repo-wide tooling in `scripts/`, plus the fixture corpora the
pipeline lints run against.

## Layout

| Directory | Covers |
|-----------|--------|
| `checks/` | `scripts/check_*.py` — the spec and consistency linters |
| `audit/` | the claim-audit, citation-provenance, verification and passport pipeline |
| `clients/` | the literature API clients (arXiv, Crossref, OpenAlex, Semantic Scholar) |
| `evals/` | the eval harness, lift reporting and pattern-eval runtime |
| `migrations/` | `scripts/migrate_*.py` corpus migrations |
| `tooling/` | everything else: CLI entry points, manifest runners, shared helpers |
| `fixtures/` | fixture corpora — see the caveat below |

A test for `scripts/<name>.py` is named `test_<name>.py` and lives in the
directory matching the list above. Add a new group only when an existing one
would need a qualifier to describe it.

## Where tests live in this repo

Two conventions coexist, deliberately:

- **Self-contained packages keep their tests inside them** — `scripts/adapters/tests/`,
  `skills/*/scripts/tests/`, `bridge/scripts/tests/`. These ship as units, and a
  reader of the package should find its tests without leaving the directory.
- **Repo-wide tooling in `scripts/` is tested from here.** That code is a flat
  set of linters and CLIs with no package boundary, and its tests already shared
  this directory's fixture corpora.

CI runs `pytest scripts/ tests/ skills/`, which picks up both.

## Two ways these tests are invoked

1. `pytest` — the normal path, and what `.github/workflows/pytest.yml` runs.
2. `python3 -m unittest tests.<group>.test_<name>` — used by ~25 steps in
   `.github/workflows/spec-consistency.yml`.

The second matters when editing a test: **`conftest.py` is not loaded under
`unittest`**. A test that imports from `scripts/` must arrange its own path
setup in the module, rather than relying on a fixture or a conftest hook. The
established form is:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.checks import check_pipeline_integrity
```

`parents[2]` is the repo root from `tests/<group>/test_x.py`. Anything computing
a path from `__file__` must count from that depth.

The import names the group, because `scripts/` holds only group directories —
`scripts/<group>/x.py` is tested by `tests/<group>/test_x.py`, so the group in
the import is the directory this test is already in. A bare `import x` is a bug
even when a whole-suite run passes on some earlier test's `sys.path` insert; the
per-file runs in `scripts/_ci_pytest_manifest.toml` do not get that.

A subset of these files is additionally pinned by
`scripts/_ci_pytest_manifest.toml`, the single source of truth for the
file-by-file pytest invocations in `spec-consistency.yml`. Adding a direct
`pytest tests/<group>/test_x.py` step to that workflow instead of a manifest
entry is rejected by `scripts/checks/check_ci_pytest_manifest.py`.

## `fixtures/` is not test-only

Despite living here, several fixture corpora are read by **production** linters,
not just by tests — `scripts/checks/check_pattern_eval_manifest.py` and
`scripts/checks/check_v3_6_6_ab_manifest.py` both validate trees under
`fixtures/`. Treat these as spec corpora with a test-adjacent home, and check
for non-test consumers before moving or pruning one.
