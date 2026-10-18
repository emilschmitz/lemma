"""Stateful accelerators (``stateful`` in lemma.toml [run]): the agent writes a state, a ``build`` and an ``execute``.

The emitted ``run_query`` contract is rewritten into three host items and two agent functions, with the SAME query spec:

* ``query_pre(<tables>)``: the ``requires`` of ``run_query`` (``valid_cols_*``, literal hypotheses, join caps), verbatim.
* ``query_post(<tables>, <params>, res)``: the ``ensures`` of ``run_query``, verbatim.
* ``QDb``: one field per table, named like the ``run_query`` parameter; ``QState { snap: Ghost<QDb>, acc: QAcc }`` with
  ``db() = snap@`` and ``inv() = query_pre(db) && qstate_inv(self)``.
* agent: ``struct QAcc`` (region AGENT_STATE), ``spec fn qstate_inv(s: &QState) -> bool`` (helper region),
  ``build(<tables by value>) -> (s: QState)`` ensures ``s.inv() && s.db() == QDb { .. the inputs .. }`` (region AGENT_BUILD),
  ``execute(s: &QState, <params>) -> (res)`` requires ``s.inv()`` ensures ``query_post(db, params, res)`` (region AGENT_EDIT).

So ``execute(&build(cols), p)`` satisfies exactly what ``run_query(cols, p)`` had to: ``inv`` is the agent's, but it is only
assumed where ``build`` proved it, so a wrong ``inv`` fails the proof and never changes an answer. The degenerate case is
a ``QAcc`` that owns the tables (``inv``: ``s.acc.<t> == s.db().<t>``) and an ``execute`` that is the old ``run_query`` body.

The host runtime ``QRuntime`` (``runtime_rs``) is fixed and verified: it holds at most one state with the data version it was
built from; ``execute_at(version)`` returns ``None`` unless that state is present and was built at ``version``, and otherwise the
result satisfies ``query_post`` on the snapshot ``refresh`` was given. What it cannot know, and trusts, is that the caller
passes the version of the data it hands to ``refresh`` and bumps the version whenever the data changes (DuckDB's commit
id / table version in the extension, a counter in the tests). Nothing is persisted: a new process builds again.

With lemma.toml ``assumptions = false`` (``decline.py``) ``execute`` may decline: ``wrap_decline`` makes it return ``Option<T>`` with
``ensures res matches Some(res) ==> query_post(..)``; ``execute_at`` then returns ``Option<Option<T>>`` (``Some(None)`` = declined).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import lemma_config
from declarative_spec.parse import DeclarativeUnsupported
from declarative_spec.regions import BUILD_END, BUILD_START, STATE_END, STATE_START

__all__ = [
    "BUILD_END", "BUILD_START", "STATE_END", "STATE_START", "contract", "enabled", "is_stateful", "runtime_rs", "to_stateful",
    "unwrap_decline", "wrap_decline",
]

_RUN_QUERY = re.compile(
    r"pub fn run_query\((?P<params>[^)]*)\) -> \(res: (?P<ret>[^\n]*)\)\n"
    r"    requires\n(?P<req>(?:        [^\n]*\n)*)"
    r"    ensures\n(?P<ens>(?:        [^\n]*\n)*)"
    r"\{\n// AGENT_EDIT_START\n// AGENT_EDIT_END\n\}"
)


def enabled() -> bool:
    return bool(lemma_config.get("stateful"))


def is_stateful(spec_rs: str) -> bool:
    return BUILD_START in spec_rs


@dataclass(frozen=True)
class Contract:
    tables: list[tuple[str, str]]  # (parameter name, Cols_<suffix>) in run_query order
    params: list[tuple[str, str]]  # runtime parameters (name, type): every non-table parameter
    ret: str  # what execute returns: ``Option<T>`` when it may decline
    declines: bool = False  # lemma.toml assumptions = false: execute returns Option, None declines (wrap_decline)
    scans: tuple[tuple[str, str], ...] = ()  # agent scans (agent_scan.py): (handle parameter of build, Scan_<suffix>), one per table

    @property
    def value(self) -> str:
        """The result type ``query_post`` is about (``ret`` without the decline ``Option``)."""
        return self.ret[len("Option<") : -1] if self.declines else self.ret


def _split_top(text: str) -> list[str]:
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
    return [p.strip() for p in parts if p.strip()]


def _conjuncts(block: str) -> list[str]:
    """The comma-ended clauses of a requires/ensures block (one per line; a clause may run over several lines)."""
    out, cur = [], ""
    for line in block.splitlines():
        cur = f"{cur} {line.strip()}" if cur else line.strip()
        balanced = sum(cur.count(o) - cur.count(c) for o, c in ("()", "[]", "{}")) == 0
        if cur.endswith(",") and balanced:
            out.append(cur[:-1].strip())
            cur = ""
    if cur:
        raise DeclarativeUnsupported(f"stateful: a run_query clause does not end with ',': {cur[:80]}")
    return out


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(name)}(?!\w)", text) is not None


def to_stateful(spec_rs: str) -> str:
    """Rewrite the ``run_query`` contract of an emitted spec into the build/execute contract (see the module doc)."""
    m = _RUN_QUERY.search(spec_rs)
    if m is None:
        raise DeclarativeUnsupported("stateful: no run_query contract of the expected form in the spec")
    tables: list[tuple[str, str]] = []
    arcs: list[str] = []
    params: list[tuple[str, str]] = []
    scans: list[tuple[str, str]] = []
    for part in _split_top(m.group("params")):
        name, _, ty = part.partition(":")
        name, ty = name.strip(), ty.strip()
        tm = re.fullmatch(r"&(Cols_\w+)", ty)
        sm = re.fullmatch(r"&(Scan_\w+)", ty)
        if tm:
            tables.append((name, tm.group(1)))
        elif sm:
            # An agent-scan handle (agent_scan.py): build gets it, execute does not (scans are for making the state).
            scans.append((name, sm.group(1)))
        elif "std::sync::Arc<" in ty:
            arcs.append(name)
        else:
            params.append((name, ty))
    structs = [s for _n, s in tables]
    if len(set(structs)) != len(structs):
        raise DeclarativeUnsupported("stateful: a self join (two parameters of one table) has no stateful contract yet")
    if not tables:
        raise DeclarativeUnsupported("stateful: run_query reads no table")
    req = [c for c in _conjuncts(m.group("req")) if not any(_mentions(c, a) for a in arcs)]
    # `scan_full_<t>(<t>_scan) == *<t>`: a precondition of build and refresh (the handle scans exactly the table build is given),
    # not of query_pre (execute has no handle). build takes the tables by value, so `*<t>` becomes `<t>`.
    scan_req = [c for c in req if any(_mentions(c, n) for n, _s in scans)]
    req = [c for c in req if c not in scan_req]
    table_names = {n for n, _s in tables}
    for c in scan_req:
        sm = re.fullmatch(r"scan_full_\w+\((\w+)\) == \*(\w+)", c)
        if sm is None or sm.group(2) not in table_names:
            raise DeclarativeUnsupported(f"stateful: a scan-handle requires of an unexpected form: {c[:80]}")
    scan_req = [re.sub(r"== \*(\w+)$", r"== \1", c) for c in scan_req]
    for c in req:
        for p, _ty in params:
            if _mentions(c, p):
                raise DeclarativeUnsupported(f"stateful: a requires on the runtime parameter {p} is not supported: {c[:80]}")
    ens = _conjuncts(m.group("ens"))
    ret = m.group("ret").strip()

    table_params = ", ".join(f"{n}: &{s}" for n, s in tables)
    run_params = "".join(f", {n}: {t}" for n, t in params)
    snap_tables = ", ".join(f"&self.snap@.{n}" for n, _s in tables)
    db_tables = ", ".join(f"&s.db().{n}" for n, _s in tables)
    param_names = "".join(f", {n}" for n, _t in params)
    pre_body = "\n".join(f"    &&& {c}" for c in req) or "    true"
    post_body = "\n".join(f"    &&& {c}" for c in ens) or "    true"
    qdb_fields = "\n".join(f"    pub {n}: {s}," for n, s in tables)
    build_params = ", ".join([f"{n}: {s}" for n, s in tables] + [f"{n}: &{s}" for n, s in scans])
    build_pre = ", ".join(f"&{n}" for n, _s in tables)
    build_scan_req = "".join(f"        {c},\n" for c in scan_req)
    qdb_init = ", ".join(f"{n}: {n}" for n, _s in tables)
    scan_note = (
        "\n// Agent scans: `build` gets one scan handle per table (scan_full_<t>(<t>_scan) == <t>) and may call scan_where_<t> to make the\n"
        "// state from the rows DuckDB returns for a predicate; `execute` answers from the state only."
        if scans
        else ""
    )
    block = f"""// STATEFUL CONTRACT (lemma.toml `stateful`): `build` makes a state from the tables, `execute` answers from the state.
