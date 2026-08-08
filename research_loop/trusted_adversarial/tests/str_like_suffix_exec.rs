//! Adversarial tests for TRUSTED `str_like_suffix_exec` (value_bounds.py).
//!
//! Spec: `str_like_suffix(s, lit) := lit.is_suffix_of(s)`
//! Body: `s.ends_with(lit)`

/// Inlined TRUSTED body from value_bounds.py — do not import from lemma_native.
fn under_test(s: &str, lit: &str) -> bool {
    s.ends_with(lit)
}

/// Independent char-seq oracle for `lit.is_suffix_of(s)` (no `ends_with` call).
fn spec_oracle(s: &str, lit: &str) -> bool {
    let s_chars: Vec<char> = s.chars().collect();
    let lit_chars: Vec<char> = lit.chars().collect();
    if lit_chars.len() > s_chars.len() {
        return false;
    }
    let offset = s_chars.len() - lit_chars.len();
    lit_chars
        .iter()
        .enumerate()
        .all(|(i, &c)| s_chars[offset + i] == c)
}

fn assert_suffix(s: &str, lit: &str, expect: bool) {
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
    assert_suffix("", "", true);
}

#[test]
fn empty_s_nonempty_lit_is_false() {
    assert_suffix("", "x", false);
    assert_suffix("", "🔥", false);
}

#[test]
fn empty_lit_matches_any_s() {
    assert_suffix("hello", "", true);
    assert_suffix("🔥", "", true);
    assert_suffix("", "", true);
}

#[test]
fn exact_whole_string_match() {
    assert_suffix("abc", "abc", true);
    assert_suffix("a", "a", true);
}

#[test]
fn proper_suffix_not_whole_string() {
    assert_suffix("foobar", "bar", true);
    assert_suffix("xxfoo", "foo", true);
}

#[test]
fn prefix_match_is_not_suffix() {
    assert_suffix("foobar", "foo", false);
    assert_suffix("abc", "ab", false);
}

#[test]
fn interior_substring_that_is_also_suffix() {
    assert_suffix("banana", "ana", true);
    assert_suffix("ababc", "bc", true);
    assert_suffix("ababc", "ab", false);
}

#[test]
fn case_sensitive_mismatch() {
    assert_suffix("Hello", "hello", false);
    assert_suffix("SQL", "ql", false);
    assert_suffix("SQL", "QL", true);
}

#[test]
fn lit_longer_than_s_is_false() {
    assert_suffix("a", "aa", false);
    assert_suffix("hi", "hello", false);
}

#[test]
fn near_miss_last_scalar() {
    assert_suffix("café", "cafe", false);
    assert_suffix("resume", "resumé", false);
}

#[test]
fn unicode_accented_suffix() {
    assert_suffix("order-café", "café", true);
    assert_suffix("naïve", "ïve", true);
}

#[test]
fn emoji_suffix() {
    assert_suffix("go🚀", "🚀", true);
    assert_suffix("flag🇺🇸", "🇺🇸", true);
    assert_suffix("🚀go", "🚀", false);
}

#[test]
fn combining_mark_suffix() {
    assert_suffix("e\u{0301}", "\u{0301}", true);
    assert_suffix("resume\u{0301}", "me\u{0301}", true);
    assert_suffix("resume\u{0301}", "sum\u{0301}", false);
}

#[test]
fn long_repeated_ascii_skew() {
    let s = "a".repeat(10_000) + "suffix";
    assert_suffix(&s, "suffix", true);
    assert_suffix(&s, "uffix", true);
    assert_suffix(&s, "prefix", false);
}

#[test]
fn seeded_adversarial_pairs() {
    const PAIRS: &[(&str, &str, bool)] = &[
        ("", "", true),
        ("x", "", true),
        ("", "x", false),
        ("abc", "c", true),
        ("abc", "bc", true),
        ("abc", "d", false),
        ("🎉party", "party", true),
        ("party🎉", "party", false),
        ("\\n\\t", "\\t", true),
        ("null\u{0}end", "end", true),
    ];
    for &(s, lit, expect) in PAIRS {
        assert_suffix(s, lit, expect);
    }
}
