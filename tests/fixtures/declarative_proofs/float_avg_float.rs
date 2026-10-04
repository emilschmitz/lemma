// Worked example: ungrouped AVG over a DOUBLE column. Exact f64 sum (idealization), a u64 count cast with
// `host_u64_to_f64`, one division (`lemma_f64_div_defined`, `lemma_f64_div_real`). The sum's magnitude bound
// is tracked against the count (`cnt * cap + 1`) so the quotient bound `cap + 1` follows.
// AGENT_HELPERS_START
proof fn bound_step(m: int, p: real)
    ensures ((m + 1) as real) * p == (m as real) * p + p,
{
    assert(((m + 1) as real) == (m as real) + 1real);
    assert(((m as real) + 1real) * p == (m as real) * p + p) by (nonlinear_arith);
}

proof fn bound_below(m: int, p: real)
    requires 0 <= m <= 100, 0real <= p, p <= 0x10000000000000000000000int as real,
    ensures (m as real) * p + 1real + p <= 0x1000000000000000000000000000000000000000000000000000int as real,
{
    assert((m as real) <= 100real);
    assert((m as real) * p <= 100real * p) by (nonlinear_arith)
        requires (m as real) <= 100real, 0real <= p;
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut acc: f64 = 0.0;
    let mut cnt: u64 = 0;
    let mut i: usize = t.n;
    proof {
        assert(avg_m_sum(t, t.n as int) == 0real);
        assert(avg_m_count(t, t.n as int) == 0);
        assert((MAG_CAP_t_v as real) == 1024real);
        assert((cnt as int as real) == 0real);
        assert((cnt as int as real) * (MAG_CAP_t_v as real) == 0real);
    }
    while i > 0
        invariant
            i <= t.n,
            t.n <= ROW_CAP_t,
            valid_cols_t(t),
            f64_literals_ok(),
            (acc as real) == avg_m_sum(t, i as int),
            cnt as int == avg_m_count(t, i as int),
            cnt as int <= (t.n - i) as int,
            f64_within(acc, (cnt as int as real) * (MAG_CAP_t_v as real) + 1real),
        decreases i,
    {
        i -= 1;
        let v = t.v[i];
        proof {
            assert(t.v@.len() == t.n as int);
            assert(t.v@[i as int].is_finite_spec());
            assert(f64_within(v, MAG_CAP_t_v as real));
            assert((MAG_CAP_t_v as real) == 1024real);
            lemma_avg_m_count_step(t, i as int);
            lemma_avg_m_count_bound(t, i as int + 1);
            reveal_with_fuel(avg_m_sum, 2);
            assert(row_hit(t, i as int));
            bound_step(cnt as int, MAG_CAP_t_v as real);
            bound_below(cnt as int, MAG_CAP_t_v as real);
            lemma_f64_add_defined(v, acc);
            lemma_count_step_fits_u64(cnt, 100);
        }
        let next = v + acc;
        proof {
            lemma_f64_add_within(v, acc, next, MAG_CAP_t_v as real, (cnt as int as real) * (MAG_CAP_t_v as real) + 1real);
        }
        acc = next;
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
            assert((cnt as int as real) <= 100real);
        }
        let fc = host_u64_to_f64(cnt);
        proof {
            assert(cnt as int >= 1);
            assert(abs_real(fc as real) == (cnt as int as real));
            let cap = MAG_CAP_t_v as real;
            let cq = cap + 1real;
            let c = cnt as int as real;
            assert(-cq * c < (acc as real) && (acc as real) < cq * c) by (nonlinear_arith)
                requires -(c * cap + 1real) < (acc as real), (acc as real) < c * cap + 1real, c >= 1real, cq == cap + 1real;
            lemma_f64_div_defined(acc, fc, c * cap + 1real, cq);
        }
        let avg = acc / fc;
        proof {
            let cap = MAG_CAP_t_v as real;
            let c = cnt as int as real;
            lemma_f64_div_real(acc, fc, avg, c * cap + 1real, cap + 1real);
            assert(row_hit(t, 0)) by { assert(t.n > 0); };
        }
        res.push(OutRow { m: Some(avg) });
    }
    res
// AGENT_EDIT_END
