    let mut acc: u64 = 0;
    let mut i: usize = a.n;
    while i > 0
        invariant
            i <= a.n,
            valid_cols_t(a),
            valid_cols_t(b),
            acc as int == count_c(a, b, i as int),
            acc as int <= ((a.n - i) as int) * 4,
            a.n as int <= ROW_CAP_t as int,
            b.n as int <= ROW_CAP_t as int,
            ROW_CAP_t == 4,
        decreases i,
    {
        i -= 1;
        let mut inner: u64 = 0;
        let mut j: usize = b.n;
        while j > 0
            invariant
                j <= b.n,
                i < a.n,
                valid_cols_t(a),
                valid_cols_t(b),
                inner as int == count_c_d1(a, b, i as int, j as int),
                inner as int <= (b.n - j) as int,
                b.n as int <= ROW_CAP_t as int,
                ROW_CAP_t == 4,
            decreases j,
        {
            j -= 1;
            proof {
                reveal_with_fuel(count_c_d1, 2);
                assert(a.a@.len() == a.n as int);
                assert(b.a@.len() == b.n as int);
            }
            if a.a[i] < b.a[j] {
                inner = inner + 1;
            }
        }
        proof {
            reveal_with_fuel(count_c, 2);
        }
        acc = acc + inner;
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { c: acc });
    res
