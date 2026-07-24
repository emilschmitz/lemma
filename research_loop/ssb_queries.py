"""SSB workload SQL strings and schema fallback for Verus research loop."""

from __future__ import annotations

# Schema copied from research_loop/ssb_workload.py (read-only duplicate for isolation).
fallback_dtypes = {
    "LO_EXTENDEDPRICE": "BIGINT",
    "LO_ORDTOTALPRICE": "BIGINT",
    "LO_REVENUE": "BIGINT",
    "LO_SUPPLYCOST": "BIGINT",
}

schema = {
    "LO_ORDERKEY": "int",
    "LO_LINENUMBER": "int",
    "LO_CUSTKEY": "int",
    "LO_PARTKEY": "int",
    "LO_SUPPKEY": "int",
    "LO_ORDERDATE": "int",
    "LO_ORDERPRIORITY": "string",
    "LO_SHIPPRIORITY": "int",
    "LO_QUANTITY": "int",
    "LO_EXTENDEDPRICE": "int",
    "LO_ORDTOTALPRICE": "int",
    "LO_DISCOUNT": "int",
    "LO_REVENUE": "int",
    "LO_SUPPLYCOST": "int",
    "LO_TAX": "int",
    "LO_COMMITDATE": "int",
    "LO_SHIPMODE": "string",
    "C_NAME": "string",
    "C_ADDRESS": "string",
    "C_CITY": "string",
    "C_NATION": "string",
    "C_REGION": "string",
    "C_PHONE": "string",
    "C_MKTSEGMENT": "string",
    "S_NAME": "string",
    "S_ADDRESS": "string",
    "S_CITY": "string",
    "S_NATION": "string",
    "S_REGION": "string",
    "S_PHONE": "string",
    "P_NAME": "string",
    "P_MFGR": "string",
    "P_CATEGORY": "string",
    "P_BRAND": "string",
    "P_COLOR": "string",
    "P_TYPE": "string",
    "P_SIZE": "int",
    "P_CONTAINER": "string",
    "D_YEAR": "int",
    "D_YEARMONTHNUM": "int",
    "D_WEEKNUMINYEAR": "int",
}

