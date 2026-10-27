"""Title-slide motifs for the zh-classroom preset.

Each motif is ``draw(builder, slide, cx, y)``: it draws native shapes centred
on ``cx`` with its top at ``y`` (inches), using the builder's primitives and
theme colours. The core builder loads ``MOTIFS`` from here only when this
preset is active.
"""
from __future__ import annotations


def tree(b, slide, cx: float, y: float) -> None:
    """Two-level decision tree with four leaves, from the 分類與決策樹 deck."""
    line = b.t["colors"]["line"]
    nodes = [(cx, y), (cx - 0.9, y + 0.55), (cx + 0.9, y + 0.55)]
    for (px, py), (qx, qy) in ((nodes[0], nodes[1]), (nodes[0], nodes[2])):
        b.line(slide, px, py + 0.12, qx, qy, color=line)
    for nx, ny in nodes:
        b.box(slide, nx - 0.4, ny - 0.05, 0.8, 0.22, fill=b.t["colors"]["card"],
              border=line, radius=0.1, shadow=False)
    for i, nx in enumerate((cx - 1.3, cx - 0.5, cx + 0.5, cx + 1.3)):
        b.dot(slide, nx - 0.06, y + 1.1, 0.12,
              b.accent("positive") if i % 2 else b.t["colors"]["card"],
              border=b.accent("positive"))


MOTIFS = {"tree": tree}
