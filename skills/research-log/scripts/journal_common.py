"""Share top-level entry discovery and the journal's frontmatter subset.

Supported metadata uses scalars, quoted scalars, indented multiline scalars,
block scalars, and string lists. This is deliberately not a general YAML parser.
"""

from __future__ import annotations

from pathlib import Path
import re

Metadata = dict[str, str | list[str]]
_META_STEM = re.compile(r"^[A-Z][A-Z0-9_]*$")
_FIELD = re.compile(r"^([a-z_]+):[ \t]*(.*)$")
_LIST_FIELDS = frozenset({"tags", "slide_decks"})
_SCALAR_FIELDS = frozenset(
    {
        "date",
        "experiment",
        "summary",
        "milestone",
        "follows",
        "git_head",
        "mode",
    }
)


def entry_paths(directory: Path) -> list[Path]:
    """Return sorted top-level Markdown entries, excluding reserved meta stems.

    Args:
        directory: Journal directory; missing directories yield no entries.

    Returns:
        Regular entry paths in filename order, without scanning subdirectories.
    """
    return sorted(
        path
        for path in directory.glob("*.md")
        if path.is_file() and not _META_STEM.fullmatch(path.stem)
    )


def unquote_scalar(value: str) -> str:
    """Decode a single plain or quoted frontmatter scalar.

    Args:
        value: Scalar text without surrounding whitespace.

    Returns:
        Text with one matching quote pair removed and YAML quotes unescaped.

    Raises:
        ValueError: A quoted scalar has no closing quote.
    """
    if value[:1] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            raise ValueError("Unterminated quoted frontmatter scalar")
        if value[0] == "'":
            return value[1:-1].replace("''", "'")
        return (
            value[1:-1]
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\\\", "\\")
        )
    return value


def parse_frontmatter(text: str) -> tuple[Metadata, int]:
    """Read supported journal fields and return the first body offset.

    Args:
        text: Markdown source with normalized newlines.

    Returns:
        Recognized fields and offset immediately after the closing delimiter.
        Missing frontmatter returns an empty mapping and offset zero.

    Raises:
        ValueError: Frontmatter is unclosed or a recognized value is malformed.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, 0
    closing = next(
        (
            index
            for index in range(1, len(lines))
            if lines[index].strip() == "---"
        ),
        None,
    )
    if closing is None:
        raise ValueError("Unclosed frontmatter")
    fields: Metadata = {}
    index = 1
    while index < closing:
        match = _FIELD.match(lines[index].rstrip("\n"))
        index += 1
        if match is None:
            continue
        key, raw = match.groups()
        raw = raw.rstrip()
        continuation: list[str] = []
        while index < closing and (
            lines[index][:1].isspace()
            or not lines[index].strip()
            or (key in _LIST_FIELDS and lines[index].startswith("- "))
        ):
            continuation.append(lines[index].rstrip("\n"))
            index += 1
        if key in _LIST_FIELDS:
            if raw.startswith("["):
                if not raw.endswith("]"):
                    raise ValueError(f"Unclosed list for {key}")
                fields[key] = _parse_string_list(raw[1:-1])
            elif not raw:
                values = [line.strip() for line in continuation if line.strip()]
                if any(not value.startswith("- ") for value in values):
                    raise ValueError(f"Expected a string list for {key}")
                fields[key] = [
                    unquote_scalar(value[2:].strip()) for value in values
                ]
            else:
                raise ValueError(f"Expected a list for {key}")
        elif key in _SCALAR_FIELDS:
            if raw in {"|", "|-", "|+", ">", ">-", ">+"}:
                fields[key] = "\n".join(
                    line.strip() for line in continuation
                ).strip()
            else:
                combined = "\n".join(
                    [raw, *(line.strip() for line in continuation)]
                ).rstrip()
                fields[key] = unquote_scalar(combined)
    return fields, sum(len(line) for line in lines[: closing + 1])


def scalar(fields: Metadata, key: str) -> str:
    """Return a scalar metadata value, using empty text only for absent fields.

    Args:
        fields: Parsed entry metadata.
        key: Scalar field name.

    Returns:
        The scalar value or empty text for an optional or missing field.

    Raises:
        ValueError: A scalar field holds a list.
    """
    value = fields.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"Expected scalar metadata for {key}")
    return value


def _parse_string_list(text: str) -> list[str]:
    """Split a flow list only at commas outside quoted string values."""
    values: list[str] = []
    start = 0
    index = 0
    quote = ""
    while index < len(text):
        character = text[index]
        if quote:
            if quote == '"' and character == "\\":
                index += 2
                continue
            if character == quote:
                if quote == "'" and text[index : index + 2] == "''":
                    index += 2
                    continue
                quote = ""
        elif character in {"'", '"'} and not text[start:index].strip():
            quote = character
        elif character == ",":
            values.append(unquote_scalar(text[start:index].strip()))
            start = index + 1
        index += 1
    if quote:
        raise ValueError("Unterminated quoted frontmatter list item")
    if text[start:].strip():
        values.append(unquote_scalar(text[start:].strip()))
    return values
