"""Tests for the `python3 -m svg_to_pptx` command line.

Omitting `--mode` printed a menu and called `input()`. In a pipeline, a CI
job, or an agent session there is nobody to answer it: the call blocks on a
pipe that never carries a line, and the export never finishes.
"""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from svg_to_pptx import __main__ as cli


class _Terminal(io.StringIO):
    """A stdin stand-in that claims to be a terminal."""

    def isatty(self) -> bool:
        """Return True, as an interactive terminal does."""
        return True


def _never_prompt() -> str:
    """Fail the test if the CLI reaches for the interactive prompt."""
    raise AssertionError("the CLI prompted for a mode with no terminal attached")


def test_a_non_interactive_run_defaults_to_native(monkeypatch: pytest.MonkeyPatch) -> None:
    """With stdin not a terminal, the documented default is chosen silently."""
    monkeypatch.setattr(cli, "_prompt_mode", _never_prompt)
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    assert cli._resolve_mode(None) == "native"


def test_an_interactive_run_still_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    """At a terminal the menu is still worth showing."""
    monkeypatch.setattr(cli, "_prompt_mode", lambda: "embed")
    monkeypatch.setattr(sys, "stdin", _Terminal())
    assert cli._resolve_mode(None) == "embed"


@pytest.mark.parametrize("mode", ["native", "embed"])
def test_an_explicit_mode_is_never_second_guessed(
        mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--mode` is honoured at a terminal as well as off one."""
    monkeypatch.setattr(cli, "_prompt_mode", _never_prompt)
    monkeypatch.setattr(sys, "stdin", _Terminal())
    assert cli._resolve_mode(mode) == mode


def test_a_detached_stdin_defaults_to_native(monkeypatch: pytest.MonkeyPatch) -> None:
    """A closed stdin resolves too, rather than raising on `isatty`.

    A daemonised runner can leave `sys.stdin` as None.
    """
    monkeypatch.setattr(cli, "_prompt_mode", _never_prompt)
    monkeypatch.setattr(sys, "stdin", None)
    assert cli._resolve_mode(None) == "native"
