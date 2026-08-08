#!/usr/bin/env python3
"""presentation_state.py -- Deck/Slide/VisualModule state store, Review Result event log, and Revision Request store for the report-slides multi-agent workflow.
Independent implementation (no import from skills/agent-state/) that follows the same proven pattern: sidecar-lock-file writes, atomic YAML
replace, id-keyed maps for mutable records, append-only JSONL for immutable facts, and write-time referential-integrity checks. Bootstraps
its own .research/presentations/.gitignore rather than touching .research/.gitignore, since agent-state may independently manage that
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
from presentation_events import (
    LockTimeoutError,
    StateParseError,
    append_event,
    canonical_relative_path,
    create_artifact_record,
    EVENTS_RELATIVE_DIR,
    create_assignment_record,
    load_events,
    load_artifacts,
    load_assignments,
    load_plans,
    load_review_results,
    load_revision_requests,
    register_artifact_record,
    register_assignment_record,
    register_plan_record,
    create_revision_request,
    effective_review_results,
    next_actions,
    workflow_blockers,
)
try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Run: pip install pyyaml", file=sys.stderr)
    raise SystemExit(1)
DECKS_RELATIVE_PATH = Path(".research/presentations/state/decks.yaml")
SLIDES_RELATIVE_PATH = Path(".research/presentations/state/slides.yaml")
VISUAL_MODULES_RELATIVE_PATH = Path(".research/presentations/state/visual_modules.yaml")
REVISION_REQUESTS_RELATIVE_PATH = Path(".research/presentations/state/revision_requests.yaml")
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
# defines one 9-state enum for "Slide or visual module", not two.
_PRODUCTION_UNIT_TRANSITIONS: Dict[str, frozenset] = {
    "planned": frozenset({"ready", "blocked"}),
    "ready": frozenset({"assigned", "blocked"}),
    "assigned": frozenset({"producing", "blocked"}),
    "producing": frozenset({"review_required", "blocked"}),
    "review_required": frozenset({"passed", "revision_required", "superseded", "blocked"}),
    "revision_required": frozenset({"producing", "superseded", "blocked"}),
    "passed": frozenset({"superseded", "blocked"}),
    "blocked": frozenset({
        "planned", "ready", "assigned", "producing",
        "review_required", "revision_required",
    }),
    "superseded": frozenset(),
}
_PRODUCTION_UNIT_STATUSES = frozenset(_PRODUCTION_UNIT_TRANSITIONS.keys())
_MODULE_TYPES = frozenset({"data_visualization", "architecture", "conceptual", "annotation"})
_REVIEW_SUBJECT_TYPES = frozenset({"plan", "module", "slide", "deck"})
_REVIEW_STATUSES = frozenset({"passed", "failed", "blocked"})
_REVISION_REQUESTERS = frozenset({"user", "reviewer"})
class ProjectRootNotFoundError(RuntimeError):
    """Raised when no ancestor directory containing a .git entry can be found."""
class DeckNotFoundError(ValueError):
    """Raised when a deck_id does not exist in state/decks.yaml."""
class SlideNotFoundError(ValueError):
    """Raised when a slide_id does not exist in state/slides.yaml."""
class VisualModuleNotFoundError(ValueError):
    """Raised when a module_id does not exist in state/visual_modules.yaml."""
class ProductionNotAllowedError(RuntimeError):
    """Raised when a production-guarded action is attempted before a Deck
    reaches "approved" or a later status."""
_APPROVED_OR_LATER = frozenset({"approved", "producing", "draft_review", "revising", "validating", "completed"})
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
    gitignore_path.write_text("state/*.lock\nstate/*.tmp\nevents/\ncache/\n", encoding="utf-8")
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
    if not isinstance(doc, dict):
        raise StateParseError(f"Invalid state document in {path}: expected mapping")
    version = doc.get("version", 1)
    if version != STATE_SCHEMA_VERSION:
        raise StateParseError(
            f"Unsupported schema version {version!r} in {path} (expected {STATE_SCHEMA_VERSION})"
        )
    records = doc.get(top_key, {}) or {}
    if not isinstance(records, dict):
        raise StateParseError(f"Invalid {top_key} map in {path}: expected mapping")
    if any(not isinstance(record, dict) for record in records.values()):
        raise StateParseError(f"Invalid {top_key} map in {path}: records must be mappings")
    return records
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
            "current_plan_id": None, "approved_plan_version": None,
            "approved_plan_sha256": None, "approval_id": None,
            "approved_by": None, "approved_at": None, "approval_mode": None,
            "draft_preview_id": None, "draft_approval_id": None,
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
            "approved_takeaway_sha256": None, "approved_evidence_sha256": None,
            "slide_spec_path": None, "slide_spec_sha256": None,
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
            "visual_spec_path": None, "assignment_path": None,
            "artifact_manifest_path": None, "attempt": 1,
            "supersedes_module_id": None, "created_at": now, "updated_at": now,
            "created_by": created_by,
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
def record_review(
    project_root: Path,
    subject_type: str,
    subject_id: str,
    reviewer_id: Optional[str] = None,
    reviewer_role: Optional[str] = None,
    status: Optional[str] = None,
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
        reviewer_id: Reviewer identity, or ``None`` for an unverifiable
            legacy call.
        reviewer_role: Review role, e.g. ``scientific`` or
            ``visual_quality``.  Legacy callers may pass the status here and
            omit this argument.
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
    # The original API accepted ``(reviewer_role, status, findings, round)``.
    # Preserve that call shape while explicitly retaining its unverifiable ID.
    if status is None:
        status = reviewer_role
        reviewer_role = reviewer_id
        reviewer_id = None
    elif not isinstance(status, str):
        legacy_status = reviewer_role
        legacy_findings = status
        legacy_round = findings if isinstance(findings, int) else round_number
        reviewer_role, reviewer_id = reviewer_id, None
        status = legacy_status
        findings = legacy_findings if isinstance(legacy_findings, list) else None
        round_number = legacy_round
    if reviewer_id is not None:
        if not isinstance(reviewer_id, str):
            raise ValueError("reviewer_id must be a non-empty trimmed string or null")
        reviewer_id = reviewer_id.strip()
        if not reviewer_id:
            raise ValueError("reviewer_id must be a non-empty trimmed string or null")
    if not isinstance(reviewer_role, str) or not reviewer_role.strip():
        raise ValueError("reviewer_role is required")
    if subject_type not in _REVIEW_SUBJECT_TYPES:
        raise ValueError(f"subject_type must be one of {sorted(_REVIEW_SUBJECT_TYPES)}, got {subject_type!r}")
    if not isinstance(status, str) or status not in _REVIEW_STATUSES:
        raise ValueError(f"status must be one of {sorted(_REVIEW_STATUSES)}, got {status!r}")
    if isinstance(round_number, bool) or not isinstance(round_number, int) or round_number < 1:
        raise ValueError("round_number must be a positive integer")
    if findings is not None and not isinstance(findings, list):
        raise ValueError("findings must be a list")
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
        "subject_id": subject_id, "reviewer_id": reviewer_id, "reviewer_role": reviewer_role,
        "identity_verifiable": reviewer_id is not None,
        "status": status,
        "findings": findings or [], "round": round_number, "ts": _utc_now_iso(),
    }
    append_event(project_root, event)
    return event
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
    """Return the complete durable workflow snapshot for one deck.
    The query is read-only and deterministic: it never replays or appends
    events, so invoking it from a fresh process cannot create duplicates.
    Args:
        project_root: The project's root directory.
        deck_id: The Deck to look up.
    Returns:
        A mapping containing deck, plan, assignment, artifact, review, draft,
        blocker, and next-action records.
    Raises:
        DeckNotFoundError: If ``deck_id`` does not exist.
        StateParseError: If a state YAML file or event shard is malformed.
    """
    decks = load_decks(project_root)
    if deck_id not in decks:
        raise DeckNotFoundError(f"Unknown deck_id: {deck_id}")
    deck = decks[deck_id]
    slides = [s for s in load_slides(project_root).values() if s.get("deck_id") == deck_id]
    slide_ids = {s["id"] for s in slides}
    modules = [m for m in load_visual_modules(project_root).values() if m.get("slide_id") in slide_ids]
    module_ids = {m["id"] for m in modules}
    revisions = [
        r for r in load_revision_requests(project_root).values()
        if r.get("subject_id") == deck_id
        or r.get("subject_id") in slide_ids
        or r.get("subject_id") in module_ids
    ]
    plans = [p for p in load_plans(project_root).values() if p.get("deck_id") == deck_id]
    assignments = [
        assignment for assignment in load_assignments(project_root).values()
        if assignment.get("deck_id") == deck_id
        or assignment.get("slide_id") in slide_ids
        or assignment.get("module_id") in module_ids
    ]
    artifacts = [
        artifact for artifact in load_artifacts(project_root).values()
        if artifact.get("deck_id") == deck_id
        or artifact.get("slide_id") in slide_ids
        or artifact.get("module_id") in module_ids
    ]
    subject_ids = {deck_id} | slide_ids | module_ids
    reviews = load_review_results(project_root, subject_ids=subject_ids)
    approval = _approval_snapshot(deck)
    draft_preview, draft_decision = _draft_snapshots(project_root, deck_id, deck)
    blockers = workflow_blockers(deck, slides, modules, assignments, reviews, draft_preview, draft_decision)
    next_action_list = next_actions(deck, plans, slides, modules, reviews, approval, draft_preview)
    return {
        "deck": deck,
        "plans": sorted(plans, key=_record_order),
        "approval": approval,
        "slides": sorted(slides, key=lambda s: s["created_at"]),
        "visual_modules": sorted(modules, key=lambda m: m["created_at"]),
        "assignments": sorted(assignments, key=_record_order),
        "artifacts": sorted(artifacts, key=_record_order),
        "review_results": reviews,
        "revision_requests": sorted(revisions, key=_record_order),
        "draft_preview": draft_preview,
        "draft_decision": draft_decision,
        "blockers": blockers,
        "next_actions": next_action_list,
    }
def _record_order(record: Dict[str, Any]) -> tuple[str, str]:
    """Return a stable timestamp/ID ordering key for persisted records."""
    return str(record.get("created_at", record.get("ts", ""))), str(record.get("id", ""))
def _approval_snapshot(deck: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract persisted approval identity, or ``None`` when absent."""
    if not deck.get("approval_id") and deck.get("approved_plan_version") is None:
        return None
    return {
        "id": deck.get("approval_id"),
        "plan_version": deck.get("approved_plan_version"),
        "plan_sha256": deck.get("approved_plan_sha256"),
        "approved_by": deck.get("approved_by"),
        "approved_at": deck.get("approved_at"),
        "approval_mode": deck.get("approval_mode"),
    }
