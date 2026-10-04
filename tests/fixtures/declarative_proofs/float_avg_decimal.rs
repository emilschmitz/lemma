// Worked example: ungrouped AVG over a DECIMAL(10,2) column (DuckDB returns DOUBLE). The spec states the real
// value of each cell (`stored / 100`). The body sums the stored integers exactly in an i128, then, under the f64
// idealization, casts sum / scale / count with `host_i128_to_f64` / `host_u64_to_f64` and divides twice
// (`lemma_f64_div_defined` and `lemma_f64_div_real` each time): (sum / 100) / count.
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
            avg_m_sum(t, i as int) == (acc as int as real) / 100real,
            cnt as int == avg_m_count(t, i as int),
            -(cnt as int) * 10000000000int <= acc as int,
            acc as int <= (cnt as int) * 10000000000int,
            cnt as int <= (t.n - i) as int,
        decreases i,
    {
        i -= 1;
        let cell = t.d[i];
        proof {
            assert(t.d@.len() == t.n as int);
            lemma_avg_m_count_step(t, i as int);
            lemma_avg_m_count_bound(t, i as int + 1);
            reveal_with_fuel(avg_m_sum, 2);
            assert(row_hit(t, i as int));
            assert(avg_m_val(t, i as int) == ((cell as int) as real) / 100real);
            lemma_sum_step_fits_i128(acc, cell as i128, 100 * 10000000000int);
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
            assert((acc as int as real) <= 100real * 10000000000real);
            assert(-(100real * 10000000000real) <= (acc as int as real));
            assert((cnt as int as real) <= 100real);
        }
        let fs = host_i128_to_f64(acc);
        let fscale = host_u64_to_f64(100);
        let fc = host_u64_to_f64(cnt);
        proof {
            assert(cnt as int >= 1);
            assert((fscale as real) == 100real);
            assert(abs_real(fscale as real) == 100real);
            assert((fs as real) == (acc as int as real));
            assert(f64_within(fs, 2000000000000real));
            lemma_f64_div_defined(fs, fscale, 2000000000000real, 100000000000real);
        }
        let mean_scaled = fs / fscale;
        proof {
            lemma_f64_div_real(fs, fscale, mean_scaled, 2000000000000real, 100000000000real);
            let c = cnt as int as real;
            assert(abs_real(fc as real) == c);
            let m = (mean_scaled as real);
            assert(m == (acc as int as real) / 100real);
            assert(-(1000000000real) * c < m && m < 1000000000real * c) by (nonlinear_arith)
                requires m == (acc as int as real) / 100real, -c * 10000000000real <= (acc as int as real), (acc as int as real) <= c * 10000000000real, c >= 1real;
            assert(f64_within(mean_scaled, 20000000000real)) by {
                assert(mean_scaled.is_finite_spec());
            };
            lemma_f64_div_defined(mean_scaled, fc, 20000000000real, 1000000000real);
        }
        let avg = mean_scaled / fc;
        proof {
            lemma_f64_div_real(mean_scaled, fc, avg, 20000000000real, 1000000000real);
            assert(row_hit(t, 0)) by { assert(t.n > 0); };
        }
        res.push(OutRow { m: Some(avg) });
    }
    res
// AGENT_EDIT_END
