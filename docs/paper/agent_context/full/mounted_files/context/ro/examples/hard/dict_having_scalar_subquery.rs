// Worked example (SEC shape, DICTIONARY string mode): `num JOIN sub ... GROUP BY name, cik HAVING SUM(value) > (SELECT AVG(sub_total)
// FROM (SELECT SUM(value) ... GROUP BY cik))`, ORDER BY the total DESC LIMIT 100 (published GenDB Q3 shape). Uncorrelated scalar
// subquery: the threshold is computed once from per-cik totals (exec floor division on u128 of non-negative operands), then the
// groups above it are selected by repeated maximum. The key idea is a per-class sum (sum over the join partner, here
// the dictionary entry of sub) that makes the spec's num-major fold equal to the exec's sub-major sums. Keep each list
// invariant in an opaque spec fn and one step lemma per branch; valid_cols_<t> is in every loop invariant.
// AGENT_HELPERS_START
spec fn usd(n: &Cols_num, i: int) -> bool {
    n.uom__dict@[n.uom@[i] as int]@ == "USD"@
}

spec fn fok(s: &Cols_sub, j: int) -> bool {
    s.fy__valid@[j] && (s.fy@[j] as int) == 2022
}

spec fn nstr(n: &Cols_num, i: int) -> Seq<char> {
    n.adsh__dict@[n.adsh@[i] as int]@
}

spec fn sstr(s: &Cols_sub, j: int) -> Seq<char> {
    s.adsh__dict@[s.adsh@[j] as int]@
}

// per sub-dictionary code c: the sum of the values of the USD num rows (from i on) whose adsh string is entry c
spec fn sd(n: &Cols_num, s: &Cols_sub, c: int, i: int) -> int
    decreases n.n as int - i
{
    if i < 0 || i >= n.n as int {
        0int
    } else {
        (if usd(n, i) && nstr(n, i) == s.adsh__dict@[c]@ { n.value@[i] as int } else { 0int }) + sd(n, s, c, i + 1)
    }
}

// some USD num row from i on has adsh string entry c
spec fn hx(n: &Cols_num, s: &Cols_sub, c: int, i: int) -> bool
    decreases n.n as int - i
{
    if i < 0 || i >= n.n as int {
        false
    } else {
        (usd(n, i) && nstr(n, i) == s.adsh__dict@[c]@) || hx(n, s, c, i + 1)
    }
}

proof fn lemma_hx_sd(n: &Cols_num, s: &Cols_sub, c: int, i: int)
    requires
        0 <= i,
    ensures
        !hx(n, s, c, i) ==> sd(n, s, c, i) == 0,
    decreases n.n as int - i,
{
    if i < n.n as int {
        lemma_hx_sd(n, s, c, i + 1);
    }
}

proof fn lemma_hx_exists(n: &Cols_num, s: &Cols_sub, c: int, i: int)
    requires
        0 <= i,
    ensures
        hx(n, s, c, i) <==> exists|t: int| #![trigger usd(n, t)] i <= t < n.n as int && usd(n, t) && nstr(n, t) == s.adsh__dict@[c]@,
    decreases n.n as int - i,
{
    if i < n.n as int {
        lemma_hx_exists(n, s, c, i + 1);
        if hx(n, s, c, i) {
            if usd(n, i) && nstr(n, i) == s.adsh__dict@[c]@ {
                assert(i <= i && i < n.n as int && usd(n, i) && nstr(n, i) == s.adsh__dict@[c]@);
            } else {
                let t = choose|t: int| #![trigger usd(n, t)] i + 1 <= t < n.n as int && usd(n, t) && nstr(n, t) == s.adsh__dict@[c]@;
                assert(i <= t < n.n as int && usd(n, t) && nstr(n, t) == s.adsh__dict@[c]@);
            }
        }
        if exists|t: int| #![trigger usd(n, t)] i <= t < n.n as int && usd(n, t) && nstr(n, t) == s.adsh__dict@[c]@ {
            let t = choose|t: int| #![trigger usd(n, t)] i <= t < n.n as int && usd(n, t) && nstr(n, t) == s.adsh__dict@[c]@;
            if t == i {
            } else {
                assert(i + 1 <= t < n.n as int && usd(n, t) && nstr(n, t) == s.adsh__dict@[c]@);
            }
        }
    }
}

proof fn lemma_sub_dict_eq(s: &Cols_sub, a: int, b: int)
    requires
        valid_cols_sub(s),
        0 <= a < s.adsh__dict@.len(),
        0 <= b < s.adsh__dict@.len(),
        s.adsh__dict@[a]@ == s.adsh__dict@[b]@,
    ensures
        a == b,
{
    if a < b {
        assert(s.adsh__dict@[a]@ != s.adsh__dict@[b]@);
    } else if b < a {
        assert(s.adsh__dict@[b]@ != s.adsh__dict@[a]@);
    }
}

proof fn lemma_name_dict_eq(s: &Cols_sub, a: int, b: int)
    requires
        valid_cols_sub(s),
        0 <= a < s.name__dict@.len(),
        0 <= b < s.name__dict@.len(),
        s.name__dict@[a]@ == s.name__dict@[b]@,
    ensures
        a == b,
{
    if a < b {
        assert(s.name__dict@[a]@ != s.name__dict@[b]@);
    } else if b < a {
        assert(s.name__dict@[b]@ != s.name__dict@[a]@);
    }
}

// the main-key partial sum: per sub row b from b on that is in group (nc, ck) and passes the filter, the class sum from num row a on
spec fn fg(n: &Cols_num, s: &Cols_sub, a: int, b: int, nc: int, ck: int) -> int
    decreases s.n as int - b
{
    if b < 0 || b >= s.n as int {
        0int
    } else {
        (if (s.name@[b] as int) == nc && (s.cik@[b] as int) == ck && fok(s, b) { sd(n, s, s.adsh@[b] as int, a) } else { 0int }) + fg(n, s, a, b + 1, nc, ck)
    }
}

spec fn fq(n: &Cols_num, s: &Cols_sub, a: int, b: int, ck: int) -> int
    decreases s.n as int - b
{
    if b < 0 || b >= s.n as int {
        0int
    } else {
        (if (s.cik@[b] as int) == ck && fok(s, b) { sd(n, s, s.adsh@[b] as int, a) } else { 0int }) + fq(n, s, a, b + 1, ck)
    }
}

proof fn lemma_sd_oob(n: &Cols_num, s: &Cols_sub, c: int, i: int)
    requires
        i >= n.n as int,
    ensures
        sd(n, s, c, i) == 0,
{
}

proof fn lemma_fg_oob(n: &Cols_num, s: &Cols_sub, a: int, b: int, nc: int, ck: int)
    requires
        a >= n.n as int,
        0 <= b,
    ensures
        fg(n, s, a, b, nc, ck) == 0,
    decreases s.n as int - b,
{
    if b < s.n as int {
        lemma_fg_oob(n, s, a, b + 1, nc, ck);
        lemma_sd_oob(n, s, s.adsh@[b] as int, a);
    }
}

proof fn lemma_fq_oob(n: &Cols_num, s: &Cols_sub, a: int, b: int, ck: int)
    requires
        a >= n.n as int,
        0 <= b,
    ensures
        fq(n, s, a, b, ck) == 0,
    decreases s.n as int - b,
{
    if b < s.n as int {
        lemma_fq_oob(n, s, a, b + 1, ck);
        lemma_sd_oob(n, s, s.adsh@[b] as int, a);
    }
}

// the host's per-key sum over the pairs from (a, b) on, in terms of the class sums
proof fn lemma_link_g_d1(n: &Cols_num, s: &Cols_sub, a: int, b: int, nc: int, ck: int)
    requires
        valid_cols_sub(s),
        0 <= a < n.n as int,
        0 <= b,
        0 <= nc < s.name__dict@.len(),
    ensures
        sum_total_value_d1(n, s, a, b, (s.name__dict@[nc]@, ck)) + fg(n, s, a + 1, b, nc, ck) == fg(n, s, a, b, nc, ck),
    decreases s.n as int - b,
{
    if b < s.n as int {
        lemma_link_g_d1(n, s, a, b + 1, nc, ck);
        let c = s.adsh@[b] as int;
        assert(0 <= (s.name@[b] as int) < s.name__dict@.len());
        assert(sd(n, s, c, a) == (if usd(n, a) && nstr(n, a) == s.adsh__dict@[c]@ { n.value@[a] as int } else { 0int }) + sd(n, s, c, a + 1));
        assert(sstr(s, b) == s.adsh__dict@[c]@);
        if (s.name@[b] as int) != nc {
            if s.name__dict@[s.name@[b] as int]@ == s.name__dict@[nc]@ {
                lemma_name_dict_eq(s, s.name@[b] as int, nc);
            }
        }
        assert(sum_total_value_d1(n, s, a, b, (s.name__dict@[nc]@, ck)) == (if row_hit(n, s, a, b) && key_at(n, s, a, b) == (s.name__dict@[nc]@, ck) { sum_total_value_val(n, s, a, b) } else { 0int }) + sum_total_value_d1(n, s, a, b + 1, (s.name__dict@[nc]@, ck)));
        assert(fg(n, s, a, b, nc, ck) == (if (s.name@[b] as int) == nc && (s.cik@[b] as int) == ck && fok(s, b) { sd(n, s, c, a) } else { 0int }) + fg(n, s, a, b + 1, nc, ck));
        assert(fg(n, s, a + 1, b, nc, ck) == (if (s.name@[b] as int) == nc && (s.cik@[b] as int) == ck && fok(s, b) { sd(n, s, c, a + 1) } else { 0int }) + fg(n, s, a + 1, b + 1, nc, ck));
    }
}

proof fn lemma_link_g(n: &Cols_num, s: &Cols_sub, a: int, nc: int, ck: int)
    requires
        valid_cols_sub(s),
        0 <= a,
        0 <= nc < s.name__dict@.len(),
    ensures
        sum_total_value(n, s, a, (s.name__dict@[nc]@, ck)) == fg(n, s, a, 0, nc, ck),
    decreases n.n as int - a,
{
    if a < n.n as int {
        lemma_link_g(n, s, a + 1, nc, ck);
        lemma_link_g_d1(n, s, a, 0, nc, ck);
    } else {
        lemma_fg_oob(n, s, a, 0, nc, ck);
    }
}

proof fn lemma_link_q_d1(n: &Cols_num, s: &Cols_sub, a: int, b: int, ck: int)
    requires
        valid_cols_sub(s),
        0 <= a < n.n as int,
        0 <= b,
    ensures
        sq_1_sum_sub_total_d1(n, s, a, b, ck) + fq(n, s, a + 1, b, ck) == fq(n, s, a, b, ck),
    decreases s.n as int - b,
{
    if b < s.n as int {
        lemma_link_q_d1(n, s, a, b + 1, ck);
        let c = s.adsh@[b] as int;
        assert(sd(n, s, c, a) == (if usd(n, a) && nstr(n, a) == s.adsh__dict@[c]@ { n.value@[a] as int } else { 0int }) + sd(n, s, c, a + 1));
        assert(sstr(s, b) == s.adsh__dict@[c]@);
        assert(sq_1_sum_sub_total_d1(n, s, a, b, ck) == (if sq_1_row_hit(n, s, a, b) && sq_1_key_at(n, s, a, b) == ck { sq_1_sum_sub_total_val(n, s, a, b) } else { 0int }) + sq_1_sum_sub_total_d1(n, s, a, b + 1, ck));
        assert(fq(n, s, a, b, ck) == (if (s.cik@[b] as int) == ck && fok(s, b) { sd(n, s, c, a) } else { 0int }) + fq(n, s, a, b + 1, ck));
        assert(fq(n, s, a + 1, b, ck) == (if (s.cik@[b] as int) == ck && fok(s, b) { sd(n, s, c, a + 1) } else { 0int }) + fq(n, s, a + 1, b + 1, ck));
    }
}

proof fn lemma_link_q(n: &Cols_num, s: &Cols_sub, a: int, ck: int)
    requires
        valid_cols_sub(s),
        0 <= a,
    ensures
        sq_1_sum_sub_total(n, s, a, ck) == fq(n, s, a, 0, ck),
    decreases n.n as int - a,
{
    if a < n.n as int {
        lemma_link_q(n, s, a + 1, ck);
        lemma_link_q_d1(n, s, a, 0, ck);
    } else {
        lemma_fq_oob(n, s, a, 0, ck);
    }
}
// ---- the HAVING subquery: first occurrences of a cik among the hit pairs, counted/summed against a list of distinct ciks ----
spec fn vv(n: &Cols_num, s: &Cols_sub, which: bool, k: int) -> int {
    if which { sq_1_sum_sub_total(n, s, 0, k) } else { 1int }
}

spec fn sq_seen(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: int) -> bool {
    exists|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 < i0) || (j0 == i0 && j1 < i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k
}

spec fn sq_gex(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: int) -> bool {
    exists|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 > i0) || (j0 == i0 && j1 >= i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k
}

spec fn gfold(n: &Cols_num, s: &Cols_sub, which: bool, i0: int, i1: int) -> int
    decreases (if i0 < n.n as int { n.n as int - i0 } else { 0int }), (if i1 < s.n as int { s.n as int - i1 } else { 0int })
{
    if i0 < 0 || i0 >= n.n as int || i1 < 0 {
        0int
    } else if i1 >= s.n as int {
        gfold(n, s, which, i0 + 1, 0)
    } else {
        (if sq_1_row_hit(n, s, i0, i1) && !sq_seen(n, s, i0, i1, sq_1_key_at(n, s, i0, i1)) { vv(n, s, which, sq_1_key_at(n, s, i0, i1)) } else { 0int })
            + gfold(n, s, which, i0, i1 + 1)
    }
}

