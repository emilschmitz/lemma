"""Streaming executors, phase 2a (lemma.toml ``[run] stream``, docs/STREAM.md "Joins"): inner equi-joins of ONE streamed table with one or
more MATERIALIZED build tables.

SQL side (before the spec is emitted):

* the stream table is named by a ``-- stream: <table>`` line of the SQL text. The host writes that line with :func:`with_header` from
  :func:`choose_stream_table`, the deterministic rule: the table with the most rows after its own single-table filter conjuncts (WHERE
  and ON) on the run's database; a tie goes to the table first in FROM. The header is part of the query text (the spec's SQL comment
  shows it), so every later emission (prepare, each session, the official measure, the install) states the same spec. A join without
  the header is refused loudly (no default choice);
* :func:`outermost` puts the stream table first in FROM (all joins are inner, so the order does not change the result) and lets
  ``parse_query.rewrite_comma_joins`` connect the build tables through the ON/WHERE equalities; the emitter then states the join with
  the stream table as the OUTER fold (``X(t, u, i0, k) = X_d1(t, u, i0, 0, k) + X(t, u, i0 + 1, k)``), so a stream row's contribution is
  the inner fold over the builds at that row and ``agg_rng`` stays a difference of suffix folds;
* :func:`check_sql` (the gate) refuses outer / semi / anti / cross / natural joins, USING, subqueries, CTEs and self joins.

Spec side (:func:`to_stream_join`, after the decline wrap): ``run_query`` is replaced by the phase-1 block extended by the builds. The
monoid ``Agg`` (SUM / COUNT / AVG folds, ``hits``, ``n_hit_*``; MIN / MAX over a join are refused), ``agg_row(t, <builds>, i0, k, p)``
(the inner fold at row ``i0``), ``agg_rng`` and the lemmas are emitted for the stream table only; build tables are ordinary ``Cols_<b>``
arguments with ``valid_cols_<b>``. The chunk view and its trusted items are phase 1's (S1, S2 for the stream table), nothing else is
trusted. The agent gets a seventh region, AGENT_BUILD (the body of ``q_build``), a ``QBuild`` type in AGENT_STATE and
``qbuild_inv(bld, <builds>, p)`` in AGENT_HELPERS; ``qacc_inv`` and ``st_val`` take the build.

Host runtime of a join (``Pool``, fixed, verified): ONE object per stream holds the build tables, the agent's ``QBuild`` and one
``vstd::rwlock::RwLock`` slot per worker (a state ``QAcc`` and its chunk segments). Workers step their own slot (``pool_step(&pool, w,
chunk)``, uncontended lock); ``pool_finish`` consumes the pool, merges every slot and checks that the segments tile ``[0, n)`` as phase 1's
``exec_finish``. Why not phase 1's per-worker ``Exec``: two executors could only be merged if Verus knew they hold the same build, and
no run-time check short of comparing the build tables proves that (an ``Arc`` pointer comparison has no spec in vstd, adding one would be a
new trusted item). Keeping every state inside the one pool makes the build the same by construction.
"""

from __future__ import annotations

import contextlib
import contextvars
import re
from dataclasses import dataclass, field
from pathlib import Path

import sqlglot
from sqlglot import exp

from declarative_spec.parse import DeclarativeUnsupported

BUILD_START, BUILD_END = "// AGENT_BUILD_START", "// AGENT_BUILD_END"
JOIN_MARKER = "// LEMMA_STREAM_JOIN:"
RULE = (
    "the table with the most rows after its own single-table filter conjuncts (WHERE and ON) on the run's database; a tie goes to the "
    "table first in FROM"
)

STUB = {
    "state": "pub struct QAcc {\n    pub z: u8,\n}\n\npub struct QBuild {\n    pub z: u8,\n}",
    "helpers": (
        "pub open spec fn qbuild_inv(bld: &QBuild, @@BUILD_PARAMS@@, p: &Params) -> bool {\n    true\n}\n\n"
        "pub open spec fn qacc_inv(s: &QAcc, bld: &QBuild) -> bool {\n    true\n}\n\n"
        "pub open spec fn st_val(s: &QAcc, bld: &QBuild, k: Key) -> Agg {\n    agg_zero()\n}"
    ),
    "build": "None",
    "init": "QAcc { z: 0 }",
    "step": "false",
    "merge": "None",
    "finish": "None",
}

def _refuse(why: str) -> DeclarativeUnsupported:
    return DeclarativeUnsupported(f"stream (lemma.toml [run] stream): {why}")


def is_join(spec_rs: str) -> bool:
    return JOIN_MARKER in spec_rs


# ---- the stream table: header, rule, reorder ----------------------------------------------------------------------------------------

_HEADER = re.compile(r"^[ \t]*--[ \t]*stream:[ \t]*(.*?)[ \t]*$", re.M | re.I)
_CHOSEN: contextvars.ContextVar[str | None] = contextvars.ContextVar("lemma_stream_table", default=None)


def header_table(sql: str) -> str | None:
    """The table a ``-- stream: <table>`` line of the SQL names, or None without one (more than one, or not a name: refused)."""
    found = _HEADER.findall(sql)
    if not found:
        return None
    if len(found) > 1:
        raise _refuse("more than one `-- stream:` line")
    name = found[0].strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise _refuse(f"`-- stream: {name}` does not name a table")
    return name


def with_header(sql: str, table: str) -> str:
    """``sql`` with the ``-- stream: <table>`` line first (an existing line must name the same table)."""
    have = header_table(sql)
    if have is not None:
        if have.casefold() != table.casefold():
            raise _refuse(f"the SQL already streams {have}, the rule chose {table}")
        return sql
    return f"-- stream: {table}\n{sql}"


@contextlib.contextmanager
def emitting(sql: str):
    """While a spec is emitted from ``sql``: the stream table its header names (read by :func:`outermost_for_emit`)."""
    token = _CHOSEN.set(header_table(sql))
    try:
        yield
    finally:
        _CHOSEN.reset(token)


def _select(sql: str) -> exp.Select:
    tree = sqlglot.parse_one(sql)
    if not isinstance(tree, exp.Select):
        raise _refuse("the query is not one SELECT (set operations are not stated)")
    return tree


def _tables(select: exp.Select) -> list[exp.Table]:
    from_ = select.args.get("from_")
    if from_ is None:
        return []
    nodes = [from_.this] + [j.this for j in select.args.get("joins") or []]
    if not all(isinstance(n, exp.Table) for n in nodes):
        raise _refuse("a FROM item that is not a base table (a derived table or a table function)")
    return nodes  # type: ignore[return-value]


def check_sql(sql: str) -> None:
    """The phase-2a join gate (SQL level): inner equi-joins of base tables, no subquery, no CTE, no self join."""
    try:
        tree = sqlglot.parse_one(sql)
    except sqlglot.errors.SqlglotError:
        return  # the emitter reports the parse error
    if not list(tree.find_all(exp.Join)):
        return  # one table: phase 1's gate (stream.check_sql, stream.read_shape) decides
    if not isinstance(tree, exp.Select):
        raise _refuse("a set operation (UNION / EXCEPT / INTERSECT) is not stated")
    if tree.args.get("with_") is not None:
        raise _refuse("a WITH clause (CTE) is not stated (phase 3)")
    nested = [s for s in tree.find_all(exp.Select) if s is not tree]
    if nested:
        raise _refuse("a subquery (IN / EXISTS / scalar / derived table) is not stated (phase 3)")
    joins = tree.args.get("joins") or []
    for j in joins:
        side = (j.args.get("side") or "").upper()
        kind = (j.args.get("kind") or "").upper()
        if side or kind in ("SEMI", "ANTI", "OUTER", "CROSS", "ASOF", "POSITIONAL") or j.args.get("method"):
            raise _refuse(f"a {' '.join(x for x in (j.args.get('method') or '', side, kind) if x)} JOIN: only inner equi-joins are streamed (phase 2b/3)")
        if j.args.get("using"):
            raise _refuse("JOIN .. USING: write the equality in ON")
    nodes = _tables(tree)
    names = [n.name.casefold() for n in nodes]
    if len(set(names)) != len(names):
        raise _refuse("a self join (a table twice): a stream reads one table once and builds others; streaming one table twice is not stated")


