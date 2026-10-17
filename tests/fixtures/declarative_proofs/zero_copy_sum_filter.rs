// Worked example (LEMMA_ZERO_COPY=1, prototype): ungrouped SUM over a DECIMAL(38,4) column (i128 cells) read in place from pinned DuckDB chunks.
//   SELECT SUM(value) AS total FROM num WHERE value > 5000
// `num.value` is a `PinnedCol` (research_loop/zero_copy_lib.rs): `chunks[k]` is a slice, `offs[k]` the row where it starts; its view is the
// concatenation, so the spec is unchanged. Hot loop = chunk by chunk, row by row, descending, exactly the sliced hot-loop recipe; the only
// new proof step is `lemma_cell(&num.value, k, j)`: global row `offs[k] + j` is cell `j` of chunk `k`.
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let m: usize = num.value.chunks.len();
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut k: usize = m;
    proof {
        assert(num.value.off(m as int) == num.n as int);
        assert(sum_total(num, num.n as int) == 0);
    }
    while k > 0
        invariant
            k <= m,
            m == num.value.chunks@.len(),
            num.value.wf(),
            valid_cols_num(num),
            acc as int == sum_total(num, num.value.off(k as int)),
            any <==> exists|i0: int| #![trigger row_hit(num, i0)] num.value.off(k as int) <= i0 < num.n as int && row_hit(num, i0),
            -((num.n as int - num.value.off(k as int))) * 46116860184273879039999int <= acc as int,
            acc as int <= (num.n as int - num.value.off(k as int)) * 46116860184273879039999int,
        decreases k,
    {
        k -= 1;
        let c: &[i128] = num.value.chunks[k];
        let base: usize = num.value.offs[k];
        let ghost len = c@.len() as int;
        proof {
            assert(num.value.off(k as int + 1) == num.value.off(k as int) + len);
        }
        let mut j: usize = c.len();
        while j > 0
            invariant
                j <= c.len(),
                k < m,
                m == num.value.chunks@.len(),
                num.value.wf(),
                valid_cols_num(num),
                c == num.value.chunks@[k as int],
                base == num.value.off(k as int),
                len == c@.len() as int,
                num.value.off(k as int + 1) == base as int + len,
                num.n <= 2147483648,
                acc as int == sum_total(num, base as int + j as int),
                any <==> exists|i0: int| #![trigger row_hit(num, i0)] base as int + j as int <= i0 < num.n as int && row_hit(num, i0),
                -((num.n as int - (base as int + j as int))) * 46116860184273879039999int <= acc as int,
                acc as int <= (num.n as int - (base as int + j as int)) * 46116860184273879039999int,
            decreases j,
        {
            j -= 1;
            let v: i128 = c[j];
            proof {
                assert(j as int + 1 <= c@.len());
                assert(num.value.chunks@[k as int]@.len() == c@.len());
                lemma_cell(&num.value, k as int, j as int);
                let g = base as int + j as int;
                assert(g == num.value.off(k as int) + j as int);
                assert(num.value@[g] == num.value.chunks@[k as int]@[j as int]);
                assert(num.value.chunks@[k as int]@[j as int] == c@[j as int]);
                assert(v == c@[j as int]);
                assert(num.value@[g] == c@[j as int]);
                assert(num.value@[g] as int >= -46116860184273879039999 && num.value@[g] as int <= 46116860184273879039999);
                reveal_with_fuel(sum_total, 2);
                assert(row_hit(num, g) <==> ((v as int) > 50000000));
                let rem = num.n as int - (g + 1);
                assert((rem + 1) * 46116860184273879039999int == rem * 46116860184273879039999int + 46116860184273879039999int) by (nonlinear_arith);
                assert((rem + 1) * 46116860184273879039999int <= 2147483648int * 46116860184273879039999int) by (nonlinear_arith)
                    requires rem + 1 <= 2147483648int, rem + 1 >= 0;
            }
            if v > 50000000 {
                acc = acc + v;
                any = true;
                proof {
                    assert(row_hit(num, base as int + j as int));
                }
            }
        }
        proof {
            assert(j == 0);
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if any { Some(acc) } else { None } });
    proof {
        assert(num.value.off(0) == 0);
        assert(res@[0].total is Some <==> any);
    }
    res
// AGENT_EDIT_END
