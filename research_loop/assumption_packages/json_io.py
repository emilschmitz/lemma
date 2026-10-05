"""JSON form of a ``CatalogAssumptions`` package, so a user's package is a file, not code.

Shape (every field optional except ``tables``; an unknown field is an error)::

    {"max_rows": 1024, "max_rows_cube": ..., "max_rows_4": ..., "max_cell_u64": ...,
     "max_native_u32": ..., "max_string_len": ...,
     "tables": {"t": {"max_rows": 1024, "unique_keys": [["id"]],
                      "columns": {"c": {"max_value_exclusive": 64, "scale": 0, "max_string_len": 16,
                                        "max_distinct": 8, "nullable": true}}}},
     "join_caps": [{"left": "a", "right": "b", "equalities": [["x", "y"]], "max_tuples": 4096}]}

``profile.py`` writes this plus the metadata keys ``name`` and ``proposals``, which the loader ignores.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    JoinCap,
    TableAssumptions,
)

_CATALOG_SCALARS = ("max_rows", "max_rows_cube", "max_rows_4", "max_cell_u64", "max_native_u32", "max_string_len")


def catalog_to_dict(catalog: CatalogAssumptions) -> dict[str, Any]:
    """Plain-JSON dict of ``catalog``; ``None`` fields and default column fields are omitted."""
    out: dict[str, Any] = {k: getattr(catalog, k) for k in _CATALOG_SCALARS if getattr(catalog, k) is not None}
    tables: dict[str, Any] = {}
    for tname, ta in catalog.tables.items():
        t: dict[str, Any] = {}
        if ta.max_rows is not None:
            t["max_rows"] = ta.max_rows
        if ta.one_row_per_adsh:
            t["one_row_per_adsh"] = True
        if ta.unique_keys:
            t["unique_keys"] = [list(k) for k in ta.unique_keys]
        t["columns"] = {
            cname: {
                f.name: getattr(ca, f.name)
                for f in dataclasses.fields(ca)
                if getattr(ca, f.name) != f.default
            }
            for cname, ca in ta.columns.items()
        }
        tables[tname] = t
    out["tables"] = tables
    out["join_caps"] = [
        {"left": j.left, "right": j.right, "equalities": [list(e) for e in j.equalities], "max_tuples": j.max_tuples}
        for j in catalog.join_caps
    ]
    return out


def catalog_from_dict(d: dict[str, Any]) -> CatalogAssumptions:
    """Build a catalog from the JSON shape. An unknown field raises ``TypeError`` (fail fast on typos)."""
    scalars = {k: d[k] for k in _CATALOG_SCALARS if k in d}
    tables = {}
    for tname, t in d["tables"].items():
        t = dict(t)
        cols = {c: ColumnAssumption(**ca) for c, ca in t.pop("columns", {}).items()}
        keys = tuple(tuple(k) for k in t.pop("unique_keys", ()))
        tables[tname] = TableAssumptions(columns=cols, unique_keys=keys, **t)
    joins = tuple(
        JoinCap(
            left=j["left"],
            right=j["right"],
            equalities=tuple((a, b) for a, b in j["equalities"]),
            max_tuples=j["max_tuples"],
        )
        for j in d.get("join_caps", ())
    )
    return CatalogAssumptions(tables=tables, join_caps=joins, **scalars)


def load_catalog_json(path: str | Path) -> CatalogAssumptions:
    return catalog_from_dict(json.loads(Path(path).read_text()))
