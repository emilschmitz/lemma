"""Large-table measure for the declarative flag. The recursive pipeline is untouched."""

from __future__ import annotations

import subprocess
from pathlib import Path

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.bench import rows_from_stdout
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import _apply_speed_bar
from research_loop.decl_columns import write_group_count_measure
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)

_SQL = "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k"


def _catalog(*, domain: int | None) -> CatalogAssumptions:
    columns = {}
    if domain is not None:
        columns["k"] = ColumnAssumption(max_value_exclusive=domain)
    return CatalogAssumptions(
        tables={"t": TableAssumptions(max_rows=64, columns=columns)},
    )


def test_key_cap_emitted_only_when_column_is_bounded() -> None:
    capped = emit_declarative_spec(_SQL, {"t": {"k": "ubigint"}}, _catalog(domain=32))
    open_ended = emit_declarative_spec(_SQL, {"t": {"k": "ubigint"}}, _catalog(domain=None))
    assert "pub const KEY_CAP_t_k: usize = 32;" in capped
    assert "KEY_CAP_t_k" not in open_ended
    assert "lemma_index_key_below_cap" in capped
    assert "lemma_index_key_below_cap" not in open_ended


def test_key_bound_lemma_names_the_column_for_two_schemas() -> None:
    fact = emit_declarative_spec(
        "SELECT grp, COUNT(*) AS cnt FROM fact GROUP BY grp",
        {"fact": {"grp": "ubigint"}},
        CatalogAssumptions(
            tables={
                "fact": TableAssumptions(
                    max_rows=64,
                    columns={"grp": ColumnAssumption(max_value_exclusive=64)},
                )
            },
        ),
    )
    src = emit_declarative_spec(
        "SELECT slot, COUNT(*) AS c FROM src GROUP BY slot",
        {"src": {"slot": "ubigint"}},
        CatalogAssumptions(
            tables={
                "src": TableAssumptions(
                    max_rows=128,
                    columns={"slot": ColumnAssumption(max_value_exclusive=256)},
                )
            },
        ),
    )
    assert "cols.grp@[i] as int <= 63" in fact
    assert "(cols.grp@[i] as int) < (KEY_CAP_fact_grp as int)" in fact
    assert "cols.slot@[i] as int <= 255" in src
    assert "(cols.slot@[i] as int) < (KEY_CAP_src_slot as int)" in src


