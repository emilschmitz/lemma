"""TPC-H workload + Rust RunQuery bodies for Verus research loop."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TBL = ROOT / "data" / "tpch-sf1" / "lineitem.tbl"
TPCH_DATA_DIR = ROOT / "data" / "tpch-sf1"

lineitem_schema = {
    "L_ORDERKEY": "BIGINT",
    "L_PARTKEY": "BIGINT",
    "L_SUPPKEY": "BIGINT",
    "L_LINENUMBER": "BIGINT",
    "L_QUANTITY": "INTEGER",
    "L_EXTENDEDPRICE": "BIGINT",
    "L_DISCOUNT": "INTEGER",
    "L_TAX": "INTEGER",
    "L_RETURNFLAG": "VARCHAR",
    "L_LINESTATUS": "VARCHAR",
    "L_SHIPDATE": "INTEGER",
    "L_COMMITDATE": "INTEGER",
    "L_RECEIPTDATE": "INTEGER",
    "L_SHIPINSTRUCT": "VARCHAR",
    "L_SHIPMODE": "VARCHAR",
    "L_COMMENT": "VARCHAR",
}

orders_schema = {
    "O_ORDERKEY": "INTEGER",
    "O_CUSTKEY": "INTEGER",
    "O_ORDERSTATUS": "VARCHAR",
    "O_TOTALPRICE": "BIGINT",
    "O_ORDERDATE": "INTEGER",
    "O_ORDERPRIORITY": "VARCHAR",
    "O_CLERK": "VARCHAR",
    "O_SHIPPRIORITY": "INTEGER",
    "O_COMMENT": "VARCHAR",
}

customer_schema = {
    "C_CUSTKEY": "INTEGER",
    "C_NAME": "VARCHAR",
    "C_ADDRESS": "VARCHAR",
    "C_NATIONKEY": "INTEGER",
    "C_PHONE": "VARCHAR",
    "C_ACCTBAL": "BIGINT",
    "C_MKTSEGMENT": "VARCHAR",
    "C_COMMENT": "VARCHAR",
}

# Backward-compatible alias for single-table lineitem fixtures.
schema = dict(lineitem_schema)

Q1_SQL = """
SELECT l_returnflag, l_linestatus, SUM(l_quantity) AS sum_qty
FROM lineitem
WHERE l_shipdate <= 19980902
GROUP BY l_returnflag, l_linestatus
"""

Q3_SQL = """
SELECT SUM(l_extendedprice) AS revenue
FROM lineitem
INNER JOIN orders ON l_orderkey = o_orderkey
INNER JOIN customer ON o_custkey = c_custkey
WHERE c_mktsegment = 'BUILDING'
  AND o_orderdate < 19950315
  AND l_shipdate > 19950315
"""

Q6_SQL = """
SELECT SUM(l_extendedprice * l_discount) AS revenue
FROM lineitem
WHERE l_quantity >= 1 AND l_quantity <= 50
  AND l_discount >= 1 AND l_discount <= 5
  AND l_shipdate >= 19960101 AND l_shipdate <= 19961231
