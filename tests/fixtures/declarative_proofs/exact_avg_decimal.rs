// Worked example (lemma.toml [sql] exact_division): ungrouped AVG over a DECIMAL(10,2) column as an EXACT RATIONAL.
// The spec is `rat_is(r, avg_m_num, avg_m_den)`: the stored integer sum over (count * 100). No float anywhere: the body
// sums the stored integers in an i128, counts the rows, and returns `Rat { num: sum, den: count * 100 }` (the very pair
// of the spec, so the cross-multiplied equality is immediate). The host prints num / den as a double outside the proof.
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
            acc as int == avg_m_sum(t, i as int),
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
            reveal_with_fuel(avg_m_sum, 2);
            reveal_with_fuel(avg_m_count, 2);
            assert(row_hit(t, i as int));
        }
        acc = acc + (cell as i128);
        cnt = cnt + 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    if cnt == 0 {
        res.push(OutRow { m: None });
        proof {
            if t.n > 0 {
                lemma_avg_m_count_bound(t, 1);
            }
            assert(!(exists|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0)));
        }
    } else {
        let r = Rat { num: acc, den: (cnt as i128) * 100 };
        proof {
            assert(avg_m_den(t, 0) == (cnt as int) * 100);
            assert(avg_m_num(t, 0) == acc as int);
            assert(row_hit(t, 0)) by { assert(t.n > 0); };
        }
        res.push(OutRow { m: Some(r) });
    }
    res
// AGENT_EDIT_END
