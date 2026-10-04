"""Emit declarative Verus spec from SQL + schema + catalog assumptions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from declarative_spec.parse import (
    DeclarativeUnsupported,
    GroupCol,
    ParsedQuery,
    parse_declarative_sql,
)
from declarative_spec.schema_types import (
    ColumnTypeInfo,
    KeyKind,
    SchemaModel,
    rust_ident,
)
from research_loop.table_assumptions import (
    CatalogAssumptions,
    TableAssumptions,
    column_abs_sum_exclusive,
    column_assumption_exclusive,
)

# Re-export for callers/tests
__all__ = ["DeclarativeUnsupported", "emit_declarative_spec"]


def _cap_const_name(prefix: str, *parts: str) -> str:
    segs = [re.sub(r"[^a-z0-9_]", "_", p.lower()) for p in parts]
    return f"{prefix}_{'_'.join(segs)}"


def _lookup_table_assumptions(catalog: CatalogAssumptions | None, table: str) -> TableAssumptions | None:
    if catalog is None:
        return None
    hit = catalog.tables.get(table)
    if hit is not None:
        return hit
    folded = table.casefold()
    for name, ta in catalog.tables.items():
        if name.casefold() == folded:
            return ta
    return None


def _host_lemma_region() -> str:
    """Lemma source the agent can call. Assemble replaces this same region."""
    from declarative_spec.trusted_sets import current

    body = current().lemmas_rs(None)
    return "// HOST_LEMMAS_START\n" + body + "\n// HOST_LEMMAS_END"


def _row_cap_inclusive(catalog: CatalogAssumptions | None, table: str) -> int:
    ta = _lookup_table_assumptions(catalog, table)
    if ta is not None and ta.max_rows is not None:
        return ta.max_rows
    if catalog is not None and catalog.max_rows is not None:
        return catalog.max_rows
    from declarative_spec.lemmas import FitRefusal

    raise FitRefusal(f"no row cap for table {table!r}")


def _cell_inclusive_max(
    catalog: CatalogAssumptions | None,
    table: str,
    column: str,
    info: ColumnTypeInfo,
) -> int | None:
    if info.is_float:
        return None
    ta = _lookup_table_assumptions(catalog, table)
    ex = column_assumption_exclusive(column, ta)
    if ex is None and info.cell_exclusive_cap is not None:
        ex = info.cell_exclusive_cap
    if ex is None or ex <= 0:
        return None
    return ex - 1


def _join_col_is_unique(ta: TableAssumptions | None, col: str) -> bool:
    if ta is None:
        return False
    folded = col.casefold()
    for group in ta.unique_keys:
        if len(group) == 1 and group[0].casefold() == folded:
            return True
    return False


def _resolve_group_col(
    g: GroupCol,
    schema: SchemaModel,
    default_table: str | None,
    involved: list[str],
) -> tuple[str, str, ColumnTypeInfo, KeyKind]:
    table = g.table or default_table
    if table is None:
        raise DeclarativeUnsupported("group column requires table qualification in join queries")
    c_orig, info = schema.lookup_column(table, g.column)
    if info.key_kind is None:
        raise DeclarativeUnsupported("float columns cannot be group keys")
    if info.is_float:
        raise DeclarativeUnsupported("float group keys are not supported")
    return table, c_orig, info, info.key_kind


def _int_literal(n: int) -> str:
    if n >= 0:
        return str(n)
    return f"({n})"


def _emit_open_spec_int(name: str, value: int) -> str:
    return f"pub open spec const {name}: int = {_int_literal(value)};"


@dataclass
class _EmitCtx:
    catalog: CatalogAssumptions | None
    lines: list[str]
    consts: list[str]

    def add_const(self, name: str, value: int) -> str:
        self.consts.append(_emit_open_spec_int(name, value))
        return name

    def add_exec_const(self, name: str, value: int) -> str:
        self.consts.append(f"pub const {name}: usize = {value};")
        return name


def _host_hash_key_axiom(rust_ty: str) -> str:
    """Host-owned hash axiom. The agent must not import this; it is an assume."""
    allowed = {
        "bool",
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "usize",
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
        "isize",
    }
    if rust_ty not in allowed:
        return ""
    return (
        "broadcast use vstd::std_specs::hash::"
        f"axiom_{rust_ty}_obeys_hash_table_key_model;"
    )


def _emit_group_count_block(*, seq_ty: str, key_ty: str, elem: str) -> str:
    """`elem` is the spec expression for keys[i] compared to k (e.g. keys[i] or keys[i]@)."""
    elem_j = elem.replace("[i]", "[j]")
    return f"""
