# Research Log Section History Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add budgeted cross-history section queries and teach agents to consult prior research logs proactively before repeating failed, solved, or expensive research work.

**Architecture:** A stateless Python CLI scans Markdown logs on every invocation. Parsing and filtering live in a focused core module, response sizing and opaque cursors live in a budget module, and the CLI module owns JSON I/O and error translation. `research-log` and `research-mode` consume this interface through an event-driven Historical Experience Check protocol that does not require mode activation.

**Tech Stack:** Python 3 standard library (`argparse`, `base64`, `dataclasses`, `datetime`, `hashlib`, `json`, `pathlib`, `re`, `urllib.parse`), pytest subprocess tests, Markdown skill and README documentation.

## Global Constraints

- Implement the approved spec at `docs/superpowers/specs/2026-08-02-research-log-section-history-query-design.md`.
- Default response budget is exactly **4,000 estimated tokens**.
- Agent-selected budgets may be lower; the hard maximum is exactly **8,000 estimated tokens**.
- Estimate serialized responses as `ceil(character_count / 4)` and include all JSON metadata in the estimate.
- `search` never returns full section bodies.
- An overflowing multi-ID `fetch` returns zero partial bodies and provides safe batch suggestions.
- Oversized single sections use reconstructable chunks with exact source offsets; never summarize or silently truncate them.
- Frontmatter `date` is authoritative. Never infer a missing or invalid date from the filename.
- Querying is read-only and stateless. Do not create or modify journal files, `INDEX.md`, or `MILESTONES.md`.
- Use no third-party Python dependencies.
- All new function signatures have type annotations. Public modules, functions, classes, and methods have Google-style English docstrings.
- Keep every source and test file below 1,000 lines.
- All comments, docstrings, log/error messages, and commit subjects are English.
- Keep the four user-facing READMEs structurally consistent: `README.md`, `README.zh-TW.md`, `README.zh-CN.md`, and `README.ja-JP.md`.

---

## File Structure

- **Create** `skills/research-log/scripts/section_query_core.py` — Markdown/frontmatter parsing, canonical taxonomy, aliases, result identity, date-range resolution, and filtering.
- **Create** `skills/research-log/scripts/section_query_budget.py` — deterministic JSON sizing, journal fingerprints, opaque cursor encoding/validation, pagination, fetch batch packing, and exact chunk planning.
- **Create** `skills/research-log/scripts/section_query.py` — CLI arguments, operation orchestration, stable success/error JSON, and exit codes.
- **Create** `skills/research-log/scripts/tests/test_section_query.py` — subprocess coverage for `types`, parsing, aliases, date filters, ordering, IDs, and JSON errors.
- **Create** `skills/research-log/scripts/tests/test_section_query_budget.py` — subprocess coverage for budgets, pagination, cursor invalidation, atomic fetch overflow, batch suggestions, and chunks.
- **Create** `skills/research-log/scripts/tests/test_research_history_protocol.py` — instruction-level assertions for proactive history-check behavior across `research-log` and `research-mode`.
- **Modify** `skills/research-log/SKILL.md` — add `query`, the strict `types → search → fetch` flow, and Historical Experience Check rules.
- **Modify** `skills/research-mode/SKILL.md` — add mode-specific history-check decision points without making modes mandatory.
- **Modify** `skills/research-mode/references/routing_guide.md` — document intent-to-section routing in the shared routing reference.
- **Modify** `examples/research-log/README.md` — add explicit Failures query and overflow/batch examples.
- **Modify** `README.md`, `README.zh-TW.md`, `README.zh-CN.md`, `README.ja-JP.md` — add the query command and proactive-history behavior consistently.

---

### Task 1: Markdown Scanner and Mixed Section Taxonomy

**Files:**
- Create: `skills/research-log/scripts/section_query_core.py`
- Create: `skills/research-log/scripts/section_query.py`
- Create: `skills/research-log/scripts/tests/test_section_query.py`

**Interfaces:**
- Produces: `ScanResult`, `SectionOccurrence`, `TypeSummary`, `QueryWarning`, `scan_journal(log_dir: Path) -> ScanResult`, `normalize_heading(heading: str) -> tuple[str, str]`, and CLI operation `types`.
- Consumes: no earlier task interfaces.

- [ ] **Step 1: Write failing subprocess tests for taxonomy and parsing**

Create helpers that always invoke the public CLI:

```python
"""Subprocess tests for research-log section discovery and search."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "section_query.py"

def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run section_query.py with the supplied CLI arguments."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )

def _write_log(log_dir: Path, name: str, body: str) -> Path:
    """Write one UTF-8 research-log fixture."""
    path = log_dir / name
    path.write_text(body, encoding="utf-8")
    return path

def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Decode a successful JSON response and expose assertion failures."""
    assert result.returncode == 0, result.stderr or result.stdout
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["ok"] is True
    return payload
```

Add focused tests with complete fixtures and assertions:

