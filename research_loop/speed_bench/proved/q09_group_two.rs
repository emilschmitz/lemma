use vstd::prelude::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;
pub const K1: usize = 32;
pub const K2: usize = 8;
pub const DENSE: usize = 256;

pub struct Cols {
    pub n: usize,
    pub k: Vec<u32>,
    pub k2: Vec<u32>,
    pub amount: Vec<u64>,
}

impl Cols {
    #[inline(always)]
    #[verifier::external_body]
    pub exec fn key_exec(&self, i: usize) -> (res: u32)
        requires
            i < self.n,
        ensures
            res == self.k[i as int],
    {
        self.k[i]
    }

    #[inline(always)]
    #[verifier::external_body]
    pub exec fn key2_exec(&self, i: usize) -> (res: u32)
        requires
            i < self.n,
        ensures
            res == self.k2[i as int],
    {
        self.k2[i]
    }

    pub open spec fn get_amount(self, i: int) -> u64 {
        self.amount[i as int]
    }

    #[inline(always)]
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
    pub oa: Vec<u32>,
    pub ob: Vec<u32>,
    pub ov: Vec<u128>,
}

pub open spec fn slot_key(i: int) -> (u32, u32) {
    ((i / (K2 as int)) as u32, (i % (K2 as int)) as u32)
}

pub open spec fn valid_cols(cols: &Cols) -> bool {
    &&& cols.n <= LEMMA_MAX_ROWS
    &&& cols.k.len() == cols.n
    &&& cols.k2.len() == cols.n
    &&& cols.amount.len() == cols.n
}

pub open spec fn method_spec_helper(cols: &Cols, k: int) -> Map<(u32, u32), u128>
    recommends
        0 <= k && k <= cols.n,
        valid_cols(cols),
    decreases cols.n - k,
{
    if k < cols.n {
        let tail = method_spec_helper(cols, k + 1);
        let key = (cols.k[k as int], cols.k2[k as int]);
        let prev = if tail.contains_key(key) { tail[key] } else { 0u128 };
        tail.insert(key, (prev as int + ((cols.get_amount(k) as int)) as u64 as int) as u128)
    } else {
        Map::empty()
    }
}

pub open spec fn method_spec(cols: &Cols) -> Map<(u32, u32), u128>
    recommends
        valid_cols(cols),
{
    method_spec_helper(cols, 0)
}

pub open spec fn dense_map(seen: Seq<bool>, vals: Seq<u128>, i: int) -> Map<(u32, u32), u128>
    recommends
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        let tail = dense_map(seen, vals, i + 1);
        if seen[i] {
            tail.insert(slot_key(i), vals[i])
        } else {
            tail
        }
    } else {
        Map::empty()
    }
}

pub open spec fn over_map(a: Seq<u32>, b: Seq<u32>, v: Seq<u128>, n: int) -> Map<(u32, u32), u128>
    recommends
        a.len() == b.len(),
        b.len() == v.len(),
        0 <= n <= a.len(),
    decreases n,
{
    if n > 0 {
        over_map(a, b, v, n - 1).insert((a[n - 1], b[n - 1]), v[n - 1])
    } else {
        Map::empty()
    }
}

pub open spec fn latest(a: Seq<u32>, b: Seq<u32>, v: Seq<u128>, ka: u32, kb: u32, n: int) -> u128
    recommends
        a.len() == b.len(),
        b.len() == v.len(),
        0 <= n <= a.len(),
    decreases n,
{
    if n > 0 {
        if a[n - 1] == ka && b[n - 1] == kb {
            v[n - 1]
        } else {
            latest(a, b, v, ka, kb, n - 1)
        }
    } else {
        0
    }
}

pub open spec fn group_view(
    seen: Seq<bool>,
    vals: Seq<u128>,
    a: Seq<u32>,
    b: Seq<u32>,
    v: Seq<u128>,
) -> Map<(u32, u32), u128> {
    dense_map(seen, vals, 0).union_prefer_right(over_map(a, b, v, a.len() as int))
}

