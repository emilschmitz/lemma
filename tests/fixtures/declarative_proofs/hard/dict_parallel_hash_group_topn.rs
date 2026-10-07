// Worked example (SEC shape, PARALLEL, hash GROUP BY with merge): single table, GROUP BY an integer key with a wide range (`ddate`: no dense array), COUNT(*) and SUM,
// WHERE a dictionary string filter and a value filter, ORDER BY the sum DESC LIMIT 20. Structure: (1) the dictionary code of the string literal is looked up once;
// (2) FOUR workers (vstd thread spawn/join, one per physical core), each folds a contiguous row range BACKWARDS into its OWN hash table (key -> position in parallel Vecs of
// keys / counts / sums / witness rows) with the telescoping invariant per key `cs == count_c(lo.., key) - count_c(hi.., key)` (the spec's folds are suffix folds);
// (3) the main thread merges the workers' tables back to front by key into the global table (invariant: after merging workers m.. the table equals the fold over their ranges);
// (4) the same top-N selection loop (`used`/`pos`/`sel`) and the four host closing lemmas as the join top-N example. The worker fold and the merge step are NESTED fns at the
// top of the run_query body (the helpers region admits only proof fn / spec fn items; a struct is not admitted either: the table is a 5-tuple). A `&mut` parameter's
// postcondition is written with `final(g)` / `old(g)`. The `Err` arm of a join re-runs the range inline. Proved by a manual prover (Sonnet 5.5) from the real agent prompt on
// 2026-10-07; real SEC kernel 203 ms vs 297 ms for DuckDB on 8 threads (1.46x; 5.6x vs 1-thread DuckDB), x86-64-v3.
// AGENT_HELPERS_START
proof fn lemma_fold_step(t: &Cols_num, i: int, k: int)
    requires
        0 <= i < t.n as int,
    ensures
        count_c(t, i, k) == (if row_hit(t, i) && key_at(t, i) == k { 1int } else { 0int }) + count_c(t, i + 1, k),
        sum_s(t, i, k) == (if row_hit(t, i) && key_at(t, i) == k { sum_s_val(t, i) } else { 0int }) + sum_s(t, i + 1, k),
{
    reveal_with_fuel(count_c, 2);
    reveal_with_fuel(sum_s, 2);
}

proof fn lemma_no_hit_zero(t: &Cols_num, i: int, k: int)
    requires
        0 <= i,
        forall|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int ==> !(row_hit(t, j) && key_at(t, j) == k),
    ensures
        count_c(t, i, k) == 0,
        sum_s(t, i, k) == 0,
    decreases t.n as int - i,
{
    if i < t.n as int {
        lemma_no_hit_zero(t, i + 1, k);
        lemma_fold_step(t, i, k);
    }
}

// The code of "USD" in the dictionary (or the dictionary length when absent) decides row_hit by one integer comparison.
proof fn lemma_hit_iff(t: &Cols_num, ucode: int, i: int)
    requires
        valid_cols_num(t),
        0 <= ucode <= t.uom__dict@.len(),
        ucode < t.uom__dict@.len() ==> t.uom__dict@[ucode]@ == "USD"@,
        forall|q: int| 0 <= q < ucode ==> t.uom__dict@[q]@ != "USD"@,
        0 <= i < t.n as int,
    ensures
        row_hit(t, i) <==> (t.uom@[i] as int == ucode && t.value@[i] as int > 0),
{
    let u = t.uom@[i] as int;
    assert(u < t.uom__dict@.len());
    if t.uom__dict@[u]@ == "USD"@ {
        assert(u >= ucode);
        if u > ucode {
            assert(t.uom__dict@[ucode]@ != t.uom__dict@[u]@);
        }
    }
}

spec fn p1_inv(t: &Cols_num, ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, idx: Map<i64, usize>, wit: Seq<int>, i: int) -> bool {
    &&& cs.len() == ks.len()
    &&& ss.len() == ks.len()
    &&& wit.len() == ks.len()
    &&& forall|r: int| #![trigger ks[r]] 0 <= r < ks.len() ==> idx.contains_key(ks[r]) && idx[ks[r]] as int == r
    &&& forall|k: i64| #![trigger idx.contains_key(k)] idx.contains_key(k) ==> (idx[k] as int) < ks.len() && ks[idx[k] as int] == k
    &&& forall|r: int| #![trigger cs[r]] 0 <= r < ks.len() ==> cs[r] as int == count_c(t, i, ks[r] as int)
            && cs[r] as int <= t.n as int - i
            && ss[r] as int == sum_s(t, i, ks[r] as int)
            && -((t.n as int - i) * 46116860184273879039999int) <= ss[r] as int
            && ss[r] as int <= (t.n as int - i) * 46116860184273879039999int
    &&& forall|r: int| #![trigger wit[r]] 0 <= r < ks.len() ==> row_hit(t, wit[r]) && key_at(t, wit[r]) == ks[r] as int
    &&& forall|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j) ==> idx.contains_key(t.ddate@[j])
}

proof fn lemma_p1_nohit(t: &Cols_num, ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, idx: Map<i64, usize>, wit: Seq<int>, i: int)
    requires
        valid_cols_num(t),
        p1_inv(t, ks, cs, ss, idx, wit, i + 1),
        0 <= i < t.n as int,
        !row_hit(t, i),
    ensures
        p1_inv(t, ks, cs, ss, idx, wit, i),
{
    assert forall|r: int| #![trigger cs[r]] 0 <= r < ks.len() implies cs[r] as int == count_c(t, i, ks[r] as int)
            && cs[r] as int <= t.n as int - i
            && ss[r] as int == sum_s(t, i, ks[r] as int)
            && -((t.n as int - i) * 46116860184273879039999int) <= ss[r] as int
            && ss[r] as int <= (t.n as int - i) * 46116860184273879039999int by {
        lemma_fold_step(t, i, ks[r] as int);
    }
    assert forall|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j) implies idx.contains_key(t.ddate@[j]) by {
        assert(j != i);
    }
}

proof fn lemma_p1_hit_existing(t: &Cols_num, ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, idx: Map<i64, usize>, wit: Seq<int>, i: int, p: int, nc: u64, ns: i128)
    requires
        valid_cols_num(t),
        p1_inv(t, ks, cs, ss, idx, wit, i + 1),
        0 <= i < t.n as int,
        row_hit(t, i),
        idx.contains_key(t.ddate@[i]),
        idx[t.ddate@[i]] as int == p,
        0 <= p < ks.len(),
        nc as int == cs[p] as int + 1,
        ns as int == ss[p] as int + t.value@[i] as int,
    ensures
        p1_inv(t, ks, cs.update(p, nc), ss.update(p, ns), idx, wit, i),
{
    let k = t.ddate@[i];
    assert(key_at(t, i) == k as int);
    assert(ks[p] == k);
    assert(t.value@[i] as int <= 46116860184273879039999int && t.value@[i] as int >= -46116860184273879039999int);
    assert forall|r: int| #![trigger cs.update(p, nc)[r]] 0 <= r < ks.len() implies cs.update(p, nc)[r] as int == count_c(t, i, ks[r] as int)
            && cs.update(p, nc)[r] as int <= t.n as int - i
            && ss.update(p, ns)[r] as int == sum_s(t, i, ks[r] as int)
            && -((t.n as int - i) * 46116860184273879039999int) <= ss.update(p, ns)[r] as int
            && ss.update(p, ns)[r] as int <= (t.n as int - i) * 46116860184273879039999int by {
        lemma_fold_step(t, i, ks[r] as int);
        if r == p {
            assert(sum_s_val(t, i) == t.value@[i] as int);
        } else {
            assert(ks[r] != k);
        }
    }
    assert forall|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j) implies idx.contains_key(t.ddate@[j]) by {
        if j != i { assert(i + 1 <= j); }
    }
}