```python
def test_types_lists_canonical_first_and_discovers_custom(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(
        log_dir,
        "2026-01-02_run.md",
        """---
date: 2026-01-02
experiment: run
---
## Open Problems
Unresolved issue.
## Goal
Test a baseline.
""",
    )

    payload = _payload(_run("types", "--dir", str(log_dir)))
    names = [item["name"] for item in payload["types"]]

    assert names[:9] == [
        "Goal", "Changes", "Setup", "Results", "Failures",
        "Analysis", "Charts", "Conclusion", "Next Steps",
    ]
    assert names[9:] == ["Open Problems"]
    assert payload["types"][9]["occurrence_count"] == 1
    assert payload["types"][9]["log_count"] == 1
    assert payload["types"][9]["earliest_date"] == "2026-01-02"

def test_failure_aliases_merge_but_open_problems_stays_custom(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(
        log_dir,
        "2026-01-02_run.md",
        """---
date: 2026-01-02
experiment: run
---
## Failure
First failure.
## Failures / Pitfalls
Second failure.
## Open Problems
Not yet attempted.
""",
    )

    payload = _payload(_run("types", "--dir", str(log_dir)))
    by_name = {item["name"]: item for item in payload["types"]}

    assert by_name["Failures"]["occurrence_count"] == 2
    assert by_name["Failures"]["variants"] == ["Failure", "Failures / Pitfalls"]
    assert by_name["Open Problems"]["occurrence_count"] == 1
```

Also test that `INDEX.md` and `MILESTONES.md` are excluded, fenced-code `##`
text is ignored, a level-three heading is not discovered as a type, repeated
headings get occurrence numbers 1 and 2, missing `experiment` warns without a
filename fallback, invalid `date` remains visible to `types`, and invalid UTF-8
produces an error. Task 2 verifies that level-three text remains in the parent
section body once `search` exposes body-size metadata.

- [ ] **Step 2: Run taxonomy tests and verify the expected failure**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_section_query.py \
  -k "types or heading or utf" -v
```

Expected: FAIL because `section_query.py` and its core module do not exist.

- [ ] **Step 3: Implement typed models, parsing, taxonomy, and the initial CLI**

Define these exact public interfaces in `section_query_core.py`:

```python
"""Parse and query structured Markdown research-log sections."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

CANONICAL_TYPES: tuple[str, ...] = (
    "Goal", "Changes", "Setup", "Results", "Failures",
    "Analysis", "Charts", "Conclusion", "Next Steps",
)
HEADING_ALIASES: dict[str, str] = {
    "failure": "Failures",
    "failures": "Failures",
    "pitfall": "Failures",
    "pitfalls": "Failures",
    "failures / pitfalls": "Failures",
}

@dataclass(frozen=True)
class QueryWarning:
    """Describe a non-fatal problem found while scanning one log."""

    code: str
    path: str
    message: str

@dataclass(frozen=True)
class SectionOccurrence:
    """Represent one level-two section occurrence in a research log."""

    result_id: str
    path: Path
    log_stem: str
    log_date: date | None
    experiment: str | None
    type_name: str
    type_key: str
    original_heading: str
    occurrence_number: int
    body: str
    body_start: int
    body_end: int

@dataclass(frozen=True)
class ScanResult:
    """Contain parsed sections, warnings, and a content fingerprint."""

    sections: tuple[SectionOccurrence, ...]
    warnings: tuple[QueryWarning, ...]
    journal_fingerprint: str

@dataclass(frozen=True)
class TypeSummary:
    """Summarize one canonical or discovered section type."""

    name: str
    key: str
    canonical: bool
    variants: tuple[str, ...]
    occurrence_count: int
    log_count: int
    earliest_date: date | None
    latest_date: date | None

def normalize_heading(heading: str) -> tuple[str, str]:
    """Return a display name and URL-safe stable key for a heading."""

def scan_journal(log_dir: Path) -> ScanResult:
    """Scan UTF-8 Markdown logs without changing the filesystem."""

def discover_types(scan: ScanResult) -> tuple[TypeSummary, ...]:
    """Return canonical summaries first, followed by custom summaries."""
```

Implementation requirements:

- Read bytes once per file, decode strictly as UTF-8, and feed the same bytes
  into a SHA-256 fingerprint in sorted relative-path order.
- Recognize frontmatter only between opening and closing `---` lines.
- Parse only scalar `date:` and `experiment:` fields; strip one matching pair
  of single or double quotes.
- Track backtick and tilde fenced blocks so headings inside code are ignored.
- Preserve the exact body slice after the `##` heading line through the
  character position before the next level-two heading.
- Normalize heading case and whitespace before consulting the explicit alias
  table. Encode keys with `urllib.parse.quote(..., safe="-._~")`.
- Build IDs as `<filename-stem>::<type-key>` and append `::<occurrence>` only
  for the second and later normalized occurrence.
- Return canonical zero-count summaries, then custom summaries sorted by
  case-folded display name.
- Missing directories and empty directories produce successful empty scans.

In `section_query.py`, add a typed `main(arguments: list[str] | None = None) -> int`
and a `types` subcommand. Emit JSON with `ensure_ascii=False` and an `ok: true`
field. Catch the core's typed read/decoding exception and emit `ok: false` with
a non-zero exit code.

- [ ] **Step 4: Run taxonomy tests and verify they pass**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_section_query.py \
  -k "types or heading or utf" -v
```

Expected: all selected tests PASS.

- [ ] **Step 5: Commit scanner and taxonomy**

```bash
git add \
  skills/research-log/scripts/section_query.py \
  skills/research-log/scripts/section_query_core.py \
  skills/research-log/scripts/tests/test_section_query.py
git commit -m "feat(research-log): discover historical section types"
```

---

### Task 2: Date-Filtered Section Search and Stable Manifests

**Files:**
- Modify: `skills/research-log/scripts/section_query_core.py`
- Modify: `skills/research-log/scripts/section_query.py`
- Modify: `skills/research-log/scripts/tests/test_section_query.py`

**Interfaces:**
- Consumes: `ScanResult`, `SectionOccurrence`, `normalize_heading()`, and `scan_journal()` from Task 1.
- Produces: `DateBounds`, `resolve_date_bounds(...) -> DateBounds`, `search_sections(...) -> tuple[SectionOccurrence, ...]`, `manifest_record(...) -> dict[str, object]`, and CLI operation `search`.

- [ ] **Step 1: Add failing tests for filters, ordering, warnings, and IDs**

Add these representative complete tests:

```python
def test_search_multiple_types_with_inclusive_custom_bounds(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    for day in ("2025-12-31", "2026-01-01", "2026-06-30", "2026-07-01"):
        _write_log(
            log_dir,
            f"{day}_run.md",
            f"""---
