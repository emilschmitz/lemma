"""The helper region may hold plain (exec) `fn` items, verified by Verus against their own requires/ensures.

Trust must not drop: every form that turns checking off or restates a trusted spec stays rejected in both regions.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.admit import admit_declarative_body, admit_helpers, declarative_edit_from_file
from declarative_spec.assemble import assemble_declarative_program
from tests.test_declarative_vec_outrow_proof import BODIES, USUM, VERUS, _accepted, _spec, needs_verus

ROOT = Path(__file__).resolve().parents[1]
SPEC = _spec(USUM[1], USUM[2])
BODY = (BODIES / f"{USUM[0]}.rs").read_text()

WIDEN = "fn widen(x: i64) -> (r: i128)\n    ensures r as int == x as int\n{\n    x as i128\n}\n"


@pytest.mark.parametrize(
    "helpers",
    [
        WIDEN,
        "pub fn inc(x: u64) -> (r: u64)\n    requires x < 100,\n    ensures r == x + 1\n{\n    x + 1\n}",
        "exec fn id(x: u64) -> (r: u64) ensures r == x { x }",
        "#[verifier::rlimit(20)]\nfn id(x: u64) -> (r: u64) ensures r == x { x }",
        "#[verifier::truncate]\nfn low(x: u64) -> (r: u8) { x as u8 }",
        "#[verifier::loop_isolation(false)]\nfn id(x: u64) -> (r: u64) ensures r == x { x }",
        (
            "fn count_to(n: u64) -> (r: u64) ensures r == n {\n"
            "    let mut i: u64 = 0;\n"
            "    while i < n invariant i <= n, decreases n - i { i += 1; }\n"
            "    i\n}"
        ),
        "fn id(x: u64) -> (r: u64) ensures r == x { x }\nproof fn p() { }\nspec fn s() -> int { 1 }",
    ],
)
def test_exec_helper_is_admitted(helpers: str) -> None:
    result = admit_helpers(helpers, SPEC)
    assert result.ok, result.violations


@pytest.mark.parametrize(
    "helpers",
    [
        "#[verifier::external_body]\nfn f(x: u64) -> (r: u64) ensures r == x + 1;",
        "#[verifier::external_body]\nfn f(x: u64) -> (r: u64) ensures false { x }",
        "#[verifier(external_body)]\nfn f(x: u64) -> (r: u64) ensures false { x }",
        "#[verifier::external]\nfn f(x: u64) -> u64 { x }",
        "#[verifier::external_fn_specification]\nfn ex_f(x: u64) -> (r: u64) ensures false { x }",
        "#[cfg_attr(verus_keep_ghost, verifier::external_body)]\nfn f() { }",
        "#[verifier::exec_allows_no_decreases_clause]\nfn f(x: u64) -> (r: u64) ensures false { loop { } }",
        "#[cfg(not(verus_keep_ghost))]\nfn f() { }",
        "#[derive(Clone)]\nfn f() { }",
        "#[no_mangle]\nfn f() { }",
        "#[verifier::admit]\nfn f() { }",
        "fn f(x: u64) -> (r: u64) ensures r == x { assume(false); x }",
        "fn f(x: u64) -> (r: u64) ensures r == x { proof { admit(); } x }",
        "unsafe fn f() { }",
        "fn f() { unsafe { } }",
        "extern \"C\" fn f() { }",
        "const fn f() { }",
        "async fn f() { }",
        "assume_specification[ foo ] () ;",
        "impl Clone for S { fn clone(&self) -> S { S } }",
        "impl S { fn f() { } }",
        "trait T { fn f(); }",
        "macro_rules! m { () => { }; }",
        "fn f() { macro_rules! m { () => { }; } }",
        "fn f() { thread_local!(static X: u64 = 1); }",
        "static X: u64 = 1;",
        "mod m { }",
        "use vstd::seq::*;",
        "fn f() { let x = std::fs::read(\"a\"); }",
        "fn f() { let x = include_str!(\"a\"); }",
    ],
)
def test_forbidden_forms_are_rejected_in_the_helper_region(helpers: str) -> None:
    assert not admit_helpers(helpers, SPEC).ok, helpers


@pytest.mark.parametrize(
    "bad",
    [
        "#[verifier::exec_allows_no_decreases_clause]\nfn f() {}",
        "#[cfg(not(verus_keep_ghost))]\nfn f() {}",
        "#[derive(Clone)]\nstruct S;",
        "impl Clone for S { }",
        "impl S { fn f() { } }",
        "trait T { }",
        "macro_rules! m { () => { }; }",
        "static X: u64 = 1;",
        "#[verifier::external_body]\nfn f() {}",
    ],
)
def test_the_same_forms_are_rejected_in_the_body(bad: str) -> None:
    assert not admit_declarative_body(bad + "\n0u64").ok, bad


def test_lifetimes_and_impl_trait_arguments_are_not_mistaken_for_items() -> None:
    ok = "fn f<'a>(x: &'a str, g: impl Fn(u64) -> u64) -> (r: u64) { g(1) }"
    assert admit_helpers(ok, SPEC).ok
    assert admit_declarative_body("let s: &'static str = 1;\n0u64").ok


def test_exec_helper_name_may_not_reuse_a_host_name_or_repeat() -> None:
    assert not admit_helpers("fn row_hit(x: u64) { }", SPEC).ok
    assert not admit_helpers("fn a() { }\nfn a() { }", SPEC).ok


def test_declarative_edit_from_file_takes_a_file_with_an_exec_helper() -> None:
    agent = SPEC.replace("// AGENT_EDIT_START\n// AGENT_EDIT_END", f"// AGENT_EDIT_START\n{BODY}\n// AGENT_EDIT_END").replace(
        "// AGENT_HELPERS_START\n// AGENT_HELPERS_END", f"// AGENT_HELPERS_START\n{WIDEN}\n// AGENT_HELPERS_END"
    )
    assert declarative_edit_from_file(agent, SPEC).strip() == BODY.strip()


# ---- a real Verus run ----------------------------------------------------------------------


def _verus(helpers: str, body: str) -> str:
    program = assemble_declarative_program(SPEC, body, helpers=helpers)
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False) as f:
        f.write(program)
    proc = subprocess.run(
        [str(ROOT / "scripts" / "ram" / "verus_guarded.sh"), f.name, "--crate-type=lib", "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    return proc.stdout + "\n" + proc.stderr


_USE = "acc = acc + (line as i128);"
_USES_HELPER = BODY.replace(_USE, "acc = acc + widen(line);")


@needs_verus
def test_run_query_calling_a_verified_exec_helper_verifies() -> None:
    assert _USE in BODY
    out = _verus(WIDEN, _USES_HELPER)
    assert _accepted(out), out[-3000:]


@needs_verus
def test_helper_whose_own_body_does_not_prove_its_ensures_is_rejected() -> None:
    bad = "fn widen(x: i64) -> (r: i128)\n    ensures r as int == x as int + 1\n{\n    x as i128\n}\n"
    out = _verus(bad, _USES_HELPER)
    assert not _accepted(out), out[-2000:]


@needs_verus
def test_a_helper_that_proves_a_different_ensures_makes_run_query_fail_not_pass() -> None:
    off_by_one = "fn widen(x: i64) -> (r: i128)\n    ensures r as int == x as int + 1\n{\n    x as i128 + 1\n}\n"
    out = _verus(off_by_one, _USES_HELPER)
    assert not _accepted(out), out[-2000:]


# ---- adversary findings (research_loop/menus/exec_helpers_ADVERSARY_VERDICT.md) -------------------------------------


@pytest.mark.parametrize(
    "helpers",
    [
        # H1: a raw string ending in a backslash must not hide the item between two quotes
        'fn k() { let a = r"\\"; }\n#[verifier::external_body] fn lie() -> (r: u64) ensures false { 0 }\nfn m() { let b = r"\\"; let c = "\\""; }',
        'fn k() { let a = r#"x"#; }\nproof fn p() { assume(false); }\n',
        # H2: an unterminated comment / string would swallow the host signature that follows the region
        "fn f() { }\n/* open",
        'fn f() { let s = "open; }',
        'fn f() { let s = r#"open; }',
        # H3: a path-led macro item hides non-fn items from the header check
        "fn a() { }\n::vstd::prelude::verus! { struct S { x: u64 } }",
        "fn a() { }\nverus! { struct S { x: u64 } }",
        "impl<F: Fn(u64)> Tr for S { }",
        # H4: admit spelled so that `admit (` does not match
        "proof fn p() ensures false { (admit)(); }",
        "proof fn p() ensures false { admit::<>(); }",
        "proof fn p() ensures false { let g = admit; g(); }",
        "fn f() { let t = Tracked::assume_new(); }",
    ],
)
def test_adversary_smuggling_forms_are_rejected_in_helpers(helpers: str) -> None:
    assert not admit_helpers(helpers, SPEC).ok, helpers


@pytest.mark.parametrize(
    "body",
    [
        'let a = r"\\"; assume(false); let b = r"\\"; 0u64',
        "/* open\n0u64",
        "(admit)();\n0u64",
        "admit::<>();\n0u64",
    ],
)
def test_adversary_smuggling_forms_are_rejected_in_the_body(body: str) -> None:
    assert not admit_declarative_body(body).ok, body


def test_raw_strings_and_lifetimes_that_are_fine_stay_admitted() -> None:
    assert admit_helpers('fn f<\'a>(x: &\'a str) -> (r: u64) { let s = r#"a "b" c"#; let t = br"x"; 1 }', SPEC).ok
    assert admit_helpers('fn f() { let r = 1u64; let br = 2u64; let _ = r + br; }', SPEC).ok
