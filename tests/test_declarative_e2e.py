"""Declarative group-by count verifies; recursive mode still emits the walk."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.admit import admit_declarative_body
from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.lemmas import float_error_lemmas_rs
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)
from verus_transpiler import transpile_sql_to_verus

VERUS = Path("/home/emil/tools/verus/verus")

_COUNT_SQL = "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k"
_COUNT_BODY = """
    let mut i: usize = cols.n;
    let mut map: HashMapWithView<u64, u64> = HashMapWithView::new();
    while i > 0
        invariant
            i <= cols.n,
            valid_cols_t(cols),
            forall|k: u64|
                #[trigger] map@.contains_key(k) <==> (exists|j: int|
                    i as int <= j < cols.n as int && cols.k@[j] == k),
            forall|k: u64|
                map@.contains_key(k) ==> map@[k] as int == group_count(cols.k@, i as int, k),
        decreases i,
    {
        let i_old = i;
        proof {
            let keys = cols.k@;
            let start = i_old as int;
            assert(keys.len() == cols.n as int);
            assert(0 < start);
            assert(0 <= ROW_CAP_t <= u64::MAX as int);
        }
        i = i - 1;
        let k = cols.k[i];
        let prev: u64 = if map.contains_key(&k) {
            *map.get(&k).unwrap()
        } else {
            0
        };
        proof {
            let keys = cols.k@;
            let start = i_old as int;
            let ii = i as int;
            assert(ii + 1 == start);
            assert(keys[ii] == k);
            assert(keys.len() == cols.n as int);
            lemma_group_count_le_suffix(keys, ii, k);
            lemma_group_count_le_suffix(keys, start, k);
            lemma_group_count_witness(keys, start, k);
            if map@.contains_key(k) {
                assert(prev as int == group_count(keys, start, k));
                assert(group_count(keys, ii, k) == group_count(keys, start, k) + 1);
                assert(prev as int + 1 == group_count(keys, ii, k));
                assert(group_count(keys, ii, k) <= keys.len() - ii);
                assert(prev as int + 1 <= ROW_CAP_t);
            } else {
                assert(!(exists|j: int| start <= j < keys.len() && keys[j] == k));
                assert(!(group_count(keys, start, k) > 0));
                assert(group_count(keys, start, k) == 0);
                assert(group_count(keys, ii, k) == 1);
                assert(prev == 0);
                assert(prev as int + 1 <= ROW_CAP_t);
            }
            lemma_count_step_fits_u64(prev, ROW_CAP_t);
            assert((prev + 1) as int == prev as int + 1);
        }
        let next = prev + 1;
        map.insert(k, next);
        proof {
            let keys = cols.k@;
            let ii = i as int;
            assert(next as int == group_count(keys, ii, k));
        }
    }
    map
"""

_FOLD_FN = """
pub const FLOAT_ABS_EPS: f64 = 0.000001f64;
pub open spec const MAG: int = 10;

