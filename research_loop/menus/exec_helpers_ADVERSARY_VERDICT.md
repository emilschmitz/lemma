VERDICT: HOLES FOUND (4)

Scope: `declarative_spec/admit.py` (staged diff on f7b68d8), spec = SPEC of `tests/test_declarative_exec_helpers.py`
(ungrouped SUM). Verus evidence is from `scripts/ram/verus_guarded.sh`, assembled with the real
`assemble_declarative_program`. None of the four holes needs the new exec-`fn` allowance (H1, H2, H3 and H4 work
with `proof fn` / `spec fn` helpers and, for H1/H4, in the `run_query` body too), but the exec allowance adds one
convenient carrier for H1 (an `external_body` exec `fn` is callable from the body). The new allowance itself
(exec `fn` verified against its own requires/ensures, attribute whitelist, impl/trait/macro_rules/static/mod/use/
unsafe/extern rejection, `exec_allows_no_decreases_clause` rejection) held in everything I tried that is not
listed below.

## HOLES

### H1. Raw strings desynchronise `_strip_comments_and_strings`: every ban is bypassed (HOLE, Verus-confirmed)
`_strip_comments_and_strings` treats `r"\"` as an opening quote plus an escaped quote, so everything up to the
next `"` is "inside a string" and invisible to every regex (assume, admit, external, cfg, impl, ...), while rustc
sees a raw string `\` and live code. Works in the helper region and in the `run_query` body.
Minimal repro (helpers):
```
fn k() { let a = r"\"; }
#[verifier::external_body]
fn lie() -> (r: u64) ensures false { 0 }
fn m() { let b = r"\"; let c = "\""; }
```
body: `let _z = lie();  let res: Vec<OutRow> = Vec::new(); res`
`admit_helpers` -> ok, `admit_declarative_body` -> ok. Verus on the assembled program:
`verification results:: 6 verified, 0 errors`. The body returns an empty result for `SELECT SUM(line)` and is
"proved" equal to the spec. Same trick hides `assume(false)` (`fn f(..) { let a = r"\"; proof { assume(false); }
let b = r"\"; x }` plus a `fn z() { let q = "\""; }` tail to balance the stripped braces: admitted).
Fix: replace the stripper with a real Rust lexer (raw strings `r#*"..."#*`, `br`, `b"`, `c"`, `cr`, char vs
lifetime) and raise on anything it cannot lex; or reject the characters/tokens `r"`, `r#`, `br"`, `br#` outright
(an agent never needs a raw string).

### H2. Unterminated block comment in the helper region swallows the host `run_query` signature (HOLE, Verus-confirmed)
The stripper accepts an unterminated `/*` (it just stops), so `_top_level_headers` sees a balanced helper region.
In the assembled file the comment runs through `// AGENT_HELPERS_END` and the host `pub fn run_query(...) requires
... ensures <method_spec> {` and is closed by a `*/` that the BODY starts with, after which the body supplies its
own `run_query` with `ensures true`.
helpers: `fn dummy() {}\n/*`
body:
```
*/
pub fn run_query(pre: &Cols_pre) -> (res: Vec<OutRow>)
    requires valid_cols_pre(pre),
    ensures true,
{ Vec::new() }
// }
fn extra() {
```
(The `// }` line only compensates the raw brace counter in `assemble_declarative_program`; the host's two trailing
`}` close `extra` and `verus!`.) Both regions admitted; Verus: `6 verified, 0 errors`, i.e. the host `ensures`
is gone and an empty result is "proved". Pre-existing for the helper region (spec/proof fn), not caused by the
exec allowance, but it is a full bypass of the "trust only from the host" invariant.
Unterminated `"` in the helper is rejected only by accident (stripped braces become unbalanced).
Fix: the lexer must raise on an unterminated comment/string/char in either region; additionally, after assembly,
assert that the exact host `run_query` signature text (requires/ensures) appears once, outside any comment/string
of the lexed assembled file, and that each region lexes standalone to completion.