def outermost(sql: str, schema: dict, table: str) -> str:
    """``sql`` (after ``rewrite_comma_joins``) with ``table`` first in FROM; the others follow, each joined through its ON/WHERE equality."""
    from declarative_spec.parse_query import rewrite_comma_joins

    select = _select(sql)
    nodes = _tables(select)
    names = [n.name.casefold() for n in nodes]
    if table.casefold() not in names:
        raise _refuse(f"`-- stream: {table}` names no table of the query ({', '.join(n.name for n in nodes)})")
    pos = names.index(table.casefold())
    if pos == 0:
        return sql
    joins = select.args.get("joins") or []
    conds = [j.args["on"] for j in joins if j.args.get("on") is not None]
    if len(conds) != len(joins):
        raise _refuse("a join without an ON equality (a cross product) is not streamed")
    where = select.args.get("where")
    if where is not None:
        conds.append(where.this)
    new = select.copy()
    new.set("from_", exp.From(this=nodes[pos].copy()))
    new.set("joins", [exp.Join(this=n.copy()) for i, n in enumerate(nodes) if i != pos])
    new.set("where", exp.Where(this=exp.and_(*[c.copy() for c in conds])))
    out = rewrite_comma_joins(new.sql(), schema)
    check = _select(out)
    if any(j.args.get("on") is None for j in check.args.get("joins") or []) or _tables(check)[0].name.casefold() != table.casefold():
        raise _refuse(f"the join cannot be stated with {table} outermost: a build table has no equality to the tables before it")
    return out


def outermost_for_emit(sql: str, schema: dict) -> str:
    """In ``emit._emit_fixed`` (stream on, after ``rewrite_comma_joins``): the SQL with the header's table outermost. A join needs the
    header; a single table needs none (and a header there must name it)."""
    try:
        tree = sqlglot.parse_one(sql)
    except sqlglot.errors.SqlglotError:
        return sql  # the emitter reports the parse error
    chosen = _CHOSEN.get()
    if not isinstance(tree, exp.Select) or not tree.args.get("joins"):
        from_ = tree.args.get("from_") if isinstance(tree, exp.Select) else None
        single = from_.this if from_ is not None else None
        if chosen is not None and not (isinstance(single, exp.Table) and single.name.casefold() == chosen.casefold()):
            raise _refuse(f"`-- stream: {chosen}` names no table of the query")
        return sql  # one table (phase 1): unchanged
    nodes = _tables(tree)
    if chosen is None:
        raise _refuse(
            "a join needs its stream table named: a `-- stream: <table>` line in the SQL (stream_join.choose_stream_table: "
            + RULE
            + ")"
        )
    return outermost(sql, schema, chosen)


def choose_stream_table(sql: str, schema: dict, db_path: Path | str) -> dict:
    """The deterministic rule (:data:`RULE`) on ``db_path``: ``{"table", "rows_after_filters": {table: rows}, "rule"}``.

    The single-table conjuncts are found as the data profile finds them (``research_loop.data_profile``: WHERE and every ON, each
    conjunct whose columns all belong to one table), each table counted once with all of its conjuncts. ``sql`` is fixed-constant SQL
    (a template: one binding's literals)."""
    from declarative_spec.parse_query import rewrite_comma_joins
    from research_loop.data_profile import QUERY_TIMEOUT_SEC, _Runner, _SelectProfile, _sql

    check_sql(sql)
    select = sqlglot.parse_one(rewrite_comma_joins(sql, schema), read="duckdb")
    if not isinstance(select, exp.Select):
        raise _refuse("the query is not one SELECT")
    runner = _Runner(Path(db_path), QUERY_TIMEOUT_SEC)
    try:
        prof = _SelectProfile(select, runner)
        if prof.skipped or any(s.derived for s in prof.sources):
            raise _refuse("a FROM item that is not a base table of the database")
        filters, _eq = prof._predicates()
        counts: dict[str, int] = {}
        for s in prof.sources:
            conds = filters[s.alias.lower()]
            where = " AND ".join(f"({_sql(c)})" for c in conds)
            counts[s.label] = runner.count(f"SELECT 1 FROM {s.from_sql}" + (f" WHERE {where}" if where else ""))
    finally:
        runner.con.close()
    best = max(counts.values())
    table = next(t for t, v in counts.items() if v == best)  # dicts keep FROM order: the first of a tie
    return {"table": table, "rows_after_filters": counts, "rule": RULE}


def is_join_sql(sql: str) -> bool:
    try:
        tree = sqlglot.parse_one(sql)
    except sqlglot.errors.SqlglotError:
        return False
    return bool(list(tree.find_all(exp.Join)))


def ensure_header(sql: str, schema: dict, db_path: Path | str | None, record_dir: Path | None) -> str:
    """A join without a ``-- stream:`` line gets the one the rule (:func:`choose_stream_table`) picks on ``db_path`` (the run's
    database); the choice and the counts are written to ``<record_dir>/stream_choice.json``. Fixed SQL, a one-table query or SQL that
    already names its stream table is returned unchanged. A template is counted with its first binding's literals (``binding``)."""
    if header_table(sql) is not None or not is_join_sql(sql):
        return sql
    if not db_path:
        raise _refuse("a join needs its stream table, chosen on the run's database (LEMMA_MEASURE_DB is not set)")
    from declarative_spec import templates

    literal = sql
    template = templates.parse_template(sql)
    if template is not None:
        from declarative_spec.drive import template_bindings

        drawn = template_bindings(sql)
        literal = templates.with_literals(sql, drawn["bindings"][0])
    choice = choose_stream_table(literal, schema, db_path)
    if record_dir is not None:
        import json

        record_dir.mkdir(parents=True, exist_ok=True)
        (record_dir / "stream_choice.json").write_text(json.dumps({**choice, "db_path": str(db_path)}, indent=2) + "\n")
    return with_header(sql, choice["table"])


# ---- reading the emitted join spec ----------------------------------------------------------------------------------------------------


@dataclass
class JFold:
    name: str
    inner: str  # the fold over the builds at one stream row: `inner(tabs, i0, 0, args)`
    args: list[str]  # after (tabs, i0), substituted (`k`, `p.<name>`)


@dataclass
class JoinShape:
    ts: str  # the stream table's suffix
    builds: list[str]  # the build tables' suffixes, in run_query's order (= the inner fold's nesting)
    cols: list[tuple[str, str]]  # the stream table's (field, element type), without n
    params: list[tuple[str, str]]
    key: str | None
    rh_args: list[str]
    folds: list[JFold] = field(default_factory=list)
    hit_preds: list[tuple[str, list[str]]] = field(default_factory=list)
    ok_args: list[str] = field(default_factory=list)

    # Variable names: the stream table is `t`, a build table `b_<suffix>` (a bare table name can clash with a glob-imported vstd
    # function, e.g. `sub`, which Verus then reports as ambiguous; the host's own names never start with `b_`).
    @property
    def bvars(self) -> list[str]:
        return [f"b_{b}" for b in self.builds]

    @property
    def tabs(self) -> list[str]:
        return ["t", *self.bvars]

    @property
    def types(self) -> list[str]:
        return [self.ts, *self.builds]

    @property
    def idx(self) -> list[str]:
        return [f"i{j}" for j in range(len(self.tabs))]

    @property
    def tp(self) -> str:
        """The tables as parameters of a host spec fn: `t: &Cols_t, b_u: &Cols_u`."""
        return ", ".join(f"{v}: &Cols_{s}" for v, s in zip(self.tabs, self.types, strict=True))

    @property
    def ta(self) -> str:
        return ", ".join(self.tabs)

    @property
    def bp(self) -> str:
        return ", ".join(f"{v}: &Cols_{s}" for v, s in zip(self.bvars, self.builds, strict=True))

    @property
    def ba(self) -> str:
        return ", ".join(self.bvars)


