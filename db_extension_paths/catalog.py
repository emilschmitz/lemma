"""DuckDB catalog helpers for Verus experiments."""
from __future__ import annotations

import os
import re

import duckdb


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DatabaseCatalog:
    def __init__(self, database_path: str | None = None):
        self.database_path = database_path or ":memory:"
        self.con = None

    def _ensure_connection(self):
        if self.con is None:
            try:
                self.con = duckdb.connect(self.database_path)
            except Exception:
                pass

    def get_table_schema(self, table_name: str) -> dict[str, str]:
        self._ensure_connection()
        schema_dict: dict[str, str] = {}

        if table_name.lower() == "lineorder_flat":
            from research_loop.ssb_workload import fallback_dtypes, schema as ssb_schema

            return {
                col: (fallback_dtypes.get(col, "INTEGER") if t == "int" else "VARCHAR")
                for col, t in ssb_schema.items()
            }
        if table_name.lower() == "lineitem":
            from research_loop.tpch_workload import schema as tpch_schema

            return dict(tpch_schema)

        if self.con:
            try:
                query = """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE lower(table_name) = lower(?);
                """
                res = self.con.execute(query, [table_name]).fetchall()
                if res:
                    for col_name, data_type in res:
                        schema_dict[col_name.upper()] = data_type.upper()
                    return schema_dict
            except Exception:
                pass

        ddl_path = os.path.join(_repo_root(), "ssb-dbgen", "dss.ddl")
        if os.path.exists(ddl_path):
            schema_dict = self._parse_ddl_file(ddl_path, table_name)
            if schema_dict:
                return schema_dict
        return {}

    def get_primary_keys(self, table_name: str) -> list[str]:
        self._ensure_connection()
        pks: list[str] = []
        if self.con:
            try:
                query = """
                    SELECT column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.constraint_type = 'PRIMARY KEY' AND lower(tc.table_name) = lower(?);
                """
                res = self.con.execute(query, [table_name]).fetchall()
                pks = [row[0].upper() for row in res]
            except Exception:
                pass
        return pks

    def _parse_ddl_file(self, file_path: str, table_name: str) -> dict[str, str]:
        schema_dict: dict[str, str] = {}
        try:
            with open(file_path) as f:
                content = f.read()
            content = re.sub(r"--.*", "", content)
            pattern = re.compile(
                rf"CREATE\s+TABLE\s+(?:\w+\.)?{table_name}\s*\(([\s\S]*?)\);",
                re.IGNORECASE,
            )
            match = pattern.search(content)
            if not match:
                return {}
            columns_part = match.group(1)
            for line in columns_part.split(","):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    col_name = parts[0].strip('"`[]').upper()
                    data_type = parts[1].upper()
                    if any(t in data_type for t in ("INT", "KEY", "DATE", "NUM", "YEAR", "DECIMAL", "NUMERIC")):
                        schema_dict[col_name] = "int"
                    else:
                        schema_dict[col_name] = "string"
        except Exception:
            pass
        return schema_dict
