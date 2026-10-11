// Worked example (hard, long; PARALLEL + dict, LEMMA_PARALLEL_VSTD=1 and LEMMA_STRING_ENCODING=dict): TPC-H Q1: two dictionary string keys, four
// aggregates (three decimal sums incl. a product, a count), ORDER BY the keys, 8 vstd workers with one flat slot array of m1*m2 slots each.
// Found by a manual prover (5 checks). TPC-H SF3 (18.0M lineitem rows): 21.9 ms (median of 9; best 21.6 ms) vs 86.6 ms for the all-core reference engine
// (3.95x, above the 2.8x TPC-H target), 295.0 ms for one thread (13.5x); 87 verified, 0 errors at the default rlimit.
// Techniques (each fixed a failure that cost a check):
// * slot = c1 * m2 + c2: build the Vec by nested push loops with invariant `len == a1 * m2 + a2`, read `v.len()` (a usize, so m1 * m2 fits), bound slot
//   arithmetic with `lemma_sl_range` / `lemma_sl_inj` (nonlinear_arith).
// * Per-slot invariants as two opaque bundles: `grid_eq` (acc == fold(lo) - fold(hi) for key (dict1[c1], dict2[c2]), trigger `dk(t, c1, c2)`) and a keyless
//   `grid_bd` (overflow bounds: rows seen * 1e15, times 2e30 for the product sum, count <= rows seen). Product bound: the `mul_small` technique.
// * Cover invariants of the form `forall r. exists a, b. kk(r) == dk(a, b)` never fire (the key term sits only under the inner exists): wrap the inner
//   existential in a NAMED spec fn that takes the key as a parameter (`src_of(l, k, c1, c2)`), state the invariant as `forall r ==> src_of(l, kk(r), ..)`, and
//   prove the steps pointwise (`lemma_src_skip`, `lemma_src_next`) from `assert forall .. by { let k0 = kk(..); ... }`.
// * Merge: join the 8 results (the Err arm recomputes the chunk inline) and add them slotwise (`lemma_merge_ok`); emit by nested loops over c1, c2 with a sorted
//   insertion using `pair_le` and a get_char comparison loop (as in hard/group_decimal_sums_string_keys_sorted.rs).
// AGENT_HELPERS_START
spec fn m1_of(t: &Cols_lineitem) -> int { t.l_returnflag__dict@.len() as int }
spec fn m2_of(t: &Cols_lineitem) -> int { t.l_linestatus__dict@.len() as int }
spec fn mg(t: &Cols_lineitem) -> int { m1_of(t) * m2_of(t) }
spec fn dk(t: &Cols_lineitem, a: int, b: int) -> (Seq<char>, Seq<char>) {
    (t.l_returnflag__dict@[a]@, t.l_linestatus__dict@[b]@)
}
spec fn sl(m2: int, c1: int, c2: int) -> int { c1 * m2 + c2 }

proof fn lemma_sl_range(m1: int, m2: int, c1: int, c2: int)
    requires 0 <= c1 < m1, 0 <= c2 < m2,
    ensures 0 <= c1 * m2, c1 * m2 <= sl(m2, c1, c2), 0 <= sl(m2, c1, c2) < m1 * m2,
{
    assert(c1 * m2 >= 0) by (nonlinear_arith) requires c1 >= 0, m2 >= 0;
    assert((m1 - c1 - 1) * m2 >= 0) by (nonlinear_arith) requires m1 - c1 - 1 >= 0, m2 >= 0;
    assert(m1 * m2 == (m1 - c1 - 1) * m2 + c1 * m2 + m2) by (nonlinear_arith);
}

proof fn lemma_sl_inj(m2: int, a: int, b: int, c: int, d: int)
    requires 0 <= a, 0 <= c, 0 <= b < m2, 0 <= d < m2, sl(m2, a, b) == sl(m2, c, d),
    ensures a == c, b == d,
{
    if a < c {
        assert(c * m2 >= (a + 1) * m2) by (nonlinear_arith) requires c >= a + 1, m2 >= 0;
        assert((a + 1) * m2 == a * m2 + m2) by (nonlinear_arith);
    }
    if c < a {
        assert(a * m2 >= (c + 1) * m2) by (nonlinear_arith) requires a >= c + 1, m2 >= 0;
        assert((c + 1) * m2 == c * m2 + m2) by (nonlinear_arith);
    }
}

proof fn lemma_dict_eq(t: &Cols_lineitem, a: int, c: int, b: int, d: int)
    requires
        valid_cols_lineitem(t),
        0 <= a < m1_of(t), 0 <= c < m1_of(t), 0 <= b < m2_of(t), 0 <= d < m2_of(t),
        dk(t, a, b) == dk(t, c, d),
    ensures a == c, b == d,
{
    if a != c {
        if a < c {
            assert(t.l_returnflag__dict@[a]@ != t.l_returnflag__dict@[c]@);
        } else {
            assert(t.l_returnflag__dict@[c]@ != t.l_returnflag__dict@[a]@);
        }
    }
    if b != d {
        if b < d {
            assert(t.l_linestatus__dict@[b]@ != t.l_linestatus__dict@[d]@);
        } else {
            assert(t.l_linestatus__dict@[d]@ != t.l_linestatus__dict@[b]@);
        }
    }
}

proof fn mul_small(p: int, d: int)
    requires
        -999999999999999 <= p <= 999999999999999,
        -999999999999999 <= d <= 999999999999999,
    ensures -2000000000000000000000000000000int <= p * (100 - d) <= 2000000000000000000000000000000int,
{
    let e = 100 - d;
    assert(0 <= (999999999999999 - p) * (1000000000000100 + e)) by (nonlinear_arith)
        requires 0 <= 999999999999999 - p, 0 <= 1000000000000100 + e;
    assert(0 <= (999999999999999 + p) * (1000000000000100 - e)) by (nonlinear_arith)
        requires 0 <= 999999999999999 + p, 0 <= 1000000000000100 - e;
    assert(0 <= (999999999999999 - p) * (1000000000000100 - e)) by (nonlinear_arith)
        requires 0 <= 999999999999999 - p, 0 <= 1000000000000100 - e;
    assert(0 <= (999999999999999 + p) * (1000000000000100 + e)) by (nonlinear_arith)
        requires 0 <= 999999999999999 + p, 0 <= 1000000000000100 + e;
    assert(p * e <= 999999999999999 * 1000000000000100 && -(999999999999999 * 1000000000000100) <= p * e) by (nonlinear_arith)
        requires
            0 <= (999999999999999 - p) * (1000000000000100 + e),
            0 <= (999999999999999 + p) * (1000000000000100 - e),
            0 <= (999999999999999 - p) * (1000000000000100 - e),
            0 <= (999999999999999 + p) * (1000000000000100 + e);
}

proof fn lemma_cells(l: &Cols_lineitem, i: int)
    requires valid_cols_lineitem(l), 0 <= i < l.n as int,
    ensures
        -999999999999999 <= l.l_quantity@[i] as int <= 999999999999999,
        -999999999999999 <= l.l_extendedprice@[i] as int <= 999999999999999,
        -999999999999999 <= l.l_discount@[i] as int <= 999999999999999,
{
}

spec fn hit_key(l: &Cols_lineitem, w: int, k: (Seq<char>, Seq<char>)) -> bool {
    row_hit(l, w) && key_at(l, w) == k
}

spec fn wit(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>)) -> bool {
    exists|w: int| #![trigger hit_key(l, w, k)] i <= w < l.n as int && hit_key(l, w, k)
}

proof fn lemma_sums_step(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>))
    requires 0 <= i < l.n as int,
    ensures
        sum_sum_qty(l, i, k) == (if hit_key(l, i, k) { sum_sum_qty_val(l, i) } else { 0int }) + sum_sum_qty(l, i + 1, k),
        sum_sum_base_price(l, i, k) == (if hit_key(l, i, k) { sum_sum_base_price_val(l, i) } else { 0int }) + sum_sum_base_price(l, i + 1, k),
        sum_sum_disc_price(l, i, k) == (if hit_key(l, i, k) { sum_sum_disc_price_val(l, i) } else { 0int }) + sum_sum_disc_price(l, i + 1, k),
        count_count_order(l, i, k) == (if hit_key(l, i, k) { 1int } else { 0int }) + count_count_order(l, i + 1, k),
{
    reveal_with_fuel(sum_sum_qty, 2);
    reveal_with_fuel(sum_sum_base_price, 2);
    reveal_with_fuel(sum_sum_disc_price, 2);
    reveal_with_fuel(count_count_order, 2);
}

proof fn lemma_fold_end(l: &Cols_lineitem, k: (Seq<char>, Seq<char>))
    ensures
        sum_sum_qty(l, l.n as int, k) == 0,
        sum_sum_base_price(l, l.n as int, k) == 0,
        sum_sum_disc_price(l, l.n as int, k) == 0,
        count_count_order(l, l.n as int, k) == 0,
{
    reveal_with_fuel(sum_sum_qty, 2);
    reveal_with_fuel(sum_sum_base_price, 2);
    reveal_with_fuel(sum_sum_disc_price, 2);
    reveal_with_fuel(count_count_order, 2);
}

