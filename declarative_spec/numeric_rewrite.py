"""Rewrite DATE and DECIMAL SQL into exact integer SQL before the declarative parser sees it.

A DATE column is stored as an integer, days since 1970-01-01. A DECIMAL(p,s) column is stored
as the integer ``value * 10**s``. The rewrite types every numeric expression with a scale and
states each comparison and arithmetic step over the stored integers:

* a DATE literal, or a DATE moved by an INTERVAL, becomes its day number;
* a decimal literal becomes its digits at its own scale (``0.05`` is ``5`` at scale 2);
* ``+`` and ``-`` bring both sides to the larger scale, ``*`` adds the scales;
* a comparison brings both sides to the larger scale, so every comparison is exact;
* SUM keeps the scale of its argument, as DuckDB's DECIMAL sum does.

A float column stays a float: a number that meets a float column (comparison, ``+``, ``-``, ``*``)
is rewritten as a float literal ``<decimal>e0`` (the f64 idealization: the spec reads it as that exact real).
Anything not exactly representable is refused: ``/``, ``%``, AVG of a DECIMAL, a non-constant integer
column mixed with a float column, a number against a DATE.

``rewrite_numeric`` returns the integer SQL and the scale of each SELECT output, in order.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from fractions import Fraction
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.parse_exprs import fold_date, fold_number
from declarative_spec.schema_types import ColumnTypeInfo, SchemaModel

MAX_SCALE = 38
_NUMBER = re.compile(r"^(\d*)(?:\.(\d*))?$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_EPOCH = dt.date(1970, 1, 1)
_COMPARE = (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE)

# (kind, scale). kind: num | date | float | str | bool | unknown   (``float``: a double, or a float expression)
Type = tuple[str, int]


# The type DuckDB computes + - * in, by its exclusive magnitude cap (it raises an overflow error beyond it).
_SQL_INT_CAP = {
    "tinyint": 2**7, "int1": 2**7, "smallint": 2**15, "int2": 2**15, "integer": 2**31, "int": 2**31, "int4": 2**31,
    "bigint": 2**63, "int8": 2**63, "int64": 2**63, "utinyint": 2**8, "usmallint": 2**16, "uinteger": 2**32,
    "uint": 2**32, "ubigint": 2**64,
}


@dataclass
class _T:
    node: exp.Expression
    kind: str
    scale: int = 0
    # Integer overflow model (plain integer columns, integer literals, + - *): ``mag`` is the largest absolute
    # value the catalog allows, ``tcap`` the exclusive cap of the type DuckDB computes in (2**31 INTEGER, 2**63
    # BIGINT; 0 when the operand is not a plain integer). ``prec`` is a DECIMAL column's precision.
    mag: int | None = None
    tcap: int = 0
    prec: tuple[int, int] | None = None  # (precision, scale) of a DECIMAL column


@dataclass
class _Scope:
    tables: dict[str, dict[str, Type]] = field(default_factory=dict)
    aliases: dict[str, Type] = field(default_factory=dict)
    parent: _Scope | None = None
    # column -> (type info, largest absolute value the catalog allows or None), per table alias
    meta: dict[str, dict[str, tuple[ColumnTypeInfo, int | None]]] = field(default_factory=dict)

    def find_meta(self, qual: str, name: str) -> tuple[ColumnTypeInfo, int | None] | None:
        name = name.casefold()
        if qual:
            cols = self.meta.get(qual.casefold())
            if cols is not None:
                return cols.get(name)
        else:
            hits = [cols[name] for cols in self.meta.values() if name in cols]
            if len(hits) == 1:
                return hits[0]
        return self.parent.find_meta(qual, name) if self.parent else None

    def find(self, qual: str, name: str) -> Type | None:
        name = name.casefold()
        if qual:
            cols = self.tables.get(qual.casefold())
            if cols is not None:
                return cols.get(name)
        else:
            hits = [cols[name] for cols in self.tables.values() if name in cols]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise DeclarativeUnsupported(f"column {name!r} is ambiguous")
            if name in self.aliases:
                return self.aliases[name]
        return self.parent.find(qual, name) if self.parent else None


def _info_type(info: ColumnTypeInfo) -> Type:
    if info.is_float:
        return "float", 0
    if info.is_date:
        return "date", 0
    if info.spec_as == "int":
        return "num", info.scale
    if info.spec_as == "Seq<char>":
        return "str", 0
    return "bool", 0


def _int_node(value: int) -> exp.Expression:
    lit = exp.Literal.number(abs(value))
    return lit if value >= 0 else exp.Neg(this=lit)


def _scaled(t: _T, to_scale: int) -> exp.Expression:
    """``t`` as the integer at ``to_scale`` (an exact multiplication by a power of ten)."""
    shift = to_scale - t.scale
    if shift == 0:
        return t.node
    node = t.node
    inner = node.this if isinstance(node, exp.Neg) else node
    if isinstance(inner, exp.Literal) and inner.is_int:
        value = int(inner.this) * 10**shift
        return _int_node(-value if isinstance(node, exp.Neg) else value)
    left = node if isinstance(node, (exp.Column, exp.Paren)) else exp.Paren(this=node)
    return exp.Mul(this=left, expression=exp.Literal.number(10**shift))


def _align(ts: list[_T]) -> list[_T]:
    scale = max(t.scale for t in ts)
    if scale > MAX_SCALE:
        raise DeclarativeUnsupported(f"DECIMAL scale {scale} exceeds {MAX_SCALE}")
    return [_T(_scaled(t, scale), "num", scale, prec=t.prec) for t in ts]


def _unparen(node: exp.Expression) -> exp.Expression:
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def _iso_date_days(node: exp.Expression) -> int | None:
    if isinstance(node, exp.Literal) and node.is_string:
        match = _ISO_DATE.match(str(node.this))
        if match:
            return (dt.date(*(int(x) for x in match.groups())) - _EPOCH).days
    return None


class _Rewriter:
    def __init__(self, model: SchemaModel, catalog: object | None = None) -> None:
        self.model = model
        self.catalog = catalog

    # ---- queries -----------------------------------------------------------------------

    def query(self, node: exp.Expression, parent: _Scope | None) -> tuple[exp.Expression, list[Type]]:
        if isinstance(node, exp.Select):
            return self.select(node, parent)
        if isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
            left, left_types = self.query(node.this, parent)
            right, right_types = self.query(node.expression, parent)
            if left_types != right_types:
                raise DeclarativeUnsupported("set operation over outputs of different type or scale")
            node.set("this", left)
            node.set("expression", right)
            return node, left_types
        raise DeclarativeUnsupported("unsupported top-level SQL shape")

    def select(self, node: exp.Select, parent: _Scope | None) -> tuple[exp.Expression, list[Type]]:
        scope = _Scope(parent=parent)
        sources: list[exp.Expression] = []
        from_clause = node.args.get("from_")
        if from_clause is not None:
            sources.append(from_clause.this)
        sources += [join.this for join in node.args.get("joins") or []]
        for source in sources:
            self._add_source(scope, source, parent)

        outputs: list[Type] = []
        items = []
        for item in node.expressions:
            alias = item.alias if isinstance(item, exp.Alias) else ""
            body = item.this if isinstance(item, exp.Alias) else item
            if isinstance(body, exp.Star):
                outputs.append(("unknown", 0))
                items.append(item)
                continue
            typed = self.typed(body, scope)
            new = typed.node
            outputs.append((typed.kind, typed.scale))
            if isinstance(item, exp.Alias):
                item.set("this", new)
                new = item
            items.append(new)
            name = alias or (body.name if isinstance(body, exp.Column) else "")
            if name:
                scope.aliases[name.casefold()] = (typed.kind, typed.scale)
        node.set("expressions", items)

        for join in node.args.get("joins") or []:
            self._hoist_scaled_equalities(node, join, scope)
            on = join.args.get("on")
            if on is not None:
                self._check_join_on(on, scope)
        where = node.args.get("where")
        if where is not None:
            where.set("this", self.walk(where.this, scope))
        having = node.args.get("having")
        if having is not None:
            having.set("this", self.walk(having.this, scope))
        return node, outputs

    def _add_source(self, scope: _Scope, source: exp.Expression, parent: _Scope | None) -> None:
        if isinstance(source, exp.Subquery):
            inner, outputs = self.query(source.this, parent)
            source.set("this", inner)
            names = [
                (item.alias or getattr(item, "name", "")).casefold()
                for item in inner.expressions  # type: ignore[attr-defined]
            ]
            scope.tables[(source.alias or "derived").casefold()] = {
                n: t for n, t in zip(names, outputs, strict=True) if n
            }
            return
        if isinstance(source, exp.Table):
            key = (source.alias or source.name).casefold()
            columns = self.model.tables.get(source.name.casefold(), {})
            scope.tables[key] = {c: _info_type(i) for c, i in columns.items()}
            scope.meta[key] = {c: (i, self._column_mag(source.name, c, i)) for c, i in columns.items()}
            return
        raise DeclarativeUnsupported("FROM table reference")

    def _column_mag(self, table: str, column: str, info: ColumnTypeInfo) -> int | None:
        """Largest absolute cell the catalog (or the column type) allows; None when no catalog is given."""
        if self.catalog is None or info.is_float or info.is_date:
            return None
        from declarative_spec.emit import _lookup_table_assumptions
        from research_loop.table_assumptions import column_assumption_exclusive

        cap = column_assumption_exclusive(column, _lookup_table_assumptions(self.catalog, table))
        cap = cap if cap is not None else (_SQL_INT_CAP.get(info.sql_type) or info.cell_exclusive_cap)
        return None if cap is None else cap - 1

    def _hoist_scaled_equalities(self, select: exp.Select, join: exp.Join, scope: _Scope) -> None:
        """An INNER JOIN equality between DECIMALs of different scale becomes a WHERE comparison.

        The WHERE comparison brings both sides to the larger scale exactly (as ``ON a.x < b.z`` already is), so the
        result is the same rows; an ON pair is compared as stored integers and cannot be rescaled."""
        if (join.side or "").upper() or (join.kind or "").upper() not in ("", "INNER") or join.args.get("on") is None:
            return

        def parts(n: exp.Expression) -> list[exp.Expression]:
            return parts(n.this) + parts(n.expression) if isinstance(n, exp.And) else [n]

        keep: list[exp.Expression] = []
        moved: list[exp.Expression] = []
        for conj in parts(join.args["on"]):
            if isinstance(conj, exp.EQ) and isinstance(conj.this, exp.Column) and isinstance(conj.expression, exp.Column):
                left, right = self.typed(conj.this, scope), self.typed(conj.expression, scope)
                if left.kind == right.kind == "num" and left.scale != right.scale:
                    moved.append(conj)
                    continue
            keep.append(conj)
        if not moved:
            return

        def conjoin(items: list[exp.Expression]) -> exp.Expression | None:
            out = None
            for item in items:
                out = item if out is None else exp.And(this=out, expression=item)
            return out

        join.set("on", conjoin(keep))
        where = select.args.get("where")
        cond = conjoin(([where.this] if where is not None else []) + moved)
        select.set("where", exp.Where(this=cond))

    def _check_join_on(self, on: exp.Expression, scope: _Scope) -> None:
        """A join equality compares stored integers as they are, so both sides need the same scale."""
        for eq in on.find_all(exp.EQ):
            if isinstance(eq.this, exp.Column) and isinstance(eq.expression, exp.Column):
                left, right = self.typed(eq.this, scope), self.typed(eq.expression, scope)
                if (left.kind, left.scale) != (right.kind, right.scale) and "unknown" not in (
                    left.kind,
                    right.kind,
                ):
                    raise DeclarativeUnsupported(
                        f"join compares {left.kind}({left.scale}) with {right.kind}({right.scale})"
                    )

    # ---- boolean contexts --------------------------------------------------------------

    def walk(self, node: exp.Expression, scope: _Scope) -> exp.Expression:
        if isinstance(node, _COMPARE):
            return self._compare(node, scope)
        if isinstance(node, exp.Between):
            return self._between(node, scope)
        if isinstance(node, exp.In):
            return self._in(node, scope)
        if isinstance(node, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            return self.query(node, scope)[0]
        for key, child in list(node.args.items()):
            if isinstance(child, exp.Expression):
                node.set(key, self.walk(child, scope))
            elif isinstance(child, list):
                node.set(key, [self.walk(c, scope) if isinstance(c, exp.Expression) else c for c in child])
        return node

    def _compare(self, node: exp.Expression, scope: _Scope) -> exp.Expression:
        left, right = self.typed(node.this, scope), self.typed(node.expression, scope)  # type: ignore[attr-defined]
        if (left.kind, right.kind) == ("str", "str") and not isinstance(node, (exp.EQ, exp.NEQ)):
            raise DeclarativeUnsupported("string ordering comparison: only = and <> on strings are stated")
        left, right = self._pair(left, right)
        node.set("this", left.node)
        node.set("expression", right.node)
        return node

    def _pair(self, left: _T, right: _T) -> tuple[_T, _T]:
        """Make the two operands of one comparison the same integer type, or refuse."""
        for a, b in ((left, right), (right, left)):
            if a.kind == "date" and b.kind == "str":
                days = _iso_date_days(b.node)
                if days is None:
                    raise DeclarativeUnsupported("a DATE column compared with a string that is not YYYY-MM-DD")
                b.node, b.kind = _int_node(days), "date"
        kinds = {left.kind, right.kind}
        if kinds == {"num"}:
            self._require_decimal_literal_in_range(left, right)
            aligned = _align([left, right])
            return aligned[0], aligned[1]
        if "date" in kinds and kinds != {"date"}:
            if "unknown" in kinds:
                raise DeclarativeUnsupported("a DATE compared with an operand of unknown type")
            raise DeclarativeUnsupported(f"a DATE compared with {(kinds - {'date'}).pop()}")
        if "float" in kinds:
            if kinds == {"float"}:
                return left, right
            for num, flt in ((right, left), (left, right)):
                if flt.kind == "float" and num.kind == "num":
                    if fold_number(num.node) is not None:
                        lit = _T(_float_literal(num), "float")
                        return (left, lit) if num is right else (lit, right)
                    if isinstance(_unparen(flt.node), (exp.Column, exp.Add, exp.Sub, exp.Mul, exp.Neg)):
                        raise DeclarativeUnsupported(
                            "a non-constant integer or DECIMAL value compared with a float column: "
                            "mixed with a float column"
                        )
                    return left, right  # an average or sum of floats: the emitter widens the integer side to real
        if "unknown" in kinds and any(t.kind == "num" and t.scale > 0 for t in (left, right)):
            raise DeclarativeUnsupported("a DECIMAL compared with an operand of unknown type")
        return left, right

    @staticmethod
    def _require_decimal_literal_in_range(left: _T, right: _T) -> None:
        """DuckDB casts a literal and a DECIMAL column to one DECIMAL of at most 38 digits, and raises a
        Conversion Error when the literal needs more: the spec would return a value instead."""
        for col, lit in ((left, right), (right, left)):
            node = _unparen(lit.node)
            node = _unparen(node.this) if isinstance(node, exp.Neg) else node
            if col.prec is None or not isinstance(node, exp.Literal):
                continue
            digits = len(str(abs(int(node.this))))
            lit_int = max(1, digits - lit.scale)
            if max(col.prec[0] - col.prec[1], lit_int) + max(col.prec[1], lit.scale) > 38:
                raise DeclarativeUnsupported(
                    "a literal outside the DECIMAL column's range: DuckDB raises a Conversion Error for it"
                )

    def _between(self, node: exp.Between, scope: _Scope) -> exp.Expression:
        this = self.typed(node.this, scope)
        low = self.typed(node.args["low"], scope)
        high = self.typed(node.args["high"], scope)
        if this.kind == "str":
            raise DeclarativeUnsupported("BETWEEN on strings: string ordering is not stated")
        this, low = self._pair(this, low)
        this, high = self._pair(this, high)
        if {this.kind, low.kind, high.kind} == {"num"}:
            this, low, high = _align([this, low, high])
        node.set("this", this.node)
        node.set("low", low.node)
        node.set("high", high.node)
        return node

    def _in(self, node: exp.In, scope: _Scope) -> exp.Expression:
        this = self.typed(node.this, scope)
        query = node.args.get("query")
        if query is not None:
            inner, outputs = self.query(query.this, scope)
            query.set("this", inner)
            mine = (this.kind, this.scale)
            exact = lambda t: t[0] == "date" or (t[0] == "num" and t[1] > 0)  # noqa: E731
            if len(outputs) != 1 or (mine != outputs[0] and (exact(mine) or exact(outputs[0]))):
                raise DeclarativeUnsupported("IN (SELECT ...) between operands of different type or scale")
            return node
        items = [self.typed(e, scope) for e in node.expressions]
        pairs = [self._pair(this, item) for item in items]
        this = pairs[0][0] if pairs else this
        items = [p[1] for p in pairs]
        if {this.kind, *(i.kind for i in items)} == {"num"}:
            aligned = _align([this, *items])
            this, items = aligned[0], aligned[1:]
        node.set("this", this.node)
        node.set("expressions", [i.node for i in items])
        return node

    # ---- numeric expressions ------------------------------------------------------------

    def typed(self, node: exp.Expression, scope: _Scope) -> _T:
        if isinstance(node, exp.Paren):
            inner = self.typed(node.this, scope)
            return _T(exp.Paren(this=inner.node), inner.kind, inner.scale, inner.mag, inner.tcap, inner.prec)
        if isinstance(node, exp.Column):
            found = scope.find(node.table, node.name)
            if found is None:
                return _T(node, "unknown")
            meta = scope.find_meta(node.table, node.name)
            if meta is None:
                return _T(node, *found)
            info, mag = meta
            plain = found[0] == "num" and found[1] == 0 and info.precision is None and not info.is_hugeint
            tcap = _SQL_INT_CAP.get(info.sql_type, 0) if plain else 0
            return _T(node, *found, mag=mag if plain else None, tcap=tcap, prec=(info.precision, info.scale) if info.precision else None)
        if isinstance(node, exp.Literal):
            return self._literal(node)
        if isinstance(node, exp.Boolean):
            return _T(node, "bool")
        if isinstance(node, exp.Neg):
            inner = self.typed(node.this, scope)
            if inner.kind == "float":
                return _T(exp.Neg(this=inner.node), "float")
            self._require_num(inner, "negation")
            return _T(exp.Neg(this=inner.node), "num", inner.scale, inner.mag, inner.tcap, inner.prec)
        if isinstance(node, (exp.Cast, exp.Add, exp.Sub)):
            days = self._folded_date(node)
            if days is not None:
                return _T(_int_node(days), "date")
        if isinstance(node, (exp.Add, exp.Sub, exp.Mul)):
            return self._arith(node, scope)
        if isinstance(node, (exp.Div, exp.IntDiv, exp.Mod)):
            raise DeclarativeUnsupported("division or modulo in an expression")
        if isinstance(node, exp.Cast):
            raise DeclarativeUnsupported("CAST")
        if isinstance(node, exp.Extract):
            col = self.typed(node.expression, scope)
            if col.kind != "date":
                raise DeclarativeUnsupported("EXTRACT needs a DATE column")
            return _T(node, "num", 0)
        if isinstance(node, (exp.Sum, exp.Avg, exp.Min, exp.Max)):
            return self._aggregate(node, scope)
        if isinstance(node, exp.Count):
            return _T(self.walk(node, scope), "num", 0)
        if isinstance(node, exp.Subquery):
            inner, outputs = self.query(node.this, scope)
            node.set("this", inner)
            if len(outputs) != 1:
                raise DeclarativeUnsupported("scalar subquery with several columns")
            return _T(node, *outputs[0])
        if isinstance(node, exp.Case):
            return self._case(node, scope)
        return _T(self.walk(node, scope), "unknown")

    def _literal(self, node: exp.Literal) -> _T:
        if node.is_string:
            return _T(node, "str")
        match = _NUMBER.match(str(node.this))
        if match is None or not (match.group(1) or match.group(2)):
            raise DeclarativeUnsupported(f"number literal {node.this!r} (only plain decimals are exact)")
        whole, frac = match.group(1), match.group(2) or ""
        value = int((whole + frac) or "0")
        if frac:
            return _T(exp.Literal.number(value), "num", len(frac))
        # DuckDB types a whole-number literal INTEGER when it fits, else BIGINT.
        return _T(exp.Literal.number(value), "num", 0, mag=value, tcap=2**31 if value < 2**31 else 2**63)

    def _folded_date(self, node: exp.Expression) -> int | None:
        if isinstance(node, (exp.Add, exp.Sub)) and (
            isinstance(node.expression, exp.Interval) or isinstance(node.this, exp.Interval)
        ):
            text = fold_date(node)
            if text is None:
                raise DeclarativeUnsupported("INTERVAL arithmetic on a column")
            return int(text)
        if isinstance(node, exp.Cast):
            text = fold_date(node)
            return None if text is None else int(text)
        return None

    @staticmethod
    def _require_num(t: _T, what: str) -> None:
        if t.kind != "num":
            raise DeclarativeUnsupported(f"{what} on a {t.kind} operand")

    def _arith(self, node: exp.Expression, scope: _Scope) -> _T:
        left, right = self.typed(node.this, scope), self.typed(node.expression, scope)  # type: ignore[attr-defined]
        if "float" in (left.kind, right.kind):
            left, right = _float_operand(left), _float_operand(right)
            return _T(type(node)(this=left.node, expression=right.node), "float")
        self._require_num(left, "arithmetic")
        self._require_num(right, "arithmetic")
        if isinstance(node, exp.Mul):
            scale = left.scale + right.scale
            if scale > MAX_SCALE:
                raise DeclarativeUnsupported(f"DECIMAL scale {scale} exceeds {MAX_SCALE}")
            out = _T(exp.Mul(this=left.node, expression=right.node), "num", scale)
            return self._integer_result(node, left, right, out) if scale == 0 else out
        raw_left, raw_right = left, right
        left, right = _align([left, right])
        out = _T(type(node)(this=left.node, expression=right.node), "num", left.scale)
        return self._integer_result(node, raw_left, raw_right, out) if left.scale == 0 else out

    def _integer_result(self, node: exp.Expression, left: _T, right: _T, result: _T) -> _T:
        """Plain integer + - *: DuckDB errors when the result leaves its type, and the spec's integers do not."""
        if left.tcap and right.tcap and left.mag is not None and right.mag is not None:
            mag = left.mag * right.mag if isinstance(node, exp.Mul) else left.mag + right.mag
            tcap = max(left.tcap, right.tcap)
            if mag >= tcap:
                raise DeclarativeUnsupported(
                    f"integer arithmetic can overflow: the catalog allows |result| up to {mag}, "
                    f"the type holds up to {tcap - 1}, and DuckDB raises an overflow error there"
                )
            result.mag, result.tcap = mag, tcap
        return result

    def _aggregate(self, node: exp.Expression, scope: _Scope) -> _T:
        arg = node.this
        if not isinstance(arg, exp.Expression) or isinstance(arg, exp.Distinct):
            return _T(self.walk(node, scope), "unknown")
        inner = self.typed(arg, scope)
        node.set("this", inner.node)
        if isinstance(node, exp.Sum):
            if inner.kind not in ("num", "float"):
                raise DeclarativeUnsupported(f"SUM over a {inner.kind} operand")
            return _T(node, inner.kind, inner.scale)
        if isinstance(node, exp.Avg):
            if inner.kind == "num" and inner.scale > 0:
                # DuckDB averages a DECIMAL in DOUBLE: the spec states the exact quotient in natural units.
                marked = exp.Anonymous(this=f"__dec{inner.scale}", expressions=[inner.node])
                node.set("this", marked)
                return _T(node, "float")
            if inner.kind not in ("num", "float"):
                raise DeclarativeUnsupported(f"AVG over a {inner.kind} operand")
            return _T(node, "float")
        if inner.kind in ("str", "bool"):
            raise DeclarativeUnsupported(f"MIN or MAX over a {inner.kind}: only integer and date orderings are stated")
        return _T(node, inner.kind, inner.scale)

    def _decimal_case(self, node: exp.Case, results: list[_T]) -> _T:
        """A CASE whose results are DECIMAL columns of one scale and integer literals, which are rescaled exactly."""
        scale = _decimal_case_scale(results)
        for r in results:
            inner = _unparen(r.node)
            literal = isinstance(inner.this if isinstance(inner, exp.Neg) else inner, exp.Literal)
            if r.scale != scale and not literal:
                raise DeclarativeUnsupported("a DECIMAL CASE result of another scale than its column results")
            if r.scale == scale and not (literal or isinstance(inner, exp.Column)):
                raise DeclarativeUnsupported("a DECIMAL CASE result that is not a column or a literal")
        arms = node.args.get("ifs") or []
        for arm, r in zip(arms, results[: len(arms)], strict=True):
            arm.set("true", _scaled(r, scale))
        if node.args.get("default") is not None:
            node.set("default", _scaled(results[-1], scale))
        return _T(node, "num", scale)

    def _case(self, node: exp.Case, scope: _Scope) -> _T:
        results: list[_T] = []
        for arm in node.args.get("ifs") or []:
            arm.set("this", self.walk(arm.this, scope))
            res = self.typed(arm.args["true"], scope)
            arm.set("true", res.node)
            results.append(res)
        default = node.args.get("default")
        if default is not None:
            res = self.typed(default, scope)
            node.set("default", res.node)
            results.append(res)
        if any(r.kind == "num" and r.scale > 0 for r in results):
            return self._decimal_case(node, results)
        kinds = {r.kind for r in results}
        if kinds == {"float", "num"}:
            # An integer literal beside a float column is that float (every scale is 0 here).
            for r in results:
                lit = _unparen(r.node)
                lit = _unparen(lit.this) if isinstance(lit, exp.Neg) else lit
                if r.kind == "num" and not isinstance(lit, exp.Literal):
                    raise DeclarativeUnsupported("CASE returns a float column or an integer expression")
            return _T(node, "float")
        return _T(node, kinds.pop() if len(kinds) == 1 else "unknown")


