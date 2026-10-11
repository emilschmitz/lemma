// Worked example (LEMMA_COLD_STREAM=1, LEMMA_NARROW_CELLS=1): the streaming chunk fold for COUNT(*) over an INTEGER column (i32 cells, DuckDB's stored width).
//   SELECT COUNT(*) AS n FROM num WHERE qtrs = 3
// No catalog cap is assumed or checked: the count of rows equal to 3 does not depend on how large the other cells are (a stronger theorem than the declarative one).
// COLD_FOLD_START
pub open spec fn hit(x: i32) -> int {
    if (x as int) == 3 { 1int } else { 0int }
}

pub open spec fn hit_f() -> spec_fn(i32) -> int {
    |x: i32| hit(x)
}

/// What the state is of the rows seen so far (in any order).
pub open spec fn st_rel(st: ColdState, seen: Seq<ColdRow>) -> bool {
    &&& st.cnt as int == sum_by(seen, hit_f())
    &&& st.rows as int == seen.len()
    &&& seen.len() <= ROW_CAP_num as int
}

proof fn lemma_hit_le(s: Seq<i32>)
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

pub fn cold_update(st: &mut ColdState, chunk: &[i32], Ghost(prev): Ghost<Seq<i32>>) -> (ok: bool)
    requires
        st_rel(*old(st), prev),
        prev.len() + chunk@.len() <= ROW_CAP_num as int,
    ensures
        ok,
        st_rel(*final(st), prev + chunk@),
{
    // One branch-free pass over the vector.
    let mut cnt: u64 = st.cnt;
    let mut j: usize = 0;
    proof {
        assert(prev + chunk@.take(0) =~= prev);
        lemma_hit_le(prev);
    }
    while j < chunk.len()
        invariant
            j <= chunk.len(),
            prev.len() + chunk@.len() <= ROW_CAP_num as int,
            cnt as int == sum_by(prev + chunk@.take(j as int), hit_f()),
            cnt as int <= prev.len() + j as int,
        decreases chunk.len() - j,
    {
        let x = chunk[j];
        proof {
            let s = prev + chunk@.take(j as int);
            assert(s.push(x) =~= prev + chunk@.take(j as int + 1));
            lemma_sum_by_push(s, x, hit_f());
        }
        cnt = cnt + (x == 3) as u64;
        j += 1;
    }
    proof {
        assert(chunk@.take(chunk@.len() as int) =~= chunk@);
    }
    st.cnt = cnt;
    st.rows = st.rows + chunk.len() as u64;
    true
}

pub fn cold_combine(t: &mut ColdState, s: &ColdState, Ghost(a): Ghost<Seq<i32>>, Ghost(b): Ghost<Seq<i32>>)
    requires
        st_rel(*old(t), a),
        st_rel(*s, b),
        a.len() + b.len() <= ROW_CAP_num as int,
    ensures
        st_rel(*final(t), a + b),
{
    proof {
        lemma_sum_by_concat(a, b, hit_f());
        lemma_hit_le(a);
        lemma_hit_le(b);
    }
    t.cnt = t.cnt + s.cnt;
    t.rows = t.rows + s.rows;
}

/// The spec's suffix count over the column equals the order-free sum.
proof fn lemma_suffix(num: &Cols_num, i: int)
    requires
        0 <= i <= num.n as int,
        num.qtrs@.len() == num.n as int,
    ensures
        count_n(num, i) == sum_by(num.qtrs@.skip(i), hit_f()),
    decreases num.n as int - i,
{
    let col = num.qtrs@;
    if i == num.n as int {
        assert(col.skip(i) =~= Seq::<i32>::empty());
        assert(count_n(num, i) == 0);
    } else {
        lemma_suffix(num, i + 1);
        reveal_with_fuel(count_n, 2);
        assert(col.skip(i) =~= seq![col[i]] + col.skip(i + 1));
        lemma_sum_by_concat(seq![col[i]], col.skip(i + 1), hit_f());
        assert(seq![col[i]] =~= Seq::<i32>::empty().push(col[i]));
        lemma_sum_by_push(Seq::<i32>::empty(), col[i], hit_f());
        assert(row_hit(num, i) <==> (col[i] as int) == 3);
    }
}
// COLD_FOLD_END
// AGENT_EDIT_START
    proof {
        let col = num.qtrs@;
        lemma_sum_by_perm(seen, col, hit_f());
        lemma_suffix(num, 0);
        assert(col.skip(0) =~= col);
    }
    let mut res: Vec<OutRow> = Vec::new();
    res.push(OutRow { n: st.cnt });
    res
// AGENT_EDIT_END
