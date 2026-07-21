"""Basic SQL batch-1: verify honest ACCEPT, adversarial REJECT, DuckDB correctness."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
VERUS_SRC = ROOT / "verus" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(VERUS_SRC) not in sys.path:
    sys.path.insert(0, str(VERUS_SRC))

from verus.research_loop.basic_sql_fixtures import BASIC_SQL_FIXTURES  # noqa: E402
from verus.research_loop.harness import resolve_verus_bin  # noqa: E402

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
from test_adversarial_runquery import (  # noqa: E402
    assemble_verified_program_source,
    compile_and_run_verified_program,
    verify_assembled_run_query,
)

TINY_SCALAR_ROWS: list[tuple[int, int]] = [
    (10, 2),
    (20, 0),
    (30, 5),
    (7, 1),
    (100, 3),
]

TINY_LIKE_ROWS: list[tuple[int, str]] = [
    (10, "Alpha"),
    (20, "Beta"),
    (30, "Apple"),
    (5, "A"),
    (15, "Apricot"),
]

TINY_HAVING_ROWS: list[tuple[int, str, int]] = [
    (1, "a", 8),
    (1, "a", 5),
    (2, "b", 12),
    (1, "b", 3),
    (3, "c", 20),
]


def write_pipe_tbl(
    path: str,
    columns: list[str],
    rows: list[tuple[object, ...]],
) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("|".join(columns) + "\n")
        for row in rows:
            cells: list[str] = []
            for val in row:
                if isinstance(val, str):
                    cells.append(f'"{val}"')
                else:
                    cells.append(str(val))
            f.write("|".join(cells) + "\n")


def duckdb_scalar(sql: str, tbl_path: str) -> int:
    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE t AS SELECT * FROM read_csv('{tbl_path}', delim='|', header=true)"
    )
    row = con.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


def duckdb_groupby_map_len_checksum(sql: str, tbl_path: str) -> tuple[int, int]:
    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE t AS SELECT * FROM read_csv('{tbl_path}', delim='|', header=true)"
    )
    rows = con.execute(sql).fetchall()
    checksum = 0
    for *_keys, total in rows:
        checksum = (checksum + int(total)) % (1 << 64)
    return len(rows), checksum


def parse_scalar_result(stdout: str) -> int:
    m = re.search(r"RESULT:\s*(\d+)", stdout)
    if not m:
        raise ValueError(f"no scalar RESULT in output: {stdout!r}")
    return int(m.group(1))


def parse_groupby_result(stdout: str) -> tuple[int, int]:
    m = re.search(r"RESULT:\s*map_len=(\d+)\s+checksum=(\d+)", stdout)
    if not m:
        raise ValueError(f"no group-by RESULT in output: {stdout!r}")
    return int(m.group(1)), int(m.group(2))


_ADVERSARIAL_BODIES: dict[str, dict[str, str]] = {
    "min": {
        "wrong_filter": """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = u64::MAX;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let y = cols.get_y_exec(i);
        if y < 1 {
            let x = cols.get_x_exec(i);
            if x < res { res = x; }
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}""",
    },
    "max": {
        "wrong_agg": """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let x = cols.get_x_exec(i);
            if x < res { res = x; }
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}""",
    },
    "avg": {
        "wrong_count": """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut sum: u64 = 0;
    let mut count: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            sum == sum_helper(cols, i as int),
            count == count_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let x = cols.get_x_exec(i);
            sum = add_u64(sum, x);
            count = add_u64(count, 2);
        }
    }
    if count == 0 { 0 } else { sum / count }
}""",
    },
    "in_list": {
        "wrong_filter": """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let y = cols.get_y_exec(i);
        if y == 1 || y == 2 {
            let x = cols.get_x_exec(i);
            res = add_u64(res, x);
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}""",
    },
    "like_prefix": {
        "wrong_filter": """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let s = cols.get_s_exec(i);
        if s.starts_with("B") {
            let x = cols.get_x_exec(i);
            res = add_u64(res, x);
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}""",
    },
    "having": {
        "wrong_having": """\
