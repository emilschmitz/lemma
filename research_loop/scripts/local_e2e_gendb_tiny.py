#!/usr/bin/env python3
"""Host e2e for every GenDB template (T1–T30) on tiny SEC DuckDB.

This is transpile → stub run_query → assemble → Verus verify → compile → pin.
It is **not** the Docker agent prove path. Agent-in-docker still needs
``local_e2e_tiny_docker.sh`` (and a docker install).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_loop.method_spec_ret_type import (
    parse_method_spec_params,
    parse_method_spec_return_type,
    resolve_ret_type_from_method_spec,
)
from research_loop.scripts.local_e2e_tiny_docker import DEFAULT_TINY_DB, LIBDUCKDB
from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema
from research_loop.trusted_ret_bridge import (
    bridge_from_method_spec_type,
    get_bridge,
)
from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.column_projection import project_multi_schema_for_query

_GEN = ROOT / "holdout/gendb_sec_edgar/generate_queries.py"
OUT_DIR = ROOT / "research_loop/generated/local_e2e_gendb_tiny"


def _load_templates():
    spec = importlib.util.spec_from_file_location("gendb_generate_queries", _GEN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate_templates()


def instantiate_gendb_queries() -> list[tuple[str, str]]:
    templates = _load_templates()
    if len(templates) != 30:
        raise RuntimeError(f"expected 30 GenDB templates, got {len(templates)}")
    out: list[tuple[str, str]] = []
    for tid in range(1, 31):
        random.seed(tid)
        sql = templates[tid - 1][0]().strip()
        out.append((f"T{tid:02d}", sql))
    return out


def _valid_fn(struct: str) -> str:
    if struct == "Cols":
        return "valid_cols"
    if struct.startswith("Cols_"):
        return f"valid_cols_{struct[5:]}"
    return f"valid_{struct}"


def external_body_stub_from_spec(spec_rs: str) -> str:
    """External-body run_query matching MethodSpec params (not an agent proof)."""
    params = parse_method_spec_params(spec_rs)
    ret_key = resolve_ret_type_from_method_spec(spec_rs)
    spec_ret = parse_method_spec_return_type(spec_rs)
    bridge = get_bridge(ret_key) or bridge_from_method_spec_type(spec_ret)
    sig = ", ".join(f"{n}: &{s}" for n, s in params)
    req = " && ".join(f"{_valid_fn(s)}({n})" for n, s in params)
    call = ", ".join(n for n, _ in params)
    ensures = bridge.ensures.rstrip().removesuffix(",")
    ensures = re.sub(r"method_spec\([^)]*\)", f"method_spec({call})", ensures)
    uses = ""
    if "HashMapWithView" in bridge.rust_ret:
        uses = "    use vstd::hash_map::HashMapWithView;\n"
    elif "StringHashMap" in bridge.rust_ret:
        uses = "    use vstd::hash_map::StringHashMap;\n"
    return (
        f"#[verifier::external_body]\n"
        f"pub exec fn run_query({sig}) -> (res: {bridge.rust_ret})\n"
        f"    requires {req},\n"
        f"    ensures {ensures},\n"
        f"{{\n{uses}    {bridge.default_stub}\n}}"
    )


def write_gendb_sql_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    for qid, sql in instantiate_gendb_queries():
        chunks.append(f"-- {qid}: GenDB template\n{sql.rstrip().rstrip(';')};\n")
    path.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    return path


def run_one_host(qid: str, sql: str, *, out_dir: Path) -> dict[str, Any]:
    from research_loop.harness import resolve_verus_bin, run_custom_sql_pipeline

    if resolve_verus_bin() is None:
        return {"qid": qid, "ok": False, "stage": "preflight", "error": "verus not found"}
    if not DEFAULT_TINY_DB.is_file():
        return {"qid": qid, "ok": False, "stage": "preflight", "error": "tiny duckdb missing"}
    if not LIBDUCKDB.is_file():
        return {"qid": qid, "ok": False, "stage": "preflight", "error": "libduckdb missing"}

    run_dir = out_dir / qid.lower()
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LEMMA_RUN_DIR"] = str(run_dir)
    os.environ["LEMMA_DUCKDB_PATH"] = str(DEFAULT_TINY_DB)
    os.environ["LEMMA_DUCKDB_LIB_DIR"] = str(LIBDUCKDB.parent)
    os.environ["ENABLE_VERUS_VERIFY"] = "1"
    os.environ["REQUIRE_PROOF"] = "1"
    os.environ["VERUS_VERIFY_TIMEOUT_SEC"] = os.environ.get("VERUS_VERIFY_TIMEOUT_SEC", "180")
    os.environ["COMPILE_TIMEOUT_SEC"] = os.environ.get("COMPILE_TIMEOUT_SEC", "180")

    catalog = load_sec_schema()
    projected = project_multi_schema_for_query(sql, catalog)
    spec_rs = transpile_sql_to_verus(sql, projected)
    body = external_body_stub_from_spec(spec_rs)
    t0 = time.perf_counter()
    res = run_custom_sql_pipeline(
        sql,
        catalog,
        run_query_body=body,
        skip_bench=False,
        workload="sec",
        duckdb_path=str(DEFAULT_TINY_DB),
        limit=500,
    )
    elapsed = round(time.perf_counter() - t0, 1)
    ok = (
        res.get("stage") not in {"assemble", "verify", "transpile", "parse"}
        and res.get("proof_verified") is True
        and int(res.get("latency_us", -1)) >= 0
    )
    rec = {
        "qid": qid,
        "ok": ok,
        "elapsed_s": elapsed,
        "stage": res.get("stage"),
        "proof_verified": res.get("proof_verified"),
        "latency_us": res.get("latency_us"),
        "error": (res.get("error") or res.get("verify_msg") or res.get("bench_error") or "")[:800],
        "sql_preview": " ".join(sql.split())[:180],
    }
    (run_dir / "result.json").write_text(json.dumps(rec, indent=2) + "\n")
    return rec


def _ensure_verus_path() -> None:
    home = Path(os.environ.get("HOME", "/home/emil"))
    extra = [
        str(home / "tools/verus"),
        str(home / "src/verus/source/target-verus/release"),
        str(home / ".cargo/bin"),
        str(home / ".local/bin"),
    ]
    os.environ["PATH"] = ":".join(extra + [os.environ.get("PATH", "")])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GenDB T1–T30 host e2e on tiny SEC")
    parser.add_argument("templates", nargs="*", help="T1 T16 … or omit for all 30")
    args = parser.parse_args(argv)
    _ensure_verus_path()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    queries = instantiate_gendb_queries()
    write_gendb_sql_file(OUT_DIR / "gendb_t1_t30.sql")
    wanted = {a.upper().replace("T", "").zfill(2) for a in args.templates}
    if wanted:
        queries = [(qid, sql) for qid, sql in queries if qid[1:] in wanted or qid in {f"T{w}" for w in wanted}]
        if not queries:
            print("no matching templates", file=sys.stderr)
            return 2

    results: list[dict[str, Any]] = []
    for qid, sql in queries:
        print(f"=== host e2e {qid} ===", flush=True)
        try:
            rec = run_one_host(qid, sql, out_dir=OUT_DIR)
        except Exception as exc:
            rec = {"qid": qid, "ok": False, "stage": "exception", "error": str(exc)[:800]}
        results.append(rec)
        print(
            f"{qid}: ok={rec.get('ok')} proof={rec.get('proof_verified')} "
            f"lat={rec.get('latency_us')} stage={rec.get('stage')} {rec.get('elapsed_s')}s",
            flush=True,
        )
        if rec.get("error") and not rec.get("ok"):
            print(f"  error: {rec['error'][:240]}", flush=True)

    summary = {
        "n": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "note": "host stub pipeline on tiny DuckDB; not Docker agent proofs",
        "results": results,
    }
    (OUT_DIR / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"DONE {summary['ok']}/{summary['n']} host e2e ok  logs={OUT_DIR}",
        flush=True,
    )
    return 0 if summary["ok"] == summary["n"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
