    // Query template ([sql] templates): the filter constant is the run_query argument `param_lo`.
    //   -- params: lo BIGINT
    //   SELECT SUM(x) AS s FROM t WHERE x > $lo
    let mut acc: i128 = 0;
    let mut any = false;
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            valid_cols_t(t),
            acc as int == sum_s(t, i as int, param_lo),
            -((t.n as int - i as int) * 999999) <= acc as int <= (t.n as int - i as int) * 999999,
            any <==> exists|i0: int| #![trigger row_hit(t, i0, param_lo)] i as int <= i0 < t.n as int && row_hit(t, i0, param_lo),
        decreases i,
    {
        i -= 1;
        proof {
            assert(t.x@.len() == t.n as int);
        }
        let v = t.x[i];
        proof {
            assert(row_hit(t, i as int, param_lo) <==> (v as int) > (param_lo as int));
            assert(sum_s(t, i as int, param_lo) == (if row_hit(t, i as int, param_lo) { sum_s_val(t, i as int) } else { 0int }) + sum_s(t, i as int + 1, param_lo));
        }
        if v > param_lo {
            acc = acc + (v as i128);
            any = true;
        }
        proof {
            if !row_hit(t, i as int, param_lo) {
                assert((exists|i0: int| #![trigger row_hit(t, i0, param_lo)] i as int <= i0 < t.n as int && row_hit(t, i0, param_lo))
                    ==> (exists|i0: int| #![trigger row_hit(t, i0, param_lo)] i as int + 1 <= i0 < t.n as int && row_hit(t, i0, param_lo)));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { s: if any { Some(acc) } else { None } });
    res
