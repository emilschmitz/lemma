"""Membership in grammar G (docs/SQL_FRAGMENT.md): one accepted and one refused query per rule, the three levels,
the typed rules, and the generator that draws from G."""

from __future__ import annotations

import duckdb
import pytest

from declarative_spec.fragment import fragment_level, in_fragment

HIGH = "SELECT g, SUM(a) AS s, COUNT(*) AS n FROM t WHERE a > 1 AND b IN (1, 2) GROUP BY g"
MED = "SELECT t.g, SUM(t.a * u.w) AS s FROM t JOIN u ON t.k = u.k WHERE u.w BETWEEN 1 AND 5 GROUP BY t.g ORDER BY t.g LIMIT 3"
FULL = (
    "SELECT t.g, AVG(CASE WHEN t.a > 1 THEN t.a ELSE 0 END) AS m, COUNT(DISTINCT t.b) AS d FROM t JOIN u ON t.k = u.k "
    "JOIN v ON u.k = v.k WHERE t.a > (SELECT MAX(w) FROM u) AND t.k NOT IN (SELECT k FROM v) "
    "AND NOT EXISTS (SELECT 1 FROM v WHERE v.k = t.k AND v.z > 0) GROUP BY t.g HAVING COUNT(*) > 2 ORDER BY t.g LIMIT 5"
)


@pytest.mark.parametrize(("sql", "level"), [(HIGH, "high"), (MED, "med"), (FULL, "full")])
def test_smallest_level(sql: str, level: str) -> None:
    assert fragment_level(sql)[0] == level
    assert in_fragment(sql)[0]


def test_levels_are_nested() -> None:
    assert in_fragment(HIGH, "high")[0] and in_fragment(HIGH, "med")[0]
    assert in_fragment(MED, "med")[0] and not in_fragment(MED, "high")[0]
    assert not in_fragment(FULL, "med")[0]
    assert fragment_level(MED)[1].startswith("L1")  # why it is not high
    assert fragment_level(FULL)[1].startswith("L")


@pytest.mark.parametrize(
    ("sql", "rule"),
    [
        ("SELECT a FROM t, u WHERE t.k = u.k", "R5"),
        ("SELECT t.a FROM t LEFT JOIN u ON t.k = u.k", "R5"),
        ("SELECT t.a FROM t JOIN u ON t.k < u.k", "R6"),
        ("SELECT a, SUM(a) OVER (PARTITION BY g) AS w FROM t", "R2"),
        ("SELECT a FROM t UNION SELECT a FROM u", "R1"),
        ("WITH c AS (SELECT a FROM t) SELECT a FROM c", "R1"),
        ("SELECT a FROM (SELECT a FROM t) AS d", "R5"),
        ("SELECT a FROM t WHERE s LIKE 'x%'", "R18"),
        ("SELECT a / b AS q FROM t", "R14"),
        ("SELECT UPPER(s) AS q FROM t", "R14"),
        ("SELECT a FROM t WHERE a > (SELECT MAX(w) FROM u WHERE u.k = t.k)", "R13"),
        ("SELECT SUM(CASE WHEN a > 1 THEN a END) AS s FROM t", "R15"),
        ("SELECT a FROM t OFFSET 3", "R2"),
        ("SELECT * FROM t", "R4"),
        ("SELECT a FROM t HAVING a > 1", "R8"),
        ("SELECT a + 1 FROM t", "R11"),
        ("SELECT a FROM t WHERE a + 1 IN (1, 2)", "R17"),
        ("SELECT a FROM t LIMIT a", "R9"),
        ("SELECT COUNT(DISTINCT a, b) AS c FROM t", "R12"),
        ("SELECT a FROM t WHERE CAST(a AS VARCHAR) = 'x'", "R14"),
        ("SELECT a FROM t WHERE EXISTS (SELECT 1 FROM u WHERE u.k > t.k)", "R13"),
    ],
)
def test_each_rule_refuses_and_names_itself(sql: str, rule: str) -> None:
    ok, why = in_fragment(sql)
    assert not ok
    assert why.startswith(rule), why


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT g, AVG(a) AS m FROM t GROUP BY g",  # needs full
        "SELECT g, SUM(a) AS s FROM t GROUP BY g HAVING SUM(a) > 3",
        "SELECT g, SUM(CASE WHEN a > 1 THEN a ELSE 0 END) AS s FROM t GROUP BY g",
        "SELECT g, SUM(a) AS s FROM t WHERE a * 2 > 3 GROUP BY g",
        "SELECT g, SUM(a) AS s FROM t GROUP BY g ORDER BY g",  # ORDER BY without LIMIT
        "SELECT SUM(a) AS s FROM t",  # no group key
    ],
)
def test_levels_leave_out_what_the_spec_says(sql: str) -> None:
    assert not in_fragment(sql, "med")[0]


