use vstd::arithmetic::div_mod::*;
use vstd::hash_map::HashMapWithView;
use vstd::prelude::*;
use vstd::wrapping::u128_specs::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;
pub const DENSE: usize = 1024;

pub struct Cols_t {
    pub n: usize,
    pub dim_id: Vec<u32>,
    pub amount: Vec<u64>,
}

pub struct Cols_dim {
    pub n: usize,
    pub id: Vec<u32>,
    pub w: Vec<u64>,
}

pub open spec fn valid_cols_t(t: &Cols_t) -> bool {
    &&& t.n <= LEMMA_MAX_ROWS
    &&& t.dim_id.len() == t.n
    &&& t.amount.len() == t.n
}

pub open spec fn valid_cols_dim(dim: &Cols_dim) -> bool {
    &&& dim.n <= LEMMA_MAX_ROWS
    &&& dim.id.len() == dim.n
    &&& dim.w.len() == dim.n
}

pub open spec fn join_method_spec_helper(t: &Cols_t, dim: &Cols_dim, i0: int, i1: int) -> (res: (u128, int))
    recommends
        0 <= i0 <= t.n,
        0 <= i1 <= dim.n,
        valid_cols_t(t),
        valid_cols_dim(dim),
    decreases t.n - i0, dim.n - i1,
{
    if i0 < t.n {
        if i1 < dim.n {
            let tail = join_method_spec_helper(t, dim, i0, i1 + 1);
            if t.dim_id[i0 as int] == dim.id[i1 as int] {
                {
                    let (s, c) = tail;
                    (
                        wrapping_add(
                            s,
                            wrapping_mul(t.amount[i0 as int] as u128, dim.w[i1 as int] as u128),
                        ),
                        c + 1,
                    )
                }
            } else {
                tail
            }
        } else {
            join_method_spec_helper(t, dim, i0 + 1, 0)
        }
    } else {
        (0u128, 0)
    }
}

pub open spec fn method_spec(t: &Cols_t, dim: &Cols_dim) -> Option<u128>
    recommends
        valid_cols_t(t),
        valid_cols_dim(dim),
{
    let (s, c) = join_method_spec_helper(t, dim, 0, 0);
    if c == 0 {
        None
    } else {
        Some(s)
    }
}

pub open spec fn dim_w(dim: &Cols_dim, id: u32, j: int) -> u128
    recommends
        0 <= j <= dim.n,
        valid_cols_dim(dim),
    decreases dim.n - j,
{
    if j < dim.n {
        let tail = dim_w(dim, id, j + 1);
        if dim.id[j] == id {
            wrapping_add(tail, dim.w[j] as u128)
        } else {
            tail
        }
    } else {
        0u128
    }
}

pub open spec fn dim_c(dim: &Cols_dim, id: u32, j: int) -> int
    recommends
        0 <= j <= dim.n,
        valid_cols_dim(dim),
    decreases dim.n - j,
{
    if j < dim.n {
        let tail = dim_c(dim, id, j + 1);
        if dim.id[j] == id {
            tail + 1
        } else {
            tail
        }
    } else {
        0
    }
}

proof fn add_mod(x: u128, y: u128)
    ensures
        (wrapping_add(x, y) as int) == ((x as int) + (y as int)) % ((u128::MAX as int) + 1),
{
    let m: int = (u128::MAX as int) + 1;
    let s: int = (x as int) + (y as int);
    assert(s < m + m);
    if s > (u128::MAX as int) {
        assert(wrapping_add(x, y) == (s - m) as u128);
        assert(s % m == s - m);
    } else {
        assert(wrapping_add(x, y) == s as u128);
        assert(s % m == s);
    }
}

proof fn mul_mod(x: u128, y: u128)
    ensures
        (wrapping_mul(x, y) as int) == ((x as int) * (y as int)) % ((u128::MAX as int) + 1),
{
    let m: int = (u128::MAX as int) + 1;
    assert(wrapping_mul(x, y) == ((x as nat * y as nat) % (m as nat)) as u128);
}

