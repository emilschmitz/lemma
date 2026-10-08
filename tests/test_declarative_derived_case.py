"""An aggregate expression (CASE, ratio of CASE sums) over a derived table is inlined into the outer query.

The derived table is a plain select-project-join; the outer aggregate runs over its joined rows, with each
derived output name replaced by the expression it stands for. Emission checks plus a differential: the flattened
``Query`` (CASE text) evaluated in Python over DuckDB's joined rows equals DuckDB's answer.
"""

from __future__ import annotations

import random
import re

import duckdb
import pytest

from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.numeric_rewrite import rewrite_numeric
from declarative_spec.parse_query import parse_query
from declarative_spec.resolve import flatten_derived
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {
    "fact": {"fk": "bigint", "dk1": "bigint", "dk2": "bigint", "v": "bigint", "w": "bigint", "d": "date", "tag": "varchar"},
    "dim": {"dk": "bigint", "region": "varchar", "label": "varchar"},
}
CATALOG = CatalogAssumptions(
    max_rows=64,
    tables={
        t: TableAssumptions(
            max_rows=64,
            columns={
                c: ColumnAssumption(max_value_exclusive=2**20)
                for c, ty in SCHEMA[t].items()
                if ty in ("bigint", "integer")
            },
        )
        for t in SCHEMA
    },
)

# Q8 shape: ratio of conditional sums by a date part over an SPJ derived table with a column renamed through a table alias.
RATIO = (
    "SELECT yr, SUM(CASE WHEN lab = 'a' THEN amt ELSE 0 END) / SUM(amt) AS share FROM ("
    " SELECT EXTRACT(year FROM d) AS yr, v * (10 - w) AS amt, d2.label AS lab"
    " FROM fact, dim d1, dim d2 WHERE dk1 = d1.dk AND dk2 = d2.dk AND d1.region = 'x' AND v > 0"
    ") AS t GROUP BY yr ORDER BY yr"
)
# A filtered derived table whose outputs are reused by several aggregates.
REUSED = (
    "SELECT g, SUM(CASE WHEN g = 'p' THEN q ELSE 0 END) AS sp, SUM(q) AS sq, COUNT(CASE WHEN q > 2 THEN q END) AS big FROM ("
    " SELECT tag AS g, v AS q FROM fact WHERE w <> 0"
    ") AS t GROUP BY g ORDER BY g"
)


def test_ratio_of_case_sums_over_a_derived_join_emits_the_inner_cells() -> None:
    spec = emit_declarative_spec(RATIO, SCHEMA, CATALOG)
    assert "spec_civil_year(" in spec
    assert "pub share: f64" in spec
    # the CASE condition reads the second alias of dim, so the spec has a cell of the aliased row
    assert "(d2.label@[i2]@) == " in spec


def test_case_over_a_filtered_derived_table_with_outputs_reused() -> None:
    spec = emit_declarative_spec(REUSED, SCHEMA, CATALOG)
    assert "(fact.w@[i0] as int) != 0" in spec
    assert spec.count("(fact.v@[i0] as int)") >= 3  # CASE result, plain SUM, COUNT(CASE) all read v


@pytest.mark.parametrize(
    "sql",
    [
        # two outputs of one name: the outer reference is ambiguous in DuckDB, so it is refused
        "SELECT SUM(CASE WHEN q > 1 THEN q ELSE 0 END) AS s FROM (SELECT v AS q, w AS q FROM fact) AS t",
        # a FILTER clause names derived outputs; its text is not rewritten
        "SELECT SUM(CASE WHEN q > 1 THEN q ELSE 0 END) FILTER (WHERE q > 1) AS s FROM (SELECT v AS q FROM fact) AS t",
        # an output the derived table does not have
        "SELECT SUM(CASE WHEN zz > 1 THEN q ELSE 0 END) AS s FROM (SELECT v AS q FROM fact) AS t",
        # a derived table that aggregates is not a plain select-project-join
        "SELECT SUM(CASE WHEN c > 1 THEN c ELSE 0 END) AS s FROM (SELECT tag, COUNT(*) AS c FROM fact GROUP BY tag) AS t",
    ],
)
def test_unsupported_derived_case_shapes_stay_loud(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec(sql, SCHEMA, CATALOG)


# ---- differential against DuckDB -------------------------------------------------------------------------------------


def _db(seed: int) -> duckdb.DuckDBPyConnection:
    rng = random.Random(seed)
    con = duckdb.connect()
    con.execute("CREATE TABLE dim(dk BIGINT, region VARCHAR, label VARCHAR)")
    con.execute("CREATE TABLE fact(fk BIGINT, dk1 BIGINT, dk2 BIGINT, v BIGINT, w BIGINT, d DATE, tag VARCHAR)")
    con.executemany(
        "INSERT INTO dim VALUES (?, ?, ?)",
        [(i, rng.choice(["x", "y"]), rng.choice(["a", "b", "c"])) for i in range(6)],
    )
    con.executemany(
        "INSERT INTO fact VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                i,
                rng.randint(0, 6),  # 6 has no dim row: unmatched
                rng.randint(0, 5),
                rng.choice([0, 0, 1, 2, 3, 5, -2]),  # zeros, negatives and ties
                rng.choice([0, 0, 3, 10, 12]),
                f"{rng.choice([1994, 1995, 1996])}-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}",
                rng.choice(["p", "q", "r"]),
            )
            for i in range(rng.randint(0, 45))
        ],
    )
    return con


