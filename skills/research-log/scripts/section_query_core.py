"""Parse and query structured Markdown research-log sections."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import quote

CANONICAL_TYPES: tuple[str, ...] = (
    "Goal", "Changes", "Setup", "Results", "Failures",
    "Analysis", "Charts", "Conclusion", "Next Steps",
)
HEADING_ALIASES: dict[str, str] = {
    "failure": "Failures",
    "failures": "Failures",
    "pitfall": "Failures",
    "pitfalls": "Failures",
    "failures / pitfalls": "Failures",
}

_EXCLUDED_NAMES = frozenset({"INDEX.md", "MILESTONES.md"})
_HEADING_PATTERN = re.compile(r"^[ \t]{0,3}##(?!#)[ \t]+(.+?)[ \t]*(?:\r?\n)?$")
_FENCE_PATTERN = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_SCALAR_PATTERN = re.compile(r"^(date|experiment):[ \t]*(.*?)[ \t]*$")
_CANONICAL_BY_NORMALIZED = {
    " ".join(type_name.split()).casefold(): type_name
    for type_name in CANONICAL_TYPES
}


@dataclass(frozen=True)
class QueryWarning:
    """Describe a non-fatal problem found while scanning one log."""

    code: str
    path: str
    message: str


@dataclass(frozen=True)
class SectionOccurrence:
    """Represent one level-two section occurrence in a research log."""

    result_id: str
    path: Path
    log_stem: str
    log_date: date | None
    experiment: str | None
    type_name: str
    type_key: str
    original_heading: str
    occurrence_number: int
    body: str
    body_start: int
    body_end: int


@dataclass(frozen=True)
class ScanResult:
    """Contain parsed sections, warnings, and a content fingerprint."""

    sections: tuple[SectionOccurrence, ...]
    warnings: tuple[QueryWarning, ...]
    journal_fingerprint: str


@dataclass(frozen=True)
class TypeSummary:
    """Summarize one canonical or discovered section type."""

    name: str
    key: str
    canonical: bool
    variants: tuple[str, ...]
    occurrence_count: int
    log_count: int
    earliest_date: date | None
    latest_date: date | None


class JournalReadError(Exception):
    """Report a log file that cannot be decoded as UTF-8."""

    def __init__(self, path: Path) -> None:
        """Initialize the decoding failure for one log path.

        Args:
            path: Path of the invalid UTF-8 log.
        """
        self.path = path
        super().__init__(f"Could not decode {path} as UTF-8.")


def normalize_heading(heading: str) -> tuple[str, str]:
    """Return a display name and URL-safe stable key for a heading.

    Args:
        heading: Raw text from a Markdown level-two heading.

    Returns:
        The normalized display name and its URL-safe case-insensitive key.
    """
    display_name = " ".join(heading.split())
    normalized = display_name.casefold()
    canonical_name = HEADING_ALIASES.get(normalized) or _CANONICAL_BY_NORMALIZED.get(
        normalized
    )
    if canonical_name is not None:
        display_name = canonical_name
        normalized = canonical_name.casefold()
    return display_name, quote(normalized, safe="-._~")


def scan_journal(log_dir: Path) -> ScanResult:
    """Scan UTF-8 Markdown logs without changing the filesystem.

    Args:
        log_dir: Directory containing Markdown research logs.

    Returns:
        Parsed section occurrences, metadata warnings, and a content fingerprint.

    Raises:
        JournalReadError: A selected Markdown file is not valid UTF-8.
    """
    if not log_dir.is_dir():
        return ScanResult((), (), sha256().hexdigest())

    markdown_paths = sorted(
        (
            path for path in log_dir.rglob("*.md")
            if path.is_file() and path.name not in _EXCLUDED_NAMES
        ),
        key=lambda path: path.relative_to(log_dir).as_posix(),
    )
    digest = sha256()
    all_sections: list[SectionOccurrence] = []
    all_warnings: list[QueryWarning] = []
    for path in markdown_paths:
        relative_path = path.relative_to(log_dir).as_posix()
        content_bytes = path.read_bytes()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_bytes)
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise JournalReadError(path) from error
        sections, warnings = _scan_log(path, relative_path, text)
        all_sections.extend(sections)
        all_warnings.extend(warnings)
    return ScanResult(tuple(all_sections), tuple(all_warnings), digest.hexdigest())


def discover_types(scan: ScanResult) -> tuple[TypeSummary, ...]:
    """Return canonical summaries first, followed by custom summaries.

    Args:
        scan: Parsed result from :func:`scan_journal`.

    Returns:
        One summary per canonical or discovered type.
    """
    sections_by_key: dict[str, list[SectionOccurrence]] = defaultdict(list)
    for section in scan.sections:
        sections_by_key[section.type_key].append(section)

    summaries: list[TypeSummary] = []
    canonical_keys = set()
    for canonical_name in CANONICAL_TYPES:
        _, canonical_key = normalize_heading(canonical_name)
        canonical_keys.add(canonical_key)
        summaries.append(_summarize_type(canonical_name, canonical_key, sections_by_key[canonical_key], True))

    custom_summaries = [
        _summarize_type(sections[0].type_name, type_key, sections, False)
        for type_key, sections in sections_by_key.items()
        if type_key not in canonical_keys
    ]
    custom_summaries.sort(key=lambda summary: summary.name.casefold())
    return tuple(summaries + custom_summaries)


def _scan_log(
    path: Path, relative_path: str, text: str
) -> tuple[list[SectionOccurrence], list[QueryWarning]]:
    """Parse metadata and level-two headings from one decoded log."""
    frontmatter, content_start = _parse_frontmatter(text)
    warnings: list[QueryWarning] = []
    experiment = frontmatter.get("experiment")
    if not experiment:
        warnings.append(QueryWarning(
            "missing_experiment", relative_path, "Missing experiment frontmatter field."
        ))
        experiment = None
    log_date = _parse_date(frontmatter.get("date"), relative_path, warnings)
    heading_matches = _find_level_two_headings(text, content_start)
    occurrences_by_key: dict[str, int] = defaultdict(int)
    sections: list[SectionOccurrence] = []
    for index, (heading_start, heading_end, heading) in enumerate(heading_matches):
        body_end = (
            heading_matches[index + 1][0]
            if index + 1 < len(heading_matches)
            else len(text)
        )
        type_name, type_key = normalize_heading(heading)
        occurrences_by_key[type_key] += 1
        occurrence_number = occurrences_by_key[type_key]
        result_id = f"{path.stem}::{type_key}"
        if occurrence_number > 1:
            result_id = f"{result_id}::{occurrence_number}"
        sections.append(SectionOccurrence(
            result_id=result_id,
            path=path,
            log_stem=path.stem,
            log_date=log_date,
            experiment=experiment,
            type_name=type_name,
            type_key=type_key,
            original_heading=heading,
            occurrence_number=occurrence_number,
            body=text[heading_end:body_end],
            body_start=heading_end,
            body_end=body_end,
        ))
    return sections, warnings


def _parse_frontmatter(text: str) -> tuple[dict[str, str], int]:
    """Return recognized scalar frontmatter and the content offset."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return {}, 0
    offset = len(lines[0])
    fields: dict[str, str] = {}
    for line in lines[1:]:
        offset += len(line)
        if line.rstrip("\r\n") == "---":
            return fields, offset
        match = _SCALAR_PATTERN.match(line.rstrip("\r\n"))
        if match is not None:
            fields[match.group(1)] = _unquote_scalar(match.group(2))
    return {}, 0


