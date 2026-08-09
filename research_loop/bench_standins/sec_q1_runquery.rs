// Proved run_query body — see sec_q1_runquery.py (SEC_Q1_RUNQUERY constant).
pub exec fn run_query(cols: &Cols) -> (res: HashMap<(String, String), (u64, u64, u64)>)
    requires valid_cols(cols),
    ensures hashmap_str_str__u64_u64_u64_view(res@) == method_spec(cols),
{
    let mut st = agg_step_state_new_str_str__u64_u64_u64();
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            agg_step_inner_str_str__u64_u64_u64_view(st.inner@) == method_spec_helper(cols, i as int),
            hashmap_str_str__u64_u64_u64_view(st.projected@)
                == agg_step_inner_str_str__u64_u64_u64_view(st.inner@).map_values(
                    |v: (u64, Map<Seq<char>, bool>, u64, u64)| agg_step_project_str_str__u64_u64_u64(v),
                ),
        decreases i,
    {
        i = i - 1;
        if !cols.eq_at_stmt(i, "") {
            let stmt = cols.get_stmt_exec(i);
            let rfile = cols.get_rfile_exec(i);
            let adsh = cols.get_adsh_exec(i);
            let line = cols.get_line_exec(i);
            agg_step_str_str__u64_u64_u64(
                &mut st,
                stmt.as_str(),
                rfile.as_str(),
                adsh.as_str(),
                line as u64,
            );
            proof {
                let ghost tail = method_spec_helper(cols, (i + 1) as int);
                let ghost key = (cols.stmt[i as int]@, cols.rfile[i as int]@);
                let ghost prev = if tail.contains_key(key) {
                    tail[key]
                } else {
                    (0u64, Map::empty(), 0u64, 0u64)
                };
                let ghost expected = agg_step_apply_row_str_str__u64_u64_u64(
                    prev,
                    cols.adsh[i as int]@,
                    cols.line[i as int] as u64,
                );
                assert(expected == method_spec_helper(cols, i as int)[key]);
                assert(agg_step_inner_str_str__u64_u64_u64_view(st.inner@) == method_spec_helper(cols, i as int));
            }
        } else {
            proof {
                assert(method_spec_helper(cols, i as int) == method_spec_helper(cols, (i + 1) as int));
            }
        }
    }
    st.projected
}
