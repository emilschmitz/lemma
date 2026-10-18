// Stateful contract (lemma.toml `stateful`): a grouped COUNT/SUM answered from a precomputed per-group table.
// TPC-H SF1 catalog (tpch_sf1):
//   SELECT l_returnflag, COUNT(*) AS c, SUM(l_quantity) AS s FROM lineitem GROUP BY l_returnflag
// build: one backward pass over the rows bumps one dense slot per dictionary code (as dict_group_count_sum_dense.rs) and
// keeps only the dictionary and the two per-code arrays; the row columns are dropped. execute: one pass over the codes
// (at most 16) emits an OutRow per nonzero slot. The invariant states the per-code arrays as the spec folds over the
// snapshot `s.db().lineitem`, so `execute` never reads a row.
// AGENT_STATE_START
pub struct QAcc {
    pub dict: Vec<String>,
    pub counts: Vec<u64>,
    pub sums: Vec<i128>,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
pub open spec fn qstate_inv(s: &QState) -> bool {
    let li = s.db().lineitem;
    &&& s.acc.dict@ == li.l_returnflag__dict@
    &&& s.acc.counts@.len() == s.acc.dict@.len()
    &&& s.acc.sums@.len() == s.acc.dict@.len()
    &&& forall|c: int| #![trigger s.acc.counts@[c]] 0 <= c < s.acc.dict@.len() ==> s.acc.counts@[c] as int == count_c(&li, 0, li.l_returnflag__dict@[c]@)
    &&& forall|c: int| #![trigger s.acc.sums@[c]] 0 <= c < s.acc.dict@.len() ==> s.acc.sums@[c] as int == sum_s(&li, 0, li.l_returnflag__dict@[c]@)
}

proof fn lemma_count_pos(lineitem: &Cols_lineitem, i: int, k: Seq<char>)
    requires
        0 <= i,
    ensures
        count_c(lineitem, i, k) > 0 <==> exists|j: int| #![trigger row_hit(lineitem, j)] i <= j < lineitem.n as int && row_hit(lineitem, j) && key_at(lineitem, j) == k,
    decreases lineitem.n as int - i,
{
    if i < lineitem.n as int {
        lemma_count_pos(lineitem, i + 1, k);
        lemma_count_c_bound(lineitem, i + 1, k);
        if row_hit(lineitem, i) && key_at(lineitem, i) == k {
            assert(i <= i && i < lineitem.n as int && row_hit(lineitem, i) && key_at(lineitem, i) == k);
        } else if exists|j: int| #![trigger row_hit(lineitem, j)] i <= j < lineitem.n as int && row_hit(lineitem, j) && key_at(lineitem, j) == k {
            let j = choose|j: int| #![trigger row_hit(lineitem, j)] i <= j < lineitem.n as int && row_hit(lineitem, j) && key_at(lineitem, j) == k;
            assert(j != i);
            assert(i + 1 <= j < lineitem.n as int && row_hit(lineitem, j) && key_at(lineitem, j) == k);
        }
    }
}
// AGENT_HELPERS_END
// AGENT_BUILD_START
    let snap: Ghost<QDb> = Ghost(QDb { lineitem: lineitem });
    let m: usize = lineitem.l_returnflag__dict.len();
    let mut counts: Vec<u64> = Vec::new();
    let mut sums: Vec<i128> = Vec::new();
    let mut z: usize = 0;
    while z < m
        invariant
            z <= m,
            m == lineitem.l_returnflag__dict@.len(),
            counts@.len() == z as int,
            sums@.len() == z as int,
            forall|c: int| 0 <= c < z as int ==> counts@[c] == 0 && sums@[c] == 0,
        decreases m - z,
    {
        counts.push(0);
        sums.push(0);
        z += 1;
    }
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            valid_cols_lineitem(&lineitem),
            m == lineitem.l_returnflag__dict@.len(),
            counts@.len() == m as int,
            sums@.len() == m as int,
            forall|c: int| #![trigger counts@[c]] 0 <= c < m as int ==> counts@[c] as int == count_c(&lineitem, i as int, lineitem.l_returnflag__dict@[c]@),
            forall|c: int| #![trigger sums@[c]] 0 <= c < m as int ==> sums@[c] as int == sum_s(&lineitem, i as int, lineitem.l_returnflag__dict@[c]@)
                && -((lineitem.n - i) as int) * 8191int <= sums@[c] as int
                && sums@[c] as int <= ((lineitem.n - i) as int) * 8191int,
        decreases i,
    {
        i -= 1;
        let v = lineitem.l_quantity[i];
        let code = lineitem.l_returnflag[i] as usize;
        proof {
            assert(lineitem.l_quantity@.len() == lineitem.n as int);
            assert(lineitem.l_returnflag@.len() == lineitem.n as int);
            assert(code < m);
            assert(lineitem.l_quantity@[i as int] as int >= -8191 && lineitem.l_quantity@[i as int] as int <= 8191);
            lemma_count_c_bound(&lineitem, (i + 1) as int, lineitem.l_returnflag__dict@[code as int]@);
            assert forall|kk: Seq<char>| #[trigger] sum_s(&lineitem, i as int, kk) == (if row_hit(&lineitem, i as int) && key_at(&lineitem, i as int) == kk { sum_s_val(&lineitem, i as int) } else { 0int }) + sum_s(&lineitem, i as int + 1, kk) by {
                reveal_with_fuel(sum_s, 2);
            };
            assert(row_hit(&lineitem, i as int));
            assert(sum_s_val(&lineitem, i as int) == v as int);
        }
        let before = counts[code];
        counts.set(code, before + 1);
        let sb = sums[code];
        sums.set(code, sb + v as i128);
        proof {
            assert forall|c: int| #![trigger counts@[c]] 0 <= c < m as int implies
                counts@[c] as int == count_c(&lineitem, i as int, lineitem.l_returnflag__dict@[c]@) by {
                if c == code as int {
                    assert(key_at(&lineitem, i as int) == lineitem.l_returnflag__dict@[c]@);
                } else {
                    assert(lineitem.l_returnflag__dict@[c]@ != lineitem.l_returnflag__dict@[code as int]@) by {
                        if c < code as int { assert(lineitem.l_returnflag__dict@[c]@ != lineitem.l_returnflag__dict@[code as int]@); }
                        else { assert(lineitem.l_returnflag__dict@[code as int]@ != lineitem.l_returnflag__dict@[c]@); }
                    };
                    assert(key_at(&lineitem, i as int) != lineitem.l_returnflag__dict@[c]@);
                }
            };
            assert forall|c: int| #![trigger sums@[c]] 0 <= c < m as int implies
                sums@[c] as int == sum_s(&lineitem, i as int, lineitem.l_returnflag__dict@[c]@)
                && -((lineitem.n - i) as int) * 8191int <= sums@[c] as int
                && sums@[c] as int <= ((lineitem.n - i) as int) * 8191int by {
                if c == code as int {
                    assert(key_at(&lineitem, i as int) == lineitem.l_returnflag__dict@[c]@);
                } else {
                    assert(lineitem.l_returnflag__dict@[c]@ != lineitem.l_returnflag__dict@[code as int]@) by {
                        if c < code as int { assert(lineitem.l_returnflag__dict@[c]@ != lineitem.l_returnflag__dict@[code as int]@); }
                        else { assert(lineitem.l_returnflag__dict@[code as int]@ != lineitem.l_returnflag__dict@[c]@); }
                    };
                    assert(key_at(&lineitem, i as int) != lineitem.l_returnflag__dict@[c]@);
                }
            };
        }
    }
    let dict = lineitem.l_returnflag__dict;
    QState { snap, acc: QAcc { dict, counts, sums } }
