//! Hand-tuned bare Rust for SSB flat queries (no Dafny). Usage: bench_q <idx> <tbl> [limit]
//!
//! Loads only columns each query reads (matches verified column projection).

use std::collections::HashMap;
use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::time::Instant;

fn strip_quotes(s: &str) -> &str {
    s.trim_matches('"')
}

use std::io::Read;

fn u32_at(idx: &HashMap<String, usize>, fields: &[&str], name: &str) -> u32 {
    fields
        .get(*idx.get(name).expect("missing col"))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0)
}

fn u64_at(idx: &HashMap<String, usize>, fields: &[&str], name: &str) -> u64 {
    fields
        .get(*idx.get(name).expect("missing col"))
        .and_then(|s| s.parse().ok())
        .unwrap_or(0)
}

fn str_at(idx: &HashMap<String, usize>, fields: &[&str], name: &str) -> String {
    let s = fields.get(*idx.get(name).expect("missing col")).copied().unwrap_or("");
    strip_quotes(s).to_string()
}

struct TableLoader {
    rdr: BufReader<File>,
    idx: HashMap<String, usize>,
}

impl TableLoader {
    fn open(tbl: &str) -> Self {
        let f = File::open(tbl).expect("open .tbl");
        let mut rdr = BufReader::new(f);
        let mut hdr = String::new();
        rdr.read_line(&mut hdr).unwrap();
        let mut idx = HashMap::new();
        for (i, c) in hdr.split('|').enumerate() {
            idx.insert(c.trim().to_uppercase(), i);
        }
        Self { rdr, idx }
    }

    fn read_rows<F>(&mut self, limit: usize, mut row: F)
    where
        F: FnMut(&HashMap<String, usize>, &[&str]),
    {
        for line in self.rdr.by_ref().lines().take(limit) {
            let line = line.unwrap();
            let fields: Vec<&str> = line.split('|').collect();
            if fields.is_empty() {
                continue;
            }
            row(&self.idx, &fields);
        }
    }
}

fn time_loop<F: FnMut()>(mut f: F) {
    let mut times = [0u128; 5];
    for t in &mut times {
        let t0 = Instant::now();
        f();
        *t = t0.elapsed().as_micros();
    }
    times.sort();
    println!("QUERY_LATENCY_US: {}", times[times.len() / 2]);
}

fn run_q1(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut lo_discount = Vec::with_capacity(limit);
    let mut lo_quantity = Vec::with_capacity(limit);
    let mut lo_extendedprice = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        lo_discount.push(u32_at(idx, f, "LO_DISCOUNT"));
        lo_quantity.push(u32_at(idx, f, "LO_QUANTITY"));
        lo_extendedprice.push(u64_at(idx, f, "LO_EXTENDEDPRICE"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: u64 = 0;
        for i in 0..n {
            let od = lo_orderdate[i];
            let disc = lo_discount[i];
            let qty = lo_quantity[i];
            if od >= 1_993_0101 && od <= 1_993_1231 && disc >= 1 && disc <= 3 && qty < 25 {
                acc = acc.wrapping_add(lo_extendedprice[i].wrapping_mul(disc as u64));
            }
        }
        std::hint::black_box(acc);
    });
}

fn run_q2(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut lo_discount = Vec::with_capacity(limit);
    let mut lo_quantity = Vec::with_capacity(limit);
    let mut lo_extendedprice = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        lo_discount.push(u32_at(idx, f, "LO_DISCOUNT"));
        lo_quantity.push(u32_at(idx, f, "LO_QUANTITY"));
        lo_extendedprice.push(u64_at(idx, f, "LO_EXTENDEDPRICE"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: u64 = 0;
        for i in 0..n {
            let od = lo_orderdate[i];
            let disc = lo_discount[i];
            let qty = lo_quantity[i];
            if od >= 1_994_0101 && od <= 1_994_0131 && disc >= 4 && disc <= 6 && qty >= 26 && qty <= 35 {
                acc = acc.wrapping_add(lo_extendedprice[i].wrapping_mul(disc as u64));
            }
        }
        std::hint::black_box(acc);
    });
}

