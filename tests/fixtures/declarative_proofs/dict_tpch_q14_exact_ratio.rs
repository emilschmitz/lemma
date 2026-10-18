// Worked example (lemma.toml [sql] exact_division, dictionary strings, join chain): TPC-H Q14,
//   SELECT 100.00 * SUM(CASE WHEN p_type LIKE 'PROMO%' THEN l_extendedprice * (1 - l_discount) ELSE 0 END)
//          / SUM(l_extendedprice * (1 - l_discount)) AS promo_revenue
//   FROM lineitem, part WHERE l_partkey = p_partkey AND l_shipdate >= DATE '1995-09-01' AND l_shipdate < DATE '1995-10-01'
// as an EXACT RATIONAL: the spec is `rat_is(r, 10000 * N * 10^4, D * 10^6)` for the two exact sums N and D. No float: the body
// returns `Rat { num: 100 * N, den: D }` (the same fraction; signs flipped when D < 0) and, for D == 0, `Rat { num: N, den: 0 }`
// (the host prints +inf, -inf or NaN, as DuckDB's division by zero). Written for the tpch_sf1 assumption package (p_partkey unique,
// |key| < 2^18, price < 2^24, |discount| < 16, row caps 2^25 / 2^20). Plan:
// * PROMO flags once per dictionary entry (`lemma_promo_like`: `LIKE 'lit%'` without `%`/`_` in lit is "starts with lit");
// * a dense position table over the part key (`pos[key + 262143] = part row + 1`, 0 = no part row with that key);
// * one backward pass over lineitem: a row in the date window whose key has a part row adds its term; the host's chain row lemma
//   (`lemma_sum_promo_revenue__*_row`, from the unique p_partkey) says the inner fold is that one term, or 0 when no part row hits.
// AGENT_HELPERS_START
proof fn lemma_like_pct(s: Seq<char>)
    ensures spec_like(s, seq!['%']),
    decreases s.len(),
{
    let p = seq!['%'];
    assert(p.len() == 1 && p[0] == '%');
    assert(p.skip(1) =~= Seq::<char>::empty());
    if s.len() == 0 {
        assert(spec_like(s, p.skip(1)));
    } else {
        lemma_like_pct(s.skip(1));
        assert(spec_like(s.skip(1), p));
    }
}

// `col LIKE 'lit%'` for a literal without `%` or `_`: the cell starts with the literal.
proof fn lemma_like_prefix(s: Seq<char>, pre: Seq<char>)
    requires forall|i: int| 0 <= i < pre.len() ==> pre[i] != '%' && pre[i] != '_',
    ensures spec_like(s, pre.push('%')) == (s.len() >= pre.len() && s.subrange(0, pre.len() as int) =~= pre),
    decreases pre.len(),
{
    let p = pre.push('%');
    if pre.len() == 0 {
        assert(p =~= seq!['%']);
        lemma_like_pct(s);
    } else {
        assert(p.len() == pre.len() + 1);
        assert(p[0] == pre[0]);
        assert(p.skip(1) =~= pre.skip(1).push('%'));
        if s.len() > 0 {
            lemma_like_prefix(s.skip(1), pre.skip(1));
            assert(forall|i: int| 0 <= i < pre.skip(1).len() ==> pre.skip(1)[i] != '%' && pre.skip(1)[i] != '_');
            if s.len() >= pre.len() && s[0] == pre[0] && s.skip(1).subrange(0, pre.len() - 1) =~= pre.skip(1) {
                let n = pre.len() as int;
                assert forall|i: int| 0 <= i < n implies s.subrange(0, n)[i] == pre[i] by {
                    if i > 0 {
                        assert(s.skip(1).subrange(0, n - 1)[i - 1] == pre.skip(1)[i - 1]);
                    }
                };
                assert(s.subrange(0, n) =~= pre);
            }
            if s.len() >= pre.len() && s.subrange(0, pre.len() as int) =~= pre {
                assert(s[0] == pre[0]);
                assert(s.skip(1).subrange(0, pre.len() - 1) =~= pre.skip(1));
            }
        }
    }
}

