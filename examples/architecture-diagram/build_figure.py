#!/usr/bin/env python3
"""build_figure.py -- the same architecture at figure density, on one page.

`build_diagram.py` composes for a slide and pages onto a second one. This uses
the `figure` token set instead: the same type sizes and spacing floors on a
2400x1350 canvas, which is four times the area, so the whole model fits once
with room for the detail a slide has to leave out.

    python3 examples/architecture-diagram/build_figure.py
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
        SystemExit: With an actionable message when the skill is absent.
    """
    for path in (
        Path.home() / ".claude" / "skills" / "report-slides",
        Path(__file__).resolve().parents[2] / "skills" / "report-slides",
    ):
        if (path / "scripts" / "diagram_builder.py").is_file():
            return path
    sys.exit(
        "report-slides skill not found. Install it with `bash install.sh` from "
        "the repository root, or run this script from inside a clone."
    )


SKILL = find_skill()
sys.path.insert(0, str(SKILL / "scripts"))

from diagram_builder import Diagram  # noqa: E402

TOKENS = yaml.safe_load(
    (SKILL / "references" / "tokens" / "figure.tokens.yaml").read_text(encoding="utf-8")
)


def compose() -> Diagram:
    """Build the full model as one figure.

    Returns:
        The composed diagram, not yet written.
    """
    d = Diagram(
        TOKENS,
        title="Transformer encoder — full architecture",
        subtitle="Input pipeline, the repeated stack, both sub-blocks opened up, and the training path",
        footnote="Amber: active only during training. Arcs are residual identities. "
                 "B batch, L sequence length, d model width, H heads.",
    )

    inp = d.section("in", "1. Input", flow="row")
    tok = d.node(inp, "tok", ["Token ids"], shape="(B, L)", kind="data")
    emb = d.node(inp, "emb", ["Embedding", "vocab 32k, weight-tied"], shape="(B, L, d)")
    pos = d.node(inp, "pos", ["Rotary position", "applied to Q and K"], shape="(B, L, d)")

    stack = d.section("stack", "2. Encoder stack  (N = 24)", flow="row")
    b1 = d.node(stack, "b1", ["Block 1"], shape="(B, L, d)", kind="accent")
    b2 = d.node(stack, "b2", ["Block 2"], shape="(B, L, d)")
    d.ellipsis(stack, "rep")
    bn = d.node(stack, "bn", ["Block N"], shape="(B, L, d)")

    head = d.section("head", "3. Head", flow="row")
    pool = d.node(head, "pool", ["Mean pool", "masked over padding"], shape="(B, d)")
    proj = d.node(head, "proj", ["Task head", "Linear d to C"], shape="(B, C)")
    loss = d.node(head, "loss", ["Cross-entropy", "label smoothing 0.1"],
                  shape="scalar", kind="aux")

    attn = d.section("attn", "4. Self-attention sub-block  (pre-norm residual)",
                     flow="row")
    ag = d.group(attn, "g", "", flow="row")
    ln1 = d.node(ag, "ln1", ["LayerNorm"], shape="(B, L, d)")
    qkv = d.node(ag, "qkv", ["QKV projection", "3 x Linear d to d"],
                 shape="(B, H, L, d/H)")
    sdp = d.node(ag, "sdp", ["Scaled dot-product", "causal mask, dropout 0.1"],
                 shape="(B, H, L, L)", kind="accent")
    out = d.node(ag, "out", ["Output projection"], shape="(B, L, d)")
    add1 = d.op(ag, "add1", "+")

    ffn = d.section("ffn", "5. Feed-forward sub-block  (pre-norm residual)",
                    flow="row")
    fg = d.group(ffn, "g", "", flow="row")
    ln2 = d.node(fg, "ln2", ["LayerNorm"], shape="(B, L, d)")
    up = d.node(fg, "up", ["Linear d to 4d", "GELU, dropout 0.1"], shape="(B, L, 4d)")
    dn = d.node(fg, "dn", ["Linear 4d to d"], shape="(B, L, d)")
    add2 = d.op(fg, "add2", "+")

    train = d.section("train", "6. Training", flow="row")
    fwd = d.node(train, "fwd", ["Forward pass", "bf16 autocast"], shape="(B, L, d)")
    bwd = d.node(train, "bwd", ["Backward", "grad clip 1.0"], shape="grads", kind="aux")
    opt = d.node(train, "opt", ["AdamW", "beta 0.9 / 0.95, wd 0.1"], shape="params",
                 kind="aux")
    sched = d.node(train, "sched", ["Cosine schedule", "2k warmup steps"],
                   shape="lr", kind="aux")

    infer = d.section("infer", "7. Inference", flow="row")
    cache = d.node(infer, "cache", ["KV cache", "per layer, per head"],
                   shape="(B, H, L, d/H)")
    step = d.node(infer, "step", ["Incremental step", "one token at a time"],
                  shape="(B, 1, d)", kind="accent")
    samp = d.node(infer, "samp", ["Sampling", "top-p 0.9, temp 0.8"], shape="(B, 1)")
    outp = d.node(infer, "out", ["Generated token"], shape="(B, 1)", kind="data")

    for a, b in (
        (fwd, bwd), (bwd, opt), (opt, sched),
        (cache, step), (step, samp), (samp, outp),
        (tok, emb), (emb, pos), (pos, b1), (b1, b2), (bn, pool), (pool, proj),
        (proj, loss), (ln1, qkv), (qkv, sdp), (sdp, out), (out, add1),
        (ln2, up), (up, dn), (dn, add2),
    ):
        d.connect(a, b)
    d.connect(ln1, add1, route="over")
    d.connect(ln2, add2, route="over")
    d.connect(loss, sdp, route="under", style="dashed", kind="aux")
    return d


if __name__ == "__main__":
    figure = compose()
    for written in figure.write(Path(__file__).parent / "figure-01.svg"):
        print("wrote", written)
    for source, target in figure.spanning_connections():
        print(f"note: {source} -> {target} spans a page break and was not drawn")
