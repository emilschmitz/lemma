// Worked example (hard; PARALLEL + dict, LEMMA_PARALLEL_VSTD=1 and LEMMA_STRING_ENCODING=dict): TPC-H Q12 (orders join lineitem, dictionary l_shipmode, two conditional counts).
// Plan: 8 vstd workers scan lineitem in 32-row blocks (a branch-free flag loop skips blocks with no qualifying row), each returns its hit orderkeys;
// the hits go into one bitset per ship mode (one bit per key below 2^25) plus a spill map holding the counts beyond the first (and every count of an out-of-range key);
// 8 workers then scan orders, read the priority only for a key that has a hit, and add the counts.
// Why it replaced the u8-counter version: that version spent ~12-15 ms of its ~45 ms in a sequential merge zero-filling and touching 2 x 32 MB; the bitsets are 2 x 4 MB (merge ~0.5 ms).
// The scan was 2x slower with a short-circuit row test (branch misses); the block flag loop vectorizes (SSE2) and skips ~70% of the rows' second pass.
// TPC-H SF3 (18.0M lineitem rows, 4.5M orders), 82 verified, 0 errors at the default rlimit. Machine shared (load 1.5-2.7), medians of 9: 23.7-26.8 ms against 62-66 ms for the live all-core DuckDB
// in the same lock window (2.4-2.8x), 29-38 ms against the stored 56.0 ms bar (1.5-1.9x; best runs 2.0-2.4x). The previous body: 44-46 ms in the same window (1.4x of DuckDB's 62-66; 0.78x when measured under heavy load).
// Constants 17996609 / 4500000 / 2249577 / 562501 are the SF3 row caps: valid for any catalog with caps at most SF3's.
// AGENT_HELPERS_START
spec fn mstr(l: &Cols_lineitem, i: int) -> Seq<char> {
    l.l_shipmode__dict@[l.l_shipmode@[i] as int]@
}

spec fn dfilt(l: &Cols_lineitem, i: int) -> bool {
    (l.l_commitdate@[i] as int) < (l.l_receiptdate@[i] as int)
    && (l.l_shipdate@[i] as int) < (l.l_commitdate@[i] as int)
    && (l.l_receiptdate@[i] as int) >= 8766
    && (l.l_receiptdate@[i] as int) < 9131
}

spec fn hit_m(l: &Cols_lineitem, i: int, m: Seq<char>) -> bool {
    dfilt(l, i) && mstr(l, i) == m
}

spec fn ohi(o: &Cols_orders, i: int) -> bool {
    (o.o_orderpriority__dict@[o.o_orderpriority@[i] as int]@) == "1-URGENT"@ || (o.o_orderpriority__dict@[o.o_orderpriority@[i] as int]@) == "2-HIGH"@
}

spec fn sc(l: &Cols_lineitem, x: int, m: Seq<char>, j: int) -> int
    decreases l.n as int - j
{
    if j < 0 || j >= l.n as int {
        0int
    } else {
        (if hit_m(l, j, m) && (l.l_orderkey@[j] as int) == x { 1int } else { 0int }) + sc(l, x, m, j + 1)
    }
}

spec fn in_rng(x: i64) -> bool {
    0 <= (x as int) < 33554432
}

spec fn tel(l: &Cols_lineitem, m: Seq<char>, lo: int, hi: int) -> spec_fn(int) -> int {
    |x: int| sc(l, x, m, lo) - sc(l, x, m, hi)
}

spec fn wbit(w: u64, b: int) -> bool {
    ((w >> (b as u64)) & 1u64) == 1u64
}

spec fn bit_of(a: Seq<u64>, x: int) -> int {
    if wbit(a[x / 64], x % 64) { 1int } else { 0int }
}

proof fn lemma_bit01(w: u64, b: int)
    requires
        0 <= b < 64,
    ensures
        ((w >> (b as u64)) & 1u64) <= 1,
        wbit(w, b) <==> (((w >> (b as u64)) & 1u64) == 1u64),
        !wbit(w, b) <==> (((w >> (b as u64)) & 1u64) == 0u64),
{
    let bb = b as u64;
    assert(((w >> bb) & 1u64) <= 1) by (bit_vector)
        requires bb < 64;
}

proof fn lemma_bit_zero(b: int)
    requires
        0 <= b < 64,
    ensures
        !wbit(0u64, b),
{
    let bb = b as u64;
    assert(((0u64 >> bb) & 1u64) == 0u64) by (bit_vector)
        requires bb < 64;
}

proof fn lemma_bit_set(w: u64, b: int)
    requires
        0 <= b < 64,
    ensures
        wbit(w | (1u64 << (b as u64)), b),
        forall|c: int| 0 <= c < 64 && c != b ==> (wbit(w | (1u64 << (b as u64)), c) <==> wbit(w, c)),
{
    let bb = b as u64;
    assert((((w | (1u64 << bb)) >> bb) & 1u64) == 1u64) by (bit_vector)
        requires bb < 64;
    assert forall|c: int| 0 <= c < 64 && c != b implies (wbit(w | (1u64 << bb), c) <==> wbit(w, c)) by {
        let cc = c as u64;
        assert(((((w | (1u64 << bb)) >> cc) & 1u64) == 1u64) <==> (((w >> cc) & 1u64) == 1u64)) by (bit_vector)
            requires bb < 64, cc < 64, cc != bb;
    }
}

#[verifier::opaque]
spec fn st_ok(a: Seq<u64>, mp: Map<i64, u32>, f: spec_fn(int) -> int) -> bool {
    &&& a.len() == 524288
    &&& forall|x: i64| #![trigger mp.contains_key(x)] (if in_rng(x) { bit_of(a, x as int) } else { 0int }) + (if mp.contains_key(x) { mp[x] as int } else { 0int }) == f(x as int)
    &&& forall|x: i64| #![trigger mp.contains_key(x)] (mp.contains_key(x) && in_rng(x)) ==> bit_of(a, x as int) == 1
}

proof fn lemma_sc_bound(l: &Cols_lineitem, x: int, m: Seq<char>, j: int)
    requires
        0 <= j,
    ensures
        0 <= sc(l, x, m, j) <= (if j < l.n as int { l.n as int - j } else { 0int }),
    decreases l.n as int - j,
{
    if j < l.n as int {
        lemma_sc_bound(l, x, m, j + 1);
    }
}

proof fn lemma_sc_pos(l: &Cols_lineitem, x: int, m: Seq<char>, j: int)
    requires
        0 <= j,
    ensures
        sc(l, x, m, j) > 0 <==> exists|t: int| #![trigger hit_m(l, t, m)] j <= t < l.n as int && hit_m(l, t, m) && (l.l_orderkey@[t] as int) == x,
    decreases l.n as int - j,
{
    if j < l.n as int {
        lemma_sc_pos(l, x, m, j + 1);
        lemma_sc_bound(l, x, m, j + 1);
        if hit_m(l, j, m) && (l.l_orderkey@[j] as int) == x {
            assert(j <= j && j < l.n as int && hit_m(l, j, m) && (l.l_orderkey@[j] as int) == x);
        } else if exists|t: int| #![trigger hit_m(l, t, m)] j <= t < l.n as int && hit_m(l, t, m) && (l.l_orderkey@[t] as int) == x {
            let t = choose|t: int| #![trigger hit_m(l, t, m)] j <= t < l.n as int && hit_m(l, t, m) && (l.l_orderkey@[t] as int) == x;
            assert(t != j);
            assert(j + 1 <= t < l.n as int && hit_m(l, t, m) && (l.l_orderkey@[t] as int) == x);
        }
    }
}

proof fn lemma_d1(o: &Cols_orders, l: &Cols_lineitem, i0: int, j: int, k: Seq<char>)
    requires
        valid_cols_orders(o),
        valid_cols_lineitem(l),
        0 <= i0 < o.n as int,
        0 <= j,
        k == "MAIL"@ || k == "SHIP"@,
    ensures
        sum_high_line_count_d1(o, l, i0, j, k) == (if ohi(o, i0) { sc(l, o.o_orderkey@[i0] as int, k, j) } else { 0int }),
        sum_low_line_count_d1(o, l, i0, j, k) == (if ohi(o, i0) { 0int } else { sc(l, o.o_orderkey@[i0] as int, k, j) }),
    decreases l.n as int - j,
{
    if j < l.n as int {
        lemma_d1(o, l, i0, j + 1, k);
        reveal_with_fuel(sum_high_line_count_d1, 2);
        reveal_with_fuel(sum_low_line_count_d1, 2);
        reveal_with_fuel(sc, 2);
        let x = o.o_orderkey@[i0] as int;
        assert((row_hit(o, l, i0, j) && key_at(o, l, i0, j) == k) <==> (hit_m(l, j, k) && (l.l_orderkey@[j] as int) == x));
    }
}

proof fn lemma_tot(o: &Cols_orders, l: &Cols_lineitem, i0: int, k: Seq<char>)
    requires
        valid_cols_orders(o),
        valid_cols_lineitem(l),
        0 <= i0,
        k == "MAIL"@ || k == "SHIP"@,
    ensures
        sum_high_line_count(o, l, i0, k) >= 0,
        sum_low_line_count(o, l, i0, k) >= 0,
        (sum_high_line_count(o, l, i0, k) + sum_low_line_count(o, l, i0, k) > 0) <==> exists|a: int, b: int| #![trigger row_hit(o, l, a, b)] i0 <= a < o.n as int && 0 <= b < l.n as int && row_hit(o, l, a, b) && key_at(o, l, a, b) == k,
    decreases o.n as int - i0,
{
    if i0 < o.n as int {
        lemma_tot(o, l, i0 + 1, k);
        lemma_d1(o, l, i0, 0, k);
        let x = o.o_orderkey@[i0] as int;
        lemma_sc_bound(l, x, k, 0);
        lemma_sc_pos(l, x, k, 0);
        reveal_with_fuel(sum_high_line_count, 2);
        reveal_with_fuel(sum_low_line_count, 2);
        if sc(l, x, k, 0) > 0 {
            let t = choose|t: int| #![trigger hit_m(l, t, k)] 0 <= t < l.n as int && hit_m(l, t, k) && (l.l_orderkey@[t] as int) == x;
            assert(row_hit(o, l, i0, t) && key_at(o, l, i0, t) == k);
        } else if exists|a: int, b: int| #![trigger row_hit(o, l, a, b)] i0 <= a < o.n as int && 0 <= b < l.n as int && row_hit(o, l, a, b) && key_at(o, l, a, b) == k {
            let (a, b) = choose|a: int, b: int| #![trigger row_hit(o, l, a, b)] i0 <= a < o.n as int && 0 <= b < l.n as int && row_hit(o, l, a, b) && key_at(o, l, a, b) == k;
            if a == i0 {
                assert(0 <= b < l.n as int && hit_m(l, b, k) && (l.l_orderkey@[b] as int) == x);
            } else {
                assert(i0 + 1 <= a < o.n as int && 0 <= b < l.n as int && row_hit(o, l, a, b) && key_at(o, l, a, b) == k);
            }
        }
    }
}

proof fn lemma_code_iff(l: &Cols_lineitem, j: int, found: bool, code: int, s: Seq<char>)
    requires
        valid_cols_lineitem(l),
        0 <= j < l.n as int,
        found ==> 0 <= code < l.l_shipmode__dict@.len() && l.l_shipmode__dict@[code]@ == s,
        !found ==> forall|m: int| 0 <= m < l.l_shipmode__dict@.len() ==> l.l_shipmode__dict@[m]@ != s,
    ensures
        mstr(l, j) == s <==> (found && (l.l_shipmode@[j] as int) == code),
{
    let c = l.l_shipmode@[j] as int;
    assert(c < l.l_shipmode__dict@.len());
    if found && c != code {
        let a = if c < code { c } else { code };
        let b = if c < code { code } else { c };
        assert(l.l_shipmode__dict@[a]@ != l.l_shipmode__dict@[b]@);
    }
}