proof fn lemma_count_wit(l: &Cols_lineitem, i: int, k: (Seq<char>, Seq<char>))
    requires 0 <= i <= l.n as int,
    ensures count_count_order(l, i, k) > 0 <==> wit(l, i, k),
    decreases l.n as int - i,
{
    if i < l.n as int {
        lemma_count_wit(l, i + 1, k);
        lemma_count_count_order_bound(l, i + 1, k);
        lemma_sums_step(l, i, k);
        if hit_key(l, i, k) {
            assert(i <= i && i < l.n as int && hit_key(l, i, k));
        } else {
            if wit(l, i, k) {
                let w = choose|w: int| i <= w < l.n as int && hit_key(l, w, k);
                assert(w != i);
                assert(i + 1 <= w < l.n as int && hit_key(l, w, k));
            }
            if wit(l, i + 1, k) {
                let w = choose|w: int| i + 1 <= w < l.n as int && hit_key(l, w, k);
                assert(i <= w < l.n as int && hit_key(l, w, k));
            }
        }
    } else {
        lemma_fold_end(l, k);
    }
}

spec fn eqs(t: &Cols_lineitem, lo: int, hi: int, k: (Seq<char>, Seq<char>), a: (i128, i128, i128, u64)) -> bool {
    &&& a.0 as int == sum_sum_qty(t, lo, k) - sum_sum_qty(t, hi, k)
    &&& a.1 as int == sum_sum_base_price(t, lo, k) - sum_sum_base_price(t, hi, k)
    &&& a.2 as int == sum_sum_disc_price(t, lo, k) - sum_sum_disc_price(t, hi, k)
    &&& a.3 as int == count_count_order(t, lo, k) - count_count_order(t, hi, k)
}

spec fn bd1(a: (i128, i128, i128, u64), w: int) -> bool {
    &&& -(w * 1000000000000000int) <= a.0 as int
    &&& a.0 as int <= w * 1000000000000000int
    &&& -(w * 1000000000000000int) <= a.1 as int
    &&& a.1 as int <= w * 1000000000000000int
    &&& -(w * 2000000000000000000000000000000int) <= a.2 as int
    &&& a.2 as int <= w * 2000000000000000000000000000000int
    &&& a.3 as int <= w
}

spec fn sums0(t: &Cols_lineitem, k: (Seq<char>, Seq<char>), a: (i128, i128, i128, u64)) -> bool {
    &&& a.0 as int == sum_sum_qty(t, 0, k)
    &&& a.1 as int == sum_sum_base_price(t, 0, k)
    &&& a.2 as int == sum_sum_disc_price(t, 0, k)
    &&& a.3 as int == count_count_order(t, 0, k)
}

#[verifier::opaque]
spec fn grid_eq(t: &Cols_lineitem, v: Seq<(i128, i128, i128, u64)>, lo: int, hi: int) -> bool {
    forall|c1: int, c2: int| #![trigger dk(t, c1, c2)]
        0 <= c1 < m1_of(t) && 0 <= c2 < m2_of(t) ==> eqs(t, lo, hi, dk(t, c1, c2), v[sl(m2_of(t), c1, c2)])
}

#[verifier::opaque]
spec fn grid_bd(v: Seq<(i128, i128, i128, u64)>, w: int) -> bool {
    forall|s: int| #![trigger v[s]] 0 <= s < v.len() ==> bd1(v[s], w)
}

#[verifier::opaque]
spec fn grid0(t: &Cols_lineitem, v: Seq<(i128, i128, i128, u64)>) -> bool {
    forall|c1: int, c2: int| #![trigger dk(t, c1, c2)]
        0 <= c1 < m1_of(t) && 0 <= c2 < m2_of(t) ==> sums0(t, dk(t, c1, c2), v[sl(m2_of(t), c1, c2)])
}

proof fn lemma_grid_get(t: &Cols_lineitem, v: Seq<(i128, i128, i128, u64)>, lo: int, hi: int, c1: int, c2: int)
    requires grid_eq(t, v, lo, hi), 0 <= c1 < m1_of(t), 0 <= c2 < m2_of(t),
    ensures eqs(t, lo, hi, dk(t, c1, c2), v[sl(m2_of(t), c1, c2)]),
{
    reveal(grid_eq);
    let _k = dk(t, c1, c2);
}

proof fn lemma_grid0_get(t: &Cols_lineitem, v: Seq<(i128, i128, i128, u64)>, c1: int, c2: int)
    requires grid0(t, v), 0 <= c1 < m1_of(t), 0 <= c2 < m2_of(t),
    ensures sums0(t, dk(t, c1, c2), v[sl(m2_of(t), c1, c2)]),
{
    reveal(grid0);
    let _k = dk(t, c1, c2);
}

proof fn lemma_bd_get(v: Seq<(i128, i128, i128, u64)>, w: int, s: int)
    requires grid_bd(v, w), 0 <= s < v.len(),
    ensures bd1(v[s], w),
{
    reveal(grid_bd);
}

proof fn lemma_init_zero(t: &Cols_lineitem, v: Seq<(i128, i128, i128, u64)>, hi: int)
    requires
        v.len() == mg(t),
        forall|s: int| #![trigger v[s]] 0 <= s < v.len() ==> v[s] == (0i128, 0i128, 0i128, 0u64),
    ensures grid_eq(t, v, hi, hi), grid_bd(v, 0),
{
    reveal(grid_eq);
    reveal(grid_bd);
    assert forall|c1: int, c2: int| #![trigger dk(t, c1, c2)]
        0 <= c1 < m1_of(t) && 0 <= c2 < m2_of(t) implies eqs(t, hi, hi, dk(t, c1, c2), v[sl(m2_of(t), c1, c2)]) by {
        lemma_sl_range(m1_of(t), m2_of(t), c1, c2);
        assert(v[sl(m2_of(t), c1, c2)] == (0i128, 0i128, 0i128, 0u64));
    };
}

proof fn lemma_row_pair(t: &Cols_lineitem, i: int, c1: int, c2: int)
    requires
        valid_cols_lineitem(t),
        0 <= i < t.n as int,
        0 <= c1 < m1_of(t),
        0 <= c2 < m2_of(t),
    ensures
        sum_sum_qty(t, i, dk(t, c1, c2)) == sum_sum_qty(t, i + 1, dk(t, c1, c2))
            + (if row_hit(t, i) && c1 == t.l_returnflag@[i] as int && c2 == t.l_linestatus@[i] as int { sum_sum_qty_val(t, i) } else { 0int }),
        sum_sum_base_price(t, i, dk(t, c1, c2)) == sum_sum_base_price(t, i + 1, dk(t, c1, c2))
            + (if row_hit(t, i) && c1 == t.l_returnflag@[i] as int && c2 == t.l_linestatus@[i] as int { sum_sum_base_price_val(t, i) } else { 0int }),
        sum_sum_disc_price(t, i, dk(t, c1, c2)) == sum_sum_disc_price(t, i + 1, dk(t, c1, c2))
            + (if row_hit(t, i) && c1 == t.l_returnflag@[i] as int && c2 == t.l_linestatus@[i] as int { sum_sum_disc_price_val(t, i) } else { 0int }),
        count_count_order(t, i, dk(t, c1, c2)) == count_count_order(t, i + 1, dk(t, c1, c2))
            + (if row_hit(t, i) && c1 == t.l_returnflag@[i] as int && c2 == t.l_linestatus@[i] as int { 1int } else { 0int }),
{
    lemma_sums_step(t, i, dk(t, c1, c2));
    let a = t.l_returnflag@[i] as int;
    let b = t.l_linestatus@[i] as int;
    assert(a < m1_of(t));
    assert(b < m2_of(t));
    assert(key_at(t, i) == dk(t, a, b));
    if key_at(t, i) == dk(t, c1, c2) {
        lemma_dict_eq(t, a, c1, b, c2);
    }
    assert(hit_key(t, i, dk(t, c1, c2)) == (row_hit(t, i) && c1 == a && c2 == b));
}

proof fn lemma_step_hit(t: &Cols_lineitem, i: int, hi: int, old: Seq<(i128, i128, i128, u64)>, nw: Seq<(i128, i128, i128, u64)>, c1: int, c2: int, a: (i128, i128, i128, u64))
    requires
        valid_cols_lineitem(t),
        0 <= i < hi,
        hi <= t.n as int,
        row_hit(t, i),
        c1 == t.l_returnflag@[i] as int,
        c2 == t.l_linestatus@[i] as int,
        old.len() == mg(t),
        grid_eq(t, old, i + 1, hi),
        grid_bd(old, hi - i - 1),
        a.0 as int == old[sl(m2_of(t), c1, c2)].0 as int + sum_sum_qty_val(t, i),
        a.1 as int == old[sl(m2_of(t), c1, c2)].1 as int + sum_sum_base_price_val(t, i),
        a.2 as int == old[sl(m2_of(t), c1, c2)].2 as int + sum_sum_disc_price_val(t, i),
        a.3 as int == old[sl(m2_of(t), c1, c2)].3 as int + 1,
        nw == old.update(sl(m2_of(t), c1, c2), a),
    ensures grid_eq(t, nw, i, hi), grid_bd(nw, hi - i),
{
    let m1 = m1_of(t);
    let m2 = m2_of(t);
    assert(c1 < m1);
    assert(c2 < m2);
    lemma_sl_range(m1, m2, c1, c2);
    lemma_cells(t, i);
    mul_small(t.l_extendedprice@[i] as int, t.l_discount@[i] as int);
    assert(sum_sum_disc_price_val(t, i) == (t.l_extendedprice@[i] as int) * (100 - (t.l_discount@[i] as int)));
    assert(sum_sum_qty_val(t, i) == t.l_quantity@[i] as int);
    assert(sum_sum_base_price_val(t, i) == t.l_extendedprice@[i] as int);
    let s = sl(m2, c1, c2);
    assert(nw.len() == old.len());
    reveal(grid_eq);
    assert forall|d1: int, d2: int| #![trigger dk(t, d1, d2)]
        0 <= d1 < m1 && 0 <= d2 < m2 implies eqs(t, i, hi, dk(t, d1, d2), nw[sl(m2, d1, d2)]) by {
        lemma_sl_range(m1, m2, d1, d2);
        lemma_grid_get(t, old, i + 1, hi, d1, d2);
        lemma_row_pair(t, i, d1, d2);
        if d1 == c1 && d2 == c2 {
            assert(nw[s] == a);
        } else {
            if sl(m2, d1, d2) == s {
                lemma_sl_inj(m2, d1, d2, c1, c2);
            }
            assert(sl(m2, d1, d2) != s);
            assert(nw[sl(m2, d1, d2)] == old[sl(m2, d1, d2)]);
        }
    };
    reveal(grid_bd);
    assert forall|q: int| #![trigger nw[q]] 0 <= q < nw.len() implies bd1(nw[q], hi - i) by {
        lemma_bd_get(old, hi - i - 1, q);
        if q == s {
        } else {
            assert(nw[q] == old[q]);
        }
    };
}

