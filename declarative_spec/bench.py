"""Column-file speed bar for a declarative binary. No database client lives here."""

from __future__ import annotations

import json
import math
from pathlib import Path


def rows_from_stdout(stdout: str) -> list[tuple[int, int]]:
    rows: list[tuple[int, int]] = []
    for line in stdout.splitlines():
        if not line.startswith("ROW "):
            continue
        parts = line.split()
        if len(parts) != 3:
            continue
        rows.append((int(parts[1]), int(parts[2])))
    return sorted(rows)


def rows_from_stdout_general(stdout: str) -> list[list[str]]:
    """Rows printed as ``ROW`` plus unit-separator fields. Strings are hex."""
    rows: list[list[str]] = []
    for line in stdout.splitlines():
        if not line.startswith("ROW\x1f"):
            continue
        rows.append(line.split("\x1f")[1:])
    return rows


def order_info(sql: str) -> dict:
    """Which output columns ORDER BY sorts on (``order_cols``, by position) and whether a LIMIT cuts the result (``limited``).

    ``order_cols`` is None when some ORDER BY item is not one of the output columns (an expression of its own): then the row check stays strict.
    Only a LIMIT over an ORDER BY whose keys do not make every row unique has a legitimate choice (which tied rows fall at the cut)."""
    import sqlglot
    from sqlglot import exp

    tree = sqlglot.parse_one(sql)
    order, limit = tree.args.get("order"), tree.args.get("limit")
    if order is None or limit is None:
        return {"order_cols": None, "limited": False}
    try:
        limit_n = int(limit.expression.name)
    except (AttributeError, ValueError):
        return {"order_cols": None, "limited": False}  # an unreadable LIMIT: stay strict
    outs = list(tree.expressions)
    texts = [" ".join(e.this.sql().split()).lower() if isinstance(e, exp.Alias) else " ".join(e.sql().split()).lower() for e in outs]
    aliases = [e.alias.lower() if isinstance(e, exp.Alias) else (e.name.lower() if isinstance(e, exp.Column) else None) for e in outs]
    cols: list[int] = []
    for item in order.expressions:
        key = item.this
        if isinstance(key, exp.Literal) and not key.is_string:
            idx = int(key.name) - 1
        else:
            text = " ".join(key.sql().split()).lower()
            idx = texts.index(text) if text in texts else (aliases.index(key.name.lower()) if isinstance(key, exp.Column) and not key.table and key.name.lower() in aliases else -1)
        if not 0 <= idx < len(outs):
            return {"order_cols": None, "limited": True, "limit": limit_n}
        cols.append(idx)
    return {"order_cols": cols, "limited": True, "limit": limit_n}


def rows_match_error(
    got: list[list[str]],
    expect: list,
    kinds: list[str],
    order_cols: list[int] | None = None,
    limited: bool = False,
) -> str | None:
    """None when ``got`` matches ``expect``. A float matches within ``float_tolerance`` (the only epsilon).

    Result columns are matched by position: the SELECT order is the output order.
    """
    decoded: list[list[object]] = []
    for raw in got:
        if len(raw) != len(kinds):
            return f"proved but a result row has {len(raw)} fields, expected {len(kinds)}"
        try:
            decoded.append([_decode_field(cell, kind) for cell, kind in zip(raw, kinds, strict=True)])
        except ValueError as exc:
            return f"proved but a result field did not parse ({exc})"
    expected = [list(row) for row in expect]
    if len(decoded) != len(expected):
        return (
            "proved but result rows differ from the loaded table "
            f"(got {len(decoded)} rows, expected {len(expected)})"
        )
    if _rows_equal(decoded, expected, kinds):
        return None
    left = sorted(decoded, key=lambda row: _row_key(row, kinds))
    right = sorted(expected, key=lambda row: _row_key(row, kinds))
    if _rows_equal(left, right, kinds):
        return None
    if limited and order_cols and _equal_up_to_the_cut_tie_group(decoded, expected, kinds, order_cols):
        return None
    return (
        "proved but result rows differ from the loaded table "
        f"(got {len(decoded)} rows, expected {len(expected)}; float tolerance relative {REL_TOLERANCE:g})"
    )


