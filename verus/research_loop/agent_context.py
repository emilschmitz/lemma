"""Agent context: hardware profile, aggregate table stats, optional DuckDB EXPLAIN hints."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from verus.research_loop.agent_primitives.emit_externs import lemma_enable_parallel
from verus.research_loop.lemma_flags import (
    lemma_enable_parallel as _lemma_enable_parallel_flag,
    lemma_enable_spill_hash,
    lemma_enable_vector_scan,
    lemma_hash_spill_bytes,
    lemma_load_from_duckdb,
)


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default) == "1"


def _parse_cache_kb(path: str) -> int | None:
    try:
        with open(path, encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def hardware_profile() -> dict[str, Any]:
    """CPU count and optional cache sizes (sysfs or LEMMA_ASSUMED_L* overrides)."""
    profile: dict[str, Any] = {
        "cpu_count": os.cpu_count() or 1,
        "parallel_enabled": lemma_enable_parallel(),
    }
    for level, env_key, sysfs in (
        ("l1d_kb", "LEMMA_ASSUMED_L1", "/sys/devices/system/cpu/cpu0/cache/index0/size"),
        ("l2_kb", "LEMMA_ASSUMED_L2", "/sys/devices/system/cpu/cpu0/cache/index2/size"),
        ("l3_kb", "LEMMA_ASSUMED_L3", "/sys/devices/system/cpu/cpu0/cache/index3/size"),
    ):
        if env_key in os.environ:
            try:
                profile[level] = int(os.environ[env_key])
                continue
            except ValueError:
                pass
        raw = _parse_cache_kb(sysfs) if os.path.exists(sysfs) else None
        if raw is not None:
            profile[level] = raw
    return profile


def _histogram_u32(col: list[int], bins: int) -> list[int]:
    bins = max(1, bins)
    if not col:
        return [0] * bins
    lo = min(col)
    hi = max(col)
    if lo == hi:
        h = [0] * bins
        h[0] = len(col)
        return h
    span = hi - lo + 1
    hist = [0] * bins
    for v in col:
        bin_idx = min(bins - 1, (v - lo) * bins // span)
        hist[bin_idx] += 1
    return hist


def column_stats_bundle(
    col_vals: list[Any],
    *,
    dtype: str,
    histogram_bins: int = 64,
) -> dict[str, Any]:
    """Rich per-column stats for agent context (mirrors Rust `column_stats_bundle_*`)."""
    bins = max(1, histogram_bins)
    if dtype == "u32":
        numeric = [int(v) for v in col_vals]
        return {
            "dtype": "u32",
            "count": len(numeric),
            "min": min(numeric) if numeric else None,
            "max": max(numeric) if numeric else None,
            "approx_distinct": _approx_distinct(numeric),
            "histogram_bins": bins,
            "histogram": _histogram_u32(numeric, bins),
        }
    if dtype == "u64":
        numeric = [int(v) for v in col_vals]
        return {
            "dtype": "u64",
            "count": len(numeric),
            "min": min(numeric) if numeric else None,
            "max": max(numeric) if numeric else None,
            "approx_distinct": _approx_distinct(numeric),
            "histogram_bins": bins,
            "histogram": _histogram_u32(numeric, bins),
        }
    empty = sum(1 for v in col_vals if v == "" or str(v).upper() == "NULL")
    return {
        "dtype": "string",
        "count": len(col_vals),
        "null_rate": empty / len(col_vals) if col_vals else 0.0,
        "approx_distinct": _approx_distinct(col_vals),
        "max_len": max((len(str(v)) for v in col_vals), default=0),
        "histogram_bins": bins,
        "histogram": [],
    }


def _zone_segments_u32(col: list[int], zone_rows: int) -> list[dict[str, int]]:
    if not col:
        return []
    zone_rows = max(1, zone_rows)
    zones: list[dict[str, int]] = []
    start = 0
    while start < len(col):
        end = min(start + zone_rows, len(col))
        seg = col[start:end]
        zones.append(
            {
                "min": min(seg),
                "max": max(seg),
                "start": start,
                "end": end,
            }
        )
        start = end
    return zones


def _approx_distinct(values: list[Any]) -> int:
    """HyperLogLog-lite NDV estimate (no row samples in output)."""
    registers = [0] * 256
    for v in values:
        h = hash(v) & ((1 << 64) - 1)
        idx = h & 255
        rho = min(63, (h >> 8).bit_length()) + 1 if h >> 8 else 1
        registers[idx] = max(registers[idx], rho)
    alpha = 0.7213 / (1.0 + 1.079 / 256)
    sum_inv = sum(2.0 ** (-r) for r in registers)
    return max(1, round(alpha * 256 * 256 / sum_inv))


def _load_pipe_tbl(
    tbl_path: str,
    columns: list[str] | None,
    *,
    limit: int | None,
) -> tuple[list[str], list[list[str]]]:
    rows: list[list[str]] = []
    with open(tbl_path, encoding="utf-8") as f:
        header = f.readline().strip()
        if not header:
            return [], rows
        hdr_cols = [c.strip().upper() for c in header.split("|")]
        want = [c.upper() for c in columns] if columns else hdr_cols
        idx_map = [hdr_cols.index(c) for c in want]
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            parts = line.rstrip("\n").split("|")
            if not parts:
                continue
            rows.append([parts[j].strip().strip('"') for j in idx_map])
    return want, rows


def table_aggregate_stats(
    tbl_path: str,
    columns: list[str],
    *,
    limit: int | None = None,
    zone_rows: int = 65536,
) -> dict[str, Any]:
    """Aggregate stats + zone maps only — never raw row dumps."""
    want, rows = _load_pipe_tbl(tbl_path, columns, limit=limit)
    out: dict[str, Any] = {
        "path": tbl_path,
        "row_count": len(rows),
        "columns": {},
    }
    if not rows:
        return out
    ncol = len(want)
    for ci, col in enumerate(want):
        col_vals = [r[ci] for r in rows]
        numeric_u32: list[int] | None = None
        numeric_u64: list[int] | None = None
        try:
            numeric_u32 = [int(v) for v in col_vals]
        except ValueError:
            pass
        if numeric_u32 is None:
            try:
                numeric_u64 = [int(v) for v in col_vals]
            except ValueError:
                pass
        col_stat: dict[str, Any] = {"dtype": "string"}
        if numeric_u32 is not None:
            col_stat = column_stats_bundle(col_vals, dtype="u32")
            col_stat["zone_map"] = _zone_segments_u32(numeric_u32, zone_rows)
        elif numeric_u64 is not None:
            col_stat = column_stats_bundle(col_vals, dtype="u64")
            col_stat["zone_map"] = _zone_segments_u32(numeric_u64, zone_rows)
        else:
            col_stat = column_stats_bundle(col_vals, dtype="string")
        out["columns"][col] = col_stat
    return out


def duckdb_plan_hints(sql: str, tbl_paths: dict[str, str]) -> dict[str, Any] | None:
    """Optional EXPLAIN / SUMMARIZE hints; never executes the analytical query."""
    if not _env_bool("LEMMA_AGENT_DUCK_EXPLAIN", "0"):
        return None
    try:
        import duckdb
    except ImportError:
        return {"available": False, "reason": "duckdb not installed"}
    con = duckdb.connect()
    try:
        for alias, path in tbl_paths.items():
            safe = re.sub(r"[^a-zA-Z0-9_]", "_", alias)
            con.execute(
                f"CREATE OR REPLACE VIEW {safe} AS SELECT * FROM read_csv("
                f"'{path}', delim='|', header=true, quote='\"')"
            )
        plan = con.execute(f"EXPLAIN {sql}").fetchall()
        hints: dict[str, Any] = {
            "available": True,
            "explain": [list(row) for row in plan],
            "summarize": {},
        }
        for alias, path in tbl_paths.items():
            safe = re.sub(r"[^a-zA-Z0-9_]", "_", alias)
            try:
                summ = con.execute(f"SUMMARIZE {safe}").fetchdf()
                hints["summarize"][alias] = summ.to_dict(orient="records")
            except Exception as e:
                hints["summarize"][alias] = {"error": str(e)}
        return hints
    except Exception as e:
        return {"available": True, "error": str(e)}
    finally:
        con.close()


def write_agent_context(path: str | Path, **blobs: Any) -> Path:
    """Write JSON agent context next to pending_runquery artifacts."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(blobs, f, indent=2)
        f.write("\n")
    return p


