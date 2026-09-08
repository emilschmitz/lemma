// === Agent primitives: parallel scan/agg (LEMMA_ENABLE_PARALLEL=1 or LEMMA_FAST_TRUSTEDS=1) ===
//
// Bodies below are serial for Verus verification. At exec time the Rust reference crate
// may parallelize (rayon chunked reduce) with identical wrapping-u64 semantics — see
// agent_primitives/tests/equiv.rs. We are not proving the parallel implementation; we
// trust result == serial_wrapping_spec(...).

pub open spec fn par_sum_u64_spec(vals: Seq<u64>) -> u64 {
    par_sum_u64_fold(vals, 0, 0)
}

pub open spec fn par_sum_u64_fold(vals: Seq<u64>, i: int, acc: u64) -> u64
    decreases vals.len() - i,
{
    if i >= vals.len() {
        acc
    } else {
        par_sum_u64_fold(vals, i + 1, wrapping_add_u64(acc, vals[i]))
    }
}

pub open spec fn par_filter_sum_u64_pair_len(col: Seq<u64>, mask: Seq<bool>) -> int {
    if col.len() < mask.len() {
        col.len()
    } else {
        mask.len()
    }
}

pub open spec fn par_filter_sum_u64_spec(col: Seq<u64>, mask: Seq<bool>) -> u64 {
    par_filter_sum_u64_fold(col, mask, 0, 0)
}

pub open spec fn par_filter_sum_u64_fold(
    col: Seq<u64>,
    mask: Seq<bool>,
    i: int,
    acc: u64,
) -> u64
    decreases par_filter_sum_u64_pair_len(col, mask) - i,
{
    let n = par_filter_sum_u64_pair_len(col, mask);
    if i >= n {
        acc
    } else if mask[i] {
        par_filter_sum_u64_fold(col, mask, i + 1, wrapping_add_u64(acc, col[i]))
    } else {
        par_filter_sum_u64_fold(col, mask, i + 1, acc)
    }
}

#[verifier::external_body]
pub exec fn par_sum_u64(vals: &Vec<u64>) -> (sum: u64)
    ensures sum == par_sum_u64_spec(vals@),
{
    let mut sum: u64 = 0;
    let mut i: usize = 0;
    while i < vals.len() {
        sum = sum.wrapping_add(vals[i]);
        i = i + 1;
    }
    sum
}

#[verifier::external_body]
pub exec fn par_filter_sum_u64(col: &Vec<u64>, mask: &Vec<bool>) -> (sum: u64)
    ensures sum == par_filter_sum_u64_spec(col@, mask@),
{
    let n = if col.len() < mask.len() { col.len() } else { mask.len() };
    let mut sum: u64 = 0;
    let mut i: usize = 0;
    while i < n {
        if mask[i] {
            sum = sum.wrapping_add(col[i]);
        }
        i = i + 1;
    }
    sum
}

// par_probe_sum_u64 / par_probe_sum_u64_multi: Rust-only in lemma_agent_primitives (hash_join.rs).
// Same serial-looking pattern as above if we add Verus externs later.
//
// par_small_card_filter_sum: Rust-only (small_card_agg.rs). Use SmallCardBuckets<N> in verified
// code or a fixed [u64; N] loop; check try_add (false on key >= N) instead of silent drops.
