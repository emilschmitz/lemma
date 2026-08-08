//! Adversarial tests for TRUSTED `str_like_prefix_exec` (value_bounds.py).
//!
//! Spec: `str_like_prefix(s, lit) := lit.is_prefix_of(s)`
//! Body: `s.starts_with(lit)`
//!
//! HOLES: `#[verifier::external_body]` — Verus does not prove the body; no exec/spec
//! mismatch found on valid UTF-8 inputs (char-seq `is_prefix_of` agrees with `starts_with`).

/// Inlined TRUSTED body from value_bounds.py — do not import from lemma_native.
fn under_test(s: &str, lit: &str) -> bool {
    s.starts_with(lit)
}

/// Independent char-seq oracle for `lit.is_prefix_of(s)` (no `starts_with` call).
fn spec_oracle(s: &str, lit: &str) -> bool {
    let s_chars: Vec<char> = s.chars().collect();
    let lit_chars: Vec<char> = lit.chars().collect();
    if lit_chars.len() > s_chars.len() {
        return false;
    }
    lit_chars
        .iter()
        .enumerate()
        .all(|(i, &c)| s_chars[i] == c)
}

fn assert_prefix(s: &str, lit: &str, expect: bool) {
    let got = under_test(s, lit);
    let want = spec_oracle(s, lit);
    assert_eq!(
        got, want,
        "under_test diverged from spec oracle: s={s:?} lit={lit:?}"
    );
    assert_eq!(got, expect, "s={s:?} lit={lit:?}");
}

#[test]
fn both_empty_is_true() {
    assert_prefix("", "", true);
}

#[test]
fn empty_s_nonempty_lit_is_false() {
    assert_prefix("", "x", false);
    assert_prefix("", "🔥", false);
}

#[test]
fn empty_lit_matches_any_s() {
    assert_prefix("hello", "", true);
    assert_prefix("🔥", "", true);
    assert_prefix("", "", true);
}

#[test]
fn exact_whole_string_match() {
    assert_prefix("abc", "abc", true);
    assert_prefix("a", "a", true);
}

#[test]
fn proper_prefix_not_whole_string() {
    assert_prefix("foobar", "foo", true);
    assert_prefix("xxbar", "xx", true);
}

#[test]
fn suffix_match_is_not_prefix() {
    assert_prefix("foobar", "bar", false);
    assert_prefix("abc", "bc", false);
}

#[test]
fn interior_substring_not_prefix() {
    assert_prefix("xabc", "abc", false);
    assert_prefix("banana", "ana", false);
}

#[test]
fn lit_longer_than_s_is_false() {
    assert_prefix("a", "aa", false);
    assert_prefix("hi", "hello", false);
}

#[test]
fn near_miss_first_scalar() {
    assert_prefix("café", "cafe", false);
    assert_prefix("resumé", "resume", false);
}

#[test]
fn unicode_accented_prefix() {
    assert_prefix("café-order", "café", true);
    assert_prefix("ïve-ly", "ïve", true);
}

#[test]
fn emoji_prefix() {
    assert_prefix("🚀go", "🚀", true);
    assert_prefix("🇺🇸flag", "🇺🇸", true);
    assert_prefix("go🚀", "🚀", false);
}

#[test]
fn combining_mark_prefix() {
    assert_prefix("\u{0301}e", "\u{0301}", true);
    assert_prefix("me\u{0301}resume", "me\u{0301}", true);
}

#[test]
fn case_sensitive_mismatch() {
    assert_prefix("Hello", "hello", false);
    assert_prefix("SQLquery", "SQL", true);
}

#[test]
fn long_repeated_ascii_skew() {
    let s = "prefix".to_string() + &"a".repeat(10_000);
    assert_prefix(&s, "prefix", true);
    assert_prefix(&s, "prefi", true);
    assert_prefix(&s, "suffix", false);
}

#[test]
fn seeded_adversarial_pairs() {
    const PAIRS: &[(&str, &str, bool)] = &[
        ("", "", true),
        ("x", "", true),
        ("", "x", false),
        ("abc", "a", true),
        ("abc", "ab", true),
        ("abc", "d", false),
        ("party🎉", "party", true),
        ("🎉party", "party", false),
        ("\\n\\t", "\\", true),
        ("end\u{0}null", "end", true),
    ];
    for &(s, lit, expect) in PAIRS {
        assert_prefix(s, lit, expect);
    }
}
