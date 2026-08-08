#!/usr/bin/env python3
"""Grouped bar chart: SSB Q1–Q3 @ 1.5M + TPC-H Q1/Q6 @ 6M, single-thread engines."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCALING = ROOT / "data" / "benchmarks" / "scaling_results.json"
TPCH = ROOT / "data" / "benchmarks" / "tpch_sf1_results.json"
ENV = ROOT / "data" / "benchmarks" / "benchmark_environment.json"
OUT = ROOT / "scratch" / "plots" / "benchmark_overview.png"

SSB_ROWS = 1_500_000
SSB_QUERIES = ["1", "2", "3"]
TPCH_QUERIES = ["Q1", "Q6"]

ENGINES_SSB = [
    ("postgres_1t", "PostgreSQL"),
    ("duckdb_1t", "DuckDB"),
    ("bare_rust", "Bare Rust"),
    ("verified_rust", "Verified"),
]
ENGINES_TPCH = [
    ("duckdb_1t", "DuckDB"),
    ("bare_rust", "Bare Rust"),
    ("verified_rust", "Verified"),
]


def _fmt_rows(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n // 1000}k"
    return str(n)


def load_env_line() -> str:
    if not ENV.is_file():
        return ""
    env = json.loads(ENV.read_text())
    ram = env.get("ram_gib", "?")
    threads = env.get("cpu_threads", "?")
    cpu = env.get("cpu", "unknown CPU")
    os_name = "WSL2" if "WSL" in env.get("os", "") else env.get("os", "")
    return f"{cpu} · {threads} threads · {ram} GiB RAM · {os_name}"


def load_rows() -> list[dict]:
    scaling = json.loads(SCALING.read_text())
    block = scaling["sizes"][str(SSB_ROWS)]
    rows: list[dict] = []

    for qkey in SSB_QUERIES:
        duck = block["duckdb"]["hot_us"]["duckdb_1t"][qkey]
        pg = block["postgres"]["hot_us"]["postgres_1t"][qkey]
        bare = block["queries"][qkey]["bare_rust"]["hot_us"]
        ver = block["queries"][qkey]["verified_rust"]["hot_us"]
        xlabel = f"SSB Q{qkey}\n{_fmt_rows(SSB_ROWS)}"
        for engine_key, engine_label in ENGINES_SSB:
            if engine_key == "postgres_1t":
                us = pg
            elif engine_key == "duckdb_1t":
                us = duck
            elif engine_key == "bare_rust":
                us = bare
            else:
                us = ver
            rows.append({"xlabel": xlabel, "engine": engine_label, "ms": us / 1000.0})

    if TPCH.is_file():
        tpch = json.loads(TPCH.read_text())
        nrows = int(tpch["meta"]["row_count"])
        for qkey in TPCH_QUERIES:
            q = tpch["queries"][qkey]
            duck = int(q["duckdb_1t_us"])
            bare = int(q["bare_rust_us"])
            ver = int(q["verified_rust"]["hot_us"])
            xlabel = f"TPC-H {qkey}\n{_fmt_rows(nrows)}"
            values = {"duckdb_1t": duck, "bare_rust": bare, "verified_rust": ver}
            for engine_key, engine_label in ENGINES_TPCH:
                rows.append(
                    {
                        "xlabel": xlabel,
                        "engine": engine_label,
                        "ms": values[engine_key] / 1000.0,
                    }
                )

    return rows


def main() -> None:
    import matplotlib.pyplot as plt
    import pandas as pd
    import seaborn as sns

    df = pd.DataFrame(load_rows())
    OUT.parent.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid", context="talk", font_scale=0.85)
    palette = {
        "PostgreSQL": "#4C72B0",
        "DuckDB": "#DD8452",
        "Bare Rust": "#55A868",
        "Verified": "#C44E52",
    }

    x_order = list(dict.fromkeys(df["xlabel"]))
    fig, ax = plt.subplots(figsize=(12, 5.5))
    sns.barplot(
        data=df,
        x="xlabel",
        y="ms",
        hue="engine",
        order=x_order,
        hue_order=[e[1] for e in ENGINES_SSB],
        palette=palette,
        ax=ax,
    )
    ax.set_yscale("log")
    ax.set_xlabel("Query (row count under label)")
    ax.set_ylabel("Hot-loop latency (ms, log scale)")
    ax.set_title("Single-thread hot-loop latency by engine")
    ax.legend(title="Engine", loc="upper left", frameon=True, ncol=2)

    env_line = load_env_line()
    metric = "hot-loop latency — median timed query execution; table load excluded"
    fig.text(
        0.5,
        0.01,
        f"Execution environment: {env_line}   |   Metric: {metric}",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#444444",
        wrap=True,
    )

    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT, dpi=160, bbox_inches="tight")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
