// Stream contract (lemma.toml [run] stream), verified fixture (tests/test_stream_null_distinct.py) and worked example: COUNT(DISTINCT x)
// per group.
//   SELECT s, COUNT(DISTINCT g) AS dg, COUNT(*) AS c FROM t GROUP BY s      (t: s VARCHAR, g VARCHAR nullable)
// The Agg field `set_count_distinct_dg: Set<Seq<char>>` is the SET of the group's non-NULL values (agg_plus is the union), so a value
// seen in two chunks or by two workers counts once; q_finish takes its size (lemma_agg_total: `.len() == count_distinct_dg(t, 0, k)`).
// The state: one slot per key (`idx`, a StringHashMap from key to slot, with its key list), the slot's row count, its values as a
// StringHashSet (`sets`, the view is the Agg set) and the same values as a list (`lists`, to merge a slot into another: a hash set
// cannot be iterated in Verus). A slot's set is swapped out of its Vec (`set_and_swap`), changed, and swapped back.
// AGENT_STATE_START
pub struct QAcc {
    pub idx: StringHashMap<usize>,
    pub keys: Vec<String>,
    pub cnt: Vec<u64>,
    pub sets: Vec<StringHashSet>,
    pub lists: Vec<Vec<String>>,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
// The values of a list, as a set.
pub open spec fn list_set(l: Seq<String>) -> Set<Seq<char>>
    decreases l.len(),
{
    if l.len() == 0 {
        Set::<Seq<char>>::empty()
    } else {
        list_set(l.drop_last()).insert(l.last()@)
    }
}

pub proof fn lemma_list_set_push(l: Seq<String>, x: String)
    ensures
        list_set(l.push(x)) == list_set(l).insert(x@),
{
    assert(l.push(x).drop_last() =~= l);
}

pub proof fn lemma_list_set_take(l: Seq<String>, i: int)
    requires
        0 <= i < l.len(),
    ensures
        list_set(l.take(i + 1)) == list_set(l.take(i)).insert(l[i]@),
{
    assert(l.take(i + 1).drop_last() =~= l.take(i));
}

pub open spec fn qacc_inv(s: &QAcc) -> bool {
    &&& s.keys@.len() == s.cnt@.len()
    &&& s.keys@.len() == s.sets@.len()
    &&& s.keys@.len() == s.lists@.len()
    &&& forall|k: Seq<char>| #[trigger] s.idx@.contains_key(k) ==> (s.idx@[k] as int) < s.keys@.len() && s.keys@[s.idx@[k] as int]@ == k
    &&& forall|j: int| 0 <= j < s.keys@.len() ==> s.idx@.contains_key(#[trigger] s.keys@[j]@) && s.idx@[s.keys@[j]@] == j
    &&& forall|j: int| 0 <= j < s.cnt@.len() ==> #[trigger] s.cnt@[j] >= 1
    &&& forall|j: int| 0 <= j < s.sets@.len() ==> #[trigger] s.sets@[j]@ == list_set(s.lists@[j]@)
}

pub open spec fn slot_val(s: &QAcc, j: int) -> Agg {
    Agg { count_c: s.cnt@[j] as int, set_count_distinct_dg: s.sets@[j]@, hits: s.cnt@[j] as int }
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

pub open spec fn count_delta(dc: int) -> Agg {
    Agg { count_c: dc, set_count_distinct_dg: Set::<Seq<char>>::empty(), hits: dc }
}

pub open spec fn set_delta(vs: Set<Seq<char>>) -> Agg {
    Agg { count_c: 0, set_count_distinct_dg: vs, hits: 0 }
}

// Add dc rows to the slot of `key` (opening it when new); the slot's index. None = overflow (decline).
pub fn add_count(m: &mut QAcc, key: &str, dc: u64) -> (r: Option<usize>)
    requires
        qacc_inv(old(m)),
        dc >= 1,
    ensures
        r matches Some(j) ==> qacc_inv(final(m)) && (j as int) < final(m).keys@.len() && final(m).keys@[j as int]@ == key@
            && forall|k: Key| #[trigger] st_val(final(m), k) == agg_plus(st_val(old(m), k), if k == key@ { count_delta(dc as int) } else { agg_zero() }),
{
    let ghost m0 = *m;
    match m.idx.get(key) {
        Some(jr) => {
            let j = *jr;
            let c = match m.cnt[j].checked_add(dc) {
                Some(v) => v,
                None => return None,
            };
            m.cnt.set(j, c);
            proof {
                assert forall|k: Key| #[trigger] st_val(m, k) == agg_plus(st_val(&m0, k), if k == key@ { count_delta(dc as int) } else { agg_zero() }) by {
                    if m.idx@.contains_key(k) && k != key@ {
                        assert(m0.keys@[m0.idx@[k] as int]@ == k);
                        assert(m0.keys@[j as int]@ == key@);
                    }
                    assert(st_val(m, k).set_count_distinct_dg =~= agg_plus(st_val(&m0, k), if k == key@ { count_delta(dc as int) } else { agg_zero() }).set_count_distinct_dg);
                }
                assert forall|jj: int| 0 <= jj < m.cnt@.len() implies #[trigger] m.cnt@[jj] >= 1 by {
                    if jj != j as int {
                        assert(m.cnt@[jj] == m0.cnt@[jj]);
                    }
                }
            }
            Some(j)
        },
        None => {
            let j = m.keys.len();
            m.keys.push(key.to_owned());
            m.idx.insert(key.to_owned(), j);
            m.cnt.push(dc);
            m.sets.push(StringHashSet::new());
            m.lists.push(Vec::new());
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
                assert forall|jj: int| 0 <= jj < m.sets@.len() implies #[trigger] m.sets@[jj]@ == list_set(m.lists@[jj]@) by {
                    if jj < j as int {
                        assert(m.sets@[jj] == m0.sets@[jj]);
                        assert(m.lists@[jj] == m0.lists@[jj]);
                    } else {
                        assert(m.lists@[jj]@ =~= Seq::<String>::empty());
                    }
                }
                assert forall|k: Key| #[trigger] st_val(m, k) == agg_plus(st_val(&m0, k), if k == key@ { count_delta(dc as int) } else { agg_zero() }) by {
                    if k != key@ && m0.idx@.contains_key(k) {
                        assert(m.idx@[k] == m0.idx@[k]);
                        assert(m.cnt@[m0.idx@[k] as int] == m0.cnt@[m0.idx@[k] as int]);
                        assert(m.sets@[m0.idx@[k] as int] == m0.sets@[m0.idx@[k] as int]);
                    }
                    assert(st_val(m, k).set_count_distinct_dg =~= agg_plus(st_val(&m0, k), if k == key@ { count_delta(dc as int) } else { agg_zero() }).set_count_distinct_dg);
                }
            }
            Some(j)
        },
    }
}

