use vstd::prelude::*;
use vstd::wrapping::u128_specs::*;

verus! {

pub const LEMMA_MAX_ROWS: usize = 2_000_000;
pub const K1: usize = 32;
pub const K2: usize = 8;
pub const DENSE: usize = 256;

pub struct Cols {
    pub n: usize,
    pub k: Vec<u32>,
    pub k2: Vec<u32>,
    pub amount: Vec<u64>,
}

impl Cols {
    #[inline(always)]
    #[verifier::external_body]
    pub exec fn key_exec(&self, i: usize) -> (res: u32)
        requires
            i < self.n,
        ensures
            res == self.k[i as int],
    {
        self.k[i]
    }

    #[inline(always)]
    #[verifier::external_body]
    pub exec fn key2_exec(&self, i: usize) -> (res: u32)
        requires
            i < self.n,
        ensures
            res == self.k2[i as int],
    {
        self.k2[i]
    }

    pub open spec fn get_amount(self, i: int) -> u64 {
        self.amount[i as int]
    }

    #[inline(always)]
    #[verifier::external_body]
    pub exec fn get_amount_exec(&self, i: usize) -> (res: u64)
        requires
            i < self.n,
        ensures
            res == self.get_amount(i as int),
    {
        self.amount[i]
    }
}

pub struct Groups {
    pub seen: Vec<bool>,
    pub vals: Vec<u128>,
    pub oa: Vec<u32>,
    pub ob: Vec<u32>,
    pub ov: Vec<u128>,
}

pub open spec fn slot_key(i: int) -> (u32, u32) {
    ((i / (K2 as int)) as u32, (i % (K2 as int)) as u32)
}

pub open spec fn bit() -> u128 {
    1u128 << 127
}

pub open spec fn mask() -> u128 {
    (bit() - 1) as u128
}

pub open spec fn word_low(w: u128) -> u128 {
    w & mask()
}

pub open spec fn word_seen(w: u128) -> bool {
    (w & bit()) != 0
}

pub open spec fn seen_seq(words: Seq<u128>) -> Seq<bool> {
    Seq::new(words.len(), |i: int| word_seen(words[i]))
}

pub open spec fn val_seq(words: Seq<u128>) -> Seq<u128> {
    Seq::new(words.len(), |i: int| word_low(words[i]))
}

pub open spec fn limb(lo: u64, hi: u64) -> u128 {
    ((hi as u128) << 64) | (lo as u128)
}

pub open spec fn pack_word(lo: u64, hi: u64, seen: u8) -> u128 {
    if seen != 0 {
        limb(lo, hi) | bit()
    } else {
        limb(lo, hi)
    }
}

pub open spec fn words_of(lo: Seq<u64>, hi: Seq<u64>, seen: Seq<u8>) -> Seq<u128> {
    Seq::new(lo.len(), |i: int| pack_word(lo[i], hi[i], seen[i]))
}

pub open spec fn valid_cols(cols: &Cols) -> bool {
    &&& cols.n <= LEMMA_MAX_ROWS
    &&& cols.k.len() == cols.n
    &&& cols.k2.len() == cols.n
    &&& cols.amount.len() == cols.n
}

pub open spec fn method_spec_helper(cols: &Cols, k: int) -> Map<(u32, u32), u128>
    recommends
        0 <= k && k <= cols.n,
        valid_cols(cols),
    decreases cols.n - k,
{
    if k < cols.n {
        let tail = method_spec_helper(cols, k + 1);
        let key = (cols.k[k as int], cols.k2[k as int]);
        let prev = if tail.contains_key(key) { tail[key] } else { 0u128 };
        tail.insert(key, (prev as int + ((cols.get_amount(k) as int)) as u64 as int) as u128)
    } else {
        Map::empty()
    }
}

pub open spec fn method_spec(cols: &Cols) -> Map<(u32, u32), u128>
    recommends
        valid_cols(cols),
{
    method_spec_helper(cols, 0)
}

pub open spec fn dense_map(seen: Seq<bool>, vals: Seq<u128>, i: int) -> Map<(u32, u32), u128>
    recommends
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        let tail = dense_map(seen, vals, i + 1);
        if seen[i] {
            tail.insert(slot_key(i), vals[i])
        } else {
            tail
        }
    } else {
        Map::empty()
    }
}

pub open spec fn over_map(a: Seq<u32>, b: Seq<u32>, v: Seq<u128>, n: int) -> Map<(u32, u32), u128>
    recommends
        a.len() == b.len(),
        b.len() == v.len(),
        0 <= n <= a.len(),
    decreases n,
{
    if n > 0 {
        over_map(a, b, v, n - 1).insert((a[n - 1], b[n - 1]), v[n - 1])
    } else {
        Map::empty()
    }
}

pub open spec fn latest(a: Seq<u32>, b: Seq<u32>, v: Seq<u128>, ka: u32, kb: u32, n: int) -> u128
    recommends
        a.len() == b.len(),
        b.len() == v.len(),
        0 <= n <= a.len(),
    decreases n,
{
    if n > 0 {
        if a[n - 1] == ka && b[n - 1] == kb {
            v[n - 1]
        } else {
            latest(a, b, v, ka, kb, n - 1)
        }
    } else {
        0
    }
}

pub open spec fn group_view(
    seen: Seq<bool>,
    vals: Seq<u128>,
    a: Seq<u32>,
    b: Seq<u32>,
    v: Seq<u128>,
) -> Map<(u32, u32), u128> {
    dense_map(seen, vals, 0).union_prefer_right(over_map(a, b, v, a.len() as int))
}

proof fn lemma_rows_fit()
    ensures
        (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX,
{
    assert((LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX) by (compute_only);
}

proof fn lemma_dense_empty(seen: Seq<bool>, vals: Seq<u128>, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        forall|t: int| i <= t < DENSE as int ==> !seen[t],
    ensures
        dense_map(seen, vals, i) =~= Map::<(u32, u32), u128>::empty(),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_empty(seen, vals, i + 1);
        assert(!seen[i]);
    }
}

proof fn lemma_dense_get(seen: Seq<bool>, vals: Seq<u128>, key: int, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        0 <= key < DENSE as int,
        i <= key,
        seen[key],
    ensures
        dense_map(seen, vals, i).contains_key(slot_key(key)),
        dense_map(seen, vals, i)[slot_key(key)] == vals[key],
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        if i == key {
            assert(seen[i]);
        } else {
            lemma_dense_get(seen, vals, key, i + 1);
        }
    }
}

