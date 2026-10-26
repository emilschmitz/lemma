//! Proved generic library of the streaming executors (lemma.toml [run] stream, docs/STREAM.md). No `external_body`, no `assume`.
//!
//! A streaming executor folds the chunks DuckDB's parallel scan hands out, in ANY order and on any number of workers. Each worker's
//! state is the fold of its chunks; states are merged in any order. The answer is right because
//!   * the per-query aggregate `agg_plus` is a commutative monoid (host-proved per query: `lemma_agg_laws`),
//!   * a fold over a sequence is invariant under any reordering (`lemma_fold_perm`, `lemma_fold_bij`) and splits over a
//!     concatenation (`lemma_fold_concat`), and
//!   * chunks whose row ranges tile `[0, n)` (checked at run time by the host runtime) fold to the range fold of `[0, n)`
//!     (`lemma_tiles`), given the one-row step of the range fold (host-proved per query: `lemma_agg_step`).
//! `sum_by` / `lemma_sum_by_perm` are the integer special case (the archived `cold_lib.rs` of tag archive/pin-path-2026-10-07).
//!
//! `// STREAM_LIB_BEGIN` .. `// STREAM_LIB_END` is the slice the assembler pastes into every stream program.

use vstd::prelude::*;

verus! {

// STREAM_LIB_BEGIN

// ---- integer sums of per-row terms (from cold_lib) ------------------------------------------------------------------------------

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

// ---- folds over a commutative monoid ------------------------------------------------------------------------------------------

/// The left fold of `f` over `s` with `plus`, starting at `z`.
pub open spec fn fold_by<T, A>(s: Seq<T>, f: spec_fn(T) -> A, z: A, plus: spec_fn(A, A) -> A) -> A
    decreases s.len(),
{
    if s.len() == 0 {
        z
    } else {
        plus(fold_by(s.drop_last(), f, z, plus), f(s.last()))
    }
}

/// `z` is a two-sided identity of `plus`, and `plus` is associative.
pub open spec fn monoid_laws<A>(z: A, plus: spec_fn(A, A) -> A) -> bool {
    &&& forall|a: A| #[trigger] plus(z, a) == a
    &&& forall|a: A| #[trigger] plus(a, z) == a
    &&& forall|a: A, b: A, c: A|
        #![trigger plus(plus(a, b), c)]
        #![trigger plus(a, plus(b, c))]
        plus(plus(a, b), c) == plus(a, plus(b, c))
}

pub open spec fn comm_laws<A>(plus: spec_fn(A, A) -> A) -> bool {
    forall|a: A, b: A| #[trigger] plus(a, b) == plus(b, a)
}

pub proof fn lemma_fold_push<T, A>(s: Seq<T>, x: T, f: spec_fn(T) -> A, z: A, plus: spec_fn(A, A) -> A)
    ensures
        fold_by(s.push(x), f, z, plus) == plus(fold_by(s, f, z, plus), f(x)),
{
    assert(s.push(x).drop_last() =~= s);
    assert(s.push(x).last() == x);
}

pub proof fn lemma_fold_concat<T, A>(a: Seq<T>, b: Seq<T>, f: spec_fn(T) -> A, z: A, plus: spec_fn(A, A) -> A)
    requires
        monoid_laws(z, plus),
    ensures
        fold_by(a + b, f, z, plus) == plus(fold_by(a, f, z, plus), fold_by(b, f, z, plus)),
    decreases b.len(),
{
    if b.len() == 0 {
        assert(a + b =~= a);
    } else {
        let b2 = b.drop_last();
        assert((a + b).drop_last() =~= a + b2);
        assert((a + b).last() == b.last());
        lemma_fold_concat(a, b2, f, z, plus);
        let fa = fold_by(a, f, z, plus);
        let fb2 = fold_by(b2, f, z, plus);
        assert(plus(plus(fa, fb2), f(b.last())) == plus(fa, plus(fb2, f(b.last()))));
    }
}

pub proof fn lemma_fold_one<T, A>(x: T, f: spec_fn(T) -> A, z: A, plus: spec_fn(A, A) -> A)
    requires
        monoid_laws(z, plus),
    ensures
        fold_by(seq![x], f, z, plus) == f(x),
{
    assert(seq![x].drop_last() =~= Seq::<T>::empty());
    assert(seq![x].last() == x);
    assert(fold_by(Seq::<T>::empty(), f, z, plus) == z);
    assert(fold_by(seq![x], f, z, plus) == plus(fold_by(seq![x].drop_last(), f, z, plus), f(x)));
    assert(plus(z, f(x)) == f(x));
}

pub proof fn lemma_fold_remove<T, A>(b: Seq<T>, j: int, f: spec_fn(T) -> A, z: A, plus: spec_fn(A, A) -> A)
    requires
        monoid_laws(z, plus),
        comm_laws(plus),
        0 <= j < b.len(),
    ensures
        fold_by(b, f, z, plus) == plus(fold_by(b.remove(j), f, z, plus), f(b[j])),
{
    let l = b.subrange(0, j);
    let r = b.subrange(j + 1, b.len() as int);
    assert(b =~= l + seq![b[j]] + r);
    assert(b.remove(j) =~= l + r);
    lemma_fold_concat(l + seq![b[j]], r, f, z, plus);
    lemma_fold_concat(l, seq![b[j]], f, z, plus);
    lemma_fold_concat(l, r, f, z, plus);
    lemma_fold_one(b[j], f, z, plus);
    let fl = fold_by(l, f, z, plus);
    let fr = fold_by(r, f, z, plus);
    let x = f(b[j]);
    assert(plus(plus(fl, x), fr) == plus(fl, plus(x, fr)));
    assert(plus(x, fr) == plus(fr, x));
    assert(plus(fl, plus(fr, x)) == plus(plus(fl, fr), x));
}

/// A fold over a commutative monoid does not depend on the order of the elements (multiset form).
pub proof fn lemma_fold_perm<T, A>(a: Seq<T>, b: Seq<T>, f: spec_fn(T) -> A, z: A, plus: spec_fn(A, A) -> A)
    requires
        monoid_laws(z, plus),
        comm_laws(plus),
        a.to_multiset() =~= b.to_multiset(),
    ensures
        fold_by(a, f, z, plus) == fold_by(b, f, z, plus),
    decreases a.len(),
{
    broadcast use vstd::seq_lib::group_to_multiset_ensures;

    assert(a.to_multiset() == b.to_multiset());
    assert(a.to_multiset().len() == a.len());
    assert(b.to_multiset().len() == b.len());
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
        lemma_fold_perm(a2, b2, f, z, plus);
        lemma_fold_remove(b, j, f, z, plus);
        lemma_fold_push(a2, x, f, z, plus);
    }
}