// Add the value v to the set of slot j.
pub fn add_val(m: &mut QAcc, j: usize, v: &str)
    requires
        qacc_inv(old(m)),
        (j as int) < old(m).keys@.len(),
    ensures
        qacc_inv(final(m)),
        final(m).keys@ == old(m).keys@,
        final(m).idx@ == old(m).idx@,
        forall|k: Key| #[trigger] st_val(final(m), k) == agg_plus(
            st_val(old(m), k),
            if k == old(m).keys@[j as int]@ { set_delta(Set::<Seq<char>>::empty().insert(v@)) } else { agg_zero() },
        ),
{
    let ghost m0 = *m;
    let mut st = StringHashSet::new();
    m.sets.set_and_swap(j, &mut st);
    let mut li: Vec<String> = Vec::new();
    m.lists.set_and_swap(j, &mut li);
    let ghost li0 = li@;
    if !st.contains(v) {
        st.insert(v.to_owned());
        let x = v.to_owned();
        li.push(x);
        proof {
            lemma_list_set_push(li0, x);
        }
    }
    m.sets.set_and_swap(j, &mut st);
    m.lists.set_and_swap(j, &mut li);
    proof {
        assert(m.sets@[j as int]@ =~= m0.sets@[j as int]@.insert(v@));
        assert forall|jj: int| 0 <= jj < m.sets@.len() implies #[trigger] m.sets@[jj]@ == list_set(m.lists@[jj]@) by {
            if jj != j as int {
                assert(m.sets@[jj] == m0.sets@[jj]);
                assert(m.lists@[jj] == m0.lists@[jj]);
            }
        }
        assert forall|k: Key| #[trigger] st_val(m, k) == agg_plus(
            st_val(&m0, k),
            if k == m0.keys@[j as int]@ { set_delta(Set::<Seq<char>>::empty().insert(v@)) } else { agg_zero() },
        ) by {
            if m.idx@.contains_key(k) {
                let jk = m.idx@[k] as int;
                if jk != j as int {
                    assert(m.sets@[jk] == m0.sets@[jk]);
                    assert(k != m0.keys@[j as int]@);
                } else {
                    assert(k == m0.keys@[j as int]@);
                }
            } else {
                assert(k != m0.keys@[j as int]@);
            }
            assert(st_val(m, k).set_count_distinct_dg =~= agg_plus(
                st_val(&m0, k),
                if k == m0.keys@[j as int]@ { set_delta(Set::<Seq<char>>::empty().insert(v@)) } else { agg_zero() },
            ).set_count_distinct_dg);
        }
    }
}
// AGENT_HELPERS_END
// AGENT_INIT_START
    let s = QAcc { idx: StringHashMap::new(), keys: Vec::new(), cnt: Vec::new(), sets: Vec::new(), lists: Vec::new() };
    proof {
        assert forall|k: Key| #[trigger] st_val(&s, k) == agg_zero() by {}
    }
    s
