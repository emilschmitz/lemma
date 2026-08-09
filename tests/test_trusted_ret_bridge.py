"""Structural MethodSpec return-type → Trusted/shell bridge."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_loop.assemble_runquery import build_runquery_agent_source
from research_loop.method_spec_ret_type import (
    parse_method_spec_return_type,
    resolve_ret_type_from_method_spec,
    ret_key_from_method_spec_type,
)
from research_loop.trusted_ret_bridge import (
    get_bridge,
    parse_verus_type,
    spec_to_exec_type,
    structural_bridge_for_spec_type,
)
from verus_transpiler import transpile_sql_to_verus

ROOT = Path(__file__).resolve().parents[1]
QUERIES_PATH = ROOT / "holdout" / "gendb_sec_edgar" / "queries.sql"

SEC_SCHEMA: dict[str, dict[str, str]] = {
    "pre": {
        "stmt": "string",
        "rfile": "string",
        "adsh": "string",
        "line": "int",
        "tag": "string",
        "version": "string",
        "plabel": "string",
    },
    "num": {
        "adsh": "string",
        "tag": "string",
        "version": "string",
        "uom": "string",
        "value": "double",
        "ddate": "int",
    },
    "sub": {
        "adsh": "string",
        "name": "string",
        "cik": "int",
        "sic": "int",
        "fy": "int",
    },
    "tag": {
        "tag": "string",
        "version": "string",
        "tlabel": "string",
        "abstract": "int",
    },
}


def _spec(ret: str) -> str:
    return f"""pub open spec fn method_spec(cols: &Cols) -> {ret}
    recommends valid_cols(cols),
{{
    Map::empty()
}}"""


def _load_sec_queries() -> list[tuple[str, str]]:
    text = QUERIES_PATH.read_text()
    out: list[tuple[str, str]] = []
    for m in re.finditer(
        r"-- Q(\d+):.*?\n(SELECT.*?;)",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        out.append((m.group(1), m.group(2).strip()))
    return out


@pytest.mark.parametrize(
    ("spec_ret", "expected_key", "rust_fragment", "trusted_fragment"),
    [
        (
            "Map<(Seq<char>, Seq<char>), (u64, u64)>",
            "map_str_str__u64_u64",
            "HashMap<(String, String), (u64, u64)>",
            "agg_put_str_str__u64_u64",
        ),
        (
            "Seq<(Seq<char>, Seq<char>, u64)>",
            "seq_str_str_u64",
            "Vec<(String, String, u64)>",
            "vec_str_str_u64_view",
        ),
        (
            "Map<(Seq<char>, Seq<char>), (u64, u64, u64)>",
            "map_str_str__u64_u64_u64",
            "HashMap<(String, String), (u64, u64, u64)>",
            "hashmap_str_str__u64_u64_u64_view",
        ),
        (
            "Map<(u32, Seq<char>, Seq<char>), (u64, u64, u64)>",
            "map_u32_str_str__u64_u64_u64",
            "HashMap<(u32, String, String), (u64, u64, u64)>",
            "agg_add_u32_str_str__u64_u64_u64",
        ),
        (
            "Map<(Seq<char>, Seq<char>, Seq<char>, Seq<char>), (u64, u64)>",
            "map_str_str_str_str__u64_u64",
            "HashMap<(String, String, String, String), (u64, u64)>",
            "agg_put_str_str_str_str__u64_u64",
        ),
    ],
)
def test_structural_bridge_shapes(
    spec_ret: str,
    expected_key: str,
    rust_fragment: str,
    trusted_fragment: str,
) -> None:
    bridge = structural_bridge_for_spec_type(spec_ret)
    assert bridge.key == expected_key
    assert rust_fragment in bridge.rust_ret
    assert trusted_fragment in bridge.trusted_rs
    src = build_runquery_agent_source(ret_type=bridge.key)
    assert rust_fragment in src
    assert bridge.ensures in src


def test_static_u64_and_map_str_u32_u64_still_work() -> None:
    assert ret_key_from_method_spec_type("u64") == "u64"
    assert ret_key_from_method_spec_type("Map<(Seq<char>, u32), u64>") == "map_str_u32_u64"
    src = build_runquery_agent_source(ret_type="map_str_u32_u64")
    assert "HashMap<(String, u32), u64>" in src
    assert "hashmap_str_u32_u64_view(res@) == method_spec(cols)," in src


def test_nested_map_unsupported() -> None:
    with pytest.raises(ValueError, match=r"^unsupported MethodSpec return type:"):
        structural_bridge_for_spec_type("Map<u32, Map<u32, u64>>")


def test_spec_to_exec_type_rejects_unknown_atom() -> None:
    with pytest.raises(ValueError, match="unsupported Verus type"):
        parse_verus_type("bool")


def test_resolve_ret_type_registers_seq_projection() -> None:
    spec = _spec("Seq<(Seq<char>, Seq<char>, u64)>").replace("Map::empty()", "Seq::empty()")
    key = resolve_ret_type_from_method_spec(spec)
    assert key == "seq_str_str_u64"
    assert get_bridge(key) is not None


@pytest.mark.parametrize("qnum", ["1", "2", "3", "4", "6", "24"])
def test_sec_holdout_resolve_ret_type(qnum: str) -> None:
    queries = dict(_load_sec_queries())
    sql = queries[qnum]
    tables: dict[str, dict[str, str]] = {}
    if qnum == "1":
        tables = {"pre": SEC_SCHEMA["pre"]}
    elif qnum == "2":
        tables = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    elif qnum == "3":
        tables = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    elif qnum == "4":
        tables = {t: SEC_SCHEMA[t] for t in ("num", "sub", "tag", "pre")}
    elif qnum == "6":
        tables = {t: SEC_SCHEMA[t] for t in ("num", "sub", "pre")}
    elif qnum == "24":
        tables = {"num": SEC_SCHEMA["num"], "pre": SEC_SCHEMA["pre"]}
    raw = transpile_sql_to_verus(sql, tables)
    key = resolve_ret_type_from_method_spec(raw)
    assert key
    if qnum == "3":
        assert key == "map_str_u32_u64"
    else:
        assert get_bridge(key) is not None or key in {
            "u64",
            "map_str_u32_u64",
            "map_u32_str_u64",
        }
