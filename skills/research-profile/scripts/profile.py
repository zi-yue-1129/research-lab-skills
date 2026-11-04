#!/usr/bin/env python3
"""profile.py -- Research Profile CLI: list, validate, and resolve named profiles.

A profile is a named, selectable bundle of conventions that would otherwise be
hardcoded into a skill: a writing voice, a language policy, a field's
references, a venue's citation style, a slide style. Skills keep general
defaults in their core and read the active profile through this script.

Usage:
    # Every profile this install ships, with the axes each one sets
    python profile.py --list [--json]

    # One profile, with `extends` merged and file paths made absolute
    python profile.py --show <name> [--json]

    # The profile in force for this project (or the core defaults if none).
    # --session carries a `/profile use <name>` choice made in conversation;
    # it outranks the project file.
    python profile.py --active [--session <name>] [--json]

    # Record or clear the project's profile in .research/profile.yaml
    python profile.py --set <name> [--json]
    python profile.py --clear [--json]

    # Check every profile (or one) against the schema
    python profile.py --validate [<name>] [--json]
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


PROJECT_FILE_RELATIVE_PATH = Path(".research/profile.yaml")
PROFILE_MANIFEST_NAME = "profile.yaml"
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
FOLLOW_USER = "follow-user"

TOP_LEVEL_KEYS = frozenset({"name", "description", "extends", "axes"})
AXES = ("voice", "language", "field", "venue", "slides")
CITATION_STYLES = frozenset({
    "apa7", "chicago-author-date", "chicago-notes", "mla9", "ieee", "vancouver",
})

#: Per axis: allowed keys, and which of them name files inside the profile
#: (a string, or a list of strings for the plural keys).
AXIS_SCHEMA: Dict[str, Dict[str, Any]] = {
    "voice": {"keys": {"rules"}, "file_keys": {"rules"}},
    "language": {"keys": {"body", "abstract", "interface"}, "file_keys": set()},
    "field": {
        "keys": {"domain", "evidence_profile", "references", "ethics",
                 "journals", "examples"},
        "file_keys": {"references", "ethics", "journals", "examples"},
    },
    "venue": {"keys": {"citation_style", "references"},
              "file_keys": {"references"}},
    # slides maps a slide skill's name to one of that skill's own style or
    # preset names; the profile never owns the style files themselves.
    "slides": {"keys": None, "file_keys": set()},
}

#: What every skill does when no profile is active. Consumers read these from
#: `--active` rather than restating them, so the core default lives once.
CORE_DEFAULTS: Dict[str, Any] = {
    "voice": None,
    "language": {"body": FOLLOW_USER, "abstract": [FOLLOW_USER],
                 "interface": FOLLOW_USER},
    "field": None,
    "venue": {"citation_style": None},
    "slides": {},
}


class ProfileError(ValueError):
    """Raised when a profile is missing, malformed, or cannot be resolved."""


class ProjectRootNotFoundError(RuntimeError):
    """Raised when no ancestor directory containing a .git entry can be found."""


def profiles_dir() -> Path:
    """Return the directory holding the bundled profiles.

    Returns:
        ``<skill>/profiles``, resolved from this script's location so it works
        both in the repository and in an installed ``~/.claude/skills`` copy.
    """
    return Path(__file__).resolve().parent.parent / "profiles"


def find_project_root(start: Path) -> Path:
    """Find the nearest ancestor directory containing a .git entry.

    Args:
        start: Directory to begin the upward search from.

    Returns:
        The first directory (start or an ancestor) containing ``.git``.

    Raises:
        ProjectRootNotFoundError: If no such directory exists.
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise ProjectRootNotFoundError(f"no .git found above {start}")


