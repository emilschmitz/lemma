// Worked example (LEMMA_ZERO_COPY=1, LEMMA_NARROW_CELLS=1): COUNT(*) over an INTEGER column (i32 cells, DuckDB's stored width) read in place from pinned chunks.
//   SELECT COUNT(*) AS n FROM num WHERE qtrs = 3
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let m: usize = num.qtrs.chunks.len();
    let mut acc: u64 = 0;
    let mut k: usize = m;
    proof {
        assert(num.qtrs.off(m as int) == num.n as int);
        assert(count_n(num, num.n as int) == 0);
    }
    while k > 0
        invariant
            k <= m,
            m == num.qtrs.chunks@.len(),
            num.qtrs.wf(),
            valid_cols_num(num),
            acc as int == count_n(num, num.qtrs.off(k as int)),
            acc as int <= num.n as int - num.qtrs.off(k as int),
        decreases k,
    {
        k -= 1;
        let c: &[i32] = num.qtrs.chunks[k];
        let base: usize = num.qtrs.offs[k];
        let ghost len = c@.len() as int;
        proof {
            assert(num.qtrs.off(k as int + 1) == num.qtrs.off(k as int) + len);
        }
        let mut j: usize = c.len();
        while j > 0
            invariant
                j <= c.len(),
                k < m,
                m == num.qtrs.chunks@.len(),
                num.qtrs.wf(),
                valid_cols_num(num),
                c == num.qtrs.chunks@[k as int],
                base == num.qtrs.off(k as int),
                len == c@.len() as int,
                num.qtrs.off(k as int + 1) == base as int + len,
                acc as int == count_n(num, base as int + j as int),
                acc as int <= num.n as int - (base as int + j as int),
            decreases j,
        {
            j -= 1;
            let v: i32 = c[j];
            proof {
                lemma_cell(&num.qtrs, k as int, j as int);
                let g = base as int + j as int;
                assert(g == num.qtrs.off(k as int) + j as int);
                assert(num.qtrs@[g] == c@[j as int]);
                reveal_with_fuel(count_n, 2);
                assert(row_hit(num, g) <==> ((v as int) == 3));
            }
            if v == 3 {
                acc = acc + 1;
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { n: acc });
    res
// AGENT_EDIT_END
