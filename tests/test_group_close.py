"""The host-proved closing lemmas of a grouped query (declarative_spec/group_close.py) verify with the emitted spec, and a mutated one does not."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

DB = Path("/home/emil/projects/lemma-db/holdout/gendb_sec_edgar/duckdb/sec_edgar_dec.duckdb")
SQL = (
    "SELECT s.fy, s.afs, COUNT(DISTINCT s.adsh) AS n_filings, SUM(n.value) AS total FROM num n JOIN sub s ON n.adsh = s.adsh "
    "WHERE n.uom = 'USD' AND s.fy IS NOT NULL GROUP BY s.fy, s.afs ORDER BY total DESC LIMIT 7"
)


def _spec(monkeypatch: pytest.MonkeyPatch) -> str:
    if not DB.is_file():
        pytest.skip("SEC database not available")
    monkeypatch.setenv("LEMMA_DUCKDB_PATH", str(DB))
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    from research_loop.scripts import declarative_manual as dm
    from research_loop.trust_configs import apply_trust_config

    with apply_trust_config("adversary_declarative0"):
        return dm.regenerate_spec("sec", SQL)


def _verify(text: str, tmp_path: Path) -> str:
    from research_loop.harness import resolve_verus_bin

    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    text = text.replace("// AGENT_EDIT_START", "// AGENT_EDIT_START\nVec::new()", 1) + "\nfn main() {}\n"
    path = tmp_path / "close.rs"
    path.write_text(text)
    proc = subprocess.run(
        [str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"), str(path), "--triggers-mode", "silent"],
        capture_output=True, text=True, timeout=900, check=False,
    )
    return proc.stdout + proc.stderr


def test_the_four_lemmas_are_emitted_and_verify(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec = _spec(monkeypatch)
    for name in ("lemma_group_close_rows", "lemma_group_close_distinct", "lemma_group_close_present", "lemma_group_close_omitted"):
        assert f"pub proof fn {name}(" in spec
    log = _verify(spec, tmp_path)
    # the only failing item is the empty run_query body used here (its postconditions), not a host lemma
    assert len(re.findall(r"^error: postcondition not satisfied", log, re.M)) == 1, log[-2000:]
    assert "function body check" not in log and "assertion failed" not in log


def test_a_broken_lemma_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec = _spec(monkeypatch)
    start = spec.index("pub proof fn lemma_group_close_distinct(")
    broken = spec[:start] + spec[start:].replace("assert(gk[sel[a]] != gk[sel[b]]);", "assert(gk[sel[a]] == gk[sel[b]]);", 1)
    assert broken != spec
    log = _verify(broken, tmp_path)
    assert "assertion failed" in log