// AGENT_BUILD_END
// AGENT_EDIT_START
    let ghost li = s.db().lineitem;
    let m: usize = s.acc.dict.len();
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut idx: Seq<int> = Seq::empty();
    let mut c: usize = 0;
    while c < m
        invariant
            c <= m,
            s.inv(),
            li == s.db().lineitem,
            m == s.acc.dict@.len(),
            idx.len() == res@.len(),
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> 0 <= idx[r] < c as int,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> s.acc.counts@[idx[r]] > 0,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].l_returnflag@ == s.acc.dict@[idx[r]]@,
            forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() ==> res@[r].c == s.acc.counts@[idx[r]] && res@[r].s == s.acc.sums@[idx[r]],
            forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() ==> idx[r] < idx[r2],
            forall|q: int| #![trigger s.acc.counts@[q]] 0 <= q < c as int && s.acc.counts@[q] > 0 ==> exists|r: int| 0 <= r < idx.len() && idx[r] == q,
        decreases m - c,
    {
        let cnt = s.acc.counts[c];
        if cnt > 0 {
            let ghost old = res@;
            let ghost old_idx = idx;
            let sv = s.acc.sums[c];
            res.push(OutRow { l_returnflag: s.acc.dict[c].clone(), c: cnt, s: sv });
            proof {
                let x = res@[old.len() as int];
                assert(res@ == old.push(x));
                assert(x.l_returnflag@ == s.acc.dict@[c as int]@ && x.c == cnt && s.acc.counts@[c as int] == cnt && x.s == sv);
                idx = old_idx.push(c as int);
                assert(idx.len() == res@.len());
                assert forall|r: int| 0 <= r < idx.len() implies idx[r] == (if r < old.len() as int { old_idx[r] } else { c as int }) by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies 0 <= idx[r] < (c + 1) as int by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies s.acc.counts@[idx[r]] > 0 by {};
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].l_returnflag@ == s.acc.dict@[idx[r]]@ by {
                    if r < old.len() as int { assert(res@[r] == old[r]); }
                };
                assert forall|r: int| #![trigger idx[r]] 0 <= r < idx.len() implies res@[r].c == s.acc.counts@[idx[r]] && res@[r].s == s.acc.sums@[idx[r]] by {
                    if r < old.len() as int { assert(res@[r] == old[r]); }
                };
                assert forall|r: int, r2: int| #![trigger idx[r], idx[r2]] 0 <= r < r2 < idx.len() implies idx[r] < idx[r2] by {};
                assert forall|q: int| #![trigger s.acc.counts@[q]] 0 <= q < (c + 1) as int && s.acc.counts@[q] > 0 implies exists|r: int| 0 <= r < idx.len() && idx[r] == q by {
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
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(&li, res@[r]) by {
            let q = idx[r];
            assert(s.acc.counts@[q] > 0);
            assert(s.acc.counts@[q] as int == count_c(&li, 0, li.l_returnflag__dict@[q]@));
            lemma_count_pos(&li, 0, li.l_returnflag__dict@[q]@);
            let j = choose|j: int| 0 <= j < li.n as int && row_hit(&li, j) && key_at(&li, j) == li.l_returnflag__dict@[q]@;
            assert(row_hit(&li, j) && key_at(&li, j) == res@[r].l_returnflag@);
            assert((res@[r].c as int) == count_c(&li, 0, res@[r].l_returnflag@));
            assert((res@[r].s as int) == sum_s(&li, 0, res@[r].l_returnflag@));
        };
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies res@[a].l_returnflag@ != res@[b].l_returnflag@ by {
            assert(idx[a] < idx[b]);
            assert(idx[b] < m as int);
            assert(li.l_returnflag__dict@[idx[a]]@ != li.l_returnflag__dict@[idx[b]]@);
        };
        assert forall|i0: int| #![trigger row_hit(&li, i0)] row_hit(&li, i0) && (true) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(&li, i0) == res@[r].l_returnflag@ by {
            let code = li.l_returnflag@[i0] as int;
            assert(key_at(&li, i0) == li.l_returnflag__dict@[code]@);
            lemma_count_pos(&li, 0, li.l_returnflag__dict@[code]@);
            assert(s.acc.counts@[code] as int == count_c(&li, 0, li.l_returnflag__dict@[code]@));
            assert(s.acc.counts@[code] > 0);
            let r = choose|r: int| 0 <= r < idx.len() && idx[r] == code;
            assert(res@[r].l_returnflag@ == li.l_returnflag__dict@[code]@);
        };
    }
    res
// AGENT_EDIT_END
