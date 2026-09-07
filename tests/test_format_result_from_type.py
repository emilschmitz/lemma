"""format_result glue for admitted exec return types (incl. HashMapWithView)."""

from research_loop.format_result_from_type import format_result_for_exec_type


def test_hashmap_with_view_tuple_value_prints_map_len() -> None:
    expr = format_result_for_exec_type(
        "HashMapWithView<(String, String), (u64, u64, u64)>"
    )
    assert "map_len" in expr
    assert "RESULT:" in expr


def test_hashmap_with_view_pair_value_prints_map_len() -> None:
    expr = format_result_for_exec_type("HashMapWithView<(String, String), (u64, u64)>")
    assert "map_len" in expr


def test_u64_still_plain() -> None:
    assert "RESULT: {}" in format_result_for_exec_type("u64")
