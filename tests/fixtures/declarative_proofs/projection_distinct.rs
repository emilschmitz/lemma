    // Rows forwards; a passing row is pushed unless an equal key is already there (linear scan).
    let mut res: Vec<OutRow> = Vec::new();
    let mut i: usize = 0;
    while i < t.n
        invariant
            i <= t.n,
            valid_cols_t(t),
            forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(t, res@[r]),
            forall|p: int, q: int| #![trigger res@[p], res@[q]] 0 <= p < q < res@.len() ==> out_key(res@[p]) != out_key(res@[q]),
            forall|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < i as int && row_hit(t, i0) ==> exists|r: int|
                #![trigger res@[r]] 0 <= r < res@.len() && out_key(res@[r]) == proj_key(t, i0),
        decreases t.n - i,
    {
        proof {
            assert(t.a@.len() == t.n as int);
            assert(t.g@.len() == t.n as int);
        }
        let a = t.a[i];
        let g = t.g[i];
        if a > 1 {
            let mut j: usize = 0;
            while j < res.len() && res[j].g != g
                invariant
                    j <= res@.len(),
                    forall|r: int| #![trigger res@[r]] 0 <= r < j as int ==> res@[r].g != g,
                decreases res@.len() - j,
            {
                j += 1;
            }
            if j == res.len() {
                let ghost old = res@;
                res.push(OutRow { g: g });
                proof {
                    let x = OutRow { g: g };
                    assert(res@ == old.push(x));
                    assert(row_hit(t, i as int));
                    assert(out_key(x) == proj_key(t, i as int));
                    assert(out_row_ok(t, x));
                    assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(t, res@[r]) by {
                        if r < old.len() {
                            assert(res@[r] == old[r]);
                        }
                    };
                    assert forall|p: int, q: int| #![trigger res@[p], res@[q]] 0 <= p < q < res@.len() implies out_key(res@[p]) != out_key(res@[q]) by {
                        if q < old.len() {
                            assert(res@[p] == old[p] && res@[q] == old[q]);
                        } else {
                            assert(res@[q] == x);
                            assert(res@[p] == old[p]);
                            assert(old[p].g != g);
                        }
                    };
                    assert forall|i0: int| #![trigger row_hit(t, i0)] 0 <= i0 < (i + 1) as int && row_hit(t, i0) implies exists|r: int|
                        #![trigger res@[r]] 0 <= r < res@.len() && out_key(res@[r]) == proj_key(t, i0) by {
                        if i0 == i as int {
                            assert(res@[old.len() as int] == x);
                        } else {
                            let r = choose|r: int| 0 <= r < old.len() && out_key(old[r]) == proj_key(t, i0);
                            assert(res@[r] == old[r]);
                        }
                    };
                }
            } else {
                proof {
                    assert(res@[j as int].g == g);
                    assert(row_hit(t, i as int));
                    assert(out_key(res@[j as int]) == proj_key(t, i as int));
                }
            }
        } else {
            proof {
                assert(!row_hit(t, i as int));
            }
        }
        i += 1;
    }
    res
