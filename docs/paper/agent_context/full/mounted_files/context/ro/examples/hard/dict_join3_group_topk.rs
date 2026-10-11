// Worked example (hard shape, dictionary string mode): a THREE-table join on dictionary string keys, GROUP BY four keys (two dictionary
// strings plus tag and plabel), SUM and COUNT(*), ORDER BY the sum, LIMIT. The shape of (the published GenDB SEC 3-table query)
//   SELECT s.name, p.stmt, n.tag, p.plabel, SUM(n.value) AS total_value, COUNT(*) AS cnt FROM num n
//   JOIN sub s ON n.adsh = s.adsh JOIN pre p ON n.adsh = p.adsh AND n.tag = p.tag AND n.version = p.version
//   WHERE n.uom = 'USD' AND p.stmt = 'IS' AND s.fy = 2023 AND n.value IS NOT NULL
//   GROUP BY s.name, p.stmt, n.tag, p.plabel ORDER BY total_value DESC LIMIT 200
// Table and column names differ in your spec; keep the structure. Techniques (each fixed a failure of a real prover attempt):
//  1. Literals ('USD', 'IS') are looked up ONCE in the dictionary, so a row test is one code comparison.
//  2. Never loop over one table inside a loop over another. The small side (`sub`, unique adsh) is indexed through a `StringHashMap` and a per-code array;
//     the many side (`pre`) is chained by an injective packed key (3 x 32 bits in an `i128`, `HashMapWithView<i128, usize>`) with a `prv` array linking rows
//     of the same key; the NUM pass walks the chain (translate each num dictionary entry to the other tables' codes once, with a sentinel for "absent").
//  3. The GROUP BY map is keyed by the packed code tuple; the per-group sum, count and key codes sit in PARALLEL `Vec`s (no map iteration, no OutRow clone).
//  4. Bound sums with the host join cap (`JOIN_CAP_...`): sum <= matched pairs * cell bound < i128::MAX.
//  5. Z3 matching loop: `forall r. out_row_ok(res[r])` and the coverage ensures (`forall hit. exists r ...`) retrigger each other. State the coverage fact with an
//     explicit witness-index function (`choose|r| key == okey(res[r])`) plus a collapse fact (distinct keys make the witness unique), keep every large
//     quantified fact behind a `#[verifier::opaque]` predicate that only its own lemma reveals, and give the aggregator lemma `#[verifier::rlimit(N)]` (here 30: the one lemma that exceeded the host default budget of 3; keep N small, a larger N only burns the wall clock).
//  6. Record every `len` equality of the parallel Vecs as a loop invariant (`gtg@.len() == gnm@.len()`); an assert inside a `proof` block is NOT visible
//     inside a later loop, restate facts about untouched variables in its invariant.
//  7. `valid_cols_<t>` stays reachable from every loop invariant (here through the opaque wrapper `vcs`), every loop has a `decreases`.
//  8. A `usize` literal above u32::MAX is a rustc error under Verus: compare through `u64`.
//  9. Constants (cell bounds, `JOIN_CAP_...`) come from YOUR spec; this fixture copies its own spec's numbers, and relies on `sub.adsh` being a catalog-declared unique key (re-check `valid_cols_sub`).
// Sizing (no dense table anywhere): the groups live in a `HashMapWithView<i128, usize>` keyed by the packed code tuple, so the key dictionaries' PRODUCT never
// matters (REAL catalog: name 9,646 x stmt 8 x tag 197,363 x plabel 698,147 = 1.06e16 codes pairs; a dense table here is forbidden, see the prompt's
// "Dense slot table" section). Codes are u32 (no declared bound), the only per-code arrays are over ONE dictionary each.
// Speed: proved, ran at 0.93x of the all-core reference on the 1M-row SYNTHETIC db. REAL EDGAR (sec_edgar_dec.duckdb, sec_margin_dec; num 39,401,761, pre 9,600,799, sub 86,135):
// 153 verified, 0 errors; result rows equal DuckDB's; median of 9: 4.44 s (best 3.57 s) vs 1.17 s all-core (0.26x), 4.16 s one thread (0.94x). Correct and runnable; not faster than the all-core engine.
// AGENT_HELPERS_START
spec fn nf(n: &Cols_num, i0: int) -> bool {
    n.uom__dict@[n.uom@[i0] as int]@ == "USD"@
}

spec fn sf(s: &Cols_sub, j: int) -> bool {
    s.fy__valid@[j] && (s.fy@[j] as int) == 2023
}

spec fn pf(p: &Cols_pre, q: int) -> bool {
    p.stmt__valid@[q] && p.stmt__dict@[p.stmt@[q] as int]@ == "IS"@
}

spec fn ae(n: &Cols_num, s: &Cols_sub, i0: int, j: int) -> bool {
    n.adsh__dict@[n.adsh@[i0] as int]@ == s.adsh__dict@[s.adsh@[j] as int]@
}

spec fn mt(n: &Cols_num, p: &Cols_pre, i0: int, q: int) -> bool {
    &&& n.adsh__dict@[n.adsh@[i0] as int]@ == p.adsh__dict@[p.adsh@[q] as int]@
    &&& n.tag__dict@[n.tag@[i0] as int]@ == p.tag__dict@[p.tag@[q] as int]@
    &&& n.version__dict@[n.version@[i0] as int]@ == p.version__dict@[p.version@[q] as int]@
}

spec fn cr(n: &Cols_num, p: &Cols_pre, i0: int, q: int) -> bool {
    pf(p, q) && mt(n, p, i0, q)
}

spec fn pe_of(p: &Cols_pre, q: int) -> int {
    if p.plabel__valid@[q] { p.plabel@[q] as int + 1 } else { 0int }
}

spec fn enc3(a: int, b: int, c: int) -> int {
    a * 36893488147419103232int + b * 8589934592int + c
}

spec fn rk(p: &Cols_pre, q: int) -> int {
    enc3(p.adsh@[q] as int, p.tag@[q] as int, p.version@[q] as int)
}

spec fn dd(d: Seq<String>) -> bool {
    forall|a: int, b: int| #![trigger d[a]@, d[b]@] 0 <= a < b < d.len() ==> d[a]@ != d[b]@
}

spec fn okey(r: OutRow) -> (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)) {
    (r.name@, (if r.stmt is Some { (true, r.stmt->Some_0@) } else { (false, Seq::<char>::empty()) }), r.tag@, (if r.plabel is Some { (true, r.plabel->Some_0@) } else { (false, Seq::<char>::empty()) }))
}

spec fn gkey(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: int, tg: int, pe: int) -> (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)) {
    (s.name__dict@[nm]@, (true, "IS"@), n.tag__dict@[tg]@, if pe > 0 { (true, p.plabel__dict@[pe - 1]@) } else { (false, Seq::<char>::empty()) })
}

spec fn gk(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, g: int) -> (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)) {
    gkey(n, s, p, nm[g] as int, tg[g] as int, pe[g] as int)
}

spec fn bnd(n: &Cols_num, p: &Cols_pre, i0: int, lo: int) -> int {
    join_tuples_num_pre(n, p, i0 + 1) + join_tuples_num_pre_d1(n, p, i0, lo)
}

spec fn gs_one(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, lo: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)), sv: int, cv: int) -> bool {
    &&& sv == sum_total_value(n, s, p, i0 + 1, k) + sum_total_value_d2(n, s, p, i0, j, lo, k)
    &&& cv == count_cnt(n, s, p, i0 + 1, k) + count_cnt_d2(n, s, p, i0, j, lo, k)
    &&& -(bnd(n, p, i0, lo) * 46116860184273879039999int) <= sv
    &&& sv <= bnd(n, p, i0, lo) * 46116860184273879039999int
    &&& cv <= bnd(n, p, i0, lo)
}

proof fn lemma_hit_iff(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, q: int)
    ensures
        row_hit(n, s, p, i0, j, q) <==> (0 <= i0 < n.n as int && 0 <= j < s.n as int && 0 <= q < p.n as int && ae(n, s, i0, j) && cr(n, p, i0, q) && nf(n, i0) && sf(s, j)),
{
}

proof fn lemma_key_hit(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, q: int)
    requires
        row_hit(n, s, p, i0, j, q),
    ensures
        key_at(n, s, p, i0, j, q) == gkey(n, s, p, s.name@[j] as int, n.tag@[i0] as int, pe_of(p, q)),
{
}

proof fn lemma_enc3(a1: int, b1: int, c1: int, a2: int, b2: int, c2: int)
    requires
        0 <= b1 < 4294967296,
        0 <= b2 < 4294967296,
        0 <= c1 < 8589934592,
        0 <= c2 < 8589934592,
        enc3(a1, b1, c1) == enc3(a2, b2, c2),
    ensures
        a1 == a2 && b1 == b2 && c1 == c2,
{
    let m = (a1 - a2) * 4294967296 + (b1 - b2);
    assert(m * 8589934592 == c2 - c1);
    if m >= 1 {
        assert(m * 8589934592 >= 8589934592);
    }
    if m <= -1 {
        assert(m * 8589934592 <= -8589934592);
    }
    assert(m == 0);
    assert(c1 == c2);
    let m2 = a1 - a2;
    assert(m2 * 4294967296 == b2 - b1);
    if m2 >= 1 {
        assert(m2 * 4294967296 >= 4294967296);
    }
    if m2 <= -1 {
        assert(m2 * 4294967296 <= -4294967296);
    }
    assert(m2 == 0);
}

proof fn lemma_dd_eq(d: Seq<String>, a: int, b: int)
    requires
        dd(d),
        0 <= a < d.len(),
        0 <= b < d.len(),
        d[a]@ == d[b]@,
    ensures
        a == b,
{
    if a < b {
        assert(d[a]@ != d[b]@);
    } else if b < a {
        assert(d[b]@ != d[a]@);
    }
}

proof fn lemma_dd_num(n: &Cols_num)
    requires
        valid_cols_num(n),
    ensures
        dd(n.adsh__dict@),
        dd(n.tag__dict@),
        dd(n.uom__dict@),
        dd(n.version__dict@),
{
}

proof fn lemma_dd_sub(s: &Cols_sub)
    requires
        valid_cols_sub(s),
    ensures
        dd(s.adsh__dict@),
        dd(s.name__dict@),
{
}

proof fn lemma_dd_pre(p: &Cols_pre)
    requires
        valid_cols_pre(p),
    ensures
        dd(p.adsh__dict@),
        dd(p.tag__dict@),
        dd(p.version__dict@),
        dd(p.plabel__dict@),
        dd(p.stmt__dict@),
{
}

proof fn lemma_lit_code(d: Seq<String>, lit: Seq<char>, found: bool, code: int, c: int)
    requires
        dd(d),
        0 <= c < d.len(),
        found ==> (0 <= code < d.len() && d[code]@ == lit),
        !found ==> (forall|m: int| 0 <= m < d.len() ==> d[m]@ != lit),
    ensures
        (d[c]@ == lit) <==> (found && c == code),
{
    if found && d[c]@ == lit {
        assert(d[code]@ == d[c]@);
        lemma_dd_eq(d, c, code);
    }
}

proof fn lemma_ae_unique(n: &Cols_num, s: &Cols_sub, i0: int, j: int)
    requires
        valid_cols_sub(s),
        0 <= j < s.n as int,
        ae(n, s, i0, j),
    ensures
        forall|b: int| #![trigger ae(n, s, i0, b)] 0 <= b < s.n as int && b != j ==> !ae(n, s, i0, b),
{
    assert forall|b: int| #![trigger ae(n, s, i0, b)] 0 <= b < s.n as int && b != j implies !ae(n, s, i0, b) by {
        if ae(n, s, i0, b) {
            if b < j {
                assert(!(s.adsh__dict@[s.adsh@[b] as int]@ == s.adsh__dict@[s.adsh@[j] as int]@));
            } else {
                assert(!(s.adsh__dict@[s.adsh@[j] as int]@ == s.adsh__dict@[s.adsh@[b] as int]@));
            }
        }
    };
}

proof fn lemma_gkey_inj(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm1: int, tg1: int, pe1: int, nm2: int, tg2: int, pe2: int)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
        valid_cols_pre(p),
        0 <= nm1 < s.name__dict@.len(),
        0 <= tg1 < n.tag__dict@.len(),
        0 <= pe1 <= p.plabel__dict@.len(),
        0 <= nm2 < s.name__dict@.len(),
        0 <= tg2 < n.tag__dict@.len(),
        0 <= pe2 <= p.plabel__dict@.len(),
        gkey(n, s, p, nm1, tg1, pe1) == gkey(n, s, p, nm2, tg2, pe2),
    ensures
        nm1 == nm2 && tg1 == tg2 && pe1 == pe2,
{
    lemma_dd_sub(s);
    lemma_dd_num(n);
    lemma_dd_pre(p);
    lemma_dd_eq(s.name__dict@, nm1, nm2);
    lemma_dd_eq(n.tag__dict@, tg1, tg2);
    if pe1 > 0 && pe2 > 0 {
        lemma_dd_eq(p.plabel__dict@, pe1 - 1, pe2 - 1);
    }
}