date: {day}
experiment: run-{day}
---
## Failures
Failure on {day}.
## Analysis
Analysis on {day}.
""",
        )

    payload = _payload(
        _run(
            "search", "--dir", str(log_dir),
            "--sections", "Failures", "Analysis",
            "--from", "2026-01-01", "--to", "2026-06-30",
        )
    )

    assert payload["total_matches"] == 4
    assert [item["date"] for item in payload["matches"]] == [
        "2026-06-30", "2026-06-30", "2026-01-01", "2026-01-01",
    ]
    assert payload["query"]["resolved_from"] == "2026-01-01"
    assert payload["query"]["resolved_to"] == "2026-06-30"

def test_year_range_uses_explicit_today_for_reproducibility(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    _write_log(
        log_dir,
        "2026-01-01_run.md",
        "---\ndate: 2026-01-01\nexperiment: run\n---\n## Goal\nIncluded.\n",
    )
    _write_log(
        log_dir,
        "2025-12-31_old.md",
        "---\ndate: 2025-12-31\nexperiment: old\n---\n## Goal\nExcluded.\n",
    )

    payload = _payload(
        _run(
            "search", "--dir", str(log_dir), "--sections", "Goal",
            "--range", "year", "--today", "2026-08-02",
        )
    )

    assert payload["total_matches"] == 1
    assert payload["query"]["resolved_from"] == "2026-01-01"
    assert payload["query"]["resolved_to"] == "2026-08-02"
```

Also test `7d`, `30d`, `90d`, default `all`, one-sided custom bounds, custom
bounds conflicting with `--range`, invalid ISO dates, unknown section types
with valid choices, undated logs included last for `all`, undated logs excluded
with warnings for bounded queries, repeated-section IDs, path and original
heading provenance, level-three text included in `body_chars`, a 160-character
whitespace-normalized preview, and the absence of a `body` key in every search
match.

- [ ] **Step 2: Run new search tests and verify they fail**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_section_query.py \
  -k "search or range or bounds or unknown" -v
```

Expected: FAIL because `search` and date-bound interfaces are absent.

- [ ] **Step 3: Implement date bounds and manifest-only search**

Add these exact interfaces to `section_query_core.py`:

```python
@dataclass(frozen=True)
class DateBounds:
    """Describe inclusive resolved bounds for one query."""

    range_name: str
    start: date | None
    end: date | None
    reference_date: date

def resolve_date_bounds(
    range_name: str | None,
    from_text: str | None,
    to_text: str | None,
    today: date,
) -> DateBounds:
    """Validate and resolve preset or custom inclusive date bounds."""

def search_sections(
    scan: ScanResult,
    requested_types: tuple[str, ...],
    bounds: DateBounds,
) -> tuple[SectionOccurrence, ...]:
    """Filter and deterministically order matching section occurrences."""

def manifest_record(section: SectionOccurrence, budget: int) -> dict[str, object]:
    """Build a source-preserving summary without returning the full body."""
```

Use `date.today()` only when `--today` is absent. Resolve preset starts as
`today - timedelta(days=N - 1)` so a `7d` range contains seven inclusive
calendar dates. `year` begins January 1. Reject `--from` later than `--to`, but
allow explicitly requested future bounds.

Resolve canonical names, aliases, and exact discovered custom names through the
same normalizer used by `types`. Unknown names fail as a group and list every
valid current name. Sort valid dates newest first, then filename, then source
occurrence. Put undated matches last for `all` only.

Each manifest record includes `id`, `date`, `experiment`, `path`, `type`,
`type_key`, `original_heading`, `occurrence`, `body_chars`,
`estimated_body_tokens`, `preview`, and `fits_fetch_budget`. Do not include a
body field.

Add the `search` parser and emit normalized query fields, scan warnings,
`total_matches`, and unpaginated records. Task 3 adds response budgeting and
cursors without changing these record fields.

- [ ] **Step 4: Run all core query tests**

```bash
python3 -m pytest skills/research-log/scripts/tests/test_section_query.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit search behavior**

```bash
git add \
  skills/research-log/scripts/section_query.py \
  skills/research-log/scripts/section_query_core.py \
  skills/research-log/scripts/tests/test_section_query.py
git commit -m "feat(research-log): search sections by type and date"
```

---

### Task 3: Response Budgets, Journal Fingerprints, and Pagination Cursors

**Files:**
- Create: `skills/research-log/scripts/section_query_budget.py`
- Create: `skills/research-log/scripts/tests/test_section_query_budget.py`
- Modify: `skills/research-log/scripts/section_query.py`

**Interfaces:**
- Consumes: `journal_fingerprint` from `ScanResult` and manifest dictionaries from Task 2.
- Produces: `DEFAULT_BUDGET`, `MAX_BUDGET`, `estimate_json_tokens(...)`, `encode_cursor(...)`, `decode_cursor(...)`, `paginate_records(...)`, and budgeted `types`/`search` responses.

- [ ] **Step 1: Write failing budget and pagination tests**

Create the second subprocess test module with typed `_run`, `_write_log`, and
`_payload` helpers equivalent to Task 1. Add these key tests:

```python
def test_default_budget_is_4000_and_maximum_is_8000(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()

    default_result = _payload(_run("types", "--dir", str(log_dir)))
    assert default_result["budget"]["limit"] == 4000

    rejected = _run("types", "--dir", str(log_dir), "--budget", "8001")
    assert rejected.returncode != 0
    error = json.loads(rejected.stdout)
    assert error["ok"] is False
    assert error["error"]["code"] == "budget_above_maximum"

def test_search_cursor_returns_every_match_without_duplicates(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    for index in range(40):
        day = index % 28 + 1
        _write_log(
            log_dir,
            f"2026-01-{day:02d}_run_{index:02d}.md",
            f"---\ndate: 2026-01-{day:02d}\nexperiment: run-{index}\n---\n"
            f"## Failures\n{'x' * 300}\n",
        )

    first = _payload(
        _run(
            "search", "--dir", str(log_dir), "--sections", "Failures",
            "--budget", "600",
        )
    )
    assert first["returned_matches"] < first["total_matches"]
    seen = [item["id"] for item in first["matches"]]
    cursor = first["next_cursor"]

    while cursor:
        page = _payload(
            _run(
                "search", "--dir", str(log_dir), "--sections", "Failures",
                "--budget", "600", "--cursor", cursor,
            )
        )
        seen.extend(item["id"] for item in page["matches"])
        cursor = page["next_cursor"]

    assert len(seen) == 40
    assert len(set(seen)) == 40
```

Also test taxonomy pagination preserves canonical-first ordering, each page is
at or below its limit, lower budgets work, too-small metadata budgets fail, a
changed query rejects a search cursor, a changed file rejects both cursor
kinds, and cursors contain only URL-safe opaque text.

- [ ] **Step 2: Run budget tests and verify they fail**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_section_query_budget.py \
  -k "budget or cursor or page" -v
```

Expected: FAIL because budget metadata and pagination do not exist.

- [ ] **Step 3: Implement deterministic sizing and cursor validation**

Create `section_query_budget.py` with these exact interfaces:

```python
"""Budget JSON responses and encode stateless research-log cursors."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_BUDGET = 4000
MAX_BUDGET = 8000
CHARS_PER_TOKEN = 4
CURSOR_VERSION = 1

