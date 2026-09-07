"""SQL → Verus Rust transpiler for verified analytical queries."""

from .column_projection import project_multi_schema_for_query, project_schema_for_query
from .parse_sql import UnsupportedContractError
from .query_tables import catalog_tables_in_query, uses_multi_table_program
from .rust_ident import rust_ident
from .transpiler import generate_cols_rs, transpile_sql_to_verus

__all__ = [
    "UnsupportedContractError",
    "catalog_tables_in_query",
    "generate_cols_rs",
    "project_multi_schema_for_query",
    "project_schema_for_query",
    "rust_ident",
    "transpile_sql_to_verus",
    "uses_multi_table_program",
]
