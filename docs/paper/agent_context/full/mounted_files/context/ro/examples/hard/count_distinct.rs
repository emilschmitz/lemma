    // Sweep from the end: a row counts when no later row has the same value, i.e. its value is not
    // yet in `seen`, the set of values of rows i..n.
    let mut seen: HashSetWithView<i64> = HashSetWithView::new();
    let mut cnt: u64 = 0;
    let mut i: usize = pre.n;
    while i > 0
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            cnt as int == count_distinct_c(pre, i as int),
            cnt as int <= (pre.n - i) as int,
            forall|v: i64| #[trigger] seen@.contains(v) <==> exists|j: int| i as int <= j < pre.n as int && pre.report@[j] == v,
        decreases i,
    {
        i -= 1;
        let v = pre.report[i];
        proof {
            assert(pre.report@.len() == pre.n as int);
            lemma_count_distinct_c_bound(pre, i as int + 1);
            assert(row_hit(pre, i as int));
            assert(count_distinct_c_val(pre, i as int) == v as int);
        }
        let fresh = seen.insert(v);
        proof {
            // `fresh` is true exactly when no row j > i has value v.
            assert(fresh == !(exists|j: int| i as int + 1 <= j < pre.n as int && pre.report@[j] == v));
            assert(fresh == !(exists|j0: int| (j0 > i as int) && row_hit(pre, j0) && count_distinct_c_val(pre, j0) == count_distinct_c_val(pre, i as int))) by {
                if exists|j0: int| (j0 > i as int) && row_hit(pre, j0) && count_distinct_c_val(pre, j0) == count_distinct_c_val(pre, i as int) {
                    let j0 = choose|j0: int| (j0 > i as int) && row_hit(pre, j0) && count_distinct_c_val(pre, j0) == count_distinct_c_val(pre, i as int);
                    assert(pre.report@[j0] == v);
                }
                if exists|j: int| i as int + 1 <= j < pre.n as int && pre.report@[j] == v {
                    let j = choose|j: int| i as int + 1 <= j < pre.n as int && pre.report@[j] == v;
                    assert(row_hit(pre, j));
                    assert(count_distinct_c_val(pre, j) == count_distinct_c_val(pre, i as int));
                }
            };
            assert forall|w: i64| #[trigger] seen@.contains(w) <==> exists|j: int| i as int <= j < pre.n as int && pre.report@[j] == w by {
                if w == v {
                    assert(pre.report@[i as int] == w);
                }
            };
        }
        if fresh {
            cnt += 1;
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { c: cnt });
    res
