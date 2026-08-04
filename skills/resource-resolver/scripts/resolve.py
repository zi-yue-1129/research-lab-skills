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
_SKIP_DIR_NAMES = frozenset({
    "node_modules", "__pycache__", "venv", "dist", "build", "site-packages",
})


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
    if status == "skipped":
        return f"{role}: skipped"
    if status == "ok":
        created_note = " (created)" if result.get("created") else ""
        return f"{role}: set to {result['primary']}{created_note}"
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
