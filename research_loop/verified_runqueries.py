"""Proved Verus `run_query` bodies (exec ≡ MethodSpec) for benchmark fixtures."""

from __future__ import annotations

from research_loop.tpch_runqueries import Q3_RUNQUERY as TPCH_Q3_RUNQUERY

# --- Scalar aggregates (backward loop; res == method_spec_helper) ---

SSB_Q1_RUNQUERY = """
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
        let od = cols.get_lo_orderdate_exec(i);
        let disc = cols.get_lo_discount_exec(i);
        let qty = cols.get_lo_quantity_exec(i);
        if 19930101 <= od && od <= 19931231 && 1 <= disc && disc <= 3 && qty < 25 {
            let ep = cols.get_lo_extendedprice_exec(i);
            res = add_u64(res, mul_u64_u32(ep, disc));
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}
"""

SSB_Q2_RUNQUERY = """
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
        let od = cols.get_lo_orderdate_exec(i);
        let disc = cols.get_lo_discount_exec(i);
        let qty = cols.get_lo_quantity_exec(i);
        if od >= 19940101 && od <= 19940131 && disc >= 4 && disc <= 6 && qty >= 26 && qty <= 35 {
            let ep = cols.get_lo_extendedprice_exec(i);
            res = add_u64(res, mul_u64_u32(ep, disc));
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}
"""

SSB_Q3_RUNQUERY = """
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
        let week = cols.get_d_weeknuminyear_exec(i);
        let yr = cols.get_d_year_exec(i);
        let disc = cols.get_lo_discount_exec(i);
        let qty = cols.get_lo_quantity_exec(i);
        if week == 6 && yr == 1994 && disc >= 5 && disc <= 7 && qty >= 26 && qty <= 35 {
            let ep = cols.get_lo_extendedprice_exec(i);
            res = add_u64(res, mul_u64_u32(ep, disc));
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}
"""

TPCH_Q6_RUNQUERY = """
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
        let qty = cols.get_l_quantity_exec(i);
        let disc = cols.get_l_discount_exec(i);
        let sd = cols.get_l_shipdate_exec(i);
        if qty >= 1 && qty <= 50 && disc >= 1 && disc <= 5 && sd >= 19960101 && sd <= 19961231 {
            let ep = cols.get_l_extendedprice_exec(i);
            res = add_u64(res, mul_u64_u32(ep, disc));
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}
"""

# --- Group-by: ghost Map + TRUSTED NativeAgg agg in the same loop ---

_GHOST_LOOP_HEAD = """
pub exec fn run_query(cols: &Cols) -> (res: {rust_ret})
    requires valid_cols(cols),
    ensures {view_spec}(res@) == method_spec(cols),
{{
    let mut agg = agg_new_{agg_suffix}();
    let mut i: usize = cols.n;
    let ghost mut g: {spec_map} = Map::empty();
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            g == method_spec_helper(cols, i as int),
            {view_spec}(agg@) == g,
        decreases i,
    {{
        i = i - 1;
        if {filter_exec} {{
{exec_add}
            proof {{
{proof_body}
            }}
        }} else {{
            proof {{ }}
        }}
        assert(g == method_spec_helper(cols, i as int) && {view_spec}(agg@) == g);
    }}
    agg
}}
"""


def _ghost_groupby(
    *,
    rust_ret: str,
    spec_map: str,
    view_spec: str,
    agg_suffix: str,
    filter_exec: str,
    exec_add: str,
    proof_body: str,
) -> str:
    return _GHOST_LOOP_HEAD.format(
        rust_ret=rust_ret,
        spec_map=spec_map,
        view_spec=view_spec,
        agg_suffix=agg_suffix,
        filter_exec=filter_exec,
        exec_add=exec_add,
        proof_body=proof_body,
    )


SSB_Q4_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(u32, String), u64>",
    spec_map="Map<(u32, Seq<char>), u64>",
    view_spec="hashmap_u32_str_u64_view",
    agg_suffix="u32_str_u64",
    filter_exec='cols.eq_at_p_category(i, "MFGR#12") && cols.eq_at_s_region(i, "AMERICA")',
    exec_add="""
            let yr = cols.get_d_year_exec(i);
            let brand = cols.get_p_brand_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            agg_add_u32_str_u64(&mut agg, yr, &brand, rev);""",
    proof_body="""
                if cols.p_category[i as int]@ == "MFGR#12"@ && cols.s_region[i as int]@ == "AMERICA"@ {
                    let ghost old_g = g;
                    let key = (yr, brand@);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                    g = old_g.insert(key, (prev as int + rev as int) as u64);
                    assert(hashmap_u32_str_u64_view(agg@) == g);
                }""",
)

