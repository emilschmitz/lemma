"""Extended Basic SQL fixtures: INTERSECT/EXCEPT, joins, ILIKE, windows, recursive CTE."""

from __future__ import annotations

from dataclasses import dataclass

_SCALAR_LOOP = """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases i,
    {{
        i = i - 1;
{body}
        assert(res == method_spec_helper(cols, i as int));
    }}
    res
}}"""

_INTERSECT_RUNQUERY = """\
// TRUSTED: INTERSECT branch compose.
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: Vec<u64>)
    requires valid_cols(cols),
    ensures res@ == method_spec(cols),
{
    let mut left: u64 = 0;
    let mut right: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0 {
        i = i - 1;
        let b = cols.get_b_exec(i);
        if b > 0 {
            let a = cols.get_a_exec(i);
            left = add_u64(left, a);
        }
        let a = cols.get_a_exec(i);
        if a > 0 {
            let b = cols.get_b_exec(i);
            right = add_u64(right, b as u64);
        }
    }
    if left <= right { vec![left] } else { vec![right] }
}"""

_EXCEPT_RUNQUERY = """\
// TRUSTED: EXCEPT branch compose.
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: Vec<u64>)
    requires valid_cols(cols),
    ensures res@ == method_spec(cols),
{
    let mut left: u64 = 0;
    let mut right: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0 {
        i = i - 1;
        let b = cols.get_b_exec(i);
        if b > 0 {
            let a = cols.get_a_exec(i);
            left = add_u64(left, a);
        }
        let a = cols.get_a_exec(i);
        if a > 0 {
            let b = cols.get_b_exec(i);
            right = add_u64(right, b as u64);
        }
    }
    if left > right { vec![left - right] } else { vec![0] }
}"""

_CROSS_JOIN_RUNQUERY = """\
// TRUSTED: CROSS JOIN nested-loop exec bridge.
#[verifier::external_body]
pub exec fn run_query(left: &Cols_a, right: &Cols_b) -> (res: u64)
    requires
        valid_cols_a(left),
        valid_cols_b(right),
    ensures res == method_spec(left, right),
{
    let mut acc: u64 = 0;
    let mut li: usize = 0;
    while li < left.n {
        let mut ri: usize = 0;
        while ri < right.n {
            let v = left.get_v_exec(li);
            acc = add_u64(acc, v);
            ri = ri + 1;
        }
        li = li + 1;
    }
    acc
}"""

_FULL_JOIN_RUNQUERY = """\
// TRUSTED: FULL OUTER JOIN nested-loop exec bridge.
#[verifier::external_body]
pub exec fn run_query(left: &Cols_a, right: &Cols_b) -> (res: u64)
    requires
        valid_cols_a(left),
        valid_cols_b(right),
    ensures res == method_spec(left, right),
{
    let mut acc: u64 = 0;
    let mut li: usize = 0;
    while li < left.n {
        let mut ri: usize = 0;
        while ri < right.n {
            if left.get_id_exec(li) == right.get_id_exec(ri) {
                acc = add_u64(acc, left.get_v_exec(li));
            }
            ri = ri + 1;
        }
        li = li + 1;
    }
    acc
}"""

_SEMI_JOIN_RUNQUERY = """\
// TRUSTED: SEMI JOIN — HashSet build-probe on right.id.
#[verifier::external_body]
pub exec fn run_query(left: &Cols_a, right: &Cols_b) -> (res: u64)
    requires
        valid_cols_a(left),
        valid_cols_b(right),
    ensures res == method_spec(left, right),
{
    let mut keys: std::collections::HashSet<u32> =
        std::collections::HashSet::with_capacity(right.n);
    let mut ri: usize = 0;
    while ri < right.n {
        keys.insert(right.id[ri]);
        ri = ri + 1;
    }
    let mut acc: u64 = 0;
    let mut li: usize = 0;
    while li < left.n {
        if keys.contains(&left.id[li]) {
            acc = add_u64(acc, left.v[li]);
        }
        li = li + 1;
    }
    acc
}"""

_ANTI_JOIN_RUNQUERY = """\
// TRUSTED: ANTI JOIN — HashSet build-probe on right.id (exclude matches).
#[verifier::external_body]
pub exec fn run_query(left: &Cols_a, right: &Cols_b) -> (res: u64)
    requires
        valid_cols_a(left),
        valid_cols_b(right),
    ensures res == method_spec(left, right),
{
    let mut keys: std::collections::HashSet<u32> =
        std::collections::HashSet::with_capacity(right.n);
    let mut ri: usize = 0;
    while ri < right.n {
        keys.insert(right.id[ri]);
        ri = ri + 1;
    }
    let mut acc: u64 = 0;
    let mut li: usize = 0;
    while li < left.n {
        if !keys.contains(&left.id[li]) {
            acc = add_u64(acc, left.v[li]);
        }
        li = li + 1;
    }
    acc
}"""

