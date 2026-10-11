// Control for zero_copy_sum_two_cols.rs: the same query on flat Vec<i64> columns (the copy path).
//   SELECT SUM(l_extendedprice) AS s FROM lineitem WHERE l_quantity < 24
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            valid_cols_lineitem(lineitem),
            lineitem.n <= 6001215,
            acc as int == sum_s(lineitem, i as int),
            any <==> exists|i0: int| #![trigger row_hit(lineitem, i0)] i as int <= i0 < lineitem.n as int && row_hit(lineitem, i0),
            -((lineitem.n - i) as int) * 999999999999999int <= acc as int,
            acc as int <= ((lineitem.n - i) as int) * 999999999999999int,
        decreases i,
    {
        i -= 1;
        let p = lineitem.l_extendedprice[i];
        let q = lineitem.l_quantity[i];
        proof {
            assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
            assert(lineitem.l_quantity@.len() == lineitem.n as int);
            reveal_with_fuel(sum_s, 2);
            assert(row_hit(lineitem, i as int) <==> ((q as int) < 2400));
            assert(sum_s_val(lineitem, i as int) == p as int);
            let rem = lineitem.n as int - (i as int + 1);
            assert((rem + 1) * 999999999999999int == rem * 999999999999999int + 999999999999999int) by (nonlinear_arith);
            assert((rem + 1) * 999999999999999int <= 6001215int * 999999999999999int) by (nonlinear_arith)
                requires rem + 1 <= 6001215int, rem + 1 >= 0;
        }
        if q < 2400 {
            acc = acc + (p as i128);
            any = true;
            proof {
                assert(row_hit(lineitem, i as int));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { s: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].s is Some <==> any);
    }
    res
// AGENT_EDIT_END