proof fn lemma_d2_step(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, i1: int, q: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        0 <= q < p.n as int,
    ensures
        sum_total_value_d2(n, s, p, i0, i1, q, k) == (if row_hit(n, s, p, i0, i1, q) && key_at(n, s, p, i0, i1, q) == k { sum_total_value_val(n, s, p, i0, i1, q) } else { 0int }) + sum_total_value_d2(n, s, p, i0, i1, q + 1, k),
        count_cnt_d2(n, s, p, i0, i1, q, k) == (if row_hit(n, s, p, i0, i1, q) && key_at(n, s, p, i0, i1, q) == k { 1int } else { 0int }) + count_cnt_d2(n, s, p, i0, i1, q + 1, k),
{
    reveal_with_fuel(sum_total_value_d2, 2);
    reveal_with_fuel(count_cnt_d2, 2);
}

proof fn lemma_d2_end(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, i1: int, q: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        q >= p.n as int,
    ensures
        sum_total_value_d2(n, s, p, i0, i1, q, k) == 0,
        count_cnt_d2(n, s, p, i0, i1, q, k) == 0,
{
    reveal_with_fuel(sum_total_value_d2, 2);
    reveal_with_fuel(count_cnt_d2, 2);
}

proof fn lemma_d2_skip(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, i1: int, a: int, b: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        0 <= a <= b <= p.n as int,
        forall|q: int| #![trigger row_hit(n, s, p, i0, i1, q)] a <= q < b ==> !row_hit(n, s, p, i0, i1, q),
    ensures
        sum_total_value_d2(n, s, p, i0, i1, a, k) == sum_total_value_d2(n, s, p, i0, i1, b, k),
        count_cnt_d2(n, s, p, i0, i1, a, k) == count_cnt_d2(n, s, p, i0, i1, b, k),
    decreases b - a,
{
    if a < b {
        lemma_d2_step(n, s, p, i0, i1, a, k);
        assert(!row_hit(n, s, p, i0, i1, a));
        lemma_d2_skip(n, s, p, i0, i1, a + 1, b, k);
    }
}

proof fn lemma_d2_zero_k(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, i1: int, i2: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        0 <= i2,
        forall|q: int| #![trigger row_hit(n, s, p, i0, i1, q)] i2 <= q < p.n as int && row_hit(n, s, p, i0, i1, q) ==> key_at(n, s, p, i0, i1, q) != k,
    ensures
        sum_total_value_d2(n, s, p, i0, i1, i2, k) == 0,
        count_cnt_d2(n, s, p, i0, i1, i2, k) == 0,
    decreases p.n as int - i2,
{
    reveal_with_fuel(sum_total_value_d2, 2);
    reveal_with_fuel(count_cnt_d2, 2);
    if i2 < p.n as int {
        lemma_d2_zero_k(n, s, p, i0, i1, i2 + 1, k);
    }
}

proof fn lemma_d1_zero_k(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, i1: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        0 <= i1,
        forall|b: int, q: int| #![trigger row_hit(n, s, p, i0, b, q)] i1 <= b < s.n as int && 0 <= q < p.n as int && row_hit(n, s, p, i0, b, q) ==> key_at(n, s, p, i0, b, q) != k,
    ensures
        sum_total_value_d1(n, s, p, i0, i1, k) == 0,
        count_cnt_d1(n, s, p, i0, i1, k) == 0,
    decreases s.n as int - i1,
{
    reveal_with_fuel(sum_total_value_d1, 2);
    reveal_with_fuel(count_cnt_d1, 2);
    if i1 < s.n as int {
        lemma_d2_zero_k(n, s, p, i0, i1, 0, k);
        lemma_d1_zero_k(n, s, p, i0, i1 + 1, k);
    }
}

proof fn lemma_total_zero_k(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        0 <= i,
        forall|a: int, b: int, c: int| #![trigger row_hit(n, s, p, a, b, c)] i <= a < n.n as int && row_hit(n, s, p, a, b, c) ==> key_at(n, s, p, a, b, c) != k,
    ensures
        sum_total_value(n, s, p, i, k) == 0,
        count_cnt(n, s, p, i, k) == 0,
    decreases n.n as int - i,
{
    reveal_with_fuel(sum_total_value, 2);
    reveal_with_fuel(count_cnt, 2);
    if i < n.n as int {
        lemma_d1_zero_k(n, s, p, i, 0, k);
        lemma_total_zero_k(n, s, p, i + 1, k);
    }
}

proof fn lemma_total_step(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        0 <= i0 < n.n as int,
    ensures
        sum_total_value(n, s, p, i0, k) == sum_total_value_d1(n, s, p, i0, 0, k) + sum_total_value(n, s, p, i0 + 1, k),
        count_cnt(n, s, p, i0, k) == count_cnt_d1(n, s, p, i0, 0, k) + count_cnt(n, s, p, i0 + 1, k),
{
    reveal_with_fuel(sum_total_value, 2);
    reveal_with_fuel(count_cnt, 2);
}

proof fn lemma_d1_single(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, i1: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        0 <= j < s.n as int,
        0 <= i1,
        forall|b: int| #![trigger ae(n, s, i0, b)] 0 <= b < s.n as int && b != j ==> !ae(n, s, i0, b),
    ensures
        sum_total_value_d1(n, s, p, i0, i1, k) == (if i1 <= j { sum_total_value_d2(n, s, p, i0, j, 0, k) } else { 0int }),
        count_cnt_d1(n, s, p, i0, i1, k) == (if i1 <= j { count_cnt_d2(n, s, p, i0, j, 0, k) } else { 0int }),
    decreases s.n as int - i1,
{
    reveal_with_fuel(sum_total_value_d1, 2);
    reveal_with_fuel(count_cnt_d1, 2);
    if i1 < s.n as int {
        lemma_d1_single(n, s, p, i0, j, i1 + 1, k);
        if i1 != j {
            assert forall|q: int| #![trigger row_hit(n, s, p, i0, i1, q)] 0 <= q < p.n as int && row_hit(n, s, p, i0, i1, q) implies key_at(n, s, p, i0, i1, q) != k by {
                lemma_hit_iff(n, s, p, i0, i1, q);
            };
            lemma_d2_zero_k(n, s, p, i0, i1, 0, k);
        }
    }
}

proof fn lemma_row_total(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        valid_cols_sub(s),
        0 <= i0 < n.n as int,
        0 <= j < s.n as int,
        ae(n, s, i0, j),
    ensures
        sum_total_value(n, s, p, i0, k) == sum_total_value_d2(n, s, p, i0, j, 0, k) + sum_total_value(n, s, p, i0 + 1, k),
        count_cnt(n, s, p, i0, k) == count_cnt_d2(n, s, p, i0, j, 0, k) + count_cnt(n, s, p, i0 + 1, k),
{
    lemma_ae_unique(n, s, i0, j);
    lemma_total_step(n, s, p, i0, k);
    lemma_d1_single(n, s, p, i0, j, 0, k);
}

proof fn lemma_row_none(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        0 <= i0 < n.n as int,
        forall|b: int, q: int| #![trigger row_hit(n, s, p, i0, b, q)] !row_hit(n, s, p, i0, b, q),
    ensures
        sum_total_value(n, s, p, i0, k) == sum_total_value(n, s, p, i0 + 1, k),
        count_cnt(n, s, p, i0, k) == count_cnt(n, s, p, i0 + 1, k),
{
    lemma_total_step(n, s, p, i0, k);
    lemma_d1_zero_k(n, s, p, i0, 0, k);
}

proof fn lemma_jd1_step(n: &Cols_num, p: &Cols_pre, i0: int, r: int)
    requires
        0 <= r < p.n as int,
    ensures
        join_tuples_num_pre_d1(n, p, i0, r) == (if mt(n, p, i0, r) { 1int } else { 0int }) + join_tuples_num_pre_d1(n, p, i0, r + 1),
{
    reveal_with_fuel(join_tuples_num_pre_d1, 2);
}

proof fn lemma_jd1_end(n: &Cols_num, p: &Cols_pre, i0: int, r: int)
    requires
        r >= p.n as int,
    ensures
        join_tuples_num_pre_d1(n, p, i0, r) == 0,
{
    reveal_with_fuel(join_tuples_num_pre_d1, 2);
}

proof fn lemma_jd1_nonneg(n: &Cols_num, p: &Cols_pre, i0: int, a: int)
    requires
        0 <= a,
    ensures
        join_tuples_num_pre_d1(n, p, i0, a) >= 0,
    decreases p.n as int - a,
{
    reveal_with_fuel(join_tuples_num_pre_d1, 2);
    if a < p.n as int {
        lemma_jd1_nonneg(n, p, i0, a + 1);
    }
}

proof fn lemma_jd1_mono(n: &Cols_num, p: &Cols_pre, i0: int, a: int, b: int)
    requires
        0 <= a <= b,
    ensures
        join_tuples_num_pre_d1(n, p, i0, a) >= join_tuples_num_pre_d1(n, p, i0, b),
    decreases b - a,
{
    reveal_with_fuel(join_tuples_num_pre_d1, 2);
    if a < b {
        lemma_jd1_mono(n, p, i0, a + 1, b);
    }
}

proof fn lemma_J_step(n: &Cols_num, p: &Cols_pre, i0: int)
    requires
        0 <= i0 < n.n as int,
    ensures
        join_tuples_num_pre(n, p, i0) == join_tuples_num_pre_d1(n, p, i0, 0) + join_tuples_num_pre(n, p, i0 + 1),
{
    reveal_with_fuel(join_tuples_num_pre, 2);
}

proof fn lemma_J_nonneg(n: &Cols_num, p: &Cols_pre, a: int)
    requires
        0 <= a,
    ensures
        join_tuples_num_pre(n, p, a) >= 0,
    decreases n.n as int - a,
{
    reveal_with_fuel(join_tuples_num_pre, 2);
    if a < n.n as int {
        lemma_jd1_nonneg(n, p, a, 0);
        lemma_J_nonneg(n, p, a + 1);
    }
}

proof fn lemma_J_ge(n: &Cols_num, p: &Cols_pre, a: int, i0: int)
    requires
        0 <= a <= i0 < n.n as int,
    ensures
        join_tuples_num_pre(n, p, a) >= join_tuples_num_pre_d1(n, p, i0, 0) + join_tuples_num_pre(n, p, i0 + 1),
    decreases i0 - a,
{
    lemma_J_step(n, p, a);
    if a < i0 {
        lemma_jd1_nonneg(n, p, a, 0);
        lemma_J_ge(n, p, a + 1, i0);
    }
}

proof fn lemma_bnd_cap(n: &Cols_num, p: &Cols_pre, i0: int, lo: int)
    requires
        join_tuples_num_pre(n, p, 0) <= JOIN_CAP_num_pre as int,
        0 <= i0 < n.n as int,
        0 <= lo,
    ensures
        0 <= bnd(n, p, i0, lo),
        bnd(n, p, i0, lo) <= 68719476736int,
{
    lemma_jd1_mono(n, p, i0, 0, lo);
    lemma_J_ge(n, p, 0, i0);
    lemma_jd1_nonneg(n, p, i0, lo);
    lemma_J_nonneg(n, p, i0 + 1);
    assert(JOIN_CAP_num_pre as int == 68719476736int);
}

#[verifier::opaque]
spec fn vcs(n: &Cols_num, s: &Cols_sub, p: &Cols_pre) -> bool {
    valid_cols_num(n) && valid_cols_sub(s) && valid_cols_pre(p)
}

proof fn lemma_vcs_close(n: &Cols_num, s: &Cols_sub, p: &Cols_pre)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
        valid_cols_pre(p),
    ensures
        vcs(n, s, p),
{
    reveal(vcs);
}

proof fn lemma_vcs_open(n: &Cols_num, s: &Cols_sub, p: &Cols_pre)
    requires
        vcs(n, s, p),
    ensures
        valid_cols_num(n),
        valid_cols_sub(s),
        valid_cols_pre(p),
{
    reveal(vcs);
}

proof fn lemma_gs_skip(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, lo: int, r1: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)), sv: int, cv: int)
    requires
        0 <= r1 <= lo <= p.n as int,
        forall|c: int| #![trigger row_hit(n, s, p, i0, j, c)] r1 <= c < lo ==> !row_hit(n, s, p, i0, j, c),
        gs_one(n, s, p, i0, j, lo, k, sv, cv),
    ensures
        gs_one(n, s, p, i0, j, r1, k, sv, cv),
{
    lemma_d2_skip(n, s, p, i0, j, r1, lo, k);
    lemma_jd1_mono(n, p, i0, r1, lo);
}

proof fn lemma_gs_step_other(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, r: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)), sv: int, cv: int)
    requires
        0 <= r < p.n as int,
        gs_one(n, s, p, i0, j, r + 1, k, sv, cv),
        !(row_hit(n, s, p, i0, j, r) && key_at(n, s, p, i0, j, r) == k),
    ensures
        gs_one(n, s, p, i0, j, r, k, sv, cv),
{
    lemma_d2_step(n, s, p, i0, j, r, k);
    lemma_jd1_step(n, p, i0, r);
}

proof fn lemma_gs_step_same(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, r: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)), sv: int, cv: int, sv2: int, cv2: int)
    requires
        valid_cols_num(n),
        0 <= i0 < n.n as int,
        0 <= r < p.n as int,
        row_hit(n, s, p, i0, j, r),
        key_at(n, s, p, i0, j, r) == k,
        gs_one(n, s, p, i0, j, r + 1, k, sv, cv),
        sv2 == sv + n.value@[i0] as int,
        cv2 == cv + 1,
    ensures
        gs_one(n, s, p, i0, j, r, k, sv2, cv2),
{
    lemma_d2_step(n, s, p, i0, j, r, k);
    lemma_jd1_step(n, p, i0, r);
    lemma_hit_iff(n, s, p, i0, j, r);
    assert(-46116860184273879039999int <= n.value@[i0] as int <= 46116860184273879039999int);
    assert(sum_total_value_val(n, s, p, i0, j, r) == n.value@[i0] as int);
    assert(mt(n, p, i0, r));
}

proof fn lemma_gs_new(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, r: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)), sv: int, cv: int)
    requires
        valid_cols_num(n),
        0 <= i0 < n.n as int,
        0 <= r < p.n as int,
        row_hit(n, s, p, i0, j, r),
        key_at(n, s, p, i0, j, r) == k,
        sum_total_value(n, s, p, i0 + 1, k) == 0,
        count_cnt(n, s, p, i0 + 1, k) == 0,
        sum_total_value_d2(n, s, p, i0, j, r + 1, k) == 0,
        count_cnt_d2(n, s, p, i0, j, r + 1, k) == 0,
        sv == n.value@[i0] as int,
        cv == 1,
    ensures
        gs_one(n, s, p, i0, j, r, k, sv, cv),
{
    lemma_d2_step(n, s, p, i0, j, r, k);
    lemma_jd1_step(n, p, i0, r);
    lemma_hit_iff(n, s, p, i0, j, r);
    lemma_jd1_nonneg(n, p, i0, r + 1);
    lemma_J_nonneg(n, p, i0 + 1);
    assert(-46116860184273879039999int <= n.value@[i0] as int <= 46116860184273879039999int);
    assert(sum_total_value_val(n, s, p, i0, j, r) == n.value@[i0] as int);
    assert(mt(n, p, i0, r));
}

proof fn lemma_gs_finish(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)), sv: int, cv: int)
    requires
        valid_cols_sub(s),
        0 <= i0 < n.n as int,
        0 <= j < s.n as int,
        ae(n, s, i0, j),
        gs_one(n, s, p, i0, j, 0, k, sv, cv),
    ensures
        gs_one(n, s, p, i0 - 1, 0, p.n as int, k, sv, cv),
{
    lemma_row_total(n, s, p, i0, j, k);
    lemma_d2_end(n, s, p, i0 - 1, 0, p.n as int, k);
    lemma_jd1_end(n, p, i0 - 1, p.n as int);
    lemma_J_step(n, p, i0);
    assert((i0 - 1) + 1 == i0);
}

proof fn lemma_gs_finish_none(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)), sv: int, cv: int)
    requires
        0 <= i0 < n.n as int,
        forall|b: int, q: int| #![trigger row_hit(n, s, p, i0, b, q)] !row_hit(n, s, p, i0, b, q),
        gs_one(n, s, p, i0, 0, p.n as int, k, sv, cv),
    ensures
        gs_one(n, s, p, i0 - 1, 0, p.n as int, k, sv, cv),
{
    lemma_row_none(n, s, p, i0, k);
    lemma_d2_end(n, s, p, i0, 0, p.n as int, k);
    lemma_d2_end(n, s, p, i0 - 1, 0, p.n as int, k);
    lemma_jd1_end(n, p, i0, p.n as int);
    lemma_jd1_end(n, p, i0 - 1, p.n as int);
    lemma_J_step(n, p, i0);
    lemma_jd1_nonneg(n, p, i0, 0);
    assert((i0 - 1) + 1 == i0);
}

proof fn lemma_gs_enter(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, j2: int, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)), sv: int, cv: int)
    requires
        gs_one(n, s, p, i0, j, p.n as int, k, sv, cv),
    ensures
        gs_one(n, s, p, i0, j2, p.n as int, k, sv, cv),
{
    lemma_d2_end(n, s, p, i0, j, p.n as int, k);
    lemma_d2_end(n, s, p, i0, j2, p.n as int, k);
}

spec fn cov_one(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, a: int, b: int, c: int) -> bool {
    exists|g: int| #![trigger gk(n, s, p, nm, tg, pe, g)] 0 <= g < nm.len() && gk(n, s, p, nm, tg, pe, g) == key_at(n, s, p, a, b, c)
}

spec fn wit_one(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, g: int) -> bool {
    exists|a: int, b: int, c: int| #![trigger row_hit(n, s, p, a, b, c)] row_hit(n, s, p, a, b, c) && key_at(n, s, p, a, b, c) == gk(n, s, p, nm, tg, pe, g)
}

#[verifier::opaque]
spec fn g_shape(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>) -> bool {
    &&& tg.len() == nm.len()
    &&& pe.len() == nm.len()
    &&& forall|g: int| #![trigger nm[g]] 0 <= g < nm.len() ==> (nm[g] as int) < s.name__dict@.len() && (tg[g] as int) < n.tag__dict@.len() && (pe[g] as int) <= p.plabel__dict@.len() && (pe[g] as int) <= 4294967296
    &&& forall|a: int, b: int| #![trigger nm[a], nm[b]] 0 <= a < b < nm.len() ==> !(nm[a] == nm[b] && tg[a] == tg[b] && pe[a] == pe[b])
}

#[verifier::opaque]
spec fn g_sums(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, lo: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>) -> bool {
    &&& sm.len() == nm.len()
    &&& ct.len() == nm.len()
    &&& forall|g: int| #![trigger sm[g]] 0 <= g < nm.len() ==> gs_one(n, s, p, i0, j, lo, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int)
}

#[verifier::opaque]
spec fn g_cov(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, lo: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>) -> bool {
    forall|a: int, b: int, c: int| #![trigger row_hit(n, s, p, a, b, c)] row_hit(n, s, p, a, b, c) && (a > i0 || (a == i0 && c >= lo)) ==> cov_one(n, s, p, nm, tg, pe, a, b, c)
}

#[verifier::opaque]
spec fn g_wit(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>) -> bool {
    forall|g: int| #![trigger nm[g]] 0 <= g < nm.len() ==> wit_one(n, s, p, nm, tg, pe, g)
}

proof fn lemma_shape_get(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, g: int)
    requires
        g_shape(n, s, p, nm, tg, pe),
        0 <= g < nm.len(),
    ensures
        tg.len() == nm.len(),
        pe.len() == nm.len(),
        (nm[g] as int) < s.name__dict@.len(),
        (tg[g] as int) < n.tag__dict@.len(),
        (pe[g] as int) <= p.plabel__dict@.len(),
        (pe[g] as int) <= 4294967296,
{
    reveal(g_shape);
}

proof fn lemma_gk_ne(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, a: int, b: int)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
        valid_cols_pre(p),
        g_shape(n, s, p, nm, tg, pe),
        0 <= a < nm.len(),
        0 <= b < nm.len(),
        a != b,
    ensures
        gk(n, s, p, nm, tg, pe, a) != gk(n, s, p, nm, tg, pe, b),
{
    reveal(g_shape);
    if gk(n, s, p, nm, tg, pe, a) == gk(n, s, p, nm, tg, pe, b) {
        lemma_gkey_inj(n, s, p, nm[a] as int, tg[a] as int, pe[a] as int, nm[b] as int, tg[b] as int, pe[b] as int);
        if a < b {
            assert(!(nm[a] == nm[b] && tg[a] == tg[b] && pe[a] == pe[b]));
        } else {
            assert(!(nm[b] == nm[a] && tg[b] == tg[a] && pe[b] == pe[a]));
        }
    }
}

proof fn lemma_gk_ne_new(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, nn: int, tn: int, pn: int, g: int)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
        valid_cols_pre(p),
        g_shape(n, s, p, nm, tg, pe),
        0 <= g < nm.len(),
        0 <= nn < s.name__dict@.len(),
        0 <= tn < n.tag__dict@.len(),
        0 <= pn <= p.plabel__dict@.len(),
        !(nm[g] as int == nn && tg[g] as int == tn && pe[g] as int == pn),
    ensures
        gk(n, s, p, nm, tg, pe, g) != gkey(n, s, p, nn, tn, pn),
{
    reveal(g_shape);
    if gk(n, s, p, nm, tg, pe, g) == gkey(n, s, p, nn, tn, pn) {
        lemma_gkey_inj(n, s, p, nm[g] as int, tg[g] as int, pe[g] as int, nn, tn, pn);
    }
}

proof fn lemma_nohit_range(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, r1: int, lo: int)
    requires
        forall|c: int| #![trigger cr(n, p, i0, c)] r1 <= c < lo ==> !cr(n, p, i0, c),
    ensures
        forall|c: int| #![trigger row_hit(n, s, p, i0, j, c)] r1 <= c < lo ==> !row_hit(n, s, p, i0, j, c),
{
    assert forall|c: int| #![trigger row_hit(n, s, p, i0, j, c)] r1 <= c < lo implies !row_hit(n, s, p, i0, j, c) by {
        lemma_hit_iff(n, s, p, i0, j, c);
    };
}

proof fn lemma_init(n: &Cols_num, s: &Cols_sub, p: &Cols_pre)
    ensures
        g_shape(n, s, p, Seq::<usize>::empty(), Seq::<u32>::empty(), Seq::<u64>::empty()),
        g_sums(n, s, p, n.n as int - 1, 0, p.n as int, Seq::<usize>::empty(), Seq::<u32>::empty(), Seq::<u64>::empty(), Seq::<i128>::empty(), Seq::<u64>::empty()),
        g_cov(n, s, p, n.n as int - 1, p.n as int, Seq::<usize>::empty(), Seq::<u32>::empty(), Seq::<u64>::empty()),
        g_wit(n, s, p, Seq::<usize>::empty(), Seq::<u32>::empty(), Seq::<u64>::empty()),
{
    reveal(g_shape);
    reveal(g_sums);
    reveal(g_cov);
    reveal(g_wit);
    assert forall|a: int, b: int, c: int| #![trigger row_hit(n, s, p, a, b, c)] row_hit(n, s, p, a, b, c) && (a > n.n as int - 1 || (a == n.n as int - 1 && c >= p.n as int)) implies cov_one(n, s, p, Seq::<usize>::empty(), Seq::<u32>::empty(), Seq::<u64>::empty(), a, b, c) by {
        lemma_hit_iff(n, s, p, a, b, c);
    };
}

proof fn lemma_sums_skip_lo(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, lo: int, r1: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>)
    requires
        0 <= r1 <= lo <= p.n as int,
        forall|c: int| #![trigger cr(n, p, i0, c)] r1 <= c < lo ==> !cr(n, p, i0, c),
        g_sums(n, s, p, i0, j, lo, nm, tg, pe, sm, ct),
    ensures
        g_sums(n, s, p, i0, j, r1, nm, tg, pe, sm, ct),
{
    reveal(g_sums);
    lemma_nohit_range(n, s, p, i0, j, r1, lo);
    assert forall|g: int| #![trigger sm[g]] 0 <= g < nm.len() implies gs_one(n, s, p, i0, j, r1, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int) by {
        lemma_gs_skip(n, s, p, i0, j, lo, r1, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int);
    };
}

proof fn lemma_cov_skip_lo(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, lo: int, r1: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>)
    requires
        0 <= r1 <= lo <= p.n as int,
        forall|c: int| #![trigger cr(n, p, i0, c)] r1 <= c < lo ==> !cr(n, p, i0, c),
        g_cov(n, s, p, i0, lo, nm, tg, pe),
    ensures
        g_cov(n, s, p, i0, r1, nm, tg, pe),
{
    reveal(g_cov);
    assert forall|a: int, b: int, c: int| #![trigger row_hit(n, s, p, a, b, c)] row_hit(n, s, p, a, b, c) && (a > i0 || (a == i0 && c >= r1)) implies cov_one(n, s, p, nm, tg, pe, a, b, c) by {
        lemma_hit_iff(n, s, p, a, b, c);
        if a == i0 && c < lo {
            assert(cr(n, p, i0, c));
        }
    };
}

