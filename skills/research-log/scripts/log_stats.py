#!/usr/bin/env python3
"""log_stats.py — Estimate research log token volume for milestone-mode gating.

Usage:
    # Human-readable report
    python log_stats.py --dir docs/research_log

    # Machine-readable JSON (used by SKILL.md instructions)
    python log_stats.py --dir docs/research_log --threshold 6000 --json
"""

from collections import Counter
import argparse
import json
from pathlib import Path

from journal_common import entry_paths, parse_frontmatter, scalar
from journal_milestones import read_milestones

DEFAULT_THRESHOLD = 6000
CHARS_PER_TOKEN = 4


def scan_logs(
    log_dir: Path, milestone_max_entries: int = 30
) -> dict[str, object]:
    """Scan research log entries and estimate total token volume.

    Args:
        log_dir: Directory containing top-level journal entries.
        milestone_max_entries: Size at which the newest ongoing group needs review.

    Returns:
        Volume statistics and, for existing directories, milestone counts and
        a size recommendation. Missing directories retain the legacy zeroed
        response shape.

    Raises:
        OSError: A source file cannot be read.
        ValueError: Source metadata or milestone definitions are malformed.
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
    milestone_counts: Counter[str] = Counter()
    for path in entry_paths(log_dir):
        text = path.read_text(encoding="utf-8")
        total_chars += len(text)
        file_count += 1
        metadata, _ = parse_frontmatter(text)
        milestone_counts[scalar(metadata, "milestone")] += 1

    milestones = []
    if (log_dir / "MILESTONES.md").is_file():
        document = read_milestones(log_dir / "MILESTONES.md")
        milestones = [
            {
                "id": milestone.identifier,
                "status": milestone.status,
                "entries": milestone_counts[milestone.identifier],
            }
            for milestone in document.milestones
        ]
    ongoing = [
        milestone
        for milestone in milestones
        if milestone["status"] == "ongoing"
    ]
    newest = max(
        ongoing, key=lambda milestone: int(milestone["id"][1:]), default=None
    )
    return {
        "file_count": file_count,
        "total_chars": total_chars,
        "estimated_tokens": total_chars // CHARS_PER_TOKEN,
        "milestones_exists": (log_dir / "MILESTONES.md").is_file(),
        "milestones": milestones,
        "recommend_new_milestone": newest is not None
        and newest["entries"] >= milestone_max_entries,
    }


def main() -> None:
    """Print journal volume and milestone recommendations for the CLI."""
    ap = argparse.ArgumentParser(
        description="Estimate research log token volume for milestone-mode gating"
    )
    ap.add_argument(
        "--dir",
        default="docs/research_log",
        metavar="PATH",
        help="Research log directory (default: docs/research_log)",
    )
    ap.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        metavar="N",
        help=f"Token threshold for recommending milestone mode "
        f"(default: {DEFAULT_THRESHOLD})",
    )
    ap.add_argument(
        "--milestone-max-entries",
        type=int,
        default=30,
        metavar="N",
        help="Recommend a new milestone at this ongoing entry count (default 30)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of a text report",
    )
    args = ap.parse_args()

    if args.milestone_max_entries < 1:
        ap.error("--milestone-max-entries must be positive")
    stats = scan_logs(Path(args.dir), args.milestone_max_entries)
    stats["threshold"] = args.threshold
    stats["recommend_enable"] = (
        not stats["milestones_exists"]
        and stats["estimated_tokens"] >= args.threshold
    )

    if args.json:
        print(json.dumps(stats))
        return

    plural = "y" if stats["file_count"] == 1 else "ies"
    print(f"Log stats for {args.dir}:")
    print(
        f"  {stats['file_count']} entr{plural} · {stats['total_chars']} chars"
        f" · ~{stats['estimated_tokens']} tokens (est.)"
    )
    print(f"  Threshold: {args.threshold} tokens")
    if stats["milestones_exists"]:
        print("  Milestone mode: already active (MILESTONES.md present)")
        ongoing = [
            milestone
            for milestone in stats["milestones"]
            if milestone["status"] == "ongoing"
        ]
        newest = max(
            ongoing,
            key=lambda milestone: int(milestone["id"][1:]),
            default=None,
        )
        identifier = newest["id"] if newest is not None else "none"
        entries = newest["entries"] if newest is not None else 0
        recommendation = "yes" if stats["recommend_new_milestone"] else "no"
        print(
            f"  Newest ongoing milestone: {identifier} · {entries} entries"
            f" · threshold: {args.milestone_max_entries} entries"
            f" · recommend new milestone: {recommendation}"
        )
    elif stats["recommend_enable"]:
        print("  Milestone mode: THRESHOLD CROSSED — enable milestone grouping")
    else:
        print("  Milestone mode: below threshold (not yet enabled)")


if __name__ == "__main__":
    main()