def available_profiles(root: Optional[Path] = None) -> List[str]:
    """List the profile names under the profiles directory.

    Args:
        root: Profiles directory; defaults to :func:`profiles_dir`.

    Returns:
        Sorted names of subdirectories that contain a ``profile.yaml``.
    """
    root = root or profiles_dir()
    if not root.is_dir():
        return []
    return sorted(
        child.name for child in root.iterdir()
        if child.is_dir() and (child / PROFILE_MANIFEST_NAME).is_file()
    )


def load_manifest(name: str, root: Optional[Path] = None) -> Dict[str, Any]:
    """Read one profile's ``profile.yaml`` without resolving ``extends``.

    Args:
        name: Profile name (its directory name).
        root: Profiles directory; defaults to :func:`profiles_dir`.

    Returns:
        The parsed manifest.

    Raises:
        ProfileError: If the profile does not exist or is not a YAML mapping.
    """
    root = root or profiles_dir()
    path = root / name / PROFILE_MANIFEST_NAME
    if not path.is_file():
        known = ", ".join(available_profiles(root)) or "none"
        raise ProfileError(f"unknown profile '{name}' (available: {known})")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: expected a mapping at the top level")
    return data


def validate_manifest(name: str, data: Dict[str, Any],
                      root: Optional[Path] = None) -> List[str]:
    """Check one manifest against the schema.

    Args:
        name: The profile's directory name.
        data: Its parsed manifest.
        root: Profiles directory; defaults to :func:`profiles_dir`.

    Returns:
        Human-readable problems; empty when the manifest is valid.
    """
    root = root or profiles_dir()
    problems: List[str] = []
    where = f"{name}/{PROFILE_MANIFEST_NAME}"

    if not NAME_PATTERN.match(name):
        problems.append(f"{where}: directory name must be kebab-case")
    unknown = set(data) - TOP_LEVEL_KEYS
    if unknown:
        problems.append(f"{where}: unknown keys {sorted(unknown)}")
    if data.get("name") != name:
        problems.append(f"{where}: name '{data.get('name')}' must equal the "
                        f"directory name '{name}'")
    if not isinstance(data.get("description"), str) or not data["description"].strip():
        problems.append(f"{where}: description is required")

    extends = data.get("extends", [])
    if not isinstance(extends, list) or not all(isinstance(e, str) for e in extends):
        problems.append(f"{where}: extends must be a list of profile names")
    else:
        for parent in extends:
            if not (root / parent / PROFILE_MANIFEST_NAME).is_file():
                problems.append(f"{where}: extends unknown profile '{parent}'")

    axes = data.get("axes", {})
    if not isinstance(axes, dict):
        problems.append(f"{where}: axes must be a mapping")
        return problems
    if not axes and not extends:
        problems.append(f"{where}: sets no axes and extends nothing")
    for axis, value in axes.items():
        if axis not in AXIS_SCHEMA:
            problems.append(f"{where}: unknown axis '{axis}' (known: {list(AXES)})")
            continue
        if not isinstance(value, dict):
            problems.append(f"{where}: axis '{axis}' must be a mapping")
            continue
        schema = AXIS_SCHEMA[axis]
        if schema["keys"] is not None:
            extra = set(value) - schema["keys"]
            if extra:
                problems.append(f"{where}: axis '{axis}' has unknown keys {sorted(extra)}")
        for key in schema["file_keys"] & set(value):
            paths = value[key] if isinstance(value[key], list) else [value[key]]
            for rel in paths:
                if not isinstance(rel, str) or not (root / name / rel).is_file():
                    problems.append(f"{where}: {axis}.{key} names missing file '{rel}'")
        if axis == "language":
            problems.extend(_validate_language(where, value))
        if axis == "venue" and "citation_style" in value:
            if value["citation_style"] not in CITATION_STYLES:
                problems.append(f"{where}: venue.citation_style must be one of "
                                f"{sorted(CITATION_STYLES)}")
        if axis == "slides":
            for skill, style in value.items():
                if not isinstance(style, str) or not NAME_PATTERN.match(style):
                    problems.append(f"{where}: slides.{skill} must be a kebab-case "
                                    f"style or preset name")
    return problems


