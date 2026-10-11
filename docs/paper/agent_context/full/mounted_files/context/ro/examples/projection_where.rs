    // Walk the rows from the last to the first and put each passing row in front of the result.
    // Invariants: the result is the passing rows of the suffix, counted per key like the spec's fold.
    let mut res: Vec<OutRow> = Vec::new();
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            valid_cols_t(t),
            res@.len() as int == hit_count(t, i as int),
            forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(t, res@[r]),
            forall|k: (int, int)| #![trigger out_copies(res@, 0, k)] out_copies(res@, 0, k) == hits_with(t, i as int, k),
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
            res.insert(0, OutRow { a: a, g: g });
            proof {
                let x = OutRow { a: a, g: g };
                assert(res@ == old.insert(0, x));
                assert(row_hit(t, i as int));
                assert(out_key(x) == proj_key(t, i as int));
                assert(out_row_ok(t, x));
                assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(t, res@[r]) by {
                    if r > 0 {
                        assert(res@[r] == old[r - 1]);
                    }
                };
                assert forall|k: (int, int)| #![trigger out_copies(res@, 0, k)] out_copies(res@, 0, k) == hits_with(t, i as int, k) by {
                    lemma_shift(old, x, 0, k);
                    assert(out_copies(res@, 1, k) == out_copies(old, 0, k));
                    assert(out_copies(old, 0, k) == hits_with(t, (i + 1) as int, k));
                };
            }
        } else {
            proof {
                assert(!row_hit(t, i as int));
            }
        }
    }
    res
