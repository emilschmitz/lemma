#!/usr/bin/env python3
"""Build the local Docker e2e SQL suite: GenDB T1–T30 + historically failed queries.

Tiny SEC DuckDB, product path (agent in Docker). Not a stub host run.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "research_loop/generated/local_e2e_gendb_docker"
SUITE_SQL = OUT_DIR / "suite.sql"
SUITE_MANIFEST = OUT_DIR / "suite_manifest.json"

R23_RESULTS = (
    ROOT / "holdout/gendb_sec_edgar/results/r23rocket_gcp_20260908/results.partial.json"
)
R23_SQL = ROOT / "holdout/gendb_sec_edgar/results/r23rocket_gcp_20260908/queries_resample.sql"
R17_CLASSIFY = ROOT / "holdout/gendb_sec_edgar/results/r17_gcp_20260907/failure_classify.json"
R15_SQL = ROOT / "holdout/gendb_sec_edgar/queries_resample_r15.sql"
PAPER_SQL = ROOT / "holdout/gendb_sec_edgar/queries.sql"
PAPER_FAILED_QIDS = ("Q2", "Q3", "Q4", "Q6", "Q24")


def _norm(sql: str) -> str:
    return " ".join(sql.split()).rstrip(";").lower()


def _parse_qn(path: Path) -> dict[str, str]:
    from research_loop.scripts.gendb_published_one_run import parse_queries

    return parse_queries(path)


def failed_r23_qids(results_path: Path = R23_RESULTS) -> list[str]:
    if not results_path.is_file():
        return []
    data = json.loads(results_path.read_text(encoding="utf-8"))
    out: list[str] = []
    for rec in data.get("results") or []:
        if rec.get("lemma_ok") is True:
            continue
        qid = rec.get("qid")
        if isinstance(qid, str) and qid.startswith("Q"):
            out.append(qid)
    return out


def failed_r17_qids(classify_path: Path = R17_CLASSIFY) -> list[str]:
    if not classify_path.is_file():
        return []
    data = json.loads(classify_path.read_text(encoding="utf-8"))
    out: list[str] = []
    for rec in data.get("rows") or []:
        if rec.get("last_status") == "SUCCESS":
            continue
        qid = rec.get("qid")
        if isinstance(qid, str) and qid.startswith("Q"):
            out.append(qid)
    return out


def build_suite_entries() -> list[dict[str, str]]:
    from research_loop.scripts.local_e2e_gendb_tiny import instantiate_gendb_queries

    seen: set[str] = set()
    entries: list[dict[str, str]] = []

    def add(source: str, sql: str) -> None:
        key = _norm(sql)
        if not key or key in seen:
            return
        seen.add(key)
        qid = f"Q{len(entries) + 1}"
        entries.append({"qid": qid, "source": source, "sql": sql.strip().rstrip(";")})

    for tid, sql in instantiate_gendb_queries():
        add(f"gendb-{tid}", sql)

    r23 = _parse_qn(R23_SQL) if R23_SQL.is_file() else {}
    for qid in failed_r23_qids():
        if qid in r23:
            add(f"r23rocket-failed-{qid}", r23[qid])

    r15 = _parse_qn(R15_SQL) if R15_SQL.is_file() else {}
    for qid in failed_r17_qids():
        if qid in r15:
            add(f"r17-failed-{qid}", r15[qid])

    paper = _parse_qn(PAPER_SQL) if PAPER_SQL.is_file() else {}
    for qid in PAPER_FAILED_QIDS:
        if qid in paper:
            add(f"paper-{qid}", paper[qid])

    return entries


def write_suite_sql(path: Path = SUITE_SQL) -> Path:
    entries = build_suite_entries()
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = [
        f"-- {e['qid']}: {e['source']}\n{e['sql']};\n" for e in entries
    ]
    path.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    SUITE_MANIFEST.write_text(
        json.dumps(
            {
                "n": len(entries),
                "n_gendb": sum(1 for e in entries if e["source"].startswith("gendb-")),
                "entries": [{"qid": e["qid"], "source": e["source"]} for e in entries],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    path = write_suite_sql()
    data = json.loads(SUITE_MANIFEST.read_text(encoding="utf-8"))
    print(f"wrote {path} n={data['n']} gendb={data['n_gendb']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
