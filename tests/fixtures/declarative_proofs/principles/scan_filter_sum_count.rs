// Principle 1: a filtered scan with COUNT and SUM over integer cells and over a DECIMAL column.
//   SELECT COUNT(*) AS n, SUM(ev_qty) AS q, SUM(ev_cost) AS c FROM events WHERE ev_qty > 2 AND ev_cost <= 50.00
// * A DECIMAL(12,2) cell is a scaled integer: `ev_cost` holds 100 * the amount, so `<= 50.00` is `<= 5000` and the SUM is read at scale 2.
// * The host spec is a suffix fold: `count_n(events, i)` / `sum_q(events, i)` fold rows i..n. Scan from the END; at each step the invariant
//   says the accumulator IS the fold at `i`, and `reveal_with_fuel(.., 2)` unrolls the fold by one row.
// * Sums go in `i128`, bounded by (rows seen) * (cell bound) in the invariant; the bounds come from `valid_cols_events`.
// * `any` records whether a row passed: SUM over no rows is NULL (`None`), COUNT over no rows is 0.
// * `&&` on bools (short-circuit), the filter computed once as `hit`; `row_hit` is the host's label for the WHERE clause.
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut cnt: u64 = 0;
    let mut sq: i128 = 0;
    let mut sc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = events.n;
    while i > 0
        invariant
            i <= events.n,
            valid_cols_events(events),
            cnt as int == count_n(events, i as int),
            sq as int == sum_q(events, i as int),
            sc as int == sum_c(events, i as int),
            cnt as int <= (events.n - i) as int,
            -999 * ((events.n - i) as int) <= sq as int <= 999 * ((events.n - i) as int),
            -999999 * ((events.n - i) as int) <= sc as int <= 999999 * ((events.n - i) as int),
            any <==> exists|i0: int| #![trigger row_hit(events, i0)] i as int <= i0 && row_hit(events, i0),
        decreases i,
    {
        i -= 1;
        let q = events.ev_qty[i];
        let c = events.ev_cost[i];
        let hit = q > 2 && c <= 5000;
        proof {
            assert(row_hit(events, i as int) <==> hit);
            reveal_with_fuel(count_n, 2);
            reveal_with_fuel(sum_q, 2);
            reveal_with_fuel(sum_c, 2);
        }
        if hit {
            cnt = cnt + 1;
            sq = sq + (q as i128);
            sc = sc + (c as i128);
            any = true;
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { n: cnt, q: if any { Some(sq) } else { None }, c: if any { Some(sc) } else { None } });
    res
// AGENT_EDIT_END
