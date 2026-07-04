import os
import re
import json
import hashlib

import duckdb
import pandas as pd

from db_extension.dataset_config import effective_dataset_size, tbl_path

# ANSI Color Codes
COLOR_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_RESET = "\033[0m"

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")
BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "queries")

def get_sql_hash(sql: str) -> str:
    # Normalize SQL for hashing
    norm = re.sub(r"\s+", " ", sql).strip().lower()
    return hashlib.md5(norm.encode("utf-8")).hexdigest()

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass

def generate_synthetic_data(dataset_size=50000) -> pd.DataFrame:
    columns = {
        "LO_ORDERKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_LINENUMBER": [1 + (i % 100) for i in range(dataset_size)],
        "LO_CUSTKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_PARTKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_SUPPKEY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_ORDERDATE": [19930101 + (i % 365) for i in range(dataset_size)],
        "LO_ORDERPRIORITY": ["1-URGENT" if (i % 2 == 0) else "2-HIGH" for i in range(dataset_size)],
        "LO_SHIPPRIORITY": [1 + (i % 100) for i in range(dataset_size)],
        "LO_QUANTITY": [i % 50 for i in range(dataset_size)],
        "LO_EXTENDEDPRICE": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_ORDTOTALPRICE": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_DISCOUNT": [i % 10 for i in range(dataset_size)],
        "LO_REVENUE": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_SUPPLYCOST": [1000 + (i % 1000) for i in range(dataset_size)],
        "LO_TAX": [1 + (i % 100) for i in range(dataset_size)],
        "LO_COMMITDATE": [1 + (i % 100) for i in range(dataset_size)],
        "LO_SHIPMODE": ["dummy"] * dataset_size,
        "C_NAME": ["dummy"] * dataset_size,
        "C_ADDRESS": ["dummy"] * dataset_size,
        "C_CITY": ["UNITED KI1" if (i % 2 == 0) else "UNITED KI2" for i in range(dataset_size)],
        "C_NATION": ["UNITED STATES" if (i % 5 == 0) else "UNITED KINGDOM" for i in range(dataset_size)],
        "C_REGION": ["AMERICA" if (i % 2 == 0) else "ASIA" for i in range(dataset_size)],
        "C_PHONE": ["dummy"] * dataset_size,
        "C_MKTSEGMENT": ["dummy"] * dataset_size,
        "S_NAME": ["dummy"] * dataset_size,
        "S_ADDRESS": ["dummy"] * dataset_size,
        "S_CITY": ["UNITED KI5" if (i % 2 == 0) else "UNITED KI6" for i in range(dataset_size)],
        "S_NATION": ["UNITED STATES" if (i % 5 == 0) else "UNITED KINGDOM" for i in range(dataset_size)],
        "S_REGION": ["AMERICA" if (i % 2 == 0) else "ASIA" for i in range(dataset_size)],
        "S_PHONE": ["dummy"] * dataset_size,
        "P_NAME": ["dummy"] * dataset_size,
        "P_MFGR": ["dummy"] * dataset_size,
        "P_CATEGORY": ["MFGR#12" if (i % 3 == 0) else "MFGR#14" for i in range(dataset_size)],
        "P_BRAND": ["MFGR#2221" if (i % 4 == 0) else "MFGR#2222" for i in range(dataset_size)],
        "P_COLOR": ["dummy"] * dataset_size,
        "P_TYPE": ["dummy"] * dataset_size,
        "P_SIZE": [1 + (i % 100) for i in range(dataset_size)],
        "P_CONTAINER": ["dummy"] * dataset_size,
        "D_YEAR": [1992 + (i % 7) for i in range(dataset_size)],
        "D_YEARMONTHNUM": [1 + (i % 100) for i in range(dataset_size)],
        "D_WEEKNUMINYEAR": [1 + (i % 52) for i in range(dataset_size)]
    }
    return pd.DataFrame(columns)

def print_result_table(df: pd.DataFrame):
    if df.empty:
        print("Empty result (0 rows)")
        return
    print(df.to_string(index=False))


def truncate_for_box(text: str, width: int = 18) -> str:
    """Conservative single-line truncation for DuckDB CLI box display."""
    text = str(text).replace("\n", " ").strip()
    if width < 4 or len(text) <= width:
        return text
    return text[: width - 1] + "…"


def demo_box_width() -> int | None:
    raw = os.environ.get("LEMMA_DEMO_BOX", os.environ.get("LEMMA_LIMIT_BOX", "0")).strip()
    if raw in ("0", "false", "False", ""):
        return None
    if raw in ("1", "true", "True"):
        return int(os.environ.get("LEMMA_DEMO_BOX_WIDTH", "18"))
    try:
        return max(4, int(raw))
    except ValueError:
        return 18


def format_scalar_for_box(val) -> str:
    """Format a single query result cell for lemma()'s stdout → DuckDB box."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if val.is_integer() and abs(val) < 1e15:
            return str(int(val))
        return format(val, ".15g")
    text = str(val).strip()
    if re.fullmatch(r"-?\d+\.0+", text):
        return text.split(".", 1)[0]
    width = demo_box_width()
    if width is not None:
        text = truncate_for_box(text, width)
    return text


def sql_result_schema(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[list[str], list[str]]:
    """Column names and DuckDB type strings for any SELECT (generic)."""
    cur = con.execute(sql)
    desc = cur.description or []
    names = [d[0] for d in desc]
    types = [str(d[1]) if len(d) > 1 else "" for d in desc]
    return names, types


def is_integer_result_type(type_str: str) -> bool:
    t = type_str.upper()
    return any(k in t for k in ("INT", "HUGEINT", "BIGINT", "SMALLINT", "TINYINT", "UBIGINT"))


def quote_sql_identifier(name: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return name
    return '"' + name.replace('"', '""') + '"'


def escape_sql_string_literal(sql: str) -> str:
    return sql.replace("'", "''")


def lemma_select_line(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    """Build a lemma() SELECT with short column label and native-looking numeric type when possible."""
    names, types = sql_result_schema(con, sql)
    alias = quote_sql_identifier(names[0] if len(names) == 1 else "result")
    inner = escape_sql_string_literal(sql.strip())
    call = f"lemma('{inner}')"
    if len(names) == 1 and is_integer_result_type(types[0]):
        return f"SELECT CAST({call} AS HUGEINT) AS {alias}"
    return f"SELECT {call} AS {alias}"

def setup_db(con: duckdb.DuckDBPyConnection, *, quiet: bool = False):
    flat_path = tbl_path()
    row_limit = effective_dataset_size()

    if not flat_path.exists():
        raise FileNotFoundError(
            f"Real SSB flat table not found at {flat_path}.\n"
            "Run: ./scripts/build_ssb_flat_dataset.sh"
        )

    if quiet:
        con.execute("SET enable_progress_bar = false")

    if not quiet:
        print(f"Loading table 'lineorder_flat' from {flat_path} ({row_limit:,} rows)...")
    con.execute(
        f"CREATE TABLE lineorder_flat AS SELECT * FROM read_csv('{flat_path}', delim='|', header=True) LIMIT {row_limit}"
    )
    if not quiet:
        print(f"{COLOR_GREEN}Loaded {row_limit:,} rows into 'lineorder_flat'.{COLOR_RESET}")