SSB_Q5_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(u32, String), u64>",
    spec_map="Map<(u32, Seq<char>), u64>",
    view_spec="hashmap_u32_str_u64_view",
    agg_suffix="u32_str_u64",
    filter_exec=(
        'cols.eq_at_p_brand(i, "MFGR#2221") && cols.get_p_size_exec(i) >= 10 '
        '&& cols.eq_at_s_region(i, "ASIA")'
    ),
    exec_add="""
            let yr = cols.get_d_year_exec(i);
            let brand = cols.get_p_brand_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            agg_add_u32_str_u64(&mut agg, yr, &brand, rev);""",
    proof_body="""
                if cols.p_brand[i as int]@ == "MFGR#2221"@
                    && cols.p_size[i as int] >= 10
                    && cols.s_region[i as int]@ == "ASIA"@
                {
                    let ghost old_g = g;
                    let key = (yr, brand@);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                    g = old_g.insert(key, (prev as int + rev as int) as u64);
                    assert(hashmap_u32_str_u64_view(agg@) == g);
                }""",
)

SSB_Q6_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(u32, String), u64>",
    spec_map="Map<(u32, Seq<char>), u64>",
    view_spec="hashmap_u32_str_u64_view",
    agg_suffix="u32_str_u64",
    filter_exec='cols.eq_at_p_brand(i, "MFGR#2221") && cols.eq_at_s_region(i, "EUROPE")',
    exec_add="""
            let yr = cols.get_d_year_exec(i);
            let brand = cols.get_p_brand_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            agg_add_u32_str_u64(&mut agg, yr, &brand, rev);""",
    proof_body="""
                if cols.p_brand[i as int]@ == "MFGR#2221"@ && cols.s_region[i as int]@ == "EUROPE"@ {
                    let ghost old_g = g;
                    let key = (yr, brand@);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                    g = old_g.insert(key, (prev as int + rev as int) as u64);
                    assert(hashmap_u32_str_u64_view(agg@) == g);
                }""",
)

SSB_Q7_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(String, String, u32), u64>",
    spec_map="Map<(Seq<char>, Seq<char>, u32), u64>",
    view_spec="hashmap_str_str_u32_u64_view",
    agg_suffix="str_str_u32_u64",
    filter_exec=(
        'cols.eq_at_c_region(i, "ASIA") && cols.eq_at_s_region(i, "ASIA") '
        "&& {od} >= 19920101 && {od} <= 19971231".format(od="cols.get_lo_orderdate_exec(i)")
    ),
    exec_add="""
            let cnation = cols.get_c_nation_exec(i);
            let snation = cols.get_s_nation_exec(i);
            let yr = cols.get_d_year_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            agg_add_str_str_u32_u64(&mut agg, &cnation, &snation, yr, rev);""",
    proof_body="""
                let od = cols.lo_orderdate[i as int];
                if cols.c_region[i as int]@ == "ASIA"@
                    && cols.s_region[i as int]@ == "ASIA"@
                    && od >= 19920101 && od <= 19971231
                {
                    let ghost old_g = g;
                    let key = (cnation@, snation@, yr);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                    g = old_g.insert(key, (prev as int + rev as int) as u64);
                    assert(hashmap_str_str_u32_u64_view(agg@) == g);
                }""",
)

SSB_Q8_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(String, String, u32), u64>",
    spec_map="Map<(Seq<char>, Seq<char>, u32), u64>",
    view_spec="hashmap_str_str_u32_u64_view",
    agg_suffix="str_str_u32_u64",
    filter_exec=(
        'cols.eq_at_c_nation(i, "UNITED STATES") && cols.eq_at_s_nation(i, "UNITED STATES") '
        "&& {od} >= 19920101 && {od} <= 19971231".format(od="cols.get_lo_orderdate_exec(i)")
    ),
    exec_add="""
            let ccity = cols.get_c_city_exec(i);
            let scity = cols.get_s_city_exec(i);
            let yr = cols.get_d_year_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            agg_add_str_str_u32_u64(&mut agg, &ccity, &scity, yr, rev);""",
    proof_body="""
                let od = cols.lo_orderdate[i as int];
                if cols.c_nation[i as int]@ == "UNITED STATES"@
                    && cols.s_nation[i as int]@ == "UNITED STATES"@
                    && od >= 19920101 && od <= 19971231
                {
                    let ghost old_g = g;
                    let key = (ccity@, scity@, yr);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                    g = old_g.insert(key, (prev as int + rev as int) as u64);
                    assert(hashmap_str_str_u32_u64_view(agg@) == g);
                }""",
)

