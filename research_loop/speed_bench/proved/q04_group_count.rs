use vstd::hash_map::HashMapWithView;
use vstd::prelude::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;
pub const DENSE: usize = 1024;

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

proof fn lemma_dense_set(seen: Seq<bool>, vals: Seq<u64>, key: int, next: u64, i: int)
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
        ) == dense_map(seen, vals, i).insert(key as u32, next)),
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
            assert(dense_map(seen2, vals2, i) == tail.insert(i as u32, next));
            if seen[i] {
                assert(dense_map(seen, vals, i) == tail.insert(i as u32, vals[i]));
                assert(tail.insert(i as u32, vals[i]).insert(key as u32, next) == tail.insert(
                    key as u32,
                    next,
                ));
            } else {
                assert(dense_map(seen, vals, i) == tail);
            }
        } else {
            assert(tail2 == tail.insert(key as u32, next));
            assert(seen2[i] == seen[i]);
            assert(vals2[i] == vals[i]);
            if seen[i] {
                assert(dense_map(seen, vals, i) == tail.insert(i as u32, vals[i]));
                assert(dense_map(seen2, vals2, i) == tail2.insert(i as u32, vals[i]));
                assert(tail.insert(key as u32, next).insert(i as u32, vals[i]) == tail.insert(
                    i as u32,
                    vals[i],
                ).insert(key as u32, next));
            } else {
                assert(dense_map(seen, vals, i) == tail);
                assert(dense_map(seen2, vals2, i) == tail2);
            }
        }
    }
}

pub exec fn run_query(cols: &Cols) -> (res: Groups)
    requires
        valid_cols(cols),
    ensures
        res.seen.len() == DENSE,
        res.vals.len() == DENSE,
        group_view(res.seen@, res.vals@, res.overflow@) == method_spec(cols),
{
    broadcast use vstd::std_specs::hash::axiom_u32_obeys_hash_table_key_model;
    let mut seen: Vec<bool> = Vec::new();
    let mut vals: Vec<u64> = Vec::new();
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
    let mut overflow = HashMapWithView::<u32, u64>::new();
    proof {
        lemma_dense_empty(seen@, vals@, 0);
    }
    assert(group_view(seen@, vals@, overflow@) =~= Map::<u32, u64>::empty());
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            seen.len() == DENSE,
            vals.len() == DENSE,
            group_view(seen@, vals@, overflow@) == method_spec_helper(cols, i as int),
            forall|key: u32|
                overflow@.contains_key(key) ==> key >= DENSE as u32 && overflow@[key]
                    <= (cols.n - i) as u64,
            forall|t: int|
                0 <= t < DENSE as int && seen@[t] ==> vals@[t] <= (cols.n - i) as u64,
        decreases i,
    {
        let ghost bound = (cols.n - i) as u64;
        i = i - 1;
        let key = cols.key_exec(i);
        let ghost before_seen = seen@;
        let ghost before_vals = vals@;
        let ghost before_over = overflow@;
        if key < DENSE as u32 {
            let idx = key as usize;
            let prev = if seen[idx] {
                vals[idx]
            } else {
                0u64
            };
            proof {
                lemma_count_fits();
            }
            assert(prev <= bound);
            assert(prev as int + 1 < u64::MAX as int);
            let next = prev + 1;
            proof {
                if before_seen[idx as int] {
                    lemma_dense_get(before_seen, before_vals, key as int, 0);
                } else {
                    lemma_dense_absent(before_seen, before_vals, key as int, 0);
                }
            }
            seen.set(idx, true);
            vals.set(idx, next);
            proof {
                lemma_dense_set(before_seen, before_vals, key as int, next, 0);
            }
            assert(overflow@ == before_over);
            assert(!before_over.contains_key(key));
            assert(group_view(seen@, vals@, overflow@) == method_spec_helper(cols, i as int));
        } else {
            let prev = match overflow.get(&key) {
                Some(v) => *v,
                None => 0u64,
            };
            proof {
                lemma_count_fits();
            }
            assert(prev <= bound);
            assert(prev as int + 1 < u64::MAX as int);
            let next = prev + 1;
            proof {
                lemma_dense_keys_below(seen@, vals@, key, 0);
            }
            let ghost before_group = group_view(seen@, vals@, overflow@);
            overflow.insert(key, next);
            assert(before_group == method_spec_helper(cols, (i + 1) as int));
            assert(overflow@ == before_over.insert(key, next));
            assert(group_view(seen@, vals@, overflow@) == dense_map(seen@, vals@, 0).union_prefer_right(
                before_over.insert(key, next),
            ));
            assert(before_group.insert(key, next) == method_spec_helper(cols, i as int));
            assert(group_view(seen@, vals@, overflow@) == before_group.insert(key, next));
        }
    }
    Groups { seen, vals, overflow }
}

}

fn main() {
    let n: usize = 2_000_000;
    let mut k = Vec::with_capacity(n);
    for i in 0..n {
        k.push((i % 32) as u32);
    }
    let cols = Cols { n, k };
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
    let mut pairs = Vec::new();
    for key in 0..32u32 {
        if groups.seen[key as usize] {
            pairs.push((key, groups.vals[key as usize]));
        }
    }
    println!("OVERFLOW:{}", groups.overflow.len());
    println!("RESULT:{pairs:?}");
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
