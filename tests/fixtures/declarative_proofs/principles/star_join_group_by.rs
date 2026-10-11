// Principle 4: a chain (star) join of a fact table with TWO unique-key dimension tables, then GROUP BY a dimension's string column (dictionary mode + LEMMA_JOIN_CHAIN=1).
//   SELECT it_group, SUM(ev_qty) AS q FROM events, items, users
//   WHERE ev_item = it_id AND ev_user = us_id AND us_level >= 3 GROUP BY it_group
// * Both dimension keys are unique (`valid_cols_items`, `valid_cols_users`), so each fact row has at most one matching tuple `(i, a, b)`: `lemma_chain_hit_unique` says so,
//   and the host lemma `lemma_sum_q_row(events, items, users, j, k)` gives the fold of fact row `j` for a group key `k`. `lemma_step_hit` / `lemma_step_none` below
//   turn that into the one-row step `sum_q(j, k) == sum_q(j + 1, k) + (this row's quantity if its group is k)`; nothing counts matches.
// * Each dimension gets an index `arr[key + 999] = row + 1` (principle 3). The scan runs from the end; a row is a hit when both probes find a row and the user filter holds.
// * The group state is one slot per DICTIONARY CODE of `it_group` (principle 2): `acc[c]` is the fold for key `dict[c]`, `pres[c]` says some hit row has that group.
//   Invariants: (A) `acc[c] == sum_q(events, items, users, i, dict[c]@)`; (B) `pres[c]` has a witness tuple; (C) every hit tuple at or after row `i` has its group present.
// * Closing: the host proves the three postconditions of a GROUPED result from plain ghost data (`group_close.py`): `gk` (group keys), `gw` (a witness tuple per group), `sel`.
//   Here the result is one row per present code in code order, so `sel[r] == r`, every group is `used`, and `pos[g] == g`.
// AGENT_HELPERS_START
spec fn idx_fwd(keys: Seq<i64>, arr: Seq<usize>) -> bool {
    forall|a: int| #![trigger keys[a]] 0 <= a < keys.len() ==> arr[keys[a] as int + 999] == a + 1
}

spec fn idx_bwd(keys: Seq<i64>, arr: Seq<usize>) -> bool {
    forall|p: int| #![trigger arr[p]] 0 <= p < arr.len() && arr[p] != 0usize ==> exists|a: int| #![trigger keys[a]]
        0 <= a < keys.len() && keys[a] as int + 999 == p && arr[p] == a + 1
}

spec fn wit(events: &Cols_events, items: &Cols_items, users: &Cols_users, c: int) -> bool {
    exists|j: int, a: int, b: int| #![trigger row_hit(events, items, users, j, a, b)]
        row_hit(events, items, users, j, a, b) && key_at(events, items, users, j, a, b) == items.it_group__dict@[c]@
}

// fact row j has a matching tuple (a, b): its fold for key k is the row's quantity if the tuple's group is k
proof fn lemma_step_hit(events: &Cols_events, items: &Cols_items, users: &Cols_users, j: int, a: int, b: int, k: Seq<char>)
    requires
        valid_cols_events(events), valid_cols_items(items), valid_cols_users(users),
        row_hit(events, items, users, j, a, b),
    ensures
        sum_q(events, items, users, j, k) == sum_q(events, items, users, j + 1, k)
            + (if key_at(events, items, users, j, a, b) == k { events.ev_qty@[j] as int } else { 0int }),
{
    lemma_sum_q_row(events, items, users, j, k);
    reveal_with_fuel(sum_q, 2);
}

// fact row j has no matching tuple: it adds nothing to any key
proof fn lemma_step_none(events: &Cols_events, items: &Cols_items, users: &Cols_users, j: int, k: Seq<char>)
    requires
        valid_cols_events(events), valid_cols_items(items), valid_cols_users(users),
        0 <= j < events.n as int,
        forall|z1: int, z2: int| #![trigger row_hit(events, items, users, j, z1, z2)] !row_hit(events, items, users, j, z1, z2),
    ensures
        sum_q(events, items, users, j, k) == sum_q(events, items, users, j + 1, k),
{
    lemma_sum_q_row(events, items, users, j, k);
    reveal_with_fuel(sum_q, 2);
}

