"""TPC-H Q3, Q14, Q19 in the declarative emitter: emission, refusals, verified reference bodies, DuckDB differentials.

* Q14 is a ratio of two exact DECIMAL sums (CASE with LIKE and arithmetic results, then `/`): DuckDB divides in DOUBLE.
* Q19 is a three-way disjunction over a join; Q3 a three-table join with GROUP BY, ORDER BY and LIMIT.
Each reference body (``tests/fixtures/declarative_proofs/tpch_q*.rs``) is verified by Verus (memory-guarded), mutated bodies
are rejected, and the compiled program's rows are compared with DuckDB on a deterministic slice of dbgen SF 0.01.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
from pathlib import Path

import duckdb
import pytest

from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
from declarative_spec.pipeline import run_declarative_metrics
from research_loop.decl_query_measure import write_query_measure
from research_loop.scripts.declarative_round import tpch_schema_and_catalog
from tests.tpch_mini import build_mini_tpch

ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"
VERUS = Path("/home/emil/tools/verus/verus")
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")

Q14 = (
    "select 100.00 * sum(case when p_type like 'PROMO%' then l_extendedprice * (1 - l_discount) else 0 end) "
    "/ sum(l_extendedprice * (1 - l_discount)) as promo_revenue from lineitem, part "
    "where l_partkey = p_partkey and l_shipdate >= date '1995-09-01' and l_shipdate < date '1995-09-01' + interval '1' month"
)
Q19 = (
    "select sum(l_extendedprice * (1 - l_discount)) as revenue from lineitem, part where "
    "(p_partkey = l_partkey and p_brand = 'Brand#12' and p_container in ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG') "
    "and l_quantity >= 1 and l_quantity <= 1 + 10 and p_size between 1 and 5 and l_shipmode in ('AIR', 'AIR REG') "
    "and l_shipinstruct = 'DELIVER IN PERSON') "
    "or (p_partkey = l_partkey and p_brand = 'Brand#23' and p_container in ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK') "
    "and l_quantity >= 10 and l_quantity <= 10 + 10 and p_size between 1 and 10 and l_shipmode in ('AIR', 'AIR REG') "
    "and l_shipinstruct = 'DELIVER IN PERSON') "
    "or (p_partkey = l_partkey and p_brand = 'Brand#34' and p_container in ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG') "
    "and l_quantity >= 20 and l_quantity <= 20 + 10 and p_size between 1 and 15 and l_shipmode in ('AIR', 'AIR REG') "
    "and l_shipinstruct = 'DELIVER IN PERSON')"
)
Q3 = (
    "select l_orderkey, sum(l_extendedprice * (1 - l_discount)) as revenue, o_orderdate, o_shippriority "
    "from customer, orders, lineitem where c_mktsegment = 'BUILDING' and c_custkey = o_custkey "
    "and l_orderkey = o_orderkey and o_orderdate < date '1995-03-15' and l_shipdate > date '1995-03-15' "
    "group by l_orderkey, o_orderdate, o_shippriority order by revenue desc, o_orderdate limit 10"
)


@contextlib.contextmanager
def timing_lock(path: str = "/tmp/lemma_timing.lock"):
    """Serialize with the iterator's timing runs (the compiled program times itself, even on a tiny table)."""
    with open(path, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@pytest.fixture(scope="module")
def part_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = build_mini_tpch(tmp_path_factory.mktemp("mini") / "part.duckdb", "part")
    if path is None:
        pytest.skip("duckdb tpch extension unavailable")
    return path


@pytest.fixture(scope="module")
def customer_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = build_mini_tpch(tmp_path_factory.mktemp("mini") / "customer.duckdb", "customer")
    if path is None:
        pytest.skip("duckdb tpch extension unavailable")
    return path


def _run(sql: str, db: Path, body: str, work: Path) -> tuple[dict, dict]:
    schema, catalog = tpch_schema_and_catalog(db)
    prepared = write_query_measure(sql=sql, schema=schema, catalog=catalog, db_path=db, dest=work / "data")
    spec = emit_declarative_spec(sql, schema, catalog)
    os.environ["LEMMA_VERUS_BIN"] = str(ROOT / "scripts" / "ram" / "verus_guarded.sh")
    with timing_lock(), timing_lock("/tmp/tpch_emit_verus.lock"):  # one Verus at a time on the shared machine
        metrics = run_declarative_metrics(spec_rs=spec, agent_source=body, work_dir=work / "run", column_bins=prepared["bins"])
    return metrics, prepared


def _check(sql: str, db: Path, fixture: str, tmp: Path, mutate: tuple[str, str] | None = None) -> tuple[dict, dict]:
    body = (PROOFS / fixture).read_text()
    if mutate is not None:
        assert mutate[0] in body, mutate[0]
        body = body.replace(mutate[0], mutate[1])
    return _run(sql, db, body, tmp)


# ---- emission and refusals (no Verus) ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tpch() -> tuple[dict, object]:
    import tempfile

    path = build_mini_tpch(Path(tempfile.mkdtemp()) / "emit.duckdb", "part")
    if path is None:
        pytest.skip("duckdb tpch extension unavailable")
    return tpch_schema_and_catalog(path)


def test_q14_states_the_ratio_over_two_hidden_sums_with_ieee_zero_cases(tpch: tuple[dict, object]) -> None:
    spec = emit_declarative_spec(Q14, *tpch)
    assert "pub open spec fn ratio_promo_revenue(" in spec
    assert "10000 * sum_promo_revenue__num(" in spec  # 100.00 is 10000 at scale 2
    assert "((num as real) * 10000real) / ((den as real) * 1000000real)" in spec  # scales 6 over 4
    for case in ("v.is_infinite_spec() && !v.is_sign_negative_spec()", "v.is_infinite_spec() && v.is_sign_negative_spec()", "v.is_nan_spec()"):
        assert case in spec
    assert "pub promo_revenue: Option<f64>," in spec  # SUM of no rows is NULL
    assert "pub fn host_f64_div_by_zero" in spec  # the one trusted item of a ratio spec
    assert "spec_like((part.p_type@[i1]@), \"PROMO%\"@)" in spec


def test_a_spec_without_a_ratio_carries_no_division_lemma(tpch: tuple[dict, object]) -> None:
    spec = emit_declarative_spec("select avg(l_extendedprice) as x from lineitem", *tpch)
    assert "host_f64_div_by_zero" not in spec
    assert "lemma_f64_div_real" in spec  # the pinned idealization family is untouched
    assert "host_f64_div_by_zero" not in emit_declarative_spec(Q19, *tpch)


def test_q3_and_q19_emit_with_the_full_clause_shapes(tpch: tuple[dict, object], customer_db: Path) -> None:
    q19 = emit_declarative_spec(Q19, *tpch)
    assert q19.count("&& ((lineitem.l_shipinstruct@[i0]@) == \"DELIVER IN PERSON\"@)") == 3
    assert "pub revenue: Option<i128>," in q19
    q3 = emit_declarative_spec(Q3, *tpch_schema_and_catalog(customer_db))
    assert "(res@.len() == 10) ||" in q3
    assert "pub fn run_query(customer: &Cols_customer, orders: &Cols_orders, lineitem: &Cols_lineitem)" in q3


@pytest.mark.parametrize(
    ("sql", "why"),
    [
        ("select sum(l_extendedprice) / sum(l_discount) as r from lineitem where l_quantity / 2 > 1", "division"),
        ("select sum(l_extendedprice) / 2 as r from lineitem", "SUM or COUNT"),
        ("select avg(l_extendedprice) / sum(l_discount) as r from lineitem", "SUM / COUNT"),
        ("select sum(l_extendedprice) / (2 * sum(l_discount)) as r from lineitem", "denominator"),
        ("select sum(l_extendedprice) // sum(l_discount) as r from lineitem", "parse error"),
        ("select sum(l_extendedprice) / sum(l_discount) from lineitem", "alias"),
        ("select l_returnflag, sum(l_extendedprice) / sum(l_discount) as r from lineitem group by l_returnflag having r > 1", "division"),
        ("select l_returnflag, sum(l_extendedprice) / sum(l_discount) as r from lineitem group by l_returnflag order by r", "ORDER BY"),
        ("select sum(l_extendedprice) filter (where l_quantity > 5) / sum(l_discount) as r from lineitem", "SUM / COUNT"),
    ],
)
def test_division_shapes_not_stated_exactly_are_refused(tpch: tuple[dict, object], sql: str, why: str) -> None:
    with pytest.raises(DeclarativeUnsupported, match=why):
        emit_declarative_spec(sql, *tpch)


def test_a_float_operand_of_a_ratio_is_refused() -> None:
    schema = {"t": {"a": "double", "b": "double"}}
    from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

    catalog = CatalogAssumptions(
        max_rows=8,
        tables={"t": TableAssumptions(max_rows=8, columns={c: ColumnAssumption(max_value_exclusive=1000) for c in "ab"})},
    )
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec("select sum(a) / sum(b) as r from t", schema, catalog)


def test_case_like_condition_and_arithmetic_result_emit_exactly(tpch: tuple[dict, object]) -> None:
    spec = emit_declarative_spec(
        "select sum(case when p_type like 'PROMO%' then l_quantity * 2 else 0 end) as s from lineitem, part "
        "where l_partkey = p_partkey",
        *tpch,
    )
    assert "if spec_like((part.p_type@[i1]@), \"PROMO%\"@) { ((lineitem.l_quantity@[i0] as int) * 2) } else { 0int }" in spec
    neg = emit_declarative_spec(
        "select sum(case when p_type not like 'PROMO%' then l_quantity else 0 end) as s from lineitem, part where l_partkey = p_partkey",
        *tpch,
    )
    assert "!(spec_like(" in neg


@pytest.mark.parametrize(
    "sql",
    [
        "select sum(case when p_type like 'a%' escape '!' then 1 else 0 end) as s from part",
        "select sum(case when p_type like p_name then 1 else 0 end) as s from part",
        "select sum(case when p_type like 'a\"b' then 1 else 0 end) as s from part",
        "select sum(case when p_size > 1 then p_retailprice * 2 else p_retailprice * p_retailprice end) as s from part",  # scales 2 and 4
    ],
)
def test_case_forms_not_stated_exactly_are_refused(tpch: tuple[dict, object], sql: str) -> None:
    with pytest.raises(DeclarativeUnsupported):
        emit_declarative_spec(sql, *tpch)


def test_new_shape_classes_are_registered_as_witnessed() -> None:
    from declarative_spec import shapes

    for name in ("ratio", "like", "sum_case", "order_by"):
        assert shapes.REGISTRY[name].status == shapes.WITNESSED
        assert (ROOT / shapes.REGISTRY[name].witness).is_file()


# ---- Bench comparison of IEEE values (no Verus) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("got", "want", "ok"),
    [
        ("inf", float("inf"), True),
        ("-inf", float("-inf"), True),
        ("NaN", float("nan"), True),
        ("inf", float("-inf"), False),
        ("NaN", 1.0, False),
        ("1.0", float("inf"), False),
        ("1.0000000001", 1.0, True),
    ],
)
def test_row_compare_treats_ieee_non_finite_floats_like_duckdb(got: str, want: float, ok: bool) -> None:
    assert (rows_match_error([[got]], [[want]], ["float"]) is None) is ok


