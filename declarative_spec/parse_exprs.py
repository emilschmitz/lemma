"""Exact constant folding and integer arithmetic for the declarative parser.

Dates are the integer days since 1970-01-01, DuckDB's own DATE representation, so integer
order is date order. A date literal moved by an INTERVAL
follows DuckDB: DAY/WEEK add days; MONTH/YEAR add months and clamp the day to the end
of the target month. Number literals fold as exact rationals, never as floats.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from collections.abc import Callable
from fractions import Fraction

from sqlglot import exp

from declarative_spec.parse import DeclarativeUnsupported

_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_OPS = {"==": "==", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<="}


def _date_literal(node: exp.Expression) -> dt.date | None:
    if not isinstance(node, exp.Cast):
        return None
    if getattr(node.args.get("to"), "this", None) != exp.DataType.Type.DATE:
        return None
    lit = node.this
    if not isinstance(lit, exp.Literal) or not lit.is_string:
        return None
    match = _DATE.match(str(lit.this))
    if not match:
        raise DeclarativeUnsupported("DATE literal")
    return dt.date(*(int(x) for x in match.groups()))


def _interval(node: exp.Expression) -> tuple[int, str]:
    if not isinstance(node, exp.Interval):
        raise DeclarativeUnsupported("date arithmetic needs an INTERVAL")
    amount = node.this
    if not isinstance(amount, exp.Literal) or not re.fullmatch(r"-?\d+", str(amount.this)):
        raise DeclarativeUnsupported("INTERVAL amount")
    unit = node.args.get("unit")
    name = str(getattr(unit, "name", "") or getattr(unit, "this", "")).upper()
    if name not in ("DAY", "WEEK", "MONTH", "YEAR"):
        raise DeclarativeUnsupported(f"INTERVAL unit {name!r}")
    return int(str(amount.this)), name


def _shift(day: dt.date, amount: int, unit: str) -> dt.date:
    if unit in ("DAY", "WEEK"):
        return day + dt.timedelta(days=amount * (7 if unit == "WEEK" else 1))
    months = amount * (12 if unit == "YEAR" else 1)
    total = day.year * 12 + (day.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, min(day.day, last))


_EPOCH = dt.date(1970, 1, 1)


def fold_date(node: exp.Expression) -> str | None:
    """Days since 1970-01-01 for a DATE literal, optionally moved by INTERVALs. None if not a date constant."""
    day = _folded_day(node)
    return None if day is None else str((day - _EPOCH).days)


def _folded_day(node: exp.Expression) -> dt.date | None:
    day = _date_literal(node)
    if day is not None:
        return day
    if isinstance(node, exp.Paren):
        return _folded_day(node.this)
    if isinstance(node, (exp.Add, exp.Sub)):
        base = _folded_day(node.this)
        if base is None:
            return None
        amount, unit = _interval(node.expression)
        return _shift(base, -amount if isinstance(node, exp.Sub) else amount, unit)
    return None


def is_float_literal(node: exp.Expression) -> bool:
    """A number literal written ``<decimal>e0``: the rewriter's mark for a float constant."""
    return isinstance(node, exp.Literal) and node.is_number and re.fullmatch(r"\d+(\.\d+)?e0", str(node.this)) is not None


def has_float_literal(node: exp.Expression) -> bool:
    return any(is_float_literal(n) for n in node.walk())


def fold_number(node: exp.Expression) -> Fraction | None:
    """Exact value of a constant number expression (+, -, *, unary -). None if it has a column."""
    if isinstance(node, exp.Paren):
        return fold_number(node.this)
    if isinstance(node, exp.Literal):
        return Fraction(str(node.this)) if node.is_number else None
    if isinstance(node, exp.Neg):
        inner = fold_number(node.this)
        return None if inner is None else -inner
    if isinstance(node, (exp.Add, exp.Sub, exp.Mul)):
        left, right = fold_number(node.this), fold_number(node.expression)
        if left is None or right is None:
            return None
        if isinstance(node, exp.Add):
            return left + right
        if isinstance(node, exp.Sub):
            return left - right
        return left * right
    return None


def arith_text(
    node: exp.Expression,
    ref: Callable[[exp.Column], str],
    refs: list[str],
) -> str | None:
    """Integer arithmetic over columns as spec text. None when ``node`` is not arithmetic.

    Only whole-number literals, columns, ``+``, ``-``, ``*`` and negation. A decimal literal
    or ``/`` changes the DuckDB result type, which this text cannot state, so they refuse.
    Column names are recorded in ``refs`` so the emitter can check they are integer typed.
    """
    if isinstance(node, exp.Paren):
        inner = arith_text(node.this, ref, refs)
        return None if inner is None else f"({inner})"
    if isinstance(node, exp.Column):
        refs.append(ref(node))
        return refs[-1]
    if isinstance(node, exp.Literal):
        if is_float_literal(node):
            return str(node.this)
        if node.is_number and re.fullmatch(r"\d+", str(node.this)):
            return str(node.this)
        if node.is_number:
            raise DeclarativeUnsupported("decimal literal in arithmetic with a column")
        return None
    if isinstance(node, exp.Neg):
        inner = arith_text(node.this, ref, refs)
        return None if inner is None else f"(-{inner})"
    if isinstance(node, (exp.Add, exp.Sub, exp.Mul)):
        left = arith_text(node.this, ref, refs)
        right = arith_text(node.expression, ref, refs)
        if left is None or right is None:
            return None
        op = {exp.Add: "+", exp.Sub: "-", exp.Mul: "*"}[type(node)]
        return f"({left} {op} {right})"
    if isinstance(node, (exp.Div, exp.IntDiv, exp.Mod)):
        raise DeclarativeUnsupported("division or modulo in an expression")
    return None


def compare_to_rational(left_text: str, op: str, value: Fraction) -> str:
    """``left op value`` over an integer-valued ``left`` with no rounding.

    ``left op p/q`` with q > 0 is ``left * q op p``, so a decimal literal such as 0.05
    compares exactly against an integer column.
    """
    if value.denominator == 1:
        return f"({left_text} {_OPS[op]} {value.numerator})"
    return f"(({left_text}) * {value.denominator} {_OPS[op]} {value.numerator})"


_DATE_PARTS = {"YEAR": "spec_civil_year", "MONTH": "spec_civil_month", "DAY": "spec_civil_day"}


def extract_text(
    node: exp.Extract,
    ref: Callable[[exp.Column], str],
    refs: list[str],
) -> str:
    """``EXTRACT(part FROM col)`` over a DATE column (days since 1970-01-01), as a civil-date spec fn."""
    part = str(node.this.name if hasattr(node.this, "name") else node.this).upper()
    if part not in _DATE_PARTS or not isinstance(node.expression, exp.Column):
        raise DeclarativeUnsupported("EXTRACT")
    refs.append(ref(node.expression))
    return f"{_DATE_PARTS[part]}({refs[-1]})"
