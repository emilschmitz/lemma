// MUST FAIL: exact_q14_ratio_checked.rs with the per-row product price * (100 - discount) and 100 * N UNCHECKED and no
// decline. With no data assumption (no cap on any cell) both can leave i128, so Verus must reject this body.
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut n_acc: i128 = 0;
    let mut d_acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            valid_cols_lineitem(lineitem),
            n_acc as int == sum_promo_revenue__num(lineitem, i as int),
            d_acc as int == sum_promo_revenue__den(lineitem, i as int),
            any <==> exists|i0: int| #![trigger row_hit(lineitem, i0)] i as int <= i0 && row_hit(lineitem, i0),
        decreases i,
    {
        i -= 1;
        let ship = lineitem.l_shipdate[i];
        let qty = lineitem.l_quantity[i];
        let price = lineitem.l_extendedprice[i];
        let disc = lineitem.l_discount[i];
        proof {
            assert(lineitem.l_shipdate@.len() == lineitem.n as int);
            assert(lineitem.l_quantity@.len() == lineitem.n as int);
            assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
            assert(lineitem.l_discount@.len() == lineitem.n as int);
            assert(row_hit(lineitem, i as int) <==> ((ship as int) >= 9374 && (ship as int) < 9404));
            reveal_with_fuel(sum_promo_revenue__num, 2);
            reveal_with_fuel(sum_promo_revenue__den, 2);
        }
        if ship >= 9374 && ship < 9404 {
            let v = (price as i128) * (100i128 - (disc as i128));  // UNCHECKED
            proof {
                assert(sum_promo_revenue__den_val(lineitem, i as int) == v as int);
                assert(sum_promo_revenue__num_val(lineitem, i as int) == if (qty as int) > 10 { v as int } else { 0int });
            }
            match d_acc.checked_add(v) {
                Some(next) => {
                    d_acc = next;
                },
                None => {
                    return None;
                },
            }
            if qty > 10 {
                match n_acc.checked_add(v) {
                    Some(next) => {
                        n_acc = next;
                    },
                    None => {
                        return None;
                    },
                }
            }
            any = true;
            proof {
                assert(row_hit(lineitem, i as int));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    if !any {
        res.push(OutRow { promo_revenue: None });
        return Some(res);
    }
    let ghost nn = n_acc as int;
    let ghost dd = d_acc as int;
    let r: Rat;
    if d_acc == 0 {
        r = Rat { num: n_acc, den: 0 };
        proof {
            assert(10000 * nn * 10000 == 100000000 * nn);
        }
    } else {
        let hundred_n = n_acc * 100;  // UNCHECKED
        if d_acc > 0 {
            r = Rat { num: hundred_n, den: d_acc };
            proof {
                assert((nn * 100) * (dd * 1000000) == (10000 * nn * 10000) * dd) by (nonlinear_arith);
            }
        } else {
            if hundred_n == i128::MIN || d_acc == i128::MIN {
                return None;  // the negation leaves i128
            }
            r = Rat { num: -hundred_n, den: -d_acc };
            proof {
                assert((-(nn * 100)) * (dd * 1000000) == (10000 * nn * 10000) * (-dd)) by (nonlinear_arith);
            }
        }
    }
    proof {
        assert(rat_is(r, 10000 * sum_promo_revenue__num(lineitem, 0) * 10000, sum_promo_revenue__den(lineitem, 0) * 1000000));
    }
    res.push(OutRow { promo_revenue: Some(r) });
    Some(res)
// AGENT_EDIT_END
