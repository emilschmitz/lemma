"""Membership test for grammar G, the whitelist SQL fragment of the declarative path (docs/SQL_FRAGMENT.md).

``in_fragment(sql)`` is purely syntactic: it walks the sqlglot AST and accepts only the listed constructs.
Anything else is out, and the reason names the rule it breaks. It does not look at a schema.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CMP = (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE)
_AGG = (exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Count)
_SELECT_KEYS = {"expressions", "from_", "joins", "where", "group", "having", "order", "limit", "distinct"}


class Out(Exception):
    """The query is outside G; the message names the broken rule."""


def in_fragment(
    sql: str,
    level: str = "full",
    schema: dict[str, dict[str, str]] | None = None,
    nullable: set[tuple[str, str]] | None = None,
    dialect: str | None = None,
) -> tuple[bool, str]:
    """``(True, "")`` when ``sql`` is in G_<level> (``"high"`` is inside ``"med"`` inside ``"full"``, the default), else ``(False, rule)``."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception as exc:  # untrusted input: any parse failure is a refusal
        return False, f"R0 not parseable SQL: {str(exc).splitlines()[0]}"
    try:
        if not isinstance(tree, exp.Select):
            raise Out("R1 top level must be one SELECT (no WITH, set operations, VALUES)")
        _select(tree, top=True, outer=frozenset())
    except Out as out:
        return False, str(out)
    if level in _LEVEL_TABLES and (rule := _level_rule(tree, level)):
        return False, rule
    if schema is not None and (rule := _typed_rule(tree, schema, nullable or set(), level)):
        return False, rule
    return True, ""


def _scope(sel: exp.Select) -> dict[str, str]:
    """Alias or table name -> table name for the FROM and JOIN tables of one SELECT."""
    out: dict[str, str] = {}
    tables = [sel.args["from_"].this] + [j.this for j in sel.args.get("joins") or []]
    for t in tables:
        out[t.name.lower()] = t.name.lower()
        if t.alias:
            out[t.alias.lower()] = t.name.lower()
    return out


def _column_of(col: exp.Column, scope: dict[str, str], schema: dict[str, dict[str, str]]) -> tuple[str, str] | None:
    """The (table, column) a column reference names in ``scope``, if it is one of the select's own tables."""
    name = col.name.lower()
    if col.table:
        table = scope.get(col.table.lower())
        return (table, name) if table and name in schema.get(table, {}) else None
    owners = {t for t in scope.values() if name in schema.get(t, {})}
    return (next(iter(owners)), name) if len(owners) == 1 else None


def _in_condition(col: exp.Column, root: exp.Expression) -> bool:
    """Is ``col`` inside the WHEN condition of a CASE below ``root``?"""
    node = col
    while node is not root and node.parent is not None:
        if isinstance(node.parent, exp.If) and node.parent.this is node:
            return True
        node = node.parent
    return False


def _typed_rule(tree: exp.Select, schema: dict[str, dict[str, str]], nullable: set[tuple[str, str]], level: str = "full") -> str:
    """Rules that need column types or the nullable-column list (checked only when a schema is given)."""
    for sel in tree.find_all(exp.Select):
        if sel.args.get("from_") is None or not isinstance(sel.args["from_"].this, exp.Table):
            continue
        scope = _scope(sel)
        grouped = sel.args.get("group") is not None
        for node in sel.find_all(exp.Min, exp.Max, exp.Sum, exp.Avg):
            if node.find_ancestor(exp.Select) is not sel:
                continue
            # value positions only: a CASE condition on a nullable column is three-valued logic, it never makes the cell NULL
            cols = [c for c in node.find_all(exp.Column) if not _in_condition(c, node)]
            refs = [r for c in cols if (r := _column_of(c, scope, schema))]
            if isinstance(node, (exp.Min, exp.Max)):
                banned = {"string"} | ({"double"} if level in _LEVEL_TABLES else set())
                if any(schema[t][c] in banned for t, c in refs):
                    return "T1 MIN/MAX apply to integer, DECIMAL and date columns (a dictionary string code does not preserve order; G_high and G_med are also float-free)"
            if grouped and any((t, c) in nullable for t, c in refs):
                return "T2 SUM/MIN/MAX/AVG in a grouped query over a nullable column (an all-NULL group has no value)"
    return ""


