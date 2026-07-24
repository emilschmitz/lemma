"""Basic SQL batch-1 fixtures: transpiled spec + proved run_query bodies."""

from __future__ import annotations

from dataclasses import dataclass

_SCALAR_SCHEMA = {"X": "bigint", "Y": "int"}
_LIKE_SCHEMA = {"X": "bigint", "S": "string"}
_HAVING_SCHEMA = {"K": "int", "S": "string", "V": "bigint"}

_SCALAR_LOOP_HEAD = """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{{
    let mut res: u64 = {init};
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
}}
"""

_MIN_BODY = """\
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let x = cols.get_x_exec(i);
            if x < res {
                res = x;
            }
        }"""

_MAX_BODY = """\
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let x = cols.get_x_exec(i);
            if x > res {
                res = x;
            }
        }"""

_AVG_RUNQUERY = """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut sum: u64 = 0;
    let mut count: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            sum == sum_helper(cols, i as int),
            count == count_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let y = cols.get_y_exec(i);
        if y >= 1 {
            let x = cols.get_x_exec(i);
            sum = add_u64(sum, x);
            count = add_u64(count, 1);
        }
    }
    if count == 0 {
        0
    } else {
        sum / count
    }
}"""

_IN_LIST_BODY = """\
        let y = cols.get_y_exec(i);
        if y == 1 || y == 2 || y == 5 {
            let x = cols.get_x_exec(i);
            res = add_u64(res, x);
        }"""

_LIKE_PREFIX_RUNQUERY = """\
pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires valid_cols(cols),
    ensures res == method_spec(cols),
{
    let mut res: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            res == method_spec_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let s = cols.get_s_exec(i);
        if str_like_prefix_exec(&s, "A") {
            let x = cols.get_x_exec(i);
            res = add_u64(res, x);
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}"""

_CASE_SUM_BODY = """\
        let flag = cols.get_flag_exec(i);
        let value = cols.get_value_exec(i);
        let term = case_when_u64_exec(flag > 0, value, 0);
        res = add_u64(res, term);"""

_COUNT_STAR_BODY = """\
        res = add_u64(res, 1);"""

_CASE_SCHEMA = {"FLAG": "int", "VALUE": "bigint"}
_COUNT_SCHEMA = {"X": "bigint"}

_HAVING_RUNQUERY = """\
// TRUSTED: HAVING post-filter on exec HashMap (spec uses apply_having_filter).
#[verifier::external_body]
pub exec fn apply_having_filter_exec(
    hm: HashMap<(u32, String), u64>,
) -> (res: HashMap<(u32, String), u64>)
    ensures
        hashmap_u32_str_u64_view(res@)
            == apply_having_filter(
                hashmap_u32_str_u64_view(hm@),
                |k: (u32, Seq<char>), v: u64| v > 10,
            ),
{
    hm.into_iter()
        .filter(|(_k, v)| *v > 10)
        .collect()
}

pub exec fn run_query(cols: &Cols) -> (res: HashMap<(u32, String), u64>)
    requires valid_cols(cols),
    ensures hashmap_u32_str_u64_view(res@) == method_spec(cols),
{
    let mut agg = agg_new_u32_str_u64();
    let mut i: usize = cols.n;
    let ghost mut g: Map<(u32, Seq<char>), u64> = Map::empty();
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            g == method_spec_helper(cols, i as int),
            hashmap_u32_str_u64_view(agg@) == g,
        decreases i,
    {
        i = i - 1;
        {
            let k = cols.get_k_exec(i);
            let s = cols.get_s_exec(i);
            let v = cols.get_v_exec(i);
            agg_add_u32_str_u64(&mut agg, k, &s, v);
            proof {
                let ghost old_g = g;
                let key = (k, s@);
                let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                g = old_g.insert(key, (prev as int + v as int) as u64);
                assert(hashmap_u32_str_u64_view(agg@) == g);
            }
        }
        assert(g == method_spec_helper(cols, i as int) && hashmap_u32_str_u64_view(agg@) == g);
    }
    apply_having_filter_exec(agg)
}"""


@dataclass(frozen=True)
class BasicSqlFixture:
    sql: str
    schema: dict[str, str]
    ret_type: str
    run_query: str
    description: str


BASIC_SQL_FIXTURES: dict[str, BasicSqlFixture] = {
    "min": BasicSqlFixture(
        sql="SELECT MIN(X) FROM t WHERE Y >= 1",
        schema=dict(_SCALAR_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP_HEAD.format(init="u64::MAX", body=_MIN_BODY),
        description="Scalar MIN with Y >= 1 filter",
    ),
    "max": BasicSqlFixture(
        sql="SELECT MAX(X) FROM t WHERE Y >= 1",
        schema=dict(_SCALAR_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP_HEAD.format(init="0", body=_MAX_BODY),
        description="Scalar MAX with Y >= 1 filter",
    ),
    "avg": BasicSqlFixture(
        sql="SELECT AVG(X) FROM t WHERE Y >= 1",
        schema=dict(_SCALAR_SCHEMA),
        ret_type="u64",
        run_query=_AVG_RUNQUERY,
        description="Scalar AVG via sum_helper/count_helper",
    ),
    "in_list": BasicSqlFixture(
        sql="SELECT SUM(X) FROM t WHERE Y IN (1, 2, 5)",
        schema=dict(_SCALAR_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP_HEAD.format(init="0", body=_IN_LIST_BODY),
        description="Scalar SUM with IN (1, 2, 5)",
    ),
    "like_prefix": BasicSqlFixture(
        sql="SELECT SUM(X) FROM t WHERE S LIKE 'A%'",
        schema=dict(_LIKE_SCHEMA),
        ret_type="u64",
        run_query=_LIKE_PREFIX_RUNQUERY,
        description="Scalar SUM with LIKE 'A%' prefix",
    ),
    "having": BasicSqlFixture(
        sql="SELECT K, S, SUM(V) FROM t GROUP BY K, S HAVING SUM(V) > 10",
        schema=dict(_HAVING_SCHEMA),
        ret_type="map_u32_str_u64",
        run_query=_HAVING_RUNQUERY,
        description="Group-by with HAVING SUM(V) > 10",
    ),
    "case_sum": BasicSqlFixture(
        sql="SELECT SUM(CASE WHEN flag > 0 THEN value ELSE 0 END) FROM t",
        schema=dict(_CASE_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP_HEAD.format(init="0", body=_CASE_SUM_BODY),
        description="Scalar SUM with CASE WHEN flag > 0",
    ),
    "count_star": BasicSqlFixture(
        sql="SELECT COUNT(*) FROM t",
        schema=dict(_COUNT_SCHEMA),
        ret_type="u64",
        run_query=_SCALAR_LOOP_HEAD.format(init="0", body=_COUNT_STAR_BODY),
        description="Scalar COUNT(*) over all rows",
    ),
}

BASIC_SQL_RETURN_TYPES: dict[str, str] = {
    key: fx.ret_type for key, fx in BASIC_SQL_FIXTURES.items()
}

BASIC_SQL_RUNQUERIES: dict[str, str] = {
    key: fx.run_query for key, fx in BASIC_SQL_FIXTURES.items()
}
