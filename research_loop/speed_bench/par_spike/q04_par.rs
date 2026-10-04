use vstd::hash_map::HashMapWithView;
use vstd::prelude::*;
use vstd::thread::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;
pub const DENSE: usize = 1024;

// ---- identical to proved/q04_group_count.rs ----
pub struct Cols {
    pub n: usize,
    pub k: Vec<u32>,
}

impl Cols {
    #[verifier::external_body]
    pub exec fn key_exec(&self, i: usize) -> (res: u32)
        requires
            i < self.n,
        ensures
            res == self.k[i as int],
    {
        self.k[i]
    }
}

pub struct Groups {
    pub seen: Vec<bool>,
    pub vals: Vec<u64>,
    pub overflow: HashMapWithView<u32, u64>,
}

pub open spec fn valid_cols(cols: &Cols) -> bool {
    &&& cols.n <= LEMMA_MAX_ROWS
    &&& cols.k.len() == cols.n
}

pub open spec fn method_spec_helper(cols: &Cols, k: int) -> Map<u32, u64>
    recommends
        0 <= k && k <= cols.n,
        valid_cols(cols),
    decreases cols.n - k,
{
    if k < cols.n {
        let tail = method_spec_helper(cols, k + 1);
        let key = cols.k[k as int];
        let prev = if tail.contains_key(key) { tail[key] } else { 0u64 };
        tail.insert(key, (prev as int + 1u64 as int) as u64)
    } else {
        Map::empty()
    }
}

pub open spec fn method_spec(cols: &Cols) -> Map<u32, u64>
    recommends
        valid_cols(cols),
{
    method_spec_helper(cols, 0)
}

pub open spec fn dense_map(seen: Seq<bool>, vals: Seq<u64>, i: int) -> Map<u32, u64>
    recommends
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        let tail = dense_map(seen, vals, i + 1);
        if seen[i] {
            tail.insert(i as u32, vals[i])
        } else {
            tail
        }
    } else {
        Map::empty()
    }
}

pub open spec fn group_view(seen: Seq<bool>, vals: Seq<u64>, over: Map<u32, u64>) -> Map<u32, u64> {
    dense_map(seen, vals, 0).union_prefer_right(over)
}

proof fn lemma_count_fits()
    ensures
        (LEMMA_MAX_ROWS as u64) < u64::MAX,
{
    assert((LEMMA_MAX_ROWS as u64) < u64::MAX) by (compute_only);
}

proof fn lemma_dense_empty(seen: Seq<bool>, vals: Seq<u64>, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        forall|t: int| i <= t < DENSE as int ==> !seen[t],
    ensures
        dense_map(seen, vals, i) =~= Map::<u32, u64>::empty(),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_empty(seen, vals, i + 1);
        assert(!seen[i]);
    }
}

proof fn lemma_dense_get(seen: Seq<bool>, vals: Seq<u64>, key: int, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        0 <= key < DENSE as int,
        i <= key,
        seen[key],
    ensures
        dense_map(seen, vals, i).contains_key(key as u32),
        dense_map(seen, vals, i)[key as u32] == vals[key],
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        if i == key {
            assert(seen[i]);
        } else {
            lemma_dense_get(seen, vals, key, i + 1);
        }
    }
}

proof fn lemma_dense_absent(seen: Seq<bool>, vals: Seq<u64>, key: int, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        0 <= key < DENSE as int,
        !seen[key],
    ensures
        !dense_map(seen, vals, i).contains_key(key as u32),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_absent(seen, vals, key, i + 1);
    }
}

proof fn lemma_dense_keys_below(seen: Seq<bool>, vals: Seq<u64>, key: u32, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        key >= DENSE as u32,
    ensures
        !dense_map(seen, vals, i).contains_key(key),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_keys_below(seen, vals, key, i + 1);
    }
}