proof fn lemma_upd_bounds(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, r: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>, g: int)
    requires
        vcs(n, s, p),
        join_tuples_num_pre(n, p, 0) <= JOIN_CAP_num_pre as int,
        0 <= i0 < n.n as int,
        0 <= j < s.n as int,
        0 <= r < p.n as int,
        row_hit(n, s, p, i0, j, r),
        g_sums(n, s, p, i0, j, r + 1, nm, tg, pe, sm, ct),
        0 <= g < nm.len(),
    ensures
        -170141183460469231731687303715884105728int <= sm[g] as int + n.value@[i0] as int,
        sm[g] as int + n.value@[i0] as int <= 170141183460469231731687303715884105727int,
        ct[g] as int + 1 <= 18446744073709551615int,
{
    lemma_vcs_open(n, s, p);
    reveal(g_sums);
    lemma_bnd_cap(n, p, i0, r);
    lemma_jd1_step(n, p, i0, r);
    lemma_hit_iff(n, s, p, i0, j, r);
    assert(mt(n, p, i0, r));
    assert(-46116860184273879039999int <= n.value@[i0] as int <= 46116860184273879039999int);
    assert(bnd(n, p, i0, r + 1) + 1 == bnd(n, p, i0, r));
}

proof fn lemma_sums_found(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, r: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>, g: int, x: i128, y: u64)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        0 <= j < s.n as int,
        0 <= r < p.n as int,
        row_hit(n, s, p, i0, j, r),
        g_shape(n, s, p, nm, tg, pe),
        g_sums(n, s, p, i0, j, r + 1, nm, tg, pe, sm, ct),
        0 <= g < nm.len(),
        gk(n, s, p, nm, tg, pe, g) == key_at(n, s, p, i0, j, r),
        x as int == sm[g] as int + n.value@[i0] as int,
        y as int == ct[g] as int + 1,
    ensures
        g_sums(n, s, p, i0, j, r, nm, tg, pe, sm.update(g, x), ct.update(g, y)),
{
    lemma_vcs_open(n, s, p);
    reveal(g_sums);
    let sm2 = sm.update(g, x);
    let ct2 = ct.update(g, y);
    assert forall|g2: int| #![trigger sm2[g2]] 0 <= g2 < nm.len() implies gs_one(n, s, p, i0, j, r, gk(n, s, p, nm, tg, pe, g2), sm2[g2] as int, ct2[g2] as int) by {
        let k2 = gk(n, s, p, nm, tg, pe, g2);
        if g2 == g {
            lemma_gs_step_same(n, s, p, i0, j, r, k2, sm[g] as int, ct[g] as int, x as int, y as int);
        } else {
            lemma_gk_ne(n, s, p, nm, tg, pe, g2, g);
            lemma_gs_step_other(n, s, p, i0, j, r, k2, sm[g2] as int, ct[g2] as int);
        }
    };
}

proof fn lemma_cov_hit(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, r: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, gi: int)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        0 <= j < s.n as int,
        0 <= r < p.n as int,
        row_hit(n, s, p, i0, j, r),
        g_cov(n, s, p, i0, r + 1, nm, tg, pe),
        0 <= gi < nm.len(),
        gk(n, s, p, nm, tg, pe, gi) == key_at(n, s, p, i0, j, r),
    ensures
        g_cov(n, s, p, i0, r, nm, tg, pe),
{
    lemma_vcs_open(n, s, p);
    reveal(g_cov);
    lemma_hit_iff(n, s, p, i0, j, r);
    lemma_ae_unique(n, s, i0, j);
    assert forall|a: int, b: int, c: int| #![trigger row_hit(n, s, p, a, b, c)] row_hit(n, s, p, a, b, c) && (a > i0 || (a == i0 && c >= r)) implies cov_one(n, s, p, nm, tg, pe, a, b, c) by {
        if a > i0 || (a == i0 && c >= r + 1) {
        } else {
            lemma_hit_iff(n, s, p, a, b, c);
            assert(ae(n, s, i0, b));
            assert(b == j);
            assert(0 <= gi < nm.len() && gk(n, s, p, nm, tg, pe, gi) == key_at(n, s, p, a, b, c));
        }
    };
}

proof fn lemma_cov_push(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, lo: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, nn: usize, tn: u32, pn: u64)
    requires
        g_cov(n, s, p, i0, lo, nm, tg, pe),
        tg.len() == nm.len(),
        pe.len() == nm.len(),
    ensures
        g_cov(n, s, p, i0, lo, nm.push(nn), tg.push(tn), pe.push(pn)),
{
    reveal(g_cov);
    let nm2 = nm.push(nn);
    let tg2 = tg.push(tn);
    let pe2 = pe.push(pn);
    assert forall|a: int, b: int, c: int| #![trigger row_hit(n, s, p, a, b, c)] row_hit(n, s, p, a, b, c) && (a > i0 || (a == i0 && c >= lo)) implies cov_one(n, s, p, nm2, tg2, pe2, a, b, c) by {
        assert(cov_one(n, s, p, nm, tg, pe, a, b, c));
        let g = choose|g: int| 0 <= g < nm.len() && gk(n, s, p, nm, tg, pe, g) == key_at(n, s, p, a, b, c);
        assert(nm2[g] == nm[g]);
        assert(tg2[g] == tg[g]);
        assert(pe2[g] == pe[g]);
        assert(0 <= g < nm2.len() && gk(n, s, p, nm2, tg2, pe2, g) == key_at(n, s, p, a, b, c));
    };
}

proof fn lemma_wit_push(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, nn: usize, tn: u32, pn: u64, a: int, b: int, c: int)
    requires
        g_wit(n, s, p, nm, tg, pe),
        tg.len() == nm.len(),
        pe.len() == nm.len(),
        row_hit(n, s, p, a, b, c),
        key_at(n, s, p, a, b, c) == gkey(n, s, p, nn as int, tn as int, pn as int),
    ensures
        g_wit(n, s, p, nm.push(nn), tg.push(tn), pe.push(pn)),
{
    reveal(g_wit);
    let nm2 = nm.push(nn);
    let tg2 = tg.push(tn);
    let pe2 = pe.push(pn);
    assert forall|g: int| #![trigger nm2[g]] 0 <= g < nm2.len() implies wit_one(n, s, p, nm2, tg2, pe2, g) by {
        if g < nm.len() {
            assert(wit_one(n, s, p, nm, tg, pe, g));
            let a0 = choose|a0: int, b0: int, c0: int| row_hit(n, s, p, a0, b0, c0) && key_at(n, s, p, a0, b0, c0) == gk(n, s, p, nm, tg, pe, g);
            assert(nm2[g] == nm[g]);
            assert(tg2[g] == tg[g]);
            assert(pe2[g] == pe[g]);
            assert(row_hit(n, s, p, a0.0, a0.1, a0.2) && key_at(n, s, p, a0.0, a0.1, a0.2) == gk(n, s, p, nm2, tg2, pe2, g));
        } else {
            assert(nm2[g] == nn);
            assert(tg2[g] == tn);
            assert(pe2[g] == pn);
            assert(row_hit(n, s, p, a, b, c) && key_at(n, s, p, a, b, c) == gk(n, s, p, nm2, tg2, pe2, g));
        }
    };
}

proof fn lemma_newkey_zero(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, r: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, k: (Seq<char>, (bool, Seq<char>), Seq<char>, (bool, Seq<char>)))
    requires
        0 <= i0 < n.n as int,
        0 <= r < p.n as int,
        g_cov(n, s, p, i0, r + 1, nm, tg, pe),
        forall|g: int| #![trigger gk(n, s, p, nm, tg, pe, g)] 0 <= g < nm.len() ==> gk(n, s, p, nm, tg, pe, g) != k,
    ensures
        sum_total_value(n, s, p, i0 + 1, k) == 0,
        count_cnt(n, s, p, i0 + 1, k) == 0,
        sum_total_value_d2(n, s, p, i0, j, r + 1, k) == 0,
        count_cnt_d2(n, s, p, i0, j, r + 1, k) == 0,
{
    reveal(g_cov);
    assert forall|a: int, b: int, c: int| #![trigger row_hit(n, s, p, a, b, c)] i0 + 1 <= a < n.n as int && row_hit(n, s, p, a, b, c) implies key_at(n, s, p, a, b, c) != k by {
        assert(cov_one(n, s, p, nm, tg, pe, a, b, c));
        let g = choose|g: int| 0 <= g < nm.len() && gk(n, s, p, nm, tg, pe, g) == key_at(n, s, p, a, b, c);
        assert(gk(n, s, p, nm, tg, pe, g) != k);
    };
    lemma_total_zero_k(n, s, p, i0 + 1, k);
    assert forall|q: int| #![trigger row_hit(n, s, p, i0, j, q)] r + 1 <= q < p.n as int && row_hit(n, s, p, i0, j, q) implies key_at(n, s, p, i0, j, q) != k by {
        assert(cov_one(n, s, p, nm, tg, pe, i0, j, q));
        let g = choose|g: int| 0 <= g < nm.len() && gk(n, s, p, nm, tg, pe, g) == key_at(n, s, p, i0, j, q);
        assert(gk(n, s, p, nm, tg, pe, g) != k);
    };
    lemma_d2_zero_k(n, s, p, i0, j, r + 1, k);
}

proof fn lemma_sums_new(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, r: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>, nn: usize, tn: u32, pn: u64, vv: i128)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        0 <= j < s.n as int,
        0 <= r < p.n as int,
        row_hit(n, s, p, i0, j, r),
        g_shape(n, s, p, nm, tg, pe),
        g_sums(n, s, p, i0, j, r + 1, nm, tg, pe, sm, ct),
        g_cov(n, s, p, i0, r + 1, nm, tg, pe),
        nn as int == s.name@[j] as int,
        tn as int == n.tag@[i0] as int,
        pn as int == pe_of(p, r),
        vv as int == n.value@[i0] as int,
        forall|g: int| #![trigger nm[g]] 0 <= g < nm.len() ==> !(nm[g] == nn && tg[g] == tn && pe[g] == pn),
    ensures
        g_shape(n, s, p, nm.push(nn), tg.push(tn), pe.push(pn)),
        g_sums(n, s, p, i0, j, r, nm.push(nn), tg.push(tn), pe.push(pn), sm.push(vv), ct.push(1u64)),
{
    lemma_vcs_open(n, s, p);
    let nm2 = nm.push(nn);
    let tg2 = tg.push(tn);
    let pe2 = pe.push(pn);
    let sm2 = sm.push(vv);
    let ct2 = ct.push(1u64);
    lemma_key_hit(n, s, p, i0, j, r);
    lemma_hit_iff(n, s, p, i0, j, r);
    let k0 = key_at(n, s, p, i0, j, r);
    assert((s.name@[j] as int) < s.name__dict@.len());
    assert((n.tag@[i0] as int) < n.tag__dict@.len());
    assert((p.plabel@[r] as int) < p.plabel__dict@.len());
    assert(k0 == gkey(n, s, p, nn as int, tn as int, pn as int));
    assert(0 <= (nn as int) && (nn as int) < s.name__dict@.len());
    assert(0 <= (tn as int) && (tn as int) < n.tag__dict@.len());
    assert(0 <= (pn as int) && (pn as int) <= p.plabel__dict@.len());
    assert(pn as int <= 4294967296);
    lemma_shape_get_all(n, s, p, nm, tg, pe);
    // shape of the extended state
    reveal(g_shape);
    assert(nm2.len() == nm.len() + 1);
    assert forall|g: int| #![trigger nm2[g]] 0 <= g < nm2.len() implies (nm2[g] as int) < s.name__dict@.len() && (tg2[g] as int) < n.tag__dict@.len() && (pe2[g] as int) <= p.plabel__dict@.len() && (pe2[g] as int) <= 4294967296 by {
        if g < nm.len() {
            assert(nm2[g] == nm[g]);
            assert(tg2[g] == tg[g]);
            assert(pe2[g] == pe[g]);
        } else {
            assert(nm2[g] == nn);
            assert(tg2[g] == tn);
            assert(pe2[g] == pn);
        }
    };
    assert forall|a: int, b: int| #![trigger nm2[a], nm2[b]] 0 <= a < b < nm2.len() implies !(nm2[a] == nm2[b] && tg2[a] == tg2[b] && pe2[a] == pe2[b]) by {
        if b < nm.len() {
            assert(nm2[a] == nm[a]);
            assert(nm2[b] == nm[b]);
            assert(tg2[a] == tg[a]);
            assert(tg2[b] == tg[b]);
            assert(pe2[a] == pe[a]);
            assert(pe2[b] == pe[b]);
        } else {
            assert(nm2[a] == nm[a]);
            assert(tg2[a] == tg[a]);
            assert(pe2[a] == pe[a]);
            assert(nm2[b] == nn);
            assert(tg2[b] == tn);
            assert(pe2[b] == pn);
        }
    };
    // sums
    assert forall|g: int| #![trigger gk(n, s, p, nm, tg, pe, g)] 0 <= g < nm.len() implies gk(n, s, p, nm, tg, pe, g) != k0 by {
        lemma_gk_ne_new(n, s, p, nm, tg, pe, nn as int, tn as int, pn as int, g);
    };
    lemma_newkey_zero(n, s, p, i0, j, r, nm, tg, pe, k0);
    reveal(g_sums);
    assert forall|g: int| #![trigger sm2[g]] 0 <= g < nm2.len() implies gs_one(n, s, p, i0, j, r, gk(n, s, p, nm2, tg2, pe2, g), sm2[g] as int, ct2[g] as int) by {
        if g < nm.len() {
            assert(nm2[g] == nm[g]);
            assert(tg2[g] == tg[g]);
            assert(pe2[g] == pe[g]);
            assert(sm2[g] == sm[g]);
            assert(ct2[g] == ct[g]);
            lemma_gs_step_other(n, s, p, i0, j, r, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int);
        } else {
            assert(nm2[g] == nn);
            assert(tg2[g] == tn);
            assert(pe2[g] == pn);
            assert(sm2[g] == vv);
            assert(ct2[g] == 1u64);
            lemma_gs_new(n, s, p, i0, j, r, k0, vv as int, 1);
        }
    };
}

proof fn lemma_shape_get_all(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>)
    requires
        g_shape(n, s, p, nm, tg, pe),
    ensures
        tg.len() == nm.len(),
        pe.len() == nm.len(),
        forall|g: int| #![trigger nm[g]] 0 <= g < nm.len() ==> (nm[g] as int) < s.name__dict@.len() && (tg[g] as int) < n.tag__dict@.len() && (pe[g] as int) <= p.plabel__dict@.len() && (pe[g] as int) <= 4294967296,
        forall|a: int, b: int| #![trigger nm[a], nm[b]] 0 <= a < b < nm.len() ==> !(nm[a] == nm[b] && tg[a] == tg[b] && pe[a] == pe[b]),
{
    reveal(g_shape);
}

proof fn lemma_sums_finish(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        0 <= j < s.n as int,
        ae(n, s, i0, j),
        g_sums(n, s, p, i0, j, 0, nm, tg, pe, sm, ct),
    ensures
        g_sums(n, s, p, i0 - 1, 0, p.n as int, nm, tg, pe, sm, ct),
{
    lemma_vcs_open(n, s, p);
    reveal(g_sums);
    assert forall|g: int| #![trigger sm[g]] 0 <= g < nm.len() implies gs_one(n, s, p, i0 - 1, 0, p.n as int, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int) by {
        lemma_gs_finish(n, s, p, i0, j, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int);
    };
}

proof fn lemma_sums_finish_none(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>)
    requires
        0 <= i0 < n.n as int,
        forall|b: int, q: int| #![trigger row_hit(n, s, p, i0, b, q)] !row_hit(n, s, p, i0, b, q),
        g_sums(n, s, p, i0, 0, p.n as int, nm, tg, pe, sm, ct),
    ensures
        g_sums(n, s, p, i0 - 1, 0, p.n as int, nm, tg, pe, sm, ct),
{
    reveal(g_sums);
    assert forall|g: int| #![trigger sm[g]] 0 <= g < nm.len() implies gs_one(n, s, p, i0 - 1, 0, p.n as int, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int) by {
        lemma_gs_finish_none(n, s, p, i0, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int);
    };
}

proof fn lemma_sums_enter(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, j2: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>)
    requires
        g_sums(n, s, p, i0, j, p.n as int, nm, tg, pe, sm, ct),
    ensures
        g_sums(n, s, p, i0, j2, p.n as int, nm, tg, pe, sm, ct),
{
    reveal(g_sums);
    assert forall|g: int| #![trigger sm[g]] 0 <= g < nm.len() implies gs_one(n, s, p, i0, j2, p.n as int, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int) by {
        lemma_gs_enter(n, s, p, i0, j, j2, gk(n, s, p, nm, tg, pe, g), sm[g] as int, ct[g] as int);
    };
}

proof fn lemma_cov_finish(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>)
    requires
        g_cov(n, s, p, i0, 0, nm, tg, pe),
    ensures
        g_cov(n, s, p, i0 - 1, p.n as int, nm, tg, pe),
{
    reveal(g_cov);
}

proof fn lemma_cov_finish_none(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>)
    requires
        forall|b: int, q: int| #![trigger row_hit(n, s, p, i0, b, q)] !row_hit(n, s, p, i0, b, q),
        g_cov(n, s, p, i0, p.n as int, nm, tg, pe),
    ensures
        g_cov(n, s, p, i0 - 1, p.n as int, nm, tg, pe),
{
    reveal(g_cov);
    assert forall|a: int, b: int, c: int| #![trigger row_hit(n, s, p, a, b, c)] row_hit(n, s, p, a, b, c) && (a > i0 - 1 || (a == i0 - 1 && c >= p.n as int)) implies cov_one(n, s, p, nm, tg, pe, a, b, c) by {
        if a == i0 {
            assert(!row_hit(n, s, p, i0, b, c));
        }
    };
}

proof fn lemma_nohit_nf(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int)
    requires
        0 <= i0 < n.n as int,
        !nf(n, i0),
    ensures
        forall|b: int, q: int| #![trigger row_hit(n, s, p, i0, b, q)] !row_hit(n, s, p, i0, b, q),
{
    assert forall|b: int, q: int| #![trigger row_hit(n, s, p, i0, b, q)] !row_hit(n, s, p, i0, b, q) by {
        lemma_hit_iff(n, s, p, i0, b, q);
    };
}

proof fn lemma_nohit_sub(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int)
    requires
        0 <= i0 < n.n as int,
        forall|t: int| #![trigger sf(s, t)] 0 <= t < s.n as int && sf(s, t) ==> s.adsh__dict@[s.adsh@[t] as int]@ != n.adsh__dict@[n.adsh@[i0] as int]@,
    ensures
        forall|b: int, q: int| #![trigger row_hit(n, s, p, i0, b, q)] !row_hit(n, s, p, i0, b, q),
{
    assert forall|b: int, q: int| #![trigger row_hit(n, s, p, i0, b, q)] !row_hit(n, s, p, i0, b, q) by {
        lemma_hit_iff(n, s, p, i0, b, q);
        if row_hit(n, s, p, i0, b, q) {
            assert(sf(s, b));
            assert(ae(n, s, i0, b));
        }
    };
}

