"""The bulk (numpy) exporter against the per-row oracle it replaced (``tests/_export_rowwise_reference.py``).

Every case runs both on the same DuckDB table and the same struct fields and demands identical bytes, or a ``ValueError`` from both:
NULL cells and validity vectors, extreme values and the narrow widths, dictionary order and contents, DECIMAL (i64 and i128), dates,
the empty table.
"""

from __future__ import annotations

import datetime as dt
import struct
from decimal import Decimal

import duckdb
import pytest

from declarative_spec.schema_types import SchemaModel
from research_loop.decl_query_measure import _export_table
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions
from tests._export_rowwise_reference import _export_table_rowwise

ERR = "ValueError"


def _model(schema: dict[str, str], nullable: tuple[str, ...] = (), scales: dict[str, int] | None = None, caps: dict[str, int] | None = None) -> SchemaModel:
    cols = {
        c: ColumnAssumption(nullable=c in nullable, scale=(scales or {}).get(c, 0), max_value_exclusive=(caps or {}).get(c))
        for c in schema
    }
    cat = CatalogAssumptions(max_rows=10**7, tables={"t": TableAssumptions(max_rows=10**7, columns=cols)})
    return SchemaModel.from_caller({"t": schema}, "t").with_nullable(cat)


def _run(fn, con, model, fields):
    try:
        return fn(con, model, "t", fields)
    except ValueError:
        return ERR


def both(ddl: str, rows: list[tuple], schema: dict[str, str], fields: list[tuple[str, str]], **kw) -> bytes | str:
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t ({ddl})")
    if rows:
        con.executemany(f"INSERT INTO t VALUES ({', '.join('?' * len(rows[0]))})", rows)
    model = _model(schema, **kw)
    old = _run(_export_table_rowwise, con, model, fields)
    new = _run(_export_table, con, model, fields)
    assert new == old, (old if old == ERR else old[:200], new if new == ERR else new[:200])
    return new


# ---- NULLs --------------------------------------------------------------------------------------------------------------------------
def test_nullable_int_gets_default_cell_and_validity_vector() -> None:
    out = both("x BIGINT", [(5,), (None,), (-7,), (None,)], {"x": "bigint"}, [("x", "i64"), ("x__valid", "bool")], nullable=("x",))
    assert struct.unpack_from("<4q", out, 8) == (5, 0, -7, 0)
    assert out[40:] == bytes([1, 0, 1, 0])


def test_nullable_decimal_i128_and_date_null_cells() -> None:
    both("v DECIMAL(38,4), d DATE", [(Decimal("1.5"), dt.date(2000, 1, 2)), (None, None)],
         {"v": "decimal(38,4)", "d": "date"}, [("v", "i128"), ("v__valid", "bool"), ("d", "i32"), ("d__valid", "bool")], nullable=("v", "d"), scales={"v": 4})


def test_null_in_a_column_not_declared_nullable_is_refused_by_both() -> None:
    assert both("x BIGINT", [(1,), (None,)], {"x": "bigint"}, [("x", "i64")]) == ERR
    assert both("s VARCHAR", [("a",), (None,)], {"s": "varchar"}, [("s", "String")]) == ERR


def test_nullable_dictionary_null_cells_take_code_zero_without_an_entry() -> None:
    out = both("s VARCHAR", [(None,), ("b",), (None,), ("a",), ("b",)], {"s": "varchar"},
               [("s", "u8"), ("s__dict", "String"), ("s__valid", "bool")], nullable=("s",))
    assert out[8:13] == bytes([0, 0, 0, 1, 0])  # NULL, b, NULL, a, b
    assert struct.unpack_from("<Q", out, 13)[0] == 2


def test_all_null_dictionary_column_still_has_an_entry_zero() -> None:
    out = both("s VARCHAR", [(None,), (None,)], {"s": "varchar"}, [("s", "u8"), ("s__dict", "String"), ("s__valid", "bool")], nullable=("s",))
    assert struct.unpack_from("<Q", out, 10)[0] == 1


def test_nullable_plain_string_null_is_empty() -> None:
    both("s VARCHAR", [("x",), (None,), ("",)], {"s": "varchar"}, [("s", "String"), ("s__valid", "bool")], nullable=("s",))


# ---- extreme values and narrow widths ----------------------------------------------------------------------------------------------------
def test_i64_and_u64_extremes() -> None:
    both("a BIGINT, b UBIGINT", [(-(2**63), 2**64 - 1), (2**63 - 1, 0)], {"a": "bigint", "b": "ubigint"}, [("a", "i64"), ("b", "u64")])


def test_hugeint_extremes_into_i128() -> None:
    out = both("h HUGEINT", [(2**127 - 1,), (-(2**127),), (-1,), (0,), (2**64,), (-(2**64),)], {"h": "hugeint"}, [("h", "i128")])
    assert int.from_bytes(out[8:24], "little", signed=True) == 2**127 - 1