// query_pre is the requires and query_post the ensures that run_query had, verbatim; db() is the ghost snapshot of the
// tables `build` was given. The host keeps the state while the data version stays the same and calls `build` again
// (on the current tables) when it changes; `execute` may run many times per build.{scan_note}
pub struct QDb {{
{qdb_fields}
}}

pub open spec fn query_pre({table_params}) -> bool {{
{pre_body}
}}

pub open spec fn query_post({table_params}{run_params}, res: {ret}) -> bool {{
{post_body}
}}

// The agent's state type: `pub struct QAcc {{ .. }}` (and any further structs or enums it uses). Ghost fields are allowed.
{STATE_START}
{STATE_END}

pub struct QState {{
    pub snap: Ghost<QDb>,
    pub acc: QAcc,
}}

impl QState {{
    pub open spec fn db(&self) -> QDb {{
        self.snap@
    }}

    // qstate_inv is the agent's `spec fn qstate_inv(s: &QState) -> bool` (helper region).
    pub open spec fn inv(&self) -> bool {{
        query_pre({snap_tables}) && qstate_inv(self)
    }}
}}

pub fn build({build_params}) -> (s: QState)
    requires
        query_pre({build_pre}),
{build_scan_req}    ensures
        s.inv(),
        s.db() == (QDb {{ {qdb_init} }}),
{{
{BUILD_START}
{BUILD_END}
}}

