    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = pre.n;
    while i > 0
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            acc as int == sum_total(pre, i as int),
            -((pre.n - i) as int) * 0x8000_0000_0000_0000int <= acc as int,
            acc as int <= ((pre.n - i) as int) * 0x8000_0000_0000_0000int,
            any <==> exists|i0: int| #![trigger row_hit(pre, i0)] i as int <= i0 && row_hit(pre, i0),
        decreases i,
    {
        i -= 1;
        let line = pre.line[i];
        proof {
            assert(pre.line@.len() == pre.n as int);
            assert(row_hit(pre, i as int) <==> ((line as int) > 5));
            assert(sum_total_val(pre, i as int) == line as int);
            reveal_with_fuel(sum_total, 2);
        }
        if line > 5 {
            acc = acc + (line as i128);
            any = true;
            proof {
                assert(row_hit(pre, i as int));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].total is Some <==> any);
    }
    res
