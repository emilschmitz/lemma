// Worked example for LEMMA_STRING_ENCODING=dict: the same query as ungrouped_minmax_string_filter.rs,
//   SELECT MIN(ddate) AS lo, MAX(ddate) AS hi FROM num WHERE uom = 'pure' AND qtrs = 3
// A string column `uom` is two vectors: `num.uom` (one code per row) and `num.uom__dict` (the distinct strings),
// and the spec reads a cell as `num.uom__dict@[num.uom@[i] as int]@`. `valid_cols` gives you: every code is below
// `num.uom__dict@.len()`, and the dictionary entries are pairwise distinct.
// * Equality with a literal becomes a CODE comparison, with the literal's code looked up ONCE before the loop:
//   scan the dictionary for the entry equal to the literal (`String == String` ensures `res == (a@ == b@)`).
//   `found` says an entry equals it and `code` is its index. Distinctness makes that entry the only one, so
//   `num.uom[i] as usize == code` is the SQL equality, and with no such entry no row passes.
// * The row loop then compares one integer per row instead of a heap string.
// AGENT_EDIT_START
    let pure: String = String::from_str("pure");
    let mut code: usize = 0;
    let mut found: bool = false;
    let mut k: usize = 0;
    while k < num.uom__dict.len()
        invariant
            k <= num.uom__dict@.len(),
            pure@ == "pure"@,
            valid_cols_num(num),
            found ==> code < k && num.uom__dict@[code as int]@ == "pure"@,
            !found ==> forall|m: int| 0 <= m < k as int ==> num.uom__dict@[m]@ != "pure"@,
        decreases num.uom__dict@.len() - k,
    {
        if !found && num.uom__dict[k] == pure {
            found = true;
            code = k;
        }
        k += 1;
    }
    proof {
        // the code of the literal is unique, so a cell equals the literal exactly when its code is `code`
        assert forall|j: int| 0 <= j < num.n as int implies
            ((num.uom__dict@[num.uom@[j] as int]@ == "pure"@) <==> (found && num.uom@[j] as int == code as int)) by {
            if found {
                if num.uom@[j] as int != code as int {
                    // two different dictionary entries are different strings
                    let a = if (num.uom@[j] as int) < (code as int) { num.uom@[j] as int } else { code as int };
                    let b = if (num.uom@[j] as int) < (code as int) { code as int } else { num.uom@[j] as int };
                    assert(num.uom__dict@[a]@ != num.uom__dict@[b]@);
                }
            }
        };
    }
    let mut lo: i64 = 0;
    let mut hi: i64 = 0;
    let mut any: bool = false;
    let mut i: usize = 0;
    while i < num.n
        invariant
            i <= num.n,
            valid_cols_num(num),
            found ==> code < num.uom__dict@.len() && num.uom__dict@[code as int]@ == "pure"@,
            forall|j: int| 0 <= j < num.n as int ==>
                ((num.uom__dict@[num.uom@[j] as int]@ == "pure"@) <==> (found && num.uom@[j] as int == code as int)),
            any <==> exists|j: int| #![trigger row_hit(num, j)] 0 <= j < i as int && row_hit(num, j),
            any ==> exists|j: int| 0 <= j < i as int && row_hit(num, j) && (num.ddate@[j] as int) == (lo as int),
            any ==> forall|j: int| #![trigger row_hit(num, j)] 0 <= j < i as int && row_hit(num, j) ==> (num.ddate@[j] as int) >= (lo as int),
            any ==> exists|j: int| 0 <= j < i as int && row_hit(num, j) && (num.ddate@[j] as int) == (hi as int),
            any ==> forall|j: int| #![trigger row_hit(num, j)] 0 <= j < i as int && row_hit(num, j) ==> (num.ddate@[j] as int) <= (hi as int),
        decreases num.n - i,
    {
        let q = num.qtrs[i];
        let d = num.ddate[i];
        let hit = q == 3 && found && (num.uom[i] as usize) == code;
        proof {
            assert(row_hit(num, i as int) <==> hit);
        }
        if hit {
            if !any {
                lo = d;
                hi = d;
                any = true;
            } else {
                if d < lo { lo = d; }
                if d > hi { hi = d; }
            }
        }
        i += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    if any {
        res.push(OutRow { lo: Some(lo as i128), hi: Some(hi as i128) });
    } else {
        res.push(OutRow { lo: None, hi: None });
    }
    res
// AGENT_EDIT_END
