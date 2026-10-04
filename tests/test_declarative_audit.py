"""Removed host lemmas stay removed everywhere the agent can see them; the hard reference bodies verify without them."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from declarative_spec.emit import emit_declarative_spec
from declarative_spec.lemma_index import lemma_index_markdown
from declarative_spec.prompt import build_declarative_prompt
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions

VERUS = Path("/home/emil/tools/verus/verus")
HARD = Path(__file__).parent / "fixtures" / "declarative_proofs" / "hard"
_PRE = {"pre": {"line": "bigint", "report": "bigint"}}

REMOVED = (
    "lemma_u64_add_fits",
    "lemma_i128_add_fits",
    "lemma_count_step_fits_u64",
    "lemma_count_step_fits_i128",
    "lemma_sum_step_fits_u64",
    "lemma_sum_step_fits_i128",
    "lemma_index_key_below_cap",
    "lemma_count_cnt_step",
    "lemma_hit_count_step",
)

HARD_CASES = {
    "count_distinct": "SELECT COUNT(DISTINCT report) AS c FROM pre",
    "two_key": "SELECT report, line, COUNT(*) AS c FROM pre GROUP BY report, line",
    "usum_nonlinear": "SELECT SUM(line) AS total FROM pre WHERE line > 5",
    "map_count": "SELECT report, COUNT(*) AS c FROM pre GROUP BY report",
}


def _spec(sql: str) -> str:
    return emit_declarative_spec(sql, _PRE, CatalogAssumptions(tables={"pre": TableAssumptions(max_rows=64)}))


@pytest.mark.parametrize("name", REMOVED)
def test_removed_lemma_is_not_in_index_or_prompt(name: str) -> None:
    index = lemma_index_markdown()
    prompt = build_declarative_prompt(sql="SELECT 1", spec_path="s", edit_path="e", lemma_index=index)
    assert name not in index
    assert name not in prompt


@pytest.mark.parametrize("name", REMOVED)
def test_removed_lemma_is_not_in_emitted_specs(name: str) -> None:
    for sql in HARD_CASES.values():
        assert name not in _spec(sql)


@pytest.mark.parametrize("name", sorted(HARD_CASES))
def test_hard_reference_body_never_calls_a_removed_lemma(name: str) -> None:
    body = (HARD / f"{name}.rs").read_text()
    assert not [r for r in REMOVED if r in body]


@pytest.mark.skipif(not VERUS.is_file(), reason="verus binary not installed")
@pytest.mark.parametrize("name", sorted(HARD_CASES))
def test_hard_reference_body_verifies_without_removed_lemmas(name: str) -> None:
    spec = _spec(HARD_CASES[name])
    src = spec.replace("// AGENT_EDIT_START\n// AGENT_EDIT_END", (HARD / f"{name}.rs").read_text())
    assert src != spec
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
        f.write(src)
    proc = subprocess.run(
        [str(VERUS), f.name, "--crate-type=lib", "--triggers-mode", "silent"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert "verification results::" in out and " 0 errors" in out, out[-2000:]


# --- Verus information setup: the agent can find what it needs with one grep each ---

import shlex  # noqa: E402

from declarative_spec.drive import mount_verus_docs  # noqa: E402
from declarative_spec.verus_docs import (  # noqa: E402
    DOCS_CACHE,
    LOOKUPS,
    guide_index_markdown,
    lemmas_markdown,
)

_FAKE_VSTD = """
pub struct Bag<K> { x: K }

impl<K> View for Bag<K> {
    type V = int;
}

impl<K> Bag<K> {
    /// Adds one.
    pub fn add_one(&mut self, k: K)
        ensures final(self)@ == old(self)@ + 1,
    {
    }
}

pub fn free_fn() {}

pub assume_specification<T, A: Allocator>[ Vec::<T, A>::push ](vec: &mut Vec<T, A>, value: T)
    ensures
        final(vec)@ == old(vec)@.push(value),
;

