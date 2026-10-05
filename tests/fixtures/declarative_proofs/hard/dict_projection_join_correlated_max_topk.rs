// Worked example (hard, long, dictionary string mode): a projection over a TWO-table join with a join to a per-key MAX subquery,
// ORDER BY a three-column key with string tie-breaks, LIMIT 100. The published GenDB SEC query Q2:
//   SELECT s.name, n.tag, n.value FROM num n JOIN sub s ON n.adsh = s.adsh
//   JOIN (SELECT adsh, tag, MAX(value) AS max_value FROM num WHERE uom = 'pure' AND value IS NOT NULL GROUP BY adsh, tag) m
//     ON n.adsh = m.adsh AND n.tag = m.tag AND n.value = m.max_value
//   WHERE n.uom = 'pure' AND s.fy = 2022 AND n.value IS NOT NULL ORDER BY n.value DESC, s.name, n.tag LIMIT 100
// Found by a manual prover (Sonnet subagent, not a model-agent result): 69 verified, 0 errors (a standalone script reported 70) (8 checks). Proved against BOTH the local
// 1M-row synthetic catalog (sec_edgar_local_dec.duckdb) and the real catalog (sec_edgar_dec.duckdb: num 39,401,761 rows, sub 86,135);
// both emit the same spec (package sec_margin_dec: ROW_CAP_num 2^31, ROW_CAP_sub 2^20, no dictionary caps), so the body is size-agnostic.
// Timed on the local 1M-row synthetic db by the manual harness (`check`): result rows equal the reference engine's, 75,250 us vs 80,090 us for the
// all-core engine (1.06x) and 154,978 us for one thread (2.06x). The full-size (39M-row) table was not run.
// The plain-string template is `projection_join_correlated_max_topk.rs`; this is the dictionary-mode rewrite.
// Techniques (each is a helper bundle or a loop below):
//  1. The correlated MAX is a HASH MAP over the packed (adsh code, tag code) -> group max (`HashMapWithView<i128, i128>`, `pk(a, t) = a * 2^32 + t`,
//     `lemma_pk_inj`), built in one forward pass over the pure rows. `sq_1` (the spec's "exists a row with this value, all rows <= it") is decided by
//     ONE equality `value == mx[key]` (`lemma_gm_sq`): equal strings <=> equal codes (the dictionaries are pairwise distinct, `lemma_grp_eq`).
//     The plain example walked a per-key row chain for every row (quadratic in the group size); a map is O(rows) and a smaller proof.
//  2. The pure literal is looked up ONCE in `n.uom__dict` (`pcode`), so a row is pure iff `pfound && n.uom[i] == pcode` (`pud`).
//  3. The join key adsh has one dictionary PER TABLE: `tr[d]` = the sub code of num dictionary entry d (a sentinel `scodes` if none), built with
//     one `StringHashMap` over sub's dictionary probed once per NUM dictionary entry (`trd`), as in `dict_join_probe_sum.rs`. No per-row string work.
//  4. The filtered sub rows (fy valid and 2022) are chained BY SUB CODE: `sh[code]` = newest row with that code (a `Vec` over ONE dictionary,
//     sentinel `s.n`), `sx[row]` = the next older such row (the opaque bundle `ch`, with init/step/own/head/next lemmas). A group-max pure num row
//     walks the chain of `tr[its adsh code]`, newest first, so every (num row, sub row) hit is visited exactly once and the pair order is
//     the spec's suffix fold order (num row descending, sub row descending): `tk(res, i, j)` is the loop invariant, `lemma_range_skip` closes the
//     gaps between chain links and `lemma_tk_shift` moves to the next num row.
//  5. The result is the sorted top-100 `Vec<OutRow>` (insert at the first position whose element is strictly greater, pop the 101st) maintained by
//     the opaque bundle `tk` with `lemma_tk_hit/skip/shift/final` (adapted from `projection_top_k`). The ORDER is `kle` (value DESC, then name, then tag,
//     the spec's text): it needs `seq_le` to be total, antisymmetric and transitive (`lemma_seq_le_total/anti/trans`, `lemma_kle_total/trans`):
//     the omitted-row clause ("the last kept row is <= every row that was dropped") uses transitivity when the 101st row is popped.
//  6. Exec string order: `get_char` loops over `as_str()` stopped at the first difference, tied to `seq_le` by `lemma_le_stop` (see
//     `group_decimal_sums_string_keys_sorted.rs`); exec `fn` helpers are not allowed so the two loops (tag when names are equal, name otherwise) are inline.
// Sizing at real scale: the only table that scales with the rows is the group-max map `mx` (one entry per distinct pure (adsh, tag) pair, at most the pure
// rows); everything else is one `Vec` over ONE dictionary (`sh`, `tr`: sub / num adsh dictionary sizes) or over sub's rows (`sx`, 86k at SEC scale) plus the
// 100-row result. No table over a product of dictionary sizes exists (the earlier fixture that built one panicked at `LEMMA_DENSE_SLOT_BUDGET`); the packed
// pair is a hash KEY, never an index. The row loop does a hash lookup per pure row and one chain walk per group-max row; the speed was not tuned.
// Pitfalls it hit (each cost a check):
//  * Verus forgets facts about a variable that is not in a loop's invariant: the inner position loop needs `x.value == vi` stated, or `kle(..)` of the
//    compared row cannot be tied to the exec comparison.
//  * A quantifier whose trigger term (`n.value@[q]`) is absent from the goal never fires: the bundle clause "every pure row's key is in the map and bounded"
//    is triggered by `is_pure(n, q)` instead, and is exposed through `lemma_gm_val` / `lemma_gm_att` rather than by `reveal` inside the loop lemmas.
//  * A whole-program rlimit overrun is reported on the first big lemma: `lemma_tk_hit` sits near the limit, keep it separate and do not add asserts to it.
//  * `StringHashMap::get` returns the map entry, so its key view fact (`smap@[k]`) must be restated before `lemma_trd_step`.
// AGENT_HELPERS_START
spec fn pk(x: int, b: int) -> int {
    x * 4294967296int + b
}

proof fn lemma_pk_inj(x: int, b: int, y: int, d: int)
    requires
        0 <= b < 4294967296int,
        0 <= d < 4294967296int,
        pk(x, b) == pk(y, d),
    ensures
        x == y && b == d,
{
    if x < y {
        assert(y * 4294967296int >= x * 4294967296int + 4294967296int) by (nonlinear_arith)
            requires y >= x + 1;
    } else if y < x {
        assert(x * 4294967296int >= y * 4294967296int + 4294967296int) by (nonlinear_arith)
            requires x >= y + 1;
    }
}

proof fn lemma_pk_rng32(x: int, b: int)
    requires
        0 <= x < 4294967296int,
        0 <= b < 4294967296int,
    ensures
        0 <= pk(x, b) < 18446744073709551616int,
{
    assert(x * 4294967296int <= 4294967295int * 4294967296int) by (nonlinear_arith)
        requires x <= 4294967295int;
}

spec fn dist(d: Seq<String>) -> bool {
    forall|x: int, y: int| #![trigger d[x]@, d[y]@] 0 <= x < y < d.len() ==> d[x]@ != d[y]@
}

proof fn lemma_dict_eq(d: Seq<String>, a: int, b: int)
    requires
        dist(d),
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

proof fn lemma_valid_dists(n: &Cols_num, s: &Cols_sub)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
    ensures
        dist(n.adsh__dict@),
        dist(n.tag__dict@),
        dist(n.uom__dict@),
        dist(s.adsh__dict@),
{
}

// ---------- string order (seq_le) is a total order, and the result order `kle` is a total preorder ----------

proof fn lemma_seq_le_total(a: Seq<char>, b: Seq<char>)
    ensures
        seq_le(a, b) || seq_le(b, a),
    decreases a.len(),
{
    if a.len() > 0 && b.len() > 0 && a[0] == b[0] {
        lemma_seq_le_total(a.skip(1), b.skip(1));
    }
}

proof fn lemma_seq_le_anti(a: Seq<char>, b: Seq<char>)
    requires
        seq_le(a, b),
        seq_le(b, a),
    ensures
        a == b,
    decreases a.len(),
{
    if a.len() > 0 && b.len() > 0 && a[0] == b[0] {
        lemma_seq_le_anti(a.skip(1), b.skip(1));
        assert forall|k: int| 0 <= k < a.len() implies a[k] == b[k] by {
            if k > 0 {
                assert(a.skip(1)[k - 1] == a[k]);
                assert(b.skip(1)[k - 1] == b[k]);
            }
        };
        assert(a =~= b);
    } else if a.len() == 0 && b.len() == 0 {
        assert(a =~= b);
    }
}

proof fn lemma_seq_le_trans(a: Seq<char>, b: Seq<char>, c: Seq<char>)
    requires
        seq_le(a, b),
        seq_le(b, c),
    ensures
        seq_le(a, c),
    decreases a.len(),
{
    if a.len() > 0 && b.len() > 0 && c.len() > 0 && a[0] == b[0] && b[0] == c[0] {
        lemma_seq_le_trans(a.skip(1), b.skip(1), c.skip(1));
    }
}