pub open spec fn group_count(keys: {seq_ty}, i: int, k: {key_ty}) -> int
    decreases keys.len() - i
{{
    if i < 0 || i >= keys.len() {{
        0
    }} else if {elem} == k {{
        1 + group_count(keys, i + 1, k)
    }} else {{
        group_count(keys, i + 1, k)
    }}
}}

pub proof fn lemma_group_count_le_suffix(keys: {seq_ty}, i: int, k: {key_ty})
    requires
        0 <= i <= keys.len(),
    ensures
        0 <= group_count(keys, i, k) <= keys.len() - i,
    decreases keys.len() - i,
{{
    if i < keys.len() {{
        lemma_group_count_le_suffix(keys, i + 1, k);
    }}
}}

pub proof fn lemma_group_count_witness(keys: {seq_ty}, i: int, k: {key_ty})
    requires
        0 <= i <= keys.len(),
    ensures
        group_count(keys, i, k) > 0 <==> (exists|j: int| i <= j < keys.len() && {elem_j} == k),
    decreases keys.len() - i,
{{
    if i >= keys.len() {{
        assert(group_count(keys, i, k) == 0);
        assert(forall|j: int| i <= j < keys.len() ==> !(#[trigger] {elem_j} == k));
    }} else {{
        lemma_group_count_witness(keys, i + 1, k);
        if {elem} == k {{
            lemma_group_count_le_suffix(keys, i + 1, k);
            assert(group_count(keys, i, k) == 1 + group_count(keys, i + 1, k));
            assert(group_count(keys, i + 1, k) >= 0);
            assert(group_count(keys, i, k) > 0);
            assert(exists|j: int| i <= j < keys.len() && {elem_j} == k) by {{
                assert({elem} == k);
            }};
        }} else {{
            assert({elem} != k);
            assert(group_count(keys, i, k) == group_count(keys, i + 1, k));
            if group_count(keys, i + 1, k) > 0 {{
                let j = choose|j: int| i + 1 <= j < keys.len() && {elem_j} == k;
                assert(i <= j < keys.len() && {elem_j} == k);
            }}
            if exists|j: int| i <= j < keys.len() && {elem_j} == k {{
                let j = choose|j: int| i <= j < keys.len() && {elem_j} == k;
                assert(j != i);
                assert(i + 1 <= j < keys.len() && {elem_j} == k);
                assert(group_count(keys, i + 1, k) > 0);
            }}
        }}
    }}
}}
""".strip()


def _emit_matched_sum_int(
    t_struct: str,
    u_struct: str,
    t_field: str,
    u_field: str,
    sum_field: str,
    *,
    group_on_t: bool,
    sum_on_t: bool,
    group_field: str,
) -> str:
    g_ref = f"t.{group_field}@[i]" if group_on_t else f"u.{group_field}@[j]"
    s_ref = f"t.{sum_field}@[i]" if sum_on_t else f"u.{sum_field}@[j]"
    return f"""
pub open spec fn matched_sum(
    t: &{t_struct},
    u: &{u_struct},
    g: int,
) -> int
    decreases t.n, u.n
{{
    matched_sum_rec(t, u, g, 0, 0)
}}

pub open spec fn matched_sum_rec(
    t: &{t_struct},
    u: &{u_struct},
    g: int,
    i: int,
    j: int,
) -> int
    decreases t.n as int - i, u.n as int - j
{{
    if i >= t.n as int {{
        0
    }} else if j >= u.n as int {{
        matched_sum_rec(t, u, g, i + 1, 0)
    }} else if t.{t_field}@[i] == u.{u_field}@[j] {{
        let g_here = {g_ref} as int;
        let add = if g_here == g {{
            {s_ref} as int
        }} else {{
            0
        }};
        add + matched_sum_rec(t, u, g, i, j + 1)
    }} else {{
        matched_sum_rec(t, u, g, i, j + 1)
    }}
}}
""".strip()


def _emit_matched_real_sum(
    t_struct: str,
    u_struct: str,
    t_field: str,
    u_field: str,
    sum_field: str,
    *,
    group_on_t: bool,
    sum_on_t: bool,
    group_field: str,
) -> str:
    g_ref = f"t.{group_field}@[i]" if group_on_t else f"u.{group_field}@[j]"
    s_ref = f"{('t' if sum_on_t else 'u')}.{sum_field}@[{'i' if sum_on_t else 'j'}]"
    return f"""
pub open spec fn matched_real_sum(
    t: &{t_struct},
    u: &{u_struct},
    g: int,
) -> real
    decreases t.n, u.n
{{
    matched_real_sum_rec(t, u, g, 0, 0)
}}

pub open spec fn matched_real_sum_rec(
    t: &{t_struct},
    u: &{u_struct},
    g: int,
    i: int,
    j: int,
) -> real
    decreases t.n as int - i, u.n as int - j
{{
    if i >= t.n as int {{
        0real
    }} else if j >= u.n as int {{
        matched_real_sum_rec(t, u, g, i + 1, 0)
    }} else if t.{t_field}@[i] == u.{u_field}@[j] {{
        let g_here = {g_ref} as int;
        let v = {s_ref} as real;
        let add = if g_here == g {{ v }} else {{ 0real }};
        add + matched_real_sum_rec(t, u, g, i, j + 1)
    }} else {{
        matched_real_sum_rec(t, u, g, i, j + 1)
    }}
}}
""".strip()


def _emit_dense_count_map_lemma(*, key_ty: str) -> str:
    """The final map condition, once the dense count vector and the nonzero copy are in hand."""
    return f"""
pub proof fn lemma_dense_count_map(
    keys: Seq<{key_ty}>,
    counts: Seq<{key_ty}>,
    map: Map<{key_ty}, {key_ty}>,
    key_cap: int,
)
    requires
        0 <= key_cap,
        counts.len() == key_cap,
        forall|j: int| 0 <= j < keys.len() ==> {{
            &&& 0 <= (#[trigger] keys[j] as int)
            &&& (keys[j] as int) < key_cap
        }},
        forall|kk: int| 0 <= kk < key_cap ==> counts[kk] as int == group_count(keys, 0, kk as {key_ty}),
        forall|k: {key_ty}| #[trigger] map.contains_key(k) ==> {{
            &&& (k as int) < key_cap
            &&& map[k] == counts[k as int]
            &&& counts[k as int] > 0
        }},
        forall|kk: int| 0 <= kk < key_cap && counts[kk] > 0 ==> #[trigger] map.contains_key(kk as {key_ty}),
    ensures
        forall|k: {key_ty}| #[trigger] map.contains_key(k) <==> (exists|j: int|
            0 <= j < keys.len() && keys[j] == k),
        forall|k: {key_ty}| #[trigger] map.contains_key(k) ==> map[k] as int == group_count(keys, 0, k),
{{
    assert forall|k: {key_ty}|
        #[trigger] map.contains_key(k) <==> (exists|j: int| 0 <= j < keys.len() && keys[j] == k)
    by {{
        if map.contains_key(k) {{
            assert(counts[k as int] as int == group_count(keys, 0, k));
            assert(counts[k as int] > 0);
            lemma_group_count_witness(keys, 0, k);
        }}
        if exists|j: int| 0 <= j < keys.len() && keys[j] == k {{
            let j = choose|j: int| 0 <= j < keys.len() && keys[j] == k;
            assert(keys[j] == k);
            assert(0 <= (keys[j] as int) && (keys[j] as int) < key_cap);
            assert((k as int) == (keys[j] as int));
            lemma_group_count_witness(keys, 0, k);
            assert(group_count(keys, 0, k) > 0);
            assert(counts[k as int] > 0);
            assert(map.contains_key(k));
        }}
    }};
    assert forall|k: {key_ty}|
        #[trigger] map.contains_key(k) ==> map[k] as int == group_count(keys, 0, k)
    by {{
        if map.contains_key(k) {{
            assert(map[k] == counts[k as int]);
            assert(counts[k as int] as int == group_count(keys, 0, k));
        }}
    }};
}}
""".strip()


def _emit_valid_cols(struct: str, table: str, fields: list[tuple[str, str, ColumnTypeInfo]], row_cap_name: str, ctx: _EmitCtx) -> str:
    lines = [f"pub open spec fn valid_cols_{rust_ident(table)}(cols: &{struct}) -> bool {{"]
    conj: list[str] = [f"cols.n as int <= {row_cap_name}"]
    for _orig, field, info in fields:
        conj.append(f"cols.{field}@.len() == cols.n as int")
        if info.is_float:
            continue
        inc = _cell_inclusive_max(ctx.catalog, table, _orig, info)
        if inc is not None:
            if info.signed:
                conj.append(
                    f"forall|i: int| 0 <= i < cols.n as int ==> cols.{field}@[i] as int <= {_int_literal(inc)}"
                )
            else:
                conj.append(
                    f"forall|i: int| 0 <= i < cols.n as int ==> cols.{field}@[i] as int >= 0 && cols.{field}@[i] as int <= {_int_literal(inc)}"
                )
    lines.append("    " + "\n    && ".join(conj))
    lines.append("}")
    return "\n".join(lines)


def _sum_bound_inclusive_abs(
    catalog: CatalogAssumptions | None,
    left: str,
    right: str,
    sum_table: str,
    sum_col: str,
    sum_info: ColumnTypeInfo,
    join_left_table: str,
    join_left_col: str,
    join_right_table: str,
    join_right_col: str,
) -> int:
    rows_l = _row_cap_inclusive(catalog, left)
    rows_r = _row_cap_inclusive(catalog, right)
    fact_rows = _row_cap_inclusive(catalog, sum_table)
    other_table = right if sum_table.casefold() == left.casefold() else left
    other_rows = _row_cap_inclusive(catalog, other_table)

    inc_cell = _cell_inclusive_max(catalog, sum_table, sum_col, sum_info)
    if inc_cell is None:
        from declarative_spec.lemmas import FitRefusal

        raise FitRefusal("integer sum requires cell bound")

    ta_l = _lookup_table_assumptions(catalog, join_left_table)
    ta_r = _lookup_table_assumptions(catalog, join_right_table)
    left_unique = _join_col_is_unique(ta_l, join_left_col)
    right_unique = _join_col_is_unique(ta_r, join_right_col)

    if left_unique and right_unique or left_unique or right_unique:
        product = fact_rows * inc_cell
    else:
        product = rows_l * rows_r * inc_cell

    ta_sum = _lookup_table_assumptions(catalog, sum_table)
    abs_ex = column_abs_sum_exclusive(sum_col, ta_sum)
    if abs_ex is not None:
        at_most_once = left_unique or right_unique
        if at_most_once:
            product = min(product, abs_ex - 1)
        else:
            product = min(product, (abs_ex - 1) * other_rows)

    return product


_COUNT_PATH_SHAPE_REFUSALS = frozenset(
    {
        "multi-column GROUP BY not yet emitted in count path",
        "mixed group key types",
    }
)


def emit_declarative_spec(
    sql: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
    catalog: CatalogAssumptions | None = None,
) -> str:
    """Spec for ``sql``. DATE and DECIMAL are first stated as exact integer SQL (``numeric_rewrite``)."""
    from declarative_spec.numeric_rewrite import rewrite_numeric, with_out_scales

    sql = _flatten_group_derived_sql(sql)
    integer_sql, scales = rewrite_numeric(sql, schema, catalog)
    _check_shape_classes(integer_sql)
    spec = _emit_integer_sql(integer_sql, schema, catalog)
    spec = _with_f64_literals(spec, integer_sql)
    return _with_agent_surface(with_out_scales(spec, scales))


_F64_LITERAL = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)e0(?!\w)")


def _refuse_bad_literals(texts: dict[str, Fraction]) -> None:
    """Refuse a float literal that is no finite nonzero double, and two decimal values that round to the same
    double (the literal hypothesis would be contradictory, so every body would verify). Never crash."""
    seen: dict[float, tuple[str, Fraction]] = {}
    for label, value in sorted(texts.items()):
        try:
            double = float(value)
        except OverflowError:
            double = float("inf")  # a huge literal: float(Fraction) raises instead of returning inf
        if double in (float("inf"), float("-inf")) or (double == 0.0 and value != 0):
            raise DeclarativeUnsupported(
                f"float literal {label[:40]}{'...' if len(label) > 40 else ''} is not a finite nonzero double"
            )
        if double in seen and seen[double][1] != value:
            raise DeclarativeUnsupported(
                f"float literals {seen[double][0]} and {label} are the same double ({double!r}) "
                "but different decimal values: the literal hypothesis would be contradictory"
            )
        seen[double] = (label, value)


def _with_f64_literals(spec: str, integer_sql: str) -> str:
    """State, as a hypothesis of ``run_query``, that each f64 literal denotes its decimal value.

    Verus gives a float literal no value as a real (`(1.5f64 as real)` is unconstrained), so the f64
    idealization also needs: the literal ``c`` as an f64 is the real ``c`` (the nearest double ignored).
    """
    texts: dict[str, Fraction] = {}
    for m in _F64_LITERAL.finditer(integer_sql):
        base = m.group(1)
        texts[base if "." in base else f"{base}.0"] = Fraction(base)
    outside_lemmas = spec.partition("// HOST_LEMMAS_START")[0] + spec.rpartition("// HOST_LEMMAS_END")[2]
    if not texts and "f64" not in outside_lemmas:
        return spec
    texts["0.0"] = Fraction("0")  # the initial value of every accumulator
    _refuse_bad_literals(texts)
    conj = "\n".join(
        f"    &&& ({text}f64 as real) == ({v.numerator}real / {v.denominator}real)" for text, v in sorted(texts.items())
    )

    fn = (
        "// HYPOTHESIS (f64 idealization): each f64 literal denotes its decimal value as a real.\n"
        f"pub open spec fn f64_literals_ok() -> bool {{\n{conj}\n}}\n\n"
    )
    assert spec.count("pub fn run_query(") == 1
    head, sep, tail = spec.partition("pub fn run_query(")
    sig, req, rest = tail.partition("requires\n")
    assert req, "run_query has no requires"
    return head.rstrip("\n") + "\n\n" + fn + sep + sig + req + "        f64_literals_ok(),\n" + rest


_COLS_STRUCT = re.compile(r"pub struct (Cols_\w+) \{\n((?:    pub [^\n]+\n)+)\}")
_VALID_FN = re.compile(
    r"pub open spec fn (valid_cols_\w+)\((\w+): &(Cols_\w+)\) -> bool \{\n    &&& (.*?)\n\}", re.S
)


def _prune_unread_columns(spec: str) -> str:
    """Keep in each ``Cols_<table>`` (and its ``valid_cols``) only the columns the spec reads.

    A column no spec text mentions is never loaded, so a NULL in it cannot block the run.
    A column the query reads stays, and a NULL there still fails at export.
    """
    rest = _COLS_STRUCT.sub("", spec)
    rest = _VALID_FN.sub("", rest)
    used = set(re.findall(r"\w\.((?:r#)?\w+)@", rest))

    def struct(m: re.Match[str]) -> str:
        lines = [
            ln
            for ln in m.group(2).splitlines()
            if ln.strip() == "pub n: usize," or re.match(r"\s+pub ((?:r#)?\w+):", ln).group(1) in used
        ]
        return f"pub struct {m.group(1)} {{\n" + "\n".join(lines) + "\n}"

    def valid(m: re.Match[str]) -> str:
        param = m.group(2)
        dropped = {
            f
            for f in re.findall(rf"\b{re.escape(param)}\.((?:r#)?\w+)@", m.group(4))
            if f not in used
        }
        conj = m.group(4).split("\n    &&& ")
        kept = [c for c in conj if not any(re.search(rf"\b{re.escape(param)}\.{re.escape(f)}@", c) for f in dropped)]
        body = "\n    &&& ".join(kept or ["true"])
        return f"pub open spec fn {m.group(1)}({param}: &{m.group(3)}) -> bool {{\n    &&& {body}\n}}"

    spec = _COLS_STRUCT.sub(struct, spec)
    return _VALID_FN.sub(valid, spec)


def _check_shape_classes(integer_sql: str) -> None:
    """Refuse a query with a shape class known to have no proof (see ``shapes``). A parse the surface cannot
    read is left to the emitter, which refuses it."""
    from declarative_spec.parse_query import parse_query
    from declarative_spec.shapes import check_shapes

    try:
        query = parse_query(integer_sql)
    except DeclarativeUnsupported:
        return
    check_shapes(query)


def _flatten_group_derived_sql(sql: str) -> str:
    """SQL with a filter over a grouped derived table merged into the grouped query (see ``flatten_group``)."""
    import sqlglot

    from declarative_spec.flatten_group import flatten_group_derived, move_inner_join_filters

    try:
        tree = sqlglot.parse_one(sql)
    except sqlglot.errors.SqlglotError:
        return sql  # the stages below report the parse error
    moved = move_inner_join_filters(tree)
    flat = flatten_group_derived(tree)
    return sql if flat is tree and not moved else flat.sql()


def _fit_host_lemma_region(spec: str) -> str:
    """Put into the host lemma region the trusted set's blocks this spec needs (no float lemma without a float)."""
    from declarative_spec.trusted_sets import current

    body = current().lemmas_rs(spec)
    start, end = "// HOST_LEMMAS_START", "// HOST_LEMMAS_END"
    head, _, rest = spec.partition(start)
    _, _, tail = rest.partition(end)
    return f"{head}{start}\n{body}\n{end}{tail}"


