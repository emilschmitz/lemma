// Worked example for LEMMA_STRING_ENCODING=dict: a JOIN ON a dictionary-encoded string key, probed through ARRAYS OVER CODES.
//   SELECT SUM(n.value) AS v FROM num n JOIN sub s ON n.adsh = s.adsh WHERE s.form = '10-K'
// Each table has its OWN dictionary (`n.adsh__dict`, `s.adsh__dict`), so `row_hit` compares the two strings through them.
// The build side is the small table `sub`; `sub` is NOT declared unique here, so the recipe counts instead of storing an index:
//   1. the code of the literal '10-K' in `s.form__dict` is looked up ONCE (see dict_string_filter_minmax.rs);
//   2. `cnt[c]` = number of filtered `sub` rows whose `adsh` code is c (backward pass, like the spec's suffix fold `fcs`);
//      equal strings have equal codes (the dictionary is pairwise distinct), so a duplicate adsh is counted exactly;
//   3. `tr[d]` = the `sub` code whose string equals entry d of NUM's dictionary (`scodes` if none): ONE `StringHashMap`
//      over the small `sub` dictionary, probed once per NUM dictionary entry (86k strings), never once per NUM row;
//   4. one backward pass over `num`: `acc += value * cnt[tr[code]]`, two array reads per row and no string work. Each NUM row
//      contributes `value * hc(i0, 0)` (`lemma_d1_hc`), hc is the number of matching sub rows, which is `cnt[tr[code]]`
//      (`lemma_hc_fcs`) or 0 (`lemma_hc_none`).
// The i128 accumulator is bounded by (n.n - i) * VMAX * ROW_CAP_sub = at most 2^31 * 4.6e22 * 2^20, below i128::MAX.
// AGENT_HELPERS_START
spec fn form_ok(s: &Cols_sub, t: int) -> bool {
    s.form__dict@[s.form@[t] as int]@ == "10-K"@
}

spec fn fcs(s: &Cols_sub, c: int, k: int) -> int
    decreases s.n as int - k
{
    if k < 0 || k >= s.n as int {
        0int
    } else {
        (if (s.adsh@[k] as int) == c && form_ok(s, k) { 1int } else { 0int }) + fcs(s, c, k + 1)
    }
}

spec fn hc(n: &Cols_num, s: &Cols_sub, i0: int, k: int) -> int
    decreases s.n as int - k
{
    if k < 0 || k >= s.n as int {
        0int
    } else {
        (if row_hit(n, s, i0, k) { 1int } else { 0int }) + hc(n, s, i0, k + 1)
    }
}

proof fn lemma_fcs_bound(s: &Cols_sub, c: int, k: int)
    requires
        0 <= k,
    ensures
        0 <= fcs(s, c, k) <= (if k < s.n as int { s.n as int - k } else { 0int }),
    decreases s.n as int - k,
{
    if k < s.n as int {
        lemma_fcs_bound(s, c, k + 1);
    }
}

proof fn lemma_hc_bound(n: &Cols_num, s: &Cols_sub, i0: int, k: int)
    requires
        0 <= k,
    ensures
        0 <= hc(n, s, i0, k) <= (if k < s.n as int { s.n as int - k } else { 0int }),
    decreases s.n as int - k,
{
    if k < s.n as int {
        lemma_hc_bound(n, s, i0, k + 1);
    }
}

proof fn lemma_dict_eq(s: &Cols_sub, a: int, b: int)
    requires
        valid_cols_sub(s),
        0 <= a < s.adsh__dict@.len(),
        0 <= b < s.adsh__dict@.len(),
        s.adsh__dict@[a]@ == s.adsh__dict@[b]@,
    ensures
        a == b,
{
    if a < b {
        assert(s.adsh__dict@[a]@ != s.adsh__dict@[b]@);
    } else if b < a {
        assert(s.adsh__dict@[b]@ != s.adsh__dict@[a]@);
    }
}

// the sum over the sub rows from k on of one num row's contribution is value * (number of hits)
proof fn lemma_d1_hc(n: &Cols_num, s: &Cols_sub, i0: int, k: int)
    requires
        0 <= i0 < n.n as int,
        0 <= k,
    ensures
        sum_v_d1(n, s, i0, k) == (n.value@[i0] as int) * hc(n, s, i0, k),
    decreases s.n as int - k,
{
    if k < s.n as int {
        lemma_d1_hc(n, s, i0, k + 1);
        let v = n.value@[i0] as int;
        let r = hc(n, s, i0, k + 1);
        assert(v * (1 + r) == v + v * r) by (nonlinear_arith);
    }
}

