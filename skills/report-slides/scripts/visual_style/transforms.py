"""Affine `transform` resolution for the SVG scene parser.

`svg_to_pptx.style_parser.parse_transform` reads `translate`, `rotate`, `scale`
and `matrix`, so a deck may use any of them and still convert. The linter used
to accept only `translate` and raise on the rest, which turned a perfectly
convertible slide into an `unreadable-input` finding and blocked the gate.

Composing the matrix instead is both more permissive and more honest: a
transformed element is measured where it is actually drawn, and a rotated shape
is reported by the axis-aligned box that contains it -- a superset, which can
start a conversation, rather than the untransformed coordinates, which describe
a slide that does not exist.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

_TRANSFORM_CALL_RE = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")
_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARGUMENT_SEPARATORS = " \t\r\n,"

# Argument counts SVG allows for each function this parser understands.
_ARGUMENT_COUNTS = {
    "translate": (1, 2),
    "scale": (1, 2),
    "rotate": (1, 3),
    "matrix": (6,),
}


@dataclass(frozen=True)
class Affine:
    """A 2D affine transform in SVG's `matrix(a b c d e f)` ordering.

    A point maps as `x' = a*x + c*y + e`, `y' = b*x + d*y + f`.

    Attributes:
        a: Column-one x coefficient.
        b: Column-one y coefficient.
        c: Column-two x coefficient.
        d: Column-two y coefficient.
        e: Translation in x.
        f: Translation in y.
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def apply(self, x: float, y: float) -> Tuple[float, float]:
        """Map one point through the transform.

        Args:
            x: Point x coordinate.
            y: Point y coordinate.

        Returns:
            The transformed `(x, y)`.
        """
        return (self.a * x + self.c * y + self.e,
                self.b * x + self.d * y + self.f)

    def compose(self, other: "Affine") -> "Affine":
        """Return this transform applied after `other`.

        SVG nests transforms so that the outermost is applied last, and a
        transform list reads the same way: in `translate(100,0) scale(2)` the
        point is scaled first. Composing in the other order is silent and
        wrong, so it has a test of its own.

        Args:
            other: The transform applied first.

        Returns:
            The composed transform.
        """
        return Affine(
            a=self.a * other.a + self.c * other.b,
            b=self.b * other.a + self.d * other.b,
            c=self.a * other.c + self.c * other.d,
            d=self.b * other.c + self.d * other.d,
            e=self.a * other.e + self.c * other.f + self.e,
            f=self.b * other.e + self.d * other.f + self.f)

    def bounds(self, x: float, y: float, w: float, h: float
               ) -> Tuple[float, float, float, float]:
        """Return the axis-aligned box containing a transformed rectangle.

        Args:
            x: Untransformed left edge.
            y: Untransformed top edge.
            w: Untransformed width.
            h: Untransformed height.

        Returns:
            `(x, y, width, height)` of the hull, exact when the transform is
            axis-aligned and a superset once rotation is involved.
        """
        corners = [self.apply(x, y), self.apply(x + w, y),
                   self.apply(x, y + h), self.apply(x + w, y + h)]
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def scale_factor(self) -> float:
        """Return the uniform scale this transform applies to lengths.

        Font sizes and measured text widths have no orientation to carry
        through a matrix, so they travel by area: the square root of the
        determinant is 1.0 for any rotation or reflection and `s` for
        `scale(s)`, which is the behaviour a reader expects.

        Returns:
            The scale factor, never negative.
        """
        return math.sqrt(abs(self.a * self.d - self.b * self.c))


IDENTITY = Affine()


def _named_transform(name: str, numbers: List[float]) -> Optional[Affine]:
    """Build the affine for one transform function.

    Args:
        name: The function name, already known to be supported.
        numbers: Its arguments, already known to be the right count.

    Returns:
        The affine, or None when the name is not one this parser builds.
    """
    if name == "translate":
        return Affine(e=numbers[0], f=numbers[1] if len(numbers) > 1 else 0.0)
    if name == "scale":
        return Affine(a=numbers[0],
                      d=numbers[1] if len(numbers) > 1 else numbers[0])
    if name == "rotate":
        radians = math.radians(numbers[0])
        cos, sin = math.cos(radians), math.sin(radians)
        rotation = Affine(a=cos, b=sin, c=-sin, d=cos)
        if len(numbers) == 1:
            return rotation
        centre_x, centre_y = numbers[1], numbers[2]
        return (Affine(e=centre_x, f=centre_y)
                .compose(rotation)
                .compose(Affine(e=-centre_x, f=-centre_y)))
    if name == "matrix":
        return Affine(*numbers)
    return None


def parse_transform(raw: Optional[str], element_id: str) -> Affine:
    """Resolve a `transform` attribute into a single affine transform.

    Every character of the attribute has to be accounted for. An earlier
    version matched arguments with a digits-and-dots pattern, so
    `translate(1e2,0)` matched nothing at all and the translation was silently
    dropped -- the element was then measured a hundred units from where it is
    drawn and the slide passed. Refusing is the honest outcome for anything
    this parser cannot read: the linter turns the error into
    `unreadable-input`, which names the file.

    Args:
        raw: The raw `transform` attribute, or None.
        element_id: Identifier used in the error message.

    Returns:
        The composed transform, or the identity when the attribute is absent.

    Raises:
        ValueError: If the transform names a function this parser does not
            support, carries the wrong number of arguments, or holds anything
            that cannot be read as a number.
    """
    if not raw or not raw.strip():
        return IDENTITY
    matrix = IDENTITY
    seen = False
    for match in _TRANSFORM_CALL_RE.finditer(raw):
        seen = True
        name, arguments = match.group(1), match.group(2)
        if name not in _ARGUMENT_COUNTS:
            raise ValueError(
                f"{element_id} carries an unsupported transform {name}; "
                "translate, scale, rotate and matrix can be measured")
        numbers = [float(token) for token in _NUMBER_RE.findall(arguments)]
        residue = _NUMBER_RE.sub("", arguments).strip(_ARGUMENT_SEPARATORS)
        if residue or len(numbers) not in _ARGUMENT_COUNTS[name]:
            raise ValueError(
                f"{element_id} has a transform this parser cannot read: "
                f"{name}({arguments})")
        function = _named_transform(name, numbers)
        if function is None:
            raise ValueError(
                f"{element_id} has a transform this parser cannot read: "
                f"{name}({arguments})")
        matrix = matrix.compose(function)
    outside = _TRANSFORM_CALL_RE.sub("", raw).strip()
    if outside or not seen:
        raise ValueError(
            f"{element_id} has a transform this parser cannot read: {raw!r}")
    return matrix