proof fn lemma_dense_absent(seen: Seq<bool>, vals: Seq<u128>, key: int, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        0 <= key < DENSE as int,
        !seen[key],
    ensures
        !dense_map(seen, vals, i).contains_key(slot_key(key)),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_absent(seen, vals, key, i + 1);
    }
}

proof fn lemma_slot(ka: u32, kb: u32)
    requires
        ka < K1 as u32,
        kb < K2 as u32,
    ensures
        0 <= (ka as int) * (K2 as int) + (kb as int) < DENSE as int,
        slot_key((ka as int) * (K2 as int) + (kb as int)) == (ka, kb),
{
    let i = (ka as int) * (K2 as int) + (kb as int);
    assert(i / (K2 as int) == ka as int) by (nonlinear_arith)
        requires
            kb < K2 as u32,
            i == (ka as int) * (K2 as int) + (kb as int),
            K2 == 8,
    {
    };
    assert(i % (K2 as int) == kb as int) by (nonlinear_arith)
        requires
            kb < K2 as u32,
            i == (ka as int) * (K2 as int) + (kb as int),
            K2 == 8,
    {
    };
}

proof fn lemma_dense_outside(seen: Seq<bool>, vals: Seq<u128>, ka: u32, kb: u32, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        ka >= K1 as u32 || kb >= K2 as u32,
    ensures
        !dense_map(seen, vals, i).contains_key((ka, kb)),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_outside(seen, vals, ka, kb, i + 1);
        assert(slot_key(i).0 < K1 as u32 || slot_key(i).1 < K2 as u32);
    }
}

proof fn lemma_dense_set(seen: Seq<bool>, vals: Seq<u128>, key: int, next: u128, i: int)
    requires
        seen.len() == DENSE as int,
        vals.len() == DENSE as int,
        0 <= i <= DENSE as int,
        0 <= key < DENSE as int,
    ensures
        (i > key ==> dense_map(seen.update(key, true), vals.update(key, next), i)
            == dense_map(seen, vals, i)) && (i <= key ==> dense_map(
            seen.update(key, true),
            vals.update(key, next),
            i,
        ) == dense_map(seen, vals, i).insert(slot_key(key), next)),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_set(seen, vals, key, next, i + 1);
        let seen2 = seen.update(key, true);
        let vals2 = vals.update(key, next);
        let tail = dense_map(seen, vals, i + 1);
        let tail2 = dense_map(seen2, vals2, i + 1);
        if i > key {
            assert(seen2[i] == seen[i]);
            assert(vals2[i] == vals[i]);
            assert(tail2 == tail);
        } else if i == key {
            assert(tail2 == tail);
            assert(seen2[i]);
            assert(vals2[i] == next);
            assert(dense_map(seen2, vals2, i) == tail.insert(slot_key(i), next));
            if seen[i] {
                assert(dense_map(seen, vals, i) == tail.insert(slot_key(i), vals[i]));
                assert(tail.insert(slot_key(i), vals[i]).insert(slot_key(key), next) == tail.insert(
                    slot_key(key),
                    next,
                ));
            } else {
                assert(dense_map(seen, vals, i) == tail);
            }
        } else {
            assert(tail2 == tail.insert(slot_key(key), next));
            assert(seen2[i] == seen[i]);
            assert(vals2[i] == vals[i]);
            if seen[i] {
                assert(dense_map(seen, vals, i) == tail.insert(slot_key(i), vals[i]));
                assert(dense_map(seen2, vals2, i) == tail2.insert(slot_key(i), vals[i]));
                assert(tail.insert(slot_key(key), next).insert(slot_key(i), vals[i]) == tail.insert(
                    slot_key(i),
                    vals[i],
                ).insert(slot_key(key), next));
            } else {
                assert(dense_map(seen, vals, i) == tail);
                assert(dense_map(seen2, vals2, i) == tail2);
            }
        }
    }
}


proof fn lemma_over_rect(a: Seq<u32>, b: Seq<u32>, v: Seq<u128>, n: int, ka: u32, kb: u32)
    requires
        a.len() == b.len() && b.len() == v.len(),
        0 <= n <= a.len(),
        ka < K1 as u32,
        kb < K2 as u32,
        forall|t: int| 0 <= t < a.len() ==> a[t] >= K1 as u32 || b[t] >= K2 as u32,
    ensures
        !over_map(a, b, v, n).contains_key((ka, kb)),
    decreases n,
{
    if n > 0 {
        lemma_over_rect(a, b, v, n - 1, ka, kb);
    }
}

proof fn lemma_over_same_prefix(
    a: Seq<u32>,
    b: Seq<u32>,
    v: Seq<u128>,
    a0: Seq<u32>,
    b0: Seq<u32>,
    v0: Seq<u128>,
    n: int,
)
    requires
        a0.len() == b0.len() && b0.len() == v0.len(),
        a.len() == b.len() && b.len() == v.len(),
        0 <= n <= a0.len(),
        n <= a.len(),
        forall|t: int| 0 <= t < n ==> a[t] == a0[t] && b[t] == b0[t] && v[t] == v0[t],
    ensures
        over_map(a, b, v, n) == over_map(a0, b0, v0, n),
    decreases n,
{
    if n > 0 {
        lemma_over_same_prefix(a, b, v, a0, b0, v0, n - 1);
    }
}

proof fn lemma_latest_map(a: Seq<u32>, b: Seq<u32>, v: Seq<u128>, ka: u32, kb: u32, n: int)
    requires
        a.len() == b.len() && b.len() == v.len(),
        0 <= n <= a.len(),
    ensures
        over_map(a, b, v, n).contains_key((ka, kb)) ==> over_map(a, b, v, n)[(ka, kb)] == latest(a, b, v, ka, kb, n),
        !over_map(a, b, v, n).contains_key((ka, kb)) ==> latest(a, b, v, ka, kb, n) == 0,
    decreases n,
{
    if n > 0 {
        lemma_latest_map(a, b, v, ka, kb, n - 1);
    }
}

proof fn lemma_split(w: u128)
    ensures
        (w & mask()) | (w & bit()) == w,
        (w & bit()) == 0 || (w & bit()) == bit(),
        (w & mask()) < bit(),
{
    assert((w & mask()) | (w & bit()) == w) by (bit_vector);
    assert((w & bit()) == 0 || (w & bit()) == bit()) by (bit_vector);
    assert((w & mask()) < bit()) by (bit_vector);
}

