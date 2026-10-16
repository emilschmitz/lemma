"""Build opus_none_results.{md,json} and speedup_opus_none.{png,svg} from the Opus `none` container runs (2026-10-11 and 2026-10-16; read-only).

Cost: a session's `total_cost_usd` from its stream-json result event. A session killed at its wall limit has no result event; its cost is
estimated from the per-message usage in claude_raw.jsonl (input, cache write, cache read: exact) plus output tokens estimated from the
characters of its assistant content (text, thinking, tool input), with the token/char ratio range of the sessions that did finish. The
per-token prices are fitted from the finished sessions (the fit is exact to 1e-13).
"""
import json, os, re, statistics as st
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = "/home/emil/projects/lemma-db"
D = f"{ROOT}/research_loop/generated/container_runs"
OUT = os.path.dirname(os.path.abspath(__file__))
RUNS = ["tpch_q01", "tpch_q03", "tpch_q06", "tpch_q09", "tpch_q12", "tpch_q18", "ssb_q2_1", "ssb_q4_3"]
# the 19 queries of the frozen run; those not in RUNS are "tba"
ALL = {"SSB": ["Q1.1", "Q1.2", "Q1.3", "Q2.1", "Q2.3", "Q3.1", "Q3.2", "Q3.3", "Q3.4", "Q4.1", "Q4.2", "Q4.3"],
       "TPC-H": ["Q1", "Q3", "Q6", "Q9", "Q12", "Q14", "Q18"]}
K = ["input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"]


def sessions(path):
    out, cur = [], None
    for line in open(path):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = e.get("type")
        if t == "system" and e.get("subtype") == "init":
            cur = {"msgs": {}, "chars": 0, "result": None}
            out.append(cur)
        elif t == "assistant" and cur is not None:
            m, u = e["message"], e["message"].get("usage") or {}
            prev = cur["msgs"].get(m["id"], {})
            cur["msgs"][m["id"]] = {k: max(prev.get(k, 0), u.get(k, 0)) for k in K}
            for c in m.get("content", []):
                cur["chars"] += len(c.get("text") or "") + len(c.get("thinking") or "") + (len(json.dumps(c.get("input"))) if c.get("type") == "tool_use" else 0)
        elif t == "result" and cur is not None:
            cur["result"] = e
    return out


def name(stem):
    b, q = stem.split("_", 1)
    n = re.match(r"q(\d+)(?:_(\d+))?", q)
    return ("SSB" if b == "ssb" else "TPC-H"), f"Q{int(n[1])}" + (f".{n[2]}" if n[2] else "")


res, S = {}, {}
for stem in RUNS:
    res[stem] = json.loads([l for l in open(f"{D}/claude-opus-5-5_{stem}.log") if l.startswith("RESULT ")][-1][7:], strict=False)
    S[stem] = sessions(os.path.join(res[stem]["run_dir"], "workspace/logs/claude_raw.jsonl"))
done = [s for ss in S.values() for s in ss if s["result"]]
A = np.array([[s["result"]["usage"][k] for k in K] for s in done], float)
price, *_ = np.linalg.lstsq(A, np.array([s["result"]["total_cost_usd"] for s in done]), rcond=None)
ratio = [s["result"]["usage"]["output_tokens"] / s["chars"] for s in done]
rlo, rmid, rhi = min(ratio), st.median(ratio), max(ratio)