proof fn lemma_step_skip(t: &Cols_lineitem, i: int, hi: int, old: Seq<(i128, i128, i128, u64)>)
    requires
        valid_cols_lineitem(t),
        0 <= i < hi,
        hi <= t.n as int,
        !row_hit(t, i),
        grid_eq(t, old, i + 1, hi),
        grid_bd(old, hi - i - 1),
    ensures grid_eq(t, old, i, hi), grid_bd(old, hi - i),
{
    let m1 = m1_of(t);
    let m2 = m2_of(t);
    reveal(grid_eq);
    assert forall|d1: int, d2: int| #![trigger dk(t, d1, d2)]
        0 <= d1 < m1 && 0 <= d2 < m2 implies eqs(t, i, hi, dk(t, d1, d2), old[sl(m2, d1, d2)]) by {
        lemma_grid_get(t, old, i + 1, hi, d1, d2);
        lemma_row_pair(t, i, d1, d2);
    };
    reveal(grid_bd);
    assert forall|q: int| #![trigger old[q]] 0 <= q < old.len() implies bd1(old[q], hi - i) by {
        lemma_bd_get(old, hi - i - 1, q);
    };
}

proof fn lemma_merge_ok(
    t: &Cols_lineitem,
    old_t: Seq<(i128, i128, i128, u64)>,
    r: Seq<(i128, i128, i128, u64)>,
    tot: Seq<(i128, i128, i128, u64)>,
    lo: int,
    hi: int,
)
    requires
        0 <= lo <= hi,
        grid_eq(t, old_t, 0, lo),
        grid_bd(old_t, lo),
        grid_eq(t, r, lo, hi),
        grid_bd(r, hi - lo),
        old_t.len() == mg(t),
        r.len() == mg(t),
        tot.len() == mg(t),
        forall|q: int| #![trigger tot[q]] 0 <= q < tot.len() ==>
            tot[q].0 as int == old_t[q].0 as int + r[q].0 as int
            && tot[q].1 as int == old_t[q].1 as int + r[q].1 as int
            && tot[q].2 as int == old_t[q].2 as int + r[q].2 as int
            && tot[q].3 as int == old_t[q].3 as int + r[q].3 as int,
    ensures grid_eq(t, tot, 0, hi), grid_bd(tot, hi),
{
    reveal(grid_eq);
    reveal(grid_bd);
    assert forall|c1: int, c2: int| #![trigger dk(t, c1, c2)]
        0 <= c1 < m1_of(t) && 0 <= c2 < m2_of(t) implies eqs(t, 0, hi, dk(t, c1, c2), tot[sl(m2_of(t), c1, c2)]) by {
        lemma_sl_range(m1_of(t), m2_of(t), c1, c2);
        lemma_grid_get(t, old_t, 0, lo, c1, c2);
        lemma_grid_get(t, r, lo, hi, c1, c2);
        let s = sl(m2_of(t), c1, c2);
        assert(tot[s].0 as int == old_t[s].0 as int + r[s].0 as int);
    };
    assert forall|s: int| #![trigger tot[s]] 0 <= s < tot.len() implies bd1(tot[s], hi) by {
        lemma_bd_get(old_t, lo, s);
        lemma_bd_get(r, hi - lo, s);
    };
}

proof fn lemma_total(t: &Cols_lineitem, v: Seq<(i128, i128, i128, u64)>)
    requires grid_eq(t, v, 0, t.n as int),
    ensures grid0(t, v),
{
    reveal(grid0);
    assert forall|c1: int, c2: int| #![trigger dk(t, c1, c2)]
        0 <= c1 < m1_of(t) && 0 <= c2 < m2_of(t) implies sums0(t, dk(t, c1, c2), v[sl(m2_of(t), c1, c2)]) by {
        lemma_grid_get(t, v, 0, t.n as int, c1, c2);
        lemma_fold_end(t, dk(t, c1, c2));
    };
}

spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

spec fn part_ok(t: &Cols_lineitem, lo: int, hi: int, r: Vec<(i128, i128, i128, u64)>) -> bool {
    &&& r@.len() == mg(t)
    &&& grid_eq(t, r@, lo, hi)
    &&& grid_bd(r@, hi - lo)
}

spec fn handle_ok(t: &Cols_lineitem, h: vstd::thread::JoinHandle<Vec<(i128, i128, i128, u64)>>, lo: int, hi: int) -> bool {
    forall|r: Vec<(i128, i128, i128, u64)>| #[trigger] h.predicate(r) ==> part_ok(t, lo, hi, r)
}

proof fn lemma_end(t: &Cols_lineitem, n: int, cs: int)
    requires
        n == t.n as int,
        cs == n / 8 + 1,
    ensures
        lo_of(n, cs, 8) == n,
        lo_of(n, cs, 0) == 0,
{
    assert(8 * cs >= n);
}

proof fn lemma_lo_range(n: int, cs: int, c: int)
    requires
        0 <= c,
        cs >= 0,
        n >= 0,
    ensures
        lo_of(n, cs, c) <= lo_of(n, cs, c + 1) <= n,
        0 <= lo_of(n, cs, c),
{
    assert(c * cs <= (c + 1) * cs) by (nonlinear_arith)
        requires c >= 0, cs >= 0;
    assert(c * cs >= 0) by (nonlinear_arith)
        requires c >= 0, cs >= 0;
}

// ---------------- emit: sorted insertion of the nonzero slots ----------------

spec fn pair_le(a: (Seq<char>, Seq<char>), b: (Seq<char>, Seq<char>)) -> bool {
    if a.0 == b.0 { seq_le(a.1, b.1) } else { seq_le(a.0, b.0) }
}

proof fn lemma_seq_le_total(a: Seq<char>, b: Seq<char>)
    ensures seq_le(a, b) || seq_le(b, a),
    decreases a.len(),
{
    if a.len() > 0 && b.len() > 0 && a[0] == b[0] {
        lemma_seq_le_total(a.skip(1), b.skip(1));
    }
}

proof fn lemma_pair_total(a: (Seq<char>, Seq<char>), b: (Seq<char>, Seq<char>))
    ensures pair_le(a, b) || pair_le(b, a),
{
    lemma_seq_le_total(a.0, b.0);
    lemma_seq_le_total(a.1, b.1);
}

proof fn lemma_le_stop(a: Seq<char>, b: Seq<char>, t: int)
    requires
        0 <= t <= a.len(),
        t <= b.len(),
        forall|u: int| 0 <= u < t ==> a[u] == b[u],
        t == a.len() || t == b.len() || a[t] != b[t],
    ensures seq_le(a, b) == (t == a.len() || (t < b.len() && a[t] < b[t])),
    decreases t,
{
    if t > 0 {
        assert(a[0] == b[0]);
        assert forall|u: int| 0 <= u < t - 1 implies a.skip(1)[u] == b.skip(1)[u] by {
            assert(a.skip(1)[u] == a[u + 1]);
            assert(b.skip(1)[u] == b[u + 1]);
        };
        if t < a.len() {
            assert(a.skip(1)[t - 1] == a[t]);
        }
        if t < b.len() {
            assert(b.skip(1)[t - 1] == b[t]);
        }
        lemma_le_stop(a.skip(1), b.skip(1), t - 1);
    }
}

spec fn kk(gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, r: int) -> (Seq<char>, Seq<char>) { (gf[r], gs[r]) }

#[verifier::opaque]
spec fn strs_ok(gf: Seq<String>, gfv: Seq<Seq<char>>) -> bool {
    &&& gf.len() == gfv.len()
    &&& forall|r: int| #![trigger gf[r]] 0 <= r < gf.len() ==> gf[r]@ == gfv[r]
}

proof fn lemma_strs_get(gf: Seq<String>, gfv: Seq<Seq<char>>, j: int)
    requires strs_ok(gf, gfv), 0 <= j < gf.len(),
    ensures gf[j]@ == gfv[j],
{
    reveal(strs_ok);
}

proof fn lemma_strs_insert(gf: Seq<String>, gfv: Seq<Seq<char>>, p: int, e: String)
    requires strs_ok(gf, gfv), 0 <= p <= gf.len(),
    ensures
        strs_ok(gf.insert(p, e), gfv.insert(p, e@)),
        gf.insert(p, e).len() == gf.len() + 1,
        gfv.insert(p, e@).len() == gfv.len() + 1,
{
    reveal(strs_ok);
    gf.insert_ensures(p, e);
    gfv.insert_ensures(p, e@);
    let g2 = gf.insert(p, e);
    let v2 = gfv.insert(p, e@);
    assert forall|r: int| #![trigger g2[r]] 0 <= r < g2.len() implies g2[r]@ == v2[r] by {
        if r < p {
        } else if r == p {
        } else {
            assert(g2[r] == gf[r - 1]);
            assert(v2[r] == gfv[r - 1]);
        }
    };
}

