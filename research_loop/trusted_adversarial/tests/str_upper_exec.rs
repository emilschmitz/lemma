//! Adversarial tests for TRUSTED `str_upper_exec` (value_bounds.py).
//!
//! Verus contract: `ensures res@ == str_upper(s@)` where `str_upper` is `arbitrary()`.
//! TRUSTED body: `s.to_ascii_uppercase()`.
//!
//! HOLES:
//! - `str_upper` spec is `#[verifier::external_body] arbitrary()` — no definitional semantics.
//! - Body is ASCII-only (`a`–`z`); Unicode letters (é, ß, σ) pass through unchanged.
//! - Differs from `str::to_uppercase()` / typical SQL `UPPER` on non-ASCII text.

/// Inline TRUSTED exec body from value_bounds.py — do not import from lemma_native.
fn under_test(s: &str) -> String {
    s.to_ascii_uppercase()
}

/// Independent per-scalar oracle for ASCII uppercasing (no `to_ascii_uppercase` call).
fn ascii_upper_oracle(s: &str) -> String {
    s.chars()
        .map(|c| {
            if ('a'..='z').contains(&c) {
                char::from_u32((c as u32) - ('a' as u32) + ('A' as u32)).unwrap()
            } else {
                c
            }
        })
        .collect()
}

fn assert_matches_ascii_oracle(s: &str) {
    let got = under_test(s);
    let want = ascii_upper_oracle(s);
    assert_eq!(got, want, "s={s:?}");
}

#[test]
fn empty_string() {
    assert_matches_ascii_oracle("");
    assert_eq!(under_test(""), "");
}

#[test]
fn all_lower_ascii_alphabet() {
    assert_matches_ascii_oracle("abcdefghijklmnopqrstuvwxyz");
    assert_eq!(
        under_test("abcdefghijklmnopqrstuvwxyz"),
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    );
}

#[test]
fn already_upper_ascii_unchanged() {
    assert_matches_ascii_oracle("ABCDEFGHIJKLMNOPQRSTUVWXYZ");
    assert_matches_ascii_oracle("SQL UPPER");
}

#[test]
fn mixed_case_ascii() {
    assert_matches_ascii_oracle("Hello, World! 123");
    assert_eq!(under_test("MiXeDcAsE"), "MIXEDCASE");
}

#[test]
fn digits_and_symbols_unchanged() {
    assert_matches_ascii_oracle("0123456789!@#$%^&*()_+-=[]{}|;':\",./<>?");
    assert_matches_ascii_oracle(" \t\n\r");
}

#[test]
fn underscore_and_backslash() {
    assert_matches_ascii_oracle("snake_case_and-path\\file");
}

#[test]
fn non_ascii_letters_unchanged() {
    // HOLE: SQL/Unicode upper would change many of these; ASCII body does not.
    assert_matches_ascii_oracle("café résumé naïve");
    assert_eq!(under_test("café"), "CAFé");
    assert_ne!(under_test("café"), "CAFÉ");
}

#[test]
fn turkish_dotted_i_ascii_only() {
    // ASCII 'i' uppercases; Unicode 'ı' (U+0131) and 'İ' (U+0130) are untouched.
    assert_matches_ascii_oracle("istanbul");
    assert_eq!(under_test("istanbul"), "ISTANBUL");
    // HOLE: ASCII uppercases a-z only; dotted capital İ + latin letters → İSTANBUL.
    assert_eq!(under_test("İstanbul"), "İSTANBUL");
    assert_eq!(under_test("ı"), "ı");
}

#[test]
fn german_eszett_and_greek() {
    assert_matches_ascii_oracle("straße");
    assert_eq!(under_test("straße"), "STRAßE");
    assert_matches_ascii_oracle("σίγμα");
    assert_eq!(under_test("σίγμα"), "σίγμα");
}

#[test]
fn emoji_and_symbols_unchanged() {
    assert_matches_ascii_oracle("go🚀UP");
    assert_eq!(under_test("go🚀UP"), "GO🚀UP");
    assert_matches_ascii_oracle("flag🇺🇸test");
}

#[test]
fn combining_mark_sequence() {
    assert_matches_ascii_oracle("e\u{0301}");
    assert_eq!(under_test("resume\u{0301}"), "RESUME\u{0301}");
}

#[test]
fn long_repeated_ascii() {
    let s = "a".repeat(8_192) + "Z" + &"b".repeat(8_192);
    assert_matches_ascii_oracle(&s);
    assert!(under_test(&s).starts_with('A'));
    assert!(under_test(&s).ends_with('B'));
}

#[test]
fn seeded_adversarial_strings() {
    const CASES: &[&str] = &[
        "",
        "a",
        "A",
        "z",
        "Z",
        "aBcDeF",
        "NULL",
        "UPPER('x')",
        "line\nbreak\ttab",
        "café",
        "İ",
        "ı",
        "ß",
        "Σ",
        "🎉party",
        "a\u{0301}",
        "\\x41",
    ];
    for &s in CASES {
        assert_matches_ascii_oracle(s);
    }
}

#[test]
fn diverges_from_unicode_upper_on_non_ascii() {
    // Documents contract gap vs locale-aware / Unicode uppercasing.
    let inputs = ["café", "straße", "σ", "naïve"];
    for input in inputs {
        let got = under_test(input);
        assert_eq!(got, ascii_upper_oracle(input));
        let unicode = input.to_uppercase();
        assert_ne!(
            got, unicode,
            "HOLE: ASCII body {got:?} != Unicode upper {unicode:?} for {input:?}"
        );
    }
}
