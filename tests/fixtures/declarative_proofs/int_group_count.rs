    let mut i: usize = cols.n;
    let mut map: HashMapWithView<i64, u64> = HashMapWithView::new();
    while i > 0
        invariant
            i <= cols.n,
            valid_cols_sub(cols),
            forall|k: i64|
                #[trigger] map@.contains_key(k) <==> (exists|j: int|
                    i as int <= j < cols.n as int && cols.fy@[j] == k),
            forall|k: i64|
                map@.contains_key(k) ==> map@[k] as int == group_count(cols.fy@, i as int, k),
        decreases i,
    {
        let i_old = i;
        proof {
            let keys = cols.fy@;
            let start = i_old as int;
            assert(keys.len() == cols.n as int);
            assert(0 < start);
            assert(0 <= ROW_CAP_sub <= u64::MAX as int);
        }
        i = i - 1;
        let k = cols.fy[i];
        let prev: u64 = if map.contains_key(&k) {
            *map.get(&k).unwrap()
        } else {
            0
        };
        proof {
            let keys = cols.fy@;
            let start = i_old as int;
            let ii = i as int;
            assert(ii + 1 == start);
            assert(keys[ii] == k);
            assert(keys.len() == cols.n as int);
            lemma_group_count_le_suffix(keys, ii, k);
            lemma_group_count_le_suffix(keys, start, k);
            lemma_group_count_witness(keys, start, k);
            if map@.contains_key(k) {
                assert(prev as int == group_count(keys, start, k));
                assert(group_count(keys, ii, k) == group_count(keys, start, k) + 1);
                assert(prev as int + 1 == group_count(keys, ii, k));
                assert(group_count(keys, ii, k) <= keys.len() - ii);
                assert(prev as int + 1 <= ROW_CAP_sub);
            } else {
                assert(!(exists|j: int| start <= j < keys.len() && keys[j] == k));
                assert(!(group_count(keys, start, k) > 0));
                assert(group_count(keys, start, k) == 0);
                assert(group_count(keys, ii, k) == 1);
                assert(prev == 0);
                assert(prev as int + 1 <= ROW_CAP_sub);
            }
            lemma_count_step_fits_u64(prev, ROW_CAP_sub);
            assert((prev + 1) as int == prev as int + 1);
        }
        let next = prev + 1;
        map.insert(k, next);
        proof {
            let keys = cols.fy@;
            let ii = i as int;
            assert(next as int == group_count(keys, ii, k));
        }
    }
    map