proof fn lemma_or_add(x: u128)
    requires
        x < bit(),
    ensures
        (x | bit()) == x + bit(),
        ((x | bit()) & mask()) == x,
        ((x | bit()) & bit()) == bit(),
{
    assert((x | bit()) == x + bit()) by (bit_vector)
        requires
            x < bit(),
    ;
    assert(((x | bit()) & mask()) == x) by (bit_vector)
        requires
            x < bit(),
    ;
    assert(((x | bit()) & bit()) == bit()) by (bit_vector)
        requires
            x < bit(),
    ;
}

proof fn lemma_mask_idx(ka: u32, kb: u32)
    ensures
        (ka & 31) as int <= 31,
        (kb & 7) as int <= 7,
        ka < 32 ==> (ka & 31) == ka,
        kb < 8 ==> (kb & 7) == kb,
{
    assert((ka & 31) <= 31) by (bit_vector);
    assert((kb & 7) <= 7) by (bit_vector);
    assert(ka < 32 ==> (ka & 31) == ka) by (bit_vector);
    assert(kb < 8 ==> (kb & 7) == kb) by (bit_vector);
}

proof fn lemma_idx_bound(ka: u32, kb: u32)
    ensures
        ((ka & 31) as int) * 8 + ((kb & 7) as int) < 256,
{
    lemma_mask_idx(ka, kb);
    assert(((ka & 31) as int) * 8 <= 31 * 8) by (nonlinear_arith)
        requires
            (ka & 31) as int <= 31,
    {
    };
    assert(((ka & 31) as int) * 8 + ((kb & 7) as int) <= 248 + 7);
}

proof fn lemma_pack(w: u128, add: u128)
    requires
        add < bit(),
        (w & mask()) + add < bit(),
    ensures
        ((wrapping_add(w, add) | bit()) & mask()) == (w & mask()) + add,
        ((wrapping_add(w, add) | bit()) & bit()) == bit(),
{
    lemma_split(w);
    let low = w & mask();
    let flag = w & bit();
    assert(w == low | flag);
    if flag == 0 {
        assert((low | 0) == low) by (bit_vector);
        assert(w == low);
        assert((w as int) + (add as int) <= u128::MAX as int) by (nonlinear_arith)
            requires
                (w as int) + (add as int) < bit() as int,
                bit() as int <= u128::MAX as int,
        {
        };
        assert(wrapping_add(w, add) == (w + add) as u128);
        let x = (w + add) as u128;
        lemma_or_add(x);
    } else {
        assert(flag == bit());
        assert((low | flag) == low + bit()) by (bit_vector)
            requires
                low < bit(),
                flag == bit(),
        ;
        assert(w == low + bit());
        let sum = (low as int) + (add as int) + (bit() as int);
        assert(sum == (w as int) + (add as int));
        assert(sum < (bit() as int) + (bit() as int)) by (nonlinear_arith)
            requires
                (low as int) + (add as int) < bit() as int,
                sum == (low as int) + (add as int) + (bit() as int),
        {
        };
        assert((bit() as int) + (bit() as int) == (u128::MAX as int) + 1) by (compute_only);
        assert(sum <= u128::MAX as int);
        assert(wrapping_add(w, add) == sum as u128);
        let x = (low + add) as u128;
        assert(x < bit());
        lemma_or_add(x);
        assert((x as int) + (bit() as int) == sum);
        assert(wrapping_add(w, add) == (x | bit()));
        assert((((x | bit()) | bit()) & mask()) == x) by (bit_vector)
            requires
                x < bit(),
        ;
        assert((((x | bit()) | bit()) & bit()) == bit()) by (bit_vector)
            requires
                x < bit(),
        ;
    }
}

proof fn lemma_rows_bit()
    ensures
        (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) < bit(),
{
    assert((LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) < bit()) by (compute_only);
}

proof fn lemma_zero_word()
    ensures
        word_seen(0) == false,
        word_low(0) == 0,
{
    assert((0u128 & bit()) == 0) by (bit_vector);
    assert((0u128 & mask()) == 0) by (bit_vector);
}

proof fn lemma_seqs_set(words: Seq<u128>, idx: int, nextw: u128)
    requires
        words.len() == DENSE as int,
        0 <= idx < DENSE as int,
    ensures
        seen_seq(words.update(idx, nextw)) =~= seen_seq(words).update(idx, word_seen(nextw)),
        val_seq(words.update(idx, nextw)) =~= val_seq(words).update(idx, word_low(nextw)),
{
    let w2 = words.update(idx, nextw);
    assert forall|t: int|
        0 <= t < DENSE as int implies seen_seq(w2)[t] == seen_seq(words).update(idx, word_seen(nextw))[t]
            && val_seq(w2)[t] == val_seq(words).update(idx, word_low(nextw))[t] by {
        if t == idx {
            assert(w2[t] == nextw);
        } else {
            assert(w2[t] == words[t]);
        }
    };
    assert(seen_seq(w2) =~= seen_seq(words).update(idx, word_seen(nextw)));
    assert(val_seq(w2) =~= val_seq(words).update(idx, word_low(nextw)));
}

proof fn lemma_dense_ext(
    s1: Seq<bool>,
    v1: Seq<u128>,
    s2: Seq<bool>,
    v2: Seq<u128>,
    i: int,
)
    requires
        s1.len() == DENSE as int,
        v1.len() == DENSE as int,
        s2 =~= s1,
        v2 =~= v1,
        0 <= i <= DENSE as int,
    ensures
        dense_map(s1, v1, i) == dense_map(s2, v2, i),
    decreases DENSE as int - i,
{
    if i < DENSE as int {
        lemma_dense_ext(s1, v1, s2, v2, i + 1);
    }
}

proof fn lemma_mul0(x: u128)
    ensures
        wrapping_mul(x, 0) == 0,
{
    assert(wrapping_mul(x, 0) == 0);
}

proof fn lemma_mul1(x: u128)
    ensures
        wrapping_mul(x, 1) == x,
{
    assert(wrapping_mul(x, 1) == x);
}

proof fn lemma_limb_split(lo: u64, hi: u64)
    ensures
        limb(lo, hi) as int == (hi as int) * 0x1_0000_0000_0000_0000 + (lo as int),
{
    assert((lo as u128) < 0x1_0000_0000_0000_0000) by (bit_vector);
    assert(((hi as u128) << 64) == (hi as u128) * 0x1_0000_0000_0000_0000) by (bit_vector);
    assert((((hi as u128) << 64) | (lo as u128)) == ((hi as u128) << 64) + (lo as u128)) by (bit_vector);
}

