# report-slides Multi-Agent Redesign — Phase A: State Store & Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic, offline-testable foundation the rest of the report-slides redesign depends on: a Deck/Slide/VisualModule state machine with a real production gate, the Deck Plan / Complex Visual Specification / Worker Assignment contract validators, a deterministic complex-visual-detection function, and a real `.pptx` structural validator. Phase B (SKILL.md rewrite + 11 agent persona files) and Phase C (worked example + reference docs) build on top of this and are separate plans.

**Architecture:** See `docs/superpowers/specs/2026-08-06-report-slides-multiagent-design.md` for full rationale. Summary: a new, independent `presentation_state.py` module (not an extension of `agent-state`) implements the Deck/Slide/VisualModule/Review-Result/Revision-Request state store under `.research/presentations/`, following `agent-state`'s proven pattern (sidecar-lock atomic YAML writes, id-keyed maps, append-only JSONL events, write-time referential-integrity checks) as an independent implementation with no code dependency on that skill. Separate small validator scripts under `skills/report-slides/scripts/` check the Deck Plan, Complex Visual Specification, and produced `.pptx` structure contracts. `validate_diagram_manifest.py` and `validate_visual_review.py` (existing, tested scripts) gain small additive extensions.

**Tech Stack:** Python 3, PyYAML, `python-pptx` (already a dependency via `to_pptx.py`), stdlib `zipfile`/`xml.etree.ElementTree`/`fcntl`, pytest (subprocess-driven CLI tests, following `agent-state`'s `test_state_cli.py` pattern).

## Global Constraints

- All new functions carry full type hints and Google-style docstrings (user's global code-style standard).
- No silent failures: empty/invalid required fields raise `ValueError`; unknown foreign-key ids raise the matching `*NotFoundError`; illegal state transitions raise `ValueError` naming the attempted and allowed transitions.
- All generated file content (code, docstrings, comments, test names) is in English.
- No placeholders — every step below contains the literal code to write.
- **`presentation_state.py` is a new, independent module.** It must not import anything from `skills/agent-state/`. It reuses that skill's *pattern* (locking, atomic YAML, id-keyed maps), not its code.
- **Storage location:** `.research/presentations/` at the project root (found via the same "nearest ancestor containing `.git`" convention). This module bootstraps its own `.research/presentations/.gitignore` (covering `state/*.lock`, `events/`, `cache/`) — it must never write to or assume the existence of `.research/.gitignore` itself, since `agent-state` may independently manage that file in the same project and the two must never race or clobber each other.
- **Shared production-unit state machine:** the task's own required-states list defines *one* shared 9-state enum for "Slide or visual module" (`planned, ready, assigned, producing, review_required, revision_required, passed, blocked, superseded`) — implement this as one shared transition table/constant pair, used by both the Slide and Visual Module entities, not two separate copies.
- Every id is generated via `generate_id(prefix)` → `"<prefix>_<UTC-date>_<6-hex-chars>"`, exactly `agent-state`'s existing format (`deck`, `sld`, `mod`, `rev`, `rvq` prefixes for Deck/Slide/VisualModule/ReviewResult/RevisionRequest respectively).
- Baseline: the existing `report-slides` test suites (`scripts/tests/*.py`, `svg_to_pptx/tests/*.py`) must stay green throughout — verify with `cd skills/report-slides/scripts && python3 -m pytest -v` after Task 7 as well as after every task that touches an existing file.
- `validate_diagram_manifest.py` and `validate_visual_review.py` are **existing, tested files** (44 and 13 test cases respectively per the audit) — Task 7's edits must be strictly additive (new optional field, new enum values appended to an existing tuple) and must not change any existing required-field behavior.

---

### Task 1: `presentation_state.py` core — module scaffold, Deck, and Slide entities

**Files:**
- Create: `skills/report-slides/scripts/presentation_state.py`
- Test: `skills/report-slides/scripts/tests/test_presentation_state.py`

**Interfaces:**
- Produces: `find_project_root`, `generate_id`, `_utc_now_iso`, `_ensure_research_gitignore`, `_locked_file`, `_load_yaml_map`, `_save_yaml_map` (shared primitives every later task in this plan builds on); `ProjectRootNotFoundError`, `StateParseError`, `DeckNotFoundError`, `SlideNotFoundError`, `LockTimeoutError`; `DECKS_RELATIVE_PATH`, `SLIDES_RELATIVE_PATH`; `load_decks`, `create_deck`, `set_deck_status`; `load_slides`, `create_slide`, `set_slide_status`; `_DECK_TRANSITIONS`, `_DECK_STATUSES`, `_PRODUCTION_UNIT_TRANSITIONS`, `_PRODUCTION_UNIT_STATUSES`; a CLI (`_build_parser`, `_dispatch`, `main`) with actions `--create-deck`, `--set-deck-status`, `--create-slide`, `--set-slide-status`.

- [ ] **Step 1: Write the failing tests**

Create `skills/report-slides/scripts/tests/test_presentation_state.py`:

```python
"""Subprocess tests for presentation_state.py -- Deck/Slide state CLI."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "presentation_state.py"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, check=False,
    )


def test_create_deck_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-deck", "--title", "Q3 Results Deck", "--skill", "research_narrative_planner", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("deck_")
    assert data["title"] == "Q3 Results Deck"
    assert data["status"] == "planning"
    assert data["plan_version"] == 0
    assert data["created_by"] == "research_narrative_planner"


def test_create_deck_without_title_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--create-deck", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_set_deck_status_legal_transition(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "content_review", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "content_review"


def test_set_deck_status_illegal_transition_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    # planning -> approved directly is illegal; must pass through
    # content_review and awaiting_approval first.
    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "approved", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    assert "Illegal deck transition" in data["message"]


def test_set_deck_status_unrecognized_status_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "not-a-real-status", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_set_deck_status_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--set-deck-status", "--deck-id", "deck_does_not_exist", "--status", "content_review", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "DeckNotFoundError"


def test_deck_can_be_blocked_from_any_active_state(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "blocked", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "blocked"


def test_deck_can_resume_from_blocked_to_prior_active_state(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "blocked", "--json")

    result = _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "content_review", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "content_review"


def test_create_slide_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01",
        "--title", "Action conditioning improves command sensitivity", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("sld_")
    assert data["deck_id"] == deck["id"]
    assert data["plan_slide_id"] == "slide-01"
    assert data["status"] == "planned"


def test_create_slide_without_title_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)

    result = _run(project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_slide_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-slide", "--deck-id", "deck_does_not_exist",
        "--plan-slide-id", "slide-01", "--title", "T", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "DeckNotFoundError"


def test_set_slide_status_legal_transition(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    slide = json.loads(_run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--title", "T", "--json",
    ).stdout)

    result = _run(project, "--set-slide-status", "--slide-id", slide["id"], "--status", "ready", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "ready"


def test_set_slide_status_illegal_transition_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    slide = json.loads(_run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--title", "T", "--json",
    ).stdout)

    # planned -> passed directly is illegal.
    result = _run(project, "--set-slide-status", "--slide-id", slide["id"], "--status", "passed", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_set_slide_status_unknown_slide_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--set-slide-status", "--slide-id", "sld_does_not_exist", "--status", "ready", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SlideNotFoundError"


def test_bootstraps_own_gitignore_not_shared_one(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    _run(project, "--create-deck", "--title", "T", "--json")

    assert (project / ".research" / "presentations" / ".gitignore").is_file()
    assert not (project / ".research" / ".gitignore").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_state.py -v`
Expected: FAIL/ERROR on every test (`presentation_state.py` doesn't exist yet).

- [ ] **Step 3: Implement `presentation_state.py`**

Create `skills/report-slides/scripts/presentation_state.py`:

```python
#!/usr/bin/env python3
"""presentation_state.py -- Deck/Slide/VisualModule state store, Review
Result event log, and Revision Request store for the report-slides
multi-agent workflow.

Independent implementation (no import from skills/agent-state/) that
follows the same proven pattern: sidecar-lock-file writes, atomic YAML
replace, id-keyed maps for mutable records, append-only JSONL for
immutable facts, and write-time referential-integrity checks. Bootstraps
its own .research/presentations/.gitignore rather than touching
.research/.gitignore, since agent-state may independently manage that
file in the same project.

Usage:
    python presentation_state.py --create-deck --title "..." [--skill NAME] [--json]
    python presentation_state.py --set-deck-status --deck-id DECK_ID \
        --status planning|content_review|awaiting_approval|approved|producing| \
        draft_review|revising|validating|completed|blocked [--json]

    python presentation_state.py --create-slide --deck-id DECK_ID \
        --plan-slide-id "slide-01" --title "..." [--skill NAME] [--json]
    python presentation_state.py --set-slide-status --slide-id SLIDE_ID \
        --status planned|ready|assigned|producing|review_required| \
        revision_required|passed|blocked|superseded [--json]
"""
import argparse
import errno
import fcntl
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Run: pip install pyyaml", file=sys.stderr)
    raise SystemExit(1)


DECKS_RELATIVE_PATH = Path(".research/presentations/state/decks.yaml")
SLIDES_RELATIVE_PATH = Path(".research/presentations/state/slides.yaml")
VISUAL_MODULES_RELATIVE_PATH = Path(".research/presentations/state/visual_modules.yaml")
REVISION_REQUESTS_RELATIVE_PATH = Path(".research/presentations/state/revision_requests.yaml")
EVENTS_RELATIVE_DIR = Path(".research/presentations/events")
STATE_SCHEMA_VERSION = 1
LOCK_TIMEOUT_SECONDS = int(os.environ.get("PRESENTATION_STATE_LOCK_TIMEOUT_SECONDS", "30"))
LOCK_POLL_INTERVAL_SECONDS = 0.1

_DECK_TRANSITIONS: Dict[str, frozenset] = {
    "planning": frozenset({"content_review", "blocked"}),
    "content_review": frozenset({"awaiting_approval", "planning", "blocked"}),
    "awaiting_approval": frozenset({"approved", "planning", "blocked"}),
    "approved": frozenset({"producing", "blocked"}),
    "producing": frozenset({"draft_review", "blocked"}),
    "draft_review": frozenset({"producing", "validating", "blocked"}),
    "validating": frozenset({"completed", "revising", "blocked"}),
    "revising": frozenset({"validating", "blocked"}),
    "completed": frozenset(),
    "blocked": frozenset({
        "planning", "content_review", "awaiting_approval", "approved",
        "producing", "draft_review", "validating", "revising",
    }),
}
_DECK_STATUSES = frozenset(_DECK_TRANSITIONS.keys())

# Shared by Slide and Visual Module -- the task's own required-states list
# defines one 9-state enum for "Slide or visual module", not two.
_PRODUCTION_UNIT_TRANSITIONS: Dict[str, frozenset] = {
    "planned": frozenset({"ready", "blocked"}),
    "ready": frozenset({"assigned", "blocked"}),
    "assigned": frozenset({"producing", "blocked"}),
    "producing": frozenset({"review_required", "blocked"}),
    "review_required": frozenset({"passed", "revision_required", "blocked"}),
    "revision_required": frozenset({"producing", "blocked"}),
    "passed": frozenset({"superseded", "blocked"}),
    "blocked": frozenset({
        "planned", "ready", "assigned", "producing",
        "review_required", "revision_required",
    }),
    "superseded": frozenset(),
}
_PRODUCTION_UNIT_STATUSES = frozenset(_PRODUCTION_UNIT_TRANSITIONS.keys())


class ProjectRootNotFoundError(RuntimeError):
    """Raised when no ancestor directory containing a .git entry can be found."""


class StateParseError(ValueError):
    """Raised when a state/*.yaml file exists but cannot be parsed as valid YAML."""


class DeckNotFoundError(ValueError):
    """Raised when a deck_id does not exist in state/decks.yaml."""


class SlideNotFoundError(ValueError):
    """Raised when a slide_id does not exist in state/slides.yaml."""


class LockTimeoutError(RuntimeError):
    """Raised when an exclusive lock can't be acquired within the timeout."""


def find_project_root(start: Path) -> Path:
    """Find the nearest ancestor directory containing a .git entry.

    Args:
        start: Directory to begin the upward search from.

    Returns:
        The absolute path of the first directory (start or an ancestor)
        that contains a .git file or directory.

    Raises:
        ProjectRootNotFoundError: If no ancestor up to the filesystem root
            contains a .git entry.
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise ProjectRootNotFoundError(f"No .git found in {start} or any parent directory.")


def generate_id(prefix: str) -> str:
    """Generate a sortable, human-scannable record id.

    Args:
        prefix: Short entity tag, e.g. "deck", "sld", "mod".

    Returns:
        An id of the form "<prefix>_<UTC-date>_<6-hex-chars>".
    """
    now = datetime.now(timezone.utc)
    return f"{prefix}_{now:%Y%m%d}_{uuid.uuid4().hex[:6]}"


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 "Z"-suffixed string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_research_gitignore(project_root: Path) -> None:
    """Bootstrap .research/presentations/.gitignore on first write.

    Scoped to this module's own subtree -- never touches the top-level
    .research/.gitignore, which agent-state may independently manage in
    the same project.

    Args:
        project_root: The project's root directory.
    """
    gitignore_path = project_root / ".research" / "presentations" / ".gitignore"
    if gitignore_path.exists():
        return
    gitignore_path.parent.mkdir(parents=True, exist_ok=True)
    gitignore_path.write_text("state/*.lock\nevents/\ncache/\n", encoding="utf-8")


@contextmanager
def _locked_file(project_root: Path, path: Path) -> Iterator[None]:
    """Acquire an exclusive lock scoped to `path` via a sidecar lock file.

    Locks the sidecar (`path` + ".lock"), never `path` itself: an atomic
    replace of `path` inside the critical section would otherwise swap in
    a fresh, never-locked inode, letting a concurrent process race past
    the lock. The sidecar is only ever touch()'d then flocked, so its
    identity never changes.

    Args:
        project_root: The project's root directory.
        path: The data file this lock protects.

    Raises:
        LockTimeoutError: If the lock isn't acquired within
            LOCK_TIMEOUT_SECONDS.
    """
    _ensure_research_gitignore(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.touch(exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR)
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"Could not acquire lock on {lock_path} within {LOCK_TIMEOUT_SECONDS}s"
                    )
                time.sleep(LOCK_POLL_INTERVAL_SECONDS)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _load_yaml_map(path: Path, top_key: str) -> Dict[str, Any]:
    """Load an id-keyed YAML document's records map.

    Args:
        path: Path to the YAML file.
        top_key: The top-level key the records map is nested under.

    Returns:
        id -> record map (empty if the file doesn't exist yet).

    Raises:
        StateParseError: If the file exists but isn't valid YAML, or its
            schema version doesn't match STATE_SCHEMA_VERSION.
    """
    if not path.exists():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise StateParseError(f"Invalid YAML in {path}: {exc}") from exc
    version = doc.get("version", 1)
    if version != STATE_SCHEMA_VERSION:
        raise StateParseError(
            f"Unsupported schema version {version!r} in {path} (expected {STATE_SCHEMA_VERSION})"
        )
    return doc.get(top_key, {}) or {}


def _save_yaml_map(path: Path, top_key: str, records: Dict[str, Any]) -> None:
    """Write an id-keyed YAML document, replacing the file atomically.

    Args:
        path: Destination YAML path.
        top_key: Top-level key to nest `records` under.
        records: The full id -> record map to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        yaml.safe_dump({"version": STATE_SCHEMA_VERSION, top_key: records}, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def load_decks(project_root: Path) -> Dict[str, Any]:
    """Load all Deck records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Deck record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / DECKS_RELATIVE_PATH, "decks")


def create_deck(project_root: Path, title: str, created_by: str = "user") -> Dict[str, Any]:
    """Create a new Deck record with status "planning".

    Args:
        project_root: The project's root directory.
        title: Human-readable deck title/working name.
        created_by: Name of the skill/agent creating this Deck, or "user".

    Returns:
        The full new Deck record, including its generated "id".

    Raises:
        ValueError: If title is empty/missing.
    """
    if not title:
        raise ValueError("title is required")
    path = project_root / DECKS_RELATIVE_PATH
    with _locked_file(project_root, path):
        decks = _load_yaml_map(path, "decks")
        deck_id = generate_id("deck")
        now = _utc_now_iso()
        record = {
            "id": deck_id, "title": title, "status": "planning", "plan_version": 0,
            "created_at": now, "updated_at": now, "created_by": created_by,
        }
        decks[deck_id] = record
        _save_yaml_map(path, "decks", decks)
    return record


def set_deck_status(project_root: Path, deck_id: str, status: str) -> Dict[str, Any]:
    """Transition a Deck's workflow status.

    Args:
        project_root: The project's root directory.
        deck_id: The Deck to update.
        status: New status; must be a legal transition from the Deck's
            current status per the Deck state machine.

    Returns:
        The updated Deck record.

    Raises:
        DeckNotFoundError: If deck_id doesn't exist.
        ValueError: If status is unrecognized or not a legal transition
            from the Deck's current status.
    """
    if status not in _DECK_STATUSES:
        raise ValueError(f"Unrecognized deck status: {status!r}")
    path = project_root / DECKS_RELATIVE_PATH
    with _locked_file(project_root, path):
        decks = _load_yaml_map(path, "decks")
        if deck_id not in decks:
            raise DeckNotFoundError(f"Unknown deck_id: {deck_id}")
        current = decks[deck_id]["status"]
        if status not in _DECK_TRANSITIONS[current]:
            raise ValueError(
                f"Illegal deck transition: {current!r} -> {status!r} "
                f"(allowed from {current!r}: {sorted(_DECK_TRANSITIONS[current])})"
            )
        decks[deck_id]["status"] = status
        decks[deck_id]["updated_at"] = _utc_now_iso()
        _save_yaml_map(path, "decks", decks)
        return decks[deck_id]


def load_slides(project_root: Path) -> Dict[str, Any]:
    """Load all Slide records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Slide record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / SLIDES_RELATIVE_PATH, "slides")


def create_slide(
    project_root: Path, deck_id: str, plan_slide_id: str, title: str, created_by: str = "user",
) -> Dict[str, Any]:
    """Create a new Slide record with status "planned".

    Args:
        project_root: The project's root directory.
        deck_id: The Deck this Slide belongs to; must already exist.
        plan_slide_id: The slide_id assigned to this slide in the Deck
            Plan contract (e.g. "slide-01") -- distinct from this
            record's own generated "id", kept so the state store and the
            plan document can be cross-referenced.
        title: The slide's current title.
        created_by: Name of the skill/agent creating this Slide, or "user".

    Returns:
        The full new Slide record, including its generated "id".

    Raises:
        ValueError: If title or plan_slide_id is empty/missing.
        DeckNotFoundError: If deck_id doesn't exist.
    """
    if not plan_slide_id:
        raise ValueError("plan_slide_id is required")
    if not title:
        raise ValueError("title is required")
    if deck_id not in load_decks(project_root):
        raise DeckNotFoundError(f"Unknown deck_id: {deck_id}")
    path = project_root / SLIDES_RELATIVE_PATH
    with _locked_file(project_root, path):
        slides = _load_yaml_map(path, "slides")
        slide_id = generate_id("sld")
        now = _utc_now_iso()
        record = {
            "id": slide_id, "deck_id": deck_id, "plan_slide_id": plan_slide_id, "title": title,
            "status": "planned", "created_at": now, "updated_at": now, "created_by": created_by,
        }
        slides[slide_id] = record
        _save_yaml_map(path, "slides", slides)
    return record


def set_slide_status(project_root: Path, slide_id: str, status: str) -> Dict[str, Any]:
    """Transition a Slide's production status.

    Args:
        project_root: The project's root directory.
        slide_id: The Slide to update.
        status: New status; must be a legal transition from the Slide's
            current status per the shared production-unit state machine.

    Returns:
        The updated Slide record.

    Raises:
        SlideNotFoundError: If slide_id doesn't exist.
        ValueError: If status is unrecognized or not a legal transition
            from the Slide's current status.
    """
    if status not in _PRODUCTION_UNIT_STATUSES:
        raise ValueError(f"Unrecognized slide status: {status!r}")
    path = project_root / SLIDES_RELATIVE_PATH
    with _locked_file(project_root, path):
        slides = _load_yaml_map(path, "slides")
        if slide_id not in slides:
            raise SlideNotFoundError(f"Unknown slide_id: {slide_id}")
        current = slides[slide_id]["status"]
        if status not in _PRODUCTION_UNIT_TRANSITIONS[current]:
            raise ValueError(
                f"Illegal slide transition: {current!r} -> {status!r} "
                f"(allowed from {current!r}: {sorted(_PRODUCTION_UNIT_TRANSITIONS[current])})"
            )
        slides[slide_id]["status"] = status
        slides[slide_id]["updated_at"] = _utc_now_iso()
        _save_yaml_map(path, "slides", slides)
        return slides[slide_id]


def _build_parser() -> argparse.ArgumentParser:
    """Construct the presentation_state.py argument parser."""
    parser = argparse.ArgumentParser(
        description="Presentation state: Deck/Slide/VisualModule workflow store."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create-deck", action="store_true")
    action.add_argument("--set-deck-status", action="store_true")
    action.add_argument("--create-slide", action="store_true")
    action.add_argument("--set-slide-status", action="store_true")

    parser.add_argument("--skill", metavar="NAME")
    parser.add_argument("--title", metavar="TEXT")
    parser.add_argument("--deck-id", metavar="ID")
    parser.add_argument("--slide-id", metavar="ID")
    parser.add_argument("--plan-slide-id", metavar="ID")
    parser.add_argument("--status", metavar="STATUS")
    parser.add_argument("--json", action="store_true")
    return parser


def _dispatch(args: argparse.Namespace, project_root: Path) -> Dict[str, Any]:
    """Route parsed CLI args to the matching call.

    Args:
        args: Parsed argparse namespace.
        project_root: The project's root directory.

    Returns:
        The JSON-serializable result of the selected action.
    """
    if args.create_deck:
        return create_deck(project_root, args.title, created_by=args.skill or "user")
    if args.set_deck_status:
        return set_deck_status(project_root, args.deck_id, args.status)
    if args.create_slide:
        return create_slide(
            project_root, args.deck_id, args.plan_slide_id, args.title,
            created_by=args.skill or "user",
        )
    if args.set_slide_status:
        return set_slide_status(project_root, args.slide_id, args.status)
    raise AssertionError("no action selected despite argparse required group")


def main() -> None:
    """CLI entry point for presentation_state.py."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        project_root = find_project_root(Path.cwd())
        result = _dispatch(args, project_root)
    except (
        ProjectRootNotFoundError, StateParseError, DeckNotFoundError,
        SlideNotFoundError, LockTimeoutError, ValueError,
    ) as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 -- stdout must always stay parseable
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)

    print(json.dumps(result) if args.json else json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_state.py -v`
Expected: all 15 tests pass, pristine output.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_state.py skills/report-slides/scripts/tests/test_presentation_state.py
git commit -m "feat(report-slides): add Deck and Slide state entities to presentation_state.py"
```

---

### Task 2: Visual Module, Review Result, and Revision Request

**Files:**
- Modify: `skills/report-slides/scripts/presentation_state.py`
- Modify: `skills/report-slides/scripts/tests/test_presentation_state.py`

**Interfaces:**
- Consumes: Task 1's `_locked_file`, `_load_yaml_map`, `_save_yaml_map`, `generate_id`, `_utc_now_iso`, `load_slides`, `SlideNotFoundError`, `_PRODUCTION_UNIT_TRANSITIONS`, `_PRODUCTION_UNIT_STATUSES`, `load_decks`, `DeckNotFoundError`, the `_build_parser`/`_dispatch`/`main` scaffold.
- Produces: `VisualModuleNotFoundError`; `VISUAL_MODULES_RELATIVE_PATH`, `_MODULE_TYPES`; `load_visual_modules`, `create_visual_module`, `set_module_status`; `record_review`, `_REVIEW_SUBJECT_TYPES`, `_REVIEW_STATUSES`, `_events_shard_path`, `_append_event`; `REVISION_REQUESTS_RELATIVE_PATH`, `_REVISION_REQUESTERS`; `load_revision_requests`, `create_revision_request`; new CLI actions `--create-visual-module`, `--set-module-status`, `--record-review`, `--create-revision-request`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/report-slides/scripts/tests/test_presentation_state.py`:

```python
def _make_deck_and_slide(project: Path) -> tuple:
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    slide = json.loads(_run(
        project, "--create-slide", "--deck-id", deck["id"], "--plan-slide-id", "slide-01", "--title", "T", "--json",
    ).stdout)
    return deck["id"], slide["id"]


def test_create_visual_module_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)

    result = _run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "observation-input", "--module-type", "architecture",
        "--skill", "architecture_diagram_worker", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("mod_")
    assert data["slide_id"] == slide_id
    assert data["module_key"] == "observation-input"
    assert data["module_type"] == "architecture"
    assert data["status"] == "planned"
    assert data["dependencies"] == []


def test_create_visual_module_invalid_type_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)

    result = _run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "m1", "--module-type", "not-a-real-type", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_create_visual_module_unknown_slide_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--create-visual-module", "--slide-id", "sld_does_not_exist",
        "--module-key", "m1", "--module-type", "architecture", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SlideNotFoundError"


def test_create_visual_module_unknown_dependency_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)

    result = _run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "m1", "--module-type", "architecture",
        "--dependencies", "mod_does_not_exist", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "VisualModuleNotFoundError"


def test_module_cannot_start_producing_with_unresolved_dependency(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    upstream = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "upstream", "--module-type", "architecture", "--json",
    ).stdout)
    downstream = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "downstream", "--module-type", "architecture",
        "--dependencies", upstream["id"], "--json",
    ).stdout)
    for status in ("ready", "assigned"):
        _run(project, "--set-module-status", "--module-id", downstream["id"], "--status", status, "--json")

    result = _run(project, "--set-module-status", "--module-id", downstream["id"], "--status", "producing", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
    assert "unresolved dependencies" in data["message"]


def test_module_can_start_producing_once_dependency_passed(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    upstream = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "upstream", "--module-type", "architecture", "--json",
    ).stdout)
    downstream = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "downstream", "--module-type", "architecture",
        "--dependencies", upstream["id"], "--json",
    ).stdout)
    for status in ("ready", "assigned", "producing", "review_required", "passed"):
        _run(project, "--set-module-status", "--module-id", upstream["id"], "--status", status, "--json")
    for status in ("ready", "assigned"):
        _run(project, "--set-module-status", "--module-id", downstream["id"], "--status", status, "--json")

    result = _run(project, "--set-module-status", "--module-id", downstream["id"], "--status", "producing", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "producing"


def test_two_independent_modules_can_both_reach_producing(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    a = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "a", "--module-type", "data_visualization", "--json",
    ).stdout)
    b = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "b", "--module-type", "conceptual", "--json",
    ).stdout)

    for module_id in (a["id"], b["id"]):
        for status in ("ready", "assigned", "producing"):
            result = _run(project, "--set-module-status", "--module-id", module_id, "--status", status, "--json")
            assert result.returncode == 0, result.stderr

    assert json.loads(_run(project, "--set-module-status", "--module-id", a["id"], "--status", "producing", "--json").stderr or "{}") == {}


def test_record_review_returns_new_event(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    result = _run(
        project, "--record-review", "--subject-type", "deck", "--subject-id", deck_id,
        "--reviewer-role", "content_reviewer", "--status", "failed",
        "--findings-json", json.dumps([{"kind": "unsupported-claim", "description": "Slide 2 claims X without a citation"}]),
        "--round", "1", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("rev_")
    assert data["subject_type"] == "deck"
    assert data["subject_id"] == deck_id
    assert data["status"] == "failed"
    assert data["findings"][0]["kind"] == "unsupported-claim"
    assert data["round"] == 1


def test_record_review_invalid_subject_type_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    result = _run(
        project, "--record-review", "--subject-type", "not-a-real-type", "--subject-id", deck_id,
        "--reviewer-role", "content_reviewer", "--status", "passed", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_record_review_invalid_status_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    result = _run(
        project, "--record-review", "--subject-type", "deck", "--subject-id", deck_id,
        "--reviewer-role", "content_reviewer", "--status", "not-a-real-status", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_record_review_unknown_subject_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(
        project, "--record-review", "--subject-type", "slide", "--subject-id", "sld_does_not_exist",
        "--reviewer-role", "content_reviewer", "--status", "passed", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "SlideNotFoundError"


def test_create_revision_request_returns_new_record(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    result = _run(
        project, "--create-revision-request", "--subject-type", "deck", "--subject-id", deck_id,
        "--requested-by", "user", "--instructions", "Shorten the introduction slide.", "--json",
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"].startswith("rvq_")
    assert data["requested_by"] == "user"
    assert data["instructions"] == "Shorten the introduction slide."
    assert data["supersedes"] is None


def test_create_revision_request_supersedes_marks_prior_slide_superseded(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    for status in ("ready", "assigned", "producing", "review_required", "passed"):
        _run(project, "--set-slide-status", "--slide-id", slide_id, "--status", status, "--json")

    result = _run(
        project, "--create-revision-request", "--subject-type", "slide", "--subject-id", slide_id,
        "--requested-by", "reviewer", "--instructions", "Re-run with corrected data.",
        "--supersedes", slide_id, "--json",
    )

    assert result.returncode == 0, result.stderr
    updated = json.loads(_run(project, "--set-slide-status", "--slide-id", slide_id, "--status", "blocked", "--json").stdout)
    # blocked is legal from every active status but NOT from "superseded" --
    # if this now succeeds, the slide was never actually marked superseded.
    assert updated["status"] == "blocked"


def test_create_revision_request_invalid_requested_by_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)

    result = _run(
        project, "--create-revision-request", "--subject-type", "deck", "--subject-id", deck_id,
        "--requested-by", "not-a-real-requester", "--instructions", "X", "--json",
    )

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"
```

Note on `test_create_revision_request_supersedes_marks_prior_slide_superseded`: this asserts indirectly (a `superseded` slide cannot transition to `blocked`, since `superseded` is a terminal state with no outgoing transitions in `_PRODUCTION_UNIT_TRANSITIONS` — if the assertion holds, the slide was *not* superseded, which is the bug this test is designed to catch; if the implementation is correct, this call itself will error with `SlideNotFoundError`-shaped... no — it will return a `ValueError` "Illegal slide transition" response, not a 200, so the test as written checks the wrong thing). **Implementer: replace this test's final two lines with a direct check instead** — after creating the revision request, call `--set-slide-status --slide-id <slide_id> --status blocked` and assert `result.returncode == 1` and `json.loads(result.stdout)["error"] == "ValueError"` (proving the slide is now `superseded`, from which `blocked` is not a legal transition). Use this corrected assertion when writing the test.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_state.py -k "visual_module or record_review or revision_request" -v`
Expected: FAIL/ERROR on every new test.

- [ ] **Step 3: Implement `presentation_state.py` additions**

Add the new path constant right after `REVISION_REQUESTS_RELATIVE_PATH = Path(".research/presentations/state/revision_requests.yaml")` is already present from Task 1 — actually add `_MODULE_TYPES` right after `_PRODUCTION_UNIT_STATUSES = frozenset(_PRODUCTION_UNIT_TRANSITIONS.keys())`:

```python
_MODULE_TYPES = frozenset({"data_visualization", "architecture", "conceptual", "annotation"})
_REVIEW_SUBJECT_TYPES = frozenset({"plan", "module", "slide", "deck"})
_REVIEW_STATUSES = frozenset({"passed", "failed", "blocked"})
_REVISION_REQUESTERS = frozenset({"user", "reviewer"})
```

Add the new exception classes right after `class SlideNotFoundError(ValueError):` block:

```python
class VisualModuleNotFoundError(ValueError):
    """Raised when a module_id does not exist in state/visual_modules.yaml."""
```

Add the following functions right after `set_slide_status` (i.e. right before `def _build_parser`):

```python
def load_visual_modules(project_root: Path) -> Dict[str, Any]:
    """Load all Visual Module records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Visual Module record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / VISUAL_MODULES_RELATIVE_PATH, "visual_modules")


def create_visual_module(
    project_root: Path,
    slide_id: str,
    module_key: str,
    module_type: str,
    dependencies: Optional[list] = None,
    created_by: str = "user",
) -> Dict[str, Any]:
    """Create a new Visual Module record with status "planned".

    Args:
        project_root: The project's root directory.
        slide_id: The Slide this module belongs to; must already exist.
        module_key: The module's id from its Complex Visual Specification
            (e.g. "observation-input") -- distinct from this record's own
            generated "id", kept for cross-reference with the spec.
        module_type: Must be one of "data_visualization", "architecture",
            "conceptual", "annotation".
        dependencies: Ids (this store's generated "id", not module_key) of
            other Visual Modules that must reach "passed" before this one
            may enter "producing". Each must already exist.
        created_by: Name of the skill/agent creating this module, or "user".

    Returns:
        The full new Visual Module record, including its generated "id".

    Raises:
        ValueError: If module_key is empty/missing, or module_type is not
            one of the four allowed values.
        SlideNotFoundError: If slide_id doesn't exist.
        VisualModuleNotFoundError: If any id in dependencies doesn't exist.
    """
    if not module_key:
        raise ValueError("module_key is required")
    if module_type not in _MODULE_TYPES:
        raise ValueError(f"module_type must be one of {sorted(_MODULE_TYPES)}, got {module_type!r}")
    if slide_id not in load_slides(project_root):
        raise SlideNotFoundError(f"Unknown slide_id: {slide_id}")
    dependencies = list(dependencies or [])
    existing_modules = load_visual_modules(project_root)
    for dep_id in dependencies:
        if dep_id not in existing_modules:
            raise VisualModuleNotFoundError(f"Unknown dependency module id: {dep_id}")
    path = project_root / VISUAL_MODULES_RELATIVE_PATH
    with _locked_file(project_root, path):
        modules = _load_yaml_map(path, "visual_modules")
        module_id = generate_id("mod")
        now = _utc_now_iso()
        record = {
            "id": module_id, "slide_id": slide_id, "module_key": module_key,
            "module_type": module_type, "dependencies": dependencies, "status": "planned",
            "created_at": now, "updated_at": now, "created_by": created_by,
        }
        modules[module_id] = record
        _save_yaml_map(path, "visual_modules", modules)
    return record


def set_module_status(project_root: Path, module_id: str, status: str) -> Dict[str, Any]:
    """Transition a Visual Module's production status.

    Entering "producing" additionally requires every id in this module's
    "dependencies" to already be "passed" -- the mechanism that lets
    independent modules run in parallel while a module with an unresolved
    dependency stays blocked from starting.

    Args:
        project_root: The project's root directory.
        module_id: The Visual Module to update.
        status: New status; must be a legal transition from the module's
            current status per the shared production-unit state machine.

    Returns:
        The updated Visual Module record.

    Raises:
        VisualModuleNotFoundError: If module_id doesn't exist.
        ValueError: If status is unrecognized, not a legal transition
            from the current status, or is "producing" while an
            unresolved dependency remains.
    """
    if status not in _PRODUCTION_UNIT_STATUSES:
        raise ValueError(f"Unrecognized module status: {status!r}")
    path = project_root / VISUAL_MODULES_RELATIVE_PATH
    with _locked_file(project_root, path):
        modules = _load_yaml_map(path, "visual_modules")
        if module_id not in modules:
            raise VisualModuleNotFoundError(f"Unknown module_id: {module_id}")
        record = modules[module_id]
        current = record["status"]
        if status not in _PRODUCTION_UNIT_TRANSITIONS[current]:
            raise ValueError(
                f"Illegal module transition: {current!r} -> {status!r} "
                f"(allowed from {current!r}: {sorted(_PRODUCTION_UNIT_TRANSITIONS[current])})"
            )
        if status == "producing":
            unresolved = [
                dep_id for dep_id in record["dependencies"]
                if modules.get(dep_id, {}).get("status") != "passed"
            ]
            if unresolved:
                raise ValueError(f"Cannot enter 'producing': unresolved dependencies {unresolved}")
        record["status"] = status
        record["updated_at"] = _utc_now_iso()
        _save_yaml_map(path, "visual_modules", modules)
        return record


def _events_shard_path(project_root: Path, when: datetime) -> Path:
    """Return today's (or `when`'s) events shard path.

    Args:
        project_root: The project's root directory.
        when: The UTC datetime to shard by (date component only).

    Returns:
        Path to .research/presentations/events/YYYY-MM-DD.jsonl.
    """
    return project_root / EVENTS_RELATIVE_DIR / f"{when:%Y-%m-%d}.jsonl"


def _append_event(project_root: Path, event: Dict[str, Any]) -> None:
    """Append one JSON event line to today's shard, under its own lock.

    Args:
        project_root: The project's root directory.
        event: The event dict to append (already fully built).
    """
    shard_path = _events_shard_path(project_root, datetime.now(timezone.utc))
    with _locked_file(project_root, shard_path):
        shard_path.parent.mkdir(parents=True, exist_ok=True)
        with shard_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")


def record_review(
    project_root: Path,
    subject_type: str,
    subject_id: str,
    reviewer_role: str,
    status: str,
    findings: Optional[list] = None,
    round_number: int = 1,
) -> Dict[str, Any]:
    """Append a Review Result event.

    Args:
        project_root: The project's root directory.
        subject_type: Must be one of "plan", "module", "slide", "deck".
        subject_id: The id of the reviewed record. "plan" and "deck" are
            both validated against Deck records (a plan is embedded in
            its Deck, with no separate store record of its own).
        reviewer_role: Free-text reviewer identity, e.g.
            "content_reviewer", "scientific_visual_reviewer".
        status: Must be one of "passed", "failed", "blocked".
        findings: Optional list of finding dicts; stored as given, not
            schema-validated here (that is validate_deck_plan.py's /
            validate_visual_module.py's job at the contract layer).
        round_number: Which review round this is for the subject (1-based).

    Returns:
        The full Review Result event, including its generated "id" and "ts".

    Raises:
        ValueError: If subject_type/status is not one of the allowed
            values, or round_number is not a positive int.
        DeckNotFoundError: If subject_type is "plan"/"deck" and
            subject_id doesn't exist.
        SlideNotFoundError: If subject_type is "slide" and subject_id
            doesn't exist.
        VisualModuleNotFoundError: If subject_type is "module" and
            subject_id doesn't exist.
    """
    if subject_type not in _REVIEW_SUBJECT_TYPES:
        raise ValueError(f"subject_type must be one of {sorted(_REVIEW_SUBJECT_TYPES)}, got {subject_type!r}")
    if status not in _REVIEW_STATUSES:
        raise ValueError(f"status must be one of {sorted(_REVIEW_STATUSES)}, got {status!r}")
    if round_number < 1:
        raise ValueError("round_number must be a positive integer")
    if subject_type in ("plan", "deck"):
        if subject_id not in load_decks(project_root):
            raise DeckNotFoundError(f"Unknown deck_id: {subject_id}")
    elif subject_type == "slide":
        if subject_id not in load_slides(project_root):
            raise SlideNotFoundError(f"Unknown slide_id: {subject_id}")
    else:
        if subject_id not in load_visual_modules(project_root):
            raise VisualModuleNotFoundError(f"Unknown module_id: {subject_id}")
    event: Dict[str, Any] = {
        "event": "review_result", "id": generate_id("rev"), "subject_type": subject_type,
        "subject_id": subject_id, "reviewer_role": reviewer_role, "status": status,
        "findings": findings or [], "round": round_number, "ts": _utc_now_iso(),
    }
    _append_event(project_root, event)
    return event


def load_revision_requests(project_root: Path) -> Dict[str, Any]:
    """Load all Revision Request records.

    Args:
        project_root: The project's root directory.

    Returns:
        id -> Revision Request record map (empty if none exist yet).
    """
    return _load_yaml_map(project_root / REVISION_REQUESTS_RELATIVE_PATH, "revision_requests")


def create_revision_request(
    project_root: Path,
    subject_type: str,
    subject_id: str,
    requested_by: str,
    instructions: str,
    supersedes: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new Revision Request record.

    Args:
        project_root: The project's root directory.
        subject_type: Must be one of "plan", "module", "slide", "deck".
        subject_id: The id of the record the revision targets; existence
            checked the same way as record_review's subject_id.
        requested_by: Must be "user" or "reviewer".
        instructions: Free-text description of the requested change.
        supersedes: Optional id of a prior Slide or Visual Module this
            revision replaces; if given and it currently exists as a
            Slide or Visual Module, that record is marked "superseded" as
            part of this same call.

    Returns:
        The full new Revision Request record, including its generated "id".

    Raises:
        ValueError: If subject_type/requested_by is not one of the
            allowed values, or instructions is empty/missing.
        DeckNotFoundError: If subject_type is "plan"/"deck" and
            subject_id doesn't exist.
        SlideNotFoundError: If subject_type is "slide" and subject_id
            doesn't exist.
        VisualModuleNotFoundError: If subject_type is "module" and
            subject_id doesn't exist.
    """
    if subject_type not in _REVIEW_SUBJECT_TYPES:
        raise ValueError(f"subject_type must be one of {sorted(_REVIEW_SUBJECT_TYPES)}, got {subject_type!r}")
    if requested_by not in _REVISION_REQUESTERS:
        raise ValueError(f"requested_by must be one of {sorted(_REVISION_REQUESTERS)}, got {requested_by!r}")
    if not instructions:
        raise ValueError("instructions is required")
    if subject_type in ("plan", "deck"):
        if subject_id not in load_decks(project_root):
            raise DeckNotFoundError(f"Unknown deck_id: {subject_id}")
    elif subject_type == "slide":
        if subject_id not in load_slides(project_root):
            raise SlideNotFoundError(f"Unknown slide_id: {subject_id}")
    else:
        if subject_id not in load_visual_modules(project_root):
            raise VisualModuleNotFoundError(f"Unknown module_id: {subject_id}")
    path = project_root / REVISION_REQUESTS_RELATIVE_PATH
    with _locked_file(project_root, path):
        requests = _load_yaml_map(path, "revision_requests")
        request_id = generate_id("rvq")
        record = {
            "id": request_id, "subject_type": subject_type, "subject_id": subject_id,
            "requested_by": requested_by, "instructions": instructions,
            "supersedes": supersedes, "created_at": _utc_now_iso(),
        }
        requests[request_id] = record
        _save_yaml_map(path, "revision_requests", requests)
    if supersedes:
        if subject_type == "slide" and supersedes in load_slides(project_root):
            set_slide_status(project_root, supersedes, "superseded")
        elif subject_type == "module" and supersedes in load_visual_modules(project_root):
            set_module_status(project_root, supersedes, "superseded")
    return record
```

In `_build_parser`, add the four new actions to the mutually exclusive group, right after `action.add_argument("--set-slide-status", action="store_true")`:

```python
    action.add_argument("--create-visual-module", action="store_true")
    action.add_argument("--set-module-status", action="store_true")
    action.add_argument("--record-review", action="store_true")
    action.add_argument("--create-revision-request", action="store_true")
```

Add the new value flags right after `parser.add_argument("--plan-slide-id", metavar="ID")` and before `parser.add_argument("--status", metavar="STATUS")`:

```python
    parser.add_argument("--module-id", metavar="ID")
    parser.add_argument("--module-key", metavar="ID")
    parser.add_argument("--module-type", metavar="TYPE")
    parser.add_argument("--dependencies", metavar="ID", nargs="*", default=[])
    parser.add_argument("--subject-type", metavar="TYPE")
    parser.add_argument("--subject-id", metavar="ID")
    parser.add_argument("--reviewer-role", metavar="NAME")
    parser.add_argument("--findings-json", metavar="JSON")
    parser.add_argument("--round", type=int, default=1, metavar="N")
    parser.add_argument("--requested-by", metavar="WHO")
    parser.add_argument("--instructions", metavar="TEXT")
    parser.add_argument("--supersedes", metavar="ID")
```

In `_dispatch`, add the four new branches right after the `if args.set_slide_status:` block and before `raise AssertionError(...)`:

```python
    if args.create_visual_module:
        return create_visual_module(
            project_root, args.slide_id, args.module_key, args.module_type,
            dependencies=args.dependencies, created_by=args.skill or "user",
        )
    if args.set_module_status:
        return set_module_status(project_root, args.module_id, args.status)
    if args.record_review:
        findings = json.loads(args.findings_json) if args.findings_json else None
        return record_review(
            project_root, args.subject_type, args.subject_id, args.reviewer_role,
            args.status, findings=findings, round_number=args.round,
        )
    if args.create_revision_request:
        return create_revision_request(
            project_root, args.subject_type, args.subject_id, args.requested_by,
            args.instructions, supersedes=args.supersedes,
        )
```

In `main`, add `VisualModuleNotFoundError` to the caught-exception tuple, right after `SlideNotFoundError,`:

```python
        VisualModuleNotFoundError,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_state.py -v`
Expected: all tests pass (15 from Task 1 + 14 new = 29), pristine output.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_state.py skills/report-slides/scripts/tests/test_presentation_state.py
git commit -m "feat(report-slides): add Visual Module, Review Result, and Revision Request to presentation_state.py"
```

---

### Task 3: Production gate, query, and referential-integrity validation

**Files:**
- Modify: `skills/report-slides/scripts/presentation_state.py`
- Modify: `skills/report-slides/scripts/tests/test_presentation_state.py`

**Interfaces:**
- Consumes: everything from Tasks 1-2.
- Produces: `ProductionNotAllowedError`, `_APPROVED_OR_LATER`, `assert_production_allowed`; `query`; `validate_referential_integrity`; new CLI actions `--check-production-allowed`, `--query`, `--validate`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/report-slides/scripts/tests/test_presentation_state.py`:

```python
def test_check_production_allowed_blocks_before_approved(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "content_review", "--json")
    _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", "awaiting_approval", "--json")

    result = _run(project, "--check-production-allowed", "--deck-id", deck["id"], "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProductionNotAllowedError"


def test_check_production_allowed_passes_at_approved(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck = json.loads(_run(project, "--create-deck", "--title", "T", "--json").stdout)
    for status in ("content_review", "awaiting_approval", "approved"):
        _run(project, "--set-deck-status", "--deck-id", deck["id"], "--status", status, "--json")

    result = _run(project, "--check-production-allowed", "--deck-id", deck["id"], "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "approved"


def test_check_production_allowed_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--check-production-allowed", "--deck-id", "deck_does_not_exist", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "DeckNotFoundError"


def test_query_returns_deck_with_slides_modules_and_revisions(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, slide_id = _make_deck_and_slide(project)
    module = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "m1", "--module-type", "architecture", "--json",
    ).stdout)
    _run(
        project, "--create-revision-request", "--subject-type", "slide", "--subject-id", slide_id,
        "--requested-by", "user", "--instructions", "Shorten.", "--json",
    )

    result = _run(project, "--query", "--deck-id", deck_id, "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["deck"]["id"] == deck_id
    assert [s["id"] for s in data["slides"]] == [slide_id]
    assert [m["id"] for m in data["visual_modules"]] == [module["id"]]
    assert len(data["revision_requests"]) == 1


def test_query_unknown_deck_id_errors(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    result = _run(project, "--query", "--deck-id", "deck_does_not_exist", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "DeckNotFoundError"


def test_query_after_reinvocation_reflects_durable_state_with_no_duplicates(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, slide_id = _make_deck_and_slide(project)
    _run(project, "--set-slide-status", "--slide-id", slide_id, "--status", "ready", "--json")

    # Simulate resuming an interrupted workflow: a brand-new process
    # re-queries the same deck_id with no in-memory state carried over.
    first = json.loads(_run(project, "--query", "--deck-id", deck_id, "--json").stdout)
    second = json.loads(_run(project, "--query", "--deck-id", deck_id, "--json").stdout)

    assert first == second
    assert len(second["slides"]) == 1
    assert second["slides"][0]["status"] == "ready"


def test_validate_on_clean_project_reports_no_violations(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _make_deck_and_slide(project)

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"violations": [], "clean": True}


def test_validate_catches_dangling_slide_deck_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    slides_path = project / ".research" / "presentations" / "state" / "slides.yaml"
    doc = yaml.safe_load(slides_path.read_text())
    doc["slides"][slide_id]["deck_id"] = "deck_does_not_exist"
    slides_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {"entity": "slide", "id": slide_id, "field": "deck_id", "missing_id": "deck_does_not_exist"} in data["violations"]


def test_validate_catches_dangling_module_slide_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _, slide_id = _make_deck_and_slide(project)
    module = json.loads(_run(
        project, "--create-visual-module", "--slide-id", slide_id,
        "--module-key", "m1", "--module-type", "architecture", "--json",
    ).stdout)
    modules_path = project / ".research" / "presentations" / "state" / "visual_modules.yaml"
    doc = yaml.safe_load(modules_path.read_text())
    doc["visual_modules"][module["id"]]["slide_id"] = "sld_does_not_exist"
    modules_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {"entity": "visual_module", "id": module["id"], "field": "slide_id", "missing_id": "sld_does_not_exist"} in data["violations"]


def test_validate_catches_dangling_revision_subject_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    deck_id, _ = _make_deck_and_slide(project)
    request = json.loads(_run(
        project, "--create-revision-request", "--subject-type", "deck", "--subject-id", deck_id,
        "--requested-by", "user", "--instructions", "X", "--json",
    ).stdout)
    requests_path = project / ".research" / "presentations" / "state" / "revision_requests.yaml"
    doc = yaml.safe_load(requests_path.read_text())
    doc["revision_requests"][request["id"]]["subject_id"] = "deck_does_not_exist"
    requests_path.write_text(yaml.safe_dump(doc, sort_keys=True))

    result = _run(project, "--validate", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clean"] is False
    assert {"entity": "revision_request", "id": request["id"], "field": "subject_id", "missing_id": "deck_does_not_exist"} in data["violations"]
```

Add `import yaml` to the top of `test_presentation_state.py` (needed by the hand-editing tests above) — the existing imports at the top of the file (`json, subprocess, sys, Path, pytest`) need `import yaml` added alongside them.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_state.py -k "production_allowed or query or validate" -v`
Expected: FAIL/ERROR on every new test.

- [ ] **Step 3: Implement `presentation_state.py` additions**

Add the new exception and constant right after `class VisualModuleNotFoundError(ValueError):` block:

```python
class ProductionNotAllowedError(RuntimeError):
    """Raised when a production-guarded action is attempted before a Deck
    reaches "approved" or a later status."""


_APPROVED_OR_LATER = frozenset({"approved", "producing", "draft_review", "revising", "validating", "completed"})
```

Add the following functions right after `create_revision_request` (i.e. right before `def _build_parser`):

```python
def assert_production_allowed(project_root: Path, deck_id: str) -> Dict[str, Any]:
    """Guard used by every artifact-producing script before it writes
    anything -- the mechanism that makes "no presentation artifact before
    plan approval" a real, deterministic guarantee rather than a prose
    instruction.

    Args:
        project_root: The project's root directory.
        deck_id: The Deck the artifact belongs to.

    Returns:
        The Deck record, if production is currently allowed.

    Raises:
        DeckNotFoundError: If deck_id doesn't exist.
        ProductionNotAllowedError: If the Deck's status is earlier than
            "approved".
    """
    decks = load_decks(project_root)
    if deck_id not in decks:
        raise DeckNotFoundError(f"Unknown deck_id: {deck_id}")
    record = decks[deck_id]
    if record["status"] not in _APPROVED_OR_LATER:
        raise ProductionNotAllowedError(
            f"Deck {deck_id} is at status {record['status']!r}; no presentation "
            "artifact may be produced before it reaches 'approved'."
        )
    return record


def query(project_root: Path, deck_id: str) -> Dict[str, Any]:
    """Return a Deck plus every Slide, Visual Module, and Revision
    Request linked to it.

    This is the single read path used both for normal inspection and for
    resuming an interrupted workflow: the returned status is always the
    last durably-written state, never inferred or replayed from a log.

    Args:
        project_root: The project's root directory.
        deck_id: The Deck to look up.

    Returns:
        {"deck": {...}, "slides": [...], "visual_modules": [...],
        "revision_requests": [...]}, each list ordered by created_at.

    Raises:
        DeckNotFoundError: If deck_id doesn't exist.
    """
    decks = load_decks(project_root)
    if deck_id not in decks:
        raise DeckNotFoundError(f"Unknown deck_id: {deck_id}")
    slides = [s for s in load_slides(project_root).values() if s["deck_id"] == deck_id]
    slide_ids = {s["id"] for s in slides}
    modules = [m for m in load_visual_modules(project_root).values() if m["slide_id"] in slide_ids]
    module_ids = {m["id"] for m in modules}
    revisions = [
        r for r in load_revision_requests(project_root).values()
        if r["subject_id"] == deck_id or r["subject_id"] in slide_ids or r["subject_id"] in module_ids
    ]
    return {
        "deck": decks[deck_id],
        "slides": sorted(slides, key=lambda s: s["created_at"]),
        "visual_modules": sorted(modules, key=lambda m: m["created_at"]),
        "revision_requests": sorted(revisions, key=lambda r: r["created_at"]),
    }


def validate_referential_integrity(project_root: Path) -> list:
    """Scan state/*.yaml for dangling foreign keys.

    Diagnostic pass over hand-authored/hand-edited data -- every write
    path in this module already rejects a dangling reference at write
    time, so a clean project should always report zero violations.

    Args:
        project_root: The project's root directory.

    Returns:
        A list of violation dicts, each shaped {"entity", "id", "field",
        "missing_id"}. Empty if nothing is broken.
    """
    decks = load_decks(project_root)
    slides = load_slides(project_root)
    modules = load_visual_modules(project_root)
    revisions = load_revision_requests(project_root)

    violations: list = []
    for slide_id, slide in slides.items():
        deck_id = slide.get("deck_id")
        if deck_id not in decks:
            violations.append({"entity": "slide", "id": slide_id, "field": "deck_id", "missing_id": deck_id})
    for module_id, module in modules.items():
        slide_id = module.get("slide_id")
        if slide_id not in slides:
            violations.append({"entity": "visual_module", "id": module_id, "field": "slide_id", "missing_id": slide_id})
        for dep_id in module.get("dependencies", []):
            if dep_id not in modules:
                violations.append({"entity": "visual_module", "id": module_id, "field": "dependencies", "missing_id": dep_id})
    known_ids = set(decks) | set(slides) | set(modules)
    for request_id, request in revisions.items():
        subject_id = request.get("subject_id")
        if subject_id not in known_ids:
            violations.append({"entity": "revision_request", "id": request_id, "field": "subject_id", "missing_id": subject_id})
    return violations
```

In `_build_parser`, add the three new actions to the mutually exclusive group, right after `action.add_argument("--create-revision-request", action="store_true")`:

```python
    action.add_argument("--check-production-allowed", action="store_true")
    action.add_argument("--query", action="store_true")
    action.add_argument("--validate", action="store_true")
```

In `_dispatch`, add the three new branches right after the `if args.create_revision_request:` block and before `raise AssertionError(...)`:

```python
    if args.check_production_allowed:
        return assert_production_allowed(project_root, args.deck_id)
    if args.query:
        return query(project_root, args.deck_id)
    if args.validate:
        violations = validate_referential_integrity(project_root)
        return {"violations": violations, "clean": len(violations) == 0}
```

In `main`, add `ProductionNotAllowedError` to the caught-exception tuple, right after `VisualModuleNotFoundError,`:

```python
        ProductionNotAllowedError,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_state.py -v`
Expected: all tests pass (29 from Tasks 1-2 + 11 new = 40), pristine output.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_state.py skills/report-slides/scripts/tests/test_presentation_state.py
git commit -m "feat(report-slides): add production gate, query, and --validate to presentation_state.py"
```

---

### Task 4: `validate_deck_plan.py` — Deck Plan / SlidePlanEntry / Deck Approval contracts

**Files:**
- Create: `skills/report-slides/scripts/validate_deck_plan.py`
- Test: `skills/report-slides/scripts/tests/test_validate_deck_plan.py`

**Interfaces:**
- Produces: `validate_slide_plan_entry`, `validate_deck_plan`, `validate_deck_approval`, CLI (`--plan PATH | --approval PATH`).

- [ ] **Step 1: Write the failing tests**

Create `skills/report-slides/scripts/tests/test_validate_deck_plan.py`:

```python
"""Tests for validate_deck_plan.py."""
import json
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parent.parent / "validate_deck_plan.py"

_VALID_SLIDE = {
    "slide_id": "slide-01",
    "title": "Action conditioning improves command sensitivity",
    "purpose": "Establish the core result",
    "key_takeaway": "Conditioning on action improves sensitivity by 2x",
    "evidence_refs": ["log-2026-08-01#experiment-3"],
    "intended_visual_type": "data",
    "visual_rationale": "A bar chart best shows the magnitude of improvement",
    "speaker_message": "This is our headline finding",
    "dependencies": [],
    "open_questions": [],
}

_VALID_PLAN = {
    "deck_id": "deck-q3-results",
    "purpose": "Report Q3 experiment results to the research team",
    "audience": "internal research team",
    "estimated_duration_minutes": 15,
    "slides": [_VALID_SLIDE],
    "excluded_content": ["Unrelated Q2 baseline data"],
    "known_gaps": ["Long-horizon rollout stability not yet measured"],
}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_valid_plan_passes(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(_VALID_PLAN))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 0, result.stdout
    data = json.loads(result.stdout)
    assert data == {"valid": True, "errors": []}


def test_plan_missing_purpose_fails(tmp_path: Path) -> None:
    plan = {**_VALID_PLAN}
    del plan["purpose"]
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["valid"] is False
    assert any("purpose" in err for err in data["errors"])


def test_plan_empty_slides_list_fails(tmp_path: Path) -> None:
    plan = {**_VALID_PLAN, "slides": []}
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("slides" in err for err in data["errors"])


def test_plan_duplicate_slide_id_fails(tmp_path: Path) -> None:
    plan = {**_VALID_PLAN, "slides": [_VALID_SLIDE, {**_VALID_SLIDE}]}
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("duplicate slide_id" in err for err in data["errors"])


def test_plan_invalid_visual_type_fails(tmp_path: Path) -> None:
    bad_slide = {**_VALID_SLIDE, "intended_visual_type": "not-a-real-route"}
    plan = {**_VALID_PLAN, "slides": [bad_slide]}
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("intended_visual_type" in err for err in data["errors"])


def test_plan_slide_missing_key_takeaway_fails(tmp_path: Path) -> None:
    bad_slide = {k: v for k, v in _VALID_SLIDE.items() if k != "key_takeaway"}
    plan = {**_VALID_PLAN, "slides": [bad_slide]}
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("key_takeaway" in err for err in data["errors"])


def test_valid_approval_approve_passes(tmp_path: Path) -> None:
    approval = {"deck_id": "deck-q3-results", "plan_version": 1, "decision": "approve", "approved_by": "user"}
    approval_path = tmp_path / "approval.yaml"
    approval_path.write_text(yaml.safe_dump(approval))

    result = _run("--approval", str(approval_path), "--json")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_valid_approval_revise_requires_revisions_requested(tmp_path: Path) -> None:
    approval = {"deck_id": "deck-q3-results", "decision": "revise", "approved_by": "user"}
    approval_path = tmp_path / "approval.yaml"
    approval_path.write_text(yaml.safe_dump(approval))

    result = _run("--approval", str(approval_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("revisions_requested" in err for err in data["errors"])


def test_approval_invalid_decision_fails(tmp_path: Path) -> None:
    approval = {"deck_id": "deck-q3-results", "decision": "maybe", "approved_by": "user"}
    approval_path = tmp_path / "approval.yaml"
    approval_path.write_text(yaml.safe_dump(approval))

    result = _run("--approval", str(approval_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("decision" in err for err in data["errors"])


def test_malformed_yaml_reports_error(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("deck_id: [unterminated")

    result = _run("--plan", str(plan_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["valid"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_deck_plan.py -v`
Expected: FAIL/ERROR on every test (`validate_deck_plan.py` doesn't exist yet).

- [ ] **Step 3: Implement `validate_deck_plan.py`**

Create `skills/report-slides/scripts/validate_deck_plan.py`:

```python
#!/usr/bin/env python3
"""validate_deck_plan.py -- Schema validator for the Deck Plan (with its
embedded SlidePlanEntry list) and Deck Approval contracts, used at
Stages 3-5 of the report-slides multi-agent workflow.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

_VISUAL_TYPES = frozenset({"native", "data", "generative", "hybrid", "none"})
_DECK_APPROVAL_DECISIONS = frozenset({"approve", "revise"})


def _load_document(path: Path) -> Any:
    """Load a YAML or JSON document by file extension.

    Args:
        path: Path to a .yaml/.yml or .json file.

    Returns:
        The parsed document.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


def validate_slide_plan_entry(entry: Any, index: int) -> List[str]:
    """Validate one SlidePlanEntry embedded in a Deck Plan.

    Args:
        entry: The parsed entry mapping.
        index: Its position in the plan's "slides" list, used to prefix
            error messages so multiple bad entries are all reported.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    prefix = f"slides[{index}]"
    if not isinstance(entry, dict):
        return [f"{prefix}: must be a mapping"]
    for field in (
        "slide_id", "title", "purpose", "key_takeaway",
        "intended_visual_type", "visual_rationale", "speaker_message",
    ):
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}.{field}: required non-empty string")
    if not isinstance(entry.get("evidence_refs"), list):
        errors.append(f"{prefix}.evidence_refs: required list")
    for key in ("dependencies", "open_questions"):
        if key in entry and not isinstance(entry[key], list):
            errors.append(f"{prefix}.{key}: must be a list if present")
    visual_type = entry.get("intended_visual_type")
    if isinstance(visual_type, str) and visual_type not in _VISUAL_TYPES:
        errors.append(f"{prefix}.intended_visual_type: must be one of {sorted(_VISUAL_TYPES)}, got {visual_type!r}")
    return errors


def validate_deck_plan(doc: Any) -> List[str]:
    """Validate a full Deck Plan document.

    Args:
        doc: The parsed Deck Plan mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]
    for field in ("deck_id", "purpose", "audience"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")
    duration = doc.get("estimated_duration_minutes")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        errors.append("estimated_duration_minutes: required positive number")
    slides = doc.get("slides")
    if not isinstance(slides, list) or not slides:
        errors.append("slides: required non-empty list")
    else:
        seen_ids: set = set()
        for i, entry in enumerate(slides):
            errors.extend(validate_slide_plan_entry(entry, i))
            slide_id = entry.get("slide_id") if isinstance(entry, dict) else None
            if slide_id:
                if slide_id in seen_ids:
                    errors.append(f"slides[{i}].slide_id: duplicate slide_id {slide_id!r}")
                seen_ids.add(slide_id)
    for field in ("excluded_content", "known_gaps"):
        if field in doc and not isinstance(doc[field], list):
            errors.append(f"{field}: must be a list if present")
    return errors


def validate_deck_approval(doc: Any) -> List[str]:
    """Validate a Deck Approval document.

    Args:
        doc: The parsed Deck Approval mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]
    for field in ("deck_id", "approved_by"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")
    decision = doc.get("decision")
    if decision not in _DECK_APPROVAL_DECISIONS:
        errors.append(f"decision: must be one of {sorted(_DECK_APPROVAL_DECISIONS)}, got {decision!r}")
    if decision == "revise":
        revisions = doc.get("revisions_requested")
        if not isinstance(revisions, list) or not revisions:
            errors.append("revisions_requested: required non-empty list when decision is 'revise'")
    if "plan_version" in doc and not isinstance(doc["plan_version"], int):
        errors.append("plan_version: must be an int if present")
    return errors


def main() -> None:
    """CLI entry point for validate_deck_plan.py."""
    parser = argparse.ArgumentParser(description="Validate Deck Plan / Deck Approval documents for report-slides.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", metavar="PATH", type=Path)
    group.add_argument("--approval", metavar="PATH", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    target = args.plan or args.approval
    try:
        doc = _load_document(target)
    except (OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        errors = [f"failed to read/parse {target}: {exc}"]
    else:
        errors = validate_deck_plan(doc) if args.plan else validate_deck_approval(doc)

    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_deck_plan.py -v`
Expected: all 10 tests pass, pristine output.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/validate_deck_plan.py skills/report-slides/scripts/tests/test_validate_deck_plan.py
git commit -m "feat(report-slides): add validate_deck_plan.py for Deck Plan / Deck Approval contracts"
```

---

### Task 5: `validate_visual_module.py` and `complex_visual_detector.py`

**Files:**
- Create: `skills/report-slides/scripts/validate_visual_module.py`
- Create: `skills/report-slides/scripts/complex_visual_detector.py`
- Create: `skills/report-slides/references/complex_visual_thresholds.yaml`
- Test: `skills/report-slides/scripts/tests/test_validate_visual_module.py`
- Test: `skills/report-slides/scripts/tests/test_complex_visual_detector.py`

**Interfaces:**
- Produces: `validate_module_spec`, `validate_complex_visual_spec`, `validate_worker_assignment`, CLI (`--spec PATH | --assignment PATH`); `load_thresholds`, `requires_complex_workflow`, CLI (`--signals PATH [--thresholds PATH]`).

- [ ] **Step 1: Write the failing tests**

Create `skills/report-slides/scripts/tests/test_validate_visual_module.py`:

```python
"""Tests for validate_visual_module.py."""
import json
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parent.parent / "validate_visual_module.py"

_VALID_SPEC = {
    "visual_id": "model-architecture-01",
    "message": "Show how action conditioning affects latent-state prediction",
    "modules": [
        {
            "id": "observation-input", "purpose": "Represent visual observation input",
            "route": "native", "module_type": "architecture", "output_anchors": ["observation_embedding"],
        },
        {
            "id": "command-input", "purpose": "Represent velocity and angular-velocity commands",
            "route": "native", "module_type": "architecture", "output_anchors": ["command_embedding"],
        },
        {
            "id": "latent-dynamics", "purpose": "Represent action-conditioned latent transition",
            "route": "native", "module_type": "architecture",
            "input_anchors": ["observation_embedding", "command_embedding"],
            "output_anchors": ["predicted_latent"],
        },
    ],
    "connections": [
        {"from": "observation-input.observation_embedding", "to": "latent-dynamics.observation_embedding"},
        {"from": "command-input.command_embedding", "to": "latent-dynamics.command_embedding"},
    ],
    "layout": {"direction": "left-to-right", "hierarchy": ["inputs", "latent transition"]},
}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_valid_spec_passes(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(_VALID_SPEC))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_spec_missing_modules_fails(tmp_path: Path) -> None:
    spec = {**_VALID_SPEC, "modules": []}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("modules" in err for err in data["errors"])


def test_spec_duplicate_module_id_fails(tmp_path: Path) -> None:
    spec = {**_VALID_SPEC, "modules": [_VALID_SPEC["modules"][0], {**_VALID_SPEC["modules"][0]}]}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("duplicate module id" in err for err in data["errors"])


def test_spec_connection_referencing_unknown_module_fails(tmp_path: Path) -> None:
    spec = {**_VALID_SPEC, "connections": [{"from": "nonexistent.out", "to": "latent-dynamics.observation_embedding"}]}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("does not reference a declared module" in err for err in data["errors"])


def test_spec_invalid_route_fails(tmp_path: Path) -> None:
    bad_module = {**_VALID_SPEC["modules"][0], "route": "not-a-real-route"}
    spec = {**_VALID_SPEC, "modules": [bad_module]}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any(".route:" in err for err in data["errors"])


def test_spec_invalid_module_type_fails(tmp_path: Path) -> None:
    bad_module = {**_VALID_SPEC["modules"][0], "module_type": "not-a-real-type"}
    spec = {**_VALID_SPEC, "modules": [bad_module]}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any(".module_type:" in err for err in data["errors"])


def test_spec_missing_layout_fails(tmp_path: Path) -> None:
    spec = {k: v for k, v in _VALID_SPEC.items() if k != "layout"}
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    result = _run("--spec", str(spec_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("layout" in err for err in data["errors"])


def test_valid_worker_assignment_passes(tmp_path: Path) -> None:
    assignment = {
        "module_id": "mod_20260806_ab12cd", "worker_type": "architecture",
        "assigned_at": "2026-08-06T00:00:00Z", "inputs_resolved": True, "blocker": None,
    }
    assignment_path = tmp_path / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump(assignment))

    result = _run("--assignment", str(assignment_path), "--json")

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout) == {"valid": True, "errors": []}


def test_worker_assignment_missing_inputs_resolved_fails(tmp_path: Path) -> None:
    assignment = {"module_id": "mod_20260806_ab12cd", "worker_type": "architecture", "assigned_at": "2026-08-06T00:00:00Z"}
    assignment_path = tmp_path / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump(assignment))

    result = _run("--assignment", str(assignment_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("inputs_resolved" in err for err in data["errors"])


def test_worker_assignment_invalid_worker_type_fails(tmp_path: Path) -> None:
    assignment = {
        "module_id": "mod_20260806_ab12cd", "worker_type": "not-a-real-worker",
        "assigned_at": "2026-08-06T00:00:00Z", "inputs_resolved": True,
    }
    assignment_path = tmp_path / "assignment.yaml"
    assignment_path.write_text(yaml.safe_dump(assignment))

    result = _run("--assignment", str(assignment_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any("worker_type" in err for err in data["errors"])
```

Create `skills/report-slides/scripts/tests/test_complex_visual_detector.py`:

```python
"""Tests for complex_visual_detector.py."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "complex_visual_detector.py"

_ALL_FALSE_SIGNALS = {
    "region_count": 2, "route_count": 1, "multi_stage": False, "mixed_technique": False,
    "heavy_cross_region_connections": False, "expected_reuse": False, "not_atomic": False,
}


def _write_thresholds(tmp_path: Path, region: int = 3, route: int = 1) -> Path:
    path = tmp_path / "thresholds.yaml"
    path.write_text(f"region_count_threshold: {region}\nroute_count_threshold: {route}\n")
    return path


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_all_signals_false_and_under_threshold_does_not_trigger(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps(_ALL_FALSE_SIGNALS))
    thresholds_path = _write_thresholds(tmp_path)

    result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"requires_complex_workflow": False, "triggered_signals": []}


def test_region_count_over_threshold_triggers(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps({**_ALL_FALSE_SIGNALS, "region_count": 4}))
    thresholds_path = _write_thresholds(tmp_path, region=3)

    result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

    data = json.loads(result.stdout)
    assert data["requires_complex_workflow"] is True
    assert "region_count" in data["triggered_signals"]


def test_route_count_over_threshold_triggers(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps({**_ALL_FALSE_SIGNALS, "route_count": 2}))
    thresholds_path = _write_thresholds(tmp_path, route=1)

    result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

    data = json.loads(result.stdout)
    assert data["requires_complex_workflow"] is True
    assert "route_count" in data["triggered_signals"]


def test_each_qualitative_signal_triggers_independently(tmp_path: Path) -> None:
    thresholds_path = _write_thresholds(tmp_path)
    for key in ("multi_stage", "mixed_technique", "heavy_cross_region_connections", "expected_reuse", "not_atomic"):
        signals_path = tmp_path / f"signals_{key}.json"
        signals_path.write_text(json.dumps({**_ALL_FALSE_SIGNALS, key: True}))

        result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

        data = json.loads(result.stdout)
        assert data["requires_complex_workflow"] is True, key
        assert key in data["triggered_signals"]


def test_missing_signal_key_raises(tmp_path: Path) -> None:
    incomplete = {k: v for k, v in _ALL_FALSE_SIGNALS.items() if k != "region_count"}
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps(incomplete))
    thresholds_path = _write_thresholds(tmp_path)

    result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

    assert result.returncode != 0


def test_default_thresholds_file_is_used_when_not_specified(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps(_ALL_FALSE_SIGNALS))

    result = _run("--signals", str(signals_path), "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"requires_complex_workflow": False, "triggered_signals": []}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_visual_module.py tests/test_complex_visual_detector.py -v`
Expected: FAIL/ERROR on every test.

- [ ] **Step 3: Implement `validate_visual_module.py`**

Create `skills/report-slides/scripts/validate_visual_module.py`:

```python
#!/usr/bin/env python3
"""validate_visual_module.py -- Schema validator for the Complex Visual
Specification (with its embedded ModuleSpec list) and Worker Assignment
contracts, used at Stages 7-9 of the report-slides multi-agent workflow.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

_ROUTES = frozenset({"native", "data", "generative", "hybrid"})
_MODULE_TYPES = frozenset({"data_visualization", "architecture", "conceptual", "annotation"})
_EDITABILITY = frozenset({"native", "hybrid", "raster"})


def _load_document(path: Path) -> Any:
    """Load a YAML or JSON document by file extension."""
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


def validate_module_spec(module: Any, index: int) -> List[str]:
    """Validate one ModuleSpec embedded in a Complex Visual Specification.

    Args:
        module: The parsed module mapping.
        index: Its position in the spec's "modules" list.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    prefix = f"modules[{index}]"
    if not isinstance(module, dict):
        return [f"{prefix}: must be a mapping"]
    for field in ("id", "purpose"):
        value = module.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}.{field}: required non-empty string")
    route = module.get("route")
    if route not in _ROUTES:
        errors.append(f"{prefix}.route: must be one of {sorted(_ROUTES)}, got {route!r}")
    module_type = module.get("module_type")
    if module_type not in _MODULE_TYPES:
        errors.append(f"{prefix}.module_type: must be one of {sorted(_MODULE_TYPES)}, got {module_type!r}")
    editability = module.get("editability")
    if editability is not None and editability not in _EDITABILITY:
        errors.append(f"{prefix}.editability: must be one of {sorted(_EDITABILITY)} if given, got {editability!r}")
    for key in ("input_anchors", "output_anchors", "dependencies"):
        if key in module and not isinstance(module[key], list):
            errors.append(f"{prefix}.{key}: must be a list if present")
    return errors


def validate_complex_visual_spec(doc: Any) -> List[str]:
    """Validate a full Complex Visual Specification document.

    Args:
        doc: The parsed Complex Visual Specification mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]
    for field in ("visual_id", "message"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")
    modules = doc.get("modules")
    module_ids: Set[str] = set()
    if not isinstance(modules, list) or not modules:
        errors.append("modules: required non-empty list")
    else:
        for i, module in enumerate(modules):
            errors.extend(validate_module_spec(module, i))
            module_id = module.get("id") if isinstance(module, dict) else None
            if module_id:
                if module_id in module_ids:
                    errors.append(f"modules[{i}].id: duplicate module id {module_id!r}")
                module_ids.add(module_id)
    connections = doc.get("connections", [])
    if not isinstance(connections, list):
        errors.append("connections: must be a list if present")
    else:
        for i, conn in enumerate(connections):
            if not isinstance(conn, dict) or "from" not in conn or "to" not in conn:
                errors.append(f"connections[{i}]: must be a mapping with 'from' and 'to'")
                continue
            for end in ("from", "to"):
                endpoint = conn[end]
                owner = endpoint.split(".", 1)[0] if isinstance(endpoint, str) else None
                if owner not in module_ids:
                    errors.append(f"connections[{i}].{end}: {endpoint!r} does not reference a declared module")
    layout = doc.get("layout")
    if not isinstance(layout, dict) or not layout.get("direction") or not isinstance(layout.get("hierarchy"), list):
        errors.append("layout: required mapping with 'direction' (str) and 'hierarchy' (list)")
    return errors


def validate_worker_assignment(doc: Any) -> List[str]:
    """Validate a Worker Assignment document.

    Args:
        doc: The parsed Worker Assignment mapping.

    Returns:
        A list of human-readable error strings; empty if valid.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["document must be a mapping"]
    for field in ("module_id", "worker_type", "assigned_at"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field}: required non-empty string")
    if doc.get("worker_type") not in _MODULE_TYPES:
        errors.append(f"worker_type: must be one of {sorted(_MODULE_TYPES)}, got {doc.get('worker_type')!r}")
    if not isinstance(doc.get("inputs_resolved"), bool):
        errors.append("inputs_resolved: required bool")
    if "blocker" in doc and doc["blocker"] is not None and not isinstance(doc["blocker"], str):
        errors.append("blocker: must be a string or null")
    return errors


def main() -> None:
    """CLI entry point for validate_visual_module.py."""
    parser = argparse.ArgumentParser(description="Validate Complex Visual Specification / Worker Assignment documents.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--spec", metavar="PATH", type=Path)
    group.add_argument("--assignment", metavar="PATH", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    target = args.spec or args.assignment
    try:
        doc = _load_document(target)
    except (OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        errors = [f"failed to read/parse {target}: {exc}"]
    else:
        errors = validate_complex_visual_spec(doc) if args.spec else validate_worker_assignment(doc)

    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create the thresholds config**

Create `skills/report-slides/references/complex_visual_thresholds.yaml`:

```yaml
# Configurable numeric thresholds for complex_visual_detector.py's
# region_count / route_count signals. The remaining detection signals
# (multi_stage, mixed_technique, heavy_cross_region_connections,
# expected_reuse, not_atomic) are inherently qualitative judgments the
# Slide Architect records as explicit booleans -- any true value triggers
# the complex-visual workflow regardless of these thresholds.
region_count_threshold: 3
route_count_threshold: 1
```

- [ ] **Step 5: Implement `complex_visual_detector.py`**

Create `skills/report-slides/scripts/complex_visual_detector.py`:

```python
#!/usr/bin/env python3
"""complex_visual_detector.py -- Deterministic decision on whether a
planned visual must enter the complex-visual decomposition workflow
(Stage 7), reading configurable numeric thresholds instead of hard-coding
them only in natural-language agent instructions.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "references" / "complex_visual_thresholds.yaml"
_QUALITATIVE_SIGNALS = (
    "multi_stage", "mixed_technique", "heavy_cross_region_connections", "expected_reuse", "not_atomic",
)


def load_thresholds(path: Path = DEFAULT_THRESHOLDS_PATH) -> Dict[str, int]:
    """Load the configurable numeric detection thresholds.

    Args:
        path: Path to the thresholds YAML file.

    Returns:
        {"region_count_threshold": int, "route_count_threshold": int}.

    Raises:
        ValueError: If a required key is missing or not an int.
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    thresholds = {}
    for key in ("region_count_threshold", "route_count_threshold"):
        value = doc.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path}: {key} must be an int, got {value!r}")
        thresholds[key] = value
    return thresholds


def requires_complex_workflow(signals: Dict[str, Any], thresholds: Dict[str, int]) -> Dict[str, Any]:
    """Decide whether a planned visual requires the complex-visual workflow.

    Args:
        signals: The Slide Architect's recorded complexity_signals --
            {"region_count": int, "route_count": int, "multi_stage": bool,
            "mixed_technique": bool, "heavy_cross_region_connections": bool,
            "expected_reuse": bool, "not_atomic": bool}.
        thresholds: {"region_count_threshold": int, "route_count_threshold": int}.

    Returns:
        {"requires_complex_workflow": bool, "triggered_signals": [str, ...]}.

    Raises:
        KeyError: If a required signal key is missing from `signals`.
    """
    triggered = []
    if signals["region_count"] > thresholds["region_count_threshold"]:
        triggered.append("region_count")
    if signals["route_count"] > thresholds["route_count_threshold"]:
        triggered.append("route_count")
    for key in _QUALITATIVE_SIGNALS:
        if signals[key]:
            triggered.append(key)
    return {"requires_complex_workflow": bool(triggered), "triggered_signals": triggered}


def main() -> None:
    """CLI entry point for complex_visual_detector.py."""
    parser = argparse.ArgumentParser(description="Decide whether a planned visual requires the complex-visual workflow.")
    parser.add_argument("--signals", metavar="PATH", type=Path, required=True)
    parser.add_argument("--thresholds", metavar="PATH", type=Path, default=DEFAULT_THRESHOLDS_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        signals = json.loads(args.signals.read_text(encoding="utf-8"))
        thresholds = load_thresholds(args.thresholds)
        result = requires_complex_workflow(signals, thresholds)
    except (KeyError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}) if args.json else f"Error: {exc}")
        sys.exit(1)

    print(json.dumps(result) if args.json else json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_visual_module.py tests/test_complex_visual_detector.py -v`
Expected: all 16 tests pass, pristine output.

- [ ] **Step 7: Commit**

```bash
git add skills/report-slides/scripts/validate_visual_module.py skills/report-slides/scripts/complex_visual_detector.py \
  skills/report-slides/references/complex_visual_thresholds.yaml \
  skills/report-slides/scripts/tests/test_validate_visual_module.py skills/report-slides/scripts/tests/test_complex_visual_detector.py
git commit -m "feat(report-slides): add Complex Visual Specification validator and configurable complexity detector"
```

---

### Task 6: `validate_pptx_structure.py` — real PPTX structural validation

**Files:**
- Create: `skills/report-slides/scripts/validate_pptx_structure.py`
- Test: `skills/report-slides/scripts/tests/test_validate_pptx_structure.py`

**Interfaces:**
- Produces: `PptxStructureError`, `validate_pptx_structure`, CLI (`--pptx PATH --expected-slides N [--declared-editability PATH]`).
- Note for the implementer: this task is less mechanical than the others in this plan (real OOXML zip/XML parsing, dependent on `python-pptx`'s internal part-naming conventions) — read the test fixtures carefully and verify each assertion empirically while implementing, not just by inspection.

- [ ] **Step 1: Write the failing tests**

Create `skills/report-slides/scripts/tests/test_validate_pptx_structure.py`:

```python
"""Tests for validate_pptx_structure.py."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

SCRIPT = Path(__file__).resolve().parent.parent / "validate_pptx_structure.py"


def _build_pptx(path: Path, n_slides: int, picture_path: Path = None) -> None:
    prs = Presentation()
    blank_layout = prs.slide_layouts[6]
    for i in range(n_slides):
        slide = prs.slides.add_slide(blank_layout)
        if picture_path is not None:
            slide.shapes.add_picture(str(picture_path), 0, 0, width=prs.slide_width, height=prs.slide_height)
        else:
            box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
            box.text_frame.text = f"Slide {i}"
    prs.save(str(path))


def _make_test_png(path: Path) -> Path:
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c48900000000a49444154789c630001000005000"
        "10d0a2db40000000049454e44ae426082"
    )
    path.write_bytes(png_bytes)
    return path


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_valid_native_pptx_passes(tmp_path: Path) -> None:
    pptx_path = tmp_path / "deck.pptx"
    _build_pptx(pptx_path, n_slides=3)

    result = _run("--pptx", str(pptx_path), "--expected-slides", "3", "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "passed"
    assert data["slide_count_actual"] == 3
    assert data["relationship_violations"] == []


def test_slide_count_mismatch_fails(tmp_path: Path) -> None:
    pptx_path = tmp_path / "deck.pptx"
    _build_pptx(pptx_path, n_slides=2)

    result = _run("--pptx", str(pptx_path), "--expected-slides", "5", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["status"] == "failed"
    assert data["slide_count_actual"] == 2
    assert data["slide_count_expected"] == 5


def test_broken_relationship_target_is_caught(tmp_path: Path) -> None:
    png_path = _make_test_png(tmp_path / "img.png")
    pptx_path = tmp_path / "deck.pptx"
    _build_pptx(pptx_path, n_slides=1, picture_path=png_path)

    corrupted_path = tmp_path / "corrupted.pptx"
    with zipfile.ZipFile(pptx_path) as src, zipfile.ZipFile(corrupted_path, "w") as dst:
        for item in src.infolist():
            if item.filename.startswith("ppt/media/"):
                continue
            dst.writestr(item, src.read(item.filename))

    result = _run("--pptx", str(corrupted_path), "--expected-slides", "1", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["status"] == "failed"
    assert len(data["relationship_violations"]) >= 1


def test_editability_mismatch_is_caught(tmp_path: Path) -> None:
    png_path = _make_test_png(tmp_path / "img.png")
    pptx_path = tmp_path / "deck.pptx"
    _build_pptx(pptx_path, n_slides=1, picture_path=png_path)
    declared_path = tmp_path / "declared.json"
    declared_path.write_text(json.dumps({"0": "native"}))

    result = _run("--pptx", str(pptx_path), "--expected-slides", "1", "--declared-editability", str(declared_path), "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["status"] == "failed"
    assert len(data["editability_mismatches"]) == 1
    assert data["editability_mismatches"][0]["declared"] == "native"
    assert data["editability_mismatches"][0]["observed"] == "raster"


def test_editability_match_passes(tmp_path: Path) -> None:
    pptx_path = tmp_path / "deck.pptx"
    _build_pptx(pptx_path, n_slides=1)  # textbox only -> native
    declared_path = tmp_path / "declared.json"
    declared_path.write_text(json.dumps({"0": "native"}))

    result = _run("--pptx", str(pptx_path), "--expected-slides", "1", "--declared-editability", str(declared_path), "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "passed"
    assert data["editability_mismatches"] == []


def test_not_a_pptx_file_reports_error(tmp_path: Path) -> None:
    bogus_path = tmp_path / "not-a-pptx.pptx"
    bogus_path.write_text("not a zip file at all")

    result = _run("--pptx", str(bogus_path), "--expected-slides", "1", "--json")

    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["status"] == "failed"
    assert "error" in data
```

If, while implementing, the exact slide-name string produced by `_slide_names` (Step 3 below) doesn't match `"ppt/slides/slide1.xml"` for `python-pptx`'s output in this environment, adjust `test_editability_mismatch_is_caught`'s implicit expectations accordingly — the test only asserts on `declared`/`observed` values, not the literal slide name, so no change should actually be needed; this note is here in case a `python-pptx` version difference surfaces something to investigate.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_pptx_structure.py -v`
Expected: FAIL/ERROR on every test (`validate_pptx_structure.py` doesn't exist yet).

- [ ] **Step 3: Implement `validate_pptx_structure.py`**

Create `skills/report-slides/scripts/validate_pptx_structure.py`:

```python
#!/usr/bin/env python3
"""validate_pptx_structure.py -- Real structural validation of a produced
.pptx file: package integrity, slide count, relationship integrity, and
an editability cross-check against what a manifest/module declared.

Read-only auditor: never modifies the .pptx it inspects, and does not
touch svg_to_pptx/'s generation code. Stdlib zipfile/xml.etree only, no
new dependencies beyond python-pptx (already required by to_pptx.py).
"""
import argparse
import datetime
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

_NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


class PptxStructureError(ValueError):
    """Raised when the .pptx file cannot be opened or parsed at all
    (as opposed to a structural finding, which is reported, not raised)."""


def _read_xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    """Read and parse one XML part from the .pptx zip.

    Args:
        zf: The open zip archive.
        name: The part's path inside the archive.

    Returns:
        The parsed XML root element.

    Raises:
        PptxStructureError: If the part is missing or malformed.
    """
    try:
        return ET.fromstring(zf.read(name))
    except KeyError as exc:
        raise PptxStructureError(f"missing required part: {name}") from exc
    except ET.ParseError as exc:
        raise PptxStructureError(f"malformed XML in {name}: {exc}") from exc


def _slide_names(zf: zipfile.ZipFile, presentation_xml: ET.Element) -> List[str]:
    """Return slide part names in presentation order.

    Args:
        zf: The open zip archive.
        presentation_xml: The parsed ppt/presentation.xml root.

    Returns:
        Slide part paths (e.g. "ppt/slides/slide1.xml"), in the order
        <p:sldIdLst> declares them -- not a sorted glob, since order
        matters for slide-count/expected_slides correspondence.

    Raises:
        PptxStructureError: If ppt/_rels/presentation.xml.rels is missing
            or malformed.
    """
    rels = _read_xml(zf, "ppt/_rels/presentation.xml.rels")
    rid_to_target = {rel.get("Id"): rel.get("Target") for rel in rels.findall("rel:Relationship", _NS)}
    names = []
    sld_id_lst = presentation_xml.find("p:sldIdLst", _NS)
    for sld_id in (sld_id_lst if sld_id_lst is not None else []):
        rid = sld_id.get("{%s}id" % _NS["r"])
        target = rid_to_target.get(rid)
        if target:
            names.append(target if target.startswith("ppt/") else f"ppt/{target.lstrip('/')}")
    return names


def _relationship_violations(zf: zipfile.ZipFile, slide_name: str) -> List[Dict[str, Any]]:
    """Check that every r:embed/r:id/r:link referenced inside a slide
    resolves to a .rels entry whose Target exists in the package.

    Args:
        zf: The open zip archive.
        slide_name: The slide part's path.

    Returns:
        A list of violation dicts; empty if all references resolve.
    """
    violations: List[Dict[str, Any]] = []
    slide_xml = _read_xml(zf, slide_name)
    rels_name = slide_name.replace("slides/", "slides/_rels/") + ".rels"
    try:
        rels_xml = _read_xml(zf, rels_name)
        rid_to_target = {rel.get("Id"): rel.get("Target") for rel in rels_xml.findall("rel:Relationship", _NS)}
    except PptxStructureError:
        rid_to_target = {}
    referenced_rids = set()
    for elem in slide_xml.iter():
        for attr in ("{%s}embed" % _NS["r"], "{%s}id" % _NS["r"], "{%s}link" % _NS["r"]):
            rid = elem.get(attr)
            if rid:
                referenced_rids.add(rid)
    slide_dir = "/".join(slide_name.split("/")[:-1])
    for rid in referenced_rids:
        target = rid_to_target.get(rid)
        if target is None:
            violations.append({"slide": slide_name, "rid": rid, "issue": "no matching relationship entry"})
            continue
        resolved = target if target.startswith("ppt/") else f"{slide_dir}/{target}"
        resolved = resolved.replace("/./", "/").replace("slides/../", "")
        if resolved.lstrip("/") not in zf.namelist():
            violations.append({"slide": slide_name, "rid": rid, "issue": f"target does not exist: {resolved}"})
    return violations


def _observed_editability(zf: zipfile.ZipFile, slide_name: str) -> str:
    """Classify a slide's shape content.

    Args:
        zf: The open zip archive.
        slide_name: The slide part's path.

    Returns:
        "native" (vector shapes only), "raster" (a picture and no vector
        shapes), or "hybrid" (both present).
    """
    slide_xml = _read_xml(zf, slide_name)
    sp_tree = slide_xml.find(".//p:cSld/p:spTree", _NS)
    has_vector = sp_tree is not None and any(
        sp_tree.findall(f"p:{tag}", _NS) for tag in ("sp", "cxnSp")
    )
    has_picture = sp_tree is not None and len(sp_tree.findall("p:pic", _NS)) > 0
    if has_vector and has_picture:
        return "hybrid"
    if has_picture:
        return "raster"
    return "native"


def validate_pptx_structure(
    pptx_path: Path, expected_slides: int, declared_editability: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Validate a produced .pptx file's package structure.

    Args:
        pptx_path: Path to the .pptx file.
        expected_slides: Expected slide count (matches
            validate_visual_review.py's existing "expected_slides" field).
        declared_editability: Optional {slide_index_as_str: editability}
            map (as declared by the manifest/module) to cross-check
            against what's actually observed in the rendered output.

    Returns:
        {"status": "passed"|"failed", "checked_at": iso8601,
        "slide_count_expected": int, "slide_count_actual": int,
        "relationship_violations": [...], "editability_mismatches": [...]}.

    Raises:
        PptxStructureError: If the file is not a valid zip, or a required
            part is missing or malformed -- i.e. the package cannot be
            inspected at all.
    """
    try:
        zf = zipfile.ZipFile(pptx_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PptxStructureError(f"not a valid .pptx/zip file: {exc}") from exc
    with zf:
        _read_xml(zf, "[Content_Types].xml")
        presentation_xml = _read_xml(zf, "ppt/presentation.xml")
        slide_names = _slide_names(zf, presentation_xml)

        relationship_violations: List[Dict[str, Any]] = []
        editability_mismatches: List[Dict[str, Any]] = []
        for i, slide_name in enumerate(slide_names):
            relationship_violations.extend(_relationship_violations(zf, slide_name))
            observed = _observed_editability(zf, slide_name)
            declared = (declared_editability or {}).get(str(i))
            if declared and declared != observed:
                editability_mismatches.append({"slide": slide_name, "declared": declared, "observed": observed})

        status = (
            "passed"
            if len(slide_names) == expected_slides and not relationship_violations and not editability_mismatches
            else "failed"
        )
        return {
            "status": status,
            "checked_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "slide_count_expected": expected_slides,
            "slide_count_actual": len(slide_names),
            "relationship_violations": relationship_violations,
            "editability_mismatches": editability_mismatches,
        }


def main() -> None:
    """CLI entry point for validate_pptx_structure.py."""
    parser = argparse.ArgumentParser(description="Validate a .pptx file's package structure.")
    parser.add_argument("--pptx", metavar="PATH", type=Path, required=True)
    parser.add_argument("--expected-slides", type=int, required=True)
    parser.add_argument("--declared-editability", metavar="PATH", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    declared = json.loads(args.declared_editability.read_text(encoding="utf-8")) if args.declared_editability else None

    try:
        result = validate_pptx_structure(args.pptx, args.expected_slides, declared)
    except PptxStructureError as exc:
        result = {"status": "failed", "error": str(exc)}
        print(json.dumps(result) if args.json else json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_pptx_structure.py -v`
Expected: all 6 tests pass, pristine output. If `test_broken_relationship_target_is_caught` or `test_editability_mismatch_is_caught` fail because of how `python-pptx` in this environment names/embeds media (rather than a logic bug), inspect the actual zip contents (`python3 -c "import zipfile; print(zipfile.ZipFile('...').namelist())"`) and adjust the fixture-corruption or assertion to match reality — but do not weaken `validate_pptx_structure`'s actual detection logic to make a test pass.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/validate_pptx_structure.py skills/report-slides/scripts/tests/test_validate_pptx_structure.py
git commit -m "feat(report-slides): add real .pptx structural validator (validate_pptx_structure.py)"
```

---

### Task 7: Extend `validate_diagram_manifest.py` and `validate_visual_review.py`

**Files:**
- Modify: `skills/report-slides/scripts/validate_diagram_manifest.py`
- Modify: `skills/report-slides/scripts/validate_visual_review.py`
- Modify: `skills/report-slides/scripts/tests/test_validate_diagram_manifest.py`
- Modify: `skills/report-slides/scripts/tests/test_validate_visual_review.py`

**Interfaces:**
- Consumes: both files' existing structure exactly as currently written (this task is pure addition — read each file's current relevant section with the Read tool before editing, and use its own existing helper functions/patterns rather than introducing new ones).
- Produces: `_validate_optional_text` (new helper in `validate_diagram_manifest.py`), an optional `modules_ref` field on manifests; six new entries appended to `validate_visual_review.py`'s `_ALLOWED_FINDING_KINDS` tuple.

**Global constraint specific to this task:** both target files already have passing test suites (44 cases for `validate_diagram_manifest.py`, 13 for `validate_visual_review.py`) that must still pass unmodified after these edits — this task only adds new optional/additive behavior, it does not change any existing required-field validation.

- [ ] **Step 1: Write the failing tests**

Append to `skills/report-slides/scripts/tests/test_validate_diagram_manifest.py` (read the file first to match its exact existing fixture-building helper function(s) and import style before writing these — the tests below use a placeholder helper name `_valid_manifest_document()` that must be replaced with whatever this test file's existing valid-manifest fixture helper is actually called):

```python
def test_manifest_without_modules_ref_still_passes(tmp_path: Path) -> None:
    # A manifest with no modules_ref key at all (the overwhelming majority
    # of existing/simple manifests) must continue to validate cleanly --
    # modules_ref is optional, never required.
    manifest_dir = tmp_path / "some-diagram"
    manifest_dir.mkdir()
    document = _valid_manifest_document()  # replace with this file's actual fixture helper
    manifest_path = manifest_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(document))

    issues = validate_manifest(manifest_path)

    assert issues == []


def test_manifest_with_valid_modules_ref_passes(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "some-diagram"
    manifest_dir.mkdir()
    (manifest_dir / "modules.yaml").write_text("visual_id: some-diagram\n")
    document = {**_valid_manifest_document(), "modules_ref": "modules.yaml"}
    manifest_path = manifest_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(document))

    issues = validate_manifest(manifest_path)

    assert issues == []


def test_manifest_with_modules_ref_pointing_at_missing_file_fails(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "some-diagram"
    manifest_dir.mkdir()
    document = {**_valid_manifest_document(), "modules_ref": "does-not-exist.yaml"}
    manifest_path = manifest_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(document))

    issues = validate_manifest(manifest_path)

    assert any(issue.path == "modules_ref" for issue in issues)
```

Append to `skills/report-slides/scripts/tests/test_validate_visual_review.py`:

```python
def test_unsupported_claim_is_an_allowed_finding_kind() -> None:
    assert "unsupported-claim" in _ALLOWED_FINDING_KINDS


def test_all_new_plan_level_finding_kinds_are_allowed() -> None:
    for kind in (
        "unsupported-claim", "duplicated-content", "missing-limitation",
        "excessive-background", "unnecessary-visual", "weak-continuity",
    ):
        assert kind in _ALLOWED_FINDING_KINDS
```

(These two tests import `_ALLOWED_FINDING_KINDS` the same way this test file already imports other names from `validate_visual_review` — match its existing import statement rather than adding a new one.)

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_diagram_manifest.py tests/test_validate_visual_review.py -k "modules_ref or finding_kind" -v`
Expected: FAIL/ERROR on every new test (`test_manifest_without_modules_ref_still_passes` may already pass since it exercises no new behavior — that's fine, it's a regression guard, not a new-behavior test; the other four should fail).

- [ ] **Step 3: Implement `validate_diagram_manifest.py`**

Read `skills/report-slides/scripts/validate_diagram_manifest.py` first to confirm the exact current text still matches what's quoted below (it was last read for this plan's own research pass; re-confirm before editing since Task 1-6 of this plan don't touch this file, but re-confirming costs nothing and protects against drift).

In `validate_diagram_manifest.py`, find this exact text (immediately after `_validate_nullable_text`, immediately before `_validate_kebab_id_field`):

```python
def _validate_nullable_text(
    document: Mapping[str, Any],
    field_name: str,
    path: Path,
    issues: List[ValidationIssue],
) -> Optional[str]:
    """Require a string-or-null provenance field and return strings."""
    if field_name not in document:
        issues.append(_issue(path, field_name, "{} is required".format(field_name)))
        return None
    value = document[field_name]
    if value is not None and not isinstance(value, str):
        issues.append(
            _issue(path, field_name, "{} must be a string or null".format(field_name))
        )
        return None
    return value


def _validate_kebab_id_field(
```

Replace it with:

```python
def _validate_nullable_text(
    document: Mapping[str, Any],
    field_name: str,
    path: Path,
    issues: List[ValidationIssue],
) -> Optional[str]:
    """Require a string-or-null provenance field and return strings."""
    if field_name not in document:
        issues.append(_issue(path, field_name, "{} is required".format(field_name)))
        return None
    value = document[field_name]
    if value is not None and not isinstance(value, str):
        issues.append(
            _issue(path, field_name, "{} must be a string or null".format(field_name))
        )
        return None
    return value


def _validate_optional_text(
    document: Mapping[str, Any],
    field_name: str,
    path: Path,
    issues: List[ValidationIssue],
) -> Optional[str]:
    """Validate a field that may be entirely absent; if present, must be
    a string or null. Unlike _validate_nullable_text, absence is not
    itself an issue -- this is for genuinely optional fields."""
    if field_name not in document:
        return None
    value = document[field_name]
    if value is not None and not isinstance(value, str):
        issues.append(
            _issue(path, field_name, "{} must be a string or null if present".format(field_name))
        )
        return None
    return value


def _validate_kebab_id_field(
```

Then find this exact text inside `validate_manifest`:

```python
    _validate_review(document, path, issues)
    _validate_route_provenance(
        authoring_route,
        source_paths,
        path,
        issues,
    )

    if diagram_id is not None and diagram_id != path.parent.name:
```

Replace it with:

```python
    _validate_review(document, path, issues)
    _validate_route_provenance(
        authoring_route,
        source_paths,
        path,
        issues,
    )
    modules_ref = _validate_optional_text(document, "modules_ref", path, issues)
    if modules_ref:
        resolved, path_error = _resolve_relative_path(path.parent, modules_ref)
        if path_error is not None or resolved is None:
            issues.append(_issue(path, "modules_ref", path_error or "invalid modules_ref path"))
        elif not resolved.is_file():
            issues.append(_issue(path, "modules_ref", "modules_ref file does not exist"))

    if diagram_id is not None and diagram_id != path.parent.name:
```

- [ ] **Step 4: Implement `validate_visual_review.py`**

Read `skills/report-slides/scripts/validate_visual_review.py` first to confirm the exact current text of `_ALLOWED_FINDING_KINDS` still matches what's quoted below.

Find this exact text:

```python
_ALLOWED_FINDING_KINDS: Tuple[str, ...] = (
    "clipping",
    "overlap",
    "text-reflow",
    "connector-drift",
    "crop",
    "unreadably-small-text",
    "missing-image",
    "z-order",
    "alignment",
    "other",
)
```

Replace it with:

```python
_ALLOWED_FINDING_KINDS: Tuple[str, ...] = (
    "clipping",
    "overlap",
    "text-reflow",
    "connector-drift",
    "crop",
    "unreadably-small-text",
    "missing-image",
    "z-order",
    "alignment",
    "other",
    # Plan-level finding kinds (Content Reviewer, Stage 4) -- reusing this
    # same findings[].kind vocabulary rather than a parallel one.
    "unsupported-claim",
    "duplicated-content",
    "missing-limitation",
    "excessive-background",
    "unnecessary-visual",
    "weak-continuity",
)
```

- [ ] **Step 5: Run all affected tests to verify they pass, and confirm no regression**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_diagram_manifest.py tests/test_validate_visual_review.py -v`
Expected: all existing 44 + 13 tests still pass, plus the 5 new tests from Step 1, with zero failures.

Then run the full existing `report-slides` suite to confirm nothing else regressed:

Run: `cd skills/report-slides/scripts && python3 -m pytest -v`
Expected: every test across `scripts/tests/` and `svg_to_pptx/tests/` passes (this plan's new files' tests plus every pre-existing test file).

- [ ] **Step 6: Commit**

```bash
git add skills/report-slides/scripts/validate_diagram_manifest.py skills/report-slides/scripts/validate_visual_review.py \
  skills/report-slides/scripts/tests/test_validate_diagram_manifest.py skills/report-slides/scripts/tests/test_validate_visual_review.py
git commit -m "feat(report-slides): add optional modules_ref to diagram manifests and plan-level finding kinds"
```