def _unquote_scalar(value: str) -> str:
    """Remove one matching pair of scalar quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _parse_date(
    raw_date: str | None, relative_path: str, warnings: list[QueryWarning]
) -> date | None:
    """Parse a scalar date and add a warning when it is malformed."""
    if raw_date is None:
        return None
    try:
        return date.fromisoformat(raw_date)
    except ValueError:
        warnings.append(QueryWarning(
            "invalid_date", relative_path, f"Invalid date frontmatter value: {raw_date}."
        ))
        return None


def _find_level_two_headings(text: str, content_start: int) -> list[tuple[int, int, str]]:
    """Locate unfenced level-two headings after frontmatter."""
    headings: list[tuple[int, int, str]] = []
    active_fence: tuple[str, int] | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        line_end = offset + len(line)
        if line_end <= content_start:
            offset = line_end
            continue
        fence_match = _FENCE_PATTERN.match(line)
        if active_fence is None and fence_match is not None:
            marker = fence_match.group(1)
            active_fence = (marker[0], len(marker))
            offset = line_end
            continue
        if active_fence is not None:
            if fence_match is not None:
                marker = fence_match.group(1)
                if marker[0] == active_fence[0] and len(marker) >= active_fence[1]:
                    active_fence = None
            offset = line_end
            continue
        heading_match = _HEADING_PATTERN.match(line)
        if heading_match is not None:
            headings.append((offset, line_end, heading_match.group(1)))
        offset = line_end
    return headings


def _summarize_type(
    name: str,
    key: str,
    sections: list[SectionOccurrence],
    canonical: bool,
) -> TypeSummary:
    """Create one type summary from its section occurrences."""
    variants = tuple(dict.fromkeys(section.original_heading for section in sections))
    log_paths = {section.path for section in sections}
    known_dates = [section.log_date for section in sections if section.log_date is not None]
    return TypeSummary(
        name=name,
        key=key,
        canonical=canonical,
        variants=variants,
        occurrence_count=len(sections),
        log_count=len(log_paths),
        earliest_date=min(known_dates, default=None),
        latest_date=max(known_dates, default=None),
    )
