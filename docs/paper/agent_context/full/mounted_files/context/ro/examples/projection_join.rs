    // Same recipe as projection_where: walk the rows backwards and put each passing row in front.
    // The inner invariant adds the partial inner fold to the finished outer suffix.
    let mut res: Vec<OutRow> = Vec::new();
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            valid_cols_t(t),
            valid_cols_u(u),
            res@.len() as int == hit_count(t, u, i as int),
            forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(t, u, res@[r]),
            forall|k: (int, int)| #![trigger out_copies(res@, 0, k)] out_copies(res@, 0, k) == hits_with(t, u, i as int, k),
        decreases i,
    {
        i -= 1;
        let ghost base = res@;
        let mut j: usize = u.n;
        while j > 0
            invariant
                j <= u.n,
                i < t.n,
                valid_cols_t(t),
                valid_cols_u(u),
                res@.len() as int == hit_count_d1(t, u, i as int, j as int) + base.len(),
                base.len() as int == hit_count(t, u, (i + 1) as int),
                forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(t, u, res@[r]),
                forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                    out_copies(res@, 0, k) == hits_with_d1(t, u, i as int, j as int, k) + hits_with(t, u, (i + 1) as int, k),
            decreases j,
        {
            j -= 1;
            let a = t.a[i];
            let gt = t.g[i];
            let w = u.w[j];
            let gu = u.g[j];
            proof {
                assert(t.a@.len() == t.n as int);
                assert(t.g@.len() == t.n as int);
                assert(u.w@.len() == u.n as int);
                assert(u.g@.len() == u.n as int);
            }
            if gt == gu {
                let ghost old = res@;
                res.insert(0, OutRow { a: a, w: w });
                proof {
                    let x = OutRow { a: a, w: w };
                    assert(res@ == old.insert(0, x));
                    assert(row_hit(t, u, i as int, j as int));
                    assert(out_key(x) == proj_key(t, u, i as int, j as int));
                    assert(out_row_ok(t, u, x));
                    assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(t, u, res@[r]) by {
                        if r > 0 {
                            assert(res@[r] == old[r - 1]);
                        }
                    };
                    assert forall|k: (int, int)| #![trigger out_copies(res@, 0, k)]
                        out_copies(res@, 0, k) == hits_with_d1(t, u, i as int, j as int, k) + hits_with(t, u, (i + 1) as int, k) by {
                        lemma_shift(old, x, 0, k);
                        assert(out_copies(res@, 1, k) == out_copies(old, 0, k));
                    };
                }
            } else {
                proof {
                    assert(!row_hit(t, u, i as int, j as int));
                }
            }
        }
        proof {
            // hit_count(i) = hit_count_d1(i, 0) + hit_count(i + 1), and likewise for hits_with.
            assert forall|k: (int, int)| #![trigger out_copies(res@, 0, k)] out_copies(res@, 0, k) == hits_with(t, u, i as int, k) by {
                assert(hits_with(t, u, i as int, k) == hits_with_d1(t, u, i as int, 0, k) + hits_with(t, u, (i + 1) as int, k));
            };
            assert(hit_count(t, u, i as int) == hit_count_d1(t, u, i as int, 0) + hit_count(t, u, (i + 1) as int));
        }
    }
    res