proof fn lemma_p1_hit_new(t: &Cols_num, ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, idx: Map<i64, usize>, wit: Seq<int>, i: int)
    requires
        valid_cols_num(t),
        p1_inv(t, ks, cs, ss, idx, wit, i + 1),
        0 <= i < t.n as int,
        row_hit(t, i),
        !idx.contains_key(t.ddate@[i]),
        ks.len() <= usize::MAX,
    ensures
        p1_inv(t, ks.push(t.ddate@[i]), cs.push(1u64), ss.push(t.value@[i]), idx.insert(t.ddate@[i], ks.len() as usize), wit.push(i), i),
{
    let k = t.ddate@[i];
    let ks2 = ks.push(k);
    let cs2 = cs.push(1u64);
    let ss2 = ss.push(t.value@[i]);
    let idx2 = idx.insert(k, ks.len() as usize);
    let wit2 = wit.push(i);
    assert(key_at(t, i) == k as int);
    assert(t.value@[i] as int <= 46116860184273879039999int && t.value@[i] as int >= -46116860184273879039999int);
    assert forall|j: int| #![trigger row_hit(t, j)] i + 1 <= j < t.n as int implies !(row_hit(t, j) && key_at(t, j) == k as int) by {
        if row_hit(t, j) && key_at(t, j) == k as int {
            assert(idx.contains_key(t.ddate@[j]));
            assert(t.ddate@[j] == k);
        }
    }
    lemma_no_hit_zero(t, i + 1, k as int);
    lemma_fold_step(t, i, k as int);
    assert forall|r: int| #![trigger ks2[r]] 0 <= r < ks2.len() implies idx2.contains_key(ks2[r]) && idx2[ks2[r]] as int == r by {
        if r < ks.len() as int {
            assert(ks2[r] == ks[r]);
            assert(ks[r] != k);
            assert(idx2.contains_key(ks[r]));
            assert(idx2[ks[r]] == idx[ks[r]]);
        } else {
            assert(ks2[r] == k);
            assert(idx2.contains_key(k));
            assert(idx2[k] as int == ks.len() as int);
        }
    }
    assert forall|k2: i64| #![trigger idx2.contains_key(k2)] idx2.contains_key(k2) implies (idx2[k2] as int) < ks2.len() && ks2[idx2[k2] as int] == k2 by {
        if k2 == k {
            assert(ks2[ks.len() as int] == k);
        } else {
            assert(idx.contains_key(k2));
            assert(ks2[idx[k2] as int] == ks[idx[k2] as int]);
        }
    }
    assert forall|r: int| #![trigger cs2[r]] 0 <= r < ks2.len() implies cs2[r] as int == count_c(t, i, ks2[r] as int)
            && cs2[r] as int <= t.n as int - i
            && ss2[r] as int == sum_s(t, i, ks2[r] as int)
            && -((t.n as int - i) * 46116860184273879039999int) <= ss2[r] as int
            && ss2[r] as int <= (t.n as int - i) * 46116860184273879039999int by {
        if r < ks.len() as int {
            assert(ks2[r] == ks[r]);
            assert(cs2[r] == cs[r]);
            assert(ss2[r] == ss[r]);
            lemma_fold_step(t, i, ks[r] as int);
            assert(ks[r] != k);
        } else {
            assert(ks2[r] == k);
            assert(sum_s_val(t, i) == t.value@[i] as int);
        }
    }
    assert forall|r: int| #![trigger wit2[r]] 0 <= r < ks2.len() implies row_hit(t, wit2[r]) && key_at(t, wit2[r]) == ks2[r] as int by {
        if r < ks.len() as int { assert(wit2[r] == wit[r]); assert(ks2[r] == ks[r]); }
    }
    assert forall|j: int| #![trigger row_hit(t, j)] i <= j < t.n as int && row_hit(t, j) implies idx2.contains_key(t.ddate@[j]) by {
        if j != i { assert(i + 1 <= j); assert(idx.contains_key(t.ddate@[j])); }
    }
}

spec fn tk_count(tk: Seq<bool>, i: int) -> int
    decreases tk.len() - i
{
    if i < 0 || i >= tk.len() { 0int } else { (if tk[i] { 1int } else { 0int }) + tk_count(tk, i + 1) }
}

proof fn lemma_tk_count_set(tk: Seq<bool>, p: int, i: int)
    requires 0 <= p < tk.len(), !tk[p], 0 <= i <= tk.len(),
    ensures tk_count(tk.update(p, true), i) == tk_count(tk, i) + (if i <= p { 1int } else { 0int }),
    decreases tk.len() - i,
{
    if i < tk.len() {
        lemma_tk_count_set(tk, p, i + 1);
    }
}

proof fn lemma_tk_count_untaken(tk: Seq<bool>, i: int)
    requires 0 <= i <= tk.len(), tk_count(tk, i) < tk.len() - i,
    ensures exists|j: int| #![trigger tk[j]] i <= j < tk.len() && !tk[j],
    decreases tk.len() - i,
{
    if i < tk.len() {
        if tk[i] {
            lemma_tk_count_untaken(tk, i + 1);
        }
    }
}

proof fn lemma_tk_count_zero(tk: Seq<bool>, i: int)
    requires 0 <= i <= tk.len(), forall|q: int| #![trigger tk[q]] i <= q < tk.len() ==> !tk[q],
    ensures tk_count(tk, i) == 0,
    decreases tk.len() - i,
{
    if i < tk.len() {
        lemma_tk_count_zero(tk, i + 1);
    }
}

proof fn lemma_tk_count_all(tk: Seq<bool>, i: int)
    requires 0 <= i <= tk.len(),
    ensures 0 <= tk_count(tk, i) <= tk.len() - i,
    decreases tk.len() - i,
{
    if i < tk.len() {
        lemma_tk_count_all(tk, i + 1);
    }
}

proof fn lemma_tk_count_all_taken(tk: Seq<bool>, i: int)
    requires 0 <= i <= tk.len(), tk_count(tk, i) == tk.len() - i,
    ensures forall|j: int| #![trigger tk[j]] i <= j < tk.len() ==> tk[j],
    decreases tk.len() - i,
{
    if i < tk.len() {
        lemma_tk_count_all(tk, i + 1);
        lemma_tk_count_all_taken(tk, i + 1);
    }
}