def _draft_snapshots(
    project_root: Path, deck_id: str, deck: Dict[str, Any]
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return latest draft preview/decision records without writing state."""
    previews = [
        event for event in load_events(project_root, event_type="draft_preview")
        if event.get("deck_id") == deck_id
    ]
    decisions = [
        event for event in load_events(project_root, event_type="draft_decision")
        if event.get("deck_id") == deck_id
    ]
    preview = previews[-1] if previews else None
    decision = decisions[-1] if decisions else None
    if deck.get("draft_preview_id"):
        preview = next((event for event in previews if event.get("id") == deck["draft_preview_id"]), None)
    if deck.get("draft_approval_id"):
        decision = next((event for event in decisions if event.get("id") == deck["draft_approval_id"]), None)
    return preview, decision
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
    plans = load_plans(project_root)
    assignments = load_assignments(project_root)
    artifacts = load_artifacts(project_root)
    load_review_results(project_root)
    violations: list = []
    for entity, records in (("deck", decks), ("slide", slides), ("visual_module", modules), ("revision_request", revisions), ("plan", plans), ("assignment", assignments), ("artifact", artifacts)):
        for record_id, record in records.items():
            if record.get("id") != record_id:
                violations.append({"entity": entity, "id": record_id, "field": "id", "missing_id": record.get("id")})
    for slide_id, slide in slides.items():
        deck_id = slide.get("deck_id")
        if deck_id not in decks:
            violations.append({"entity": "slide", "id": slide_id, "field": "deck_id", "missing_id": deck_id})
    for module_id, module in modules.items():
        slide_id = module.get("slide_id")
        if slide_id not in slides:
            violations.append({"entity": "visual_module", "id": module_id, "field": "slide_id", "missing_id": slide_id})
        elif slides[slide_id].get("deck_id") not in decks:
            violations.append({"entity": "visual_module", "id": module_id, "field": "slide_id", "missing_id": slides[slide_id].get("deck_id")})
        for dep_id in module.get("dependencies", []):
            if dep_id not in modules:
                violations.append({"entity": "visual_module", "id": module_id, "field": "dependencies", "missing_id": dep_id})
        if module.get("assignment_path") and not any(
            assignment.get("module_id") == module_id and assignment.get("assignment_path") == module.get("assignment_path")
            for assignment in assignments.values()
        ):
            violations.append({"entity": "visual_module", "id": module_id, "field": "assignment_path", "missing_id": module.get("assignment_path")})
        if module.get("artifact_manifest_path") and not any(
            artifact.get("module_id") == module_id and artifact.get("path") == module.get("artifact_manifest_path")
            for artifact in artifacts.values()
        ):
            violations.append({"entity": "visual_module", "id": module_id, "field": "artifact_manifest_path", "missing_id": module.get("artifact_manifest_path")})
    known_ids = set(decks) | set(slides) | set(modules)
    for request_id, request in revisions.items():
        subject_id = request.get("subject_id")
        if subject_id not in known_ids:
            violations.append({"entity": "revision_request", "id": request_id, "field": "subject_id", "missing_id": subject_id})
    for plan_id, plan in plans.items():
        if plan.get("deck_id") not in decks:
            violations.append({"entity": "plan", "id": plan_id, "field": "deck_id", "missing_id": plan.get("deck_id")})
        superseded = plan.get("supersedes_plan_id")
        if superseded is not None and (superseded not in plans or plans[superseded].get("deck_id") != plan.get("deck_id")):
            violations.append({"entity": "plan", "id": plan_id, "field": "supersedes_plan_id", "missing_id": superseded})
    for assignment_id, assignment in assignments.items():
        if assignment.get("deck_id") not in decks:
            violations.append({"entity": "assignment", "id": assignment_id, "field": "deck_id", "missing_id": assignment.get("deck_id")})
        if assignment.get("slide_id") is not None and assignment.get("slide_id") not in slides:
            violations.append({"entity": "assignment", "id": assignment_id, "field": "slide_id", "missing_id": assignment.get("slide_id")})
        if assignment.get("module_id") is not None and assignment.get("module_id") not in modules:
            violations.append({"entity": "assignment", "id": assignment_id, "field": "module_id", "missing_id": assignment.get("module_id")})
        assignment_deck = assignment.get("deck_id")
        slide_id = assignment.get("slide_id")
        if slide_id in slides and slides[slide_id].get("deck_id") != assignment_deck:
            violations.append({"entity": "assignment", "id": assignment_id, "field": "slide_id", "missing_id": slides[slide_id].get("deck_id")})
        module_id = assignment.get("module_id")
        if module_id in modules:
            module_slide = modules[module_id].get("slide_id")
            if module_slide not in slides or slides[module_slide].get("deck_id") != assignment_deck:
                violations.append({"entity": "assignment", "id": assignment_id, "field": "module_id", "missing_id": module_id})
            elif slide_id is not None and module_slide != slide_id:
                violations.append({"entity": "assignment", "id": assignment_id, "field": "slide_id", "missing_id": module_slide})
        for dependency in assignment.get("dependencies", []):
            if dependency not in modules:
                violations.append({"entity": "assignment", "id": assignment_id, "field": "dependencies", "missing_id": dependency})
            else:
                dep_slide = modules[dependency].get("slide_id")
                if dep_slide not in slides or slides[dep_slide].get("deck_id") != assignment_deck:
                    violations.append({"entity": "assignment", "id": assignment_id, "field": "dependencies", "missing_id": dependency})
    for artifact_id, artifact in artifacts.items():
        if artifact.get("deck_id") not in decks:
            violations.append({"entity": "artifact", "id": artifact_id, "field": "deck_id", "missing_id": artifact.get("deck_id")})
        if artifact.get("slide_id") is not None and artifact.get("slide_id") not in slides:
            violations.append({"entity": "artifact", "id": artifact_id, "field": "slide_id", "missing_id": artifact.get("slide_id")})
        if artifact.get("module_id") is not None and artifact.get("module_id") not in modules:
            violations.append({"entity": "artifact", "id": artifact_id, "field": "module_id", "missing_id": artifact.get("module_id")})
        artifact_deck = artifact.get("deck_id")
        slide_id = artifact.get("slide_id")
        if slide_id in slides and slides[slide_id].get("deck_id") != artifact_deck:
            violations.append({"entity": "artifact", "id": artifact_id, "field": "slide_id", "missing_id": slides[slide_id].get("deck_id")})
        module_id = artifact.get("module_id")
        if module_id in modules:
            module_slide = modules[module_id].get("slide_id")
            if module_slide not in slides or slides[module_slide].get("deck_id") != artifact_deck:
                violations.append({"entity": "artifact", "id": artifact_id, "field": "module_id", "missing_id": module_id})
            elif slide_id is not None and module_slide != slide_id:
                violations.append({"entity": "artifact", "id": artifact_id, "field": "slide_id", "missing_id": module_slide})
    return violations
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
    action.add_argument("--create-visual-module", action="store_true")
    action.add_argument("--set-module-status", action="store_true")
    action.add_argument("--record-review", action="store_true")
    action.add_argument("--create-revision-request", action="store_true")
    action.add_argument("--check-production-allowed", action="store_true")
    action.add_argument("--query", action="store_true")
    action.add_argument("--validate", action="store_true")
    for gated_action in (
        "--register-plan", "--record-content-review", "--approve-deck",
        "--record-production-review", "--request-targeted-revision",
        "--register-draft-preview", "--approve-draft", "--complete-deck",
    ):
        action.add_argument(gated_action, action="store_true")
    parser.add_argument("--skill", metavar="NAME")
    parser.add_argument("--authored-by", dest="authored_by", metavar="NAME")
    parser.add_argument("--title", metavar="TEXT")
    parser.add_argument("--deck-id", metavar="ID")
    parser.add_argument("--slide-id", metavar="ID")
    parser.add_argument("--plan-slide-id", metavar="ID")
    parser.add_argument("--module-id", metavar="ID")
    parser.add_argument("--module-key", metavar="ID")
    parser.add_argument("--module-type", metavar="TYPE")
    parser.add_argument("--dependencies", metavar="ID", nargs="*", default=[])
    parser.add_argument("--subject-type", metavar="TYPE")
    parser.add_argument("--subject-id", metavar="ID")
    parser.add_argument("--reviewer-id", metavar="ID")
    parser.add_argument("--reviewer-role", metavar="NAME")
    parser.add_argument("--findings-json", metavar="JSON")
    parser.add_argument("--round", type=int, default=1, metavar="N")
    parser.add_argument("--requested-by", metavar="WHO")
    parser.add_argument("--instructions", metavar="TEXT")
    parser.add_argument("--supersedes", metavar="ID")
    parser.add_argument("--status", metavar="STATUS")
    parser.add_argument("--plan-path", "--plan", dest="plan_path", type=Path, metavar="PATH")
    parser.add_argument("--review-path", "--review", dest="review_path", type=Path, metavar="PATH")
    parser.add_argument("--approval-path", "--approval", dest="approval_path", type=Path, metavar="PATH")
    parser.add_argument("--revision-path", "--revision", dest="revision_path", type=Path, metavar="PATH")
    parser.add_argument("--preview-path", "--preview", dest="preview_path", type=Path, metavar="PATH")
    parser.add_argument("--decision-path", "--decision", dest="decision_path", type=Path, metavar="PATH")
    parser.add_argument("--completion-record-path", "--completion", dest="completion_record_path", type=Path, metavar="PATH")
    parser.add_argument("--path", "--source", dest="generic_path", type=Path, metavar="PATH")
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
        if args.status == "approved":
            from presentation_gates import ApprovalGateError
            from presentation_workflow import approve_deck
            if args.approval_path is None and args.generic_path is None:
                raise ApprovalGateError(
                    "plan_approvable", args.deck_id or "<unknown>",
                    [{"reason": "approval evidence document is required"}],
                )
            return approve_deck(project_root, args.approval_path or args.generic_path)
        if args.status == "completed":
            from presentation_gates import CompletionGateError
            from presentation_workflow import complete_deck
            if args.completion_record_path is None and args.generic_path is None:
                raise CompletionGateError(
                    "deck_completable", args.deck_id or "<unknown>",
                    [{"reason": "completion evidence document is required"}],
                )
            return complete_deck(project_root, args.deck_id, args.completion_record_path or args.generic_path)
        if args.status == "validating":
            from presentation_gates import DraftGateError
            from presentation_workflow import approve_draft
            if args.decision_path is None and args.generic_path is None:
                raise DraftGateError(
                    "draft_approvable", args.deck_id or "<unknown>",
                    [{"reason": "draft decision evidence document is required"}],
                )
            return approve_draft(project_root, args.decision_path or args.generic_path)
        return set_deck_status(project_root, args.deck_id, args.status)
    if args.create_slide:
        return create_slide(
            project_root, args.deck_id, args.plan_slide_id, args.title,
            created_by=args.skill or "user",
        )
    if args.set_slide_status:
        if args.status == "passed":
            if args.review_path is not None or args.generic_path is not None:
                from presentation_workflow import record_production_review
                return record_production_review(project_root, args.review_path or args.generic_path)
            from presentation_gates import ReviewGateError
            slides = load_slides(project_root)
            if args.slide_id not in slides:
                raise SlideNotFoundError(f"Unknown slide_id: {args.slide_id}")
            raise ReviewGateError("slide_passable", str(slides[args.slide_id].get("deck_id", "<unknown>")), [{"reason": "production review evidence document is required"}])
        return set_slide_status(project_root, args.slide_id, args.status)
    if args.create_visual_module:
        return create_visual_module(
            project_root, args.slide_id, args.module_key, args.module_type,
            dependencies=args.dependencies, created_by=args.skill or "user",
        )
    if args.set_module_status:
        if args.status == "passed":
            from presentation_gates import ReviewGateError
            from presentation_workflow import record_production_review
            if args.review_path is None and args.generic_path is None:
                module = load_visual_modules(project_root).get(args.module_id, {})
                slide = load_slides(project_root).get(module.get("slide_id"), {})
                raise ReviewGateError(
                    "module_passable", str(slide.get("deck_id", "<unknown>")),
                    [{"reason": "production review evidence document is required"}],
                )
            return record_production_review(project_root, args.review_path or args.generic_path)
        return set_module_status(project_root, args.module_id, args.status)
    if args.record_review:
        if args.status == "passed" and args.subject_type in {"slide", "module"}:
            from presentation_gates import ReviewGateError
            records = load_slides(project_root) if args.subject_type == "slide" else load_visual_modules(project_root)
            target = records.get(args.subject_id, {})
            slide = load_slides(project_root).get(target.get("slide_id"), {}) if args.subject_type == "module" else target
            raise ReviewGateError("slide_passable", str(slide.get("deck_id", "<unknown>")), [{"reason": "use --record-production-review with an evidence document"}])
        findings = json.loads(args.findings_json) if args.findings_json else None
        return record_review(
            project_root, args.subject_type, args.subject_id,
            reviewer_id=args.reviewer_id, reviewer_role=args.reviewer_role,
            status=args.status, findings=findings, round_number=args.round,
        )
    if args.create_revision_request:
        return create_revision_request(
            project_root, args.subject_type, args.subject_id, args.requested_by,
            args.instructions, supersedes=args.supersedes,
        )
    if args.check_production_allowed:
        from presentation_gates import assert_production_allowed as assert_production_gate
        return assert_production_gate(project_root, args.deck_id)
    if args.query:
        return query(project_root, args.deck_id)
    if args.validate:
        violations = validate_referential_integrity(project_root)
        return {"violations": violations, "clean": len(violations) == 0}
    if args.register_plan:
        from presentation_workflow import register_plan
        return register_plan(project_root, args.deck_id, args.plan_path or args.generic_path, args.authored_by or args.skill or "user")
    if args.record_content_review:
        from presentation_workflow import record_content_review
        return record_content_review(project_root, args.deck_id, args.review_path or args.generic_path)
    if args.approve_deck:
        from presentation_workflow import approve_deck
        return approve_deck(project_root, args.approval_path or args.generic_path)
    if args.record_production_review:
        from presentation_workflow import record_production_review
        return record_production_review(project_root, args.review_path or args.generic_path)
    if args.request_targeted_revision:
        from presentation_workflow import request_targeted_revision
        return request_targeted_revision(project_root, args.revision_path or args.generic_path)
    if args.register_draft_preview:
        from presentation_workflow import register_draft_preview
        return register_draft_preview(project_root, args.preview_path or args.generic_path)
    if args.approve_draft:
        from presentation_workflow import approve_draft
        return approve_draft(project_root, args.decision_path or args.generic_path)
    if args.complete_deck:
        from presentation_workflow import complete_deck
        return complete_deck(project_root, args.deck_id, args.completion_record_path or args.generic_path)
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
        SlideNotFoundError, VisualModuleNotFoundError, ProductionNotAllowedError,
        LockTimeoutError, ValueError,
    ) as exc:
        from presentation_workflow import translate_cli_gate_error
        exc = translate_cli_gate_error(args, exc)
        error = ({"error": type(exc).__name__, "predicate": getattr(exc, "predicate"), "deck_id": getattr(exc, "deck_id"), "blockers": getattr(exc, "blockers")} if all(hasattr(exc, field) for field in ("predicate", "deck_id", "blockers")) else {"error": type(exc).__name__, "message": str(exc)})
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 -- stdout must always stay parseable
        error = ({"error": type(exc).__name__, "predicate": getattr(exc, "predicate"), "deck_id": getattr(exc, "deck_id"), "blockers": getattr(exc, "blockers")} if all(hasattr(exc, field) for field in ("predicate", "deck_id", "blockers")) else {"error": type(exc).__name__, "message": str(exc)})
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
if __name__ == "__main__":
    main()
