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
