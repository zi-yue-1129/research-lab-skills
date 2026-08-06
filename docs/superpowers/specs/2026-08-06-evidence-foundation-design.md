# Literature and Evidence Foundation — Design

## Problem

`deep-research`'s `bibliography_agent` and `source_verification_agent`
currently produce an Annotated Bibliography and a Synthesis Report as
Markdown documents only. Those reports are a *view*: nothing about a
source or a finding is persisted as structured, queryable data.

`agent-state`'s `record_claim()` already carries an `evidence_ref` field,
but it is an opaque free-text string (a path, a quote, or a URL). There is
no Source registry, no deduplication (the same paper can be logged
repeatedly across research runs or projects), and no way to tag a finding
as supporting, refuting, or qualifying a claim with structured
limitations/uncertainty. Literature reports are the only artifact that
exists; there is no durable Evidence layer underneath them.

## Goal

Add two new entities to `agent-state` — **Source** and **Evidence** — with
the same first-class treatment as the existing Project/Question/
Hypothesis/Experiment/Run entities (YAML store, CLI actions, SQLite query
index), auto-registered by `deep-research`'s existing agents as they do
their normal work:

- Every unique source is registered once and reused across runs and
  projects, deduplicated by DOI, then normalized URL, then flagged (not
  merged) on a title+first-author+year match.
- Every extracted finding becomes a structured, tagged Evidence Statement
  (stance: supports/refutes/mixed, optional limitations, optional
  uncertainty note) linked to a Source and a Question (required) /
  Hypothesis (optional).
- `record_claim()` gains an `evidence_id` parameter so a Claim can point
  at a specific structured Evidence Statement instead of only a free-text
  reference.
- The Annotated Bibliography and Synthesis Report continue to be
  generated exactly as before; they become a rendered view over this
  structured data rather than the only record of it.

## Non-goals

- No new skill and no new interactive dialogue. This is a data-layer
  addition inside `agent-state`, driven automatically by `deep-research`'s
  existing agents — no user-facing workflow changes.