@dataclass(frozen=True)
class Page:
    """Contain one budget-safe prefix and its continuation cursor."""

    records: tuple[dict[str, object], ...]
    next_cursor: str | None
    estimated_tokens: int

class BudgetError(ValueError):
    """Report an invalid or insufficient response budget."""

    def __init__(self, code: str, message: str, details: dict[str, object]) -> None:
        """Initialize a machine-readable budget error."""
        super().__init__(message)
        self.code = code
        self.details = details

class CursorError(ValueError):
    """Report a malformed, mismatched, or stale opaque cursor."""

def serialize_json(payload: Mapping[str, Any]) -> str:
    """Serialize output exactly as the CLI writes it."""

def estimate_json_tokens(payload: Mapping[str, Any]) -> int:
    """Return ceil(serialized character count divided by four)."""

def query_fingerprint(query: Mapping[str, object]) -> str:
    """Hash normalized query conditions deterministically."""

def encode_cursor(payload: Mapping[str, object]) -> str:
    """Encode versioned JSON as unpadded URL-safe base64 text."""

def decode_cursor(cursor: str) -> dict[str, object]:
    """Decode and validate the shape and version of an opaque cursor."""

def paginate_records(
    records: Sequence[dict[str, object]],
    start_index: int,
    budget: int,
    response_builder: Callable[[Sequence[dict[str, object]], str | None], dict[str, object]],
    cursor_builder: Callable[[int], str],
) -> Page:
    """Return the largest non-empty record prefix whose full JSON fits."""
