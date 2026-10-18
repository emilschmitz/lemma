    // Query template ([sql] templates): both DATE bounds are run_query arguments (i32 day numbers since 1970-01-01).
    //   -- params: d0 DATE, d1 DATE
    //   SELECT COUNT(*) AS c FROM t WHERE d >= $d0 AND d < $d1
    let mut c: u64 = 0;
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            valid_cols_t(t),
            c as int == count_c(t, i as int, param_d0, param_d1),
            c as int <= t.n as int - i as int,
        decreases i,
    {
        i -= 1;
        proof {
            assert(t.d@.len() == t.n as int);
        }
        let v = t.d[i];
        proof {
            assert(row_hit(t, i as int, param_d0, param_d1) <==> ((v as int) >= (param_d0 as int) && (v as int) < (param_d1 as int)));
        }
        if v >= param_d0 && v < param_d1 {
            c = c + 1;
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { c });
    res
