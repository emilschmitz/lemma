"""Predicate pushdown rule (lemma.toml [run] ``pushdown``): which WHERE conjuncts the host may apply while it exports a table.

The host exports one column file per base table (``Cols_<t>``) and the proved ``run_query`` reads only those vectors. With
pushdown on, the export is ``SELECT <needed columns> FROM t WHERE <pushed conjuncts>`` instead of the full scan, so the database
skips data (zone maps) and the proved code sees only rows that can matter. The spec text is NOT changed: it still states the
whole query, WHERE included, over whatever vectors it is given, and the runtime data-assumption checks run on the delivered rows.

Soundness argument (this module is host code; it is trusted like the rest of the transpiler):

    Let the query be  F(σ_W(t1 ⋈ ... ⋈ tk))  where every ⋈ is an INNER (or comma / CROSS) join, W = C ∧ R, and C mentions only
    columns of ti and constants. Every row of the join that comes from a ti-row r with C(r) not TRUE fails W (an AND with a
    FALSE or NULL conjunct is never TRUE), so σ_W(t1 ⋈ .. ti .. ⋈ tk) = σ_W(t1 ⋈ .. σ_C(ti) .. ⋈ tk), and F (GROUP BY, HAVING,
    aggregates, DISTINCT, ORDER BY, LIMIT) only ever sees σ_W(...). Hence F is unchanged when ti is replaced by σ_C(ti),
    PROVIDED ti is read nowhere else: the column file of ti is shared by every occurrence of ti in the query.

    The proved body computes spec(delivered). spec(delivered) = spec(full) follows from the argument above applied to the spec's
    own WHERE, which the transpiler states with DuckDB's semantics (the oracle comparison checks that agreement on every run).
    Every data assumption of the catalog (row caps, value bounds, abs-sum caps, distinct caps, unique keys, join caps,
    one-row-per-key) is an upper bound or a uniqueness claim, so it holds of any subset of rows that satisfies it in full;
    the generated main re-checks them on the delivered rows anyway.

What is trusted: DuckDB evaluates the pushed predicate correctly (it keeps exactly the rows on which C is TRUE, in table order).

Allow-list (anything else pushes nothing; no approximations):
  * the statement is ONE plain SELECT: no WITH, no set operation, no subquery / derived table / EXISTS / IN (SELECT ..) /
    scalar subquery anywhere, no window function, no table function or VALUES in FROM;
  * FROM is base tables of the schema joined by INNER / comma / CROSS joins only (no LEFT / RIGHT / FULL / SEMI / ANTI /
    NATURAL / ASOF / LATERAL), no catalog or schema qualifier;
  * a table that occurs more than once (self join) gets nothing pushed (its file serves every occurrence);
  * a top-level OR conjunct that spans tables pushes, per table t, the implied predicate OR_i (AND of Di's t-only conjuncts),
    only when EVERY disjunct Di has at least one t-only conjunct (sound: see ``_implied_by_disjunction``);
  * a pushed conjunct is a top-level AND-conjunct of WHERE (never HAVING, never a join's ON) whose column references all
    resolve to that one table, with at least one column, built only from: columns, literals, NULL, TRUE/FALSE, = <> < <= > >=,
    AND / OR / NOT (inside the one conjunct), BETWEEN, IN (literal list), LIKE / ILIKE (no ESCAPE), IS [NOT] NULL, + - * and
    unary minus, CAST(<literal> AS <type>) (``DATE '...'``), INTERVAL '<n>' <unit>, and named parameters (``:name``).
    No function calls (nondeterministic or not), no division, no CASE.
Refused shapes (push nothing for the query): NOT EXISTS / anti joins, outer joins (preserved side and the other), any subquery
(a scalar subquery's emptiness, a correlated reference), CTEs, set operations, windows. HAVING is never inspected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from declarative_spec.schema_types import SchemaModel, rust_ident


@dataclass(frozen=True)
class Fragment:
    """One pushed conjunct: SQL text (rendered for the export's dialect) and the named parameters it binds (templates)."""

    sql: str
    params: tuple[str, ...] = ()


@dataclass
class PushdownPlan:
    """Pushed conjuncts per table (casefolded name; AND of the fragments), or ``refused`` with the reason nothing is pushed."""

    pushed: dict[str, list[Fragment]] = field(default_factory=dict)
    refused: str | None = None
    kept: list[str] = field(default_factory=list)  # WHERE conjuncts not pushed, with the reason (for the plan file)

    def where(self, table: str) -> str | None:
        """The export's WHERE for ``table`` (``None``: full scan)."""
        frags = self.pushed.get(table.casefold()) or []
        return " AND ".join(f"({f.sql})" for f in frags) if frags else None

    def params(self, table: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(p for f in self.pushed.get(table.casefold()) or [] for p in f.params))

    def bound_where(self, table: str, sql: str, binding: dict[str, str] | None) -> str | None:
        """:meth:`where` with every named parameter replaced by the SQL literal of its value in ``binding`` (a query template,
        ``declarative_spec/templates.py``): what one round's export applies. Rendered in DuckDB's dialect. Loud on a parameter
        the binding does not name; ``binding`` may be None only when nothing pushed for ``table`` has a parameter."""
        where = self.where(table)
        if where is None or not self.params(table):
            return where
        if binding is None:
            raise ValueError(f"the pushed predicate on {table} binds {self.params(table)}: a run needs their values")
        from declarative_spec import templates

        template = templates.parse_template(sql)
        if template is None:
            raise ValueError(f"the pushed predicate on {table} has parameters but the SQL is not a query template")
        tree = sqlglot.parse_one(where, read="duckdb")
        for node in list(tree.find_all(exp.Placeholder)):
            if node.name not in binding:
                raise ValueError(f"no value for parameter {node.name} of the pushed predicate on {table}")
            literal = sqlglot.parse_one(templates.sql_literal(template.param(node.name), binding[node.name]), read="duckdb")
            node.replace(exp.paren(literal))
        return tree.sql(dialect="duckdb")


_LEAF_OK = (exp.Literal, exp.Null, exp.Boolean, exp.DataType, exp.Placeholder)
_NODE_OK = (
    exp.Column, exp.Identifier, exp.Paren, exp.And, exp.Or, exp.Not,
    exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Is, exp.Between, exp.In, exp.Like, exp.ILike,
    exp.Add, exp.Sub, exp.Mul, exp.Neg, exp.Cast, exp.Interval, exp.Var,
) + _LEAF_OK
_REFUSED_ANYWHERE = (exp.Subquery, exp.Exists, exp.Window, exp.With, exp.Union, exp.Intersect, exp.Except, exp.Lateral, exp.Unnest, exp.Values)


def plan_pushdown(sql: str, schema: dict, *, dialect: str | None = None) -> PushdownPlan:
    """Apply the rule to ``sql`` (parsed like the transpiler parses it); fragments are rendered in ``dialect``.

    A query template (``-- params:`` header, ``$name`` placeholders) is planned on its body with each ``$name`` read as the named
    parameter ``:name``: a pushed conjunct may compare a column with a parameter, and each run's export binds that run's value
    (:meth:`PushdownPlan.bound_where`)."""
    from declarative_spec import templates

    template = templates.parse_template(sql)
    if template is not None:
        body, last = [], 0
        for start, end, name in templates._placeholders(template.body):
            body.append(template.body[last:start] + f":{name}")
            last = end
        sql = "".join(body) + template.body[last:]
    try:
        tree = sqlglot.parse_one(sql)
    except sqlglot.errors.SqlglotError as exc:
        return PushdownPlan(refused=f"parse error: {exc}")
    if not isinstance(tree, exp.Select):
        return PushdownPlan(refused=f"not a plain SELECT ({type(tree).__name__})")
    for node in tree.walk():
        if isinstance(node, _REFUSED_ANYWHERE) or (isinstance(node, exp.Select) and node is not tree):
            return PushdownPlan(refused=f"{type(node).__name__} in the query")
    from_ = tree.args.get("from_")
    if from_ is None or not isinstance(from_.this, exp.Table):
        return PushdownPlan(refused="FROM is not a base table")
    nodes = [from_.this]
    for join in tree.args.get("joins") or []:
        side = (join.args.get("side") or "").upper()
        kind = (join.args.get("kind") or "").upper()
        if side or kind not in ("", "INNER", "CROSS") or join.args.get("method"):
            return PushdownPlan(refused=f"{' '.join(x for x in (join.args.get('method') or '', side, kind) if x)} JOIN")
        if not isinstance(join.this, exp.Table):
            return PushdownPlan(refused="a join operand is not a base table")
        nodes.append(join.this)
    if any(n.args.get("db") or n.args.get("catalog") or not isinstance(n.this, exp.Identifier) for n in nodes):
        return PushdownPlan(refused="a qualified or computed table reference")
    model = SchemaModel.from_caller(schema, nodes[0].name)
    names = [n.name.casefold() for n in nodes]
    if any(name not in model.tables for name in names):
        return PushdownPlan(refused="a FROM table is not in the schema")
    # qualifier -> table: an aliased table is reachable only through its alias.
    by_qualifier: dict[str, str] = {}
    for n in nodes:
        q = (n.alias or n.name).casefold()
        if q in by_qualifier:
            return PushdownPlan(refused=f"qualifier {q} names two tables")
        by_qualifier[q] = n.name.casefold()
    plan = PushdownPlan()
    where = tree.args.get("where")
    if where is None:
        return plan
    for conj in _conjuncts(where.this):
        table, why = _single_table(conj, by_qualifier, set(names), model)
        if table is not None and names.count(table) > 1:
            table, why = None, f"{table} occurs more than once (self join)"
        if table is not None:
            plan.pushed.setdefault(table, []).append(_render(conj, model, table, dialect))
            continue
        implied = {t: p for t, p in _implied_by_disjunction(conj, by_qualifier, set(names), model).items() if names.count(t) == 1}
        for t, pred in implied.items():
            plan.pushed.setdefault(t, []).append(_render(pred, model, t, dialect))
        plan.kept.append(f"{conj.sql()}  -- {why}" + (f"; implied per-table OR pushed for {', '.join(sorted(implied))}" if implied else ""))
    return plan


def _implied_by_disjunction(conj: exp.Expression, by_qualifier: dict[str, str], tables: set[str], model: SchemaModel) -> dict[str, exp.Expression]:
    """For ``D1 OR ... OR Dn`` where every Di has AND-conjuncts over table t only: t -> ``(t-part of D1) OR ... OR (t-part of Dn)``.

    Implied, hence sound to push: if no t-part is TRUE of a t-row, every Di (t-part AND rest) is FALSE or NULL for every joined
    row built from it, so the OR is not TRUE and WHERE drops the row anyway (TPC-H Q19 shape)."""
    node = conj
    while isinstance(node, exp.Paren):
        node = node.this
    if not isinstance(node, exp.Or):
        return {}
    per: list[dict[str, list[exp.Expression]]] = []
    for d in _disjuncts(node):
        parts: dict[str, list[exp.Expression]] = {}
        for c in _conjuncts(d):
            t, _why = _single_table(c, by_qualifier, tables, model)
            if t is not None:
                parts.setdefault(t, []).append(c.copy())
        per.append(parts)
    out: dict[str, exp.Expression] = {}
    for t in sorted(set.intersection(*(set(p) for p in per))):
        out[t] = exp.or_(*(exp.paren(exp.and_(*p[t])) for p in per))
    return out


def _disjuncts(node: exp.Expression) -> list[exp.Expression]:
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.Or):
        return _disjuncts(node.this) + _disjuncts(node.expression)
    return [node]


