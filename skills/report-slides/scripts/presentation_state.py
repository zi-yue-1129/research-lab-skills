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
from typing import Any, Dict, Iterator

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
