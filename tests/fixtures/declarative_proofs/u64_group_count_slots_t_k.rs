let mut counts: Vec<u64> = Vec::new();
let mut c: usize = 0;
while c < KEY_CAP_t_k
    invariant
        c <= KEY_CAP_t_k,
        counts@.len() == c as int,
        forall|j: int| 0 <= j < c as int ==> counts@[j] == 0u64,
    decreases KEY_CAP_t_k - c,
{
    counts.push(0u64);
    c = c + 1;
}
let mut i: usize = cols.n;
while i > 0
    invariant
        i <= cols.n,
        valid_cols_t(cols),
        counts@.len() == KEY_CAP_t_k as int,
        forall|kk: int| 0 <= kk < KEY_CAP_t_k as int ==> counts@[kk] as int == group_count(cols.k@, i as int, kk as u64),
    decreases i,
{
    let i_old = i;
    i = i - 1;
    let k = cols.k[i];
    let idx: usize = k as usize;
    let prev = counts[idx];
    proof {
        let keys = cols.k@;
        let start = i_old as int;
        let ii = i as int;
        assert(keys.len() == cols.n as int);
        assert(ii + 1 == start);
        assert(keys[ii] == k);
        assert(0 <= (k as int) && (k as int) < (KEY_CAP_t_k as int));
        assert(idx as int == k as int);
        lemma_group_count_le_suffix(keys, ii, k);
        lemma_group_count_le_suffix(keys, start, k);
        lemma_group_count_witness(keys, start, k);
        assert(prev as int == group_count(keys, start, k));
        assert(group_count(keys, ii, k) == group_count(keys, start, k) + 1);
        assert(prev as int + 1 <= ROW_CAP_t);
    }
    let next = prev + 1;
    counts[idx] = next;
    proof {
        let keys = cols.k@;
        let ii = i as int;
        assert(counts@[k as int] == next);
        assert(next as int == group_count(keys, ii, k));
    }
}
let mut map: HashMapWithView<u64, u64> = HashMapWithView::new();
let mut c2: usize = 0;
while c2 < KEY_CAP_t_k
    invariant
        c2 <= KEY_CAP_t_k,
        counts@.len() == KEY_CAP_t_k as int,
        i == 0,
        forall|kk: int| 0 <= kk < KEY_CAP_t_k as int ==> counts@[kk] as int == group_count(cols.k@, 0, kk as u64),
        forall|k: u64|
            #[trigger] map@.contains_key(k) ==> k < (KEY_CAP_t_k as u64)
                && map@[k] == counts@[k as int]
                && counts@[k as int] > 0,
        forall|kk: int| 0 <= kk < c2 as int && counts@[kk] > 0 ==> map@.contains_key(kk as u64),
    decreases KEY_CAP_t_k - c2,
{
    let v = counts[c2];
    let ghost before = map@;
    if v > 0 {
        map.insert(c2 as u64, v);
    }
    proof {
        assert(counts@[c2 as int] == v);
        if v > 0 {
            assert(map@ == before.insert(c2 as u64, v));
            assert(map@[c2 as u64] == v);
        }
        assert forall|k: u64|
            #[trigger] map@.contains_key(k) ==> k < (KEY_CAP_t_k as u64)
                && map@[k] == counts@[k as int]
                && counts@[k as int] > 0
        by {
            if map@.contains_key(k) {
                if v > 0 && k == (c2 as u64) {
                    assert(map@[k] == v);
                    assert(counts@[c2 as int] == v);
                } else {
                    assert(before.contains_key(k));
                    assert(map@[k] == before[k]);
                }
            }
        };
    }
    c2 = c2 + 1;
}
proof {
    let keys = cols.k@;
    assert(c2 == KEY_CAP_t_k);
    assert forall|k: u64|
        #[trigger] map@.contains_key(k) <==> (exists|j: int| 0 <= j < cols.n as int && keys[j] == k)
    by {
        if map@.contains_key(k) {
            assert(counts@[k as int] as int == group_count(keys, 0, k));
            assert(counts@[k as int] > 0);
            lemma_group_count_witness(keys, 0, k);
        }
        if exists|j: int| 0 <= j < cols.n as int && keys[j] == k {
            let j = choose|j: int| 0 <= j < cols.n as int && keys[j] == k;
            assert(keys[j] == k);
            assert((k as int) < (KEY_CAP_t_k as int));
            lemma_group_count_witness(keys, 0, k);
            assert(group_count(keys, 0, k) > 0);
            assert(counts@[k as int] > 0);
            assert(map@.contains_key(k));
        }
    };
    assert forall|k: u64|
        #[trigger] map@.contains_key(k) ==> map@[k] as int == group_count(keys, 0, k)
    by {
        if map@.contains_key(k) {
            assert(map@[k] == counts@[k as int]);
            assert(counts@[k as int] as int == group_count(keys, 0, k));
        }
    };
}
map
