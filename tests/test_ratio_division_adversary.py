"""Adversary regression tests for the ratio-of-aggregates / CASE-LIKE / CASE-arithmetic emitter and
``host_f64_div_by_zero`` (commit 3e9656b). Verdict: ``research_loop/menus/ratio_division_ADVERSARY_VERDICT.md``.

Passing tests pin what holds (spec meaning compared with DuckDB 1.5.4 on small tables; refusals; the trusted
statement's IEEE claims checked against DuckDB). ``xfail(strict=True)`` tests are findings that are open and still
reproduce: when a fix lands the test XPASSes and strict mode forces the marker to be removed.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction

import duckdb
import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.lemmas import float_div_zero_lemma_rs
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

SCHEMA = {
    "li": {
        "okey": "bigint",
        "price": "decimal(15,2)",
        "disc": "decimal(15,2)",
        "qty": "integer",
        "flag": "varchar",
        "pkey": "bigint",
        "nf": "varchar",
        "big": "decimal(18,0)",
        "d4": "decimal(15,4)",
        "dbl": "double",
    },
    "part": {"pkey": "bigint", "ptype": "varchar"},
    "num": {"adsh": "bigint", "value": "decimal(15,2)", "ddate": "bigint"},
    "v": {"adsh": "bigint", "value": "decimal(15,2)"},
}
DDL = (
    "create table li(okey bigint, price decimal(15,2), disc decimal(15,2), qty integer, flag varchar, pkey bigint,"
    " nf varchar, big decimal(18,0), d4 decimal(15,4), dbl double)",
    "create table part(pkey bigint, ptype varchar)",
)


def _catalog(nullable: frozenset[tuple[str, str]] = frozenset()) -> CatalogAssumptions:
    def col(t: str, c: str, ty: str) -> ColumnAssumption:
        kw: dict = {}
        if ty in ("bigint", "integer"):
            kw["max_value_exclusive"] = 2**20
        if (t, c) in nullable:
            kw["nullable"] = True
        return ColumnAssumption(**kw)

    return CatalogAssumptions(
        max_rows=64,
        tables={
            t: TableAssumptions(max_rows=64, columns={c: col(t, c, ty) for c, ty in SCHEMA[t].items()})
            for t in SCHEMA
        },
    )


def _emit(sql: str, nullable: frozenset[tuple[str, str]] = frozenset()) -> str:
    return emit_declarative_spec(sql, SCHEMA, _catalog(nullable))


def _flat(spec: str) -> str:
    return " ".join(spec.split())


# ---- spec meaning versus DuckDB (the spec formula is evaluated on the integer rows) --------------------------------

_ROWS = [
    # okey, price*100, disc*100, qty, flag, big, d4*10000
    (1, 300, 50, 2, "a1", 7, 12345),
    (2, 500, 25, 3, "b", 9, 20001),
    (3, 700, 0, 3, "ax", -4, -2500),
]


def _con(rows: list[tuple]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for ddl in DDL:
        con.execute(ddl)
    for okey, price, disc, qty, flag, big, d4 in rows:
        con.execute(
            "insert into li values (?,?,?,?,?,?,?,?,?,?)",
            [okey, price / 100, disc / 100, qty, flag, 1, "x", big, d4 / 10000, 1.5],
        )
    return con


def _hidden_sum(spec: str, alias: str, part: str, rows: list[tuple]) -> int:
    """The exact integer the spec's hidden aggregate ``<alias>__<part>`` folds over ``rows``."""
    chunks = _flat(spec).split("pub open spec fn ")
    found = [c for c in chunks if re.match(rf"(?:sum|count)_{alias}__{part}_val\(", c)]
    if not found:  # COUNT(*) / COUNT(col) of a non-nullable column: one per row
        return len(rows)
    head, tail = "{ if 0 <= i0 < li.n as int { ", " } else { 0int } }"
    chunk = found[0].strip()
    body = chunk[chunk.index(head) + len(head) : chunk.rindex(tail)]
    body = re.sub(r"spec_like\(\(li\.flag@\[i0\]@\), \"(.*?)\"@\)", lambda mm: f"like(R['flag'], {mm.group(1)!r})", body)
    body = re.sub(r"\(li\.(\w+)@\[i0\] as int\)", lambda mm: f"R[{mm.group(1)!r}]", body)
    body = body.replace("1int", "1").replace("0int", "0").replace("&&", " and ").replace("||", " or ").replace("!(", "not (")
    while "if " in body:
        body = re.sub(r"if (.*?) \{ (.*?) \} else \{ (.*?) \}", r"((\2) IFX (\1) ELSEX (\3))", body, count=1)
    body = body.replace("IFX", "if").replace("ELSEX", "else")
    total = 0
    for okey, price, disc, qty, flag, big, d4 in rows:
        env = {"R": {"okey": okey, "price": price, "disc": disc, "qty": qty, "flag": flag, "big": big, "d4": d4}}
        total += eval(body, {"like": lambda s, p: s.startswith(p.rstrip("%"))}, env)
    return total


