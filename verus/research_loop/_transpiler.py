"""Transpiler import shim — adds verus/src to path when package not installed."""
from __future__ import annotations

import os
import sys

_VERUS_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _VERUS_SRC not in sys.path:
    sys.path.insert(0, _VERUS_SRC)

from verus_transpiler import (  # noqa: E402
    generate_cols_rs,
    project_multi_schema_for_query,
    project_schema_for_query,
    transpile_sql_to_verus,
)

__all__ = [
    "transpile_sql_to_verus",
    "project_schema_for_query",
    "project_multi_schema_for_query",
    "generate_cols_rs",
]
