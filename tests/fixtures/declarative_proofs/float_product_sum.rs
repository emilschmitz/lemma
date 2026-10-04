// Worked example: ungrouped SUM(a * (1 - b)) over two DOUBLE columns, exact under the f64 idealization.
// Each f64 step calls the host lemma that says the f64 result is the real result (`lemma_f64_sub_within`,
// `lemma_f64_mul_within`, `lemma_f64_add_within`); each needs the operands' `f64_within(x, cap)` facts. The
// accumulator invariant is `acc as real == sum_s(...)` exactly and a magnitude bound that grows by one product
// bound per row.
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
        assert((MAG_CAP_t_a as real) == 1024real);
        assert((MAG_CAP_t_a as real) * (2real + (MAG_CAP_t_b as real)) <= f64_safe_bound());
        assert(((t.n - t.n) as int as real) == 0real);
        assert(-1real < (acc as real));
        assert(((t.n - t.n) as int as real) * ((MAG_CAP_t_a as real) * (2real + (MAG_CAP_t_b as real))) == 0real);
        assert(f64_within(acc, ((t.n - t.n) as int as real) * ((MAG_CAP_t_a as real) * (2real + (MAG_CAP_t_b as real))) + 1real));
    }
    while i > 0
        invariant
            i <= t.n,
            t.n <= ROW_CAP_t,
            valid_cols_t(t),
            f64_literals_ok(),
            (acc as real) == sum_s(t, i as int),
            f64_within(acc, ((t.n - i) as int as real) * ((MAG_CAP_t_a as real) * (2real + (MAG_CAP_t_b as real))) + 1real),
            any <==> exists|i0: int| #![trigger row_hit(t, i0)] i as int <= i0 && row_hit(t, i0),
        decreases i,
    {
        i -= 1;
        let a = t.a[i];
        let b = t.b[i];
        proof {
            assert(t.a@.len() == t.n as int);
            assert(t.b@.len() == t.n as int);
            assert(t.a@[i as int].is_finite_spec());
            assert(t.b@[i as int].is_finite_spec());
            reveal_with_fuel(sum_s, 2);
            assert(f64_within(a, MAG_CAP_t_a as real));
            assert(f64_within(b, MAG_CAP_t_b as real));
            assert((MAG_CAP_t_a as real) == 1024real && (MAG_CAP_t_b as real) == 1024real);
            assert(f64_within(1.0f64, 2real));
            assert((2real + (MAG_CAP_t_b as real)) * (MAG_CAP_t_a as real) == 1050624real);
            bound_step((t.n - (i + 1)) as int, (MAG_CAP_t_a as real) * (2real + (MAG_CAP_t_b as real)));
            bound_below((t.n - (i + 1)) as int, (MAG_CAP_t_a as real) * (2real + (MAG_CAP_t_b as real)));
        }
        let one: f64 = 1.0;
        proof { lemma_f64_sub_within(one, b, 2real, MAG_CAP_t_b as real); }
        let om = one - b;
        proof {
        }
        proof { lemma_f64_mul_within(a, om, MAG_CAP_t_a as real, 2real + (MAG_CAP_t_b as real)); }
        let p = a * om;
        proof {
        }
        proof { lemma_f64_add_within(p, acc, (MAG_CAP_t_a as real) * (2real + (MAG_CAP_t_b as real)),
                ((t.n - (i + 1)) as int as real) * ((MAG_CAP_t_a as real) * (2real + (MAG_CAP_t_b as real))) + 1real); }
        let next = p + acc;
        proof {
        }
        acc = next;
        any = true;
        proof {
            assert(row_hit(t, i as int));
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { s: if any { Some(acc) } else { None } });
    proof {
        assert(sum_s(t, t.n as int) == 0real);
    }
    res
// AGENT_EDIT_END
