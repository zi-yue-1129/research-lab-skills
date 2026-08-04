# Resource Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Resource Resolver (`skills/resource-resolver/`) and migrate `research-log`, `report-slides`, `deep-research`, and `academic-pipeline` to consume it instead of hardcoding resource paths.

**Architecture:** A standalone CLI (`resolve.py`) maps logical resource roles (research_log, experiment_config, results, slides, paper, bibliography) to project paths recorded in `.research/workspace.yaml`, discovering candidates by directory-name matching and never writing to disk without explicit user confirmation. It ships as its own skill (`skills/resource-resolver/`) so `install.sh` deploys it like any other skill; four existing skills are then migrated to call it instead of hardcoding paths.

**Tech Stack:** Python 3 (stdlib `argparse`/`json`/`pathlib` + PyYAML, already a project dependency), pytest with subprocess-based CLI tests (matching `skills/research-log/scripts/tests/test_log_stats.py`), bash.

**Spec:** `docs/superpowers/specs/2026-08-04-resource-resolver-design.md`

## Global Constraints

- All Python functions get full type hints and Google-style docstrings (project-wide standard; applies to every function in `resolve.py`).
- No silent failures: `resolve.py` raises explicit typed exceptions (`ProjectRootNotFoundError`, `WorkspaceParseError`, `RoleRegistryError`, `UnknownRoleError`) rather than falling back to defaults on malformed input. The one exception, by explicit design decision, is the SessionStart hook shell command, which is allowed to fail silently (`|| true`) since it is a convenience trigger with a working fallback (lazy per-role resolution).
- `resolve.py` never creates a *resource role's* target directory (e.g. `docs/research_log/`, `docs/slides/`) unless `--create` is passed on `--set`, and `--set` is only ever called after a human has confirmed a specific path — no autonomous directory creation, moving, or reorganizing of user project files anywhere in this plan. This does not extend to `.research/` and its four reserved subdirectories (`state/`, `events/`, `indexes/`, `cache/`): those are the Resolver's own tool-owned bookkeeping infrastructure, analogous to `.git/`, and `save_workspace` (Task 1) creates them unconditionally on every write — including under `--skip` — as a documented, intentional exception, not a violation. (Ruling confirmed 2026-08-05 during Task 3 review, after this ambiguity was flagged as a plan-vs-finding conflict.)
- Keep `resolve.py` a single file under 1000 lines (project-wide file-size guidance); at the size scoped here it will land well under that.
- Follow the existing repo convention: skill CLI scripts are tested via subprocess (`subprocess.run([sys.executable, str(SCRIPT), *args], ...)`), not by importing the module — see `skills/research-log/scripts/tests/test_log_stats.py`. `skills/resource-resolver/scripts/` has no `__init__.py`, matching `research-log`/`report-slides`, not `bridge/`.
- SKILL.md frontmatter `description:` fields are skill-routing trigger text, not runtime paths — leave them worded as-is during migration even where they mention a literal path like `docs/research_log/`.
- Commit after each task.

---

### Task 1: `resolve.py` bootstrap — project root, workspace I/O, role registry, `--check`

**Files:**
- Create: `skills/resource-resolver/scripts/resolve.py`
- Create: `skills/resource-resolver/scripts/tests/test_resolve.py`

**Interfaces:**
- Produces: `find_project_root(start: Path) -> Path`, `load_role_registry(registry_path: Path) -> Dict[str, Dict[str, Any]]`, `load_workspace(project_root: Path) -> Dict[str, Any]`, `save_workspace(project_root: Path, data: Dict[str, Any]) -> None`, `check_roles(registry, workspace) -> Dict[str, List[str]]`, exceptions `ProjectRootNotFoundError`, `WorkspaceParseError`, `RoleRegistryError`, constants `WORKSPACE_RELATIVE_PATH`, `RESERVED_SUBDIRS`, `ROLE_REGISTRY_RELATIVE_PATH`. CLI: `resolve.py --check [--json] [--registry PATH]`.

- [ ] **Step 1: Write the failing tests**

Create `skills/resource-resolver/scripts/tests/test_resolve.py`:

```python
"""Tests for resolve.py -- Resource Resolver CLI (--check action)."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "resolve.py"

MINIMAL_REGISTRY = textwrap.dedent("""\
    version: 1
    roles:
      - name: research_log
        description: Structured research log entries
        aliases: [research_log, research-log]
        default_relative_path: docs/research_log
        consumed_by: [research-log]
      - name: slides
        description: Generated presentation decks
        aliases: [slides, presentations]
        default_relative_path: docs/slides
        consumed_by: [report-slides]
""")


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def _make_registry(tmp_path: Path, content: str = MINIMAL_REGISTRY) -> Path:
    registry_path = tmp_path / "resolver_roles.yaml"
    registry_path.write_text(content, encoding="utf-8")
    return registry_path


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_reports_all_unconfigured_when_workspace_absent(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(project, "--check", "--json", "--registry", str(registry))
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {
        "configured": [],
        "skipped": [],
        "unconfigured": ["research_log", "slides"],
    }


def test_check_reports_configured_role(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              research_log:
                primary: docs/research_log
                readonly_sources: []
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )

    result = _run(project, "--check", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data == {
        "configured": ["research_log"],
        "skipped": [],
        "unconfigured": ["slides"],
    }


def test_check_reports_skipped_role(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              slides:
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )

    result = _run(project, "--check", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data == {
        "configured": [],
        "skipped": ["slides"],
        "unconfigured": ["research_log"],
    }


def test_check_errors_when_no_git_root(tmp_path: Path) -> None:
    no_git_dir = tmp_path / "not_a_project"
    no_git_dir.mkdir()
    registry = _make_registry(tmp_path)

    result = _run(no_git_dir, "--check", "--json", "--registry", str(registry))
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ProjectRootNotFoundError"


def test_check_errors_on_malformed_workspace(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text("not: valid: yaml: [", encoding="utf-8")

    result = _run(project, "--check", "--json", "--registry", str(registry))
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "WorkspaceParseError"


def test_check_human_readable_output(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(project, "--check", "--registry", str(registry))
    assert result.returncode == 0, result.stderr
    assert "Unconfigured: research_log, slides" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest skills/resource-resolver/scripts/tests/test_resolve.py -v`
Expected: FAIL/ERROR — `resolve.py` does not exist yet (`FileNotFoundError` from `subprocess.run`, surfaced as a non-zero returncode / stderr in every test).

- [ ] **Step 3: Implement `resolve.py`**

Create `skills/resource-resolver/scripts/resolve.py`:

```python
#!/usr/bin/env python3
"""resolve.py -- Resource Resolver CLI: map logical resource roles to project paths.

Usage:
    # Report which roles are configured/unconfigured/skipped (silent-safe, for hooks)
    python resolve.py --check [--json]

    # Resolve a single role to a path, or list discovery candidates
    python resolve.py --role research_log [--json]

    # Record a user-confirmed path for a role
    python resolve.py --set research_log --path docs/research_log [--create] [--json]
    python resolve.py --set research_log --skip [--json]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


WORKSPACE_RELATIVE_PATH = Path(".research/workspace.yaml")
RESERVED_SUBDIRS = ("state", "events", "indexes", "cache")
ROLE_REGISTRY_RELATIVE_PATH = Path("references/resolver_roles.yaml")


class ProjectRootNotFoundError(RuntimeError):
    """Raised when no ancestor directory containing a .git entry can be found."""


class WorkspaceParseError(ValueError):
    """Raised when workspace.yaml exists but cannot be parsed as valid YAML."""


class RoleRegistryError(ValueError):
    """Raised when resolver_roles.yaml is missing, malformed, or has no roles."""


class UnknownRoleError(ValueError):
    """Raised when a role name is not present in the role registry."""


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
    raise ProjectRootNotFoundError(
        f"No .git found in {start} or any parent directory."
    )


def load_role_registry(registry_path: Path) -> Dict[str, Dict[str, Any]]:
    """Load and index the static role registry.

    Args:
        registry_path: Path to resolver_roles.yaml.

    Returns:
        A dict mapping role name to its full role definition.

    Raises:
        RoleRegistryError: If the file is missing, not valid YAML, or has
            no top-level 'roles' list.
    """
    if not registry_path.is_file():
        raise RoleRegistryError(f"Role registry not found: {registry_path}")

    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RoleRegistryError(f"Invalid YAML in {registry_path}: {exc}") from exc

    if not isinstance(data, dict) or "roles" not in data:
        raise RoleRegistryError(
            f"{registry_path} must be a mapping with a top-level 'roles' list."
        )

    return {role["name"]: role for role in data["roles"]}


def load_workspace(project_root: Path) -> Dict[str, Any]:
    """Load the project's confirmed role -> path mappings.

    Args:
        project_root: The project's root directory (see find_project_root).

    Returns:
        The parsed workspace document. If .research/workspace.yaml does not
        exist yet, returns an empty default document ({"version": 1,
        "roles": {}}) rather than raising, since an unconfigured workspace
        is the expected first-run state.

    Raises:
        WorkspaceParseError: If workspace.yaml exists but is not valid YAML,
            or its top-level structure is not a mapping with a 'roles' key.
    """
    workspace_path = project_root / WORKSPACE_RELATIVE_PATH
    if not workspace_path.is_file():
        return {"version": 1, "roles": {}}

    try:
        data = yaml.safe_load(workspace_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkspaceParseError(f"Invalid YAML in {workspace_path}: {exc}") from exc

    if not isinstance(data, dict) or "roles" not in data:
        raise WorkspaceParseError(
            f"{workspace_path} must be a mapping with a top-level 'roles' key."
        )
    return data


def save_workspace(project_root: Path, data: Dict[str, Any]) -> None:
    """Write the workspace document and ensure the .research/ layout exists.

    Creates .research/ and its four reserved subdirectories (state/, events/,
    indexes/, cache/) if they don't exist yet. Their internal structure is
    out of scope for this tool -- they are only staked out as empty
    placeholders for future subsystems.

    Args:
        project_root: The project's root directory.
        data: The full workspace document to serialize (version + roles).
            Mutated in place to stamp a fresh top-level "resolved_at".
    """
    research_dir = project_root / ".research"
    for subdir in RESERVED_SUBDIRS:
        (research_dir / subdir).mkdir(parents=True, exist_ok=True)

    data["resolved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    workspace_path = project_root / WORKSPACE_RELATIVE_PATH
    workspace_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def check_roles(
    registry: Dict[str, Dict[str, Any]], workspace: Dict[str, Any]
) -> Dict[str, List[str]]:
    """Diff the role registry against the workspace's confirmed roles.

    Args:
        registry: Role name -> role definition, from load_role_registry.
        workspace: The workspace document, from load_workspace.

    Returns:
        A dict with "configured" (roles with a primary path), "skipped"
        (roles explicitly skipped, no primary), and "unconfigured" (roles
        never asked about). Each value is a sorted list of role names.
    """
    roles_data = workspace.get("roles", {})
    configured: List[str] = []
    skipped: List[str] = []
    unconfigured: List[str] = []
    for name in registry:
        entry = roles_data.get(name)
        if entry is None:
            unconfigured.append(name)
        elif entry.get("primary"):
            configured.append(name)
        else:
            skipped.append(name)
    return {
        "configured": sorted(configured),
        "skipped": sorted(skipped),
        "unconfigured": sorted(unconfigured),
    }


def _format_human(result: Dict[str, Any]) -> str:
    """Render a result dict as a human-readable summary.

    Args:
        result: A dict returned by check_roles (later tasks add resolve_role
            and set_role result shapes here too).

    Returns:
        A human-readable summary string.

    Raises:
        ValueError: If result does not match any known shape.
    """
    if "configured" in result:
        return "\n".join([
            f"Configured:   {', '.join(result['configured']) or '(none)'}",
            f"Skipped:      {', '.join(result['skipped']) or '(none)'}",
            f"Unconfigured: {', '.join(result['unconfigured']) or '(none)'}",
        ])
    raise ValueError(f"Unrecognized result shape: {result}")


def _default_registry_path() -> Path:
    """Return the resolver_roles.yaml path bundled next to this script.

    Returns:
        `references/resolver_roles.yaml` relative to this script's parent
        skill directory (i.e. `skills/resource-resolver/references/...`).
    """
    return Path(__file__).resolve().parent.parent / ROLE_REGISTRY_RELATIVE_PATH


def main() -> None:
    """CLI entry point for resolve.py."""
    parser = argparse.ArgumentParser(
        description="Resource Resolver: map logical resource roles to project paths."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--check", action="store_true",
        help="Report which roles are configured/unconfigured/skipped",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of human-readable text",
    )
    parser.add_argument(
        "--registry", default=None, metavar="PATH",
        help="Override path to resolver_roles.yaml "
             "(default: references/resolver_roles.yaml next to this script)",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry) if args.registry else _default_registry_path()

    try:
        project_root = find_project_root(Path.cwd())
        registry = load_role_registry(registry_path)
        workspace = load_workspace(project_root)
        result = check_roles(registry, workspace)
    except (ProjectRootNotFoundError, WorkspaceParseError, RoleRegistryError) as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)

    print(json.dumps(result) if args.json else _format_human(result))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest skills/resource-resolver/scripts/tests/test_resolve.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add skills/resource-resolver/scripts/resolve.py skills/resource-resolver/scripts/tests/test_resolve.py
git commit -m "feat(resource-resolver): add resolve.py with --check action"
```

---

### Task 2: `resolve.py` — `--role` discovery and resolution

**Files:**
- Modify: `skills/resource-resolver/scripts/resolve.py`
- Modify: `skills/resource-resolver/scripts/tests/test_resolve.py`

**Interfaces:**
- Consumes: `load_role_registry`, `load_workspace`, `UnknownRoleError` from Task 1.
- Produces: `discover_candidates(role: Dict[str, Any], project_root: Path, max_depth: int = 3) -> List[Dict[str, str]]`, `resolve_role(role_name: str, registry: Dict[str, Dict[str, Any]], workspace: Dict[str, Any], project_root: Path) -> Dict[str, Any]`. CLI: `resolve.py --role NAME [--json] [--registry PATH]`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/resource-resolver/scripts/tests/test_resolve.py`:

```python
def test_role_resolved_when_configured(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    log_dir = project / "docs" / "research_log"
    log_dir.mkdir(parents=True)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              research_log:
                primary: docs/research_log
                readonly_sources: []
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )

    result = _run(project, "--role", "research_log", "--json", "--registry", str(registry))
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {
        "status": "resolved",
        "role": "research_log",
        "primary": "docs/research_log",
        "readonly_sources": [],
    }


