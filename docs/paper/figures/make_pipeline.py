"""Pipeline figure for the Lemma paper: `uv run python docs/paper/figures/make_pipeline.py` -> pipeline.{pdf,svg,png}."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "svg.fonttype": "none", "pdf.fonttype": 42})

INK, MUTE = "#1f2328", "#6e7781"
FILL = {"input": "#f6f8fa", "host": "#eaf2fb", "agent": "#fdf1e4", "proof": "#e9f6ec", "serve": "#f6f8fa"}
EDGE = {"input": "#d0d7de", "host": "#9cc1ea", "agent": "#f0b97a", "proof": "#8fd19e", "serve": "#d0d7de"}

fig, ax = plt.subplots(figsize=(7.0, 2.35))
ax.set_xlim(0, 100)
ax.set_ylim(0, 34)
ax.axis("off")


def box(x, y, w, h, title, sub, kind):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=1.2",
                                fc=FILL[kind], ec=EDGE[kind], lw=0.9))
    ax.text(x + w / 2, y + h * 0.64, title, ha="center", va="center", color=INK, fontweight="bold")
    ax.text(x + w / 2, y + h * 0.3, sub, ha="center", va="center", color=MUTE, fontsize=7, linespacing=1.15)


def arrow(x0, y0, x1, y1, text=None, rad=0.0, dy=1.6):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=8, lw=0.8,
                                 color=MUTE, connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2 + dy, text, ha="center", va="center", color=MUTE, fontsize=6.5)


# top row: the per-query synthesis path
box(0.5, 20, 15, 11, "SQL query", "+ schema\n+ data assumptions", "input")
box(20.5, 20, 16, 11, "Transpiler", "deterministic\nSQL → Verus spec", "host")
box(41.5, 20, 17, 11, "LLM agent", "writes run_query\n(sandboxed)", "agent")
box(63.5, 20, 15, 11, "Verus", "proves run_query\n≡ spec", "proof")
box(83.5, 20, 16, 11, "Compile", "native binary\n(Rust)", "proof")
arrow(16.2, 25.5, 20.0, 25.5)
arrow(37.2, 25.5, 41.0, 25.5, "spec")
arrow(59.2, 27.2, 63.0, 27.2, "body", dy=1.4)
arrow(63.0, 23.6, 59.2, 23.6, "errors", dy=-1.5)
arrow(79.2, 25.5, 83.0, 25.5, "proved", dy=1.6)

# bottom row: check and serve
box(63.5, 3, 15, 11, "Check", "rows = DuckDB's,\nfaster on all cores", "host")
box(83.5, 3, 16, 11, "Serve", "cached in DuckDB\nextension", "serve")
box(41.5, 3, 17, 11, "Rejected", "nothing ships", "input")
arrow(91.5, 19.6, 74.0, 14.6, rad=-0.15)
arrow(79.2, 8.5, 83.0, 8.5)
arrow(63.0, 8.5, 59.2, 8.5, "fails", dy=1.6)

for kind, label, y in (("host", "host, deterministic", 11.0), ("agent", "LLM", 7.2), ("proof", "proved / built from proof", 3.4)):
    ax.add_patch(FancyBboxPatch((1.0, y), 2.0, 2.0, boxstyle="round,pad=0.1,rounding_size=0.4", fc=FILL[kind], ec=EDGE[kind], lw=0.8))
    ax.text(4.2, y + 1.0, label, va="center", color=MUTE, fontsize=6.8)

fig.tight_layout(pad=0.2)
for ext in ("pdf", "svg", "png"):
    fig.savefig(OUT / f"pipeline.{ext}", dpi=300 if ext == "png" else None, bbox_inches="tight")
print("wrote", *(OUT / f"pipeline.{e}" for e in ("pdf", "svg", "png")))
