"""Streaming executors: ``COUNT(DISTINCT x)`` as a set-valued field of the stream monoid (docs/STREAM.md "COUNT DISTINCT and NULL keys").

The spec states ``COUNT(DISTINCT x)`` as a fold that counts a row (a tuple of rows over a join) only when no LATER row (tuple, in
lexicographic order) of the same group has the same value. That count is not a difference of suffix folds over a chunk's range, so the
stream ``Agg`` carries the SET of the group's values instead: ``set_<fold>: Set<V>``, ``agg_zero`` the empty set, ``agg_plus`` the union,
``agg_row`` the values of the row (phase 1: a singleton or empty; a join: the values of the row's matching build tuples), ``agg_rng`` a
range fold of unions. ``q_finish`` takes the size. Everything here is host text, proved by Verus with the spec (nothing trusted):

* ``set_<fold>_d<e>(tables, i0..ie, k, p)``: the values of the hit tuples whose first ``e`` indices are ``i0..i(e-1)`` and whose index
  ``e`` is at least ``ie`` (a suffix fold of unions over level ``e``; level 0 is the stream table, level ``m`` the last build table);
* ``lemma_set_<fold>_d<e>_mem``: membership in that set is "some such hit tuple has the value";
* ``lemma_set_<fold>_d<e>_count``: the spec's own count fold at level ``e`` is the size of that set minus the values of the tuples
  after the block (``out``), by induction over the nesting (the last-occurrence count is the number of distinct values);
* ``stream_set_<fold>`` (the range fold) with ``lemma_stream_set_<fold>``: the range ``[lo, hi)`` united with the suffix at ``hi`` is the
  suffix at ``lo``; ``lemma_agg_total`` then states ``agg_rng(.., 0, n, ..).set_<fold>.len() == <fold>(.., 0, ..)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from declarative_spec.parse import DeclarativeUnsupported


def _refuse(why: str) -> DeclarativeUnsupported:
    return DeclarativeUnsupported(f"stream (lemma.toml [run] stream): {why}")


@dataclass
class Distinct:
    """One ``COUNT(DISTINCT x)`` fold of the spec, in the stream contract's names."""

    name: str  # the spec's (outermost) fold, e.g. `count_distinct_d`
    pred: str  # the per-tuple predicate the spec counts: `row_hit` or `hit_<x>` (x not NULL)
    pred_args: list[str]  # its arguments after the tables and indices
    keyed: bool  # grouped: `&& key_at(..) == k`
    valfn: str  # the value function `<name>_val`
    vtype: str  # its type (`int`, `Seq<char>`, ..)
    args: list[str]  # the fold's arguments after the indices (`k`, `p.<param>`)
    levels: int  # m: the number of build tables (0: one table)
    tabs: list[str] = field(default_factory=list)  # the contract's table variables (stream table first)
    types: list[str] = field(default_factory=list)  # their suffixes

    @property
    def field(self) -> str:
        return f"set_{self.name}"

    @property
    def idx(self) -> list[str]:
        return [f"i{e}" for e in range(self.levels + 1)]


def _lex(j: list[str], i: list[str], upto: int) -> str:
    """``j`` after ``i`` in lexicographic order on the first ``upto`` components, in the emitter's text (``false`` for none)."""
    if upto == 0:
        return "false"
    parts = []
    for d in range(upto):
        parts.append("(" + " && ".join([f"{j[e]} == {i[e]}" for e in range(d)] + [f"{j[d]} > {i[d]}"]) + ")")
    return "(" + " || ".join(parts) + ")"


