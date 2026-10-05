// SELECT COUNT(*) AS c FROM part WHERE NOT EXISTS (SELECT SUM(price) AS s FROM li WHERE qty > 100)
// NOT EXISTS over an ungrouped aggregate is FALSE for every part row: the count is 0.
    let mut acc: u64 = 0;
    let mut i: usize = part.n;
    while i > 0
        invariant
            i <= part.n,
            valid_cols_part(part),
            acc as int == count_c(part, li, i as int),
            acc == 0,
            part.n as int <= ROW_CAP_part as int,
        decreases i,
    {
        i -= 1;
        proof {
            reveal_with_fuel(count_c, 2);
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { c: acc });
    res
