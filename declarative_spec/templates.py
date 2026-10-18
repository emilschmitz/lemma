"""Query templates (lemma.toml [sql] templates): a query's constants become runtime PARAMETERS of the spec and of ``run_query``.

A template is DuckDB SQL with named placeholders ``$name`` (DuckDB's own prepared-statement syntax, so the reference engine runs
the same text with the values bound) and ONE header comment that declares every parameter's SQL type::

    -- params: day DATE, disc DECIMAL(15,2), qty BIGINT, segment VARCHAR
    SELECT SUM(x) AS s FROM t WHERE d >= $day AND p < $disc AND q < $qty AND seg = $segment

Without the header nothing here applies (the SQL is emitted exactly as before). With the header and the switch off the
emitter refuses loudly.

Where a parameter may stand: one side of ``column <op> $p`` (``= <> < <= > >=``) or a bound of ``column BETWEEN $a AND $b``,
the column a base-table column of the parameter's type (BIGINT: integer column; DATE: DATE column; DECIMAL(p,s): DECIMAL
column of the same scale s; VARCHAR: string column, ``=`` and ``<>`` only). Anything else is refused.

How the spec is made (no new trusted item, no assume): the template is emitted twice by the unchanged emitter, once with
every parameter replaced by a literal near the low end of its range and once near the high end. The two specs must be the
same text except at the places where the literal itself is printed; those places become the parameter
(``(param_<name> as int)`` for a number, ``param_<name>@`` for a string). Any other difference (a constant folded with the
literal, a different shape for a different value) refuses the template. The parameter is then threaded as an argument
through every spec/proof function that reads it (and every call of those), and ``run_query`` gets one argument per
parameter (``i64``; DATE ``i32`` day number; DECIMAL ``i64`` scaled integer; VARCHAR ``&String``) with a ``requires`` that
the value lies in the column's catalog range (the same bounds ``valid_cols`` states of the column). The generated ``main``
reads the values from its command line and checks that range with ``assert!`` before the call.
"""

from __future__ import annotations

import calendar
import datetime as dt
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from declarative_spec.parse import DeclarativeUnsupported

_HEADER = re.compile(r"^[ \t]*--[ \t]*params[ \t]*:(.*)$", re.MULTILINE | re.IGNORECASE)
_DECL = re.compile(r"\s*([A-Za-z_]\w*)\s+(BIGINT|DATE|VARCHAR|DECIMAL\s*\(\s*(\d+)\s*,\s*(\d+)\s*\))\s*(?:,|$)", re.IGNORECASE)
_EPOCH = dt.date(1970, 1, 1)
_DATE_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DAY_MIN = (dt.date(1, 1, 1) - _EPOCH).days
_DAY_MAX = (dt.date(9999, 12, 31) - _EPOCH).days
_I64 = (-(2**63), 2**63 - 1)
_I32 = (-(2**31), 2**31 - 1)
PARAM_LINE = re.compile(r"^// PARAM (\w+) (i64|i32|String) (-?\d+|-) (-?\d+|-)$", re.MULTILINE)


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # BIGINT | DATE | DECIMAL | VARCHAR
    precision: int = 0
    scale: int = 0

    @property
    def ident(self) -> str:
        return f"param_{self.name}"

    @property
    def rust(self) -> str:
        return {"BIGINT": "i64", "DATE": "i32", "DECIMAL": "i64", "VARCHAR": "String"}[self.kind]

    @property
    def spec_arg_type(self) -> str:
        return "&String" if self.kind == "VARCHAR" else self.rust

    @property
    def sql_type(self) -> str:
        return f"DECIMAL({self.precision},{self.scale})" if self.kind == "DECIMAL" else self.kind


@dataclass(frozen=True)
class Template:
    text: str  # the SQL as written, header included
    body: str  # the SQL without the header line
    params: tuple[Param, ...]

    def param(self, name: str) -> Param:
        for p in self.params:
            if p.name == name:
                return p
        raise KeyError(name)


