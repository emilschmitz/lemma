"""The f64 idealization: float shapes are in scope, proved by Verus, and run against DuckDB within epsilon.

Trusted (see docs/TRUSTED_FAMILIES.md, "f64 idealization"): finite f64 values within the catalog caps behave
like the reals on `as real` values (add, sub, mul, div, integer casts, comparisons), rounding ignored. Every
proved body in `tests/fixtures/declarative_proofs/float_*.rs` calls those host lemmas. For each shape:

* the emitted spec has the expected float form (real arithmetic, real literals, the literal hypothesis);
* the reference body verifies (`N verified, 0 errors`) and, compiled, prints DuckDB's answer within epsilon;
* a wrong body (a flipped comparison or a dropped term) is rejected by Verus.

Float ties and near-ties: the proved side is exact in the idealization, but the machine sum differs from
DuckDB's by rounding. Test data keeps every group sum and threshold well away from a tie, and rows are
compared as a set within epsilon (never by weakening the Verus statement).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pytest

from declarative_spec.bench import rows_from_stdout_general, rows_match_error
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.lemmas import float_error_lemmas_rs
from declarative_spec.pipeline import run_declarative_metrics
from research_loop.decl_query_measure import write_query_measure
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

VERUS = Path("/home/emil/tools/verus/verus")
PROOFS = Path(__file__).parent / "fixtures" / "declarative_proofs"
EPS = "0.000001"
SCHEMA = {
    "t": {"k": "integer", "a": "double", "b": "double", "v": "double", "i": "integer", "d": "decimal(10,2)"}
}
CATALOG = CatalogAssumptions(
    max_rows=100,
    tables={
        "t": TableAssumptions(
            max_rows=100,
            columns={c: ColumnAssumption(max_value_exclusive=2**10) for c in "abvi"},
        )
    },
)
needs_verus = pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")


def _build_db(path: Path) -> None:
    rng = random.Random(11)
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (k INTEGER, a DOUBLE, b DOUBLE, v DOUBLE, i INTEGER, d DECIMAL(10,2))")
    rows = []
    for n in range(40):
        rows.append(
            (
                n % 5,
                round(rng.uniform(0.0, 9.0), 3),
                round(rng.uniform(0.0, 1.0), 3),
                round(rng.uniform(0.0, 6.0), 3),
                rng.randint(-50, 50),
                round(rng.uniform(-90.0, 90.0), 2),
            )
        )
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.close()


@dataclass(frozen=True)
class Shape:
    sql: str
    body: str
    spec_has: tuple[str, ...]
    wrong: tuple[str, str]  # (text in the body, wrong replacement): Verus must reject it


SHAPES: dict[str, Shape] = {
    "filter_count": Shape(
        "SELECT COUNT(*) AS c FROM t WHERE v > 1.5",
        "float_filter_count",
        ("(t.v@[i0] as real) > (15real / 10real)", "(1.5f64 as real) == (3real / 2real)"),
        ("let gt = v > 1.5;", "let gt = v < 1.5;"),
    ),
    "min_max": Shape(
        "SELECT MAX(v) AS mx, MIN(v) AS mn FROM t",
        "float_min_max",
        ("pub open spec fn max_mx(t: &Cols_t, bound: real)", "pub open spec fn min_mn(t: &Cols_t, bound: real)"),
        ("let bigger = v > hi;", "let bigger = v < hi;"),
    ),
    "product_sum": Shape(
        "SELECT SUM(a * (1 - b)) AS s FROM t",
        "float_product_sum",
        ("(t.a@[i0] as real) * ((1real - (t.b@[i0] as real)))", "(1.0f64 as real) == (1real / 1real)"),
        ("let p = a * om;", "let p = a + om;"),
    ),
    "group_sum_having": Shape(
        "SELECT k, SUM(v) AS s FROM t GROUP BY k HAVING SUM(v) > 10",
        "float_group_sum_having",
        ("sum_s(t, 0, (row.k as int)) > 10real", "(10.0f64 as real) == (10real / 1real)"),
        ("let big = acc > 10.0;", "let big = acc > 100.0;"),
    ),
    "order_by_limit": Shape(
        "SELECT v FROM t ORDER BY v LIMIT 3",
        "float_order_limit",
        ("pub open spec fn proj_key(t: &Cols_t, i0: int) -> real", "(res@[i].v as real)) <= ((res@[i + 1].v as real)"),
        ("let less = vj < vb;", "let less = vj > vb;"),
    ),
    "group_sum_order_limit": Shape(
        "SELECT k, SUM(v) AS s FROM t GROUP BY k ORDER BY s DESC LIMIT 2",
        "float_group_sum_order_limit",
        ("((res@[i].s as real)) >= ((res@[i + 1].s as real))", "res@.len() <= 2"),
        ("let more = gj > gb;", "let more = gj < gb;"),
    ),
    "sum_eps": Shape(
        "SELECT SUM(v) AS s FROM t",
        "float_sum_eps",
        ("(t.v@[i0] as real)", "abs_real(((res@[r].s->Some_0 as real)) - sum_s(t, 0)) <= (FLOAT_ABS_EPS as real)"),
        ("let next = acc + x;", "let next = x + x;"),
    ),
    "avg_int": Shape(
        "SELECT AVG(i) AS m FROM t",
        "float_avg_int",
        ("(((t.i@[i0] as int)) as real)", "avg_m_sum(t, i0) / (c as real)"),
        ("let avg = fs / fc;", "let avg = fs / fs;"),
    ),
    "avg_float": Shape(
        "SELECT AVG(v) AS m FROM t",
        "float_avg_float",
        ("(t.v@[i0] as real)", "avg_m_sum(t, i0) / (c as real)"),
        ("let avg = acc / fc;", "let avg = fc / fc;"),
    ),
    "avg_decimal": Shape(
        "SELECT AVG(d) AS m FROM t",
        "float_avg_decimal",
        ("(((((t.d@[i0] as int)) as real)) / 100real)",),
        ("let mean_scaled = fs / fscale;", "let mean_scaled = fs / fc;"),
    ),
    "group_avg_having": Shape(
        "SELECT k, AVG(v) AS m FROM t GROUP BY k HAVING AVG(v) > 2",
        "float_group_avg_having",
        ("avg_m(t, 0, (row.k as int)) > 2real",),
        ("let big = avg > 2.0;", "let big = avg > 20.0;"),
    ),
    "group_avg_decimal": Shape(
        "SELECT k, AVG(d) AS m FROM t GROUP BY k",
        "float_group_avg_decimal",
        ("/ 100real",),
        ("let avg = mean_scaled / fc;", "let avg = mean_scaled / fscale;"),
    ),
}


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("floatdb") / "t.duckdb"
    _build_db(path)
    return path


def _run(db: Path, tmp: Path, shape: Shape, mutate: tuple[str, str] | None = None) -> tuple[dict, dict]:
    prepared = write_query_measure(
        sql=shape.sql, schema=SCHEMA, catalog=CATALOG, db_path=db, dest=tmp / "data", float_abs_eps=EPS
    )
    spec = emit_declarative_spec(shape.sql, SCHEMA, CATALOG, float_abs_eps=EPS)
    source = (PROOFS / f"{shape.body}.rs").read_text()
    if mutate is not None:
        old, new = mutate
        assert old in source, old
        source = source.replace(old, new, 1)
    metrics = run_declarative_metrics(
        spec_rs=spec, agent_source=source, work_dir=tmp / "run", column_bins=prepared["bins"]
    )
    return metrics, prepared


@pytest.mark.parametrize("name", list(SHAPES))
def test_spec_states_the_float_query_over_reals(name: str) -> None:
    shape = SHAPES[name]
    spec = emit_declarative_spec(shape.sql, SCHEMA, CATALOG, float_abs_eps=EPS)
    for text in shape.spec_has:
        assert text in spec, text
    assert "f64_literals_ok()" in spec.split("pub fn run_query(")[1].split("ensures")[0]
    assert "// HYPOTHESIS (f64 idealization)" in spec


@needs_verus
@pytest.mark.parametrize("name", list(SHAPES))
def test_float_shape_proves_runs_and_matches_duckdb_within_epsilon(name: str, db: Path, tmp_path: Path) -> None:
    metrics, prepared = _run(db, tmp_path, SHAPES[name])
    assert metrics["proof_verified"], str(metrics.get("compiler_error"))[-2500:]
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error")
    got = rows_from_stdout_general(metrics["stdout"])
    assert got
    assert rows_match_error(got, prepared["rows"], prepared["kinds"], EPS) is None


@needs_verus
@pytest.mark.parametrize("name", list(SHAPES))
def test_wrong_float_body_is_rejected(name: str, db: Path, tmp_path: Path) -> None:
    shape = SHAPES[name]
    metrics, _prepared = _run(db, tmp_path, shape, shape.wrong)
    assert not metrics["proof_verified"]
    assert "verification results::" in str(metrics.get("compiler_error")), str(metrics.get("compiler_error"))[-1500:]


def test_trusted_float_code_is_exactly_these_items() -> None:
    from declarative_spec.lemmas import host_float_lemmas_rs

    rust = host_float_lemmas_rs()
    names = [
        part.lstrip().splitlines()[0].split("fn ")[1].split("(")[0]
        for part in rust.split("#[verifier::external_body]")[1:]
    ]
    assert names == [
        "lemma_f64_left_fold_empty",
        "lemma_f64_add_defined",
        "lemma_f64_left_fold_push",
        "lemma_f64_sum_within_eps",
        "lemma_f64_sub_defined",
        "lemma_f64_mul_defined",
        "lemma_f64_add_real",
        "lemma_f64_sub_real",
        "lemma_f64_mul_real",
        "lemma_f64_div_defined",
        "lemma_f64_div_real",
        "lemma_f64_lt_real",
        "lemma_f64_le_real",
        "lemma_f64_gt_real",
        "lemma_f64_ge_real",
        "lemma_f64_eq_real",
        "lemma_f64_add_exact",
        "lemma_f64_sub_exact",
        "lemma_f64_mul_exact",
        "host_u64_to_f64_exact",
        "host_i128_to_f64_exact",
    ]
    # The idealized casts (false above 2^53) are gone: only the exact casts remain.
    assert "pub fn host_u64_to_f64(" not in rust and "pub fn host_i128_to_f64(" not in rust
    assert rust.count("// TRUSTED (f64") >= len(names) - 1
