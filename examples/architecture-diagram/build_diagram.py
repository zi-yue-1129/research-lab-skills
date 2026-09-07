#!/usr/bin/env python3
"""build_diagram.py -- compose the example architecture figure.

Run it from anywhere; it finds the report-slides skill whether you installed it
(`bash install.sh`) or are working inside a clone of this repository:

    python3 examples/architecture-diagram/build_diagram.py

It writes `slide-01.svg` beside itself. Turning that into an editable PPTX is a
second, optional step -- see this directory's README -- so the figure itself
needs nothing beyond Python and the skill.

Edit the composition below and re-run. You never write a coordinate: every box
is sized from the measured width of its own text, positions snap to the token
grid, and the builder raises rather than letting a composition run off the
canvas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml


def find_skill() -> Path:
    """Locate the installed or in-repo report-slides skill.

    Returns:
        The skill's root directory.

    Raises:
        SystemExit: With an actionable message when the skill is not present,
            rather than a traceback about an import.
    """
    candidates = [
        Path.home() / ".claude" / "skills" / "report-slides",
        Path(__file__).resolve().parents[2] / "skills" / "report-slides",
    ]
    for path in candidates:
        if (path / "scripts" / "diagram_builder.py").is_file():
            return path
    sys.exit(
        "report-slides skill not found. Install it with `bash install.sh` from "
        "the repository root, or run this script from inside a clone."
    )


SKILL = find_skill()
sys.path.insert(0, str(SKILL / "scripts"))

from diagram_builder import Diagram  # noqa: E402  (needs the path above)

TOKENS = yaml.safe_load(
    (SKILL / "references" / "tokens" / "default.tokens.yaml").read_text(encoding="utf-8")
)


def compose() -> Diagram:
    """Build the figure: a transformer encoder stack with one block opened up.

    Returns:
        The composed diagram, not yet written.
    """
    d = Diagram(
        TOKENS,
        title="Transformer encoder stack",
        subtitle="Token stream to pooled representation, with one block opened up",
        footnote="Amber: the training-only gradient path. Arcs are residual identities. L sequence length, d model width, H heads.",
    )

    # Band 0 -- the pipeline, read left to right.
    stack = d.section("stack", "1. Forward path  (encoder stack, N=24)",
                      flow="row")
    tok = d.node(stack, "tok", ["Token ids"], shape="(B, L)", kind="data")
    emb = d.node(stack, "emb", ["Embedding", "vocab 32k, tied"], shape="(B, L, d)")
    pos = d.node(stack, "pos", ["Rotary position"], shape="(B, L, d)")
    b1 = d.node(stack, "b1", ["Block 1"], shape="(B, L, d)", kind="accent")
    d.ellipsis(stack, "rep")
    bn = d.node(stack, "bn", ["Block N"], shape="(B, L, d)")

    pool = d.node(stack, "pool", ["Mean pool"], shape="(B, d)")
    loss = d.node(stack, "loss", ["Cross-entropy"], shape="scalar", kind="aux")

    # Band 1 -- one block opened up. Nested groups are what let a figure show
    # internals without becoming a second figure.
    # The builder refused one section holding both sub-blocks -- taller than a
    # canvas on its own -- and said to split it. Two sections is the fix, and
    # paging then places them wherever they fit.
    attn_sec = d.section("attn", "2. Self-attention  (pre-norm residual)",
                         flow="row")
    attn = d.group(attn_sec, "g", "", flow="row")
    ln1 = d.node(attn, "ln1", ["LayerNorm"], shape="(B, L, d)")
    sdp = d.node(attn, "sdp", ["Scaled dot-product", "H heads, causal mask"],
                 shape="(B, H, L, L)", kind="accent")
    add1 = d.op(attn, "add1", "+")

    ffn_sec = d.section("ffn", "3. Feed-forward  (pre-norm residual)", flow="row")
    ffn = d.group(ffn_sec, "g", "", flow="row")
    ln2 = d.node(ffn, "ln2", ["LayerNorm"], shape="(B, L, d)")
    up = d.node(ffn, "up", ["Linear d to 4d", "GELU, dropout 0.1"],
                shape="(B, L, 4d)")
    add2 = d.op(ffn, "add2", "+")

    for source, target in (
        (tok, emb), (emb, pos), (pos, b1), (bn, pool), (pool, loss),
        (ln1, sdp), (sdp, add1), (ln2, up), (up, add2),
    ):
        d.connect(source, target)

    # Identity paths skip the sub-block they wrap; that is the residual.
    d.connect(ln1, add1, route="over")
    d.connect(ln2, add2, route="over")
    d.connect(add1, ln2, route="auto")
    d.connect(loss, sdp, route="under", style="dashed", kind="aux")
    return d


if __name__ == "__main__":
    diagram = compose()
    for written in diagram.write(Path(__file__).parent / "slide-01.svg"):
        print("wrote", written)
    for source, target in diagram.spanning_connections():
        print(f"note: {source} -> {target} spans a page break and was not drawn")