proof fn lemma_promo_like(s: Seq<char>)
    ensures spec_like(s, "PROMO%"@) == (s.len() >= 5 && s[0] == 'P' && s[1] == 'R' && s[2] == 'O' && s[3] == 'M' && s[4] == 'O'),
{
    reveal_strlit("PROMO%");
    let pre = seq!['P', 'R', 'O', 'M', 'O'];
    assert("PROMO%"@ =~= pre.push('%'));
    lemma_like_prefix(s, pre);
    if s.len() >= 5 && s[0] == 'P' && s[1] == 'R' && s[2] == 'O' && s[3] == 'M' && s[4] == 'O' {
        assert(s.subrange(0, 5) =~= pre);
    }
    if s.len() >= 5 && s.subrange(0, 5) =~= pre {
        assert(s[0] == 'P' && s[1] == 'R' && s[2] == 'O' && s[3] == 'M' && s[4] == 'O');
    }
}

// One lineitem row's term: |price * (100 - disc)| <= 16777215 * 115 under the package caps.
proof fn lemma_term_bound(a: int, b: int)
    requires -16777215int <= a <= 16777215int, -15int <= b <= 15int,
    ensures -1929379725int <= a * (100 - b) <= 1929379725int,
{
    assert(85int <= 100 - b <= 115int);
    assert(a * (100 - b) <= 16777215int * 115int) by (nonlinear_arith)
        requires -16777215int <= a <= 16777215int, 85int <= 100 - b <= 115int;
    assert(a * (100 - b) >= -(16777215int * 115int)) by (nonlinear_arith)
        requires -16777215int <= a <= 16777215int, 85int <= 100 - b <= 115int;
}

spec fn key_slot(part: &Cols_part, t: int) -> int {
    part.p_partkey@[t] as int + 262143
}

// The position table: an entry s != 0 names a part row t < done whose key slot is s; every part row t < done has a nonzero entry.
spec fn pos_ok(part: &Cols_part, pos: Seq<u32>, done: int) -> bool {
    &&& pos.len() == 524287
    &&& forall|s: int| #![trigger pos[s]] 0 <= s < 524287 && pos[s] != 0 ==>
        (pos[s] as int) - 1 < done && (pos[s] as int) - 1 < part.n as int && key_slot(part, (pos[s] as int) - 1) == s
    &&& forall|t: int| #![trigger part.p_partkey@[t]] 0 <= t < done ==> pos[key_slot(part, t)] != 0
}