@pytest.mark.parametrize(("fty", "lo", "hi"), [("i8", -128, 127), ("i16", -32768, 32767), ("i32", -(2**31), 2**31 - 1)])
def test_narrow_bounds_pack_and_one_past_is_refused(monkeypatch: pytest.MonkeyPatch, fty: str, lo: int, hi: int) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    schema = {"x": "bigint"}
    caps = {"x": hi}
    assert both("x BIGINT", [(lo,), (hi,)], schema, [("x", fty)], caps=caps) != ERR
    assert both("x BIGINT", [(lo,), (hi + 1,)], schema, [("x", fty)], caps=caps) == ERR
    assert both("x BIGINT", [(lo - 1,), (hi,)], schema, [("x", fty)], caps=caps) == ERR


@pytest.mark.parametrize("fty", ["u8", "u16", "u32", "i8"])
def test_a_field_type_the_column_does_not_have_is_refused_by_both(fty: str) -> None:
    assert both("x BIGINT", [(1,)], {"x": "bigint"}, [("x", fty)]) == ERR


def test_narrow_decimal_scaled_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")
    both("d DECIMAL(10,2)", [(Decimal("327.67"),), (Decimal("-327.68"),)], {"d": "decimal(10,2)"}, [("d", "i16")], scales={"d": 2}, caps={"d": 2**15})
    assert both("d DECIMAL(10,2)", [(Decimal("327.68"),)], {"d": "decimal(10,2)"}, [("d", "i16")], scales={"d": 2}, caps={"d": 2**15}) == ERR


def test_integer_widened_into_an_i64_field() -> None:
    both("x INTEGER", [(-5,), (2**31 - 1,)], {"x": "integer"}, [("x", "i64")])
    both("x SMALLINT", [(-5,), (300,)], {"x": "smallint"}, [("x", "i64")])


def test_f64_specials_and_negative_zero() -> None:
    both("f DOUBLE", [(1.5,), (-0.0,), (float("inf"),), (float("nan"),), (5e-324,)], {"f": "double"}, [("f", "f64")])
    both("f FLOAT", [(1.5,), (0.1,)], {"f": "float"}, [("f", "f64")])


def test_bool_and_date_cells() -> None:
    both("b BOOLEAN, d DATE", [(True, dt.date(1969, 12, 31)), (False, dt.date(1970, 1, 1)), (True, dt.date(9999, 12, 31))],
         {"b": "boolean", "d": "date"}, [("b", "bool"), ("d", "i32")])
    both("d DATE", [(dt.date(1, 1, 1),)], {"d": "date"}, [("d", "i32")])


# ---- DECIMAL ---------------------------------------------------------------------------------------------------------------------------
def test_decimal_i64_scaled() -> None:
    both("v DECIMAL(12,2)", [(Decimal("123456789.01"),), (Decimal("-0.05"),), (Decimal("0.00"),)], {"v": "decimal(12,2)"}, [("v", "i64")], scales={"v": 2})


def test_decimal_i128_extremes_do_not_overflow_a_decimal_multiply() -> None:
    nines = Decimal("9" * 34 + "." + "9" * 4)
    out = both("v DECIMAL(38,4)", [(nines,), (-nines,), (Decimal("0.0001"),), (Decimal("-0.0001"),)], {"v": "decimal(38,4)"}, [("v", "i128")], scales={"v": 4})
    assert int.from_bytes(out[8:24], "little", signed=True) == 10**38 - 1


def test_decimal_with_fewer_fractional_digits_than_the_catalog_scale_is_scaled_up() -> None:
    both("v DECIMAL(12,1)", [(Decimal("1.5"),), (Decimal("-2.5"),)], {"v": "decimal(12,1)"}, [("v", "i64")], scales={"v": 3})
    both("v DECIMAL(30,1)", [(Decimal("1.5"),)], {"v": "decimal(30,1)"}, [("v", "i128")], scales={"v": 4})


# ---- dictionaries and strings ----------------------------------------------------------------------------------------------------------------
def test_dictionary_codes_follow_first_appearance_not_sorted_order() -> None:
    out = both("s VARCHAR", [("zebra",), ("apple",), ("zebra",), ("mango",), ("apple",)], {"s": "varchar"}, [("s", "u8"), ("s__dict", "String")])
    assert out[8:13] == bytes([0, 1, 0, 2, 1])


def test_dictionary_empty_unicode_quote_and_whitespace_values() -> None:
    vals = ["", " ", "  ", "it's", 'say "hi"', "back\\slash", "naïve", "日本語", "😀", "line\nbreak", "a'b''c", "A", "a", "A "]
    both("s VARCHAR", [(v,) for v in vals + vals[::-1]], {"s": "varchar"}, [("s", "u8"), ("s__dict", "String")])
    both("s VARCHAR", [(v,) for v in vals], {"s": "varchar"}, [("s", "String")])