def _spec_value(spec: str, alias: str, rows: list[tuple]) -> float:
    """The (single) f64 value the emitted ``ratio_<alias>`` pins, from its K, scales and the hidden sums."""
    text = _flat(spec)
    k = int(re.search(rf"fn ratio_{alias}\(.*?let ratio_n__: int = (-?\d+) \* ", text).group(1))
    f_den, f_num = (
        int(g)
        for g in re.search(
            rf"fn ratio_{alias}\(.*?\(ratio_v__ as real\) == \(\(ratio_n__ as real\) \* (\d+)real\) / \(\(ratio_d__ as real\) \* (\d+)real\)", text
        ).groups()
    )
    num = k * _hidden_sum(spec, alias, "num", rows)
    den = _hidden_sum(spec, alias, "den", rows)
    if den == 0:
        return math.inf if num > 0 else (-math.inf if num < 0 else math.nan)
    return float(Fraction(num * f_den, den * f_num))


_AGREE = [
    "select sum(price)/sum(disc) as r from li",
    "select 100.00 * sum(price) / sum(disc) as r from li",
    "select sum(price*disc)/sum(price) as r from li",
    "select sum(price*(1-disc)) / sum(price*(1+disc)) as r from li",
    "select sum(qty)/sum(okey) as r from li",
    "select sum(big)/sum(d4) as r from li",
    "select 0.5 * sum(price) / sum(qty) as r from li",
    "select -3 * sum(price) / sum(d4) as r from li",
    "select 2.25 * count(*) / sum(price) as r from li",
    "select count(*)/count(price) as r from li",
    "select 100.00 * sum(case when flag like 'a%' then price*(1-disc) else 0 end) / sum(price*(1-disc)) as r from li",
    "select sum(case when flag not like 'a%' then price*qty else disc end) / sum(price) as r from li",
    # zero denominators: every numerator sign
    "select sum(price) / sum(disc*0) as r from li",
    "select -1 * sum(price) / sum(disc*0) as r from li",
    "select 0 * sum(price) / sum(disc*0) as r from li",
    "select sum(case when qty > 100 then price else 0 end) / sum(case when qty > 100 then disc else 0 end) as r from li",
]


@pytest.mark.parametrize("sql", _AGREE)
def test_ratio_spec_value_matches_duckdb(sql: str) -> None:
    spec = _emit(sql)
    got = _con(_ROWS).execute(sql).fetchone()[0]
    want = _spec_value(spec, "r", _ROWS)
    if math.isnan(want):
        assert got is not None and math.isnan(got)
    else:
        assert got == pytest.approx(want, rel=1e-9, abs=1e-12)
        if math.isinf(want):
            assert math.copysign(1, got) == math.copysign(1, want)


@pytest.mark.parametrize(
    ("sql", "optional"),
    [
        ("select sum(price)/sum(disc) as r from li", True),
        ("select sum(price)/count(*) as r from li", True),
        ("select count(*)/count(*) as r from li", False),
        ("select flag, sum(price)/sum(disc) as r from li group by flag", False),
    ],
)
def test_null_ness_of_ratio_output(sql: str, optional: bool) -> None:
    """An ungrouped ratio with a SUM operand is NULL when no row passes (``Option``); COUNT/COUNT and grouped are not."""
    spec = _flat(_emit(sql))
    assert (" pub r: Option<f64>" in spec) == optional
    con = _con(_ROWS)
    empty = sql.replace(" from li", " from li where qty > 100")
    got = con.execute(empty).fetchall()
    if optional:
        assert got == [(None,)]
    elif "group by" in sql:
        assert got == []
    else:
        assert got[0][0] != got[0][0]  # NaN


# ---- the zero-denominator branch and the trusted statement ---------------------------------------------------------


def test_zero_denominator_branches_follow_the_sign_of_the_numerator_constant() -> None:
    spec = _flat(_emit("select -1 * sum(price) / sum(disc) as r from li"))
    assert "let ratio_n__: int = -1 * sum_r__num(li, i0);" in spec
    assert "else if ratio_n__ > 0 { ratio_v__.is_infinite_spec() && !ratio_v__.is_sign_negative_spec() }" in spec
    assert "else if ratio_n__ < 0 { ratio_v__.is_infinite_spec() && ratio_v__.is_sign_negative_spec() }" in spec
    assert "else { ratio_v__.is_nan_spec() }" in spec