proof fn lemma_ohi(o: &Cols_orders, i0: int, hf: Seq<bool>)
    requires
        valid_cols_orders(o),
        0 <= i0 < o.n as int,
        hf.len() == o.o_orderpriority__dict@.len(),
        forall|q: int| #![trigger hf[q]] 0 <= q < hf.len() ==> (hf[q] <==> (o.o_orderpriority__dict@[q]@ == "1-URGENT"@ || o.o_orderpriority__dict@[q]@ == "2-HIGH"@)),
    ensures
        ohi(o, i0) <==> hf[o.o_orderpriority@[i0] as int],
{
    let c = o.o_orderpriority@[i0] as int;
    assert(c < o.o_orderpriority__dict@.len());
}

proof fn lemma_st_init(l: &Cols_lineitem, a: Seq<u64>, m: Seq<char>, k: int)
    requires
        a.len() == 524288,
        forall|i: int| 0 <= i < a.len() ==> a[i] == 0,
    ensures
        st_ok(a, Map::<i64, u32>::empty(), tel(l, m, k, k)),
{
    reveal(st_ok);
    assert forall|x: i64| in_rng(x) implies bit_of(a, x as int) == 0 by {
        lemma_bit_zero((x as int) % 64);
        assert(a[(x as int) / 64] == 0u64);
    }
}

proof fn lemma_st_get(a: Seq<u64>, mp: Map<i64, u32>, f: spec_fn(int) -> int, x: i64)
    requires
        st_ok(a, mp, f),
    ensures
        (if in_rng(x) { bit_of(a, x as int) } else { 0int }) + (if mp.contains_key(x) { mp[x] as int } else { 0int }) == f(x as int),
        (in_rng(x) && bit_of(a, x as int) == 0) ==> !mp.contains_key(x),
{
    reveal(st_ok);
}

proof fn lemma_st_same(a: Seq<u64>, mp: Map<i64, u32>, f: spec_fn(int) -> int, f2: spec_fn(int) -> int)
    requires
        st_ok(a, mp, f),
        forall|x: int| #![trigger f2(x)] f2(x) == f(x),
    ensures
        st_ok(a, mp, f2),
{
    reveal(st_ok);
}

proof fn lemma_st_inc(a: Seq<u64>, mp: Map<i64, u32>, a2: Seq<u64>, mp2: Map<i64, u32>, y: i64, f: spec_fn(int) -> int, f2: spec_fn(int) -> int)
    requires
        st_ok(a, mp, f),
        forall|x: int| #![trigger f2(x)] f2(x) == f(x) + (if x == y as int { 1int } else { 0int }),
        f(y as int) + 1 <= 0xffff_ffff,
        (in_rng(y) && bit_of(a, y as int) == 0) ==> (a2 == a.update((y as int) / 64, a[(y as int) / 64] | (1u64 << (((y as int) % 64) as u64))) && mp2 == mp),
        !(in_rng(y) && bit_of(a, y as int) == 0) ==> (a2 == a && mp2 == mp.insert(y, ((if mp.contains_key(y) { mp[y] as int } else { 0int }) + 1) as u32)),
    ensures
        st_ok(a2, mp2, f2),
{
    reveal(st_ok);
    assert(a2.len() == 524288);
    let yi = y as int;
    if in_rng(y) && bit_of(a, yi) == 0 {
        assert(!mp.contains_key(y));
        lemma_bit_set(a[yi / 64], yi % 64);
        assert(wbit(a2[yi / 64], yi % 64));
        assert forall|x: i64| #![trigger mp2.contains_key(x)] (if in_rng(x) { bit_of(a2, x as int) } else { 0int }) + (if mp2.contains_key(x) { mp2[x] as int } else { 0int }) == f2(x as int) by {
            if in_rng(x) && x != y {
                let xi = x as int;
                if xi / 64 == yi / 64 {
                    assert(xi % 64 != yi % 64);
                    assert(wbit(a2[xi / 64], xi % 64) <==> wbit(a[xi / 64], xi % 64));
                } else {
                    assert(a2[xi / 64] == a[xi / 64]);
                }
            }
        };
        assert forall|x: i64| #![trigger mp2.contains_key(x)] (mp2.contains_key(x) && in_rng(x)) implies bit_of(a2, x as int) == 1 by {
            let xi = x as int;
            assert(x != y);
            assert(bit_of(a, xi) == 1);
            if xi / 64 == yi / 64 {
                assert(xi % 64 != yi % 64);
                assert(wbit(a2[xi / 64], xi % 64) <==> wbit(a[xi / 64], xi % 64));
            } else {
                assert(a2[xi / 64] == a[xi / 64]);
            }
        };
    } else {
        assert(a2 == a);
        assert forall|x: i64| #![trigger mp2.contains_key(x)] (if in_rng(x) { bit_of(a2, x as int) } else { 0int }) + (if mp2.contains_key(x) { mp2[x] as int } else { 0int }) == f2(x as int) by {
            if x == y {
                assert(f(y as int) == (if in_rng(y) { bit_of(a, y as int) } else { 0int }) + (if mp.contains_key(y) { mp[y] as int } else { 0int }));
            }
        };
        assert forall|x: i64| #![trigger mp2.contains_key(x)] (mp2.contains_key(x) && in_rng(x)) implies bit_of(a2, x as int) == 1 by {
            if x == y {
                assert(in_rng(y));
                assert(bit_of(a, yi) != 0);
            }
        };
    }
}

proof fn lemma_tel_inc(l: &Cols_lineitem, m: Seq<char>, j: int)
    requires
        0 <= j < l.n as int,
    ensures
        forall|x: int| #![trigger tel(l, m, j, l.n as int)(x)] tel(l, m, j, l.n as int)(x) == tel(l, m, j + 1, l.n as int)(x) + (if hit_m(l, j, m) && (l.l_orderkey@[j] as int) == x { 1int } else { 0int }),
{
    reveal_with_fuel(sc, 2);
}

spec fn lcnt(s: Seq<i64>, x: int) -> int
    decreases s.len()
{
    if s.len() == 0 {
        0int
    } else {
        lcnt(s.drop_last(), x) + (if s.last() as int == x { 1int } else { 0int })
    }
}

proof fn lemma_lcnt_push(s: Seq<i64>, v: i64, x: int)
    ensures
        lcnt(s.push(v), x) == lcnt(s, x) + (if v as int == x { 1int } else { 0int }),
{
    reveal_with_fuel(lcnt, 2);
    assert(s.push(v).drop_last() =~= s);
}

proof fn lemma_lcnt_zero(s: Seq<i64>, x: int)
    ensures
        lcnt(s.subrange(0, 0), x) == 0,
{
    assert(s.subrange(0, 0).len() == 0);
}

proof fn lemma_lcnt_sub_step(s: Seq<i64>, p: int, x: int)
    requires
        0 <= p < s.len(),
    ensures
        lcnt(s.subrange(0, p + 1), x) == lcnt(s.subrange(0, p), x) + (if s[p] as int == x { 1int } else { 0int }),
{
    reveal_with_fuel(lcnt, 2);
    assert(s.subrange(0, p + 1).drop_last() =~= s.subrange(0, p));
}

proof fn lemma_lcnt_prefix(s: Seq<i64>, p: int, x: int)
    requires
        0 <= p <= s.len(),
    ensures
        lcnt(s.subrange(0, p), x) <= lcnt(s, x),
    decreases s.len() - p,
{
    if p < s.len() {
        lemma_lcnt_prefix(s, p + 1, x);
        lemma_lcnt_sub_step(s, p, x);
    } else {
        assert(s.subrange(0, p) =~= s);
    }
}

#[verifier::opaque]
spec fn lst_ok(l: &Cols_lineitem, v: Seq<i64>, m: Seq<char>, lo: int, hi: int) -> bool {
    forall|x: int| #![trigger lcnt(v, x)] lcnt(v, x) == sc(l, x, m, lo) - sc(l, x, m, hi)
}

proof fn lemma_lst_init(l: &Cols_lineitem, m: Seq<char>, hi: int)
    ensures
        lst_ok(l, Seq::<i64>::empty(), m, hi, hi),
{
    reveal(lst_ok);
    assert(Seq::<i64>::empty().len() == 0);
}

proof fn lemma_lst_step(l: &Cols_lineitem, old: Seq<i64>, new: Seq<i64>, m: Seq<char>, i: int, hi: int, hit: bool, y: i64)
    requires
        0 <= i < l.n as int,
        lst_ok(l, old, m, i + 1, hi),
        hit ==> y == l.l_orderkey@[i],
        hit <==> hit_m(l, i, m),
        hit ==> new == old.push(y),
        !hit ==> new == old,
    ensures
        lst_ok(l, new, m, i, hi),
{
    reveal(lst_ok);
    reveal_with_fuel(sc, 2);
    assert forall|x: int| #![trigger lcnt(new, x)] lcnt(new, x) == sc(l, x, m, i) - sc(l, x, m, hi) by {
        if hit {
            lemma_lcnt_push(old, y, x);
        }
    };
}

spec fn telp(l: &Cols_lineitem, m: Seq<char>, lo0: int, lo1: int, s: Seq<i64>, p: int) -> spec_fn(int) -> int {
    |x: int| sc(l, x, m, lo0) - sc(l, x, m, lo1) + lcnt(s.subrange(0, p), x)
}

proof fn lemma_telp_start(l: &Cols_lineitem, m: Seq<char>, lo0: int, lo1: int, s: Seq<i64>)
    ensures
        forall|x: int| #![trigger telp(l, m, lo0, lo1, s, 0)(x)] telp(l, m, lo0, lo1, s, 0)(x) == tel(l, m, lo0, lo1)(x),
{
    assert forall|x: int| #![trigger telp(l, m, lo0, lo1, s, 0)(x)] telp(l, m, lo0, lo1, s, 0)(x) == tel(l, m, lo0, lo1)(x) by {
        lemma_lcnt_zero(s, x);
    };
}

proof fn lemma_telp_end(l: &Cols_lineitem, m: Seq<char>, lo0: int, lo1: int, hi1: int, s: Seq<i64>)
    requires
        lst_ok(l, s, m, lo1, hi1),
    ensures
        forall|x: int| #![trigger telp(l, m, lo0, lo1, s, s.len() as int)(x)] telp(l, m, lo0, lo1, s, s.len() as int)(x) == tel(l, m, lo0, hi1)(x),
{
    reveal(lst_ok);
    assert(s.subrange(0, s.len() as int) =~= s);
}

proof fn lemma_telp_step(l: &Cols_lineitem, m: Seq<char>, lo0: int, lo1: int, s: Seq<i64>, p: int)
    requires
        0 <= p < s.len(),
    ensures
        forall|x: int| #![trigger telp(l, m, lo0, lo1, s, p + 1)(x)] telp(l, m, lo0, lo1, s, p + 1)(x) == telp(l, m, lo0, lo1, s, p)(x) + (if x == s[p] as int { 1int } else { 0int }),
{
    assert forall|x: int| #![trigger telp(l, m, lo0, lo1, s, p + 1)(x)] telp(l, m, lo0, lo1, s, p + 1)(x) == telp(l, m, lo0, lo1, s, p)(x) + (if x == s[p] as int { 1int } else { 0int }) by {
        lemma_lcnt_sub_step(s, p, x);
    };
}

proof fn lemma_telp_bound(l: &Cols_lineitem, m: Seq<char>, lo0: int, lo1: int, hi1: int, s: Seq<i64>, p: int, x: int)
    requires
        lst_ok(l, s, m, lo1, hi1),
        0 <= lo0,
        0 <= lo1,
        0 <= hi1,
        0 <= p <= s.len(),
    ensures
        telp(l, m, lo0, lo1, s, p)(x) <= l.n as int,
{
    reveal(lst_ok);
    lemma_lcnt_prefix(s, p, x);
    lemma_sc_bound(l, x, m, lo0);
    lemma_sc_bound(l, x, m, hi1);
}

spec fn part_ok(l: &Cols_lineitem, lo: int, hi: int, r: (Vec<i64>, Vec<i64>)) -> bool {
    lst_ok(l, r.0@, "MAIL"@, lo, hi) && lst_ok(l, r.1@, "SHIP"@, lo, hi)
}

