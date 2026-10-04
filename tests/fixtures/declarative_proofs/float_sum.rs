// Worked example: ungrouped SUM(v) over a DOUBLE column. Floats are exact reals (rounding error is accepted), so
// the sum is an exact fold: the loop invariant is `acc as real == sum_s(...)` and `f64_within(acc, cnt * cap + 1)`;
// each add calls `lemma_f64_add_defined` then `lemma_f64_add_within`.
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
    let mut any: bool = false;
    let mut i: usize = t.n;
    proof {
        assert(sum_s(t, t.n as int) == 0real);
        assert(acc.is_finite_spec());
        assert((acc as real) == 0real);
        assert((MAG_CAP_t_v as real) == 1024real);
        assert(((t.n - t.n) as int as real) == 0real);
        assert(((t.n - t.n) as int as real) * (MAG_CAP_t_v as real) == 0real);
        assert(f64_within(acc, ((t.n - t.n) as int as real) * (MAG_CAP_t_v as real) + 1real));
    }
    while i > 0
        invariant
            i <= t.n,
            t.n <= ROW_CAP_t,
            valid_cols_t(t),
            f64_literals_ok(),
            (acc as real) == sum_s(t, i as int),
            f64_within(acc, ((t.n - i) as int as real) * (MAG_CAP_t_v as real) + 1real),
            any <==> exists|i0: int| #![trigger row_hit(t, i0)] i as int <= i0 && row_hit(t, i0),
        decreases i,
    {
        i -= 1;
        let v = t.v[i];
        proof {
            assert(t.v@.len() == t.n as int);
            assert(t.v@[i as int].is_finite_spec());
            assert(f64_within(v, MAG_CAP_t_v as real));
            assert((MAG_CAP_t_v as real) == 1024real);
            reveal_with_fuel(sum_s, 2);
            bound_step((t.n - (i + 1)) as int, MAG_CAP_t_v as real);
            bound_below((t.n - (i + 1)) as int, MAG_CAP_t_v as real);
        }
        proof { lemma_f64_add_within(v, acc, MAG_CAP_t_v as real, ((t.n - (i + 1)) as int as real) * (MAG_CAP_t_v as real) + 1real); }
        let next = v + acc;
        proof {
            assert(row_hit(t, i as int));
        }
        acc = next;
        any = true;
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { s: if any { Some(acc) } else { None } });
    res
// AGENT_EDIT_END