// a matching tuple of fact row j is found by BOTH indexes
proof fn lemma_probe(events: &Cols_events, items: &Cols_items, users: &Cols_users, ai: Seq<usize>, au: Seq<usize>, j: int, a: int, b: int)
    requires
        valid_cols_events(events), valid_cols_items(items), valid_cols_users(users),
        idx_fwd(items.it_id@, ai),
        idx_fwd(users.us_id@, au),
        row_hit(events, items, users, j, a, b),
    ensures
        ai[events.ev_item@[j] as int + 999] == a + 1,
        au[events.ev_user@[j] as int + 999] == b + 1,
{
    assert(items.it_id@.len() == items.n as int && users.us_id@.len() == users.n as int);
    assert(items.it_id@[a] == events.ev_item@[j]);
    assert(users.us_id@[b] == events.ev_user@[j]);
    assert(ai[items.it_id@[a] as int + 999] == a + 1);
    assert(au[users.us_id@[b] as int + 999] == b + 1);
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    fn build_index(keys: &Vec<i64>) -> (arr: Vec<usize>)
        requires
            keys@.len() < 1000,
            forall|a: int| #![trigger keys@[a]] 0 <= a < keys@.len() ==> -999 <= keys@[a] as int <= 999,
            forall|a: int, b: int| #![trigger keys@[a], keys@[b]] 0 <= a < b < keys@.len() ==> keys@[a] != keys@[b],
        ensures
            arr@.len() == 1999,
            idx_fwd(keys@, arr@),
            idx_bwd(keys@, arr@),
    {
        let mut arr: Vec<usize> = vec![0usize; 1999];
        let mut a: usize = 0;
        while a < keys.len()
            invariant
                a <= keys@.len(),
                keys@.len() < 1000,
                arr@.len() == 1999,
                forall|b: int| #![trigger keys@[b]] 0 <= b < keys@.len() ==> -999 <= keys@[b] as int <= 999,
                forall|b: int, c: int| #![trigger keys@[b], keys@[c]] 0 <= b < c < keys@.len() ==> keys@[b] != keys@[c],
                forall|b: int| #![trigger keys@[b]] 0 <= b < a as int ==> arr@[keys@[b] as int + 999] == b + 1,
                forall|p: int| #![trigger arr@[p]] 0 <= p < arr@.len() && arr@[p] != 0usize ==> exists|b: int| #![trigger keys@[b]]
                    0 <= b < a as int && keys@[b] as int + 999 == p && arr@[p] == b + 1,
            decreases keys@.len() - a,
        {
            let pos: usize = (keys[a] + 999) as usize;
            let ghost old = arr@;
            arr.set(pos, a + 1);
            proof {
                assert forall|b: int| #![trigger keys@[b]] 0 <= b < a as int + 1 implies arr@[keys@[b] as int + 999] == b + 1 by {
                    if b < a as int {
                        assert(keys@[b] != keys@[a as int]);
                    }
                }
                assert forall|p: int| #![trigger arr@[p]] 0 <= p < arr@.len() && arr@[p] != 0usize implies exists|b: int| #![trigger keys@[b]]
                    0 <= b < a as int + 1 && keys@[b] as int + 999 == p && arr@[p] == b + 1 by {
                    if p != pos as int {
                        assert(old[p] == arr@[p]);
                        let b = choose|b: int| 0 <= b < a as int && keys@[b] as int + 999 == p && old[p] == b + 1;
                        assert(0 <= b < a as int + 1 && keys@[b] as int + 999 == p && arr@[p] == b + 1);
                    } else {
                        assert(keys@[a as int] as int + 999 == p && arr@[p] == a as int + 1);
                    }
                }
            }
            a += 1;
        }
        arr
    }

    let ai = build_index(&items.it_id);
    let au = build_index(&users.us_id);
    let m: usize = items.it_group__dict.len();
    let mut acc: Vec<i128> = vec![0i128; m];
    let mut pres: Vec<bool> = vec![false; m];
    let mut i: usize = events.n;
    while i > 0
        invariant
            i <= events.n,
            valid_cols_events(events), valid_cols_items(items), valid_cols_users(users),
            ai@.len() == 1999, au@.len() == 1999,
            idx_fwd(items.it_id@, ai@), idx_bwd(items.it_id@, ai@),
            idx_fwd(users.us_id@, au@), idx_bwd(users.us_id@, au@),
            m == items.it_group__dict@.len(),
            acc@.len() == m as int, pres@.len() == m as int,
            // (A) every slot is the host fold for its key
            forall|c: int| #![trigger acc@[c]] 0 <= c < m as int ==> acc@[c] as int == sum_q(events, items, users, i as int, items.it_group__dict@[c]@)
                && -999 * ((events.n - i) as int) <= acc@[c] as int <= 999 * ((events.n - i) as int),
            // (B) a present slot has a witness tuple
            forall|c: int| #![trigger pres@[c]] 0 <= c < m as int && pres@[c] ==> wit(events, items, users, c),
            // (C) the group of every hit tuple at or after row i is present
            forall|j: int, a: int, b: int| #![trigger row_hit(events, items, users, j, a, b)]
                i as int <= j && row_hit(events, items, users, j, a, b) ==> pres@[items.it_group@[a] as int],
        decreases i,
    {
        i -= 1;
        let ki = events.ev_item[i];
        let ku = events.ev_user[i];
        let q = events.ev_qty[i];
        proof {
            assert(events.ev_item@.len() == events.n as int);
            assert(events.ev_user@.len() == events.n as int);
            assert(events.ev_qty@.len() == events.n as int);
            assert(-999 <= ki as int <= 999 && -999 <= ku as int <= 999);
        }
        let ci = ai[(ki + 999) as usize];
        let cu = au[(ku + 999) as usize];
        if ci != 0 && cu != 0 {
            let ra = ci - 1;
            let rb = cu - 1;
            proof {
                // the probes find real dimension rows with the fact row's keys
                let a0 = choose|a: int| 0 <= a < items.it_id@.len() && items.it_id@[a] as int + 999 == ki as int + 999 && ai@[ki as int + 999] == a + 1;
                let b0 = choose|b: int| 0 <= b < users.us_id@.len() && users.us_id@[b] as int + 999 == ku as int + 999 && au@[ku as int + 999] == b + 1;
                assert(a0 == ra as int && b0 == rb as int);
                assert(items.it_id@[ra as int] == ki && users.us_id@[rb as int] == ku);
                assert(users.us_level@.len() == users.n as int);
                assert(items.it_group@.len() == items.n as int);
            }
            if users.us_level[rb] >= 3 {
                // the unique hit tuple of row i is (i, ra, rb)
                let code = items.it_group[ra] as usize;
                proof {
                    assert(row_hit(events, items, users, i as int, ra as int, rb as int));
                    assert(code < m);
                }
                let before = acc[code];
                acc.set(code, before + (q as i128));
                pres.set(code, true);
                proof {
                    assert forall|c: int| #![trigger acc@[c]] 0 <= c < m as int implies acc@[c] as int == sum_q(events, items, users, i as int, items.it_group__dict@[c]@)
                        && -999 * ((events.n - i) as int) <= acc@[c] as int <= 999 * ((events.n - i) as int) by {
                        lemma_step_hit(events, items, users, i as int, ra as int, rb as int, items.it_group__dict@[c]@);
                        if c != code as int {
                            // two codes are two different dictionary entries
                            if c < code as int {
                                assert(items.it_group__dict@[c]@ != items.it_group__dict@[code as int]@);
                            } else {
                                assert(items.it_group__dict@[code as int]@ != items.it_group__dict@[c]@);
                            }
                        }
                    };
                    assert forall|c: int| #![trigger pres@[c]] 0 <= c < m as int && pres@[c] implies wit(events, items, users, c) by {
                        if c == code as int {
                            assert(row_hit(events, items, users, i as int, ra as int, rb as int) && key_at(events, items, users, i as int, ra as int, rb as int) == items.it_group__dict@[c]@);
                        }
                    };
                    assert forall|j: int, a: int, b: int| #![trigger row_hit(events, items, users, j, a, b)]
                        i as int <= j && row_hit(events, items, users, j, a, b) implies pres@[items.it_group@[a] as int] by {
                        if j == i as int {
                            lemma_chain_hit_unique(events, items, users, j, ra as int, rb as int, a, b);
                        }
                    };
                }
            } else {
                proof {
                    assert forall|z1: int, z2: int| #![trigger row_hit(events, items, users, i as int, z1, z2)] !row_hit(events, items, users, i as int, z1, z2) by {
                        if row_hit(events, items, users, i as int, z1, z2) {
                            lemma_probe(events, items, users, ai@, au@, i as int, z1, z2);
                            assert(z2 == rb as int);
                        }
                    }
                    assert forall|c: int| #![trigger acc@[c]] 0 <= c < m as int implies acc@[c] as int == sum_q(events, items, users, i as int, items.it_group__dict@[c]@) by {
                        lemma_step_none(events, items, users, i as int, items.it_group__dict@[c]@);
                    };
                }
            }
        } else {
            proof {
                assert forall|z1: int, z2: int| #![trigger row_hit(events, items, users, i as int, z1, z2)] !row_hit(events, items, users, i as int, z1, z2) by {
                    if row_hit(events, items, users, i as int, z1, z2) {
                        lemma_probe(events, items, users, ai@, au@, i as int, z1, z2);
                    }
                }
                assert forall|c: int| #![trigger acc@[c]] 0 <= c < m as int implies acc@[c] as int == sum_q(events, items, users, i as int, items.it_group__dict@[c]@) by {
                    lemma_step_none(events, items, users, i as int, items.it_group__dict@[c]@);
                };
            }
        }
    }
    // emit one row per present code, in code order, recording the ghost data the host closing lemmas take
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut gk: Seq<Seq<char>> = Seq::empty();
    let ghost mut gw: Seq<(int, int, int)> = Seq::empty();
    let ghost mut idx: Seq<int> = Seq::empty();
    let mut c: usize = 0;
    while c < m
        invariant
            c <= m,
            valid_cols_events(events), valid_cols_items(items), valid_cols_users(users),
            m == items.it_group__dict@.len(),
            acc@.len() == m as int, pres@.len() == m as int,
            forall|q: int| #![trigger acc@[q]] 0 <= q < m as int ==> acc@[q] as int == sum_q(events, items, users, 0, items.it_group__dict@[q]@),
            forall|q: int| #![trigger pres@[q]] 0 <= q < m as int && pres@[q] ==> wit(events, items, users, q),
            gk.len() == res@.len() && gw.len() == res@.len() && idx.len() == res@.len(),
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> 0 <= idx[r] < c as int && pres@[idx[r]] && gk[r] == items.it_group__dict@[idx[r]]@,
            forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> res@[r].it_group@ == gk[r] && res@[r].q as int == sum_q(events, items, users, 0, gk[r]),
            forall|r: int| #![trigger gw[r]] 0 <= r < gw.len() ==> row_hit(events, items, users, gw[r].0, gw[r].1, gw[r].2) && key_at(events, items, users, gw[r].0, gw[r].1, gw[r].2) == gk[r],
            forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() ==> idx[r] < idx[r2],
            forall|q: int| #![trigger pres@[q]] 0 <= q < c as int && pres@[q] ==> exists|r: int| 0 <= r < idx.len() && idx[r] == q,
        decreases m - c,
    {
        if pres[c] {
            let ghost old_res = res@;
            let ghost old_gk = gk;
            let ghost old_gw = gw;
            let ghost old_idx = idx;
            res.push(OutRow { it_group: items.it_group__dict[c].clone(), q: acc[c] });
            proof {
                let x = res@[old_res.len() as int];
                assert(res@ == old_res.push(x));
                assert(x.it_group@ == items.it_group__dict@[c as int]@ && x.q == acc@[c as int]);
                let w = choose|j: int, a: int, b: int| #![trigger row_hit(events, items, users, j, a, b)]
                    row_hit(events, items, users, j, a, b) && key_at(events, items, users, j, a, b) == items.it_group__dict@[c as int]@;
                gk = old_gk.push(items.it_group__dict@[c as int]@);
                gw = old_gw.push(w);
                idx = old_idx.push(c as int);
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies 0 <= idx[r] < (c + 1) as int && pres@[idx[r]] && gk[r] == items.it_group__dict@[idx[r]]@ by {}
                assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies res@[r].it_group@ == gk[r] && res@[r].q as int == sum_q(events, items, users, 0, gk[r]) by {
                    if r < old_res.len() as int {
                        assert(res@[r] == old_res[r]);
                    }
                };
                assert forall|r: int| #![trigger gw[r]] 0 <= r < gw.len() implies row_hit(events, items, users, gw[r].0, gw[r].1, gw[r].2) && key_at(events, items, users, gw[r].0, gw[r].1, gw[r].2) == gk[r] by {};
                assert forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() implies idx[r] < idx[r2] by {};
                assert forall|q: int| #![trigger pres@[q]] 0 <= q < (c + 1) as int && pres@[q] implies exists|r: int| 0 <= r < idx.len() && idx[r] == q by {
                    if q == c as int {
                        assert(idx[old_idx.len() as int] == q);
                    } else {
                        let r = choose|r: int| 0 <= r < old_idx.len() && old_idx[r] == q;
                        assert(idx[r] == q);
                    }
                };
            }
        }
        c += 1;
    }
    proof {
        let n = gk.len() as int;
        let sel = Seq::new(gk.len(), |r: int| r);
        let used = Seq::new(gk.len(), |g: int| true);
        // (C) at row 0: every hit tuple's group is present, hence has a result row
        assert forall|i0: int, i1: int, i2: int| #![trigger row_hit(events, items, users, i0, i1, i2)]
            row_hit(events, items, users, i0, i1, i2) && (true) implies exists|g: int| #![trigger gk[g]] 0 <= g < gk.len() && gk[g] == key_at(events, items, users, i0, i1, i2) by {
            let code = items.it_group@[i1] as int;
            assert(pres@[code]);
            let r = choose|r: int| 0 <= r < idx.len() && idx[r] == code;
            assert(gk[r] == items.it_group__dict@[code]@);
        };
        assert forall|a: int, b: int| #![trigger gk[a], gk[b]] 0 <= a < b < gk.len() implies gk[a] != gk[b] by {
            assert(idx[a] < idx[b]);
            assert(items.it_group__dict@[idx[a]]@ != items.it_group__dict@[idx[b]]@);
        };
        lemma_group_close_rows(events, items, users, res@, gk, gw, sel);
        lemma_group_close_distinct(events, items, users, res@, gk, sel);
        lemma_group_close_present(events, items, users, res@, gk, sel, used, sel);
    }
    res
// AGENT_EDIT_END
