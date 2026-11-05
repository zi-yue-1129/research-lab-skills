"""Script detection and text-width estimates shared by the rules and fixers."""
from __future__ import annotations

import re

# Han, kana, Hangul, Bopomofo, CJK punctuation, and full-width forms. Anything
# else (Latin, digits, Greek, maths symbols, ASCII punctuation) is "latin".
_CJK = re.compile(
    "[⺀-⿿　-〿぀-ヿ㄀-ㄯ㄰-㆏"
    "ㆠ-ㇿ㈀-㏿㐀-䶿一-鿿가-힯"
    "豈-﫿︰-﹏＀-￯\U00020000-\U0002fa1f]"
)


def script_of(ch: str) -> str | None:
    """Return ``"cjk"``, ``"latin"``, or None for script-neutral whitespace."""
    if ch.isspace() and ch != "　":
        return None
    return "cjk" if _CJK.match(ch) else "latin"


def split_by_script(text: str) -> list[tuple[str, str]]:
    """Split ``text`` into ``(script, segment)`` runs.

    Whitespace joins the segment before it (or the first segment, when the
    text starts with whitespace), so splitting never creates blank runs.
    """
    segments: list[list] = []
    pending = ""
    for ch in text:
        s = script_of(ch)
        if s is None:
            if segments:
                segments[-1][1] += ch
            else:
                pending += ch
            continue
        if segments and segments[-1][0] == s:
            segments[-1][1] += ch
        else:
            segments.append([s, pending + ch])
            pending = ""
    if pending:
        if segments:
            segments[-1][1] += pending
        else:
            return [("latin", pending)]
    return [(s, t) for s, t in segments]


def scripts_in(text: str) -> set[str]:
    return {s for s in map(script_of, text) if s}


def em_width(text: str) -> float:
    """Approximate width in em of ``text`` in a proportional face.

    CJK is 1 em; Latin glyphs use typical serif/sans averages (space 0.25,
    lowercase 0.45, uppercase 0.65, digits 0.5, punctuation 0.3, other 0.55).
    It is a screen, not a measurement: the exported page images decide.
    """
    total = 0.0
    for ch in text:
        if script_of(ch) == "cjk":
            total += 1.0
        elif ch.isspace():
            total += 0.25
        elif ch.islower():
            total += 0.45
        elif ch.isupper():
            total += 0.65
        elif ch.isdigit():
            total += 0.5
        elif ch in ".,:;'!|()[]{}-/\\\"`":
            total += 0.3
        else:
            total += 0.55
    return total