def _select(sel: exp.Select, *, top: bool, outer: frozenset[str], kind: str = "top") -> None:
    if sel.args.get("with_"):
        raise Out("R1 WITH (CTEs) is not in G")
    if any(isinstance(i, exp.Star) for i in sel.expressions):
        raise Out("R4 the select list names its columns (no SELECT *)")
    if sel.find(exp.Window):
        raise Out("R2 window functions are out of scope")
    for key, value in sel.args.items():
        if value and key not in _SELECT_KEYS:
            raise Out(f"R2 clause not in G: {key.upper()} (WITH, OFFSET, QUALIFY, WINDOW, SAMPLE, LOCK, hints)")
    if not top:
        if sel.args.get("limit") or sel.args.get("order"):
            raise Out("R3 ORDER BY / LIMIT only at the top level")
        if kind == "exists" and (sel.args.get("distinct") or sel.args.get("group") or sel.args.get("having")):
            raise Out("R3 DISTINCT / GROUP BY / HAVING inside EXISTS")
    names = _from(sel)
    scope = names | (outer if kind == "exists" else frozenset())
    local = names
    items = sel.expressions
    if not items:
        raise Out("R4 empty select list")
    group = sel.args.get("group")
    group_cols = _group(group)
    has_agg = False
    for item in items:
        if kind == "exists" and isinstance(item, exp.Literal):
            continue  # EXISTS ignores its select list: SELECT 1
        agg = _item(item, local, scope)
        has_agg |= agg
        if not agg and (group_cols or any(_has_agg(i) for i in items)) and not isinstance(_unalias(item), exp.Column):
            raise Out("R7 a non-aggregate expression next to aggregates must be a GROUP BY column")
    if sel.args.get("having") is not None:
        if group is None:
            raise Out("R8 HAVING needs GROUP BY")
        _bool(sel.args["having"].this, local, scope, having=True, allow_sub=False)
    if sel.args.get("where") is not None:
        _where(sel.args["where"].this, local, scope, kind)
    order = sel.args.get("order")
    if order is not None:
        for key in order.expressions:
            if not isinstance(key.this, exp.Column):
                raise Out("R9 ORDER BY keys are output names or columns")
    limit = sel.args.get("limit")
    if limit is not None:
        n = limit.expression
        if not (isinstance(n, exp.Literal) and not n.is_string and n.this.isdigit()) or limit.args.get("limit_options"):
            raise Out("R9 LIMIT is a non-negative integer literal")
    if kind == "scalar" and not (len(items) == 1 and has_agg and group is None):
        raise Out("R10 a scalar subquery is one aggregate over no GROUP BY")
    if kind == "in" and len(items) != 1:
        raise Out("R10 IN subquery selects one column")


def _from(sel: exp.Select) -> frozenset[str]:
    frm = sel.args.get("from_")
    if frm is None or not isinstance(frm.this, exp.Table):
        raise Out("R5 FROM is a base table (no derived table, no CTE reference, no VALUES)")
    names: set[str] = set()
    _table(frm.this, names)
    for join in sel.args.get("joins") or []:
        if join.args.get("side") or join.args.get("method") or join.args.get("using") or join.args.get("kind") not in (None, "", "INNER"):
            raise Out("R5 only [INNER] JOIN ... ON (no outer, cross, natural, semi, anti, USING)")
        if join.args.get("on") is None:
            raise Out("R5 comma joins and joins without ON are not in G")
        if not isinstance(join.this, exp.Table):
            raise Out("R5 a joined relation is a base table")
        _table(join.this, names)
        if not _equi(join.args["on"]):
            raise Out("R6 ON is a conjunction of column = column")
    return frozenset(names)


def _table(table: exp.Table, names: set[str]) -> None:
    if table.args.get("db") or table.args.get("catalog") or table.args.get("sample") or table.args.get("pivots"):
        raise Out("R5 plain table name only")
    names.add(table.name.lower())
    if table.alias:
        names.add(table.alias.lower())


def _equi(node: exp.Expression) -> bool:
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.And):
        return _equi(node.left) and _equi(node.right)
    return isinstance(node, exp.EQ) and isinstance(node.left, exp.Column) and isinstance(node.right, exp.Column)


