#!/usr/bin/env python3
"""Align a supervisor's Word rewrite against the Markdown it came from.

Paragraph-level diffing fails on a built manuscript. Word puts long inline
mathematics on its own display line, which splits one Markdown paragraph into
several Word paragraphs and makes untouched prose look rewritten. Aligning
sentences instead is immune to that, because a split moves sentences between
paragraphs without changing the sentences themselves.

Mathematics is stripped from both sides before comparison. Word carries none
of it, so leaving it in would report every formula as deleted. Mathematics is
therefore restored from the Markdown sources when the edits are applied, never
read out of the .docx.

``--facts`` prints the numbers, bracketed citations and cross-references each
source holds, which is the inventory to snapshot before editing and compare
against afterwards.

Typical use::

    python3 sentence_diff.py --docx v3.txt --sources docs/paper/en/*.md
    python3 sentence_diff.py --facts --sources docs/paper/en/*.md > before.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

SENTENCE_BOUNDARY: re.Pattern = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
"""Split points between sentences, requiring a capital or opening bracket."""

MINIMUM_SENTENCE_LENGTH: int = 25
"""Shorter fragments are headings or table cells, and only add noise."""

SMART_CHARACTERS: Dict[str, str] = {
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
}
"""Word's curly punctuation, mapped back to the ASCII the sources use."""

NUMBER_PATTERN: re.Pattern = re.compile(r"-?\d+(?:\.\d+)?")
"""Any numeric literal, which a rewrite must not silently change."""

CITATION_PATTERN: re.Pattern = re.compile(r"\[\d+(?:\]\s*,\s*\[\d+)*\]")
"""Bracketed reference markers."""

REFERENCE_PATTERN: re.Pattern = re.compile(
    r"(?:Section|Fig\.|Figure|Table|Equation|Supplementary Material|"
    r"Proposition)\s+[A-Za-z0-9.\-()]+"
)
"""Cross-references a rewrite must keep pointing at the same object."""


def normalise(text: str) -> str:
    """Reduce one line to the form both sides can be compared in.

    Args:
        text: A Markdown line or an extracted Word paragraph.

    Returns:
        The line with smart punctuation, mathematics and emphasis removed and
        whitespace collapsed.
    """
    for source, target in SMART_CHARACTERS.items():
        text = text.replace(source, target)
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.DOTALL)
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"[`*_]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def sentences(text: str) -> List[str]:
    """Split one normalised line into comparable sentences.

    Args:
        text: A line to split.

    Returns:
        Sentences long enough to be worth aligning.
    """
    return [
        part.strip()
        for part in SENTENCE_BOUNDARY.split(normalise(text))
        if len(part.strip()) > MINIMUM_SENTENCE_LENGTH
    ]


def source_sentences(paths: Sequence[Path]) -> List[str]:
    """Collect every prose sentence of the Markdown sources, in order.

    Args:
        paths: Markdown sections, in the order the manuscript assembles them.

    Returns:
        One entry per sentence, with headings, tables, images and display
        mathematics skipped.
    """
    collected: List[str] = []
    for path in paths:
        for raw in path.read_text(encoding="utf-8").split("\n"):
            line = raw.strip()
            if not line or line.startswith(("#", "|", "![", "$$")):
                continue
            collected += sentences(line)
    return collected


def document_sentences(path: Path) -> List[str]:
    """Collect every sentence of the extracted Word text.

    Args:
        path: Output of ``docx_text.py``.

    Returns:
        One entry per sentence, with table rows skipped.
    """
    collected: List[str] = []
    for raw in path.read_text(encoding="utf-8").split("\n"):
        line = raw.strip()
        if not line or line.startswith("|"):
            continue
        collected += sentences(line)
    return collected


def fact_inventory(paths: Sequence[Path]) -> Dict[str, Dict[str, List[str]]]:
    """List the facts a rewrite must not move.

    Args:
        paths: Markdown sections to inventory.

    Returns:
        Per file, the sorted numbers, citations and cross-references it holds.
    """
    inventory: Dict[str, Dict[str, List[str]]] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        inventory[str(path)] = {
            "numbers": sorted(NUMBER_PATTERN.findall(text)),
            "citations": sorted(CITATION_PATTERN.findall(text)),
            "references": sorted(REFERENCE_PATTERN.findall(text)),
        }
    return inventory


def report_differences(repo: Sequence[str], docx: Sequence[str]) -> int:
    """Print every sentence the rewrite added, dropped or replaced.

    Args:
        repo: Sentences of the Markdown sources.
        docx: Sentences of the supervisor's document.

    Returns:
        The number of differing hunks printed.
    """
    matcher = difflib.SequenceMatcher(None, repo, docx, autojunk=False)
    hunks = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks += 1
        print(f"===== {tag} =====")
        for line in repo[i1:i2]:
            print(f"  SOURCE- {line}")
        for line in docx[j1:j2]:
            print(f"  REWRITE+ {line}")
        print()
    return hunks


def build_parser() -> argparse.ArgumentParser:
    """Construct the command line parser.

    Returns:
        The parser for this entry point.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sources",
        type=Path,
        nargs="+",
        required=True,
        help="Markdown sections, in assembly order.",
    )
    parser.add_argument(
        "--docx",
        type=Path,
        help="Text extracted by docx_text.py; omit with --facts.",
    )
    parser.add_argument(
        "--facts",
        action="store_true",
        help="Print the fact inventory as JSON instead of a diff.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the requested comparison.

    Args:
        argv: Command line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit status.

    Raises:
        SystemExit: If neither ``--facts`` nor ``--docx`` was given.
    """
    arguments = build_parser().parse_args(argv)
    if arguments.facts:
        print(json.dumps(fact_inventory(arguments.sources), indent=2))
        return 0
    if arguments.docx is None:
        raise SystemExit("Pass --docx to diff, or --facts to inventory.")
    repo = source_sentences(arguments.sources)
    docx = document_sentences(arguments.docx)
    hunks = report_differences(repo, docx)
    print(f"{hunks} differing hunk(s) over {len(repo)} source sentences.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
