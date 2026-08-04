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
from typing import Any, Dict, List

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