_NWAY_JOIN_RUNQUERY = """\
// TRUSTED: 3-way equijoin — HashMap build-probe on b.id (hash_join_exec path).
#[verifier::external_body]
pub exec fn run_query(a: &Cols_a, b: &Cols_b, c: &Cols_c) -> (res: u64)
    requires
        valid_cols_a(a),
        valid_cols_b(b),
        valid_cols_c(c),
    ensures res == method_spec(a, b, c),
{
    let mut probe: HashMap<u32, usize> = HashMap::new();
    let mut bi: usize = 0;
    while bi < b.n {
        probe.insert(b.get_id_exec(bi), bi);
        bi = bi + 1;
    }
    let mut acc: u64 = 0;
    let mut ai: usize = 0;
    while ai < a.n {
        let aid = a.get_id_exec(ai);
        if let Some(bi) = probe.get(&aid) {
            let mut ci: usize = 0;
            while ci < c.n {
                if c.get_id_exec(ci) == aid {
                    acc = add_u64(acc, a.get_v_exec(ai));
                }
                ci = ci + 1;
            }
        }
        ai = ai + 1;
    }
    acc
}"""

_ILIKE_BODY = """\
        let name = cols.get_name_exec(i);
        if str_ilike_match_exec(&name, "foo%") {
            let value = cols.get_value_exec(i);
            res = add_u64(res, value);
        }"""

_UNDERSCORE_BODY = """\
        let name = cols.get_name_exec(i);
        if str_like_underscore_match_exec(&name, "f_o") {
            let value = cols.get_value_exec(i);
            res = add_u64(res, value);
        }"""

_GROUPED_DERIVED_RUNQUERY = """\
// TRUSTED: outer SUM over grouped derived map.
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut acc: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0 {
        i = i - 1;
        let b = cols.get_b_exec(i);
        let a = cols.get_a_exec(i);
        acc = add_u64(acc, add_u64(a, b as u64));
    }
    acc
}"""

_CORR_EXISTS_BRIDGE = """\
// TRUSTED: correlated EXISTS nested-loop bridge.
#[verifier::external_body]
pub exec fn exists_corr_exists_1_exec(cols: &Cols, outer_key: u32) -> (res: bool)
    ensures res == exists_corr_exists_1_spec(cols, outer_key),
{
    let mut j: usize = 0;
    while j < cols.n {
        if cols.get_cat_exec(j) == outer_key {
            return true;
        }
        j = j + 1;
    }
    false
}"""

_CORR_EXISTS_BODY = """\
        let cat = cols.get_cat_exec(i);
        if exists_corr_exists_1_exec(cols, cat) {
            let value = cols.get_value_exec(i);
            res = add_u64(res, value);
        }"""

_WINDOW_SUM_RUNQUERY = """\
// TRUSTED: window SUM partition exec bridge.
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut acc: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0 {
        i = i - 1;
        let cat = cols.get_cat_exec(i);
        let value = cols.get_value_exec(i);
        let _ = cat;
        acc = add_u64(acc, value);
    }
    acc
}"""

_ROW_NUMBER_RUNQUERY = """\
// TRUSTED: ROW_NUMBER window exec bridge.
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut acc: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0 {
        i = i - 1;
        acc = add_u64(acc, (i + 1) as u64);
    }
    acc
}"""

_RECURSIVE_CTE_RUNQUERY = """\
// TRUSTED: recursive CTE fixpoint exec bridge (depth-bounded).
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut acc: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0 {
        i = i - 1;
        let cat = cols.get_cat_exec(i);
        if cat <= 3 {
            acc = add_u64(acc, cat as u64);
        }
    }
    acc
}"""

_ABS_BODY = """\
        let delta = cols.get_delta_exec(i);
        let term = abs_u64_exec(delta as u64);
        res = add_u64(res, term);"""

_BOOL_BODY = """\
        if cols.get_active_exec(i) {
            let value = cols.get_value_exec(i);
            res = add_u64(res, value);
        }"""