// ---- Seq-level spec (same fold), per-key counts, concatenation ----
pub open spec fn fold(s: Seq<u32>) -> Map<u32, u64>
    decreases s.len(),
{
    if s.len() > 0 {
        let tail = fold(s.skip(1));
        let key = s[0];
        let prev = if tail.contains_key(key) { tail[key] } else { 0u64 };
        tail.insert(key, (prev as int + 1u64 as int) as u64)
    } else {
        Map::empty()
    }
}

pub open spec fn cnt(s: Seq<u32>, key: u32) -> int
    decreases s.len(),
{
    if s.len() > 0 {
        cnt(s.skip(1), key) + if s[0] == key { 1int } else { 0int }
    } else {
        0
    }
}

proof fn lemma_helper_is_fold(cols: &Cols, k: int)
    requires
        valid_cols(cols),
        0 <= k <= cols.n,
    ensures
        method_spec_helper(cols, k) == fold(cols.k@.skip(k)),
    decreases cols.n - k,
{
    if k < cols.n {
        lemma_helper_is_fold(cols, k + 1);
        assert(cols.k@.skip(k).skip(1) =~= cols.k@.skip(k + 1));
    }
}

proof fn lemma_cnt_le_len(s: Seq<u32>, key: u32)
    ensures
        0 <= cnt(s, key) <= s.len(),
    decreases s.len(),
{
    if s.len() > 0 {
        lemma_cnt_le_len(s.skip(1), key);
    }
}

proof fn lemma_cnt_add(a: Seq<u32>, b: Seq<u32>, key: u32)
    ensures
        cnt(a + b, key) == cnt(a, key) + cnt(b, key),
    decreases a.len(),
{
    if a.len() == 0 {
        assert(a + b =~= b);
    } else {
        lemma_cnt_add(a.skip(1), b, key);
        assert((a + b).skip(1) =~= a.skip(1) + b);
        assert((a + b)[0] == a[0]);
    }
}

proof fn lemma_cnt_push(a: Seq<u32>, x: u32, key: u32)
    ensures
        cnt(a.push(x), key) == cnt(a, key) + if x == key { 1int } else { 0int },
{
    lemma_cnt_add(a, seq![x], key);
    assert(a.push(x) =~= a + seq![x]);
    assert(seq![x].skip(1) =~= Seq::<u32>::empty());
    assert(cnt(Seq::<u32>::empty(), key) == 0);
    assert(cnt(seq![x], key) == if x == key { 1int } else { 0int });
}

proof fn lemma_fold_char(s: Seq<u32>, key: u32)
    requires
        s.len() < u64::MAX,
    ensures
        fold(s).contains_key(key) <==> cnt(s, key) > 0,
        fold(s).contains_key(key) ==> fold(s)[key] as int == cnt(s, key),
    decreases s.len(),
{
    if s.len() > 0 {
        lemma_fold_char(s.skip(1), key);
        lemma_fold_char(s.skip(1), s[0]);
        lemma_cnt_le_len(s.skip(1), s[0]);
    }
}

