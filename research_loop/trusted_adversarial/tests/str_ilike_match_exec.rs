//! Adversarial tests for TRUSTED `str_ilike_match_exec` (`value_bounds.py`).
//!
//! TRUSTED body: `str_like_underscore_match_exec(&s.to_ascii_lowercase(), &pat.to_ascii_lowercase())`
//! Verus spec: `ensures res == str_ilike_match(s@, pat@)` where `str_ilike_match` is `arbitrary()`.
//!
//! HOLES:
//! - `str_ilike_match` and `str_like_underscore_match` specs are vacuous (`arbitrary()`).
//! - Case fold is ASCII-only (`to_ascii_lowercase`), not full Unicode ILIKE / SQL semantics.

/// TRUSTED underscore-LIKE matcher — exact body from `value_bounds.py`.
fn str_like_underscore_match_exec(s: &str, pat: &str) -> bool {
    fn m(s: &[char], si: usize, p: &[char], pi: usize) -> bool {
        if pi >= p.len() {
            return si >= s.len();
        }
        if p[pi] == '%' {
            let mut k = si;
            while k <= s.len() {
                if m(s, k, p, pi + 1) {
                    return true;
                }
                k += 1;
            }
            return false;
        }
        if p[pi] == '_' {
            if si >= s.len() {
                return false;
            }
            return m(s, si + 1, p, pi + 1);
        }
        if si >= s.len() || s[si] != p[pi] {
            return false;
        }
        m(s, si + 1, p, pi + 1)
    }
    let sc: Vec<char> = s.chars().collect();
    let pc: Vec<char> = pat.chars().collect();
    m(&sc, 0, &pc, 0)
}

/// Inline TRUSTED `str_ilike_match_exec` body — not `lemma_native`.
fn under_test(s: &str, pat: &str) -> bool {
    str_like_underscore_match_exec(&s.to_ascii_lowercase(), &pat.to_ascii_lowercase())
}

/// Independent DP oracle: ASCII-lowercase then underscore + `%` LIKE.
fn oracle_ilike_ascii(s: &str, pat: &str) -> bool {
    oracle_like_underscore_dp(&s.to_ascii_lowercase(), &pat.to_ascii_lowercase())
}

fn oracle_like_underscore_dp(s: &str, pat: &str) -> bool {
    let s: Vec<char> = s.chars().collect();
    let p: Vec<char> = pat.chars().collect();
    let n = s.len();
    let m = p.len();
    let mut dp = vec![vec![false; m + 1]; n + 1];
    dp[n][m] = true;
    for j in (0..m).rev() {
        if p[j] == '%' {
            dp[n][j] = dp[n][j + 1];
        }
    }
    for i in (0..n).rev() {
        for j in (0..m).rev() {
            if p[j] == '%' {
                dp[i][j] = dp[i + 1][j] || dp[i][j + 1];
            } else {
                dp[i][j] = (p[j] == '_' || s[i] == p[j]) && dp[i + 1][j + 1];
            }
        }
    }
    dp[0][0]
}

fn assert_ilike(s: &str, pat: &str, expect: bool) {
    let got = under_test(s, pat);
    let want = oracle_ilike_ascii(s, pat);
    assert_eq!(
        got, want,
        "under_test diverged from oracle: s={s:?} pat={pat:?}"
    );
    assert_eq!(got, expect, "s={s:?} pat={pat:?}");
}

#[test]
fn ascii_case_insensitive_exact() {
    assert_ilike("Foo", "foo", true);
    assert_ilike("BAR", "bar", true);
    assert_ilike("MiXeD", "mixed", true);
}

#[test]
fn uppercase_pattern_folded() {
    assert_ilike("hello", "HELLO", true);
    assert_ilike("AbCdE", "A%C%E", true);
}

#[test]
fn percent_prefix_suffix() {
    assert_ilike("foobar", "%bar", true);
    assert_ilike("foobar", "FOO%", true);
    assert_ilike("x", "%x", true);
}

#[test]
fn percent_middle_and_only() {
    assert_ilike("foobar", "f%r", true);
    assert_ilike("anything", "%", true);
    assert_ilike("abcde", "a%%e", true);
}

#[test]
fn underscore_single_char_wildcard() {
    assert_ilike("cat", "c_t", true);
    assert_ilike("cat", "C_T", true);
    assert_ilike("a_b", "a_b", true);
}

#[test]
fn underscore_length_mismatch() {
    assert_ilike("cat", "c__t", false);
    assert_ilike("ab", "a_b", false);
    assert_ilike("a", "_", true);
}

#[test]
fn empty_strings() {
    assert_ilike("", "", true);
    assert_ilike("", "%", true);
    assert_ilike("", "x", false);
    assert_ilike("x", "", false);
}

#[test]
fn literal_percent_and_underscore_chars() {
    assert_ilike("100%", "100%", true);
    assert_ilike("a%c", "a%c", true);
    assert_ilike("miss", "m_s", false);
}

#[test]
fn case_mismatch_after_fold() {
    assert_ilike("ABC", "abd", false);
    assert_ilike("foo", "FOOB", false);
    assert_ilike("prefix", "pre%fix", true);
}

#[test]
fn multiple_percent_greedy_edges() {
    assert_ilike("abc", "a%c", true);
    assert_ilike("abc", "%b%", true);
    assert_ilike("abc", "%d%", false);
    assert_ilike("a", "%%", true);
}

#[test]
fn long_ascii_with_wildcards() {
    let s = "A".repeat(500) + "z" + &"B".repeat(500);
    assert_ilike(&s, "%z%", true);
    assert_ilike(&s, "a%z%", true);
    assert_ilike(&s, "%z", false); // ends with B's, not z
    assert_ilike(&s, "%b", true); // ASCII-fold of trailing B's
}

#[test]
fn seeded_adversarial_pairs() {
    const PAIRS: &[(&str, &str, bool)] = &[
        ("Test", "t%t", true),
        ("NO", "n_", true),
        ("NO", "n__", false),
        ("_", "_", true),
        ("%", "%", true),
        ("abc", "a_c", true), // a _ c
        ("abc", "A_C", true),
        ("abc", "a_b", false), // would need middle any + trailing 'b'
        ("Z", "z", true),
        ("z", "Z", true),
        ("hello world", "HELLO%WORLD", true),
    ];
    for &(s, pat, expect) in PAIRS {
        assert_ilike(s, pat, expect);
    }
}

#[test]
fn unicode_not_ascii_folded() {
    let got = under_test("α", "A");
    let oracle = oracle_ilike_ascii("α", "A");
    assert_eq!(got, oracle);
    assert_eq!(got, false);
    // HOLE: real SQL ILIKE may differ; spec is arbitrary() anyway.
}

#[test]
fn ascii_i_case_fold() {
    assert_ilike("I", "i", true);
    // Turkish İ is not ASCII-folded to i.
    assert_ilike("İ", "i", false);
}