proof fn lemma_gfold_acc(n: &Cols_num, s: &Cols_sub, i0: int, i1: int)
    requires
        0 <= i0 < n.n as int,
        0 <= i1,
    ensures
        sq_1_acc_d1(n, s, i0, i1) + sq_1_acc(n, s, i0 + 1) == gfold(n, s, true, i0, i1),
    decreases (if i0 < n.n as int { n.n as int - i0 } else { 0int }), (if i1 < s.n as int { s.n as int - i1 } else { 0int }),
{
    if i1 >= s.n as int {
        assert(sq_1_acc_d1(n, s, i0, i1) == 0);
        assert(gfold(n, s, true, i0, i1) == gfold(n, s, true, i0 + 1, 0));
        if i0 + 1 < n.n as int {
            lemma_gfold_acc(n, s, i0 + 1, 0);
            assert(sq_1_acc(n, s, i0 + 1) == sq_1_acc_d1(n, s, i0 + 1, 0) + sq_1_acc(n, s, i0 + 2));
        } else {
            assert(sq_1_acc(n, s, i0 + 1) == 0);
            assert(gfold(n, s, true, i0 + 1, 0) == 0);
        }
    } else {
        lemma_gfold_acc(n, s, i0, i1 + 1);
        assert(sq_1_acc_d1(n, s, i0, i1) == (if sq_1_row_hit(n, s, i0, i1) && !(exists|j0: int, j1: int| ((j0 < i0) || (j0 == i0 && j1 < i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == sq_1_key_at(n, s, i0, i1)) { sq_1_sum_sub_total(n, s, 0, sq_1_key_at(n, s, i0, i1)) } else { 0int }) + sq_1_acc_d1(n, s, i0, i1 + 1));
        assert(gfold(n, s, true, i0, i1) == (if sq_1_row_hit(n, s, i0, i1) && !sq_seen(n, s, i0, i1, sq_1_key_at(n, s, i0, i1)) { vv(n, s, true, sq_1_key_at(n, s, i0, i1)) } else { 0int }) + gfold(n, s, true, i0, i1 + 1));
    }
}

proof fn lemma_gfold_groups(n: &Cols_num, s: &Cols_sub, i0: int, i1: int)
    requires
        0 <= i0 < n.n as int,
        0 <= i1,
    ensures
        sq_1_groups_d1(n, s, i0, i1) + sq_1_groups(n, s, i0 + 1) == gfold(n, s, false, i0, i1),
    decreases (if i0 < n.n as int { n.n as int - i0 } else { 0int }), (if i1 < s.n as int { s.n as int - i1 } else { 0int }),
{
    if i1 >= s.n as int {
        assert(sq_1_groups_d1(n, s, i0, i1) == 0);
        assert(gfold(n, s, false, i0, i1) == gfold(n, s, false, i0 + 1, 0));
        if i0 + 1 < n.n as int {
            lemma_gfold_groups(n, s, i0 + 1, 0);
            assert(sq_1_groups(n, s, i0 + 1) == sq_1_groups_d1(n, s, i0 + 1, 0) + sq_1_groups(n, s, i0 + 2));
        } else {
            assert(sq_1_groups(n, s, i0 + 1) == 0);
            assert(gfold(n, s, false, i0 + 1, 0) == 0);
        }
    } else {
        lemma_gfold_groups(n, s, i0, i1 + 1);
        assert(sq_1_groups_d1(n, s, i0, i1) == (if sq_1_row_hit(n, s, i0, i1) && !(exists|j0: int, j1: int| ((j0 < i0) || (j0 == i0 && j1 < i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == sq_1_key_at(n, s, i0, i1)) { 1int } else { 0int }) + sq_1_groups_d1(n, s, i0, i1 + 1));
        assert(gfold(n, s, false, i0, i1) == (if sq_1_row_hit(n, s, i0, i1) && !sq_seen(n, s, i0, i1, sq_1_key_at(n, s, i0, i1)) { vv(n, s, false, sq_1_key_at(n, s, i0, i1)) } else { 0int }) + gfold(n, s, false, i0, i1 + 1));
    }
}

proof fn lemma_gfold_top(n: &Cols_num, s: &Cols_sub)
    ensures
        sq_1_acc(n, s, 0) == gfold(n, s, true, 0, 0),
        sq_1_groups(n, s, 0) == gfold(n, s, false, 0, 0),
{
    if n.n as int > 0 {
        lemma_gfold_acc(n, s, 0, 0);
        lemma_gfold_groups(n, s, 0, 0);
    }
}

spec fn ind(n: &Cols_num, s: &Cols_sub, which: bool, k: int, i0: int, i1: int) -> int {
    if !sq_seen(n, s, i0, i1, k) && sq_gex(n, s, i0, i1, k) { vv(n, s, which, k) } else { 0int }
}

spec fn wsum(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, which: bool, m: int, i0: int, i1: int) -> int
    decreases m,
{
    if m <= 0 {
        0int
    } else {
        wsum(n, s, dk, which, m - 1, i0, i1) + ind(n, s, which, dk[m - 1] as int, i0, i1)
    }
}

spec fn vsum(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, which: bool, m: int) -> int
    decreases m,
{
    if m <= 0 {
        0int
    } else {
        vsum(n, s, dk, which, m - 1) + vv(n, s, which, dk[m - 1] as int)
    }
}

spec fn hit_key(n: &Cols_num, s: &Cols_sub, k: int) -> bool {
    exists|a: int, b: int| #![trigger sq_1_row_hit(n, s, a, b)] sq_1_row_hit(n, s, a, b) && sq_1_key_at(n, s, a, b) == k
}

spec fn key_in(dk: Seq<i64>, m: int, key: int) -> bool {
    exists|r: int| #![trigger dk[r]] 0 <= r < m && dk[r] as int == key
}

proof fn lemma_seen_step(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: int)
    ensures
        sq_seen(n, s, i0, i1 + 1, k) <==> (sq_seen(n, s, i0, i1, k) || (sq_1_row_hit(n, s, i0, i1) && sq_1_key_at(n, s, i0, i1) == k)),
{
    if sq_seen(n, s, i0, i1 + 1, k) {
        let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 < i0) || (j0 == i0 && j1 < i1 + 1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
        if j0 == i0 && j1 == i1 {
        } else {
            assert(((j0 < i0) || (j0 == i0 && j1 < i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k);
        }
    }
    if sq_seen(n, s, i0, i1, k) {
        let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 < i0) || (j0 == i0 && j1 < i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
        assert(((j0 < i0) || (j0 == i0 && j1 < i1 + 1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k);
    }
    if sq_1_row_hit(n, s, i0, i1) && sq_1_key_at(n, s, i0, i1) == k {
        assert(((i0 < i0) || (i0 == i0 && i1 < i1 + 1)) && sq_1_row_hit(n, s, i0, i1) && sq_1_key_at(n, s, i0, i1) == k);
    }
}

proof fn lemma_gex_step(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: int)
    ensures
        sq_gex(n, s, i0, i1, k) <==> ((sq_1_row_hit(n, s, i0, i1) && sq_1_key_at(n, s, i0, i1) == k) || sq_gex(n, s, i0, i1 + 1, k)),
{
    if sq_gex(n, s, i0, i1, k) {
        let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 > i0) || (j0 == i0 && j1 >= i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
        if j0 == i0 && j1 == i1 {
        } else {
            assert(((j0 > i0) || (j0 == i0 && j1 >= i1 + 1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k);
        }
    }
    if sq_gex(n, s, i0, i1 + 1, k) {
        let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 > i0) || (j0 == i0 && j1 >= i1 + 1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
        assert(((j0 > i0) || (j0 == i0 && j1 >= i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k);
    }
    if sq_1_row_hit(n, s, i0, i1) && sq_1_key_at(n, s, i0, i1) == k {
        assert(((i0 > i0) || (i0 == i0 && i1 >= i1)) && sq_1_row_hit(n, s, i0, i1) && sq_1_key_at(n, s, i0, i1) == k);
    }
}

proof fn lemma_seen_end(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: int)
    requires
        i1 >= s.n as int,
    ensures
        sq_seen(n, s, i0, i1, k) <==> sq_seen(n, s, i0 + 1, 0, k),
{
    if sq_seen(n, s, i0, i1, k) {
        let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 < i0) || (j0 == i0 && j1 < i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
        assert(((j0 < i0 + 1) || (j0 == i0 + 1 && j1 < 0)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k);
    }
    if sq_seen(n, s, i0 + 1, 0, k) {
        let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 < i0 + 1) || (j0 == i0 + 1 && j1 < 0)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
        assert(((j0 < i0) || (j0 == i0 && j1 < i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k);
    }
}

proof fn lemma_gex_end(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: int)
    requires
        i1 >= s.n as int,
    ensures
        sq_gex(n, s, i0, i1, k) <==> sq_gex(n, s, i0 + 1, 0, k),
{
    if sq_gex(n, s, i0, i1, k) {
        let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 > i0) || (j0 == i0 && j1 >= i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
        assert(((j0 > i0 + 1) || (j0 == i0 + 1 && j1 >= 0)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k);
    }
    if sq_gex(n, s, i0 + 1, 0, k) {
        let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 > i0 + 1) || (j0 == i0 + 1 && j1 >= 0)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
        assert(((j0 > i0) || (j0 == i0 && j1 >= i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k);
    }
}

proof fn lemma_gex_oob(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: int)
    requires
        i0 >= n.n as int,
    ensures
        !sq_gex(n, s, i0, i1, k),
{
    if sq_gex(n, s, i0, i1, k) {
        let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 > i0) || (j0 == i0 && j1 >= i1)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
        assert(false);
    }
}

proof fn lemma_wsum_oob(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, which: bool, m: int, i0: int, i1: int)
    requires
        i0 >= n.n as int,
    ensures
        wsum(n, s, dk, which, m, i0, i1) == 0,
    decreases m,
{
    if m > 0 {
        lemma_wsum_oob(n, s, dk, which, m - 1, i0, i1);
        lemma_gex_oob(n, s, i0, i1, dk[m - 1] as int);
    }
}

proof fn lemma_wsum_end(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, which: bool, m: int, i0: int, i1: int)
    requires
        i1 >= s.n as int,
    ensures
        wsum(n, s, dk, which, m, i0, i1) == wsum(n, s, dk, which, m, i0 + 1, 0),
    decreases m,
{
    if m > 0 {
        lemma_wsum_end(n, s, dk, which, m - 1, i0, i1);
        let k = dk[m - 1] as int;
        lemma_seen_end(n, s, i0, i1, k);
        lemma_gex_end(n, s, i0, i1, k);
    }
}

// per index step: crossing the pair (i0, i1)
proof fn lemma_wsum_step_m(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, which: bool, m: int, i0: int, i1: int)
    requires
        0 <= m,
        forall|a: int, b: int| 0 <= a < b < m ==> #[trigger] dk[a] != #[trigger] dk[b],
    ensures
        sq_1_row_hit(n, s, i0, i1) ==> wsum(n, s, dk, which, m, i0, i1) == wsum(n, s, dk, which, m, i0, i1 + 1)
            + (if key_in(dk, m, sq_1_key_at(n, s, i0, i1)) && !sq_seen(n, s, i0, i1, sq_1_key_at(n, s, i0, i1)) { vv(n, s, which, sq_1_key_at(n, s, i0, i1)) } else { 0int }),
        !sq_1_row_hit(n, s, i0, i1) ==> wsum(n, s, dk, which, m, i0, i1) == wsum(n, s, dk, which, m, i0, i1 + 1),
    decreases m,
{
    if m > 0 {
        lemma_wsum_step_m(n, s, dk, which, m - 1, i0, i1);
        let k = dk[m - 1] as int;
        lemma_seen_step(n, s, i0, i1, k);
        lemma_gex_step(n, s, i0, i1, k);
        if sq_1_row_hit(n, s, i0, i1) {
            let key = sq_1_key_at(n, s, i0, i1);
            if k == key {
                assert(!key_in(dk, m - 1, key)) by {
                    if key_in(dk, m - 1, key) {
                        let r = choose|r: int| #![trigger dk[r]] 0 <= r < m - 1 && dk[r] as int == key;
                        assert(dk[r] != dk[m - 1]);
                    }
                };
                assert(key_in(dk, m, key));
                assert(sq_gex(n, s, i0, i1, k));
                assert(sq_seen(n, s, i0, i1 + 1, k));
            } else {
                assert(key_in(dk, m, key) <==> key_in(dk, m - 1, key)) by {
                    if key_in(dk, m, key) {
                        let r = choose|r: int| #![trigger dk[r]] 0 <= r < m && dk[r] as int == key;
                        assert(r != m - 1);
                    }
                    if key_in(dk, m - 1, key) {
                        let r = choose|r: int| #![trigger dk[r]] 0 <= r < m - 1 && dk[r] as int == key;
                        assert(0 <= r < m && dk[r] as int == key);
                    }
                };
            }
        }
    }
}

proof fn lemma_gfold_wsum(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, which: bool, m: int, i0: int, i1: int)
    requires
        0 <= i0,
        0 <= i1,
        0 <= m,
        forall|a: int, b: int| 0 <= a < b < m ==> #[trigger] dk[a] != #[trigger] dk[b],
        forall|a: int, b: int| #![trigger sq_1_row_hit(n, s, a, b)] sq_1_row_hit(n, s, a, b) ==> key_in(dk, m, sq_1_key_at(n, s, a, b)),
    ensures
        gfold(n, s, which, i0, i1) == wsum(n, s, dk, which, m, i0, i1),
    decreases (if i0 < n.n as int { n.n as int - i0 } else { 0int }), (if i1 < s.n as int { s.n as int - i1 } else { 0int }),
{
    if i0 >= n.n as int {
        lemma_wsum_oob(n, s, dk, which, m, i0, i1);
    } else if i1 >= s.n as int {
        lemma_gfold_wsum(n, s, dk, which, m, i0 + 1, 0);
        lemma_wsum_end(n, s, dk, which, m, i0, i1);
    } else {
        lemma_gfold_wsum(n, s, dk, which, m, i0, i1 + 1);
        lemma_wsum_step_m(n, s, dk, which, m, i0, i1);
    }
}

proof fn lemma_wsum_00(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, which: bool, m: int)
    requires
        0 <= m,
        forall|r: int| #![trigger dk[r]] 0 <= r < m ==> hit_key(n, s, dk[r] as int),
    ensures
        wsum(n, s, dk, which, m, 0, 0) == vsum(n, s, dk, which, m),
    decreases m,
{
    if m > 0 {
        lemma_wsum_00(n, s, dk, which, m - 1);
        let k = dk[m - 1] as int;
        assert(hit_key(n, s, dk[m - 1] as int));
        let (a, b) = choose|a: int, b: int| #![trigger sq_1_row_hit(n, s, a, b)] sq_1_row_hit(n, s, a, b) && sq_1_key_at(n, s, a, b) == dk[m - 1] as int;
        assert(sq_gex(n, s, 0, 0, k)) by {
            assert(((a > 0) || (a == 0 && b >= 0)) && sq_1_row_hit(n, s, a, b) && sq_1_key_at(n, s, a, b) == k);
        };
        assert(!sq_seen(n, s, 0, 0, k)) by {
            if sq_seen(n, s, 0, 0, k) {
                let (j0, j1) = choose|j0: int, j1: int| #![trigger sq_1_row_hit(n, s, j0, j1)] ((j0 < 0) || (j0 == 0 && j1 < 0)) && sq_1_row_hit(n, s, j0, j1) && sq_1_key_at(n, s, j0, j1) == k;
                assert(false);
            }
        };
    }
}

// the HAVING subquery in terms of the list of distinct ciks
proof fn lemma_sq_lists(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, m: int)
    requires
        0 <= m,
        forall|a: int, b: int| 0 <= a < b < m ==> #[trigger] dk[a] != #[trigger] dk[b],
        forall|a: int, b: int| #![trigger sq_1_row_hit(n, s, a, b)] sq_1_row_hit(n, s, a, b) ==> key_in(dk, m, sq_1_key_at(n, s, a, b)),
        forall|r: int| #![trigger dk[r]] 0 <= r < m ==> hit_key(n, s, dk[r] as int),
    ensures
        sq_1_acc(n, s, 0) == vsum(n, s, dk, true, m),
        sq_1_groups(n, s, 0) == m,
{
    lemma_gfold_top(n, s);
    lemma_gfold_wsum(n, s, dk, true, m, 0, 0);
    lemma_gfold_wsum(n, s, dk, false, m, 0, 0);
    lemma_wsum_00(n, s, dk, true, m);
    lemma_wsum_00(n, s, dk, false, m);
    lemma_vsum_count(n, s, dk, m);
}

proof fn lemma_vsum_count(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, m: int)
    requires
        0 <= m,
    ensures
        vsum(n, s, dk, false, m) == m,
    decreases m,
{
    if m > 0 {
        lemma_vsum_count(n, s, dk, m - 1);
    }
}
proof fn lemma_fg_zero(n: &Cols_num, s: &Cols_sub, b: int, nc: int, ck: int)
    requires
        0 <= b,
        forall|jj: int| #![trigger s.adsh@[jj]] b <= jj < s.n as int && (s.name@[jj] as int) == nc && (s.cik@[jj] as int) == ck && fok(s, jj) ==> sd(n, s, s.adsh@[jj] as int, 0) == 0,
    ensures
        fg(n, s, 0, b, nc, ck) == 0,
    decreases s.n as int - b,
{
    if b < s.n as int {
        lemma_fg_zero(n, s, b + 1, nc, ck);
    }
}

proof fn lemma_fq_zero(n: &Cols_num, s: &Cols_sub, b: int, ck: int)
    requires
        0 <= b,
        forall|jj: int| #![trigger s.adsh@[jj]] b <= jj < s.n as int && (s.cik@[jj] as int) == ck && fok(s, jj) ==> sd(n, s, s.adsh@[jj] as int, 0) == 0,
    ensures
        fq(n, s, 0, b, ck) == 0,
    decreases s.n as int - b,
{
    if b < s.n as int {
        lemma_fq_zero(n, s, b + 1, ck);
    }
}
proof fn lemma_fg_unfold(n: &Cols_num, s: &Cols_sub, b: int, nc: int, ck: int)
    requires
        0 <= b < s.n as int,
    ensures
        fg(n, s, 0, b, nc, ck) == (if (s.name@[b] as int) == nc && (s.cik@[b] as int) == ck && fok(s, b) { sd(n, s, s.adsh@[b] as int, 0) } else { 0int }) + fg(n, s, 0, b + 1, nc, ck),
{
}

proof fn lemma_fq_unfold(n: &Cols_num, s: &Cols_sub, b: int, ck: int)
    requires
        0 <= b < s.n as int,
    ensures
        fq(n, s, 0, b, ck) == (if (s.cik@[b] as int) == ck && fok(s, b) { sd(n, s, s.adsh@[b] as int, 0) } else { 0int }) + fq(n, s, 0, b + 1, ck),
{
}

// ---- group list bundles (opaque: revealed only inside the step lemmas) ----
#[verifier::opaque]
spec fn gdist(gn: Seq<u16>, gk: Seq<i64>) -> bool {
    forall|a: int, b: int| #![trigger gn[a], gn[b]] 0 <= a < b < gn.len() ==> !(gn[a] == gn[b] && gk[a] == gk[b])
}

#[verifier::opaque]
spec fn gvals(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, j: int) -> bool {
    &&& gk.len() == gn.len()
    &&& gt.len() == gn.len()
    &&& forall|g: int| #![trigger gn[g]] 0 <= g < gn.len() ==> (gn[g] as int) < s.name__dict@.len() && gt[g] as int == fg(n, s, 0, j, gn[g] as int, gk[g] as int)
        && -(99035203142830421991927790436352int * (s.n as int - j)) <= gt[g] as int && gt[g] as int <= 99035203142830421991927790436352int * (s.n as int - j)
}

#[verifier::opaque]
spec fn gcov(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, j: int) -> bool {
    forall|jj: int| #![trigger s.adsh@[jj]] j <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) ==> exists|g: int| #![trigger gn[g]] 0 <= g < gn.len() && gn[g] as int == s.name@[jj] as int && gk[g] as int == s.cik@[jj] as int
}

#[verifier::opaque]
spec fn gwit(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gw: Seq<int>) -> bool {
    &&& gw.len() == gn.len()
    &&& gk.len() == gn.len()
    &&& forall|g: int| #![trigger gw[g]] 0 <= g < gn.len() ==> 0 <= gw[g] < s.n as int && fok(s, gw[g]) && hx(n, s, s.adsh@[gw[g]] as int, 0) && s.name@[gw[g]] as int == gn[g] as int && s.cik@[gw[g]] as int == gk[g] as int
}

proof fn lemma_gvals_bound(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, j: int, g: int)
    requires
        gvals(n, s, gn, gk, gt, j),
        0 <= g < gn.len(),
    ensures
        -(99035203142830421991927790436352int * (s.n as int - j)) <= gt[g] as int <= 99035203142830421991927790436352int * (s.n as int - j),
{
    reveal(gvals);
    assert(gn[g] as int >= 0);
}

proof fn lemma_g_init(n: &Cols_num, s: &Cols_sub)
    ensures
        gdist(Seq::<u16>::empty(), Seq::<i64>::empty()),
        gvals(n, s, Seq::<u16>::empty(), Seq::<i64>::empty(), Seq::<i128>::empty(), s.n as int),
        gcov(n, s, Seq::<u16>::empty(), Seq::<i64>::empty(), s.n as int),
        gwit(n, s, Seq::<u16>::empty(), Seq::<i64>::empty(), Seq::<int>::empty()),
{
    reveal(gdist);
    reveal(gvals);
    reveal(gcov);
    reveal(gwit);
}

proof fn lemma_g_skip_vals(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, j: int)
    requires
        0 <= j < s.n as int,
        gvals(n, s, gn, gk, gt, j + 1),
        !(fok(s, j) && hx(n, s, s.adsh@[j] as int, 0)),
    ensures
        gvals(n, s, gn, gk, gt, j),
{
    reveal(gvals);
    lemma_hx_sd(n, s, s.adsh@[j] as int, 0);
    assert forall|g: int| #![trigger gn[g]] 0 <= g < gn.len() implies (gn[g] as int) < s.name__dict@.len() && gt[g] as int == fg(n, s, 0, j, gn[g] as int, gk[g] as int)
        && -(99035203142830421991927790436352int * (s.n as int - j)) <= gt[g] as int && gt[g] as int <= 99035203142830421991927790436352int * (s.n as int - j) by {
        lemma_fg_unfold(n, s, j, gn[g] as int, gk[g] as int);
    };
}

proof fn lemma_g_skip_cov(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, j: int)
    requires
        0 <= j < s.n as int,
        gcov(n, s, gn, gk, j + 1),
        !(fok(s, j) && hx(n, s, s.adsh@[j] as int, 0)),
    ensures
        gcov(n, s, gn, gk, j),
{
    reveal(gcov);
    assert forall|jj: int| #![trigger s.adsh@[jj]] j <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) implies exists|g: int| #![trigger gn[g]] 0 <= g < gn.len() && gn[g] as int == s.name@[jj] as int && gk[g] as int == s.cik@[jj] as int by {
        assert(jj != j);
    };
}

proof fn lemma_g_update(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, gt2: Seq<i128>, j: int, g0: int, sval: i128)
    requires
        0 <= j < s.n as int,
        fok(s, j),
        hx(n, s, s.adsh@[j] as int, 0),
        sd(n, s, s.adsh@[j] as int, 0) == sval as int,
        -(99035203142830421991927790436352int) <= sval as int <= 99035203142830421991927790436352int,
        gdist(gn, gk),
        gvals(n, s, gn, gk, gt, j + 1),
        gcov(n, s, gn, gk, j + 1),
        0 <= g0 < gn.len(),
        gn[g0] == s.name@[j],
        gk[g0] == s.cik@[j],
        gt2.len() == gt.len(),
        gt2[g0] as int == gt[g0] as int + sval as int,
        forall|g: int| 0 <= g < gt.len() && g != g0 ==> gt2[g] == gt[g],
    ensures
        gvals(n, s, gn, gk, gt2, j),
        gcov(n, s, gn, gk, j),
{
    reveal(gdist);
    reveal(gvals);
    reveal(gcov);
    assert forall|g: int| #![trigger gn[g]] 0 <= g < gn.len() implies (gn[g] as int) < s.name__dict@.len() && gt2[g] as int == fg(n, s, 0, j, gn[g] as int, gk[g] as int)
        && -(99035203142830421991927790436352int * (s.n as int - j)) <= gt2[g] as int && gt2[g] as int <= 99035203142830421991927790436352int * (s.n as int - j) by {
        lemma_fg_unfold(n, s, j, gn[g] as int, gk[g] as int);
        if g != g0 {
            if g < g0 {
                assert(!(gn[g] == gn[g0] && gk[g] == gk[g0]));
            } else {
                assert(!(gn[g0] == gn[g] && gk[g0] == gk[g]));
            }
        }
    };
    assert forall|jj: int| #![trigger s.adsh@[jj]] j <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) implies exists|g: int| #![trigger gn[g]] 0 <= g < gn.len() && gn[g] as int == s.name@[jj] as int && gk[g] as int == s.cik@[jj] as int by {
        if jj == j {
            assert(gn[g0] as int == s.name@[jj] as int);
        }
    };
}

proof fn lemma_g_push(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, gw: Seq<int>, gn2: Seq<u16>, gk2: Seq<i64>, gt2: Seq<i128>, gw2: Seq<int>, j: int, sval: i128)
    requires
        0 <= j < s.n as int,
        fok(s, j),
        hx(n, s, s.adsh@[j] as int, 0),
        sd(n, s, s.adsh@[j] as int, 0) == sval as int,
        -(99035203142830421991927790436352int) <= sval as int <= 99035203142830421991927790436352int,
        (s.name@[j] as int) < s.name__dict@.len(),
        gdist(gn, gk),
        gvals(n, s, gn, gk, gt, j + 1),
        gcov(n, s, gn, gk, j + 1),
        gwit(n, s, gn, gk, gw),
        forall|g: int| 0 <= g < gn.len() ==> !(gn[g] == s.name@[j] && gk[g] == s.cik@[j]),
        gw2 == gw.push(j),
        gn2 == gn.push(s.name@[j]),
        gk2 == gk.push(s.cik@[j]),
        gt2 == gt.push(sval),
    ensures
        gdist(gn2, gk2),
        gvals(n, s, gn2, gk2, gt2, j),
        gcov(n, s, gn2, gk2, j),
        gwit(n, s, gn2, gk2, gw2),
{
    reveal(gdist);
    reveal(gvals);
    reveal(gcov);
    reveal(gwit);
    let nlen = gn.len() as int;
    let nm = s.name@[j];
    let ck = s.cik@[j];
    assert forall|jj: int| #![trigger s.adsh@[jj]] j + 1 <= jj < s.n as int && (s.name@[jj] as int) == nm as int && (s.cik@[jj] as int) == ck as int && fok(s, jj) implies sd(n, s, s.adsh@[jj] as int, 0) == 0 by {
        if hx(n, s, s.adsh@[jj] as int, 0) {
            let g2 = choose|g2: int| #![trigger gn[g2]] 0 <= g2 < gn.len() && gn[g2] as int == s.name@[jj] as int && gk[g2] as int == s.cik@[jj] as int;
            assert(!(gn[g2] == nm && gk[g2] == ck));
        } else {
            lemma_hx_sd(n, s, s.adsh@[jj] as int, 0);
        }
    };
    lemma_fg_zero(n, s, j + 1, nm as int, ck as int);
    lemma_fg_unfold(n, s, j, nm as int, ck as int);
    assert forall|a: int, b: int| #![trigger gn2[a], gn2[b]] 0 <= a < b < gn2.len() implies !(gn2[a] == gn2[b] && gk2[a] == gk2[b]) by {
        if b == nlen {
            assert(!(gn[a] == nm && gk[a] == ck));
        }
    };
    assert forall|g: int| #![trigger gn2[g]] 0 <= g < gn2.len() implies (gn2[g] as int) < s.name__dict@.len() && gt2[g] as int == fg(n, s, 0, j, gn2[g] as int, gk2[g] as int)
        && -(99035203142830421991927790436352int * (s.n as int - j)) <= gt2[g] as int && gt2[g] as int <= 99035203142830421991927790436352int * (s.n as int - j) by {
        if g < nlen {
            assert(gn2[g] == gn[g]);
            assert(gk2[g] == gk[g]);
            assert(!(gn[g] == nm && gk[g] == ck));
            lemma_fg_unfold(n, s, j, gn[g] as int, gk[g] as int);
        }
    };
    assert forall|jj: int| #![trigger s.adsh@[jj]] j <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) implies exists|g: int| #![trigger gn2[g]] 0 <= g < gn2.len() && gn2[g] as int == s.name@[jj] as int && gk2[g] as int == s.cik@[jj] as int by {
        if jj == j {
            assert(gn2[nlen] as int == s.name@[jj] as int);
        } else {
            let g3 = choose|g3: int| #![trigger gn[g3]] 0 <= g3 < gn.len() && gn[g3] as int == s.name@[jj] as int && gk[g3] as int == s.cik@[jj] as int;
            assert(gn2[g3] == gn[g3]);
        }
    };
    assert forall|g: int| #![trigger gw2[g]] 0 <= g < gn2.len() implies 0 <= gw2[g] < s.n as int && fok(s, gw2[g]) && hx(n, s, s.adsh@[gw2[g]] as int, 0) && s.name@[gw2[g]] as int == gn2[g] as int && s.cik@[gw2[g]] as int == gk2[g] as int by {
        if g == nlen {
            assert(gw2[g] == j);
        } else {
            assert(gw2[g] == gw[g]);
            assert(gn2[g] == gn[g]);
            assert(gk2[g] == gk[g]);
        }
    };
}
// ---- the class sums bundle ----
#[verifier::opaque]
spec fn svinv(n: &Cols_num, s: &Cols_sub, sv: Seq<i128>, hv: Seq<bool>, i: int) -> bool {
    &&& sv.len() == s.adsh__dict@.len()
    &&& hv.len() == s.adsh__dict@.len()
    &&& forall|c: int| #![trigger sv[c]] #![trigger hv[c]] 0 <= c < sv.len() ==> sv[c] as int == sd(n, s, c, i) && hv[c] == hx(n, s, c, i)
        && -(46116860184273879039999int * (n.n as int - i)) <= sv[c] as int && sv[c] as int <= 46116860184273879039999int * (n.n as int - i)
}

proof fn lemma_sv_init(n: &Cols_num, s: &Cols_sub, sv: Seq<i128>, hv: Seq<bool>)
    requires
        sv.len() == s.adsh__dict@.len(),
        hv.len() == s.adsh__dict@.len(),
        forall|c: int| #![trigger sv[c]] 0 <= c < sv.len() ==> sv[c] == 0 && !hv[c],
    ensures
        svinv(n, s, sv, hv, n.n as int),
{
    reveal(svinv);
    assert forall|c: int| #![trigger sv[c]] #![trigger hv[c]] 0 <= c < sv.len() implies sv[c] as int == sd(n, s, c, n.n as int) && hv[c] == hx(n, s, c, n.n as int)
        && -(46116860184273879039999int * (n.n as int - n.n as int)) <= sv[c] as int && sv[c] as int <= 46116860184273879039999int * (n.n as int - n.n as int) by {
        assert(sv[c] == 0);
        assert(!hv[c]);
        assert(sd(n, s, c, n.n as int) == 0);
        assert(!hx(n, s, c, n.n as int));
    };
}

proof fn lemma_sv_nomatch(n: &Cols_num, s: &Cols_sub, sv: Seq<i128>, hv: Seq<bool>, i: int)
    requires
        0 <= i < n.n as int,
        svinv(n, s, sv, hv, i + 1),
        forall|c: int| 0 <= c < sv.len() ==> !(usd(n, i) && nstr(n, i) == s.adsh__dict@[c]@),
    ensures
        svinv(n, s, sv, hv, i),
{
    reveal(svinv);
    assert forall|c: int| #![trigger sv[c]] #![trigger hv[c]] 0 <= c < sv.len() implies sv[c] as int == sd(n, s, c, i) && hv[c] == hx(n, s, c, i)
        && -(46116860184273879039999int * (n.n as int - i)) <= sv[c] as int && sv[c] as int <= 46116860184273879039999int * (n.n as int - i) by {
        assert(sd(n, s, c, i) == (if usd(n, i) && nstr(n, i) == s.adsh__dict@[c]@ { n.value@[i] as int } else { 0int }) + sd(n, s, c, i + 1));
        assert(hx(n, s, c, i) == ((usd(n, i) && nstr(n, i) == s.adsh__dict@[c]@) || hx(n, s, c, i + 1)));
    };
}

proof fn lemma_sv_match(n: &Cols_num, s: &Cols_sub, sv: Seq<i128>, hv: Seq<bool>, sv2: Seq<i128>, hv2: Seq<bool>, i: int, t: int)
    requires
        valid_cols_sub(s),
        0 <= i < n.n as int,
        svinv(n, s, sv, hv, i + 1),
        usd(n, i),
        0 <= t < sv.len(),
        nstr(n, i) == s.adsh__dict@[t]@,
        -46116860184273879039999int <= n.value@[i] as int <= 46116860184273879039999int,
        sv2.len() == sv.len(),
        hv2.len() == hv.len(),
        sv2[t] as int == sv[t] as int + n.value@[i] as int,
        hv2[t],
        forall|c: int| 0 <= c < sv.len() && c != t ==> sv2[c] == sv[c] && hv2[c] == hv[c],
    ensures
        svinv(n, s, sv2, hv2, i),
{
    reveal(svinv);
    assert forall|c: int| #![trigger sv2[c]] #![trigger hv2[c]] 0 <= c < sv2.len() implies sv2[c] as int == sd(n, s, c, i) && hv2[c] == hx(n, s, c, i)
        && -(46116860184273879039999int * (n.n as int - i)) <= sv2[c] as int && sv2[c] as int <= 46116860184273879039999int * (n.n as int - i) by {
        assert(sd(n, s, c, i) == (if usd(n, i) && nstr(n, i) == s.adsh__dict@[c]@ { n.value@[i] as int } else { 0int }) + sd(n, s, c, i + 1));
        assert(hx(n, s, c, i) == ((usd(n, i) && nstr(n, i) == s.adsh__dict@[c]@) || hx(n, s, c, i + 1)));
        if c != t {
            if s.adsh__dict@[c]@ == nstr(n, i) {
                lemma_sub_dict_eq(s, c, t);
            }
        }
    };
}

proof fn lemma_sv_at(n: &Cols_num, s: &Cols_sub, sv: Seq<i128>, hv: Seq<bool>, c: int)
    requires
        valid_cols_num(n),
        svinv(n, s, sv, hv, 0),
        0 <= c < sv.len(),
    ensures
        sv[c] as int == sd(n, s, c, 0),
        hv[c] == hx(n, s, c, 0),
        -(99035203142830421991927790436352int) <= sv[c] as int <= 99035203142830421991927790436352int,
{
    reveal(svinv);
    assert(sv[c] as int == sd(n, s, c, 0));
    assert(n.n as int <= ROW_CAP_num as int);
    assert(46116860184273879039999int * (n.n as int) <= 46116860184273879039999int * 2147483648int);
}
// ---- cik list bundles ----
spec fn sumseq(sq: Seq<i128>, m: int) -> int
    decreases m,
{
    if m <= 0 {
        0int
    } else {
        sumseq(sq, m - 1) + sq[m - 1] as int
    }
}

proof fn lemma_sumseq_ext(a: Seq<i128>, b: Seq<i128>, m: int)
    requires
        m <= a.len(),
        m <= b.len(),
        forall|r: int| 0 <= r < m ==> a[r] == b[r],
    ensures
        sumseq(a, m) == sumseq(b, m),
    decreases m,
{
    if m > 0 {
        lemma_sumseq_ext(a, b, m - 1);
    }
}

proof fn lemma_sumseq_push(sq: Seq<i128>, x: i128)
    ensures
        sumseq(sq.push(x), sq.len() as int + 1) == sumseq(sq, sq.len() as int) + x as int,
{
    lemma_sumseq_ext(sq.push(x), sq, sq.len() as int);
}

proof fn lemma_sumseq_set(sq: Seq<i128>, sq2: Seq<i128>, g: int, m: int)
    requires
        0 <= g < m <= sq.len(),
        sq2.len() == sq.len(),
        forall|r: int| 0 <= r < sq.len() && r != g ==> sq2[r] == sq[r],
    ensures
        sumseq(sq2, m) == sumseq(sq, m) - sq[g] as int + sq2[g] as int,
    decreases m,
{
    if m - 1 == g {
        lemma_sumseq_ext(sq2, sq, m - 1);
    } else {
        lemma_sumseq_set(sq, sq2, g, m - 1);
    }
}

spec fn kacc(ct: Seq<i128>, acc: i128, s: &Cols_sub, j: int) -> bool {
    &&& acc as int == sumseq(ct, ct.len() as int)
    &&& -(99035203142830421991927790436352int * (s.n as int - j)) <= acc as int
    &&& acc as int <= 99035203142830421991927790436352int * (s.n as int - j)
}

#[verifier::opaque]
spec fn kdist(dk: Seq<i64>) -> bool {
    forall|a: int, b: int| #![trigger dk[a], dk[b]] 0 <= a < b < dk.len() ==> dk[a] != dk[b]
}

#[verifier::opaque]
spec fn kvals(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, ct: Seq<i128>, j: int) -> bool {
    &&& ct.len() == dk.len()
    &&& forall|g: int| #![trigger dk[g]] 0 <= g < dk.len() ==> ct[g] as int == fq(n, s, 0, j, dk[g] as int)
        && -(99035203142830421991927790436352int * (s.n as int - j)) <= ct[g] as int && ct[g] as int <= 99035203142830421991927790436352int * (s.n as int - j)
}

#[verifier::opaque]
spec fn kcov(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, j: int) -> bool {
    forall|jj: int| #![trigger s.adsh@[jj]] j <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) ==> exists|g: int| #![trigger dk[g]] 0 <= g < dk.len() && dk[g] as int == s.cik@[jj] as int
}

#[verifier::opaque]
spec fn kwit(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>) -> bool {
    forall|g: int| #![trigger dk[g]] 0 <= g < dk.len() ==> exists|jj: int| #![trigger s.adsh@[jj]] 0 <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) && s.cik@[jj] as int == dk[g] as int
}

proof fn lemma_kvals_bound(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, ct: Seq<i128>, j: int, g: int)
    requires
        kvals(n, s, dk, ct, j),
        0 <= g < dk.len(),
    ensures
        -(99035203142830421991927790436352int * (s.n as int - j)) <= ct[g] as int <= 99035203142830421991927790436352int * (s.n as int - j),
{
    reveal(kvals);
    assert(dk[g] as int >= -9223372036854775808int);
}

proof fn lemma_k_init(n: &Cols_num, s: &Cols_sub)
    ensures
        kdist(Seq::<i64>::empty()),
        kvals(n, s, Seq::<i64>::empty(), Seq::<i128>::empty(), s.n as int),
        kcov(n, s, Seq::<i64>::empty(), s.n as int),
        kwit(n, s, Seq::<i64>::empty()),
        kacc(Seq::<i128>::empty(), 0i128, s, s.n as int),
{
    reveal(kdist);
    reveal(kvals);
    reveal(kcov);
    reveal(kwit);
}

proof fn lemma_k_skip_vals(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, ct: Seq<i128>, j: int)
    requires
        0 <= j < s.n as int,
        kvals(n, s, dk, ct, j + 1),
        !(fok(s, j) && hx(n, s, s.adsh@[j] as int, 0)),
    ensures
        kvals(n, s, dk, ct, j),
{
    reveal(kvals);
    lemma_hx_sd(n, s, s.adsh@[j] as int, 0);
    assert forall|g: int| #![trigger dk[g]] 0 <= g < dk.len() implies ct[g] as int == fq(n, s, 0, j, dk[g] as int)
        && -(99035203142830421991927790436352int * (s.n as int - j)) <= ct[g] as int && ct[g] as int <= 99035203142830421991927790436352int * (s.n as int - j) by {
        lemma_fq_unfold(n, s, j, dk[g] as int);
    };
}

proof fn lemma_k_skip_cov(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, j: int)
    requires
        0 <= j < s.n as int,
        kcov(n, s, dk, j + 1),
        !(fok(s, j) && hx(n, s, s.adsh@[j] as int, 0)),
    ensures
        kcov(n, s, dk, j),
{
    reveal(kcov);
    assert forall|jj: int| #![trigger s.adsh@[jj]] j <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) implies exists|g: int| #![trigger dk[g]] 0 <= g < dk.len() && dk[g] as int == s.cik@[jj] as int by {
        assert(jj != j);
    };
}

proof fn lemma_k_update(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, ct: Seq<i128>, ct2: Seq<i128>, j: int, g0: int, sval: i128)
    requires
        0 <= j < s.n as int,
        fok(s, j),
        hx(n, s, s.adsh@[j] as int, 0),
        sd(n, s, s.adsh@[j] as int, 0) == sval as int,
        -(99035203142830421991927790436352int) <= sval as int <= 99035203142830421991927790436352int,
        kdist(dk),
        kvals(n, s, dk, ct, j + 1),
        kcov(n, s, dk, j + 1),
        0 <= g0 < dk.len(),
        dk[g0] == s.cik@[j],
        ct2.len() == ct.len(),
        ct2[g0] as int == ct[g0] as int + sval as int,
        forall|g: int| 0 <= g < ct.len() && g != g0 ==> ct2[g] == ct[g],
    ensures
        kvals(n, s, dk, ct2, j),
        kcov(n, s, dk, j),
{
    reveal(kdist);
    reveal(kvals);
    reveal(kcov);
    assert forall|g: int| #![trigger dk[g]] 0 <= g < dk.len() implies ct2[g] as int == fq(n, s, 0, j, dk[g] as int)
        && -(99035203142830421991927790436352int * (s.n as int - j)) <= ct2[g] as int && ct2[g] as int <= 99035203142830421991927790436352int * (s.n as int - j) by {
        lemma_fq_unfold(n, s, j, dk[g] as int);
        if g != g0 {
            if g < g0 {
                assert(dk[g] != dk[g0]);
            } else {
                assert(dk[g0] != dk[g]);
            }
        }
    };
    assert forall|jj: int| #![trigger s.adsh@[jj]] j <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) implies exists|g: int| #![trigger dk[g]] 0 <= g < dk.len() && dk[g] as int == s.cik@[jj] as int by {
        if jj == j {
            assert(dk[g0] as int == s.cik@[jj] as int);
        }
    };
}

proof fn lemma_k_push(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, ct: Seq<i128>, dk2: Seq<i64>, ct2: Seq<i128>, j: int, sval: i128)
    requires
        0 <= j < s.n as int,
        fok(s, j),
        hx(n, s, s.adsh@[j] as int, 0),
        sd(n, s, s.adsh@[j] as int, 0) == sval as int,
        -(99035203142830421991927790436352int) <= sval as int <= 99035203142830421991927790436352int,
        kdist(dk),
        kvals(n, s, dk, ct, j + 1),
        kcov(n, s, dk, j + 1),
        kwit(n, s, dk),
        forall|g: int| 0 <= g < dk.len() ==> dk[g] != s.cik@[j],
        dk2 == dk.push(s.cik@[j]),
        ct2 == ct.push(sval),
    ensures
        kdist(dk2),
        kvals(n, s, dk2, ct2, j),
        kcov(n, s, dk2, j),
        kwit(n, s, dk2),
{
    reveal(kdist);
    reveal(kvals);
    reveal(kcov);
    reveal(kwit);
    let nlen = dk.len() as int;
    let ck = s.cik@[j];
    assert forall|jj: int| #![trigger s.adsh@[jj]] j + 1 <= jj < s.n as int && (s.cik@[jj] as int) == ck as int && fok(s, jj) implies sd(n, s, s.adsh@[jj] as int, 0) == 0 by {
        if hx(n, s, s.adsh@[jj] as int, 0) {
            let g2 = choose|g2: int| #![trigger dk[g2]] 0 <= g2 < dk.len() && dk[g2] as int == s.cik@[jj] as int;
            assert(dk[g2] != ck);
        } else {
            lemma_hx_sd(n, s, s.adsh@[jj] as int, 0);
        }
    };
    lemma_fq_zero(n, s, j + 1, ck as int);
    lemma_fq_unfold(n, s, j, ck as int);
    assert forall|a: int, b: int| #![trigger dk2[a], dk2[b]] 0 <= a < b < dk2.len() implies dk2[a] != dk2[b] by {
        if b == nlen {
            assert(dk[a] != ck);
        }
    };
    assert forall|g: int| #![trigger dk2[g]] 0 <= g < dk2.len() implies ct2[g] as int == fq(n, s, 0, j, dk2[g] as int)
        && -(99035203142830421991927790436352int * (s.n as int - j)) <= ct2[g] as int && ct2[g] as int <= 99035203142830421991927790436352int * (s.n as int - j) by {
        if g < nlen {
            assert(dk2[g] == dk[g]);
            assert(dk[g] != ck);
            lemma_fq_unfold(n, s, j, dk[g] as int);
        }
    };
    assert forall|jj: int| #![trigger s.adsh@[jj]] j <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) implies exists|g: int| #![trigger dk2[g]] 0 <= g < dk2.len() && dk2[g] as int == s.cik@[jj] as int by {
        if jj == j {
            assert(dk2[nlen] as int == s.cik@[jj] as int);
        } else {
            let g3 = choose|g3: int| #![trigger dk[g3]] 0 <= g3 < dk.len() && dk[g3] as int == s.cik@[jj] as int;
            assert(dk2[g3] == dk[g3]);
        }
    };
    assert forall|g: int| #![trigger dk2[g]] 0 <= g < dk2.len() implies exists|jj: int| #![trigger s.adsh@[jj]] 0 <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) && s.cik@[jj] as int == dk2[g] as int by {
        if g == nlen {
            assert(0 <= j < s.n as int && fok(s, j) && hx(n, s, s.adsh@[j] as int, 0));
        } else {
            let jj = choose|jj: int| #![trigger s.adsh@[jj]] 0 <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) && s.cik@[jj] as int == dk[g] as int;
            assert(dk2[g] == dk[g]);
        }
    };
}

proof fn lemma_kacc_skip(ct: Seq<i128>, acc: i128, s: &Cols_sub, j: int)
    requires
        kacc(ct, acc, s, j + 1),
    ensures
        kacc(ct, acc, s, j),
{
}

proof fn lemma_kacc_push(ct: Seq<i128>, acc: i128, acc2: i128, sval: i128, s: &Cols_sub, j: int)
    requires
        kacc(ct, acc, s, j + 1),
        acc2 as int == acc as int + sval as int,
        -(99035203142830421991927790436352int) <= sval as int <= 99035203142830421991927790436352int,
    ensures
        kacc(ct.push(sval), acc2, s, j),
{
    lemma_sumseq_push(ct, sval);
}

proof fn lemma_kacc_set(ct: Seq<i128>, ct2: Seq<i128>, acc: i128, acc2: i128, sval: i128, g0: int, s: &Cols_sub, j: int)
    requires
        kacc(ct, acc, s, j + 1),
        0 <= g0 < ct.len(),
        ct2.len() == ct.len(),
        ct2[g0] as int == ct[g0] as int + sval as int,
        forall|r: int| 0 <= r < ct.len() && r != g0 ==> ct2[r] == ct[r],
        acc2 as int == acc as int + sval as int,
        -(99035203142830421991927790436352int) <= sval as int <= 99035203142830421991927790436352int,
    ensures
        kacc(ct2, acc2, s, j),
{
    lemma_sumseq_set(ct, ct2, g0, ct.len() as int);
}

// an active sub row has a hit pair, and conversely
proof fn lemma_active_hit(n: &Cols_num, s: &Cols_sub, jj: int)
    requires
        0 <= jj < s.n as int,
        valid_cols_sub(s),
    ensures
        (fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0)) <==> exists|i: int| #![trigger row_hit(n, s, i, jj)] row_hit(n, s, i, jj),
{
    lemma_hx_exists(n, s, s.adsh@[jj] as int, 0);
    if fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) {
        let t = choose|t: int| #![trigger usd(n, t)] 0 <= t < n.n as int && usd(n, t) && nstr(n, t) == s.adsh__dict@[s.adsh@[jj] as int]@;
        assert(row_hit(n, s, t, jj));
    }
    if exists|i: int| #![trigger row_hit(n, s, i, jj)] row_hit(n, s, i, jj) {
        let i = choose|i: int| #![trigger row_hit(n, s, i, jj)] row_hit(n, s, i, jj);
        assert(0 <= i < n.n as int && usd(n, i) && nstr(n, i) == s.adsh__dict@[s.adsh@[jj] as int]@);
    }
}