proof fn lemma_limb_add(lo: u64, hi: u64, add: u64)
    requires
        hi < u64::MAX,
        (limb(lo, hi) as int) + (add as int) < (bit() as int),
    ensures
        ({
            let v = vstd::wrapping::u64_specs::wrapping_add(lo, add);
            let carried = (lo as int) + (add as int) > u64::MAX as int;
            let nh = if carried {
                (hi + 1) as u64
            } else {
                hi
            };
            (v < lo) == carried && (limb(v, nh) as int) == (limb(lo, hi) as int) + (add as int)
        }),
{
    lemma_limb_split(lo, hi);
    let sum = (lo as int) + (add as int);
    let v = vstd::wrapping::u64_specs::wrapping_add(lo, add);
    if sum > u64::MAX as int {
        assert(v == (sum - 0x1_0000_0000_0000_0000) as u64);
        assert((sum - 0x1_0000_0000_0000_0000) < (lo as int));
        assert(v < lo);
        let nh = (hi + 1) as u64;
        lemma_limb_split(v, nh);
        assert((limb(v, nh) as int) == (nh as int) * 0x1_0000_0000_0000_0000 + (v as int));
        assert((nh as int) * 0x1_0000_0000_0000_0000 + (v as int) == (limb(lo, hi) as int) + (add as int));
    } else {
        assert(v == sum as u64);
        assert(sum >= lo as int);
        assert(!(v < lo));
        lemma_limb_split(v, hi);
        assert((limb(v, hi) as int) == (limb(lo, hi) as int) + (add as int));
    }
}

proof fn lemma_pack_low(lo: u64, hi: u64, seen: u8)
    requires
        (limb(lo, hi) as int) < (bit() as int),
    ensures
        word_low(pack_word(lo, hi, seen)) == limb(lo, hi),
        word_seen(pack_word(lo, hi, seen)) == (seen != 0),
{
    let v = limb(lo, hi);
    if seen == 0 {
        assert(pack_word(lo, hi, seen) == v);
        assert((v & mask()) == v) by (bit_vector)
            requires
                (v as int) < (bit() as int),
        ;
        assert((v & bit()) == 0) by (bit_vector)
            requires
                (v as int) < (bit() as int),
        ;
    } else {
        lemma_or_add(v);
        assert(pack_word(lo, hi, seen) == (v | bit()));
    }
}

proof fn lemma_update_id(s: Seq<u128>, i: int)
    requires
        0 <= i < s.len(),
    ensures
        s.update(i, s[i]) =~= s,
{
    assert forall|t: int| 0 <= t < s.len() implies s.update(i, s[i])[t] == s[t] by {
        if t != i {
            assert(s.update(i, s[i])[t] == s[t]);
        }
    };
}

proof fn lemma_latest_bound(a: Seq<u32>, b: Seq<u32>, v: Seq<u128>, ka: u32, kb: u32, n: int, bound: int)
    requires
        a.len() == b.len() && b.len() == v.len(),
        0 <= n <= a.len(),
        0 <= bound,
        forall|t: int| 0 <= t < v.len() ==> v[t] <= bound,
    ensures
        latest(a, b, v, ka, kb, n) <= bound,
    decreases n,
{
    if n > 0 {
        if a[n - 1] == ka && b[n - 1] == kb {
            assert(latest(a, b, v, ka, kb, n) == v[n - 1]);
            assert(v[n - 1] <= bound);
        } else {
            lemma_latest_bound(a, b, v, ka, kb, n - 1, bound);
            assert(latest(a, b, v, ka, kb, n) == latest(a, b, v, ka, kb, n - 1));
        }
    }
}

#[cold]
#[inline(never)]
fn find_latest(oa: &Vec<u32>, ob: &Vec<u32>, ov: &Vec<u128>, ka: u32, kb: u32) -> (res: u128)
    requires
        oa.len() == ob.len() && ob.len() == ov.len(),
    ensures
        res == latest(oa@, ob@, ov@, ka, kb, oa@.len() as int),
{
    let mut p: usize = oa.len();
    let mut prev: u128 = 0;
    let mut found = false;
    while p > 0
        invariant
            p <= oa.len(),
            oa.len() == ob.len() && ob.len() == ov.len(),
            p as int <= oa@.len(),
            !found ==> prev == 0,
            found ==> prev == latest(oa@, ob@, ov@, ka, kb, oa@.len() as int),
            !found ==> latest(oa@, ob@, ov@, ka, kb, oa@.len() as int) == latest(oa@, ob@, ov@, ka, kb, p as int),
        decreases p,
    {
        let ghost p_old = p as int;
        p = p - 1;
        if !found && oa[p] == ka && ob[p] == kb {
            proof {
                assert(latest(oa@, ob@, ov@, ka, kb, p_old) == ov@[p as int]);
                assert(latest(oa@, ob@, ov@, ka, kb, oa@.len() as int) == latest(oa@, ob@, ov@, ka, kb, p_old));
            }
            prev = ov[p];
            found = true;
        } else if !found {
            proof {
                assert(latest(oa@, ob@, ov@, ka, kb, p_old) == latest(oa@, ob@, ov@, ka, kb, p as int));
            }
        }
    }
    assert(p == 0);
    assert(latest(oa@, ob@, ov@, ka, kb, 0) == 0);
    if found {
        assert(prev == latest(oa@, ob@, ov@, ka, kb, oa@.len() as int));
    } else {
        assert(latest(oa@, ob@, ov@, ka, kb, oa@.len() as int) == 0);
        assert(prev == 0);
    }
    assert(prev == latest(oa@, ob@, ov@, ka, kb, oa@.len() as int));
    prev
}

#[cold]
#[inline(never)]
fn record_overflow(
    oa: &mut Vec<u32>,
    ob: &mut Vec<u32>,
    ov: &mut Vec<u128>,
    ka: u32,
    kb: u32,
    amount: u64,
)
    requires
        oa.len() == ob.len() && ob.len() == ov.len(),
        (latest(oa@, ob@, ov@, ka, kb, oa@.len() as int) as int) + (amount as int) <= u128::MAX as int,
    ensures
        final(oa)@ == old(oa)@.push(ka),
        final(ob)@ == old(ob)@.push(kb),
        final(ov)@ == old(ov)@.push((latest(old(oa)@, old(ob)@, old(ov)@, ka, kb, old(oa)@.len() as int) + (amount as u128)) as u128),
{
    let prev = find_latest(oa, ob, ov, ka, kb);
    proof {
        assert(prev == latest(oa@, ob@, ov@, ka, kb, oa@.len() as int));
        assert((prev as int) + (amount as int) <= u128::MAX as int);
    }
    let next = prev + (amount as u128);
    oa.push(ka);
    ob.push(kb);
    ov.push(next);
}

