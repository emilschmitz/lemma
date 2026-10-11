// Principle 5: top-N with ORDER BY ... LIMIT, ties included (a projection, no GROUP BY).
//   SELECT ev_qty, ev_user FROM events WHERE ev_qty > 1 ORDER BY ev_qty DESC LIMIT 3
// * The spec talks about a MULTISET of result keys: `out_copies(res, 0, k)` is how many times key `k` is in `res`, `hits_with(events, i, k)` how many passing rows from `i`
//   on have key `k`. The postconditions: every result row is a passing row; the rows are sorted by the ORDER BY column; no key appears more often than it passes;
//   `res` has `min(3, hit_count)` rows; and (the tie rule) if a passing row was left out, the LAST kept row is not smaller than it.
//   So which of several rows with EQUAL sort keys survive is not fixed by the spec: any of them is a correct answer, and DuckDB's choice is checked up to ties.
// * One backward pass keeps `res` = the top 3 of the rows seen so far, sorted. A passing row is inserted before the first strictly smaller kept row
//   (`res[p].ev_qty >= a` skips equal keys, so a new row that ties the last kept one lands behind it); if that makes 4 rows the last is popped. A row that ties all
//   3 kept rows is not inserted at all. The invariant (M) is the tie rule above for the suffix seen so far.
// * `lemma_insert` / `lemma_drop` (helpers) say how `out_copies` changes when a row is inserted at `p` or the last row is popped.
// AGENT_HELPERS_START
proof fn lemma_tail(s: Seq<OutRow>, p: int, x: OutRow, i: int, k: (int, int))
    requires
        0 <= p <= s.len(),
        p <= i,
    ensures
        out_copies(s.insert(p, x), i + 1, k) == out_copies(s, i, k),
    decreases s.len() - i,
{
    if i < s.len() {
        lemma_tail(s, p, x, i + 1, k);
        assert(s.insert(p, x)[i + 1] == s[i]);
    }
}

proof fn lemma_insert(s: Seq<OutRow>, p: int, x: OutRow, i: int, k: (int, int))
    requires
        0 <= i <= p <= s.len(),
    ensures
        out_copies(s.insert(p, x), i, k) == out_copies(s, i, k) + (if out_key(x) == k { 1int } else { 0int }),
    decreases p - i,
{
    if i < p {
        assert(s.insert(p, x)[i] == s[i]);
        lemma_insert(s, p, x, i + 1, k);
    } else {
        assert(s.insert(p, x)[p] == x);
        lemma_tail(s, p, x, p, k);
    }
}

proof fn lemma_drop(s: Seq<OutRow>, i: int, k: (int, int))
    requires
        s.len() > 0,
        0 <= i,
    ensures
        out_copies(s.drop_last(), i, k) + (if i < s.len() && out_key(s.last()) == k { 1int } else { 0int })
            == out_copies(s, i, k),
    decreases s.len() - i,
{
    if i < s.len() - 1 {
        assert(s.drop_last()[i] == s[i]);
        lemma_drop(s, i + 1, k);
    } else if i == s.len() - 1 {
        assert(s[i] == s.last());
        assert(out_copies(s, i + 1, k) == 0);
        assert(out_copies(s.drop_last(), i, k) == 0);
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    // Streaming top-3 over the rows from last to first. `res` is the top 3 of the suffix, sorted by `a` descending.
    // A passing row is inserted before the first smaller one; when that makes 4 rows the last one is dropped.
    // (M) says: if some key still has an omitted copy, the last kept row is not smaller than that key.
    let mut res: Vec<OutRow> = Vec::new();
    let mut i: usize = events.n;
    while i > 0
        invariant
            i <= events.n,
            valid_cols_events(events),
            res@.len() <= 3,
            res@.len() as int == (if hit_count(events, i as int) < 3 { hit_count(events, i as int) } else { 3int }),
            forall|q: int| #![trigger res@[q]] 0 <= q && q + 1 < res@.len() ==> res@[q].ev_qty >= res@[q + 1].ev_qty,
            forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(events, res@[r]),
            forall|k: (int, int)| #![trigger out_copies(res@, 0, k)] out_copies(res@, 0, k) <= hits_with(events, i as int, k),
            res@.len() as int == hit_count(events, i as int) ==> forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                out_copies(res@, 0, k) == hits_with(events, i as int, k),
            forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                hits_with(events, i as int, k) > out_copies(res@, 0, k) && res@.len() > 0 ==> res@[res@.len() - 1].ev_qty as int >= k.0,
        decreases i,
    {
        i -= 1;
        let a = events.ev_qty[i];
        let g = events.ev_user[i];
        proof {
            assert(events.ev_qty@.len() == events.n as int);
            assert(events.ev_user@.len() == events.n as int);
        }
        if a > 1 {
            let ghost old = res@;
            let mut p: usize = 0;
            while p < res.len() && res[p].ev_qty >= a
                invariant
                    p <= res@.len(),
                    res@ == old,
                    forall|q: int| #![trigger res@[q]] 0 <= q < p as int ==> res@[q].ev_qty >= a,
                decreases res@.len() - p,
            {
                p += 1;
            }
            let x = OutRow { ev_qty: a, ev_user: g };
            proof {
                assert(row_hit(events, i as int));
                assert(out_key(x) == proj_key(events, i as int));
                assert(out_row_ok(events, x));
                assert(hit_count(events, i as int) == 1 + hit_count(events, (i + 1) as int));
                assert forall|k: (int, int)| #![trigger hits_with(events, i as int, k)]
                    hits_with(events, i as int, k) == hits_with(events, (i + 1) as int, k) + (if out_key(x) == k { 1int } else { 0int }) by {};
            }
            if p == 3 {
                // x is not larger than any kept row, and 3 rows are kept: x is omitted.
                proof {
                    assert forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                        hits_with(events, i as int, k) > out_copies(res@, 0, k) && res@.len() > 0 implies res@[res@.len() - 1].ev_qty as int >= k.0 by {
                        if out_key(x) == k {
                            assert(res@[2].ev_qty >= a);
                        }
                    };
                }
            } else {
                res.insert(p, x);
                proof {
                    assert forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                        out_copies(res@, 0, k) == out_copies(old, 0, k) + (if out_key(x) == k { 1int } else { 0int }) by {
                        lemma_insert(old, p as int, x, 0, k);
                    };
                }
                if res.len() > 3 {
                    let ghost mid = res@;
                    let _y = res.pop();
                    proof {
                        assert(res@ == mid.drop_last());
                        assert forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                            out_copies(res@, 0, k) + (if out_key(mid.last()) == k { 1int } else { 0int }) == out_copies(mid, 0, k) by {
                            lemma_drop(mid, 0, k);
                        };
                    }
                }
                proof {
                    assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(events, res@[r]) by {
                        assert(res@[r] == x || exists|q: int| 0 <= q < old.len() && res@[r] == old[q]);
                    };
                }
            }
        } else {
            proof {
                assert(!row_hit(events, i as int));
                assert(hit_count(events, i as int) == hit_count(events, (i + 1) as int));
            }
        }
    }
    res
// AGENT_EDIT_END