def _validate_language(where: str, value: Dict[str, Any]) -> List[str]:
    """Check the language axis's tags.

    Args:
        where: Location prefix for messages.
        value: The language axis mapping.

    Returns:
        Problems found, if any.
    """
    problems = []
    for key in ("body", "interface"):
        if key in value and not _is_language(value[key]):
            problems.append(f"{where}: language.{key} must be a language tag "
                            f"or '{FOLLOW_USER}'")
    if "abstract" in value:
        tags = value["abstract"]
        if not isinstance(tags, list) or not tags or not all(_is_language(t) for t in tags):
            problems.append(f"{where}: language.abstract must be a non-empty list "
                            f"of language tags or '{FOLLOW_USER}'")
    return problems


def _is_language(tag: Any) -> bool:
    return isinstance(tag, str) and (tag == FOLLOW_USER or bool(LANGUAGE_PATTERN.match(tag)))


def resolve(name: str, root: Optional[Path] = None,
            _chain: Optional[List[str]] = None) -> Dict[str, Any]:
    """Resolve a profile: merge its ``extends`` chain and absolutise file paths.

    Parents apply first, in the order listed, then the profile itself. Within
    an axis, a later profile's keys replace an earlier one's; keys it does not
    set are inherited.

    Args:
        name: Profile to resolve.
        root: Profiles directory; defaults to :func:`profiles_dir`.

    Returns:
        ``{"name", "description", "chain", "axes"}`` where ``chain`` lists
        every profile that contributed, parents first.

    Raises:
        ProfileError: On an unknown profile, an invalid manifest, or a cycle.
    """
    root = root or profiles_dir()
    chain = list(_chain or [])
    if name in chain:
        raise ProfileError(f"extends cycle: {' -> '.join(chain + [name])}")
    data = load_manifest(name, root)
    problems = validate_manifest(name, data, root)
    if problems:
        raise ProfileError("; ".join(problems))

    axes: Dict[str, Dict[str, Any]] = {}
    contributors: List[str] = []
    for parent in data.get("extends", []):
        parent_resolved = resolve(parent, root, chain + [name])
        for c in parent_resolved["chain"]:
            if c not in contributors:
                contributors.append(c)
        for axis, value in parent_resolved["axes"].items():
            axes.setdefault(axis, {}).update(value)
    for axis, value in data.get("axes", {}).items():
        axes.setdefault(axis, {}).update(_absolutise(axis, value, root / name))
    contributors.append(name)
    return {"name": name, "description": data["description"],
            "chain": contributors, "axes": axes}


def _absolutise(axis: str, value: Dict[str, Any], base: Path) -> Dict[str, Any]:
    out = dict(value)
    for key in AXIS_SCHEMA[axis]["file_keys"] & set(value):
        if isinstance(value[key], list):
            out[key] = [str(base / p) for p in value[key]]
        else:
            out[key] = str(base / value[key])
    return out


def read_project_profile(project_root: Path) -> Optional[str]:
    """Read the profile name recorded for a project.

    Args:
        project_root: The project's root directory.

    Returns:
        The recorded name, or None when the file is absent or names none.

    Raises:
        ProfileError: If the file exists but is malformed.
    """
    path = project_root / PROJECT_FILE_RELATIVE_PATH
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: expected a mapping")
    value = data.get("profile")
    if value is not None and not isinstance(value, str):
        raise ProfileError(f"{path}: 'profile' must be a single profile name")
    return value or None