def _float_literal(t: _T) -> exp.Expression:
    """A constant number met by a float column, as the float literal ``<decimal>e0``."""
    value = fold_number(t.node)
    if value is None:
        raise DeclarativeUnsupported("a non-constant integer or DECIMAL value mixed with a float column")
    exact = Decimal(value.numerator) / Decimal(value.denominator * 10**t.scale) if value else Decimal(0)
    lit = exp.Literal.number(f"{abs(exact):f}e0")
    return exp.Neg(this=lit) if exact < 0 else lit


def _float_operand(t: _T) -> _T:
    if t.kind == "float":
        return t
    if t.kind == "num":
        return _T(_float_literal(t), "float")
    raise DeclarativeUnsupported(f"arithmetic mixing a float column with a {t.kind} operand")


def _decimal_case_scale(results: list[_T]) -> int:
    scales = {r.scale for r in results if r.kind == "num" and r.scale > 0}
    if len(scales) != 1 or any(r.kind != "num" for r in results):
        raise DeclarativeUnsupported("a DECIMAL result in CASE beside a result of another type or scale")
    return scales.pop()


def _first_table(tree: exp.Expression) -> str:
    table = tree.find(exp.Table)
    if table is None:
        raise DeclarativeUnsupported("FROM")
    return table.name


def rewrite_numeric(sql: str, schema: dict, catalog: object | None = None) -> tuple[str, list[int]]:
    """Integer-only SQL for ``sql``, and the DECIMAL scale of each SELECT output in order."""
    try:
        tree = sqlglot.parse_one(sql)
    except Exception as exc:
        raise DeclarativeUnsupported(f"SQL parse error: {exc}") from exc
    model = SchemaModel.from_caller(schema, _first_table(tree))
    rewritten, outputs = _Rewriter(model, catalog).query(tree, None)
    return rewritten.sql(), [scale if kind == "num" else 0 for kind, scale in outputs]


OUT_SCALES_PREFIX = "// OUT_SCALES: "


def with_out_scales(spec: str, scales: list[int]) -> str:
    """Record each output's DECIMAL scale above ``OutRow``: the stored integer is value * 10**scale."""
    if not any(scales) or "pub struct OutRow" not in spec:
        return spec
    line = OUT_SCALES_PREFIX + ",".join(str(s) for s in scales)
    return spec.replace("pub struct OutRow", line + "\npub struct OutRow", 1)