proof fn lemma_sums_lens(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, j: int, lo: int, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>)
    requires
        g_sums(n, s, p, i0, j, lo, nm, tg, pe, sm, ct),
    ensures
        sm.len() == nm.len(),
        ct.len() == nm.len(),
{
    reveal(g_sums);
}

spec fn tf(n: &Cols_num, p: &Cols_pre, i0: int, ta: int, tt: int, tv: int) -> bool {
    &&& 0 <= ta < p.adsh__dict@.len()
    &&& 0 <= tt < p.tag__dict@.len()
    &&& 0 <= tv < p.version__dict@.len()
    &&& ta < 4294967296
    &&& tt < 4294967296
    &&& tv < 4294967296
    &&& p.adsh__dict@[ta]@ == n.adsh__dict@[n.adsh@[i0] as int]@
    &&& p.tag__dict@[tt]@ == n.tag__dict@[n.tag@[i0] as int]@
    &&& p.version__dict@[tv]@ == n.version__dict@[n.version@[i0] as int]@
}

#[verifier::opaque]
spec fn gm_inv(gm: Map<i128, usize>, gek: Seq<i128>, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>) -> bool {
    &&& gek.len() == nm.len()
    &&& tg.len() == nm.len()
    &&& pe.len() == nm.len()
    &&& forall|g: int| #![trigger gek[g]] 0 <= g < gek.len() ==> (gek[g] as int == enc3(nm[g] as int, tg[g] as int, pe[g] as int) && gm.contains_key(gek[g]) && gm[gek[g]] as int == g)
    &&& forall|k: i128| #![trigger gm.contains_key(k)] gm.contains_key(k) ==> ((gm[k] as int) < gek.len() && gek[gm[k] as int] == k)
}

proof fn lemma_gm_init(gm: Map<i128, usize>)
    requires
        gm == Map::<i128, usize>::empty(),
    ensures
        gm_inv(gm, Seq::<i128>::empty(), Seq::<usize>::empty(), Seq::<u32>::empty(), Seq::<u64>::empty()),
{
    reveal(gm_inv);
}

proof fn lemma_gm_found(gm: Map<i128, usize>, gek: Seq<i128>, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, e: i128, g: usize)
    requires
        gm_inv(gm, gek, nm, tg, pe),
        gm.contains_key(e),
        gm[e] == g,
    ensures
        (g as int) < nm.len(),
        e as int == enc3(nm[g as int] as int, tg[g as int] as int, pe[g as int] as int),
{
    reveal(gm_inv);
}

proof fn lemma_gm_none(gm: Map<i128, usize>, gek: Seq<i128>, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, e: i128)
    requires
        gm_inv(gm, gek, nm, tg, pe),
        !gm.contains_key(e),
    ensures
        forall|g: int| #![trigger nm[g]] 0 <= g < nm.len() ==> enc3(nm[g] as int, tg[g] as int, pe[g] as int) != e as int,
{
    reveal(gm_inv);
    assert forall|g: int| #![trigger nm[g]] 0 <= g < nm.len() implies enc3(nm[g] as int, tg[g] as int, pe[g] as int) != e as int by {
        if enc3(nm[g] as int, tg[g] as int, pe[g] as int) == e as int {
            assert(gek[g] == e);
            assert(gm.contains_key(gek[g]));
        }
    };
}

proof fn lemma_gm_push(gm: Map<i128, usize>, gek: Seq<i128>, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, e: i128, nn: usize, tn: u32, pn: u64, gi: usize, gm2: Map<i128, usize>)
    requires
        gm_inv(gm, gek, nm, tg, pe),
        !gm.contains_key(e),
        e as int == enc3(nn as int, tn as int, pn as int),
        gi as int == nm.len(),
        gm2 == gm.insert(e, gi),
    ensures
        gm_inv(gm2, gek.push(e), nm.push(nn), tg.push(tn), pe.push(pn)),
{
    reveal(gm_inv);
    let gek2 = gek.push(e);
    let nm2 = nm.push(nn);
    let tg2 = tg.push(tn);
    let pe2 = pe.push(pn);
    assert forall|g: int| #![trigger gek2[g]] 0 <= g < gek2.len() implies (gek2[g] as int == enc3(nm2[g] as int, tg2[g] as int, pe2[g] as int) && gm2.contains_key(gek2[g]) && gm2[gek2[g]] as int == g) by {
        if g < gek.len() {
            assert(gek2[g] == gek[g]);
            assert(nm2[g] == nm[g]);
            assert(tg2[g] == tg[g]);
            assert(pe2[g] == pe[g]);
            assert(gm.contains_key(gek[g]));
            assert(gek[g] != e);
            assert(gm2.contains_key(gek[g]));
            assert(gm2[gek[g]] == gm[gek[g]]);
        } else {
            assert(gek2[g] == e);
            assert(nm2[g] == nn);
            assert(tg2[g] == tn);
            assert(pe2[g] == pn);
            assert(gm2.contains_key(e));
            assert(gm2[e] == gi);
        }
    };
    assert forall|k: i128| #![trigger gm2.contains_key(k)] gm2.contains_key(k) implies ((gm2[k] as int) < gek2.len() && gek2[gm2[k] as int] == k) by {
        if k == e {
            assert(gm2[k] == gi);
            assert(gek2[nm.len() as int] == e);
        } else {
            assert(gm.contains_key(k));
            assert(gm2[k] == gm[k]);
            assert(gek2[gm[k] as int] == gek[gm[k] as int]);
        }
    };
}

#[verifier::opaque]
spec fn lm_inv(p: &Cols_pre, lm: Map<i128, usize>, q: int) -> bool {
    &&& forall|k: i128| #![trigger lm.contains_key(k)] lm.contains_key(k) ==> (
        1 <= lm[k] as int && lm[k] as int <= q && pf(p, lm[k] as int - 1) && rk(p, lm[k] as int - 1) == k as int
        && (forall|t: int| #![trigger pf(p, t)] lm[k] as int <= t < q ==> !(pf(p, t) && rk(p, t) == k as int)))
    &&& forall|t: int| #![trigger pf(p, t)] 0 <= t < q && pf(p, t) ==> exists|k: i128| #![trigger lm.contains_key(k)] lm.contains_key(k) && k as int == rk(p, t)
}

proof fn lemma_lm_init(p: &Cols_pre, lm: Map<i128, usize>)
    requires
        lm == Map::<i128, usize>::empty(),
    ensures
        lm_inv(p, lm, 0),
{
    reveal(lm_inv);
}

proof fn lemma_lm_pf(p: &Cols_pre, lm: Map<i128, usize>, q: int, key: i128, lm2: Map<i128, usize>)
    requires
        lm_inv(p, lm, q),
        0 <= q < p.n as int,
        pf(p, q),
        key as int == rk(p, q),
        lm2 == lm.insert(key, (q + 1) as usize),
    ensures
        lm_inv(p, lm2, q + 1),
{
    reveal(lm_inv);
    assert forall|k: i128| #![trigger lm2.contains_key(k)] lm2.contains_key(k) implies (
        1 <= lm2[k] as int && lm2[k] as int <= q + 1 && pf(p, lm2[k] as int - 1) && rk(p, lm2[k] as int - 1) == k as int
        && (forall|t: int| #![trigger pf(p, t)] lm2[k] as int <= t < q + 1 ==> !(pf(p, t) && rk(p, t) == k as int))) by {
        if k == key {
            assert(lm2[k] as int == q + 1);
        } else {
            assert(lm.contains_key(k));
            assert(lm2[k] == lm[k]);
            assert forall|t: int| #![trigger pf(p, t)] lm2[k] as int <= t < q + 1 implies !(pf(p, t) && rk(p, t) == k as int) by {
                if t == q {
                    assert(rk(p, q) == key as int);
                    assert(k as int != key as int);
                }
            };
        }
    };
    assert forall|t: int| #![trigger pf(p, t)] 0 <= t < q + 1 && pf(p, t) implies exists|k: i128| #![trigger lm2.contains_key(k)] lm2.contains_key(k) && k as int == rk(p, t) by {
        if t < q {
            let k0 = choose|k: i128| lm.contains_key(k) && k as int == rk(p, t);
            assert(lm2.contains_key(k0));
        } else {
            assert(lm2.contains_key(key));
        }
    };
}

proof fn lemma_lm_nopf(p: &Cols_pre, lm: Map<i128, usize>, q: int)
    requires
        lm_inv(p, lm, q),
        0 <= q < p.n as int,
        !pf(p, q),
    ensures
        lm_inv(p, lm, q + 1),
{
    reveal(lm_inv);
    assert forall|k: i128| #![trigger lm.contains_key(k)] lm.contains_key(k) implies (
        1 <= lm[k] as int && lm[k] as int <= q + 1 && pf(p, lm[k] as int - 1) && rk(p, lm[k] as int - 1) == k as int
        && (forall|t: int| #![trigger pf(p, t)] lm[k] as int <= t < q + 1 ==> !(pf(p, t) && rk(p, t) == k as int))) by {
        assert forall|t: int| #![trigger pf(p, t)] lm[k] as int <= t < q + 1 implies !(pf(p, t) && rk(p, t) == k as int) by {
            if t == q {
                assert(!pf(p, q));
            }
        };
    };
}

proof fn lemma_lm_some(p: &Cols_pre, lm: Map<i128, usize>, key: i128, v: usize)
    requires
        lm_inv(p, lm, p.n as int),
        lm.contains_key(key),
        lm[key] == v,
    ensures
        1 <= v as int,
        v as int <= p.n as int,
        pf(p, v as int - 1),
        rk(p, v as int - 1) == key as int,
        forall|t: int| #![trigger pf(p, t)] v as int <= t < p.n as int ==> !(pf(p, t) && rk(p, t) == key as int),
{
    reveal(lm_inv);
}

proof fn lemma_lm_none(p: &Cols_pre, lm: Map<i128, usize>, key: i128)
    requires
        lm_inv(p, lm, p.n as int),
        !lm.contains_key(key),
    ensures
        forall|t: int| #![trigger pf(p, t)] 0 <= t < p.n as int ==> !(pf(p, t) && rk(p, t) == key as int),
{
    reveal(lm_inv);
    assert forall|t: int| #![trigger pf(p, t)] 0 <= t < p.n as int implies !(pf(p, t) && rk(p, t) == key as int) by {
        if pf(p, t) && rk(p, t) == key as int {
            let k0 = choose|k: i128| lm.contains_key(k) && k as int == rk(p, t);
            assert(k0 == key);
        }
    };
}