#[inline(always)]
fn apply_row(
    cols: &Cols,
    lo: &mut [u64; 256],
    hi: &mut [u64; 256],
    seen_b: &mut [u8; 256],
    oa: &mut Vec<u32>,
    ob: &mut Vec<u32>,
    ov: &mut Vec<u128>,
    i: usize,
)
    requires
        i < cols.n,
        valid_cols(cols),
        lo@.len() == 256,
        hi@.len() == 256,
        seen_b@.len() == 256,
        oa.len() == ob.len() && ob.len() == ov.len(),
        group_view(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), oa@, ob@, ov@) == method_spec_helper(cols, (i + 1) as int),
        forall|t: int| 0 <= t < oa.len() ==> oa@[t] >= K1 as u32 || ob@[t] >= K2 as u32,
        forall|t: int|
            0 <= t < DENSE as int && !word_seen(words_of(lo@, hi@, seen_b@)[t]) ==> word_low(words_of(lo@, hi@, seen_b@)[t]) == 0,
        forall|t: int|
            0 <= t < DENSE as int ==> word_low(words_of(lo@, hi@, seen_b@)[t]) <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
        forall|t: int|
            0 <= t < DENSE as int ==> (limb(lo@[t], hi@[t]) as int) < (bit() as int),
        forall|t: int|
            0 <= t < ov.len() ==> ov@[t] <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
    ensures
        final(lo)@.len() == 256,
        final(hi)@.len() == 256,
        final(seen_b)@.len() == 256,
        final(oa).len() == final(ob).len() && final(ob).len() == final(ov).len(),
        group_view(seen_seq(words_of(final(lo)@, final(hi)@, final(seen_b)@)), val_seq(words_of(final(lo)@, final(hi)@, final(seen_b)@)), final(oa)@, final(ob)@, final(ov)@) == method_spec_helper(cols, i as int),
        forall|t: int| 0 <= t < final(oa).len() ==> final(oa)@[t] >= K1 as u32 || final(ob)@[t] >= K2 as u32,
        forall|t: int|
            0 <= t < DENSE as int && !word_seen(words_of(final(lo)@, final(hi)@, final(seen_b)@)[t]) ==> word_low(words_of(final(lo)@, final(hi)@, final(seen_b)@)[t]) == 0,
        forall|t: int|
            0 <= t < DENSE as int ==> word_low(words_of(final(lo)@, final(hi)@, final(seen_b)@)[t]) <= ((cols.n - i) as u128) * (u64::MAX as u128),
        forall|t: int|
            0 <= t < DENSE as int ==> (limb(final(lo)@[t], final(hi)@[t]) as int) < (bit() as int),
        forall|t: int|
            0 <= t < final(ov).len() ==> final(ov)@[t] <= ((cols.n - i) as u128) * (u64::MAX as u128),
{
        let ghost bound = ((cols.n - (i + 1)) as u128) * (u64::MAX as u128);
        let ka = cols.k[i];
        let kb = cols.k2[i];
        let amount = cols.amount[i];
        let ghost before_words = words_of(lo@, hi@, seen_b@);
        let ghost before_a = oa@;
        let ghost before_b = ob@;
        let ghost before_v = ov@;
        proof {
            lemma_idx_bound(ka, kb);
        }
        let pred: u128 = if ka < K1 as u32 && kb < K2 as u32 {
            1u128
        } else {
            0u128
        };
        let idx_u: u32 = ((ka & 31) * 8) + (kb & 7);
        let idx: usize = (idx_u & 255) as usize;
        proof {
            lemma_idx_bound(ka, kb);
            assert(idx_u < 256);
            assert((idx_u & 255) == idx_u) by (bit_vector)
                requires
                    idx_u < 256,
            ;
            assert(idx == idx_u as usize);
        }
        let old_lo = lo[idx];
        let old_hi = hi[idx];
        let old_seen = seen_b[idx];
        let ghost lo0 = lo@;
        let ghost hi0 = hi@;
        let ghost seen0 = seen_b@;
        proof {
            lemma_idx_bound(ka, kb);
            assert(idx < 256);
            assert((limb(old_lo, old_hi) as int) < (bit() as int));
            lemma_limb_split(old_lo, old_hi);
            assert((bit() as int) == 0x8000_0000_0000_0000 * 0x1_0000_0000_0000_0000) by (compute_only);
            assert((old_hi as int) * 0x1_0000_0000_0000_0000 <= (limb(old_lo, old_hi) as int));
            assert(old_hi < 0x8000_0000_0000_0000) by (nonlinear_arith)
                requires
                    (old_hi as int) * 0x1_0000_0000_0000_0000 <= (limb(old_lo, old_hi) as int),
                    (limb(old_lo, old_hi) as int) < 0x8000_0000_0000_0000 * 0x1_0000_0000_0000_0000,
                    (old_hi as int) >= 0,
            {
            };
            assert(old_hi < u64::MAX);
            assert(before_words[idx as int] == pack_word(old_lo, old_hi, old_seen));
        }
        let add64: u64 = if pred == 1 { amount } else { 0 };
        let new_lo = old_lo.wrapping_add(add64);
        lo[idx] = new_lo;
        let carried = new_lo < old_lo;
        let new_hi = if carried {
            let bumped = old_hi.wrapping_add(1);
            hi[idx] = bumped;
            bumped
        } else {
            old_hi
        };
        if pred == 1 {
            seen_b[idx] = 1;
        }
        let ghost cur = before_words[idx as int];
        let ghost add: u128 = if pred == 1 { amount as u128 } else { 0 };
        let ghost packed = if pred == 1 { wrapping_add(cur, add) | bit() } else { cur };
        if pred == 0 {
            proof {
                assert(ka >= K1 as u32 || kb >= K2 as u32);
                assert((0u128 << 127) == 0) by (bit_vector);
                assert((pred << 127) == 0);
                lemma_mul0(amount as u128);
                assert(add == 0);
                assert(wrapping_add(cur, 0) == cur);
                assert((cur | 0) == cur) by (bit_vector);
                assert(packed == cur);
                assert(cur == before_words[idx as int]);
                lemma_update_id(before_words, idx as int);
                assert(words_of(lo@, hi@, seen_b@) =~= before_words);
                assert(seen_seq(words_of(lo@, hi@, seen_b@)) =~= seen_seq(before_words));
                assert(val_seq(words_of(lo@, hi@, seen_b@)) =~= val_seq(before_words));
                lemma_dense_ext(
                    seen_seq(before_words),
                    val_seq(before_words),
                    seen_seq(words_of(lo@, hi@, seen_b@)),
                    val_seq(words_of(lo@, hi@, seen_b@)),
                    0,
                );
            }
            proof {
                assert(0 <= bound);
                lemma_latest_bound(before_a, before_b, before_v, ka, kb, before_a.len() as int, bound);
            }
            let ghost prev = latest(before_a, before_b, before_v, ka, kb, before_a.len() as int);
            assert(prev <= bound);
            assert(bound == ((cols.n - (i + 1)) as u128) * (u64::MAX as u128));
            assert(amount as u128 <= u64::MAX as u128);
            assert(prev + (amount as u128) <= ((cols.n - i) as u128) * (u64::MAX as u128)) by (nonlinear_arith)
                requires
                    prev <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
                    amount as u128 <= u64::MAX as u128,
                    (cols.n - i) as u128 == (cols.n - (i + 1)) as u128 + 1,
            {
            };
            assert(((cols.n - i) as u128) * (u64::MAX as u128) <= u128::MAX) by (nonlinear_arith)
                requires
                    cols.n <= LEMMA_MAX_ROWS,
                    i < cols.n,
                    (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX,
            {
            };
            let ghost next = (prev + (amount as u128)) as u128;
            assert((prev as int) + (amount as int) <= u128::MAX as int);
            record_overflow(oa, ob, ov, ka, kb, amount);
            assert(oa@ == before_a.push(ka));
            assert(ob@ == before_b.push(kb));
            assert(ov@ == before_v.push(next));
            proof {
                lemma_over_same_prefix(oa@, ob@, ov@, before_a, before_b, before_v, before_a.len() as int);
                lemma_latest_map(before_a, before_b, before_v, ka, kb, before_a.len() as int);
                lemma_dense_outside(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), ka, kb, 0);
            }
            assert(over_map(oa@, ob@, ov@, (before_a.len() as int) + 1) == over_map(oa@, ob@, ov@, before_a.len() as int).insert((ka, kb), next));
            assert(over_map(oa@, ob@, ov@, oa@.len() as int) == over_map(before_a, before_b, before_v, before_a.len() as int).insert((ka, kb), next));
            assert(group_view(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), oa@, ob@, ov@) == method_spec_helper(cols, i as int));
            proof {
                assert forall|t: int|
                    0 <= t < DENSE as int implies word_low(words_of(lo@, hi@, seen_b@)[t]) <= ((cols.n - i) as u128) * (u64::MAX as u128)
                        && (!word_seen(words_of(lo@, hi@, seen_b@)[t]) ==> word_low(words_of(lo@, hi@, seen_b@)[t]) == 0) by {
                    assert(words_of(lo@, hi@, seen_b@)[t] == before_words[t]);
                    assert(word_low(before_words[t]) <= bound);
                    assert(bound <= ((cols.n - i) as u128) * (u64::MAX as u128)) by (nonlinear_arith)
                        requires
                            bound == ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
                            (cols.n - i) as u128 == (cols.n - (i + 1)) as u128 + 1,
                    {
                    };
                };
            }
        } else {
            proof {
                lemma_mask_idx(ka, kb);
                lemma_slot(ka, kb);
                assert((1u128 << 127) == bit());
                assert((pred << 127) == bit());
                lemma_mul1(amount as u128);
                assert(add == amount as u128);
                assert((ka & 31) == ka);
                assert((kb & 7) == kb);
                assert(idx as int == (ka as int) * (K2 as int) + (kb as int));
                assert(before_words[idx as int] == pack_word(old_lo, old_hi, old_seen));
                let ghost gseen = seen_seq(before_words);
                let ghost gvals = val_seq(before_words);
                let ghost prev = word_low(cur);
                if word_seen(cur) {
                    lemma_dense_get(gseen, gvals, idx as int, 0);
                } else {
                    lemma_dense_absent(gseen, gvals, idx as int, 0);
                    assert(prev == 0);
                }
                lemma_over_rect(before_a, before_b, before_v, before_a.len() as int, ka, kb);
                lemma_rows_fit();
                lemma_rows_bit();
                assert(prev <= bound);
                assert(bound == ((cols.n - (i + 1)) as u128) * (u64::MAX as u128));
                assert(amount as u128 <= u64::MAX as u128);
                assert(prev + (amount as u128) <= ((cols.n - i) as u128) * (u64::MAX as u128)) by (nonlinear_arith)
                    requires
                        prev <= ((cols.n - (i + 1)) as u128) * (u64::MAX as u128),
                        amount as u128 <= u64::MAX as u128,
                        (cols.n - i) as u128 == (cols.n - (i + 1)) as u128 + 1,
                {
                };
                assert(((cols.n - i) as u128) * (u64::MAX as u128) <= u128::MAX) by (nonlinear_arith)
                    requires
                        cols.n <= LEMMA_MAX_ROWS,
                        i < cols.n,
                        (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) <= u128::MAX,
                {
                };
                assert(((cols.n - i) as u128) * (u64::MAX as u128) < bit()) by (nonlinear_arith)
                    requires
                        cols.n <= LEMMA_MAX_ROWS,
                        i < cols.n,
                        (LEMMA_MAX_ROWS as u128) * (u64::MAX as u128) < bit(),
                {
                };
                let ghost next = (prev + (amount as u128)) as u128;
                assert(word_low(cur) + add < bit());
                lemma_pack_low(old_lo, old_hi, old_seen);
                assert(word_low(cur) == limb(old_lo, old_hi));
                assert((limb(old_lo, old_hi) as int) + (amount as int) < (bit() as int));
                lemma_limb_add(old_lo, old_hi, amount);
                assert((limb(new_lo, new_hi) as int) == (limb(old_lo, old_hi) as int) + (amount as int));
                lemma_pack(cur, add);
                assert(word_low(packed) == limb(new_lo, new_hi));
                lemma_split(packed);
                assert((packed & bit()) == bit());
                assert(packed == (word_low(packed) | bit()));
                assert(packed == (limb(new_lo, new_hi) | bit()));
                assert(pack_word(new_lo, new_hi, 1) == (limb(new_lo, new_hi) | bit()));
                assert(seen_b@[idx as int] == 1);
                assert(lo@[idx as int] == new_lo && hi@[idx as int] == new_hi);
                assert forall|t: int|
                    0 <= t < DENSE as int implies words_of(lo@, hi@, seen_b@)[t] == before_words.update(idx as int, packed)[t] by {
                    if t == idx as int {
                        assert(words_of(lo@, hi@, seen_b@)[t] == pack_word(new_lo, new_hi, 1));
                        assert(before_words.update(idx as int, packed)[t] == packed);
                    } else {
                        assert(lo@[t] == lo0[t]);
                        assert(hi@[t] == hi0[t]);
                        assert(seen_b@[t] == seen0[t]);
                        assert(before_words[t] == pack_word(lo0[t], hi0[t], seen0[t]));
                    }
                };
                assert(words_of(lo@, hi@, seen_b@) =~= before_words.update(idx as int, packed));
                assert(word_low(packed) == next);
                assert(word_seen(packed));
                lemma_seqs_set(before_words, idx as int, packed);
                assert(seen_seq(words_of(lo@, hi@, seen_b@)) =~= gseen.update(idx as int, true));
                assert(val_seq(words_of(lo@, hi@, seen_b@)) =~= gvals.update(idx as int, next));
                lemma_dense_set(gseen, gvals, idx as int, next, 0);
                lemma_dense_ext(
                    seen_seq(words_of(lo@, hi@, seen_b@)),
                    val_seq(words_of(lo@, hi@, seen_b@)),
                    gseen.update(idx as int, true),
                    gvals.update(idx as int, next),
                    0,
                );
                assert(dense_map(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), 0) == dense_map(gseen, gvals, 0).insert(slot_key(idx as int), next));
                assert(group_view(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), oa@, ob@, ov@) == method_spec_helper(cols, i as int));
                assert forall|t: int|
                    0 <= t < DENSE as int implies (!word_seen(words_of(lo@, hi@, seen_b@)[t]) ==> word_low(words_of(lo@, hi@, seen_b@)[t]) == 0)
                        && word_low(words_of(lo@, hi@, seen_b@)[t]) <= ((cols.n - i) as u128) * (u64::MAX as u128) by {
                    if t == idx as int {
                        assert(word_seen(words_of(lo@, hi@, seen_b@)[t]));
                        assert(word_low(words_of(lo@, hi@, seen_b@)[t]) == next);
                    } else {
                        assert(words_of(lo@, hi@, seen_b@)[t] == before_words[t]);
                        assert(word_low(before_words[t]) <= bound);
                    }
                };
            }
        }
}