# SQL strings aligned with research_loop/ssb_workload.py `queries` list (15 entries).
queries = [
    """
    SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
    FROM lineorder_flat
    WHERE LO_ORDERDATE >= 19930101 AND LO_ORDERDATE <= 19931231
      AND LO_DISCOUNT >= 1 AND LO_DISCOUNT <= 3
      AND LO_QUANTITY < 25
    """,
    """
    SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
    FROM lineorder_flat
    WHERE LO_ORDERDATE >= 19940101 AND LO_ORDERDATE <= 19940131
      AND LO_DISCOUNT >= 4 AND LO_DISCOUNT <= 6
      AND LO_QUANTITY >= 26 AND LO_QUANTITY <= 35
    """,
    """
    SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
    FROM lineorder_flat
    WHERE D_WEEKNUMINYEAR = 6 AND D_YEAR = 1994
      AND LO_DISCOUNT >= 5 AND LO_DISCOUNT <= 7
      AND LO_QUANTITY >= 26 AND LO_QUANTITY <= 35
    """,
    """
    SELECT D_YEAR, P_BRAND, SUM(LO_REVENUE) AS brand_revenue
    FROM lineorder_flat
    WHERE P_CATEGORY = 'MFGR#12' AND S_REGION = 'AMERICA'
    GROUP BY D_YEAR, P_BRAND
    """,
    """
    SELECT D_YEAR, P_BRAND, SUM(LO_REVENUE) AS brand_revenue
    FROM lineorder_flat
    WHERE P_BRAND = 'MFGR#2221' AND P_SIZE >= 10 AND S_REGION = 'ASIA'
    GROUP BY D_YEAR, P_BRAND
    """,
    """
    SELECT D_YEAR, P_BRAND, SUM(LO_REVENUE) AS brand_revenue
    FROM lineorder_flat
    WHERE P_BRAND = 'MFGR#2221' AND S_REGION = 'EUROPE'
    GROUP BY D_YEAR, P_BRAND
    """,
    """
    SELECT C_NATION, S_NATION, D_YEAR, SUM(LO_REVENUE) AS revenue
    FROM lineorder_flat
    WHERE C_REGION = 'ASIA' AND S_REGION = 'ASIA'
      AND LO_ORDERDATE >= 19920101 AND LO_ORDERDATE <= 19971231
    GROUP BY C_NATION, S_NATION, D_YEAR
    """,
    """
    SELECT C_CITY, S_CITY, D_YEAR, SUM(LO_REVENUE) AS revenue
    FROM lineorder_flat
    WHERE C_NATION = 'UNITED STATES' AND S_NATION = 'UNITED STATES'
      AND LO_ORDERDATE >= 19920101 AND LO_ORDERDATE <= 19971231
    GROUP BY C_CITY, S_CITY, D_YEAR
    """,
    """
    SELECT C_CITY, S_CITY, D_YEAR, SUM(LO_REVENUE) AS revenue
    FROM lineorder_flat
    WHERE C_CITY = 'UNITED KI1' AND S_CITY = 'UNITED KI5'
      AND LO_ORDERDATE >= 19920101 AND LO_ORDERDATE <= 19971231
    GROUP BY C_CITY, S_CITY, D_YEAR
    """,
    """
    SELECT C_CITY, S_CITY, D_YEAR, SUM(LO_REVENUE) AS revenue
    FROM lineorder_flat
    WHERE C_CITY = 'UNITED KI1' AND S_CITY = 'UNITED KI5'
      AND LO_ORDERDATE >= 19971201 AND LO_ORDERDATE <= 19971231
    GROUP BY C_CITY, S_CITY, D_YEAR
    """,
    """
    SELECT D_YEAR, C_NATION, SUM(LO_REVENUE - LO_SUPPLYCOST) AS profit
    FROM lineorder_flat
    WHERE C_REGION = 'AMERICA' AND S_REGION = 'AMERICA' AND P_MFGR = 'MFGR#1'
    GROUP BY D_YEAR, C_NATION
    """,
    """
    SELECT D_YEAR, C_NATION, SUM(LO_REVENUE - LO_SUPPLYCOST) AS profit
    FROM lineorder_flat
    WHERE C_REGION = 'AMERICA' AND S_REGION = 'AMERICA'
      AND LO_ORDERDATE >= 19970101 AND LO_ORDERDATE <= 19981231
      AND P_MFGR = 'MFGR#1'
    GROUP BY D_YEAR, C_NATION
    """,
    """
    SELECT D_YEAR, S_NATION, P_CATEGORY, SUM(LO_REVENUE - LO_SUPPLYCOST) AS profit
    FROM lineorder_flat
    WHERE C_REGION = 'AMERICA' AND S_NATION = 'UNITED STATES'
      AND LO_ORDERDATE >= 19970101 AND LO_ORDERDATE <= 19971231
      AND P_CATEGORY = 'MFGR#14'
    GROUP BY D_YEAR, S_NATION, P_CATEGORY
    """,
    """
    SELECT SUM(LO_EXTENDEDPRICE * LO_DISCOUNT) AS revenue
    FROM lineorder_flat
    WHERE LO_ORDERDATE >= 19940101 AND LO_ORDERDATE <= 19941231
      AND LO_DISCOUNT >= 5 AND LO_DISCOUNT <= 7
      AND LO_QUANTITY < 24
    """,
    """
    SELECT LO_ORDERPRIORITY, SUM(LO_QUANTITY) AS sum_qty
    FROM lineorder_flat
    WHERE LO_ORDERDATE >= 19980901 AND LO_ORDERDATE <= 19981231
    GROUP BY LO_ORDERPRIORITY
    """,
]


def load_schema() -> dict[str, str]:
    """Prefer live DuckDB catalog; fall back to static SSB schema."""
    try:
        from db_extension import DatabaseCatalog

        catalog = DatabaseCatalog()
        return catalog.get_table_schema("lineorder_flat")
    except Exception:
        return dict(schema)
