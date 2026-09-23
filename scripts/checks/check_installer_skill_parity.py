#!/usr/bin/env python3
"""Lint: every installer offers every skill marketplace.json ships.

``.claude-plugin/marketplace.json`` is the canonical list of skills this
repository ships, split across plugins. ``install.sh``, ``install.ps1`` and
``bin/crs.js`` each carry their own hardcoded copy of that list, split across
``RESOLVER_SKILLS`` / ``LAB_SKILLS`` / ``ARS_SKILLS`` arrays, rather than
reading the manifest. A skill added to the manifest and to none of an
installer's arrays is installed by the plugin path and silently missing from
that installer. This is exactly how ``advisor-writing-style`` shipped in the
plugin manifest while `curl | bash`, PowerShell and npm installs all left it
out: it was never added to any of the three ``ARS_SKILLS`` arrays.

The two sides are not expected to partition identically -- ``resource-resolver``
and ``agent-state`` sit in their own array in every installer (a shared
foundation installed unconditionally) but appear inside more than one
plugin's ``skills`` list in the manifest. What must hold is the *union*: every
skill named by any plugin must be installed by some array in every installer,
and every skill an installer can install must be named by some plugin.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: (installer path, [array names]) checked against the manifest's union.
INSTALLERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("install.sh", ("RESOLVER_SKILLS", "LAB_SKILLS", "ARS_SKILLS")),
    ("install.ps1", ("$ResolverSkills", "$LabSkills", "$ArsSkills")),
    ("bin/crs.js", ("RESOLVER_SKILLS", "LAB_SKILLS", "ARS_SKILLS")),
)


def canonical_skills(root: Path) -> set[str]:
    """Read the full skill set marketplace.json ships, across every plugin.

    Args:
        root: Repository root.

    Returns:
        Skill directory names (without the ``./skills/`` prefix) named by
        any plugin's ``skills`` list.

    Raises:
        ValueError: If the manifest declares no plugins at all.
    """
    manifest_path = root / ".claude-plugin" / "marketplace.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugins = manifest.get("plugins", [])
    if not plugins:
        raise ValueError(f"{manifest_path}: no plugins declared")
    skills: set[str] = set()
    for plugin in plugins:
        skills |= {
            path.rsplit("/", 1)[-1] for path in plugin.get("skills", [])
        }
    return skills


def installer_array(text: str, array_name: str) -> set[str]:
    """Extract one quoted skill-name array from an installer's source text.

    Works across bash (``NAME=(...)``), PowerShell (``$Name = @(...)``) and
    JavaScript (``const NAME = [...]``) declarations, since all three are a
    single-quoted-or-double-quoted string list on one logical assignment.

    Args:
        text: The installer script's full source.
        array_name: The declared array's name, exactly as it appears
            (``ARS_SKILLS``, ``$ArsSkills``, ...).

    Returns:
        The quoted string literals found in that assignment.

    Raises:
        ValueError: If no assignment to ``array_name`` is found.
    """
    escaped = re.escape(array_name)
    match = re.search(rf"{escaped}\s*=\s*[\[(@(]*\(?(.*?)[\])]", text)
    if match is None:
        raise ValueError(f"no assignment to {array_name!r} found")
    return set(re.findall(r"""['"]([^'"]+)['"]""", match.group(1)))


def installer_skills(path: Path, array_names: tuple[str, ...]) -> set[str]:
    """Union every named skill array an installer declares.

    Args:
        path: Installer script to read.
        array_names: Every array this installer partitions its skills into.

    Returns:
        The union of every array's skill names.

    Raises:
        ValueError: If any named array is missing from the script.
    """
    text = path.read_text(encoding="utf-8")
    skills: set[str] = set()
    for array_name in array_names:
        try:
            skills |= installer_array(text, array_name)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    return skills


def check_parity(root: Path) -> list[str]:
    """Compare every installer's total skill set against the manifest.

    Args:
        root: Repository root.

    Returns:
        Human-readable violation messages, empty if every installer's union
        matches the manifest's union exactly.
    """
    violations: list[str] = []
    try:
        canonical = canonical_skills(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]

    for relative_path, array_names in INSTALLERS:
        installer_path = root / relative_path
        try:
            found = installer_skills(installer_path, array_names)
        except (OSError, ValueError) as exc:
            violations.append(str(exc))
            continue
        missing = canonical - found
        extra = found - canonical
        if missing:
            violations.append(
                f"{installer_path}: marketplace.json ships {sorted(missing)}"
                " but no installer array names them"
            )
        if extra:
            violations.append(
                f"{installer_path}: names {sorted(extra)}, absent from "
                "every plugin's skills list in marketplace.json"
            )
    return violations


def build_parser() -> argparse.ArgumentParser:
    """Construct the command line parser.

    Returns:
        The parser for this entry point.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root to check.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the parity check and print its result.

    Args:
        argv: Command line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        0 if every installer matches the manifest, 1 otherwise.
    """
    arguments = build_parser().parse_args(argv)
    violations = check_parity(arguments.path)
    if violations:
        for violation in violations:
            sys.stdout.write(f"ERROR: {violation}\n")
        sys.stderr.write(f"\n{len(violations)} violation(s) found.\n")
        return 1
    sys.stdout.write(
        "OK: every installer offers every skill marketplace.json ships.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
