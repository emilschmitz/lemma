// Worked example (LEMMA_COLD_STREAM=1): the streaming chunk fold over TWO columns (DECIMAL(15,2) as i64 cells), TPC-H lineitem.
//   SELECT SUM(l_extendedprice) AS s FROM lineitem WHERE l_quantity < 24
// A row is the pair (price, quantity); the two vectors of one update call are row-aligned (ZC-2 item 2).
// NO catalog cap is assumed or checked: an i64 cell is at most 2^63 in magnitude, so a sum of fewer than 2^64 of them fits an i128 whatever the data is. The
// theorem is therefore stronger than the declarative one (which also required |cell| < 10^15); the cap check (a second compare per cell) is not needed.
// COLD_FOLD_START
pub open spec fn term(x: ColdRow) -> int {
    if (x.1 as int) < 2400 { x.0 as int } else { 0int }
}

pub open spec fn hit(x: ColdRow) -> int {
    if (x.1 as int) < 2400 { 1int } else { 0int }
}

pub open spec fn term_f() -> spec_fn(ColdRow) -> int {
    |x: ColdRow| term(x)
}

pub open spec fn hit_f() -> spec_fn(ColdRow) -> int {
    |x: ColdRow| hit(x)
}

pub open spec fn chunk_rows(c0: Seq<i64>, c1: Seq<i64>) -> Seq<ColdRow> {
    Seq::new(c0.len(), |i: int| (c0[i], c1[i]))
}

pub open spec fn st_rel(st: ColdState, seen: Seq<ColdRow>) -> bool {
    &&& st.acc as int == sum_by(seen, term_f())
    &&& st.cnt as int == sum_by(seen, hit_f())
    &&& st.rows as int == seen.len()
    &&& seen.len() <= ROW_CAP_lineitem as int
}

proof fn lemma_term_any(s: Seq<ColdRow>)
    ensures
        forall|i: int| 0 <= i < s.len() ==> -9223372036854775808int <= #[trigger] term_f()(s[i]) <= 9223372036854775808int,
{
}

/// |sum of terms| <= len * 2^63, and with len <= 2^62 that fits an i128 (a row cap above 2^62 fails to verify, loudly).
proof fn lemma_acc_fits(s: Seq<ColdRow>)
    requires
        s.len() <= ROW_CAP_lineitem as int,
    ensures
        -170141183460469231731687303715884105728int <= sum_by(s, term_f()) - 9223372036854775808int,
        sum_by(s, term_f()) + 9223372036854775808int <= 170141183460469231731687303715884105727int,
{
    lemma_term_any(s);
    lemma_sum_by_bound(s, term_f(), 9223372036854775808int);
    assert(ROW_CAP_lineitem as int <= 4611686018427387904int);
    assert((s.len() as int + 1) * 9223372036854775808int <= 9223372036854775808int * 9223372036854775808int) by (nonlinear_arith)
        requires s.len() as int + 1 <= 9223372036854775808int;
}

proof fn lemma_hit_le(s: Seq<ColdRow>)
    ensures
        0 <= sum_by(s, hit_f()) <= s.len(),
    decreases s.len(),
{
    if s.len() > 0 {
        lemma_hit_le(s.drop_last());
    }
}

pub fn cold_init() -> (st: ColdState)
    ensures
        st_rel(st, Seq::empty()),
{
    ColdState { acc: 0, cnt: 0, rows: 0 }
}

proof fn lemma_mask(p: i64, m: i64)
    ensures
        m == -1i64 ==> (p & m) == p,
        m == 0i64 ==> (p & m) == 0i64,
{
    assert((m == -1i64) ==> (p & m) == p) by (bit_vector);
    assert((m == 0i64) ==> (p & m) == 0i64) by (bit_vector);
}

pub fn cold_update(st: &mut ColdState, c0: &[i64], c1: &[i64], Ghost(prev): Ghost<Seq<ColdRow>>) -> (ok: bool)
    requires
        st_rel(*old(st), prev),
        c0@.len() == c1@.len(),
        prev.len() + c0@.len() <= ROW_CAP_lineitem as int,
    ensures
        ok,
        st_rel(*final(st), prev + chunk_rows(c0@, c1@)),
{
    // One branch-free pass: masked sum and hit count. A data-dependent branch on random data costs 2x (measured).
    // (the equal-length test is dead by the precondition; it tells the compiler the two slices are equally long, so the loop has no bounds checks)
    if c0.len() != c1.len() {
        return false;
    }
    let ghost chunk = chunk_rows(c0@, c1@);
    let mut acc: i128 = st.acc;
    let mut cnt: u64 = st.cnt;
    let mut j: usize = 0;
    proof {
        assert(prev + chunk.take(0) =~= prev);
        lemma_hit_le(prev);
        assert(chunk.len() == c0@.len());
    }
    while j < c0.len()
        invariant
            j <= c0.len(),
            c0@.len() == c1@.len(),
            chunk == chunk_rows(c0@, c1@),
            chunk.len() == c0@.len(),
            prev.len() + chunk.len() <= ROW_CAP_lineitem as int,
            acc as int == sum_by(prev + chunk.take(j as int), term_f()),
            cnt as int == sum_by(prev + chunk.take(j as int), hit_f()),
            cnt as int <= prev.len() + j as int,
        decreases c0.len() - j,
    {
        let p = c0[j];
        let q = c1[j];
        let hit = q < 2400;
        let m: i64 = -(hit as i64);
        let v: i64 = p & m;
        proof {
            lemma_mask(p, m);
            let s = prev + chunk.take(j as int);
            assert(chunk[j as int] == (p, q));
            assert(s.push((p, q)) =~= prev + chunk.take(j as int + 1));
            lemma_sum_by_push(s, (p, q), term_f());
            lemma_sum_by_push(s, (p, q), hit_f());
            lemma_acc_fits(s);
        }
        acc = acc + v as i128;
        cnt = cnt + hit as u64;
        j += 1;
    }
    proof {
        assert(chunk.take(chunk.len() as int) =~= chunk);
    }
    st.acc = acc;
    st.cnt = cnt;
    st.rows = st.rows + c0.len() as u64;
    true
}