// ---- one worker's fold over its own chunk: dense partial arrays + a log of overflow keys ----
pub exec fn chunk_groups(cols: &Cols) -> (res: (Vec<bool>, Vec<u64>, Vec<u32>))
    requires
        valid_cols(cols),
    ensures
        res.0.len() == DENSE,
        res.1.len() == DENSE,
        forall|t: int| #![trigger res.0@[t]] #![trigger res.1@[t]]
            0 <= t < DENSE as int ==> (res.0@[t]) == (cnt(cols.k@, t as u32) > 0)
                && res.1@[t] as int == cnt(cols.k@, t as u32),
        forall|j: int| 0 <= j < res.2@.len() ==> (#[trigger] res.2@[j]) >= DENSE as u32,
        forall|key: u32| key >= DENSE as u32 ==> cnt(res.2@, key) == #[trigger] cnt(cols.k@, key),
{
    let mut seen: Vec<bool> = vec![false; DENSE];
    let mut vals: Vec<u64> = vec![0u64; DENSE];
    let mut ovk: Vec<u32> = Vec::new();
    let mut i: usize = cols.n;
    proof {
        assert(cols.k@.skip(cols.n as int) =~= Seq::<u32>::empty());
    }
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            seen.len() == DENSE,
            vals.len() == DENSE,
            forall|t: int| #![trigger seen@[t]] #![trigger vals@[t]]
                0 <= t < DENSE as int ==> (seen@[t]) == (cnt(
                    cols.k@.skip(i as int),
                    t as u32,
                ) > 0) && vals@[t] as int == cnt(cols.k@.skip(i as int), t as u32),
            forall|j: int| 0 <= j < ovk@.len() ==> (#[trigger] ovk@[j]) >= DENSE as u32,
            forall|key: u32|
                key >= DENSE as u32 ==> cnt(ovk@, key) == #[trigger] cnt(
                    cols.k@.skip(i as int),
                    key,
                ),
        decreases i,
    {
        let ghost sk1 = cols.k@.skip(i as int);
        i = i - 1;
        let key = cols.key_exec(i);
        let ghost sk = cols.k@.skip(i as int);
        proof {
            assert(sk.skip(1) =~= sk1);
            assert(sk[0] == key);
            assert forall|y: u32| cnt(sk, y) == #[trigger] cnt(sk1, y) + if key == y {
                1int
            } else {
                0int
            } by {}
        }
        if key < DENSE as u32 {
            let idx = key as usize;
            let prev = vals[idx];
            proof {
                assert(idx as int as u32 == key);
                assert(vals@[idx as int] as int == cnt(sk1, key));
                lemma_cnt_le_len(sk1, key);
                assert(sk1.len() == cols.n - i - 1);
                lemma_count_fits();
            }
            let next = prev + 1;
            seen.set(idx, true);
            vals.set(idx, next);
            proof {
                assert forall|t: int| #![trigger seen@[t]] #![trigger vals@[t]] 0 <= t < DENSE as int implies (seen@[t]) == (cnt(sk, t as u32) > 0)
                    && vals@[t] as int == cnt(sk, t as u32) by {
                    if t == idx as int {
                        assert(t as u32 == key);
                        assert(cnt(sk, key) == cnt(sk1, key) + 1);
                    } else {
                        assert(t as u32 != key);
                    }
                }
                assert forall|key2: u32| key2 >= DENSE as u32 implies cnt(ovk@, key2) == #[trigger] cnt(sk, key2) by {
                    assert(key2 != key);
                    assert(cnt(ovk@, key2) == cnt(sk1, key2));
                    assert(cnt(sk, key2) == cnt(sk1, key2));
                }
            }
        } else {
            let ghost old_ovk = ovk@;
            ovk.push(key);
            proof {
                assert forall|key2: u32| key2 >= DENSE as u32 implies cnt(ovk@, key2) == #[trigger] cnt(sk, key2) by {
                    lemma_cnt_push(old_ovk, key, key2);
                    assert(ovk@ == old_ovk.push(key));
                    assert(cnt(old_ovk, key2) == cnt(sk1, key2));
                    assert(cnt(sk, key2) == cnt(sk1, key2) + if key == key2 { 1int } else { 0int });
                }
                assert forall|t: int| #![trigger seen@[t]] #![trigger vals@[t]] 0 <= t < DENSE as int implies (seen@[t]) == (cnt(sk, t as u32) > 0)
                    && vals@[t] as int == cnt(sk, t as u32) by {
                    assert(t as u32 != key);
                }
                assert forall|j: int| 0 <= j < ovk@.len() implies (#[trigger] ovk@[j]) >= DENSE as u32 by {
                    if j < old_ovk.len() {
                        assert(ovk@[j] == old_ovk[j]);
                    }
                }
            }
        }
    }
    proof {
        assert(cols.k@.skip(0) =~= cols.k@);
    }
    (seen, vals, ovk)
}

// ---- concatenation of chunks ----
pub open spec fn cat_k(cs: Seq<Cols>, w: int) -> Seq<u32>
    decreases w,
{
    if w <= 0 {
        Seq::empty()
    } else {
        cat_k(cs, w - 1) + cs[w - 1].k@
    }
}

