"""SQL oracle: DuckDB on tiny .tbl data must match honest verified run_query binary."""

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

from verus.research_loop.harness import resolve_verus_bin  # noqa: E402

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
from test_adversarial_runquery import (  # noqa: E402
    GROUPBY_SCHEMA,
    GROUPBY_SQL,
    HONEST_GROUPBY_BODY,
    HONEST_SCALAR_BODY,
    SCALAR_SCHEMA,
    SCALAR_SQL,
    assemble_verified_program_source,
    compile_and_run_verified_program,
)

SCALAR_ROWS: list[tuple[int, int]] = [
    (10, 2),
    (20, 0),
    (30, 5),
    (7, 1),
]

GROUPBY_ROWS: list[tuple[int, str, int]] = [
    (1, "a", 10),
    (1, "a", 5),
    (2, "b", 7),
    (1, "b", 3),
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


def duckdb_scalar_sum(sql: str, tbl_path: str) -> int:
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
    for _k, _s, total in rows:
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


@unittest.skipUnless(resolve_verus_bin(), "verus binary not found")
class TestSqlOracle(unittest.TestCase):
    def test_scalar_honest_exec_matches_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tbl = os.path.join(tmp, "scalar.tbl")
            write_pipe_tbl(tbl, ["X", "Y"], SCALAR_ROWS)
            expected = duckdb_scalar_sum(SCALAR_SQL, tbl)

            program = assemble_verified_program_source(
                schema=SCALAR_SCHEMA,
                sql=SCALAR_SQL,
                run_query_body=HONEST_SCALAR_BODY,
                ret_type="u64",
                default_tbl=tbl,
            )
            ok, out = compile_and_run_verified_program(program, tbl)
            self.assertTrue(ok, out)
            actual = parse_scalar_result(out)
            self.assertEqual(actual, expected)

    def test_groupby_honest_exec_matches_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tbl = os.path.join(tmp, "groupby.tbl")
            write_pipe_tbl(tbl, ["K", "S", "V"], GROUPBY_ROWS)
            expected_len, expected_checksum = duckdb_groupby_map_len_checksum(
                GROUPBY_SQL, tbl
            )

            program = assemble_verified_program_source(
                schema=GROUPBY_SCHEMA,
                sql=GROUPBY_SQL,
                run_query_body=HONEST_GROUPBY_BODY,
                ret_type="map_u32_str_u64",
                default_tbl=tbl,
            )
            ok, out = compile_and_run_verified_program(program, tbl)
            self.assertTrue(ok, out)
            actual_len, actual_checksum = parse_groupby_result(out)
            self.assertEqual(actual_len, expected_len)
            self.assertEqual(actual_checksum, expected_checksum)


if __name__ == "__main__":
    unittest.main()