// the final facts about the cik list, then the HAVING subquery value
proof fn lemma_k_final(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, ct: Seq<i128>)
    requires
        valid_cols_sub(s),
        kdist(dk),
        kvals(n, s, dk, ct, 0),
        kcov(n, s, dk, 0),
        kwit(n, s, dk),
    ensures
        sq_1_acc(n, s, 0) == sumseq(ct, dk.len() as int),
        sq_1_groups(n, s, 0) == dk.len() as int,
{
    let m = dk.len() as int;
    reveal(kdist);
    reveal(kvals);
    reveal(kcov);
    reveal(kwit);
    assert forall|a: int, b: int| #![trigger sq_1_row_hit(n, s, a, b)] sq_1_row_hit(n, s, a, b) implies key_in(dk, m, sq_1_key_at(n, s, a, b)) by {
        assert(row_hit(n, s, a, b));
        lemma_active_hit(n, s, b);
        assert(s.adsh@[b] as int >= 0);
        assert(0 <= b < s.n as int && fok(s, b) && hx(n, s, s.adsh@[b] as int, 0));
        assert(sq_1_key_at(n, s, a, b) == s.cik@[b] as int);
    };
    assert forall|r: int| #![trigger dk[r]] 0 <= r < m implies hit_key(n, s, dk[r] as int) by {
        let jj = choose|jj: int| #![trigger s.adsh@[jj]] 0 <= jj < s.n as int && fok(s, jj) && hx(n, s, s.adsh@[jj] as int, 0) && s.cik@[jj] as int == dk[r] as int;
        lemma_active_hit(n, s, jj);
        let i = choose|i: int| #![trigger row_hit(n, s, i, jj)] row_hit(n, s, i, jj);
        assert(sq_1_row_hit(n, s, i, jj));
        assert(sq_1_key_at(n, s, i, jj) == dk[r] as int);
    };
    lemma_sq_lists(n, s, dk, m);
    lemma_vsum_ct(n, s, dk, ct, m);
}