spec fn kle(a: (Seq<char>, Seq<char>, int), b: (Seq<char>, Seq<char>, int)) -> bool {
    if a.2 == b.2 {
        if a.0 == b.0 { seq_le(a.1, b.1) } else { seq_le(a.0, b.0) }
    } else {
        a.2 >= b.2
    }
}

proof fn lemma_kle_total(a: (Seq<char>, Seq<char>, int), b: (Seq<char>, Seq<char>, int))
    ensures
        kle(a, b) || kle(b, a),
{
    if a.2 == b.2 {
        if a.0 == b.0 {
            lemma_seq_le_total(a.1, b.1);
        } else {
            lemma_seq_le_total(a.0, b.0);
        }
    }
}

proof fn lemma_kle_trans(a: (Seq<char>, Seq<char>, int), b: (Seq<char>, Seq<char>, int), c: (Seq<char>, Seq<char>, int))
    requires
        kle(a, b),
        kle(b, c),
    ensures
        kle(a, c),
{
    if a.2 == b.2 && b.2 == c.2 {
        if a.0 == b.0 && b.0 == c.0 {
            lemma_seq_le_trans(a.1, b.1, c.1);
        } else if a.0 == b.0 {
        } else if b.0 == c.0 {
        } else {
            lemma_seq_le_trans(a.0, b.0, c.0);
            if a.0 == c.0 {
                lemma_seq_le_anti(a.0, b.0);
            }
        }
    }
}

proof fn lemma_le_stop(a: Seq<char>, b: Seq<char>, t: int)
    requires
        0 <= t <= a.len(),
        t <= b.len(),
        forall|u: int| 0 <= u < t ==> a[u] == b[u],
        t == a.len() || t == b.len() || a[t] != b[t],
    ensures
        seq_le(a, b) == (t == a.len() || (t < b.len() && a[t] < b[t])),
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

// ---------- the top-100 buffer ----------

proof fn lemma_tail(s: Seq<OutRow>, p: int, x: OutRow, i: int, k: (Seq<char>, Seq<char>, int))
    requires
        0 <= p <= s.len(),
        p <= i,
    ensures
        out_copies(s.insert(p, x), i + 1, k) == out_copies(s, i, k),
    decreases s.len() - i,
{
    if i < s.len() {
        lemma_tail(s, p, x, i + 1, k);
        assert(s.insert(p, x)[i + 1] == s[i]);
    }
}

proof fn lemma_insert(s: Seq<OutRow>, p: int, x: OutRow, i: int, k: (Seq<char>, Seq<char>, int))
    requires
        0 <= i <= p <= s.len(),
    ensures
        out_copies(s.insert(p, x), i, k) == out_copies(s, i, k) + (if out_key(x) == k { 1int } else { 0int }),
    decreases p - i,
{
    if i < p {
        assert(s.insert(p, x)[i] == s[i]);
        lemma_insert(s, p, x, i + 1, k);
    } else {
        assert(s.insert(p, x)[p] == x);
        lemma_tail(s, p, x, p, k);
    }
}

proof fn lemma_drop(s: Seq<OutRow>, i: int, k: (Seq<char>, Seq<char>, int))
    requires
        s.len() > 0,
        0 <= i,
    ensures
        out_copies(s.drop_last(), i, k) + (if i < s.len() && out_key(s.last()) == k { 1int } else { 0int })
            == out_copies(s, i, k),
    decreases s.len() - i,
{
    if i < s.len() - 1 {
        assert(s.drop_last()[i] == s[i]);
        lemma_drop(s, i + 1, k);
    } else if i == s.len() - 1 {
        assert(s[i] == s.last());
        assert(out_copies(s, i + 1, k) == 0);
        assert(out_copies(s.drop_last(), i, k) == 0);
    }
}

spec fn tot_cnt(n: &Cols_num, s: &Cols_sub, i0: int, i1: int) -> int {
    hit_count_d1(n, s, i0, i1) + hit_count(n, s, i0 + 1)
}

spec fn tot_with(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: (Seq<char>, Seq<char>, int)) -> int {
    hits_with_d1(n, s, i0, i1, k) + hits_with(n, s, i0 + 1, k)
}

#[verifier::opaque]
spec fn tk(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int, j: int) -> bool {
    &&& res.len() <= 100
    &&& res.len() as int == (if tot_cnt(n, s, i, j) < 100 { tot_cnt(n, s, i, j) } else { 100int })
    &&& forall|q: int| #![trigger res[q]] 0 <= q && q + 1 < res.len() ==> kle(out_key(res[q]), out_key(res[q + 1]))
    &&& forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, s, res[r])
    &&& forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)] out_copies(res, 0, k) <= tot_with(n, s, i, j, k)
    &&& res.len() as int == tot_cnt(n, s, i, j) ==> forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
            out_copies(res, 0, k) == tot_with(n, s, i, j, k)
    &&& forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
            tot_with(n, s, i, j, k) > out_copies(res, 0, k) && res.len() > 0 ==> kle(out_key(res[res.len() - 1]), k)
}

proof fn lemma_tk_init(n: &Cols_num, s: &Cols_sub)
    ensures
        tk(Seq::<OutRow>::empty(), n, s, n.n as int - 1, s.n as int),
{
    reveal(tk);
    assert(hit_count(n, s, n.n as int) == 0);
    assert(hit_count_d1(n, s, n.n as int - 1, s.n as int) == 0);
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger hits_with(n, s, n.n as int, k)] tot_with(n, s, n.n as int - 1, s.n as int, k) == 0 by {
        assert(hits_with(n, s, n.n as int, k) == 0);
        assert(hits_with_d1(n, s, n.n as int - 1, s.n as int, k) == 0);
    };
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(Seq::<OutRow>::empty(), 0, k)] out_copies(Seq::<OutRow>::empty(), 0, k) == 0 by {};
}

proof fn lemma_tk_shift(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int)
    requires
        0 <= i < n.n as int,
        tk(res, n, s, i, 0),
    ensures
        tk(res, n, s, i - 1, s.n as int),
{
    reveal(tk);
    assert(hit_count_d1(n, s, i - 1, s.n as int) == 0);
    assert(tot_cnt(n, s, i - 1, s.n as int) == tot_cnt(n, s, i, 0));
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger hits_with(n, s, i, k)] tot_with(n, s, i - 1, s.n as int, k) == tot_with(n, s, i, 0, k) by {
        assert(hits_with_d1(n, s, i - 1, s.n as int, k) == 0);
    };
}

proof fn lemma_tk_skip(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int, j: int)
    requires
        0 <= j < s.n as int,
        !row_hit(n, s, i, j),
        tk(res, n, s, i, j + 1),
    ensures
        tk(res, n, s, i, j),
{
    reveal(tk);
    assert(hit_count_d1(n, s, i, j) == hit_count_d1(n, s, i, j + 1));
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)] tot_with(n, s, i, j, k) == tot_with(n, s, i, j + 1, k) by {
        assert(hits_with_d1(n, s, i, j, k) == hits_with_d1(n, s, i, j + 1, k));
    };
}

proof fn lemma_range_skip(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int, lo: int, hi: int)
    requires
        0 <= lo <= hi <= s.n as int,
        tk(res, n, s, i, hi),
        forall|r: int| #![trigger row_hit(n, s, i, r)] lo <= r < hi ==> !row_hit(n, s, i, r),
    ensures
        tk(res, n, s, i, lo),
    decreases hi - lo,
{
    if lo < hi {
        lemma_tk_skip(res, n, s, i, hi - 1);
        lemma_range_skip(res, n, s, i, lo, hi - 1);
    }
}

