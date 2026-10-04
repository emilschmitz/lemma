"""Second adversary review of NULL support (manual adversary, Sonnet subagent): confirmation of the two fixes plus the
dictionary + nullable and join-key-cap attacks. Verdict: "Second review" in research_loop/menus/nulls_ADVERSARY_VERDICT.md.
"""

from __future__ import annotations

import os
import re
import struct

import duckdb
import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.schema_types import SchemaModel
from research_loop.decl_query_measure import _export_table
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions
from tests.null_differential import SCHEMA, accepted, assert_equivalent, differs

# ---- (1) BETWEEN / NOT BETWEEN ---------------------------------------------------------------------------------------------

BETWEEN = [
    "SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND 0",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND b",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT BETWEEN b AND 0",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN 0 AND b",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT BETWEEN b AND x",
    "SELECT COUNT(*) AS c FROM t WHERE x BETWEEN a AND b",
    "SELECT COUNT(*) AS c FROM t WHERE x BETWEEN a AND 2",
    "SELECT COUNT(*) AS c FROM t WHERE x BETWEEN 1 AND b",
    "SELECT COUNT(*) AS c FROM t WHERE a BETWEEN b AND x",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (x BETWEEN a AND 0)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (x NOT BETWEEN a AND b)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a BETWEEN b AND x)",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND 0 AND b > 0",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND 0 OR b IS NULL",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (x NOT BETWEEN a AND 0 OR b > 1)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (x BETWEEN a AND b AND NOT (a > 1))",
    "SELECT COUNT(*) AS c FROM t WHERE (x NOT BETWEEN a AND 1) AND (x NOT BETWEEN 2 AND b)",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND b OR x BETWEEN b AND a",
    "SELECT SUM(x) AS s FROM t WHERE x NOT BETWEEN a AND b",
    "SELECT x, COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND 1 GROUP BY x",
    "SELECT COUNT(*) AS c FROM t WHERE s NOT BETWEEN 'a' AND 'x' OR s IS NULL" if False else "SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND a",
]


@pytest.mark.parametrize("sql", BETWEEN)
def test_between_families_match_duckdb(sql: str) -> None:
    assert_equivalent(sql, trials=200)


def test_witness_null_bound_keeps_the_row() -> None:
    """a NULL, x = 5: `x NOT BETWEEN a AND 0` is TRUE, the spec's row_hit must keep the row."""
    con = duckdb.connect()
    con.execute("CREATE TABLE t (id BIGINT, a BIGINT, x BIGINT)")
    con.execute("INSERT INTO t VALUES (0, NULL, 5), (1, NULL, NULL), (2, 1, 5)")
    assert con.execute("SELECT COUNT(*) FROM t WHERE x NOT BETWEEN a AND 0").fetchone() == (2,)
    spec = emit_declarative_spec("SELECT COUNT(*) AS c FROM t WHERE x NOT BETWEEN a AND 0", SCHEMA, __import__("tests.null_differential", fromlist=["CAT"]).CAT)
    row_hit = spec.split("spec fn row_hit")[1].split("\n}")[0]
    # not a flat `a IS NOT NULL AND ...`: the high side (x > 0) alone settles it
    assert "||" in row_hit


# ---- (2) NOT IN subquery ------------------------------------------------------------------------------------------------------

NOT_IN = [
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT k FROM u WHERE k > 100)",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT k FROM u)",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT k FROM u WHERE k > 1)",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a IN (SELECT k FROM u WHERE m > 100))",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a IN (SELECT k FROM u))",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (NOT (a NOT IN (SELECT k FROM u WHERE k > 1)))",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT m FROM u WHERE m IS NOT NULL)",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT m FROM u WHERE m IS NOT NULL AND m > 5)",
    "SELECT COUNT(*) AS c FROM t WHERE a IN (SELECT m FROM u WHERE m IS NOT NULL)",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT k FROM u WHERE k > 1) OR b > 1",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT k FROM u WHERE k > 1) AND b IS NULL",
    "SELECT COUNT(*) AS c FROM t WHERE NOT (a NOT IN (SELECT k FROM u WHERE k > 1) OR b > 1)",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT k FROM u WHERE k > t.x)",
    "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT k FROM u WHERE k = t.id)",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT IN (SELECT k FROM u WHERE k > 100)",
    "SELECT COUNT(*) AS c FROM t WHERE x NOT IN (SELECT m FROM u WHERE m IS NOT NULL)",
    "SELECT SUM(x) AS s FROM t WHERE a NOT IN (SELECT k FROM u WHERE k > 1)",
]