# ---- parsing ---------------------------------------------------------------------------------------------------------


def _placeholders(sql: str) -> list[tuple[int, int, str]]:
    """``(start, end, name)`` of every ``$name`` outside string literals, quoted identifiers and comments."""
    out: list[tuple[int, int, str]] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
        elif ch == "$":
            m = re.compile(r"\$([A-Za-z_]\w*)").match(sql, i)
            if m is None:
                raise DeclarativeUnsupported("a `$` that is not a named parameter `$name` (positional parameters are not templates)")
            out.append((m.start(), m.end(), m.group(1)))
            i = m.end()
        else:
            i += 1
    return out


def parse_template(sql: str) -> Template | None:
    """The template, or None when the SQL has no ``-- params:`` header (then it is ordinary fixed-constant SQL)."""
    headers = list(_HEADER.finditer(sql))
    if not headers:
        return None
    from declarative_spec import sql_switches

    if not sql_switches.templates():
        raise DeclarativeUnsupported("the SQL declares query parameters (`-- params:`) but lemma.toml [sql] templates is off")
    if len(headers) > 1:
        raise DeclarativeUnsupported("more than one `-- params:` header")
    decl_text = headers[0].group(1).strip()
    params: list[Param] = []
    pos = 0
    while pos < len(decl_text):
        m = _DECL.match(decl_text, pos)
        if m is None:
            raise DeclarativeUnsupported(
                f"cannot read the parameter declaration {decl_text[pos:]!r}: write `name TYPE, ...` with TYPE one of BIGINT, DATE, DECIMAL(p,s), VARCHAR"
            )
        kind = m.group(2).upper()
        if kind.startswith("DECIMAL"):
            precision, scale = int(m.group(3)), int(m.group(4))
            if not 1 <= precision <= 18 or not 0 <= scale <= precision:
                raise DeclarativeUnsupported(f"parameter {m.group(1)}: DECIMAL({precision},{scale}) is not a 64-bit scaled integer (precision 1..18)")
            params.append(Param(m.group(1), "DECIMAL", precision, scale))
        else:
            params.append(Param(m.group(1), kind))
        pos = m.end()
    if not params:
        raise DeclarativeUnsupported("the `-- params:` header declares no parameter")
    folded = [p.name.casefold() for p in params]
    if len(set(folded)) != len(folded):
        raise DeclarativeUnsupported("a parameter is declared twice")
    body = sql[: headers[0].start()] + sql[headers[0].end() :]
    used = {name for _s, _e, name in _placeholders(body)}
    declared = {p.name for p in params}
    if used - declared:
        raise DeclarativeUnsupported(f"undeclared parameter(s) {sorted(used - declared)}: declare each in the `-- params:` header")
    if declared - used:
        raise DeclarativeUnsupported(f"declared parameter(s) {sorted(declared - used)} are not used in the query")
    return Template(text=sql, body=body, params=tuple(params))


# ---- values ----------------------------------------------------------------------------------------------------------


def _date(text: str) -> dt.date:
    if not _DATE_TEXT.match(text):
        raise ValueError(f"{text!r} is not a date YYYY-MM-DD")
    return dt.date.fromisoformat(text)


