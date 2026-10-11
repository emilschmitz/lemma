// Principle 3: an equi-join on a UNIQUE key, as a lookup. Build an index of the dimension table once, then scan the fact table and probe it (LEMMA_JOIN_CHAIN=1).
//   SELECT COUNT(*) AS n, SUM(ev_qty) AS q FROM events, items WHERE ev_item = it_id AND it_shelf < 20
// * `valid_cols_items` says `it_id` is unique (a catalog assumption, checked by the loader), so a fact row matches at most ONE dimension row.
//   The host proves it for you: `lemma_count_n_row(events, items, j)` says, for fact row `j`, that if `(j, y1)` passes `row_hit` then the inner fold
//   equals the term of that one tuple, and if no `(j, y1)` passes the inner fold is 0. You never count matches or reason about nested sums.
// * The index: `arr[key + 999] = row + 1` (0 = no such key). `idx_fwd`: every dimension row is found at its key; `idx_bwd`: every nonzero cell names a row with that key.
//   999 is the key cap in `valid_cols_*`: use YOUR spec's cap for the offset and the array size.
// * The scan, from the end, keeps `cnt == count_n(events, items, i)`; a row with a nonzero cell and a passing dimension filter is the unique hit; a zero cell means
//   no dimension row has that key, so no tuple passes `row_hit` for this fact row (that is what `idx_fwd` is for).
// AGENT_HELPERS_START
spec fn idx_fwd(keys: Seq<i64>, arr: Seq<usize>) -> bool {
    forall|a: int| #![trigger keys[a]] 0 <= a < keys.len() ==> arr[keys[a] as int + 999] == a + 1
}

spec fn idx_bwd(keys: Seq<i64>, arr: Seq<usize>) -> bool {
    forall|p: int| #![trigger arr[p]] 0 <= p < arr.len() && arr[p] != 0usize ==> exists|a: int| #![trigger keys[a]]
        0 <= a < keys.len() && keys[a] as int + 999 == p && arr[p] == a + 1
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

    let arr = build_index(&items.it_id);
    let mut cnt: u64 = 0;
    let mut sq: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = events.n;
    while i > 0
        invariant
            i <= events.n,
            valid_cols_events(events),
            valid_cols_items(items),
            arr@.len() == 1999,
            idx_fwd(items.it_id@, arr@),
            idx_bwd(items.it_id@, arr@),
            cnt as int == count_n(events, items, i as int),
            sq as int == sum_q(events, items, i as int),
            cnt as int <= (events.n - i) as int,
            -999 * ((events.n - i) as int) <= sq as int <= 999 * ((events.n - i) as int),
            any <==> exists|i0: int, i1: int| #![trigger row_hit(events, items, i0, i1)] i as int <= i0 && row_hit(events, items, i0, i1),
        decreases i,
    {
        i -= 1;
        let key = events.ev_item[i];
        let q = events.ev_qty[i];
        proof {
            assert(events.ev_item@.len() == events.n as int);
            assert(events.ev_qty@.len() == events.n as int);
            assert(-999 <= key as int <= 999);
            lemma_count_n_row(events, items, i as int);
            lemma_sum_q_row(events, items, i as int);
            reveal_with_fuel(count_n, 2);
            reveal_with_fuel(sum_q, 2);
        }
        let cell = arr[(key + 999) as usize];
        if cell != 0 {
            let r = cell - 1;
            proof {
                // the cell names a dimension row with this key
                let b = choose|b: int| 0 <= b < items.it_id@.len() && items.it_id@[b] as int + 999 == key as int + 999 && arr@[key as int + 999] == b + 1;
                assert(b == r as int);
                assert(items.it_id@[r as int] == key);
                assert(items.it_shelf@.len() == items.n as int);
            }
            let shelf = items.it_shelf[r];
            if shelf < 20 {
                proof {
                    assert(row_hit(events, items, i as int, r as int));
                }
                cnt = cnt + 1;
                sq = sq + (q as i128);
                any = true;
            } else {
                proof {
                    // no other dimension row has this key (unique), so no tuple passes for fact row i
                    assert forall|z: int| #![trigger row_hit(events, items, i as int, z)] !row_hit(events, items, i as int, z) by {
                        if row_hit(events, items, i as int, z) {
                            assert(items.it_id@[z] == key);
                            assert(arr@[key as int + 999] == z + 1);
                            assert(z == r as int);
                        }
                    }
                }
            }
        } else {
            proof {
                assert forall|z: int| #![trigger row_hit(events, items, i as int, z)] !row_hit(events, items, i as int, z) by {
                    if row_hit(events, items, i as int, z) {
                        assert(items.it_id@[z] == key);
                        assert(arr@[key as int + 999] == z + 1);
                    }
                }
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { n: cnt, q: if any { Some(sq) } else { None } });
    res
// AGENT_EDIT_END
