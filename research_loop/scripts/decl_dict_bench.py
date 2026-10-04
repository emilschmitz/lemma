"""Speed of a proved body on plain vs dictionary-encoded string columns, against DuckDB.

    uv run python research_loop/scripts/decl_dict_bench.py sec     # SEC string filter (synthetic DECIMAL database)
    uv run python research_loop/scripts/decl_dict_bench.py tpch    # TPC-H lineitem string filter (needs a TPC-H database)

Each mode emits the spec (``LEMMA_STRING_ENCODING``), exports the column files, assembles the hand-proved
fixture body, verifies, compiles with opt-level 3 and runs the binary (it prints the median of its timed runs).
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from declarative_spec.assemble import assemble_declarative_program  # noqa: E402
from declarative_spec.emit import emit_declarative_spec  # noqa: E402
from declarative_spec.pipeline import compile_and_run  # noqa: E402
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers  # noqa: E402
from research_loop.decl_query_measure import write_query_measure  # noqa: E402

PROOFS = ROOT / "tests" / "fixtures" / "declarative_proofs"

CASES = {
    "sec": {
        "sql": "SELECT MIN(ddate) AS lo, MAX(ddate) AS hi FROM num WHERE uom = 'pure' AND qtrs = 3",
        "plain": "ungrouped_minmax_string_filter.rs",
        "dict": "dict_string_filter_minmax.rs",
    },
    "tpch": {
        "sql": "SELECT MIN(l_extendedprice) AS lo, COUNT(*) AS n FROM lineitem WHERE l_shipmode = 'AIR'",
        "plain": "tpch_shipmode_min_count_plain.rs",
        "dict": "dict_shipmode_min_count.rs",
    },
}


def context(which: str):
    if which == "sec":
        from research_loop.scripts.declarative_round import SEC_DB, sec_catalog, sec_schema

        return SEC_DB, sec_schema(), sec_catalog()
    from research_loop.scripts.declarative_round import TPCH_DB, tpch_schema_and_catalog

    schema, catalog = tpch_schema_and_catalog(TPCH_DB)
    return TPCH_DB, schema, _with_distinct(catalog, "lineitem", "l_shipmode", 16)  # TPC-H: 7 ship modes


def _with_distinct(catalog, table: str, column: str, cap: int):
    """The catalog with a distinct-value cap on one string column: the dictionary codes then fit u8."""
    import dataclasses

    from research_loop.table_assumptions import ColumnAssumption

    ta = catalog.tables[table]
    old = ta.columns.get(column, ColumnAssumption())
    cols = {**ta.columns, column: dataclasses.replace(old, max_distinct=cap)}
    return dataclasses.replace(catalog, tables={**catalog.tables, table: dataclasses.replace(ta, columns=cols)})


def run(which: str, mode: str, repeat: int) -> dict:
    os.environ["LEMMA_STRING_ENCODING"] = mode
    case = CASES[which]
    db, schema, catalog = context(which)
    spec = emit_declarative_spec(case["sql"], schema, catalog)
    with tempfile.TemporaryDirectory(prefix=f"dict-bench-{which}-{mode}-") as tmp:
        prep = write_query_measure(sql=case["sql"], schema=schema, catalog=catalog, db_path=db, dest=Path(tmp) / "cols")
        text = (PROOFS / case[mode]).read_text()
        program = assemble_declarative_program(
            spec, extract_agent_edit(text), helpers=extract_agent_helpers(text), column_bins=prep["bins"]
        )
        times = []
        for _ in range(repeat):
            metrics = compile_and_run(program, work_dir=Path(tmp) / "build") if not times else _rerun(Path(tmp) / "build")
            if metrics["status"] != "SUCCESS":
                raise SystemExit(f"{which}/{mode}: {metrics.get('compiler_error', '')[-1500:]}")
            if not times:  # the first run's printed rows must be DuckDB's rows
                from declarative_spec.bench import rows_from_stdout_general, rows_match_error

                bad = rows_match_error(rows_from_stdout_general(metrics["stdout"]), prep["rows"], prep["kinds"])
                if bad:
                    raise SystemExit(f"{which}/{mode}: result differs from DuckDB: {bad}")
            times.append(metrics["latency_us"])
    return {"mode": mode, "binary_us": statistics.median(times), "duck_us": prep["duck_us"], "duck1_us": prep["duck1_us"]}


def _rerun(build: Path) -> dict:
    import subprocess

    from declarative_spec.pipeline import _latency_us

    out = subprocess.run([str(build / "declarative_query")], capture_output=True, text=True, cwd=build, timeout=120)
    return {"status": "SUCCESS", "latency_us": _latency_us(out.stdout)}


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "sec"
    repeat = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    for mode in ("plain", "dict"):
        r = run(which, mode, repeat)
        print(
            f"{which} {mode:5s} binary {r['binary_us']:>9.0f} us   DuckDB {r['duck_us']:>9.0f} us "
            f"(1 thread {r['duck1_us']:>9.0f} us)   binary/duck {r['binary_us'] / r['duck_us']:.2f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
