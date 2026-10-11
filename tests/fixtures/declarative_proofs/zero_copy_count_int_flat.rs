// Control for zero_copy_count_int.rs: the same COUNT on a flat Vec<i32> column (the copy path).
//   SELECT COUNT(*) AS n FROM num WHERE qtrs = 3
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut acc: u64 = 0;
    let mut i: usize = num.n;
    while i > 0
        invariant
            i <= num.n,
            valid_cols_num(num),
            acc as int == count_n(num, i as int),
            acc as int <= num.n as int - i as int,
        decreases i,
    {
        i -= 1;
        let v = num.qtrs[i];
        proof {
            assert(num.qtrs@.len() == num.n as int);
            reveal_with_fuel(count_n, 2);
            assert(row_hit(num, i as int) <==> ((v as int) == 3));
        }
        if v == 3 {
            acc = acc + 1;
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { n: acc });
    res
// AGENT_EDIT_END
