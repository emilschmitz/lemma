// Worked example (LEMMA_STRING_ENCODING=dict): ungrouped COUNT and SUM under a string-literal filter, on a dictionary-coded column:
//   SELECT COUNT(*) AS c, SUM(value) AS s FROM num WHERE uom = 'USD'
// Found by a manual prover on the first check; on REAL EDGAR (num 39,401,761 rows, DECIMAL(38,4) value): 65.1 ms vs 278.8 ms for the
// all-core reference engine (4.28x), 1,015 ms for one thread (15.6x); 8 verified, 0 errors. One backward pass over the code and value columns,
// branch-free accumulate (`t = if hit {v} else {0}`, `u = if hit {1} else {0}`), the literal's code looked up ONCE (see dict_string_filter_minmax.rs).
// The i128 sum needs no helper: cell cap ~4.6e22 times n <= 2^31 is linear in `n - i` and far below i128.
// AGENT_HELPERS_START
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let usd: String = String::from_str("USD");
    let mut code: usize = 0;
    let mut found: bool = false;
    let mut k: usize = 0;
    while k < num.uom__dict.len()
        invariant
            k <= num.uom__dict@.len(),
            usd@ == "USD"@,
            valid_cols_num(num),
            found ==> code < k && num.uom__dict@[code as int]@ == "USD"@,
            !found ==> forall|m: int| 0 <= m < k as int ==> num.uom__dict@[m]@ != "USD"@,
        decreases num.uom__dict@.len() - k,
    {
        if !found && num.uom__dict[k] == usd {
            found = true;
            code = k;
        }
        k += 1;
    }
    proof {
        assert forall|j: int| 0 <= j < num.n as int implies
            ((num.uom__dict@[num.uom@[j] as int]@ == "USD"@) <==> (found && num.uom@[j] as int == code as int)) by {
            if found {
                if num.uom@[j] as int != code as int {
                    let a = if (num.uom@[j] as int) < (code as int) { num.uom@[j] as int } else { code as int };
                    let b = if (num.uom@[j] as int) < (code as int) { code as int } else { num.uom@[j] as int };
                    assert(num.uom__dict@[a]@ != num.uom__dict@[b]@);
                }
            }
        };
        assert(count_c(num, num.n as int) == 0);
        assert(sum_s(num, num.n as int) == 0);
    }
    let mut cnt: u64 = 0;
    let mut s: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = num.n;
    while i > 0
        invariant
            i <= num.n,
            valid_cols_num(num),
            forall|j: int| 0 <= j < num.n as int ==>
                ((num.uom__dict@[num.uom@[j] as int]@ == "USD"@) <==> (found && num.uom@[j] as int == code as int)),
            cnt as int == count_c(num, i as int),
            s as int == sum_s(num, i as int),
            -46116860184273879039999 * ((num.n - i) as int) <= s as int <= 46116860184273879039999 * ((num.n - i) as int),
            cnt as int <= (num.n - i) as int,
            any <==> exists|j: int| #![trigger row_hit(num, j)] i as int <= j < num.n as int && row_hit(num, j),
        decreases i,
    {
        i -= 1;
        let c = num.uom[i];
        let v = num.value[i];
        let hit = found && (c as usize) == code;
        proof {
            assert(row_hit(num, i as int) <==> hit);
            assert(count_c(num, i as int) == (if row_hit(num, i as int) { 1int } else { 0int }) + count_c(num, i as int + 1));
            assert(sum_s(num, i as int) == (if row_hit(num, i as int) { sum_s_val(num, i as int) } else { 0int }) + sum_s(num, i as int + 1));
        }
        let t: i128 = if hit { v } else { 0 };
        let u: u64 = if hit { 1 } else { 0 };
        cnt = cnt + u;
        s = s + t;
        any = any || hit;
    }
    let mut res: Vec<OutRow> = Vec::new();
    if any {
        res.push(OutRow { c: cnt, s: Some(s) });
    } else {
        res.push(OutRow { c: cnt, s: None });
    }
    res
// AGENT_EDIT_END