def read_join_shape(spec: str) -> JoinShape:
    from declarative_spec import stream
    from declarative_spec.templates import spec_params

    if re.search(r"pub struct OutRow", spec) is None:
        raise _refuse("the result is not a list of OutRow rows (map results are not stated)")
    if "__dict" in spec:
        raise _refuse("dictionary-encoded strings: stream tables use the plain encoding")
    if re.search(r"\bf64\b", spec):
        raise _refuse("a FLOAT/DOUBLE value is not stated in the stream contract")
    m = stream._RUN_QUERY.search(spec)
    if m is None:
        raise _refuse("no run_query contract of the expected form (Option<Vec<OutRow>>, assumptions = false)")
    sig = stream._split_args(m.group("params"))
    tabs = [(n, t) for n, t in sig if t.startswith("&Cols_")]
    ntab = len(tabs)
    if sig[:ntab] != tabs:
        raise _refuse("run_query must take its tables first")
    types = [t.removeprefix("&Cols_") for _n, t in tabs]
    if len(set(types)) != len(types):
        raise _refuse("a self join (one table twice) is not stated")
    ts, builds = types[0], types[1:]
    declared = {name: ty for name, ty, _lo, _hi in spec_params(spec)}
    params: list[tuple[str, str]] = []
    for name, ty in sig[ntab:]:
        if not name.startswith("param_") or name.removeprefix("param_") not in declared:
            raise _refuse(f"run_query parameter {name}: {ty} is not a template parameter")
        if ty not in ("i64", "i32"):
            raise _refuse(f"template parameter {name}: {ty}: only integer, DECIMAL and DATE parameters are stated")
        params.append((name.removeprefix("param_"), ty))
    # i128: DECIMAL(38, s) cells (DuckDB HUGEINT storage, the same 16 little-endian bytes); the ABI 6 glue does not hand them yet
    allowed = ("i128", "i64", "i32", "i16", "i8", "u64", "u32", "u16", "u8", "bool", "String")
    cols_of: dict[str, list[tuple[str, str]]] = {}
    for s in types:
        body = re.search(rf"pub struct Cols_{s} \{{\n((?:    pub [^\n]+\n)+)\}}", spec)
        if body is None:
            raise _refuse(f"no struct Cols_{s}")
        cols_of[s] = re.findall(r"    pub ((?:r#)?\w+): Vec<([^>\n]+)>,", body.group(1))
        for f, ty in cols_of[s]:
            if ty not in allowed:
                raise _refuse(f"column {s}.{f}: Vec<{ty}> is not stated for a stream or a build table")
    pvars = [n for n, _t in tabs]
    tp_spec = ", ".join(f"{n}: {t}" for n, t in tabs)
    idx = [f"i{j}" for j in range(ntab)]
    idx_p = ", ".join(f"{i}: int" for i in idx)
    ka = re.search(rf"pub open spec fn key_at\({re.escape(tp_spec)}, {re.escape(idx_p)}\) -> ([^\n]+) \{{\n", spec)
    key = ka.group(1).strip() if ka else None
    if key is not None and "bool" in key:
        raise _refuse("a GROUP BY key over a nullable column (a NULL cell's value is not part of the chunk view)")
    rh = stream._spec_fn_sig(spec, "row_hit")
    if rh is None or rh[: 2 * ntab] != [*tabs, *[(i, "int") for i in idx]]:
        raise _refuse("no row_hit(<tables>, <row indices>, ..) of the expected form")
    pnames = {n for n, _t in params}

    def sub(text: str) -> str:
        return re.sub(r"(?<![\w.])param_(\w+)\b", lambda mm: f"p.{mm.group(1)}" if mm.group(1) in pnames else mm.group(0), text)

    shape = JoinShape(ts=ts, builds=builds, cols=cols_of[ts], params=params, key=key, rh_args=[sub(n) for n, _t in rh[2 * ntab :]])
    call_args = [a.strip() for a in m.group("args").split(",")]
    if call_args[:ntab] != pvars:
        raise _refuse("run_query_ok is not called on the tables first")
    shape.ok_args = call_args[ntab:]

    for name in re.findall(r"pub open spec fn ((?:min|max)_\w+)\(", spec):
        if not name.endswith("_val"):
            raise _refuse(f"{name}: MIN / MAX over a join is not stated in phase 2a")

    v0 = re.escape(pvars[0])
    pv = ", ".join(pvars)
    fold_re = re.compile(
        rf"pub open spec fn (\w+)\({re.escape(tp_spec)}, i0: int((?:, [^\n]*?)?)\) -> int\n"
        rf"    decreases {v0}\.n as int - i0\n\{{\n"
        rf"    if i0 < 0 \|\| i0 >= {v0}\.n as int \{{\n        0int\n    \}} else \{{\n"
        rf"        (\w+)\({re.escape(pv)}, i0, 0((?:, \w+)*)\) \+ \1\({re.escape(pv)}, i0 \+ 1((?:, \w+)*)\)\n"
        rf"    \}}\n\}}"
    )
    found: dict[str, JFold] = {}
    for fm in fold_re.finditer(spec):
        args = [n for n, _t in stream._split_args(fm.group(2).lstrip(", "))]
        inner_args = [a.strip() for a in fm.group(4).split(",") if a.strip()]
        rec = [a.strip() for a in fm.group(5).split(",") if a.strip()]
        if rec != args or inner_args != args:
            raise _refuse(f"fold {fm.group(1)} recurses with other arguments")
        found[fm.group(1)] = JFold(name=fm.group(1), inner=fm.group(3), args=[sub(a) for a in args])
    inner_names = {f.inner for f in found.values()}
    for name in re.findall(r"pub open spec fn (\w+)\([^\n]*\n    decreases ", spec):
        if name in found or name == "seq_le":
            continue
        base = re.sub(r"_d\d+$", "", name)
        if base not in found or not (name in inner_names or re.fullmatch(rf"{re.escape(base)}_d\d+", name)):
            raise _refuse(f"spec fn {name} is not a recognized fold over the join (COUNT DISTINCT and other folds are not phase 2a)")
        body = re.search(rf"pub open spec fn {re.escape(name)}\(.*?\n\}}\n", spec, re.S)
        if body is not None and re.search(r"\b(?:exists|forall|choose)\s*\|", body.group(0)):
            raise _refuse(f"fold {name}: its per-row term looks at other rows (not phase 2a)")
    shape.folds = list(found.values())
    ok = re.search(r"pub open spec fn run_query_ok\([^\n]*\n(.*?)\n\}\n", spec, re.S)
    if ok is None:
        raise _refuse("no run_query_ok")
    ex_vars = ", ".join(f"{i}: int" for i in idx)
    for name in dict.fromkeys(re.findall(rf"exists\|{re.escape(ex_vars)}\| #!\[trigger (hit_\w+)\({re.escape(pv)}, {', '.join(idx)}", ok.group(1))):
        hs = stream._spec_fn_sig(spec, name)
        if hs is None or hs[: 2 * ntab] != [*tabs, *[(i, "int") for i in idx]]:
            raise _refuse(f"{name}: unexpected signature")
        shape.hit_preds.append((name, [sub(n) for n, _t in hs[2 * ntab :]]))
    if not shape.folds:
        raise _refuse("not an aggregate query (phase 2a streams grouped or ungrouped aggregates over a join only)")
    return shape


# ---- emission -------------------------------------------------------------------------------------------------------------------------


def _c(name: str, *parts: str) -> str:
    return f"{name}({', '.join(p for p in parts if p)})"


def _cond(sh: JoinShape, pred: str, args: list[str], idx: list[str]) -> str:
    """The pair condition of a count field at the row indices ``idx``: the predicate (and the group key when grouped)."""
    c = _c(pred, sh.ta, *idx, *args)
    return f"{c} && {_c('key_at', sh.ta, *idx)} == k" if sh.key else c


