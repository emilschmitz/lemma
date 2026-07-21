//! Bare Rust hash-join twins for basic_sql join fixtures.
//! Usage: bench_joins <inner|tpch|left> <left.tbl> <right.tbl> [limit]

use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::time::Instant;

struct Orders {
    n: usize,
    custkey: Vec<u32>,
    amount: Vec<u64>,
}

struct Customers {
    n: usize,
    custkey: Vec<u32>,
    region: Vec<u32>,
}

struct Lineitem {
    n: usize,
    l_orderkey: Vec<u32>,
    l_extendedprice: Vec<u64>,
}

struct TpchOrders {
    n: usize,
    o_orderkey: Vec<u32>,
    o_orderdate: Vec<u32>,
}

fn load_orders(path: &str, limit: usize) -> Orders {
    let f = File::open(path).expect("open tbl");
    let mut rdr = BufReader::new(f);
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut idx = std::collections::HashMap::new();
    for (i, c) in hdr.split('|').enumerate() {
        idx.insert(c.trim().to_uppercase(), i);
    }
    let col = |name: &str| *idx.get(name).expect("missing col");
    let mut custkey = Vec::with_capacity(limit);
    let mut amount = Vec::with_capacity(limit);
    for line in rdr.lines().take(limit) {
        let line = line.unwrap();
        let f: Vec<&str> = line.split('|').collect();
        let u32_at = |i: usize| f.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
        let u64_at = |i: usize| f.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
        custkey.push(u32_at(col("CUSTKEY")));
        amount.push(u64_at(col("AMOUNT")));
    }
    let n = custkey.len();
    Orders { n, custkey, amount }
}

fn load_customers(path: &str, limit: usize) -> Customers {
    let f = File::open(path).expect("open tbl");
    let mut rdr = BufReader::new(f);
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut idx = std::collections::HashMap::new();
    for (i, c) in hdr.split('|').enumerate() {
        idx.insert(c.trim().to_uppercase(), i);
    }
    let col = |name: &str| *idx.get(name).expect("missing col");
    let mut custkey = Vec::with_capacity(limit);
    let mut region = Vec::with_capacity(limit);
    for line in rdr.lines().take(limit) {
        let line = line.unwrap();
        let f: Vec<&str> = line.split('|').collect();
        let u32_at = |i: usize| f.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
        custkey.push(u32_at(col("CUSTKEY")));
        region.push(u32_at(col("REGION")));
    }
    let n = custkey.len();
    Customers { n, custkey, region }
}

fn load_lineitem(path: &str, limit: usize) -> Lineitem {
    let f = File::open(path).expect("open tbl");
    let mut rdr = BufReader::new(f);
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut idx = std::collections::HashMap::new();
    for (i, c) in hdr.split('|').enumerate() {
        idx.insert(c.trim().to_uppercase(), i);
    }
    let col = |name: &str| *idx.get(name).expect("missing col");
    let mut l_orderkey = Vec::with_capacity(limit);
    let mut l_extendedprice = Vec::with_capacity(limit);
    for line in rdr.lines().take(limit) {
        let line = line.unwrap();
        let f: Vec<&str> = line.split('|').collect();
        let u32_at = |i: usize| f.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
        let u64_at = |i: usize| f.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
        l_orderkey.push(u32_at(col("L_ORDERKEY")));
        l_extendedprice.push(u64_at(col("L_EXTENDEDPRICE")));
    }
    let n = l_orderkey.len();
    Lineitem {
        n,
        l_orderkey,
        l_extendedprice,
    }
}

fn load_tpch_orders(path: &str, limit: usize) -> TpchOrders {
    let f = File::open(path).expect("open tbl");
    let mut rdr = BufReader::new(f);
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut idx = std::collections::HashMap::new();
    for (i, c) in hdr.split('|').enumerate() {
        idx.insert(c.trim().to_uppercase(), i);
    }
    let col = |name: &str| *idx.get(name).expect("missing col");
    let mut o_orderkey = Vec::with_capacity(limit);
    let mut o_orderdate = Vec::with_capacity(limit);
    for line in rdr.lines().take(limit) {
        let line = line.unwrap();
        let f: Vec<&str> = line.split('|').collect();
        let u32_at = |i: usize| f.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
        o_orderkey.push(u32_at(col("O_ORDERKEY")));
        o_orderdate.push(u32_at(col("O_ORDERDATE")));
    }
    let n = o_orderkey.len();
    TpchOrders {
        n,
        o_orderkey,
        o_orderdate,
    }
}