def test_typed_rules_need_a_schema() -> None:
    schema = {"t": {"g": "int", "s": "string", "a": "int"}}
    string_max = "SELECT g, MAX(s) AS m FROM t GROUP BY g"
    assert in_fragment(string_max)[0]
    ok, why = in_fragment(string_max, schema=schema)
    assert not ok and why.startswith("T1")
    grouped = "SELECT g, SUM(a) AS m FROM t GROUP BY g"
    assert in_fragment(grouped, schema=schema, nullable=set())[0]
    ok, why = in_fragment(grouped, schema=schema, nullable={("t", "a")})
    assert not ok and why.startswith("T2")
    assert in_fragment("SELECT SUM(a) AS m FROM t", schema=schema, nullable={("t", "a")})[0]  # ungrouped is not T2


@pytest.mark.parametrize(
    ("sql", "level", "ok"),
    [
        ("SELECT g, MIN(s) AS m FROM t GROUP BY g", "high", False),
        ("SELECT t.g, MAX(t.s) AS m FROM t JOIN u ON t.k = u.k GROUP BY t.g ORDER BY t.g LIMIT 3", "med", False),
        ("SELECT g, MAX(u.s) AS m FROM t JOIN u ON t.k = u.k GROUP BY g", "full", False),
        ("SELECT g, MIN(a) AS m, MAX(d) AS x, MAX(dt) AS y FROM t GROUP BY g", "high", True),  # int, decimal, date
        ("SELECT g, MIN(f) AS m FROM t GROUP BY g", "high", False),  # the low levels are float-free
        ("SELECT g, MIN(f) AS m FROM t GROUP BY g", "full", True),
    ],
)
def test_t1_min_max_over_strings_is_out_and_names_its_rule(sql: str, level: str, ok: bool) -> None:
    schema = {
        "t": {"g": "int", "k": "int", "a": "int", "s": "string", "d": "decimal(18,4)", "dt": "date", "f": "double"},
        "u": {"k": "int", "s": "string"},
    }
    got, why = in_fragment(sql, level, schema=schema)
    assert got is ok, why
    if not ok:
        assert why.startswith("T1") and "dictionary string" in why


def test_t2_looks_at_value_positions_not_case_conditions() -> None:
    schema = {"t": {"g": "int", "a": "int", "b": "int"}}
    cond = "SELECT g, SUM(CASE WHEN b > 1 THEN a ELSE 0 END) AS m FROM t GROUP BY g"
    assert in_fragment(cond, schema=schema, nullable={("t", "b")})[0]  # b only decides a branch
    ok, why = in_fragment(cond, schema=schema, nullable={("t", "a")})  # a is the summed value
    assert not ok and why.startswith("T2")


def test_unparseable_is_a_refusal_not_a_crash() -> None:
    ok, why = in_fragment("SELECT FROM WHERE (")
    assert not ok and why.startswith("R0")


def test_no_dataset_names_in_the_fragment_module() -> None:
    from pathlib import Path

    text = Path("declarative_spec/fragment.py").read_text().lower()
    assert not [w for w in ("edgar", "tpch", "sec_margin", "duckdb") if w in text]


# ---- the generator ----------------------------------------------------------------------------------------------


@pytest.fixture
def small_db(tmp_path):
    path = tmp_path / "small.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE f (k INTEGER, g VARCHAR, a INTEGER, d DECIMAL(10,2))")
    con.execute("CREATE TABLE dim (k INTEGER, nm VARCHAR, w INTEGER)")
    con.execute("INSERT INTO f SELECT i % 20, 'g' || (i % 4), i % 7, i * 1.25 FROM range(400) t(i)")
    con.execute("INSERT INTO dim SELECT i, 'n' || (i % 3), i % 5 FROM range(20) t(i)")
    con.close()
    return path


@pytest.mark.parametrize("level", ["high", "med", "full"])
def test_generator_is_deterministic_and_stays_in_its_level(small_db, level) -> None:
    from research_loop.scripts.fragment_gen import draw

    a, _, _ = draw(small_db, 3, 12, level=level)
    b, _, _ = draw(small_db, 3, 12, level=level)
    assert a == b
    assert a != draw(small_db, 4, 12, level=level)[0]
    rank = {"high": 0, "med": 1, "full": 2}
    for sql in a:
        got, _ = fragment_level(sql)
        assert got is not None and rank[got] <= rank[level], sql


def test_generator_keeps_only_runnable_nonempty_nonconstant_queries(small_db) -> None:
    from research_loop.scripts.fragment_gen import draw

    kept, _, _ = draw(small_db, 9, 20, level="full")
    con = duckdb.connect(str(small_db), read_only=True)
    for sql in kept:
        rows = con.execute(sql).fetchall()
        assert rows and not (len(rows) > 1 and all(len({r[i] for r in rows}) == 1 for i in range(len(rows[0])))), sql


def test_pairwise_coverage_is_reported(small_db) -> None:
    from research_loop.scripts.fragment_gen import draw, feasible_pairs

    _, _, pairs = draw(small_db, 5, 40, level="high")
    assert len(pairs["covered"]) == len(feasible_pairs("high"))
    assert set(pairs["uncovered"]) <= set(pairs["covered"])