def parse_term(cond: str, val: str, pv: list[str], idx: list[str], spec: str, sub) -> tuple[str, list[str], bool, str, str] | None:
    """The innermost term of a COUNT DISTINCT fold, ``(if BASE(i) && !(exists|j| LEX(j, i) && BASE(j) && V(j) == V(i)) { 1int } ..``,
    as ``(pred, pred_args, keyed, valfn, vtype)``; None when the term is not of that form (exactly the emitter's text)."""
    cut = cond.find(" && !(exists|")
    if val != "1int" or cut < 0:
        return None
    tab = ", ".join(pv)
    m = re.fullmatch(rf"(\w+)\({re.escape(tab)}, {re.escape(', '.join(idx))}((?:, [\w.]+)*)\)( && key_at\({re.escape(tab)}, {re.escape(', '.join(idx))}\) == k)?", cond[:cut])
    vm = re.search(r" && (\w+)\([^()]*\) == \1\([^()]*\)\)$", cond)
    if m is None or vm is None:
        return None
    pred, pargs, keyed, valfn = m.group(1), [a.strip() for a in m.group(2).split(",") if a.strip()], bool(m.group(3)), vm.group(1)
    jdx = [f"j{e}" for e in range(len(idx))]

    def base(ix: list[str]) -> str:
        b = f"{pred}({', '.join([*pv, *ix, *pargs])})"
        return b + (f" && key_at({', '.join([*pv, *ix])}) == k" if keyed else "")

    want = (
        f"{base(idx)} && !(exists|{', '.join(f'{j}: int' for j in jdx)}| {_lex(jdx, idx, len(idx))} && {base(jdx)} && "
        f"{valfn}({', '.join([*pv, *jdx])}) == {valfn}({', '.join([*pv, *idx])}))"
    )
    if cond != want:
        return None
    ty = re.search(rf"pub open spec fn {re.escape(valfn)}\([^\n]*\) -> ([^\n]+?) \{{\n", spec)
    if ty is None:
        raise _refuse(f"COUNT DISTINCT {valfn}: no value function")
    return pred, [sub(a) for a in pargs], keyed, valfn, ty.group(1)


# ---- emission (stream contract names: tables `tabs`, indices i0..im, `k: Key`, `p: &Params`) ----------------------------------------


def _c(name: str, *parts: str) -> str:
    return f"{name}({', '.join(p for p in parts if p)})"


def _fns(d: Distinct) -> tuple[str, str, str]:
    tp = ", ".join(f"{v}: &Cols_{s}" for v, s in zip(d.tabs, d.types, strict=True))
    return tp, ", ".join(d.tabs), f"Set::<{d.vtype}>::empty()"


def base(d: Distinct, ix: list[str]) -> str:
    ta = ", ".join(d.tabs)
    b = _c(d.pred, ta, *ix, *d.pred_args)
    return b + (f" && {_c('key_at', ta, *ix)} == k" if d.keyed else "")


def _trig(d: Distinct, ix: list[str]) -> str:
    return _c(d.pred, ", ".join(d.tabs), *ix, *d.pred_args)


def _val(d: Distinct, ix: list[str]) -> str:
    return _c(d.valfn, ", ".join(d.tabs), *ix)


def term(d: Distinct, e: int, ix: list[str]) -> str:
    """Level e's term at the indices ``ix`` (``e + 1`` of them): a singleton or empty at the last level, else the next level's set."""
    _tp, ta, empty = _fns(d)
    if e == d.levels:
        return f"(if {base(d, ix)} {{ {empty}.insert({_val(d, ix)}) }} else {{ {empty} }})"
    return _c(f"{d.field}_d{e + 1}", ta, *ix, "0", "k", "p")


def count(d: Distinct, e: int, ix: list[str]) -> str:
    """The spec's own count fold at level e."""
    name = d.name if e == 0 else f"{d.name}_d{e}"
    return _c(name, ", ".join(d.tabs), *ix, *d.args)


def row_expr(d: Distinct) -> str:
    """agg_row's field at stream row i0 (inside the table)."""
    return term(d, 0, ["i0"])


def _ex(d: Distinct, e: int, lo: str) -> tuple[str, list[str]]:
    """``exists|je..jm| lo <= je && BASE(i0..i(e-1), je..jm) && V(..) == v`` and the bound variables."""
    js = [f"j{x}" for x in range(e, d.levels + 1)]
    ix = [*d.idx[:e], *js]
    vs = ", ".join(f"{j}: int" for j in js)
    return f"(exists|{vs}| #![trigger {_trig(d, ix)}] {lo} <= j{e} && {base(d, ix)} && {_val(d, ix)} == v)", js


