"""Host-proved COUNT(DISTINCT) library for a two-table join: emitted next to the spec, verified by Verus, and refuted when mutated."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from declarative_spec.distinct_lemmas import distinct_lemmas

KT = "((bool, int), (bool, Seq<char>))"
JOIN = dict(
    name="count_distinct_n_filings",
    hit="row_hit(n, s, i0, i1) && key_at(n, s, i0, i1) == k",
    value="count_distinct_n_filings_val",
    vt="Seq<char>",
    idxs=["i0", "i1"],
    params=[("n", "Cols_num"), ("s", "Cols_sub")],
    bounds=["n", "s"],
    key_ty=KT,
)

# A tiny, complete spec in the emitter's exact fold shape (see emit_surface._emit_fold / _later).
TOY = """use vstd::prelude::*;
use vstd::set::*;
use vstd::seq::*;
verus! {
pub struct Cols_num { pub n: usize, pub a: Vec<u32> }
pub struct Cols_sub { pub n: usize, pub b: Vec<u32>, pub g: Vec<u32> }
pub open spec fn row_hit(n: &Cols_num, s: &Cols_sub, i0: int, i1: int) -> bool {
    &&& 0 <= i0 < n.n as int
    &&& 0 <= i1 < s.n as int
    &&& n.a@[i0] == s.b@[i1]
}
pub open spec fn key_at(n: &Cols_num, s: &Cols_sub, i0: int, i1: int) -> ((bool, int), (bool, Seq<char>)) {
    ((true, (if 0 <= i1 < s.n as int { s.g@[i1] as int } else { 0int })), (false, Seq::<char>::empty()))
}
pub open spec fn count_distinct_n_filings_val(n: &Cols_num, s: &Cols_sub, i0: int, i1: int) -> Seq<char> {
    if 0 <= i1 < s.n as int { seq!['a'].push(('0' as int + s.b@[i1] as int) as char) } else { Seq::<char>::empty() }
}
pub open spec fn count_distinct_n_filings_d1(n: &Cols_num, s: &Cols_sub, i0: int, i1: int, k: ((bool, int), (bool, Seq<char>))) -> int
    decreases s.n as int - i1
{
    if i1 < 0 || i1 >= s.n as int {
        0int
    } else {
        (if row_hit(n, s, i0, i1) && key_at(n, s, i0, i1) == k && !(exists|j0: int, j1: int| ((j0 > i0) || (j0 == i0 && j1 > i1)) && row_hit(n, s, j0, j1) && key_at(n, s, j0, j1) == k && count_distinct_n_filings_val(n, s, j0, j1) == count_distinct_n_filings_val(n, s, i0, i1)) { 1int } else { 0int }) + count_distinct_n_filings_d1(n, s, i0, i1 + 1, k)
    }
}
pub open spec fn count_distinct_n_filings(n: &Cols_num, s: &Cols_sub, i0: int, k: ((bool, int), (bool, Seq<char>))) -> int
    decreases n.n as int - i0
{
    if i0 < 0 || i0 >= n.n as int {
        0int
    } else {
        count_distinct_n_filings_d1(n, s, i0, 0, k) + count_distinct_n_filings(n, s, i0 + 1, k)
    }
}
"""


def _verify(text: str, tmp_path: Path) -> tuple[bool, str]:
    from research_loop.harness import resolve_verus_bin

    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    path = tmp_path / "distinct.rs"
    path.write_text(text + "\nfn main() {}\n}\n")
    proc = subprocess.run(
        [str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"), str(path), "--triggers-mode", "silent"],
        capture_output=True, text=True, timeout=600, check=False,
    )
    log = proc.stdout + proc.stderr
    return "verification results:: " in log and " 0 errors" in log, log


def test_only_a_two_table_join_gets_the_library() -> None:
    assert distinct_lemmas(**{**JOIN, "idxs": ["i0"], "bounds": ["n"]}) == ""  # one table: the agent proves its own
    assert distinct_lemmas(**{**JOIN, "idxs": ["i0", "i1", "i2"], "bounds": ["n", "s", "t"]}) == ""
    text = distinct_lemmas(**JOIN)
    for item in ("lemma_count_distinct_n_filings_is_set_len", "lemma_count_distinct_n_filings_value", "lemma_count_distinct_n_filings_set_step", "count_distinct_n_filings_pset"):
        assert item in text
    ungrouped = distinct_lemmas(**{**JOIN, "key_ty": None, "hit": "row_hit(n, s, i0, i1)"})
    assert ", k" not in ungrouped and "lemma_count_distinct_n_filings_is_set_len" in ungrouped


def test_library_verifies_and_mutations_fail(tmp_path: Path) -> None:
    lib = distinct_lemmas(**JOIN)
    ok, log = _verify(TOY + lib, tmp_path)
    assert ok, log[-3000:]
    # mutation 1: the prefix set includes the current row
    bad1 = lib.replace("j0 < i0 && count_distinct_n_filings_hit", "j0 <= i0 && count_distinct_n_filings_hit", 1)
    assert bad1 != lib and not _verify(TOY + bad1, tmp_path)[0]
    # mutation 2: the claimed count is off by one
    old = "count_distinct_n_filings(n, s, i0, k) == count_distinct_n_filings_set(n, s, i0, k).len(),"
    assert old in lib
    bad2 = lib.replace(old, old.rstrip(",") + " + 1,", 1)
    assert not _verify(TOY + bad2, tmp_path)[0]
