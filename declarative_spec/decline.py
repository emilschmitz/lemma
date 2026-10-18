"""No data assumptions (lemma.toml ``assumptions = false``, the default since 2026-10-17): ``run_query`` may DECLINE.

The owner's decision follows JetStream (arXiv 2610.20527): the spec is stated over exact mathematical integers and the
loaded columns, with no row, value, dictionary-size or unique-key caps. An accelerated program cannot always compute
that exact answer in machine integers, so it may decline instead: ``run_query`` returns ``Option<T>`` where ``T`` is the
result type the spec had before, and its contract is

    ensures res matches Some(res) ==> run_query_ok(<params>, res)

where the spec fn ``run_query_ok`` is the conjunction of the old ``ensures`` clauses. ``None`` is a decline: it promises nothing and proves nothing wrong. When to decline
(for example a checked addition that overflowed) is the body's choice: it decides coverage and speed, never correctness.

A declined query is answered by the reference engine only where a user explicitly asks for that (the extension's
``lemma_route_unproved`` setting, labelled); the experiment harness never substitutes the reference engine's answer: a
decline is reported as ``DECLINED`` (not a success, not a proof failure) and counts as a failed query.

How a decline leaves the compiled program (``assemble.py``):

* the generated ``main`` prints the line ``LEMMA_DECLINED`` and exits with code ``DECLINE_EXIT_CODE`` (3) before any
  result row or latency line; the harness (``pipeline.compile_and_run``) turns that into status ``DECLINED``;
* the C ABI an in-database extension links against reports the same outcome as the status ``ABI_STATUS_DECLINED`` (1)
  next to ``ABI_STATUS_OK`` (0); ``ABI_STATUS_ERROR`` (2) is a load or contract failure. The extension may route a
  declined query to the host engine only under its user flag ``lemma_route_unproved`` and must label that answer as
  not produced by the proved program.
"""

from __future__ import annotations

import re

from declarative_spec.parse import DeclarativeUnsupported

DECLINE_MARKER = "// LEMMA_DECLINE: run_query returns None to decline (lemma.toml assumptions = false); Some(res) satisfies run_query_ok above"
DECLINE_LINE = "LEMMA_DECLINED"
DECLINE_EXIT_CODE = 3
ABI_STATUS_OK = 0
ABI_STATUS_DECLINED = 1
ABI_STATUS_ERROR = 2
STATUS_DECLINED = "DECLINED"

_SIG = re.compile(r"pub fn run_query\((?P<params>[^)]*)\) -> \(res: (?P<ty>[^\n]*)\)\n")
_BINDERS = ("forall", "exists", "choose")


def is_decline_spec(spec: str) -> bool:
    """The spec was emitted with ``assumptions = false``: its ``run_query`` returns ``Option`` (None = decline)."""
    return DECLINE_MARKER in spec


def result_type(spec: str) -> str | None:
    """The result type of ``run_query`` without the decline ``Option`` (the type a ``Some`` carries)."""
    m = _SIG.search(spec)
    if m is None:
        return None
    ty = m.group("ty")
    if is_decline_spec(spec):
        if not (ty.startswith("Option<") and ty.endswith(">")):
            raise ValueError(f"a decline spec's run_query must return Option<..>, got {ty}")
        return ty[len("Option<") : -1]
    return ty


def split_clauses(text: str) -> list[str]:
    """The comma-separated clauses of an ``ensures`` list (top level only: not inside brackets or a quantifier's ``|..|`` binders)."""
    clauses: list[str] = []
    depth = 0
    start = 0
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                raise DeclarativeUnsupported("unbalanced ensures clause")
        elif ch == "|" and re.search(r"\b(?:" + "|".join(_BINDERS) + r")\s*$", text[:i]):
            close = text.find("|", i + 1)
            if close == -1:
                raise DeclarativeUnsupported("unterminated quantifier binder in ensures")
            i = close + 1
            continue
        elif ch == "," and depth == 0:
            clauses.append(text[start:i])
            start = i + 1
        i += 1
    if depth != 0 or in_string:
        raise DeclarativeUnsupported("unbalanced ensures clause")
    clauses.append(text[start:])
    return [c.strip() for c in clauses if c.strip()]


CONTRACT_FN = "run_query_ok"
_OK_FN = re.compile(r"pub open spec fn run_query_ok\((?P<params>[^)]*), res: (?P<ty>[^\n]*)\) -> bool \{\n(?P<body>.*?)\n\}\n\n", re.DOTALL)


def _param_names(params: str) -> list[str]:
    names = []
    for part in split_clauses(params):
        name, sep, _ty = part.partition(":")
        if not sep:
            raise DeclarativeUnsupported(f"run_query parameter without a type: {part}")
        names.append(name.strip())
    return names