proof fn lemma_tk_hit(old: Seq<OutRow>, res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub, i: int, j: int, x: OutRow, p: int)
    requires
        0 <= j < s.n as int,
        row_hit(n, s, i, j),
        out_key(x) == proj_key(n, s, i, j),
        tk(old, n, s, i, j + 1),
        0 <= p <= old.len(),
        forall|q: int| #![trigger old[q]] 0 <= q < p ==> kle(out_key(old[q]), out_key(x)),
        p == old.len() || !kle(out_key(old[p]), out_key(x)),
        p == 100 ==> res == old,
        p < 100 ==> res == (if old.insert(p, x).len() > 100 { old.insert(p, x).drop_last() } else { old.insert(p, x) }),
    ensures
        tk(res, n, s, i, j),
{
    reveal(tk);
    assert(out_row_ok(n, s, x));
    assert(hit_count_d1(n, s, i, j) == 1 + hit_count_d1(n, s, i, j + 1));
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(old, 0, k)]
        tot_with(n, s, i, j, k) == tot_with(n, s, i, j + 1, k) + (if out_key(x) == k { 1int } else { 0int }) by {
        assert(hits_with_d1(n, s, i, j, k)
            == (if row_hit(n, s, i, j) && proj_key(n, s, i, j) == k { 1int } else { 0int })
            + hits_with_d1(n, s, i, j + 1, k));
    };
    if p == 100 {
        assert(old.len() == 100);
        assert(kle(out_key(old[99]), out_key(x)));
        assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
            tot_with(n, s, i, j, k) > out_copies(res, 0, k) && res.len() > 0 implies kle(out_key(res[res.len() - 1]), k) by {
            if out_key(x) == k {
                assert(kle(out_key(old[99]), k));
            }
        };
    } else {
        let ins = old.insert(p, x);
        assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(ins, 0, k)]
            out_copies(ins, 0, k) == out_copies(old, 0, k) + (if out_key(x) == k { 1int } else { 0int }) by {
            lemma_insert(old, p, x, 0, k);
        };
        if p < old.len() {
            lemma_kle_total(out_key(old[p]), out_key(x));
        }
        assert forall|q: int| #![trigger ins[q]] 0 <= q && q + 1 < ins.len() implies kle(out_key(ins[q]), out_key(ins[q + 1])) by {
            if q < p - 1 {
                assert(ins[q] == old[q]);
                assert(ins[q + 1] == old[q + 1]);
            } else if q == p - 1 {
                assert(ins[q] == old[q]);
                assert(ins[q + 1] == x);
            } else if q == p {
                assert(ins[q] == x);
                assert(ins[q + 1] == old[q]);
            } else {
                assert(ins[q] == old[q - 1]);
                assert(ins[q + 1] == old[q]);
            }
        };
        assert forall|r: int| #![trigger ins[r]] 0 <= r < ins.len() implies out_row_ok(n, s, ins[r]) by {
            if r < p {
                assert(ins[r] == old[r]);
            } else if r == p {
                assert(ins[r] == x);
            } else {
                assert(ins[r] == old[r - 1]);
            }
        };
        if ins.len() > 100 {
            assert(old.len() == 100);
            assert(ins[100] == old[99]);
            assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
                out_copies(res, 0, k) + (if out_key(ins.last()) == k { 1int } else { 0int }) == out_copies(ins, 0, k) by {
                lemma_drop(ins, 0, k);
            };
            assert forall|q: int| #![trigger res[q]] 0 <= q && q + 1 < res.len() implies kle(out_key(res[q]), out_key(res[q + 1])) by {
                assert(res[q] == ins[q]);
                assert(res[q + 1] == ins[q + 1]);
            };
            assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(n, s, res[r]) by {
                assert(res[r] == ins[r]);
            };
            assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)]
                tot_with(n, s, i, j, k) > out_copies(res, 0, k) && res.len() > 0 implies kle(out_key(res[res.len() - 1]), k) by {
                assert(res[99] == ins[99]);
                assert(kle(out_key(ins[99]), out_key(ins[100])));
                if out_key(ins.last()) == k {
                    assert(ins.last() == ins[100]);
                } else {
                    assert(out_copies(old, 0, k) < tot_with(n, s, i, j + 1, k));
                    assert(kle(out_key(old[99]), k));
                    lemma_kle_trans(out_key(ins[99]), out_key(old[99]), k);
                }
            };
        } else {
            assert(old.len() < 100);
            assert(old.len() as int == tot_cnt(n, s, i, j + 1));
        }
    }
}

proof fn lemma_tk_final(res: Seq<OutRow>, n: &Cols_num, s: &Cols_sub)
    requires
        tk(res, n, s, -1int, s.n as int),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, s, res[r]),
        forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> (if ((res[i].value as int)) == ((res[i + 1].value as int)) { if (res[i].name@) == (res[i + 1].name@) { seq_le(res[i].tag@, res[i + 1].tag@) } else { seq_le(res[i].name@, res[i + 1].name@) } } else { ((res[i].value as int)) >= ((res[i + 1].value as int)) }),
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_copies(res, 0, out_key(res[r])) <= hits_with(n, s, 0, out_key(res[r])),
        res.len() <= 100,
        ((hit_count(n, s, 0) <= 100) && res.len() as int == hit_count(n, s, 0)) || ((hit_count(n, s, 0) > 100) && res.len() == 100),
        res.len() as int == hit_count(n, s, 0) ==> (forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_copies(res, 0, out_key(res[r])) == hits_with(n, s, 0, out_key(res[r]))),
        forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) && hits_with(n, s, 0, proj_key(n, s, i0, i1)) > out_copies(res, 0, proj_key(n, s, i0, i1)) && res.len() > 0 ==> (if ((res[(res.len() as int) - 1].value as int)) == ((n.value@[i0] as int)) { if (res[(res.len() as int) - 1].name@) == ((s.name__dict@[s.name@[i1] as int]@)) { seq_le(res[(res.len() as int) - 1].tag@, (n.tag__dict@[n.tag@[i0] as int]@)) } else { seq_le(res[(res.len() as int) - 1].name@, (s.name__dict@[s.name@[i1] as int]@)) } } else { ((res[(res.len() as int) - 1].value as int)) >= ((n.value@[i0] as int)) }),
{
    reveal(tk);
    assert(hit_count_d1(n, s, -1int, s.n as int) == 0);
    assert(tot_cnt(n, s, -1int, s.n as int) == hit_count(n, s, 0));
    assert forall|k: (Seq<char>, Seq<char>, int)| #![trigger out_copies(res, 0, k)] tot_with(n, s, -1int, s.n as int, k) == hits_with(n, s, 0, k) by {
        assert(hits_with_d1(n, s, -1int, s.n as int, k) == 0);
    };
    assert forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)]
        row_hit(n, s, i0, i1) && hits_with(n, s, 0, proj_key(n, s, i0, i1)) > out_copies(res, 0, proj_key(n, s, i0, i1)) && res.len() > 0
        implies (if ((res[(res.len() as int) - 1].value as int)) == ((n.value@[i0] as int)) { if (res[(res.len() as int) - 1].name@) == ((s.name__dict@[s.name@[i1] as int]@)) { seq_le(res[(res.len() as int) - 1].tag@, (n.tag__dict@[n.tag@[i0] as int]@)) } else { seq_le(res[(res.len() as int) - 1].name@, (s.name__dict@[s.name@[i1] as int]@)) } } else { ((res[(res.len() as int) - 1].value as int)) >= ((n.value@[i0] as int)) }) by {
        assert(kle(out_key(res[res.len() - 1]), proj_key(n, s, i0, i1)));
    };
}

// ---------- the per-key max of the pure rows: a map from the packed (adsh code, tag code) to the group max ----------

spec fn is_pure(n: &Cols_num, q: int) -> bool {
    n.uom__dict@[n.uom@[q] as int]@ == "pure"@
}

spec fn pkey(n: &Cols_num, q: int) -> int {
    pk(n.adsh@[q] as int, n.tag@[q] as int)
}

spec fn fyf(s: &Cols_sub, q: int) -> bool {
    s.fy__valid@[q] && (s.fy@[q] as int) == 2022
}

// two num rows have equal adsh and tag STRINGS iff their packed code keys are equal (the dictionaries are pairwise distinct)
proof fn lemma_grp_eq(n: &Cols_num, a: int, b: int)
    requires
        valid_cols_num(n),
        0 <= a < n.n as int,
        0 <= b < n.n as int,
    ensures
        (n.adsh__dict@[n.adsh@[a] as int]@ == n.adsh__dict@[n.adsh@[b] as int]@ && n.tag__dict@[n.tag@[a] as int]@ == n.tag__dict@[n.tag@[b] as int]@)
            <==> pkey(n, a) == pkey(n, b),
{
    lemma_valid_dists_num(n);
    assert(n.adsh@.len() == n.n as int && n.tag@.len() == n.n as int);
    assert((n.adsh@[a] as int) < n.adsh__dict@.len());
    assert((n.adsh@[b] as int) < n.adsh__dict@.len());
    assert((n.tag@[a] as int) < n.tag__dict@.len());
    assert((n.tag@[b] as int) < n.tag__dict@.len());
    if n.adsh__dict@[n.adsh@[a] as int]@ == n.adsh__dict@[n.adsh@[b] as int]@ && n.tag__dict@[n.tag@[a] as int]@ == n.tag__dict@[n.tag@[b] as int]@ {
        lemma_dict_eq(n.adsh__dict@, n.adsh@[a] as int, n.adsh@[b] as int);
        lemma_dict_eq(n.tag__dict@, n.tag@[a] as int, n.tag@[b] as int);
    }
    if pkey(n, a) == pkey(n, b) {
        lemma_pk_inj(n.adsh@[a] as int, n.tag@[a] as int, n.adsh@[b] as int, n.tag@[b] as int);
    }
}

proof fn lemma_valid_dists_num(n: &Cols_num)
    requires
        valid_cols_num(n),
    ensures
        dist(n.adsh__dict@),
        dist(n.tag__dict@),
        dist(n.uom__dict@),
{
}

