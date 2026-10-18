"""Host side of agent scans (declarative_spec/agent_scan.py): the fixed translation of a scan predicate to DuckDB SQL and its export.

The proved binary calls ``scan_where_<t>(handle, pred)``. Its trusted exec body serializes ``pred`` to a key
(``R:<col>:<lo>:<hi>`` = ``lo <= cell <= hi``; ``I:<col>:<v1>,<v2>,...`` = cell in the list; atoms joined by ``;``; empty = no atom)
and reads ``scan_<t>_<fnv64(key)>.bin``. When that file is missing it runs this module (the command in ``<data dir>/scan_cmd``),
which exports, through the same exporter as the full column file (``decl_query_measure._export_planned_to``),

    SELECT <the columns of Cols_<t>> FROM <t> WHERE (<pushed predicate, if any>) AND (<cell_1> BETWEEN lo AND hi) AND ...

where ``<cell>`` is exactly the SQL the exporter loads that column as (``decl_query_measure.int_cell_sql``: days for a date, the
scaled integer for a DECIMAL). A NULL cell makes the comparison NULL, so its row is not returned, as ``scan_cell_ok_<t>`` says.
Dictionary columns are written with the full table's dictionary (``scan_where`` ensures the dictionaries are the full table's).

Trusted: DuckDB evaluates this WHERE correctly and returns the rows in table order. Everything else here is fixed host code.
"""

from __future__ import annotations

import argparse
import pickle
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ATOM = re.compile(r"^(R):([A-Za-z_][A-Za-z0-9_]*):(-?\d+):(-?\d+)$|^(I):([A-Za-z_][A-Za-z0-9_]*):((?:-?\d+)(?:,-?\d+)*)?$")


def write_scan_context(dest: Path, db_path: Path, duck_cfg: dict, plans: dict, fields: dict, wheres: dict, dict_entries: dict) -> None:
    """What a scan export needs, fixed at prepare time: the database, the column plans and struct fields, the pushed predicates, the full dictionaries."""
    ctx = {"db_path": str(db_path), "duck_cfg": duck_cfg, "plans": plans, "fields": fields, "wheres": wheres, "dict_entries": dict_entries}
    (dest / "scan_ctx.pkl").write_bytes(pickle.dumps(ctx))
    (dest / "scan_cmd").write_text("\n".join([str(ROOT), sys.executable, "-m", "research_loop.scan_export", "--dir", str(dest)]) + "\n")


def predicate_sql(key: str, plan: tuple, fields: list[tuple[str, str]], base_types: dict[str, str]) -> str:
    """The DuckDB WHERE of one scan key (``"TRUE"`` for the empty key). ``fields``: the ``Cols_<t>`` fields, in plan order.
    Unknown or non-integer columns are refused, not skipped."""
    from declarative_spec.agent_scan import scan_columns
    from research_loop.decl_query_measure import _quote, int_cell_sql

    table, names, types, infos, _nullable, _dict_of, _valid = plan
    if len(fields) != len(names):
        raise ValueError(f"{table}: {len(fields)} struct fields for {len(names)} planned columns")
    scan_ok = {c for c, _ty, _n in scan_columns(fields)}
    allowed = {f.removeprefix("r#"): idx for idx, (f, _t) in enumerate(fields) if f in scan_ok}
    if not key:
        return "TRUE"
    parts: list[str] = []
    for atom in key.split(";"):
        m = _ATOM.match(atom)
        if m is None:
            raise ValueError(f"malformed scan atom {atom!r}")
        col = m.group(2) or m.group(6)
        if col not in allowed:
            raise ValueError(f"{table}.{col} is not a scan column")
        idx = allowed[col]
        cell = int_cell_sql(_quote(names[idx]), types[idx], infos[idx], base_types[names[idx]])
        if m.group(1):
            parts.append(f"(({cell}) BETWEEN {int(m.group(3))} AND {int(m.group(4))})")
        else:
            values = [int(v) for v in (m.group(7) or "").split(",") if v]
            parts.append(f"(({cell}) IN ({', '.join(str(v) for v in values)}))" if values else "FALSE")
    return " AND ".join(parts)


def export_scan(data_dir: Path, suffix: str, key: str) -> Path:
    from declarative_spec.agent_scan import fnv64
    from research_loop.decl_query_measure import (
        _export_planned_to,
        _quote,
        open_measure_connection,
    )

    ctx = pickle.loads((data_dir / "scan_ctx.pkl").read_bytes())
    plan = ctx["plans"][suffix]
    base = data_dir / f"scan_{suffix}_{fnv64(key)}"
    con, _cfg = open_measure_connection(Path(ctx["db_path"]), data_dir)
    try:
        uniq = list(dict.fromkeys(plan[1]))
        desc = con.execute(f"SELECT {', '.join(_quote(n) for n in uniq)} FROM {_quote(plan[0])} LIMIT 0").description
        base_types = {n: str(d[1]) for n, d in zip(uniq, desc, strict=True)}
        where = predicate_sql(key, plan, ctx["fields"][suffix], base_types)
        if ctx["wheres"].get(suffix):
            where = f"({ctx['wheres'][suffix]}) AND ({where})"
        part = base.with_suffix(".bin.part")
        with part.open("wb") as fh:
            _export_planned_to(con, plan, fh, where=where, fixed_dicts=ctx["dict_entries"].get(suffix) or {})
    finally:
        con.close()
    part.replace(base.with_suffix(".bin"))
    base.with_suffix(".key").write_text(key)
    return base.with_suffix(".bin")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--table", required=True)
    ap.add_argument("--key", required=True)
    args = ap.parse_args(argv)
    export_scan(args.dir, args.table, args.key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
