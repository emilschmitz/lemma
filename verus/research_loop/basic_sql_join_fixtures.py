"""Basic SQL join fixtures: transpiled spec + proved (or TRUSTED) run_query bodies."""

from __future__ import annotations

from dataclasses import dataclass

_SYNTH_JOIN_HOT = """\
fn synth_join_build_stamp(
    right_custkey: &[u32],
    right_region: &[u32],
    stamp: &mut [u32; 10_001],
    g: u32,
) {
    for i in 0..right_custkey.len() {
        if right_region[i] == 1 {
            stamp[right_custkey[i] as usize] = g;
        }
    }
}

fn synth_join_probe_sum(
    left_custkey: &[u32],
    left_amount: &[u64],
    stamp: &[u32; 10_001],
    g: u32,
) -> u64 {
    let mut acc: u64 = 0;
    for i in 0..left_custkey.len() {
        if stamp[left_custkey[i] as usize] == g {
            acc = acc.wrapping_add(left_amount[i]);
        }
    }
    acc
}

fn synth_join_sum_hot(
    left_custkey: &[u32],
    left_amount: &[u64],
    right_custkey: &[u32],
    right_region: &[u32],
) -> u64 {
    use std::sync::atomic::{AtomicU32, Ordering};
    const CAP: usize = 10_001;
    static GEN: AtomicU32 = AtomicU32::new(1);
    static mut STAMP: [u32; CAP] = [0u32; CAP];
    let g = GEN.fetch_add(1, Ordering::Relaxed);
    // SAFETY: single-threaded bench; generation stamp avoids clearing.
    unsafe {
        let stamp = &mut *(&raw mut STAMP);
        synth_join_build_stamp(right_custkey, right_region, stamp, g);
        synth_join_probe_sum(left_custkey, left_amount, stamp, g)
    }
}"""

_TPCH_JOIN_HOT = """\
fn tpch_join_sum_hot(
    li_orderkey: &[u32],
    li_price: &[u64],
    ord_orderkey: &[u32],
    ord_date: &[u32],
) -> u64 {
    use std::sync::atomic::{AtomicU32, Ordering};
    static GEN: AtomicU32 = AtomicU32::new(1);
    let g = GEN.fetch_add(1, Ordering::Relaxed);
    let mut max_key: u32 = 0;
    for i in 0..ord_orderkey.len() {
        let d = ord_date[i];
        if d >= 19_960_101 && d <= 19_961_231 {
            let k = ord_orderkey[i];
            if k > max_key {
                max_key = k;
            }
        }
    }
    for i in 0..li_orderkey.len() {
        let k = li_orderkey[i];
        if k > max_key {
            max_key = k;
        }
    }
    let cap = (max_key as usize) + 1;
    let mut present = vec![0u32; cap];
    for i in 0..ord_orderkey.len() {
        let d = ord_date[i];
        if d >= 19_960_101 && d <= 19_961_231 {
            present[ord_orderkey[i] as usize] = g;
        }
    }
    let mut acc: u64 = 0;
    for i in 0..li_orderkey.len() {
        if present[li_orderkey[i] as usize] == g {
            acc = acc.wrapping_add(li_price[i]);
        }
    }
    acc
}"""

_INNER_JOIN_SUM = """\
// TRUSTED: hash join build-probe (method_spec remains nested-loop fold).
#[verifier::external_body]
pub exec fn run_query(left: &Cols_orders, right: &Cols_customers) -> (res: u64)
    requires
        valid_cols_orders(left),
        valid_cols_customers(right),
    ensures res == method_spec(left, right),
{
    synth_join_sum_hot(
        &left.custkey,
        &left.amount,
        &right.custkey,
        &right.region,
    )
}"""

_TPCH_JOIN_SUM = """\
// TRUSTED: hash join — build orderkeys in 1996 window, probe lineitem.
#[verifier::external_body]
pub exec fn run_query(left: &Cols_lineitem, right: &Cols_orders) -> (res: u64)
    requires
        valid_cols_lineitem(left),
        valid_cols_orders(right),
    ensures res == method_spec(left, right),
{
    tpch_join_sum_hot(
        &left.l_orderkey,
        &left.l_extendedprice,
        &right.o_orderkey,
        &right.o_orderdate,
    )
}"""

_LEFT_JOIN_SUM = """\
// TRUSTED: LEFT JOIN + WHERE region==1 — hash join equivalent of nested-loop spec.
#[verifier::external_body]
pub exec fn run_query(left: &Cols_orders, right: &Cols_customers) -> (res: u64)
    requires
        valid_cols_orders(left),
        valid_cols_customers(right),
    ensures res == method_spec(left, right),
{
    synth_join_sum_hot(
        &left.custkey,
        &left.amount,
        &right.custkey,
        &right.region,
    )
}"""

