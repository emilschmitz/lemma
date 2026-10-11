// Worked example (LEMMA_COLD_STREAM=1): the streaming chunk fold for an ungrouped SUM over a DECIMAL(38,4) column (i128 cells) with a filter.
//   SELECT SUM(value) AS total FROM num WHERE value > 5000
// DuckDB scans the column in parallel and calls `cold_update` once per vector, `cold_combine` across threads, `cold_finish` once. Nothing here depends on the
// order or the grouping of the chunks: the state is `sum_by` of a per-row term over the multiset of rows seen (cold_lib.rs: lemma_sum_by_perm).
// COLD_FOLD_START
pub open spec fn cap_ok(x: i128) -> bool {
    -46116860184273879039999 <= x as int <= 46116860184273879039999
}

pub open spec fn term(x: i128) -> int {
    if (x as int) > 50000000 { x as int } else { 0int }
}

pub open spec fn hit(x: i128) -> int {
    if (x as int) > 50000000 { 1int } else { 0int }
}

pub open spec fn term_f() -> spec_fn(i128) -> int {
    |x: i128| term(x)
}

pub open spec fn hit_f() -> spec_fn(i128) -> int {
    |x: i128| hit(x)
}

pub open spec fn all_cap(s: Seq<i128>) -> bool {
    forall|i: int| 0 <= i < s.len() ==> cap_ok(#[trigger] s[i])
}

/// What the state is of the rows seen so far (in any order).
pub open spec fn st_rel(st: ColdState, seen: Seq<ColdRow>) -> bool {
    &&& st.acc as int == sum_by(seen, term_f())
    &&& st.cnt as int == sum_by(seen, hit_f())
    &&& st.rows as int == seen.len()
    &&& all_cap(seen)
    &&& seen.len() <= ROW_CAP_num as int
}

proof fn lemma_term_bounds(s: Seq<i128>)
    requires
        all_cap(s),
    ensures
        forall|i: int| 0 <= i < s.len() ==> -46116860184273879039999int <= #[trigger] term_f()(s[i]) <= 46116860184273879039999int,
        forall|i: int| 0 <= i < s.len() ==> 0 <= #[trigger] hit_f()(s[i]) <= 1,
{
}

proof fn lemma_hit_le(s: Seq<i128>)
    ensures
        0 <= sum_by(s, hit_f()) <= s.len(),
    decreases s.len(),
{
    if s.len() > 0 {
        lemma_hit_le(s.drop_last());
    }
}

proof fn lemma_hit_nonneg(s: Seq<i128>)
    ensures
        sum_by(s, hit_f()) >= 0,
{
    lemma_hit_le(s);
}

pub fn cold_init() -> (st: ColdState)
    ensures
        st_rel(st, Seq::empty()),
{
    ColdState { acc: 0, cnt: 0, rows: 0 }
}

/// One vector of the column. `false`: a cell is outside the catalog cap (the state is unchanged and the caller aborts the query).
pub fn cold_update(st: &mut ColdState, chunk: &[i128], Ghost(prev): Ghost<Seq<i128>>) -> (ok: bool)
    requires
        st_rel(*old(st), prev),
        prev.len() + chunk@.len() <= ROW_CAP_num as int,
    ensures
        ok ==> st_rel(*final(st), prev + chunk@),
        !ok ==> *final(st) == *old(st),
{
    let mut i: usize = 0;
    while i < chunk.len()
        invariant
            i <= chunk.len(),
            forall|k: int| 0 <= k < i as int ==> cap_ok(chunk@[k]),
        decreases chunk.len() - i,
    {
        let x = chunk[i];
        if x < -46116860184273879039999i128 || x > 46116860184273879039999i128 {
            return false;
        }
        i += 1;
    }
    let mut acc: i128 = st.acc;
    let mut cnt: u64 = st.cnt;
    let mut j: usize = 0;
    proof {
        assert(prev + chunk@.take(0) =~= prev);
        lemma_hit_le(prev);
    }
    while j < chunk.len()
        invariant
            j <= chunk.len(),
            all_cap(chunk@),
            all_cap(prev),
            prev.len() + chunk@.len() <= ROW_CAP_num as int,
            acc as int == sum_by(prev + chunk@.take(j as int), term_f()),
            cnt as int == sum_by(prev + chunk@.take(j as int), hit_f()),
            cnt as int <= prev.len() + j as int,
        decreases chunk.len() - j,
    {
        let x = chunk[j];
        proof {
            let s = prev + chunk@.take(j as int);
            assert(s.push(x) =~= prev + chunk@.take(j as int + 1));
            lemma_sum_by_push(s, x, term_f());
            lemma_sum_by_push(s, x, hit_f());
            assert(all_cap(s)) by {
                assert forall|k: int| 0 <= k < s.len() implies cap_ok(#[trigger] s[k]) by {
                    if k < prev.len() {
                        assert(s[k] == prev[k]);
                    } else {
                        assert(s[k] == chunk@[k - prev.len()]);
                    }
                }
            }
            lemma_term_bounds(s);
            lemma_sum_by_bound(s, term_f(), 46116860184273879039999int);
            assert(s.len() as int * 46116860184273879039999int <= 2147483648int * 46116860184273879039999int) by (nonlinear_arith)
                requires s.len() <= 2147483648;
        }
        if x > 50000000 {
            acc = acc + x;
            cnt = cnt + 1;
        }
        j += 1;
    }
    proof {
        assert(chunk@.take(chunk@.len() as int) =~= chunk@);
        assert forall|k: int| 0 <= k < (prev + chunk@).len() implies cap_ok(#[trigger] (prev + chunk@)[k]) by {
            if k < prev.len() {
                assert((prev + chunk@)[k] == prev[k]);
            } else {
                assert((prev + chunk@)[k] == chunk@[k - prev.len()]);
            }
        }
    }
    st.acc = acc;
    st.cnt = cnt;
    st.rows = st.rows + chunk.len() as u64;
    true
}

/// Merge two partial states (any two thread-local states DuckDB combines).
pub fn cold_combine(t: &mut ColdState, s: &ColdState, Ghost(a): Ghost<Seq<i128>>, Ghost(b): Ghost<Seq<i128>>)
    requires
        st_rel(*old(t), a),
        st_rel(*s, b),
        a.len() + b.len() <= ROW_CAP_num as int,
    ensures
        st_rel(*final(t), a + b),
{
    proof {
        lemma_sum_by_concat(a, b, term_f());
        lemma_sum_by_concat(a, b, hit_f());
        lemma_hit_le(a);
        lemma_hit_le(b);
        lemma_term_bounds(a);
        lemma_term_bounds(b);
        lemma_sum_by_bound(a, term_f(), 46116860184273879039999int);
        lemma_sum_by_bound(b, term_f(), 46116860184273879039999int);
        assert(all_cap(a + b)) by {
            assert forall|k: int| 0 <= k < (a + b).len() implies cap_ok(#[trigger] (a + b)[k]) by {
                if k < a.len() {
                    assert((a + b)[k] == a[k]);
                } else {
                    assert((a + b)[k] == b[k - a.len()]);
                }
            }
        }
        assert(a.len() as int * 46116860184273879039999int <= 2147483648int * 46116860184273879039999int) by (nonlinear_arith)
            requires a.len() <= 2147483648;
        assert(b.len() as int * 46116860184273879039999int <= 2147483648int * 46116860184273879039999int) by (nonlinear_arith)
            requires b.len() <= 2147483648;
    }
    t.acc = t.acc + s.acc;
    t.cnt = t.cnt + s.cnt;
    t.rows = t.rows + s.rows;
}

/// The spec's suffix fold over the column equals the order-free sums.
proof fn lemma_suffix(num: &Cols_num, i: int)
    requires
        0 <= i <= num.n as int,
        num.value@.len() == num.n as int,
    ensures
        sum_total(num, i) == sum_by(num.value@.skip(i), term_f()),
        (exists|i0: int| #![trigger row_hit(num, i0)] i <= i0 < num.n as int && row_hit(num, i0)) <==> sum_by(num.value@.skip(i), hit_f()) > 0,
    decreases num.n as int - i,
{
    let col = num.value@;
    if i == num.n as int {
        assert(col.skip(i) =~= Seq::<i128>::empty());
        assert(sum_total(num, i) == 0);
    } else {
        lemma_suffix(num, i + 1);
        reveal_with_fuel(sum_total, 2);
        assert(col.skip(i) =~= seq![col[i]] + col.skip(i + 1));
        lemma_sum_by_concat(seq![col[i]], col.skip(i + 1), term_f());
        lemma_sum_by_concat(seq![col[i]], col.skip(i + 1), hit_f());
        assert(seq![col[i]] =~= Seq::<i128>::empty().push(col[i]));
        lemma_sum_by_push(Seq::<i128>::empty(), col[i], term_f());
        lemma_sum_by_push(Seq::<i128>::empty(), col[i], hit_f());
        lemma_hit_nonneg(col.skip(i + 1));
        assert(row_hit(num, i) <==> (col[i] as int) > 50000000);
        assert(sum_total_val(num, i) == col[i] as int);
    }
}
// COLD_FOLD_END
// AGENT_EDIT_START
    proof {
        let col = num.value@;
        lemma_sum_by_perm(seen, col, term_f());
        lemma_sum_by_perm(seen, col, hit_f());
        lemma_suffix(num, 0);
        assert(col.skip(0) =~= col);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { total: if st.cnt > 0 { Some(st.acc) } else { None } });
    proof {
        assert(res@[0].total is Some <==> st.cnt > 0);
    }
    res
// AGENT_EDIT_END
