"""Axis and value label formatting shared by both chart routes.

A slide's chart is drawn twice: once as SVG for review, and once as a native
PPTX chart for the exported deck. Both have to say the same thing about the
same numbers, so the rules that decide what a label reads live here rather
than in either renderer.
"""
from __future__ import annotations

from typing import List

_MAX_TICK_DECIMALS = 3
_TICK_COUNT = 6


def tick_decimals(y_max: float) -> int:
    """Return the fewest decimals that keep the six y ticks distinct.

    A fixed whole-number format labelled the shipped example deck's 0-1 axis
    0, 0, 0, 1, 1, 1: three pairs of identical numbers against six different
    grid lines. An axis whose labels repeat tells the reader nothing about the
    scale.

    Args:
        y_max: The axis maximum.

    Returns:
        A decimal count between 0 and 3. A degenerate axis (`y_max` of 0) has
        no distinct ticks at any precision and gets the maximum.
    """
    for decimals in range(_MAX_TICK_DECIMALS + 1):
        labels = {f"{y_max * i / 5:.{decimals}f}" for i in range(_TICK_COUNT)}
        if len(labels) == _TICK_COUNT:
            return decimals
    return _MAX_TICK_DECIMALS


def axis_tick_labels(y_max: float, unit: str) -> List[str]:
    """Return the six y-axis tick labels for a bar or line chart.

    The renderers appended a literal `%` to every tick, so a throughput series
    of 340 requests per second was labelled `340%`. A percentage suffix on
    non-percentage data is not a styling choice; it states something false
    about the numbers. The unit is declared per slide and defaults to empty,
    because a bare number is never wrong.

    Args:
        y_max: The axis maximum.
        unit: The slide's `unit` string, appended verbatim.

    Returns:
        Six labels, from 0 to `y_max`.
    """
    decimals = tick_decimals(y_max)
    return [f"{y_max * i / 5:.{decimals}f}{unit}" for i in range(_TICK_COUNT)]


def number_format(unit: str, decimals: int) -> str:
    """Return the PPTX number format that reproduces one of those labels.

    A native chart formats its own labels, so the unit has to reach it as a
    format string rather than as text. The unit is quoted: an unquoted `%` is
    an operator in this format language, and Excel would multiply the value by
    a hundred before printing it, turning a bar of 98.4 into `9840%`.

    Args:
        unit: The slide's `unit` string.
        decimals: Decimal places, as `tick_decimals` chose them.

    Returns:
        A number format string such as `0.0"%"`.
    """
    base = "0" if decimals <= 0 else "0." + "0" * decimals
    if not unit:
        return base
    return f'{base}"{unit.replace(chr(34), "")}"'
