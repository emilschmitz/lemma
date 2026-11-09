// Stream contract (lemma.toml [run] stream), verified fixture (tests/test_stream_strings.py): VARCHAR template parameters.
//   -- params: x VARCHAR, y VARCHAR, z VARCHAR
//   SELECT COUNT(*) AS c, SUM(m) AS sm FROM t WHERE s = $x AND g IN ($y, $z)      (t: g, s VARCHAR, m DECIMAL(12,2); no NULLs)
// Params holds the strings (p.x, p.y, p.z); the spec reads them through params_canon(p), whose texts are p's (lemma_param_str).
// Per chunk, each ENTRY of s and g is compared with the parameters once (a Vec<bool> memo indexed by entry); per row the WHERE
// is two array reads. The state: the count and the exact sum (checked: an overflow declines).
// AGENT_STATE_START
pub struct QAcc {
    pub cnt: u64,
    pub sum: i128,
}
// AGENT_STATE_END
// AGENT_HELPERS_START
pub open spec fn qacc_inv(s: &QAcc) -> bool {
    true
}

pub open spec fn st_val(s: &QAcc, k: Key) -> Agg {
    Agg { count_c: s.cnt as int, sum_sm: s.sum as int, hits: s.cnt as int }
}

// Equal texts, char by char (vstd's exact specs of unicode_len and get_char).
pub fn eq_text(a: &str, b: &str) -> (r: bool)
    ensures
        r == (a@ == b@),
{
    let n = a.unicode_len();
    if n != b.unicode_len() {
        return false;
    }
    let mut i: usize = 0;
    while i < n
        invariant
            n == a@.len(),
            n == b@.len(),
            i <= n,
            forall|j: int| 0 <= j < i ==> a@[j] == b@[j],
        decreases n - i,
    {
        if a.get_char(i) != b.get_char(i) {
            return false;
        }
        i += 1;
    }
    assert(a@ =~= b@);
    true
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

// The memo of one chunk column: h[j] = entry j equals the text of x or of y, for every entry j <= mx.
pub fn memo_eq(v: &StrCol, mx: u32, x: &str, y: &str) -> (h: Vec<bool>)
    requires
        (mx as int) < v.ents@.len(),
    ensures
        h@.len() == mx as int + 1,
        forall|j: int| 0 <= j <= mx ==> #[trigger] h@[j] == (v.ents@[j] == x@ || v.ents@[j] == y@),
{
    let mut h: Vec<bool> = Vec::new();
    let mut j: u64 = 0;
    while j <= mx as u64
        invariant
            j <= mx as u64 + 1,
            h@.len() == j,
            (mx as int) < v.ents@.len(),
            forall|q: int| 0 <= q < j ==> #[trigger] h@[q] == (v.ents@[q] == x@ || v.ents@[q] == y@),
        decreases mx as u64 + 1 - j,
    {
        let e = str_ent(v, j as usize);
        let hit = eq_text(e, x) || eq_text(e, y);
        h.push(hit);
        j += 1;
    }
    h
}
// AGENT_HELPERS_END
// AGENT_INIT_START
    QAcc { cnt: 0, sum: 0 }
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
    let ms = max_sel(c.s.sel);
    let mg = max_sel(c.g.sel);
    proof {
        let r1 = choose|r: int| 0 <= r < c.s.sel@.len() && c.s.sel@[r] == ms;
        let r2 = choose|r: int| 0 <= r < c.g.sel@.len() && c.g.sel@[r] == mg;
        assert((c.s.sel@[r1] as int) < c.s.ents@.len());
        assert((c.g.sel@[r2] as int) < c.g.ents@.len());
    }
    let hs = memo_eq(&c.s, ms, p.x.as_str(), p.x.as_str());
    let hg = memo_eq(&c.g, mg, p.y.as_str(), p.z.as_str());
    let mut r: usize = 0;
    while r < c.len
        invariant
            chunk_ok_t(c),
            t == stream_table_t(c.sid),
            r <= c.len,
            hs@.len() == ms as int + 1,
            hg@.len() == mg as int + 1,
            forall|q: int| 0 <= q < c.len ==> c.s.sel@[q] <= ms,
            forall|q: int| 0 <= q < c.len ==> c.g.sel@[q] <= mg,
            forall|j: int| 0 <= j <= ms ==> #[trigger] hs@[j] == (c.s.ents@[j] == p.x@ || c.s.ents@[j] == p.x@),
            forall|j: int| 0 <= j <= mg ==> #[trigger] hg@[j] == (c.g.ents@[j] == p.y@ || c.g.ents@[j] == p.z@),
            st_val(s, ()) == agg_plus(s0, agg_rng(&t, c.off as int, c.off + r, (), p)),
        decreases c.len - r,
    {
        let js = c.s.sel[r] as usize;
        let jg = c.g.sel[r] as usize;
        let hit = hs[js] && hg[jg];
        let m = c.m[r];
        proof {
            lemma_agg_step(&t, c.off as int, c.off + r + 1, (), p);
            assert(c.s.ents@[js as int] == t.s@[c.off + r]@);
            assert(c.g.ents@[jg as int] == t.g@[c.off + r]@);
            assert(t.m@[c.off + r] == m);
            assert(hit == row_hit(&t, c.off + r, &params_canon(p).x, &params_canon(p).y, &params_canon(p).z));
        }
        if hit {
            s.cnt = match s.cnt.checked_add(1) {
                Some(v) => v,
                None => return false,
            };
            s.sum = match s.sum.checked_add(m as i128) {
                Some(v) => v,
                None => return false,
            };
        }
        r += 1;
    }
    proof {
        assert forall|k: Key| #[trigger] st_val(s, k) == agg_plus(st_val(old(s), k), agg_rng(&t, c.off as int, c.off + c.len, k, p)) by {}
    }
    true
// AGENT_STEP_END
// AGENT_MERGE_START
    let cnt = match a.cnt.checked_add(b.cnt) {
        Some(v) => v,
        None => return None,
    };
    let sum = match a.sum.checked_add(b.sum) {
        Some(v) => v,
        None => return None,
    };
    Some(QAcc { cnt, sum })
// AGENT_MERGE_END
// AGENT_FINISH_START
    proof {
        lemma_agg_total(&t@, (), p);
        assert(st_val(&s, ()) == agg_rng(&t@, 0, t@.n as int, (), p));
    }
    let mut res: Vec<OutRow> = Vec::new();
    if s.cnt > 0 {
        res.push(OutRow { c: s.cnt, sm: Some(s.sum) });
    } else {
        res.push(OutRow { c: 0, sm: None });
    }
    proof {
        assert(res@.len() == 1);
        assert(res@[0] == res@[0]);
    }
    Some(res)
// AGENT_FINISH_END