def spec_value(param: Param, text: str) -> int | str:
    """The value as ``run_query`` receives it: BIGINT as is, DATE the day number since 1970-01-01, DECIMAL value * 10**scale."""
    if param.kind == "VARCHAR":
        return str(text)
    if param.kind == "BIGINT":
        if not re.fullmatch(r"-?\d+", str(text)):
            raise ValueError(f"parameter {param.name}: {text!r} is not an integer")
        value = int(text)
        if not _I64[0] <= value <= _I64[1]:
            raise ValueError(f"parameter {param.name}: {text} does not fit BIGINT")
        return value
    if param.kind == "DATE":
        return (_date(str(text)) - _EPOCH).days
    try:
        dec = Decimal(str(text))
    except InvalidOperation as exc:
        raise ValueError(f"parameter {param.name}: {text!r} is not a decimal") from exc
    if not re.fullmatch(r"-?\d+(\.\d+)?", str(text)):
        raise ValueError(f"parameter {param.name}: {text!r} is not a plain decimal")
    sign, digits, exponent = dec.as_tuple()
    assert isinstance(exponent, int)
    if -exponent > param.scale:
        raise ValueError(f"parameter {param.name}: {text} has more than {param.scale} fractional digits")
    scaled = (-1 if sign else 1) * int("".join(map(str, digits)) or "0") * 10 ** (exponent + param.scale)
    if abs(scaled) >= 10**param.precision:
        raise ValueError(f"parameter {param.name}: {text} does not fit {param.sql_type}")
    return scaled


def text_of(param: Param, value: int | str) -> str:
    """Inverse of :func:`spec_value`: the canonical SQL-level text of a value."""
    if param.kind == "VARCHAR":
        return str(value)
    value = int(value)
    if param.kind == "BIGINT":
        return str(value)
    if param.kind == "DATE":
        return (_EPOCH + dt.timedelta(days=value)).isoformat()
    if param.scale == 0:
        return str(value)
    sign = "-" if value < 0 else ""
    whole, frac = divmod(abs(value), 10**param.scale)
    return f"{sign}{whole}.{frac:0{param.scale}d}"


def sql_literal(param: Param, text: str) -> str:
    """The SQL literal for the value (what a user would have written in place of the placeholder)."""
    value = spec_value(param, text)  # validates
    if param.kind == "VARCHAR":
        return "'" + str(value).replace("'", "''") + "'"
    if param.kind == "DATE":
        return f"DATE '{text_of(param, value)}'"
    shown = text_of(param, value)
    return f"({shown})" if shown.startswith("-") else shown


def python_value(param: Param, text: str) -> int | dt.date | Decimal | str:
    """The value as an exact Python object (int, date, Decimal, str): what a reference engine binds to ``$name``."""
    spec_value(param, text)  # validates
    if param.kind == "BIGINT":
        return int(text)
    if param.kind == "DATE":
        return _date(text)
    if param.kind == "DECIMAL":
        return Decimal(text)
    return str(text)


def python_values(template: Template, binding: Mapping[str, str]) -> dict[str, object]:
    _check_binding(template, binding)
    return {p.name: python_value(p, binding[p.name]) for p in template.params}


def binary_args(template: Template, binding: Mapping[str, str]) -> list[str]:
    """The command line of the compiled binary: one value per parameter, in declaration order, as ``run_query`` receives it."""
    _check_binding(template, binding)
    return [str(spec_value(p, binding[p.name])) for p in template.params]


def _check_binding(template: Template, binding: Mapping[str, str]) -> None:
    names = {p.name for p in template.params}
    if set(binding) != names:
        raise ValueError(f"binding {sorted(binding)} does not name exactly the parameters {sorted(names)}")


def instantiate(template: Template, binding: Mapping[str, str]) -> str:
    """The template body with every placeholder replaced by the literal of its value (fixed-constant SQL)."""
    _check_binding(template, binding)
    out: list[str] = []
    last = 0
    for start, end, name in _placeholders(template.body):
        out.append(template.body[last:start])
        out.append(sql_literal(template.param(name), binding[name]))
        last = end
    out.append(template.body[last:])
    return "".join(out)


# ---- positions and ranges --------------------------------------------------------------------------------------------


def _unparen(node):
    from sqlglot import exp

    while isinstance(node, exp.Paren):
        node = node.this
    return node


