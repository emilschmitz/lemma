"""Basic SQL projection / ORDER BY fixtures."""

from __future__ import annotations

from dataclasses import dataclass

_DISTINCT_RUNQUERY = """\
// TRUSTED: Set<u32> spec viewed as Seq for exec RESULT formatting.
#[verifier::external_body]
pub open spec fn distinct_set_to_seq(s: Set<u32>) -> Seq<u32> {
    arbitrary()
}

// TRUSTED: DISTINCT projection exec bridge.
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: Vec<u32>)
    requires valid_cols(cols),
    ensures res@ == distinct_set_to_seq(method_spec(cols)),
{
    let mut seen: std::collections::HashSet<u32> = std::collections::HashSet::new();
    let mut i: usize = 0;
    while i < cols.n {
        let a = cols.get_a_exec(i);
        if a > 0 {
            seen.insert(a);
        }
        i = i + 1;
    }
    let mut out: Vec<u32> = seen.into_iter().collect();
    out.sort();
    out
}"""

_PROJECTION_RUNQUERY = """\
// TRUSTED: projection exec (spec Seq tracks first projected column).
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: Vec<u32>)
    requires valid_cols(cols),
    ensures res@ == method_spec(cols),
{
    let mut out: Vec<u32> = Vec::new();
    let mut i: usize = 0;
    while i < cols.n {
        let a = cols.get_a_exec(i);
        if a > 0 {
            out.push(a);
        }
        i = i + 1;
    }
    out
}"""

_ORDER_LIMIT_RUNQUERY = """\
// TRUSTED: GROUP BY + ORDER BY k + LIMIT 2 exec bridge (method_spec_result axiom).
#[verifier::external_body]
pub exec fn run_query(cols: &Cols) -> (res: Vec<(u32, u64)>)
    requires valid_cols(cols),
    ensures res@ == method_spec_result(cols),
{
    let mut agg: std::collections::HashMap<u32, u64> = std::collections::HashMap::new();
    let mut i: usize = 0;
    while i < cols.n {
        let k = cols.get_k_exec(i);
        let v = cols.get_v_exec(i);
        let prev = agg.get(&k).copied().unwrap_or(0);
        agg.insert(k, prev.wrapping_add(v));
        i = i + 1;
    }
    let mut pairs: Vec<(u32, u64)> = agg.into_iter().collect();
    pairs.sort_by_key(|p| p.0);
    if pairs.len() > 2 {
        pairs.truncate(2);
    }
    pairs
}"""

_ARITH_BODY = """\
        let a = cols.get_a_exec(i);
        if a > 0 {
            let b = cols.get_b_exec(i);
            let term = add_u64(a, b as u64);
            res = add_u64(res, term);
        }"""

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


@dataclass(frozen=True)
class BasicSqlProjOrderFixture:
    sql: str
    schema: dict[str, str]
    ret_type: str
    run_query: str
    description: str


BASIC_SQL_PROJ_ORDER_FIXTURES: dict[str, BasicSqlProjOrderFixture] = {
    "distinct_proj": BasicSqlProjOrderFixture(
        sql="SELECT DISTINCT a FROM t WHERE a > 0",
        schema={"A": "int"},
        ret_type="set_u32",
        run_query=_DISTINCT_RUNQUERY,
        description="DISTINCT projection (TRUSTED Set spec)",
    ),
    "projection": BasicSqlProjOrderFixture(
        sql="SELECT a, b FROM t WHERE a > 0",
        schema={"A": "int", "B": "int"},
        ret_type="seq_u32",
        run_query=_PROJECTION_RUNQUERY,
        description="SELECT a,b projection (spec Seq on column a; TRUSTED exec bridge)",
    ),
    "order_limit": BasicSqlProjOrderFixture(
        sql="SELECT k, SUM(v) FROM t GROUP BY k ORDER BY k LIMIT 2",
        schema={"K": "int", "V": "bigint"},
        ret_type="seq_u32_u64",
        run_query=_ORDER_LIMIT_RUNQUERY,
        description="GROUP BY + ORDER BY + LIMIT (proved map + TRUSTED sort/limit)",
    ),
    "arith_sum": BasicSqlProjOrderFixture(
        sql="SELECT SUM(a + b) FROM t WHERE a > 0",
        schema={"A": "bigint", "B": "int"},
        ret_type="u64",
        run_query=_SCALAR_LOOP.format(body=_ARITH_BODY),
        description="SUM(a+b) — row add via TRUSTED add_u64; loop proved",
    ),
}

BASIC_SQL_PROJ_ORDER_RETURN_TYPES: dict[str, str] = {
    key: fx.ret_type for key, fx in BASIC_SQL_PROJ_ORDER_FIXTURES.items()
}

BASIC_SQL_PROJ_ORDER_RUNQUERIES: dict[str, str] = {
    key: fx.run_query for key, fx in BASIC_SQL_PROJ_ORDER_FIXTURES.items()
}
