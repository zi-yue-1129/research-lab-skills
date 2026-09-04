#!/usr/bin/env python3
"""Validate a report-slides design-token file against the token schema."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from design_tokens import DesignTokens, TokenError


def validate_token_file(path: Path) -> list[str]:
    """Validate one token file.

    Args:
        path: Path to a `.tokens.yaml` file.

    Returns:
        A list of human-readable errors; empty when the file is valid.
    """
    try:
        DesignTokens.load(path)
    except TokenError as exc:
        return [str(exc)]
    return []


def main() -> None:
    """Run token validation and exit non-zero on any error."""
    parser = argparse.ArgumentParser(
        description="Validate a report-slides design-token file."
    )
    parser.add_argument("--tokens", metavar="PATH", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    errors = validate_token_file(args.tokens)
    result = {"valid": not errors, "errors": errors}
    # `sys.stdout.write` rather than `print`: the repository's lint forbids
    # `print` in new code, and the payload shape is what callers parse.
    payload = json.dumps(result) if args.json else json.dumps(result, indent=2)
    sys.stdout.write(payload + "\n")
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
