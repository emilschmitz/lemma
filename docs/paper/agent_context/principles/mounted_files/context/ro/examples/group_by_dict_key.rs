// Principle 2: GROUP BY a dictionary-coded string key into dense arrays (LEMMA_STRING_ENCODING=dict).
//   SELECT ev_kind, COUNT(*) AS n, SUM(ev_qty) AS q FROM events WHERE ev_day >= 30 GROUP BY ev_kind
// * A string column is `ev_kind: Vec<u8>` of CODES plus `ev_kind__dict: Vec<String>`; the spec reads a cell as `ev_kind__dict@[code]@` and
//   `valid_cols_events` says the entries are pairwise distinct. So "same group" is "same code": one array slot per code, no hashing.
// * Phase 1 builds `counts` and `sums` (one slot per dictionary entry, zeros). Phase 2 scans from the END and bumps the slot of the row's code only
//   when the filter holds. The invariant says EVERY slot equals the host fold for its key, `count_n(events, i, dict[c]@)`; one row of
//   unfolding (`reveal_with_fuel(.., 2)`) changes only the slot of `code`, because a different code is a different (distinct) dictionary entry.
// * Phase 3 walks the codes in order and emits an `OutRow` for every slot with a nonzero count. A ghost `idx` records which code each result
//   row came from; it gives the three postconditions: each row is a real group (`out_row_ok`, with `lemma_count_pos` finding a witness row),
//   keys are pairwise distinct (`idx` is strictly increasing and entries are distinct), every passing row's group has a row.
// * Bounds: `|sums[c]| <= (rows seen) * 999` is the cell cap of `ev_qty` in `valid_cols_events`; redo it for YOUR spec's cap.
// AGENT_HELPERS_START
proof fn lemma_count_pos(events: &Cols_events, i: int, k: Seq<char>)
    requires
        0 <= i,
    ensures
        count_n(events, i, k) > 0 <==> exists|j: int| #![trigger row_hit(events, j)] i <= j < events.n as int && row_hit(events, j) && key_at(events, j) == k,
    decreases events.n as int - i,
{
    if i < events.n as int {
        lemma_count_pos(events, i + 1, k);
        lemma_count_n_bound(events, i + 1, k);
        if row_hit(events, i) && key_at(events, i) == k {
            assert(i <= i && i < events.n as int && row_hit(events, i) && key_at(events, i) == k);
        } else if exists|j: int| #![trigger row_hit(events, j)] i <= j < events.n as int && row_hit(events, j) && key_at(events, j) == k {
            let j = choose|j: int| #![trigger row_hit(events, j)] i <= j < events.n as int && row_hit(events, j) && key_at(events, j) == k;
            assert(j != i);
            assert(i + 1 <= j < events.n as int && row_hit(events, j) && key_at(events, j) == k);
        }
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let m: usize = events.ev_kind__dict.len();
    let mut counts: Vec<u64> = Vec::new();
    let mut sums: Vec<i128> = Vec::new();
    let mut z: usize = 0;
    while z < m
        invariant
            z <= m,
            m == events.ev_kind__dict@.len(),
            counts@.len() == z as int,
            sums@.len() == z as int,
            forall|c: int| 0 <= c < z as int ==> counts@[c] == 0 && sums@[c] == 0,
        decreases m - z,
    {
        counts.push(0);
        sums.push(0);
        z += 1;
    }
    let mut i: usize = events.n;
    while i > 0
        invariant
            i <= events.n,
            valid_cols_events(events),
            m == events.ev_kind__dict@.len(),
            counts@.len() == m as int,
            sums@.len() == m as int,
            forall|c: int| #![trigger counts@[c]] 0 <= c < m as int ==> counts@[c] as int == count_n(events, i as int, events.ev_kind__dict@[c]@),
            forall|c: int| #![trigger sums@[c]] 0 <= c < m as int ==> sums@[c] as int == sum_q(events, i as int, events.ev_kind__dict@[c]@)
                && -((events.n - i) as int) * 999int <= sums@[c] as int
                && sums@[c] as int <= ((events.n - i) as int) * 999int,
        decreases i,
    {
        i -= 1;
        let v = events.ev_qty[i];
        let code = events.ev_kind[i] as usize;
        let hit = events.ev_day[i] >= 30;
        proof {
            assert(events.ev_qty@.len() == events.n as int);
            assert(events.ev_kind@.len() == events.n as int);
            assert(events.ev_day@.len() == events.n as int);
            assert(code < m);
            assert(row_hit(events, i as int) <==> hit);
            lemma_count_n_bound(events, (i + 1) as int, events.ev_kind__dict@[code as int]@);
            // one row of unfolding, for every key at once
            assert forall|kk: Seq<char>| #[trigger] count_n(events, i as int, kk) == (if row_hit(events, i as int) && key_at(events, i as int) == kk { 1int } else { 0int }) + count_n(events, i as int + 1, kk) by {
                reveal_with_fuel(count_n, 2);
            };
            assert forall|kk: Seq<char>| #[trigger] sum_q(events, i as int, kk) == (if row_hit(events, i as int) && key_at(events, i as int) == kk { sum_q_val(events, i as int) } else { 0int }) + sum_q(events, i as int + 1, kk) by {
                reveal_with_fuel(sum_q, 2);
            };
            assert(sum_q_val(events, i as int) == v as int);
        }
        if hit {
            let before = counts[code];
            counts.set(code, before + 1);
            let sb = sums[code];
            sums.set(code, sb + (v as i128));
        }
        proof {
            assert forall|c: int| #![trigger counts@[c]] 0 <= c < m as int implies
                counts@[c] as int == count_n(events, i as int, events.ev_kind__dict@[c]@)
                && sums@[c] as int == sum_q(events, i as int, events.ev_kind__dict@[c]@)
                && -((events.n - i) as int) * 999int <= sums@[c] as int
                && sums@[c] as int <= ((events.n - i) as int) * 999int by {
                assert(key_at(events, i as int) == events.ev_kind__dict@[code as int]@);
                if hit && c != code as int {
                    // two different codes are two different dictionary entries (they are pairwise distinct)
                    if c < code as int {
                        assert(events.ev_kind__dict@[c]@ != events.ev_kind__dict@[code as int]@);
                    } else {
                        assert(events.ev_kind__dict@[code as int]@ != events.ev_kind__dict@[c]@);
                    }
                }
            };
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut idx: Seq<int> = Seq::empty();
    let mut c: usize = 0;
    while c < m
        invariant
            c <= m,
            valid_cols_events(events),
            m == events.ev_kind__dict@.len(),
            counts@.len() == m as int,
            sums@.len() == m as int,
            forall|q: int| #![trigger counts@[q]] 0 <= q < m as int ==> counts@[q] as int == count_n(events, 0, events.ev_kind__dict@[q]@),
            forall|q: int| #![trigger sums@[q]] 0 <= q < m as int ==> sums@[q] as int == sum_q(events, 0, events.ev_kind__dict@[q]@),
            idx.len() == res@.len(),
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> 0 <= idx[r] < c as int,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> counts@[idx[r]] > 0,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].ev_kind@ == events.ev_kind__dict@[idx[r]]@,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].n == counts@[idx[r]] && res@[r].q == sums@[idx[r]],
            forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() ==> idx[r] < idx[r2],
            forall|q: int| #![trigger counts@[q]] 0 <= q < c as int && counts@[q] > 0 ==> exists|r: int| 0 <= r < idx.len() && idx[r] == q,
        decreases m - c,
    {
        let cnt = counts[c];
        if cnt > 0 {
            let ghost old = res@;
            let ghost old_idx = idx;
            let sv = sums[c];
            res.push(OutRow { ev_kind: events.ev_kind__dict[c].clone(), n: cnt, q: sv });
            proof {
                let x = res@[old.len() as int];
                assert(res@ == old.push(x));
                assert(x.ev_kind@ == events.ev_kind__dict@[c as int]@ && x.n == cnt && counts@[c as int] == cnt && x.q == sv);
                idx = old_idx.push(c as int);
                assert(idx.len() == res@.len());
                assert forall|r: int| 0 <= r < idx.len() implies idx[r] == (if r < old.len() as int { old_idx[r] } else { c as int }) by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies 0 <= idx[r] < (c + 1) as int by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies counts@[idx[r]] > 0 by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].ev_kind@ == events.ev_kind__dict@[idx[r]]@ by {
                    if r < old.len() as int { assert(res@[r] == old[r]); }
                };
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].n == counts@[idx[r]] && res@[r].q == sums@[idx[r]] by {
                    if r < old.len() as int { assert(res@[r] == old[r]); }
                };
                assert forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() implies idx[r] < idx[r2] by {};
                assert forall|q: int| #![trigger counts@[q]] 0 <= q < (c + 1) as int && counts@[q] > 0 implies exists|r: int| 0 <= r < idx.len() && idx[r] == q by {
                    if q == c as int { assert(idx[old.len() as int] == q); }
                    else {
                        let r = choose|r: int| 0 <= r < old_idx.len() && old_idx[r] == q;
                        assert(idx[r] == q);
                    }
                };
            }
        }
        c += 1;
    }
    proof {
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(events, res@[r]) by {
            let q = idx[r];
            assert(counts@[q] > 0);
            assert(counts@[q] as int == count_n(events, 0, events.ev_kind__dict@[q]@));
            lemma_count_pos(events, 0, events.ev_kind__dict@[q]@);
            let j = choose|j: int| 0 <= j < events.n as int && row_hit(events, j) && key_at(events, j) == events.ev_kind__dict@[q]@;
            assert(row_hit(events, j) && key_at(events, j) == res@[r].ev_kind@);
            assert((res@[r].n as int) == count_n(events, 0, res@[r].ev_kind@));
            assert((res@[r].q as int) == sum_q(events, 0, res@[r].ev_kind@));
        };
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies res@[a].ev_kind@ != res@[b].ev_kind@ by {
            assert(idx[a] < idx[b]);
            assert(idx[b] < m as int);
            assert(events.ev_kind__dict@[idx[a]]@ != events.ev_kind__dict@[idx[b]]@);
        };
        assert forall|i0: int| #![trigger row_hit(events, i0)] row_hit(events, i0) && (true) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(events, i0) == res@[r].ev_kind@ by {
            let code = events.ev_kind@[i0] as int;
            assert(key_at(events, i0) == events.ev_kind__dict@[code]@);
            lemma_count_pos(events, 0, events.ev_kind__dict@[code]@);
            assert(counts@[code] as int == count_n(events, 0, events.ev_kind__dict@[code]@));
            assert(counts@[code] > 0);
            let r = choose|r: int| 0 <= r < idx.len() && idx[r] == code;
            assert(res@[r].ev_kind@ == events.ev_kind__dict@[code]@);
        };
    }
    res
// AGENT_EDIT_END