def _with_agent_surface(spec: str) -> str:
    """Import every vstd module by glob, and mark the helper region just above `run_query`."""
    from declarative_spec.regions import HELPERS_END, HELPERS_START
    from declarative_spec.vstd_index import preamble_uses

    assert spec.count("use vstd::prelude::*;") == 1
    spec = _prune_unread_columns(spec)
    spec = _fit_host_lemma_region(spec)
    spec = spec.replace("use vstd::prelude::*;", preamble_uses(), 1)
    head, sep, tail = spec.partition("pub fn run_query(")
    assert sep
    if "spec_like(" in head and "spec fn spec_like(" not in head:
        from declarative_spec.emit_like import SPEC_LIKE_FN

        head = f"{head}{SPEC_LIKE_FN}\n\n"
    return f"{head}{HELPERS_START}\n{HELPERS_END}\n{sep}{tail}"


def _emit_integer_sql(
    sql: str,
    schema: dict[str, str] | dict[str, dict[str, str]],
    catalog: CatalogAssumptions | None,
) -> str:
    from declarative_spec.emit_surface import emit_from_surface
    from declarative_spec.string_encoding import dict_mode

    if dict_mode():
        # The count and join-sum emitters below know `Vec<String>` columns only: with dictionary-encoded strings every
        # query takes the surface emitter, which refuses what it cannot state.
        return emit_from_surface(sql, schema, catalog)
    try:
        parsed = parse_declarative_sql(sql)
    except DeclarativeUnsupported:
        return emit_from_surface(sql, schema, catalog)
    from_table = parsed.from_table or parsed.left_table or ""
    model = SchemaModel.from_caller(schema, from_table)
    ctx = _EmitCtx(catalog=catalog, lines=[], consts=[])
    try:
        if parsed.is_join:
            return _emit_join_sum(parsed, model, ctx)
        return _emit_count(parsed, model, ctx)
    except DeclarativeUnsupported as exc:
        # The count emitter takes one group key of one type. The surface emitter takes the
        # other grouped-count shapes, or raises its own DeclarativeUnsupported.
        if str(exc) not in _COUNT_PATH_SHAPE_REFUSALS:
            raise
        return emit_from_surface(sql, schema, catalog)