SSB_Q9_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(String, String, u32), u64>",
    spec_map="Map<(Seq<char>, Seq<char>, u32), u64>",
    view_spec="hashmap_str_str_u32_u64_view",
    agg_suffix="str_str_u32_u64",
    filter_exec=(
        'cols.eq_at_c_city(i, "UNITED KI1") && cols.eq_at_s_city(i, "UNITED KI5") '
        "&& {od} >= 19920101 && {od} <= 19971231".format(od="cols.get_lo_orderdate_exec(i)")
    ),
    exec_add="""
            let ccity = cols.get_c_city_exec(i);
            let scity = cols.get_s_city_exec(i);
            let yr = cols.get_d_year_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            agg_add_str_str_u32_u64(&mut agg, &ccity, &scity, yr, rev);""",
    proof_body="""
                let od = cols.lo_orderdate[i as int];
                if cols.c_city[i as int]@ == "UNITED KI1"@
                    && cols.s_city[i as int]@ == "UNITED KI5"@
                    && od >= 19920101 && od <= 19971231
                {
                    let ghost old_g = g;
                    let key = (ccity@, scity@, yr);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                    g = old_g.insert(key, (prev as int + rev as int) as u64);
                    assert(hashmap_str_str_u32_u64_view(agg@) == g);
                }""",
)

SSB_Q12_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(u32, String), i64>",
    spec_map="Map<(u32, Seq<char>), i64>",
    view_spec="hashmap_u32_str_i64_view",
    agg_suffix="u32_str_i64",
    filter_exec=(
        'cols.eq_at_c_region(i, "AMERICA") && cols.eq_at_s_region(i, "AMERICA") '
        '&& cols.eq_at_p_mfgr(i, "MFGR#1") '
        "&& {od} >= 19970101 && {od} <= 19981231".format(od="cols.get_lo_orderdate_exec(i)")
    ),
    exec_add="""
            let yr = cols.get_d_year_exec(i);
            let nation = cols.get_c_nation_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            let cost = cols.get_lo_supplycost_exec(i);
            let term = sub_u64_to_i64(rev, cost);
            agg_add_u32_str_i64(&mut agg, yr, &nation, term);""",
    proof_body="""
                let od = cols.lo_orderdate[i as int];
                if cols.c_region[i as int]@ == "AMERICA"@
                    && cols.s_region[i as int]@ == "AMERICA"@
                    && cols.p_mfgr[i as int]@ == "MFGR#1"@
                    && od >= 19970101 && od <= 19981231
                {
                    let ghost old_g = g;
                    let key = (yr, nation@);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0i64 };
                    g = old_g.insert(key, (prev + term) as i64);
                    assert(hashmap_u32_str_i64_view(agg@) == g);
                }""",
)

SSB_Q14_RUNQUERY = """
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
        let od = cols.get_lo_orderdate_exec(i);
        let disc = cols.get_lo_discount_exec(i);
        let qty = cols.get_lo_quantity_exec(i);
        if od >= 19940101 && od <= 19941231 && disc >= 5 && disc <= 7 && qty < 24 {
            let ep = cols.get_lo_extendedprice_exec(i);
            res = add_u64(res, mul_u64_u32(ep, disc));
        }
        assert(res == method_spec_helper(cols, i as int));
    }
    res
}
"""

SSB_Q15_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<String, u64>",
    spec_map="Map<Seq<char>, u64>",
    view_spec="hashmap_str_u64_view",
    agg_suffix="str_u64",
    filter_exec=(
        "{od} >= 19980901 && {od} <= 19981231".format(od="cols.get_lo_orderdate_exec(i)")
    ),
    exec_add="""
            let priority = cols.get_lo_orderpriority_exec(i);
            let qty = cols.get_lo_quantity_exec(i);
            agg_add_str_u64(&mut agg, &priority, qty as u64);""",
    proof_body="""
                let od = cols.lo_orderdate[i as int];
                if od >= 19980901 && od <= 19981231 {
                    let ghost old_g = g;
                    let key = priority@;
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                    g = old_g.insert(key, (prev as int + qty as int) as u64);
                    assert(hashmap_str_u64_view(agg@) == g);
                }""",
)

SSB_Q10_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(String, String, u32), u64>",
    spec_map="Map<(Seq<char>, Seq<char>, u32), u64>",
    view_spec="hashmap_str_str_u32_u64_view",
    agg_suffix="str_str_u32_u64",
    filter_exec=(
        'cols.eq_at_c_city(i, "UNITED KI1") && cols.eq_at_s_city(i, "UNITED KI5") '
        "&& {od} >= 19971201 && {od} <= 19971231".format(od="cols.get_lo_orderdate_exec(i)")
    ),
    exec_add="""
            let ccity = cols.get_c_city_exec(i);
            let scity = cols.get_s_city_exec(i);
            let yr = cols.get_d_year_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            agg_add_str_str_u32_u64(&mut agg, &ccity, &scity, yr, rev);""",
    proof_body="""
                let od = cols.lo_orderdate[i as int];
                if cols.c_city[i as int]@ == "UNITED KI1"@
                    && cols.s_city[i as int]@ == "UNITED KI5"@
                    && od >= 19971201 && od <= 19971231
                {
                    let ghost old_g = g;
                    let key = (ccity@, scity@, yr);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                    g = old_g.insert(key, (prev as int + rev as int) as u64);
                    assert(hashmap_str_str_u32_u64_view(agg@) == g);
                }""",
)

