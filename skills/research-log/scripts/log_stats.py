#!/usr/bin/env python3
"""log_stats.py — Estimate research log token volume for milestone-mode gating.

Usage:
    # Human-readable report
    python log_stats.py --dir docs/research_log

    # Machine-readable JSON (used by SKILL.md instructions)
    python log_stats.py --dir docs/research_log --threshold 6000 --json
"""

import argparse
import json
from pathlib import Path

DEFAULT_THRESHOLD = 6000
EXCLUDED_NAMES = frozenset({"INDEX.md", "MILESTONES.md"})
CHARS_PER_TOKEN = 4


def scan_logs(log_dir: Path) -> dict:
    """Scan research log entries and estimate total token volume.

    Returns a dict with `file_count`, `total_chars`, `estimated_tokens`,
    and `milestones_exists` (whether MILESTONES.md is present in log_dir).
    Does not raise if log_dir is missing — returns zeroed stats instead,
    matching research-log's existing "create docs/research_log silently
    if absent" behavior.
    """
    if not log_dir.is_dir():
        return {
            "file_count": 0,
            "total_chars": 0,
            "estimated_tokens": 0,
            "milestones_exists": False,
        }

    total_chars = 0
    file_count = 0
    for path in sorted(log_dir.glob("*.md")):
        if path.name in EXCLUDED_NAMES:
            continue
        total_chars += len(path.read_text(encoding="utf-8"))
        file_count += 1

    return {
        "file_count": file_count,
        "total_chars": total_chars,
        "estimated_tokens": total_chars // CHARS_PER_TOKEN,
        "milestones_exists": (log_dir / "MILESTONES.md").is_file(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Estimate research log token volume for milestone-mode gating"
    )
    ap.add_argument("--dir", default="docs/research_log", metavar="PATH",
                     help="Research log directory (default: docs/research_log)")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, metavar="N",
                     help=f"Token threshold for recommending milestone mode "
                          f"(default: {DEFAULT_THRESHOLD})")
    ap.add_argument("--json", action="store_true",
                     help="Output machine-readable JSON instead of a text report")
    args = ap.parse_args()

    stats = scan_logs(Path(args.dir))
    stats["threshold"] = args.threshold
    stats["recommend_enable"] = (
        not stats["milestones_exists"] and stats["estimated_tokens"] >= args.threshold
    )

    if args.json:
        print(json.dumps(stats))
        return

    plural = "y" if stats["file_count"] == 1 else "ies"
    print(f"Log stats for {args.dir}:")
    print(f"  {stats['file_count']} entr{plural} · {stats['total_chars']} chars"
          f" · ~{stats['estimated_tokens']} tokens (est.)")
    print(f"  Threshold: {args.threshold} tokens")
    if stats["milestones_exists"]:
        print("  Milestone mode: already active (MILESTONES.md present)")
    elif stats["recommend_enable"]:
        print("  Milestone mode: THRESHOLD CROSSED — enable milestone grouping")
    else:
        print("  Milestone mode: below threshold (not yet enabled)")


if __name__ == "__main__":
    main()
