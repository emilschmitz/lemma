#!/usr/bin/env python3
"""GenDB-style grouped bar chart for README: 5 SSB queries @ 1.5M rows, single-thread engines."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCALING = ROOT / "data" / "benchmarks" / "scaling_results.json"
OUT = ROOT / "plots" / "benchmark_overview.png"

ROWS = 1_500_000
QUERIES = [
    ("Q2", "2", "good"),
    ("Q3", "3", "good"),
    ("Q5", "5", "good"),
    ("Q1", "1", "marginal"),
    ("Q4", "4", "marginal"),
]
ENGINES = [
    ("postgres_1t", "PostgreSQL"),
    ("duckdb_1t", "DuckDB"),
    ("bare_rust", "Bare Rust"),
    ("verified_rust", "Verified"),
]


def load_ms() -> list[dict]:
    data = json.loads(SCALING.read_text())
    block = data["sizes"][str(ROWS)]
    rows: list[dict] = []
    for qlabel, qkey, tier in QUERIES:
        duck = block["duckdb"]["hot_us"]["duckdb_1t"][qkey]
        pg = block["postgres"]["hot_us"]["postgres_1t"][qkey]
        bare = block["queries"][qkey]["bare_rust"]["hot_us"]
        ver = block["queries"][qkey]["verified_rust"]["hot_us"]
        for engine_key, engine_label in ENGINES:
            if engine_key == "postgres_1t":
                us = pg
            elif engine_key == "duckdb_1t":
                us = duck
            elif engine_key == "bare_rust":
                us = bare
            else:
                us = ver
            rows.append(
                {
                    "query": qlabel,
                    "tier": tier,
                    "engine": engine_label,
                    "ms": us / 1000.0,
                }
            )
    return rows


def main() -> None:
    import matplotlib.pyplot as plt
    import pandas as pd
    import seaborn as sns

    df = pd.DataFrame(load_ms())
    OUT.parent.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid", context="talk", font_scale=0.85)
    palette = {
        "PostgreSQL": "#4C72B0",
        "DuckDB": "#DD8452",
        "Bare Rust": "#55A868",
        "Verified": "#C44E52",
    }

    fig, ax = plt.subplots(figsize=(11, 5.5))
    sns.barplot(
        data=df,
        x="query",
        y="ms",
        hue="engine",
        order=[q[0] for q in QUERIES],
        hue_order=[e[1] for e in ENGINES],
        palette=palette,
        ax=ax,
    )
    ax.set_yscale("log")
    ax.set_xlabel("SSB flat query (1.5M rows)")
    ax.set_ylabel("Hot-loop latency (ms, log scale)")
    ax.set_title("Single-thread hot-loop latency by engine")
    ax.legend(title="Engine", loc="upper left", frameon=True)

    for i, (qlabel, _qkey, tier) in enumerate(QUERIES):
        color = "#2ca02c" if tier == "good" else "#ff7f0e"
        ax.text(
            i,
            ax.get_ylim()[1] * 0.55,
            "✓" if tier == "good" else "~",
            ha="center",
            va="bottom",
            fontsize=14,
            color=color,
            fontweight="bold",
        )

    fig.tight_layout()
    fig.savefig(OUT, dpi=160, bbox_inches="tight")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