def test_key_bound_lemma_verifies_for_two_domains(tmp_path: Path) -> None:
    cases = (
        (
            "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k",
            {"t": {"k": "ubigint"}},
            _catalog(domain=8),
        ),
        (
            "SELECT slot, COUNT(*) AS c FROM src GROUP BY slot",
            {"src": {"slot": "ubigint"}},
            CatalogAssumptions(
                tables={
                    "src": TableAssumptions(
                        max_rows=64,
                        columns={"slot": ColumnAssumption(max_value_exclusive=256)},
                    )
                },
            ),
        ),
    )
    verus = Path("/home/emil/tools/verus/verus")
    for sql, schema, catalog in cases:
        spec = emit_declarative_spec(sql, schema, catalog)
        cut = spec.index("pub open spec fn group_count")
        src = spec[:cut].rstrip() + "\n}\n\nfn main() {}\n"
        path = tmp_path / f"{next(iter(schema))}.rs"
        path.write_text(src)
        proc = subprocess.run([str(verus), str(path)], capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "0 errors" in (proc.stdout + proc.stderr)


def test_assemble_reads_column_file_or_stays_empty() -> None:
    spec = emit_declarative_spec(_SQL, {"t": {"k": "ubigint"}}, _catalog(domain=32))
    empty = assemble_declarative_program(spec, "    let mut x: u64 = 0;\n    x\n")
    assert "vec![]" in empty
    assert "std::fs::read" not in empty
    loaded = assemble_declarative_program(
        spec,
        "    let mut x: u64 = 0;\n    x\n",
        column_bins={"t": "/tmp/cols_t.bin"},
    )
    assert 'std::fs::read("/tmp/cols_t.bin")' in loaded
    assert "QUERY_LATENCY_US:" in loaded
    assert "samples[2]" in loaded


def test_speed_bar_accepts_a_faster_match_and_rejects_a_loss() -> None:
    bar = {"duck_us": 1000, "rows": [[1, 4], [2, 6]]}
    fast = {
        "status": "SUCCESS",
        "proof_verified": True,
        "latency_us": 400,
        "stdout": "ROW 2 6\nROW 1 4\nQUERY_LATENCY_US: 400\n",
    }
    won = _apply_speed_bar(fast, bar)
    assert won["status"] == "SUCCESS"
    assert won["duck_us"] == 1000

    slow = {**fast, "latency_us": 1000}
    lost = _apply_speed_bar(slow, bar)
    assert lost["status"] == "FAILURE"
    assert "slower than DuckDB" in lost["compiler_error"]

    wrong = {**fast, "stdout": "ROW 1 4\nQUERY_LATENCY_US: 400\n"}
    mismatch = _apply_speed_bar(wrong, bar)
    assert mismatch["status"] == "FAILURE"
    assert "differ" in mismatch["compiler_error"]


def test_write_group_count_measure_matches_two_domains(tmp_path: Path) -> None:
    for domain, seed in ((8, 1), (32, 9)):
        catalog = CatalogAssumptions(
            tables={
                "t": TableAssumptions(
                    max_rows=200,
                    columns={"k": ColumnAssumption(max_value_exclusive=domain)},
                )
            },
        )
        prepared = write_group_count_measure(
            sql=_SQL,
            catalog=catalog,
            n=200,
            seed=seed,
            dest=tmp_path / f"d{domain}",
        )
        assert prepared["duck_us"] > 0
        assert rows_from_stdout(
            "".join(f"ROW {k} {v}\n" for k, v in prepared["rows"])
        ) == [(k, v) for k, v in prepared["rows"]]
        blob = Path(prepared["bin"]).read_bytes()
        assert len(blob) == 8 + 200 * 8


_DENSE_BODY = """
    broadcast use vstd::std_specs::hash::axiom_u64_obeys_hash_table_key_model;
    let mut counts: Vec<u64> = Vec::new();
    let mut c: usize = 0;
    while c < KEY_CAP_t_k
        invariant
            c <= KEY_CAP_t_k,
            counts@.len() == c as int,
            forall|j: int| 0 <= j < c as int ==> counts@[j] == 0u64,
        decreases KEY_CAP_t_k - c,
    {
        counts.push(0u64);
        c = c + 1;
    }
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols_t(cols),
            counts@.len() == KEY_CAP_t_k as int,
            forall|kk: int| 0 <= kk < KEY_CAP_t_k as int ==> counts@[kk] as int == group_count(cols.k@, i as int, kk as u64),
        decreases i,
    {
        let i_old = i;
        i = i - 1;
        let k = cols.k[i];
        let idx: usize = k as usize;
        let prev = counts[idx];
        proof {
            let keys = cols.k@;
            let start = i_old as int;
            let ii = i as int;
            assert(keys.len() == cols.n as int);
            assert(ii + 1 == start);
            assert(keys[ii] == k);
            assert(0 <= (k as int) && (k as int) < (KEY_CAP_t_k as int));
            assert(idx as int == k as int);
            lemma_group_count_le_suffix(keys, ii, k);
            lemma_group_count_le_suffix(keys, start, k);
            lemma_group_count_witness(keys, start, k);
            assert(prev as int == group_count(keys, start, k));
            assert(group_count(keys, ii, k) == group_count(keys, start, k) + 1);
            assert(prev as int + 1 <= ROW_CAP_t);
            lemma_count_step_fits_u64(prev, ROW_CAP_t);
        }
        let next = prev + 1;
        counts[idx] = next;
        proof {
            let keys = cols.k@;
            let ii = i as int;
            assert(counts@[k as int] == next);
            assert(next as int == group_count(keys, ii, k));
        }
    }
    let mut map: HashMapWithView<u64, u64> = HashMapWithView::new();
    let mut c2: usize = 0;
    while c2 < KEY_CAP_t_k
        invariant
            c2 <= KEY_CAP_t_k,
            counts@.len() == KEY_CAP_t_k as int,
            i == 0,
            forall|kk: int| 0 <= kk < KEY_CAP_t_k as int ==> counts@[kk] as int == group_count(cols.k@, 0, kk as u64),
            forall|k: u64|
                #[trigger] map@.contains_key(k) ==> k < (KEY_CAP_t_k as u64)
                    && map@[k] == counts@[k as int]
                    && counts@[k as int] > 0,
            forall|kk: int| 0 <= kk < c2 as int && counts@[kk] > 0 ==> map@.contains_key(kk as u64),
        decreases KEY_CAP_t_k - c2,
    {
        let v = counts[c2];
        let ghost before = map@;
        if v > 0 {
            map.insert(c2 as u64, v);
        }
        proof {
            assert(counts@[c2 as int] == v);
            if v > 0 {
                assert(map@ == before.insert(c2 as u64, v));
                assert(map@[c2 as u64] == v);
            }
            assert forall|k: u64|
                #[trigger] map@.contains_key(k) ==> k < (KEY_CAP_t_k as u64)
                    && map@[k] == counts@[k as int]
                    && counts@[k as int] > 0
            by {
                if map@.contains_key(k) {
                    if v > 0 && k == (c2 as u64) {
                        assert(map@[k] == v);
                        assert(counts@[c2 as int] == v);
                    } else {
                        assert(before.contains_key(k));
                        assert(map@[k] == before[k]);
                    }
                }
            };
        }
        c2 = c2 + 1;
    }
    proof {
        let keys = cols.k@;
        assert(c2 == KEY_CAP_t_k);
        assert forall|k: u64|
            #[trigger] map@.contains_key(k) <==> (exists|j: int| 0 <= j < cols.n as int && keys[j] == k)
        by {
            if map@.contains_key(k) {
                assert(counts@[k as int] as int == group_count(keys, 0, k));
                assert(counts@[k as int] > 0);
                lemma_group_count_witness(keys, 0, k);
            }
            if exists|j: int| 0 <= j < cols.n as int && keys[j] == k {
                let j = choose|j: int| 0 <= j < cols.n as int && keys[j] == k;
                assert(keys[j] == k);
                assert((k as int) < (KEY_CAP_t_k as int));
                lemma_group_count_witness(keys, 0, k);
                assert(group_count(keys, 0, k) > 0);
                assert(counts@[k as int] > 0);
                assert(map@.contains_key(k));
            }
        };
        assert forall|k: u64|
            #[trigger] map@.contains_key(k) ==> map@[k] as int == group_count(keys, 0, k)
        by {
            if map@.contains_key(k) {
                assert(map@[k] == counts@[k as int]);
                assert(counts@[k as int] as int == group_count(keys, 0, k));
            }
        };
    }
    map
"""


def test_dense_group_count_beats_duck_on_loaded_rows(tmp_path: Path) -> None:
    from declarative_spec.pipeline import run_declarative_metrics

    n = 100_000
    catalog = CatalogAssumptions(
        tables={
            "t": TableAssumptions(
                max_rows=n,
                columns={"k": ColumnAssumption(max_value_exclusive=32)},
            )
        },
    )
    spec = emit_declarative_spec(_SQL, {"t": {"k": "ubigint"}}, catalog)
    prepared = write_group_count_measure(
        sql=_SQL,
        catalog=catalog,
        n=n,
        seed=3,
        dest=tmp_path / "data",
    )
    metrics = run_declarative_metrics(
        spec_rs=spec,
        agent_source=_DENSE_BODY,
        work_dir=tmp_path / "build",
        column_bins={"t": prepared["bin"]},
        speed_bar={"duck_us": prepared["duck_us"], "rows": prepared["rows"]},
    )
    assert metrics["status"] == "SUCCESS", metrics.get("compiler_error")
    assert metrics["proof_verified"] is True
    assert 0 <= metrics["latency_us"] < prepared["duck_us"]