proof fn lemma_vsum_ct(n: &Cols_num, s: &Cols_sub, dk: Seq<i64>, ct: Seq<i128>, m: int)
    requires
        valid_cols_sub(s),
        0 <= m <= dk.len(),
        ct.len() == dk.len(),
        forall|g: int| #![trigger dk[g]] 0 <= g < dk.len() ==> ct[g] as int == fq(n, s, 0, 0, dk[g] as int),
    ensures
        vsum(n, s, dk, true, m) == sumseq(ct, m),
    decreases m,
{
    if m > 0 {
        lemma_vsum_ct(n, s, dk, ct, m - 1);
        lemma_link_q(n, s, 0, dk[m - 1] as int);
        assert(dk[m - 1] as int >= -9223372036854775808int);
    }
}
// ---- floor division by a positive count, from non-negative unsigned quotients ----
proof fn lemma_floor_neg(a: int, c: int, uq: int, ur: int)
    requires
        c > 0,
        a < 0,
        uq == (-a + c - 1) / c,
        ur == (-a + c - 1) % c,
    ensures
        -uq == a / c,
{
    lemma_fundamental_div_mod(-a + c - 1, c);
    assert(0 <= ur < c);
    assert(a == (-uq) * c + (c - 1 - ur)) by (nonlinear_arith)
        requires
            -a + c - 1 == c * uq + ur,
    ;
    lemma_fundamental_div_mod_converse(a, c, -uq, c - 1 - ur);
}