def _emit_count(parsed: ParsedQuery, model: SchemaModel, ctx: _EmitCtx) -> str:
    table = parsed.from_table
    assert table is not None
    t_orig, _cols_map = model.lookup_table(table)
    struct = f"Cols_{rust_ident(t_orig)}"

    fields: list[tuple[str, str, ColumnTypeInfo]] = []
    group_meta: list[tuple[str, str, KeyKind]] = []
    seen_fields: set[str] = set()
    for g in parsed.group_cols:
        _gt, gc, ginfo, gkind = _resolve_group_col(g, model, t_orig, [t_orig])
        field = rust_ident(gc)
        if field not in seen_fields:
            fields.append((gc, field, ginfo))
            seen_fields.add(field)
        group_meta.append((field, gc, gkind))

    row_cap = _row_cap_inclusive(ctx.catalog, t_orig)
    row_cap_name = ctx.add_const(_cap_const_name("ROW_CAP", t_orig), row_cap)

    from declarative_spec.lemmas import choose_agg_slot

    value_ty = choose_agg_slot(row_cap, signed=False)
    key_kinds = [k for _, _, k in group_meta]
    if len(set(key_kinds)) != 1:
        raise DeclarativeUnsupported("mixed group key types")
    if len(group_meta) != 1:
        raise DeclarativeUnsupported("multi-column GROUP BY not yet emitted in count path")
    from research_loop.table_assumptions import column_assumption_exclusive

    _gfield, gcol, gkind0_early = group_meta[0]
    key_cap_name: str | None = None
    key_inclusive: int | None = None
    if gkind0_early != KeyKind.STRING:
        exclusive = column_assumption_exclusive(gcol, _lookup_table_assumptions(ctx.catalog, t_orig))
        if exclusive is not None and exclusive > 0:
            key_cap_name = ctx.add_exec_const(_cap_const_name("KEY_CAP", t_orig, gcol), exclusive)
            key_inclusive = exclusive - 1
    ginfo_exec = next(info for _c, f, info in fields if f == group_meta[0][0])
    if key_kinds[0] == KeyKind.STRING:
        map_ty = f"StringHashMap<{value_ty}>"
        quant_ty = "Seq<char>"
        count_block = _emit_group_count_block(seq_ty="Seq<String>", key_ty="Seq<char>", elem="keys[i]@")
        hash_use = "use vstd::hash_map::StringHashMap;"
    else:
        quant_ty = ginfo_exec.exec_rust
        map_ty = f"HashMapWithView<{quant_ty}, {value_ty}>"
        count_block = _emit_group_count_block(
            seq_ty=f"Seq<{quant_ty}>", key_ty=quant_ty, elem="keys[i]"
        )
        hash_use = "use vstd::hash_map::HashMapWithView;"

    struct_lines = [f"pub struct {struct} {{"]
    struct_lines.append("    pub n: usize,")
    for _c, field, info in fields:
        struct_lines.append(f"    pub {field}: Vec<{info.exec_rust}>,")
    struct_lines.append("}")

    dense_map_lemma = ""
    if key_cap_name is not None and key_inclusive is not None and not ginfo_exec.signed:
        if ginfo_exec.exec_rust == "u64":
            dense_map_lemma = _emit_dense_count_map_lemma(key_ty="u64")

    parts: list[str] = [
        "use vstd::prelude::*;",
        hash_use,
        "verus! {",
    ]
    if key_kinds[0] != KeyKind.STRING:
        axiom = _host_hash_key_axiom(ginfo_exec.exec_rust)
        if axiom:
            parts.append(axiom)
    parts.extend([
        "\n".join(struct_lines),
        "",
        _emit_valid_cols(struct, t_orig, fields, row_cap_name, ctx),
        "",
        count_block,
        "",
        dense_map_lemma,
        "",
        _host_lemma_region(),
        "",
    ])

    field, _, gkind0 = group_meta[0]
    if gkind0 == KeyKind.STRING:
        key_cmp = f"cols.{field}@[j]@ == k"
    else:
        key_cmp = f"cols.{field}@[j] == k"
    mem = f"""forall|k: {quant_ty}| res@.contains_key(k) <==> exists|j: int|
    0 <= j < cols.n as int && {key_cmp}"""
    count_eq = f"res@[k] as int == group_count(cols.{field}@, 0, k)"

    parts.append(
        f"""pub fn run_query(cols: &{struct}) -> (res: {map_ty})
    requires
        valid_cols_{rust_ident(t_orig)}(cols),
    ensures
        {mem},
        forall|k: {quant_ty}| res@.contains_key(k) ==> {count_eq},
{{
// AGENT_EDIT_START
// AGENT_EDIT_END
}}"""
    )
    parts.append("}")

    header_consts = "\n".join(ctx.consts)
    if header_consts:
        verus_at = parts.index("verus! {")
        parts.insert(verus_at + 1, header_consts)

    return "\n".join(parts) + "\n"