def param_ranges(template: Template, schema: Mapping, catalog) -> dict[str, tuple[int, int] | None]:
    """Where each parameter stands, checked, and the range of its value: the catalog range of the column it is compared with
    (the intersection over several places). None for a VARCHAR parameter (a string is compared, not bounded)."""
    import sqlglot
    from sqlglot import exp

    from declarative_spec.emit import _cell_inclusive_max
    from declarative_spec.schema_types import SchemaModel

    try:
        tree = sqlglot.parse_one(template.body, read="duckdb")
    except sqlglot.errors.SqlglotError as exc:
        raise DeclarativeUnsupported(f"template does not parse: {exc}") from exc
    aliases: dict[str, str] = {}
    first_table = None
    for table in tree.find_all(exp.Table):
        first_table = first_table or table.name
        aliases[table.alias_or_name.casefold()] = table.name
    if first_table is None:
        raise DeclarativeUnsupported("template reads no table")
    model = SchemaModel.from_caller(dict(schema), first_table)
    ranges: dict[str, tuple[int, int] | None] = {}
    comparisons = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
    for ph in tree.find_all(exp.Placeholder):
        name = str(ph.name)
        param = template.param(name)
        node, parent = ph, ph.parent
        while isinstance(parent, exp.Paren):
            node, parent = parent, parent.parent
        where = parent.sql() if parent is not None else name
        if isinstance(parent, comparisons):
            other = parent.expression if parent.this is node else parent.this
        elif isinstance(parent, exp.Between) and parent.this is not node and not parent.args.get("symmetric"):
            other = parent.this
        else:
            raise DeclarativeUnsupported(
                f"parameter ${name} in `{where[:80]}`: a parameter may only be one side of `column <op> $p` or a bound of `column BETWEEN $a AND $b`"
            )
        other = _unparen(other)
        if not isinstance(other, exp.Column):
            raise DeclarativeUnsupported(f"parameter ${name} in `{where[:80]}` is not compared with a plain column")
        if param.kind == "VARCHAR" and not isinstance(parent, (exp.EQ, exp.NEQ)):
            raise DeclarativeUnsupported(f"VARCHAR parameter ${name} in `{where[:80]}`: only `=` and `<>` are parameterized")
        table = _column_table(other, aliases, model)
        orig, info = model.lookup_column(table, other.name)
        _check_type(param, info, f"{table}.{orig}")
        if param.kind == "VARCHAR":
            ranges[name] = None
            continue
        inc = _cell_inclusive_max(catalog, table, orig, info)
        if inc is None:
            raise DeclarativeUnsupported(f"parameter ${name}: column {table}.{orig} has no value bound")
        lo, hi = (-inc if info.signed else 0), inc
        rust_lo, rust_hi = _I32 if param.kind == "DATE" else _I64
        lo, hi = max(lo, rust_lo), min(hi, rust_hi)
        if param.kind == "DATE":
            lo, hi = max(lo, _DAY_MIN), min(hi, _DAY_MAX)
        if param.kind == "DECIMAL":
            lo, hi = max(lo, -(10**param.precision) + 1), min(hi, 10**param.precision - 1)
        old = ranges.get(name)
        if old is not None:
            lo, hi = max(lo, old[0]), min(hi, old[1])
        ranges[name] = (lo, hi)
    return ranges


def _column_table(column, aliases: dict[str, str], model) -> str:
    qualifier = column.table
    if qualifier:
        table = aliases.get(qualifier.casefold())
        if table is None or table.casefold() not in model.tables:
            raise DeclarativeUnsupported(f"parameter compared with {column.sql()}: {qualifier!r} is not a base table of the schema")
        return table
    hits = sorted({t for t in aliases.values() if t.casefold() in model.tables and column.name.casefold() in model.tables[t.casefold()]})
    if len(hits) != 1:
        raise DeclarativeUnsupported(f"parameter compared with column {column.name!r}: it is {'ambiguous' if hits else 'not a base-table column'}")
    return hits[0]


