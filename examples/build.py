"""Compose the demo diagram. Rerun after editing to regenerate everything."""
import sys, yaml
from pathlib import Path
sys.path.insert(0, r"D:/LearningData/self_learn/research-lab-skills/skills/report-slides/scripts")
from diagram_builder import Diagram

tokens = yaml.safe_load(Path(
    r"D:/LearningData/self_learn/research-lab-skills/skills/report-slides/references/tokens/default.tokens.yaml"
).read_text(encoding="utf-8"))

d = Diagram(tokens,
    title="Retrieval-augmented answering",
    subtitle="A question is grounded in retrieved passages before a single decode pass",
    footnote="Amber border marks a component built offline and only read at query time.")

i = d.boundary("ingest", "1. Index  (offline)")
n1 = d.node(i, "docs",  ["Document corpus"], shape="N documents", kind="data")
n2 = d.node(i, "chunk", ["Chunker"],         shape="512 tok, 64 overlap")
n3 = d.node(i, "emb",   ["Passage encoder"], shape="frozen  \u2192  (N, 768)")
n4 = d.node(i, "index", ["Vector index"],    shape="HNSW, cosine", kind="aux")

r = d.boundary("query", "2. Retrieve  (online)")
m1 = d.node(r, "q",    ["Question"],              shape="(B, Lq)", kind="data")
m2 = d.node(r, "qenc", ["Query encoder"],         shape="shared weights", kind="module")
m3 = d.node(r, "top",  ["Top-k search"],          shape="(B, k, 768)", kind="accent")
m4 = d.node(r, "rank", ["Reranker"],  shape="(B, k)")

g = d.boundary("generate", "3. Ground and answer")
o1 = d.node(g, "ctx", ["Prompt assembly"],    shape="question + passages")
o2 = d.node(g, "lm",  ["Decoder LM"],         shape="(B, Lc, d)", kind="accent")
o3 = d.node(g, "ans", ["Answer"], shape="(B, La) + citations", kind="data")

for a, b in ((n1,n2),(n2,n3),(n3,n4),(m1,m2),(m2,m3),(m3,m4),(m4,o1),(o1,o2),(o2,o3)):
    d.connect(a, b)
d.connect(n4, m3, label="k nearest", style="dashed")

print("wrote", d.write(Path(__file__).parent / "slide-01.svg"))