/// The same fact for a reordering given as an explicit bijection: `a[i] == b[pa[i]]`, `pb` the inverse of `pa`
/// (the form the runtime's tiling check produces: `pa[i]` = the chunk index of segment `i`, `pb[j]` = the segment of chunk `j`).
pub proof fn lemma_fold_bij<T, A>(
    a: Seq<T>,
    b: Seq<T>,
    pa: Seq<int>,
    pb: Seq<int>,
    f: spec_fn(T) -> A,
    z: A,
    plus: spec_fn(A, A) -> A,
)
    requires
        monoid_laws(z, plus),
        comm_laws(plus),
        a.len() == b.len(),
        pa.len() == a.len(),
        pb.len() == b.len(),
        forall|i: int| #![trigger pa[i]] 0 <= i < a.len() ==> 0 <= pa[i] < b.len() && pb[pa[i]] == i && a[i] == b[pa[i]],
        forall|j: int| #![trigger pb[j]] 0 <= j < b.len() ==> 0 <= pb[j] < a.len() && pa[pb[j]] == j,
    ensures
        fold_by(a, f, z, plus) == fold_by(b, f, z, plus),
    decreases a.len(),
{
    if a.len() > 0 {
        let last = a.len() - 1;
        let j0 = pa[last];
        let a2 = a.drop_last();
        let b2 = b.remove(j0);
        let pa2 = Seq::new(last as nat, |i: int| if pa[i] < j0 { pa[i] } else { pa[i] - 1 });
        let pb2 = Seq::new(last as nat, |j: int| if j < j0 { pb[j] } else { pb[j + 1] });
        assert forall|i: int| #![trigger pa2[i]] 0 <= i < a2.len() implies 0 <= pa2[i] < b2.len() && pb2[pa2[i]] == i
            && a2[i] == b2[pa2[i]] by {
            assert(pb[pa[i]] == i);
            assert(pa[i] != j0);
        }
        assert forall|j: int| #![trigger pb2[j]] 0 <= j < b2.len() implies 0 <= pb2[j] < a2.len() && pa2[pb2[j]] == j by {
            let jj = if j < j0 { j } else { j + 1 };
            assert(pa[pb[jj]] == jj);
            assert(pb[jj] != last);
        }
        lemma_fold_bij(a2, b2, pa2, pb2, f, z, plus);
        lemma_fold_remove(b, j0, f, z, plus);
        assert(a =~= a2.push(a[last]));
        lemma_fold_push(a2, a[last], f, z, plus);
    }
}

// ---- MIN / MAX: Option<int> under omin / omax (None = no row) --------------------------------------------------------------------

pub open spec fn omin(a: Option<int>, b: Option<int>) -> Option<int> {
    match (a, b) {
        (None, _) => b,
        (_, None) => a,
        (Some(x), Some(y)) => Some(if x <= y { x } else { y }),
    }
}

pub open spec fn omax(a: Option<int>, b: Option<int>) -> Option<int> {
    match (a, b) {
        (None, _) => b,
        (_, None) => a,
        (Some(x), Some(y)) => Some(if x >= y { x } else { y }),
    }
}

