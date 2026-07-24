// === Agent primitives: parallel scan/agg (requires LEMMA_ENABLE_PARALLEL=1) ===
//
// Bodies below are serial for Verus verification. At exec time the Rust reference crate
// may parallelize (rayon chunked reduce) with identical wrapping-u64 semantics — see
// agent_primitives/tests/equiv.rs. The agent chooses ST vs MT; there is no auto-threshold.

#[verifier::external_body]
pub exec fn par_sum_u64(vals: &Vec<u64>) -> (sum: u64)
    ensures sum <= vals@.len() as u64 * u64::MAX,
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
    ensures col@.len() == mask@.len() ==> sum <= col@.len() as u64 * u64::MAX,
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
