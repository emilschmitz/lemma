"""Gate DuckDB SQL by agent data mode (none | stats | full)."""
from __future__ import annotations

import re

_WRITE_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|REPLACE|COPY|ATTACH|DETACH|INSTALL|LOAD|"
    r"EXPORT|IMPORT|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CALL|SET|RESET)\b",
    re.IGNORECASE,
)

_AGG_FUNCS = re.compile(
    r"\b(COUNT|SUM|AVG|MIN|MAX|APPROX_COUNT_DISTINCT|APPROX_QUANTILE|"
    r"STDDEV|STDDEV_SAMP|STDDEV_POP|VARIANCE|VAR_SAMP|VAR_POP|"
    r"BOOL_AND|BOOL_OR|STRING_AGG|GROUP_CONCAT|LISTAGG)\s*\(",
    re.IGNORECASE,
)

_ALLOWED_STARTS = re.compile(
    r"^\s*(SELECT|EXPLAIN|SUMMARIZE|SHOW|DESCRIBE|DESC|PRAGMA)\b",
    re.IGNORECASE | re.DOTALL,
)

_SELECT_STAR = re.compile(r"\bSELECT\s+(DISTINCT\s+)?\*\b", re.IGNORECASE)
_LIMIT = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)
_BARE_COLUMN_SELECT = re.compile(
    r"\bSELECT\s+(DISTINCT\s+)?(?![\s(]*(?:COUNT|SUM|AVG|MIN|MAX|APPROX_)\s*\()"
    r"(?:[a-zA-Z_][\w.]*\s*,\s*)*[a-zA-Z_][\w.]*",
    re.IGNORECASE,
)


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip())


def _is_read_only(sql: str) -> str | None:
    norm = _normalize(sql)
    if not _ALLOWED_STARTS.match(norm):
        return "only read-only queries (SELECT, EXPLAIN, SUMMARIZE, SHOW, DESCRIBE, PRAGMA) are allowed"
    if _WRITE_KEYWORDS.search(norm):
        return "write or DDL statements are not allowed in this mode"
    upper = norm.upper()
    if upper.startswith("PRAGMA"):
        allowed_pragma = (
            "TABLE_INFO",
            "SHOW_TABLES",
            "DATABASE_LIST",
            "TABLE_LIST",
            "SHOW",
        )
        if not any(p in upper for p in allowed_pragma):
            return "only read-only PRAGMA (table_info, show_tables, etc.) allowed"
    if upper.startswith("SET ") or upper.startswith("RESET "):
        return "SET/RESET not allowed"
    return None


def _is_stats_query(sql: str) -> str | None:
    norm = _normalize(sql)
    upper = norm.upper()

    if upper.startswith("EXPLAIN") or upper.startswith("SUMMARIZE"):
        return None
    if upper.startswith("SHOW ") or upper.startswith("DESCRIBE") or upper.startswith("DESC "):
        return None
    if upper.startswith("PRAGMA"):
        return None

    if not upper.startswith("SELECT"):
        return "stats mode allows aggregate/stats SELECT queries only"

    if _SELECT_STAR.search(norm):
        return "SELECT * is not allowed in stats mode"

    if _LIMIT.search(norm) and not _AGG_FUNCS.search(norm):
        return "LIMIT without aggregates looks like row sampling (not allowed in stats mode)"

    if _BARE_COLUMN_SELECT.search(norm) and not _AGG_FUNCS.search(norm):
        return "bare column SELECT without aggregates is not allowed in stats mode"

    if not _AGG_FUNCS.search(norm):
        # Allow simple scalar subqueries / COUNT(*) style checks
        if re.search(r"\bCOUNT\s*\(\s*\*\s*\)", norm, re.IGNORECASE):
            return None
        return "stats mode requires aggregate functions (COUNT, SUM, AVG, MIN, MAX, APPROX_*)"

    return None


def check_duckdb_sql(sql: str, mode: str) -> str | None:
    """Return error message if SQL is rejected, else None."""
    mode = (mode or "stats").strip().lower()
    if mode == "none":
        return "duckdb_sql is disabled (AGENT_DATA_MODE=none)"
    if mode == "full":
        return _is_read_only(sql)
    if mode == "stats":
        ro_err = _is_read_only(sql)
        if ro_err:
            return ro_err
        return _is_stats_query(sql)
    return f"unknown AGENT_DATA_MODE: {mode!r}"
