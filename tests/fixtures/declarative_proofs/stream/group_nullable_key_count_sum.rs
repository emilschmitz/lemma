// Stream contract (lemma.toml [run] stream), verified fixture (tests/test_stream_null_distinct.py) and worked example: a GROUP BY a
// nullable string key.
//   SELECT g, COUNT(*) AS c, SUM(m) AS sm FROM t GROUP BY g      (t: g VARCHAR nullable, m DECIMAL(12,2))
// `Key` is `(bool, Seq<char>)`: `(true, v)` for the value v, `(false, "")` for NULL. All NULL rows form ONE group of their own, apart
// from every value group (also from the empty string's). The state: one slot per string key seen (`idx`, a StringHashMap from key to
// slot, with its key list) and a separate NULL slot (`ncnt`, `nsum`); counts and exact sums (checked: an overflow declines).
// AGENT_STATE_START
pub struct QAcc {
    pub idx: StringHashMap<usize>,
    pub keys: Vec<String>,
    pub cnt: Vec<u64>,
    pub sum: Vec<i128>,
    pub ncnt: u64,
    pub nsum: i128,
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

pub open spec fn null_val(s: &QAcc) -> Agg {
    Agg { count_c: s.ncnt as int, sum_sm: s.nsum as int, hits: s.ncnt as int }
}

// The NULL key: (false, "") is the only key a NULL cell has (key_at); (false, x) for another x is no row's key.
pub open spec fn null_key() -> Key {
    (false, Seq::<char>::empty())
}

pub open spec fn st_val(s: &QAcc, k: Key) -> Agg {
    if k.0 {
        if s.idx@.contains_key(k.1) {
            slot_val(s, s.idx@[k.1] as int)
        } else {
            agg_zero()
        }
    } else if k == null_key() {
        null_val(s)
    } else {
        agg_zero()
    }
}

// The part of b's state in its string slots below j (q_merge folds b's slots into a one by one, then b's NULL slot).
pub open spec fn st_part(b: &QAcc, k: Key, j: int) -> Agg {
    if k.0 && b.idx@.contains_key(k.1) && (b.idx@[k.1] as int) < j {
        st_val(b, k)
    } else {
        agg_zero()
    }
}

// Add (count, sum) to the slot of the string key `key` in `m`, or open a new slot. false = overflow (decline).
pub fn add_to(m: &mut QAcc, key: &str, dc: u64, ds: i128) -> (ok: bool)
    requires
        qacc_inv(old(m)),
        dc >= 1,
    ensures
        ok ==> qacc_inv(final(m)) && forall|k: Key| #[trigger] st_val(final(m), k) == agg_plus(
            st_val(old(m), k),
            if k == (true, key@) { Agg { count_c: dc as int, sum_sm: ds as int, hits: dc as int } } else { agg_zero() },
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
                    if k == (true, key@) { Agg { count_c: dc as int, sum_sm: ds as int, hits: dc as int } } else { agg_zero() },
                ) by {
                    if k.0 && m.idx@.contains_key(k.1) && k.1 != key@ {
                        assert(m0.keys@[m0.idx@[k.1] as int]@ == k.1);
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
                    if k == (true, key@) { Agg { count_c: dc as int, sum_sm: ds as int, hits: dc as int } } else { agg_zero() },
                ) by {
                    if k.0 && k.1 != key@ && m0.idx@.contains_key(k.1) {
                        assert(m.idx@[k.1] == m0.idx@[k.1]);
                        assert(m.cnt@[m0.idx@[k.1] as int] == m0.cnt@[m0.idx@[k.1] as int]);
                        assert(m.sum@[m0.idx@[k.1] as int] == m0.sum@[m0.idx@[k.1] as int]);
                    }
                }
            }
            true
        },
    }
}