def _check_type(param: Param, info, label: str) -> None:
    ok = {
        "BIGINT": info.precision is None and not info.is_date and info.exec_rust not in ("String", "bool", "f64"),
        "DATE": info.is_date,
        "DECIMAL": info.precision is not None and info.scale == param.scale,
        "VARCHAR": info.exec_rust == "String",
    }[param.kind]
    if not ok:
        raise DeclarativeUnsupported(f"parameter ${param.name} {param.sql_type} is compared with {label} of type {info.sql_type}")


# ---- emission ----------------------------------------------------------------------------------------------------------

_FRACTIONS = (0.0137, 0.0291, 0.0419, 0.0573)


def _sentinels(template: Template, ranges: dict, attempt: int) -> list[dict[str, int | str]]:
    """Three bindings: every number near the low end, near the high end and near the middle of its range (all distinct, no
    0 or 1), every string a distinct marker word."""
    used: set[int] = set()
    sets: list[dict[str, int | str]] = [{}, {}, {}]

    def free(value: int, direction: int) -> int:
        while abs(value) in used or value in (0, 1, -1):
            value += direction
        used.add(abs(value))
        return value

    for k, p in enumerate(template.params):
        if p.kind == "VARCHAR":
            for index, word in enumerate("abc"):
                sets[index][p.name] = f"lmp{word}{k}q{attempt}"
            continue
        lo, hi = ranges[p.name]
        width = hi - lo
        step = max(attempt + 1, int(width * _FRACTIONS[attempt % len(_FRACTIONS)]))
        a, b = free(lo + step, 1), free(hi - step, -1)
        mid = free(lo + width // 2 + step // 3 + 1, 1)
        if not lo <= a < mid < b <= hi:
            raise DeclarativeUnsupported(f"parameter ${p.name}: the range [{lo}, {hi}] is too narrow to parameterize")
        sets[0][p.name], sets[1][p.name], sets[2][p.name] = a, b, mid
    return sets


def _marker(k: int) -> str:
    return f"__LEMMA_PARAM_{k}__"


def _mark(spec: str, template: Template, values: Mapping[str, int | str]) -> tuple[str, list[int]]:
    """Replace every printed occurrence of each parameter's value by its marker; also return the count per parameter."""
    from declarative_spec.literals import rust_string_literal

    counts: list[int] = []
    for k, p in enumerate(template.params):
        value = values[p.name]
        if p.kind == "VARCHAR":
            pattern = re.escape(rust_string_literal(str(value))) + "@"
        else:
            n = abs(int(value))
            if int(value) < 0:
                pattern = rf"\(\s*-\s*{n}(?:int)?\s*\)|-\s*{n}(?:int)?(?![\w.])"
            else:
                pattern = rf"(?<![\w.]){n}(?:int)?(?![\w.])"
        spec, count = re.subn(pattern, _marker(k), spec)
        counts.append(count)
    return spec, counts


def emit_template(template: Template, schema, catalog, core: Callable[[str, object, object], str]) -> str:
    """The parameterized spec of ``template`` (see the module docstring). ``core`` is the fixed-constant emitter."""
    from declarative_spec.emit import with_sql_comment

    ranges = param_ranges(template, schema, catalog)
    failure = ""
    for attempt in range(len(_FRACTIONS)):
        marked: list[tuple[str, list[int]]] = []
        for values in _sentinels(template, ranges, attempt):
            spec_v = core(instantiate(template, {p.name: text_of(p, values[p.name]) for p in template.params}), schema, catalog)
            clash = re.search(r"(?<![\w.])param_\w", spec_v) or re.search(r"__LEMMA_PARAM_", spec_v)
            if clash:
                raise DeclarativeUnsupported(f"the spec already uses the identifier {clash.group(0)!r} the parameters are named with")
            marked.append(_mark(spec_v, template, values))
        missing = [p.name for p, c in zip(template.params, marked[0][1], strict=True) if c == 0]
        if missing:
            raise DeclarativeUnsupported(f"parameter(s) {missing} do not reach the spec as a value")
        if all(m == marked[0] for m in marked):
            break
        other = next(m for m in marked if m != marked[0])
        failure = _first_difference(marked[0][0], other[0]) if other[0] != marked[0][0] else f"the value is printed {marked[0][1]} vs {other[1]} times"
    else:
        raise DeclarativeUnsupported(
            "the spec depends on the parameter value beyond the places the value is printed (a constant folded with it, or a "
            f"different shape for a different value), so it cannot be parameterized: {failure}"
        )
    spec = marked[0][0]
    for k, p in enumerate(template.params):
        spec = spec.replace(_marker(k), f"{p.ident}@" if p.kind == "VARCHAR" else f"({p.ident} as int)")
    spec = thread_params(spec, template.params)
    spec = _with_param_requires(spec, template.params, ranges)
    return with_sql_comment(spec, template.text)


def _first_difference(a: str, b: str) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"`...{a[max(0, i - 40):i + 40]}...` vs `...{b[max(0, i - 40):i + 40]}...`"
    return "the two texts differ in length"


# ---- threading the parameters through the spec functions ----------------------------------------------------------------

_QUALS = r"(?:pub(?:\([^)]*\))?\s+)?(?:(?:open|closed|uninterp|exec|spec|proof|broadcast)\s+)*"
_FN_START = re.compile(rf"^{_QUALS}fn\s+(\w+)", re.MULTILINE)
_ITEM_START = re.compile(
    rf"^(?:#\[|{_QUALS}(?:fn|struct|enum|const|static|impl|type|trait|use|mod)\b|// HOST_LEMMAS_|// AGENT_HELPERS_)", re.MULTILINE
)


def _match_paren(text: str, open_at: int) -> int:
    """Index of the ``)`` matching the ``(`` at ``open_at``; string literals are skipped."""
    depth, i = 0, open_at
    while i < len(text):
        ch = text[i]
        if ch == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise DeclarativeUnsupported("unbalanced parentheses in the generated spec")


def _host_region(spec: str) -> tuple[int, int]:
    start, end = spec.find("// HOST_LEMMAS_START"), spec.find("// HOST_LEMMAS_END")
    return (start, end) if 0 <= start < end else (-1, -1)


def _fn_segments(spec: str) -> dict[str, tuple[int, int]]:
    """Top-level function items outside the host lemma region: name -> (start, end) of its text."""
    host = _host_region(spec)
    boundaries = sorted({m.start() for m in _ITEM_START.finditer(spec)} | {len(spec)})
    out: dict[str, tuple[int, int]] = {}
    for m in _FN_START.finditer(spec):
        if host[0] <= m.start() < host[1]:
            continue
        name = m.group(1)
        if name in out:
            raise DeclarativeUnsupported(f"the spec defines {name} twice")
        end = next(b for b in boundaries if b > m.start())
        if host[0] > m.start():
            end = min(end, host[0])
        out[name] = (m.start(), end)
    return out


def _call_sites(text: str, name: str) -> list[int]:
    """Indexes of the ``(`` of every call of ``name`` (not its definition)."""
    return [m.end() - 1 for m in re.finditer(rf"(?<![\w.])(?<!fn ){re.escape(name)}\s*(?:::<[^>()]*>)?\(", text)]


def _uses(text: str, param: Param) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(param.ident)}(?!\w)", text) is not None