spec fn handle_ok(l: &Cols_lineitem, h: vstd::thread::JoinHandle<(Vec<i64>, Vec<i64>)>, lo: int, hi: int) -> bool {
    forall|r: (Vec<i64>, Vec<i64>)| #[trigger] h.predicate(r) ==> part_ok(l, lo, hi, r)
}

spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

proof fn lemma_end(n: int, cs: int)
    requires
        cs == n / 8 + 1,
        n >= 0,
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

spec fn part2_ok(o: &Cols_orders, l: &Cols_lineitem, lo: int, hi: int, r: (u64, u64, u64, u64)) -> bool {
    &&& r.0 as int == sum_high_line_count(o, l, lo, "MAIL"@) - sum_high_line_count(o, l, hi, "MAIL"@)
    &&& r.1 as int == sum_low_line_count(o, l, lo, "MAIL"@) - sum_low_line_count(o, l, hi, "MAIL"@)
    &&& r.2 as int == sum_high_line_count(o, l, lo, "SHIP"@) - sum_high_line_count(o, l, hi, "SHIP"@)
    &&& r.3 as int == sum_low_line_count(o, l, lo, "SHIP"@) - sum_low_line_count(o, l, hi, "SHIP"@)
    &&& r.0 as int <= (hi - lo) * 17996609
    &&& r.1 as int <= (hi - lo) * 17996609
    &&& r.2 as int <= (hi - lo) * 17996609
    &&& r.3 as int <= (hi - lo) * 17996609
}

spec fn handle2_ok(o: &Cols_orders, l: &Cols_lineitem, h: vstd::thread::JoinHandle<(u64, u64, u64, u64)>, lo: int, hi: int) -> bool {
    forall|r: (u64, u64, u64, u64)| #[trigger] h.predicate(r) ==> part2_ok(o, l, lo, hi, r)
}

proof fn lemma_out1(o: &Cols_orders, l: &Cols_lineitem, res: Seq<OutRow>, pm: bool, ps: bool, hm: int, lm: int, hs: int, ls: int)
    requires
        hm == sum_high_line_count(o, l, 0, "MAIL"@),
        lm == sum_low_line_count(o, l, 0, "MAIL"@),
        hs == sum_high_line_count(o, l, 0, "SHIP"@),
        ls == sum_low_line_count(o, l, 0, "SHIP"@),
        pm ==> exists|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "MAIL"@,
        ps ==> exists|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "SHIP"@,
        res.len() == (if pm { 1int } else { 0int }) + (if ps { 1int } else { 0int }),
        pm ==> (res[0].l_shipmode@ == "MAIL"@ && res[0].high_line_count as int == hm && res[0].low_line_count as int == lm),
        ps ==> (res[if pm { 1int } else { 0int }].l_shipmode@ == "SHIP"@ && res[if pm { 1int } else { 0int }].high_line_count as int == hs && res[if pm { 1int } else { 0int }].low_line_count as int == ls),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(o, l, res[r]),
{
    let idx: int = if pm { 1int } else { 0int };
    assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(o, l, res[r]) by {
        if pm && r == 0 {
            let (a, b) = choose|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "MAIL"@;
            assert(row_hit(o, l, a, b) && key_at(o, l, a, b) == res[r].l_shipmode@);
        } else {
            assert(ps && r == idx);
            let (a, b) = choose|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "SHIP"@;
            assert(row_hit(o, l, a, b) && key_at(o, l, a, b) == res[r].l_shipmode@);
        }
    };
}

proof fn lemma_out3(o: &Cols_orders, l: &Cols_lineitem, res: Seq<OutRow>, pm: bool, ps: bool)
    requires
        forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) ==> (key_at(o, l, a, b) == "MAIL"@ || key_at(o, l, a, b) == "SHIP"@),
        forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "MAIL"@ ==> pm,
        forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "SHIP"@ ==> ps,
        res.len() == (if pm { 1int } else { 0int }) + (if ps { 1int } else { 0int }),
        pm ==> res[0].l_shipmode@ == "MAIL"@,
        ps ==> res[if pm { 1int } else { 0int }].l_shipmode@ == "SHIP"@,
    ensures
        forall|i0: int, i1: int| #![trigger row_hit(o, l, i0, i1)] row_hit(o, l, i0, i1) && (true) ==> exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(o, l, i0, i1) == res[r].l_shipmode@,
{
    let idx: int = if pm { 1int } else { 0int };
    assert forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && (true) implies exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(o, l, a, b) == res[r].l_shipmode@ by {
        if key_at(o, l, a, b) == "MAIL"@ {
            assert(pm);
            assert(0 <= 0 < res.len() && key_at(o, l, a, b) == res[0].l_shipmode@);
        } else {
            assert(ps);
            assert(0 <= idx < res.len() && key_at(o, l, a, b) == res[idx].l_shipmode@);
        }
    };
}

proof fn lemma_out24(res: Seq<OutRow>, pm: bool, ps: bool)
    requires
        res.len() == (if pm { 1int } else { 0int }) + (if ps { 1int } else { 0int }),
        pm ==> res[0].l_shipmode@ == "MAIL"@,
        ps ==> res[if pm { 1int } else { 0int }].l_shipmode@ == "SHIP"@,
    ensures
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> res[a].l_shipmode@ != res[b].l_shipmode@,
        forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> (seq_le(res[i].l_shipmode@, res[i + 1].l_shipmode@)),
{
    reveal_strlit("MAIL");
    reveal_strlit("SHIP");
    reveal_with_fuel(seq_le, 3);
    assert("MAIL"@[0] == 'M');
    assert("SHIP"@[0] == 'S');
    assert("MAIL"@ != "SHIP"@);
    assert(seq_le("MAIL"@, "SHIP"@));
    assert forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() implies res[a].l_shipmode@ != res[b].l_shipmode@ by {
        assert(pm && ps && a == 0 && b == 1);
    };
    assert forall|q: int| #![trigger res[q]] 0 <= q && q + 1 < res.len() implies (seq_le(res[q].l_shipmode@, res[q + 1].l_shipmode@)) by {
        assert(pm && ps && q == 0);
    };
}

proof fn lemma_facts(o: &Cols_orders, l: &Cols_lineitem, pm: bool, ps: bool, hm: int, lm: int, hs: int, ls: int)
    requires
        valid_cols_orders(o),
        valid_cols_lineitem(l),
        hm == sum_high_line_count(o, l, 0, "MAIL"@),
        lm == sum_low_line_count(o, l, 0, "MAIL"@),
        hs == sum_high_line_count(o, l, 0, "SHIP"@),
        ls == sum_low_line_count(o, l, 0, "SHIP"@),
        pm <==> hm + lm > 0,
        ps <==> hs + ls > 0,
    ensures
        forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) ==> (key_at(o, l, a, b) == "MAIL"@ || key_at(o, l, a, b) == "SHIP"@),
        forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "MAIL"@ ==> pm,
        forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "SHIP"@ ==> ps,
        pm ==> exists|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "MAIL"@,
        ps ==> exists|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "SHIP"@,
{
    lemma_tot(o, l, 0, "MAIL"@);
    lemma_tot(o, l, 0, "SHIP"@);
    assert forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) implies (key_at(o, l, a, b) == "MAIL"@ || key_at(o, l, a, b) == "SHIP"@) by {};
    assert forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "MAIL"@ implies pm by {
        assert(0 <= a < o.n as int && 0 <= b < l.n as int);
    };
    assert forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "SHIP"@ implies ps by {
        assert(0 <= a < o.n as int && 0 <= b < l.n as int);
    };
}

proof fn lemma_out(o: &Cols_orders, l: &Cols_lineitem, res: Seq<OutRow>, pm: bool, ps: bool, hm: int, lm: int, hs: int, ls: int)
    requires
        hm == sum_high_line_count(o, l, 0, "MAIL"@),
        lm == sum_low_line_count(o, l, 0, "MAIL"@),
        hs == sum_high_line_count(o, l, 0, "SHIP"@),
        ls == sum_low_line_count(o, l, 0, "SHIP"@),
        forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) ==> (key_at(o, l, a, b) == "MAIL"@ || key_at(o, l, a, b) == "SHIP"@),
        forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "MAIL"@ ==> pm,
        forall|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "SHIP"@ ==> ps,
        pm ==> exists|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "MAIL"@,
        ps ==> exists|a: int, b: int| #![trigger row_hit(o, l, a, b)] row_hit(o, l, a, b) && key_at(o, l, a, b) == "SHIP"@,
        res.len() == (if pm { 1int } else { 0int }) + (if ps { 1int } else { 0int }),
        pm ==> (res[0].l_shipmode@ == "MAIL"@ && res[0].high_line_count as int == hm && res[0].low_line_count as int == lm),
        ps ==> (res[if pm { 1int } else { 0int }].l_shipmode@ == "SHIP"@ && res[if pm { 1int } else { 0int }].high_line_count as int == hs && res[if pm { 1int } else { 0int }].low_line_count as int == ls),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(o, l, res[r]),
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> res[a].l_shipmode@ != res[b].l_shipmode@,
        forall|i0: int, i1: int| #![trigger row_hit(o, l, i0, i1)] row_hit(o, l, i0, i1) && (true) ==> exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(o, l, i0, i1) == res[r].l_shipmode@,
        forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> (seq_le(res[i].l_shipmode@, res[i + 1].l_shipmode@)),
{
    lemma_out1(o, l, res, pm, ps, hm, lm, hs, ls);
    lemma_out3(o, l, res, pm, ps);
    lemma_out24(res, pm, ps);
}

spec fn rowflag(l: &Cols_lineitem, t: int, fm: bool, cmc: usize, fs: bool, csc: usize) -> bool {
    dfilt(l, t) && ((fm && (l.l_shipmode@[t] as int) == cmc as int) || (fs && (l.l_shipmode@[t] as int) == csc as int))
}

proof fn lemma_flag_skip(l: &Cols_lineitem, t: int, fm: bool, cmc: usize, fs: bool, csc: usize)
    requires
        valid_cols_lineitem(l),
        0 <= t < l.n as int,
        fm ==> (cmc as int) < l.l_shipmode__dict@.len() && l.l_shipmode__dict@[cmc as int]@ == "MAIL"@,
        !fm ==> forall|m: int| 0 <= m < l.l_shipmode__dict@.len() ==> l.l_shipmode__dict@[m]@ != "MAIL"@,
        fs ==> (csc as int) < l.l_shipmode__dict@.len() && l.l_shipmode__dict@[csc as int]@ == "SHIP"@,
        !fs ==> forall|m: int| 0 <= m < l.l_shipmode__dict@.len() ==> l.l_shipmode__dict@[m]@ != "SHIP"@,
        !rowflag(l, t, fm, cmc, fs, csc),
    ensures
        !hit_m(l, t, "MAIL"@),
        !hit_m(l, t, "SHIP"@),
{
    lemma_code_iff(l, t, fm, cmc as int, "MAIL"@);
    lemma_code_iff(l, t, fs, csc as int, "SHIP"@);
}

proof fn lemma_and5(a: u32, b: u32, c: u32, d: u32, e: u32)
    requires
        a <= 1, b <= 1, c <= 1, d <= 1, e <= 1,
    ensures
        (a & b & c & d & e) <= 1,
        ((a & b & c & d & e) == 1) <==> (a == 1 && b == 1 && c == 1 && d == 1 && e == 1),
{
    assert((a & b & c & d & e) <= 1) by (bit_vector)
        requires a <= 1, b <= 1, c <= 1, d <= 1, e <= 1;
    assert(((a & b & c & d & e) == 1) <==> (a == 1 && b == 1 && c == 1 && d == 1 && e == 1)) by (bit_vector)
        requires a <= 1, b <= 1, c <= 1, d <= 1, e <= 1;
}

proof fn lemma_or01(a: u32, b: u32)
    requires
        a <= 1, b <= 1,
    ensures
        (a | b) <= 1,
        ((a | b) == 0) <==> (a == 0 && b == 0),
{
    assert((a | b) <= 1) by (bit_vector)
        requires a <= 1, b <= 1;
    assert(((a | b) == 0) <==> (a == 0 && b == 0)) by (bit_vector)
        requires a <= 1, b <= 1;
}