### H3. `_top_level_headers` lets a `::path::macro!{ ... }` item hide arbitrary items from the "only fn items" check (HOLE, Verus-accepted, exploit beyond aliasing not built)
`_continues_after_block` treats any next char that is not alpha/`_`/`#` as "same item", so `fn a() {}\n::vstd::prelude::verus! { pub struct Zs; spec fn zz() -> bool { true } type Q = u64; }`
is admitted (the macro block is skipped, no header recorded). Verus: `6 verified, 0 errors`, so the struct,
the spec fn and the type alias exist in the module. Admitted this way (admission only): `struct`, `enum`, `type`,
`const`, `global size_of ...`, module-level `broadcast use vstd::..::group_x;`, and
`impl<T: Fn()> View for Vec2<T> { .. }` (see next point).
Harm: a `type i128 = i8;` / `type Vec<T> = ...` / `enum Option<T>` at module level shadows names the host
text resolves (`Option<i128>`, `Vec<OutRow>` in `OutRow` / the host signature). I did not construct a Verus-accepted
program that weakens the host ensures this way (aliasing narrower types only strengthens it), so severity here is
"admission invariant broken, concrete unsoundness unproven". Also related: `_FORBIDDEN_ITEMS` impl pattern
`\bimpl\b[^;{}()]*(?:\bfor\b|\{)` stops at `(`, so `impl<F: Fn(u64)> Tr for S {}` / `impl<T: Fn()> View for X<T>`
is NOT matched (admitted; nested in a fn body or via the macro carrier).
Fix: in `_continues_after_block` continue only for `else`, the clause keywords, `{`, and binary-operator characters
(never `:`); reject any top-level header that does not start with an identifier or `#[`; reject `\bverus\s*!` and any
`!` followed by `{`/`(`/`[` at depth 0; make the impl ban `\bimpl\b` anywhere except directly after
`->`, `:`, `(`, `,`, `<`, `&`, `+`, `=` (argument/return position).

### H4. `admit` is banned only as `admit (`; `(admit)()` and `admit::<>()` pass admission and Verus (HOLE, Verus-confirmed)
`re.search(r"\badmit\s*\(")` misses the call spellings `(admit)()` and `admit::<>()` (vstd `pervasive::admit`
is in scope through the glob import).
helpers:
```
proof fn p1() ensures false { (admit)(); }
proof fn p2() ensures false { admit::<>(); }
```
`admit_helpers` -> ok. Verus: `7 verified, 0 errors` (two false-ensuring proof fns, i.e. false is derivable).
Fix: ban `\badmit\b` anywhere, exactly like `\bassume_?\b`; also ban `\bassume_new` / `\bassume_new_fallback`
(see below) and `\bexec_allows_no_decreases_clause\b`, `\bproof_from_false\b` already covered by `_ASSUME_NAME`.

## ATTACKS ATTEMPTED THAT FAILED OR ARE HARMLESS

All "admitted" rows were run through `admit_helpers(h, SPEC)`; "Verus" = real run.

