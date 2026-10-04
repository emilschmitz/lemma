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


def _core_body() -> str:
    return emit_agent_externs(enable_parallel=False)


def test_core_primitives_have_no_external_body() -> None:
    body = _core_body()
    assert "external_body" not in body
    for sym in (
        "build_zone_map_u32",
        "may_satisfy_range_u32",
        "build_hashset_u32",
        "probe_sum_u64",
        "decode_dict_str",
    ):
        assert f"pub exec fn {sym}" in body


def test_core_primitives_client_behavior(tmp_path: Path) -> None:
    """Callers see the ensures: zone_rows == 0 gives no zones, set/probe/decode contracts hold."""
    client = """
fn client_zero_rows(col: &Vec<u32>) {
    let z = build_zone_map_u32(col, 0);
    assert(z@.len() == 0);
}

fn client_range(seg: &ZoneSegmentU32) {
    let b = may_satisfy_range_u32(seg, 5, 9);
    assert(b == (seg.max >= 5 && seg.min <= 9));
}

fn client_set(keys: &Vec<u32>, probe: &Vec<u32>, vals: &Vec<u64>) {
    let s = build_hashset_u32(keys, 0);
    assert(s@ == hashset_u32_keys_from_seq(keys@));
    let t = probe_sum_u64(probe, vals, &s);
    assert(t == probe_sum_u64_spec(probe@, vals@, s@));
}

fn client_decode(codes: &Vec<u32>, dict: &Vec<String>)
    requires
        codes@.len() > 0,
        (codes[0] as int) < dict@.len(),
{
    let s = decode_dict_str(codes, dict, 0);
    assert(s == dict[codes[0] as int]);
}
"""
    body = _core_body().replace("use vstd::hash_set::HashSetWithView;\n\n", "")
    _verify(
        tmp_path,
        "client.rs",
        "use vstd::hash_set::HashSetWithView;\n" + body + client,
    )
