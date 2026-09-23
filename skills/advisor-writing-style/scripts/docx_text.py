#!/usr/bin/env python3
"""Extract a .docx document's text without pandoc.

A supervisor returns the built manuscript as Word, and the edits have to be
read before they can be carried back. Pandoc is often unavailable on a lab
machine, and converting through it renumbers lists and rewrites tables
anyway. This reads the document part directly and prints one line per
paragraph and one line per table row, which is the shape the sentence
differ expects.

Inline and display mathematics carry no ``w:t`` runs, so they come out empty.
That is deliberate: mathematics is compared from the Markdown sources, never
from Word.

Typical use::

    python3 docx_text.py CM-SAC_manuscript_en_v3.docx > v3.txt
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from typing import Iterator, List, Optional, Sequence
from xml.etree import ElementTree

WORD_NAMESPACE: str = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
)
"""WordprocessingML namespace every element of the document part carries."""

NAMESPACES: dict = {"w": WORD_NAMESPACE}
"""Namespace map for ElementTree lookups."""


def element_text(node: ElementTree.Element) -> str:
    """Join every text run beneath one element.

    Args:
        node: Element to read, typically a paragraph or a table cell.

    Returns:
        The concatenated run text, with no separator between runs.
    """
    return "".join(run.text or "" for run in node.iter(f"{{{WORD_NAMESPACE}}}t"))


def document_lines(path: Path) -> Iterator[str]:
    """Yield the document's paragraphs and table rows in reading order.

    Args:
        path: The .docx file to read.

    Yields:
        One non-empty line per paragraph, and one pipe-delimited line per
        table row.

    Raises:
        ValueError: If the archive holds no document part or no body.
    """
    with zipfile.ZipFile(path) as archive:
        if "word/document.xml" not in archive.namelist():
            raise ValueError(f"{path} holds no word/document.xml part")
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    body = root.find("w:body", NAMESPACES)
    if body is None:
        raise ValueError(f"{path}'s document part holds no body")
    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            line = element_text(child).strip()
            if line:
                yield line
        elif tag == "tbl":
            for row in child.findall("w:tr", NAMESPACES):
                cells: List[str] = [
                    element_text(cell).strip()
                    for cell in row.findall("w:tc", NAMESPACES)
                ]
                yield "| " + " | ".join(cells) + " |"


def build_parser() -> argparse.ArgumentParser:
    """Construct the command line parser.

    Returns:
        The parser for this entry point.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("document", type=Path, help="The .docx file to read")
    parser.add_argument(
        "--output",
        type=Path,
        help="File to write to; defaults to standard output.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Print or write the document's text.

    Args:
        argv: Command line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit status.
    """
    arguments = build_parser().parse_args(argv)
    lines = list(document_lines(arguments.document))
    text = "\n".join(lines) + "\n"
    if arguments.output is None:
        print(text, end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(text, encoding="utf-8")
        print(f"wrote {arguments.output} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