proof fn assoc(x: u128, y: u128, z: u128)
    ensures
        wrapping_add(wrapping_add(x, y), z) == wrapping_add(x, wrapping_add(y, z)),
{
    add_mod(x, y);
    add_mod(y, z);
    add_mod(wrapping_add(x, y), z);
    add_mod(x, wrapping_add(y, z));
    let m: int = (u128::MAX as int) + 1;
    assert((((x as int) + (y as int)) % m + (z as int)) % m == ((x as int) + (((y as int) + (z as int)) % m)) % m);
}

proof fn commute(x: u128, y: u128)
    ensures
        wrapping_add(x, y) == wrapping_add(y, x),
{
    add_mod(x, y);
    add_mod(y, x);
}

proof fn regroup(p: u128, n: u128, q: u128)
    ensures
        wrapping_add(wrapping_add(p, n), q) == wrapping_add(wrapping_add(p, q), n),
{
    assoc(p, n, q);
    commute(n, q);
    assoc(p, q, n);
}

proof fn mul_distributes_mod(a: int, w1: int, w2: int, m: int)
    requires
        0 < m,
    ensures
        (a * ((w1 + w2) % m)) % m == (a * w1 + a * w2) % m,
{
    lemma_mul_mod_noop_right(a, w1 + w2, m);
    assert((a * ((w1 + w2) % m)) % m == (a * (w1 + w2)) % m);
    assert(a * (w1 + w2) == a * w1 + a * w2) by (nonlinear_arith);
}

proof fn dist(a: u128, w1: u128, w2: u128)
    ensures
        wrapping_mul(a, wrapping_add(w1, w2)) == wrapping_add(
            wrapping_mul(a, w1),
            wrapping_mul(a, w2),
        ),
{
    let m: int = (u128::MAX as int) + 1;
    add_mod(w1, w2);
    mul_mod(a, wrapping_add(w1, w2));
    mul_mod(a, w1);
    mul_mod(a, w2);
    add_mod(wrapping_mul(a, w1), wrapping_mul(a, w2));
    mul_distributes_mod(a as int, w1 as int, w2 as int, m);
    lemma_add_mod_noop((a as int) * (w1 as int), (a as int) * (w2 as int), m);
    let left = wrapping_mul(a, wrapping_add(w1, w2));
    let right = wrapping_add(wrapping_mul(a, w1), wrapping_mul(a, w2));
    assert((left as int) == (right as int));
}

proof fn add_zero(x: u128)
    ensures
        wrapping_add(x, 0) == x,
        wrapping_add(0, x) == x,
{
    add_mod(x, 0);
    add_mod(0, x);
}

proof fn mul_zero(x: u128)
    ensures
        wrapping_mul(x, 0) == 0,
        wrapping_mul(0, x) == 0,
{
    mul_mod(x, 0);
    mul_mod(0, x);
}

proof fn lemma_span(t: &Cols_t, dim: &Cols_dim, i0: int, i1: int)
    requires
        valid_cols_t(t),
        valid_cols_dim(dim),
        0 <= i0 < t.n,
        0 <= i1 <= dim.n,
    ensures
        join_method_spec_helper(t, dim, i0, i1).0 == wrapping_add(
            wrapping_mul(t.amount[i0] as u128, dim_w(dim, t.dim_id[i0], i1)),
            join_method_spec_helper(t, dim, i0 + 1, 0).0,
        ),
        join_method_spec_helper(t, dim, i0, i1).1 == dim_c(dim, t.dim_id[i0], i1)
            + join_method_spec_helper(t, dim, i0 + 1, 0).1,
    decreases dim.n - i1,
{
    if i1 == dim.n {
        mul_zero(t.amount[i0] as u128);
        add_zero(join_method_spec_helper(t, dim, i0 + 1, 0).0);
        assert(join_method_spec_helper(t, dim, i0, i1) == join_method_spec_helper(t, dim, i0 + 1, 0));
    } else {
        lemma_span(t, dim, i0, i1 + 1);
        let id = t.dim_id[i0];
        let amount = t.amount[i0] as u128;
        let tail = join_method_spec_helper(t, dim, i0, i1 + 1);
        let next = join_method_spec_helper(t, dim, i0 + 1, 0);
        let rest = dim_w(dim, id, i1 + 1);
        if dim.id[i1] == id {
            let w = dim.w[i1] as u128;
            dist(amount, rest, w);
            regroup(wrapping_mul(amount, rest), next.0, wrapping_mul(amount, w));
            assert(dim_w(dim, id, i1) == wrapping_add(rest, w));
            assert(dim_c(dim, id, i1) == dim_c(dim, id, i1 + 1) + 1);
        } else {
            assert(dim_w(dim, id, i1) == rest);
            assert(dim_c(dim, id, i1) == dim_c(dim, id, i1 + 1));
        }
    }
}

