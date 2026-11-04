#!/usr/bin/env python3
"""Lint: keep profile-specific content out of skill cores.

Anything true for one person, course, lab, field, venue or language belongs in
a named profile under ``skills/research-profile/profiles/``, not in a skill's
core (see ``skills/research-profile/SKILL.md``). This lint scans the cores for
two kinds of term:

* ``IDENTIFYING_TERMS`` name a specific person, school, lab, course or paper.
  They are banned in profiles too (``check_profiles.py`` enforces that side):
  a profile is named and written for what it does, never for who it is for.
* ``CONTEXT_TERMS`` name one national or institutional context. A profile may
  carry them; a core should not assume them.

The repository inherited many such terms, so this is a ratchet rather than a
ban: ``core_neutrality_baseline.json`` records the hit count per file, and the
lint fails when a file gains hits, when a new file has any, or when a file's
count drops below its baseline without the baseline being lowered (rerun with
``--update-baseline`` after moving content into a profile).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

IDENTIFYING_TERMS: tuple[str, ...] = (
    r"CM-SAC",
    r"s2v-dagger",
    r"Cognitive Memory",
    r"Tamkang",
    r"淡江",
    r"\bTKU\b",
    r"tku-lecture",
)

CONTEXT_TERMS: tuple[str, ...] = (
    r"Taiwan",
    r"台灣",
    r"臺灣",
    r"\bTSSCI\b",
    r"HEEACT",
    r"tw-hei",
    r"教育部",
    r"\bMOE\b",
)

#: Paths (relative to the repo root) whose files count as skill cores.
SCAN_ROOTS: tuple[str, ...] = ("skills", "commands", "shared", ".claude/CLAUDE.md")
#: Path fragments excluded from the scan: profiles may hold context terms, and
#: tests and fixtures legitimately spell out the terms they check for.
EXCLUDED_PARTS: tuple[str, ...] = ("research-profile/profiles/", "/tests/", "/fixtures/")
TEXT_SUFFIXES = frozenset({".md", ".py", ".yaml", ".yml", ".json", ".txt", ".tex", ".js", ".sh"})
BASELINE_PATH = Path("scripts/checks/core_neutrality_baseline.json")

PATTERN = re.compile("|".join(IDENTIFYING_TERMS + CONTEXT_TERMS), re.IGNORECASE)


def iter_core_files(root: Path):
    """Yield every text file in the scanned core paths.

    Args:
        root: Repository root.

    Yields:
        Paths relative to ``root``, in sorted order.
    """
    for entry in SCAN_ROOTS:
        base = root / entry
        candidates = [base] if base.is_file() else sorted(base.rglob("*"))
        for path in candidates:
            rel = path.relative_to(root).as_posix()
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            if any(part in f"/{rel}" for part in EXCLUDED_PARTS):
                continue
            yield Path(rel)


def count_hits(root: Path) -> dict[str, int]:
    """Count term hits per core file.

    Args:
        root: Repository root.

    Returns:
        ``{relative path: hits}`` for files with at least one hit.
    """
    counts: dict[str, int] = {}
    for rel in iter_core_files(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        hits = len(PATTERN.findall(text))
        if hits:
            counts[rel.as_posix()] = hits
    return counts


def compare(current: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """Compare current hit counts with the baseline.

    Args:
        current: Counts from :func:`count_hits`.
        baseline: Recorded counts.

    Returns:
        Problems; empty when the two agree exactly.
    """
    problems = []
    for path in sorted(set(current) | set(baseline)):
        now, was = current.get(path, 0), baseline.get(path, 0)
        if now > was:
            problems.append(
                f"{path}: {now} profile-specific term(s), baseline {was}. Move the "
                f"content into a profile (skills/research-profile/profiles/) instead.")
        elif now < was:
            problems.append(
                f"{path}: {now} term(s), baseline {was}. Good -- lower the baseline "
                f"with --update-baseline so the gain is locked in.")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)

    current = count_hits(args.root)
    baseline_file = args.root / BASELINE_PATH
    if args.update_baseline:
        baseline_file.write_text(json.dumps(current, indent=2, sort_keys=True,
                                            ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Baseline written: {len(current)} file(s), {sum(current.values())} hit(s).")
        return 0

    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    problems = compare(current, baseline)
    if problems:
        print("\n".join(problems))
        return 1
    print(f"OK: core neutrality matches baseline ({len(current)} file(s), "
          f"{sum(current.values())} legacy hit(s) still to move into profiles).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
