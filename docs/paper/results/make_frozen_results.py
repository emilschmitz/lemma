"""Build frozen_results.{md,json} and speedup.{png,svg} from the container RESULT logs (read-only)."""
import glob, json, os, re, statistics as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

D = "/home/emil/projects/lemma-db/.claude/worktrees/agent-a7263fc262d297db2/research_loop/generated/container_runs"
OUT = os.path.dirname(os.path.abspath(__file__))
TABLES = {"SSB": ["lineorder", "date", "part", "supplier", "customer"],
          "TPC-H": ["lineitem", "orders", "customer", "part", "partsupp", "supplier", "nation", "region"]}
OWN = {"SSB Q3.1", "SSB Q4.1", "SSB Q4.2", "TPC-H Q1", "TPC-H Q12", "TPC-H Q14"}
SAME = {"TPC-H Q3", "TPC-H Q6"}
rows = []
for f in sorted(glob.glob(f"{D}/sonnet_*.log")):
    r = json.loads([l for l in open(f) if l.startswith("RESULT ")][-1][7:])
    b = os.path.basename(f)
    bench = "SSB" if "_ssb_" in b else "TPC-H"
    n = re.search(r"_q(\d+)(?:_(\d+))?\.log", b)
    q = f"Q{int(n[1])}" + (f".{n[2]}" if n[2] else "")
    name = f"{bench} {q}"
    o = r["official"]
    sub = open(os.path.join(r["run_dir"], "workspace/mcp_results/submitted.json")).read()
    proof = re.search(r"\d+ verified, \d+ errors", sub)[0]
    sql = r["sql"].lower()
    # whole-word table match in the FROM clause region (after 'from')
    frm = re.split(r"\bfrom\b", sql, maxsplit=1)[1]
    tabs = [t for t in TABLES[bench] if re.search(rf"\b{t}\b", frm)]
    ex = "own solution" if name in OWN else "same shape" if name in SAME else "none"
    ours, duck = o["ours_median_us"], o["duck_median_us"]
    rows.append(dict(benchmark=bench, query=name, tables=tabs, proof=proof, status=r["status"],
                     ours_ms=round(ours / 1000, 3), duck_ms=round(duck / 1000, 3),
                     speedup=round(duck / ours, 2), example=ex, inconclusive_pm10=abs(duck / ours - 1) <= 0.10))
def key(r): return (r["benchmark"], -r["speedup"])
rows.sort(key=key)
med = lambda xs: round(st.median(xs), 2)
summ = {b: med([r["speedup"] for r in rows if r["benchmark"] == b]) for b in TABLES}
summ.update({e: med([r["speedup"] for r in rows if r["example"] == e]) for e in ("own solution", "same shape", "none")})
summ["all"] = med([r["speedup"] for r in rows])
json.dump(dict(sha="75f4303", settings=dict(agent="Sonnet 5.5", limit_min=25, duckdb="1.5.4", threads=8, memory_limit="8GB",
         rounds="median of 5 interleaved rounds", join_chain=1, dict_strings=True),
         median_speedup=summ, queries=rows), open(f"{OUT}/frozen_results.json", "w"), indent=2)

md = ["# Lemma frozen run: results vs DuckDB", "",
 "Frozen at commit 75f4303. Agent: Claude Sonnet 5.5 in the Docker container, 25 minute limit, dictionary-encoded strings, "
 "`LEMMA_JOIN_CHAIN=1`. Baseline: DuckDB 1.5.4, all 8 threads, `memory_limit` 8GB. Each verdict is the median of 5 interleaved "
 "rounds (ours and DuckDB alternate order); speedup is the ratio of the two medians (DuckDB / ours). Data are SF1 (SSB, TPC-H) on a "
 "4-core/8-thread 14 GB laptop, so the ratios are not comparable to GenDB's absolute times. Per "
 "`research_loop/menus/official_measure_ADVERSARY_VERDICT.md`, results within +-10% of 1.0x are inconclusive; none of the 19 "
 "queries falls in that band (smallest is 1.16x), but the small ratios (1.16x to 1.3x) sit close to it. "
 "Example column: *own* = the query's own solution was mounted as a worked example; *same shape* = a solution to a same-shape query "
 "was mounted; *none* = no example of its own.", ""]
for b in TABLES:
    md += [f"## {b} SF1", "", "| Query | Tables joined | Proof | Ours (ms) | DuckDB (ms) | Speedup | Example |", "|---|---|---|---|---|---|---|"]
    for r in [r for r in rows if r["benchmark"] == b]:
        md.append(f"| {r['query'].split(' ')[1]} | {', '.join(r['tables'])} | {r['proof']} | {r['ours_ms']:.2f} | {r['duck_ms']:.2f} | {r['speedup']:.2f}x | {r['example']} |")
    md += ["", f"Median speedup: {summ[b]:.2f}x", ""]
md += ["## Not run", "",
 "- SSB Q2.2: the transpiler refuses BETWEEN on strings.",
 "- TPC-H Q2, Q4, Q5, Q7, Q10, Q16, Q19, Q21: not attempted in this run (these transpile per docs/tpch_transpiler_plan.md, 15 of 22 transpile).",
 "- TPC-H Q8, Q11, Q13, Q15, Q17, Q20, Q22: not attempted; the transpiler refuses them (docs/tpch_transpiler_plan.md).", "",
 "Median speedup by example class: " + ", ".join(f"{e} {summ[e]:.2f}x" for e in ("own solution", "same shape", "none")) + f". All 19: {summ['all']:.2f}x.", ""]
open(f"{OUT}/frozen_results.md", "w").write("\n".join(md))

col = {"own solution": "#1b6ca8", "same shape": "#e08a1e", "none": "#8c8c8c"}
fig, ax = plt.subplots(figsize=(8, 8))
ys, labels, y = [], [], 0
for b in TABLES:
    br = sorted([r for r in rows if r["benchmark"] == b], key=lambda r: r["speedup"])
    for r in br:
        ax.barh(y, r["speedup"], color=col[r["example"]], height=0.7)
        ax.text(r["speedup"] + 0.04, y, f"{r['speedup']:.2f}x", va="center", fontsize=8)
        ys.append(y); labels.append(r["query"]); y += 1
    y += 1
ax.axvspan(0.9, 1.1, color="#d0d0d0", alpha=0.6, zorder=0)
ax.axvline(1.0, color="black", lw=1)
ax.set_yticks(ys); ax.set_yticklabels(labels, fontsize=9)
ax.set_xlabel("Speedup vs DuckDB (ratio of medians, higher is faster)")
ax.set_xlim(0, 3.8)
ax.set_title("Lemma (verified) vs DuckDB, SF1, 19 queries")
ax.legend(handles=[Patch(color=col[k], label=k) for k in col] + [Patch(color="#d0d0d0", label="+-10% (inconclusive)")],
          title="Example", loc="lower right", fontsize=8)
for s in ("top", "right"): ax.spines[s].set_visible(False)
fig.tight_layout()
fig.savefig(f"{OUT}/speedup.png", dpi=200); fig.savefig(f"{OUT}/speedup.svg")
print(json.dumps(summ))
