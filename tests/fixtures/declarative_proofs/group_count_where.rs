    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut ks: Seq<int> = Seq::empty();
    let ghost mut wit: Seq<int> = Seq::empty();
    let ghost mut pos: Map<int, int> = Map::empty();
    // Pass 1: collect the distinct keys of the rows that pass the filter.
    let mut i: usize = 0;
    while i < pre.n
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            ks.len() == res@.len(),
            wit.len() == res@.len(),
            forall|r: int|
                #![trigger ks[r]] #![trigger res@[r]]
                0 <= r < res@.len() ==> res@[r].report as int == ks[r] && res@[r].cnt == 0,
            forall|r: int|
                #![trigger ks[r]]
                0 <= r < ks.len() ==> pos.contains_key(ks[r]) && pos[ks[r]] == r,
            forall|r: int|
                #![trigger wit[r]] #![trigger ks[r]]
                0 <= r < ks.len() ==> row_hit(pre, wit[r]) && 0 <= wit[r] < i as int && key_at(pre, wit[r]) == ks[r],
            forall|i0: int|
                #![trigger row_hit(pre, i0)]
                0 <= i0 < i as int && row_hit(pre, i0) ==> exists|r: int|
                    #![trigger ks[r]]
                    0 <= r < ks.len() && key_at(pre, i0) == ks[r],
        decreases pre.n - i,
    {
        let ghost old_res = res@;
        let ghost old_ks = ks;
        let ghost old_wit = wit;
        let ghost old_pos = pos;
        let line = pre.line[i];
        let k = pre.report[i];
        proof {
            assert(pre.line@.len() == pre.n as int);
            assert(pre.report@.len() == pre.n as int);
            assert(key_at(pre, i as int) == k as int);
            assert(row_hit(pre, i as int) <==> ((line as int) > 5));
        }
        if line > 5 {
            let mut j: usize = 0;
            while j < res.len() && res[j].report != k
                invariant
                    j <= res@.len(),
                    res@ == old_res,
                    forall|r: int| #![trigger res@[r]] 0 <= r < j as int ==> res@[r].report != k,
                decreases res@.len() - j,
            {
                j += 1;
            }
            if j == res.len() {
                res.push(OutRow { report: k, cnt: 0 });
                proof {
                    let n_old = old_res.len() as int;
                    ks = old_ks.push(k as int);
                    wit = old_wit.push(i as int);
                    assert(res@ == old_res.push(OutRow { report: k, cnt: 0 }));
                    assert forall|r: int| 0 <= r < n_old implies old_ks[r] != k as int by {
                        assert(old_res[r].report != k);
                    };
                    pos = old_pos.insert(k as int, n_old);
                    assert forall|r: int| #![trigger ks[r]] 0 <= r < ks.len() implies pos.contains_key(ks[r]) && pos[ks[r]] == r by {
                        if r < n_old {
                            assert(ks[r] == old_ks[r]);
                        }
                    };
                    assert forall|i0: int| #![trigger row_hit(pre, i0)] 0 <= i0 < (i + 1) as int && row_hit(pre, i0) implies exists|r: int| #![trigger ks[r]] 0 <= r < ks.len() && key_at(pre, i0) == ks[r] by {
                        if i0 == i as int {
                            assert(key_at(pre, i0) == ks[n_old]);
                        } else {
                            let r = choose|r: int| 0 <= r < old_ks.len() && key_at(pre, i0) == old_ks[r];
                            assert(ks[r] == old_ks[r]);
                        }
                    };
                }
            } else {
                proof {
                    assert(res@[j as int].report == k);
                    assert(ks[j as int] == k as int);
                    assert forall|i0: int| #![trigger row_hit(pre, i0)] 0 <= i0 < (i + 1) as int && row_hit(pre, i0) implies exists|r: int| #![trigger ks[r]] 0 <= r < ks.len() && key_at(pre, i0) == ks[r] by {
                        if i0 == i as int {
                            assert(key_at(pre, i0) == ks[j as int]);
                        }
                    };
                }
            }
        } else {
            proof {
                assert(!row_hit(pre, i as int));
                assert forall|i0: int| #![trigger row_hit(pre, i0)] 0 <= i0 < (i + 1) as int && row_hit(pre, i0) implies exists|r: int| #![trigger ks[r]] 0 <= r < ks.len() && key_at(pre, i0) == ks[r] by {
                    assert(i0 != i as int);
                };
            }
        }
        i += 1;
    }
    // Pass 2: count the rows of each key from the end, so `count_cnt` unfolds one row at a time.
    let mut i: usize = pre.n;
    while i > 0
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            ks.len() == res@.len(),
            forall|r: int|
                #![trigger ks[r]]
                0 <= r < ks.len() ==> pos.contains_key(ks[r]) && pos[ks[r]] == r,
            forall|r: int|
                #![trigger ks[r]] #![trigger res@[r]]
                0 <= r < res@.len() ==> res@[r].report as int == ks[r]
                    && res@[r].cnt as int == count_cnt(pre, i as int, ks[r]),
            wit.len() == ks.len(),
            forall|r: int|
                #![trigger wit[r]] #![trigger ks[r]]
                0 <= r < ks.len() ==> row_hit(pre, wit[r]) && key_at(pre, wit[r]) == ks[r],
            forall|i0: int|
                #![trigger row_hit(pre, i0)]
                0 <= i0 < pre.n as int && row_hit(pre, i0) ==> exists|r: int|
                    #![trigger ks[r]]
                    0 <= r < ks.len() && key_at(pre, i0) == ks[r],
        decreases i,
    {
        let ghost old_res = res@;
        i -= 1;
        let line = pre.line[i];
        let k = pre.report[i];
        proof {
            assert(pre.line@.len() == pre.n as int);
            assert(pre.report@.len() == pre.n as int);
            assert(key_at(pre, i as int) == k as int);
            assert(row_hit(pre, i as int) <==> ((line as int) > 5));
        }
        if line > 5 {
            let mut j: usize = 0;
            while j < res.len() && res[j].report != k
                invariant
                    j <= res@.len(),
                    res@ == old_res,
                    forall|r: int| #![trigger res@[r]] 0 <= r < j as int ==> res@[r].report != k,
                decreases res@.len() - j,
            {
                j += 1;
            }
            proof {
                assert(row_hit(pre, i as int));
                let r0 = choose|r: int| 0 <= r < ks.len() && key_at(pre, i as int) == ks[r];
                assert(res@[r0].report == k);
                assert(j < res@.len());
            }
            let c = res[j].cnt;
            proof {
                lemma_count_cnt_bound(pre, i as int + 1, k as int);
                assert(c as int == count_cnt(pre, i as int + 1, k as int));
                assert(c as int <= pre.n as int);
                assert(pre.n as int <= ROW_CAP_pre as int);
            }
            res.set(j, OutRow { report: k, cnt: c + 1 });
            proof {
                assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies res@[r].report as int == ks[r] && res@[r].cnt as int == count_cnt(pre, i as int, ks[r]) by {
                    if r == j as int {
                        assert(ks[r] == k as int);
                    } else {
                        assert(res@[r] == old_res[r]);
                        assert(pos[ks[r]] == r);
                        assert(pos[ks[j as int]] == j as int);
                    }
                };
            }
        } else {
            proof {
                assert(!row_hit(pre, i as int));
                assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies res@[r].report as int == ks[r] && res@[r].cnt as int == count_cnt(pre, i as int, ks[r]) by {

                };
            }
        }
    }
    proof {
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(pre, res@[r]) by {
            let i0 = wit[r];
            assert(res@[r].report as int == ks[r]);
            assert(row_hit(pre, i0) && key_at(pre, i0) == res@[r].report as int);
            assert(res@[r].cnt as int == count_cnt(pre, 0, res@[r].report as int));
        };
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies res@[a].report != res@[b].report by {
            assert(res@[a].report as int == ks[a]);
            assert(res@[b].report as int == ks[b]);
            assert(pos[ks[a]] == a);
            assert(pos[ks[b]] == b);
        };
        assert forall|i0: int| #![trigger row_hit(pre, i0)] row_hit(pre, i0) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(pre, i0) == res@[r].report as int by {
            let r = choose|r: int| 0 <= r < ks.len() && key_at(pre, i0) == ks[r];
            assert(res@[r].report as int == ks[r]);
        };
    }
    res