pub assume_specification[ <String as PartialEq>::eq ](s: &String, other: &String) -> (res: bool)
    ensures
        res == (s@ == other@),
;

pub assume_specification[<$uN as PartialEq<$uN>>::eq](x: &$uN, y: &$uN) -> bool;
"""


def test_index_names_methods_with_their_owner_and_leaves_free_fns_bare(tmp_path: Path) -> None:
    (tmp_path / "bag.rs").write_text(_FAKE_VSTD)
    md = lemmas_markdown(tmp_path)
    assert "## Bag::add_one" in md
    assert "- ensures: final(self)@ == old(self)@ + 1," in md
    assert "## free_fn" in md and "## Bag::free_fn" not in md


def test_index_has_std_exec_specs_with_clean_signature_and_ensures(tmp_path: Path) -> None:
    (tmp_path / "bag.rs").write_text(_FAKE_VSTD)
    md = lemmas_markdown(tmp_path)
    push = md.split("## Vec::push\n", 1)[1].split("\n\n", 1)[0]
    assert "- ensures: final(vec)@ == old(vec)@.push(value)," in push
    assert "assume_specification" in push and "String::eq" not in push
    eq = md.split("## String::eq\n", 1)[1].split("\n\n", 1)[0]
    assert "- trait: PartialEq" in eq and "- ensures: res == (s@ == other@)," in eq
    assert "$uN" not in md


def test_guide_index_has_title_and_headings_per_page(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Exists and choose\n\ntext\n\n## The choose operator\n\n### skipped\n")
    (tmp_path / "b.md").write_text("no heading at all\n")
    md = guide_index_markdown(tmp_path)
    assert "guide/a.md: Exists and choose | The choose operator" in md
    assert "guide/b.md: " in md


needs_docs = pytest.mark.skipif(not (DOCS_CACHE / "COMMIT").is_file(), reason="run fetch_verus_docs.sh")


@pytest.fixture(scope="module")
def verus_mount(tmp_path_factory: pytest.TempPathFactory) -> Path:
    ro = tmp_path_factory.mktemp("ro")
    mount_verus_docs(ro)
    return ro / "verus"


@needs_docs
@pytest.mark.parametrize("task, args, expect", LOOKUPS, ids=[t for t, _, _ in LOOKUPS])
def test_each_lookup_is_one_grep_in_a_built_workspace(verus_mount: Path, task: str, args: str, expect: str) -> None:
    proc = subprocess.run(["grep", *shlex.split(args)], cwd=verus_mount, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"{task}: grep {args} found nothing"
    assert expect in proc.stdout, f"{task}: {expect!r} not in output of grep {args}"


@needs_docs
def test_twelve_topics_are_covered_by_the_lookup_table() -> None:
    joined = " ".join(t.lower() for t, _, _ in LOOKUPS)
    for topic in (
        "subrange", "decreases", "hashmapwithview", "stringhashmap", "string equality", "vec::push",
        "assert forall", "nonlinear_arith", "broadcast use", "reveal", "opaque", "choose", "invariant",
    ):
        assert topic in joined, topic


@needs_docs
def test_index_md_carries_every_recipe_and_points_at_the_three_indexes(verus_mount: Path) -> None:
    index = (verus_mount / "INDEX.md").read_text()
    for _task, args, _ in LOOKUPS:
        assert f"`grep {args}`" in index
    for name in ("LEMMAS.md", "EXAMPLES_INDEX.md", "GUIDE_INDEX.md"):
        assert name in index
        assert (verus_mount / name).is_file()


def test_prompt_points_at_the_indexes_and_does_not_deny_the_hash_map_source() -> None:
    prompt = build_declarative_prompt(sql="SELECT 1", spec_path="s", edit_path="e", lemma_index="x")
    assert "`GUIDE_INDEX.md`" in prompt and "`INDEX.md`" in prompt
    assert "is not a file in this workspace" not in prompt
    assert '^## StringHashMap::' in prompt
