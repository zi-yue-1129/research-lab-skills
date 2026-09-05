#!/usr/bin/env python3
"""Validate all compliance_report YAML fixtures against Schema 12.

Loads each examples/compliance/fixture_*.yaml in-process and runs it
through scripts.checks.check_compliance_report.validate(). Exits 0 if every
fixture validates; exits 1 on first failure or if no fixtures are found.

Usage:
  python scripts/tooling/validate_compliance_fixtures.py [fixture_dir]

Default fixture_dir: examples/compliance (relative to repo root).
"""
from __future__ import annotations


import sys
from pathlib import Path
# The `scripts.<group>.<module>` imports below resolve against the repo root,
# which is not on sys.path when this file is run directly as
# `python3 scripts/<group>/<name>.py` — only when run as `python3 -m`. Both
# invocation styles are in use (workflows, agent instructions, tests), so the
# root goes on the path explicitly. parents[2] is the repo root from
# scripts/<group>/<name>.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import sys
from pathlib import Path

import yaml

from scripts.checks.check_compliance_report import validate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "examples" / "compliance"


def validate_fixture(yaml_path: Path) -> list[str]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return validate(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture_dir", type=Path, nargs="?", default=DEFAULT_DIR)
    args = parser.parse_args()

    fixtures = sorted(args.fixture_dir.glob("fixture_*.yaml"))
    if not fixtures:
        print(f"ERROR: no fixture_*.yaml files in {args.fixture_dir}", file=sys.stderr)
        return 1

    failed = 0
    for fx in fixtures:
        errors = validate_fixture(fx)
        if errors:
            print(f"[FAIL] {fx.name}:")
            for e in errors:
                print(f"  {e}")
            failed += 1
        else:
            print(f"[OK] {fx.name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
