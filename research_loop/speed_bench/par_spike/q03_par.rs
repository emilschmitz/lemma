use vstd::hash_map::HashMapWithView;
use vstd::prelude::*;
use vstd::thread::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;
pub const DENSE: usize = 1024;

// ---- identical to proved/q03_group_sum.rs ----
pub struct Cols {
    pub n: usize,
    pub k: Vec<u32>,
    pub amount: Vec<u64>,
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

    pub open spec fn get_amount(self, i: int) -> u64 {
        self.amount[i as int]
    }

    #[verifier::external_body]
    pub exec fn get_amount_exec(&self, i: usize) -> (res: u64)
        requires
            i < self.n,
        ensures
            res == self.get_amount(i as int),
    {
        self.amount[i]
    }
}

pub struct Groups {
    pub seen: Vec<bool>,
    pub vals: Vec<u128>,
    pub overflow: HashMapWithView<u32, u128>,
}

pub open spec fn valid_cols(cols: &Cols) -> bool {
    &&& cols.n <= LEMMA_MAX_ROWS
    &&& cols.k.len() == cols.n
    &&& cols.amount.len() == cols.n
}

pub open spec fn method_spec_helper(cols: &Cols, k: int) -> Map<u32, u128>
    recommends
        0 <= k && k <= cols.n,
        valid_cols(cols),
    decreases cols.n - k,
{
    if k < cols.n {
        let tail = method_spec_helper(cols, k + 1);
        let key = cols.k[k as int];
        let prev = if tail.contains_key(key) { tail[key] } else { 0u128 };
        tail.insert(key, (prev as int + ((cols.get_amount(k) as int)) as u64 as int) as u128)
    } else {
        Map::empty()
    }
}

pub open spec fn method_spec(cols: &Cols) -> Map<u32, u128>
    recommends
        valid_cols(cols),
{
    method_spec_helper(cols, 0)
}

pub open spec fn dense_map(seen: Seq<bool>, vals: Seq<u128>, i: int) -> Map<u32, u128>
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

pub open spec fn group_view(seen: Seq<bool>, vals: Seq<u128>, over: Map<u32, u128>) -> Map<u32, u128> {
    dense_map(seen, vals, 0).union_prefer_right(over)
}

proof fn lemma_dense_empty(seen: Seq<bool>, vals: Seq<u128>, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        forall|t: int| i <= t < DENSE as int ==> !seen[t],
    ensures
        dense_map(seen, vals, i) =~= Map::<u32, u128>::empty(),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_empty(seen, vals, i + 1);
        assert(!seen[i]);
    }
}

proof fn lemma_dense_get(seen: Seq<bool>, vals: Seq<u128>, key: int, i: int)
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

proof fn lemma_dense_absent(seen: Seq<bool>, vals: Seq<u128>, key: int, i: int)
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

proof fn lemma_dense_keys_below(seen: Seq<bool>, vals: Seq<u128>, key: u32, i: int)
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





