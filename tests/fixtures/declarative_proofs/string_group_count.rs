    let mut i: usize = cols.n;
    let mut map: StringHashMap<u64> = StringHashMap::new();
    while i > 0
        invariant
            i <= cols.n,
            valid_cols_num(cols),
            forall|k: Seq<char>|
                #[trigger] map@.contains_key(k) <==> (exists|j: int|
                    i as int <= j < cols.n as int && cols.uom@[j]@ == k),
            forall|k: Seq<char>|
                map@.contains_key(k) ==> map@[k] as int == group_count(cols.uom@, i as int, k),
        decreases i,
    {
        let i_old = i;
        i = i - 1;
        let key: &String = &cols.uom[i];
        let prev: u64 = if map.contains_key(key.as_str()) {
            *map.get(key.as_str()).unwrap()
        } else {
            0
        };
        proof {
            let keys = cols.uom@;
            let start = i_old as int;
            let ii = i as int;
            assert(ii + 1 == start);
            assert(keys.len() == cols.n as int);
            assert(keys[ii]@ == key@);
            lemma_group_count_le_suffix(keys, ii, key@);
            lemma_group_count_le_suffix(keys, start, key@);
            lemma_group_count_witness(keys, start, key@);
            if map@.contains_key(key@) {
                assert(prev as int == group_count(keys, start, key@));
                assert(group_count(keys, ii, key@) == group_count(keys, start, key@) + 1);
                assert(group_count(keys, ii, key@) <= keys.len() - ii);
                assert(prev as int + 1 <= ROW_CAP_num);
            } else {
                assert(!(exists|j: int| start <= j < keys.len() && keys[j]@ == key@));
                assert(group_count(keys, start, key@) == 0);
                assert(group_count(keys, ii, key@) == 1);
                assert(prev == 0);
                assert(prev as int + 1 <= ROW_CAP_num);
            }
            lemma_count_step_fits_u64(prev, ROW_CAP_num);
        }
        let next = prev + 1;
        map.insert(key.clone(), next);
        proof {
            let keys = cols.uom@;
            let ii = i as int;
            assert(next as int == group_count(keys, ii, key@));
            assert forall|k: Seq<char>| map@.contains_key(k) implies map@[k] as int == group_count(keys, ii, k) by {
                if k != key@ {
                    assert(keys[ii]@ != k);
                }
            }
        }
    }
    map
