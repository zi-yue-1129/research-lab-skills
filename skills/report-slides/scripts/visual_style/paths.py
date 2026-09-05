"""Bounding-box extraction for SVG `<path>` data.

A pie chart is nothing but `<path>` elements, and so is any hand-authored
curve. Without geometry here they are invisible to `safe-area`, `element-overlap`
and `occupancy`, and the gate claims to have settled properties it never looked
at -- while the human reviewer has been told those properties are already
measured. That combination is worse than either alone.

The bound is a superset, never a subset. Bezier segments are bounded by their
control points, which is exact for the hull and never smaller than the curve;
arcs are bounded by the ellipse extremes actually swept. Over-reporting a
finding is a conversation; under-reporting one is a defect that ships.
"""
from __future__ import annotations

import math
import re
from typing import List, Optional, Tuple

_TOKEN_RE = re.compile(
    r"([MmZzLlHhVvCcSsQqTtAa])|(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
# Argument count per command, indexed by the uppercase letter.
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4,
          "Q": 4, "T": 2, "A": 7, "Z": 0}


def _tokenise(data: str) -> List[str]:
    """Split path data into commands and numbers.

    Args:
        data: The raw `d` attribute.

    Returns:
        Commands as single-letter strings and numbers as numeric strings, in
        source order.

    Raises:
        ValueError: If the data contains anything that is neither.
    """
    tokens: List[str] = []
    position = 0
    for match in _TOKEN_RE.finditer(data):
        if data[position:match.start()].strip(" \t\r\n,"):
            raise ValueError(
                f"path data has an unreadable token near offset {position}")
        tokens.append(match.group(0))
        position = match.end()
    if data[position:].strip(" \t\r\n,"):
        raise ValueError(
            f"path data has an unreadable token near offset {position}")
    return tokens


def _arc_extremes(x0: float, y0: float, rx: float, ry: float,
                  rotation: float, large_arc: bool, sweep: bool,
                  x1: float, y1: float) -> List[Tuple[float, float]]:
    """Return points bounding one elliptical-arc segment.

    Implements the SVG endpoint-to-centre conversion, then adds whichever of
    the ellipse's four cardinal extremes the arc actually sweeps. A rotated
    ellipse falls back to the circumscribing box, which is a superset.

    Args:
        x0: Segment start x.
        y0: Segment start y.
        rx: Radius along the ellipse's x axis.
        ry: Radius along the ellipse's y axis.
        rotation: `x-axis-rotation` in degrees.
        large_arc: The large-arc flag.
        sweep: The sweep flag.
        x1: Segment end x.
        y1: Segment end y.

    Returns:
        Points whose bounding box contains the arc.
    """
    points = [(x0, y0), (x1, y1)]
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return points

    phi = math.radians(rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x0 - x1) / 2.0, (y0 - y1) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    scale = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if scale > 1.0:
        rx *= math.sqrt(scale)
        ry *= math.sqrt(scale)

    numerator = (rx * rx * ry * ry - rx * rx * y1p * y1p
                 - ry * ry * x1p * x1p)
    denominator = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    if denominator == 0:
        return points
    factor = math.sqrt(max(0.0, numerator / denominator))
    if large_arc == sweep:
        factor = -factor
    cxp = factor * rx * y1p / ry
    cyp = -factor * ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (x0 + x1) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y0 + y1) / 2.0

    if rotation % 360.0 != 0.0:
        # A rotated ellipse's extremes are not at the cardinal angles. The
        # circumscribing box is a superset, which is the safe direction.
        radius = max(rx, ry)
        return points + [(cx - radius, cy - radius), (cx + radius, cy + radius)]

    start = math.atan2((y0 - cy) / ry, (x0 - cx) / rx)
    end = math.atan2((y1 - cy) / ry, (x1 - cx) / rx)
    delta = (end - start) % (2 * math.pi)
    if not sweep:
        delta -= 2 * math.pi

    for quarter in range(4):
        angle = quarter * math.pi / 2.0
        offset = (angle - start) % (2 * math.pi)
        if not sweep:
            offset -= 2 * math.pi
        if (0 <= offset <= delta) or (delta <= offset <= 0):
            points.append((cx + rx * math.cos(angle),
                           cy + ry * math.sin(angle)))
    return points


def path_points(data: str) -> List[Tuple[float, float]]:
    """Return points whose bounding box contains the whole path.

    Args:
        data: The raw `d` attribute.

    Returns:
        The collected points, empty when the path draws nothing.

    Raises:
        ValueError: If the data cannot be read, so the caller can report it
            rather than measure a path it did not understand.
    """
    tokens = _tokenise(data)
    points: List[Tuple[float, float]] = []
    cursor = 0
    command: Optional[str] = None
    x = y = start_x = start_y = 0.0

    while cursor < len(tokens):
        token = tokens[cursor]
        if token.isalpha():
            command = token
            cursor += 1
            if command.upper() == "Z":
                x, y = start_x, start_y
                points.append((x, y))
                continue
        elif command is None:
            raise ValueError("path data begins with a number, not a command")
        elif command.upper() == "M":
            # A repeated M argument list continues as an implicit lineto.
            command = "l" if command == "m" else "L"

        letter = (command or "").upper()
        arity = _ARITY.get(letter)
        if arity is None:
            raise ValueError(f"path data uses an unsupported command {command}")
        if cursor + arity > len(tokens):
            raise ValueError(f"path command {command} is missing arguments")
        args = [float(value) for value in tokens[cursor:cursor + arity]]
        cursor += arity
        relative = (command or "").islower()

        if letter == "H":
            x = x + args[0] if relative else args[0]
            points.append((x, y))
        elif letter == "V":
            y = y + args[0] if relative else args[0]
            points.append((x, y))
        elif letter == "A":
            end_x = x + args[5] if relative else args[5]
            end_y = y + args[6] if relative else args[6]
            points.extend(_arc_extremes(
                x, y, args[0], args[1], args[2],
                bool(args[3]), bool(args[4]), end_x, end_y))
            x, y = end_x, end_y
        else:
            pairs = [(args[index], args[index + 1])
                     for index in range(0, arity, 2)]
            for offset_x, offset_y in pairs:
                point_x = x + offset_x if relative else offset_x
                point_y = y + offset_y if relative else offset_y
                points.append((point_x, point_y))
            x, y = points[-1]
            if letter == "M":
                start_x, start_y = x, y
    return points


def path_bounds(data: str) -> Optional[Tuple[float, float, float, float]]:
    """Return `(x, y, width, height)` for a path, or None when it draws nothing.

    Args:
        data: The raw `d` attribute.

    Returns:
        The bounding rectangle in SVG units.

    Raises:
        ValueError: If the data cannot be read.
    """
    points = path_points(data)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
