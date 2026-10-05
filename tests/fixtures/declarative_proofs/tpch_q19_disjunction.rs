// Worked example: TPC-H Q19, an ungrouped SUM over lineitem x part under three disjuncts, each a conjunction of an equality
// join, string equalities, `IN` lists, integer ranges (DECIMAL quantities are stored as integers: `>= 1` is `>= 100`):
//   SELECT SUM(l_extendedprice * (1 - l_discount)) AS revenue FROM lineitem, part WHERE
//     (p_partkey = l_partkey AND p_brand = 'Brand#12' AND p_container IN ('SM CASE','SM BOX','SM PACK','SM PKG')
//        AND l_quantity >= 1 AND l_quantity <= 1 + 10 AND p_size BETWEEN 1 AND 5
//        AND l_shipmode IN ('AIR','AIR REG') AND l_shipinstruct = 'DELIVER IN PERSON') OR (... Brand#23 ...) OR (... Brand#34 ...)
// Reference body (sequential nested loop): the exec predicate mirrors the emitted `row_hit` conjunct for conjunct, with every
// string equality a `String == String` against `String::from_str("..")` (ensures `ret@ == "..."@`; `==` ensures
// `res == (a@ == b@)`). The sum is folded backwards over the pairs like `tpch_q14_promo_ratio.rs`; `any` says some pair hit
// (SUM of no rows is NULL).
// Assumption of this body: ROW_CAP_lineitem * ROW_CAP_part * (1.1e30 per-pair bound) fits i128 (caps' product at most 1.5e8).
// AGENT_HELPERS_START
proof fn lemma_term_bound(a: int, b: int)
    requires -999999999999999int <= a <= 999999999999999int, -999999999999999int <= b <= 999999999999999int,
    ensures -1100000000000000000000000000000int <= a * (100 - b) <= 1100000000000000000000000000000int,
{
    assert(-1000000000000099int <= 100 - b <= 1000000000000099int);
    assert(a * (100 - b) <= 999999999999999int * 1000000000000099int) by (nonlinear_arith)
        requires -999999999999999int <= a <= 999999999999999int, -1000000000000099int <= 100 - b <= 1000000000000099int;
    assert(a * (100 - b) >= -(999999999999999int * 1000000000000099int)) by (nonlinear_arith)
        requires -999999999999999int <= a <= 999999999999999int, -1000000000000099int <= 100 - b <= 1000000000000099int;
}