_TINY_SCHEMA = {"A": "bigint", "B": "int"}
_STR_SCHEMA = {"NAME": "string", "VALUE": "bigint"}
_SUBQ_SCHEMA = {"VALUE": "bigint", "CAT": "int"}
_CROSS_SCHEMA = {
    "a": {"V": "bigint"},
    "b": {"K": "int"},
}
_JOIN_AB_SCHEMA = {
    "a": {"ID": "int", "V": "bigint"},
    "b": {"ID": "int", "K": "int"},
}
_NWAY_SCHEMA = {
    "a": {"ID": "int", "V": "bigint"},
    "b": {"ID": "int", "K": "int"},
    "c": {"ID": "int", "W": "bigint"},
}
_WIN_SCHEMA = {"VALUE": "bigint", "CAT": "int"}
_REC_SCHEMA = {"CAT": "int", "VALUE": "bigint"}
_SCALAR_FN_SCHEMA = {"VALUE": "bigint", "DELTA": "int", "ACTIVE": "bool"}


@dataclass(frozen=True)
class BasicSqlExtendedFixture:
    sql: str
    schema: dict[str, str] | dict[str, dict[str, str]]
    ret_type: str
    run_query: str
    description: str
    table_order: tuple[str, ...] | None = None
    default_tbls: dict[str, str] | None = None
    is_join: bool = False
    is_nway_join: bool = False