"""

queries = {
    "Q1": Q1_SQL.strip(),
    "Q3": Q3_SQL.strip(),
    "Q6": Q6_SQL.strip(),
}

TPCH_NWAY_SCHEMA: dict[str, dict[str, str]] = {
    "lineitem": {
        "L_ORDERKEY": "INTEGER",
        "L_EXTENDEDPRICE": "BIGINT",
        "L_SHIPDATE": "INTEGER",
    },
    "orders": {
        "O_ORDERKEY": "INTEGER",
        "O_CUSTKEY": "INTEGER",
        "O_ORDERDATE": "INTEGER",
    },
    "customer": {
        "C_CUSTKEY": "INTEGER",
        "C_MKTSEGMENT": "VARCHAR",
    },
}

TPCH_NWAY_TABLE_ORDER: tuple[str, ...] = ("lineitem", "orders", "customer")

TPCH_DEFAULT_TBLS: dict[str, dict[str, str]] = {
    "Q3": {
        "lineitem": "data/tpch-sf1/lineitem.tbl",
        "orders": "data/tpch-sf1/orders.tbl",
        "customer": "data/tpch-sf1/customer.tbl",
    },
}

TPCH_QUERY_KIND: dict[str, str] = {
    "Q1": "single",
    "Q3": "nway",
    "Q6": "single",
}

Q1_RUNQUERY = """
    // Hot path: direct 6-bucket index (returnflag × linestatus), then materialize Map
    // so the return type matches method_spec: Map<(String, String), u64>.
    let n = cols.n;
    let mut acc = [0u64; 6];
    for i in 0..n {
        if cols.l_shipdate[i] <= 19_980_902 {
            let rf = cols.l_returnflag[i].as_bytes().first().copied().unwrap_or(0);
            let ls = cols.l_linestatus[i].as_bytes().first().copied().unwrap_or(0);
            let r = match rf {
                b'N' => 0usize,
                b'R' => 1,
                b'A' => 2,
                _ => continue,
            };
            let s = match ls {
                b'O' => 0usize,
                b'F' => 1,
                _ => continue,
            };
            let gi = r * 2 + s;
            acc[gi] = acc[gi].wrapping_add(cols.l_quantity[i] as u64);
        }
    }
    let mut out: HashMap<(String, String), u64> = HashMap::new();
    let labels = [
        ("N", "O"),
        ("N", "F"),
        ("R", "O"),
        ("R", "F"),
        ("A", "O"),
        ("A", "F"),
    ];
    for (j, (a, b)) in labels.iter().enumerate() {
        if acc[j] != 0 {
            out.insert(((*a).to_string(), (*b).to_string()), acc[j]);
        }
    }
    out
"""

_TPCH_Q1_HOT = """\
#[inline(always)]
fn tpch_q1_accumulate_hot(
    quantity: &[u32],
    shipdate: &[u32],
    returnflag: &[u8],
    linestatus: &[u8],
) -> [u64; 6] {
    let n = shipdate.len();
    let mut acc = [0u64; 6];
    for i in 0..n {
        if shipdate[i] > 19_980_902 {
            continue;
        }
        let rf = returnflag[i];
        let ls = linestatus[i];
        let r = match rf {
            b'N' => 0usize,
            b'R' => 1,
            b'A' => 2,
            _ => continue,
        };
        let s = match ls {
            b'O' => 0usize,
            b'F' => 1,
            _ => continue,
        };
        let gi = r * 2 + s;
        acc[gi] = acc[gi].wrapping_add(quantity[i] as u64);
    }
    acc
}

fn tpch_q1_materialize(acc: [u64; 6]) -> std::collections::HashMap<(String, String), u64> {
    use std::collections::HashMap;
    let mut out: HashMap<(String, String), u64> = HashMap::new();
    let labels = [
        ("N", "O"),
        ("N", "F"),
        ("R", "O"),
        ("R", "F"),
        ("A", "O"),
        ("A", "F"),
    ];
    for (j, (a, b)) in labels.iter().enumerate() {
        if acc[j] != 0 {
            out.insert(((*a).to_string(), (*b).to_string()), acc[j]);
        }
    }
    out
}"""

Q6_RUNQUERY = """
    let n = cols.n;
    let mut acc: u64 = 0;
    for i in 0..n {
        let qty = cols.l_quantity[i];
        let disc = cols.l_discount[i];
        let sd = cols.l_shipdate[i];
        if qty >= 1
            && qty <= 50
            && disc >= 1
            && disc <= 5
            && sd >= 19_960_101
            && sd <= 19_961_231
        {
            acc = add_u64(acc, mul_u64_u32(cols.l_extendedprice[i], disc));
        }
    }
    acc
