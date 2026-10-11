// Worked example (LEMMA_ZERO_COPY=1): SUM over one DECIMAL(15,2) column filtered by another (two borrowed columns, i64 cells), TPC-H lineitem.
//   SELECT SUM(l_extendedprice) AS s FROM lineitem WHERE l_quantity < 24
// Both columns come from one pin, so they have the same chunk boundaries (`valid_cols` carries `l_quantity.offs@ == l_extendedprice.offs@`).
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let m: usize = lineitem.l_extendedprice.chunks.len();
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut k: usize = m;
    proof {
        assert(lineitem.l_quantity.offs@ == lineitem.l_extendedprice.offs@);
        assert(lineitem.l_quantity.chunks@.len() == m);
        assert(lineitem.l_extendedprice.off(m as int) == lineitem.n as int);
        assert(sum_s(lineitem, lineitem.n as int) == 0);
    }
    while k > 0
        invariant
            k <= m,
            m == lineitem.l_extendedprice.chunks@.len(),
            m == lineitem.l_quantity.chunks@.len(),
            lineitem.l_extendedprice.wf(),
            lineitem.l_quantity.wf(),
            lineitem.l_quantity.offs@ == lineitem.l_extendedprice.offs@,
            valid_cols_lineitem(lineitem),
            acc as int == sum_s(lineitem, lineitem.l_extendedprice.off(k as int)),
            any <==> exists|i0: int| #![trigger row_hit(lineitem, i0)] lineitem.l_extendedprice.off(k as int) <= i0 < lineitem.n as int && row_hit(lineitem, i0),
            -((lineitem.n as int - lineitem.l_extendedprice.off(k as int))) * 999999999999999int <= acc as int,
            acc as int <= (lineitem.n as int - lineitem.l_extendedprice.off(k as int)) * 999999999999999int,
        decreases k,
    {
        k -= 1;
        let pc: &[i64] = lineitem.l_extendedprice.chunks[k];
        let qc: &[i64] = lineitem.l_quantity.chunks[k];
        let base: usize = lineitem.l_extendedprice.offs[k];
        let ghost len = pc@.len() as int;
        proof {
            assert(lineitem.l_extendedprice.off(k as int + 1) == lineitem.l_extendedprice.off(k as int) + len);
            assert(lineitem.l_quantity.off(k as int + 1) == lineitem.l_quantity.off(k as int) + qc@.len());
            assert(lineitem.l_quantity.off(k as int) == lineitem.l_extendedprice.off(k as int));
            assert(lineitem.l_quantity.off(k as int + 1) == lineitem.l_extendedprice.off(k as int + 1));
            assert(qc@.len() == len);
        }
        let mut j: usize = pc.len();
        while j > 0
            invariant
                j <= pc.len(),
                pc.len() == qc.len(),
                k < m,
                m == lineitem.l_extendedprice.chunks@.len(),
                m == lineitem.l_quantity.chunks@.len(),
                lineitem.l_extendedprice.wf(),
                lineitem.l_quantity.wf(),
                lineitem.l_quantity.offs@ == lineitem.l_extendedprice.offs@,
                valid_cols_lineitem(lineitem),
                pc == lineitem.l_extendedprice.chunks@[k as int],
                qc == lineitem.l_quantity.chunks@[k as int],
                base == lineitem.l_extendedprice.off(k as int),
                base == lineitem.l_quantity.off(k as int),
                len == pc@.len() as int,
                lineitem.l_extendedprice.off(k as int + 1) == base as int + len,
                lineitem.n <= 6001215,
                acc as int == sum_s(lineitem, base as int + j as int),
                any <==> exists|i0: int| #![trigger row_hit(lineitem, i0)] base as int + j as int <= i0 < lineitem.n as int && row_hit(lineitem, i0),
                -((lineitem.n as int - (base as int + j as int))) * 999999999999999int <= acc as int,
                acc as int <= (lineitem.n as int - (base as int + j as int)) * 999999999999999int,
            decreases j,
        {
            j -= 1;
            let p: i64 = pc[j];
            let q: i64 = qc[j];
            proof {
                lemma_cell(&lineitem.l_extendedprice, k as int, j as int);
                lemma_cell(&lineitem.l_quantity, k as int, j as int);
                let g = base as int + j as int;
                assert(g == lineitem.l_extendedprice.off(k as int) + j as int);
                assert(g == lineitem.l_quantity.off(k as int) + j as int);
                assert(lineitem.l_extendedprice@[g] == pc@[j as int]);
                assert(lineitem.l_quantity@[g] == qc@[j as int]);
                assert(lineitem.l_extendedprice@[g] as int >= -999999999999999 && lineitem.l_extendedprice@[g] as int <= 999999999999999);
                reveal_with_fuel(sum_s, 2);
                assert(row_hit(lineitem, g) <==> ((q as int) < 2400));
                assert(sum_s_val(lineitem, g) == p as int);
                let rem = lineitem.n as int - (g + 1);
                assert((rem + 1) * 999999999999999int == rem * 999999999999999int + 999999999999999int) by (nonlinear_arith);
                assert((rem + 1) * 999999999999999int <= 6001215int * 999999999999999int) by (nonlinear_arith)
                    requires rem + 1 <= 6001215int, rem + 1 >= 0;
            }
            if q < 2400 {
                acc = acc + (p as i128);
                any = true;
                proof {
                    assert(row_hit(lineitem, base as int + j as int));
                }
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { s: if any { Some(acc) } else { None } });
    proof {
        assert(lineitem.l_extendedprice.off(0) == 0);
        assert(res@[0].s is Some <==> any);
    }
    res
// AGENT_EDIT_END
