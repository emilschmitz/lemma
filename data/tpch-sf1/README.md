# TPC-H SF1 (integer-normalized)

Pipe-delimited `.tbl` files generated from DuckDB `tpch` extension (`CALL dbgen`).

| Table     | File            |
|-----------|-----------------|
| region    | `region.tbl`    |
| nation    | `nation.tbl`    |
| part      | `part.tbl`      |
| supplier  | `supplier.tbl`  |
| partsupp  | `partsupp.tbl`  |
| customer  | `customer.tbl`  |
| orders    | `orders.tbl`    |
| lineitem  | `lineitem.tbl`  |

Row counts and paths: `dataset_meta.json`.

## Regenerate

```bash
uv run python scripts/export_tpch.py --sf 1
```

Lineitem-only (also writes sibling tables):

```bash
uv run python scripts/export_tpch_lineitem.py --sf 1
```
