// Worked example: TPC-H Q14,
//   SELECT 100.00 * SUM(CASE WHEN p_type LIKE 'PROMO%' THEN l_extendedprice * (1 - l_discount) ELSE 0 END)
//          / SUM(l_extendedprice * (1 - l_discount)) AS promo_revenue
//   FROM lineitem, part WHERE l_partkey = p_partkey AND l_shipdate >= DATE '1995-09-01' AND l_shipdate < DATE '1995-09-01' + INTERVAL '1' MONTH
// a ratio of two exact DECIMAL sums, divided in DOUBLE like DuckDB. Reference body (sequential nested loop, no hash join):
// * the two i128 sums are folded backwards over the lineitem x part pairs, so each loop step is one unfolding of the
//   emitted `sum_*_d1` / `sum_*` (join_group_sum.rs pattern); `any` tracks whether some pair hit (the SUM is NULL otherwise);
// * `p_type LIKE 'PROMO%'` is decided by `unicode_len` / `get_char` (exact vstd specs) and `lemma_promo_like`: for a literal
//   without `%` or `_`, `LIKE 'lit%'` is "starts with lit" (`lemma_like_prefix`, proved by induction on the literal);
// * the ratio: cast both sums (`host_i128_to_f64`), scale by the constants 10^8 and 10^6 (cast from u64: the proof can
//   not use float literals), divide once (`lemma_f64_div_real`); a zero denominator takes `host_f64_div_by_zero`.
// Assumption of this body: ROW_CAP_lineitem * ROW_CAP_part * (1.1e30 per-pair bound) fits i128, i.e. the row caps' product is
// at most about 1.5e8 (the SF 0.01 and mini catalogs; at SF 1 a hash join and the part key's uniqueness are needed instead).
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

// One pair's contribution: |price * (100 - disc)| < 1.1e30 for DECIMAL(15,2) cells.
proof fn lemma_term_bound(a: int, b: int)
    requires -999999999999999int <= a <= 999999999999999int, -999999999999999int <= b <= 999999999999999int,
    ensures -1100000000000000000000000000000int <= a * (100 - b) <= 1100000000000000000000000000000int,
{
    assert(-1000000000000099int <= 100 - b <= 1000000000000099int);
    assert(a * (100 - b) <= 999999999999999int * 1000000000000099int) by (nonlinear_arith)
        requires -999999999999999int <= a <= 999999999999999int, -1000000000000099int <= 100 - b <= 1000000000000099int;
    assert(a * (100 - b) >= -(999999999999999int * 1000000000000099int)) by (nonlinear_arith)
        requires -999999999999999int <= a <= 999999999999999int, -1000000000000099int <= 100 - b <= 1000000000000099int;
}

