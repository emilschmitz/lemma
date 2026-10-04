"""Adversary judge scores group-by map cardinality against DuckDB."""

from __future__ import annotations

from research_loop.adversary.judge import (
    _MAP_LEN_SCOREABLE,
    _parse_map_len,
    _parse_printed_result,
    _scoreable_ret,
)


def test_map_u32_u64_is_scoreable_for_cardinality() -> None:
    assert "map_u32_u64" in _MAP_LEN_SCOREABLE
    assert "map_u32__u128" in _MAP_LEN_SCOREABLE
    assert "map_u32_u32__u128" in _MAP_LEN_SCOREABLE
    assert _scoreable_ret("map_u32_u64")
    assert _scoreable_ret("map_u32__u128")
    assert _scoreable_ret("map_u32_u32__u128")
    assert _scoreable_ret("u64")
    assert not _scoreable_ret("seq_u64")


def test_parse_map_len_from_printer() -> None:
    assert _parse_map_len("RESULT: map_len=3\n") == 3
    assert _parse_map_len("noise\nRESULT: map_len=0\n") == 0
    assert _parse_map_len("RESULT: 7\n") is None


def test_map_len_is_not_an_opaque_block_for_scalar_parser() -> None:
    printed, reason = _parse_printed_result("RESULT: map_len=2\n")
    assert printed is None
    assert reason == "map_len_only"
