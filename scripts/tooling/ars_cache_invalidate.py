#!/usr/bin/env python3
"""/ars-cache-invalidate CLI — drop cached verification entries for a citation.

Backs the `/ars-cache-invalidate <citation_key>` slash command (Delta 2,
deliverable 6). Removes every cached resolver entry (all resolvers, all query
forms) for the named citation_key so the next pipeline run re-verifies it live.
Idempotent: invalidating a citation with no cached rows succeeds as a no-op.

Spec: docs/design/2026-05-21-v3.10-182-promote-citation-gate-spec.md §2 Delta 2.
"""
from __future__ import annotations

from pathlib import Path

import sys
# The `scripts.<group>.<module>` imports below resolve against the repo root,
# which is not on sys.path when this file is run directly as
# `python3 scripts/<group>/<name>.py` — only when run as `python3 -m`. Both
# invocation styles are in use (workflows, agent instructions, tests), so the
# root goes on the path explicitly. parents[2] is the repo root from
# scripts/<group>/<name>.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import sys

try:
    from scripts.audit.verification_cache import VerificationCache
except ImportError:
    from scripts.audit.verification_cache import VerificationCache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ars-cache-invalidate",
        description="Drop cached verification entries for a citation_key.",
    )
    parser.add_argument(
        "citation_key",
        help="The citation_key whose cached resolver entries to invalidate.",
    )
    args = parser.parse_args(argv)

    cache = VerificationCache()
    cache.invalidate(args.citation_key)
    print(f"[ars-cache-invalidate] cleared cache for '{args.citation_key}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