spec fn gm1(m: Map<i128, i128>, n: &Cols_num, j: int) -> bool {
    forall|key: i128| #![trigger m.contains_key(key)] m.contains_key(key) ==>
        exists|q: int| #![trigger n.value@[q]] 0 <= q < j && is_pure(n, q) && pkey(n, q) == key as int && n.value@[q] == m[key]
}

spec fn gm2(m: Map<i128, i128>, n: &Cols_num, j: int) -> bool {
    forall|q: int| #![trigger is_pure(n, q)] 0 <= q < j && is_pure(n, q) ==>
        (m.contains_key(pkey(n, q) as i128) && n.value@[q] <= m[pkey(n, q) as i128])
}

#[verifier::opaque]
spec fn gm(m: Map<i128, i128>, n: &Cols_num, j: int) -> bool {
    gm1(m, n, j) && gm2(m, n, j)
}

proof fn lemma_gm_val(m: Map<i128, i128>, n: &Cols_num, j: int, q: int)
    requires
        gm(m, n, j),
        0 <= q < j,
        is_pure(n, q),
    ensures
        m.contains_key(pkey(n, q) as i128),
        n.value@[q] <= m[pkey(n, q) as i128],
{
    reveal(gm);
    assert(gm2(m, n, j));
}

proof fn lemma_gm_att(m: Map<i128, i128>, n: &Cols_num, j: int, key: i128)
    requires
        gm(m, n, j),
        m.contains_key(key),
    ensures
        exists|q: int| #![trigger n.value@[q]] 0 <= q < j && is_pure(n, q) && pkey(n, q) == key as int && n.value@[q] == m[key],
{
    reveal(gm);
    assert(gm1(m, n, j));
}

proof fn lemma_gm_init(n: &Cols_num, m: Map<i128, i128>)
    requires
        m == Map::<i128, i128>::empty(),
    ensures
        gm(m, n, 0),
{
    reveal(gm);
    assert(gm1(m, n, 0));
    assert(gm2(m, n, 0));
}

proof fn lemma_gm1_skip(m: Map<i128, i128>, n: &Cols_num, j: int)
    requires
        gm(m, n, j),
        0 <= j,
    ensures
        gm1(m, n, j + 1),
{
    assert forall|key: i128| #![trigger m.contains_key(key)] m.contains_key(key) implies
        exists|q: int| #![trigger n.value@[q]] 0 <= q < j + 1 && is_pure(n, q) && pkey(n, q) == key as int && n.value@[q] == m[key] by {
        lemma_gm_att(m, n, j, key);
        let q = choose|q: int| #![trigger n.value@[q]] 0 <= q < j && is_pure(n, q) && pkey(n, q) == key as int && n.value@[q] == m[key];
        assert(0 <= q < j + 1 && is_pure(n, q) && pkey(n, q) == key as int && n.value@[q] == m[key]);
    };
}

proof fn lemma_gm2_skip(m: Map<i128, i128>, n: &Cols_num, j: int)
    requires
        gm(m, n, j),
        0 <= j,
        !is_pure(n, j),
    ensures
        gm2(m, n, j + 1),
{
    assert forall|q: int| #![trigger is_pure(n, q)] 0 <= q < j + 1 && is_pure(n, q) implies
        (m.contains_key(pkey(n, q) as i128) && n.value@[q] <= m[pkey(n, q) as i128]) by {
        assert(q < j);
        lemma_gm_val(m, n, j, q);
    };
}

proof fn lemma_gm_skip(m: Map<i128, i128>, n: &Cols_num, j: int)
    requires
        gm(m, n, j),
        0 <= j,
        !is_pure(n, j),
    ensures
        gm(m, n, j + 1),
{
    lemma_gm1_skip(m, n, j);
    lemma_gm2_skip(m, n, j);
    reveal(gm);
}

proof fn lemma_gm1_step(m0: Map<i128, i128>, m1: Map<i128, i128>, n: &Cols_num, j: int, key: i128, v: i128)
    requires
        gm(m0, n, j),
        0 <= j < n.n as int,
        is_pure(n, j),
        key as int == pkey(n, j),
        v == n.value@[j],
        (m0.contains_key(key) && v <= m0[key] && m1 == m0)
            || (m0.contains_key(key) && v > m0[key] && m1 == m0.insert(key, v))
            || (!m0.contains_key(key) && m1 == m0.insert(key, v)),
    ensures
        gm1(m1, n, j + 1),
{
    assert forall|k2: i128| #![trigger m1.contains_key(k2)] m1.contains_key(k2) implies
        exists|q: int| #![trigger n.value@[q]] 0 <= q < j + 1 && is_pure(n, q) && pkey(n, q) == k2 as int && n.value@[q] == m1[k2] by {
        if k2 == key && m1[key] == v {
            assert(0 <= j < j + 1 && is_pure(n, j) && pkey(n, j) == k2 as int && n.value@[j] == m1[k2]);
        } else {
            assert(m0.contains_key(k2));
            lemma_gm_att(m0, n, j, k2);
            let q = choose|q: int| #![trigger n.value@[q]] 0 <= q < j && is_pure(n, q) && pkey(n, q) == k2 as int && n.value@[q] == m0[k2];
            assert(0 <= q < j + 1 && is_pure(n, q) && pkey(n, q) == k2 as int && n.value@[q] == m1[k2]);
        }
    };
}

proof fn lemma_gm2_step(m0: Map<i128, i128>, m1: Map<i128, i128>, n: &Cols_num, j: int, key: i128, v: i128)
    requires
        gm(m0, n, j),
        0 <= j < n.n as int,
        is_pure(n, j),
        key as int == pkey(n, j),
        v == n.value@[j],
        (m0.contains_key(key) && v <= m0[key] && m1 == m0)
            || (m0.contains_key(key) && v > m0[key] && m1 == m0.insert(key, v))
            || (!m0.contains_key(key) && m1 == m0.insert(key, v)),
    ensures
        gm2(m1, n, j + 1),
{
    assert(pkey(n, j) as i128 == key);
    assert forall|q: int| #![trigger is_pure(n, q)] 0 <= q < j + 1 && is_pure(n, q) implies
        (m1.contains_key(pkey(n, q) as i128) && n.value@[q] <= m1[pkey(n, q) as i128]) by {
        if q == j {
            assert(m1.contains_key(key));
        } else {
            lemma_gm_val(m0, n, j, q);
            if (pkey(n, q) as i128) == key {
                assert(m0.contains_key(key));
            }
        }
    };
}

proof fn lemma_gm_step(m0: Map<i128, i128>, m1: Map<i128, i128>, n: &Cols_num, j: int, key: i128, v: i128)
    requires
        gm(m0, n, j),
        0 <= j < n.n as int,
        is_pure(n, j),
        key as int == pkey(n, j),
        v == n.value@[j],
        (m0.contains_key(key) && v <= m0[key] && m1 == m0)
            || (m0.contains_key(key) && v > m0[key] && m1 == m0.insert(key, v))
            || (!m0.contains_key(key) && m1 == m0.insert(key, v)),
    ensures
        gm(m1, n, j + 1),
{
    lemma_gm1_step(m0, m1, n, j, key, v);
    lemma_gm2_step(m0, m1, n, j, key, v);
    reveal(gm);
}

// a pure num row i is the max of its (adsh, tag) group exactly when its value equals the map entry
proof fn lemma_gm_sq(n: &Cols_num, s: &Cols_sub, m: Map<i128, i128>, i: int, i1: int)
    requires
        valid_cols_num(n),
        gm(m, n, n.n as int),
        0 <= i < n.n as int,
        is_pure(n, i),
    ensures
        m.contains_key(pkey(n, i) as i128),
        sq_1(n, s, i, i1, n.value@[i] as int) <==> n.value@[i] == m[pkey(n, i) as i128],
{
    reveal(gm);
    let key = pkey(n, i) as i128;
    lemma_pk_rng32(n.adsh@[i] as int, n.tag@[i] as int);
    assert(key as int == pkey(n, i));
    lemma_gm_val(m, n, n.n as int, i);
    assert(m.contains_key(key) && n.value@[i] <= m[key]);
    if n.value@[i] == m[key] {
        lemma_gm_att(m, n, n.n as int, key);
        let q = choose|q: int| #![trigger n.value@[q]] 0 <= q < n.n as int && is_pure(n, q) && pkey(n, q) == key as int && n.value@[q] == m[key];
        lemma_grp_eq(n, q, i);
        assert(0 <= q < n.n as int && (n.uom__dict@[n.uom@[q] as int]@ == "pure"@) && (n.adsh__dict@[n.adsh@[q] as int]@ == n.adsh__dict@[n.adsh@[i] as int]@) && (n.tag__dict@[n.tag@[q] as int]@ == n.tag__dict@[n.tag@[i] as int]@) && (n.value@[q] as int) == (n.value@[i] as int));
        assert forall|j0: int| #![trigger n.adsh@[j0]] 0 <= j0 < n.n as int && (((((((n.uom__dict@[n.uom@[j0] as int]@) == "pure"@) && true)) && ((n.adsh__dict@[n.adsh@[j0] as int]@) == (n.adsh__dict@[n.adsh@[i] as int]@))) && ((n.tag__dict@[n.tag@[j0] as int]@) == (n.tag__dict@[n.tag@[i] as int]@)))) implies (n.value@[j0] as int) <= (n.value@[i] as int) by {
            lemma_grp_eq(n, j0, i);
            assert(is_pure(n, j0));
            assert(pkey(n, j0) == pkey(n, i));
            lemma_gm_val(m, n, n.n as int, j0);
        };
    }
    if sq_1(n, s, i, i1, n.value@[i] as int) {
        let j0 = choose|j0: int| #![trigger n.adsh@[j0]] 0 <= j0 < n.n as int && (((((((n.uom__dict@[n.uom@[j0] as int]@) == "pure"@) && true)) && ((n.adsh__dict@[n.adsh@[j0] as int]@) == (n.adsh__dict@[n.adsh@[i] as int]@))) && ((n.tag__dict@[n.tag@[j0] as int]@) == (n.tag__dict@[n.tag@[i] as int]@)))) && (n.value@[j0] as int) == (n.value@[i] as int);
        // the group max is attained by a pure row of the group; sq_1's "forall" bounds it by value[i]
        lemma_gm_att(m, n, n.n as int, key);
        let q = choose|q: int| #![trigger n.value@[q]] 0 <= q < n.n as int && is_pure(n, q) && pkey(n, q) == key as int && n.value@[q] == m[key];
        lemma_grp_eq(n, q, i);
        assert(n.value@[q] as int <= n.value@[i] as int);
    }
}