proof fn lemma_rows_fit()
    ensures
        (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX,
{
    assert((LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX) by (compute_only);
}

proof fn lemma_dense_empty(seen: Seq<bool>, vals: Seq<u128>, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        forall|t: int| i <= t < DENSE as int ==> !seen[t],
    ensures
        dense_map(seen, vals, i) =~= Map::<(u32, u32), u128>::empty(),
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
        dense_map(seen, vals, i).contains_key(slot_key(key)),
        dense_map(seen, vals, i)[slot_key(key)] == vals[key],
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
        !dense_map(seen, vals, i).contains_key(slot_key(key)),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_absent(seen, vals, key, i + 1);
    }
}

proof fn lemma_slot(ka: u32, kb: u32)
    requires
        ka < K1 as u32,
        kb < K2 as u32,
    ensures
        0 <= (ka as int) * (K2 as int) + (kb as int) < DENSE as int,
        slot_key((ka as int) * (K2 as int) + (kb as int)) == (ka, kb),
{
    let i = (ka as int) * (K2 as int) + (kb as int);
    assert(i / (K2 as int) == ka as int) by (nonlinear_arith)
        requires
            kb < K2 as u32,
            i == (ka as int) * (K2 as int) + (kb as int),
            K2 == 8,
    {
    };
    assert(i % (K2 as int) == kb as int) by (nonlinear_arith)
        requires
            kb < K2 as u32,
            i == (ka as int) * (K2 as int) + (kb as int),
            K2 == 8,
    {
    };
}

proof fn lemma_dense_outside(seen: Seq<bool>, vals: Seq<u128>, ka: u32, kb: u32, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        ka >= K1 as u32 || kb >= K2 as u32,
    ensures
        !dense_map(seen, vals, i).contains_key((ka, kb)),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_outside(seen, vals, ka, kb, i + 1);
        assert(slot_key(i).0 < K1 as u32 || slot_key(i).1 < K2 as u32);
    }
}

proof fn lemma_dense_set(seen: Seq<bool>, vals: Seq<u128>, key: int, next: u128, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        0 <= key < DENSE as int,
    ensures
        (i > key ==> dense_map(seen.update(key, true), vals.update(key, next), i)
            == dense_map(seen, vals, i)) && (i <= key ==> dense_map(
            seen.update(key, true),
            vals.update(key, next),
            i,
        ) == dense_map(seen, vals, i).insert(slot_key(key), next)),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_set(seen, vals, key, next, i + 1);
        let seen2 = seen.update(key, true);
        let vals2 = vals.update(key, next);
        let tail = dense_map(seen, vals, i + 1);
        let tail2 = dense_map(seen2, vals2, i + 1);
        if i > key {
            assert(seen2[i] == seen[i]);
            assert(vals2[i] == vals[i]);
            assert(tail2 == tail);
        } else if i == key {
            assert(tail2 == tail);
            assert(seen2[i]);
            assert(vals2[i] == next);
            assert(dense_map(seen2, vals2, i) == tail.insert(slot_key(i), next));
            if seen[i] {
                assert(dense_map(seen, vals, i) == tail.insert(slot_key(i), vals[i]));
                assert(tail.insert(slot_key(i), vals[i]).insert(slot_key(key), next) == tail.insert(
                    slot_key(key),
                    next,
                ));
            } else {
                assert(dense_map(seen, vals, i) == tail);
            }
        } else {
            assert(tail2 == tail.insert(slot_key(key), next));
            assert(seen2[i] == seen[i]);
            assert(vals2[i] == vals[i]);
            if seen[i] {
                assert(dense_map(seen, vals, i) == tail.insert(slot_key(i), vals[i]));
                assert(dense_map(seen2, vals2, i) == tail2.insert(slot_key(i), vals[i]));
                assert(tail.insert(slot_key(key), next).insert(slot_key(i), vals[i]) == tail.insert(
                    slot_key(i),
                    vals[i],
                ).insert(slot_key(key), next));
            } else {
                assert(dense_map(seen, vals, i) == tail);
                assert(dense_map(seen2, vals2, i) == tail2);
            }
        }
    }
}


proof fn lemma_over_rect(a: Seq<u32>, b: Seq<u32>, v: Seq<u128>, n: int, ka: u32, kb: u32)
    requires
        a.len() == b.len() && b.len() == v.len(),
        0 <= n <= a.len(),
        ka < K1 as u32,
        kb < K2 as u32,
        forall|t: int| 0 <= t < a.len() ==> a[t] >= K1 as u32 || b[t] >= K2 as u32,
    ensures
        !over_map(a, b, v, n).contains_key((ka, kb)),
    decreases n,
{
    if n > 0 {
        lemma_over_rect(a, b, v, n - 1, ka, kb);
    }
}

proof fn lemma_over_same_prefix(
    a: Seq<u32>,
    b: Seq<u32>,
    v: Seq<u128>,
    a0: Seq<u32>,
    b0: Seq<u32>,
    v0: Seq<u128>,
    n: int,
)
    requires
        a0.len() == b0.len() && b0.len() == v0.len(),
        a.len() == b.len() && b.len() == v.len(),
        0 <= n <= a0.len(),
        n <= a.len(),
        forall|t: int| 0 <= t < n ==> a[t] == a0[t] && b[t] == b0[t] && v[t] == v0[t],
    ensures
        over_map(a, b, v, n) == over_map(a0, b0, v0, n),
    decreases n,
{
    if n > 0 {
        lemma_over_same_prefix(a, b, v, a0, b0, v0, n - 1);
    }
}