// Add (count, sum) to the NULL slot. false = overflow (decline).
pub fn add_null(m: &mut QAcc, dc: u64, ds: i128) -> (ok: bool)
    requires
        qacc_inv(old(m)),
    ensures
        ok ==> qacc_inv(final(m)) && forall|k: Key| #[trigger] st_val(final(m), k) == agg_plus(
            st_val(old(m), k),
            if k == null_key() { Agg { count_c: dc as int, sum_sm: ds as int, hits: dc as int } } else { agg_zero() },
        ),
{
    let c = match m.ncnt.checked_add(dc) {
        Some(v) => v,
        None => return false,
    };
    let s = match m.nsum.checked_add(ds) {
        Some(v) => v,
        None => return false,
    };
    m.ncnt = c;
    m.nsum = s;
    true
}
// AGENT_HELPERS_END
// AGENT_INIT_START
    let s = QAcc { idx: StringHashMap::new(), keys: Vec::new(), cnt: Vec::new(), sum: Vec::new(), ncnt: 0, nsum: 0 };
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
        let m = c.m[r];
        let ghost s1 = *s;
        proof {
            assert(t.m@[c.off + r] == m);
            assert(c.g__valid@[r as int] == t.g__valid@[c.off + r]);
        }
        if c.g__valid[r] {
            let key = str_ent(&c.g, c.g.sel[r] as usize);
            proof {
                assert(key@ == t.g@[c.off + r]@);
                assert(key_at(&t, c.off + r) == (true, key@));
            }
            if !add_to(s, key, 1, m as i128) {
                return false;
            }
        } else {
            proof {
                assert(key_at(&t, c.off + r) == null_key());
            }
            if !add_null(s, 1, m as i128) {
                return false;
            }
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
                if k == (true, key@) {
                    assert(b.idx@[k.1] == j);
                } else if k.0 && b.idx@.contains_key(k.1) {
                    assert(b.keys@[b.idx@[k.1] as int]@ == k.1);
                }
            }
        }
        j += 1;
    }
    let ghost m2 = m;
    if !add_null(&mut m, b.ncnt, b.nsum) {
        return None;
    }
    proof {
        assert forall|k: Key| #[trigger] st_val(&m, k) == agg_plus(st_val(&a0, k), st_val(&b, k)) by {
            assert(st_val(&m2, k) == agg_plus(st_val(&a0, k), st_part(&b, k, j as int)));
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
            forall|r: int| #![trigger res@[r]] 0 <= r < j ==> res@[r].g is Some && res@[r].g->Some_0@ == s.keys@[r]@ && res@[r].c == s.cnt@[r]
                && res@[r].sm == s.sum@[r],
        decreases s.keys@.len() - j,
    {
        res.push(OutRow { g: Some(s.keys[j].clone()), c: s.cnt[j], sm: s.sum[j] });
        j += 1;
    }
    let nk = res.len();
    if s.ncnt > 0 {
        res.push(OutRow { g: None, c: s.ncnt, sm: s.nsum });
    }
    proof {
        let tt = t@;
        assert forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() implies out_row_ok(&tt, res@[r]) by {
            if r < nk {
                let k = (true, s.keys@[r]@);
                lemma_agg_total(&tt, k, p);
                assert(s.idx@[k.1] == r);
                assert(st_val(&s, k) == agg_rng(&tt, 0, tt.n as int, k, p));
                assert(s.cnt@[r] >= 1);
                let i0 = choose|i0: int| #![trigger row_hit(&tt, i0)] row_hit(&tt, i0) && key_at(&tt, i0) == k;
                assert(row_hit(&tt, i0) && key_at(&tt, i0) == k);
            } else {
                let k = null_key();
                lemma_agg_total(&tt, k, p);
                assert(st_val(&s, k) == agg_rng(&tt, 0, tt.n as int, k, p));
                let i0 = choose|i0: int| #![trigger row_hit(&tt, i0)] row_hit(&tt, i0) && key_at(&tt, i0) == k;
                assert(row_hit(&tt, i0) && key_at(&tt, i0) == k);
            }
        }
        assert forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() implies (if res@[a].g is Some {
            (true, res@[a].g->Some_0@)
        } else {
            (false, Seq::<char>::empty())
        }) != (if res@[b].g is Some { (true, res@[b].g->Some_0@) } else { (false, Seq::<char>::empty()) }) by {
            if b < nk {
                assert(s.idx@[s.keys@[a]@] == a);
                assert(s.idx@[s.keys@[b]@] == b);
            }
        }
        assert forall|i0: int| #![trigger row_hit(&tt, i0)] row_hit(&tt, i0) && (true) implies exists|r: int| #![trigger res@[r]] 0 <= r < res@.len()
            && key_at(&tt, i0) == (if res@[r].g is Some { (true, res@[r].g->Some_0@) } else { (false, Seq::<char>::empty()) }) by {
            let k = key_at(&tt, i0);
            lemma_agg_total(&tt, k, p);
            assert(st_val(&s, k) == agg_rng(&tt, 0, tt.n as int, k, p));
            if k.0 {
                assert(s.idx@.contains_key(k.1));
                let r = s.idx@[k.1] as int;
                assert(res@[r].g->Some_0@ == k.1);
            } else {
                assert(k == null_key());
                assert(s.ncnt > 0);
                assert(res@[nk as int].g is None);
            }
        }
    }
    Some(res)
// AGENT_FINISH_END
