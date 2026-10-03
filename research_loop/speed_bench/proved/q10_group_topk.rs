use vstd::hash_map::HashMapWithView;
use vstd::prelude::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;
pub const DENSE: usize = 1024;

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

pub open spec fn group_keys_helper(cols: &Cols, k: int) -> Seq<u32>
    recommends
        0 <= k && k <= cols.n,
        valid_cols(cols),
    decreases cols.n - k,
{
    if k < cols.n {
        let tail = group_keys_helper(cols, k + 1);
        let key = cols.k[k as int];
        if tail.contains(key) {
            tail
        } else {
            tail.push(key)
        }
    } else {
        Seq::empty()
    }
}

pub open spec fn spec_group_before(a: (u32, u128), b: (u32, u128)) -> bool {
    if (a.1) != (b.1) {
        (b.1) < (a.1)
    } else {
        (a.0) < (b.0)
    }
}

pub open spec fn spec_seq_insert_by<A>(s: Seq<A>, x: A, before: spec_fn(A, A) -> bool) -> Seq<A>
    decreases s.len(),
{
    if s.len() == 0 {
        Seq::<A>::empty().push(x)
    } else if before(x, s[0]) {
        Seq::<A>::empty().push(x) + s
    } else {
        Seq::<A>::empty().push(s[0]) + spec_seq_insert_by(s.subrange(1, s.len() as int), x, before)
    }
}

pub open spec fn spec_seq_sort_by<A>(s: Seq<A>, before: spec_fn(A, A) -> bool) -> Seq<A>
    decreases s.len(),
{
    if s.len() == 0 {
        s
    } else {
        spec_seq_insert_by(
            spec_seq_sort_by(s.subrange(0, s.len() - 1), before),
            s[s.len() - 1],
            before,
        )
    }
}

pub open spec fn spec_map_at_keys<K, V>(keys: Seq<K>, m: Map<K, V>, i: int) -> Seq<(K, V)>
    decreases keys.len() - i,
{
    if i >= keys.len() {
        Seq::empty()
    } else {
        let rest = spec_map_at_keys(keys, m, i + 1);
        if m.contains_key(keys[i]) {
            Seq::<(K, V)>::empty().push((keys[i], m[keys[i]])) + rest
        } else {
            rest
        }
    }
}

pub open spec fn spec_map_at_keys_prefix<K, V>(keys: Seq<K>, m: Map<K, V>, n: int) -> Seq<(K, V)>
    decreases n,
{
    if n <= 0 {
        Seq::empty()
    } else {
        let prev = spec_map_at_keys_prefix(keys, m, n - 1);
        if 0 <= n - 1 < keys.len() && m.contains_key(keys[n - 1]) {
            prev.push((keys[n - 1], m[keys[n - 1]]))
        } else {
            prev
        }
    }
}

pub proof fn lemma_map_at_keys_prefix_complete<K, V>(keys: Seq<K>, m: Map<K, V>, n: int)
    requires
        0 <= n,
        n <= keys.len(),
    ensures
        spec_map_at_keys_prefix(keys, m, n) + spec_map_at_keys(keys, m, n) == spec_map_at_keys(
            keys,
            m,
            0,
        ),
    decreases n,
{
    if n > 0 {
        lemma_map_at_keys_prefix_complete(keys, m, n - 1);
        let prev = spec_map_at_keys_prefix(keys, m, n - 1);
        let rest = spec_map_at_keys(keys, m, n);
        let here = spec_map_at_keys(keys, m, n - 1);
        assert(n - 1 < keys.len());
        if m.contains_key(keys[n - 1]) {
            let pair = (keys[n - 1], m[keys[n - 1]]);
            let one = Seq::<(K, V)>::empty().push(pair);
            assert(here == one + rest);
            assert(spec_map_at_keys_prefix(keys, m, n) == prev.push(pair));
            assert(prev.push(pair) == prev + one);
            assert(prev + here == (prev + one) + rest);
        } else {
            assert(here == rest);
            assert(spec_map_at_keys_prefix(keys, m, n) == prev);
        }
    }
}

pub open spec fn spec_seq_take<A>(s: Seq<A>, n: int) -> Seq<A> {
    if n <= 0 {
        Seq::empty()
    } else if n >= s.len() {
        s
    } else {
        s.subrange(0, n)
    }
}

#[verifier::external_body]
pub exec fn exec_sort_by(s: Vec<(u32, u128)>) -> (res: Vec<(u32, u128)>)
    ensures
        res@ == spec_seq_sort_by(
            s@,
            |a: (u32, u128), b: (u32, u128)| spec_group_before(a, b),
        ),
{
    let before = |a: &(u32, u128), b: &(u32, u128)| -> bool {
        if (a.1) != (b.1) {
            (b.1) < (a.1)
        } else {
            (a.0) < (b.0)
        }
    };
    let mut v = s;
    v.sort_by(|a, b| {
        if before(a, b) {
            std::cmp::Ordering::Less
        } else if before(b, a) {
            std::cmp::Ordering::Greater
        } else {
            std::cmp::Ordering::Equal
        }
    });
    v
}