@pytest.mark.parametrize("sql", NOT_IN)
def test_not_in_subquery_families_match_duckdb(sql: str) -> None:
    assert_equivalent(sql, trials=200)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT m FROM u)",  # nullable column selected, not proven
        "SELECT COUNT(*) AS c FROM t WHERE x NOT IN (SELECT m FROM u)",
        "SELECT COUNT(*) AS c FROM t WHERE a IN (SELECT m FROM u)",
        "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT NULL FROM u)",
        "SELECT COUNT(*) AS c FROM t WHERE a NOT IN (SELECT m FROM u WHERE m > 100 OR m IS NULL)",
    ],
)
def test_a_subquery_that_can_return_null_is_refused_so_not_in_never_keeps_rows_wrongly(sql: str) -> None:
    """`x NOT IN (... NULL ...)` is never TRUE: the emitter refuses a subquery whose column is not proven non-NULL."""
    assert not accepted(sql)


def test_not_in_with_a_null_in_the_list_is_never_true() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (x BIGINT)")
    con.execute("INSERT INTO t VALUES (1), (5)")
    con.execute("CREATE TABLE u (m BIGINT)")
    con.execute("INSERT INTO u VALUES (1), (NULL)")
    assert con.execute("SELECT COUNT(*) FROM t WHERE x NOT IN (SELECT m FROM u)").fetchone() == (0,)


# ---- (3) dictionary + nullable ---------------------------------------------------------------------------------------------

DSCHEMA = {"t": {"id": "bigint", "s": "varchar", "g": "varchar"}, "u": {"k": "varchar", "w": "bigint"}}
DCAT = CatalogAssumptions(
    max_rows=64,
    tables={
        "t": TableAssumptions(max_rows=64, columns={"s": ColumnAssumption(nullable=True, max_distinct=3), "g": ColumnAssumption(max_distinct=3)}),
        "u": TableAssumptions(max_rows=64, columns={"k": ColumnAssumption(nullable=True, max_distinct=3)}),
    },
)


def dspec(sql: str) -> str:
    os.environ["LEMMA_STRING_ENCODING"] = "dict"
    try:
        return emit_declarative_spec(sql, DSCHEMA, DCAT)
    finally:
        del os.environ["LEMMA_STRING_ENCODING"]


def _row_hit(spec: str) -> str:
    return spec.split("spec fn row_hit")[1].split("\n}")[0]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t WHERE s = 'x'",
        "SELECT COUNT(*) AS c FROM t WHERE s = ''",
        "SELECT COUNT(*) AS c FROM t WHERE s <> 'x'",
        "SELECT COUNT(*) AS c FROM t WHERE NOT (s = 'x')",
        "SELECT COUNT(*) AS c FROM t WHERE s IN ('x', 'y')",
        "SELECT COUNT(*) AS c FROM t WHERE s NOT IN ('x', 'y')",
        "SELECT COUNT(*) AS c FROM t WHERE s LIKE 'x%'",
        "SELECT COUNT(*) AS c FROM t WHERE s = g",
        "SELECT COUNT(*) AS c FROM t, u WHERE t.s = u.k",
    ],
)
def test_every_dictionary_comparison_checks_the_validity_bit_before_reading_the_cell(sql: str) -> None:
    """A NULL cell has code 0 (= dictionary entry 0): the validity bit must precede every read of the dictionary cell."""
    row_hit = _row_hit(dspec(sql))
    cell = re.search(r"\w+\.\w+__dict@\[", row_hit)
    assert cell is not None
    for m in re.finditer(r"(\w+)\.(\w+)__dict@\[", row_hit):
        if m.group(2) not in ("s", "k"):
            continue  # g is not declared nullable: no validity vector
        valid = f"{m.group(1)}.{m.group(2)}__valid@["
        assert valid in row_hit[: m.start()], row_hit