spec fn sel_inv(ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, used: Seq<bool>, pos: Seq<int>, res: Seq<OutRow>, sel: Seq<int>) -> bool {
    &&& used.len() == ks.len()
    &&& cs.len() == ks.len()
    &&& ss.len() == ks.len()
    &&& pos.len() == ks.len()
    &&& sel.len() == res.len()
    &&& tk_count(used, 0) == res.len() as int
    &&& (forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> 0 <= sel[r] < ks.len() && used[sel[r]])
    &&& (forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> res[r].ddate == ks[sel[r]] && res[r].c == cs[sel[r]] && res[r].s == ss[sel[r]])
    &&& (forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() ==> sel[a] != sel[b])
    &&& (forall|g: int| #![trigger used[g]] 0 <= g < ks.len() && used[g] ==> 0 <= pos[g] < sel.len() && sel[pos[g]] == g)
    &&& (forall|i: int| #![trigger res[i], res[i + 1]] 0 <= i && i + 1 < res.len() ==> res[i].s >= res[i + 1].s)
    &&& (forall|g: int, r: int| #![trigger used[g], res[r]] 0 <= g < ks.len() && !used[g] && 0 <= r < res.len() ==> res[r].s >= ss[g])
}

proof fn lemma_sel_step(ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, used: Seq<bool>, pos: Seq<int>, res: Seq<OutRow>, sel: Seq<int>, p: int)
    requires
        sel_inv(ks, cs, ss, used, pos, res, sel),
        0 <= p < used.len(),
        !used[p],
        forall|q: int| #![trigger used[q]] 0 <= q < used.len() && !used[q] ==> ss[p] >= ss[q],
    ensures
        sel_inv(ks, cs, ss, used.update(p, true), pos.update(p, res.len() as int), res.push(OutRow { ddate: ks[p], c: cs[p], s: ss[p] }), sel.push(p)),
{
    lemma_tk_count_set(used, p, 0);
    let row = OutRow { ddate: ks[p], c: cs[p], s: ss[p] };
    let used2 = used.update(p, true);
    let pos2 = pos.update(p, res.len() as int);
    let res2 = res.push(row);
    let sel2 = sel.push(p);
    let m = res.len() as int;
    assert(res2[m] == row);
    assert(sel2[m] == p);
    assert forall|r: int| #![trigger sel2[r]] 0 <= r < sel2.len() implies 0 <= sel2[r] < ks.len() && used2[sel2[r]] by {
        if r < m { assert(sel2[r] == sel[r]); }
    }
    assert forall|r: int| #![trigger res2[r]] 0 <= r < res2.len() implies res2[r].ddate == ks[sel2[r]] && res2[r].c == cs[sel2[r]] && res2[r].s == ss[sel2[r]] by {
        if r < m { assert(res2[r] == res[r]); assert(sel2[r] == sel[r]); }
    }
    assert forall|a: int, b: int| #![trigger sel2[a], sel2[b]] 0 <= a < b < sel2.len() implies sel2[a] != sel2[b] by {
        if b < m { assert(sel2[a] == sel[a]); assert(sel2[b] == sel[b]); }
        else { assert(sel2[a] == sel[a]); assert(used[sel[a]]); }
    }
    assert forall|g: int| #![trigger used2[g]] 0 <= g < ks.len() && used2[g] implies 0 <= pos2[g] < sel2.len() && sel2[pos2[g]] == g by {
        if g != p { assert(used[g]); assert(sel2[pos[g]] == sel[pos[g]]); }
    }
    assert forall|i: int| #![trigger res2[i], res2[i + 1]] 0 <= i && i + 1 < res2.len() implies res2[i].s >= res2[i + 1].s by {
        if i + 1 < m { assert(res2[i] == res[i]); assert(res2[i + 1] == res[i + 1]); }
        else { assert(res2[i] == res[i]); }
    }
    assert forall|g: int, r: int| #![trigger used2[g], res2[r]] 0 <= g < ks.len() && !used2[g] && 0 <= r < res2.len() implies res2[r].s >= ss[g] by {
        assert(g != p);
        assert(!used[g]);
        if r < m { assert(res2[r] == res[r]); }
    }
}

// ---- Parallel upgrade: per-range worker tables, merged back to front. ----
spec fn ucode_ok(t: &Cols_num, ucode: int) -> bool {
    &&& 0 <= ucode <= t.uom__dict@.len()
    &&& ucode < t.uom__dict@.len() ==> t.uom__dict@[ucode]@ == "USD"@
    &&& forall|q: int| 0 <= q < ucode ==> t.uom__dict@[q]@ != "USD"@
}

// A table folded over the row range [i, hi): per key, the fold from i minus the fold from hi.
spec fn pr_inv(t: &Cols_num, hi: int, ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, idx: Map<i64, usize>, wit: Seq<int>, i: int) -> bool {
    &&& cs.len() == ks.len()
    &&& ss.len() == ks.len()
    &&& wit.len() == ks.len()
    &&& forall|r: int| #![trigger ks[r]] 0 <= r < ks.len() ==> idx.contains_key(ks[r]) && idx[ks[r]] as int == r
    &&& forall|k: i64| #![trigger idx.contains_key(k)] idx.contains_key(k) ==> (idx[k] as int) < ks.len() && ks[idx[k] as int] == k
    &&& forall|r: int| #![trigger cs[r]] 0 <= r < ks.len() ==> cs[r] as int == count_c(t, i, ks[r] as int) - count_c(t, hi, ks[r] as int)
            && cs[r] as int <= hi - i
            && ss[r] as int == sum_s(t, i, ks[r] as int) - sum_s(t, hi, ks[r] as int)
            && -((hi - i) * 46116860184273879039999int) <= ss[r] as int
            && ss[r] as int <= (hi - i) * 46116860184273879039999int
    &&& forall|r: int| #![trigger wit[r]] 0 <= r < ks.len() ==> row_hit(t, wit[r]) && key_at(t, wit[r]) == ks[r] as int
    &&& forall|j: int| #![trigger row_hit(t, j)] i <= j < hi && row_hit(t, j) ==> idx.contains_key(t.ddate@[j])
}

spec fn tab_ok(t: &Cols_num, hi: int, lo: int, r: (Vec<i64>, Vec<u64>, Vec<i128>, HashMapWithView<i64, usize>, Ghost<Seq<int>>)) -> bool {
    pr_inv(t, hi, r.0@, r.1@, r.2@, r.3@, r.4@, lo)
}

proof fn lemma_range_zero(t: &Cols_num, i: int, hi: int, k: int)
    requires
        0 <= i <= hi <= t.n as int,
        forall|j: int| #![trigger row_hit(t, j)] i <= j < hi ==> !(row_hit(t, j) && key_at(t, j) == k),
    ensures
        count_c(t, i, k) == count_c(t, hi, k),
        sum_s(t, i, k) == sum_s(t, hi, k),
    decreases hi - i,
{
    if i < hi {
        lemma_range_zero(t, i + 1, hi, k);
        lemma_fold_step(t, i, k);
    }
}

proof fn lemma_sum_s_bound(t: &Cols_num, i: int, k: int)
    requires
        valid_cols_num(t),
        0 <= i <= t.n as int,
    ensures
        -((t.n as int - i) * 46116860184273879039999int) <= sum_s(t, i, k) <= (t.n as int - i) * 46116860184273879039999int,
    decreases t.n as int - i,
{
    if i < t.n as int {
        lemma_sum_s_bound(t, i + 1, k);
        lemma_fold_step(t, i, k);
        assert(t.value@[i] as int <= 46116860184273879039999int && t.value@[i] as int >= -46116860184273879039999int);
    }
}

proof fn lemma_pr_nohit(t: &Cols_num, hi: int, ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, idx: Map<i64, usize>, wit: Seq<int>, i: int)
    requires
        valid_cols_num(t),
        pr_inv(t, hi, ks, cs, ss, idx, wit, i + 1),
        0 <= i < hi <= t.n as int,
        !row_hit(t, i),
    ensures
        pr_inv(t, hi, ks, cs, ss, idx, wit, i),
{
    assert forall|r: int| #![trigger cs[r]] 0 <= r < ks.len() implies cs[r] as int == count_c(t, i, ks[r] as int) - count_c(t, hi, ks[r] as int)
            && cs[r] as int <= hi - i
            && ss[r] as int == sum_s(t, i, ks[r] as int) - sum_s(t, hi, ks[r] as int)
            && -((hi - i) * 46116860184273879039999int) <= ss[r] as int
            && ss[r] as int <= (hi - i) * 46116860184273879039999int by {
        lemma_fold_step(t, i, ks[r] as int);
    }
    assert forall|j: int| #![trigger row_hit(t, j)] i <= j < hi && row_hit(t, j) implies idx.contains_key(t.ddate@[j]) by {
        assert(j != i);
    }
}

