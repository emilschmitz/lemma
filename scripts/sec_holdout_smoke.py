#!/usr/bin/env python3
"""One-shot: parse + transpile all 6 SEC holdout queries."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from verus_transpiler import transpile_sql_to_verus
from verus_transpiler.parse_sql import UnsupportedContractError, parse_sql

ROOT = Path(__file__).resolve().parents[1]
QUERIES_PATH = ROOT / "holdout" / "gendb_sec_edgar" / "queries.sql"

SCHEMA: dict[str, dict[str, str]] = {
    "pre": {
        "stmt": "string",
        "rfile": "string",
        "adsh": "string",
        "line": "int",
        "tag": "string",
        "version": "string",
        "plabel": "string",
    },
    "num": {
        "adsh": "string",
        "tag": "string",
        "version": "string",
        "uom": "string",
        "value": "double",
        "ddate": "int",
    },
    "sub": {
        "adsh": "string",
        "name": "string",
        "cik": "int",
        "sic": "int",
        "fy": "int",
    },
    "tag": {
        "tag": "string",
        "version": "string",
        "tlabel": "string",
        "abstract": "int",
    },
}

REAL_SPEC = {"1", "2", "3", "4", "6", "24"}
UNSUPPORTED: set[str] = set()


def _fold_helpers(out: str) -> list[str]:
    names = (
        "multi_agg_helper",
        "method_spec_helper",
        "join_method_spec_helper",
        "join_sum_helper",
        "join_count_helper",
        "join_projection_helper",
        "join_anti_multi_agg_helper",
        "join_right_match_helper",
        "derived_m_helper",
    )
    chunks: list[str] = []
    for name in names:
        marker = f"pub open spec fn {name}"
        if marker not in out:
            continue
        start = out.index(marker)
        rest = out[start + 1 :]
        nxt = rest.find("\npub open spec fn ")
        chunk = out[start:] if nxt == -1 else out[start : start + 1 + nxt]
        chunks.append(chunk)
    return chunks


def _fold_helpers_have_no_arbitrary(out: str) -> bool:
    return all("arbitrary()" not in c for c in _fold_helpers(out))


def main() -> int:
    text = QUERIES_PATH.read_text()
    ok = fail = 0
    for m in re.finditer(
        r"-- Q(\d+):.*?\n(SELECT.*?;)",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        qnum, sql = m.group(1), m.group(2).strip()
        try:
            parse_sql(sql, SCHEMA)
            if qnum in UNSUPPORTED:
                try:
                    transpile_sql_to_verus(sql, SCHEMA)
                except UnsupportedContractError:
                    print(f"Q{qnum}: OK (expected UnsupportedContractError)")
                    ok += 1
                    continue
                raise RuntimeError("expected UnsupportedContractError")
            out = transpile_sql_to_verus(sql, SCHEMA)
            if "method_spec" not in out:
                raise RuntimeError("missing method_spec")
            if "unimplemented!" in out:
                raise RuntimeError("vacuous TRUSTED/unimplemented run_query")
            helpers = _fold_helpers(out)
            if not helpers:
                raise RuntimeError("missing recursive fold helper")
            if not _fold_helpers_have_no_arbitrary(out):
                raise RuntimeError("fake arbitrary() in MethodSpec fold helper")
            if qnum in REAL_SPEC and not any("decreases" in c for c in helpers):
                raise RuntimeError("missing decreases in real spec fold")
            print(f"Q{qnum}: OK")
            ok += 1
        except Exception as exc:
            print(f"Q{qnum}: FAIL {exc}")
            fail += 1
    print(f"\n{ok} OK, {fail} FAIL")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
