"""Compare a named assumption package against the live DuckDB.

``uv run python -m research_loop.assumption_packages.check --package sec_margin --db <path>``

Every violated assumption is listed with the measured number, then the run exits
non-zero. Nothing is skipped: a table or column the package names that the
database lacks is a violation too.

Measuring rules (same as the loader):

* row cap: ``COUNT(*) <= max_rows``
* value cap (exclusive): integers use ``MAX(ABS(col)) < cap``. DOUBLE columns are
  truncated toward zero into u64, so negatives become 0:
  ``MAX(GREATEST(TRUNC(col), 0)) < cap``
* DECIMAL(p, s) columns: the cap is on the stored integer ``value * 10**s``, so the cap's
  ``scale`` must equal ``s`` and ``MAX(ABS(col)) * 10**s < cap``, measured exactly
* string cap: ``MAX(LENGTH(col)) <= cap``
* unique key: no group of the key columns has more than one row
* join cap: ``COUNT(*)`` of the declared join is at most the cap (named with the measured count when violated)
* catalog caps: ``max_rows`` over every table; ``max_native_u32`` over columns of
  at most 32 bits; ``max_cell_u64`` over BIGINT/HUGEINT/DOUBLE columns;
  ``max_string_len`` over every VARCHAR column.
"""

from __future__ import annotations

import argparse
from typing import Any

from research_loop.decl_query_measure import decimal_scaled
from db_extension.dataset_config import (
    _FLOAT_DUCKDB_TYPES,
    _INTEGER_DUCKDB_TYPES,
    _quote_duckdb_ident,
)
from research_loop.assumption_packages import assumption_package
from research_loop.table_assumptions import CatalogAssumptions

_NARROW_INT_TYPES = frozenset(
    {
        "integer", "int", "int4", "int32", "smallint", "int2", "int16",
        "tinyint", "int1", "utinyint", "uint8", "usmallint", "uint16",
        "uinteger", "uint32",
    }
)
_STRING_TYPES = frozenset({"varchar", "text", "string", "char", "bpchar"})


class AssumptionViolation(RuntimeError):
    """The package states something the database contradicts."""


def _max_value(con: Any, table: str, col: str, base: str, scale: int = 0) -> int | None:
    """Largest absolute cell as an integer; a DECIMAL's is its stored integer, exactly."""
    q, t = _quote_duckdb_ident(col), _quote_duckdb_ident(table)
    if base == "decimal":
        got = con.execute(f"SELECT MAX(ABS({q})) FROM {t}").fetchone()[0]
        return None if got is None else decimal_scaled(got, scale)
    if base in _FLOAT_DUCKDB_TYPES:
        sql = f"SELECT CAST(MAX(GREATEST(TRUNC({q}), 0)) AS HUGEINT) FROM {t}"
    else:
        sql = f"SELECT CAST(MAX(ABS({q})) AS HUGEINT) FROM {t}"
    got = con.execute(sql).fetchone()[0]
    return None if got is None else int(got)


def _max_len(con: Any, table: str, col: str) -> int | None:
    q, t = _quote_duckdb_ident(col), _quote_duckdb_ident(table)
    got = con.execute(f"SELECT MAX(LENGTH({q})) FROM {t}").fetchone()[0]
    return None if got is None else int(got)


def _max_group(con: Any, table: str, key: tuple[str, ...]) -> int | None:
    group = ", ".join(_quote_duckdb_ident(c) for c in key)
    got = con.execute(
        f"SELECT MAX(c) FROM (SELECT COUNT(*) AS c FROM {_quote_duckdb_ident(table)} "
        f"GROUP BY {group})"
    ).fetchone()[0]
    return None if got is None else int(got)