pub exec fn run_query(cols: &Cols) -> (res: HashMap<(u32, String), u64>)
    requires valid_cols(cols),
    ensures hashmap_u32_str_u64_view(res@) == method_spec(cols),
{
    let mut agg = agg_new_u32_str_u64();
    let mut i: usize = cols.n;
    let ghost mut g: Map<(u32, Seq<char>), u64> = Map::empty();
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            g == method_spec_helper(cols, i as int),
            hashmap_u32_str_u64_view(agg@) == g,
        decreases i,
    {
        i = i - 1;
        {
            let k = cols.get_k_exec(i);
            let s = cols.get_s_exec(i);
            let v = cols.get_v_exec(i);
            agg_add_u32_str_u64(&mut agg, k, &s, v);
            proof {
                let ghost old_g = g;
                let key = (k, s@);
                let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                g = old_g.insert(key, (prev as int + v as int) as u64);
                assert(hashmap_u32_str_u64_view(agg@) == g);
            }
        }
        assert(g == method_spec_helper(cols, i as int) && hashmap_u32_str_u64_view(agg@) == g);
    }
    agg
}""",
    },
}


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestBasicSqlBatch1Verify(unittest.TestCase):
    def test_honest_fixtures_accept(self) -> None:
        for key, fx in BASIC_SQL_FIXTURES.items():
            with self.subTest(feature=key):
                ok = verify_assembled_run_query(
                    schema=fx.schema,
                    sql=fx.sql,
                    run_query_body=fx.run_query,
                    ret_type=fx.ret_type,
                )
                self.assertTrue(ok, f"honest {key} should verify")

    def test_adversarial_fixtures_reject(self) -> None:
        for key, bodies in _ADVERSARIAL_BODIES.items():
            fx = BASIC_SQL_FIXTURES[key]
            for case, body in bodies.items():
                with self.subTest(feature=key, case=case):
                    ok = verify_assembled_run_query(
                        schema=fx.schema,
                        sql=fx.sql,
                        run_query_body=body,
                        ret_type=fx.ret_type,
                    )
                    self.assertFalse(ok, f"{key}/{case} should be rejected")


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestBasicSqlBatch1DuckDB(unittest.TestCase):
    def test_scalar_features_match_duckdb(self) -> None:
        cases = [
            ("min", TINY_SCALAR_ROWS, ["X", "Y"], duckdb_scalar),
            ("max", TINY_SCALAR_ROWS, ["X", "Y"], duckdb_scalar),
            ("avg", TINY_SCALAR_ROWS, ["X", "Y"], duckdb_scalar),
            ("in_list", TINY_SCALAR_ROWS, ["X", "Y"], duckdb_scalar),
        ]
        for key, rows, cols, duck_fn in cases:
            fx = BASIC_SQL_FIXTURES[key]
            with self.subTest(feature=key):
                with tempfile.TemporaryDirectory() as tmp:
                    tbl = os.path.join(tmp, f"{key}.tbl")
                    write_pipe_tbl(tbl, cols, rows)
                    expected = duck_fn(fx.sql, tbl)
                    program = assemble_verified_program_source(
                        schema=fx.schema,
                        sql=fx.sql,
                        run_query_body=fx.run_query,
                        ret_type=fx.ret_type,
                        default_tbl=tbl,
                    )
                    ok, out = compile_and_run_verified_program(program, tbl)
                    self.assertTrue(ok, out)
                    self.assertEqual(parse_scalar_result(out), expected)

    def test_like_prefix_matches_duckdb(self) -> None:
        fx = BASIC_SQL_FIXTURES["like_prefix"]
        with tempfile.TemporaryDirectory() as tmp:
            tbl = os.path.join(tmp, "like.tbl")
            write_pipe_tbl(tbl, ["X", "S"], TINY_LIKE_ROWS)
            expected = duckdb_scalar(fx.sql, tbl)
            program = assemble_verified_program_source(
                schema=fx.schema,
                sql=fx.sql,
                run_query_body=fx.run_query,
                ret_type=fx.ret_type,
                default_tbl=tbl,
            )
            ok, out = compile_and_run_verified_program(program, tbl)
            self.assertTrue(ok, out)
            self.assertEqual(parse_scalar_result(out), expected)

    def test_having_matches_duckdb(self) -> None:
        fx = BASIC_SQL_FIXTURES["having"]
        with tempfile.TemporaryDirectory() as tmp:
            tbl = os.path.join(tmp, "having.tbl")
            write_pipe_tbl(tbl, ["K", "S", "V"], TINY_HAVING_ROWS)
            expected_len, expected_checksum = duckdb_groupby_map_len_checksum(
                fx.sql, tbl
            )
            program = assemble_verified_program_source(
                schema=fx.schema,
                sql=fx.sql,
                run_query_body=fx.run_query,
                ret_type=fx.ret_type,
                default_tbl=tbl,
            )
            ok, out = compile_and_run_verified_program(program, tbl)
            self.assertTrue(ok, out)
            actual_len, actual_checksum = parse_groupby_result(out)
            self.assertEqual(actual_len, expected_len)
            self.assertEqual(actual_checksum, expected_checksum)


if __name__ == "__main__":
    unittest.main()