#[verifier::opaque]
spec fn inv_keys(gf: Seq<Seq<char>>, gs: Seq<Seq<char>>) -> bool {
    &&& gf.len() == gs.len()
    &&& forall|a: int, b: int| #![trigger kk(gf, gs, a), kk(gf, gs, b)]
        0 <= a < b < gf.len() ==> kk(gf, gs, a) != kk(gf, gs, b)
    &&& forall|r: int| #![trigger kk(gf, gs, r)]
        0 <= r && r + 1 < gf.len() ==> pair_le(kk(gf, gs, r), kk(gf, gs, r + 1))
}

#[verifier::opaque]
spec fn inv_acc_e(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, ac: Seq<(i128, i128, i128, u64)>) -> bool {
    &&& ac.len() == gf.len()
    &&& gs.len() == gf.len()
    &&& forall|r: int| #![trigger kk(gf, gs, r)]
        0 <= r < gf.len() ==> sums0(l, kk(gf, gs, r), ac[r]) && wit(l, 0, kk(gf, gs, r))
}

spec fn pr(c1: int, c2: int, a: int, b: int) -> bool {
    a < c1 || (a == c1 && b < c2)
}

#[verifier::opaque]
spec fn inv_cva(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int) -> bool {
    forall|a: int, b: int| #![trigger dk(l, a, b)]
        0 <= a < m1_of(l) && 0 <= b < m2_of(l) && pr(c1, c2, a, b) && wit(l, 0, dk(l, a, b)) ==>
            exists|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() && kk(gf, gs, r) == dk(l, a, b)
}

spec fn src_of(l: &Cols_lineitem, k: (Seq<char>, Seq<char>), c1: int, c2: int) -> bool {
    exists|a: int, b: int| #![trigger dk(l, a, b)]
        0 <= a < m1_of(l) && 0 <= b < m2_of(l) && pr(c1, c2, a, b) && k == dk(l, a, b)
}

#[verifier::opaque]
spec fn inv_cvb(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int) -> bool {
    forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() ==> src_of(l, kk(gf, gs, r), c1, c2)
}

proof fn lemma_src_skip(l: &Cols_lineitem, k: (Seq<char>, Seq<char>), c1: int, c2: int)
    requires src_of(l, k, c1, c2),
    ensures src_of(l, k, c1, c2 + 1),
{
    let ab = choose|a: int, b: int| 0 <= a < m1_of(l) && 0 <= b < m2_of(l) && pr(c1, c2, a, b) && k == dk(l, a, b);
    assert(0 <= ab.0 < m1_of(l) && 0 <= ab.1 < m2_of(l) && pr(c1, c2 + 1, ab.0, ab.1) && k == dk(l, ab.0, ab.1));
}

proof fn lemma_src_next(l: &Cols_lineitem, k: (Seq<char>, Seq<char>), c1: int, m2: int)
    requires m2 == m2_of(l), src_of(l, k, c1, m2),
    ensures src_of(l, k, c1 + 1, 0),
{
    let ab = choose|a: int, b: int| 0 <= a < m1_of(l) && 0 <= b < m2_of(l) && pr(c1, m2, a, b) && k == dk(l, a, b);
    assert(0 <= ab.0 < m1_of(l) && 0 <= ab.1 < m2_of(l) && pr(c1 + 1, 0, ab.0, ab.1) && k == dk(l, ab.0, ab.1));
}

spec fn inv_cv(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int) -> bool {
    inv_cva(l, gf, gs, c1, c2) && inv_cvb(l, gf, gs, c1, c2)
}

proof fn lemma_emit_empty(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, ac: Seq<(i128, i128, i128, u64)>)
    requires gf.len() == 0, gs.len() == 0, ac.len() == 0,
    ensures inv_keys(gf, gs), inv_acc_e(l, gf, gs, ac), inv_cv(l, gf, gs, 0, 0),
{
    reveal(inv_keys);
    reveal(inv_acc_e);
    reveal(inv_cva);
    reveal(inv_cvb);
}

proof fn lemma_acc_e_get(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, ac: Seq<(i128, i128, i128, u64)>, j: int)
    requires inv_acc_e(l, gf, gs, ac), 0 <= j < gf.len(),
    ensures sums0(l, kk(gf, gs, j), ac[j]), wit(l, 0, kk(gf, gs, j)),
{
    reveal(inv_acc_e);
}

proof fn lemma_emit_new(
    l: &Cols_lineitem,
    gf: Seq<Seq<char>>,
    gs: Seq<Seq<char>>,
    ac: Seq<(i128, i128, i128, u64)>,
    p: int,
    f: Seq<char>,
    s: Seq<char>,
    b: (i128, i128, i128, u64),
)
    requires
        inv_keys(gf, gs),
        inv_acc_e(l, gf, gs, ac),
        forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() ==> kk(gf, gs, r) != (f, s),
        0 <= p <= gf.len(),
        p == 0 || pair_le(kk(gf, gs, p - 1), (f, s)),
        p == gf.len() || !pair_le(kk(gf, gs, p), (f, s)),
        sums0(l, (f, s), b),
        wit(l, 0, (f, s)),
    ensures
        inv_keys(gf.insert(p, f), gs.insert(p, s)),
        inv_acc_e(l, gf.insert(p, f), gs.insert(p, s), ac.insert(p, b)),
        gf.insert(p, f).len() == gf.len() + 1,
        gs.insert(p, s).len() == gs.len() + 1,
        ac.insert(p, b).len() == ac.len() + 1,
{
    reveal(inv_keys);
    reveal(inv_acc_e);
    let key = (f, s);
    let gf2 = gf.insert(p, f);
    let gs2 = gs.insert(p, s);
    let ac2 = ac.insert(p, b);
    gf.insert_ensures(p, f);
    gs.insert_ensures(p, s);
    ac.insert_ensures(p, b);
    let n0 = gf.len() as int;
    assert(gf2.len() == n0 + 1);
    assert(gs2.len() == n0 + 1);
    assert(ac2.len() == n0 + 1);
    assert forall|r: int| 0 <= r < n0 + 1 implies kk(gf2, gs2, r) == (if r < p { kk(gf, gs, r) } else if r == p { key } else { kk(gf, gs, r - 1) }) by {
        if r < p {
        } else if r == p {
        } else {
            assert(gf2[r] == gf[r - 1]);
            assert(gs2[r] == gs[r - 1]);
        }
    };
    assert forall|a: int, b2: int| #![trigger kk(gf2, gs2, a), kk(gf2, gs2, b2)] 0 <= a < b2 < n0 + 1 implies kk(gf2, gs2, a) != kk(gf2, gs2, b2) by {
        if a < p && b2 < p {
            assert(kk(gf, gs, a) != kk(gf, gs, b2));
        } else if a < p && b2 == p {
            assert(kk(gf, gs, a) != key);
        } else if a < p && b2 > p {
            assert(kk(gf, gs, a) != kk(gf, gs, b2 - 1));
        } else if a == p {
            assert(kk(gf, gs, b2 - 1) != key);
        } else {
            assert(kk(gf, gs, a - 1) != kk(gf, gs, b2 - 1));
        }
    };
    assert forall|r: int| #![trigger kk(gf2, gs2, r)] 0 <= r && r + 1 < n0 + 1 implies pair_le(kk(gf2, gs2, r), kk(gf2, gs2, r + 1)) by {
        if r + 1 < p {
            assert(pair_le(kk(gf, gs, r), kk(gf, gs, r + 1)));
        } else if r + 1 == p {
            assert(pair_le(kk(gf, gs, p - 1), key));
        } else if r == p {
            lemma_pair_total(kk(gf, gs, p), key);
            assert(pair_le(key, kk(gf, gs, p)));
        } else {
            assert(pair_le(kk(gf, gs, r - 1), kk(gf, gs, r)));
        }
    };
    assert forall|r: int| #![trigger kk(gf2, gs2, r)] 0 <= r < n0 + 1 implies sums0(l, kk(gf2, gs2, r), ac2[r]) && wit(l, 0, kk(gf2, gs2, r)) by {
        if r < p {
            assert(ac2[r] == ac[r]);
        } else if r == p {
            assert(ac2[r] == b);
        } else {
            assert(ac2[r] == ac[r - 1]);
        }
    };
}

proof fn lemma_cva_insert(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int, p: int, f: Seq<char>, s: Seq<char>)
    requires
        inv_cva(l, gf, gs, c1, c2),
        gs.len() == gf.len(),
        0 <= c1 < m1_of(l),
        0 <= c2 < m2_of(l),
        0 <= p <= gf.len(),
        (f, s) == dk(l, c1, c2),
    ensures inv_cva(l, gf.insert(p, f), gs.insert(p, s), c1, c2 + 1),
{
    reveal(inv_cva);
    gf.insert_ensures(p, f);
    gs.insert_ensures(p, s);
    let gf2 = gf.insert(p, f);
    let gs2 = gs.insert(p, s);
    assert forall|r: int| 0 <= r < gf.len() + 1 implies kk(gf2, gs2, r) == (if r < p { kk(gf, gs, r) } else if r == p { (f, s) } else { kk(gf, gs, r - 1) }) by {
        if r < p {
        } else if r == p {
        } else {
            assert(gf2[r] == gf[r - 1]);
            assert(gs2[r] == gs[r - 1]);
        }
    };
    assert forall|a: int, b: int| #![trigger dk(l, a, b)]
        0 <= a < m1_of(l) && 0 <= b < m2_of(l) && pr(c1, c2 + 1, a, b) && wit(l, 0, dk(l, a, b)) implies
            exists|r: int| #![trigger kk(gf2, gs2, r)] 0 <= r < gf2.len() && kk(gf2, gs2, r) == dk(l, a, b) by {
        if a == c1 && b == c2 {
            assert(kk(gf2, gs2, p) == dk(l, a, b));
        } else {
            assert(pr(c1, c2, a, b));
            let r0 = choose|r0: int| 0 <= r0 < gf.len() && kk(gf, gs, r0) == dk(l, a, b);
            if r0 < p {
                assert(kk(gf2, gs2, r0) == dk(l, a, b));
            } else {
                assert(kk(gf2, gs2, r0 + 1) == dk(l, a, b));
            }
        }
    };
}

