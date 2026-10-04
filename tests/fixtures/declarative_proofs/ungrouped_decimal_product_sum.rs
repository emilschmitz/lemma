// Worked example: ungrouped SUM of a product of two DECIMAL(15,2) columns (scaled i64 cells) under a date range
// and a discount/quantity filter (the shape of a TPC-H Q6 style query).
// 1. `mul_small` (helper region): nonlinear_arith bounds the product from the cell bounds, so the `i128` add fits.
// 2. Branch-free accumulate: `let t = if hit { price * disc } else { 0 }; acc = acc + t;` is about 1.7x faster than
//    `if hit { acc = acc + price * disc }` here, because the filter is unpredictable. Use `&&` on bools, not `&`
//    (Verus rejects the non-short-circuit form). Cheap range test first, the other columns inside it.
// 3. The loop invariant ties `acc` to the host fold `sum_revenue(...)` and bounds it by (rows seen) * cell bound.
// AGENT_HELPERS_START
proof fn mul_small(p: i128, d: i128)
    requires -999999999999999 <= p <= 999999999999999, 8 <= d <= 10,
    ensures -10000000000000000 <= p * d <= 10000000000000000,
{
    assert(p * d <= 10 * 999999999999999) by (nonlinear_arith)
        requires p <= 999999999999999, 8 <= d <= 10, -999999999999999 <= p;
    assert(p * d >= 10 * -999999999999999) by (nonlinear_arith)
        requires p <= 999999999999999, 8 <= d <= 10, -999999999999999 <= p;
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            valid_cols_lineitem(lineitem),
            acc as int == sum_revenue(lineitem, i as int),
            -((lineitem.n - i) as int) * 10000000000000000int <= acc as int,
            acc as int <= ((lineitem.n - i) as int) * 10000000000000000int,
            any <==> exists|i0: int| #![trigger row_hit(lineitem, i0)] i as int <= i0 && row_hit(lineitem, i0),
        decreases i,
    {
        i -= 1;
        let sd = lineitem.l_shipdate[i];
        proof {
            assert(lineitem.l_shipdate@.len() == lineitem.n as int);
            reveal_with_fuel(sum_revenue, 2);
        }
        if sd >= 8766 && sd < 9131 {
            let disc = lineitem.l_discount[i];
            let qty = lineitem.l_quantity[i];
            let price = lineitem.l_extendedprice[i];
            let hit: bool = (disc >= 8) && (disc <= 10) && (qty < 2500);
            let t: i128 = if hit {
                proof { mul_small(price as i128, disc as i128); }
                (price as i128) * (disc as i128)
            } else { 0 };
            acc = acc + t;
            any = any || hit;
            proof {
                assert(hit <==> row_hit(lineitem, i as int));
            }
        } else {
            proof {
                assert(!row_hit(lineitem, i as int));
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { revenue: if any { Some(acc) } else { None } });
    proof {
        assert(res@[0].revenue is Some <==> any);
    }
    res
// AGENT_EDIT_END