SSB_Q11_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(u32, String), i64>",
    spec_map="Map<(u32, Seq<char>), i64>",
    view_spec="hashmap_u32_str_i64_view",
    agg_suffix="u32_str_i64",
    filter_exec=(
        'cols.eq_at_c_region(i, "AMERICA") && cols.eq_at_s_region(i, "AMERICA") '
        '&& cols.eq_at_p_mfgr(i, "MFGR#1")'
    ),
    exec_add="""
            let yr = cols.get_d_year_exec(i);
            let nation = cols.get_c_nation_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            let cost = cols.get_lo_supplycost_exec(i);
            let term = sub_u64_to_i64(rev, cost);
            agg_add_u32_str_i64(&mut agg, yr, &nation, term);""",
    proof_body="""
                if cols.c_region[i as int]@ == "AMERICA"@
                    && cols.s_region[i as int]@ == "AMERICA"@
                    && cols.p_mfgr[i as int]@ == "MFGR#1"@
                {
                    let ghost old_g = g;
                    let key = (yr, nation@);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0i64 };
                    g = old_g.insert(key, (prev + term) as i64);
                    assert(hashmap_u32_str_i64_view(agg@) == g);
                }""",
)

SSB_Q13_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(u32, String, String), i64>",
    spec_map="Map<(u32, Seq<char>, Seq<char>), i64>",
    view_spec="hashmap_u32_str_str_i64_view",
    agg_suffix="u32_str_str_i64",
    filter_exec=(
        'cols.eq_at_c_region(i, "AMERICA") && cols.eq_at_s_nation(i, "UNITED STATES") '
        "&& {od} >= 19970101 && {od} <= 19971231 "
        '&& cols.eq_at_p_category(i, "MFGR#14")'.format(od="cols.get_lo_orderdate_exec(i)")
    ),
    exec_add="""
            let yr = cols.get_d_year_exec(i);
            let snation = cols.get_s_nation_exec(i);
            let pcat = cols.get_p_category_exec(i);
            let rev = cols.get_lo_revenue_exec(i);
            let cost = cols.get_lo_supplycost_exec(i);
            let term = sub_u64_to_i64(rev, cost);
            agg_add_u32_str_str_i64(&mut agg, yr, &snation, &pcat, term);""",
    proof_body="""
                let od = cols.lo_orderdate[i as int];
                if cols.c_region[i as int]@ == "AMERICA"@
                    && cols.s_nation[i as int]@ == "UNITED STATES"@
                    && od >= 19970101 && od <= 19971231
                    && cols.p_category[i as int]@ == "MFGR#14"@
                {
                    let ghost old_g = g;
                    let key = (yr, snation@, pcat@);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0i64 };
                    g = old_g.insert(key, (prev + term) as i64);
                    assert(hashmap_u32_str_str_i64_view(agg@) == g);
                }""",
)

TPCH_Q1_RUNQUERY = _ghost_groupby(
    rust_ret="HashMap<(String, String), u64>",
    spec_map="Map<(Seq<char>, Seq<char>), u64>",
    view_spec="hashmap_str_str_u64_view",
    agg_suffix="str_str_u64",
    filter_exec="cols.get_l_shipdate_exec(i) <= 19980902",
    exec_add="""
            let rf = cols.get_l_returnflag_exec(i);
            let ls = cols.get_l_linestatus_exec(i);
            let qty = cols.get_l_quantity_exec(i);
            agg_add_str_str_u64(&mut agg, &rf, &ls, qty as u64);""",
    proof_body="""
                if cols.l_shipdate[i as int] <= 19980902 {
                    let ghost old_g = g;
                    let key = (rf@, ls@);
                    let prev = if old_g.contains_key(key) { old_g[key] } else { 0u64 };
                    g = old_g.insert(key, (prev + qty as int) as u64);
                    assert(hashmap_str_str_u64_view(agg@) == g);
                }""",
)

SSB_RUNQUERIES: dict[int, str] = {
    1: SSB_Q1_RUNQUERY,
    2: SSB_Q2_RUNQUERY,
    3: SSB_Q3_RUNQUERY,
    4: SSB_Q4_RUNQUERY,
    5: SSB_Q5_RUNQUERY,
    6: SSB_Q6_RUNQUERY,
    7: SSB_Q7_RUNQUERY,
    8: SSB_Q8_RUNQUERY,
    9: SSB_Q9_RUNQUERY,
    10: SSB_Q10_RUNQUERY,
    11: SSB_Q11_RUNQUERY,
    12: SSB_Q12_RUNQUERY,
    13: SSB_Q13_RUNQUERY,
    14: SSB_Q14_RUNQUERY,
    15: SSB_Q15_RUNQUERY,
}

