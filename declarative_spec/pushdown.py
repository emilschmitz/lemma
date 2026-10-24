"""Predicate pushdown rule (lemma.toml [run] ``pushdown``): which conjuncts the host may apply while it exports a table.

The host exports one column file per base table (``Cols_<t>``) and the proved ``run_query`` reads only those vectors. With
pushdown on, the export is ``SELECT <needed columns> FROM t WHERE <pushed predicate>`` instead of the full scan, so the database
skips data (zone maps) and the proved code sees only rows that can matter. The spec text is NOT changed: it still states the
whole query, WHERE included, over whatever vectors it is given, and the runtime data-assumption checks run on the delivered rows.

Soundness argument (this module is host code; it is trusted like the rest of the transpiler):

    Blocks and reads. Every SELECT in the statement (the outer query, a derived table in FROM, a scalar / IN / EXISTS subquery,
    correlated or not) is a block. A block's FROM items are joined left-deep: X0 J1 X1 J2 ... Jm Xm. Each base-table item is
    one READ of that table. The block's result is a function of what its reads deliver (and, for a correlated block, of the
    outer row); a block whose result is unchanged for every outer row leaves every enclosing block, hence the query, unchanged.
    One table has ONE column file however often it is read, so the file must serve every read of that table at once.

    (R1) Inner chain, WHERE. Let a read r of table t be "preserved": r is X0, or the right operand of an INNER / comma / CROSS
    join (never the right operand of a LEFT join). Inner joins and the left operand of a LEFT join both distribute over a union
    of their input rows, so the block's joined relation is the union over t-rows s of f({s}), and every row of f({s}) carries
    s's columns unchanged (not NULL-extended). If C is a WHERE conjunct mentioning only r's columns and constants, every row of
    f({s}) with C(s) not TRUE fails WHERE (an AND with a FALSE or NULL conjunct is never TRUE). So
    σ_W(f(t)) = σ_W(f(σ_C t)), and GROUP BY / HAVING / aggregates / DISTINCT / ORDER BY / LIMIT only ever see σ_W(...).
    (R2) Inner ON. An ON conjunct of an INNER join is a filter σ_θ on the left-deep prefix it joins, so (R1) applies to it
    verbatim for a preserved read.
    (R3) LEFT JOIN, preserved side. ``L LEFT JOIN b ON θ`` keeps every row of L (decomposing L by rows commutes with the
    LEFT join), so a WHERE conjunct on a preserved read of L pushes by (R1). A conjunct on a read that is the right operand of
    a LEFT join (null-supplying) is NOT pushed from WHERE or from any later ON: removing b-rows turns matched rows into
    NULL-extended rows, which a predicate such as ``b.x IS NULL`` (the anti-join) accepts. An ON conjunct of a LEFT join on
    the preserved side is NOT pushed either: an L-row failing it is still kept, NULL-extended.
    (R4) LEFT JOIN, ON on the null-supplying side. In ``L LEFT JOIN b ON θ`` with θ = D ∧ E, D mentioning only b (a base
    table read) and constants: a b-row s with D(s) not TRUE satisfies θ with no L-row, so it is in no match and its absence
    changes no L-row's "has a match" status. Hence L ⟕_θ b = L ⟕_θ σ_D(b) (rows and NULL extension alike).
    (R5) Implied disjunctions. A conjunct D1 OR ... OR Dn where every Di has AND-conjuncts on read r implies, for that read,
    the OR of those parts: an r-row failing every part fails every Di. It pushes wherever a single-read conjunct would.
    (R6) Several reads of one table (self join, the same table in the outer query and in a subquery). Let read i of t admit
    predicate P_i by (R1)-(R5). The file is σ_P(t) with P = P_1 OR ... OR P_n. For each read i, σ_P(t) lies between
    σ_{P_i}(t) and t and every row it drops fails P_i, so the argument for read i holds for σ_P(t) exactly as for σ_{P_i}(t).
    If ANY read of t admits nothing (e.g. it is null-supplying, or its block has no conjunct on it), t is exported in full.
    The pushed fragments are the conjuncts common to every P_i, plus (when no P_i is wholly common) the OR of the remainders.

    The proved body computes spec(delivered). spec(delivered) = spec(full) follows from the argument above applied to the spec's
    own query, which the transpiler states with DuckDB's semantics (the oracle comparison checks that agreement on every run).
    Every data assumption of the catalog (row caps, value bounds, abs-sum caps, distinct caps, unique keys, join caps,
    one-row-per-key) is an upper bound or a uniqueness claim, so it holds of any subset of rows that satisfies it in full;
    the generated main re-checks them on the delivered rows anyway.

What is trusted: DuckDB evaluates the pushed predicate correctly (it keeps exactly the rows on which it is TRUE, in table order).

Allow-list (anything else pushes nothing; no approximations):
  * the statement is a SELECT with no WITH, no set operation (anywhere), no window function, no LATERAL / UNNEST / VALUES /
    table function, no parenthesized join, no catalog or schema qualifier, no column-renaming table alias, and every table it
    reads is in the schema; otherwise nothing is pushed for the query;
  * in a block whose joins are not all INNER / comma / CROSS / LEFT [OUTER] (RIGHT, FULL, SEMI, ANTI, NATURAL, ASOF ...),
    every read admits nothing;
  * a pushed conjunct is a top-level AND-conjunct of a block's WHERE or of a join's ON (never HAVING) whose column references
    all resolve to that one read of the block (a column of an outer block, i.e. a correlation, never resolves), with at least
    one column, built only from: columns, literals, NULL, TRUE/FALSE, = <> < <= > >=, AND / OR / NOT (inside the one
    conjunct), BETWEEN, IN (literal list), LIKE / ILIKE (no ESCAPE), IS [NOT] NULL, + - * and unary minus,
    CAST(<literal> AS <type>) (``DATE '...'``), INTERVAL '<n>' <unit>, and named parameters (``:name``). No function calls,
    no division, no CASE, no subquery;
  * in a block with a derived table, an unqualified column never resolves (the derived table's columns are not modelled).
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
_REFUSED_ANYWHERE = (exp.Window, exp.With, exp.Union, exp.Intersect, exp.Except, exp.Lateral, exp.Unnest, exp.Values)


@dataclass
class _Read:
    """One read of a base table (a FROM item of one block): the conjuncts it admits by rules (R1)-(R5), columns unqualified."""

    table: str
    preds: list[exp.Expression] = field(default_factory=list)
    why: str = "no pushable conjunct on it"


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
        if isinstance(node, _REFUSED_ANYWHERE):
            return PushdownPlan(refused=f"{type(node).__name__} in the query")
    first = tree.find(exp.Table)
    if first is None:
        return PushdownPlan(refused="no table in the query")
    model = SchemaModel.from_caller(schema, first.name)
    plan = PushdownPlan()
    reads: list[_Read] = []
    handled: set[int] = set()
    for block in [n for n in tree.walk() if isinstance(n, exp.Select)]:
        why = _plan_block(block, model, reads, handled, plan.kept)
        if why is not None:
            return PushdownPlan(refused=why)
    if any(id(t) not in handled for t in tree.find_all(exp.Table)):
        return PushdownPlan(refused="a table reference outside a block's FROM")
    by_table: dict[str, list[_Read]] = {}
    for read in reads:
        by_table.setdefault(read.table, []).append(read)
    for table, rs in by_table.items():
        frags = _combine(rs, dialect)
        if frags:
            plan.pushed[table] = frags
        elif any(r.preds for r in rs):
            blocked = next(r for r in rs if not r.preds)
            plan.kept.append(f"table {table}: nothing pushed -- read {len(rs)} times and one read admits nothing ({blocked.why})")
    return plan


def _combine(rs: list[_Read], dialect: str | None) -> list[Fragment]:
    """Rule (R6): the fragments for a table read by ``rs``: conjuncts every read admits, plus the OR of what remains (only when
    every read has a remainder; a read whose whole predicate is common makes that OR TRUE). Nothing when a read admits nothing."""
    if any(not r.preds for r in rs):
        return []
    keyed = [list(dict.fromkeys(p.sql() for p in r.preds)) for r in rs]
    by_key = {p.sql(): p for r in rs for p in r.preds}
    common = [k for k in keyed[0] if all(k in ks for ks in keyed)]
    out = [by_key[k] for k in common]
    rests = [[k for k in ks if k not in common] for ks in keyed]
    if len(rs) > 1 and all(rests):
        terms = list(dict.fromkeys(tuple(rest) for rest in rests))
        out.append(exp.or_(*(exp.paren(exp.and_(*(by_key[k].copy() for k in term))) for term in terms)))
    return [_fragment(p, dialect) for p in out]


def _plan_block(block: exp.Select, model: SchemaModel, reads: list[_Read], handled: set[int], kept: list[str]) -> str | None:
    """Record the reads of one SELECT block and the conjuncts each admits (rules R1-R5); a reason when nothing may be pushed
    for the whole query."""
    from_ = block.args.get("from_")
    joins = block.args.get("joins") or []
    if from_ is None:
        return "joins without FROM" if joins else None
    items = [from_.this] + [j.this for j in joins]
    quals: dict[str, str | None] = {}  # qualifier -> table (None: a derived table)
    read_of: dict[str, _Read] = {}
    qual_of: list[str | None] = []
    has_derived = False
    for item in items:
        if isinstance(item, exp.Table):
            alias = item.args.get("alias")
            if item.args.get("db") or item.args.get("catalog") or not isinstance(item.this, exp.Identifier) or item.args.get("joins"):
                return "a qualified or computed table reference"
            if alias is not None and alias.columns:
                return "a table alias that renames columns"
            table: str | None = item.name.casefold()
            if table not in model.tables:
                return "a FROM table is not in the schema"
            handled.add(id(item))
            q: str | None = (item.alias or item.name).casefold()
        elif isinstance(item, exp.Subquery) and isinstance(item.this, exp.Select):
            table, q, has_derived = None, (item.alias.casefold() if item.alias else None), True
        else:
            return f"a FROM item that is neither a base table nor a derived SELECT ({type(item).__name__})"
        if q is not None:
            if q in quals:
                return f"qualifier {q} names two tables"
            quals[q] = table
        if table is not None:
            read_of[q] = _Read(table=table)
            reads.append(read_of[q])
        qual_of.append(q)
    preserved = {qual_of[0]}
    pool: list[tuple[exp.Expression, str]] = []  # (conjunct, origin) of INNER ON: rules R2, R5
    left_on: list[tuple[str | None, exp.Expression]] = []  # (null-supplying qualifier, ON conjunct): rules R4, R5
    for join, q in zip(joins, qual_of[1:]):
        side = (join.args.get("side") or "").upper()
        kind = (join.args.get("kind") or "").upper()
        method = join.args.get("method")
        if method or side not in ("", "LEFT") or kind not in ("", "INNER", "CROSS", "OUTER") or (kind == "OUTER" and side != "LEFT"):
            reason = f"{' '.join(x for x in (str(method or ''), side, kind) if x)} JOIN in its block"
            for read in read_of.values():
                read.preds, read.why = [], reason
            kept.append(f"{reason}: the reads {', '.join(sorted(r.table for r in read_of.values()))} of that block admit nothing")
            return None
        on = join.args.get("on")
        ons = _conjuncts(on) if on is not None else []
        if side == "LEFT":
            left_on.extend((q, c) for c in ons)
        else:
            preserved.add(q)
            pool.extend((c, "ON") for c in ons)
    where = block.args.get("where")
    pool = [(c, "WHERE") for c in (_conjuncts(where.this) if where is not None else [])] + pool
    # Rules R1-R3, R5: WHERE and INNER ON conjuncts go to preserved reads only.
    for conj, origin in pool:
        q, why = _single_read(conj, quals, model, has_derived)
        if q is not None and q in preserved:
            read_of[q].preds.append(_strip(conj, model, read_of[q].table))
            continue
        if q is not None:
            why = f"on {q}, the null-supplying side of a LEFT JOIN"
        implied = {q2: p for q2, p in _implied_by_disjunction(conj, quals, model, has_derived).items() if q2 in preserved}
        for q2, pred in implied.items():
            read_of[q2].preds.append(_strip(pred, model, read_of[q2].table))
        kept.append(f"{conj.sql()}  -- {origin}: {why}" + (f"; implied per-table OR pushed for {', '.join(sorted(implied))}" if implied else ""))
    # Rules R4, R5: a LEFT JOIN's ON conjunct goes to that join's null-supplying base read only.
    for nq, conj in left_on:
        q, why = _single_read(conj, quals, model, has_derived)
        if q is not None and q == nq:
            read_of[q].preds.append(_strip(conj, model, read_of[q].table))
            continue
        if q is not None:
            why = f"on {q}, not the null-supplying side of this LEFT JOIN"
        implied = {q2: p for q2, p in _implied_by_disjunction(conj, quals, model, has_derived).items() if q2 == nq}
        for q2, pred in implied.items():
            read_of[q2].preds.append(_strip(pred, model, read_of[q2].table))
        kept.append(f"{conj.sql()}  -- LEFT JOIN ON: {why}" + (f"; implied OR pushed for {nq}" if implied else ""))
    for q, read in read_of.items():
        if q not in preserved and not read.preds:
            read.why = f"{q} is the null-supplying side of a LEFT JOIN"
    return None


def _implied_by_disjunction(conj: exp.Expression, quals: dict[str, str | None], model: SchemaModel, has_derived: bool) -> dict[str, exp.Expression]:
    """Rule (R5): for ``D1 OR ... OR Dn`` where every Di has AND-conjuncts over read q only: q -> ``(q-part of D1) OR ... OR
    (q-part of Dn)``.

    Implied, hence sound to push: if no q-part is TRUE of a row, every Di (q-part AND rest) is FALSE or NULL for every joined
    row built from it, so the OR is not TRUE and the filter drops the row anyway (TPC-H Q19 shape)."""
    node = conj
    while isinstance(node, exp.Paren):
        node = node.this
    if not isinstance(node, exp.Or):
        return {}
    per: list[dict[str, list[exp.Expression]]] = []
    for d in _disjuncts(node):
        parts: dict[str, list[exp.Expression]] = {}
        for c in _conjuncts(d):
            q, _why = _single_read(c, quals, model, has_derived)
            if q is not None:
                parts.setdefault(q, []).append(c.copy())
        per.append(parts)
    out: dict[str, exp.Expression] = {}
    for q in sorted(set.intersection(*(set(p) for p in per))):
        out[q] = exp.or_(*(exp.paren(exp.and_(*p[q])) for p in per))
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


def _single_read(conj: exp.Expression, quals: dict[str, str | None], model: SchemaModel, has_derived: bool) -> tuple[str | None, str]:
    """The one base-table read (its qualifier) every column of ``conj`` resolves to in this block, or ``(None, reason)``."""
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
        owner = _owner(col, quals, model, has_derived)
        if owner is None:
            return None, f"column {col.sql()} does not resolve to exactly one base table of its block"
        owners.add(owner)
    if len(owners) != 1:
        return None, "no column" if not owners else f"columns of {len(owners)} tables"
    return owners.pop(), ""


def _owner(col: exp.Column, quals: dict[str, str | None], model: SchemaModel, has_derived: bool) -> str | None:
    """The qualifier of the block's base-table read that ``col`` names. A column of an outer block (a correlation) does not
    resolve: SQL binds a name to the innermost block that has it, so a name no local read has belongs to an outer block."""
    if col.args.get("db") or col.args.get("catalog"):
        return None
    name = col.name.casefold()
    if col.table:
        q = col.table.casefold()
        table = quals.get(q)
        return q if table is not None and name in model.tables[table] else None
    if has_derived:
        return None
    hits = [q for q, t in quals.items() if t is not None and name in model.tables[t]]
    return hits[0] if len(hits) == 1 else None


def _strip(conj: exp.Expression, model: SchemaModel, table: str) -> exp.Expression:
    """``conj`` with every column replaced by the table's quoted original column name (the export reads one table)."""
    out = conj.copy()
    for col in list(out.find_all(exp.Column)):
        orig = model.original_column_names[(table, col.name.casefold())]
        col.replace(exp.column(exp.to_identifier(orig, quoted=True)))
    return out


def _fragment(pred: exp.Expression, dialect: str | None) -> Fragment:
    params = tuple(dict.fromkeys(p.name for p in pred.find_all(exp.Placeholder)))
    return Fragment(sql=pred.sql(dialect=dialect), params=params)


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