@pytest.mark.parametrize(
    ("x", "want"),
    [("5.0", math.inf), ("-5.0", -math.inf), ("0.0", math.nan), ("-0.0", math.nan), ("4.9e-324", math.inf), ("-4.9e-324", -math.inf), ("1.7976931348623157e308", math.inf)],
)
def test_ieee_division_by_plus_zero_matches_the_trusted_ensures(x: str, want: float) -> None:
    """The three ensures of ``host_f64_div_by_zero`` hold for DuckDB's DOUBLE division (x/0.0 in Rust is the same IEEE op)."""
    got = duckdb.sql(f"select {x}::double / 0.0::double").fetchone()[0]
    if math.isnan(want):
        assert math.isnan(got)
    else:
        assert got == want


def test_duckdb_sum_over_zero_is_plus_zero_so_a_negative_constant_cannot_make_minus_zero_denominators() -> None:
    """Every zero denominator DuckDB divides by is the cast of an integer 0, i.e. +0.0 (the lemma divides by +0.0)."""
    got = duckdb.sql("select -1 * sum(x) / sum(y) from (select 5::decimal(15,2) x, 0::decimal(15,2) y)").fetchone()[0]
    assert got == -math.inf
    got = duckdb.sql("select sum(x) / sum(-y) from (select 5::decimal(15,2) x, 0::decimal(15,2) y)").fetchone()[0]
    assert got == math.inf  # SUM of -0 is the DECIMAL 0: no negative zero exists for integers


def test_div_zero_lemma_text_is_exactly_ieee() -> None:
    text = float_div_zero_lemma_rs()
    assert "requires x.is_finite_spec()" in text
    assert text.count("x / 0.0") == 1  # a Rust division by the literal +0.0
    assert "(x as real) > 0real ==> o.is_infinite_spec() && !o.is_sign_negative_spec()" in text
    assert "(x as real) < 0real ==> o.is_infinite_spec() && o.is_sign_negative_spec()" in text
    assert "(x as real) == 0real ==> o.is_nan_spec()" in text


def test_lemma_is_added_only_to_specs_that_state_inf_or_nan() -> None:
    ratio = assemble_declarative_program(_emit("select sum(price)/sum(disc) as r from li"), "    Vec::new()")
    plain = assemble_declarative_program(_emit("select avg(price) as a from li"), "    Vec::new()")
    assert "host_f64_div_by_zero" in ratio
    assert "host_f64_div_by_zero" not in plain


# ---- refusals ------------------------------------------------------------------------------------------------------

_REFUSED = [
    "select sum(price) as s from li where price / disc > 2",
    "select sum(price/disc) as s from li",
    "select sum(price)/sum(disc)/2 as r from li",
    "select (sum(price)/sum(disc)) + 1 as r from li",
    "select 100 * (sum(price) / sum(disc)) as r from li",
    "select sum(price)/sum(disc) from li",
    "select r from (select sum(price)/sum(disc) as r from li) t",
    "with t as (select flag, sum(price)/sum(disc) as r from li group by flag) select flag from t where r > 1",
    "select flag, sum(price)/sum(disc) as r from li group by flag having sum(price)/sum(disc) > 1",
    "select flag, sum(price)/sum(disc) as r from li group by flag having r > 1",
    "select flag, sum(price)/sum(disc) as r from li group by flag order by r desc limit 1",
    "select flag, sum(price)/sum(disc) as r from li group by flag order by flag, r",
    "select flag, sum(price)/sum(disc) as r from li group by flag order by 2",
    "select sum(price) // sum(disc) as r from li",
    "select sum(price) % sum(disc) as r from li",
    "select sum(dbl)/sum(dbl) as r from li",
    "select sum(price)/sum(dbl) as r from li",
    "select avg(price)/sum(disc) as r from li",
    "select min(price)/sum(disc) as r from li",
    "select sum(distinct price)/sum(disc) as r from li",
    "select count(distinct price)/sum(disc) as r from li",
    "select sum(price) filter (where qty>2)/sum(disc) as r from li",
    "select sum(price)/sum(disc) filter (where qty>2) as r from li",
    "select sum(price) / (2 * sum(disc)) as r from li",
    "select sum(price) / 0 as r from li",
    "select 1 / sum(price) as r from li",
    "select price / disc as r from li",
    "select sum(price)/sum(disc) as r, sum(qty)/sum(okey) as r from li",
    "select sum(price)/nullif(sum(disc),0) as r from li",
    "select coalesce(sum(price)/sum(disc), 0) as r from li",
    "select sum(case when flag like 'P%' then price/2 else 0 end) as s from li",
    "select sum(case when flag like 'P%' then dbl*2 else 0 end) as s from li",
    "select sum(case when flag like 'P%' then qty*qty else 0 end) as s from li",
    "select sum(case when flag like 'P%' then price*price*price*price*price*price*price*price*price*price*price*price*price*price*price*price*price*price*price*price else 0 end) as s from li",
    "select sum(case when flag like 'P%' escape '!' then price else 0 end) as s from li",
    "select sum(case when flag ilike 'p%' then price else 0 end) as s from li",
    "select sum(case when flag like 'P%' then price else 0.5 end) as s from li",
    "select sum(case when flag like 'P%' then price else qty end) as s from li",
]


