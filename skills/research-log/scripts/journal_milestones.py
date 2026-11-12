"""Parse preserved milestone definitions and journal-local rendering options."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

_HEADER = re.compile(r"^## (M\d+): (.+)$")
_STATUS = re.compile(r"\*\*Status:\*\*[ \t]*(ongoing|closed)\b")
_OPTIONS = re.compile(r"<!-- research-log: (.*?) -->")


class MilestoneFormatError(ValueError):
    """Report a milestone source error with its one-based line number."""

    def __init__(self, message: str, line: int) -> None:
        """Initialize a source diagnostic.

        Args:
            message: Description of the invalid source.
            line: One-based source line number.
        """
        super().__init__(message)
        self.line = line


@dataclass(frozen=True)
class Milestone:
    """Store a source milestone's identity, description and preserved status."""

    identifier: str
    title: str
    description: str
    status: str


@dataclass(frozen=True)
class MilestoneDocument:
    """Store source definitions and deterministic table rendering options."""

    milestones: tuple[Milestone, ...]
    options_comment: str = ""
    summary_chars: int = 300
    split_closed: bool = False


def read_milestones(path: Path) -> MilestoneDocument:
    """Parse source headers without retaining old generated table contents.

    Args:
        path: Existing MILESTONES.md source.

    Returns:
        Definitions in source order and validated journal-local options.
        A legacy file without headers returns an empty definition sequence.

    Raises:
        MilestoneFormatError: Headers, boundaries, statuses or options are invalid.
        OSError: The source cannot be read.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    comment, summary_chars, split_closed = _read_options(lines)
    headers = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _HEADER.fullmatch(line)) is not None
    ]
    milestones: list[Milestone] = []
    identifiers: set[str] = set()
    for position, (start, match) in enumerate(headers):
        end = (
            headers[position + 1][0]
            if position + 1 < len(headers)
            else len(lines)
        )
        identifier, title = match.groups()
        if identifier in identifiers:
            raise MilestoneFormatError(
                f"Duplicate milestone {identifier}", start + 1
            )
        identifiers.add(identifier)
        boundary = next(
            (
                index
                for index in range(start + 1, end)
                if lines[index].startswith("**Date range:**")
            ),
            None,
        )
        description_end = boundary if boundary is not None else end
        for index in range(start + 1, description_end):
            if re.match(r"^##(?:\s|$)", lines[index]):
                raise MilestoneFormatError(
                    "Unexpected level-two heading in milestone description",
                    index + 1,
                )
        if boundary is None:
            raise MilestoneFormatError(
                f"Missing **Date range:** for {identifier}", start + 1
            )
        status_match = next(
            (
                found
                for line in lines[boundary:end]
                if (found := _STATUS.search(line)) is not None
            ),
            None,
        )
        if status_match is None:
            raise MilestoneFormatError(
                f"Missing or invalid status for {identifier}", boundary + 1
            )
        description = "\n".join(lines[start + 1 : boundary]).rstrip()
        milestones.append(
            Milestone(identifier, title, description, status_match.group(1))
        )
    return MilestoneDocument(
        tuple(milestones), comment, summary_chars, split_closed
    )


def _read_options(lines: list[str]) -> tuple[str, int, bool]:
    """Validate the single options comment immediately following the title."""
    first_header = next(
        (index for index, line in enumerate(lines) if _HEADER.fullmatch(line)),
        len(lines),
    )
    comments = [
        (index, line)
        for index, line in enumerate(lines[:first_header])
        if "<!-- research-log:" in line
    ]
    if not comments:
        return "", 300, False
    index, comment = comments[0]
    if len(comments) != 1 or index != 1 or lines[0] != "# Research Milestones":
        raise MilestoneFormatError(
            "Options must be one comment directly under # Research Milestones",
            index + 1,
        )
    match = _OPTIONS.fullmatch(comment)
    if match is None:
        raise MilestoneFormatError(
            "Malformed research-log options comment", index + 1
        )
    options: dict[str, str] = {}
    for setting in match.group(1).split():
        key, separator, value = setting.partition("=")
        if (
            not separator
            or key not in {"summary_chars", "split_closed"}
            or key in options
        ):
            raise MilestoneFormatError(
                f"Unknown, duplicate or malformed option: {setting}", index + 1
            )
        options[key] = value
    raw_chars = options.get("summary_chars", "300")
    if not raw_chars.isdecimal() or int(raw_chars) < 1:
        raise MilestoneFormatError(
            "summary_chars must be a positive integer", index + 1
        )
    raw_split = options.get("split_closed", "false")
    if raw_split not in {"true", "false"}:
        raise MilestoneFormatError(
            "split_closed must be true or false", index + 1
        )
    return comment, int(raw_chars), raw_split == "true"
