//! Adversarial tests for TRUSTED `str_like_contains_exec` (`value_bounds.py`).
//!
//! Verus contract: `ensures res == str_like_contains(s@, lit@)`.
//! Spec axiom: `str_like_contains` is TRUSTED `arbitrary()` (no real substring semantics).
//! Exec body: `s.contains(lit)`.
//!
//! HOLES:
//! - `str_like_contains` spec is unconstrained (`arbitrary()`); the `ensures` tie is vacuous
//!   at proof time — substring meaning is assumed only via the exec body, not the spec.
//! - No exec-vs-oracle mismatch found below; Rust `str::contains` matches char-wise oracle.

/// TRUSTED body mirror (`value_bounds.py` `str_like_contains_exec`).
fn under_test(s: &str, lit: &str) -> bool {
    s.contains(lit)
}

/// Independent substring oracle (char sliding window; does not call `str::contains`).
fn oracle_substring_contains(s: &str, lit: &str) -> bool {
    if lit.is_empty() {
        return true;
    }
    let s_chars: Vec<char> = s.chars().collect();
    let lit_chars: Vec<char> = lit.chars().collect();
    if lit_chars.len() > s_chars.len() {
        return false;
    }
    let max_start = s_chars.len() - lit_chars.len();
    for start in 0..=max_start {
        if s_chars[start..start + lit_chars.len()] == lit_chars[..] {
            return true;
        }
    }
    false
}

fn assert_exec_matches_oracle(s: &str, lit: &str, label: &str) {
    let got = under_test(s, lit);
    let want = oracle_substring_contains(s, lit);
    assert_eq!(got, want, "{label}: s={s:?} lit={lit:?}");
}

#[test]
fn both_empty() {
    assert_exec_matches_oracle("", "", "both_empty");
}

#[test]
fn empty_haystack_nonempty_needle() {
    assert_exec_matches_oracle("", "x", "empty_haystack");
    assert_exec_matches_oracle("", "needle", "empty_haystack_long");
}

#[test]
fn empty_needle_always_true() {
    for s in ["", "a", "abc", "🦀", "multi\nline"] {
        assert_exec_matches_oracle(s, "", "empty_needle");
    }
}

#[test]
fn exact_match_single_char() {
    assert_exec_matches_oracle("a", "a", "exact_single");
    assert_exec_matches_oracle("z", "z", "exact_single_z");
}

#[test]
fn needle_longer_than_haystack() {
    assert_exec_matches_oracle("ab", "abcd", "needle_longer");
    assert_exec_matches_oracle("🦀", "🦀🦀", "emoji_needle_longer");
}

#[test]
fn prefix_middle_suffix_hits() {
    assert_exec_matches_oracle("hello world", "hello", "prefix");
    assert_exec_matches_oracle("hello world", "lo wo", "middle");
    assert_exec_matches_oracle("hello world", "world", "suffix");
}

#[test]
fn absent_substring() {
    assert_exec_matches_oracle("abcdef", "xyz", "absent");
    assert_exec_matches_oracle("aaaa", "aaaab", "absent_longer");
}

#[test]
fn overlapping_occurrences() {
    assert_exec_matches_oracle("aaaa", "aa", "overlapping");
    assert_exec_matches_oracle("ababab", "aba", "overlapping_aba");
}

#[test]
fn unicode_cyrillic_and_combining() {
    assert_exec_matches_oracle("привет мир", "привет", "cyrillic_prefix");
    assert_exec_matches_oracle("café", "café", "accented_exact");
    assert_exec_matches_oracle("e\u{0301}", "\u{0301}", "combining_mark");
}

#[test]
fn emoji_and_multibyte() {
    assert_exec_matches_oracle("foo🦀bar", "🦀", "emoji_middle");
    assert_exec_matches_oracle("🦀🦀", "🦀", "emoji_repeat");
    assert_exec_matches_oracle("a🦀b", "🦀b", "emoji_suffix_pair");
}

#[test]
fn case_sensitive_mismatch() {
    assert_exec_matches_oracle("Hello", "hello", "case_upper_in_lower");
    assert_exec_matches_oracle("hello", "Hello", "case_lower_in_upper");
    assert_exec_matches_oracle("ASCII", "ascii", "case_ascii");
}

#[test]
fn whitespace_and_embedded_null() {
    assert_exec_matches_oracle("a\tb\nc", "\t", "tab");
    assert_exec_matches_oracle("a\tb\nc", "\nb", "newline_span");
    assert_exec_matches_oracle("before\0after", "\0", "embedded_nul");
}

#[test]
fn length_skew_and_repeated_pattern() {
    let hay = "x".repeat(500) + "MARKER" + &"y".repeat(500);
    assert_exec_matches_oracle(&hay, "MARKER", "long_skew_hit");
    assert_exec_matches_oracle(&hay, "MARK", "long_skew_partial_miss");
    assert_exec_matches_oracle(&"ab".repeat(100), "abab", "repeated_pattern");
}

#[test]
fn lcg_seeded_pairs() {
    const PAIRS: [(&str, &str); 16] = [
        ("", ""),
        ("a", ""),
        ("", "z"),
        ("test", "es"),
        ("test", "tex"),
        ("🌟✨", "✨"),
        ("line1\nline2", "line2"),
        ("αβγ", "β"),
        ("__", "_"),
        ("abc", "def"),
        ("prefix_rest", "prefix"),
        ("rest_suffix", "suffix"),
        ("mid", "id"),
        ("A", "a"),
        ("null\0byte", "null"),
        ("zzzz", "zzz"),
    ];
    for (i, (s, lit)) in PAIRS.iter().enumerate() {
        assert_exec_matches_oracle(s, lit, &format!("lcg_pair_{i}"));
    }
}