| Attack (snippet) | Admitted | Result |
|---|---|---|
| `#[verifier::external_body]` / `external` / `external_fn_specification` / `external_type_specification` / `verifier(external_body)` (incl. whitespace, `r#`, `::verifier`, `verus::internal`, `#[doc=".."]` before, comment inside attr, `]` inside doc string) | no | rejected by the whitelist and the `external` regex |
| `#[cfg(..)]`, `#[cfg_attr(..)]`, `#[derive]`, `#[no_mangle]`, `#[verifier::admit]`, `#![verifier::external_body]` inner attribute, attribute on statement/expression | no | rejected |
| `#[verifier::exec_allows_no_decreases_clause]` | no | rejected |
| `loop { }` with `ensures false` | yes | Verus: `error: loop must have a decreases clause` -> harmless (also needs no extra rule) |
| exec recursion `fn d(x) ensures false { d(x) }` | yes | Verus: `error: recursive function must have a decreases clause` -> harmless |
| `while true { }` with `ensures false` | yes | same `loop` rule expected; the second run in my batch did not finish before I stopped (queue wait), not separately confirmed |
| `proof fn p() ensures false;` (bodyless) | yes | Verus: `a proof function must have a body (use the axiom keyword)` -> harmless; `axiom fn` / `pub axiom fn` are rejected by `_ASSUME_NAME` ("axiom") |
| bodyless exec `fn`, bodyless `spec fn` | yes | Verus/rustc: `E0308 mismatched types` -> harmless |
| `Tracked::<..>::assume_new()` / `Ghost::assume_new()` (not matched by `\bassume_?\b`) | yes | Verus: `verus_builtin::..::assume_new is not supported` -> harmless today, but ban the name anyway |
| `assume(false)`, `assume_ (`, `builtin::assume_`, `::builtin::assume_`, `assume_x(`, `admit (`, `vstd::pervasive::admit(`, `admit\n(` | no (except `assume_x` / `assume_it` as plain identifiers: admitted, harmless) | rejected |
| `fn admit_fnptr: let g = admit; g();` | yes | admitted (same root cause as H4; not separately run) |
| `unreached`, `proof_from_false`, `arbitrary`, `spec_affirm`, `axiom_*`, `unimplemented!` | no | rejected by name |
| `unsafe`, `unsafe {}`, `extern "C"`, `extern crate`, `const fn`, `async fn`, `tracked fn`, `uninterp spec fn`, `pub(crate) fn`, struct/enum-less items at top level, `use ..`, `mod`, `macro_rules!`, `thread_local!`, `static`, `trait`, `impl X for Y`, `impl X {}` | no | rejected (but see H3 for macro-hidden items and the `impl<..Fn(..)..>` pattern gap) |
| `std::fs`, `std::process`, `std :: process` (whitespace), `::std::fs`, `core::include_bytes!`, `env!`, `std::println` (path form) | no | rejected |
| `std::thread::spawn(...)` | yes | allowed by design (`thread` in `_STD_OK`); compute-only, DoS-only at worst; also unsupported by Verus (not verified) |
| `file!()`, `panic!()`, `cfg!(..)`, `union U {..}` nested in fn | yes | harmless (no host access; `panic!` must be proved unreachable by Verus; a union read needs `unsafe`) |
| `#[verifier::rlimit(0)]`, `rlimit(infinity)`, `opaque`, `loop_isolation(false)`, `spinoff_prover`, `memoize`, `truncate`, `inline`, `#[inline(always)]`, `#[allow(..)]` | yes | harmless / DoS-only: rlimit 0 or infinity just lifts the solver budget; the 25-minute wall per attempt still bounds it; `loop_isolation(false)` only adds facts to loops, `truncate` is modelled exactly by Verus |
| `requires false` helper with any ensures | yes | harmless: callers must prove `false` |
| helper named like a host item (`row_hit`, `sum_total`, `run_query`, `main`, `row_hex`) | no | rejected by `host_names` |
| helper `fn r#row_hit` / `spec fn r#sum_total` | yes | name regex reads the name as `r`; rustc then reports a duplicate definition (E0428), so a loud failure, harmless. Cheap fix: allow `r#` in the header name pattern |
| helper named like a vstd item (`lemma_mul_is_commutative`) or loader name (`load_cols_pre`) | yes | shadows a glob import only for host lemma bodies; Verus checks the helper, a duplicate of a loader name is a compile error; the emitted specs (I scanned four queries plus the lemma templates) call only host-defined free functions, so no spec meaning is reachable by shadowing; harmless |
| marker tricks: `// AGENT_EDIT_START` inside the helpers, `// AGENT_HELPERS_*` inside the body, `// HOST_LEMMAS_*` inside a region | yes | the text outside the first marker pair is discarded; fake markers in comments do not change what is stitched (`find` hits the host's markers first); at worst a duplicated region, still admitted twice |
| helper that mentions `f64` / `is_infinite_spec` to make the host add float lemmas | yes | host adds its own verified/trusted lemmas, could only cause a duplicate-name compile error |
| `main` / `hex_fn` in the assembled file calling an unqualified name a helper could shadow | n/a | main and loaders call only `row_hex`, `load_cols_*`, `run_query` and qualified paths; `row_hex`/`run_query`/`main` are blocked, `load_cols_*` collides loudly |
| timing spoof via `println!("QUERY_LATENCY_US: 1")` | not tested | `println!` is not path-qualified so the std path ban does not see it; Verus most likely rejects the macro in verified code, and the parse picks the first `QUERY_LATENCY_US:` match in stdout; pre-existing, unverified |

## Residual notes
* H1 and H2 are the serious ones: with either, the agent can choose its own `ensures` or add any trusted item and
  Verus reports `N verified, 0 errors`. They are independent of the exec-helper change, but H1 makes an
  `external_body` exec helper (callable from the body) a trivial carrier.
* After fixing the lexer, add tests that feed each snippet above to both `admit_helpers` and
  `admit_declarative_body`, and add an assembled-program invariant check (host `run_query` header present once,
  outside comments) so a future lexer gap cannot silently drop the host `ensures`.

## Resolution
H1-H4 fixed in declarative_spec/admit.py (strict lexer incl. raw strings and unterminated comment/string errors; `::` starts a new item; `verus!` and item-position `impl` rejected; `admit`/`assume_new` banned in any spelling). Tests: tests/test_declarative_exec_helpers.py (adversary section).