// a num row whose string is entry `c` of sub's dictionary hits exactly the filtered sub rows with code c
proof fn lemma_hc_fcs(n: &Cols_num, s: &Cols_sub, i0: int, c: int, k: int)
    requires
        valid_cols_sub(s),
        0 <= i0 < n.n as int,
        0 <= c < s.adsh__dict@.len(),
        0 <= k,
        s.adsh__dict@[c]@ == n.adsh__dict@[n.adsh@[i0] as int]@,
    ensures
        hc(n, s, i0, k) == fcs(s, c, k),
    decreases s.n as int - k,
{
    if k < s.n as int {
        lemma_hc_fcs(n, s, i0, c, k + 1);
        assert(s.adsh@[k] as int >= 0 && (s.adsh@[k] as int) < s.adsh__dict@.len());
        if row_hit(n, s, i0, k) {
            lemma_dict_eq(s, s.adsh@[k] as int, c);
        }
        if (s.adsh@[k] as int) == c {
            assert(s.adsh__dict@[s.adsh@[k] as int]@ == s.adsh__dict@[c]@);
        }
    }
}

// a num row whose string is in no entry of sub's dictionary hits no sub row
proof fn lemma_hc_none(n: &Cols_num, s: &Cols_sub, i0: int, k: int)
    requires
        valid_cols_sub(s),
        0 <= i0 < n.n as int,
        0 <= k,
        forall|c: int| 0 <= c < s.adsh__dict@.len() ==> s.adsh__dict@[c]@ != n.adsh__dict@[n.adsh@[i0] as int]@,
    ensures
        hc(n, s, i0, k) == 0,
    decreases s.n as int - k,
{
    if k < s.n as int {
        lemma_hc_none(n, s, i0, k + 1);
        assert(s.adsh@[k] as int >= 0 && (s.adsh@[k] as int) < s.adsh__dict@.len());
        assert(!row_hit(n, s, i0, k));
    }
}