def _counts(sh: JoinShape) -> list[tuple[str, str, list[str]]]:
    return [("hits", "row_hit", sh.rh_args)] + [(f"n_{n}", n, a) for n, a in sh.hit_preds]


def _count_fns(sh: JoinShape) -> list[str]:
    """Per count field c: the inner folds stream_c_d<j> (j = 1..m over build j) and the stream fold stream_c, with their lemmas."""
    out: list[str] = []
    m = len(sh.builds)
    tabs, idx = sh.tabs, sh.idx
    for c, pred, args in _counts(sh):
        for j in range(m, 0, -1):
            bj = tabs[j]
            head = idx[:j]
            params = ", ".join([sh.tp, *[f"{i}: int" for i in idx[: j + 1]], "k: Key", "p: &Params"])
            if j == m:
                term = f"(if {_cond(sh, pred, args, idx)} {{ 1int }} else {{ 0int }})"
            else:
                term = _c(f"stream_{c}_d{j + 1}", sh.ta, *idx[: j + 1], "0", "k", "p")
            out.append(f"""pub open spec fn stream_{c}_d{j}({params}) -> int
    decreases {bj}.n as int - {idx[j]},
{{
    if {idx[j]} < 0 || {idx[j]} >= {bj}.n as int {{
        0int
    }} else {{
        {term} + {_c(f'stream_{c}_d{j}', sh.ta, *head, f'{idx[j]} + 1', 'k', 'p')}
    }}
}}""")
            # positivity: > 0 iff the next level (or the pair condition, innermost) holds somewhere in [i_j, n_j)
            lp = ", ".join([sh.tp, *[f"{i}: int" for i in idx[: j + 1]], "k: Key", "p: &Params"])
            me = _c(f"stream_{c}_d{j}", sh.ta, *idx[: j + 1], "k", "p")
            if j == m:
                cx = _cond(sh, pred, args, [*head, "x"])
                trig = _c(pred, sh.ta, *head, "x", *args)
                ex = f"(exists|x: int| #![trigger {trig}] {idx[j]} <= x < {bj}.n as int && {cx})"
                here = _cond(sh, pred, args, idx[: j + 1])
                zero_case = f"!({here})"
                witness_note = f"assert({idx[j]} <= {idx[j]} < {bj}.n as int && {here});"
                ch = f"choose|x: int| #![trigger {trig}] {idx[j]} <= x < {bj}.n as int && {cx}"
                body_here = ""
            else:
                nx = _c(f"stream_{c}_d{j + 1}", sh.ta, *head, "x", "0", "k", "p")
                ex = f"(exists|x: int| {idx[j]} <= x < {bj}.n as int && (#[trigger] {nx}) > 0)"
                here_v = _c(f"stream_{c}_d{j + 1}", sh.ta, *idx[: j + 1], "0", "k", "p")
                zero_case = f"{here_v} <= 0"
                witness_note = f"assert({here_v} > 0);"
                ch = f"choose|x: int| {idx[j]} <= x < {bj}.n as int && (#[trigger] {nx}) > 0"
                body_here = f"\n        lemma_stream_{c}_d{j + 1}_pos({sh.ta}, {', '.join(idx[: j + 1])}, 0, k, p);"
            out.append(f"""pub proof fn lemma_stream_{c}_d{j}_pos({lp})
    requires
        0 <= {idx[j]} <= {bj}.n as int,
    ensures
        {me} >= 0,
        {me} > 0 <==> {ex},
    decreases {bj}.n as int - {idx[j]},
{{
    if {idx[j]} < {bj}.n as int {{
        lemma_stream_{c}_d{j}_pos({sh.ta}, {', '.join([*head, f'{idx[j]} + 1'])}, k, p);{body_here}
        if {zero_case} {{
            if {ex} {{
                let x = {ch};
                assert(x != {idx[j]});
            }}
        }} else {{
            {witness_note}
        }}
    }}
}}""")
        t0 = sh.tabs[0]
        out.append(f"""pub open spec fn stream_{c}({sh.tp}, i0: int, k: Key, p: &Params) -> int
    decreases {t0}.n as int - i0,
{{
    if i0 < 0 || i0 >= {t0}.n as int {{
        0int
    }} else {{
        agg_row({sh.ta}, i0, k, p).{c} + stream_{c}({sh.ta}, i0 + 1, k, p)
    }}
}}""")
        out.append(f"""pub proof fn lemma_stream_{c}_pos({sh.tp}, i0: int, k: Key, p: &Params)
    requires
        0 <= i0 <= {t0}.n as int,
    ensures
        stream_{c}({sh.ta}, i0, k, p) >= 0,
        stream_{c}({sh.ta}, i0, k, p) > 0 <==> (exists|j: int| i0 <= j < {t0}.n as int && (#[trigger] agg_row({sh.ta}, j, k, p)).{c} > 0),
    decreases {t0}.n as int - i0,
{{
    if i0 < {t0}.n as int {{
        lemma_stream_{c}_pos({sh.ta}, i0 + 1, k, p);
        lemma_stream_{c}_d1_pos({sh.ta}, i0, 0, k, p);
        if agg_row({sh.ta}, i0, k, p).{c} <= 0 {{
            if exists|j: int| i0 <= j < {t0}.n as int && (#[trigger] agg_row({sh.ta}, j, k, p)).{c} > 0 {{
                let j = choose|j: int| i0 <= j < {t0}.n as int && (#[trigger] agg_row({sh.ta}, j, k, p)).{c} > 0;
                assert(j != i0);
            }}
        }}
    }}
}}""")
    return out


def _total_count(sh: JoinShape, c: str, pred: str, args: list[str]) -> tuple[list[str], str]:
    """lemma_agg_total's ensures and body for one count field: > 0 iff some tuple of rows meets the pair condition."""
    t0 = sh.tabs[0]
    idx = sh.idx
    m = len(sh.builds)
    rng = f"agg_rng({sh.ta}, 0, {t0}.n as int, k, p).{c}"
    vars_ = ", ".join(f"{i}: int" for i in idx)
    trig = _c(pred, sh.ta, *idx, *args)
    cond = _cond(sh, pred, args, idx)
    ens = [f"        {rng} >= 0,", f"        {rng} > 0 <==> (exists|{vars_}| #![trigger {trig}] {cond}),"]
    # ==> from a witness tuple: innermost level first, each level's positivity at index 0
    up = []
    for j in range(m, 0, -1):
        up.append(f"        lemma_stream_{c}_d{j}_pos({sh.ta}, {', '.join(idx[:j])}, 0, k, p);")
        if j < m:
            up.append(f"        assert({_c(f'stream_{c}_d{j + 1}', sh.ta, *idx[: j + 1], '0', 'k', 'p')} > 0);")
    up.append(f"        assert(agg_row({sh.ta}, i0, k, p).{c} > 0);")
    # <== down from the stream row: choose each level's index
    down = [
        f"        let j = choose|j: int| 0 <= j < {t0}.n as int && (#[trigger] agg_row({sh.ta}, j, k, p)).{c} > 0;",
        "        let i0 = j;",
    ]
    for j in range(1, m + 1):
        down.append(f"        lemma_stream_{c}_d{j}_pos({sh.ta}, {', '.join(idx[:j])}, 0, k, p);")
        bj = sh.tabs[j]
        if j < m:
            nx = _c(f"stream_{c}_d{j + 1}", sh.ta, *idx[:j], "x", "0", "k", "p")
            down.append(f"        let {idx[j]} = choose|x: int| 0 <= x < {bj}.n as int && (#[trigger] {nx}) > 0;")
        else:
            cx = _cond(sh, pred, args, [*idx[:j], "x"])
            tx = _c(pred, sh.ta, *idx[:j], "x", *args)
            down.append(f"        let {idx[j]} = choose|x: int| #![trigger {tx}] 0 <= x < {bj}.n as int && {cx};")
    down.append(f"        assert({cond});")
    choose_all = f"choose|{vars_}| #![trigger {trig}] {cond}"
    body = f"""    lemma_stream_{c}_pos({sh.ta}, 0, k, p);
    assert(stream_{c}({sh.ta}, {t0}.n as int, k, p) == 0);
    if exists|{vars_}| #![trigger {trig}] {cond} {{
        let ({', '.join(idx)}) = {choose_all};
{chr(10).join(up)}
    }}
    if {rng} > 0 {{
{chr(10).join(down)}
    }}"""
    return ens, body


