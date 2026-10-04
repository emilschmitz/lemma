use vstd::hash_map::HashMapWithView;
use vstd::prelude::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;
pub const DENSE: usize = 1024;

pub struct Cols {
    pub n: usize,
    pub dim_id: Vec<u32>,
}

impl Cols {
    pub open spec fn get_dim_id(self, i: int) -> u32 {
        self.dim_id[i as int]
    }

    #[verifier::external_body]
    pub exec fn get_dim_id_exec(&self, i: usize) -> (res: u32)
        requires
            i < self.n,
        ensures
            res == self.get_dim_id(i as int),
    {
        self.dim_id[i]
    }
}

pub open spec fn valid_cols(cols: &Cols) -> bool {
    &&& cols.n <= LEMMA_MAX_ROWS
    &&& cols.dim_id.len() == cols.n
}

pub open spec fn method_spec_helper(cols: &Cols, k: int) -> Map<u32, bool>
    recommends
        0 <= k && k <= cols.n,
        valid_cols(cols),
    decreases cols.n - k,
{
    if k < cols.n {
        let tail = method_spec_helper(cols, k + 1);
        let v = cols.get_dim_id(k);
        if tail.contains_key(v) {
            tail
        } else {
            tail.insert(v, true)
        }
    } else {
        Map::empty()
    }
}

pub open spec fn method_spec(cols: &Cols) -> u64
    recommends
        valid_cols(cols),
{
    method_spec_helper(cols, 0).dom().len() as u64
}

pub open spec fn dense_map(seen: Seq<bool>, i: int) -> Map<u32, bool>
    recommends
        seen.len() == DENSE as int,
        0 <= i <= DENSE as int,
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        let tail = dense_map(seen, i + 1);
        if seen[i] {
            tail.insert(i as u32, true)
        } else {
            tail
        }
    } else {
        Map::empty()
    }
}

pub open spec fn group_view(seen: Seq<bool>, over: Map<u32, bool>) -> Map<u32, bool> {
    dense_map(seen, 0).union_prefer_right(over)
}

proof fn lemma_count_fits()
    ensures
        (LEMMA_MAX_ROWS as u64) < u64::MAX,
{
    assert((LEMMA_MAX_ROWS as u64) < u64::MAX) by (compute_only);
}

proof fn lemma_dense_empty(seen: Seq<bool>, i: int)
    requires
        seen.len() == DENSE as int,
        0 <= i <= DENSE as int,
        forall|t: int| i <= t < DENSE as int ==> !seen[t],
    ensures
        dense_map(seen, i) =~= Map::<u32, bool>::empty(),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_empty(seen, i + 1);
        assert(!seen[i]);
    }
}

proof fn lemma_dense_absent(seen: Seq<bool>, key: int, i: int)
    requires
        seen.len() == DENSE as int,
        0 <= i <= DENSE as int,
        0 <= key < DENSE as int,
        !seen[key],
    ensures
        !dense_map(seen, i).contains_key(key as u32),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_absent(seen, key, i + 1);
    }
}

proof fn lemma_dense_present(seen: Seq<bool>, key: int, i: int)
    requires
        seen.len() == DENSE as int,
        0 <= i <= DENSE as int,
        0 <= key < DENSE as int,
        i <= key,
        seen[key],
    ensures
        dense_map(seen, i).contains_key(key as u32),
        dense_map(seen, i)[key as u32] == true,
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        if i == key {
            assert(seen[i]);
        } else {
            lemma_dense_present(seen, key, i + 1);
        }
    }
}

proof fn lemma_dense_keys_below(seen: Seq<bool>, key: u32, i: int)
    requires
        seen.len() == DENSE as int,
        0 <= i <= DENSE as int,
        key >= DENSE as u32,
    ensures
        !dense_map(seen, i).contains_key(key),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_keys_below(seen, key, i + 1);
    }
}

proof fn lemma_dense_insert(seen: Seq<bool>, key: int, i: int)
    requires
        seen.len() == DENSE as int,
        0 <= i <= DENSE as int,
        0 <= key < DENSE as int,
        !seen[key],
    ensures
        (i > key ==> dense_map(seen.update(key, true), i) == dense_map(seen, i)) && (i
            <= key ==> dense_map(seen.update(key, true), i) == dense_map(seen, i).insert(
            key as u32,
            true,
        )),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_insert(seen, key, i + 1);
        let seen2 = seen.update(key, true);
        let tail = dense_map(seen, i + 1);
        let tail2 = dense_map(seen2, i + 1);
        if i > key {
            assert(seen2[i] == seen[i]);
            assert(tail2 == tail);
        } else if i == key {
            assert(tail2 == tail);
            assert(seen2[i]);
            assert(dense_map(seen2, i) == tail.insert(i as u32, true));
            assert(!seen[i]);
            assert(dense_map(seen, i) == tail);
        } else {
            assert(tail2 == tail.insert(key as u32, true));
            assert(seen2[i] == seen[i]);
            if seen[i] {
                assert(dense_map(seen, i) == tail.insert(i as u32, true));
                assert(dense_map(seen2, i) == tail2.insert(i as u32, true));
                assert(tail.insert(key as u32, true).insert(i as u32, true) == tail.insert(
                    i as u32,
                    true,
                ).insert(key as u32, true));
            } else {
                assert(dense_map(seen, i) == tail);
                assert(dense_map(seen2, i) == tail2);
            }
        }
    }
}