pub fn execute(s: &QState{run_params}) -> (res: {ret})
    requires
        s.inv(),
    ensures
        query_post({db_tables}{param_names}, res),
{{
// AGENT_EDIT_START
// AGENT_EDIT_END
}}"""
    return spec_rs[: m.start()] + block + spec_rs[m.end() :]


def contract(spec_rs: str) -> Contract:
    """Tables, runtime parameters and result type of a stateful spec (read back from ``build`` and ``execute``)."""
    b = re.search(r"pub fn build\(([^)]*)\) -> \(s: QState\)", spec_rs)
    e = re.search(r"pub fn execute\(s: &QState((?:, [^)]*)?)\) -> \(res: ([^\n]*)\)\n    requires", spec_rs)
    if b is None or e is None:
        raise ValueError("not a stateful spec: build/execute signatures missing")
    tables = []
    scans = []
    for part in _split_top(b.group(1)):
        name, _, ty = part.partition(":")
        if ty.strip().startswith("&Scan_"):
            scans.append((name.strip(), ty.strip()[1:]))
        else:
            tables.append((name.strip(), ty.strip()))
    params = []
    for part in _split_top(e.group(1).lstrip(", ")):
        name, _, ty = part.partition(":")
        params.append((name.strip(), ty.strip()))
    from declarative_spec.decline import DECLINE_MARKER_STATEFUL

    ret = e.group(2).strip()
    declines = DECLINE_MARKER_STATEFUL in spec_rs
    if declines and not (ret.startswith("Option<") and ret.endswith(">")):
        raise ValueError(f"a declining stateful spec's execute must return Option<..>, got {ret}")
    return Contract(tables=tables, params=params, ret=ret, declines=declines, scans=tuple(scans))


_EXECUTE = re.compile(
    r"pub fn execute\((?P<params>s: &QState[^)]*)\) -> \(res: (?P<ret>[^\n]*)\)\n"
    r"    requires\n        s\.inv\(\),\n"
    r"    ensures\n        query_post\((?P<args>[^\n]*), res\),\n"
)
_EXECUTE_DECLINE = re.compile(
    r"// LEMMA_DECLINE: [^\n]*\npub fn execute\((?P<params>s: &QState[^)]*)\) -> \(res: Option<(?P<ret>[^\n]*)>\)\n"
    r"    requires\n        s\.inv\(\),\n"
    r"    ensures\n        res matches Some\(res\) ==> query_post\((?P<args>[^\n]*), res\),\n"
)


def wrap_decline(spec_rs: str) -> str:
    """lemma.toml assumptions = false on a stateful spec: ``execute`` returns ``Option<T>`` and ensures
    ``res matches Some(res) ==> query_post(.., res)``; ``None`` declines (``decline.py``). ``query_pre``, ``query_post`` and ``build``
    are unchanged: ``query_post`` stays the contract on the value a ``Some`` carries, as ``run_query_ok`` is for ``run_query``.
    ``build`` cannot decline (it only makes the state; a body that cannot answer declines from ``execute``)."""
    from declarative_spec.decline import DECLINE_MARKER_STATEFUL, is_decline_spec

    if is_decline_spec(spec_rs):
        raise ValueError("the spec already declines")
    m = _EXECUTE.search(spec_rs)
    if m is None:
        raise DeclarativeUnsupported("stateful: no execute contract of the expected form in the spec")
    new = (
        f"{DECLINE_MARKER_STATEFUL}\n"
        f"pub fn execute({m.group('params')}) -> (res: Option<{m.group('ret')}>)\n"
        "    requires\n        s.inv(),\n"
        f"    ensures\n        res matches Some(res) ==> query_post({m.group('args')}, res),\n"
    )
    return spec_rs[: m.start()] + new + spec_rs[m.end() :]


def unwrap_decline(spec_rs: str) -> str:
    """The inverse of :func:`wrap_decline` (for readers that classify a spec by its contract, like ``decline.unwrap_option``)."""
    m = _EXECUTE_DECLINE.search(spec_rs)
    if m is None:
        raise ValueError("a declining stateful spec without its execute contract")
    old = (
        f"pub fn execute({m.group('params')}) -> (res: {m.group('ret')})\n"
        "    requires\n        s.inv(),\n"
        f"    ensures\n        query_post({m.group('args')}, res),\n"
    )
    return spec_rs[: m.start()] + old + spec_rs[m.end() :]


def runtime_rs(spec_rs: str) -> str:
    """The fixed, verified host runtime: one state, tagged with the data version it was built from.

    ``refresh`` builds from the tables it is given and records the version; ``execute_at`` answers only from a state built
    at the version asked for (``None`` otherwise), so an answer from another version's state cannot be returned.
    """
    c = contract(spec_rs)
    build_params = ", ".join([f"{n}: {s}" for n, s in c.tables] + [f"{n}: &{s}" for n, s in c.scans])
    build_pre = ", ".join(f"&{n}" for n, _s in c.tables)
    build_args = ", ".join([n for n, _s in c.tables] + [n for n, _s in c.scans])
    # agent scans: the handle scans exactly the table refresh is given (the same requires build has)
    scan_req = "".join(f"            {_scan_full_fn(s)}({n}) == {_scan_table(n, c.tables)},\n" for n, s in c.scans)
    qdb_init = ", ".join(f"{n}: {n}" for n, _s in c.tables)
    run_params = "".join(f", {n}: {t}" for n, t in c.params)
    param_names = "".join(f", {n}" for n, _t in c.params)
    db_tables = ", ".join(f"&st.db().{n}" for n, _s in c.tables)
    # A declining execute (assumptions = false): Some(None) is its decline; None still means "no state built at this version".
    answered = "(Some(Some(r)), Some(st))" if c.declines else "(Some(r), Some(st))"
    return f"""