pub open spec fn slots_ok(sums: Seq<(u128, u64)>, dim: &Cols_dim, j: int) -> bool {
    &&& sums.len() == DENSE as int
    &&& forall|id: int|
        0 <= id < DENSE as int ==> sums[id].0 == dim_w(dim, id as u32, j) && sums[id].1 as int
            == dim_c(dim, id as u32, j)
}

pub open spec fn over_ok(over: Map<u32, (u128, u64)>, dim: &Cols_dim, j: int) -> bool {
    &&& forall|id: u32|
        id >= DENSE as u32 ==> (over.contains_key(id) ==> over[id].0 == dim_w(dim, id, j)
            && over[id].1 as int == dim_c(dim, id, j)) && (!over.contains_key(id) ==> dim_w(dim, id, j)
            == 0 && dim_c(dim, id, j) == 0)
}

proof fn lemma_dim_c_bound(dim: &Cols_dim, id: u32, j: int)
    requires
        valid_cols_dim(dim),
        0 <= j <= dim.n,
    ensures
        0 <= dim_c(dim, id, j) <= dim.n - j,
    decreases dim.n - j,
{
    if j < dim.n {
        lemma_dim_c_bound(dim, id, j + 1);
    }
}

proof fn lemma_product_fits()
    ensures
        (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) < u64::MAX as int,
{
    assert((LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) < u64::MAX as int) by (compute_only);
}