def _equal_up_to_the_cut_tie_group(got: list[list[object]], expect: list[list[object]], kinds: list[str], order_cols: list[int]) -> bool:
    """ORDER BY keys that tie let DuckDB and the proved binary keep different rows at a LIMIT cut; both answers are valid SQL.

    Accepted when the ORDER BY key columns agree position by position, and every key group except the LAST (the one the cut falls in) holds the
    same rows. The last group's members are not compared with DuckDB: the proved spec says each kept row is not after any omitted one, which is
    the proof's job, and the reference output does not contain the omitted tied rows to compare with."""
    def key(row: list[object]) -> list[object]:
        return [row[i] for i in order_cols]

    key_kinds = [kinds[i] for i in order_cols]
    for left, right in zip(got, expect, strict=True):
        if not all(_values_equal(g, e, k) for g, e, k in zip(key(left), key(right), key_kinds, strict=True)):
            return False
    last = len(expect) - 1
    start = last
    while start > 0 and all(_values_equal(a, b, k) for a, b, k in zip(key(expect[start - 1]), key(expect[last]), key_kinds, strict=True)):
        start -= 1
    head_got = sorted(got[:start], key=lambda row: _row_key(row, kinds))
    head_exp = sorted(expect[:start], key=lambda row: _row_key(row, kinds))
    return _rows_equal(head_got, head_exp, kinds)


REL_TOLERANCE = 1e-9
ABS_FLOOR = 1e-9


def float_tolerance(expect: float) -> float:
    """The row check's tolerance for one DuckDB float: relative 1e-9 of the value, with a 1e-9 floor.

    Float results are exact reals in the spec (rounding is ignored, see `declarative_spec/lemmas.py`), so the
    binary and DuckDB can differ in the last bits; this is the only epsilon left and it never enters a spec.
    """
    return REL_TOLERANCE * abs(expect) + ABS_FLOOR


def _decode_field(cell: str, kind: str) -> object:
    if cell == "NULL":
        return None
    if kind == "str":
        try:
            return bytes.fromhex(cell).decode("utf-8")
        except ValueError as exc:
            raise ValueError(f"string {cell!r}") from exc
    if kind == "float":
        return float(cell)
    return int(cell)


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"not a float: {value!r}")  # noqa: TRY004
    return float(value)


def _values_equal(got: object, expect: object, kind: str) -> bool:
    if got is None or expect is None:
        return got is None and expect is None
    if kind == "float":
        g, e = _as_float(got), _as_float(expect)
        if math.isnan(g) or math.isnan(e):
            return math.isnan(g) and math.isnan(e)  # a ratio with a zero denominator is IEEE NaN / inf (like DuckDB)
        if math.isinf(g) or math.isinf(e):
            return g == e
        return abs(g - e) <= float_tolerance(e)
    return got == expect


def _rows_equal(
    got: list[list[object]], expect: list[list[object]], kinds: list[str]
) -> bool:
    for left, right in zip(got, expect, strict=True):
        if len(left) != len(kinds) or len(right) != len(kinds):
            return False
        for g, e, kind in zip(left, right, kinds, strict=True):
            if not _values_equal(g, e, kind):
                return False
    return True


def _row_key(row: list[object], kinds: list[str]) -> tuple[object, ...]:
    parts: list[object] = []
    for value, kind in zip(row, kinds, strict=True):
        if value is None:
            parts.append(None)
        elif kind == "float":
            parts.append(round(_as_float(value), 6))
        else:
            parts.append(value)
    return tuple(parts)


def load_speed_bar(data_dir: Path) -> tuple[dict[str, str], dict] | None:
    expect_path = data_dir / "expect.json"
    if not expect_path.is_file():
        return None
    bins: dict[str, str] = {}
    for path in sorted(data_dir.glob("cols_*.bin")):
        suffix = path.name[len("cols_") : -len(".bin")]
        bins[suffix] = str(path)
    if not bins:
        raise FileNotFoundError(f"no column file in {data_dir}")
    bar = json.loads(expect_path.read_text(encoding="utf-8"))
    return bins, bar
