"""Propose an assumption package from a user's DuckDB.

``uv run python -m research_loop.assumption_packages.profile --db data.duckdb --name mypkg --out mypkg.json
[--margin 4] [--value-margin 1] [--join a.x=b.y,a.z=b.w ...]``

Measures with the same rules and code as ``check.py`` (so a generated package passes it on the same data), then writes

* ``<out>``: the machine-readable package (``json_io.py``), loadable as ``LEMMA_ASSUMPTION_PACKAGE=<out>``;
* ``<out>`` with suffix ``.md``: a plain-language report, one row per bound.

Proposals, not truth. A cap is the measured value rounded UP to a power of two (rows, distinct counts and join sizes
first times ``--margin``, default 4; value caps times ``--value-margin``, default 1). Unique keys are listed under
``proposals`` in the JSON and are NOT in the package until the user moves them into a table's ``unique_keys``.
A column with no NULL is declared (by omission) to hold none; that is a claim about future data too.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from db_extension.dataset_config import (
    _FLOAT_DUCKDB_TYPES,
    _INTEGER_DUCKDB_TYPES,
    _quote_duckdb_ident,
)
from research_loop.assumption_packages.check import (
    _NARROW_INT_TYPES,
    _STRING_TYPES,
    _max_group,
    _max_len,
    _max_value,
)
from research_loop.assumption_packages.json_io import catalog_to_dict
from research_loop.table_assumptions import (
    CatalogAssumptions,
    ColumnAssumption,
    JoinCap,
    TableAssumptions,
)

_NUMERIC = _INTEGER_DUCKDB_TYPES | _FLOAT_DUCKDB_TYPES | {"decimal"}
_WIDE = (_INTEGER_DUCKDB_TYPES - _NARROW_INT_TYPES) | _FLOAT_DUCKDB_TYPES  # u64 cells (catalog max_cell_u64)


def pow2_at_least(n: int) -> int:
    """Smallest power of two >= n (>= 1)."""
    return 1 << max(n - 1, 0).bit_length()


def pow2_above(n: int) -> int:
    """Smallest power of two strictly greater than n (an exclusive cap that n sits under)."""
    return 1 << max(n, 0).bit_length()


def parse_join(spec: str) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """``a.x=b.y,a.z=b.w`` -> (``a``, ``b``, ((``x``, ``y``), (``z``, ``w``))). Both sides must name one table each."""
    pairs = []
    left = right = None
    for part in spec.split(","):
        (lt, lc), (rt, rc) = (side.strip().split(".", 1) for side in part.split("="))
        if left not in (None, lt) or right not in (None, rt):
            raise ValueError(f"join {spec!r}: every equality must be between the same two tables")
        left, right = lt, rt
        pairs.append((lc, rc))
    assert left is not None and right is not None
    return left, right, tuple(pairs)


def _schema(con: Any) -> tuple[dict[str, dict[str, str]], dict[tuple[str, str], int]]:
    types: dict[str, dict[str, str]] = {}
    scales: dict[tuple[str, str], int] = {}
    for t, c, d in con.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
    ).fetchall():
        full = str(d).lower()
        types.setdefault(str(t), {})[str(c)] = full.split("(")[0]
        if full.startswith("decimal("):
            scales[(str(t), str(c))] = int(full.rstrip(")").split(",")[1])
    return types, scales


def _declared_keys(con: Any, table: str) -> list[tuple[str, ...]]:
    rows = con.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE schema_name = 'main' AND table_name = ? AND constraint_type IN ('PRIMARY KEY', 'UNIQUE')",
        [table],
    ).fetchall()
    return [tuple(r[0]) for r in rows]


def _id_like(col: str) -> bool:
    c = col.casefold()
    return c == "id" or c.endswith("_id")


def profile(
    con: Any,
    *,
    margin: int = 4,
    value_margin: int = 1,
    joins: tuple[str, ...] = (),
) -> tuple[CatalogAssumptions, list[dict[str, Any]], dict[str, list[list[str]]]]:
    """Return (proposed catalog, report rows, proposed unique keys per table)."""
    types, scales = _schema(con)
    report: list[dict[str, Any]] = []

    def row(bound: str, measured: Any, cap: Any, breaks: str, effect: str) -> None:
        report.append({"bound": bound, "measured": measured, "cap": cap, "breaks": breaks, "effect": effect})

    tables: dict[str, TableAssumptions] = {}
    proposals: dict[str, list[list[str]]] = {}
    wide_caps: list[int] = []
    narrow_caps: list[int] = []
    string_caps: list[int] = []
    for t, cols in types.items():
        qt = _quote_duckdb_ident(t)
        n = int(con.execute(f"SELECT COUNT(*) FROM {qt}").fetchone()[0])
        row_cap = pow2_at_least(max(n, 1) * margin)
        row(
            f"{t}: rows", n, row_cap,
            "load fails: more rows than the proof's index range",
            "sets integer widths of counters and loop indices; smaller is easier to prove and faster",
        )
        nulls = {}
        all_distinct: list[str] = []  # string columns with no NULL where every cell is different
        if n:
            listed = ", ".join(f"COUNT(*) FILTER (WHERE {_quote_duckdb_ident(c)} IS NULL)" for c in cols)
            nulls = dict(zip(cols, con.execute(f"SELECT {listed} FROM {qt}").fetchone(), strict=True))
        col_asm: dict[str, ColumnAssumption] = {}
        for c, base in cols.items():
            qc = _quote_duckdb_ident(c)
            null_n = int(nulls.get(c, 0))
            kw: dict[str, Any] = {"nullable": null_n > 0}
            if null_n:
                row(
                    f"{t}.{c}: nullable", f"{null_n} NULL cells", "nullable",
                    "n/a (declared)",
                    "adds a validity vector; queries follow SQL three-valued logic (slower, more to prove)",
                )
            else:
                row(
                    f"{t}.{c}: NOT NULL", "0 NULL cells", "no NULL",
                    "load fails on the first NULL cell",
                    "no validity vector; simplest and fastest",
                )
            if base in _NUMERIC:
                scale = scales.get((t, c), 0)
                m = _max_value(con, t, c, base, scale)
                if m is not None:
                    cap = pow2_above(m * value_margin)
                    kw.update(max_value_exclusive=cap, scale=scale)
                    unit = f" (stored integer, value x 10^{scale})" if base == "decimal" else ""
                    row(
                        f"{t}.{c}: max abs(value){unit}", m, f"< {cap}",
                        "load fails; sums over the column may overflow the proof's integer width",
                        "picks the cell width (u32/u64/i128); sums and products are proved against it",
                    )
                    if base in _NARROW_INT_TYPES:
                        narrow_caps.append(cap)
                    elif base in _WIDE:
                        wide_caps.append(cap)
            elif base in _STRING_TYPES:
                m = _max_len(con, t, c)
                d = int(con.execute(f"SELECT COUNT(DISTINCT {qc}) FROM {qt}").fetchone()[0])
                if m is not None:
                    cap = pow2_at_least(m)
                    kw["max_string_len"] = cap
                    string_caps.append(cap)
                    row(
                        f"{t}.{c}: max length", m, cap,
                        "load fails on a longer string",
                        "bounds string comparison/hash work and buffer sizes",
                    )
                if n > 1 and d == n and not null_n:
                    all_distinct.append(c)
                dcap = pow2_at_least(max(d, 1) * margin)
                kw["max_distinct"] = dcap
                row(
                    f"{t}.{c}: distinct values", d, dcap,
                    "load fails when the dictionary outgrows the code width",
                    "picks the dictionary code width (u8/u16/u32); narrower is faster",
                )
            col_asm[c] = ColumnAssumption(**kw)

        keys: list[tuple[str, ...]] = []
        for k in _declared_keys(con, t):
            if k not in keys:
                keys.append(k)
        for c in cols:
            if (_id_like(c) or c in all_distinct) and (c,) not in keys:
                keys.append((c,))
        proven = [k for k in keys if all(c in cols for c in k) and (_max_group(con, t, k) or 0) <= 1]
        if proven and n:
            proposals[t] = [list(k) for k in proven]
            for k in proven:
                row(
                    f"{t}: unique key ({', '.join(k)})", "no duplicates today", "PROPOSAL only",
                    "if the user claims it and data repeats a key, proofs about joins on it are vacuous",
                    "lets a join add each outer cell once (tighter sums, no row-multiplication)",
                )
        tables[t] = TableAssumptions(max_rows=row_cap, columns=col_asm)

    join_caps = []
    for spec in joins:
        lt, rt, eqs = parse_join(spec)
        on = " AND ".join(f"l.{_quote_duckdb_ident(a)} = r.{_quote_duckdb_ident(b)}" for a, b in eqs)
        m = int(
            con.execute(
                f"SELECT COUNT(*) FROM {_quote_duckdb_ident(lt)} l JOIN {_quote_duckdb_ident(rt)} r ON {on}"
            ).fetchone()[0]
        )
        cap = pow2_at_least(max(m, 1) * margin)
        join_caps.append(JoinCap(lt, rt, eqs, cap))
        row(
            f"join {lt} x {rt} on {spec}", m, cap,
            "load fails when the join has more tuples",
            "bounds the join's output size, so counts and sums over it fit their integer widths",
        )

    all_rows = max((ta.max_rows or 1 for ta in tables.values()), default=1)
    catalog = CatalogAssumptions(
        tables=tables,
        max_rows=all_rows,
        max_rows_cube=all_rows,
        max_rows_4=all_rows,
        max_cell_u64=max(wide_caps) if wide_caps else None,
        max_native_u32=max([2**31, *narrow_caps]),
        max_string_len=max(string_caps) if string_caps else None,
        join_caps=tuple(join_caps),
    )
    return catalog, report, proposals


def render_report(name: str, report: list[dict[str, Any]]) -> str:
    lines = [
        f"# Proposed assumptions: {name}",
        "",
        "These are PROPOSALS measured on today's data. Each one is a claim that all future data obeys the same bound; "
        "a proof holds only IF the data does. A wrong claim makes proofs vacuous. Review every row.",
        "",
        "| Bound | Measured | Proposed cap | What breaks if data exceeds it | Effect on proof/speed |",
        "|---|---|---|---|---|",
    ]
    for r in report:
        lines.append(f"| {r['bound']} | {r['measured']} | {r['cap']} | {r['breaks']} | {r['effect']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    import duckdb

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True, help="JSON package path; the report goes next to it as .md")
    ap.add_argument("--margin", type=int, default=4, help="factor on rows, distinct counts, join sizes (default 4)")
    ap.add_argument("--value-margin", type=int, default=1, help="factor on value maxima (default 1)")
    ap.add_argument("--join", action="append", default=[], help="a.x=b.y[,a.z=b.w]; repeatable; measures the join size")
    args = ap.parse_args()
    con = duckdb.connect(args.db, read_only=True)
    try:
        catalog, report, proposals = profile(
            con, margin=args.margin, value_margin=args.value_margin, joins=tuple(args.join)
        )
    finally:
        con.close()
    out = Path(args.out)
    doc = {"name": args.name, **catalog_to_dict(catalog), "proposals": {"unique_keys": proposals}}
    out.write_text(json.dumps(doc, indent=2) + "\n")
    out.with_suffix(".md").write_text(render_report(args.name, report))
    print(f"wrote {out} and {out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