// ---------- 'pure' literal code, the translation of num's adsh dictionary, the fy flags ----------

#[verifier::opaque]
spec fn pud(n: &Cols_num, pfound: bool, pcode: usize) -> bool {
    forall|q: int| #![trigger n.uom@[q]] 0 <= q < n.n as int ==> (is_pure(n, q) <==> (pfound && (n.uom@[q] as int) == (pcode as int)))
}

proof fn lemma_pud_get(n: &Cols_num, pfound: bool, pcode: usize, q: int)
    requires
        pud(n, pfound, pcode),
        0 <= q < n.n as int,
    ensures
        is_pure(n, q) <==> (pfound && (n.uom@[q] as int) == (pcode as int)),
{
    reveal(pud);
}

#[verifier::opaque]
spec fn trd(tr: Seq<usize>, n: &Cols_num, s: &Cols_sub, d: int) -> bool {
    &&& tr.len() == d
    &&& forall|q: int| #![trigger tr[q]] 0 <= q < d ==> (
        ((tr[q] as int) < s.adsh__dict@.len() && s.adsh__dict@[tr[q] as int]@ == n.adsh__dict@[q]@)
        || ((tr[q] as int) == s.adsh__dict@.len() && forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> s.adsh__dict@[c2]@ != n.adsh__dict@[q]@))
}

proof fn lemma_trd_get(tr: Seq<usize>, n: &Cols_num, s: &Cols_sub, d: int, q: int)
    requires
        trd(tr, n, s, d),
        0 <= q < d,
    ensures
        tr.len() == d,
        ((tr[q] as int) < s.adsh__dict@.len() && s.adsh__dict@[tr[q] as int]@ == n.adsh__dict@[q]@)
        || ((tr[q] as int) == s.adsh__dict@.len() && forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> s.adsh__dict@[c2]@ != n.adsh__dict@[q]@),
{
    reveal(trd);
}

proof fn lemma_trd_step(tr0: Seq<usize>, tr1: Seq<usize>, n: &Cols_num, s: &Cols_sub, d: int, v: usize)
    requires
        trd(tr0, n, s, d),
        tr1 == tr0.push(v),
        0 <= d,
        ((v as int) < s.adsh__dict@.len() && s.adsh__dict@[v as int]@ == n.adsh__dict@[d]@)
        || ((v as int) == s.adsh__dict@.len() && forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> s.adsh__dict@[c2]@ != n.adsh__dict@[d]@),
    ensures
        trd(tr1, n, s, d + 1),
{
    reveal(trd);
    assert forall|q: int| #![trigger tr1[q]] 0 <= q < d + 1 implies (
        ((tr1[q] as int) < s.adsh__dict@.len() && s.adsh__dict@[tr1[q] as int]@ == n.adsh__dict@[q]@)
        || ((tr1[q] as int) == s.adsh__dict@.len() && forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> s.adsh__dict@[c2]@ != n.adsh__dict@[q]@)) by {
        if q < d {
            assert(tr1[q] == tr0[q]);
        } else {
            assert(tr1[q] == v);
        }
    };
}

#[verifier::opaque]
spec fn pgd(pg: Seq<bool>, s: &Cols_sub, j: int) -> bool {
    &&& pg.len() == j
    &&& forall|q: int| #![trigger pg[q]] 0 <= q < j ==> pg[q] == fyf(s, q)
}

proof fn lemma_pgd_step(pg0: Seq<bool>, pg1: Seq<bool>, s: &Cols_sub, j: int, fl: bool)
    requires
        pgd(pg0, s, j),
        pg1 == pg0.push(fl),
        0 <= j,
        fl == fyf(s, j),
    ensures
        pgd(pg1, s, j + 1),
{
    reveal(pgd);
    assert forall|q: int| #![trigger pg1[q]] 0 <= q < j + 1 implies pg1[q] == fyf(s, q) by {
        if q < j {
            assert(pg1[q] == pg0[q]);
        }
    };
}

proof fn lemma_pgd_get(pg: Seq<bool>, s: &Cols_sub, j: int, q: int)
    requires
        pgd(pg, s, j),
        0 <= q < j,
    ensures
        pg.len() == j,
        pg[q] == fyf(s, q),
{
    reveal(pgd);
}

// ---------- chains over the filtered sub rows: head per sub-dictionary code, next-same-code pointer per row ----------