fn fold_f64(xs: &Vec<f64>) -> (acc: f64)
    requires
        xs@.len() <= 4,
        forall|i: int| 0 <= i < xs@.len() ==> {
            let r = #[trigger] (xs@[i] as real);
            let cap = MAG as real;
            -cap < r && r < cap
        },
        host_f64_sum_error(xs@.len() as int, MAG) <= (FLOAT_ABS_EPS as real),
    ensures
        abs_real((acc as real) - real_sum_seq(xs@)) <= (FLOAT_ABS_EPS as real),
{
    let mut acc: f64 = 0.0;
    let mut i: usize = 0;
    proof {
        lemma_f64_left_fold_empty();
        assert(xs@.take(0) == Seq::<f64>::empty());
    }
    while i < xs.len()
        invariant
            i <= xs.len(),
            xs@.len() <= 4,
            acc == f64_left_fold(xs@.take(i as int)),
            forall|j: int| 0 <= j < xs@.len() ==> {
                let r = #[trigger] (xs@[j] as real);
                let cap = MAG as real;
                -cap < r && r < cap
            },
            host_f64_sum_error(xs@.len() as int, MAG) <= (FLOAT_ABS_EPS as real),
        decreases xs.len() - i,
    {
        let x = xs[i];
        let prev = acc;
        proof { lemma_f64_add_defined(prev, x); }
        let next = prev + x;
        proof {
            assert(x == xs@[i as int]);
            lemma_f64_left_fold_push(xs@.take(i as int), x, prev, next);
            assert(xs@.take((i + 1) as int) =~= xs@.take(i as int).push(x));
            assert(next == f64_left_fold(xs@.take((i + 1) as int)));
        }
        acc = next;
        i = i + 1;
    }
    proof {
        assert(xs@.take(xs@.len() as int) =~= xs@);
        assert(acc == f64_left_fold(xs@));
        lemma_f64_sum_within_eps(acc, xs@.len() as int, MAG, FLOAT_ABS_EPS, xs@);
    }
    acc
}
"""


def _run_verus(src: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(src)
        path = f.name
    proc = subprocess.run(
        [str(VERUS), path, "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    return proc.stdout + "\n" + proc.stderr


def test_declarative_group_count_verifies_with_fit_lemma() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    catalog = CatalogAssumptions(tables={"t": TableAssumptions(max_rows=64)})
    spec = emit_declarative_spec(
        _COUNT_SQL,
        {"t": {"k": "ubigint"}},
        catalog,
    )
    assert "HashMapWithView<u64, u64>" in spec
    assert "group_count" in spec
    assert "method_spec" not in spec
    admission = admit_declarative_body(_COUNT_BODY)
    assert admission.ok, admission.violations
    assert "assume(" not in _COUNT_BODY
    assert "lemma_count_step_fits_u64" in _COUNT_BODY
    program = assemble_declarative_program(spec, _COUNT_BODY)
    assert program.index("fn main()") > program.index("fn load_cols_t")
    assert "Instant::now()" in program
    assert "QUERY_LATENCY_US:" in program
    out = _run_verus(program)
    assert "verification results::" in out, out
    assert "0 errors" in out, out


def test_float_sum_spec_is_real_and_accumulator_calls_host_lemma() -> None:
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    catalog = CatalogAssumptions(
        tables={
            "t": TableAssumptions(
                max_rows=8,
                columns={"v": ColumnAssumption(max_value_exclusive=10)},
            ),
            "u": TableAssumptions(
                max_rows=8,
                unique_keys=(("a",),),
            ),
        }
    )
    spec = emit_declarative_spec(
        "SELECT u.g, SUM(t.v) AS total FROM t JOIN u ON t.a = u.a GROUP BY u.g",
        {
            "t": {"a": "integer", "v": "double"},
            "u": {"a": "integer", "g": "integer"},
        },
        catalog,
        float_abs_eps="0.000001",
    )
    assert "matched_real_sum" in spec
    assert "as real" in spec
    assert "FLOAT_ABS_EPS" in spec
    assert "Vec<f64>" in spec
    assert "method_spec" not in spec
    src = (
        "use vstd::prelude::*;\nverus! {\n"
        + float_error_lemmas_rs()
        + "\n"
        + _FOLD_FN
        + "\n}\nfn main() {}\n"
    )
    assert "0.000001" not in _FOLD_FN.split("fn fold_f64", 1)[1]
    out = _run_verus(src)
    assert "0 errors" in out, out


def test_recursive_mode_emits_walk_without_declarative_emitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)

    def _boom(*_args, **_kwargs):
        raise AssertionError("declarative emitter must not run")

    monkeypatch.setattr("declarative_spec.emit.emit_declarative_spec", _boom)
    out = transpile_sql_to_verus(
        _COUNT_SQL,
        {"t": {"k": "bigint"}},
        catalog_assumptions=CatalogAssumptions(max_rows=1000),
    )
    assert "method_spec" in out
    assert ".insert(" in out


def test_declarative_flag_compiles_and_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Production harness entry: the flag compiles the proved body and runs it."""
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")

    def _old_pipeline(*_args, **_kwargs):
        raise AssertionError("recursive pipeline must not run when LEMMA_SPEC_STYLE=declarative")

    monkeypatch.setenv("LEMMA_SPEC_STYLE", "declarative")
    monkeypatch.setattr("research_loop.harness.run_custom_sql_pipeline", _old_pipeline)

    catalog = CatalogAssumptions(tables={"t": TableAssumptions(max_rows=64)})
    spec = emit_declarative_spec(_COUNT_SQL, {"t": {"k": "ubigint"}}, catalog)
    agent = spec.replace(
        "// AGENT_EDIT_START\n// AGENT_EDIT_END",
        "// AGENT_EDIT_START\n" + _COUNT_BODY + "\n// AGENT_EDIT_END",
    )
    ro = tmp_path / "context" / "ro"
    ro.mkdir(parents=True)
    (ro / "spec.rs").write_text(spec)
    agent_path = tmp_path / "runquery_agent.rs"
    agent_path.write_text(agent)

    from db_extension.verus_bridge import invoke_verus_custom_pipeline

    metrics = invoke_verus_custom_pipeline(
        sql=_COUNT_SQL,
        schema={"t": {"k": "ubigint"}},
        runquery_path=agent_path,
    )
    assert metrics["proof_verified"], metrics.get("compiler_error")
    assert metrics["status"] == "SUCCESS"
    assert metrics["latency_us"] >= 0


def test_declarative_mcp_run_solution_compiles_and_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The Docker agent's run_runquery uses the declarative compiler, not method_spec."""
    if not VERUS.is_file():
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_SPEC_STYLE", "declarative")
    catalog = CatalogAssumptions(tables={"t": TableAssumptions(max_rows=64)})
    spec = emit_declarative_spec(_COUNT_SQL, {"t": {"k": "ubigint"}}, catalog)
    agent = spec.replace(
        "// AGENT_EDIT_START\n// AGENT_EDIT_END",
        "// AGENT_EDIT_START\n" + _COUNT_BODY + "\n// AGENT_EDIT_END",
    )
    ro = tmp_path / "context" / "ro"
    ro.mkdir(parents=True)
    (ro / "spec.rs").write_text(spec)
    (ro / "query.sql").write_text(_COUNT_SQL + "\n")
    (ro / "schema.json").write_text('{"t": {"k": "ubigint"}}\n')
    (tmp_path / "runquery_agent.rs").write_text(agent)

    from db_extension.agent.measure_core import run_solution

    out = run_solution(
        path="runquery_agent.rs",
        query_id=1,
        dataset_size=8,
        ws=tmp_path,
        sql=_COUNT_SQL,
        schema={"t": {"k": "ubigint"}},
    )
    assert out["ok"], out.get("errors")
    assert out["metrics"]["proof_verified"]
    assert out["metrics"]["latency_us"] >= 0
    assert "method_spec" not in " ".join(out.get("errors") or [])