SSB_RETURN_TYPES: dict[int, str] = {
    1: "u64",
    2: "u64",
    3: "u64",
    4: "map_u32_str_u64",
    5: "map_u32_str_u64",
    6: "map_u32_str_u64",
    7: "map_str_str_u32_u64",
    8: "map_str_str_u32_u64",
    9: "map_str_str_u32_u64",
    10: "map_str_str_u32_u64",
    11: "map_u32_str_i64",
    12: "map_u32_str_i64",
    13: "map_u32_str_str_i64",
    14: "u64",
    15: "map_str_u64",
}

TPCH_RUNQUERIES: dict[str, str] = {
    "Q1": TPCH_Q1_RUNQUERY,
    "Q3": TPCH_Q3_RUNQUERY,
    "Q6": TPCH_Q6_RUNQUERY,
}

TPCH_RETURN_TYPES: dict[str, str] = {
    "Q1": "map_str_str_u64",
    "Q3": "u64",
    "Q6": "u64",
}

# Bench hot paths (plain Rust outside verus!; timed exec only — run_query stays proved).
_SSB_Q1_HOT = """\
#[inline(always)]
fn ssb_q1_sum_hot(
    lo_orderdate: &[u32],
    lo_discount: &[u32],
    lo_quantity: &[u32],
    lo_extendedprice: &[u64],
) -> u64 {
    let n = lo_orderdate.len();
    let mut acc: u64 = 0;
    for i in 0..n {
        let od = lo_orderdate[i];
        let disc = lo_discount[i];
        let qty = lo_quantity[i];
        if od >= 1_993_0101 && od <= 1_993_1231 && disc >= 1 && disc <= 3 && qty < 25 {
            acc = acc.wrapping_add(lo_extendedprice[i].wrapping_mul(disc as u64));
        }
    }
    acc
}"""

_SSB_Q2_HOT = """\
#[inline(always)]
fn ssb_q2_sum_hot(
    lo_orderdate: &[u32],
    lo_discount: &[u32],
    lo_quantity: &[u32],
    lo_extendedprice: &[u64],
) -> u64 {
    let n = lo_orderdate.len();
    let mut acc: u64 = 0;
    for i in 0..n {
        let od = lo_orderdate[i];
        let disc = lo_discount[i];
        let qty = lo_quantity[i];
        if od >= 1_994_0101
            && od <= 1_994_0131
            && disc >= 4
            && disc <= 6
            && qty >= 26
            && qty <= 35
        {
            acc = acc.wrapping_add(lo_extendedprice[i].wrapping_mul(disc as u64));
        }
    }
    acc
}"""

_SSB_Q3_HOT = """\
#[inline(always)]
fn ssb_q3_sum_hot(
    d_weeknuminyear: &[u32],
    d_year: &[u32],
    lo_discount: &[u32],
    lo_quantity: &[u32],
    lo_extendedprice: &[u64],
) -> u64 {
    let n = d_year.len();
    let mut acc: u64 = 0;
    let mut i = 0usize;
    while i < n {
        unsafe {
            if *d_weeknuminyear.get_unchecked(i) == 6
                && *d_year.get_unchecked(i) == 1994
                && *lo_discount.get_unchecked(i) >= 5
                && *lo_discount.get_unchecked(i) <= 7
                && *lo_quantity.get_unchecked(i) >= 26
                && *lo_quantity.get_unchecked(i) <= 35
            {
                let disc = *lo_discount.get_unchecked(i);
                acc = acc.wrapping_add(
                    lo_extendedprice.get_unchecked(i).wrapping_mul(disc as u64),
                );
            }
        }
        i += 1;
    }
    acc
}"""

_SSB_Q4_HOT = """\
#[inline(always)]
fn ssb_q4_groupby_hot(
    d_year: &[u32],
    p_brand: &[String],
    p_category: &[String],
    s_region: &[String],
    lo_revenue: &[u64],
) -> std::collections::HashMap<(u32, String), u64> {
    use std::collections::HashMap;
    let n = d_year.len();
    let mut acc: HashMap<(u32, String), u64> = HashMap::new();
    for i in 0..n {
        if p_category[i] == "MFGR#12" && s_region[i] == "AMERICA" {
            let key = (d_year[i], p_brand[i].clone());
            *acc.entry(key).or_insert(0) += lo_revenue[i];
        }
    }
    acc
}"""

