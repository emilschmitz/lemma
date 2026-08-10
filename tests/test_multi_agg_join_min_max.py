"""MIN/MAX in multi-aggregate GROUP BY on JOIN queries."""

from __future__ import annotations

import re

import pytest

from research_loop.assemble_runquery import build_runquery_agent_source
from research_loop.assemble_verified_program import prepare_agent_visible_spec
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.multi_agg_step_bridge import (
    multi_agg_step_trusted_rs,
    parse_multi_agg_layout,
)
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

JOIN_STRING_FILTER_SQL = """SELECT s.sic, COUNT(*) AS cnt, COUNT(DISTINCT n.adsh) AS n_adsh
FROM num n JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'pure' AND s.name = 'ACME'
GROUP BY s.sic"""


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


def test_q9_like_agg_step_apply_row_min_max_u64() -> None:
    """MIN/MAX apply_row must bind row params as u64, not int (matches inner state slots)."""
    out = transpile_sql_to_verus(Q9_LIKE_SQL, {"num": NUM_SCHEMA, "sub": SUB_SCHEMA})
    layout = parse_multi_agg_layout(out)
    assert layout is not None
    assert re.search(r"let t\d+ = row_u64_\d+;", layout.apply_body)
    assert not re.search(r"let t\d+ = row_u64_\d+ as int;", layout.apply_body)

    ret_type = resolve_ret_type_from_method_spec(out)
    trusted = multi_agg_step_trusted_rs(out, ret_type)
    assert "agg_step_apply_row_u32__u64_u64_u64_u64_u64_u64" in trusted
    apply_chunk = re.search(
        r"pub open spec fn agg_step_apply_row_u32__u64_u64_u64_u64_u64_u64[\s\S]*?^}",
        trusted,
        re.MULTILINE,
    )
    assert apply_chunk is not None
    body = apply_chunk.group(0)
    assert re.search(r"let t\d+ = row_u64_\d+;", body)
    assert not re.search(r"let t\d+ = row_u64_\d+ as int;", body)

    visible = prepare_agent_visible_spec(out, ret_type)
    assert "let t5 = row_u64_0;" in visible or "let t5 = row_u64_0;\n" in visible


def test_join_multi_agg_where_string_literal_seq_view() -> None:
    out = transpile_sql_to_verus(JOIN_STRING_FILTER_SQL, {"num": NUM_SCHEMA, "sub": SUB_SCHEMA})
    helpers = _fold_helpers(out)
    assert helpers
    helper = helpers[0]
    assert re.search(r'==\s*"pure"@', helper), helper
    assert re.search(r'==\s*"ACME"@', helper), helper
    assert not re.search(r'==\s*"pure"(?!@)', helper)
    assert not re.search(r'==\s*"ACME"(?!@)', helper)


def test_join_multi_agg_nested_loop_wrap_advances_outer() -> None:
    out = transpile_sql_to_verus(JOIN_STRING_FILTER_SQL, {"num": NUM_SCHEMA, "sub": SUB_SCHEMA})
    helper = _extract_fn(out, "multi_agg_helper")
    assert re.search(
        r"if i1 < sub\.n \{[\s\S]*?\} else \{\s*multi_agg_helper\(num, sub, i0 \+ 1, 0\)",
        helper,
    ), helper
    assert re.search(
        r"if i0 < num\.n \{[\s\S]*?\} else \{\s*Map::empty\(\)",
        helper,
    ), helper