pub exec fn run_query(t: &Cols_t, dim: &Cols_dim) -> (res: Option<u128>)
    requires
        valid_cols_t(t),
        valid_cols_dim(dim),
    ensures
        res == method_spec(t, dim),
{
    broadcast use vstd::std_specs::hash::axiom_u32_obeys_hash_table_key_model;
    let mut sums: Vec<(u128, u64)> = Vec::new();
    let mut j: usize = 0;
    while j < DENSE
        invariant
            j <= DENSE,
            sums.len() == j,
            forall|k: int| 0 <= k < j as int ==> sums@[k] == (0u128, 0u64),
        decreases DENSE - j,
    {
        sums.push((0u128, 0u64));
        j = j + 1;
    }
    let mut over: HashMapWithView<u32, (u128, u64)> = HashMapWithView::new();
    proof {
        assert forall|id: int| 0 <= id < DENSE as int implies sums@[id].0 == dim_w(dim, id as u32, dim.n as int)
            && sums@[id].1 as int == dim_c(dim, id as u32, dim.n as int) by {
        }
        assert(over@ =~= Map::<u32, (u128, u64)>::empty());
    }
    let mut i: usize = dim.n;
    while i > 0
        invariant
            i <= dim.n,
            valid_cols_dim(dim),
            slots_ok(sums@, dim, i as int),
            over_ok(over@, dim, i as int),
            forall|id: u32| over@.contains_key(id) ==> id >= DENSE as u32,
        decreases i,
    {
        let ghost j0 = i as int;
        i = i - 1;
        let id = dim.id[i];
        let w = dim.w[i];
        let ghost before_over = over@;
        proof {
            assert(slots_ok(sums@, dim, j0));
            assert(over_ok(before_over, dim, j0));
            assert(j0 == i as int + 1);
        }
        if id < DENSE as u32 {
            let idx = id as usize;
            let prev = sums[idx];
            proof {
                lemma_dim_c_bound(dim, id, j0);
                assert(prev.1 as int == dim_c(dim, id, j0));
                assert(prev.1 < u64::MAX);
            }
            let next_w = prev.0.wrapping_add(w as u128);
            let next_c = prev.1 + 1;
            let ghost before = sums@;
            sums.set(idx, (next_w, next_c));
            proof {
                assert(sums@ == before.update(idx as int, (next_w, next_c)));
                assert forall|k: int|
                    0 <= k < DENSE as int implies sums@[k].0 == dim_w(dim, k as u32, i as int)
                    && sums@[k].1 as int == dim_c(dim, k as u32, i as int) by {
                    if k == id as int {
                        assert(before[k].0 == dim_w(dim, id, j0));
                        assert(before[k].1 as int == dim_c(dim, id, j0));
                        assert(dim_w(dim, id, i as int) == wrapping_add(dim_w(dim, id, j0), w as u128));
                        assert(dim_c(dim, id, i as int) == dim_c(dim, id, j0) + 1);
                        assert(next_w == wrapping_add(before[k].0, w as u128));
                    } else {
                        assert(sums@[k] == before[k]);
                        assert(dim.id[i as int] != k as u32);
                        assert(before[k].0 == dim_w(dim, k as u32, j0));
                        assert(dim_w(dim, k as u32, i as int) == dim_w(dim, k as u32, j0));
                        assert(dim_c(dim, k as u32, i as int) == dim_c(dim, k as u32, j0));
                    }
                }
                assert(slots_ok(sums@, dim, i as int));
                assert(over@ == before_over);
                assert forall|k: u32|
                    k >= DENSE as u32 implies ({
                        &&& over@.contains_key(k) ==> over@[k].0 == dim_w(dim, k, i as int) && over@[k].1
                            as int == dim_c(dim, k, i as int)
                        &&& !over@.contains_key(k) ==> dim_w(dim, k, i as int) == 0 && dim_c(dim, k, i as int)
                            == 0
                    }) by {
                    assert(dim.id[i as int] != k);
                    assert(dim_w(dim, k, i as int) == dim_w(dim, k, j0));
                    assert(dim_c(dim, k, i as int) == dim_c(dim, k, j0));
                }
                assert(over_ok(over@, dim, i as int));
            }
        } else {
            let prev = match over.get(&id) {
                Some(v) => *v,
                None => (0u128, 0u64),
            };
            proof {
                lemma_dim_c_bound(dim, id, j0);
                assert(prev.1 < u64::MAX);
            }
            let next = (prev.0.wrapping_add(w as u128), prev.1 + 1);
            over.insert(id, next);
            proof {
                assert(over@ == before_over.insert(id, next));
                assert forall|k: int|
                    0 <= k < DENSE as int implies sums@[k].0 == dim_w(dim, k as u32, i as int)
                    && sums@[k].1 as int == dim_c(dim, k as u32, i as int) by {
                    assert(dim.id[i as int] != k as u32);
                    assert(sums@[k].0 == dim_w(dim, k as u32, j0));
                    assert(dim_w(dim, k as u32, i as int) == dim_w(dim, k as u32, j0));
                    assert(dim_c(dim, k as u32, i as int) == dim_c(dim, k as u32, j0));
                }
                assert(slots_ok(sums@, dim, i as int));
                assert forall|k: u32|
                    k >= DENSE as u32 implies ({
                        &&& over@.contains_key(k) ==> over@[k].0 == dim_w(dim, k, i as int) && over@[k].1
                            as int == dim_c(dim, k, i as int)
                        &&& !over@.contains_key(k) ==> dim_w(dim, k, i as int) == 0 && dim_c(dim, k, i as int)
                            == 0
                    }) by {
                    if k == id {
                        add_zero(w as u128);
                        if before_over.contains_key(id) {
                            assert(prev.0 == before_over[id].0);
                            assert(before_over[id].0 == dim_w(dim, id, j0));
                        } else {
                            assert(dim_w(dim, id, j0) == 0);
                            assert(prev.0 == 0);
                        }
                        assert(next.0 == wrapping_add(prev.0, w as u128));
                        assert(dim_w(dim, id, i as int) == wrapping_add(dim_w(dim, id, j0), w as u128));
                        assert(over@[id] == next);
                    } else {
                        assert(dim.id[i as int] != k);
                        assert(over@.contains_key(k) == before_over.contains_key(k));
                        assert(dim_w(dim, k, i as int) == dim_w(dim, k, j0));
                        assert(dim_c(dim, k, i as int) == dim_c(dim, k, j0));
                        if before_over.contains_key(k) {
                            assert(over@[k] == before_over[k]);
                        }
                    }
                }
                assert(over_ok(over@, dim, i as int));
            }
        }
    }
    let mut acc: u128 = 0;
    let mut cnt: u64 = 0;
    let mut r: usize = t.n;
    while r > 0
        invariant
            r <= t.n,
            valid_cols_t(t),
            valid_cols_dim(dim),
            slots_ok(sums@, dim, 0),
            over_ok(over@, dim, 0),
            forall|id: u32| over@.contains_key(id) ==> id >= DENSE as u32,
            acc == join_method_spec_helper(t, dim, r as int, 0).0,
            cnt as int == join_method_spec_helper(t, dim, r as int, 0).1,
            cnt as int <= ((t.n - r) as int) * (dim.n as int),
        decreases r,
    {
        r = r - 1;
        let id = t.dim_id[r];
        let amount = t.amount[r];
        let (weight, hits) = if id < DENSE as u32 {
            sums[id as usize]
        } else {
            match over.get(&id) {
                Some(v) => *v,
                None => (0u128, 0u64),
            }
        };
        proof {
            lemma_span(t, dim, r as int, 0);
            if id < DENSE as u32 {
                assert(weight == dim_w(dim, id, 0));
                assert(hits as int == dim_c(dim, id, 0));
            } else {
                assert(weight == dim_w(dim, id, 0));
                assert(hits as int == dim_c(dim, id, 0));
            }
            lemma_product_fits();
            lemma_dim_c_bound(dim, id, 0);
            assert(dim_c(dim, id, 0) <= dim.n as int);
            assert(cnt as int + (hits as int) <= ((t.n - r) as int) * (dim.n as int)) by (nonlinear_arith)
                requires
                    cnt as int <= ((t.n - (r + 1)) as int) * (dim.n as int),
                    hits as int <= dim.n as int,
                    (t.n - r) as int == (t.n - (r + 1)) as int + 1,
            {
            };
            assert(cnt as int + (hits as int) < u64::MAX as int) by (nonlinear_arith)
                requires
                    cnt as int + (hits as int) <= ((t.n - r) as int) * (dim.n as int),
                    t.n <= LEMMA_MAX_ROWS,
                    dim.n <= LEMMA_MAX_ROWS,
                    r < t.n,
                    (LEMMA_MAX_ROWS as int) * (LEMMA_MAX_ROWS as int) < u64::MAX as int,
            {
            };
        }
        acc = acc.wrapping_add((amount as u128).wrapping_mul(weight));
        cnt = cnt + hits;
        proof {
            assert(acc == join_method_spec_helper(t, dim, r as int, 0).0);
            assert(cnt as int == join_method_spec_helper(t, dim, r as int, 0).1);
        }
    }
    if cnt == 0 {
        None
    } else {
        Some(acc)
    }
}

}

fn env_usize(key: &str) -> usize {
    std::env::var(key).unwrap().parse().unwrap()
}

fn main() {
    let n = env_usize("SPEED_ROWS");
    let mut dim_id = Vec::with_capacity(n);
    let mut amount = Vec::with_capacity(n);
    for i in 0..n {
        dim_id.push((i % 1000) as u32);
        amount.push(((i as u64) * 17) % 1000);
    }
    let t = Cols_t { n, dim_id, amount };
    let mut id = Vec::with_capacity(1000);
    let mut w = Vec::with_capacity(1000);
    for j in 0..1000 {
        id.push(j as u32);
        w.push((j as u64) * 3);
    }
    let dim = Cols_dim { n: 1000, id, w };
    for _ in 0..env_usize("SPEED_WARMUP") {
        let _ = run_query(&t, &dim);
    }
    let mut samples = Vec::new();
    let mut last = None;
    for _ in 0..env_usize("SPEED_RUNS") {
        let t0 = std::time::Instant::now();
        last = Some(run_query(&t, &dim));
        samples.push(t0.elapsed().as_micros());
    }
    samples.sort();
    println!("RESULT:{:?}", last.unwrap());
    println!("SAMPLES_US:{samples:?}");
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