def _emit_join_sum(
    parsed: ParsedQuery,
    model: SchemaModel,
    ctx: _EmitCtx,
) -> str:
    lt, rt = parsed.left_table, parsed.right_table
    assert lt and rt
    lt_orig, _ = model.lookup_table(lt)
    rt_orig, _ = model.lookup_table(rt)

    sum_t, sum_c, sum_info = model.resolve_column(parsed.sum_qual, parsed.sum_column or "", [lt_orig, rt_orig])

    # collect struct fields: join cols + group cols + sum col
    def add_field(table: str, col: str, acc: dict[tuple[str, str], tuple[str, str, ColumnTypeInfo]]):
        c_orig, info = model.lookup_column(table, col)
        acc[(table.casefold(), c_orig.casefold())] = (c_orig, rust_ident(c_orig), info)

    field_map: dict[tuple[str, str], tuple[str, str, ColumnTypeInfo]] = {}
    add_field(parsed.join_left_table or lt_orig, parsed.join_left_col or "", field_map)
    add_field(parsed.join_right_table or rt_orig, parsed.join_right_col or "", field_map)
    add_field(sum_t, sum_c, field_map)

    group_table = None
    group_field = None
    group_kind: KeyKind | None = None
    for g in parsed.group_cols:
        gt, gc, _ginfo, gkind = _resolve_group_col(g, model, None, [lt_orig, rt_orig])
        add_field(gt, gc, field_map)
        group_table = gt
        group_field = rust_ident(gc)
        group_kind = gkind

    if group_kind is None:
        raise DeclarativeUnsupported("missing group column")

    lt_struct = f"Cols_{rust_ident(lt_orig)}"
    rt_struct = f"Cols_{rust_ident(rt_orig)}"

    lt_fields = [(c, f, i) for (t, _), (c, f, i) in field_map.items() if t == lt_orig.casefold()]
    rt_fields = [(c, f, i) for (t, _), (c, f, i) in field_map.items() if t == rt_orig.casefold()]

    if group_kind == KeyKind.STRING:
        raise DeclarativeUnsupported(
            "JOIN GROUP BY on a string column is not supported in declarative mode"
        )
    g_exec = "i64"
    for _c, field, info in lt_fields + rt_fields:
        if field == group_field:
            g_exec = info.exec_rust
            break
    quant_ty = g_exec

    row_cap_l = ctx.add_const(_cap_const_name("ROW_CAP", lt_orig), _row_cap_inclusive(ctx.catalog, lt_orig))
    row_cap_r = ctx.add_const(_cap_const_name("ROW_CAP", rt_orig), _row_cap_inclusive(ctx.catalog, rt_orig))

    from declarative_spec.lemmas import choose_agg_slot

    if sum_info.is_float:
        value_ty = "f64"
        map_ty = f"HashMapWithView<{quant_ty}, {value_ty}>"
        ta = _lookup_table_assumptions(ctx.catalog, sum_t)
        mag_ex = column_assumption_exclusive(sum_c, ta)
        if mag_ex is None:
            from declarative_spec.lemmas import FitRefusal

            raise FitRefusal("float sum requires magnitude cap")
        ctx.add_const("MAG_CAP", mag_ex - 1)
    else:
        inclusive_abs = _sum_bound_inclusive_abs(
            ctx.catalog,
            lt_orig,
            rt_orig,
            sum_t,
            sum_c,
            sum_info,
            parsed.join_left_table or lt_orig,
            parsed.join_left_col or "",
            parsed.join_right_table or rt_orig,
            parsed.join_right_col or "",
        )
        ctx.add_const("SUM_CAP", inclusive_abs)
        choose_agg_slot(inclusive_abs, signed=sum_info.signed)
        # DuckDB widens every integer SUM to HUGEINT, a signed 128-bit integer.
        value_ty = "i128"
        map_ty = f"HashMapWithView<{quant_ty}, {value_ty}>"

    def emit_struct(name: str, table: str, flist: list[tuple[str, str, ColumnTypeInfo]]) -> str:
        lines = [f"pub struct {name} {{", "    pub n: usize,"]
        for _, field, info in flist:
            lines.append(f"    pub {field}: Vec<{info.exec_rust}>,")
        lines.append("}")
        return "\n".join(lines)

    jt_field = rust_ident(parsed.join_left_col or "")
    ju_field = rust_ident(parsed.join_right_col or "")
    sum_field = rust_ident(sum_c)

    parts: list[str] = [
        "use vstd::prelude::*;",
        "use vstd::hash_map::HashMapWithView;",
        "verus! {",
    ]
    hash_axiom = _host_hash_key_axiom(quant_ty)
    if hash_axiom:
        parts.append(hash_axiom)
    if ctx.consts:
        parts.append("\n".join(ctx.consts))
    parts.extend(
        [
            emit_struct(lt_struct, lt_orig, lt_fields),
            emit_struct(rt_struct, rt_orig, rt_fields),
            "",
            _emit_valid_cols(lt_struct, lt_orig, lt_fields, row_cap_l, ctx),
            _emit_valid_cols(rt_struct, rt_orig, rt_fields, row_cap_r, ctx),
            "",
        ]
    )

    group_on_t = (group_table or lt_orig).casefold() == lt_orig.casefold()
    sum_on_t = sum_t.casefold() == lt_orig.casefold()

    if sum_info.is_float:
        parts.append(
            _emit_matched_real_sum(
                lt_struct,
                rt_struct,
                jt_field,
                ju_field,
                sum_field,
                group_on_t=group_on_t,
                sum_on_t=sum_on_t,
                group_field=group_field or "",
            )
        )
    else:
        parts.append(
            _emit_matched_sum_int(
                lt_struct,
                rt_struct,
                jt_field,
                ju_field,
                sum_field,
                group_on_t=group_on_t,
                sum_on_t=sum_on_t,
                group_field=group_field or "",
            )
        )

    parts.extend(["", _host_lemma_region(), ""])

    gt_name = group_table or lt_orig
    g_struct = lt_struct if gt_name.casefold() == lt_orig.casefold() else rt_struct
    g_prefix = "t" if g_struct == lt_struct else "u"

    g_idx = "i" if g_prefix == "t" else "j"
    g_eq = f"{g_prefix}.{group_field}@[{g_idx}] == g"
    mem = f"""forall|g: {quant_ty}| res@.contains_key(g) <==> exists|i: int, j: int|
    0 <= i < t.n as int && 0 <= j < u.n as int
    && t.{jt_field}@[i] == u.{ju_field}@[j]
    && {g_eq}"""

    if sum_info.is_float:
        value_ensure = (
            "res@[g] as real == matched_real_sum(t, u, g as int)"
        )
    else:
        value_ensure = "res@[g] as int == matched_sum(t, u, g as int)"

    parts.append(
        f"""pub fn run_query(t: &{lt_struct}, u: &{rt_struct}) -> (res: {map_ty})
    requires
        valid_cols_{rust_ident(lt_orig)}(t),
        valid_cols_{rust_ident(rt_orig)}(u),
    ensures
        {mem},
        forall|g: {quant_ty}| res@.contains_key(g) ==> {value_ensure},
{{
// AGENT_EDIT_START
// AGENT_EDIT_END
}}"""
    )
    parts.append("}")

    return "\n".join(parts) + "\n"