pub open spec fn all_valid(cs: Seq<Cols>) -> bool {
    forall|j: int| 0 <= j < cs.len() ==> valid_cols(&#[trigger] cs[j])
}

proof fn lemma_cat_len(cs: Seq<Cols>, w: int)
    requires
        all_valid(cs),
        0 <= w < cs.len(),
    ensures
        cat_k(cs, w + 1).len() == cat_k(cs, w).len() + cs[w].n,
{
}

proof fn lemma_cat_prefix_len(cs: Seq<Cols>, w1: int, w2: int)
    requires
        0 <= w1 <= w2 <= cs.len(),
    ensures
        cat_k(cs, w1).len() <= cat_k(cs, w2).len(),
    decreases w2 - w1,
{
    if w1 < w2 {
        lemma_cat_prefix_len(cs, w1 + 1, w2);
    }
}

type Part = (Cols, Vec<bool>, Vec<u64>, Vec<u32>);

pub open spec fn part_ok(c: Cols, ret: Part) -> bool {
    &&& ret.0.k@ == c.k@
    &&& ret.0.n == c.n
    &&& ret.1.len() == DENSE
    &&& ret.2.len() == DENSE
    &&& forall|t: int| #![trigger ret.1@[t]] #![trigger ret.2@[t]]
        0 <= t < DENSE as int ==> (ret.1@[t]) == (cnt(c.k@, t as u32) > 0) && ret.2@[t]
            as int == cnt(c.k@, t as u32)
    &&& forall|j: int| 0 <= j < ret.3@.len() ==> (#[trigger] ret.3@[j]) >= DENSE as u32
    &&& forall|key: u32| key >= DENSE as u32 ==> cnt(ret.3@, key) == #[trigger] cnt(c.k@, key)
}

pub open spec fn handle_ok(h: JoinHandle<Part>, c: Cols) -> bool {
    forall|ret: Part| #[trigger] h.predicate(ret) ==> part_ok(c, ret)
}

pub open spec fn same_chunk(a: Cols, b: Cols) -> bool {
    a.k@ == b.k@ && a.n == b.n
}

/// Same statement as the single-threaded ensures, for the table whose key column is the
/// concatenation of the chunks.
pub proof fn lemma_same_as_single_threaded(whole: &Cols, k: Seq<u32>)
    requires
        valid_cols(whole),
        whole.k@ == k,
    ensures
        method_spec(whole) == fold(k),
{
    lemma_helper_is_fold(whole, 0);
    assert(k.skip(0) =~= k);
}

#[verifier::exec_allows_no_decreases_clause]
pub exec fn par_run_query(chunks: &mut Vec<Cols>) -> (res: Groups)
    requires
        all_valid(old(chunks)@),
        cat_k(old(chunks)@, old(chunks)@.len() as int).len() <= LEMMA_MAX_ROWS,
    ensures
        final(chunks)@.len() == old(chunks)@.len(),
        forall|j: int|
            0 <= j < old(chunks)@.len() ==> same_chunk(#[trigger] final(chunks)@[j], old(chunks)@[j]),
        res.seen.len() == DENSE,
        res.vals.len() == DENSE,
        group_view(res.seen@, res.vals@, res.overflow@) == fold(
            cat_k(old(chunks)@, old(chunks)@.len() as int),
        ),
{
    broadcast use vstd::std_specs::hash::axiom_u32_obeys_hash_table_key_model;
    let ghost orig = chunks@;
    let w = chunks.len();
    let mut handles: Vec<JoinHandle<Part>> = Vec::new();
    while chunks.len() > 0
        invariant
            all_valid(orig),
            chunks@ == orig.subrange(0, chunks@.len() as int),
            handles@.len() + chunks@.len() == w,
            w == orig.len(),
            forall|m: int|
                0 <= m < handles@.len() ==> handle_ok(#[trigger] handles@[m], orig[w as int - 1 - m]),
        decreases chunks.len(),
    {
        let c = chunks.pop().unwrap();
        let ghost cg = c;
        proof {
            assert(orig[chunks@.len() as int] == c);
            assert(valid_cols(&c));
        }
        let h = spawn(
            move || -> (r: Part)
                requires
                    valid_cols(&c),
                ensures
                    part_ok(c, r),
                {
                    let (s, v, o) = chunk_groups(&c);
                    (c, s, v, o)
                },
        );
        proof {
            assert(handle_ok(h, cg));
        }
        let ghost old_handles = handles@;
        handles.push(h);
        proof {
            let m = handles@.len() as int - 1;
            assert(handles@[m] == h);
            assert(orig[w as int - 1 - m] == cg);
            assert forall|m2: int| 0 <= m2 < handles@.len() implies handle_ok(
                #[trigger] handles@[m2],
                orig[w as int - 1 - m2],
            ) by {
                if m2 < m {
                    assert(handles@[m2] == old_handles[m2]);
                }
            }
        }
    }
    let mut acc_seen: Vec<bool> = vec![false; DENSE];
    let mut acc_vals: Vec<u64> = vec![0u64; DENSE];
    let mut over = HashMapWithView::<u32, u64>::new();
    let mut joined: usize = 0;
    let mut out: Vec<Cols> = Vec::new();
    proof {
        assert(cat_k(orig, 0) =~= Seq::<u32>::empty());
    }
    while handles.len() > 0
        invariant
            all_valid(orig),
            w == orig.len(),
            cat_k(orig, w as int).len() <= LEMMA_MAX_ROWS,
            joined + handles@.len() == w,
            out@.len() == joined,
            forall|j: int| 0 <= j < joined ==> same_chunk(#[trigger] out@[j], orig[j]),
            forall|m: int|
                0 <= m < handles@.len() ==> handle_ok(#[trigger] handles@[m], orig[w as int - 1 - m]),
            acc_seen.len() == DENSE,
            acc_vals.len() == DENSE,
            forall|t: int| #![trigger acc_seen@[t]] #![trigger acc_vals@[t]]
                0 <= t < DENSE as int ==> (acc_seen@[t]) == (cnt(
                    cat_k(orig, joined as int),
                    t as u32,
                ) > 0) && acc_vals@[t] as int == cnt(cat_k(orig, joined as int), t as u32),
            forall|key: u32|
                key >= DENSE as u32 ==> (over@.contains_key(key) <==> #[trigger] cnt(
                    cat_k(orig, joined as int),
                    key,
                ) > 0) && (over@.contains_key(key) ==> over@[key] as int == cnt(
                    cat_k(orig, joined as int),
                    key,
                )),
            forall|key: u32| key < DENSE as u32 ==> !(#[trigger] over@.contains_key(key)),
        decreases handles.len(),
    {
        let ghost old_handles = handles@;
        let h = handles.pop().unwrap();
        let ghost m = handles@.len() as int;
        assert(h == old_handles[m]);
        assert(handle_ok(h, orig[w as int - 1 - m]));
        let r = match h.join() {
            Ok(r) => r,
            Err(_) => {
                // vstd's join returns Err only if a worker panicked; the trusted wrapper does
                // not say workers cannot panic, so the proof cannot rule this branch out.
                loop {}
            },
        };
        let ghost jj = joined as int;
        proof {
            assert(part_ok(orig[w as int - 1 - m], r));
            assert(w as int - 1 - m == jj);
            lemma_cat_len(orig, jj);
            assert(cat_k(orig, jj + 1) == cat_k(orig, jj) + orig[jj].k@);
            lemma_cat_prefix_len(orig, jj + 1, w as int);
            assert forall|key: u32| cnt(cat_k(orig, jj + 1), key) == #[trigger] cnt(cat_k(orig, jj), key)
                + cnt(orig[jj].k@, key) by {
                lemma_cat_len(orig, jj);
                lemma_cnt_add(cat_k(orig, jj), orig[jj].k@, key);
            }
        }
        let (c, ps, pv, po) = r;
        // merge the dense partial arrays
        let ghost acc_seen0 = acc_seen@;
        let ghost acc_vals0 = acc_vals@;
        let mut t: usize = 0;
        while t < DENSE
            invariant
                t <= DENSE,
                acc_seen.len() == DENSE,
                acc_vals.len() == DENSE,
                ps.len() == DENSE,
                pv.len() == DENSE,
                acc_seen0.len() == DENSE,
                acc_vals0.len() == DENSE,
                cat_k(orig, jj + 1).len() <= LEMMA_MAX_ROWS,
                jj == joined as int,
                forall|key: u32| cnt(cat_k(orig, jj + 1), key) == #[trigger] cnt(cat_k(orig, jj), key)
                    + cnt(orig[jj].k@, key),
                forall|t2: int| #![trigger ps@[t2]] #![trigger pv@[t2]]
                    0 <= t2 < DENSE as int ==> (ps@[t2]) == (cnt(c.k@, t2 as u32) > 0)
                        && pv@[t2] as int == cnt(c.k@, t2 as u32),
                c.k@ == orig[jj].k@,
                forall|t2: int|
                    0 <= t2 < DENSE as int ==> (#[trigger] acc_seen0[t2]) == (cnt(
                        cat_k(orig, jj),
                        t2 as u32,
                    ) > 0) && acc_vals0[t2] as int == cnt(cat_k(orig, jj), t2 as u32),
                forall|t2: int| #![trigger acc_seen@[t2]] #![trigger acc_vals@[t2]]
                    0 <= t2 < t as int ==> (acc_seen@[t2]) == (cnt(
                        cat_k(orig, jj + 1),
                        t2 as u32,
                    ) > 0) && acc_vals@[t2] as int == cnt(cat_k(orig, jj + 1), t2 as u32),
                forall|t2: int|
                    t as int <= t2 < DENSE as int ==> acc_seen@[t2] == acc_seen0[t2] && acc_vals@[t2]
                        == acc_vals0[t2],
            decreases DENSE - t,
        {
            proof {
                let tk = t as u32;
                assert(t as int as u32 == tk);
                assert(ps@[t as int] == (cnt(c.k@, tk) > 0));
                assert(acc_vals0[t as int] as int == cnt(cat_k(orig, jj), tk));
                assert(pv@[t as int] as int == cnt(c.k@, tk));
                assert(cnt(cat_k(orig, jj + 1), tk) == cnt(cat_k(orig, jj), tk) + cnt(orig[jj].k@, tk));
                lemma_cnt_le_len(cat_k(orig, jj + 1), tk);
                assert(cnt(cat_k(orig, jj + 1), tk) == acc_vals0[t as int] as int + pv@[t as int] as int);
                assert(acc_vals0[t as int] as int + pv@[t as int] as int <= LEMMA_MAX_ROWS);
                lemma_count_fits();
            }
            let a = acc_vals[t];
            let b = pv[t];
            let sa = acc_seen[t];
            let sb = ps[t];
            acc_vals.set(t, a + b);
            acc_seen.set(t, sa || sb);
            t = t + 1;
        }
        // replay the worker's overflow-key log into the shared overflow map
        let mut x: usize = 0;
        let ghost cat0 = cat_k(orig, jj);
        while x < po.len()
            invariant
                x <= po.len(),
                jj == joined as int,
                cat0 == cat_k(orig, jj),
                cat_k(orig, jj + 1).len() <= LEMMA_MAX_ROWS,
                forall|j: int| 0 <= j < po@.len() ==> (#[trigger] po@[j]) >= DENSE as u32,
                forall|key: u32|
                    key >= DENSE as u32 ==> cnt(po@, key) == #[trigger] cnt(c.k@, key),
                c.k@ == orig[jj].k@,
                forall|key: u32| cnt(cat_k(orig, jj + 1), key) == #[trigger] cnt(cat_k(orig, jj), key)
                    + cnt(orig[jj].k@, key),
                forall|key: u32|
                    key >= DENSE as u32 ==> (over@.contains_key(key) <==> #[trigger] (cnt(cat0, key)
                        + cnt(po@.subrange(0, x as int), key)) > 0) && (over@.contains_key(key) ==> over@[key]
                        as int == cnt(cat0, key) + cnt(po@.subrange(0, x as int), key)),
                forall|key: u32| key < DENSE as u32 ==> !(#[trigger] over@.contains_key(key)),
            decreases po.len() - x,
        {
            let key = po[x];
            let ghost before = over@;
            proof {
                assert(po@[x as int] == key);
                assert(key >= DENSE as u32);
                assert(cnt(po@, key) == cnt(c.k@, key));
            }
            let prev = match over.get(&key) {
                Some(v) => *v,
                None => 0u64,
            };
            proof {
                let sub = po@.subrange(0, x as int);
                lemma_cnt_le_len(cat_k(orig, jj + 1), key);
                lemma_cnt_le_len(po@, key);
                assert(sub.push(po@[x as int]) =~= po@.subrange(0, x as int + 1));
                assert forall|key2: u32| cnt(sub.push(key), key2) == #[trigger] cnt(sub, key2) + if key == key2 {
                    1int
                } else {
                    0int
                } by {
                    lemma_cnt_push(sub, key, key2);
                }
                // monotone bound: cnt(cat0)+cnt(sub) + 1 <= cnt(cat0)+cnt(po) = cnt(cat(jj+1)) <= MAX
                lemma_cnt_prefix(po@, x as int, key);
                lemma_count_fits();
                assert(cnt(cat_k(orig, jj + 1), key) == cnt(cat0, key) + cnt(po@, key));
                if over@.contains_key(key) {
                    assert(prev as int == cnt(cat0, key) + cnt(sub, key));
                } else {
                    assert(prev == 0);
                }
            }
            let next = prev + 1;
            over.insert(key, next);
            proof {
                let sub = po@.subrange(0, x as int);
                assert forall|key2: u32| key2 >= DENSE as u32 implies (over@.contains_key(key2) <==> #[trigger] (cnt(
                    cat0,
                    key2,
                ) + cnt(po@.subrange(0, x as int + 1), key2)) > 0) && (over@.contains_key(key2)
                    ==> over@[key2] as int == cnt(cat0, key2) + cnt(po@.subrange(0, x as int + 1), key2)) by {
                    assert(po@.subrange(0, x as int + 1) =~= sub.push(key));
                    lemma_cnt_le_len(cat0, key2);
                    lemma_cnt_le_len(sub, key2);
                    lemma_cnt_push(sub, key, key2);
                    assert(over@ == before.insert(key, next));
                    let tot_old = cnt(cat0, key2) + cnt(sub, key2);
                    assert(before.contains_key(key2) <==> tot_old > 0);
                    assert(before.contains_key(key2) ==> before[key2] as int == tot_old);
                    if key2 == key {
                        assert(over@.contains_key(key2));
                        assert(over@[key2] == next);
                        if before.contains_key(key) {
                            assert(prev == before[key]);
                        } else {
                            assert(prev == 0);
                            assert(tot_old == 0);
                        }
                    }
                }
                assert forall|key2: u32| key2 < DENSE as u32 implies !(#[trigger] over@.contains_key(key2)) by {
                    assert(key2 != key);
                }
            }
            x = x + 1;
        }
        proof {
            assert(po@.subrange(0, po@.len() as int) =~= po@);
            assert forall|key: u32| key >= DENSE as u32 implies (over@.contains_key(key) <==> #[trigger] cnt(
                cat_k(orig, jj + 1),
                key,
            ) > 0) && (over@.contains_key(key) ==> over@[key] as int == cnt(cat_k(orig, jj + 1), key)) by {
                assert(x == po.len());
                assert(po@.subrange(0, x as int) == po@);
                assert(cnt(po@, key) == cnt(c.k@, key));
                assert(cnt(cat_k(orig, jj + 1), key) == cnt(cat_k(orig, jj), key) + cnt(orig[jj].k@, key));
            }
        }
        out.push(c);
        joined = joined + 1;
        proof {
            assert forall|j: int| 0 <= j < joined implies same_chunk(#[trigger] out@[j], orig[j]) by {
                if j < joined - 1 {
                }
            }
        }
    }
    *chunks = out;
    proof {
        assert(joined == w);
        let cat = cat_k(orig, w as int);
        assert(cat.len() <= LEMMA_MAX_ROWS);
        assert(cat.len() < u64::MAX) by {
            lemma_count_fits();
        }
        assert(cat_k(orig, joined as int) == cat);
        lemma_view_eq(acc_seen@, acc_vals@, over@, cat);
    }
    Groups { seen: acc_seen, vals: acc_vals, overflow: over }
}

proof fn lemma_view_eq(seen: Seq<bool>, vals: Seq<u64>, over: Map<u32, u64>, cat: Seq<u32>)
    requires
        seen.len() == DENSE,
        vals.len() == DENSE,
        cat.len() < u64::MAX,
        forall|t: int|
            0 <= t < DENSE as int ==> (#[trigger] seen[t]) == (cnt(cat, t as u32) > 0) && vals[t]
                as int == cnt(cat, t as u32),
        forall|key: u32|
            key >= DENSE as u32 ==> (over.contains_key(key) <==> #[trigger] cnt(cat, key) > 0) && (
            over.contains_key(key) ==> over[key] as int == cnt(cat, key)),
        forall|key: u32| key < DENSE as u32 ==> !(#[trigger] over.contains_key(key)),
    ensures
        group_view(seen, vals, over) == fold(cat),
{
    let gv = group_view(seen, vals, over);
    let f = fold(cat);
    assert forall|key: u32| #![trigger gv.contains_key(key)] gv.contains_key(key) == f.contains_key(key) && (
    gv.contains_key(key) ==> gv[key] == f[key]) by {
        lemma_fold_char(cat, key);
        if key < DENSE as u32 {
            assert(seen[key as int] == (cnt(cat, key) > 0));
            assert(!over.contains_key(key));
            if seen[key as int] {
                lemma_dense_get(seen, vals, key as int, 0);
            } else {
                lemma_dense_absent(seen, vals, key as int, 0);
            }
        } else {
            lemma_dense_keys_below(seen, vals, key, 0);
        }
    }
    assert(gv =~= f);
}

// cnt of a prefix is at most cnt of the whole
proof fn lemma_cnt_prefix(s: Seq<u32>, x: int, key: u32)
    requires
        0 <= x < s.len(),
        s[x] == key,
    ensures
        cnt(s.subrange(0, x), key) + 1 <= cnt(s, key),
{
    let p = s.subrange(0, x);
    let q = s.subrange(x, s.len() as int);
    assert(s =~= p + q);
    lemma_cnt_add(p, q, key);
    assert(q.skip(1) =~= q.skip(1));
    lemma_cnt_le_len(q.skip(1), key);
    assert(q[0] == key);
}

}

fn env_usize(key: &str) -> usize {
    std::env::var(key).unwrap().parse().unwrap()
}

fn main() {
    let n = env_usize("SPEED_ROWS");
    let w = env_usize("SPEED_THREADS");
    let mut chunks: Vec<Cols> = Vec::new();
    for j in 0..w {
        let lo = n * j / w;
        let hi = n * (j + 1) / w;
        let mut k = Vec::with_capacity(hi - lo);
        for i in lo..hi {
            k.push((i % 32) as u32);
        }
        chunks.push(Cols { n: hi - lo, k });
    }
    for _ in 0..env_usize("SPEED_WARMUP") {
        let _ = par_run_query(&mut chunks);
    }
    let mut samples = Vec::new();
    let mut last = None;
    for _ in 0..env_usize("SPEED_RUNS") {
        let t0 = std::time::Instant::now();
        last = Some(par_run_query(&mut chunks));
        samples.push(t0.elapsed().as_micros());
    }
    samples.sort();
    let groups = last.unwrap();
    let mut pairs = Vec::new();
    for key in 0..32u32 {
        if groups.seen[key as usize] {
            pairs.push((key, groups.vals[key as usize]));
        }
    }
    println!("OVERFLOW:{}", groups.overflow.len());
    println!("RESULT:{pairs:?}");
    println!("SAMPLES_US:{samples:?}");
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
