"""ORDER BY is a spec sort, then LIMIT, inside method_spec."""

from __future__ import annotations

from verus_transpiler.transpiler import transpile_sql_to_verus

_STAR = {
    "pre": {
        "adsh": "string",
        "stmt": "string",
        "tag": "string",
        "version": "string",
        "line": "int",
        "plabel": "string",
    },
    "sub": {"adsh": "string", "form": "string", "name": "string"},
    "tag": {
        "tag": "string",
        "version": "string",
        "tlabel": "string",
        "custom": "int",
    },
}

_STAR_SQL = """
SELECT s.name, p.stmt, t.tlabel, p.line, p.plabel
FROM pre p
JOIN sub s ON p.adsh = s.adsh
JOIN tag t ON p.tag = t.tag AND p.version = t.version
WHERE s.form = '10-Q' AND p.stmt = 'CI' AND t.custom = 0
ORDER BY s.name, p.line
LIMIT 50
"""


def test_star_order_by_sorts_before_limit() -> None:
    out = transpile_sql_to_verus(_STAR_SQL, _STAR)
    assert "spec_seq_take(spec_seq_sort_by(" in out
    assert "|a: (Seq<char>, Seq<char>, Seq<char>, u32, Seq<char>), b:" in out
    assert "spec_join_proj_before(a, b)" in out
    assert "spec_char_seq_lt(a.0, b.0)" in out
    assert "(a.3) < (b.3)" in out
    assert "agent may apply in run_query" not in out
    assert "assume(" not in out
    assert "arbitrary()" not in out


def test_group_by_limit_stays_a_full_map() -> None:
    sql = """
    SELECT s.form, COUNT(*) AS num_lines
    FROM pre p JOIN sub s ON p.adsh = s.adsh
    GROUP BY s.form
    ORDER BY num_lines DESC
    LIMIT 10
    """
    out = transpile_sql_to_verus(
        sql,
        {
            "pre": {"adsh": "string", "stmt": "string"},
            "sub": {"adsh": "string", "form": "string"},
        },
    )
    spec = out.split("pub open spec fn method_spec", 1)[1].split("pub proof fn", 1)[0]
    assert "Map<" in spec
    assert "spec_seq_take(" not in spec
    assert "agent may apply in run_query" not in out
    assert "run_query still returns the full map" in out


def test_single_column_desc_flips_the_spec_compare() -> None:
    sql = "SELECT name FROM sub ORDER BY name DESC LIMIT 2"
    out = transpile_sql_to_verus(sql, {"sub": {"name": "string", "adsh": "string"}})
    assert "spec_seq_take(spec_seq_sort_by(" in out
    assert "spec_char_seq_lt(b, a)" in out
    assert "agent may apply in run_query" not in out
