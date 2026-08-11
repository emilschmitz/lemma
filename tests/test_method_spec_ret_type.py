"""MethodSpec return-type parsing and RET_TYPE_CONFIG key resolution."""

from __future__ import annotations

import pytest

from research_loop.assemble_runquery import build_runquery_agent_source
from research_loop.method_spec_ret_type import (
    parse_method_spec_return_type,
    resolve_ret_type_from_method_spec,
    ret_key_from_method_spec_type,
)
from verus_transpiler import transpile_sql_to_verus

_HAVING_SCHEMA = {"K": "int", "S": "string", "V": "bigint"}
_HAVING_SQL = "SELECT K, S, SUM(V) FROM t GROUP BY K, S HAVING SUM(V) > 10"
_SCALAR_SQL = "SELECT SUM(V) FROM t"
_SCALAR_SCHEMA = {"V": "bigint"}
_THREE_KEY_SQL = "SELECT k, s1, s2, SUM(v) FROM t GROUP BY k, s1, s2"
_THREE_KEY_SCHEMA = {"K": "int", "S1": "string", "S2": "string", "V": "bigint"}


def _method_spec_return(spec_text: str) -> str:
    return parse_method_spec_return_type(spec_text)


def test_parse_scalar_u64_method_spec() -> None:
    raw = transpile_sql_to_verus(_SCALAR_SQL, _SCALAR_SCHEMA)
    assert _method_spec_return(raw) == "u64"
    assert resolve_ret_type_from_method_spec(raw) == "u64"


def test_parse_map_u32_str_u64_method_spec() -> None:
    raw = transpile_sql_to_verus(_HAVING_SQL, _HAVING_SCHEMA)
    assert _method_spec_return(raw) == "Map<(u32, Seq<char>), u64>"
    assert resolve_ret_type_from_method_spec(raw) == "map_u32_str_u64"


def test_parse_map_str_u32_u64_method_spec() -> None:
    spec = """pub open spec fn method_spec(cols: &Cols) -> Map<(Seq<char>, u32), u64>
    recommends valid_cols(cols),
{
    Map::empty()
}"""
    assert parse_method_spec_return_type(spec) == "Map<(Seq<char>, u32), u64>"
    assert resolve_ret_type_from_method_spec(spec) == "map_str_u32_u64"


def test_build_runquery_agent_source_map_str_u32_u64() -> None:
    src = build_runquery_agent_source(ret_type="map_str_u32_u64")
    assert "HashMapWithView<(String, u32), u64>" in src
    assert "res@ == method_spec(cols)," in src


def test_parse_map_u32_str_str_u64_method_spec() -> None:
    raw = transpile_sql_to_verus(_THREE_KEY_SQL, _THREE_KEY_SCHEMA)
    assert _method_spec_return(raw) == "Map<(u32, Seq<char>, Seq<char>), u64>"
    assert resolve_ret_type_from_method_spec(raw) == "map_u32_str_str_u64"


def test_build_runquery_agent_source_map_u32_str_str_u64() -> None:
    src = build_runquery_agent_source(ret_type="map_u32_str_str_u64")
    assert "HashMapWithView<(u32, String, String), u64>" in src
    assert "res@ == method_spec(cols)," in src


def test_unsupported_method_spec_return_type_raises() -> None:
    bogus = "pub open spec fn method_spec(cols: &Cols) -> Map<u32, Map<u32, u64>>\n    recommends valid_cols(cols),\n{\n    Map::empty()\n}"
    with pytest.raises(ValueError, match=r"^unsupported MethodSpec return type:"):
        ret_key_from_method_spec_type(parse_method_spec_return_type(bogus))
    with pytest.raises(ValueError, match=r"^unsupported MethodSpec return type:"):
        resolve_ret_type_from_method_spec(bogus)


def test_resolve_seq_projection_method_spec() -> None:
    spec = """pub open spec fn method_spec(cols: &Cols) -> Seq<(Seq<char>, Seq<char>, u64)>
    recommends valid_cols(cols),
{
    Seq::empty()
}"""
    key = resolve_ret_type_from_method_spec(spec)
    assert key == "seq_str_str_u64"
    src = build_runquery_agent_source(ret_type=key)
    assert "Vec<(String, String, u64)>" in src
    assert "vec_str_str_u64_view(res@) == method_spec(cols)," in src


def test_parse_handles_multiline_return_type() -> None:
    spec = """pub open spec fn method_spec(cols: &Cols) -> Map<(
    u32,
    Seq<char>
), u64>
    recommends valid_cols(cols),
{
    Map::empty()
}"""
    parsed = parse_method_spec_return_type(spec)
    assert "Map<" in parsed
    assert "u32" in parsed
    assert "Seq<char>" in parsed
    assert parsed.endswith("u64>")
    assert resolve_ret_type_from_method_spec(spec) == "map_u32_str_u64"
