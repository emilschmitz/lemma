//! Adversarial tests for TRUSTED `str_lower_exec` (`value_bounds.py`).
//!
//! Verus contract: `ensures res@ == str_lower(s@)`.
//! TRUSTED spec: `str_lower(s) = arbitrary()` — vacuous axiom.
//! TRUSTED body: `s.to_ascii_lowercase()` (ASCII A–Z only; non-ASCII unchanged).
//!
//! HOLES: `str_lower` spec is `arbitrary()` — no real char-level semantics to falsify.
//! Exec body is pinned to Rust `to_ascii_lowercase`; tests cross-check vs an independent
//! per-scalar oracle (not `str_lower`).

/// Inlined TRUSTED exec body from value_bounds.py.
fn under_test(s: &str) -> String {
    s.to_ascii_lowercase()
}

/// Independent oracle: lowercase ASCII A–Z; leave all other scalars unchanged.
fn ascii_lower_oracle(s: &str) -> String {
    s.chars()
        .map(|c| {
            if ('A'..='Z').contains(&c) {
                char::from_u32(c as u32 + 32).unwrap_or(c)
            } else {
                c
            }
        })
        .collect()
}

fn assert_lower(s: &str, expect: &str) {
    let got = under_test(s);
    let oracle = ascii_lower_oracle(s);
    assert_eq!(
        got, oracle,
        "under_test diverged from independent oracle: s={s:?}"
    );
    assert_eq!(got, expect, "s={s:?}");
}

#[test]
fn empty_string() {
    assert_lower("", "");
}

#[test]
fn all_lowercase_ascii_unchanged() {
    assert_lower("hello", "hello");
    assert_lower("abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz");
}

#[test]
fn all_uppercase_ascii_lowercased() {
    assert_lower("HELLO", "hello");
    assert_lower("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz");
}

#[test]
fn mixed_case_ascii() {
    assert_lower("HeLLo WoRLd", "hello world");
    assert_lower("RustLang", "rustlang");
    assert_lower("aBcDeF", "abcdef");
}

#[test]
fn non_ascii_only_unchanged() {
    assert_lower("café", "café");
    assert_lower("naïve", "naïve");
    assert_lower("日本語", "日本語");
    assert_lower("über", "über");
}

#[test]
fn mixed_ascii_and_non_ascii() {
    assert_lower("Hello Café", "hello café");
    // U+00C9 É is not ASCII — only A–Z are lowered.
    assert_lower("CAFÉ", "cafÉ");
    assert_lower("MIXED Ñoño", "mixed Ñoño");
    assert_lower("ASCII only + é", "ascii only + é");
}

#[test]
fn digits_symbols_punctuation_unchanged() {
    assert_lower("123 !@#$%^&*()", "123 !@#$%^&*()");
    assert_lower("A1B2C3", "a1b2c3");
    assert_lower("TAB\tNEW\nLINE", "tab\tnew\nline");
}

#[test]
fn turkish_dotless_i_unchanged() {
    // U+0130 LATIN CAPITAL LETTER I WITH DOT ABOVE — not ASCII; to_ascii_lowercase leaves it.
    assert_lower("İstanbul", "İstanbul");
    assert_lower("I", "i");
}

#[test]
fn greek_and_cyrillic_unchanged() {
    assert_lower("ΑΒΓΔ", "ΑΒΓΔ");
    assert_lower("ПРИВЕТ", "ПРИВЕТ");
    // Greek capitals are non-ASCII for to_ascii_lowercase.
    assert_lower("HELLO ΑΒΓ", "hello ΑΒΓ");
}

#[test]
fn emoji_and_surrogates_unchanged() {
    assert_lower("HELLO🎉WORLD", "hello🎉world");
    assert_lower("FLAG🇺🇸", "flag🇺🇸");
    assert_lower("🔥FIRE", "🔥fire");
}

#[test]
fn long_repeated_mixed() {
    let s = "AbC".repeat(5000);
    let want = "abc".repeat(5000);
    assert_lower(&s, &want);
}

#[test]
fn seeded_adversarial_inputs() {
    const CASES: &[(&str, &str)] = &[
        ("", ""),
        ("a", "a"),
        ("A", "a"),
        ("Z", "z"),
        ("z", "z"),
        ("ABC", "abc"),
        ("ß", "ß"),
        ("Straße", "straße"),
        ("\u{0000}A\u{007F}", "\u{0000}a\u{007f}"),
        ("\\N\\T", "\\n\\t"),
        ("MiXeD123!@#", "mixed123!@#"),
        ("Ñ", "Ñ"),
        ("RESUMÉ", "resumÉ"),
    ];
    for &(s, expect) in CASES {
        assert_lower(s, expect);
    }
}
