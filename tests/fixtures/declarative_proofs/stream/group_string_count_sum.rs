// Stream contract (lemma.toml [run] stream), host test fixture: a small GROUP BY with a string key.
//   SELECT s, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY s      (t: m DECIMAL(12,2), s VARCHAR; no NULLs in them)
// The state: one slot per key seen (`keys`, a StringHashMap from key to slot), its count and exact sum (checked: an overflow declines).
// AGENT_STATE_START
pub struct QAcc {
    pub idx: StringHashMap<usize>,
    pub keys: Vec<String>,
    pub cnt: Vec<u64>,
    pub sum: Vec<i128>,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
pub open spec fn qacc_inv(s: &QAcc) -> bool {
    &&& s.keys@.len() == s.cnt@.len()
    &&& s.keys@.len() == s.sum@.len()
    &&& forall|k: Seq<char>| #[trigger] s.idx@.contains_key(k) ==> (s.idx@[k] as int) < s.keys@.len() && s.keys@[s.idx@[k] as int]@ == k
    &&& forall|j: int| 0 <= j < s.keys@.len() ==> s.idx@.contains_key(#[trigger] s.keys@[j]@) && s.idx@[s.keys@[j]@] == j
    &&& forall|j: int| 0 <= j < s.cnt@.len() ==> #[trigger] s.cnt@[j] >= 1
}

pub open spec fn slot_val(s: &QAcc, j: int) -> Agg {
    Agg { count_c: s.cnt@[j] as int, sum_sm: s.sum@[j] as int, hits: s.cnt@[j] as int }
}

pub open spec fn st_val(s: &QAcc, k: Key) -> Agg {
    if s.idx@.contains_key(k) {
        slot_val(s, s.idx@[k] as int)
    } else {
        agg_zero()
    }
}

// The part of b's state in its slots below j (q_merge folds b's slots into a one by one).
pub open spec fn st_part(b: &QAcc, k: Key, j: int) -> Agg {
    if b.idx@.contains_key(k) && (b.idx@[k] as int) < j {
        st_val(b, k)
    } else {
        agg_zero()
    }
}

// Add `v` (count, sum) to the slot of `key` in `m`, or open a new slot. false = overflow (decline).
pub fn add_to(m: &mut QAcc, key: &str, dc: u64, ds: i128) -> (ok: bool)
    requires
        qacc_inv(old(m)),
        dc >= 1,
    ensures
        ok ==> qacc_inv(final(m)) && forall|k: Key| #[trigger] st_val(final(m), k) == agg_plus(
            st_val(old(m), k),
            if k == key@ { Agg { count_c: dc as int, sum_sm: ds as int, hits: dc as int } } else { agg_zero() },
        ),
{
    let ghost m0 = *m;
    match m.idx.get(key) {
        Some(jr) => {
            let j = *jr;
            let c = match m.cnt[j].checked_add(dc) {
                Some(v) => v,
                None => return false,
            };
            let s = match m.sum[j].checked_add(ds) {
                Some(v) => v,
                None => return false,
            };
            m.cnt.set(j, c);
            m.sum.set(j, s);
            proof {
                assert forall|k: Key| #[trigger] st_val(m, k) == agg_plus(
                    st_val(&m0, k),
                    if k == key@ { Agg { count_c: dc as int, sum_sm: ds as int, hits: dc as int } } else { agg_zero() },
                ) by {
                    if m.idx@.contains_key(k) && k != key@ {
                        assert(m0.keys@[m0.idx@[k] as int]@ == k);
                        assert(m0.keys@[j as int]@ == key@);
                    }
                }
                assert forall|jj: int| 0 <= jj < m.cnt@.len() implies #[trigger] m.cnt@[jj] >= 1 by {
                    if jj != j as int {
                        assert(m.cnt@[jj] == m0.cnt@[jj]);
                    }
                }
            }
            true
        },
        None => {
            let j = m.keys.len();
            m.keys.push(key.to_owned());
            m.idx.insert(key.to_owned(), j);
            m.cnt.push(dc);
            m.sum.push(ds);
            proof {
                assert forall|k: Seq<char>| #[trigger] m.idx@.contains_key(k) implies (m.idx@[k] as int) < m.keys@.len() && m.keys@[m.idx@[k] as int]@ == k by {
                    if k != key@ {
                        assert(m0.idx@.contains_key(k));
                    }
                }
                assert forall|jj: int| 0 <= jj < m.keys@.len() implies m.idx@.contains_key(#[trigger] m.keys@[jj]@) && m.idx@[m.keys@[jj]@] == jj by {
                    if jj < j as int {
                        assert(m.keys@[jj] == m0.keys@[jj]);
                        assert(m0.idx@.contains_key(m0.keys@[jj]@));
                    }
                }
                assert forall|jj: int| 0 <= jj < m.cnt@.len() implies #[trigger] m.cnt@[jj] >= 1 by {
                    if jj < j as int {
                        assert(m.cnt@[jj] == m0.cnt@[jj]);
                    }
                }
                assert forall|k: Key| #[trigger] st_val(m, k) == agg_plus(
                    st_val(&m0, k),
                    if k == key@ { Agg { count_c: dc as int, sum_sm: ds as int, hits: dc as int } } else { agg_zero() },
                ) by {
                    if k != key@ && m0.idx@.contains_key(k) {
                        assert(m.idx@[k] == m0.idx@[k]);
                        assert(m.cnt@[m0.idx@[k] as int] == m0.cnt@[m0.idx@[k] as int]);
                        assert(m.sum@[m0.idx@[k] as int] == m0.sum@[m0.idx@[k] as int]);
                    }
                }
            }
            true
        },
    }
}
// AGENT_HELPERS_END
// AGENT_INIT_START
    let s = QAcc { idx: StringHashMap::new(), keys: Vec::new(), cnt: Vec::new(), sum: Vec::new() };
    proof {
        assert forall|k: Key| #[trigger] st_val(&s, k) == agg_zero() by {}
    }
    s
