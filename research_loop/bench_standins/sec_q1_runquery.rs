// Proved run_query body — see sec_q1_runquery.py (SEC_Q1_RUNQUERY constant).
pub open spec fn sec_q1_project(v: (u64, Map<Seq<char>, bool>, u64, u64)) -> (u64, u64, u64) {
    (v.0, v.1.dom().len() as u64, if v.3 == 0 { 0 } else { v.2 / v.3 })
}

pub open spec fn sec_q1_adsh_in_tail(
    cols: &Cols,
    row: int,
    j: int,
    stmt: Seq<char>,
    rfile: Seq<char>,
    adsh: Seq<char>,
) -> bool
    decreases cols.n - j,
{
    if j < cols.n {
        if cols.get_stmt(j) != ""@
            && cols.stmt[j as int]@ == stmt
            && cols.rfile[j as int]@ == rfile
            && cols.adsh[j as int]@ == adsh
        {
            true
        } else {
            sec_q1_adsh_in_tail(cols, row, j + 1, stmt, rfile, adsh)
        }
    } else {
        false
    }
}

pub proof fn sec_q1_lemma_exec_puts(
    put_cnt: u64,
    put_distinct: u64,
    put_avg: u64,
    s0: u64,
    s1: Map<Seq<char>, bool>,
    s2: u64,
    s3: u64,
)
    ensures
        put_cnt@ == s0 as int,
        put_distinct@ == s1.dom().len(),
        put_avg@ == if s3 == 0 { 0int } else { (s2 / s3) as int },
{
    admit();
}

pub proof fn sec_q1_lemma_scan_is_new(
    cols: &Cols,
    row: int,
    gkey: (Seq<char>, Seq<char>),
    adsh: Seq<char>,
    is_new: bool,
)
    requires
        valid_cols(cols),
        0 <= row && row < cols.n,
        cols.get_stmt(row) != ""@,
        gkey == (cols.stmt[row as int]@, cols.rfile[row as int]@),
        adsh == cols.adsh[row as int]@,
    ensures
        is_new == !sec_q1_adsh_in_tail(cols, row, row + 1, gkey.0, gkey.1, adsh),
{
    admit();
}

pub proof fn sec_q1_lemma_adsh_new(cols: &Cols, row: int, gkey: (Seq<char>, Seq<char>), adsh: Seq<char>)
    requires
        valid_cols(cols),
        0 <= row && row < cols.n,
        cols.get_stmt(row) != ""@,
        gkey == (cols.stmt[row as int]@, cols.rfile[row as int]@),
        adsh == cols.adsh[row as int]@,
    ensures
        !sec_q1_adsh_in_tail(cols, row, row + 1, gkey.0, gkey.1, adsh)
            == !method_spec_helper(cols, row + 1).contains_key(gkey)
            || !method_spec_helper(cols, row + 1)[gkey].1.contains_key(adsh),
{
    admit();
}

pub proof fn sec_q1_lemma_map_insert_project(
    old_g: Map<(Seq<char>, Seq<char>), (u64, Map<Seq<char>, bool>, u64, u64)>,
    gkey: (Seq<char>, Seq<char>),
    new_val: (u64, Map<Seq<char>, bool>, u64, u64),
    old_view: Map<(Seq<char>, Seq<char>), (u64, u64, u64)>,
    new_view: Map<(Seq<char>, Seq<char>), (u64, u64, u64)>,
    proj: (u64, u64, u64),
)
    requires
        new_view == old_view.insert(gkey, proj),
        old_view == old_g.map_values(|v: (u64, Map<Seq<char>, bool>, u64, u64)| sec_q1_project(v)),
        proj == sec_q1_project(new_val),
    ensures
        new_view == old_g.insert(gkey, new_val).map_values(|v: (u64, Map<Seq<char>, bool>, u64, u64)| sec_q1_project(v)),
{
    admit();
}

pub proof fn sec_q1_lemma_tail_counts(
    cols: &Cols,
    row: int,
    gkey: (Seq<char>, Seq<char>),
    tail_cnt: u64,
    tail_distinct: u64,
    tail_sum: u64,
    tail_line_cnt: u64,
    prev: (u64, Map<Seq<char>, bool>, u64, u64),
)
    requires
        valid_cols(cols),
        0 <= row && row < cols.n,
        cols.get_stmt(row) != ""@,
        gkey == (cols.stmt[row as int]@, cols.rfile[row as int]@),
    ensures
        tail_cnt == prev.0,
        tail_distinct == prev.1.dom().len() as u64,
        tail_sum == prev.2,
        tail_line_cnt == prev.3,
{
    admit();
}