# ---- Verus: the reference bodies verify, wrong ones do not -------------------------------------------------------------

_MUTATIONS = {
    "tpch_q14_promo_ratio.rs": [
        ("d_acc = d_acc + val;", "d_acc = d_acc + val + 1;"),  # a wrong denominator
        ("let k1 = host_u64_to_f64(100000000);", "let k1 = host_u64_to_f64(10000000);"),  # a wrong scale
        ("v = host_f64_div_by_zero(fnum);", "v = fnum;"),  # no IEEE zero-denominator result
    ],
    "tpch_q19_disjunction.rs": [
        ("let hit = c1 || c2 || c3;", "let hit = c1 || c2;"),  # a lost disjunct
        ("&& qty >= 1000 && qty <= 2000", "&& qty >= 1000 && qty <= 2100"),  # a wrong bound
    ],
    "tpch_q3_join_group_topk.rs": [
        ("let keep = if gb == gj { db <= dj } else { gb >= gj };", "let keep = if gb == gj { db >= dj } else { gb >= gj };"),  # wrong tie order
        ("orders.o_orderdate[i1] < 9204;", "orders.o_orderdate[i1] < 9205;"),  # a wrong date bound
    ],
}
_SQL = {"tpch_q14_promo_ratio.rs": Q14, "tpch_q19_disjunction.rs": Q19, "tpch_q3_join_group_topk.rs": Q3}


