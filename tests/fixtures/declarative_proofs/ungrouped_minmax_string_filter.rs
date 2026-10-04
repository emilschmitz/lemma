// Worked example: ungrouped MIN and MAX of an integer column under a filter that includes a string-literal
// comparison. The shape of
//   SELECT MIN(ddate) AS lo, MAX(ddate) AS hi FROM num WHERE uom = 'pure' AND qtrs = 3
// (verified by a manual prover on the first full try; 3.8x faster than the all-core reference engine on 1M rows).
// * `uom = 'pure'`: `&str ==` has NO spec tying it to `@`, and `reveal_strlit` does not help. Build the literal once
//   as a `String` (`String::from_str("pure")` ensures `ret@ == "pure"@`), keep `pure@ == "pure"@` in the loop
//   invariant, and compare `num.uom[i] == pure` (`String == String` ensures `res == (a@ == b@)`; vstd `string.rs`).
// * MIN and MAX as an existential witness plus a universal bound over the rows seen so far (`any ==> exists ...`,
//   `any ==> forall ... >= lo`), with `any` tracking whether some row hit.
// * No arithmetic, so no fit lemma is needed. The row predicate is proved equal to the exec `hit` in one assert.
// AGENT_EDIT_START
    let pure: String = String::from_str("pure");
    let mut lo: i64 = 0;
    let mut hi: i64 = 0;
    let mut any: bool = false;
    let mut i: usize = 0;
    while i < num.n
        invariant
            i <= num.n,
            pure@ == "pure"@,
            valid_cols_num(num),
            any <==> exists|j: int| #![trigger row_hit(num, j)] 0 <= j < i as int && row_hit(num, j),
            any ==> exists|j: int| 0 <= j < i as int && row_hit(num, j) && (num.ddate@[j] as int) == (lo as int),
            any ==> forall|j: int| #![trigger row_hit(num, j)] 0 <= j < i as int && row_hit(num, j) ==> (num.ddate@[j] as int) >= (lo as int),
            any ==> exists|j: int| 0 <= j < i as int && row_hit(num, j) && (num.ddate@[j] as int) == (hi as int),
            any ==> forall|j: int| #![trigger row_hit(num, j)] 0 <= j < i as int && row_hit(num, j) ==> (num.ddate@[j] as int) <= (hi as int),
        decreases num.n - i,
    {
        let q = num.qtrs[i];
        let d = num.ddate[i];
        let hit = q == 3 && num.uom[i] == pure;
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