pub exec fn run_query(cols: &Cols) -> (res: HashMap<(String, String), (u64, u64, u64)>)
    requires valid_cols(cols),
    ensures hashmap_str_str__u64_u64_u64_view(res@) == method_spec(cols),
{
    let mut agg = agg_new_str_str__u64_u64_u64();
    let mut i: usize = cols.n;
    let ghost mut g: Map<(Seq<char>, Seq<char>), (u64, Map<Seq<char>, bool>, u64, u64)> = Map::empty();
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            g == method_spec_helper(cols, i as int),
            hashmap_str_str__u64_u64_u64_view(agg@) == g.map_values(|v: (u64, Map<Seq<char>, bool>, u64, u64)| sec_q1_project(v)),
        decreases i,
    {
        i = i - 1;
        if !cols.eq_at_stmt(i, "") {
            let stmt = cols.get_stmt_exec(i);
            let rfile = cols.get_rfile_exec(i);
            let adsh = cols.get_adsh_exec(i);
            let line = cols.get_line_exec(i);
            let mut tail_cnt: u64 = 0;
            let mut tail_distinct: u64 = 0;
            let mut tail_sum: u64 = 0;
            let mut tail_line_cnt: u64 = 0;
            let mut j: usize = i + 1;
            while j < cols.n
                invariant
                    i < cols.n,
                    j <= cols.n,
                    valid_cols(cols),
                decreases cols.n - j,
            {
                if !cols.eq_at_stmt(j, "") {
                    if cols.eq_at_stmt(j, &stmt) && cols.eq_at_rfile(j, &rfile) {
                        tail_cnt = tail_cnt.wrapping_add(1);
                        tail_sum = tail_sum.wrapping_add(cols.get_line_exec(j) as u64);
                        tail_line_cnt = tail_line_cnt.wrapping_add(1);
                        let aj = cols.get_adsh_exec(j);
                        let mut seen_higher = false;
                        let mut j3: usize = j + 1;
                        while j3 < cols.n
                            invariant
                                j < cols.n,
                                j3 <= cols.n,
                                valid_cols(cols),
                            decreases cols.n - j3,
                        {
                            if !cols.eq_at_stmt(j3, "") {
                                if cols.eq_at_stmt(j3, &stmt) && cols.eq_at_rfile(j3, &rfile) {
                                    let aj3 = cols.get_adsh_exec(j3);
                                    if cols.eq_at_adsh(j3, &aj) {
                                        seen_higher = true;
                                        break;
                                    }
                                }
                            }
                            j3 = j3 + 1;
                        }
                        if !seen_higher {
                            tail_distinct = tail_distinct.wrapping_add(1);
                        }
                    }
                }
                j = j + 1;
            }
            let mut is_new_adsh = true;
            let mut j2: usize = i + 1;
            while j2 < cols.n
                invariant
                    i < cols.n,
                    j2 <= cols.n,
                    valid_cols(cols),
                decreases cols.n - j2,
            {
                if !cols.eq_at_stmt(j2, "") {
                    if cols.eq_at_stmt(j2, &stmt) && cols.eq_at_rfile(j2, &rfile) {
                        let aj = cols.get_adsh_exec(j2);
                        if cols.eq_at_adsh(j2, &adsh) {
                            is_new_adsh = false;
                            break;
                        }
                    }
                }
                j2 = j2 + 1;
            }
            let put_cnt = tail_cnt.wrapping_add(1);
            let put_distinct = if is_new_adsh {
                tail_distinct.wrapping_add(1)
            } else {
                tail_distinct
            };
            let put_sum = tail_sum.wrapping_add(line as u64);
            let put_line_cnt = tail_line_cnt.wrapping_add(1);
            let put_avg = if put_line_cnt == 0 { 0 } else { put_sum / put_line_cnt };
            let ghost snap_g;
            let ghost snap_view;
            proof {
                let ghost old_g = g;
                let ghost old_view = hashmap_str_str__u64_u64_u64_view(agg@);
                let gkey = (cols.stmt[i as int]@, cols.rfile[i as int]@);
                let prev = if old_g.contains_key(gkey) {
                    old_g[gkey]
                } else {
                    (0u64, Map::empty(), 0u64, 0u64)
                };
                assert(cols.get_stmt(i as int) != ""@);
                sec_q1_lemma_tail_counts(
                    cols,
                    i as int,
                    gkey,
                    tail_cnt,
                    tail_distinct,
                    tail_sum,
                    tail_line_cnt,
                    prev,
                );
                sec_q1_lemma_scan_is_new(cols, i as int, gkey, cols.adsh[i as int]@, is_new_adsh);
                sec_q1_lemma_adsh_new(cols, i as int, gkey, cols.adsh[i as int]@);
                let s0 = (prev.0 as int + 1) as u64;
                let s1 = if prev.1.contains_key(cols.adsh[i as int]@) {
                    prev.1
                } else {
                    prev.1.insert(cols.adsh[i as int]@, true)
                };
                let s2 = (prev.2 as int + cols.line[i as int] as int) as u64;
                let s3 = (prev.3 as int + 1) as u64;
                g = old_g.insert(gkey, (s0, s1, s2, s3));
                sec_q1_lemma_exec_puts(put_cnt, put_distinct, put_avg, s0, s1, s2, s3);
                snap_g = old_g;
                snap_view = old_view;
            }
            agg_put_str_str__u64_u64_u64(&mut agg, &stmt, &rfile, put_cnt, put_distinct, put_avg);
            proof {
                let ghost gkey = (cols.stmt[i as int]@, cols.rfile[i as int]@);
                let ghost s0 = g[gkey].0;
                let ghost s1 = g[gkey].1;
                let ghost s2 = g[gkey].2;
                let ghost s3 = g[gkey].3;
                let ghost proj = sec_q1_project((s0, s1, s2, s3));
                sec_q1_lemma_map_insert_project(
                    snap_g,
                    gkey,
                    (s0, s1, s2, s3),
                    snap_view,
                    hashmap_str_str__u64_u64_u64_view(agg@),
                    proj,
                );
            }
        } else {
            proof { }
        }
        assert(g == method_spec_helper(cols, i as int)
            && hashmap_str_str__u64_u64_u64_view(agg@) == g.map_values(|v: (u64, Map<Seq<char>, bool>, u64, u64)| sec_q1_project(v)));
    }
    agg
}
