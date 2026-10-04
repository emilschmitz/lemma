    let mut c: u64 = 0;
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            valid_cols_t(t),
            f64_literals_ok(),
            c as int == count_c(t, i as int),
            c as int <= t.n as int - i as int,
        decreases i,
    {
        i -= 1;
        let v = t.v[i];
        let c_old = c;
        proof {
            assert(t.v@.len() == t.n as int);
            assert(t.v@[i as int].is_finite_spec());
            lemma_count_c_step(t, i as int);
            lemma_count_c_bound(t, i as int + 1);
        }
        let gt = v > 1.5;
        proof {
            lemma_f64_gt_real(v, 1.5f64, gt);
            assert(f64_literals_ok());
            assert((1.5f64 as real) == (3real / 2real));
            assert((1.5f64 as real) == (15real / 10real));
            assert((v as real) > (1.5f64 as real) <==> gt);
            assert(row_hit(t, i as int) <==> gt);
        }
        if gt {
            c = c + 1;
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { c });
    res