proof fn lemma_hc_exists(n: &Cols_num, s: &Cols_sub, i0: int, k: int)
    requires
        0 <= k,
    ensures
        hc(n, s, i0, k) > 0 <==> exists|t: int| #![trigger row_hit(n, s, i0, t)] k <= t < s.n as int && row_hit(n, s, i0, t),
    decreases s.n as int - k,
{
    if k < s.n as int {
        lemma_hc_exists(n, s, i0, k + 1);
        lemma_hc_bound(n, s, i0, k + 1);
        if row_hit(n, s, i0, k) {
            assert(k <= k && k < s.n as int && row_hit(n, s, i0, k));
        } else if exists|t: int| #![trigger row_hit(n, s, i0, t)] k <= t < s.n as int && row_hit(n, s, i0, t) {
            let t = choose|t: int| #![trigger row_hit(n, s, i0, t)] k <= t < s.n as int && row_hit(n, s, i0, t);
            assert(t != k);
            assert(k + 1 <= t < s.n as int && row_hit(n, s, i0, t));
        }
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let ten: String = String::from_str("10-K");
    let mut code: usize = 0;
    let mut found: bool = false;
    let mut kk: usize = 0;
    while kk < s.form__dict.len()
        invariant
            kk <= s.form__dict@.len(),
            ten@ == "10-K"@,
            valid_cols_sub(s),
            found ==> code < kk && s.form__dict@[code as int]@ == "10-K"@,
            !found ==> forall|m: int| 0 <= m < kk as int ==> s.form__dict@[m]@ != "10-K"@,
        decreases s.form__dict@.len() - kk,
    {
        if !found && s.form__dict[kk] == ten {
            found = true;
            code = kk;
        }
        kk += 1;
    }
    proof {
        assert forall|j: int| 0 <= j < s.n as int implies (form_ok(s, j) <==> (found && s.form@[j] as int == code as int)) by {
            if found {
                if s.form@[j] as int != code as int {
                    let a = if (s.form@[j] as int) < (code as int) { s.form@[j] as int } else { code as int };
                    let b = if (s.form@[j] as int) < (code as int) { code as int } else { s.form@[j] as int };
                    assert(s.form__dict@[a]@ != s.form__dict@[b]@);
                }
            }
        };
    }
    let scodes: usize = s.adsh__dict.len();
    let ncodes: usize = n.adsh__dict.len();
    // 2. cnt[c]: filtered sub rows per sub code
    let mut cnt: Vec<u64> = Vec::new();
    let mut z: usize = 0;
    while z < scodes
        invariant
            z <= scodes,
            scodes == s.adsh__dict@.len(),
            cnt@.len() == z as int,
            forall|c: int| 0 <= c < z as int ==> cnt@[c] == 0,
        decreases scodes - z,
    {
        cnt.push(0);
        z += 1;
    }
    proof {
        assert forall|c: int| #![trigger cnt@[c]] 0 <= c < scodes as int implies cnt@[c] as int == fcs(s, c, s.n as int) by {};
    }
    let mut j: usize = s.n;
    while j > 0
        invariant
            j <= s.n,
            valid_cols_sub(s),
            scodes == s.adsh__dict@.len(),
            cnt@.len() == scodes as int,
            forall|jj: int| 0 <= jj < s.n as int ==> (form_ok(s, jj) <==> (found && s.form@[jj] as int == code as int)),
            forall|c: int| #![trigger cnt@[c]] 0 <= c < scodes as int ==> cnt@[c] as int == fcs(s, c, j as int),
        decreases j,
    {
        j -= 1;
        let c = s.adsh[j] as usize;
        proof {
            assert(s.adsh@.len() == s.n as int);
            assert(s.form@.len() == s.n as int);
            assert(c < scodes);
            lemma_fcs_bound(s, c as int, (j + 1) as int);
        }
        if found && (s.form[j] as usize) == code {
            let ghost old = cnt@;
            let before = cnt[c];
            cnt.set(c, before + 1);
            proof {
                assert(form_ok(s, j as int));
                assert forall|c2: int| #![trigger cnt@[c2]] 0 <= c2 < scodes as int implies cnt@[c2] as int == fcs(s, c2, j as int) by {
                    if c2 == c as int {
                        assert(fcs(s, c2, j as int) == 1 + fcs(s, c2, j as int + 1));
                    } else {
                        assert(fcs(s, c2, j as int) == fcs(s, c2, j as int + 1));
                    }
                };
            }
        } else {
            proof {
                assert(!form_ok(s, j as int));
                assert forall|c2: int| #![trigger cnt@[c2]] 0 <= c2 < scodes as int implies cnt@[c2] as int == fcs(s, c2, j as int) by {
                    assert(fcs(s, c2, j as int) == fcs(s, c2, j as int + 1));
                };
            }
        }
    }
    // 3. smap: sub dictionary string -> sub code
    let mut smap: StringHashMap<usize> = StringHashMap::new();
    let mut c: usize = 0;
    while c < scodes
        invariant
            c <= scodes,
            scodes == s.adsh__dict@.len(),
            valid_cols_sub(s),
            forall|k: Seq<char>| #[trigger] smap@.contains_key(k) ==> (smap@[k] as int) < c as int && s.adsh__dict@[smap@[k] as int]@ == k,
            forall|t: int| 0 <= t < c as int ==> #[trigger] smap@.contains_key(s.adsh__dict@[t]@),
        decreases scodes - c,
    {
        let key = s.adsh__dict[c].clone();
        let ghost old = smap@;
        proof {
            assert(key@ == s.adsh__dict@[c as int]@);
        }
        smap.insert(key, c);
        proof {
            assert forall|k: Seq<char>| #[trigger] smap@.contains_key(k) implies (smap@[k] as int) < (c + 1) as int && s.adsh__dict@[smap@[k] as int]@ == k by {
                if k == key@ {
                    assert(smap@[k] == c);
                } else {
                    assert(old.contains_key(k));
                }
            };
            assert forall|t: int| 0 <= t < (c + 1) as int implies #[trigger] smap@.contains_key(s.adsh__dict@[t]@) by {
                if t == c as int {
                } else {
                    assert(old.contains_key(s.adsh__dict@[t]@));
                }
            };
        }
        c += 1;
    }
    // 3b. tr[d]: the sub code of NUM dictionary entry d (scodes: none)
    let mut tr: Vec<usize> = Vec::new();
    let mut d: usize = 0;
    while d < ncodes
        invariant
            d <= ncodes,
            ncodes == n.adsh__dict@.len(),
            scodes == s.adsh__dict@.len(),
            valid_cols_sub(s),
            tr@.len() == d as int,
            forall|k: Seq<char>| #[trigger] smap@.contains_key(k) ==> (smap@[k] as int) < scodes as int && s.adsh__dict@[smap@[k] as int]@ == k,
            forall|t: int| 0 <= t < scodes as int ==> #[trigger] smap@.contains_key(s.adsh__dict@[t]@),
            forall|q: int| #![trigger tr@[q]] 0 <= q < d as int ==> (
                ((tr@[q] as int) < scodes as int && s.adsh__dict@[tr@[q] as int]@ == n.adsh__dict@[q]@)
                || (tr@[q] == scodes && forall|c2: int| 0 <= c2 < scodes as int ==> s.adsh__dict@[c2]@ != n.adsh__dict@[q]@)),
        decreases ncodes - d,
    {
        let found_code = smap.get(n.adsh__dict[d].as_str());
        match found_code {
            Some(v) => {
                tr.push(*v);
            }
            None => {
                proof {
                    assert(!smap@.contains_key(n.adsh__dict@[d as int]@));
                    assert forall|c2: int| 0 <= c2 < scodes as int implies s.adsh__dict@[c2]@ != n.adsh__dict@[d as int]@ by {
                        if s.adsh__dict@[c2]@ == n.adsh__dict@[d as int]@ {
                            assert(smap@.contains_key(s.adsh__dict@[c2]@));
                        }
                    };
                }
                tr.push(scodes);
            }
        }
        d += 1;
    }
    // 4. one backward pass over num
    let mut acc: i128 = 0;
    let mut any: bool = false;
    let mut i: usize = n.n;
    proof {
        assert(sum_v(n, s, n.n as int) == 0);
    }
    while i > 0
        invariant
            i <= n.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            ncodes == n.adsh__dict@.len(),
            scodes == s.adsh__dict@.len(),
            tr@.len() == ncodes as int,
            cnt@.len() == scodes as int,
            forall|q: int| #![trigger tr@[q]] 0 <= q < ncodes as int ==> (
                ((tr@[q] as int) < scodes as int && s.adsh__dict@[tr@[q] as int]@ == n.adsh__dict@[q]@)
                || (tr@[q] == scodes && forall|c2: int| 0 <= c2 < scodes as int ==> s.adsh__dict@[c2]@ != n.adsh__dict@[q]@)),
            forall|c2: int| #![trigger cnt@[c2]] 0 <= c2 < scodes as int ==> cnt@[c2] as int == fcs(s, c2, 0),
            acc as int == sum_v(n, s, i as int),
            -(48357032784585166988245991424int) * ((n.n - i) as int) <= acc as int <= 48357032784585166988245991424int * ((n.n - i) as int),
            any <==> exists|j0: int| #![trigger hc(n, s, j0, 0)] i as int <= j0 < n.n as int && hc(n, s, j0, 0) > 0,
        decreases i,
    {
        i -= 1;
        let dcode = n.adsh[i] as usize;
        let v = n.value[i];
        proof {
            assert(n.adsh@.len() == n.n as int);
            assert(n.value@.len() == n.n as int);
            assert(dcode < ncodes);
            lemma_d1_hc(n, s, i as int, 0);
            lemma_hc_bound(n, s, i as int, 0);
        }
        let t = tr[dcode];
        let mut k: u64 = 0;
        if t < scodes {
            k = cnt[t];
            proof {
                lemma_hc_fcs(n, s, i as int, t as int, 0);
                lemma_fcs_bound(s, t as int, 0);
            }
        } else {
            proof {
                lemma_hc_none(n, s, i as int, 0);
            }
        }
        proof {
            assert(hc(n, s, i as int, 0) == k as int);
            assert(k as int <= s.n as int);
            assert(s.n as int <= 1048576);
            assert(sum_v(n, s, i as int) == sum_v_d1(n, s, i as int, 0) + sum_v(n, s, i as int + 1));
            let vi = n.value@[i as int] as int;
            assert(-46116860184273879039999int * 1048576 <= vi * (k as int) <= 46116860184273879039999int * 1048576) by (nonlinear_arith)
                requires
                    -46116860184273879039999int <= vi <= 46116860184273879039999int,
                    0 <= k as int <= 1048576,
            ;
        }
        let term: i128 = v * (k as i128);
        acc = acc + term;
        any = any || k > 0;
        proof {
            assert(hc(n, s, i as int, 0) > 0 <==> k > 0);
        }
    }
    let mut res: Vec<OutRow> = Vec::new();
    proof {
        assert forall|j0: int| 0 <= j0 < n.n as int implies (hc(n, s, j0, 0) > 0 <==> exists|t: int| #![trigger row_hit(n, s, j0, t)] 0 <= t < s.n as int && row_hit(n, s, j0, t)) by {
            lemma_hc_exists(n, s, j0, 0);
        };
        if any {
            let j0 = choose|j0: int| 0 <= j0 < n.n as int && hc(n, s, j0, 0) > 0;
            let t = choose|t: int| 0 <= t < s.n as int && row_hit(n, s, j0, t);
            assert(row_hit(n, s, j0, t));
        } else {
            assert forall|a: int, b: int| #![trigger row_hit(n, s, a, b)] !row_hit(n, s, a, b) by {
                if row_hit(n, s, a, b) {
                    assert(hc(n, s, a, 0) > 0);
                }
            };
        }
    }
    if any {
        res.push(OutRow { v: Some(acc) });
    } else {
        res.push(OutRow { v: None });
    }
    res
// AGENT_EDIT_END