def violations(catalog: CatalogAssumptions, con: Any) -> list[str]:
    """Every assumption in ``catalog`` that ``con`` contradicts."""
    types: dict[str, dict[str, str]] = {}
    scales: dict[tuple[str, str], int] = {}
    for t, c, d in con.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main'"
    ).fetchall():
        full = str(d).lower()
        types.setdefault(str(t), {})[str(c)] = full.split("(")[0]
        if full.startswith("decimal("):
            scales[(str(t), str(c))] = int(full.rstrip(")").split(",")[1])

    out: list[str] = []
    counts = {
        t: int(con.execute(f"SELECT COUNT(*) FROM {_quote_duckdb_ident(t)}").fetchone()[0])
        for t in types
    }

    def check_rows(label: str, cap: int | None, measured: int) -> None:
        if cap is not None and measured > cap:
            out.append(f"{label}: row cap {cap} < measured {measured}")

    for name, table in catalog.tables.items():
        if name not in types:
            out.append(f"table {name}: named by the package but absent from the database")
            continue
        check_rows(f"table {name}", table.max_rows, counts[name])
        for col, ca in table.columns.items():
            if col not in types[name]:
                out.append(f"{name}.{col}: named by the package but absent from the database")
                continue
            base = types[name][col]
            db_scale = scales.get((name, col), 0)
            if ca.max_value_exclusive is not None:
                if base not in _INTEGER_DUCKDB_TYPES | _FLOAT_DUCKDB_TYPES | {"decimal"}:
                    out.append(f"{name}.{col}: value cap on non-numeric type {base}")
                elif ca.scale != db_scale:
                    out.append(
                        f"{name}.{col}: value cap is in units of 10^-{ca.scale}, "
                        f"the column is {base} with scale {db_scale}"
                    )
                else:
                    m = _max_value(con, name, col, base, db_scale)
                    if m is not None and m >= ca.max_value_exclusive:
                        out.append(
                            f"{name}.{col}: value cap < {ca.max_value_exclusive} "
                            f"but measured max {m}"
                        )
            if ca.max_string_len is not None:
                if base not in _STRING_TYPES:
                    out.append(f"{name}.{col}: string cap on non-string type {base}")
                else:
                    m = _max_len(con, name, col)
                    if m is not None and m > ca.max_string_len:
                        out.append(
                            f"{name}.{col}: string length cap {ca.max_string_len} "
                            f"but measured max {m}"
                        )
            if ca.abs_sum_exclusive is not None:
                q, t = _quote_duckdb_ident(col), _quote_duckdb_ident(name)
                s = con.execute(
                    f"SELECT CAST(SUM(CEIL(ABS({q}))) AS HUGEINT) FROM {t}"
                ).fetchone()[0]
                if s is not None and int(s) >= ca.abs_sum_exclusive:
                    out.append(
                        f"{name}.{col}: abs-sum cap < {ca.abs_sum_exclusive} "
                        f"but measured sum {int(s)}"
                    )
        keys = list(table.unique_keys)
        if table.one_row_per_adsh and ("adsh",) not in keys:
            keys.append(("adsh",))
        for key in keys:
            missing = [c for c in key if c not in types[name]]
            if missing:
                out.append(f"{name} unique key {key}: columns {missing} absent")
                continue
            m = _max_group(con, name, key)
            if m is not None and m > 1:
                out.append(f"{name} unique key {key}: a group has {m} rows")

    for jc in catalog.join_caps:
        label = f"join cap {jc.left} JOIN {jc.right} ON " + " AND ".join(
            f"{jc.left}.{a} = {jc.right}.{b}" for a, b in jc.equalities
        )
        absent = [(t, c) for t, c in [(jc.left, a) for a, _ in jc.equalities] + [(jc.right, b) for _, b in jc.equalities]
                  if t not in types or c not in types[t]]
        if absent:
            out.append(f"{label}: {absent} absent from the database")
            continue
        on = " AND ".join(
            f"l.{_quote_duckdb_ident(a)} = r.{_quote_duckdb_ident(b)}" for a, b in jc.equalities
        )
        measured = int(
            con.execute(
                f"SELECT COUNT(*) FROM {_quote_duckdb_ident(jc.left)} l "
                f"JOIN {_quote_duckdb_ident(jc.right)} r ON {on}"
            ).fetchone()[0]
        )
        if measured > jc.max_tuples:
            out.append(f"{label}: cap {jc.max_tuples} < measured {measured} joined tuples")

    for label, cap in (
        ("max_rows", catalog.max_rows),
        ("max_rows_cube", catalog.max_rows_cube),
        ("max_rows_4", catalog.max_rows_4),
    ):
        for t, n in counts.items():
            check_rows(f"catalog {label}, table {t}", cap, n)

    for t, cols in types.items():
        for c, base in cols.items():
            if catalog.max_native_u32 is not None and base in _NARROW_INT_TYPES:
                m = _max_value(con, t, c, base)
                if m is not None and m >= catalog.max_native_u32:
                    out.append(
                        f"catalog max_native_u32 < {catalog.max_native_u32} "
                        f"but {t}.{c} measured max {m}"
                    )
            if catalog.max_cell_u64 is not None and (
                base in _FLOAT_DUCKDB_TYPES
                or (base in _INTEGER_DUCKDB_TYPES and base not in _NARROW_INT_TYPES)
            ):
                m = _max_value(con, t, c, base)
                if m is not None and m >= catalog.max_cell_u64:
                    out.append(
                        f"catalog max_cell_u64 < {catalog.max_cell_u64} "
                        f"but {t}.{c} measured max {m}"
                    )
            if catalog.max_string_len is not None and base in _STRING_TYPES:
                m = _max_len(con, t, c)
                if m is not None and m > catalog.max_string_len:
                    out.append(
                        f"catalog max_string_len {catalog.max_string_len} "
                        f"but {t}.{c} measured max {m}"
                    )
    return out


def check_package(package: str, db: str) -> None:
    """Raise ``AssumptionViolation`` listing every violated assumption."""
    import duckdb

    con = duckdb.connect(db, read_only=True)
    try:
        found = violations(assumption_package(package), con)
    finally:
        con.close()
    if found:
        raise AssumptionViolation(
            f"package {package!r} is false on {db}:\n  " + "\n  ".join(found)
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--package", required=True)
    ap.add_argument("--db", required=True)
    args = ap.parse_args()
    check_package(args.package, args.db)
    print(f"assumption package {args.package!r} holds on {args.db}")


if __name__ == "__main__":
    main()
