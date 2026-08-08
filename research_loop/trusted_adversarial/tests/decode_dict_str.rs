//! Adversarial tests for TRUSTED `decode_dict_str` (`verus_externs_core.rs.inc`).
//!
//! TRUSTED body: `dict[codes[i] as usize].clone()`
//! TRUSTED requires: `i < codes@.len()`
//! TRUSTED ensures: `(codes[i] as int) < dict@.len()` — **WEAK**: bounds the code index only;
//! does **not** ensure `s@ == dict@[codes[i]]` (string equality / correct dictionary lookup).
//!
//! HOLES (ensures gaps a malicious `external_body` could exploit while still satisfying Verus):
//! - No postcondition tying the returned `String` to `dict[codes[i]]`; any string is admissible
//!   as long as the code index is in range.
//! - No relation between `codes@.len()` and `dict@.len()` beyond per-row `codes[i] < dict.len()`.
//! - Panics on `codes[i] >= dict.len()` are runtime-only; Verus does not require a safe fallback.

use lemma_agent_primitives::decode_dict_str as reference_decode;

/// Mirror of TRUSTED `decode_dict_str` body in `verus_externs_core.rs.inc`.
fn under_test(codes: &[u32], dict: &[String], i: usize) -> String {
    dict[codes[i] as usize].clone()
}

fn assert_matches_reference(codes: &[u32], dict: &[String], i: usize) {
    let got = under_test(codes, dict, i);
    let expected = reference_decode(codes, dict, i)
        .unwrap_or_else(|| panic!("reference returned None for i={i}"));
    assert_eq!(got, expected);
}

// --- adversarial cases (≥10) ---

#[test]
fn adv_row_zero_code_not_row_index() {
    // Catches `dict[i]` instead of `dict[codes[i]]`.
    let codes = vec![2u32, 0, 1];
    let dict = vec!["a".into(), "b".into(), "c".into()];
    assert_eq!(under_test(&codes, &dict, 0), "c");
    assert_ne!(under_test(&codes, &dict, 0), dict[0]);
}

#[test]
fn adv_large_code_at_last_dict_slot() {
    let codes = vec![4u32];
    let dict = vec!["d0".into(), "d1".into(), "d2".into(), "d3".into(), "d4".into()];
    assert_eq!(under_test(&codes, &dict, 0), "d4");
}

#[test]
fn adv_repeated_code_same_string() {
    let codes = vec![1u32, 1, 1, 0, 1];
    let dict = vec!["x".into(), "y".into()];
    for i in 0..codes.len() {
        let want = if codes[i] == 0 { "x" } else { "y" };
        assert_eq!(under_test(&codes, &dict, i), want);
    }
}

#[test]
fn adv_unicode_dict_entries() {
    let codes = vec![0u32, 2, 1];
    let dict = vec!["🦆".into(), "naïve".into(), "日本語".into()];
    assert_eq!(under_test(&codes, &dict, 1), "日本語");
    assert_eq!(under_test(&codes, &dict, 2), "naïve");
}

#[test]
fn adv_empty_string_in_dictionary() {
    let codes = vec![0u32, 1, 0];
    let dict = vec!["".into(), "nonempty".into()];
    assert_eq!(under_test(&codes, &dict, 0), "");
    assert_eq!(under_test(&codes, &dict, 2), "");
}

#[test]
fn adv_long_strings_stable_clone() {
    let long = "z".repeat(10_000);
    let codes = vec![1u32];
    let dict = vec!["short".into(), long.clone()];
    assert_eq!(under_test(&codes, &dict, 0), long);
}

#[test]
fn adv_middle_row_non_identity_mapping() {
    // Second row: i=1 but codes[1]=3 — wrong-index bugs often show up off row 0.
    let codes = vec![0u32, 3, 2, 1];
    let dict = vec!["w".into(), "x".into(), "y".into(), "z".into()];
    assert_eq!(under_test(&codes, &dict, 1), "z");
    assert_matches_reference(&codes, &dict, 1);
}

#[test]
fn adv_single_element_both_vectors() {
    let codes = vec![0u32];
    let dict = vec!["only".into()];
    assert_eq!(under_test(&codes, &dict, 0), "only");
}

#[test]
fn adv_code_zero_explicit() {
    let codes = vec![0u32, 0, 0];
    let dict = vec!["alpha".into(), "beta".into()];
    for i in 0..3 {
        assert_eq!(under_test(&codes, &dict, i), "alpha");
    }
}

#[test]
fn adv_max_u32_index_within_dict() {
    let n = 8usize;
    let dict: Vec<String> = (0..n).map(|k| format!("v{k}")).collect();
    let code = (n - 1) as u32;
    let codes = vec![code];
    assert_eq!(under_test(&codes, &dict, 0), format!("v{}", n - 1));
}

#[test]
fn adv_skewed_codes_not_dense() {
    // Sparse / non-contiguous codes still must index dict, not row position.
    let codes = vec![7u32, 2, 5, 0];
    let dict: Vec<String> = (0..8).map(|k| format!("slot{k}")).collect();
    assert_eq!(under_test(&codes, &dict, 0), "slot7");
    assert_eq!(under_test(&codes, &dict, 3), "slot0");
}

#[test]
fn adv_all_rows_match_reference_roundtrip() {
    let col = vec![
        "red".to_string(),
        "green".to_string(),
        "blue".to_string(),
        "red".to_string(),
        "green".to_string(),
    ];
    let (codes, dict) = lemma_agent_primitives::encode_dictionary_str(&col);
    for i in 0..col.len() {
        assert_matches_reference(&codes, &dict, i);
        assert_eq!(under_test(&codes, &dict, i), col[i]);
    }
}

#[test]
#[should_panic]
fn adv_oob_code_panics_at_runtime() {
    // satisfies requires (i < codes.len()) but violates implicit need codes[i] < dict.len()
    let codes = vec![3u32];
    let dict = vec!["a".into(), "b".into()];
    let _ = under_test(&codes, &dict, 0);
}

#[test]
fn adv_ensures_gap_wrong_string_would_pass_verus() {
    // Documented hole: Verus ensures only `codes[i] < dict.len()`, not string equality.
    // A malicious body could return `dict[0].clone()` for every row while still meeting ensures
    // when all codes are in range — these tests catch that semantic bug even though Verus would not.
    let codes = vec![2u32, 0, 1];
    let dict = vec!["first".into(), "second".into(), "third".into()];
    assert_eq!(under_test(&codes, &dict, 0), "third");
    assert_ne!(under_test(&codes, &dict, 0), "first");
    assert_eq!(under_test(&codes, &dict, 1), "first");
    assert_eq!(under_test(&codes, &dict, 2), "second");
}
