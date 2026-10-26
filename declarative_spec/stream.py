"""Streaming executors (lemma.toml ``[run] stream``, docs/STREAM.md): the spec side of phase 1.

The emitter states the query exactly as before (``run_query_ok`` is unchanged); :func:`to_stream` then replaces ``run_query`` by the
stream contract over ONE ghost table ``T = stream_table_<t>(id)`` (the rows DuckDB's parallel scan returns, each once):

* host, proved (nothing trusted): ``Params`` (the template parameters), ``Key`` (the group key, ``()`` when ungrouped), the spec-only
  ``Agg`` (one field per suffix fold of the spec, one per MIN / MAX, ``hits`` and one count per extra existence predicate),
  ``agg_zero`` / ``agg_plus`` / ``agg_row`` / ``agg_rng`` and the lemmas ``lemma_agg_step`` (one row), ``lemma_agg_empty``,
  ``lemma_agg_laws`` (commutative monoid) and ``lemma_agg_total`` (the range ``[0, n)`` agrees with the spec's folds);
* the generic proved library ``research_loop/verus_lib/stream_lib.rs`` (folds, permutation, tiling);
* the chunk view ``Chunk_<t>`` with the only two trusted items, S1 (``chunk_<t>`` and its accessor ``str_ent``) and S2
  (``stream_end_<t>``), each marked ``TRUSTED`` with the authorization line;
* the agent regions AGENT_STATE (``QAcc``), AGENT_HELPERS (``qacc_inv``, ``st_val``, helpers) and the bodies AGENT_INIT / STEP / MERGE /
  FINISH of ``q_init`` / ``q_step`` / ``q_merge`` / ``q_finish``;
* the host runtime ``Exec`` (a ``type_invariant``: the state is the fold of the recorded segments), ``exec_new`` / ``exec_step`` /
  ``exec_merge`` / ``exec_finish``; ``exec_finish`` checks at run time that the segments tile ``[0, n)`` (a lost, doubled or skipped
  chunk is an ERROR, never a wrong answer).

The gate (:func:`check_gate`) refuses loudly everything that is not a single-table grouped or ungrouped aggregate of the recognized
folds (SUM / COUNT / AVG incl. exact rationals / MIN / MAX), and every setting the stream contract does not compose with. There is no
fallback to ``run_query``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import lemma_config
from declarative_spec.parse import DeclarativeUnsupported

ROOT = Path(__file__).resolve().parents[1]
STREAM_LIB = ROOT / "research_loop" / "verus_lib" / "stream_lib.rs"

STREAM_MARKER = "// LEMMA_STREAM: run_query is replaced by the streaming executor contract (lemma.toml [run] stream, docs/STREAM.md)"
INIT_START, INIT_END = "// AGENT_INIT_START", "// AGENT_INIT_END"
STEP_START, STEP_END = "// AGENT_STEP_START", "// AGENT_STEP_END"
MERGE_START, MERGE_END = "// AGENT_MERGE_START", "// AGENT_MERGE_END"
FINISH_START, FINISH_END = "// AGENT_FINISH_START", "// AGENT_FINISH_END"
TRUSTED_LINE = "authorized by Emil 2026-10-25 (docs/STREAM.md \"Trusted items\"; data loading only)"

# The bodies regions (name -> markers) and the stub the host gate verifies with (q_step false, q_merge None, q_finish None).
BODY_REGIONS = {
    "init": (INIT_START, INIT_END),
    "step": (STEP_START, STEP_END),
    "merge": (MERGE_START, MERGE_END),
    "finish": (FINISH_START, FINISH_END),
}
STUB = {
    "state": "pub struct QAcc {\n    pub z: u8,\n}",
    "helpers": (
        "pub open spec fn qacc_inv(s: &QAcc) -> bool {\n    true\n}\n\n"
        "pub open spec fn st_val(s: &QAcc, k: Key) -> Agg {\n    agg_zero()\n}"
    ),
    "init": "QAcc { z: 0 }",
    "step": "false",
    "merge": "None",
    "finish": "None",
}


def enabled() -> bool:
    return bool(lemma_config.get("stream"))


def is_stream(spec_rs: str) -> bool:
    return STREAM_MARKER in spec_rs


def lib_slice() -> str:
    text = STREAM_LIB.read_text()
    start = text.index("\n// STREAM_LIB_BEGIN\n") + 1
    end = text.index("\n// STREAM_LIB_END\n") + len("\n// STREAM_LIB_END")
    return text[start:end]


# ---- reading the emitted spec ----------------------------------------------------------------------------------------------------


@dataclass
class Fold:
    """A suffix fold of the spec: ``name(t, i0, args..) = (if cond { val } else { 0int }) + name(t, i0 + 1, args..)``."""

    name: str
    args: list[str]  # the arguments after (t, i0): `k` and `param_*`
    cond: str  # over `i0`
    val: str


@dataclass
class MinMax:
    """A MIN / MAX predicate of the spec: ``name(t, args.., bound)`` with the exists/forall body over ``j0``."""

    name: str
    kind: str  # "min" | "max"
    args: list[str]  # the arguments after t, `bound` among them
    cond: str  # over `j0`
    valfn: str  # `<name>_val`


@dataclass
class Shape:
    tv: str  # the table variable of run_query (e.g. `lineitem`)
    ts: str  # the table suffix (`Cols_<ts>`)
    cols: list[tuple[str, str]]  # (field, element type) of Cols_<ts>, without n
    params: list[tuple[str, str]]  # (name without `param_`, type)
    key: str | None  # the group key type (key_at's), None = ungrouped
    rh_args: list[str]  # row_hit's arguments after (t, i0)
    folds: list[Fold] = field(default_factory=list)
    minmax: list[MinMax] = field(default_factory=list)
    hit_preds: list[tuple[str, list[str]]] = field(default_factory=list)  # (hit_X, its arguments after (t, i0))
    ok_args: list[str] = field(default_factory=list)  # run_query_ok's arguments after t, before res


def _split_args(text: str) -> list[tuple[str, str]]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += {"<": 1, "(": 1, "[": 1, ">": -1, ")": -1, "]": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    out = []
    for p in parts:
        name, _, ty = p.partition(":")
        out.append((name.strip(), ty.strip()))
    return out


def _spec_fn_sig(spec: str, name: str) -> list[tuple[str, str]] | None:
    m = re.search(rf"pub open spec fn {re.escape(name)}\(([^\n]*)\) -> ", spec)
    return _split_args(m.group(1)) if m else None


_RUN_QUERY = re.compile(
    r"// LEMMA_DECLINE: [^\n]*\npub fn run_query\((?P<params>[^)]*)\) -> \(res: Option<Vec<OutRow>>\)\n"
    r"    requires\n(?:        [^\n]*\n)*"
    r"    ensures\n        res matches Some\(res\) ==> run_query_ok\((?P<args>[^\n]*), res\),\n"
    r"\{\n// AGENT_EDIT_START\n// AGENT_EDIT_END\n\}\n"
)


def _refuse(why: str) -> DeclarativeUnsupported:
    return DeclarativeUnsupported(f"stream (lemma.toml [run] stream): {why}")


def check_settings() -> None:
    """The settings the stream contract does not compose with: refused loudly, never silently changed."""
    if lemma_config.assumptions_enabled():
        raise _refuse("needs assumptions = false (q_finish and exec_finish may decline); the assumption-package path is not stated")
    if lemma_config.get("stateful"):
        raise _refuse("stateful = true is another contract for run_query; switch one of them off")
    # in_duckdb composes since the ABI 6 stream template exists (assemble_library.assemble_stream_library_program): the same spec.


def check_sql(sql: str) -> None:
    """SQL-level refusals of phase 1 (before the spec is read): rowid and order-dependent aggregates."""
    low = sql.lower()
    if re.search(r"\bdistinct\b", low):
        raise _refuse("DISTINCT: COUNT DISTINCT / SELECT DISTINCT need a set-valued field (phase 2)")
    if re.search(r"\browid\b", low):
        raise _refuse("rowid: the stream offsets are the scan's, not the table's row ids")
    for fn in ("first", "last", "any_value", "arg_min", "arg_max", "string_agg", "list", "array_agg", "group_concat"):
        if re.search(rf"\b{fn}\s*\(", low):
            raise _refuse(f"{fn}(): an order-dependent aggregate has no stream contract")


def read_shape(spec: str) -> Shape:
    """The parts of an emitted (decline) spec the stream contract is built from; refuses every other shape."""
    if "OutRow" not in spec or re.search(r"pub struct OutRow", spec) is None:
        raise _refuse("the result is not a list of OutRow rows (map results are not stated)")
    structs = re.findall(r"pub struct (Cols_\w+) \{\n((?:    pub [^\n]+\n)+)\}", spec)
    if len(structs) != 1:
        raise _refuse(f"phase 1 streams one table; this query reads {len(structs)} column structs (joins are phase 2)")
    if "__dict" in spec:
        raise _refuse("dictionary-encoded strings: stream tables use the plain encoding")
    if re.search(r"\bf64\b", spec):
        raise _refuse("a FLOAT/DOUBLE value is not stated in the stream contract")
    m = _RUN_QUERY.search(spec)
    if m is None:
        raise _refuse("no run_query contract of the expected form (Option<Vec<OutRow>>, assumptions = false)")
    sig = _split_args(m.group("params"))
    cols_name, body = structs[0]
    ts = cols_name.removeprefix("Cols_")
    tables = [(n, t) for n, t in sig if t == f"&{cols_name}"]
    if len(tables) != 1 or sig[0] != tables[0]:
        raise _refuse("run_query must take the one table first (a self join is not phase 1)")
    tv = tables[0][0]
    from declarative_spec.templates import spec_params

    declared = {name: ty for name, ty, _lo, _hi in spec_params(spec)}
    params: list[tuple[str, str]] = []
    for name, ty in sig[1:]:
        if not name.startswith("param_") or name.removeprefix("param_") not in declared:
            raise _refuse(f"run_query parameter {name}: {ty} is not a template parameter")
        if ty not in ("i64", "i32"):
            raise _refuse(f"template parameter {name}: {ty}: only integer, DECIMAL and DATE parameters are stated")
        params.append((name.removeprefix("param_"), ty))
    cols = re.findall(r"    pub ((?:r#)?\w+): Vec<([^>\n]+)>,", body)
    for f, ty in cols:
        if ty not in ("i64", "i32", "i16", "i8", "u64", "u32", "u16", "u8", "bool", "String"):
            raise _refuse(f"column {ts}.{f}: Vec<{ty}> has no chunk view")
    ka = re.search(rf"pub open spec fn key_at\({re.escape(tv)}: &{cols_name}, i0: int\) -> ([^\n]+) \{{\n", spec)
    key = ka.group(1).strip() if ka else None
    if key is not None and "bool" in key:
        raise _refuse("a GROUP BY key over a nullable column (a NULL cell's value is not part of the chunk view)")
    rh = _spec_fn_sig(spec, "row_hit")
    if rh is None or rh[:2] != [(tv, f"&{cols_name}"), ("i0", "int")]:
        raise _refuse("no row_hit(t, i0, ..) of the expected form")
    pnames = {n for n, _t in params}

    def sub(text: str) -> str:
        """The spec's `param_<name>` arguments are fields of the stream contract's `p: &Params`."""
        return re.sub(r"(?<![\w.])param_(\w+)\b", lambda m: f"p.{m.group(1)}" if m.group(1) in pnames else m.group(0), text)

    def subs(args: list[str]) -> list[str]:
        return [sub(a) for a in args]

    shape = Shape(tv=tv, ts=ts, cols=cols, params=params, key=key, rh_args=subs([n for n, _t in rh[2:]]))
    shape.ok_args = [a.strip() for a in m.group("args").split(",")][1:]
    if [a.strip() for a in m.group("args").split(",")][0] != tv:
        raise _refuse("run_query_ok is not called on the table first")

    n_expr = rf"{re.escape(tv)}\.n as int"
    fold_re = re.compile(
        rf"pub open spec fn (\w+)\({re.escape(tv)}: &{cols_name}, i0: int((?:, [^\n]*?)?)\) -> int\n"
        rf"    decreases {n_expr} - i0\n\{{\n"
        rf"    if i0 < 0 \|\| i0 >= {n_expr} \{{\n        0int\n    \}} else \{{\n"
        rf"        \(if (.+?) \{{ (.+) \}} else \{{ 0int \}}\) \+ \1\({re.escape(tv)}, i0 \+ 1((?:, \w+)*)\)\n"
        rf"    \}}\n\}}"
    )
    recursive = re.findall(rf"pub open spec fn (\w+)\([^\n]*\n    decreases ", spec)
    found = {}
    for fm in fold_re.finditer(spec):
        args = [n for n, _t in _split_args(fm.group(2).lstrip(", "))]
        call = [a.strip() for a in fm.group(5).split(",") if a.strip()]
        if call != args:
            raise _refuse(f"fold {fm.group(1)} recurses with other arguments")
        if re.search(r"\b(?:exists|forall|choose)\s*\|", fm.group(3) + fm.group(4)):
            raise _refuse(f"fold {fm.group(1)}: its per-row term looks at other rows (COUNT DISTINCT and similar are not phase 1)")
        found[fm.group(1)] = Fold(name=fm.group(1), args=subs(args), cond=sub(fm.group(3)), val=sub(fm.group(4)))
    for name in recursive:
        if name in found or name == "seq_le":
            continue
        raise _refuse(f"spec fn {name} is not a recognized fold (COUNT DISTINCT and other folds are not phase 1)")
    shape.folds = list(found.values())

    mm_re = re.compile(
        rf"pub open spec fn ((min|max)_\w+)\({re.escape(tv)}: &{cols_name}((?:, [^\n]*?)?)\) -> bool \{{\n"
        rf"    &&& \(exists\|j0: int\| 0 <= j0 < {n_expr} && (.+) && (\w+)\({re.escape(tv)}, j0\) == bound\)\n"
        rf"    &&& \(forall\|j0: int\| 0 <= j0 < {n_expr} && \4 ==> \5\({re.escape(tv)}, j0\) (>=|<=) bound\)\n\}}"
    )
    for mm in mm_re.finditer(spec):
        args = [n for n, _t in _split_args(mm.group(3).lstrip(", "))]
        if "bound" not in args:
            raise _refuse(f"{mm.group(1)} has no bound argument")
        if (mm.group(2) == "min") != (mm.group(6) == ">="):
            raise _refuse(f"{mm.group(1)}: unexpected order")
        shape.minmax.append(MinMax(name=mm.group(1), kind=mm.group(2), args=subs(args), cond=sub(mm.group(4)), valfn=mm.group(5)))
    named = {mm.name for mm in shape.minmax}
    for other in re.findall(r"pub open spec fn ((?:min|max)_\w+)\(", spec):
        if other not in named and not other.endswith("_val"):
            raise _refuse(f"{other} is not a MIN/MAX predicate of the recognized form")
    ok = re.search(r"pub open spec fn run_query_ok\([^\n]*\n(.*?)\n\}\n", spec, re.S)
    if ok is None:
        raise _refuse("no run_query_ok")
    for name in dict.fromkeys(re.findall(rf"exists\|i0: int\| #!\[trigger (hit_\w+)\({re.escape(tv)}, i0", ok.group(1))):
        hs = _spec_fn_sig(spec, name)
        if hs is None or hs[:2] != [(tv, f"&{cols_name}"), ("i0", "int")]:
            raise _refuse(f"{name}: unexpected signature")
        shape.hit_preds.append((name, subs([n for n, _t in hs[2:]])))
    if not shape.folds and not shape.minmax:
        raise _refuse("not an aggregate query (phase 1 streams grouped or ungrouped aggregates only)")
    return shape


# ---- emission ---------------------------------------------------------------------------------------------------------------------


def _call(name: str, tv: str, first: list[str], args: list[str], **subst: str) -> str:
    return f"{name}({', '.join([tv, *first, *[subst.get(a, a) for a in args]])})"


def _hit_cond(shape: Shape, pred: str = "row_hit", args: list[str] | None = None) -> str:
    c = _call(pred, shape.tv, ["i0"], shape.rh_args if args is None else args)
    return f"{c} && key_at({shape.tv}, i0) == k" if shape.key else c


def emit_contract(shape: Shape) -> str:
    """The stream block that replaces run_query (everything host-side, proved, plus S1/S2 and the agent regions)."""
    tv, ts = shape.tv, shape.ts
    cols = f"Cols_{ts}"
    key = shape.key or "()"
    fields: list[tuple[str, str, str, str, str]] = []  # (field, type, zero, plus, row expr) ; rng built below
    for f in shape.folds:
        fields.append((f.name, "int", "0int", "+", f"if {f.cond} {{ {f.val} }} else {{ 0int }}"))
    for mm in shape.minmax:
        cond_i = re.sub(r"\bj0\b", "i0", mm.cond)
        fields.append((mm.name, "Option<int>", "None", "o" + mm.kind, f"if {cond_i} {{ Some({mm.valfn}({tv}, i0)) }} else {{ None }}"))
    fields.append(("hits", "int", "0int", "+", f"if {_hit_cond(shape)} {{ 1int }} else {{ 0int }}"))
    for name, args in shape.hit_preds:
        fields.append((f"n_{name}", "int", "0int", "+", f"if {_hit_cond(shape, name, args)} {{ 1int }} else {{ 0int }}"))

    struct_fields = "\n".join(f"    pub {n}: {t}," for n, t, *_ in fields)
    zero = ", ".join(f"{n}: {z}" for n, _t, z, _p, _r in fields)

    def plus_of(n: str, op: str) -> str:
        return f"{n}: a.{n} + b.{n}" if op == "+" else f"{n}: {op}(a.{n}, b.{n})"

    plus = ",\n        ".join(plus_of(n, op) for n, _t, _z, op, _r in fields)
    row = ",\n        ".join(f"{n}: {r}" for n, _t, _z, _p, r in fields)

    # range folds: suffix-fold differences for the spec's folds and the counts, a range fold for MIN / MAX
    rng_parts = []
    extra_fns = []
    for f in shape.folds:
        rng_parts.append(
            f"{f.name}: {_call(f.name, tv, ['lo'], f.args)} - {_call(f.name, tv, ['hi'], f.args)}"
        )
    for n, t, _z, op, _r in fields:
        if t == "Option<int>":
            extra_fns.append(f"""pub open spec fn stream_{n}({tv}: &{cols}, lo: int, hi: int, k: Key, p: &Params) -> Option<int>
    decreases hi - lo,
{{
    if hi <= lo {{
        None
    }} else {{
        {op}(stream_{n}({tv}, lo, hi - 1, k, p), agg_row({tv}, hi - 1, k, p).{n})
    }}
}}""")
            rng_parts.append(f"{n}: stream_{n}({tv}, lo, hi, k, p)")
        elif n == "hits" or n.startswith("n_hit_"):
            extra_fns.append(f"""pub open spec fn stream_{n}({tv}: &{cols}, i0: int, k: Key, p: &Params) -> int
    decreases {tv}.n as int - i0,
{{
    if i0 < 0 || i0 >= {tv}.n as int {{
        0int
    }} else {{
        agg_row({tv}, i0, k, p).{n} + stream_{n}({tv}, i0 + 1, k, p)
    }}
}}""")
            rng_parts.append(f"{n}: stream_{n}({tv}, lo, k, p) - stream_{n}({tv}, hi, k, p)")
    rng = ",\n        ".join(rng_parts)

    # lemma_agg_step: unfold each suffix fold at i0 = hi - 1
    step_lines = []
    for f in shape.folds:
        step_lines.append(
            f"        assert({_call(f.name, tv, ['i0'], f.args)} == (if {f.cond} {{ {f.val} }} else {{ 0int }}) + {_call(f.name, tv, ['i0 + 1'], f.args)});"
        )
    for n, t, *_ in fields:
        if n == "hits" or n.startswith("n_hit_"):
            step_lines.append(
                f"        assert(stream_{n}({tv}, i0, k, p) == agg_row({tv}, i0, k, p).{n} + stream_{n}({tv}, i0 + 1, k, p));"
            )
    step_body = "\n".join(step_lines)

    def at(args: tuple[str, str, str]) -> str:
        """The omin / omax laws of every MIN / MAX field at the points of one law (a, b, c are Agg names or `a`)."""
        x, y, z = args
        return " ".join(f"lemma_{op}_at({x}.{n}, {y}.{n}, {z}.{n});" for n, _t, _z, op, _r in fields if op in ("omin", "omax"))

    # lemma_agg_total: the full range agrees with the spec's folds and predicates
    tot_ens = []
    tot_body = []
    for f in shape.folds:
        tot_ens.append(f"        agg_rng({tv}, 0, {tv}.n as int, k, p).{f.name} == {_call(f.name, tv, ['0'], f.args)},")
        tot_body.append(f"    assert({_call(f.name, tv, [f'{tv}.n as int'], f.args)} == 0);")
    count_fields = [("hits", "row_hit", shape.rh_args)] + [(f"n_{n}", n, a) for n, a in shape.hit_preds]
    for n, pred, args in count_fields:
        cond = _hit_cond(shape, pred, args)
        trig = _call(pred, tv, ["i0"], args)
        tot_ens.append(f"        agg_rng({tv}, 0, {tv}.n as int, k, p).{n} >= 0,")
        tot_ens.append(
            f"        agg_rng({tv}, 0, {tv}.n as int, k, p).{n} > 0 <==> (exists|i0: int| #![trigger {trig}] {cond}),"
        )
        tot_body.append(f"""    lemma_stream_{n}_pos({tv}, 0, k, p);
    assert(stream_{n}({tv}, {tv}.n as int, k, p) == 0);
    if exists|i0: int| #![trigger {trig}] {cond} {{
        let i0 = choose|i0: int| #![trigger {trig}] {cond};
        assert(agg_row({tv}, i0, k, p).{n} > 0);
    }}
    if agg_rng({tv}, 0, {tv}.n as int, k, p).{n} > 0 {{
        let j = choose|j: int| 0 <= j < {tv}.n as int && (#[trigger] agg_row({tv}, j, k, p)).{n} > 0;
        let i0 = j;
        assert({cond});
    }}""")
        extra_fns.append(f"""pub proof fn lemma_stream_{n}_pos({tv}: &{cols}, i0: int, k: Key, p: &Params)
    requires
        0 <= i0 <= {tv}.n as int,
    ensures
        stream_{n}({tv}, i0, k, p) >= 0,
        stream_{n}({tv}, i0, k, p) > 0 <==> (exists|j: int| i0 <= j < {tv}.n as int && (#[trigger] agg_row({tv}, j, k, p)).{n} > 0),
    decreases {tv}.n as int - i0,
{{
    if i0 < {tv}.n as int {{
        lemma_stream_{n}_pos({tv}, i0 + 1, k, p);
        if agg_row({tv}, i0, k, p).{n} <= 0 {{
            if exists|j: int| i0 <= j < {tv}.n as int && (#[trigger] agg_row({tv}, j, k, p)).{n} > 0 {{
                let j = choose|j: int| i0 <= j < {tv}.n as int && (#[trigger] agg_row({tv}, j, k, p)).{n} > 0;
                assert(j != i0);
            }}
        }}
    }}
}}""")
    for mm in shape.minmax:
        n = mm.name
        cmp = ">=" if mm.kind == "min" else "<="
        pred_call = _call(n, tv, [], mm.args, bound="b")
        tot_ens.append(
            f"        agg_rng({tv}, 0, {tv}.n as int, k, p).{n} is None <==> !(exists|j0: int| 0 <= j0 < {tv}.n as int && {mm.cond}),"
        )
        tot_ens.append(f"        agg_rng({tv}, 0, {tv}.n as int, k, p).{n} matches Some(b) ==> {pred_call},")
        tot_body.append(f"""    lemma_stream_{n}_range({tv}, 0, {tv}.n as int, k, p);
    if exists|j0: int| 0 <= j0 < {tv}.n as int && {mm.cond} {{
        let j0 = choose|j0: int| 0 <= j0 < {tv}.n as int && {mm.cond};
        assert(agg_row({tv}, j0, k, p).{n} is Some);
    }}
    if agg_rng({tv}, 0, {tv}.n as int, k, p).{n} is None {{
        assert forall|j0: int| 0 <= j0 < {tv}.n as int implies !({mm.cond}) by {{
            assert(agg_row({tv}, j0, k, p).{n} is None);
        }}
    }}
    match agg_rng({tv}, 0, {tv}.n as int, k, p).{n} {{
        Some(b) => {{
            let j = choose|j: int| 0 <= j < {tv}.n as int && (#[trigger] agg_row({tv}, j, k, p)).{n} == Some(b);
            let j0 = j;
            assert({mm.cond} && {mm.valfn}({tv}, j0) == b);
            assert forall|j0: int| 0 <= j0 < {tv}.n as int && {mm.cond} implies {mm.valfn}({tv}, j0) {cmp} b by {{
                assert(agg_row({tv}, j0, k, p).{n} == Some({mm.valfn}({tv}, j0)));
            }}
        }}
        None => {{}}
    }}""")
        extra_fns.append(f"""pub proof fn lemma_stream_{n}_range({tv}: &{cols}, lo: int, hi: int, k: Key, p: &Params)
    requires
        0 <= lo <= hi,
    ensures
        stream_{n}({tv}, lo, hi, k, p) is None <==> (forall|j: int| lo <= j < hi ==> (#[trigger] agg_row({tv}, j, k, p)).{n} is None),
        stream_{n}({tv}, lo, hi, k, p) matches Some(b) ==> (exists|j: int| lo <= j < hi && (#[trigger] agg_row({tv}, j, k, p)).{n} == Some(b))
            && (forall|j: int| lo <= j < hi && (#[trigger] agg_row({tv}, j, k, p)).{n} is Some ==> agg_row({tv}, j, k, p).{n}->Some_0 {cmp} b),
    decreases hi - lo,
{{
    if hi > lo {{
        lemma_stream_{n}_range({tv}, lo, hi - 1, k, p);
        let last = agg_row({tv}, hi - 1, k, p).{n};
        let prev = stream_{n}({tv}, lo, hi - 1, k, p);
        if prev is None {{
            assert forall|j: int| lo <= j < hi - 1 implies (#[trigger] agg_row({tv}, j, k, p)).{n} is None by {{}}
        }}
        match stream_{n}({tv}, lo, hi, k, p) {{
            Some(b) => {{
                if last == Some(b) {{
                    assert(agg_row({tv}, hi - 1, k, p).{n} == Some(b));
                }} else {{
                    let j = choose|j: int| lo <= j < hi - 1 && (#[trigger] agg_row({tv}, j, k, p)).{n} == prev;
                    assert(agg_row({tv}, j, k, p).{n} == Some(b));
                }}
            }}
            None => {{}}
        }}
    }}
}}""")
    tot_ens_s = "\n".join(tot_ens)
    tot_body_s = "\n".join(tot_body)

    params_struct = "\n".join(f"    pub {n}: {t}," for n, t in shape.params)
    params_eq = " && ".join(f"a.{n} == b.{n}" for n, _t in shape.params) or "true"
    ok_args_p = ", ".join(f"p.{a.removeprefix('param_')}" for a in shape.ok_args)
    ok_args_e = ", ".join(f"e.params().{a.removeprefix('param_')}" for a in shape.ok_args)
    ok_p = f"&t@{', ' + ok_args_p if ok_args_p else ''}"
    ok_e = f"&stream_table_{ts}(e.sid()){', ' + ok_args_e if ok_args_e else ''}"

    chunk = _chunk_items(shape)
    extra = "\n\n".join(extra_fns)
    return f"""{STREAM_MARKER}
// The streaming contract. T = stream_table_{ts}(id) is the ghost table of one stream: the rows DuckDB's parallel scan of {ts}
// returns (each row once, at the offset its chunk was handed out at). Workers fold chunks into QAcc states (q_step), states are
// merged in any order (q_merge), and q_finish answers from the state of all chunks. Proved by Verus: everything below except the
// two items marked TRUSTED (S1, S2). The host runtime Exec checks at run time that the chunks tile [0, n) exactly.

{lib_slice()}

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

// Spec-only: one field per suffix fold of the spec, one per MIN / MAX (None = no row), `hits` (rows of the group that pass the
// WHERE) and one count per further existence predicate the result mentions.
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

// The contribution of row i0 to group k.
pub open spec fn agg_row({tv}: &{cols}, i0: int, k: Key, p: &Params) -> Agg {{
    Agg {{
        {row}
    }}
}}

{extra}

// The fold of agg_row over the rows [lo, hi) (0 <= lo <= hi): the spec's suffix folds as differences, MIN / MAX as a range fold.
pub open spec fn agg_rng({tv}: &{cols}, lo: int, hi: int, k: Key, p: &Params) -> Agg {{
    Agg {{
        {rng}
    }}
}}

pub proof fn lemma_agg_empty({tv}: &{cols}, lo: int, k: Key, p: &Params)
    requires
        0 <= lo,
    ensures
        agg_rng({tv}, lo, lo, k, p) == agg_zero(),
{{
}}

// One row: a range grows by agg_row at its end.
pub proof fn lemma_agg_step({tv}: &{cols}, lo: int, hi: int, k: Key, p: &Params)
    requires
        0 <= lo < hi,
    ensures
        agg_rng({tv}, lo, hi, k, p) == agg_plus(agg_rng({tv}, lo, hi - 1, k, p), agg_row({tv}, hi - 1, k, p)),
{{
    let i0 = hi - 1;
    if i0 < {tv}.n as int {{
{step_body}
    }}
}}

// agg_plus is a commutative monoid with identity agg_zero.
pub proof fn lemma_agg_laws()
    ensures
        monoid_laws(agg_zero(), agg_plus_f()),
        comm_laws(agg_plus_f()),
{{
    assert forall|a: Agg| #[trigger] agg_plus(agg_zero(), a) == a by {{ {at(("a", "a", "a"))} }}
    assert forall|a: Agg| #[trigger] agg_plus(a, agg_zero()) == a by {{ {at(("a", "a", "a"))} }}
    assert forall|a: Agg, b: Agg| #[trigger] agg_plus(a, b) == agg_plus(b, a) by {{ {at(("a", "b", "b"))} }}
    assert forall|a: Agg, b: Agg, c: Agg| #[trigger] agg_plus(agg_plus(a, b), c) == agg_plus(a, agg_plus(b, c)) by {{ {at(("a", "b", "c"))} }}
}}

// The whole table: what q_finish needs to meet run_query_ok.
pub proof fn lemma_agg_total({tv}: &{cols}, k: Key, p: &Params)
    ensures
{tot_ens_s}
{{
{tot_body_s}
}}

// ---- the stream: ghost table, chunk view, the two trusted items ----

{chunk}

// ---- the agent: state, init, step, merge, finish ----

// The agent's state type: `pub struct QAcc {{ .. }}` (and further structs / enums). No references, no lifetimes.
// AGENT_STATE_START
// AGENT_STATE_END

// The agent's helper region (above) defines `spec fn qacc_inv(s: &QAcc) -> bool` and `spec fn st_val(s: &QAcc, k: Key) -> Agg`
// (the value of group k the state stands for).

pub fn q_init(p: &Params) -> (s: QAcc)
    ensures
        qacc_inv(&s),
        forall|k: Key| #[trigger] st_val(&s, k) == agg_zero(),
{{
{INIT_START}
{INIT_END}
}}

// Fold one chunk into the state. false = decline (the query is then declined, never answered wrongly).
pub fn q_step(s: &mut QAcc, c: &Chunk_{ts}, p: &Params) -> (ok: bool)
    requires
        qacc_inv(old(s)),
        chunk_ok_{ts}(c),
    ensures
        ok ==> qacc_inv(final(s)) && forall|k: Key| #[trigger] st_val(final(s), k)
            == agg_plus(st_val(old(s), k), agg_rng(&stream_table_{ts}(c.sid), c.off as int, c.off + c.len, k, p)),
{{
{STEP_START}
{STEP_END}
}}

// Merge two states (any two: the chunks of a and of b are disjoint). None = decline.
pub fn q_merge(a: QAcc, b: QAcc) -> (r: Option<QAcc>)
    requires
        qacc_inv(&a),
        qacc_inv(&b),
    ensures
        r matches Some(r) ==> qacc_inv(&r) && forall|k: Key| #[trigger] st_val(&r, k) == agg_plus(st_val(&a, k), st_val(&b, k)),
{{
{MERGE_START}
{MERGE_END}
}}

// Answer from the state of the whole table (HAVING, ORDER BY and LIMIT happen here). None = decline.
pub fn q_finish(s: QAcc, t: Ghost<{cols}>, p: &Params) -> (res: Option<Vec<OutRow>>)
    requires
        qacc_inv(&s),
        valid_cols_{ts}(&t@),
        forall|k: Key| #[trigger] st_val(&s, k) == agg_rng(&t@, 0, t@.n as int, k, p),
    ensures
        res matches Some(r) ==> run_query_ok({ok_p}, r),
{{
{FINISH_START}
{FINISH_END}
}}

{_runtime(shape, ok_e)}"""


def _chunk_items(shape: Shape) -> str:
    """The ghost table, Chunk_<t> (the agent's view of one chunk), RawChunk_<t> (the ABI the glue fills), S1 and S2."""
    ts, tv = shape.ts, shape.tv
    cols = f"Cols_{ts}"
    names = {f for f, _t in shape.cols}
    chunk_fields, raw_fields, ok, builds, inits = [], [], [], [], []
    for f, ty in shape.cols:
        valid = f"{f}__valid" if not f.endswith("__valid") and f"{f}__valid" in names else None
        guard = f" && t.{valid}@[c.off + r]" if valid else ""
        if ty == "String":
            chunk_fields.append(f"    pub {f}: StrCol<'a>,")
            raw_fields += [f"    pub {f}_sel: usize,", f"    pub {f}_ents: usize,", f"    pub {f}_nents: u64,", f"    pub {f}_dict: u64,"]
            ok.append(f"    &&& c.{f}.sel@.len() == c.len && c.{f}.raw@.len() == c.{f}.ents@.len()")
            ok.append(
                f"    &&& forall|r: int| #![trigger c.{f}.sel@[r]] 0 <= r < c.len ==> (c.{f}.sel@[r] as int) < c.{f}.ents@.len()"
            )
            ok.append(
                f"    &&& forall|r: int| #![trigger c.{f}.sel@[r]] 0 <= r < c.len{guard} ==> c.{f}.ents@[c.{f}.sel@[r] as int] == t.{f}@[c.off + r]@"
            )
            builds.append(
                f"    let {f}_sel: &'a [u32] = lemma_stream_slice(raw.{f}_sel as *const u32, len);\n"
                f"    let {f}_raw: &'a [StrRaw] = lemma_stream_slice(raw.{f}_ents as *const StrRaw, raw.{f}_nents as usize);\n"
                f"    if !lemma_stream_strings_ok({f}_sel, {f}_raw) {{\n        return None;\n    }}"
            )
            inits.append(f"{f}: StrCol {{ sel: {f}_sel, raw: {f}_raw, ents: Ghost::assume_new(), dict_id: raw.{f}_dict }}")
        else:
            chunk_fields.append(f"    pub {f}: &'a [{ty}],")
            raw_fields.append(f"    pub {f}: usize,")
            ok.append(f"    &&& c.{f}@.len() == c.len")
            ok.append(f"    &&& forall|r: int| #![trigger c.{f}@[r]] 0 <= r < c.len{guard} ==> c.{f}@[r] == t.{f}@[c.off + r]")
            builds.append(f"    let {f}: &'a [{ty}] = lemma_stream_slice(raw.{f} as *const {ty}, len);")
            inits.append(f"{f}")
    chunk_fields_s = "\n".join(chunk_fields)
    raw_fields_s = "\n".join(raw_fields)
    ok_s = "\n".join(ok)
    builds_s = "\n".join(builds)
    inits_s = ", ".join(["sid: sh.id", "off: raw.off as usize", "len", *inits])
    return f"""// The ghost table of stream `id`: never materialized; S1 and S2 are the only facts about it.
pub uninterp spec fn stream_table_{ts}(id: u64) -> {cols};

// One stream of {ts} (exec handle): `id` names its ghost table, `raw` is the address of the glue's StreamEnd_{ts}.
pub struct Stream_{ts} {{
    pub id: u64,
    pub raw: usize,
}}

// DuckDB's string_t (16 bytes): length (u32) then 12 inline bytes, or a 4-byte prefix and a pointer when longer than 12.
#[repr(C)]
pub struct StrRaw {{
    pub w0: u64,
    pub w1: u64,
}}

// A VARCHAR column of one chunk: row r is the entry ents@[sel@[r]] (FLAT: sel is the identity; DICTIONARY: the dictionary
// entries). `ents` is the ghost view of the entries `raw` holds; str_ent reads one.
pub struct StrCol<'a> {{
    pub sel: &'a [u32],
    pub raw: &'a [StrRaw],
    pub ents: Ghost<Seq<Seq<char>>>,
    // DuckDB's dictionary id of a DICTIONARY vector (0: FLAT or unknown). Plain data: nothing is promised about it (equal ids are
    // NOT claimed to mean equal entries; a cross-chunk memo keyed by it needs a further S1 claim, not authorized yet).
    pub dict_id: u64,
}}

// The agent's view of one chunk: rows [off, off + len) of the ghost table.
pub struct Chunk_{ts}<'a> {{
    pub sid: u64,
    pub off: usize,
    pub len: usize,
{chunk_fields_s}
}}

// What S1 promises about a chunk (NULL cells: the validity is exact, the value is promised only where the cell is valid).
pub open spec fn chunk_ok_{ts}(c: &Chunk_{ts}) -> bool {{
    let t = stream_table_{ts}(c.sid);
    &&& c.off + c.len <= t.n
{ok_s}
}}

// The chunk the glue hands over (ABI): j = the chunk's index and off = its first row, both from one fetch_add of the scan's
// counter; one buffer address per column (len cells of the column-file encoding: DATE days i32, DECIMAL scaled integers, bool
// one byte 0/1; VARCHAR: len u32 selection indices into nents string_t entries).
#[repr(C)]
pub struct RawChunk_{ts} {{
    pub j: u64,
    pub off: u64,
    pub len: u64,
{raw_fields_s}
}}

// What the glue keeps behind Stream_{ts}.raw for S2: chunks handed out and rows scanned, final once every worker has returned.
#[repr(C)]
pub struct StreamEnd_{ts} {{
    pub m: u64,
    pub n: u64,
}}

#[verifier::external]
fn lemma_stream_slice<'a, X>(ptr: *const X, len: usize) -> &'a [X] {{
    // part of S1: a buffer of `len` cells the glue owns for the chunk's lifetime
    if len == 0 {{ &[] }} else {{ unsafe {{ std::slice::from_raw_parts(ptr, len) }} }}
}}

#[verifier::external]
fn lemma_stream_str_bytes<'a>(e: &'a StrRaw) -> &'a [u8] {{
    // part of S1: the bytes of one string_t (inline up to 12 bytes, else behind the pointer)
    let len = (e.w0 & 0xffff_ffff) as usize;
    if len <= 12 {{
        unsafe {{ std::slice::from_raw_parts((e as *const StrRaw as *const u8).add(4), len) }}
    }} else {{
        unsafe {{ std::slice::from_raw_parts(e.w1 as *const u8, len) }}
    }}
}}

#[verifier::external]
fn lemma_stream_strings_ok(sel: &[u32], ents: &[StrRaw]) -> bool {{
    // part of S1 (checked, not trusted): every selection index is in range (their maximum: a branch-free pass) and every entry
    // is UTF-8 (a DICTIONARY vector hands its few entries, a FLAT one its len)
    (sel.is_empty() || (sel.iter().fold(0u32, |m, &s| m.max(s)) as usize) < ents.len())
        && ents.iter().all(|e| std::str::from_utf8(lemma_stream_str_bytes(e)).is_ok())
}}

// TRUSTED S1 (chunk view), {TRUSTED_LINE}.
// The chunk is rows [off, off + len) of the ghost table of `sh` (chunk_ok_{ts}). Checked here, not trusted: selection indices in
// range and UTF-8 (None otherwise).
#[verifier::external_body]
pub fn chunk_{ts}<'a>(sh: &Stream_{ts}, raw: &'a RawChunk_{ts}) -> (c: Option<Chunk_{ts}<'a>>)
    ensures
        c matches Some(c) ==> c.sid == sh.id && chunk_ok_{ts}(&c),
{{
    let len = raw.len as usize;
{builds_s}
    Some(Chunk_{ts} {{ {inits_s} }})
}}

// TRUSTED S1 (accessor), {TRUSTED_LINE}.
#[verifier::external_body]
pub fn str_ent<'a>(v: &StrCol<'a>, j: usize) -> (s: &'a str)
    requires
        j < v.ents@.len(),
    ensures
        s@ == v.ents@[j as int],
{{
    let raw: &'a [StrRaw] = v.raw;
    unsafe {{ std::str::from_utf8_unchecked(lemma_stream_str_bytes(&raw[j])) }}
}}

// TRUSTED S2 (stream end), {TRUSTED_LINE}.
// Called once every worker has returned: n is the number of rows of the ghost table, and the table is well formed. (m, the
// number of chunks handed out, is not trusted: exec_finish only sizes its check with it.)
#[verifier::external_body]
pub fn stream_end_{ts}(sh: &Stream_{ts}) -> (r: (usize, usize))
    ensures
        r.1 == stream_table_{ts}(sh.id).n,
        valid_cols_{ts}(&stream_table_{ts}(sh.id)),
{{
    let e = unsafe {{ &*(sh.raw as *const StreamEnd_{ts}) }};
    (e.m as usize, e.n as usize)
}}"""


def _runtime(shape: Shape, ok_e: str) -> str:
    ts = shape.ts
    return f"""// ---- the host runtime (fixed, verified) ----

pub open spec fn seg_agg(id: u64, k: Key, p: Params) -> spec_fn(Seg) -> Agg {{
    |s: Seg| agg_rng(&stream_table_{ts}(id), s.off as int, seg_end(s), k, &p)
}}

pub open spec fn seg_fold(id: u64, segs: Seq<Seg>, k: Key, p: Params) -> Agg {{
    fold_by(segs, seg_agg(id, k, p), agg_zero(), agg_plus_f())
}}

// Segments that are a reordering (pa, pb) of chunks that tile the ghost table fold to the whole table.
pub proof fn lemma_stream_total(id: u64, segs: Seq<Seg>, tiles: Seq<Seg>, pa: Seq<int>, pb: Seq<int>, k: Key, p: Params)
    requires
        segs.len() == tiles.len(),
        pa.len() == segs.len(),
        pb.len() == tiles.len(),
        forall|i: int| #![trigger pa[i]] 0 <= i < segs.len() ==> 0 <= pa[i] < tiles.len() && pb[pa[i]] == i && segs[i] == tiles[pa[i]],
        forall|j: int| #![trigger pb[j]] 0 <= j < tiles.len() ==> 0 <= pb[j] < segs.len() && pa[pb[j]] == j,
        tiles_ok(tiles, stream_table_{ts}(id).n as int),
    ensures
        seg_fold(id, segs, k, p) == agg_rng(&stream_table_{ts}(id), 0, stream_table_{ts}(id).n as int, k, &p),
{{
    lemma_agg_laws();
    let t = stream_table_{ts}(id);
    let rng = |lo: int, hi: int| agg_rng(&t, lo, hi, k, &p);
    let row = |i: int| agg_row(&t, i, k, &p);
    assert forall|lo: int| 0 <= lo implies #[trigger] rng(lo, lo) == agg_zero() by {{
        lemma_agg_empty(&t, lo, k, &p);
    }}
    assert forall|lo: int, hi: int| 0 <= lo < hi implies #[trigger] rng(lo, hi) == (agg_plus_f())(rng(lo, hi - 1), row(hi - 1)) by {{
        lemma_agg_step(&t, lo, hi, k, &p);
    }}
    assert(rng_step_ok(rng, row, agg_zero(), agg_plus_f()));
    assert forall|s: Seg| #[trigger] (seg_agg(id, k, p))(s) == rng(s.off as int, seg_end(s)) by {{}}
    lemma_fold_bij(segs, tiles, pa, pb, seg_agg(id, k, p), agg_zero(), agg_plus_f());
    lemma_tiles(tiles, t.n as int, seg_agg(id, k, p), rng, row, agg_zero(), agg_plus_f());
}}

// The outcome of a stream: the rows, a decline by the agent's code, or an error of the glue or the scheduling (never rows).
pub enum StreamOut {{
    Rows(Vec<OutRow>),
    Declined,
    Error,
}}

// One worker's executor (and, after exec_merge, several workers'). The type invariant: unless poisoned (acc None), the state is
// the fold of the segments of the chunks it has stepped.
pub struct Exec {{
    sh: Stream_{ts},
    p: Params,
    acc: Option<QAcc>,
    err: bool,
    segs: Vec<Seg>,
}}

impl Exec {{
    #[verifier::type_invariant]
    spec fn wf(self) -> bool {{
        match self.acc {{
            Some(a) => qacc_inv(&a) && forall|k: Key| #[trigger] st_val(&a, k) == seg_fold(self.sh.id, self.segs@, k, self.p),
            None => true,
        }}
    }}

    pub closed spec fn sid(self) -> u64 {{
        self.sh.id
    }}

    pub closed spec fn params(self) -> Params {{
        self.p
    }}
}}

pub fn exec_new(sh: Stream_{ts}, p: Params) -> (e: Exec)
    ensures
        e.sid() == sh.id,
        e.params() == p,
{{
    let a = q_init(&p);
    let segs: Vec<Seg> = Vec::new();
    proof {{
        assert forall|k: Key| #[trigger] st_val(&a, k) == seg_fold(sh.id, segs@, k, p) by {{}}
    }}
    Exec {{ sh, p, acc: Some(a), err: false, segs }}
}}

// Not poisoned (no decline and no error so far).
pub fn exec_ok(e: &Exec) -> bool {{
    e.acc.is_some()
}}

pub fn exec_step(e: Exec, raw: &RawChunk_{ts}) -> (r: Exec)
    ensures
        r.sid() == e.sid(),
        r.params() == e.params(),
{{
    proof {{
        use_type_invariant(&e);
    }}
    let Exec {{ sh, p, acc, err, mut segs }} = e;
    match acc {{
        None => Exec {{ sh, p, acc: None, err, segs }},
        Some(a0) => {{
            let mut a = a0;
            match chunk_{ts}(&sh, raw) {{
                None => Exec {{ sh, p, acc: None, err: true, segs }},
                Some(c) => {{
                    let ghost old_segs = segs@;
                    if q_step(&mut a, &c, &p) {{
                        let s = Seg {{ j: raw.j as usize, off: c.off, len: c.len }};
                        segs.push(s);
                        proof {{
                            assert forall|k: Key| #[trigger] st_val(&a, k) == seg_fold(sh.id, segs@, k, p) by {{
                                lemma_fold_push(old_segs, s, seg_agg(sh.id, k, p), agg_zero(), agg_plus_f());
                                assert(segs@ == old_segs.push(s));
                            }}
                        }}
                        Exec {{ sh, p, acc: Some(a), err, segs }}
                    }} else {{
                        Exec {{ sh, p, acc: None, err, segs }}
                    }}
                }}
            }}
        }}
    }}
}}

pub fn exec_merge(a: Exec, b: Exec) -> (r: Exec)
    ensures
        r.sid() == a.sid(),
        r.params() == a.params(),
{{
    proof {{
        use_type_invariant(&a);
        use_type_invariant(&b);
    }}
    let Exec {{ sh, p, acc, err, mut segs }} = a;
    let Exec {{ sh: sh_b, p: p_b, acc: acc_b, err: err_b, segs: mut segs_b }} = b;
    if sh.id != sh_b.id || !params_eq(&p, &p_b) {{
        return Exec {{ sh, p, acc: None, err: true, segs }};
    }}
    match acc {{
        Some(x) => match acc_b {{
            Some(y) => {{
                let ghost sa = segs@;
                let ghost sb = segs_b@;
                let ghost gx = x;
                let ghost gy = y;
                match q_merge(x, y) {{
                    Some(m) => {{
                        segs.append(&mut segs_b);
                        proof {{
                            lemma_agg_laws();
                            assert forall|k: Key| #[trigger] st_val(&m, k) == seg_fold(sh.id, segs@, k, p) by {{
                                assert(st_val(&gx, k) == seg_fold(sh.id, sa, k, p));
                                assert(st_val(&gy, k) == seg_fold(sh.id, sb, k, p));
                                lemma_fold_concat(sa, sb, seg_agg(sh.id, k, p), agg_zero(), agg_plus_f());
                            }}
                        }}
                        Exec {{ sh, p, acc: Some(m), err, segs }}
                    }}
                    None => Exec {{ sh, p, acc: None, err, segs }},
                }}
            }}
            None => Exec {{ sh, p, acc: None, err: err || err_b, segs }},
        }},
        None => Exec {{ sh, p, acc: None, err: err || err_b, segs }},
    }}
}}

// Rows only when the stepped chunks tile [0, n) exactly: each chunk index below m once, offsets contiguous from 0 to n.
pub fn exec_finish(e: Exec) -> (r: StreamOut)
    ensures
        r matches StreamOut::Rows(res) ==> run_query_ok({ok_e}, res),
{{
    proof {{
        use_type_invariant(&e);
    }}
    let Exec {{ sh, p, acc, err, segs }} = e;
    let a = match acc {{
        Some(a) => a,
        None => {{
            return if err {{ StreamOut::Error }} else {{ StreamOut::Declined }};
        }}
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
        assert forall|k: Key| #[trigger] st_val(&a, k) == agg_rng(&t, 0, t.n as int, k, &p) by {{
            lemma_stream_total(sh.id, segs@, tiles, pa, pos, k, p);
        }}
    }}
    match q_finish(a, Ghost(t), &p) {{
        Some(res) => StreamOut::Rows(res),
        None => StreamOut::Declined,
    }}
}}
"""


def to_stream(spec: str) -> str:
    """Replace run_query of an emitted (assumptions = false) spec by the stream contract; refuse every other shape loudly."""
    check_settings()
    shape = read_shape(spec)
    m = _RUN_QUERY.search(spec)
    assert m is not None
    return spec[: m.start()] + emit_contract(shape) + spec[m.end() :]


def extract_regions(source: str) -> dict[str, str]:
    """The agent's six regions of a stream file: state, helpers, init, step, merge, finish."""
    from declarative_spec.regions import (
        HELPERS_END,
        HELPERS_START,
        STATE_END,
        STATE_START,
        _required,
    )

    out = {"state": _required(source, STATE_START, STATE_END, "AGENT_STATE"),
           "helpers": _required(source, HELPERS_START, HELPERS_END, "AGENT_HELPERS")}
    for name, (start, end) in BODY_REGIONS.items():
        out[name] = _required(source, start, end, f"AGENT_{name.upper()}")
    return out
