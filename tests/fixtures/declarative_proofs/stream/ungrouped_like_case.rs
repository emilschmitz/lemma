// Stream contract (lemma.toml [run] stream), verified fixture (tests/test_stream_strings.py): LIKE inside CASE inside SUM.
//   SELECT SUM(CASE WHEN s LIKE 'ab%' THEN m ELSE 0 END) AS sp, SUM(m) AS sm, COUNT(*) AS c FROM t
//   (t: s VARCHAR, m DECIMAL(12,2); no NULLs; both SUMs are NULL on an empty table)
// The spec states LIKE as spec_like over Seq<char> (a per-row predicate of agg_row). `LIKE 'ab%'` is "starts with ab"
// (lemma_like_prefix, by induction on the literal). Per chunk, each ENTRY of s is tested once (a Vec<bool> memo indexed by
// entry); per row the CASE is an array read. The state: the two exact sums and the count (checked: an overflow declines).
// AGENT_STATE_START
pub struct QAcc {
    pub sp: i128,
    pub sm: i128,
    pub cnt: u64,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
pub open spec fn qacc_inv(s: &QAcc) -> bool {
    true
}

pub open spec fn st_val(s: &QAcc, k: Key) -> Agg {
    Agg { sum_sp: s.sp as int, sum_sm: s.sm as int, count_c: s.cnt as int, hits: s.cnt as int }
}

proof fn lemma_like_pct(s: Seq<char>)
    ensures
        spec_like(s, seq!['%']),
    decreases s.len(),
{
    let p = seq!['%'];
    assert(p.len() == 1 && p[0] == '%');
    assert(p.skip(1) =~= Seq::<char>::empty());
    if s.len() == 0 {
        assert(spec_like(s, p.skip(1)));
    } else {
        lemma_like_pct(s.skip(1));
        assert(spec_like(s.skip(1), p));
    }
}

// `col LIKE 'lit%'` for a literal without `%` or `_`: the cell starts with the literal.
proof fn lemma_like_prefix(s: Seq<char>, pre: Seq<char>)
    requires
        forall|i: int| 0 <= i < pre.len() ==> pre[i] != '%' && pre[i] != '_',
    ensures
        spec_like(s, pre.push('%')) == (s.len() >= pre.len() && s.subrange(0, pre.len() as int) =~= pre),
    decreases pre.len(),
{
    let p = pre.push('%');
    if pre.len() == 0 {
        assert(p =~= seq!['%']);
        lemma_like_pct(s);
    } else {
        assert(p.len() == pre.len() + 1);
        assert(p[0] == pre[0]);
        assert(p.skip(1) =~= pre.skip(1).push('%'));
        if s.len() > 0 {
            lemma_like_prefix(s.skip(1), pre.skip(1));
            assert(forall|i: int| 0 <= i < pre.skip(1).len() ==> pre.skip(1)[i] != '%' && pre.skip(1)[i] != '_');
            if s.len() >= pre.len() && s[0] == pre[0] && s.skip(1).subrange(0, pre.len() - 1) =~= pre.skip(1) {
                let n = pre.len() as int;
                assert forall|i: int| 0 <= i < n implies s.subrange(0, n)[i] == pre[i] by {
                    if i > 0 {
                        assert(s.skip(1).subrange(0, n - 1)[i - 1] == pre.skip(1)[i - 1]);
                    }
                };
                assert(s.subrange(0, n) =~= pre);
            }
            if s.len() >= pre.len() && s.subrange(0, pre.len() as int) =~= pre {
                assert(s[0] == pre[0]);
                assert(s.skip(1).subrange(0, pre.len() - 1) =~= pre.skip(1));
            }
        }
    }
}

proof fn lemma_ab_like(s: Seq<char>)
    ensures
        spec_like(s, "ab%"@) == (s.len() >= 2 && s[0] == 'a' && s[1] == 'b'),
{
    reveal_strlit("ab%");
    let pre = seq!['a', 'b'];
    assert("ab%"@ =~= pre.push('%'));
    lemma_like_prefix(s, pre);
    if s.len() >= 2 && s[0] == 'a' && s[1] == 'b' {
        assert(s.subrange(0, 2) =~= pre);
    }
    if s.len() >= 2 && s.subrange(0, 2) =~= pre {
        assert(s[0] == 'a' && s[1] == 'b');
    }
}

// The largest selection index of a non-empty chunk column: an entry some row uses, and every row's entry is at most it.
pub fn max_sel(sel: &[u32]) -> (mx: u32)
    requires
        sel@.len() > 0,
    ensures
        exists|r: int| 0 <= r < sel@.len() && sel@[r] == mx,
        forall|r: int| 0 <= r < sel@.len() ==> sel@[r] <= mx,
{
    let mut mx = sel[0];
    let mut r: usize = 1;
    while r < sel.len()
        invariant
            1 <= r <= sel@.len(),
            exists|q: int| 0 <= q < r && sel@[q] == mx,
            forall|q: int| 0 <= q < r ==> sel@[q] <= mx,
        decreases sel@.len() - r,
    {
        if sel[r] > mx {
            mx = sel[r];
        }
        r += 1;
    }
    mx
}

// The memo of one chunk column: h[j] = entry j is LIKE 'ab%', for every entry j <= mx.
pub fn memo_like(v: &StrCol, mx: u32) -> (h: Vec<bool>)
    requires
        (mx as int) < v.ents@.len(),
    ensures
        h@.len() == mx as int + 1,
        forall|j: int| 0 <= j <= mx ==> #[trigger] h@[j] == spec_like(v.ents@[j], "ab%"@),
{
    let mut h: Vec<bool> = Vec::new();
    let mut j: u64 = 0;
    while j <= mx as u64
        invariant
            j <= mx as u64 + 1,
            h@.len() == j,
            (mx as int) < v.ents@.len(),
            forall|q: int| 0 <= q < j ==> #[trigger] h@[q] == spec_like(v.ents@[q], "ab%"@),
        decreases mx as u64 + 1 - j,
    {
        let e = str_ent(v, j as usize);
        let hit = e.unicode_len() >= 2 && e.get_char(0) == 'a' && e.get_char(1) == 'b';
        proof {
            lemma_ab_like(e@);
        }
        h.push(hit);
        j += 1;
    }
    h
}
// AGENT_HELPERS_END
// AGENT_INIT_START
    QAcc { sp: 0, sm: 0, cnt: 0 }
// AGENT_INIT_END
// AGENT_STEP_START
    let ghost t = stream_table_t(c.sid);
    let ghost s0 = st_val(old(s), ());
    if c.len == 0 {
        proof {
            lemma_agg_empty(&t, c.off as int, (), p);
        }
        return true;
    }
    let mx = max_sel(c.s.sel);
    proof {
        let r1 = choose|r: int| 0 <= r < c.s.sel@.len() && c.s.sel@[r] == mx;
        assert((c.s.sel@[r1] as int) < c.s.ents@.len());
    }
    let hl = memo_like(&c.s, mx);
    let mut r: usize = 0;
    while r < c.len
        invariant
            chunk_ok_t(c),
            t == stream_table_t(c.sid),
            r <= c.len,
            hl@.len() == mx as int + 1,
            forall|q: int| 0 <= q < c.len ==> c.s.sel@[q] <= mx,
            forall|j: int| 0 <= j <= mx ==> #[trigger] hl@[j] == spec_like(c.s.ents@[j], "ab%"@),
            st_val(s, ()) == agg_plus(s0, agg_rng(&t, c.off as int, c.off + r, (), p)),
        decreases c.len - r,
    {
        let j = c.s.sel[r] as usize;
        let m = c.m[r];
        let v: i64 = if hl[j] { m } else { 0 };
        proof {
            lemma_agg_step(&t, c.off as int, c.off + r + 1, (), p);
            assert(c.s.ents@[j as int] == t.s@[c.off + r]@);
            assert(t.m@[c.off + r] == m);
            assert(v as int == sum_sp_val(&t, c.off + r));
        }
        s.sp = match s.sp.checked_add(v as i128) {
            Some(x) => x,
            None => return false,
        };
        s.sm = match s.sm.checked_add(m as i128) {
            Some(x) => x,
            None => return false,
        };
        s.cnt = match s.cnt.checked_add(1) {
            Some(x) => x,
            None => return false,
        };
        r += 1;
    }
    proof {
        assert forall|k: Key| #[trigger] st_val(s, k) == agg_plus(st_val(old(s), k), agg_rng(&t, c.off as int, c.off + c.len, k, p)) by {}
    }
    true
// AGENT_STEP_END
// AGENT_MERGE_START
    let sp = match a.sp.checked_add(b.sp) {
        Some(v) => v,
        None => return None,
    };
    let sm = match a.sm.checked_add(b.sm) {
        Some(v) => v,
        None => return None,
    };
    let cnt = match a.cnt.checked_add(b.cnt) {
        Some(v) => v,
        None => return None,
    };
    Some(QAcc { sp, sm, cnt })
// AGENT_MERGE_END
// AGENT_FINISH_START
    proof {
        lemma_agg_total(&t@, (), p);
        assert(st_val(&s, ()) == agg_rng(&t@, 0, t@.n as int, (), p));
    }
    let mut res: Vec<OutRow> = Vec::new();
    if s.cnt > 0 {
        res.push(OutRow { sp: Some(s.sp), sm: Some(s.sm), c: s.cnt });
    } else {
        res.push(OutRow { sp: None, sm: None, c: 0 });
    }
    proof {
        assert(res@.len() == 1);
    }
    Some(res)
// AGENT_FINISH_END