pub exec fn run_query(cols: &Cols) -> (res: Groups)
    requires
        valid_cols(cols),
    ensures
        res.seen.len() == DENSE,
        res.vals.len() == DENSE,
        group_view(res.seen@, res.vals@, res.oa@, res.ob@, res.ov@) == method_spec(cols),
{
    let mut lo: [u64; 256] = [0u64; 256];
    let mut hi: [u64; 256] = [0u64; 256];
    let mut seen_b: [u8; 256] = [0u8; 256];
    proof {
        lemma_zero_word();
        assert forall|t: int|
            0 <= t < DENSE as int implies words_of(lo@, hi@, seen_b@)[t] == 0 && !seen_seq(words_of(lo@, hi@, seen_b@))[t]
                && val_seq(words_of(lo@, hi@, seen_b@))[t] == 0 by {
            assert(lo@[t] == 0 && hi@[t] == 0 && seen_b@[t] == 0);
            assert(limb(0, 0) == 0) by (bit_vector);
        };
        lemma_dense_empty(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), 0);
    }
    let mut oa: Vec<u32> = Vec::new();
    let mut ob: Vec<u32> = Vec::new();
    let mut ov: Vec<u128> = Vec::new();
    assert(group_view(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), oa@, ob@, ov@)
        =~= Map::<(u32, u32), u128>::empty());
    proof {
        assert forall|t: int| 0 <= t < DENSE as int implies (limb(lo@[t], hi@[t]) as int) < (bit() as int) by {
            assert(lo@[t] == 0 && hi@[t] == 0);
            assert(limb(0, 0) == 0) by (bit_vector);
            assert(bit() == 1u128 << 127);
            assert((1u128 << 127) > 0) by (bit_vector);
            assert(0 < (bit() as int));
        };
    }
    if cols.k.len() == cols.k2.len() && cols.k.len() == cols.amount.len() {
        assert(cols.k.len() == cols.n);
        let mut i: usize = cols.k.len();
    while i >= 8
        invariant
            i <= cols.n,
            valid_cols(cols),
            lo@.len() == 256,
            hi@.len() == 256,
            seen_b@.len() == 256,
            oa.len() == ob.len() && ob.len() == ov.len(),
            group_view(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), oa@, ob@, ov@) == method_spec_helper(cols, i as int),
            forall|t: int| 0 <= t < oa.len() ==> oa@[t] >= K1 as u32 || ob@[t] >= K2 as u32,
            forall|t: int|
                0 <= t < DENSE as int && !word_seen(words_of(lo@, hi@, seen_b@)[t]) ==> word_low(words_of(lo@, hi@, seen_b@)[t]) == 0,
            forall|t: int|
                0 <= t < DENSE as int ==> word_low(words_of(lo@, hi@, seen_b@)[t]) <= ((cols.n - i) as u128) * (u64::MAX as u128),
            forall|t: int|
                0 <= t < DENSE as int ==> (limb(lo@[t], hi@[t]) as int) < (bit() as int),
            forall|t: int|
                0 <= t < ov.len() ==> ov@[t] <= ((cols.n - i) as u128) * (u64::MAX as u128),
        decreases i,
    {
        apply_row(cols, &mut lo, &mut hi, &mut seen_b, &mut oa, &mut ob, &mut ov, i - 1);
        apply_row(cols, &mut lo, &mut hi, &mut seen_b, &mut oa, &mut ob, &mut ov, i - 2);
        apply_row(cols, &mut lo, &mut hi, &mut seen_b, &mut oa, &mut ob, &mut ov, i - 3);
        apply_row(cols, &mut lo, &mut hi, &mut seen_b, &mut oa, &mut ob, &mut ov, i - 4);
        apply_row(cols, &mut lo, &mut hi, &mut seen_b, &mut oa, &mut ob, &mut ov, i - 5);
        apply_row(cols, &mut lo, &mut hi, &mut seen_b, &mut oa, &mut ob, &mut ov, i - 6);
        apply_row(cols, &mut lo, &mut hi, &mut seen_b, &mut oa, &mut ob, &mut ov, i - 7);
        apply_row(cols, &mut lo, &mut hi, &mut seen_b, &mut oa, &mut ob, &mut ov, i - 8);
        i = i - 8;
    }
    while i > 0
        invariant
            i <= cols.n,
            valid_cols(cols),
            lo@.len() == 256,
            hi@.len() == 256,
            seen_b@.len() == 256,
            oa.len() == ob.len() && ob.len() == ov.len(),
            group_view(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), oa@, ob@, ov@) == method_spec_helper(cols, i as int),
            forall|t: int| 0 <= t < oa.len() ==> oa@[t] >= K1 as u32 || ob@[t] >= K2 as u32,
            forall|t: int|
                0 <= t < DENSE as int && !word_seen(words_of(lo@, hi@, seen_b@)[t]) ==> word_low(words_of(lo@, hi@, seen_b@)[t]) == 0,
            forall|t: int|
                0 <= t < DENSE as int ==> word_low(words_of(lo@, hi@, seen_b@)[t]) <= ((cols.n - i) as u128) * (u64::MAX as u128),
            forall|t: int|
                0 <= t < DENSE as int ==> (limb(lo@[t], hi@[t]) as int) < (bit() as int),
            forall|t: int|
                0 <= t < ov.len() ==> ov@[t] <= ((cols.n - i) as u128) * (u64::MAX as u128),
        decreases i,
    {
        apply_row(cols, &mut lo, &mut hi, &mut seen_b, &mut oa, &mut ob, &mut ov, i - 1);
        i = i - 1;
    }
    } else {
        proof {
            assert(false);
        }
    }
    proof {
        assert((1u128 << 127) > 0) by (bit_vector);
    }
    let low_mask: u128 = (1u128 << 127) - 1;
    proof {
        assert((1u128 << 127) == bit());
        assert(low_mask == mask());
    }
    let mut seen: Vec<bool> = Vec::new();
    let mut vals: Vec<u128> = Vec::new();
    let mut j: usize = 0;
    while j < DENSE
        invariant
            j <= DENSE,
            lo@.len() == 256,
            hi@.len() == 256,
            seen_b@.len() == 256,
            valid_cols(cols),
            seen.len() == j,
            vals.len() == j,
            oa.len() == ob.len() && ob.len() == ov.len(),
            group_view(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), oa@, ob@, ov@) == method_spec(cols),
            low_mask == mask(),
            forall|t: int|
                0 <= t < j as int ==> seen@[t] == word_seen(words_of(lo@, hi@, seen_b@)[t]) && vals@[t] == word_low(words_of(lo@, hi@, seen_b@)[t]),
        decreases DENSE - j,
    {
        let w_lo = lo[j];
        let w_hi = hi[j];
        let w_seen = seen_b[j];
        let w_limb = ((w_hi as u128) << 64) | (w_lo as u128);
        let w = if w_seen != 0 { w_limb | (1u128 << 127) } else { w_limb };
        let ghost j0 = j as int;
        let ghost old_seen = seen@;
        let ghost old_vals = vals@;
        proof {
            assert((1u128 << 127) == bit());
            assert(low_mask == mask());
            assert(((w & bit()) != 0) == word_seen(w));
            assert((w & low_mask) == word_low(w));
        }
        seen.push((w & (1u128 << 127)) != 0);
        vals.push(w & low_mask);
        proof {
            assert(seen@[j0] == word_seen(words_of(lo@, hi@, seen_b@)[j0]));
            assert(vals@[j0] == word_low(words_of(lo@, hi@, seen_b@)[j0]));
            assert forall|t: int|
                0 <= t < j0 + 1 implies seen@[t] == word_seen(words_of(lo@, hi@, seen_b@)[t]) && vals@[t] == word_low(words_of(lo@, hi@, seen_b@)[t]) by {
                if t < j0 {
                    assert(seen@[t] == old_seen[t]);
                    assert(vals@[t] == old_vals[t]);
                }
            };
        }
        j = j + 1;
    }
    proof {
        assert forall|t: int|
            0 <= t < DENSE as int implies seen@[t] == seen_seq(words_of(lo@, hi@, seen_b@))[t] && vals@[t] == val_seq(words_of(lo@, hi@, seen_b@))[t] by {
            assert(seen@[t] == word_seen(words_of(lo@, hi@, seen_b@)[t]));
            assert(vals@[t] == word_low(words_of(lo@, hi@, seen_b@)[t]));
        };
        assert(seen@ =~= seen_seq(words_of(lo@, hi@, seen_b@)));
        assert(vals@ =~= val_seq(words_of(lo@, hi@, seen_b@)));
        lemma_dense_ext(seen@, vals@, seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), 0);
        assert(group_view(seen@, vals@, oa@, ob@, ov@) == group_view(seen_seq(words_of(lo@, hi@, seen_b@)), val_seq(words_of(lo@, hi@, seen_b@)), oa@, ob@, ov@));
    }
    Groups { seen, vals, oa, ob, ov }
}

}