proof fn lemma_pair_count_fits(m: int, nl: int, np: int)
    requires 0 <= m <= nl * np, 0 <= nl <= 60175, 0 <= np <= 2000,
    ensures m <= 120350000int,
{
    assert(nl * np <= 60175 * 2000) by (nonlinear_arith)
        requires 0 <= nl <= 60175, 0 <= np <= 2000;
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let mut n_acc: i128 = 0;
    let mut d_acc: i128 = 0;
    let mut any: bool = false;
    let ghost mut m: int = 0;
    let mut i0: usize = lineitem.n;
    while i0 > 0
        invariant
            i0 <= lineitem.n,
            valid_cols_lineitem(lineitem),
            valid_cols_part(part),
            n_acc as int == sum_promo_revenue__num(lineitem, part, i0 as int),
            d_acc as int == sum_promo_revenue__den(lineitem, part, i0 as int),
            m == (lineitem.n as int - i0 as int) * (part.n as int),
            0 <= m <= lineitem.n as int * part.n as int,
            -m * 1100000000000000000000000000000int <= n_acc as int <= m * 1100000000000000000000000000000int,
            -m * 1100000000000000000000000000000int <= d_acc as int <= m * 1100000000000000000000000000000int,
            any <==> exists|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)]
                i0 as int <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b),
        decreases i0,
    {
        i0 -= 1;
        let ghost m_row = m;
        let mut i1: usize = part.n;
        proof {
            assert(sum_promo_revenue__num_d1(lineitem, part, i0 as int, part.n as int) == 0);
            assert(sum_promo_revenue__den_d1(lineitem, part, i0 as int, part.n as int) == 0);
            assert(m_row == (lineitem.n as int - i0 as int - 1) * (part.n as int));
            assert((lineitem.n as int - i0 as int) * (part.n as int) == m_row + part.n as int) by (nonlinear_arith)
                requires m_row == (lineitem.n as int - i0 as int - 1) * (part.n as int);
            assert(m_row + part.n as int <= lineitem.n as int * part.n as int) by (nonlinear_arith)
                requires m_row + part.n as int == (lineitem.n as int - i0 as int) * (part.n as int), 0 <= i0 as int;
            assert(i0 as int + 1 <= lineitem.n as int);
        }
        while i1 > 0
            invariant
                i0 < lineitem.n,
                i1 <= part.n,
                valid_cols_lineitem(lineitem),
                valid_cols_part(part),
                n_acc as int == sum_promo_revenue__num_d1(lineitem, part, i0 as int, i1 as int) + sum_promo_revenue__num(lineitem, part, i0 as int + 1),
                d_acc as int == sum_promo_revenue__den_d1(lineitem, part, i0 as int, i1 as int) + sum_promo_revenue__den(lineitem, part, i0 as int + 1),
                m == m_row + (part.n as int - i1 as int),
                m_row + part.n as int <= lineitem.n as int * part.n as int,
                0 <= m_row,
                m <= m_row + part.n as int,
                -m * 1100000000000000000000000000000int <= n_acc as int <= m * 1100000000000000000000000000000int,
                -m * 1100000000000000000000000000000int <= d_acc as int <= m * 1100000000000000000000000000000int,
                any <==> ((exists|b: int| #![trigger row_hit(lineitem, part, i0 as int, b)]
                    i1 as int <= b < part.n as int && row_hit(lineitem, part, i0 as int, b))
                    || (exists|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)]
                        i0 as int + 1 <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b))),
            decreases i1,
        {
            i1 -= 1;
            let ghost m_old = m;
            proof {
                m = m + 1;
                assert(lineitem.l_partkey@.len() == lineitem.n as int);
                assert(lineitem.l_shipdate@.len() == lineitem.n as int);
                assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
                assert(lineitem.l_discount@.len() == lineitem.n as int);
                assert(part.p_partkey@.len() == part.n as int);
                assert(part.p_type@.len() == part.n as int);
                reveal_with_fuel(sum_promo_revenue__num_d1, 2);
                reveal_with_fuel(sum_promo_revenue__den_d1, 2);
                lemma_pair_count_fits(m, lineitem.n as int, part.n as int);
            }
            let price = lineitem.l_extendedprice[i0];
            let disc = lineitem.l_discount[i0];
            let sd = lineitem.l_shipdate[i0];
            let hit = lineitem.l_partkey[i0] == part.p_partkey[i1] && sd >= 9374 && sd < 9404;
            proof {
                assert(row_hit(lineitem, part, i0 as int, i1 as int) <==> hit);
                lemma_term_bound(price as int, disc as int);
            }
            let ptype: &str = part.p_type[i1].as_str();
            let plen = ptype.unicode_len();
            let promo = plen >= 5 && ptype.get_char(0) == 'P' && ptype.get_char(1) == 'R' && ptype.get_char(2) == 'O'
                && ptype.get_char(3) == 'M' && ptype.get_char(4) == 'O';
            proof {
                lemma_promo_like(part.p_type@[i1 as int]@);
                assert(ptype@ == part.p_type@[i1 as int]@);
                assert(promo == spec_like(part.p_type@[i1 as int]@, "PROMO%"@));
            }
            if hit {
                let val: i128 = (price as i128) * (100 - (disc as i128));
                proof {
                    assert(val as int == (lineitem.l_extendedprice@[i0 as int] as int) * (100 - (lineitem.l_discount@[i0 as int] as int)));
                    assert(sum_promo_revenue__den_val(lineitem, part, i0 as int, i1 as int) == val as int);
                    assert(sum_promo_revenue__num_val(lineitem, part, i0 as int, i1 as int) == (if promo { val as int } else { 0int }));
                }
                d_acc = d_acc + val;
                if promo {
                    n_acc = n_acc + val;
                }
                any = true;
            }
            proof {
                if !hit {
                    assert(!row_hit(lineitem, part, i0 as int, i1 as int));
                }
                assert forall|b: int| #![trigger row_hit(lineitem, part, i0 as int, b)] i1 as int <= b < part.n as int && row_hit(lineitem, part, i0 as int, b)
                    implies (hit || exists|b2: int| #![trigger row_hit(lineitem, part, i0 as int, b2)] i1 as int + 1 <= b2 < part.n as int && row_hit(lineitem, part, i0 as int, b2)) by {
                    if b > i1 as int {
                        assert(i1 as int + 1 <= b < part.n as int);
                    }
                };
            }
        }
        proof {
            assert(sum_promo_revenue__num(lineitem, part, i0 as int) == sum_promo_revenue__num_d1(lineitem, part, i0 as int, 0) + sum_promo_revenue__num(lineitem, part, i0 as int + 1)) by {
                reveal_with_fuel(sum_promo_revenue__num, 2);
            };
            assert(sum_promo_revenue__den(lineitem, part, i0 as int) == sum_promo_revenue__den_d1(lineitem, part, i0 as int, 0) + sum_promo_revenue__den(lineitem, part, i0 as int + 1)) by {
                reveal_with_fuel(sum_promo_revenue__den, 2);
            };
            assert forall|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)] i0 as int <= a < lineitem.n as int && 0 <= b < part.n as int && row_hit(lineitem, part, a, b)
                implies (exists|b2: int| #![trigger row_hit(lineitem, part, i0 as int, b2)] 0 <= b2 < part.n as int && row_hit(lineitem, part, i0 as int, b2))
                    || exists|a2: int, b2: int| #![trigger row_hit(lineitem, part, a2, b2)] i0 as int + 1 <= a2 < lineitem.n as int && 0 <= b2 < part.n as int && row_hit(lineitem, part, a2, b2) by {
                if a == i0 as int {
                    assert(0 <= b < part.n as int);
                } else {
                    assert(i0 as int + 1 <= a < lineitem.n as int);
                }
            };
            assert(m == (lineitem.n as int - i0 as int) * (part.n as int));
        }
    }
    let ghost n_int = n_acc as int;
    let ghost d_int = d_acc as int;
    proof {
        assert(n_int == sum_promo_revenue__num(lineitem, part, 0));
        assert(d_int == sum_promo_revenue__den(lineitem, part, 0));
    }
    let mut res: Vec<OutRow> = Vec::new();
    if !any {
        res.push(OutRow { promo_revenue: None });
        proof {
            assert(!(exists|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)] row_hit(lineitem, part, a, b))) by {
                assert forall|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)] !row_hit(lineitem, part, a, b) by {
                    if 0 <= a < lineitem.n as int && 0 <= b < part.n as int {
                    }
                };
            };
            assert(res@[0].promo_revenue is None);
        }
    } else {
        let fnum = host_i128_to_f64(n_acc);
        let fden = host_i128_to_f64(d_acc);
        let v: f64;
        if d_acc == 0 {
            v = host_f64_div_by_zero(fnum);
        } else {
            let k1 = host_u64_to_f64(100000000);
            let k2 = host_u64_to_f64(1000000);
            proof {
                assert((fnum as real) == (n_acc as int as real));
                assert((fden as real) == (d_acc as int as real));
                assert((k1 as real) == 100000000real);
                assert((k2 as real) == 1000000real);
                assert(f64_within(fnum, 0x100000000000000000000000000000000int as real));
                assert(f64_within(fden, 0x100000000000000000000000000000000int as real));
                assert(f64_within(k1, 134217728real));
                assert(f64_within(k2, 1048576real));
                lemma_f64_mul_real(fnum, k1, 0x100000000000000000000000000000000int as real, 134217728real);
                lemma_f64_mul_real(fden, k2, 0x100000000000000000000000000000000int as real, 1048576real);
            }
            let x = fnum * k1;
            let y = fden * k2;
            proof {
                assert((x as real) == (fnum as real) * 100000000real);
                assert((y as real) == (fden as real) * 1000000real);
                assert(f64_within(x, 0x100000000000000000000000000000000int as real * 134217728real));
                assert(f64_within(y, 0x100000000000000000000000000000000int as real * 1048576real));
                // |y| >= 1e6: the denominator sum is a nonzero integer
                assert(d_acc as int != 0);
                assert(abs_real(y as real) >= 1000000real) by {
                    let dr = d_acc as int as real;
                    assert(dr >= 1real || dr <= -1real);
                };
                lemma_f64_div_real(x, y, 0x100000000000000000000000000000000int as real * 134217728real, 0x100000000000000000000000000000000int as real * 134217728real);
            }
            v = x / y;
            proof {
                assert((v as real) == (x as real) / (y as real));
            }
        }
        res.push(OutRow { promo_revenue: Some(v) });
        proof {
            assert((fnum as real) == (n_acc as int as real));
            assert(exists|a: int, b: int| #![trigger row_hit(lineitem, part, a, b)] row_hit(lineitem, part, a, b));
            assert(res@[0].promo_revenue is Some);
            assert(res@[0].promo_revenue->Some_0 == v);
        }
    }
    res
// AGENT_EDIT_END