_SYNTHETIC_JOIN_SCHEMA: dict[str, dict[str, str]] = {
    "orders": {"CUSTKEY": "int", "AMOUNT": "bigint"},
    "customers": {"CUSTKEY": "int", "REGION": "int"},
}

_TPCH_JOIN_SCHEMA: dict[str, dict[str, str]] = {
    "lineitem": {"L_ORDERKEY": "int", "L_EXTENDEDPRICE": "bigint"},
    "orders": {"O_ORDERKEY": "int", "O_ORDERDATE": "int"},
}


@dataclass(frozen=True)
class BasicSqlJoinFixture:
    sql: str
    schema: dict[str, dict[str, str]]
    table_order: tuple[str, str]
    ret_type: str
    run_query: str
    description: str
    default_tbls: dict[str, str]
    bench_limit: int = 500
    hot_path: str = ""
    bench_exec: str = ""


BASIC_SQL_JOIN_FIXTURES: dict[str, BasicSqlJoinFixture] = {
    "inner_join_sum": BasicSqlJoinFixture(
        sql=(
            "SELECT SUM(o.amount) FROM orders o "
            "INNER JOIN customers c ON o.custkey = c.custkey "
            "WHERE c.region = 1"
        ),
        schema=dict(_SYNTHETIC_JOIN_SCHEMA),
        table_order=("orders", "customers"),
        ret_type="u64",
        run_query=_INNER_JOIN_SUM,
        description="INNER JOIN scalar SUM with region filter",
        default_tbls={
            "orders": "verus/research_loop/testdata/basic_inner_join_orders.tbl",
            "customers": "verus/research_loop/testdata/basic_inner_join_customers.tbl",
        },
        bench_limit=100_000,
        hot_path=_SYNTH_JOIN_HOT,
        bench_exec=(
            "synth_join_sum_hot("
            "&left.custkey, &left.amount, &right.custkey, &right.region)"
        ),
    ),
    "tpch_join_sum": BasicSqlJoinFixture(
        sql=(
            "SELECT SUM(l_extendedprice) FROM lineitem "
            "INNER JOIN orders ON l_orderkey = o_orderkey "
            "WHERE o_orderdate >= 19960101 AND o_orderdate <= 19961231"
        ),
        schema=dict(_TPCH_JOIN_SCHEMA),
        table_order=("lineitem", "orders"),
        ret_type="u64",
        run_query=_TPCH_JOIN_SUM,
        description="TPC-H lineitem INNER JOIN orders, 1996 date window",
        default_tbls={
            "lineitem": "data/tpch-sf1/lineitem.tbl",
            "orders": "data/tpch-sf1/orders.tbl",
        },
        bench_limit=50_000,
        hot_path=_TPCH_JOIN_HOT,
        bench_exec=(
            "tpch_join_sum_hot("
            "&left.l_orderkey, &left.l_extendedprice, "
            "&right.o_orderkey, &right.o_orderdate)"
        ),
    ),
    "left_join_sum": BasicSqlJoinFixture(
        sql=(
            "SELECT SUM(o.amount) FROM orders o "
            "LEFT JOIN customers c ON o.custkey = c.custkey "
            "WHERE c.region = 1"
        ),
        schema=dict(_SYNTHETIC_JOIN_SCHEMA),
        table_order=("orders", "customers"),
        ret_type="u64",
        run_query=_LEFT_JOIN_SUM,
        description="LEFT JOIN scalar SUM (TRUSTED spec + exec bridge)",
        default_tbls={
            "orders": "verus/research_loop/testdata/basic_left_join_orders.tbl",
            "customers": "verus/research_loop/testdata/basic_left_join_customers.tbl",
        },
        bench_limit=100_000,
        hot_path=_SYNTH_JOIN_HOT,
        bench_exec=(
            "synth_join_sum_hot("
            "&left.custkey, &left.amount, &right.custkey, &right.region)"
        ),
    ),
}

BASIC_SQL_JOIN_RETURN_TYPES: dict[str, str] = {
    key: fx.ret_type for key, fx in BASIC_SQL_JOIN_FIXTURES.items()
}

BASIC_SQL_JOIN_RUNQUERIES: dict[str, str] = {
    key: fx.run_query for key, fx in BASIC_SQL_JOIN_FIXTURES.items()
}