proof fn lemma_cvb_insert(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int, p: int, f: Seq<char>, s: Seq<char>)
    requires
        inv_cvb(l, gf, gs, c1, c2),
        gs.len() == gf.len(),
        0 <= c1 < m1_of(l),
        0 <= c2 < m2_of(l),
        0 <= p <= gf.len(),
        (f, s) == dk(l, c1, c2),
    ensures inv_cvb(l, gf.insert(p, f), gs.insert(p, s), c1, c2 + 1),
{
    reveal(inv_cvb);
    gf.insert_ensures(p, f);
    gs.insert_ensures(p, s);
    let gf2 = gf.insert(p, f);
    let gs2 = gs.insert(p, s);
    assert forall|r: int| 0 <= r < gf.len() + 1 implies kk(gf2, gs2, r) == (if r < p { kk(gf, gs, r) } else if r == p { (f, s) } else { kk(gf, gs, r - 1) }) by {
        if r < p {
        } else if r == p {
        } else {
            assert(gf2[r] == gf[r - 1]);
            assert(gs2[r] == gs[r - 1]);
        }
    };
    assert forall|r: int| #![trigger kk(gf2, gs2, r)] 0 <= r < gf2.len() implies src_of(l, kk(gf2, gs2, r), c1, c2 + 1) by {
        if r == p {
            assert(0 <= c1 < m1_of(l) && 0 <= c2 < m2_of(l) && pr(c1, c2 + 1, c1, c2) && kk(gf2, gs2, r) == dk(l, c1, c2));
        } else {
            let rr = if r < p { r } else { r - 1 };
            assert(kk(gf2, gs2, r) == kk(gf, gs, rr));
            let k0 = kk(gf, gs, rr);
            assert(src_of(l, k0, c1, c2));
            lemma_src_skip(l, k0, c1, c2);
        }
    };
}

proof fn lemma_cv_insert(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int, p: int, f: Seq<char>, s: Seq<char>)
    requires
        inv_cv(l, gf, gs, c1, c2),
        inv_keys(gf, gs),
        0 <= c1 < m1_of(l),
        0 <= c2 < m2_of(l),
        0 <= p <= gf.len(),
        (f, s) == dk(l, c1, c2),
    ensures inv_cv(l, gf.insert(p, f), gs.insert(p, s), c1, c2 + 1),
{
    reveal(inv_keys);
    lemma_cva_insert(l, gf, gs, c1, c2, p, f, s);
    lemma_cvb_insert(l, gf, gs, c1, c2, p, f, s);
}

proof fn lemma_cva_skip(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int)
    requires
        inv_cva(l, gf, gs, c1, c2),
        0 <= c1 < m1_of(l),
        0 <= c2 < m2_of(l),
        !wit(l, 0, dk(l, c1, c2)),
    ensures inv_cva(l, gf, gs, c1, c2 + 1),
{
    reveal(inv_cva);
    assert forall|a: int, b: int| #![trigger dk(l, a, b)]
        0 <= a < m1_of(l) && 0 <= b < m2_of(l) && pr(c1, c2 + 1, a, b) && wit(l, 0, dk(l, a, b)) implies
            exists|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() && kk(gf, gs, r) == dk(l, a, b) by {
        if a == c1 && b == c2 {
        } else {
            assert(pr(c1, c2, a, b));
        }
    };
}

proof fn lemma_cvb_skip(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int)
    requires
        inv_cvb(l, gf, gs, c1, c2),
    ensures inv_cvb(l, gf, gs, c1, c2 + 1),
{
    reveal(inv_cvb);
    assert forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() implies src_of(l, kk(gf, gs, r), c1, c2 + 1) by {
        let k0 = kk(gf, gs, r);
        assert(src_of(l, k0, c1, c2));
        lemma_src_skip(l, k0, c1, c2);
    };
}

proof fn lemma_cv_skip(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int)
    requires
        inv_cv(l, gf, gs, c1, c2),
        0 <= c1 < m1_of(l),
        0 <= c2 < m2_of(l),
        !wit(l, 0, dk(l, c1, c2)),
    ensures inv_cv(l, gf, gs, c1, c2 + 1),
{
    lemma_cva_skip(l, gf, gs, c1, c2);
    lemma_cvb_skip(l, gf, gs, c1, c2);
}

proof fn lemma_cva_next(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, m2: int)
    requires m2 == m2_of(l), inv_cva(l, gf, gs, c1, m2),
    ensures inv_cva(l, gf, gs, c1 + 1, 0),
{
    reveal(inv_cva);
    assert forall|a: int, b: int| #![trigger dk(l, a, b)]
        0 <= a < m1_of(l) && 0 <= b < m2_of(l) && pr(c1 + 1, 0, a, b) && wit(l, 0, dk(l, a, b)) implies
            exists|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() && kk(gf, gs, r) == dk(l, a, b) by {
        assert(pr(c1, m2, a, b));
    };
}

proof fn lemma_cvb_next(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, m2: int)
    requires m2 == m2_of(l), inv_cvb(l, gf, gs, c1, m2),
    ensures inv_cvb(l, gf, gs, c1 + 1, 0),
{
    reveal(inv_cvb);
    assert forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() implies src_of(l, kk(gf, gs, r), c1 + 1, 0) by {
        let k0 = kk(gf, gs, r);
        assert(src_of(l, k0, c1, m2));
        lemma_src_next(l, k0, c1, m2);
    };
}

proof fn lemma_cv_next(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, m2: int)
    requires m2 == m2_of(l), inv_cv(l, gf, gs, c1, m2),
    ensures inv_cv(l, gf, gs, c1 + 1, 0),
{
    lemma_cva_next(l, gf, gs, c1, m2);
    lemma_cvb_next(l, gf, gs, c1, m2);
}

proof fn lemma_cv_distinct(l: &Cols_lineitem, gf: Seq<Seq<char>>, gs: Seq<Seq<char>>, c1: int, c2: int)
    requires
        valid_cols_lineitem(l),
        inv_cv(l, gf, gs, c1, c2),
        0 <= c1 < m1_of(l),
        0 <= c2 < m2_of(l),
    ensures forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() ==> kk(gf, gs, r) != dk(l, c1, c2),
{
    reveal(inv_cvb);
    assert forall|r: int| #![trigger kk(gf, gs, r)] 0 <= r < gf.len() implies kk(gf, gs, r) != dk(l, c1, c2) by {
        let k0 = kk(gf, gs, r);
        assert(src_of(l, k0, c1, c2));
        let ab = choose|a: int, b: int| 0 <= a < m1_of(l) && 0 <= b < m2_of(l) && pr(c1, c2, a, b) && k0 == dk(l, a, b);
        if k0 == dk(l, c1, c2) {
            lemma_dict_eq(l, ab.0, c1, ab.1, c2);
        }
    };
}