spec fn hit_from(lineitem: &Cols_lineitem, part: &Cols_part, i: int) -> bool {
    exists|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)]
        i <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b)
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    // 1. PROMO flag of each p_type dictionary entry.
    let nd: usize = part.p_type__dict.len();
    let mut promo_code: Vec<bool> = Vec::new();
    let mut c: usize = 0;
    while c < nd
        invariant
            c <= nd,
            nd == part.p_type__dict@.len(),
            promo_code@.len() == c as int,
            forall|e: int| #![trigger promo_code@[e]] 0 <= e < c as int ==> promo_code@[e] == spec_like(part.p_type__dict@[e]@, "PROMO%"@),
        decreases nd - c,
    {
        let ptype: &str = part.p_type__dict[c].as_str();
        let plen = ptype.unicode_len();
        let promo = plen >= 5 && ptype.get_char(0) == 'P' && ptype.get_char(1) == 'R' && ptype.get_char(2) == 'O'
            && ptype.get_char(3) == 'M' && ptype.get_char(4) == 'O';
        proof {
            lemma_promo_like(part.p_type__dict@[c as int]@);
            assert(ptype@ == part.p_type__dict@[c as int]@);
        }
        promo_code.push(promo);
        c += 1;
    }
    // 2. Position table over the part key.
    let mut pos: Vec<u32> = Vec::new();
    let mut z: usize = 0;
    while z < 524287
        invariant
            z <= 524287,
            pos@.len() == z as int,
            forall|s: int| #![trigger pos@[s]] 0 <= s < z as int ==> pos@[s] == 0,
        decreases 524287 - z,
    {
        pos.push(0);
        z += 1;
    }
    let mut t: usize = 0;
    while t < part.n
        invariant
            t <= part.n,
            valid_cols_part(part),
            pos_ok(part, pos@, t as int),
        decreases part.n - t,
    {
        proof {
            assert(part.p_partkey@.len() == part.n as int);
        }
        let key = part.p_partkey[t];
        let slot: usize = (key + 262143) as usize;
        let ghost old_pos = pos@;
        proof {
            assert(key_slot(part, t as int) == slot as int);
        }
        pos.set(slot, (t + 1) as u32);
        proof {
            assert(pos@ == old_pos.update(slot as int, (t + 1) as u32));
            assert forall|s: int| #![trigger pos@[s]] 0 <= s < 524287 && pos@[s] != 0 implies
                (pos@[s] as int) - 1 < t as int + 1 && (pos@[s] as int) - 1 < part.n as int && key_slot(part, (pos@[s] as int) - 1) == s by {
                if s != slot as int {
                    assert(pos@[s] == old_pos[s]);
                }
            };
            assert forall|u: int| #![trigger part.p_partkey@[u]] 0 <= u < t as int + 1 implies pos@[key_slot(part, u)] != 0 by {
                if u < t as int {
                    assert(old_pos[key_slot(part, u)] != 0);
                    if key_slot(part, u) != slot as int {
                        assert(pos@[key_slot(part, u)] == old_pos[key_slot(part, u)]);
                    }
                }
            };
        }
        t += 1;
    }
    // 3. One backward pass over lineitem.
    let mut n_acc: i128 = 0;
    let mut d_acc: i128 = 0;
    let mut any: bool = false;
    let mut i0: usize = lineitem.n;
    while i0 > 0
        invariant
            i0 <= lineitem.n,
            valid_cols_lineitem(lineitem),
            valid_cols_part(part),
            pos_ok(part, pos@, part.n as int),
            nd == part.p_type__dict@.len(),
            promo_code@.len() == nd as int,
            forall|e: int| #![trigger promo_code@[e]] 0 <= e < nd as int ==> promo_code@[e] == spec_like(part.p_type__dict@[e]@, "PROMO%"@),
            n_acc as int == sum_promo_revenue__num(lineitem, part, i0 as int),
            d_acc as int == sum_promo_revenue__den(lineitem, part, i0 as int),
            -((lineitem.n - i0) as int) * 1929379725int <= n_acc as int <= ((lineitem.n - i0) as int) * 1929379725int,
            -((lineitem.n - i0) as int) * 1929379725int <= d_acc as int <= ((lineitem.n - i0) as int) * 1929379725int,
            any <==> hit_from(lineitem, part, i0 as int),
        decreases i0,
    {
        i0 -= 1;
        proof {
            assert(lineitem.l_partkey@.len() == lineitem.n as int);
            assert(lineitem.l_shipdate@.len() == lineitem.n as int);
            assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
            assert(lineitem.l_discount@.len() == lineitem.n as int);
            assert(part.p_partkey@.len() == part.n as int);
            assert(part.p_type@.len() == part.n as int);
            reveal_with_fuel(sum_promo_revenue__num, 2);
            reveal_with_fuel(sum_promo_revenue__den, 2);
            lemma_sum_promo_revenue__num_row(lineitem, part, i0 as int);
            lemma_sum_promo_revenue__den_row(lineitem, part, i0 as int);
        }
        let sd = lineitem.l_shipdate[i0];
        let key = lineitem.l_partkey[i0];
        let p = pos[(key + 262143) as usize];
        let hit = sd >= 9374 && sd < 9404 && p != 0;
        let ghost j = i0 as int;
        let ghost m = (p as int) - 1;
        proof {
            if p != 0 {
                assert(key_slot(part, m) == key as int + 262143);
                assert(part.p_partkey@[m] == lineitem.l_partkey@[j]);
            } else {
                assert forall|y1: int| #![trigger row_hit(lineitem, part, j, y1)] !row_hit(lineitem, part, j, y1) by {
                    if 0 <= y1 < part.n as int && part.p_partkey@[y1] == lineitem.l_partkey@[j] {
                        assert(pos@[key_slot(part, y1)] != 0);
                    }
                };
            }
            if !(sd >= 9374 && sd < 9404) {
                assert forall|y1: int| #![trigger row_hit(lineitem, part, j, y1)] !row_hit(lineitem, part, j, y1) by {};
            }
            assert(hit ==> row_hit(lineitem, part, j, m));
        }
        if hit {
            let price = lineitem.l_extendedprice[i0];
            let disc = lineitem.l_discount[i0];
            let pt = part.p_type[(p - 1) as usize] as usize;
            proof {
                lemma_term_bound(price as int, disc as int);
                assert(pt < nd);
            }
            let val: i128 = (price as i128) * (100 - (disc as i128));
            let promo = promo_code[pt];
            proof {
                assert(sum_promo_revenue__den_d1(lineitem, part, j, 0) == chain_term_sum_promo_revenue__den(lineitem, part, j, m));
                assert(sum_promo_revenue__num_d1(lineitem, part, j, 0) == chain_term_sum_promo_revenue__num(lineitem, part, j, m));
                assert(sum_promo_revenue__den_val(lineitem, part, j, m) == val as int);
                assert(sum_promo_revenue__num_val(lineitem, part, j, m) == (if promo { val as int } else { 0int }));
            }
            d_acc = d_acc + val;
            if promo {
                n_acc = n_acc + val;
            }
            any = true;
        } else {
            proof {
                assert(forall|y1: int| #![trigger row_hit(lineitem, part, j, y1)] !row_hit(lineitem, part, j, y1));
                assert(sum_promo_revenue__den_d1(lineitem, part, j, 0) == 0);
                assert(sum_promo_revenue__num_d1(lineitem, part, j, 0) == 0);
            }
        }
        proof {
            if hit_from(lineitem, part, j) {
                let ab = choose|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)]
                    j <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b);
                if ab.0 > j {
                    assert(hit_from(lineitem, part, j + 1));
                } else {
                    assert(row_hit(lineitem, part, j, ab.1));
                }
            }
            if hit_from(lineitem, part, j + 1) {
                let ab = choose|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)]
                    j + 1 <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b);
                assert(row_hit(lineitem, part, ab.0, ab.1));
            }
            if hit {
                assert(row_hit(lineitem, part, j, m));
            }
        }
    }
    // 4. The exact rational (10000 * N * 10^4) / (D * 10^6) as (100 * N) / D.
    let mut res: Vec<OutRow> = Vec::new();
    if !any {
        res.push(OutRow { promo_revenue: None });
        proof {
            assert(!hit_from(lineitem, part, 0));
            assert forall|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)] !row_hit(lineitem, part, a, b) by {
                if row_hit(lineitem, part, a, b) {
                    assert(0 <= a < lineitem.n as int && 0 <= b < part.n as int);
                }
            };
        }
    } else {
        let ghost nn = n_acc as int;
        let ghost dd = d_acc as int;
        let r: Rat;
        if d_acc > 0 {
            r = Rat { num: 100 * n_acc, den: d_acc };
            proof {
                assert((100 * nn) * (dd * 1000000) == (10000 * nn * 10000) * dd) by (nonlinear_arith);
            }
        } else if d_acc < 0 {
            r = Rat { num: -100 * n_acc, den: -d_acc };
            proof {
                assert((-100 * nn) * (dd * 1000000) == (10000 * nn * 10000) * (-dd)) by (nonlinear_arith);
            }
        } else {
            r = Rat { num: n_acc, den: 0 };
        }
        proof {
            assert(rat_is(r, 10000 * sum_promo_revenue__num(lineitem, part, 0) * 10000, sum_promo_revenue__den(lineitem, part, 0) * 1000000));
            let ab = choose|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)]
                0 <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b);
            assert(row_hit(lineitem, part, ab.0, ab.1));
        }
        res.push(OutRow { promo_revenue: Some(r) });
    }
    res
// AGENT_EDIT_END