fn main() {
    let n: usize = 2_000_000;
    let mut k = Vec::with_capacity(n);
    let mut k2 = Vec::with_capacity(n);
    let mut amount = Vec::with_capacity(n);
    for i in 0..n {
        k.push((i % 32) as u32);
        k2.push((i % 8) as u32);
        amount.push(((i as u64) * 17) % 1000);
    }
    let cols = Cols { n, k, k2, amount };
    for _ in 0..2 {
        let _ = run_query(&cols);
    }
    let mut samples = Vec::with_capacity(5);
    let mut last = None;
    for _ in 0..5 {
        let t0 = std::time::Instant::now();
        last = Some(run_query(&cols));
        samples.push(t0.elapsed().as_micros());
    }
    samples.sort();
    let groups = last.unwrap();
    let mut shown = 0u32;
    let mut total = 0u128;
    for key in 0..32u32 {
        for key2 in 0..8u32 {
            let idx = (key as usize) * 8 + (key2 as usize);
            if groups.seen[idx] {
                shown += 1;
                total += groups.vals[idx];
            }
        }
    }
    println!("OVERFLOW:{}", groups.oa.len());
    println!("SHOWN:{shown}");
    println!("TOTAL:{total}");
    println!("MEDIAN_US:{}", samples[samples.len() / 2]);
}
