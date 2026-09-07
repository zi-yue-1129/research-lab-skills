"""A research log's line endings must not change what a query reports.

Logs are read as raw bytes so the scan digest covers exact content, and the
decoded text was previously used for parsing unchanged. A log written by any
Windows editor carries CRLF, so every carriage return was counted as a body
character, rode along inside `preview`, and skewed the fetch-budget decision
computed from those counts -- a wrong answer for a real user, not a test
artifact.

Fixtures are written as bytes rather than through `Path.write_text`, because
that helper translates newlines to the host's convention and would make the
fixture depend on the platform running the suite -- the very coupling under
test.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "section_query.py"

_BODY = "First body line.\nSecond body line.\n"
_LOG = "---\ndate: 2026-08-02\nexperiment: run\n---\n## Results\n" + _BODY


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run section_query.py with the supplied CLI arguments."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def _write(log_dir: Path, text: str, ending: str) -> None:
    """Write a log with exact line endings, bypassing text-mode translation."""
    path = log_dir / "2026-08-02_run.md"
    path.write_bytes(text.replace("\n", ending).encode("utf-8"))


def _first_match(log_dir: Path) -> dict:
    """Search the log directory and return the single expected match."""
    result = _run("search", "--dir", str(log_dir), "--sections", "Results")
    assert result.returncode == 0, result.stderr
    matches = json.loads(result.stdout)["matches"]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_body_chars_ignores_line_ending_style(tmp_path: Path, ending: str) -> None:
    """The count that drives the fetch budget must not depend on the editor."""
    _write(tmp_path, _LOG, ending)
    assert _first_match(tmp_path)["body_chars"] == len(_BODY)


@pytest.mark.parametrize("ending", ["\r\n", "\r"])
def test_preview_carries_no_carriage_return(tmp_path: Path, ending: str) -> None:
    """A stray `\r` in the preview is visible to whoever reads the output."""
    _write(tmp_path, _LOG, ending)
    assert "\r" not in _first_match(tmp_path)["preview"]


def test_mixed_endings_in_one_file_still_normalize(tmp_path: Path) -> None:
    """A file touched by two editors must not report a third result."""
    (tmp_path / "2026-08-02_run.md").write_bytes(
        b"---\r\ndate: 2026-08-02\r\nexperiment: run\r\n---\n"
        b"## Results\r\nFirst body line.\nSecond body line.\r\n"
    )
    assert _first_match(tmp_path)["body_chars"] == len(_BODY)


def test_the_fingerprint_still_distinguishes_differing_bytes(tmp_path: Path) -> None:
    """Normalization is for parsing only; content identity stays byte-exact.

    The fingerprint is a content digest used for cache validity, so two files
    that differ on disk must fingerprint differently even when they parse the
    same. Folding line endings into it would silently conflate them.
    """
    def fingerprint(ending: str) -> str:
        _write(tmp_path, _LOG, ending)
        result = _run("types", "--dir", str(tmp_path))
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)["journal_fingerprint"]

    assert fingerprint("\n") != fingerprint("\r\n")