pub fn cold_combine(t: &mut ColdState, s: &ColdState, Ghost(a): Ghost<Seq<ColdRow>>, Ghost(b): Ghost<Seq<ColdRow>>)
    requires
        st_rel(*old(t), a),
        st_rel(*s, b),
        a.len() + b.len() <= ROW_CAP_lineitem as int,
    ensures
        st_rel(*final(t), a + b),
{
    proof {
        lemma_sum_by_concat(a, b, term_f());
        lemma_sum_by_concat(a, b, hit_f());
        lemma_hit_le(a);
        lemma_hit_le(b);
        lemma_term_any(a);
        lemma_term_any(b);
        lemma_sum_by_bound(a, term_f(), 9223372036854775808int);
        lemma_sum_by_bound(b, term_f(), 9223372036854775808int);
        assert(ROW_CAP_lineitem as int <= 4611686018427387904int);
        assert((a.len() as int + b.len() as int) * 9223372036854775808int <= 9223372036854775808int * 9223372036854775808int) by (nonlinear_arith)
            requires a.len() as int + b.len() as int <= 9223372036854775808int;
        assert(a.len() as int * 9223372036854775808int + b.len() as int * 9223372036854775808int == (a.len() as int + b.len() as int) * 9223372036854775808int) by (nonlinear_arith);
    }
    t.acc = t.acc + s.acc;
    t.cnt = t.cnt + s.cnt;
    t.rows = t.rows + s.rows;
}

/// The spec's suffix fold over the two columns equals the order-free sums.
proof fn lemma_suffix(num: &Cols_lineitem, i: int)
    requires
        0 <= i <= num.n as int,
        num.l_extendedprice@.len() == num.n as int,
        num.l_quantity@.len() == num.n as int,
    ensures
        sum_s(num, i) == sum_by(cold_rows(num).skip(i), term_f()),
        (exists|i0: int| #![trigger row_hit(num, i0)] i <= i0 < num.n as int && row_hit(num, i0)) <==> sum_by(cold_rows(num).skip(i), hit_f()) > 0,
    decreases num.n as int - i,
{
    let col = cold_rows(num);
    if i == num.n as int {
        assert(col.skip(i) =~= Seq::<ColdRow>::empty());
        assert(sum_s(num, i) == 0);
    } else {
        lemma_suffix(num, i + 1);
        reveal_with_fuel(sum_s, 2);
        assert(col.len() == num.n as int);
        assert(col.skip(i) =~= seq![col[i]] + col.skip(i + 1));
        lemma_sum_by_concat(seq![col[i]], col.skip(i + 1), term_f());
        lemma_sum_by_concat(seq![col[i]], col.skip(i + 1), hit_f());
        assert(seq![col[i]] =~= Seq::<ColdRow>::empty().push(col[i]));
        lemma_sum_by_push(Seq::<ColdRow>::empty(), col[i], term_f());
        lemma_sum_by_push(Seq::<ColdRow>::empty(), col[i], hit_f());
        lemma_hit_le(col.skip(i + 1));
        assert(col[i] == (num.l_extendedprice@[i], num.l_quantity@[i]));
        assert(row_hit(num, i) <==> (num.l_quantity@[i] as int) < 2400);
        assert(sum_s_val(num, i) == num.l_extendedprice@[i] as int);
    }
}
// COLD_FOLD_END
// AGENT_EDIT_START
    proof {
        let col = cold_rows(lineitem);
        lemma_sum_by_perm(seen, col, term_f());
        lemma_sum_by_perm(seen, col, hit_f());
        lemma_suffix(lineitem, 0);
        assert(col.skip(0) =~= col);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { s: if st.cnt > 0 { Some(st.acc) } else { None } });
    proof {
        assert(res@[0].s is Some <==> st.cnt > 0);
    }
    res
// AGENT_EDIT_END