def _py(text: str) -> str:
    """The generated CASE text as a Python expression over a row dict."""
    text = re.sub(r"cols\.(?:r#)?((?:\w+\.)?\w+)@\[i\]", lambda m: f"row[{m.group(1)!r}]", text)
    text = re.sub(r"__STR_([0-9a-f]+)__", lambda m: repr(bytes.fromhex(m.group(1)).decode()), text)
    text = text.replace("&&", " and ").replace("||", " or ")
    inner = re.compile(r"if \(([^{}]*)\) \{ ([^{}]*) \} else \{ ([^{}]*) \}")
    while inner.search(text):
        text = inner.sub(lambda m: f"(({m.group(2)}) if ({m.group(1)}) else ({m.group(3)}))", text)
    return text


@pytest.mark.parametrize("seed", range(8))
def test_ratio_over_derived_join_matches_duckdb(seed: int) -> None:
    con = _db(seed)
    want = dict(con.execute(RATIO).fetchall())
    integer_sql, _scales = rewrite_numeric(RATIO, SCHEMA, CATALOG)
    query = flatten_derived(parse_query(integer_sql))
    num = next(a for a in query.aggs if a.alias == "share__num")
    rows = con.execute(
        'SELECT v, w, d, d2.label AS "d2.label" FROM fact, dim d1, dim d2 '
        "WHERE dk1 = d1.dk AND dk2 = d2.dk AND d1.region = 'x' AND v > 0"
    ).fetchall()
    num_by: dict[int, int] = {}
    den_by: dict[int, int] = {}
    for v, w, d, lab in rows:
        row = {"v": v, "w": w, "d": d, "d2.label": lab}
        # the CASE reads the inner cells `amt` stands for: v * (10 - w)
        num_by[d.year] = num_by.get(d.year, 0) + eval(_py(num.expr), {"row": row})  # noqa: S307
        den_by[d.year] = den_by.get(d.year, 0) + v * (10 - w)
    assert set(num_by) == set(want)
    for yr, n in num_by.items():
        if den_by[yr] == 0:
            assert want[yr] is None or want[yr] != want[yr] or abs(want[yr]) == float("inf")
        else:
            assert abs(n / den_by[yr] - want[yr]) < 1e-9, (yr, n, den_by[yr], want[yr])


@pytest.mark.parametrize("seed", range(8))
def test_reused_outputs_over_filtered_derived_match_duckdb(seed: int) -> None:
    con = _db(seed)
    want = con.execute(REUSED).fetchall()
    query = flatten_derived(parse_query(REUSED))
    sp = next(a for a in query.aggs if a.alias == "sp")
    big = next(a for a in query.aggs if a.alias == "big")
    got: dict[str, list[int]] = {}
    for v, w, tag in con.execute("SELECT v, w, tag FROM fact WHERE w <> 0").fetchall():
        row = {"v": v, "w": w, "tag": tag}
        acc = got.setdefault(tag, [0, 0, 0])
        acc[0] += eval(_py(sp.expr), {"row": row})  # noqa: S307
        acc[1] += v
        acc[2] += eval(_py(big.expr), {"row": row})  # noqa: S307
    assert want == [(g, *got[g]) for g in sorted(got)]