#[verifier::opaque]
spec fn ch(head: Seq<usize>, nx: Seq<usize>, keys: Seq<u32>, pf: Seq<bool>, j: int, sent: usize) -> bool {
    &&& nx.len() == j
    &&& pf.len() == j
    &&& 0 <= j <= keys.len()
    &&& j <= sent as int
    &&& forall|q: int| #![trigger keys[q]] 0 <= q < j ==> (keys[q] as int) < head.len()
    &&& forall|c: int| #![trigger head[c]] 0 <= c < head.len() ==>
            (head[c] == sent || ((head[c] as int) < j && pf[head[c] as int] && (keys[head[c] as int] as int) == c))
    &&& forall|q: int| #![trigger keys[q]] 0 <= q < j && pf[q] ==> (head[keys[q] as int] != sent && q <= head[keys[q] as int] as int)
    &&& forall|q: int| #![trigger nx[q]] 0 <= q < j && pf[q] && nx[q] == sent ==>
            (forall|r: int| #![trigger keys[r]] 0 <= r < q ==> !(pf[r] && keys[r] == keys[q]))
    &&& forall|q: int| #![trigger nx[q]] 0 <= q < j && pf[q] && nx[q] != sent ==>
            ((nx[q] as int) < q && pf[nx[q] as int] && keys[nx[q] as int] == keys[q]
                && (forall|r: int| #![trigger keys[r]] (nx[q] as int) < r < q ==> !(pf[r] && keys[r] == keys[q])))
}

proof fn lemma_ch_init(head: Seq<usize>, keys: Seq<u32>, sent: usize)
    requires
        forall|c: int| #![trigger head[c]] 0 <= c < head.len() ==> head[c] == sent,
    ensures
        ch(head, Seq::<usize>::empty(), keys, Seq::<bool>::empty(), 0, sent),
{
    reveal(ch);
}

proof fn lemma_ch_own(head: Seq<usize>, nx: Seq<usize>, keys: Seq<u32>, pf: Seq<bool>, j: int, sent: usize, q: int)
    requires
        ch(head, nx, keys, pf, j, sent),
        0 <= q < j,
        pf[q],
    ensures
        (keys[q] as int) < head.len(),
        head[keys[q] as int] != sent,
        q <= head[keys[q] as int] as int,
{
    reveal(ch);
}

proof fn lemma_ch_head(head: Seq<usize>, nx: Seq<usize>, keys: Seq<u32>, pf: Seq<bool>, j: int, sent: usize, c: int)
    requires
        ch(head, nx, keys, pf, j, sent),
        0 <= c < head.len(),
        head[c] != sent,
    ensures
        (head[c] as int) < j,
        pf[head[c] as int],
        (keys[head[c] as int] as int) == c,
{
    reveal(ch);
}

proof fn lemma_ch_next(head: Seq<usize>, nx: Seq<usize>, keys: Seq<u32>, pf: Seq<bool>, j: int, sent: usize, q: int)
    requires
        ch(head, nx, keys, pf, j, sent),
        0 <= q < j,
        pf[q],
    ensures
        nx.len() == j,
        nx[q] == sent ==> (forall|r: int| #![trigger keys[r]] 0 <= r < q ==> !(pf[r] && keys[r] == keys[q])),
        nx[q] != sent ==> ((nx[q] as int) < q && pf[nx[q] as int] && keys[nx[q] as int] == keys[q]
            && (forall|r: int| #![trigger keys[r]] (nx[q] as int) < r < q ==> !(pf[r] && keys[r] == keys[q]))),
{
    reveal(ch);
}

proof fn lemma_ch_step(
    h0: Seq<usize>,
    h1: Seq<usize>,
    nx0: Seq<usize>,
    nx1: Seq<usize>,
    keys: Seq<u32>,
    pf0: Seq<bool>,
    pf1: Seq<bool>,
    j: int,
    sent: usize,
    flag: bool,
    v: usize,
)
    requires
        ch(h0, nx0, keys, pf0, j, sent),
        0 <= j < keys.len(),
        j < sent as int,
        (keys[j] as int) < h0.len(),
        pf1 == pf0.push(flag),
        nx1 == nx0.push(v),
        !flag ==> (h1 == h0 && v == sent),
        flag ==> (h1 == h0.update(keys[j] as int, j as usize) && v == h0[keys[j] as int]),
    ensures
        ch(h1, nx1, keys, pf1, j + 1, sent),
{
    reveal(ch);
    let kj = keys[j] as int;
    assert(pf1.len() == j + 1);
    assert(nx1.len() == j + 1);
    assert(h1.len() == h0.len());
    assert forall|c: int| #![trigger h1[c]] 0 <= c < h1.len() implies
        (h1[c] == sent || ((h1[c] as int) < j + 1 && pf1[h1[c] as int] && (keys[h1[c] as int] as int) == c)) by {
        if flag && c == kj {
            assert(h1[c] == j as usize);
            assert(pf1[j] == flag);
        } else {
            assert(h1[c] == h0[c]);
            if h0[c] != sent {
                assert(pf1[h0[c] as int] == pf0[h0[c] as int]);
            }
        }
    };
    assert forall|q: int| #![trigger keys[q]] 0 <= q < j + 1 && pf1[q] implies (h1[keys[q] as int] != sent && q <= h1[keys[q] as int] as int) by {
        if q == j {
            assert(flag);
            assert(h1[kj] == j as usize);
        } else {
            assert(pf1[q] == pf0[q]);
            if flag && (keys[q] as int) == kj {
                assert(h1[kj] == j as usize);
            } else {
                assert(h1[keys[q] as int] == h0[keys[q] as int]);
            }
        }
    };
    assert forall|q: int| #![trigger nx1[q]] 0 <= q < j + 1 && pf1[q] && nx1[q] == sent implies
        (forall|r: int| #![trigger keys[r]] 0 <= r < q ==> !(pf1[r] && keys[r] == keys[q])) by {
        if q < j {
            assert(nx1[q] == nx0[q]);
            assert(pf1[q] == pf0[q]);
            assert forall|r: int| #![trigger keys[r]] 0 <= r < q implies !(pf1[r] && keys[r] == keys[q]) by {
                assert(pf1[r] == pf0[r]);
            };
        } else {
            assert(flag);
            assert(v == sent);
            assert forall|r: int| #![trigger keys[r]] 0 <= r < q implies !(pf1[r] && keys[r] == keys[q]) by {
                assert(pf1[r] == pf0[r]);
                if pf1[r] && keys[r] == keys[j] {
                    assert(h0[keys[r] as int] != sent);
                    assert(v == h0[kj]);
                }
            };
        }
    };
    assert forall|q: int| #![trigger nx1[q]] 0 <= q < j + 1 && pf1[q] && nx1[q] != sent implies
        ((nx1[q] as int) < q && pf1[nx1[q] as int] && keys[nx1[q] as int] == keys[q]
            && (forall|r: int| #![trigger keys[r]] (nx1[q] as int) < r < q ==> !(pf1[r] && keys[r] == keys[q]))) by {
        if q < j {
            assert(nx1[q] == nx0[q]);
            assert(pf1[q] == pf0[q]);
            assert(pf1[nx0[q] as int] == pf0[nx0[q] as int]);
            assert forall|r: int| #![trigger keys[r]] (nx1[q] as int) < r < q implies !(pf1[r] && keys[r] == keys[q]) by {
                assert(pf1[r] == pf0[r]);
            };
        } else {
            assert(flag);
            let h = h0[kj];
            assert(v == h);
            assert(h != sent);
            assert((h as int) < j);
            assert(pf1[h as int] == pf0[h as int]);
            assert forall|r: int| #![trigger keys[r]] (nx1[q] as int) < r < q implies !(pf1[r] && keys[r] == keys[q]) by {
                assert(pf1[r] == pf0[r]);
                if pf1[r] && keys[r] == keys[j] {
                    assert(r <= h0[keys[r] as int] as int);
                }
            };
        }
    };
}

// ---------- which sub rows a candidate num row hits ----------

// a num row that is NOT the group max (or not pure) hits no sub row
proof fn lemma_no_hit_a(n: &Cols_num, s: &Cols_sub, m: Map<i128, i128>, i: int)
    requires
        valid_cols_num(n),
        gm(m, n, n.n as int),
        0 <= i < n.n as int,
        !is_pure(n, i) || n.value@[i] != m[pkey(n, i) as i128],
    ensures
        forall|r: int| #![trigger row_hit(n, s, i, r)] !row_hit(n, s, i, r),
{
    assert forall|r: int| #![trigger row_hit(n, s, i, r)] !row_hit(n, s, i, r) by {
        if row_hit(n, s, i, r) {
            assert(is_pure(n, i));
            lemma_gm_sq(n, s, m, i, r);
        }
    };
}

// a num row whose adsh string is in no entry of sub's dictionary hits no sub row
proof fn lemma_no_hit_b(n: &Cols_num, s: &Cols_sub, i: int)
    requires
        valid_cols_sub(s),
        0 <= i < n.n as int,
        forall|c2: int| 0 <= c2 < s.adsh__dict@.len() ==> s.adsh__dict@[c2]@ != n.adsh__dict@[n.adsh@[i] as int]@,
    ensures
        forall|r: int| #![trigger row_hit(n, s, i, r)] !row_hit(n, s, i, r),
{
    assert forall|r: int| #![trigger row_hit(n, s, i, r)] !row_hit(n, s, i, r) by {
        if row_hit(n, s, i, r) {
            assert(s.adsh@.len() == s.n as int);
            assert((s.adsh@[r] as int) < s.adsh__dict@.len());
        }
    };
}

