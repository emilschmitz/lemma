// Worked example: ungrouped MIN over a two-table join with a string join key and a string-literal filter:
//   SELECT MIN(n.ddate) AS a FROM num n JOIN sub s ON n.adsh = s.adsh WHERE n.uom = 'USD'
// (held-out draw, manual prover, 2 checks: 11 verified, 0 errors; 8,633 us vs 15,024 us all-core = 1.74x, 3.78x vs one thread.)
// * Build the join's other side ONCE into a `StringHashMap<usize>` (key string -> row index); the stored index is the
//   witness for the join's `exists j1. row_hit(.., j1)`. Probe it while scanning the driving table once.
// * Speed: SKIP THE PROBE for rows that cannot improve the aggregate (`!(any && d >= lo)`), and test the cheap string
//   filter first (short-circuit). That skip took the run from 22.6 ms to 8.6 ms.
// * The literal `'USD'` is built once with `String::from_str` and `usd@ == "USD"@` kept in the loop invariant.
// * A helper spec fn `hit0(n, s, j0) = exists j1. row_hit(n, s, j0, j1)` keeps the MIN witness/bound invariants short.
// AGENT_HELPERS_START
spec fn hit0(n: &Cols_num, s: &Cols_sub, j0: int) -> bool {
    exists|j1: int| #![trigger row_hit(n, s, j0, j1)] row_hit(n, s, j0, j1)
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let usd: String = String::from_str("USD");
    let mut map: StringHashMap<usize> = StringHashMap::new();
    let mut j: usize = 0;
    while j < s.n
        invariant
            j <= s.n,
            valid_cols_sub(s),
            forall|k: Seq<char>| #[trigger] map@.contains_key(k) ==> (map@[k] as int) < j as int && s.adsh@[map@[k] as int]@ == k,
            forall|t: int| 0 <= t < j as int ==> #[trigger] map@.contains_key(s.adsh@[t]@),
        decreases s.n - j,
    {
        let key = s.adsh[j].clone();
        let ghost old = map@;
        proof {
            assert(key@ == s.adsh@[j as int]@);
        }
        map.insert(key, j);
        proof {
            assert forall|k: Seq<char>| #[trigger] map@.contains_key(k) implies (map@[k] as int) < (j + 1) as int && s.adsh@[map@[k] as int]@ == k by {
                if k == key@ {
                    assert(map@[k] == j);
                } else {
                    assert(old.contains_key(k));
                }
            };
            assert forall|t: int| 0 <= t < (j + 1) as int implies #[trigger] map@.contains_key(s.adsh@[t]@) by {
                if t == j as int {
                } else {
                    assert(old.contains_key(s.adsh@[t]@));
                }
            };
        }
        j += 1;
    }
    let mut lo: i64 = 0;
    let mut any: bool = false;
    let mut i: usize = 0;
    while i < n.n
        invariant
            i <= n.n,
            usd@ == "USD"@,
            valid_cols_num(n),
            valid_cols_sub(s),
            forall|k: Seq<char>| #[trigger] map@.contains_key(k) ==> (map@[k] as int) < s.n as int && s.adsh@[map@[k] as int]@ == k,
            forall|t: int| 0 <= t < s.n as int ==> #[trigger] map@.contains_key(s.adsh@[t]@),
            any <==> exists|j: int| #![trigger hit0(n, s, j)] 0 <= j < i as int && hit0(n, s, j),
            any ==> exists|j: int| 0 <= j < i as int && hit0(n, s, j) && (n.ddate@[j] as int) == (lo as int),
            any ==> forall|j: int| #![trigger hit0(n, s, j)] 0 <= j < i as int && hit0(n, s, j) ==> (n.ddate@[j] as int) >= (lo as int),
        decreases n.n - i,
    {
        let d = n.ddate[i];
        if !(any && d >= lo) {
            let is_usd = n.uom[i] == usd;
            let found = is_usd && map.contains_key(n.adsh[i].as_str());
            proof {
                assert(hit0(n, s, i as int) <==> found) by {
                    if found {
                        let k = n.adsh@[i as int]@;
                        let w = map@[k] as int;
                        assert(map@.contains_key(k));
                        assert(row_hit(n, s, i as int, w));
                    }
                    if hit0(n, s, i as int) {
                        let j1 = choose|j1: int| row_hit(n, s, i as int, j1);
                        assert(map@.contains_key(s.adsh@[j1]@));
                    }
                };
            }
            if found {
                if !any {
                    lo = d;
                    any = true;
                } else if d < lo {
                    lo = d;
                }
            }
        } else {
            proof {
                assert(n.ddate@[i as int] == d);
            }
        }
        i += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    proof {
        if any {
            let j0 = choose|j: int| 0 <= j < n.n as int && hit0(n, s, j) && (n.ddate@[j] as int) == (lo as int);
            let j1 = choose|j1: int| row_hit(n, s, j0, j1);
            assert(row_hit(n, s, j0, j1));
            assert(min_a_val(n, s, j0, j1) == lo as int);
            assert forall|a: int, b: int| 0 <= a < n.n as int && 0 <= b < s.n as int && row_hit(n, s, a, b) implies min_a_val(n, s, a, b) >= lo as int by {
                assert(hit0(n, s, a));
            };
        } else {
            assert forall|a: int, b: int| #![trigger row_hit(n, s, a, b)] !row_hit(n, s, a, b) by {
                if row_hit(n, s, a, b) {
                    assert(hit0(n, s, a));
                }
            };
        }
    }
    if any {
        res.push(OutRow { a: Some(lo as i128) });
    } else {
        res.push(OutRow { a: None });
    }
    res
// AGENT_EDIT_END
