// LEMMA_COLD_STREAM: the verified library of the streaming chunk fold. No `external_body`, no `assume`.
// A fold over the rows DuckDB delivers chunk by chunk, in ANY order, is correct because the aggregates handled here are sums of a per-row term, and a sum of
// per-row terms is invariant under permutation of the rows. `sum_by` is the sum; `lemma_sum_by_perm` is the permutation invariance (the one fact the unordered
// delivery needs); `lemma_sum_by_concat` / `lemma_sum_by_push` are how a chunk extends what was seen.
pub open spec fn sum_by<T>(s: Seq<T>, f: spec_fn(T) -> int) -> int
    decreases s.len(),
{
    if s.len() == 0 {
        0
    } else {
        sum_by(s.drop_last(), f) + f(s.last())
    }
}

pub proof fn lemma_sum_by_push<T>(s: Seq<T>, x: T, f: spec_fn(T) -> int)
    ensures
        sum_by(s.push(x), f) == sum_by(s, f) + f(x),
{
    assert(s.push(x).drop_last() =~= s);
    assert(s.push(x).last() == x);
}

pub proof fn lemma_sum_by_concat<T>(a: Seq<T>, b: Seq<T>, f: spec_fn(T) -> int)
    ensures
        sum_by(a + b, f) == sum_by(a, f) + sum_by(b, f),
    decreases b.len(),
{
    if b.len() == 0 {
        assert(a + b =~= a);
    } else {
        let b2 = b.drop_last();
        assert((a + b).drop_last() =~= a + b2);
        assert((a + b).last() == b.last());
        lemma_sum_by_concat(a, b2, f);
    }
}

pub proof fn lemma_sum_by_remove<T>(b: Seq<T>, j: int, f: spec_fn(T) -> int)
    requires
        0 <= j < b.len(),
    ensures
        sum_by(b, f) == sum_by(b.remove(j), f) + f(b[j]),
{
    let l = b.subrange(0, j);
    let r = b.subrange(j + 1, b.len() as int);
    assert(b =~= l + seq![b[j]] + r);
    assert(b.remove(j) =~= l + r);
    lemma_sum_by_concat(l + seq![b[j]], r, f);
    lemma_sum_by_concat(l, seq![b[j]], f);
    lemma_sum_by_concat(l, r, f);
    lemma_sum_by_push(Seq::<T>::empty(), b[j], f);
    assert(seq![b[j]] =~= Seq::<T>::empty().push(b[j]));
}

/// A sum of per-row terms does not depend on the order of the rows.
pub proof fn lemma_sum_by_perm<T>(a: Seq<T>, b: Seq<T>, f: spec_fn(T) -> int)
    requires
        a.to_multiset() =~= b.to_multiset(),
    ensures
        sum_by(a, f) == sum_by(b, f),
    decreases a.len(),
{
    broadcast use vstd::seq_lib::group_to_multiset_ensures;

    assert(a.to_multiset() == b.to_multiset());
    assert(a.to_multiset().len() == a.len());
    assert(b.to_multiset().len() == b.len());
    assert(a.len() == b.len());
    if a.len() > 0 {
        let x = a.last();
        let a2 = a.drop_last();
        assert(a =~= a2.push(x));
        assert(a.to_multiset().count(x) > 0);
        assert(b.to_multiset().count(x) > 0);
        assert(b.contains(x));
        let j = b.index_of(x);
        let b2 = b.remove(j);
        assert(a2.to_multiset() =~= a.to_multiset().remove(x));
        assert(b2.to_multiset() =~= b.to_multiset().remove(b[j]));
        lemma_sum_by_perm(a2, b2, f);
        lemma_sum_by_remove(b, j, f);
        lemma_sum_by_push(a2, x, f);
    }
}

/// |sum| <= len * b when every term is within b.
pub proof fn lemma_sum_by_bound<T>(s: Seq<T>, f: spec_fn(T) -> int, b: int)
    requires
        b >= 0,
        forall|i: int| 0 <= i < s.len() ==> -b <= #[trigger] f(s[i]) <= b,
    ensures
        -(s.len() as int * b) <= sum_by(s, f) <= s.len() as int * b,
    decreases s.len(),
{
    if s.len() > 0 {
        let s2 = s.drop_last();
        assert forall|i: int| 0 <= i < s2.len() implies -b <= #[trigger] f(s2[i]) <= b by {
            assert(s2[i] == s[i]);
        }
        lemma_sum_by_bound(s2, f, b);
        assert(s.len() as int * b == s2.len() as int * b + b) by (nonlinear_arith)
            requires s.len() == s2.len() + 1;
    }
}

/// A column as the spec sees it: its cells in row order. The declarative spec talks about `t.c@[i]`; the cold program never holds the column (DuckDB
/// delivers it in chunks), so the column exists only as a ghost sequence.
pub struct ColSeq<T> {
    pub s: Seq<T>,
}

impl<T> View for ColSeq<T> {
    type V = Seq<T>;

    open spec fn view(&self) -> Seq<T> {
        self.s
    }
}

/// The aggregate state: plain words (DuckDB gives the state memory at ANY alignment, so the glue stores four u64 words: the 128-bit sum as two halves, a
/// hit count and the number of rows seen).
pub struct ColdState {
    pub acc: i128,
    pub cnt: u64,
    pub rows: u64,
}
