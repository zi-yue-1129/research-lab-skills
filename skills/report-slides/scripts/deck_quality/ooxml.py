"""Low-level OOXML helpers: namespaces, shape walking with group transforms,
and the theme font scheme."""
from __future__ import annotations

from dataclasses import dataclass

from lxml import etree
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def q(tag: str) -> str:
    prefix, local = tag.split(":")
    return f"{{{NS[prefix]}}}{local}"


def local(el) -> str:
    return etree.QName(el).localname


@dataclass(frozen=True)
class Box:
    """An axis-aligned rectangle in slide EMU."""

    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def intersection(self, other: "Box") -> tuple[float, float]:
        w = min(self.right, other.right) - max(self.x, other.x)
        h = min(self.bottom, other.bottom) - max(self.y, other.y)
        return max(w, 0.0), max(h, 0.0)


@dataclass(frozen=True)
class Transform:
    """Maps a child coordinate to slide EMU: ``abs = s * child + t``."""

    sx: float = 1.0
    sy: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    def box(self, x, y, w, h) -> Box:
        return Box(self.sx * x + self.tx, self.sy * y + self.ty, self.sx * w, self.sy * h)


@dataclass(frozen=True)
class ShapeGeom:
    box: Box
    rot: int        # 60000ths of a degree
    flip_h: bool
    flip_v: bool


def _xfrm_of(el):
    for path in ("p:spPr/a:xfrm", "p:grpSpPr/a:xfrm", "p:xfrm"):
        found = el.find(path, NS)
        if found is not None:
            return found
    return None


def _pair(xfrm, tag, a="x", b="y"):
    node = xfrm.find(tag, NS) if xfrm is not None else None
    if node is None:
        return None
    return float(node.get(a, 0)), float(node.get(b, 0))


def walk(sp_tree, transform: Transform = Transform()):
    """Yield ``(element, transform)`` for every leaf shape under ``sp_tree``.

    Group shapes are descended into, composing their child-to-parent
    transform, so callers always get coordinates in slide EMU.
    """
    for el in sp_tree:
        tag = local(el)
        if tag == "grpSp":
            xfrm = _xfrm_of(el)
            off = _pair(xfrm, "a:off") or (0.0, 0.0)
            ext = _pair(xfrm, "a:ext", "cx", "cy")
            ch_off = _pair(xfrm, "a:chOff") or (0.0, 0.0)
            ch_ext = _pair(xfrm, "a:chExt", "cx", "cy")
            gx = ext[0] / ch_ext[0] if ext and ch_ext and ch_ext[0] else 1.0
            gy = ext[1] / ch_ext[1] if ext and ch_ext and ch_ext[1] else 1.0
            inner = Transform(
                sx=transform.sx * gx,
                sy=transform.sy * gy,
                tx=transform.sx * (off[0] - ch_off[0] * gx) + transform.tx,
                ty=transform.sy * (off[1] - ch_off[1] * gy) + transform.ty,
            )
            yield from walk(el, inner)
        elif tag in ("sp", "cxnSp", "pic", "graphicFrame"):
            yield el, transform


def geometry(el, transform: Transform) -> ShapeGeom | None:
    """Absolute geometry of a leaf shape, or None when it inherits its position."""
    xfrm = _xfrm_of(el)
    off = _pair(xfrm, "a:off")
    ext = _pair(xfrm, "a:ext", "cx", "cy")
    if off is None or ext is None:
        return None
    return ShapeGeom(
        box=transform.box(off[0], off[1], ext[0], ext[1]),
        rot=int(xfrm.get("rot", 0)),
        flip_h=xfrm.get("flipH") in ("1", "true"),
        flip_v=xfrm.get("flipV") in ("1", "true"),
    )


def placeholder_type(el) -> str | None:
    ph = el.find(".//p:nvPr/p:ph", NS)
    if ph is None:
        return None
    return ph.get("type", "body")


# ── theme ─────────────────────────────────────────────────────────────────

def theme_parts(prs):
    """Yield each distinct theme part used by the deck's slide masters."""
    seen = set()
    for master in prs.slide_masters:
        try:
            part = master.part.part_related_by(RT.THEME)
        except KeyError:
            continue
        if id(part) not in seen:
            seen.add(id(part))
            yield part


def theme_root(part):
    return etree.fromstring(part.blob)


def font_scheme(root) -> dict[str, dict[str, str | None]]:
    """Return ``{"major": {"latin", "ea"}, "minor": {...}}`` from a theme."""
    out: dict[str, dict[str, str | None]] = {}
    for kind in ("major", "minor"):
        node = root.find(f".//a:fontScheme/a:{kind}Font", NS)
        faces: dict[str, str | None] = {"latin": None, "ea": None}
        if node is not None:
            for script in faces:
                face = node.find(f"a:{script}", NS)
                faces[script] = face.get("typeface") if face is not None else None
        out[kind] = faces
    return out