def _out(d: Distinct, upto: int) -> str:
    """``exists|j0..jm| LEX_upto(j, i) && BASE(j) && V(j) == v``: the values of the tuples after the block of i0..i(upto-1)."""
    js = [f"j{x}" for x in range(d.levels + 1)]
    vs = ", ".join(f"{j}: int" for j in js)
    return f"(exists|{vs}| #![trigger {_trig(d, js)}] {_lex(js, d.idx, upto)} && {base(d, js)} && {_val(d, js)} == v)"


def _tuple(js: list[str]) -> str:
    return js[0] if len(js) == 1 else "(" + ", ".join(js) + ")"


def _choose(js: list[str], body: str, trig: str) -> str:
    vs = ", ".join(f"{j}: int" for j in js)
    return f"let {_tuple(js)} = choose|{vs}| #![trigger {trig}] {body};"


def emit_fns(d: Distinct) -> list[str]:
    """The set folds, their membership and count lemmas, the range fold and its lemma (all host, proved)."""
    tp, ta, empty = _fns(d)
    vt = d.vtype
    out: list[str] = []
    m = d.levels
    for e in range(m, -1, -1):
        te = d.tabs[e]
        ie = d.idx[e]
        head = d.idx[:e]
        ip = ", ".join(f"{i}: int" for i in d.idx[: e + 1])
        me = _c(f"{d.field}_d{e}", ta, *d.idx[: e + 1], "k", "p")
        nxt = _c(f"{d.field}_d{e}", ta, *head, f"{ie} + 1", "k", "p")
        out.append(f"""pub open spec fn {d.field}_d{e}({tp}, {ip}, k: Key, p: &Params) -> Set<{vt}>
    decreases {te}.n as int - {ie},
{{
    if {ie} < 0 || {ie} >= {te}.n as int {{
        {empty}
    }} else {{
        {term(d, e, d.idx[: e + 1])}.union({nxt})
    }}
}}""")
        # membership
        ex, js = _ex(d, e, ie)
        ix_j = [*head, *js]
        trig_j = _trig(d, ix_j)
        if e == m:
            here = f"assert({base(d, d.idx[: e + 1])} && {_val(d, d.idx[: e + 1])} == v);"
            at_ie = f"assert({term(d, e, d.idx[: e + 1])}.contains(v));"
            inner_lemma = ""
        else:
            _ex_in, js_in = _ex(d, e + 1, "0")
            ix_in = [*d.idx[: e + 1], *js_in]
            here = (
                _choose(js_in, f"0 <= j{e + 1} && {base(d, ix_in)} && {_val(d, ix_in)} == v", _trig(d, ix_in))
                + f"\n                    assert({base(d, ix_in)} && {_val(d, ix_in)} == v);"
            )
            ix_eq = [*d.idx[: e + 1], *js[1:]]
            at_ie = (
                f"assert(0 <= j{e + 1} && {base(d, ix_eq)} && {_val(d, ix_eq)} == v);\n"
                f"                    assert({term(d, e, d.idx[: e + 1])}.contains(v));"
            )
            inner_lemma = f"\n        lemma_{d.field}_d{e + 1}_mem({ta}, {', '.join(d.idx[: e + 1])}, 0, k, p);"
        out.append(f"""pub proof fn lemma_{d.field}_d{e}_mem({tp}, {ip}, k: Key, p: &Params)
    requires
        0 <= {ie},
    ensures
        forall|v: {vt}| #[trigger] {me}.contains(v) <==> {ex},
    decreases {te}.n as int - {ie},
{{
    if {ie} < {te}.n as int {{
        lemma_{d.field}_d{e}_mem({ta}, {', '.join([*head, f'{ie} + 1'])}, k, p);{inner_lemma}
        assert forall|v: {vt}| #[trigger] {me}.contains(v) <==> {ex} by {{
            if {me}.contains(v) {{
                if {term(d, e, d.idx[: e + 1])}.contains(v) {{
                    {here}
                }} else {{
                    assert({nxt}.contains(v));
                    {_choose(js, f"{ie} + 1 <= j{e} && {base(d, ix_j)} && {_val(d, ix_j)} == v", trig_j)}
                    assert({ie} <= j{e} && {base(d, ix_j)} && {_val(d, ix_j)} == v);
                }}
            }}
            if {ex} {{
                {_choose(js, f"{ie} <= j{e} && {base(d, ix_j)} && {_val(d, ix_j)} == v", trig_j)}
                if j{e} == {ie} {{
                    {at_ie}
                }} else {{
                    assert({ie} + 1 <= j{e} && {base(d, ix_j)} && {_val(d, ix_j)} == v);
                    assert({nxt}.contains(v));
                }}
            }}
        }}
    }} else {{
        assert forall|v: {vt}| #[trigger] {me}.contains(v) <==> {ex} by {{
            if {ex} {{
                {_choose(js, f"{ie} <= j{e} && {base(d, ix_j)} && {_val(d, ix_j)} == v", trig_j)}
                assert({trig_j});
            }}
        }}
    }}
}}""")
        # count: the spec's last-occurrence fold at level e is the size of the set minus the values after the block
        allj = [f"j{x}" for x in range(m + 1)]
        out_e = _out(d, e)
        out_n = _out(d, e + 1)
        a = term(d, e, d.idx[: e + 1])
        b = nxt
        lex_e = _lex(allj, d.idx, e)
        tail = [*head, *[f"j{x}" for x in range(e, m + 1)]]
        bridge = f"""        assert forall|v: {vt}| #[trigger] out2.contains(v) <==> {out_n} by {{
            if out2.contains(v) {{
                if out.contains(v) {{
                    {_choose(allj, f"{lex_e} && {base(d, allj)} && {_val(d, allj)} == v", _trig(d, allj))}
                    assert({_lex(allj, d.idx, e + 1)} && {base(d, allj)} && {_val(d, allj)} == v);
                }} else {{
                    {_choose(js, f"{ie} + 1 <= j{e} && {base(d, ix_j)} && {_val(d, ix_j)} == v", trig_j)}
                    {"let " + _tuple(allj[:e]) + " = " + _tuple(head) + ";" if e > 0 else ""}
                    assert({_lex(allj, d.idx, e + 1)} && {base(d, allj)} && {_val(d, allj)} == v);
                }}
            }}
            if {out_n} {{
                {_choose(allj, f"{_lex(allj, d.idx, e + 1)} && {base(d, allj)} && {_val(d, allj)} == v", _trig(d, allj))}
                if {lex_e} {{
                    assert({lex_e} && {base(d, allj)} && {_val(d, allj)} == v);
                    assert(out.contains(v));
                }} else {{
                    assert({base(d, tail)} && {_val(d, tail)} == v);
                    assert({ie} + 1 <= j{e} && {base(d, tail)} && {_val(d, tail)} == v);
                    assert(b.contains(v));
                }}
            }}
        }}"""
        if e < m:
            mid = f"""{bridge}
        lemma_{d.field}_d{e + 1}_count({ta}, {', '.join(d.idx[: e + 1])}, 0, k, p, out2);"""
        else:
            ii = d.idx[: e + 1]
            mid = f"""{bridge}
        let x = {_val(d, ii)};
        if {base(d, ii)} && !out2.contains(x) {{
            assert(a.difference(out2) =~= {empty}.insert(x));
        }} else {{
            assert(a.difference(out2) =~= {empty});
        }}"""
        out.append(f"""pub proof fn lemma_{d.field}_d{e}_count({tp}, {ip}, k: Key, p: &Params, out: Set<{vt}>)
    requires
        0 <= {ie} <= {te}.n as int,
        forall|v: {vt}| #[trigger] out.contains(v) <==> {out_e},
    ensures
        {count(d, e, d.idx[: e + 1])} == {me}.difference(out).len(),
    decreases {te}.n as int - {ie},
{{
    if {ie} < {te}.n as int {{
        let a = {a};
        let b = {b};
        lemma_{d.field}_d{e}_count({ta}, {', '.join([*head, f'{ie} + 1'])}, k, p, out);
        lemma_{d.field}_d{e}_mem({ta}, {', '.join([*head, f'{ie} + 1'])}, k, p);
        let out2 = out.union(b);
{mid}
        assert({me}.difference(out) =~= a.difference(out2).union(b.difference(out)));
        lemma_set_disjoint_lens(a.difference(out2), b.difference(out));
    }} else {{
        assert({me}.difference(out) =~= {empty});
    }}
}}""")
    # the range fold over stream rows and its relation to the suffix at level 0
    t0 = d.tabs[0]
    rs = lambda lo, hi: _c(f"stream_{d.field}", ta, lo, hi, "k", "p")
    s0 = lambda i: _c(f"{d.field}_d0", ta, i, "k", "p")
    out.append(f"""pub open spec fn stream_{d.field}({tp}, lo: int, hi: int, k: Key, p: &Params) -> Set<{vt}>
    decreases hi - lo,
{{
    if hi <= lo {{
        {empty}
    }} else {{
        {rs('lo', 'hi - 1')}.union(agg_row({ta}, hi - 1, k, p).{d.field})
    }}
}}""")
    out.append(f"""pub proof fn lemma_stream_{d.field}({tp}, lo: int, hi: int, k: Key, p: &Params)
    requires
        0 <= lo <= hi,
    ensures
        {rs('lo', 'hi')}.union({s0('hi')}) == {s0('lo')},
    decreases hi - lo,
{{
    if hi > lo {{
        lemma_stream_{d.field}({ta}, lo, hi - 1, k, p);
        assert({rs('lo', 'hi')}.union({s0('hi')}) =~= {rs('lo', 'hi - 1')}.union({s0('hi - 1')}));
    }} else {{
        assert({rs('lo', 'hi')}.union({s0('hi')}) =~= {s0('lo')});
    }}
}}""")
    del t0
    return out