def thread_params(spec: str, params: Sequence[Param]) -> str:
    """Add each parameter as the last arguments of every function that reads it (directly or through a call), and to every
    call of such a function; ``run_query`` takes all of them."""
    segments = _fn_segments(spec)
    if "run_query" not in segments:
        raise DeclarativeUnsupported("the spec has no run_query")
    need: dict[str, set[str]] = {
        f: {p.name for p in params if _uses(spec[s:e], p)} for f, (s, e) in segments.items()
    }
    need["run_query"] = {p.name for p in params}
    calls = {f: {g for g in segments if g != f and _call_sites(spec[s:e], g)} for f, (s, e) in segments.items()}
    changed = True
    while changed:
        changed = False
        for f in segments:
            for g in calls[f]:
                if not need[g] <= need[f]:
                    need[f] |= need[g]
                    changed = True
    order = [p.name for p in params]
    by_name = {p.name: p for p in params}

    def ordered(f: str) -> list[Param]:
        return [by_name[n] for n in order if n in need[f]]

    host = _host_region(spec)
    inserts: list[tuple[int, str]] = []  # (index of a `)`, text to put before it)

    def add(close: int, items: list[str]) -> None:
        sep = "" if spec[:close].rstrip().endswith(("(", ",")) else ", "
        inserts.append((close, sep + ", ".join(items)))

    for f, (s, _e) in segments.items():
        if not need[f]:
            continue
        head = re.compile(rf"fn\s+{re.escape(f)}\s*(?:<[^>()]*>)?\(").search(spec, s)
        assert head is not None
        add(_match_paren(spec, head.end() - 1), [f"{p.ident}: {p.spec_arg_type}" for p in ordered(f)])
    for g in segments:
        if not need[g] or g == "run_query":
            continue
        for open_at in _call_sites(spec, g):
            if host[0] <= open_at < host[1]:
                raise DeclarativeUnsupported(f"a host lemma calls {g}, which reads a parameter")
            add(_match_paren(spec, open_at), [p.ident for p in ordered(g)])
    for close, text in sorted(inserts, reverse=True):
        spec = spec[:close] + text + spec[close:]
    _check_scoped(spec, params)
    return spec