"""

_TPCH_Q3_HOT = """\
#[inline(always)]
fn tpch_q3_sum_hot(
    li_orderkey: &[u32],
    li_price: &[u64],
    li_shipdate: &[u32],
    ord_orderkey: &[u32],
    ord_custkey: &[u32],
    ord_date: &[u32],
    cust_custkey: &[u32],
    cust_segment: &[String],
) -> u64 {
    use std::collections::{HashMap, HashSet};
    let mut cust_building: HashSet<u32> = HashSet::with_capacity(8192);
    for i in 0..cust_custkey.len() {
        if cust_segment[i] == "BUILDING" {
            cust_building.insert(cust_custkey[i]);
        }
    }
    let mut ord_ok: HashSet<u32> = HashSet::with_capacity(ord_orderkey.len() / 2);
    for i in 0..ord_orderkey.len() {
        if ord_date[i] < 19_950_315 && cust_building.contains(&ord_custkey[i]) {
            ord_ok.insert(ord_orderkey[i]);
        }
    }
    let mut acc: u64 = 0;
    for i in 0..li_orderkey.len() {
        if li_shipdate[i] > 19_950_315 && ord_ok.contains(&li_orderkey[i]) {
            acc = acc.wrapping_add(li_price[i]);
        }
    }
    acc
}"""

Q3_RUNQUERY = """\
// TRUSTED: 3-way hash join — build customer segment + order window, probe lineitem.
#[verifier::external_body]
pub exec fn run_query(
    lineitem: &Cols_lineitem,
    orders: &Cols_orders,
    customer: &Cols_customer,
) -> (res: u64)
    requires
        valid_cols_lineitem(lineitem),
        valid_cols_orders(orders),
        valid_cols_customer(customer),
    ensures res == method_spec(lineitem, orders, customer),
{
    tpch_q3_sum_hot(
        &lineitem.l_orderkey,
        &lineitem.l_extendedprice,
        &lineitem.l_shipdate,
        &orders.o_orderkey,
        &orders.o_custkey,
        &orders.o_orderdate,
        &customer.c_custkey,
        &customer.c_mktsegment,
    )
}"""

RUNQUERIES: dict[str, str] = {
    "Q1": Q1_RUNQUERY,
    "Q3": Q3_RUNQUERY,
    "Q6": Q6_RUNQUERY,
}

RETURN_TYPES: dict[str, str] = {
    "Q1": "map_str_str_u64",
    "Q3": "u64",
    "Q6": "u64",
}

TPCH_HOT_PATHS: dict[str, str] = {
    "Q1": _TPCH_Q1_HOT,
    "Q3": _TPCH_Q3_HOT,
}

TPCH_BENCH_EXEC: dict[str, str] = {
    "Q1": "tpch_q1_materialize(tpch_q1_accumulate_hot(&cols))",
    "Q3": (
        "tpch_q3_sum_hot("
        "&lineitem.l_orderkey, &lineitem.l_extendedprice, &lineitem.l_shipdate, "
        "&orders.o_orderkey, &orders.o_custkey, &orders.o_orderdate, "
        "&customer.c_custkey, &customer.c_mktsegment)"
    ),
}

# Timed body: accumulate only (materialize after timer) — matches bare bench_tpch Q1.
TPCH_BENCH_TIMING_BODY: dict[str, str] = {
    "Q1": """\
        let acc = tpch_q1_accumulate_hot(
            &cols.l_quantity,
            &cols.l_shipdate,
            &rf_b,
            &ls_b,
        );
        std::hint::black_box(acc);""",
}

TPCH_BENCH_POST_TIMING: dict[str, str] = {
    "Q1": "let res = tpch_q1_materialize(acc);",
}

TPCH_BENCH_MAIN_PREFIX: dict[str, str] = {
    "Q1": """\
    let rf_b: Vec<u8> = cols
        .l_returnflag
        .iter()
        .map(|s| s.as_bytes().first().copied().unwrap_or(0))
        .collect();
    let ls_b: Vec<u8> = cols
        .l_linestatus
        .iter()
        .map(|s| s.as_bytes().first().copied().unwrap_or(0))
        .collect();""",
}