proof fn lemma_pr_hit_existing(t: &Cols_num, hi: int, ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, idx: Map<i64, usize>, wit: Seq<int>, i: int, p: int, nc: u64, ns: i128)
    requires
        valid_cols_num(t),
        pr_inv(t, hi, ks, cs, ss, idx, wit, i + 1),
        0 <= i < hi <= t.n as int,
        row_hit(t, i),
        idx.contains_key(t.ddate@[i]),
        idx[t.ddate@[i]] as int == p,
        0 <= p < ks.len(),
        nc as int == cs[p] as int + 1,
        ns as int == ss[p] as int + t.value@[i] as int,
    ensures
        pr_inv(t, hi, ks, cs.update(p, nc), ss.update(p, ns), idx, wit, i),
{
    let k = t.ddate@[i];
    assert(key_at(t, i) == k as int);
    assert(ks[p] == k);
    assert(t.value@[i] as int <= 46116860184273879039999int && t.value@[i] as int >= -46116860184273879039999int);
    assert forall|r: int| #![trigger cs.update(p, nc)[r]] 0 <= r < ks.len() implies cs.update(p, nc)[r] as int == count_c(t, i, ks[r] as int) - count_c(t, hi, ks[r] as int)
            && cs.update(p, nc)[r] as int <= hi - i
            && ss.update(p, ns)[r] as int == sum_s(t, i, ks[r] as int) - sum_s(t, hi, ks[r] as int)
            && -((hi - i) * 46116860184273879039999int) <= ss.update(p, ns)[r] as int
            && ss.update(p, ns)[r] as int <= (hi - i) * 46116860184273879039999int by {
        lemma_fold_step(t, i, ks[r] as int);
        if r == p {
            assert(sum_s_val(t, i) == t.value@[i] as int);
        } else {
            assert(ks[r] != k);
        }
    }
    assert forall|j: int| #![trigger row_hit(t, j)] i <= j < hi && row_hit(t, j) implies idx.contains_key(t.ddate@[j]) by {
        if j != i { assert(i + 1 <= j); }
    }
}

proof fn lemma_pr_hit_new(t: &Cols_num, hi: int, ks: Seq<i64>, cs: Seq<u64>, ss: Seq<i128>, idx: Map<i64, usize>, wit: Seq<int>, i: int)
    requires
        valid_cols_num(t),
        pr_inv(t, hi, ks, cs, ss, idx, wit, i + 1),
        0 <= i < hi <= t.n as int,
        row_hit(t, i),
        !idx.contains_key(t.ddate@[i]),
        ks.len() <= usize::MAX,
    ensures
        pr_inv(t, hi, ks.push(t.ddate@[i]), cs.push(1u64), ss.push(t.value@[i]), idx.insert(t.ddate@[i], ks.len() as usize), wit.push(i), i),
{
    let k = t.ddate@[i];
    let ks2 = ks.push(k);
    let cs2 = cs.push(1u64);
    let ss2 = ss.push(t.value@[i]);
    let idx2 = idx.insert(k, ks.len() as usize);
    let wit2 = wit.push(i);
    assert(key_at(t, i) == k as int);
    assert(t.value@[i] as int <= 46116860184273879039999int && t.value@[i] as int >= -46116860184273879039999int);
    assert forall|j: int| #![trigger row_hit(t, j)] i + 1 <= j < hi implies !(row_hit(t, j) && key_at(t, j) == k as int) by {
        if row_hit(t, j) && key_at(t, j) == k as int {
            assert(idx.contains_key(t.ddate@[j]));
            assert(t.ddate@[j] == k);
        }
    }
    lemma_range_zero(t, i + 1, hi, k as int);
    lemma_fold_step(t, i, k as int);
    assert forall|r: int| #![trigger ks2[r]] 0 <= r < ks2.len() implies idx2.contains_key(ks2[r]) && idx2[ks2[r]] as int == r by {
        if r < ks.len() as int {
            assert(ks2[r] == ks[r]);
            assert(ks[r] != k);
            assert(idx2.contains_key(ks[r]));
            assert(idx2[ks[r]] == idx[ks[r]]);
        } else {
            assert(ks2[r] == k);
            assert(idx2.contains_key(k));
            assert(idx2[k] as int == ks.len() as int);
        }
    }
    assert forall|k2: i64| #![trigger idx2.contains_key(k2)] idx2.contains_key(k2) implies (idx2[k2] as int) < ks2.len() && ks2[idx2[k2] as int] == k2 by {
        if k2 == k {
            assert(ks2[ks.len() as int] == k);
        } else {
            assert(idx.contains_key(k2));
            assert(ks2[idx[k2] as int] == ks[idx[k2] as int]);
        }
    }
    assert forall|r: int| #![trigger cs2[r]] 0 <= r < ks2.len() implies cs2[r] as int == count_c(t, i, ks2[r] as int) - count_c(t, hi, ks2[r] as int)
            && cs2[r] as int <= hi - i
            && ss2[r] as int == sum_s(t, i, ks2[r] as int) - sum_s(t, hi, ks2[r] as int)
            && -((hi - i) * 46116860184273879039999int) <= ss2[r] as int
            && ss2[r] as int <= (hi - i) * 46116860184273879039999int by {
        if r < ks.len() as int {
            assert(ks2[r] == ks[r]);
            assert(cs2[r] == cs[r]);
            assert(ss2[r] == ss[r]);
            lemma_fold_step(t, i, ks[r] as int);
            assert(ks[r] != k);
        } else {
            assert(ks2[r] == k);
            assert(sum_s_val(t, i) == t.value@[i] as int);
        }
    }
    assert forall|r: int| #![trigger wit2[r]] 0 <= r < ks2.len() implies row_hit(t, wit2[r]) && key_at(t, wit2[r]) == ks2[r] as int by {
        if r < ks.len() as int { assert(wit2[r] == wit[r]); assert(ks2[r] == ks[r]); }
    }
    assert forall|j: int| #![trigger row_hit(t, j)] i <= j < hi && row_hit(t, j) implies idx2.contains_key(t.ddate@[j]) by {
        if j != i { assert(i + 1 <= j); assert(idx.contains_key(t.ddate@[j])); }
    }
}

// Partial value of the worker's entry for key k among its first e entries (0 when absent).
spec fn wpc(widx: Map<i64, usize>, wcs: Seq<u64>, k: i64, e: int) -> int {
    if widx.contains_key(k) && (widx[k] as int) < e { wcs[widx[k] as int] as int } else { 0int }
}

spec fn wps(widx: Map<i64, usize>, wss: Seq<i128>, k: i64, e: int) -> int {
    if widx.contains_key(k) && (widx[k] as int) < e { wss[widx[k] as int] as int } else { 0int }
}

// Global table g while merging the worker table w (range [lo, hi)): g holds the fold from hi plus w's first e entries.
spec fn mg_inv(t: &Cols_num, lo: int, hi: int, gks: Seq<i64>, gcs: Seq<u64>, gss: Seq<i128>, gidx: Map<i64, usize>, gwit: Seq<int>,
        wks: Seq<i64>, wcs: Seq<u64>, wss: Seq<i128>, widx: Map<i64, usize>, e: int) -> bool {
    &&& gcs.len() == gks.len()
    &&& gss.len() == gks.len()
    &&& gwit.len() == gks.len()
    &&& forall|r: int| #![trigger gks[r]] 0 <= r < gks.len() ==> gidx.contains_key(gks[r]) && gidx[gks[r]] as int == r
    &&& forall|k: i64| #![trigger gidx.contains_key(k)] gidx.contains_key(k) ==> (gidx[k] as int) < gks.len() && gks[gidx[k] as int] == k
    &&& forall|r: int| #![trigger gcs[r]] 0 <= r < gks.len() ==>
            gcs[r] as int == count_c(t, hi, gks[r] as int) + wpc(widx, wcs, gks[r], e)
            && gss[r] as int == sum_s(t, hi, gks[r] as int) + wps(widx, wss, gks[r], e)
    &&& forall|r: int| #![trigger gwit[r]] 0 <= r < gks.len() ==> row_hit(t, gwit[r]) && key_at(t, gwit[r]) == gks[r] as int
    &&& forall|j: int| #![trigger row_hit(t, j)] hi <= j < t.n as int && row_hit(t, j) ==> gidx.contains_key(t.ddate@[j])
    &&& forall|q: int| #![trigger wks[q]] 0 <= q < e ==> gidx.contains_key(wks[q])
}