def _check_scoped(spec: str, params: Sequence[Param]) -> None:
    """Every use of a parameter lies in a function that takes it."""
    segments = _fn_segments(spec)
    covered = [(s, e) for f, (s, e) in segments.items()]
    for p in params:
        for m in re.finditer(rf"(?<![\w.]){re.escape(p.ident)}(?!\w)", spec):
            seg = next(((s, e) for s, e in covered if s <= m.start() < e), None)
            if seg is None or not re.search(rf"(?<![\w.]){re.escape(p.ident)}: ", spec[seg[0] : seg[1]]):
                raise DeclarativeUnsupported(f"parameter {p.name} is used where no function argument carries it")


def _with_param_requires(spec: str, params: Sequence[Param], ranges: Mapping[str, tuple[int, int] | None]) -> str:
    """``requires`` on each numeric parameter's range, and one ``// PARAM name type lo hi`` line per parameter above
    ``run_query`` (the assembler reads them to parse and check the command line)."""
    assert spec.count("pub fn run_query(") == 1
    head, sep, tail = spec.partition("pub fn run_query(")
    sig, req, rest = tail.partition("requires\n")
    if not req:
        raise DeclarativeUnsupported("run_query has no requires")
    conj = ""
    lines = []
    for p in params:
        rng = ranges[p.name]
        if rng is None:
            lines.append(f"// PARAM {p.name} {p.rust} - -")
            continue
        lo, hi = rng
        conj += f"        ({p.ident} as int) >= {lo},\n        ({p.ident} as int) <= {hi},\n"
        lines.append(f"// PARAM {p.name} {p.rust} {lo} {hi}")
    return head + "\n".join(lines) + "\n" + sep + sig + req + conj + rest


def spec_params(spec: str) -> list[tuple[str, str, int | None, int | None]]:
    """``(name, rust type, lo, hi)`` of every ``// PARAM`` line of a spec, in run_query's argument order."""
    return [
        (m.group(1), m.group(2), None if m.group(3) == "-" else int(m.group(3)), None if m.group(4) == "-" else int(m.group(4)))
        for m in PARAM_LINE.finditer(spec)
    ]


