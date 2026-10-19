// Worked example (lemma.toml [sql] exact_division): `SELECT SUM(a) / SUM(b) AS r FROM t` over two DECIMAL(10,2) columns as an EXACT
// RATIONAL, including a zero denominator. The spec is `rat_is(r, 1 * N * 100, D * 100)` for the exact sums N and D. The body returns
// the same fraction N / D with a positive denominator (both signs flipped when D < 0) and, when D == 0, `Rat { num: N, den: 0 }`:
// the host prints that as +inf, -inf or NaN by the sign of N, which is DuckDB's DOUBLE division by zero. No float in the proof.
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut n_acc: i128 = 0;
    let mut d_acc: i128 = 0;
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            t.n <= ROW_CAP_t,
            valid_cols_t(t),
            n_acc as int == sum_r__num(t, i as int),
            d_acc as int == sum_r__den(t, i as int),
            -((t.n - i) as int) * 10000000000int <= n_acc as int <= ((t.n - i) as int) * 10000000000int,
            -((t.n - i) as int) * 10000000000int <= d_acc as int <= ((t.n - i) as int) * 10000000000int,
        decreases i,
    {
        i -= 1;
        proof {
            assert(t.a@.len() == t.n as int);
            assert(t.b@.len() == t.n as int);
            reveal_with_fuel(sum_r__num, 2);
            reveal_with_fuel(sum_r__den, 2);
            assert(row_hit(t, i as int));
        }
        n_acc = n_acc + (t.a[i] as i128);
        d_acc = d_acc + (t.b[i] as i128);
    }
    let mut res: Vec<OutRow> = Vec::new();
    if t.n == 0 {
        res.push(OutRow { r: None });
        proof {
            assert(!(exists|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0)));
        }
    } else {
        let ghost nn = n_acc as int;
        let ghost dd = d_acc as int;
        let r: Rat;
        if d_acc > 0 {
            r = Rat { num: n_acc, den: d_acc };
            proof {
                assert(nn * (dd * 100) == (1 * nn * 100) * dd) by (nonlinear_arith);
            }
        } else if d_acc < 0 {
            r = Rat { num: -n_acc, den: -d_acc };
            proof {
                assert((-nn) * (dd * 100) == (1 * nn * 100) * (-dd)) by (nonlinear_arith);
            }
        } else {
            r = Rat { num: n_acc, den: 0 };
        }
        proof {
            assert(rat_is(r, 1 * sum_r__num(t, 0) * 100, sum_r__den(t, 0) * 100));
            assert(row_hit(t, 0));
        }
        res.push(OutRow { r: Some(r) });
    }
    res
// AGENT_EDIT_END
