//! Scaffold only — adversarial cases live in `tests/<extern_name>.rs` (one file per TRUSTED extern).
//!
//! Each integration test must include ≥10 diverse cases that try to falsify the Verus
//! `ensures` / documented semantics of that `#[verifier::external_body]` helper.