#[verifier::opaque]
spec fn prv_inv(p: &Cols_pre, prv: Seq<usize>, q: int) -> bool {
    &&& prv.len() == q
    &&& forall|r: int| #![trigger prv[r]] 0 <= r < q && pf(p, r) ==> (
        (prv[r] == 0 ==> (forall|t: int| #![trigger pf(p, t)] 0 <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r))))
        && (prv[r] > 0 ==> ((prv[r] as int) - 1 < r && pf(p, prv[r] as int - 1) && rk(p, prv[r] as int - 1) == rk(p, r)
            && (forall|t: int| #![trigger pf(p, t)] prv[r] as int <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r))))))
}

proof fn lemma_prv_init(p: &Cols_pre, prv: Seq<usize>)
    requires
        prv == Seq::<usize>::empty(),
    ensures
        prv_inv(p, prv, 0),
{
    reveal(prv_inv);
}

proof fn lemma_prv_some(p: &Cols_pre, lm: Map<i128, usize>, prv: Seq<usize>, q: int, key: i128, v: usize)
    requires
        lm_inv(p, lm, q),
        prv_inv(p, prv, q),
        0 <= q < p.n as int,
        pf(p, q),
        key as int == rk(p, q),
        lm.contains_key(key),
        lm[key] == v,
    ensures
        prv_inv(p, prv.push(v), q + 1),
{
    reveal(lm_inv);
    reveal(prv_inv);
    let prv2 = prv.push(v);
    assert forall|r: int| #![trigger prv2[r]] 0 <= r < q + 1 && pf(p, r) implies (
        (prv2[r] == 0 ==> (forall|t: int| #![trigger pf(p, t)] 0 <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r))))
        && (prv2[r] > 0 ==> ((prv2[r] as int) - 1 < r && pf(p, prv2[r] as int - 1) && rk(p, prv2[r] as int - 1) == rk(p, r)
            && (forall|t: int| #![trigger pf(p, t)] prv2[r] as int <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r)))))) by {
        if r < q {
            assert(prv2[r] == prv[r]);
        } else {
            assert(prv2[r] == v);
        }
    };
}

proof fn lemma_prv_none(p: &Cols_pre, lm: Map<i128, usize>, prv: Seq<usize>, q: int, key: i128)
    requires
        lm_inv(p, lm, q),
        prv_inv(p, prv, q),
        0 <= q < p.n as int,
        pf(p, q),
        key as int == rk(p, q),
        !lm.contains_key(key),
    ensures
        prv_inv(p, prv.push(0usize), q + 1),
{
    reveal(lm_inv);
    reveal(prv_inv);
    let prv2 = prv.push(0usize);
    assert forall|r: int| #![trigger prv2[r]] 0 <= r < q + 1 && pf(p, r) implies (
        (prv2[r] == 0 ==> (forall|t: int| #![trigger pf(p, t)] 0 <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r))))
        && (prv2[r] > 0 ==> ((prv2[r] as int) - 1 < r && pf(p, prv2[r] as int - 1) && rk(p, prv2[r] as int - 1) == rk(p, r)
            && (forall|t: int| #![trigger pf(p, t)] prv2[r] as int <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r)))))) by {
        if r < q {
            assert(prv2[r] == prv[r]);
        } else {
            assert(prv2[r] == 0);
            assert forall|t: int| #![trigger pf(p, t)] 0 <= t < r implies !(pf(p, t) && rk(p, t) == rk(p, r)) by {
                if pf(p, t) && rk(p, t) == rk(p, r) {
                    let k0 = choose|k: i128| lm.contains_key(k) && k as int == rk(p, t);
                    assert(k0 == key);
                }
            };
        }
    };
}

proof fn lemma_prv_nopf(p: &Cols_pre, prv: Seq<usize>, q: int)
    requires
        prv_inv(p, prv, q),
        0 <= q < p.n as int,
        !pf(p, q),
    ensures
        prv_inv(p, prv.push(0usize), q + 1),
{
    reveal(prv_inv);
    let prv2 = prv.push(0usize);
    assert forall|r: int| #![trigger prv2[r]] 0 <= r < q + 1 && pf(p, r) implies (
        (prv2[r] == 0 ==> (forall|t: int| #![trigger pf(p, t)] 0 <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r))))
        && (prv2[r] > 0 ==> ((prv2[r] as int) - 1 < r && pf(p, prv2[r] as int - 1) && rk(p, prv2[r] as int - 1) == rk(p, r)
            && (forall|t: int| #![trigger pf(p, t)] prv2[r] as int <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r)))))) by {
        if r < q {
            assert(prv2[r] == prv[r]);
        } else {
            assert(r == q);
        }
    };
}

proof fn lemma_prv_get(p: &Cols_pre, prv: Seq<usize>, r: int)
    requires
        prv_inv(p, prv, p.n as int),
        0 <= r < p.n as int,
        pf(p, r),
    ensures
        prv[r] == 0 ==> (forall|t: int| #![trigger pf(p, t)] 0 <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r))),
        prv[r] > 0 ==> ((prv[r] as int) - 1 < r && pf(p, prv[r] as int - 1) && rk(p, prv[r] as int - 1) == rk(p, r) && (forall|t: int| #![trigger pf(p, t)] prv[r] as int <= t < r ==> !(pf(p, t) && rk(p, t) == rk(p, r)))),
{
    reveal(prv_inv);
}

#[verifier::opaque]
spec fn ts_ok(s: &Cols_sub, dn: Seq<String>, ts: Seq<usize>, m: int) -> bool {
    &&& ts.len() == m
    &&& 0 <= m <= dn.len()
    &&& forall|q: int| #![trigger ts[q]] 0 <= q < m ==> (
        (ts[q] > 0 ==> ((ts[q] as int) - 1 < s.n as int && sf(s, ts[q] as int - 1) && s.adsh__dict@[s.adsh@[ts[q] as int - 1] as int]@ == dn[q]@))
        && (ts[q] == 0 ==> (forall|t: int| #![trigger sf(s, t)] 0 <= t < s.n as int && sf(s, t) ==> s.adsh__dict@[s.adsh@[t] as int]@ != dn[q]@)))
}

proof fn lemma_ts_init(s: &Cols_sub, dn: Seq<String>, ts: Seq<usize>)
    requires
        ts == Seq::<usize>::empty(),
    ensures
        ts_ok(s, dn, ts, 0),
{
    reveal(ts_ok);
}

proof fn lemma_ts_some(s: &Cols_sub, dn: Seq<String>, ts: Seq<usize>, m: int, v: usize, x: usize)
    requires
        ts_ok(s, dn, ts, m),
        m < dn.len(),
        (v as int) < s.n as int,
        sf(s, v as int),
        s.adsh__dict@[s.adsh@[v as int] as int]@ == dn[m]@,
        x as int == v as int + 1,
    ensures
        ts_ok(s, dn, ts.push(x), m + 1),
{
    reveal(ts_ok);
    let ts2 = ts.push(x);
    assert forall|q: int| #![trigger ts2[q]] 0 <= q < m + 1 implies (
        (ts2[q] > 0 ==> ((ts2[q] as int) - 1 < s.n as int && sf(s, ts2[q] as int - 1) && s.adsh__dict@[s.adsh@[ts2[q] as int - 1] as int]@ == dn[q]@))
        && (ts2[q] == 0 ==> (forall|t: int| #![trigger sf(s, t)] 0 <= t < s.n as int && sf(s, t) ==> s.adsh__dict@[s.adsh@[t] as int]@ != dn[q]@))) by {
        if q < m {
            assert(ts2[q] == ts[q]);
        } else {
            assert(ts2[q] == x);
        }
    };
}

proof fn lemma_ts_none(s: &Cols_sub, dn: Seq<String>, ts: Seq<usize>, m: int)
    requires
        ts_ok(s, dn, ts, m),
        m < dn.len(),
        forall|t: int| #![trigger sf(s, t)] 0 <= t < s.n as int && sf(s, t) ==> s.adsh__dict@[s.adsh@[t] as int]@ != dn[m]@,
    ensures
        ts_ok(s, dn, ts.push(0usize), m + 1),
{
    reveal(ts_ok);
    let ts2 = ts.push(0usize);
    assert forall|q: int| #![trigger ts2[q]] 0 <= q < m + 1 implies (
        (ts2[q] > 0 ==> ((ts2[q] as int) - 1 < s.n as int && sf(s, ts2[q] as int - 1) && s.adsh__dict@[s.adsh@[ts2[q] as int - 1] as int]@ == dn[q]@))
        && (ts2[q] == 0 ==> (forall|t: int| #![trigger sf(s, t)] 0 <= t < s.n as int && sf(s, t) ==> s.adsh__dict@[s.adsh@[t] as int]@ != dn[q]@))) by {
        if q < m {
            assert(ts2[q] == ts[q]);
        } else {
            assert(ts2[q] == 0);
        }
    };
}

proof fn lemma_ts_get(s: &Cols_sub, dn: Seq<String>, ts: Seq<usize>, m: int, q: int)
    requires
        ts_ok(s, dn, ts, m),
        0 <= q < m,
    ensures
        ts.len() == m,
        ts[q] > 0 ==> ((ts[q] as int) - 1 < s.n as int && sf(s, ts[q] as int - 1) && s.adsh__dict@[s.adsh@[ts[q] as int - 1] as int]@ == dn[q]@),
        ts[q] == 0 ==> (forall|t: int| #![trigger sf(s, t)] 0 <= t < s.n as int && sf(s, t) ==> s.adsh__dict@[s.adsh@[t] as int]@ != dn[q]@),
{
    reveal(ts_ok);
}

#[verifier::opaque]
spec fn tr_ok(dp: Seq<String>, dn: Seq<String>, tr: Seq<u64>, m: int) -> bool {
    &&& tr.len() == m
    &&& 0 <= m <= dn.len()
    &&& forall|q: int| #![trigger tr[q]] 0 <= q < m ==> (
        (tr[q] > 0 ==> ((tr[q] as int) <= 4294967296 && (tr[q] as int) - 1 < dp.len() && dp[tr[q] as int - 1]@ == dn[q]@))
        && (tr[q] == 0 ==> (forall|c: int| #![trigger dp[c]@] 0 <= c < dp.len() && c < 4294967296 ==> dp[c]@ != dn[q]@)))
}

proof fn lemma_tr_init(dp: Seq<String>, dn: Seq<String>, tr: Seq<u64>)
    requires
        tr == Seq::<u64>::empty(),
    ensures
        tr_ok(dp, dn, tr, 0),
{
    reveal(tr_ok);
}

proof fn lemma_tr_some(dp: Seq<String>, dn: Seq<String>, tr: Seq<u64>, m: int, c: usize, x: u64)
    requires
        tr_ok(dp, dn, tr, m),
        m < dn.len(),
        (c as int) < dp.len(),
        (c as int) < 4294967296,
        dp[c as int]@ == dn[m]@,
        x as int == c as int + 1,
    ensures
        tr_ok(dp, dn, tr.push(x), m + 1),
{
    reveal(tr_ok);
    let tr2 = tr.push(x);
    assert forall|q: int| #![trigger tr2[q]] 0 <= q < m + 1 implies (
        (tr2[q] > 0 ==> ((tr2[q] as int) <= 4294967296 && (tr2[q] as int) - 1 < dp.len() && dp[tr2[q] as int - 1]@ == dn[q]@))
        && (tr2[q] == 0 ==> (forall|c: int| #![trigger dp[c]@] 0 <= c < dp.len() && c < 4294967296 ==> dp[c]@ != dn[q]@))) by {
        if q < m {
            assert(tr2[q] == tr[q]);
        } else {
            assert(tr2[q] == x);
        }
    };
}

proof fn lemma_tr_none(dp: Seq<String>, dn: Seq<String>, tr: Seq<u64>, m: int)
    requires
        tr_ok(dp, dn, tr, m),
        m < dn.len(),
        forall|c: int| #![trigger dp[c]@] 0 <= c < dp.len() ==> dp[c]@ != dn[m]@,
    ensures
        tr_ok(dp, dn, tr.push(0u64), m + 1),
{
    reveal(tr_ok);
    let tr2 = tr.push(0u64);
    assert forall|q: int| #![trigger tr2[q]] 0 <= q < m + 1 implies (
        (tr2[q] > 0 ==> ((tr2[q] as int) <= 4294967296 && (tr2[q] as int) - 1 < dp.len() && dp[tr2[q] as int - 1]@ == dn[q]@))
        && (tr2[q] == 0 ==> (forall|c: int| #![trigger dp[c]@] 0 <= c < dp.len() && c < 4294967296 ==> dp[c]@ != dn[q]@))) by {
        if q < m {
            assert(tr2[q] == tr[q]);
        } else {
            assert(tr2[q] == 0);
        }
    };
}

proof fn lemma_tr_big(dp: Seq<String>, dn: Seq<String>, tr: Seq<u64>, m: int, v: usize)
    requires
        tr_ok(dp, dn, tr, m),
        m < dn.len(),
        dd(dp),
        (v as int) < dp.len(),
        dp[v as int]@ == dn[m]@,
        (v as int) >= 4294967296,
    ensures
        tr_ok(dp, dn, tr.push(0u64), m + 1),
{
    reveal(tr_ok);
    let tr2 = tr.push(0u64);
    assert forall|c: int| #![trigger dp[c]@] 0 <= c < dp.len() && c < 4294967296 implies dp[c]@ != dn[m]@ by {
        if dp[c]@ == dn[m]@ {
            assert(dp[c]@ == dp[v as int]@);
            lemma_dd_eq(dp, c, v as int);
        }
    };
    assert forall|q: int| #![trigger tr2[q]] 0 <= q < m + 1 implies (
        (tr2[q] > 0 ==> ((tr2[q] as int) <= 4294967296 && (tr2[q] as int) - 1 < dp.len() && dp[tr2[q] as int - 1]@ == dn[q]@))
        && (tr2[q] == 0 ==> (forall|c: int| #![trigger dp[c]@] 0 <= c < dp.len() && c < 4294967296 ==> dp[c]@ != dn[q]@))) by {
        if q < m {
            assert(tr2[q] == tr[q]);
        } else {
            assert(tr2[q] == 0);
        }
    };
}

proof fn lemma_tr_get(dp: Seq<String>, dn: Seq<String>, tr: Seq<u64>, m: int, q: int)
    requires
        tr_ok(dp, dn, tr, m),
        0 <= q < m,
    ensures
        tr.len() == m,
        tr[q] > 0 ==> ((tr[q] as int) <= 4294967296 && (tr[q] as int) - 1 < dp.len() && dp[tr[q] as int - 1]@ == dn[q]@),
        tr[q] == 0 ==> (forall|c: int| #![trigger dp[c]@] 0 <= c < dp.len() && c < 4294967296 ==> dp[c]@ != dn[q]@),
{
    reveal(tr_ok);
}

proof fn lemma_cr_none_a(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        forall|c: int| #![trigger p.adsh__dict@[c]@] 0 <= c < p.adsh__dict@.len() && c < 4294967296 ==> p.adsh__dict@[c]@ != n.adsh__dict@[n.adsh@[i0] as int]@,
    ensures
        forall|q: int| #![trigger cr(n, p, i0, q)] 0 <= q < p.n as int ==> !cr(n, p, i0, q),
{
    lemma_vcs_open(n, s, p);
    assert forall|q: int| #![trigger cr(n, p, i0, q)] 0 <= q < p.n as int implies !cr(n, p, i0, q) by {
        assert((p.adsh@[q] as int) < p.adsh__dict@.len());
        assert(p.adsh__dict@[p.adsh@[q] as int]@ != n.adsh__dict@[n.adsh@[i0] as int]@);
    };
}

proof fn lemma_cr_none_t(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        forall|c: int| #![trigger p.tag__dict@[c]@] 0 <= c < p.tag__dict@.len() && c < 4294967296 ==> p.tag__dict@[c]@ != n.tag__dict@[n.tag@[i0] as int]@,
    ensures
        forall|q: int| #![trigger cr(n, p, i0, q)] 0 <= q < p.n as int ==> !cr(n, p, i0, q),
{
    lemma_vcs_open(n, s, p);
    assert forall|q: int| #![trigger cr(n, p, i0, q)] 0 <= q < p.n as int implies !cr(n, p, i0, q) by {
        assert((p.tag@[q] as int) < p.tag__dict@.len());
        assert(p.tag__dict@[p.tag@[q] as int]@ != n.tag__dict@[n.tag@[i0] as int]@);
    };
}

proof fn lemma_cr_none_v(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        forall|c: int| #![trigger p.version__dict@[c]@] 0 <= c < p.version__dict@.len() && c < 4294967296 ==> p.version__dict@[c]@ != n.version__dict@[n.version@[i0] as int]@,
    ensures
        forall|q: int| #![trigger cr(n, p, i0, q)] 0 <= q < p.n as int ==> !cr(n, p, i0, q),
{
    lemma_vcs_open(n, s, p);
    assert forall|q: int| #![trigger cr(n, p, i0, q)] 0 <= q < p.n as int implies !cr(n, p, i0, q) by {
        assert((p.version@[q] as int) < p.version__dict@.len());
        assert(p.version__dict@[p.version@[q] as int]@ != n.version__dict@[n.version@[i0] as int]@);
    };
}

proof fn lemma_cr_rk(n: &Cols_num, p: &Cols_pre, i0: int, q: int, ta: int, tt: int, tv: int)
    requires
        valid_cols_pre(p),
        0 <= i0 < n.n as int,
        0 <= q < p.n as int,
        tf(n, p, i0, ta, tt, tv),
    ensures
        cr(n, p, i0, q) <==> (pf(p, q) && rk(p, q) == enc3(ta, tt, tv)),
{
    lemma_dd_pre(p);
    assert((p.adsh@[q] as int) < p.adsh__dict@.len());
    assert((p.tag@[q] as int) < p.tag__dict@.len());
    assert((p.version@[q] as int) < p.version__dict@.len());
    if cr(n, p, i0, q) {
        lemma_dd_eq(p.adsh__dict@, p.adsh@[q] as int, ta);
        lemma_dd_eq(p.tag__dict@, p.tag@[q] as int, tt);
        lemma_dd_eq(p.version__dict@, p.version@[q] as int, tv);
    }
    if pf(p, q) && rk(p, q) == enc3(ta, tt, tv) {
        lemma_enc3(p.adsh@[q] as int, p.tag@[q] as int, p.version@[q] as int, ta, tt, tv);
    }
}

proof fn lemma_chain_miss(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, ta: int, tt: int, tv: int, key: i128, lm: Map<i128, usize>)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        tf(n, p, i0, ta, tt, tv),
        key as int == enc3(ta, tt, tv),
        lm_inv(p, lm, p.n as int),
        !lm.contains_key(key),
    ensures
        forall|q: int| #![trigger cr(n, p, i0, q)] 0 <= q < p.n as int ==> !cr(n, p, i0, q),
{
    lemma_vcs_open(n, s, p);
    lemma_lm_none(p, lm, key);
    assert forall|q: int| #![trigger cr(n, p, i0, q)] 0 <= q < p.n as int implies !cr(n, p, i0, q) by {
        lemma_cr_rk(n, p, i0, q, ta, tt, tv);
    };
}

proof fn lemma_chain_hit(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, ta: int, tt: int, tv: int, key: i128, lm: Map<i128, usize>, v: usize)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        tf(n, p, i0, ta, tt, tv),
        key as int == enc3(ta, tt, tv),
        lm_inv(p, lm, p.n as int),
        lm.contains_key(key),
        lm[key] == v,
    ensures
        1 <= v as int,
        v as int <= p.n as int,
        cr(n, p, i0, v as int - 1),
        forall|c: int| #![trigger cr(n, p, i0, c)] v as int <= c < p.n as int ==> !cr(n, p, i0, c),
{
    lemma_vcs_open(n, s, p);
    lemma_lm_some(p, lm, key, v);
    lemma_cr_rk(n, p, i0, v as int - 1, ta, tt, tv);
    assert forall|c: int| #![trigger cr(n, p, i0, c)] v as int <= c < p.n as int implies !cr(n, p, i0, c) by {
        lemma_cr_rk(n, p, i0, c, ta, tt, tv);
    };
}

proof fn lemma_chain_next(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int, ta: int, tt: int, tv: int, prv: Seq<usize>, r: int)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
        tf(n, p, i0, ta, tt, tv),
        prv_inv(p, prv, p.n as int),
        0 <= r < p.n as int,
        cr(n, p, i0, r),
    ensures
        (prv[r] as int) <= r,
        prv[r] > 0 ==> cr(n, p, i0, prv[r] as int - 1),
        forall|c: int| #![trigger cr(n, p, i0, c)] prv[r] as int <= c < r ==> !cr(n, p, i0, c),
{
    lemma_vcs_open(n, s, p);
    lemma_cr_rk(n, p, i0, r, ta, tt, tv);
    lemma_prv_get(p, prv, r);
    if prv[r] > 0 {
        lemma_cr_rk(n, p, i0, prv[r] as int - 1, ta, tt, tv);
    }
    assert forall|c: int| #![trigger cr(n, p, i0, c)] prv[r] as int <= c < r implies !cr(n, p, i0, c) by {
        lemma_cr_rk(n, p, i0, c, ta, tt, tv);
    };
}

#[verifier::opaque]
spec fn mp_ok(dp: Seq<String>, m: Map<Seq<char>, usize>, c: int) -> bool {
    &&& forall|k: Seq<char>| #![trigger m.contains_key(k)] m.contains_key(k) ==> ((m[k] as int) < c && dp[m[k] as int]@ == k)
    &&& forall|t: int| #![trigger m.contains_key(dp[t]@)] 0 <= t < c ==> m.contains_key(dp[t]@)
}

proof fn lemma_mp_init(dp: Seq<String>, m: Map<Seq<char>, usize>)
    requires
        m == Map::<Seq<char>, usize>::empty(),
    ensures
        mp_ok(dp, m, 0),
{
    reveal(mp_ok);
}

proof fn lemma_mp_step(dp: Seq<String>, m: Map<Seq<char>, usize>, m2: Map<Seq<char>, usize>, c: int, ci: usize)
    requires
        mp_ok(dp, m, c),
        0 <= c < dp.len(),
        ci as int == c,
        m2 == m.insert(dp[c]@, ci),
    ensures
        mp_ok(dp, m2, c + 1),
{
    reveal(mp_ok);
    assert forall|k: Seq<char>| #![trigger m2.contains_key(k)] m2.contains_key(k) implies ((m2[k] as int) < c + 1 && dp[m2[k] as int]@ == k) by {
        if k == dp[c]@ {
            assert(m2[k] == ci);
        } else {
            assert(m.contains_key(k));
            assert(m2[k] == m[k]);
        }
    };
    assert forall|t: int| #![trigger m2.contains_key(dp[t]@)] 0 <= t < c + 1 implies m2.contains_key(dp[t]@) by {
        if t == c {
        } else {
            assert(m.contains_key(dp[t]@));
        }
    };
}

proof fn lemma_mp_some(dp: Seq<String>, m: Map<Seq<char>, usize>, c: int, k: Seq<char>, v: usize)
    requires
        mp_ok(dp, m, c),
        m.contains_key(k),
        m[k] == v,
    ensures
        (v as int) < c,
        dp[v as int]@ == k,
{
    reveal(mp_ok);
}

proof fn lemma_mp_none(dp: Seq<String>, m: Map<Seq<char>, usize>, c: int, k: Seq<char>)
    requires
        mp_ok(dp, m, c),
        !m.contains_key(k),
    ensures
        forall|t: int| #![trigger dp[t]@] 0 <= t < c ==> dp[t]@ != k,
{
    reveal(mp_ok);
    assert forall|t: int| #![trigger dp[t]@] 0 <= t < c implies dp[t]@ != k by {
        if dp[t]@ == k {
            assert(m.contains_key(dp[t]@));
        }
    };
}

#[verifier::opaque]
spec fn sm_ok(s: &Cols_sub, m: Map<Seq<char>, usize>, c: int) -> bool {
    &&& forall|k: Seq<char>| #![trigger m.contains_key(k)] m.contains_key(k) ==> ((m[k] as int) < c && sf(s, m[k] as int) && s.adsh__dict@[s.adsh@[m[k] as int] as int]@ == k)
    &&& forall|t: int| #![trigger m.contains_key(s.adsh__dict@[s.adsh@[t] as int]@)] 0 <= t < c && sf(s, t) ==> m.contains_key(s.adsh__dict@[s.adsh@[t] as int]@)
}

proof fn lemma_sm_init(s: &Cols_sub, m: Map<Seq<char>, usize>)
    requires
        m == Map::<Seq<char>, usize>::empty(),
    ensures
        sm_ok(s, m, 0),
{
    reveal(sm_ok);
}

proof fn lemma_sm_hit(s: &Cols_sub, m: Map<Seq<char>, usize>, m2: Map<Seq<char>, usize>, c: int, ci: usize)
    requires
        sm_ok(s, m, c),
        0 <= c < s.n as int,
        sf(s, c),
        ci as int == c,
        m2 == m.insert(s.adsh__dict@[s.adsh@[c] as int]@, ci),
    ensures
        sm_ok(s, m2, c + 1),
{
    reveal(sm_ok);
    assert forall|k: Seq<char>| #![trigger m2.contains_key(k)] m2.contains_key(k) implies ((m2[k] as int) < c + 1 && sf(s, m2[k] as int) && s.adsh__dict@[s.adsh@[m2[k] as int] as int]@ == k) by {
        if k == s.adsh__dict@[s.adsh@[c] as int]@ {
            assert(m2[k] == ci);
        } else {
            assert(m.contains_key(k));
            assert(m2[k] == m[k]);
        }
    };
    assert forall|t: int| #![trigger m2.contains_key(s.adsh__dict@[s.adsh@[t] as int]@)] 0 <= t < c + 1 && sf(s, t) implies m2.contains_key(s.adsh__dict@[s.adsh@[t] as int]@) by {
        if t == c {
        } else {
            assert(m.contains_key(s.adsh__dict@[s.adsh@[t] as int]@));
        }
    };
}

proof fn lemma_sm_nohit(s: &Cols_sub, m: Map<Seq<char>, usize>, c: int)
    requires
        sm_ok(s, m, c),
        0 <= c < s.n as int,
        !sf(s, c),
    ensures
        sm_ok(s, m, c + 1),
{
    reveal(sm_ok);
}

proof fn lemma_sm_some(s: &Cols_sub, m: Map<Seq<char>, usize>, c: int, k: Seq<char>, v: usize)
    requires
        sm_ok(s, m, c),
        m.contains_key(k),
        m[k] == v,
    ensures
        (v as int) < c,
        sf(s, v as int),
        s.adsh__dict@[s.adsh@[v as int] as int]@ == k,
{
    reveal(sm_ok);
}

proof fn lemma_sm_none(s: &Cols_sub, m: Map<Seq<char>, usize>, c: int, k: Seq<char>)
    requires
        sm_ok(s, m, c),
        !m.contains_key(k),
    ensures
        forall|t: int| #![trigger sf(s, t)] 0 <= t < c && sf(s, t) ==> s.adsh__dict@[s.adsh@[t] as int]@ != k,
{
    reveal(sm_ok);
    assert forall|t: int| #![trigger sf(s, t)] 0 <= t < c && sf(s, t) implies s.adsh__dict@[s.adsh@[t] as int]@ != k by {
        if s.adsh__dict@[s.adsh@[t] as int]@ == k {
            assert(m.contains_key(s.adsh__dict@[s.adsh@[t] as int]@));
        }
    };
}

proof fn lemma_newgroup_distinct(nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, e: i128, snm: usize, tgc: u32, pev: u64)
    requires
        forall|g: int| #![trigger nm[g]] 0 <= g < nm.len() ==> enc3(nm[g] as int, tg[g] as int, pe[g] as int) != e as int,
        e as int == enc3(snm as int, tgc as int, pev as int),
        tg.len() == nm.len(),
        pe.len() == nm.len(),
    ensures
        forall|g: int| #![trigger nm[g]] 0 <= g < nm.len() ==> !(nm[g] == snm && tg[g] == tgc && pe[g] == pev),
{
}

proof fn lemma_row_facts_n(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, i0: int)
    requires
        vcs(n, s, p),
        0 <= i0 < n.n as int,
    ensures
        n.uom@.len() == n.n as int,
        n.adsh@.len() == n.n as int,
        n.tag@.len() == n.n as int,
        n.version@.len() == n.n as int,
        n.value@.len() == n.n as int,
        s.name@.len() == s.n as int,
        (n.adsh@[i0] as int) < n.adsh__dict@.len(),
        (n.tag@[i0] as int) < n.tag__dict@.len(),
        (n.version@[i0] as int) < n.version__dict@.len(),
{
    lemma_vcs_open(n, s, p);
}

proof fn lemma_row_facts_p(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, r: int)
    requires
        vcs(n, s, p),
        0 <= r < p.n as int,
    ensures
        p.plabel__valid@.len() == p.n as int,
        p.plabel@.len() == p.n as int,
{
    lemma_vcs_open(n, s, p);
}

spec fn cidx(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, res: Seq<OutRow>, i0: int, i1: int, i2: int) -> int {
    choose|r: int| 0 <= r < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r])
}

#[verifier::opaque]
spec fn sel_ok(sel: Seq<usize>, used: Seq<bool>, sm: Seq<i128>, glen: int) -> bool {
    &&& used.len() == glen
    &&& sm.len() == glen
    &&& sel.len() <= 200
    &&& forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> (sel[r] as int) < glen
    &&& forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() ==> sel[a] != sel[b]
    &&& forall|g: int| #![trigger used[g]] 0 <= g < glen ==> (used[g] <==> exists|r: int| #![trigger sel[r]] 0 <= r < sel.len() && sel[r] as int == g)
    &&& forall|i: int| #![trigger sel[i]] 0 <= i && i + 1 < sel.len() ==> sm[sel[i] as int] >= sm[sel[i + 1] as int]
    &&& forall|g: int, r: int| #![trigger used[g], sel[r]] 0 <= g < glen && !used[g] && 0 <= r < sel.len() ==> sm[g] <= sm[sel[r] as int]
}

proof fn lemma_sel_init(used: Seq<bool>, sm: Seq<i128>, glen: int)
    requires
        used.len() == glen,
        sm.len() == glen,
        forall|x: int| #![trigger used[x]] 0 <= x < glen ==> !used[x],
    ensures
        sel_ok(Seq::<usize>::empty(), used, sm, glen),
{
    reveal(sel_ok);
}

proof fn lemma_sel_get(sel: Seq<usize>, used: Seq<bool>, sm: Seq<i128>, glen: int, x: int)
    requires
        sel_ok(sel, used, sm, glen),
        0 <= x < sel.len(),
    ensures
        (sel[x] as int) < glen,
        used.len() == glen,
        sm.len() == glen,
        sel.len() <= 200,
{
    reveal(sel_ok);
}

proof fn lemma_sel_push(sel: Seq<usize>, used: Seq<bool>, sm: Seq<i128>, glen: int, bi: usize, sel2: Seq<usize>, used2: Seq<bool>)
    requires
        sel_ok(sel, used, sm, glen),
        sel.len() < 200,
        (bi as int) < glen,
        !used[bi as int],
        forall|t: int| #![trigger used[t]] 0 <= t < glen ==> (used[t] || sm[t] <= sm[bi as int]),
        sel2 == sel.push(bi),
        used2 == used.update(bi as int, true),
    ensures
        sel_ok(sel2, used2, sm, glen),
{
    reveal(sel_ok);
    assert forall|r: int| #![trigger sel2[r]] 0 <= r < sel2.len() implies (sel2[r] as int) < glen by {
        if r < sel.len() {
            assert(sel2[r] == sel[r]);
        }
    };
    assert forall|g: int| #![trigger used2[g]] 0 <= g < glen implies (used2[g] <==> exists|r: int| #![trigger sel2[r]] 0 <= r < sel2.len() && sel2[r] as int == g) by {
        if g == bi as int {
            assert(sel2[sel.len() as int] as int == g);
        } else {
            assert(used2[g] == used[g]);
            if used[g] {
                let r0 = choose|r: int| 0 <= r < sel.len() && sel[r] as int == g;
                assert(sel2[r0] as int == g);
            }
            if exists|r: int| 0 <= r < sel2.len() && sel2[r] as int == g {
                let r1 = choose|r: int| 0 <= r < sel2.len() && sel2[r] as int == g;
                assert(r1 < sel.len());
                assert(sel[r1] as int == g);
            }
        }
    };
    assert forall|a: int, b: int| #![trigger sel2[a], sel2[b]] 0 <= a < b < sel2.len() implies sel2[a] != sel2[b] by {
        if b == sel.len() as int {
            assert(sel2[b] == bi);
            assert(sel2[a] == sel[a]);
            if sel2[a] == bi {
                assert(used[bi as int]);
            }
        }
    };
    assert forall|i: int| #![trigger sel2[i]] 0 <= i && i + 1 < sel2.len() implies sm[sel2[i] as int] >= sm[sel2[i + 1] as int] by {
        if i + 1 == sel.len() as int {
            assert(sel2[i] == sel[i]);
            assert(sel2[i + 1] == bi);
        } else {
            assert(sel2[i] == sel[i]);
            assert(sel2[i + 1] == sel[i + 1]);
        }
    };
    assert forall|g: int, r: int| #![trigger used2[g], sel2[r]] 0 <= g < glen && !used2[g] && 0 <= r < sel2.len() implies sm[g] <= sm[sel2[r] as int] by {
        assert(g != bi as int);
        assert(used2[g] == used[g]);
        if r < sel.len() {
            assert(sel2[r] == sel[r]);
        } else {
            assert(sel2[r] == bi);
        }
    };
}

#[verifier::opaque]
spec fn res_ok(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>, sel: Seq<usize>, res: Seq<OutRow>, x: int) -> bool {
    &&& res.len() == x
    &&& x <= sel.len()
    &&& forall|r: int| #![trigger res[r]] 0 <= r < x ==> (res[r].total_value == sm[sel[r] as int] && res[r].cnt == ct[sel[r] as int] && okey(res[r]) == gk(n, s, p, nm, tg, pe, sel[r] as int))
}

proof fn lemma_res_init(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>, sel: Seq<usize>, res: Seq<OutRow>)
    requires
        res == Seq::<OutRow>::empty(),
    ensures
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, 0),
{
    reveal(res_ok);
}

proof fn lemma_res_push(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>, sel: Seq<usize>, res: Seq<OutRow>, x: int, row: OutRow, res2: Seq<OutRow>)
    requires
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, x),
        x < sel.len(),
        row.total_value == sm[sel[x] as int],
        row.cnt == ct[sel[x] as int],
        okey(row) == gk(n, s, p, nm, tg, pe, sel[x] as int),
        res2 == res.push(row),
    ensures
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res2, x + 1),
{
    reveal(res_ok);
    assert forall|r: int| #![trigger res2[r]] 0 <= r < x + 1 implies (res2[r].total_value == sm[sel[r] as int] && res2[r].cnt == ct[sel[r] as int] && okey(res2[r]) == gk(n, s, p, nm, tg, pe, sel[r] as int)) by {
        if r < x {
            assert(res2[r] == res[r]);
        } else {
            assert(res2[r] == row);
        }
    };
}

#[verifier::opaque]
spec fn f1_ok(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>) -> bool {
    forall|g: int| #![trigger sm[g]] 0 <= g < nm.len() ==> (sm[g] as int == sum_total_value(n, s, p, 0, gk(n, s, p, nm, tg, pe, g)) && ct[g] as int == count_cnt(n, s, p, 0, gk(n, s, p, nm, tg, pe, g)))
}

proof fn lemma_fin_sums(n: &Cols_num, s: &Cols_sub, p: &Cols_pre, nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>)
    requires
        g_sums(n, s, p, -1int, 0, p.n as int, nm, tg, pe, sm, ct),
    ensures
        f1_ok(n, s, p, nm, tg, pe, sm, ct),
{
    reveal(g_sums);
    reveal(f1_ok);
    assert forall|g: int| #![trigger sm[g]] 0 <= g < nm.len() implies (sm[g] as int == sum_total_value(n, s, p, 0, gk(n, s, p, nm, tg, pe, g)) && ct[g] as int == count_cnt(n, s, p, 0, gk(n, s, p, nm, tg, pe, g))) by {
        let k = gk(n, s, p, nm, tg, pe, g);
        lemma_d2_end(n, s, p, -1int, 0, p.n as int, k);
        assert(gs_one(n, s, p, -1int, 0, p.n as int, k, sm[g] as int, ct[g] as int));
    };
}

proof fn lemma_fin_e1(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        g_wit(n, s, p, nm, tg, pe),
        f1_ok(n, s, p, nm, tg, pe, sm, ct),
        sel_ok(sel, used, sm, nm.len() as int),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, s, p, res[r]),
{
    reveal(g_wit);
    reveal(f1_ok);
    reveal(sel_ok);
    reveal(res_ok);
    assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(n, s, p, res[r]) by {
        let g = sel[r] as int;
        assert(wit_one(n, s, p, nm, tg, pe, g));
        let t = choose|a: int, b: int, c: int| row_hit(n, s, p, a, b, c) && key_at(n, s, p, a, b, c) == gk(n, s, p, nm, tg, pe, g);
        assert(okey(res[r]) == gk(n, s, p, nm, tg, pe, g));
        assert(res[r].total_value as int == sum_total_value(n, s, p, 0, okey(res[r])));
        assert(res[r].cnt as int == count_cnt(n, s, p, 0, okey(res[r])));
        assert(row_hit(n, s, p, t.0, t.1, t.2) && key_at(n, s, p, t.0, t.1, t.2) == okey(res[r]));
    };
}

proof fn lemma_fin_e2(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
        valid_cols_pre(p),
        g_shape(n, s, p, nm, tg, pe),
        sel_ok(sel, used, sm, nm.len() as int),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> (res[a].name@, (if res[a].stmt is Some { (true, res[a].stmt->Some_0@) } else { (false, Seq::<char>::empty()) }), res[a].tag@, (if res[a].plabel is Some { (true, res[a].plabel->Some_0@) } else { (false, Seq::<char>::empty()) })) != (res[b].name@, (if res[b].stmt is Some { (true, res[b].stmt->Some_0@) } else { (false, Seq::<char>::empty()) }), res[b].tag@, (if res[b].plabel is Some { (true, res[b].plabel->Some_0@) } else { (false, Seq::<char>::empty()) })),
{
    reveal(sel_ok);
    reveal(res_ok);
    assert forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() implies (res[a].name@, (if res[a].stmt is Some { (true, res[a].stmt->Some_0@) } else { (false, Seq::<char>::empty()) }), res[a].tag@, (if res[a].plabel is Some { (true, res[a].plabel->Some_0@) } else { (false, Seq::<char>::empty()) })) != (res[b].name@, (if res[b].stmt is Some { (true, res[b].stmt->Some_0@) } else { (false, Seq::<char>::empty()) }), res[b].tag@, (if res[b].plabel is Some { (true, res[b].plabel->Some_0@) } else { (false, Seq::<char>::empty()) })) by {
        lemma_gk_ne(n, s, p, nm, tg, pe, sel[a] as int, sel[b] as int);
        assert(okey(res[a]) == gk(n, s, p, nm, tg, pe, sel[a] as int));
        assert(okey(res[b]) == gk(n, s, p, nm, tg, pe, sel[b] as int));
    };
}

proof fn lemma_fin_e3(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        g_cov(n, s, p, -1int, p.n as int, nm, tg, pe),
        sel_ok(sel, used, sm, nm.len() as int),
        (sel.len() == 200) || (forall|g: int| #![trigger used[g]] 0 <= g < nm.len() ==> used[g]),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        (res.len() == 200) || (forall|i0: int, i1: int, i2: int| #![trigger row_hit(n, s, p, i0, i1, i2)] row_hit(n, s, p, i0, i1, i2) && (true) ==> (0 <= cidx(n, s, p, res, i0, i1, i2) < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[cidx(n, s, p, res, i0, i1, i2)]))),
{
    reveal(g_cov);
    reveal(sel_ok);
    reveal(res_ok);
    if res.len() != 200 {
        assert(sel.len() != 200);
        assert forall|i0: int, i1: int, i2: int| #![trigger row_hit(n, s, p, i0, i1, i2)] row_hit(n, s, p, i0, i1, i2) && (true) implies (0 <= cidx(n, s, p, res, i0, i1, i2) < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[cidx(n, s, p, res, i0, i1, i2)])) by {
            lemma_hit_iff(n, s, p, i0, i1, i2);
            assert(cov_one(n, s, p, nm, tg, pe, i0, i1, i2));
            let g = choose|g: int| 0 <= g < nm.len() && gk(n, s, p, nm, tg, pe, g) == key_at(n, s, p, i0, i1, i2);
            assert(used[g]);
            let r = choose|r: int| 0 <= r < sel.len() && sel[r] as int == g;
            assert(okey(res[r]) == gk(n, s, p, nm, tg, pe, sel[r] as int));
            assert(0 <= r < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r]));
            assert(exists|r2: int| 0 <= r2 < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r2]));
        };
    }
}

proof fn lemma_fin_col(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
        valid_cols_pre(p),
        g_shape(n, s, p, nm, tg, pe),
        sel_ok(sel, used, sm, nm.len() as int),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        forall|i0: int, i1: int, i2: int, r: int| #![trigger row_hit(n, s, p, i0, i1, i2), res[r]] row_hit(n, s, p, i0, i1, i2) && 0 <= r < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r]) ==> cidx(n, s, p, res, i0, i1, i2) == r,
{
    reveal(sel_ok);
    reveal(res_ok);
    assert forall|i0: int, i1: int, i2: int, r: int| #![trigger row_hit(n, s, p, i0, i1, i2), res[r]] row_hit(n, s, p, i0, i1, i2) && 0 <= r < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r]) implies cidx(n, s, p, res, i0, i1, i2) == r by {
        assert(exists|r2: int| 0 <= r2 < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r2]));
        let r2 = cidx(n, s, p, res, i0, i1, i2);
        assert(0 <= r2 < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r2]));
        assert(okey(res[r]) == gk(n, s, p, nm, tg, pe, sel[r] as int));
        assert(okey(res[r2]) == gk(n, s, p, nm, tg, pe, sel[r2] as int));
        if r != r2 {
            if r < r2 {
                assert(sel[r] != sel[r2]);
            } else {
                assert(sel[r2] != sel[r]);
            }
            lemma_gk_ne(n, s, p, nm, tg, pe, sel[r] as int, sel[r2] as int);
        }
    };
}

proof fn lemma_fin_e4(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        g_cov(n, s, p, -1int, p.n as int, nm, tg, pe),
        f1_ok(n, s, p, nm, tg, pe, sm, ct),
        sel_ok(sel, used, sm, nm.len() as int),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        forall|i0: int, i1: int, i2: int, r: int| #![trigger row_hit(n, s, p, i0, i1, i2), res[r]] row_hit(n, s, p, i0, i1, i2) && (true) && 0 <= r < res.len() && ((res[r].total_value as int) < sum_total_value(n, s, p, 0, key_at(n, s, p, i0, i1, i2))) ==> (0 <= cidx(n, s, p, res, i0, i1, i2) < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[cidx(n, s, p, res, i0, i1, i2)])),
{
    reveal(g_cov);
    reveal(f1_ok);
    reveal(sel_ok);
    reveal(res_ok);
    assert forall|i0: int, i1: int, i2: int, r: int| #![trigger row_hit(n, s, p, i0, i1, i2), res[r]] row_hit(n, s, p, i0, i1, i2) && (true) && 0 <= r < res.len() && ((res[r].total_value as int) < sum_total_value(n, s, p, 0, key_at(n, s, p, i0, i1, i2))) implies (0 <= cidx(n, s, p, res, i0, i1, i2) < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[cidx(n, s, p, res, i0, i1, i2)])) by {
        lemma_hit_iff(n, s, p, i0, i1, i2);
        assert(cov_one(n, s, p, nm, tg, pe, i0, i1, i2));
        let g = choose|g: int| 0 <= g < nm.len() && gk(n, s, p, nm, tg, pe, g) == key_at(n, s, p, i0, i1, i2);
        if !used[g] {
            assert(sm[g] <= sm[sel[r] as int]);
            assert(false);
        }
        let r2 = choose|r2: int| 0 <= r2 < sel.len() && sel[r2] as int == g;
        assert(okey(res[r2]) == gk(n, s, p, nm, tg, pe, sel[r2] as int));
        assert(0 <= r2 < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r2]));
        assert(exists|r3: int| 0 <= r3 < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r3]));
    };
}

