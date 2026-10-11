// Principle 7: aggregates over a NULLABLE column skip the NULL cells (a validity vector).
//   SELECT COUNT(*) AS m, COUNT(ev_score) AS n, SUM(ev_score) AS s FROM events WHERE ev_day > 3
// * A column the catalog declares nullable is loaded as `ev_score: Vec<i64>` PLUS `ev_score__valid: Vec<bool>` (false = NULL; the cell stored under a NULL is meaningless).
//   `COUNT(*)` counts every row that passes WHERE (`row_hit`); `COUNT(ev_score)` and `SUM(ev_score)` count/add only rows that ALSO have a valid cell (`hit_n`, `hit_s`).
// * Test the validity bit BEFORE using the cell: the spec adds the cell only when `ev_score__valid@[i]` holds.
// * SUM follows SQL: over no non-NULL cells it is NULL (`None`), not 0. So track `any`, which is true exactly when some row has `hit_s`; COUNT over none is 0.
// * Three accumulators, one backward pass, each invariant is the host fold at `i`; `reveal_with_fuel(.., 2)` unrolls each by one row.
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut cm: u64 = 0;
    let mut cn: u64 = 0;
    let mut sum: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = events.n;
    while i > 0
        invariant
            i <= events.n,
            valid_cols_events(events),
            cm as int == count_m(events, i as int),
            cn as int == count_n(events, i as int),
            sum as int == sum_s(events, i as int),
            cm as int <= (events.n - i) as int,
            cn as int <= (events.n - i) as int,
            -999 * ((events.n - i) as int) <= sum as int <= 999 * ((events.n - i) as int),
            any <==> exists|i0: int| #![trigger hit_s(events, i0)] i as int <= i0 && hit_s(events, i0),
        decreases i,
    {
        i -= 1;
        let day = events.ev_day[i];
        let valid = events.ev_score__valid[i];
        let score = events.ev_score[i];
        let hit = day > 3;
        proof {
            assert(events.ev_day@.len() == events.n as int);
            assert(events.ev_score@.len() == events.n as int);
            assert(events.ev_score__valid@.len() == events.n as int);
            assert(row_hit(events, i as int) <==> hit);
            assert(hit_n(events, i as int) <==> (hit && valid));
            assert(hit_s(events, i as int) <==> (hit && valid));
            reveal_with_fuel(count_m, 2);
            reveal_with_fuel(count_n, 2);
            reveal_with_fuel(sum_s, 2);
        }
        if hit {
            cm = cm + 1;
            if valid {
                cn = cn + 1;
                sum = sum + (score as i128);
                any = true;
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { m: cm, n: cn, s: if any { Some(sum) } else { None } });
    res
// AGENT_EDIT_END