// AGENT_INIT_END
// AGENT_STEP_START
    let ghost t = stream_table_t(c.sid);
    let ghost s0 = *s;
    proof {
        assert forall|k: Key| #[trigger] st_val(s, k) == agg_plus(st_val(&s0, k), agg_rng(&t, c.off as int, c.off as int, k, p)) by {
            lemma_agg_empty(&t, c.off as int, k, p);
            assert(st_val(s, k).set_count_distinct_dg =~= agg_plus(st_val(&s0, k), agg_zero()).set_count_distinct_dg);
        }
    }
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
        let ghost s1 = *s;
        let ghost i = c.off + r;
        proof {
            assert(key@ == t.s@[i]@);
            assert(key_at(&t, i) == key@);
            assert(c.g__valid@[r as int] == t.g__valid@[i]);
        }
        let j = match add_count(s, key, 1) {
            Some(j) => j,
            None => return false,
        };
        let ghost s2 = *s;
        let ghost vs: Set<Seq<char>> = if t.g__valid@[i] { Set::<Seq<char>>::empty().insert(t.g@[i]@) } else { Set::<Seq<char>>::empty() };
        if c.g__valid[r] {
            let v = str_ent(&c.g, c.g.sel[r] as usize);
            proof {
                assert(v@ == t.g@[i]@);
            }
            add_val(s, j, v);
        }
        proof {
            assert forall|k: Key| #[trigger] st_val(s, k) == agg_plus(st_val(&s0, k), agg_rng(&t, c.off as int, c.off + r + 1, k, p)) by {
                lemma_agg_step(&t, c.off as int, c.off + r + 1, k, p);
                assert(st_val(&s1, k) == agg_plus(st_val(&s0, k), agg_rng(&t, c.off as int, c.off + r, k, p)));
                assert(st_val(&s2, k) == agg_plus(st_val(&s1, k), if k == key@ { count_delta(1) } else { agg_zero() }));
                assert(st_val(s, k) == agg_plus(st_val(&s2, k), if k == key@ { set_delta(vs) } else { agg_zero() })) by {
                    if !t.g__valid@[i] {
                        assert(st_val(s, k).set_count_distinct_dg =~= agg_plus(st_val(&s2, k), if k == key@ { set_delta(vs) } else { agg_zero() }).set_count_distinct_dg);
                    }
                }
                assert(agg_row(&t, i, k, p).set_count_distinct_dg =~= (if k == key@ { vs } else { Set::<Seq<char>>::empty() }));
                assert(st_val(s, k).set_count_distinct_dg =~= agg_plus(st_val(&s0, k), agg_rng(&t, c.off as int, c.off + r + 1, k, p)).set_count_distinct_dg);
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
    proof {
        assert forall|k: Key| #[trigger] st_val(&m, k) == agg_plus(st_val(&a0, k), st_part(&b, k, 0)) by {
            assert(st_val(&m, k).set_count_distinct_dg =~= agg_plus(st_val(&a0, k), agg_zero()).set_count_distinct_dg);
        }
    }
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
        let jm = match add_count(&mut m, key, b.cnt[j]) {
            Some(x) => x,
            None => return None,
        };
        let ghost m2 = m;
        let ghost l = b.lists@[j as int]@;
        let mut i: usize = 0;
        proof {
            assert(l.take(0) =~= Seq::<String>::empty());
            assert forall|k: Key| #[trigger] st_val(&m, k) == agg_plus(st_val(&m2, k), if k == key@ { set_delta(list_set(l.take(0))) } else { agg_zero() }) by {
                assert(st_val(&m, k).set_count_distinct_dg =~= agg_plus(st_val(&m2, k), if k == key@ { set_delta(list_set(l.take(0))) } else { agg_zero() }).set_count_distinct_dg);
            }
        }
        while i < b.lists[j].len()
            invariant
                qacc_inv(&m),
                qacc_inv(&b),
                (j as int) < b.keys@.len(),
                l == b.lists@[j as int]@,
                (jm as int) < m.keys@.len(),
                m.keys@[jm as int]@ == key@,
                i <= l.len(),
                forall|k: Key| #[trigger] st_val(&m, k) == agg_plus(st_val(&m2, k), if k == key@ { set_delta(list_set(l.take(i as int))) } else { agg_zero() }),
            decreases l.len() - i,
        {
            let ghost m3 = m;
            add_val(&mut m, jm, b.lists[j][i].as_str());
            proof {
                lemma_list_set_take(l, i as int);
                assert forall|k: Key| #[trigger] st_val(&m, k) == agg_plus(st_val(&m2, k), if k == key@ { set_delta(list_set(l.take(i as int + 1))) } else { agg_zero() }) by {
                    assert(st_val(&m3, k) == agg_plus(st_val(&m2, k), if k == key@ { set_delta(list_set(l.take(i as int))) } else { agg_zero() }));
                    assert(st_val(&m, k).set_count_distinct_dg =~= agg_plus(st_val(&m2, k), if k == key@ { set_delta(list_set(l.take(i as int + 1))) } else { agg_zero() }).set_count_distinct_dg);
                }
            }
            i += 1;
        }
        proof {
            assert(l.take(l.len() as int) =~= l);
            assert(b.sets@[j as int]@ == list_set(l));
            assert forall|k: Key| #[trigger] st_val(&m, k) == agg_plus(st_val(&a0, k), st_part(&b, k, j as int + 1)) by {
                assert(st_val(&m1, k) == agg_plus(st_val(&a0, k), st_part(&b, k, j as int)));
                assert(st_val(&m2, k) == agg_plus(st_val(&m1, k), if k == key@ { count_delta(b.cnt@[j as int] as int) } else { agg_zero() }));
                if k == key@ {
                    assert(b.idx@[k] == j);
                } else if b.idx@.contains_key(k) {
                    assert(b.keys@[b.idx@[k] as int]@ == k);
                }
                assert(st_val(&m, k).set_count_distinct_dg =~= agg_plus(st_val(&a0, k), st_part(&b, k, j as int + 1)).set_count_distinct_dg);
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
            forall|r: int| #![trigger res@[r]] 0 <= r < j ==> res@[r].s@ == s.keys@[r]@ && res@[r].c == s.cnt@[r]
                && res@[r].dg as int == s.sets@[r]@.len(),
        decreases s.keys@.len() - j,
    {
        let dg = s.sets[j].len() as u64;
        res.push(OutRow { s: s.keys[j].clone(), dg, c: s.cnt[j] });
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
