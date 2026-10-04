// Worked example: ungrouped AVG over an integer column (DuckDB returns DOUBLE). Exact integer sum and count, then
// one f64 division under the f64 idealization: cast the i128 sum and the u64 count to f64
// (`host_i128_to_f64`, `host_u64_to_f64`), then `lemma_f64_div_defined` and `lemma_f64_div_real`.
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut acc: i128 = 0;
    let mut cnt: u64 = 0;
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            t.n <= ROW_CAP_t,
            valid_cols_t(t),
            f64_literals_ok(),
            (acc as int as real) == avg_m_sum(t, i as int),
            cnt as int == avg_m_count(t, i as int),
            -(cnt as int) * 0x8000_0000_0000_0000int <= acc as int,
            acc as int <= (cnt as int) * 0x8000_0000_0000_0000int,
            cnt as int <= (t.n - i) as int,
        decreases i,
    {
        i -= 1;
        let cell = t.i[i];
        proof {
            assert(t.i@.len() == t.n as int);
            lemma_avg_m_count_step(t, i as int);
            lemma_avg_m_count_bound(t, i as int + 1);
            reveal_with_fuel(avg_m_sum, 2);
            assert(row_hit(t, i as int));
            assert(avg_m_val(t, i as int) == ((cell as int) as real));
            lemma_sum_step_fits_i128(acc, cell as i128, 100 * 0x8000_0000_0000_0000int);
            lemma_count_step_fits_u64(cnt, 100);
        }
        acc = acc + (cell as i128);
        cnt = cnt + 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    if cnt == 0 {
        res.push(OutRow { m: None });
        proof {
            if t.n > 0 {
                lemma_avg_m_count_step(t, 0);
                lemma_avg_m_count_bound(t, 1);
            }
            assert(!(exists|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0)));
        }
    } else {
        proof {
            assert((acc as int as real) <= 100real * (0x8000_0000_0000_0000int as real));
            assert(-(100real * (0x8000_0000_0000_0000int as real)) <= (acc as int as real));
            assert((cnt as int as real) <= 100real);
        }
        let fs = host_i128_to_f64(acc);
        let fc = host_u64_to_f64(cnt);
        proof {
            assert(cnt as int >= 1);
            assert(abs_real(fc as real) == (cnt as int as real));
            assert((fs as real) == (acc as int as real));
            assert((cnt as int as real) * (0x8000_0000_0000_0000int as real) == (cnt as int as real) * 9223372036854775808real);
            assert(-(0x10000000000000000int as real) * (cnt as int as real) < (acc as int as real)) by (nonlinear_arith)
                requires (acc as int as real) >= -((cnt as int as real) * (0x8000_0000_0000_0000int as real)), (cnt as int as real) >= 1real;
            assert((acc as int as real) < (0x10000000000000000int as real) * (cnt as int as real)) by (nonlinear_arith)
                requires (acc as int as real) <= ((cnt as int as real) * (0x8000_0000_0000_0000int as real)), (cnt as int as real) >= 1real;
            assert(f64_within(fs, (100real + 0real) * 0x8000_0000_0000_0000int as real + 1real)) by {
                assert((acc as int as real) <= 100real * (0x8000_0000_0000_0000int as real));
                assert(-(100real * (0x8000_0000_0000_0000int as real)) <= (acc as int as real));
            };
            let q = 0x10000000000000000int as real;
            lemma_f64_div_defined(fs, fc, (100real + 0real) * 0x8000_0000_0000_0000int as real + 1real, q);
        }
        let avg = fs / fc;
        proof {
            lemma_f64_div_real(fs, fc, avg, (100real + 0real) * 0x8000_0000_0000_0000int as real + 1real, 0x10000000000000000int as real);
            assert(row_hit(t, 0)) by { assert(t.n > 0); };
        }
        res.push(OutRow { m: Some(avg) });
    }
    res
// AGENT_EDIT_END