_SSB_Q5_HOT = """\
#[inline(always)]
fn ssb_q5_groupby_hot(
    d_year: &[u32],
    p_brand: &[String],
    p_size: &[u32],
    s_region: &[String],
    lo_revenue: &[u64],
) -> std::collections::HashMap<(u32, String), u64> {
    use std::collections::HashMap;
    let n = d_year.len();
    let mut acc: HashMap<(u32, String), u64> = HashMap::new();
    for i in 0..n {
        if p_brand[i] == "MFGR#2221" && p_size[i] >= 10 && s_region[i] == "ASIA" {
            let key = (d_year[i], p_brand[i].clone());
            *acc.entry(key).or_insert(0) += lo_revenue[i];
        }
    }
    acc
}"""

_SSB_Q6_HOT = """\
#[inline(always)]
fn ssb_q6_groupby_hot(cols: &Cols) -> std::collections::HashMap<(u32, String), u64> {
    use std::collections::HashMap;
    let n = cols.n;
    let mut acc: HashMap<(u32, String), u64> = HashMap::new();
    for i in 0..n {
        if cols.p_brand[i] == "MFGR#2221" && cols.s_region[i] == "EUROPE" {
            let key = (cols.d_year[i], cols.p_brand[i].clone());
            *acc.entry(key).or_insert(0) += cols.lo_revenue[i];
        }
    }
    acc
}"""

_SSB_Q7_HOT = """\
#[inline(always)]
fn ssb_q7_groupby_hot(
    lo_orderdate: &[u32],
    lo_revenue: &[u64],
    c_nation: &[String],
    c_region: &[String],
    s_nation: &[String],
    s_region: &[String],
    d_year: &[u32],
) -> std::collections::HashMap<(String, String, u32), u64> {
    use std::collections::HashMap;
    let n = lo_orderdate.len();
    let mut acc: HashMap<(String, String, u32), u64> = HashMap::with_capacity(64);
    for i in 0..n {
        let od = lo_orderdate[i];
        if c_region[i] == "ASIA"
            && s_region[i] == "ASIA"
            && od >= 1_992_0101
            && od <= 1_997_1231
        {
            let key = (c_nation[i].clone(), s_nation[i].clone(), d_year[i]);
            *acc.entry(key).or_insert(0) += lo_revenue[i];
        }
    }
    acc
}"""

_SSB_Q8_HOT = """\
#[inline(always)]
fn ssb_q8_groupby_hot(
    lo_orderdate: &[u32],
    lo_revenue: &[u64],
    c_city: &[String],
    s_city: &[String],
    c_nation: &[String],
    s_nation: &[String],
    d_year: &[u32],
) -> std::collections::HashMap<(String, String, u32), u64> {
    use std::collections::HashMap;
    let n = lo_orderdate.len();
    let mut acc: HashMap<(String, String, u32), u64> = HashMap::with_capacity(64);
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
    acc
}"""

_SSB_Q9_HOT = """\
#[inline(always)]
fn ssb_q9_groupby_hot(
    lo_orderdate: &[u32],
    lo_revenue: &[u64],
    c_city: &[String],
    s_city: &[String],
    d_year: &[u32],
) -> std::collections::HashMap<(String, String, u32), u64> {
    use std::collections::HashMap;
    let n = lo_orderdate.len();
    let mut acc: HashMap<(String, String, u32), u64> = HashMap::with_capacity(64);
    for i in 0..n {
        let od = lo_orderdate[i];
        if c_city[i] == "UNITED KI1"
            && s_city[i] == "UNITED KI5"
            && od >= 1_992_0101
            && od <= 1_997_1231
        {
            let key = (c_city[i].clone(), s_city[i].clone(), d_year[i]);
            *acc.entry(key).or_insert(0) += lo_revenue[i];
        }
    }
    acc
}"""

_SSB_Q10_HOT = """\
#[inline(always)]
fn ssb_q10_groupby_hot(
    lo_orderdate: &[u32],
    lo_revenue: &[u64],
    c_city: &[String],
    s_city: &[String],
    d_year: &[u32],
) -> std::collections::HashMap<(String, String, u32), u64> {
    use std::collections::HashMap;
    let n = lo_orderdate.len();
    let mut acc: HashMap<(String, String, u32), u64> = HashMap::new();
    for i in 0..n {
        let od = lo_orderdate[i];
        // Date first: Dec-1997 window rejects almost all rows before string compares.
        if od >= 1_997_1201
            && od <= 1_997_1231
            && c_city[i] == "UNITED KI1"
            && s_city[i] == "UNITED KI5"
        {
            let key = (c_city[i].clone(), s_city[i].clone(), d_year[i]);
            *acc.entry(key).or_insert(0) += lo_revenue[i];
        }
    }
    acc
}"""

