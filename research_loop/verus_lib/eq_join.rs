//! Proved equijoin index. Rocketship: the body is verified, not `external_body`.
//!
//! One idea: the bucket for a key is the increasing row ids where the column
//! equals that key. `equijoin_pairs_*` walks outer rows and those buckets, so
//! the pair list is the nested-loop match list (same order as `rem_join`).
//!
//! vstd `StringHashMap` and `std::collections::HashMap` supply the hash-table
//! view. This file does not assume the join result.
//!
//! `// EQ_JOIN_PROVED_BEGIN` .. `// EQ_JOIN_PROVED_END` is the slice assembled
//! into join queries. The oracle below that marker is tests only.

use std::collections::HashMap;
use std::hash::RandomState;
use vstd::prelude::*;

verus! {

// EQ_JOIN_PROVED_BEGIN

use core::hash::Hash;
use vstd::hash_map::StringHashMap;
use vstd::std_specs::hash::{
    axiom_contains_deref_key, axiom_maps_deref_key_to_value, axiom_random_state_builds_valid_hashers,
    axiom_u32_obeys_hash_table_key_model, axiom_u64_obeys_hash_table_key_model,
    builds_valid_hashers, obeys_key_model,
};
use vstd::map::{axiom_map_insert_different, lemma_map_insert_domain, lemma_map_insert_same};
use vstd::seq::{
    lemma_seq_push_index_different, lemma_seq_push_index_same, lemma_seq_push_len,
    lemma_seq_update_different, lemma_seq_update_len,
};
use vstd::set::{lemma_set_insert_different, lemma_set_insert_same};
use vstd::string::{StringSliceAdditionalSpecFns, is_ascii};

proof fn lemma_ascii_chars_eq_from_u8(c1: char, c2: char)
    requires
        '\0' <= c1 <= '\u{7f}',
        '\0' <= c2 <= '\u{7f}',
        c1 as u8 == c2 as u8,
    ensures
        c1 == c2,
{
    let u1 = c1 as u32;
    let u2 = c2 as u32;
    assert(u1 <= 0x7f);
    assert(u2 <= 0x7f);
    assert(u1 as u8 == c1 as u8);
    assert(u2 as u8 == c2 as u8);
    assert(u1 == u2) by (bit_vector)
        requires
            u1 <= 0x7f,
            u2 <= 0x7f,
            u1 as u8 == u2 as u8,
    ;
    vstd::utf8::char_u32_cast(c1, u1);
    vstd::utf8::char_u32_cast(c2, u2);
    assert(u1 as char == c1);
    assert(u2 as char == c2);
}

/// `true` exactly when the two strings have the same view. The body is checked.
pub fn eq_str_view(a: &str, b: &str) -> (r: bool)
    ensures
        r == (a@ == b@),
{
    let an = a.unicode_len();
    let bn = b.unicode_len();
    if an != bn {
        proof {
            assert(an as int == a@.len());
            assert(bn as int == b@.len());
            assert(a@.len() != b@.len());
        }
        return false;
    }
    if a.is_ascii() && b.is_ascii() {
        let mut i: usize = 0;
        while i < an
            invariant
                i <= an,
                an as int == a@.len(),
                bn as int == b@.len(),
                an == bn,
                is_ascii(a),
                is_ascii(b),
                forall|j: int| 0 <= j < i as int ==> a@[j] == b@[j],
            decreases an - i,
        {
            let ca = a.get_ascii(i);
            let cb = b.get_ascii(i);
            if ca != cb {
                proof {
                    assert(a@[i as int] as u8 == ca);
                    assert(b@[i as int] as u8 == cb);
                    assert(a@[i as int] != b@[i as int]);
                }
                return false;
            }
            proof {
                assert(a@[i as int] as u8 == ca);
                assert(b@[i as int] as u8 == cb);
                assert(ca == cb);
                assert('\0' <= a@[i as int] <= '\u{7f}');
                assert('\0' <= b@[i as int] <= '\u{7f}');
                lemma_ascii_chars_eq_from_u8(a@[i as int], b@[i as int]);
                assert(a@[i as int] == b@[i as int]);
            }
            i = i + 1;
        }
        proof {
            assert(i == an);
            assert forall|j: int| 0 <= j < a@.len() implies a@[j] == b@[j] by {
                assert(0 <= j < i as int);
            };
            assert(a@ =~= b@);
        }
        return true;
    }
    let mut i: usize = 0;
    while i < an
        invariant
            i <= an,
            an as int == a@.len(),
            bn as int == b@.len(),
            an == bn,
            forall|j: int| 0 <= j < i as int ==> a@[j] == b@[j],
        decreases an - i,
    {
        let ca = a.get_char(i);
        let cb = b.get_char(i);
        let ua = ca as u32;
        let ub = cb as u32;
        if ua != ub {
            proof {
                assert(a@[i as int] == ca);
                assert(b@[i as int] == cb);
                if ca == cb {
                    assert(ua == ub);
                }
                assert(ca != cb);
            }
            return false;
        }
        proof {
            assert(ua == ub);
            vstd::utf8::char_u32_cast(ca, ua);
            vstd::utf8::char_u32_cast(cb, ub);
            assert(ua as char == ca);
            assert(ub as char == cb);
            assert(ca == cb);
            assert(a@[i as int] == ca);
            assert(b@[i as int] == cb);
            assert(a@[i as int] == b@[i as int]);
        }
        i = i + 1;
    }
    proof {
        assert(i == an);
        assert forall|j: int| 0 <= j < a@.len() implies a@[j] == b@[j] by {
            assert(0 <= j < i as int);
        };
        assert(a@ =~= b@);
    }
    true
}

/// Compare a bounded string to a literal without counting characters on the column.
pub fn eq_ascii_lit(s: &str, lit: &str) -> (r: bool)
    requires
        s@.len() <= 512,
    ensures
        r == (s@ == lit@),
{
    if !lit.is_ascii() {
        return eq_str_view(s, lit);
    }
    let ln_chars = lit.unicode_len();
    proof {
        assert(ln_chars as int == lit@.len());
        assert(lit@.len() <= usize::MAX);
        assert(is_ascii(lit));
    }
    if !s.is_ascii() {
        proof {
            assert(!is_ascii(s));
            assert(is_ascii(lit));
            if s@ == lit@ {
                assert(is_ascii(s));
            }
            assert(s@ != lit@);
        }
        return false;
    }
    let sn = s.len();
    let ln = lit.len();
    proof {
        broadcast use vstd::string::is_ascii_spec_bytes;
        assert(is_ascii(s));
        assert(is_ascii(lit));
        assert(s.spec_bytes().len() == s@.len());
        assert(lit.spec_bytes().len() == lit@.len());
        assert(s@.len() <= usize::MAX);
        assert(lit@.len() <= usize::MAX);
        assert(sn == s.spec_bytes().len() as usize);
        assert(ln == lit.spec_bytes().len() as usize);
        assert(sn as int == s@.len());
        assert(ln as int == lit@.len());
    }
    if sn != ln {
        proof {
            assert(s@.len() != lit@.len());
        }
        return false;
    }
    let mut i: usize = 0;
    while i < sn
        invariant
            i <= sn,
            sn as int == s@.len(),
            ln as int == lit@.len(),
            sn == ln,
            is_ascii(s),
            is_ascii(lit),
            forall|j: int| 0 <= j < i as int ==> s@[j] == lit@[j],
        decreases sn - i,
    {
        let ca = s.get_ascii(i);
        let cb = lit.get_ascii(i);
        if ca != cb {
            proof {
                assert(s@[i as int] as u8 == ca);
                assert(lit@[i as int] as u8 == cb);
                assert(s@[i as int] != lit@[i as int]);
            }
            return false;
        }
        proof {
            assert(s@[i as int] as u8 == ca);
            assert(lit@[i as int] as u8 == cb);
            assert(ca == cb);
            assert('\0' <= s@[i as int] <= '\u{7f}');
            assert('\0' <= lit@[i as int] <= '\u{7f}');
            lemma_ascii_chars_eq_from_u8(s@[i as int], lit@[i as int]);
            assert(s@[i as int] == lit@[i as int]);
        }
        i = i + 1;
    }
    proof {
        assert(i == sn);
        assert forall|j: int| 0 <= j < s@.len() implies s@[j] == lit@[j] by {
            assert(0 <= j < i as int);
        };
        assert(s@ =~= lit@);
    }
    true
}

/// Row ids `0..end` where `keys[id] == k`, in increasing order.
pub open spec fn eq_row_ids<K>(keys: Seq<K>, k: K, end: int) -> Seq<usize>
    decreases end,
{
    if end <= 0 {
        Seq::<usize>::empty()
    } else {
        let prev = eq_row_ids(keys, k, end - 1);
        if 0 <= end - 1 < keys.len() {
            if keys[end - 1] == k {
                prev.push((end - 1) as usize)
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

/// Spec keys of an exec column (`String@` or an integer's view).
pub open spec fn key_views<K: View>(keys: Seq<K>) -> Seq<<K as View>::V> {
    Seq::new(keys.len(), |i: int| keys[i]@)
}

pub open spec fn prefix_pairs(i: usize, js: Seq<usize>, t: int) -> Seq<(usize, usize)>
    decreases t,
{
    if t <= 0 {
        Seq::<(usize, usize)>::empty()
    } else {
        let prev = prefix_pairs(i, js, t - 1);
        if 0 <= t - 1 < js.len() {
            prev.push((i, js[t - 1]))
        } else {
            prev
        }
    }
}

/// Matches between `outer[0..n]` and `inner`, outer-major, inner increasing.
pub open spec fn nested_eq_pairs<K>(outer: Seq<K>, inner: Seq<K>, n: int) -> Seq<(usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize)>::empty()
    } else if n - 1 >= outer.len() {
        nested_eq_pairs(outer, inner, n - 1)
    } else {
        let i = (n - 1) as usize;
        let ids = eq_row_ids(inner, outer[n - 1], inner.len() as int);
        nested_eq_pairs(outer, inner, n - 1) + prefix_pairs(i, ids, ids.len() as int)
    }
}

/// `m[k]` is a bucket whose view is `eq_row_ids(keys, k, end)`.
pub open spec fn index_ok<K>(
    keys: Seq<K>,
    buckets: Seq<Vec<usize>>,
    m: Map<K, usize>,
    end: int,
) -> bool {
    &&& forall|k: K|
        #[trigger] m.contains_key(k) ==> {
            let bi = m[k] as int;
            0 <= bi < buckets.len() && buckets[bi]@ == eq_row_ids(keys, k, end)
        }
    &&& forall|k: K|
        (#[trigger] eq_row_ids(keys, k, end)).len() > 0 ==> m.contains_key(k)
    &&& forall|k1: K, k2: K|
        #![trigger m.contains_key(k1), m.contains_key(k2)]
        m.contains_key(k1) && m.contains_key(k2) && k1 != k2 ==> m[k1] != m[k2]
}

pub proof fn lemma_index_bucket<K>(
    keys: Seq<K>,
    buckets: Seq<Vec<usize>>,
    m: Map<K, usize>,
    end: int,
    k: K,
)
    requires
        index_ok(keys, buckets, m, end),
        m.contains_key(k),
    ensures
        0 <= (m[k] as int) < buckets.len(),
        buckets[(m[k] as int)]@ == eq_row_ids(keys, k, end),
{
    assert(buckets[(m[k] as int)]@ == eq_row_ids(keys, k, end));
}

pub proof fn lemma_index_covers<K>(
    keys: Seq<K>,
    buckets: Seq<Vec<usize>>,
    m: Map<K, usize>,
    end: int,
    k: K,
)
    requires
        index_ok(keys, buckets, m, end),
        eq_row_ids(keys, k, end).len() > 0,
    ensures
        m.contains_key(k),
{
    assert(m.contains_key(k));
}

pub proof fn lemma_index_absent<K>(
    keys: Seq<K>,
    buckets: Seq<Vec<usize>>,
    m: Map<K, usize>,
    end: int,
    k: K,
)
    requires
        index_ok(keys, buckets, m, end),
        !m.contains_key(k),
    ensures
        eq_row_ids(keys, k, end).len() == 0,
{
    if eq_row_ids(keys, k, end).len() > 0 {
        lemma_index_covers(keys, buckets, m, end, k);
        assert(false);
    }
}

pub proof fn lemma_index_distinct<K>(
    keys: Seq<K>,
    buckets: Seq<Vec<usize>>,
    m: Map<K, usize>,
    end: int,
    k1: K,
    k2: K,
)
    requires
        index_ok(keys, buckets, m, end),
        m.contains_key(k1),
        m.contains_key(k2),
        k1 != k2,
    ensures
        m[k1] != m[k2],
{
    assert(m[k1] != m[k2]);
}

pub proof fn lemma_eq_row_ids_step<K>(keys: Seq<K>, k: K, end: int, row: usize)
    requires
        0 <= end < keys.len(),
        row as int == end,
    ensures
        keys[end] == k ==> eq_row_ids(keys, k, end + 1) == eq_row_ids(keys, k, end).push(row),
        keys[end] != k ==> eq_row_ids(keys, k, end + 1) == eq_row_ids(keys, k, end),
{
    assert((row as int) as usize == row);
    let prev = eq_row_ids(keys, k, end);
    let next = eq_row_ids(keys, k, end + 1);
    if keys[end] == k {
        assert(next == prev.push(row));
    } else {
        assert(next == prev);
    }
}

pub proof fn lemma_prefix_pairs_step(i: usize, js: Seq<usize>, t: int)
    requires
        0 <= t < js.len(),
    ensures
        prefix_pairs(i, js, t + 1) == prefix_pairs(i, js, t).push((i, js[t])),
{
    assert(prefix_pairs(i, js, t + 1) == prefix_pairs(i, js, t).push((i, js[t])));
}

pub proof fn lemma_nested_eq_pairs_step<K>(outer: Seq<K>, inner: Seq<K>, n: int)
    requires
        0 < n <= outer.len(),
    ensures
        nested_eq_pairs(outer, inner, n) == nested_eq_pairs(outer, inner, n - 1) + prefix_pairs(
            (n - 1) as usize,
            eq_row_ids(inner, outer[n - 1], inner.len() as int),
            eq_row_ids(inner, outer[n - 1], inner.len() as int).len() as int,
        ),
{
    assert(nested_eq_pairs(outer, inner, n) == nested_eq_pairs(outer, inner, n - 1) + prefix_pairs(
        (n - 1) as usize,
        eq_row_ids(inner, outer[n - 1], inner.len() as int),
        eq_row_ids(inner, outer[n - 1], inner.len() as int).len() as int,
    ));
}

pub proof fn lemma_seq_add_empty<A>(s: Seq<A>)
    ensures
        s + Seq::<A>::empty() == s,
{
    broadcast use vstd::seq::group_seq_lemmas;

    assert(s + Seq::<A>::empty() =~= s);
}

pub proof fn lemma_key_view_at<K: View>(keys: Seq<K>, i: int)
    requires
        0 <= i < keys.len(),
    ensures
        key_views(keys)[i] == keys[i]@,
{
    broadcast use vstd::seq::lemma_seq_new_index;

    assert(key_views(keys)[i] == keys[i]@);
}

pub proof fn lemma_index_ok_empty<K>(keys: Seq<K>)
    ensures
        index_ok(keys, Seq::<Vec<usize>>::empty(), Map::<K, usize>::empty(), 0),
{
    broadcast use vstd::map::group_map_lemmas;

    assert forall|k: K| eq_row_ids(keys, k, 0) == Seq::<usize>::empty() by {
        assert(eq_row_ids(keys, k, 0) == Seq::<usize>::empty());
    };
    assert(Map::<K, usize>::empty().dom() =~= Set::<K>::empty());
    assert(index_ok(keys, Seq::<Vec<usize>>::empty(), Map::<K, usize>::empty(), 0));
}

pub proof fn lemma_eq_row_ids_len0<K>(keys: Seq<K>, k: K, end: int)
    requires
        eq_row_ids(keys, k, end).len() == 0,
    ensures
        eq_row_ids(keys, k, end) == Seq::<usize>::empty(),
{
    broadcast use vstd::seq::group_seq_lemmas;

    let s = eq_row_ids(keys, k, end);
    assert(s.len() == 0);
    assert(Seq::<usize>::empty().len() == 0);
    assert(s =~= Seq::<usize>::empty());
}

pub proof fn lemma_eq_row_ids_len_le_end<K>(keys: Seq<K>, k: K, end: int)
    requires
        0 <= end <= keys.len(),
    ensures
        eq_row_ids(keys, k, end).len() <= end,
    decreases end,
{
    if end > 0 {
        lemma_eq_row_ids_len_le_end(keys, k, end - 1);
        let prev = eq_row_ids(keys, k, end - 1);
        assert(prev.len() <= end - 1);
        if 0 <= end - 1 < keys.len() && keys[end - 1] == k {
            assert(eq_row_ids(keys, k, end) == prev.push((end - 1) as usize));
        } else {
            assert(eq_row_ids(keys, k, end) == prev);
        }
    }
}

pub proof fn lemma_prefix_pairs_len_le_t(i: usize, js: Seq<usize>, t: int)
    requires
        0 <= t,
    ensures
        prefix_pairs(i, js, t).len() <= t,
    decreases t,
{
    if t > 0 {
        lemma_prefix_pairs_len_le_t(i, js, t - 1);
        let prev = prefix_pairs(i, js, t - 1);
        assert(prev.len() <= t - 1);
        if 0 <= t - 1 < js.len() {
            assert(prefix_pairs(i, js, t) == prev.push((i, js[t - 1])));
            assert(prefix_pairs(i, js, t).len() == prev.len() + 1);
        } else {
            assert(prefix_pairs(i, js, t) == prev);
        }
    }
}

/// Pair-list length is at most the product of the two scanned lengths.
pub proof fn lemma_nested_eq_pairs_len_le_product<K>(outer: Seq<K>, inner: Seq<K>, n: int)
    requires
        0 <= n,
    ensures
        nested_eq_pairs(outer, inner, n).len() <= n * inner.len(),
    decreases n,
{
    if n > 0 {
        lemma_nested_eq_pairs_len_le_product(outer, inner, n - 1);
        let prev = nested_eq_pairs(outer, inner, n - 1);
        assert(prev.len() <= (n - 1) * inner.len());
        if n - 1 >= outer.len() {
            assert(nested_eq_pairs(outer, inner, n) == prev);
            assert((n - 1) * inner.len() <= n * inner.len()) by (nonlinear_arith)
                requires
                    0 <= inner.len(),
            {
            }
        } else {
            let i = (n - 1) as usize;
            let end = inner.len() as int;
            let ids = eq_row_ids(inner, outer[n - 1], end);
            lemma_eq_row_ids_len_le_end(inner, outer[n - 1], end);
            lemma_prefix_pairs_len_le_t(i, ids, ids.len() as int);
            let added = prefix_pairs(i, ids, ids.len() as int);
            assert(added.len() <= ids.len());
            assert(ids.len() <= end);
            assert(nested_eq_pairs(outer, inner, n) == prev + added);
            assert((prev + added).len() == prev.len() + added.len());
            assert(prev.len() + added.len() <= (n - 1) * inner.len() + inner.len()) by (nonlinear_arith)
                requires
                    prev.len() <= (n - 1) * inner.len(),
                    added.len() <= inner.len(),
            {
            }
            assert((n - 1) * inner.len() + inner.len() == n * inner.len()) by (nonlinear_arith)
                requires
                    0 <= inner.len(),
            {
            }
        }
    }
}

pub proof fn lemma_eq_row_ids_bounded<K>(keys: Seq<K>, k: K, end: int)
    requires
        0 <= end <= keys.len(),
        end <= usize::MAX as int,
    ensures
        forall|t: int|
            0 <= t < eq_row_ids(keys, k, end).len() ==> (#[trigger] eq_row_ids(keys, k, end)[t] as int)
                < end,
    decreases end,
{
    if end > 0 {
        assert(0 <= end - 1 <= usize::MAX as int);
        assert(end - 1 <= keys.len());
        lemma_eq_row_ids_bounded(keys, k, end - 1);
        let prev = eq_row_ids(keys, k, end - 1);
        let row = (end - 1) as usize;
        assert(row as int == end - 1);
        lemma_eq_row_ids_step(keys, k, end - 1, row);
        let cur = eq_row_ids(keys, k, end);
        if keys[end - 1] == k {
            assert(cur == prev.push(row));
            assert forall|t: int| 0 <= t < cur.len() implies ((cur[t] as int) < end) by {
                if t == prev.len() {
                    assert(cur[t] == row);
                    assert((row as int) < end);
                } else {
                    lemma_seq_push_index_different(prev, row, t);
                    assert((prev[t] as int) < end - 1);
                }
            };
        } else {
            assert(cur == prev);
            assert forall|t: int| 0 <= t < cur.len() implies ((cur[t] as int) < end) by {
                assert((prev[t] as int) < end - 1);
            };
        }
    }
}

/// Each stored pair is an outer index below `n` and an inner index below `inner.len()`.
pub proof fn lemma_nested_eq_pairs_index_in_range<K>(outer: Seq<K>, inner: Seq<K>, n: int)
    requires
        0 <= n <= outer.len(),
        n <= usize::MAX as int,
        inner.len() <= usize::MAX as int,
    ensures
        forall|p: int|
            0 <= p < nested_eq_pairs(outer, inner, n).len() ==> {
                let pair = #[trigger] nested_eq_pairs(outer, inner, n)[p];
                (pair.0 as int) < n && (pair.1 as int) < inner.len()
            },
    decreases n,
{
    if n > 0 {
        lemma_nested_eq_pairs_index_in_range(outer, inner, n - 1);
        let prev = nested_eq_pairs(outer, inner, n - 1);
        if n - 1 >= outer.len() {
            assert(nested_eq_pairs(outer, inner, n) == prev);
        } else {
            assert(0 <= n - 1 <= usize::MAX as int);
            let i = (n - 1) as usize;
            assert(i as int == n - 1);
            let end = inner.len() as int;
            let ids = eq_row_ids(inner, outer[n - 1], end);
            let added = prefix_pairs(i, ids, ids.len() as int);
            assert(nested_eq_pairs(outer, inner, n) == prev + added);
            lemma_eq_row_ids_bounded(inner, outer[n - 1], end);
            lemma_prefix_len(i, ids, ids.len() as int);
            assert forall|p: int|
                #![trigger (prev + added)[p]]
                0 <= p < (prev + added).len()
                implies ((prev + added)[p].0 as int) < n && ((prev + added)[p].1 as int)
                    < inner.len()
            by {
                if p < prev.len() {
                    lemma_left_index(prev, added, p);
                } else {
                    let q = p - prev.len();
                    lemma_right_index(prev, added, q);
                    lemma_prefix_at(i, ids, ids.len() as int, q);
                    assert(added[q] == (i, ids[q]));
                    assert((i as int) == n - 1);
                    assert((ids[q] as int) < end);
                }
            };
        }
    }
}

/// Existing key: one bucket grows by `row`. Map is unchanged.
#[verifier::spinoff_prover]
pub proof fn lemma_index_append<K>(
    keys: Seq<K>,
    old_b: Seq<Vec<usize>>,
    new_b: Seq<Vec<usize>>,
    old_bucket: Seq<usize>,
    m: Map<K, usize>,
    k: K,
    end: int,
    row: usize,
    bi: usize,
)
    requires
        index_ok(keys, old_b, m, end),
        0 <= end < keys.len(),
        row as int == end,
        keys[end] == k,
        m.contains_key(k),
        m[k] == bi,
        (bi as int) < old_b.len(),
        old_b[bi as int]@ == old_bucket,
        new_b == old_b.update(bi as int, new_b[bi as int]),
        new_b[bi as int]@ == old_bucket.push(row),
    ensures
        index_ok(keys, new_b, m, end + 1),
{
    broadcast use vstd::seq::group_seq_lemmas;

    lemma_eq_row_ids_step(keys, k, end, row);
    lemma_index_bucket(keys, old_b, m, end, k);
    lemma_seq_update_len(old_b, bi as int, new_b[bi as int]);
    assert(new_b.len() == old_b.len());
    assert forall|k2: K| m.contains_key(k2) implies {
        let bi2 = m[k2] as int;
        0 <= bi2 < new_b.len() && new_b[bi2]@ == eq_row_ids(keys, k2, end + 1)
    } by {
        lemma_index_bucket(keys, old_b, m, end, k2);
        let bi2 = m[k2] as int;
        assert(0 <= bi2 < old_b.len());
        assert(bi2 < new_b.len());
        if k2 == k {
            assert(bi2 == bi as int);
            assert(old_bucket == eq_row_ids(keys, k, end));
            assert(new_b[bi2]@ == old_bucket.push(row));
            assert(eq_row_ids(keys, k, end + 1) == old_bucket.push(row));
        } else {
            lemma_index_distinct(keys, old_b, m, end, k2, k);
            assert(bi2 != bi as int);
            lemma_seq_update_different(old_b, bi2, bi as int, new_b[bi as int]);
            assert(old_b.update(bi as int, new_b[bi as int])[bi2] == old_b[bi2]);
            assert(new_b[bi2] == old_b[bi2]);
            lemma_eq_row_ids_step(keys, k2, end, row);
            assert(keys[end] != k2);
            assert(eq_row_ids(keys, k2, end + 1) == eq_row_ids(keys, k2, end));
            assert(new_b[bi2]@ == eq_row_ids(keys, k2, end + 1));
        }
    };
    assert forall|k2: K| eq_row_ids(keys, k2, end + 1).len() > 0 implies m.contains_key(k2) by {
        lemma_eq_row_ids_step(keys, k2, end, row);
        if keys[end] == k2 {
            assert(k2 == k);
            assert(m.contains_key(k));
        } else {
            assert(eq_row_ids(keys, k2, end + 1) == eq_row_ids(keys, k2, end));
            lemma_index_covers(keys, old_b, m, end, k2);
        }
    };
    assert forall|k1: K, k2: K| #![auto]
        m.contains_key(k1) && m.contains_key(k2) && k1 != k2 implies m[k1] != m[k2] by {
        lemma_index_distinct(keys, old_b, m, end, k1, k2);
    };
    assert(index_ok(keys, new_b, m, end + 1));
}

/// Fresh key: append a new one-element bucket and point the map at it.
#[verifier::spinoff_prover]
pub proof fn lemma_index_insert<K>(
    keys: Seq<K>,
    old_b: Seq<Vec<usize>>,
    new_b: Seq<Vec<usize>>,
    old_m: Map<K, usize>,
    new_m: Map<K, usize>,
    k: K,
    end: int,
    row: usize,
    bi: usize,
    one: Vec<usize>,
)
    requires
        index_ok(keys, old_b, old_m, end),
        0 <= end < keys.len(),
        row as int == end,
        keys[end] == k,
        !old_m.contains_key(k),
        bi as int == old_b.len(),
        one@ == Seq::<usize>::empty().push(row),
        new_b == old_b.push(one),
        new_m == old_m.insert(k, bi),
    ensures
        index_ok(keys, new_b, new_m, end + 1),
{
    broadcast use vstd::seq::group_seq_lemmas;
    broadcast use vstd::map::group_map_lemmas;
    broadcast use vstd::set::group_set_lemmas;

    lemma_eq_row_ids_step(keys, k, end, row);
    lemma_index_absent(keys, old_b, old_m, end, k);
    lemma_eq_row_ids_len0(keys, k, end);
    assert(eq_row_ids(keys, k, end + 1) == Seq::<usize>::empty().push(row));
    lemma_seq_push_len(old_b, one);
    lemma_seq_push_index_same(old_b, one, bi as int);
    assert(new_b[bi as int] == one);
    assert(new_b[bi as int]@ == one@);
    assert(new_b[bi as int]@ == eq_row_ids(keys, k, end + 1));
    lemma_map_insert_same(old_m, k, bi);
    assert(old_m.insert(k, bi)[k] == bi);
    assert(new_m[k] == bi);
    lemma_map_insert_domain(old_m, k, bi);
    lemma_set_insert_same(old_m.dom(), k);
    assert(new_m.contains_key(k));

    assert forall|k2: K| new_m.contains_key(k2) implies {
        let bi2 = new_m[k2] as int;
        0 <= bi2 < new_b.len() && new_b[bi2]@ == eq_row_ids(keys, k2, end + 1)
    } by {
        let bi2 = new_m[k2] as int;
        if k2 == k {
            assert(bi2 == bi as int);
            assert(0 <= bi2 < new_b.len());
            assert(new_b[bi2]@ == eq_row_ids(keys, k, end + 1));
        } else {
            lemma_set_insert_different(old_m.dom(), k2, k);
            assert(old_m.contains_key(k2));
            axiom_map_insert_different(old_m, k2, k, bi);
            assert(old_m.insert(k, bi)[k2] == old_m[k2]);
            assert(new_m[k2] == old_m[k2]);
            lemma_index_bucket(keys, old_b, old_m, end, k2);
            assert(0 <= bi2 < old_b.len());
            assert(bi2 != bi as int);
            lemma_seq_push_index_different(old_b, one, bi2);
            assert(new_b[bi2] == old_b[bi2]);
            lemma_eq_row_ids_step(keys, k2, end, row);
            assert(keys[end] != k2);
            assert(eq_row_ids(keys, k2, end + 1) == eq_row_ids(keys, k2, end));
            assert(new_b[bi2]@ == eq_row_ids(keys, k2, end + 1));
        }
    };
    assert forall|k2: K| eq_row_ids(keys, k2, end + 1).len() > 0 implies new_m.contains_key(k2) by {
        lemma_eq_row_ids_step(keys, k2, end, row);
        if keys[end] == k2 {
            assert(k2 == k);
            assert(new_m.contains_key(k));
        } else {
            assert(eq_row_ids(keys, k2, end + 1) == eq_row_ids(keys, k2, end));
            lemma_index_covers(keys, old_b, old_m, end, k2);
            lemma_set_insert_different(old_m.dom(), k2, k);
            assert(new_m.contains_key(k2));
        }
    };
    assert forall|k1: K, k2: K| #![auto]
        new_m.contains_key(k1) && new_m.contains_key(k2) && k1 != k2 implies new_m[k1] != new_m[k2] by {
        if k1 != k && k2 != k {
            lemma_set_insert_different(old_m.dom(), k1, k);
            lemma_set_insert_different(old_m.dom(), k2, k);
            axiom_map_insert_different(old_m, k1, k, bi);
            axiom_map_insert_different(old_m, k2, k, bi);
            assert(new_m[k1] == old_m[k1]);
            assert(new_m[k2] == old_m[k2]);
            lemma_index_distinct(keys, old_b, old_m, end, k1, k2);
        } else if k1 == k {
            assert(new_m[k1] == bi);
            lemma_set_insert_different(old_m.dom(), k2, k);
            axiom_map_insert_different(old_m, k2, k, bi);
            assert(new_m[k2] == old_m[k2]);
            lemma_index_bucket(keys, old_b, old_m, end, k2);
            assert((old_m[k2] as int) < old_b.len());
            assert(old_m[k2] != bi);
        } else {
            assert(k2 == k);
            assert(new_m[k2] == bi);
            lemma_set_insert_different(old_m.dom(), k1, k);
            axiom_map_insert_different(old_m, k1, k, bi);
            assert(new_m[k1] == old_m[k1]);
            lemma_index_bucket(keys, old_b, old_m, end, k1);
            assert((old_m[k1] as int) < old_b.len());
            assert(old_m[k1] != bi);
        }
    };
    assert(index_ok(keys, new_b, new_m, end + 1));
}

pub struct EqIndexStr {
    pub buckets: Vec<Vec<usize>>,
    pub map: StringHashMap<usize>,
}

/// Bucket row-ids for `keys`. Each id appears once, in increasing order.
pub fn build_eq_index_str(keys: &Vec<String>) -> (idx: EqIndexStr)
    ensures
        index_ok(key_views(keys@), idx.buckets@, idx.map@, keys@.len() as int),
{
    let ghost sk = key_views(keys@);
    let mut buckets: Vec<Vec<usize>> = Vec::with_capacity(keys.len());
    let mut map: StringHashMap<usize> = StringHashMap::with_capacity(keys.len());
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        lemma_index_ok_empty::<Seq<char>>(sk);
    }
    let mut i: usize = 0;
    while i < keys.len()
        invariant
            i <= keys.len(),
            keys@.len() == keys.len() as int,
            sk == key_views(keys@),
            index_ok(sk, buckets@, map@, i as int),
        decreases keys.len() - i,
    {
        let key = keys[i].clone();
        let ghost k = key@;
        let ghost end = i as int;
        proof {
            lemma_key_view_at(keys@, end);
            assert(k == sk[end]);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(keys@.len() == keys.len() as int);
        }
        let present = map.contains_key(key.as_str());
        proof {
            assert(present == map@.contains_key(k));
        }
        if present {
            let got = map.get(key.as_str());
            proof {
                assert(got is Some);
                assert(map@.contains_key(k));
            }
            let bi = *got.unwrap();
            proof {
                assert(map@[k] == bi);
                lemma_index_bucket(sk, buckets@, map@, end, k);
                assert((bi as int) < buckets@.len());
            }
            let ghost old_b = buckets@;
            let ghost old_bucket = buckets@[bi as int]@;
            let ghost m = map@;
            buckets[bi].push(i);
            proof {
                assert(buckets@ == old_b.update(bi as int, buckets@[bi as int]));
                assert(buckets@[bi as int]@ == old_bucket.push(i));
                lemma_index_append(sk, old_b, buckets@, old_bucket, m, k, end, i, bi);
            }
        } else {
            proof {
                assert(!map@.contains_key(k));
            }
            let bi = buckets.len();
            let ghost old_b = buckets@;
            let ghost old_m = map@;
            let mut one: Vec<usize> = Vec::new();
            one.push(i);
            let ghost one_g = one;
            proof {
                broadcast use vstd::std_specs::vec::axiom_spec_len;
                assert(bi as int == old_b.len());
                assert(one_g@ == Seq::<usize>::empty().push(i));
                assert(!old_m.contains_key(k));
            }
            buckets.push(one);
            map.insert(key, bi);
            proof {
                assert(buckets@ == old_b.push(one_g));
                assert(map@ == old_m.insert(k, bi));
                lemma_index_insert(sk, old_b, buckets@, old_m, map@, k, end, i, bi, one_g);
            }
        }
        proof {
            assert(index_ok(sk, buckets@, map@, end + 1));
        }
        i = i + 1;
    }
    EqIndexStr { buckets, map }
}

/// Bucket for `key`, or `None` when no row matches.
pub fn probe_eq_str<'a>(idx: &'a EqIndexStr, keys: &Vec<String>, key: &str) -> (hit: Option<&'a Vec<usize>>)
    requires
        index_ok(key_views(keys@), idx.buckets@, idx.map@, keys@.len() as int),
    ensures
        match hit {
            Some(v) => v@ == eq_row_ids(key_views(keys@), key@, keys@.len() as int),
            None => eq_row_ids(key_views(keys@), key@, keys@.len() as int).len() == 0,
        },
{
    let ghost sk = key_views(keys@);
    let ghost n = keys@.len() as int;
    let bi_opt: Option<usize> = match idx.map.get(key) {
        Some(bi_ref) => Some(*bi_ref),
        None => None,
    };
    match bi_opt {
        Some(bi) => {
            proof {
                broadcast use vstd::std_specs::vec::axiom_spec_len;
                assert(idx.map@.contains_key(key@));
                assert(idx.map@[key@] == bi);
                assert((bi as int) < idx.buckets@.len());
                assert(idx.buckets@[bi as int]@ == eq_row_ids(sk, key@, n));
                assert(idx.buckets.len() == idx.buckets@.len());
            }
            Some(&idx.buckets[bi])
        },
        None => {
            proof {
                assert(!idx.map@.contains_key(key@));
                assert(eq_row_ids(sk, key@, n).len() == 0);
            }
            None
        },
    }
}

pub fn push_prefix_pairs(pairs: &mut Vec<(usize, usize)>, i: usize, ids: &Vec<usize>)
    ensures
        final(pairs)@ == old(pairs)@ + prefix_pairs(i, ids@, ids@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(ids@.len() == ids.len() as int);
    }
    let ghost base = pairs@;
    let mut extra: Vec<(usize, usize)> = Vec::new();
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            extra@ == prefix_pairs(i, ids@, t as int),
        decreases ids.len() - t,
    {
        let ghost old_extra = extra@;
        let id = ids[t];
        extra.push((i, id));
        proof {
            assert(id == ids@[t as int]);
            lemma_prefix_pairs_step(i, ids@, t as int);
            assert(extra@ == old_extra.push((i, ids@[t as int])));
            assert(extra@ == prefix_pairs(i, ids@, t as int + 1));
        }
        t = t + 1;
    }
    proof {
        assert(extra@ == prefix_pairs(i, ids@, ids@.len() as int));
        assert(pairs@ == base);
    }
    pairs.append(&mut extra);
    proof {
        assert(pairs@ == base + prefix_pairs(i, ids@, ids@.len() as int));
    }
}

/// Pair list equal to the nested equijoin on one string column.
pub fn equijoin_pairs_str(outer: &Vec<String>, inner: &Vec<String>) -> (pairs: Vec<(usize, usize)>)
    ensures
        pairs@ == nested_eq_pairs(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    let idx = build_eq_index_str(inner);
    let ghost ov = key_views(outer@);
    let ghost iv = key_views(inner@);
    let mut pairs: Vec<(usize, usize)> = Vec::new();
    let mut i: usize = 0;
    while i < outer.len()
        invariant
            i <= outer.len(),
            outer@.len() == outer.len() as int,
            inner@.len() == inner.len() as int,
            ov == key_views(outer@),
            iv == key_views(inner@),
            index_ok(iv, idx.buckets@, idx.map@, inner@.len() as int),
            pairs@ == nested_eq_pairs(ov, iv, i as int),
        decreases outer.len() - i,
    {
        let key = outer[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(ov[end] == key@);
        }
        let ghost before = pairs@;
        let bi_opt: Option<usize> = match idx.map.get(key.as_str()) {
            Some(bi_ref) => Some(*bi_ref),
            None => None,
        };
        match bi_opt {
            Some(bi) => {
                proof {
                    assert(idx.map@.contains_key(key@));
                    assert(idx.buckets@[bi as int]@ == eq_row_ids(iv, key@, iv.len() as int));
                }
                let ids = &idx.buckets[bi];
                push_prefix_pairs(&mut pairs, i, ids);
                proof {
                    lemma_nested_eq_pairs_step(ov, iv, end + 1);
                    assert(ids@ == eq_row_ids(iv, ov[end], iv.len() as int));
                    assert(pairs@ == before + prefix_pairs(i, ids@, ids@.len() as int));
                    assert(pairs@ == nested_eq_pairs(ov, iv, end + 1));
                }
            },
            None => {
                proof {
                    assert(!idx.map@.contains_key(key@));
                    assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                    lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                    lemma_nested_eq_pairs_step(ov, iv, end + 1);
                    lemma_seq_add_empty(before);
                    assert(prefix_pairs(i, Seq::<usize>::empty(), 0) == Seq::<(usize, usize)>::empty());
                    assert(pairs@ == nested_eq_pairs(ov, iv, end + 1));
                }
            },
        }
        i = i + 1;
    }
    pairs
}

// SHAPE_INTKEY_BEGIN
/// Identity view for integer keys (`u64@ == u64`). Trigger for the quantifier.
pub open spec fn view_is_id<K: View<V = K>>(x: K) -> bool {
    x@ == x
}

#[verifier::reject_recursive_types(K)]
pub struct EqIndexCopy<K> where K: View<V = K> + Eq + Hash {
    pub buckets: Vec<Vec<usize>>,
    pub map: HashMap<K, usize>,
}

pub proof fn lemma_u64_hash_key()
    ensures
        obeys_key_model::<u64>(),
        builds_valid_hashers::<RandomState>(),
        forall|x: u64| #[trigger] view_is_id(x),
{
    broadcast use axiom_u64_obeys_hash_table_key_model;
    broadcast use axiom_random_state_builds_valid_hashers;

    assert(obeys_key_model::<u64>());
    assert(builds_valid_hashers::<RandomState>());
    assert forall|x: u64| #[trigger] view_is_id(x) by {
        assert(x@ == x);
    };
}

pub proof fn lemma_u32_hash_key()
    ensures
        obeys_key_model::<u32>(),
        builds_valid_hashers::<RandomState>(),
        forall|x: u32| #[trigger] view_is_id(x),
{
    broadcast use axiom_u32_obeys_hash_table_key_model;
    broadcast use axiom_random_state_builds_valid_hashers;

    assert(obeys_key_model::<u32>());
    assert(builds_valid_hashers::<RandomState>());
    assert forall|x: u32| #[trigger] view_is_id(x) by {
        assert(x@ == x);
    };
}

/// Same bucket invariant as [`build_eq_index_str`], for identity-view keys (`u32`, `u64`).
pub fn build_eq_index_copy<K: Copy + View<V = K> + Eq + Hash>(keys: &Vec<K>) -> (idx: EqIndexCopy<K>)
    requires
        obeys_key_model::<K>(),
        builds_valid_hashers::<RandomState>(),
        forall|x: K| #[trigger] view_is_id(x),
    ensures
        index_ok(key_views(keys@), idx.buckets@, idx.map@, keys@.len() as int),
{
    let ghost sk = key_views(keys@);
    let mut buckets: Vec<Vec<usize>> = Vec::with_capacity(keys.len());
    let mut map: HashMap<K, usize> = HashMap::with_capacity(keys.len());
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        lemma_index_ok_empty(sk);
    }
    let mut i: usize = 0;
    while i < keys.len()
        invariant
            i <= keys.len(),
            keys@.len() == keys.len() as int,
            sk == key_views(keys@),
            obeys_key_model::<K>(),
            builds_valid_hashers::<RandomState>(),
            forall|x: K| #[trigger] view_is_id(x),
            index_ok(sk, buckets@, map@, i as int),
        decreases keys.len() - i,
    {
        let key = keys[i];
        let ghost k = key@;
        let ghost end = i as int;
        proof {
            lemma_key_view_at(keys@, end);
            assert(k == sk[end]);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(keys@.len() == keys.len() as int);
        }
        proof {
            assert(view_is_id(key));
            assert(key@ == key);
            broadcast use axiom_contains_deref_key;
        }
        let present = map.contains_key(&key);
        proof {
            assert(present == map@.contains_key(key));
            assert(present == map@.contains_key(k));
        }
        if present {
            let got = map.get(&key);
            proof {
                broadcast use axiom_maps_deref_key_to_value;
                assert(got is Some);
                assert(map@.contains_key(k));
            }
            let bi = *got.unwrap();
            proof {
                assert(map@[k] == bi);
                lemma_index_bucket(sk, buckets@, map@, end, k);
                assert((bi as int) < buckets@.len());
            }
            let ghost old_b = buckets@;
            let ghost old_bucket = buckets@[bi as int]@;
            let ghost m = map@;
            buckets[bi].push(i);
            proof {
                assert(buckets@ == old_b.update(bi as int, buckets@[bi as int]));
                assert(buckets@[bi as int]@ == old_bucket.push(i));
                lemma_index_append(sk, old_b, buckets@, old_bucket, m, k, end, i, bi);
            }
        } else {
            proof {
                assert(!map@.contains_key(k));
            }
            let bi = buckets.len();
            let ghost old_b = buckets@;
            let ghost old_m = map@;
            let mut one: Vec<usize> = Vec::new();
            one.push(i);
            let ghost one_g = one;
            proof {
                broadcast use vstd::std_specs::vec::axiom_spec_len;
                assert(bi as int == old_b.len());
                assert(one_g@ == Seq::<usize>::empty().push(i));
                assert(!old_m.contains_key(k));
            }
            buckets.push(one);
            map.insert(key, bi);
            proof {
                assert(buckets@ == old_b.push(one_g));
                assert(map@ == old_m.insert(k, bi));
                lemma_index_insert(sk, old_b, buckets@, old_m, map@, k, end, i, bi, one_g);
            }
        }
        proof {
            assert(index_ok(sk, buckets@, map@, end + 1));
        }
        i = i + 1;
    }
    EqIndexCopy { buckets, map }
}

pub fn build_eq_index_u64(keys: &Vec<u64>) -> (idx: EqIndexCopy<u64>)
    ensures
        index_ok(key_views(keys@), idx.buckets@, idx.map@, keys@.len() as int),
{
    proof {
        lemma_u64_hash_key();
    }
    build_eq_index_copy(keys)
}

pub fn build_eq_index_u32(keys: &Vec<u32>) -> (idx: EqIndexCopy<u32>)
    ensures
        index_ok(key_views(keys@), idx.buckets@, idx.map@, keys@.len() as int),
{
    proof {
        lemma_u32_hash_key();
    }
    build_eq_index_copy(keys)
}

pub fn equijoin_pairs_copy<K: Copy + View<V = K> + Eq + Hash>(
    outer: &Vec<K>,
    inner: &Vec<K>,
) -> (pairs: Vec<(usize, usize)>)
    requires
        obeys_key_model::<K>(),
        builds_valid_hashers::<RandomState>(),
        forall|x: K| #[trigger] view_is_id(x),
    ensures
        pairs@ == nested_eq_pairs(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    let idx = build_eq_index_copy(inner);
    let ghost ov = key_views(outer@);
    let ghost iv = key_views(inner@);
    let mut pairs: Vec<(usize, usize)> = Vec::new();
    let mut i: usize = 0;
    while i < outer.len()
        invariant
            i <= outer.len(),
            outer@.len() == outer.len() as int,
            inner@.len() == inner.len() as int,
            ov == key_views(outer@),
            iv == key_views(inner@),
            obeys_key_model::<K>(),
            builds_valid_hashers::<RandomState>(),
            forall|x: K| #[trigger] view_is_id(x),
            index_ok(iv, idx.buckets@, idx.map@, inner@.len() as int),
            pairs@ == nested_eq_pairs(ov, iv, i as int),
        decreases outer.len() - i,
    {
        let key = outer[i];
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(ov[end] == key@);
        }
        let ghost before = pairs@;
        proof {
            assert(view_is_id(key));
            assert(key@ == key);
            broadcast use axiom_contains_deref_key;
            broadcast use axiom_maps_deref_key_to_value;
        }
        let bi_opt: Option<usize> = match idx.map.get(&key) {
            Some(bi_ref) => Some(*bi_ref),
            None => None,
        };
        match bi_opt {
            Some(bi) => {
                proof {
                    assert(idx.map@.contains_key(key@));
                    assert(idx.buckets@[bi as int]@ == eq_row_ids(iv, key@, iv.len() as int));
                }
                let ids = &idx.buckets[bi];
                push_prefix_pairs(&mut pairs, i, ids);
                proof {
                    lemma_nested_eq_pairs_step(ov, iv, end + 1);
                    assert(ids@ == eq_row_ids(iv, ov[end], iv.len() as int));
                    assert(pairs@ == before + prefix_pairs(i, ids@, ids@.len() as int));
                    assert(pairs@ == nested_eq_pairs(ov, iv, end + 1));
                }
            },
            None => {
                proof {
                    assert(!idx.map@.contains_key(key@));
                    assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                    lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                    lemma_nested_eq_pairs_step(ov, iv, end + 1);
                    lemma_seq_add_empty(before);
                    assert(prefix_pairs(i, Seq::<usize>::empty(), 0) == Seq::<(usize, usize)>::empty());
                    assert(pairs@ == nested_eq_pairs(ov, iv, end + 1));
                }
            },
        }
        i = i + 1;
    }
    pairs
}

pub fn equijoin_pairs_u64(outer: &Vec<u64>, inner: &Vec<u64>) -> (pairs: Vec<(usize, usize)>)
    ensures
        pairs@ == nested_eq_pairs(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    proof {
        lemma_u64_hash_key();
    }
    equijoin_pairs_copy(outer, inner)
}

pub fn equijoin_pairs_u32(outer: &Vec<u32>, inner: &Vec<u32>) -> (pairs: Vec<(usize, usize)>)
    ensures
        pairs@ == nested_eq_pairs(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    proof {
        lemma_u32_hash_key();
    }
    equijoin_pairs_copy(outer, inner)
}

// SHAPE_INTKEY_END

// SHAPE_TWOKEY_BEGIN
/// Row ids where column `a` equals `ka` and column `b` equals `kb`.
pub open spec fn eq_row_ids2<A, B>(a: Seq<A>, b: Seq<B>, ka: A, kb: B, end: int) -> Seq<usize>
    decreases end,
{
    if end <= 0 {
        Seq::<usize>::empty()
    } else {
        let prev = eq_row_ids2(a, b, ka, kb, end - 1);
        if 0 <= end - 1 < a.len() {
            if end - 1 < b.len() {
                if a[end - 1] == ka {
                    if b[end - 1] == kb {
                        prev.push((end - 1) as usize)
                    } else {
                        prev
                    }
                } else {
                    prev
                }
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

pub open spec fn nested_eq_pairs2<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
) -> Seq<(usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize)>::empty()
    } else if n - 1 >= outer_a.len() || n - 1 >= outer_b.len() {
        nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1)
    } else {
        let i = (n - 1) as usize;
        let ids = eq_row_ids2(
            inner_a,
            inner_b,
            outer_a[n - 1],
            outer_b[n - 1],
            inner_a.len() as int,
        );
        nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1) + prefix_pairs(
            i,
            ids,
            ids.len() as int,
        )
    }
}

/// Keep `ids[0..t]` whose `col` entry equals `k`.
pub open spec fn filter_match<B>(ids: Seq<usize>, col: Seq<B>, k: B, t: int) -> Seq<usize>
    decreases t,
{
    if t <= 0 {
        Seq::<usize>::empty()
    } else {
        let prev = filter_match(ids, col, k, t - 1);
        if 0 <= t - 1 < ids.len() {
            let j = ids[t - 1];
            if 0 <= j < col.len() {
                if col[j as int] == k {
                    prev.push(j)
                } else {
                    prev
                }
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

pub proof fn lemma_eq_row_ids2_step<A, B>(
    a: Seq<A>,
    b: Seq<B>,
    ka: A,
    kb: B,
    end: int,
    row: usize,
)
    requires
        0 <= end < a.len(),
        end < b.len(),
        row as int == end,
    ensures
        a[end] == ka && b[end] == kb ==> eq_row_ids2(a, b, ka, kb, end + 1) == eq_row_ids2(
            a,
            b,
            ka,
            kb,
            end,
        ).push(row),
        !(a[end] == ka && b[end] == kb) ==> eq_row_ids2(a, b, ka, kb, end + 1) == eq_row_ids2(
            a,
            b,
            ka,
            kb,
            end,
        ),
{
    assert((row as int) as usize == row);
    let prev = eq_row_ids2(a, b, ka, kb, end);
    let next = eq_row_ids2(a, b, ka, kb, end + 1);
    if a[end] == ka && b[end] == kb {
        assert(next == prev.push(row));
    } else {
        assert(next == prev);
    }
}

pub proof fn lemma_nested_eq_pairs2_step<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
)
    requires
        0 < n <= outer_a.len(),
        n <= outer_b.len(),
        inner_a.len() == inner_b.len(),
    ensures
        nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, n) == nested_eq_pairs2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            n - 1,
        ) + prefix_pairs(
            (n - 1) as usize,
            eq_row_ids2(inner_a, inner_b, outer_a[n - 1], outer_b[n - 1], inner_a.len() as int),
            eq_row_ids2(inner_a, inner_b, outer_a[n - 1], outer_b[n - 1], inner_a.len() as int).len() as int,
        ),
{
}

pub proof fn lemma_filter_prefix_same<B>(s: Seq<usize>, col: Seq<B>, k: B, j: usize, t: int)
    requires
        0 <= t <= s.len(),
    ensures
        filter_match(s.push(j), col, k, t) == filter_match(s, col, k, t),
    decreases t,
{
    if t > 0 {
        lemma_filter_prefix_same(s, col, k, j, t - 1);
        lemma_seq_push_index_different(s, j, t - 1);
    }
}

pub proof fn lemma_filter_push<B>(s: Seq<usize>, col: Seq<B>, k: B, j: usize)
    requires
        (j as int) < col.len(),
    ensures
        col[j as int] == k ==> filter_match(s.push(j), col, k, (s.len() + 1) as int) == filter_match(
            s,
            col,
            k,
            s.len() as int,
        ).push(j),
        col[j as int] != k ==> filter_match(s.push(j), col, k, (s.len() + 1) as int) == filter_match(
            s,
            col,
            k,
            s.len() as int,
        ),
{
    lemma_filter_prefix_same(s, col, k, j, s.len() as int);
    lemma_seq_push_len(s, j);
    lemma_seq_push_index_same(s, j, s.len() as int);
}

pub proof fn lemma_filter_is_ids2<A, B>(a: Seq<A>, b: Seq<B>, ka: A, kb: B, end: int)
    requires
        0 <= end <= a.len(),
        a.len() == b.len(),
        end <= usize::MAX as int,
    ensures
        filter_match(
            eq_row_ids(a, ka, end),
            b,
            kb,
            eq_row_ids(a, ka, end).len() as int,
        ) == eq_row_ids2(a, b, ka, kb, end),
    decreases end,
{
    if end > 0 {
        assert(0 <= end - 1 <= usize::MAX as int);
        lemma_filter_is_ids2(a, b, ka, kb, end - 1);
        let row = (end - 1) as usize;
        assert(row as int == end - 1);
        let prev = eq_row_ids(a, ka, end - 1);
        lemma_eq_row_ids_step(a, ka, end - 1, row);
        lemma_eq_row_ids2_step(a, b, ka, kb, end - 1, row);
        if a[end - 1] == ka {
            assert(eq_row_ids(a, ka, end) == prev.push(row));
            lemma_filter_push(prev, b, kb, row);
            if b[end - 1] == kb {
                assert(eq_row_ids2(a, b, ka, kb, end) == eq_row_ids2(a, b, ka, kb, end - 1).push(row));
            } else {
                assert(eq_row_ids2(a, b, ka, kb, end) == eq_row_ids2(a, b, ka, kb, end - 1));
            }
        } else {
            assert(eq_row_ids(a, ka, end) == prev);
            assert(eq_row_ids2(a, b, ka, kb, end) == eq_row_ids2(a, b, ka, kb, end - 1));
        }
    }
}

pub fn filter_row_ids_str(ids: &Vec<usize>, col: &Vec<String>, key: &String) -> (out: Vec<usize>)
    requires
        forall|t: int| 0 <= t < ids@.len() ==> ids@[t] < col@.len(),
    ensures
        out@ == filter_match(ids@, key_views(col@), key@, ids@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(ids@.len() == ids.len() as int);
        assert(col@.len() == col.len() as int);
    }
    let mut out: Vec<usize> = Vec::new();
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            col@.len() == col.len() as int,
            forall|u: int| 0 <= u < ids@.len() ==> ids@[u] < col@.len(),
            out@ == filter_match(ids@, key_views(col@), key@, t as int),
        decreases ids.len() - t,
    {
        let id = ids[t];
        proof {
            assert(id == ids@[t as int]);
            assert(id < col@.len());
            lemma_key_view_at(col@, id as int);
        }
        let ghost old_out = out@;
        if col[id] == *key {
            out.push(id);
            proof {
                assert(col@[id as int]@ == key@);
                assert(key_views(col@)[id as int] == key@);
                assert(out@ == old_out.push(id));
                assert(out@ == filter_match(ids@, key_views(col@), key@, t as int + 1));
            }
        } else {
            proof {
                assert(col@[id as int]@ != key@);
                assert(out@ == filter_match(ids@, key_views(col@), key@, t as int + 1));
            }
        }
        t = t + 1;
    }
    out
}

/// Same matches as `filter_row_ids_str`, written into a reused buffer.
pub fn filter_row_ids_str_into(
    out: &mut Vec<usize>,
    ids: &Vec<usize>,
    col: &Vec<String>,
    key: &String,
)
    requires
        forall|t: int| 0 <= t < ids@.len() ==> ids@[t] < col@.len(),
    ensures
        final(out)@ == filter_match(ids@, key_views(col@), key@, ids@.len() as int),
{
    out.clear();
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(out@ =~= Seq::<usize>::empty());
        assert(ids@.len() == ids.len() as int);
        assert(col@.len() == col.len() as int);
        assert(filter_match(ids@, key_views(col@), key@, 0) =~= Seq::<usize>::empty());
    }
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            col@.len() == col.len() as int,
            forall|u: int| 0 <= u < ids@.len() ==> ids@[u] < col@.len(),
            out@ == filter_match(ids@, key_views(col@), key@, t as int),
        decreases ids.len() - t,
    {
        let id = ids[t];
        proof {
            assert(id == ids@[t as int]);
            assert(id < col@.len());
            lemma_key_view_at(col@, id as int);
        }
        let ghost old_out = out@;
        if col[id] == *key {
            out.push(id);
            proof {
                assert(col@[id as int]@ == key@);
                assert(key_views(col@)[id as int] == key@);
                assert(out@ == old_out.push(id));
                assert(out@ == filter_match(ids@, key_views(col@), key@, t as int + 1));
            }
        } else {
            proof {
                assert(col@[id as int]@ != key@);
                assert(out@ == filter_match(ids@, key_views(col@), key@, t as int + 1));
            }
        }
        t = t + 1;
    }
}

pub open spec fn ids_u32_eq(ids: Seq<usize>, col: Seq<u32>, year: u32, t: int) -> Seq<usize>
    decreases t,
{
    if t <= 0 {
        Seq::<usize>::empty()
    } else {
        let prev = ids_u32_eq(ids, col, year, t - 1);
        if 0 <= t - 1 < ids.len() {
            let j = ids[t - 1];
            if 0 <= (j as int) < col.len() && col[j as int] == year {
                prev.push(j)
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

pub fn filter_ids_u32(ids: &Vec<usize>, col: &Vec<u32>, year: u32) -> (out: Vec<usize>)
    requires
        forall|t: int| 0 <= t < ids@.len() ==> ids@[t] < col@.len(),
    ensures
        out@ == ids_u32_eq(ids@, col@, year, ids@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(ids@.len() == ids.len() as int);
        assert(col@.len() == col.len() as int);
        assert(ids_u32_eq(ids@, col@, year, 0) =~= Seq::<usize>::empty());
    }
    let mut out: Vec<usize> = Vec::new();
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            col@.len() == col.len() as int,
            forall|u: int| 0 <= u < ids@.len() ==> ids@[u] < col@.len(),
            out@ == ids_u32_eq(ids@, col@, year, t as int),
        decreases ids.len() - t,
    {
        let id = ids[t];
        proof {
            assert(id == ids@[t as int]);
            assert(id < col@.len());
        }
        let ghost old_out = out@;
        if col[id] == year {
            out.push(id);
            proof {
                assert(col@[id as int] == year);
                assert(out@ == old_out.push(id));
                assert(out@ == ids_u32_eq(ids@, col@, year, t as int + 1));
            }
        } else {
            proof {
                assert(col@[id as int] != year);
                assert(out@ == ids_u32_eq(ids@, col@, year, t as int + 1));
            }
        }
        t = t + 1;
    }
    out
}

pub open spec fn ids_u32_between(ids: Seq<usize>, col: Seq<u32>, lo: u32, hi: u32, t: int) -> Seq<usize>
    decreases t,
{
    if t <= 0 {
        Seq::<usize>::empty()
    } else {
        let prev = ids_u32_between(ids, col, lo, hi, t - 1);
        if 0 <= t - 1 < ids.len() {
            let j = ids[t - 1];
            if 0 <= (j as int) < col.len() && lo <= col[j as int] && col[j as int] <= hi {
                prev.push(j)
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

pub fn filter_ids_u32_between(
    ids: &Vec<usize>,
    col: &Vec<u32>,
    lo: u32,
    hi: u32,
) -> (out: Vec<usize>)
    requires
        forall|t: int| 0 <= t < ids@.len() ==> ids@[t] < col@.len(),
        lo <= hi,
    ensures
        out@ == ids_u32_between(ids@, col@, lo, hi, ids@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(ids@.len() == ids.len() as int);
        assert(col@.len() == col.len() as int);
        assert(ids_u32_between(ids@, col@, lo, hi, 0) =~= Seq::<usize>::empty());
    }
    let mut out: Vec<usize> = Vec::new();
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            col@.len() == col.len() as int,
            forall|u: int| 0 <= u < ids@.len() ==> ids@[u] < col@.len(),
            lo <= hi,
            out@ == ids_u32_between(ids@, col@, lo, hi, t as int),
        decreases ids.len() - t,
    {
        let id = ids[t];
        proof {
            assert(id == ids@[t as int]);
            assert(id < col@.len());
        }
        let ghost old_out = out@;
        if lo <= col[id] && col[id] <= hi {
            out.push(id);
            proof {
                assert(lo <= col@[id as int] && col@[id as int] <= hi);
                assert(out@ == old_out.push(id));
                assert(out@ == ids_u32_between(ids@, col@, lo, hi, t as int + 1));
            }
        } else {
            proof {
                assert(!(lo <= col@[id as int] && col@[id as int] <= hi));
                assert(out@ == ids_u32_between(ids@, col@, lo, hi, t as int + 1));
            }
        }
        t = t + 1;
    }
    out
}

pub fn filter_ids_ascii_lit(ids: &Vec<usize>, col: &Vec<String>, lit: &str) -> (out: Vec<usize>)
    requires
        forall|t: int| 0 <= t < ids@.len() ==> ids@[t] < col@.len(),
        forall|j: int| 0 <= j < col@.len() ==> col@[j]@.len() <= 512,
    ensures
        out@ == filter_match(ids@, key_views(col@), lit@, ids@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(ids@.len() == ids.len() as int);
        assert(col@.len() == col.len() as int);
        assert(filter_match(ids@, key_views(col@), lit@, 0) =~= Seq::<usize>::empty());
    }
    let mut out: Vec<usize> = Vec::new();
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            col@.len() == col.len() as int,
            forall|u: int| 0 <= u < ids@.len() ==> ids@[u] < col@.len(),
            forall|j: int| 0 <= j < col@.len() ==> col@[j]@.len() <= 512,
            out@ == filter_match(ids@, key_views(col@), lit@, t as int),
        decreases ids.len() - t,
    {
        let id = ids[t];
        proof {
            assert(id == ids@[t as int]);
            assert(id < col.len());
            assert((col@[id as int]@).len() <= 512);
        }
        let cell = col[id].as_str();
        proof {
            assert(cell@ == col@[id as int]@);
            assert(cell@.len() <= 512);
        }
        let hit = eq_ascii_lit(cell, lit);
        let ghost old_out = out@;
        if hit {
            out.push(id);
            proof {
                assert(cell@ == lit@);
                assert(key_views(col@)[id as int] == lit@);
                assert(out@ == old_out.push(id));
                assert(out@ == filter_match(ids@, key_views(col@), lit@, t as int + 1));
            }
        } else {
            proof {
                assert(cell@ != lit@);
                assert(key_views(col@)[id as int] != lit@);
                assert(out@ == filter_match(ids@, key_views(col@), lit@, t as int + 1));
            }
        }
        t = t + 1;
    }
    out
}

/// Same as [`filter_ids_u32`], writing into `out` so the caller can reuse the buffer.
pub fn filter_ids_u32_into(out: &mut Vec<usize>, ids: &Vec<usize>, col: &Vec<u32>, year: u32)
    requires
        forall|t: int| 0 <= t < ids@.len() ==> ids@[t] < col@.len(),
    ensures
        final(out)@ == ids_u32_eq(ids@, col@, year, ids@.len() as int),
{
    out.clear();
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(out@ =~= Seq::<usize>::empty());
        assert(ids@.len() == ids.len() as int);
        assert(col@.len() == col.len() as int);
        assert(ids_u32_eq(ids@, col@, year, 0) =~= Seq::<usize>::empty());
    }
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            col@.len() == col.len() as int,
            forall|u: int| 0 <= u < ids@.len() ==> ids@[u] < col@.len(),
            out@ == ids_u32_eq(ids@, col@, year, t as int),
        decreases ids.len() - t,
    {
        let id = ids[t];
        proof {
            assert(id == ids@[t as int]);
            assert(id < col@.len());
        }
        let ghost old_out = out@;
        if col[id] == year {
            out.push(id);
            proof {
                assert(col@[id as int] == year);
                assert(out@ == old_out.push(id));
                assert(out@ == ids_u32_eq(ids@, col@, year, t as int + 1));
            }
        } else {
            proof {
                assert(col@[id as int] != year);
                assert(out@ == ids_u32_eq(ids@, col@, year, t as int + 1));
            }
        }
        t = t + 1;
    }
}

/// Same as [`filter_ids_ascii_lit`], writing into `out` so the caller can reuse the buffer.
pub fn filter_ids_ascii_lit_into(out: &mut Vec<usize>, ids: &Vec<usize>, col: &Vec<String>, lit: &str)
    requires
        forall|t: int| 0 <= t < ids@.len() ==> ids@[t] < col@.len(),
        forall|j: int| 0 <= j < col@.len() ==> col@[j]@.len() <= 512,
    ensures
        final(out)@ == filter_match(ids@, key_views(col@), lit@, ids@.len() as int),
{
    out.clear();
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(out@ =~= Seq::<usize>::empty());
        assert(ids@.len() == ids.len() as int);
        assert(col@.len() == col.len() as int);
        assert(filter_match(ids@, key_views(col@), lit@, 0) =~= Seq::<usize>::empty());
    }
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            col@.len() == col.len() as int,
            forall|u: int| 0 <= u < ids@.len() ==> ids@[u] < col@.len(),
            forall|j: int| 0 <= j < col@.len() ==> col@[j]@.len() <= 512,
            out@ == filter_match(ids@, key_views(col@), lit@, t as int),
        decreases ids.len() - t,
    {
        let id = ids[t];
        proof {
            assert(id == ids@[t as int]);
            assert(id < col.len());
            assert((col@[id as int]@).len() <= 512);
        }
        let cell = col[id].as_str();
        proof {
            assert(cell@ == col@[id as int]@);
            assert(cell@.len() <= 512);
        }
        let hit = eq_ascii_lit(cell, lit);
        let ghost old_out = out@;
        if hit {
            out.push(id);
            proof {
                assert(cell@ == lit@);
                assert(key_views(col@)[id as int] == lit@);
                assert(out@ == old_out.push(id));
                assert(out@ == filter_match(ids@, key_views(col@), lit@, t as int + 1));
            }
        } else {
            proof {
                assert(cell@ != lit@);
                assert(key_views(col@)[id as int] != lit@);
                assert(out@ == filter_match(ids@, key_views(col@), lit@, t as int + 1));
            }
        }
        t = t + 1;
    }
}

/// Equijoin on two string columns (for example `tag` and `version`).
pub fn equijoin_pairs_str2(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
) -> (pairs: Vec<(usize, usize)>)
    requires
        outer0@.len() == outer1@.len(),
        inner0@.len() == inner1@.len(),
    ensures
        pairs@ == nested_eq_pairs2(
            key_views(outer0@),
            key_views(outer1@),
            key_views(inner0@),
            key_views(inner1@),
            outer0@.len() as int,
        ),
{
    let idx = build_eq_index_str(inner0);
    let ghost oa = key_views(outer0@);
    let ghost ob = key_views(outer1@);
    let ghost ia = key_views(inner0@);
    let ghost ib = key_views(inner1@);
    let mut pairs: Vec<(usize, usize)> = Vec::new();
    let mut i: usize = 0;
    while i < outer0.len()
        invariant
            i <= outer0.len(),
            outer0@.len() == outer0.len() as int,
            outer1@.len() == outer0@.len(),
            inner0@.len() == inner0.len() as int,
            inner1@.len() == inner0@.len(),
            oa == key_views(outer0@),
            ob == key_views(outer1@),
            ia == key_views(inner0@),
            ib == key_views(inner1@),
            index_ok(ia, idx.buckets@, idx.map@, inner0@.len() as int),
            pairs@ == nested_eq_pairs2(oa, ob, ia, ib, i as int),
        decreases outer0.len() - i,
    {
        let key0 = outer0[i].clone();
        let key1 = outer1[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer0@, end);
            lemma_key_view_at(outer1@, end);
            assert(oa[end] == key0@);
            assert(ob[end] == key1@);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            broadcast use vstd::seq::lemma_seq_new_len;
            assert(inner0@.len() == inner0.len() as int);
            assert(ia.len() == inner0@.len());
            assert(ia.len() as int <= usize::MAX as int);
        }
        let ghost before = pairs@;
        let present = idx.map.contains_key(key0.as_str());
        if present {
            let got = idx.map.get(key0.as_str());
            let bi = *got.unwrap();
            proof {
                assert(idx.map@.contains_key(key0@));
                lemma_index_bucket(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_bounded(ia, key0@, ia.len() as int);
            }
            let ids = &idx.buckets[bi];
            let filtered = filter_row_ids_str(ids, inner1, &key1);
            push_prefix_pairs(&mut pairs, i, &filtered);
            proof {
                lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                assert(filtered@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                lemma_nested_eq_pairs2_step(oa, ob, ia, ib, end + 1);
                assert(pairs@ == nested_eq_pairs2(oa, ob, ia, ib, end + 1));
            }
        } else {
            proof {
                assert(!idx.map@.contains_key(key0@));
                lemma_index_absent(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_len0(ia, key0@, ia.len() as int);
                lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                lemma_nested_eq_pairs2_step(oa, ob, ia, ib, end + 1);
                lemma_seq_add_empty(before);
                assert(pairs@ == nested_eq_pairs2(oa, ob, ia, ib, end + 1));
            }
        }
        i = i + 1;
    }
    pairs
}

// SHAPE_TWOKEY_END
// SHAPE_STAR_BEGIN
pub open spec fn tag_prefix(i: usize, s: usize, tags: Seq<usize>, t: int) -> Seq<(usize, usize, usize)>
    decreases t,
{
    if t <= 0 {
        Seq::<(usize, usize, usize)>::empty()
    } else {
        let prev = tag_prefix(i, s, tags, t - 1);
        if 0 <= t - 1 < tags.len() {
            prev.push((i, s, tags[t - 1]))
        } else {
            prev
        }
    }
}

pub open spec fn sub_product(
    i: usize,
    subs: Seq<usize>,
    tags: Seq<usize>,
    s_end: int,
) -> Seq<(usize, usize, usize)>
    decreases s_end,
{
    if s_end <= 0 {
        Seq::<(usize, usize, usize)>::empty()
    } else {
        let prev = sub_product(i, subs, tags, s_end - 1);
        if 0 <= s_end - 1 < subs.len() {
            prev + tag_prefix(i, subs[s_end - 1], tags, tags.len() as int)
        } else {
            prev
        }
    }
}

/// Forward nested star: each outer row with every sub match and every two-key tag match.
pub open spec fn nested_star(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    n: int,
) -> Seq<(usize, usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize, usize)>::empty()
    } else if n - 1 >= pre_a.len() {
        nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n - 1)
    } else {
        let i = (n - 1) as usize;
        let subs = eq_row_ids(sub_a, pre_a[n - 1], sub_a.len() as int);
        let tags = eq_row_ids2(tag_t, tag_v, pre_t[n - 1], pre_v[n - 1], tag_t.len() as int);
        nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n - 1) + sub_product(
            i,
            subs,
            tags,
            subs.len() as int,
        )
    }
}

pub proof fn lemma_tag_prefix_step(i: usize, s: usize, tags: Seq<usize>, t: int)
    requires
        0 <= t < tags.len(),
    ensures
        tag_prefix(i, s, tags, t + 1) == tag_prefix(i, s, tags, t).push((i, s, tags[t])),
{
    assert(tag_prefix(i, s, tags, t + 1) == tag_prefix(i, s, tags, t).push((i, s, tags[t])));
}

pub proof fn lemma_sub_product_step(i: usize, subs: Seq<usize>, tags: Seq<usize>, s: int)
    requires
        0 <= s < subs.len(),
    ensures
        sub_product(i, subs, tags, s + 1) == sub_product(i, subs, tags, s) + tag_prefix(
            i,
            subs[s],
            tags,
            tags.len() as int,
        ),
{
    assert(sub_product(i, subs, tags, s + 1) == sub_product(i, subs, tags, s) + tag_prefix(
        i,
        subs[s],
        tags,
        tags.len() as int,
    ));
}

pub proof fn lemma_seq_add_push<A>(a: Seq<A>, b: Seq<A>, x: A)
    ensures
        (a + b).push(x) == a + b.push(x),
{
    broadcast use vstd::seq::group_seq_lemmas;

    assert((a + b).push(x) =~= a + b.push(x));
}

pub proof fn lemma_seq_add_assoc<A>(a: Seq<A>, b: Seq<A>, c: Seq<A>)
    ensures
        (a + b) + c == a + (b + c),
{
    broadcast use vstd::seq::group_seq_lemmas;

    assert((a + b) + c =~= a + (b + c));
}

pub proof fn lemma_nested_star_step(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    n: int,
)
    requires
        0 < n <= pre_a.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        tag_t.len() == tag_v.len(),
    ensures
        nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n) == nested_star(
            pre_a,
            pre_t,
            pre_v,
            sub_a,
            tag_t,
            tag_v,
            n - 1,
        ) + sub_product(
            (n - 1) as usize,
            eq_row_ids(sub_a, pre_a[n - 1], sub_a.len() as int),
            eq_row_ids2(tag_t, tag_v, pre_t[n - 1], pre_v[n - 1], tag_t.len() as int),
            eq_row_ids(sub_a, pre_a[n - 1], sub_a.len() as int).len() as int,
        ),
{
    assert(nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n) == nested_star(
        pre_a,
        pre_t,
        pre_v,
        sub_a,
        tag_t,
        tag_v,
        n - 1,
    ) + sub_product(
        (n - 1) as usize,
        eq_row_ids(sub_a, pre_a[n - 1], sub_a.len() as int),
        eq_row_ids2(tag_t, tag_v, pre_t[n - 1], pre_v[n - 1], tag_t.len() as int),
        eq_row_ids(sub_a, pre_a[n - 1], sub_a.len() as int).len() as int,
    ));
}

pub fn push_star_product(
    out: &mut Vec<(usize, usize, usize)>,
    i: usize,
    subs: &Vec<usize>,
    tags: &Vec<usize>,
)
    ensures
        final(out)@ == old(out)@ + sub_product(i, subs@, tags@, subs@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(subs@.len() == subs.len() as int);
        assert(tags@.len() == tags.len() as int);
    }
    let ghost base = out@;
    proof {
        assert(sub_product(i, subs@, tags@, 0) =~= Seq::<(usize, usize, usize)>::empty());
        lemma_seq_add_empty(base);
        assert(out@ == base + sub_product(i, subs@, tags@, 0));
    }
    let mut s: usize = 0;
    while s < subs.len()
        invariant
            s <= subs.len(),
            subs@.len() == subs.len() as int,
            tags@.len() == tags.len() as int,
            out@ == base + sub_product(i, subs@, tags@, s as int),
        decreases subs.len() - s,
    {
        let sid = subs[s];
        let ghost at_sub = out@;
        proof {
            assert(sid == subs@[s as int]);
            assert(at_sub == base + sub_product(i, subs@, tags@, s as int));
            lemma_seq_add_empty(at_sub);
            assert(tag_prefix(i, sid, tags@, 0) =~= Seq::<(usize, usize, usize)>::empty());
            assert(out@ == at_sub + tag_prefix(i, sid, tags@, 0));
        }
        let mut t: usize = 0;
        while t < tags.len()
            invariant
                t <= tags.len(),
                s < subs.len(),
                subs@.len() == subs.len() as int,
                tags@.len() == tags.len() as int,
                sid == subs@[s as int],
                at_sub == base + sub_product(i, subs@, tags@, s as int),
                out@ == at_sub + tag_prefix(i, sid, tags@, t as int),
            decreases tags.len() - t,
        {
            let tid = tags[t];
            let ghost old_out = out@;
            out.push((i, sid, tid));
            proof {
                assert(tid == tags@[t as int]);
                lemma_tag_prefix_step(i, sid, tags@, t as int);
                assert(out@ == old_out.push((i, sid, tags@[t as int])));
                lemma_seq_add_push(at_sub, tag_prefix(i, sid, tags@, t as int), (i, sid, tags@[t as int]));
                assert(out@ == at_sub + tag_prefix(i, sid, tags@, t as int + 1));
            }
            t = t + 1;
        }
        proof {
            assert(out@ == at_sub + tag_prefix(i, sid, tags@, tags@.len() as int));
            lemma_sub_product_step(i, subs@, tags@, s as int);
            assert(sub_product(i, subs@, tags@, s as int + 1) == sub_product(i, subs@, tags@, s as int)
                + tag_prefix(i, sid, tags@, tags@.len() as int));
            lemma_seq_add_assoc(
                base,
                sub_product(i, subs@, tags@, s as int),
                tag_prefix(i, sid, tags@, tags@.len() as int),
            );
            assert(out@ == base + sub_product(i, subs@, tags@, s as int + 1));
        }
        s = s + 1;
    }
    proof {
        assert(out@ == base + sub_product(i, subs@, tags@, subs@.len() as int));
    }
}

/// Star equijoin: `pre.adsh = sub.adsh` and `pre.tag = tag.tag AND pre.version = tag.version`.
pub fn star_eq_triples_str(
    pre_adsh: &Vec<String>,
    pre_tag: &Vec<String>,
    pre_ver: &Vec<String>,
    sub_adsh: &Vec<String>,
    tag_tag: &Vec<String>,
    tag_ver: &Vec<String>,
) -> (triples: Vec<(usize, usize, usize)>)
    requires
        pre_adsh@.len() == pre_tag@.len(),
        pre_adsh@.len() == pre_ver@.len(),
        tag_tag@.len() == tag_ver@.len(),
    ensures
        triples@ == nested_star(
            key_views(pre_adsh@),
            key_views(pre_tag@),
            key_views(pre_ver@),
            key_views(sub_adsh@),
            key_views(tag_tag@),
            key_views(tag_ver@),
            pre_adsh@.len() as int,
        ),
{
    let idx_sub = build_eq_index_str(sub_adsh);
    let idx_tag = build_eq_index_str(tag_tag);
    let ghost pa = key_views(pre_adsh@);
    let ghost pt = key_views(pre_tag@);
    let ghost pv = key_views(pre_ver@);
    let ghost sa = key_views(sub_adsh@);
    let ghost tt = key_views(tag_tag@);
    let ghost tv = key_views(tag_ver@);
    let mut triples: Vec<(usize, usize, usize)> = Vec::new();
    let mut i: usize = 0;
    while i < pre_adsh.len()
        invariant
            i <= pre_adsh.len(),
            pre_adsh@.len() == pre_adsh.len() as int,
            pre_adsh@.len() == pre_tag@.len(),
            pre_adsh@.len() == pre_ver@.len(),
            pre_tag@.len() == pre_tag.len() as int,
            pre_ver@.len() == pre_ver.len() as int,
            sub_adsh@.len() == sub_adsh.len() as int,
            tag_tag@.len() == tag_tag.len() as int,
            tag_ver@.len() == tag_ver.len() as int,
            tag_tag@.len() == tag_ver@.len(),
            pa == key_views(pre_adsh@),
            pt == key_views(pre_tag@),
            pv == key_views(pre_ver@),
            sa == key_views(sub_adsh@),
            tt == key_views(tag_tag@),
            tv == key_views(tag_ver@),
            index_ok(sa, idx_sub.buckets@, idx_sub.map@, sub_adsh@.len() as int),
            index_ok(tt, idx_tag.buckets@, idx_tag.map@, tag_tag@.len() as int),
            triples@ == nested_star(pa, pt, pv, sa, tt, tv, i as int),
        decreases pre_adsh.len() - i,
    {
        let key_a = pre_adsh[i].clone();
        let key_t = pre_tag[i].clone();
        let key_v = pre_ver[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(pre_adsh@, end);
            lemma_key_view_at(pre_tag@, end);
            lemma_key_view_at(pre_ver@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            broadcast use vstd::seq::lemma_seq_new_len;
            assert(pa[end] == key_a@);
            assert(pt[end] == key_t@);
            assert(pv[end] == key_v@);
            assert(sa.len() == sub_adsh@.len());
            assert(tt.len() == tag_tag@.len());
            assert(tv.len() == tag_ver@.len());
            assert(sa.len() as int <= usize::MAX as int);
            assert(tt.len() as int <= usize::MAX as int);
        }
        let present_a = idx_sub.map.contains_key(key_a.as_str());
        let present_t = idx_tag.map.contains_key(key_t.as_str());
        if present_a {
            let got_a = idx_sub.map.get(key_a.as_str());
            let bi_a = *got_a.unwrap();
            proof {
                assert(idx_sub.map@.contains_key(key_a@));
                lemma_index_bucket(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                assert((bi_a as int) < idx_sub.buckets@.len());
            }
            let sub_ids = &idx_sub.buckets[bi_a];
            if present_t {
                let got_t = idx_tag.map.get(key_t.as_str());
                let bi_t = *got_t.unwrap();
                proof {
                    assert(idx_tag.map@.contains_key(key_t@));
                    lemma_index_bucket(tt, idx_tag.buckets@, idx_tag.map@, tt.len() as int, key_t@);
                    lemma_eq_row_ids_bounded(tt, key_t@, tt.len() as int);
                    assert((bi_t as int) < idx_tag.buckets@.len());
                }
                let tag_bucket = &idx_tag.buckets[bi_t];
                let tags = filter_row_ids_str(tag_bucket, tag_ver, &key_v);
                let ghost before = triples@;
                push_star_product(&mut triples, i, sub_ids, &tags);
                proof {
                    lemma_filter_is_ids2(tt, tv, key_t@, key_v@, tt.len() as int);
                    assert(sub_ids@ == eq_row_ids(sa, pa[end], sa.len() as int));
                    assert(tags@ == eq_row_ids2(tt, tv, pt[end], pv[end], tt.len() as int));
                    lemma_nested_star_step(pa, pt, pv, sa, tt, tv, end + 1);
                    assert(triples@ == before + sub_product(i, sub_ids@, tags@, sub_ids@.len() as int));
                    assert(triples@ == nested_star(pa, pt, pv, sa, tt, tv, end + 1));
                }
            } else {
                let tags: Vec<usize> = Vec::new();
                let ghost before = triples@;
                push_star_product(&mut triples, i, sub_ids, &tags);
                proof {
                    assert(!idx_tag.map@.contains_key(key_t@));
                    lemma_index_absent(tt, idx_tag.buckets@, idx_tag.map@, tt.len() as int, key_t@);
                    lemma_eq_row_ids_len0(tt, key_t@, tt.len() as int);
                    lemma_filter_is_ids2(tt, tv, key_t@, key_v@, tt.len() as int);
                    assert(eq_row_ids2(tt, tv, pt[end], pv[end], tt.len() as int) =~= Seq::<usize>::empty());
                    assert(tags@ == eq_row_ids2(tt, tv, pt[end], pv[end], tt.len() as int));
                    assert(sub_ids@ == eq_row_ids(sa, pa[end], sa.len() as int));
                    lemma_nested_star_step(pa, pt, pv, sa, tt, tv, end + 1);
                    assert(triples@ == before + sub_product(i, sub_ids@, tags@, sub_ids@.len() as int));
                    assert(triples@ == nested_star(pa, pt, pv, sa, tt, tv, end + 1));
                }
            }
        } else {
            let sub_ids: Vec<usize> = Vec::new();
            let tags: Vec<usize> = Vec::new();
            let ghost before = triples@;
            push_star_product(&mut triples, i, &sub_ids, &tags);
            proof {
                assert(!idx_sub.map@.contains_key(key_a@));
                lemma_index_absent(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                lemma_eq_row_ids_len0(sa, key_a@, sa.len() as int);
                assert(eq_row_ids(sa, pa[end], sa.len() as int) =~= Seq::<usize>::empty());
                assert(sub_ids@ == eq_row_ids(sa, pa[end], sa.len() as int));
                assert(sub_product(i, sub_ids@, tags@, 0) =~= Seq::<(usize, usize, usize)>::empty());
                lemma_nested_star_step(pa, pt, pv, sa, tt, tv, end + 1);
                assert(sub_product(
                    i,
                    eq_row_ids(sa, pa[end], sa.len() as int),
                    eq_row_ids2(tt, tv, pt[end], pv[end], tt.len() as int),
                    0,
                ) =~= Seq::<(usize, usize, usize)>::empty());
                assert(triples@ == before + sub_product(i, sub_ids@, tags@, sub_ids@.len() as int));
                assert(triples@ == nested_star(pa, pt, pv, sa, tt, tv, end + 1));
            }
        }
        i = i + 1;
    }
    triples
}


// SHAPE_STAR_END
/// How many ids in `ids[0..t]` are strictly below `bound`.
pub open spec fn ids_lt(ids: Seq<usize>, t: int, bound: int) -> int
    decreases t,
{
    if t <= 0 {
        0
    } else {
        let prev = ids_lt(ids, t - 1, bound);
        if 0 <= t - 1 < ids.len() && (ids[t - 1] as int) < bound {
            prev + 1
        } else {
            prev
        }
    }
}

pub open spec fn pair_pos<K>(outer: Seq<K>, inner: Seq<K>, i0: int, i1: int) -> int {
    if !(0 <= i0 < outer.len()) {
        nested_eq_pairs(outer, inner, i0).len() as int
    } else {
        let ids = eq_row_ids(inner, outer[i0], inner.len() as int);
        nested_eq_pairs(outer, inner, i0).len() as int + ids_lt(ids, ids.len() as int, i1)
    }
}

pub open spec fn loop_acc<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int, int) -> A,
    base: A,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
) -> A
    decreases n_outer - i0, n_inner - i1,
{
    if i0 < n_outer {
        if i1 < n_inner {
            let tail = loop_acc(outer, inner, step, base, n_outer, n_inner, i0, i1 + 1);
            if 0 <= i0 < outer.len() && 0 <= i1 < inner.len() && outer[i0] == inner[i1] {
                step(tail, i0, i1)
            } else {
                tail
            }
        } else {
            loop_acc(outer, inner, step, base, n_outer, n_inner, i0 + 1, 0)
        }
    } else {
        base
    }
}

pub open spec fn pair_acc<A>(
    pairs: Seq<(usize, usize)>,
    step: spec_fn(A, int, int) -> A,
    base: A,
    k: int,
) -> A
    decreases pairs.len() - k,
{
    if k >= pairs.len() {
        base
    } else {
        let tail = pair_acc(pairs, step, base, k + 1);
        step(tail, pairs[k].0 as int, pairs[k].1 as int)
    }
}

pub proof fn lemma_prefix_len(i: usize, ids: Seq<usize>, t: int)
    requires
        0 <= t <= ids.len(),
    ensures
        prefix_pairs(i, ids, t).len() == t,
    decreases t,
{
    if t > 0 {
        lemma_prefix_len(i, ids, t - 1);
        assert(prefix_pairs(i, ids, t) == prefix_pairs(i, ids, t - 1).push((i, ids[t - 1])));
    }
}

pub proof fn lemma_ids_lt_skip(ids: Seq<usize>, t: int, bound: int)
    requires
        0 <= t <= ids.len(),
        forall|p: int| 0 <= p < t ==> (#[trigger] ids[p] as int) != bound,
    ensures
        ids_lt(ids, t, bound) == ids_lt(ids, t, bound + 1),
    decreases t,
{
    if t > 0 {
        lemma_ids_lt_skip(ids, t - 1, bound);
        let id = ids[t - 1] as int;
        if id < bound {
            assert(id < bound + 1);
        } else {
            assert(id >= bound + 1);
        }
    }
}

pub proof fn lemma_ids_lt_all(ids: Seq<usize>, t: int, bound: int)
    requires
        0 <= t <= ids.len(),
        forall|p: int| 0 <= p < t ==> (#[trigger] ids[p] as int) < bound,
    ensures
        ids_lt(ids, t, bound) == t,
    decreases t,
{
    if t > 0 {
        lemma_ids_lt_all(ids, t - 1, bound);
        assert((ids[t - 1] as int) < bound);
    }
}

pub proof fn lemma_eq_members<K>(keys: Seq<K>, k: K, end: int)
    requires
        0 <= end <= keys.len(),
        end <= usize::MAX as int,
    ensures
        forall|p: int|
            0 <= p < eq_row_ids(keys, k, end).len() ==> {
                let row = #[trigger] eq_row_ids(keys, k, end)[p] as int;
                0 <= row < end && keys[row] == k
            },
    decreases end,
{
    if end > 0 {
        assert(0 <= end - 1 <= usize::MAX as int);
        lemma_eq_members(keys, k, end - 1);
        let prev = eq_row_ids(keys, k, end - 1);
        let cur = eq_row_ids(keys, k, end);
        if 0 <= end - 1 < keys.len() {
            if keys[end - 1] == k {
                let row = (end - 1) as usize;
                assert(row as int == end - 1);
                assert(cur == prev.push(row));
                assert forall|p: int| 0 <= p < cur.len() implies ({
                    let r = #[trigger] cur[p] as int;
                    0 <= r < end && keys[r] == k
                }) by {
                    if p < prev.len() {
                        assert(cur[p] == prev[p]);
                    } else {
                        assert(cur[p] == row);
                    }
                };
            } else {
                assert(cur == prev);
            }
        } else {
            assert(cur == prev);
        }
    }
}

pub proof fn lemma_ids_lt_push_prefix(s: Seq<usize>, x: usize, t: int, bound: int)
    requires
        0 <= t <= s.len(),
    ensures
        ids_lt(s.push(x), t, bound) == ids_lt(s, t, bound),
    decreases t,
{
    if t > 0 {
        lemma_ids_lt_push_prefix(s, x, t - 1, bound);
        assert(s.push(x)[t - 1] == s[t - 1]);
    }
}

pub proof fn lemma_eq_rank<K>(keys: Seq<K>, k: K, end: int, row: int)
    requires
        0 <= row < end <= keys.len(),
        keys[row] == k,
        end <= usize::MAX as int,
    ensures
        ({
            let ids = eq_row_ids(keys, k, end);
            let r = ids_lt(ids, ids.len() as int, row);
            &&& 0 <= r < ids.len()
            &&& ids[r] as int == row
            &&& ids_lt(ids, ids.len() as int, row + 1) == r + 1
        }),
    decreases end - row,
{
    let prev = eq_row_ids(keys, k, end - 1);
    let cur = eq_row_ids(keys, k, end);
    if end == row + 1 {
        let pushed = (end - 1) as usize;
        assert(0 <= end - 1 <= usize::MAX as int);
        assert(pushed as int == end - 1);
        assert(cur == prev.push(pushed));
        lemma_eq_members(keys, k, row);
        lemma_ids_lt_all(prev, prev.len() as int, row);
        lemma_ids_lt_all(prev, prev.len() as int, row + 1);
        lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row);
        lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row + 1);
        assert(ids_lt(cur, prev.len() as int, row) == prev.len() as int);
        assert(ids_lt(cur, prev.len() as int, row + 1) == prev.len() as int);
        assert((pushed as int) < row + 1);
        assert(cur.len() == prev.len() + 1);
        assert(ids_lt(cur, cur.len() as int, row) == prev.len() as int);
        assert(ids_lt(cur, cur.len() as int, row + 1) == prev.len() as int + 1);
        assert(cur[prev.len() as int] == pushed);
    } else {
        lemma_eq_rank(keys, k, end - 1, row);
        let pushed = (end - 1) as usize;
        assert(0 <= end - 1 <= usize::MAX as int);
        assert(pushed as int == end - 1);
        assert(pushed as int > row);
        if 0 <= end - 1 < keys.len() {
            if keys[end - 1] == k {
                assert(cur == prev.push(pushed));
                lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row);
                lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row + 1);
                let r = ids_lt(prev, prev.len() as int, row);
                assert(cur[r] == prev[r]);
            } else {
                assert(cur == prev);
            }
        } else {
            assert(cur == prev);
        }
    }
}

pub proof fn lemma_prefix_at(i: usize, ids: Seq<usize>, t: int, p: int)
    requires
        0 <= p < t <= ids.len(),
    ensures
        prefix_pairs(i, ids, t)[p] == (i, ids[p]),
    decreases t,
{
    lemma_prefix_len(i, ids, t - 1);
    if p < t - 1 {
        lemma_prefix_at(i, ids, t - 1, p);
        assert(prefix_pairs(i, ids, t) == prefix_pairs(i, ids, t - 1).push((i, ids[t - 1])));
        assert(prefix_pairs(i, ids, t)[p] == prefix_pairs(i, ids, t - 1)[p]);
    } else {
        assert(prefix_pairs(i, ids, t) == prefix_pairs(i, ids, t - 1).push((i, ids[t - 1])));
        assert(prefix_pairs(i, ids, t)[p] == (i, ids[t - 1]));
    }
}

pub proof fn lemma_left_index<A>(a: Seq<A>, b: Seq<A>, p: int)
    requires
        0 <= p < a.len(),
    ensures
        (a + b)[p] == a[p],
{
    assert((a + b)[p] == a[p]);
}

pub proof fn lemma_right_index<A>(a: Seq<A>, b: Seq<A>, p: int)
    requires
        0 <= p < b.len(),
    ensures
        (a + b)[a.len() + p] == b[p],
{
    assert((a + b)[a.len() + p] == b[p]);
}

pub proof fn lemma_ids_lt_zero(ids: Seq<usize>, t: int)
    requires
        0 <= t <= ids.len(),
    ensures
        ids_lt(ids, t, 0) == 0,
    decreases t,
{
    if t > 0 {
        lemma_ids_lt_zero(ids, t - 1);
        assert(0 <= (ids[t - 1] as int));
    }
}

pub proof fn lemma_nested_len_mono<K>(outer: Seq<K>, inner: Seq<K>, n: int, m: int)
    requires
        0 <= n <= m,
    ensures
        nested_eq_pairs(outer, inner, n).len() <= nested_eq_pairs(outer, inner, m).len(),
    decreases m - n,
{
    if n < m {
        lemma_nested_len_mono(outer, inner, n, m - 1);
        let cur = nested_eq_pairs(outer, inner, m);
        let prev = nested_eq_pairs(outer, inner, m - 1);
        if m - 1 < outer.len() {
            let ids = eq_row_ids(inner, outer[m - 1], inner.len() as int);
            let extra = prefix_pairs((m - 1) as usize, ids, ids.len() as int);
            assert(cur == prev + extra);
            assert(prev.len() <= cur.len());
        } else {
            assert(cur == prev);
        }
    }
}

pub proof fn lemma_nested_index<K>(outer: Seq<K>, inner: Seq<K>, n: int, m: int, p: int)
    requires
        0 <= n <= m,
        0 <= p < nested_eq_pairs(outer, inner, n).len(),
    ensures
        nested_eq_pairs(outer, inner, m)[p] == nested_eq_pairs(outer, inner, n)[p],
    decreases m - n,
{
    if n < m {
        let cur = nested_eq_pairs(outer, inner, m);
        let prev = nested_eq_pairs(outer, inner, m - 1);
        lemma_nested_len_mono(outer, inner, n, m - 1);
        if m - 1 >= outer.len() {
            assert(cur == prev);
        } else {
            let i = (m - 1) as usize;
            let ids = eq_row_ids(inner, outer[m - 1], inner.len() as int);
            let extra = prefix_pairs(i, ids, ids.len() as int);
            assert(cur == prev + extra);
            assert(p < prev.len());
            lemma_left_index(prev, extra, p);
        }
        lemma_nested_index(outer, inner, n, m - 1, p);
    }
}

pub proof fn lemma_acc<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int, int) -> A,
    base: A,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
)
    requires
        outer.len() == n_outer,
        inner.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
        0 <= i0 <= n_outer,
        0 <= i1 <= n_inner,
    ensures
        loop_acc(outer, inner, step, base, n_outer, n_inner, i0, i1) == pair_acc(
            nested_eq_pairs(outer, inner, n_outer),
            step,
            base,
            pair_pos(outer, inner, i0, i1),
        ),
    decreases n_outer - i0, n_inner - i1,
{
    let pairs = nested_eq_pairs(outer, inner, n_outer);
    let pos = pair_pos(outer, inner, i0, i1);
    if i0 >= n_outer {
        assert(nested_eq_pairs(outer, inner, i0) =~= pairs);
        assert(pos == pairs.len() as int);
    } else if i1 >= n_inner {
        lemma_acc(outer, inner, step, base, n_outer, n_inner, i0 + 1, 0);
        let ids = eq_row_ids(inner, outer[i0], n_inner);
        lemma_eq_members(inner, outer[i0], n_inner);
        assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < n_inner by {
            assert(0 <= (ids[p] as int) < n_inner);
        };
        assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < i1 by {
            assert((ids[p] as int) < n_inner);
            assert(n_inner <= i1);
        };
        lemma_ids_lt_all(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_len(i0u, ids, ids.len() as int);
        assert(nested_eq_pairs(outer, inner, i0 + 1).len() == nested_eq_pairs(outer, inner, i0).len() + ids.len());
        if i0 + 1 < outer.len() {
            let next_ids = eq_row_ids(inner, outer[i0 + 1], n_inner);
            lemma_ids_lt_zero(next_ids, next_ids.len() as int);
        }
        assert(pair_pos(outer, inner, i0 + 1, 0) == pos);
    } else if outer[i0] == inner[i1] {
        lemma_acc(outer, inner, step, base, n_outer, n_inner, i0, i1 + 1);
        lemma_eq_rank(inner, outer[i0], n_inner, i1);
        let ids = eq_row_ids(inner, outer[i0], n_inner);
        let r = ids_lt(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_len(i0u, ids, ids.len() as int);
        lemma_prefix_at(i0u, ids, ids.len() as int, r);
        let row_pairs = prefix_pairs(i0u, ids, ids.len() as int);
        let earlier = nested_eq_pairs(outer, inner, i0);
        let through = nested_eq_pairs(outer, inner, i0 + 1);
        assert(through == earlier + row_pairs);
        assert(i1 as int <= usize::MAX as int);
        let i1u = i1 as usize;
        assert(i1u as int == i1);
        assert(row_pairs[r] == (i0u, i1u));
        assert(0 <= r < row_pairs.len());
        lemma_right_index(earlier, row_pairs, r);
        assert(pos == earlier.len() as int + r);
        assert(through.len() == earlier.len() + row_pairs.len());
        assert(pos < through.len());
        lemma_nested_len_mono(outer, inner, i0 + 1, n_outer);
        assert(through.len() <= pairs.len());
        assert(pos < pairs.len());
        lemma_nested_index(outer, inner, i0 + 1, n_outer, pos);
        assert(through[pos] == (i0u, i1u));
        assert(pairs[pos] == (i0u, i1u));
        assert(pos + 1 == pair_pos(outer, inner, i0, i1 + 1));
        assert(loop_acc(outer, inner, step, base, n_outer, n_inner, i0, i1) == step(
            loop_acc(outer, inner, step, base, n_outer, n_inner, i0, i1 + 1),
            i0,
            i1,
        ));
        assert(pair_acc(pairs, step, base, pos) == step(pair_acc(pairs, step, base, pos + 1), i0, i1));
    } else {
        lemma_acc(outer, inner, step, base, n_outer, n_inner, i0, i1 + 1);
        let ids = eq_row_ids(inner, outer[i0], n_inner);
        lemma_eq_members(inner, outer[i0], n_inner);
        assert forall|p: int| 0 <= p < ids.len() implies (#[trigger] ids[p] as int) != i1 by {
            assert(inner[(ids[p] as int)] == outer[i0]);
        };
        lemma_ids_lt_skip(ids, ids.len() as int, i1);
        assert(pos == pair_pos(outer, inner, i0, i1 + 1));
    }
}


// SHAPE_TWOKEY_BEGIN
/// Rank of `row` in a two-column id list.
pub proof fn lemma_eq2_members<A, B>(a: Seq<A>, b: Seq<B>, ka: A, kb: B, end: int)
    requires
        0 <= end <= a.len(),
        end <= b.len(),
        end <= usize::MAX as int,
    ensures
        forall|p: int|
            0 <= p < eq_row_ids2(a, b, ka, kb, end).len() ==> {
                let row = #[trigger] eq_row_ids2(a, b, ka, kb, end)[p] as int;
                0 <= row < end && a[row] == ka && b[row] == kb
            },
    decreases end,
{
    if end > 0 {
        assert(0 <= end - 1 <= usize::MAX as int);
        lemma_eq2_members(a, b, ka, kb, end - 1);
        let prev = eq_row_ids2(a, b, ka, kb, end - 1);
        let cur = eq_row_ids2(a, b, ka, kb, end);
        if 0 <= end - 1 < a.len() && end - 1 < b.len() && a[end - 1] == ka && b[end - 1] == kb {
            let row = (end - 1) as usize;
            assert(row as int == end - 1);
            assert(cur == prev.push(row));
            assert forall|p: int| 0 <= p < cur.len() implies ({
                let r = #[trigger] cur[p] as int;
                0 <= r < end && a[r] == ka && b[r] == kb
            }) by {
                if p < prev.len() {
                    assert(cur[p] == prev[p]);
                } else {
                    assert(cur[p] == row);
                }
            };
        } else {
            assert(cur == prev);
        }
    }
}

pub proof fn lemma_eq2_rank<A, B>(a: Seq<A>, b: Seq<B>, ka: A, kb: B, end: int, row: int)
    requires
        0 <= row < end <= a.len(),
        end <= b.len(),
        a[row] == ka,
        b[row] == kb,
        end <= usize::MAX as int,
    ensures
        ({
            let ids = eq_row_ids2(a, b, ka, kb, end);
            let r = ids_lt(ids, ids.len() as int, row);
            &&& 0 <= r < ids.len()
            &&& ids[r] as int == row
            &&& ids_lt(ids, ids.len() as int, row + 1) == r + 1
        }),
    decreases end - row,
{
    let prev = eq_row_ids2(a, b, ka, kb, end - 1);
    let cur = eq_row_ids2(a, b, ka, kb, end);
    if end == row + 1 {
        let pushed = (end - 1) as usize;
        assert(0 <= end - 1 <= usize::MAX as int);
        assert(pushed as int == end - 1);
        assert(cur == prev.push(pushed));
        lemma_eq2_members(a, b, ka, kb, row);
        lemma_ids_lt_all(prev, prev.len() as int, row);
        lemma_ids_lt_all(prev, prev.len() as int, row + 1);
        lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row);
        lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row + 1);
        assert(ids_lt(cur, prev.len() as int, row) == prev.len() as int);
        assert(ids_lt(cur, prev.len() as int, row + 1) == prev.len() as int);
        assert((pushed as int) < row + 1);
        assert(cur.len() == prev.len() + 1);
        assert(ids_lt(cur, cur.len() as int, row) == prev.len() as int);
        assert(ids_lt(cur, cur.len() as int, row + 1) == prev.len() as int + 1);
        assert(cur[prev.len() as int] == pushed);
    } else {
        lemma_eq2_rank(a, b, ka, kb, end - 1, row);
        let pushed = (end - 1) as usize;
        assert(0 <= end - 1 <= usize::MAX as int);
        assert(pushed as int == end - 1);
        assert(pushed as int > row);
        if 0 <= end - 1 < a.len() && end - 1 < b.len() && a[end - 1] == ka && b[end - 1] == kb {
            assert(cur == prev.push(pushed));
            lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row);
            lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row + 1);
            let r = ids_lt(prev, prev.len() as int, row);
            assert(cur[r] == prev[r]);
        } else {
            assert(cur == prev);
        }
    }
}

// SHAPE_TWOKEY_END
// SHAPE_STAR_BEGIN
pub proof fn lemma_tag_prefix_len(i: usize, s: usize, tags: Seq<usize>, t: int)
    requires
        0 <= t <= tags.len(),
    ensures
        tag_prefix(i, s, tags, t).len() == t,
    decreases t,
{
    if t > 0 {
        lemma_tag_prefix_len(i, s, tags, t - 1);
        assert(tag_prefix(i, s, tags, t) == tag_prefix(i, s, tags, t - 1).push((i, s, tags[t - 1])));
    }
}

pub proof fn lemma_tag_prefix_at(i: usize, s: usize, tags: Seq<usize>, t: int, p: int)
    requires
        0 <= p < t <= tags.len(),
    ensures
        tag_prefix(i, s, tags, t)[p] == (i, s, tags[p]),
    decreases t,
{
    lemma_tag_prefix_len(i, s, tags, t - 1);
    if p < t - 1 {
        lemma_tag_prefix_at(i, s, tags, t - 1, p);
        assert(tag_prefix(i, s, tags, t) == tag_prefix(i, s, tags, t - 1).push((i, s, tags[t - 1])));
        assert(tag_prefix(i, s, tags, t)[p] == tag_prefix(i, s, tags, t - 1)[p]);
    } else {
        assert(tag_prefix(i, s, tags, t) == tag_prefix(i, s, tags, t - 1).push((i, s, tags[t - 1])));
        assert(tag_prefix(i, s, tags, t)[p] == (i, s, tags[t - 1]));
    }
}

pub proof fn lemma_sub_product_len(i: usize, subs: Seq<usize>, tags: Seq<usize>, s_end: int)
    requires
        0 <= s_end <= subs.len(),
    ensures
        sub_product(i, subs, tags, s_end).len() == s_end * tags.len(),
    decreases s_end,
{
    if s_end > 0 {
        lemma_sub_product_len(i, subs, tags, s_end - 1);
        lemma_tag_prefix_len(i, subs[s_end - 1], tags, tags.len() as int);
        let prev = sub_product(i, subs, tags, s_end - 1);
        let extra = tag_prefix(i, subs[s_end - 1], tags, tags.len() as int);
        assert(sub_product(i, subs, tags, s_end) == prev + extra);
        assert(prev.len() == (s_end - 1) * tags.len());
        assert(extra.len() == tags.len());
        assert((prev + extra).len() == prev.len() + extra.len());
        assert(prev.len() + extra.len() == s_end * tags.len()) by (nonlinear_arith)
            requires
                prev.len() == (s_end - 1) * tags.len(),
                extra.len() == tags.len(),
        {
        }
        assert(sub_product(i, subs, tags, s_end).len() == prev.len() + extra.len());
        assert(sub_product(i, subs, tags, s_end).len() == s_end * tags.len());
    } else {
        assert(s_end == 0);
        assert(sub_product(i, subs, tags, s_end).len() == 0);
        vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(tags.len() as int);
        assert(0 * (tags.len() as int) == 0);
        assert(s_end * tags.len() == 0);
    }
}

pub open spec fn star_sub(sub_a: Seq<Seq<char>>, key: Seq<char>, i1: int) -> bool {
    &&& 0 <= i1 < sub_a.len()
    &&& sub_a[i1] == key
}

pub open spec fn star_pos(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    i0: int,
    i1: int,
    i2: int,
) -> int {
    if !(0 <= i0 < pre_a.len() && i0 < pre_t.len() && i0 < pre_v.len()) {
        nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0).len() as int
    } else {
        let subs = eq_row_ids(sub_a, pre_a[i0], sub_a.len() as int);
        let tags = eq_row_ids2(tag_t, tag_v, pre_t[i0], pre_v[i0], tag_t.len() as int);
        let sr = ids_lt(subs, subs.len() as int, i1);
        let tr = if star_sub(sub_a, pre_a[i0], i1) {
            ids_lt(tags, tags.len() as int, i2)
        } else {
            0
        };
        nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0).len() as int + sr * (tags.len() as int) + tr
    }
}

pub open spec fn loop_acc3<A>(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    n0: int,
    n1: int,
    n2: int,
    i0: int,
    i1: int,
    i2: int,
) -> A
    decreases n0 - i0, n1 - i1, n2 - i2,
{
    if i0 < n0 {
        if i1 < n1 {
            if i2 < n2 {
                let tail = loop_acc3(
                    pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0, i1, i2 + 1,
                );
                if pre_a[i0] == sub_a[i1] && pre_t[i0] == tag_t[i2] && pre_v[i0] == tag_v[i2] {
                    step(tail, i0, i1, i2)
                } else {
                    tail
                }
            } else {
                loop_acc3(
                    pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0, i1 + 1, 0,
                )
            }
        } else {
            loop_acc3(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0 + 1, 0, 0)
        }
    } else {
        base
    }
}

pub open spec fn triple_acc<A>(
    triples: Seq<(usize, usize, usize)>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    k: int,
) -> A
    decreases triples.len() - k,
{
    if k >= triples.len() {
        base
    } else {
        let tail = triple_acc(triples, step, base, k + 1);
        step(tail, triples[k].0 as int, triples[k].1 as int, triples[k].2 as int)
    }
}

/// Folding `s` with `x` appended equals folding `s` after applying `x` to the base.
/// `triple_acc` walks from the end, so the appended triple is the first step.
pub proof fn lemma_triple_acc_push_at<A>(
    s: Seq<(usize, usize, usize)>,
    x: (usize, usize, usize),
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    k: int,
)
    requires
        0 <= k <= s.len(),
    ensures
        triple_acc(s.push(x), step, base, k) == triple_acc(
            s,
            step,
            step(base, x.0 as int, x.1 as int, x.2 as int),
            k,
        ),
    decreases s.len() - k,
{
    let s2 = s.push(x);
    let b2 = step(base, x.0 as int, x.1 as int, x.2 as int);
    reveal_with_fuel(triple_acc, 1);
    assert(s2.len() == s.len() + 1);
    if k == s.len() {
        assert(k + 1 == s2.len());
        assert(triple_acc(s2, step, base, k + 1) == base);
        lemma_seq_push_index_same(s, x, k);
        assert(s2[k] == x);
        assert(triple_acc(s2, step, base, k) == b2);
        assert(k >= s.len());
        assert(triple_acc(s, step, b2, k) == b2);
    } else {
        lemma_triple_acc_push_at(s, x, step, base, k + 1);
        lemma_seq_push_index_different(s, x, k);
        assert(s2[k] == s[k]);
        assert(triple_acc(s2, step, base, k) == step(
            triple_acc(s2, step, base, k + 1),
            s2[k].0 as int,
            s2[k].1 as int,
            s2[k].2 as int,
        ));
        assert(triple_acc(s, step, b2, k) == step(
            triple_acc(s, step, b2, k + 1),
            s[k].0 as int,
            s[k].1 as int,
            s[k].2 as int,
        ));
    }
}

pub proof fn lemma_nested_star_len_mono(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    n: int,
    m: int,
)
    requires
        0 <= n <= m,
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        tag_t.len() == tag_v.len(),
    ensures
        nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n).len()
            <= nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, m).len(),
    decreases m - n,
{
    if n < m {
        lemma_nested_star_len_mono(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n, m - 1);
        let cur = nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, m);
        let prev = nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, m - 1);
        if m - 1 < pre_a.len() {
            lemma_nested_star_step(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, m);
            assert(prev.len() <= cur.len());
        } else {
            assert(cur == prev);
        }
    }
}

pub proof fn lemma_nested_star_index(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    n: int,
    m: int,
    p: int,
)
    requires
        0 <= n <= m,
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        tag_t.len() == tag_v.len(),
        0 <= p < nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n).len(),
    ensures
        nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, m)[p]
            == nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n)[p],
    decreases m - n,
{
    if n < m {
        let cur = nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, m);
        let prev = nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, m - 1);
        lemma_nested_star_len_mono(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n, m - 1);
        if m - 1 >= pre_a.len() {
            assert(cur == prev);
        } else {
            lemma_nested_star_step(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, m);
            assert(p < prev.len());
            let subs = eq_row_ids(sub_a, pre_a[m - 1], sub_a.len() as int);
            let tags = eq_row_ids2(tag_t, tag_v, pre_t[m - 1], pre_v[m - 1], tag_t.len() as int);
            let extra = sub_product((m - 1) as usize, subs, tags, subs.len() as int);
            lemma_left_index(prev, extra, p);
        }
        lemma_nested_star_index(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n, m - 1, p);
    }
}

pub proof fn lemma_nested_star_past(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    n: int,
)
    requires
        n >= pre_a.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        tag_t.len() == tag_v.len(),
    ensures
        nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n)
            == nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, pre_a.len() as int),
    decreases n - pre_a.len(),
{
    if n > pre_a.len() {
        assert(nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n) == nested_star(
            pre_a,
            pre_t,
            pre_v,
            sub_a,
            tag_t,
            tag_v,
            n - 1,
        ));
        lemma_nested_star_past(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n - 1);
    }
}

pub proof fn lemma_star_acc<A>(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    n0: int,
    n1: int,
    n2: int,
    i0: int,
    i1: int,
    i2: int,
)
    requires
        pre_a.len() == n0,
        pre_t.len() == n0,
        pre_v.len() == n0,
        sub_a.len() == n1,
        tag_t.len() == n2,
        tag_v.len() == n2,
        n0 <= usize::MAX as int,
        n1 <= usize::MAX as int,
        n2 <= usize::MAX as int,
        0 <= i0 <= n0,
        0 <= i1 <= n1,
        0 <= i2 <= n2,
    ensures
        loop_acc3(
            pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0, i1, i2,
        ) == triple_acc(
            nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n0),
            step,
            base,
            star_pos(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0, i1, i2),
        ),
    decreases n0 - i0, n1 - i1, n2 - i2,
{
    let triples = nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n0);
    let pos = star_pos(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0, i1, i2);
    if i0 >= n0 {
        lemma_nested_star_past(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0);
        assert(nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0) == triples);
        assert(pos == triples.len() as int);
    } else if i1 >= n1 {
        lemma_star_acc(
            pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0 + 1, 0, 0,
        );
        let subs = eq_row_ids(sub_a, pre_a[i0], n1);
        let tags = eq_row_ids2(tag_t, tag_v, pre_t[i0], pre_v[i0], n2);
        lemma_eq_members(sub_a, pre_a[i0], n1);
        assert forall|p: int| 0 <= p < subs.len() implies (#[trigger] subs[p] as int) < i1 by {
            assert((subs[p] as int) < n1);
            assert(n1 <= i1);
        };
        lemma_ids_lt_all(subs, subs.len() as int, i1);
        lemma_sub_product_len(i0 as usize, subs, tags, subs.len() as int);
        assert((i0 as usize) as int == i0);
        lemma_nested_star_step(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0 + 1);
        let earlier = nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0);
        let through = nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0 + 1);
        assert(through.len() == earlier.len() + subs.len() * tags.len());
        if i0 + 1 < n0 {
            let subs2 = eq_row_ids(sub_a, pre_a[i0 + 1], n1);
            let tags2 = eq_row_ids2(tag_t, tag_v, pre_t[i0 + 1], pre_v[i0 + 1], n2);
            lemma_ids_lt_zero(subs2, subs2.len() as int);
            lemma_ids_lt_zero(tags2, tags2.len() as int);
        }
        assert(star_pos(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0 + 1, 0, 0) == pos);
    } else if i2 >= n2 {
        lemma_star_acc(
            pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0, i1 + 1, 0,
        );
        let subs = eq_row_ids(sub_a, pre_a[i0], n1);
        let tags = eq_row_ids2(tag_t, tag_v, pre_t[i0], pre_v[i0], n2);
        if star_sub(sub_a, pre_a[i0], i1) {
            lemma_eq_rank(sub_a, pre_a[i0], n1, i1);
            lemma_eq2_members(tag_t, tag_v, pre_t[i0], pre_v[i0], n2);
            assert forall|p: int| 0 <= p < tags.len() implies (#[trigger] tags[p] as int) < i2 by {
                assert((tags[p] as int) < n2);
                assert(n2 <= i2);
            };
            lemma_ids_lt_all(tags, tags.len() as int, i2);
            lemma_ids_lt_zero(tags, tags.len() as int);
            let sr = ids_lt(subs, subs.len() as int, i1);
            let tlen = tags.len() as int;
            vstd::arithmetic::mul::lemma_mul_is_distributive_add_other_way(tlen, sr, 1);
            vstd::arithmetic::mul::lemma_mul_basics_4(tlen);
            assert((sr + 1) * tlen == sr * tlen + tlen);
        } else {
            lemma_eq_members(sub_a, pre_a[i0], n1);
            assert forall|p: int| 0 <= p < subs.len() implies (#[trigger] subs[p] as int) != i1 by {
                assert(sub_a[(subs[p] as int)] == pre_a[i0]);
            };
            lemma_ids_lt_skip(subs, subs.len() as int, i1);
            lemma_ids_lt_zero(tags, tags.len() as int);
        }
        assert(star_pos(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0, i1 + 1, 0) == pos);
    } else if pre_a[i0] == sub_a[i1] && pre_t[i0] == tag_t[i2] && pre_v[i0] == tag_v[i2] {
        lemma_star_acc(
            pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0, i1, i2 + 1,
        );
        lemma_eq_rank(sub_a, pre_a[i0], n1, i1);
        lemma_eq2_rank(tag_t, tag_v, pre_t[i0], pre_v[i0], n2, i2);
        let subs = eq_row_ids(sub_a, pre_a[i0], n1);
        let tags = eq_row_ids2(tag_t, tag_v, pre_t[i0], pre_v[i0], n2);
        let sr = ids_lt(subs, subs.len() as int, i1);
        let tr = ids_lt(tags, tags.len() as int, i2);
        let tlen = tags.len() as int;
        let i0u = i0 as usize;
        let i1u = i1 as usize;
        let i2u = i2 as usize;
        assert(i0u as int == i0);
        assert(i1u as int == i1);
        assert(i2u as int == i2);
        lemma_sub_product_len(i0u, subs, tags, subs.len() as int);
        let prod = sub_product(i0u, subs, tags, subs.len() as int);
        assert(0 <= sr < subs.len());
        assert(0 <= tr < tlen);
        assert(sr * tlen + tr < prod.len()) by (nonlinear_arith)
            requires
                0 <= sr < subs.len(),
                0 <= tr < tlen,
                prod.len() == subs.len() * tags.len(),
                tlen == tags.len() as int,
        {
        }
        lemma_sub_product_at(i0u, subs, tags, subs.len() as int, sr, tr);
        lemma_nested_star_step(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0 + 1);
        let earlier = nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0);
        let through = nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0 + 1);
        assert(through == earlier + prod);
        assert(prod[sr * tags.len() + tr] == (i0u, subs[sr], tags[tr]));
        assert(subs[sr] as int == i1);
        assert(tags[tr] as int == i2);
        assert(subs[sr] == i1u);
        assert(tags[tr] == i2u);
        lemma_right_index(earlier, prod, sr * tlen + tr);
        assert(pos == earlier.len() as int + sr * tlen + tr);
        assert(sr * tlen + tr < prod.len()) by (nonlinear_arith)
            requires
                0 <= sr < subs.len(),
                0 <= tr < tlen,
                prod.len() == subs.len() * tags.len(),
                tlen == tags.len() as int,
        {
        }
        assert(pos < through.len());
        lemma_nested_star_len_mono(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0 + 1, n0);
        assert(through.len() <= triples.len());
        assert(pos < triples.len());
        lemma_nested_star_index(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0 + 1, n0, pos);
        assert(triples[pos] == (i0u, i1u, i2u));
        assert(pos + 1 == star_pos(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0, i1, i2 + 1));
        assert(loop_acc3(
            pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0, i1, i2,
        ) == step(
            loop_acc3(
                pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0, i1, i2 + 1,
            ),
            i0,
            i1,
            i2,
        ));
        assert(triple_acc(triples, step, base, pos) == step(
            triple_acc(triples, step, base, pos + 1),
            i0,
            i1,
            i2,
        ));
    } else {
        lemma_star_acc(
            pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, i0, i1, i2 + 1,
        );
        let subs = eq_row_ids(sub_a, pre_a[i0], n1);
        let tags = eq_row_ids2(tag_t, tag_v, pre_t[i0], pre_v[i0], n2);
        if star_sub(sub_a, pre_a[i0], i1) {
            lemma_eq2_members(tag_t, tag_v, pre_t[i0], pre_v[i0], n2);
            assert forall|p: int| 0 <= p < tags.len() implies (#[trigger] tags[p] as int) != i2 by {
                assert(tag_t[(tags[p] as int)] == pre_t[i0]);
                assert(tag_v[(tags[p] as int)] == pre_v[i0]);
            };
            lemma_ids_lt_skip(tags, tags.len() as int, i2);
        }
        assert(pos == star_pos(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, i0, i1, i2 + 1));
    }
}

pub proof fn lemma_sub_product_at(
    i: usize,
    subs: Seq<usize>,
    tags: Seq<usize>,
    s_end: int,
    sr: int,
    tr: int,
)
    requires
        0 <= sr < s_end <= subs.len(),
        0 <= tr < tags.len(),
    ensures
        sub_product(i, subs, tags, s_end)[sr * tags.len() + tr] == (i, subs[sr], tags[tr]),
    decreases s_end,
{
    let tlen = tags.len() as int;
    let prev = sub_product(i, subs, tags, s_end - 1);
    let extra = tag_prefix(i, subs[s_end - 1], tags, tlen);
    assert(sub_product(i, subs, tags, s_end) == prev + extra);
    lemma_sub_product_len(i, subs, tags, s_end - 1);
    lemma_tag_prefix_len(i, subs[s_end - 1], tags, tlen);
    if sr < s_end - 1 {
        lemma_sub_product_at(i, subs, tags, s_end - 1, sr, tr);
        assert(sr * tlen + tr < prev.len()) by (nonlinear_arith)
            requires
                0 <= sr < s_end - 1,
                0 <= tr < tlen,
                prev.len() == (s_end - 1) * tlen,
        {
        }
        lemma_left_index(prev, extra, sr * tlen + tr);
    } else {
        assert(sr == s_end - 1);
        lemma_tag_prefix_at(i, subs[s_end - 1], tags, tlen, tr);
        assert(tr < extra.len());
        lemma_right_index(prev, extra, tr);
        assert(prev.len() == sr * tlen);
        assert(prev.len() + tr == sr * tlen + tr);
    }
}

// SHAPE_STAR_END
// SHAPE_TWOKEY_BEGIN
/// Position of `(i0, i1)` in a two-column nested match list.
pub open spec fn pair_pos2<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    i0: int,
    i1: int,
) -> int {
    if !(0 <= i0 < outer_a.len() && i0 < outer_b.len()) {
        nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, i0).len() as int
    } else {
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[i0], outer_b[i0], inner_a.len() as int);
        nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, i0).len() as int + ids_lt(
            ids,
            ids.len() as int,
            i1,
        )
    }
}

/// Nested loop over two equalities, same order as a two-table helper.
pub open spec fn loop_acc2<A, B, C>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    step: spec_fn(C, int, int) -> C,
    base: C,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
) -> C
    decreases n_outer - i0, n_inner - i1,
{
    if i0 < n_outer {
        if i1 < n_inner {
            let tail = loop_acc2(
                outer_a,
                outer_b,
                inner_a,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0,
                i1 + 1,
            );
            if 0 <= i0 < outer_a.len() && 0 <= i0 < outer_b.len() && 0 <= i1 < inner_a.len()
                && 0 <= i1 < inner_b.len() && outer_a[i0] == inner_a[i1] && outer_b[i0] == inner_b[i1] {
                step(tail, i0, i1)
            } else {
                tail
            }
        } else {
            loop_acc2(
                outer_a,
                outer_b,
                inner_a,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0 + 1,
                0,
            )
        }
    } else {
        base
    }
}

pub proof fn lemma_nested_len_mono2<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
    m: int,
)
    requires
        0 <= n <= m,
    ensures
        nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, n).len() <= nested_eq_pairs2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            m,
        ).len(),
    decreases m - n,
{
    if n < m {
        lemma_nested_len_mono2(outer_a, outer_b, inner_a, inner_b, n, m - 1);
        let cur = nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, m);
        let prev = nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, m - 1);
        if m - 1 >= outer_a.len() || m - 1 >= outer_b.len() {
            assert(cur == prev);
        } else {
            let ids = eq_row_ids2(
                inner_a,
                inner_b,
                outer_a[m - 1],
                outer_b[m - 1],
                inner_a.len() as int,
            );
            let extra = prefix_pairs((m - 1) as usize, ids, ids.len() as int);
            assert(cur == prev + extra);
            assert(prev.len() <= cur.len());
        }
    }
}

pub proof fn lemma_nested_index2<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
    m: int,
    p: int,
)
    requires
        0 <= n <= m,
        0 <= p < nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, n).len(),
    ensures
        nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, m)[p] == nested_eq_pairs2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            n,
        )[p],
    decreases m - n,
{
    if n < m {
        let cur = nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, m);
        let prev = nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, m - 1);
        lemma_nested_len_mono2(outer_a, outer_b, inner_a, inner_b, n, m - 1);
        if m - 1 >= outer_a.len() || m - 1 >= outer_b.len() {
            assert(cur == prev);
        } else {
            let i = (m - 1) as usize;
            let ids = eq_row_ids2(
                inner_a,
                inner_b,
                outer_a[m - 1],
                outer_b[m - 1],
                inner_a.len() as int,
            );
            let extra = prefix_pairs(i, ids, ids.len() as int);
            assert(cur == prev + extra);
            assert(p < prev.len());
            lemma_left_index(prev, extra, p);
        }
        lemma_nested_index2(outer_a, outer_b, inner_a, inner_b, n, m - 1, p);
    }
}

pub proof fn lemma_acc2<A, B, C>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    step: spec_fn(C, int, int) -> C,
    base: C,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
)
    requires
        outer_a.len() == n_outer,
        outer_b.len() == n_outer,
        inner_a.len() == n_inner,
        inner_b.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
        0 <= i0 <= n_outer,
        0 <= i1 <= n_inner,
    ensures
        loop_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1,
        ) == pair_acc(
            nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, n_outer),
            step,
            base,
            pair_pos2(outer_a, outer_b, inner_a, inner_b, i0, i1),
        ),
    decreases n_outer - i0, n_inner - i1,
{
    let pairs = nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, n_outer);
    let pos = pair_pos2(outer_a, outer_b, inner_a, inner_b, i0, i1);
    if i0 >= n_outer {
        assert(nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, i0) =~= pairs);
        assert(pos == pairs.len() as int);
    } else if i1 >= n_inner {
        lemma_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            i0 + 1,
            0,
        );
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
        lemma_eq2_members(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
        assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < n_inner by {
            assert(0 <= (ids[p] as int) < n_inner);
        };
        assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < i1 by {
            assert((ids[p] as int) < n_inner);
            assert(n_inner <= i1);
        };
        lemma_ids_lt_all(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_len(i0u, ids, ids.len() as int);
        lemma_nested_eq_pairs2_step(outer_a, outer_b, inner_a, inner_b, i0 + 1);
        assert(nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, i0 + 1).len()
            == nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, i0).len() + ids.len());
        if i0 + 1 < outer_a.len() {
            let next_ids = eq_row_ids2(inner_a, inner_b, outer_a[i0 + 1], outer_b[i0 + 1], n_inner);
            lemma_ids_lt_zero(next_ids, next_ids.len() as int);
        }
        assert(pair_pos2(outer_a, outer_b, inner_a, inner_b, i0 + 1, 0) == pos);
    } else if outer_a[i0] == inner_a[i1] && outer_b[i0] == inner_b[i1] {
        lemma_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1 + 1,
        );
        lemma_eq2_rank(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner, i1);
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
        let r = ids_lt(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_len(i0u, ids, ids.len() as int);
        lemma_prefix_at(i0u, ids, ids.len() as int, r);
        let row_pairs = prefix_pairs(i0u, ids, ids.len() as int);
        let earlier = nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, i0);
        let through = nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, i0 + 1);
        lemma_nested_eq_pairs2_step(outer_a, outer_b, inner_a, inner_b, i0 + 1);
        assert(through == earlier + row_pairs);
        assert(i1 <= usize::MAX as int);
        let i1u = i1 as usize;
        assert(i1u as int == i1);
        assert(row_pairs[r] == (i0u, i1u));
        assert(0 <= r < row_pairs.len());
        lemma_right_index(earlier, row_pairs, r);
        assert(pos == earlier.len() as int + r);
        assert(through.len() == earlier.len() + row_pairs.len());
        assert(pos < through.len());
        lemma_nested_len_mono2(outer_a, outer_b, inner_a, inner_b, i0 + 1, n_outer);
        assert(through.len() <= pairs.len());
        assert(pos < pairs.len());
        lemma_nested_index2(outer_a, outer_b, inner_a, inner_b, i0 + 1, n_outer, pos);
        assert(through[pos] == (i0u, i1u));
        assert(pairs[pos] == (i0u, i1u));
        assert(pos + 1 == pair_pos2(outer_a, outer_b, inner_a, inner_b, i0, i1 + 1));
        assert(loop_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1,
        ) == step(
            loop_acc2(
                outer_a,
                outer_b,
                inner_a,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0,
                i1 + 1,
            ),
            i0,
            i1,
        ));
        assert(pair_acc(pairs, step, base, pos) == step(pair_acc(pairs, step, base, pos + 1), i0, i1));
    } else {
        lemma_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1 + 1,
        );
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
        lemma_eq2_members(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
        assert forall|p: int| 0 <= p < ids.len() implies (#[trigger] ids[p] as int) != i1 by {
            assert(inner_a[(ids[p] as int)] == outer_a[i0]);
            assert(inner_b[(ids[p] as int)] == outer_b[i0]);
        };
        lemma_ids_lt_skip(ids, ids.len() as int, i1);
        assert(pos == pair_pos2(outer_a, outer_b, inner_a, inner_b, i0, i1 + 1));
    }
}

// SHAPE_TWOKEY_END
/// Origin of the nested match list: starting at (0, 0) is position 0.
pub proof fn lemma_pair_pos_origin<K>(outer: Seq<K>, inner: Seq<K>)
    ensures
        pair_pos(outer, inner, 0, 0) == 0,
{
    assert(nested_eq_pairs(outer, inner, 0) =~= Seq::<(usize, usize)>::empty());
    if outer.len() == 0 {
        assert(pair_pos(outer, inner, 0, 0) == 0);
    } else {
        let ids = eq_row_ids(inner, outer[0], inner.len() as int);
        lemma_ids_lt_zero(ids, ids.len() as int);
        assert(pair_pos(outer, inner, 0, 0) == 0);
    }
}

// SHAPE_TWOKEY_BEGIN
/// Origin of the two-column nested match list: starting at (0, 0) is position 0.
pub proof fn lemma_pair_pos2_origin<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
)
    ensures
        pair_pos2(outer_a, outer_b, inner_a, inner_b, 0, 0) == 0,
{
    assert(nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, 0)
        =~= Seq::<(usize, usize)>::empty());
    if outer_a.len() == 0 || outer_b.len() == 0 {
        assert(pair_pos2(outer_a, outer_b, inner_a, inner_b, 0, 0) == 0);
    } else {
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[0], outer_b[0], inner_a.len() as int);
        lemma_ids_lt_zero(ids, ids.len() as int);
        assert(pair_pos2(outer_a, outer_b, inner_a, inner_b, 0, 0) == 0);
    }
}

// SHAPE_TWOKEY_END
// SHAPE_STAR_BEGIN
/// Origin of the star nested match list: starting at (0, 0, 0) is position 0.
pub proof fn lemma_star_pos_origin(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
)
    ensures
        star_pos(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, 0, 0, 0) == 0,
{
    assert(nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, 0)
        =~= Seq::<(usize, usize, usize)>::empty());
    if pre_a.len() == 0 || pre_t.len() == 0 || pre_v.len() == 0 {
        assert(star_pos(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, 0, 0, 0) == 0);
    } else {
        let subs = eq_row_ids(sub_a, pre_a[0], sub_a.len() as int);
        let tags = eq_row_ids2(tag_t, tag_v, pre_t[0], pre_v[0], tag_t.len() as int);
        lemma_ids_lt_zero(subs, subs.len() as int);
        lemma_ids_lt_zero(tags, tags.len() as int);
        vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(tags.len() as int);
        assert(star_pos(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, 0, 0, 0) == 0);
    }
}

// SHAPE_STAR_END
/// At the origin indices, ``loop_acc`` equals ``pair_acc`` of the nested match list at 0.
pub proof fn lemma_loop_at_origin<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int, int) -> A,
    base: A,
    n_outer: int,
    n_inner: int,
)
    requires
        outer.len() == n_outer,
        inner.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
    ensures
        loop_acc(outer, inner, step, base, n_outer, n_inner, 0, 0) == pair_acc(
            nested_eq_pairs(outer, inner, n_outer),
            step,
            base,
            0,
        ),
{
    lemma_acc(outer, inner, step, base, n_outer, n_inner, 0, 0);
    lemma_pair_pos_origin(outer, inner);
}

// SHAPE_TWOKEY_BEGIN
/// At the origin indices, ``loop_acc2`` equals ``pair_acc`` of the two-column match list at 0.
pub proof fn lemma_loop2_at_origin<A, B, C>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    step: spec_fn(C, int, int) -> C,
    base: C,
    n_outer: int,
    n_inner: int,
)
    requires
        outer_a.len() == n_outer,
        outer_b.len() == n_outer,
        inner_a.len() == n_inner,
        inner_b.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
    ensures
        loop_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            0,
            0,
        ) == pair_acc(
            nested_eq_pairs2(outer_a, outer_b, inner_a, inner_b, n_outer),
            step,
            base,
            0,
        ),
{
    lemma_acc2(outer_a, outer_b, inner_a, inner_b, step, base, n_outer, n_inner, 0, 0);
    lemma_pair_pos2_origin(outer_a, outer_b, inner_a, inner_b);
}

// SHAPE_TWOKEY_END
// SHAPE_STAR_BEGIN
/// At the origin indices, ``loop_acc3`` equals ``triple_acc`` of the star match list at 0.
pub proof fn lemma_star_at_origin<A>(
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    n0: int,
    n1: int,
    n2: int,
)
    requires
        pre_a.len() == n0,
        pre_t.len() == n0,
        pre_v.len() == n0,
        sub_a.len() == n1,
        tag_t.len() == n2,
        tag_v.len() == n2,
        n0 <= usize::MAX as int,
        n1 <= usize::MAX as int,
        n2 <= usize::MAX as int,
    ensures
        loop_acc3(
            pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, 0, 0, 0,
        ) == triple_acc(
            nested_star(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, n0),
            step,
            base,
            0,
        ),
{
    lemma_star_acc(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v, step, base, n0, n1, n2, 0, 0, 0);
    lemma_star_pos_origin(pre_a, pre_t, pre_v, sub_a, tag_t, tag_v);
}

// SHAPE_STAR_END
// SHAPE_LEFT_BEGIN
// LEFT anti-join miss list: outer rows with no equijoin match (existence-only).
// Same order as join_anti_multi_agg_helper: increasing ids; fold from the end.

/// Outer row ids in `0..n` with no matching inner key, increasing.
pub open spec fn nested_anti_misses<K>(outer: Seq<K>, inner: Seq<K>, n: int) -> Seq<usize>
    decreases n,
{
    if n <= 0 {
        Seq::<usize>::empty()
    } else if n - 1 >= outer.len() {
        nested_anti_misses(outer, inner, n - 1)
    } else {
        let prev = nested_anti_misses(outer, inner, n - 1);
        if eq_row_ids(inner, outer[n - 1], inner.len() as int).len() == 0 {
            prev.push((n - 1) as usize)
        } else {
            prev
        }
    }
}

pub proof fn lemma_nested_anti_misses_step<K>(outer: Seq<K>, inner: Seq<K>, n: int)
    requires
        0 < n <= outer.len(),
    ensures
        eq_row_ids(inner, outer[n - 1], inner.len() as int).len() == 0 ==> nested_anti_misses(
            outer,
            inner,
            n,
        ) == nested_anti_misses(outer, inner, n - 1).push((n - 1) as usize),
        eq_row_ids(inner, outer[n - 1], inner.len() as int).len() > 0 ==> nested_anti_misses(
            outer,
            inner,
            n,
        ) == nested_anti_misses(outer, inner, n - 1),
{
    if eq_row_ids(inner, outer[n - 1], inner.len() as int).len() == 0 {
        assert(nested_anti_misses(outer, inner, n) == nested_anti_misses(outer, inner, n - 1).push(
            (n - 1) as usize,
        ));
    } else {
        assert(nested_anti_misses(outer, inner, n) == nested_anti_misses(outer, inner, n - 1));
    }
}

/// Nested-loop LEFT-anti fold: on a miss, apply `step`; matches MethodSpec order.
pub open spec fn anti_loop_acc<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int) -> A,
    base: A,
    n_outer: int,
    i: int,
) -> A
    decreases n_outer - i,
{
    if i < n_outer {
        let tail = anti_loop_acc(outer, inner, step, base, n_outer, i + 1);
        if 0 <= i < outer.len() && eq_row_ids(inner, outer[i], inner.len() as int).len() == 0 {
            step(tail, i)
        } else {
            tail
        }
    } else {
        base
    }
}

/// Fold a miss-id list from the high index downward (same direction as MethodSpec).
pub open spec fn miss_acc<A>(
    misses: Seq<usize>,
    step: spec_fn(A, int) -> A,
    base: A,
    k: int,
) -> A
    decreases misses.len() - k,
{
    if k >= misses.len() {
        base
    } else {
        let tail = miss_acc(misses, step, base, k + 1);
        step(tail, misses[k] as int)
    }
}

pub proof fn lemma_eq_row_ids_nonempty_iff<K>(keys: Seq<K>, k: K, end: int)
    requires
        0 <= end <= keys.len(),
        end <= usize::MAX as int,
    ensures
        (eq_row_ids(keys, k, end).len() > 0) <==> (exists|j: int|
            0 <= j < end && keys[j] == k),
    decreases end,
{
    if end > 0 {
        lemma_eq_row_ids_nonempty_iff(keys, k, end - 1);
        lemma_eq_row_ids_step(keys, k, end - 1, (end - 1) as usize);
        if keys[end - 1] == k {
            assert(eq_row_ids(keys, k, end).len() > 0);
            assert(exists|j: int| 0 <= j < end && keys[j] == k) by {
                assert(0 <= end - 1 < end && keys[end - 1] == k);
            };
        } else {
            assert(eq_row_ids(keys, k, end) == eq_row_ids(keys, k, end - 1));
            assert((eq_row_ids(keys, k, end).len() > 0) <==> (exists|j: int|
                0 <= j < end - 1 && keys[j] == k));
            assert((exists|j: int| 0 <= j < end && keys[j] == k) <==> (exists|j: int|
                0 <= j < end - 1 && keys[j] == k)) by {
                if exists|j: int| 0 <= j < end && keys[j] == k {
                    let j = choose|j: int| 0 <= j < end && keys[j] == k;
                    if j == end - 1 {
                        assert(keys[end - 1] == k);
                        assert(false);
                    } else {
                        assert(0 <= j < end - 1 && keys[j] == k);
                    }
                }
            };
        }
    } else {
        assert(eq_row_ids(keys, k, 0).len() == 0);
        assert(!(exists|j: int| 0 <= j < 0 && keys[j] == k));
    }
}

/// Miss list for `a` is a prefix of the miss list for `b` (`a <= b`).
pub proof fn lemma_anti_miss_prefix<K>(outer: Seq<K>, inner: Seq<K>, a: int, b: int)
    requires
        0 <= a <= b <= outer.len(),
        b <= usize::MAX as int,
    ensures
        nested_anti_misses(outer, inner, a).len() <= nested_anti_misses(outer, inner, b).len(),
        forall|p: int|
            0 <= p < nested_anti_misses(outer, inner, a).len() ==> (#[trigger] nested_anti_misses(
                outer,
                inner,
                b,
            )[p]) == nested_anti_misses(outer, inner, a)[p],
    decreases b - a,
{
    if a < b {
        lemma_anti_miss_prefix(outer, inner, a, b - 1);
        lemma_nested_anti_misses_step(outer, inner, b);
        let at_a = nested_anti_misses(outer, inner, a);
        let at_prev = nested_anti_misses(outer, inner, b - 1);
        let at_b = nested_anti_misses(outer, inner, b);
        let ids = eq_row_ids(inner, outer[b - 1], inner.len() as int);
        if ids.len() == 0 {
            assert(at_b == at_prev.push((b - 1) as usize));
            assert(at_a.len() <= at_prev.len());
            assert(at_a.len() <= at_b.len());
            assert forall|p: int| 0 <= p < at_a.len() implies at_b[p] == at_a[p] by {
                lemma_seq_push_index_different(at_prev, (b - 1) as usize, p);
                assert(at_b[p] == at_prev[p]);
                assert(at_prev[p] == at_a[p]);
            };
        } else {
            assert(at_b == at_prev);
        }
    }
}

pub proof fn lemma_anti_miss_at<K>(outer: Seq<K>, inner: Seq<K>, n: int, i: int)
    requires
        0 <= i < n <= outer.len(),
        n <= usize::MAX as int,
        eq_row_ids(inner, outer[i], inner.len() as int).len() == 0,
    ensures
        (nested_anti_misses(outer, inner, i).len() as int) < nested_anti_misses(
            outer,
            inner,
            n,
        ).len(),
        nested_anti_misses(outer, inner, n)[nested_anti_misses(outer, inner, i).len() as int]
            == i as usize,
{
    lemma_nested_anti_misses_step(outer, inner, i + 1);
    assert(nested_anti_misses(outer, inner, i + 1) == nested_anti_misses(outer, inner, i).push(
        i as usize,
    ));
    lemma_anti_miss_prefix(outer, inner, i + 1, n);
    let k = nested_anti_misses(outer, inner, i).len() as int;
    assert(nested_anti_misses(outer, inner, i + 1)[k] == i as usize);
    assert(nested_anti_misses(outer, inner, n)[k] == nested_anti_misses(outer, inner, i + 1)[k]);
}

/// `anti_loop_acc` from left index `i` equals `miss_acc` from the miss-list suffix.
pub proof fn lemma_anti_acc<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int) -> A,
    base: A,
    n_outer: int,
    i: int,
)
    requires
        outer.len() == n_outer,
        n_outer <= usize::MAX as int,
        0 <= i <= n_outer,
    ensures
        anti_loop_acc(outer, inner, step, base, n_outer, i) == miss_acc(
            nested_anti_misses(outer, inner, n_outer),
            step,
            base,
            nested_anti_misses(outer, inner, i).len() as int,
        ),
    decreases n_outer - i,
{
    if i < n_outer {
        lemma_anti_acc(outer, inner, step, base, n_outer, i + 1);
        lemma_nested_anti_misses_step(outer, inner, i + 1);
        let misses = nested_anti_misses(outer, inner, n_outer);
        let k_i = nested_anti_misses(outer, inner, i).len() as int;
        let ids = eq_row_ids(inner, outer[i], inner.len() as int);
        if ids.len() == 0 {
            lemma_anti_miss_at(outer, inner, n_outer, i);
            assert(misses[k_i] == i as usize);
            assert(0 <= k_i < misses.len());
            assert(anti_loop_acc(outer, inner, step, base, n_outer, i) == step(
                anti_loop_acc(outer, inner, step, base, n_outer, i + 1),
                i,
            ));
            assert(miss_acc(misses, step, base, k_i) == step(
                miss_acc(misses, step, base, k_i + 1),
                misses[k_i] as int,
            ));
        } else {
            assert(nested_anti_misses(outer, inner, i + 1) == nested_anti_misses(outer, inner, i));
        }
    }
}

/// Origin: anti helper fold equals miss_acc of the full miss list at 0.
pub proof fn lemma_anti_at_origin<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int) -> A,
    base: A,
    n_outer: int,
)
    requires
        outer.len() == n_outer,
        n_outer <= usize::MAX as int,
    ensures
        anti_loop_acc(outer, inner, step, base, n_outer, 0) == miss_acc(
            nested_anti_misses(outer, inner, n_outer),
            step,
            base,
            0,
        ),
{
    assert(nested_anti_misses(outer, inner, 0) =~= Seq::<usize>::empty());
    lemma_anti_acc(outer, inner, step, base, n_outer, 0);
}

/// LEFT-anti miss ids for one `String` key column. View equals [`nested_anti_misses`].
pub fn anti_miss_rows_str(outer: &Vec<String>, inner: &Vec<String>) -> (misses: Vec<usize>)
    ensures
        misses@ == nested_anti_misses(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    let idx = build_eq_index_str(inner);
    let ghost ov = key_views(outer@);
    let ghost iv = key_views(inner@);
    let mut misses: Vec<usize> = Vec::new();
    let mut i: usize = 0;
    while i < outer.len()
        invariant
            i <= outer.len(),
            outer@.len() == outer.len() as int,
            inner@.len() == inner.len() as int,
            ov == key_views(outer@),
            iv == key_views(inner@),
            index_ok(iv, idx.buckets@, idx.map@, inner@.len() as int),
            misses@ == nested_anti_misses(ov, iv, i as int),
        decreases outer.len() - i,
    {
        let key = outer[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(ov[end] == key@);
        }
        let ghost before = misses@;
        let hit = probe_eq_str(&idx, inner, key.as_str());
        match hit {
            Some(v) => {
                if v.len() == 0 {
                    misses.push(i);
                    proof {
                        assert(v@ == eq_row_ids(iv, key@, iv.len() as int));
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                        lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                        lemma_nested_anti_misses_step(ov, iv, end + 1);
                        assert(misses@ == before.push(i));
                        assert(misses@ == nested_anti_misses(ov, iv, end + 1));
                    }
                } else {
                    proof {
                        assert(v@ == eq_row_ids(iv, key@, iv.len() as int));
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() > 0);
                        lemma_nested_anti_misses_step(ov, iv, end + 1);
                        assert(misses@ == nested_anti_misses(ov, iv, end + 1));
                    }
                }
            },
            None => {
                misses.push(i);
                proof {
                    assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                    lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                    lemma_nested_anti_misses_step(ov, iv, end + 1);
                    assert(misses@ == before.push(i));
                    assert(misses@ == nested_anti_misses(ov, iv, end + 1));
                }
            },
        }
        i = i + 1;
    }
    misses
}

// SHAPE_LEFT_END

// SHAPE_4TABLE_BEGIN
/// Row ids where three columns equal (nested-if; Spec && is not short-circuit).
pub open spec fn eq_row_ids3<A, B, C>(
    a: Seq<A>, b: Seq<B>, c: Seq<C>, ka: A, kb: B, kc: C, end: int,
) -> Seq<usize>
    decreases end,
{
    if end <= 0 {
        Seq::<usize>::empty()
    } else {
        let prev = eq_row_ids3(a, b, c, ka, kb, kc, end - 1);
        if 0 <= end - 1 < a.len() {
            if end - 1 < b.len() {
                if end - 1 < c.len() {
                    if a[end - 1] == ka {
                        if b[end - 1] == kb {
                            if c[end - 1] == kc {
                                prev.push((end - 1) as usize)
                            } else { prev }
                        } else { prev }
                    } else { prev }
                } else { prev }
            } else { prev }
        } else { prev }
    }
}

pub proof fn lemma_eq_row_ids3_step<A, B, C>(
    a: Seq<A>, b: Seq<B>, c: Seq<C>, ka: A, kb: B, kc: C, end: int, row: usize,
)
    requires
        0 <= end < a.len(), end < b.len(), end < c.len(), row as int == end,
    ensures
        ({
            let hit = a[end] == ka && b[end] == kb && c[end] == kc;
            &&& hit ==> eq_row_ids3(a, b, c, ka, kb, kc, end + 1)
                == eq_row_ids3(a, b, c, ka, kb, kc, end).push(row)
            &&& !hit ==> eq_row_ids3(a, b, c, ka, kb, kc, end + 1)
                == eq_row_ids3(a, b, c, ka, kb, kc, end)
        }),
{
    let prev = eq_row_ids3(a, b, c, ka, kb, kc, end);
    let next = eq_row_ids3(a, b, c, ka, kb, kc, end + 1);
    if a[end] == ka {
        if b[end] == kb {
            if c[end] == kc { assert(next == prev.push(row)); }
            else { assert(next == prev); }
        } else { assert(next == prev); }
    } else { assert(next == prev); }
}

pub proof fn lemma_eq3_members<A, B, C>(
    a: Seq<A>, b: Seq<B>, c: Seq<C>, ka: A, kb: B, kc: C, end: int,
)
    requires
        0 <= end <= a.len(), end <= b.len(), end <= c.len(), end <= usize::MAX as int,
    ensures
        forall|p: int|
            0 <= p < eq_row_ids3(a, b, c, ka, kb, kc, end).len() ==> {
                let row = #[trigger] eq_row_ids3(a, b, c, ka, kb, kc, end)[p] as int;
                0 <= row < end && a[row] == ka && b[row] == kb && c[row] == kc
            },
    decreases end,
{
    if end > 0 {
        assert(0 <= end - 1 <= usize::MAX as int);
        lemma_eq3_members(a, b, c, ka, kb, kc, end - 1);
        let prev = eq_row_ids3(a, b, c, ka, kb, kc, end - 1);
        let cur = eq_row_ids3(a, b, c, ka, kb, kc, end);
        if 0 <= end - 1 < a.len() && end - 1 < b.len() && end - 1 < c.len()
            && a[end - 1] == ka && b[end - 1] == kb && c[end - 1] == kc
        {
            let row = (end - 1) as usize;
            assert(row as int == end - 1);
            assert(cur == prev.push(row));
            assert forall|p: int| 0 <= p < cur.len() implies ({
                let r = #[trigger] cur[p] as int;
                0 <= r < end && a[r] == ka && b[r] == kb && c[r] == kc
            }) by {
                if p < prev.len() { assert(cur[p] == prev[p]); }
                else { assert(cur[p] == row); }
            };
        } else { assert(cur == prev); }
    }
}

pub proof fn lemma_eq3_rank<A, B, C>(
    a: Seq<A>, b: Seq<B>, c: Seq<C>, ka: A, kb: B, kc: C, end: int, row: int,
)
    requires
        0 <= row < end <= a.len(), end <= b.len(), end <= c.len(),
        a[row] == ka, b[row] == kb, c[row] == kc, end <= usize::MAX as int,
    ensures
        ({
            let ids = eq_row_ids3(a, b, c, ka, kb, kc, end);
            let r = ids_lt(ids, ids.len() as int, row);
            &&& 0 <= r < ids.len()
            &&& ids[r] as int == row
            &&& ids_lt(ids, ids.len() as int, row + 1) == r + 1
        }),
    decreases end - row,
{
    let prev = eq_row_ids3(a, b, c, ka, kb, kc, end - 1);
    let cur = eq_row_ids3(a, b, c, ka, kb, kc, end);
    if end == row + 1 {
        let pushed = (end - 1) as usize;
        assert(0 <= end - 1 <= usize::MAX as int);
        assert(pushed as int == end - 1);
        assert(cur == prev.push(pushed));
        lemma_eq3_members(a, b, c, ka, kb, kc, row);
        lemma_ids_lt_all(prev, prev.len() as int, row);
        lemma_ids_lt_all(prev, prev.len() as int, row + 1);
        lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row);
        lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row + 1);
        assert(ids_lt(cur, prev.len() as int, row) == prev.len() as int);
        assert(ids_lt(cur, prev.len() as int, row + 1) == prev.len() as int);
        assert((pushed as int) < row + 1);
        assert(cur.len() == prev.len() + 1);
        assert(ids_lt(cur, cur.len() as int, row) == prev.len() as int);
        assert(ids_lt(cur, cur.len() as int, row + 1) == prev.len() as int + 1);
        assert(cur[prev.len() as int] == pushed);
    } else {
        lemma_eq3_rank(a, b, c, ka, kb, kc, end - 1, row);
        let pushed = (end - 1) as usize;
        assert(0 <= end - 1 <= usize::MAX as int);
        assert(pushed as int == end - 1);
        assert(pushed as int > row);
        if 0 <= end - 1 < a.len() && end - 1 < b.len() && end - 1 < c.len()
            && a[end - 1] == ka && b[end - 1] == kb && c[end - 1] == kc
        {
            assert(cur == prev.push(pushed));
            lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row);
            lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row + 1);
            let r = ids_lt(prev, prev.len() as int, row);
            assert(cur[r] == prev[r]);
        } else { assert(cur == prev); }
    }
}

/// Ids from ``eq_row_ids2`` are strictly below ``end`` (for a follow-on column filter).
pub proof fn lemma_eq2_bounded<A, B>(a: Seq<A>, b: Seq<B>, ka: A, kb: B, end: int)
    requires
        0 <= end <= a.len(),
        end <= b.len(),
        end <= usize::MAX as int,
    ensures
        forall|t: int|
            0 <= t < eq_row_ids2(a, b, ka, kb, end).len() ==> (
                #[trigger] eq_row_ids2(a, b, ka, kb, end)[t] as int
            ) < end,
{
    lemma_eq2_members(a, b, ka, kb, end);
}

/// ``filter_match`` of a two-column id list on a third column is ``eq_row_ids3``.
pub proof fn lemma_filter_is_ids3<A, B, C>(
    a: Seq<A>, b: Seq<B>, c: Seq<C>, ka: A, kb: B, kc: C, end: int,
)
    requires
        0 <= end <= a.len(), a.len() == b.len(), a.len() == c.len(), end <= usize::MAX as int,
    ensures
        filter_match(
            eq_row_ids2(a, b, ka, kb, end), c, kc,
            eq_row_ids2(a, b, ka, kb, end).len() as int,
        ) == eq_row_ids3(a, b, c, ka, kb, kc, end),
    decreases end,
{
    if end > 0 {
        assert(0 <= end - 1 <= usize::MAX as int);
        lemma_filter_is_ids3(a, b, c, ka, kb, kc, end - 1);
        let row = (end - 1) as usize;
        assert(row as int == end - 1);
        let prev2 = eq_row_ids2(a, b, ka, kb, end - 1);
        lemma_eq_row_ids2_step(a, b, ka, kb, end - 1, row);
        lemma_eq_row_ids3_step(a, b, c, ka, kb, kc, end - 1, row);
        if a[end - 1] == ka {
            if b[end - 1] == kb {
                assert(eq_row_ids2(a, b, ka, kb, end) == prev2.push(row));
                lemma_filter_push(prev2, c, kc, row);
                if c[end - 1] == kc {
                    assert(eq_row_ids3(a, b, c, ka, kb, kc, end)
                        == eq_row_ids3(a, b, c, ka, kb, kc, end - 1).push(row));
                } else {
                    assert(eq_row_ids3(a, b, c, ka, kb, kc, end)
                        == eq_row_ids3(a, b, c, ka, kb, kc, end - 1));
                }
            } else {
                assert(eq_row_ids2(a, b, ka, kb, end) == prev2);
                assert(eq_row_ids3(a, b, c, ka, kb, kc, end)
                    == eq_row_ids3(a, b, c, ka, kb, kc, end - 1));
            }
        } else {
            assert(eq_row_ids2(a, b, ka, kb, end) == prev2);
            assert(eq_row_ids3(a, b, c, ka, kb, kc, end)
                == eq_row_ids3(a, b, c, ka, kb, kc, end - 1));
        }
    }
}


/// Quads for fixed hub/sub/tag over ``pres[0..p]``.
pub open spec fn pre_prefix4(
    i: usize, s: usize, t: usize, pres: Seq<usize>, p: int,
) -> Seq<(usize, usize, usize, usize)>
    decreases p,
{
    if p <= 0 {
        Seq::<(usize, usize, usize, usize)>::empty()
    } else {
        let prev = pre_prefix4(i, s, t, pres, p - 1);
        if 0 <= p - 1 < pres.len() {
            prev.push((i, s, t, pres[p - 1]))
        } else { prev }
    }
}

/// For fixed hub/sub: tags × pres cartesian, tag-major.
pub open spec fn tag_pre_product(
    i: usize, s: usize, tags: Seq<usize>, pres: Seq<usize>, t_end: int,
) -> Seq<(usize, usize, usize, usize)>
    decreases t_end,
{
    if t_end <= 0 {
        Seq::<(usize, usize, usize, usize)>::empty()
    } else {
        let prev = tag_pre_product(i, s, tags, pres, t_end - 1);
        if 0 <= t_end - 1 < tags.len() {
            prev + pre_prefix4(i, s, tags[t_end - 1], pres, pres.len() as int)
        } else { prev }
    }
}

/// Full three-arm product for one hub row: subs × tags × pres.
pub open spec fn quad_product(
    i: usize, subs: Seq<usize>, tags: Seq<usize>, pres: Seq<usize>, s_end: int,
) -> Seq<(usize, usize, usize, usize)>
    decreases s_end,
{
    if s_end <= 0 {
        Seq::<(usize, usize, usize, usize)>::empty()
    } else {
        let prev = quad_product(i, subs, tags, pres, s_end - 1);
        if 0 <= s_end - 1 < subs.len() {
            prev + tag_pre_product(i, subs[s_end - 1], tags, pres, tags.len() as int)
        } else { prev }
    }
}

/// Star equijoin match list: hub ⋈ 1-col ⋈ 2-col ⋈ 3-col (num⋈sub⋈tag⋈pre).
pub open spec fn nested_quad(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    n: int,
) -> Seq<(usize, usize, usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize, usize, usize)>::empty()
    } else if n - 1 >= hub_a.len() {
        nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n - 1)
    } else {
        let i = (n - 1) as usize;
        let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
        let tags = eq_row_ids2(tag_t, tag_v, hub_t[n - 1], hub_v[n - 1], tag_t.len() as int);
        let pres = eq_row_ids3(
            pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
        );
        nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n - 1)
            + quad_product(i, subs, tags, pres, subs.len() as int)
    }
}

/// Same star as `nested_quad`, keeping hub unit `USD`, sic in 7000..=8999,
/// abstract 0, and statement `EQ`.
pub open spec fn nested_quad_kept(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    uom: Seq<Seq<char>>,
    sic: Seq<u32>,
    abstr: Seq<u32>,
    stmt: Seq<Seq<char>>,
    n: int,
) -> Seq<(usize, usize, usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize, usize, usize)>::empty()
    } else if n - 1 >= hub_a.len() {
        nested_quad_kept(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n - 1,
        )
    } else {
        let i = (n - 1) as usize;
        let prev = nested_quad_kept(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n - 1,
        );
        if n - 1 >= uom.len() || uom[n - 1] != "USD"@ {
            prev
        } else {
            let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
            let tags = eq_row_ids2(tag_t, tag_v, hub_t[n - 1], hub_v[n - 1], tag_t.len() as int);
            let pres = eq_row_ids3(
                pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
            );
            let subs_k = ids_u32_between(subs, sic, 7000u32, 8999u32, subs.len() as int);
            let tags_k = ids_u32_eq(tags, abstr, 0u32, tags.len() as int);
            let pres_k = filter_match(pres, stmt, "EQ"@, pres.len() as int);
            prev + quad_product(i, subs_k, tags_k, pres_k, subs_k.len() as int)
        }
    }
}

pub proof fn lemma_nested_quad_kept_step(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    uom: Seq<Seq<char>>,
    sic: Seq<u32>,
    abstr: Seq<u32>,
    stmt: Seq<Seq<char>>,
    n: int,
)
    requires
        0 < n <= hub_a.len(),
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        hub_a.len() == uom.len(),
        tag_t.len() == tag_v.len(),
        tag_t.len() == abstr.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        pre_a.len() == stmt.len(),
        sub_a.len() == sic.len(),
    ensures
        nested_quad_kept(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n,
        ) == {
            let prev = nested_quad_kept(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt,
                n - 1,
            );
            if uom[n - 1] != "USD"@ {
                prev
            } else {
                let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
                let tags = eq_row_ids2(tag_t, tag_v, hub_t[n - 1], hub_v[n - 1], tag_t.len() as int);
                let pres = eq_row_ids3(
                    pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
                );
                prev + quad_product(
                    (n - 1) as usize,
                    ids_u32_between(subs, sic, 7000u32, 8999u32, subs.len() as int),
                    ids_u32_eq(tags, abstr, 0u32, tags.len() as int),
                    filter_match(pres, stmt, "EQ"@, pres.len() as int),
                    ids_u32_between(subs, sic, 7000u32, 8999u32, subs.len() as int).len() as int,
                )
            }
        },
{
    assert(n - 1 < uom.len());
}

pub proof fn lemma_ids_u32_between_bounded(
    ids: Seq<usize>,
    col: Seq<u32>,
    lo: u32,
    hi: u32,
    t: int,
    bound: int,
)
    requires
        0 <= t <= ids.len(),
        forall|s: int| 0 <= s < ids.len() ==> (#[trigger] ids[s] as int) < bound,
    ensures
        forall|p: int|
            0 <= p < ids_u32_between(ids, col, lo, hi, t).len() ==> (#[trigger] ids_u32_between(
                ids, col, lo, hi, t,
            )[p] as int) < bound,
    decreases t,
{
    if t > 0 {
        lemma_ids_u32_between_bounded(ids, col, lo, hi, t - 1, bound);
        let prev = ids_u32_between(ids, col, lo, hi, t - 1);
        let cur = ids_u32_between(ids, col, lo, hi, t);
        reveal_with_fuel(ids_u32_between, 2);
        if 0 <= t - 1 < ids.len() {
            let j = ids[t - 1];
            if 0 <= (j as int) < col.len() && lo <= col[j as int] && col[j as int] <= hi {
                assert(cur == prev.push(j));
                assert((j as int) < bound);
                assert forall|p: int| 0 <= p < cur.len() implies (cur[p] as int) < bound by {
                    if p < prev.len() {
                        lemma_seq_push_index_different(prev, j, p);
                    } else {
                        lemma_seq_push_index_same(prev, j, p);
                    }
                };
            }
        }
    }
}

pub proof fn lemma_pre_prefix_bounded(
    i: usize,
    s: usize,
    t: usize,
    pres: Seq<usize>,
    p: int,
    hub_b: int,
    sub_b: int,
    tag_b: int,
    pre_b: int,
)
    requires
        0 <= p <= pres.len(),
        (i as int) < hub_b,
        (s as int) < sub_b,
        (t as int) < tag_b,
        forall|j: int| 0 <= j < pres.len() ==> (#[trigger] pres[j] as int) < pre_b,
    ensures
        forall|q: int|
            0 <= q < pre_prefix4(i, s, t, pres, p).len() ==> {
                let row = #[trigger] pre_prefix4(i, s, t, pres, p)[q];
                &&& (row.0 as int) < hub_b
                &&& (row.1 as int) < sub_b
                &&& (row.2 as int) < tag_b
                &&& (row.3 as int) < pre_b
            },
    decreases p,
{
    if p > 0 {
        lemma_pre_prefix_bounded(i, s, t, pres, p - 1, hub_b, sub_b, tag_b, pre_b);
        reveal_with_fuel(pre_prefix4, 2);
        if 0 <= p - 1 < pres.len() {
            let prev = pre_prefix4(i, s, t, pres, p - 1);
            let row = (i, s, t, pres[p - 1]);
            let cur = prev.push(row);
            assert(pre_prefix4(i, s, t, pres, p) == cur);
            assert((pres[p - 1] as int) < pre_b);
            assert forall|q: int| 0 <= q < cur.len() implies {
                let r = #[trigger] cur[q];
                (r.0 as int) < hub_b && (r.1 as int) < sub_b && (r.2 as int) < tag_b
                    && (r.3 as int) < pre_b
            } by {
                if q < prev.len() {
                    lemma_seq_push_index_different(prev, row, q);
                } else {
                    lemma_seq_push_index_same(prev, row, q);
                }
            };
        }
    }
}

pub proof fn lemma_tag_pre_bounded(
    i: usize,
    s: usize,
    tags: Seq<usize>,
    pres: Seq<usize>,
    t_end: int,
    hub_b: int,
    sub_b: int,
    tag_b: int,
    pre_b: int,
)
    requires
        0 <= t_end <= tags.len(),
        (i as int) < hub_b,
        (s as int) < sub_b,
        forall|j: int| 0 <= j < tags.len() ==> (#[trigger] tags[j] as int) < tag_b,
        forall|j: int| 0 <= j < pres.len() ==> (#[trigger] pres[j] as int) < pre_b,
    ensures
        forall|q: int|
            0 <= q < tag_pre_product(i, s, tags, pres, t_end).len() ==> {
                let row = #[trigger] tag_pre_product(i, s, tags, pres, t_end)[q];
                &&& (row.0 as int) < hub_b
                &&& (row.1 as int) < sub_b
                &&& (row.2 as int) < tag_b
                &&& (row.3 as int) < pre_b
            },
    decreases t_end,
{
    if t_end > 0 {
        lemma_tag_pre_bounded(i, s, tags, pres, t_end - 1, hub_b, sub_b, tag_b, pre_b);
        reveal_with_fuel(tag_pre_product, 2);
        if 0 <= t_end - 1 < tags.len() {
            let prev = tag_pre_product(i, s, tags, pres, t_end - 1);
            let tid = tags[t_end - 1];
            let extra = pre_prefix4(i, s, tid, pres, pres.len() as int);
            assert((tid as int) < tag_b);
            lemma_pre_prefix_bounded(i, s, tid, pres, pres.len() as int, hub_b, sub_b, tag_b, pre_b);
            let cur = prev + extra;
            assert(tag_pre_product(i, s, tags, pres, t_end) == cur);
            assert forall|q: int| #![trigger cur[q]] 0 <= q < cur.len() implies {
                let row = cur[q];
                (row.0 as int) < hub_b && (row.1 as int) < sub_b && (row.2 as int) < tag_b
                    && (row.3 as int) < pre_b
            } by {
                if q < prev.len() {
                    lemma_left_index(prev, extra, q);
                } else {
                    lemma_right_index(prev, extra, q - prev.len());
                }
            };
        }
    }
}

pub proof fn lemma_quad_product_bounded(
    i: usize,
    subs: Seq<usize>,
    tags: Seq<usize>,
    pres: Seq<usize>,
    s_end: int,
    hub_b: int,
    sub_b: int,
    tag_b: int,
    pre_b: int,
)
    requires
        0 <= s_end <= subs.len(),
        (i as int) < hub_b,
        forall|j: int| 0 <= j < subs.len() ==> (#[trigger] subs[j] as int) < sub_b,
        forall|j: int| 0 <= j < tags.len() ==> (#[trigger] tags[j] as int) < tag_b,
        forall|j: int| 0 <= j < pres.len() ==> (#[trigger] pres[j] as int) < pre_b,
    ensures
        forall|q: int|
            0 <= q < quad_product(i, subs, tags, pres, s_end).len() ==> {
                let row = #[trigger] quad_product(i, subs, tags, pres, s_end)[q];
                &&& (row.0 as int) < hub_b
                &&& (row.1 as int) < sub_b
                &&& (row.2 as int) < tag_b
                &&& (row.3 as int) < pre_b
            },
    decreases s_end,
{
    if s_end > 0 {
        lemma_quad_product_bounded(i, subs, tags, pres, s_end - 1, hub_b, sub_b, tag_b, pre_b);
        reveal_with_fuel(quad_product, 2);
        if 0 <= s_end - 1 < subs.len() {
            let prev = quad_product(i, subs, tags, pres, s_end - 1);
            let sid = subs[s_end - 1];
            let extra = tag_pre_product(i, sid, tags, pres, tags.len() as int);
            assert((sid as int) < sub_b);
            lemma_tag_pre_bounded(i, sid, tags, pres, tags.len() as int, hub_b, sub_b, tag_b, pre_b);
            let cur = prev + extra;
            assert(quad_product(i, subs, tags, pres, s_end) == cur);
            assert forall|q: int| #![trigger cur[q]] 0 <= q < cur.len() implies {
                let row = cur[q];
                (row.0 as int) < hub_b && (row.1 as int) < sub_b && (row.2 as int) < tag_b
                    && (row.3 as int) < pre_b
            } by {
                if q < prev.len() {
                    lemma_left_index(prev, extra, q);
                } else {
                    lemma_right_index(prev, extra, q - prev.len());
                }
            };
        }
    }
}

pub proof fn lemma_nested_quad_kept_rows_in_range(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>,
    tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    uom: Seq<Seq<char>>,
    sic: Seq<u32>,
    abstr: Seq<u32>,
    stmt: Seq<Seq<char>>,
    n: int,
)
    requires
        0 <= n <= hub_a.len(),
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        hub_a.len() == uom.len(),
        tag_t.len() == tag_v.len(),
        tag_t.len() == abstr.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        pre_a.len() == stmt.len(),
        sub_a.len() == sic.len(),
        sub_a.len() <= usize::MAX as nat,
        tag_t.len() <= usize::MAX as nat,
        pre_a.len() <= usize::MAX as nat,
        hub_a.len() <= usize::MAX as nat,
    ensures
        forall|p: int|
            0 <= p < nested_quad_kept(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n,
            ).len() ==> {
                let row = #[trigger] nested_quad_kept(
                    hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n,
                )[p];
                &&& (row.0 as int) < hub_a.len()
                &&& (row.1 as int) < sub_a.len()
                &&& (row.2 as int) < tag_t.len()
                &&& (row.3 as int) < pre_a.len()
            },
    decreases n,
{
    if n > 0 {
        lemma_nested_quad_kept_rows_in_range(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n - 1,
        );
        let prev = nested_quad_kept(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n - 1,
        );
        if uom[n - 1] == "USD"@ {
            let i = (n - 1) as usize;
            assert(0 <= n - 1 <= usize::MAX as int);
            assert(i as int == n - 1);
            let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
            let tags = eq_row_ids2(tag_t, tag_v, hub_t[n - 1], hub_v[n - 1], tag_t.len() as int);
            let pres = eq_row_ids3(
                pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
            );
            lemma_eq_row_ids_bounded(sub_a, hub_a[n - 1], sub_a.len() as int);
            lemma_eq2_members(tag_t, tag_v, hub_t[n - 1], hub_v[n - 1], tag_t.len() as int);
            lemma_eq3_members(
                pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
            );
            let subs_k = ids_u32_between(subs, sic, 7000u32, 8999u32, subs.len() as int);
            let tags_k = ids_u32_eq(tags, abstr, 0u32, tags.len() as int);
            let pres_k = filter_match(pres, stmt, "EQ"@, pres.len() as int);
            assert forall|s: int| 0 <= s < subs.len() implies (subs[s] as int) < sub_a.len() by {
                assert((subs[s] as int) < sub_a.len());
            };
            lemma_ids_u32_between_bounded(subs, sic, 7000u32, 8999u32, subs.len() as int, sub_a.len() as int);
            assert forall|s: int| 0 <= s < tags.len() implies (tags[s] as int) < tag_t.len() by {
                assert((tags[s] as int) < tag_t.len());
            };
            lemma_ids_u32_bounded(tags, abstr, 0u32, tags.len() as int, tag_t.len() as int);
            assert forall|s: int| 0 <= s < pres.len() implies (pres[s] as int) < pre_a.len() by {
                assert((pres[s] as int) < pre_a.len());
            };
            lemma_filter_match_bounded(pres, stmt, "EQ"@, pres.len() as int, pre_a.len() as int);
            lemma_quad_product_bounded(
                i, subs_k, tags_k, pres_k, subs_k.len() as int,
                hub_a.len() as int, sub_a.len() as int, tag_t.len() as int, pre_a.len() as int,
            );
            let extra = quad_product(i, subs_k, tags_k, pres_k, subs_k.len() as int);
            lemma_nested_quad_kept_step(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n,
            );
            let cur = prev + extra;
            assert forall|p: int| #![trigger cur[p]] 0 <= p < cur.len() implies {
                let row = cur[p];
                (row.0 as int) < hub_a.len() && (row.1 as int) < sub_a.len()
                    && (row.2 as int) < tag_t.len() && (row.3 as int) < pre_a.len()
            } by {
                if p < prev.len() {
                    lemma_left_index(prev, extra, p);
                } else {
                    lemma_right_index(prev, extra, p - prev.len());
                }
            };
        }
    }
}

pub proof fn lemma_pre_prefix4_step(i: usize, s: usize, t: usize, pres: Seq<usize>, p: int)
    requires 0 <= p < pres.len(),
    ensures
        pre_prefix4(i, s, t, pres, p + 1)
            == pre_prefix4(i, s, t, pres, p).push((i, s, t, pres[p])),
{ assert(pre_prefix4(i, s, t, pres, p + 1) == pre_prefix4(i, s, t, pres, p).push((i, s, t, pres[p]))); }

pub proof fn lemma_tag_pre_product_step(
    i: usize, s: usize, tags: Seq<usize>, pres: Seq<usize>, t: int,
)
    requires 0 <= t < tags.len(),
    ensures
        tag_pre_product(i, s, tags, pres, t + 1)
            == tag_pre_product(i, s, tags, pres, t)
                + pre_prefix4(i, s, tags[t], pres, pres.len() as int),
{
    assert(tag_pre_product(i, s, tags, pres, t + 1)
        == tag_pre_product(i, s, tags, pres, t)
            + pre_prefix4(i, s, tags[t], pres, pres.len() as int));
}

pub proof fn lemma_quad_product_step(
    i: usize, subs: Seq<usize>, tags: Seq<usize>, pres: Seq<usize>, s: int,
)
    requires 0 <= s < subs.len(),
    ensures
        quad_product(i, subs, tags, pres, s + 1)
            == quad_product(i, subs, tags, pres, s)
                + tag_pre_product(i, subs[s], tags, pres, tags.len() as int),
{
    assert(quad_product(i, subs, tags, pres, s + 1)
        == quad_product(i, subs, tags, pres, s)
            + tag_pre_product(i, subs[s], tags, pres, tags.len() as int));
}

pub proof fn lemma_nested_quad_step(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    n: int,
)
    requires
        0 < n <= hub_a.len(),
        hub_a.len() == hub_t.len(), hub_a.len() == hub_v.len(),
        tag_t.len() == tag_v.len(),
        pre_a.len() == pre_t.len(), pre_a.len() == pre_v.len(),
    ensures
        nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n)
            == nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n - 1)
                + quad_product(
                    (n - 1) as usize,
                    eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int),
                    eq_row_ids2(tag_t, tag_v, hub_t[n - 1], hub_v[n - 1], tag_t.len() as int),
                    eq_row_ids3(
                        pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1],
                        pre_a.len() as int,
                    ),
                    eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int).len() as int,
                ),
{
    assert(nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n)
        == nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n - 1)
            + quad_product(
                (n - 1) as usize,
                eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int),
                eq_row_ids2(tag_t, tag_v, hub_t[n - 1], hub_v[n - 1], tag_t.len() as int),
                eq_row_ids3(
                    pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1],
                    pre_a.len() as int,
                ),
                eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int).len() as int,
            ));
}

pub proof fn lemma_pre_prefix4_len(i: usize, s: usize, t: usize, pres: Seq<usize>, p: int)
    requires 0 <= p <= pres.len(),
    ensures pre_prefix4(i, s, t, pres, p).len() == p as nat,
    decreases p,
{ if p > 0 { lemma_pre_prefix4_len(i, s, t, pres, p - 1); } }

pub proof fn lemma_tag_pre_product_len(
    i: usize, s: usize, tags: Seq<usize>, pres: Seq<usize>, t_end: int,
)
    requires 0 <= t_end <= tags.len(),
    ensures tag_pre_product(i, s, tags, pres, t_end).len() == t_end * pres.len(),
    decreases t_end,
{
    if t_end > 0 {
        lemma_tag_pre_product_len(i, s, tags, pres, t_end - 1);
        lemma_pre_prefix4_len(i, s, tags[t_end - 1], pres, pres.len() as int);
        let prev = tag_pre_product(i, s, tags, pres, t_end - 1);
        let extra = pre_prefix4(i, s, tags[t_end - 1], pres, pres.len() as int);
        assert(tag_pre_product(i, s, tags, pres, t_end) == prev + extra);
        assert(prev.len() == (t_end - 1) * pres.len());
        assert(extra.len() == pres.len());
        assert((prev + extra).len() == prev.len() + extra.len());
        assert(prev.len() + extra.len() == t_end * pres.len()) by (nonlinear_arith)
            requires prev.len() == (t_end - 1) * pres.len(), extra.len() == pres.len(),
        {}
        assert(tag_pre_product(i, s, tags, pres, t_end).len() == t_end * pres.len());
    } else {
        vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(pres.len() as int);
        assert(tag_pre_product(i, s, tags, pres, t_end).len() == 0);
        assert(t_end * pres.len() == 0);
    }
}

pub proof fn lemma_quad_product_len(
    i: usize, subs: Seq<usize>, tags: Seq<usize>, pres: Seq<usize>, s_end: int,
)
    requires 0 <= s_end <= subs.len(),
    ensures quad_product(i, subs, tags, pres, s_end).len() == s_end * (tags.len() * pres.len()),
    decreases s_end,
{
    if s_end > 0 {
        lemma_quad_product_len(i, subs, tags, pres, s_end - 1);
        lemma_tag_pre_product_len(i, subs[s_end - 1], tags, pres, tags.len() as int);
        let prev = quad_product(i, subs, tags, pres, s_end - 1);
        let extra = tag_pre_product(i, subs[s_end - 1], tags, pres, tags.len() as int);
        let tp = tags.len() * pres.len();
        assert(quad_product(i, subs, tags, pres, s_end) == prev + extra);
        assert(prev.len() == (s_end - 1) * tp);
        assert(extra.len() == tp);
        assert((prev + extra).len() == prev.len() + extra.len());
        assert(prev.len() + extra.len() == s_end * tp) by (nonlinear_arith)
            requires prev.len() == (s_end - 1) * tp, extra.len() == tp,
        {}
        assert(quad_product(i, subs, tags, pres, s_end).len() == s_end * tp);
    } else {
        let tp = tags.len() * pres.len();
        vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(tp as int);
        assert(quad_product(i, subs, tags, pres, s_end).len() == 0);
        assert(s_end * tp == 0);
    }
}

pub proof fn lemma_pre_prefix4_at(
    i: usize, s: usize, t: usize, pres: Seq<usize>, p: int, pr: int,
)
    requires 0 <= pr < p <= pres.len(),
    ensures pre_prefix4(i, s, t, pres, p)[pr] == (i, s, t, pres[pr]),
    decreases p,
{
    lemma_pre_prefix4_len(i, s, t, pres, p - 1);
    if pr < p - 1 {
        lemma_pre_prefix4_at(i, s, t, pres, p - 1, pr);
        let prev = pre_prefix4(i, s, t, pres, p - 1);
        let cur = pre_prefix4(i, s, t, pres, p);
        assert(cur == prev.push((i, s, t, pres[p - 1])));
        assert(cur[pr] == prev[pr]);
    } else {
        assert(pr == p - 1);
        let prev = pre_prefix4(i, s, t, pres, p - 1);
        let cur = pre_prefix4(i, s, t, pres, p);
        assert(cur == prev.push((i, s, t, pres[p - 1])));
        assert(cur[pr] == (i, s, t, pres[pr]));
    }
}

pub proof fn lemma_tag_pre_product_at(
    i: usize, s: usize, tags: Seq<usize>, pres: Seq<usize>, t_end: int, tr: int, pr: int,
)
    requires 0 <= tr < t_end <= tags.len(), 0 <= pr < pres.len(),
    ensures
        tag_pre_product(i, s, tags, pres, t_end)[tr * pres.len() + pr]
            == (i, s, tags[tr], pres[pr]),
    decreases t_end,
{
    let plen = pres.len() as int;
    let prev = tag_pre_product(i, s, tags, pres, t_end - 1);
    let extra = pre_prefix4(i, s, tags[t_end - 1], pres, plen);
    assert(tag_pre_product(i, s, tags, pres, t_end) == prev + extra);
    lemma_tag_pre_product_len(i, s, tags, pres, t_end - 1);
    lemma_pre_prefix4_len(i, s, tags[t_end - 1], pres, plen);
    if tr < t_end - 1 {
        lemma_tag_pre_product_at(i, s, tags, pres, t_end - 1, tr, pr);
        assert(tr * plen + pr < prev.len()) by (nonlinear_arith)
            requires 0 <= tr < t_end - 1, 0 <= pr < plen, prev.len() == (t_end - 1) * plen,
        {}
        lemma_left_index(prev, extra, tr * plen + pr);
    } else {
        assert(tr == t_end - 1);
        lemma_pre_prefix4_at(i, s, tags[t_end - 1], pres, plen, pr);
        assert(pr < extra.len());
        lemma_right_index(prev, extra, pr);
        assert(prev.len() == tr * plen);
        assert(prev.len() + pr == tr * plen + pr);
    }
}

pub proof fn lemma_quad_product_at(
    i: usize, subs: Seq<usize>, tags: Seq<usize>, pres: Seq<usize>,
    s_end: int, sr: int, tr: int, pr: int,
)
    requires
        0 <= sr < s_end <= subs.len(), 0 <= tr < tags.len(), 0 <= pr < pres.len(),
    ensures
        ({
            let tp = tags.len() * pres.len();
            quad_product(i, subs, tags, pres, s_end)[sr * tp + tr * pres.len() + pr]
                == (i, subs[sr], tags[tr], pres[pr])
        }),
    decreases s_end,
{
    let tlen = tags.len() as int;
    let plen = pres.len() as int;
    let tp = tlen * plen;
    let prev = quad_product(i, subs, tags, pres, s_end - 1);
    let extra = tag_pre_product(i, subs[s_end - 1], tags, pres, tlen);
    assert(quad_product(i, subs, tags, pres, s_end) == prev + extra);
    lemma_quad_product_len(i, subs, tags, pres, s_end - 1);
    lemma_tag_pre_product_len(i, subs[s_end - 1], tags, pres, tlen);
    if sr < s_end - 1 {
        lemma_quad_product_at(i, subs, tags, pres, s_end - 1, sr, tr, pr);
        assert(sr * tp + tr * plen + pr < prev.len()) by (nonlinear_arith)
            requires
                0 <= sr < s_end - 1, 0 <= tr < tlen, 0 <= pr < plen,
                prev.len() == (s_end - 1) * tp, tp == tlen * plen,
        {}
        lemma_left_index(prev, extra, sr * tp + tr * plen + pr);
    } else {
        assert(sr == s_end - 1);
        lemma_tag_pre_product_at(i, subs[s_end - 1], tags, pres, tlen, tr, pr);
        assert(tr * plen + pr < extra.len()) by (nonlinear_arith)
            requires 0 <= tr < tlen, 0 <= pr < plen, extra.len() == tlen * plen,
        {}
        lemma_right_index(prev, extra, tr * plen + pr);
        assert(prev.len() == sr * tp);
        assert(prev.len() + tr * plen + pr == sr * tp + tr * plen + pr);
    }
}


pub fn push_quad_product(
    out: &mut Vec<(usize, usize, usize, usize)>,
    i: usize,
    subs: &Vec<usize>,
    tags: &Vec<usize>,
    pres: &Vec<usize>,
)
    ensures
        final(out)@ == old(out)@ + quad_product(i, subs@, tags@, pres@, subs@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(subs@.len() == subs.len() as int);
        assert(tags@.len() == tags.len() as int);
        assert(pres@.len() == pres.len() as int);
    }
    let ghost base = out@;
    let mut extra: Vec<(usize, usize, usize, usize)> = Vec::new();
    let mut s: usize = 0;
    while s < subs.len()
        invariant
            s <= subs.len(),
            subs@.len() == subs.len() as int,
            tags@.len() == tags.len() as int,
            pres@.len() == pres.len() as int,
            extra@ == quad_product(i, subs@, tags@, pres@, s as int),
        decreases subs.len() - s,
    {
        let sid = subs[s];
        let ghost at_sub = extra@;
        proof {
            assert(sid == subs@[s as int]);
            lemma_seq_add_empty(at_sub);
        }
        let mut t: usize = 0;
        while t < tags.len()
            invariant
                t <= tags.len(),
                s < subs.len(),
                subs@.len() == subs.len() as int,
                tags@.len() == tags.len() as int,
                pres@.len() == pres.len() as int,
                sid == subs@[s as int],
                extra@ == at_sub + tag_pre_product(i, sid, tags@, pres@, t as int),
            decreases tags.len() - t,
        {
            let tid = tags[t];
            let ghost at_tag = extra@;
            proof { assert(tid == tags@[t as int]); }
            let mut p: usize = 0;
            while p < pres.len()
                invariant
                    p <= pres.len(),
                    t < tags.len(),
                    s < subs.len(),
                    subs@.len() == subs.len() as int,
                    tags@.len() == tags.len() as int,
                    pres@.len() == pres.len() as int,
                    sid == subs@[s as int],
                    tid == tags@[t as int],
                    extra@ == at_tag + pre_prefix4(i, sid, tid, pres@, p as int),
                decreases pres.len() - p,
            {
                let pid = pres[p];
                let ghost old_extra = extra@;
                extra.push((i, sid, tid, pid));
                proof {
                    assert(pid == pres@[p as int]);
                    lemma_pre_prefix4_step(i, sid, tid, pres@, p as int);
                    assert(extra@ == old_extra.push((i, sid, tid, pres@[p as int])));
                    lemma_seq_add_push(
                        at_tag,
                        pre_prefix4(i, sid, tid, pres@, p as int),
                        (i, sid, tid, pres@[p as int]),
                    );
                    assert(extra@ == at_tag + pre_prefix4(i, sid, tid, pres@, p as int + 1));
                }
                p = p + 1;
            }
            proof {
                assert(extra@ == at_tag + pre_prefix4(i, sid, tid, pres@, pres@.len() as int));
                lemma_tag_pre_product_step(i, sid, tags@, pres@, t as int);
                assert(extra@ == at_sub + tag_pre_product(i, sid, tags@, pres@, t as int + 1));
            }
            t = t + 1;
        }
        proof {
            assert(extra@ == at_sub + tag_pre_product(i, sid, tags@, pres@, tags@.len() as int));
            lemma_quad_product_step(i, subs@, tags@, pres@, s as int);
            assert(extra@ == quad_product(i, subs@, tags@, pres@, s as int + 1));
        }
        s = s + 1;
    }
    proof {
        assert(extra@ == quad_product(i, subs@, tags@, pres@, subs@.len() as int));
        assert(out@ == base);
    }
    out.append(&mut extra);
    proof {
        assert(out@ == base + quad_product(i, subs@, tags@, pres@, subs@.len() as int));
    }
}

/// Star equijoin: hub.adsh=sub.adsh, hub.(tag,version)=tag.(tag,version),
/// hub.(adsh,tag,version)=pre.(adsh,tag,version). Typical SEC num⋈sub⋈tag⋈pre.
pub fn star_eq_quads_str(
    hub_adsh: &Vec<String>,
    hub_tag: &Vec<String>,
    hub_ver: &Vec<String>,
    sub_adsh: &Vec<String>,
    tag_tag: &Vec<String>,
    tag_ver: &Vec<String>,
    pre_adsh: &Vec<String>,
    pre_tag: &Vec<String>,
    pre_ver: &Vec<String>,
) -> (quads: Vec<(usize, usize, usize, usize)>)
    requires
        hub_adsh@.len() == hub_tag@.len(),
        hub_adsh@.len() == hub_ver@.len(),
        tag_tag@.len() == tag_ver@.len(),
        pre_adsh@.len() == pre_tag@.len(),
        pre_adsh@.len() == pre_ver@.len(),
    ensures
        quads@ == nested_quad(
            key_views(hub_adsh@), key_views(hub_tag@), key_views(hub_ver@),
            key_views(sub_adsh@),
            key_views(tag_tag@), key_views(tag_ver@),
            key_views(pre_adsh@), key_views(pre_tag@), key_views(pre_ver@),
            hub_adsh@.len() as int,
        ),
{
    let idx_sub = build_eq_index_str(sub_adsh);
    let idx_tag = build_eq_index_str(tag_tag);
    let idx_pre = build_eq_index_str(pre_adsh);
    let ghost ha = key_views(hub_adsh@);
    let ghost ht = key_views(hub_tag@);
    let ghost hv = key_views(hub_ver@);
    let ghost sa = key_views(sub_adsh@);
    let ghost tt = key_views(tag_tag@);
    let ghost tv = key_views(tag_ver@);
    let ghost pa = key_views(pre_adsh@);
    let ghost pt = key_views(pre_tag@);
    let ghost pv = key_views(pre_ver@);
    let mut quads: Vec<(usize, usize, usize, usize)> = Vec::new();
    let mut i: usize = 0;
    while i < hub_adsh.len()
        invariant
            i <= hub_adsh.len(),
            hub_adsh@.len() == hub_adsh.len() as int,
            hub_adsh@.len() == hub_tag@.len(),
            hub_adsh@.len() == hub_ver@.len(),
            hub_tag@.len() == hub_tag.len() as int,
            hub_ver@.len() == hub_ver.len() as int,
            sub_adsh@.len() == sub_adsh.len() as int,
            tag_tag@.len() == tag_tag.len() as int,
            tag_ver@.len() == tag_ver.len() as int,
            tag_tag@.len() == tag_ver@.len(),
            pre_adsh@.len() == pre_adsh.len() as int,
            pre_tag@.len() == pre_tag.len() as int,
            pre_ver@.len() == pre_ver.len() as int,
            pre_adsh@.len() == pre_tag@.len(),
            pre_adsh@.len() == pre_ver@.len(),
            ha == key_views(hub_adsh@),
            ht == key_views(hub_tag@),
            hv == key_views(hub_ver@),
            sa == key_views(sub_adsh@),
            tt == key_views(tag_tag@),
            tv == key_views(tag_ver@),
            pa == key_views(pre_adsh@),
            pt == key_views(pre_tag@),
            pv == key_views(pre_ver@),
            index_ok(sa, idx_sub.buckets@, idx_sub.map@, sub_adsh@.len() as int),
            index_ok(tt, idx_tag.buckets@, idx_tag.map@, tag_tag@.len() as int),
            index_ok(pa, idx_pre.buckets@, idx_pre.map@, pre_adsh@.len() as int),
            quads@ == nested_quad(ha, ht, hv, sa, tt, tv, pa, pt, pv, i as int),
        decreases hub_adsh.len() - i,
    {
        let key_a = &hub_adsh[i];
        let key_t = &hub_tag[i];
        let key_v = &hub_ver[i];
        let ghost end = i as int;
        proof {
            lemma_key_view_at(hub_adsh@, end);
            lemma_key_view_at(hub_tag@, end);
            lemma_key_view_at(hub_ver@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            broadcast use vstd::seq::lemma_seq_new_len;
            assert(ha[end] == key_a@);
            assert(ht[end] == key_t@);
            assert(hv[end] == key_v@);
            assert(sa.len() == sub_adsh@.len());
            assert(tt.len() == tag_tag@.len());
            assert(tv.len() == tag_ver@.len());
            assert(pa.len() == pre_adsh@.len());
            assert(pt.len() == pre_tag@.len());
            assert(pv.len() == pre_ver@.len());
            assert(sa.len() as int <= usize::MAX as int);
            assert(tt.len() as int <= usize::MAX as int);
            assert(pa.len() as int <= usize::MAX as int);
        }
        let present_a = idx_sub.map.contains_key(key_a.as_str());
        let present_t = idx_tag.map.contains_key(key_t.as_str());
        let present_p = idx_pre.map.contains_key(key_a.as_str());
        let sub_ids: Vec<usize>;
        let tags: Vec<usize>;
        let pres: Vec<usize>;
        if present_a {
            let got_a = idx_sub.map.get(key_a.as_str());
            let bi_a = *got_a.unwrap();
            proof {
                assert(idx_sub.map@.contains_key(key_a@));
                lemma_index_bucket(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                assert((bi_a as int) < idx_sub.buckets@.len());
            }
            sub_ids = idx_sub.buckets[bi_a].clone();
        } else {
            proof {
                assert(!idx_sub.map@.contains_key(key_a@));
                lemma_index_absent(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                lemma_eq_row_ids_len0(sa, key_a@, sa.len() as int);
            }
            sub_ids = Vec::new();
        }
        if present_t {
            let got_t = idx_tag.map.get(key_t.as_str());
            let bi_t = *got_t.unwrap();
            proof {
                assert(idx_tag.map@.contains_key(key_t@));
                lemma_index_bucket(tt, idx_tag.buckets@, idx_tag.map@, tt.len() as int, key_t@);
                lemma_eq_row_ids_bounded(tt, key_t@, tt.len() as int);
                assert((bi_t as int) < idx_tag.buckets@.len());
            }
            let tag_bucket = &idx_tag.buckets[bi_t];
            tags = filter_row_ids_str(tag_bucket, tag_ver, key_v);
            proof {
                lemma_filter_is_ids2(tt, tv, key_t@, key_v@, tt.len() as int);
            }
        } else {
            proof {
                assert(!idx_tag.map@.contains_key(key_t@));
                lemma_index_absent(tt, idx_tag.buckets@, idx_tag.map@, tt.len() as int, key_t@);
                lemma_eq_row_ids_len0(tt, key_t@, tt.len() as int);
                lemma_filter_is_ids2(tt, tv, key_t@, key_v@, tt.len() as int);
                assert(eq_row_ids2(tt, tv, ht[end], hv[end], tt.len() as int)
                    =~= Seq::<usize>::empty());
            }
            tags = Vec::new();
        }
        if present_p {
            let got_p = idx_pre.map.get(key_a.as_str());
            let bi_p = *got_p.unwrap();
            proof {
                assert(idx_pre.map@.contains_key(key_a@));
                lemma_index_bucket(pa, idx_pre.buckets@, idx_pre.map@, pa.len() as int, key_a@);
                lemma_eq_row_ids_bounded(pa, key_a@, pa.len() as int);
                assert((bi_p as int) < idx_pre.buckets@.len());
            }
            let pre_bucket = &idx_pre.buckets[bi_p];
            let pre_mid = filter_row_ids_str(pre_bucket, pre_tag, key_t);
            proof {
                lemma_filter_is_ids2(pa, pt, key_a@, key_t@, pa.len() as int);
                assert(pre_mid@ == eq_row_ids2(pa, pt, ha[end], ht[end], pa.len() as int));
                lemma_eq2_bounded(pa, pt, ha[end], ht[end], pa.len() as int);
                assert(pa.len() == pre_ver@.len());
                assert forall|t: int|
                    0 <= t < pre_mid@.len() implies (#[trigger] pre_mid@[t] as int)
                        < pre_ver@.len() by {
                    assert(
                        (eq_row_ids2(pa, pt, ha[end], ht[end], pa.len() as int)[t] as int)
                            < pa.len()
                    );
                    assert(pre_mid@[t] == eq_row_ids2(pa, pt, ha[end], ht[end], pa.len() as int)[t]);
                };
            }
            pres = filter_row_ids_str(&pre_mid, pre_ver, key_v);
            proof {
                lemma_filter_is_ids3(pa, pt, pv, key_a@, key_t@, key_v@, pa.len() as int);
            }
        } else {
            proof {
                assert(!idx_pre.map@.contains_key(key_a@));
                lemma_index_absent(pa, idx_pre.buckets@, idx_pre.map@, pa.len() as int, key_a@);
                lemma_eq_row_ids_len0(pa, key_a@, pa.len() as int);
                lemma_filter_is_ids2(pa, pt, key_a@, key_t@, pa.len() as int);
                lemma_filter_is_ids3(pa, pt, pv, key_a@, key_t@, key_v@, pa.len() as int);
                assert(eq_row_ids3(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int)
                    =~= Seq::<usize>::empty());
            }
            pres = Vec::new();
        }
        let ghost before = quads@;
        proof {
            assert(sub_ids@ == eq_row_ids(sa, ha[end], sa.len() as int));
            assert(tags@ == eq_row_ids2(tt, tv, ht[end], hv[end], tt.len() as int));
            assert(pres@ == eq_row_ids3(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int));
        }
        push_quad_product(&mut quads, i, &sub_ids, &tags, &pres);
        proof {
            lemma_nested_quad_step(ha, ht, hv, sa, tt, tv, pa, pt, pv, end + 1);
            assert(quads@ == before + quad_product(
                i, sub_ids@, tags@, pres@, sub_ids@.len() as int,
            ));
            assert(quads@ == nested_quad(ha, ht, hv, sa, tt, tv, pa, pt, pv, end + 1));
        }
        i = i + 1;
    }
    quads
}

pub fn star_eq_quads_kept(
    hub_adsh: &Vec<String>,
    hub_tag: &Vec<String>,
    hub_ver: &Vec<String>,
    sub_adsh: &Vec<String>,
    tag_tag: &Vec<String>,
    tag_ver: &Vec<String>,
    pre_adsh: &Vec<String>,
    pre_tag: &Vec<String>,
    pre_ver: &Vec<String>,
    hub_uom: &Vec<String>,
    sub_sic: &Vec<u32>,
    tag_abs: &Vec<u32>,
    pre_stmt: &Vec<String>,
) -> (quads: Vec<(usize, usize, usize, usize)>)
    requires
        hub_adsh@.len() == hub_tag@.len(),
        hub_adsh@.len() == hub_ver@.len(),
        hub_adsh@.len() == hub_uom@.len(),
        tag_tag@.len() == tag_ver@.len(),
        tag_tag@.len() == tag_abs@.len(),
        pre_adsh@.len() == pre_tag@.len(),
        pre_adsh@.len() == pre_ver@.len(),
        pre_adsh@.len() == pre_stmt@.len(),
        sub_adsh@.len() == sub_sic@.len(),
        forall|j: int| 0 <= j < hub_uom@.len() ==> (hub_uom@[j]@).len() <= 512,
        forall|j: int| 0 <= j < pre_stmt@.len() ==> (pre_stmt@[j]@).len() <= 512,
    ensures
        quads@ == nested_quad_kept(
            key_views(hub_adsh@), key_views(hub_tag@), key_views(hub_ver@),
            key_views(sub_adsh@),
            key_views(tag_tag@), key_views(tag_ver@),
            key_views(pre_adsh@), key_views(pre_tag@), key_views(pre_ver@),
            key_views(hub_uom@), sub_sic@, tag_abs@, key_views(pre_stmt@),
            hub_adsh@.len() as int,
        ),
        forall|p: int|
            #![trigger quads@[p]]
            0 <= p < quads@.len() ==> {
                &&& (quads@[p].0 as int) < hub_adsh@.len()
                &&& (quads@[p].1 as int) < sub_adsh@.len()
                &&& (quads@[p].2 as int) < tag_tag@.len()
                &&& (quads@[p].3 as int) < pre_adsh@.len()
            },
{
    let idx_sub = build_eq_index_str(sub_adsh);
    let idx_tag = build_eq_index_str(tag_tag);
    let idx_pre = build_eq_index_str(pre_adsh);
    let ghost ha = key_views(hub_adsh@);
    let ghost ht = key_views(hub_tag@);
    let ghost hv = key_views(hub_ver@);
    let ghost sa = key_views(sub_adsh@);
    let ghost tt = key_views(tag_tag@);
    let ghost tv = key_views(tag_ver@);
    let ghost pa = key_views(pre_adsh@);
    let ghost pt = key_views(pre_tag@);
    let ghost pv = key_views(pre_ver@);
    let ghost uo = key_views(hub_uom@);
    let ghost stt = key_views(pre_stmt@);
    let mut quads: Vec<(usize, usize, usize, usize)> = Vec::new();
    let empty_ids: Vec<usize> = Vec::new();
    proof {
        assert(empty_ids@ =~= Seq::<usize>::empty());
    }
    let mut i: usize = 0;
    while i < hub_adsh.len()
        invariant
            i <= hub_adsh.len(),
            hub_adsh@.len() == hub_adsh.len() as int,
            hub_adsh@.len() == hub_tag@.len(),
            hub_adsh@.len() == hub_ver@.len(),
            hub_adsh@.len() == hub_uom@.len(),
            sub_adsh@.len() == sub_adsh.len() as int,
            sub_adsh@.len() == sub_sic@.len(),
            tag_tag@.len() == tag_tag.len() as int,
            tag_tag@.len() == tag_ver@.len(),
            tag_tag@.len() == tag_abs@.len(),
            pre_adsh@.len() == pre_adsh.len() as int,
            pre_adsh@.len() == pre_tag@.len(),
            pre_adsh@.len() == pre_ver@.len(),
            pre_adsh@.len() == pre_stmt@.len(),
            ha == key_views(hub_adsh@),
            ht == key_views(hub_tag@),
            hv == key_views(hub_ver@),
            sa == key_views(sub_adsh@),
            tt == key_views(tag_tag@),
            tv == key_views(tag_ver@),
            pa == key_views(pre_adsh@),
            pt == key_views(pre_tag@),
            pv == key_views(pre_ver@),
            uo == key_views(hub_uom@),
            stt == key_views(pre_stmt@),
            index_ok(sa, idx_sub.buckets@, idx_sub.map@, sub_adsh@.len() as int),
            index_ok(tt, idx_tag.buckets@, idx_tag.map@, tag_tag@.len() as int),
            index_ok(pa, idx_pre.buckets@, idx_pre.map@, pre_adsh@.len() as int),
            empty_ids@ =~= Seq::<usize>::empty(),
            forall|j: int| 0 <= j < hub_uom@.len() ==> (hub_uom@[j]@).len() <= 512,
            forall|j: int| 0 <= j < pre_stmt@.len() ==> (pre_stmt@[j]@).len() <= 512,
            quads@ == nested_quad_kept(
                ha, ht, hv, sa, tt, tv, pa, pt, pv, uo, sub_sic@, tag_abs@, stt, i as int,
            ),
        decreases hub_adsh.len() - i,
    {
        let key_a = &hub_adsh[i];
        let key_t = &hub_tag[i];
        let key_v = &hub_ver[i];
        let uom_s = hub_uom[i].as_str();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(hub_adsh@, end);
            lemma_key_view_at(hub_tag@, end);
            lemma_key_view_at(hub_ver@, end);
            lemma_key_view_at(hub_uom@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            broadcast use vstd::seq::lemma_seq_new_len;
            assert(ha[end] == key_a@);
            assert(ht[end] == key_t@);
            assert(hv[end] == key_v@);
            assert(uo[end] == uom_s@);
            assert(uom_s@.len() <= 512);
            assert(sa.len() == sub_adsh@.len());
            assert(tt.len() == tag_tag@.len());
            assert(pa.len() == pre_adsh@.len());
            assert(sa.len() as int <= usize::MAX as int);
            assert(tt.len() as int <= usize::MAX as int);
            assert(pa.len() as int <= usize::MAX as int);
        }
        if eq_ascii_lit(uom_s, "USD") {
            let present_a = idx_sub.map.contains_key(key_a.as_str());
            let present_t = idx_tag.map.contains_key(key_t.as_str());
            let present_p = idx_pre.map.contains_key(key_a.as_str());
            let sub_ids: &Vec<usize>;
            if present_a {
                let got_a = idx_sub.map.get(key_a.as_str());
                let bi_a = *got_a.unwrap();
                proof {
                    assert(idx_sub.map@.contains_key(key_a@));
                    lemma_index_bucket(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                    assert((bi_a as int) < idx_sub.buckets@.len());
                }
                sub_ids = &idx_sub.buckets[bi_a];
                proof {
                    assert(sub_ids@ == idx_sub.buckets@[bi_a as int]@);
                    assert(sub_ids@ == eq_row_ids(sa, ha[end], sa.len() as int));
                    lemma_eq_row_ids_bounded(sa, ha[end], sa.len() as int);
                }
            } else {
                proof {
                    assert(!idx_sub.map@.contains_key(key_a@));
                    lemma_index_absent(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                    lemma_eq_row_ids_len0(sa, key_a@, sa.len() as int);
                }
                sub_ids = &empty_ids;
                proof {
                    assert(sub_ids@ == empty_ids@);
                    assert(sub_ids@ == eq_row_ids(sa, ha[end], sa.len() as int));
                }
            }
            proof {
                assert forall|t: int| 0 <= t < sub_ids@.len() implies (sub_ids@[t] as int) < sub_sic@.len() by {
                    assert((sub_ids@[t] as int) < sa.len());
                    assert(sa.len() == sub_sic@.len());
                };
            }
            let kept_sub = filter_ids_u32_between(sub_ids, sub_sic, 7000, 8999);
            let tag_ids: &Vec<usize>;
            if present_t {
                let got_t = idx_tag.map.get(key_t.as_str());
                let bi_t = *got_t.unwrap();
                proof {
                    assert(idx_tag.map@.contains_key(key_t@));
                    lemma_index_bucket(tt, idx_tag.buckets@, idx_tag.map@, tt.len() as int, key_t@);
                    lemma_eq_row_ids_bounded(tt, key_t@, tt.len() as int);
                    assert((bi_t as int) < idx_tag.buckets@.len());
                }
                tag_ids = &idx_tag.buckets[bi_t];
            } else {
                proof {
                    assert(!idx_tag.map@.contains_key(key_t@));
                    lemma_index_absent(tt, idx_tag.buckets@, idx_tag.map@, tt.len() as int, key_t@);
                    lemma_eq_row_ids_len0(tt, key_t@, tt.len() as int);
                }
                tag_ids = &empty_ids;
            }
            let tags = filter_row_ids_str(tag_ids, tag_ver, key_v);
            proof {
                lemma_filter_is_ids2(tt, tv, key_t@, key_v@, tt.len() as int);
                assert(tags@ == eq_row_ids2(tt, tv, ht[end], hv[end], tt.len() as int));
                assert forall|t: int| 0 <= t < tags@.len() implies (tags@[t] as int) < tag_abs@.len() by {
                    lemma_eq2_members(tt, tv, ht[end], hv[end], tt.len() as int);
                    assert((tags@[t] as int) < tt.len());
                    assert(tt.len() == tag_abs@.len());
                };
            }
            let kept_tag = filter_ids_u32(&tags, tag_abs, 0);
            let pres: Vec<usize>;
            if present_p {
                let got_p = idx_pre.map.get(key_a.as_str());
                let bi_p = *got_p.unwrap();
                proof {
                    assert(idx_pre.map@.contains_key(key_a@));
                    lemma_index_bucket(pa, idx_pre.buckets@, idx_pre.map@, pa.len() as int, key_a@);
                    lemma_eq_row_ids_bounded(pa, key_a@, pa.len() as int);
                    assert((bi_p as int) < idx_pre.buckets@.len());
                }
                let pre_bucket = &idx_pre.buckets[bi_p];
                let pre_mid = filter_row_ids_str(pre_bucket, pre_tag, key_t);
                proof {
                    lemma_filter_is_ids2(pa, pt, key_a@, key_t@, pa.len() as int);
                    assert(pre_mid@ == eq_row_ids2(pa, pt, ha[end], ht[end], pa.len() as int));
                    lemma_eq2_bounded(pa, pt, ha[end], ht[end], pa.len() as int);
                    assert forall|t: int|
                        0 <= t < pre_mid@.len() implies (#[trigger] pre_mid@[t] as int) < pre_ver@.len() by {
                        assert((pre_mid@[t] as int) < pa.len());
                        assert(pa.len() == pre_ver@.len());
                    };
                }
                pres = filter_row_ids_str(&pre_mid, pre_ver, key_v);
                proof {
                    lemma_filter_is_ids3(pa, pt, pv, key_a@, key_t@, key_v@, pa.len() as int);
                    assert(pres@ == eq_row_ids3(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int));
                }
            } else {
                proof {
                    assert(!idx_pre.map@.contains_key(key_a@));
                    lemma_index_absent(pa, idx_pre.buckets@, idx_pre.map@, pa.len() as int, key_a@);
                    lemma_eq_row_ids_len0(pa, key_a@, pa.len() as int);
                    lemma_filter_is_ids2(pa, pt, key_a@, key_t@, pa.len() as int);
                    lemma_filter_is_ids3(pa, pt, pv, key_a@, key_t@, key_v@, pa.len() as int);
                    assert(eq_row_ids3(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int)
                        =~= Seq::<usize>::empty());
                }
                pres = Vec::new();
                proof {
                    assert(pres@ =~= Seq::<usize>::empty());
                    assert(pres@ == eq_row_ids3(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int));
                }
            }
            proof {
                assert forall|t: int| 0 <= t < pres@.len() implies (pres@[t] as int) < pre_stmt@.len() by {
                    lemma_eq3_members(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int);
                    assert((pres@[t] as int) < pa.len());
                    assert(pa.len() == pre_stmt@.len());
                };
                assert forall|j: int| 0 <= j < pre_stmt@.len() implies (pre_stmt@[j]@).len() <= 512 by {
                };
            }
            let kept_pre = filter_ids_ascii_lit(&pres, pre_stmt, "EQ");
            let ghost before = quads@;
            push_quad_product(&mut quads, i, &kept_sub, &kept_tag, &kept_pre);
            proof {
                assert(kept_sub@ == ids_u32_between(sub_ids@, sub_sic@, 7000u32, 8999u32, sub_ids@.len() as int));
                assert(kept_tag@ == ids_u32_eq(tags@, tag_abs@, 0u32, tags@.len() as int));
                assert(kept_pre@ == filter_match(pres@, stt, "EQ"@, pres@.len() as int));
                lemma_nested_quad_kept_step(
                    ha, ht, hv, sa, tt, tv, pa, pt, pv, uo, sub_sic@, tag_abs@, stt, end + 1,
                );
                assert(quads@ == before + quad_product(
                    i, kept_sub@, kept_tag@, kept_pre@, kept_sub@.len() as int,
                ));
                assert(uo[end] == "USD"@);
                assert(quads@ == nested_quad_kept(
                    ha, ht, hv, sa, tt, tv, pa, pt, pv, uo, sub_sic@, tag_abs@, stt, end + 1,
                ));
            }
        } else {
            proof {
                assert(uom_s@ != "USD"@);
                assert(uo[end] != "USD"@);
                lemma_nested_quad_kept_step(
                    ha, ht, hv, sa, tt, tv, pa, pt, pv, uo, sub_sic@, tag_abs@, stt, end + 1,
                );
                assert(quads@ == nested_quad_kept(
                    ha, ht, hv, sa, tt, tv, pa, pt, pv, uo, sub_sic@, tag_abs@, stt, end + 1,
                ));
            }
        }
        i = i + 1;
    }
    proof {
        assert(i == hub_adsh.len());
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        broadcast use vstd::seq::lemma_seq_new_len;
        assert(sa.len() == sub_adsh@.len());
        assert(tt.len() == tag_tag@.len());
        assert(pa.len() == pre_adsh@.len());
        assert(ha.len() == hub_adsh@.len());
        assert(sub_adsh@.len() == sub_adsh.len() as int);
        assert(tag_tag@.len() == tag_tag.len() as int);
        assert(pre_adsh@.len() == pre_adsh.len() as int);
        assert(hub_adsh@.len() == hub_adsh.len() as int);
        assert(sa.len() <= usize::MAX as nat);
        assert(tt.len() <= usize::MAX as nat);
        assert(pa.len() <= usize::MAX as nat);
        assert(ha.len() <= usize::MAX as nat);
        lemma_nested_quad_kept_rows_in_range(
            ha, ht, hv, sa, tt, tv, pa, pt, pv, uo, sub_sic@, tag_abs@, stt, i as int,
        );
        assert(quads@ == nested_quad_kept(
            ha, ht, hv, sa, tt, tv, pa, pt, pv, uo, sub_sic@, tag_abs@, stt, i as int,
        ));
    }
    quads
}


pub open spec fn quad_sub(sub_a: Seq<Seq<char>>, key: Seq<char>, i1: int) -> bool {
    &&& 0 <= i1 < sub_a.len()
    &&& sub_a[i1] == key
}

pub open spec fn quad_tag(
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>, kt: Seq<char>, kv: Seq<char>, i2: int,
) -> bool {
    &&& 0 <= i2 < tag_t.len()
    &&& i2 < tag_v.len()
    &&& tag_t[i2] == kt
    &&& tag_v[i2] == kv
}

pub open spec fn quad_pos(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    i0: int, i1: int, i2: int, i3: int,
) -> int {
    if !(0 <= i0 < hub_a.len() && i0 < hub_t.len() && i0 < hub_v.len()) {
        nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0).len() as int
    } else {
        let subs = eq_row_ids(sub_a, hub_a[i0], sub_a.len() as int);
        let tags = eq_row_ids2(tag_t, tag_v, hub_t[i0], hub_v[i0], tag_t.len() as int);
        let pres = eq_row_ids3(
            pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], pre_a.len() as int,
        );
        let tlen = tags.len() as int;
        let plen = pres.len() as int;
        let sr = ids_lt(subs, subs.len() as int, i1);
        let tr = if quad_sub(sub_a, hub_a[i0], i1) {
            ids_lt(tags, tags.len() as int, i2)
        } else { 0 };
        let pr = if quad_sub(sub_a, hub_a[i0], i1) && quad_tag(tag_t, tag_v, hub_t[i0], hub_v[i0], i2) {
            ids_lt(pres, pres.len() as int, i3)
        } else { 0 };
        nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0).len() as int
            + sr * (tlen * plen) + tr * plen + pr
    }
}

pub open spec fn loop_acc4<A>(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
    n0: int, n1: int, n2: int, n3: int,
    i0: int, i1: int, i2: int, i3: int,
) -> A
    decreases n0 - i0, n1 - i1, n2 - i2, n3 - i3,
{
    if i0 < n0 {
        if i1 < n1 {
            if i2 < n2 {
                if i3 < n3 {
                    let tail = loop_acc4(
                        hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
                        step, base, n0, n1, n2, n3, i0, i1, i2, i3 + 1,
                    );
                    if hub_a[i0] == sub_a[i1] {
                        if hub_t[i0] == tag_t[i2] {
                            if hub_v[i0] == tag_v[i2] {
                                if hub_a[i0] == pre_a[i3] {
                                    if hub_t[i0] == pre_t[i3] {
                                        if hub_v[i0] == pre_v[i3] {
                                            step(tail, i0, i1, i2, i3)
                                        } else { tail }
                                    } else { tail }
                                } else { tail }
                            } else { tail }
                        } else { tail }
                    } else { tail }
                } else {
                    loop_acc4(
                        hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
                        step, base, n0, n1, n2, n3, i0, i1, i2 + 1, 0,
                    )
                }
            } else {
                loop_acc4(
                    hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
                    step, base, n0, n1, n2, n3, i0, i1 + 1, 0, 0,
                )
            }
        } else {
            loop_acc4(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
                step, base, n0, n1, n2, n3, i0 + 1, 0, 0, 0,
            )
        }
    } else { base }
}

pub open spec fn quad_acc<A>(
    quads: Seq<(usize, usize, usize, usize)>,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
    k: int,
) -> A
    decreases quads.len() - k,
{
    if k >= quads.len() {
        base
    } else {
        let tail = quad_acc(quads, step, base, k + 1);
        step(tail, quads[k].0 as int, quads[k].1 as int, quads[k].2 as int, quads[k].3 as int)
    }
}

pub proof fn lemma_quad_acc_suffix<A>(
    prev: Seq<(usize, usize, usize, usize)>,
    extra: Seq<(usize, usize, usize, usize)>,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
    j: int,
)
    requires
        0 <= j <= extra.len(),
    ensures
        quad_acc(prev + extra, step, base, prev.len() + j) == quad_acc(extra, step, base, j),
    decreases extra.len() - j,
{
    let whole = prev + extra;
    reveal_with_fuel(quad_acc, 1);
    if j < extra.len() {
        lemma_quad_acc_suffix(prev, extra, step, base, j + 1);
        lemma_right_index(prev, extra, j);
        assert(whole[prev.len() + j] == extra[j]);
    } else {
        assert(prev.len() + j == whole.len());
    }
}

pub proof fn lemma_quad_acc_concat<A>(
    prev: Seq<(usize, usize, usize, usize)>,
    extra: Seq<(usize, usize, usize, usize)>,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
    k: int,
)
    requires
        0 <= k <= prev.len(),
    ensures
        quad_acc(prev + extra, step, base, k) == quad_acc(prev, step, quad_acc(extra, step, base, 0), k),
    decreases prev.len() - k,
{
    let whole = prev + extra;
    let inner = quad_acc(extra, step, base, 0);
    reveal_with_fuel(quad_acc, 1);
    if k == prev.len() {
        lemma_quad_acc_suffix(prev, extra, step, base, 0);
        assert(quad_acc(whole, step, base, k) == inner);
        assert(quad_acc(prev, step, inner, k) == inner);
    } else {
        lemma_quad_acc_concat(prev, extra, step, base, k + 1);
        lemma_left_index(prev, extra, k);
        assert(whole[k] == prev[k]);
    }
}

pub proof fn lemma_quad_acc_push_at<A>(
    s: Seq<(usize, usize, usize, usize)>,
    x: (usize, usize, usize, usize),
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
    k: int,
)
    requires
        0 <= k <= s.len(),
    ensures
        quad_acc(s.push(x), step, base, k) == quad_acc(
            s,
            step,
            step(base, x.0 as int, x.1 as int, x.2 as int, x.3 as int),
            k,
        ),
    decreases s.len() - k,
{
    let s2 = s.push(x);
    let b2 = step(base, x.0 as int, x.1 as int, x.2 as int, x.3 as int);
    reveal_with_fuel(quad_acc, 1);
    assert(s2.len() == s.len() + 1);
    if k == s.len() {
        assert(k + 1 == s2.len());
        assert(quad_acc(s2, step, base, k + 1) == base);
        lemma_seq_push_index_same(s, x, k);
        assert(s2[k] == x);
        assert(quad_acc(s2, step, base, k) == b2);
        assert(k >= s.len());
        assert(quad_acc(s, step, b2, k) == b2);
    } else {
        lemma_quad_acc_push_at(s, x, step, base, k + 1);
        lemma_seq_push_index_different(s, x, k);
        assert(s2[k] == s[k]);
        assert(quad_acc(s2, step, base, k) == step(
            quad_acc(s2, step, base, k + 1),
            s2[k].0 as int,
            s2[k].1 as int,
            s2[k].2 as int,
            s2[k].3 as int,
        ));
        assert(quad_acc(s, step, b2, k) == step(
            quad_acc(s, step, b2, k + 1),
            s[k].0 as int,
            s[k].1 as int,
            s[k].2 as int,
            s[k].3 as int,
        ));
    }
}

pub proof fn lemma_pre_prefix_all_id<A>(
    i: usize,
    s: usize,
    t: usize,
    pres: Seq<usize>,
    p: int,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
)
    requires
        0 <= p <= pres.len(),
        forall|acc: A, j: int|
            #![trigger step(acc, i as int, s as int, t as int, pres[j] as int)]
            0 <= j < p ==> step(acc, i as int, s as int, t as int, pres[j] as int) == acc,
    ensures
        quad_acc(pre_prefix4(i, s, t, pres, p), step, base, 0) == base,
    decreases p,
{
    if p > 0 {
        reveal_with_fuel(pre_prefix4, 2);
        let prev = pre_prefix4(i, s, t, pres, p - 1);
        if 0 <= p - 1 < pres.len() {
            let id = pres[p - 1];
            let x = (i, s, t, id);
            assert(step(base, i as int, s as int, t as int, id as int) == base);
            lemma_pre_prefix_all_id(i, s, t, pres, p - 1, step, base);
            assert(pre_prefix4(i, s, t, pres, p) == prev.push(x));
            lemma_quad_acc_push_at(prev, x, step, base, 0);
        } else {
            lemma_pre_prefix_all_id(i, s, t, pres, p - 1, step, base);
        }
    }
}

pub proof fn lemma_quad_product_all_id<A>(
    i: usize,
    subs: Seq<usize>,
    tags: Seq<usize>,
    pres: Seq<usize>,
    s_end: int,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
)
    requires
        0 <= s_end <= subs.len(),
        forall|acc: A, sr: int, tr: int, pr: int|
            #![trigger step(acc, i as int, subs[sr] as int, tags[tr] as int, pres[pr] as int)]
            0 <= sr < s_end && 0 <= tr < tags.len() && 0 <= pr < pres.len() ==> step(
                acc,
                i as int,
                subs[sr] as int,
                tags[tr] as int,
                pres[pr] as int,
            ) == acc,
    ensures
        quad_acc(quad_product(i, subs, tags, pres, s_end), step, base, 0) == base,
    decreases s_end,
{
    if s_end > 0 {
        let sid = subs[s_end - 1];
        let prev = quad_product(i, subs, tags, pres, s_end - 1);
        let extra = tag_pre_product(i, sid, tags, pres, tags.len() as int);
        reveal_with_fuel(quad_product, 2);
        assert(quad_product(i, subs, tags, pres, s_end) == prev + extra);
        assert forall|acc: A, tr: int, pr: int|
            #![trigger step(acc, i as int, sid as int, tags[tr] as int, pres[pr] as int)]
            0 <= tr < tags.len() && 0 <= pr < pres.len()
            implies step(acc, i as int, sid as int, tags[tr] as int, pres[pr] as int) == acc by {
        };
        lemma_tag_pre_all_id(i, sid, tags, pres, tags.len() as int, step, base);
        lemma_quad_product_all_id(i, subs, tags, pres, s_end - 1, step, base);
        lemma_quad_acc_concat(prev, extra, step, base, 0);
    }
}

pub proof fn lemma_tag_pre_all_id<A>(
    i: usize,
    s: usize,
    tags: Seq<usize>,
    pres: Seq<usize>,
    t_end: int,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
)
    requires
        0 <= t_end <= tags.len(),
        forall|acc: A, tr: int, pr: int|
            #![trigger step(acc, i as int, s as int, tags[tr] as int, pres[pr] as int)]
            0 <= tr < t_end && 0 <= pr < pres.len() ==> step(
                acc,
                i as int,
                s as int,
                tags[tr] as int,
                pres[pr] as int,
            ) == acc,
    ensures
        quad_acc(tag_pre_product(i, s, tags, pres, t_end), step, base, 0) == base,
    decreases t_end,
{
    if t_end > 0 {
        let tid = tags[t_end - 1];
        let prev = tag_pre_product(i, s, tags, pres, t_end - 1);
        let extra = pre_prefix4(i, s, tid, pres, pres.len() as int);
        reveal_with_fuel(tag_pre_product, 2);
        assert(tag_pre_product(i, s, tags, pres, t_end) == prev + extra);
        assert forall|acc: A, pr: int|
            #![trigger step(acc, i as int, s as int, tid as int, pres[pr] as int)]
            0 <= pr < pres.len() implies step(acc, i as int, s as int, tid as int, pres[pr] as int)
                == acc by {
        };
        lemma_pre_prefix_all_id(i, s, tid, pres, pres.len() as int, step, base);
        lemma_tag_pre_all_id(i, s, tags, pres, t_end - 1, step, base);
        lemma_quad_acc_concat(prev, extra, step, base, 0);
    }
}

pub proof fn lemma_quad_product_ext(
    i: usize,
    a: Seq<usize>,
    b: Seq<usize>,
    tags: Seq<usize>,
    pres: Seq<usize>,
    s_end: int,
)
    requires
        0 <= s_end <= a.len(),
        s_end <= b.len(),
        forall|j: int| 0 <= j < s_end ==> a[j] == b[j],
    ensures
        quad_product(i, a, tags, pres, s_end) == quad_product(i, b, tags, pres, s_end),
    decreases s_end,
{
    if s_end > 0 {
        lemma_quad_product_ext(i, a, b, tags, pres, s_end - 1);
        assert(a[s_end - 1] == b[s_end - 1]);
        reveal_with_fuel(quad_product, 2);
    }
}

pub proof fn lemma_quad_product_push(
    i: usize,
    subs: Seq<usize>,
    id: usize,
    tags: Seq<usize>,
    pres: Seq<usize>,
)
    ensures
        quad_product(i, subs.push(id), tags, pres, (subs.len() + 1) as int)
            == quad_product(i, subs, tags, pres, subs.len() as int) + tag_pre_product(
            i,
            id,
            tags,
            pres,
            tags.len() as int,
        ),
{
    let grown = subs.push(id);
    let t = subs.len() as int;
    assert forall|j: int| 0 <= j < t implies grown[j] == subs[j] by {
        lemma_seq_push_index_different(subs, id, j);
    };
    lemma_quad_product_ext(i, grown, subs, tags, pres, t);
    reveal_with_fuel(quad_product, 2);
    lemma_seq_push_index_same(subs, id, t);
    assert(grown[t] == id);
    assert(quad_product(i, grown, tags, pres, t + 1) == quad_product(i, grown, tags, pres, t)
        + tag_pre_product(i, id, tags, pres, tags.len() as int));
}

pub proof fn lemma_pre_prefix_ext(
    i: usize,
    s: usize,
    t: usize,
    a: Seq<usize>,
    b: Seq<usize>,
    p: int,
)
    requires
        0 <= p <= a.len(),
        p <= b.len(),
        forall|j: int| 0 <= j < p ==> a[j] == b[j],
    ensures
        pre_prefix4(i, s, t, a, p) == pre_prefix4(i, s, t, b, p),
    decreases p,
{
    if p > 0 {
        lemma_pre_prefix_ext(i, s, t, a, b, p - 1);
        reveal_with_fuel(pre_prefix4, 2);
        assert(a[p - 1] == b[p - 1]);
    }
}

pub proof fn lemma_pre_prefix_of_push(i: usize, s: usize, t: usize, pres: Seq<usize>, id: usize)
    ensures
        pre_prefix4(i, s, t, pres.push(id), (pres.len() + 1) as int)
            == pre_prefix4(i, s, t, pres, pres.len() as int).push((i, s, t, id)),
{
    let grown = pres.push(id);
    let p = pres.len() as int;
    assert forall|j: int| 0 <= j < p implies grown[j] == pres[j] by {
        lemma_seq_push_index_different(pres, id, j);
    };
    lemma_pre_prefix_ext(i, s, t, grown, pres, p);
    reveal_with_fuel(pre_prefix4, 2);
    lemma_seq_push_index_same(pres, id, p);
    assert(grown[p] == id);
    assert(pre_prefix4(i, s, t, grown, p + 1) == pre_prefix4(i, s, t, grown, p).push((i, s, t, id)));
}

pub proof fn lemma_pre_prefix_fold_filter<A>(
    i: usize,
    s: usize,
    t: usize,
    pres: Seq<usize>,
    stmt: Seq<Seq<char>>,
    p: int,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
)
    requires
        0 <= p <= pres.len(),
        forall|j: int| 0 <= j < p ==> (pres[j] as int) < stmt.len(),
        forall|acc: A, j: int|
            #![trigger step(acc, i as int, s as int, t as int, pres[j] as int)]
            0 <= j < p && stmt[pres[j] as int] != "EQ"@ ==> step(
                acc,
                i as int,
                s as int,
                t as int,
                pres[j] as int,
            ) == acc,
    ensures
        quad_acc(pre_prefix4(i, s, t, pres, p), step, base, 0) == quad_acc(
            pre_prefix4(
                i,
                s,
                t,
                filter_match(pres, stmt, "EQ"@, p),
                filter_match(pres, stmt, "EQ"@, p).len() as int,
            ),
            step,
            base,
            0,
        ),
    decreases p,
{
    if p > 0 {
        reveal_with_fuel(pre_prefix4, 2);
        reveal_with_fuel(filter_match, 2);
        let prev = pre_prefix4(i, s, t, pres, p - 1);
        let filt_prev = filter_match(pres, stmt, "EQ"@, p - 1);
        if 0 <= p - 1 < pres.len() {
            let id = pres[p - 1];
            assert((id as int) < stmt.len());
            let x = (i, s, t, id);
            if stmt[id as int] == "EQ"@ {
                let b2 = step(base, i as int, s as int, t as int, id as int);
                lemma_pre_prefix_fold_filter(i, s, t, pres, stmt, p - 1, step, b2);
                assert(pre_prefix4(i, s, t, pres, p) == prev.push(x));
                assert(filter_match(pres, stmt, "EQ"@, p) == filt_prev.push(id));
                lemma_pre_prefix_of_push(i, s, t, filt_prev, id);
                lemma_quad_acc_push_at(prev, x, step, base, 0);
                lemma_quad_acc_push_at(
                    pre_prefix4(i, s, t, filt_prev, filt_prev.len() as int),
                    x,
                    step,
                    base,
                    0,
                );
            } else {
                lemma_pre_prefix_fold_filter(i, s, t, pres, stmt, p - 1, step, base);
                assert(pre_prefix4(i, s, t, pres, p) == prev.push(x));
                assert(filter_match(pres, stmt, "EQ"@, p) == filt_prev);
                assert(step(base, i as int, s as int, t as int, id as int) == base);
                lemma_quad_acc_push_at(prev, x, step, base, 0);
            }
        } else {
            lemma_pre_prefix_fold_filter(i, s, t, pres, stmt, p - 1, step, base);
        }
    }
}

pub proof fn lemma_tag_pre_ext(
    i: usize,
    s: usize,
    a: Seq<usize>,
    b: Seq<usize>,
    pres: Seq<usize>,
    t_end: int,
)
    requires
        0 <= t_end <= a.len(),
        t_end <= b.len(),
        forall|j: int| 0 <= j < t_end ==> a[j] == b[j],
    ensures
        tag_pre_product(i, s, a, pres, t_end) == tag_pre_product(i, s, b, pres, t_end),
    decreases t_end,
{
    if t_end > 0 {
        lemma_tag_pre_ext(i, s, a, b, pres, t_end - 1);
        assert(a[t_end - 1] == b[t_end - 1]);
        reveal_with_fuel(tag_pre_product, 2);
    }
}

pub proof fn lemma_tag_pre_push(
    i: usize,
    s: usize,
    tags: Seq<usize>,
    id: usize,
    pres: Seq<usize>,
)
    ensures
        tag_pre_product(i, s, tags.push(id), pres, (tags.len() + 1) as int)
            == tag_pre_product(i, s, tags, pres, tags.len() as int) + pre_prefix4(
            i,
            s,
            id,
            pres,
            pres.len() as int,
        ),
{
    let grown = tags.push(id);
    let t = tags.len() as int;
    assert forall|j: int| 0 <= j < t implies grown[j] == tags[j] by {
        lemma_seq_push_index_different(tags, id, j);
    };
    lemma_tag_pre_ext(i, s, grown, tags, pres, t);
    reveal_with_fuel(tag_pre_product, 2);
    lemma_seq_push_index_same(tags, id, t);
    assert(grown[t] == id);
    assert(tag_pre_product(i, s, grown, pres, t + 1) == tag_pre_product(i, s, grown, pres, t)
        + pre_prefix4(i, s, id, pres, pres.len() as int));
}

pub proof fn lemma_tag_pre_fold_filter<A>(
    i: usize,
    s: usize,
    tags: Seq<usize>,
    pres: Seq<usize>,
    abstr: Seq<u32>,
    stmt: Seq<Seq<char>>,
    t_end: int,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
)
    requires
        0 <= t_end <= tags.len(),
        forall|tr: int| 0 <= tr < t_end ==> (tags[tr] as int) < abstr.len(),
        forall|pr: int| 0 <= pr < pres.len() ==> (pres[pr] as int) < stmt.len(),
        forall|acc: A, tr: int, pr: int|
            #![trigger step(acc, i as int, s as int, tags[tr] as int, pres[pr] as int)]
            0 <= tr < t_end && 0 <= pr < pres.len() && !(abstr[tags[tr] as int] == 0
                && stmt[pres[pr] as int] == "EQ"@) ==> step(
                acc,
                i as int,
                s as int,
                tags[tr] as int,
                pres[pr] as int,
            ) == acc,
    ensures
        quad_acc(tag_pre_product(i, s, tags, pres, t_end), step, base, 0) == quad_acc(
            tag_pre_product(
                i,
                s,
                ids_u32_eq(tags, abstr, 0u32, t_end),
                filter_match(pres, stmt, "EQ"@, pres.len() as int),
                ids_u32_eq(tags, abstr, 0u32, t_end).len() as int,
            ),
            step,
            base,
            0,
        ),
    decreases t_end,
{
    if t_end > 0 {
        let tid = tags[t_end - 1];
        let prev = tag_pre_product(i, s, tags, pres, t_end - 1);
        let extra = pre_prefix4(i, s, tid, pres, pres.len() as int);
        let kept_prev = ids_u32_eq(tags, abstr, 0u32, t_end - 1);
        let kept_pres = filter_match(pres, stmt, "EQ"@, pres.len() as int);
        reveal_with_fuel(tag_pre_product, 2);
        reveal_with_fuel(ids_u32_eq, 2);
        assert(tag_pre_product(i, s, tags, pres, t_end) == prev + extra);
        assert((tid as int) < abstr.len());
        if abstr[tid as int] == 0 {
            let mid = quad_acc(extra, step, base, 0);
            assert forall|acc: A, j: int|
                #![trigger step(acc, i as int, s as int, tid as int, pres[j] as int)]
                0 <= j < pres.len() && stmt[pres[j] as int] != "EQ"@
                implies step(acc, i as int, s as int, tid as int, pres[j] as int) == acc by {
                assert((pres[j] as int) < stmt.len());
            };
            lemma_pre_prefix_fold_filter(i, s, tid, pres, stmt, pres.len() as int, step, base);
            lemma_tag_pre_fold_filter(i, s, tags, pres, abstr, stmt, t_end - 1, step, mid);
            lemma_quad_acc_concat(prev, extra, step, base, 0);
            assert(ids_u32_eq(tags, abstr, 0u32, t_end) == kept_prev.push(tid));
            lemma_tag_pre_push(i, s, kept_prev, tid, kept_pres);
            let kept_prev_prod = tag_pre_product(i, s, kept_prev, kept_pres, kept_prev.len() as int);
            let kept_extra = pre_prefix4(i, s, tid, kept_pres, kept_pres.len() as int);
            lemma_quad_acc_concat(kept_prev_prod, kept_extra, step, base, 0);
        } else {
            assert forall|acc: A, pr: int|
                #![trigger step(acc, i as int, s as int, tid as int, pres[pr] as int)]
                0 <= pr < pres.len() implies step(acc, i as int, s as int, tid as int, pres[pr] as int)
                    == acc by {
                assert((pres[pr] as int) < stmt.len());
                assert(abstr[tid as int] != 0);
            };
            lemma_pre_prefix_all_id(i, s, tid, pres, pres.len() as int, step, base);
            lemma_tag_pre_fold_filter(i, s, tags, pres, abstr, stmt, t_end - 1, step, base);
            lemma_quad_acc_concat(prev, extra, step, base, 0);
            assert(ids_u32_eq(tags, abstr, 0u32, t_end) == kept_prev);
        }
    }
}

pub proof fn lemma_quad_product_fold_filter<A>(
    i: usize,
    subs: Seq<usize>,
    tags: Seq<usize>,
    pres: Seq<usize>,
    sic: Seq<u32>,
    abstr: Seq<u32>,
    stmt: Seq<Seq<char>>,
    s_end: int,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
)
    requires
        0 <= s_end <= subs.len(),
        forall|sr: int| 0 <= sr < s_end ==> (subs[sr] as int) < sic.len(),
        forall|tr: int| 0 <= tr < tags.len() ==> (tags[tr] as int) < abstr.len(),
        forall|pr: int| 0 <= pr < pres.len() ==> (pres[pr] as int) < stmt.len(),
        forall|acc: A, sr: int, tr: int, pr: int|
            #![trigger step(acc, i as int, subs[sr] as int, tags[tr] as int, pres[pr] as int)]
            0 <= sr < s_end && 0 <= tr < tags.len() && 0 <= pr < pres.len()
                && !(7000 <= sic[subs[sr] as int] && sic[subs[sr] as int] <= 8999 && abstr[tags[tr] as int] == 0
                    && stmt[pres[pr] as int] == "EQ"@) ==> step(
                acc, i as int, subs[sr] as int, tags[tr] as int, pres[pr] as int,
            ) == acc,
    ensures
        quad_acc(quad_product(i, subs, tags, pres, s_end), step, base, 0) == quad_acc(
            quad_product(
                i,
                ids_u32_between(subs, sic, 7000u32, 8999u32, s_end),
                ids_u32_eq(tags, abstr, 0u32, tags.len() as int),
                filter_match(pres, stmt, "EQ"@, pres.len() as int),
                ids_u32_between(subs, sic, 7000u32, 8999u32, s_end).len() as int,
            ),
            step, base, 0,
        ),
    decreases s_end,
{
    if s_end > 0 {
        let sid = subs[s_end - 1];
        let prev = quad_product(i, subs, tags, pres, s_end - 1);
        let extra = tag_pre_product(i, sid, tags, pres, tags.len() as int);
        reveal_with_fuel(quad_product, 2);
        reveal_with_fuel(ids_u32_between, 2);
        assert(quad_product(i, subs, tags, pres, s_end) == prev + extra);
        assert((sid as int) < sic.len());
        let kept_prev = ids_u32_between(subs, sic, 7000u32, 8999u32, s_end - 1);
        let kept_tags = ids_u32_eq(tags, abstr, 0u32, tags.len() as int);
        let kept_pres = filter_match(pres, stmt, "EQ"@, pres.len() as int);
        if 7000 <= sic[sid as int] && sic[sid as int] <= 8999 {
            let mid = quad_acc(extra, step, base, 0);
            assert forall|acc: A, tr: int, pr: int|
                #![trigger step(acc, i as int, sid as int, tags[tr] as int, pres[pr] as int)]
                0 <= tr < tags.len() && 0 <= pr < pres.len() && !(abstr[tags[tr] as int] == 0
                    && stmt[pres[pr] as int] == "EQ"@)
                implies step(acc, i as int, sid as int, tags[tr] as int, pres[pr] as int) == acc by {
                assert((tags[tr] as int) < abstr.len());
                assert((pres[pr] as int) < stmt.len());
                assert(7000 <= sic[sid as int] && sic[sid as int] <= 8999);
            };
            lemma_tag_pre_fold_filter(i, sid, tags, pres, abstr, stmt, tags.len() as int, step, base);
            lemma_quad_product_fold_filter(i, subs, tags, pres, sic, abstr, stmt, s_end - 1, step, mid);
            lemma_quad_acc_concat(prev, extra, step, base, 0);
            assert(ids_u32_between(subs, sic, 7000u32, 8999u32, s_end) == kept_prev.push(sid));
            lemma_quad_product_push(i, kept_prev, sid, kept_tags, kept_pres);
            let kept_prev_prod = quad_product(i, kept_prev, kept_tags, kept_pres, kept_prev.len() as int);
            let kept_extra = tag_pre_product(i, sid, kept_tags, kept_pres, kept_tags.len() as int);
            lemma_quad_acc_concat(kept_prev_prod, kept_extra, step, base, 0);
        } else {
            assert forall|acc: A, tr: int, pr: int|
                #![trigger step(acc, i as int, sid as int, tags[tr] as int, pres[pr] as int)]
                0 <= tr < tags.len() && 0 <= pr < pres.len()
                implies step(acc, i as int, sid as int, tags[tr] as int, pres[pr] as int) == acc by {
                assert((tags[tr] as int) < abstr.len());
                assert((pres[pr] as int) < stmt.len());
                assert(!(7000 <= sic[sid as int] && sic[sid as int] <= 8999));
            };
            lemma_tag_pre_all_id(i, sid, tags, pres, tags.len() as int, step, base);
            lemma_quad_product_fold_filter(i, subs, tags, pres, sic, abstr, stmt, s_end - 1, step, base);
            lemma_quad_acc_concat(prev, extra, step, base, 0);
            assert(ids_u32_between(subs, sic, 7000u32, 8999u32, s_end) == kept_prev);
            assert(quad_acc(quad_product(i, subs, tags, pres, s_end), step, base, 0) == quad_acc(
                quad_product(i, kept_prev, kept_tags, kept_pres, kept_prev.len() as int),
                step, base, 0,
            ));
        }
    }
}

pub proof fn lemma_quad_acc_kept_matches<A>(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    uom: Seq<Seq<char>>,
    sic: Seq<u32>,
    abstr: Seq<u32>,
    stmt: Seq<Seq<char>>,
    n: int,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
)
    requires
        0 <= n <= hub_a.len(),
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        hub_a.len() == uom.len(),
        tag_t.len() == tag_v.len(),
        tag_t.len() == abstr.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        pre_a.len() == stmt.len(),
        sub_a.len() == sic.len(),
        sub_a.len() <= usize::MAX as nat,
        tag_t.len() <= usize::MAX as nat,
        pre_a.len() <= usize::MAX as nat,
        hub_a.len() <= usize::MAX as nat,
        forall|acc: A, i0: int, i1: int, i2: int, i3: int|
            #![trigger step(acc, i0, i1, i2, i3)]
            0 <= i0 < uom.len() && 0 <= i1 < sic.len() && 0 <= i2 < abstr.len() && 0 <= i3 < stmt.len()
                && !(
                    uom[i0] == "USD"@ && stmt[i3] == "EQ"@ && 7000 <= sic[i1] && sic[i1] <= 8999
                        && abstr[i2] == 0
                ) ==> step(acc, i0, i1, i2, i3) == acc,
    ensures
        quad_acc(
            nested_quad_kept(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n,
            ),
            step, base, 0,
        ) == quad_acc(
            nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n),
            step, base, 0,
        ),
    decreases n,
{
    if n > 0 {
        let prev_full = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n - 1);
        let i = (n - 1) as usize;
        let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
        let tags = eq_row_ids2(tag_t, tag_v, hub_t[n - 1], hub_v[n - 1], tag_t.len() as int);
        let pres = eq_row_ids3(
            pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
        );
        let full_prod = quad_product(i, subs, tags, pres, subs.len() as int);
        lemma_nested_quad_step(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n);
        assert(nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n) == prev_full + full_prod);
        assert(0 <= n - 1 <= usize::MAX as int);
        assert(i as int == n - 1);
        lemma_eq_row_ids_bounded(sub_a, hub_a[n - 1], sub_a.len() as int);
        lemma_eq2_members(tag_t, tag_v, hub_t[n - 1], hub_v[n - 1], tag_t.len() as int);
        lemma_eq3_members(
            pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
        );
        if uom[n - 1] != "USD"@ {
            lemma_nested_quad_kept_step(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n,
            );
            assert forall|acc: A, sr: int, tr: int, pr: int|
                #![trigger step(acc, i as int, subs[sr] as int, tags[tr] as int, pres[pr] as int)]
                0 <= sr < subs.len() && 0 <= tr < tags.len() && 0 <= pr < pres.len()
                implies step(acc, i as int, subs[sr] as int, tags[tr] as int, pres[pr] as int) == acc by {
                assert((subs[sr] as int) < sic.len());
                assert((tags[tr] as int) < abstr.len());
                assert((pres[pr] as int) < stmt.len());
                assert(uom[i as int] != "USD"@);
            };
            lemma_quad_product_all_id(i, subs, tags, pres, subs.len() as int, step, base);
            lemma_quad_acc_concat(prev_full, full_prod, step, base, 0);
            lemma_quad_acc_kept_matches(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt,
                n - 1, step, base,
            );
        } else {
            let subs_k = ids_u32_between(subs, sic, 7000u32, 8999u32, subs.len() as int);
            let tags_k = ids_u32_eq(tags, abstr, 0u32, tags.len() as int);
            let pres_k = filter_match(pres, stmt, "EQ"@, pres.len() as int);
            let kept_prod = quad_product(i, subs_k, tags_k, pres_k, subs_k.len() as int);
            lemma_nested_quad_kept_step(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n,
            );
            assert forall|acc: A, sr: int, tr: int, pr: int|
                #![trigger step(acc, i as int, subs[sr] as int, tags[tr] as int, pres[pr] as int)]
                0 <= sr < subs.len() && 0 <= tr < tags.len() && 0 <= pr < pres.len()
                    && !(7000 <= sic[subs[sr] as int] && sic[subs[sr] as int] <= 8999 && abstr[tags[tr] as int] == 0
                        && stmt[pres[pr] as int] == "EQ"@)
                implies step(acc, i as int, subs[sr] as int, tags[tr] as int, pres[pr] as int) == acc by {
                assert((subs[sr] as int) < sic.len());
                assert((tags[tr] as int) < abstr.len());
                assert((pres[pr] as int) < stmt.len());
                assert(uom[i as int] == "USD"@);
            };
            lemma_quad_product_fold_filter(
                i, subs, tags, pres, sic, abstr, stmt, subs.len() as int, step, base,
            );
            let mid = quad_acc(full_prod, step, base, 0);
            let prev_kept = nested_quad_kept(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt, n - 1,
            );
            lemma_quad_acc_concat(prev_full, full_prod, step, base, 0);
            lemma_quad_acc_concat(prev_kept, kept_prod, step, base, 0);
            lemma_quad_acc_kept_matches(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, uom, sic, abstr, stmt,
                n - 1, step, mid,
            );
        }
    }
}

pub proof fn lemma_nested_quad_len_mono(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    n: int, m: int,
)
    requires
        0 <= n <= m,
        hub_a.len() == hub_t.len(), hub_a.len() == hub_v.len(),
        tag_t.len() == tag_v.len(),
        pre_a.len() == pre_t.len(), pre_a.len() == pre_v.len(),
    ensures
        nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n).len()
            <= nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, m).len(),
    decreases m - n,
{
    if n < m {
        lemma_nested_quad_len_mono(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n, m - 1,
        );
        let cur = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, m);
        let prev = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, m - 1);
        if m - 1 < hub_a.len() {
            lemma_nested_quad_step(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, m,
            );
            assert(prev.len() <= cur.len());
        } else { assert(cur == prev); }
    }
}

pub proof fn lemma_nested_quad_index(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    n: int, m: int, p: int,
)
    requires
        0 <= n <= m,
        hub_a.len() == hub_t.len(), hub_a.len() == hub_v.len(),
        tag_t.len() == tag_v.len(),
        pre_a.len() == pre_t.len(), pre_a.len() == pre_v.len(),
        0 <= p < nested_quad(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n,
        ).len(),
    ensures
        nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, m)[p]
            == nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n)[p],
    decreases m - n,
{
    if n < m {
        let cur = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, m);
        let prev = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, m - 1);
        lemma_nested_quad_len_mono(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n, m - 1,
        );
        if m - 1 >= hub_a.len() {
            assert(cur == prev);
        } else {
            lemma_nested_quad_step(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, m,
            );
            assert(p < prev.len());
            let subs = eq_row_ids(sub_a, hub_a[m - 1], sub_a.len() as int);
            let tags = eq_row_ids2(tag_t, tag_v, hub_t[m - 1], hub_v[m - 1], tag_t.len() as int);
            let pres = eq_row_ids3(
                pre_a, pre_t, pre_v, hub_a[m - 1], hub_t[m - 1], hub_v[m - 1],
                pre_a.len() as int,
            );
            let extra = quad_product((m - 1) as usize, subs, tags, pres, subs.len() as int);
            lemma_left_index(prev, extra, p);
        }
        lemma_nested_quad_index(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n, m - 1, p,
        );
    }
}

pub proof fn lemma_nested_quad_past(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    n: int,
)
    requires
        n >= hub_a.len(),
        hub_a.len() == hub_t.len(), hub_a.len() == hub_v.len(),
        tag_t.len() == tag_v.len(),
        pre_a.len() == pre_t.len(), pre_a.len() == pre_v.len(),
    ensures
        nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n)
            == nested_quad(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
                hub_a.len() as int,
            ),
    decreases n - hub_a.len(),
{
    if n > hub_a.len() {
        assert(nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n)
            == nested_quad(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n - 1,
            ));
        lemma_nested_quad_past(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n - 1,
        );
    }
}


pub proof fn lemma_quad_acc<A>(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
    n0: int, n1: int, n2: int, n3: int,
    i0: int, i1: int, i2: int, i3: int,
)
    requires
        hub_a.len() == n0, hub_t.len() == n0, hub_v.len() == n0,
        sub_a.len() == n1,
        tag_t.len() == n2, tag_v.len() == n2,
        pre_a.len() == n3, pre_t.len() == n3, pre_v.len() == n3,
        n0 <= usize::MAX as int, n1 <= usize::MAX as int,
        n2 <= usize::MAX as int, n3 <= usize::MAX as int,
        0 <= i0 <= n0, 0 <= i1 <= n1, 0 <= i2 <= n2, 0 <= i3 <= n3,
    ensures
        loop_acc4(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, n3, i0, i1, i2, i3,
        ) == quad_acc(
            nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n0),
            step, base,
            quad_pos(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1, i2, i3),
        ),
    decreases n0 - i0, n1 - i1, n2 - i2, n3 - i3,
{
    let quads = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n0);
    let pos = quad_pos(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1, i2, i3);
    if i0 >= n0 {
        lemma_nested_quad_past(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0);
        assert(nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0) == quads);
        assert(pos == quads.len() as int);
    } else if i1 >= n1 {
        lemma_quad_acc(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, n3, i0 + 1, 0, 0, 0,
        );
        let subs = eq_row_ids(sub_a, hub_a[i0], n1);
        let tags = eq_row_ids2(tag_t, tag_v, hub_t[i0], hub_v[i0], n2);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n3);
        let tlen = tags.len() as int;
        let plen = pres.len() as int;
        let tp = tlen * plen;
        lemma_eq_members(sub_a, hub_a[i0], n1);
        assert forall|p: int| 0 <= p < subs.len() implies (#[trigger] subs[p] as int) < i1 by {
            assert((subs[p] as int) < n1);
            assert(n1 <= i1);
        };
        lemma_ids_lt_all(subs, subs.len() as int, i1);
        lemma_quad_product_len(i0 as usize, subs, tags, pres, subs.len() as int);
        assert((i0 as usize) as int == i0);
        assert(!quad_sub(sub_a, hub_a[i0], i1));
        lemma_nested_quad_step(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0 + 1);
        let earlier = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0);
        let through = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0 + 1);
        assert(through.len() == earlier.len() + subs.len() * tp);
        assert(ids_lt(subs, subs.len() as int, i1) == subs.len() as int);
        assert(pos == earlier.len() as int + (subs.len() as int) * (tlen * plen));
        assert(pos == through.len() as int);
        if i0 + 1 < n0 {
            let subs2 = eq_row_ids(sub_a, hub_a[i0 + 1], n1);
            let tags2 = eq_row_ids2(tag_t, tag_v, hub_t[i0 + 1], hub_v[i0 + 1], n2);
            let pres2 = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0 + 1], hub_t[i0 + 1], hub_v[i0 + 1], n3);
            lemma_ids_lt_zero(subs2, subs2.len() as int);
            lemma_ids_lt_zero(tags2, tags2.len() as int);
            lemma_ids_lt_zero(pres2, pres2.len() as int);
            let tlen2 = tags2.len() as int;
            let plen2 = pres2.len() as int;
            vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(tlen2 * plen2);
            vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(plen2);
            assert(quad_pos(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0 + 1, 0, 0, 0,
            ) == through.len() as int);
        } else {
            assert(i0 + 1 == n0);
            assert(quad_pos(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0 + 1, 0, 0, 0,
            ) == through.len() as int);
        }
        assert(quad_pos(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0 + 1, 0, 0, 0) == pos);
    } else if i2 >= n2 {
        lemma_quad_acc(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, n3, i0, i1 + 1, 0, 0,
        );
        let subs = eq_row_ids(sub_a, hub_a[i0], n1);
        let tags = eq_row_ids2(tag_t, tag_v, hub_t[i0], hub_v[i0], n2);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n3);
        let tlen = tags.len() as int;
        let plen = pres.len() as int;
        let tp = tlen * plen;
        let base_len = nested_quad(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0,
        ).len() as int;
        vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(plen);
        assert(!quad_tag(tag_t, tag_v, hub_t[i0], hub_v[i0], i2));
        if quad_sub(sub_a, hub_a[i0], i1) {
            lemma_eq_rank(sub_a, hub_a[i0], n1, i1);
            lemma_eq2_members(tag_t, tag_v, hub_t[i0], hub_v[i0], n2);
            assert forall|p: int| 0 <= p < tags.len() implies (#[trigger] tags[p] as int) < i2 by {
                assert((tags[p] as int) < n2);
                assert(n2 <= i2);
            };
            lemma_ids_lt_all(tags, tags.len() as int, i2);
            lemma_ids_lt_zero(tags, tags.len() as int);
            lemma_ids_lt_zero(pres, pres.len() as int);
            let sr = ids_lt(subs, subs.len() as int, i1);
            assert(ids_lt(tags, tags.len() as int, i2) == tags.len() as int);
            assert((tags.len() as int) * plen == tp);
            assert(pos == base_len + sr * tp + (tags.len() as int) * plen);
            vstd::arithmetic::mul::lemma_mul_is_distributive_add_other_way(tp, sr, 1);
            vstd::arithmetic::mul::lemma_mul_basics_4(tp);
            assert((sr + 1) * tp == sr * tp + tp);
            assert(pos == base_len + (sr + 1) * tp);
            assert(ids_lt(subs, subs.len() as int, i1 + 1) == sr + 1);
            assert(quad_pos(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1 + 1, 0, 0,
            ) == base_len + (sr + 1) * tp);
        } else {
            lemma_eq_members(sub_a, hub_a[i0], n1);
            assert forall|p: int| 0 <= p < subs.len() implies (#[trigger] subs[p] as int) != i1 by {
                assert(sub_a[(subs[p] as int)] == hub_a[i0]);
            };
            lemma_ids_lt_skip(subs, subs.len() as int, i1);
            lemma_ids_lt_zero(tags, tags.len() as int);
            lemma_ids_lt_zero(pres, pres.len() as int);
            let sr = ids_lt(subs, subs.len() as int, i1);
            assert(pos == base_len + sr * tp);
            assert(quad_pos(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1 + 1, 0, 0,
            ) == base_len + sr * tp);
        }
        assert(quad_pos(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1 + 1, 0, 0) == pos);
    } else if i3 >= n3 {
        lemma_quad_acc(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, n3, i0, i1, i2 + 1, 0,
        );
        let subs = eq_row_ids(sub_a, hub_a[i0], n1);
        let tags = eq_row_ids2(tag_t, tag_v, hub_t[i0], hub_v[i0], n2);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n3);
        let tlen = tags.len() as int;
        let plen = pres.len() as int;
        let tp = tlen * plen;
        let base_len = nested_quad(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0,
        ).len() as int;
        let sr = ids_lt(subs, subs.len() as int, i1);
        vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(plen);
        if quad_sub(sub_a, hub_a[i0], i1) {
            if quad_tag(tag_t, tag_v, hub_t[i0], hub_v[i0], i2) {
                lemma_eq2_rank(tag_t, tag_v, hub_t[i0], hub_v[i0], n2, i2);
                lemma_eq3_members(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n3);
                assert forall|p: int| 0 <= p < pres.len() implies (#[trigger] pres[p] as int) < i3 by {
                    assert((pres[p] as int) < n3);
                    assert(n3 <= i3);
                };
                lemma_ids_lt_all(pres, pres.len() as int, i3);
                lemma_ids_lt_zero(pres, pres.len() as int);
                let tr = ids_lt(tags, tags.len() as int, i2);
                assert(ids_lt(pres, pres.len() as int, i3) == pres.len() as int);
                assert(pos == base_len + sr * tp + tr * plen + (pres.len() as int));
                vstd::arithmetic::mul::lemma_mul_is_distributive_add_other_way(plen, tr, 1);
                vstd::arithmetic::mul::lemma_mul_basics_4(plen);
                assert((tr + 1) * plen == tr * plen + plen);
                assert(pos == base_len + sr * tp + (tr + 1) * plen);
                assert(ids_lt(tags, tags.len() as int, i2 + 1) == tr + 1);
                assert(quad_pos(
                    hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1, i2 + 1, 0,
                ) == base_len + sr * tp + (tr + 1) * plen);
            } else {
                lemma_eq2_members(tag_t, tag_v, hub_t[i0], hub_v[i0], n2);
                assert forall|p: int| 0 <= p < tags.len() implies (#[trigger] tags[p] as int) != i2 by {
                    assert(tag_t[(tags[p] as int)] == hub_t[i0]);
                    assert(tag_v[(tags[p] as int)] == hub_v[i0]);
                };
                lemma_ids_lt_skip(tags, tags.len() as int, i2);
                lemma_ids_lt_zero(pres, pres.len() as int);
                let tr = ids_lt(tags, tags.len() as int, i2);
                assert(pos == base_len + sr * tp + tr * plen);
                assert(quad_pos(
                    hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1, i2 + 1, 0,
                ) == base_len + sr * tp + tr * plen);
            }
        } else {
            lemma_ids_lt_zero(pres, pres.len() as int);
            assert(pos == base_len + sr * tp);
            assert(quad_pos(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1, i2 + 1, 0,
            ) == base_len + sr * tp);
        }
        assert(quad_pos(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1, i2 + 1, 0) == pos);
    } else if hub_a[i0] == sub_a[i1]
        && hub_t[i0] == tag_t[i2]
        && hub_v[i0] == tag_v[i2]
        && hub_a[i0] == pre_a[i3]
        && hub_t[i0] == pre_t[i3]
        && hub_v[i0] == pre_v[i3]
    {
        lemma_quad_acc(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, n3, i0, i1, i2, i3 + 1,
        );
        lemma_eq_rank(sub_a, hub_a[i0], n1, i1);
        lemma_eq2_rank(tag_t, tag_v, hub_t[i0], hub_v[i0], n2, i2);
        lemma_eq3_rank(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n3, i3);
        let subs = eq_row_ids(sub_a, hub_a[i0], n1);
        let tags = eq_row_ids2(tag_t, tag_v, hub_t[i0], hub_v[i0], n2);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n3);
        let sr = ids_lt(subs, subs.len() as int, i1);
        let tr = ids_lt(tags, tags.len() as int, i2);
        let pr = ids_lt(pres, pres.len() as int, i3);
        let tlen = tags.len() as int;
        let plen = pres.len() as int;
        let tp = tlen * plen;
        let i0u = i0 as usize;
        let i1u = i1 as usize;
        let i2u = i2 as usize;
        let i3u = i3 as usize;
        assert(i0u as int == i0);
        assert(i1u as int == i1);
        assert(i2u as int == i2);
        assert(i3u as int == i3);
        lemma_quad_product_len(i0u, subs, tags, pres, subs.len() as int);
        let prod = quad_product(i0u, subs, tags, pres, subs.len() as int);
        assert(0 <= sr < subs.len());
        assert(0 <= tr < tlen);
        assert(0 <= pr < plen);
        assert(sr * tp + tr * plen + pr < prod.len()) by (nonlinear_arith)
            requires
                0 <= sr < subs.len(), 0 <= tr < tlen, 0 <= pr < plen,
                prod.len() == subs.len() * tp, tp == tlen * plen,
        {}
        lemma_quad_product_at(i0u, subs, tags, pres, subs.len() as int, sr, tr, pr);
        lemma_nested_quad_step(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0 + 1);
        let earlier = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0);
        let through = nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0 + 1);
        assert(through == earlier + prod);
        assert(prod[sr * tp + tr * plen + pr] == (i0u, subs[sr], tags[tr], pres[pr]));
        assert(subs[sr] as int == i1);
        assert(tags[tr] as int == i2);
        assert(pres[pr] as int == i3);
        assert(subs[sr] == i1u);
        assert(tags[tr] == i2u);
        assert(pres[pr] == i3u);
        lemma_right_index(earlier, prod, sr * tp + tr * plen + pr);
        assert(pos == earlier.len() as int + sr * tp + tr * plen + pr);
        assert(pos < through.len());
        lemma_nested_quad_len_mono(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0 + 1, n0,
        );
        assert(through.len() <= quads.len());
        assert(pos < quads.len());
        lemma_nested_quad_index(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0 + 1, n0, pos,
        );
        assert(quads[pos] == (i0u, i1u, i2u, i3u));
        assert(pos + 1 == quad_pos(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1, i2, i3 + 1,
        ));
        assert(loop_acc4(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, n3, i0, i1, i2, i3,
        ) == step(
            loop_acc4(
                hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
                step, base, n0, n1, n2, n3, i0, i1, i2, i3 + 1,
            ),
            i0, i1, i2, i3,
        ));
        assert(quad_acc(quads, step, base, pos) == step(
            quad_acc(quads, step, base, pos + 1), i0, i1, i2, i3,
        ));
    } else {
        lemma_quad_acc(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, n3, i0, i1, i2, i3 + 1,
        );
        let subs = eq_row_ids(sub_a, hub_a[i0], n1);
        let tags = eq_row_ids2(tag_t, tag_v, hub_t[i0], hub_v[i0], n2);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n3);
        if quad_sub(sub_a, hub_a[i0], i1) {
            if quad_tag(tag_t, tag_v, hub_t[i0], hub_v[i0], i2) {
                lemma_eq3_members(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n3);
                assert forall|p: int| 0 <= p < pres.len() implies (#[trigger] pres[p] as int) != i3 by {
                    assert(pre_a[(pres[p] as int)] == hub_a[i0]);
                    assert(pre_t[(pres[p] as int)] == hub_t[i0]);
                    assert(pre_v[(pres[p] as int)] == hub_v[i0]);
                };
                lemma_ids_lt_skip(pres, pres.len() as int, i3);
            }
        }
        assert(pos == quad_pos(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, i0, i1, i2, i3 + 1,
        ));
    }
}

/// Origin of the 4-table star match list: starting at (0,0,0,0) is position 0.
pub proof fn lemma_quad_pos_origin(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
)
    ensures
        quad_pos(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, 0, 0, 0, 0) == 0,
{
    assert(nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, 0)
        =~= Seq::<(usize, usize, usize, usize)>::empty());
    if hub_a.len() == 0 || hub_t.len() == 0 || hub_v.len() == 0 {
        assert(quad_pos(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, 0, 0, 0, 0) == 0);
    } else {
        let subs = eq_row_ids(sub_a, hub_a[0], sub_a.len() as int);
        let tags = eq_row_ids2(tag_t, tag_v, hub_t[0], hub_v[0], tag_t.len() as int);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[0], hub_t[0], hub_v[0], pre_a.len() as int);
        lemma_ids_lt_zero(subs, subs.len() as int);
        lemma_ids_lt_zero(tags, tags.len() as int);
        lemma_ids_lt_zero(pres, pres.len() as int);
        let tlen = tags.len() as int;
        let plen = pres.len() as int;
        vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(tlen * plen);
        vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(plen);
        assert(ids_lt(subs, subs.len() as int, 0) == 0);
        assert(0 * (tlen * plen) == 0);
        assert(0 * plen == 0);
        assert(quad_pos(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, 0, 0, 0, 0) == 0);
    }
}

/// At the origin indices, ``loop_acc4`` equals ``quad_acc`` of the star match list at 0.
pub proof fn lemma_quad_at_origin<A>(
    hub_a: Seq<Seq<char>>, hub_t: Seq<Seq<char>>, hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    tag_t: Seq<Seq<char>>, tag_v: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>, pre_t: Seq<Seq<char>>, pre_v: Seq<Seq<char>>,
    step: spec_fn(A, int, int, int, int) -> A,
    base: A,
    n0: int, n1: int, n2: int, n3: int,
)
    requires
        hub_a.len() == n0, hub_t.len() == n0, hub_v.len() == n0,
        sub_a.len() == n1,
        tag_t.len() == n2, tag_v.len() == n2,
        pre_a.len() == n3, pre_t.len() == n3, pre_v.len() == n3,
        n0 <= usize::MAX as int, n1 <= usize::MAX as int,
        n2 <= usize::MAX as int, n3 <= usize::MAX as int,
    ensures
        loop_acc4(
            hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, n3, 0, 0, 0, 0,
        ) == quad_acc(
            nested_quad(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v, n0),
            step, base, 0,
        ),
{
    lemma_quad_acc(
        hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v,
        step, base, n0, n1, n2, n3, 0, 0, 0, 0,
    );
    lemma_quad_pos_origin(hub_a, hub_t, hub_v, sub_a, tag_t, tag_v, pre_a, pre_t, pre_v);
}
// SHAPE_4TABLE_END

// SHAPE_LEFT3_BEGIN
// LEFT anti-join miss list on three String keys (holdout Q24: tag∧version∧adsh).
// Miss when eq_row_ids3 is empty; fold with miss_acc from the end.

/// Outer row ids in `0..n` with no three-column match, increasing.
pub open spec fn nested_anti_misses3<A, B, C>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    n: int,
) -> Seq<usize>
    decreases n,
{
    if n <= 0 {
        Seq::<usize>::empty()
    } else if n - 1 >= oa.len() || n - 1 >= ob.len() || n - 1 >= oc.len() {
        nested_anti_misses3(oa, ob, oc, ia, ib, ic, n - 1)
    } else {
        let prev = nested_anti_misses3(oa, ob, oc, ia, ib, ic, n - 1);
        if eq_row_ids3(ia, ib, ic, oa[n - 1], ob[n - 1], oc[n - 1], ia.len() as int).len() == 0 {
            prev.push((n - 1) as usize)
        } else {
            prev
        }
    }
}

pub proof fn lemma_nested_anti_misses3_step<A, B, C>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    n: int,
)
    requires
        0 < n <= oa.len(),
        n <= ob.len(),
        n <= oc.len(),
    ensures
        eq_row_ids3(ia, ib, ic, oa[n - 1], ob[n - 1], oc[n - 1], ia.len() as int).len()
            == 0 ==> nested_anti_misses3(oa, ob, oc, ia, ib, ic, n)
            == nested_anti_misses3(oa, ob, oc, ia, ib, ic, n - 1).push((n - 1) as usize),
        eq_row_ids3(ia, ib, ic, oa[n - 1], ob[n - 1], oc[n - 1], ia.len() as int).len()
            > 0 ==> nested_anti_misses3(oa, ob, oc, ia, ib, ic, n)
            == nested_anti_misses3(oa, ob, oc, ia, ib, ic, n - 1),
{
    if eq_row_ids3(ia, ib, ic, oa[n - 1], ob[n - 1], oc[n - 1], ia.len() as int).len() == 0 {
        assert(nested_anti_misses3(oa, ob, oc, ia, ib, ic, n)
            == nested_anti_misses3(oa, ob, oc, ia, ib, ic, n - 1).push((n - 1) as usize));
    } else {
        assert(nested_anti_misses3(oa, ob, oc, ia, ib, ic, n)
            == nested_anti_misses3(oa, ob, oc, ia, ib, ic, n - 1));
    }
}

pub open spec fn anti_loop_acc3<A, B, C, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
    i: int,
) -> Acc
    decreases n_outer - i,
{
    if i < n_outer {
        let tail = anti_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i + 1);
        if 0 <= i < oa.len() && i < ob.len() && i < oc.len() && eq_row_ids3(
            ia,
            ib,
            ic,
            oa[i],
            ob[i],
            oc[i],
            ia.len() as int,
        ).len() == 0 {
            step(tail, i)
        } else {
            tail
        }
    } else {
        base
    }
}

pub proof fn lemma_eq_row_ids3_empty_from_first<A, B, C>(
    a: Seq<A>,
    b: Seq<B>,
    c: Seq<C>,
    ka: A,
    kb: B,
    kc: C,
    end: int,
)
    requires
        0 <= end <= a.len(),
        a.len() == b.len(),
        a.len() == c.len(),
        end <= usize::MAX as int,
        eq_row_ids(a, ka, end).len() == 0,
    ensures
        eq_row_ids3(a, b, c, ka, kb, kc, end).len() == 0,
{
    lemma_filter_is_ids2(a, b, ka, kb, end);
    assert(eq_row_ids2(a, b, ka, kb, end) == filter_match(
        eq_row_ids(a, ka, end),
        b,
        kb,
        eq_row_ids(a, ka, end).len() as int,
    ));
    assert(eq_row_ids2(a, b, ka, kb, end).len() == 0);
    lemma_filter_is_ids3(a, b, c, ka, kb, kc, end);
    assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == filter_match(
        eq_row_ids2(a, b, ka, kb, end),
        c,
        kc,
        eq_row_ids2(a, b, ka, kb, end).len() as int,
    ));
}

pub proof fn lemma_eq_row_ids3_nonempty_iff<A, B, C>(
    a: Seq<A>,
    b: Seq<B>,
    c: Seq<C>,
    ka: A,
    kb: B,
    kc: C,
    end: int,
)
    requires
        0 <= end <= a.len(),
        a.len() == b.len(),
        a.len() == c.len(),
        end <= usize::MAX as int,
    ensures
        (eq_row_ids3(a, b, c, ka, kb, kc, end).len() > 0) <==> (exists|j: int|
            0 <= j < end && a[j] == ka && b[j] == kb && c[j] == kc),
    decreases end,
{
    if end > 0 {
        lemma_eq_row_ids3_nonempty_iff(a, b, c, ka, kb, kc, end - 1);
        let row = (end - 1) as usize;
        lemma_eq_row_ids3_step(a, b, c, ka, kb, kc, end - 1, row);
        if a[end - 1] == ka && b[end - 1] == kb && c[end - 1] == kc {
            assert(eq_row_ids3(a, b, c, ka, kb, kc, end).len() > 0);
            assert(exists|j: int| 0 <= j < end && a[j] == ka && b[j] == kb && c[j] == kc) by {
                assert(0 <= end - 1 < end && a[end - 1] == ka && b[end - 1] == kb && c[end - 1]
                    == kc);
            };
        } else {
            assert(eq_row_ids3(a, b, c, ka, kb, kc, end)
                == eq_row_ids3(a, b, c, ka, kb, kc, end - 1));
            assert((eq_row_ids3(a, b, c, ka, kb, kc, end).len() > 0) <==> (exists|j: int|
                0 <= j < end - 1 && a[j] == ka && b[j] == kb && c[j] == kc));
            assert((exists|j: int| 0 <= j < end && a[j] == ka && b[j] == kb && c[j] == kc)
                <==> (exists|j: int|
                0 <= j < end - 1 && a[j] == ka && b[j] == kb && c[j] == kc)) by {
                if exists|j: int| 0 <= j < end && a[j] == ka && b[j] == kb && c[j] == kc {
                    let j = choose|j: int|
                        0 <= j < end && a[j] == ka && b[j] == kb && c[j] == kc;
                    if j == end - 1 {
                        assert(a[end - 1] == ka && b[end - 1] == kb && c[end - 1] == kc);
                        assert(false);
                    } else {
                        assert(0 <= j < end - 1 && a[j] == ka && b[j] == kb && c[j] == kc);
                    }
                }
            };
        }
    } else {
        assert(eq_row_ids3(a, b, c, ka, kb, kc, 0).len() == 0);
        assert(!(exists|j: int| 0 <= j < 0 && a[j] == ka && b[j] == kb && c[j] == kc));
    }
}

pub proof fn lemma_anti_miss3_prefix<A, B, C>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    a: int,
    b: int,
)
    requires
        0 <= a <= b <= oa.len(),
        b <= ob.len(),
        b <= oc.len(),
        b <= usize::MAX as int,
    ensures
        nested_anti_misses3(oa, ob, oc, ia, ib, ic, a).len() <= nested_anti_misses3(
            oa,
            ob,
            oc,
            ia,
            ib,
            ic,
            b,
        ).len(),
        forall|p: int|
            0 <= p < nested_anti_misses3(oa, ob, oc, ia, ib, ic, a).len() ==> (
            #[trigger] nested_anti_misses3(oa, ob, oc, ia, ib, ic, b)[p]
            ) == nested_anti_misses3(oa, ob, oc, ia, ib, ic, a)[p],
    decreases b - a,
{
    if a < b {
        lemma_anti_miss3_prefix(oa, ob, oc, ia, ib, ic, a, b - 1);
        lemma_nested_anti_misses3_step(oa, ob, oc, ia, ib, ic, b);
        let at_a = nested_anti_misses3(oa, ob, oc, ia, ib, ic, a);
        let at_prev = nested_anti_misses3(oa, ob, oc, ia, ib, ic, b - 1);
        let at_b = nested_anti_misses3(oa, ob, oc, ia, ib, ic, b);
        let ids = eq_row_ids3(ia, ib, ic, oa[b - 1], ob[b - 1], oc[b - 1], ia.len() as int);
        if ids.len() == 0 {
            assert(at_b == at_prev.push((b - 1) as usize));
            assert(at_a.len() <= at_prev.len());
            assert(at_a.len() <= at_b.len());
            assert forall|p: int| 0 <= p < at_a.len() implies at_b[p] == at_a[p] by {
                lemma_seq_push_index_different(at_prev, (b - 1) as usize, p);
                assert(at_b[p] == at_prev[p]);
                assert(at_prev[p] == at_a[p]);
            };
        } else {
            assert(at_b == at_prev);
        }
    }
}

pub proof fn lemma_anti_miss3_at<A, B, C>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    n: int,
    i: int,
)
    requires
        0 <= i < n <= oa.len(),
        n <= ob.len(),
        n <= oc.len(),
        n <= usize::MAX as int,
        eq_row_ids3(ia, ib, ic, oa[i], ob[i], oc[i], ia.len() as int).len() == 0,
    ensures
        (nested_anti_misses3(oa, ob, oc, ia, ib, ic, i).len() as int) < nested_anti_misses3(
            oa,
            ob,
            oc,
            ia,
            ib,
            ic,
            n,
        ).len(),
        nested_anti_misses3(oa, ob, oc, ia, ib, ic, n)[nested_anti_misses3(
            oa,
            ob,
            oc,
            ia,
            ib,
            ic,
            i,
        ).len() as int] == i as usize,
{
    lemma_nested_anti_misses3_step(oa, ob, oc, ia, ib, ic, i + 1);
    assert(nested_anti_misses3(oa, ob, oc, ia, ib, ic, i + 1)
        == nested_anti_misses3(oa, ob, oc, ia, ib, ic, i).push(i as usize));
    lemma_anti_miss3_prefix(oa, ob, oc, ia, ib, ic, i + 1, n);
    let k = nested_anti_misses3(oa, ob, oc, ia, ib, ic, i).len() as int;
    assert(nested_anti_misses3(oa, ob, oc, ia, ib, ic, i + 1)[k] == i as usize);
    assert(nested_anti_misses3(oa, ob, oc, ia, ib, ic, n)[k]
        == nested_anti_misses3(oa, ob, oc, ia, ib, ic, i + 1)[k]);
}

pub proof fn lemma_anti_acc3<A, B, C, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
    i: int,
)
    requires
        oa.len() == n_outer,
        ob.len() == n_outer,
        oc.len() == n_outer,
        n_outer <= usize::MAX as int,
        0 <= i <= n_outer,
    ensures
        anti_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i) == miss_acc(
            nested_anti_misses3(oa, ob, oc, ia, ib, ic, n_outer),
            step,
            base,
            nested_anti_misses3(oa, ob, oc, ia, ib, ic, i).len() as int,
        ),
    decreases n_outer - i,
{
    if i < n_outer {
        lemma_anti_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i + 1);
        lemma_nested_anti_misses3_step(oa, ob, oc, ia, ib, ic, i + 1);
        let misses = nested_anti_misses3(oa, ob, oc, ia, ib, ic, n_outer);
        let k_i = nested_anti_misses3(oa, ob, oc, ia, ib, ic, i).len() as int;
        let ids = eq_row_ids3(ia, ib, ic, oa[i], ob[i], oc[i], ia.len() as int);
        if ids.len() == 0 {
            lemma_anti_miss3_at(oa, ob, oc, ia, ib, ic, n_outer, i);
            assert(misses[k_i] == i as usize);
            assert(0 <= k_i < misses.len());
            assert(anti_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i) == step(
                anti_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i + 1),
                i,
            ));
            assert(miss_acc(misses, step, base, k_i) == step(
                miss_acc(misses, step, base, k_i + 1),
                misses[k_i] as int,
            ));
        } else {
            assert(nested_anti_misses3(oa, ob, oc, ia, ib, ic, i + 1)
                == nested_anti_misses3(oa, ob, oc, ia, ib, ic, i));
        }
    }
}

pub proof fn lemma_anti3_at_origin<A, B, C, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
)
    requires
        oa.len() == n_outer,
        ob.len() == n_outer,
        oc.len() == n_outer,
        n_outer <= usize::MAX as int,
    ensures
        anti_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, 0) == miss_acc(
            nested_anti_misses3(oa, ob, oc, ia, ib, ic, n_outer),
            step,
            base,
            0,
        ),
{
    assert(nested_anti_misses3(oa, ob, oc, ia, ib, ic, 0) =~= Seq::<usize>::empty());
    lemma_anti_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, 0);
}

/// LEFT-anti miss ids for three `String` key columns. View equals [`nested_anti_misses3`].
pub fn anti_miss_rows_str3(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    outer2: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
    inner2: &Vec<String>,
) -> (misses: Vec<usize>)
    requires
        outer0@.len() == outer1@.len(),
        outer0@.len() == outer2@.len(),
        inner0@.len() == inner1@.len(),
        inner0@.len() == inner2@.len(),
    ensures
        misses@ == nested_anti_misses3(
            key_views(outer0@),
            key_views(outer1@),
            key_views(outer2@),
            key_views(inner0@),
            key_views(inner1@),
            key_views(inner2@),
            outer0@.len() as int,
        ),
{
    let idx = build_eq_index_str(inner0);
    let ghost oa = key_views(outer0@);
    let ghost ob = key_views(outer1@);
    let ghost oc = key_views(outer2@);
    let ghost ia = key_views(inner0@);
    let ghost ib = key_views(inner1@);
    let ghost ic = key_views(inner2@);
    let mut misses: Vec<usize> = Vec::new();
    let mut i: usize = 0;
    while i < outer0.len()
        invariant
            i <= outer0.len(),
            outer0@.len() == outer0.len() as int,
            outer1@.len() == outer0@.len(),
            outer2@.len() == outer0@.len(),
            inner0@.len() == inner0.len() as int,
            inner1@.len() == inner0@.len(),
            inner2@.len() == inner0@.len(),
            oa == key_views(outer0@),
            ob == key_views(outer1@),
            oc == key_views(outer2@),
            ia == key_views(inner0@),
            ib == key_views(inner1@),
            ic == key_views(inner2@),
            index_ok(ia, idx.buckets@, idx.map@, inner0@.len() as int),
            misses@ == nested_anti_misses3(oa, ob, oc, ia, ib, ic, i as int),
        decreases outer0.len() - i,
    {
        let key0 = &outer0[i];
        let key1 = &outer1[i];
        let key2 = &outer2[i];
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer0@, end);
            lemma_key_view_at(outer1@, end);
            lemma_key_view_at(outer2@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(oa[end] == key0@);
            assert(ob[end] == key1@);
            assert(oc[end] == key2@);
            assert(ia.len() as int <= usize::MAX as int);
        }
        let ghost before = misses@;
        let present = idx.map.contains_key(key0.as_str());
        if present {
            let got = idx.map.get(key0.as_str());
            let bi = *got.unwrap();
            proof {
                assert(idx.map@.contains_key(key0@));
                lemma_index_bucket(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_bounded(ia, key0@, ia.len() as int);
            }
            let ids = &idx.buckets[bi];
            let filtered2 = filter_row_ids_str(ids, inner1, key1);
            proof {
                lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                assert(filtered2@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                lemma_eq2_bounded(ia, ib, oa[end], ob[end], ia.len() as int);
                assert(ia.len() == inner2@.len());
                assert forall|t: int|
                    0 <= t < filtered2@.len() implies (#[trigger] filtered2@[t] as int)
                        < inner2@.len() by {
                    assert(
                        (eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int)[t] as int)
                            < ia.len()
                    );
                    assert(filtered2@[t]
                        == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int)[t]);
                };
            }
            let filtered3 = filter_row_ids_str(&filtered2, inner2, key2);
            if filtered3.len() == 0 {
                misses.push(i);
                proof {
                    lemma_filter_is_ids3(ia, ib, ic, key0@, key1@, key2@, ia.len() as int);
                    assert(filtered3@
                        == eq_row_ids3(ia, ib, ic, oa[end], ob[end], oc[end], ia.len() as int));
                    assert(eq_row_ids3(ia, ib, ic, oa[end], ob[end], oc[end], ia.len() as int)
                        .len() == 0);
                    lemma_nested_anti_misses3_step(oa, ob, oc, ia, ib, ic, end + 1);
                    assert(misses@ == before.push(i));
                    assert(misses@ == nested_anti_misses3(oa, ob, oc, ia, ib, ic, end + 1));
                }
            } else {
                proof {
                    lemma_filter_is_ids3(ia, ib, ic, key0@, key1@, key2@, ia.len() as int);
                    assert(filtered3@
                        == eq_row_ids3(ia, ib, ic, oa[end], ob[end], oc[end], ia.len() as int));
                    assert(eq_row_ids3(ia, ib, ic, oa[end], ob[end], oc[end], ia.len() as int)
                        .len() > 0);
                    lemma_nested_anti_misses3_step(oa, ob, oc, ia, ib, ic, end + 1);
                    assert(misses@ == nested_anti_misses3(oa, ob, oc, ia, ib, ic, end + 1));
                }
            }
        } else {
            misses.push(i);
            proof {
                assert(!idx.map@.contains_key(key0@));
                lemma_index_absent(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_len0(ia, key0@, ia.len() as int);
                lemma_eq_row_ids3_empty_from_first(
                    ia,
                    ib,
                    ic,
                    key0@,
                    key1@,
                    key2@,
                    ia.len() as int,
                );
                lemma_nested_anti_misses3_step(oa, ob, oc, ia, ib, ic, end + 1);
                assert(misses@ == before.push(i));
                assert(misses@ == nested_anti_misses3(oa, ob, oc, ia, ib, ic, end + 1));
            }
        }
        i = i + 1;
    }
    misses
}
// SHAPE_LEFT3_END

// SHAPE_ANTI_BEGIN
// ANTI JOIN keyword (two-table, one equality): miss rows = outer ids with no match.
// Reuses nested_anti_misses / anti_miss_rows_str / miss_acc / anti_loop_acc /
// lemma_anti_at_origin from SHAPE_LEFT — do not fork a second copy here.
// Transpiler emits lemma_<helper>_is_anti (+ _is_anti_loop) and method_is_fold.
// SHAPE_ANTI_END

// SHAPE_SEMI_BEGIN
// SEMI JOIN hit list: outer rows with at least one equijoin match (existence-only).
// Same order as join_semi_multi_agg_helper: increasing ids; fold from the end.

/// Outer row ids in `0..n` with a matching inner key, increasing.
pub open spec fn nested_semi_hits<K>(outer: Seq<K>, inner: Seq<K>, n: int) -> Seq<usize>
    decreases n,
{
    if n <= 0 {
        Seq::<usize>::empty()
    } else if n - 1 >= outer.len() {
        nested_semi_hits(outer, inner, n - 1)
    } else {
        let prev = nested_semi_hits(outer, inner, n - 1);
        if eq_row_ids(inner, outer[n - 1], inner.len() as int).len() > 0 {
            prev.push((n - 1) as usize)
        } else {
            prev
        }
    }
}

pub proof fn lemma_nested_semi_hits_step<K>(outer: Seq<K>, inner: Seq<K>, n: int)
    requires
        0 < n <= outer.len(),
    ensures
        eq_row_ids(inner, outer[n - 1], inner.len() as int).len() > 0 ==> nested_semi_hits(
            outer,
            inner,
            n,
        ) == nested_semi_hits(outer, inner, n - 1).push((n - 1) as usize),
        eq_row_ids(inner, outer[n - 1], inner.len() as int).len() == 0 ==> nested_semi_hits(
            outer,
            inner,
            n,
        ) == nested_semi_hits(outer, inner, n - 1),
{
    if eq_row_ids(inner, outer[n - 1], inner.len() as int).len() > 0 {
        assert(nested_semi_hits(outer, inner, n) == nested_semi_hits(outer, inner, n - 1).push(
            (n - 1) as usize,
        ));
    } else {
        assert(nested_semi_hits(outer, inner, n) == nested_semi_hits(outer, inner, n - 1));
    }
}

/// Nested-loop SEMI fold: on a hit, apply `step`; matches MethodSpec order.
pub open spec fn semi_loop_acc<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int) -> A,
    base: A,
    n_outer: int,
    i: int,
) -> A
    decreases n_outer - i,
{
    if i < n_outer {
        let tail = semi_loop_acc(outer, inner, step, base, n_outer, i + 1);
        if 0 <= i < outer.len() && eq_row_ids(inner, outer[i], inner.len() as int).len() > 0 {
            step(tail, i)
        } else {
            tail
        }
    } else {
        base
    }
}

/// Fold a hit-id list from the high index downward (same direction as MethodSpec).
pub open spec fn hit_acc<A>(
    hits: Seq<usize>,
    step: spec_fn(A, int) -> A,
    base: A,
    k: int,
) -> A
    decreases hits.len() - k,
{
    if k >= hits.len() {
        base
    } else {
        let tail = hit_acc(hits, step, base, k + 1);
        step(tail, hits[k] as int)
    }
}

/// Hit list for `a` is a prefix of the hit list for `b` (`a <= b`).
pub proof fn lemma_semi_hit_prefix<K>(outer: Seq<K>, inner: Seq<K>, a: int, b: int)
    requires
        0 <= a <= b <= outer.len(),
        b <= usize::MAX as int,
    ensures
        nested_semi_hits(outer, inner, a).len() <= nested_semi_hits(outer, inner, b).len(),
        forall|p: int|
            0 <= p < nested_semi_hits(outer, inner, a).len() ==> (#[trigger] nested_semi_hits(
                outer,
                inner,
                b,
            )[p]) == nested_semi_hits(outer, inner, a)[p],
    decreases b - a,
{
    if a < b {
        lemma_semi_hit_prefix(outer, inner, a, b - 1);
        lemma_nested_semi_hits_step(outer, inner, b);
        let at_a = nested_semi_hits(outer, inner, a);
        let at_prev = nested_semi_hits(outer, inner, b - 1);
        let at_b = nested_semi_hits(outer, inner, b);
        let ids = eq_row_ids(inner, outer[b - 1], inner.len() as int);
        if ids.len() > 0 {
            assert(at_b == at_prev.push((b - 1) as usize));
            assert(at_a.len() <= at_prev.len());
            assert(at_a.len() <= at_b.len());
            assert forall|p: int| 0 <= p < at_a.len() implies at_b[p] == at_a[p] by {
                lemma_seq_push_index_different(at_prev, (b - 1) as usize, p);
                assert(at_b[p] == at_prev[p]);
                assert(at_prev[p] == at_a[p]);
            };
        } else {
            assert(at_b == at_prev);
        }
    }
}

pub proof fn lemma_semi_hit_at<K>(outer: Seq<K>, inner: Seq<K>, n: int, i: int)
    requires
        0 <= i < n <= outer.len(),
        n <= usize::MAX as int,
        eq_row_ids(inner, outer[i], inner.len() as int).len() > 0,
    ensures
        (nested_semi_hits(outer, inner, i).len() as int) < nested_semi_hits(
            outer,
            inner,
            n,
        ).len(),
        nested_semi_hits(outer, inner, n)[nested_semi_hits(outer, inner, i).len() as int]
            == i as usize,
{
    lemma_nested_semi_hits_step(outer, inner, i + 1);
    assert(nested_semi_hits(outer, inner, i + 1) == nested_semi_hits(outer, inner, i).push(
        i as usize,
    ));
    lemma_semi_hit_prefix(outer, inner, i + 1, n);
    let k = nested_semi_hits(outer, inner, i).len() as int;
    assert(nested_semi_hits(outer, inner, i + 1)[k] == i as usize);
    assert(nested_semi_hits(outer, inner, n)[k] == nested_semi_hits(outer, inner, i + 1)[k]);
}

/// `semi_loop_acc` from left index `i` equals `hit_acc` from the hit-list suffix.
pub proof fn lemma_semi_acc<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int) -> A,
    base: A,
    n_outer: int,
    i: int,
)
    requires
        outer.len() == n_outer,
        n_outer <= usize::MAX as int,
        0 <= i <= n_outer,
    ensures
        semi_loop_acc(outer, inner, step, base, n_outer, i) == hit_acc(
            nested_semi_hits(outer, inner, n_outer),
            step,
            base,
            nested_semi_hits(outer, inner, i).len() as int,
        ),
    decreases n_outer - i,
{
    if i < n_outer {
        lemma_semi_acc(outer, inner, step, base, n_outer, i + 1);
        lemma_nested_semi_hits_step(outer, inner, i + 1);
        let hits = nested_semi_hits(outer, inner, n_outer);
        let k_i = nested_semi_hits(outer, inner, i).len() as int;
        let ids = eq_row_ids(inner, outer[i], inner.len() as int);
        if ids.len() > 0 {
            lemma_semi_hit_at(outer, inner, n_outer, i);
            assert(hits[k_i] == i as usize);
            assert(0 <= k_i < hits.len());
            assert(semi_loop_acc(outer, inner, step, base, n_outer, i) == step(
                semi_loop_acc(outer, inner, step, base, n_outer, i + 1),
                i,
            ));
            assert(hit_acc(hits, step, base, k_i) == step(
                hit_acc(hits, step, base, k_i + 1),
                hits[k_i] as int,
            ));
        } else {
            assert(nested_semi_hits(outer, inner, i + 1) == nested_semi_hits(outer, inner, i));
        }
    }
}

/// Origin: semi helper fold equals hit_acc of the full hit list at 0.
pub proof fn lemma_semi_at_origin<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int) -> A,
    base: A,
    n_outer: int,
)
    requires
        outer.len() == n_outer,
        n_outer <= usize::MAX as int,
    ensures
        semi_loop_acc(outer, inner, step, base, n_outer, 0) == hit_acc(
            nested_semi_hits(outer, inner, n_outer),
            step,
            base,
            0,
        ),
{
    assert(nested_semi_hits(outer, inner, 0) =~= Seq::<usize>::empty());
    lemma_semi_acc(outer, inner, step, base, n_outer, 0);
}

/// SEMI hit ids for one `String` key column. View equals [`nested_semi_hits`].
pub fn semi_hit_rows_str(outer: &Vec<String>, inner: &Vec<String>) -> (hits: Vec<usize>)
    ensures
        hits@ == nested_semi_hits(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    let idx = build_eq_index_str(inner);
    let ghost ov = key_views(outer@);
    let ghost iv = key_views(inner@);
    let mut hits: Vec<usize> = Vec::new();
    let mut i: usize = 0;
    while i < outer.len()
        invariant
            i <= outer.len(),
            outer@.len() == outer.len() as int,
            inner@.len() == inner.len() as int,
            ov == key_views(outer@),
            iv == key_views(inner@),
            index_ok(iv, idx.buckets@, idx.map@, inner@.len() as int),
            hits@ == nested_semi_hits(ov, iv, i as int),
        decreases outer.len() - i,
    {
        let key = outer[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(ov[end] == key@);
        }
        let ghost before = hits@;
        let hit = probe_eq_str(&idx, inner, key.as_str());
        match hit {
            Some(v) => {
                if v.len() == 0 {
                    proof {
                        assert(v@ == eq_row_ids(iv, key@, iv.len() as int));
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                        lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                        lemma_nested_semi_hits_step(ov, iv, end + 1);
                        assert(hits@ == nested_semi_hits(ov, iv, end + 1));
                    }
                } else {
                    hits.push(i);
                    proof {
                        assert(v@ == eq_row_ids(iv, key@, iv.len() as int));
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() > 0);
                        lemma_nested_semi_hits_step(ov, iv, end + 1);
                        assert(hits@ == before.push(i));
                        assert(hits@ == nested_semi_hits(ov, iv, end + 1));
                    }
                }
            },
            None => {
                proof {
                    assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                    lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                    lemma_nested_semi_hits_step(ov, iv, end + 1);
                    assert(hits@ == nested_semi_hits(ov, iv, end + 1));
                }
            },
        }
        i = i + 1;
    }
    hits
}

// SHAPE_SEMI_END
// SHAPE_PAIR3_BEGIN
// Two-table equijoin on three String keys (e.g. num⋈pre on adsh∧tag∧version).
// Exec list == nested_eq_pairs3; fold via loop_acc_pair3 (loop_acc3 is the star).

/// Nested match list for three equalities on the same outer/inner row pair.
pub open spec fn nested_eq_pairs3<A, B, C>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    outer_c: Seq<C>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    inner_c: Seq<C>,
    n: int,
) -> Seq<(usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize)>::empty()
    } else if n - 1 >= outer_a.len() || n - 1 >= outer_b.len() || n - 1 >= outer_c.len() {
        nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n - 1)
    } else {
        let i = (n - 1) as usize;
        let ids = eq_row_ids3(
            inner_a,
            inner_b,
            inner_c,
            outer_a[n - 1],
            outer_b[n - 1],
            outer_c[n - 1],
            inner_a.len() as int,
        );
        nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n - 1) + prefix_pairs(
            i,
            ids,
            ids.len() as int,
        )
    }
}

pub proof fn lemma_nested_eq_pairs3_step<A, B, C>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    outer_c: Seq<C>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    inner_c: Seq<C>,
    n: int,
)
    requires
        0 < n <= outer_a.len(),
        n <= outer_b.len(),
        n <= outer_c.len(),
        inner_a.len() == inner_b.len(),
        inner_a.len() == inner_c.len(),
    ensures
        nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n) == nested_eq_pairs3(
            outer_a,
            outer_b,
            outer_c,
            inner_a,
            inner_b,
            inner_c,
            n - 1,
        ) + prefix_pairs(
            (n - 1) as usize,
            eq_row_ids3(
                inner_a,
                inner_b,
                inner_c,
                outer_a[n - 1],
                outer_b[n - 1],
                outer_c[n - 1],
                inner_a.len() as int,
            ),
            eq_row_ids3(
                inner_a,
                inner_b,
                inner_c,
                outer_a[n - 1],
                outer_b[n - 1],
                outer_c[n - 1],
                inner_a.len() as int,
            ).len() as int,
        ),
{
}

/// Equijoin on three string columns (for example `adsh`, `tag`, and `version`).
pub fn equijoin_pairs_str3(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    outer2: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
    inner2: &Vec<String>,
) -> (pairs: Vec<(usize, usize)>)
    requires
        outer0@.len() == outer1@.len(),
        outer0@.len() == outer2@.len(),
        inner0@.len() == inner1@.len(),
        inner0@.len() == inner2@.len(),
    ensures
        pairs@ == nested_eq_pairs3(
            key_views(outer0@),
            key_views(outer1@),
            key_views(outer2@),
            key_views(inner0@),
            key_views(inner1@),
            key_views(inner2@),
            outer0@.len() as int,
        ),
{
    let idx = build_eq_index_str(inner0);
    let ghost oa = key_views(outer0@);
    let ghost ob = key_views(outer1@);
    let ghost oc = key_views(outer2@);
    let ghost ia = key_views(inner0@);
    let ghost ib = key_views(inner1@);
    let ghost ic = key_views(inner2@);
    let mut pairs: Vec<(usize, usize)> = Vec::new();
    let mut i: usize = 0;
    while i < outer0.len()
        invariant
            i <= outer0.len(),
            outer0@.len() == outer0.len() as int,
            outer1@.len() == outer0@.len(),
            outer2@.len() == outer0@.len(),
            inner0@.len() == inner0.len() as int,
            inner1@.len() == inner0@.len(),
            inner2@.len() == inner0@.len(),
            oa == key_views(outer0@),
            ob == key_views(outer1@),
            oc == key_views(outer2@),
            ia == key_views(inner0@),
            ib == key_views(inner1@),
            ic == key_views(inner2@),
            index_ok(ia, idx.buckets@, idx.map@, inner0@.len() as int),
            pairs@ == nested_eq_pairs3(oa, ob, oc, ia, ib, ic, i as int),
        decreases outer0.len() - i,
    {
        let key0 = outer0[i].clone();
        let key1 = outer1[i].clone();
        let key2 = outer2[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer0@, end);
            lemma_key_view_at(outer1@, end);
            lemma_key_view_at(outer2@, end);
            assert(oa[end] == key0@);
            assert(ob[end] == key1@);
            assert(oc[end] == key2@);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            broadcast use vstd::seq::lemma_seq_new_len;
            assert(inner0@.len() == inner0.len() as int);
            assert(ia.len() == inner0@.len());
            assert(ia.len() as int <= usize::MAX as int);
        }
        let ghost before = pairs@;
        let present = idx.map.contains_key(key0.as_str());
        if present {
            let got = idx.map.get(key0.as_str());
            let bi = *got.unwrap();
            proof {
                assert(idx.map@.contains_key(key0@));
                lemma_index_bucket(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_bounded(ia, key0@, ia.len() as int);
            }
            let ids = &idx.buckets[bi];
            let mid = filter_row_ids_str(ids, inner1, &key1);
            proof {
                lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                assert(mid@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                lemma_eq2_bounded(ia, ib, oa[end], ob[end], ia.len() as int);
                assert forall|t: int|
                    0 <= t < mid@.len() implies (#[trigger] mid@[t] as int) < inner2@.len() by {
                    assert(
                        (eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int)[t] as int)
                            < ia.len()
                    );
                    assert(mid@[t] == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int)[t]);
                    assert(ia.len() == inner2@.len());
                };
            }
            let filtered = filter_row_ids_str(&mid, inner2, &key2);
            push_prefix_pairs(&mut pairs, i, &filtered);
            proof {
                lemma_filter_is_ids3(ia, ib, ic, key0@, key1@, key2@, ia.len() as int);
                assert(filtered@ == eq_row_ids3(ia, ib, ic, oa[end], ob[end], oc[end], ia.len() as int));
                lemma_nested_eq_pairs3_step(oa, ob, oc, ia, ib, ic, end + 1);
                assert(pairs@ == nested_eq_pairs3(oa, ob, oc, ia, ib, ic, end + 1));
            }
        } else {
            proof {
                assert(!idx.map@.contains_key(key0@));
                lemma_index_absent(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_len0(ia, key0@, ia.len() as int);
                lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                lemma_filter_is_ids3(ia, ib, ic, key0@, key1@, key2@, ia.len() as int);
                lemma_nested_eq_pairs3_step(oa, ob, oc, ia, ib, ic, end + 1);
                lemma_seq_add_empty(before);
                assert(pairs@ == nested_eq_pairs3(oa, ob, oc, ia, ib, ic, end + 1));
            }
        }
        i = i + 1;
    }
    pairs
}

/// Position of `(i0, i1)` in a three-column nested match list.
pub open spec fn pair_pos3<A, B, C>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    outer_c: Seq<C>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    inner_c: Seq<C>,
    i0: int,
    i1: int,
) -> int {
    if !(0 <= i0 < outer_a.len() && i0 < outer_b.len() && i0 < outer_c.len()) {
        nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0).len() as int
    } else {
        let ids = eq_row_ids3(
            inner_a,
            inner_b,
            inner_c,
            outer_a[i0],
            outer_b[i0],
            outer_c[i0],
            inner_a.len() as int,
        );
        nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0).len() as int
            + ids_lt(ids, ids.len() as int, i1)
    }
}

/// Nested loop over three equalities, same order as a two-table helper.
pub open spec fn loop_acc_pair3<A, B, C, Acc>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    outer_c: Seq<C>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    inner_c: Seq<C>,
    step: spec_fn(Acc, int, int) -> Acc,
    base: Acc,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
) -> Acc
    decreases n_outer - i0, n_inner - i1,
{
    if i0 < n_outer {
        if i1 < n_inner {
            let tail = loop_acc_pair3(
                outer_a,
                outer_b,
                outer_c,
                inner_a,
                inner_b,
                inner_c,
                step,
                base,
                n_outer,
                n_inner,
                i0,
                i1 + 1,
            );
            if 0 <= i0 < outer_a.len() && 0 <= i0 < outer_b.len() && 0 <= i0 < outer_c.len()
                && 0 <= i1 < inner_a.len() && 0 <= i1 < inner_b.len() && 0 <= i1 < inner_c.len()
                && outer_a[i0] == inner_a[i1] && outer_b[i0] == inner_b[i1]
                && outer_c[i0] == inner_c[i1]
            {
                step(tail, i0, i1)
            } else {
                tail
            }
        } else {
            loop_acc_pair3(
                outer_a,
                outer_b,
                outer_c,
                inner_a,
                inner_b,
                inner_c,
                step,
                base,
                n_outer,
                n_inner,
                i0 + 1,
                0,
            )
        }
    } else {
        base
    }
}

pub proof fn lemma_nested_len_mono_pair3<A, B, C>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    outer_c: Seq<C>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    inner_c: Seq<C>,
    n: int,
    m: int,
)
    requires
        0 <= n <= m,
    ensures
        nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n).len()
            <= nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, m).len(),
    decreases m - n,
{
    if n < m {
        lemma_nested_len_mono_pair3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n, m - 1);
        let cur = nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, m);
        let prev = nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, m - 1);
        if m - 1 >= outer_a.len() || m - 1 >= outer_b.len() || m - 1 >= outer_c.len() {
            assert(cur == prev);
        } else {
            let ids = eq_row_ids3(
                inner_a,
                inner_b,
                inner_c,
                outer_a[m - 1],
                outer_b[m - 1],
                outer_c[m - 1],
                inner_a.len() as int,
            );
            let extra = prefix_pairs((m - 1) as usize, ids, ids.len() as int);
            assert(cur == prev + extra);
            assert(prev.len() <= cur.len());
        }
    }
}

pub proof fn lemma_nested_index_pair3<A, B, C>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    outer_c: Seq<C>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    inner_c: Seq<C>,
    n: int,
    m: int,
    p: int,
)
    requires
        0 <= n <= m,
        0 <= p < nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n).len(),
    ensures
        nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, m)[p]
            == nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n)[p],
    decreases m - n,
{
    if n < m {
        let cur = nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, m);
        let prev = nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, m - 1);
        lemma_nested_len_mono_pair3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n, m - 1);
        if m - 1 >= outer_a.len() || m - 1 >= outer_b.len() || m - 1 >= outer_c.len() {
            assert(cur == prev);
        } else {
            let i = (m - 1) as usize;
            let ids = eq_row_ids3(
                inner_a,
                inner_b,
                inner_c,
                outer_a[m - 1],
                outer_b[m - 1],
                outer_c[m - 1],
                inner_a.len() as int,
            );
            let extra = prefix_pairs(i, ids, ids.len() as int);
            assert(cur == prev + extra);
            assert(p < prev.len());
            lemma_left_index(prev, extra, p);
        }
        lemma_nested_index_pair3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n, m - 1, p);
    }
}

pub proof fn lemma_acc_pair3<A, B, C, Acc>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    outer_c: Seq<C>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    inner_c: Seq<C>,
    step: spec_fn(Acc, int, int) -> Acc,
    base: Acc,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
)
    requires
        outer_a.len() == n_outer,
        outer_b.len() == n_outer,
        outer_c.len() == n_outer,
        inner_a.len() == n_inner,
        inner_b.len() == n_inner,
        inner_c.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
        0 <= i0 <= n_outer,
        0 <= i1 <= n_inner,
    ensures
        loop_acc_pair3(
            outer_a,
            outer_b,
            outer_c,
            inner_a,
            inner_b,
            inner_c,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1,
        ) == pair_acc(
            nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n_outer),
            step,
            base,
            pair_pos3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0, i1),
        ),
    decreases n_outer - i0, n_inner - i1,
{
    let pairs = nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n_outer);
    let pos = pair_pos3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0, i1);
    if i0 >= n_outer {
        assert(nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0) =~= pairs);
        assert(pos == pairs.len() as int);
    } else if i1 >= n_inner {
        lemma_acc_pair3(
            outer_a,
            outer_b,
            outer_c,
            inner_a,
            inner_b,
            inner_c,
            step,
            base,
            n_outer,
            n_inner,
            i0 + 1,
            0,
        );
        let ids = eq_row_ids3(inner_a, inner_b, inner_c, outer_a[i0], outer_b[i0], outer_c[i0], n_inner);
        lemma_eq3_members(inner_a, inner_b, inner_c, outer_a[i0], outer_b[i0], outer_c[i0], n_inner);
        assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < n_inner by {
            assert(0 <= (ids[p] as int) < n_inner);
        };
        assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < i1 by {
            assert((ids[p] as int) < n_inner);
            assert(n_inner <= i1);
        };
        lemma_ids_lt_all(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_len(i0u, ids, ids.len() as int);
        lemma_nested_eq_pairs3_step(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0 + 1);
        assert(nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0 + 1).len()
            == nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0).len()
                + ids.len());
        if i0 + 1 < outer_a.len() {
            let next_ids = eq_row_ids3(
                inner_a,
                inner_b,
                inner_c,
                outer_a[i0 + 1],
                outer_b[i0 + 1],
                outer_c[i0 + 1],
                n_inner,
            );
            lemma_ids_lt_zero(next_ids, next_ids.len() as int);
        }
        assert(pair_pos3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0 + 1, 0) == pos);
    } else if outer_a[i0] == inner_a[i1] && outer_b[i0] == inner_b[i1] && outer_c[i0] == inner_c[i1] {
        lemma_acc_pair3(
            outer_a,
            outer_b,
            outer_c,
            inner_a,
            inner_b,
            inner_c,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1 + 1,
        );
        lemma_eq3_rank(inner_a, inner_b, inner_c, outer_a[i0], outer_b[i0], outer_c[i0], n_inner, i1);
        let ids = eq_row_ids3(inner_a, inner_b, inner_c, outer_a[i0], outer_b[i0], outer_c[i0], n_inner);
        let r = ids_lt(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_len(i0u, ids, ids.len() as int);
        lemma_prefix_at(i0u, ids, ids.len() as int, r);
        let row_pairs = prefix_pairs(i0u, ids, ids.len() as int);
        let earlier = nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0);
        let through = nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0 + 1);
        lemma_nested_eq_pairs3_step(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0 + 1);
        assert(through == earlier + row_pairs);
        assert(i1 <= usize::MAX as int);
        let i1u = i1 as usize;
        assert(i1u as int == i1);
        assert(row_pairs[r] == (i0u, i1u));
        assert(0 <= r < row_pairs.len());
        lemma_right_index(earlier, row_pairs, r);
        assert(pos == earlier.len() as int + r);
        assert(through.len() == earlier.len() + row_pairs.len());
        assert(pos < through.len());
        lemma_nested_len_mono_pair3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0 + 1, n_outer);
        assert(through.len() <= pairs.len());
        assert(pos < pairs.len());
        lemma_nested_index_pair3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0 + 1, n_outer, pos);
        assert(through[pos] == (i0u, i1u));
        assert(pairs[pos] == (i0u, i1u));
        assert(pos + 1 == pair_pos3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0, i1 + 1));
        assert(loop_acc_pair3(
            outer_a,
            outer_b,
            outer_c,
            inner_a,
            inner_b,
            inner_c,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1,
        ) == step(
            loop_acc_pair3(
                outer_a,
                outer_b,
                outer_c,
                inner_a,
                inner_b,
                inner_c,
                step,
                base,
                n_outer,
                n_inner,
                i0,
                i1 + 1,
            ),
            i0,
            i1,
        ));
        assert(pair_acc(pairs, step, base, pos) == step(pair_acc(pairs, step, base, pos + 1), i0, i1));
    } else {
        lemma_acc_pair3(
            outer_a,
            outer_b,
            outer_c,
            inner_a,
            inner_b,
            inner_c,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1 + 1,
        );
        let ids = eq_row_ids3(inner_a, inner_b, inner_c, outer_a[i0], outer_b[i0], outer_c[i0], n_inner);
        lemma_eq3_members(inner_a, inner_b, inner_c, outer_a[i0], outer_b[i0], outer_c[i0], n_inner);
        assert forall|p: int| 0 <= p < ids.len() implies (#[trigger] ids[p] as int) != i1 by {
            assert(inner_a[(ids[p] as int)] == outer_a[i0]);
            assert(inner_b[(ids[p] as int)] == outer_b[i0]);
            assert(inner_c[(ids[p] as int)] == outer_c[i0]);
        };
        lemma_ids_lt_skip(ids, ids.len() as int, i1);
        assert(pos == pair_pos3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, i0, i1 + 1));
    }
}

/// Origin of the three-column nested match list: starting at (0, 0) is position 0.
pub proof fn lemma_pair_pos3_origin<A, B, C>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    outer_c: Seq<C>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    inner_c: Seq<C>,
)
    ensures
        pair_pos3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, 0, 0) == 0,
{
    assert(nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, 0)
        =~= Seq::<(usize, usize)>::empty());
    if outer_a.len() == 0 || outer_b.len() == 0 || outer_c.len() == 0 {
        assert(pair_pos3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, 0, 0) == 0);
    } else {
        let ids = eq_row_ids3(
            inner_a,
            inner_b,
            inner_c,
            outer_a[0],
            outer_b[0],
            outer_c[0],
            inner_a.len() as int,
        );
        lemma_ids_lt_zero(ids, ids.len() as int);
        assert(pair_pos3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, 0, 0) == 0);
    }
}

/// At the origin indices, ``loop_acc_pair3`` equals ``pair_acc`` of the three-column match list at 0.
pub proof fn lemma_loop_pair3_at_origin<A, B, C, Acc>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    outer_c: Seq<C>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    inner_c: Seq<C>,
    step: spec_fn(Acc, int, int) -> Acc,
    base: Acc,
    n_outer: int,
    n_inner: int,
)
    requires
        outer_a.len() == n_outer,
        outer_b.len() == n_outer,
        outer_c.len() == n_outer,
        inner_a.len() == n_inner,
        inner_b.len() == n_inner,
        inner_c.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
    ensures
        loop_acc_pair3(
            outer_a,
            outer_b,
            outer_c,
            inner_a,
            inner_b,
            inner_c,
            step,
            base,
            n_outer,
            n_inner,
            0,
            0,
        ) == pair_acc(
            nested_eq_pairs3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, n_outer),
            step,
            base,
            0,
        ),
{
    lemma_acc_pair3(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c, step, base, n_outer, n_inner, 0, 0);
    lemma_pair_pos3_origin(outer_a, outer_b, outer_c, inner_a, inner_b, inner_c);
}
// SHAPE_PAIR3_END
// SHAPE_OR_BEGIN
// OR of two equalities: match list is outer-major, inner-increasing ids where
// either predicate holds (once per row pair — same as nested-loop `A || B`).

/// Inner ids `0..end` where `a[j] == ka || b[j] == kb`, increasing.
pub open spec fn or_match_ids<A, B>(
    a: Seq<A>,
    ka: A,
    b: Seq<B>,
    kb: B,
    end: int,
) -> Seq<usize>
    decreases end,
{
    if end <= 0 {
        Seq::<usize>::empty()
    } else {
        let prev = or_match_ids(a, ka, b, kb, end - 1);
        if 0 <= end - 1 < a.len() && 0 <= end - 1 < b.len() {
            if a[end - 1] == ka || b[end - 1] == kb {
                prev.push((end - 1) as usize)
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

/// Matches between `outer[0..n]` and `inner` under `A || B`, outer-major.
pub open spec fn nested_or_eq_pairs<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    n: int,
) -> Seq<(usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize)>::empty()
    } else if n - 1 >= outer_a.len() || n - 1 >= outer_b.len() {
        nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, n - 1)
    } else {
        let i = (n - 1) as usize;
        let ids = or_match_ids(
            inner_a,
            outer_a[n - 1],
            inner_b,
            outer_b[n - 1],
            inner_a.len() as int,
        );
        nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, n - 1) + prefix_pairs(
            i,
            ids,
            ids.len() as int,
        )
    }
}

pub proof fn lemma_or_match_ids_step<A, B>(a: Seq<A>, ka: A, b: Seq<B>, kb: B, end: int, row: usize)
    requires
        0 <= end < a.len(),
        end < b.len(),
        a.len() == b.len(),
        row as int == end,
    ensures
        (a[end] == ka || b[end] == kb) ==> or_match_ids(a, ka, b, kb, end + 1) == or_match_ids(
            a,
            ka,
            b,
            kb,
            end,
        ).push(row),
        !(a[end] == ka || b[end] == kb) ==> or_match_ids(a, ka, b, kb, end + 1) == or_match_ids(
            a,
            ka,
            b,
            kb,
            end,
        ),
{
    assert((row as int) as usize == row);
    let prev = or_match_ids(a, ka, b, kb, end);
    let next = or_match_ids(a, ka, b, kb, end + 1);
    if a[end] == ka || b[end] == kb {
        assert(next == prev.push(row));
    } else {
        assert(next == prev);
    }
}

pub proof fn lemma_nested_or_eq_pairs_step<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    n: int,
)
    requires
        0 < n <= outer_a.len(),
        n <= outer_b.len(),
        inner_a.len() == inner_b.len(),
    ensures
        ({
            let i = (n - 1) as usize;
            let ids = or_match_ids(
                inner_a,
                outer_a[n - 1],
                inner_b,
                outer_b[n - 1],
                inner_a.len() as int,
            );
            nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, n) == nested_or_eq_pairs(
                outer_a,
                inner_a,
                outer_b,
                inner_b,
                n - 1,
            ) + prefix_pairs(i, ids, ids.len() as int)
        }),
{
    let i = (n - 1) as usize;
    let ids = or_match_ids(
        inner_a,
        outer_a[n - 1],
        inner_b,
        outer_b[n - 1],
        inner_a.len() as int,
    );
    assert(nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, n) == nested_or_eq_pairs(
        outer_a,
        inner_a,
        outer_b,
        inner_b,
        n - 1,
    ) + prefix_pairs(i, ids, ids.len() as int));
}

/// Nested-loop fold with OR match — same order as `_gen_nested_loop` `full_cond`.
pub open spec fn or_loop_acc<A, B, C>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    step: spec_fn(C, int, int) -> C,
    base: C,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
) -> C
    decreases n_outer - i0, n_inner - i1,
{
    if i0 < n_outer {
        if i1 < n_inner {
            let tail = or_loop_acc(
                outer_a,
                inner_a,
                outer_b,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0,
                i1 + 1,
            );
            if 0 <= i0 < outer_a.len() && 0 <= i0 < outer_b.len() && 0 <= i1 < inner_a.len() && 0
                <= i1 < inner_b.len() && (outer_a[i0] == inner_a[i1] || outer_b[i0] == inner_b[i1]) {
                step(tail, i0, i1)
            } else {
                tail
            }
        } else {
            or_loop_acc(outer_a, inner_a, outer_b, inner_b, step, base, n_outer, n_inner, i0 + 1, 0)
        }
    } else {
        base
    }
}

pub open spec fn or_pair_pos<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    i0: int,
    i1: int,
) -> int {
    if !(0 <= i0 < outer_a.len()) || !(0 <= i0 < outer_b.len()) {
        nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, i0).len() as int
    } else {
        let ids = or_match_ids(inner_a, outer_a[i0], inner_b, outer_b[i0], inner_a.len() as int);
        nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, i0).len() as int + ids_lt(
            ids,
            ids.len() as int,
            i1,
        )
    }
}

pub proof fn lemma_or_members<A, B>(a: Seq<A>, ka: A, b: Seq<B>, kb: B, end: int)
    requires
        0 <= end <= a.len(),
        end <= b.len(),
        a.len() == b.len(),
        end <= usize::MAX as int,
    ensures
        forall|p: int|
            0 <= p < or_match_ids(a, ka, b, kb, end).len() ==> {
                let row = #[trigger] or_match_ids(a, ka, b, kb, end)[p] as int;
                0 <= row < end && (a[row] == ka || b[row] == kb)
            },
    decreases end,
{
    if end > 0 {
        assert(0 <= end - 1 <= usize::MAX as int);
        lemma_or_members(a, ka, b, kb, end - 1);
        let prev = or_match_ids(a, ka, b, kb, end - 1);
        let cur = or_match_ids(a, ka, b, kb, end);
        if 0 <= end - 1 < a.len() && 0 <= end - 1 < b.len() {
            if a[end - 1] == ka || b[end - 1] == kb {
                let row = (end - 1) as usize;
                assert(row as int == end - 1);
                assert(cur == prev.push(row));
                assert forall|p: int| 0 <= p < cur.len() implies ({
                    let r = #[trigger] cur[p] as int;
                    0 <= r < end && (a[r] == ka || b[r] == kb)
                }) by {
                    if p < prev.len() {
                        assert(cur[p] == prev[p]);
                    } else {
                        assert(cur[p] == row);
                    }
                };
            } else {
                assert(cur == prev);
            }
        } else {
            assert(cur == prev);
        }
    }
}

pub proof fn lemma_or_rank<A, B>(a: Seq<A>, ka: A, b: Seq<B>, kb: B, end: int, row: int)
    requires
        0 <= row < end <= a.len(),
        end <= b.len(),
        a.len() == b.len(),
        a[row] == ka || b[row] == kb,
        end <= usize::MAX as int,
    ensures
        ({
            let ids = or_match_ids(a, ka, b, kb, end);
            let r = ids_lt(ids, ids.len() as int, row);
            &&& 0 <= r < ids.len()
            &&& ids[r] as int == row
            &&& ids_lt(ids, ids.len() as int, row + 1) == r + 1
        }),
    decreases end - row,
{
    let prev = or_match_ids(a, ka, b, kb, end - 1);
    let cur = or_match_ids(a, ka, b, kb, end);
    if end == row + 1 {
        let pushed = (end - 1) as usize;
        assert(0 <= end - 1 <= usize::MAX as int);
        assert(pushed as int == end - 1);
        assert(cur == prev.push(pushed));
        lemma_or_members(a, ka, b, kb, row);
        lemma_ids_lt_all(prev, prev.len() as int, row);
        lemma_ids_lt_all(prev, prev.len() as int, row + 1);
        lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row);
        lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row + 1);
        assert(ids_lt(cur, prev.len() as int, row) == prev.len() as int);
        assert(ids_lt(cur, prev.len() as int, row + 1) == prev.len() as int);
        assert((pushed as int) < row + 1);
        assert(cur.len() == prev.len() + 1);
        assert(ids_lt(cur, cur.len() as int, row) == prev.len() as int);
        assert(ids_lt(cur, cur.len() as int, row + 1) == prev.len() as int + 1);
        assert(cur[prev.len() as int] == pushed);
    } else {
        lemma_or_rank(a, ka, b, kb, end - 1, row);
        let pushed = (end - 1) as usize;
        assert(0 <= end - 1 <= usize::MAX as int);
        assert(pushed as int == end - 1);
        assert(pushed as int > row);
        if 0 <= end - 1 < a.len() && 0 <= end - 1 < b.len() {
            if a[end - 1] == ka || b[end - 1] == kb {
                assert(cur == prev.push(pushed));
                lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row);
                lemma_ids_lt_push_prefix(prev, pushed, prev.len() as int, row + 1);
                let r = ids_lt(prev, prev.len() as int, row);
                assert(ids_lt(cur, cur.len() as int, row) == r);
                assert(ids_lt(cur, cur.len() as int, row + 1) == r + 1);
                assert(cur[r] == prev[r]);
            } else {
                assert(cur == prev);
            }
        } else {
            assert(cur == prev);
        }
    }
}

pub proof fn lemma_nested_or_len_mono<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    n: int,
    m: int,
)
    requires
        0 <= n <= m <= outer_a.len(),
        m <= outer_b.len(),
        inner_a.len() == inner_b.len(),
    ensures
        nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, n).len() <= nested_or_eq_pairs(
            outer_a,
            inner_a,
            outer_b,
            inner_b,
            m,
        ).len(),
    decreases m - n,
{
    if n < m {
        let cur = nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, m);
        let prev = nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, m - 1);
        lemma_nested_or_eq_pairs_step(outer_a, inner_a, outer_b, inner_b, m);
        assert(prev.len() <= cur.len());
        lemma_nested_or_len_mono(outer_a, inner_a, outer_b, inner_b, n, m - 1);
    }
}

pub proof fn lemma_nested_or_index<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    n: int,
    m: int,
    p: int,
)
    requires
        0 <= n <= m <= outer_a.len(),
        m <= outer_b.len(),
        inner_a.len() == inner_b.len(),
        0 <= p < nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, n).len(),
    ensures
        nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, m)[p] == nested_or_eq_pairs(
            outer_a,
            inner_a,
            outer_b,
            inner_b,
            n,
        )[p],
    decreases m - n,
{
    if n < m {
        let cur = nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, m);
        let prev = nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, m - 1);
        lemma_nested_or_len_mono(outer_a, inner_a, outer_b, inner_b, n, m - 1);
        if m - 1 >= outer_a.len() || m - 1 >= outer_b.len() {
            assert(cur == prev);
        } else {
            lemma_nested_or_eq_pairs_step(outer_a, inner_a, outer_b, inner_b, m);
            let i = (m - 1) as usize;
            let ids = or_match_ids(
                inner_a,
                outer_a[m - 1],
                inner_b,
                outer_b[m - 1],
                inner_a.len() as int,
            );
            let extra = prefix_pairs(i, ids, ids.len() as int);
            assert(cur == prev + extra);
            assert(p < prev.len());
            lemma_left_index(prev, extra, p);
        }
        lemma_nested_or_index(outer_a, inner_a, outer_b, inner_b, n, m - 1, p);
    }
}

pub proof fn lemma_or_acc<A, B, C>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    step: spec_fn(C, int, int) -> C,
    base: C,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
)
    requires
        outer_a.len() == n_outer,
        outer_b.len() == n_outer,
        inner_a.len() == n_inner,
        inner_b.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
        0 <= i0 <= n_outer,
        0 <= i1 <= n_inner,
    ensures
        or_loop_acc(outer_a, inner_a, outer_b, inner_b, step, base, n_outer, n_inner, i0, i1)
            == pair_acc(
            nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, n_outer),
            step,
            base,
            or_pair_pos(outer_a, inner_a, outer_b, inner_b, i0, i1),
        ),
    decreases n_outer - i0, n_inner - i1,
{
    let pairs = nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, n_outer);
    let pos = or_pair_pos(outer_a, inner_a, outer_b, inner_b, i0, i1);
    if i0 >= n_outer {
        assert(nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, i0) =~= pairs);
        assert(pos == pairs.len() as int);
    } else if i1 >= n_inner {
        lemma_or_acc(outer_a, inner_a, outer_b, inner_b, step, base, n_outer, n_inner, i0 + 1, 0);
        let ids = or_match_ids(inner_a, outer_a[i0], inner_b, outer_b[i0], n_inner);
        lemma_or_members(inner_a, outer_a[i0], inner_b, outer_b[i0], n_inner);
        assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < n_inner by {
            assert(0 <= (ids[p] as int) < n_inner);
        };
        assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < i1 by {
            assert((ids[p] as int) < n_inner);
            assert(n_inner <= i1);
        };
        lemma_ids_lt_all(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_len(i0u, ids, ids.len() as int);
        assert(nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, i0 + 1).len()
            == nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, i0).len() + ids.len());
        if i0 + 1 < outer_a.len() {
            let next_ids = or_match_ids(
                inner_a,
                outer_a[i0 + 1],
                inner_b,
                outer_b[i0 + 1],
                n_inner,
            );
            lemma_ids_lt_zero(next_ids, next_ids.len() as int);
        }
        assert(or_pair_pos(outer_a, inner_a, outer_b, inner_b, i0 + 1, 0) == pos);
    } else if outer_a[i0] == inner_a[i1] || outer_b[i0] == inner_b[i1] {
        lemma_or_acc(outer_a, inner_a, outer_b, inner_b, step, base, n_outer, n_inner, i0, i1 + 1);
        lemma_or_rank(inner_a, outer_a[i0], inner_b, outer_b[i0], n_inner, i1);
        let ids = or_match_ids(inner_a, outer_a[i0], inner_b, outer_b[i0], n_inner);
        let r = ids_lt(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_len(i0u, ids, ids.len() as int);
        lemma_prefix_at(i0u, ids, ids.len() as int, r);
        let row_pairs = prefix_pairs(i0u, ids, ids.len() as int);
        let earlier = nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, i0);
        let through = nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, i0 + 1);
        assert(through == earlier + row_pairs);
        assert(i1 as int <= usize::MAX as int);
        let i1u = i1 as usize;
        assert(i1u as int == i1);
        assert(row_pairs[r] == (i0u, i1u));
        assert(0 <= r < row_pairs.len());
        lemma_right_index(earlier, row_pairs, r);
        assert(pos == earlier.len() as int + r);
        assert(through.len() == earlier.len() + row_pairs.len());
        assert(pos < through.len());
        lemma_nested_or_len_mono(outer_a, inner_a, outer_b, inner_b, i0 + 1, n_outer);
        assert(through.len() <= pairs.len());
        assert(pos < pairs.len());
        lemma_nested_or_index(outer_a, inner_a, outer_b, inner_b, i0 + 1, n_outer, pos);
        assert(through[pos] == (i0u, i1u));
        assert(pairs[pos] == (i0u, i1u));
        assert(pos + 1 == or_pair_pos(outer_a, inner_a, outer_b, inner_b, i0, i1 + 1));
        assert(or_loop_acc(outer_a, inner_a, outer_b, inner_b, step, base, n_outer, n_inner, i0, i1)
            == step(
            or_loop_acc(outer_a, inner_a, outer_b, inner_b, step, base, n_outer, n_inner, i0, i1 + 1),
            i0,
            i1,
        ));
        assert(pair_acc(pairs, step, base, pos) == step(
            pair_acc(pairs, step, base, pos + 1),
            i0,
            i1,
        ));
    } else {
        lemma_or_acc(outer_a, inner_a, outer_b, inner_b, step, base, n_outer, n_inner, i0, i1 + 1);
        let ids = or_match_ids(inner_a, outer_a[i0], inner_b, outer_b[i0], n_inner);
        lemma_or_members(inner_a, outer_a[i0], inner_b, outer_b[i0], n_inner);
        assert forall|p: int| 0 <= p < ids.len() implies (#[trigger] ids[p] as int) != i1 by {
            assert(inner_a[(ids[p] as int)] == outer_a[i0] || inner_b[(ids[p] as int)]
                == outer_b[i0]);
        };
        lemma_ids_lt_skip(ids, ids.len() as int, i1);
        assert(pos == or_pair_pos(outer_a, inner_a, outer_b, inner_b, i0, i1 + 1));
    }
}

pub proof fn lemma_or_pair_pos_origin<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
)
    requires
        outer_a.len() == outer_b.len(),
        inner_a.len() == inner_b.len(),
    ensures
        or_pair_pos(outer_a, inner_a, outer_b, inner_b, 0, 0) == 0,
{
    if outer_a.len() == 0 {
        assert(or_pair_pos(outer_a, inner_a, outer_b, inner_b, 0, 0) == 0);
    } else {
        let ids = or_match_ids(inner_a, outer_a[0], inner_b, outer_b[0], inner_a.len() as int);
        lemma_ids_lt_zero(ids, ids.len() as int);
        assert(or_pair_pos(outer_a, inner_a, outer_b, inner_b, 0, 0) == 0);
    }
}

/// At the origin indices, ``or_loop_acc`` equals ``pair_acc`` of the OR match list at 0.
pub proof fn lemma_or_at_origin<A, B, C>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    step: spec_fn(C, int, int) -> C,
    base: C,
    n_outer: int,
    n_inner: int,
)
    requires
        outer_a.len() == n_outer,
        outer_b.len() == n_outer,
        inner_a.len() == n_inner,
        inner_b.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
    ensures
        or_loop_acc(outer_a, inner_a, outer_b, inner_b, step, base, n_outer, n_inner, 0, 0)
            == pair_acc(
            nested_or_eq_pairs(outer_a, inner_a, outer_b, inner_b, n_outer),
            step,
            base,
            0,
        ),
{
    lemma_or_acc(outer_a, inner_a, outer_b, inner_b, step, base, n_outer, n_inner, 0, 0);
    lemma_or_pair_pos_origin(outer_a, inner_a, outer_b, inner_b);
}

/// Proved nested-loop OR-equality match list (same order as MethodSpec `full_cond`).
pub fn orjoin_pairs_str(
    outer_a: &Vec<String>,
    outer_b: &Vec<String>,
    inner_a: &Vec<String>,
    inner_b: &Vec<String>,
) -> (pairs: Vec<(usize, usize)>)
    requires
        outer_a@.len() == outer_b@.len(),
        inner_a@.len() == inner_b@.len(),
        outer_a@.len() <= usize::MAX as int,
        inner_a@.len() <= usize::MAX as int,
    ensures
        pairs@ == nested_or_eq_pairs(
            key_views(outer_a@),
            key_views(inner_a@),
            key_views(outer_b@),
            key_views(inner_b@),
            outer_a@.len() as int,
        ),
{
    let ghost oa = key_views(outer_a@);
    let ghost ia = key_views(inner_a@);
    let ghost ob = key_views(outer_b@);
    let ghost ib = key_views(inner_b@);
    let mut pairs: Vec<(usize, usize)> = Vec::new();
    let mut i: usize = 0;
    while i < outer_a.len()
        invariant
            i <= outer_a.len(),
            outer_a@.len() == outer_b@.len(),
            inner_a@.len() == inner_b@.len(),
            outer_a@.len() == outer_a.len() as int,
            outer_b@.len() == outer_b.len() as int,
            inner_a@.len() == inner_a.len() as int,
            inner_b@.len() == inner_b.len() as int,
            oa == key_views(outer_a@),
            ia == key_views(inner_a@),
            ob == key_views(outer_b@),
            ib == key_views(inner_b@),
            pairs@ == nested_or_eq_pairs(oa, ia, ob, ib, i as int),
        decreases outer_a.len() - i,
    {
        let ghost before = pairs@;
        let ghost end = i as int;
        proof {
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(end < outer_a@.len());
            assert(end < outer_b@.len());
            lemma_key_view_at(outer_a@, end);
            lemma_key_view_at(outer_b@, end);
        }
        let mut j: usize = 0;
        while j < inner_a.len()
            invariant
                i < outer_a.len(),
                j <= inner_a.len(),
                outer_a@.len() == outer_b@.len(),
                inner_a@.len() == inner_b@.len(),
                outer_a@.len() == outer_a.len() as int,
                outer_b@.len() == outer_b.len() as int,
                inner_a@.len() == inner_a.len() as int,
                inner_b@.len() == inner_b.len() as int,
                oa == key_views(outer_a@),
                ia == key_views(inner_a@),
                ob == key_views(outer_b@),
                ib == key_views(inner_b@),
                end == i as int,
                0 <= end < oa.len(),
                end < ob.len(),
                before == nested_or_eq_pairs(oa, ia, ob, ib, end),
                pairs@ == before + or_scan_prefix(oa, ia, ob, ib, i, j as int),
            decreases inner_a.len() - j,
        {
            let ghost pj = j as int;
            let ka = outer_a[i].clone();
            let kb = outer_b[i].clone();
            let ia_j = inner_a[j].clone();
            let ib_j = inner_b[j].clone();
            proof {
                broadcast use vstd::std_specs::vec::axiom_spec_len;
                assert(pj < inner_a@.len());
                assert(pj < inner_b@.len());
                lemma_key_view_at(inner_a@, pj);
                lemma_key_view_at(inner_b@, pj);
                assert(oa[end] == ka@);
                assert(ob[end] == kb@);
                assert(ia[pj] == ia_j@);
                assert(ib[pj] == ib_j@);
            }
            if ka == ia_j || kb == ib_j {
                pairs.push((i, j));
                proof {
                    assert(oa[end] == ia[pj] || ob[end] == ib[pj]);
                    lemma_or_scan_prefix_hit(oa, ia, ob, ib, i, pj);
                }
            } else {
                proof {
                    assert(!(oa[end] == ia[pj] || ob[end] == ib[pj]));
                    lemma_or_scan_prefix_miss(oa, ia, ob, ib, i, pj);
                }
            }
            j = j + 1;
        }
        proof {
            lemma_or_scan_prefix_is_ids(oa, ia, ob, ib, i, inner_a@.len() as int);
            lemma_nested_or_eq_pairs_step(oa, ia, ob, ib, end + 1);
            let ids = or_match_ids(ia, oa[end], ib, ob[end], ia.len() as int);
            assert(or_scan_prefix(oa, ia, ob, ib, i, ia.len() as int) == prefix_pairs(
                i,
                ids,
                ids.len() as int,
            ));
            assert(pairs@ == before + prefix_pairs(i, ids, ids.len() as int));
            assert(pairs@ == nested_or_eq_pairs(oa, ia, ob, ib, end + 1));
        }
        i = i + 1;
    }
    pairs
}

/// Inner scan `0..j` of OR matches for fixed outer row `i`.
pub open spec fn or_scan_prefix<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    i: usize,
    j: int,
) -> Seq<(usize, usize)>
    decreases j,
{
    if j <= 0 {
        Seq::<(usize, usize)>::empty()
    } else {
        let prev = or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j - 1);
        if 0 <= (i as int) < outer_a.len() && 0 <= (i as int) < outer_b.len() && 0 <= j - 1
            < inner_a.len() && 0 <= j - 1 < inner_b.len() && (outer_a[i as int] == inner_a[j - 1]
            || outer_b[i as int] == inner_b[j - 1]) {
            prev.push((i, (j - 1) as usize))
        } else {
            prev
        }
    }
}

pub proof fn lemma_or_scan_prefix_hit<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    i: usize,
    j: int,
)
    requires
        0 <= (i as int) < outer_a.len(),
        (i as int) < outer_b.len(),
        0 <= j < inner_a.len(),
        j < inner_b.len(),
        j <= usize::MAX as int,
        outer_a[i as int] == inner_a[j] || outer_b[i as int] == inner_b[j],
    ensures
        or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j + 1) == or_scan_prefix(
            outer_a,
            inner_a,
            outer_b,
            inner_b,
            i,
            j,
        ).push((i, j as usize)),
{
    let prev = or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j);
    let next = or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j + 1);
    let ju = j as usize;
    assert(ju as int == j);
    assert(next == prev.push((i, ju)));
}

pub proof fn lemma_or_scan_prefix_miss<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    i: usize,
    j: int,
)
    requires
        0 <= (i as int) < outer_a.len(),
        (i as int) < outer_b.len(),
        0 <= j < inner_a.len(),
        j < inner_b.len(),
        !(outer_a[i as int] == inner_a[j] || outer_b[i as int] == inner_b[j]),
    ensures
        or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j + 1) == or_scan_prefix(
            outer_a,
            inner_a,
            outer_b,
            inner_b,
            i,
            j,
        ),
{
    assert(or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j + 1) == or_scan_prefix(
        outer_a,
        inner_a,
        outer_b,
        inner_b,
        i,
        j,
    ));
}

pub proof fn lemma_or_scan_prefix_is_ids<A, B>(
    outer_a: Seq<A>,
    inner_a: Seq<A>,
    outer_b: Seq<B>,
    inner_b: Seq<B>,
    i: usize,
    j: int,
)
    requires
        0 <= (i as int) < outer_a.len(),
        (i as int) < outer_b.len(),
        0 <= j <= inner_a.len(),
        j <= inner_b.len(),
        inner_a.len() == inner_b.len(),
        j <= usize::MAX as int,
    ensures
        or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j) == prefix_pairs(
            i,
            or_match_ids(inner_a, outer_a[i as int], inner_b, outer_b[i as int], j),
            or_match_ids(inner_a, outer_a[i as int], inner_b, outer_b[i as int], j).len() as int,
        ),
    decreases j,
{
    let ka = outer_a[i as int];
    let kb = outer_b[i as int];
    let ids = or_match_ids(inner_a, ka, inner_b, kb, j);
    if j > 0 {
        lemma_or_scan_prefix_is_ids(outer_a, inner_a, outer_b, inner_b, i, j - 1);
        let prev_ids = or_match_ids(inner_a, ka, inner_b, kb, j - 1);
        let prev_scan = or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j - 1);
        assert(prev_scan == prefix_pairs(i, prev_ids, prev_ids.len() as int));
        lemma_or_match_ids_step(inner_a, ka, inner_b, kb, j - 1, (j - 1) as usize);
        if inner_a[j - 1] == ka || inner_b[j - 1] == kb {
            let row = (j - 1) as usize;
            assert(row as int == j - 1);
            assert(ids == prev_ids.push(row));
            lemma_prefix_pairs_step(i, ids, prev_ids.len() as int);
            assert(prefix_pairs(i, ids, ids.len() as int) == prefix_pairs(
                i,
                ids,
                prev_ids.len() as int,
            ).push((i, row)));
            assert(prefix_pairs(i, ids, prev_ids.len() as int) == prefix_pairs(
                i,
                prev_ids,
                prev_ids.len() as int,
            )) by {
                lemma_prefix_pairs_push_suffix(i, prev_ids, row, prev_ids.len() as int);
            };
            assert(or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j) == prev_scan.push(
                (i, row),
            ));
        } else {
            assert(ids == prev_ids);
            assert(or_scan_prefix(outer_a, inner_a, outer_b, inner_b, i, j) == prev_scan);
        }
    }
}

pub proof fn lemma_prefix_pairs_push_suffix(i: usize, ids: Seq<usize>, x: usize, t: int)
    requires
        0 <= t <= ids.len(),
    ensures
        prefix_pairs(i, ids.push(x), t) == prefix_pairs(i, ids, t),
    decreases t,
{
    if t > 0 {
        lemma_prefix_pairs_push_suffix(i, ids, x, t - 1);
        assert(ids.push(x)[t - 1] == ids[t - 1]);
    }
}

// SHAPE_OR_END

// SHAPE_LOJ_BEGIN
// Plain LEFT OUTER JOIN: matched (i, Some(j)) pairs plus unmatched left (i, None).
// Same outer-major order as nested_eq_pairs; miss rows use the anti existence check.

/// Matched pairs for outer row `i` as `(i, Some(j))`, increasing `j`.
pub open spec fn prefix_loj_pairs(i: usize, js: Seq<usize>, t: int) -> Seq<(usize, Option<usize>)>
    decreases t,
{
    if t <= 0 {
        Seq::<(usize, Option<usize>)>::empty()
    } else {
        let prev = prefix_loj_pairs(i, js, t - 1);
        if 0 <= t - 1 < js.len() {
            prev.push((i, Some(js[t - 1])))
        } else {
            prev
        }
    }
}

/// LEFT OUTER join list for `outer[0..n]`: matches, or a single `(i, None)` on miss.
pub open spec fn nested_loj_pairs<K>(outer: Seq<K>, inner: Seq<K>, n: int) -> Seq<(usize, Option<usize>)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, Option<usize>)>::empty()
    } else if n - 1 >= outer.len() {
        nested_loj_pairs(outer, inner, n - 1)
    } else {
        let i = (n - 1) as usize;
        let ids = eq_row_ids(inner, outer[n - 1], inner.len() as int);
        let prev = nested_loj_pairs(outer, inner, n - 1);
        if ids.len() == 0 {
            prev.push((i, None))
        } else {
            prev + prefix_loj_pairs(i, ids, ids.len() as int)
        }
    }
}

pub proof fn lemma_prefix_loj_pairs_step(i: usize, js: Seq<usize>, t: int)
    requires
        0 <= t < js.len(),
    ensures
        prefix_loj_pairs(i, js, t + 1) == prefix_loj_pairs(i, js, t).push((i, Some(js[t]))),
{
    assert(prefix_loj_pairs(i, js, t + 1) == prefix_loj_pairs(i, js, t).push((i, Some(js[t]))));
}

pub proof fn lemma_prefix_loj_len(i: usize, ids: Seq<usize>, t: int)
    requires
        0 <= t <= ids.len(),
    ensures
        prefix_loj_pairs(i, ids, t).len() == t,
    decreases t,
{
    if t > 0 {
        lemma_prefix_loj_len(i, ids, t - 1);
        assert(prefix_loj_pairs(i, ids, t) == prefix_loj_pairs(i, ids, t - 1).push((i, Some(ids[t - 1]))));
    }
}

pub proof fn lemma_nested_loj_pairs_step<K>(outer: Seq<K>, inner: Seq<K>, n: int)
    requires
        0 < n <= outer.len(),
    ensures
        ({
            let ids = eq_row_ids(inner, outer[n - 1], inner.len() as int);
            let prev = nested_loj_pairs(outer, inner, n - 1);
            let i = (n - 1) as usize;
            &&& ids.len() == 0 ==> nested_loj_pairs(outer, inner, n) == prev.push((i, None))
            &&& ids.len() > 0 ==> nested_loj_pairs(outer, inner, n) == prev + prefix_loj_pairs(
                i,
                ids,
                ids.len() as int,
            )
        }),
{
    let ids = eq_row_ids(inner, outer[n - 1], inner.len() as int);
    let prev = nested_loj_pairs(outer, inner, n - 1);
    let i = (n - 1) as usize;
    if ids.len() == 0 {
        assert(nested_loj_pairs(outer, inner, n) == prev.push((i, None)));
    } else {
        assert(nested_loj_pairs(outer, inner, n) == prev + prefix_loj_pairs(i, ids, ids.len() as int));
    }
}

/// Nested-loop LEFT OUTER fold: on match `step(..., Some(i1))`; on finished miss `None`.
pub open spec fn loj_loop_acc<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int, Option<int>) -> A,
    base: A,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
) -> A
    decreases n_outer - i0, n_inner - i1,
{
    if i0 < n_outer {
        if i1 < n_inner {
            let tail = loj_loop_acc(outer, inner, step, base, n_outer, n_inner, i0, i1 + 1);
            if 0 <= i0 < outer.len() && 0 <= i1 < inner.len() && outer[i0] == inner[i1] {
                step(tail, i0, Some(i1))
            } else {
                tail
            }
        } else {
            let tail = loj_loop_acc(outer, inner, step, base, n_outer, n_inner, i0 + 1, 0);
            if 0 <= i0 < outer.len() && eq_row_ids(inner, outer[i0], n_inner).len() == 0 {
                step(tail, i0, None)
            } else {
                tail
            }
        }
    } else {
        base
    }
}

/// Fold a LOJ pair list from the high index downward (same direction as MethodSpec).
pub open spec fn loj_acc<A>(
    pairs: Seq<(usize, Option<usize>)>,
    step: spec_fn(A, int, Option<int>) -> A,
    base: A,
    k: int,
) -> A
    decreases pairs.len() - k,
{
    if k >= pairs.len() {
        base
    } else {
        let tail = loj_acc(pairs, step, base, k + 1);
        let oi1 = pairs[k].1;
        match oi1 {
            Some(j) => step(tail, pairs[k].0 as int, Some(j as int)),
            None => step(tail, pairs[k].0 as int, None),
        }
    }
}

/// Index into `nested_loj_pairs` for the nested-loop cursor `(i0, i1)`.
/// On a miss row, the cursor stays at that slot until the outer index advances.
pub open spec fn loj_pos<K>(outer: Seq<K>, inner: Seq<K>, i0: int, i1: int) -> int {
    if !(0 <= i0 < outer.len()) {
        nested_loj_pairs(outer, inner, i0).len() as int
    } else {
        let ids = eq_row_ids(inner, outer[i0], inner.len() as int);
        let base = nested_loj_pairs(outer, inner, i0).len() as int;
        if ids.len() == 0 {
            base
        } else {
            base + ids_lt(ids, ids.len() as int, i1)
        }
    }
}

pub proof fn lemma_loj_prefix_at(i: usize, ids: Seq<usize>, t: int, r: int)
    requires
        0 <= r < t <= ids.len(),
    ensures
        prefix_loj_pairs(i, ids, t)[r] == (i, Some(ids[r])),
    decreases t,
{
    lemma_prefix_loj_len(i, ids, t);
    let prev = prefix_loj_pairs(i, ids, t - 1);
    let cur = prefix_loj_pairs(i, ids, t);
    assert(cur == prev.push((i, Some(ids[t - 1]))));
    lemma_prefix_loj_len(i, ids, t - 1);
    if r < t - 1 {
        lemma_loj_prefix_at(i, ids, t - 1, r);
        assert(0 <= r < prev.len());
        lemma_seq_push_index_different(prev, (i, Some(ids[t - 1])), r);
    } else {
        assert(r == t - 1);
        assert(r == prev.len() as int);
        lemma_seq_push_index_same(prev, (i, Some(ids[t - 1])), prev.len() as int);
    }
}

pub proof fn lemma_loj_nested_len_mono<K>(outer: Seq<K>, inner: Seq<K>, n: int, m: int)
    requires
        0 <= n <= m <= outer.len(),
    ensures
        nested_loj_pairs(outer, inner, n).len() <= nested_loj_pairs(outer, inner, m).len(),
    decreases m - n,
{
    if n < m {
        lemma_loj_nested_len_mono(outer, inner, n, m - 1);
        lemma_nested_loj_pairs_step(outer, inner, m);
        let ids = eq_row_ids(inner, outer[m - 1], inner.len() as int);
        let prev = nested_loj_pairs(outer, inner, m - 1);
        let cur = nested_loj_pairs(outer, inner, m);
        if ids.len() == 0 {
            assert(cur == prev.push(((m - 1) as usize, None)));
            assert(prev.len() <= cur.len());
        } else {
            lemma_prefix_loj_len((m - 1) as usize, ids, ids.len() as int);
            assert(cur == prev + prefix_loj_pairs((m - 1) as usize, ids, ids.len() as int));
            assert(prev.len() <= cur.len());
        }
    }
}

pub proof fn lemma_loj_nested_index<K>(outer: Seq<K>, inner: Seq<K>, n: int, m: int, p: int)
    requires
        0 <= n <= m <= outer.len(),
        m <= usize::MAX as int,
        0 <= p < nested_loj_pairs(outer, inner, n).len(),
    ensures
        nested_loj_pairs(outer, inner, m)[p] == nested_loj_pairs(outer, inner, n)[p],
    decreases m - n,
{
    if n < m {
        lemma_loj_nested_len_mono(outer, inner, n, m - 1);
        lemma_loj_nested_index(outer, inner, n, m - 1, p);
        lemma_nested_loj_pairs_step(outer, inner, m);
        let prev = nested_loj_pairs(outer, inner, m - 1);
        let cur = nested_loj_pairs(outer, inner, m);
        let ids = eq_row_ids(inner, outer[m - 1], inner.len() as int);
        let row = (m - 1) as usize;
        assert(row as int == m - 1);
        assert(0 <= p < prev.len());
        if ids.len() == 0 {
            assert(cur == prev.push((row, None)));
            lemma_seq_push_index_different(prev, (row, None), p);
        } else {
            let extra = prefix_loj_pairs(row, ids, ids.len() as int);
            assert(cur == prev + extra);
            lemma_left_index(prev, extra, p);
        }
    }
}

pub proof fn lemma_loj_acc<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int, Option<int>) -> A,
    base: A,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
)
    requires
        outer.len() == n_outer,
        inner.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
        0 <= i0 <= n_outer,
        0 <= i1 <= n_inner,
    ensures
        loj_loop_acc(outer, inner, step, base, n_outer, n_inner, i0, i1) == loj_acc(
            nested_loj_pairs(outer, inner, n_outer),
            step,
            base,
            loj_pos(outer, inner, i0, i1),
        ),
    decreases n_outer - i0, n_inner - i1,
{
    let pairs = nested_loj_pairs(outer, inner, n_outer);
    let pos = loj_pos(outer, inner, i0, i1);
    if i0 >= n_outer {
        assert(nested_loj_pairs(outer, inner, i0) =~= pairs);
        assert(pos == pairs.len() as int);
    } else if i1 >= n_inner {
        let ids = eq_row_ids(inner, outer[i0], n_inner);
        if ids.len() == 0 {
            lemma_loj_acc(outer, inner, step, base, n_outer, n_inner, i0 + 1, 0);
            lemma_nested_loj_pairs_step(outer, inner, i0 + 1);
            let earlier = nested_loj_pairs(outer, inner, i0);
            let through = nested_loj_pairs(outer, inner, i0 + 1);
            let i0u = i0 as usize;
            assert(i0u as int == i0);
            assert(through == earlier.push((i0u, None)));
            assert(pos == earlier.len() as int);
            assert(through.len() == earlier.len() + 1);
            assert(0 <= pos < through.len());
            lemma_loj_nested_len_mono(outer, inner, i0 + 1, n_outer);
            assert(through.len() <= pairs.len());
            assert(pos < pairs.len());
            lemma_loj_nested_index(outer, inner, i0 + 1, n_outer, pos);
            lemma_seq_push_index_same(earlier, (i0u, None), earlier.len() as int);
            assert(through[pos] == (i0u, None));
            assert(pairs[pos] == (i0u, None));
            if i0 + 1 < outer.len() {
                let next_ids = eq_row_ids(inner, outer[i0 + 1], n_inner);
                if next_ids.len() == 0 {
                    assert(loj_pos(outer, inner, i0 + 1, 0)
                        == nested_loj_pairs(outer, inner, i0 + 1).len() as int);
                } else {
                    lemma_ids_lt_zero(next_ids, next_ids.len() as int);
                    assert(loj_pos(outer, inner, i0 + 1, 0)
                        == nested_loj_pairs(outer, inner, i0 + 1).len() as int);
                }
            } else {
                assert(loj_pos(outer, inner, i0 + 1, 0)
                    == nested_loj_pairs(outer, inner, i0 + 1).len() as int);
            }
            assert(loj_pos(outer, inner, i0 + 1, 0) == through.len() as int);
            assert(loj_pos(outer, inner, i0 + 1, 0) == pos + 1);
            assert(loj_loop_acc(outer, inner, step, base, n_outer, n_inner, i0, i1) == step(
                loj_loop_acc(outer, inner, step, base, n_outer, n_inner, i0 + 1, 0),
                i0,
                None,
            ));
            assert(loj_acc(pairs, step, base, pos) == step(
                loj_acc(pairs, step, base, pos + 1),
                i0,
                None,
            ));
        } else {
            lemma_loj_acc(outer, inner, step, base, n_outer, n_inner, i0 + 1, 0);
            lemma_eq_members(inner, outer[i0], n_inner);
            assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < n_inner by {
                assert(0 <= (ids[p] as int) < n_inner);
            };
            assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < i1 by {
                assert((ids[p] as int) < n_inner);
                assert(n_inner <= i1);
            };
            lemma_ids_lt_all(ids, ids.len() as int, i1);
            let i0u = i0 as usize;
            assert(i0u as int == i0);
            lemma_prefix_loj_len(i0u, ids, ids.len() as int);
            lemma_nested_loj_pairs_step(outer, inner, i0 + 1);
            assert(nested_loj_pairs(outer, inner, i0 + 1).len()
                == nested_loj_pairs(outer, inner, i0).len() + ids.len());
            if i0 + 1 < outer.len() {
                let next_ids = eq_row_ids(inner, outer[i0 + 1], n_inner);
                lemma_ids_lt_zero(next_ids, next_ids.len() as int);
            }
            assert(loj_pos(outer, inner, i0 + 1, 0) == pos);
        }
    } else if outer[i0] == inner[i1] {
        lemma_loj_acc(outer, inner, step, base, n_outer, n_inner, i0, i1 + 1);
        lemma_eq_rank(inner, outer[i0], n_inner, i1);
        let ids = eq_row_ids(inner, outer[i0], n_inner);
        assert(ids.len() > 0);
        let r = ids_lt(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_loj_len(i0u, ids, ids.len() as int);
        lemma_loj_prefix_at(i0u, ids, ids.len() as int, r);
        let row_pairs = prefix_loj_pairs(i0u, ids, ids.len() as int);
        let earlier = nested_loj_pairs(outer, inner, i0);
        let through = nested_loj_pairs(outer, inner, i0 + 1);
        lemma_nested_loj_pairs_step(outer, inner, i0 + 1);
        assert(through == earlier + row_pairs);
        assert(i1 as int <= usize::MAX as int);
        let i1u = i1 as usize;
        assert(i1u as int == i1);
        assert(row_pairs[r] == (i0u, Some(i1u)));
        assert(0 <= r < row_pairs.len());
        lemma_right_index(earlier, row_pairs, r);
        assert(pos == earlier.len() as int + r);
        assert(through.len() == earlier.len() + row_pairs.len());
        assert(pos < through.len());
        lemma_loj_nested_len_mono(outer, inner, i0 + 1, n_outer);
        assert(through.len() <= pairs.len());
        assert(pos < pairs.len());
        lemma_loj_nested_index(outer, inner, i0 + 1, n_outer, pos);
        assert(through[pos] == (i0u, Some(i1u)));
        assert(pairs[pos] == (i0u, Some(i1u)));
        assert(pos + 1 == loj_pos(outer, inner, i0, i1 + 1));
        assert(loj_loop_acc(outer, inner, step, base, n_outer, n_inner, i0, i1) == step(
            loj_loop_acc(outer, inner, step, base, n_outer, n_inner, i0, i1 + 1),
            i0,
            Some(i1),
        ));
        assert(loj_acc(pairs, step, base, pos) == step(
            loj_acc(pairs, step, base, pos + 1),
            i0,
            Some(i1),
        ));
    } else {
        lemma_loj_acc(outer, inner, step, base, n_outer, n_inner, i0, i1 + 1);
        let ids = eq_row_ids(inner, outer[i0], n_inner);
        if ids.len() == 0 {
            assert(loj_pos(outer, inner, i0, i1 + 1) == pos);
        } else {
            lemma_eq_members(inner, outer[i0], n_inner);
            assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) != i1 by {
                if (ids[p] as int) == i1 {
                    assert(inner[i1] == outer[i0]);
                    assert(false);
                }
            };
            lemma_ids_lt_skip(ids, ids.len() as int, i1);
            assert(loj_pos(outer, inner, i0, i1 + 1) == pos);
        }
    }
}

pub proof fn lemma_loj_pos_origin<K>(outer: Seq<K>, inner: Seq<K>)
    requires
        outer.len() <= usize::MAX as int,
        inner.len() <= usize::MAX as int,
    ensures
        loj_pos(outer, inner, 0, 0) == 0,
{
    assert(nested_loj_pairs(outer, inner, 0) =~= Seq::<(usize, Option<usize>)>::empty());
    if outer.len() > 0 {
        let ids = eq_row_ids(inner, outer[0], inner.len() as int);
        if ids.len() == 0 {
            assert(loj_pos(outer, inner, 0, 0) == 0);
        } else {
            lemma_ids_lt_zero(ids, ids.len() as int);
            assert(loj_pos(outer, inner, 0, 0) == 0);
        }
    }
}

/// At the origin indices, ``loj_loop_acc`` equals ``loj_acc`` of the full LOJ list at 0.
pub proof fn lemma_loj_at_origin<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step: spec_fn(A, int, Option<int>) -> A,
    base: A,
    n_outer: int,
    n_inner: int,
)
    requires
        outer.len() == n_outer,
        inner.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
    ensures
        loj_loop_acc(outer, inner, step, base, n_outer, n_inner, 0, 0) == loj_acc(
            nested_loj_pairs(outer, inner, n_outer),
            step,
            base,
            0,
        ),
{
    lemma_loj_acc(outer, inner, step, base, n_outer, n_inner, 0, 0);
    lemma_loj_pos_origin(outer, inner);
}

pub fn push_prefix_loj_pairs(pairs: &mut Vec<(usize, Option<usize>)>, i: usize, ids: &Vec<usize>)
    ensures
        final(pairs)@ == old(pairs)@ + prefix_loj_pairs(i, ids@, ids@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(ids@.len() == ids.len() as int);
    }
    let ghost base = pairs@;
    let mut extra: Vec<(usize, Option<usize>)> = Vec::new();
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            extra@ == prefix_loj_pairs(i, ids@, t as int),
        decreases ids.len() - t,
    {
        let ghost old_extra = extra@;
        let id = ids[t];
        extra.push((i, Some(id)));
        proof {
            assert(id == ids@[t as int]);
            lemma_prefix_loj_pairs_step(i, ids@, t as int);
            assert(extra@ == old_extra.push((i, Some(ids@[t as int]))));
            assert(extra@ == prefix_loj_pairs(i, ids@, t as int + 1));
        }
        t = t + 1;
    }
    proof {
        assert(extra@ == prefix_loj_pairs(i, ids@, ids@.len() as int));
        assert(pairs@ == base);
    }
    pairs.append(&mut extra);
    proof {
        assert(pairs@ == base + prefix_loj_pairs(i, ids@, ids@.len() as int));
    }
}

/// LEFT OUTER pair list for one `String` key column. View equals [`nested_loj_pairs`].
pub fn left_outer_pairs_str(outer: &Vec<String>, inner: &Vec<String>) -> (pairs: Vec<(usize, Option<usize>)>)
    ensures
        pairs@ == nested_loj_pairs(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    let idx = build_eq_index_str(inner);
    let ghost ov = key_views(outer@);
    let ghost iv = key_views(inner@);
    let mut pairs: Vec<(usize, Option<usize>)> = Vec::new();
    let mut i: usize = 0;
    while i < outer.len()
        invariant
            i <= outer.len(),
            outer@.len() == outer.len() as int,
            inner@.len() == inner.len() as int,
            ov == key_views(outer@),
            iv == key_views(inner@),
            index_ok(iv, idx.buckets@, idx.map@, inner@.len() as int),
            pairs@ == nested_loj_pairs(ov, iv, i as int),
        decreases outer.len() - i,
    {
        let key = outer[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(ov[end] == key@);
        }
        let ghost before = pairs@;
        let hit = probe_eq_str(&idx, inner, key.as_str());
        match hit {
            Some(v) => {
                if v.len() == 0 {
                    pairs.push((i, None));
                    proof {
                        assert(v@ == eq_row_ids(iv, key@, iv.len() as int));
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                        lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                        lemma_nested_loj_pairs_step(ov, iv, end + 1);
                        assert(pairs@ == before.push((i, None)));
                        assert(pairs@ == nested_loj_pairs(ov, iv, end + 1));
                    }
                } else {
                    push_prefix_loj_pairs(&mut pairs, i, v);
                    proof {
                        assert(v@ == eq_row_ids(iv, key@, iv.len() as int));
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() > 0);
                        lemma_nested_loj_pairs_step(ov, iv, end + 1);
                        assert(pairs@ == before + prefix_loj_pairs(i, v@, v@.len() as int));
                        assert(pairs@ == nested_loj_pairs(ov, iv, end + 1));
                    }
                }
            },
            None => {
                pairs.push((i, None));
                proof {
                    assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                    lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                    lemma_nested_loj_pairs_step(ov, iv, end + 1);
                    assert(pairs@ == before.push((i, None)));
                    assert(pairs@ == nested_loj_pairs(ov, iv, end + 1));
                }
            },
        }
        i = i + 1;
    }
    pairs
}

/// LEFT OUTER pair list for one `u64` key column. View equals [`nested_loj_pairs`].
pub fn left_outer_pairs_u64(outer: &Vec<u64>, inner: &Vec<u64>) -> (pairs: Vec<(usize, Option<usize>)>)
    ensures
        pairs@ == nested_loj_pairs(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    proof {
        lemma_u64_hash_key();
    }
    left_outer_pairs_copy(outer, inner)
}

pub fn left_outer_pairs_copy<K: Copy + View<V = K> + Eq + Hash>(
    outer: &Vec<K>,
    inner: &Vec<K>,
) -> (pairs: Vec<(usize, Option<usize>)>)
    requires
        obeys_key_model::<K>(),
        builds_valid_hashers::<RandomState>(),
        forall|x: K| #[trigger] view_is_id(x),
    ensures
        pairs@ == nested_loj_pairs(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    let idx = build_eq_index_copy(inner);
    let ghost ov = key_views(outer@);
    let ghost iv = key_views(inner@);
    let mut pairs: Vec<(usize, Option<usize>)> = Vec::new();
    let mut i: usize = 0;
    while i < outer.len()
        invariant
            i <= outer.len(),
            outer@.len() == outer.len() as int,
            inner@.len() == inner.len() as int,
            ov == key_views(outer@),
            iv == key_views(inner@),
            obeys_key_model::<K>(),
            builds_valid_hashers::<RandomState>(),
            forall|x: K| #[trigger] view_is_id(x),
            index_ok(iv, idx.buckets@, idx.map@, inner@.len() as int),
            pairs@ == nested_loj_pairs(ov, iv, i as int),
        decreases outer.len() - i,
    {
        let key = outer[i];
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(ov[end] == key@);
        }
        let ghost before = pairs@;
        proof {
            assert(view_is_id(key));
            assert(key@ == key);
            broadcast use axiom_contains_deref_key;
            broadcast use axiom_maps_deref_key_to_value;
        }
        let bi_opt: Option<usize> = match idx.map.get(&key) {
            Some(bi_ref) => Some(*bi_ref),
            None => None,
        };
        match bi_opt {
            Some(bi) => {
                proof {
                    assert(idx.map@.contains_key(key@));
                    assert(idx.buckets@[bi as int]@ == eq_row_ids(iv, key@, iv.len() as int));
                }
                let ids = &idx.buckets[bi];
                if ids.len() == 0 {
                    pairs.push((i, None));
                    proof {
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                        lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                        lemma_nested_loj_pairs_step(ov, iv, end + 1);
                        assert(pairs@ == before.push((i, None)));
                        assert(pairs@ == nested_loj_pairs(ov, iv, end + 1));
                    }
                } else {
                    push_prefix_loj_pairs(&mut pairs, i, ids);
                    proof {
                        assert(ids@ == eq_row_ids(iv, ov[end], iv.len() as int));
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() > 0);
                        lemma_nested_loj_pairs_step(ov, iv, end + 1);
                        assert(pairs@ == before + prefix_loj_pairs(i, ids@, ids@.len() as int));
                        assert(pairs@ == nested_loj_pairs(ov, iv, end + 1));
                    }
                }
            },
            None => {
                pairs.push((i, None));
                proof {
                    assert(!idx.map@.contains_key(key@));
                    assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                    lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                    lemma_nested_loj_pairs_step(ov, iv, end + 1);
                    assert(pairs@ == before.push((i, None)));
                    assert(pairs@ == nested_loj_pairs(ov, iv, end + 1));
                }
            },
        }
        i = i + 1;
    }
    pairs
}

// SHAPE_LOJ_END

// SHAPE_CHAIN_BEGIN
// 3-table chain: A.k = B.k AND B.m = C.m (different mid keys). Not a star.
// Exec list order equals nested rem_join. Spec && is not short-circuit: nested if.

/// `(i, j, ks[0..t])` triples.
pub open spec fn prefix_triples(i: usize, j: usize, ks: Seq<usize>, t: int) -> Seq<(usize, usize, usize)>
    decreases t,
{
    if t <= 0 {
        Seq::<(usize, usize, usize)>::empty()
    } else {
        let prev = prefix_triples(i, j, ks, t - 1);
        if 0 <= t - 1 < ks.len() {
            prev.push((i, j, ks[t - 1]))
        } else {
            prev
        }
    }
}

/// Middles `0..j_end` matching `key` on `b_k`, each expanded by inners on `b_m[j]`.
pub open spec fn chain_mid_product<K, M>(
    i: usize,
    key: K,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    j_end: int,
) -> Seq<(usize, usize, usize)>
    decreases j_end,
{
    if j_end <= 0 {
        Seq::<(usize, usize, usize)>::empty()
    } else {
        let prev = chain_mid_product(i, key, b_k, b_m, c_m, j_end - 1);
        let j = j_end - 1;
        if 0 <= j < b_k.len() {
            if j < b_m.len() {
                if b_k[j] == key {
                    let ids = eq_row_ids(c_m, b_m[j], c_m.len() as int);
                    prev + prefix_triples(i, j as usize, ids, ids.len() as int)
                } else {
                    prev
                }
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

/// Expand a mid-id bucket (already `eq_row_ids` of `b_k`) into chain triples.
pub open spec fn chain_expand_mids<M>(
    i: usize,
    mids: Seq<usize>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    s_end: int,
) -> Seq<(usize, usize, usize)>
    decreases s_end,
{
    if s_end <= 0 {
        Seq::<(usize, usize, usize)>::empty()
    } else {
        let prev = chain_expand_mids(i, mids, b_m, c_m, s_end - 1);
        if 0 <= s_end - 1 < mids.len() {
            let j = mids[s_end - 1];
            if (j as int) < b_m.len() {
                let ids = eq_row_ids(c_m, b_m[j as int], c_m.len() as int);
                prev + prefix_triples(i, j, ids, ids.len() as int)
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

/// Chain matches for outer rows `0..n`, outer-major (same order as rem_join).
pub open spec fn nested_chain<K, M>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    n: int,
) -> Seq<(usize, usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize, usize)>::empty()
    } else if n - 1 >= a_k.len() {
        nested_chain(a_k, b_k, b_m, c_m, n - 1)
    } else {
        let i = (n - 1) as usize;
        nested_chain(a_k, b_k, b_m, c_m, n - 1) + chain_mid_product(
            i,
            a_k[n - 1],
            b_k,
            b_m,
            c_m,
            b_k.len() as int,
        )
    }
}

/// How many chain triples come from matching middles in `0..j_end`.
pub open spec fn chain_mid_prefix_len<K, M>(
    key: K,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    j_end: int,
) -> int
    decreases j_end,
{
    if j_end <= 0 {
        0
    } else {
        let prev = chain_mid_prefix_len(key, b_k, b_m, c_m, j_end - 1);
        let j = j_end - 1;
        if 0 <= j < b_k.len() {
            if j < b_m.len() {
                if b_k[j] == key {
                    prev + eq_row_ids(c_m, b_m[j], c_m.len() as int).len() as int
                } else {
                    prev
                }
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

pub open spec fn chain_pos<K, M>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    i0: int,
    i1: int,
    i2: int,
) -> int {
    if !(0 <= i0 < a_k.len()) {
        nested_chain(a_k, b_k, b_m, c_m, i0).len() as int
    } else {
        let base = nested_chain(a_k, b_k, b_m, c_m, i0).len() as int;
        let before = chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1);
        let inner_part = if 0 <= i1 < b_k.len() {
            if i1 < b_m.len() {
                if b_k[i1] == a_k[i0] {
                    let ids = eq_row_ids(c_m, b_m[i1], c_m.len() as int);
                    ids_lt(ids, ids.len() as int, i2)
                } else {
                    0
                }
            } else {
                0
            }
        } else {
            0
        };
        base + before + inner_part
    }
}

/// Nested rem_join fold for a chain. Nested `if` (Spec `&&` is not short-circuit).
pub open spec fn loop_acc_chain<K, M, A>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    n0: int,
    n1: int,
    n2: int,
    i0: int,
    i1: int,
    i2: int,
) -> A
    decreases n0 - i0, n1 - i1, n2 - i2,
{
    if i0 < n0 {
        if i1 < n1 {
            if i2 < n2 {
                let tail = loop_acc_chain(
                    a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0, i1, i2 + 1,
                );
                if 0 <= i0 < a_k.len() {
                    if 0 <= i1 < b_k.len() {
                        if i1 < b_m.len() {
                            if 0 <= i2 < c_m.len() {
                                if a_k[i0] == b_k[i1] {
                                    if b_m[i1] == c_m[i2] {
                                        step(tail, i0, i1, i2)
                                    } else {
                                        tail
                                    }
                                } else {
                                    tail
                                }
                            } else {
                                tail
                            }
                        } else {
                            tail
                        }
                    } else {
                        tail
                    }
                } else {
                    tail
                }
            } else {
                loop_acc_chain(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0, i1 + 1, 0)
            }
        } else {
            loop_acc_chain(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0 + 1, 0, 0)
        }
    } else {
        base
    }
}

pub proof fn lemma_prefix_triples_step(i: usize, j: usize, ks: Seq<usize>, t: int)
    requires
        0 <= t < ks.len(),
    ensures
        prefix_triples(i, j, ks, t + 1) == prefix_triples(i, j, ks, t).push((i, j, ks[t])),
{
    assert(prefix_triples(i, j, ks, t + 1) == prefix_triples(i, j, ks, t).push((i, j, ks[t])));
}

pub proof fn lemma_prefix_triples_len(i: usize, j: usize, ks: Seq<usize>, t: int)
    requires
        0 <= t <= ks.len(),
    ensures
        prefix_triples(i, j, ks, t).len() == t,
    decreases t,
{
    if t > 0 {
        lemma_prefix_triples_len(i, j, ks, t - 1);
        assert(prefix_triples(i, j, ks, t) == prefix_triples(i, j, ks, t - 1).push((i, j, ks[t - 1])));
    }
}

pub proof fn lemma_prefix_triples_at(i: usize, j: usize, ks: Seq<usize>, t: int, p: int)
    requires
        0 <= p < t <= ks.len(),
    ensures
        prefix_triples(i, j, ks, t)[p] == (i, j, ks[p]),
    decreases t,
{
    lemma_prefix_triples_len(i, j, ks, t - 1);
    if p < t - 1 {
        lemma_prefix_triples_at(i, j, ks, t - 1, p);
        assert(prefix_triples(i, j, ks, t)
            == prefix_triples(i, j, ks, t - 1).push((i, j, ks[t - 1])));
        assert(prefix_triples(i, j, ks, t)[p] == prefix_triples(i, j, ks, t - 1)[p]);
    } else {
        assert(prefix_triples(i, j, ks, t)
            == prefix_triples(i, j, ks, t - 1).push((i, j, ks[t - 1])));
        assert(prefix_triples(i, j, ks, t)[p] == (i, j, ks[t - 1]));
    }
}

pub proof fn lemma_chain_mid_product_len<K, M>(
    i: usize,
    key: K,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    j_end: int,
)
    requires
        0 <= j_end <= b_k.len(),
        b_k.len() == b_m.len(),
    ensures
        chain_mid_product(i, key, b_k, b_m, c_m, j_end).len() as int
            == chain_mid_prefix_len(key, b_k, b_m, c_m, j_end),
    decreases j_end,
{
    if j_end > 0 {
        lemma_chain_mid_product_len(i, key, b_k, b_m, c_m, j_end - 1);
        let j = j_end - 1;
        if b_k[j] == key {
            let ids = eq_row_ids(c_m, b_m[j], c_m.len() as int);
            lemma_prefix_triples_len(i, j as usize, ids, ids.len() as int);
            let prev = chain_mid_product(i, key, b_k, b_m, c_m, j_end - 1);
            let extra = prefix_triples(i, j as usize, ids, ids.len() as int);
            assert(chain_mid_product(i, key, b_k, b_m, c_m, j_end) == prev + extra);
            assert((prev + extra).len() == prev.len() + extra.len());
        }
    }
}

pub proof fn lemma_chain_mid_product_step<K, M>(
    i: usize,
    key: K,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    j_end: int,
)
    requires
        0 < j_end <= b_k.len(),
        b_k.len() == b_m.len(),
    ensures
        ({
            let j = j_end - 1;
            let prev = chain_mid_product(i, key, b_k, b_m, c_m, j_end - 1);
            &&& b_k[j] == key ==> chain_mid_product(i, key, b_k, b_m, c_m, j_end)
                == prev + prefix_triples(
                    i,
                    j as usize,
                    eq_row_ids(c_m, b_m[j], c_m.len() as int),
                    eq_row_ids(c_m, b_m[j], c_m.len() as int).len() as int,
                )
            &&& b_k[j] != key ==> chain_mid_product(i, key, b_k, b_m, c_m, j_end) == prev
        }),
{
    let j = j_end - 1;
    if b_k[j] == key {
        assert(chain_mid_product(i, key, b_k, b_m, c_m, j_end)
            == chain_mid_product(i, key, b_k, b_m, c_m, j_end - 1) + prefix_triples(
                i,
                j as usize,
                eq_row_ids(c_m, b_m[j], c_m.len() as int),
                eq_row_ids(c_m, b_m[j], c_m.len() as int).len() as int,
            ));
    } else {
        assert(chain_mid_product(i, key, b_k, b_m, c_m, j_end)
            == chain_mid_product(i, key, b_k, b_m, c_m, j_end - 1));
    }
}

pub proof fn lemma_nested_chain_step<K, M>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    n: int,
)
    requires
        0 < n <= a_k.len(),
        b_k.len() == b_m.len(),
    ensures
        nested_chain(a_k, b_k, b_m, c_m, n) == nested_chain(a_k, b_k, b_m, c_m, n - 1)
            + chain_mid_product(
                (n - 1) as usize,
                a_k[n - 1],
                b_k,
                b_m,
                c_m,
                b_k.len() as int,
            ),
{
    assert(nested_chain(a_k, b_k, b_m, c_m, n) == nested_chain(a_k, b_k, b_m, c_m, n - 1)
        + chain_mid_product(
            (n - 1) as usize,
            a_k[n - 1],
            b_k,
            b_m,
            c_m,
            b_k.len() as int,
        ));
}

pub proof fn lemma_chain_mid_prefix_len_step<K, M>(
    key: K,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    j_end: int,
)
    requires
        0 < j_end <= b_k.len(),
        b_k.len() == b_m.len(),
    ensures
        ({
            let j = j_end - 1;
            let prev = chain_mid_prefix_len(key, b_k, b_m, c_m, j_end - 1);
            &&& b_k[j] == key ==> chain_mid_prefix_len(key, b_k, b_m, c_m, j_end)
                == prev + eq_row_ids(c_m, b_m[j], c_m.len() as int).len() as int
            &&& b_k[j] != key ==> chain_mid_prefix_len(key, b_k, b_m, c_m, j_end) == prev
        }),
{
    let j = j_end - 1;
    if b_k[j] == key {
        assert(chain_mid_prefix_len(key, b_k, b_m, c_m, j_end)
            == chain_mid_prefix_len(key, b_k, b_m, c_m, j_end - 1)
                + eq_row_ids(c_m, b_m[j], c_m.len() as int).len() as int);
    } else {
        assert(chain_mid_prefix_len(key, b_k, b_m, c_m, j_end)
            == chain_mid_prefix_len(key, b_k, b_m, c_m, j_end - 1));
    }
}

pub proof fn lemma_chain_mid_at<K, M>(
    i: usize,
    key: K,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    j_end: int,
    j: int,
    tr: int,
)
    requires
        b_k.len() == b_m.len(),
        0 <= j < j_end <= b_k.len(),
        j_end <= usize::MAX as int,
        b_k[j] == key,
        ({
            let ids = eq_row_ids(c_m, b_m[j], c_m.len() as int);
            0 <= tr < ids.len()
        }),
    ensures
        ({
            let ids = eq_row_ids(c_m, b_m[j], c_m.len() as int);
            let prod = chain_mid_product(i, key, b_k, b_m, c_m, j_end);
            let off = chain_mid_prefix_len(key, b_k, b_m, c_m, j);
            let ju = j as usize;
            &&& ju as int == j
            &&& 0 <= off + tr < prod.len()
            &&& prod[off + tr] == (i, ju, ids[tr])
        }),
    decreases j_end - j,
{
    let ids = eq_row_ids(c_m, b_m[j], c_m.len() as int);
    assert(0 <= j <= usize::MAX as int);
    let ju = j as usize;
    assert(ju as int == j);
    if j_end == j + 1 {
        lemma_chain_mid_product_step(i, key, b_k, b_m, c_m, j_end);
        let prev = chain_mid_product(i, key, b_k, b_m, c_m, j);
        let extra = prefix_triples(i, ju, ids, ids.len() as int);
        assert(chain_mid_product(i, key, b_k, b_m, c_m, j_end) == prev + extra);
        lemma_chain_mid_product_len(i, key, b_k, b_m, c_m, j);
        lemma_prefix_triples_len(i, ju, ids, ids.len() as int);
        lemma_prefix_triples_at(i, ju, ids, ids.len() as int, tr);
        let off = chain_mid_prefix_len(key, b_k, b_m, c_m, j);
        assert(prev.len() as int == off);
        assert(tr < extra.len());
        lemma_right_index(prev, extra, tr);
        assert((prev + extra)[off + tr] == extra[tr]);
        assert(extra[tr] == (i, ju, ids[tr]));
    } else {
        lemma_chain_mid_at(i, key, b_k, b_m, c_m, j_end - 1, j, tr);
        lemma_chain_mid_product_step(i, key, b_k, b_m, c_m, j_end);
        let prev = chain_mid_product(i, key, b_k, b_m, c_m, j_end - 1);
        let off = chain_mid_prefix_len(key, b_k, b_m, c_m, j);
        assert(0 <= off + tr < prev.len());
        if b_k[j_end - 1] == key {
            let ids2 = eq_row_ids(c_m, b_m[j_end - 1], c_m.len() as int);
            assert(0 <= j_end - 1 <= usize::MAX as int);
            let jnext = (j_end - 1) as usize;
            assert(jnext as int == j_end - 1);
            let extra = prefix_triples(i, jnext, ids2, ids2.len() as int);
            assert(chain_mid_product(i, key, b_k, b_m, c_m, j_end) == prev + extra);
            lemma_left_index(prev, extra, off + tr);
        } else {
            assert(chain_mid_product(i, key, b_k, b_m, c_m, j_end) == prev);
        }
    }
}

pub proof fn lemma_nested_chain_len_mono<K, M>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    n: int,
    m: int,
)
    requires
        0 <= n <= m,
        b_k.len() == b_m.len(),
    ensures
        nested_chain(a_k, b_k, b_m, c_m, n).len()
            <= nested_chain(a_k, b_k, b_m, c_m, m).len(),
    decreases m - n,
{
    if n < m {
        lemma_nested_chain_len_mono(a_k, b_k, b_m, c_m, n, m - 1);
        let cur = nested_chain(a_k, b_k, b_m, c_m, m);
        let prev = nested_chain(a_k, b_k, b_m, c_m, m - 1);
        if m - 1 < a_k.len() {
            lemma_nested_chain_step(a_k, b_k, b_m, c_m, m);
            assert(prev.len() <= cur.len());
        } else {
            assert(cur == prev);
        }
    }
}

pub proof fn lemma_nested_chain_index<K, M>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    n: int,
    m: int,
    p: int,
)
    requires
        0 <= n <= m,
        b_k.len() == b_m.len(),
        0 <= p < nested_chain(a_k, b_k, b_m, c_m, n).len(),
    ensures
        nested_chain(a_k, b_k, b_m, c_m, m)[p]
            == nested_chain(a_k, b_k, b_m, c_m, n)[p],
    decreases m - n,
{
    if n < m {
        let cur = nested_chain(a_k, b_k, b_m, c_m, m);
        let prev = nested_chain(a_k, b_k, b_m, c_m, m - 1);
        lemma_nested_chain_len_mono(a_k, b_k, b_m, c_m, n, m - 1);
        if m - 1 >= a_k.len() {
            assert(cur == prev);
        } else {
            lemma_nested_chain_step(a_k, b_k, b_m, c_m, m);
            assert(p < prev.len());
            let extra = chain_mid_product(
                (m - 1) as usize,
                a_k[m - 1],
                b_k,
                b_m,
                c_m,
                b_k.len() as int,
            );
            lemma_left_index(prev, extra, p);
        }
        lemma_nested_chain_index(a_k, b_k, b_m, c_m, n, m - 1, p);
    }
}

pub proof fn lemma_nested_chain_past<K, M>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    n: int,
)
    requires
        n >= a_k.len(),
        b_k.len() == b_m.len(),
    ensures
        nested_chain(a_k, b_k, b_m, c_m, n)
            == nested_chain(a_k, b_k, b_m, c_m, a_k.len() as int),
    decreases n - a_k.len(),
{
    if n > a_k.len() {
        assert(nested_chain(a_k, b_k, b_m, c_m, n)
            == nested_chain(a_k, b_k, b_m, c_m, n - 1));
        lemma_nested_chain_past(a_k, b_k, b_m, c_m, n - 1);
    }
}

pub proof fn lemma_chain_expand_push_prefix<M>(
    i: usize,
    mids: Seq<usize>,
    x: usize,
    b_m: Seq<M>,
    c_m: Seq<M>,
    t: int,
)
    requires
        0 <= t <= mids.len(),
    ensures
        chain_expand_mids(i, mids.push(x), b_m, c_m, t) == chain_expand_mids(i, mids, b_m, c_m, t),
    decreases t,
{
    if t > 0 {
        lemma_chain_expand_push_prefix(i, mids, x, b_m, c_m, t - 1);
        assert(mids.push(x)[t - 1] == mids[t - 1]);
    }
}

pub proof fn lemma_chain_mid_eq_expand<K, M>(
    i: usize,
    key: K,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    j_end: int,
)
    requires
        0 <= j_end <= b_k.len(),
        b_k.len() == b_m.len(),
        j_end <= usize::MAX as int,
    ensures
        chain_mid_product(i, key, b_k, b_m, c_m, j_end) == chain_expand_mids(
            i,
            eq_row_ids(b_k, key, j_end),
            b_m,
            c_m,
            eq_row_ids(b_k, key, j_end).len() as int,
        ),
    decreases j_end,
{
    if j_end > 0 {
        lemma_chain_mid_eq_expand(i, key, b_k, b_m, c_m, j_end - 1);
        let j = j_end - 1;
        let ju = j as usize;
        assert(ju as int == j);
        let prev_ids = eq_row_ids(b_k, key, j_end - 1);
        let cur_ids = eq_row_ids(b_k, key, j_end);
        let prev_prod = chain_mid_product(i, key, b_k, b_m, c_m, j_end - 1);
        assert(prev_prod == chain_expand_mids(i, prev_ids, b_m, c_m, prev_ids.len() as int));
        lemma_eq_row_ids_step(b_k, key, j_end - 1, ju);
        if b_k[j] == key {
            assert(cur_ids == prev_ids.push(ju));
            let ids = eq_row_ids(c_m, b_m[j], c_m.len() as int);
            let extra = prefix_triples(i, ju, ids, ids.len() as int);
            assert(chain_mid_product(i, key, b_k, b_m, c_m, j_end) == prev_prod + extra);
            lemma_chain_expand_push_prefix(i, prev_ids, ju, b_m, c_m, prev_ids.len() as int);
            assert(chain_expand_mids(i, cur_ids, b_m, c_m, prev_ids.len() as int)
                == chain_expand_mids(i, prev_ids, b_m, c_m, prev_ids.len() as int));
            assert((ju as int) < b_m.len());
            assert(chain_expand_mids(i, cur_ids, b_m, c_m, cur_ids.len() as int)
                == chain_expand_mids(i, cur_ids, b_m, c_m, prev_ids.len() as int) + extra);
            assert(chain_mid_product(i, key, b_k, b_m, c_m, j_end)
                == chain_expand_mids(i, cur_ids, b_m, c_m, cur_ids.len() as int));
        } else {
            assert(cur_ids == prev_ids);
            assert(chain_mid_product(i, key, b_k, b_m, c_m, j_end) == prev_prod);
        }
    }
}

pub proof fn lemma_chain_acc<K, M, A>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    n0: int,
    n1: int,
    n2: int,
    i0: int,
    i1: int,
    i2: int,
)
    requires
        a_k.len() == n0,
        b_k.len() == n1,
        b_m.len() == n1,
        c_m.len() == n2,
        n0 <= usize::MAX as int,
        n1 <= usize::MAX as int,
        n2 <= usize::MAX as int,
        0 <= i0 <= n0,
        0 <= i1 <= n1,
        0 <= i2 <= n2,
    ensures
        loop_acc_chain(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0, i1, i2)
            == triple_acc(
                nested_chain(a_k, b_k, b_m, c_m, n0),
                step,
                base,
                chain_pos(a_k, b_k, b_m, c_m, i0, i1, i2),
            ),
    decreases n0 - i0, n1 - i1, n2 - i2,
{
    let triples = nested_chain(a_k, b_k, b_m, c_m, n0);
    let pos = chain_pos(a_k, b_k, b_m, c_m, i0, i1, i2);
    if i0 >= n0 {
        lemma_nested_chain_past(a_k, b_k, b_m, c_m, i0);
        assert(nested_chain(a_k, b_k, b_m, c_m, i0) == triples);
        assert(pos == triples.len() as int);
    } else if i1 >= n1 {
        lemma_chain_acc(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0 + 1, 0, 0);
        lemma_nested_chain_step(a_k, b_k, b_m, c_m, i0 + 1);
        assert(0 <= i0 <= usize::MAX as int);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_chain_mid_product_len(i0u, a_k[i0], b_k, b_m, c_m, n1);
        let earlier = nested_chain(a_k, b_k, b_m, c_m, i0);
        let prod = chain_mid_product(i0u, a_k[i0], b_k, b_m, c_m, n1);
        let through = nested_chain(a_k, b_k, b_m, c_m, i0 + 1);
        assert(through == earlier + prod);
        assert(i1 == n1);
        assert(chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, n1) == prod.len() as int);
        assert(chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1) == prod.len() as int);
        // i1 == n1 == b_k.len(), so chain_pos has no inner_part at this mid.
        assert(!(0 <= i1 < b_k.len()));
        assert(pos == earlier.len() as int + prod.len() as int);
        assert(through.len() == earlier.len() + prod.len());
        if i0 + 1 < a_k.len() {
            assert(chain_mid_prefix_len(a_k[i0 + 1], b_k, b_m, c_m, 0) == 0);
            if 0 < b_k.len() {
                if 0 < b_m.len() {
                    if b_k[0] == a_k[i0 + 1] {
                        let ids0 = eq_row_ids(c_m, b_m[0], c_m.len() as int);
                        lemma_ids_lt_zero(ids0, ids0.len() as int);
                    }
                }
            }
            assert(chain_pos(a_k, b_k, b_m, c_m, i0 + 1, 0, 0)
                == nested_chain(a_k, b_k, b_m, c_m, i0 + 1).len() as int);
            assert(nested_chain(a_k, b_k, b_m, c_m, i0 + 1) == through);
            assert(chain_pos(a_k, b_k, b_m, c_m, i0 + 1, 0, 0) == through.len() as int);
        } else {
            assert(chain_pos(a_k, b_k, b_m, c_m, i0 + 1, 0, 0)
                == nested_chain(a_k, b_k, b_m, c_m, i0 + 1).len() as int);
            assert(nested_chain(a_k, b_k, b_m, c_m, i0 + 1) == through);
        }
        assert(chain_pos(a_k, b_k, b_m, c_m, i0 + 1, 0, 0) == pos);
    } else if i2 >= n2 {
        lemma_chain_acc(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0, i1 + 1, 0);
        assert(n2 == c_m.len() as int);
        let base_len = nested_chain(a_k, b_k, b_m, c_m, i0).len() as int;
        if b_k[i1] == a_k[i0] {
            let ids = eq_row_ids(c_m, b_m[i1], n2);
            let ids_full = eq_row_ids(c_m, b_m[i1], c_m.len() as int);
            assert(ids == ids_full);
            lemma_eq_members(c_m, b_m[i1], n2);
            assert forall|p: int| 0 <= p < ids.len() implies (#[trigger] ids[p] as int) < i2 by {
                assert((ids[p] as int) < n2);
                assert(n2 <= i2);
            };
            lemma_ids_lt_all(ids, ids.len() as int, i2);
            lemma_chain_mid_prefix_len_step(a_k[i0], b_k, b_m, c_m, i1 + 1);
            assert(chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1 + 1)
                == chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1) + ids.len() as int);
            assert(pos == base_len + chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1)
                + ids.len() as int);
            if i1 + 1 < b_k.len() {
                if i1 + 1 < b_m.len() {
                    if b_k[i1 + 1] == a_k[i0] {
                        let ids_next = eq_row_ids(c_m, b_m[i1 + 1], c_m.len() as int);
                        lemma_ids_lt_zero(ids_next, ids_next.len() as int);
                    }
                }
            }
            assert(chain_pos(a_k, b_k, b_m, c_m, i0, i1 + 1, 0)
                == base_len + chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1 + 1));
            assert(chain_pos(a_k, b_k, b_m, c_m, i0, i1 + 1, 0) == pos);
        } else {
            lemma_chain_mid_prefix_len_step(a_k[i0], b_k, b_m, c_m, i1 + 1);
            assert(chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1 + 1)
                == chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1));
            assert(pos == base_len + chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1));
            if i1 + 1 < b_k.len() {
                if i1 + 1 < b_m.len() {
                    if b_k[i1 + 1] == a_k[i0] {
                        let ids_next = eq_row_ids(c_m, b_m[i1 + 1], c_m.len() as int);
                        lemma_ids_lt_zero(ids_next, ids_next.len() as int);
                    }
                }
            }
            assert(chain_pos(a_k, b_k, b_m, c_m, i0, i1 + 1, 0)
                == base_len + chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1 + 1));
            assert(chain_pos(a_k, b_k, b_m, c_m, i0, i1 + 1, 0) == pos);
        }
    } else {
        // Split on the two chain equalities with nested if (mirrors loop_acc_chain).
        if a_k[i0] == b_k[i1] {
            if b_m[i1] == c_m[i2] {
                lemma_chain_acc(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0, i1, i2 + 1);
                lemma_eq_rank(c_m, b_m[i1], n2, i2);
                let ids = eq_row_ids(c_m, b_m[i1], n2);
                let tr = ids_lt(ids, ids.len() as int, i2);
                let i0u = i0 as usize;
                let i1u = i1 as usize;
                let i2u = i2 as usize;
                assert(i0u as int == i0);
                assert(i1u as int == i1);
                assert(i2u as int == i2);
                lemma_nested_chain_step(a_k, b_k, b_m, c_m, i0 + 1);
                let earlier = nested_chain(a_k, b_k, b_m, c_m, i0);
                let prod = chain_mid_product(i0u, a_k[i0], b_k, b_m, c_m, n1);
                let through = nested_chain(a_k, b_k, b_m, c_m, i0 + 1);
                assert(through == earlier + prod);
                let off = chain_mid_prefix_len(a_k[i0], b_k, b_m, c_m, i1);
                lemma_chain_mid_at(i0u, a_k[i0], b_k, b_m, c_m, n1, i1, tr);
                assert(prod[off + tr] == (i0u, i1u, ids[tr]));
                assert(ids[tr] as int == i2);
                assert(ids[tr] == i2u);
                lemma_right_index(earlier, prod, off + tr);
                assert(pos == earlier.len() as int + off + tr);
                assert(pos < through.len());
                lemma_nested_chain_len_mono(a_k, b_k, b_m, c_m, i0 + 1, n0);
                assert(through.len() <= triples.len());
                assert(pos < triples.len());
                lemma_nested_chain_index(a_k, b_k, b_m, c_m, i0 + 1, n0, pos);
                assert(triples[pos] == (i0u, i1u, i2u));
                assert(pos + 1 == chain_pos(a_k, b_k, b_m, c_m, i0, i1, i2 + 1));
                assert(loop_acc_chain(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0, i1, i2)
                    == step(
                        loop_acc_chain(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0, i1, i2 + 1),
                        i0,
                        i1,
                        i2,
                    ));
                assert(triple_acc(triples, step, base, pos) == step(
                    triple_acc(triples, step, base, pos + 1),
                    i0,
                    i1,
                    i2,
                ));
            } else {
                lemma_chain_acc(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0, i1, i2 + 1);
                let ids = eq_row_ids(c_m, b_m[i1], n2);
                lemma_eq_members(c_m, b_m[i1], n2);
                assert forall|p: int| 0 <= p < ids.len() implies (#[trigger] ids[p] as int) != i2 by {
                    assert(c_m[(ids[p] as int)] == b_m[i1]);
                };
                lemma_ids_lt_skip(ids, ids.len() as int, i2);
                assert(pos == chain_pos(a_k, b_k, b_m, c_m, i0, i1, i2 + 1));
            }
        } else {
            lemma_chain_acc(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, i0, i1, i2 + 1);
            assert(pos == chain_pos(a_k, b_k, b_m, c_m, i0, i1, i2 + 1));
        }
    }
}

pub proof fn lemma_chain_pos_origin<K, M>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
)
    requires
        b_k.len() == b_m.len(),
    ensures
        chain_pos(a_k, b_k, b_m, c_m, 0, 0, 0) == 0,
{
    assert(nested_chain(a_k, b_k, b_m, c_m, 0) =~= Seq::<(usize, usize, usize)>::empty());
    if a_k.len() == 0 {
        assert(chain_pos(a_k, b_k, b_m, c_m, 0, 0, 0) == 0);
    } else {
        assert(chain_mid_prefix_len(a_k[0], b_k, b_m, c_m, 0) == 0);
        if 0 < b_k.len() {
            if b_k[0] == a_k[0] {
                let ids = eq_row_ids(c_m, b_m[0], c_m.len() as int);
                lemma_ids_lt_zero(ids, ids.len() as int);
            }
        }
        assert(chain_pos(a_k, b_k, b_m, c_m, 0, 0, 0) == 0);
    }
}

/// At the origin indices, ``loop_acc_chain`` equals ``triple_acc`` of the chain list at 0.
pub proof fn lemma_chain_at_origin<K, M, A>(
    a_k: Seq<K>,
    b_k: Seq<K>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    n0: int,
    n1: int,
    n2: int,
)
    requires
        a_k.len() == n0,
        b_k.len() == n1,
        b_m.len() == n1,
        c_m.len() == n2,
        n0 <= usize::MAX as int,
        n1 <= usize::MAX as int,
        n2 <= usize::MAX as int,
    ensures
        loop_acc_chain(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, 0, 0, 0)
            == triple_acc(nested_chain(a_k, b_k, b_m, c_m, n0), step, base, 0),
{
    lemma_chain_acc(a_k, b_k, b_m, c_m, step, base, n0, n1, n2, 0, 0, 0);
    lemma_chain_pos_origin(a_k, b_k, b_m, c_m);
}

/// Append inner matches for one middle row onto a chain triple list.
pub fn push_chain_inners(
    out: &mut Vec<(usize, usize, usize)>,
    i: usize,
    j: usize,
    inners: &Vec<usize>,
)
    ensures
        final(out)@ == old(out)@ + prefix_triples(i, j, inners@, inners@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(inners@.len() == inners.len() as int);
    }
    let ghost base = out@;
    let mut t: usize = 0;
    while t < inners.len()
        invariant
            t <= inners.len(),
            inners@.len() == inners.len() as int,
            out@ == base + prefix_triples(i, j, inners@, t as int),
        decreases inners.len() - t,
    {
        let kid = inners[t];
        let ghost old_out = out@;
        out.push((i, j, kid));
        proof {
            assert(kid == inners@[t as int]);
            lemma_prefix_triples_step(i, j, inners@, t as int);
            assert(out@ == old_out.push((i, j, inners@[t as int])));
            lemma_seq_add_push(base, prefix_triples(i, j, inners@, t as int), (i, j, inners@[t as int]));
            assert(out@ == base + prefix_triples(i, j, inners@, t as int + 1));
        }
        t = t + 1;
    }
}

pub proof fn lemma_chain_expand_mids_step<M>(
    i: usize,
    mids: Seq<usize>,
    b_m: Seq<M>,
    c_m: Seq<M>,
    s: int,
)
    requires
        0 <= s < mids.len(),
        (mids[s] as int) < b_m.len(),
    ensures
        chain_expand_mids(i, mids, b_m, c_m, s + 1) == chain_expand_mids(i, mids, b_m, c_m, s)
            + prefix_triples(
                i,
                mids[s],
                eq_row_ids(c_m, b_m[mids[s] as int], c_m.len() as int),
                eq_row_ids(c_m, b_m[mids[s] as int], c_m.len() as int).len() as int,
            ),
{
    assert(chain_expand_mids(i, mids, b_m, c_m, s + 1) == chain_expand_mids(i, mids, b_m, c_m, s)
        + prefix_triples(
            i,
            mids[s],
            eq_row_ids(c_m, b_m[mids[s] as int], c_m.len() as int),
            eq_row_ids(c_m, b_m[mids[s] as int], c_m.len() as int).len() as int,
        ));
}

/// Chain equijoin: `a.k = b.k` and `b.m = c.m` (string keys). View equals [`nested_chain`].
pub fn chain_eq_triples_str(
    a_k: &Vec<String>,
    b_k: &Vec<String>,
    b_m: &Vec<String>,
    c_m: &Vec<String>,
) -> (triples: Vec<(usize, usize, usize)>)
    requires
        b_k@.len() == b_m@.len(),
    ensures
        triples@ == nested_chain(
            key_views(a_k@),
            key_views(b_k@),
            key_views(b_m@),
            key_views(c_m@),
            a_k@.len() as int,
        ),
{
    let idx_b = build_eq_index_str(b_k);
    let idx_c = build_eq_index_str(c_m);
    let ghost ak = key_views(a_k@);
    let ghost bk = key_views(b_k@);
    let ghost bm = key_views(b_m@);
    let ghost cm = key_views(c_m@);
    let mut triples: Vec<(usize, usize, usize)> = Vec::new();
    let mut i: usize = 0;
    while i < a_k.len()
        invariant
            i <= a_k.len(),
            a_k@.len() == a_k.len() as int,
            b_k@.len() == b_k.len() as int,
            b_m@.len() == b_m.len() as int,
            c_m@.len() == c_m.len() as int,
            b_k@.len() == b_m@.len(),
            ak == key_views(a_k@),
            bk == key_views(b_k@),
            bm == key_views(b_m@),
            cm == key_views(c_m@),
            index_ok(bk, idx_b.buckets@, idx_b.map@, b_k@.len() as int),
            index_ok(cm, idx_c.buckets@, idx_c.map@, c_m@.len() as int),
            triples@ == nested_chain(ak, bk, bm, cm, i as int),
        decreases a_k.len() - i,
    {
        let key_a = a_k[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(a_k@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(ak[end] == key_a@);
            assert(bk.len() == b_k@.len());
            assert(bm.len() == b_m@.len());
            assert(cm.len() == c_m@.len());
        }
        let ghost before = triples@;
        let present_b = idx_b.map.contains_key(key_a.as_str());
        if present_b {
            let got_b = idx_b.map.get(key_a.as_str());
            let bi_b = *got_b.unwrap();
            proof {
                assert(idx_b.map@.contains_key(key_a@));
                lemma_index_bucket(bk, idx_b.buckets@, idx_b.map@, bk.len() as int, key_a@);
                assert((bi_b as int) < idx_b.buckets@.len());
            }
            let mids = &idx_b.buckets[bi_b];
            let ghost mid_ids = mids@;
            proof {
                assert(mid_ids == eq_row_ids(bk, ak[end], bk.len() as int));
                lemma_eq_members(bk, ak[end], bk.len() as int);
            }
            let mut s: usize = 0;
            let ghost at_outer = triples@;
            while s < mids.len()
                invariant
                    s <= mids.len(),
                    mids@.len() == mids.len() as int,
                    mid_ids == mids@,
                    mid_ids == eq_row_ids(bk, ak[end], bk.len() as int),
                    b_m@.len() == b_m.len() as int,
                    c_m@.len() == c_m.len() as int,
                    bm == key_views(b_m@),
                    cm == key_views(c_m@),
                    index_ok(cm, idx_c.buckets@, idx_c.map@, c_m@.len() as int),
                    forall|p: int| 0 <= p < mid_ids.len() ==> (#[trigger] mid_ids[p] as int) < bm.len(),
                    triples@ == at_outer + chain_expand_mids(i, mid_ids, bm, cm, s as int),
                decreases mids.len() - s,
            {
                let j = mids[s];
                proof {
                    assert(j == mid_ids[s as int]);
                    assert((j as int) < bm.len());
                    assert((j as int) < b_m@.len());
                }
                let key_m = b_m[j].clone();
                proof {
                    lemma_key_view_at(b_m@, j as int);
                    assert(bm[j as int] == key_m@);
                }
                let ghost before_mid = triples@;
                let present_c = idx_c.map.contains_key(key_m.as_str());
                if present_c {
                    let got_c = idx_c.map.get(key_m.as_str());
                    let bi_c = *got_c.unwrap();
                    proof {
                        assert(idx_c.map@.contains_key(key_m@));
                        lemma_index_bucket(cm, idx_c.buckets@, idx_c.map@, cm.len() as int, key_m@);
                        assert((bi_c as int) < idx_c.buckets@.len());
                    }
                    let inners = &idx_c.buckets[bi_c];
                    push_chain_inners(&mut triples, i, j, inners);
                    proof {
                        assert(inners@ == eq_row_ids(cm, key_m@, cm.len() as int));
                        assert(inners@ == eq_row_ids(cm, bm[j as int], cm.len() as int));
                        lemma_chain_expand_mids_step(i, mid_ids, bm, cm, s as int);
                        assert(triples@ == before_mid + prefix_triples(
                            i,
                            j,
                            inners@,
                            inners@.len() as int,
                        ));
                        assert(triples@ == at_outer + chain_expand_mids(i, mid_ids, bm, cm, s as int + 1));
                    }
                } else {
                    proof {
                        assert(!idx_c.map@.contains_key(key_m@));
                        lemma_index_absent(cm, idx_c.buckets@, idx_c.map@, cm.len() as int, key_m@);
                        lemma_eq_row_ids_len0(cm, key_m@, cm.len() as int);
                        assert(eq_row_ids(cm, bm[j as int], cm.len() as int) =~= Seq::<usize>::empty());
                        lemma_prefix_triples_len(i, j, Seq::<usize>::empty(), 0);
                        lemma_chain_expand_mids_step(i, mid_ids, bm, cm, s as int);
                        lemma_seq_add_empty(before_mid);
                        assert(triples@ == at_outer + chain_expand_mids(i, mid_ids, bm, cm, s as int + 1));
                    }
                }
                s = s + 1;
            }
            proof {
                lemma_chain_mid_eq_expand(i, ak[end], bk, bm, cm, bk.len() as int);
                assert(mids@ == eq_row_ids(bk, ak[end], bk.len() as int));
                assert(triples@ == before + chain_mid_product(i, ak[end], bk, bm, cm, bk.len() as int));
                lemma_nested_chain_step(ak, bk, bm, cm, end + 1);
                assert(triples@ == nested_chain(ak, bk, bm, cm, end + 1));
            }
        } else {
            proof {
                assert(!idx_b.map@.contains_key(key_a@));
                lemma_index_absent(bk, idx_b.buckets@, idx_b.map@, bk.len() as int, key_a@);
                lemma_eq_row_ids_len0(bk, key_a@, bk.len() as int);
                assert(eq_row_ids(bk, ak[end], bk.len() as int) =~= Seq::<usize>::empty());
                lemma_chain_mid_eq_expand(i, ak[end], bk, bm, cm, bk.len() as int);
                assert(chain_expand_mids(i, Seq::<usize>::empty(), bm, cm, 0)
                    =~= Seq::<(usize, usize, usize)>::empty());
                assert(chain_mid_product(i, ak[end], bk, bm, cm, bk.len() as int)
                    =~= Seq::<(usize, usize, usize)>::empty());
                lemma_nested_chain_step(ak, bk, bm, cm, end + 1);
                lemma_seq_add_empty(before);
                assert(triples@ == nested_chain(ak, bk, bm, cm, end + 1));
            }
        }
        i = i + 1;
    }
    triples
}

// SHAPE_CHAIN_END

// SHAPE_RIGHT_BEGIN
// RIGHT OUTER after honest side-swap (preserved side = outer): matched pairs
// plus one miss slot per unmatched outer. Null-extends the inner on miss.

/// Prefix of `(outer_i, Some(inner_id))` for the first `t` match ids.
pub open spec fn prefix_right_pairs(i: usize, js: Seq<usize>, t: int) -> Seq<
    (usize, Option<usize>),
>
    decreases t,
{
    if t <= 0 {
        Seq::<(usize, Option<usize>)>::empty()
    } else {
        let prev = prefix_right_pairs(i, js, t - 1);
        if 0 <= t - 1 < js.len() {
            prev.push((i, Some(js[t - 1])))
        } else {
            prev
        }
    }
}

/// Outer-major RIGHT/LEFT-outer slots for `outer[0..n]`.
pub open spec fn nested_right_pairs<K>(outer: Seq<K>, inner: Seq<K>, n: int) -> Seq<
    (usize, Option<usize>),
>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, Option<usize>)>::empty()
    } else if n - 1 >= outer.len() {
        nested_right_pairs(outer, inner, n - 1)
    } else {
        let i = (n - 1) as usize;
        let ids = eq_row_ids(inner, outer[n - 1], inner.len() as int);
        let prev = nested_right_pairs(outer, inner, n - 1);
        if ids.len() == 0 {
            prev.push((i, None))
        } else {
            prev + prefix_right_pairs(i, ids, ids.len() as int)
        }
    }
}

pub proof fn lemma_nested_right_pairs_step<K>(outer: Seq<K>, inner: Seq<K>, n: int)
    requires
        0 < n <= outer.len(),
    ensures
        eq_row_ids(inner, outer[n - 1], inner.len() as int).len() == 0 ==> nested_right_pairs(
            outer,
            inner,
            n,
        ) == nested_right_pairs(outer, inner, n - 1).push(((n - 1) as usize, None)),
        eq_row_ids(inner, outer[n - 1], inner.len() as int).len() > 0 ==> nested_right_pairs(
            outer,
            inner,
            n,
        ) == nested_right_pairs(outer, inner, n - 1) + prefix_right_pairs(
            (n - 1) as usize,
            eq_row_ids(inner, outer[n - 1], inner.len() as int),
            eq_row_ids(inner, outer[n - 1], inner.len() as int).len() as int,
        ),
{
    if eq_row_ids(inner, outer[n - 1], inner.len() as int).len() == 0 {
        assert(nested_right_pairs(outer, inner, n) == nested_right_pairs(outer, inner, n - 1).push(
            ((n - 1) as usize, None),
        ));
    } else {
        assert(nested_right_pairs(outer, inner, n) == nested_right_pairs(outer, inner, n - 1)
            + prefix_right_pairs(
            (n - 1) as usize,
            eq_row_ids(inner, outer[n - 1], inner.len() as int),
            eq_row_ids(inner, outer[n - 1], inner.len() as int).len() as int,
        ));
    }
}

pub proof fn lemma_prefix_right_len(i: usize, ids: Seq<usize>, t: int)
    requires
        0 <= t <= ids.len(),
    ensures
        prefix_right_pairs(i, ids, t).len() == t,
    decreases t,
{
    if t > 0 {
        lemma_prefix_right_len(i, ids, t - 1);
        assert(prefix_right_pairs(i, ids, t) == prefix_right_pairs(i, ids, t - 1).push((i, Some(
            ids[t - 1],
        ))));
    }
}

/// Fold a RIGHT-outer slot list from the high index downward (MethodSpec order).
pub open spec fn right_acc<A>(
    slots: Seq<(usize, Option<usize>)>,
    step_hit: spec_fn(A, int, int) -> A,
    step_miss: spec_fn(A, int) -> A,
    base: A,
    k: int,
) -> A
    decreases slots.len() - k,
{
    if k >= slots.len() {
        base
    } else {
        let tail = right_acc(slots, step_hit, step_miss, base, k + 1);
        match slots[k].1 {
            Some(j) => step_hit(tail, slots[k].0 as int, j as int),
            None => step_miss(tail, slots[k].0 as int),
        }
    }
}

/// Alias used by join fold lemmas: loop fold at origin is the slot-list fold.
pub open spec fn right_loop_acc<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step_hit: spec_fn(A, int, int) -> A,
    step_miss: spec_fn(A, int) -> A,
    base: A,
    n_outer: int,
    _i: int,
) -> A {
    right_acc(
        nested_right_pairs(outer, inner, n_outer),
        step_hit,
        step_miss,
        base,
        0,
    )
}

/// Origin fact: RIGHT-outer fold equals `right_acc` of the full slot list at 0.
pub proof fn lemma_right_at_origin<K, A>(
    outer: Seq<K>,
    inner: Seq<K>,
    step_hit: spec_fn(A, int, int) -> A,
    step_miss: spec_fn(A, int) -> A,
    base: A,
    n_outer: int,
)
    ensures
        right_loop_acc(outer, inner, step_hit, step_miss, base, n_outer, 0) == right_acc(
            nested_right_pairs(outer, inner, n_outer),
            step_hit,
            step_miss,
            base,
            0,
        ),
{
}

/// RIGHT-outer slots for one `String` key column. View equals [`nested_right_pairs`].
pub fn right_outer_pairs_str(outer: &Vec<String>, inner: &Vec<String>) -> (slots: Vec<
    (usize, Option<usize>),
>)
    ensures
        slots@ == nested_right_pairs(key_views(outer@), key_views(inner@), outer@.len() as int),
{
    let idx = build_eq_index_str(inner);
    let ghost ov = key_views(outer@);
    let ghost iv = key_views(inner@);
    let mut slots: Vec<(usize, Option<usize>)> = Vec::new();
    let mut i: usize = 0;
    while i < outer.len()
        invariant
            i <= outer.len(),
            outer@.len() == outer.len() as int,
            inner@.len() == inner.len() as int,
            ov == key_views(outer@),
            iv == key_views(inner@),
            index_ok(iv, idx.buckets@, idx.map@, inner@.len() as int),
            slots@ == nested_right_pairs(ov, iv, i as int),
        decreases outer.len() - i,
    {
        let key = outer[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(ov[end] == key@);
        }
        let ghost before = slots@;
        let hit = probe_eq_str(&idx, inner, key.as_str());
        match hit {
            Some(v) => {
                if v.len() == 0 {
                    slots.push((i, None));
                    proof {
                        assert(v@ == eq_row_ids(iv, key@, iv.len() as int));
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                        lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                        lemma_nested_right_pairs_step(ov, iv, end + 1);
                        assert(slots@ == before.push((i, None)));
                        assert(slots@ == nested_right_pairs(ov, iv, end + 1));
                    }
                } else {
                    let mut t: usize = 0;
                    let ghost ids = v@;
                    while t < v.len()
                        invariant
                            t <= v.len(),
                            v@.len() == v.len() as int,
                            ids == v@,
                            ids == eq_row_ids(iv, key@, iv.len() as int),
                            ov == key_views(outer@),
                            iv == key_views(inner@),
                            slots@ == before + prefix_right_pairs(i, ids, t as int),
                            index_ok(iv, idx.buckets@, idx.map@, inner@.len() as int),
                        decreases v.len() - t,
                    {
                        let j = v[t];
                        slots.push((i, Some(j)));
                        proof {
                            assert(prefix_right_pairs(i, ids, t as int + 1)
                                == prefix_right_pairs(i, ids, t as int).push((i, Some(ids[t as int]))));
                            assert(j == ids[t as int]);
                            assert(slots@ == before + prefix_right_pairs(i, ids, t as int).push((
                                i,
                                Some(j),
                            )));
                            assert(slots@ == before + prefix_right_pairs(i, ids, t as int + 1));
                        }
                        t = t + 1;
                    }
                    proof {
                        lemma_nested_right_pairs_step(ov, iv, end + 1);
                        assert(eq_row_ids(iv, key@, iv.len() as int).len() > 0);
                        assert(slots@ == before + prefix_right_pairs(i, ids, ids.len() as int));
                        assert(slots@ == nested_right_pairs(ov, iv, end + 1));
                    }
                }
            },
            None => {
                slots.push((i, None));
                proof {
                    assert(eq_row_ids(iv, key@, iv.len() as int).len() == 0);
                    lemma_eq_row_ids_len0(iv, key@, iv.len() as int);
                    lemma_nested_right_pairs_step(ov, iv, end + 1);
                    assert(slots@ == before.push((i, None)));
                    assert(slots@ == nested_right_pairs(ov, iv, end + 1));
                }
            },
        }
        i = i + 1;
    }
    slots
}

// SHAPE_RIGHT_END

// SHAPE_FULL_BEGIN
// FULL OUTER JOIN: matched pairs, then unmatched left, then unmatched right.
// Parts reuse nested_eq_pairs / nested_anti_misses; no whole-join Trusted.

/// Three-phase FULL OUTER fold (pair list, then left misses, then right misses).
pub open spec fn full_acc<A>(
    pairs: Seq<(usize, usize)>,
    left_miss: Seq<usize>,
    right_miss: Seq<usize>,
    step_pair: spec_fn(A, int, int) -> A,
    step_left: spec_fn(A, int) -> A,
    step_right: spec_fn(A, int) -> A,
    base: A,
) -> A {
    let after_pairs = pair_acc(pairs, step_pair, base, 0);
    let after_left = miss_acc(left_miss, step_left, after_pairs, 0);
    miss_acc(right_miss, step_right, after_left, 0)
}

/// Origin: ``full_acc`` is pair_acc then left miss_acc then right miss_acc at 0.
pub proof fn lemma_full_at_origin<A>(
    pairs: Seq<(usize, usize)>,
    left_miss: Seq<usize>,
    right_miss: Seq<usize>,
    step_pair: spec_fn(A, int, int) -> A,
    step_left: spec_fn(A, int) -> A,
    step_right: spec_fn(A, int) -> A,
    base: A,
)
    ensures
        full_acc(pairs, left_miss, right_miss, step_pair, step_left, step_right, base)
            == miss_acc(
            right_miss,
            step_right,
            miss_acc(left_miss, step_left, pair_acc(pairs, step_pair, base, 0), 0),
            0,
        ),
{
}

/// Matched pairs + left anti-misses + right anti-misses (String keys).
pub fn full_outer_parts_str(left: &Vec<String>, right: &Vec<String>) -> (parts: (
    Vec<(usize, usize)>,
    Vec<usize>,
    Vec<usize>,
))
    ensures
        parts.0@ == nested_eq_pairs(
            key_views(left@),
            key_views(right@),
            left@.len() as int,
        ),
        parts.1@ == nested_anti_misses(
            key_views(left@),
            key_views(right@),
            left@.len() as int,
        ),
        parts.2@ == nested_anti_misses(
            key_views(right@),
            key_views(left@),
            right@.len() as int,
        ),
{
    let pairs = equijoin_pairs_str(left, right);
    let left_miss = anti_miss_rows_str(left, right);
    let right_miss = anti_miss_rows_str(right, left);
    (pairs, left_miss, right_miss)
}
// SHAPE_FULL_END

// SHAPE_Q6_BEGIN
/// Holdout Q6: hub ⋈ 1-col mid ⋈ 3-col inner (num⋈sub on adsh, num⋈pre on adsh/tag/version).
/// Match list order equals nested-loop (hub-major, mid, then inner). Reuses sub_product /
/// triple_acc; not the 1+2 string star.

/// Forward nested Q6: each hub row with every 1-col mid match and every 3-col inner match.
pub open spec fn nested_q6(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    n: int,
) -> Seq<(usize, usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize, usize)>::empty()
    } else if n - 1 >= hub_a.len() {
        nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n - 1)
    } else {
        let i = (n - 1) as usize;
        let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
        let pres = eq_row_ids3(
            pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
        );
        nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n - 1) + sub_product(
            i,
            subs,
            pres,
            subs.len() as int,
        )
    }
}

pub open spec fn nested_q6_kept(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    uom: Seq<Seq<char>>,
    fy: Seq<u32>,
    stmt: Seq<Seq<char>>,
    n: int,
) -> Seq<(usize, usize, usize)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, usize, usize)>::empty()
    } else if n - 1 >= hub_a.len() {
        nested_q6_kept(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n - 1)
    } else {
        let i = (n - 1) as usize;
        let prev = nested_q6_kept(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n - 1,
        );
        if n - 1 >= uom.len() || uom[n - 1] != "pure"@ {
            prev
        } else {
            let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
            let pres = eq_row_ids3(
                pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
            );
            let subs_k = ids_u32_eq(subs, fy, 2022u32, subs.len() as int);
            let pres_k = filter_match(pres, stmt, "BS"@, pres.len() as int);
            prev + sub_product(i, subs_k, pres_k, subs_k.len() as int)
        }
    }
}

pub proof fn lemma_nested_q6_kept_step(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    uom: Seq<Seq<char>>,
    fy: Seq<u32>,
    stmt: Seq<Seq<char>>,
    n: int,
)
    requires
        0 < n <= hub_a.len(),
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        hub_a.len() == uom.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        pre_a.len() == stmt.len(),
    ensures
        nested_q6_kept(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n)
            == {
            let prev = nested_q6_kept(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n - 1,
            );
            if uom[n - 1] != "pure"@ {
                prev
            } else {
                let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
                let pres = eq_row_ids3(
                    pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1],
                    pre_a.len() as int,
                );
                prev + sub_product(
                    (n - 1) as usize,
                    ids_u32_eq(subs, fy, 2022u32, subs.len() as int),
                    filter_match(pres, stmt, "BS"@, pres.len() as int),
                    ids_u32_eq(subs, fy, 2022u32, subs.len() as int).len() as int,
                )
            }
        },
{
    assert(n - 1 < uom.len());
}

pub proof fn lemma_triple_acc_suffix<A>(
    prev: Seq<(usize, usize, usize)>,
    extra: Seq<(usize, usize, usize)>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    j: int,
)
    requires
        0 <= j <= extra.len(),
    ensures
        triple_acc(prev + extra, step, base, prev.len() + j) == triple_acc(extra, step, base, j),
    decreases extra.len() - j,
{
    let whole = prev + extra;
    reveal_with_fuel(triple_acc, 1);
    if j < extra.len() {
        lemma_triple_acc_suffix(prev, extra, step, base, j + 1);
        lemma_right_index(prev, extra, j);
        assert(whole[prev.len() + j] == extra[j]);
    } else {
        assert(prev.len() + j == whole.len());
    }
}

pub proof fn lemma_triple_acc_concat<A>(
    prev: Seq<(usize, usize, usize)>,
    extra: Seq<(usize, usize, usize)>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    k: int,
)
    requires
        0 <= k <= prev.len(),
    ensures
        triple_acc(prev + extra, step, base, k)
            == triple_acc(prev, step, triple_acc(extra, step, base, 0), k),
    decreases prev.len() - k,
{
    let whole = prev + extra;
    let inner = triple_acc(extra, step, base, 0);
    reveal_with_fuel(triple_acc, 1);
    if k == prev.len() {
        lemma_triple_acc_suffix(prev, extra, step, base, 0);
        assert(triple_acc(whole, step, base, k) == inner);
        assert(triple_acc(prev, step, inner, k) == inner);
    } else {
        lemma_triple_acc_concat(prev, extra, step, base, k + 1);
        lemma_left_index(prev, extra, k);
        assert(whole[k] == prev[k]);
    }
}

pub proof fn lemma_tag_prefix_ext(
    i: usize,
    s: usize,
    a: Seq<usize>,
    b: Seq<usize>,
    t: int,
)
    requires
        0 <= t <= a.len(),
        t <= b.len(),
        forall|j: int| 0 <= j < t ==> a[j] == b[j],
    ensures
        tag_prefix(i, s, a, t) == tag_prefix(i, s, b, t),
    decreases t,
{
    if t > 0 {
        lemma_tag_prefix_ext(i, s, a, b, t - 1);
        reveal_with_fuel(tag_prefix, 2);
        assert(a[t - 1] == b[t - 1]);
    }
}

pub proof fn lemma_tag_prefix_of_push(i: usize, s: usize, tags: Seq<usize>, id: usize)
    ensures
        tag_prefix(i, s, tags.push(id), (tags.len() + 1) as int)
            == tag_prefix(i, s, tags, tags.len() as int).push((i, s, id)),
{
    let grown = tags.push(id);
    let t = tags.len() as int;
    assert forall|j: int| 0 <= j < t implies grown[j] == tags[j] by {
        lemma_seq_push_index_different(tags, id, j);
    };
    lemma_tag_prefix_ext(i, s, grown, tags, t);
    reveal_with_fuel(tag_prefix, 2);
    lemma_seq_push_index_same(tags, id, t);
    assert(grown[t] == id);
    assert(tag_prefix(i, s, grown, t + 1) == tag_prefix(i, s, grown, t).push((i, s, id)));
}

pub proof fn lemma_sub_product_ext(
    i: usize,
    a: Seq<usize>,
    b: Seq<usize>,
    tags: Seq<usize>,
    s_end: int,
)
    requires
        0 <= s_end <= a.len(),
        s_end <= b.len(),
        forall|j: int| 0 <= j < s_end ==> a[j] == b[j],
    ensures
        sub_product(i, a, tags, s_end) == sub_product(i, b, tags, s_end),
    decreases s_end,
{
    if s_end > 0 {
        lemma_sub_product_ext(i, a, b, tags, s_end - 1);
        assert(a[s_end - 1] == b[s_end - 1]);
        reveal_with_fuel(sub_product, 2);
    }
}

pub proof fn lemma_sub_product_push(i: usize, subs: Seq<usize>, id: usize, tags: Seq<usize>)
    ensures
        sub_product(i, subs.push(id), tags, (subs.len() + 1) as int)
            == sub_product(i, subs, tags, subs.len() as int) + tag_prefix(
            i,
            id,
            tags,
            tags.len() as int,
        ),
{
    let grown = subs.push(id);
    let t = subs.len() as int;
    assert forall|j: int| 0 <= j < t implies grown[j] == subs[j] by {
        lemma_seq_push_index_different(subs, id, j);
    };
    lemma_sub_product_ext(i, grown, subs, tags, t);
    reveal_with_fuel(sub_product, 2);
    lemma_seq_push_index_same(subs, id, t);
    assert(grown[t] == id);
    assert(sub_product(i, grown, tags, t + 1) == sub_product(i, grown, tags, t) + tag_prefix(
        i,
        id,
        tags,
        tags.len() as int,
    ));
}

pub proof fn lemma_tag_fold_filter<A>(
    i: usize,
    s: usize,
    tags: Seq<usize>,
    stmt: Seq<Seq<char>>,
    t: int,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
)
    requires
        0 <= t <= tags.len(),
        forall|j: int| 0 <= j < t ==> (tags[j] as int) < stmt.len(),
        forall|acc: A, j: int|
            #![trigger step(acc, i as int, s as int, tags[j] as int)]
            0 <= j < t && stmt[tags[j] as int] != "BS"@ ==> step(
                acc,
                i as int,
                s as int,
                tags[j] as int,
            ) == acc,
    ensures
        triple_acc(tag_prefix(i, s, tags, t), step, base, 0) == triple_acc(
            tag_prefix(
                i,
                s,
                filter_match(tags, stmt, "BS"@, t),
                filter_match(tags, stmt, "BS"@, t).len() as int,
            ),
            step,
            base,
            0,
        ),
    decreases t,
{
    let filt = filter_match(tags, stmt, "BS"@, t);
    if t > 0 {
        reveal_with_fuel(tag_prefix, 2);
        reveal_with_fuel(filter_match, 2);
        let prev = tag_prefix(i, s, tags, t - 1);
        let filt_prev = filter_match(tags, stmt, "BS"@, t - 1);
        if 0 <= t - 1 < tags.len() {
            let id = tags[t - 1];
            assert((id as int) < stmt.len());
            let x = (i, s, id);
            if stmt[id as int] == "BS"@ {
                let b2 = step(base, i as int, s as int, id as int);
                lemma_tag_fold_filter(i, s, tags, stmt, t - 1, step, b2);
                assert(tag_prefix(i, s, tags, t) == prev.push(x));
                assert(filt == filt_prev.push(id));
                lemma_tag_prefix_of_push(i, s, filt_prev, id);
                lemma_triple_acc_push_at(prev, x, step, base, 0);
                lemma_triple_acc_push_at(
                    tag_prefix(i, s, filt_prev, filt_prev.len() as int),
                    x,
                    step,
                    base,
                    0,
                );
            } else {
                lemma_tag_fold_filter(i, s, tags, stmt, t - 1, step, base);
                assert(tag_prefix(i, s, tags, t) == prev.push(x));
                assert(filt == filt_prev);
                assert(step(base, i as int, s as int, id as int) == base);
                lemma_triple_acc_push_at(prev, x, step, base, 0);
            }
        } else {
            lemma_tag_fold_filter(i, s, tags, stmt, t - 1, step, base);
            assert(tag_prefix(i, s, tags, t) == prev);
            assert(filt == filt_prev);
        }
    }
}

pub proof fn lemma_sub_fold_filter<A>(
    i: usize,
    subs: Seq<usize>,
    tags: Seq<usize>,
    fy: Seq<u32>,
    stmt: Seq<Seq<char>>,
    s_end: int,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
)
    requires
        0 <= s_end <= subs.len(),
        forall|sr: int| 0 <= sr < s_end ==> (subs[sr] as int) < fy.len(),
        forall|tr: int| 0 <= tr < tags.len() ==> (tags[tr] as int) < stmt.len(),
        forall|acc: A, sr: int, tr: int|
            #![trigger step(acc, i as int, subs[sr] as int, tags[tr] as int)]
            0 <= sr < s_end && 0 <= tr < tags.len() && !(fy[subs[sr] as int] == 2022
                && stmt[tags[tr] as int] == "BS"@) ==> step(
                acc,
                i as int,
                subs[sr] as int,
                tags[tr] as int,
            ) == acc,
    ensures
        triple_acc(sub_product(i, subs, tags, s_end), step, base, 0) == triple_acc(
            sub_product(
                i,
                ids_u32_eq(subs, fy, 2022u32, s_end),
                filter_match(tags, stmt, "BS"@, tags.len() as int),
                ids_u32_eq(subs, fy, 2022u32, s_end).len() as int,
            ),
            step,
            base,
            0,
        ),
    decreases s_end,
{
    let kept_tags = filter_match(tags, stmt, "BS"@, tags.len() as int);
    let kept_subs = ids_u32_eq(subs, fy, 2022u32, s_end);
    if s_end > 0 {
        let sid = subs[s_end - 1];
        let prev = sub_product(i, subs, tags, s_end - 1);
        let extra = tag_prefix(i, sid, tags, tags.len() as int);
        let kept_prev = ids_u32_eq(subs, fy, 2022u32, s_end - 1);
        reveal_with_fuel(sub_product, 2);
        reveal_with_fuel(ids_u32_eq, 2);
        assert(sub_product(i, subs, tags, s_end) == prev + extra);
        assert((sid as int) < fy.len());
        if fy[sid as int] == 2022 {
            let mid = triple_acc(extra, step, base, 0);
            lemma_tag_fold_filter(i, sid, tags, stmt, tags.len() as int, step, base);
            assert(mid == triple_acc(
                tag_prefix(i, sid, kept_tags, kept_tags.len() as int),
                step,
                base,
                0,
            ));
            lemma_sub_fold_filter(i, subs, tags, fy, stmt, s_end - 1, step, mid);
            lemma_triple_acc_concat(prev, extra, step, base, 0);
            assert(kept_subs == kept_prev.push(sid));
            lemma_sub_product_push(i, kept_prev, sid, kept_tags);
            let kept_prev_prod = sub_product(i, kept_prev, kept_tags, kept_prev.len() as int);
            let kept_extra = tag_prefix(i, sid, kept_tags, kept_tags.len() as int);
            lemma_triple_acc_concat(kept_prev_prod, kept_extra, step, base, 0);
        } else {
            assert forall|acc: A, tr: int|
                #![trigger step(acc, i as int, sid as int, tags[tr] as int)]
                0 <= tr < tags.len() implies step(acc, i as int, sid as int, tags[tr] as int) == acc by {
                assert((tags[tr] as int) < stmt.len());
                assert(fy[sid as int] != 2022);
            };
            lemma_tag_all_id(i, sid, tags, tags.len() as int, step, base);
            lemma_sub_fold_filter(i, subs, tags, fy, stmt, s_end - 1, step, base);
            lemma_triple_acc_concat(prev, extra, step, base, 0);
            assert(kept_subs == kept_prev);
        }
    }
}

pub proof fn lemma_tag_all_id<A>(
    i: usize,
    s: usize,
    tags: Seq<usize>,
    t: int,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
)
    requires
        0 <= t <= tags.len(),
        forall|acc: A, j: int|
            #![trigger step(acc, i as int, s as int, tags[j] as int)]
            0 <= j < t ==> step(acc, i as int, s as int, tags[j] as int) == acc,
    ensures
        triple_acc(tag_prefix(i, s, tags, t), step, base, 0) == base,
    decreases t,
{
    if t > 0 {
        reveal_with_fuel(tag_prefix, 2);
        let prev = tag_prefix(i, s, tags, t - 1);
        if 0 <= t - 1 < tags.len() {
            let id = tags[t - 1];
            let x = (i, s, id);
            assert(step(base, i as int, s as int, id as int) == base);
            lemma_tag_all_id(i, s, tags, t - 1, step, base);
            assert(tag_prefix(i, s, tags, t) == prev.push(x));
            lemma_triple_acc_push_at(prev, x, step, base, 0);
        } else {
            lemma_tag_all_id(i, s, tags, t - 1, step, base);
            assert(tag_prefix(i, s, tags, t) == prev);
        }
    } else {
        reveal_with_fuel(triple_acc, 1);
    }
}

pub proof fn lemma_sub_all_id<A>(
    i: usize,
    subs: Seq<usize>,
    tags: Seq<usize>,
    s_end: int,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
)
    requires
        0 <= s_end <= subs.len(),
        forall|acc: A, sr: int, tr: int|
            #![trigger step(acc, i as int, subs[sr] as int, tags[tr] as int)]
            0 <= sr < s_end && 0 <= tr < tags.len() ==> step(
                acc,
                i as int,
                subs[sr] as int,
                tags[tr] as int,
            ) == acc,
    ensures
        triple_acc(sub_product(i, subs, tags, s_end), step, base, 0) == base,
    decreases s_end,
{
    if s_end > 0 {
        let sid = subs[s_end - 1];
        let prev = sub_product(i, subs, tags, s_end - 1);
        let extra = tag_prefix(i, sid, tags, tags.len() as int);
        reveal_with_fuel(sub_product, 2);
        assert forall|acc: A, tr: int|
            #![trigger step(acc, i as int, sid as int, tags[tr] as int)]
            0 <= tr < tags.len() implies step(acc, i as int, sid as int, tags[tr] as int) == acc by {
        };
        lemma_tag_all_id(i, sid, tags, tags.len() as int, step, base);
        lemma_sub_all_id(i, subs, tags, s_end - 1, step, base);
        lemma_triple_acc_concat(prev, extra, step, base, 0);
        assert(sub_product(i, subs, tags, s_end) == prev + extra);
    }
}

pub proof fn lemma_filter_match_bounded<B>(
    ids: Seq<usize>,
    col: Seq<B>,
    k: B,
    t: int,
    bound: int,
)
    requires
        0 <= t <= ids.len(),
        forall|s: int| 0 <= s < ids.len() ==> (#[trigger] ids[s] as int) < bound,
    ensures
        forall|p: int|
            0 <= p < filter_match(ids, col, k, t).len() ==> (#[trigger] filter_match(
                ids,
                col,
                k,
                t,
            )[p] as int) < bound,
    decreases t,
{
    if t > 0 {
        lemma_filter_match_bounded(ids, col, k, t - 1, bound);
        let prev = filter_match(ids, col, k, t - 1);
        let cur = filter_match(ids, col, k, t);
        reveal_with_fuel(filter_match, 2);
        if 0 <= t - 1 < ids.len() {
            let j = ids[t - 1];
            if 0 <= j < col.len() && col[j as int] == k {
                assert(cur == prev.push(j));
                assert((j as int) < bound);
                assert forall|p: int| 0 <= p < cur.len() implies (cur[p] as int) < bound by {
                    if p < prev.len() {
                        lemma_seq_push_index_different(prev, j, p);
                    } else {
                        lemma_seq_push_index_same(prev, j, p);
                    }
                };
            }
        }
    }
}

pub proof fn lemma_ids_u32_bounded(
    ids: Seq<usize>,
    col: Seq<u32>,
    year: u32,
    t: int,
    bound: int,
)
    requires
        0 <= t <= ids.len(),
        forall|s: int| 0 <= s < ids.len() ==> (#[trigger] ids[s] as int) < bound,
    ensures
        forall|p: int|
            0 <= p < ids_u32_eq(ids, col, year, t).len() ==> (#[trigger] ids_u32_eq(
                ids,
                col,
                year,
                t,
            )[p] as int) < bound,
    decreases t,
{
    if t > 0 {
        lemma_ids_u32_bounded(ids, col, year, t - 1, bound);
        let prev = ids_u32_eq(ids, col, year, t - 1);
        let cur = ids_u32_eq(ids, col, year, t);
        reveal_with_fuel(ids_u32_eq, 2);
        if 0 <= t - 1 < ids.len() {
            let j = ids[t - 1];
            if 0 <= (j as int) < col.len() && col[j as int] == year {
                assert(cur == prev.push(j));
                assert((j as int) < bound);
                assert forall|p: int| 0 <= p < cur.len() implies (cur[p] as int) < bound by {
                    if p < prev.len() {
                        lemma_seq_push_index_different(prev, j, p);
                    } else {
                        lemma_seq_push_index_same(prev, j, p);
                    }
                };
            }
        }
    }
}

pub proof fn lemma_tag_prefix_bounded(
    i: usize,
    s: usize,
    tags: Seq<usize>,
    t: int,
    hub_len: int,
    sub_len: int,
    pre_len: int,
)
    requires
        (i as int) < hub_len,
        (s as int) < sub_len,
        0 <= t <= tags.len(),
        forall|j: int| 0 <= j < tags.len() ==> (tags[j] as int) < pre_len,
    ensures
        forall|p: int|
            0 <= p < tag_prefix(i, s, tags, t).len() ==> {
                let row = #[trigger] tag_prefix(i, s, tags, t)[p];
                &&& (row.0 as int) < hub_len
                &&& (row.1 as int) < sub_len
                &&& (row.2 as int) < pre_len
            },
    decreases t,
{
    if t > 0 {
        lemma_tag_prefix_bounded(i, s, tags, t - 1, hub_len, sub_len, pre_len);
        reveal_with_fuel(tag_prefix, 2);
        if 0 <= t - 1 < tags.len() {
            let id = tags[t - 1];
            let prev = tag_prefix(i, s, tags, t - 1);
            let cur = tag_prefix(i, s, tags, t);
            assert(cur == prev.push((i, s, id)));
            assert((id as int) < pre_len);
            assert forall|p: int| #![trigger cur[p]] 0 <= p < cur.len() implies {
                let row = cur[p];
                (row.0 as int) < hub_len && (row.1 as int) < sub_len && (row.2 as int) < pre_len
            } by {
                if p < prev.len() {
                    lemma_seq_push_index_different(prev, (i, s, id), p);
                } else {
                    lemma_seq_push_index_same(prev, (i, s, id), p);
                }
            };
        }
    }
}

pub proof fn lemma_sub_product_bounded(
    i: usize,
    subs: Seq<usize>,
    tags: Seq<usize>,
    s_end: int,
    hub_len: int,
    sub_len: int,
    pre_len: int,
)
    requires
        (i as int) < hub_len,
        0 <= s_end <= subs.len(),
        forall|sr: int| 0 <= sr < subs.len() ==> (subs[sr] as int) < sub_len,
        forall|tr: int| 0 <= tr < tags.len() ==> (tags[tr] as int) < pre_len,
    ensures
        forall|p: int|
            0 <= p < sub_product(i, subs, tags, s_end).len() ==> {
                let row = #[trigger] sub_product(i, subs, tags, s_end)[p];
                &&& (row.0 as int) < hub_len
                &&& (row.1 as int) < sub_len
                &&& (row.2 as int) < pre_len
            },
    decreases s_end,
{
    if s_end > 0 {
        lemma_sub_product_bounded(i, subs, tags, s_end - 1, hub_len, sub_len, pre_len);
        let prev = sub_product(i, subs, tags, s_end - 1);
        let sid = subs[s_end - 1];
        let extra = tag_prefix(i, sid, tags, tags.len() as int);
        reveal_with_fuel(sub_product, 2);
        assert((sid as int) < sub_len);
        lemma_tag_prefix_bounded(i, sid, tags, tags.len() as int, hub_len, sub_len, pre_len);
        assert(sub_product(i, subs, tags, s_end) == prev + extra);
        let cur = prev + extra;
        assert forall|p: int| #![trigger cur[p]] 0 <= p < cur.len() implies {
            let row = cur[p];
            (row.0 as int) < hub_len && (row.1 as int) < sub_len && (row.2 as int) < pre_len
        } by {
            if p < prev.len() {
                lemma_left_index(prev, extra, p);
            } else {
                lemma_right_index(prev, extra, p - prev.len());
            }
        };
    }
}

pub proof fn lemma_nested_q6_kept_rows_in_range(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    uom: Seq<Seq<char>>,
    fy: Seq<u32>,
    stmt: Seq<Seq<char>>,
    n: int,
)
    requires
        0 <= n <= hub_a.len(),
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        hub_a.len() == uom.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        pre_a.len() == stmt.len(),
        sub_a.len() == fy.len(),
        sub_a.len() <= usize::MAX as nat,
        pre_a.len() <= usize::MAX as nat,
    ensures
        forall|p: int|
            0 <= p < nested_q6_kept(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n,
            ).len() ==> {
                let row = #[trigger] nested_q6_kept(
                    hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n,
                )[p];
                &&& (row.0 as int) < hub_a.len()
                &&& (row.1 as int) < sub_a.len()
                &&& (row.2 as int) < pre_a.len()
            },
    decreases n,
{
    if n > 0 {
        lemma_nested_q6_kept_rows_in_range(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n - 1,
        );
        let prev = nested_q6_kept(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n - 1,
        );
        if uom[n - 1] == "pure"@ {
            let i = (n - 1) as usize;
            let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
            let pres = eq_row_ids3(
                pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
            );
            lemma_eq_row_ids_bounded(sub_a, hub_a[n - 1], sub_a.len() as int);
            lemma_eq3_members(
                pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
            );
            let subs_k = ids_u32_eq(subs, fy, 2022u32, subs.len() as int);
            let pres_k = filter_match(pres, stmt, "BS"@, pres.len() as int);
            lemma_ids_u32_bounded(subs, fy, 2022u32, subs.len() as int, sub_a.len() as int);
            lemma_filter_match_bounded(pres, stmt, "BS"@, pres.len() as int, pre_a.len() as int);
            lemma_sub_product_bounded(
                i, subs_k, pres_k, subs_k.len() as int, hub_a.len() as int, sub_a.len() as int,
                pre_a.len() as int,
            );
            let extra = sub_product(i, subs_k, pres_k, subs_k.len() as int);
            lemma_nested_q6_kept_step(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n,
            );
            let cur = prev + extra;
            assert forall|p: int| #![trigger cur[p]] 0 <= p < cur.len() implies {
                let row = cur[p];
                (row.0 as int) < hub_a.len() && (row.1 as int) < sub_a.len()
                    && (row.2 as int) < pre_a.len()
            } by {
                if p < prev.len() {
                    lemma_left_index(prev, extra, p);
                } else {
                    lemma_right_index(prev, extra, p - prev.len());
                }
            };
        }
    }
}

pub proof fn lemma_triple_acc_kept_matches<A>(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    uom: Seq<Seq<char>>,
    fy: Seq<u32>,
    stmt: Seq<Seq<char>>,
    n: int,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
)
    requires
        0 <= n <= hub_a.len(),
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        hub_a.len() == uom.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        pre_a.len() == stmt.len(),
        sub_a.len() == fy.len(),
        sub_a.len() <= usize::MAX as nat,
        pre_a.len() <= usize::MAX as nat,
        hub_a.len() <= usize::MAX as nat,
        forall|acc: A, i0: int, i1: int, i2: int|
            #![trigger step(acc, i0, i1, i2)]
            0 <= i0 < uom.len() && 0 <= i1 < fy.len() && 0 <= i2 < stmt.len() && !(
                uom[i0] == "pure"@ && stmt[i2] == "BS"@ && fy[i1] == 2022
            ) ==> step(acc, i0, i1, i2) == acc,
    ensures
        triple_acc(
            nested_q6_kept(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n),
            step,
            base,
            0,
        ) == triple_acc(nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n), step, base, 0),
    decreases n,
{
    if n > 0 {
        let prev_full = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n - 1);
        let prev_kept = nested_q6_kept(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n - 1,
        );
        let i = (n - 1) as usize;
        let subs = eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int);
        let pres = eq_row_ids3(
            pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
        );
        let full_prod = sub_product(i, subs, pres, subs.len() as int);
        lemma_nested_q6_step(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n);
        assert(nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n) == prev_full + full_prod);
        lemma_eq_row_ids_bounded(sub_a, hub_a[n - 1], sub_a.len() as int);
        lemma_eq3_members(
            pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1], pre_a.len() as int,
        );
        assert(0 <= n - 1 <= usize::MAX as int);
        assert(i as int == n - 1);
        if uom[n - 1] != "pure"@ {
            lemma_nested_q6_kept_step(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n,
            );
            assert forall|acc: A, sr: int, tr: int|
                #![trigger step(acc, i as int, subs[sr] as int, pres[tr] as int)]
                0 <= sr < subs.len() && 0 <= tr < pres.len()
                implies step(acc, i as int, subs[sr] as int, pres[tr] as int) == acc by {
                assert((subs[sr] as int) < fy.len());
                assert((pres[tr] as int) < stmt.len());
                assert(uom[i as int] != "pure"@);
            };
            lemma_sub_all_id(i, subs, pres, subs.len() as int, step, base);
            lemma_triple_acc_concat(prev_full, full_prod, step, base, 0);
            lemma_triple_acc_kept_matches(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n - 1, step, base,
            );
        } else {
            let subs_k = ids_u32_eq(subs, fy, 2022u32, subs.len() as int);
            let pres_k = filter_match(pres, stmt, "BS"@, pres.len() as int);
            let kept_prod = sub_product(i, subs_k, pres_k, subs_k.len() as int);
            lemma_nested_q6_kept_step(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n,
            );
            assert forall|acc: A, sr: int, tr: int|
                #![trigger step(acc, i as int, subs[sr] as int, pres[tr] as int)]
                0 <= sr < subs.len() && 0 <= tr < pres.len() && !(fy[subs[sr] as int] == 2022
                    && stmt[pres[tr] as int] == "BS"@)
                implies step(acc, i as int, subs[sr] as int, pres[tr] as int) == acc by {
                assert((subs[sr] as int) < fy.len());
                assert((pres[tr] as int) < stmt.len());
                assert(uom[i as int] == "pure"@);
            };
            assert forall|sr: int| 0 <= sr < subs.len() implies (subs[sr] as int) < fy.len() by {
                assert((subs[sr] as int) < sub_a.len());
            };
            assert forall|tr: int| 0 <= tr < pres.len() implies (pres[tr] as int) < stmt.len() by {
                assert((pres[tr] as int) < pre_a.len());
            };
            lemma_sub_fold_filter(i, subs, pres, fy, stmt, subs.len() as int, step, base);
            let mid = triple_acc(full_prod, step, base, 0);
            lemma_triple_acc_concat(prev_full, full_prod, step, base, 0);
            lemma_triple_acc_concat(prev_kept, kept_prod, step, base, 0);
            lemma_triple_acc_kept_matches(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, uom, fy, stmt, n - 1, step, mid,
            );
        }
    }
}

pub proof fn lemma_nested_q6_step(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    n: int,
)
    requires
        0 < n <= hub_a.len(),
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
    ensures
        nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n) == nested_q6(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n - 1,
        ) + sub_product(
            (n - 1) as usize,
            eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int),
            eq_row_ids3(
                pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1],
                pre_a.len() as int,
            ),
            eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int).len() as int,
        ),
{
    assert(nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n) == nested_q6(
        hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n - 1,
    ) + sub_product(
        (n - 1) as usize,
        eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int),
        eq_row_ids3(
            pre_a, pre_t, pre_v, hub_a[n - 1], hub_t[n - 1], hub_v[n - 1],
            pre_a.len() as int,
        ),
        eq_row_ids(sub_a, hub_a[n - 1], sub_a.len() as int).len() as int,
    ));
}

/// Q6 equijoin: hub.adsh=sub.adsh and hub.(adsh,tag,version)=pre.(adsh,tag,version).
pub fn q6_eq_triples_str(
    hub_adsh: &Vec<String>,
    hub_tag: &Vec<String>,
    hub_ver: &Vec<String>,
    sub_adsh: &Vec<String>,
    pre_adsh: &Vec<String>,
    pre_tag: &Vec<String>,
    pre_ver: &Vec<String>,
) -> (triples: Vec<(usize, usize, usize)>)
    requires
        hub_adsh@.len() == hub_tag@.len(),
        hub_adsh@.len() == hub_ver@.len(),
        pre_adsh@.len() == pre_tag@.len(),
        pre_adsh@.len() == pre_ver@.len(),
    ensures
        triples@ == nested_q6(
            key_views(hub_adsh@),
            key_views(hub_tag@),
            key_views(hub_ver@),
            key_views(sub_adsh@),
            key_views(pre_adsh@),
            key_views(pre_tag@),
            key_views(pre_ver@),
            hub_adsh@.len() as int,
        ),
{
    let idx_sub = build_eq_index_str(sub_adsh);
    let idx_pre = build_eq_index_str(pre_adsh);
    let ghost ha = key_views(hub_adsh@);
    let ghost ht = key_views(hub_tag@);
    let ghost hv = key_views(hub_ver@);
    let ghost sa = key_views(sub_adsh@);
    let ghost pa = key_views(pre_adsh@);
    let ghost pt = key_views(pre_tag@);
    let ghost pv = key_views(pre_ver@);
    let mut triples: Vec<(usize, usize, usize)> = Vec::with_capacity(hub_adsh.len());
    let mut pre_mid: Vec<usize> = Vec::new();
    let mut pres: Vec<usize> = Vec::new();
    let empty_sub: Vec<usize> = Vec::new();
    proof {
        assert(empty_sub@ =~= Seq::<usize>::empty());
    }
    let mut i: usize = 0;
    while i < hub_adsh.len()
        invariant
            i <= hub_adsh.len(),
            hub_adsh@.len() == hub_adsh.len() as int,
            hub_adsh@.len() == hub_tag@.len(),
            hub_adsh@.len() == hub_ver@.len(),
            hub_tag@.len() == hub_tag.len() as int,
            hub_ver@.len() == hub_ver.len() as int,
            sub_adsh@.len() == sub_adsh.len() as int,
            pre_adsh@.len() == pre_adsh.len() as int,
            pre_tag@.len() == pre_tag.len() as int,
            pre_ver@.len() == pre_ver.len() as int,
            pre_adsh@.len() == pre_tag@.len(),
            pre_adsh@.len() == pre_ver@.len(),
            ha == key_views(hub_adsh@),
            ht == key_views(hub_tag@),
            hv == key_views(hub_ver@),
            sa == key_views(sub_adsh@),
            pa == key_views(pre_adsh@),
            pt == key_views(pre_tag@),
            pv == key_views(pre_ver@),
            index_ok(sa, idx_sub.buckets@, idx_sub.map@, sub_adsh@.len() as int),
            index_ok(pa, idx_pre.buckets@, idx_pre.map@, pre_adsh@.len() as int),
            empty_sub@ =~= Seq::<usize>::empty(),
            triples@ == nested_q6(ha, ht, hv, sa, pa, pt, pv, i as int),
        decreases hub_adsh.len() - i,
    {
        let key_a = &hub_adsh[i];
        let key_t = &hub_tag[i];
        let key_v = &hub_ver[i];
        let ghost end = i as int;
        proof {
            lemma_key_view_at(hub_adsh@, end);
            lemma_key_view_at(hub_tag@, end);
            lemma_key_view_at(hub_ver@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            broadcast use vstd::seq::lemma_seq_new_len;
            assert(ha[end] == key_a@);
            assert(ht[end] == key_t@);
            assert(hv[end] == key_v@);
            assert(sa.len() == sub_adsh@.len());
            assert(pa.len() == pre_adsh@.len());
            assert(pt.len() == pre_tag@.len());
            assert(pv.len() == pre_ver@.len());
            assert(sa.len() as int <= usize::MAX as int);
            assert(pa.len() as int <= usize::MAX as int);
        }
        let present_a = idx_sub.map.contains_key(key_a.as_str());
        let present_p = idx_pre.map.contains_key(key_a.as_str());
        let sub_ids: &Vec<usize>;
        if present_a {
            let got_a = idx_sub.map.get(key_a.as_str());
            let bi_a = *got_a.unwrap();
            proof {
                assert(idx_sub.map@.contains_key(key_a@));
                lemma_index_bucket(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                assert((bi_a as int) < idx_sub.buckets@.len());
            }
            sub_ids = &idx_sub.buckets[bi_a];
            proof {
                assert(sub_ids@ == idx_sub.buckets@[bi_a as int]@);
                assert(idx_sub.buckets@[(bi_a as int)]@ == eq_row_ids(sa, key_a@, sa.len() as int));
                assert(key_a@ == ha[end]);
                assert(sub_ids@ == eq_row_ids(sa, ha[end], sa.len() as int));
            }
        } else {
            proof {
                assert(!idx_sub.map@.contains_key(key_a@));
                lemma_index_absent(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                lemma_eq_row_ids_len0(sa, key_a@, sa.len() as int);
            }
            sub_ids = &empty_sub;
            proof {
                assert(empty_sub@ =~= Seq::<usize>::empty());
                assert(sub_ids@ == empty_sub@);
                assert(key_a@ == ha[end]);
                assert(eq_row_ids(sa, ha[end], sa.len() as int) =~= Seq::<usize>::empty());
                assert(sub_ids@ == eq_row_ids(sa, ha[end], sa.len() as int));
            }
        }
        if present_p {
            let got_p = idx_pre.map.get(key_a.as_str());
            let bi_p = *got_p.unwrap();
            proof {
                assert(idx_pre.map@.contains_key(key_a@));
                lemma_index_bucket(pa, idx_pre.buckets@, idx_pre.map@, pa.len() as int, key_a@);
                lemma_eq_row_ids_bounded(pa, key_a@, pa.len() as int);
                assert((bi_p as int) < idx_pre.buckets@.len());
            }
            let pre_bucket = &idx_pre.buckets[bi_p];
            filter_row_ids_str_into(&mut pre_mid, pre_bucket, pre_tag, key_t);
            proof {
                lemma_filter_is_ids2(pa, pt, key_a@, key_t@, pa.len() as int);
                assert(pre_mid@ == eq_row_ids2(pa, pt, ha[end], ht[end], pa.len() as int));
                lemma_eq2_bounded(pa, pt, ha[end], ht[end], pa.len() as int);
                assert(pa.len() == pre_ver@.len());
                assert forall|t: int|
                    0 <= t < pre_mid@.len() implies (#[trigger] pre_mid@[t] as int)
                        < pre_ver@.len() by {
                    assert(
                        (eq_row_ids2(pa, pt, ha[end], ht[end], pa.len() as int)[t] as int)
                            < pa.len()
                    );
                    assert(pre_mid@[t] == eq_row_ids2(pa, pt, ha[end], ht[end], pa.len() as int)[t]);
                };
            }
            filter_row_ids_str_into(&mut pres, &pre_mid, pre_ver, key_v);
            proof {
                lemma_filter_is_ids3(pa, pt, pv, key_a@, key_t@, key_v@, pa.len() as int);
            }
        } else {
            pres.clear();
            proof {
                assert(!idx_pre.map@.contains_key(key_a@));
                lemma_index_absent(pa, idx_pre.buckets@, idx_pre.map@, pa.len() as int, key_a@);
                lemma_eq_row_ids_len0(pa, key_a@, pa.len() as int);
                lemma_filter_is_ids2(pa, pt, key_a@, key_t@, pa.len() as int);
                lemma_filter_is_ids3(pa, pt, pv, key_a@, key_t@, key_v@, pa.len() as int);
                assert(eq_row_ids3(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int)
                    =~= Seq::<usize>::empty());
                assert(pres@ =~= Seq::<usize>::empty());
            }
        }
        let ghost before = triples@;
        proof {
            assert(sub_ids@ == eq_row_ids(sa, ha[end], sa.len() as int));
            assert(pres@ == eq_row_ids3(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int));
        }
        push_star_product(&mut triples, i, sub_ids, &pres);
        proof {
            lemma_nested_q6_step(ha, ht, hv, sa, pa, pt, pv, end + 1);
            assert(triples@ == before + sub_product(i, sub_ids@, pres@, sub_ids@.len() as int));
            assert(triples@ == nested_q6(ha, ht, hv, sa, pa, pt, pv, end + 1));
        }
        i = i + 1;
    }
    triples
}

/// Multiplier for the checked string hash. Same mix as the fast helper hasher.
pub const FX_K: u64 = 0x517cc1b727220a95;

pub open spec fn fx_mix(h: u64, b: u8) -> u64 {
    vstd::wrapping::u64_specs::wrapping_add(
        vstd::wrapping::u64_specs::wrapping_mul(h, FX_K),
        b as u64,
    )
}

/// Hash of `s[0..done)`, starting from `h0`.
pub open spec fn fx_prefix(s: Seq<char>, done: int, h0: u64) -> u64
    decreases done,
{
    if done <= 0 {
        h0
    } else {
        fx_mix(fx_prefix(s, done - 1, h0), s[done - 1] as u8)
    }
}

pub open spec fn fx_feed_spec(s: Seq<char>, h0: u64) -> u64 {
    fx_prefix(s, s.len() as int, h0)
}

/// Hash of three strings, with a separator byte so different splits do not alias.
pub open spec fn fx_triple(a: Seq<char>, b: Seq<char>, c: Seq<char>) -> u64 {
    let h1 = fx_feed_spec(a, 0u64);
    let h2 = fx_mix(h1, 0xffu8);
    let h3 = fx_feed_spec(b, h2);
    let h4 = fx_mix(h3, 0xffu8);
    fx_feed_spec(c, h4)
}

#[inline(always)]
pub fn fx_feed(s: &str, h0: u64) -> (h: u64)
    ensures
        h == fx_feed_spec(s@, h0),
{
    let n = s.unicode_len();
    let mut h = h0;
    let mut i: usize = 0;
    proof {
        assert(n as int == s@.len());
        assert(h == fx_prefix(s@, 0, h0));
    }
    if s.is_ascii() {
        proof {
            assert(is_ascii(s));
        }
        while i < n
            invariant
                is_ascii(s),
                i <= n,
                n as int == s@.len(),
                h == fx_prefix(s@, i as int, h0),
            decreases n - i,
        {
            let b = s.get_ascii(i);
            let prev = h;
            proof {
                assert(i < s@.len());
                assert(b == s@[i as int] as u8);
                assert(fx_prefix(s@, i as int + 1, h0) == fx_mix(prev, b));
            }
            h = prev.wrapping_mul(FX_K).wrapping_add(b as u64);
            proof {
                assert(h == fx_mix(prev, b));
            }
            i = i + 1;
        }
    } else {
        while i < n
            invariant
                i <= n,
                n as int == s@.len(),
                h == fx_prefix(s@, i as int, h0),
            decreases n - i,
        {
            let c = s.get_char(i);
            let b = c as u8;
            let prev = h;
            proof {
                assert(i < s@.len());
                assert(c == s@[i as int]);
                assert(b == s@[i as int] as u8);
                assert(fx_prefix(s@, i as int + 1, h0) == fx_mix(prev, b));
            }
            h = prev.wrapping_mul(FX_K).wrapping_add(b as u64);
            proof {
                assert(h == fx_mix(prev, b));
            }
            i = i + 1;
        }
    }
    proof {
        assert(i == n);
        assert(h == fx_prefix(s@, s@.len() as int, h0));
    }
    h
}

#[inline(always)]
pub fn fx_triple_exec(a: &str, b: &str, c: &str) -> (h: u64)
    ensures
        h == fx_triple(a@, b@, c@),
{
    let h1 = fx_feed(a, 0u64);
    let h2 = h1.wrapping_mul(FX_K).wrapping_add(0xffu64);
    proof {
        assert(h2 == fx_mix(h1, 0xffu8));
    }
    let h3 = fx_feed(b, h2);
    let h4 = h3.wrapping_mul(FX_K).wrapping_add(0xffu64);
    proof {
        assert(h4 == fx_mix(h3, 0xffu8));
    }
    fx_feed(c, h4)
}

/// Ids whose three string columns equal the probe, read back from a hash bucket.
pub open spec fn fx_kept_ids(
    hashes: Seq<u64>,
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    end: int,
) -> Seq<usize> {
    let bucket = eq_row_ids(hashes, fx_triple(ka, kb, kc), end);
    let f1 = filter_match(bucket, a, ka, bucket.len() as int);
    let f2 = filter_match(f1, b, kb, f1.len() as int);
    filter_match(f2, c, kc, f2.len() as int)
}

/// A hash hit filtered by the three strings is exactly the three-column match list.
/// Collisions stay in the hash bucket and are dropped by the string filters.
#[verifier::spinoff_prover]
pub proof fn lemma_fx_kept_is_eq3(
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    hashes: Seq<u64>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    end: int,
)
    requires
        a.len() == b.len(),
        a.len() == c.len(),
        a.len() == hashes.len(),
        0 <= end <= a.len(),
        end <= usize::MAX as int,
        forall|i: int| 0 <= i < hashes.len() ==> hashes[i] == fx_triple(a[i], b[i], c[i]),
    ensures
        fx_kept_ids(hashes, a, b, c, ka, kb, kc, end) == eq_row_ids3(a, b, c, ka, kb, kc, end),
    decreases end,
{
    if end > 0 {
        assert(0 <= end - 1 <= usize::MAX as int);
        lemma_fx_kept_is_eq3(a, b, c, hashes, ka, kb, kc, end - 1);
        let row = (end - 1) as usize;
        assert(row as int == end - 1);
        let h = fx_triple(ka, kb, kc);
        assert(hashes[end - 1] == fx_triple(a[end - 1], b[end - 1], c[end - 1]));
        lemma_eq_row_ids_step(hashes, h, end - 1, row);
        let prev_b = eq_row_ids(hashes, h, end - 1);
        let prev_kept = fx_kept_ids(hashes, a, b, c, ka, kb, kc, end - 1);
        if hashes[end - 1] == h {
            assert(eq_row_ids(hashes, h, end) == prev_b.push(row));
            lemma_seq_push_len(prev_b, row);
            assert((row as int) < a.len());
            lemma_filter_push(prev_b, a, ka, row);
            let f1_prev = filter_match(prev_b, a, ka, prev_b.len() as int);
            let bucket = prev_b.push(row);
            let f1 = filter_match(bucket, a, ka, bucket.len() as int);
            if a[end - 1] == ka {
                assert(f1 == f1_prev.push(row));
                lemma_seq_push_len(f1_prev, row);
                assert((row as int) < b.len());
                lemma_filter_push(f1_prev, b, kb, row);
                let f2_prev = filter_match(f1_prev, b, kb, f1_prev.len() as int);
                let f2 = filter_match(f1, b, kb, f1.len() as int);
                if b[end - 1] == kb {
                    assert(f2 == f2_prev.push(row));
                    lemma_seq_push_len(f2_prev, row);
                    assert((row as int) < c.len());
                    lemma_filter_push(f2_prev, c, kc, row);
                    let f3_prev = filter_match(f2_prev, c, kc, f2_prev.len() as int);
                    let f3 = filter_match(f2, c, kc, f2.len() as int);
                    assert(prev_kept == f3_prev);
                    assert(fx_kept_ids(hashes, a, b, c, ka, kb, kc, end) == f3);
                    lemma_eq_row_ids3_step(a, b, c, ka, kb, kc, end - 1, row);
                    if c[end - 1] == kc {
                        assert(f3 == f3_prev.push(row));
                        assert(fx_triple(a[end - 1], b[end - 1], c[end - 1]) == h);
                        assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == prev_kept.push(row));
                    } else {
                        assert(f3 == f3_prev);
                        assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == eq_row_ids3(
                            a, b, c, ka, kb, kc, end - 1,
                        ));
                    }
                } else {
                    assert(f2 == f2_prev);
                    let f3_prev = filter_match(f2_prev, c, kc, f2_prev.len() as int);
                    let f3 = filter_match(f2, c, kc, f2.len() as int);
                    assert(f3 == f3_prev);
                    assert(prev_kept == f3_prev);
                    assert(fx_kept_ids(hashes, a, b, c, ka, kb, kc, end) == f3);
                    lemma_eq_row_ids3_step(a, b, c, ka, kb, kc, end - 1, row);
                    assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == eq_row_ids3(
                        a, b, c, ka, kb, kc, end - 1,
                    ));
                }
            } else {
                assert(f1 == f1_prev);
                let f2_prev = filter_match(f1_prev, b, kb, f1_prev.len() as int);
                let f2 = filter_match(f1, b, kb, f1.len() as int);
                assert(f2 == f2_prev);
                let f3_prev = filter_match(f2_prev, c, kc, f2_prev.len() as int);
                let f3 = filter_match(f2, c, kc, f2.len() as int);
                assert(f3 == f3_prev);
                assert(prev_kept == f3_prev);
                assert(fx_kept_ids(hashes, a, b, c, ka, kb, kc, end) == f3);
                lemma_eq_row_ids3_step(a, b, c, ka, kb, kc, end - 1, row);
                assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == eq_row_ids3(
                    a, b, c, ka, kb, kc, end - 1,
                ));
            }
        } else {
            assert(eq_row_ids(hashes, h, end) == prev_b);
            assert(fx_kept_ids(hashes, a, b, c, ka, kb, kc, end) == prev_kept);
            if a[end - 1] == ka && b[end - 1] == kb && c[end - 1] == kc {
                assert(fx_triple(a[end - 1], b[end - 1], c[end - 1]) == h);
                assert(hashes[end - 1] == h);
                assert(false);
            }
            lemma_eq_row_ids3_step(a, b, c, ka, kb, kc, end - 1, row);
            assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == eq_row_ids3(
                a, b, c, ka, kb, kc, end - 1,
            ));
        }
    }
}

pub proof fn lemma_filter_preserves_bound<B>(ids: Seq<usize>, col: Seq<B>, k: B, t: int, bound: int)
    requires
        0 <= t <= ids.len(),
        forall|u: int| 0 <= u < ids.len() ==> (ids[u] as int) < bound,
    ensures
        forall|u: int|
            0 <= u < filter_match(ids, col, k, t).len() ==> (
                #[trigger] filter_match(ids, col, k, t)[u] as int
            ) < bound,
    decreases t,
{
    if t > 0 {
        lemma_filter_preserves_bound(ids, col, k, t - 1, bound);
        let prev = filter_match(ids, col, k, t - 1);
        let cur = filter_match(ids, col, k, t);
        if 0 <= t - 1 < ids.len() {
            let j = ids[t - 1];
            if 0 <= j < col.len() && col[j as int] == k {
                assert(cur == prev.push(j));
                assert((j as int) < bound);
                assert forall|u: int| 0 <= u < cur.len() implies (cur[u] as int) < bound by {
                    if u == prev.len() {
                        assert(cur[u] == j);
                    } else {
                        lemma_seq_push_index_different(prev, j, u);
                    }
                };
            } else {
                assert(cur == prev);
            }
        } else {
            assert(cur == prev);
        }
    }
}

pub open spec fn iota_ids(n: int) -> Seq<usize>
    decreases n,
{
    if n <= 0 {
        Seq::<usize>::empty()
    } else {
        iota_ids(n - 1).push((n - 1) as usize)
    }
}

pub proof fn lemma_iota_len(n: int)
    requires
        0 <= n,
    ensures
        iota_ids(n).len() as int == n,
    decreases n,
{
    if n > 0 {
        lemma_iota_len(n - 1);
        lemma_seq_push_len(iota_ids(n - 1), (n - 1) as usize);
    }
}

pub proof fn lemma_iota_bounded(n: int)
    requires
        0 <= n <= usize::MAX as int,
    ensures
        iota_ids(n).len() as int == n,
        forall|u: int|
            #![trigger iota_ids(n)[u]]
            0 <= u < n ==> iota_ids(n)[u] == (u as usize),
    decreases n,
{
    lemma_iota_len(n);
    if n > 0 {
        lemma_iota_bounded(n - 1);
        let s = iota_ids(n - 1);
        lemma_seq_push_len(s, (n - 1) as usize);
        assert forall|u: int| 0 <= u < n implies iota_ids(n)[u] == (u as usize) by {
            if u == n - 1 {
                lemma_seq_push_index_same(s, (n - 1) as usize, u);
            } else {
                lemma_seq_push_index_different(s, (n - 1) as usize, u);
                assert(iota_ids(n)[u] == s[u]);
            }
        };
    }
}

pub open spec fn pick_rows(rows: Seq<usize>, pos: Seq<usize>, t: int) -> Seq<usize>
    decreases t,
{
    if t <= 0 {
        Seq::<usize>::empty()
    } else {
        let prev = pick_rows(rows, pos, t - 1);
        if 0 <= t - 1 < pos.len() {
            let p = pos[t - 1];
            if 0 <= p < rows.len() {
                prev.push(rows[p as int])
            } else {
                prev
            }
        } else {
            prev
        }
    }
}

pub open spec fn filter3(
    ids: Seq<usize>,
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
) -> Seq<usize> {
    let f1 = filter_match(ids, a, ka, ids.len() as int);
    let f2 = filter_match(f1, b, kb, f1.len() as int);
    filter_match(f2, c, kc, f2.len() as int)
}

/// String-filtered presentation ids reached through a compact hash of statement-matching rows.
pub closed spec fn fx_kept_picked(
    rows: Seq<usize>,
    hashes: Seq<u64>,
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
) -> Seq<usize> {
    let bucket = eq_row_ids(hashes, fx_triple(ka, kb, kc), hashes.len() as int);
    let picked = pick_rows(rows, bucket, bucket.len() as int);
    filter3(picked, a, b, c, ka, kb, kc)
}

pub closed spec fn bs_filtered_eq3(
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    stmt: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    end: int,
) -> Seq<usize> {
    let pres = eq_row_ids3(a, b, c, ka, kb, kc, end);
    filter_match(pres, stmt, "BS"@, pres.len() as int)
}

pub proof fn lemma_pick_step(rows: Seq<usize>, pos: Seq<usize>, t: int)
    requires
        0 < t <= pos.len(),
    ensures
        ({
            let p = pos[t - 1];
            let prev = pick_rows(rows, pos, t - 1);
            &&& (0 <= p < rows.len() ==> pick_rows(rows, pos, t) == prev.push(rows[p as int]))
            &&& (!(0 <= p < rows.len()) ==> pick_rows(rows, pos, t) == prev)
        }),
{
    let p = pos[t - 1];
    let prev = pick_rows(rows, pos, t - 1);
    if 0 <= p < rows.len() {
        assert(pick_rows(rows, pos, t) == prev.push(rows[p as int]));
    } else {
        assert(pick_rows(rows, pos, t) == prev);
    }
}

pub proof fn lemma_push_prefix<A>(s: Seq<A>, x: A)
    ensures
        s.push(x).subrange(0, s.len() as int) == s,
{
    let p = s.push(x);
    lemma_seq_push_len(s, x);
    assert forall|i: int| 0 <= i < s.len() implies p[i] == s[i] by {
        lemma_seq_push_index_different(s, x, i);
    };
    assert(p.subrange(0, s.len() as int) =~= s);
}

pub proof fn lemma_pick_rows_agree(
    rows: Seq<usize>,
    rows_p: Seq<usize>,
    pos: Seq<usize>,
    t: int,
)
    requires
        0 <= t <= pos.len(),
        forall|u: int|
            #![trigger pos[u]]
            0 <= u < t ==> {
                let p = pos[u];
                &&& 0 <= p < rows.len()
                &&& p < rows_p.len()
                &&& rows[p as int] == rows_p[p as int]
            },
    ensures
        pick_rows(rows, pos, t) == pick_rows(rows_p, pos, t),
    decreases t,
{
    if t > 0 {
        lemma_pick_rows_agree(rows, rows_p, pos, t - 1);
        lemma_pick_step(rows, pos, t);
        lemma_pick_step(rows_p, pos, t);
    }
}

pub proof fn lemma_pick_pos_prefix(rows: Seq<usize>, pos: Seq<usize>, extra: usize, t: int)
    requires
        0 <= t <= pos.len(),
    ensures
        pick_rows(rows, pos.push(extra), t) == pick_rows(rows, pos, t),
    decreases t,
{
    if t > 0 {
        lemma_pick_pos_prefix(rows, pos, extra, t - 1);
        lemma_seq_push_len(pos, extra);
        lemma_seq_push_index_different(pos, extra, t - 1);
        assert(pos.push(extra)[t - 1] == pos[t - 1]);
        lemma_pick_step(rows, pos.push(extra), t);
        lemma_pick_step(rows, pos, t);
        let p = pos[t - 1];
        let prev = pick_rows(rows, pos, t - 1);
        assert(pick_rows(rows, pos.push(extra), t - 1) == prev);
        if 0 <= p < rows.len() {
            assert(pick_rows(rows, pos.push(extra), t) == prev.push(rows[p as int]));
            assert(pick_rows(rows, pos, t) == prev.push(rows[p as int]));
        } else {
            assert(pick_rows(rows, pos.push(extra), t) == prev);
            assert(pick_rows(rows, pos, t) == prev);
        }
    }
}

pub proof fn lemma_eq_row_ids_on_prefix<K>(keys: Seq<K>, k: K, end: int)
    requires
        0 <= end <= keys.len(),
    ensures
        eq_row_ids(keys, k, end) == eq_row_ids(keys.subrange(0, end), k, end),
    decreases end,
{
    if end > 0 {
        lemma_eq_row_ids_on_prefix(keys, k, end - 1);
        let sub = keys.subrange(0, end);
        assert(sub.len() == end);
        assert(sub[end - 1] == keys[end - 1]);
        assert(eq_row_ids(keys, k, end - 1) == eq_row_ids(keys.subrange(0, end - 1), k, end - 1));
        assert(sub.subrange(0, end - 1) == keys.subrange(0, end - 1));
        lemma_eq_row_ids_on_prefix(sub, k, end - 1);
    }
}

pub proof fn lemma_filter3_push(
    picked: Seq<usize>,
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    j: usize,
)
    requires
        (j as int) < a.len(),
        (j as int) < b.len(),
        (j as int) < c.len(),
    ensures
        a[j as int] == ka && b[j as int] == kb && c[j as int] == kc ==> filter3(
            picked.push(j),
            a,
            b,
            c,
            ka,
            kb,
            kc,
        ) == filter3(picked, a, b, c, ka, kb, kc).push(j),
        !(a[j as int] == ka && b[j as int] == kb && c[j as int] == kc) ==> filter3(
            picked.push(j),
            a,
            b,
            c,
            ka,
            kb,
            kc,
        ) == filter3(picked, a, b, c, ka, kb, kc),
{
    let ext = picked.push(j);
    lemma_seq_push_len(picked, j);
    assert(ext.len() as int == (picked.len() + 1) as int);
    lemma_filter_push(picked, a, ka, j);
    let old_f1 = filter_match(picked, a, ka, picked.len() as int);
    let new_f1 = filter_match(ext, a, ka, ext.len() as int);
    let old3 = filter3(picked, a, b, c, ka, kb, kc);
    let new3 = filter3(ext, a, b, c, ka, kb, kc);
    if a[j as int] == ka {
        assert(new_f1 == old_f1.push(j));
        lemma_seq_push_len(old_f1, j);
        lemma_filter_push(old_f1, b, kb, j);
        let old_f2 = filter_match(old_f1, b, kb, old_f1.len() as int);
        let new_f2 = filter_match(new_f1, b, kb, new_f1.len() as int);
        if b[j as int] == kb {
            assert(new_f2 == old_f2.push(j));
            lemma_seq_push_len(old_f2, j);
            lemma_filter_push(old_f2, c, kc, j);
            let old_f3 = filter_match(old_f2, c, kc, old_f2.len() as int);
            let new_f3 = filter_match(new_f2, c, kc, new_f2.len() as int);
            assert(old3 == old_f3);
            assert(new3 == new_f3);
            if c[j as int] == kc {
                assert(new_f3 == old_f3.push(j));
                assert(new3 == old3.push(j));
            } else {
                assert(new_f3 == old_f3);
                assert(new3 == old3);
            }
        } else {
            assert(new_f2 == old_f2);
            assert(filter_match(new_f2, c, kc, new_f2.len() as int) == filter_match(
                old_f2,
                c,
                kc,
                old_f2.len() as int,
            ));
            assert(new3 == old3);
        }
    } else {
        assert(new_f1 == old_f1);
        assert(filter_match(new_f1, b, kb, new_f1.len() as int) == filter_match(
            old_f1,
            b,
            kb,
            old_f1.len() as int,
        ));
        assert(new3 == old3);
    }
}

#[verifier::spinoff_prover]
#[verifier::rlimit(8)]
pub proof fn lemma_bs_pick_base(
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    stmt: Seq<Seq<char>>,
    rows: Seq<usize>,
    hashes: Seq<u64>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
)
    requires
        rows == filter_match(iota_ids(0), stmt, "BS"@, 0),
        hashes.len() == rows.len(),
    ensures
        fx_kept_picked(rows, hashes, a, b, c, ka, kb, kc) == bs_filtered_eq3(
            a, b, c, stmt, ka, kb, kc, 0,
        ),
{
    reveal(fx_kept_picked);
    reveal(bs_filtered_eq3);
    assert(iota_ids(0) =~= Seq::<usize>::empty());
    assert(rows =~= Seq::<usize>::empty());
    assert(hashes.len() == 0);
    let h = fx_triple(ka, kb, kc);
    assert(eq_row_ids(hashes, h, 0) =~= Seq::<usize>::empty());
    assert(pick_rows(rows, Seq::<usize>::empty(), 0) =~= Seq::<usize>::empty());
    assert(fx_kept_picked(rows, hashes, a, b, c, ka, kb, kc) =~= Seq::<usize>::empty());
    assert(eq_row_ids3(a, b, c, ka, kb, kc, 0) =~= Seq::<usize>::empty());
    assert(bs_filtered_eq3(a, b, c, stmt, ka, kb, kc, 0) =~= Seq::<usize>::empty());
}

#[verifier::spinoff_prover]
#[verifier::rlimit(8)]
pub proof fn lemma_bs_rows_skip(
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    stmt: Seq<Seq<char>>,
    rows: Seq<usize>,
    hashes: Seq<u64>,
    end: int,
)
    requires
        a.len() == b.len(),
        a.len() == c.len(),
        a.len() == stmt.len(),
        0 < end <= a.len(),
        end <= usize::MAX as int,
        stmt[end - 1] != "BS"@,
        rows == filter_match(iota_ids(end), stmt, "BS"@, end),
        hashes.len() == rows.len(),
        forall|j: int|
            0 <= j < rows.len() ==> {
                let r = #[trigger] rows[j] as int;
                &&& 0 <= r < end
                &&& hashes[j] == fx_triple(a[r], b[r], c[r])
                &&& stmt[r] == "BS"@
            },
    ensures
        rows == filter_match(iota_ids(end - 1), stmt, "BS"@, end - 1),
        forall|j: int|
            0 <= j < rows.len() ==> {
                let r = #[trigger] rows[j] as int;
                &&& 0 <= r < end - 1
                &&& hashes[j] == fx_triple(a[r], b[r], c[r])
                &&& stmt[r] == "BS"@
            },
{
    lemma_iota_len(end - 1);
    let s = iota_ids(end - 1);
    assert(s.len() as int == end - 1);
    assert((s.len() + 1) as int == end);
    assert(iota_ids(end) == s.push((end - 1) as usize));
    lemma_filter_push(s, stmt, "BS"@, (end - 1) as usize);
    assert(filter_match(iota_ids(end), stmt, "BS"@, end) == filter_match(
        s, stmt, "BS"@, s.len() as int,
    ));
    assert(rows == filter_match(s, stmt, "BS"@, end - 1));
    assert forall|j: int| 0 <= j < rows.len() implies {
        let r = #[trigger] rows[j] as int;
        &&& 0 <= r < end - 1
        &&& hashes[j] == fx_triple(a[r], b[r], c[r])
        &&& stmt[r] == "BS"@
    } by {
        let r = rows[j] as int;
        assert(0 <= r < end);
        assert(stmt[r] == "BS"@);
        assert(r != end - 1);
    };
}

#[verifier::spinoff_prover]
#[verifier::rlimit(8)]
pub proof fn lemma_bs_filtered_skip(
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    stmt: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    end: int,
)
    requires
        a.len() == b.len(),
        a.len() == c.len(),
        a.len() == stmt.len(),
        0 < end <= a.len(),
        end <= usize::MAX as int,
        stmt[end - 1] != "BS"@,
    ensures
        bs_filtered_eq3(a, b, c, stmt, ka, kb, kc, end) == bs_filtered_eq3(
            a, b, c, stmt, ka, kb, kc, end - 1,
        ),
{
    reveal(bs_filtered_eq3);
    lemma_eq_row_ids3_step(a, b, c, ka, kb, kc, end - 1, (end - 1) as usize);
    let prev_eq = eq_row_ids3(a, b, c, ka, kb, kc, end - 1);
    if a[end - 1] == ka && b[end - 1] == kb && c[end - 1] == kc {
        assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == prev_eq.push((end - 1) as usize));
        lemma_seq_push_len(prev_eq, (end - 1) as usize);
        lemma_filter_push(prev_eq, stmt, "BS"@, (end - 1) as usize);
        assert(stmt[end - 1] != "BS"@);
        assert(bs_filtered_eq3(a, b, c, stmt, ka, kb, kc, end) == filter_match(
            prev_eq, stmt, "BS"@, prev_eq.len() as int,
        ));
        assert(bs_filtered_eq3(a, b, c, stmt, ka, kb, kc, end - 1) == filter_match(
            prev_eq, stmt, "BS"@, prev_eq.len() as int,
        ));
    } else {
        assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == prev_eq);
        assert(bs_filtered_eq3(a, b, c, stmt, ka, kb, kc, end) == bs_filtered_eq3(
            a, b, c, stmt, ka, kb, kc, end - 1,
        ));
    }
}

#[verifier::spinoff_prover]
#[verifier::rlimit(12)]
pub proof fn lemma_bs_rows_keep(
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    stmt: Seq<Seq<char>>,
    rows: Seq<usize>,
    hashes: Seq<u64>,
    end: int,
)
    requires
        a.len() == b.len(),
        a.len() == c.len(),
        a.len() == stmt.len(),
        0 < end <= a.len(),
        end <= usize::MAX as int,
        stmt[end - 1] == "BS"@,
        rows == filter_match(iota_ids(end), stmt, "BS"@, end),
        hashes.len() == rows.len(),
        forall|j: int|
            0 <= j < rows.len() ==> {
                let r = #[trigger] rows[j] as int;
                &&& 0 <= r < end
                &&& hashes[j] == fx_triple(a[r], b[r], c[r])
                &&& stmt[r] == "BS"@
            },
    ensures
        ({
            let prev = filter_match(iota_ids(end - 1), stmt, "BS"@, end - 1);
            let rows_p = rows.subrange(0, prev.len() as int);
            let hashes_p = hashes.subrange(0, prev.len() as int);
            &&& rows == prev.push((end - 1) as usize)
            &&& rows_p == prev
            &&& hashes_p.len() == rows_p.len()
            &&& forall|j: int|
                0 <= j < rows_p.len() ==> {
                    let r = #[trigger] rows_p[j] as int;
                    &&& 0 <= r < end - 1
                    &&& hashes_p[j] == fx_triple(a[r], b[r], c[r])
                    &&& stmt[r] == "BS"@
                }
        }),
{
    lemma_iota_bounded(end - 1);
    let s = iota_ids(end - 1);
    assert(s.len() as int == end - 1);
    assert((s.len() + 1) as int == end);
    assert(iota_ids(end) == s.push((end - 1) as usize));
    lemma_filter_push(s, stmt, "BS"@, (end - 1) as usize);
    let prev = filter_match(s, stmt, "BS"@, end - 1);
    assert(rows == prev.push((end - 1) as usize));
    lemma_seq_push_len(prev, (end - 1) as usize);
    lemma_push_prefix(prev, (end - 1) as usize);
    let rows_p = rows.subrange(0, prev.len() as int);
    let hashes_p = hashes.subrange(0, prev.len() as int);
    assert(rows_p == prev);
    assert(hashes_p.len() == rows_p.len());
    assert forall|u: int| 0 <= u < s.len() implies (s[u] as int) < end - 1 by {
        assert(s[u] == (u as usize));
    };
    lemma_filter_preserves_bound(s, stmt, "BS"@, end - 1, end - 1);
    assert forall|j: int| 0 <= j < rows_p.len() implies {
        let r = #[trigger] rows_p[j] as int;
        &&& 0 <= r < end - 1
        &&& hashes_p[j] == fx_triple(a[r], b[r], c[r])
        &&& stmt[r] == "BS"@
    } by {
        lemma_seq_push_index_different(prev, (end - 1) as usize, j);
        assert(rows[j] == prev[j]);
        assert(rows_p[j] == rows[j]);
        assert(hashes_p[j] == hashes[j]);
        assert((prev[j] as int) < end - 1);
    };
}

#[verifier::spinoff_prover]
#[verifier::rlimit(8)]
pub proof fn lemma_fx_is_filter3(
    rows: Seq<usize>,
    hashes: Seq<u64>,
    pa: Seq<Seq<char>>,
    pb: Seq<Seq<char>>,
    pc: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    picked: Seq<usize>,
    bucket: Seq<usize>,
)
    requires
        bucket == eq_row_ids(hashes, fx_triple(ka, kb, kc), hashes.len() as int),
        picked == pick_rows(rows, bucket, bucket.len() as int),
    ensures
        fx_kept_picked(rows, hashes, pa, pb, pc, ka, kb, kc) == filter3(
            picked, pa, pb, pc, ka, kb, kc,
        ),
{
    reveal(fx_kept_picked);
}

#[verifier::spinoff_prover]
#[verifier::rlimit(15)]
pub proof fn lemma_bs_picked_step(
    rows: Seq<usize>,
    hashes: Seq<u64>,
    prev: Seq<usize>,
    h: u64,
    hrow: u64,
    end: int,
)
    requires
        0 < end <= usize::MAX as int,
        rows == prev.push((end - 1) as usize),
        hashes.len() == rows.len(),
        prev.len() as int == (hashes.len() as int) - 1,
        hashes[prev.len() as int] == hrow,
        rows[prev.len() as int] == (end - 1) as usize,
    ensures
        ({
            let rows_p = rows.subrange(0, prev.len() as int);
            let hashes_p = hashes.subrange(0, prev.len() as int);
            let old_bucket = eq_row_ids(hashes_p, h, hashes_p.len() as int);
            let new_bucket = eq_row_ids(hashes, h, hashes.len() as int);
            let old_picked = pick_rows(rows_p, old_bucket, old_bucket.len() as int);
            let new_picked = pick_rows(rows, new_bucket, new_bucket.len() as int);
            &&& rows_p == prev
            &&& hrow == h ==> new_picked == old_picked.push((end - 1) as usize)
            &&& hrow != h ==> new_picked == old_picked
        }),
{
    lemma_seq_push_len(prev, (end - 1) as usize);
    lemma_push_prefix(prev, (end - 1) as usize);
    let last = prev.len() as int;
    let rows_p = rows.subrange(0, last);
    let hashes_p = hashes.subrange(0, last);
    assert(rows_p == prev);
    assert((last as usize) as int == last);
    lemma_eq_row_ids_step(hashes, h, last, last as usize);
    lemma_eq_row_ids_on_prefix(hashes, h, last);
    let old_bucket = eq_row_ids(hashes_p, h, hashes_p.len() as int);
    let new_bucket = eq_row_ids(hashes, h, hashes.len() as int);
    assert(eq_row_ids(hashes, h, last) == old_bucket);
    lemma_eq_row_ids_bounded(hashes_p, h, hashes_p.len() as int);
    assert forall|u: int|
        #![trigger old_bucket[u]]
        0 <= u < old_bucket.len()
        implies {
            let p = old_bucket[u];
            &&& 0 <= p < rows.len()
            &&& p < rows_p.len()
            &&& rows[p as int] == rows_p[p as int]
        } by {
        let p = old_bucket[u];
        assert((p as int) < hashes_p.len() as int);
        assert(hashes_p.len() == rows_p.len());
        lemma_seq_push_index_different(prev, (end - 1) as usize, p as int);
        assert(rows[p as int] == prev[p as int]);
        assert(rows_p[p as int] == prev[p as int]);
    };
    lemma_pick_rows_agree(rows, rows_p, old_bucket, old_bucket.len() as int);
    let old_picked = pick_rows(rows_p, old_bucket, old_bucket.len() as int);
    if hrow == h {
        assert(new_bucket == old_bucket.push(last as usize));
        lemma_pick_pos_prefix(rows, old_bucket, last as usize, old_bucket.len() as int);
        assert(pick_rows(rows, new_bucket, old_bucket.len() as int) == old_picked);
        lemma_pick_step(rows, new_bucket, new_bucket.len() as int);
        let new_picked = pick_rows(rows, new_bucket, new_bucket.len() as int);
        assert(rows[last] == (end - 1) as usize);
        assert(new_picked == old_picked.push((end - 1) as usize));
    } else {
        assert(new_bucket == old_bucket);
        assert(pick_rows(rows, new_bucket, new_bucket.len() as int) == old_picked);
    }
}

#[verifier::spinoff_prover]
#[verifier::rlimit(12)]
pub proof fn lemma_bs_keep_close(
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    stmt: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    end: int,
    old_picked: Seq<usize>,
    new_picked: Seq<usize>,
    h: u64,
    hrow: u64,
)
    requires
        a.len() == b.len(),
        a.len() == c.len(),
        a.len() == stmt.len(),
        0 < end <= a.len(),
        end <= usize::MAX as int,
        stmt[end - 1] == "BS"@,
        h == fx_triple(ka, kb, kc),
        hrow == fx_triple(a[end - 1], b[end - 1], c[end - 1]),
        hrow == h ==> new_picked == old_picked.push((end - 1) as usize),
        hrow != h ==> new_picked == old_picked,
        filter3(old_picked, a, b, c, ka, kb, kc) == bs_filtered_eq3(
            a, b, c, stmt, ka, kb, kc, end - 1,
        ),
    ensures
        filter3(new_picked, a, b, c, ka, kb, kc) == bs_filtered_eq3(
            a, b, c, stmt, ka, kb, kc, end,
        ),
{
    reveal(bs_filtered_eq3);
    let old3 = filter3(old_picked, a, b, c, ka, kb, kc);
    if hrow == h {
        assert(new_picked == old_picked.push((end - 1) as usize));
        lemma_filter3_push(old_picked, a, b, c, ka, kb, kc, (end - 1) as usize);
        lemma_eq_row_ids3_step(a, b, c, ka, kb, kc, end - 1, (end - 1) as usize);
        if a[end - 1] == ka && b[end - 1] == kb && c[end - 1] == kc {
            let prev_eq = eq_row_ids3(a, b, c, ka, kb, kc, end - 1);
            assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == prev_eq.push((end - 1) as usize));
            lemma_seq_push_len(prev_eq, (end - 1) as usize);
            lemma_filter_push(prev_eq, stmt, "BS"@, (end - 1) as usize);
            assert(filter3(new_picked, a, b, c, ka, kb, kc) == old3.push((end - 1) as usize));
            assert(bs_filtered_eq3(a, b, c, stmt, ka, kb, kc, end) == old3.push((end - 1) as usize));
        } else {
            assert(filter3(new_picked, a, b, c, ka, kb, kc) == old3);
            assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == eq_row_ids3(
                a, b, c, ka, kb, kc, end - 1,
            ));
            assert(bs_filtered_eq3(a, b, c, stmt, ka, kb, kc, end) == old3);
        }
    } else {
        assert(new_picked == old_picked);
        if a[end - 1] == ka && b[end - 1] == kb && c[end - 1] == kc {
            assert(hrow == h);
            assert(false);
        }
        lemma_eq_row_ids3_step(a, b, c, ka, kb, kc, end - 1, (end - 1) as usize);
        assert(eq_row_ids3(a, b, c, ka, kb, kc, end) == eq_row_ids3(
            a, b, c, ka, kb, kc, end - 1,
        ));
        assert(bs_filtered_eq3(a, b, c, stmt, ka, kb, kc, end) == old3);
        assert(filter3(new_picked, a, b, c, ka, kb, kc) == old3);
    }
}

#[verifier::spinoff_prover]
#[verifier::rlimit(8)]
pub proof fn lemma_bs_pick_keep_step(
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    stmt: Seq<Seq<char>>,
    rows: Seq<usize>,
    hashes: Seq<u64>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    end: int,
)
    requires
        a.len() == b.len(),
        a.len() == c.len(),
        a.len() == stmt.len(),
        0 < end <= a.len(),
        end <= usize::MAX as int,
        stmt[end - 1] == "BS"@,
        rows == filter_match(iota_ids(end), stmt, "BS"@, end),
        hashes.len() == rows.len(),
        forall|j: int|
            0 <= j < rows.len() ==> {
                let r = #[trigger] rows[j] as int;
                &&& 0 <= r < end
                &&& hashes[j] == fx_triple(a[r], b[r], c[r])
                &&& stmt[r] == "BS"@
            },
        fx_kept_picked(
            rows.subrange(
                0,
                filter_match(iota_ids(end - 1), stmt, "BS"@, end - 1).len() as int,
            ),
            hashes.subrange(
                0,
                filter_match(iota_ids(end - 1), stmt, "BS"@, end - 1).len() as int,
            ),
            a,
            b,
            c,
            ka,
            kb,
            kc,
        ) == bs_filtered_eq3(a, b, c, stmt, ka, kb, kc, end - 1),
    ensures
        fx_kept_picked(rows, hashes, a, b, c, ka, kb, kc) == bs_filtered_eq3(
            a, b, c, stmt, ka, kb, kc, end,
        ),
{
    lemma_bs_rows_keep(a, b, c, stmt, rows, hashes, end);
    let prev = filter_match(iota_ids(end - 1), stmt, "BS"@, end - 1);
    assert(rows == prev.push((end - 1) as usize));
    lemma_seq_push_len(prev, (end - 1) as usize);
    let last = prev.len() as int;
    lemma_seq_push_index_same(prev, (end - 1) as usize, last);
    assert(rows[last] == (end - 1) as usize);
    assert(hashes[last] == fx_triple(a[end - 1], b[end - 1], c[end - 1]));
    let h = fx_triple(ka, kb, kc);
    let hrow = hashes[last];
    assert(prev.len() as int == (hashes.len() as int) - 1);
    lemma_bs_picked_step(rows, hashes, prev, h, hrow, end);
    let rows_p = rows.subrange(0, prev.len() as int);
    let hashes_p = hashes.subrange(0, prev.len() as int);
    let old_bucket = eq_row_ids(hashes_p, h, hashes_p.len() as int);
    let new_bucket = eq_row_ids(hashes, h, hashes.len() as int);
    let old_picked = pick_rows(rows_p, old_bucket, old_bucket.len() as int);
    let new_picked = pick_rows(rows, new_bucket, new_bucket.len() as int);
    lemma_fx_is_filter3(rows_p, hashes_p, a, b, c, ka, kb, kc, old_picked, old_bucket);
    lemma_fx_is_filter3(rows, hashes, a, b, c, ka, kb, kc, new_picked, new_bucket);
    assert(filter3(old_picked, a, b, c, ka, kb, kc) == bs_filtered_eq3(
        a, b, c, stmt, ka, kb, kc, end - 1,
    ));
    lemma_bs_keep_close(
        a, b, c, stmt, ka, kb, kc, end, old_picked, new_picked, h, hrow,
    );
    assert(fx_kept_picked(rows, hashes, a, b, c, ka, kb, kc) == filter3(
        new_picked, a, b, c, ka, kb, kc,
    ));
    assert(fx_kept_picked(rows, hashes, a, b, c, ka, kb, kc) == bs_filtered_eq3(
        a, b, c, stmt, ka, kb, kc, end,
    ));
}

/// Compact hash of statement-matching rows, filtered by the three strings, is the
/// three-column match list filtered to that statement.
#[verifier::spinoff_prover]
#[verifier::rlimit(8)]
pub proof fn lemma_bs_pick_is_kept(
    a: Seq<Seq<char>>,
    b: Seq<Seq<char>>,
    c: Seq<Seq<char>>,
    stmt: Seq<Seq<char>>,
    rows: Seq<usize>,
    hashes: Seq<u64>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    end: int,
)
    requires
        a.len() == b.len(),
        a.len() == c.len(),
        a.len() == stmt.len(),
        0 <= end <= a.len(),
        end <= usize::MAX as int,
        rows == filter_match(iota_ids(end), stmt, "BS"@, end),
        hashes.len() == rows.len(),
        forall|j: int|
            0 <= j < rows.len() ==> {
                let r = #[trigger] rows[j] as int;
                &&& 0 <= r < end
                &&& hashes[j] == fx_triple(a[r], b[r], c[r])
                &&& stmt[r] == "BS"@
            },
    ensures
        fx_kept_picked(rows, hashes, a, b, c, ka, kb, kc) == bs_filtered_eq3(
            a, b, c, stmt, ka, kb, kc, end,
        ),
    decreases end,
{
    if end == 0 {
        lemma_bs_pick_base(a, b, c, stmt, rows, hashes, ka, kb, kc);
    } else if stmt[end - 1] != "BS"@ {
        lemma_bs_rows_skip(a, b, c, stmt, rows, hashes, end);
        lemma_bs_pick_is_kept(a, b, c, stmt, rows, hashes, ka, kb, kc, end - 1);
        lemma_bs_filtered_skip(a, b, c, stmt, ka, kb, kc, end);
        assert(fx_kept_picked(rows, hashes, a, b, c, ka, kb, kc) == bs_filtered_eq3(
            a, b, c, stmt, ka, kb, kc, end - 1,
        ));
        assert(fx_kept_picked(rows, hashes, a, b, c, ka, kb, kc) == bs_filtered_eq3(
            a, b, c, stmt, ka, kb, kc, end,
        ));
    } else {
        lemma_bs_rows_keep(a, b, c, stmt, rows, hashes, end);
        let prev = filter_match(iota_ids(end - 1), stmt, "BS"@, end - 1);
        let rows_p = rows.subrange(0, prev.len() as int);
        let hashes_p = hashes.subrange(0, prev.len() as int);
        lemma_bs_pick_is_kept(a, b, c, stmt, rows_p, hashes_p, ka, kb, kc, end - 1);
        lemma_bs_pick_keep_step(a, b, c, stmt, rows, hashes, ka, kb, kc, end);
    }
}

#[verifier::spinoff_prover]
#[verifier::rlimit(8)]
pub proof fn lemma_exec_is_fx_kept(
    out: Seq<usize>,
    rows: Seq<usize>,
    hashes: Seq<u64>,
    pa: Seq<Seq<char>>,
    pt: Seq<Seq<char>>,
    pv: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
    picked: Seq<usize>,
    pre_a: Seq<usize>,
    pre_mid: Seq<usize>,
    bucket: Seq<usize>,
)
    requires
        bucket == eq_row_ids(hashes, fx_triple(ka, kb, kc), hashes.len() as int),
        picked == pick_rows(rows, bucket, bucket.len() as int),
        pre_a == filter_match(picked, pa, ka, picked.len() as int),
        pre_mid == filter_match(pre_a, pt, kb, pre_a.len() as int),
        out == filter_match(pre_mid, pv, kc, pre_mid.len() as int),
    ensures
        out == fx_kept_picked(rows, hashes, pa, pt, pv, ka, kb, kc),
{
    reveal(fx_kept_picked);
    assert(out == fx_kept_picked(rows, hashes, pa, pt, pv, ka, kb, kc));
}

#[verifier::spinoff_prover]
#[verifier::rlimit(8)]
pub proof fn lemma_absent_is_fx_kept(
    out: Seq<usize>,
    rows: Seq<usize>,
    hashes: Seq<u64>,
    pa: Seq<Seq<char>>,
    pt: Seq<Seq<char>>,
    pv: Seq<Seq<char>>,
    ka: Seq<char>,
    kb: Seq<char>,
    kc: Seq<char>,
)
    requires
        eq_row_ids(hashes, fx_triple(ka, kb, kc), hashes.len() as int).len() == 0,
        out.len() == 0,
    ensures
        out == fx_kept_picked(rows, hashes, pa, pt, pv, ka, kb, kc),
{
    reveal(fx_kept_picked);
    let h = fx_triple(ka, kb, kc);
    lemma_eq_row_ids_len0(hashes, h, hashes.len() as int);
    assert(out =~= Seq::<usize>::empty());
    assert(pick_rows(rows, Seq::<usize>::empty(), 0) =~= Seq::<usize>::empty());
    assert(fx_kept_picked(rows, hashes, pa, pt, pv, ka, kb, kc) =~= Seq::<usize>::empty());
}

#[verifier::spinoff_prover]
#[verifier::rlimit(10)]
pub proof fn lemma_bs_view_rows(
    pre_adsh: Seq<String>,
    pre_tag: Seq<String>,
    pre_ver: Seq<String>,
    pre_stmt: Seq<String>,
    rows: Seq<usize>,
    hashes: Seq<u64>,
)
    requires
        pre_adsh.len() == pre_tag.len(),
        pre_adsh.len() == pre_ver.len(),
        pre_adsh.len() == pre_stmt.len(),
        rows == filter_match(
            iota_ids(pre_adsh.len() as int),
            key_views(pre_stmt),
            "BS"@,
            pre_adsh.len() as int,
        ),
        forall|j: int|
            #![trigger rows[j]]
            0 <= j < rows.len() ==> {
                let r = rows[j] as int;
                &&& 0 <= r < pre_adsh.len() as int
                &&& hashes[j] == fx_triple(pre_adsh[r]@, pre_tag[r]@, pre_ver[r]@)
                &&& pre_stmt[r]@ == "BS"@
            },
    ensures
        ({
            let pa = key_views(pre_adsh);
            let pt = key_views(pre_tag);
            let pv = key_views(pre_ver);
            let stt = key_views(pre_stmt);
            &&& rows == filter_match(iota_ids(pa.len() as int), stt, "BS"@, pa.len() as int)
            &&& forall|j: int|
                0 <= j < rows.len() ==> {
                    let r = #[trigger] rows[j] as int;
                    &&& 0 <= r < pa.len()
                    &&& hashes[j] == fx_triple(pa[r], pt[r], pv[r])
                    &&& stt[r] == "BS"@
                }
        }),
{
    let pa = key_views(pre_adsh);
    let pt = key_views(pre_tag);
    let pv = key_views(pre_ver);
    let stt = key_views(pre_stmt);
    assert(pa.len() == pre_adsh.len());
    assert(stt == key_views(pre_stmt));
    assert forall|j: int| 0 <= j < rows.len() implies {
        let r = #[trigger] rows[j] as int;
        &&& 0 <= r < pa.len()
        &&& hashes[j] == fx_triple(pa[r], pt[r], pv[r])
        &&& stt[r] == "BS"@
    } by {
        let r = rows[j] as int;
        lemma_key_view_at(pre_adsh, r);
        lemma_key_view_at(pre_tag, r);
        lemma_key_view_at(pre_ver, r);
        lemma_key_view_at(pre_stmt, r);
        assert(pa[r] == pre_adsh[r]@);
        assert(pt[r] == pre_tag[r]@);
        assert(pv[r] == pre_ver[r]@);
        assert(stt[r] == pre_stmt[r]@);
    };
}

#[verifier::spinoff_prover]
#[verifier::rlimit(8)]
pub proof fn lemma_bs_into_finish(
    pre_adsh: Seq<String>,
    pre_tag: Seq<String>,
    pre_ver: Seq<String>,
    pre_stmt: Seq<String>,
    rows: Seq<usize>,
    hashes: Seq<u64>,
    out: Seq<usize>,
    key_a: Seq<char>,
    key_t: Seq<char>,
    key_v: Seq<char>,
)
    requires
        pre_adsh.len() == pre_tag.len(),
        pre_adsh.len() == pre_ver.len(),
        pre_adsh.len() == pre_stmt.len(),
        rows.len() == hashes.len(),
        rows == filter_match(
            iota_ids(pre_adsh.len() as int),
            key_views(pre_stmt),
            "BS"@,
            pre_adsh.len() as int,
        ),
        forall|j: int|
            #![trigger rows[j]]
            0 <= j < rows.len() ==> {
                let r = rows[j] as int;
                &&& 0 <= r < pre_adsh.len() as int
                &&& hashes[j] == fx_triple(pre_adsh[r]@, pre_tag[r]@, pre_ver[r]@)
                &&& pre_stmt[r]@ == "BS"@
            },
        out == fx_kept_picked(
            rows,
            hashes,
            key_views(pre_adsh),
            key_views(pre_tag),
            key_views(pre_ver),
            key_a,
            key_t,
            key_v,
        ),
    ensures
        out == bs_filtered_eq3(
            key_views(pre_adsh),
            key_views(pre_tag),
            key_views(pre_ver),
            key_views(pre_stmt),
            key_a,
            key_t,
            key_v,
            pre_adsh.len() as int,
        ),
{
    lemma_bs_view_rows(pre_adsh, pre_tag, pre_ver, pre_stmt, rows, hashes);
    let pa = key_views(pre_adsh);
    let pt = key_views(pre_tag);
    let pv = key_views(pre_ver);
    let stt = key_views(pre_stmt);
    lemma_bs_pick_is_kept(pa, pt, pv, stt, rows, hashes, key_a, key_t, key_v, pa.len() as int);
}
pub struct BsPick {
    pub rows: Vec<usize>,
    pub hashes: Vec<u64>,
    pub idx: EqIndexCopy<u64>,
}

pub fn build_bs_pick(
    pre_adsh: &Vec<String>,
    pre_tag: &Vec<String>,
    pre_ver: &Vec<String>,
    pre_stmt: &Vec<String>,
) -> (pick: BsPick)
    requires
        pre_adsh@.len() == pre_tag@.len(),
        pre_adsh@.len() == pre_ver@.len(),
        pre_adsh@.len() == pre_stmt@.len(),
        forall|j: int| 0 <= j < pre_stmt@.len() ==> (pre_stmt@[j]@).len() <= 512,
    ensures
        pick.rows@.len() == pick.hashes@.len(),
        pick.rows@ == filter_match(
            iota_ids(pre_adsh@.len() as int),
            key_views(pre_stmt@),
            "BS"@,
            pre_adsh@.len() as int,
        ),
        forall|j: int|
            0 <= j < pick.rows@.len() ==> {
                let r = #[trigger] pick.rows@[j] as int;
                &&& 0 <= r < pre_adsh@.len()
                &&& pick.hashes@[j] == fx_triple(pre_adsh@[r]@, pre_tag@[r]@, pre_ver@[r]@)
                &&& pre_stmt@[r]@ == "BS"@
            },
        index_ok(
            key_views(pick.hashes@),
            pick.idx.buckets@,
            pick.idx.map@,
            pick.hashes@.len() as int,
        ),
{
    let ghost stt = key_views(pre_stmt@);
    let mut rows: Vec<usize> = Vec::new();
    let mut hashes: Vec<u64> = Vec::new();
    let mut hr: usize = 0;
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(pre_adsh@.len() == pre_adsh.len() as int);
        assert(rows@ =~= Seq::<usize>::empty());
        assert(hashes@ =~= Seq::<u64>::empty());
        assert(iota_ids(0) =~= Seq::<usize>::empty());
        assert(filter_match(iota_ids(0), stt, "BS"@, 0) =~= Seq::<usize>::empty());
    }
    #[verifier::rlimit(20)]
    while hr < pre_adsh.len()
        invariant
            hr <= pre_adsh.len(),
            pre_adsh@.len() == pre_adsh.len() as int,
            pre_tag@.len() == pre_tag.len() as int,
            pre_ver@.len() == pre_ver.len() as int,
            pre_stmt@.len() == pre_stmt.len() as int,
            pre_adsh@.len() == pre_tag@.len(),
            pre_adsh@.len() == pre_ver@.len(),
            pre_adsh@.len() == pre_stmt@.len(),
            stt == key_views(pre_stmt@),
            forall|j: int| 0 <= j < pre_stmt@.len() ==> (pre_stmt@[j]@).len() <= 512,
            rows@.len() == hashes@.len(),
            rows@ == filter_match(iota_ids(hr as int), stt, "BS"@, hr as int),
            forall|j: int|
                0 <= j < rows@.len() ==> {
                    let r = #[trigger] rows@[j] as int;
                    &&& 0 <= r < hr as int
                    &&& hashes@[j] == fx_triple(pre_adsh@[r]@, pre_tag@[r]@, pre_ver@[r]@)
                    &&& pre_stmt@[r]@ == "BS"@
                },
        decreases pre_adsh.len() - hr,
    {
        let a_s = pre_adsh[hr].as_str();
        let t_s = pre_tag[hr].as_str();
        let v_s = pre_ver[hr].as_str();
        let stmt_s = pre_stmt[hr].as_str();
        proof {
            lemma_key_view_at(pre_adsh@, hr as int);
            lemma_key_view_at(pre_tag@, hr as int);
            lemma_key_view_at(pre_ver@, hr as int);
            lemma_key_view_at(pre_stmt@, hr as int);
            assert(a_s@ == pre_adsh@[hr as int]@);
            assert(t_s@ == pre_tag@[hr as int]@);
            assert(v_s@ == pre_ver@[hr as int]@);
            assert(stmt_s@ == pre_stmt@[hr as int]@);
            assert(stmt_s@.len() <= 512);
            assert(stt[hr as int] == pre_stmt@[hr as int]@);
        }
        let is_bs = eq_ascii_lit(stmt_s, "BS");
        if is_bs {
            let hkey = fx_triple_exec(a_s, t_s, v_s);
            let ghost old_rows = rows@;
            let ghost old_h = hashes@;
            rows.push(hr);
            hashes.push(hkey);
            proof {
                assert(is_bs);
                assert(stmt_s@ == "BS"@);
                assert(stt[hr as int] == "BS"@);
                assert(hkey == fx_triple(
                    pre_adsh@[hr as int]@,
                    pre_tag@[hr as int]@,
                    pre_ver@[hr as int]@,
                ));
                lemma_seq_push_len(old_rows, hr);
                lemma_seq_push_len(old_h, hkey);
                lemma_iota_len(hr as int);
                let s = iota_ids(hr as int);
                assert(s.len() as int == hr as int);
                assert((s.len() + 1) as int == (hr + 1) as int);
                assert(iota_ids((hr + 1) as int) == s.push(hr));
                lemma_filter_push(s, stt, "BS"@, hr);
                assert(old_rows == filter_match(s, stt, "BS"@, hr as int));
                assert(rows@ == old_rows.push(hr));
                assert(rows@ == filter_match(iota_ids((hr + 1) as int), stt, "BS"@, (hr + 1) as int));
                assert forall|j: int| 0 <= j < rows@.len() implies {
                    let r = #[trigger] rows@[j] as int;
                    &&& 0 <= r < (hr + 1) as int
                    &&& hashes@[j] == fx_triple(pre_adsh@[r]@, pre_tag@[r]@, pre_ver@[r]@)
                    &&& pre_stmt@[r]@ == "BS"@
                } by {
                    if j < old_rows.len() {
                        lemma_seq_push_index_different(old_rows, hr, j);
                        lemma_seq_push_index_different(old_h, hkey, j);
                        assert(rows@[j] == old_rows[j]);
                        assert(hashes@[j] == old_h[j]);
                    } else {
                        assert(j == old_rows.len());
                        lemma_seq_push_index_same(old_rows, hr, j);
                        lemma_seq_push_index_same(old_h, hkey, j);
                        assert(rows@[j] == hr);
                        assert((rows@[j] as int) == hr as int);
                    }
                };
            }
        } else {
            proof {
                assert(!is_bs);
                assert(stmt_s@ != "BS"@);
                assert(stt[hr as int] != "BS"@);
                lemma_iota_len(hr as int);
                let s = iota_ids(hr as int);
                assert(s.len() as int == hr as int);
                assert((s.len() + 1) as int == (hr + 1) as int);
                assert(iota_ids((hr + 1) as int) == s.push(hr));
                lemma_filter_push(s, stt, "BS"@, hr);
                assert(rows@ == filter_match(s, stt, "BS"@, hr as int));
                assert(rows@ == filter_match(iota_ids((hr + 1) as int), stt, "BS"@, (hr + 1) as int));
            }
        }
        hr = hr + 1;
    }
    let idx = build_eq_index_u64(&hashes);
    proof {
        lemma_u64_hash_key();
        assert(hr == pre_adsh.len());
    }
    BsPick { rows, hashes, idx }
}

#[verifier::rlimit(20)]
pub fn bs_kept_into(
    out: &mut Vec<usize>,
    rows: &Vec<usize>,
    hashes: &Vec<u64>,
    idx: &EqIndexCopy<u64>,
    pre_adsh: &Vec<String>,
    pre_tag: &Vec<String>,
    pre_ver: &Vec<String>,
    pre_stmt: &Vec<String>,
    key_a: &String,
    key_t: &String,
    key_v: &String,
)
    requires
        pre_adsh@.len() == pre_tag@.len(),
        pre_adsh@.len() == pre_ver@.len(),
        pre_adsh@.len() == pre_stmt@.len(),
        rows@.len() == hashes@.len(),
        rows@ == filter_match(
            iota_ids(pre_adsh@.len() as int),
            key_views(pre_stmt@),
            "BS"@,
            pre_adsh@.len() as int,
        ),
        forall|j: int|
            #![trigger rows@[j]]
            0 <= j < rows@.len() ==> {
                let r = rows@[j] as int;
                &&& 0 <= r < pre_adsh@.len() as int
                &&& hashes@[j] == fx_triple(pre_adsh@[r]@, pre_tag@[r]@, pre_ver@[r]@)
                &&& pre_stmt@[r]@ == "BS"@
            },
        index_ok(key_views(hashes@), idx.buckets@, idx.map@, hashes@.len() as int),
        forall|j: int| 0 <= j < pre_stmt@.len() ==> (pre_stmt@[j]@).len() <= 512,
    ensures
        final(out)@ == bs_filtered_eq3(
            key_views(pre_adsh@),
            key_views(pre_tag@),
            key_views(pre_ver@),
            key_views(pre_stmt@),
            key_a@,
            key_t@,
            key_v@,
            pre_adsh@.len() as int,
        ),
{
    let ghost pa = key_views(pre_adsh@);
    let ghost pt = key_views(pre_tag@);
    let ghost pv = key_views(pre_ver@);
    let ghost stt = key_views(pre_stmt@);
    let ghost ph = key_views(hashes@);
    proof {
        lemma_u64_hash_key();
        assert forall|j: int| 0 <= j < ph.len() implies ph[j] == hashes@[j] by {
            lemma_key_view_at(hashes@, j);
            assert(view_is_id(hashes@[j]));
            assert(hashes@[j]@ == hashes@[j]);
        };
        assert(ph.len() == hashes@.len());
        assert(ph =~= hashes@);
    }
    let hq = fx_triple_exec(key_a.as_str(), key_t.as_str(), key_v.as_str());
    proof {
        assert(hq == fx_triple(key_a@, key_t@, key_v@));
        assert(view_is_id(hq));
        assert(hq@ == hq);
        broadcast use axiom_contains_deref_key;
        broadcast use axiom_maps_deref_key_to_value;
    }
    let mut pre_a_ids: Vec<usize> = Vec::new();
    let mut pre_mid: Vec<usize> = Vec::new();
    let present = idx.map.contains_key(&hq);
    let mut picked: Vec<usize> = Vec::new();
    if present {
        let got = idx.map.get(&hq);
        let bi = *got.unwrap();
        proof {
            assert(idx.map@.contains_key(hq));
            lemma_index_bucket(ph, idx.buckets@, idx.map@, ph.len() as int, hq);
            lemma_eq_row_ids_bounded(ph, hq, ph.len() as int);
            assert((bi as int) < idx.buckets@.len());
        }
        let bucket = &idx.buckets[bi];
        proof {
            assert(bucket@ == eq_row_ids(ph, hq, ph.len() as int));
            assert(ph.len() == rows@.len());
        }
        let mut t: usize = 0;
        proof {
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(picked@ =~= Seq::<usize>::empty());
            assert(pick_rows(rows@, bucket@, 0) =~= Seq::<usize>::empty());
        }
        while t < bucket.len()
            invariant
                t <= bucket.len(),
                bucket@.len() == bucket.len() as int,
                bucket@ == eq_row_ids(ph, hq, ph.len() as int),
                ph.len() == rows@.len(),
                forall|j: int|
                    #![trigger rows@[j]]
                    0 <= j < rows@.len() ==> (rows@[j] as int) < pre_adsh@.len() as int,
                forall|u: int|
                    0 <= u < bucket@.len() ==> (#[trigger] bucket@[u] as int) < rows@.len(),
                picked@ == pick_rows(rows@, bucket@, t as int),
                forall|u: int|
                    0 <= u < picked@.len() ==> (#[trigger] picked@[u] as int)
                        < pre_adsh@.len() as int,
            decreases bucket.len() - t,
        {
            let p = bucket[t];
            proof {
                assert(p == bucket@[t as int]);
                assert(0 <= (p as int));
                assert((p as int) < rows@.len());
                assert(rows@[p as int] == rows@[p as int]);
                let r = rows@[p as int] as int;
                assert(0 <= r < pre_adsh@.len() as int);
                lemma_pick_step(rows@, bucket@, (t + 1) as int);
            }
            let ghost old_p = picked@;
            picked.push(rows[p]);
            proof {
                lemma_seq_push_len(old_p, rows@[p as int]);
                assert(picked@ == old_p.push(rows@[p as int]));
                assert(picked@ == pick_rows(rows@, bucket@, (t + 1) as int));
                assert forall|u: int|
                    0 <= u < picked@.len() implies (#[trigger] picked@[u] as int)
                        < pre_adsh@.len() as int by {
                    if u < old_p.len() {
                        lemma_seq_push_index_different(old_p, rows@[p as int], u);
                    } else {
                        lemma_seq_push_index_same(old_p, rows@[p as int], u);
                        assert(picked@[u] == rows@[p as int]);
                    }
                };
            }
            t = t + 1;
        }
        proof {
            assert(picked@ == pick_rows(rows@, bucket@, bucket@.len() as int));
            assert forall|u: int| 0 <= u < picked@.len() implies picked@[u] < pre_tag@.len() by {
                assert((picked@[u] as int) < pre_adsh@.len());
                assert(pre_tag@.len() == pre_adsh@.len());
            };
        }
        filter_row_ids_str_into(&mut pre_a_ids, &picked, pre_adsh, key_a);
        proof {
            assert(pre_a_ids@ == filter_match(picked@, pa, key_a@, picked@.len() as int));
            lemma_filter_preserves_bound(
                picked@, pa, key_a@, picked@.len() as int, pre_adsh@.len() as int,
            );
        }
        filter_row_ids_str_into(&mut pre_mid, &pre_a_ids, pre_tag, key_t);
        proof {
            lemma_filter_preserves_bound(
                pre_a_ids@, pt, key_t@, pre_a_ids@.len() as int, pre_tag@.len() as int,
            );
        }
        filter_row_ids_str_into(out, &pre_mid, pre_ver, key_v);
        proof {
            assert(out@ == filter_match(pre_mid@, pv, key_v@, pre_mid@.len() as int));
            assert(pre_mid@ == filter_match(pre_a_ids@, pt, key_t@, pre_a_ids@.len() as int));
            assert(ph =~= hashes@);
            assert(bucket@ == eq_row_ids(hashes@, fx_triple(key_a@, key_t@, key_v@), hashes@.len() as int));
            lemma_exec_is_fx_kept(
                out@, rows@, hashes@, pa, pt, pv, key_a@, key_t@, key_v@,
                picked@, pre_a_ids@, pre_mid@, bucket@,
            );
        }
    } else {
        out.clear();
        proof {
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(!idx.map@.contains_key(hq));
            lemma_index_absent(ph, idx.buckets@, idx.map@, ph.len() as int, hq);
            lemma_eq_row_ids_len0(ph, hq, ph.len() as int);
            assert(ph =~= hashes@);
            assert(eq_row_ids(hashes@, fx_triple(key_a@, key_t@, key_v@), hashes@.len() as int).len() == 0);
            assert(out@.len() == 0);
            lemma_absent_is_fx_kept(
                out@, rows@, hashes@, pa, pt, pv, key_a@, key_t@, key_v@,
            );
        }
    }
    proof {
        lemma_bs_into_finish(
            pre_adsh@, pre_tag@, pre_ver@, pre_stmt@,
            rows@, hashes@, out@, key_a@, key_t@, key_v@,
        );
    }
}

/// Same join as `q6_eq_triples_str`, keeping only hub rows whose unit is `pure`,
/// mid rows whose year is 2022, and inner rows whose statement is `BS`.
/// The inner index hashes only statement-matching rows; string equality drops collisions.

pub fn q6_eq_triples_kept(
    hub_adsh: &Vec<String>,
    hub_tag: &Vec<String>,
    hub_ver: &Vec<String>,
    sub_adsh: &Vec<String>,
    pre_adsh: &Vec<String>,
    pre_tag: &Vec<String>,
    pre_ver: &Vec<String>,
    hub_uom: &Vec<String>,
    sub_fy: &Vec<u32>,
    pre_stmt: &Vec<String>,
) -> (triples: Vec<(usize, usize, usize)>)
    requires
        hub_adsh@.len() == hub_tag@.len(),
        hub_adsh@.len() == hub_ver@.len(),
        hub_adsh@.len() == hub_uom@.len(),
        pre_adsh@.len() == pre_tag@.len(),
        pre_adsh@.len() == pre_ver@.len(),
        pre_adsh@.len() == pre_stmt@.len(),
        sub_adsh@.len() == sub_fy@.len(),
        forall|j: int| 0 <= j < hub_uom@.len() ==> (hub_uom@[j]@).len() <= 512,
        forall|j: int| 0 <= j < pre_stmt@.len() ==> (pre_stmt@[j]@).len() <= 512,
    ensures
        triples@ == nested_q6_kept(
            key_views(hub_adsh@),
            key_views(hub_tag@),
            key_views(hub_ver@),
            key_views(sub_adsh@),
            key_views(pre_adsh@),
            key_views(pre_tag@),
            key_views(pre_ver@),
            key_views(hub_uom@),
            sub_fy@,
            key_views(pre_stmt@),
            hub_adsh@.len() as int,
        ),
        forall|p: int|
            #![trigger triples@[p]]
            0 <= p < triples@.len() ==> {
                &&& (triples@[p].0 as int) < hub_adsh@.len()
                &&& (triples@[p].1 as int) < sub_adsh@.len()
                &&& (triples@[p].2 as int) < pre_adsh@.len()
            },
{
    let idx_sub = build_eq_index_str(sub_adsh);
    let ghost ha = key_views(hub_adsh@);
    let ghost ht = key_views(hub_tag@);
    let ghost hv = key_views(hub_ver@);
    let ghost sa = key_views(sub_adsh@);
    let ghost pa = key_views(pre_adsh@);
    let ghost pt = key_views(pre_tag@);
    let ghost pv = key_views(pre_ver@);
    let ghost uo = key_views(hub_uom@);
    let ghost stt = key_views(pre_stmt@);
    let bs = build_bs_pick(pre_adsh, pre_tag, pre_ver, pre_stmt);
    proof {
        assert(bs.rows@ == filter_match(
            iota_ids(pre_adsh@.len() as int), stt, "BS"@, pre_adsh@.len() as int,
        ));
    }
    let mut triples: Vec<(usize, usize, usize)> = Vec::new();
    let mut pre_a_ids: Vec<usize> = Vec::new();
    let mut pre_mid: Vec<usize> = Vec::new();
    let mut pres: Vec<usize> = Vec::new();
    let mut kept_sub: Vec<usize> = Vec::new();
    let mut kept_pre: Vec<usize> = Vec::new();
    let empty_sub: Vec<usize> = Vec::new();
    proof {
        assert(empty_sub@ =~= Seq::<usize>::empty());
    }
    let mut i: usize = 0;
    while i < hub_adsh.len()
        invariant
            i <= hub_adsh.len(),
            hub_adsh@.len() == hub_adsh.len() as int,
            hub_adsh@.len() == hub_tag@.len(),
            hub_adsh@.len() == hub_ver@.len(),
            hub_adsh@.len() == hub_uom@.len(),
            hub_uom@.len() == hub_uom.len() as int,
            sub_adsh@.len() == sub_adsh.len() as int,
            sub_adsh@.len() == sub_fy@.len(),
            sub_fy@.len() == sub_fy.len() as int,
            pre_adsh@.len() == pre_adsh.len() as int,
            pre_tag@.len() == pre_tag.len() as int,
            pre_ver@.len() == pre_ver.len() as int,
            pre_stmt@.len() == pre_stmt.len() as int,
            pre_adsh@.len() == pre_tag@.len(),
            pre_adsh@.len() == pre_ver@.len(),
            pre_adsh@.len() == pre_stmt@.len(),
            ha == key_views(hub_adsh@),
            ht == key_views(hub_tag@),
            hv == key_views(hub_ver@),
            sa == key_views(sub_adsh@),
            pa == key_views(pre_adsh@),
            pt == key_views(pre_tag@),
            pv == key_views(pre_ver@),
            uo == key_views(hub_uom@),
            stt == key_views(pre_stmt@),
            index_ok(sa, idx_sub.buckets@, idx_sub.map@, sub_adsh@.len() as int),
            bs.rows@.len() == bs.hashes@.len(),
            bs.rows@ == filter_match(
                iota_ids(pre_adsh@.len() as int), stt, "BS"@, pre_adsh@.len() as int,
            ),
            index_ok(
                key_views(bs.hashes@), bs.idx.buckets@, bs.idx.map@, bs.hashes@.len() as int,
            ),
            forall|j: int|
                0 <= j < bs.rows@.len() ==> {
                    let r = #[trigger] bs.rows@[j] as int;
                    &&& 0 <= r < pa.len()
                    &&& bs.hashes@[j] == fx_triple(pa[r], pt[r], pv[r])
                    &&& stt[r] == "BS"@
                },
            empty_sub@ =~= Seq::<usize>::empty(),
            forall|j: int| 0 <= j < hub_uom@.len() ==> (hub_uom@[j]@).len() <= 512,
            forall|j: int| 0 <= j < pre_stmt@.len() ==> (pre_stmt@[j]@).len() <= 512,
            triples@ == nested_q6_kept(ha, ht, hv, sa, pa, pt, pv, uo, sub_fy@, stt, i as int),
        decreases hub_adsh.len() - i,
    {
        let key_a = &hub_adsh[i];
        let key_t = &hub_tag[i];
        let key_v = &hub_ver[i];
        let ghost end = i as int;
        proof {
            lemma_key_view_at(hub_adsh@, end);
            lemma_key_view_at(hub_tag@, end);
            lemma_key_view_at(hub_ver@, end);
            lemma_key_view_at(hub_uom@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(ha[end] == key_a@);
            assert(ht[end] == key_t@);
            assert(hv[end] == key_v@);
            assert(uo[end] == hub_uom@[end]@);
            assert((hub_uom@[end]@).len() <= 512);
        }
        let uom_s = hub_uom[i].as_str();
        proof {
            assert(uom_s@ == hub_uom@[end]@);
            assert(uom_s@.len() <= 512);
        }
        let uom_ok = eq_ascii_lit(uom_s, "pure");
        if !uom_ok {
            proof {
                assert(uom_s@ != "pure"@);
                assert(uo[end] != "pure"@);
                lemma_nested_q6_kept_step(ha, ht, hv, sa, pa, pt, pv, uo, sub_fy@, stt, end + 1);
                assert(triples@ == nested_q6_kept(
                    ha, ht, hv, sa, pa, pt, pv, uo, sub_fy@, stt, end + 1,
                ));
            }
        } else {
            proof {
                assert(uom_s@ == "pure"@);
                assert(uo[end] == "pure"@);
                assert(sa.len() == sub_adsh@.len());
                assert(pa.len() == pre_adsh@.len());
            }
            let present_a = idx_sub.map.contains_key(key_a.as_str());
            let sub_ids: &Vec<usize>;
            if present_a {
                let got_a = idx_sub.map.get(key_a.as_str());
                let bi_a = *got_a.unwrap();
                proof {
                    assert(idx_sub.map@.contains_key(key_a@));
                    lemma_index_bucket(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                    assert((bi_a as int) < idx_sub.buckets@.len());
                }
                sub_ids = &idx_sub.buckets[bi_a];
                proof {
                    assert(sub_ids@ == idx_sub.buckets@[bi_a as int]@);
                    assert(sub_ids@ == eq_row_ids(sa, ha[end], sa.len() as int));
                }
            } else {
                proof {
                    assert(!idx_sub.map@.contains_key(key_a@));
                    lemma_index_absent(sa, idx_sub.buckets@, idx_sub.map@, sa.len() as int, key_a@);
                    lemma_eq_row_ids_len0(sa, key_a@, sa.len() as int);
                }
                sub_ids = &empty_sub;
                proof {
                    assert(sub_ids@ == empty_sub@);
                    assert(sub_ids@ == eq_row_ids(sa, ha[end], sa.len() as int));
                }
            }
            proof {
                assert(sub_ids@ == eq_row_ids(sa, ha[end], sa.len() as int));
                lemma_eq_row_ids_bounded(sa, ha[end], sa.len() as int);
                assert(sub_fy@.len() == sa.len());
            }
            filter_ids_u32_into(&mut kept_sub, sub_ids, sub_fy, 2022);
            if kept_sub.len() == 0 {
                proof {
                    broadcast use vstd::std_specs::vec::axiom_spec_len;
                    assert(kept_sub@.len() == kept_sub.len() as int);
                    assert(kept_sub@ == ids_u32_eq(
                        sub_ids@, sub_fy@, 2022u32, sub_ids@.len() as int,
                    ));
                    assert(ids_u32_eq(sub_ids@, sub_fy@, 2022u32, sub_ids@.len() as int).len() == 0);
                    assert(sub_product(
                        i,
                        ids_u32_eq(sub_ids@, sub_fy@, 2022u32, sub_ids@.len() as int),
                        filter_match(
                            eq_row_ids3(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int),
                            stt,
                            "BS"@,
                            eq_row_ids3(pa, pt, pv, ha[end], ht[end], hv[end], pa.len() as int).len() as int,
                        ),
                        0,
                    ) =~= Seq::<(usize, usize, usize)>::empty());
                    lemma_nested_q6_kept_step(
                        ha, ht, hv, sa, pa, pt, pv, uo, sub_fy@, stt, end + 1,
                    );
                    assert(triples@ == nested_q6_kept(
                        ha, ht, hv, sa, pa, pt, pv, uo, sub_fy@, stt, end + 1,
                    ));
                }
            } else {
                bs_kept_into(
                    &mut kept_pre,
                    &bs.rows,
                    &bs.hashes,
                    &bs.idx,
                    pre_adsh,
                    pre_tag,
                    pre_ver,
                    pre_stmt,
                    key_a,
                    key_t,
                    key_v,
                );
            let ghost before = triples@;
            push_star_product(&mut triples, i, &kept_sub, &kept_pre);
            proof {
                assert(kept_sub@ == ids_u32_eq(sub_ids@, sub_fy@, 2022u32, sub_ids@.len() as int));
                assert(kept_pre@ == bs_filtered_eq3(
                    pa, pt, pv, stt, ha[end], ht[end], hv[end], pa.len() as int,
                ));
                lemma_nested_q6_kept_step(ha, ht, hv, sa, pa, pt, pv, uo, sub_fy@, stt, end + 1);
                assert(triples@ == before + sub_product(
                    i, kept_sub@, kept_pre@, kept_sub@.len() as int,
                ));
                assert(triples@ == nested_q6_kept(
                    ha, ht, hv, sa, pa, pt, pv, uo, sub_fy@, stt, end + 1,
                ));
            }
        }
        }
        i = i + 1;
    }
    proof {
        assert(i == hub_adsh.len());
        assert(sa.len() <= usize::MAX as nat);
        assert(pa.len() <= usize::MAX as nat);
        lemma_nested_q6_kept_rows_in_range(
            ha, ht, hv, sa, pa, pt, pv, uo, sub_fy@, stt, i as int,
        );
        assert(triples@ == nested_q6_kept(
            ha, ht, hv, sa, pa, pt, pv, uo, sub_fy@, stt, i as int,
        ));
    }
    triples
}

pub open spec fn q6_sub(sub_a: Seq<Seq<char>>, key: Seq<char>, i1: int) -> bool {
    &&& 0 <= i1 < sub_a.len()
    &&& sub_a[i1] == key
}

pub open spec fn q6_pos(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    i0: int,
    i1: int,
    i2: int,
) -> int {
    if !(0 <= i0 < hub_a.len() && i0 < hub_t.len() && i0 < hub_v.len()) {
        nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0).len() as int
    } else {
        let subs = eq_row_ids(sub_a, hub_a[i0], sub_a.len() as int);
        let pres = eq_row_ids3(
            pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], pre_a.len() as int,
        );
        let sr = ids_lt(subs, subs.len() as int, i1);
        let pr = if q6_sub(sub_a, hub_a[i0], i1) {
            ids_lt(pres, pres.len() as int, i2)
        } else {
            0
        };
        nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0).len() as int
            + sr * (pres.len() as int) + pr
    }
}

pub open spec fn loop_acc_q6<A>(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    n0: int,
    n1: int,
    n2: int,
    i0: int,
    i1: int,
    i2: int,
) -> A
    decreases n0 - i0, n1 - i1, n2 - i2,
{
    if i0 < n0 {
        if i1 < n1 {
            if i2 < n2 {
                let tail = loop_acc_q6(
                    hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v,
                    step, base, n0, n1, n2, i0, i1, i2 + 1,
                );
                if hub_a[i0] == sub_a[i1]
                    && hub_a[i0] == pre_a[i2]
                    && hub_t[i0] == pre_t[i2]
                    && hub_v[i0] == pre_v[i2]
                {
                    step(tail, i0, i1, i2)
                } else {
                    tail
                }
            } else {
                loop_acc_q6(
                    hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v,
                    step, base, n0, n1, n2, i0, i1 + 1, 0,
                )
            }
        } else {
            loop_acc_q6(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v,
                step, base, n0, n1, n2, i0 + 1, 0, 0,
            )
        }
    } else {
        base
    }
}

pub proof fn lemma_nested_q6_len_mono(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    n: int,
    m: int,
)
    requires
        0 <= n <= m,
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
    ensures
        nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n).len()
            <= nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, m).len(),
    decreases m - n,
{
    if n < m {
        lemma_nested_q6_len_mono(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n, m - 1);
        let cur = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, m);
        let prev = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, m - 1);
        if m - 1 < hub_a.len() {
            lemma_nested_q6_step(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, m);
            assert(prev.len() <= cur.len());
        } else {
            assert(cur == prev);
        }
    }
}

pub proof fn lemma_nested_q6_index(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    n: int,
    m: int,
    p: int,
)
    requires
        0 <= n <= m,
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
        0 <= p < nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n).len(),
    ensures
        nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, m)[p]
            == nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n)[p],
    decreases m - n,
{
    if n < m {
        let cur = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, m);
        let prev = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, m - 1);
        lemma_nested_q6_len_mono(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n, m - 1);
        if m - 1 >= hub_a.len() {
            assert(cur == prev);
        } else {
            lemma_nested_q6_step(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, m);
            assert(p < prev.len());
            let subs = eq_row_ids(sub_a, hub_a[m - 1], sub_a.len() as int);
            let pres = eq_row_ids3(
                pre_a, pre_t, pre_v, hub_a[m - 1], hub_t[m - 1], hub_v[m - 1],
                pre_a.len() as int,
            );
            let extra = sub_product((m - 1) as usize, subs, pres, subs.len() as int);
            lemma_left_index(prev, extra, p);
        }
        lemma_nested_q6_index(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n, m - 1, p);
    }
}

pub proof fn lemma_nested_q6_past(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    n: int,
)
    requires
        n >= hub_a.len(),
        hub_a.len() == hub_t.len(),
        hub_a.len() == hub_v.len(),
        pre_a.len() == pre_t.len(),
        pre_a.len() == pre_v.len(),
    ensures
        nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n)
            == nested_q6(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, hub_a.len() as int,
            ),
    decreases n - hub_a.len(),
{
    if n > hub_a.len() {
        assert(nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n)
            == nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n - 1));
        lemma_nested_q6_past(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n - 1);
    }
}

pub proof fn lemma_q6_acc<A>(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    n0: int,
    n1: int,
    n2: int,
    i0: int,
    i1: int,
    i2: int,
)
    requires
        hub_a.len() == n0,
        hub_t.len() == n0,
        hub_v.len() == n0,
        sub_a.len() == n1,
        pre_a.len() == n2,
        pre_t.len() == n2,
        pre_v.len() == n2,
        n0 <= usize::MAX as int,
        n1 <= usize::MAX as int,
        n2 <= usize::MAX as int,
        0 <= i0 <= n0,
        0 <= i1 <= n1,
        0 <= i2 <= n2,
    ensures
        loop_acc_q6(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, step, base, n0, n1, n2, i0, i1, i2,
        ) == triple_acc(
            nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n0),
            step,
            base,
            q6_pos(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0, i1, i2),
        ),
    decreases n0 - i0, n1 - i1, n2 - i2,
{
    let triples = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n0);
    let pos = q6_pos(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0, i1, i2);
    if i0 >= n0 {
        lemma_nested_q6_past(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0);
        assert(nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0) == triples);
        assert(pos == triples.len() as int);
    } else if i1 >= n1 {
        lemma_q6_acc(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, i0 + 1, 0, 0,
        );
        let subs = eq_row_ids(sub_a, hub_a[i0], n1);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n2);
        lemma_eq_members(sub_a, hub_a[i0], n1);
        assert forall|p: int| 0 <= p < subs.len() implies (#[trigger] subs[p] as int) < i1 by {
            assert((subs[p] as int) < n1);
            assert(n1 <= i1);
        };
        lemma_ids_lt_all(subs, subs.len() as int, i1);
        lemma_sub_product_len(i0 as usize, subs, pres, subs.len() as int);
        assert((i0 as usize) as int == i0);
        lemma_nested_q6_step(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0 + 1);
        let earlier = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0);
        let through = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0 + 1);
        assert(through.len() == earlier.len() + subs.len() * pres.len());
        if i0 + 1 < n0 {
            let subs2 = eq_row_ids(sub_a, hub_a[i0 + 1], n1);
            let pres2 = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0 + 1], hub_t[i0 + 1], hub_v[i0 + 1], n2);
            lemma_ids_lt_zero(subs2, subs2.len() as int);
            lemma_ids_lt_zero(pres2, pres2.len() as int);
        }
        assert(q6_pos(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0 + 1, 0, 0) == pos);
    } else if i2 >= n2 {
        lemma_q6_acc(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, i0, i1 + 1, 0,
        );
        let subs = eq_row_ids(sub_a, hub_a[i0], n1);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n2);
        if q6_sub(sub_a, hub_a[i0], i1) {
            lemma_eq_rank(sub_a, hub_a[i0], n1, i1);
            lemma_eq3_members(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n2);
            assert forall|p: int| 0 <= p < pres.len() implies (#[trigger] pres[p] as int) < i2 by {
                assert((pres[p] as int) < n2);
                assert(n2 <= i2);
            };
            lemma_ids_lt_all(pres, pres.len() as int, i2);
            lemma_ids_lt_zero(pres, pres.len() as int);
            let sr = ids_lt(subs, subs.len() as int, i1);
            let plen = pres.len() as int;
            vstd::arithmetic::mul::lemma_mul_is_distributive_add_other_way(plen, sr, 1);
            vstd::arithmetic::mul::lemma_mul_basics_4(plen);
            assert((sr + 1) * plen == sr * plen + plen);
        } else {
            lemma_eq_members(sub_a, hub_a[i0], n1);
            assert forall|p: int| 0 <= p < subs.len() implies (#[trigger] subs[p] as int) != i1 by {
                assert(sub_a[(subs[p] as int)] == hub_a[i0]);
            };
            lemma_ids_lt_skip(subs, subs.len() as int, i1);
            lemma_ids_lt_zero(pres, pres.len() as int);
        }
        assert(q6_pos(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0, i1 + 1, 0) == pos);
    } else if hub_a[i0] == sub_a[i1]
        && hub_a[i0] == pre_a[i2]
        && hub_t[i0] == pre_t[i2]
        && hub_v[i0] == pre_v[i2]
    {
        lemma_q6_acc(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, i0, i1, i2 + 1,
        );
        lemma_eq_rank(sub_a, hub_a[i0], n1, i1);
        lemma_eq3_rank(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n2, i2);
        let subs = eq_row_ids(sub_a, hub_a[i0], n1);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n2);
        let sr = ids_lt(subs, subs.len() as int, i1);
        let pr = ids_lt(pres, pres.len() as int, i2);
        let plen = pres.len() as int;
        let i0u = i0 as usize;
        let i1u = i1 as usize;
        let i2u = i2 as usize;
        assert(i0u as int == i0);
        assert(i1u as int == i1);
        assert(i2u as int == i2);
        lemma_sub_product_len(i0u, subs, pres, subs.len() as int);
        let prod = sub_product(i0u, subs, pres, subs.len() as int);
        assert(0 <= sr < subs.len());
        assert(0 <= pr < plen);
        assert(sr * plen + pr < prod.len()) by (nonlinear_arith)
            requires
                0 <= sr < subs.len(),
                0 <= pr < plen,
                prod.len() == subs.len() * pres.len(),
                plen == pres.len() as int,
        {
        }
        lemma_sub_product_at(i0u, subs, pres, subs.len() as int, sr, pr);
        lemma_nested_q6_step(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0 + 1);
        let earlier = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0);
        let through = nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0 + 1);
        assert(through == earlier + prod);
        assert(prod[sr * pres.len() + pr] == (i0u, subs[sr], pres[pr]));
        assert(subs[sr] as int == i1);
        assert(pres[pr] as int == i2);
        assert(subs[sr] == i1u);
        assert(pres[pr] == i2u);
        lemma_right_index(earlier, prod, sr * plen + pr);
        assert(pos == earlier.len() as int + sr * plen + pr);
        assert(sr * plen + pr < prod.len()) by (nonlinear_arith)
            requires
                0 <= sr < subs.len(),
                0 <= pr < plen,
                prod.len() == subs.len() * pres.len(),
                plen == pres.len() as int,
        {
        }
        assert(pos < through.len());
        lemma_nested_q6_len_mono(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0 + 1, n0);
        assert(through.len() <= triples.len());
        assert(pos < triples.len());
        lemma_nested_q6_index(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0 + 1, n0, pos);
        assert(triples[pos] == (i0u, i1u, i2u));
        assert(pos + 1 == q6_pos(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0, i1, i2 + 1));
        assert(loop_acc_q6(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, step, base, n0, n1, n2, i0, i1, i2,
        ) == step(
            loop_acc_q6(
                hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v,
                step, base, n0, n1, n2, i0, i1, i2 + 1,
            ),
            i0,
            i1,
            i2,
        ));
        assert(triple_acc(triples, step, base, pos) == step(
            triple_acc(triples, step, base, pos + 1),
            i0,
            i1,
            i2,
        ));
    } else {
        lemma_q6_acc(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v,
            step, base, n0, n1, n2, i0, i1, i2 + 1,
        );
        let subs = eq_row_ids(sub_a, hub_a[i0], n1);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n2);
        if q6_sub(sub_a, hub_a[i0], i1) {
            lemma_eq3_members(pre_a, pre_t, pre_v, hub_a[i0], hub_t[i0], hub_v[i0], n2);
            assert forall|p: int| 0 <= p < pres.len() implies (#[trigger] pres[p] as int) != i2 by {
                assert(pre_a[(pres[p] as int)] == hub_a[i0]);
                assert(pre_t[(pres[p] as int)] == hub_t[i0]);
                assert(pre_v[(pres[p] as int)] == hub_v[i0]);
            };
            lemma_ids_lt_skip(pres, pres.len() as int, i2);
        }
        assert(pos == q6_pos(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, i0, i1, i2 + 1));
    }
}

/// Origin of the Q6 match list: starting at (0, 0, 0) is position 0.
pub proof fn lemma_q6_pos_origin(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
)
    ensures
        q6_pos(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, 0, 0, 0) == 0,
{
    assert(nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, 0)
        =~= Seq::<(usize, usize, usize)>::empty());
    if hub_a.len() == 0 || hub_t.len() == 0 || hub_v.len() == 0 {
        assert(q6_pos(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, 0, 0, 0) == 0);
    } else {
        let subs = eq_row_ids(sub_a, hub_a[0], sub_a.len() as int);
        let pres = eq_row_ids3(pre_a, pre_t, pre_v, hub_a[0], hub_t[0], hub_v[0], pre_a.len() as int);
        lemma_ids_lt_zero(subs, subs.len() as int);
        lemma_ids_lt_zero(pres, pres.len() as int);
        vstd::arithmetic::mul::lemma_mul_by_zero_is_zero(pres.len() as int);
        assert(q6_pos(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, 0, 0, 0) == 0);
    }
}

/// At the origin indices, ``loop_acc_q6`` equals ``triple_acc`` of the Q6 match list at 0.
pub proof fn lemma_q6_at_origin<A>(
    hub_a: Seq<Seq<char>>,
    hub_t: Seq<Seq<char>>,
    hub_v: Seq<Seq<char>>,
    sub_a: Seq<Seq<char>>,
    pre_a: Seq<Seq<char>>,
    pre_t: Seq<Seq<char>>,
    pre_v: Seq<Seq<char>>,
    step: spec_fn(A, int, int, int) -> A,
    base: A,
    n0: int,
    n1: int,
    n2: int,
)
    requires
        hub_a.len() == n0,
        hub_t.len() == n0,
        hub_v.len() == n0,
        sub_a.len() == n1,
        pre_a.len() == n2,
        pre_t.len() == n2,
        pre_v.len() == n2,
        n0 <= usize::MAX as int,
        n1 <= usize::MAX as int,
        n2 <= usize::MAX as int,
    ensures
        loop_acc_q6(
            hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, step, base, n0, n1, n2, 0, 0, 0,
        ) == triple_acc(
            nested_q6(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, n0),
            step,
            base,
            0,
        ),
{
    lemma_q6_acc(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v, step, base, n0, n1, n2, 0, 0, 0);
    lemma_q6_pos_origin(hub_a, hub_t, hub_v, sub_a, pre_a, pre_t, pre_v);
}
// SHAPE_Q6_END

// SHAPE_ANTI2_BEGIN
// Two-key ANTI / LEFT-anti miss list (String∧String). Miss when eq_row_ids2 is empty.

pub proof fn lemma_eq_row_ids2_empty_from_first<A, B>(
    a: Seq<A>,
    b: Seq<B>,
    ka: A,
    kb: B,
    end: int,
)
    requires
        0 <= end <= a.len(),
        a.len() == b.len(),
        end <= usize::MAX as int,
        eq_row_ids(a, ka, end).len() == 0,
    ensures
        eq_row_ids2(a, b, ka, kb, end).len() == 0,
{
    lemma_filter_is_ids2(a, b, ka, kb, end);
    assert(eq_row_ids2(a, b, ka, kb, end) == filter_match(
        eq_row_ids(a, ka, end),
        b,
        kb,
        eq_row_ids(a, ka, end).len() as int,
    ));
    assert(eq_row_ids2(a, b, ka, kb, end).len() == 0);
}

pub proof fn lemma_eq_row_ids2_nonempty_iff<A, B>(
    a: Seq<A>,
    b: Seq<B>,
    ka: A,
    kb: B,
    end: int,
)
    requires
        0 <= end <= a.len(),
        a.len() == b.len(),
        end <= usize::MAX as int,
    ensures
        (eq_row_ids2(a, b, ka, kb, end).len() > 0) <==> (exists|j: int|
            0 <= j < end && a[j] == ka && b[j] == kb),
    decreases end,
{
    if end > 0 {
        lemma_eq_row_ids2_nonempty_iff(a, b, ka, kb, end - 1);
        let row = (end - 1) as usize;
        lemma_eq_row_ids2_step(a, b, ka, kb, end - 1, row);
        if a[end - 1] == ka && b[end - 1] == kb {
            assert(eq_row_ids2(a, b, ka, kb, end).len() > 0);
            assert(exists|j: int| 0 <= j < end && a[j] == ka && b[j] == kb) by {
                assert(0 <= end - 1 < end && a[end - 1] == ka && b[end - 1] == kb);
            };
        } else {
            assert(eq_row_ids2(a, b, ka, kb, end) == eq_row_ids2(a, b, ka, kb, end - 1));
            assert((eq_row_ids2(a, b, ka, kb, end).len() > 0) <==> (exists|j: int|
                0 <= j < end - 1 && a[j] == ka && b[j] == kb));
            assert((exists|j: int| 0 <= j < end && a[j] == ka && b[j] == kb)
                <==> (exists|j: int|
                0 <= j < end - 1 && a[j] == ka && b[j] == kb)) by {
                if exists|j: int| 0 <= j < end && a[j] == ka && b[j] == kb {
                    let j = choose|j: int| 0 <= j < end && a[j] == ka && b[j] == kb;
                    if j == end - 1 {
                        assert(a[end - 1] == ka && b[end - 1] == kb);
                        assert(false);
                    } else {
                        assert(0 <= j < end - 1 && a[j] == ka && b[j] == kb);
                    }
                }
            };
        }
    } else {
        assert(eq_row_ids2(a, b, ka, kb, 0).len() == 0);
        assert(!(exists|j: int| 0 <= j < 0 && a[j] == ka && b[j] == kb));
    }
}

/// Outer row ids in `0..n` with no two-column match, increasing.
pub open spec fn nested_anti_misses2<A, B>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    n: int,
) -> Seq<usize>
    decreases n,
{
    if n <= 0 {
        Seq::<usize>::empty()
    } else if n - 1 >= oa.len() || n - 1 >= ob.len() {
        nested_anti_misses2(oa, ob, ia, ib, n - 1)
    } else {
        let prev = nested_anti_misses2(oa, ob, ia, ib, n - 1);
        if eq_row_ids2(ia, ib, oa[n - 1], ob[n - 1], ia.len() as int).len() == 0 {
            prev.push((n - 1) as usize)
        } else {
            prev
        }
    }
}

pub proof fn lemma_nested_anti_misses2_step<A, B>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    n: int,
)
    requires
        0 < n <= oa.len(),
        n <= ob.len(),
    ensures
        eq_row_ids2(ia, ib, oa[n - 1], ob[n - 1], ia.len() as int).len()
            == 0 ==> nested_anti_misses2(oa, ob, ia, ib, n)
            == nested_anti_misses2(oa, ob, ia, ib, n - 1).push((n - 1) as usize),
        eq_row_ids2(ia, ib, oa[n - 1], ob[n - 1], ia.len() as int).len()
            > 0 ==> nested_anti_misses2(oa, ob, ia, ib, n)
            == nested_anti_misses2(oa, ob, ia, ib, n - 1),
{
    if eq_row_ids2(ia, ib, oa[n - 1], ob[n - 1], ia.len() as int).len() == 0 {
        assert(nested_anti_misses2(oa, ob, ia, ib, n)
            == nested_anti_misses2(oa, ob, ia, ib, n - 1).push((n - 1) as usize));
    } else {
        assert(nested_anti_misses2(oa, ob, ia, ib, n)
            == nested_anti_misses2(oa, ob, ia, ib, n - 1));
    }
}

pub open spec fn anti_loop_acc2<A, B, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
    i: int,
) -> Acc
    decreases n_outer - i,
{
    if i < n_outer {
        let tail = anti_loop_acc2(oa, ob, ia, ib, step, base, n_outer, i + 1);
        if 0 <= i < oa.len() && i < ob.len() && eq_row_ids2(
            ia,
            ib,
            oa[i],
            ob[i],
            ia.len() as int,
        ).len() == 0 {
            step(tail, i)
        } else {
            tail
        }
    } else {
        base
    }
}

pub proof fn lemma_anti_miss2_prefix<A, B>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    a: int,
    b: int,
)
    requires
        0 <= a <= b <= oa.len(),
        b <= ob.len(),
        b <= usize::MAX as int,
    ensures
        nested_anti_misses2(oa, ob, ia, ib, a).len()
            <= nested_anti_misses2(oa, ob, ia, ib, b).len(),
        forall|p: int|
            0 <= p < nested_anti_misses2(oa, ob, ia, ib, a).len() ==> (
                #[trigger] nested_anti_misses2(oa, ob, ia, ib, b)[p]
            ) == nested_anti_misses2(oa, ob, ia, ib, a)[p],
    decreases b - a,
{
    if a < b {
        lemma_anti_miss2_prefix(oa, ob, ia, ib, a, b - 1);
        lemma_nested_anti_misses2_step(oa, ob, ia, ib, b);
        let at_a = nested_anti_misses2(oa, ob, ia, ib, a);
        let at_prev = nested_anti_misses2(oa, ob, ia, ib, b - 1);
        let at_b = nested_anti_misses2(oa, ob, ia, ib, b);
        let ids = eq_row_ids2(ia, ib, oa[b - 1], ob[b - 1], ia.len() as int);
        if ids.len() == 0 {
            assert(at_b == at_prev.push((b - 1) as usize));
            assert(at_a.len() <= at_prev.len());
            assert(at_a.len() <= at_b.len());
            assert forall|p: int| 0 <= p < at_a.len() implies at_b[p] == at_a[p] by {
                lemma_seq_push_index_different(at_prev, (b - 1) as usize, p);
                assert(at_b[p] == at_prev[p]);
                assert(at_prev[p] == at_a[p]);
            };
        } else {
            assert(at_b == at_prev);
        }
    }
}

pub proof fn lemma_anti_miss2_at<A, B>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    n: int,
    i: int,
)
    requires
        0 <= i < n <= oa.len(),
        n <= ob.len(),
        n <= usize::MAX as int,
        eq_row_ids2(ia, ib, oa[i], ob[i], ia.len() as int).len() == 0,
    ensures
        (nested_anti_misses2(oa, ob, ia, ib, i).len() as int)
            < nested_anti_misses2(oa, ob, ia, ib, n).len(),
        nested_anti_misses2(oa, ob, ia, ib, n)[
            nested_anti_misses2(oa, ob, ia, ib, i).len() as int
        ] == i as usize,
{
    lemma_nested_anti_misses2_step(oa, ob, ia, ib, i + 1);
    assert(nested_anti_misses2(oa, ob, ia, ib, i + 1)
        == nested_anti_misses2(oa, ob, ia, ib, i).push(i as usize));
    lemma_anti_miss2_prefix(oa, ob, ia, ib, i + 1, n);
    let k = nested_anti_misses2(oa, ob, ia, ib, i).len() as int;
    assert(nested_anti_misses2(oa, ob, ia, ib, i + 1)[k] == i as usize);
    assert(nested_anti_misses2(oa, ob, ia, ib, n)[k]
        == nested_anti_misses2(oa, ob, ia, ib, i + 1)[k]);
}

pub proof fn lemma_anti_acc2<A, B, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
    i: int,
)
    requires
        oa.len() == n_outer,
        ob.len() == n_outer,
        n_outer <= usize::MAX as int,
        0 <= i <= n_outer,
    ensures
        anti_loop_acc2(oa, ob, ia, ib, step, base, n_outer, i) == miss_acc(
            nested_anti_misses2(oa, ob, ia, ib, n_outer),
            step,
            base,
            nested_anti_misses2(oa, ob, ia, ib, i).len() as int,
        ),
    decreases n_outer - i,
{
    if i < n_outer {
        lemma_anti_acc2(oa, ob, ia, ib, step, base, n_outer, i + 1);
        lemma_nested_anti_misses2_step(oa, ob, ia, ib, i + 1);
        let misses = nested_anti_misses2(oa, ob, ia, ib, n_outer);
        let k_i = nested_anti_misses2(oa, ob, ia, ib, i).len() as int;
        let ids = eq_row_ids2(ia, ib, oa[i], ob[i], ia.len() as int);
        if ids.len() == 0 {
            lemma_anti_miss2_at(oa, ob, ia, ib, n_outer, i);
            assert(misses[k_i] == i as usize);
            assert(0 <= k_i < misses.len());
            assert(anti_loop_acc2(oa, ob, ia, ib, step, base, n_outer, i) == step(
                anti_loop_acc2(oa, ob, ia, ib, step, base, n_outer, i + 1),
                i,
            ));
            assert(miss_acc(misses, step, base, k_i) == step(
                miss_acc(misses, step, base, k_i + 1),
                misses[k_i] as int,
            ));
        } else {
            assert(nested_anti_misses2(oa, ob, ia, ib, i + 1)
                == nested_anti_misses2(oa, ob, ia, ib, i));
        }
    }
}

pub proof fn lemma_anti2_at_origin<A, B, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
)
    requires
        oa.len() == n_outer,
        ob.len() == n_outer,
        n_outer <= usize::MAX as int,
    ensures
        anti_loop_acc2(oa, ob, ia, ib, step, base, n_outer, 0) == miss_acc(
            nested_anti_misses2(oa, ob, ia, ib, n_outer),
            step,
            base,
            0,
        ),
{
    assert(nested_anti_misses2(oa, ob, ia, ib, 0) =~= Seq::<usize>::empty());
    lemma_anti_acc2(oa, ob, ia, ib, step, base, n_outer, 0);
}

/// Two-key ANTI/LEFT-anti miss ids. View equals [`nested_anti_misses2`].
pub fn anti_miss_rows_str2(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
) -> (misses: Vec<usize>)
    requires
        outer0@.len() == outer1@.len(),
        inner0@.len() == inner1@.len(),
    ensures
        misses@ == nested_anti_misses2(
            key_views(outer0@),
            key_views(outer1@),
            key_views(inner0@),
            key_views(inner1@),
            outer0@.len() as int,
        ),
{
    let idx = build_eq_index_str(inner0);
    let ghost oa = key_views(outer0@);
    let ghost ob = key_views(outer1@);
    let ghost ia = key_views(inner0@);
    let ghost ib = key_views(inner1@);
    let mut misses: Vec<usize> = Vec::new();
    let mut i: usize = 0;
    while i < outer0.len()
        invariant
            i <= outer0.len(),
            outer0@.len() == outer0.len() as int,
            outer1@.len() == outer0@.len(),
            inner0@.len() == inner0.len() as int,
            inner1@.len() == inner0@.len(),
            oa == key_views(outer0@),
            ob == key_views(outer1@),
            ia == key_views(inner0@),
            ib == key_views(inner1@),
            index_ok(ia, idx.buckets@, idx.map@, inner0@.len() as int),
            misses@ == nested_anti_misses2(oa, ob, ia, ib, i as int),
        decreases outer0.len() - i,
    {
        let key0 = outer0[i].clone();
        let key1 = outer1[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer0@, end);
            lemma_key_view_at(outer1@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(oa[end] == key0@);
            assert(ob[end] == key1@);
            assert(ia.len() as int <= usize::MAX as int);
        }
        let ghost before = misses@;
        let present = idx.map.contains_key(key0.as_str());
        if present {
            let got = idx.map.get(key0.as_str());
            let bi = *got.unwrap();
            proof {
                assert(idx.map@.contains_key(key0@));
                lemma_index_bucket(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_bounded(ia, key0@, ia.len() as int);
            }
            let ids = &idx.buckets[bi];
            let filtered2 = filter_row_ids_str(ids, inner1, &key1);
            if filtered2.len() == 0 {
                misses.push(i);
                proof {
                    lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                    assert(filtered2@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                    assert(eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int).len() == 0);
                    lemma_nested_anti_misses2_step(oa, ob, ia, ib, end + 1);
                    assert(misses@ == before.push(i));
                    assert(misses@ == nested_anti_misses2(oa, ob, ia, ib, end + 1));
                }
            } else {
                proof {
                    lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                    assert(filtered2@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                    assert(eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int).len() > 0);
                    lemma_nested_anti_misses2_step(oa, ob, ia, ib, end + 1);
                    assert(misses@ == nested_anti_misses2(oa, ob, ia, ib, end + 1));
                }
            }
        } else {
            misses.push(i);
            proof {
                assert(!idx.map@.contains_key(key0@));
                lemma_index_absent(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_len0(ia, key0@, ia.len() as int);
                lemma_eq_row_ids2_empty_from_first(ia, ib, key0@, key1@, ia.len() as int);
                lemma_nested_anti_misses2_step(oa, ob, ia, ib, end + 1);
                assert(misses@ == before.push(i));
                assert(misses@ == nested_anti_misses2(oa, ob, ia, ib, end + 1));
            }
        }
        i = i + 1;
    }
    misses
}
// SHAPE_ANTI2_END

// SHAPE_SEMI2_BEGIN
// Two-key SEMI hit list (String∧String). Hit when eq_row_ids2 is nonempty.

/// Outer row ids in `0..n` with a two-column match, increasing.
pub open spec fn nested_semi_hits2<A, B>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    n: int,
) -> Seq<usize>
    decreases n,
{
    if n <= 0 {
        Seq::<usize>::empty()
    } else if n - 1 >= oa.len() || n - 1 >= ob.len() {
        nested_semi_hits2(oa, ob, ia, ib, n - 1)
    } else {
        let prev = nested_semi_hits2(oa, ob, ia, ib, n - 1);
        if eq_row_ids2(ia, ib, oa[n - 1], ob[n - 1], ia.len() as int).len() > 0 {
            prev.push((n - 1) as usize)
        } else {
            prev
        }
    }
}

pub proof fn lemma_nested_semi_hits2_step<A, B>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    n: int,
)
    requires
        0 < n <= oa.len(),
        n <= ob.len(),
    ensures
        eq_row_ids2(ia, ib, oa[n - 1], ob[n - 1], ia.len() as int).len()
            > 0 ==> nested_semi_hits2(oa, ob, ia, ib, n)
            == nested_semi_hits2(oa, ob, ia, ib, n - 1).push((n - 1) as usize),
        eq_row_ids2(ia, ib, oa[n - 1], ob[n - 1], ia.len() as int).len()
            == 0 ==> nested_semi_hits2(oa, ob, ia, ib, n)
            == nested_semi_hits2(oa, ob, ia, ib, n - 1),
{
    if eq_row_ids2(ia, ib, oa[n - 1], ob[n - 1], ia.len() as int).len() > 0 {
        assert(nested_semi_hits2(oa, ob, ia, ib, n)
            == nested_semi_hits2(oa, ob, ia, ib, n - 1).push((n - 1) as usize));
    } else {
        assert(nested_semi_hits2(oa, ob, ia, ib, n)
            == nested_semi_hits2(oa, ob, ia, ib, n - 1));
    }
}

pub open spec fn semi_loop_acc2<A, B, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
    i: int,
) -> Acc
    decreases n_outer - i,
{
    if i < n_outer {
        let tail = semi_loop_acc2(oa, ob, ia, ib, step, base, n_outer, i + 1);
        if 0 <= i < oa.len() && i < ob.len() && eq_row_ids2(
            ia,
            ib,
            oa[i],
            ob[i],
            ia.len() as int,
        ).len() > 0 {
            step(tail, i)
        } else {
            tail
        }
    } else {
        base
    }
}

pub proof fn lemma_semi_hit2_prefix<A, B>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    a: int,
    b: int,
)
    requires
        0 <= a <= b <= oa.len(),
        b <= ob.len(),
        b <= usize::MAX as int,
    ensures
        nested_semi_hits2(oa, ob, ia, ib, a).len()
            <= nested_semi_hits2(oa, ob, ia, ib, b).len(),
        forall|p: int|
            0 <= p < nested_semi_hits2(oa, ob, ia, ib, a).len() ==> (
                #[trigger] nested_semi_hits2(oa, ob, ia, ib, b)[p]
            ) == nested_semi_hits2(oa, ob, ia, ib, a)[p],
    decreases b - a,
{
    if a < b {
        lemma_semi_hit2_prefix(oa, ob, ia, ib, a, b - 1);
        lemma_nested_semi_hits2_step(oa, ob, ia, ib, b);
        let at_a = nested_semi_hits2(oa, ob, ia, ib, a);
        let at_prev = nested_semi_hits2(oa, ob, ia, ib, b - 1);
        let at_b = nested_semi_hits2(oa, ob, ia, ib, b);
        let ids = eq_row_ids2(ia, ib, oa[b - 1], ob[b - 1], ia.len() as int);
        if ids.len() > 0 {
            assert(at_b == at_prev.push((b - 1) as usize));
            assert(at_a.len() <= at_prev.len());
            assert(at_a.len() <= at_b.len());
            assert forall|p: int| 0 <= p < at_a.len() implies at_b[p] == at_a[p] by {
                lemma_seq_push_index_different(at_prev, (b - 1) as usize, p);
                assert(at_b[p] == at_prev[p]);
                assert(at_prev[p] == at_a[p]);
            };
        } else {
            assert(at_b == at_prev);
        }
    }
}

pub proof fn lemma_semi_hit2_at<A, B>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    n: int,
    i: int,
)
    requires
        0 <= i < n <= oa.len(),
        n <= ob.len(),
        n <= usize::MAX as int,
        eq_row_ids2(ia, ib, oa[i], ob[i], ia.len() as int).len() > 0,
    ensures
        (nested_semi_hits2(oa, ob, ia, ib, i).len() as int)
            < nested_semi_hits2(oa, ob, ia, ib, n).len(),
        nested_semi_hits2(oa, ob, ia, ib, n)[
            nested_semi_hits2(oa, ob, ia, ib, i).len() as int
        ] == i as usize,
{
    lemma_nested_semi_hits2_step(oa, ob, ia, ib, i + 1);
    assert(nested_semi_hits2(oa, ob, ia, ib, i + 1)
        == nested_semi_hits2(oa, ob, ia, ib, i).push(i as usize));
    lemma_semi_hit2_prefix(oa, ob, ia, ib, i + 1, n);
    let k = nested_semi_hits2(oa, ob, ia, ib, i).len() as int;
    assert(nested_semi_hits2(oa, ob, ia, ib, i + 1)[k] == i as usize);
    assert(nested_semi_hits2(oa, ob, ia, ib, n)[k]
        == nested_semi_hits2(oa, ob, ia, ib, i + 1)[k]);
}

pub proof fn lemma_semi_acc2<A, B, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
    i: int,
)
    requires
        oa.len() == n_outer,
        ob.len() == n_outer,
        n_outer <= usize::MAX as int,
        0 <= i <= n_outer,
    ensures
        semi_loop_acc2(oa, ob, ia, ib, step, base, n_outer, i) == hit_acc(
            nested_semi_hits2(oa, ob, ia, ib, n_outer),
            step,
            base,
            nested_semi_hits2(oa, ob, ia, ib, i).len() as int,
        ),
    decreases n_outer - i,
{
    if i < n_outer {
        lemma_semi_acc2(oa, ob, ia, ib, step, base, n_outer, i + 1);
        lemma_nested_semi_hits2_step(oa, ob, ia, ib, i + 1);
        let hits = nested_semi_hits2(oa, ob, ia, ib, n_outer);
        let k_i = nested_semi_hits2(oa, ob, ia, ib, i).len() as int;
        let ids = eq_row_ids2(ia, ib, oa[i], ob[i], ia.len() as int);
        if ids.len() > 0 {
            lemma_semi_hit2_at(oa, ob, ia, ib, n_outer, i);
            assert(hits[k_i] == i as usize);
            assert(0 <= k_i < hits.len());
            assert(semi_loop_acc2(oa, ob, ia, ib, step, base, n_outer, i) == step(
                semi_loop_acc2(oa, ob, ia, ib, step, base, n_outer, i + 1),
                i,
            ));
            assert(hit_acc(hits, step, base, k_i) == step(
                hit_acc(hits, step, base, k_i + 1),
                hits[k_i] as int,
            ));
        } else {
            assert(nested_semi_hits2(oa, ob, ia, ib, i + 1)
                == nested_semi_hits2(oa, ob, ia, ib, i));
        }
    }
}

pub proof fn lemma_semi2_at_origin<A, B, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    ia: Seq<A>,
    ib: Seq<B>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
)
    requires
        oa.len() == n_outer,
        ob.len() == n_outer,
        n_outer <= usize::MAX as int,
    ensures
        semi_loop_acc2(oa, ob, ia, ib, step, base, n_outer, 0) == hit_acc(
            nested_semi_hits2(oa, ob, ia, ib, n_outer),
            step,
            base,
            0,
        ),
{
    assert(nested_semi_hits2(oa, ob, ia, ib, 0) =~= Seq::<usize>::empty());
    lemma_semi_acc2(oa, ob, ia, ib, step, base, n_outer, 0);
}

/// Two-key SEMI hit ids. View equals [`nested_semi_hits2`].
pub fn semi_hit_rows_str2(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
) -> (hits: Vec<usize>)
    requires
        outer0@.len() == outer1@.len(),
        inner0@.len() == inner1@.len(),
    ensures
        hits@ == nested_semi_hits2(
            key_views(outer0@),
            key_views(outer1@),
            key_views(inner0@),
            key_views(inner1@),
            outer0@.len() as int,
        ),
{
    let idx = build_eq_index_str(inner0);
    let ghost oa = key_views(outer0@);
    let ghost ob = key_views(outer1@);
    let ghost ia = key_views(inner0@);
    let ghost ib = key_views(inner1@);
    let mut hits: Vec<usize> = Vec::new();
    let mut i: usize = 0;
    while i < outer0.len()
        invariant
            i <= outer0.len(),
            outer0@.len() == outer0.len() as int,
            outer1@.len() == outer0@.len(),
            inner0@.len() == inner0.len() as int,
            inner1@.len() == inner0@.len(),
            oa == key_views(outer0@),
            ob == key_views(outer1@),
            ia == key_views(inner0@),
            ib == key_views(inner1@),
            index_ok(ia, idx.buckets@, idx.map@, inner0@.len() as int),
            hits@ == nested_semi_hits2(oa, ob, ia, ib, i as int),
        decreases outer0.len() - i,
    {
        let key0 = outer0[i].clone();
        let key1 = outer1[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer0@, end);
            lemma_key_view_at(outer1@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(oa[end] == key0@);
            assert(ob[end] == key1@);
            assert(ia.len() as int <= usize::MAX as int);
        }
        let ghost before = hits@;
        let present = idx.map.contains_key(key0.as_str());
        if present {
            let got = idx.map.get(key0.as_str());
            let bi = *got.unwrap();
            proof {
                assert(idx.map@.contains_key(key0@));
                lemma_index_bucket(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_bounded(ia, key0@, ia.len() as int);
            }
            let ids = &idx.buckets[bi];
            let filtered2 = filter_row_ids_str(ids, inner1, &key1);
            if filtered2.len() == 0 {
                proof {
                    lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                    assert(filtered2@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                    assert(eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int).len() == 0);
                    lemma_nested_semi_hits2_step(oa, ob, ia, ib, end + 1);
                    assert(hits@ == nested_semi_hits2(oa, ob, ia, ib, end + 1));
                }
            } else {
                hits.push(i);
                proof {
                    lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                    assert(filtered2@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                    assert(eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int).len() > 0);
                    lemma_nested_semi_hits2_step(oa, ob, ia, ib, end + 1);
                    assert(hits@ == before.push(i));
                    assert(hits@ == nested_semi_hits2(oa, ob, ia, ib, end + 1));
                }
            }
        } else {
            proof {
                assert(!idx.map@.contains_key(key0@));
                lemma_index_absent(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_len0(ia, key0@, ia.len() as int);
                lemma_eq_row_ids2_empty_from_first(ia, ib, key0@, key1@, ia.len() as int);
                lemma_nested_semi_hits2_step(oa, ob, ia, ib, end + 1);
                assert(hits@ == nested_semi_hits2(oa, ob, ia, ib, end + 1));
            }
        }
        i = i + 1;
    }
    hits
}
// SHAPE_SEMI2_END

// SHAPE_SEMI3_BEGIN
// Three-key SEMI hit list. Hit when eq_row_ids3 is nonempty. Reuses filter/index
// helpers from SHAPE_LEFT3; no second anti exec.

/// Outer row ids in `0..n` with a three-column match, increasing.
pub open spec fn nested_semi_hits3<A, B, C>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    n: int,
) -> Seq<usize>
    decreases n,
{
    if n <= 0 {
        Seq::<usize>::empty()
    } else if n - 1 >= oa.len() || n - 1 >= ob.len() || n - 1 >= oc.len() {
        nested_semi_hits3(oa, ob, oc, ia, ib, ic, n - 1)
    } else {
        let prev = nested_semi_hits3(oa, ob, oc, ia, ib, ic, n - 1);
        if eq_row_ids3(ia, ib, ic, oa[n - 1], ob[n - 1], oc[n - 1], ia.len() as int).len() > 0 {
            prev.push((n - 1) as usize)
        } else {
            prev
        }
    }
}

pub proof fn lemma_nested_semi_hits3_step<A, B, C>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    n: int,
)
    requires
        0 < n <= oa.len(),
        n <= ob.len(),
        n <= oc.len(),
    ensures
        eq_row_ids3(ia, ib, ic, oa[n - 1], ob[n - 1], oc[n - 1], ia.len() as int).len()
            > 0 ==> nested_semi_hits3(oa, ob, oc, ia, ib, ic, n)
            == nested_semi_hits3(oa, ob, oc, ia, ib, ic, n - 1).push((n - 1) as usize),
        eq_row_ids3(ia, ib, ic, oa[n - 1], ob[n - 1], oc[n - 1], ia.len() as int).len()
            == 0 ==> nested_semi_hits3(oa, ob, oc, ia, ib, ic, n)
            == nested_semi_hits3(oa, ob, oc, ia, ib, ic, n - 1),
{
    if eq_row_ids3(ia, ib, ic, oa[n - 1], ob[n - 1], oc[n - 1], ia.len() as int).len() > 0 {
        assert(nested_semi_hits3(oa, ob, oc, ia, ib, ic, n)
            == nested_semi_hits3(oa, ob, oc, ia, ib, ic, n - 1).push((n - 1) as usize));
    } else {
        assert(nested_semi_hits3(oa, ob, oc, ia, ib, ic, n)
            == nested_semi_hits3(oa, ob, oc, ia, ib, ic, n - 1));
    }
}

pub open spec fn semi_loop_acc3<A, B, C, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
    i: int,
) -> Acc
    decreases n_outer - i,
{
    if i < n_outer {
        let tail = semi_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i + 1);
        if 0 <= i < oa.len() && i < ob.len() && i < oc.len() && eq_row_ids3(
            ia,
            ib,
            ic,
            oa[i],
            ob[i],
            oc[i],
            ia.len() as int,
        ).len() > 0 {
            step(tail, i)
        } else {
            tail
        }
    } else {
        base
    }
}

pub proof fn lemma_semi_hit3_prefix<A, B, C>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    a: int,
    b: int,
)
    requires
        0 <= a <= b <= oa.len(),
        b <= ob.len(),
        b <= oc.len(),
        b <= usize::MAX as int,
    ensures
        nested_semi_hits3(oa, ob, oc, ia, ib, ic, a).len()
            <= nested_semi_hits3(oa, ob, oc, ia, ib, ic, b).len(),
        forall|p: int|
            0 <= p < nested_semi_hits3(oa, ob, oc, ia, ib, ic, a).len() ==> (
                #[trigger] nested_semi_hits3(oa, ob, oc, ia, ib, ic, b)[p]
            ) == nested_semi_hits3(oa, ob, oc, ia, ib, ic, a)[p],
    decreases b - a,
{
    if a < b {
        lemma_semi_hit3_prefix(oa, ob, oc, ia, ib, ic, a, b - 1);
        lemma_nested_semi_hits3_step(oa, ob, oc, ia, ib, ic, b);
        let at_a = nested_semi_hits3(oa, ob, oc, ia, ib, ic, a);
        let at_prev = nested_semi_hits3(oa, ob, oc, ia, ib, ic, b - 1);
        let at_b = nested_semi_hits3(oa, ob, oc, ia, ib, ic, b);
        let ids = eq_row_ids3(ia, ib, ic, oa[b - 1], ob[b - 1], oc[b - 1], ia.len() as int);
        if ids.len() > 0 {
            assert(at_b == at_prev.push((b - 1) as usize));
            assert(at_a.len() <= at_prev.len());
            assert(at_a.len() <= at_b.len());
            assert forall|p: int| 0 <= p < at_a.len() implies at_b[p] == at_a[p] by {
                lemma_seq_push_index_different(at_prev, (b - 1) as usize, p);
                assert(at_b[p] == at_prev[p]);
                assert(at_prev[p] == at_a[p]);
            };
        } else {
            assert(at_b == at_prev);
        }
    }
}

pub proof fn lemma_semi_hit3_at<A, B, C>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    n: int,
    i: int,
)
    requires
        0 <= i < n <= oa.len(),
        n <= ob.len(),
        n <= oc.len(),
        n <= usize::MAX as int,
        eq_row_ids3(ia, ib, ic, oa[i], ob[i], oc[i], ia.len() as int).len() > 0,
    ensures
        (nested_semi_hits3(oa, ob, oc, ia, ib, ic, i).len() as int)
            < nested_semi_hits3(oa, ob, oc, ia, ib, ic, n).len(),
        nested_semi_hits3(oa, ob, oc, ia, ib, ic, n)[
            nested_semi_hits3(oa, ob, oc, ia, ib, ic, i).len() as int
        ] == i as usize,
{
    lemma_nested_semi_hits3_step(oa, ob, oc, ia, ib, ic, i + 1);
    assert(nested_semi_hits3(oa, ob, oc, ia, ib, ic, i + 1)
        == nested_semi_hits3(oa, ob, oc, ia, ib, ic, i).push(i as usize));
    lemma_semi_hit3_prefix(oa, ob, oc, ia, ib, ic, i + 1, n);
    let k = nested_semi_hits3(oa, ob, oc, ia, ib, ic, i).len() as int;
    assert(nested_semi_hits3(oa, ob, oc, ia, ib, ic, i + 1)[k] == i as usize);
    assert(nested_semi_hits3(oa, ob, oc, ia, ib, ic, n)[k]
        == nested_semi_hits3(oa, ob, oc, ia, ib, ic, i + 1)[k]);
}

pub proof fn lemma_semi_acc3<A, B, C, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
    i: int,
)
    requires
        oa.len() == n_outer,
        ob.len() == n_outer,
        oc.len() == n_outer,
        n_outer <= usize::MAX as int,
        0 <= i <= n_outer,
    ensures
        semi_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i) == hit_acc(
            nested_semi_hits3(oa, ob, oc, ia, ib, ic, n_outer),
            step,
            base,
            nested_semi_hits3(oa, ob, oc, ia, ib, ic, i).len() as int,
        ),
    decreases n_outer - i,
{
    if i < n_outer {
        lemma_semi_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i + 1);
        lemma_nested_semi_hits3_step(oa, ob, oc, ia, ib, ic, i + 1);
        let hits = nested_semi_hits3(oa, ob, oc, ia, ib, ic, n_outer);
        let k_i = nested_semi_hits3(oa, ob, oc, ia, ib, ic, i).len() as int;
        let ids = eq_row_ids3(ia, ib, ic, oa[i], ob[i], oc[i], ia.len() as int);
        if ids.len() > 0 {
            lemma_semi_hit3_at(oa, ob, oc, ia, ib, ic, n_outer, i);
            assert(hits[k_i] == i as usize);
            assert(0 <= k_i < hits.len());
            assert(semi_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i) == step(
                semi_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, i + 1),
                i,
            ));
            assert(hit_acc(hits, step, base, k_i) == step(
                hit_acc(hits, step, base, k_i + 1),
                hits[k_i] as int,
            ));
        } else {
            assert(nested_semi_hits3(oa, ob, oc, ia, ib, ic, i + 1)
                == nested_semi_hits3(oa, ob, oc, ia, ib, ic, i));
        }
    }
}

pub proof fn lemma_semi3_at_origin<A, B, C, Acc>(
    oa: Seq<A>,
    ob: Seq<B>,
    oc: Seq<C>,
    ia: Seq<A>,
    ib: Seq<B>,
    ic: Seq<C>,
    step: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
)
    requires
        oa.len() == n_outer,
        ob.len() == n_outer,
        oc.len() == n_outer,
        n_outer <= usize::MAX as int,
    ensures
        semi_loop_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, 0) == hit_acc(
            nested_semi_hits3(oa, ob, oc, ia, ib, ic, n_outer),
            step,
            base,
            0,
        ),
{
    assert(nested_semi_hits3(oa, ob, oc, ia, ib, ic, 0) =~= Seq::<usize>::empty());
    lemma_semi_acc3(oa, ob, oc, ia, ib, ic, step, base, n_outer, 0);
}

/// Three-key SEMI hit ids. View equals [`nested_semi_hits3`].
pub fn semi_hit_rows_str3(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    outer2: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
    inner2: &Vec<String>,
) -> (hits: Vec<usize>)
    requires
        outer0@.len() == outer1@.len(),
        outer0@.len() == outer2@.len(),
        inner0@.len() == inner1@.len(),
        inner0@.len() == inner2@.len(),
    ensures
        hits@ == nested_semi_hits3(
            key_views(outer0@),
            key_views(outer1@),
            key_views(outer2@),
            key_views(inner0@),
            key_views(inner1@),
            key_views(inner2@),
            outer0@.len() as int,
        ),
{
    let idx = build_eq_index_str(inner0);
    let ghost oa = key_views(outer0@);
    let ghost ob = key_views(outer1@);
    let ghost oc = key_views(outer2@);
    let ghost ia = key_views(inner0@);
    let ghost ib = key_views(inner1@);
    let ghost ic = key_views(inner2@);
    let mut hits: Vec<usize> = Vec::new();
    let mut i: usize = 0;
    while i < outer0.len()
        invariant
            i <= outer0.len(),
            outer0@.len() == outer0.len() as int,
            outer1@.len() == outer0@.len(),
            outer2@.len() == outer0@.len(),
            inner0@.len() == inner0.len() as int,
            inner1@.len() == inner0@.len(),
            inner2@.len() == inner0@.len(),
            oa == key_views(outer0@),
            ob == key_views(outer1@),
            oc == key_views(outer2@),
            ia == key_views(inner0@),
            ib == key_views(inner1@),
            ic == key_views(inner2@),
            index_ok(ia, idx.buckets@, idx.map@, inner0@.len() as int),
            hits@ == nested_semi_hits3(oa, ob, oc, ia, ib, ic, i as int),
        decreases outer0.len() - i,
    {
        let key0 = outer0[i].clone();
        let key1 = outer1[i].clone();
        let key2 = outer2[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer0@, end);
            lemma_key_view_at(outer1@, end);
            lemma_key_view_at(outer2@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(oa[end] == key0@);
            assert(ob[end] == key1@);
            assert(oc[end] == key2@);
            assert(ia.len() as int <= usize::MAX as int);
        }
        let ghost before = hits@;
        let present = idx.map.contains_key(key0.as_str());
        if present {
            let got = idx.map.get(key0.as_str());
            let bi = *got.unwrap();
            proof {
                assert(idx.map@.contains_key(key0@));
                lemma_index_bucket(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_bounded(ia, key0@, ia.len() as int);
            }
            let ids = &idx.buckets[bi];
            let filtered2 = filter_row_ids_str(ids, inner1, &key1);
            proof {
                lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                assert(filtered2@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                lemma_eq2_bounded(ia, ib, oa[end], ob[end], ia.len() as int);
                assert(ia.len() == inner2@.len());
                assert forall|t: int|
                    0 <= t < filtered2@.len() implies (#[trigger] filtered2@[t] as int)
                        < inner2@.len() by {
                    assert(
                        (eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int)[t] as int)
                            < ia.len()
                    );
                    assert(filtered2@[t]
                        == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int)[t]);
                };
            }
            let filtered3 = filter_row_ids_str(&filtered2, inner2, &key2);
            if filtered3.len() == 0 {
                proof {
                    lemma_filter_is_ids3(ia, ib, ic, key0@, key1@, key2@, ia.len() as int);
                    assert(filtered3@
                        == eq_row_ids3(ia, ib, ic, oa[end], ob[end], oc[end], ia.len() as int));
                    assert(eq_row_ids3(ia, ib, ic, oa[end], ob[end], oc[end], ia.len() as int)
                        .len() == 0);
                    lemma_nested_semi_hits3_step(oa, ob, oc, ia, ib, ic, end + 1);
                    assert(hits@ == nested_semi_hits3(oa, ob, oc, ia, ib, ic, end + 1));
                }
            } else {
                hits.push(i);
                proof {
                    lemma_filter_is_ids3(ia, ib, ic, key0@, key1@, key2@, ia.len() as int);
                    assert(filtered3@
                        == eq_row_ids3(ia, ib, ic, oa[end], ob[end], oc[end], ia.len() as int));
                    assert(eq_row_ids3(ia, ib, ic, oa[end], ob[end], oc[end], ia.len() as int)
                        .len() > 0);
                    lemma_nested_semi_hits3_step(oa, ob, oc, ia, ib, ic, end + 1);
                    assert(hits@ == before.push(i));
                    assert(hits@ == nested_semi_hits3(oa, ob, oc, ia, ib, ic, end + 1));
                }
            }
        } else {
            proof {
                assert(!idx.map@.contains_key(key0@));
                lemma_index_absent(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_len0(ia, key0@, ia.len() as int);
                lemma_eq_row_ids3_empty_from_first(
                    ia,
                    ib,
                    ic,
                    key0@,
                    key1@,
                    key2@,
                    ia.len() as int,
                );
                lemma_nested_semi_hits3_step(oa, ob, oc, ia, ib, ic, end + 1);
                assert(hits@ == nested_semi_hits3(oa, ob, oc, ia, ib, ic, end + 1));
            }
        }
        i = i + 1;
    }
    hits
}
// SHAPE_SEMI3_END

// SHAPE_LOJ2_BEGIN
// Two-key LEFT OUTER: matched (i, Some(j)) via eq_row_ids2, or (i, None) on miss.
// Reuses prefix_loj_pairs / loj_acc / push_prefix_loj_pairs from SHAPE_LOJ.

/// LEFT OUTER join list for `outer[0..n]` on two columns: matches, or `(i, None)` on miss.
pub open spec fn nested_loj_pairs2<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
) -> Seq<(usize, Option<usize>)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, Option<usize>)>::empty()
    } else if n - 1 >= outer_a.len() || n - 1 >= outer_b.len() {
        nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1)
    } else {
        let i = (n - 1) as usize;
        let ids = eq_row_ids2(
            inner_a,
            inner_b,
            outer_a[n - 1],
            outer_b[n - 1],
            inner_a.len() as int,
        );
        let prev = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1);
        if ids.len() == 0 {
            prev.push((i, None))
        } else {
            prev + prefix_loj_pairs(i, ids, ids.len() as int)
        }
    }
}

pub proof fn lemma_nested_loj_pairs2_step<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
)
    requires
        0 < n <= outer_a.len(),
        n <= outer_b.len(),
    ensures
        ({
            let ids = eq_row_ids2(
                inner_a,
                inner_b,
                outer_a[n - 1],
                outer_b[n - 1],
                inner_a.len() as int,
            );
            let prev = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1);
            let i = (n - 1) as usize;
            &&& ids.len() == 0 ==> nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n)
                == prev.push((i, None))
            &&& ids.len() > 0 ==> nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n)
                == prev + prefix_loj_pairs(i, ids, ids.len() as int)
        }),
{
    let ids = eq_row_ids2(
        inner_a,
        inner_b,
        outer_a[n - 1],
        outer_b[n - 1],
        inner_a.len() as int,
    );
    let prev = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1);
    let i = (n - 1) as usize;
    if ids.len() == 0 {
        assert(nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n) == prev.push((i, None)));
    } else {
        assert(nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n)
            == prev + prefix_loj_pairs(i, ids, ids.len() as int));
    }
}

/// Nested-loop LEFT OUTER fold on two keys: match `Some(i1)`; finished miss `None`.
pub open spec fn loj_loop_acc2<A, B, Acc>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    step: spec_fn(Acc, int, Option<int>) -> Acc,
    base: Acc,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
) -> Acc
    decreases n_outer - i0, n_inner - i1,
{
    if i0 < n_outer {
        if i1 < n_inner {
            let tail = loj_loop_acc2(
                outer_a,
                outer_b,
                inner_a,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0,
                i1 + 1,
            );
            if 0 <= i0 < outer_a.len() {
                if i0 < outer_b.len() {
                    if 0 <= i1 < inner_a.len() {
                        if i1 < inner_b.len() {
                            if outer_a[i0] == inner_a[i1] {
                                if outer_b[i0] == inner_b[i1] {
                                    step(tail, i0, Some(i1))
                                } else {
                                    tail
                                }
                            } else {
                                tail
                            }
                        } else {
                            tail
                        }
                    } else {
                        tail
                    }
                } else {
                    tail
                }
            } else {
                tail
            }
        } else {
            let tail = loj_loop_acc2(
                outer_a,
                outer_b,
                inner_a,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0 + 1,
                0,
            );
            if 0 <= i0 < outer_a.len() {
                if i0 < outer_b.len() {
                    if eq_row_ids2(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner).len() == 0 {
                        step(tail, i0, None)
                    } else {
                        tail
                    }
                } else {
                    tail
                }
            } else {
                tail
            }
        }
    } else {
        base
    }
}

/// Index into `nested_loj_pairs2` for the nested-loop cursor `(i0, i1)`.
pub open spec fn loj_pos2<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    i0: int,
    i1: int,
) -> int {
    if !(0 <= i0 < outer_a.len() && i0 < outer_b.len()) {
        nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0).len() as int
    } else {
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[i0], outer_b[i0], inner_a.len() as int);
        let base = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0).len() as int;
        if ids.len() == 0 {
            base
        } else {
            base + ids_lt(ids, ids.len() as int, i1)
        }
    }
}

pub proof fn lemma_loj_nested_len_mono2<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
    m: int,
)
    requires
        0 <= n <= m <= outer_a.len(),
        m <= outer_b.len(),
    ensures
        nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n).len()
            <= nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, m).len(),
    decreases m - n,
{
    if n < m {
        lemma_loj_nested_len_mono2(outer_a, outer_b, inner_a, inner_b, n, m - 1);
        lemma_nested_loj_pairs2_step(outer_a, outer_b, inner_a, inner_b, m);
        let ids = eq_row_ids2(
            inner_a,
            inner_b,
            outer_a[m - 1],
            outer_b[m - 1],
            inner_a.len() as int,
        );
        let prev = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, m - 1);
        let cur = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, m);
        if ids.len() == 0 {
            assert(cur == prev.push(((m - 1) as usize, None)));
            assert(prev.len() <= cur.len());
        } else {
            lemma_prefix_loj_len((m - 1) as usize, ids, ids.len() as int);
            assert(cur == prev + prefix_loj_pairs((m - 1) as usize, ids, ids.len() as int));
            assert(prev.len() <= cur.len());
        }
    }
}

pub proof fn lemma_loj_nested_index2<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
    m: int,
    p: int,
)
    requires
        0 <= n <= m <= outer_a.len(),
        m <= outer_b.len(),
        m <= usize::MAX as int,
        0 <= p < nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n).len(),
    ensures
        nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, m)[p]
            == nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n)[p],
    decreases m - n,
{
    if n < m {
        lemma_loj_nested_len_mono2(outer_a, outer_b, inner_a, inner_b, n, m - 1);
        lemma_loj_nested_index2(outer_a, outer_b, inner_a, inner_b, n, m - 1, p);
        lemma_nested_loj_pairs2_step(outer_a, outer_b, inner_a, inner_b, m);
        let prev = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, m - 1);
        let cur = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, m);
        let ids = eq_row_ids2(
            inner_a,
            inner_b,
            outer_a[m - 1],
            outer_b[m - 1],
            inner_a.len() as int,
        );
        let row = (m - 1) as usize;
        assert(row as int == m - 1);
        assert(0 <= p < prev.len());
        if ids.len() == 0 {
            assert(cur == prev.push((row, None)));
            lemma_seq_push_index_different(prev, (row, None), p);
        } else {
            let extra = prefix_loj_pairs(row, ids, ids.len() as int);
            assert(cur == prev + extra);
            lemma_left_index(prev, extra, p);
        }
    }
}

pub proof fn lemma_loj_acc2<A, B, Acc>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    step: spec_fn(Acc, int, Option<int>) -> Acc,
    base: Acc,
    n_outer: int,
    n_inner: int,
    i0: int,
    i1: int,
)
    requires
        outer_a.len() == n_outer,
        outer_b.len() == n_outer,
        inner_a.len() == n_inner,
        inner_b.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
        0 <= i0 <= n_outer,
        0 <= i1 <= n_inner,
    ensures
        loj_loop_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1,
        ) == loj_acc(
            nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n_outer),
            step,
            base,
            loj_pos2(outer_a, outer_b, inner_a, inner_b, i0, i1),
        ),
    decreases n_outer - i0, n_inner - i1,
{
    let pairs = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n_outer);
    let pos = loj_pos2(outer_a, outer_b, inner_a, inner_b, i0, i1);
    if i0 >= n_outer {
        assert(nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0) =~= pairs);
        assert(pos == pairs.len() as int);
    } else if i1 >= n_inner {
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
        if ids.len() == 0 {
            lemma_loj_acc2(
                outer_a,
                outer_b,
                inner_a,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0 + 1,
                0,
            );
            lemma_nested_loj_pairs2_step(outer_a, outer_b, inner_a, inner_b, i0 + 1);
            let earlier = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0);
            let through = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0 + 1);
            let i0u = i0 as usize;
            assert(i0u as int == i0);
            assert(through == earlier.push((i0u, None)));
            assert(pos == earlier.len() as int);
            assert(through.len() == earlier.len() + 1);
            assert(0 <= pos < through.len());
            lemma_loj_nested_len_mono2(outer_a, outer_b, inner_a, inner_b, i0 + 1, n_outer);
            assert(through.len() <= pairs.len());
            assert(pos < pairs.len());
            lemma_loj_nested_index2(outer_a, outer_b, inner_a, inner_b, i0 + 1, n_outer, pos);
            lemma_seq_push_index_same(earlier, (i0u, None), earlier.len() as int);
            assert(through[pos] == (i0u, None));
            assert(pairs[pos] == (i0u, None));
            if i0 + 1 < outer_a.len() {
                let next_ids = eq_row_ids2(
                    inner_a,
                    inner_b,
                    outer_a[i0 + 1],
                    outer_b[i0 + 1],
                    n_inner,
                );
                if next_ids.len() == 0 {
                    assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, i0 + 1, 0)
                        == nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0 + 1).len()
                            as int);
                } else {
                    lemma_ids_lt_zero(next_ids, next_ids.len() as int);
                    assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, i0 + 1, 0)
                        == nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0 + 1).len()
                            as int);
                }
            } else {
                assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, i0 + 1, 0)
                    == nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0 + 1).len() as int);
            }
            assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, i0 + 1, 0) == through.len() as int);
            assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, i0 + 1, 0) == pos + 1);
            assert(loj_loop_acc2(
                outer_a,
                outer_b,
                inner_a,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0,
                i1,
            ) == step(
                loj_loop_acc2(
                    outer_a,
                    outer_b,
                    inner_a,
                    inner_b,
                    step,
                    base,
                    n_outer,
                    n_inner,
                    i0 + 1,
                    0,
                ),
                i0,
                None,
            ));
            assert(loj_acc(pairs, step, base, pos) == step(
                loj_acc(pairs, step, base, pos + 1),
                i0,
                None,
            ));
        } else {
            lemma_loj_acc2(
                outer_a,
                outer_b,
                inner_a,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0 + 1,
                0,
            );
            lemma_eq2_members(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
            assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < n_inner by {
                assert(0 <= (ids[p] as int) < n_inner);
            };
            assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) < i1 by {
                assert((ids[p] as int) < n_inner);
                assert(n_inner <= i1);
            };
            lemma_ids_lt_all(ids, ids.len() as int, i1);
            let i0u = i0 as usize;
            assert(i0u as int == i0);
            lemma_prefix_loj_len(i0u, ids, ids.len() as int);
            lemma_nested_loj_pairs2_step(outer_a, outer_b, inner_a, inner_b, i0 + 1);
            assert(nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0 + 1).len()
                == nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0).len() + ids.len());
            if i0 + 1 < outer_a.len() {
                let next_ids = eq_row_ids2(
                    inner_a,
                    inner_b,
                    outer_a[i0 + 1],
                    outer_b[i0 + 1],
                    n_inner,
                );
                lemma_ids_lt_zero(next_ids, next_ids.len() as int);
            }
            assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, i0 + 1, 0) == pos);
        }
    } else if outer_a[i0] == inner_a[i1] && outer_b[i0] == inner_b[i1] {
        lemma_loj_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1 + 1,
        );
        lemma_eq2_rank(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner, i1);
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
        assert(ids.len() > 0);
        let r = ids_lt(ids, ids.len() as int, i1);
        let i0u = i0 as usize;
        assert(i0u as int == i0);
        lemma_prefix_loj_len(i0u, ids, ids.len() as int);
        lemma_loj_prefix_at(i0u, ids, ids.len() as int, r);
        let row_pairs = prefix_loj_pairs(i0u, ids, ids.len() as int);
        let earlier = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0);
        let through = nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, i0 + 1);
        lemma_nested_loj_pairs2_step(outer_a, outer_b, inner_a, inner_b, i0 + 1);
        assert(through == earlier + row_pairs);
        assert(i1 as int <= usize::MAX as int);
        let i1u = i1 as usize;
        assert(i1u as int == i1);
        assert(row_pairs[r] == (i0u, Some(i1u)));
        assert(0 <= r < row_pairs.len());
        lemma_right_index(earlier, row_pairs, r);
        assert(pos == earlier.len() as int + r);
        assert(through.len() == earlier.len() + row_pairs.len());
        assert(pos < through.len());
        lemma_loj_nested_len_mono2(outer_a, outer_b, inner_a, inner_b, i0 + 1, n_outer);
        assert(through.len() <= pairs.len());
        assert(pos < pairs.len());
        lemma_loj_nested_index2(outer_a, outer_b, inner_a, inner_b, i0 + 1, n_outer, pos);
        assert(through[pos] == (i0u, Some(i1u)));
        assert(pairs[pos] == (i0u, Some(i1u)));
        assert(pos + 1 == loj_pos2(outer_a, outer_b, inner_a, inner_b, i0, i1 + 1));
        assert(loj_loop_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1,
        ) == step(
            loj_loop_acc2(
                outer_a,
                outer_b,
                inner_a,
                inner_b,
                step,
                base,
                n_outer,
                n_inner,
                i0,
                i1 + 1,
            ),
            i0,
            Some(i1),
        ));
        assert(loj_acc(pairs, step, base, pos) == step(
            loj_acc(pairs, step, base, pos + 1),
            i0,
            Some(i1),
        ));
    } else {
        lemma_loj_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            i0,
            i1 + 1,
        );
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
        if ids.len() == 0 {
            assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, i0, i1 + 1) == pos);
        } else {
            lemma_eq2_members(inner_a, inner_b, outer_a[i0], outer_b[i0], n_inner);
            assert forall|p: int| 0 <= p < ids.len() implies (ids[p] as int) != i1 by {
                if (ids[p] as int) == i1 {
                    assert(inner_a[i1] == outer_a[i0]);
                    assert(inner_b[i1] == outer_b[i0]);
                    assert(false);
                }
            };
            lemma_ids_lt_skip(ids, ids.len() as int, i1);
            assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, i0, i1 + 1) == pos);
        }
    }
}

pub proof fn lemma_loj_pos2_origin<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
)
    requires
        outer_a.len() <= usize::MAX as int,
        outer_b.len() <= usize::MAX as int,
        inner_a.len() <= usize::MAX as int,
        inner_b.len() <= usize::MAX as int,
    ensures
        loj_pos2(outer_a, outer_b, inner_a, inner_b, 0, 0) == 0,
{
    assert(nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, 0)
        =~= Seq::<(usize, Option<usize>)>::empty());
    if outer_a.len() > 0 && outer_b.len() > 0 {
        let ids = eq_row_ids2(inner_a, inner_b, outer_a[0], outer_b[0], inner_a.len() as int);
        if ids.len() == 0 {
            assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, 0, 0) == 0);
        } else {
            lemma_ids_lt_zero(ids, ids.len() as int);
            assert(loj_pos2(outer_a, outer_b, inner_a, inner_b, 0, 0) == 0);
        }
    }
}

/// At the origin indices, ``loj_loop_acc2`` equals ``loj_acc`` of the full LOJ2 list at 0.
pub proof fn lemma_loj_at_origin2<A, B, Acc>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    step: spec_fn(Acc, int, Option<int>) -> Acc,
    base: Acc,
    n_outer: int,
    n_inner: int,
)
    requires
        outer_a.len() == n_outer,
        outer_b.len() == n_outer,
        inner_a.len() == n_inner,
        inner_b.len() == n_inner,
        n_outer <= usize::MAX as int,
        n_inner <= usize::MAX as int,
    ensures
        loj_loop_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step,
            base,
            n_outer,
            n_inner,
            0,
            0,
        ) == loj_acc(
            nested_loj_pairs2(outer_a, outer_b, inner_a, inner_b, n_outer),
            step,
            base,
            0,
        ),
{
    lemma_loj_acc2(outer_a, outer_b, inner_a, inner_b, step, base, n_outer, n_inner, 0, 0);
    lemma_loj_pos2_origin(outer_a, outer_b, inner_a, inner_b);
}

/// LEFT OUTER pair list for two `String` key columns. View equals [`nested_loj_pairs2`].
pub fn left_outer_pairs_str2(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
) -> (pairs: Vec<(usize, Option<usize>)>)
    requires
        outer0@.len() == outer1@.len(),
        inner0@.len() == inner1@.len(),
    ensures
        pairs@ == nested_loj_pairs2(
            key_views(outer0@),
            key_views(outer1@),
            key_views(inner0@),
            key_views(inner1@),
            outer0@.len() as int,
        ),
{
    let idx = build_eq_index_str(inner0);
    let ghost oa = key_views(outer0@);
    let ghost ob = key_views(outer1@);
    let ghost ia = key_views(inner0@);
    let ghost ib = key_views(inner1@);
    let mut pairs: Vec<(usize, Option<usize>)> = Vec::new();
    let mut i: usize = 0;
    while i < outer0.len()
        invariant
            i <= outer0.len(),
            outer0@.len() == outer0.len() as int,
            outer1@.len() == outer0@.len(),
            inner0@.len() == inner0.len() as int,
            inner1@.len() == inner0@.len(),
            oa == key_views(outer0@),
            ob == key_views(outer1@),
            ia == key_views(inner0@),
            ib == key_views(inner1@),
            index_ok(ia, idx.buckets@, idx.map@, inner0@.len() as int),
            pairs@ == nested_loj_pairs2(oa, ob, ia, ib, i as int),
        decreases outer0.len() - i,
    {
        let key0 = outer0[i].clone();
        let key1 = outer1[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer0@, end);
            lemma_key_view_at(outer1@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(oa[end] == key0@);
            assert(ob[end] == key1@);
            assert(ia.len() as int <= usize::MAX as int);
        }
        let ghost before = pairs@;
        let present = idx.map.contains_key(key0.as_str());
        if present {
            let got = idx.map.get(key0.as_str());
            let bi = *got.unwrap();
            proof {
                assert(idx.map@.contains_key(key0@));
                lemma_index_bucket(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_bounded(ia, key0@, ia.len() as int);
            }
            let ids = &idx.buckets[bi];
            let filtered = filter_row_ids_str(ids, inner1, &key1);
            if filtered.len() == 0 {
                pairs.push((i, None));
                proof {
                    lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                    assert(filtered@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                    assert(eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int).len() == 0);
                    lemma_nested_loj_pairs2_step(oa, ob, ia, ib, end + 1);
                    assert(pairs@ == before.push((i, None)));
                    assert(pairs@ == nested_loj_pairs2(oa, ob, ia, ib, end + 1));
                }
            } else {
                push_prefix_loj_pairs(&mut pairs, i, &filtered);
                proof {
                    lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                    assert(filtered@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                    assert(eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int).len() > 0);
                    lemma_nested_loj_pairs2_step(oa, ob, ia, ib, end + 1);
                    assert(pairs@ == before + prefix_loj_pairs(i, filtered@, filtered@.len() as int));
                    assert(pairs@ == nested_loj_pairs2(oa, ob, ia, ib, end + 1));
                }
            }
        } else {
            pairs.push((i, None));
            proof {
                assert(!idx.map@.contains_key(key0@));
                lemma_index_absent(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_len0(ia, key0@, ia.len() as int);
                lemma_eq_row_ids2_empty_from_first(ia, ib, key0@, key1@, ia.len() as int);
                lemma_nested_loj_pairs2_step(oa, ob, ia, ib, end + 1);
                assert(pairs@ == before.push((i, None)));
                assert(pairs@ == nested_loj_pairs2(oa, ob, ia, ib, end + 1));
            }
        }
        i = i + 1;
    }
    pairs
}
// SHAPE_LOJ2_END

// SHAPE_RIGHT2_BEGIN
// Two-key RIGHT OUTER after honest side-swap (preserved = outer): matched pairs
// via eq_row_ids2, or (i, None) on miss. Same outer-major order as nested_right_pairs.
// Reuses prefix_right_pairs / right_acc from SHAPE_RIGHT.

/// Outer-major RIGHT-outer slots for `outer[0..n]` on two columns.
pub open spec fn nested_right_pairs2<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
) -> Seq<(usize, Option<usize>)>
    decreases n,
{
    if n <= 0 {
        Seq::<(usize, Option<usize>)>::empty()
    } else if n - 1 >= outer_a.len() || n - 1 >= outer_b.len() {
        nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1)
    } else {
        let i = (n - 1) as usize;
        let ids = eq_row_ids2(
            inner_a,
            inner_b,
            outer_a[n - 1],
            outer_b[n - 1],
            inner_a.len() as int,
        );
        let prev = nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1);
        if ids.len() == 0 {
            prev.push((i, None))
        } else {
            prev + prefix_right_pairs(i, ids, ids.len() as int)
        }
    }
}

pub proof fn lemma_nested_right_pairs2_step<A, B>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    n: int,
)
    requires
        0 < n <= outer_a.len(),
        n <= outer_b.len(),
    ensures
        ({
            let ids = eq_row_ids2(
                inner_a,
                inner_b,
                outer_a[n - 1],
                outer_b[n - 1],
                inner_a.len() as int,
            );
            let prev = nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1);
            let i = (n - 1) as usize;
            &&& ids.len() == 0 ==> nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n)
                == prev.push((i, None))
            &&& ids.len() > 0 ==> nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n)
                == prev + prefix_right_pairs(i, ids, ids.len() as int)
        }),
{
    let ids = eq_row_ids2(
        inner_a,
        inner_b,
        outer_a[n - 1],
        outer_b[n - 1],
        inner_a.len() as int,
    );
    let prev = nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n - 1);
    let i = (n - 1) as usize;
    if ids.len() == 0 {
        assert(nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n) == prev.push((i, None)));
    } else {
        assert(nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n)
            == prev + prefix_right_pairs(i, ids, ids.len() as int));
    }
}

pub proof fn lemma_prefix_right_pairs_step(i: usize, js: Seq<usize>, t: int)
    requires
        0 <= t < js.len(),
    ensures
        prefix_right_pairs(i, js, t + 1) == prefix_right_pairs(i, js, t).push((i, Some(js[t]))),
{
    assert(prefix_right_pairs(i, js, t + 1) == prefix_right_pairs(i, js, t).push((i, Some(js[t]))));
}

pub fn push_prefix_right_pairs(slots: &mut Vec<(usize, Option<usize>)>, i: usize, ids: &Vec<usize>)
    ensures
        final(slots)@ == old(slots)@ + prefix_right_pairs(i, ids@, ids@.len() as int),
{
    proof {
        broadcast use vstd::std_specs::vec::axiom_spec_len;
        assert(ids@.len() == ids.len() as int);
    }
    let ghost base = slots@;
    let mut extra: Vec<(usize, Option<usize>)> = Vec::new();
    let mut t: usize = 0;
    while t < ids.len()
        invariant
            t <= ids.len(),
            ids@.len() == ids.len() as int,
            extra@ == prefix_right_pairs(i, ids@, t as int),
        decreases ids.len() - t,
    {
        let ghost old_extra = extra@;
        let id = ids[t];
        extra.push((i, Some(id)));
        proof {
            assert(id == ids@[t as int]);
            lemma_prefix_right_pairs_step(i, ids@, t as int);
            assert(extra@ == old_extra.push((i, Some(ids@[t as int]))));
            assert(extra@ == prefix_right_pairs(i, ids@, t as int + 1));
        }
        t = t + 1;
    }
    proof {
        assert(extra@ == prefix_right_pairs(i, ids@, ids@.len() as int));
        assert(slots@ == base);
    }
    slots.append(&mut extra);
    proof {
        assert(slots@ == base + prefix_right_pairs(i, ids@, ids@.len() as int));
    }
}

/// Alias: RIGHT-outer fold on two keys equals `right_acc` of the two-key slot list.
pub open spec fn right_loop_acc2<A, B, Acc>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    step_hit: spec_fn(Acc, int, int) -> Acc,
    step_miss: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
    _i: int,
) -> Acc {
    right_acc(
        nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n_outer),
        step_hit,
        step_miss,
        base,
        0,
    )
}

/// Origin fact: two-key RIGHT-outer fold equals `right_acc` of the full slot list at 0.
pub proof fn lemma_right_at_origin2<A, B, Acc>(
    outer_a: Seq<A>,
    outer_b: Seq<B>,
    inner_a: Seq<A>,
    inner_b: Seq<B>,
    step_hit: spec_fn(Acc, int, int) -> Acc,
    step_miss: spec_fn(Acc, int) -> Acc,
    base: Acc,
    n_outer: int,
)
    ensures
        right_loop_acc2(
            outer_a,
            outer_b,
            inner_a,
            inner_b,
            step_hit,
            step_miss,
            base,
            n_outer,
            0,
        ) == right_acc(
            nested_right_pairs2(outer_a, outer_b, inner_a, inner_b, n_outer),
            step_hit,
            step_miss,
            base,
            0,
        ),
{
}

/// RIGHT OUTER pair list for two `String` key columns. View equals [`nested_right_pairs2`].
pub fn right_outer_pairs_str2(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
) -> (slots: Vec<(usize, Option<usize>)>)
    requires
        outer0@.len() == outer1@.len(),
        inner0@.len() == inner1@.len(),
    ensures
        slots@ == nested_right_pairs2(
            key_views(outer0@),
            key_views(outer1@),
            key_views(inner0@),
            key_views(inner1@),
            outer0@.len() as int,
        ),
{
    let idx = build_eq_index_str(inner0);
    let ghost oa = key_views(outer0@);
    let ghost ob = key_views(outer1@);
    let ghost ia = key_views(inner0@);
    let ghost ib = key_views(inner1@);
    let mut slots: Vec<(usize, Option<usize>)> = Vec::new();
    let mut i: usize = 0;
    while i < outer0.len()
        invariant
            i <= outer0.len(),
            outer0@.len() == outer0.len() as int,
            outer1@.len() == outer0@.len(),
            inner0@.len() == inner0.len() as int,
            inner1@.len() == inner0@.len(),
            oa == key_views(outer0@),
            ob == key_views(outer1@),
            ia == key_views(inner0@),
            ib == key_views(inner1@),
            index_ok(ia, idx.buckets@, idx.map@, inner0@.len() as int),
            slots@ == nested_right_pairs2(oa, ob, ia, ib, i as int),
        decreases outer0.len() - i,
    {
        let key0 = outer0[i].clone();
        let key1 = outer1[i].clone();
        let ghost end = i as int;
        proof {
            lemma_key_view_at(outer0@, end);
            lemma_key_view_at(outer1@, end);
            broadcast use vstd::std_specs::vec::axiom_spec_len;
            assert(oa[end] == key0@);
            assert(ob[end] == key1@);
            assert(ia.len() as int <= usize::MAX as int);
        }
        let ghost before = slots@;
        let present = idx.map.contains_key(key0.as_str());
        if present {
            let got = idx.map.get(key0.as_str());
            let bi = *got.unwrap();
            proof {
                assert(idx.map@.contains_key(key0@));
                lemma_index_bucket(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_bounded(ia, key0@, ia.len() as int);
            }
            let ids = &idx.buckets[bi];
            let filtered = filter_row_ids_str(ids, inner1, &key1);
            if filtered.len() == 0 {
                slots.push((i, None));
                proof {
                    lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                    assert(filtered@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                    assert(eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int).len() == 0);
                    lemma_nested_right_pairs2_step(oa, ob, ia, ib, end + 1);
                    assert(slots@ == before.push((i, None)));
                    assert(slots@ == nested_right_pairs2(oa, ob, ia, ib, end + 1));
                }
            } else {
                push_prefix_right_pairs(&mut slots, i, &filtered);
                proof {
                    lemma_filter_is_ids2(ia, ib, key0@, key1@, ia.len() as int);
                    assert(filtered@ == eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int));
                    assert(eq_row_ids2(ia, ib, oa[end], ob[end], ia.len() as int).len() > 0);
                    lemma_nested_right_pairs2_step(oa, ob, ia, ib, end + 1);
                    assert(slots@ == before + prefix_right_pairs(i, filtered@, filtered@.len() as int));
                    assert(slots@ == nested_right_pairs2(oa, ob, ia, ib, end + 1));
                }
            }
        } else {
            slots.push((i, None));
            proof {
                assert(!idx.map@.contains_key(key0@));
                lemma_index_absent(ia, idx.buckets@, idx.map@, ia.len() as int, key0@);
                lemma_eq_row_ids_len0(ia, key0@, ia.len() as int);
                lemma_eq_row_ids2_empty_from_first(ia, ib, key0@, key1@, ia.len() as int);
                lemma_nested_right_pairs2_step(oa, ob, ia, ib, end + 1);
                assert(slots@ == before.push((i, None)));
                assert(slots@ == nested_right_pairs2(oa, ob, ia, ib, end + 1));
            }
        }
        i = i + 1;
    }
    slots
}
// SHAPE_RIGHT2_END

// SHAPE_FULL2_BEGIN
// Two-key FULL OUTER: matched pairs + left/right anti-misses via *2 helpers.
// Parts reuse nested_eq_pairs2 / nested_anti_misses2; no whole-join Trusted.

/// Matched pairs + left anti-misses + right anti-misses (two String keys).
pub fn full_outer_parts_str2(
    left0: &Vec<String>,
    left1: &Vec<String>,
    right0: &Vec<String>,
    right1: &Vec<String>,
) -> (parts: (Vec<(usize, usize)>, Vec<usize>, Vec<usize>))
    requires
        left0@.len() == left1@.len(),
        right0@.len() == right1@.len(),
    ensures
        parts.0@ == nested_eq_pairs2(
            key_views(left0@),
            key_views(left1@),
            key_views(right0@),
            key_views(right1@),
            left0@.len() as int,
        ),
        parts.1@ == nested_anti_misses2(
            key_views(left0@),
            key_views(left1@),
            key_views(right0@),
            key_views(right1@),
            left0@.len() as int,
        ),
        parts.2@ == nested_anti_misses2(
            key_views(right0@),
            key_views(right1@),
            key_views(left0@),
            key_views(left1@),
            right0@.len() as int,
        ),
{
    let pairs = equijoin_pairs_str2(left0, left1, right0, right1);
    let left_miss = anti_miss_rows_str2(left0, left1, right0, right1);
    let right_miss = anti_miss_rows_str2(right0, right1, left0, left1);
    (pairs, left_miss, right_miss)
}
// SHAPE_FULL2_END

// EQ_JOIN_PROVED_END


#[verifier::external_body]
fn oracle_key(n: usize) -> (s: String) {
    n.to_string()
}

#[verifier::external_body]
fn oracle_naive_pairs(outer: &Vec<String>, inner: &Vec<String>) -> (out: Vec<(usize, usize)>) {
    let mut out = Vec::new();
    let mut i = 0;
    while i < outer.len() {
        let mut j = 0;
        while j < inner.len() {
            if outer[i] == inner[j] {
                out.push((i, j));
            }
            j += 1;
        }
        i += 1;
    }
    out
}

#[verifier::external_body]
fn oracle_expect_pairs(got: &Vec<(usize, usize)>, exp: &Vec<(usize, usize)>) {
    if got.len() != exp.len() {
        panic!("pair len {} != {}", got.len(), exp.len());
    }
    let mut i = 0;
    while i < got.len() {
        if got[i] != exp[i] {
            panic!("pair mismatch at {}", i);
        }
        i += 1;
    }
}

#[verifier::external_body]
fn oracle_fill(dst: &mut Vec<String>, n: usize, salt: usize, modu: usize) {
    dst.clear();
    let mut i = 0;
    while i < n {
        let id = if modu == 0 { i } else { (i.wrapping_mul(salt).wrapping_add(salt)) % modu };
        dst.push(oracle_key(id));
        i += 1;
    }
}

#[verifier::external_body]
fn oracle_check_case(outer: &Vec<String>, inner: &Vec<String>) {
    let got = equijoin_pairs_str(outer, inner);
    let exp = oracle_naive_pairs(outer, inner);
    oracle_expect_pairs(&got, &exp);
    let idx = build_eq_index_str(inner);
    let mut seen = vec![0usize; inner.len()];
    let mut i = 0;
    while i < inner.len() {
        match probe_eq_str(&idx, inner, inner[i].as_str()) {
            Some(bucket) => {
                let mut found = false;
                let mut t = 0;
                while t < bucket.len() {
                    if bucket[t] == i {
                        found = true;
                    }
                    if t > 0 && bucket[t] <= bucket[t - 1] {
                        panic!("bucket not increasing");
                    }
                    if bucket[t] >= inner.len() || inner[bucket[t]] != inner[i] {
                        panic!("bucket element not a match");
                    }
                    t += 1;
                }
                if !found {
                    panic!("row missing from its bucket");
                }
            },
            None => panic!("probe missed an existing key"),
        }
        seen[i] = seen[i] + 1;
        i += 1;
    }
    let miss = probe_eq_str(&idx, inner, "\u{0000}no-such-key");
    match miss {
        Some(_) => panic!("probe invented a key"),
        None => {},
    }
}

#[verifier::external_body]
fn oracle_naive_u64(outer: &Vec<u64>, inner: &Vec<u64>) -> (out: Vec<(usize, usize)>) {
    let mut out = Vec::new();
    let mut i = 0;
    while i < outer.len() {
        let mut j = 0;
        while j < inner.len() {
            if outer[i] == inner[j] {
                out.push((i, j));
            }
            j += 1;
        }
        i += 1;
    }
    out
}

#[verifier::external_body]
fn oracle_fill_u64(dst: &mut Vec<u64>, n: usize, salt: usize, modu: usize) {
    dst.clear();
    let mut i = 0;
    while i < n {
        let id = if modu == 0 { i as u64 } else { ((i.wrapping_mul(salt).wrapping_add(salt)) % modu) as u64 };
        dst.push(id);
        i += 1;
    }
}

#[verifier::external_body]
fn oracle_check_u64(outer: &Vec<u64>, inner: &Vec<u64>) {
    let got = equijoin_pairs_u64(outer, inner);
    let exp = oracle_naive_u64(outer, inner);
    oracle_expect_pairs(&got, &exp);
}

#[verifier::external_body]
fn oracle_naive_u32(outer: &Vec<u32>, inner: &Vec<u32>) -> (out: Vec<(usize, usize)>) {
    let mut out = Vec::new();
    let mut i = 0;
    while i < outer.len() {
        let mut j = 0;
        while j < inner.len() {
            if outer[i] == inner[j] {
                out.push((i, j));
            }
            j += 1;
        }
        i += 1;
    }
    out
}

#[verifier::external_body]
fn oracle_check_u32(outer: &Vec<u32>, inner: &Vec<u32>) {
    let got = equijoin_pairs_u32(outer, inner);
    let exp = oracle_naive_u32(outer, inner);
    oracle_expect_pairs(&got, &exp);
}

#[verifier::external_body]
fn oracle_naive_str2(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
) -> (out: Vec<(usize, usize)>) {
    let mut out = Vec::new();
    let mut i = 0;
    while i < outer0.len() {
        let mut j = 0;
        while j < inner0.len() {
            if outer0[i] == inner0[j] && outer1[i] == inner1[j] {
                out.push((i, j));
            }
            j += 1;
        }
        i += 1;
    }
    out
}

#[verifier::external_body]
fn oracle_check_str2(
    outer0: &Vec<String>,
    outer1: &Vec<String>,
    inner0: &Vec<String>,
    inner1: &Vec<String>,
) {
    let got = equijoin_pairs_str2(outer0, outer1, inner0, inner1);
    let exp = oracle_naive_str2(outer0, outer1, inner0, inner1);
    oracle_expect_pairs(&got, &exp);
}

#[verifier::external_body]
fn oracle_expect_triples(got: &Vec<(usize, usize, usize)>, exp: &Vec<(usize, usize, usize)>) {
    if got.len() != exp.len() {
        panic!("triple len {} != {}", got.len(), exp.len());
    }
    let mut i = 0;
    while i < got.len() {
        if got[i] != exp[i] {
            panic!("triple mismatch at {}", i);
        }
        i += 1;
    }
}

#[verifier::external_body]
fn oracle_naive_star(
    pre_adsh: &Vec<String>,
    pre_tag: &Vec<String>,
    pre_ver: &Vec<String>,
    sub_adsh: &Vec<String>,
    tag_tag: &Vec<String>,
    tag_ver: &Vec<String>,
) -> (out: Vec<(usize, usize, usize)>) {
    let mut out = Vec::new();
    let mut i = 0;
    while i < pre_adsh.len() {
        let mut s = 0;
        while s < sub_adsh.len() {
            if pre_adsh[i] == sub_adsh[s] {
                let mut t = 0;
                while t < tag_tag.len() {
                    if pre_tag[i] == tag_tag[t] && pre_ver[i] == tag_ver[t] {
                        out.push((i, s, t));
                    }
                    t += 1;
                }
            }
            s += 1;
        }
        i += 1;
    }
    out
}

#[verifier::external_body]
fn oracle_check_star(
    pre_adsh: &Vec<String>,
    pre_tag: &Vec<String>,
    pre_ver: &Vec<String>,
    sub_adsh: &Vec<String>,
    tag_tag: &Vec<String>,
    tag_ver: &Vec<String>,
) {
    let got = star_eq_triples_str(pre_adsh, pre_tag, pre_ver, sub_adsh, tag_tag, tag_ver);
    let exp = oracle_naive_star(pre_adsh, pre_tag, pre_ver, sub_adsh, tag_tag, tag_ver);
    oracle_expect_triples(&got, &exp);
}

#[verifier::external_body]
fn check_eq_join_oracle() {
    oracle_check_case(&Vec::new(), &Vec::new());
    let mut a: Vec<String> = Vec::new();
    let mut b: Vec<String> = Vec::new();
    a.push("adsh".to_string());
    oracle_check_case(&a, &b);
    oracle_check_case(&b, &a);
    b.push("adsh".to_string());
    oracle_check_case(&a, &b);
    b.push("adsh".to_string());
    a.push("other".to_string());
    a.push("adsh".to_string());
    oracle_check_case(&a, &b);
    let mut i = 0;
    while i < 25 {
        oracle_fill(&mut a, (i % 9) + 1, i + 3, (i % 5) + 1);
        oracle_fill(&mut b, (i % 7) + 1, i + 5, (i % 4) + 1);
        oracle_check_case(&a, &b);
        i += 1;
    }
    oracle_fill(&mut a, 4000, 1, 250);
    oracle_fill(&mut b, 250, 1, 250);
    oracle_check_case(&a, &b);
    oracle_fill(&mut a, 300, 1, 1);
    oracle_fill(&mut b, 300, 1, 1);
    oracle_check_case(&a, &b);
    a.clear();
    b.clear();
    a.push("".to_string());
    a.push("λ".to_string());
    b.push("".to_string());
    b.push("λ".to_string());
    b.push("".to_string());
    oracle_check_case(&a, &b);
    let mut long = String::new();
    i = 0;
    while i < 2000 {
        long.push('x');
        i += 1;
    }
    a.clear();
    b.clear();
    a.push(long.clone());
    b.push(long);
    b.push("y".to_string());
    oracle_check_case(&a, &b);
    oracle_fill(&mut b, 20000, 1, 20000);
    let idx = build_eq_index_str(&b);
    i = 0;
    while i < b.len() {
        match probe_eq_str(&idx, &b, b[i].as_str()) {
            Some(bucket) => {
                if bucket.len() != 1 || bucket[0] != i {
                    panic!("unique key bucket");
                }
            },
            None => panic!("unique key missing"),
        }
        i += 1;
    }

    let mut x64: Vec<u64> = Vec::new();
    let mut y64: Vec<u64> = Vec::new();
    oracle_check_u64(&x64, &y64);
    x64.push(0);
    oracle_check_u64(&x64, &y64);
    y64.push(0);
    y64.push(0);
    x64.push(u64::MAX);
    oracle_check_u64(&x64, &y64);
    oracle_fill_u64(&mut x64, 4000, 1, 250);
    oracle_fill_u64(&mut y64, 250, 1, 250);
    oracle_check_u64(&x64, &y64);
    oracle_fill_u64(&mut x64, 300, 7, 1);
    oracle_fill_u64(&mut y64, 300, 7, 1);
    oracle_check_u64(&x64, &y64);
    oracle_fill_u64(&mut y64, 20000, 1, 20000);
    oracle_fill_u64(&mut x64, 1000, 3, 20000);
    oracle_check_u64(&x64, &y64);

    let mut x32: Vec<u32> = Vec::new();
    let mut y32: Vec<u32> = Vec::new();
    x32.push(0);
    x32.push(u32::MAX);
    y32.push(u32::MAX);
    y32.push(1);
    oracle_check_u32(&x32, &y32);
    i = 0;
    x32.clear();
    y32.clear();
    while i < 500 {
        x32.push((i % 40) as u32);
        y32.push((i % 17) as u32);
        i += 1;
    }
    oracle_check_u32(&x32, &y32);

    let mut o0: Vec<String> = Vec::new();
    let mut o1: Vec<String> = Vec::new();
    let mut n0: Vec<String> = Vec::new();
    let mut n1: Vec<String> = Vec::new();
    oracle_check_str2(&o0, &o1, &n0, &n1);
    o0.push("Assets".to_string());
    o1.push("us-gaap/2024".to_string());
    n0.push("Assets".to_string());
    n1.push("us-gaap/2023".to_string());
    oracle_check_str2(&o0, &o1, &n0, &n1);
    n1.clear();
    n1.push("us-gaap/2024".to_string());
    n0.push("Assets".to_string());
    n1.push("us-gaap/2024".to_string());
    o0.push("Liab".to_string());
    o1.push("us-gaap/2024".to_string());
    oracle_check_str2(&o0, &o1, &n0, &n1);
    oracle_fill(&mut o0, 1500, 1, 80);
    oracle_fill(&mut o1, 1500, 3, 20);
    oracle_fill(&mut n0, 200, 1, 80);
    oracle_fill(&mut n1, 200, 3, 20);
    oracle_check_str2(&o0, &o1, &n0, &n1);

    let mut pre_a: Vec<String> = Vec::new();
    let mut pre_t: Vec<String> = Vec::new();
    let mut pre_v: Vec<String> = Vec::new();
    let mut sub_a: Vec<String> = Vec::new();
    let mut tag_t: Vec<String> = Vec::new();
    let mut tag_v: Vec<String> = Vec::new();
    oracle_check_star(&pre_a, &pre_t, &pre_v, &sub_a, &tag_t, &tag_v);
    pre_a.push("0001".to_string());
    pre_t.push("Assets".to_string());
    pre_v.push("us-gaap/2024".to_string());
    oracle_check_star(&pre_a, &pre_t, &pre_v, &sub_a, &tag_t, &tag_v);
    sub_a.push("0001".to_string());
    sub_a.push("0001".to_string());
    tag_t.push("Assets".to_string());
    tag_v.push("us-gaap/2023".to_string());
    oracle_check_star(&pre_a, &pre_t, &pre_v, &sub_a, &tag_t, &tag_v);
    tag_t.push("Assets".to_string());
    tag_v.push("us-gaap/2024".to_string());
    pre_a.push("0002".to_string());
    pre_t.push("Liab".to_string());
    pre_v.push("ifrs/2024".to_string());
    oracle_check_star(&pre_a, &pre_t, &pre_v, &sub_a, &tag_t, &tag_v);
    oracle_fill(&mut pre_a, 400, 1, 60);
    oracle_fill(&mut pre_t, 400, 5, 30);
    oracle_fill(&mut pre_v, 400, 9, 8);
    oracle_fill(&mut sub_a, 120, 1, 60);
    oracle_fill(&mut tag_t, 90, 5, 30);
    oracle_fill(&mut tag_v, 90, 9, 8);
    oracle_check_star(&pre_a, &pre_t, &pre_v, &sub_a, &tag_t, &tag_v);
    oracle_fill(&mut pre_a, 40, 1, 1);
    oracle_fill(&mut pre_t, 40, 1, 1);
    oracle_fill(&mut pre_v, 40, 1, 1);
    oracle_fill(&mut sub_a, 40, 1, 1);
    oracle_fill(&mut tag_t, 40, 1, 1);
    oracle_fill(&mut tag_v, 40, 1, 1);
    oracle_check_star(&pre_a, &pre_t, &pre_v, &sub_a, &tag_t, &tag_v);
    oracle_bench_equijoin();
}

#[verifier::external_body]
fn oracle_bench_equijoin() {
    let n_in: usize = 20_000;
    let n_out: usize = 100_000;
    let mut inner: Vec<String> = Vec::new();
    let mut i: usize = 0;
    while i < n_in {
        inner.push(i.to_string());
        i += 1;
    }
    let mut outer: Vec<String> = Vec::new();
    i = 0;
    while i < n_out {
        outer.push((i % n_in).to_string());
        i += 1;
    }
    let started = std::time::Instant::now();
    let pairs = equijoin_pairs_str(&outer, &inner);
    let us = started.elapsed().as_micros();
    if pairs.len() != n_out || pairs[0] != (0, 0) || pairs[n_out - 1] != (n_out - 1, (n_out - 1) % n_in) {
        panic!("bench pairs wrong len {}", pairs.len());
    }
    if us > 5_000_000 {
        panic!("bench equijoin slow {}us", us);
    }
}


} // verus!

fn main() {
    check_eq_join_oracle();
}