proof fn lemma_latest_map(a: Seq<u32>, b: Seq<u32>, v: Seq<u128>, ka: u32, kb: u32, n: int)
    requires
        a.len() == b.len() && b.len() == v.len(),
        0 <= n <= a.len(),
    ensures
        over_map(a, b, v, n).contains_key((ka, kb)) ==> over_map(a, b, v, n)[(ka, kb)] == latest(a, b, v, ka, kb, n),
        !over_map(a, b, v, n).contains_key((ka, kb)) ==> latest(a, b, v, ka, kb, n) == 0,
    decreases n,
{
    if n > 0 {
        lemma_latest_map(a, b, v, ka, kb, n - 1);
    }
}

pub exec fn run_query(cols: &Cols) -> (res: Groups)
    requires
        valid_cols(cols),
    ensures
        res.seen.len() == DENSE,
        res.vals.len() == DENSE,
        group_view(res.seen@, res.vals@, res.oa@, res.ob@, res.ov@) == method_spec(cols),
{
    let mut seen: Vec<bool> = Vec::new();
    let mut vals: Vec<u128> = Vec::new();
    let mut j: usize = 0;
    while j < DENSE
        invariant
            j <= DENSE,
            seen.len() == j,
            vals.len() == j,
            forall|t: int| 0 <= t < j as int ==> !seen@[t],
        decreases DENSE - j,
    {
        seen.push(false);
        vals.push(0);
        j = j + 1;
    }
    let mut oa: Vec<u32> = Vec::new();
    let mut ob: Vec<u32> = Vec::new();
    let mut ov: Vec<u128> = Vec::new();
    proof {
        lemma_dense_empty(seen@, vals@, 0);
    }
    assert(group_view(seen@, vals@, oa@, ob@, ov@) =~= Map::<(u32, u32), u128>::empty());
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            seen.len() == DENSE,
            vals.len() == DENSE,
            oa.len() == ob.len() && ob.len() == ov.len(),
            group_view(seen@, vals@, oa@, ob@, ov@) == method_spec_helper(cols, i as int),
            forall|t: int|
                0 <= t < oa.len() ==> oa@[t] >= K1 as u32 || ob@[t] >= K2 as u32,
            forall|t: int|
                0 <= t < DENSE as int && seen@[t] ==> vals@[t] <= ((cols.n - i) as u128) * (u64::MAX as u128),
            forall|t: int|
                0 <= t < ov.len() ==> ov@[t] <= ((cols.n - i) as u128) * (u64::MAX as u128),
        decreases i,
    {
        let ghost bound = ((cols.n - i) as u128) * (u64::MAX as u128);
        i = i - 1;
        let ka = cols.key_exec(i);
        let kb = cols.key2_exec(i);
        let amount = cols.get_amount_exec(i);
        let ghost before_seen = seen@;
        let ghost before_vals = vals@;
        let ghost before_a = oa@;
        let ghost before_b = ob@;
        let ghost before_v = ov@;
        if ka < K1 as u32 && kb < K2 as u32 {
            proof {
                lemma_slot(ka, kb);
            }
            let idx = (ka as usize) * K2 + (kb as usize);
            let prev = if seen[idx] { vals[idx] } else { 0u128 };
            proof {
                lemma_rows_fit();
                if before_seen[idx as int] {
                    lemma_dense_get(before_seen, before_vals, idx as int, 0);
                } else {
                    lemma_dense_absent(before_seen, before_vals, idx as int, 0);
                }
                lemma_over_rect(before_a, before_b, before_v, before_a.len() as int, ka, kb);
            }
            assert(prev <= bound);
            assert(bound == ((cols.n - (i + 1)) as u128) * (u64::MAX as u128));
            assert(amount as u128 <= u64::MAX as u128);
            assert(prev + (amount as u128) <= ((cols.n - i) as u128) * (u64::MAX as u128)) by (nonlinear_arith)
                requires
                    prev <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
                    amount as u128 <= u64::MAX as u128,
                    (cols.n - i) as u128 == (cols.n - (i + 1)) as u128 + 1,
            {
            };
            assert(((cols.n - i) as u128) * (u64::MAX as u128) <= u128::MAX) by (nonlinear_arith)
                requires
                    cols.n <= LEMMA_MAX_ROWS,
                    i < cols.n,
                    (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX,
            {
            };
            let next = prev + (amount as u128);
            seen.set(idx, true);
            vals.set(idx, next);
            proof {
                lemma_dense_set(before_seen, before_vals, idx as int, next, 0);
            }
            assert(group_view(seen@, vals@, oa@, ob@, ov@) == method_spec_helper(cols, i as int));
        } else {
            let mut p: usize = oa.len();
            let mut prev: u128 = 0;
            let mut found = false;
            assert(before_a.len() == before_b.len() && before_b.len() == before_v.len());
            while p > 0
                invariant
                    p <= oa.len(),
                    oa.len() == ob.len() && ob.len() == ov.len(),
                    oa@ == before_a,
                    ob@ == before_b,
                    ov@ == before_v,
                    before_a.len() == before_b.len() && before_b.len() == before_v.len(),
                    p as int <= before_a.len(),
                    !found ==> prev == 0,
                    prev <= bound,
                    forall|t: int| 0 <= t < ov.len() ==> ov@[t] <= bound,
                    found ==> prev == latest(before_a, before_b, before_v, ka, kb, before_a.len() as int),
                    !found ==> latest(before_a, before_b, before_v, ka, kb, before_a.len() as int) == latest(before_a, before_b, before_v, ka, kb, p as int),
                decreases p,
            {
                p = p - 1;
                if !found && oa[p] == ka && ob[p] == kb {
                    prev = ov[p];
                    found = true;
                }
            }
            proof {
                lemma_rows_fit();
                lemma_latest_map(before_a, before_b, before_v, ka, kb, before_a.len() as int);
                lemma_dense_outside(seen@, vals@, ka, kb, 0);
            }
            assert(prev == latest(before_a, before_b, before_v, ka, kb, before_a.len() as int));
            assert(prev <= bound);
            assert(bound == ((cols.n - (i + 1)) as u128) * (u64::MAX as u128));
            assert(amount as u128 <= u64::MAX as u128);
            assert(prev + (amount as u128) <= ((cols.n - i) as u128) * (u64::MAX as u128)) by (nonlinear_arith)
                requires
                    prev <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
                    amount as u128 <= u64::MAX as u128,
                    (cols.n - i) as u128 == (cols.n - (i + 1)) as u128 + 1,
            {
            };
            assert(((cols.n - i) as u128) * (u64::MAX as u128) <= u128::MAX) by (nonlinear_arith)
                requires
                    cols.n <= LEMMA_MAX_ROWS,
                    i < cols.n,
                    (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX,
            {
            };
            let next = prev + (amount as u128);
            oa.push(ka);
            ob.push(kb);
            ov.push(next);
            assert(oa@ == before_a.push(ka));
            assert(ob@ == before_b.push(kb));
            assert(ov@ == before_v.push(next));
            proof {
                lemma_over_same_prefix(oa@, ob@, ov@, before_a, before_b, before_v, before_a.len() as int);
            }
            assert(over_map(oa@, ob@, ov@, (before_a.len() as int) + 1) == over_map(oa@, ob@, ov@, before_a.len() as int).insert((ka, kb), next));
            assert(over_map(oa@, ob@, ov@, oa@.len() as int) == over_map(before_a, before_b, before_v, before_a.len() as int).insert((ka, kb), next));
            assert(group_view(seen@, vals@, oa@, ob@, ov@) == method_spec_helper(cols, i as int));
        }
    }
    Groups { seen, vals, oa, ob, ov }
}

}

fn main() {
    let n: usize = 2_000_000;
    let mut k = Vec::with_capacity(n);
    let mut k2 = Vec::with_capacity(n);
    let mut amount = Vec::with_capacity(n);
    for i in 0..n {
        k.push((i % 32) as u32);
        k2.push((i % 8) as u32);
        amount.push(((i as u64) * 17) % 1000);
    }
    let cols = Cols { n, k, k2, amount };
    for _ in 0..2 {
        let _ = run_query(&cols);
    }
    let mut samples = Vec::with_capacity(5);
    let mut last = None;
    for _ in 0..5 {
        let t0 = std::time::Instant::now();
        last = Some(run_query(&cols));
        samples.push(t0.elapsed().as_micros());
    }
    samples.sort();
    let groups = last.unwrap();
    let mut shown = 0u32;
    let mut total = 0u128;
    for key in 0..32u32 {
        for key2 in 0..8u32 {
            let idx = (key as usize) * 8 + (key2 as usize);
            if groups.seen[idx] {
                shown += 1;
                total += groups.vals[idx];
            }
        }
    }
    println!("OVERFLOW:{}", groups.oa.len());
    println!("SHOWN:{shown}");
    println!("TOTAL:{total}");
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
