// Worked example (LEMMA_STRING_ENCODING=dict): SELECT MIN(l_extendedprice) AS lo, COUNT(*) AS n FROM lineitem WHERE l_shipmode = 'AIR'
// `l_shipmode` is `lineitem.l_shipmode` (codes) and `lineitem.l_shipmode__dict` (the distinct strings).
// The literal's code is looked up once; the row loop compares one small integer per row (see dict_string_filter_minmax.rs).
// AGENT_EDIT_START
    let air: String = String::from_str("AIR");
    let mut code: usize = 0;
    let mut found: bool = false;
    let mut k: usize = 0;
    while k < lineitem.l_shipmode__dict.len()
        invariant
            k <= lineitem.l_shipmode__dict@.len(),
            air@ == "AIR"@,
            valid_cols_lineitem(lineitem),
            found ==> code < k && lineitem.l_shipmode__dict@[code as int]@ == "AIR"@,
            !found ==> forall|m: int| 0 <= m < k as int ==> lineitem.l_shipmode__dict@[m]@ != "AIR"@,
        decreases lineitem.l_shipmode__dict@.len() - k,
    {
        if !found && lineitem.l_shipmode__dict[k] == air {
            found = true;
            code = k;
        }
        k += 1;
    }
    proof {
        assert forall|j: int| 0 <= j < lineitem.n as int implies
            ((lineitem.l_shipmode__dict@[lineitem.l_shipmode@[j] as int]@ == "AIR"@) <==> (found && lineitem.l_shipmode@[j] as int == code as int)) by {
            if found {
                if lineitem.l_shipmode@[j] as int != code as int {
                    let a = if (lineitem.l_shipmode@[j] as int) < (code as int) { lineitem.l_shipmode@[j] as int } else { code as int };
                    let b = if (lineitem.l_shipmode@[j] as int) < (code as int) { code as int } else { lineitem.l_shipmode@[j] as int };
                    assert(lineitem.l_shipmode__dict@[a]@ != lineitem.l_shipmode__dict@[b]@);
                }
            }
        };
    }
    let mut cnt: u64 = 0;
    let mut lo: i64 = 0;
    let mut any: bool = false;
    let mut i: usize = lineitem.n;
    while i > 0
        invariant
            i <= lineitem.n,
            valid_cols_lineitem(lineitem),
            found ==> code < lineitem.l_shipmode__dict@.len() && lineitem.l_shipmode__dict@[code as int]@ == "AIR"@,
            forall|j: int| 0 <= j < lineitem.n as int ==>
                ((lineitem.l_shipmode__dict@[lineitem.l_shipmode@[j] as int]@ == "AIR"@) <==> (found && lineitem.l_shipmode@[j] as int == code as int)),
            cnt as int == count_n(lineitem, i as int),
            any <==> exists|j: int| #![trigger row_hit(lineitem, j)] i as int <= j < lineitem.n as int && row_hit(lineitem, j),
            any ==> exists|j: int| i as int <= j < lineitem.n as int && row_hit(lineitem, j) && (lineitem.l_extendedprice@[j] as int) == (lo as int),
            any ==> forall|j: int| #![trigger row_hit(lineitem, j)] i as int <= j < lineitem.n as int && row_hit(lineitem, j) ==> (lineitem.l_extendedprice@[j] as int) >= (lo as int),
        decreases i,
    {
        i -= 1;
        let p = lineitem.l_extendedprice[i];
        let c = lineitem.l_shipmode[i];
        let hit = found && (c as usize) == code;
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