def emit_join_contract(sh: JoinShape) -> str:
    from declarative_spec import stream

    tv, ts = sh.tabs[0], sh.ts
    cols = f"Cols_{ts}"
    key = sh.key or "()"
    fields: list[tuple[str, str, str]] = []  # (field, row expr, rng expr)
    for f in sh.folds:
        fields.append(
            (f.name, _c(f.inner, sh.ta, "i0", "0", *f.args), f"{_c(f.name, sh.ta, 'lo', *f.args)} - {_c(f.name, sh.ta, 'hi', *f.args)}")
        )
    for c, _pred, _args in _counts(sh):
        fields.append((c, _c(f"stream_{c}_d1", sh.ta, "i0", "0", "k", "p"), f"stream_{c}({sh.ta}, lo, k, p) - stream_{c}({sh.ta}, hi, k, p)"))
    struct_fields = "\n".join(f"    pub {n}: int," for n, _r, _g in fields)
    zero = ", ".join(f"{n}: 0int" for n, _r, _g in fields)
    plus = ",\n        ".join(f"{n}: a.{n} + b.{n}" for n, _r, _g in fields)
    row_in = ",\n            ".join(f"{n}: {r}" for n, r, _g in fields)
    rng = ",\n        ".join(f"{n}: {g}" for n, _r, g in fields)

    step_lines = [
        f"        assert({_c(f.name, sh.ta, 'i0', *f.args)} == {_c(f.inner, sh.ta, 'i0', '0', *f.args)} + {_c(f.name, sh.ta, 'i0 + 1', *f.args)});"
        for f in sh.folds
    ]
    step_lines += [
        f"        assert(stream_{c}({sh.ta}, i0, k, p) == agg_row({sh.ta}, i0, k, p).{c} + stream_{c}({sh.ta}, i0 + 1, k, p));"
        for c, _p, _a in _counts(sh)
    ]
    tot_ens = [f"        agg_rng({sh.ta}, 0, {tv}.n as int, k, p).{f.name} == {_c(f.name, sh.ta, '0', *f.args)}," for f in sh.folds]
    tot_body = [f"    assert({_c(f.name, sh.ta, f'{tv}.n as int', *f.args)} == 0);" for f in sh.folds]
    for c, pred, args in _counts(sh):
        e, b = _total_count(sh, c, pred, args)
        tot_ens += e
        tot_body.append(b)

    params_struct = "\n".join(f"    pub {n}: {t}," for n, t in sh.params)
    params_eq = " && ".join(f"a.{n} == b.{n}" for n, _t in sh.params) or "true"
    ok_p = ", ".join(["&t@", sh.ba, *[f"p.{a.removeprefix('param_')}" for a in sh.ok_args]])
    ok_pl = ", ".join(
        [f"&stream_table_{ts}(pl.sid())", *[f"&pl.build_{b}()" for b in sh.builds], *[f"pl.params().{a.removeprefix('param_')}" for a in sh.ok_args]]
    )
    vb = ",\n        ".join(f"valid_cols_{b}({v})" for v, b in zip(sh.bvars, sh.builds, strict=True))
    chunk = stream._chunk_items(stream.Shape(tv=tv, ts=ts, cols=sh.cols, params=sh.params, key=sh.key, rh_args=sh.rh_args))
    extra = "\n\n".join(_count_fns(sh))
    builds_txt = ", ".join(f"`{b}`" for b in sh.builds)
    return f"""{stream.STREAM_MARKER}
{JOIN_MARKER} {ts} is streamed (outermost); {', '.join(sh.builds)} {'is a build table' if len(sh.builds) == 1 else 'are build tables'} (materialized, read-only)
// The streaming contract of an inner join. T = stream_table_{ts}(id) is the ghost table of one stream: the rows DuckDB's parallel scan
// of {ts} returns (each row once, at the offset its chunk was handed out at). The build tables {builds_txt} are ordinary loaded column
// structs. q_build makes the agent's QBuild once per stream; workers fold chunks into QAcc states (q_step), states are merged (q_merge)
// and q_finish answers. Proved by Verus: everything below except the two items marked TRUSTED (S1, S2). The host runtime Pool checks at
// run time that the chunks tile [0, n) exactly.

{stream.lib_slice()}

// ---- the query's aggregate as a commutative monoid (host, proved) ----

// The template parameters (an empty struct when the query has none).
#[derive(Clone, Copy)]
pub struct Params {{
{params_struct}
}}

// The group key (key_at's type); `()` for an ungrouped aggregate.
pub type Key = {key};

pub fn params_eq(a: &Params, b: &Params) -> (r: bool)
    ensures
        r == (*a == *b),
{{
    {params_eq}
}}

// Spec-only: one field per suffix fold of the spec, `hits` (pairs of rows of the stream table and the builds in group k that pass the
// WHERE and the ON) and one count per further existence predicate the result mentions.
pub struct Agg {{
{struct_fields}
}}

pub open spec fn agg_zero() -> Agg {{
    Agg {{ {zero} }}
}}

pub open spec fn agg_plus(a: Agg, b: Agg) -> Agg {{
    Agg {{
        {plus}
    }}
}}

pub open spec fn agg_plus_f() -> spec_fn(Agg, Agg) -> Agg {{
    |a: Agg, b: Agg| agg_plus(a, b)
}}

// The contribution of stream row i0 to group k: the fold over the build rows that row i0 meets (the spec's own inner folds); zero
// outside the table.
pub open spec fn agg_row({sh.tp}, i0: int, k: Key, p: &Params) -> Agg {{
    if 0 <= i0 < {tv}.n as int {{
        Agg {{
            {row_in}
        }}
    }} else {{
        agg_zero()
    }}
}}

{extra}

// The fold of agg_row over the stream rows [lo, hi) (0 <= lo <= hi): the spec's suffix folds as differences.
pub open spec fn agg_rng({sh.tp}, lo: int, hi: int, k: Key, p: &Params) -> Agg {{
    Agg {{
        {rng}
    }}
}}

pub proof fn lemma_agg_empty({sh.tp}, lo: int, k: Key, p: &Params)
    requires
        0 <= lo,
    ensures
        agg_rng({sh.ta}, lo, lo, k, p) == agg_zero(),
{{
}}

// One stream row: a range grows by agg_row at its end.
pub proof fn lemma_agg_step({sh.tp}, lo: int, hi: int, k: Key, p: &Params)
    requires
        0 <= lo < hi,
    ensures
        agg_rng({sh.ta}, lo, hi, k, p) == agg_plus(agg_rng({sh.ta}, lo, hi - 1, k, p), agg_row({sh.ta}, hi - 1, k, p)),
{{
    let i0 = hi - 1;
    if i0 < {tv}.n as int {{
{chr(10).join(step_lines)}
    }}
}}

// agg_plus is a commutative monoid with identity agg_zero.
pub proof fn lemma_agg_laws()
    ensures
        monoid_laws(agg_zero(), agg_plus_f()),
        comm_laws(agg_plus_f()),
{{
    assert forall|a: Agg| #[trigger] agg_plus(agg_zero(), a) == a by {{  }}
    assert forall|a: Agg| #[trigger] agg_plus(a, agg_zero()) == a by {{  }}
    assert forall|a: Agg, b: Agg| #[trigger] agg_plus(a, b) == agg_plus(b, a) by {{  }}
    assert forall|a: Agg, b: Agg, c: Agg| #[trigger] agg_plus(agg_plus(a, b), c) == agg_plus(a, agg_plus(b, c)) by {{  }}
}}

// The whole stream table against the builds: what q_finish needs to meet run_query_ok.
pub proof fn lemma_agg_total({sh.tp}, k: Key, p: &Params)
    ensures
{chr(10).join(tot_ens)}
{{
{chr(10).join(tot_body)}
}}

// ---- the stream: ghost table, chunk view, the two trusted items ----

{chunk}

// ---- the agent: build, state, init, step, merge, finish ----

// The agent's types: `pub struct QAcc {{ .. }}` (a worker's state) and `pub struct QBuild {{ .. }}` (made once per stream from the build
// tables, read-only afterwards), and further structs / enums. No references, no lifetimes.
// AGENT_STATE_START
// AGENT_STATE_END

// The agent's helper region (above) defines `spec fn qbuild_inv(bld: &QBuild, {sh.bp}, p: &Params) -> bool`, `spec fn qacc_inv(s: &QAcc,
// bld: &QBuild) -> bool` and `spec fn st_val(s: &QAcc, bld: &QBuild, k: Key) -> Agg` (the value of group k the state stands for).

// Build once per stream from the build tables (a hash or dense table of the build rows). None = decline.
pub fn q_build({sh.bp}, p: &Params) -> (r: Option<QBuild>)
    requires
        {vb},
    ensures
        r matches Some(bld) ==> qbuild_inv(&bld, {sh.ba}, p),
{{
{BUILD_START}
{BUILD_END}
}}

pub fn q_init(bld: &QBuild, {sh.bp}, p: &Params) -> (s: QAcc)
    requires
        {vb},
        qbuild_inv(bld, {sh.ba}, p),
    ensures
        qacc_inv(&s, bld),
        forall|k: Key| #[trigger] st_val(&s, bld, k) == agg_zero(),
{{
{stream.INIT_START}
{stream.INIT_END}
}}

// Fold one chunk of {ts} into the state. false = decline (the query is then declined, never answered wrongly).
pub fn q_step(s: &mut QAcc, c: &Chunk_{ts}, bld: &QBuild, {sh.bp}, p: &Params) -> (ok: bool)
    requires
        qacc_inv(old(s), bld),
        chunk_ok_{ts}(c),
        {vb},
        qbuild_inv(bld, {sh.ba}, p),
    ensures
        ok ==> qacc_inv(final(s), bld) && forall|k: Key| #[trigger] st_val(final(s), bld, k)
            == agg_plus(st_val(old(s), bld, k), agg_rng(&stream_table_{ts}(c.sid), {sh.ba}, c.off as int, c.off + c.len, k, p)),
{{
{stream.STEP_START}
{stream.STEP_END}
}}

// Merge two states of the same stream (any two: their chunks are disjoint). None = decline.
pub fn q_merge(a: QAcc, b: QAcc, bld: &QBuild, {sh.bp}, p: &Params) -> (r: Option<QAcc>)
    requires
        qacc_inv(&a, bld),
        qacc_inv(&b, bld),
        {vb},
        qbuild_inv(bld, {sh.ba}, p),
    ensures
        r matches Some(r) ==> qacc_inv(&r, bld) && forall|k: Key| #[trigger] st_val(&r, bld, k) == agg_plus(st_val(&a, bld, k), st_val(&b, bld, k)),
{{
{stream.MERGE_START}
{stream.MERGE_END}
}}

// Answer from the state of the whole stream table (HAVING, ORDER BY and LIMIT happen here). None = decline.
pub fn q_finish(s: QAcc, t: Ghost<{cols}>, bld: &QBuild, {sh.bp}, p: &Params) -> (res: Option<Vec<OutRow>>)
    requires
        qacc_inv(&s, bld),
        valid_cols_{ts}(&t@),
        {vb},
        qbuild_inv(bld, {sh.ba}, p),
        forall|k: Key| #[trigger] st_val(&s, bld, k) == agg_rng(&t@, {sh.ba}, 0, t@.n as int, k, p),
    ensures
        res matches Some(r) ==> run_query_ok({ok_p}, r),
{{
{stream.FINISH_START}
{stream.FINISH_END}
}}

{_runtime(sh, ok_pl)}"""