proof fn lemma_final(
    l: &Cols_lineitem,
    gf: Seq<Seq<char>>,
    gs: Seq<Seq<char>>,
    ac: Seq<(i128, i128, i128, u64)>,
    res: Seq<OutRow>,
)
    requires
        valid_cols_lineitem(l),
        inv_keys(gf, gs),
        inv_acc_e(l, gf, gs, ac),
        inv_cv(l, gf, gs, m1_of(l), 0),
        res.len() == gf.len(),
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==>
            res[r].l_returnflag@ == gf[r] && res[r].l_linestatus@ == gs[r]
            && res[r].sum_qty == ac[r].0 && res[r].sum_base_price == ac[r].1
            && res[r].sum_disc_price == ac[r].2 && res[r].count_order == ac[r].3,
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(l, res[r]),
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> (res[a].l_returnflag@, res[a].l_linestatus@) != (res[b].l_returnflag@, res[b].l_linestatus@),
        forall|i0: int| #![trigger row_hit(l, i0)] row_hit(l, i0) && (true) ==> exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(l, i0) == (res[r].l_returnflag@, res[r].l_linestatus@),
        forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> (if (res[i].l_returnflag@) == (res[i + 1].l_returnflag@) { seq_le(res[i].l_linestatus@, res[i + 1].l_linestatus@) } else { seq_le(res[i].l_returnflag@, res[i + 1].l_returnflag@) }),
{
    reveal(inv_keys);
    reveal(inv_acc_e);
    reveal(inv_cva);
    assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(l, res[r]) by {
        let k = kk(gf, gs, r);
        assert(sums0(l, k, ac[r]) && wit(l, 0, k));
        let w = choose|w: int| 0 <= w < l.n as int && hit_key(l, w, k);
        assert((res[r].l_returnflag@, res[r].l_linestatus@) == k);
        assert(row_hit(l, w) && key_at(l, w) == (res[r].l_returnflag@, res[r].l_linestatus@));
    };
    assert forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() implies (res[a].l_returnflag@, res[a].l_linestatus@) != (res[b].l_returnflag@, res[b].l_linestatus@) by {
        assert(kk(gf, gs, a) != kk(gf, gs, b));
    };
    assert forall|i0: int| #![trigger row_hit(l, i0)] row_hit(l, i0) && (true) implies exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(l, i0) == (res[r].l_returnflag@, res[r].l_linestatus@) by {
        let a = l.l_returnflag@[i0] as int;
        let b = l.l_linestatus@[i0] as int;
        assert(a < m1_of(l));
        assert(b < m2_of(l));
        assert(key_at(l, i0) == dk(l, a, b));
        assert(hit_key(l, i0, dk(l, a, b)));
        assert(0 <= i0 < l.n as int && hit_key(l, i0, dk(l, a, b)));
        assert(wit(l, 0, dk(l, a, b)));
        assert(pr(m1_of(l), 0, a, b));
        let r0 = choose|r0: int| 0 <= r0 < gf.len() && kk(gf, gs, r0) == dk(l, a, b);
        assert(key_at(l, i0) == (res[r0].l_returnflag@, res[r0].l_linestatus@));
    };
    assert forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() implies (if (res[i].l_returnflag@) == (res[i + 1].l_returnflag@) { seq_le(res[i].l_linestatus@, res[i + 1].l_linestatus@) } else { seq_le(res[i].l_returnflag@, res[i + 1].l_returnflag@) }) by {
        assert(pair_le(kk(gf, gs, i), kk(gf, gs, i + 1)));
    };
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    let n = lineitem.n;
    let cs: usize = n / 8 + 1;
    let mut handles: Vec<vstd::thread::JoinHandle<Vec<(i128, i128, i128, u64)>>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8,
            n == lineitem.n,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_lineitem(lineitem),
            **lineitem_arc == *lineitem,
            handles@.len() == k as int,
            forall|m: int|
                0 <= m < k as int ==> #[trigger] handle_ok(lineitem, handles@[m], lo_of(n as int, cs as int, 7 - m), lo_of(n as int, cs as int, 8 - m)),
        decreases 8 - k,
    {
        let c: usize = 7 - k;
        proof {
            assert(n <= 2147483648);
            assert(c as int * cs as int <= 7 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= n { c * cs } else { n };
        let hi: usize = if (c + 1) * cs <= n { (c + 1) * cs } else { n };
        let pa = std::sync::Arc::clone(lineitem_arc);
        proof {
            assert(lo as int == lo_of(n as int, cs as int, 7 - k as int));
            assert(hi as int == lo_of(n as int, cs as int, 8 - k as int));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
            assert(*pa == *lineitem);
        }
        let h = vstd::thread::spawn(
            move || -> (r: Vec<(i128, i128, i128, u64)>)
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_lineitem(&*pa),
                ensures
                    part_ok(&*pa, lo as int, hi as int, r),
                {

let m1w: usize = pa.l_returnflag__dict.len();
let m2w: usize = pa.l_linestatus__dict.len();
let mut v: Vec<(i128, i128, i128, u64)> = Vec::new();
let mut a1: usize = 0;
while a1 < m1w
    invariant
        a1 <= m1w,
        m1w == (&*pa).l_returnflag__dict@.len(),
        m2w == (&*pa).l_linestatus__dict@.len(),
        v@.len() == a1 as int * m2w as int,
        forall|s: int| #![trigger v@[s]] 0 <= s < v@.len() ==> v@[s] == (0i128, 0i128, 0i128, 0u64),
    decreases m1w - a1,
{
    let mut a2: usize = 0;
    while a2 < m2w
        invariant
            a2 <= m2w,
            m2w == (&*pa).l_linestatus__dict@.len(),
            v@.len() == a1 as int * m2w as int + a2 as int,
            forall|s: int| #![trigger v@[s]] 0 <= s < v@.len() ==> v@[s] == (0i128, 0i128, 0i128, 0u64),
        decreases m2w - a2,
    {
        v.push((0i128, 0i128, 0i128, 0u64));
        a2 += 1;
    }
    proof {
        assert((a1 as int + 1) * (m2w as int) == a1 as int * (m2w as int) + m2w as int) by (nonlinear_arith);
    }
    a1 += 1;
}
let mm: usize = v.len();
proof {
    assert(mm as int == m1w as int * m2w as int);
    assert(mm as int == mg((&*pa)));
}

proof {
    lemma_init_zero((&*pa), v@, hi as int);
}
let mut i: usize = hi;
while i > lo
    invariant
        lo <= i <= hi,
        hi <= (&*pa).n,
        valid_cols_lineitem((&*pa)),
        m1w == (&*pa).l_returnflag__dict@.len(),
        m2w == (&*pa).l_linestatus__dict@.len(),
        v@.len() == mm as int,
        mm as int == mg((&*pa)),
        mm as int == m1w as int * m2w as int,
        grid_eq((&*pa), v@, i as int, hi as int),
        grid_bd(v@, hi as int - i as int),
    decreases i - lo,
{
    i -= 1;
    let sd = pa.l_shipdate[i];
    proof {
        assert((&*pa).l_shipdate@.len() == (&*pa).n as int);
        assert((&*pa).l_returnflag@.len() == (&*pa).n as int);
        assert((&*pa).l_linestatus@.len() == (&*pa).n as int);
        assert((&*pa).l_quantity@.len() == (&*pa).n as int);
        assert((&*pa).l_extendedprice@.len() == (&*pa).n as int);
        assert((&*pa).l_discount@.len() == (&*pa).n as int);
        assert((&*pa).n <= ROW_CAP_lineitem);
    }
    if sd <= 10471 {
        proof {
            assert(row_hit((&*pa), i as int));
            lemma_cells((&*pa), i as int);
        }
        let qv: i64 = pa.l_quantity[i];
        let pv: i64 = pa.l_extendedprice[i];
        let dv: i64 = pa.l_discount[i];
        let c1: usize = pa.l_returnflag[i] as usize;
        let c2: usize = pa.l_linestatus[i] as usize;
        proof {
            mul_small(pv as int, dv as int);
            assert((c1 as int) < m1w as int);
            assert((c2 as int) < m2w as int);
            lemma_sl_range(m1w as int, m2w as int, c1 as int, c2 as int);
            assert(c1 as int * (m2w as int) <= usize::MAX);
        }
        let s: usize = c1 * m2w + c2;
        let e64: i64 = 100 - dv;
        let prod: i128 = (pv as i128) * (e64 as i128);
        let a = v[s];
        proof {
            lemma_bd_get(v@, hi as int - i as int - 1, s as int);
            assert(hi as int - i as int - 1 <= ROW_CAP_lineitem);
        }
        let nq: i128 = a.0 + (qv as i128);
        let nb: i128 = a.1 + (pv as i128);
        let nd: i128 = a.2 + prod;
        let nc: u64 = a.3 + 1;
        let ghost old = v@;
        v.set(s, (nq, nb, nd, nc));
        proof {
            assert(a == old[s as int]);
            assert(s as int == sl(m2w as int, c1 as int, c2 as int));
            assert(sum_sum_qty_val((&*pa), i as int) == qv as int);
            assert(sum_sum_base_price_val((&*pa), i as int) == pv as int);
            assert(sum_sum_disc_price_val((&*pa), i as int) == (pv as int) * (100 - (dv as int)));
            lemma_step_hit((&*pa), i as int, hi as int, old, v@, c1 as int, c2 as int, (nq, nb, nd, nc));
        }
    } else {
        proof {
            assert(!row_hit((&*pa), i as int));
            lemma_step_skip((&*pa), i as int, hi as int, v@);
        }
    }
}

                    proof {
                        assert(i == lo);
                    }
                    v
                },
        );
        proof {
            assert(handle_ok(lineitem, h, lo_of(n as int, cs as int, 7 - k as int), lo_of(n as int, cs as int, 8 - k as int)));
        }
        let ghost old = handles@;
        handles.push(h);
        k += 1;
        proof {
            assert forall|m: int| 0 <= m < k as int implies #[trigger] handle_ok(
                lineitem,
                handles@[m],
                lo_of(n as int, cs as int, 7 - m),
                lo_of(n as int, cs as int, 8 - m),
            ) by {
                if m < k as int - 1 {
                    assert(handles@[m] == old[m]);
                }
            }
        }
    }

let m1: usize = lineitem.l_returnflag__dict.len();
let m2: usize = lineitem.l_linestatus__dict.len();
let mut tot: Vec<(i128, i128, i128, u64)> = Vec::new();
let mut a1: usize = 0;
while a1 < m1
    invariant
        a1 <= m1,
        m1 == lineitem.l_returnflag__dict@.len(),
        m2 == lineitem.l_linestatus__dict@.len(),
        tot@.len() == a1 as int * m2 as int,
        forall|s: int| #![trigger tot@[s]] 0 <= s < tot@.len() ==> tot@[s] == (0i128, 0i128, 0i128, 0u64),
    decreases m1 - a1,
{
    let mut a2: usize = 0;
    while a2 < m2
        invariant
            a2 <= m2,
            m2 == lineitem.l_linestatus__dict@.len(),
            tot@.len() == a1 as int * m2 as int + a2 as int,
            forall|s: int| #![trigger tot@[s]] 0 <= s < tot@.len() ==> tot@[s] == (0i128, 0i128, 0i128, 0u64),
        decreases m2 - a2,
    {
        tot.push((0i128, 0i128, 0i128, 0u64));
        a2 += 1;
    }
    proof {
        assert((a1 as int + 1) * (m2 as int) == a1 as int * (m2 as int) + m2 as int) by (nonlinear_arith);
    }
    a1 += 1;
}
let mmt: usize = tot.len();
proof {
    assert(mmt as int == m1 as int * m2 as int);
    assert(mmt as int == mg(lineitem));
}

    let mut j: usize = 0;
    let mut rest: Vec<vstd::thread::JoinHandle<Vec<(i128, i128, i128, u64)>>> = handles;
    proof {
        lemma_end(lineitem, n as int, cs as int);
        lemma_init_zero(lineitem, tot@, 0);
        assert(n <= ROW_CAP_lineitem);
    }
    while rest.len() > 0
        invariant
            j <= 8,
            j + rest@.len() == 8,
            n == lineitem.n,
            n <= ROW_CAP_lineitem,
            cs == n / 8 + 1,
            cs <= 268435457,
            valid_cols_lineitem(lineitem),
            m1 == lineitem.l_returnflag__dict@.len(),
            m2 == lineitem.l_linestatus__dict@.len(),
            tot@.len() == mmt as int,
            mmt as int == mg(lineitem),
            forall|mm: int|
                0 <= mm < rest@.len() ==> #[trigger] handle_ok(
                    lineitem,
                    rest@[mm],
                    lo_of(n as int, cs as int, 7 - mm),
                    lo_of(n as int, cs as int, 8 - mm),
                ),
            grid_eq(lineitem, tot@, 0, lo_of(n as int, cs as int, j as int)),
            grid_bd(tot@, lo_of(n as int, cs as int, j as int)),
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        proof {
            let mm = rest@.len() as int;
            assert(handle_ok(lineitem, old_rest[mm], lo_of(n as int, cs as int, 7 - mm), lo_of(n as int, cs as int, 8 - mm)));
            assert(h == old_rest[mm]);
            assert(7 - mm == j as int);
            assert(handle_ok(lineitem, h, lo_of(n as int, cs as int, j as int), lo_of(n as int, cs as int, j as int + 1)));
        }
        let c: usize = j;
        proof {
            assert(n <= 2147483648);
            assert(c as int * cs as int <= 7 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 268435457) by (nonlinear_arith)
                requires c <= 7, cs <= 268435457, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= n { c * cs } else { n };
        let hi: usize = if (c + 1) * cs <= n { (c + 1) * cs } else { n };
        proof {
            assert(lo as int == lo_of(n as int, cs as int, j as int));
            assert(hi as int == lo_of(n as int, cs as int, j as int + 1));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
        }
        let r: Vec<(i128, i128, i128, u64)>;
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(part_ok(lineitem, lo as int, hi as int, r));
                }
            },
            Err(_) => {
                r = {

let m1w: usize = lineitem.l_returnflag__dict.len();
let m2w: usize = lineitem.l_linestatus__dict.len();
let mut v: Vec<(i128, i128, i128, u64)> = Vec::new();
let mut a1: usize = 0;
while a1 < m1w
    invariant
        a1 <= m1w,
        m1w == lineitem.l_returnflag__dict@.len(),
        m2w == lineitem.l_linestatus__dict@.len(),
        v@.len() == a1 as int * m2w as int,
        forall|s: int| #![trigger v@[s]] 0 <= s < v@.len() ==> v@[s] == (0i128, 0i128, 0i128, 0u64),
    decreases m1w - a1,
{
    let mut a2: usize = 0;
    while a2 < m2w
        invariant
            a2 <= m2w,
            m2w == lineitem.l_linestatus__dict@.len(),
            v@.len() == a1 as int * m2w as int + a2 as int,
            forall|s: int| #![trigger v@[s]] 0 <= s < v@.len() ==> v@[s] == (0i128, 0i128, 0i128, 0u64),
        decreases m2w - a2,
    {
        v.push((0i128, 0i128, 0i128, 0u64));
        a2 += 1;
    }
    proof {
        assert((a1 as int + 1) * (m2w as int) == a1 as int * (m2w as int) + m2w as int) by (nonlinear_arith);
    }
    a1 += 1;
}
let mm: usize = v.len();
proof {
    assert(mm as int == m1w as int * m2w as int);
    assert(mm as int == mg(lineitem));
}

proof {
    lemma_init_zero(lineitem, v@, hi as int);
}
let mut i: usize = hi;
while i > lo
    invariant
        lo <= i <= hi,
        hi <= lineitem.n,
        valid_cols_lineitem(lineitem),
        m1w == lineitem.l_returnflag__dict@.len(),
        m2w == lineitem.l_linestatus__dict@.len(),
        v@.len() == mm as int,
        mm as int == mg(lineitem),
        mm as int == m1w as int * m2w as int,
        grid_eq(lineitem, v@, i as int, hi as int),
        grid_bd(v@, hi as int - i as int),
    decreases i - lo,
{
    i -= 1;
    let sd = lineitem.l_shipdate[i];
    proof {
        assert(lineitem.l_shipdate@.len() == lineitem.n as int);
        assert(lineitem.l_returnflag@.len() == lineitem.n as int);
        assert(lineitem.l_linestatus@.len() == lineitem.n as int);
        assert(lineitem.l_quantity@.len() == lineitem.n as int);
        assert(lineitem.l_extendedprice@.len() == lineitem.n as int);
        assert(lineitem.l_discount@.len() == lineitem.n as int);
        assert(lineitem.n <= ROW_CAP_lineitem);
    }
    if sd <= 10471 {
        proof {
            assert(row_hit(lineitem, i as int));
            lemma_cells(lineitem, i as int);
        }
        let qv: i64 = lineitem.l_quantity[i];
        let pv: i64 = lineitem.l_extendedprice[i];
        let dv: i64 = lineitem.l_discount[i];
        let c1: usize = lineitem.l_returnflag[i] as usize;
        let c2: usize = lineitem.l_linestatus[i] as usize;
        proof {
            mul_small(pv as int, dv as int);
            assert((c1 as int) < m1w as int);
            assert((c2 as int) < m2w as int);
            lemma_sl_range(m1w as int, m2w as int, c1 as int, c2 as int);
            assert(c1 as int * (m2w as int) <= usize::MAX);
        }
        let s: usize = c1 * m2w + c2;
        let e64: i64 = 100 - dv;
        let prod: i128 = (pv as i128) * (e64 as i128);
        let a = v[s];
        proof {
            lemma_bd_get(v@, hi as int - i as int - 1, s as int);
            assert(hi as int - i as int - 1 <= ROW_CAP_lineitem);
        }
        let nq: i128 = a.0 + (qv as i128);
        let nb: i128 = a.1 + (pv as i128);
        let nd: i128 = a.2 + prod;
        let nc: u64 = a.3 + 1;
        let ghost old = v@;
        v.set(s, (nq, nb, nd, nc));
        proof {
            assert(a == old[s as int]);
            assert(s as int == sl(m2w as int, c1 as int, c2 as int));
            assert(sum_sum_qty_val(lineitem, i as int) == qv as int);
            assert(sum_sum_base_price_val(lineitem, i as int) == pv as int);
            assert(sum_sum_disc_price_val(lineitem, i as int) == (pv as int) * (100 - (dv as int)));
            lemma_step_hit(lineitem, i as int, hi as int, old, v@, c1 as int, c2 as int, (nq, nb, nd, nc));
        }
    } else {
        proof {
            assert(!row_hit(lineitem, i as int));
            lemma_step_skip(lineitem, i as int, hi as int, v@);
        }
    }
}

                    proof {
                        assert(i == lo);
                    }
                    v
                };
                proof {
                    assert(part_ok(lineitem, lo as int, hi as int, r));
                }
            },
        }
        let ghost old_t = tot@;
        let mut z: usize = 0;
        while z < mmt
            invariant
                z <= mmt,
                tot@.len() == mmt as int,
                r@.len() == mmt as int,
                old_t.len() == mmt as int,
                lo <= hi <= n,
                n <= ROW_CAP_lineitem,
                grid_bd(old_t, lo as int),
                grid_bd(r@, hi as int - lo as int),
                forall|q: int| #![trigger tot@[q]] 0 <= q < z as int ==>
                    tot@[q].0 as int == old_t[q].0 as int + r@[q].0 as int
                    && tot@[q].1 as int == old_t[q].1 as int + r@[q].1 as int
                    && tot@[q].2 as int == old_t[q].2 as int + r@[q].2 as int
                    && tot@[q].3 as int == old_t[q].3 as int + r@[q].3 as int,
                forall|q: int| #![trigger tot@[q]] z as int <= q < mmt as int ==> tot@[q] == old_t[q],
            decreases mmt - z,
        {
            proof {
                lemma_bd_get(old_t, lo as int, z as int);
                lemma_bd_get(r@, hi as int - lo as int, z as int);
            }
            let a = tot[z];
            let b = r[z];
            tot.set(z, (a.0 + b.0, a.1 + b.1, a.2 + b.2, a.3 + b.3));
            z += 1;
        }
        proof {
            lemma_merge_ok(lineitem, old_t, r@, tot@, lo as int, hi as int);
        }
        j += 1;
    }
    proof {
        lemma_end(lineitem, n as int, cs as int);
        lemma_total(lineitem, tot@);
    }
    let mut gf: Vec<String> = Vec::new();
    let mut gs: Vec<String> = Vec::new();
    let mut ac: Vec<(i128, i128, i128, u64)> = Vec::new();
    let ghost mut gfv: Seq<Seq<char>> = Seq::empty();
    let ghost mut gsv: Seq<Seq<char>> = Seq::empty();
    proof {
        lemma_emit_empty(lineitem, gfv, gsv, ac@);
        reveal(strs_ok);
        assert(strs_ok(gf@, gfv));
        assert(strs_ok(gs@, gsv));
    }
    let mut c1: usize = 0;
    while c1 < m1
        invariant
            c1 <= m1,
            valid_cols_lineitem(lineitem),
            m1 == lineitem.l_returnflag__dict@.len(),
            m2 == lineitem.l_linestatus__dict@.len(),
            tot@.len() == mmt as int,
            mmt as int == mg(lineitem),
            grid0(lineitem, tot@),
            gf@.len() == gfv.len(),
            gs@.len() == gsv.len(),
            ac@.len() == gfv.len(),
            gsv.len() == gfv.len(),
            strs_ok(gf@, gfv),
            strs_ok(gs@, gsv),
            inv_keys(gfv, gsv),
            inv_acc_e(lineitem, gfv, gsv, ac@),
            inv_cv(lineitem, gfv, gsv, c1 as int, 0),
        decreases m1 - c1,
    {
        let mut c2: usize = 0;
        while c2 < m2
            invariant
                c1 < m1,
                c2 <= m2,
                valid_cols_lineitem(lineitem),
                m1 == lineitem.l_returnflag__dict@.len(),
                m2 == lineitem.l_linestatus__dict@.len(),
                tot@.len() == mmt as int,
                mmt as int == mg(lineitem),
                grid0(lineitem, tot@),
                gf@.len() == gfv.len(),
                gs@.len() == gsv.len(),
                ac@.len() == gfv.len(),
                gsv.len() == gfv.len(),
                strs_ok(gf@, gfv),
                strs_ok(gs@, gsv),
                inv_keys(gfv, gsv),
                inv_acc_e(lineitem, gfv, gsv, ac@),
                inv_cv(lineitem, gfv, gsv, c1 as int, c2 as int),
            decreases m2 - c2,
        {
            proof {
                lemma_sl_range(m1 as int, m2 as int, c1 as int, c2 as int);
                assert(c1 as int * (m2 as int) <= usize::MAX);
            }
            let s: usize = c1 * m2 + c2;
            let a = tot[s];
            proof {
                lemma_grid0_get(lineitem, tot@, c1 as int, c2 as int);
                assert(s as int == sl(m2 as int, c1 as int, c2 as int));
                assert(a == tot@[s as int]);
                lemma_count_wit(lineitem, 0, dk(lineitem, c1 as int, c2 as int));
            }
            if a.3 > 0 {
                let kf: String = lineitem.l_returnflag__dict[c1].clone();
                let ks: String = lineitem.l_linestatus__dict[c2].clone();
                proof {
                    assert(kf@ == lineitem.l_returnflag__dict@[c1 as int]@);
                    assert(ks@ == lineitem.l_linestatus__dict@[c2 as int]@);
                    assert((kf@, ks@) == dk(lineitem, c1 as int, c2 as int));
                    assert(wit(lineitem, 0, (kf@, ks@)));
                    lemma_cv_distinct(lineitem, gfv, gsv, c1 as int, c2 as int);
                }
                let mut p: usize = 0;
                let mut go: bool = true;
                while go
                    invariant
                        p <= gf@.len(),
                        gf@.len() == gfv.len(),
                        gs@.len() == gsv.len(),
                        gsv.len() == gfv.len(),
                        strs_ok(gf@, gfv),
                        strs_ok(gs@, gsv),
                        forall|q: int| #![trigger kk(gfv, gsv, q)] 0 <= q < p as int ==> pair_le(kk(gfv, gsv, q), (kf@, ks@)),
                        go || p == gf@.len() || !pair_le(kk(gfv, gsv, p as int), (kf@, ks@)),
                    decreases gf@.len() - p + (if go { 1int } else { 0int }),
                {
                    if p >= gf.len() {
                        go = false;
                    } else {
                        let ple: bool;
                        proof {
                            lemma_strs_get(gf@, gfv, p as int);
                            lemma_strs_get(gs@, gsv, p as int);
                        }
                        if gf[p] == kf {
                            let la = gs[p].as_str().unicode_len();
                            let lb = ks.as_str().unicode_len();
                            let mut t: usize = 0;
                            while t < la && t < lb && gs[p].as_str().get_char(t) == ks.as_str().get_char(t)
                                invariant
                                    t <= la,
                                    t <= lb,
                                    p < gs@.len(),
                                    la as int == gs@[p as int]@.len(),
                                    lb as int == ks@.len(),
                                    forall|u: int| 0 <= u < t as int ==> gs@[p as int]@[u] == ks@[u],
                                decreases la - t,
                            {
                                t += 1;
                            }
                            proof {
                                lemma_le_stop(gs@[p as int]@, ks@, t as int);
                            }
                            ple = t == la || (t < lb && gs[p].as_str().get_char(t) < ks.as_str().get_char(t));
                        } else {
                            let la = gf[p].as_str().unicode_len();
                            let lb = kf.as_str().unicode_len();
                            let mut t: usize = 0;
                            while t < la && t < lb && gf[p].as_str().get_char(t) == kf.as_str().get_char(t)
                                invariant
                                    t <= la,
                                    t <= lb,
                                    p < gf@.len(),
                                    la as int == gf@[p as int]@.len(),
                                    lb as int == kf@.len(),
                                    forall|u: int| 0 <= u < t as int ==> gf@[p as int]@[u] == kf@[u],
                                decreases la - t,
                            {
                                t += 1;
                            }
                            proof {
                                lemma_le_stop(gf@[p as int]@, kf@, t as int);
                            }
                            ple = t == la || (t < lb && gf[p].as_str().get_char(t) < kf.as_str().get_char(t));
                        }
                        proof {
                            assert(ple == pair_le(kk(gfv, gsv, p as int), (kf@, ks@)));
                        }
                        if ple {
                            p += 1;
                        } else {
                            go = false;
                        }
                    }
                }
                proof {
                    assert(sums0(lineitem, (kf@, ks@), a));
                    lemma_emit_new(lineitem, gfv, gsv, ac@, p as int, kf@, ks@, a);
                    lemma_cv_insert(lineitem, gfv, gsv, c1 as int, c2 as int, p as int, kf@, ks@);
                    lemma_strs_insert(gf@, gfv, p as int, kf);
                    lemma_strs_insert(gs@, gsv, p as int, ks);
                    let ghost old_gfv = gfv;
                    let ghost old_gsv = gsv;
                    gfv = old_gfv.insert(p as int, kf@);
                    gsv = old_gsv.insert(p as int, ks@);
                }
                gf.insert(p, kf);
                gs.insert(p, ks);
                ac.insert(p, a);
            } else {
                proof {
                    assert(!wit(lineitem, 0, dk(lineitem, c1 as int, c2 as int)));
                    lemma_cv_skip(lineitem, gfv, gsv, c1 as int, c2 as int);
                }
            }
            c2 += 1;
        }
        proof {
            assert(c2 == m2);
            lemma_cv_next(lineitem, gfv, gsv, c1 as int, m2 as int);
        }
        c1 += 1;
    }
    proof {
        assert(c1 == m1);
    }
    let mut res: Vec<OutRow> = Vec::new();
    let mut g: usize = 0;
    while g < gf.len()
        invariant
            g <= gf@.len(),
            inv_keys(gfv, gsv),
            inv_acc_e(lineitem, gfv, gsv, ac@),
            inv_cv(lineitem, gfv, gsv, m1 as int, 0),
            gf@.len() == gs@.len(),
            gf@.len() == gfv.len(),
            gs@.len() == gsv.len(),
            ac@.len() == gfv.len(),
            strs_ok(gf@, gfv),
            strs_ok(gs@, gsv),
            res@.len() == g as int,
            forall|r: int| #![trigger res@[r]] 0 <= r < g as int ==>
                res@[r].l_returnflag@ == gfv[r] && res@[r].l_linestatus@ == gsv[r]
                && res@[r].sum_qty == ac@[r].0 && res@[r].sum_base_price == ac@[r].1
                && res@[r].sum_disc_price == ac@[r].2 && res@[r].count_order == ac@[r].3,
        decreases gf@.len() - g,
    {
        let a = ac[g];
        let ghost old_res = res@;
        proof {
            lemma_strs_get(gf@, gfv, g as int);
            lemma_strs_get(gs@, gsv, g as int);
        }
        let row = OutRow {
            l_returnflag: gf[g].clone(),
            l_linestatus: gs[g].clone(),
            sum_qty: a.0,
            sum_base_price: a.1,
            sum_disc_price: a.2,
            count_order: a.3,
        };
        proof {
            assert(row.l_returnflag@ == gf@[g as int]@);
            assert(row.l_linestatus@ == gs@[g as int]@);
        }
        res.push(row);
        proof {
            assert(res@ == old_res.push(row));
            assert forall|r: int| #![trigger res@[r]] 0 <= r < g as int + 1 implies
                res@[r].l_returnflag@ == gfv[r] && res@[r].l_linestatus@ == gsv[r]
                && res@[r].sum_qty == ac@[r].0 && res@[r].sum_base_price == ac@[r].1
                && res@[r].sum_disc_price == ac@[r].2 && res@[r].count_order == ac@[r].3 by {
                if r < g as int {
                    assert(res@[r] == old_res[r]);
                }
            };
        }
        g += 1;
    }
    proof {
        lemma_final(lineitem, gfv, gsv, ac@, res@);
    }
    res
// AGENT_EDIT_END