BASIC_SQL_EXTENDED_FIXTURES: dict[str, BasicSqlExtendedFixture] = {
    "intersect": BasicSqlExtendedFixture(
        sql=(
            "SELECT SUM(a) FROM t WHERE b > 0 "
            "INTERSECT SELECT SUM(b) FROM t WHERE a > 0"
        ),
        schema=dict(_TINY_SCHEMA),
        ret_type="seq_u64",
        run_query=_INTERSECT_RUNQUERY,
        description="INTERSECT of two scalar SUM branches (TRUSTED compose)",
    ),
    "except": BasicSqlExtendedFixture(
        sql=(
            "SELECT SUM(a) FROM t WHERE b > 0 "
            "EXCEPT SELECT SUM(b) FROM t WHERE a > 5"
        ),
        schema=dict(_TINY_SCHEMA),
        ret_type="seq_u64",
        run_query=_EXCEPT_RUNQUERY,
        description="EXCEPT of two scalar SUM branches (TRUSTED compose)",
    ),
    "cross_join": BasicSqlExtendedFixture(
        sql="SELECT SUM(a.v) FROM a CROSS JOIN b",
        schema=dict(_CROSS_SCHEMA),
        ret_type="u64",
        run_query=_CROSS_JOIN_RUNQUERY,
        description="CROSS JOIN scalar SUM (TRUSTED nested loop)",
        table_order=("a", "b"),
        default_tbls={"a": "research_loop/testdata/basic_cross_join_a.tbl", "b": "research_loop/testdata/basic_cross_join_b.tbl"},
        is_join=True,
    ),
    "full_join_sum": BasicSqlExtendedFixture(
        sql="SELECT SUM(a.v) FROM a FULL OUTER JOIN b ON a.id = b.id",
        schema=dict(_JOIN_AB_SCHEMA),
        ret_type="u64",
        run_query=_FULL_JOIN_RUNQUERY,
        description="FULL OUTER JOIN SUM (TRUSTED nested loop)",
        table_order=("a", "b"),
        default_tbls={"a": "research_loop/testdata/basic_full_join_a.tbl", "b": "research_loop/testdata/basic_full_join_b.tbl"},
        is_join=True,
    ),
    "semi_join": BasicSqlExtendedFixture(
        sql="SELECT SUM(a.v) FROM a SEMI JOIN b ON a.id = b.id",
        schema=dict(_JOIN_AB_SCHEMA),
        ret_type="u64",
        run_query=_SEMI_JOIN_RUNQUERY,
        description="SEMI JOIN SUM (TRUSTED nested loop)",
        table_order=("a", "b"),
        default_tbls={"a": "research_loop/testdata/basic_semi_join_a.tbl", "b": "research_loop/testdata/basic_semi_join_b.tbl"},
        is_join=True,
    ),
    "anti_join": BasicSqlExtendedFixture(
        sql="SELECT SUM(a.v) FROM a ANTI JOIN b ON a.id = b.id",
        schema=dict(_JOIN_AB_SCHEMA),
        ret_type="u64",
        run_query=_ANTI_JOIN_RUNQUERY,
        description="ANTI JOIN SUM (TRUSTED HashSet exclude)",
        table_order=("a", "b"),
        default_tbls={"a": "research_loop/testdata/basic_anti_join_a.tbl", "b": "research_loop/testdata/basic_anti_join_b.tbl"},
        is_join=True,
    ),
    "nway_join_sum": BasicSqlExtendedFixture(
        sql=(
            "SELECT SUM(a.v) FROM a "
            "JOIN b ON a.id = b.id JOIN c ON b.id = c.id"
        ),
        schema=dict(_NWAY_SCHEMA),
        ret_type="u64",
        run_query=_NWAY_JOIN_RUNQUERY,
        description="3-table equijoin SUM (HashMap build-probe TRUSTED)",
        table_order=("a", "b", "c"),
        default_tbls={
            "a": "research_loop/testdata/basic_nway_join_a.tbl",
            "b": "research_loop/testdata/basic_nway_join_b.tbl",
            "c": "research_loop/testdata/basic_nway_join_c.tbl",
        },
        is_join=True,
        is_nway_join=True,
    ),
    "ilike": BasicSqlExtendedFixture(
        sql="SELECT SUM(value) FROM t WHERE name ILIKE 'foo%'",
        schema=dict(_STR_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP.format(body=_ILIKE_BODY),
        description="ILIKE prefix filter (TRUSTED str_ilike_match)",
    ),
    "like_underscore": BasicSqlExtendedFixture(
        sql="SELECT SUM(value) FROM t WHERE name LIKE 'f_o'",
        schema=dict(_STR_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP.format(body=_UNDERSCORE_BODY),
        description="LIKE with _ wildcard (TRUSTED str_like_underscore_match)",
    ),
    "grouped_derived": BasicSqlExtendedFixture(
        sql=(
            "SELECT SUM(x) FROM "
            "(SELECT a, SUM(b) AS x FROM t GROUP BY a) s"
        ),
        schema=dict(_TINY_SCHEMA),
        ret_type="u64",
        run_query=_GROUPED_DERIVED_RUNQUERY,
        description="Outer SUM over grouped derived table (TRUSTED map)",
    ),
    "correlated_exists": BasicSqlExtendedFixture(
        sql=(
            "SELECT SUM(value) FROM t AS t_outer "
            "WHERE EXISTS (SELECT 1 FROM t AS t_inner WHERE t_inner.cat = t_outer.cat)"
        ),
        schema=dict(_SUBQ_SCHEMA),
        ret_type="u64",
        run_query=_CORR_EXISTS_BRIDGE + "\n\n" + _SCALAR_LOOP.format(body=_CORR_EXISTS_BODY),
        description="Correlated EXISTS semi-join (TRUSTED exists_corr bridge)",
    ),
    "window_sum": BasicSqlExtendedFixture(
        sql=(
            "SELECT SUM(x) FROM "
            "(SELECT SUM(value) OVER (PARTITION BY cat) AS x FROM t) s"
        ),
        schema=dict(_WIN_SCHEMA),
        ret_type="u64",
        run_query=_WINDOW_SUM_RUNQUERY,
        description="Outer SUM over window SUM column (TRUSTED partition loop)",
    ),
    "row_number": BasicSqlExtendedFixture(
        sql=(
            "SELECT SUM(rn) FROM "
            "(SELECT ROW_NUMBER() OVER (ORDER BY value) AS rn FROM t) s"
        ),
        schema=dict(_WIN_SCHEMA),
        ret_type="u64",
        run_query=_ROW_NUMBER_RUNQUERY,
        description="Outer SUM over ROW_NUMBER window (TRUSTED partition loop)",
    ),
    "recursive_cte": BasicSqlExtendedFixture(
        sql=(
            "WITH RECURSIVE cnt(n) AS ("
            "  SELECT cat AS n FROM t WHERE cat = 1 "
            "  UNION ALL "
            "  SELECT n AS n FROM cnt WHERE n < 3"
            ") SELECT SUM(n) FROM cnt"
        ),
        schema=dict(_REC_SCHEMA),
        ret_type="u64",
        run_query=_RECURSIVE_CTE_RUNQUERY,
        description="Recursive CTE SUM (TRUSTED depth-bounded fixpoint)",
    ),
    "abs_sum": BasicSqlExtendedFixture(
        sql="SELECT SUM(abs(delta)) FROM t",
        schema=dict(_SCALAR_FN_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP.format(body=_ABS_BODY),
        description="SUM(abs(col)) with TRUSTED abs_u64 bridge",
    ),
    "bool_filter": BasicSqlExtendedFixture(
        sql="SELECT SUM(value) FROM t WHERE active = TRUE",
        schema=dict(_SCALAR_FN_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP.format(body=_BOOL_BODY),
        description="Scalar SUM with bool WHERE filter",
    ),
}

BASIC_SQL_EXTENDED_RETURN_TYPES: dict[str, str] = {
    key: fx.ret_type for key, fx in BASIC_SQL_EXTENDED_FIXTURES.items()
}

BASIC_SQL_EXTENDED_RUNQUERIES: dict[str, str] = {
    key: fx.run_query for key, fx in BASIC_SQL_EXTENDED_FIXTURES.items()
}