proof fn lemma_mg_init(t: &Cols_num, lo: int, hi: int, gks: Seq<i64>, gcs: Seq<u64>, gss: Seq<i128>, gidx: Map<i64, usize>, gwit: Seq<int>,
        wks: Seq<i64>, wcs: Seq<u64>, wss: Seq<i128>, widx: Map<i64, usize>)
    requires
        p1_inv(t, gks, gcs, gss, gidx, gwit, hi),
    ensures
        mg_inv(t, lo, hi, gks, gcs, gss, gidx, gwit, wks, wcs, wss, widx, 0),
{
}

// Merge worker entry e into a global entry that already exists.
proof fn lemma_mg_existing(t: &Cols_num, lo: int, hi: int, gks: Seq<i64>, gcs: Seq<u64>, gss: Seq<i128>, gidx: Map<i64, usize>, gwit: Seq<int>,
        wks: Seq<i64>, wcs: Seq<u64>, wss: Seq<i128>, widx: Map<i64, usize>, wwit: Seq<int>, e: int, p: int, nc: u64, ns: i128)
    requires
        valid_cols_num(t),
        pr_inv(t, hi, wks, wcs, wss, widx, wwit, lo),
        mg_inv(t, lo, hi, gks, gcs, gss, gidx, gwit, wks, wcs, wss, widx, e),
        0 <= e < wks.len(),
        gidx.contains_key(wks[e]),
        gidx[wks[e]] as int == p,
        nc as int == gcs[p] as int + wcs[e] as int,
        ns as int == gss[p] as int + wss[e] as int,
    ensures
        mg_inv(t, lo, hi, gks, gcs.update(p, nc), gss.update(p, ns), gidx, gwit, wks, wcs, wss, widx, e + 1),
{
    let k = wks[e];
    assert(widx.contains_key(k) && widx[k] as int == e);
    assert(gks[p] == k);
    assert forall|r: int| #![trigger gcs.update(p, nc)[r]] 0 <= r < gks.len() implies
            gcs.update(p, nc)[r] as int == count_c(t, hi, gks[r] as int) + wpc(widx, wcs, gks[r], e + 1)
            && gss.update(p, ns)[r] as int == sum_s(t, hi, gks[r] as int) + wps(widx, wss, gks[r], e + 1) by {
        let kr = gks[r];
        if r == p {
            assert(kr == k);
        } else {
            assert(kr != k);
            if widx.contains_key(kr) && widx[kr] as int == e {
                assert(wks[e] == kr);
            }
        }
    }
}

// Merge worker entry e into a new global entry.
proof fn lemma_mg_new(t: &Cols_num, lo: int, hi: int, gks: Seq<i64>, gcs: Seq<u64>, gss: Seq<i128>, gidx: Map<i64, usize>, gwit: Seq<int>,
        wks: Seq<i64>, wcs: Seq<u64>, wss: Seq<i128>, widx: Map<i64, usize>, wwit: Seq<int>, e: int)
    requires
        valid_cols_num(t),
        pr_inv(t, hi, wks, wcs, wss, widx, wwit, lo),
        mg_inv(t, lo, hi, gks, gcs, gss, gidx, gwit, wks, wcs, wss, widx, e),
        0 <= e < wks.len(),
        !gidx.contains_key(wks[e]),
        gks.len() <= usize::MAX,
    ensures
        mg_inv(t, lo, hi, gks.push(wks[e]), gcs.push(wcs[e]), gss.push(wss[e]), gidx.insert(wks[e], gks.len() as usize), gwit.push(wwit[e]), wks, wcs, wss, widx, e + 1),
{
    let k = wks[e];
    let gks2 = gks.push(k);
    let gcs2 = gcs.push(wcs[e]);
    let gss2 = gss.push(wss[e]);
    let gidx2 = gidx.insert(k, gks.len() as usize);
    let gwit2 = gwit.push(wwit[e]);
    assert(widx.contains_key(k) && widx[k] as int == e);
    assert forall|j: int| #![trigger row_hit(t, j)] hi <= j < t.n as int implies !(row_hit(t, j) && key_at(t, j) == k as int) by {
        if row_hit(t, j) && key_at(t, j) == k as int {
            assert(gidx.contains_key(t.ddate@[j]));
            assert(t.ddate@[j] == k);
        }
    }
    lemma_no_hit_zero(t, hi, k as int);
    assert forall|r: int| #![trigger gks2[r]] 0 <= r < gks2.len() implies gidx2.contains_key(gks2[r]) && gidx2[gks2[r]] as int == r by {
        if r < gks.len() as int {
            assert(gks2[r] == gks[r]);
            assert(gks[r] != k);
        } else {
            assert(gks2[r] == k);
        }
    }
    assert forall|k2: i64| #![trigger gidx2.contains_key(k2)] gidx2.contains_key(k2) implies (gidx2[k2] as int) < gks2.len() && gks2[gidx2[k2] as int] == k2 by {
        if k2 == k {
            assert(gks2[gks.len() as int] == k);
        } else {
            assert(gidx.contains_key(k2));
            assert(gks2[gidx[k2] as int] == gks[gidx[k2] as int]);
        }
    }
    assert forall|r: int| #![trigger gcs2[r]] 0 <= r < gks2.len() implies
            gcs2[r] as int == count_c(t, hi, gks2[r] as int) + wpc(widx, wcs, gks2[r], e + 1)
            && gss2[r] as int == sum_s(t, hi, gks2[r] as int) + wps(widx, wss, gks2[r], e + 1) by {
        if r < gks.len() as int {
            let kr = gks[r];
            assert(gks2[r] == kr);
            assert(gcs2[r] == gcs[r]);
            assert(gss2[r] == gss[r]);
            assert(kr != k);
            if widx.contains_key(kr) && widx[kr] as int == e {
                assert(wks[e] == kr);
            }
        } else {
            assert(gks2[r] == k);
        }
    }
    assert forall|r: int| #![trigger gwit2[r]] 0 <= r < gks2.len() implies row_hit(t, gwit2[r]) && key_at(t, gwit2[r]) == gks2[r] as int by {
        if r < gks.len() as int { assert(gwit2[r] == gwit[r]); assert(gks2[r] == gks[r]); }
    }
    assert forall|j: int| #![trigger row_hit(t, j)] hi <= j < t.n as int && row_hit(t, j) implies gidx2.contains_key(t.ddate@[j]) by {
        assert(gidx.contains_key(t.ddate@[j]));
    }
    assert forall|q: int| #![trigger wks[q]] 0 <= q < e + 1 implies gidx2.contains_key(wks[q]) by {
        if q < e { assert(gidx.contains_key(wks[q])); }
    }
}