def _group(group: exp.Group | None) -> list[exp.Column]:
    if group is None:
        return []
    if any(group.args.get(k) for k in ("all", "rollup", "cube", "grouping_sets", "totals")):
        raise Out("R8 GROUP BY is a plain list of columns (no ROLLUP, CUBE, GROUPING SETS, ALL)")
    cols = group.expressions
    if not all(isinstance(c, exp.Column) for c in cols):
        raise Out("R8 GROUP BY keys are columns")
    return cols


def _unalias(node: exp.Expression) -> exp.Expression:
    return node.this if isinstance(node, exp.Alias) else node


def _has_agg(node: exp.Expression) -> bool:
    return isinstance(_unalias(node), _AGG)


def _item(item: exp.Expression, local: frozenset[str], scope: frozenset[str]) -> bool:
    """One select item; True when it is an aggregate."""
    inner = _unalias(item)
    if isinstance(inner, _AGG):
        if not isinstance(item, exp.Alias) and not (isinstance(inner, exp.Count) or isinstance(inner.this, exp.Column)):
            raise Out("R11 an aggregate over an expression needs an alias")
        _agg(inner, local, scope)
        return True
    if isinstance(inner, exp.Column):
        _col(inner, local, scope)
        return False
    if isinstance(inner, exp.Literal) and not isinstance(item, exp.Alias):
        raise Out("R11 a constant select item needs an alias")
    if not isinstance(item, exp.Alias):
        raise Out("R11 a select expression needs an alias")
    _scalar(inner, local, scope)
    return False


def _agg(node: exp.Expression, local: frozenset[str], scope: frozenset[str]) -> None:
    if node.args.get("expressions") or node.args.get("distinct"):
        raise Out("R12 aggregate with extra arguments")
    arg = node.this
    if isinstance(node, exp.Count):
        if isinstance(arg, exp.Star):
            return
        if isinstance(arg, exp.Distinct):
            if len(arg.expressions) != 1 or not isinstance(arg.expressions[0], exp.Column):
                raise Out("R12 COUNT(DISTINCT) takes one column")
            _col(arg.expressions[0], local, scope)
            return
        if not isinstance(arg, exp.Column):
            raise Out("R12 COUNT takes *, a column or DISTINCT column")
        _col(arg, local, scope)
        return
    if isinstance(arg, (exp.Distinct, exp.Star)):
        raise Out("R12 only COUNT takes DISTINCT or *")
    _scalar(arg, local, scope)


def _col(col: exp.Column, local: frozenset[str], scope: frozenset[str]) -> None:
    if col.table and col.table.lower() not in scope:
        raise Out(f"R13 column {col.table}.{col.name} is correlated outside an EXISTS equality")


def _scalar(node: exp.Expression, local: frozenset[str], scope: frozenset[str]) -> None:
    """Scalar expression: columns, literals, + - * and unary minus, CASE with ELSE, DATE literals."""
    if isinstance(node, exp.Column):
        _col(node, local, scope)
    elif isinstance(node, exp.Literal):
        pass
    elif isinstance(node, exp.Paren):
        _scalar(node.this, local, scope)
    elif isinstance(node, exp.Neg):
        _scalar(node.this, local, scope)
    elif isinstance(node, (exp.Add, exp.Sub, exp.Mul)):
        _scalar(node.left, local, scope)
        _scalar(node.right, local, scope)
    elif isinstance(node, exp.Cast):
        if not (node.to.this == exp.DType.DATE and isinstance(node.this, exp.Literal) and _DATE.match(str(node.this.this))):
            raise Out("R14 the only cast is a DATE 'yyyy-mm-dd' literal")
    elif isinstance(node, exp.Case):
        if node.args.get("this") is not None:
            raise Out("R15 CASE is searched (CASE WHEN ...)")
        if node.args.get("default") is None:
            raise Out("R15 CASE needs an ELSE")
        for arm in node.args["ifs"]:
            _bool(arm.this, local, scope, having=False, allow_sub=False)
            _scalar(arm.args["true"], local, scope)
        _scalar(node.args["default"], local, scope)
    elif isinstance(node, (exp.Div, exp.IntDiv, exp.Mod)):
        raise Out("R14 general division and modulo are out of scope")
    elif isinstance(node, exp.Func) or isinstance(node, exp.Anonymous):
        raise Out(f"R14 function {type(node).__name__} is out of scope (no scalar functions)")
    else:
        raise Out(f"R14 scalar expression {type(node).__name__} is not in G")


