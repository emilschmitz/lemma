    let mut acc: u64 = 0;
    let mut i: usize = t.n;
    while i > 0
        invariant
            i <= t.n,
            valid_cols_t(t),
            acc as int == count_c(t, i as int),
            acc as int <= (t.n - i) as int,
            t.n as int <= ROW_CAP_t as int,
        decreases i,
    {
        i -= 1;
        let a = t.a[i];
        proof {
            assert(t.a@.len() == t.n as int);
            reveal_with_fuel(count_c, 2);
        }
        if a > 1 {
            acc = acc + 1;
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { c: acc });
    res