spec fn gvals_names(s: &Cols_sub, gn: Seq<u16>) -> bool {
    forall|g: int| #![trigger gn[g]] 0 <= g < gn.len() ==> (gn[g] as int) < s.name__dict@.len()
}

// ---- the group facts in terms of the host spec ----
#[verifier::opaque]
spec fn gfa(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>) -> bool {
    forall|g: int| #![trigger gn[g]] 0 <= g < gn.len() ==> (gn[g] as int) < s.name__dict@.len() && gt[g] as int == sum_total_value(n, s, 0, (s.name__dict@[gn[g] as int]@, gk[g] as int))
}

#[verifier::opaque]
spec fn gfc(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>) -> bool {
    forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) ==> exists|g: int| #![trigger gn[g]] 0 <= g < gn.len() && gn[g] as int == s.name@[i1] as int && gk[g] as int == s.cik@[i1] as int
}

#[verifier::opaque]
spec fn gfd(s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>) -> bool {
    forall|a: int, b: int| #![trigger gn[a], gn[b]] 0 <= a < b < gn.len() ==> (s.name__dict@[gn[a] as int]@, gk[a] as int) != (s.name__dict@[gn[b] as int]@, gk[b] as int)
}

proof fn lemma_gfa(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>)
    requires
        valid_cols_sub(s),
        gvals(n, s, gn, gk, gt, 0),
    ensures
        gfa(n, s, gn, gk, gt),
{
    reveal(gvals);
    reveal(gfa);
    assert forall|g: int| #![trigger gn[g]] 0 <= g < gn.len() implies (gn[g] as int) < s.name__dict@.len() && gt[g] as int == sum_total_value(n, s, 0, (s.name__dict@[gn[g] as int]@, gk[g] as int)) by {
        lemma_link_g(n, s, 0, gn[g] as int, gk[g] as int);
    };
}

