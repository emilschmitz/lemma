"""Unit tests for multi-aggregate MethodSpec emission (_emit_multi_agg_spec)."""

from __future__ import annotations

import re

from verus_transpiler import transpile_sql_to_verus

# Minimal schemas (test fixtures only — not engine hardcoding).
PRE_SCHEMA = {
    "stmt": "string",
    "rfile": "string",
    "adsh": "string",
    "line": "int",
}

NUM_SCHEMA = {
    "tag": "string",
    "value": "double",
}

Q1_LIKE_SQL = """SELECT stmt, rfile, COUNT(*) AS cnt,
       COUNT(DISTINCT adsh) AS num_filings,
       AVG(line) AS avg_line_num
FROM pre
WHERE stmt IS NOT NULL
GROUP BY stmt, rfile"""

COUNT_SUM_SQL = "SELECT tag, COUNT(*) AS c, SUM(value) AS s FROM num GROUP BY tag"

COUNT_AVG_SQL = "SELECT tag, COUNT(*) AS c, AVG(value) AS avg_v FROM num GROUP BY tag"

BROKEN_PLACEHOLDERS = (
    "{prev}",
    "{prev_sum}",
    "{prev_cnt}",
    "__PREV__",
    "__PREV_SUM__",
    "__PREV_CNT__",
)

FREE_STATE_NAMES = tuple(f"s{i}" for i in range(8))


def _extract_fn(out: str, name: str) -> str:
    marker = f"pub open spec fn {name}("
    start = out.index(marker)
    rest = out[start + 1 :]
    nxt = rest.find("\npub open spec fn ")
    return out[start:] if nxt == -1 else out[start : start + 1 + nxt]


def _extract_multi_agg_fold_helper(out: str) -> str:
    for name in ("method_spec_helper", "multi_agg_helper"):
        if f"pub open spec fn {name}(" in out:
            return _extract_fn(out, name)
    raise AssertionError("expected multi-agg fold helper in transpile output")


def _map_values_closure(out: str) -> str:
    m = re.search(r"map_values\(\|([^|]+)\|\s*(.+?)\)\)", out, re.DOTALL)
    assert m is not None, "expected map_values closure in method_spec"
    return m.group(0)


def _assert_no_placeholders(text: str) -> None:
    for p in BROKEN_PLACEHOLDERS:
        assert p not in text, f"leftover placeholder {p!r}"


def _assert_no_free_state_in_closure(closure: str, bind: str = "v") -> None:
    """Projection closure must read folded state via `v` / `v.i`, not bare s0..s7."""
    inner = closure.split("|", 2)[-1]  # after |bind|
    for name in FREE_STATE_NAMES:
        assert not re.search(rf"(?<![.\w]){name}(?![.\w])", inner), (
            f"free aggregate state name {name!r} in map_values closure"
        )
    assert bind in closure
    if "." in inner:
        assert re.search(rf"{bind}\.\d+", inner), (
            f"expected {bind}.N projection in map_values closure"
        )


def test_q1_like_multi_agg_emission() -> None:
    out = transpile_sql_to_verus(Q1_LIKE_SQL, {"pre": PRE_SCHEMA})

    helper = _extract_multi_agg_fold_helper(out)
    spec = _extract_fn(out, "method_spec")

    assert "decreases" in helper
    assert "arbitrary()" not in helper
    assert "arbitrary()" not in spec
    _assert_no_placeholders(out)

    closure = _map_values_closure(spec)
    assert "map_values(|v|" in closure
    _assert_no_free_state_in_closure(closure)

    # AVG leg projects sum/count slots (v.2 / v.3) inside the closure.
    assert re.search(r"v\.\d+", closure)
    assert "v.1.dom().len()" in closure or "v.1" in closure

    # Helper fold binds prior state via `prev` tuple projection, not placeholders.
    assert "let prev = if tail.contains_key(key)" in helper
    assert re.search(r"prev\.\d+", helper), "multi-state helper must use prev.N"
    assert "let s0 = (prev.0" in helper or "let s0 = (prev " in helper


def test_count_sum_multi_agg_projection_and_prev() -> None:
    out = transpile_sql_to_verus(COUNT_SUM_SQL, {"num": NUM_SCHEMA})

    helper = _extract_multi_agg_fold_helper(out)
    spec = _extract_fn(out, "method_spec")
    _assert_no_placeholders(out)

    closure = _map_values_closure(spec)
    assert "map_values(|v|" in closure
    assert "(v.0, v.1)" in closure
    _assert_no_free_state_in_closure(closure)

    assert "let s0 = (prev.0 as int + 1) as u64;" in helper
    assert "let s1 = (prev.1 as int +" in helper
    assert re.search(r"prev\.\d+", helper)


def test_avg_prev_sum_cnt_substituted_not_placeholder() -> None:
    out = transpile_sql_to_verus(COUNT_AVG_SQL, {"num": NUM_SCHEMA})

    helper = _extract_multi_agg_fold_helper(out)
    _assert_no_placeholders(out)

    # AVG fold updates sum slot (prev.1) then count slot (prev.2), not __PREV_SUM__/__PREV_CNT__.
    assert "let s1 = (prev.1 as int +" in helper
    assert "let s2 = (prev.2 as int + 1) as u64;" in helper
    assert "__PREV_SUM__" not in helper
    assert "__PREV_CNT__" not in helper

    closure = _map_values_closure(_extract_fn(out, "method_spec"))
    assert re.search(r"if v\.2 == 0", closure) or "v.2" in closure


def test_regression_no_map_values_with_free_state_names() -> None:
    """Broken emission used map_values(|_k| ...) with unbound s0/s1 in the closure."""
    for sql, schema in (
        (Q1_LIKE_SQL, {"pre": PRE_SCHEMA}),
        (COUNT_SUM_SQL, {"num": NUM_SCHEMA}),
        (COUNT_AVG_SQL, {"num": NUM_SCHEMA}),
    ):
        out = transpile_sql_to_verus(sql, schema)
        assert "map_values(|_k|" not in out
        assert "map_values(|_k |" not in out

        closure = _map_values_closure(_extract_fn(out, "method_spec"))
        _assert_no_free_state_in_closure(closure)

        # Broken closure looked like raw.map_values(|_k| (s0, s1, ...)) with no `v`.
        if "(s0" in closure or ", s1" in closure:
            raise AssertionError(
                "map_values closure still references free s0/s1-style names"
            )