- No separate SearchStrategy entity. Search strategy and protocol stay
  documents (`deep-research`'s existing PRISMA templates); this design
  only covers Source and Evidence.
- No fixed-taxonomy validation of `evidence_tier` inside `agent-state`. It
  is a free-text field; grading logic (meta-analysis > RCT > cohort > case
  report > expert opinion) stays owned by `deep-research`'s
  `source_quality_hierarchy.md`.
- No retroactive migration of existing Claims' free-text `evidence_ref`
  values into structured Evidence records.
- No change to `deep-research`'s report content or format — registering
  Source/Evidence is an additional side effect alongside report
  generation, not a replacement for it.

## Data Model

### Source (`.research/state/sources.yaml`)

```
{
  "id": "src_xxxxxxxx",
  "title": str,
  "authors": Optional[str],        # free text, e.g. "Smith J, Lee K"
  "year": Optional[int],
  "doi": Optional[str],
  "url": Optional[str],
  "venue": Optional[str],          # journal / conference / publisher
  "evidence_tier": Optional[str],  # free text, e.g. "RCT", "meta-analysis"
  "screening_status": str,         # "included" | "excluded" | "pending"
  "exclusion_reason": Optional[str],
  "project_id": str,
  "created_at": iso8601,
  "created_by": str,
}
```

### Evidence (`.research/state/evidence.yaml`)

```
{
  "id": "evd_xxxxxxxx",
  "source_id": str,                # FK -> Source
  "question_id": str,              # FK -> Question, required
  "hypothesis_id": Optional[str],  # FK -> Hypothesis
  "statement": str,                # the extracted finding from the source
  "stance": str,                   # "supports" | "refutes" | "mixed"
  "limitations": Optional[str],
  "uncertainty_note": Optional[str],
  "created_at": iso8601,
  "created_by": str,
}
```

## Components

### `state_store.py`

- **`create_source(project_root, title, *, authors=None, year=None,
  doi=None, url=None, venue=None, evidence_tier=None, project_id=None,
  created_by="user") -> Dict`**

  Dedup order:
  1. Exact `doi` match against existing sources → return the existing
     record unchanged. Idempotent, not an error.
  2. Else exact normalized-URL match (strip query/fragment, lowercase
     scheme+host) → return the existing record unchanged.
  3. Else, before creating the new record, check for a normalized
     title + first-author-token + year exact match against existing
     sources. If found, still create the new Source (this is a hint, not
     a merge), and attach `"duplicate_hint": {"source_id": <id>, "reason":
     "title+author+year match"}` to the returned record so the caller
     (`deep-research`) can decide whether to treat it as the same source.
     No match → `"duplicate_hint": None`.

  Raises `ValueError` if `title` is empty/missing.
  Raises `ProjectNotFoundError` if `project_id` is given but unknown
  (same default-project behavior as `create_question`: omitted
  `project_id` lazily creates/uses `proj_default`).

- **`set_source_screening(project_root, source_id, screening_status,
  exclusion_reason=None) -> Dict`**

  `screening_status` must be one of `"included"`, `"excluded"`,
  `"pending"`. Raises `SourceNotFoundError` if `source_id` is unknown,
  `ValueError` for an invalid status.

- **`create_evidence(project_root, source_id, question_id, statement,
  stance, *, hypothesis_id=None, limitations=None, uncertainty_note=None,
  created_by="user") -> Dict`**

  Raises `ValueError` if `statement` is empty/missing or `stance` is not
  one of `"supports"`, `"refutes"`, `"mixed"`. Raises `SourceNotFoundError`
  / `QuestionNotFoundError` / `HypothesisNotFoundError` for unknown FKs.

- **`record_claim(...)`** gains `evidence_id: Optional[str] = None`.
  When given, must reference an existing Evidence record
  (`EvidenceNotFoundError` otherwise). Existing `evidence_ref` behavior is
  unchanged — both fields can be set independently.

- New exceptions: `SourceNotFoundError(ValueError)`,
  `EvidenceNotFoundError(ValueError)`.

- **`validate_referential_integrity`** extended to check the four new
  YAML-to-YAML foreign keys: `sources.project_id -> projects`,
  `evidence.source_id -> sources`, `evidence.question_id -> questions`,
  `evidence.hypothesis_id -> hypotheses`. It does **not** check
  `claims.evidence_id -> evidence`: Claims live in the append-only
  `events/*.jsonl` shards, not in `state/*.yaml`, and this pass is a scan
  of the YAML state files only. `record_claim` already rejects an unknown
  `evidence_id` at write time.

### `state.py` CLI

New mutually-exclusive actions: `--create-source`,
`--set-source-screening`, `--set-source-evidence-tier`,
`--create-evidence`.

New flags: `--title`, `--authors`, `--year`, `--doi`, `--url`, `--venue`,
`--evidence-tier`, `--source-id`, `--screening-status`,
`--exclusion-reason`, `--stance`, `--limitations`, `--uncertainty-note`.

`--record-claim` gains `--evidence-id`.

### `state_index.py`

New tables `sources` and `evidence`, mirroring the existing
projects/questions/hypotheses/experiments/runs tables (same
`_sync_state_tables`-driven full replace-on-rebuild pattern; Evidence's
`created_at`-ordered listing follows the same convention as
Hypothesis/Experiment). Indexes on `sources.project_id`,
`evidence.source_id`, `evidence.question_id`, `evidence.hypothesis_id`.

`query()` gains a `source_id` filter, mutually exclusive with the
existing filters, returning the Source plus its linked Evidence records
(ordered by `created_at`). The existing `question_id` filter's response
gains an additional `"evidence"` key (Evidence records linked to that
Question), alongside its current `"hypotheses"` and `"runs"` keys — same
shape convention as the existing `hypothesis_id` → `experiments` walk.

### `deep-research` integration

The new CLI actions are inert until something calls them — this is the
integration surface that actually makes registration automatic:

- `skills/deep-research/agents/bibliography_agent.md`: add instructions to
  call `--create-source` for each source as it is added to the corpus,
  and `--set-source-screening` for each screening decision (include/
  exclude + reason), using the `$STATE` discovery convention already
  established in `skills/research-project-init/SKILL.md` and
  `skills/agent-state/SKILL.md`.
- `skills/deep-research/agents/source_verification_agent.md`: add
  instructions to call `--set-source-evidence-tier` for each source once
  its evidence-hierarchy grade is assigned.
- `skills/deep-research/agents/synthesis_agent.md`: add instructions to
  call `--create-evidence` for each synthesized key finding, linking it
  to the current run's `question_id`.
- `skills/agent-state/SKILL.md`: document the four new actions (with
  bash examples) in its "Research chain" section, the same way
  `--create-question` was documented there.

## Data Flow

1. `bibliography_agent` finds and screens a source → calls
   `--create-source` (dedup-checked) → gets a `source_id`; calls
   `--set-source-screening` if the source is excluded during screening.
2. `source_verification_agent` grades an included source → calls
   `--set-source-evidence-tier`. `synthesis_agent` extracts a key finding
   from an included source → calls `--create-evidence` with the
   `source_id`, the current research run's `question_id`, the finding as
   `statement`, and a `stance` (plus optional `hypothesis_id`/
   `limitations`/`uncertainty_note`) → gets an `evidence_id`.
3. If a Run records a Claim built on that finding, `record_claim` is
   called with `evidence_id` pointing at the structured Evidence.
4. `report_compiler_agent` renders the Markdown Annotated
   Bibliography/Synthesis Report exactly as before, unaffected. Separately,
   `--query --source-id <id>` or the extended `--query --question-id <id>`
   now surface the structured Evidence directly.

## Error Handling

No silent failures, consistent with the rest of `agent-state`:

- Empty `title` / `statement` → `ValueError`.
- Unknown `source_id` / `question_id` / `hypothesis_id` / `evidence_id`
  references → the matching `*NotFoundError`.
- Invalid `screening_status` / `stance` values → `ValueError`.
- Duplicate `doi`/URL on `create_source` is **not** an error — it returns
  the existing record idempotently, since `deep-research` legitimately
  re-registers the same source across research runs.

## Testing Plan

New tests in `skills/agent-state/scripts/tests/test_state_cli.py`
covering: `create_source` dedup by exact doi, dedup by exact normalized
URL, `duplicate_hint` surfaced (not merged) on a title+author+year match,
`create_source` with an unknown `project_id`; `set_source_screening`
status transitions and invalid-status rejection; `create_evidence` FK
validation for source/question/hypothesis and empty-statement/invalid-
stance rejection; `record_claim` with a valid and an unknown
`evidence_id`; `validate_referential_integrity` catching a dangling
Source/Evidence FK; index sync and `--query --source-id` / extended
`--query --question-id` shapes.

`test_state_cli.py` is already over the ~1000-line file-size guideline
before this change (accepted pre-existing debt, noted previously in the
`research-project-init` plan). This addition grows it further; that is
accepted again here rather than addressed as part of this feature.