// All entries merged: g is the fold from lo.
proof fn lemma_mg_finish(t: &Cols_num, lo: int, hi: int, gks: Seq<i64>, gcs: Seq<u64>, gss: Seq<i128>, gidx: Map<i64, usize>, gwit: Seq<int>,
        wks: Seq<i64>, wcs: Seq<u64>, wss: Seq<i128>, widx: Map<i64, usize>, wwit: Seq<int>)
    requires
        valid_cols_num(t),
        0 <= lo <= hi <= t.n as int,
        pr_inv(t, hi, wks, wcs, wss, widx, wwit, lo),
        mg_inv(t, lo, hi, gks, gcs, gss, gidx, gwit, wks, wcs, wss, widx, wks.len() as int),
    ensures
        p1_inv(t, gks, gcs, gss, gidx, gwit, lo),
{
    assert forall|r: int| #![trigger gcs[r]] 0 <= r < gks.len() implies gcs[r] as int == count_c(t, lo, gks[r] as int)
            && gcs[r] as int <= t.n as int - lo
            && gss[r] as int == sum_s(t, lo, gks[r] as int)
            && -((t.n as int - lo) * 46116860184273879039999int) <= gss[r] as int
            && gss[r] as int <= (t.n as int - lo) * 46116860184273879039999int by {
        let k = gks[r];
        if widx.contains_key(k) {
            let q = widx[k] as int;
            assert(q < wks.len() as int && wks[q] == k);
            assert(wcs[q] as int == count_c(t, lo, k as int) - count_c(t, hi, k as int));
            assert(wss[q] as int == sum_s(t, lo, k as int) - sum_s(t, hi, k as int));
            assert(wpc(widx, wcs, k, wks.len() as int) == wcs[q] as int);
            assert(wps(widx, wss, k, wks.len() as int) == wss[q] as int);
        } else {
            assert forall|j: int| #![trigger row_hit(t, j)] lo <= j < hi implies !(row_hit(t, j) && key_at(t, j) == k as int) by {
                if row_hit(t, j) && key_at(t, j) == k as int {
                    assert(widx.contains_key(t.ddate@[j]));
                    assert(t.ddate@[j] == k);
                }
            }
            lemma_range_zero(t, lo, hi, k as int);
        }
        lemma_count_c_bound(t, lo, k as int);
        lemma_sum_s_bound(t, lo, k as int);
        assert(gcs[r] as int == count_c(t, lo, k as int));
        assert(gss[r] as int == sum_s(t, lo, k as int));
        assert(gcs[r] as int <= t.n as int - lo);
        assert(-((t.n as int - lo) * 46116860184273879039999int) <= gss[r] as int);
    }
    assert forall|j: int| #![trigger row_hit(t, j)] lo <= j < t.n as int && row_hit(t, j) implies gidx.contains_key(t.ddate@[j]) by {
        if j < hi {
            let k = t.ddate@[j];
            assert(widx.contains_key(k));
            assert(wks[widx[k] as int] == k);
        }
    }
}

spec fn lo_of(n: int, cs: int, k: int) -> int {
    if k * cs <= n { k * cs } else { n }
}

