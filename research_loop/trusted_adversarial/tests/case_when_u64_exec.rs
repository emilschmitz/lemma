//! Adversarial tests for TRUSTED `case_when_u64_exec`.
//!
//! Verus contract: `ensures res == case_when_u64(cond, then_v, else_v)`.
//! TRUSTED body (`value_bounds.py`): `if cond { then_v } else { else_v }`.
//!
//! HOLES: none — exec body matches the open spec exactly on all u64 inputs.

/// Spec oracle (`case_when_u64` in value_bounds.py).
fn case_when_u64_spec(cond: bool, then_v: u64, else_v: u64) -> u64 {
    if cond {
        then_v
    } else {
        else_v
    }
}

/// Inline TRUSTED exec body — not `lemma_native`.
fn under_test(cond: bool, then_v: u64, else_v: u64) -> u64 {
    if cond {
        then_v
    } else {
        else_v
    }
}

fn assert_matches_spec(cond: bool, then_v: u64, else_v: u64) {
    let got = under_test(cond, then_v, else_v);
    let want = case_when_u64_spec(cond, then_v, else_v);
    assert_eq!(got, want, "cond={cond} then={then_v} else={else_v}");
}

#[test]
fn cond_true_returns_then_branch() {
    assert_matches_spec(true, 42, 7);
    assert_matches_spec(true, 1, 0);
    assert_matches_spec(true, u64::MAX, 0);
}

#[test]
fn cond_false_returns_else_branch() {
    assert_matches_spec(false, 42, 7);
    assert_matches_spec(false, 0, 99);
    assert_matches_spec(false, 1, u64::MAX);
}

#[test]
fn both_operands_zero() {
    assert_matches_spec(true, 0, 0);
    assert_matches_spec(false, 0, 0);
}

#[test]
fn then_max_else_zero() {
    assert_matches_spec(true, u64::MAX, 0);
    assert_matches_spec(false, u64::MAX, 0);
}

#[test]
fn then_zero_else_max() {
    assert_matches_spec(true, 0, u64::MAX);
    assert_matches_spec(false, 0, u64::MAX);
}

#[test]
fn both_operands_max() {
    assert_matches_spec(true, u64::MAX, u64::MAX);
    assert_matches_spec(false, u64::MAX, u64::MAX);
}

#[test]
fn equal_branches_ignore_condition() {
    for cond in [true, false] {
        assert_matches_spec(cond, 12345, 12345);
        assert_matches_spec(cond, u64::MAX, u64::MAX);
        assert_matches_spec(cond, 0, 0);
    }
}

#[test]
fn asymmetric_large_gap() {
    assert_matches_spec(true, 1, u64::MAX - 1);
    assert_matches_spec(false, 1, u64::MAX - 1);
    assert_matches_spec(true, u64::MAX / 2, u64::MAX / 2 + 1);
    assert_matches_spec(false, u64::MAX / 2, u64::MAX / 2 + 1);
}

#[test]
fn powers_of_two_edges() {
    for &v in &[1u64, 2, 256, 65536, 1 << 32, 1 << 40] {
        assert_matches_spec(true, v, v.wrapping_add(1));
        assert_matches_spec(false, v, v.wrapping_add(1));
    }
}

#[test]
fn lcg_seed_grid() {
    let mut seed: u64 = 0xCA5E_CA5E;
    for i in 0..64 {
        let cond = seed & 1 == 0;
        let then_v = seed.wrapping_mul(1_103_515_245);
        let else_v = seed.rotate_left(17) ^ 0x9E37_79B9;
        assert_matches_spec(cond, then_v, else_v);
        seed = seed.wrapping_add(i + 1);
    }
}

#[test]
fn then_one_else_max_minus_one() {
    assert_matches_spec(true, 1, u64::MAX - 1);
    assert_matches_spec(false, 1, u64::MAX - 1);
}

#[test]
fn then_gt_else_both_branches() {
    assert_matches_spec(true, 1000, 3);
    assert_matches_spec(false, 1000, 3);
}

#[test]
fn then_lt_else_both_branches() {
    assert_matches_spec(true, 3, 1000);
    assert_matches_spec(false, 3, 1000);
}

#[test]
fn alternating_bit_patterns() {
    assert_matches_spec(true, 0xAAAA_AAAA_AAAA_AAAA, 0x5555_5555_5555_5555);
    assert_matches_spec(false, 0xAAAA_AAAA_AAAA_AAAA, 0x5555_5555_5555_5555);
}