def test_role_resolved_external_uri_skips_existence_check(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              research_log:
                primary: "notion://shared-lab-library"
                readonly_sources: []
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )

    result = _run(project, "--role", "research_log", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data["status"] == "resolved"
    assert data["primary"] == "notion://shared-lab-library"


def test_role_stale_mapping_when_primary_deleted(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    research_dir = project / ".research"
    research_dir.mkdir()
    (research_dir / "workspace.yaml").write_text(
        textwrap.dedent("""\
            version: 1
            roles:
              research_log:
                primary: docs/research_log
                readonly_sources: []
                confirmed_at: "2026-08-04T10:00:00+08:00"
        """),
        encoding="utf-8",
    )
    # docs/research_log deliberately not created on disk

    result = _run(project, "--role", "research_log", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data == {
        "status": "stale_mapping",
        "role": "research_log",
        "primary": "docs/research_log",
    }


def test_role_unresolved_returns_ranked_candidates(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    (project / "docs" / "research_log").mkdir(parents=True)
    (project / "unrelated_dir").mkdir()

    result = _run(project, "--role", "research_log", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data["status"] == "unresolved"
    assert data["candidates"] == [{"path": "docs/research_log", "confidence": "exact"}]
    assert data["default_relative_path"] == "docs/research_log"


def test_role_no_candidates_suggests_default(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(project, "--role", "slides", "--json", "--registry", str(registry))
    data = json.loads(result.stdout)
    assert data == {
        "status": "no_candidates",
        "role": "slides",
        "default_relative_path": "docs/slides",
    }


def test_role_errors_on_unknown_role(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(project, "--role", "nonexistent", "--json", "--registry", str(registry))
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "UnknownRoleError"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest skills/resource-resolver/scripts/tests/test_resolve.py -v -k test_role`
Expected: FAIL — `--role` is not a recognized argument yet (argparse error, non-zero exit not carrying the expected JSON shape).

- [ ] **Step 3: Implement `--role`**

In `skills/resource-resolver/scripts/resolve.py`, add a module constant right after `ROLE_REGISTRY_RELATIVE_PATH`:

```python
_SKIP_DIR_NAMES = frozenset({
    "node_modules", "__pycache__", "venv", "dist", "build", "site-packages",
})
```

Add `UnknownRoleError` next to the other exception classes (after `RoleRegistryError`):

```python
class UnknownRoleError(ValueError):
    """Raised when a role name is not present in the role registry."""
```

Insert `discover_candidates` and `resolve_role` after `check_roles` and before `_format_human`:

```python
def discover_candidates(
    role: Dict[str, Any], project_root: Path, max_depth: int = 3
) -> List[Dict[str, str]]:
    """Scan the project tree for directories matching a role's aliases.

    Args:
        role: A single role definition (must include an "aliases" list).
        project_root: Directory to scan from.
        max_depth: Maximum directory depth below project_root to descend
            into (project_root itself is depth 0).

    Returns:
        A list of {"path": <relative posix path>, "confidence": "exact" |
        "partial"} dicts. Exact alias matches (directory name equals an
        alias) are ranked before partial matches (directory name contains
        an alias as a substring). Each match appears once.
    """
    aliases = [a.lower() for a in role["aliases"]]
    exact_matches: List[str] = []
    partial_matches: List[str] = []
    seen: set = set()

    def _walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir())
        except (PermissionError, FileNotFoundError):
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name.startswith(".") or entry.name in _SKIP_DIR_NAMES:
                continue
            name_lower = entry.name.lower()
            relative = entry.relative_to(project_root).as_posix()
            if name_lower in aliases:
                if relative not in seen:
                    exact_matches.append(relative)
                    seen.add(relative)
            elif any(alias in name_lower for alias in aliases):
                if relative not in seen:
                    partial_matches.append(relative)
                    seen.add(relative)
            _walk(entry, depth + 1)

    _walk(project_root, 0)
    return (
        [{"path": p, "confidence": "exact"} for p in exact_matches]
        + [{"path": p, "confidence": "partial"} for p in partial_matches]
    )


def resolve_role(
    role_name: str,
    registry: Dict[str, Dict[str, Any]],
    workspace: Dict[str, Any],
    project_root: Path,
) -> Dict[str, Any]:
    """Resolve a single role to a path, or report discovery candidates.

    Args:
        role_name: The role to resolve (must exist in registry).
        registry: Role name -> role definition, from load_role_registry.
        workspace: The workspace document, from load_workspace.
        project_root: The project's root directory.

    Returns:
        {"status": "resolved", "role", "primary", "readonly_sources"} if
        already configured and the primary still exists (or is a URI).
        {"status": "stale_mapping", "role", "primary"} if the recorded
        primary is a local path that no longer exists.
        {"status": "unresolved", "role", "candidates", "default_relative_path"}
        if unconfigured and directory-name candidates were found.
        {"status": "no_candidates", "role", "default_relative_path"} if
        unconfigured and nothing matched.

    Raises:
        UnknownRoleError: If role_name is not in the registry.
    """
    if role_name not in registry:
        raise UnknownRoleError(f"Unknown role: {role_name}")

    role = registry[role_name]
    entry = workspace.get("roles", {}).get(role_name)

    if entry and entry.get("primary"):
        primary = entry["primary"]
        if "://" not in primary and not (project_root / primary).exists():
            return {"status": "stale_mapping", "role": role_name, "primary": primary}
        return {
            "status": "resolved",
            "role": role_name,
            "primary": primary,
            "readonly_sources": entry.get("readonly_sources", []),
        }

    candidates = discover_candidates(role, project_root)
    if not candidates:
        return {
            "status": "no_candidates",
            "role": role_name,
            "default_relative_path": role["default_relative_path"],
        }
    return {
        "status": "unresolved",
        "role": role_name,
        "candidates": candidates,
        "default_relative_path": role["default_relative_path"],
    }
```

Replace `_format_human` entirely with:

```python
def _format_human(result: Dict[str, Any]) -> str:
    """Render a result dict as a human-readable summary.

    Args:
        result: A dict returned by check_roles or resolve_role.

    Returns:
        A human-readable summary string.

    Raises:
        ValueError: If result does not match any known shape.
    """
    if "configured" in result:
        return "\n".join([
            f"Configured:   {', '.join(result['configured']) or '(none)'}",
            f"Skipped:      {', '.join(result['skipped']) or '(none)'}",
            f"Unconfigured: {', '.join(result['unconfigured']) or '(none)'}",
        ])

    status = result.get("status")
    role = result.get("role", "?")
    if status == "resolved":
        return f"{role}: {result['primary']}"
    if status == "stale_mapping":
        return f"{role}: stale mapping, {result['primary']} no longer exists"
    if status == "unresolved":
        candidates = ", ".join(c["path"] for c in result["candidates"])
        return f"{role}: candidates found -- {candidates}"
    if status == "no_candidates":
        return f"{role}: no candidates found, suggest {result['default_relative_path']}"
    raise ValueError(f"Unrecognized result shape: {result}")
```

Replace `main()` entirely with:

```python
def main() -> None:
    """CLI entry point for resolve.py."""
    parser = argparse.ArgumentParser(
        description="Resource Resolver: map logical resource roles to project paths."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--check", action="store_true",
        help="Report which roles are configured/unconfigured/skipped",
    )
    action.add_argument(
        "--role", metavar="NAME",
        help="Resolve a single role to a path, or report discovery candidates",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of human-readable text",
    )
    parser.add_argument(
        "--registry", default=None, metavar="PATH",
        help="Override path to resolver_roles.yaml "
             "(default: references/resolver_roles.yaml next to this script)",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry) if args.registry else _default_registry_path()

    try:
        project_root = find_project_root(Path.cwd())
        registry = load_role_registry(registry_path)

        if args.check:
            workspace = load_workspace(project_root)
            result = check_roles(registry, workspace)
        else:
            workspace = load_workspace(project_root)
            result = resolve_role(args.role, registry, workspace, project_root)
    except (ProjectRootNotFoundError, WorkspaceParseError, RoleRegistryError,
            UnknownRoleError) as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)

    print(json.dumps(result) if args.json else _format_human(result))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest skills/resource-resolver/scripts/tests/test_resolve.py -v`
Expected: PASS (all tests, including Task 1's)

- [ ] **Step 5: Commit**

```bash
git add skills/resource-resolver/scripts/resolve.py skills/resource-resolver/scripts/tests/test_resolve.py
git commit -m "feat(resource-resolver): add --role discovery/resolution action"
```

---

### Task 3: `resolve.py` — `--set` confirmation

**Files:**
- Modify: `skills/resource-resolver/scripts/resolve.py`
- Modify: `skills/resource-resolver/scripts/tests/test_resolve.py`

**Interfaces:**
- Consumes: `load_workspace`, `save_workspace`, `UnknownRoleError` from Tasks 1-2.
- Produces: `set_role(role_name: str, registry: Dict[str, Dict[str, Any]], project_root: Path, path: Optional[str] = None, readonly_sources: Optional[List[str]] = None, create: bool = False, skip: bool = False) -> Dict[str, Any]`. CLI: `resolve.py --set ROLE --path PATH [--readonly PATH ...] [--create] [--json]` and `resolve.py --set ROLE --skip [--json]`.

- [ ] **Step 1: Write the failing tests**

Append to `skills/resource-resolver/scripts/tests/test_resolve.py`:

```python
def test_set_writes_primary_and_creates_directory(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    target = project / "docs" / "research_log"
    assert not target.exists()

    result = _run(
        project, "--set", "research_log", "--path", "docs/research_log",
        "--create", "--json", "--registry", str(registry),
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {
        "status": "ok",
        "role": "research_log",
        "primary": "docs/research_log",
        "readonly_sources": [],
        "created": True,
    }
    assert target.is_dir()

    workspace_text = (project / ".research" / "workspace.yaml").read_text(encoding="utf-8")
    assert "docs/research_log" in workspace_text
    for subdir in ("state", "events", "indexes", "cache"):
        assert (project / ".research" / subdir).is_dir()


def test_set_without_create_does_not_touch_filesystem(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)
    target = project / "docs" / "research_log"

    result = _run(
        project, "--set", "research_log", "--path", "docs/research_log",
        "--json", "--registry", str(registry),
    )
    data = json.loads(result.stdout)
    assert data["created"] is False
    assert not target.exists()


def test_set_with_readonly_sources(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(
        project, "--set", "research_log", "--path", "docs/research_log",
        "--readonly", "notion://shared-lab-library",
        "--readonly", "docs/old_project_log",
        "--json", "--registry", str(registry),
    )
    data = json.loads(result.stdout)
    assert data["readonly_sources"] == [
        "notion://shared-lab-library",
        "docs/old_project_log",
    ]


def test_set_skip_marks_role_without_primary(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(
        project, "--set", "slides", "--skip", "--json", "--registry", str(registry),
    )
    data = json.loads(result.stdout)
    assert data == {"status": "skipped", "role": "slides"}

    check = _run(project, "--check", "--json", "--registry", str(registry))
    check_data = json.loads(check.stdout)
    assert check_data["skipped"] == ["slides"]


def test_set_errors_on_unknown_role(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(
        project, "--set", "nonexistent", "--path", "x",
        "--json", "--registry", str(registry),
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "UnknownRoleError"


def test_set_errors_when_path_missing_and_not_skip(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    result = _run(
        project, "--set", "research_log", "--json", "--registry", str(registry),
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "ValueError"


def test_set_overwrites_existing_mapping(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    registry = _make_registry(tmp_path)

    _run(project, "--set", "research_log", "--path", "old/path",
         "--json", "--registry", str(registry))
    _run(project, "--set", "research_log", "--path", "docs/research_log",
         "--json", "--registry", str(registry))

    workspace_text = (project / ".research" / "workspace.yaml").read_text(encoding="utf-8")
    assert "docs/research_log" in workspace_text
    assert "old/path" not in workspace_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest skills/resource-resolver/scripts/tests/test_resolve.py -v -k test_set`
Expected: FAIL — `--set` is not a recognized argument yet.

- [ ] **Step 3: Implement `--set`**

Insert `set_role` after `resolve_role` and before `_format_human` in `skills/resource-resolver/scripts/resolve.py`:

```python
def set_role(
    role_name: str,
    registry: Dict[str, Dict[str, Any]],
    project_root: Path,
    path: Optional[str] = None,
    readonly_sources: Optional[List[str]] = None,
    create: bool = False,
    skip: bool = False,
) -> Dict[str, Any]:
    """Write a user-confirmed role mapping into workspace.yaml.

    Args:
        role_name: The role being confirmed (must exist in registry).
        registry: Role name -> role definition, from load_role_registry.
        project_root: The project's root directory.
        path: The confirmed primary path, relative to project_root, or an
            external URI. Required unless skip is True.
        readonly_sources: Optional additional read-only source paths/URIs.
        create: If True, and path is a local path that doesn't exist yet,
            create it as a directory before recording the mapping.
        skip: If True, records the role as explicitly skipped (no primary).
            path and readonly_sources are ignored.

    Returns:
        {"status": "skipped", "role"} if skip is True, otherwise
        {"status": "ok", "role", "primary", "readonly_sources", "created"}.

    Raises:
        UnknownRoleError: If role_name is not in the registry.
        ValueError: If skip is False and path is None.
    """
    if role_name not in registry:
        raise UnknownRoleError(f"Unknown role: {role_name}")

    workspace = load_workspace(project_root)
    workspace.setdefault("roles", {})
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    if skip:
        workspace["roles"][role_name] = {"confirmed_at": now}
        save_workspace(project_root, workspace)
        return {"status": "skipped", "role": role_name}

    if path is None:
        raise ValueError("path is required unless skip=True")

    created = False
    if create and "://" not in path:
        (project_root / path).mkdir(parents=True, exist_ok=True)
        created = True

    workspace["roles"][role_name] = {
        "primary": path,
        "readonly_sources": readonly_sources or [],
        "confirmed_at": now,
    }
    save_workspace(project_root, workspace)
    return {
        "status": "ok",
        "role": role_name,
        "primary": path,
        "readonly_sources": readonly_sources or [],
        "created": created,
    }
```

In `_format_human`, insert two new branches right before the final `raise ValueError(...)` line:

```python
    if status == "skipped":
        return f"{role}: skipped"
    if status == "ok":
        created_note = " (created)" if result.get("created") else ""
        return f"{role}: set to {result['primary']}{created_note}"
```

Replace `main()` entirely with:

```python
def main() -> None:
    """CLI entry point for resolve.py."""
    parser = argparse.ArgumentParser(
        description="Resource Resolver: map logical resource roles to project paths."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--check", action="store_true",
        help="Report which roles are configured/unconfigured/skipped",
    )
    action.add_argument(
        "--role", metavar="NAME",
        help="Resolve a single role to a path, or report discovery candidates",
    )
    action.add_argument(
        "--set", metavar="ROLE",
        help="Record a confirmed path (or --skip) for a role",
    )
    parser.add_argument("--path", metavar="PATH", help="Path to record (with --set)")
    parser.add_argument(
        "--readonly", metavar="PATH", action="append", default=[],
        help="Additional read-only source, repeatable (with --set)",
    )
    parser.add_argument(
        "--create", action="store_true",
        help="Create the directory if it doesn't exist yet (with --set)",
    )
    parser.add_argument(
        "--skip", action="store_true",
        help="Record the role as explicitly skipped, no path (with --set)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of human-readable text",
    )
    parser.add_argument(
        "--registry", default=None, metavar="PATH",
        help="Override path to resolver_roles.yaml "
             "(default: references/resolver_roles.yaml next to this script)",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry) if args.registry else _default_registry_path()

    try:
        project_root = find_project_root(Path.cwd())
        registry = load_role_registry(registry_path)

        if args.check:
            workspace = load_workspace(project_root)
            result = check_roles(registry, workspace)
        elif args.role:
            workspace = load_workspace(project_root)
            result = resolve_role(args.role, registry, workspace, project_root)
        else:
            result = set_role(
                args.set, registry, project_root,
                path=args.path, readonly_sources=args.readonly,
                create=args.create, skip=args.skip,
            )
    except (ProjectRootNotFoundError, WorkspaceParseError, RoleRegistryError,
            UnknownRoleError, ValueError) as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error) if args.json else f"Error: {exc}")
        sys.exit(1)

    print(json.dumps(result) if args.json else _format_human(result))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest skills/resource-resolver/scripts/tests/test_resolve.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add skills/resource-resolver/scripts/resolve.py skills/resource-resolver/scripts/tests/test_resolve.py
git commit -m "feat(resource-resolver): add --set confirmation action"
```

---

### Task 4: Role registry data file + `resource-resolver` SKILL.md

**Files:**
- Create: `skills/resource-resolver/references/resolver_roles.yaml`
- Create: `skills/resource-resolver/SKILL.md`

**Interfaces:**
- Consumes: `resolve.py`'s `--check`/`--role`/`--set` CLI contract from Tasks 1-3.
- Produces: the 6-role registry consumed by every migrated skill in Tasks 6-9; the `/resolve-workspace` one-time setup flow documented for users.

- [ ] **Step 1: Create the role registry**

Create `skills/resource-resolver/references/resolver_roles.yaml`:

```yaml
version: 1
roles:
  - name: research_log
    description: Structured research log entries (one file per experiment/session)
    aliases: [research_log, research-log, lab_notes, labnotes, logs]
    default_relative_path: docs/research_log
    consumed_by: [research-log, research-mode]

  - name: experiment_config
    description: Experiment parameter/config files (yaml/json/toml run configs)
    aliases: [experiment_config, configs, experiments, runs, params]
    default_relative_path: configs
    consumed_by: [research-mode]

  - name: results
    description: Experiment outputs, metrics, artifacts
    aliases: [results, outputs, artifacts, evals]
    default_relative_path: results
    consumed_by: [research-log, report-slides]

  - name: slides
    description: Generated presentation decks and slide assets
    aliases: [slides, presentations, decks, reports]
    default_relative_path: docs/slides
    consumed_by: [report-slides]

  - name: paper
    description: Manuscript drafts and paper-related documents
    aliases: [paper, papers, manuscript, manuscripts, draft]
    default_relative_path: docs/papers
    consumed_by: [academic-pipeline]

  - name: bibliography
    description: Reference/citation libraries (BibTeX, Zotero exports, etc.)
    aliases: [bibliography, references, citations, bib]
    default_relative_path: docs/bibliography
    consumed_by: [deep-research, academic-pipeline]
```

- [ ] **Step 2: Verify the registry loads via the CLI built in Tasks 1-3**

Run (from repo root, in a scratch directory that has its own `.git` so `find_project_root` succeeds independently of this repo's real workspace state):

```bash
mkdir -p /tmp/resolver-smoke-test && cd /tmp/resolver-smoke-test && git init -q
python3 "$OLDPWD/skills/resource-resolver/scripts/resolve.py" --check --json
cd "$OLDPWD" && rm -rf /tmp/resolver-smoke-test
```

Expected: JSON output listing all 6 role names under `"unconfigured"`, confirming the registry parses and every role name matches the CLI's expectations. (No `--registry` flag needed here — this exercises the real default path resolution in `_default_registry_path()`.)

- [ ] **Step 3: Write `skills/resource-resolver/SKILL.md`**

Create `skills/resource-resolver/SKILL.md`:

```markdown
---
name: resource-resolver
description: Maps logical resource roles (research log, experiment config, results, slides, paper, bibliography) to actual project paths, without assuming any folder naming convention. Use when a skill needs to know where to read or write a project resource, or when the user wants to set up or change where these resources live. Triggers on phrases like "set up my workspace", "where should slides go", "change the research log location", "resolve workspace".
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Resource Resolver

Maps six logical resource **roles** to actual project paths, confirmed by the
user and recorded in `.research/workspace.yaml`. Other skills call `resolve.py`
instead of hardcoding paths like `docs/research_log/`. This skill never moves,
reorganizes, or renames existing files, and never creates a directory without
an explicit user-confirmed `--create`.

## Roles

| Role | Default | Consumed by |
|------|---------|-------------|
| `research_log` | `docs/research_log` | research-log, research-mode |
| `experiment_config` | `configs` | research-mode |
| `results` | `results` | research-log, report-slides |
| `slides` | `docs/slides` | report-slides |
| `paper` | `docs/papers` | academic-pipeline |
| `bibliography` | `docs/bibliography` | deep-research, academic-pipeline |

Full definitions (aliases used for discovery, descriptions) live in
`references/resolver_roles.yaml`.

## `/resolve-workspace` (one-time setup)

Run this once per project to confirm all six roles up front:

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
python "$RESOLVE" --check --json
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
python $RESOLVE --check --json
```

For every role listed under `"unconfigured"`:

1. Run `python "$RESOLVE" --role <name> --json`.
2. If `status` is `"unresolved"`, present the `candidates` list to the user
   and let them pick one (or name a different path).
3. If `status` is `"no_candidates"`, tell the user no matching directory was
   found and suggest `default_relative_path`; let them accept it, name a
   different path, or say the role doesn't apply to this project.
4. If the user names a path that doesn't exist yet, ask explicitly whether to
   create it. Only then call `--set <name> --path <chosen-path> --create`.
   If it already exists, omit `--create`.
5. If the user says a role doesn't apply here, call
   `python "$RESOLVE" --set <name> --skip` so future checks don't re-ask.

## First-use role confirmation (lazy fallback)

If a skill needs a role that turns out to be unconfigured mid-task, don't stop
and force the user through the full setup flow — run the same `--role` /
`--set` sequence above for just that one role, inline, then continue.

## Calling convention for other skills

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
ROLE_JSON=$(python "$RESOLVE" --role <role_name> --json)
TARGET_DIR=$(echo "$ROLE_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('primary',''))")
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
$RoleJson = python $RESOLVE --role <role_name> --json | ConvertFrom-Json
$TargetDir = $RoleJson.primary
```

If `$TARGET_DIR` (or `$TargetDir`) comes back empty, the role is unconfigured
— follow "First-use role confirmation" above before proceeding.

## Optional: SessionStart hook

Add this to `.claude/settings.json` (project or user level, via the
`update-config` skill or by hand) to silently surface unconfigured roles at
the start of every session, instead of relying on a skill to think to check:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "f=$(find ~/.claude -path '*/resource-resolver/scripts/resolve.py' 2>/dev/null | head -1); [ -n \"$f\" ] && python3 \"$f\" --check || true"
          }
        ]
      }
    ]
  }
}
```

This hook is intentionally allowed to fail silently (`|| true`) — it's a
convenience trigger, not a requirement. Every skill above still resolves
roles lazily on first use even if this hook is never installed.

## Non-goals

- Never moves, reorganizes, or renames existing user files or directories.
- Never creates a directory without an explicit user-confirmed `--create`.
- Never fetches or syncs external services (Notion, Zotero, Google Drive,
  etc.) — a `readonly_sources` or `primary` entry containing `://` is stored
  and returned verbatim, never dereferenced.
- `.research/state/`, `.research/events/`, `.research/indexes/`,
  `.research/cache/` are reserved empty directories for future subsystems;
  this skill does not read or write inside them.
```

- [ ] **Step 4: Verify the SessionStart hook command fails silently**

The hook snippet documented in `SKILL.md` must never block session startup,
even before `resolve.py` has ever been installed. Verify the `|| true`
guarantee directly:

```bash
cd /tmp && rm -rf hook-smoke-test && mkdir hook-smoke-test && cd hook-smoke-test
f=$(find ~/.claude -path '*/resource-resolver/scripts/resolve.py' 2>/dev/null | head -1); [ -n "$f" ] && python3 "$f" --check || true
echo "exit code: $?"
cd - && rm -rf /tmp/hook-smoke-test
```

Expected: `exit code: 0` even though `~/.claude` has no installed
`resource-resolver` yet in this environment (the `find` returns nothing, `-n
"$f"` is false, the `&&` short-circuits, and `|| true` guarantees success).

- [ ] **Step 5: Commit**

```bash
git add skills/resource-resolver/references/resolver_roles.yaml skills/resource-resolver/SKILL.md
git commit -m "feat(resource-resolver): add role registry and SKILL.md"
```

---

### Task 5: `install.sh` — always install `resource-resolver`

**Files:**
- Modify: `install.sh:14-16`

**Interfaces:**
- Consumes: `skills/resource-resolver/` directory produced by Tasks 1-4.

- [ ] **Step 1: Modify the SKILLS arrays**

In `install.sh`, replace:

```bash
# Lab skills (experiment journal + presentations + mode routing)
LAB_SKILLS=("research-log" "report-slides" "research-mode")
# Academic Research Skills (deep research, paper writing, review, pipeline)
ARS_SKILLS=("deep-research" "academic-paper" "academic-paper-reviewer" "academic-pipeline")
# Default: install everything
SKILLS=("${LAB_SKILLS[@]}" "${ARS_SKILLS[@]}")
```

with:

```bash
# Shared foundation both lab and ARS skills depend on -- always installed
RESOLVER_SKILLS=("resource-resolver")
# Lab skills (experiment journal + presentations + mode routing)
LAB_SKILLS=("research-log" "report-slides" "research-mode")
# Academic Research Skills (deep research, paper writing, review, pipeline)
ARS_SKILLS=("deep-research" "academic-paper" "academic-paper-reviewer" "academic-pipeline")
# Default: install everything
SKILLS=("${RESOLVER_SKILLS[@]}" "${LAB_SKILLS[@]}" "${ARS_SKILLS[@]}")
```

Then find the `--ars-only` / `--lab-only` argument handling further down and update it so `resource-resolver` stays in `SKILLS` in both branches. Replace:

```bash
    --ars-only)  SKILLS=("${ARS_SKILLS[@]}") ;;
    --lab-only)  SKILLS=("${LAB_SKILLS[@]}") ;;
```

with:

```bash
    --ars-only)  SKILLS=("${RESOLVER_SKILLS[@]}" "${ARS_SKILLS[@]}") ;;
    --lab-only)  SKILLS=("${RESOLVER_SKILLS[@]}" "${LAB_SKILLS[@]}") ;;
```

- [ ] **Step 2: Verify with a shell syntax check and a dry-run install**

Run: `bash -n install.sh`
Expected: no output (syntax OK).

Run (local, isolated install to a scratch `DEST`, doesn't touch the real `~/.claude`):

```bash
cd /tmp && rm -rf resolver-install-test && mkdir resolver-install-test && cd resolver-install-test
bash "$OLDPWD/install.sh" --local --ars-only
ls .claude/skills
cd "$OLDPWD" && rm -rf /tmp/resolver-install-test
```

Expected: `.claude/skills` contains `resource-resolver` alongside the four ARS skills. Repeat with `--lab-only` and expect `resource-resolver` alongside the three lab skills.

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "fix(install): always install resource-resolver alongside any skill subset"
```

---

### Task 6: Migrate `research-log` to the Resolver

**Files:**
- Modify: `skills/research-log/SKILL.md`

**Interfaces:**
- Consumes: `resolve.py --role research_log --json` / `--set research_log ...` CLI contract from Tasks 1-4.

- [ ] **Step 1: Add the resolution step to the Storage section**

In `skills/research-log/SKILL.md`, replace:

```markdown
## Storage

All files in `docs/research_log/` (relative to project root). Create it if absent.

Filename: `YYYY-MM-DD_<experiment-slug>.md`
Index: `docs/research_log/INDEX.md` (auto-generated, never hand-edited)
Milestones: `docs/research_log/MILESTONES.md` (auto-generated once milestone mode is active — see Milestone Mode below; never hand-edited)
```

with:

```markdown
## Storage

**Resolve the log directory first** (see `skills/resource-resolver/SKILL.md`):

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
ROLE_JSON=$(python "$RESOLVE" --role research_log --json)
RESEARCH_LOG_DIR=$(echo "$ROLE_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('primary',''))")
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
$RoleJson = python $RESOLVE --role research_log --json | ConvertFrom-Json
$RESEARCH_LOG_DIR = $RoleJson.primary
```

If `$RESEARCH_LOG_DIR` comes back empty, the role isn't configured yet: follow
"First-use role confirmation" in `skills/resource-resolver/SKILL.md` (surface
`candidates` or `default_relative_path` from `$ROLE_JSON`, get the user's
confirmation, then `--set research_log --path <path> [--create]`) before
continuing. Every `docs/research_log` path below means `$RESEARCH_LOG_DIR`.

Filename: `YYYY-MM-DD_<experiment-slug>.md`
Index: `$RESEARCH_LOG_DIR/INDEX.md` (auto-generated, never hand-edited)
Milestones: `$RESEARCH_LOG_DIR/MILESTONES.md` (auto-generated once milestone mode is active — see Milestone Mode below; never hand-edited)
```

- [ ] **Step 2: Replace every remaining hardcoded `docs/research_log` occurrence**

Apply each of these exact replacements in `skills/research-log/SKILL.md` (frontmatter `description:` on line 3 is intentionally excluded — it's skill-routing trigger text, not a runtime path):

| Old | New |
|-----|-----|
| `` Once `docs/research_log/MILESTONES.md` exists, always keep `` | `` Once `$RESEARCH_LOG_DIR/MILESTONES.md` exists, always keep `` |
| `python "$LOG_STATS" --dir docs/research_log --json` | `python "$LOG_STATS" --dir "$RESEARCH_LOG_DIR" --json` |
| `python $LOG_STATS --dir docs\research_log --json` | `python $LOG_STATS --dir $RESEARCH_LOG_DIR --json` |
| `` Write `docs/research_log/MILESTONES.md` (format below) `` | `` Write `$RESEARCH_LOG_DIR/MILESTONES.md` (format below) `` |
| `PRIOR=$(ls -t docs/research_log/*.md 2>/dev/null \|` | `PRIOR=$(ls -t "$RESEARCH_LOG_DIR"/*.md 2>/dev/null \|` |
| `$PRIOR = Get-ChildItem docs\research_log -Filter "*.md" \|` | `$PRIOR = Get-ChildItem $RESEARCH_LOG_DIR -Filter "*.md" \|` |
| `` **Step 3 — Milestone check (only if `docs/research_log/MILESTONES.md` already exists):** `` | `` **Step 3 — Milestone check (only if `$RESEARCH_LOG_DIR/MILESTONES.md` already exists):** `` |
| `` If `docs/research_log/MILESTONES.md` already exists, also update it: append `` | `` If `$RESEARCH_LOG_DIR/MILESTONES.md` already exists, also update it: append `` |
| `` Confirm: `✓ Created docs/research_log/YYYY-MM-DD_<slug>.md` `` | `` Confirm: `✓ Created $RESEARCH_LOG_DIR/YYYY-MM-DD_<slug>.md` `` |
| `ls -t docs/research_log/*.md \| grep -v INDEX \| grep -v MILESTONES \| head -5` | `ls -t "$RESEARCH_LOG_DIR"/*.md \| grep -v INDEX \| grep -v MILESTONES \| head -5` |
| `` Rebuild INDEX.md. If `docs/research_log/MILESTONES.md` exists, rebuild it too. `` | `` Rebuild INDEX.md. If `$RESEARCH_LOG_DIR/MILESTONES.md` exists, rebuild it too. `` |
| `find docs/research_log -maxdepth 1 -name "*.md" ! -name "INDEX.md" ! -name "MILESTONES.md" \| sort -r` | `find "$RESEARCH_LOG_DIR" -maxdepth 1 -name "*.md" ! -name "INDEX.md" ! -name "MILESTONES.md" \| sort -r` |
| `` If `docs/research_log/MILESTONES.md` already exists, rebuild it too, from `` | `` If `$RESEARCH_LOG_DIR/MILESTONES.md` already exists, rebuild it too, from `` |
| `python "$SECTION_QUERY" types --dir docs/research_log --budget 4000` (first occurrence) | `python "$SECTION_QUERY" types --dir "$RESEARCH_LOG_DIR" --budget 4000` |
| `python $SECTION_QUERY types --dir docs\research_log --budget 4000` | `python $SECTION_QUERY types --dir $RESEARCH_LOG_DIR --budget 4000` |
| `python "$SECTION_QUERY" types --dir docs/research_log --budget 4000 --cursor "<opaque-cursor>"` | `python "$SECTION_QUERY" types --dir "$RESEARCH_LOG_DIR" --budget 4000 --cursor "<opaque-cursor>"` |
| `  --dir docs/research_log \` (5 occurrences, in the `search`/`fetch` examples) | `  --dir "$RESEARCH_LOG_DIR" \` |
| `1. The current project contains a non-empty \`docs/research_log/\` journal.` | `1. The current project contains a non-empty research log journal (see the resolved \`$RESEARCH_LOG_DIR\` from Storage above).` |
| `- If \`docs/research_log/\` does not exist, create it silently.` | `- If \`$RESEARCH_LOG_DIR\` does not exist, create it silently — the directory itself was already confirmed by the user during role resolution; this only covers the directory not yet existing on disk.` |

- [ ] **Step 3: Verify no unmigrated occurrences remain**

Run: `grep -n "docs/research_log\|docs\\\\research_log" skills/research-log/SKILL.md`
Expected: only line 3 (the frontmatter `description:` field) matches.

- [ ] **Step 4: Commit**

```bash
git add skills/research-log/SKILL.md
git commit -m "refactor(research-log): resolve research_log directory via resource-resolver"
```

---

### Task 7: Migrate `report-slides` to the Resolver (+ cross-role `research_log` read)

**Files:**
- Modify: `skills/report-slides/SKILL.md`
- Modify: `skills/report-slides/scripts/setup.sh`
- Modify: `skills/report-slides/scripts/setup.ps1`
- Modify: `skills/report-slides/scripts/tests/test_setup_scripts.py`

**Interfaces:**
- Consumes: `resolve.py --role slides --json`, `--role research_log --json`, `--set ...` CLI contract from Tasks 1-4.

- [ ] **Step 1: Parameterize `setup.sh` to accept a slides directory**

In `skills/report-slides/scripts/setup.sh`, replace:

```bash
#!/usr/bin/env bash
# report-slides project setup — copies required scripts into the current project.
# Run from the project root:
#   bash "$(find ~/.claude -path "*/report-slides/scripts/setup.sh" | head -1)"
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_DIR="$(dirname "$SCRIPT_DIR")"

mkdir -p scripts docs/slides/reports docs/slides/assets/diagrams

cp "$SCRIPT_DIR/generate_slides.py" scripts/
cp "$SCRIPT_DIR/validate_diagram_manifest.py" scripts/
cp "$SCRIPT_DIR/render_review_sheet.py" scripts/

echo "report-slides setup complete:"
echo "  scripts/generate_slides.py"
echo "  scripts/validate_diagram_manifest.py"
echo "  scripts/render_review_sheet.py"
echo "  docs/slides/reports/"
echo "  docs/slides/assets/diagrams/"
```

with:

```bash
#!/usr/bin/env bash
# report-slides project setup — copies required scripts into the current project.
# Run from the project root:
#   bash "$(find ~/.claude -path "*/report-slides/scripts/setup.sh" | head -1)" [SLIDES_DIR]
# SLIDES_DIR defaults to docs/slides; SKILL.md resolves it via resource-resolver
# and passes it explicitly.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_DIR="$(dirname "$SCRIPT_DIR")"
SLIDES_DIR="${1:-docs/slides}"

mkdir -p scripts "$SLIDES_DIR/reports" "$SLIDES_DIR/assets/diagrams"

cp "$SCRIPT_DIR/generate_slides.py" scripts/
cp "$SCRIPT_DIR/validate_diagram_manifest.py" scripts/
cp "$SCRIPT_DIR/render_review_sheet.py" scripts/

echo "report-slides setup complete:"
echo "  scripts/generate_slides.py"
echo "  scripts/validate_diagram_manifest.py"
echo "  scripts/render_review_sheet.py"
echo "  $SLIDES_DIR/reports/"
echo "  $SLIDES_DIR/assets/diagrams/"
```

(The trailing lines about Pillow / set-style / Mermaid are unchanged — leave them as-is below this block.)

- [ ] **Step 2: Parameterize `setup.ps1` to accept a slides directory**

In `skills/report-slides/scripts/setup.ps1`, replace:

```powershell
# setup.ps1 — report-slides project setup for Windows PowerShell
# Run from the project root:
#   & (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter setup.ps1 |
#       Where-Object FullName -like '*report-slides*' | Select-Object -First 1).FullName

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

New-Item -ItemType Directory -Force -Path "scripts", "docs\slides\reports", "docs\slides\assets\diagrams" | Out-Null
Copy-Item "$ScriptDir\generate_slides.py" "scripts\" -Force
Copy-Item "$ScriptDir\validate_diagram_manifest.py" "scripts\" -Force
Copy-Item "$ScriptDir\render_review_sheet.py" "scripts\" -Force

Write-Host "report-slides setup complete:"
Write-Host "  scripts\generate_slides.py"
Write-Host "  scripts\validate_diagram_manifest.py"
Write-Host "  scripts\render_review_sheet.py"
Write-Host "  docs\slides\reports\"
Write-Host "  docs\slides\assets\diagrams\"
```

with:

```powershell
# setup.ps1 — report-slides project setup for Windows PowerShell
# Run from the project root:
#   & (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter setup.ps1 |
#       Where-Object FullName -like '*report-slides*' | Select-Object -First 1).FullName [SlidesDir]
# SlidesDir defaults to docs\slides; SKILL.md resolves it via resource-resolver
# and passes it explicitly.

param(
    [string]$SlidesDir = "docs\slides"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

New-Item -ItemType Directory -Force -Path "scripts", "$SlidesDir\reports", "$SlidesDir\assets\diagrams" | Out-Null
Copy-Item "$ScriptDir\generate_slides.py" "scripts\" -Force
Copy-Item "$ScriptDir\validate_diagram_manifest.py" "scripts\" -Force
Copy-Item "$ScriptDir\render_review_sheet.py" "scripts\" -Force

Write-Host "report-slides setup complete:"
Write-Host "  scripts\generate_slides.py"
Write-Host "  scripts\validate_diagram_manifest.py"
Write-Host "  scripts\render_review_sheet.py"
Write-Host "  $SlidesDir\reports\"
Write-Host "  $SlidesDir\assets\diagrams\"
```

(The trailing lines about Pillow / set-style / Mermaid are unchanged.)

- [ ] **Step 3: Fix and extend `test_setup_scripts.py`**

In `skills/report-slides/scripts/tests/test_setup_scripts.py`, replace the PowerShell assertion:

```python
    assert "docs\\slides\\assets\\diagrams" in setup_text
```

with:

```python
    assert 'docs\\slides"' in setup_text  # default $SlidesDir value preserved
```

Then append a new test to the same file:

```python
def test_setup_sh_accepts_custom_slides_dir(tmp_path: Path) -> None:
    """A caller-supplied SLIDES_DIR argument overrides the docs/slides default."""
    result = subprocess.run(
        ["bash", str(SETUP_SH), "custom/slides/root"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "custom/slides/root/reports/" in result.stdout
    assert (tmp_path / "custom/slides/root/reports").is_dir()
    assert (tmp_path / "custom/slides/root/assets/diagrams").is_dir()
    assert not (tmp_path / "docs").exists()
```

- [ ] **Step 4: Run the setup script tests**

Run: `python3 -m pytest skills/report-slides/scripts/tests/test_setup_scripts.py -v`
Expected: PASS (3 passed — the original default-path test still passes unchanged since the new `SLIDES_DIR` argument is optional).

- [ ] **Step 5: Add resolution to `SKILL.md`'s Setup section**

In `skills/report-slides/SKILL.md`, replace:

```markdown
## Setup (first use in a project)

**macOS / Linux / Git Bash:**
```bash
bash "$(find ~/.claude -path "*/report-slides/scripts/setup.sh" | head -1)"
```

**Windows (PowerShell):**
```powershell
& (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter setup.ps1 |
    Where-Object FullName -like "*report-slides*" | Select-Object -First 1).FullName
```

This copies `generate_slides.py`, `validate_diagram_manifest.py`, and `render_review_sheet.py` into `scripts/` and creates both `docs/slides/reports/` and `docs/slides/assets/diagrams/`. `to_pptx.py` stays in the skill bundle and is invoked directly from there.
```

with:

```markdown
## Setup (first use in a project)

**Resolve the slides and research-log directories first** (see
`skills/resource-resolver/SKILL.md`):

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
SLIDES_DIR=$(python "$RESOLVE" --role slides --json | python3 -c "import json,sys;print(json.load(sys.stdin).get('primary',''))")
RESEARCH_LOG_DIR=$(python "$RESOLVE" --role research_log --json | python3 -c "import json,sys;print(json.load(sys.stdin).get('primary',''))")
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
$SLIDES_DIR = (python $RESOLVE --role slides --json | ConvertFrom-Json).primary
$RESEARCH_LOG_DIR = (python $RESOLVE --role research_log --json | ConvertFrom-Json).primary
```

If either comes back empty, that role is unconfigured — follow "First-use
role confirmation" in `skills/resource-resolver/SKILL.md` before continuing.
Every `docs/slides` reference below means `$SLIDES_DIR`; every
`docs/research_log` reference means `$RESEARCH_LOG_DIR`.

**macOS / Linux / Git Bash:**
```bash
bash "$(find ~/.claude -path "*/report-slides/scripts/setup.sh" | head -1)" "$SLIDES_DIR"
```

**Windows (PowerShell):**
```powershell
& (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter setup.ps1 |
    Where-Object FullName -like "*report-slides*" | Select-Object -First 1).FullName $SLIDES_DIR
```

This copies `generate_slides.py`, `validate_diagram_manifest.py`, and `render_review_sheet.py` into `scripts/` and creates both `$SLIDES_DIR/reports/` and `$SLIDES_DIR/assets/diagrams/`. `to_pptx.py` stays in the skill bundle and is invoked directly from there.
```

- [ ] **Step 6: Replace every remaining hardcoded `docs/slides` / `docs/research_log` occurrence in `SKILL.md`**

Apply each of these exact replacements (frontmatter `description:` on line 3 has no path references, nothing to exclude there):

| Old | New |
|-----|-----|
| `` **Project default:** if `docs/slides/_style.md` exists it is applied automatically to every deck. `` | `` **Project default:** if `$SLIDES_DIR/_style.md` exists it is applied automatically to every deck. `` |
| `` To **create a custom style**: make `docs/slides/styles/<name>.md` using the schema in `` | `` To **create a custom style**: make `$SLIDES_DIR/styles/<name>.md` using the schema in `` |
| `` `references/styles/STYLES.md`, then copy it to `docs/slides/_style.md` to activate it as the project default. `` | `` `references/styles/STYLES.md`, then copy it to `$SLIDES_DIR/_style.md` to activate it as the project default. `` |
| `cat docs/research_log/INDEX.md 2>/dev/null \` | `cat "$RESEARCH_LOG_DIR/INDEX.md" 2>/dev/null \` |
| `  \|\| find docs/research_log -maxdepth 1 -name "*.md" ! -name "INDEX.md" \| sort -r \| head -20` | `  \|\| find "$RESEARCH_LOG_DIR" -maxdepth 1 -name "*.md" ! -name "INDEX.md" \| sort -r \| head -20` |
| `` 6. Style? (skip = use `docs/slides/_style.md` if present / name a built-in / `custom` to create one) `` | `` 6. Style? (skip = use `$SLIDES_DIR/_style.md` if present / name a built-in / `custom` to create one) `` |
| `[ -f docs/slides/_style.md ] && STYLE_FILE="docs/slides/_style.md"` | `[ -f "$SLIDES_DIR/_style.md" ] && STYLE_FILE="$SLIDES_DIR/_style.md"` |
| `` 1. `docs/slides/styles/<name>.md` (project-local) `` | `` 1. `$SLIDES_DIR/styles/<name>.md` (project-local) `` |
| `` and ask for the required frontmatter values, then write `docs/slides/styles/<name>.md`. `` | `` and ask for the required frontmatter values, then write `$SLIDES_DIR/styles/<name>.md`. `` |
| `` Output directory: `docs/slides/reports/YYYY-MM-DD_<name>/` `` | `` Output directory: `$SLIDES_DIR/reports/YYYY-MM-DD_<name>/` `` |
| `cd "$(find ~/.claude -path "*/report-slides/scripts" -type d \| head -1)"` | unchanged (this locates the skill bundle, not a resolved resource) |
| `    --slides docs/slides/reports/YYYY-MM-DD_<name>/ \` (native shapes example) | `    --slides "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/" \` |
| `    --out    docs/slides/reports/YYYY-MM-DD_<name>/deck.pptx` (native shapes example) | `    --out    "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/deck.pptx"` |
| `    --slides docs/slides/reports/YYYY-MM-DD_<name>/ \` (SVG embed example) | `    --slides "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/" \` |
| `    --out    docs/slides/reports/YYYY-MM-DD_<name>/deck.pptx` (SVG embed example) | `    --out    "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/deck.pptx"` |

Leave line 96 (`BRIDGE="$(find ~/.claude -path "*/research-lab-skills/bridge/scripts/passport_to_log.py" ...)"`) and line 558 (`python3 skills/report-slides/scripts/validate_visual_review.py ...`) unchanged — they reference the skill bundle's own scripts, not a resolved resource role, and the `bridge/` install gap they depend on is explicitly out of scope for this plan (see spec's "Installation gap" section).

- [ ] **Step 7: Verify no unmigrated occurrences remain**

Run: `grep -n "docs/slides\|docs/research_log" skills/report-slides/SKILL.md`
Expected: no matches.

- [ ] **Step 8: Commit**

```bash
git add skills/report-slides/SKILL.md skills/report-slides/scripts/setup.sh skills/report-slides/scripts/setup.ps1 skills/report-slides/scripts/tests/test_setup_scripts.py
git commit -m "refactor(report-slides): resolve slides and research_log directories via resource-resolver"
```

---

### Task 8: Adopt `bibliography` role in `deep-research`

**Files:**
- Modify: `skills/deep-research/SKILL.md`

**Interfaces:**
- Consumes: `resolve.py --role bibliography --json` / `--set bibliography ...` CLI contract from Tasks 1-4.

- [ ] **Step 1: Add a Resource Resolver Integration section**

In `skills/deep-research/SKILL.md`, find this block (currently at lines 340-358):

```markdown
## Handoff Protocol: deep-research → academic-paper

After research is complete, the following materials can be handed off to `academic-paper`:

1. **Research Question Brief** (from research_question_agent)
2. **Methodology Blueprint** (from research_architect_agent)
3. **Annotated Bibliography** (from bibliography_agent)
4. **Synthesis Report** (from synthesis_agent)
5. **[If socratic mode] INSIGHT Collection and Research Plan Summary**

**Trigger**: User says "now help me write a paper" or "write a paper based on this"

`academic-paper`'s `intake_agent` will automatically detect available materials and skip redundant steps:
- Has RQ Brief -> skip topic scoping
- Has Bibliography -> skip literature search
- Has Synthesis -> accelerate findings / discussion writing

See `examples/handoff_to_paper.md` for a detailed handoff example.

---
```

Insert a new section immediately after it (before the next `---` becomes the section boundary, i.e. right after `See examples/handoff_to_paper.md for a detailed handoff example.` and its existing `---`):

```markdown
## Resource Resolver Integration

When the user wants the **Annotated Bibliography** (or any other research
artifact) saved to disk rather than just handed off in-conversation, resolve
where it belongs instead of asking ad hoc every time (see
`skills/resource-resolver/SKILL.md`):

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
ROLE_JSON=$(python "$RESOLVE" --role bibliography --json)
BIBLIOGRAPHY_DIR=$(echo "$ROLE_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('primary',''))")
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
$BIBLIOGRAPHY_DIR = (python $RESOLVE --role bibliography --json | ConvertFrom-Json).primary
```

If `$BIBLIOGRAPHY_DIR` comes back empty, follow "First-use role confirmation"
in `skills/resource-resolver/SKILL.md`: present the returned `candidates` (or
`default_relative_path`) to the user, get their confirmation, then
`--set bibliography --path <path> [--create]`. This replaces asking the user
where to save on every run with a one-time-then-cached confirmation.

---
```

- [ ] **Step 2: Verify placement**

Run: `grep -n "^## " skills/deep-research/SKILL.md | sed -n '/Handoff Protocol/,/Full Academic Pipeline/p'`
Expected: `## Resource Resolver Integration` appears between `## Handoff Protocol: deep-research → academic-paper` and `## Full Academic Pipeline`.

- [ ] **Step 3: Commit**

```bash
git add skills/deep-research/SKILL.md
git commit -m "feat(deep-research): adopt bibliography role via resource-resolver"
```

---

### Task 9: Adopt `paper` role in `academic-pipeline`

**Files:**
- Modify: `skills/academic-pipeline/SKILL.md`

**Interfaces:**
- Consumes: `resolve.py --role paper --json` / `--set paper ...` CLI contract from Tasks 1-4.

- [ ] **Step 1: Add resolution to Step 1: INTAKE & DETECTION**

In `skills/academic-pipeline/SKILL.md`, find:

```markdown
### Step 1: INTAKE & DETECTION

```
pipeline_orchestrator_agent analyzes the user's input:

1. What materials does the user have?
   - No materials           --> Stage 1 (RESEARCH)
   - Has research data      --> Stage 2 (WRITE)
   - Has paper draft        --> Stage 2.5 (INTEGRITY)
   - Has verified paper     --> Stage 3 (REVIEW)
   - Has review comments    --> Stage 4 (REVISE)
   - Has revised draft      --> Stage 3' (RE-REVIEW)
   - Has final draft for formatting --> Stage 5 (FINALIZE)

2. What is the user's goal?
   - Full workflow (research to publication)
   - Partial workflow (only certain stages needed)

3. Determine entry point, confirm with user
```
```

Replace it with:

```markdown
### Step 1: INTAKE & DETECTION

```
pipeline_orchestrator_agent analyzes the user's input:

1. What materials does the user have?
   - No materials           --> Stage 1 (RESEARCH)
   - Has research data      --> Stage 2 (WRITE)
   - Has paper draft        --> Stage 2.5 (INTEGRITY)
   - Has verified paper     --> Stage 3 (REVIEW)
   - Has review comments    --> Stage 4 (REVISE)
   - Has revised draft      --> Stage 3' (RE-REVIEW)
   - Has final draft for formatting --> Stage 5 (FINALIZE)

2. What is the user's goal?
   - Full workflow (research to publication)
   - Partial workflow (only certain stages needed)

3. Determine entry point, confirm with user
```

**Resolve the paper output location once, here at intake** (see
`skills/resource-resolver/SKILL.md`), so it's ready by the time Stage 5 needs
it — don't re-ask at every stage:

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
ROLE_JSON=$(python "$RESOLVE" --role paper --json)
PAPER_DIR=$(echo "$ROLE_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('primary',''))")
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
$PAPER_DIR = (python $RESOLVE --role paper --json | ConvertFrom-Json).primary
```

If `$PAPER_DIR` comes back empty, follow "First-use role confirmation" in
`skills/resource-resolver/SKILL.md` before continuing intake. Carry
`$PAPER_DIR` through pipeline state (`state_tracker_agent`) so Stage 5
(`format-convert -> final output`) writes there without re-resolving.
```

- [ ] **Step 2: Note the carried-through path at the Stage 4.5 -> 5 transition**

In `skills/academic-pipeline/SKILL.md`, find (inside the Step 4: TRANSITION list):

```markdown
   - Stage 4.5 --> 5: Pass verified final draft to format-convert mode
```

Replace it with:

```markdown
   - Stage 4.5 --> 5: Pass verified final draft, plus the `$PAPER_DIR` resolved at intake, to format-convert mode
```

- [ ] **Step 3: Verify placement**

Run: `grep -n "PAPER_DIR\|Resource Resolver" skills/academic-pipeline/SKILL.md`
Expected: three matches — the intake resolution block and the two `$PAPER_DIR` mentions (intake + Stage 4.5 -> 5 transition).

- [ ] **Step 4: Commit**

```bash
git add skills/academic-pipeline/SKILL.md
git commit -m "feat(academic-pipeline): adopt paper role via resource-resolver"
```

---

## Post-plan verification (run once all tasks are complete)

```bash
python3 -m pytest skills/resource-resolver/scripts/tests/ skills/report-slides/scripts/tests/test_setup_scripts.py -v
grep -rn "docs/research_log\|docs\\\\research_log" skills/research-log/SKILL.md   # expect: only the description: line
grep -rn "docs/slides" skills/report-slides/SKILL.md                              # expect: no matches
bash -n install.sh
```
