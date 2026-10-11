"""Read-only live dashboard of container runs: `uv run python research_loop/scripts/dashboard.py [--port 8765]`.

Reads research_loop/runs/*/ (manifest.json, workspace/mcp_results/runs/*.json, submitted.json, logs/agent_stream.jsonl)
and research_loop/generated/container_runs/*.log RESULT lines. Writes nothing. The page refreshes every 10 s.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "research_loop" / "runs"
LOGS = ROOT / "research_loop" / "generated" / "container_runs"
VERIFIED = re.compile(r"(\d+) verified, (\d+) errors")


def _json(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _results() -> dict[str, dict]:
    out = {}
    for log in LOGS.glob("*.log"):
        for line in log.read_text(errors="replace").splitlines():
            if line.startswith("RESULT "):
                d = json.loads(line[7:])
                out[d.get("run_dir", "")] = {"log": log.name, **d}
    return out


def _last_says(stream: Path, n: int = 2) -> list[str]:
    said = []
    try:
        for line in stream.read_text(errors="replace").splitlines():
            if not line.startswith("{"):
                continue
            e = json.loads(line)
            if e.get("type") == "assistant":
                for c in e.get("message", {}).get("content") or []:
                    if c.get("type") == "text" and c.get("text", "").strip():
                        said.append(c["text"].strip())
    except (OSError, ValueError):
        pass
    return said[-n:]


def _run_row(run: Path, results: dict) -> dict:
    man = _json(run / "manifest.json")
    ws = run / "workspace"
    checks = []
    for f in sorted((ws / "mcp_results" / "runs").glob("*.json")):
        m = _json(f).get("metrics", {})
        v = VERIFIED.search(str(m.get("compiler_error", "")))
        checks.append({
            "t": f.stem[9:15],
            "status": m.get("status", "?"),
            "verified": v.group(0) if v else "",
            "speedup": m.get("speedup"),
            "partial": _json(f).get("partial", False),
        })
    proved = [c for c in checks if c["status"] == "SUCCESS" or (c["verified"].endswith(" 0 errors") and c["speedup"])]
    best = max((c["speedup"] for c in proved if c["speedup"]), default=None)
    sub = _json(ws / "mcp_results" / "submitted.json")
    sub_x = (sub.get("metrics") or {}).get("speedup")
    res = results.get(str(run), {})
    return {
        "run": run.name,
        "sql": (man.get("sql") or "")[:160],
        "model": man.get("agent_model", ""),
        "started": man.get("started_at", ""),
        "age_min": (time.time() - run.stat().st_mtime) / 60,
        "checks": checks,
        "submitted": (ws / "mcp_results" / "submitted.json").exists(),
        "result": res,
        "says": _last_says(ws / "logs" / "agent_stream.jsonl"),
        "sessions": man.get("sessions") or [],
        "best": best,
        "submitted_x": sub_x,
    }


def _system() -> str:
    try:
        mem = subprocess.run(["free", "-m"], capture_output=True, text=True).stdout.splitlines()[1].split()
        avail = f"{int(mem[-1]) / 1024:.1f} GB available"
    except (OSError, IndexError, ValueError):
        avail = "?"
    busy = subprocess.run(["pgrep", "-fa", "[c]ontainer_batch.py"], capture_output=True, text=True).stdout.strip()
    return f"memory: {avail} | container batch: {'running' if busy else 'idle'}"


def page(limit: int) -> str:
    results = _results()
    runs = sorted((p for p in RUNS.glob("2026*") if p.is_dir()), key=lambda p: p.name, reverse=True)[:limit]
    rows = []
    for run in runs:
        r = _run_row(run, results)
        res = r["result"]
        if res:
            x = (res.get("duck_us") or 0) / res["latency_us"] if (res.get("latency_us") or -1) > 0 else None
            state = f"<b class={'ok' if res.get('status') == 'SUCCESS' else 'bad'}>{html.escape(str(res.get('status')))}</b>"
            state += f" {x:.2f}x" if x else f" <small>{html.escape(str(res.get('error') or '')[:90])}</small>"
        else:
            state = "<b class=live>running</b>" if r["age_min"] < 30 else "<span class=dim>no RESULT</span>"
        checks = " ".join(
            f"<span class='chk {'ok' if c['status'] == 'SUCCESS' else ('part' if c['partial'] else 'bad')}' "
            f"title='{c['t']} {html.escape(c['status'])} {c['verified']}'>"
            f"{c['verified'].split(' verified')[0] if c['verified'] else '·'}"
            f"{'/' + c['verified'].split(', ')[1].split()[0] if c['verified'] else ''}"
            f"{(' ' + format(c['speedup'], '.2f') + 'x') if c['speedup'] else ''}</span>"
            for c in r["checks"])
        says = "<br>".join(html.escape(s[:300]) for s in r["says"])
        best = (f"best proved {r['best']:.2f}x" if r["best"] else "no proved run yet")
        best += f"<br>submitted {r['submitted_x']:.2f}x" if r["submitted_x"] else ""
        rows.append(
            f"<tr><td><a href='/run/{html.escape(r['run'])}'><code>{html.escape(r['run'])}</code></a><br><small>{html.escape(r['model'])}</small></td>"
            f"<td><small>{html.escape(r['sql'])}</small></td><td>{state}{' · submitted' if r['submitted'] else ''}</td><td><small>{best}</small></td>"
            f"<td>{checks}</td><td><small>{says}</small></td></tr>")
    return f"""<!doctype html><html><head><meta charset=utf-8><meta http-equiv=refresh content=10>
