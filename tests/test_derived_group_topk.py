"""ORDER BY/LIMIT over a grouped derived table is that group, sorted, then cut."""

from __future__ import annotations

from verus_transpiler.transpiler import transpile_sql_to_verus

_SCHEMA = {"t": {"k": "INTEGER", "amount": "BIGINT"}}

_TOP = (
    "SELECT k, s FROM (SELECT k, SUM(amount) AS s FROM t GROUP BY k) u "
    "ORDER BY s DESC, k ASC LIMIT 5"
)


def _spec(src: str) -> str:
    return src.split("pub open spec fn method_spec(", 1)[1].split("// ===", 1)[0]


def test_exact_sum_top_is_sorted_u128_prefix(monkeypatch) -> None:
    monkeypatch.setenv("LEMMA_EXACT_SUM", "1")
    src = transpile_sql_to_verus(_TOP, _SCHEMA)
    spec = _spec(src)
    assert "Seq<(u32, u128)>" in src
    assert "spec_seq_sort_by" in spec
    assert "spec_seq_take(" in spec
    assert ", 5)" in spec


def test_count_top_limit_one_stays_u64(monkeypatch) -> None:
    monkeypatch.delenv("LEMMA_EXACT_SUM", raising=False)
    src = transpile_sql_to_verus(
        "SELECT k, s FROM (SELECT k, COUNT(*) AS s FROM t GROUP BY k) u "
        "ORDER BY k ASC LIMIT 1",
        _SCHEMA,
    )
    spec = _spec(src)
    assert "Seq<(u32, u64)>" in src
    assert "u128" not in spec
    assert "spec_seq_take(" in spec
    assert ", 1)" in spec