def active(project_root: Optional[Path], session: Optional[str] = None,
           root: Optional[Path] = None) -> Dict[str, Any]:
    """Work out which profile is in force and what each axis resolves to.

    Precedence, lowest to highest: core defaults, the project's
    ``.research/profile.yaml``, a session choice. Axes the profile leaves
    unset keep the core default.

    Args:
        project_root: Project root, or None outside a project.
        session: A profile chosen in conversation with ``/profile use``.
        root: Profiles directory; defaults to :func:`profiles_dir`.

    Returns:
        ``{"status": "active"|"none", "source": "session"|"project"|"none",
        "profile": <name or None>, "chain": [...], "axes": {...}}``.
    """
    name, source = None, "none"
    if project_root is not None:
        name = read_project_profile(project_root)
        source = "project" if name else "none"
    if session:
        name, source = session, "session"

    axes = json.loads(json.dumps(CORE_DEFAULTS))
    if name is None:
        return {"status": "none", "source": "none", "profile": None,
                "chain": [], "axes": axes}
    resolved = resolve(name, root)
    for axis, value in resolved["axes"].items():
        if isinstance(axes.get(axis), dict):
            axes[axis].update(value)
        else:
            axes[axis] = value
    return {"status": "active", "source": source, "profile": name,
            "chain": resolved["chain"], "axes": axes}


def write_project_profile(project_root: Path, name: Optional[str]) -> Path:
    """Record (or clear, with None) the project's profile.

    Args:
        project_root: The project's root directory.
        name: Profile name, or None to clear.

    Returns:
        Path of the file written.
    """
    path = project_root / PROJECT_FILE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"profile": name}, sort_keys=False),
                    encoding="utf-8")
    return path


def _emit(payload: Dict[str, Any], as_json: bool, text: str) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2) if as_json else text)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true")
    group.add_argument("--show", metavar="NAME")
    group.add_argument("--active", action="store_true")
    group.add_argument("--set", metavar="NAME")
    group.add_argument("--clear", action="store_true")
    group.add_argument("--validate", nargs="?", const="", metavar="NAME")
    parser.add_argument("--session", metavar="NAME")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.list:
            rows = []
            for name in available_profiles():
                data = load_manifest(name)
                rows.append({"name": name, "description": data.get("description", ""),
                             "axes": sorted(data.get("axes", {})),
                             "extends": data.get("extends", [])})
            text = "\n".join(f"{r['name']:<32} {', '.join(r['axes']) or '(extends only)'}"
                             f"  {r['description']}" for r in rows) or "No profiles installed."
            _emit({"profiles": rows}, args.json, text)
            return 0

        if args.show:
            resolved = resolve(args.show)
            _emit(resolved, args.json, yaml.safe_dump(resolved, sort_keys=False,
                                                      allow_unicode=True))
            return 0

        if args.validate is not None:
            names = [args.validate] if args.validate else available_profiles()
            problems = []
            for name in names:
                try:
                    problems += validate_manifest(name, load_manifest(name))
                except ProfileError as exc:
                    problems.append(str(exc))
            _emit({"ok": not problems, "problems": problems}, args.json,
                  "\n".join(problems) or f"OK: {len(names)} profile(s) valid.")
            return 1 if problems else 0

        try:
            project_root: Optional[Path] = find_project_root(Path.cwd())
        except ProjectRootNotFoundError:
            project_root = None

        if args.active:
            state = active(project_root, args.session)
            label = (f"{state['profile']} (from {state['source']})"
                     if state["profile"] else "none (core defaults)")
            _emit(state, args.json, f"Active profile: {label}")
            return 0

        if project_root is None:
            raise ProfileError("not inside a git project; nothing to record")
        if args.set:
            resolve(args.set)  # refuse to record a profile that does not resolve
            path = write_project_profile(project_root, args.set)
            _emit({"status": "set", "profile": args.set, "path": str(path)},
                  args.json, f"Project profile set to {args.set} ({path})")
            return 0
        path = write_project_profile(project_root, None)
        _emit({"status": "cleared", "path": str(path)}, args.json,
              f"Project profile cleared ({path})")
        return 0
    except ProfileError as exc:
        _emit({"status": "error", "error": str(exc)}, args.json, f"Error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