def build_agent_context(
    *,
    sql: str,
    schema: dict,
    tbl_paths: dict[str, str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Assemble context dict honoring LEMMA_AGENT_* flags."""
    ctx: dict[str, Any] = {"sql": sql, "schema_summary": schema}
    if _env_bool("LEMMA_AGENT_HARDWARE", "1"):
        ctx["hardware"] = hardware_profile()
    if _env_bool("LEMMA_AGENT_STATS", "1") and tbl_paths:
        ctx["table_stats"] = {
            alias: table_aggregate_stats(
                path,
                _columns_for_table(schema, alias),
                limit=limit,
            )
            for alias, path in tbl_paths.items()
            if path and os.path.isfile(path)
        }
    if _env_bool("LEMMA_AGENT_DUCK_EXPLAIN", "0") and tbl_paths:
        hints = duckdb_plan_hints(sql, tbl_paths)
        if hints is not None:
            ctx["duckdb_hints"] = hints
    ctx["flags"] = {
        "LEMMA_ENABLE_PARALLEL": _lemma_enable_parallel_flag(),
        "LEMMA_ENABLE_VECTOR_SCAN": lemma_enable_vector_scan(),
        "LEMMA_ENABLE_SPILL_HASH": lemma_enable_spill_hash(),
        "LEMMA_HASH_SPILL_BYTES": lemma_hash_spill_bytes(),
        "LEMMA_LOAD_FORMAT": os.environ.get("LEMMA_LOAD_FORMAT", "lemma_columnar"),
        "LEMMA_LOAD_FROM_DUCKDB": lemma_load_from_duckdb(),
        "ENABLE_TEMPLATES": _env_bool("ENABLE_TEMPLATES", "0"),
    }
    return ctx


def _columns_for_table(schema: dict, table: str) -> list[str]:
    from verus_transpiler.parse_sql import normalize_schema

    flat, multi = normalize_schema(schema)
    if multi:
        if table in multi:
            return list(multi[table].keys())
        return list(next(iter(multi.values())).keys())
    return list(flat.keys())
