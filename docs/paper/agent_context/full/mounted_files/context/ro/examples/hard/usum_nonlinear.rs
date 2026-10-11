    // The per-row bound is a ghost variable, not a literal, so `(n - i) * m` is a product of two
    // unknowns. Z3 needs `by (nonlinear_arith)` (or the vstd mul lemmas) to step it.
    let ghost m: int = 0x8000_0000_0000_0000int;
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = pre.n;
    while i > 0
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            m == 0x8000_0000_0000_0000int,
            acc as int == sum_total(pre, i as int),
            -((pre.n - i) as int) * m <= acc as int,
            acc as int <= ((pre.n - i) as int) * m,
            any <==> exists|i0: int| #![trigger row_hit(pre, i0)] i as int <= i0 && row_hit(pre, i0),
        decreases i,
    {
        i -= 1;
        let line = pre.line[i];
        proof {
            assert(pre.line@.len() == pre.n as int);
            assert(row_hit(pre, i as int) <==> ((line as int) > 5));
            assert(sum_total_val(pre, i as int) == line as int);
            reveal_with_fuel(sum_total, 2);
            let k = (pre.n - i) as int;
            assert((k) * m == (k - 1) * m + m) by (nonlinear_arith)
                requires k >= 1;
            assert(0 <= (k - 1) * m) by (nonlinear_arith)
                requires k >= 1, m > 0;
            assert(-(k * m) == -((k - 1) * m) - m) by (nonlinear_arith)
                requires k >= 1;
            // the i128 add cannot overflow: |acc| <= 64 * 2^63 and |line| <= 2^63
            assert(k <= 64);
            assert(k * m <= 64 * 0x8000_0000_0000_0000int) by (nonlinear_arith)
                requires 1 <= k <= 64, m == 0x8000_0000_0000_0000int;
        }
        if line > 5 {
            acc = acc + (line as i128);
            any = true;
            proof {
                assert(row_hit(pre, i as int));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].total is Some <==> any);
    }
    res
