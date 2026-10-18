    // assumptions = false + query template: the filter constant is the run_query argument `param_lo`, whose range is only its
    // type's (there are no catalog ranges). cost DECIMAL(38,2) has i128 cells and no cap: add with checked_add and decline
    // (None) when the exact total leaves i128.
    //   -- params: lo BIGINT
    //   SELECT SUM(cost) AS total FROM pre WHERE line > $lo
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = pre.n;
    while i > 0
        invariant
            i <= pre.n,
            valid_cols_pre(pre),
            acc as int == sum_total(pre, i as int, param_lo),
            any <==> exists|i0: int| #![trigger row_hit(pre, i0, param_lo)] i as int <= i0 && row_hit(pre, i0, param_lo),
        decreases i,
    {
        i -= 1;
        let line = pre.line[i];
        let cost = pre.cost[i];
        proof {
            assert(pre.line@.len() == pre.n as int);
            assert(pre.cost@.len() == pre.n as int);
            assert(row_hit(pre, i as int, param_lo) <==> ((line as int) > (param_lo as int)));
            assert(sum_total_val(pre, i as int) == cost as int);
            reveal_with_fuel(sum_total, 2);
        }
        if line > param_lo {
            match acc.checked_add(cost) {
                Some(next) => {
                    acc = next;
                },
                None => {
                    return None;
                },
            }
            any = true;
            proof {
                assert(row_hit(pre, i as int, param_lo));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].total is Some <==> any);
    }
    Some(res)