fn run_q3(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut d_weeknuminyear = Vec::with_capacity(limit);
    let mut d_year = Vec::with_capacity(limit);
    let mut lo_discount = Vec::with_capacity(limit);
    let mut lo_quantity = Vec::with_capacity(limit);
    let mut lo_extendedprice = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        d_weeknuminyear.push(u32_at(idx, f, "D_WEEKNUMINYEAR"));
        d_year.push(u32_at(idx, f, "D_YEAR"));
        lo_discount.push(u32_at(idx, f, "LO_DISCOUNT"));
        lo_quantity.push(u32_at(idx, f, "LO_QUANTITY"));
        lo_extendedprice.push(u64_at(idx, f, "LO_EXTENDEDPRICE"));
    });
    let n = d_year.len();
    time_loop(|| {
        let mut acc: u64 = 0;
        for i in 0..n {
            if d_weeknuminyear[i] == 6
                && d_year[i] == 1994
                && lo_discount[i] >= 5
                && lo_discount[i] <= 7
                && lo_quantity[i] >= 26
                && lo_quantity[i] <= 35
            {
                acc = acc.wrapping_add(lo_extendedprice[i].wrapping_mul(lo_discount[i] as u64));
            }
        }
        std::hint::black_box(acc);
    });
}

fn run_q4(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut d_year = Vec::with_capacity(limit);
    let mut p_brand = Vec::with_capacity(limit);
    let mut p_category = Vec::with_capacity(limit);
    let mut s_region = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        d_year.push(u32_at(idx, f, "D_YEAR"));
        p_brand.push(str_at(idx, f, "P_BRAND"));
        p_category.push(str_at(idx, f, "P_CATEGORY"));
        s_region.push(str_at(idx, f, "S_REGION"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
    });
    let n = d_year.len();
    time_loop(|| {
        let mut acc: HashMap<(u32, String), u64> = HashMap::new();
        for i in 0..n {
            if p_category[i] == "MFGR#12" && s_region[i] == "AMERICA" {
                let key = (d_year[i], p_brand[i].clone());
                *acc.entry(key).or_insert(0) += lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q5(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut d_year = Vec::with_capacity(limit);
    let mut p_brand = Vec::with_capacity(limit);
    let mut p_size = Vec::with_capacity(limit);
    let mut s_region = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        d_year.push(u32_at(idx, f, "D_YEAR"));
        p_brand.push(str_at(idx, f, "P_BRAND"));
        p_size.push(u32_at(idx, f, "P_SIZE"));
        s_region.push(str_at(idx, f, "S_REGION"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
    });
    let n = d_year.len();
    time_loop(|| {
        let mut acc: HashMap<(u32, String), u64> = HashMap::new();
        for i in 0..n {
            if p_brand[i] == "MFGR#2221" && p_size[i] >= 10 && s_region[i] == "ASIA" {
                let key = (d_year[i], p_brand[i].clone());
                *acc.entry(key).or_insert(0) += lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q6(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut d_year = Vec::with_capacity(limit);
    let mut p_brand = Vec::with_capacity(limit);
    let mut s_region = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        d_year.push(u32_at(idx, f, "D_YEAR"));
        p_brand.push(str_at(idx, f, "P_BRAND"));
        s_region.push(str_at(idx, f, "S_REGION"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
    });
    let n = d_year.len();
    time_loop(|| {
        let mut acc: HashMap<(u32, String), u64> = HashMap::new();
        for i in 0..n {
            if p_brand[i] == "MFGR#2221" && s_region[i] == "EUROPE" {
                let key = (d_year[i], p_brand[i].clone());
                *acc.entry(key).or_insert(0) += lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q7(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut c_nation = Vec::with_capacity(limit);
    let mut s_nation = Vec::with_capacity(limit);
    let mut c_region = Vec::with_capacity(limit);
    let mut s_region = Vec::with_capacity(limit);
    let mut d_year = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        c_nation.push(str_at(idx, f, "C_NATION"));
        s_nation.push(str_at(idx, f, "S_NATION"));
        c_region.push(str_at(idx, f, "C_REGION"));
        s_region.push(str_at(idx, f, "S_REGION"));
        d_year.push(u32_at(idx, f, "D_YEAR"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: HashMap<(String, String, u32), u64> = HashMap::new();
        for i in 0..n {
            let od = lo_orderdate[i];
            if c_region[i] == "ASIA" && s_region[i] == "ASIA" && od >= 1_992_0101 && od <= 1_997_1231 {
                let key = (c_nation[i].clone(), s_nation[i].clone(), d_year[i]);
                *acc.entry(key).or_insert(0) += lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q8(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut c_city = Vec::with_capacity(limit);
    let mut s_city = Vec::with_capacity(limit);
    let mut c_nation = Vec::with_capacity(limit);
    let mut s_nation = Vec::with_capacity(limit);
    let mut d_year = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        c_city.push(str_at(idx, f, "C_CITY"));
        s_city.push(str_at(idx, f, "S_CITY"));
        c_nation.push(str_at(idx, f, "C_NATION"));
        s_nation.push(str_at(idx, f, "S_NATION"));
        d_year.push(u32_at(idx, f, "D_YEAR"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: HashMap<(String, String, u32), u64> = HashMap::new();
        for i in 0..n {
            let od = lo_orderdate[i];
            if c_nation[i] == "UNITED STATES"
                && s_nation[i] == "UNITED STATES"
                && od >= 1_992_0101
                && od <= 1_997_1231
            {
                let key = (c_city[i].clone(), s_city[i].clone(), d_year[i]);
                *acc.entry(key).or_insert(0) += lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q9(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut c_city = Vec::with_capacity(limit);
    let mut s_city = Vec::with_capacity(limit);
    let mut d_year = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        c_city.push(str_at(idx, f, "C_CITY"));
        s_city.push(str_at(idx, f, "S_CITY"));
        d_year.push(u32_at(idx, f, "D_YEAR"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: HashMap<(String, String, u32), u64> = HashMap::new();
        for i in 0..n {
            let od = lo_orderdate[i];
            if c_city[i] == "UNITED KI1" && s_city[i] == "UNITED KI5" && od >= 1_992_0101 && od <= 1_997_1231 {
                let key = (c_city[i].clone(), s_city[i].clone(), d_year[i]);
                *acc.entry(key).or_insert(0) += lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q10(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut c_city = Vec::with_capacity(limit);
    let mut s_city = Vec::with_capacity(limit);
    let mut d_year = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        c_city.push(str_at(idx, f, "C_CITY"));
        s_city.push(str_at(idx, f, "S_CITY"));
        d_year.push(u32_at(idx, f, "D_YEAR"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: HashMap<(String, String, u32), u64> = HashMap::new();
        for i in 0..n {
            let od = lo_orderdate[i];
            if od >= 1_997_1201 && od <= 1_997_1231 && c_city[i] == "UNITED KI1" && s_city[i] == "UNITED KI5" {
                let key = (c_city[i].clone(), s_city[i].clone(), d_year[i]);
                *acc.entry(key).or_insert(0) += lo_revenue[i];
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q11(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut d_year = Vec::with_capacity(limit);
    let mut c_nation = Vec::with_capacity(limit);
    let mut c_region = Vec::with_capacity(limit);
    let mut s_region = Vec::with_capacity(limit);
    let mut p_mfgr = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    let mut lo_supplycost = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        d_year.push(u32_at(idx, f, "D_YEAR"));
        c_nation.push(str_at(idx, f, "C_NATION"));
        c_region.push(str_at(idx, f, "C_REGION"));
        s_region.push(str_at(idx, f, "S_REGION"));
        p_mfgr.push(str_at(idx, f, "P_MFGR"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
        lo_supplycost.push(u64_at(idx, f, "LO_SUPPLYCOST"));
    });
    let n = d_year.len();
    time_loop(|| {
        let mut acc: HashMap<(u32, String), i128> = HashMap::new();
        for i in 0..n {
            if c_region[i] == "AMERICA" && s_region[i] == "AMERICA" && p_mfgr[i] == "MFGR#1" {
                let key = (d_year[i], c_nation[i].clone());
                let v = lo_revenue[i] as i128 - lo_supplycost[i] as i128;
                *acc.entry(key).or_insert(0) += v;
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q12(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut d_year = Vec::with_capacity(limit);
    let mut c_nation = Vec::with_capacity(limit);
    let mut c_region = Vec::with_capacity(limit);
    let mut s_region = Vec::with_capacity(limit);
    let mut p_mfgr = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    let mut lo_supplycost = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        d_year.push(u32_at(idx, f, "D_YEAR"));
        c_nation.push(str_at(idx, f, "C_NATION"));
        c_region.push(str_at(idx, f, "C_REGION"));
        s_region.push(str_at(idx, f, "S_REGION"));
        p_mfgr.push(str_at(idx, f, "P_MFGR"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
        lo_supplycost.push(u64_at(idx, f, "LO_SUPPLYCOST"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: HashMap<(u32, String), i128> = HashMap::new();
        for i in 0..n {
            let od = lo_orderdate[i];
            if c_region[i] == "AMERICA"
                && s_region[i] == "AMERICA"
                && p_mfgr[i] == "MFGR#1"
                && od >= 1_997_0101
                && od <= 1_998_1231
            {
                let key = (d_year[i], c_nation[i].clone());
                let v = lo_revenue[i] as i128 - lo_supplycost[i] as i128;
                *acc.entry(key).or_insert(0) += v;
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q13(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut d_year = Vec::with_capacity(limit);
    let mut s_nation = Vec::with_capacity(limit);
    let mut c_region = Vec::with_capacity(limit);
    let mut p_category = Vec::with_capacity(limit);
    let mut lo_revenue = Vec::with_capacity(limit);
    let mut lo_supplycost = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        d_year.push(u32_at(idx, f, "D_YEAR"));
        s_nation.push(str_at(idx, f, "S_NATION"));
        c_region.push(str_at(idx, f, "C_REGION"));
        p_category.push(str_at(idx, f, "P_CATEGORY"));
        lo_revenue.push(u64_at(idx, f, "LO_REVENUE"));
        lo_supplycost.push(u64_at(idx, f, "LO_SUPPLYCOST"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: HashMap<(u32, String, String), i128> = HashMap::new();
        for i in 0..n {
            let od = lo_orderdate[i];
            if c_region[i] == "AMERICA"
                && s_nation[i] == "UNITED STATES"
                && od >= 1_997_0101
                && od <= 1_997_1231
                && p_category[i] == "MFGR#14"
            {
                let key = (d_year[i], s_nation[i].clone(), p_category[i].clone());
                let v = lo_revenue[i] as i128 - lo_supplycost[i] as i128;
                *acc.entry(key).or_insert(0) += v;
            }
        }
        std::hint::black_box(acc.len());
    });
}

fn run_q14(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut lo_discount = Vec::with_capacity(limit);
    let mut lo_quantity = Vec::with_capacity(limit);
    let mut lo_extendedprice = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        lo_discount.push(u32_at(idx, f, "LO_DISCOUNT"));
        lo_quantity.push(u32_at(idx, f, "LO_QUANTITY"));
        lo_extendedprice.push(u64_at(idx, f, "LO_EXTENDEDPRICE"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: u64 = 0;
        for i in 0..n {
            let od = lo_orderdate[i];
            let disc = lo_discount[i];
            let qty = lo_quantity[i];
            if od >= 1_994_0101 && od <= 1_994_1231 && disc >= 5 && disc <= 7 && qty < 24 {
                acc = acc.wrapping_add(lo_extendedprice[i].wrapping_mul(disc as u64));
            }
        }
        std::hint::black_box(acc);
    });
}

fn run_q15(tbl: &str, limit: usize) {
    let mut ld = TableLoader::open(tbl);
    let mut lo_orderdate = Vec::with_capacity(limit);
    let mut lo_orderpriority = Vec::with_capacity(limit);
    let mut lo_quantity = Vec::with_capacity(limit);
    ld.read_rows(limit, |idx, f| {
        lo_orderdate.push(u32_at(idx, f, "LO_ORDERDATE"));
        lo_orderpriority.push(str_at(idx, f, "LO_ORDERPRIORITY"));
        lo_quantity.push(u32_at(idx, f, "LO_QUANTITY"));
    });
    let n = lo_orderdate.len();
    time_loop(|| {
        let mut acc: HashMap<String, u64> = HashMap::new();
        for i in 0..n {
            let od = lo_orderdate[i];
            if od >= 1_998_0901 && od <= 1_998_1231 {
                let key = lo_orderpriority[i].clone();
                *acc.entry(key).or_insert(0) += lo_quantity[i] as u64;
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
    match qidx {
        1 => run_q1(tbl, limit),
        2 => run_q2(tbl, limit),
        3 => run_q3(tbl, limit),
        4 => run_q4(tbl, limit),
        5 => run_q5(tbl, limit),
        6 => run_q6(tbl, limit),
        7 => run_q7(tbl, limit),
        8 => run_q8(tbl, limit),
        9 => run_q9(tbl, limit),
        10 => run_q10(tbl, limit),
        11 => run_q11(tbl, limit),
        12 => run_q12(tbl, limit),
        13 => run_q13(tbl, limit),
        14 => run_q14(tbl, limit),
        15 => run_q15(tbl, limit),
        _ => panic!("unsupported query index {qidx}"),
    }
}
