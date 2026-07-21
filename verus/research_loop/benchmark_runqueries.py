"""Hand-written Verus/Rust RunQuery bodies for SSB benchmark fixtures."""

# Q1 — SSB Q1.1
Q1_RUNQUERY = """
    let n = cols.n;
    let mut acc: u64 = 0;
    for i in 0..n {
        let q = cols.lo_quantity[i];
        if q < 25
            && (1_993_0101 <= cols.lo_orderdate[i] && cols.lo_orderdate[i] <= 1_993_1231)
            && (1 <= cols.lo_discount[i] && cols.lo_discount[i] <= 3)
        {
            acc = add_u64(acc, mul_u64_u32(cols.lo_extendedprice[i], cols.lo_discount[i]));
        }
    }
    acc
"""

# Q2 — SSB Q1.2
Q2_RUNQUERY = """
    let n = cols.n;
    let mut acc: u64 = 0;
    for i in 0..n {
        let od = cols.lo_orderdate[i];
        let disc = cols.lo_discount[i];
        let qty = cols.lo_quantity[i];
        if od >= 1_994_0101 && od <= 1_994_0131 && disc >= 4 && disc <= 6 && qty >= 26 && qty <= 35
        {
            acc = add_u64(acc, mul_u64_u32(cols.lo_extendedprice[i], disc));
        }
    }
    acc
"""

# Q3 — SSB Q1.3
Q3_RUNQUERY = """
    let n = cols.n;
    let mut acc: u64 = 0;
    for i in 0..n {
        if cols.d_weeknuminyear[i] == 6
            && cols.d_year[i] == 1994
            && cols.lo_discount[i] >= 5
            && cols.lo_discount[i] <= 7
            && cols.lo_quantity[i] >= 26
            && cols.lo_quantity[i] <= 35
        {
            acc = add_u64(acc, mul_u64_u32(cols.lo_extendedprice[i], cols.lo_discount[i]));
        }
    }
    acc
"""

# Q4 — SSB Q2.1 (2-key group-by u64)
Q4_RUNQUERY = """
    let n = cols.n;
    let mut acc: HashMap<(u32, String), u64> = HashMap::new();
    for i in 0..n {
        if cols.p_category[i] == "MFGR#12" && cols.s_region[i] == "AMERICA" {
            let key = (cols.d_year[i], cols.p_brand[i].clone());
            *acc.entry(key).or_insert(0) += cols.lo_revenue[i];
        }
    }
    acc
"""

# Q5 — SSB Q2.2
Q5_RUNQUERY = """
    let n = cols.n;
    let mut acc: HashMap<(u32, String), u64> = HashMap::new();
    for i in 0..n {
        if cols.p_brand[i] == "MFGR#2221" && cols.p_size[i] >= 10 && cols.s_region[i] == "ASIA" {
            let key = (cols.d_year[i], cols.p_brand[i].clone());
            *acc.entry(key).or_insert(0) += cols.lo_revenue[i];
        }
    }
    acc
"""

# Q6 — SSB Q2.3
Q6_RUNQUERY = """
    let n = cols.n;
    let mut acc: HashMap<(u32, String), u64> = HashMap::new();
    for i in 0..n {
        if cols.p_brand[i] == "MFGR#2221" && cols.s_region[i] == "EUROPE" {
            let key = (cols.d_year[i], cols.p_brand[i].clone());
            *acc.entry(key).or_insert(0) += cols.lo_revenue[i];
        }
    }
    acc
"""

# Q10 — SSB Q3.4 (3-key group-by)
Q10_RUNQUERY = """
    let n = cols.n;
    let mut acc: HashMap<(String, String, u32), u64> = HashMap::new();
    for i in 0..n {
        let od = cols.lo_orderdate[i];
        if cols.c_city[i] == "UNITED KI1"
            && cols.s_city[i] == "UNITED KI5"
            && od >= 1_997_1201
            && od <= 1_997_1231
        {
            let key = (cols.c_city[i].clone(), cols.s_city[i].clone(), cols.d_year[i]);
            *acc.entry(key).or_insert(0) += cols.lo_revenue[i];
        }
    }
    acc
"""

# Q11 — SSB Q4.1 (2-key group-by i64 profit)
Q11_RUNQUERY = """
    let n = cols.n;
    let mut acc: HashMap<(u32, String), i64> = HashMap::new();
    for i in 0..n {
        if cols.c_region[i] == "AMERICA"
            && cols.s_region[i] == "AMERICA"
            && cols.p_mfgr[i] == "MFGR#1"
        {
            let term = sub_u64_to_i64(cols.lo_revenue[i], cols.lo_supplycost[i]);
            let key = (cols.d_year[i], cols.c_nation[i].clone());
            *acc.entry(key).or_insert(0) += term;
        }
    }
    acc
"""

# Q13 — SSB Q4.3 (3-key group-by i64)
Q13_RUNQUERY = """
    let n = cols.n;
    let mut acc: HashMap<(u32, String, String), i64> = HashMap::new();
    for i in 0..n {
        let od = cols.lo_orderdate[i];
        if cols.c_region[i] == "AMERICA"
            && cols.s_nation[i] == "UNITED STATES"
            && od >= 1_997_0101
            && od <= 1_997_1231
            && cols.p_category[i] == "MFGR#14"
        {
            let term = sub_u64_to_i64(cols.lo_revenue[i], cols.lo_supplycost[i]);
            let key = (
                cols.d_year[i],
                cols.s_nation[i].clone(),
                cols.p_category[i].clone(),
            );
            *acc.entry(key).or_insert(0) += term;
        }
    }
    acc
"""

RUNQUERIES: dict[int, str] = {
    1: Q1_RUNQUERY,
    2: Q2_RUNQUERY,
    3: Q3_RUNQUERY,
    4: Q4_RUNQUERY,
    5: Q5_RUNQUERY,
    6: Q6_RUNQUERY,
    10: Q10_RUNQUERY,
    11: Q11_RUNQUERY,
    13: Q13_RUNQUERY,
}

# Return-type tags consumed by assemble_runquery.py
RETURN_TYPES: dict[int, str] = {
    1: "u64",
    2: "u64",
    3: "u64",
    4: "map_u32_str_u64",
    5: "map_u32_str_u64",
    6: "map_u32_str_u64",
    10: "map_str_str_u32_u64",
    11: "map_u32_str_i64",
    13: "map_u32_str_str_i64",
}