rows = []
for stem in RUNS:
    r, m = res[stem], json.load(open(os.path.join(res[stem]["run_dir"], "manifest.json")))
    bench, q = name(stem)
    o = r["official"]
    sub = open(os.path.join(r["run_dir"], "workspace/mcp_results/submitted.json")).read()
    cost, tok, killed = [0.0, 0.0, 0.0], dict.fromkeys(K, 0), 0
    for s in S[stem]:
        if s["result"]:
            c = s["result"]["total_cost_usd"]
            cost = [x + c for x in cost]
            for k in K:
                tok[k] += s["result"]["usage"][k]
        else:
            killed += 1
            pm = [sum(x[k] for x in s["msgs"].values()) for k in K]
            base = float(np.dot(pm[:3], price[:3]))
            cost = [x + base + s["chars"] * rr * price[3] for x, rr in zip(cost, (rlo, rmid, rhi))]
            for k in K[:3]:
                tok[k] += pm[K.index(k)]
            tok["output_tokens"] += int(s["chars"] * rmid)
    ours, duck = o["ours_median_us"], o["duck_median_us"]
    rows.append(dict(benchmark=bench, query=q, status=r["status"], proof=re.search(r"\d+ verified, \d+ errors", sub)[0],
                     ours_ms=round(ours / 1000, 2), duck_ms=round(duck / 1000, 2), speedup=round(duck / ours, 2),
                     sessions=len(m["sessions"]), agent_min=round(sum(x["agent_s"] for x in m["sessions"]) / 60, 1),
                     best_session_speedup=round(max(x["session_speedup"] or 0 for x in m["sessions"]), 2),
                     stop_reason=m["sessions"][-1].get("stop_reason"), killed_sessions=killed,
                     cost_usd=round(cost[1], 2), cost_usd_range=[round(cost[0], 2), round(cost[2], 2)], tokens=tok,
                     git_sha=m["git_sha"][:7], replicable=m.get("replicable"), started_at=m["started_at"], run_dir=os.path.relpath(r["run_dir"], ROOT)))

cfg = json.load(open(os.path.join(res[RUNS[0]]["run_dir"], "manifest.json")))["lemma_config"]
settings = {k: v["value"] for k, v in cfg.items()}
total = [round(sum(r["cost_usd_range"][0] for r in rows), 2), round(sum(r["cost_usd"] for r in rows), 2), round(sum(r["cost_usd_range"][1] for r in rows), 2)]
json.dump(dict(model="claude-opus-5-5", date="2026-10-11/12, 2026-10-16", shas=sorted({r["git_sha"] for r in rows}), price_per_mtok=dict(zip(K, (round(p * 1e6, 3) for p in price))),
               total_cost_usd=total, settings=settings, queries=rows), open(f"{OUT}/opus_none_results.json", "w"), indent=2)

md = ["| Benchmark | Query | Proof | Ours (ms) | DuckDB (ms) | Speedup | Sessions | Agent min | Cost (USD) |", "|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    c = f"{r['cost_usd']:.2f}" if not r["killed_sessions"] else f"~{r['cost_usd']:.2f} ({r['cost_usd_range'][0]:.2f}–{r['cost_usd_range'][1]:.2f})"
    md.append(f"| {r['benchmark']} | {r['query']} | {r['proof']} | {r['ours_ms']:.2f} | {r['duck_ms']:.2f} | {r['speedup']:.2f}x | {r['sessions']} | {r['agent_min']:.0f} | {c} |")
open(f"{OUT}/opus_none_results.md", "w").write("\n".join(md) + f"\n\nTotal cost about ${total[1]:.2f} (range {total[0]:.2f}–{total[2]:.2f}).\n")

got = {(r["benchmark"], r["query"]): r["speedup"] for r in rows}
fig, ax = plt.subplots(figsize=(7, 6.5))
ys, labels, y = [], [], 0
for b in ALL:
    for q in sorted(ALL[b], key=lambda q: got.get((b, q), -1)):
        sp = got.get((b, q))
        if sp is None:
            ax.text(0.05, y, "tba", va="center", fontsize=8, color="#8c8c8c", style="italic")
        else:
            ax.barh(y, sp, color="#1b6ca8", height=0.7)
            ax.text(sp + 0.06, y, f"{sp:.2f}x", va="center", fontsize=8)
        ys.append(y); labels.append(f"{b} {q}"); y += 1
    y += 1
ax.axvspan(0.9, 1.1, color="#d0d0d0", alpha=0.6, zorder=0)
ax.axvline(1.0, color="black", lw=1)
ax.set_yticks(ys); ax.set_yticklabels(labels, fontsize=9); ax.set_ylim(-1, y - 1)
ax.set_xlabel("Speedup vs all-core DuckDB (ratio of medians, higher is faster)")
ax.set_xlim(0, 6)
ax.set_title("Lemma (verified), Opus 5.5, no examples, SF1")
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
fig.tight_layout()
fig.savefig(f"{OUT}/speedup_opus_none.png", dpi=200); fig.savefig(f"{OUT}/speedup_opus_none.svg")
print(json.dumps(dict(total=total, price=[round(p * 1e6, 3) for p in price], ratio=[rlo, rmid, rhi])))
