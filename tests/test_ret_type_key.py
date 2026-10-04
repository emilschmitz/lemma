"""ret_type_key replaced the experimental codegen_exec module (whole-query trusted run_query)."""

from __future__ import annotations

import importlib

import pytest
from verus_transpiler.parse_sql import UnsupportedContractError, parse_sql
from verus_transpiler.ret_type_key import resolve_ret_type_key
from verus_transpiler.value_bounds import emit_trusted_prelude

SCHEMA = {"k": "int", "name": "string", "amount": "bigint"}


def test_single_key_group_by_ret_type() -> None:
    q = parse_sql("SELECT k, SUM(amount) FROM t GROUP BY k", SCHEMA)
    assert resolve_ret_type_key(q, SCHEMA) == "map_u32_u64"


def test_string_key_group_by_ret_type() -> None:
    q = parse_sql("SELECT name, SUM(amount) FROM t GROUP BY name", SCHEMA)
    assert resolve_ret_type_key(q, SCHEMA) == "map_str_u64"


def test_unsupported_key_shape_fails_loudly() -> None:
    q = parse_sql("SELECT k, SUM(amount) FROM t GROUP BY k", SCHEMA)
    q.groupby_columns = ["k", "k", "k", "k"]
    with pytest.raises(UnsupportedContractError):
        resolve_ret_type_key(q, SCHEMA)


def test_whole_query_trusted_generator_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("verus_transpiler.codegen_exec")
    from verus_transpiler import templates

    assert not hasattr(templates, "emit_trusted_run_query")


def test_prelude_has_no_opaque_view_spec() -> None:
    assert "hashmap_multi_agg_view" not in emit_trusted_prelude()
