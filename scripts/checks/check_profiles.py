#!/usr/bin/env python3
"""Lint: every bundled profile is valid, registered, and non-identifying.

Profiles live in ``skills/research-profile/profiles/<name>/`` and are listed in
``PROFILE_REGISTRY.md`` at the repository root. This lint checks that:

* every profile passes ``profile.py``'s schema validation and resolves
  (its ``extends`` chain exists and has no cycle);
* the registry table names exactly the profiles on disk;
* no profile's name, description or files contain an identifying term
  (``check_core_neutrality.IDENTIFYING_TERMS``): profiles are named and
  written for what they do, never for who they belong to.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_core_neutrality import IDENTIFYING_TERMS, TEXT_SUFFIXES  # noqa: E402

PROFILE_SCRIPT = Path("skills/research-profile/scripts/profile.py")
PROFILES_DIR = Path("skills/research-profile/profiles")
REGISTRY = Path("PROFILE_REGISTRY.md")
REGISTRY_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.MULTILINE)
IDENTIFYING = re.compile("|".join(IDENTIFYING_TERMS), re.IGNORECASE)


def load_profile_module(root: Path):
    """Import ``profile.py`` from the repository.

    Args:
        root: Repository root.

    Returns:
        The loaded module.
    """
    spec = importlib.util.spec_from_file_location("research_profile", root / PROFILE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registered_names(root: Path) -> set[str]:
    """Read profile names from the registry's table rows.

    Args:
        root: Repository root.

    Returns:
        Names in the first column of rows whose first cell is backticked.
    """
    return set(REGISTRY_ROW.findall((root / REGISTRY).read_text(encoding="utf-8")))


def check(root: Path) -> list[str]:
    """Run every profile check.

    Args:
        root: Repository root.

    Returns:
        Problems; empty when all profiles pass.
    """
    module = load_profile_module(root)
    profiles_root = root / PROFILES_DIR
    on_disk = set(module.available_profiles(profiles_root))
    problems: list[str] = []

    for name in sorted(on_disk):
        try:
            manifest = module.load_manifest(name, profiles_root)
            problems += module.validate_manifest(name, manifest, profiles_root)
            module.resolve(name, profiles_root)
        except module.ProfileError as exc:
            problems.append(str(exc))
        for path in sorted((profiles_root / name).rglob("*")):
            if path.is_file() and path.suffix in TEXT_SUFFIXES:
                text = path.read_text(encoding="utf-8", errors="replace")
                for match in sorted(set(IDENTIFYING.findall(text))):
                    problems.append(f"{path.relative_to(root)}: identifying term "
                                    f"'{match}'; profiles must be de-identified")
        if IDENTIFYING.search(name):
            problems.append(f"{name}: profile name identifies a person, school, "
                            f"lab, course or paper")

    registered = registered_names(root)
    for name in sorted(on_disk - registered):
        problems.append(f"{REGISTRY}: missing a row for profile '{name}'")
    for name in sorted(registered - on_disk):
        problems.append(f"{REGISTRY}: lists '{name}', which has no "
                        f"{PROFILES_DIR}/{name}/profile.yaml")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    problems = check(args.root)
    if problems:
        print("\n".join(problems))
        return 1
    print(f"OK: {len(registered_names(args.root))} profile(s) valid, registered "
          f"and non-identifying.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