/// The monoid laws of omin at given points (no quantifier: a quantified form loops in Z3 next to the aggregate's own laws).
pub proof fn lemma_omin_at(a: Option<int>, b: Option<int>, c: Option<int>)
    ensures
        omin(None, a) == a,
        omin(a, None) == a,
        omin(a, b) == omin(b, a),
        omin(omin(a, b), c) == omin(a, omin(b, c)),
{
}

pub proof fn lemma_omax_at(a: Option<int>, b: Option<int>, c: Option<int>)
    ensures
        omax(None, a) == a,
        omax(a, None) == a,
        omax(a, b) == omax(b, a),
        omax(omax(a, b), c) == omax(a, omax(b, c)),
{
}

// ---- range folds and the tiling lemma ------------------------------------------------------------------------------------------

/// `rng(lo, hi)` is the fold of `row` over `[lo, hi)`: the empty range `[lo, lo)` gives `z`, and a range grows by one row at its end.
pub open spec fn rng_step_ok<A>(rng: spec_fn(int, int) -> A, row: spec_fn(int) -> A, z: A, plus: spec_fn(A, A) -> A) -> bool {
    &&& forall|lo: int| 0 <= lo ==> #[trigger] rng(lo, lo) == z
    &&& forall|lo: int, hi: int| 0 <= lo < hi ==> #[trigger] rng(lo, hi) == plus(rng(lo, hi - 1), row(hi - 1))
}

/// A range fold splits at any point.
pub proof fn lemma_rng_split<A>(
    rng: spec_fn(int, int) -> A,
    row: spec_fn(int) -> A,
    z: A,
    plus: spec_fn(A, A) -> A,
    lo: int,
    mid: int,
    hi: int,
)
    requires
        monoid_laws(z, plus),
        rng_step_ok(rng, row, z, plus),
        0 <= lo <= mid <= hi,
    ensures
        rng(lo, hi) == plus(rng(lo, mid), rng(mid, hi)),
    decreases hi - mid,
{
    if hi > mid {
        lemma_rng_split(rng, row, z, plus, lo, mid, hi - 1);
        assert(rng(lo, hi) == plus(rng(lo, hi - 1), row(hi - 1)));
        assert(rng(mid, hi) == plus(rng(mid, hi - 1), row(hi - 1)));
        assert(plus(plus(rng(lo, mid), rng(mid, hi - 1)), row(hi - 1)) == plus(rng(lo, mid), plus(rng(mid, hi - 1), row(hi - 1))));
    } else {
        assert(rng(mid, hi) == z);
    }
}

/// One chunk's segment: `j` is its index in the order chunks were handed out, `[off, off + len)` its rows.
#[derive(Clone, Copy)]
pub struct Seg {
    pub j: usize,
    pub off: usize,
    pub len: usize,
}

pub open spec fn seg_end(s: Seg) -> int {
    s.off + s.len
}

/// The segments, in this order, are contiguous and cover exactly `[0, n)`.
pub open spec fn tiles_ok(t: Seq<Seg>, n: int) -> bool {
    &&& t.len() == 0 ==> n == 0
    &&& t.len() > 0 ==> t[0].off == 0 && seg_end(t.last()) == n
    &&& forall|j: int| #![trigger t[j]] 0 <= j && j + 1 < t.len() ==> t[j + 1].off == seg_end(t[j])
}

/// Segments that tile `[0, n)` fold to the range fold of `[0, n)`.
pub proof fn lemma_tiles<A>(
    t: Seq<Seg>,
    n: int,
    f: spec_fn(Seg) -> A,
    rng: spec_fn(int, int) -> A,
    row: spec_fn(int) -> A,
    z: A,
    plus: spec_fn(A, A) -> A,
)
    requires
        monoid_laws(z, plus),
        rng_step_ok(rng, row, z, plus),
        tiles_ok(t, n),
        forall|s: Seg| #[trigger] f(s) == rng(s.off as int, seg_end(s)),
    ensures
        fold_by(t, f, z, plus) == rng(0, n),
    decreases t.len(),
{
    if t.len() == 0 {
        assert(rng(0, 0) == z);
    } else {
        let t2 = t.drop_last();
        let last = t.last();
        let n2 = last.off as int;
        if t2.len() > 0 {
            assert(t[t.len() - 1].off == seg_end(t[t.len() - 2]));
            assert(t2.last() == t[t.len() - 2]);
        }
        assert forall|j: int| #![trigger t2[j]] 0 <= j && j + 1 < t2.len() implies t2[j + 1].off == seg_end(t2[j]) by {
            assert(t[j + 1].off == seg_end(t[j]));
        }
        assert(tiles_ok(t2, n2));
        lemma_tiles(t2, n2, f, rng, row, z, plus);
        lemma_rng_split(rng, row, z, plus, 0, n2, n);
    }
}

// STREAM_LIB_END

} // verus!

fn main() {}