def _verify(fixture: str, db: Path, mutate: tuple[str, str] | None = None) -> tuple[bool, str]:
    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.pipeline import verify_assembled
    from declarative_spec.regions import extract_agent_edit, extract_agent_helpers

    schema, catalog = tpch_schema_and_catalog(db)
    spec = emit_declarative_spec(_SQL[fixture], schema, catalog)
    text = (PROOFS / fixture).read_text()
    if mutate is not None:
        assert mutate[0] in text, mutate[0]
        text = text.replace(*mutate, 1)
    program = assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text))
    os.environ["LEMMA_VERUS_BIN"] = str(ROOT / "scripts" / "ram" / "verus_guarded.sh")
    with timing_lock("/tmp/tpch_emit_verus.lock"):
        return verify_assembled(program, timeout_sec=900)


def _db_for(fixture: str, part_db: Path, customer_db: Path) -> Path:
    return customer_db if "q3" in fixture else part_db


@needs_verus
@pytest.mark.parametrize("fixture", sorted(_SQL))
def test_reference_body_verifies(fixture: str, part_db: Path, customer_db: Path) -> None:
    ok, out = _verify(fixture, _db_for(fixture, part_db, customer_db))
    assert ok and re.search(r"verification results:: \d+ verified, 0 errors", out), out[-2500:]


