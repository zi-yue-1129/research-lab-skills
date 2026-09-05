#!/usr/bin/env python3
"""Lint: every top-level SKILL.md must declare metadata.data_access_level.

Legal values: raw | redacted | verified_only.
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

import sys

from scripts.tooling._skill_lint import run_lint

LEGAL_VALUES = frozenset({"raw", "redacted", "verified_only"})


if __name__ == "__main__":
    sys.exit(
        run_lint(
            field="data_access_level",
            legal_values=LEGAL_VALUES,
            ok_message="OK: all SKILL.md files declare a valid data_access_level.",
        )
    )