pub exec fn run_query(cols: &Cols) -> (res: u64)
    requires
        valid_cols(cols),
    ensures
        res == method_spec(cols),
{
    broadcast use vstd::std_specs::hash::axiom_u32_obeys_hash_table_key_model;
    let mut seen: Vec<bool> = Vec::new();
    let mut j: usize = 0;
    while j < DENSE
        invariant
            j <= DENSE,
            seen.len() == j,
            forall|t: int| 0 <= t < j as int ==> !seen@[t],
        decreases DENSE - j,
    {
        seen.push(false);
        j = j + 1;
    }
    let mut overflow = HashMapWithView::<u32, bool>::new();
    proof {
        lemma_dense_empty(seen@, 0);
    }
    assert(group_view(seen@, overflow@) =~= Map::<u32, bool>::empty());
    let mut cnt: u64 = 0;
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            seen.len() == DENSE,
            cnt as int == group_view(seen@, overflow@).dom().len(),
            cnt <= (cols.n - i) as u64,
            forall|key: u32| overflow@.contains_key(key) ==> key >= DENSE as u32,
            group_view(seen@, overflow@) == method_spec_helper(cols, i as int),
        decreases i,
    {
        i = i - 1;
        let v = cols.get_dim_id_exec(i);
        let ghost before_seen = seen@;
        let ghost before_over = overflow@;
        let ghost before = group_view(before_seen, before_over);
        if v < DENSE as u32 {
            let idx = v as usize;
            if !seen[idx] {
                proof {
                    lemma_count_fits();
                    lemma_dense_absent(before_seen, v as int, 0);
                }
                assert(!before.contains_key(v));
                assert(cnt as int + 1 < u64::MAX as int);
                seen.set(idx, true);
                proof {
                    lemma_dense_insert(before_seen, v as int, 0);
                }
                assert(!before_over.contains_key(v));
                cnt = cnt + 1;
                assert(group_view(seen@, overflow@) == before.insert(v, true));
                assert(group_view(seen@, overflow@) == method_spec_helper(cols, i as int));
                assert(cnt as int == group_view(seen@, overflow@).dom().len());
            } else {
                proof {
                    lemma_dense_present(before_seen, v as int, 0);
                }
                assert(before.contains_key(v));
                assert(group_view(seen@, overflow@) == method_spec_helper(cols, i as int));
            }
        } else {
            proof {
                lemma_dense_keys_below(seen@, v, 0);
            }
            if !overflow.contains_key(&v) {
                proof {
                    lemma_count_fits();
                }
                assert(!before.contains_key(v));
                assert(cnt as int + 1 < u64::MAX as int);
                overflow.insert(v, true);
                cnt = cnt + 1;
                assert(group_view(seen@, overflow@) == before.insert(v, true));
                assert(group_view(seen@, overflow@) == method_spec_helper(cols, i as int));
                assert(cnt as int == group_view(seen@, overflow@).dom().len());
            } else {
                assert(before.contains_key(v));
                assert(group_view(seen@, overflow@) == method_spec_helper(cols, i as int));
            }
        }
        assert(cnt <= (cols.n - i) as u64);
    }
    cnt
}

}

fn env_usize(key: &str) -> usize {
    std::env::var(key).unwrap().parse().unwrap()
}

fn main() {
    let n = env_usize("SPEED_ROWS");
    let mut dim_id = Vec::with_capacity(n);
    for i in 0..n {
        dim_id.push((i % 1000) as u32);
    }
    let cols = Cols { n, dim_id };
    for _ in 0..env_usize("SPEED_WARMUP") {
        let _ = run_query(&cols);
    }
    let mut samples = Vec::new();
    let mut last = 0u64;
    for _ in 0..env_usize("SPEED_RUNS") {
        let t0 = std::time::Instant::now();
        last = run_query(&cols);
        samples.push(t0.elapsed().as_micros());
    }
    samples.sort();
    println!("RESULT:{last}");
    println!("SAMPLES_US:{samples:?}");
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
