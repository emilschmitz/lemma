//! Hand-tuned bare Rust for SSB flat queries (no Dafny). Usage: bench_q <idx> <tbl> [limit]

use std::collections::HashMap;
use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::time::Instant;

struct Cols {
    lo_orderdate: Vec<u32>,
    lo_discount: Vec<u32>,
    lo_quantity: Vec<u32>,
    lo_extendedprice: Vec<u64>,
    lo_revenue: Vec<u64>,
    lo_supplycost: Vec<u64>,
    d_year: Vec<u32>,
    d_weeknuminyear: Vec<u32>,
    p_brand: Vec<String>,
    p_size: Vec<u32>,
    p_category: Vec<String>,
    p_mfgr: Vec<String>,
    c_region: Vec<String>,
    c_nation: Vec<String>,
    c_city: Vec<String>,
    s_region: Vec<String>,
    s_nation: Vec<String>,
    s_city: Vec<String>,
}

fn strip_quotes(s: &str) -> String {
    s.trim_matches('"').to_string()
}

fn load(tbl_path: &str, limit: usize) -> Cols {
    let f = File::open(tbl_path).expect("open .tbl");
    let mut rdr = BufReader::new(f);
    let mut hdr = String::new();
    rdr.read_line(&mut hdr).unwrap();
    let mut idx: HashMap<String, usize> = HashMap::new();
    for (i, c) in hdr.split('|').enumerate() {
        idx.insert(c.trim().to_uppercase(), i);
    }
    let col = |name: &str| *idx.get(name).expect("missing col");

    let mut out = Cols {
        lo_orderdate: Vec::new(),
        lo_discount: Vec::new(),
        lo_quantity: Vec::new(),
        lo_extendedprice: Vec::new(),
        lo_revenue: Vec::new(),
        lo_supplycost: Vec::new(),
        d_year: Vec::new(),
        d_weeknuminyear: Vec::new(),
        p_brand: Vec::new(),
        p_size: Vec::new(),
        p_category: Vec::new(),
        p_mfgr: Vec::new(),
        c_region: Vec::new(),
        c_nation: Vec::new(),
        c_city: Vec::new(),
        s_region: Vec::new(),
        s_nation: Vec::new(),
        s_city: Vec::new(),
    };

    for line in rdr.lines().take(limit) {
        let line = line.unwrap();
        let f: Vec<&str> = line.split('|').collect();
        let u32_at = |i: usize| f.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
        let u64_at = |i: usize| f.get(i).and_then(|s| s.parse().ok()).unwrap_or(0);
        let str_at = |i: usize| -> String {
            f.get(i).map(|s| strip_quotes(s)).unwrap_or_default()
        };

        out.lo_orderdate.push(u32_at(col("LO_ORDERDATE")));
        out.lo_discount.push(u32_at(col("LO_DISCOUNT")));
        out.lo_quantity.push(u32_at(col("LO_QUANTITY")));
        out.lo_extendedprice.push(u64_at(col("LO_EXTENDEDPRICE")));
        out.lo_revenue.push(u64_at(col("LO_REVENUE")));
        out.lo_supplycost.push(u64_at(col("LO_SUPPLYCOST")));
        out.d_year.push(u32_at(col("D_YEAR")));
        out.d_weeknuminyear.push(u32_at(col("D_WEEKNUMINYEAR")));
        out.p_brand.push(str_at(col("P_BRAND")));
        out.p_size.push(u32_at(col("P_SIZE")));
        out.p_category.push(str_at(col("P_CATEGORY")));
        out.p_mfgr.push(str_at(col("P_MFGR")));
        out.c_region.push(str_at(col("C_REGION")));
        out.c_nation.push(str_at(col("C_NATION")));
        out.c_city.push(str_at(col("C_CITY")));
        out.s_region.push(str_at(col("S_REGION")));
        out.s_nation.push(str_at(col("S_NATION")));
        out.s_city.push(str_at(col("S_CITY")));
    }
    out
}

fn time_loop<F: FnMut()>(mut f: F) {
    for run in 0..3 {
        let t0 = Instant::now();
        f();
        let dt = t0.elapsed().as_micros();
        if run == 2 {
            println!("QUERY_LATENCY_US: {}", dt);
        }
    }
}

fn run_q1(c: &Cols) {
    time_loop(|| {
        let mut acc: u64 = 0;
        for i in 0..c.lo_orderdate.len() {
            let od = c.lo_orderdate[i];
            let disc = c.lo_discount[i];
            let qty = c.lo_quantity[i];
            if (1_993_0101..=1_993_1231).contains(&od)
                && (1..=3).contains(&disc)
                && qty < 25
            {
                acc = acc.wrapping_add(c.lo_extendedprice[i].wrapping_mul(disc as u64));
            }
        }
        std::hint::black_box(acc);
    });
}