proof fn lemma_a5(code: u32, fm: bool, cmc: usize, fs: bool, csc: usize, mc: u32, scd: u32, mm: u32, ms: u32)
    requires
        mc == cmc as u32,
        scd == csc as u32,
        mm == (if fm && cmc <= 4294967295 { 1u32 } else { 0u32 }),
        ms == (if fs && csc <= 4294967295 { 1u32 } else { 0u32 }),
    ensures
        ((if code == mc { mm } else { 0u32 }) | (if code == scd { ms } else { 0u32 })) <= 1,
        (((if code == mc { mm } else { 0u32 }) | (if code == scd { ms } else { 0u32 })) == 1) <==> ((fm && (code as usize) == cmc) || (fs && (code as usize) == csc)),
{
    let x: u32 = if code == mc { mm } else { 0u32 };
    let y: u32 = if code == scd { ms } else { 0u32 };
    lemma_or01(x, y);
}

proof fn lemma_lst_skip(l: &Cols_lineitem, v: Seq<i64>, m: Seq<char>, b: int, i: int, hi: int)
    requires
        0 <= b <= i <= l.n as int,
        lst_ok(l, v, m, i, hi),
        forall|t: int| #![trigger hit_m(l, t, m)] b <= t < i ==> !hit_m(l, t, m),
    ensures
        lst_ok(l, v, m, b, hi),
    decreases i - b,
{
    if b < i {
        lemma_lst_step(l, v, v, m, i - 1, hi, false, 0);
        lemma_lst_skip(l, v, m, b, i - 1, hi);
    }
}
// AGENT_HELPERS_END
pub fn run_query(orders: &Cols_orders, lineitem: &Cols_lineitem, orders_arc: &std::sync::Arc<Cols_orders>, lineitem_arc: &std::sync::Arc<Cols_lineitem>) -> (res: Vec<OutRow>)
    requires
        **orders_arc == *orders,
        **lineitem_arc == *lineitem,
        valid_cols_orders(orders),
        valid_cols_lineitem(lineitem),
    ensures
        forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(orders, lineitem, res@[r]),
        forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() ==> res@[a].l_shipmode@ != res@[b].l_shipmode@,
        forall|i0: int, i1: int| #![trigger row_hit(orders, lineitem, i0, i1)] row_hit(orders, lineitem, i0, i1) && (true) ==> exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(orders, lineitem, i0, i1) == res@[r].l_shipmode@,
        forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() ==> (seq_le(res@[i].l_shipmode@, res@[i + 1].l_shipmode@)),
{
// AGENT_EDIT_START
    // dictionary codes of the two shipmodes
    let mail: String = String::from_str("MAIL");
    let ship: String = String::from_str("SHIP");
    let nm: usize = lineitem.l_shipmode__dict.len();
    let mut fm: bool = false;
    let mut cmc: usize = 0;
    let mut fs: bool = false;
    let mut csc: usize = 0;
    let mut kk: usize = 0;
    while kk < nm
        invariant
            kk <= nm,
            nm == lineitem.l_shipmode__dict@.len(),
            mail@ == "MAIL"@,
            ship@ == "SHIP"@,
            fm ==> cmc < kk && lineitem.l_shipmode__dict@[cmc as int]@ == "MAIL"@,
            !fm ==> forall|m: int| 0 <= m < kk as int ==> lineitem.l_shipmode__dict@[m]@ != "MAIL"@,
            fs ==> csc < kk && lineitem.l_shipmode__dict@[csc as int]@ == "SHIP"@,
            !fs ==> forall|m: int| 0 <= m < kk as int ==> lineitem.l_shipmode__dict@[m]@ != "SHIP"@,
        decreases nm - kk,
    {
        if !fm && lineitem.l_shipmode__dict[kk] == mail {
            fm = true;
            cmc = kk;
        }
        if !fs && lineitem.l_shipmode__dict[kk] == ship {
            fs = true;
            csc = kk;
        }
        kk += 1;
    }
    // priority class per orders dictionary code
    let urgent: String = String::from_str("1-URGENT");
    let high: String = String::from_str("2-HIGH");
    let np: usize = orders.o_orderpriority__dict.len();
    let mut hflag: Vec<bool> = Vec::new();
    let mut c: usize = 0;
    while c < np
        invariant
            c <= np,
            np == orders.o_orderpriority__dict@.len(),
            urgent@ == "1-URGENT"@,
            high@ == "2-HIGH"@,
            hflag@.len() == c as int,
            forall|q: int| #![trigger hflag@[q]] 0 <= q < c as int ==> (hflag@[q] <==> (orders.o_orderpriority__dict@[q]@ == "1-URGENT"@ || orders.o_orderpriority__dict@[q]@ == "2-HIGH"@)),
        decreases np - c,
    {
        let h = orders.o_orderpriority__dict[c] == urgent || orders.o_orderpriority__dict[c] == high;
        hflag.push(h);
        c += 1;
    }
    // pass 1 (parallel over lineitem row ranges): hit lists per worker, merged into dense u8 counters (+ spill map)
    let n = lineitem.n;
    let cs: usize = n / 8 + 1;
    proof {
        assert(n as int <= ROW_CAP_lineitem as int);
        assert(cs <= 2249577);
    }
    let mut handles: Vec<vstd::thread::JoinHandle<(Vec<i64>, Vec<i64>)>> = Vec::new();
    let mut k: usize = 0;
    while k < 8
        invariant
            k <= 8,
            n == lineitem.n,
            cs == n / 8 + 1,
            cs <= 2249577,
            valid_cols_lineitem(lineitem),
            **lineitem_arc == *lineitem,
            nm == lineitem.l_shipmode__dict@.len(),
            fm ==> cmc < nm && lineitem.l_shipmode__dict@[cmc as int]@ == "MAIL"@,
            !fm ==> forall|m: int| 0 <= m < nm as int ==> lineitem.l_shipmode__dict@[m]@ != "MAIL"@,
            fs ==> csc < nm && lineitem.l_shipmode__dict@[csc as int]@ == "SHIP"@,
            !fs ==> forall|m: int| 0 <= m < nm as int ==> lineitem.l_shipmode__dict@[m]@ != "SHIP"@,
            handles@.len() == k as int,
            forall|m: int| 0 <= m < k as int ==> #[trigger] handle_ok(lineitem, handles@[m], lo_of(n as int, cs as int, k as int - 1 - m), lo_of(n as int, cs as int, k as int - m)),
        decreases 8 - k,
    {
        let c: usize = k;
        proof {
            assert(c as int * cs as int <= 7 * 2249577) by (nonlinear_arith)
                requires c <= 7, cs <= 2249577, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 2249577) by (nonlinear_arith)
                requires c <= 7, cs <= 2249577, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= n { c * cs } else { n };
        let hi: usize = if (c + 1) * cs <= n { (c + 1) * cs } else { n };
        let pa = std::sync::Arc::clone(lineitem_arc);
        proof {
            assert(lo as int == lo_of(n as int, cs as int, k as int));
            assert(hi as int == lo_of(n as int, cs as int, k as int + 1));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
            assert(*pa == *lineitem);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (Vec<i64>, Vec<i64>))
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_lineitem(&*pa),
                    nm == (&*pa).l_shipmode__dict@.len(),
                    fm ==> cmc < nm && (&*pa).l_shipmode__dict@[cmc as int]@ == "MAIL"@,
                    !fm ==> forall|m: int| 0 <= m < nm as int ==> (&*pa).l_shipmode__dict@[m]@ != "MAIL"@,
                    fs ==> csc < nm && (&*pa).l_shipmode__dict@[csc as int]@ == "SHIP"@,
                    !fs ==> forall|m: int| 0 <= m < nm as int ==> (&*pa).l_shipmode__dict@[m]@ != "SHIP"@,
                ensures
                    part_ok(&*pa, lo as int, hi as int, r),
                {
                    let ln: &Cols_lineitem = &*pa;
                    {
                        let mut v0: Vec<i64> = Vec::new();
                        let mut v1: Vec<i64> = Vec::new();
                        proof {
                            lemma_lst_init(ln, "MAIL"@, hi as int);
                            lemma_lst_init(ln, "SHIP"@, hi as int);
                        }
                        let mut i: usize = hi;
                        while i > lo
                            invariant
                                lo <= i <= hi,
                                hi <= ln.n,
                                valid_cols_lineitem(ln),
                                nm == ln.l_shipmode__dict@.len(),
                                fm ==> cmc < nm && ln.l_shipmode__dict@[cmc as int]@ == "MAIL"@,
                                !fm ==> forall|m: int| 0 <= m < nm as int ==> ln.l_shipmode__dict@[m]@ != "MAIL"@,
                                fs ==> csc < nm && ln.l_shipmode__dict@[csc as int]@ == "SHIP"@,
                                !fs ==> forall|m: int| 0 <= m < nm as int ==> ln.l_shipmode__dict@[m]@ != "SHIP"@,
                                lst_ok(ln, v0@, "MAIL"@, i as int, hi as int),
                                lst_ok(ln, v1@, "SHIP"@, i as int, hi as int),
                            decreases i - lo,
                        {
                            let mut stop: usize = lo;
                            let mut skip: bool = false;
                            if i - lo >= 32 {
                                stop = i - 32;
                                let mut any: bool = true;
                                if i <= ln.l_receiptdate.len() && i <= ln.l_commitdate.len() && i <= ln.l_shipdate.len() && i <= ln.l_shipmode.len() {
                                    let mc: u32 = cmc as u32;
                                    let scd: u32 = csc as u32;
                                    let mm: u32 = if fm && cmc <= 4294967295 { 1 } else { 0 };
                                    let ms: u32 = if fs && csc <= 4294967295 { 1 } else { 0 };
                                    let mut acc: u32 = 0;
                                    let mut j: usize = 0;
                                    while j < 32
                                        invariant
                                            j <= 32,
                                            stop + 32 == i,
                                            i <= hi,
                                            hi <= ln.n,
                                            valid_cols_lineitem(ln),
                                            i <= ln.l_receiptdate@.len(),
                                            i <= ln.l_commitdate@.len(),
                                            i <= ln.l_shipdate@.len(),
                                            i <= ln.l_shipmode@.len(),
                                            acc <= 1,
                                            mc == cmc as u32,
                                            scd == csc as u32,
                                            mm == (if fm && cmc <= 4294967295 { 1u32 } else { 0u32 }),
                                            ms == (if fs && csc <= 4294967295 { 1u32 } else { 0u32 }),
                                            acc == 0 ==> forall|t: int| #![trigger rowflag(ln, t, fm, cmc, fs, csc)] stop as int <= t < stop as int + j as int ==> !rowflag(ln, t, fm, cmc, fs, csc),
                                        decreases 32 - j,
                                    {
                                        let k: usize = stop + j;
                                        let rd = ln.l_receiptdate[k];
                                        let cd = ln.l_commitdate[k];
                                        let sd = ln.l_shipdate[k];
                                        let code = ln.l_shipmode[k];
                                        let a1: u32 = if rd >= 8766 { 1 } else { 0 };
                                        let a2: u32 = if rd < 9131 { 1 } else { 0 };
                                        let a3: u32 = if cd < rd { 1 } else { 0 };
                                        let a4: u32 = if sd < cd { 1 } else { 0 };
                                        let a5: u32 = (if code == mc { mm } else { 0 }) | (if code == scd { ms } else { 0 });
                                        let f: u32 = a1 & a2 & a3 & a4 & a5;
                                        proof {
                                            lemma_a5(code, fm, cmc, fs, csc, mc, scd, mm, ms);
                                            lemma_and5(a1, a2, a3, a4, a5);
                                            assert((f == 1) <==> rowflag(ln, k as int, fm, cmc, fs, csc));
                                            lemma_or01(acc, f);
                                        }
                                        acc = acc | f;
                                        j += 1;
                                    }
                                    any = acc != 0;
                                }
                                skip = !any;
                            }
                            if skip {
                                proof {
                                    assert forall|t: int| #![trigger hit_m(ln, t, "MAIL"@)] stop as int <= t < i as int implies !hit_m(ln, t, "MAIL"@) by {
                                        assert(!rowflag(ln, t, fm, cmc, fs, csc));
                                        lemma_flag_skip(ln, t, fm, cmc, fs, csc);
                                    }
                                    assert forall|t: int| #![trigger hit_m(ln, t, "SHIP"@)] stop as int <= t < i as int implies !hit_m(ln, t, "SHIP"@) by {
                                        assert(!rowflag(ln, t, fm, cmc, fs, csc));
                                        lemma_flag_skip(ln, t, fm, cmc, fs, csc);
                                    }
                                    lemma_lst_skip(ln, v0@, "MAIL"@, stop as int, i as int, hi as int);
                                    lemma_lst_skip(ln, v1@, "SHIP"@, stop as int, i as int, hi as int);
                                }
                                i = stop;
                            } else {
                                while i > stop
                                    invariant
                                        lo <= stop <= i <= hi,
                                        hi <= ln.n,
                                        valid_cols_lineitem(ln),
                                        nm == ln.l_shipmode__dict@.len(),
                                        fm ==> cmc < nm && ln.l_shipmode__dict@[cmc as int]@ == "MAIL"@,
                                        !fm ==> forall|m: int| 0 <= m < nm as int ==> ln.l_shipmode__dict@[m]@ != "MAIL"@,
                                        fs ==> csc < nm && ln.l_shipmode__dict@[csc as int]@ == "SHIP"@,
                                        !fs ==> forall|m: int| 0 <= m < nm as int ==> ln.l_shipmode__dict@[m]@ != "SHIP"@,
                                        lst_ok(ln, v0@, "MAIL"@, i as int, hi as int),
                                        lst_ok(ln, v1@, "SHIP"@, i as int, hi as int),
                                    decreases i - stop,
                                {
                                                    i -= 1;
                                                    proof {
                                                        assert(ln.l_shipmode@.len() == ln.n as int);
                                                        assert(ln.l_commitdate@.len() == ln.n as int);
                                                        assert(ln.l_receiptdate@.len() == ln.n as int);
                                                        assert(ln.l_shipdate@.len() == ln.n as int);
                                                        assert(ln.l_orderkey@.len() == ln.n as int);
                                                    }
                                                    let rd = ln.l_receiptdate[i];
                                                    let dc = rd >= 8766 && rd < 9131 && ln.l_commitdate[i] < rd && ln.l_shipdate[i] < ln.l_commitdate[i];
                                                    let hm = dc && fm && (ln.l_shipmode[i] as usize) == cmc;
                                                    let hs = dc && fs && (ln.l_shipmode[i] as usize) == csc;
                                                    let mut x: i64 = 0;
                                                    if hm || hs {
                                                        x = ln.l_orderkey[i];
                                                    }
                                                    proof {
                                                        assert(dc <==> dfilt(ln, i as int));
                                    lemma_code_iff(ln, i as int, fm, cmc as int, "MAIL"@);
                                                        lemma_code_iff(ln, i as int, fs, csc as int, "SHIP"@);
                                                        assert(hit_m(ln, i as int, "MAIL"@) <==> hm);
                                                        assert(hit_m(ln, i as int, "SHIP"@) <==> hs);
                                                    }
                                                    let ghost v0o = v0@;
                                                    let ghost v1o = v1@;
                                                    if hm {
                                                        v0.push(x);
                                                    }
                                                    if hs {
                                                        v1.push(x);
                                                    }
                                                    proof {
                                                        lemma_lst_step(ln, v0o, v0@, "MAIL"@, i as int, hi as int, hm, x);
                                                        lemma_lst_step(ln, v1o, v1@, "SHIP"@, i as int, hi as int, hs, x);
                                                    }
                                }
                            }
                        }
                        let rw: (Vec<i64>, Vec<i64>) = (v0, v1);
                        proof {
                            assert(i == lo);
                            assert(part_ok(ln, lo as int, hi as int, rw));
                        }
                        rw
                    }
                },
        );
        proof {
            assert(handle_ok(lineitem, h, lo_of(n as int, cs as int, k as int), lo_of(n as int, cs as int, k as int + 1)));
        }
        let ghost old = handles@;
        handles.insert(0, h);
        k += 1;
        proof {
            old.insert_ensures(0, h);
            assert forall|m: int| 0 <= m < k as int implies #[trigger] handle_ok(lineitem, handles@[m], lo_of(n as int, cs as int, k as int - 1 - m), lo_of(n as int, cs as int, k as int - m)) by {
                if m == 0 {
                    assert(handles@[0] == h);
                    assert(handle_ok(lineitem, h, lo_of(n as int, cs as int, (k as int - 1)), lo_of(n as int, cs as int, (k as int - 1) + 1)));
                    assert(lo_of(n as int, cs as int, (k as int - 1)) == lo_of(n as int, cs as int, k as int - 1 - 0));
                } else {
                    assert(handles@[(m - 1) + 1] == old[m - 1]);
                    assert(handle_ok(lineitem, old[m - 1], lo_of(n as int, cs as int, (k as int - 1) - 1 - (m - 1)), lo_of(n as int, cs as int, (k as int - 1) - (m - 1))));
                    assert(lo_of(n as int, cs as int, (k as int - 1) - 1 - (m - 1)) == lo_of(n as int, cs as int, k as int - 1 - m));
                    assert(lo_of(n as int, cs as int, (k as int - 1) - (m - 1)) == lo_of(n as int, cs as int, k as int - m));
                }
            }
        }
    }
    proof {
        assert(k == 8);
        assert forall|mm: int| 0 <= mm < handles@.len() implies #[trigger] handle_ok(lineitem, handles@[mm], lo_of(n as int, cs as int, 7 - mm), lo_of(n as int, cs as int, 8 - mm)) by {
            assert(handle_ok(lineitem, handles@[mm], lo_of(n as int, cs as int, k as int - 1 - mm), lo_of(n as int, cs as int, k as int - mm)));
        }
    }
    let mut a0: Vec<u64> = vec![0u64; 524288];
    let mut a1: Vec<u64> = vec![0u64; 524288];
    let mut mp0: HashMapWithView<i64, u32> = HashMapWithView::new();
    let mut mp1: HashMapWithView<i64, u32> = HashMapWithView::new();
    proof {
        lemma_end(n as int, cs as int);
        lemma_st_init(lineitem, a0@, "MAIL"@, 0);
        lemma_st_init(lineitem, a1@, "SHIP"@, 0);
        assert(lo_of(n as int, cs as int, 0) == 0);
    }
    let mut jj: usize = 0;
    let mut rest: Vec<vstd::thread::JoinHandle<(Vec<i64>, Vec<i64>)>> = handles;
    while rest.len() > 0
        invariant
            jj <= 8,
            jj + rest@.len() == 8,
            n == lineitem.n,
            n <= 17996609,
            cs == n / 8 + 1,
            cs <= 2249577,
            valid_cols_lineitem(lineitem),
            nm == lineitem.l_shipmode__dict@.len(),
            fm ==> cmc < nm && lineitem.l_shipmode__dict@[cmc as int]@ == "MAIL"@,
            !fm ==> forall|m: int| 0 <= m < nm as int ==> lineitem.l_shipmode__dict@[m]@ != "MAIL"@,
            fs ==> csc < nm && lineitem.l_shipmode__dict@[csc as int]@ == "SHIP"@,
            !fs ==> forall|m: int| 0 <= m < nm as int ==> lineitem.l_shipmode__dict@[m]@ != "SHIP"@,
            a0@.len() == 524288,
            a1@.len() == 524288,
            forall|mm: int| 0 <= mm < rest@.len() ==> #[trigger] handle_ok(lineitem, rest@[mm], lo_of(n as int, cs as int, 7 - mm), lo_of(n as int, cs as int, 8 - mm)),
            st_ok(a0@, mp0@, tel(lineitem, "MAIL"@, 0, lo_of(n as int, cs as int, jj as int))),
            st_ok(a1@, mp1@, tel(lineitem, "SHIP"@, 0, lo_of(n as int, cs as int, jj as int))),
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        proof {
            let mm = rest@.len() as int;
            assert(handle_ok(lineitem, old_rest[mm], lo_of(n as int, cs as int, 7 - mm), lo_of(n as int, cs as int, 8 - mm)));
            assert(h == old_rest[mm]);
            assert(7 - mm == jj as int);
            assert(handle_ok(lineitem, h, lo_of(n as int, cs as int, jj as int), lo_of(n as int, cs as int, jj as int + 1)));
        }
        let c: usize = jj;
        proof {
            assert(c as int * cs as int <= 7 * 2249577) by (nonlinear_arith)
                requires c <= 7, cs <= 2249577, c >= 0, cs >= 0;
            assert((c as int + 1) * cs as int <= 8 * 2249577) by (nonlinear_arith)
                requires c <= 7, cs <= 2249577, c >= 0, cs >= 0;
        }
        let lo: usize = if c * cs <= n { c * cs } else { n };
        let hi: usize = if (c + 1) * cs <= n { (c + 1) * cs } else { n };
        proof {
            assert(lo as int == lo_of(n as int, cs as int, jj as int));
            assert(hi as int == lo_of(n as int, cs as int, jj as int + 1));
            lemma_lo_range(n as int, cs as int, c as int);
            assert(lo <= hi <= n);
        }
        let r: (Vec<i64>, Vec<i64>);
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(part_ok(lineitem, lo as int, hi as int, r));
                }
            },
            Err(_) => {
                r = {
                    let ln: &Cols_lineitem = lineitem;
                    {
                        let mut v0: Vec<i64> = Vec::new();
                        let mut v1: Vec<i64> = Vec::new();
                        proof {
                            lemma_lst_init(ln, "MAIL"@, hi as int);
                            lemma_lst_init(ln, "SHIP"@, hi as int);
                        }
                        let mut i: usize = hi;
                        while i > lo
                            invariant
                                lo <= i <= hi,
                                hi <= ln.n,
                                valid_cols_lineitem(ln),
                                nm == ln.l_shipmode__dict@.len(),
                                fm ==> cmc < nm && ln.l_shipmode__dict@[cmc as int]@ == "MAIL"@,
                                !fm ==> forall|m: int| 0 <= m < nm as int ==> ln.l_shipmode__dict@[m]@ != "MAIL"@,
                                fs ==> csc < nm && ln.l_shipmode__dict@[csc as int]@ == "SHIP"@,
                                !fs ==> forall|m: int| 0 <= m < nm as int ==> ln.l_shipmode__dict@[m]@ != "SHIP"@,
                                lst_ok(ln, v0@, "MAIL"@, i as int, hi as int),
                                lst_ok(ln, v1@, "SHIP"@, i as int, hi as int),
                            decreases i - lo,
                        {
                            let mut stop: usize = lo;
                            let mut skip: bool = false;
                            if i - lo >= 32 {
                                stop = i - 32;
                                let mut any: bool = true;
                                if i <= ln.l_receiptdate.len() && i <= ln.l_commitdate.len() && i <= ln.l_shipdate.len() && i <= ln.l_shipmode.len() {
                                    let mc: u32 = cmc as u32;
                                    let scd: u32 = csc as u32;
                                    let mm: u32 = if fm && cmc <= 4294967295 { 1 } else { 0 };
                                    let ms: u32 = if fs && csc <= 4294967295 { 1 } else { 0 };
                                    let mut acc: u32 = 0;
                                    let mut j: usize = 0;
                                    while j < 32
                                        invariant
                                            j <= 32,
                                            stop + 32 == i,
                                            i <= hi,
                                            hi <= ln.n,
                                            valid_cols_lineitem(ln),
                                            i <= ln.l_receiptdate@.len(),
                                            i <= ln.l_commitdate@.len(),
                                            i <= ln.l_shipdate@.len(),
                                            i <= ln.l_shipmode@.len(),
                                            acc <= 1,
                                            mc == cmc as u32,
                                            scd == csc as u32,
                                            mm == (if fm && cmc <= 4294967295 { 1u32 } else { 0u32 }),
                                            ms == (if fs && csc <= 4294967295 { 1u32 } else { 0u32 }),
                                            acc == 0 ==> forall|t: int| #![trigger rowflag(ln, t, fm, cmc, fs, csc)] stop as int <= t < stop as int + j as int ==> !rowflag(ln, t, fm, cmc, fs, csc),
                                        decreases 32 - j,
                                    {
                                        let k: usize = stop + j;
                                        let rd = ln.l_receiptdate[k];
                                        let cd = ln.l_commitdate[k];
                                        let sd = ln.l_shipdate[k];
                                        let code = ln.l_shipmode[k];
                                        let a1: u32 = if rd >= 8766 { 1 } else { 0 };
                                        let a2: u32 = if rd < 9131 { 1 } else { 0 };
                                        let a3: u32 = if cd < rd { 1 } else { 0 };
                                        let a4: u32 = if sd < cd { 1 } else { 0 };
                                        let a5: u32 = (if code == mc { mm } else { 0 }) | (if code == scd { ms } else { 0 });
                                        let f: u32 = a1 & a2 & a3 & a4 & a5;
                                        proof {
                                            lemma_a5(code, fm, cmc, fs, csc, mc, scd, mm, ms);
                                            lemma_and5(a1, a2, a3, a4, a5);
                                            assert((f == 1) <==> rowflag(ln, k as int, fm, cmc, fs, csc));
                                            lemma_or01(acc, f);
                                        }
                                        acc = acc | f;
                                        j += 1;
                                    }
                                    any = acc != 0;
                                }
                                skip = !any;
                            }
                            if skip {
                                proof {
                                    assert forall|t: int| #![trigger hit_m(ln, t, "MAIL"@)] stop as int <= t < i as int implies !hit_m(ln, t, "MAIL"@) by {
                                        assert(!rowflag(ln, t, fm, cmc, fs, csc));
                                        lemma_flag_skip(ln, t, fm, cmc, fs, csc);
                                    }
                                    assert forall|t: int| #![trigger hit_m(ln, t, "SHIP"@)] stop as int <= t < i as int implies !hit_m(ln, t, "SHIP"@) by {
                                        assert(!rowflag(ln, t, fm, cmc, fs, csc));
                                        lemma_flag_skip(ln, t, fm, cmc, fs, csc);
                                    }
                                    lemma_lst_skip(ln, v0@, "MAIL"@, stop as int, i as int, hi as int);
                                    lemma_lst_skip(ln, v1@, "SHIP"@, stop as int, i as int, hi as int);
                                }
                                i = stop;
                            } else {
                                while i > stop
                                    invariant
                                        lo <= stop <= i <= hi,
                                        hi <= ln.n,
                                        valid_cols_lineitem(ln),
                                        nm == ln.l_shipmode__dict@.len(),
                                        fm ==> cmc < nm && ln.l_shipmode__dict@[cmc as int]@ == "MAIL"@,
                                        !fm ==> forall|m: int| 0 <= m < nm as int ==> ln.l_shipmode__dict@[m]@ != "MAIL"@,
                                        fs ==> csc < nm && ln.l_shipmode__dict@[csc as int]@ == "SHIP"@,
                                        !fs ==> forall|m: int| 0 <= m < nm as int ==> ln.l_shipmode__dict@[m]@ != "SHIP"@,
                                        lst_ok(ln, v0@, "MAIL"@, i as int, hi as int),
                                        lst_ok(ln, v1@, "SHIP"@, i as int, hi as int),
                                    decreases i - stop,
                                {
                                                    i -= 1;
                                                    proof {
                                                        assert(ln.l_shipmode@.len() == ln.n as int);
                                                        assert(ln.l_commitdate@.len() == ln.n as int);
                                                        assert(ln.l_receiptdate@.len() == ln.n as int);
                                                        assert(ln.l_shipdate@.len() == ln.n as int);
                                                        assert(ln.l_orderkey@.len() == ln.n as int);
                                                    }
                                                    let rd = ln.l_receiptdate[i];
                                                    let dc = rd >= 8766 && rd < 9131 && ln.l_commitdate[i] < rd && ln.l_shipdate[i] < ln.l_commitdate[i];
                                                    let hm = dc && fm && (ln.l_shipmode[i] as usize) == cmc;
                                                    let hs = dc && fs && (ln.l_shipmode[i] as usize) == csc;
                                                    let mut x: i64 = 0;
                                                    if hm || hs {
                                                        x = ln.l_orderkey[i];
                                                    }
                                                    proof {
                                                        assert(dc <==> dfilt(ln, i as int));
                                    lemma_code_iff(ln, i as int, fm, cmc as int, "MAIL"@);
                                                        lemma_code_iff(ln, i as int, fs, csc as int, "SHIP"@);
                                                        assert(hit_m(ln, i as int, "MAIL"@) <==> hm);
                                                        assert(hit_m(ln, i as int, "SHIP"@) <==> hs);
                                                    }
                                                    let ghost v0o = v0@;
                                                    let ghost v1o = v1@;
                                                    if hm {
                                                        v0.push(x);
                                                    }
                                                    if hs {
                                                        v1.push(x);
                                                    }
                                                    proof {
                                                        lemma_lst_step(ln, v0o, v0@, "MAIL"@, i as int, hi as int, hm, x);
                                                        lemma_lst_step(ln, v1o, v1@, "SHIP"@, i as int, hi as int, hs, x);
                                                    }
                                }
                            }
                        }
                        let rw: (Vec<i64>, Vec<i64>) = (v0, v1);
                        proof {
                            assert(i == lo);
                            assert(part_ok(ln, lo as int, hi as int, rw));
                        }
                        rw
                    }
                };
            },
        }
        let len0: usize = r.0.len();
        let mut p0: usize = 0;
        proof {
            lemma_telp_start(lineitem, "MAIL"@, 0, lo as int, r.0@);
            lemma_st_same(a0@, mp0@, tel(lineitem, "MAIL"@, 0, lo as int), telp(lineitem, "MAIL"@, 0, lo as int, r.0@, 0));
        }
        while p0 < len0
            invariant
                p0 <= len0,
                len0 == r.0@.len(),
                n == lineitem.n,
                n <= 17996609,
                lo <= hi <= n,
                a0@.len() == 524288,
                lst_ok(lineitem, r.0@, "MAIL"@, lo as int, hi as int),
                st_ok(a0@, mp0@, telp(lineitem, "MAIL"@, 0, lo as int, r.0@, p0 as int)),
            decreases len0 - p0,
        {
            let y = r.0[p0];
            let inr = y >= 0 && y < 33554432;
            proof {
                lemma_telp_step(lineitem, "MAIL"@, 0, lo as int, r.0@, p0 as int);
                lemma_telp_bound(lineitem, "MAIL"@, 0, lo as int, hi as int, r.0@, p0 as int + 1, y as int);
            }
            let ghost ao = a0@;
            let ghost po = mp0@;
            proof {
                lemma_st_get(ao, po, telp(lineitem, "MAIL"@, 0, lo as int, r.0@, p0 as int), y);
            }
            let in_arr = inr && ((a0[(y as usize) / 64] >> (((y as usize) % 64) as u64)) & 1u64) == 0u64;
            proof {
                if inr {
                    lemma_bit01(ao[(y as int) / 64], (y as int) % 64);
                    assert((y as usize) as int == y as int);
                }
                assert(in_arr <==> (in_rng(y) && bit_of(ao, y as int) == 0));
            }
            if in_arr {
                let wi: usize = (y as usize) / 64;
                let bi: u64 = ((y as usize) % 64) as u64;
                let w = a0[wi];
                a0.set(wi, w | (1u64 << bi));
            } else {
                let c: u32 = match mp0.get(&y) {
                    Some(v) => *v,
                    None => 0,
                };
                proof {
                    lemma_st_get(ao, po, telp(lineitem, "MAIL"@, 0, lo as int, r.0@, p0 as int), y);
                }
                mp0.insert(y, c + 1);
            }
            proof {
                lemma_st_inc(ao, po, a0@, mp0@, y, telp(lineitem, "MAIL"@, 0, lo as int, r.0@, p0 as int), telp(lineitem, "MAIL"@, 0, lo as int, r.0@, p0 as int + 1));
            }
            p0 += 1;
        }
        proof {
            lemma_telp_end(lineitem, "MAIL"@, 0, lo as int, hi as int, r.0@);
            lemma_st_same(a0@, mp0@, telp(lineitem, "MAIL"@, 0, lo as int, r.0@, len0 as int), tel(lineitem, "MAIL"@, 0, hi as int));
        }
        let len1: usize = r.1.len();
        let mut p1: usize = 0;
        proof {
            lemma_telp_start(lineitem, "SHIP"@, 0, lo as int, r.1@);
            lemma_st_same(a1@, mp1@, tel(lineitem, "SHIP"@, 0, lo as int), telp(lineitem, "SHIP"@, 0, lo as int, r.1@, 0));
        }
        while p1 < len1
            invariant
                p1 <= len1,
                len1 == r.1@.len(),
                n == lineitem.n,
                n <= 17996609,
                lo <= hi <= n,
                a1@.len() == 524288,
                lst_ok(lineitem, r.1@, "SHIP"@, lo as int, hi as int),
                st_ok(a1@, mp1@, telp(lineitem, "SHIP"@, 0, lo as int, r.1@, p1 as int)),
            decreases len1 - p1,
        {
            let y = r.1[p1];
            let inr = y >= 0 && y < 33554432;
            proof {
                lemma_telp_step(lineitem, "SHIP"@, 0, lo as int, r.1@, p1 as int);
                lemma_telp_bound(lineitem, "SHIP"@, 0, lo as int, hi as int, r.1@, p1 as int + 1, y as int);
            }
            let ghost ao = a1@;
            let ghost po = mp1@;
            proof {
                lemma_st_get(ao, po, telp(lineitem, "SHIP"@, 0, lo as int, r.1@, p1 as int), y);
            }
            let in_arr = inr && ((a1[(y as usize) / 64] >> (((y as usize) % 64) as u64)) & 1u64) == 0u64;
            proof {
                if inr {
                    lemma_bit01(ao[(y as int) / 64], (y as int) % 64);
                    assert((y as usize) as int == y as int);
                }
                assert(in_arr <==> (in_rng(y) && bit_of(ao, y as int) == 0));
            }
            if in_arr {
                let wi: usize = (y as usize) / 64;
                let bi: u64 = ((y as usize) % 64) as u64;
                let w = a1[wi];
                a1.set(wi, w | (1u64 << bi));
            } else {
                let c: u32 = match mp1.get(&y) {
                    Some(v) => *v,
                    None => 0,
                };
                proof {
                    lemma_st_get(ao, po, telp(lineitem, "SHIP"@, 0, lo as int, r.1@, p1 as int), y);
                }
                mp1.insert(y, c + 1);
            }
            proof {
                lemma_st_inc(ao, po, a1@, mp1@, y, telp(lineitem, "SHIP"@, 0, lo as int, r.1@, p1 as int), telp(lineitem, "SHIP"@, 0, lo as int, r.1@, p1 as int + 1));
            }
            p1 += 1;
        }
        proof {
            lemma_telp_end(lineitem, "SHIP"@, 0, lo as int, hi as int, r.1@);
            lemma_st_same(a1@, mp1@, telp(lineitem, "SHIP"@, 0, lo as int, r.1@, len1 as int), tel(lineitem, "SHIP"@, 0, hi as int));
        }
        jj += 1;
    }
    proof {
        assert(jj == 8);
        assert(lo_of(n as int, cs as int, 8) == n);
    }
    // pass 2 (parallel over orders row ranges, telescoping sums)
    let ghost a0v = a0@;
    let ghost a1v = a1@;
    let ghost m0v = mp0@;
    let ghost m1v = mp1@;
    let ghost hfv = hflag@;
    let ha = std::sync::Arc::new(hflag);
    let a0a = std::sync::Arc::new(a0);
    let a1a = std::sync::Arc::new(a1);
    let m0a = std::sync::Arc::new(mp0);
    let m1a = std::sync::Arc::new(mp1);
    proof {
        assert((&*a0a)@ == a0v);
        assert((&*a1a)@ == a1v);
        assert((&*m0a)@ == m0v);
        assert((&*m1a)@ == m1v);
        assert((&*ha)@ == hfv);
        assert(lo_of(n as int, cs as int, 8) == n);
    }
    let no = orders.n;
    let cso: usize = no / 8 + 1;
    proof {
        assert(no as int <= ROW_CAP_orders as int);
        assert(cso <= 562501);
    }
    let mut handles2: Vec<vstd::thread::JoinHandle<(u64, u64, u64, u64)>> = Vec::new();
    let mut k2: usize = 0;
    while k2 < 8
        invariant
            k2 <= 8,
            no == orders.n,
            cso == no / 8 + 1,
            cso <= 562501,
            **orders_arc == *orders,
            **lineitem_arc == *lineitem,
            valid_cols_orders(orders),
            valid_cols_lineitem(lineitem),
            **orders_arc == *orders,
            (&*a0a)@.len() == 524288,
            (&*a1a)@.len() == 524288,
            st_ok((&*a0a)@, (&*m0a)@, tel(lineitem, "MAIL"@, 0, lineitem.n as int)),
            st_ok((&*a1a)@, (&*m1a)@, tel(lineitem, "SHIP"@, 0, lineitem.n as int)),
            (&*ha)@.len() == orders.o_orderpriority__dict@.len(),