@needs_verus
@pytest.mark.parametrize(
    ("fixture", "mutation"), [(f, m) for f, ms in sorted(_MUTATIONS.items()) for m in ms], ids=lambda v: v if isinstance(v, str) else ""
)
def test_wrong_body_is_rejected(fixture: str, mutation: tuple[str, str], part_db: Path, customer_db: Path) -> None:
    ok, out = _verify(fixture, _db_for(fixture, part_db, customer_db), mutation)
    assert not ok
    assert "verification results::" in out and "0 errors" not in out.split("verification results::")[1].splitlines()[0], out[-1500:]


# ---- differential: the proved program's rows against DuckDB -----------------------------------------------------------


def _matches(metrics: dict, prepared: dict) -> None:
    assert metrics["proof_verified"], str(metrics.get("compiler_error"))[-2500:]
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error")
    got = rows_from_stdout_general(metrics["stdout"])
    assert rows_match_error(got, prepared["rows"], prepared["kinds"]) is None, (got, prepared["rows"])


@needs_verus
def test_q14_promo_revenue_matches_duckdb(part_db: Path, tmp_path: Path) -> None:
    metrics, prepared = _check(Q14, part_db, "tpch_q14_promo_ratio.rs", tmp_path)
    assert prepared["rows"][0][0] not in (None, 0.0)  # the slice has promo and non-promo September 1995 rows
    _matches(metrics, prepared)


