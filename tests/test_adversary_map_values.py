"""Adversary judge scores group-by map key/value pairs against DuckDB."""

from __future__ import annotations

from research_loop.adversary.judge import (
    _duck_rows_as_map_tuples,
    _flatten_map_kv,
    _parse_map_kvs,
    _parse_map_len,
)
from research_loop.trusted_ret_bridge import vstd_map_dump_format


def test_flatten_map_kv_shapes() -> None:
    assert _flatten_map_kv(1, 10) == (1, 10)
    assert _flatten_map_kv((1, 2), 10) == (1, 2, 10)
    assert _flatten_map_kv(1, (10, 20)) == (1, 10, 20)
    assert _flatten_map_kv((1, 2), (10, 20)) == (1, 2, 10, 20)


def test_parse_map_kvs_and_len() -> None:
    stdout = "RESULT: map_len=2\nMAP_KV\t1\t10\nMAP_KV\t2\t20\n"
    assert _parse_map_len(stdout) == 2
    assert _parse_map_kvs(stdout) == [(1, 10), (2, 20)]


def test_parse_map_kvs_tuple_keys() -> None:
    stdout = "RESULT: map_len=1\nMAP_KV\t(1, 2)\t99\n"
    assert _parse_map_kvs(stdout) == [(1, 2, 99)]


def test_duck_rows_normalize_ints() -> None:
    assert _duck_rows_as_map_tuples([(1, 10), (2, 20)]) == [(1, 10), (2, 20)]


def test_vstd_map_dump_emits_peel_and_pairs() -> None:
    fmt = vstd_map_dump_format("HashMapWithView<u32, u128>")
    assert "_LemmaMapPeel" in fmt
    assert "MAP_KV" in fmt
    assert "map_len={}" in fmt
    fmt2 = vstd_map_dump_format("HashMapWithView<(u32, u32), u128>")
    assert "HashMapWithView<(u32, u32), u128>" in fmt2