forall|q: int| #![trigger (&*ha)@[q]] 0 <= q < (&*ha)@.len() ==> ((&*ha)@[q] <==> (orders.o_orderpriority__dict@[q]@ == "1-URGENT"@ || orders.o_orderpriority__dict@[q]@ == "2-HIGH"@)),
            handles2@.len() == k2 as int,
            forall|m: int| 0 <= m < k2 as int ==> #[trigger] handle2_ok(orders, lineitem, handles2@[m], lo_of(no as int, cso as int, 7 - m), lo_of(no as int, cso as int, 8 - m)),
        decreases 8 - k2,
    {
        let c: usize = 7 - k2;
        proof {
            assert(c as int * cso as int <= 7 * 562501) by (nonlinear_arith)
                requires c <= 7, cso <= 562501, c >= 0, cso >= 0;
            assert((c as int + 1) * cso as int <= 8 * 562501) by (nonlinear_arith)
                requires c <= 7, cso <= 562501, c >= 0, cso >= 0;
        }
        let lo: usize = if c * cso <= no { c * cso } else { no };
        let hi: usize = if (c + 1) * cso <= no { (c + 1) * cso } else { no };
        let po = std::sync::Arc::clone(orders_arc);
        let pl = std::sync::Arc::clone(lineitem_arc);
        let hc = std::sync::Arc::clone(&ha);
        let c0 = std::sync::Arc::clone(&a0a);
        let c1 = std::sync::Arc::clone(&a1a);
        let d0 = std::sync::Arc::clone(&m0a);
        let d1 = std::sync::Arc::clone(&m1a);
        proof {
            assert(lo as int == lo_of(no as int, cso as int, 7 - k2 as int));
            assert(hi as int == lo_of(no as int, cso as int, 8 - k2 as int));
            lemma_lo_range(no as int, cso as int, c as int);
            assert(lo <= hi <= no);
            assert(*po == *orders);
            assert(*pl == *lineitem);
            assert(*hc == *ha);
            assert(*c0 == *a0a);
            assert(*c1 == *a1a);
            assert(*d0 == *m0a);
            assert(*d1 == *m1a);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (u64, u64, u64, u64))
                requires
                    lo <= hi,
                    hi <= po.n,
                    valid_cols_orders(&*po),
                    valid_cols_lineitem(&*pl),
                    (&*hc)@.len() == (&*po).o_orderpriority__dict@.len(),
forall|q: int| #![trigger (&*hc)@[q]] 0 <= q < (&*hc)@.len() ==> ((&*hc)@[q] <==> ((&*po).o_orderpriority__dict@[q]@ == "1-URGENT"@ || (&*po).o_orderpriority__dict@[q]@ == "2-HIGH"@)),
                    (&*c0)@.len() == 524288,
                    (&*c1)@.len() == 524288,
                    st_ok((&*c0)@, (&*d0)@, tel(&*pl, "MAIL"@, 0, (&*pl).n as int)),
                    st_ok((&*c1)@, (&*d1)@, tel(&*pl, "SHIP"@, 0, (&*pl).n as int)),
                ensures
                    part2_ok(&*po, &*pl, lo as int, hi as int, r),
                {
                    let oo: &Cols_orders = &*po;
                    let ll: &Cols_lineitem = &*pl;
                    let hf: &Vec<bool> = &*hc;
                    let av0: &Vec<u64> = &*c0;
                    let av1: &Vec<u64> = &*c1;
                    let mv0: &HashMapWithView<i64, u32> = &*d0;
                    let mv1: &HashMapWithView<i64, u32> = &*d1;
                    {
                        let mut hma: u64 = 0;
                        let mut lma: u64 = 0;
                        let mut hsa: u64 = 0;
                        let mut lsa: u64 = 0;
                        proof {
                            reveal_with_fuel(sum_high_line_count, 2);
                            reveal_with_fuel(sum_low_line_count, 2);
                        }
                        let mut i: usize = hi;
                        while i > lo
                            invariant
                                lo <= i <= hi,
                                hi <= oo.n,
                                valid_cols_orders(oo),
                                valid_cols_lineitem(ll),
                                av0@.len() == 524288,
                                av1@.len() == 524288,
                                hf@.len() == oo.o_orderpriority__dict@.len(),
                                forall|q: int| #![trigger hf@[q]] 0 <= q < hf@.len() ==> (hf@[q] <==> (oo.o_orderpriority__dict@[q]@ == "1-URGENT"@ || oo.o_orderpriority__dict@[q]@ == "2-HIGH"@)),
                                st_ok(av0@, mv0@, tel(ll, "MAIL"@, 0, ll.n as int)),
                                st_ok(av1@, mv1@, tel(ll, "SHIP"@, 0, ll.n as int)),
                                hma as int == sum_high_line_count(oo, ll, i as int, "MAIL"@) - sum_high_line_count(oo, ll, hi as int, "MAIL"@),
                                lma as int == sum_low_line_count(oo, ll, i as int, "MAIL"@) - sum_low_line_count(oo, ll, hi as int, "MAIL"@),
                                hsa as int == sum_high_line_count(oo, ll, i as int, "SHIP"@) - sum_high_line_count(oo, ll, hi as int, "SHIP"@),
                                lsa as int == sum_low_line_count(oo, ll, i as int, "SHIP"@) - sum_low_line_count(oo, ll, hi as int, "SHIP"@),
                                hma as int <= (hi as int - i as int) * 17996609,
                                lma as int <= (hi as int - i as int) * 17996609,
                                hsa as int <= (hi as int - i as int) * 17996609,
                                lsa as int <= (hi as int - i as int) * 17996609,
                            decreases i - lo,
                        {
                            i -= 1;
                            proof {
                                assert(oo.o_orderkey@.len() == oo.n as int);
                                assert(oo.o_orderpriority@.len() == oo.n as int);
                                assert((oo.o_orderpriority@[i as int] as int) < oo.o_orderpriority__dict@.len());
                            }
                            let key = oo.o_orderkey[i];
                            let inr = key >= 0 && key < 33554432;
                            let mut cm: u64 = 0;
                            let mut cs: u64 = 0;
                            proof {
                                lemma_st_get(av0@, mv0@, tel(ll, "MAIL"@, 0, ll.n as int), key);
                                lemma_st_get(av1@, mv1@, tel(ll, "SHIP"@, 0, ll.n as int), key);
                                assert(sc(ll, key as int, "MAIL"@, ll.n as int) == 0);
                                assert(sc(ll, key as int, "SHIP"@, ll.n as int) == 0);
                            }
                            if inr {
                                proof {
                                    lemma_bit01(av0@[(key as int) / 64], (key as int) % 64);
                                    lemma_bit01(av1@[(key as int) / 64], (key as int) % 64);
                                    assert((key as usize) as int == key as int);
                                }
                                let b0 = (av0[(key as usize) / 64] >> (((key as usize) % 64) as u64)) & 1u64;
                                if b0 == 0 {
                                    cm = 0;
                                } else {
                                    let dv: u64 = match mv0.get(&key) {
                                        Some(v) => *v as u64,
                                        None => 0,
                                    };
                                    cm = 1 + dv;
                                }
                                let b1 = (av1[(key as usize) / 64] >> (((key as usize) % 64) as u64)) & 1u64;
                                if b1 == 0 {
                                    cs = 0;
                                } else {
                                    let dv: u64 = match mv1.get(&key) {
                                        Some(v) => *v as u64,
                                        None => 0,
                                    };
                                    cs = 1 + dv;
                                }
                            } else {
                                cm = match mv0.get(&key) {
                                    Some(v) => *v as u64,
                                    None => 0,
                                };
                                cs = match mv1.get(&key) {
                                    Some(v) => *v as u64,
                                    None => 0,
                                };
                            }
                            let mut h: bool = false;
                            if cm != 0 || cs != 0 {
                                let pc = oo.o_orderpriority[i] as usize;
                                h = hf[pc];
                            }
                            proof {
                                lemma_d1(oo, ll, i as int, 0, "MAIL"@);
                                lemma_d1(oo, ll, i as int, 0, "SHIP"@);
                                lemma_ohi(oo, i as int, hf@);
                                reveal_with_fuel(sum_high_line_count, 2);
                                reveal_with_fuel(sum_low_line_count, 2);
                                lemma_sc_bound(ll, key as int, "MAIL"@, 0);
                                lemma_sc_bound(ll, key as int, "SHIP"@, 0);
                                assert(cm as int == sc(ll, key as int, "MAIL"@, 0));
                                assert(cs as int == sc(ll, key as int, "SHIP"@, 0));
                                assert(ll.n as int <= ROW_CAP_lineitem as int);
                                assert(oo.n as int <= ROW_CAP_orders as int);
                                assert(cm as int <= 17996609);
                                assert(cs as int <= 17996609);
                                assert((hi as int - i as int) * 17996609 <= 4500000 * 17996609);
                            }
                            hma = hma + (if h { cm } else { 0 });
                            lma = lma + (if h { 0 } else { cm });
                            hsa = hsa + (if h { cs } else { 0 });
                            lsa = lsa + (if h { 0 } else { cs });
                        }
                        let rw: (u64, u64, u64, u64) = (hma, lma, hsa, lsa);
                        proof {
                            assert(i == lo);
                            assert(part2_ok(oo, ll, lo as int, hi as int, rw));
                        }
                        rw
                    }
                },
        );
        proof {
            assert(handle2_ok(orders, lineitem, h, lo_of(no as int, cso as int, 7 - k2 as int), lo_of(no as int, cso as int, 8 - k2 as int)));
        }
        let ghost old = handles2@;
        handles2.push(h);
        k2 += 1;
        proof {
            assert forall|m: int| 0 <= m < k2 as int implies #[trigger] handle2_ok(orders, lineitem, handles2@[m], lo_of(no as int, cso as int, 7 - m), lo_of(no as int, cso as int, 8 - m)) by {
                if m < k2 as int - 1 {
                    assert(handles2@[m] == old[m]);
                }
            }
        }
    }
    let mut tha: u64 = 0;
    let mut tla: u64 = 0;
    let mut tsh: u64 = 0;
    let mut tsl: u64 = 0;
    let mut jj2: usize = 0;
    let mut rest2: Vec<vstd::thread::JoinHandle<(u64, u64, u64, u64)>> = handles2;
    proof {
        lemma_end(no as int, cso as int);
        reveal_with_fuel(sum_high_line_count, 2);
        reveal_with_fuel(sum_low_line_count, 2);
        assert(lo_of(no as int, cso as int, 0) == 0);
    }
    while rest2.len() > 0
        invariant
            jj2 <= 8,
            jj2 + rest2@.len() == 8,
            no == orders.n,
            cso == no / 8 + 1,
            cso <= 562501,
            **orders_arc == *orders,
            **lineitem_arc == *lineitem,
            valid_cols_orders(orders),
            valid_cols_lineitem(lineitem),
            **orders_arc == *orders,
            (&*a0a)@.len() == 524288,
            (&*a1a)@.len() == 524288,
            st_ok((&*a0a)@, (&*m0a)@, tel(lineitem, "MAIL"@, 0, lineitem.n as int)),
            st_ok((&*a1a)@, (&*m1a)@, tel(lineitem, "SHIP"@, 0, lineitem.n as int)),
            (&*ha)@.len() == orders.o_orderpriority__dict@.len(),
