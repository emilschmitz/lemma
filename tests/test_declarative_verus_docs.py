"""Verus docs index generation (tiny fake vstd tree) and the sandbox mount."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from declarative_spec.drive import mount_verus_docs
from declarative_spec.verus_docs import DOCS_CACHE, examples_index_markdown, lemmas_markdown

FAKE = """
/// Pushing then reading the last element.
pub proof fn lemma_push_last<A>(s: Seq<A>, a: A)
    requires
        s.len() > 0,
    ensures
        s.push(a).last() == a,
{
}

pub proof fn helper_not_lemma() {}

pub open spec fn double(x: int) -> int {
    x * 2
}

pub broadcast group group_fake_axioms {
    lemma_push_last,
    double,
}
"""


def test_lemmas_index_entries(tmp_path: Path) -> None:
    (tmp_path / "seq.rs").write_text(FAKE)
    md = lemmas_markdown(tmp_path)
    assert "## lemma_push_last" in md
    assert "- path: vstd/seq.rs:3  (proof fn)" in md
    assert "- requires: s.len() > 0," in md
    assert "- ensures: s.push(a).last() == a," in md
    assert "- doc: Pushing then reading the last element." in md
    assert "## helper_not_lemma" not in md
    assert "## double" in md and "(spec fn)" in md


def test_lemmas_index_group(tmp_path: Path) -> None:
    (tmp_path / "seq.rs").write_text(FAKE)
    md = lemmas_markdown(tmp_path)
    assert "## group_fake_axioms" in md
    assert "- members: lemma_push_last double" in md


def test_examples_index_features(tmp_path: Path) -> None:
    (tmp_path / "examples").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "examples" / "a.rs").write_text("while i < n invariant forall|j: int| #[trigger] s[j] > 0 decreases n - i {}")
    (tmp_path / "tests" / "b.rs").write_text("use vstd::seq::*; broadcast use group_seq_axioms; fn f(s: Seq<int>) {}")
    md = examples_index_markdown(tmp_path)
    a = next(l for l in md.splitlines() if l.startswith("examples/a.rs"))
    b = next(l for l in md.splitlines() if l.startswith("tests/b.rs"))
    for feat in ("invariant", "forall", "trigger", "decreases", "while loop"):
        assert feat in a
    assert "broadcast use" in b and "Seq" in b and "invariant" not in b


def test_mount_present_and_indexed(tmp_path: Path) -> None:
    mount_verus_docs(tmp_path)
    v = tmp_path / "verus"
    for sub in ("guide", "examples", "tests", "vstd"):
        assert any((v / sub).rglob("*")), sub
    assert "## lemma_" in (v / "LEMMAS.md").read_text()
    assert "examples/" in (v / "EXAMPLES_INDEX.md").read_text()
    assert "LEMMAS.md" in (v / "INDEX.md").read_text()
    assert not (v / "tests" / "cargo-tests").exists()


def test_fetch_script_pins_installed_commit() -> None:
    script = (Path(__file__).resolve().parent.parent / "research_loop/scripts/fetch_verus_docs.sh").read_text()
    assert "version.json" in script and 'test "$(git rev-parse HEAD)" = "$commit"' in script
    assert (DOCS_CACHE / "COMMIT").read_text().strip() == "3a4d30bcdc4571e7927af97be9c4664973083eda"