def _conjuncts(node: exp.Expression) -> list[exp.Expression]:
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    return [node]


def _single_table(conj: exp.Expression, by_qualifier: dict[str, str], tables: set[str], model: SchemaModel) -> tuple[str | None, str]:
    """The one table every column of ``conj`` resolves to, or ``(None, reason)``."""
    for node in conj.walk():
        if not isinstance(node, _NODE_OK):
            return None, f"{type(node).__name__} is not on the allow-list"
        if isinstance(node, exp.Var) and not (isinstance(node.parent, exp.Interval) and node.arg_key == "unit"):
            return None, "a bare word outside an INTERVAL unit"
        if isinstance(node, exp.Placeholder) and (not node.name or node.name == "?"):
            return None, "an anonymous parameter"
        if isinstance(node, (exp.Like, exp.ILike)) and node.args.get("escape"):
            return None, "LIKE with ESCAPE"
        if isinstance(node, exp.In) and (node.args.get("query") or node.args.get("unnest") or node.args.get("field")):
            return None, "IN over a query"
        if isinstance(node, exp.Cast) and not isinstance(node.this, exp.Literal):
            return None, "CAST of a non-literal"
        if isinstance(node, exp.Interval) and not (isinstance(node.this, exp.Literal) and isinstance(node.args.get("unit"), exp.Var)):
            return None, "an INTERVAL that is not '<n>' <unit>"
    owners: set[str] = set()
    for col in conj.find_all(exp.Column):
        owner = _owner(col, by_qualifier, tables, model)
        if owner is None:
            return None, f"column {col.sql()} does not resolve to exactly one FROM table"
        owners.add(owner)
    if len(owners) != 1:
        return None, "no column" if not owners else f"columns of {len(owners)} tables"
    return owners.pop(), ""


