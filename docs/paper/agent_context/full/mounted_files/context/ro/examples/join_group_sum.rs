    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut ks: Seq<int> = Seq::empty();
    let ghost mut wit0: Seq<int> = Seq::empty();
    let ghost mut wit1: Seq<int> = Seq::empty();
    let ghost mut pos: Map<int, int> = Map::empty();
    // Pass 1: collect the distinct keys of the joined rows.
    let mut i0: usize = 0;
    while i0 < n.n
        invariant
            i0 <= n.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            ks.len() == res@.len(),
            wit0.len() == res@.len(),
            wit1.len() == res@.len(),
            forall|r: int|
                #![trigger ks[r]] #![trigger res@[r]]
                0 <= r < res@.len() ==> res@[r].fy as int == ks[r] && res@[r].total == 0,
            forall|r: int|
                #![trigger ks[r]]
                0 <= r < ks.len() ==> pos.contains_key(ks[r]) && pos[ks[r]] == r,
            forall|r: int|
                #![trigger ks[r]] #![trigger wit0[r]]
                0 <= r < ks.len() ==> row_hit(n, s, wit0[r], wit1[r]) && key_at(n, s, wit0[r], wit1[r]) == ks[r],
            forall|a: int, b: int|
                #![trigger row_hit(n, s, a, b)]
                0 <= a < i0 as int && row_hit(n, s, a, b) ==> exists|r: int|
                    #![trigger ks[r]]
                    0 <= r < ks.len() && key_at(n, s, a, b) == ks[r],
        decreases n.n - i0,
    {
        let mut i1: usize = 0;
        while i1 < s.n
            invariant
                i0 < n.n,
                i1 <= s.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            ks.len() == res@.len(),
            wit0.len() == res@.len(),
            wit1.len() == res@.len(),
            forall|r: int|
                #![trigger ks[r]] #![trigger res@[r]]
                0 <= r < res@.len() ==> res@[r].fy as int == ks[r] && res@[r].total == 0,
            forall|r: int|
                #![trigger ks[r]]
                0 <= r < ks.len() ==> pos.contains_key(ks[r]) && pos[ks[r]] == r,
            forall|r: int|
                #![trigger ks[r]] #![trigger wit0[r]]
                0 <= r < ks.len() ==> row_hit(n, s, wit0[r], wit1[r]) && key_at(n, s, wit0[r], wit1[r]) == ks[r],
            forall|a: int, b: int|
                #![trigger row_hit(n, s, a, b)]
                0 <= a <= i0 as int && 0 <= b && (a < i0 as int || b < i1 as int) && row_hit(n, s, a, b) ==> exists|r: int|
                    #![trigger ks[r]]
                    0 <= r < ks.len() && key_at(n, s, a, b) == ks[r],
            decreases s.n - i1,
        {
            let ghost old_res = res@;
            let ghost old_ks = ks;
            let ghost old_wit0 = wit0;
            let ghost old_wit1 = wit1;
            let ghost old_pos = pos;
            proof {
                assert(n.adsh@.len() == n.n as int);
                assert(s.adsh@.len() == s.n as int);
                assert(s.fy@.len() == s.n as int);
            }
            let eq = n.adsh[i0] == s.adsh[i1];
            proof {
                assert(row_hit(n, s, i0 as int, i1 as int) <==> eq);
            }
            if eq {
                let k = s.fy[i1];
                proof {
                    assert(key_at(n, s, i0 as int, i1 as int) == k as int);
                }
                let mut j: usize = 0;
                while j < res.len() && res[j].fy != k
                    invariant
                        j <= res@.len(),
                        res@ == old_res,
                        forall|r: int| #![trigger res@[r]] 0 <= r < j as int ==> res@[r].fy != k,
                    decreases res@.len() - j,
                {
                    j += 1;
                }
                let ghost n_old = old_res.len() as int;
                if j == res.len() {
                    res.push(OutRow { fy: k, total: 0 });
                    proof {
                                                ks = old_ks.push(k as int);
                        wit0 = old_wit0.push(i0 as int);
                        wit1 = old_wit1.push(i1 as int);
                        assert(res@ == old_res.push(OutRow { fy: k, total: 0 }));
                        assert forall|r: int| 0 <= r < n_old implies old_ks[r] != k as int by {
                            assert(old_res[r].fy != k);
                        };
                        pos = old_pos.insert(k as int, n_old);
                        assert forall|r: int| #![trigger ks[r]] 0 <= r < ks.len() implies pos.contains_key(ks[r]) && pos[ks[r]] == r by {
                            if r < n_old {
                                assert(ks[r] == old_ks[r]);
                            }
                        };
                        assert forall|r: int| #![trigger ks[r]] 0 <= r < ks.len() implies row_hit(n, s, wit0[r], wit1[r]) && key_at(n, s, wit0[r], wit1[r]) == ks[r] by {
                            if r < n_old {
                                assert(wit0[r] == old_wit0[r]);
                                assert(wit1[r] == old_wit1[r]);
                            }
                        };
                    }
                proof {
                    assert forall|r: int| 0 <= r < old_ks.len() implies ks[r] == old_ks[r] by {};
                    assert forall|a: int, b: int| #![trigger row_hit(n, s, a, b)] 0 <= a <= i0 as int && 0 <= b && (a < i0 as int || b < (i1 + 1) as int) && row_hit(n, s, a, b) implies exists|r: int| #![trigger ks[r]] 0 <= r < ks.len() && key_at(n, s, a, b) == ks[r] by {
                        if a == i0 as int && b == i1 as int {
                            assert(key_at(n, s, a, b) == ks[n_old]);
                        } else {
                            let r0 = choose|r: int| 0 <= r < old_ks.len() && key_at(n, s, a, b) == old_ks[r];
                            assert(ks[r0] == old_ks[r0]);
                        }
                    };
                }
                } else {
                    proof {
                        assert(res@[j as int].fy == k);
                        assert(ks[j as int] == k as int);
                    }
                proof {
                    assert forall|r: int| 0 <= r < old_ks.len() implies ks[r] == old_ks[r] by {};
                    assert forall|a: int, b: int| #![trigger row_hit(n, s, a, b)] 0 <= a <= i0 as int && 0 <= b && (a < i0 as int || b < (i1 + 1) as int) && row_hit(n, s, a, b) implies exists|r: int| #![trigger ks[r]] 0 <= r < ks.len() && key_at(n, s, a, b) == ks[r] by {
                        if a == i0 as int && b == i1 as int {
                            assert(key_at(n, s, a, b) == ks[j as int]);
                        } else {
                            let r0 = choose|r: int| 0 <= r < old_ks.len() && key_at(n, s, a, b) == old_ks[r];
                            assert(ks[r0] == old_ks[r0]);
                        }
                    };
                }
                }
            } else {
                proof {
                    assert forall|r: int| 0 <= r < old_ks.len() implies ks[r] == old_ks[r] by {};
                    assert forall|a: int, b: int| #![trigger row_hit(n, s, a, b)] 0 <= a <= i0 as int && 0 <= b && (a < i0 as int || b < (i1 + 1) as int) && row_hit(n, s, a, b) implies exists|r: int| #![trigger ks[r]] 0 <= r < ks.len() && key_at(n, s, a, b) == ks[r] by {
                        if a == i0 as int && b == i1 as int {
                            assert(!row_hit(n, s, i0 as int, i1 as int));
                        } else {
                            let r0 = choose|r: int| 0 <= r < old_ks.len() && key_at(n, s, a, b) == old_ks[r];
                            assert(ks[r0] == old_ks[r0]);
                        }
                    };
                }
            }
            i1 += 1;
        }
        i0 += 1;
    }
    // Pass 2: sum the joined rows of each key from the end, so `sum_total` unfolds one row at a time.
    let mut i0: usize = n.n;
    let ghost mut base: int = 0;
    while i0 > 0
        invariant
            i0 <= n.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            ks.len() == res@.len(),
            wit0.len() == ks.len(),
            wit1.len() == ks.len(),
            forall|r: int|
                #![trigger ks[r]]
                0 <= r < ks.len() ==> pos.contains_key(ks[r]) && pos[ks[r]] == r,
            forall|r: int|
                #![trigger ks[r]] #![trigger wit0[r]]
                0 <= r < ks.len() ==> row_hit(n, s, wit0[r], wit1[r]) && key_at(n, s, wit0[r], wit1[r]) == ks[r],
            forall|a: int, b: int|
                #![trigger row_hit(n, s, a, b)]
                row_hit(n, s, a, b) ==> exists|r: int|
                    #![trigger ks[r]]
                    0 <= r < ks.len() && key_at(n, s, a, b) == ks[r],
            base == (n.n as int - i0 as int) * (s.n as int),
            forall|r: int|
                #![trigger ks[r]] #![trigger res@[r]]
                0 <= r < res@.len() ==> res@[r].fy as int == ks[r]
                    && res@[r].total as int == sum_total(n, s, i0 as int, ks[r])
                    && -base * 0x8000_0000_0000_0000int <= res@[r].total as int
                    && res@[r].total as int <= base * 0x8000_0000_0000_0000int,
        decreases i0,
    {
        i0 -= 1;
        let ghost mut m: int = base;
        let ghost base_row = base;
        proof {
            assert(base_row == (n.n as int - i0 as int - 1) * (s.n as int));
            assert(base_row + s.n as int == (n.n as int - i0 as int) * (s.n as int)) by (nonlinear_arith)
                requires base_row == (n.n as int - i0 as int - 1) * (s.n as int);
            assert((n.n as int - i0 as int) * (s.n as int) <= (n.n as int) * (s.n as int)) by (nonlinear_arith)
                requires 0 <= i0 as int;
            assert((n.n as int) * (s.n as int) <= (ROW_CAP_num as int) * (ROW_CAP_sub as int)) by (nonlinear_arith)
                requires 0 <= n.n as int <= ROW_CAP_num as int, 0 <= s.n as int <= ROW_CAP_sub as int;
            assert(n.qtrs@.len() == n.n as int);
        }
        let mut i1: usize = s.n;
        while i1 > 0
            invariant
                i0 < n.n,
                i1 <= s.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            ks.len() == res@.len(),
            wit0.len() == ks.len(),
            wit1.len() == ks.len(),
            forall|r: int|
                #![trigger ks[r]]
                0 <= r < ks.len() ==> pos.contains_key(ks[r]) && pos[ks[r]] == r,
            forall|r: int|
                #![trigger ks[r]] #![trigger wit0[r]]
                0 <= r < ks.len() ==> row_hit(n, s, wit0[r], wit1[r]) && key_at(n, s, wit0[r], wit1[r]) == ks[r],
            forall|a: int, b: int|
                #![trigger row_hit(n, s, a, b)]
                row_hit(n, s, a, b) ==> exists|r: int|
                    #![trigger ks[r]]
                    0 <= r < ks.len() && key_at(n, s, a, b) == ks[r],
                base_row == (n.n as int - i0 as int - 1) * (s.n as int),
                base_row + s.n as int <= (ROW_CAP_num as int) * (ROW_CAP_sub as int),
                m == base_row + (s.n as int - i1 as int),
                forall|r: int|
                    #![trigger ks[r]] #![trigger res@[r]]
                    0 <= r < res@.len() ==> res@[r].fy as int == ks[r]
                        && res@[r].total as int == sum_total(n, s, i0 as int + 1, ks[r]) + sum_total_d1(n, s, i0 as int, i1 as int, ks[r])
                        && -m * 0x8000_0000_0000_0000int <= res@[r].total as int
                        && res@[r].total as int <= m * 0x8000_0000_0000_0000int,
            decreases i1,
        {
            let ghost old_res = res@;
            let ghost m_old = m;
            i1 -= 1;
            proof {
                m = m + 1;
                assert(n.adsh@.len() == n.n as int);
                assert(s.adsh@.len() == s.n as int);
                assert(s.fy@.len() == s.n as int);
                assert forall|kk: int| #[trigger] sum_total_d1(n, s, i0 as int, i1 as int, kk) == (if row_hit(n, s, i0 as int, i1 as int) && key_at(n, s, i0 as int, i1 as int) == kk { sum_total_val(n, s, i0 as int, i1 as int) } else { 0int }) + sum_total_d1(n, s, i0 as int, i1 as int + 1, kk) by {
                    reveal_with_fuel(sum_total_d1, 2);
                };
            }
            let eq = n.adsh[i0] == s.adsh[i1];
            proof {
                assert(row_hit(n, s, i0 as int, i1 as int) <==> eq);
            }
            if eq {
                let k = s.fy[i1];
                let mut j: usize = 0;
                while j < res.len() && res[j].fy != k
                    invariant
                        j <= res@.len(),
                        res@ == old_res,
                        forall|r: int| #![trigger res@[r]] 0 <= r < j as int ==> res@[r].fy != k,
                    decreases res@.len() - j,
                {
                    j += 1;
                }
                proof {
                    assert(key_at(n, s, i0 as int, i1 as int) == k as int);
                    assert(row_hit(n, s, i0 as int, i1 as int));
                    let r0 = choose|r: int| 0 <= r < ks.len() && key_at(n, s, i0 as int, i1 as int) == ks[r];
                    assert(res@[r0].fy == k);
                    assert(j < res@.len());
                }
                let c = res[j].total;
                let cell = n.qtrs[i0] as i128;
                proof {
                    assert(sum_total_val(n, s, i0 as int, i1 as int) == n.qtrs@[i0 as int] as int);
                    assert(m_old < (ROW_CAP_num as int) * (ROW_CAP_sub as int));
                    assert(m_old * 0x8000_0000_0000_0000int <= (ROW_CAP_num as int) * (ROW_CAP_sub as int) * 0x8000_0000_0000_0000int);
                }
                res.set(j, OutRow { fy: k, total: c + cell });
                proof {
                    assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies res@[r].fy as int == ks[r]
                            && res@[r].total as int == sum_total(n, s, i0 as int + 1, ks[r]) + sum_total_d1(n, s, i0 as int, i1 as int, ks[r])
                            && -m * 0x8000_0000_0000_0000int <= res@[r].total as int
                            && res@[r].total as int <= m * 0x8000_0000_0000_0000int by {
                        if r != j as int {
                            assert(res@[r] == old_res[r]);
                            assert(pos[ks[r]] == r);
                            assert(pos[ks[j as int]] == j as int);
                        } else {
                            assert(old_res[j as int].fy as int == ks[j as int]);
                        }
                    };
                }
            } else {
                proof {
                    assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies res@[r].fy as int == ks[r]
                            && res@[r].total as int == sum_total(n, s, i0 as int + 1, ks[r]) + sum_total_d1(n, s, i0 as int, i1 as int, ks[r])
                            && -m * 0x8000_0000_0000_0000int <= res@[r].total as int
                            && res@[r].total as int <= m * 0x8000_0000_0000_0000int by {
                    };
                }
            }
        }
        proof {
            base = m;
            assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies res@[r].total as int == sum_total(n, s, i0 as int, ks[r]) by {
                reveal_with_fuel(sum_total, 2);
            };
        }
    }
    proof {
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(n, s, res@[r]) by {
            let i0 = wit0[r];
            let i1 = wit1[r];
            assert(res@[r].fy as int == ks[r]);
            assert(row_hit(n, s, i0, i1) && key_at(n, s, i0, i1) == res@[r].fy as int);
            assert(res@[r].total as int == sum_total(n, s, 0, res@[r].fy as int));
        };
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies res@[a].fy != res@[b].fy by {
            assert(res@[a].fy as int == ks[a]);
            assert(res@[b].fy as int == ks[b]);
            assert(pos[ks[a]] == a);
            assert(pos[ks[b]] == b);
        };
        assert forall|a: int, b: int| #![trigger row_hit(n, s, a, b)] row_hit(n, s, a, b) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(n, s, a, b) == res@[r].fy as int by {
            let r = choose|r: int| 0 <= r < ks.len() && key_at(n, s, a, b) == ks[r];
            assert(res@[r].fy as int == ks[r]);
        };
    }
    res