proof fn lemma_gfc(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>)
    requires
        valid_cols_sub(s),
        gk.len() == gn.len(),
        gcov(n, s, gn, gk, 0),
    ensures
        gfc(n, s, gn, gk),
{
    reveal(gcov);
    reveal(gfc);
    assert forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) implies exists|g: int| #![trigger gn[g]] 0 <= g < gn.len() && gn[g] as int == s.name@[i1] as int && gk[g] as int == s.cik@[i1] as int by {
        lemma_active_hit(n, s, i1);
        assert(s.adsh@[i1] as int >= 0);
        assert(fok(s, i1) && hx(n, s, s.adsh@[i1] as int, 0));
    };
}

proof fn lemma_gfd(s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>)
    requires
        valid_cols_sub(s),
        gk.len() == gn.len(),
        gdist(gn, gk),
        gvals_names(s, gn),
    ensures
        gfd(s, gn, gk),
{
    reveal(gdist);
    reveal(gfd);
    assert forall|a: int, b: int| #![trigger gn[a], gn[b]] 0 <= a < b < gn.len() implies (s.name__dict@[gn[a] as int]@, gk[a] as int) != (s.name__dict@[gn[b] as int]@, gk[b] as int) by {
        if (s.name__dict@[gn[a] as int]@, gk[a] as int) == (s.name__dict@[gn[b] as int]@, gk[b] as int) {
            lemma_name_dict_eq(s, gn[a] as int, gn[b] as int);
            assert(gn[a] == gn[b]);
            assert(gk[a] == gk[b]);
        }
    };
}

proof fn lemma_g_final(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, gw: Seq<int>)
    requires
        valid_cols_sub(s),
        gdist(gn, gk),
        gvals(n, s, gn, gk, gt, 0),
        gcov(n, s, gn, gk, 0),
        gwit(n, s, gn, gk, gw),
    ensures
        gfa(n, s, gn, gk, gt),
        gfc(n, s, gn, gk),
        gfd(s, gn, gk),
        gvals_names(s, gn),
{
    lemma_gfa(n, s, gn, gk, gt);
    reveal(gfa);
    reveal(gvals);
    assert(gk.len() == gn.len());
    assert(gvals_names(s, gn)) by {
        assert forall|g: int| #![trigger gn[g]] 0 <= g < gn.len() implies (gn[g] as int) < s.name__dict@.len() by {
            assert(gn[g] as int >= 0);
        };
    };
    lemma_gfa(n, s, gn, gk, gt);
    lemma_gfc(n, s, gn, gk);
    lemma_gfd(s, gn, gk);
}

// ---- the selected rows ----
#[verifier::opaque]
spec fn sel_rows(s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, sel: Seq<usize>, res: Seq<OutRow>, taken: Seq<bool>, q: i128) -> bool {
    &&& res.len() == sel.len()
    &&& taken.len() == gn.len()
    &&& gk.len() == gn.len()
    &&& gt.len() == gn.len()
    &&& forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> (sel[r] as int) < gn.len() && taken[sel[r] as int] && gt[sel[r] as int] > q
        && (gn[sel[r] as int] as int) < s.name__dict@.len() && res[r].name@ == s.name__dict@[gn[sel[r] as int] as int]@ && res[r].cik == gk[sel[r] as int] && res[r].total_value == gt[sel[r] as int]
    &&& forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() ==> sel[a] != sel[b]
    &&& forall|g: int| #![trigger taken[g]] 0 <= g < gn.len() && taken[g] ==> exists|r: int| #![trigger sel[r]] 0 <= r < sel.len() && sel[r] as int == g
    &&& forall|g: int, r: int| #![trigger taken[g], res[r]] 0 <= g < gn.len() && !taken[g] && gt[g] > q && 0 <= r < sel.len() ==> gt[g] <= res[r].total_value
    &&& forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> res[i].total_value >= res[i + 1].total_value
}

proof fn lemma_sel_init(s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, taken: Seq<bool>, q: i128)
    requires
        taken.len() == gn.len(),
        gk.len() == gn.len(),
        gt.len() == gn.len(),
        forall|g: int| #![trigger taken[g]] 0 <= g < taken.len() ==> !taken[g],
    ensures
        sel_rows(s, gn, gk, gt, Seq::<usize>::empty(), Seq::<OutRow>::empty(), taken, q),
{
    reveal(sel_rows);
}

proof fn lemma_sel_c1(s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, sel: Seq<usize>, res: Seq<OutRow>, taken: Seq<bool>, sel2: Seq<usize>, res2: Seq<OutRow>, taken2: Seq<bool>, q: i128, best: int, row: OutRow)
    requires
        sel_rows(s, gn, gk, gt, sel, res, taken, q),
        0 <= best < gn.len(),
        best <= usize::MAX as int,
        !taken[best],
        gt[best] > q,
        (gn[best] as int) < s.name__dict@.len(),
        row.name@ == s.name__dict@[gn[best] as int]@,
        row.cik == gk[best],
        row.total_value == gt[best],
        sel2 == sel.push(best as usize),
        res2 == res.push(row),
        taken2 == taken.update(best, true),
    ensures
        forall|r: int| #![trigger sel2[r]] 0 <= r < sel2.len() ==> (sel2[r] as int) < gn.len() && taken2[sel2[r] as int] && gt[sel2[r] as int] > q
            && (gn[sel2[r] as int] as int) < s.name__dict@.len() && res2[r].name@ == s.name__dict@[gn[sel2[r] as int] as int]@ && res2[r].cik == gk[sel2[r] as int] && res2[r].total_value == gt[sel2[r] as int],
{
    reveal(sel_rows);
    let len = sel.len() as int;
    assert forall|r: int| #![trigger sel2[r]] 0 <= r < sel2.len() implies (sel2[r] as int) < gn.len() && taken2[sel2[r] as int] && gt[sel2[r] as int] > q
        && (gn[sel2[r] as int] as int) < s.name__dict@.len() && res2[r].name@ == s.name__dict@[gn[sel2[r] as int] as int]@ && res2[r].cik == gk[sel2[r] as int] && res2[r].total_value == gt[sel2[r] as int] by {
        if r < len {
            assert(sel2[r] == sel[r]);
            assert(res2[r] == res[r]);
            assert(taken[sel[r] as int]);
            assert(sel[r] as int != best);
        } else {
            assert(r == len);
            assert(sel2[r] as int == best);
            assert(res2[r] == row);
        }
    };
}

proof fn lemma_sel_c2(sel: Seq<usize>, taken: Seq<bool>, sel2: Seq<usize>, best: int)
    requires
        forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() ==> taken[sel[r] as int],
        forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() ==> sel[a] != sel[b],
        0 <= best < taken.len(),
        best <= usize::MAX as int,
        !taken[best],
        sel2 == sel.push(best as usize),
    ensures
        forall|a: int, b: int| #![trigger sel2[a], sel2[b]] 0 <= a < b < sel2.len() ==> sel2[a] != sel2[b],
{
    let len = sel.len() as int;
    assert forall|a: int, b: int| #![trigger sel2[a], sel2[b]] 0 <= a < b < sel2.len() implies sel2[a] != sel2[b] by {
        if b == len {
            assert(sel2[b] as int == best);
            assert(sel2[a] == sel[a]);
            assert(taken[sel[a] as int]);
            assert(sel[a] as int != best);
        } else {
            assert(sel2[a] == sel[a]);
            assert(sel2[b] == sel[b]);
        }
    };
}

proof fn lemma_sel_c3(sel: Seq<usize>, taken: Seq<bool>, taken2: Seq<bool>, sel2: Seq<usize>, glen: int, best: int)
    requires
        forall|g: int| #![trigger taken[g]] 0 <= g < glen && taken[g] ==> exists|r: int| #![trigger sel[r]] 0 <= r < sel.len() && sel[r] as int == g,
        0 <= best < glen,
        glen == taken.len(),
        best <= usize::MAX as int,
        sel2 == sel.push(best as usize),
        taken2 == taken.update(best, true),
    ensures
        forall|g: int| #![trigger taken2[g]] 0 <= g < glen && taken2[g] ==> exists|r: int| #![trigger sel2[r]] 0 <= r < sel2.len() && sel2[r] as int == g,
{
    let len = sel.len() as int;
    assert forall|g: int| #![trigger taken2[g]] 0 <= g < glen && taken2[g] implies exists|r: int| #![trigger sel2[r]] 0 <= r < sel2.len() && sel2[r] as int == g by {
        if g == best {
            assert(sel2[len] as int == g);
        } else {
            assert(taken[g]);
            let r = choose|r: int| #![trigger sel[r]] 0 <= r < sel.len() && sel[r] as int == g;
            assert(sel2[r] == sel[r]);
        }
    };
}

proof fn lemma_sel_step(s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, sel: Seq<usize>, res: Seq<OutRow>, taken: Seq<bool>, sel2: Seq<usize>, res2: Seq<OutRow>, taken2: Seq<bool>, q: i128, best: int, row: OutRow)
    requires
        sel_rows(s, gn, gk, gt, sel, res, taken, q),
        0 <= best < gn.len(),
        best <= usize::MAX as int,
        !taken[best],
        gt[best] > q,
        forall|g: int| #![trigger taken[g]] 0 <= g < gn.len() && !taken[g] && gt[g] > q ==> gt[g] <= gt[best],
        (gn[best] as int) < s.name__dict@.len(),
        row.name@ == s.name__dict@[gn[best] as int]@,
        row.cik == gk[best],
        row.total_value == gt[best],
        sel2 == sel.push(best as usize),
        res2 == res.push(row),
        taken2 == taken.update(best, true),
    ensures
        sel_rows(s, gn, gk, gt, sel2, res2, taken2, q),
{
    lemma_sel_c1(s, gn, gk, gt, sel, res, taken, sel2, res2, taken2, q, best, row);
    let glen = gn.len() as int;
    reveal(sel_rows);
    assert forall|r: int| #![trigger sel[r]] 0 <= r < sel.len() implies taken[sel[r] as int] by {};
    assert forall|g: int, r: int| #![trigger taken[g], res[r]] 0 <= g < glen && !taken[g] && gt[g] > q && 0 <= r < sel.len() implies gt[g] <= res[r].total_value by { assert(res[r].total_value as int >= -170141183460469231731687303715884105728int); };
    assert forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() implies res[i].total_value >= res[i + 1].total_value by {};
    assert forall|g: int| #![trigger taken[g]] 0 <= g < glen && taken[g] implies exists|r: int| #![trigger sel[r]] 0 <= r < sel.len() && sel[r] as int == g by {};
    assert forall|a: int, b: int| #![trigger sel[a], sel[b]] 0 <= a < b < sel.len() implies sel[a] != sel[b] by {};
    lemma_sel_c2(sel, taken, sel2, best);
    lemma_sel_c3(sel, taken, taken2, sel2, glen, best);
    let len = sel.len() as int;
    assert forall|g: int, r: int| #![trigger taken2[g], res2[r]] 0 <= g < glen && !taken2[g] && gt[g] > q && 0 <= r < sel2.len() implies gt[g] <= res2[r].total_value by {
        assert(g != best);
        assert(!taken[g]);
        assert(gt[g] <= gt[best]);
        if r < len {
            assert(res2[r] == res[r]);
            assert(res[r].total_value as int >= -170141183460469231731687303715884105728int);
            assert(gt[g] <= res[r].total_value);
        } else {
            assert(res2[r] == row);
        }
    };
    assert forall|i: int| #![trigger res2[i]] 0 <= i && i + 1 < res2.len() implies res2[i].total_value >= res2[i + 1].total_value by {
        if i + 1 < len {
            assert(res2[i] == res[i]);
            assert(res2[i + 1] == res[i + 1]);
        } else {
            assert(i + 1 == len);
            assert(res2[i] == res[i]);
            assert(res2[i + 1] == row);
            assert(res[i].total_value as int >= -170141183460469231731687303715884105728int);
            assert(gt[best] > q);
            assert(res[i].total_value >= gt[best]);
        }
    };
}