# ---- fresh bindings ---------------------------------------------------------------------------------------------------------


def _shift_date(day: dt.date, amount: int, unit: str) -> dt.date:
    """DuckDB's date + INTERVAL: days add days; months/years clamp the day to the end of the target month."""
    if unit == "day":
        return day + dt.timedelta(days=amount)
    months = amount * (12 if unit == "year" else 1)
    if unit not in ("month", "year"):
        raise ValueError(f"date unit {unit!r}: day, month or year")
    total = day.year * 12 + (day.month - 1) + months
    year, month = divmod(total, 12)
    return dt.date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _draw(rule: Mapping, param: Param, rng: random.Random, done: Mapping[str, str]) -> str:
    kind = rule.get("kind")
    if kind == "choice":
        return str(rng.choice(list(rule["values"])))
    if kind == "int_range":
        return str(rng.randint(int(rule["lo"]), int(rule["hi"])))
    if kind == "decimal_range":
        lo, hi = spec_value(param, str(rule["lo"])), spec_value(param, str(rule["hi"]))
        return text_of(param, rng.randint(int(lo), int(hi)))
    if kind == "date_range":
        lo, hi = _date(str(rule["lo"])), _date(str(rule["hi"]))
        unit = rule.get("unit", "day")
        if unit == "day":
            return (lo + dt.timedelta(days=rng.randint(0, (hi - lo).days))).isoformat()
        if unit == "month":
            months = [(y, m) for y in range(lo.year, hi.year + 1) for m in range(1, 13) if lo <= dt.date(y, m, 1) <= hi]
            y, m = rng.choice(months)
            return dt.date(y, m, 1).isoformat()
        if unit == "year":
            years = [y for y in range(lo.year, hi.year + 1) if lo <= dt.date(y, 1, 1) <= hi]
            return dt.date(rng.choice(years), 1, 1).isoformat()
        raise ValueError(f"date_range unit {unit!r}: day, month or year")
    if kind in ("date_shift", "int_shift", "decimal_shift"):
        base = done.get(str(rule["of"]))
        if base is None:
            raise ValueError(f"rule for {param.name} shifts {rule['of']!r}, which has no value yet (list it earlier)")
        if kind == "date_shift":
            return _shift_date(_date(base), int(rule["amount"]), str(rule.get("unit", "day"))).isoformat()
        if kind == "int_shift":
            return str(int(base) + int(rule["amount"]))
        return text_of(param, int(spec_value(param, base)) + int(spec_value(param, str(rule["amount"]))))
    raise ValueError(f"unknown binding rule kind {kind!r} for {param.name}")


def generate_bindings(template: Template, rules: Mapping[str, Mapping], n: int, seed: int) -> list[dict[str, str]]:
    """``n`` bindings drawn with ``random.Random(seed)`` from per-parameter rules (data, e.g. a benchmark's substitution
    rules). A rule is ``{"kind": ...}``: ``choice`` (``values``), ``int_range`` / ``decimal_range`` (``lo``, ``hi``),
    ``date_range`` (``lo``, ``hi``, ``unit`` day | month | year: a day, a first of month or a first of January in the range),
    or a shift of a parameter listed earlier: ``date_shift`` (``of``, ``amount``, ``unit``), ``int_shift`` /
    ``decimal_shift`` (``of``, ``amount``). Every value is checked against its declared type."""
    names = [p.name for p in template.params]
    if set(rules) != set(names):
        raise ValueError(f"rules name {sorted(rules)}, the template declares {sorted(names)}")
    rng = random.Random(seed)
    out: list[dict[str, str]] = []
    for _ in range(n):
        done: dict[str, str] = {}
        for name, rule in rules.items():
            param = template.param(name)
            value = _draw(rule, param, rng, done)
            spec_value(param, value)  # loud on a value outside the type
            done[name] = value
        out.append({name: done[name] for name in names})
    return out