def _owner(col: exp.Column, by_qualifier: dict[str, str], tables: set[str], model: SchemaModel) -> str | None:
    if col.args.get("db") or col.args.get("catalog"):
        return None
    name = col.name.casefold()
    if col.table:
        table = by_qualifier.get(col.table.casefold())
        return table if table is not None and name in model.tables[table] else None
    hits = [t for t in tables if name in model.tables[t]]
    return hits[0] if len(hits) == 1 else None


def _render(conj: exp.Expression, model: SchemaModel, table: str, dialect: str | None) -> Fragment:
    out = conj.copy()
    for col in list(out.find_all(exp.Column)):
        orig = model.original_column_names[(table, col.name.casefold())]
        col.replace(exp.column(exp.to_identifier(orig, quoted=True)))
    params = tuple(dict.fromkeys(p.name for p in out.find_all(exp.Placeholder)))
    return Fragment(sql=out.sql(dialect=dialect), params=params)


_FIELD_RE = r"pub\s+((?:r#)?[A-Za-z_][A-Za-z0-9_]*):\s+Vec<([^>]+)>"


def scan_plan(spec: str, plan: PushdownPlan, schema: dict, sql: str) -> dict:
    """The machine-readable scan plan written next to the column files: per spec struct, the table, the columns it needs (in
    struct order, ``__dict`` / ``__valid`` folded into their column) and the pushed predicate fragments."""
    import re

    tree = sqlglot.parse_one(sql)
    first = tree.find(exp.Table)
    model = SchemaModel.from_caller(schema, first.name if first is not None else "")
    tables: dict[str, dict] = {}
    for struct, body in re.findall(r"pub struct (Cols_[A-Za-z0-9_]+)\s*\{([^}]+)\}", spec):
        suffix = struct.removeprefix("Cols_")
        hits = [t for t in model.tables if rust_ident(model.original_table_names[t]) == suffix]
        if len(hits) != 1:
            raise ValueError(f"no table matches column struct {suffix}")
        table = hits[0]
        by_ident = {rust_ident(c): c for c in model.tables[table]}
        cols: list[str] = []
        for fname, _ty in re.findall(_FIELD_RE, body):
            base = fname.removesuffix("__dict").removesuffix("__valid")
            cols.append(model.original_column_names[(table, by_ident[base])])
        tables[model.original_table_names[table]] = {
            "struct": struct,
            "columns": list(dict.fromkeys(cols)),
            "predicates": [{"sql": f.sql, "params": list(f.params)} for f in plan.pushed.get(table, [])],
        }
    return {"version": 1, "refused": plan.refused, "kept": plan.kept, "tables": tables}
