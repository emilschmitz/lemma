"""Host-side adversary candidate judge."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import duckdb
from verus_transpiler.column_projection import project_schema_for_query
from verus_transpiler.parse_sql import normalize_schema

from research_loop.admit_runquery import admit_runquery_body
from research_loop.adversary.candidate import Candidate
from research_loop.adversary.significance import classify_difference
from research_loop.assemble_runquery import build_exec_run_query_from_body
from research_loop.harness import (
    resolve_verus_bin,
    run_verus_compile,
    run_verus_verify,
    write_unified_program,
)
from research_loop.lemma_flags import enable_templates
from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec
from research_loop.trust_configs import apply_trust_config
from verus_transpiler import transpile_sql_to_verus

_SPEC_TRUNC = 4000
_SCALAR_RET = frozenset({"u64", "i64"})
_RESULT_SCALAR = re.compile(r"^RESULT:\s*(-?\d+)\s*$", re.MULTILINE)
_RESULT_NONE = re.compile(r"^RESULT:\s*none\s*$", re.MULTILINE)
_RESULT_SOME = re.compile(r"^RESULT:\s*some\s+(-?\d+)\s*$", re.MULTILINE)
_OPAQUE_MARKERS = ("map_len", "checksum", "seq_len", "set_len")


def _schema_tables(schema: dict) -> dict[str, dict[str, str]]:
    _flat, multi = normalize_schema(schema)
    if multi:
        return {k: dict(v) for k, v in multi.items()}
    return {"t": dict(_flat)}


def _duckdb_type(sql_type: str) -> str:
    return sql_type.strip().upper()


def _run_duckdb(
    sql: str,
    schema: dict,
    rows: dict[str, list[dict]],
) -> tuple[list[tuple] | None, str | None]:
    tables = _schema_tables(schema)
    con = duckdb.connect()
    try:
        for table, col_types in tables.items():
            table_rows = rows.get(table, [])
            parts = [f'"{c}" {_duckdb_type(t)}' for c, t in col_types.items()]
            con.execute(f'CREATE TABLE "{table}" ({", ".join(parts)})')
            cols = list(col_types.keys())
            for row in table_rows:
                names = ", ".join(f'"{c}"' for c in cols)
                ph = ", ".join("?" for _ in cols)
                vals = [row.get(c) for c in cols]
                con.execute(
                    f'INSERT INTO "{table}" ({names}) VALUES ({ph})',
                    vals,
                )
        out = con.execute(sql).fetchall()
        return [tuple(r) for r in out], None
    except duckdb.Error as exc:
        return None, str(exc)
    finally:
        con.close()


def _rows_have_null(rows: dict[str, list[dict]]) -> bool:
    for table_rows in rows.values():
        for row in table_rows:
            if any(value is None for value in row.values()):
                return True
    return False


# DuckDB stores these as fixed-width integers. A wider Python int is not a cell.
_SQL_INT_RANGE: dict[str, tuple[int, int]] = {
    "tinyint": (-128, 127),
    "int1": (-128, 127),
    "smallint": (-32768, 32767),
    "int2": (-32768, 32767),
    "int16": (-32768, 32767),
    "integer": (-2147483648, 2147483647),
    "int": (-2147483648, 2147483647),
    "int4": (-2147483648, 2147483647),
    "int32": (-2147483648, 2147483647),
    "bigint": (-9223372036854775808, 9223372036854775807),
    "int64": (-9223372036854775808, 9223372036854775807),
    "int8": (-9223372036854775808, 9223372036854775807),
    "hugeint": (-(2**127), 2**127 - 1),
    "utinyint": (0, 255),
    "usmallint": (0, 65535),
    "uinteger": (0, 2**32 - 1),
    "ubigint": (0, 2**64 - 1),
}


def _cell_outside_sql_type(sql_type: str, value: object) -> bool:
    base = sql_type.lower().split("(")[0].strip()
    if base not in _SQL_INT_RANGE:
        return False
    if isinstance(value, bool) or not isinstance(value, int):
        return True
    lo, hi = _SQL_INT_RANGE[base]
    return value < lo or value > hi


def _rows_outside_sql_domain(schema: dict, rows: dict[str, list[dict]]) -> bool:
    tables = _schema_tables(schema)
    for table, table_rows in rows.items():
        col_types = tables.get(table)
        if col_types is None and len(tables) == 1:
            col_types = next(iter(tables.values()))
        if not col_types:
            continue
        for row in table_rows:
            for col, value in row.items():
                sql_type = col_types.get(col)
                if sql_type is None or value is None:
                    continue
                if _cell_outside_sql_type(sql_type, value):
                    return True
    return False


def _write_tbl(path: Path, table: str, col_types: dict[str, str], table_rows: list[dict]) -> int:
    cols = list(col_types.keys())
    header = "|".join(c.upper() for c in cols)
    lines = [header]
    for row in table_rows:
        cells = []
        for c in cols:
            v = row.get(c)
            if v is None:
                cells.append("")
            else:
                cells.append(str(v))
        lines.append("|".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(table_rows)


def _transpile(sql: str, schema: dict) -> tuple[str | None, dict[str, str] | None, str | None]:
    try:
        flat, multi = normalize_schema(schema)
        if multi:
            from verus_transpiler.column_projection import (
                project_multi_schema_for_query,
            )

            projected = project_multi_schema_for_query(sql, multi)
            if len(projected) == 1:
                one = next(iter(projected.values()))
                if not isinstance(one, dict):
                    raise TypeError("projected schema entry is not a column map")
                flat_schema = {str(k): str(v) for k, v in one.items()}
            else:
                flat_schema = {str(k): str(v) for k, v in flat.items()}
        else:
            projected = project_schema_for_query(sql, flat)
            flat_schema = {str(k): str(v) for k, v in projected.items()}
        spec_rs = transpile_sql_to_verus(
            sql,
            projected if multi else flat_schema,
            enable_templates=enable_templates(),
        )
        return spec_rs, flat_schema, None
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)


def _scoreable_ret(ret_type: str) -> bool:
    return ret_type in _SCALAR_RET or ret_type.startswith("opt_")


def _parse_scalar_result(stdout: str) -> tuple[int | None, str | None]:
    m = _RESULT_SCALAR.search(stdout)
    if not m:
        return None, "no RESULT: <integer> line in stdout"
    return int(m.group(1)), None


def _parse_printed_result(stdout: str) -> tuple[tuple | None, str | None]:
    """One printed scalar or Option. ``None`` cell means SQL NULL."""
    if any(m in stdout for m in _OPAQUE_MARKERS):
        return None, "product printer does not dump full rows"
    if _RESULT_NONE.search(stdout):
        return (None,), None
    some = _RESULT_SOME.search(stdout)
    if some:
        return (int(some.group(1)),), None
    scalar, reason = _parse_scalar_result(stdout)
    if reason:
        return None, reason
    return (scalar,), None


def shell_run_query(body: str, ret_type: str, spec_rs: str) -> str:
    """Wrap an interior body in the host ``run_query`` shell.

    The candidate file is only the function interior. Assembly pastes a full
    ``pub exec fn``, so the requires/ensures stay outside the admitted body.
    """
    return build_exec_run_query_from_body(body, ret_type, method_spec_rs=spec_rs)


def _exec_verified_scalar(
    *,
    work_dir: Path,
    sql: str,
    schema_dict: dict[str, str],
    run_query_body: str,
    spec_rs: str,
    ret_type: str,
    tbl_path: Path,
    row_count: int,
) -> dict[str, Any]:
    if resolve_verus_bin() is None:
        return {
            "status": "exec_fail",
            "significant": False,
            "reason": "verus binary not found",
        }
    rs_path = str(work_dir / "adversary_query.rs")
    write_unified_program(
        rs_path=rs_path,
        sql=sql,
        schema=schema_dict,
        runquery_body=shell_run_query(run_query_body, ret_type, spec_rs),
        ret_type=ret_type,
        default_tbl=str(tbl_path),
        workload="adversary",
        query_key="adv",
    )
    verify_timeout = int(os.environ.get("VERUS_VERIFY_TIMEOUT_SEC", "120"))
    compile_timeout = int(os.environ.get("COMPILE_TIMEOUT_SEC", "180"))
    proof_ok, verify_msg = run_verus_verify(rs_path, verify_timeout)
    if not proof_ok:
        return {
            "status": "impl_does_not_fit_spec",
            "significant": False,
            "proof_verified": False,
            "verify_msg": verify_msg[:2000],
        }
    compile_ok, compile_msg, binary = run_verus_compile(rs_path, compile_timeout)
    if not compile_ok or not binary:
        return {
            "status": "exec_fail",
            "significant": False,
            "proof_verified": True,
            "compile_msg": compile_msg[:2000],
        }
    limit = max(row_count, 1)
    try:
        proc = subprocess.run(
            [binary, str(tbl_path), str(limit)],
            capture_output=True,
            text=True,
            timeout=int(os.environ.get("LEMMA_BENCH_TIMEOUT_SEC", "120")),
            cwd=str(work_dir),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "exec_fail",
            "significant": False,
            "proof_verified": True,
            "reason": "binary timed out",
        }
    stdout = proc.stdout or ""
    if proc.returncode != 0:
        return {
            "status": "exec_fail",
            "significant": False,
            "proof_verified": True,
            "stderr": (proc.stderr or "")[:2000],
        }
    printed, opaque_reason = _parse_printed_result(stdout)
    if opaque_reason:
        return {
            "status": "opaque_exec_result",
            "significant": False,
            "reason": opaque_reason,
            "proof_verified": True,
            "stdout": stdout[:500],
        }
    return {
        "status": "exec_ok",
        "proof_verified": True,
        "impl_rows": [printed],
        "stdout": stdout[:500],
    }


def resolve_spec_style(style: str | None = None) -> str:
    """Explicit argument, else ``LEMMA_SPEC_STYLE``, else recursive (the default)."""
    raw = style if style is not None else os.environ.get("LEMMA_SPEC_STYLE", "")
    value = raw.strip().lower()
    if value in ("", "recursive"):
        return "recursive"
    if value == "declarative":
        return "declarative"
    raise ValueError(f"spec style must be recursive or declarative, got {raw!r}")


def judge_candidate(
    candidate: Candidate,
    *,
    config: str = "hardware",
    verify: bool = False,
    work_dir: Path | None = None,
    spec_style: str | None = None,
) -> dict[str, Any]:
    if resolve_spec_style(spec_style) == "declarative":
        from research_loop.adversary.judge_declarative import judge_declarative_candidate

        return judge_declarative_candidate(
            candidate, config=config, verify=verify, work_dir=work_dir
        )
    with apply_trust_config(config):
        admit = admit_runquery_body(candidate.run_query_body)
        if not admit.ok:
            return {
                "status": "rejected",
                "significant": False,
                "violations": admit.violations,
                "config": config,
            }

        if _rows_have_null(candidate.rows):
            return {
                "status": "rows_outside_model",
                "significant": False,
                "reason": "column loads are non-null; SQL NULL is not a cell",
                "config": config,
            }

        if _rows_outside_sql_domain(candidate.schema, candidate.rows):
            return {
                "status": "rows_outside_model",
                "significant": False,
                "reason": "cell is outside the SQL type DuckDB would store",
                "config": config,
            }

        spec_rs, schema_dict, transpile_err = _transpile(candidate.sql, candidate.schema)
        if transpile_err or spec_rs is None or schema_dict is None:
            return {
                "status": "transpile_fail",
                "significant": False,
                "error": transpile_err or "transpile failed",
                "config": config,
            }

        duck_rows, duck_error = _run_duckdb(candidate.sql, candidate.schema, candidate.rows)

        base: dict[str, Any] = {
            "config": config,
            "sql": candidate.sql,
            "duck_rows": duck_rows,
            "duck_error": duck_error,
        }

        if not verify:
            return {
                **base,
                "status": "unchecked_exec",
                "significant": False,
                "spec_rs": spec_rs[:_SPEC_TRUNC],
            }

        if len(candidate.rows) != 1:
            return {
                **base,
                "status": "exec_unsupported",
                "significant": False,
                "reason": "verify path supports a single table only",
            }

        try:
            ret_type = resolve_ret_type_from_method_spec(spec_rs)
        except ValueError as exc:
            return {
                **base,
                "status": "exec_unsupported",
                "significant": False,
                "reason": str(exc),
            }

        if not _scoreable_ret(ret_type):
            return {
                **base,
                "status": "exec_unsupported",
                "significant": False,
                "reason": f"verify path cannot execute return type {ret_type!r}",
            }

        table_name = next(iter(candidate.rows.keys()))
        tables = _schema_tables(candidate.schema)
        if table_name not in tables:
            return {
                **base,
                "status": "exec_unsupported",
                "significant": False,
                "reason": f"rows table {table_name!r} not in schema",
            }

        col_types = tables[table_name]
        schema_for_load = schema_dict
        if set(schema_for_load.keys()) != set(col_types.keys()):
            schema_for_load = {c: col_types[c] for c in col_types if c in schema_for_load or c in col_types}

        def _run_exec(root: Path) -> dict[str, Any]:
            tbl_path = root / f"{table_name}.tbl"
            n = _write_tbl(tbl_path, table_name, col_types, candidate.rows[table_name])
            return _exec_verified_scalar(
                work_dir=root,
                sql=candidate.sql,
                schema_dict=schema_for_load,
                run_query_body=candidate.run_query_body,
                spec_rs=spec_rs,
                ret_type=ret_type,
                tbl_path=tbl_path,
                row_count=n,
            )

        if work_dir is not None:
            exec_res = _run_exec(work_dir)
        else:
            with tempfile.TemporaryDirectory(prefix="lemma_adversary_") as tmp_name:
                exec_res = _run_exec(Path(tmp_name))

        status = exec_res.get("status")
        if status != "exec_ok":
            out = {**base, **exec_res}
            out.setdefault("significant", False)
            return out

        impl_rows = exec_res["impl_rows"]
        verdict = classify_difference(
            candidate.sql,
            impl_rows,
            duck_rows,
            duck_error=duck_error,
        )
        proof_verified = bool(exec_res.get("proof_verified"))
        significant = verdict.significant and proof_verified
        final_status = "hole" if significant else "no_difference"

        return {
            **base,
            **exec_res,
            "status": final_status,
            "significant": significant,
            "reason": verdict.reason,
            "impl_rows": impl_rows,
        }
