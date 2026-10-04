// Worked example: GROUP BY k, SUM(v) over a DOUBLE column, HAVING SUM(v) > 10. Exact under the f64 idealization.
// Pass 1 collects the distinct keys. Pass 2 sums each key's rows in an f64 accumulator whose invariant is
// `acc as real == sum_s(...)` (exact, so the HAVING comparison is decided exactly), then keeps the key when
// `acc > 10.0` (`lemma_f64_gt_real` and the literal hypothesis `f64_literals_ok()`).
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
        let k = t.k[i];
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
            forall|q: int| #![trigger ks@[q]] 0 <= q < r as int && sum_s(t, 0, ks@[q] as int) > 10real ==> exists|u: int| #![trigger res@[u]] 0 <= u < res@.len() && res@[u].k == ks@[q],
        decreases ks@.len() - r,
    {
        let kk = ks[r];
        let mut acc: f64 = 0.0;
        let mut i: usize = t.n;
        proof {
            assert(sum_s(t, t.n as int, kk as int) == 0real);
            assert(acc.is_finite_spec());
            assert((acc as real) == 0real);
            assert((MAG_CAP_t_v as real) == 1024real);
            assert(((t.n - t.n) as int as real) == 0real);
            assert(((t.n - t.n) as int as real) * (MAG_CAP_t_v as real) == 0real);
            assert(f64_within(acc, ((t.n - t.n) as int as real) * (MAG_CAP_t_v as real) + 1real));
        }
        while i > 0
            invariant
                i <= t.n,
                t.n <= ROW_CAP_t,
                valid_cols_t(t),
                f64_literals_ok(),
                (acc as real) == sum_s(t, i as int, kk as int),
                f64_within(acc, ((t.n - i) as int as real) * (MAG_CAP_t_v as real) + 1real),
            decreases i,
        {
            i -= 1;
            let key = t.k[i];
            let v = t.v[i];
            proof {
                assert(t.k@.len() == t.n as int);
                assert(t.v@.len() == t.n as int);
                assert(t.v@[i as int].is_finite_spec());
                assert(f64_within(v, MAG_CAP_t_v as real));
                assert((MAG_CAP_t_v as real) == 1024real);
                reveal_with_fuel(sum_s, 2);
                bound_step((t.n - (i + 1)) as int, MAG_CAP_t_v as real);
                bound_below((t.n - (i + 1)) as int, MAG_CAP_t_v as real);
            }
            if key == kk {
                proof { lemma_f64_add_within(v, acc, MAG_CAP_t_v as real, ((t.n - (i + 1)) as int as real) * (MAG_CAP_t_v as real) + 1real); }
                let next = v + acc;
                proof {
                }
                acc = next;
            }
        }
        proof {
            assert(acc.is_finite_spec());
        }
        let big = acc > 10.0;
        proof {
            lemma_f64_gt_real(acc, 10.0f64, big);
        }
        let ghost old_res = res@;
        if big {
            res.push(OutRow { k: kk, s: acc });
            proof {
                assert(res@ == old_res.push(OutRow { k: kk, s: acc }));
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
                assert forall|q: int| #![trigger ks@[q]] 0 <= q < (r + 1) as int && sum_s(t, 0, ks@[q] as int) > 10real implies exists|u: int| #![trigger res@[u]] 0 <= u < res@.len() && res@[u].k == ks@[q] by {
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
                assert forall|q: int| #![trigger ks@[q]] 0 <= q < (r + 1) as int && sum_s(t, 0, ks@[q] as int) > 10real implies exists|u: int| #![trigger res@[u]] 0 <= u < res@.len() && res@[u].k == ks@[q] by {
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
        assert forall|i0: int| #![trigger row_hit(t, i0)] row_hit(t, i0) && sum_s(t, 0, key_at(t, i0)) > 10real implies exists|u: int| #![trigger res@[u]] 0 <= u < res@.len() && key_at(t, i0) == (res@[u].k as int) by {
            assert(t.k@.len() == t.n as int);
            let q = choose|q: int| 0 <= q < ks@.len() && ks@[q] == t.k@[i0];
        };
    }
    res
// AGENT_EDIT_END
