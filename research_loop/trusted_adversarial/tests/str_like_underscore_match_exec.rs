//! Adversarial tests for TRUSTED `str_like_underscore_match_exec`
//! (`verus_transpiler/.../value_bounds.py`).
//!
//! Verus contract: `ensures res == str_like_underscore_match(s@, pat@)`.
//! Spec `str_like_underscore_match` is `arbitrary()` (TRUSTED axiom — unprovable).
//! Body: recursive `%` / `_` matcher copied below as `under_test`.
//!
//! HOLES:
//! - Spec is `arbitrary()`; Verus cannot prove the `ensures` against the exec body.
//! - No SQL `ESCAPE` clause: `%` and `_` are always wildcards in the pattern.
//! - Matching is Rust `char`-granular (Unicode scalar), not grapheme-cluster aware.

/// Exact recursive matcher from `value_bounds.py` (`str_like_underscore_match_exec` body).
fn under_test(s: &str, pat: &str) -> bool {
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

/// Independent slice-recursion oracle (different algorithm, same SQL LIKE rules).
fn oracle_sql_like(s: &str, pat: &str) -> bool {
    fn o(s: &[char], p: &[char]) -> bool {
        match (s.is_empty(), p.is_empty()) {
            (true, true) => true,
            (true, false) => p.iter().all(|&c| c == '%'),
            (false, true) => false,
            _ => {
                let (sc, sr) = (s[0], &s[1..]);
                match p[0] {
                    '%' => o(s, &p[1..]) || o(sr, p),
                    '_' => o(sr, &p[1..]),
                    pc if sc == pc => o(sr, &p[1..]),
                    _ => false,
                }
            }
        }
    }
    o(&s.chars().collect::<Vec<_>>(), &pat.chars().collect::<Vec<_>>())
}

fn assert_like(s: &str, pat: &str, want: bool, label: &str) {
    let got = under_test(s, pat);
    assert_eq!(got, want, "{label}: under_test({s:?}, {pat:?})");
    assert_eq!(
        got,
        oracle_sql_like(s, pat),
        "{label}: oracle disagrees for ({s:?}, {pat:?})"
    );
}

#[test]
fn both_empty() {
    assert_like("", "", true, "both_empty");
}

#[test]
fn empty_string_nonempty_literal_pattern() {
    assert_like("", "a", false, "empty_s_literal_pat");
    assert_like("", "_", false, "empty_s_underscore_pat");
}

#[test]
fn empty_string_percent_wildcards() {
    assert_like("", "%", true, "empty_s_percent");
    assert_like("", "%%", true, "empty_s_double_percent");
    assert_like("", "%%%", true, "empty_s_triple_percent");
}

#[test]
fn literal_exact_and_mismatch() {
    assert_like("foo", "foo", true, "exact");
    assert_like("foo", "bar", false, "literal_mismatch");
    assert_like("foo", "food", false, "longer_pat");
}

#[test]
fn single_underscore_wildcard() {
    assert_like("foo", "f_o", true, "f_o");
    assert_like("foo", "f__", true, "f__three_chars");
    assert_like("foo", "___", true, "three_underscores");
    assert_like("a", "_", true, "single_char_underscore");
}

#[test]
fn percent_prefix_suffix_contains() {
    assert_like("foo", "%oo", true, "percent_suffix");
    assert_like("foo", "f%", true, "percent_prefix");
    assert_like("foo", "%o%", true, "percent_both");
    assert_like("foo", "f%o", true, "percent_middle");
    assert_like("foo", "b%", false, "percent_wrong_prefix");
}

#[test]
fn multi_percent_runs() {
    assert_like("abc", "a%%c", true, "double_percent_middle");
    assert_like("abc", "%%bc", true, "leading_double_percent");
    assert_like("abc", "a%%", true, "trailing_double_percent");
    assert_like("abc", "%%%", true, "triple_percent_only");
    assert_like("", "%%%%", true, "quad_percent_empty");
}

#[test]
fn mixed_percent_underscore() {
    assert_like("foobar", "%o_ar", true, "percent_underscore_mix");
    assert_like("x_y_z", "_%_%", true, "underscore_percent_alternate");
    assert_like("ab", "%_%", true, "percent_underscore_two_chars");
    assert_like("a", "%_%", true, "percent_underscore_single_char");
}

#[test]
fn literal_percent_underscore_in_haystack() {
    assert_like("100%", "100%", true, "literal_percent_in_both");
    assert_like("a_b", "a_b", true, "literal_underscore_in_both");
    assert_like("a%c", "a%c", true, "literal_percent_in_haystack");
    assert_like("x%y", "_%_", true, "wildcards_over_literal_percent");
}

#[test]
fn unicode_scalar_underscore() {
    assert_like("café", "caf_", true, "unicode_accent");
    assert_like("a🎉b", "a_b", true, "emoji_single_char");
    assert_like("αβγ", "α_γ", true, "greek_underscore");
}

#[test]
fn length_skew_and_repeated_wildcards() {
    assert_like("aaaa", "a%a%a%a", true, "interleaved_percent");
    assert_like("test", "t_st", true, "classic_t_st");
    assert_like("test", "____", true, "four_underscores_exact");
    assert_like("test", "_____", false, "five_underscores_too_many");
}

#[test]
fn lcg_seeded_pairs() {
    let seeds: &[(&str, &str, bool)] = &[
        ("", "%", true),
        ("abc", "%", true),
        ("abc", "a%c", true),
        ("abc", "d%", false),
        ("xy", "_y", true),
        ("xy", "x_", true),
        ("xy", "__", true),
        ("xy", "___", false),
    ];
    for (s, p, want) in seeds {
        assert_like(s, p, *want, "seed_table");
    }

    let mut state = 0xFACEFEED_u64;
    for i in 0..64 {
        state = state.wrapping_mul(1_103_515_245).wrapping_add(i);
        let s_len = (state % 8) as usize;
        let p_len = ((state >> 8) % 6) as usize;
        let s: String = (0..s_len)
            .map(|j| {
                let c = ((state >> (j * 3)) & 0x7) as u8 + b'a';
                c as char
            })
            .collect();
        let p: String = (0..p_len)
            .map(|j| match (state >> (j * 2)) & 3 {
                0 => '%',
                1 => '_',
                _ => (b'a' + ((state >> j) & 7) as u8) as char,
            })
            .collect();
        let got = under_test(&s, &p);
        assert_eq!(
            got,
            oracle_sql_like(&s, &p),
            "lcg i={i} s={s:?} p={p:?}"
        );
    }
}