```

Use compact JSON separators and `ensure_ascii=False` in sizing and final output.
Pagination greedily tests each next record with the exact response builder. If
metadata alone cannot fit, raise `metadata_exceeds_budget`.

Cursor payloads contain `version`, `kind`, `next_index`, resolved directory,
normalized query fingerprint, journal fingerprint, and active budget. Validate
every field and reject reuse under different conditions.

Update `types` and `search` to accept `--budget` and `--cursor`, emit
`budget.limit`, `budget.estimated_tokens`, total/returned counts, and
`next_cursor`, and serialize only through `serialize_json()`.

- [ ] **Step 4: Run parser, search, and budget tests**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_section_query.py \
  skills/research-log/scripts/tests/test_section_query_budget.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit budgeted pagination**

```bash
git add \
  skills/research-log/scripts/section_query.py \
  skills/research-log/scripts/section_query_budget.py \
  skills/research-log/scripts/tests/test_section_query_budget.py
git commit -m "feat(research-log): budget section query manifests"
```

---

### Task 4: Atomic Fetch, Safe Batches, and Exact Section Chunks

**Files:**
- Modify: `skills/research-log/scripts/section_query_budget.py`
- Modify: `skills/research-log/scripts/section_query.py`
- Modify: `skills/research-log/scripts/tests/test_section_query_budget.py`

**Interfaces:**
- Consumes: exact `SectionOccurrence` bodies and IDs from Tasks 1–2; cursor and sizing primitives from Task 3.
- Produces: `plan_batches(...)`, `plan_chunks(...)`, CLI `fetch --ids ...`, and CLI `fetch --chunk-cursor ...`.

- [ ] **Step 1: Add failing tests for full fetch, overflow, batches, and chunks**

Add these key tests:

```python
def test_fetch_overflow_returns_no_partial_body_and_safe_batches(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    ids: list[str] = []
    for index in range(3):
        stem = f"2026-01-0{index + 1}_run_{index}"
        ids.append(f"{stem}::failures")
        _write_log(
            log_dir,
            f"{stem}.md",
            f"---\ndate: 2026-01-0{index + 1}\nexperiment: run-{index}\n---\n"
            f"## Failures\n{'failure ' * 500}\n",
        )

    payload = _payload(
        _run(
            "fetch", "--dir", str(log_dir), "--ids", *ids,
            "--budget", "1800",
        )
    )

    assert payload["status"] == "overflow"
    assert "items" not in payload
    assert payload["requested_ids"] == ids
    assert payload["suggested_batches"]
    assert all(batch["estimated_tokens"] <= 1800 for batch in payload["suggested_batches"])

def test_oversized_section_chunks_reconstruct_exact_body(tmp_path: Path) -> None:
    log_dir = tmp_path / "research_log"
    log_dir.mkdir()
    body = "\n\n".join(
        f"Paragraph {index}: " + "x" * 700 for index in range(12)
    ) + "\n"
    _write_log(
        log_dir,
        "2026-01-01_large.md",
        "---\ndate: 2026-01-01\nexperiment: large\n---\n## Analysis\n" + body,
    )

    first = _payload(
        _run(
            "fetch", "--dir", str(log_dir),
            "--ids", "2026-01-01_large::analysis", "--budget", "600",
        )
    )
    assert first["status"] == "chunk_required"

    chunks: list[str] = []
    cursor = first["chunk_cursor"]
    while cursor:
        page = _payload(
            _run(
                "fetch", "--dir", str(log_dir),
                "--chunk-cursor", cursor, "--budget", "600",
            )
        )
        chunks.append(page["chunk"]["text"])
        assert page["chunk"]["label"].startswith("chunk ")
        cursor = page["next_chunk_cursor"]

    assert "".join(chunks) == body
```

Also test that a fitting multi-ID fetch returns exact bodies and provenance,
request order is preserved, unknown and duplicate IDs fail, repeated
occurrences fetch separately, batch packing includes complete response overhead,
chunk offsets are contiguous and cover `[0, len(body)]`, paragraph boundaries
are preferred, a source edit invalidates a chunk cursor, and changing the budget
invalidates a chunk cursor.

- [ ] **Step 2: Run fetch tests and verify they fail**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_section_query_budget.py \
  -k "fetch or batch or chunk" -v
```

Expected: FAIL because `fetch` and chunk planning are absent.

- [ ] **Step 3: Implement atomic fetch and exact chunk plans**

Add these exact interfaces to `section_query_budget.py`:

```python
@dataclass(frozen=True)
class ChunkPlan:
    """Describe exact source ranges for one oversized section body."""

    ranges: tuple[tuple[int, int], ...]

def plan_batches(
    item_ids: Sequence[str],
    item_response_builder: Callable[[Sequence[str]], dict[str, object]],
    budget: int,
) -> tuple[dict[str, object], ...]:
    """Greedily pack request-order IDs into independently safe fetch batches."""

def plan_chunks(
    body: str,
    chunk_response_builder: Callable[[int, int, int, int], dict[str, object]],
    budget: int,
) -> ChunkPlan:
    """Partition a body into exact budget-safe ranges, preferring paragraphs."""
```

For a normal fetch, build the complete successful response before emitting it.
If it fits, return `status: "complete"` and `items`. If multiple items overflow,
return `status: "overflow"`, `requested_ids`, per-item sizes, and batch objects
with IDs and exact estimated response sizes; do not add `items` or any body.

If one requested item cannot fit alone, return `status: "chunk_required"` and a
cursor bound to the result ID, body SHA-256, journal fingerprint, range index,
and budget. Chunk retrieval returns one exact substring, `chunk X/N`, start/end
offsets, and a next cursor. Search backward from the maximum fitting endpoint
for `\n\n`; use the maximum endpoint when no boundary produces a non-empty
chunk. Prove forward progress for every chunk.

- [ ] **Step 4: Run both CLI test modules**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_section_query.py \
  skills/research-log/scripts/tests/test_section_query_budget.py -v
```

Expected: all tests PASS, including exact chunk reconstruction.

- [ ] **Step 5: Commit full-text retrieval**

```bash
git add \
  skills/research-log/scripts/section_query.py \
  skills/research-log/scripts/section_query_budget.py \
  skills/research-log/scripts/tests/test_section_query_budget.py
git commit -m "feat(research-log): fetch history in safe batches"
```

---

### Task 5: Complete Stable JSON Error Contract

**Files:**
- Modify: `skills/research-log/scripts/section_query.py`
- Modify: `skills/research-log/scripts/section_query_core.py`
- Modify: `skills/research-log/scripts/tests/test_section_query.py`
- Modify: `skills/research-log/scripts/tests/test_section_query_budget.py`

**Interfaces:**
- Consumes: all typed core, budget, cursor, and fetch errors from Tasks 1–4.
- Produces: stable `ok: false` envelopes and non-zero exit statuses for every documented failure.

- [ ] **Step 1: Add failing error-envelope tests**

Parameterize tests over these exact codes and triggers:

```python
ERROR_CASES = (
    ("unknown_section_type", ("search", "--sections", "Does Not Exist")),
    ("invalid_date_filter", ("search", "--sections", "Goal", "--from", "bad-date")),
    (
        "conflicting_date_filters",
        ("search", "--sections", "Goal", "--range", "7d", "--from", "2026-01-01"),
    ),
    ("invalid_result_id", ("fetch", "--ids", "missing::analysis")),
    ("budget_above_maximum", ("types", "--budget", "8001")),
    ("metadata_exceeds_budget", ("types", "--budget", "1")),
)
```

For each case, create a valid temporary journal, insert `--dir <fixture-path>`
after the operation, run the CLI, and assert:

```python
assert result.returncode != 0
assert payload["ok"] is False
assert payload["error"]["code"] == expected_code
assert isinstance(payload["error"]["message"], str)
assert isinstance(payload["error"]["details"], dict)
assert result.stderr == ""
```

Add separate tests for malformed required arguments, malformed cursor,
mismatched cursor, stale cursor, stale chunk cursor, and unreadable UTF-8.

- [ ] **Step 2: Run error tests and observe failures**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_section_query.py \
  skills/research-log/scripts/tests/test_section_query_budget.py \
  -k "error or invalid or stale or malformed or unknown" -v
```

Expected: malformed `argparse` cases FAIL because default parser errors are not
stable JSON yet.

- [ ] **Step 3: Centralize typed errors and JSON argument handling**

Implement this boundary in `section_query.py`:

```python
class QueryCliError(Exception):
    """Carry a stable code, message, details, and process exit status."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
        exit_status: int = 2,
    ) -> None:
        """Initialize a structured CLI error."""
        super().__init__(message)
        self.code = code
        self.details = details or {}
        self.exit_status = exit_status

def error_payload(error: QueryCliError) -> dict[str, object]:
    """Convert one CLI error into the stable public JSON envelope."""
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": str(error),
            "details": error.details,
        },
    }
```

Subclass `argparse.ArgumentParser` and override `error(message: str) -> None` to
raise `QueryCliError("invalid_arguments", message)`. Translate each core and
budget exception once in `main()`. Print one JSON document to stdout and return
the stored non-zero status. Keep `--help` as normal successful help text.

Use distinct codes for malformed, mismatched, and stale cursors. Do not catch
unexpected programmer exceptions as empty results; allow a traceback and
non-zero status during development.

- [ ] **Step 4: Run the entire section-query suite**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_section_query.py \
  skills/research-log/scripts/tests/test_section_query_budget.py -v
```

Expected: all tests PASS and no test observes a silent fallback.

- [ ] **Step 5: Commit error contract**

```bash
git add \
  skills/research-log/scripts/section_query.py \
  skills/research-log/scripts/section_query_core.py \
  skills/research-log/scripts/tests/test_section_query.py \
  skills/research-log/scripts/tests/test_section_query_budget.py
git commit -m "fix(research-log): surface section query errors"
```

---

### Task 6: Research-Log and Research-Mode Historical Experience Protocol

**Files:**
- Create: `skills/research-log/scripts/tests/test_research_history_protocol.py`
- Modify: `skills/research-log/SKILL.md:1-350`
- Modify: `skills/research-mode/SKILL.md:1-160`
- Modify: `skills/research-mode/references/routing_guide.md:1-60`

**Interfaces:**
- Consumes: public CLI commands and fields completed in Tasks 1–5.
- Produces: explicit `/research-log query` instructions and proactive research-history behavior independent of mode activation.

- [ ] **Step 1: Write failing instruction-level protocol tests**

Create tests that read the tracked skill sources and assert exact policy anchors:

```python
"""Instruction-level regression tests for proactive research history checks."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
RESEARCH_LOG = REPO_ROOT / "skills" / "research-log" / "SKILL.md"
RESEARCH_MODE = REPO_ROOT / "skills" / "research-mode" / "SKILL.md"
ROUTING_GUIDE = (
    REPO_ROOT / "skills" / "research-mode" / "references" / "routing_guide.md"
)

def test_research_log_documents_strict_query_sequence() -> None:
    """Require discovery, manifest search, and selected retrieval in order."""
    text = RESEARCH_LOG.read_text(encoding="utf-8")
    assert "### query" in text
    assert "types → search → fetch" in text
    assert "4,000" in text
    assert "8,000" in text
    assert "never silently truncate" in text

def test_history_check_does_not_require_research_mode() -> None:
    """Require direct research intent to activate historical checking."""
    text = RESEARCH_LOG.read_text(encoding="utf-8")
    assert "Historical Experience Check" in text
    assert "Mode activation is not required" in text
    assert "direct research request" in text

def test_advisory_and_costly_operation_gate_are_distinct() -> None:
    """Keep discussion advisory while gating expensive execution."""
    text = RESEARCH_LOG.read_text(encoding="utf-8")
    assert "General research discussion: advisory" in text
    assert "Costly or long-running operation: preflight gate" in text
    assert "must not report a query failure as empty history" in text

def test_mode_routing_covers_all_five_modes() -> None:
    """Require explicit history behavior for every research mode."""
    combined = RESEARCH_MODE.read_text(encoding="utf-8") + ROUTING_GUIDE.read_text(
        encoding="utf-8"
    )
    for mode in ("exp", "daily", "explore", "report", "publish"):
        assert f"`{mode}`" in combined
    assert "Open Problems" in combined
```

Add assertions for direct method ideas, anomalies, parameter changes, costly
reruns, journal absence, session-local duplicate-query avoidance, intentional
reproduction override, all five interpretation categories, and the report-mode
exception.

- [ ] **Step 2: Run protocol tests and verify they fail**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_research_history_protocol.py -v
```

Expected: FAIL because the query and proactive protocol anchors are absent.

- [ ] **Step 3: Update `research-log` with exact query and preflight behavior**

Extend the frontmatter description to cover planning, executing, repeating, and
diagnosing research in projects containing `docs/research_log/`.

Add `### query` with exact macOS/Linux/Git Bash and PowerShell discovery commands
for `section_query.py`, followed by the strict `types → search → fetch` sequence.
Document presets, custom dates, budgets, cursors, overflow, batches, and chunks
using the implemented flags. Require full type-cursor traversal before claiming
a custom type does not exist and full chunk traversal before claiming an
oversized section was reviewed.

Add `## Historical Experience Check` with this table:

| Research intent | Initial types |
|---|---|
| New method or experiment | Goal, Setup, Results, Failures, Conclusion |
| Error or anomaly | Failures, Analysis, Next Steps, discovered problem-oriented custom types |
| Parameter or implementation change | Changes, Setup, Results, Analysis |
| Costly rerun | Goal, Setup, Results, Failures |

State the two-condition trigger, event boundaries, session-local journal
fingerprint reuse, interpretation categories, advisory/gate distinction, empty
journal pass, query-failure handling, and reproduction override exactly as the
approved design specifies.

- [ ] **Step 4: Update `research-mode` routing without making it a prerequisite**

In `research-mode/SKILL.md`, add the history check after activation routing and
before research execution. In `routing_guide.md`, add a mode table with:

- `exp`: setup, run, failure, rerun;
- `daily`: only when notes become a proposed research action;
- `explore`: before committing to a previously investigated direction;
- `publish`: when reconstructing decisions, limitations, fixes, or evidence;
- `report`: only for evidence or decision provenance.

Explicitly state that direct research intent triggers the `research-log`
protocol even when no mode is active.

- [ ] **Step 5: Run protocol and skill metadata checks**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_research_history_protocol.py -v
python3 scripts/check_data_access_level.py
python3 scripts/check_task_type.py
```

Expected: all tests PASS; both lint scripts print their `OK` result and exit 0.

- [ ] **Step 6: Commit skill integration**

```bash
git add \
  skills/research-log/SKILL.md \
  skills/research-log/scripts/tests/test_research_history_protocol.py \
  skills/research-mode/SKILL.md \
  skills/research-mode/references/routing_guide.md
git commit -m "feat(research-log): check history before research work"
```

---

### Task 7: Examples, Four-Language Documentation, and Full Verification

**Files:**
- Modify: `examples/research-log/README.md`
- Modify: `README.md`
- Modify: `README.zh-TW.md`
- Modify: `README.zh-CN.md`
- Modify: `README.ja-JP.md`

**Interfaces:**
- Consumes: final CLI and skill behavior from Tasks 1–6.
- Produces: user-facing command discovery and copy-paste examples in every supported README.

- [ ] **Step 1: Add the English command-table row and proactive behavior paragraph**

Add this row to `README.md`:

```markdown
| `/research-log query` | Find section types, search history by section/date, then fetch selected results within a safe token budget |
```

Add a short paragraph explaining that agents proactively consult relevant
history before new experiments, anomaly diagnosis, parameter changes, and
costly reruns, even without `/mode`.

- [ ] **Step 2: Add structurally equivalent Traditional Chinese, Simplified Chinese, and Japanese text**

Use these command descriptions:

```markdown
| `/research-log query` | 依章節與日期搜尋歷史，再於安全 token 預算內讀取選定結果 |
| `/research-log query` | 按章节与日期搜索历史，再在安全 token 预算内读取选定结果 |
| `/research-log query` | セクションと日付で履歴を検索し、安全なトークン予算内で選択結果を取得 |
```

Mirror the proactive-history paragraph in each language. Preserve each
README's existing vocabulary and heading structure.

- [ ] **Step 3: Add executable examples to `examples/research-log/README.md`**

Document script discovery plus these scenarios:

```bash
SECTION_QUERY="$(find ~/.claude -path "*/research-log/scripts/section_query.py" | head -1)"
python3 "$SECTION_QUERY" types --dir examples/research-log
python3 "$SECTION_QUERY" search \
  --dir examples/research-log \
  --sections Failures \
  --range all
python3 "$SECTION_QUERY" fetch \
  --dir examples/research-log \
  --ids "2026-05-18_bert_finetuned_full::failures"
```

Explain that an overflow response contains no partial body. Show how to repeat
`fetch` using each `suggested_batches[].ids` group or the returned
`chunk_cursor` until `next_chunk_cursor` is null.

- [ ] **Step 4: Run focused and repository-wide verification**

```bash
python3 -m pytest \
  skills/research-log/scripts/tests/test_log_stats.py \
  skills/research-log/scripts/tests/test_section_query.py \
  skills/research-log/scripts/tests/test_section_query_budget.py \
  skills/research-log/scripts/tests/test_research_history_protocol.py -v
python3 -m pytest -q
python3 scripts/check_data_access_level.py
python3 scripts/check_task_type.py
npm pack --dry-run
git diff --check
```

Expected:

- all focused research-log tests PASS;
- the full pytest suite exits 0 with no failures;
- both skill metadata checks exit 0 with `OK` output;
- `npm pack --dry-run` lists `section_query.py`, `section_query_core.py`, and
  `section_query_budget.py` under `skills/research-log/scripts/`;
- `git diff --check` emits no output.

If an environment-only blocker occurs, record the exact command and error
separately from verified focused-test status. Do not flatten a blocker into a
test failure or claim the full suite passed.

- [ ] **Step 5: Review changed-file scope and commit documentation**

```bash
git status --short
git diff --stat
git add \
  README.md README.zh-TW.md README.zh-CN.md README.ja-JP.md \
  examples/research-log/README.md
git commit -m "docs(research-log): document historical section queries"
```

- [ ] **Step 6: Perform final clean-tree evidence check**

```bash
git status --short
git log -8 --oneline
```

Expected: empty status output, seven implementation commits at the top of
history, and the approved design commit immediately after them. Do not push or
open a pull request unless the user separately asks.