def test_null_group_key_differs_from_the_empty_string_and_from_code_zero() -> None:
    spec = dspec("SELECT s, COUNT(*) AS c FROM t GROUP BY s")
    key = spec.split("spec fn key_at")[1].split("\n}")[0]
    assert "(true, (t.s__dict@[t.s@[i0] as int]@))" in key and "(false, Seq::<char>::empty())" in key
    assert "Option<String>" in spec.split("pub struct OutRow")[1].split("}")[0]


def test_count_distinct_counts_valid_cells_only() -> None:
    spec = dspec("SELECT COUNT(DISTINCT s) AS c FROM t")
    assert "hit_c(t, i0) && (t.s__valid@[i0])" in re.sub(r"\s+", " ", spec) or "row_hit(t, i0) && (t.s__valid@[i0])" in spec


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t JOIN u ON t.s = u.k",
        "SELECT COUNT(*) AS c FROM t JOIN u ON t.g = u.k",
        "SELECT COUNT(*) AS c FROM t JOIN u ON t.s = u.k WHERE u.k IS NOT NULL",
    ],
)
def test_join_on_a_nullable_dictionary_key_is_refused_unless_proved_non_null(sql: str) -> None:
    if "IS NOT NULL" in sql:
        with pytest.raises(DeclarativeUnsupported):
            dspec(sql)  # t.s is nullable too and unproven
    else:
        with pytest.raises(DeclarativeUnsupported, match="nullable column"):
            dspec(sql)


def _export(values: list, max_distinct: int = 300, fty: str = "u16"):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (id BIGINT, s VARCHAR)")
    for i, v in enumerate(values):
        con.execute("INSERT INTO t VALUES (?, ?)", [i, v])
    cat = CatalogAssumptions(
        max_rows=100000, tables={"t": TableAssumptions(max_rows=100000, columns={"s": ColumnAssumption(nullable=True, max_distinct=max_distinct)})}
    )
    model = SchemaModel.from_caller({"t": {"id": "bigint", "s": "varchar"}}, "t").with_nullable(cat)
    blob = _export_table(con, model, "t", [("s", fty), ("s__dict", "String"), ("s__valid", "bool")])
    n = struct.unpack_from("<Q", blob, 0)[0]
    width = {"u8": 1, "u16": 2, "u32": 4}[fty]
    fmt = {"u8": "B", "u16": "H", "u32": "I"}[fty]
    codes = list(struct.unpack_from(f"<{n}{fmt}", blob, 8))
    off = 8 + width * n
    m = struct.unpack_from("<Q", blob, off)[0]
    off += 8
    entries = []
    for _ in range(m):
        ln = struct.unpack_from("<I", blob, off)[0]
        entries.append(blob[off + 4 : off + 4 + ln].decode())
        off += 4 + ln
    valid = list(blob[off : off + n])
    assert off + n == len(blob)
    return codes, entries, valid


def test_null_cell_takes_code_zero_without_an_entry_and_the_dictionary_holds_only_values() -> None:
    codes, entries, valid = _export(["x", None, "y", None, "x"])
    assert entries == ["x", "y"] and valid == [1, 0, 1, 0, 1]
    assert codes[1] == codes[3] == 0
    assert all(c < len(entries) for c in codes)