def _where(node: exp.Expression, local: frozenset[str], scope: frozenset[str], kind: str) -> None:
    if kind == "exists":
        # correlation is allowed only as outer-column = inner-column conjuncts
        for conj in _conjuncts(node):
            if _is_correlation(conj, local):
                continue
            _bool(conj, local, local, having=False, allow_sub=False)
        return
    _bool(node, local, scope, having=False, allow_sub=True)


def _conjuncts(node: exp.Expression) -> list[exp.Expression]:
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.And):
        return _conjuncts(node.left) + _conjuncts(node.right)
    return [node]


def _is_correlation(node: exp.Expression, local: frozenset[str]) -> bool:
    if not (isinstance(node, exp.EQ) and isinstance(node.left, exp.Column) and isinstance(node.right, exp.Column)):
        return False
    tabs = [c.table.lower() for c in (node.left, node.right)]
    return all(tabs) and sum(t in local for t in tabs) == 1


def _bool(node: exp.Expression, local: frozenset[str], scope: frozenset[str], *, having: bool, allow_sub: bool) -> None:
    if isinstance(node, (exp.And, exp.Or)):
        _bool(node.left, local, scope, having=having, allow_sub=allow_sub)
        _bool(node.right, local, scope, having=having, allow_sub=allow_sub)
    elif isinstance(node, exp.Paren):
        _bool(node.this, local, scope, having=having, allow_sub=allow_sub)
    elif isinstance(node, exp.Not):
        _bool(node.this, local, scope, having=having, allow_sub=allow_sub)
    elif isinstance(node, exp.Exists):
        if not allow_sub or not isinstance(node.this, exp.Select):
            raise Out("R16 EXISTS only in WHERE")
        _select(node.this, top=False, outer=local, kind="exists")
    elif isinstance(node, exp.In):
        _in(node, local, scope, allow_sub, having)
    elif isinstance(node, exp.Between):
        _operand(node.this, local, scope, having)
        for side in (node.args["low"], node.args["high"]):
            _scalar(side, local, scope)
    elif isinstance(node, exp.Is):
        if isinstance(node.expression, exp.Null) and isinstance(node.this, exp.Column):
            _col(node.this, local, scope)
        else:
            raise Out("R17 IS applies to a column and NULL")
    elif isinstance(node, _CMP):
        subs = [s for s in (node.left, node.right) if isinstance(s, exp.Subquery)]
        if subs:
            if not allow_sub or len(subs) != 1:
                raise Out("R16 one scalar subquery per comparison, in WHERE only")
            other = node.right if subs[0] is node.left else node.left
            _scalar(other, local, scope)
            if not isinstance(subs[0].this, exp.Select):
                raise Out("R16 subquery is a SELECT")
            _select(subs[0].this, top=False, outer=frozenset(), kind="scalar")
        else:
            _operand(node.left, local, scope, having)
            _operand(node.right, local, scope, having)
    elif isinstance(node, exp.Boolean):
        pass
    elif isinstance(node, exp.Like) or isinstance(node, exp.ILike) or isinstance(node, exp.SimilarTo) or isinstance(node, exp.RegexpLike):
        raise Out("R18 pattern matching (LIKE, ILIKE, SIMILAR TO, regex) is out of scope")
    else:
        raise Out(f"R18 predicate {type(node).__name__} is not in G")


def _operand(node: exp.Expression, local: frozenset[str], scope: frozenset[str], having: bool) -> None:
    if having and isinstance(node, _AGG):
        _agg(node, local, scope)
        return
    if having:
        # arithmetic over aggregates is not in G; a group column, an output alias or a literal is
        if not isinstance(node, (exp.Column, exp.Literal, exp.Neg, exp.Cast)):
            raise Out("R19 HAVING compares aggregates, group columns or aliases with literals")
    _scalar(node, local, scope)