def test_duplicate_values_share_one_code_and_entries_are_distinct() -> None:
    out = both("s VARCHAR", [("x",)] * 5 + [("y",)] * 3, {"s": "varchar"}, [("s", "u16"), ("s__dict", "String")])
    assert struct.unpack_from("<Q", out, 8 + 16)[0] == 2


def test_dictionary_size_against_the_code_width() -> None:
    rows = [(f"v{i}",) for i in range(257)]
    assert both("s VARCHAR", rows, {"s": "varchar"}, [("s", "u8"), ("s__dict", "String")]) == ERR
    assert both("s VARCHAR", rows, {"s": "varchar"}, [("s", "u16"), ("s__dict", "String")]) != ERR
    assert both("s VARCHAR", rows[:256], {"s": "varchar"}, [("s", "u8"), ("s__dict", "String")]) != ERR


def test_two_dictionary_columns_and_mixed_fields_in_one_table() -> None:
    both("a VARCHAR, n BIGINT, b VARCHAR", [("p", 1, "q"), ("q", 2, "q"), ("p", 3, "r")], {"a": "varchar", "n": "bigint", "b": "varchar"},
         [("a", "u8"), ("a__dict", "String"), ("n", "i64"), ("b", "u8"), ("b__dict", "String")])


# ---- the empty table -------------------------------------------------------------------------------------------------------------------------
def test_empty_table_all_kinds() -> None:
    out = both("x BIGINT, s VARCHAR, v DECIMAL(38,4), d DATE", [], {"x": "bigint", "s": "varchar", "v": "decimal(38,4)", "d": "date"},
               [("x", "i64"), ("s", "u8"), ("s__dict", "String"), ("v", "i128"), ("d", "i32")], scales={"v": 4})
    assert struct.unpack_from("<Q", out, 0)[0] == 0


def test_empty_table_nullable_and_plain_string() -> None:
    both("x BIGINT, s VARCHAR", [], {"x": "bigint", "s": "varchar"}, [("x", "i64"), ("x__valid", "bool"), ("s", "String")], nullable=("x",))
    both("x BIGINT", [], {"x": "bigint"}, [("x", "u8")])


def test_a_table_larger_than_one_chunk() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT i::BIGINT AS x, (i % 7)::VARCHAR AS s, CASE WHEN i % 5 = 0 THEN NULL ELSE i::DECIMAL(20,2) END AS v FROM range(1200000) r(i)")
    model = _model({"x": "bigint", "s": "varchar", "v": "decimal(20,2)"}, nullable=("v",), scales={"v": 2})
    fields = [("x", "i64"), ("s", "u8"), ("s__dict", "String"), ("v", "i128"), ("v__valid", "bool")]
    assert _export_table(con, model, "t", fields) == _export_table_rowwise(con, model, "t", fields)


@pytest.mark.parametrize(("p", "s"), [(38, 20), (30, 25), (38, 30), (38, 38), (38, 19)])
def test_decimal_wide_scales_match_the_oracle(p: int, s: int) -> None:
    ip = "1" if p > s else "0"
    v = Decimal(f"{ip}.{'3' * s}")
    both(f"v DECIMAL({p},{s})", [(v,), (-v,), (Decimal(0),)], {"v": f"decimal({p},{s})"}, [("v", "i128")], scales={"v": s})


def _new_only(ddl: str, rows: list[tuple], schema: dict[str, str], fields: list[tuple[str, str]]) -> None:
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t ({ddl})")
    con.executemany(f"INSERT INTO t VALUES ({', '.join('?' * len(rows[0]))})", rows)
    with pytest.raises(ValueError):
        _export_table(con, _model(schema), "t", fields)


def test_a_column_named_rowid_is_refused_loudly() -> None:
    _new_only("rowid BIGINT, s VARCHAR", [(3, "a"), (2, "b")], {"rowid": "bigint", "s": "varchar"}, [("s", "u8"), ("s__dict", "String")])
    _new_only("rowid VARCHAR, s VARCHAR", [("z", "a")], {"rowid": "varchar", "s": "varchar"}, [("s", "u8"), ("s__dict", "String")])


def test_a_nul_byte_in_a_dictionary_string_is_refused_loudly() -> None:
    _new_only("s VARCHAR", [("a\x00b",), ("zz",)], {"s": "varchar"}, [("s", "u8"), ("s__dict", "String")])
    _new_only("s VARCHAR", [("\x00",)], {"s": "varchar"}, [("s", "u8"), ("s__dict", "String")])


def test_a_column_type_the_field_cannot_mean_is_refused_loudly() -> None:
    _new_only("s BOOLEAN", [(True,)], {"s": "varchar"}, [("s", "String")])
    _new_only("x DOUBLE", [(1.5,)], {"x": "bigint"}, [("x", "i64")])