@needs_verus
def test_q19_revenue_matches_duckdb_and_uses_all_three_disjuncts(part_db: Path, tmp_path: Path) -> None:
    con = duckdb.connect(str(part_db), read_only=True)
    try:
        for brand in ("Brand#12", "Brand#23", "Brand#34"):
            hit = con.execute(
                "select count(*) from lineitem, part where p_partkey = l_partkey and p_brand = ? "
                "and l_shipmode in ('AIR','AIR REG') and l_shipinstruct = 'DELIVER IN PERSON'",
                [brand],
            ).fetchone()[0]
            assert hit > 0, brand
    finally:
        con.close()
    metrics, prepared = _check(Q19, part_db, "tpch_q19_disjunction.rs", tmp_path)
    assert prepared["rows"][0][0] is not None
    _matches(metrics, prepared)


@needs_verus
@pytest.mark.parametrize("limit", [10, 3])
def test_q3_top_groups_match_duckdb(limit: int, customer_db: Path, tmp_path: Path) -> None:
    body = (PROOFS / "tpch_q3_join_group_topk.rs").read_text()
    sql = Q3
    if limit != 10:
        sql = Q3.replace("limit 10", f"limit {limit}")
        for old, new in (
            ("while res.len() < 10 &&", f"while res.len() < {limit} &&"),
            ("res@.len() <= 10,", f"res@.len() <= {limit},"),
            ("if res@.len() != 10 {", f"if res@.len() != {limit} {{"),
        ):
            assert old in body, old
            body = body.replace(old, new)
    metrics, prepared = _run(sql, customer_db, body, tmp_path)
    assert len(prepared["rows"]) == min(limit, 7) or len(prepared["rows"]) == limit
    _matches(metrics, prepared)


# ---- a ratio with a zero denominator is IEEE, like DuckDB (tiny hand-made tables) ---------------------------------------


def _ratio_db(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    """lineitem (price, discount) rows in September 1995, all joined to one part per row; ``rows`` = (type, price, disc)."""
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE part (p_partkey BIGINT, p_type VARCHAR)")
    con.execute(
        "CREATE TABLE lineitem (l_partkey BIGINT, l_extendedprice DECIMAL(15,2), l_discount DECIMAL(15,2), l_shipdate DATE)"
    )
    for i, (ptype, price, disc) in enumerate(rows):
        con.execute("INSERT INTO part VALUES (?, ?)", [i, ptype])
        con.execute("INSERT INTO lineitem VALUES (?, ?, ?, DATE '1995-09-10')", [i, price, disc])
    con.close()
    return path


_ZERO_CASES = {
    "plus_inf": [("PROMO X", "100.00", "0.00"), ("STD", "100.00", "2.00")],  # num 10000 > 0, den 0
    "minus_inf": [("PROMO X", "100.00", "2.00"), ("STD", "100.00", "0.00")],  # num -10000, den 0
    "nan": [("STD", "100.00", "0.00"), ("STD", "100.00", "2.00")],  # num 0, den 0
    "finite": [("PROMO X", "100.00", "0.50"), ("STD", "300.00", "0.00")],
    "empty": [],  # no rows: SUM is NULL
}


@needs_verus
@pytest.mark.parametrize("case", sorted(_ZERO_CASES))
def test_ratio_zero_denominator_matches_duckdb(case: str, tmp_path: Path) -> None:
    db = _ratio_db(tmp_path / "r.duckdb", _ZERO_CASES[case])
    metrics, prepared = _run(Q14, db, (PROOFS / "tpch_q14_promo_ratio.rs").read_text(), tmp_path)
    expected = {"plus_inf": float("inf"), "minus_inf": float("-inf"), "nan": float("nan"), "empty": None}
    if case in expected:
        got_v = prepared["rows"][0][0]
        want = expected[case]
        assert (got_v is None) if want is None else (got_v == want or (want != want and got_v != got_v)), (case, got_v)
    _matches(metrics, prepared)
