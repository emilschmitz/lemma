// Worked example (LEMMA_STRING_ENCODING=dict): GROUP BY a dictionary string key with COUNT(*) and SUM(decimal), no filter, dense arrays over codes:
//   SELECT uom, COUNT(*) AS c, SUM(value) AS s FROM num GROUP BY uom
// Found by a manual prover on the first check, extending dict_group_count_dense.rs with a second dense array (`sums: Vec<i128>`).
// REAL EDGAR (num 39,401,761 rows): 52.6 ms vs 255.0 ms for the all-core reference engine (4.85x), 1,000 ms for one thread (19.0x); 10 verified.
// One backward pass, one slot bumped per row (dictionary entries are distinct), no hashing and no branch; invariants per code:
// `counts[c] == count_c(t, i, dict[c])`, `sums[c] == sum_s(t, i, dict[c])`, `|sums[c]| <= (n - i) * cell_cap`; then one loop over codes emits an
// OutRow per nonzero slot (ghost `idx`, as in dict_group_count_dense.rs). The `sum_s` unfold is `assert forall kk ... by { reveal_with_fuel(sum_s, 2) }`.
// AGENT_HELPERS_START
proof fn lemma_count_pos(num: &Cols_num, i: int, k: Seq<char>)
    requires
        0 <= i,
    ensures
        count_c(num, i, k) > 0 <==> exists|j: int| #![trigger row_hit(num, j)] i <= j < num.n as int && row_hit(num, j) && key_at(num, j) == k,
    decreases num.n as int - i,
{
    if i < num.n as int {
        lemma_count_pos(num, i + 1, k);
        lemma_count_c_bound(num, i + 1, k);
        if row_hit(num, i) && key_at(num, i) == k {
            assert(i <= i && i < num.n as int && row_hit(num, i) && key_at(num, i) == k);
        } else if exists|j: int| #![trigger row_hit(num, j)] i <= j < num.n as int && row_hit(num, j) && key_at(num, j) == k {
            let j = choose|j: int| #![trigger row_hit(num, j)] i <= j < num.n as int && row_hit(num, j) && key_at(num, j) == k;
            assert(j != i);
            assert(i + 1 <= j < num.n as int && row_hit(num, j) && key_at(num, j) == k);
        }
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let m: usize = num.uom__dict.len();
    let mut counts: Vec<u64> = Vec::new();
    let mut sums: Vec<i128> = Vec::new();
    let mut z: usize = 0;
    while z < m
        invariant
            z <= m,
            m == num.uom__dict@.len(),
            counts@.len() == z as int,
            sums@.len() == z as int,
            forall|c: int| 0 <= c < z as int ==> counts@[c] == 0 && sums@[c] == 0,
        decreases m - z,
    {
        counts.push(0);
        sums.push(0);
        z += 1;
    }
    let mut i: usize = num.n;
    while i > 0
        invariant
            i <= num.n,
            valid_cols_num(num),
            m == num.uom__dict@.len(),
            counts@.len() == m as int,
            sums@.len() == m as int,
            forall|c: int| #![trigger counts@[c]] 0 <= c < m as int ==> counts@[c] as int == count_c(num, i as int, num.uom__dict@[c]@),
            forall|c: int| #![trigger sums@[c]] 0 <= c < m as int ==> sums@[c] as int == sum_s(num, i as int, num.uom__dict@[c]@)
                && -((num.n - i) as int) * 46116860184273879039999int <= sums@[c] as int
                && sums@[c] as int <= ((num.n - i) as int) * 46116860184273879039999int,
        decreases i,
    {
        i -= 1;
        let v = num.value[i];
        let code = num.uom[i] as usize;
        proof {
            assert(num.value@.len() == num.n as int);
            assert(num.uom@.len() == num.n as int);
            assert(code < m);
            assert(num.value@[i as int] as int >= -46116860184273879039999 && num.value@[i as int] as int <= 46116860184273879039999);
            lemma_count_c_bound(num, (i + 1) as int, num.uom__dict@[code as int]@);
            assert forall|kk: Seq<char>| #[trigger] sum_s(num, i as int, kk) == (if row_hit(num, i as int) && key_at(num, i as int) == kk { sum_s_val(num, i as int) } else { 0int }) + sum_s(num, i as int + 1, kk) by {
                reveal_with_fuel(sum_s, 2);
            };
            assert(row_hit(num, i as int));
            assert(sum_s_val(num, i as int) == v as int);
        }
        let before = counts[code];
        counts.set(code, before + 1);
        let sb = sums[code];
        sums.set(code, sb + v);
        proof {
            assert forall|c: int| #![trigger counts@[c]] 0 <= c < m as int implies
                counts@[c] as int == count_c(num, i as int, num.uom__dict@[c]@) by {
                if c == code as int {
                    assert(key_at(num, i as int) == num.uom__dict@[c]@);
                } else {
                    assert(num.uom__dict@[c]@ != num.uom__dict@[code as int]@) by {
                        if c < code as int { assert(num.uom__dict@[c]@ != num.uom__dict@[code as int]@); }
                        else { assert(num.uom__dict@[code as int]@ != num.uom__dict@[c]@); }
                    };
                    assert(key_at(num, i as int) != num.uom__dict@[c]@);
                }
            };
            assert forall|c: int| #![trigger sums@[c]] 0 <= c < m as int implies
                sums@[c] as int == sum_s(num, i as int, num.uom__dict@[c]@)
                && -((num.n - i) as int) * 46116860184273879039999int <= sums@[c] as int
                && sums@[c] as int <= ((num.n - i) as int) * 46116860184273879039999int by {
                if c == code as int {
                    assert(key_at(num, i as int) == num.uom__dict@[c]@);
                } else {
                    assert(num.uom__dict@[c]@ != num.uom__dict@[code as int]@) by {
                        if c < code as int { assert(num.uom__dict@[c]@ != num.uom__dict@[code as int]@); }
                        else { assert(num.uom__dict@[code as int]@ != num.uom__dict@[c]@); }
                    };
                    assert(key_at(num, i as int) != num.uom__dict@[c]@);
                }
            };
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut idx: Seq<int> = Seq::empty();
    let mut c: usize = 0;
    while c < m
        invariant
            c <= m,
            valid_cols_num(num),
            m == num.uom__dict@.len(),
            counts@.len() == m as int,
            sums@.len() == m as int,
            forall|q: int| #![trigger counts@[q]] 0 <= q < m as int ==> counts@[q] as int == count_c(num, 0, num.uom__dict@[q]@),
            forall|q: int| #![trigger sums@[q]] 0 <= q < m as int ==> sums@[q] as int == sum_s(num, 0, num.uom__dict@[q]@),
            idx.len() == res@.len(),
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> 0 <= idx[r] < c as int,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> counts@[idx[r]] > 0,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].uom@ == num.uom__dict@[idx[r]]@,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].c == counts@[idx[r]] && res@[r].s == sums@[idx[r]],
            forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() ==> idx[r] < idx[r2],
            forall|q: int| #![trigger counts@[q]] 0 <= q < c as int && counts@[q] > 0 ==> exists|r: int| 0 <= r < idx.len() && idx[r] == q,
        decreases m - c,
    {
        let cnt = counts[c];
        if cnt > 0 {
            let ghost old = res@;
            let ghost old_idx = idx;
            let sv = sums[c];
            res.push(OutRow { uom: num.uom__dict[c].clone(), c: cnt, s: sv });
            proof {
                let x = res@[old.len() as int];
                assert(res@ == old.push(x));
                assert(x.uom@ == num.uom__dict@[c as int]@ && x.c == cnt && counts@[c as int] == cnt && x.s == sv);
                idx = old_idx.push(c as int);
                assert(idx.len() == res@.len());
                assert forall|r: int| 0 <= r < idx.len() implies idx[r] == (if r < old.len() as int { old_idx[r] } else { c as int }) by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies 0 <= idx[r] < (c + 1) as int by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies counts@[idx[r]] > 0 by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].uom@ == num.uom__dict@[idx[r]]@ by {
                    if r < old.len() as int { assert(res@[r] == old[r]); }
                };
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].c == counts@[idx[r]] && res@[r].s == sums@[idx[r]] by {
                    if r < old.len() as int { assert(res@[r] == old[r]); }
                };
                assert forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() implies idx[r] < idx[r2] by {};
                assert forall|q: int| #![trigger counts@[q]] 0 <= q < (c + 1) as int && counts@[q] > 0 implies exists|r: int| 0 <= r < idx.len() && idx[r] == q by {
                    if q == c as int { assert(idx[old.len() as int] == q); }
                    else {
                        let r = choose|r: int| 0 <= r < old_idx.len() && old_idx[r] == q;
                        assert(idx[r] == q);
                    }
                };
            }
        }
        c += 1;
    }
    proof {
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(num, res@[r]) by {
            let q = idx[r];
            assert(counts@[q] > 0);
            assert(counts@[q] as int == count_c(num, 0, num.uom__dict@[q]@));
            lemma_count_pos(num, 0, num.uom__dict@[q]@);
            let j = choose|j: int| 0 <= j < num.n as int && row_hit(num, j) && key_at(num, j) == num.uom__dict@[q]@;
            assert(row_hit(num, j) && key_at(num, j) == res@[r].uom@);
            assert((res@[r].c as int) == count_c(num, 0, res@[r].uom@));
            assert((res@[r].s as int) == sum_s(num, 0, res@[r].uom@));
        };
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies res@[a].uom@ != res@[b].uom@ by {
            assert(idx[a] < idx[b]);
            assert(idx[b] < m as int);
            assert(num.uom__dict@[idx[a]]@ != num.uom__dict@[idx[b]]@);
        };
        assert forall|i0: int| #![trigger row_hit(num, i0)] row_hit(num, i0) && (true) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(num, i0) == res@[r].uom@ by {
            let code = num.uom@[i0] as int;
            assert(key_at(num, i0) == num.uom__dict@[code]@);
            lemma_count_pos(num, 0, num.uom__dict@[code]@);
            assert(counts@[code] as int == count_c(num, 0, num.uom__dict@[code]@));
            assert(counts@[code] > 0);
            let r = choose|r: int| 0 <= r < idx.len() && idx[r] == code;
            assert(res@[r].uom@ == num.uom__dict@[code]@);
        };
    }
    res
// AGENT_EDIT_END