// AGENT_INIT_END
// AGENT_STEP_START
    let ghost t = stream_table_t(c.sid);
    let ghost s0 = *s;
    let mut r: usize = 0;
    while r < c.len
        invariant
            chunk_ok_t(c),
            t == stream_table_t(c.sid),
            r <= c.len,
            qacc_inv(s),
            forall|k: Key| #[trigger] st_val(s, k) == agg_plus(st_val(&s0, k), agg_rng(&t, c.off as int, c.off + r, k, p)),
        decreases c.len - r,
    {
        let key = str_ent(&c.s, c.s.sel[r] as usize);
        let m = c.m[r];
        let ghost s1 = *s;
        proof {
            assert(key@ == t.s@[c.off + r]@);
            assert(key_at(&t, c.off + r) == key@);
            assert(t.m@[c.off + r] == m);
        }
        if !add_to(s, key, 1, m as i128) {
            return false;
        }
        proof {
            assert forall|k: Key| #[trigger] st_val(s, k) == agg_plus(st_val(&s0, k), agg_rng(&t, c.off as int, c.off + r + 1, k, p)) by {
                lemma_agg_step(&t, c.off as int, c.off + r + 1, k, p);
                assert(st_val(&s1, k) == agg_plus(st_val(&s0, k), agg_rng(&t, c.off as int, c.off + r, k, p)));
            }
        }
        r += 1;
    }
    true
// AGENT_STEP_END
// AGENT_MERGE_START
    let ghost a0 = a;
    let mut m = a;
    let mut j: usize = 0;
    while j < b.keys.len()
        invariant
            qacc_inv(&m),
            qacc_inv(&b),
            j <= b.keys@.len(),
            forall|k: Key| #[trigger] st_val(&m, k) == agg_plus(st_val(&a0, k), st_part(&b, k, j as int)),
        decreases b.keys@.len() - j,
    {
        let key = b.keys[j].as_str();
        let ghost m1 = m;
        proof {
            assert(b.idx@.contains_key(b.keys@[j as int]@));
            assert(b.cnt@[j as int] >= 1);
        }
        if !add_to(&mut m, key, b.cnt[j], b.sum[j]) {
            return None;
        }
        proof {
            assert forall|k: Key| #[trigger] st_val(&m, k) == agg_plus(st_val(&a0, k), st_part(&b, k, j as int + 1)) by {
                assert(st_val(&m1, k) == agg_plus(st_val(&a0, k), st_part(&b, k, j as int)));
                if k == key@ {
                    assert(b.idx@[k] == j);
                } else if b.idx@.contains_key(k) {
                    assert(b.keys@[b.idx@[k] as int]@ == k);
                }
            }
        }
        j += 1;
    }
    proof {
        assert forall|k: Key| #[trigger] st_val(&m, k) == agg_plus(st_val(&a0, k), st_val(&b, k)) by {
            assert(st_val(&m, k) == agg_plus(st_val(&a0, k), st_part(&b, k, j as int)));
        }
    }
    Some(m)
// AGENT_MERGE_END
// AGENT_FINISH_START
    let mut res: Vec<OutRow> = Vec::new();
    let mut j: usize = 0;
    while j < s.keys.len()
        invariant
            qacc_inv(&s),
            j <= s.keys@.len(),
            res@.len() == j,
            forall|r: int| #![trigger res@[r]] 0 <= r < j ==> res@[r].s@ == s.keys@[r]@ && res@[r].c == s.cnt@[r] && res@[r].sm == s.sum@[r],
        decreases s.keys@.len() - j,
    {
        res.push(OutRow { s: s.keys[j].clone(), c: s.cnt[j], sm: s.sum[j] });
        j += 1;
    }
    proof {
        let tt = t@;
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(&tt, res@[r]) by {
            let k = s.keys@[r]@;
            lemma_agg_total(&tt, k, p);
            assert(s.idx@[k] == r);
            assert(st_val(&s, k) == agg_rng(&tt, 0, tt.n as int, k, p));
            assert(s.cnt@[r] >= 1);
            let i0 = choose|i0: int| #![trigger row_hit(&tt, i0)] row_hit(&tt, i0) && key_at(&tt, i0) == k;
            assert(row_hit(&tt, i0) && key_at(&tt, i0) == res@[r].s@);
        }
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies res@[a].s@ != res@[b].s@ by {
            assert(s.idx@[s.keys@[a]@] == a);
            assert(s.idx@[s.keys@[b]@] == b);
        }
        assert forall|i0: int| #![trigger row_hit(&tt, i0)] row_hit(&tt, i0) && (true) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(&tt, i0) == res@[r].s@ by {
            let k = key_at(&tt, i0);
            lemma_agg_total(&tt, k, p);
            assert(st_val(&s, k) == agg_rng(&tt, 0, tt.n as int, k, p));
            assert(s.idx@.contains_key(k));
            let r = s.idx@[k] as int;
            assert(res@[r].s@ == k);
        }
    }
    Some(res)
// AGENT_FINISH_END