proof fn lemma_rows_fit()
    ensures
        (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX,
{
    assert((LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX) by (compute_only);
}

// ---- Seq-level spec (same fold), per-key counts and sums, concatenation ----
pub open spec fn fold(k: Seq<u32>, a: Seq<u64>) -> Map<u32, u128>
    decreases k.len(),
{
    if k.len() > 0 && a.len() == k.len() {
        let tail = fold(k.skip(1), a.skip(1));
        let key = k[0];
        let prev = if tail.contains_key(key) { tail[key] } else { 0u128 };
        tail.insert(key, (prev as int + ((a[0] as int)) as u64 as int) as u128)
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

pub open spec fn sm(k: Seq<u32>, a: Seq<u64>, key: u32) -> int
    decreases k.len(),
{
    if k.len() > 0 && a.len() == k.len() {
        sm(k.skip(1), a.skip(1), key) + if k[0] == key { a[0] as int } else { 0int }
    } else {
        0
    }
}

proof fn lemma_helper_is_fold(cols: &Cols, k: int)
    requires
        valid_cols(cols),
        0 <= k <= cols.n,
    ensures
        method_spec_helper(cols, k) == fold(cols.k@.skip(k), cols.amount@.skip(k)),
    decreases cols.n - k,
{
    if k < cols.n {
        lemma_helper_is_fold(cols, k + 1);
        assert(cols.k@.skip(k).skip(1) =~= cols.k@.skip(k + 1));
        assert(cols.amount@.skip(k).skip(1) =~= cols.amount@.skip(k + 1));
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

proof fn lemma_sm_add(k1: Seq<u32>, a1: Seq<u64>, k2: Seq<u32>, a2: Seq<u64>, key: u32)
    requires
        k1.len() == a1.len(),
        k2.len() == a2.len(),
    ensures
        sm(k1 + k2, a1 + a2, key) == sm(k1, a1, key) + sm(k2, a2, key),
    decreases k1.len(),
{
    if k1.len() == 0 {
        assert(k1 + k2 =~= k2);
        assert(a1 + a2 =~= a2);
    } else {
        lemma_sm_add(k1.skip(1), a1.skip(1), k2, a2, key);
        assert((k1 + k2).skip(1) =~= k1.skip(1) + k2);
        assert((a1 + a2).skip(1) =~= a1.skip(1) + a2);
        assert((k1 + k2)[0] == k1[0]);
        assert((a1 + a2)[0] == a1[0]);
    }
}

proof fn lemma_sm_push(k: Seq<u32>, a: Seq<u64>, x: u32, v: u64, key: u32)
    requires
        k.len() == a.len(),
    ensures
        sm(k.push(x), a.push(v), key) == sm(k, a, key) + if x == key { v as int } else { 0int },
{
    lemma_sm_add(k, a, seq![x], seq![v], key);
    assert(k.push(x) =~= k + seq![x]);
    assert(a.push(v) =~= a + seq![v]);
    assert(seq![x].skip(1) =~= Seq::<u32>::empty());
    assert(seq![v].skip(1) =~= Seq::<u64>::empty());
    assert(sm(Seq::<u32>::empty(), Seq::<u64>::empty(), key) == 0);
    assert(sm(seq![x], seq![v], key) == if x == key { v as int } else { 0int });
}

// sm <= cnt * u64::MAX, hence fits u128 when the table is under the row cap
proof fn lemma_sm_bound(k: Seq<u32>, a: Seq<u64>, key: u32)
    requires
        k.len() == a.len(),
    ensures
        0 <= sm(k, a, key) <= cnt(k, key) * (u64::MAX as int),
    decreases k.len(),
{
    if k.len() > 0 {
        lemma_sm_bound(k.skip(1), a.skip(1), key);
        lemma_cnt_le_len(k.skip(1), key);
        if k[0] == key {
            assert(a[0] as int <= u64::MAX as int);
            assert((cnt(k.skip(1), key) + 1) * (u64::MAX as int) == cnt(k.skip(1), key) * (u64::MAX as int)
                + u64::MAX as int) by (nonlinear_arith);
        }
    }
}

proof fn lemma_sm_zero(k: Seq<u32>, a: Seq<u64>, key: u32)
    requires
        k.len() == a.len(),
        cnt(k, key) == 0,
    ensures
        sm(k, a, key) == 0,
    decreases k.len(),
{
    if k.len() > 0 {
        lemma_cnt_le_len(k.skip(1), key);
        lemma_sm_zero(k.skip(1), a.skip(1), key);
    }
}

proof fn lemma_sm_fits(k: Seq<u32>, a: Seq<u64>, key: u32)
    requires
        k.len() == a.len(),
        k.len() <= LEMMA_MAX_ROWS,
    ensures
        0 <= sm(k, a, key) <= u128::MAX,
{
    lemma_sm_bound(k, a, key);
    lemma_cnt_le_len(k, key);
    lemma_rows_fit();
    let c = cnt(k, key);
    assert(c * (u64::MAX as int) <= (LEMMA_MAX_ROWS as int) * (u64::MAX as int)) by (nonlinear_arith)
        requires
            0 <= c <= LEMMA_MAX_ROWS,
    ;
}

// nonneg sm of a prefix plus the next matching element is at most sm of the whole
proof fn lemma_sm_prefix(k: Seq<u32>, a: Seq<u64>, x: int, key: u32)
    requires
        k.len() == a.len(),
        0 <= x < k.len(),
        k[x] == key,
    ensures
        sm(k.subrange(0, x), a.subrange(0, x), key) + a[x] as int <= sm(k, a, key),
        cnt(k.subrange(0, x), key) + 1 <= cnt(k, key),
{
    let p = k.subrange(0, x);
    let q = k.subrange(x, k.len() as int);
    let pa = a.subrange(0, x);
    let qa = a.subrange(x, a.len() as int);
    assert(k =~= p + q);
    assert(a =~= pa + qa);
    lemma_sm_add(p, pa, q, qa, key);
    lemma_cnt_add(p, q, key);
    lemma_sm_bound(q.skip(1), qa.skip(1), key);
    lemma_cnt_le_len(q.skip(1), key);
    assert(q[0] == key);
    assert(qa[0] == a[x]);
}

proof fn lemma_fold_char(k: Seq<u32>, a: Seq<u64>, key: u32)
    requires
        k.len() == a.len(),
        k.len() <= LEMMA_MAX_ROWS,
    ensures
        fold(k, a).contains_key(key) <==> cnt(k, key) > 0,
        fold(k, a).contains_key(key) ==> fold(k, a)[key] as int == sm(k, a, key),
    decreases k.len(),
{
    if k.len() > 0 {
        lemma_fold_char(k.skip(1), a.skip(1), key);
        lemma_fold_char(k.skip(1), a.skip(1), k[0]);
        lemma_sm_fits(k, a, k[0]);
        lemma_cnt_le_len(k.skip(1), k[0]);
        lemma_sm_bound(k.skip(1), a.skip(1), k[0]);
        if cnt(k.skip(1), k[0]) == 0 {
            lemma_sm_zero(k.skip(1), a.skip(1), k[0]);
        }
        assert(sm(k, a, k[0]) == sm(k.skip(1), a.skip(1), k[0]) + a[0] as int);
        assert(cnt(k, k[0]) == cnt(k.skip(1), k[0]) + 1);
    }
}

// ---- one worker's fold over its own chunk: dense partial arrays + a log of overflow rows ----
pub exec fn chunk_groups(cols: &Cols) -> (res: (Vec<bool>, Vec<u128>, Vec<u32>, Vec<u64>))
    requires
        valid_cols(cols),
    ensures
        res.0.len() == DENSE,
        res.1.len() == DENSE,
        res.2.len() == res.3.len(),
        forall|t: int|
            #![trigger res.0@[t]]
            #![trigger res.1@[t]]
            0 <= t < DENSE as int ==> res.0@[t] == (cnt(cols.k@, t as u32) > 0) && res.1@[t] as int
                == sm(cols.k@, cols.amount@, t as u32),
        forall|j: int| 0 <= j < res.2@.len() ==> (#[trigger] res.2@[j]) >= DENSE as u32,
        forall|key: u32|
            key >= DENSE as u32 ==> (cnt(res.2@, key) == #[trigger] cnt(cols.k@, key) && sm(
                res.2@,
                res.3@,
                key,
            ) == sm(cols.k@, cols.amount@, key)),
{
    let mut seen: Vec<bool> = vec![false; DENSE];
    let mut vals: Vec<u128> = vec![0u128; DENSE];
    let mut ovk: Vec<u32> = Vec::new();
    let mut ova: Vec<u64> = Vec::new();
    let mut i: usize = cols.n;
    proof {
        assert(cols.k@.skip(cols.n as int) =~= Seq::<u32>::empty());
        assert(cols.amount@.skip(cols.n as int) =~= Seq::<u64>::empty());
    }
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            seen.len() == DENSE,
            vals.len() == DENSE,
            ovk.len() == ova.len(),
            forall|t: int|
                #![trigger seen@[t]]
                #![trigger vals@[t]]
                0 <= t < DENSE as int ==> seen@[t] == (cnt(cols.k@.skip(i as int), t as u32) > 0)
                    && vals@[t] as int == sm(
                    cols.k@.skip(i as int),
                    cols.amount@.skip(i as int),
                    t as u32,
                ),
            forall|j: int| 0 <= j < ovk@.len() ==> (#[trigger] ovk@[j]) >= DENSE as u32,
            forall|key: u32|
                key >= DENSE as u32 ==> cnt(ovk@, key) == #[trigger] cnt(cols.k@.skip(i as int), key),
            forall|key: u32|
                key >= DENSE as u32 ==> sm(ovk@, ova@, key) == #[trigger] sm(
                    cols.k@.skip(i as int),
                    cols.amount@.skip(i as int),
                    key,
                ),
        decreases i,
    {
        let ghost sk1 = cols.k@.skip(i as int);
        let ghost sa1 = cols.amount@.skip(i as int);
        i = i - 1;
        let key = cols.key_exec(i);
        let a = cols.get_amount_exec(i);
        let ghost sk = cols.k@.skip(i as int);
        let ghost sa = cols.amount@.skip(i as int);
        proof {
            assert(sk.skip(1) =~= sk1);
            assert(sa.skip(1) =~= sa1);
            assert(sk[0] == key);
            assert(sa[0] == a);
            assert(sk.len() == sa.len());
            assert forall|y: u32| cnt(sk, y) == #[trigger] cnt(sk1, y) + if key == y {
                1int
            } else {
                0int
            } by {}
            assert forall|y: u32| sm(sk, sa, y) == #[trigger] sm(sk1, sa1, y) + if key == y {
                a as int
            } else {
                0int
            } by {}
        }
        if key < DENSE as u32 {
            let idx = key as usize;
            let prev = vals[idx];
            proof {
                assert(idx as int as u32 == key);
                assert(seen@[idx as int] == (cnt(sk1, key) > 0));
                assert(vals@[idx as int] as int == sm(sk1, sa1, key));
                lemma_sm_fits(sk, sa, key);
            }
            let next = prev + (a as u128);
            let ghost before_seen = seen@;
            let ghost before_vals = vals@;
            seen.set(idx, true);
            vals.set(idx, next);
            proof {
                assert forall|t: int|
                    0 <= t < DENSE as int implies #[trigger] seen@[t] == (cnt(sk, t as u32) > 0)
                    && vals@[t] as int == sm(sk, sa, t as u32) by {
                    if t == idx as int {
                        assert(t as u32 == key);
                        assert(cnt(sk, key) == cnt(sk1, key) + 1);
                        assert(sm(sk, sa, key) == sm(sk1, sa1, key) + a as int);
                        assert(next as int == prev as int + a as int);
                        assert(seen@[t] == true);
                        assert(vals@[t] == next);
                        lemma_cnt_le_len(sk1, key);
                    } else {
                        assert(t as u32 != key);
                        assert(seen@[t] == before_seen[t]);
                        assert(vals@[t] == before_vals[t]);
                    }
                }
                assert forall|key2: u32|
                    #![trigger cnt(sk, key2)]
                    #![trigger sm(sk, sa, key2)]
                    key2 >= DENSE as u32 implies (cnt(ovk@, key2) == cnt(sk, key2) && sm(
                    ovk@,
                    ova@,
                    key2,
                ) == sm(sk, sa, key2)) by {
                    assert(key2 != key);
                    assert(cnt(ovk@, key2) == cnt(sk1, key2));
                    assert(sm(ovk@, ova@, key2) == sm(sk1, sa1, key2));
                    assert(cnt(sk, key2) == cnt(sk1, key2));
                    assert(sm(sk, sa, key2) == sm(sk1, sa1, key2));
                }
            }
        } else {
            let ghost old_ovk = ovk@;
            let ghost old_ova = ova@;
            ovk.push(key);
            ova.push(a);
            proof {
                assert forall|key2: u32|
                    #![trigger cnt(sk, key2)]
                    #![trigger sm(sk, sa, key2)]
                    key2 >= DENSE as u32 implies (cnt(ovk@, key2) == cnt(sk, key2) && sm(
                    ovk@,
                    ova@,
                    key2,
                ) == sm(sk, sa, key2)) by {
                    lemma_cnt_push(old_ovk, key, key2);
                    lemma_sm_push(old_ovk, old_ova, key, a, key2);
                    assert(ovk@ == old_ovk.push(key));
                    assert(ova@ == old_ova.push(a));
                    assert(cnt(old_ovk, key2) == cnt(sk1, key2));
                    assert(sm(old_ovk, old_ova, key2) == sm(sk1, sa1, key2));
                }
                assert forall|t: int|
                    0 <= t < DENSE as int implies #[trigger] seen@[t] == (cnt(sk, t as u32) > 0)
                    && vals@[t] as int == sm(sk, sa, t as u32) by {
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
        assert(cols.amount@.skip(0) =~= cols.amount@);
    }
    (seen, vals, ovk, ova)
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

pub open spec fn cat_a(cs: Seq<Cols>, w: int) -> Seq<u64>
    decreases w,
{
    if w <= 0 {
        Seq::empty()
    } else {
        cat_a(cs, w - 1) + cs[w - 1].amount@
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
        cat_a(cs, w + 1).len() == cat_a(cs, w).len() + cs[w].n,
        cat_k(cs, w).len() == cat_a(cs, w).len(),
    decreases w,
{
    lemma_cat_eqlen(cs, w);
}

proof fn lemma_cat_eqlen(cs: Seq<Cols>, w: int)
    requires
        all_valid(cs),
        0 <= w <= cs.len(),
    ensures
        cat_k(cs, w).len() == cat_a(cs, w).len(),
    decreases w,
{
    if w > 0 {
        lemma_cat_eqlen(cs, w - 1);
    }
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

type Part = (Cols, Vec<bool>, Vec<u128>, Vec<u32>, Vec<u64>);

pub open spec fn part_ok(c: Cols, ret: Part) -> bool {
    &&& ret.0.k@ == c.k@
    &&& ret.0.amount@ == c.amount@
    &&& ret.0.n == c.n
    &&& ret.1.len() == DENSE
    &&& ret.2.len() == DENSE
    &&& ret.3.len() == ret.4.len()
    &&& forall|t: int|
        #![trigger ret.1@[t]]
        #![trigger ret.2@[t]]
        0 <= t < DENSE as int ==> ret.1@[t] == (cnt(c.k@, t as u32) > 0) && ret.2@[t] as int == sm(
            c.k@,
            c.amount@,
            t as u32,
        )
    &&& forall|j: int| 0 <= j < ret.3@.len() ==> (#[trigger] ret.3@[j]) >= DENSE as u32
    &&& forall|key: u32|
        key >= DENSE as u32 ==> (cnt(ret.3@, key) == #[trigger] cnt(c.k@, key) && sm(
            ret.3@,
            ret.4@,
            key,
        ) == sm(c.k@, c.amount@, key))
}

pub open spec fn handle_ok(h: JoinHandle<Part>, c: Cols) -> bool {
    forall|ret: Part| #[trigger] h.predicate(ret) ==> part_ok(c, ret)
}

pub open spec fn same_chunk(a: Cols, b: Cols) -> bool {
    a.k@ == b.k@ && a.amount@ == b.amount@ && a.n == b.n
}

/// Same statement as the single-threaded ensures, for the table whose columns are the
/// concatenation of the chunks.
pub proof fn lemma_same_as_single_threaded(whole: &Cols, k: Seq<u32>, a: Seq<u64>)
    requires
        valid_cols(whole),
        whole.k@ == k,
        whole.amount@ == a,
    ensures
        method_spec(whole) == fold(k, a),
{
    lemma_helper_is_fold(whole, 0);
    assert(k.skip(0) =~= k);
    assert(a.skip(0) =~= a);
}

proof fn lemma_view_eq(
    seen: Seq<bool>,
    vals: Seq<u128>,
    over: Map<u32, u128>,
    k: Seq<u32>,
    a: Seq<u64>,
)
    requires
        seen.len() == DENSE,
        vals.len() == DENSE,
        k.len() == a.len(),
        k.len() <= LEMMA_MAX_ROWS,
        forall|t: int|
            #![trigger seen[t]]
            #![trigger vals[t]]
            0 <= t < DENSE as int ==> seen[t] == (cnt(k, t as u32) > 0) && vals[t] as int == sm(
                k,
                a,
                t as u32,
            ),
        forall|key: u32|
            key >= DENSE as u32 ==> (over.contains_key(key) <==> #[trigger] cnt(k, key) > 0) && (
            over.contains_key(key) ==> over[key] as int == sm(k, a, key)),
        forall|key: u32| key < DENSE as u32 ==> !(#[trigger] over.contains_key(key)),
    ensures
        group_view(seen, vals, over) == fold(k, a),
{
    let gv = group_view(seen, vals, over);
    let f = fold(k, a);
    assert forall|key: u32| #![trigger gv.contains_key(key)] gv.contains_key(key) == f.contains_key(key) && (
    gv.contains_key(key) ==> gv[key] == f[key]) by {
        lemma_fold_char(k, a, key);
        if key < DENSE as u32 {
            assert(seen[key as int] == (cnt(k, key) > 0));
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
            cat_a(old(chunks)@, old(chunks)@.len() as int),
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
                    let (s, v, ok, oa) = chunk_groups(&c);
                    (c, s, v, ok, oa)
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
    let mut acc_vals: Vec<u128> = vec![0u128; DENSE];
    let mut over = HashMapWithView::<u32, u128>::new();
    let mut joined: usize = 0;
    let mut out: Vec<Cols> = Vec::new();
    proof {
        assert(cat_k(orig, 0) =~= Seq::<u32>::empty());
        assert(cat_a(orig, 0) =~= Seq::<u64>::empty());
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
            forall|t: int|
                #![trigger acc_seen@[t]]
                #![trigger acc_vals@[t]]
                0 <= t < DENSE as int ==> acc_seen@[t] == (cnt(cat_k(orig, joined as int), t as u32)
                    > 0) && acc_vals@[t] as int == sm(
                    cat_k(orig, joined as int),
                    cat_a(orig, joined as int),
                    t as u32,
                ),
            forall|key: u32|
                key >= DENSE as u32 ==> (over@.contains_key(key) <==> #[trigger] cnt(
                    cat_k(orig, joined as int),
                    key,
                ) > 0) && (over@.contains_key(key) ==> over@[key] as int == sm(
                    cat_k(orig, joined as int),
                    cat_a(orig, joined as int),
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
            assert(cat_a(orig, jj + 1) == cat_a(orig, jj) + orig[jj].amount@);
            lemma_cat_prefix_len(orig, jj + 1, w as int);
            assert forall|key: u32| cnt(cat_k(orig, jj + 1), key) == #[trigger] cnt(cat_k(orig, jj), key)
                + cnt(orig[jj].k@, key) by {
                lemma_cnt_add(cat_k(orig, jj), orig[jj].k@, key);
            }
            assert forall|key: u32| sm(cat_k(orig, jj + 1), cat_a(orig, jj + 1), key) == #[trigger] sm(
                cat_k(orig, jj),
                cat_a(orig, jj),
                key,
            ) + sm(orig[jj].k@, orig[jj].amount@, key) by {
                lemma_sm_add(cat_k(orig, jj), cat_a(orig, jj), orig[jj].k@, orig[jj].amount@, key);
            }
        }
        let (c, ps, pv, pk, pa) = r;
        // merge the dense partial arrays
        let ghost acc_seen0 = acc_seen@;
        let ghost acc_vals0 = acc_vals@;
        let mut t: usize = 0;
        while t < DENSE
            invariant
                t <= DENSE,
                all_valid(orig),
                w == orig.len(),
                jj + 1 <= w,
                acc_seen.len() == DENSE,
                acc_vals.len() == DENSE,
                ps.len() == DENSE,
                pv.len() == DENSE,
                acc_seen0.len() == DENSE,
                acc_vals0.len() == DENSE,
                cat_k(orig, jj + 1).len() <= LEMMA_MAX_ROWS,
                cat_k(orig, jj + 1).len() == cat_a(orig, jj + 1).len(),
                jj == joined as int,
                forall|key: u32| cnt(cat_k(orig, jj + 1), key) == #[trigger] cnt(cat_k(orig, jj), key)
                    + cnt(orig[jj].k@, key),
                forall|key: u32|
                    sm(cat_k(orig, jj + 1), cat_a(orig, jj + 1), key) == #[trigger] sm(
                        cat_k(orig, jj),
                        cat_a(orig, jj),
                        key,
                    ) + sm(orig[jj].k@, orig[jj].amount@, key),
                forall|t2: int|
                    #![trigger ps@[t2]]
                    #![trigger pv@[t2]]
                    0 <= t2 < DENSE as int ==> ps@[t2] == (cnt(c.k@, t2 as u32) > 0) && pv@[t2] as int
                        == sm(c.k@, c.amount@, t2 as u32),
                c.k@ == orig[jj].k@,
                c.amount@ == orig[jj].amount@,
                forall|t2: int|
                    0 <= t2 < DENSE as int ==> (#[trigger] acc_seen0[t2]) == (cnt(
                        cat_k(orig, jj),
                        t2 as u32,
                    ) > 0) && acc_vals0[t2] as int == sm(
                        cat_k(orig, jj),
                        cat_a(orig, jj),
                        t2 as u32,
                    ),
                forall|t2: int|
                    #![trigger acc_seen@[t2]]
                    #![trigger acc_vals@[t2]]
                    0 <= t2 < t as int ==> acc_seen@[t2] == (cnt(cat_k(orig, jj + 1), t2 as u32) > 0)
                        && acc_vals@[t2] as int == sm(
                        cat_k(orig, jj + 1),
                        cat_a(orig, jj + 1),
                        t2 as u32,
                    ),
                forall|t2: int|
                    t as int <= t2 < DENSE as int ==> acc_seen@[t2] == acc_seen0[t2] && acc_vals@[t2]
                        == acc_vals0[t2],
            decreases DENSE - t,
        {
            proof {
                let tk = t as u32;
                assert(t as int as u32 == tk);
                assert(ps@[t as int] == (cnt(c.k@, tk) > 0));
                assert(acc_seen0[t as int] == (cnt(cat_k(orig, jj), tk) > 0));
                lemma_cnt_le_len(cat_k(orig, jj), tk);
                lemma_cnt_le_len(orig[jj].k@, tk);
                assert(cnt(cat_k(orig, jj + 1), tk) == cnt(cat_k(orig, jj), tk) + cnt(orig[jj].k@, tk));
                assert(acc_vals0[t as int] as int == sm(cat_k(orig, jj), cat_a(orig, jj), tk));
                assert(pv@[t as int] as int == sm(c.k@, c.amount@, tk));
                assert(sm(cat_k(orig, jj + 1), cat_a(orig, jj + 1), tk) == acc_vals0[t as int] as int
                    + pv@[t as int] as int);
                lemma_sm_fits(cat_k(orig, jj + 1), cat_a(orig, jj + 1), tk);
            }
            let a = acc_vals[t];
            let b = pv[t];
            let sa = acc_seen[t];
            let sb = ps[t];
            proof {
                assert(a as int + b as int <= u128::MAX);
            }
            let ghost pre_seen = acc_seen@;
            let ghost pre_vals = acc_vals@;
            acc_vals.set(t, a + b);
            acc_seen.set(t, sa || sb);
            proof {
                assert(acc_vals@[t as int] == (a + b) as u128);
                assert(acc_vals@[t as int] as int == a as int + b as int);
                assert(acc_seen@[t as int] == (sa || sb));
                assert(sa == acc_seen0[t as int]);
                assert(sb == ps@[t as int]);
                assert(sa == pre_seen[t as int]);
                assert(sa || sb <==> cnt(cat_k(orig, jj + 1), t as u32) > 0);
                assert(acc_vals@[t as int] as int == sm(cat_k(orig, jj + 1), cat_a(orig, jj + 1), t as u32));
                assert forall|t2: int| t as int + 1 <= t2 < DENSE as int implies acc_seen@[t2] == acc_seen0[t2]
                    && acc_vals@[t2] == acc_vals0[t2] by {
                    assert(acc_seen@[t2] == pre_seen[t2]);
                    assert(acc_vals@[t2] == pre_vals[t2]);
                }
                assert forall|t2: int| 0 <= t2 < t as int implies acc_seen@[t2] == pre_seen[t2] && acc_vals@[t2]
                    == pre_vals[t2] by {}
            }
            t = t + 1;
        }
        // replay the worker's overflow-row log into the shared overflow map
        let mut x: usize = 0;
        let ghost cat0k = cat_k(orig, jj);
        let ghost cat0a = cat_a(orig, jj);
        while x < pk.len()
            invariant
                x <= pk.len(),
                pk.len() == pa.len(),
                all_valid(orig),
                w == orig.len(),
                jj + 1 <= w,
                jj == joined as int,
                jj == joined as int,
                cat0k == cat_k(orig, jj),
                cat0a == cat_a(orig, jj),
                cat_k(orig, jj + 1).len() <= LEMMA_MAX_ROWS,
                cat_k(orig, jj + 1).len() == cat_a(orig, jj + 1).len(),
                forall|j: int| 0 <= j < pk@.len() ==> (#[trigger] pk@[j]) >= DENSE as u32,
                forall|key: u32|
                    key >= DENSE as u32 ==> (cnt(pk@, key) == #[trigger] cnt(c.k@, key) && sm(
                        pk@,
                        pa@,
                        key,
                    ) == sm(c.k@, c.amount@, key)),
                c.k@ == orig[jj].k@,
                c.amount@ == orig[jj].amount@,
                forall|key: u32| cnt(cat_k(orig, jj + 1), key) == #[trigger] cnt(cat_k(orig, jj), key)
                    + cnt(orig[jj].k@, key),
                forall|key: u32|
                    sm(cat_k(orig, jj + 1), cat_a(orig, jj + 1), key) == #[trigger] sm(
                        cat_k(orig, jj),
                        cat_a(orig, jj),
                        key,
                    ) + sm(orig[jj].k@, orig[jj].amount@, key),
                forall|key: u32|
                    key >= DENSE as u32 ==> (over@.contains_key(key) <==> #[trigger] (cnt(cat0k, key)
                        + cnt(pk@.subrange(0, x as int), key)) > 0) && (over@.contains_key(key)
                        ==> over@[key] as int == sm(cat0k, cat0a, key) + sm(
                        pk@.subrange(0, x as int),
                        pa@.subrange(0, x as int),
                        key,
                    )),
                forall|key: u32| key < DENSE as u32 ==> !(#[trigger] over@.contains_key(key)),
            decreases pk.len() - x,
        {
            let key = pk[x];
            let av = pa[x];
            let ghost before = over@;
            let ghost subk = pk@.subrange(0, x as int);
            let ghost suba = pa@.subrange(0, x as int);
            proof {
                assert(pk@[x as int] == key);
                assert(key >= DENSE as u32);
                assert(cnt(pk@, key) == cnt(c.k@, key));
                lemma_sm_prefix(pk@, pa@, x as int, key);
                assert(sm(pk@, pa@, key) == sm(c.k@, c.amount@, key));
                assert(sm(cat_k(orig, jj + 1), cat_a(orig, jj + 1), key) == sm(cat0k, cat0a, key) + sm(
                    c.k@,
                    c.amount@,
                    key,
                ));
                lemma_cat_eqlen(orig, jj);
                assert(subk.len() == suba.len());
                lemma_sm_bound(cat0k, cat0a, key);
                lemma_sm_bound(subk, suba, key);
                lemma_sm_fits(cat_k(orig, jj + 1), cat_a(orig, jj + 1), key);
                let tot = cnt(cat0k, key) + cnt(subk, key);
                assert(before.contains_key(key) <==> tot > 0);
                assert(before.contains_key(key) ==> before[key] as int == sm(cat0k, cat0a, key) + sm(
                    subk,
                    suba,
                    key,
                ));
            }
            let prev = match over.get(&key) {
                Some(v) => *v,
                None => 0u128,
            };
            proof {
                if before.contains_key(key) {
                    assert(prev as int == sm(cat0k, cat0a, key) + sm(subk, suba, key));
                } else {
                    assert(prev == 0);
                    assert(cnt(cat0k, key) + cnt(subk, key) == 0);
                    lemma_cnt_le_len(cat0k, key);
                    lemma_cnt_le_len(subk, key);
                    lemma_sm_zero(cat0k, cat0a, key);
                    lemma_sm_zero(subk, suba, key);
                }
            }
            let next = prev + (av as u128);
            over.insert(key, next);
            proof {
                assert(pk@.subrange(0, x as int + 1) =~= subk.push(key));
                assert(pa@.subrange(0, x as int + 1) =~= suba.push(av));
                assert forall|key2: u32| key2 >= DENSE as u32 implies (over@.contains_key(key2) <==> #[trigger] (cnt(
                    cat0k,
                    key2,
                ) + cnt(pk@.subrange(0, x as int + 1), key2)) > 0) && (over@.contains_key(key2)
                    ==> over@[key2] as int == sm(cat0k, cat0a, key2) + sm(
                    pk@.subrange(0, x as int + 1),
                    pa@.subrange(0, x as int + 1),
                    key2,
                )) by {
                    lemma_cnt_le_len(cat0k, key2);
                    lemma_cnt_le_len(subk, key2);
                    lemma_cnt_push(subk, key, key2);
                    lemma_sm_push(subk, suba, key, av, key2);
                    assert(over@ == before.insert(key, next));
                    let tot_old = cnt(cat0k, key2) + cnt(subk, key2);
                    assert(before.contains_key(key2) <==> tot_old > 0);
                    assert(before.contains_key(key2) ==> before[key2] as int == sm(cat0k, cat0a, key2) + sm(
                        subk,
                        suba,
                        key2,
                    ));
                    if key2 == key {
                        assert(over@.contains_key(key2));
                        assert(over@[key2] == next);
                    }
                }
                assert forall|key2: u32| key2 < DENSE as u32 implies !(#[trigger] over@.contains_key(key2)) by {
                    assert(key2 != key);
                }
            }
            x = x + 1;
        }
        proof {
            assert(pk@.subrange(0, pk@.len() as int) =~= pk@);
            assert(pa@.subrange(0, pa@.len() as int) =~= pa@);
            assert forall|key: u32| key >= DENSE as u32 implies (over@.contains_key(key) <==> #[trigger] cnt(
                cat_k(orig, jj + 1),
                key,
            ) > 0) && (over@.contains_key(key) ==> over@[key] as int == sm(
                cat_k(orig, jj + 1),
                cat_a(orig, jj + 1),
                key,
            )) by {
                assert(x == pk.len());
                assert(pk@.subrange(0, x as int) == pk@);
                assert(pa@.subrange(0, x as int) == pa@);
                assert(cnt(pk@, key) == cnt(c.k@, key));
                assert(sm(pk@, pa@, key) == sm(c.k@, c.amount@, key));
                assert(cnt(cat_k(orig, jj + 1), key) == cnt(cat0k, key) + cnt(orig[jj].k@, key));
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
        let k = cat_k(orig, w as int);
        let a = cat_a(orig, w as int);
        lemma_cat_eqlen(orig, w as int);
        assert(cat_k(orig, joined as int) == k);
        assert(cat_a(orig, joined as int) == a);
        lemma_view_eq(acc_seen@, acc_vals@, over@, k, a);
    }
    Groups { seen: acc_seen, vals: acc_vals, overflow: over }
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
        let mut amount = Vec::with_capacity(hi - lo);
        for i in lo..hi {
            k.push((i % 32) as u32);
            amount.push(((i as u64) * 17) % 1000);
        }
        chunks.push(Cols { n: hi - lo, k, amount });
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