spec fn handle_ok(t: &Cols_num, h: vstd::thread::JoinHandle<(Vec<i64>, Vec<u64>, Vec<i128>, HashMapWithView<i64, usize>, Ghost<Seq<int>>)>, lo: int, hi: int) -> bool {
    forall|r: (Vec<i64>, Vec<u64>, Vec<i128>, HashMapWithView<i64, usize>, Ghost<Seq<int>>)| #[trigger] h.predicate(r) ==> tab_ok(t, hi, lo, r)
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

proof fn lemma_lo_end(n: int, cs: int)
    requires
        n >= 0,
        cs == n / 4 + 1,
    ensures
        lo_of(n, cs, 4) == n,
        lo_of(n, cs, 0) == 0,
{
    assert(4 * cs >= n);
}
proof fn ucode_ok_proof(t: &Cols_num, ucode: usize)
    requires
        ucode <= t.uom__dict@.len(),
        ucode < t.uom__dict@.len() ==> t.uom__dict@[ucode as int]@ == "USD"@,
        forall|q: int| 0 <= q < ucode as int ==> t.uom__dict@[q]@ != "USD"@,
    ensures
        ucode_ok(t, ucode as int),
{
}
// AGENT_HELPERS_END
pub fn run_query(n: &Cols_num, n_arc: &std::sync::Arc<Cols_num>) -> (res: Vec<OutRow>)
    requires
        **n_arc == *n,
        valid_cols_num(n),
    ensures
        forall|r: int| #![trigger res@[r]] 0 <= r < res@.len() ==> out_row_ok(n, res@[r]),
        forall|a: int, b: int| #![trigger res@[a], res@[b]] 0 <= a < b < res@.len() ==> (res@[a].ddate as int) != (res@[b].ddate as int),
        (res@.len() == 20) || (forall|i0: int| #![trigger row_hit(n, i0)] row_hit(n, i0) && (true) ==> exists|r: int| #![trigger res@[r]] 0 <= r < res@.len() && key_at(n, i0) == (res@[r].ddate as int)),
        forall|i0: int, r: int| #![trigger row_hit(n, i0), res@[r]] row_hit(n, i0) && (true) && !(exists|r2: int| #![trigger res@[r2]] 0 <= r2 < res@.len() && key_at(n, i0) == (res@[r2].ddate as int)) && 0 <= r < res@.len() ==> (((res@[r].s as int)) >= (sum_s(n, 0, key_at(n, i0)))),
        forall|i: int| #![trigger res@[i]] 0 <= i && i + 1 < res@.len() ==> ((res@[i].s) >= (res@[i + 1].s) /* descending on s */),
        res@.len() <= 20,
{
// AGENT_EDIT_START
    // Worker: fold the rows [lo, hi) backwards into its own table.
    fn fold_range(t: &Cols_num, ucode: usize, lo: usize, hi: usize) -> (r: (Vec<i64>, Vec<u64>, Vec<i128>, HashMapWithView<i64, usize>, Ghost<Seq<int>>))
        requires
            valid_cols_num(t),
            lo <= hi <= t.n,
            ucode_ok(t, ucode as int),
        ensures
            tab_ok(t, hi as int, lo as int, r),
    {
        let mut ks: Vec<i64> = Vec::new();
        let mut cs: Vec<u64> = Vec::new();
        let mut ss: Vec<i128> = Vec::new();
        let mut idx: HashMapWithView<i64, usize> = HashMapWithView::new();
        let ghost mut wit: Seq<int> = Seq::empty();
        let mut i: usize = hi;
        while i > lo
            invariant
                lo <= i <= hi,
                hi <= t.n,
                valid_cols_num(t),
                ucode_ok(t, ucode as int),
                pr_inv(t, hi as int, ks@, cs@, ss@, idx@, wit, i as int),
            decreases i,
        {
            i -= 1;
            let code = t.uom[i] as usize;
            let v = t.value[i];
            let hit = code == ucode && v > 0;
            proof {
                assert(t.uom@.len() == t.n as int);
                assert(t.value@.len() == t.n as int);
                assert(t.ddate@.len() == t.n as int);
                lemma_hit_iff(t, ucode as int, i as int);
                assert(row_hit(t, i as int) == hit);
            }
            if hit {
                let k = t.ddate[i];
                let ghost ok = ks@;
                let ghost oc = cs@;
                let ghost os = ss@;
                let ghost ow = wit;
                let ghost oi = idx@;
                if idx.contains_key(&k) {
                    let p = *idx.get(&k).unwrap();
                    proof {
                        assert(oi.contains_key(k));
                        assert(oi[k] == p);
                        assert(ks@[p as int] == k);
                        assert(cs@[p as int] as int <= hi as int - (i + 1) as int);
                        assert(-((hi as int - (i + 1) as int) * 46116860184273879039999int) <= ss@[p as int] as int);
                        assert(t.value@[i as int] as int <= 46116860184273879039999int);
                    }
                    let c0 = cs[p];
                    let s0 = ss[p];
                    let nc = c0 + 1;
                    let ns = s0 + v;
                    proof {
                        lemma_pr_hit_existing(t, hi as int, ok, oc, os, oi, ow, i as int, p as int, nc, ns);
                    }
                    cs.set(p, nc);
                    ss.set(p, ns);
                } else {
                    let np = ks.len();
                    proof {
                        assert(!oi.contains_key(k));
                        lemma_pr_hit_new(t, hi as int, ok, oc, os, oi, ow, i as int);
                        wit = ow.push(i as int);
                    }
                    ks.push(k);
                    cs.push(1);
                    ss.push(v);
                    idx.insert(k, np);
                }
            } else {
                proof {
                    lemma_pr_nohit(t, hi as int, ks@, cs@, ss@, idx@, wit, i as int);
                }
            }
        }
        (ks, cs, ss, idx, Ghost(wit))
    }

    // Merge a worker's table (range [lo, hi)) into the global table, which holds the fold from hi.
    fn merge_worker(t: &Cols_num, lo: usize, hi: usize, g: &mut (Vec<i64>, Vec<u64>, Vec<i128>, HashMapWithView<i64, usize>, Ghost<Seq<int>>), w: &(Vec<i64>, Vec<u64>, Vec<i128>, HashMapWithView<i64, usize>, Ghost<Seq<int>>))
        requires
            valid_cols_num(t),
            lo <= hi <= t.n,
            p1_inv(t, old(g).0@, old(g).1@, old(g).2@, old(g).3@, old(g).4@, hi as int),
            tab_ok(t, hi as int, lo as int, *w),
        ensures
            p1_inv(t, final(g).0@, final(g).1@, final(g).2@, final(g).3@, final(g).4@, lo as int),
    {
        let wn = w.0.len();
        proof {
            lemma_mg_init(t, lo as int, hi as int, g.0@, g.1@, g.2@, g.3@, g.4@, w.0@, w.1@, w.2@, w.3@);
        }
        let mut e: usize = 0;
        while e < wn
            invariant
                e <= wn,
                wn == w.0@.len(),
                valid_cols_num(t),
                lo <= hi <= t.n,
                tab_ok(t, hi as int, lo as int, *w),
                mg_inv(t, lo as int, hi as int, g.0@, g.1@, g.2@, g.3@, g.4@, w.0@, w.1@, w.2@, w.3@, e as int),
            decreases wn - e,
        {
            let k = w.0[e];
            let wc = w.1[e];
            let wsum = w.2[e];
            let ghost wwit = w.4@;
            if g.3.contains_key(&k) {
                let p = *g.3.get(&k).unwrap();
                proof {
                    lemma_count_c_bound(t, hi as int, k as int);
                    lemma_sum_s_bound(t, hi as int, k as int);
                    assert(wc as int <= hi as int - lo as int);
                    assert(wsum as int <= (hi as int - lo as int) * 46116860184273879039999int);
                    assert(-((hi as int - lo as int) * 46116860184273879039999int) <= wsum as int);
                    assert(g.0@[p as int] == k);
                    assert(g.1@[p as int] as int == count_c(t, hi as int, k as int) + wpc(w.3@, w.1@, k, e as int));
                    assert(g.2@[p as int] as int == sum_s(t, hi as int, k as int) + wps(w.3@, w.2@, k, e as int));
                }
                let gc = g.1[p];
                let gs = g.2[p];
                let nc = gc + wc;
                let ns = gs + wsum;
                proof {
                    lemma_mg_existing(t, lo as int, hi as int, g.0@, g.1@, g.2@, g.3@, g.4@, w.0@, w.1@, w.2@, w.3@, wwit, e as int, p as int, nc, ns);
                }
                g.1.set(p, nc);
                g.2.set(p, ns);
            } else {
                let np = g.0.len();
                proof {
                    lemma_mg_new(t, lo as int, hi as int, g.0@, g.1@, g.2@, g.3@, g.4@, w.0@, w.1@, w.2@, w.3@, wwit, e as int);
                    g.4 = Ghost(g.4@.push(wwit[e as int]));
                }
                g.0.push(k);
                g.1.push(wc);
                g.2.push(wsum);
                g.3.insert(k, np);
            }
            e += 1;
        }
        proof {
            lemma_mg_finish(t, lo as int, hi as int, g.0@, g.1@, g.2@, g.3@, g.4@, w.0@, w.1@, w.2@, w.3@, w.4@);
        }
    }

    // The code of "USD" in the uom dictionary (dictionary length when absent).
    let usd: String = String::from_str("USD");
    let dl = n.uom__dict.len();
    let mut uc: usize = 0;
    while uc < dl && !(n.uom__dict[uc] == usd)
        invariant
            uc <= dl,
            dl == n.uom__dict@.len(),
            usd@ == "USD"@,
            forall|q: int| 0 <= q < uc as int ==> n.uom__dict@[q]@ != "USD"@,
        decreases dl - uc,
    {
        uc += 1;
    }
    let ucode = uc;
    proof {
        assert(ucode < dl ==> n.uom__dict@[ucode as int]@ == "USD"@);
    }
    proof { ucode_ok_proof(n, ucode); }
    // Pass 1: four workers fold contiguous row ranges into their own tables; the tables are merged back to front.
    let rows = n.n;
    let chunk: usize = rows / 4 + 1;
    proof {
        assert(rows <= 2147483648);
        lemma_lo_end(rows as int, chunk as int);
    }
    let mut handles: Vec<vstd::thread::JoinHandle<(Vec<i64>, Vec<u64>, Vec<i128>, HashMapWithView<i64, usize>, Ghost<Seq<int>>)>> = Vec::new();
    let mut k: usize = 0;
    while k < 4
        invariant
            k <= 4,
            rows == n.n,
            chunk == rows / 4 + 1,
            chunk <= 536870913,
            valid_cols_num(n),
            ucode_ok(n, ucode as int),
            **n_arc == *n,
            handles@.len() == k as int,
            forall|m: int|
                0 <= m < k as int ==> #[trigger] handle_ok(n, handles@[m], lo_of(rows as int, chunk as int, m), lo_of(rows as int, chunk as int, m + 1)),
        decreases 4 - k,
    {
        proof {
            assert(rows <= 2147483648);
            assert(k as int * chunk as int <= 3 * 536870913) by (nonlinear_arith)
                requires k <= 3, chunk <= 536870913, k >= 0, chunk >= 0;
            assert((k as int + 1) * chunk as int <= 4 * 536870913) by (nonlinear_arith)
                requires k <= 3, chunk <= 536870913, k >= 0, chunk >= 0;
        }
        let lo: usize = if k * chunk <= rows { k * chunk } else { rows };
        let hi: usize = if (k + 1) * chunk <= rows { (k + 1) * chunk } else { rows };
        let pa = std::sync::Arc::clone(n_arc);
        proof {
            assert(lo as int == lo_of(rows as int, chunk as int, k as int));
            assert(hi as int == lo_of(rows as int, chunk as int, k as int + 1));
            lemma_lo_range(rows as int, chunk as int, k as int);
            assert(*pa == *n);
        }
        let h = vstd::thread::spawn(
            move || -> (r: (Vec<i64>, Vec<u64>, Vec<i128>, HashMapWithView<i64, usize>, Ghost<Seq<int>>))
                requires
                    lo <= hi,
                    hi <= pa.n,
                    valid_cols_num(&*pa),
                    ucode_ok(&*pa, ucode as int),
                ensures
                    tab_ok(&*pa, hi as int, lo as int, r),
                {
                    fold_range(&*pa, ucode, lo, hi)
                },
        );
        proof {
            let ghost old_h = handles@;
            assert(*pa == *n);
        }
        handles.push(h);
        k += 1;
    }
    let mut g = (Vec::new(), Vec::new(), Vec::new(), HashMapWithView::new(), Ghost(Seq::empty()));
    proof {
        assert(p1_inv(n, g.0@, g.1@, g.2@, g.3@, g.4@, n.n as int)) by {
            assert forall|j: int| #![trigger row_hit(n, j)] n.n as int <= j < n.n as int && row_hit(n, j) implies g.3@.contains_key(n.ddate@[j]) by {}
        }
    }
    let mut rest = handles;
    while rest.len() > 0
        invariant
            rest@.len() <= 4,
            rows == n.n,
            chunk == rows / 4 + 1,
            chunk <= 536870913,
            valid_cols_num(n),
            ucode_ok(n, ucode as int),
            forall|mm: int|
                0 <= mm < rest@.len() ==> #[trigger] handle_ok(n, rest@[mm], lo_of(rows as int, chunk as int, mm), lo_of(rows as int, chunk as int, mm + 1)),
            p1_inv(n, g.0@, g.1@, g.2@, g.3@, g.4@, lo_of(rows as int, chunk as int, rest@.len() as int)),
        decreases rest.len(),
    {
        let ghost old_rest = rest@;
        let h = rest.pop().unwrap();
        let c: usize = rest.len();
        proof {
            assert(h == old_rest[c as int]);
            assert(c <= 3);
            assert(c as int * chunk as int <= 3 * 536870913) by (nonlinear_arith)
                requires c <= 3, chunk <= 536870913, c >= 0, chunk >= 0;
            assert((c as int + 1) * chunk as int <= 4 * 536870913) by (nonlinear_arith)
                requires c <= 3, chunk <= 536870913, c >= 0, chunk >= 0;
        }
        let lo: usize = if c * chunk <= rows { c * chunk } else { rows };
        let hi: usize = if (c + 1) * chunk <= rows { (c + 1) * chunk } else { rows };
        proof {
            assert(lo as int == lo_of(rows as int, chunk as int, c as int));
            assert(hi as int == lo_of(rows as int, chunk as int, c as int + 1));
            lemma_lo_range(rows as int, chunk as int, c as int);
            assert(handle_ok(n, h, lo as int, hi as int));
        }
        let r: (Vec<i64>, Vec<u64>, Vec<i128>, HashMapWithView<i64, usize>, Ghost<Seq<int>>);
        match h.join() {
            Ok(rr) => {
                r = rr;
                proof {
                    assert(tab_ok(n, hi as int, lo as int, r));
                }
            },
            Err(_) => {
                r = fold_range(n, ucode, lo, hi);
            },
        }
        merge_worker(n, lo, hi, &mut g, &r);
    }
    proof {
        assert(lo_of(rows as int, chunk as int, 0) == 0);
    }
    let ks = g.0;
    let cs = g.1;
    let ss = g.2;
    let idx = g.3;
    let ghost wit = g.4@;
    // Pass 2: the top 20 groups by sum, repeated maximum over a used flag per group.
    let gn = ks.len();
    let mut used: Vec<bool> = Vec::new();
    let mut f: usize = 0;
    while f < gn
        invariant
            f <= gn,
            gn == ks@.len(),
            used@.len() == f as int,
            forall|q: int| 0 <= q < f as int ==> !used@[q],
        decreases gn - f,
    {
        used.push(false);
        f += 1;
    }
    let mut res: Vec<OutRow> = Vec::new();
    let ghost mut sel: Seq<int> = Seq::empty();
    let ghost mut pos: Seq<int> = Seq::new(ks@.len(), |g: int| 0int);
    proof {
        lemma_tk_count_zero(used@, 0);
        assert(sel_inv(ks@, cs@, ss@, used@, pos, res@, sel));
    }
    while res.len() < 20 && res.len() < gn
        invariant
            gn == ks@.len(),
            res@.len() <= 20,
            sel_inv(ks@, cs@, ss@, used@, pos, res@, sel),
        decreases gn - res.len(),
    {
        proof {
            lemma_tk_count_all(used@, 0);
            lemma_tk_count_untaken(used@, 0);
        }
        let mut have: bool = false;
        let mut bj: usize = 0;
        let mut j: usize = 0;
        while j < gn
            invariant
                j <= gn,
                gn == ks@.len(),
                used@.len() == gn as int,
                ss@.len() == gn as int,
                have ==> (bj < j && !used@[bj as int]),
                have ==> forall|q: int| #![trigger used@[q]] 0 <= q < j as int && !used@[q] ==> ss@[bj as int] >= ss@[q],
                !have ==> forall|q: int| #![trigger used@[q]] 0 <= q < j as int ==> used@[q],
            decreases gn - j,
        {
            if !used[j] {
                if !have {
                    have = true;
                    bj = j;
                } else if ss[j] > ss[bj] {
                    bj = j;
                }
            }
            j += 1;
        }
        proof {
            let q = choose|q: int| 0 <= q < ks@.len() && !used@[q];
            assert(have);
        }
        let p = bj;
        proof {
            lemma_sel_step(ks@, cs@, ss@, used@, pos, res@, sel, p as int);
            sel = sel.push(p as int);
            pos = pos.update(p as int, res@.len() as int);
        }
        res.push(OutRow { ddate: ks[p], c: cs[p], s: ss[p] });
        used.set(p, true);
    }
    proof {
        assert(p1_inv(n, ks@, cs@, ss@, idx@, wit, 0));
        let gk = Seq::new(ks@.len(), |g: int| ks@[g] as int);
        let gw = wit;
        assert(gk.len() == ks@.len());
        assert forall|g: int| #![trigger gk[g]] 0 <= g < gk.len() implies gk[g] == ks@[g] as int by {}
        assert forall|a: int, b: int| #![trigger gk[a], gk[b]] 0 <= a < b < gk.len() implies gk[a] != gk[b] by {
            assert(idx@[ks@[a]] as int == a);
            assert(idx@[ks@[b]] as int == b);
        }
        assert forall|g: int| #![trigger gk[g]] 0 <= g < gk.len() implies row_hit(n, gw[g]) && key_at(n, gw[g]) == gk[g] && (true) by {}
        assert forall|i0: int| #![trigger row_hit(n, i0)] row_hit(n, i0) && (true) implies exists|g: int| #![trigger gk[g]] 0 <= g < gk.len() && gk[g] == key_at(n, i0) by {
            assert(n.ddate@.len() == n.n as int);
            let k = n.ddate@[i0];
            assert(idx@.contains_key(k));
            let g = idx@[k] as int;
            assert(gk[g] == ks@[g] as int);
            assert(ks@[g] == k);
        }
        assert forall|r: int| #![trigger sel[r]] #![trigger res@[r]] 0 <= r < sel.len() implies (true) && (res@[r].c as int) == count_c(n, 0, gk[sel[r]]) && (res@[r].s as int) == sum_s(n, 0, gk[sel[r]]) by {
            assert(res@[r].c == cs@[sel[r]]);
            assert(cs@[sel[r]] as int == count_c(n, 0, ks@[sel[r]] as int));
        }
        assert forall|g: int, r: int| #![trigger used@[g], res@[r]] 0 <= g < gk.len() && !used@[g] && 0 <= r < res@.len() implies (((res@[r].s as int)) >= (sum_s(n, 0, gk[g]))) by {
            assert(res@[r].s >= ss@[g]);
            assert(cs@[g] as int == count_c(n, 0, ks@[g] as int));
            assert(ss@[g] as int == sum_s(n, 0, ks@[g] as int));
        }
        assert(res@.len() == 20 || (forall|g: int| #![trigger used@[g]] 0 <= g < gk.len() ==> used@[g])) by {
            if res@.len() != 20 {
                lemma_tk_count_all(used@, 0);
                lemma_tk_count_all_taken(used@, 0);
            }
        }
        lemma_group_close_rows(n, res@, gk, gw, sel);
        lemma_group_close_distinct(n, res@, gk, sel);
        lemma_group_close_present(n, res@, gk, sel, used@, pos);
        lemma_group_close_omitted(n, res@, gk, sel, used@, pos);
    }
    res
// AGENT_EDIT_END