proof fn lemma_fin_e5(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        sel_ok(sel, used, sm, nm.len() as int),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        forall|i: int| #![trigger res[i], res[i + 1]] 0 <= i && i + 1 < res.len() ==> ((res[i].total_value) >= (res[i + 1].total_value)),
        res.len() <= 200,
{
    reveal(sel_ok);
    reveal(res_ok);
    assert forall|i: int| #![trigger res[i], res[i + 1]] 0 <= i && i + 1 < res.len() implies ((res[i].total_value) >= (res[i + 1].total_value)) by {
        assert(res[i].total_value == sm[sel[i] as int]);
        assert(res[i + 1].total_value == sm[sel[i + 1] as int]);
    };
}

proof fn lemma_post_a(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
        valid_cols_pre(p),
        g_shape(n, s, p, nm, tg, pe),
        g_sums(n, s, p, -1int, 0, p.n as int, nm, tg, pe, sm, ct),
        g_wit(n, s, p, nm, tg, pe),
        sel_ok(sel, used, sm, nm.len() as int),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, s, p, res[r]),
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> (res[a].name@, (if res[a].stmt is Some { (true, res[a].stmt->Some_0@) } else { (false, Seq::<char>::empty()) }), res[a].tag@, (if res[a].plabel is Some { (true, res[a].plabel->Some_0@) } else { (false, Seq::<char>::empty()) })) != (res[b].name@, (if res[b].stmt is Some { (true, res[b].stmt->Some_0@) } else { (false, Seq::<char>::empty()) }), res[b].tag@, (if res[b].plabel is Some { (true, res[b].plabel->Some_0@) } else { (false, Seq::<char>::empty()) })),
{
    lemma_fin_sums(n, s, p, nm, tg, pe, sm, ct);
    lemma_fin_e1(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
    lemma_fin_e2(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
}

proof fn lemma_post_b(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        g_cov(n, s, p, -1int, p.n as int, nm, tg, pe),
        sel_ok(sel, used, sm, nm.len() as int),
        (sel.len() == 200) || (forall|g: int| #![trigger used[g]] 0 <= g < nm.len() ==> used[g]),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        (res.len() == 200) || (forall|i0: int, i1: int, i2: int| #![trigger row_hit(n, s, p, i0, i1, i2)] row_hit(n, s, p, i0, i1, i2) && (true) ==> (0 <= cidx(n, s, p, res, i0, i1, i2) < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[cidx(n, s, p, res, i0, i1, i2)]))),
{
    lemma_fin_e3(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
}

proof fn lemma_post_c(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        g_sums(n, s, p, -1int, 0, p.n as int, nm, tg, pe, sm, ct),
        g_cov(n, s, p, -1int, p.n as int, nm, tg, pe),
        sel_ok(sel, used, sm, nm.len() as int),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        forall|i0: int, i1: int, i2: int, r: int| #![trigger row_hit(n, s, p, i0, i1, i2), res[r]] row_hit(n, s, p, i0, i1, i2) && (true) && 0 <= r < res.len() && ((res[r].total_value as int) < sum_total_value(n, s, p, 0, key_at(n, s, p, i0, i1, i2))) ==> (0 <= cidx(n, s, p, res, i0, i1, i2) < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[cidx(n, s, p, res, i0, i1, i2)])),
{
    lemma_fin_sums(n, s, p, nm, tg, pe, sm, ct);
    lemma_fin_e4(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
}

proof fn lemma_post_d(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        sel_ok(sel, used, sm, nm.len() as int),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        forall|i: int| #![trigger res[i], res[i + 1]] 0 <= i && i + 1 < res.len() ==> ((res[i].total_value) >= (res[i + 1].total_value)),
        res.len() <= 200,
{
    lemma_fin_e5(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
}

#[verifier::rlimit(30)]
proof fn lemma_final_all(
    n: &Cols_num, s: &Cols_sub, p: &Cols_pre,
    nm: Seq<usize>, tg: Seq<u32>, pe: Seq<u64>, sm: Seq<i128>, ct: Seq<u64>,
    sel: Seq<usize>, used: Seq<bool>, res: Seq<OutRow>,
)
    requires
        vcs(n, s, p),
        g_shape(n, s, p, nm, tg, pe),
        g_sums(n, s, p, -1int, 0, p.n as int, nm, tg, pe, sm, ct),
        g_cov(n, s, p, -1int, p.n as int, nm, tg, pe),
        g_wit(n, s, p, nm, tg, pe),
        sel_ok(sel, used, sm, nm.len() as int),
        (sel.len() == 200) || (forall|g: int| #![trigger used[g]] 0 <= g < nm.len() ==> used[g]),
        res_ok(n, s, p, nm, tg, pe, sm, ct, sel, res, sel.len() as int),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, s, p, res[r]),
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> (res[a].name@, (if res[a].stmt is Some { (true, res[a].stmt->Some_0@) } else { (false, Seq::<char>::empty()) }), res[a].tag@, (if res[a].plabel is Some { (true, res[a].plabel->Some_0@) } else { (false, Seq::<char>::empty()) })) != (res[b].name@, (if res[b].stmt is Some { (true, res[b].stmt->Some_0@) } else { (false, Seq::<char>::empty()) }), res[b].tag@, (if res[b].plabel is Some { (true, res[b].plabel->Some_0@) } else { (false, Seq::<char>::empty()) })),
        (res.len() == 200) || (forall|i0: int, i1: int, i2: int| #![trigger row_hit(n, s, p, i0, i1, i2)] row_hit(n, s, p, i0, i1, i2) && (true) ==> (0 <= cidx(n, s, p, res, i0, i1, i2) < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[cidx(n, s, p, res, i0, i1, i2)]))),
        forall|i0: int, i1: int, i2: int, r: int| #![trigger row_hit(n, s, p, i0, i1, i2), res[r]] row_hit(n, s, p, i0, i1, i2) && 0 <= r < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[r]) ==> cidx(n, s, p, res, i0, i1, i2) == r,
        forall|i0: int, i1: int, i2: int, r: int| #![trigger row_hit(n, s, p, i0, i1, i2), res[r]] row_hit(n, s, p, i0, i1, i2) && (true) && 0 <= r < res.len() && ((res[r].total_value as int) < sum_total_value(n, s, p, 0, key_at(n, s, p, i0, i1, i2))) ==> (0 <= cidx(n, s, p, res, i0, i1, i2) < res.len() && key_at(n, s, p, i0, i1, i2) == okey(res[cidx(n, s, p, res, i0, i1, i2)])),
        forall|i: int| #![trigger res[i], res[i + 1]] 0 <= i && i + 1 < res.len() ==> ((res[i].total_value) >= (res[i + 1].total_value)),
        res.len() <= 200,
{
    lemma_vcs_open(n, s, p);
    lemma_post_a(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
    lemma_post_b(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
    lemma_post_c(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
    lemma_post_d(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
    lemma_fin_col(n, s, p, nm, tg, pe, sm, ct, sel, used, res);
}

proof fn lemma_sel_len(sel: Seq<usize>, used: Seq<bool>, sm: Seq<i128>, glen: int)
    requires
        sel_ok(sel, used, sm, glen),
    ensures
        sel.len() <= 200,
        used.len() == glen,
        sm.len() == glen,
{
    reveal(sel_ok);
}

// AGENT_HELPERS_END
// AGENT_EDIT_START

    proof {
        lemma_vcs_close(n, s, p);
    }
    // ===== literal codes =====
    let usd: String = String::from_str("USD");
    let mut ucode: usize = 0;
    let mut ufound: bool = false;
    let mut kk: usize = 0;
    while kk < n.uom__dict.len()
        invariant
            kk <= n.uom__dict@.len(),
            usd@ == "USD"@,
            vcs(n, s, p),
            ufound ==> ucode < kk && n.uom__dict@[ucode as int]@ == "USD"@,
            !ufound ==> forall|m: int| 0 <= m < kk as int ==> n.uom__dict@[m]@ != "USD"@,
        decreases n.uom__dict@.len() - kk,
    {
        if !ufound && n.uom__dict[kk] == usd {
            ufound = true;
            ucode = kk;
        }
        kk += 1;
    }
    proof {
        lemma_dd_num(n);
        assert forall|i0: int| #![trigger nf(n, i0)] 0 <= i0 < n.n as int implies (nf(n, i0) <==> (ufound && n.uom@[i0] as int == ucode as int)) by {
            assert((n.uom@[i0] as int) < n.uom__dict@.len());
            lemma_lit_code(n.uom__dict@, "USD"@, ufound, ucode as int, n.uom@[i0] as int);
        };
    }
    let isl: String = String::from_str("IS");
    let mut scode: usize = 0;
    let mut sfound: bool = false;
    let mut kk2: usize = 0;
    while kk2 < p.stmt__dict.len()
        invariant
            kk2 <= p.stmt__dict@.len(),
            isl@ == "IS"@,
            vcs(n, s, p),
            sfound ==> scode < kk2 && p.stmt__dict@[scode as int]@ == "IS"@,
            !sfound ==> forall|m: int| 0 <= m < kk2 as int ==> p.stmt__dict@[m]@ != "IS"@,
        decreases p.stmt__dict@.len() - kk2,
    {
        if !sfound && p.stmt__dict[kk2] == isl {
            sfound = true;
            scode = kk2;
        }
        kk2 += 1;
    }
    proof {
        lemma_dd_pre(p);
        assert forall|q: int| #![trigger pf(p, q)] 0 <= q < p.n as int implies (pf(p, q) <==> (p.stmt__valid@[q] && sfound && p.stmt@[q] as int == scode as int)) by {
            assert((p.stmt@[q] as int) < p.stmt__dict@.len());
            lemma_lit_code(p.stmt__dict@, "IS"@, sfound, scode as int, p.stmt@[q] as int);
        };
    }

    // ===== sub rows of fy 2023: adsh string -> row =====
    let mut smap: StringHashMap<usize> = StringHashMap::new();
    proof {
        lemma_sm_init(s, smap@);
    }
    let mut jj: usize = 0;
    while jj < s.n
        invariant
            jj <= s.n,
            vcs(n, s, p),
            sm_ok(s, smap@, jj as int),
        decreases s.n - jj,
    {
        proof {
            lemma_vcs_open(n, s, p);
            assert(s.fy@.len() == s.n as int);
            assert(s.fy__valid@.len() == s.n as int);
            assert(s.adsh@.len() == s.n as int);
            assert((s.adsh@[jj as int] as int) < s.adsh__dict@.len());
        }
        let hit: bool = s.fy__valid[jj] && s.fy[jj] == 2023;
        proof {
            assert(hit == sf(s, jj as int));
        }
        if hit {
            let ac: usize = s.adsh[jj] as usize;
            let key: String = s.adsh__dict[ac].clone();
            let ghost old = smap@;
            smap.insert(key, jj);
            proof {
                lemma_sm_hit(s, old, smap@, jj as int, jj);
            }
        } else {
            proof {
                lemma_sm_nohit(s, smap@, jj as int);
            }
        }
        jj += 1;
    }
    let nca: usize = n.adsh__dict.len();
    let mut tsub: Vec<usize> = Vec::new();
    proof {
        lemma_ts_init(s, n.adsh__dict@, tsub@);
    }
    let mut dsb: usize = 0;
    while dsb < nca
        invariant
            dsb <= nca,
            nca == n.adsh__dict@.len(),
            vcs(n, s, p),
            sm_ok(s, smap@, s.n as int),
            ts_ok(s, n.adsh__dict@, tsub@, dsb as int),
        decreases nca - dsb,
    {
        proof {
            lemma_vcs_open(n, s, p);
        }
        let fc = smap.get(n.adsh__dict[dsb].as_str());
        let ghost old_ts = tsub@;
        match fc {
            Some(v) => {
                let vv: usize = *v;
                proof {
                    lemma_sm_some(s, smap@, s.n as int, n.adsh__dict@[dsb as int]@, vv);
                }
                tsub.push(vv + 1);
                proof {
                    lemma_ts_some(s, n.adsh__dict@, old_ts, dsb as int, vv, (vv + 1) as usize);
                }
            }
            None => {
                proof {
                    lemma_sm_none(s, smap@, s.n as int, n.adsh__dict@[dsb as int]@);
                    lemma_ts_none(s, n.adsh__dict@, old_ts, dsb as int);
                }
                tsub.push(0);
            }
        }
        dsb += 1;
    }

    // translation of n.adsh__dict entries into p.adsh__dict codes
    let pca: usize = p.adsh__dict.len();
    let mut amap: StringHashMap<usize> = StringHashMap::new();
    proof {
        lemma_mp_init(p.adsh__dict@, amap@);
    }
    let mut ca: usize = 0;
    while ca < pca
        invariant
            ca <= pca,
            pca == p.adsh__dict@.len(),
            vcs(n, s, p),
            mp_ok(p.adsh__dict@, amap@, ca as int),
        decreases pca - ca,
    {
        let key: String = p.adsh__dict[ca].clone();
        let ghost old = amap@;
        amap.insert(key, ca);
        proof {
            lemma_mp_step(p.adsh__dict@, old, amap@, ca as int, ca);
        }
        ca += 1;
    }
    let nca: usize = n.adsh__dict.len();
    let mut ta: Vec<u64> = Vec::new();
    proof {
        lemma_tr_init(p.adsh__dict@, n.adsh__dict@, ta@);
        lemma_dd_pre(p);
    }
    let mut da: usize = 0;
    while da < nca
        invariant
            da <= nca,
            nca == n.adsh__dict@.len(),
            pca == p.adsh__dict@.len(),
            vcs(n, s, p),
            dd(p.adsh__dict@),
            mp_ok(p.adsh__dict@, amap@, pca as int),
            tr_ok(p.adsh__dict@, n.adsh__dict@, ta@, da as int),
        decreases nca - da,
    {
        let fc = amap.get(n.adsh__dict[da].as_str());
        let ghost old_t = ta@;
        match fc {
            Some(v) => {
                let vv: usize = *v;
                proof {
                    lemma_mp_some(p.adsh__dict@, amap@, pca as int, n.adsh__dict@[da as int]@, vv);
                }
                if (vv as u64) < 4294967296u64 {
                    ta.push((vv as u64) + 1);
                    proof {
                        lemma_tr_some(p.adsh__dict@, n.adsh__dict@, old_t, da as int, vv, ((vv as u64) + 1) as u64);
                    }
                } else {
                    ta.push(0);
                    proof {
                        lemma_tr_big(p.adsh__dict@, n.adsh__dict@, old_t, da as int, vv);
                    }
                }
            }
            None => {
                proof {
                    lemma_mp_none(p.adsh__dict@, amap@, pca as int, n.adsh__dict@[da as int]@);
                    lemma_tr_none(p.adsh__dict@, n.adsh__dict@, old_t, da as int);
                }
                ta.push(0);
            }
        }
        da += 1;
    }

    // translation of n.tag__dict entries into p.tag__dict codes
    let pct: usize = p.tag__dict.len();
    let mut tmap: StringHashMap<usize> = StringHashMap::new();
    proof {
        lemma_mp_init(p.tag__dict@, tmap@);
    }
    let mut ct: usize = 0;
    while ct < pct
        invariant
            ct <= pct,
            pct == p.tag__dict@.len(),
            vcs(n, s, p),
            mp_ok(p.tag__dict@, tmap@, ct as int),
        decreases pct - ct,
    {
        let key: String = p.tag__dict[ct].clone();
        let ghost old = tmap@;
        tmap.insert(key, ct);
        proof {
            lemma_mp_step(p.tag__dict@, old, tmap@, ct as int, ct);
        }
        ct += 1;
    }
    let nct: usize = n.tag__dict.len();
    let mut tt: Vec<u64> = Vec::new();
    proof {
        lemma_tr_init(p.tag__dict@, n.tag__dict@, tt@);
        lemma_dd_pre(p);
    }
    let mut dt: usize = 0;
    while dt < nct
        invariant
            dt <= nct,
            nct == n.tag__dict@.len(),
            pct == p.tag__dict@.len(),
            vcs(n, s, p),
            dd(p.tag__dict@),
            mp_ok(p.tag__dict@, tmap@, pct as int),
            tr_ok(p.tag__dict@, n.tag__dict@, tt@, dt as int),
        decreases nct - dt,
    {
        let fc = tmap.get(n.tag__dict[dt].as_str());
        let ghost old_t = tt@;
        match fc {
            Some(v) => {
                let vv: usize = *v;
                proof {
                    lemma_mp_some(p.tag__dict@, tmap@, pct as int, n.tag__dict@[dt as int]@, vv);
                }
                if (vv as u64) < 4294967296u64 {
                    tt.push((vv as u64) + 1);
                    proof {
                        lemma_tr_some(p.tag__dict@, n.tag__dict@, old_t, dt as int, vv, ((vv as u64) + 1) as u64);
                    }
                } else {
                    tt.push(0);
                    proof {
                        lemma_tr_big(p.tag__dict@, n.tag__dict@, old_t, dt as int, vv);
                    }
                }
            }
            None => {
                proof {
                    lemma_mp_none(p.tag__dict@, tmap@, pct as int, n.tag__dict@[dt as int]@);
                    lemma_tr_none(p.tag__dict@, n.tag__dict@, old_t, dt as int);
                }
                tt.push(0);
            }
        }
        dt += 1;
    }

    // translation of n.version__dict entries into p.version__dict codes
    let pcv: usize = p.version__dict.len();
    let mut vmap: StringHashMap<usize> = StringHashMap::new();
    proof {
        lemma_mp_init(p.version__dict@, vmap@);
    }
    let mut cv: usize = 0;
    while cv < pcv
        invariant
            cv <= pcv,
            pcv == p.version__dict@.len(),
            vcs(n, s, p),
            mp_ok(p.version__dict@, vmap@, cv as int),
        decreases pcv - cv,
    {
        let key: String = p.version__dict[cv].clone();
        let ghost old = vmap@;
        vmap.insert(key, cv);
        proof {
            lemma_mp_step(p.version__dict@, old, vmap@, cv as int, cv);
        }
        cv += 1;
    }
    let ncv: usize = n.version__dict.len();
    let mut tv: Vec<u64> = Vec::new();
    proof {
        lemma_tr_init(p.version__dict@, n.version__dict@, tv@);
        lemma_dd_pre(p);
    }
    let mut dv: usize = 0;
    while dv < ncv
        invariant
            dv <= ncv,
            ncv == n.version__dict@.len(),
            pcv == p.version__dict@.len(),
            vcs(n, s, p),
            dd(p.version__dict@),
            mp_ok(p.version__dict@, vmap@, pcv as int),
            tr_ok(p.version__dict@, n.version__dict@, tv@, dv as int),
        decreases ncv - dv,
    {
        let fc = vmap.get(n.version__dict[dv].as_str());
        let ghost old_t = tv@;
        match fc {
            Some(v) => {
                let vv: usize = *v;
                proof {
                    lemma_mp_some(p.version__dict@, vmap@, pcv as int, n.version__dict@[dv as int]@, vv);
                }
                if (vv as u64) < 4294967296u64 {
                    tv.push((vv as u64) + 1);
                    proof {
                        lemma_tr_some(p.version__dict@, n.version__dict@, old_t, dv as int, vv, ((vv as u64) + 1) as u64);
                    }
                } else {
                    tv.push(0);
                    proof {
                        lemma_tr_big(p.version__dict@, n.version__dict@, old_t, dv as int, vv);
                    }
                }
            }
            None => {
                proof {
                    lemma_mp_none(p.version__dict@, vmap@, pcv as int, n.version__dict@[dv as int]@);
                    lemma_tr_none(p.version__dict@, n.version__dict@, old_t, dv as int);
                }
                tv.push(0);
            }
        }
        dv += 1;
    }

    // ===== pre chains: rows with the same (adsh, tag, version) codes, newest first =====
    let mut lm: HashMapWithView<i128, usize> = HashMapWithView::new();
    let mut prv: Vec<usize> = Vec::new();
    proof {
        lemma_lm_init(p, lm@);
        lemma_prv_init(p, prv@);
    }
    let mut q: usize = 0;
    while q < p.n
        invariant
            q <= p.n,
            vcs(n, s, p),
            forall|t: int| #![trigger pf(p, t)] 0 <= t < p.n as int ==> (pf(p, t) <==> (p.stmt__valid@[t] && sfound && p.stmt@[t] as int == scode as int)),
            lm_inv(p, lm@, q as int),
            prv_inv(p, prv@, q as int),
            prv@.len() == q as int,
        decreases p.n - q,
    {
        proof {
            lemma_vcs_open(n, s, p);
            assert(p.stmt__valid@.len() == p.n as int);
            assert(p.stmt@.len() == p.n as int);
            assert(p.adsh@.len() == p.n as int);
            assert(p.tag@.len() == p.n as int);
            assert(p.version@.len() == p.n as int);
        }
        let isf: bool = p.stmt__valid[q] && sfound && (p.stmt[q] as usize) == scode;
        proof {
            assert(isf == pf(p, q as int));
        }
        if isf {
            let key: i128 = (p.adsh[q] as i128) * 36893488147419103232i128 + (p.tag[q] as i128) * 8589934592i128 + (p.version[q] as i128);
            proof {
                assert(key as int == rk(p, q as int));
            }
            let ghost old_lm = lm@;
            let ghost old_prv = prv@;
            let got = lm.get(&key);
            match got {
                Some(v) => {
                    let vv: usize = *v;
                    proof {
                        lemma_prv_some(p, old_lm, old_prv, q as int, key, vv);
                    }
                    prv.push(vv);
                }
                None => {
                    proof {
                        lemma_prv_none(p, old_lm, old_prv, q as int, key);
                    }
                    prv.push(0);
                }
            }
            lm.insert(key, q + 1);
            proof {
                lemma_lm_pf(p, old_lm, q as int, key, lm@);
            }
        } else {
            proof {
                lemma_lm_nopf(p, lm@, q as int);
                lemma_prv_nopf(p, prv@, q as int);
            }
            prv.push(0);
        }
        q += 1;
    }
    proof {
        assert(prv@.len() == p.n as int);
    }

    // ===== main pass over num, newest row first =====
    let mut gnm: Vec<usize> = Vec::new();
    let mut gtg: Vec<u32> = Vec::new();
    let mut gpe: Vec<u64> = Vec::new();
    let mut gsm: Vec<i128> = Vec::new();
    let mut gct: Vec<u64> = Vec::new();
    let mut gek: Vec<i128> = Vec::new();
    let mut gm: HashMapWithView<i128, usize> = HashMapWithView::new();
    proof {
        lemma_init(n, s, p);
        lemma_gm_init(gm@);
    }
    let mut i: usize = n.n;
    while i > 0
        invariant
            i <= n.n,
            vcs(n, s, p),
            join_tuples_num_pre(n, p, 0) <= JOIN_CAP_num_pre as int,
            forall|i0: int| #![trigger nf(n, i0)] 0 <= i0 < n.n as int ==> (nf(n, i0) <==> (ufound && n.uom@[i0] as int == ucode as int)),
            ts_ok(s, n.adsh__dict@, tsub@, n.adsh__dict@.len() as int),
            tr_ok(p.adsh__dict@, n.adsh__dict@, ta@, n.adsh__dict@.len() as int),
            tr_ok(p.tag__dict@, n.tag__dict@, tt@, n.tag__dict@.len() as int),
            tr_ok(p.version__dict@, n.version__dict@, tv@, n.version__dict@.len() as int),
            lm_inv(p, lm@, p.n as int),
            prv_inv(p, prv@, p.n as int),
            prv@.len() == p.n as int,
            gsm@.len() == gnm@.len(),
            gct@.len() == gnm@.len(),
            gtg@.len() == gnm@.len(),
            gpe@.len() == gnm@.len(),
            g_shape(n, s, p, gnm@, gtg@, gpe@),
            g_wit(n, s, p, gnm@, gtg@, gpe@),
            gm_inv(gm@, gek@, gnm@, gtg@, gpe@),
            g_sums(n, s, p, (i as int) - 1, 0, p.n as int, gnm@, gtg@, gpe@, gsm@, gct@),
            g_cov(n, s, p, (i as int) - 1, p.n as int, gnm@, gtg@, gpe@),
        decreases i,
    {
        i -= 1;
        let i0: usize = i;
        proof {
            lemma_row_facts_n(n, s, p, i0 as int);
            assert(g_sums(n, s, p, i0 as int, 0, p.n as int, gnm@, gtg@, gpe@, gsm@, gct@));
            assert(g_cov(n, s, p, i0 as int, p.n as int, gnm@, gtg@, gpe@));
        }
        let isnf: bool = ufound && (n.uom[i0] as usize) == ucode;
        proof {
            assert(isnf == nf(n, i0 as int));
        }
        let da: usize = n.adsh[i0] as usize;
        proof {
            lemma_ts_get(s, n.adsh__dict@, tsub@, n.adsh__dict@.len() as int, da as int);
        }
        let tsda: usize = tsub[da];
        if !isnf || tsda == 0 {
            proof {
                if !isnf {
                    lemma_nohit_nf(n, s, p, i0 as int);
                } else {
                    assert(da as int == n.adsh@[i0 as int] as int);
                    lemma_nohit_sub(n, s, p, i0 as int);
                }
                lemma_sums_finish_none(n, s, p, i0 as int, gnm@, gtg@, gpe@, gsm@, gct@);
                lemma_cov_finish_none(n, s, p, i0 as int, gnm@, gtg@, gpe@);
            }
        } else {
            let j: usize = tsda - 1;
            proof {
                assert(da as int == n.adsh@[i0 as int] as int);
                assert((j as int) < s.n as int);
                assert(sf(s, j as int));
                assert(ae(n, s, i0 as int, j as int));
                lemma_sums_enter(n, s, p, i0 as int, 0, j as int, gnm@, gtg@, gpe@, gsm@, gct@);
            }
            let snm: usize = s.name[j] as usize;
            let tgc: u32 = n.tag[i0];
            let vv: i128 = n.value[i0];
            let dt: usize = tgc as usize;
            let dv: usize = n.version[i0] as usize;
            proof {
                assert(dt as int == n.tag@[i0 as int] as int);
                assert(dv as int == n.version@[i0 as int] as int);
                lemma_tr_get(p.adsh__dict@, n.adsh__dict@, ta@, n.adsh__dict@.len() as int, da as int);
                lemma_tr_get(p.tag__dict@, n.tag__dict@, tt@, n.tag__dict@.len() as int, dt as int);
                lemma_tr_get(p.version__dict@, n.version__dict@, tv@, n.version__dict@.len() as int, dv as int);
            }
            let xa: u64 = ta[da];
            let xt: u64 = tt[dt];
            let xv: u64 = tv[dv];
            let mut cur: usize = 0;
            if xa > 0 && xt > 0 && xv > 0 {
                proof {
                    assert(tf(n, p, i0 as int, xa as int - 1, xt as int - 1, xv as int - 1));
                }
                let key: i128 = (((xa - 1) as i128) * 36893488147419103232i128) + (((xt - 1) as i128) * 8589934592i128) + ((xv - 1) as i128);
                proof {
                    assert(key as int == enc3(xa as int - 1, xt as int - 1, xv as int - 1));
                }
                let got = lm.get(&key);
                match got {
                    Some(v) => {
                        cur = *v;
                        proof {
                            lemma_chain_hit(n, s, p, i0 as int, xa as int - 1, xt as int - 1, xv as int - 1, key, lm@, cur);
                        }
                    }
                    None => {
                        proof {
                            lemma_chain_miss(n, s, p, i0 as int, xa as int - 1, xt as int - 1, xv as int - 1, key, lm@);
                        }
                    }
                }
            } else {
                proof {
                    if xa == 0 {
                        assert(da as int == n.adsh@[i0 as int] as int);
                        lemma_cr_none_a(n, s, p, i0 as int);
                    } else if xt == 0 {
                        lemma_cr_none_t(n, s, p, i0 as int);
                    } else {
                        lemma_cr_none_v(n, s, p, i0 as int);
                    }
                }
            }
            proof {
                assert(cur as int <= p.n as int);
                assert(cur > 0 ==> cr(n, p, i0 as int, cur as int - 1));
                assert(forall|c: int| #![trigger cr(n, p, i0 as int, c)] cur as int <= c < p.n as int ==> !cr(n, p, i0 as int, c));
            }
            let ghost mut lo: int = p.n as int;
            while cur > 0
                invariant
                    cur as int <= lo,
                    lo <= p.n as int,
                    i0 < n.n,
                    vcs(n, s, p),
            join_tuples_num_pre(n, p, 0) <= JOIN_CAP_num_pre as int,
                    (j as int) < s.n as int,
                    ae(n, s, i0 as int, j as int),
                    sf(s, j as int),
                    nf(n, i0 as int),
                    snm <= 65535,
                    snm as int == s.name@[j as int] as int,
                    tgc as int == n.tag@[i0 as int] as int,
                    vv as int == n.value@[i0 as int] as int,
                    cur > 0 ==> (xa > 0 && xt > 0 && xv > 0 && tf(n, p, i0 as int, xa as int - 1, xt as int - 1, xv as int - 1)),
                    cur > 0 ==> cr(n, p, i0 as int, cur as int - 1),
                    forall|c: int| #![trigger cr(n, p, i0 as int, c)] cur as int <= c < lo ==> !cr(n, p, i0 as int, c),
                    prv_inv(p, prv@, p.n as int),
                    prv@.len() == p.n as int,
                    gsm@.len() == gnm@.len(),
                    gct@.len() == gnm@.len(),
                    gtg@.len() == gnm@.len(),
                    gpe@.len() == gnm@.len(),
                    g_shape(n, s, p, gnm@, gtg@, gpe@),
            g_wit(n, s, p, gnm@, gtg@, gpe@),
            gm_inv(gm@, gek@, gnm@, gtg@, gpe@),
                    g_sums(n, s, p, i0 as int, j as int, lo, gnm@, gtg@, gpe@, gsm@, gct@),
                    g_cov(n, s, p, i0 as int, lo, gnm@, gtg@, gpe@),
                decreases cur,
            {
                let r: usize = cur - 1;
                proof {
                    lemma_sums_skip_lo(n, s, p, i0 as int, j as int, lo, cur as int, gnm@, gtg@, gpe@, gsm@, gct@);
                    lemma_cov_skip_lo(n, s, p, i0 as int, lo, cur as int, gnm@, gtg@, gpe@);
                    lemma_hit_iff(n, s, p, i0 as int, j as int, r as int);
                    assert(row_hit(n, s, p, i0 as int, j as int, r as int));
                    lemma_key_hit(n, s, p, i0 as int, j as int, r as int);
                    lemma_row_facts_p(n, s, p, r as int);
                }
                let pev: u64 = if p.plabel__valid[r] { (p.plabel[r] as u64) + 1 } else { 0 };
                proof {
                    assert(pev as int == pe_of(p, r as int));
                    assert(pev as int <= 4294967296);
                }
                let e: i128 = (snm as i128) * 36893488147419103232i128 + (tgc as i128) * 8589934592i128 + (pev as i128);
                proof {
                    assert(e as int == enc3(snm as int, tgc as int, pev as int));
                }
                let got = gm.get(&e);
                match got {
                    Some(gi) => {
                        let g: usize = *gi;
                        proof {
                            lemma_gm_found(gm@, gek@, gnm@, gtg@, gpe@, e, g);
                            lemma_shape_get(n, s, p, gnm@, gtg@, gpe@, g as int);
                            lemma_enc3(gnm@[g as int] as int, gtg@[g as int] as int, gpe@[g as int] as int, snm as int, tgc as int, pev as int);
                            assert(gk(n, s, p, gnm@, gtg@, gpe@, g as int) == key_at(n, s, p, i0 as int, j as int, r as int));
                            lemma_upd_bounds(n, s, p, i0 as int, j as int, r as int, gnm@, gtg@, gpe@, gsm@, gct@, g as int);
                        }
                        let nsum: i128 = gsm[g] + vv;
                        let ncnt: u64 = gct[g] + 1;
                        let ghost old_sm = gsm@;
                        let ghost old_ct = gct@;
                        gsm.set(g, nsum);
                        gct.set(g, ncnt);
                        proof {
                            lemma_sums_found(n, s, p, i0 as int, j as int, r as int, gnm@, gtg@, gpe@, old_sm, old_ct, g as int, nsum, ncnt);
                            lemma_cov_hit(n, s, p, i0 as int, j as int, r as int, gnm@, gtg@, gpe@, g as int);
                        }
                    }
                    None => {
                        let glen: usize = gnm.len();
                        proof {
                            lemma_gm_none(gm@, gek@, gnm@, gtg@, gpe@, e);
                            lemma_newgroup_distinct(gnm@, gtg@, gpe@, e, snm, tgc, pev);
                            lemma_sums_new(n, s, p, i0 as int, j as int, r as int, gnm@, gtg@, gpe@, gsm@, gct@, snm, tgc, pev, vv);
                            lemma_cov_push(n, s, p, i0 as int, r as int + 1, gnm@, gtg@, gpe@, snm, tgc, pev);
                            assert(key_at(n, s, p, i0 as int, j as int, r as int) == gkey(n, s, p, snm as int, tgc as int, pev as int));
                            assert(glen as int == gnm@.len());
                            assert(gnm@.push(snm)[glen as int] == snm);
                            assert(gtg@.push(tgc)[glen as int] == tgc);
                            assert(gpe@.push(pev)[glen as int] == pev);
                            assert(gk(n, s, p, gnm@.push(snm), gtg@.push(tgc), gpe@.push(pev), glen as int) == gkey(n, s, p, snm as int, tgc as int, pev as int));
                            lemma_cov_hit(n, s, p, i0 as int, j as int, r as int, gnm@.push(snm), gtg@.push(tgc), gpe@.push(pev), glen as int);
                            lemma_wit_push(n, s, p, gnm@, gtg@, gpe@, snm, tgc, pev, i0 as int, j as int, r as int);
                            lemma_gm_push(gm@, gek@, gnm@, gtg@, gpe@, e, snm, tgc, pev, glen, gm@.insert(e, glen));
                        }
                        gnm.push(snm);
                        gtg.push(tgc);
                        gpe.push(pev);
                        gsm.push(vv);
                        gct.push(1);
                        gek.push(e);
                        gm.insert(e, glen);
                    }
                }
                proof {
                    lemma_chain_next(n, s, p, i0 as int, xa as int - 1, xt as int - 1, xv as int - 1, prv@, r as int);
                }
                let nxt: usize = prv[r];
                proof {
                    lo = r as int;
                }
                cur = nxt;
            }
            proof {
                lemma_sums_skip_lo(n, s, p, i0 as int, j as int, lo, 0, gnm@, gtg@, gpe@, gsm@, gct@);
                lemma_cov_skip_lo(n, s, p, i0 as int, lo, 0, gnm@, gtg@, gpe@);
                lemma_sums_finish(n, s, p, i0 as int, j as int, gnm@, gtg@, gpe@, gsm@, gct@);
                lemma_cov_finish(n, s, p, i0 as int, gnm@, gtg@, gpe@);
            }
        }
    }

    // ===== top 200 groups by total, largest first =====
    proof {
        assert((i as int) - 1 == -1int);
        assert(g_sums(n, s, p, -1int, 0, p.n as int, gnm@, gtg@, gpe@, gsm@, gct@));
        assert(g_cov(n, s, p, -1int, p.n as int, gnm@, gtg@, gpe@));
        lemma_sums_lens(n, s, p, -1int, 0, p.n as int, gnm@, gtg@, gpe@, gsm@, gct@);
    }
    let gcount: usize = gnm.len();
    let mut used: Vec<bool> = Vec::new();
    let mut z: usize = 0;
    while z < gcount
        invariant
            z <= gcount,
            gcount == gnm@.len(),
            used@.len() == z as int,
            forall|x: int| #![trigger used@[x]] 0 <= x < z as int ==> !used@[x],
            vcs(n, s, p),
        decreases gcount - z,
    {
        used.push(false);
        z += 1;
    }
    let mut sel: Vec<usize> = Vec::new();
    let mut go: bool = true;
    proof {
        lemma_sel_init(used@, gsm@, gcount as int);
    }
    while go && sel.len() < 200
        invariant
            vcs(n, s, p),
            g_shape(n, s, p, gnm@, gtg@, gpe@),
            g_sums(n, s, p, -1int, 0, p.n as int, gnm@, gtg@, gpe@, gsm@, gct@),
            g_cov(n, s, p, -1int, p.n as int, gnm@, gtg@, gpe@),
            g_wit(n, s, p, gnm@, gtg@, gpe@),
            gcount == gnm@.len(),
            gsm@.len() == gnm@.len(),
            used@.len() == gcount as int,
            sel_ok(sel@, used@, gsm@, gcount as int),
            !go ==> (forall|g: int| #![trigger used@[g]] 0 <= g < gcount as int ==> used@[g]),
        decreases 200 - sel@.len() + (if go { 1int } else { 0int }),
    {
        let mut bi: usize = 0;
        let mut found: bool = false;
        let mut k: usize = 0;
        while k < gcount
            invariant
                k <= gcount,
                gcount == gnm@.len(),
                gsm@.len() == gnm@.len(),
                used@.len() == gcount as int,
                vcs(n, s, p),
                found ==> (bi < k && !used@[bi as int]),
                forall|t: int| #![trigger used@[t]] 0 <= t < k as int ==> (used@[t] || (found && gsm@[t] <= gsm@[bi as int])),
            decreases gcount - k,
        {
            if !used[k] && (!found || gsm[bi] < gsm[k]) {
                bi = k;
                found = true;
            }
            k += 1;
        }
        if found {
            let ghost old_sel = sel@;
            let ghost old_used = used@;
            sel.push(bi);
            used.set(bi, true);
            proof {
                lemma_sel_push(old_sel, old_used, gsm@, gcount as int, bi, sel@, used@);
            }
        } else {
            go = false;
        }
    }
    proof {
        lemma_sel_len(sel@, used@, gsm@, gcount as int);
        assert(sel@.len() == 200 || (forall|g: int| #![trigger used@[g]] 0 <= g < gcount as int ==> used@[g]));
    }
    // ===== output rows =====
    let isout: String = String::from_str("IS");
    let mut res: Vec<OutRow> = Vec::new();
    proof {
        lemma_res_init(n, s, p, gnm@, gtg@, gpe@, gsm@, gct@, sel@, res@);
    }
    let mut x: usize = 0;
    while x < sel.len()
        invariant
            x <= sel.len(),
            isout@ == "IS"@,
            vcs(n, s, p),
            g_shape(n, s, p, gnm@, gtg@, gpe@),
            g_sums(n, s, p, -1int, 0, p.n as int, gnm@, gtg@, gpe@, gsm@, gct@),
            g_cov(n, s, p, -1int, p.n as int, gnm@, gtg@, gpe@),
            g_wit(n, s, p, gnm@, gtg@, gpe@),
            gcount == gnm@.len(),
            gsm@.len() == gnm@.len(),
            gct@.len() == gnm@.len(),
            used@.len() == gcount as int,
            sel_ok(sel@, used@, gsm@, gcount as int),
            sel@.len() == 200 || (forall|g: int| #![trigger used@[g]] 0 <= g < gcount as int ==> used@[g]),
            res_ok(n, s, p, gnm@, gtg@, gpe@, gsm@, gct@, sel@, res@, x as int),
        decreases sel.len() - x,
    {
        let g: usize = sel[x];
        proof {
            lemma_sel_get(sel@, used@, gsm@, gcount as int, x as int);
            lemma_shape_get(n, s, p, gnm@, gtg@, gpe@, g as int);
        }
        let nmc: usize = gnm[g];
        let tgc: u32 = gtg[g];
        let pec: u64 = gpe[g];
        let ghost old_res = res@;
        let row_name: String = s.name__dict[nmc].clone();
        let row_tag: String = n.tag__dict[tgc as usize].clone();
        let row_pl: Option<String> = if pec > 0 { Some(p.plabel__dict[(pec - 1) as usize].clone()) } else { None };
        let row = OutRow { name: row_name, stmt: Some(isout.clone()), tag: row_tag, plabel: row_pl, total_value: gsm[g], cnt: gct[g] };
        proof {
            assert(okey(row) == gk(n, s, p, gnm@, gtg@, gpe@, g as int));
        }
        res.push(row);
        proof {
            lemma_res_push(n, s, p, gnm@, gtg@, gpe@, gsm@, gct@, sel@, old_res, x as int, row, res@);
        }
        x += 1;
    }
    proof {
        lemma_final_all(n, s, p, gnm@, gtg@, gpe@, gsm@, gct@, sel@, used@, res@);
    }
    res
// AGENT_EDIT_END