proof fn lemma_fin_ok(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, gw: Seq<int>, sel: Seq<usize>, res: Seq<OutRow>, taken: Seq<bool>, q: i128)
    requires
        valid_cols_sub(s),
        sel_rows(s, gn, gk, gt, sel, res, taken, q),
        q as int == sq_1(n, s),
        gfa(n, s, gn, gk, gt),
        gwit(n, s, gn, gk, gw),
    ensures
        forall|r: int| #![trigger res[r]] 0 <= r < res.len() ==> out_row_ok(n, s, res[r]),
{
    reveal(sel_rows);
    reveal(gfa);
    reveal(gwit);
    assert forall|r: int| #![trigger res[r]] 0 <= r < res.len() implies out_row_ok(n, s, res[r]) by {
        assert(sel[r] as int >= 0);
        let g = sel[r] as int;
        assert(gn[g] as int >= 0);
        let jj = gw[g];
        lemma_active_hit(n, s, jj);
        let i0 = choose|i: int| #![trigger row_hit(n, s, i, jj)] row_hit(n, s, i, jj);
        let i1 = jj;
        assert(key_at(n, s, i0, i1) == (s.name__dict@[gn[g] as int]@, gk[g] as int));
        assert(row_hit(n, s, i0, i1) && key_at(n, s, i0, i1) == (res[r].name@, (res[r].cik as int)) && ((sum_total_value(n, s, 0, (res[r].name@, (res[r].cik as int))) > sq_1(n, s))) && (res[r].total_value as int) == sum_total_value(n, s, 0, (res[r].name@, (res[r].cik as int))));
    };
}

proof fn lemma_fin_sorted(s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, sel: Seq<usize>, res: Seq<OutRow>, taken: Seq<bool>, q: i128)
    requires
        sel_rows(s, gn, gk, gt, sel, res, taken, q),
    ensures
        forall|i: int| #![trigger res[i]] 0 <= i && i + 1 < res.len() ==> ((res[i].total_value) >= (res[i + 1].total_value)),
{
    reveal(sel_rows);
}

proof fn lemma_fin_distinct(s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, sel: Seq<usize>, res: Seq<OutRow>, taken: Seq<bool>, q: i128)
    requires
        sel_rows(s, gn, gk, gt, sel, res, taken, q),
        gfd(s, gn, gk),
    ensures
        forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() ==> (res[a].name@, (res[a].cik as int)) != (res[b].name@, (res[b].cik as int)),
{
    reveal(sel_rows);
    reveal(gfd);
    assert forall|a: int, b: int| #![trigger res[a], res[b]] 0 <= a < b < res.len() implies (res[a].name@, (res[a].cik as int)) != (res[b].name@, (res[b].cik as int)) by {
        assert(sel[a] as int >= 0);
        assert(sel[b] as int >= 0);
        assert(sel[a] != sel[b]);
        let ga = sel[a] as int;
        let gb = sel[b] as int;
        if ga < gb {
            assert(gn[ga] as int >= 0);
            assert(gn[gb] as int >= 0);
        } else {
            assert(gn[gb] as int >= 0);
            assert(gn[ga] as int >= 0);
        }
    };
}

proof fn lemma_fin_complete(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, sel: Seq<usize>, res: Seq<OutRow>, taken: Seq<bool>, q: i128)
    requires
        sel_rows(s, gn, gk, gt, sel, res, taken, q),
        q as int == sq_1(n, s),
        gfa(n, s, gn, gk, gt),
        gfc(n, s, gn, gk),
        forall|g: int| #![trigger taken[g]] 0 <= g < gn.len() && gt[g] > q ==> taken[g],
    ensures
        forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) && ((sum_total_value(n, s, 0, key_at(n, s, i0, i1)) > sq_1(n, s))) ==> exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(n, s, i0, i1) == (res[r].name@, (res[r].cik as int)),
{
    reveal(sel_rows);
    reveal(gfa);
    reveal(gfc);
    assert forall|i0: int, i1: int| #![trigger row_hit(n, s, i0, i1)] row_hit(n, s, i0, i1) && ((sum_total_value(n, s, 0, key_at(n, s, i0, i1)) > sq_1(n, s))) implies exists|r: int| #![trigger res[r]] 0 <= r < res.len() && key_at(n, s, i0, i1) == (res[r].name@, (res[r].cik as int)) by {
        let g = choose|g: int| #![trigger gn[g]] 0 <= g < gn.len() && gn[g] as int == s.name@[i1] as int && gk[g] as int == s.cik@[i1] as int;
        assert(gn[g] as int >= 0);
        assert(key_at(n, s, i0, i1) == (s.name__dict@[gn[g] as int]@, gk[g] as int));
        assert(gt[g] > q);
        assert(taken[g]);
        let r = choose|r: int| #![trigger sel[r]] 0 <= r < sel.len() && sel[r] as int == g;
        assert(res[r].name@ == s.name__dict@[gn[g] as int]@);
    };
}