@pytest.mark.parametrize("sql", _REFUSED)
def test_refusal_holds(sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        _emit(sql)


def test_nullable_operands_and_case_like_on_nullable_columns_are_refused_not_guessed() -> None:
    nullable = frozenset({("li", "nf"), ("li", "d4")})
    for sql in (
        "select sum(d4)/sum(price) as r from li",
        "select count(d4)/count(*) as r from li",
        "select sum(case when nf like 'x%' then price else 0 end)/sum(price) as r from li",
        "select sum(case when nf not like 'x%' then price else 0 end) as r from li",
        "select sum(case when nf not like 'x%' then price else 0 end)/sum(price) as r from li where nf is not null",
    ):
        with pytest.raises(DeclarativeUnsupported):
            _emit(sql, nullable)
    # with the column proved not NULL by the WHERE the ratio is exact
    spec = _emit("select sum(d4)/sum(price) as r from li where d4 is not null", nullable)
    assert "d4__valid" in spec


# ---- open findings (strict xfail: they reproduce today) ---------------------------------------------------------


def _ratio_params(spec: str) -> list[str]:
    sig = re.search(r"pub open spec fn ratio_\w+\(([^)]*)\)", spec).group(1)
    return [p.split(":")[0].strip() for p in sig.split(",")]


def test_ratio_over_table_named_num_does_not_shadow_its_parameter() -> None:
    params = _ratio_params(_emit("select sum(value)/sum(ddate) as r from num"))
    body = _emit("select sum(value)/sum(ddate) as r from num").split("pub open spec fn ratio_r(")[1].split("\n}")[0]
    assert "let num" not in body and "let den" not in body  # locals never reuse a table's parameter name
    assert params.count("num") == 1


def test_ratio_over_table_named_v_has_unique_parameter_names() -> None:
    params = _ratio_params(_emit("select sum(value)/sum(value) as r from v"))
    assert len(set(params)) == len(params)


def _defined_once(spec: str, name: str) -> bool:
    return len(re.findall(rf"pub open spec fn {name}\(", spec)) <= 1


def test_output_alias_named_like_a_hidden_operand_is_refused_or_unique() -> None:
    try:
        spec = _emit("select sum(price)/sum(disc) as r, sum(qty) as r__num from li")
    except DeclarativeUnsupported:
        return
    assert _defined_once(spec, "sum_r__num") and _defined_once(spec, "sum_r__num_val")


# FINDING 3 (fixed in c4b4870, reproduced at 3e9656b): ORDER BY a ratio without LIMIT was accepted and stated with `as real` on a
# possibly inf/NaN f64. It is refused on every path now; this pins it.
def test_order_by_a_ratio_is_refused_on_every_path() -> None:
    with pytest.raises(DeclarativeUnsupported):
        _emit("select flag, sum(price)/sum(disc) as r from li group by flag order by r desc")


def test_finding4_duckdb_side_exists_over_an_ungrouped_aggregate_is_always_true() -> None:
    """Pins the DuckDB fact FINDING 4 rests on (passes): the aggregate subquery returns one row even over no rows."""
    con = _con([])
    con.execute("insert into part values (1,'a'),(2,'b')")
    assert con.execute("select count(*) from part where exists (select sum(price) from li where qty > 100)").fetchone() == (2,)
    assert con.execute("select count(*) from part where exists (select sum(price)/sum(disc) as r from li where qty > 100)").fetchone() == (2,)


@pytest.mark.xfail(strict=True, reason="FINDING 4 (pre-existing, reachable with a ratio): EXISTS over an ungrouped aggregate subquery is emitted as `exists row in the subquery's table`; SQL says the aggregate always returns one row, so the spec forces the count to 0 where DuckDB returns 2")
@pytest.mark.parametrize(
    "sql",
    [
        "select count(*) as c from part where exists (select sum(price) as s from li where qty > 100)",
        "select count(*) as c from part where exists (select sum(price)/sum(disc) as r from li where qty > 100)",
        "select count(*) as c from part where not exists (select count(*)/count(*) as r from li where qty > 100)",
    ],
)
def test_exists_over_ungrouped_aggregate_subquery_is_refused_or_always_true(sql: str) -> None:
    try:
        spec = _emit(sql)
    except DeclarativeUnsupported:
        return
    # acceptable only if the subquery's WHERE does not decide the EXISTS
    assert not re.search(r"exists\|e0: int\| 0 <= e0 < li\.n as int && \(\(\(li\.qty", _flat(spec))