<meta name=viewport content="width=device-width, initial-scale=1"><title>Lemma runs</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--dim:#888;--ok:#1a7f37;--bad:#c62828;--live:#1565c0;--line:#e5e5e5}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16181c;--fg:#e8e8e8;--dim:#888;--ok:#4caf50;--bad:#ef5350;--live:#64b5f6;--line:#2c2f36}}}}
body{{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;margin:16px}}
table{{border-collapse:collapse;width:100%}} td{{border-top:1px solid var(--line);padding:6px;vertical-align:top}}
.ok{{color:var(--ok)}} .bad{{color:var(--bad)}} .live{{color:var(--live)}} .dim{{color:var(--dim)}}
.chk{{display:inline-block;border:1px solid var(--line);border-radius:4px;padding:0 4px;margin:1px;font-size:12px}}
.chk.ok{{border-color:var(--ok)}} .chk.bad{{border-color:var(--bad)}} .chk.part{{border-style:dashed}}
</style></head><body><h3>Lemma container runs</h3><p class=dim>{html.escape(_system())} · refreshes every 10 s · newest first</p>
<table><tr><th>run</th><th>query</th><th>result</th><th>best so far</th><th>verify checks (verified/errors, speedup)</th><th>agent's last words</th></tr>
{''.join(rows)}</table></body></html>"""


def trace_page(name: str) -> str:
    run = RUNS / name
    if not run.is_dir() or "/" in name:
        return "<p>no such run</p>"
    ws = run / "workspace"
    items = []
    stream = ws / "logs" / "agent_stream.jsonl"
    try:
        lines = stream.read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "system" and e.get("subtype") == "init":
            items.append("<h4>session start</h4>")
        elif e.get("type") == "assistant":
            for c in e.get("message", {}).get("content") or []:
                if c.get("type") == "text" and c.get("text", "").strip():
                    items.append(f"<div class=say>{html.escape(c['text'])}</div>")
        elif e.get("type") == "tool_call" and e.get("subtype") == "started":
            items.append(f"<pre class=tool>{html.escape(json.dumps(e.get('tool_call'))[:1500])}</pre>")
    checks = []
    for f in sorted((ws / "mcp_results" / "runs").glob("*.json")):
        d = _json(f)
        m = d.get("metrics", {})
        checks.append(f"<tr><td><code>{f.stem}</code>{' (partial)' if d.get('partial') else ''}</td><td>{html.escape(str(m.get('status')))}</td>"
                      f"<td>{'' if m.get('speedup') is None else format(m['speedup'], '.2f') + 'x'}</td>"
                      f"<td><pre class=err>{html.escape(str(m.get('compiler_error') or '')[:2500])}</pre></td></tr>")
    sub = _json(ws / "mcp_results" / "submitted.json")
    prof = run / "data_profile.md"
    body = (f"<p><a href='/'>back</a></p><h3>{html.escape(name)}</h3>"
            f"<p><b>submitted:</b> {html.escape(str(sub.get('run_id', 'nothing')))} "
            f"{'' if not (sub.get('metrics') or {}).get('speedup') else format(sub['metrics']['speedup'], '.2f') + 'x'}</p>"
            f"<h4>verify checks</h4><table>{''.join(checks)}</table>"
            f"<h4>agent conversation (text + tool calls)</h4>{''.join(items)}"
            + (f"<h4>data profile</h4><pre>{html.escape(prof.read_text())}</pre>" if prof.exists() else ""))
    return f"""<!doctype html><html><head><meta charset=utf-8><meta http-equiv=refresh content=15><title>{html.escape(name)}</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--line:#e5e5e5;--box:#f5f5f7}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16181c;--fg:#e8e8e8;--line:#2c2f36;--box:#202329}}}}
body{{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;margin:16px}} a{{color:inherit}}
.say{{background:var(--box);padding:8px;margin:6px 0;border-radius:6px;white-space:pre-wrap}}
pre{{white-space:pre-wrap;word-break:break-word;font-size:12px}} .tool{{border-left:3px solid var(--line);padding-left:8px}}
td{{border-top:1px solid var(--line);padding:4px;vertical-align:top}}</style></head><body>{body}</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = (trace_page(self.path[5:]) if self.path.startswith("/run/") else page(args.limit)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a) -> None:
            pass

    ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()


if __name__ == "__main__":
    main()
