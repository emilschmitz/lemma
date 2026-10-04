"""Rewrite DATE and DECIMAL SQL into exact integer SQL before the declarative parser sees it.

A DATE column is stored as an integer, days since 1970-01-01. A DECIMAL(p,s) column is stored
as the integer ``value * 10**s``. The rewrite types every numeric expression with a scale and
states each comparison and arithmetic step over the stored integers:

* a DATE literal, or a DATE moved by an INTERVAL, becomes its day number;
* a decimal literal becomes its digits at its own scale (``0.05`` is ``5`` at scale 2);
* ``+`` and ``-`` bring both sides to the larger scale, ``*`` adds the scales;
* a comparison brings both sides to the larger scale, so every comparison is exact;
* SUM keeps the scale of its argument, as DuckDB's DECIMAL sum does.

Anything not exactly representable is refused: ``/``, ``%``, AVG of a DECIMAL, arithmetic on a
float column, a decimal literal against a float column, a number against a DATE.

``rewrite_numeric`` returns the integer SQL and the scale of each SELECT output, in order.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.parse_exprs import fold_date
from declarative_spec.schema_types import ColumnTypeInfo, SchemaModel

MAX_SCALE = 38
_NUMBER = re.compile(r"^(\d*)(?:\.(\d*))?$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_EPOCH = dt.date(1970, 1, 1)
_COMPARE = (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE)

# (kind, scale). kind: num | date | float | str | bool | unknown
Type = tuple[str, int]


@dataclass
class _T:
    node: exp.Expression
    kind: str
    scale: int = 0


@dataclass
class _Scope:
    tables: dict[str, dict[str, Type]] = field(default_factory=dict)
    aliases: dict[str, Type] = field(default_factory=dict)
    parent: _Scope | None = None

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
    return [_T(_scaled(t, scale), "num", scale) for t in ts]


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
    def __init__(self, model: SchemaModel) -> None:
        self.model = model

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
            return
        raise DeclarativeUnsupported("FROM table reference")

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
            aligned = _align([left, right])
            return aligned[0], aligned[1]
        if "date" in kinds and kinds != {"date"}:
            if "unknown" in kinds:
                raise DeclarativeUnsupported("a DATE compared with an operand of unknown type")
            raise DeclarativeUnsupported(f"a DATE compared with {(kinds - {'date'}).pop()}")
        if "float" in kinds:
            other = right if left.kind == "float" else left
            if other.kind == "num" and other.scale > 0:
                raise DeclarativeUnsupported(
                    "a decimal value compared with a float column: "
                    "arithmetic and decimal literals need an integer or decimal column"
                )
        if "unknown" in kinds and any(t.kind == "num" and t.scale > 0 for t in (left, right)):
            raise DeclarativeUnsupported("a DECIMAL compared with an operand of unknown type")
        return left, right

    def _between(self, node: exp.Between, scope: _Scope) -> exp.Expression:
        this = self.typed(node.this, scope)
        low = self.typed(node.args["low"], scope)
        high = self.typed(node.args["high"], scope)
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
            return _T(exp.Paren(this=inner.node), inner.kind, inner.scale)
        if isinstance(node, exp.Column):
            found = scope.find(node.table, node.name)
            if found is None:
                return _T(node, "unknown")
            return _T(node, *found)
        if isinstance(node, exp.Literal):
            return self._literal(node)
        if isinstance(node, exp.Boolean):
            return _T(node, "bool")
        if isinstance(node, exp.Neg):
            inner = self.typed(node.this, scope)
            self._require_num(inner, "negation")
            return _T(exp.Neg(this=inner.node), "num", inner.scale)
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
        return _T(exp.Literal.number(int((whole + frac) or "0")), "num", len(frac))

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
        if t.kind == "float":
            raise DeclarativeUnsupported(
                f"{what} on a float column: float products and differences have no proved error bound"
            )
        if t.kind != "num":
            raise DeclarativeUnsupported(f"{what} on a {t.kind} operand")

    def _arith(self, node: exp.Expression, scope: _Scope) -> _T:
        left, right = self.typed(node.this, scope), self.typed(node.expression, scope)  # type: ignore[attr-defined]
        self._require_num(left, "arithmetic")
        self._require_num(right, "arithmetic")
        if isinstance(node, exp.Mul):
            scale = left.scale + right.scale
            if scale > MAX_SCALE:
                raise DeclarativeUnsupported(f"DECIMAL scale {scale} exceeds {MAX_SCALE}")
            return _T(exp.Mul(this=left.node, expression=right.node), "num", scale)
        left, right = _align([left, right])
        return _T(type(node)(this=left.node, expression=right.node), "num", left.scale)

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
                raise DeclarativeUnsupported("AVG over a DECIMAL: DuckDB averages in DOUBLE, which is not stated exactly")
            if inner.kind not in ("num", "float"):
                raise DeclarativeUnsupported(f"AVG over a {inner.kind} operand")
            return _T(node, "float")
        return _T(node, inner.kind, inner.scale)

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
            raise DeclarativeUnsupported("a DECIMAL result in CASE")
        kinds = {r.kind for r in results}
        return _T(node, kinds.pop() if len(kinds) == 1 else "unknown")


def _first_table(tree: exp.Expression) -> str:
    table = tree.find(exp.Table)
    if table is None:
        raise DeclarativeUnsupported("FROM")
    return table.name


def rewrite_numeric(sql: str, schema: dict) -> tuple[str, list[int]]:
    """Integer-only SQL for ``sql``, and the DECIMAL scale of each SELECT output in order."""
    try:
        tree = sqlglot.parse_one(sql)
    except Exception as exc:
        raise DeclarativeUnsupported(f"SQL parse error: {exc}") from exc
    model = SchemaModel.from_caller(schema, _first_table(tree))
    rewritten, outputs = _Rewriter(model).query(tree, None)
    return rewritten.sql(), [scale if kind == "num" else 0 for kind, scale in outputs]


OUT_SCALES_PREFIX = "// OUT_SCALES: "


def with_out_scales(spec: str, scales: list[int]) -> str:
    """Record each output's DECIMAL scale above ``OutRow``: the stored integer is value * 10**scale."""
    if not any(scales) or "pub struct OutRow" not in spec:
        return spec
    line = OUT_SCALES_PREFIX + ",".join(str(s) for s in scales)
    return spec.replace("pub struct OutRow", line + "\npub struct OutRow", 1)
