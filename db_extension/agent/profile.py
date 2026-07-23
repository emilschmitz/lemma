"""Build data profile markdown for agent context."""
from __future__ import annotations

from pathlib import Path


def _try_duckdb():
    try:
        import duckdb
    except ImportError:
        return None
    return duckdb


def _load_table(con, data_path: Path, row_limit: int | None) -> bool:
    if not data_path.is_file():
        return False
    limit_clause = f" LIMIT {row_limit}" if row_limit else ""
    con.execute(
        f"CREATE TABLE lineorder_flat AS SELECT * FROM read_csv("
        f"'{data_path}', delim='|', header=True){limit_clause}"
    )
    return True


def build_data_profile(data_path: Path | None, sql_query: str, mode: str) -> str:
    """Return markdown for context/ro/data_profile.md."""
    mode = (mode or "stats").strip().lower()
    lines = ["# Data profile", "", f"**AGENT_DATA_MODE**: `{mode}`", ""]

    if mode == "none":
        lines.extend([
            "Data access is disabled in the container. Use only the transpiled `spec.dfy`.",
            "",
            "## Target SQL (reference)",
            "```sql",
            sql_query.strip(),
            "```",
        ])
        return "\n".join(lines) + "\n"

    duckdb = _try_duckdb()
    if duckdb is None:
        lines.append("_duckdb not available on host; profile is schema-only._")
        return "\n".join(lines) + "\n"

    if data_path is None or not data_path.is_file():
        lines.extend([
            "## No data file",
            f"Expected flat table at `{data_path}` but file is missing.",
            "Run `./scripts/build_ssb_flat_dataset.sh` on the host.",
        ])
        return "\n".join(lines) + "\n"

    try:
        from db_extension.dataset_config import effective_dataset_size

        row_limit = effective_dataset_size()
    except ImportError:
        row_limit = 2_000_000

    con = duckdb.connect(":memory:")
    try:
        if not _load_table(con, data_path, row_limit):
            lines.append("Failed to load data.")
            return "\n".join(lines) + "\n"

        n = con.execute("SELECT COUNT(*) FROM lineorder_flat").fetchone()[0]
        lines.extend([
            "**Table**: `lineorder_flat`",
            f"**Rows loaded**: {n:,} (limit {row_limit:,})",
            f"**Source**: `{data_path}`",
            "",
            "## Column types",
            "```",
        ])
        schema_rows = con.execute("DESCRIBE lineorder_flat").fetchall()
        for row in schema_rows:
            lines.append(f"{row[0]}\t{row[1]}")
        lines.append("```")
        lines.append("")

        if mode in ("stats", "full"):
            try:
                summary = con.execute("SUMMARIZE lineorder_flat").fetchdf()
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
