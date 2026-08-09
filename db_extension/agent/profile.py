"""Build data profile markdown for agent context."""
from __future__ import annotations

import os
import re
from pathlib import Path

from research_loop.lemma_flags import lemma_agent_duck_explain


def _duck_explain_enabled() -> bool:
    if "LEMMA_AGENT_DUCK_EXPLAIN" in os.environ:
        return lemma_agent_duck_explain()
    try:
        from db_extension.agent.config import DEFAULT_CONFIG_ENV, _load_config_file

        cfg = _load_config_file(DEFAULT_CONFIG_ENV)
        return cfg.get("LEMMA_AGENT_DUCK_EXPLAIN", "0") == "1"
    except ImportError:
        return lemma_agent_duck_explain()


def _try_duckdb():
    try:
        import duckdb
    except ImportError:
        return None
    return duckdb


def _table_name_for_path(data_path: Path) -> str:
    raw = os.environ.get("LEMMA_PROFILE_TABLE", "").strip()
    if raw:
        return raw
    stem = data_path.stem
    # Safe SQL identifier from filename (scan_skew.tbl → scan_skew).
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", stem)
    return cleaned or "data_table"


def _load_table(con, data_path: Path, table: str, row_limit: int | None) -> bool:
    if not data_path.is_file():
        return False
    limit_clause = f" LIMIT {row_limit}" if row_limit else ""
    con.execute(
        f'CREATE TABLE "{table}" AS SELECT * FROM read_csv('
        f"'{data_path}', delim='|', header=True){limit_clause}"
    )
    return True


def build_data_profile(data_path: Path | None, sql_query: str, mode: str) -> str:
    """Return markdown for context/ro/data_profile.md."""
    mode = (mode or "stats").strip().lower()
    duck_explain = _duck_explain_enabled()
    lines = ["# Data profile", "", f"**AGENT_DATA_MODE**: `{mode}`", ""]

    if mode == "none" and not duck_explain:
        lines.extend([
            "Data access is disabled in the container. Use only the transpiled Spec.",
            "",
            "## Target SQL (reference)",
            "```sql",
            sql_query.strip(),
            "```",
        ])
        return "\n".join(lines) + "\n"

    if mode == "none" and duck_explain:
        lines.append(
            "Interactive DuckDB tool is disabled in the container; host injected EXPLAIN/SUMMARIZE below."
        )
        lines.append("")

    duckdb = _try_duckdb()
    if duckdb is None:
        lines.append("_duckdb not available on host; profile is schema-only._")
        return "\n".join(lines) + "\n"

    if data_path is None or not data_path.is_file():
        lines.extend([
            "## No data file",
            f"Expected table file at `{data_path}` but file is missing.",
            "Set `LEMMA_BENCH_TBL` / workload data paths, or generate holdout/TPC-H/SSB data.",
        ])
        return "\n".join(lines) + "\n"

    table = _table_name_for_path(data_path)

    from db_extension.dataset_config import effective_dataset_size

    row_limit = effective_dataset_size()

    con = duckdb.connect(":memory:")
    try:
        if not _load_table(con, data_path, table, row_limit):
            lines.append("Failed to load data.")
            return "\n".join(lines) + "\n"

        n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        lines.extend([
            f"**Table**: `{table}`",
            f"**Rows loaded**: {n:,} (limit {row_limit:,})",
            f"**Source**: `{data_path}`",
            "",
        ])

        include_schema = mode in ("stats", "full")
        if include_schema:
            lines.extend(["## Column types", "```"])
            schema_rows = con.execute(f'DESCRIBE "{table}"').fetchall()
            for row in schema_rows:
                lines.append(f"{row[0]}\t{row[1]}")
            lines.append("```")
            lines.append("")

        include_duck_hints = mode in ("stats", "full") or (mode == "none" and duck_explain)
        if include_duck_hints:
            try:
                summary = con.execute(f'SUMMARIZE "{table}"').fetchdf()
                lines.extend(["## SUMMARIZE", "```", summary.to_string(index=False), "```", ""])
            except Exception as e:
                lines.append(f"_SUMMARIZE failed: {e}_")
                lines.append("")

            try:
                explain = con.execute(f"EXPLAIN {sql_query}").fetchdf()
                lines.extend([
                    "## EXPLAIN (target SQL)",
                    "```",
                    explain.to_string(index=False),
                    "```",
                ])
            except Exception as e:
                lines.extend([f"_EXPLAIN failed: {e}_", ""])

        lines.extend([
            "## Target SQL",
            "```sql",
            sql_query.strip(),
            "```",
        ])
    finally:
        con.close()

    return "\n".join(lines) + "\n"