// HOST RUNTIME (fixed, verified): the state and the data version it was built from. Trusted outside Verus: that the caller
// passes the version of the tables it hands to `refresh`, and a new version whenever the data changes.
pub struct QRuntime {{
    pub version: u64,
    pub state: Option<QState>,
}}

impl QRuntime {{
    pub open spec fn ok(&self) -> bool {{
        match self.state {{
            Some(st) => st.inv(),
            None => true,
        }}
    }}

    pub fn new() -> (r: QRuntime)
        ensures
            r.ok(),
            r.state is None,
    {{
        QRuntime {{ version: 0, state: None }}
    }}

    pub fn is_current(&self, version: u64) -> (b: bool)
        ensures
            b <==> (self.state is Some && self.version == version),
    {{
        self.state.is_some() && self.version == version
    }}

    pub fn refresh(&mut self, version: u64, {build_params})
        requires
            query_pre({build_pre}),
{scan_req}        ensures
            final(self).ok(),
            final(self).version == version,
            match final(self).state {{
                Some(st) => st.db() == (QDb {{ {qdb_init} }}),
                None => false,
            }},
    {{
        let st = build({build_args});
        self.state = Some(st);
        self.version = version;
    }}

    pub fn execute_at(&self, version: u64{run_params}) -> (res: Option<{c.ret}>)
        requires
            self.ok(),
        ensures
            res is Some <==> (self.state is Some && self.version == version),
            match (res, self.state) {{
                {answered} => query_post({db_tables}{param_names}, r),
                _ => true,
            }},
    {{
        match &self.state {{
            Some(st) => {{
                if self.version == version {{
                    Some(execute(st{param_names}))
                }} else {{
                    None
                }}
            }}
            None => None,
        }}
    }}
}}
"""


def _scan_full_fn(scan_struct: str) -> str:
    return "scan_full_" + scan_struct.removeprefix("Scan_")


def _scan_table(handle: str, tables: list[tuple[str, str]]) -> str:
    """The table parameter a scan handle belongs to (agent_scan.py names it ``<table parameter>_scan``)."""
    name = handle.removesuffix("_scan")
    if name not in {n for n, _s in tables}:
        raise ValueError(f"scan handle {handle} names no table parameter")
    return name