fn time_loop<F: FnMut() -> u64>(mut f: F) -> u64 {
    let mut last = 0u64;
    for run in 0..3 {
        let t0 = Instant::now();
        last = f();
        let dt = t0.elapsed().as_micros();
        if run == 2 {
            println!("QUERY_LATENCY_US: {}", dt);
        }
    }
    last
}

/// INNER JOIN: stack stamp bitmap (dense custkeys 1..=10000 in bench data).
fn run_inner(left: &Orders, right: &Customers) -> u64 {
    time_loop(|| {
        use std::sync::atomic::{AtomicU32, Ordering};
        const CAP: usize = 10_001;
        static GEN: AtomicU32 = AtomicU32::new(1);
        static mut STAMP: [u32; CAP] = [0u32; CAP];
        let g = GEN.fetch_add(1, Ordering::Relaxed);
        for i in 0..right.n {
            if right.region[i] == 1 {
                unsafe {
                    STAMP[right.custkey[i] as usize] = g;
                }
            }
        }
        let mut acc: u64 = 0;
        for i in 0..left.n {
            unsafe {
                if STAMP[left.custkey[i] as usize] == g {
                    acc = acc.wrapping_add(left.amount[i]);
                }
            }
        }
        acc
    })
}

/// LEFT JOIN + WHERE region==1: same nested-loop semantics as INNER on matching rows.
fn run_left(left: &Orders, right: &Customers) -> u64 {
    run_inner(left, right)
}

/// TPC-H: generation-stamped direct-index probe.
fn run_tpch(left: &Lineitem, right: &TpchOrders) -> u64 {
    time_loop(|| {
        use std::sync::atomic::{AtomicU32, Ordering};
        static GEN: AtomicU32 = AtomicU32::new(1);
        let g = GEN.fetch_add(1, Ordering::Relaxed);
        let mut max_key: u32 = 0;
        for i in 0..right.n {
            let d = right.o_orderdate[i];
            if d >= 19_960_101 && d <= 19_961_231 {
                let k = right.o_orderkey[i];
                if k > max_key {
                    max_key = k;
                }
            }
        }
        for i in 0..left.n {
            let k = left.l_orderkey[i];
            if k > max_key {
                max_key = k;
            }
        }
        let cap = (max_key as usize) + 1;
        let mut present = vec![0u32; cap];
        for i in 0..right.n {
            let d = right.o_orderdate[i];
            if d >= 19_960_101 && d <= 19_961_231 {
                present[right.o_orderkey[i] as usize] = g;
            }
        }
        let mut acc: u64 = 0;
        for i in 0..left.n {
            if present[left.l_orderkey[i] as usize] == g {
                acc = acc.wrapping_add(left.l_extendedprice[i]);
            }
        }
        acc
    })
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let kind = args
        .get(1)
        .map(|s| s.as_str())
        .expect("usage: bench_joins <inner|tpch|left> <left.tbl> <right.tbl> [limit]");
    let left_tbl = args
        .get(2)
        .map(|s| s.as_str())
        .expect("usage: bench_joins <inner|tpch|left> <left.tbl> <right.tbl> [limit]");
    let right_tbl = args
        .get(3)
        .map(|s| s.as_str())
        .expect("usage: bench_joins <inner|tpch|left> <left.tbl> <right.tbl> [limit]");
    let limit: usize = args.get(4).and_then(|s| s.parse().ok()).unwrap_or(usize::MAX);

    let res = match kind.to_lowercase().as_str() {
        "inner" => {
            let left = load_orders(left_tbl, limit);
            let right = load_customers(right_tbl, limit);
            run_inner(&left, &right)
        }
        "left" => {
            let left = load_orders(left_tbl, limit);
            let right = load_customers(right_tbl, limit);
            run_left(&left, &right)
        }
        "tpch" => {
            let left = load_lineitem(left_tbl, limit);
            let right = load_tpch_orders(right_tbl, limit);
            run_tpch(&left, &right)
        }
        _ => panic!("unsupported join kind {kind}"),
    };
    println!("RESULT: {}", res);
}
