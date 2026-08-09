"""MIN/MAX in multi-aggregate GROUP BY on JOIN queries."""

from __future__ import annotations

import re

import pytest

from research_loop.assemble_runquery import build_runquery_agent_source
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.trusted_ret_bridge import get_bridge
from verus_transpiler import transpile_sql_to_verus

NUM_SCHEMA = {
    "adsh": "string",
    "tag": "string",
    "version": "string",
    "uom": "string",
    "value": "double",
    "ddate": "int",
}

SUB_SCHEMA = {
    "adsh": "string",
    "name": "string",
    "cik": "int",
    "sic": "int",
    "fy": "int",
}

MIN_MAX_JOIN_SQL = """SELECT s.sic, MIN(n.value) AS min_value, MAX(n.value) AS max_value
FROM num n JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'pure' AND s.fy = 2024
GROUP BY s.sic"""

Q9_LIKE_SQL = """SELECT s.sic, COUNT(DISTINCT s.cik) AS num_companies,
       COUNT(*) AS num_values,
       SUM(n.value) AS total_value,
       AVG(n.value) AS avg_value,
       MIN(n.value) AS min_value,
       MAX(n.value) AS max_value
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'pure' AND s.fy = 2024
      AND s.sic IS NOT NULL AND n.value IS NOT NULL AND n.value > 0
GROUP BY s.sic
HAVING COUNT(DISTINCT s.cik) >= 3"""


def _extract_fn(out: str, name: str) -> str:
    marker = f"pub open spec fn {name}("
    start = out.index(marker)
    rest = out[start + 1 :]
    nxt = rest.find("\npub open spec fn ")
    return out[start:] if nxt == -1 else out[start : start + 1 + nxt]


def _map_values_closure(out: str) -> str:
    m = re.search(r"map_values\(\|([^|]+)\|\s*(.+?)\)\)", out, re.DOTALL)
    assert m is not None, "expected map_values closure in method_spec"
    return m.group(0)


def _fold_helpers(out: str) -> list[str]:
    names = (
        "multi_agg_helper",
        "method_spec_helper",
        "join_method_spec_helper",
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


@pytest.mark.parametrize(
    "sql",
    [MIN_MAX_JOIN_SQL, Q9_LIKE_SQL],
    ids=["min_max_only", "q9_like"],
)
def test_multi_agg_join_min_max_transpile(sql: str) -> None:
    out = transpile_sql_to_verus(sql, {"num": NUM_SCHEMA, "sub": SUB_SCHEMA})
    assert "multi_agg_helper" in out
    assert "unimplemented!" not in out
    helpers = _fold_helpers(out)
    assert helpers
    assert all("arbitrary()" not in c for c in helpers)

    helper = _extract_fn(out, "multi_agg_helper")
    assert "decreases" in helper
    assert "u64::MAX" in helper
    assert re.search(r"if t\d+ < prev\.\d+", helper) or "if t0 < prev" in helper
    assert re.search(r"if t\d+ > prev\.\d+", helper) or "if t0 > prev" in helper

    spec = _extract_fn(out, "method_spec")
    closure = _map_values_closure(spec)
    assert "map_values(|v:" in closure


def test_multi_agg_join_min_max_resolve_ret_type_and_shell() -> None:
    out = transpile_sql_to_verus(MIN_MAX_JOIN_SQL, {"num": NUM_SCHEMA, "sub": SUB_SCHEMA})
    key = resolve_ret_type_from_method_spec(out)
    assert key == "map_u32__u64_u64"
    bridge = get_bridge(key)
    assert bridge is not None
    src = build_runquery_agent_source(ret_type=key)
    assert "HashMap<u32, (u64, u64)>" in src
    assert bridge.ensures in src


def test_q9_like_resolve_ret_type_and_shell() -> None:
    out = transpile_sql_to_verus(Q9_LIKE_SQL, {"num": NUM_SCHEMA, "sub": SUB_SCHEMA})
    key = resolve_ret_type_from_method_spec(out)
    assert key == "map_u32__u64_u64_u64_u64_u64_u64"
    bridge = get_bridge(key)
    assert bridge is not None
    src = build_runquery_agent_source(ret_type=key)
    assert "HashMap<u32, (u64, u64, u64, u64, u64, u64)>" in src
    assert bridge.ensures in src