pub open spec fn method_spec(cols: &Cols) -> Seq<(u32, u128)>
    recommends
        valid_cols(cols),
{
    let projected = method_spec_helper(cols, 0);
    let keys = group_keys_helper(cols, 0);
    spec_seq_take(
        spec_seq_sort_by(
            spec_map_at_keys(keys, projected, 0),
            |a: (u32, u128), b: (u32, u128)| spec_group_before(a, b),
        ),
        5,
    )
}

proof fn lemma_push_contains(s: Seq<u32>, x: u32, y: u32)
    ensures
        s.push(x).contains(y) == (s.contains(y) || y == x),
{
    vstd::seq_lib::lemma_seq_contains_after_push(s, x, y);
}

proof fn lemma_key_in_both(cols: &Cols, i: int, key: u32)
    requires
        valid_cols(cols),
        0 <= i <= cols.n,
    ensures
        group_keys_helper(cols, i).contains(key) == method_spec_helper(cols, i).contains_key(key),
    decreases cols.n - i,
{
    if i < cols.n {
        lemma_key_in_both(cols, i + 1, key);
        let k0 = cols.k[i as int];
        let tail_keys = group_keys_helper(cols, i + 1);
        let tail_map = method_spec_helper(cols, i + 1);
        assert(tail_keys.contains(key) == tail_map.contains_key(key));
        if key == k0 {
            assert(method_spec_helper(cols, i).contains_key(key));
            if tail_keys.contains(k0) {
                assert(group_keys_helper(cols, i).contains(key));
            } else {
                assert(group_keys_helper(cols, i) == tail_keys.push(k0));
                lemma_push_contains(tail_keys, k0, key);
                assert(group_keys_helper(cols, i).contains(key));
            }
        } else {
            assert(method_spec_helper(cols, i).contains_key(key) == tail_map.contains_key(key));
            if tail_keys.contains(k0) {
                assert(group_keys_helper(cols, i) == tail_keys);
            } else {
                assert(group_keys_helper(cols, i) == tail_keys.push(k0));
                lemma_push_contains(tail_keys, k0, key);
                assert(group_keys_helper(cols, i).contains(key) == tail_keys.contains(key));
            }
        }
    }
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

proof fn lemma_seen_from_dense(seen: Seq<bool>, vals: Seq<u128>, key: int, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= key < DENSE as int,
        0 <= i <= key,
        dense_map(seen, vals, i).contains_key(key as u32),
    ensures
        seen[key],
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        if i == key {
            if !seen[i] {
                lemma_dense_absent(seen, vals, key, i);
                assert(false);
            }
        } else {
            lemma_seen_from_dense(seen, vals, key, i + 1);
        }
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

pub exec fn run_query(cols: &Cols) -> (res: Vec<(u32, u128)>)
    requires
        valid_cols(cols),
    ensures
        res@ == method_spec(cols),
{
    broadcast use vstd::std_specs::hash::axiom_u32_obeys_hash_table_key_model;
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
    let mut overflow = HashMapWithView::<u32, u128>::new();
    let mut keys: Vec<u32> = Vec::new();
    proof {
        lemma_dense_empty(seen@, vals@, 0);
    }
    assert(group_view(seen@, vals@, overflow@) =~= Map::<u32, u128>::empty());
    assert(keys@ =~= Seq::<u32>::empty());
    let mut i: usize = cols.n;
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            seen.len() == DENSE,
            vals.len() == DENSE,
            group_view(seen@, vals@, overflow@) == method_spec_helper(cols, i as int),
            keys@ == group_keys_helper(cols, i as int),
            forall|key: u32|
                overflow@.contains_key(key) ==> key >= DENSE as u32 && overflow@[key]
                    <= ((cols.n - i) as u128) * (u64::MAX as u128),
            forall|t: int|
                0 <= t < DENSE as int && seen@[t] ==> vals@[t] <= ((cols.n - i) as u128)
                    * (u64::MAX as u128),
        decreases i,
    {
        let ghost bound = ((cols.n - i) as u128) * (u64::MAX as u128);
        i = i - 1;
        let key = cols.key_exec(i);
        let ghost before_seen = seen@;
        let ghost before_vals = vals@;
        let ghost before_over = overflow@;
        if key < DENSE as u32 {
            let idx = key as usize;
            let already = seen[idx];
            proof {
                lemma_key_in_both(cols, (i + 1) as int, key);
                assert(forall|k: u32| overflow@.contains_key(k) ==> k >= DENSE as u32);
                assert(!overflow@.contains_key(key));
                if already {
                    lemma_dense_get(seen@, vals@, key as int, 0);
                } else {
                    lemma_dense_absent(seen@, vals@, key as int, 0);
                }
                assert(already == group_view(seen@, vals@, overflow@).contains_key(key));
                assert(already == keys@.contains(key));
            }
            if !already {
                keys.push(key);
                assert(keys@ == group_keys_helper(cols, (i + 1) as int).push(key));
            }
            assert(keys@ == group_keys_helper(cols, i as int));
            let prev = if seen[idx] {
                vals[idx]
            } else {
                0u128
            };
            let a = cols.get_amount_exec(i);
            proof {
                lemma_rows_fit();
            }
            assert(prev <= bound);
            assert(bound == ((cols.n - (i + 1)) as u128) * (u64::MAX as u128));
            assert(a as u128 <= u64::MAX as u128);
            assert(prev + (a as u128) <= ((cols.n - i) as u128) * (u64::MAX as u128)) by (nonlinear_arith)
                requires
                    prev <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
                    a as u128 <= u64::MAX as u128,
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
            let next = prev + (a as u128);
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
            let already = overflow.contains_key(&key);
            proof {
                lemma_key_in_both(cols, (i + 1) as int, key);
                lemma_dense_keys_below(seen@, vals@, key, 0);
                assert(already == group_view(seen@, vals@, overflow@).contains_key(key));
                assert(already == keys@.contains(key));
            }
            if !already {
                keys.push(key);
                assert(keys@ == group_keys_helper(cols, (i + 1) as int).push(key));
            }
            assert(keys@ == group_keys_helper(cols, i as int));
            let prev = match overflow.get(&key) {
                Some(v) => *v,
                None => 0u128,
            };
            let a = cols.get_amount_exec(i);
            proof {
                lemma_rows_fit();
            }
            assert(prev <= bound);
            assert(bound == ((cols.n - (i + 1)) as u128) * (u64::MAX as u128));
            assert(a as u128 <= u64::MAX as u128);
            assert(prev + (a as u128) <= ((cols.n - i) as u128) * (u64::MAX as u128)) by (nonlinear_arith)
                requires
                    prev <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
                    a as u128 <= u64::MAX as u128,
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
            let next = prev + (a as u128);
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
    let ghost map = group_view(seen@, vals@, overflow@);
    assert(map == method_spec_helper(cols, 0));
    assert(keys@ == group_keys_helper(cols, 0));
    let mut rows: Vec<(u32, u128)> = Vec::new();
    let mut j: usize = 0;
    while j < keys.len()
        invariant
            valid_cols(cols),
            j <= keys.len(),
            keys@ == group_keys_helper(cols, 0),
            map == method_spec_helper(cols, 0),
            seen.len() == DENSE,
            vals.len() == DENSE,
            forall|k: u32| overflow@.contains_key(k) ==> k >= DENSE as u32,
            group_view(seen@, vals@, overflow@) == map,
            rows@ == spec_map_at_keys_prefix(keys@, map, j as int),
        decreases keys.len() - j,
    {
        let key = keys[j];
        proof {
            lemma_key_in_both(cols, 0, key);
            assert(keys@.contains(key));
            assert(map.contains_key(key));
        }
        let val = if key < DENSE as u32 {
            let idx = key as usize;
            proof {
                assert(group_view(seen@, vals@, overflow@) == dense_map(seen@, vals@, 0).union_prefer_right(overflow@));
                assert(!overflow@.contains_key(key));
                assert(dense_map(seen@, vals@, 0).contains_key(key));
                lemma_seen_from_dense(seen@, vals@, key as int, 0);
                lemma_dense_get(seen@, vals@, key as int, 0);
                assert(map[key] == vals@[key as int]);
            }
            vals[idx]
        } else {
            proof {
                lemma_dense_keys_below(seen@, vals@, key, 0);
            }
            *overflow.get(&key).unwrap()
        };
        proof {
            assert(val == map[key]);
        }
        rows.push((key, val));
        j = j + 1;
    }
    proof {
        lemma_map_at_keys_prefix_complete(keys@, map, keys@.len() as int);
        assert(spec_map_at_keys(keys@, map, keys@.len() as int) =~= Seq::<(u32, u128)>::empty());
        assert(rows@ == spec_map_at_keys(keys@, map, 0));
    }
    let sorted = exec_sort_by(rows);
    let ntake: usize = if sorted.len() < 5 {
        sorted.len()
    } else {
        5
    };
    let mut out: Vec<(u32, u128)> = Vec::new();
    let mut t: usize = 0;
    while t < ntake
        invariant
            t <= ntake,
            ntake == sorted.len() || ntake == 5,
            ntake <= sorted.len(),
            out@ == sorted@.subrange(0, t as int),
        decreases ntake - t,
    {
        out.push(sorted[t]);
        t = t + 1;
        assert(out@ == sorted@.subrange(0, t as int));
    }
    proof {
        if sorted@.len() <= 5 {
            assert(ntake == sorted.len());
            assert(out@ == sorted@);
            assert(spec_seq_take(sorted@, 5) == sorted@);
        } else {
            assert(ntake == 5);
            assert(out@ == sorted@.subrange(0, 5));
            assert(spec_seq_take(sorted@, 5) == sorted@.subrange(0, 5));
        }
    }
    out
}

}

fn main() {
    let n: usize = 2_000_000;
    let mut k = Vec::with_capacity(n);
    let mut amount = Vec::with_capacity(n);
    for i in 0..n {
        k.push((i % 32) as u32);
        amount.push(((i as u64) * 17) % 1000);
    }
    let cols = Cols { n, k, amount };
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
    println!("RESULT:{:?}", last.unwrap());
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
