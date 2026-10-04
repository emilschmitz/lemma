"""The fast-helper menu must typecheck when it is spliced in.

Sequence length is a nat. These helpers return int. Returning the length
without a cast fails compilation of every program built with
LEMMA_FAST_TRUSTEDS=1, before the query body is checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.agent_primitives.emit_externs import emit_agent_externs
from research_loop.harness import resolve_verus_bin, run_verus_verify

_HEADER = "use vstd::prelude::*;\nverus! {\n\n"
_FOOTER = "\n}\nfn main() {}\n"


def _verify(tmp_path: Path, name: str, body: str) -> None:
    if resolve_verus_bin() is None:
        pytest.skip("verus not found")
    path = tmp_path / name
    path.write_text(_HEADER + body + _FOOTER, encoding="utf-8")
    ok, log = run_verus_verify(str(path), timeout=120)
    assert ok, log


def test_core_fast_helpers_typecheck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "0")
    monkeypatch.delenv("LEMMA_ENABLE_PARALLEL", raising=False)
    body = emit_agent_externs(enable_parallel=False)
    assert "probe_sum_u64_pair_len" in body
    assert "par_filter_sum_u64_pair_len" not in body
    _verify(tmp_path, "core.rs", body)


def test_parallel_fast_helpers_typecheck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_FAST_TRUSTEDS", "1")
    body = emit_agent_externs(enable_parallel=True)
    assert "probe_sum_u64_pair_len" in body
    assert "par_filter_sum_u64_pair_len" in body
    assert "vector_filter_sum_u64_pair_len" in body
    _verify(tmp_path, "both.rs", body)