def _cols_ok_fn(spec: str, b: str) -> str:
    """A run-time check of ``valid_cols_<b>`` (its length conjuncts and the structural row bound; any other conjunct is refused)."""
    from declarative_spec.assemble import _LEN_CONJ, _valid_cols_conjuncts

    param, conj = _valid_cols_conjuncts(spec, b)
    checks = []
    for c in conj:
        if _LEN_CONJ.match(c):
            m = re.fullmatch(rf"{re.escape(param)}\.((?:r#)?\w+)@\.len\(\) == {re.escape(param)}\.n as int", c)
            if m is None:
                raise _refuse(f"valid_cols_{b} states {c!r}")
            checks.append(f"x.{m.group(1)}.len() == x.n")
        elif c == f"{param}.n as int <= 0x7fff_ffff_ffff_ffffint":
            checks.append("(x.n as u64) <= 0x7fff_ffff_ffff_ffffu64")
        else:
            raise _refuse(f"valid_cols_{b} states {c!r}: a build table is checked at run time; only lengths and the row bound are stated")
    return f"""// The build table's well-formedness, checked at run time (the glue hands the loaded columns; nothing is assumed of them).
pub fn cols_ok_{b}(x: &Cols_{b}) -> (r: bool)
    ensures
        r ==> valid_cols_{b}(x),
{{
    {' && '.join(checks) or 'true'}
}}"""


