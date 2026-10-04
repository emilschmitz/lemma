// Worked example (plain strings): SELECT MIN(l_extendedprice) AS lo, COUNT(*) AS n FROM lineitem WHERE l_shipmode = 'AIR'
// Rows from last to first, so the invariants line up with the spec's suffix folds (`count_n(lineitem, i)`).
// The literal is built once as a `String` and compared with `String == String` (ensures `res == (a@ == b@)`).
// AGENT_EDIT_START
    let air: String = String::from_str("AIR");
    let mut cnt: u64 = 0;
    let mut lo: i64 = 0;
    let mut any: bool = false;
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            air@ == "AIR"@,
            valid_cols_lineitem(lineitem),
            cnt as int == count_n(lineitem, i as int),
            any <==> exists|j: int| #![trigger row_hit(lineitem, j)] i as int <= j < lineitem.n as int && row_hit(lineitem, j),
            any ==> exists|j: int| i as int <= j < lineitem.n as int && row_hit(lineitem, j) && (lineitem.l_extendedprice@[j] as int) == (lo as int),
            any ==> forall|j: int| #![trigger row_hit(lineitem, j)] i as int <= j < lineitem.n as int && row_hit(lineitem, j) ==> (lineitem.l_extendedprice@[j] as int) >= (lo as int),
        decreases i,
    {
        i -= 1;
        let p = lineitem.l_extendedprice[i];
        let hit = lineitem.l_shipmode[i] == air;
        proof {
            assert(row_hit(lineitem, i as int) <==> hit);
            lemma_count_n_bound(lineitem, (i + 1) as int);
            assert(lineitem.n as int <= ROW_CAP_lineitem as int);
        }
        if hit {
            cnt += 1;
            if !any {
                lo = p;
                any = true;
            } else if p < lo {
                lo = p;
            }
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    if any {
        res.push(OutRow { lo: Some(lo as i128), n: cnt });
    } else {
        res.push(OutRow { lo: None, n: cnt });
    }
    res
// AGENT_EDIT_END
