// Worked example for LEMMA_STRING_ENCODING=dict: GROUP BY a dictionary-encoded string key as a DENSE ARRAY OVER CODES.
//   SELECT s, COUNT(*) AS c FROM t WHERE a > 1 GROUP BY s
// `t.s` holds codes and `t.s__dict` the distinct strings (`valid_cols`: every code is below the dictionary length, entries
// pairwise distinct), so a group is a code: `counts[code]` is its count and no hashing is needed.
// Pass 1 walks the rows from last to first, like the spec's suffix fold `count_c(t, i, k)`:
//   invariant  counts[c] == count_c(t, i, dict[c])  for every code c.
// Distinct dictionary entries make `key_at(t, i) == dict[c]` hold for exactly one c (the row's own code), so a row bumps one slot.
// Pass 2 emits one OutRow per slot with a nonzero count, in code order. A ghost `idx` records which slot each output row came from:
// the rows are real groups (`lemma_count_pos` turns count > 0 into a witness row), their keys differ (distinct entries, distinct slots),
// and every passing row's key is covered (its slot has count >= 1).
// AGENT_HELPERS_START
proof fn lemma_count_pos(t: &Cols_t, i: int, k: Seq<char>)
    requires
        0 <= i,
    ensures
        count_c(t, i, k) > 0 <==> exists|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j) && key_at(t, j) == k,
    decreases t.n as int - i,
{
    if i < t.n as int {
        lemma_count_pos(t, i + 1, k);
        lemma_count_c_bound(t, i + 1, k);
        if row_hit(t, i) && key_at(t, i) == k {
            assert(i <= i && i < t.n as int && row_hit(t, i) && key_at(t, i) == k);
        } else if exists|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j) && key_at(t, j) == k {
            let j = choose|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j) && key_at(t, j) == k;
            assert(j != i);
            assert(i + 1 <= j < t.n as int && row_hit(t, j) && key_at(t, j) == k);
        }
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let m: usize = t.s__dict.len();
    let mut counts: Vec<u64> = Vec::new();
    let mut z: usize = 0;
    while z < m
        invariant
            z <= m,
            m == t.s__dict@.len(),
            counts@.len() == z as int,
            forall|c: int| 0 <= c < z as int ==> counts@[c] == 0,
        decreases m - z,
    {
        counts.push(0);
        z += 1;
    }
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            valid_cols_t(t),
            m == t.s__dict@.len(),
            counts@.len() == m as int,
            forall|c: int| #![trigger counts@[c]] 0 <= c < m as int ==> counts@[c] as int == count_c(t, i as int, t.s__dict@[c]@),
        decreases i,
    {
        i -= 1;
        let a = t.a[i];
        let code = t.s[i] as usize;
        proof {
            assert(t.a@.len() == t.n as int);
            assert(t.s@.len() == t.n as int);
            assert(code < m);
            lemma_count_c_bound(t, (i + 1) as int, t.s__dict@[code as int]@);
        }
        if a > 1 {
            let ghost old = counts@;
            let before = counts[code];
            counts.set(code, before + 1);
            proof {
                assert(row_hit(t, i as int));
                assert forall|c: int| #![trigger counts@[c]] 0 <= c < m as int implies
                    counts@[c] as int == count_c(t, i as int, t.s__dict@[c]@) by {
                    if c == code as int {
                        assert(key_at(t, i as int) == t.s__dict@[c]@);
                    } else {
                        assert(t.s__dict@[c]@ != t.s__dict@[code as int]@) by {
                            if c < code as int { assert(t.s__dict@[c]@ != t.s__dict@[code as int]@); }
                            else { assert(t.s__dict@[code as int]@ != t.s__dict@[c]@); }
                        };
                        assert(key_at(t, i as int) != t.s__dict@[c]@);
                    }
                };
            }
        } else {
            proof {
                assert(!row_hit(t, i as int));
                assert forall|c: int| #![trigger counts@[c]] 0 <= c < m as int implies
                    counts@[c] as int == count_c(t, i as int, t.s__dict@[c]@) by {};
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut idx: Seq<int> = Seq::empty();
    let mut c: usize = 0;
    while c < m
        invariant
            c <= m,
            valid_cols_t(t),
            m == t.s__dict@.len(),
            counts@.len() == m as int,
            forall|q: int| #![trigger counts@[q]] 0 <= q < m as int ==> counts@[q] as int == count_c(t, 0, t.s__dict@[q]@),
            idx.len() == res@.len(),
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> 0 <= idx[r] < c as int,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> counts@[idx[r]] > 0,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].s@ == t.s__dict@[idx[r]]@,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].c == counts@[idx[r]],
            forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() ==> idx[r] < idx[r2],
            forall|q: int| #![trigger counts@[q]] 0 <= q < c as int && counts@[q] > 0 ==> exists|r: int| 0 <= r < idx.len() && idx[r] == q,
        decreases m - c,
    {
        let cnt = counts[c];
        if cnt > 0 {
            let ghost old = res@;
            let ghost old_idx = idx;
            res.push(OutRow { s: t.s__dict[c].clone(), c: cnt });
            proof {
                let x = res@[old.len() as int];
                assert(res@ == old.push(x));
                assert(x.s@ == t.s__dict@[c as int]@ && x.c == cnt && counts@[c as int] == cnt);
                idx = old_idx.push(c as int);
                assert(idx.len() == res@.len());
                assert forall|r: int| 0 <= r < idx.len() implies idx[r] == (if r < old.len() as int { old_idx[r] } else { c as int }) by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies 0 <= idx[r] < (c + 1) as int by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies counts@[idx[r]] > 0 by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].s@ == t.s__dict@[idx[r]]@ by {
                    if r < old.len() as int { assert(res@[r] == old[r]); }
                };
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].c == counts@[idx[r]] by {
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
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(t, res@[r]) by {
            let q = idx[r];
            assert(counts@[q] > 0);
            assert(counts@[q] as int == count_c(t, 0, t.s__dict@[q]@));
            lemma_count_pos(t, 0, t.s__dict@[q]@);
            let j = choose|j: int| 0 <= j < t.n as int && row_hit(t, j) && key_at(t, j) == t.s__dict@[q]@;
            assert(row_hit(t, j) && key_at(t, j) == res@[r].s@);
            assert((res@[r].c as int) == count_c(t, 0, res@[r].s@));
        };
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies res@[a].s@ != res@[b].s@ by {
            assert(idx[a] < idx[b]);
            assert(idx[b] < m as int);
            assert(t.s__dict@[idx[a]]@ != t.s__dict@[idx[b]]@);
        };
        assert forall|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && (true) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(t, i0) == res@[r].s@ by {
            let code = t.s@[i0] as int;
            assert(key_at(t, i0) == t.s__dict@[code]@);
            lemma_count_pos(t, 0, t.s__dict@[code]@);
            assert(counts@[code] as int == count_c(t, 0, t.s__dict@[code]@));
            assert(counts@[code] > 0);
            let r = choose|r: int| 0 <= r < idx.len() && idx[r] == code;
            assert(res@[r].s@ == t.s__dict@[code]@);
        };
    }
    res
// AGENT_EDIT_END
