    // Rows backwards, as in projection_where. A row passes when its value is the maximum of its group:
    // an inner loop computes that maximum, then `sq_1` (exists a row equal to the bound, all rows <= it) is shown for it.
    let mut res: Vec<OutRow> = Vec::new();
    let mut i: usize = t1.n;
    while i > 0
        invariant
            i <= t1.n,
            valid_cols_t(t1),
            res@.len() as int == hit_count(t1, i as int),
            forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(t1, res@[r]),
            forall|k: int| #![trigger out_copies(res@, 0, k)] out_copies(res@, 0, k) == hits_with(t1, i as int, k),
        decreases i,
    {
        i -= 1;
        proof {
            assert(t1.a@.len() == t1.n as int);
            assert(t1.g@.len() == t1.n as int);
        }
        let a = t1.a[i];
        let g = t1.g[i];
        let mut m: i64 = a;
        let mut j: usize = 0;
        while j < t1.n
            invariant
                j <= t1.n,
                i < t1.n,
                valid_cols_t(t1),
                t1.a@[i as int] == a,
                t1.g@[i as int] == g,
                forall|j2: int| #![trigger t1.a@[j2]] 0 <= j2 < j as int && t1.g@[j2] == g ==> t1.a@[j2] <= m,
                exists|j2: int| #![trigger t1.a@[j2]] 0 <= j2 < t1.n as int && t1.g@[j2] == g && t1.a@[j2] == m,
            decreases t1.n - j,
        {
            proof {
                assert(t1.a@.len() == t1.n as int);
                assert(t1.g@.len() == t1.n as int);
            }
            let aj = t1.a[j];
            let gj = t1.g[j];
            if gj == g && aj > m {
                m = aj;
                proof {
                    assert(t1.a@[j as int] == m && t1.g@[j as int] == g);
                }
            }
            j += 1;
        }
        proof {
            // m is the group maximum and row i belongs to the group, so a == m <==> sq_1(t1, i, a).
            assert(t1.a@[i as int] <= m);
            if (a as int) == (m as int) {
                assert(sq_1(t1, i as int, a as int));
            } else {
                assert(!sq_1(t1, i as int, a as int)) by {
                    if sq_1(t1, i as int, a as int) {
                        let j2 = choose|j2: int| 0 <= j2 < t1.n as int && t1.g@[j2] == g && t1.a@[j2] == m;
                        assert(t1.a@[j2] <= t1.a@[i as int]);
                    }
                };
            }
        }
        if a == m {
            let ghost old = res@;
            res.insert(0, OutRow { a: a });
            proof {
                let x = OutRow { a: a };
                assert(res@ == old.insert(0, x));
                assert(row_hit(t1, i as int));
                assert(out_key(x) == proj_key(t1, i as int));
                assert(out_row_ok(t1, x));
                assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(t1, res@[r]) by {
                    if r > 0 {
                        assert(res@[r] == old[r - 1]);
                    }
                };
                assert forall|k: int| #![trigger out_copies(res@, 0, k)] out_copies(res@, 0, k) == hits_with(t1, i as int, k) by {
                    lemma_shift(old, x, 0, k);
                    assert(out_copies(res@, 1, k) == out_copies(old, 0, k));
                };
            }
        } else {
            proof {
                assert(!row_hit(t1, i as int));
            }
        }
    }
    res
