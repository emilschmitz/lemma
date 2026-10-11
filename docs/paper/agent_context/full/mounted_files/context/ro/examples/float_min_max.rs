    let mut hi: f64 = 0.0;
    let mut lo: f64 = 0.0;
    let ghost mut wh: int = 0;
    let ghost mut wl: int = 0;
    let mut i: usize = 0;
    while i < t.n
        invariant
            i <= t.n,
            valid_cols_t(t),
            f64_literals_ok(),
            0 < i ==> 0 <= wh < i as int && 0 <= wl < i as int,
            0 < i ==> hi.is_finite_spec() && lo.is_finite_spec(),
            0 < i ==> (hi as real) == max_mx_val(t, wh) && (lo as real) == min_mn_val(t, wl),
            forall|j: int| 0 <= j < i as int ==> max_mx_val(t, j) <= (hi as real) && min_mn_val(t, j) >= (lo as real),
        decreases t.n - i,
    {
        let v = t.v[i];
        proof {
            assert(t.v@.len() == t.n as int);
            assert(t.v@[i as int].is_finite_spec());
            assert(max_mx_val(t, i as int) == (v as real));
            assert(min_mn_val(t, i as int) == (v as real));
        }
        if i == 0 {
            hi = v;
            lo = v;
            proof {
                wh = 0;
                wl = 0;
            }
        } else {
            let bigger = v > hi;
            let smaller = v < lo;
            proof {
                lemma_f64_gt_real(v, hi, bigger);
                lemma_f64_lt_real(v, lo, smaller);
            }
            if bigger {
                hi = v;
                proof { wh = i as int; }
            }
            if smaller {
                lo = v;
                proof { wl = i as int; }
            }
        }
        i += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    if t.n == 0 {
        res.push(OutRow { mx: None, mn: None });
        proof {
            assert(!(exists|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0)));
        }
    } else {
        res.push(OutRow { mx: Some(hi), mn: Some(lo) });
        proof {
            assert(row_hit(t, 0));
            assert(max_mx(t, hi as real)) by {
                assert(max_mx_val(t, wh) == (hi as real) && row_hit(t, wh));
            };
            assert(min_mn(t, lo as real)) by {
                assert(min_mn_val(t, wl) == (lo as real) && row_hit(t, wl));
            };
        }
    }
    res