def total(d: Distinct, rng_at: str) -> tuple[list[str], str]:
    """lemma_agg_total's ensures and body for the set field (``rng_at``: ``agg_rng(<tables>, 0, <t>.n as int, k, p)``)."""
    tp, ta, empty = _fns(d)
    del tp
    t0 = d.tabs[0]
    ens = [f"        {rng_at}.{d.field}.len() == {count(d, 0, ['0'])},"]
    body = f"""    lemma_stream_{d.field}({ta}, 0, {t0}.n as int, k, p);
    assert({_c(f'{d.field}_d0', ta, f'{t0}.n as int', 'k', 'p')} =~= {empty});
    assert forall|v: {d.vtype}| #[trigger] {empty}.contains(v) <==> {_out(d, 0)} by {{}}
    lemma_{d.field}_d0_count({ta}, 0, k, p, {empty});
    assert({_c(f'{d.field}_d0', ta, '0', 'k', 'p')}.difference({empty}) =~= {_c(f'{d.field}_d0', ta, '0', 'k', 'p')});
    assert({rng_at}.{d.field} =~= {_c(f'{d.field}_d0', ta, '0', 'k', 'p')});"""
    return ens, body


def laws(fields: list[str], law: str) -> str:
    """The set fields' extensional equalities for one monoid law (``left`` / ``right`` / ``comm`` / ``assoc``); "" without one."""
    pairs = {
        "left": ("agg_plus(agg_zero(), a)", "a"),
        "right": ("agg_plus(a, agg_zero())", "a"),
        "comm": ("agg_plus(a, b)", "agg_plus(b, a)"),
        "assoc": ("agg_plus(agg_plus(a, b), c)", "agg_plus(a, agg_plus(b, c))"),
    }
    lhs, rhs = pairs[law]
    return " ".join(f"assert({lhs}.{f} =~= {rhs}.{f});" for f in fields)
