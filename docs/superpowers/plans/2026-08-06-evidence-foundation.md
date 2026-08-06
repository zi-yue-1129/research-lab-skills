# Literature and Evidence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Source and Evidence as first-class `agent-state` entities (YAML store, CLI actions, SQLite query index) so `deep-research`'s existing agents can register deduplicated sources and structured, stance-tagged Evidence Statements alongside the Markdown reports they already produce.

**Architecture:** Two new YAML-backed entities (`Source`, `Evidence`) follow the exact pattern already established by Project/Question/Hypothesis/Experiment/Run in `state_store.py`, `state.py`, and `state_index.py`. `deep-research`'s `bibliography_agent`, `source_verification_agent`, and `synthesis_agent` are given instructions to call the new CLI actions as a side effect of their existing work.

**Tech Stack:** Python 3, PyYAML, SQLite (stdlib `sqlite3`), pytest (subprocess-driven CLI tests), Markdown (agent instruction files).

**Deviations from the approved design spec** (`docs/superpowers/specs/2026-08-06-evidence-foundation-design.md`), found while mapping the design onto the actual agent files during planning:

1. The spec named `source_verification_agent` as the agent calling `--create-evidence`. Reading `source_verification_agent.md` and `synthesis_agent.md` shows `source_verification_agent`'s job is grading/verifying individual sources (it already computes a Level I-VII grade per source), not extracting cross-source findings with a stance. `synthesis_agent` is explicitly "resolving conflicts in evidence" and "convergence and divergence" across sources — the actual home for a stance-tagged finding. This plan has `source_verification_agent` call a new `--set-source-evidence-tier` action (recording its existing Level I-VII grade onto the Source `bibliography_agent` already registered) and has `synthesis_agent` call `--create-evidence`.
2. The spec said `validate_referential_integrity` should check `claims.evidence_id -> evidence` "via the events shards." The existing function only ever validates the five YAML-backed entities (Project/Question/Hypothesis/Experiment/Run) — Result and Claim (both event-log entities) are not covered by it at all today, and `record_claim` already rejects an unknown `evidence_id` at write time. Extending read-time integrity checking to event shards would be new scope inconsistent with the existing design, not a gap this feature needs to close. This plan limits the extension to the four YAML-to-YAML foreign keys: `sources.project_id`, `evidence.source_id`, `evidence.question_id`, `evidence.hypothesis_id`.

## Global Constraints

- All new functions carry full type hints and Google-style docstrings, matching every existing function in `state_store.py`/`state_index.py`/`state.py` (user's global code-style standard, and the established convention in this file).
- No silent failures: empty required text fields raise `ValueError`; unknown foreign-key ids raise the matching `*NotFoundError`. `create_source`'s duplicate handling is the one deliberate exception — a doi/URL match returns the existing record instead of erroring, because `deep-research` legitimately re-registers the same source across research runs (see design spec's Error Handling section).
- All generated file content (code, docstrings, comments, agent instructions) is in English, regardless of the conversation language, matching the rest of this codebase and prior plans in this repo.
- No placeholders: every step below contains the literal code to write.
- `skills/agent-state/scripts/tests/test_state_cli.py` is already 1,554 lines, over the ~1000-line file-size guideline (pre-existing, accepted debt per the prior `research-project-init` plan). This plan adds roughly 20 more tests to it. Splitting this file is out of scope for this feature.
- Baseline test count before this plan's changes: 90 passed (verified via `cd skills/agent-state/scripts && python3 -m pytest tests/test_state_cli.py -q`). Track the running total after each task.
- `state_index.py`'s `INDEX_SCHEMA_VERSION` MUST be bumped from `2` to `3` in Task 3. This is not optional: `_connect`'s schema-version check is the only thing that forces a stale `index.db` (built before the `sources`/`evidence` tables and the `claims.evidence_id` column existed) to be wiped and rebuilt on next use. `CREATE TABLE IF NOT EXISTS` silently no-ops on an already-existing table, so without the version bump, an old `claims` table missing the `evidence_id` column would survive schema application and then fail on the first `INSERT` that supplies it — see `_connect`'s own docstring for the identical failure mode this mechanism exists to prevent.

---

### Task 1: Source entity (`state_store.py` + `state.py` CLI)

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes (existing): `_locked_file`, `_load_yaml_map`, `_save_yaml_map`, `generate_id`, `_utc_now_iso`, `load_projects`, `_ensure_default_project`, `ProjectNotFoundError` (all in `state_store.py`); `_build_parser`/`_dispatch` structure in `state.py`.
- Produces: `state_store.SOURCES_RELATIVE_PATH`, `state_store.SourceNotFoundError`, `state_store.load_sources(project_root) -> Dict[str, Any]`, `state_store.create_source(project_root, title, authors=None, year=None, doi=None, url=None, venue=None, evidence_tier=None, project_id=None, created_by="user") -> Dict[str, Any]`, `state_store.set_source_screening(project_root, source_id, screening_status, exclusion_reason=None) -> Dict[str, Any]`, `state_store.set_source_evidence_tier(project_root, source_id, evidence_tier) -> Dict[str, Any]`; CLI actions `--create-source`, `--set-source-screening`, `--set-source-evidence-tier` and flags `--title`, `--authors`, `--year`, `--doi`, `--url`, `--venue`, `--evidence-tier`, `--source-id`, `--screening-status`, `--exclusion-reason`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_create_source_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-source", "--title", "Offline-First Mobile UX Patterns",
        "--authors", "Ng T, Osei K", "--year", "2025", "--doi", "10.1000/xyz123",
        "--venue", "Journal of Mobile Computing", "--skill", "bibliography_agent", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("src_")
    assert data["title"] == "Offline-First Mobile UX Patterns"
    assert data["doi"] == "10.1000/xyz123"
    assert data["screening_status"] == "pending"
    assert data["exclusion_reason"] is None
    assert data["created_by"] == "bibliography_agent"
    assert data["duplicate_hint"] is None
    assert data["project_id"] == "proj_default"


def test_create_source_without_title_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-source", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_source_with_unknown_project_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-source", "--title", "Some Title",
        "--project-id", "proj_does_not_exist", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProjectNotFoundError"