fn run_q2(c: &Cols) {
    time_loop(|| {
        let mut acc: u64 = 0;
        for i in 0..c.lo_orderdate.len() {
            let od = c.lo_orderdate[i];
            let disc = c.lo_discount[i];
            let qty = c.lo_quantity[i];
            if (1_994_0101..=1_994_0131).contains(&od)
                && (4..=6).contains(&disc)
                && (26..=35).contains(&qty)
            {
                acc = acc.wrapping_add(c.lo_extendedprice[i].wrapping_mul(disc as u64));
            }
        }
        std::hint::black_box(acc);
    });
}

fn run_q3(c: &Cols) {
    time_loop(|| {
        let mut acc: u64 = 0;
        for i in 0..c.lo_orderdate.len() {
            let disc = c.lo_discount[i];
            let qty = c.lo_quantity[i];
            if c.d_weeknuminyear[i] == 6
                && c.d_year[i] == 1994
                && (5..=7).contains(&disc)
                && (26..=35).contains(&qty)
            {
                acc = acc.wrapping_add(c.lo_extendedprice[i].wrapping_mul(disc as u64));
            }
        }
        std::hint::black_box(acc);
    });
}

fn run_q4(c: &Cols) {
    time_loop(|| {
        let mut acc: HashMap<(u32, String), u64> = HashMap::new();
        for i in 0..c.lo_orderdate.len() {
            if c.p_category[i] == "MFGR#12" && c.s_region[i] == "AMERICA" {
                let key = (c.d_year[i], c.p_brand[i].clone());
                *acc.entry(key).or_insert(0) += c.lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q5(c: &Cols) {
    time_loop(|| {
        let mut acc: HashMap<(u32, String), u64> = HashMap::new();
        for i in 0..c.lo_orderdate.len() {
            if c.p_brand[i] == "MFGR#2221" && c.p_size[i] >= 10 && c.s_region[i] == "ASIA" {
                let key = (c.d_year[i], c.p_brand[i].clone());
                *acc.entry(key).or_insert(0) += c.lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q6(c: &Cols) {
    time_loop(|| {
        let mut acc: HashMap<(u32, String), u64> = HashMap::new();
        for i in 0..c.lo_orderdate.len() {
            if c.p_brand[i] == "MFGR#2221" && c.s_region[i] == "EUROPE" {
                let key = (c.d_year[i], c.p_brand[i].clone());
                *acc.entry(key).or_insert(0) += c.lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q10(c: &Cols) {
    time_loop(|| {
        let mut acc: HashMap<(String, String, u32), u64> = HashMap::new();
        for i in 0..c.lo_orderdate.len() {
            let od = c.lo_orderdate[i];
            if c.c_city[i] == "UNITED KI1"
                && c.s_city[i] == "UNITED KI5"
                && (1_997_1201..=1_997_1231).contains(&od)
            {
                let key = (c.c_city[i].clone(), c.s_city[i].clone(), c.d_year[i]);
                *acc.entry(key).or_insert(0) += c.lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q11(c: &Cols) {
    time_loop(|| {
        let mut acc: HashMap<(u32, String), i128> = HashMap::new();
        for i in 0..c.lo_orderdate.len() {
            if c.c_region[i] == "AMERICA"
                && c.s_region[i] == "AMERICA"
                && c.p_mfgr[i] == "MFGR#1"
            {
                let key = (c.d_year[i], c.c_nation[i].clone());
                let v = c.lo_revenue[i] as i128 - c.lo_supplycost[i] as i128;
                *acc.entry(key).or_insert(0) += v;
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q13(c: &Cols) {
    time_loop(|| {
        let mut acc: HashMap<(u32, String, String), i128> = HashMap::new();
        for i in 0..c.lo_orderdate.len() {
            let od = c.lo_orderdate[i];
            if c.c_region[i] == "AMERICA"
                && c.s_nation[i] == "UNITED STATES"
                && (1_997_0101..=1_997_1231).contains(&od)
                && c.p_category[i] == "MFGR#14"
            {
                let key = (c.d_year[i], c.s_nation[i].clone(), c.p_category[i].clone());
                let v = c.lo_revenue[i] as i128 - c.lo_supplycost[i] as i128;
                *acc.entry(key).or_insert(0) += v;
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let qidx: u32 = args.get(1).and_then(|s| s.parse().ok()).expect("usage: bench_q <idx> <tbl> [limit]");
    let tbl = args.get(2).map(|s| s.as_str()).unwrap_or("ssb-dbgen/lineorder_flat.tbl");
    let limit: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(50_000);
    let cols = load(tbl, limit);
    match qidx {
        1 => run_q1(&cols),
        2 => run_q2(&cols),
        3 => run_q3(&cols),
        4 => run_q4(&cols),
        5 => run_q5(&cols),
        6 => run_q6(&cols),
        10 => run_q10(&cols),
        11 => run_q11(&cols),
        13 => run_q13(&cols),
        _ => panic!("unsupported query index {qidx}"),
    }
}