// a group-max pure row whose adsh string is entry t of sub's dictionary hits exactly the filtered sub rows with code t
proof fn lemma_hit_iff(n: &Cols_num, s: &Cols_sub, m: Map<i128, i128>, i: int, r: int, t: int)
    requires
        valid_cols_num(n),
        valid_cols_sub(s),
        gm(m, n, n.n as int),
        0 <= i < n.n as int,
        0 <= r < s.n as int,
        is_pure(n, i),
        n.value@[i] == m[pkey(n, i) as i128],
        0 <= t < s.adsh__dict@.len(),
        s.adsh__dict@[t]@ == n.adsh__dict@[n.adsh@[i] as int]@,
    ensures
        row_hit(n, s, i, r) <==> (fyf(s, r) && (s.adsh@[r] as int) == t),
{
    lemma_valid_dists(n, s);
    lemma_gm_sq(n, s, m, i, r);
    assert(s.adsh@.len() == s.n as int);
    assert(s.fy@.len() == s.n as int);
    assert(s.fy__valid@.len() == s.n as int);
    assert((s.adsh@[r] as int) < s.adsh__dict@.len());
    if row_hit(n, s, i, r) {
        lemma_dict_eq(s.adsh__dict@, s.adsh@[r] as int, t);
    }
    if fyf(s, r) && (s.adsh@[r] as int) == t {
        assert(s.adsh__dict@[s.adsh@[r] as int]@ == n.adsh__dict@[n.adsh@[i] as int]@);
    }
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    proof {
        lemma_valid_dists(n, s);
    }
    // 0. the code of 'pure' in num's uom dictionary, looked up once
    let pure: String = String::from_str("pure");
    let mut pcode: usize = 0;
    let mut pfound: bool = false;
    let mut kk: usize = 0;
    while kk < n.uom__dict.len()
        invariant
            kk <= n.uom__dict@.len(),
            pure@ == "pure"@,
            valid_cols_num(n),
            pfound ==> pcode < kk && n.uom__dict@[pcode as int]@ == "pure"@,
            !pfound ==> forall|m: int| 0 <= m < kk as int ==> n.uom__dict@[m]@ != "pure"@,
        decreases n.uom__dict@.len() - kk,
    {
        if !pfound && n.uom__dict[kk] == pure {
            pfound = true;
            pcode = kk;
        }
        kk += 1;
    }
    proof {
        assert forall|j: int| #![trigger n.uom@[j]] 0 <= j < n.n as int implies (is_pure(n, j) <==> (pfound && (n.uom@[j] as int) == (pcode as int))) by {
            assert(n.uom@.len() == n.n as int);
            assert((n.uom@[j] as int) < n.uom__dict@.len());
            if pfound {
                if (n.uom@[j] as int) != (pcode as int) {
                    let a = if (n.uom@[j] as int) < (pcode as int) { n.uom@[j] as int } else { pcode as int };
                    let b = if (n.uom@[j] as int) < (pcode as int) { pcode as int } else { n.uom@[j] as int };
                    assert(n.uom__dict@[a]@ != n.uom__dict@[b]@);
                }
            }
        };
        reveal(pud);
    }
    let scodes: usize = s.adsh__dict.len();
    let ncodes: usize = n.adsh__dict.len();
    // 1. the group max of the pure rows, one hash map keyed by the packed (adsh code, tag code)
    let mut mx: HashMapWithView<i128, i128> = HashMapWithView::new();
    proof {
        lemma_gm_init(n, mx@);
    }
    let mut ja: usize = 0;
    while ja < n.n
        invariant
            ja <= n.n,
            valid_cols_num(n),
            pud(n, pfound, pcode),
            gm(mx@, n, ja as int),
        decreases n.n - ja,
    {
        proof {
            assert(n.adsh@.len() == n.n as int);
            assert(n.tag@.len() == n.n as int);
            assert(n.uom@.len() == n.n as int);
            assert(n.value@.len() == n.n as int);
            lemma_pud_get(n, pfound, pcode, ja as int);
        }
        let ac = n.adsh[ja];
        let tg = n.tag[ja];
        let v = n.value[ja];
        let um = n.uom[ja] as usize;
        if pfound && um == pcode {
            proof {
                lemma_pk_rng32(ac as int, tg as int);
            }
            let key: i128 = (ac as i128) * 4294967296 + (tg as i128);
            let ghost m0 = mx@;
            proof {
                assert(key as int == pkey(n, ja as int));
            }
            if mx.contains_key(&key) {
                let old = *mx.get(&key).unwrap();
                if v > old {
                    mx.insert(key, v);
                }
            } else {
                mx.insert(key, v);
            }
            proof {
                lemma_gm_step(m0, mx@, n, ja as int, key, v);
            }
        } else {
            proof {
                lemma_gm_skip(mx@, n, ja as int);
            }
        }
        ja += 1;
    }
    // 2. sub's filtered rows chained by sub-dictionary code (head per code, next pointer per row)
    let mut sh: Vec<usize> = Vec::new();
    let mut z: usize = 0;
    while z < scodes
        invariant
            z <= scodes,
            sh@.len() == z as int,
            forall|c: int| #![trigger sh@[c]] 0 <= c < z as int ==> sh@[c] == s.n,
        decreases scodes - z,
    {
        sh.push(s.n);
        z += 1;
    }
    let mut sx: Vec<usize> = Vec::with_capacity(s.n);
    let ghost mut pg: Seq<bool> = Seq::<bool>::empty();
    let mut jb: usize = 0;
    proof {
        lemma_ch_init(sh@, s.adsh@, s.n);
        reveal(pgd);
    }
    while jb < s.n
        invariant
            jb <= s.n,
            valid_cols_sub(s),
            scodes == s.adsh__dict@.len(),
            sh@.len() == scodes as int,
            ch(sh@, sx@, s.adsh@, pg, jb as int, s.n),
            pgd(pg, s, jb as int),
        decreases s.n - jb,
    {
        proof {
            assert(s.adsh@.len() == s.n as int);
            assert(s.fy@.len() == s.n as int);
            assert(s.fy__valid@.len() == s.n as int);
            assert((s.adsh@[jb as int] as int) < s.adsh__dict@.len());
        }
        let fl = s.fy__valid[jb] && s.fy[jb] == 2022;
        let kc = s.adsh[jb] as usize;
        let ghost h0 = sh@;
        let ghost nx0 = sx@;
        let ghost pg0 = pg;
        let mut v: usize = s.n;
        if fl {
            v = sh[kc];
            sh.set(kc, jb);
        }
        sx.push(v);
        proof {
            pg = pg.push(fl);
            lemma_ch_step(h0, sh@, nx0, sx@, s.adsh@, pg0, pg, jb as int, s.n, fl, v);
            lemma_pgd_step(pg0, pg, s, jb as int, fl);
        }
        jb += 1;
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
    // 3b. tr[d]: the sub code of num dictionary entry d (scodes: none)
    let mut tr: Vec<usize> = Vec::new();
    let mut d: usize = 0;
    proof {
        reveal(trd);
    }
    while d < ncodes
        invariant
            d <= ncodes,
            ncodes == n.adsh__dict@.len(),
            scodes == s.adsh__dict@.len(),
            valid_cols_sub(s),
            trd(tr@, n, s, d as int),
            forall|k: Seq<char>| #[trigger] smap@.contains_key(k) ==> (smap@[k] as int) < scodes as int && s.adsh__dict@[smap@[k] as int]@ == k,
            forall|t: int| 0 <= t < scodes as int ==> #[trigger] smap@.contains_key(s.adsh__dict@[t]@),
        decreases ncodes - d,
    {
        let found_code = smap.get(n.adsh__dict[d].as_str());
        let ghost tr0 = tr@;
        match found_code {
            Some(v) => {
                proof {
                    let k = n.adsh__dict@[d as int]@;
                    assert(smap@.contains_key(k));
                    assert(smap@[k] == *v);
                }
                tr.push(*v);
                proof {
                    lemma_trd_step(tr0, tr@, n, s, d as int, *v);
                }
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
                proof {
                    lemma_trd_step(tr0, tr@, n, s, d as int, scodes);
                }
            }
        }
        d += 1;
    }
    proof {
        reveal(ch);
        assert(sx@.len() == s.n as int);
    }
    // 4. one backward pass over num: a group-max pure row joins its filtered sub rows, newest first, into the top 100
    let mut res: Vec<OutRow> = Vec::new();
    let mut i: usize = n.n;
    proof {
        lemma_tk_init(n, s);
        assert(res@ == Seq::<OutRow>::empty());
    }
    while i > 0
        invariant
            i <= n.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            ncodes == n.adsh__dict@.len(),
            scodes == s.adsh__dict@.len(),
            sh@.len() == scodes as int,
            sx@.len() == s.n as int,
            pud(n, pfound, pcode),
            gm(mx@, n, n.n as int),
            trd(tr@, n, s, ncodes as int),
            ch(sh@, sx@, s.adsh@, pg, s.n as int, s.n),
            pgd(pg, s, s.n as int),
            tk(res@, n, s, i as int - 1, s.n as int),
        decreases i,
    {
        i -= 1;
        proof {
            assert(n.adsh@.len() == n.n as int);
            assert(n.tag@.len() == n.n as int);
            assert(n.uom@.len() == n.n as int);
            assert(n.value@.len() == n.n as int);
            assert(s.adsh@.len() == s.n as int);
            assert(s.name@.len() == s.n as int);
            assert((n.adsh@[i as int] as int) < n.adsh__dict@.len());
            assert((n.tag@[i as int] as int) < n.tag__dict@.len());
            lemma_pud_get(n, pfound, pcode, i as int);
        }
        let ac = n.adsh[i] as usize;
        let tg = n.tag[i] as usize;
        let vi = n.value[i];
        let um = n.uom[i] as usize;
        let mut t: usize = scodes;
        let mut cand: bool = false;
        if pfound && um == pcode {
            proof {
                reveal(gm);
                lemma_pk_rng32(n.adsh@[i as int] as int, n.tag@[i as int] as int);
                lemma_gm_sq(n, s, mx@, i as int, 0);
            }
            let key: i128 = (n.adsh[i] as i128) * 4294967296 + (n.tag[i] as i128);
            proof {
                assert(key as int == pkey(n, i as int));
                assert(pkey(n, i as int) as i128 == key);
            }
            let mv = *mx.get(&key).unwrap();
            if vi == mv {
                proof {
                    lemma_trd_get(tr@, n, s, ncodes as int, ac as int);
                }
                cand = true;
                t = tr[ac];
            }
        }
        proof {
            assert(cand == (is_pure(n, i as int) && n.value@[i as int] == mx@[pkey(n, i as int) as i128]));
            assert(cand ==> t == tr@[ac as int]);
            assert(!cand ==> t == scodes);
        }
        if t < scodes {
            // a group-max pure row i whose adsh string is entry t of sub's dictionary
            proof {
                lemma_trd_get(tr@, n, s, ncodes as int, ac as int);
                assert(cand);
                assert(is_pure(n, i as int));
                lemma_gm_sq(n, s, mx@, i as int, 0);
                assert(n.value@[i as int] == mx@[pkey(n, i as int) as i128]);
                assert(t == tr@[ac as int]);
            }
            let mut c: usize = sh[t];
            proof {
                if c != s.n {
                    lemma_ch_head(sh@, sx@, s.adsh@, pg, s.n as int, s.n, t as int);
                    assert forall|r: int| #![trigger row_hit(n, s, i as int, r)] (c as int) + 1 <= r < s.n as int implies !row_hit(n, s, i as int, r) by {
                        lemma_hit_iff(n, s, mx@, i as int, r, t as int);
                        if row_hit(n, s, i as int, r) {
                            lemma_pgd_get(pg, s, s.n as int, r);
                            lemma_ch_own(sh@, sx@, s.adsh@, pg, s.n as int, s.n, r);
                        }
                    };
                    lemma_range_skip(res@, n, s, i as int, c as int + 1, s.n as int);
                } else {
                    assert forall|r: int| #![trigger row_hit(n, s, i as int, r)] 0 <= r < s.n as int implies !row_hit(n, s, i as int, r) by {
                        lemma_hit_iff(n, s, mx@, i as int, r, t as int);
                        if row_hit(n, s, i as int, r) {
                            lemma_pgd_get(pg, s, s.n as int, r);
                            lemma_ch_own(sh@, sx@, s.adsh@, pg, s.n as int, s.n, r);
                        }
                    };
                    lemma_range_skip(res@, n, s, i as int, 0, s.n as int);
                }
            }
            while c != s.n
                invariant
                    c <= s.n,
                    i < n.n,
                    valid_cols_num(n),
                    valid_cols_sub(s),
                    ch(sh@, sx@, s.adsh@, pg, s.n as int, s.n),
                    pgd(pg, s, s.n as int),
                    gm(mx@, n, n.n as int),
                    sh@.len() == scodes as int,
                    sx@.len() == s.n as int,
                    scodes == s.adsh__dict@.len(),
                    t < scodes,
                    s.adsh__dict@[t as int]@ == n.adsh__dict@[n.adsh@[i as int] as int]@,
                    is_pure(n, i as int),
                    n.value@[i as int] == vi,
                    n.value@[i as int] == mx@[pkey(n, i as int) as i128],
                    tg as int == n.tag@[i as int] as int,
                    tg < n.tag__dict@.len(),
                    c != s.n ==> (pg[c as int] && (s.adsh@[c as int] as int) == t as int && tk(res@, n, s, i as int, c as int + 1)),
                    c == s.n ==> tk(res@, n, s, i as int, 0),
                decreases if c == s.n { 0int } else { c as int + 1 },
            {
                proof {
                    lemma_ch_next(sh@, sx@, s.adsh@, pg, s.n as int, s.n, c as int);
                    lemma_pgd_get(pg, s, s.n as int, c as int);
                    assert(s.name@.len() == s.n as int);
                    assert((s.name@[c as int] as int) < s.name__dict@.len());
                    lemma_hit_iff(n, s, mx@, i as int, c as int, t as int);
                    assert(row_hit(n, s, i as int, c as int));
                }
                let x = OutRow { name: s.name__dict[s.name[c] as usize].clone(), tag: n.tag__dict[tg].clone(), value: vi };
                let ghost old = res@;
                proof {
                    assert(out_key(x) == proj_key(n, s, i as int, c as int));
                }
                let mut p: usize = 0;
                let mut go: bool = true;
                while go
                    invariant
                        p <= res@.len(),
                        res@ == old,
                        x.value == vi,
                        forall|q: int| #![trigger res@[q]] 0 <= q < p as int ==> kle(out_key(res@[q]), out_key(x)),
                        go || p == res@.len() || !kle(out_key(res@[p as int]), out_key(x)),
                    decreases res@.len() - p + (if go { 1int } else { 0int }),
                {
                    if p >= res.len() {
                        go = false;
                    } else {
                        let ple: bool;
                        let rv = res[p].value;
                        if rv != vi {
                            ple = rv > vi;
                            proof {
                                assert(res@[p as int].value == rv);
                                assert(ple == kle(out_key(res@[p as int]), out_key(x)));
                            }
                        } else if res[p].name == x.name {
                            let la = res[p].tag.as_str().unicode_len();
                            let lb = x.tag.as_str().unicode_len();
                            let mut u: usize = 0;
                            while u < la && u < lb && res[p].tag.as_str().get_char(u) == x.tag.as_str().get_char(u)
                                invariant
                                    u <= la,
                                    u <= lb,
                                    p < res@.len(),
                                    la as int == res@[p as int].tag@.len(),
                                    lb as int == x.tag@.len(),
                                    forall|w: int| 0 <= w < u as int ==> res@[p as int].tag@[w] == x.tag@[w],
                                decreases la - u,
                            {
                                u += 1;
                            }
                            proof {
                                lemma_le_stop(res@[p as int].tag@, x.tag@, u as int);
                            }
                            ple = u == la || (u < lb && res[p].tag.as_str().get_char(u) < x.tag.as_str().get_char(u));
                            proof {
                                assert(res@[p as int].value == rv);
                                assert(res@[p as int].name@ == x.name@);
                                assert(ple == seq_le(res@[p as int].tag@, x.tag@));
                                assert(x.value == vi);
                                assert(out_key(res@[p as int]).2 == out_key(x).2);
                                assert(out_key(res@[p as int]).0 == out_key(x).0);
                                assert(out_key(res@[p as int]).1 == res@[p as int].tag@ && out_key(x).1 == x.tag@);
                                assert(ple == kle(out_key(res@[p as int]), out_key(x)));
                            }
                        } else {
                            let la = res[p].name.as_str().unicode_len();
                            let lb = x.name.as_str().unicode_len();
                            let mut u: usize = 0;
                            while u < la && u < lb && res[p].name.as_str().get_char(u) == x.name.as_str().get_char(u)
                                invariant
                                    u <= la,
                                    u <= lb,
                                    p < res@.len(),
                                    la as int == res@[p as int].name@.len(),
                                    lb as int == x.name@.len(),
                                    forall|w: int| 0 <= w < u as int ==> res@[p as int].name@[w] == x.name@[w],
                                decreases la - u,
                            {
                                u += 1;
                            }
                            proof {
                                lemma_le_stop(res@[p as int].name@, x.name@, u as int);
                            }
                            ple = u == la || (u < lb && res[p].name.as_str().get_char(u) < x.name.as_str().get_char(u));
                            proof {
                                assert(res@[p as int].value == rv);
                                assert(res@[p as int].name@ != x.name@);
                                assert(ple == seq_le(res@[p as int].name@, x.name@));
                                assert(x.value == vi);
                                assert(out_key(res@[p as int]).2 == out_key(x).2);
                                assert(out_key(res@[p as int]).0 != out_key(x).0);
                                assert(out_key(res@[p as int]).0 == res@[p as int].name@ && out_key(x).0 == x.name@);
                                assert(ple == kle(out_key(res@[p as int]), out_key(x)));
                            }
                        }
                        if ple {
                            p += 1;
                        } else {
                            go = false;
                        }
                    }
                }
                if p == 100 {
                    proof {
                        lemma_tk_hit(old, res@, n, s, i as int, c as int, x, p as int);
                    }
                } else {
                    res.insert(p, x);
                    if res.len() > 100 {
                        let ghost mid = res@;
                        let _y = res.pop();
                        proof {
                            assert(res@ == mid.drop_last());
                        }
                    }
                    proof {
                        lemma_tk_hit(old, res@, n, s, i as int, c as int, x, p as int);
                    }
                }
                let c2 = sx[c];
                proof {
                    assert(s.adsh@[c as int] as int == t as int);
                    if c2 == s.n {
                        assert forall|r: int| #![trigger row_hit(n, s, i as int, r)] 0 <= r < c as int implies !row_hit(n, s, i as int, r) by {
                            lemma_hit_iff(n, s, mx@, i as int, r, t as int);
                            if row_hit(n, s, i as int, r) {
                                lemma_pgd_get(pg, s, s.n as int, r);
                            }
                        };
                        lemma_range_skip(res@, n, s, i as int, 0, c as int);
                    } else {
                        assert forall|r: int| #![trigger row_hit(n, s, i as int, r)] (c2 as int) + 1 <= r < c as int implies !row_hit(n, s, i as int, r) by {
                            lemma_hit_iff(n, s, mx@, i as int, r, t as int);
                            if row_hit(n, s, i as int, r) {
                                lemma_pgd_get(pg, s, s.n as int, r);
                            }
                        };
                        lemma_range_skip(res@, n, s, i as int, c2 as int + 1, c as int);
                    }
                }
                c = c2;
            }
        } else {
            proof {
                if cand {
                    lemma_trd_get(tr@, n, s, ncodes as int, ac as int);
                    lemma_no_hit_b(n, s, i as int);
                } else {
                    lemma_no_hit_a(n, s, mx@, i as int);
                }
                lemma_range_skip(res@, n, s, i as int, 0, s.n as int);
            }
        }
        proof {
            lemma_tk_shift(res@, n, s, i as int);
        }
    }
    proof {
        lemma_tk_final(res@, n, s);
    }
    res
// AGENT_EDIT_END
