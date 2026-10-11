    // Streaming top-3 over the rows from last to first. `res` is the top 3 of the suffix, sorted by `a` descending.
    // A passing row is inserted before the first smaller one; when that makes 4 rows the last one is dropped.
    // (M) says: if some key still has an omitted copy, the last kept row is not smaller than that key.
    let mut res: Vec<OutRow> = Vec::new();
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            valid_cols_t(t),
            res@.len() <= 3,
            res@.len() as int == (if hit_count(t, i as int) < 3 { hit_count(t, i as int) } else { 3int }),
            forall|q: int| #![trigger res@[q]] 0 <= q && q + 1 < res@.len() ==> res@[q].a >= res@[q + 1].a,
            forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(t, res@[r]),
            forall|k: (int, int)| #![trigger out_copies(res@, 0, k)] out_copies(res@, 0, k) <= hits_with(t, i as int, k),
            res@.len() as int == hit_count(t, i as int) ==> forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                out_copies(res@, 0, k) == hits_with(t, i as int, k),
            forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                hits_with(t, i as int, k) > out_copies(res@, 0, k) && res@.len() > 0 ==> res@[res@.len() - 1].a as int >= k.0,
        decreases i,
    {
        i -= 1;
        let a = t.a[i];
        let g = t.g[i];
        proof {
            assert(t.a@.len() == t.n as int);
            assert(t.g@.len() == t.n as int);
        }
        if a > 1 {
            let ghost old = res@;
            let mut p: usize = 0;
            while p < res.len() && res[p].a >= a
                invariant
                    p <= res@.len(),
                    res@ == old,
                    forall|q: int| #![trigger res@[q]] 0 <= q < p as int ==> res@[q].a >= a,
                decreases res@.len() - p,
            {
                p += 1;
            }
            let x = OutRow { a: a, g: g };
            proof {
                assert(row_hit(t, i as int));
                assert(out_key(x) == proj_key(t, i as int));
                assert(out_row_ok(t, x));
                assert(hit_count(t, i as int) == 1 + hit_count(t, (i + 1) as int));
                assert forall|k: (int, int)| #![trigger hits_with(t, i as int, k)]
                    hits_with(t, i as int, k) == hits_with(t, (i + 1) as int, k) + (if out_key(x) == k { 1int } else { 0int }) by {};
            }
            if p == 3 {
                // x is not larger than any kept row, and 3 rows are kept: x is omitted.
                proof {
                    assert forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                        hits_with(t, i as int, k) > out_copies(res@, 0, k) && res@.len() > 0 implies res@[res@.len() - 1].a as int >= k.0 by {
                        if out_key(x) == k {
                            assert(res@[2].a >= a);
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
                    assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(t, res@[r]) by {
                        assert(res@[r] == x || exists|q: int| 0 <= q < old.len() && res@[r] == old[q]);
                    };
                }
            }
        } else {
            proof {
                assert(!row_hit(t, i as int));
                assert(hit_count(t, i as int) == hit_count(t, (i + 1) as int));
            }
        }
    }
    res