proof fn lemma_pair_count_fits(m: int, nl: int, np: int)
    requires 0 <= m <= nl * np, 0 <= nl <= 60175, 0 <= np <= 2000,
    ensures m <= 120350000int,
{
    assert(nl * np <= 60175 * 2000) by (nonlinear_arith)
        requires 0 <= nl <= 60175, 0 <= np <= 2000;
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let ghost mut m: int = 0;
    let mut i0: usize = lineitem.n;
    while i0 > 0
        invariant
            i0 <= lineitem.n,
            valid_cols_lineitem(lineitem),
            valid_cols_part(part),
            acc as int == sum_revenue(lineitem, part, i0 as int),
            m == (lineitem.n as int - i0 as int) * (part.n as int),
            0 <= m <= lineitem.n as int * part.n as int,
            -m * 1100000000000000000000000000000int <= acc as int <= m * 1100000000000000000000000000000int,
            any <==> exists|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)]
                i0 as int <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b),
        decreases i0,
    {
        i0 -= 1;
        let ghost m_row = m;
        let mut i1: usize = part.n;
        proof {
            assert(sum_revenue_d1(lineitem, part, i0 as int, part.n as int) == 0);
            assert(m_row == (lineitem.n as int - i0 as int - 1) * (part.n as int));
            assert((lineitem.n as int - i0 as int) * (part.n as int) == m_row + part.n as int) by (nonlinear_arith)
                requires m_row == (lineitem.n as int - i0 as int - 1) * (part.n as int);
            assert(m_row + part.n as int <= lineitem.n as int * part.n as int) by (nonlinear_arith)
                requires m_row + part.n as int == (lineitem.n as int - i0 as int) * (part.n as int), 0 <= i0 as int;
            assert(i0 as int + 1 <= lineitem.n as int);
        }
        while i1 > 0
            invariant
                i0 < lineitem.n,
                i1 <= part.n,
                valid_cols_lineitem(lineitem),
                valid_cols_part(part),
                acc as int == sum_revenue_d1(lineitem, part, i0 as int, i1 as int) + sum_revenue(lineitem, part, i0 as int + 1),
                m == m_row + (part.n as int - i1 as int),
                m_row + part.n as int <= lineitem.n as int * part.n as int,
                0 <= m_row,
                m <= m_row + part.n as int,
                -m * 1100000000000000000000000000000int <= acc as int <= m * 1100000000000000000000000000000int,
                any <==> ((exists|b: int| #![trigger row_hit(lineitem, part, i0 as int, b)]
                    i1 as int <= b < part.n as int && row_hit(lineitem, part, i0 as int, b))
                    || (exists|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)]
                        i0 as int + 1 <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b))),
            decreases i1,
        {
            i1 -= 1;
            let ghost m_old = m;
            proof {
                m = m + 1;
                assert(lineitem.l_partkey@.len() == lineitem.n as int);
                assert(lineitem.l_quantity@.len() == lineitem.n as int);
                assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
                assert(lineitem.l_discount@.len() == lineitem.n as int);
                assert(lineitem.l_shipmode@.len() == lineitem.n as int);
                assert(lineitem.l_shipinstruct@.len() == lineitem.n as int);
                assert(part.p_partkey@.len() == part.n as int);
                assert(part.p_brand@.len() == part.n as int);
                assert(part.p_container@.len() == part.n as int);
                assert(part.p_size@.len() == part.n as int);
                reveal_with_fuel(sum_revenue_d1, 2);
                lemma_pair_count_fits(m, lineitem.n as int, part.n as int);
            }
            let price = lineitem.l_extendedprice[i0];
            let disc = lineitem.l_discount[i0];
            let qty = lineitem.l_quantity[i0];
            let size = part.p_size[i1];
            let join = lineitem.l_partkey[i0] == part.p_partkey[i1];
            let air = lineitem.l_shipmode[i0] == String::from_str("AIR") || lineitem.l_shipmode[i0] == String::from_str("AIR REG");
            let dip = lineitem.l_shipinstruct[i0] == String::from_str("DELIVER IN PERSON");
            let c1 = join && part.p_brand[i1] == String::from_str("Brand#12")
                && (part.p_container[i1] == String::from_str("SM CASE") || part.p_container[i1] == String::from_str("SM BOX")
                    || part.p_container[i1] == String::from_str("SM PACK") || part.p_container[i1] == String::from_str("SM PKG"))
                && qty >= 100 && qty <= 1100 && (size >= 1 && size <= 5) && air && dip;
            let c2 = join && part.p_brand[i1] == String::from_str("Brand#23")
                && (part.p_container[i1] == String::from_str("MED BAG") || part.p_container[i1] == String::from_str("MED BOX")
                    || part.p_container[i1] == String::from_str("MED PKG") || part.p_container[i1] == String::from_str("MED PACK"))
                && qty >= 1000 && qty <= 2000 && (size >= 1 && size <= 10) && air && dip;
            let c3 = join && part.p_brand[i1] == String::from_str("Brand#34")
                && (part.p_container[i1] == String::from_str("LG CASE") || part.p_container[i1] == String::from_str("LG BOX")
                    || part.p_container[i1] == String::from_str("LG PACK") || part.p_container[i1] == String::from_str("LG PKG"))
                && qty >= 2000 && qty <= 3000 && (size >= 1 && size <= 15) && air && dip;
            let hit = c1 || c2 || c3;
            proof {
                assert(row_hit(lineitem, part, i0 as int, i1 as int) <==> hit);
                lemma_term_bound(price as int, disc as int);
            }
            if hit {
                let val: i128 = (price as i128) * (100 - (disc as i128));
                proof {
                    assert(val as int == (lineitem.l_extendedprice@[i0 as int] as int) * (100 - (lineitem.l_discount@[i0 as int] as int)));
                    assert(sum_revenue_val(lineitem, part, i0 as int, i1 as int) == val as int);
                }
                acc = acc + val;
                any = true;
            }
            proof {
                if !hit {
                    assert(!row_hit(lineitem, part, i0 as int, i1 as int));
                }
                assert forall|b: int| #![trigger row_hit(lineitem, part, i0 as int, b)] i1 as int <= b < part.n as int && row_hit(lineitem, part, i0 as int, b)
                    implies (hit || exists|b2: int| #![trigger row_hit(lineitem, part, i0 as int, b2)] i1 as int + 1 <= b2 < part.n as int && row_hit(lineitem, part, i0 as int, b2)) by {
                    if b > i1 as int {
                        assert(i1 as int + 1 <= b < part.n as int);
                    }
                };
            }
        }
        proof {
            assert(sum_revenue(lineitem, part, i0 as int) == sum_revenue_d1(lineitem, part, i0 as int, 0) + sum_revenue(lineitem, part, i0 as int + 1)) by {
                reveal_with_fuel(sum_revenue, 2);
            };
            assert forall|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)] i0 as int <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b)
                implies (exists|b2: int| #![trigger row_hit(lineitem, part, i0 as int, b2)] 0 <= b2 < part.n as int && row_hit(lineitem, part, i0 as int, b2))
                    || exists|a2: int, b2: int| #![trigger row_hit(lineitem, part, a2, b2)] i0 as int + 1 <= a2 < lineitem.n as int && 0 <= b2 < part.n as int && row_hit(lineitem, part, a2, b2) by {
                if a == i0 as int {
                    assert(0 <= b < part.n as int);
                } else {
                    assert(i0 as int + 1 <= a < lineitem.n as int);
                }
            };
            assert(m == (lineitem.n as int - i0 as int) * (part.n as int));
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    if any {
        res.push(OutRow { revenue: Some(acc) });
        proof {
            assert(exists|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)] row_hit(lineitem, part, a, b));
            assert(res@[0].revenue is Some);
        }
    } else {
        res.push(OutRow { revenue: None });
        proof {
            assert(!(exists|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)] row_hit(lineitem, part, a, b)));
            assert(res@[0].revenue is None);
        }
    }
    res
// AGENT_EDIT_END
