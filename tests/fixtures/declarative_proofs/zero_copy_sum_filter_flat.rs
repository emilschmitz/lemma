// Control for zero_copy_sum_filter.rs: the SAME query on a flat `Vec<i128>` column (the unchanged spec, the copy path). Used only to time the
// copy against the borrowed-chunk run on identical machinery (research_loop/scripts/zero_copy_oneshot.py, mode=copy).
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = num.n;
    while i > 0
        invariant
            i <= num.n,
            valid_cols_num(num),
            num.n <= 2147483648,
            acc as int == sum_total(num, i as int),
            any <==> exists|i0: int| #![trigger row_hit(num, i0)] i as int <= i0 < num.n as int && row_hit(num, i0),
            -((num.n - i) as int) * 46116860184273879039999int <= acc as int,
            acc as int <= ((num.n - i) as int) * 46116860184273879039999int,
        decreases i,
    {
        i -= 1;
        let v = num.value[i];
        proof {
            assert(num.value@.len() == num.n as int);
            reveal_with_fuel(sum_total, 2);
            assert(row_hit(num, i as int) <==> ((v as int) > 50000000));
            let rem = num.n as int - (i as int + 1);
            assert((rem + 1) * 46116860184273879039999int == rem * 46116860184273879039999int + 46116860184273879039999int) by (nonlinear_arith);
            assert((rem + 1) * 46116860184273879039999int <= 2147483648int * 46116860184273879039999int) by (nonlinear_arith)
                requires rem + 1 <= 2147483648int, rem + 1 >= 0;
        }
        if v > 50000000 {
            acc = acc + v;
            any = true;
            proof {
                assert(row_hit(num, i as int));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].total is Some <==> any);
    }
    res
// AGENT_EDIT_END