def test_null_first_then_values_still_indexes_the_dictionary() -> None:
    codes, entries, valid = _export([None, "y", None, "x"])
    assert entries == ["y", "x"] and valid == [0, 1, 0, 1] and codes[0] == codes[2] == 0
    # code 0 of a NULL cell and entry 0 ("y") are different facts: only the validity bit says which
    assert entries[codes[0]] == "y" and valid[0] == 0


def test_all_null_column_gets_one_empty_entry_so_code_zero_indexes_it() -> None:
    codes, entries, valid = _export([None, None, None])
    assert entries == [""] and codes == [0, 0, 0] and valid == [0, 0, 0]


def test_empty_table_has_an_empty_dictionary_and_no_codes() -> None:
    codes, entries, valid = _export([])
    assert codes == [] and entries == [] and valid == []


def test_256_distinct_values_plus_null_fit_u8() -> None:
    values = [f"v{i}" for i in range(256)] + [None, None]
    codes, entries, valid = _export(values, max_distinct=256, fty="u8")
    assert len(entries) == 256 and max(codes) == 255 and valid[-2:] == [0, 0]


def test_one_more_distinct_value_overflows_u8_loudly() -> None:
    with pytest.raises(ValueError, match="cannot pack 256 as u8"):
        _export([f"v{i}" for i in range(257)] + [None], max_distinct=256, fty="u8")


def test_empty_string_value_and_null_are_distinct_cells() -> None:
    codes, entries, valid = _export(["", None, "a", ""])
    assert entries[codes[0]] == "" and valid == [1, 0, 1, 1] and entries == ["", "a"]


# ---- (4) join keys through dictionaries -------------------------------------------------------------------------------------

JSCHEMA = {"t": {"id": "bigint", "adsh": "varchar", "tag": "varchar"}, "u": {"adsh": "varchar", "w": "bigint", "tag": "varchar"}}
JCAT = CatalogAssumptions(
    max_rows=64,
    tables={
        "t": TableAssumptions(max_rows=64, columns={"adsh": ColumnAssumption(max_distinct=131072), "tag": ColumnAssumption(max_distinct=300)}),
        "u": TableAssumptions(max_rows=64, columns={"adsh": ColumnAssumption(max_distinct=131072), "tag": ColumnAssumption(max_distinct=300)}),
    },
)


def jspec(sql: str) -> str:
    os.environ["LEMMA_STRING_ENCODING"] = "dict"
    try:
        return emit_declarative_spec(sql, JSCHEMA, JCAT)
    finally:
        del os.environ["LEMMA_STRING_ENCODING"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS c FROM t JOIN u ON t.adsh = u.adsh",
        "SELECT SUM(u.w) AS s FROM t JOIN u ON t.adsh = u.adsh WHERE t.tag = u.tag",
        "SELECT COUNT(*) AS c FROM t x JOIN t y ON x.adsh = y.adsh",
        "SELECT COUNT(*) AS c FROM t x JOIN t y ON x.tag = y.tag AND x.id < y.id",
        "SELECT t.adsh, COUNT(*) AS c FROM t JOIN u ON t.adsh = u.adsh GROUP BY t.adsh",
    ],
)
def test_no_emitted_comparison_relates_codes_of_two_dictionaries(sql: str) -> None:
    spec = jspec(sql)
    stmts = re.sub(r"pub struct Cols_\w+ \{.*?\n\}\n", "", spec, flags=re.S)
    stmts = re.sub(r"pub open spec fn valid_cols_\w+.*?\n\}\n", "", stmts, flags=re.S)
    # every use of a string column in a statement is the accessor `X.c__dict@[X.c@[i] as int]@`
    for m in re.finditer(r"\b(\w+)\.(adsh|tag)@\[(\w+)\](?! as int)", stmts):
        raise AssertionError(f"raw code use in a statement: {m.group(0)}")
    assert "__dict@[" in stmts


def test_a_dictionary_over_its_declared_cap_fails_loudly_at_export() -> None:
    with pytest.raises(ValueError, match="cannot pack"):
        _export([f"v{i}" for i in range(300)], max_distinct=255, fty="u8")