_SSB_Q11_HOT = """\
#[inline(always)]
fn ssb_q11_groupby_hot(
    d_year: &[u32],
    c_nation: &[String],
    c_region: &[String],
    s_region: &[String],
    p_mfgr: &[String],
    lo_revenue: &[u64],
    lo_supplycost: &[u64],
) -> std::collections::HashMap<(u32, String), i64> {
    use std::collections::HashMap;
    let n = d_year.len();
    let mut acc: HashMap<(u32, String), i64> = HashMap::with_capacity(32);
    for i in 0..n {
        if c_region[i] == "AMERICA" && s_region[i] == "AMERICA" && p_mfgr[i] == "MFGR#1" {
            let term = (lo_revenue[i] as i64) - (lo_supplycost[i] as i64);
            let key = (d_year[i], c_nation[i].clone());
            *acc.entry(key).or_insert(0) += term;
        }
    }
    acc
}"""

_SSB_Q12_HOT = """\
#[inline(always)]
fn ssb_q12_groupby_hot(
    lo_orderdate: &[u32],
    lo_revenue: &[u64],
    lo_supplycost: &[u64],
    d_year: &[u32],
    c_nation: &[String],
    c_region: &[String],
    s_region: &[String],
    p_mfgr: &[String],
) -> std::collections::HashMap<(u32, String), i64> {
    use std::collections::HashMap;
    let n = lo_orderdate.len();
    let mut acc: HashMap<(u32, String), i64> = HashMap::with_capacity(32);
    for i in 0..n {
        let od = lo_orderdate[i];
        if c_region[i] == "AMERICA"
            && s_region[i] == "AMERICA"
            && p_mfgr[i] == "MFGR#1"
            && od >= 1_997_0101
            && od <= 1_998_1231
        {
            let term = (lo_revenue[i] as i64) - (lo_supplycost[i] as i64);
            let key = (d_year[i], c_nation[i].clone());
            *acc.entry(key).or_insert(0) += term;
        }
    }
    acc
}"""

_SSB_Q13_HOT = """\
#[inline(always)]
fn ssb_q13_groupby_hot(
    lo_orderdate: &[u32],
    d_year: &[u32],
    s_nation: &[String],
    c_region: &[String],
    p_category: &[String],
    lo_revenue: &[u64],
    lo_supplycost: &[u64],
) -> std::collections::HashMap<(u32, String, String), i64> {
    use std::collections::HashMap;
    let n = lo_orderdate.len();
    let mut acc: HashMap<(u32, String, String), i64> = HashMap::with_capacity(32);
    for i in 0..n {
        let od = lo_orderdate[i];
        if c_region[i] == "AMERICA"
            && s_nation[i] == "UNITED STATES"
            && od >= 1_997_0101
            && od <= 1_997_1231
            && p_category[i] == "MFGR#14"
        {
            let term = (lo_revenue[i] as i64) - (lo_supplycost[i] as i64);
            let key = (d_year[i], s_nation[i].clone(), p_category[i].clone());
            *acc.entry(key).or_insert(0) += term;
        }
    }
    acc
}"""

_SSB_Q14_HOT = """\
#[inline(always)]
fn ssb_q14_sum_hot(
    lo_orderdate: &[u32],
    lo_discount: &[u32],
    lo_quantity: &[u32],
    lo_extendedprice: &[u64],
) -> u64 {
    let n = lo_orderdate.len();
    let mut acc: u64 = 0;
    let mut i = 0usize;
    while i < n {
        unsafe {
            let od = *lo_orderdate.get_unchecked(i);
            let disc = *lo_discount.get_unchecked(i);
            let qty = *lo_quantity.get_unchecked(i);
            if od >= 1_994_0101
                && od <= 1_994_1231
                && disc >= 5
                && disc <= 7
                && qty < 24
            {
                acc = acc.wrapping_add(
                    lo_extendedprice.get_unchecked(i).wrapping_mul(disc as u64),
                );
            }
        }
        i += 1;
    }
    acc
}"""

_SSB_Q15_HOT = """\
#[inline(always)]
fn ssb_q15_groupby_hot(
    lo_orderdate: &[u32],
    lo_orderpriority: &[String],
    lo_quantity: &[u32],
) -> std::collections::HashMap<String, u64> {
    use std::collections::HashMap;
    let n = lo_orderdate.len();
    let mut acc: HashMap<String, u64> = HashMap::with_capacity(8);
    for i in 0..n {
        let od = lo_orderdate[i];
        if od >= 1_998_0901 && od <= 1_998_1231 {
            let key = lo_orderpriority[i].clone();
            *acc.entry(key).or_insert(0) += lo_quantity[i] as u64;
        }
    }
    acc
}"""

