"""Tests for the design-token validator CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parents[2]
_SCRIPT = _SKILL_DIR / "scripts" / "validate_design_tokens.py"
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"


def test_cli_accepts_default_tokens() -> None:
    """The shipped default token file validates and exits zero."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--tokens", str(_DEFAULT_TOKENS), "--json"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"] is True


def test_cli_rejects_invalid_tokens(tmp_path: Path) -> None:
    """A token file below the typography floor exits non-zero with an error."""
    bad = tmp_path / "bad.tokens.yaml"
    bad.write_text(
        _DEFAULT_TOKENS.read_text(encoding="utf-8").replace("size: 21", "size: 9"),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--tokens", str(bad), "--json"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert payload["errors"]


def test_validate_token_file_returns_errors(tmp_path: Path) -> None:
    """The importable helper returns errors rather than raising."""
    from validate_design_tokens import validate_token_file

    assert validate_token_file(_DEFAULT_TOKENS) == []
    missing = tmp_path / "nope.yaml"
    errors = validate_token_file(missing)
    assert len(errors) == 1
    assert "nope.yaml" in errors[0]