forall|q: int| #![trigger (&*ha)@[q]] 0 <= q < (&*ha)@.len() ==> ((&*ha)@[q] <==> (orders.o_orderpriority__dict@[q]@ == "1-URGENT"@ || orders.o_orderpriority__dict@[q]@ == "2-HIGH"@)),
            forall|mm: int| 0 <= mm < rest2@.len() ==> #[trigger] handle2_ok(orders, lineitem, rest2@[mm], lo_of(no as int, cso as int, 7 - mm), lo_of(no as int, cso as int, 8 - mm)),
            tha as int == sum_high_line_count(orders, lineitem, 0, "MAIL"@) - sum_high_line_count(orders, lineitem, lo_of(no as int, cso as int, jj2 as int), "MAIL"@),
            tla as int == sum_low_line_count(orders, lineitem, 0, "MAIL"@) - sum_low_line_count(orders, lineitem, lo_of(no as int, cso as int, jj2 as int), "MAIL"@),
            tsh as int == sum_high_line_count(orders, lineitem, 0, "SHIP"@) - sum_high_line_count(orders, lineitem, lo_of(no as int, cso as int, jj2 as int), "SHIP"@),
            tsl as int == sum_low_line_count(orders, lineitem, 0, "SHIP"@) - sum_low_line_count(orders, lineitem, lo_of(no as int, cso as int, jj2 as int), "SHIP"@),
            tha as int <= lo_of(no as int, cso as int, jj2 as int) * 17996609,
            tla as int <= lo_of(no as int, cso as int, jj2 as int) * 17996609,
            tsh as int <= lo_of(no as int, cso as int, jj2 as int) * 17996609,
            tsl as int <= lo_of(no as int, cso as int, jj2 as int) * 17996609,
        decreases rest2.len(),
    {
        let ghost old_rest = rest2@;
        let h = rest2.pop().unwrap();
        proof {
            let mm = rest2@.len() as int;
            assert(handle2_ok(orders, lineitem, old_rest[mm], lo_of(no as int, cso as int, 7 - mm), lo_of(no as int, cso as int, 8 - mm)));
            assert(h == old_rest[mm]);
            assert(7 - mm == jj2 as int);
            assert(handle2_ok(orders, lineitem, h, lo_of(no as int, cso as int, jj2 as int), lo_of(no as int, cso as int, jj2 as int + 1)));
        }
        let c: usize = jj2;
        proof {
            assert(c as int * cso as int <= 7 * 562501) by (nonlinear_arith)
                requires c <= 7, cso <= 562501, c >= 0, cso >= 0;
            assert((c as int + 1) * cso as int <= 8 * 562501) by (nonlinear_arith)
                requires c <= 7, cso <= 562501, c >= 0, cso >= 0;
        }
        let lo: usize = if c * cso <= no { c * cso } else { no };
        let hi: usize = if (c + 1) * cso <= no { (c + 1) * cso } else { no };
        proof {
            assert(lo as int == lo_of(no as int, cso as int, jj2 as int));
            assert(hi as int == lo_of(no as int, cso as int, jj2 as int + 1));
            lemma_lo_range(no as int, cso as int, c as int);
            assert(lo <= hi <= no);
        }
        let r: (u64, u64, u64, u64);
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(part2_ok(orders, lineitem, lo as int, hi as int, r));
                }
            },
            Err(_) => {
                r = {
                    let oo: &Cols_orders = orders;
                    let ll: &Cols_lineitem = lineitem;
                    let hf: &Vec<bool> = &*ha;
                    let av0: &Vec<u64> = &*a0a;
                    let av1: &Vec<u64> = &*a1a;
                    let mv0: &HashMapWithView<i64, u32> = &*m0a;
                    let mv1: &HashMapWithView<i64, u32> = &*m1a;
                    {
                        let mut hma: u64 = 0;
                        let mut lma: u64 = 0;
                        let mut hsa: u64 = 0;
                        let mut lsa: u64 = 0;
                        proof {
                            reveal_with_fuel(sum_high_line_count, 2);
                            reveal_with_fuel(sum_low_line_count, 2);
                        }
                        let mut i: usize = hi;
                        while i > lo
                            invariant
                                lo <= i <= hi,
                                hi <= oo.n,
                                valid_cols_orders(oo),
                                valid_cols_lineitem(ll),
                                av0@.len() == 524288,
                                av1@.len() == 524288,
                                hf@.len() == oo.o_orderpriority__dict@.len(),
                                forall|q: int| #![trigger hf@[q]] 0 <= q < hf@.len() ==> (hf@[q] <==> (oo.o_orderpriority__dict@[q]@ == "1-URGENT"@ || oo.o_orderpriority__dict@[q]@ == "2-HIGH"@)),
                                st_ok(av0@, mv0@, tel(ll, "MAIL"@, 0, ll.n as int)),
                                st_ok(av1@, mv1@, tel(ll, "SHIP"@, 0, ll.n as int)),
                                hma as int == sum_high_line_count(oo, ll, i as int, "MAIL"@) - sum_high_line_count(oo, ll, hi as int, "MAIL"@),
                                lma as int == sum_low_line_count(oo, ll, i as int, "MAIL"@) - sum_low_line_count(oo, ll, hi as int, "MAIL"@),
                                hsa as int == sum_high_line_count(oo, ll, i as int, "SHIP"@) - sum_high_line_count(oo, ll, hi as int, "SHIP"@),
                                lsa as int == sum_low_line_count(oo, ll, i as int, "SHIP"@) - sum_low_line_count(oo, ll, hi as int, "SHIP"@),
                                hma as int <= (hi as int - i as int) * 17996609,
                                lma as int <= (hi as int - i as int) * 17996609,
                                hsa as int <= (hi as int - i as int) * 17996609,
                                lsa as int <= (hi as int - i as int) * 17996609,
                            decreases i - lo,
                        {
                            i -= 1;
                            proof {
                                assert(oo.o_orderkey@.len() == oo.n as int);
                                assert(oo.o_orderpriority@.len() == oo.n as int);
                                assert((oo.o_orderpriority@[i as int] as int) < oo.o_orderpriority__dict@.len());
                            }
                            let key = oo.o_orderkey[i];
                            let inr = key >= 0 && key < 33554432;
                            let mut cm: u64 = 0;
                            let mut cs: u64 = 0;
                            proof {
                                lemma_st_get(av0@, mv0@, tel(ll, "MAIL"@, 0, ll.n as int), key);
                                lemma_st_get(av1@, mv1@, tel(ll, "SHIP"@, 0, ll.n as int), key);
                                assert(sc(ll, key as int, "MAIL"@, ll.n as int) == 0);
                                assert(sc(ll, key as int, "SHIP"@, ll.n as int) == 0);
                            }
                            if inr {
                                proof {
                                    lemma_bit01(av0@[(key as int) / 64], (key as int) % 64);
                                    lemma_bit01(av1@[(key as int) / 64], (key as int) % 64);
                                    assert((key as usize) as int == key as int);
                                }
                                let b0 = (av0[(key as usize) / 64] >> (((key as usize) % 64) as u64)) & 1u64;
                                if b0 == 0 {
                                    cm = 0;
                                } else {
                                    let dv: u64 = match mv0.get(&key) {
                                        Some(v) => *v as u64,
                                        None => 0,
                                    };
                                    cm = 1 + dv;
                                }
                                let b1 = (av1[(key as usize) / 64] >> (((key as usize) % 64) as u64)) & 1u64;
                                if b1 == 0 {
                                    cs = 0;
                                } else {
                                    let dv: u64 = match mv1.get(&key) {
                                        Some(v) => *v as u64,
                                        None => 0,
                                    };
                                    cs = 1 + dv;
                                }
                            } else {
                                cm = match mv0.get(&key) {
                                    Some(v) => *v as u64,
                                    None => 0,
                                };
                                cs = match mv1.get(&key) {
                                    Some(v) => *v as u64,
                                    None => 0,
                                };
                            }
                            let mut h: bool = false;
                            if cm != 0 || cs != 0 {
                                let pc = oo.o_orderpriority[i] as usize;
                                h = hf[pc];
                            }
                            proof {
                                lemma_d1(oo, ll, i as int, 0, "MAIL"@);
                                lemma_d1(oo, ll, i as int, 0, "SHIP"@);
                                lemma_ohi(oo, i as int, hf@);
                                reveal_with_fuel(sum_high_line_count, 2);
                                reveal_with_fuel(sum_low_line_count, 2);
                                lemma_sc_bound(ll, key as int, "MAIL"@, 0);
                                lemma_sc_bound(ll, key as int, "SHIP"@, 0);
                                assert(cm as int == sc(ll, key as int, "MAIL"@, 0));
                                assert(cs as int == sc(ll, key as int, "SHIP"@, 0));
                                assert(ll.n as int <= ROW_CAP_lineitem as int);
                                assert(oo.n as int <= ROW_CAP_orders as int);
                                assert(cm as int <= 17996609);
                                assert(cs as int <= 17996609);
                                assert((hi as int - i as int) * 17996609 <= 4500000 * 17996609);
                            }
                            hma = hma + (if h { cm } else { 0 });
                            lma = lma + (if h { 0 } else { cm });
                            hsa = hsa + (if h { cs } else { 0 });
                            lsa = lsa + (if h { 0 } else { cs });
                        }
                        let rw: (u64, u64, u64, u64) = (hma, lma, hsa, lsa);
                        proof {
                            assert(i == lo);
                            assert(part2_ok(oo, ll, lo as int, hi as int, rw));
                        }
                        rw
                    }
                };
            },
        }
        proof {
            assert(hi as int <= 4500000);
            assert(lo as int * 17996609 <= 4500000 * 17996609);
            assert((hi as int - lo as int) * 17996609 <= 4500000 * 17996609);
        }
        tha = tha + r.0;
        tla = tla + r.1;
        tsh = tsh + r.2;
        tsl = tsl + r.3;
        jj2 += 1;
    }
    proof {
        assert(jj2 == 8);
        assert(lo_of(no as int, cso as int, 8) == no);
        assert(sum_high_line_count(orders, lineitem, no as int, "MAIL"@) == 0);
        assert(sum_low_line_count(orders, lineitem, no as int, "MAIL"@) == 0);
        assert(sum_high_line_count(orders, lineitem, no as int, "SHIP"@) == 0);
        assert(sum_low_line_count(orders, lineitem, no as int, "SHIP"@) == 0);
    }
    let hma: u64 = tha;
    let lma: u64 = tla;
    let hsa: u64 = tsh;
    let lsa: u64 = tsl;
    proof {
        assert(hma as int <= 4500000 * 17996609);
        assert(lma as int <= 4500000 * 17996609);
        assert(hsa as int <= 4500000 * 17996609);
        assert(lsa as int <= 4500000 * 17996609);
    }
    let pm: bool = hma + lma > 0;
    let ps: bool = hsa + lsa > 0;
    let mut res: Vec<OutRow> = Vec::new();
    if pm {
        let rm = OutRow { l_shipmode: String::from_str("MAIL"), high_line_count: hma as i128, low_line_count: lma as i128 };
        res.push(rm);
    }
    if ps {
        let rs = OutRow { l_shipmode: String::from_str("SHIP"), high_line_count: hsa as i128, low_line_count: lsa as i128 };
        res.push(rs);
    }
    proof {
        lemma_facts(orders, lineitem, pm, ps, hma as int, lma as int, hsa as int, lsa as int);
        lemma_out(orders, lineitem, res@, pm, ps, hma as int, lma as int, hsa as int, lsa as int);
    }
    res
// AGENT_EDIT_END