proof fn lemma_fin_dominate(n: &Cols_num, s: &Cols_sub, gn: Seq<u16>, gk: Seq<i64>, gt: Seq<i128>, sel: Seq<usize>, res: Seq<OutRow>, taken: Seq<bool>, q: i128)
    requires
        sel_rows(s, gn, gk, gt, sel, res, taken, q),
        q as int == sq_1(n, s),
        gfa(n, s, gn, gk, gt),
        gfc(n, s, gn, gk),
    ensures
        forall|i0: int, i1: int, r: int| #![trigger row_hit(n, s, i0, i1), res[r]] row_hit(n, s, i0, i1) && ((sum_total_value(n, s, 0, key_at(n, s, i0, i1)) > sq_1(n, s))) && !(exists|r2: int| #![trigger res[r2]] 0 <= r2 < res.len() && key_at(n, s, i0, i1) == (res[r2].name@, (res[r2].cik as int))) && 0 <= r < res.len() ==> (((res[r].total_value as int)) >= (sum_total_value(n, s, 0, key_at(n, s, i0, i1)))),
{
    reveal(sel_rows);
    reveal(gfa);
    reveal(gfc);
    assert forall|i0: int, i1: int, r: int| #![trigger row_hit(n, s, i0, i1), res[r]] row_hit(n, s, i0, i1) && ((sum_total_value(n, s, 0, key_at(n, s, i0, i1)) > sq_1(n, s))) && !(exists|r2: int| #![trigger res[r2]] 0 <= r2 < res.len() && key_at(n, s, i0, i1) == (res[r2].name@, (res[r2].cik as int))) && 0 <= r < res.len() implies (((res[r].total_value as int)) >= (sum_total_value(n, s, 0, key_at(n, s, i0, i1)))) by {
        let g = choose|g: int| #![trigger gn[g]] 0 <= g < gn.len() && gn[g] as int == s.name@[i1] as int && gk[g] as int == s.cik@[i1] as int;
        assert(gn[g] as int >= 0);
        assert(key_at(n, s, i0, i1) == (s.name__dict@[gn[g] as int]@, gk[g] as int));
        assert(gt[g] > q);
        if taken[g] {
            let r2 = choose|r2: int| #![trigger sel[r2]] 0 <= r2 < sel.len() && sel[r2] as int == g;
            assert(res[r2].name@ == s.name__dict@[gn[g] as int]@);
            assert(key_at(n, s, i0, i1) == (res[r2].name@, (res[r2].cik as int)));
            assert(false);
        }
        assert(res[r].total_value as int >= -170141183460469231731687303715884105728int);
    };
}
// AGENT_HELPERS_END
// AGENT_EDIT_START
    // 1. the code of 'USD' in num's uom dictionary
    let usd_s: String = String::from_str("USD");
    let mut ucode: usize = 0;
    let mut ufound: bool = false;
    let mut kk: usize = 0;
    while kk < n.uom__dict.len()
        invariant
            kk <= n.uom__dict@.len(),
            usd_s@ == "USD"@,
            valid_cols_num(n),
            ufound ==> ucode < kk && n.uom__dict@[ucode as int]@ == "USD"@,
            !ufound ==> forall|m: int| 0 <= m < kk as int ==> n.uom__dict@[m]@ != "USD"@,
        decreases n.uom__dict@.len() - kk,
    {
        if !ufound && n.uom__dict[kk] == usd_s {
            ufound = true;
            ucode = kk;
        }
        kk += 1;
    }
    proof {
        assert forall|j: int| 0 <= j < n.n as int implies (usd(n, j) <==> (ufound && n.uom@[j] as int == ucode as int)) by {
            if ufound {
                if n.uom@[j] as int != ucode as int {
                    let a = if (n.uom@[j] as int) < (ucode as int) { n.uom@[j] as int } else { ucode as int };
                    let b = if (n.uom@[j] as int) < (ucode as int) { ucode as int } else { n.uom@[j] as int };
                    assert(n.uom__dict@[a]@ != n.uom__dict@[b]@);
                }
            }
        };
    }
    let scodes: usize = s.adsh__dict.len();
    let ncodes: usize = n.adsh__dict.len();
    // 2. smap: sub dictionary string -> sub code
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
    // 2b. tr[d]: the sub code of NUM dictionary entry d (scodes: none)
    let mut tr: Vec<usize> = Vec::new();
    let mut d: usize = 0;
    while d < ncodes
        invariant
            d <= ncodes,
            ncodes == n.adsh__dict@.len(),
            scodes == s.adsh__dict@.len(),
            valid_cols_sub(s),
            tr@.len() == d as int,
            forall|k: Seq<char>| #[trigger] smap@.contains_key(k) ==> (smap@[k] as int) < scodes as int && s.adsh__dict@[smap@[k] as int]@ == k,
            forall|t: int| 0 <= t < scodes as int ==> #[trigger] smap@.contains_key(s.adsh__dict@[t]@),
            forall|q: int| #![trigger tr@[q]] 0 <= q < d as int ==> (
                ((tr@[q] as int) < scodes as int && s.adsh__dict@[tr@[q] as int]@ == n.adsh__dict@[q]@)
                || (tr@[q] == scodes && forall|c2: int| 0 <= c2 < scodes as int ==> s.adsh__dict@[c2]@ != n.adsh__dict@[q]@)),
        decreases ncodes - d,
    {
        let found_code = smap.get(n.adsh__dict[d].as_str());
        match found_code {
            Some(v) => {
                tr.push(*v);
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
            }
        }
        d += 1;
    }
    // 3. class sums: sv[c] = sum of the values of the USD num rows whose adsh is sub dictionary entry c; hv[c]: there is such a row
    let mut sv: Vec<i128> = Vec::new();
    let mut hv: Vec<bool> = Vec::new();
    let mut z: usize = 0;
    while z < scodes
        invariant
            z <= scodes,
            scodes == s.adsh__dict@.len(),
            sv@.len() == z as int,
            hv@.len() == z as int,
            forall|c2: int| #![trigger sv@[c2]] 0 <= c2 < z as int ==> sv@[c2] == 0 && !hv@[c2],
        decreases scodes - z,
    {
        sv.push(0);
        hv.push(false);
        z += 1;
    }
    proof {
        lemma_sv_init(n, s, sv@, hv@);
    }
    let mut i: usize = n.n;
    while i > 0
        invariant
            i <= n.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            ncodes == n.adsh__dict@.len(),
            scodes == s.adsh__dict@.len(),
            tr@.len() == ncodes as int,
            sv@.len() == scodes as int,
            hv@.len() == scodes as int,
            svinv(n, s, sv@, hv@, i as int),
            forall|j: int| 0 <= j < n.n as int ==> (usd(n, j) <==> (ufound && n.uom@[j] as int == ucode as int)),
            forall|q: int| #![trigger tr@[q]] 0 <= q < ncodes as int ==> (
                ((tr@[q] as int) < scodes as int && s.adsh__dict@[tr@[q] as int]@ == n.adsh__dict@[q]@)
                || (tr@[q] == scodes && forall|c2: int| 0 <= c2 < scodes as int ==> s.adsh__dict@[c2]@ != n.adsh__dict@[q]@)),
        decreases i,
    {
        i -= 1;
        proof {
            assert(n.adsh@.len() == n.n as int);
            assert(n.uom@.len() == n.n as int);
            assert(n.value@.len() == n.n as int);
            assert(n.n as int <= ROW_CAP_num as int);
        }
        let u = n.uom[i] as usize;
        let hit = ufound && u == ucode;
        proof {
            assert(hit <==> usd(n, i as int));
        }
        if hit {
            let dcode = n.adsh[i] as usize;
            let v = n.value[i];
            proof {
                assert(dcode < ncodes);
                assert(nstr(n, i as int) == n.adsh__dict@[dcode as int]@);
                assert(v == n.value@[i as int]);
            }
            let t = tr[dcode];
            if t < scodes {
                let ghost old_sv = sv@;
                let ghost old_hv = hv@;
                let cur = sv[t];
                proof {
                    reveal(svinv);
                    assert(cur == sv@[t as int]);
                    assert(-(46116860184273879039999int * (n.n as int - i as int - 1)) <= sv@[t as int] as int <= 46116860184273879039999int * (n.n as int - i as int - 1));
                    assert(-46116860184273879039999int <= v as int <= 46116860184273879039999int);
                }
                sv.set(t, cur + v);
                hv.set(t, true);
                proof {
                    lemma_sv_match(n, s, old_sv, old_hv, sv@, hv@, i as int, t as int);
                }
            } else {
                proof {
                    assert(t == tr@[dcode as int]);
                    assert(t == scodes);
                    assert forall|c: int| 0 <= c < sv@.len() implies !(usd(n, i as int) && nstr(n, i as int) == s.adsh__dict@[c]@) by {
                        assert(s.adsh__dict@[c]@ != n.adsh__dict@[dcode as int]@);
                    };
                    lemma_sv_nomatch(n, s, sv@, hv@, i as int);
                }
            }
        } else {
            proof {
                assert forall|c: int| 0 <= c < sv@.len() implies !(usd(n, i as int) && nstr(n, i as int) == s.adsh__dict@[c]@) by {};
                lemma_sv_nomatch(n, s, sv@, hv@, i as int);
            }
        }
    }
    // 4. the groups (name code, cik) of the active filtered sub rows, with their totals
    let mut gn: Vec<u16> = Vec::new();
    let mut gk: Vec<i64> = Vec::new();
    let mut gt: Vec<i128> = Vec::new();
    let mut j: usize = s.n;
    let ghost mut gw: Seq<int> = Seq::empty();
    proof {
        lemma_g_init(n, s);
    }
    while j > 0
        invariant
            j <= s.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            scodes == s.adsh__dict@.len(),
            sv@.len() == scodes as int,
            hv@.len() == scodes as int,
            svinv(n, s, sv@, hv@, 0),
            gk@.len() == gn@.len(),
            gt@.len() == gn@.len(),
            gdist(gn@, gk@),
            gvals(n, s, gn@, gk@, gt@, j as int),
            gcov(n, s, gn@, gk@, j as int),
            gwit(n, s, gn@, gk@, gw),
        decreases j,
    {
        j -= 1;
        proof {
            assert(s.fy@.len() == s.n as int);
            assert(s.fy__valid@.len() == s.n as int);
            assert(s.adsh@.len() == s.n as int);
            assert(s.name@.len() == s.n as int);
            assert(s.cik@.len() == s.n as int);
            assert(s.n as int <= ROW_CAP_sub as int);
        }
        let fv = s.fy__valid[j];
        let fy = s.fy[j];
        let c = s.adsh[j] as usize;
        proof {
            assert((fv && fy == 2022) <==> fok(s, j as int));
            assert(c < scodes);
            assert(s.adsh@[j as int] as int == c as int);
            lemma_sv_at(n, s, sv@, hv@, c as int);
        }
        let act = fv && fy == 2022 && hv[c];
        proof {
            assert(act <==> (fok(s, j as int) && hx(n, s, s.adsh@[j as int] as int, 0)));
        }
        if act {
            let nm = s.name[j];
            let ck = s.cik[j];
            let sval = sv[c];
            proof {
                assert(sval as int == sd(n, s, s.adsh@[j as int] as int, 0));
                assert((s.name@[j as int] as int) < s.name__dict@.len());
                assert(s.name@[j as int] == nm);
                assert(s.cik@[j as int] == ck);
            }
            let ghost old_gn = gn@;
            let ghost old_gk = gk@;
            let ghost old_gt = gt@;
            let mut g: usize = 0;
            while g < gn.len() && !(gn[g] == nm && gk[g] == ck)
                invariant
                    g <= gn@.len(),
                    gk@.len() == gn@.len(),
                    gn@ == old_gn,
                    gk@ == old_gk,
                    forall|r: int| 0 <= r < g as int ==> !(old_gn[r] == nm && old_gk[r] == ck),
                decreases gn@.len() - g,
            {
                g += 1;
            }
            if g == gn.len() {
                gn.push(nm);
                gk.push(ck);
                gt.push(sval);
                proof {
                    let ghost old_gw = gw;
                    gw = old_gw.push(j as int);
                    lemma_g_push(n, s, old_gn, old_gk, old_gt, old_gw, gn@, gk@, gt@, gw, j as int, sval);
                }
            } else {
                let cur = gt[g];
                proof {
                    lemma_gvals_bound(n, s, old_gn, old_gk, old_gt, j as int + 1, g as int);
                    assert(99035203142830421991927790436352int * (s.n as int - j as int) <= 99035203142830421991927790436352int * 1048576int);
                }
                gt.set(g, cur + sval);
                proof {
                    lemma_g_update(n, s, old_gn, old_gk, old_gt, gt@, j as int, g as int, sval);
                }
            }
        } else {
            proof {
                lemma_g_skip_vals(n, s, gn@, gk@, gt@, j as int);
                lemma_g_skip_cov(n, s, gn@, gk@, j as int);
            }
        }
    }
    proof {
        assert(j == 0);
        lemma_g_final(n, s, gn@, gk@, gt@, gw);
    }
    // 5. the HAVING subquery: the distinct ciks of the active filtered sub rows with their totals, and the sum of those totals
    let mut dk: Vec<i64> = Vec::new();
    let mut ct: Vec<i128> = Vec::new();
    let mut acc: i128 = 0;
    let mut j: usize = s.n;
    proof {
        lemma_k_init(n, s);
    }
    while j > 0
        invariant
            j <= s.n,
            valid_cols_num(n),
            valid_cols_sub(s),
            scodes == s.adsh__dict@.len(),
            sv@.len() == scodes as int,
            hv@.len() == scodes as int,
            svinv(n, s, sv@, hv@, 0),
            ct@.len() == dk@.len(),
            kdist(dk@),
            kvals(n, s, dk@, ct@, j as int),
            kcov(n, s, dk@, j as int),
            kwit(n, s, dk@),
            kacc(ct@, acc, s, j as int),
        decreases j,
    {
        j -= 1;
        proof {
            assert(s.fy@.len() == s.n as int);
            assert(s.fy__valid@.len() == s.n as int);
            assert(s.adsh@.len() == s.n as int);
            assert(s.cik@.len() == s.n as int);
            assert(s.n as int <= ROW_CAP_sub as int);
        }
        let fv = s.fy__valid[j];
        let fy = s.fy[j];
        let c = s.adsh[j] as usize;
        proof {
            assert((fv && fy == 2022) <==> fok(s, j as int));
            assert(c < scodes);
            assert(s.adsh@[j as int] as int == c as int);
            lemma_sv_at(n, s, sv@, hv@, c as int);
        }
        let act = fv && fy == 2022 && hv[c];
        proof {
            assert(act <==> (fok(s, j as int) && hx(n, s, s.adsh@[j as int] as int, 0)));
        }
        if act {
            let ck = s.cik[j];
            let sval = sv[c];
            proof {
                assert(sval as int == sd(n, s, s.adsh@[j as int] as int, 0));
                assert(s.cik@[j as int] == ck);
                assert(99035203142830421991927790436352int * (s.n as int - j as int) <= 99035203142830421991927790436352int * 1048576int);
                assert(s.n as int - j as int >= 1);
            }
            let ghost old_dk = dk@;
            let ghost old_ct = ct@;
            let mut g: usize = 0;
            while g < dk.len() && dk[g] != ck
                invariant
                    g <= dk@.len(),
                    dk@ == old_dk,
                    forall|r: int| 0 <= r < g as int ==> old_dk[r] != ck,
                decreases dk@.len() - g,
            {
                g += 1;
            }
            if g == dk.len() {
                let old_acc = acc;
                dk.push(ck);
                ct.push(sval);
                acc = acc + sval;
                proof {
                    lemma_k_push(n, s, old_dk, old_ct, dk@, ct@, j as int, sval);
                    lemma_kacc_push(old_ct, old_acc, acc, sval, s, j as int);
                }
            } else {
                let cur = ct[g];
                let old_acc = acc;
                proof {
                    lemma_kvals_bound(n, s, old_dk, old_ct, j as int + 1, g as int);
                }
                ct.set(g, cur + sval);
                acc = acc + sval;
                proof {
                    lemma_k_update(n, s, old_dk, old_ct, ct@, j as int, g as int, sval);
                    lemma_kacc_set(old_ct, ct@, old_acc, acc, sval, g as int, s, j as int);
                }
            }
        } else {
            proof {
                lemma_k_skip_vals(n, s, dk@, ct@, j as int);
                lemma_k_skip_cov(n, s, dk@, j as int);
                lemma_kacc_skip(ct@, acc, s, j as int);
            }
        }
    }
    proof {
        lemma_k_final(n, s, dk@, ct@);
    }
    // 6. the HAVING threshold: sq_1 = floor(acc / count), in non-negative unsigned division
    let cnt: usize = dk.len();
    proof {
        assert(acc as int == sumseq(ct@, dk@.len() as int));
        assert(99035203142830421991927790436352int * (s.n as int - 0) <= 99035203142830421991927790436352int * 1048576int);
        assert(s.n as int <= ROW_CAP_sub as int);
    }
    let q: i128 = if cnt == 0 {
        0
    } else {
        let c128: u128 = cnt as u128;
        if acc >= 0 {
            let qq: u128 = (acc as u128) / c128;
            proof {
                assert(qq <= acc as u128) by (nonlinear_arith)
                    requires
                        qq == (acc as u128) / c128,
                        c128 >= 1,
                ;
            }
            qq as i128
        } else {
            let u: u128 = ((-acc) as u128) + c128 - 1;
            let qq: u128 = u / c128;
            proof {
                assert(qq <= u) by (nonlinear_arith)
                    requires
                        qq == u / c128,
                        c128 >= 1,
                ;
            }
            -(qq as i128)
        }
    };
    proof {
        if cnt == 0 {
            assert(sq_1_groups(n, s, 0) == 0);
            assert(sq_1(n, s) == 0);
        } else if acc >= 0 {
            assert(sq_1_groups(n, s, 0) == cnt as int);
            assert(sq_1_acc(n, s, 0) == acc as int);
        } else {
            let c = cnt as int;
            let u = -(acc as int) + c - 1;
            lemma_floor_neg(acc as int, c, u / c, u % c);
        }
        assert(q as int == sq_1(n, s));
    }
    // 7. keep the qualifying groups, the greatest totals first
    let gcount: usize = gn.len();
    let mut taken: Vec<bool> = Vec::new();
    let mut tz: usize = 0;
    while tz < gcount
        invariant
            tz <= gcount,
            taken@.len() == tz as int,
            forall|k: int| #![trigger taken@[k]] 0 <= k < tz as int ==> !taken@[k],
        decreases gcount - tz,
    {
        taken.push(false);
        tz += 1;
    }
    let mut sel: Vec<usize> = Vec::new();
    let mut res: Vec<OutRow> = Vec::new();
    let mut fin: bool = false;
    proof {
        lemma_sel_init(s, gn@, gk@, gt@, taken@, q);
        assert(gvals_names(s, gn@));
    }
    while !fin && res.len() < 100
        invariant
            valid_cols_sub(s),
            gcount == gn@.len(),
            gk@.len() == gn@.len(),
            gt@.len() == gn@.len(),
            gvals_names(s, gn@),
            gfa(n, s, gn@, gk@, gt@),
            gwit(n, s, gn@, gk@, gw),
            gfc(n, s, gn@, gk@),
            gfd(s, gn@, gk@),
            q as int == sq_1(n, s),
            taken@.len() == gcount as int,
            sel@.len() == res@.len(),
            res@.len() <= 100,
            sel_rows(s, gn@, gk@, gt@, sel@, res@, taken@, q),
            fin ==> forall|k: int| #![trigger taken@[k]] 0 <= k < gcount as int && gt@[k] > q ==> taken@[k],
        decreases (if fin { 0int } else { 100int - res@.len() as int }),
    {
        let mut best: usize = gcount;
        let mut g: usize = 0;
        while g < gcount
            invariant
                g <= gcount,
                taken@.len() == gcount as int,
                gt@.len() == gcount as int,
                best <= gcount,
                best < gcount ==> best < g && !taken@[best as int] && gt@[best as int] > q,
                best == gcount ==> forall|k: int| #![trigger taken@[k]] 0 <= k < g as int ==> taken@[k] || !(gt@[k] > q),
                best < gcount ==> forall|k: int| #![trigger taken@[k]] 0 <= k < g as int && !taken@[k] && gt@[k] > q ==> gt@[k] <= gt@[best as int],
            decreases gcount - g,
        {
            if !taken[g] && gt[g] > q {
                if best == gcount || gt[g] > gt[best] {
                    best = g;
                }
            }
            g += 1;
        }
        if best == gcount {
            fin = true;
        } else {
            let ghost old_sel = sel@;
            let ghost old_res = res@;
            let ghost old_taken = taken@;
            let nmcode = gn[best] as usize;
            proof {
                assert((gn@[best as int] as int) < s.name__dict@.len());
                assert(nmcode as int == gn@[best as int] as int);
            }
            let name = s.name__dict[nmcode].clone();
            let ghost nv = name@;
            let ck = gk[best];
            let tv = gt[best];
            res.push(OutRow { name: name, cik: ck, total_value: tv });
            sel.push(best);
            taken.set(best, true);
            proof {
                let row = res@[old_res.len() as int];
                assert(row.name@ == nv);
                lemma_sel_step(s, gn@, gk@, gt@, old_sel, old_res, old_taken, sel@, res@, taken@, q, best as int, row);
            }
        }
    }
    proof {
        lemma_fin_ok(n, s, gn@, gk@, gt@, gw, sel@, res@, taken@, q);
        lemma_fin_distinct(s, gn@, gk@, gt@, sel@, res@, taken@, q);
        lemma_fin_sorted(s, gn@, gk@, gt@, sel@, res@, taken@, q);
        lemma_fin_dominate(n, s, gn@, gk@, gt@, sel@, res@, taken@, q);
        if res@.len() != 100 {
            assert(fin);
            lemma_fin_complete(n, s, gn@, gk@, gt@, sel@, res@, taken@, q);
        }
    }
    res
// AGENT_EDIT_END
