"""Basic SQL set-op / subquery / CTE fixtures."""

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

_UNION_ALL_RUNQUERY = """\
// TRUSTED: UNION ALL branch compose (method_spec is union_all_compose).
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
    vec![left, right]
}"""

_UNION_DISTINCT_RUNQUERY = """\
// TRUSTED: UNION DISTINCT branch compose (method_spec is union_distinct_compose).
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
    if left == right {
        vec![left]
    } else {
        vec![left, right]
    }
}"""

_EXISTS_BRIDGE = """\
// TRUSTED: uncorrelated EXISTS semi-join bridge.
#[verifier::external_body]
pub exec fn exists_exists_1_exec(cols: &Cols) -> (res: bool)
    ensures res == exists_exists_1_spec(cols),
{
    let mut i: usize = 0;
    while i < cols.n {
        if cols.get_cat_exec(i) == 1 {
            return true;
        }
        i = i + 1;
    }
    false
}"""

_EXISTS_BODY = """\
        if exists_exists_1_exec(cols) {
            let value = cols.get_value_exec(i);
            res = add_u64(res, value);
        }"""

_IN_BRIDGE = """\
// TRUSTED: IN (subquery) membership bridge.
#[verifier::external_body]
pub exec fn in_in_1_contains_exec(cols: &Cols, val: u32) -> (res: bool)
    ensures res == in_in_1_contains(cols, val),
{
    let mut j: usize = 0;
    while j < cols.n {
        if cols.get_value_exec(j) > 0 {
            if cols.get_cat_exec(j) == val {
                return true;
            }
        }
        j = j + 1;
    }
    false
}"""

_IN_BODY = """\
        let cat = cols.get_cat_exec(i);
        if in_in_1_contains_exec(cols, cat) {
            let value = cols.get_value_exec(i);
            res = add_u64(res, value);
        }"""

_SCALAR_SUB_RUNQUERY = """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut sum: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            sum == subquery_sel_sq2_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let cat = cols.get_cat_exec(i);
        if cat == 1 {
            let value = cols.get_value_exec(i);
            sum = add_u64(sum, value);
        }
    }
    sum
}"""

_WITH_CTE_BODY = """\
        let b = cols.get_b_exec(i);
        if b > 0 {
            let a = cols.get_a_exec(i);
            res = add_u64(res, a);
        }"""

_UNION_SCHEMA = {"A": "bigint", "B": "int"}
_SUBQ_SCHEMA = {"VALUE": "bigint", "CAT": "int"}
_CTE_SCHEMA = {"A": "bigint", "B": "int"}


@dataclass(frozen=True)
class BasicSqlSetCteFixture:
    sql: str
    schema: dict[str, str]
    ret_type: str
    run_query: str
    description: str


BASIC_SQL_SET_CTE_FIXTURES: dict[str, BasicSqlSetCteFixture] = {
    "union_all": BasicSqlSetCteFixture(
        sql=(
            "SELECT SUM(a) FROM t WHERE b > 0 "
            "UNION ALL SELECT SUM(b) FROM t WHERE a > 0"
        ),
        schema=dict(_UNION_SCHEMA),
        ret_type="seq_u64",
        run_query=_UNION_ALL_RUNQUERY,
        description="UNION ALL of two scalar SUM branches (TRUSTED compose)",
    ),
    "union": BasicSqlSetCteFixture(
        sql=(
            "SELECT SUM(a) FROM t WHERE b > 0 "
            "UNION SELECT SUM(b) FROM t WHERE a > 0"
        ),
        schema=dict(_UNION_SCHEMA),
        ret_type="seq_u64",
        run_query=_UNION_DISTINCT_RUNQUERY,
        description="UNION DISTINCT of two scalar SUM branches (TRUSTED compose)",
    ),
    "exists_uncorrelated": BasicSqlSetCteFixture(
        sql=(
            "SELECT SUM(value) FROM t "
            "WHERE EXISTS (SELECT cat FROM t WHERE cat = 1)"
        ),
        schema=dict(_SUBQ_SCHEMA),
        ret_type="u64",
        run_query=_EXISTS_BRIDGE + "\n\n" + _SCALAR_LOOP.format(body=_EXISTS_BODY),
        description="Scalar SUM gated by uncorrelated EXISTS (TRUSTED exists bridge)",
    ),
    "in_subquery": BasicSqlSetCteFixture(
        sql=(
            "SELECT SUM(value) FROM t "
            "WHERE cat IN (SELECT cat FROM t WHERE value > 0)"
        ),
        schema=dict(_SUBQ_SCHEMA),
        ret_type="u64",
        run_query=_IN_BRIDGE + "\n\n" + _SCALAR_LOOP.format(body=_IN_BODY),
        description="Scalar SUM with IN (subquery) (TRUSTED set bridge)",
    ),
    "scalar_subquery": BasicSqlSetCteFixture(
        sql="SELECT (SELECT SUM(value) FROM t WHERE cat = 1) FROM t",
        schema=dict(_SUBQ_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_SUB_RUNQUERY,
        description="Scalar subquery in SELECT list (proved subquery helper)",
    ),
    "with_cte": BasicSqlSetCteFixture(
        sql="WITH cte AS (SELECT a FROM t WHERE b > 0) SELECT SUM(a) FROM cte",
        schema=dict(_CTE_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP.format(body=_WITH_CTE_BODY),
        description="Non-recursive WITH CTE inlined to base scan",
    ),
}

BASIC_SQL_SET_CTE_RETURN_TYPES: dict[str, str] = {
    key: fx.ret_type for key, fx in BASIC_SQL_SET_CTE_FIXTURES.items()
}

BASIC_SQL_SET_CTE_RUNQUERIES: dict[str, str] = {
    key: fx.run_query for key, fx in BASIC_SQL_SET_CTE_FIXTURES.items()
}
