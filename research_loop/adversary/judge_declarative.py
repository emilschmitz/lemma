"""Adversary judge for ``LEMMA_SPEC_STYLE=declarative``.

Emit and assemble come only from ``declarative_spec``. The recursive
transpiler, ``admit_runquery`` and ``assemble_runquery`` are not called here.
The candidate ``run_query_body`` is the interior of the declarative
``run_query`` (parameters are the ``Cols_<table>`` references of the spec).
"""

from __future__ import annotations

import re
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from research_loop.adversary.candidate import Candidate
from research_loop.adversary.significance import (
    classify_difference,
    sql_limit_without_order,
    unlimited_sql,
)
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    TableAssumptions,
)

_SPEC_TRUNC = 4000
_OUT_FIELD = re.compile(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+([^,\n]+),")
_COLS_FIELD = re.compile(r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>")


_KEY_CAP_LIMIT = 1 << 20


def default_catalog(
    tables: dict[str, dict[str, str]], rows: dict[str, list[dict]]
) -> CatalogAssumptions:
    """Row cap, plus a measured exclusive cap on small unsigned columns.

    The cap is the loaded table's own max + 1, as a measured catalog would give.
    A dense group-count map needs it to print its rows. Signed and large
    columns get no assumption beyond the SQL type.
    """
    # These are upper bounds only. No row-count floor is imposed on the data: an empty table
    # (n == 0) stays allowed, because empty-table answers (SUM/MIN/MAX are NULL, COUNT is 0)
    # are exactly what the judge probes.
    biggest = max([len(r) for r in rows.values()] + [1])
    per_table: dict[str, TableAssumptions] = {}
    for table, col_types in tables.items():
        cols: dict[str, ColumnAssumption] = {}
        for col, sql_type in col_types.items():
            if not sql_type.strip().lower().startswith("u"):
                continue
            seen = [r[col] for r in rows.get(table, []) if r.get(col) is not None]
            cap = max(seen, default=0) + 1
            if cap < _KEY_CAP_LIMIT:
                cols[col] = ColumnAssumption(max_value_exclusive=cap)
        if cols:
            per_table[table] = TableAssumptions(max_rows=max(16, biggest), columns=cols)
    return CatalogAssumptions(tables=per_table, max_rows=max(16, biggest))


def _load_duckdb(
    con: duckdb.DuckDBPyConnection,
    tables: dict[str, dict[str, str]],
    rows: dict[str, list[dict]],
) -> None:
    for table, col_types in tables.items():
        parts = [f'"{c}" {t.strip().upper()}' for c, t in col_types.items()]
        con.execute(f'CREATE TABLE "{table}" ({", ".join(parts)})')
        cols = list(col_types)
        names = ", ".join(f'"{c}"' for c in cols)
        ph = ", ".join("?" for _ in cols)
        for row in rows.get(table, []):
            con.execute(
                f'INSERT INTO "{table}" ({names}) VALUES ({ph})',
                [row.get(c) for c in cols],
            )


def _decode(cell: str, fty: str, scale: int = 0) -> object:
    """One printed cell. `NULL` is an `Option` cell; a scaled integer (DECIMAL) is divided by 10**scale."""
    if cell == "NULL":
        return None
    if fty.startswith("Option<"):
        fty = fty[len("Option<") : -1]
    if fty == "String":
        return bytes.fromhex(cell).decode("utf-8")
    if fty == "f64":
        return float(cell)
    if scale:
        return Decimal(int(cell)).scaleb(-scale)
    return int(cell)


def _out_scales(spec_rs: str, n_fields: int) -> list[int]:
    """The `// OUT_SCALES: a,b,..` line the emitter writes for DECIMAL results (stored integer = value * 10**scale)."""
    m = re.search(r"^// OUT_SCALES: ([0-9,]+)$", spec_rs, re.MULTILINE)
    if m is None:
        return [0] * n_fields
    scales = [int(x) for x in m.group(1).split(",")]
    if len(scales) != n_fields:
        raise ValueError(f"OUT_SCALES has {len(scales)} entries, OutRow has {n_fields}")
    return scales


def _parse_rows(stdout: str, spec_rs: str) -> tuple[list[tuple] | None, str | None]:
    out = re.search(r"pub struct OutRow\s*\{([^}]+)\}", spec_rs)
    if out is not None:
        ftypes = [t.strip() for _n, t in _OUT_FIELD.findall(out.group(1))]
        rows: list[tuple] = []
        for line in stdout.splitlines():
            if not line.startswith("ROW\x1f"):
                continue
            cells = line.split("\x1f")[1:]
            if len(cells) != len(ftypes):
                return None, f"row has {len(cells)} fields, OutRow has {len(ftypes)}"
            scales = _out_scales(spec_rs, len(ftypes))
            rows.append(tuple(_decode(c, t, sc) for c, t, sc in zip(cells, ftypes, scales, strict=True)))
        return rows, None
    if "HashMapWithView<u64, u64>" in spec_rs and "pub const KEY_CAP_" in spec_rs:
        pairs: list[tuple] = []
        for line in stdout.splitlines():
            if line.startswith("ROW "):
                _tag, k, v = line.split()
                pairs.append((int(k), int(v)))
        return pairs, None
    return None, "spec return shape is neither OutRow nor a capped dense u64 count map"


def judge_declarative_candidate(
    candidate: Candidate,
    *,
    config: str = "hardware",
    verify: bool = False,
    work_dir: Path | None = None,
    catalog: CatalogAssumptions | None = None,
) -> dict[str, Any]:
    # Shared pure helpers of the recursive judge; no recursive emit or assemble.
    from research_loop.adversary.judge import (
        _rows_have_null,
        _rows_outside_sql_domain,
        _schema_tables,
    )

    # Declarative imports stay inside the function: the recursive judge never loads them.
    from declarative_spec.admit import admit_declarative_body
    from declarative_spec.assemble import assemble_declarative_program
    from declarative_spec.emit import DeclarativeUnsupported, emit_declarative_spec
    from declarative_spec.lemmas import FitRefusal
    from declarative_spec.pipeline import compile_and_run
    from declarative_spec.schema_types import SchemaModel, rust_ident
    from research_loop.decl_query_measure import _export_table

    base: dict[str, Any] = {"config": config, "spec_style": "declarative", "sql": candidate.sql}

    body = candidate.run_query_body
    violations = admit_declarative_body(body).violations
    if violations:
        return {**base, "status": "rejected", "significant": False, "violations": violations}

    if _rows_have_null(candidate.rows):
        return {
            **base,
            "status": "rows_outside_model",
            "significant": False,
            "reason": "column loads are non-null; SQL NULL is not a cell",
        }
    if _rows_outside_sql_domain(candidate.schema, candidate.rows):
        return {
            **base,
            "status": "rows_outside_model",
            "significant": False,
            "reason": "cell is outside the SQL type DuckDB would store",
        }

    tables = _schema_tables(candidate.schema)
    cat = catalog if catalog is not None else default_catalog(tables, candidate.rows)
    try:
        spec_rs = emit_declarative_spec(candidate.sql, tables, cat)
    except (DeclarativeUnsupported, FitRefusal) as exc:
        return {
            **base,
            "status": "refused",
            "significant": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    except Exception as exc:  # noqa: BLE001  a crash is reported, never a silent refusal
        return {
            **base,
            "status": "emit_crash",
            "significant": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    base["spec_rs"] = spec_rs[:_SPEC_TRUNC]
    if candidate.helpers.strip():
        from declarative_spec.admit import admit_helpers

        helper_violations = admit_helpers(candidate.helpers, spec_rs).violations
        if helper_violations:
            return {**base, "status": "rejected", "significant": False, "violations": helper_violations}

    if not verify:
        return {**base, "status": "unchecked_exec", "significant": False}

    con = duckdb.connect()
    try:
        _load_duckdb(con, tables, candidate.rows)
        try:
            duck_rows: list[tuple] | None = [tuple(r) for r in con.execute(candidate.sql).fetchall()]
            duck_error = None
        except duckdb.Error as exc:
            duck_rows, duck_error = None, str(exc)
        base["duck_rows"] = duck_rows
        base["duck_error"] = duck_error
        unlimited = None
        if duck_error is None and sql_limit_without_order(candidate.sql):
            unlimited = [tuple(r) for r in con.execute(unlimited_sql(candidate.sql)).fetchall()]

        model = SchemaModel.from_caller(tables, next(iter(tables)))
        structs = re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", spec_rs)
        with tempfile.TemporaryDirectory(prefix="lemma_adv_decl_") as tmp_name:
            root = work_dir if work_dir is not None else Path(tmp_name)
            root.mkdir(parents=True, exist_ok=True)
            bins: dict[str, str] = {}
            for struct_name, sbody in structs:
                suffix = struct_name.removeprefix("Cols_")
                hits = [o for o in model.original_table_names.values() if rust_ident(o) == suffix]
                if len(hits) != 1:
                    raise ValueError(f"no table matches column struct {suffix}")
                blob = _export_table(con, model, hits[0], _COLS_FIELD.findall(sbody))
                path = root / f"cols_{suffix}.bin"
                path.write_bytes(blob)
                bins[suffix] = str(path)
            assembled = assemble_declarative_program(spec_rs, body, helpers=candidate.helpers, column_bins=bins)
            metrics = compile_and_run(assembled, work_dir=root)
    finally:
        con.close()

    if metrics["status"] != "SUCCESS":
        if not metrics.get("proof_verified"):
            return {
                **base,
                "status": "impl_does_not_fit_spec",
                "significant": False,
                "proof_verified": False,
                "verify_msg": (metrics.get("verify_msg") or "")[:2000],
            }
        return {
            **base,
            "status": "exec_fail",
            "significant": False,
            "proof_verified": True,
            "reason": (metrics.get("compiler_error") or "")[:2000],
        }

    impl_rows, why = _parse_rows(metrics["stdout"], spec_rs)
    if impl_rows is None:
        return {
            **base,
            "status": "opaque_exec_result",
            "significant": False,
            "proof_verified": True,
            "reason": why,
            "stdout": metrics["stdout"][:500],
        }
    verdict = classify_difference(
        candidate.sql, impl_rows, duck_rows, duck_error=duck_error, unlimited=unlimited
    )
    return {
        **base,
        "status": "hole" if verdict.significant else "no_difference",
        "significant": verdict.significant,
        "reason": verdict.reason,
        "proof_verified": True,
        "impl_rows": impl_rows,
    }