def _in(node: exp.In, local: frozenset[str], scope: frozenset[str], allow_sub: bool, having: bool) -> None:
    if not isinstance(node.this, exp.Column):
        raise Out("R17 IN / NOT IN applies to a column")
    _col(node.this, local, scope)
    query = node.args.get("query")
    if query is not None:
        if not allow_sub or not isinstance(query.this, exp.Select):
            raise Out("R16 IN (subquery) only in WHERE")
        _select(query.this, top=False, outer=frozenset(), kind="in")
        return
    if node.args.get("unnest") or node.args.get("field"):
        raise Out("R17 IN list of literals or one subquery")
    if not node.expressions or not all(
        isinstance(v, (exp.Literal, exp.Neg, exp.Cast)) for v in node.expressions
    ):
        raise Out("R17 IN list holds literals")
    for v in node.expressions:
        _scalar(v, local, scope)




_LEVEL_TABLES = {"high": 1, "med": 2}


def _level_rule(tree: exp.Select, level: str) -> str:
    """The rule of ``level`` (``"high"`` or ``"med"``) that ``tree`` (already in G_full) breaks, or ""."""
    name = f"G_{level}"
    tables = 1 + len(tree.args.get("joins") or [])
    if tables > _LEVEL_TABLES[level]:
        return f"L1 {name} joins at most {_LEVEL_TABLES[level]} table(s)"
    if tree.find(exp.Subquery, exp.Exists):
        return f"L2 {name} has no subquery (scalar, IN, NOT IN, EXISTS, NOT EXISTS)"
    group = tree.args.get("group")
    if group is None or not 1 <= len(group.expressions) <= 2:
        return f"L3 {name} groups by 1 or 2 plain columns"
    if tree.args.get("having") is not None:
        return f"L4 {name} has no HAVING"
    if tree.args.get("distinct") or any(isinstance(c.this, exp.Distinct) for c in tree.find_all(exp.Count)):
        return f"L5 {name} has no DISTINCT (SELECT DISTINCT, COUNT(DISTINCT))"
    where = tree.args.get("where")
    if where is not None and (where.find(exp.Add, exp.Sub, exp.Mul, exp.Case) or any(not isinstance(n.this, exp.Literal) for n in where.find_all(exp.Neg))):
        return f"L6 {name} filters compare plain columns and literals (no arithmetic or CASE)"
    aggs = 0
    for item in tree.expressions:
        inner = item.this if isinstance(item, exp.Alias) else item
        if isinstance(inner, exp.Column):
            continue
        aggs += 1
        if isinstance(inner, exp.Avg):
            return f"L7 {name} has no AVG"
        arg = inner.this
        plain = isinstance(arg, (exp.Column, exp.Star))
        if isinstance(inner, exp.Sum) and level == "med" and not arg.find(exp.Case) and not arg.find(exp.Subquery):
            plain = True  # arithmetic inside SUM
        if not plain:
            return f"L8 {name} aggregates take plain columns" + (" (SUM may take arithmetic, never CASE)" if level == "med" else "")
    if not aggs:
        return f"L9 {name} selects aggregates and group keys"
    order, limit = tree.args.get("order"), tree.args.get("limit")
    if level == "high" and (order or limit):
        return f"L10 {name} has no ORDER BY or LIMIT"
    if bool(order) != bool(limit):
        return f"L10 {name} has ORDER BY and LIMIT together (top-N) or neither"
    return ""


def fragment_level(sql: str, schema=None, nullable=None, dialect: str | None = None) -> tuple[str | None, str]:
    """The smallest level containing ``sql`` (``"high"``, ``"med"``, ``"full"`` or None) and the rule that keeps it out of the next level down ("" for high)."""
    ok, reason = in_fragment(sql, "full", schema, nullable, dialect)
    if not ok:
        return None, reason
    tree = sqlglot.parse_one(sql, read=dialect)
    high, med = _level_rule(tree, "high"), _level_rule(tree, "med")  # high implies med by construction
    if schema is not None:
        high = high or _typed_rule(tree, schema, nullable or set(), "high")
        med = med or _typed_rule(tree, schema, nullable or set(), "med")
    if not high:
        return "high", ""
    return ("med", high) if not med else ("full", med)