def wrap_option(spec: str) -> str:
    """``spec`` with ``run_query`` returning ``Option<T>``: ``Some(res)`` satisfies the old contract, ``None`` declines.

    The old ``ensures`` clauses move, byte for byte, into ``pub open spec fn run_query_ok(<run_query's parameters>, res: T)`` (their
    conjunction), and ``run_query`` ensures ``res matches Some(res) ==> run_query_ok(.., res)``. The spec fn keeps the postcondition a ground
    term for the solver: a body proves the old clauses about its vector and returns ``Some`` of it, with no fact about the Option to add."""
    if is_decline_spec(spec):
        raise ValueError("the spec already declines")
    if spec.count("pub fn run_query(") != 1:
        raise DeclarativeUnsupported("a decline spec needs exactly one run_query")
    if re.search(rf"\b{CONTRACT_FN}\b", spec):
        raise DeclarativeUnsupported(f"the spec already uses the name {CONTRACT_FN}")
    m = _SIG.search(spec)
    if m is None:
        raise DeclarativeUnsupported("run_query has no `-> (res: T)` result")
    head = spec[: m.start()]
    rest = spec[m.end() :]
    ens_at = rest.find("    ensures\n")
    body_at = rest.find("\n{\n")
    if ens_at == -1 or body_at == -1 or body_at < ens_at:
        raise DeclarativeUnsupported("run_query has no ensures clause")
    before_ens = rest[: ens_at + len("    ensures\n")]
    clauses = split_clauses(rest[ens_at + len("    ensures\n") : body_at])
    if not clauses:
        raise DeclarativeUnsupported("run_query has an empty ensures")
    params, ty = m.group("params"), m.group("ty")
    args = ", ".join(_param_names(params))
    body = "\n".join(f"    &&& ({c})" for c in clauses)
    contract = f"pub open spec fn {CONTRACT_FN}({params}, res: {ty}) -> bool {{\n{body}\n}}\n\n"
    sig = f"{DECLINE_MARKER}\npub fn run_query({params}) -> (res: Option<{ty}>)\n"
    ensures = f"        res matches Some(res) ==> {CONTRACT_FN}({args}, res),"
    return head + contract + sig + before_ens + ensures + rest[body_at:]


def unwrap_option(spec: str) -> str:
    """The inverse of ``wrap_option`` (up to the whitespace between ``ensures`` clauses): the contract on the plain result type, as the
    spec would state it with data assumptions minus the caps. For readers that classify a spec by its ``ensures`` (the prompt's recipe)."""
    if not is_decline_spec(spec):
        return spec
    ok = _OK_FN.search(spec)
    m = _SIG.search(spec)
    if ok is None or m is None:
        raise ValueError("a decline spec without its run_query_ok contract")
    clauses = [re.sub(r"^    &&& \((.*)\)$", r"\1", line, flags=re.DOTALL) for line in re.split(r"\n(?=    &&& )", ok.group("body"))]
    ty = result_type(spec)
    rest = spec[m.end() :]
    ens_at = rest.find("    ensures\n")
    body_at = rest.find("\n{\n")
    unwrapped_sig = f"pub fn run_query({m.group('params')}) -> (res: {ty})\n"
    tail = rest[: ens_at + len("    ensures\n")] + "        " + ",\n        ".join(clauses) + "," + rest[body_at:]
    head = spec[: ok.start()] + spec[ok.end() : m.start()]
    head = head.replace(DECLINE_MARKER + "\n", "")
    return head + unwrapped_sig + tail


def prompt_paragraph() -> str:
    """The one factual paragraph of the agent prompt (only with ``assumptions = false``)."""
    return (
        "## Declining (no data assumptions)\n\n"
        "The spec states the exact answer over mathematical integers and makes no assumption about the data: no row-count, "
        "value, dictionary-size or unique-key caps (`valid_cols_*` only relates column lengths and dictionary codes). "
        "`run_query` returns `Option<..>`: `Some(res)` must satisfy `run_query_ok(.., res)` (the conjunction of the result's "
        "contract), and `None` declines the query "
        "(it is always allowed and proves nothing). A run whose `run_query` returns `None` on the measured data is reported "
        "as DECLINED: it is neither a success nor a proof failure, the host never substitutes another engine's answer, and "
        "in experiments a declined query counts as a failed query.\n"
    )


def enabled() -> bool:
    """True when the spec makes no data assumptions and ``run_query`` may decline: lemma.toml ``assumptions = false`` (the default)."""
    import lemma_config

    return not lemma_config.assumptions_enabled()


def catalog_problems(catalog) -> list[str]:
    """What ``catalog`` claims beyond nullability (empty: the catalog is structural, usable with ``assumptions = false``).

    Nullability is not a data assumption: a column that holds a NULL is loaded with a validity vector and one without is
    refused by the exporter, so the loaded columns are always the data. Every other field is a cap or a key claim."""
    if catalog is None:
        return []
    from research_loop.table_assumptions import ColumnAssumption

    found: list[str] = []
    for name in ("max_rows", "max_rows_cube", "max_rows_4", "max_cell_u64", "max_native_u32", "max_string_len"):
        if getattr(catalog, name) is not None:
            found.append(f"catalog {name}")
    if catalog.join_caps:
        found.append("join caps")
    for table, ta in catalog.tables.items():
        if ta.max_rows is not None:
            found.append(f"{table} row cap")
        if ta.unique_keys or ta.one_row_per_adsh:
            found.append(f"{table} unique keys")
        for column, ca in ta.columns.items():
            if ca != ColumnAssumption(nullable=ca.nullable, scale=ca.scale):
                found.append(f"{table}.{column} caps")
    return found


def check_catalog(catalog) -> None:
    """Loud when ``assumptions = false`` and ``catalog`` carries data assumptions (a package passed where none may be used)."""
    if not enabled():
        return
    found = catalog_problems(catalog)
    if found:
        raise ValueError(
            "lemma.toml assumptions = false (the default since 2026-10-17): the spec makes no data assumptions, but the catalog "
            f"passed to the emitter claims {', '.join(found[:6])}{' ...' if len(found) > 6 else ''}. Pass a structural catalog "
            "(nullability only), or set assumptions = true for the UNMAINTAINED assumption-package path."
        )
