use vstd::prelude::*;
use vstd::string::{StringSliceAdditionalSpecFns, is_ascii};

verus! {

proof fn lemma_ascii_chars_eq_from_u8(c1: char, c2: char)
    requires
        '\0' <= c1 <= '\u{7f}',
        '\0' <= c2 <= '\u{7f}',
        c1 as u8 == c2 as u8,
    ensures
        c1 == c2,
{
    let u1 = c1 as u32;
    let u2 = c2 as u32;
    assert(u1 <= 0x7f);
    assert(u2 <= 0x7f);
    assert(u1 as u8 == c1 as u8);
    assert(u2 as u8 == c2 as u8);
    assert(u1 == u2) by (bit_vector)
        requires
            u1 <= 0x7f,
            u2 <= 0x7f,
            u1 as u8 == u2 as u8,
    ;
    vstd::utf8::char_u32_cast(c1, u1);
    vstd::utf8::char_u32_cast(c2, u2);
    assert(u1 as char == c1);
    assert(u2 as char == c2);
}

pub fn eq_str_view(a: &str, b: &str) -> (r: bool)
    ensures
        r == (a@ == b@),
{
    let an = a.unicode_len();
    let bn = b.unicode_len();
    if an != bn {
        proof {
            assert(an as int == a@.len());
            assert(bn as int == b@.len());
            assert(a@.len() != b@.len());
        }
        return false;
    }
    if a.is_ascii() && b.is_ascii() {
        let mut i: usize = 0;
        while i < an
            invariant
                i <= an,
                an as int == a@.len(),
                bn as int == b@.len(),
                an == bn,
                is_ascii(a),
                is_ascii(b),
                forall|j: int| 0 <= j < i as int ==> a@[j] == b@[j],
            decreases an - i,
        {
            let ca = a.get_ascii(i);
            let cb = b.get_ascii(i);
            if ca != cb {
                proof {
                    assert(a@[i as int] as u8 == ca);
                    assert(b@[i as int] as u8 == cb);
                    assert(a@[i as int] != b@[i as int]);
                }
                return false;
            }
            proof {
                assert(a@[i as int] as u8 == ca);
                assert(b@[i as int] as u8 == cb);
                assert(ca == cb);
                assert('\0' <= a@[i as int] <= '\u{7f}');
                assert('\0' <= b@[i as int] <= '\u{7f}');
                lemma_ascii_chars_eq_from_u8(a@[i as int], b@[i as int]);
                assert(a@[i as int] == b@[i as int]);
            }
            i = i + 1;
        }
        proof {
            assert(i == an);
            assert forall|j: int| 0 <= j < a@.len() implies a@[j] == b@[j] by {
                assert(0 <= j < i as int);
            };
            assert(a@ =~= b@);
        }
        return true;
    }
    let mut i: usize = 0;
    while i < an
        invariant
            i <= an,
            an as int == a@.len(),
            bn as int == b@.len(),
            an == bn,
            forall|j: int| 0 <= j < i as int ==> a@[j] == b@[j],
        decreases an - i,
    {
        let ca = a.get_char(i);
        let cb = b.get_char(i);
        let ua = ca as u32;
        let ub = cb as u32;
        if ua != ub {
            proof {
                assert(a@[i as int] == ca);
                assert(b@[i as int] == cb);
                if ca == cb {
                    assert(ua == ub);
                }
                assert(ca != cb);
            }
            return false;
        }
        proof {
            assert(ua == ub);
            vstd::utf8::char_u32_cast(ca, ua);
            vstd::utf8::char_u32_cast(cb, ub);
            assert(ua as char == ca);
            assert(ub as char == cb);
            assert(ca == cb);
            assert(a@[i as int] == ca);
            assert(b@[i as int] == cb);
            assert(a@[i as int] == b@[i as int]);
        }
        i = i + 1;
    }
    proof {
        assert(i == an);
        assert forall|j: int| 0 <= j < a@.len() implies a@[j] == b@[j] by {
            assert(0 <= j < i as int);
        };
        assert(a@ =~= b@);
    }
    true
}

pub fn eq_ascii_lit(s: &str, lit: &str) -> (r: bool)
    requires
        s@.len() <= 512,
    ensures
        r == (s@ == lit@),
{
    if !lit.is_ascii() {
        return eq_str_view(s, lit);
    }
    let ln_chars = lit.unicode_len();
    proof {
        assert(ln_chars as int == lit@.len());
        assert(lit@.len() <= usize::MAX);
        assert(is_ascii(lit));
    }
    if !s.is_ascii() {
        proof {
            assert(!is_ascii(s));
            assert(is_ascii(lit));
            if s@ == lit@ {
                assert(is_ascii(s));
            }
            assert(s@ != lit@);
        }
        return false;
    }
    let sn = s.len();
    let ln = lit.len();
    proof {
        broadcast use vstd::string::is_ascii_spec_bytes;
        assert(is_ascii(s));
        assert(is_ascii(lit));
        assert(s.spec_bytes().len() == s@.len());
        assert(lit.spec_bytes().len() == lit@.len());
        assert(s@.len() <= usize::MAX);
        assert(lit@.len() <= usize::MAX);
        assert(sn == s.spec_bytes().len() as usize);
        assert(ln == lit.spec_bytes().len() as usize);
        assert(sn as int == s@.len());
        assert(ln as int == lit@.len());
    }
    if sn != ln {
        proof {
            assert(s@.len() != lit@.len());
        }
        return false;
    }
    let mut i: usize = 0;
    while i < sn
        invariant
            i <= sn,
            sn as int == s@.len(),
            ln as int == lit@.len(),
            sn == ln,
            is_ascii(s),
            is_ascii(lit),
            forall|j: int| 0 <= j < i as int ==> s@[j] == lit@[j],
        decreases sn - i,
    {
        let ca = s.get_ascii(i);
        let cb = lit.get_ascii(i);
        if ca != cb {
            proof {
                assert(s@[i as int] as u8 == ca);
                assert(lit@[i as int] as u8 == cb);
                assert(s@[i as int] != lit@[i as int]);
            }
            return false;
        }
        proof {
            assert(s@[i as int] as u8 == ca);
            assert(lit@[i as int] as u8 == cb);
            assert(ca == cb);
            assert('\0' <= s@[i as int] <= '\u{7f}');
            assert('\0' <= lit@[i as int] <= '\u{7f}');
            lemma_ascii_chars_eq_from_u8(s@[i as int], lit@[i as int]);
            assert(s@[i as int] == lit@[i as int]);
        }
        i = i + 1;
    }
    proof {
        assert(i == sn);
        assert forall|j: int| 0 <= j < s@.len() implies s@[j] == lit@[j] by {
            assert(0 <= j < i as int);
        };
        assert(s@ =~= lit@);
    }
    true
}

fn check_pure(s: &str) -> (r: bool)
    requires
        s@.len() <= 512,
    ensures
        r == (s@ == "pure"@),
{
    eq_ascii_lit(s, "pure")
}

}
fn main() {}