def _runtime(sh: JoinShape, ok_pl: str) -> str:
    ts = sh.ts
    vb = list(zip(sh.bvars, sh.builds, strict=True))  # (variable / field name b_<suffix>, suffix)
    bg = ", ".join(f"{v}: Cols_{b}" for v, b in vb)  # ghost / by value
    br = ", ".join(f"&{v}" for v, _b in vb)  # spec references to by-value ghosts
    pred_fields = "\n".join(f"    pub {v}: Cols_{b}," for v, b in vb)
    pool_fields = "\n".join(f"    {v}: Cols_{b}," for v, b in vb)
    self_br = ", ".join(f"&self.{v}" for v, _b in vb)
    pred_of = lambda pre: "(SlotPred { id: " + pre + "sh.id, " + ", ".join(f"{v}: {pre}{v}" for v, _b in vb) + f", bld: {pre}bld, p: {pre}p }})"  # noqa: E731
    b_names = ", ".join(sh.bvars)
    pl_b = ", ".join(f"pl.{v}" for v, _b in vb)
    pl_br = ", ".join(f"&pl.{v}" for v, _b in vb)
    getters = "\n\n".join(f"    pub closed spec fn build_{b}(self) -> Cols_{b} {{\n        self.{v}\n    }}" for v, b in vb)
    wf_b = "\n".join(f"        &&& valid_cols_{b}(&self.{v})" for v, b in vb)
    ens_b = " && ".join(f"pl.build_{b}() == {v}" for v, b in vb)
    ok_checks = " || ".join(f"!cols_ok_{b}(&{v})" for v, b in vb)
    inv_b = "\n".join(f"            valid_cols_{b}(&{v})," for v, b in vb)
    self_bs = ", ".join(f"self.{v}" for v, _b in vb)
    return f"""// ---- the host runtime of a join (fixed, verified) ----

pub open spec fn seg_agg(id: u64, {bg}, k: Key, p: Params) -> spec_fn(Seg) -> Agg {{
    |s: Seg| agg_rng(&stream_table_{ts}(id), {br}, s.off as int, seg_end(s), k, &p)
}}

pub open spec fn seg_fold(id: u64, {bg}, segs: Seq<Seg>, k: Key, p: Params) -> Agg {{
    fold_by(segs, seg_agg(id, {b_names}, k, p), agg_zero(), agg_plus_f())
}}

// Segments that are a reordering (pa, pb) of chunks that tile the ghost table fold to the whole table.
pub proof fn lemma_stream_total(id: u64, {bg}, segs: Seq<Seg>, tiles: Seq<Seg>, pa: Seq<int>, pb: Seq<int>, k: Key, p: Params)
    requires
        segs.len() == tiles.len(),
        pa.len() == segs.len(),
        pb.len() == tiles.len(),
        forall|i: int| #![trigger pa[i]] 0 <= i < segs.len() ==> 0 <= pa[i] < tiles.len() && pb[pa[i]] == i && segs[i] == tiles[pa[i]],
        forall|j: int| #![trigger pb[j]] 0 <= j < tiles.len() ==> 0 <= pb[j] < segs.len() && pa[pb[j]] == j,
        tiles_ok(tiles, stream_table_{ts}(id).n as int),
    ensures
        seg_fold(id, {b_names}, segs, k, p) == agg_rng(&stream_table_{ts}(id), {br}, 0, stream_table_{ts}(id).n as int, k, &p),
{{
    lemma_agg_laws();
    let t = stream_table_{ts}(id);
    let rng = |lo: int, hi: int| agg_rng(&t, {br}, lo, hi, k, &p);
    let row = |i: int| agg_row(&t, {br}, i, k, &p);
    assert forall|lo: int| 0 <= lo implies #[trigger] rng(lo, lo) == agg_zero() by {{
        lemma_agg_empty(&t, {br}, lo, k, &p);
    }}
    assert forall|lo: int, hi: int| 0 <= lo < hi implies #[trigger] rng(lo, hi) == (agg_plus_f())(rng(lo, hi - 1), row(hi - 1)) by {{
        lemma_agg_step(&t, {br}, lo, hi, k, &p);
    }}
    assert(rng_step_ok(rng, row, agg_zero(), agg_plus_f()));
    assert forall|s: Seg| #[trigger] (seg_agg(id, {b_names}, k, p))(s) == rng(s.off as int, seg_end(s)) by {{}}
    lemma_fold_bij(segs, tiles, pa, pb, seg_agg(id, {b_names}, k, p), agg_zero(), agg_plus_f());
    lemma_tiles(tiles, t.n as int, seg_agg(id, {b_names}, k, p), rng, row, agg_zero(), agg_plus_f());
}}

// The outcome of a stream: the rows, a decline by the agent's code, or an error of the glue or the scheduling (never rows).
pub enum StreamOut {{
    Rows(Vec<OutRow>),
    Declined,
    Error,
}}

// One worker's slot: its state (None = poisoned: declined, or S1 refused a chunk) and the segments of the chunks it has stepped.
pub struct Slot {{
    pub acc: Option<QAcc>,
    pub err: bool,
    pub segs: Vec<Seg>,
}}

// What every slot of one pool keeps true (the lock's predicate): the state is the fold of its segments against the pool's build.
pub struct SlotPred {{
    pub id: u64,
{pred_fields}
    pub bld: QBuild,
    pub p: Params,
}}

impl vstd::rwlock::RwLockPredicate<Slot> for SlotPred {{
    open spec fn inv(self, s: Slot) -> bool {{
        s.acc matches Some(a) ==> qacc_inv(&a, &self.bld) && forall|k: Key| #[trigger] st_val(&a, &self.bld, k)
            == seg_fold(self.id, {self_bs}, s.segs@, k, self.p)
    }}
}}

// One stream's executor: the build tables, the agent's QBuild (made once by q_build) and one locked slot per worker. Workers step
// their own slot (pool_step); pool_finish merges the slots. The type invariant: every slot's predicate names this pool's build.
pub struct Pool {{
    sh: Stream_{ts},
    p: Params,
{pool_fields}
    bld: QBuild,
    slots: Vec<vstd::rwlock::RwLock<Slot, SlotPred>>,
}}

impl Pool {{
    #[verifier::type_invariant]
    spec fn wf(self) -> bool {{
{wf_b}
        &&& qbuild_inv(&self.bld, {self_br}, &self.p)
        &&& forall|w: int| 0 <= w < self.slots@.len() ==> (#[trigger] self.slots@[w]).pred() == {pred_of('self.')}
    }}

    pub closed spec fn sid(self) -> u64 {{
        self.sh.id
    }}

    pub closed spec fn params(self) -> Params {{
        self.p
    }}

{getters}

    pub closed spec fn nslots(self) -> nat {{
        self.slots@.len()
    }}
}}

pub enum PoolOpen {{
    Ready(Pool),
    Declined,
    Error,
}}

{chr(10).join(_cols_ok_fn(_SPEC.get(), b) for b in sh.builds)}

// Open a stream's executor over the loaded build tables with `nslots` worker slots: q_build once, q_init per slot. Error: a build
// table is not well formed (lengths, row bound).
pub fn pool_open(sh: Stream_{ts}, {bg}, p: Params, nslots: usize) -> (r: PoolOpen)
    ensures
        r matches PoolOpen::Ready(pl) ==> pl.sid() == sh.id && pl.params() == p && {ens_b} && pl.nslots() == nslots,
{{
    if {ok_checks} {{
        return PoolOpen::Error;
    }}
    let bld = match q_build({br}, &p) {{
        Some(x) => x,
        None => {{
            return PoolOpen::Declined;
        }}
    }};
    let ghost pred = {pred_of('')};
    let mut slots: Vec<vstd::rwlock::RwLock<Slot, SlotPred>> = Vec::new();
    let mut w: usize = 0;
    while w < nslots
        invariant
            w <= nslots,
            slots@.len() == w,
{inv_b}
            qbuild_inv(&bld, {br}, &p),
            pred == {pred_of('')},
            forall|i: int| 0 <= i < slots@.len() ==> (#[trigger] slots@[i]).pred() == pred,
        decreases nslots - w,
    {{
        let a = q_init(&bld, {br}, &p);
        let segs: Vec<Seg> = Vec::new();
        proof {{
            assert forall|k: Key| #[trigger] st_val(&a, &bld, k) == seg_fold(sh.id, {b_names}, segs@, k, p) by {{}}
        }}
        let sl = Slot {{ acc: Some(a), err: false, segs }};
        slots.push(vstd::rwlock::RwLock::new(sl, Ghost(pred)));
        w = w + 1;
    }}
    PoolOpen::Ready(Pool {{ sh, p, {b_names}, bld, slots }})
}}

// Worker w folds one chunk into its slot: 0 go on, 1 poisoned (declined, or S1 refused the chunk: the answer is then a decline or an
// error; stop handing chunks), 2 there is no slot w (a glue error).
pub fn pool_step(pl: &Pool, w: usize, raw: &RawChunk_{ts}) -> (r: u8) {{
    proof {{
        use_type_invariant(pl);
    }}
    if w >= pl.slots.len() {{
        return 2;
    }}
    let (sl, h) = pl.slots[w].acquire_write();
    let Slot {{ acc, err, mut segs }} = sl;
    match acc {{
        None => {{
            h.release_write(Slot {{ acc: None, err, segs }});
            1
        }},
        Some(a0) => {{
            let mut a = a0;
            match chunk_{ts}(&pl.sh, raw) {{
                None => {{
                    h.release_write(Slot {{ acc: None, err: true, segs }});
                    1
                }},
                Some(c) => {{
                    let ghost old_segs = segs@;
                    if q_step(&mut a, &c, &pl.bld, {pl_br}, &pl.p) {{
                        let s = Seg {{ j: raw.j as usize, off: c.off, len: c.len }};
                        segs.push(s);
                        proof {{
                            assert forall|k: Key| #[trigger] st_val(&a, &pl.bld, k) == seg_fold(pl.sh.id, {pl_b}, segs@, k, pl.p) by {{
                                lemma_fold_push(old_segs, s, seg_agg(pl.sh.id, {pl_b}, k, pl.p), agg_zero(), agg_plus_f());
                                assert(segs@ == old_segs.push(s));
                            }}
                        }}
                        h.release_write(Slot {{ acc: Some(a), err, segs }});
                        0
                    }} else {{
                        h.release_write(Slot {{ acc: None, err, segs }});
                        1
                    }}
                }},
            }}
        }},
    }}
}}

// Rows only when the stepped chunks of all slots tile [0, n) exactly: each chunk index below m once, offsets contiguous from 0 to n.
pub fn pool_finish(pl: Pool) -> (r: StreamOut)
    ensures
        r matches StreamOut::Rows(res) ==> run_query_ok({ok_pl}, res),
{{
    proof {{
        use_type_invariant(&pl);
    }}
    let Pool {{ sh, p, {b_names}, bld, slots }} = pl;
    let ghost pred = {pred_of('')};
    let mut slots = slots;
    if slots.len() == 0 {{
        return StreamOut::Error;
    }}
    let first = slots.pop().unwrap();
    let Slot {{ acc: mut cur, err: mut err, mut segs }} = first.into_inner();
    while slots.len() > 0
        invariant
            forall|i: int| 0 <= i < slots@.len() ==> (#[trigger] slots@[i]).pred() == pred,
            pred == {pred_of('')},
{inv_b}
            qbuild_inv(&bld, {br}, &p),
            cur matches Some(a) ==> qacc_inv(&a, &bld) && forall|k: Key| #[trigger] st_val(&a, &bld, k) == seg_fold(sh.id, {b_names}, segs@, k, p),
        decreases slots@.len(),
    {{
        let l = slots.pop().unwrap();
        let Slot {{ acc: acc_b, err: err_b, segs: mut segs_b }} = l.into_inner();
        err = err || err_b;
        cur = match cur {{
            Some(x) => match acc_b {{
                Some(y) => {{
                    let ghost sa = segs@;
                    let ghost sb = segs_b@;
                    let ghost gx = x;
                    let ghost gy = y;
                    match q_merge(x, y, &bld, {br}, &p) {{
                        Some(mm) => {{
                            segs.append(&mut segs_b);
                            proof {{
                                lemma_agg_laws();
                                assert forall|k: Key| #[trigger] st_val(&mm, &bld, k) == seg_fold(sh.id, {b_names}, segs@, k, p) by {{
                                    assert(st_val(&gx, &bld, k) == seg_fold(sh.id, {b_names}, sa, k, p));
                                    assert(st_val(&gy, &bld, k) == seg_fold(sh.id, {b_names}, sb, k, p));
                                    lemma_fold_concat(sa, sb, seg_agg(sh.id, {b_names}, k, p), agg_zero(), agg_plus_f());
                                }}
                            }}
                            Some(mm)
                        }},
                        None => None,
                    }}
                }},
                None => None,
            }},
            None => None,
        }};
    }}
    let a = match cur {{
        Some(a) => a,
        None => {{
            return if err {{ StreamOut::Error }} else {{ StreamOut::Declined }};
        }},
    }};
    let (m, n) = stream_end_{ts}(&sh);
    let ghost t = stream_table_{ts}(sh.id);
    if segs.len() != m {{
        return StreamOut::Error;
    }}
    let mut filled: Vec<bool> = Vec::new();
    let mut soff: Vec<usize> = Vec::new();
    let mut slen: Vec<usize> = Vec::new();
    let mut j: usize = 0;
    while j < m
        invariant
            j <= m,
            filled@.len() == j,
            soff@.len() == j,
            slen@.len() == j,
            forall|x: int| 0 <= x < j ==> !(#[trigger] filled@[x]),
        decreases m - j,
    {{
        filled.push(false);
        soff.push(0);
        slen.push(0);
        j = j + 1;
    }}
    let ghost mut pos: Seq<int> = Seq::new(m as nat, |x: int| 0int);
    let mut i: usize = 0;
    while i < segs.len()
        invariant
            segs@.len() == m,
            filled@.len() == m,
            soff@.len() == m,
            slen@.len() == m,
            pos.len() == m,
            i <= m,
            forall|i2: int| #![trigger segs@[i2]] 0 <= i2 < i ==> (segs@[i2].j as int) < m && filled@[segs@[i2].j as int]
                && pos[segs@[i2].j as int] == i2 && soff@[segs@[i2].j as int] == segs@[i2].off && slen@[segs@[i2].j as int] == segs@[i2].len,
            forall|x: int| #![trigger filled@[x]] 0 <= x < m && filled@[x] ==> 0 <= pos[x] < i && segs@[pos[x]].j == x,
        decreases segs@.len() - i,
    {{
        let s = segs[i];
        if s.j >= m || filled[s.j] {{
            return StreamOut::Error;
        }}
        filled.set(s.j, true);
        soff.set(s.j, s.off);
        slen.set(s.j, s.len);
        proof {{
            pos = pos.update(s.j as int, i as int);
        }}
        i = i + 1;
    }}
    let mut o: usize = 0;
    let mut j: usize = 0;
    while j < m
        invariant
            segs@.len() == m,
            filled@.len() == m,
            soff@.len() == m,
            slen@.len() == m,
            j <= m,
            o <= n,
            forall|x: int| 0 <= x < j ==> #[trigger] filled@[x],
            j == 0 ==> o == 0,
            j > 0 ==> o == soff@[j - 1] + slen@[j - 1] && soff@[0] == 0,
            forall|x: int| #![trigger soff@[x]] 0 < x < j ==> soff@[x] == soff@[x - 1] + slen@[x - 1],
        decreases m - j,
    {{
        if !filled[j] || soff[j] != o || slen[j] > n - o {{
            return StreamOut::Error;
        }}
        o = o + slen[j];
        j = j + 1;
    }}
    if o != n {{
        return StreamOut::Error;
    }}
    proof {{
        let tiles = Seq::new(m as nat, |x: int| Seg {{ j: x as usize, off: soff@[x], len: slen@[x] }});
        let pa = Seq::new(m as nat, |i2: int| segs@[i2].j as int);
        assert forall|i2: int| #![trigger pa[i2]] 0 <= i2 < segs@.len() implies 0 <= pa[i2] < tiles.len() && pos[pa[i2]] == i2
            && segs@[i2] == tiles[pa[i2]] by {{
            assert(segs@[i2].j as int == pa[i2]);
        }}
        assert forall|x: int| #![trigger pos[x]] 0 <= x < tiles.len() implies 0 <= pos[x] < segs@.len() && pa[pos[x]] == x by {{
            assert(filled@[x]);
        }}
        assert forall|x: int| #![trigger tiles[x]] 0 <= x && x + 1 < tiles.len() implies tiles[x + 1].off == seg_end(tiles[x]) by {{
            assert(soff@[x + 1] == soff@[x] + slen@[x]);
        }}
        assert(tiles_ok(tiles, t.n as int));
        assert forall|k: Key| #[trigger] st_val(&a, &bld, k) == agg_rng(&t, {br}, 0, t.n as int, k, &p) by {{
            lemma_stream_total(sh.id, {b_names}, segs@, tiles, pa, pos, k, p);
        }}
    }}
    match q_finish(a, Ghost(t), &bld, {br}, &p) {{
        Some(res) => StreamOut::Rows(res),
        None => StreamOut::Declined,
    }}
}}
"""


_SPEC: contextvars.ContextVar[str] = contextvars.ContextVar("lemma_stream_join_spec", default="")


def to_stream_join(spec: str) -> str:
    """Replace run_query of an emitted join spec by the join stream contract (refuse every other shape loudly)."""
    from declarative_spec import stream

    shape = read_join_shape(spec)
    m = stream._RUN_QUERY.search(spec)
    assert m is not None
    token = _SPEC.set(spec)
    try:
        block = emit_join_contract(shape)
    finally:
        _SPEC.reset(token)
    return spec[: m.start()] + block + spec[m.end() :]


def stub(spec_rs: str) -> dict[str, str]:
    """The stub regions the host scaffold verifies with (q_build None, q_step false, q_merge / q_finish None)."""
    m = re.search(r"pub fn q_build\((.*?), p: &Params\) -> ", spec_rs)
    assert m is not None
    return {k: v.replace("@@BUILD_PARAMS@@", m.group(1)) for k, v in STUB.items()}