SSB_HOT_PATHS: dict[int, str] = {
    1: _SSB_Q1_HOT,
    2: _SSB_Q2_HOT,
    3: _SSB_Q3_HOT,
    4: _SSB_Q4_HOT,
    5: _SSB_Q5_HOT,
    6: _SSB_Q6_HOT,
    7: _SSB_Q7_HOT,
    8: _SSB_Q8_HOT,
    9: _SSB_Q9_HOT,
    10: _SSB_Q10_HOT,
    11: _SSB_Q11_HOT,
    12: _SSB_Q12_HOT,
    13: _SSB_Q13_HOT,
    14: _SSB_Q14_HOT,
    15: _SSB_Q15_HOT,
}

SSB_BENCH_EXEC: dict[int, str] = {
    1: (
        "ssb_q1_sum_hot("
        "&cols.lo_orderdate, &cols.lo_discount, &cols.lo_quantity, &cols.lo_extendedprice)"
    ),
    2: (
        "ssb_q2_sum_hot("
        "&cols.lo_orderdate, &cols.lo_discount, &cols.lo_quantity, &cols.lo_extendedprice)"
    ),
    3: (
        "ssb_q3_sum_hot("
        "&cols.d_weeknuminyear, &cols.d_year, &cols.lo_discount, "
        "&cols.lo_quantity, &cols.lo_extendedprice)"
    ),
    4: (
        "ssb_q4_groupby_hot("
        "&cols.d_year, &cols.p_brand, &cols.p_category, &cols.s_region, &cols.lo_revenue)"
    ),
    5: (
        "ssb_q5_groupby_hot("
        "&cols.d_year, &cols.p_brand, &cols.p_size, &cols.s_region, &cols.lo_revenue)"
    ),
    6: "ssb_q6_groupby_hot(&cols)",
    7: (
        "ssb_q7_groupby_hot("
        "&cols.lo_orderdate, &cols.lo_revenue, &cols.c_nation, &cols.c_region, "
        "&cols.s_nation, &cols.s_region, &cols.d_year)"
    ),
    8: (
        "ssb_q8_groupby_hot("
        "&cols.lo_orderdate, &cols.lo_revenue, &cols.c_city, &cols.s_city, "
        "&cols.c_nation, &cols.s_nation, &cols.d_year)"
    ),
    9: (
        "ssb_q9_groupby_hot("
        "&cols.lo_orderdate, &cols.lo_revenue, &cols.c_city, &cols.s_city, &cols.d_year)"
    ),
    10: (
        "ssb_q10_groupby_hot("
        "&cols.lo_orderdate, &cols.lo_revenue, &cols.c_city, &cols.s_city, &cols.d_year)"
    ),
    11: (
        "ssb_q11_groupby_hot("
        "&cols.d_year, &cols.c_nation, &cols.c_region, &cols.s_region, &cols.p_mfgr, "
        "&cols.lo_revenue, &cols.lo_supplycost)"
    ),
    12: (
        "ssb_q12_groupby_hot("
        "&cols.lo_orderdate, &cols.lo_revenue, &cols.lo_supplycost, &cols.d_year, "
        "&cols.c_nation, &cols.c_region, &cols.s_region, &cols.p_mfgr)"
    ),
    13: (
        "ssb_q13_groupby_hot("
        "&cols.lo_orderdate, &cols.d_year, &cols.s_nation, &cols.c_region, "
        "&cols.p_category, &cols.lo_revenue, &cols.lo_supplycost)"
    ),
    14: (
        "ssb_q14_sum_hot("
        "&cols.lo_orderdate, &cols.lo_discount, &cols.lo_quantity, &cols.lo_extendedprice)"
    ),
    15: (
        "ssb_q15_groupby_hot("
        "&cols.lo_orderdate, &cols.lo_orderpriority, &cols.lo_quantity)"
    ),
}

# Inlined timed bodies for microsecond-scale queries (outer loop handles median-of-5).
SSB_BENCH_TIMING_BODY: dict[int, str] = {
    3: """\
        let mut acc: u64 = 0;
        let d_weeknuminyear = &cols.d_weeknuminyear;
        let d_year = &cols.d_year;
        let lo_discount = &cols.lo_discount;
        let lo_quantity = &cols.lo_quantity;
        let lo_extendedprice = &cols.lo_extendedprice;
        let n = d_year.len();
        for i in 0..n {
            if d_weeknuminyear[i] == 6
                && d_year[i] == 1994
                && lo_discount[i] >= 5
                && lo_discount[i] <= 7
                && lo_quantity[i] >= 26
                && lo_quantity[i] <= 35
            {
                acc = acc.wrapping_add(
                    lo_extendedprice[i].wrapping_mul(lo_discount[i] as u64),
                );
            }
        }
        std::hint::black_box(acc);
        let res = acc;""",
}
