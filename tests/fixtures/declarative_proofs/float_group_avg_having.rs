// Worked example: GROUP BY k, AVG(v) over a DOUBLE column, HAVING AVG(v) > 2. Exact under the f64 idealization.
// Pass 1 collects the distinct keys. Pass 2, per key: an f64 sum and a u64 count over all rows, one division
// (`host_u64_to_f64`, `lemma_f64_div_defined`, `lemma_f64_div_real`), then keep the key when `avg > 2.0`.
// AGENT_HELPERS_START
proof fn bound_step(m: int, p: real)
    ensures ((m + 1) as real) * p == (m as real) * p + p,
{
    assert(((m + 1) as real) == (m as real) + 1real);
    assert(((m as real) + 1real) * p == (m as real) * p + p) by (nonlinear_arith);
}

proof fn bound_below(m: int, p: real)
    requires 0 <= m <= 100, 0real <= p, p <= 0x10000000000000000000000int as real,
    ensures (m as real) * p + 1real + p <= 0x1000000000000000000000000000000000000000000000000000int as real,
{
    assert((m as real) <= 100real);
    assert((m as real) * p <= 100real * p) by (nonlinear_arith)
        requires (m as real) <= 100real, 0real <= p;
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    // Pass 1: the distinct keys.
    let mut ks: Vec<i64> = Vec::new();
    let ghost mut wit: Seq<int> = Seq::empty();
    let mut i: usize = 0;
    while i < t.n
        invariant
            i <= t.n,
            valid_cols_t(t),
            forall|a: int, b: int| 0 <= a < b < ks@.len() ==> ks@[a] != ks@[b],
            wit.len() == ks@.len(),
            forall|r: int| #![trigger wit[r]] 0 <= r < wit.len() ==> 0 <= wit[r] < i as int && t.k@[wit[r]] == ks@[r],
            forall|j: int| #![trigger t.k@[j]] 0 <= j < i as int ==> exists|r: int| #![trigger ks@[r]] 0 <= r < ks@.len() && ks@[r] == t.k@[j],
        decreases t.n - i,
    {
        let k = t.k[i] as i64;
        proof { assert(t.k@.len() == t.n as int); }
        let mut j: usize = 0;
        while j < ks.len() && ks[j] != k
            invariant
                j <= ks@.len(),
                forall|r: int| 0 <= r < j as int ==> ks@[r] != k,
            decreases ks@.len() - j,
        {
            j += 1;
        }
        let ghost old = ks@;
        let ghost old_wit = wit;
        if j == ks.len() {
            ks.push(k);
            proof {
                wit = old_wit.push(i as int);
                assert(ks@ == old.push(k));
                assert forall|a: int, b: int| #![trigger ks@[a], ks@[b]] 0 <= a < b < ks@.len() implies ks@[a] != ks@[b] by {
                    if b == old.len() as int {
                        assert(ks@[a] == old[a]);
                        assert(old[a] != k);
                    }
                };
                assert forall|r: int| #![trigger wit[r]] 0 <= r < wit.len() implies 0 <= wit[r] < (i + 1) as int && t.k@[wit[r]] == ks@[r] by {
                    if r < old.len() as int {
                        assert(wit[r] == old_wit[r]);
                        assert(ks@[r] == old[r]);
                    }
                };
                assert forall|j2: int| #![trigger t.k@[j2]] 0 <= j2 < (i + 1) as int implies exists|r: int| #![trigger ks@[r]] 0 <= r < ks@.len() && ks@[r] == t.k@[j2] by {
                    if j2 == i as int {
                        assert(ks@[old.len() as int] == t.k@[j2]);
                    } else {
                        let r = choose|r: int| 0 <= r < old.len() && old[r] == t.k@[j2];
                        assert(ks@[r] == old[r]);
                    }
                };
            }
        } else {
            proof {
                assert(ks@[j as int] == k);
                assert forall|j2: int| #![trigger t.k@[j2]] 0 <= j2 < (i + 1) as int implies exists|r: int| #![trigger ks@[r]] 0 <= r < ks@.len() && ks@[r] == t.k@[j2] by {
                    if j2 == i as int {
                        assert(ks@[j as int] == t.k@[j2]);
                    }
                };
            }
        }
        i += 1;
    }
    proof {
        assert(i == t.n);
    }
    // Pass 2: one exact f64 sum per key.
    let ghost wit = wit;
    let mut res: Vec<OutRow> = Vec::new();
    let mut r: usize = 0;
    while r < ks.len()
        invariant
            r <= ks@.len(),
            t.n <= ROW_CAP_t,
            valid_cols_t(t),
            f64_literals_ok(),
            forall|a: int, b: int| 0 <= a < b < ks@.len() ==> ks@[a] != ks@[b],
            wit.len() == ks@.len(),
            forall|q: int| #![trigger wit[q]] 0 <= q < wit.len() ==> 0 <= wit[q] < t.n as int && t.k@[wit[q]] == ks@[q],
            forall|u: int| #![trigger res@[u]] 0 <= u < res@.len() ==> out_row_ok(t, res@[u]) && exists|q: int| #![trigger ks@[q]] 0 <= q < r as int && ks@[q] == res@[u].k,
            forall|u: int, w: int| 0 <= u < w < res@.len() ==> res@[u].k != res@[w].k,
            forall|q: int| #![trigger ks@[q]] 0 <= q < r as int && avg_m(t, 0, ks@[q] as int) > 2real ==> exists|u: int| #![trigger res@[u]] 0 <= u < res@.len() && res@[u].k == ks@[q],
        decreases ks@.len() - r,
    {
        let kk = ks[r];
        let mut acc: f64 = 0.0;
        let mut cnt: u64 = 0;
        let mut i: usize = t.n;
        proof {
            assert(avg_m_sum(t, t.n as int, kk as int) == 0real);
            assert(avg_m_count(t, t.n as int, kk as int) == 0);
            assert((MAG_CAP_t_v as real) == 1024real);
            assert((cnt as int as real) == 0real);
            assert((cnt as int as real) * (MAG_CAP_t_v as real) == 0real);
        }
        while i > 0
            invariant
                i <= t.n,
                t.n <= ROW_CAP_t,
                valid_cols_t(t),
                f64_literals_ok(),
                (acc as real) == avg_m_sum(t, i as int, kk as int),
                cnt as int == avg_m_count(t, i as int, kk as int),
                cnt as int <= (t.n - i) as int,
                f64_within(acc, (cnt as int as real) * (MAG_CAP_t_v as real) + 1real),
                (cnt > 0) <==> exists|j: int| #![trigger t.k@[j]] i as int <= j < t.n as int && t.k@[j] == kk,
            decreases i,
        {
            i -= 1;
            let key = t.k[i] as i64;
            let v = t.v[i];
            proof {
                assert(t.k@.len() == t.n as int);
                assert(t.v@.len() == t.n as int);
                assert(t.v@[i as int].is_finite_spec());
                assert(f64_within(v, MAG_CAP_t_v as real));
                assert((MAG_CAP_t_v as real) == 1024real);
                lemma_avg_m_count_bound(t, i as int + 1, kk as int);
                reveal_with_fuel(avg_m_sum, 2);
                bound_step(cnt as int, MAG_CAP_t_v as real);
                bound_below(cnt as int, MAG_CAP_t_v as real);
            }
            if key == kk {
                proof { lemma_f64_add_within(v, acc, MAG_CAP_t_v as real, (cnt as int as real) * (MAG_CAP_t_v as real) + 1real); }
                let next = v + acc;
                proof {
                }
                acc = next;
                cnt = cnt + 1;
                proof { assert(t.k@[i as int] == kk); }
            }
        }
        proof {
            let j = wit[r as int];
            assert(t.k@[j] == kk);
            assert(cnt > 0);
            assert(cnt as int >= 1);
            assert((cnt as int as real) <= 100real);
        }
        let fc = host_u64_to_f64(cnt);
        proof {
            assert(abs_real(fc as real) == (cnt as int as real));
            let cap = MAG_CAP_t_v as real;
            let cq = cap + 1real;
            let c = cnt as int as real;
            assert(-cq * c < (acc as real) && (acc as real) < cq * c) by (nonlinear_arith)
                requires -(c * cap + 1real) < (acc as real), (acc as real) < c * cap + 1real, c >= 1real, cq == cap + 1real;
            lemma_f64_div_real(acc, fc, c * cap + 1real, cq);
        }
        let avg = acc / fc;
        proof {
            let cap = MAG_CAP_t_v as real;
            let c = cnt as int as real;
            assert(avg.is_finite_spec());
        }
        let big = avg > 2.0;
        proof {
            lemma_f64_gt_real(avg, 2.0f64, big);
        }
        let ghost old_res = res@;
        if big {
            res.push(OutRow { k: kk, m: avg });
            proof {
                assert(res@ == old_res.push(OutRow { k: kk, m: avg }));
                let q0 = wit[r as int];
                assert(row_hit(t, q0));
                assert(key_at(t, q0) == (kk as int));
                assert(out_row_ok(t, res@[old_res.len() as int]));
                assert forall|u: int| #![trigger res@[u]] 0 <= u < res@.len() implies out_row_ok(t, res@[u]) && exists|q: int| #![trigger ks@[q]] 0 <= q < (r + 1) as int && ks@[q] == res@[u].k by {
                    if u < old_res.len() as int {
                        assert(res@[u] == old_res[u]);
                        let q = choose|q: int| 0 <= q < r as int && ks@[q] == old_res[u].k;
                        assert(0 <= q < (r + 1) as int);
                    } else {
                        assert(ks@[r as int] == res@[u].k);
                    }
                };
                assert forall|u: int, w: int| #![trigger res@[u], res@[w]] 0 <= u < w < res@.len() implies res@[u].k != res@[w].k by {
                    if w == old_res.len() as int {
                        let q = choose|q: int| 0 <= q < r as int && ks@[q] == old_res[u].k;
                        assert(res@[u] == old_res[u]);
                        assert(ks@[q] != ks@[r as int]);
                    }
                };
                assert forall|q: int| #![trigger ks@[q]] 0 <= q < (r + 1) as int && avg_m(t, 0, ks@[q] as int) > 2real implies exists|u: int| #![trigger res@[u]] 0 <= u < res@.len() && res@[u].k == ks@[q] by {
                    if q == r as int {
                        assert(res@[old_res.len() as int].k == ks@[q]);
                    } else {
                        let u = choose|u: int| 0 <= u < old_res.len() && old_res[u].k == ks@[q];
                        assert(res@[u] == old_res[u]);
                    }
                };
            }
        } else {
            proof {
                assert forall|q: int| #![trigger ks@[q]] 0 <= q < (r + 1) as int && avg_m(t, 0, ks@[q] as int) > 2real implies exists|u: int| #![trigger res@[u]] 0 <= u < res@.len() && res@[u].k == ks@[q] by {
                    if q < r as int {
                        let u = choose|u: int| 0 <= u < res@.len() && res@[u].k == ks@[q];
                    }
                };
                assert forall|u: int| #![trigger res@[u]] 0 <= u < res@.len() implies out_row_ok(t, res@[u]) && exists|q: int| #![trigger ks@[q]] 0 <= q < (r + 1) as int && ks@[q] == res@[u].k by {
                    let q = choose|q: int| 0 <= q < r as int && ks@[q] == res@[u].k;
                };
            }
        }
        r += 1;
    }
    proof {
        assert forall|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && avg_m(t, 0, key_at(t, i0)) > 2real implies exists|u: int| #![trigger res@[u]] 0 <= u < res@.len() && key_at(t, i0) == (res@[u].k as int) by {
            assert(t.k@.len() == t.n as int);
            let q = choose|q: int| 0 <= q < ks@.len() && ks@[q] == t.k@[i0];
        };
    }
    res
// AGENT_EDIT_END