def test_create_source_deduplicates_by_exact_doi(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    first = json.loads(_run(
        project, "--create-source", "--title", "First Title",
        "--doi", "10.1000/same-doi", "--json",
    ).stdout)

    second = json.loads(_run(
        project, "--create-source", "--title", "Different Title Entirely",
        "--doi", "10.1000/same-doi", "--json",
    ).stdout)

    assert second["id"] == first["id"]
    assert second["title"] == "First Title"
    sources_yaml = (project / ".research" / "state" / "sources.yaml").read_text()
    assert sources_yaml.count("id: src_") == 1


def test_create_source_deduplicates_by_normalized_url(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    first = json.loads(_run(
        project, "--create-source", "--title", "A Title",
        "--url", "https://example.com/paper?utm_source=x", "--json",
    ).stdout)

    second = json.loads(_run(
        project, "--create-source", "--title", "A Title",
        "--url", "http://example.com/paper/", "--json",
    ).stdout)

    assert second["id"] == first["id"]


def test_create_source_surfaces_duplicate_hint_without_merging(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    first = json.loads(_run(
        project, "--create-source", "--title", "Offline Caching Patterns",
        "--authors", "Ng T", "--year", "2025", "--json",
    ).stdout)

    second = json.loads(_run(
        project, "--create-source", "--title", "Offline Caching Patterns",
        "--authors", "Ng T", "--year", "2025", "--json",
    ).stdout)

    assert second["id"] != first["id"]
    assert second["duplicate_hint"] == {
        "source_id": first["id"], "reason": "title+author+year match",
    }
    sources_yaml = (project / ".research" / "state" / "sources.yaml").read_text()
    assert sources_yaml.count("id: src_") == 2


def test_set_source_screening_records_status_and_reason(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)

    result = _run(
        project, "--set-source-screening", "--source-id", source["id"],
        "--screening-status", "excluded", "--exclusion-reason", "Predatory journal", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["screening_status"] == "excluded"
    assert data["exclusion_reason"] == "Predatory journal"


def test_set_source_screening_invalid_status_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)

    result = _run(
        project, "--set-source-screening", "--source-id", source["id"],
        "--screening-status", "maybe", "--json",
    )

    assert result.returncode == 2  # argparse rejects the choice before dispatch


def test_set_source_screening_unknown_source_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--set-source-screening", "--source-id", "src_does_not_exist",
        "--screening-status", "included", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SourceNotFoundError"


def test_set_source_evidence_tier_updates_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)

    result = _run(
        project, "--set-source-evidence-tier", "--source-id", source["id"],
        "--evidence-tier", "Level II - Randomized Controlled Trial", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["evidence_tier"] == "Level II - Randomized Controlled Trial"


def test_set_source_evidence_tier_without_value_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)

    result = _run(
        project, "--set-source-evidence-tier", "--source-id", source["id"], "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd skills/agent-state/scripts && python3 -m pytest tests/test_state_cli.py -k "source" -v`
Expected: FAIL/ERROR on every new test (`--create-source` etc. are not recognized arguments yet).

- [ ] **Step 3: Implement `state_store.py`**

Add the new path constant next to the existing `*_RELATIVE_PATH` constants (after `RUNS_RELATIVE_PATH = Path(".research/state/runs.yaml")`, before `EVENTS_RELATIVE_DIR`):

```python
SOURCES_RELATIVE_PATH = Path(".research/state/sources.yaml")
```

Add the screening-status vocabulary next to the other `_*_STATUSES` frozensets (after `_EXPERIMENT_STATUSES = frozenset({"running", "completed", "failed"})`):

```python
_SOURCE_SCREENING_STATUSES = frozenset({"included", "excluded", "pending"})
```

Add the new exception class next to the other `*NotFoundError` classes (after `class RunNotFoundError(ValueError):` block, before `class LockTimeoutError(RuntimeError):`):

```python
class SourceNotFoundError(ValueError):
    """Raised when a source_id does not exist in state/sources.yaml."""
```

Add the following functions after `set_experiment_status` (i.e. right before `def _question_id_for_experiment`):

```python
def load_sources(project_root: Path) -> Dict[str, Any]:
    """Load all Source records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Source record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / SOURCES_RELATIVE_PATH, "sources")


def _normalize_url(url: str) -> str:
    """Normalize a URL for exact-match deduplication.

    Strips the scheme and any query string or fragment, and lowercases the
    rest, so "http vs https" or a tracking parameter doesn't create two
    Source records for the same page.

    Args:
        url: The raw URL.

    Returns:
        A normalized "host/path" string, lowercased.
    """
    without_fragment = url.split("#", 1)[0]
    without_query = without_fragment.split("?", 1)[0]
    without_scheme = without_query.split("://", 1)[-1]
    return without_scheme.lower().rstrip("/")


def _title_author_year_key(
    title: str, authors: Optional[str], year: Optional[int]
) -> str:
    """Build an exact-match hint key from title, first author, and year.

    This is a deliberately exact (not fuzzy) comparison: it strips
    non-alphanumeric characters and lowercases, so trivial punctuation or
    casing differences still match, but it never scores similarity. A hit
    only ever attaches a "duplicate_hint" to a newly created record -- it
    never merges records or blocks creation.

    Args:
        title: The source title.
        authors: Free-text authors string, e.g. "Smith J, Lee K".
        year: Publication year.

    Returns:
        A normalized "title|first_author|year" key.
    """
    normalized_title = "".join(ch.lower() for ch in title if ch.isalnum())
    first_author = (authors or "").split(",", 1)[0]
    normalized_author = "".join(ch.lower() for ch in first_author if ch.isalnum())
    return f"{normalized_title}|{normalized_author}|{year}"


def create_source(
    project_root: Path,
    title: str,
    authors: Optional[str] = None,
    year: Optional[int] = None,
    doi: Optional[str] = None,
    url: Optional[str] = None,
    venue: Optional[str] = None,
    evidence_tier: Optional[str] = None,
    project_id: Optional[str] = None,
    created_by: str = "user",
) -> Dict[str, Any]:
    """Create a new Source record, or return an existing one on an exact
    doi/URL match.

    Args:
        project_root: The project's root directory.
        title: The source's title.
        authors: Optional free-text authors, e.g. "Smith J, Lee K".
        year: Optional publication year.
        doi: Optional DOI. Checked first for deduplication (exact match).
        url: Optional URL. Checked second for deduplication (normalized
            exact match), only when no doi match is found.
        venue: Optional journal/conference/publisher name.
        evidence_tier: Optional free-text evidence grade (e.g. "Level II -
            RCT"); not validated against a fixed taxonomy.
        project_id: Project this Source belongs to. Defaults to the
            lazily-created "proj_default" if omitted.
        created_by: Name of the skill creating this Source, or "user" for
            a direct CLI call.

    Returns:
        The full Source record (existing or new), including its generated
        "id". A newly created record also carries "duplicate_hint": either
        None, or {"source_id": <id>, "reason": "title+author+year match"}
        when no doi/URL match was found but a title+first-author+year
        match against an existing Source was. An existing record returned
        via a doi/URL match carries no "duplicate_hint" key at all.

    Raises:
        ValueError: If title is empty/missing.
        ProjectNotFoundError: If project_id is given but doesn't exist.
    """
    if not title:
        raise ValueError("title is required")
    if project_id is None:
        project_id = _ensure_default_project(project_root)
    elif project_id not in load_projects(project_root):
        raise ProjectNotFoundError(f"Unknown project_id: {project_id}")
    path = project_root / SOURCES_RELATIVE_PATH
    with _locked_file(project_root, path):
        sources = _load_yaml_map(path, "sources")
        if doi:
            for existing in sources.values():
                if existing.get("doi") == doi:
                    return existing
        normalized_url = _normalize_url(url) if url else None
        if normalized_url:
            for existing in sources.values():
                existing_url = existing.get("url")
                if existing_url and _normalize_url(existing_url) == normalized_url:
                    return existing
        hint_key = _title_author_year_key(title, authors, year)
        duplicate_hint = None
        for existing in sources.values():
            if _title_author_year_key(
                existing.get("title", ""), existing.get("authors"), existing.get("year")
            ) == hint_key:
                duplicate_hint = {
                    "source_id": existing["id"],
                    "reason": "title+author+year match",
                }
                break
        source_id = generate_id("src")
        record = {
            "id": source_id,
            "title": title,
            "authors": authors,
            "year": year,
            "doi": doi,
            "url": url,
            "venue": venue,
            "evidence_tier": evidence_tier,
            "screening_status": "pending",
            "exclusion_reason": None,
            "project_id": project_id,
            "created_at": _utc_now_iso(),
            "created_by": created_by,
        }
        sources[source_id] = record
        _save_yaml_map(path, "sources", sources)
    return {**record, "duplicate_hint": duplicate_hint}


def set_source_screening(
    project_root: Path,
    source_id: str,
    screening_status: str,
    exclusion_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a Source's screening decision.

    Args:
        project_root: The project's root directory.
        source_id: The Source to update.
        screening_status: New status, must be "included", "excluded", or
            "pending".
        exclusion_reason: Optional reason, conventionally given when
            screening_status is "excluded".

    Returns:
        The updated Source record.

    Raises:
        SourceNotFoundError: If source_id doesn't exist.
        ValueError: If screening_status isn't one of the allowed values.
    """
    if screening_status not in _SOURCE_SCREENING_STATUSES:
        raise ValueError(
            "screening_status must be 'included', 'excluded', or 'pending', "
            f"got {screening_status!r}"
        )
    path = project_root / SOURCES_RELATIVE_PATH
    with _locked_file(project_root, path):
        sources = _load_yaml_map(path, "sources")
        if source_id not in sources:
            raise SourceNotFoundError(f"Unknown source_id: {source_id}")
        sources[source_id]["screening_status"] = screening_status
        sources[source_id]["exclusion_reason"] = exclusion_reason
        _save_yaml_map(path, "sources", sources)
        return sources[source_id]


def set_source_evidence_tier(
    project_root: Path, source_id: str, evidence_tier: str
) -> Dict[str, Any]:
    """Record a Source's evidence-hierarchy grade.

    Args:
        project_root: The project's root directory.
        source_id: The Source to update.
        evidence_tier: Free-text evidence grade (e.g. "Level II - RCT").
            Not validated against a fixed taxonomy -- deep-research's
            source_verification_agent owns the grading rubric.

    Returns:
        The updated Source record.

    Raises:
        SourceNotFoundError: If source_id doesn't exist.
        ValueError: If evidence_tier is empty/missing.
    """
    if not evidence_tier:
        raise ValueError("evidence_tier is required")
    path = project_root / SOURCES_RELATIVE_PATH
    with _locked_file(project_root, path):
        sources = _load_yaml_map(path, "sources")
        if source_id not in sources:
            raise SourceNotFoundError(f"Unknown source_id: {source_id}")
        sources[source_id]["evidence_tier"] = evidence_tier
        _save_yaml_map(path, "sources", sources)
        return sources[source_id]
```

- [ ] **Step 4: Implement `state.py` CLI wiring**

In `_build_parser`, add three new actions to the mutually exclusive group, right after `action.add_argument("--set-experiment-status", action="store_true")` and before `action.add_argument("--validate", action="store_true")`:

```python
    action.add_argument("--create-source", action="store_true")
    action.add_argument("--set-source-screening", action="store_true")
    action.add_argument("--set-source-evidence-tier", action="store_true")
```

Add the new value flags right after `parser.add_argument("--experiment-id", metavar="ID")` and before `parser.add_argument("--run-id", metavar="ID")`:

```python
    parser.add_argument("--source-id", metavar="ID")
```

Add the rest of the new value flags right after `parser.add_argument("--description", metavar="TEXT")` and before `parser.add_argument("--question", metavar="TEXT")`:

```python
    parser.add_argument("--title", metavar="TEXT")
    parser.add_argument("--authors", metavar="TEXT")
    parser.add_argument("--year", type=int, metavar="YEAR")
    parser.add_argument("--doi", metavar="TEXT")
    parser.add_argument("--url", metavar="TEXT")
    parser.add_argument("--venue", metavar="TEXT")
    parser.add_argument("--evidence-tier", metavar="TEXT")
    parser.add_argument(
        "--screening-status", choices=["included", "excluded", "pending"]
    )
    parser.add_argument("--exclusion-reason", metavar="TEXT")
```

In `_dispatch`, add the three new branches right after the `if args.set_experiment_status:` block and before `if args.validate:`:

```python
    if args.create_source:
        return state_store.create_source(
            project_root, args.title,
            authors=args.authors, year=args.year, doi=args.doi, url=args.url,
            venue=args.venue, evidence_tier=args.evidence_tier,
            project_id=args.project_id, created_by=args.skill or "user",
        )
    if args.set_source_screening:
        return state_store.set_source_screening(
            project_root, args.source_id, args.screening_status,
            exclusion_reason=args.exclusion_reason,
        )
    if args.set_source_evidence_tier:
        return state_store.set_source_evidence_tier(
            project_root, args.source_id, args.evidence_tier,
        )
```

In `main`, add `state_store.SourceNotFoundError` to the caught-exception tuple, right after `state_store.RunNotFoundError,` and before `state_store.LockTimeoutError,`:

```python
        state_store.SourceNotFoundError,
```

In the module docstring's `Usage:` block, add these lines right after the `--set-experiment-status` usage line and before the `--record-result` usage line:

```
    python state.py --create-source --title "..." [--authors "..."] [--year YEAR] \
        [--doi "..."] [--url "..."] [--venue "..."] [--evidence-tier "..."] \
        [--project-id PROJ_ID] [--skill NAME] [--json]
    python state.py --set-source-screening --source-id SRC_ID \
        --screening-status included|excluded|pending [--exclusion-reason "..."] [--json]
    python state.py --set-source-evidence-tier --source-id SRC_ID \
        --evidence-tier "..." [--json]
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `cd skills/agent-state/scripts && python3 -m pytest tests/test_state_cli.py -v`
Expected: all tests pass, running total 101 (90 baseline + 11 new).

- [ ] **Step 6: Commit**

```bash
git add skills/agent-state/scripts/state_store.py skills/agent-state/scripts/state.py \
  skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add Source entity with dedup by doi/URL/title-hint"
```

---

### Task 2: Evidence entity (`state_store.py` + `state.py` CLI)

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: Task 1's `SOURCES_RELATIVE_PATH`, `load_sources`, `SourceNotFoundError`; existing `load_questions`, `load_hypotheses`, `QuestionNotFoundError`, `HypothesisNotFoundError`, `load_runs`, `RunNotFoundError`, `_append_event`.
- Produces: `state_store.EVIDENCE_RELATIVE_PATH`, `state_store.EvidenceNotFoundError`, `state_store.load_evidence(project_root) -> Dict[str, Any]`, `state_store.create_evidence(project_root, source_id, question_id, statement, stance, hypothesis_id=None, limitations=None, uncertainty_note=None, created_by="user") -> Dict[str, Any]`, `record_claim(...)` gains `evidence_id: Optional[str] = None`; CLI action `--create-evidence` and flags `--stance`, `--limitations`, `--uncertainty-note`, `--evidence-id`; `--record-claim` gains `--evidence-id`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def _make_source_and_question(project: Path) -> tuple:
    source = json.loads(_run(
        project, "--create-source", "--title", "Some Title", "--json",
    ).stdout)
    question = json.loads(_run(
        project, "--create-question", "--question", "Does X help Y?", "--json",
    ).stdout)
    return source["id"], question["id"]


def test_create_evidence_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id,
        "--statement", "Offline caching reduced reported friction by 40%",
        "--stance", "supports", "--limitations", "Single-region sample",
        "--skill", "synthesis_agent", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("evd_")
    assert data["source_id"] == source_id
    assert data["question_id"] == question_id
    assert data["hypothesis_id"] is None
    assert data["stance"] == "supports"
    assert data["limitations"] == "Single-region sample"
    assert data["uncertainty_note"] is None
    assert data["created_by"] == "synthesis_agent"


def test_create_evidence_with_hypothesis_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    hypothesis = json.loads(_run(
        project, "--create-hypothesis", "--question-id", question_id,
        "--statement", "X helps Y", "--json",
    ).stdout)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--hypothesis-id", hypothesis["id"],
        "--statement", "A finding", "--stance", "refutes", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["hypothesis_id"] == hypothesis["id"]
    assert data["stance"] == "refutes"


def test_create_evidence_without_statement_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--stance", "mixed", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_evidence_invalid_stance_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "neutral", "--json",
    )

    assert result.returncode == 2  # argparse rejects the choice before dispatch


def test_create_evidence_unknown_source_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", "src_does_not_exist",
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SourceNotFoundError"


def test_create_evidence_unknown_question_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, _ = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", "q_does_not_exist", "--statement", "A finding",
        "--stance", "supports", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "QuestionNotFoundError"


def test_create_evidence_unknown_hypothesis_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)

    result = _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--hypothesis-id", "hyp_does_not_exist",
        "--statement", "A finding", "--stance", "supports", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "HypothesisNotFoundError"


def test_record_claim_with_evidence_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    ).stdout)
    run = json.loads(_run(
        project, "--start-run", "--skill", "deep-research", "--json",
    ).stdout)

    result = _run(
        project, "--record-claim", "--run-id", run["id"],
        "--statement", "Ship offline caching for v2", "--confidence", "high",
        "--evidence-id", evidence["id"], "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["evidence_id"] == evidence["id"]


def test_record_claim_with_unknown_evidence_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    run = json.loads(_run(
        project, "--start-run", "--skill", "deep-research", "--json",
    ).stdout)

    result = _run(
        project, "--record-claim", "--run-id", run["id"],
        "--statement", "A claim", "--evidence-id", "evd_does_not_exist", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "EvidenceNotFoundError"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd skills/agent-state/scripts && python3 -m pytest tests/test_state_cli.py -k "evidence" -v`
Expected: FAIL/ERROR on every new test.

- [ ] **Step 3: Implement `state_store.py`**

Add the new path constant right after `SOURCES_RELATIVE_PATH = Path(".research/state/sources.yaml")`:

```python
EVIDENCE_RELATIVE_PATH = Path(".research/state/evidence.yaml")
```

Add the stance vocabulary right after `_SOURCE_SCREENING_STATUSES = frozenset({"included", "excluded", "pending"})`:

```python
_EVIDENCE_STANCES = frozenset({"supports", "refutes", "mixed"})
```

Add the new exception class right after `class SourceNotFoundError(ValueError):` block:

```python
class EvidenceNotFoundError(ValueError):
    """Raised when an evidence_id does not exist in state/evidence.yaml."""
```

Add the following functions right after `set_source_evidence_tier` (i.e. right before `def _question_id_for_experiment`):

```python
def load_evidence(project_root: Path) -> Dict[str, Any]:
    """Load all Evidence records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Evidence record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / EVIDENCE_RELATIVE_PATH, "evidence")


def create_evidence(
    project_root: Path,
    source_id: str,
    question_id: str,
    statement: str,
    stance: str,
    hypothesis_id: Optional[str] = None,
    limitations: Optional[str] = None,
    uncertainty_note: Optional[str] = None,
    created_by: str = "user",
) -> Dict[str, Any]:
    """Create a new Evidence Statement linking a Source to a Question.

    Args:
        project_root: The project's root directory.
        source_id: The Source this finding was extracted from; must
            already exist.
        question_id: The Research Question this Evidence bears on; must
            already exist.
        statement: The extracted finding, in the source's own terms.
        stance: Must be "supports", "refutes", or "mixed" relative to the
            Question (or Hypothesis, if given).
        hypothesis_id: Optional Hypothesis this Evidence bears on more
            specifically than the Question; must already exist if given.
        limitations: Optional free-text limitations of this finding.
        uncertainty_note: Optional free-text note on remaining
            uncertainty.
        created_by: Name of the skill creating this Evidence, or "user"
            for a direct CLI call.

    Returns:
        The full new Evidence record, including its generated "id".

    Raises:
        ValueError: If statement is empty/missing, or stance isn't one of
            the allowed values.
        SourceNotFoundError: If source_id doesn't exist.
        QuestionNotFoundError: If question_id doesn't exist.
        HypothesisNotFoundError: If hypothesis_id is given but doesn't
            exist.
    """
    if not statement:
        raise ValueError("statement is required")
    if stance not in _EVIDENCE_STANCES:
        raise ValueError(
            f"stance must be 'supports', 'refutes', or 'mixed', got {stance!r}"
        )
    if source_id not in load_sources(project_root):
        raise SourceNotFoundError(f"Unknown source_id: {source_id}")
    if question_id not in load_questions(project_root):
        raise QuestionNotFoundError(f"Unknown question_id: {question_id}")
    if hypothesis_id is not None and hypothesis_id not in load_hypotheses(project_root):
        raise HypothesisNotFoundError(f"Unknown hypothesis_id: {hypothesis_id}")
    path = project_root / EVIDENCE_RELATIVE_PATH
    with _locked_file(project_root, path):
        evidence = _load_yaml_map(path, "evidence")
        evidence_id = generate_id("evd")
        record = {
            "id": evidence_id,
            "source_id": source_id,
            "question_id": question_id,
            "hypothesis_id": hypothesis_id,
            "statement": statement,
            "stance": stance,
            "limitations": limitations,
            "uncertainty_note": uncertainty_note,
            "created_at": _utc_now_iso(),
            "created_by": created_by,
        }
        evidence[evidence_id] = record
        _save_yaml_map(path, "evidence", evidence)
    return record
```

Modify `record_claim`'s signature and body (add `evidence_id`, validate it, include it in the emitted event):

```python
def record_claim(
    project_root: Path,
    run_id: str,
    statement: str,
    confidence: Optional[str] = None,
    evidence_ref: Optional[str] = None,
    evidence_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a Claim event for an existing Run.

    Args:
        project_root: The project's root directory.
        run_id: The Run this Claim belongs to; must already exist.
        statement: The assertion or decision text.
        confidence: Optional "low", "medium", or "high".
        evidence_ref: Optional supporting reference (path, quote, URL).
        evidence_id: Optional id of a structured Evidence record (see
            create_evidence); must already exist if given.

    Returns:
        The full Claim event, including its generated "id" and "ts".

    Raises:
        RunNotFoundError: If run_id doesn't exist in state/runs.yaml.
        EvidenceNotFoundError: If evidence_id is given but doesn't exist.
        ValueError: If statement is empty/missing.
    """
    if not statement:
        raise ValueError("statement is required")
    if run_id not in load_runs(project_root):
        raise RunNotFoundError(f"Unknown run_id: {run_id}")
    if evidence_id is not None and evidence_id not in load_evidence(project_root):
        raise EvidenceNotFoundError(f"Unknown evidence_id: {evidence_id}")
    event: Dict[str, Any] = {
        "event": "claim",
        "id": generate_id("clm"),
        "run_id": run_id,
        "statement": statement,
        "confidence": confidence,
        "evidence_ref": evidence_ref,
        "evidence_id": evidence_id,
        "ts": _utc_now_iso(),
    }
    _append_event(project_root, event)
    return event
```

This replaces the existing `record_claim` function (currently just above `def validate_referential_integrity`) entirely.

- [ ] **Step 4: Implement `state.py` CLI wiring**

In `_build_parser`, add one new action to the mutually exclusive group, right after `action.add_argument("--set-source-evidence-tier", action="store_true")` and before `action.add_argument("--validate", action="store_true")`:

```python
    action.add_argument("--create-evidence", action="store_true")
```

Add the new value flags right after `parser.add_argument("--exclusion-reason", metavar="TEXT")` and before `parser.add_argument("--summary", metavar="TEXT")`:

```python
    parser.add_argument("--stance", choices=["supports", "refutes", "mixed"])
    parser.add_argument("--limitations", metavar="TEXT")
    parser.add_argument("--uncertainty-note", metavar="TEXT")
    parser.add_argument("--evidence-id", metavar="ID")
```

In `_dispatch`, add the new branch right after the `if args.set_source_evidence_tier:` block and before `if args.validate:`:

```python
    if args.create_evidence:
        return state_store.create_evidence(
            project_root, args.source_id, args.question_id, args.statement,
            args.stance, hypothesis_id=args.hypothesis_id,
            limitations=args.limitations, uncertainty_note=args.uncertainty_note,
            created_by=args.skill or "user",
        )
```

Modify the existing `if args.record_claim:` branch to pass `evidence_id`:

```python
    if args.record_claim:
        return state_store.record_claim(
            project_root, args.run_id, args.statement,
            confidence=args.confidence, evidence_ref=args.evidence,
            evidence_id=args.evidence_id,
        )
```

In `main`, add `state_store.EvidenceNotFoundError` to the caught-exception tuple, right after `state_store.SourceNotFoundError,` and before `state_store.LockTimeoutError,`:

```python
        state_store.EvidenceNotFoundError,
```

In the module docstring's `Usage:` block: add a new usage line right after the `--set-source-evidence-tier` usage line and before the `--record-result` usage line:

```
    python state.py --create-evidence --source-id SRC_ID --question-id Q_ID \
        [--hypothesis-id HYP_ID] --statement "..." --stance supports|refutes|mixed \
        [--limitations "..."] [--uncertainty-note "..."] [--skill NAME] [--json]
```

Update the existing `--record-claim` usage line to add `[--evidence-id EVD_ID]`:

```
    python state.py --record-claim --run-id RUN_ID --statement "..." \
        [--confidence low|medium|high] [--evidence "..."] [--evidence-id EVD_ID] [--json]
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `cd skills/agent-state/scripts && python3 -m pytest tests/test_state_cli.py -v`
Expected: all tests pass, running total 111 (101 from Task 1 + 10 new).

- [ ] **Step 6: Commit**

```bash
git add skills/agent-state/scripts/state_store.py skills/agent-state/scripts/state.py \
  skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): add Evidence entity and evidence_id on record_claim"
```

---

### Task 3: Referential integrity + SQLite index (`state_store.py` + `state_index.py`)

**Files:**
- Modify: `skills/agent-state/scripts/state_store.py`
- Modify: `skills/agent-state/scripts/state_index.py`
- Modify: `skills/agent-state/scripts/state.py`
- Test: `skills/agent-state/scripts/tests/test_state_cli.py`

**Interfaces:**
- Consumes: Task 1's `load_sources`/`SOURCES_RELATIVE_PATH`, Task 2's `load_evidence`/`EVIDENCE_RELATIVE_PATH`; existing `validate_referential_integrity`, `_sync_state_tables`, `_ingest_shard`, `query`, `_SCHEMA`, `INDEX_SCHEMA_VERSION`.
- Produces: extended `validate_referential_integrity` (checks `sources.project_id`, `evidence.source_id`, `evidence.question_id`, `evidence.hypothesis_id`); `sources`/`evidence` SQLite tables; `claims.evidence_id` column; `state_index.query(..., source_id=None)`; `INDEX_SCHEMA_VERSION = 3`; CLI `--query --source-id`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/agent-state/scripts/tests/test_state_cli.py`:

```python
def test_validate_catches_dangling_source_project_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source = json.loads(_run(project, "--create-source", "--title", "T", "--json").stdout)
    sources_path = project / ".research" / "state" / "sources.yaml"
    data = yaml.safe_load(sources_path.read_text())
    data["sources"][source["id"]]["project_id"] = "proj_does_not_exist"
    sources_path.write_text(yaml.safe_dump(data))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {
        "entity": "source", "id": source["id"],
        "field": "project_id", "missing_id": "proj_does_not_exist",
    } in data["violations"]


def test_validate_catches_dangling_evidence_foreign_keys(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    ).stdout)
    evidence_path = project / ".research" / "state" / "evidence.yaml"
    data = yaml.safe_load(evidence_path.read_text())
    data["evidence"][evidence["id"]]["source_id"] = "src_does_not_exist"
    evidence_path.write_text(yaml.safe_dump(data))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {
        "entity": "evidence", "id": evidence["id"],
        "field": "source_id", "missing_id": "src_does_not_exist",
    } in data["violations"]


def test_query_source_id_returns_source_and_its_evidence(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    ).stdout)

    result = _run(project, "--query", "--source-id", source_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["sources"][0]["id"] == source_id
    assert [e["id"] for e in data["evidence"]] == [evidence["id"]]


def test_query_question_id_includes_linked_evidence(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    ).stdout)

    result = _run(project, "--query", "--question-id", question_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert [e["id"] for e in data["evidence"]] == [evidence["id"]]


def test_query_claims_include_evidence_id_column(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    evidence = json.loads(_run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    ).stdout)
    run = json.loads(_run(project, "--start-run", "--skill", "deep-research", "--json").stdout)
    _run(
        project, "--record-claim", "--run-id", run["id"], "--statement", "A claim",
        "--evidence-id", evidence["id"], "--json",
    )

    result = _run(project, "--query", "--run-id", run["id"], "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["claims"][0]["evidence_id"] == evidence["id"]


def test_rebuild_index_full_picks_up_sources_and_evidence(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    source_id, question_id = _make_source_and_question(project)
    _run(
        project, "--create-evidence", "--source-id", source_id,
        "--question-id", question_id, "--statement", "A finding",
        "--stance", "supports", "--json",
    )

    result = _run(project, "--rebuild-index", "--full", "--json")

    assert result.returncode == 0, result.stderr
    conn = sqlite3.connect(str(project / ".research" / "indexes" / "index.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    finally:
        conn.close()


def test_index_schema_version_is_stamped_as_3(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--rebuild-index", "--json")

    conn = sqlite3.connect(str(project / ".research" / "indexes" / "index.db"))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd skills/agent-state/scripts && python3 -m pytest tests/test_state_cli.py -k "validate_catches_dangling_source or validate_catches_dangling_evidence or query_source_id or query_question_id_includes_linked_evidence or query_claims_include_evidence_id or rebuild_index_full_picks_up_sources or index_schema_version" -v`
Expected: FAIL/ERROR on every new test.

- [ ] **Step 3: Extend `validate_referential_integrity` in `state_store.py`**

Replace the entire existing `validate_referential_integrity` function with:

```python
def validate_referential_integrity(project_root: Path) -> List[Dict[str, Any]]:
    """Scan state/*.yaml for dangling foreign keys.

    This is a diagnostic pass over hand-authored/hand-edited data -- every
    write path in this module already rejects a dangling reference at write
    time, so a clean project should always report zero violations. Nothing
    is repaired; repair is a human decision.

    Args:
        project_root: The project's root directory.

    Returns:
        A list of violation dicts, each shaped
        {"entity": <type>, "id": <record id>, "field": <fk field name>,
        "missing_id": <the dangling id>}. Empty if nothing is broken.
    """
    projects = load_projects(project_root)
    questions = load_questions(project_root)
    hypotheses = load_hypotheses(project_root)
    experiments = load_experiments(project_root)
    runs = load_runs(project_root)
    sources = load_sources(project_root)
    evidence = load_evidence(project_root)

    violations: List[Dict[str, Any]] = []
    for question_id, question in questions.items():
        project_id = question.get("project_id")
        if project_id and project_id not in projects:
            violations.append({
                "entity": "question", "id": question_id,
                "field": "project_id", "missing_id": project_id,
            })
    for hypothesis_id, hypothesis in hypotheses.items():
        question_id = hypothesis.get("question_id")
        if question_id not in questions:
            violations.append({
                "entity": "hypothesis", "id": hypothesis_id,
                "field": "question_id", "missing_id": question_id,
            })
    for experiment_id, experiment in experiments.items():
        hypothesis_id = experiment.get("hypothesis_id")
        if hypothesis_id not in hypotheses:
            violations.append({
                "entity": "experiment", "id": experiment_id,
                "field": "hypothesis_id", "missing_id": hypothesis_id,
            })
    for run_id, run in runs.items():
        experiment_id = run.get("experiment_id")
        if experiment_id and experiment_id not in experiments:
            violations.append({
                "entity": "run", "id": run_id,
                "field": "experiment_id", "missing_id": experiment_id,
            })
    for source_id, source in sources.items():
        project_id = source.get("project_id")
        if project_id and project_id not in projects:
            violations.append({
                "entity": "source", "id": source_id,
                "field": "project_id", "missing_id": project_id,
            })
    for evidence_id, evidence_record in evidence.items():
        source_id = evidence_record.get("source_id")
        if source_id not in sources:
            violations.append({
                "entity": "evidence", "id": evidence_id,
                "field": "source_id", "missing_id": source_id,
            })
        question_id = evidence_record.get("question_id")
        if question_id not in questions:
            violations.append({
                "entity": "evidence", "id": evidence_id,
                "field": "question_id", "missing_id": question_id,
            })
        hypothesis_id = evidence_record.get("hypothesis_id")
        if hypothesis_id and hypothesis_id not in hypotheses:
            violations.append({
                "entity": "evidence", "id": evidence_id,
                "field": "hypothesis_id", "missing_id": hypothesis_id,
            })
    return violations
```

- [ ] **Step 4: Extend `state_index.py`**

Bump the schema version constant:

```python
INDEX_SCHEMA_VERSION = 3
```

(replaces `INDEX_SCHEMA_VERSION = 2`)

In `_SCHEMA`, add `evidence_id TEXT` to the `claims` table (replace the existing `claims` table definition):

```python
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY, run_id TEXT, statement TEXT,
    confidence TEXT, evidence_ref TEXT, evidence_id TEXT, ts TEXT
);
```

Add the two new tables and their indexes right after the existing `claims` table definition and before `CREATE TABLE IF NOT EXISTS shard_checkpoints`:

```python
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, title TEXT, authors TEXT, year INTEGER, doi TEXT,
    url TEXT, venue TEXT, evidence_tier TEXT, screening_status TEXT,
    exclusion_reason TEXT, project_id TEXT, created_at TEXT, created_by TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY, source_id TEXT, question_id TEXT, hypothesis_id TEXT,
    statement TEXT, stance TEXT, limitations TEXT, uncertainty_note TEXT,
    created_at TEXT, created_by TEXT
);
```

Add the new indexes right after the existing `CREATE INDEX IF NOT EXISTS idx_claims_run_id ON claims(run_id);` line (the last line of `_SCHEMA`):

```python
CREATE INDEX IF NOT EXISTS idx_sources_project_id ON sources(project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_source_id ON evidence(source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_question_id ON evidence(question_id);
CREATE INDEX IF NOT EXISTS idx_evidence_hypothesis_id ON evidence(hypothesis_id);
```

In `_sync_state_tables`, add the two new imports to the existing `from state_store import (...)` block (insert alphabetically):

```python
        EVIDENCE_RELATIVE_PATH,
```
```python
        SOURCES_RELATIVE_PATH,
```

(the full updated import block, replacing the existing one, is:)

```python
    from state_store import (
        DEFAULT_PROJECT_ID,
        EVIDENCE_RELATIVE_PATH,
        EXPERIMENTS_RELATIVE_PATH,
        HYPOTHESES_RELATIVE_PATH,
        PROJECTS_RELATIVE_PATH,
        QUESTIONS_RELATIVE_PATH,
        RUNS_RELATIVE_PATH,
        SOURCES_RELATIVE_PATH,
        _load_yaml_map,
    )
```

Add the two new `_load_yaml_map` calls right after `runs = _load_yaml_map(project_root / RUNS_RELATIVE_PATH, "runs")`:

```python
    sources = _load_yaml_map(project_root / SOURCES_RELATIVE_PATH, "sources")
    evidence = _load_yaml_map(project_root / EVIDENCE_RELATIVE_PATH, "evidence")
```

Add the two new sync blocks at the end of `_sync_state_tables`, right after the existing `runs` sync block (the `conn.executemany(...)` call for runs is the last statement in the function currently):

```python
    conn.execute("DELETE FROM sources")
    if sources:
        conn.executemany(
            "INSERT INTO sources "
            "(id, title, authors, year, doi, url, venue, evidence_tier, "
            "screening_status, exclusion_reason, project_id, created_at, created_by) "
            "VALUES (:id, :title, :authors, :year, :doi, :url, :venue, :evidence_tier, "
            ":screening_status, :exclusion_reason, :project_id, :created_at, :created_by)",
            list(sources.values()),
        )
    conn.execute("DELETE FROM evidence")
    if evidence:
        conn.executemany(
            "INSERT INTO evidence "
            "(id, source_id, question_id, hypothesis_id, statement, stance, "
            "limitations, uncertainty_note, created_at, created_by) "
            "VALUES (:id, :source_id, :question_id, :hypothesis_id, :statement, :stance, "
            ":limitations, :uncertainty_note, :created_at, :created_by)",
            list(evidence.values()),
        )
```

In `_ingest_shard`, replace the existing `elif event["event"] == "claim":` block with:

```python
        elif event["event"] == "claim":
            conn.execute(
                "INSERT OR REPLACE INTO claims "
                "(id, run_id, statement, confidence, evidence_ref, evidence_id, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event["id"], event["run_id"], event["statement"],
                    event.get("confidence"), event.get("evidence_ref"),
                    event.get("evidence_id"), event["ts"],
                ),
            )
```

In `query`, add the `source_id` parameter (insert right after `experiment_id: Optional[str] = None,` and before `skill: Optional[str] = None,`):

```python
    source_id: Optional[str] = None,
```

Update the docstring's `Args:` block, inserting right after the `experiment_id: ...` line:

```
        source_id: Return this Source plus its linked Evidence.
```

Update the `filters` list and its `ValueError` message:

```python
    filters = [
        f for f in
        (run_id, question_id, project_id, hypothesis_id, experiment_id, source_id, skill, since)
        if f is not None
    ]
    if len(filters) != 1:
        raise ValueError(
            "query requires exactly one of "
            "run_id/question_id/project_id/hypothesis_id/experiment_id/source_id/skill/since"
        )
```

Add an `"evidence"` key to the existing `if question_id is not None:` branch's returned dict, right after the `"hypotheses"` key and before the `"runs"` key:

```python
                "evidence": _rows(
                    conn,
                    "SELECT * FROM evidence WHERE question_id = ? ORDER BY created_at",
                    (question_id,),
                ),
```

(the full updated `if question_id is not None:` branch, replacing the existing one, is:)

```python
        if question_id is not None:
            # Both children are returned: "hypotheses" completes the
            # Project -> Question -> Hypothesis chain (the middle link was
            # otherwise unwalkable, even though idx_hypotheses_question_id
            # exists for exactly this lookup), and "runs" is kept alongside
            # it since Runs also carry a direct question_id and existing
            # consumers already read that key.
            return {
                "questions": _rows(
                    conn, "SELECT * FROM questions WHERE id = ?", (question_id,)
                ),
                "hypotheses": _rows(
                    conn,
                    "SELECT * FROM hypotheses WHERE question_id = ? ORDER BY created_at",
                    (question_id,),
                ),
                "evidence": _rows(
                    conn,
                    "SELECT * FROM evidence WHERE question_id = ? ORDER BY created_at",
                    (question_id,),
                ),
                "runs": _rows(
                    conn,
                    "SELECT * FROM runs WHERE question_id = ? ORDER BY started_at",
                    (question_id,),
                ),
            }
```

Add a new `if source_id is not None:` branch right after the existing `if experiment_id is not None:` branch and before `if skill is not None:`:

```python
        if source_id is not None:
            return {
                "sources": _rows(
                    conn, "SELECT * FROM sources WHERE id = ?", (source_id,)
                ),
                "evidence": _rows(
                    conn,
                    "SELECT * FROM evidence WHERE source_id = ? ORDER BY created_at",
                    (source_id,),
                ),
            }
```

- [ ] **Step 5: Wire `--query --source-id` in `state.py`**

In `_dispatch`, add `source_id=args.source_id` to the existing `if args.query:` branch's call:

```python
    if args.query:
        return state_index.query(
            project_root, run_id=args.run_id, question_id=args.question_id,
            project_id=args.project_id, hypothesis_id=args.hypothesis_id,
            experiment_id=args.experiment_id, source_id=args.source_id,
            skill=args.skill, since=args.since,
        )
```

Update the module docstring's `--query` usage line to add `| --source-id ID`:

```
    python state.py --query (--run-id ID | --question-id ID | --project-id ID \
        | --hypothesis-id ID | --experiment-id ID | --source-id ID | --skill NAME \
        | --since DATE) [--json]
        (exactly one filter; each returns the named record plus its children)
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `cd skills/agent-state/scripts && python3 -m pytest tests/test_state_cli.py -v`
Expected: all tests pass, running total 117 (111 from Task 2 + 6 new).

- [ ] **Step 7: Commit**

```bash
git add skills/agent-state/scripts/state_store.py skills/agent-state/scripts/state_index.py \
  skills/agent-state/scripts/state.py skills/agent-state/scripts/tests/test_state_cli.py
git commit -m "feat(agent-state): index Source/Evidence, add --query --source-id, bump index schema to 3"
```

---

### Task 4: `deep-research` integration + `agent-state` docs

**Files:**
- Modify: `skills/deep-research/agents/bibliography_agent.md`
- Modify: `skills/deep-research/agents/source_verification_agent.md`
- Modify: `skills/deep-research/agents/synthesis_agent.md`
- Modify: `skills/agent-state/SKILL.md`

**Interfaces:**
- Consumes: Task 1's `--create-source`/`--set-source-screening`/`--set-source-evidence-tier` flags, Task 2's `--create-evidence`/`--record-claim --evidence-id` flags, Task 3's `--query --source-id`.
- Produces: no new code interfaces -- prose/instruction changes only.

This task has no automated tests (agent instruction files aren't executable). Verify instead by re-running the full `agent-state` test suite unchanged at the end (confirms nothing in Tasks 1-3 regressed) and by reading each edited file back to confirm the inserted text landed at the intended anchor without disturbing surrounding content.

- [ ] **Step 1: Add registration instructions to `bibliography_agent.md`**

Find this exact text (the end of the file):

```
### Search Limitations
- [limitations of search strategy]
```

## Quality Criteria

- Minimum 10 sources for full mode, 5 for quick mode
```

Replace it with:

```
### Search Limitations
- [limitations of search strategy]
```

## Structured Evidence Registration (agent-state)

The Annotated Bibliography above is a rendered *view*. In parallel with
producing it, register each source as structured data so it can be
deduplicated and reused across research runs, following the calling
convention in `skills/agent-state/SKILL.md`:

```bash
STATE="$(find ~/.claude -path "*/agent-state/scripts/state.py" | head -1)"
```

For each source reaching Step 5 (Annotated Bibliography), register it:

```bash
python "$STATE" --create-source --title "Exact Title" --authors "Smith J, Lee K" \
  --year 2024 --doi "10.xxxx/yyyy" --venue "Journal Name" --skill bibliography_agent \
  --project-id proj_20260806_ab12cd --json
```

`--doi`, `--url`, `--year`, `--venue`, `--authors` are all optional --
pass whatever the source actually has. The call is idempotent on an
exact `--doi` or `--url` match: a source already registered (e.g. from an
earlier research run on the same project) is returned unchanged rather
than duplicated. If the response's `duplicate_hint` is non-null, it means
no exact doi/URL match was found but an existing Source shares the same
normalized title, first author, and year -- note this in the Search
Limitations section rather than silently merging or discarding either
record.

For each screening decision made in Step 3/Step 4 (Source Screening),
record it against the `source_id` returned above:

```bash
python "$STATE" --set-source-screening --source-id src_20260806_ab12cd \
  --screening-status excluded --exclusion-reason "Predatory journal" --json
python "$STATE" --set-source-screening --source-id src_20260806_ab12cd \
  --screening-status included --json
```

This registration is additive bookkeeping -- it never changes what goes
into the Annotated Bibliography or Search Strategy Report themselves.

## Quality Criteria

- Minimum 10 sources for full mode, 5 for quick mode
```

- [ ] **Step 2: Add registration instructions to `source_verification_agent.md`**

Find this exact text (the end of the file):

```
### Verification Limitations
- [what could not be verified and why]
```

## Quality Criteria

- Every source must receive an evidence level grade (I-VII)
```

Replace it with:

```
### Verification Limitations
- [what could not be verified and why]
```

## Structured Evidence Registration (agent-state)

After assigning each source its evidence-hierarchy grade (Level I-VII,
per the table above), record that grade against the Source registered by
`bibliography_agent`, using the calling convention in
`skills/agent-state/SKILL.md`:

```bash
STATE="$(find ~/.claude -path "*/agent-state/scripts/state.py" | head -1)"

python "$STATE" --set-source-evidence-tier --source-id src_20260806_ab12cd \
  --evidence-tier "Level II - Randomized Controlled Trial" --json
```

`--evidence-tier` is free text -- pass whatever grade your own Evidence
Hierarchy table assigned (e.g. "Level I - Meta-analysis", "Level VII -
Expert Opinion"). This registration is additive bookkeeping; it never
changes the Source Verification Report itself.

## Quality Criteria

- Every source must receive an evidence level grade (I-VII)
```

- [ ] **Step 3: Add registration instructions to `synthesis_agent.md`**

Find this exact text (the end of the file):

```
### Synthesis Limitations
- [limitations of the synthesis itself]
```

## Quality Criteria

- Must integrate (not just list) findings across sources
```

Replace it with:

```
### Synthesis Limitations
- [limitations of the synthesis itself]
```

## Structured Evidence Registration (agent-state)

Each Key Theme's synthesis and each row of the Contradictions &
Resolutions table is, at its core, a finding extracted from one or more
sources and given a stance toward the current Research Question. Register
each one as a structured Evidence Statement, using the calling convention
in `skills/agent-state/SKILL.md`:

```bash
STATE="$(find ~/.claude -path "*/agent-state/scripts/state.py" | head -1)"

python "$STATE" --create-evidence --source-id src_20260806_ab12cd \
  --question-id q_20260806_ab12cd --statement "Offline caching reduces reported \
  friction in low-connectivity regions" --stance supports \
  --limitations "Single-region sample" --skill synthesis_agent --json
```

`--stance` must be `supports`, `refutes`, or `mixed` relative to the
Question (or `--hypothesis-id`, when the finding bears on a specific
Hypothesis rather than the Question as a whole). `--limitations` and
`--uncertainty-note` are optional free text -- use them for the same
caveats that would otherwise only live in prose inside the Synthesis
Report. This registration is additive bookkeeping; it never changes the
Synthesis Report itself.

## Quality Criteria

- Must integrate (not just list) findings across sources
```

- [ ] **Step 4: Update `skills/agent-state/SKILL.md`**

In the frontmatter `description:` field, find:

```
Also models the research itself as Project/Hypothesis/Experiment, layered above Question/Run, with write-time referential integrity checks.
```

Replace with:

```
Also models the research itself as Project/Hypothesis/Experiment/Source/Evidence, layered above Question/Run, with write-time referential integrity checks.
```

In the body, find:

```
Stores seven cross-skill entities without one file per record. Project,
Question, Hypothesis, Experiment, and Run are low-frequency, mutable, and
live in id-keyed YAML maps under `.research/state/`; Result and Claim are
immutable facts appended to daily JSONL shards under `.research/events/`.
```

Replace with:

```
Stores nine cross-skill entities without one file per record. Project,
Question, Hypothesis, Experiment, Run, Source, and Evidence are
low-frequency, mutable, and live in id-keyed YAML maps under
`.research/state/`; Result and Claim are immutable facts appended to
daily JSONL shards under `.research/events/`.
```

Find:

```
`--start-run` accepts at most *one* level of that chain per call.
Combining levels (e.g. `--question` with `--experiment-id`) is rejected with
a `ValueError` rather than silently letting the more specific one win and
discarding the other -- which would create no Question at all from a
`--question` that named one.

Full design rationale: `docs/superpowers/specs/2026-08-05-agent-state-storage-design.md`.
```

Replace with:

```
`--start-run` accepts at most *one* level of that chain per call.
Combining levels (e.g. `--question` with `--experiment-id`) is rejected with
a `ValueError` rather than silently letting the more specific one win and
discarding the other -- which would create no Question at all from a
`--question` that named one.

Source and Evidence sit alongside this chain rather than inside it: a
Source belongs to a Project directly (not to the linear chain), and an
Evidence Statement links a Source to a Question (required) and optionally
a Hypothesis, letting a research finding be traced back to both where it
came from and what it bears on. Neither participates in `--start-run`'s
synthetic-record auto-fill.

Full design rationale: `docs/superpowers/specs/2026-08-05-agent-state-storage-design.md`
(chain design) and `docs/superpowers/specs/2026-08-06-evidence-foundation-design.md`
(Source/Evidence design).
```

In the `## Research chain` section, find the end of the existing bash block (right before its closing fence):

```
python "$STATE" --set-hypothesis-status --hypothesis-id hyp_20260806_ef34gh --status supported --json
python "$STATE" --set-experiment-status --experiment-id exp_20260806_ij56kl --status completed --json
```
```

Replace with:

```
python "$STATE" --set-hypothesis-status --hypothesis-id hyp_20260806_ef34gh --status supported --json
python "$STATE" --set-experiment-status --experiment-id exp_20260806_ij56kl --status completed --json

# Register a Source (deduplicated by exact doi, then exact normalized URL).
python "$STATE" --create-source --title "Offline-First Mobile UX Patterns" \
  --authors "Ng T, Osei K" --year 2025 --doi "10.1000/xyz123" \
  --skill bibliography_agent --project-id proj_20260806_ab12cd --json
python "$STATE" --set-source-screening --source-id src_20260806_mn78op \
  --screening-status included --json
python "$STATE" --set-source-evidence-tier --source-id src_20260806_mn78op \
  --evidence-tier "Level III - Controlled Study" --json

# Register an Evidence Statement extracted from that Source, tagged with
# its stance toward the Question.
python "$STATE" --create-evidence --source-id src_20260806_mn78op \
  --question-id q_20260806_ab12cd --statement "Offline caching reduced reported \
  friction by 40% in the studied cohort" --stance supports --skill synthesis_agent --json

# Point a Claim at that structured Evidence, alongside (or instead of) a
# free-text evidence_ref.
python "$STATE" --record-claim --run-id run_20260806_qr12st \
  --statement "Ship offline caching for v2" --confidence high \
  --evidence-id evd_20260806_uv34wx --json
```
```

In the `## Querying` section, find:

```
python "$STATE" --query --experiment-id exp_20260806_ij56kl --json  # experiment + its runs
python "$STATE" --query --skill deep-research --json             # that skill's runs
```

Replace with:

```
python "$STATE" --query --experiment-id exp_20260806_ij56kl --json  # experiment + its runs
python "$STATE" --query --source-id src_20260806_mn78op --json      # source + its evidence
python "$STATE" --query --skill deep-research --json             # that skill's runs
```

In the `## Schema versioning` section, find:

```
`state/questions.yaml` and `state/runs.yaml` each carry a top-level
`version:` field; every `events/*.jsonl` line carries a `schema_version`
field; `indexes/index.db` carries its version in SQLite's own
`PRAGMA user_version`. All three currently read `1`.
```

Replace with:

```
`state/questions.yaml` and `state/runs.yaml` each carry a top-level
`version:` field (currently `1`); every `events/*.jsonl` line carries a
`schema_version` field (currently `1`); `indexes/index.db` carries its
version in SQLite's own `PRAGMA user_version` (currently `3`, bumped from
`2` when the Source/Evidence tables and the `claims.evidence_id` column
were added).
```

- [ ] **Step 5: Verify nothing regressed**

Run: `cd skills/agent-state/scripts && python3 -m pytest tests/test_state_cli.py -v`
Expected: all 117 tests still pass (this task touches no code, only Markdown).

Read back all four modified files to confirm each inserted section landed once, at the intended location, and no surrounding text (especially the versioned "MUST NOT" / Phase Boundary language in the three agent files) was altered.

- [ ] **Step 6: Commit**

```bash
git add skills/deep-research/agents/bibliography_agent.md \
  skills/deep-research/agents/source_verification_agent.md \
  skills/deep-research/agents/synthesis_agent.md skills/agent-state/SKILL.md
git commit -m "docs(deep-research,agent-state): wire bibliography/verification/synthesis agents into Source/Evidence registration"
```
