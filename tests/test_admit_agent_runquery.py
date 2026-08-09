"""Adversarial admission tests for AGENT_EDIT run_query contract enforcement."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_loop.admit_agent_runquery import (
    admit_agent_runquery,
    allowed_contract_from_method_spec,
    extract_agent_edit_region,
    normalize_ensures,
    parse_run_query_fn,
)
from research_loop.assemble_runquery import (
    AGENT_EDIT_END,
    AGENT_EDIT_START,
    build_runquery_agent_source,
    build_runquery_agent_source_legacy,
    host_edit_fingerprint,
    write_runquery_agent_file,
)
from verus_transpiler import transpile_sql_to_verus

_SCALAR_SQL = "SELECT SUM(V) FROM t"
_SCALAR_SCHEMA = {"V": "bigint"}
_HAVING_SQL = "SELECT K, S, SUM(V) FROM t GROUP BY K, S HAVING SUM(V) > 10"
_HAVING_SCHEMA = {"K": "int", "S": "string", "V": "bigint"}

_MAP_STR_U32_SPEC = """pub open spec fn method_spec(cols: &Cols) -> Map<(Seq<char>, u32), u64>
    recommends valid_cols(cols),
{
    Map::empty()
}"""

_SIMPLE_JOIN_SQL = """SELECT s.name, SUM(n.value) AS total
FROM num n
JOIN sub s ON n.adsh = s.adsh
WHERE n.uom = 'USD' AND s.fy = 2022
GROUP BY s.name"""


def _scalar_spec() -> str:
    return transpile_sql_to_verus(_SCALAR_SQL, _SCALAR_SCHEMA)


def _map_spec() -> str:
    return transpile_sql_to_verus(_HAVING_SQL, _HAVING_SCHEMA)


def _join_spec() -> str:
    from tests.test_sec_holdout_parse import SEC_SCHEMA

    schema = {"num": SEC_SCHEMA["num"], "sub": SEC_SCHEMA["sub"]}
    return transpile_sql_to_verus(_SIMPLE_JOIN_SQL, schema)


def _admit(source: str, spec_rs: str, *, fp: str | None = None):
    return admit_agent_runquery(source, method_spec_rs=spec_rs, expected_fingerprint=fp)


def _replace_edit_region(source: str, new_fn: str) -> str:
    start = source.index(AGENT_EDIT_START) + len(AGENT_EDIT_START)
    end = source.index(AGENT_EDIT_END)
    return source[:start] + "\n" + new_fn + "\n" + source[end:]


def test_allowed_contract_scalar() -> None:
    spec = _scalar_spec()
    contract = allowed_contract_from_method_spec(spec)
    assert contract.rust_ret == "u64"
    assert normalize_ensures(contract.ensures_line) == normalize_ensures(
        "res == method_spec(cols),"
    )
    assert contract.view_name is None


def test_allowed_contract_map() -> None:
    contract = allowed_contract_from_method_spec(_MAP_STR_U32_SPEC)
    assert "HashMap" in contract.rust_ret
    assert "hashmap_str_u32_u64_view" in contract.ensures_line


def test_accepts_default_u64_template() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64")
    result = _admit(src, spec)
    assert result.ok, result.violations
    assert result.run_query_fn is not None
    assert "0u64" in result.run_query_fn


def test_accepts_trivial_u64_body() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64", body_inner="42u64")
    result = _admit(src, spec)
    assert result.ok, result.violations
    assert "42u64" in (result.run_query_fn or "")


def test_accepts_map_hashmap_stub() -> None:
    spec = _map_spec()
    src = build_runquery_agent_source(ret_type="map_u32_str_u64")
    result = _admit(src, spec)
    assert result.ok, result.violations
    assert "HashMap::new()" in (result.run_query_fn or "")


def test_accepts_proof_block() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(
        ret_type="u64",
        body_inner="proof { assert(true); }\n    0u64",
    )
    result = _admit(src, spec)
    assert result.ok, result.violations


@pytest.mark.parametrize(
    "bad_ensures",
    [
        "ensures true,",
        "ensures res == 0,",
        "ensures hashmap_str_u32_u64_view(res@) == method_spec(cols),",  # wrong view for u64
    ],
)
def test_rejects_bad_ensures(bad_ensures: str) -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64")
    fn = (
        "pub exec fn run_query(cols: &Cols) -> (res: u64)\n"
        "    requires valid_cols(cols),\n"
        f"    {bad_ensures}\n"
        "{\n    0u64\n}"
    )
    result = _admit(_replace_edit_region(src, fn), spec)
    assert not result.ok
    assert any("ensures" in v.lower() for v in result.violations)


def test_rejects_wrong_return_type() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64")
    fn = (
        "pub exec fn run_query(cols: &Cols) -> (res: u32)\n"
        "    requires valid_cols(cols),\n"
        "    ensures res == method_spec(cols),\n"
        "{\n    0u32\n}"
    )
    result = _admit(_replace_edit_region(src, fn), spec)
    assert not result.ok
    assert any("return type" in v for v in result.violations)


@pytest.mark.parametrize("assume_body", ["assume false;", "assume true;", "assume(false);"])
def test_rejects_assume(assume_body: str) -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64", body_inner=f"{assume_body}\n    0u64")
    result = _admit(src, spec)
    assert not result.ok
    assert any("assume" in v for v in result.violations)


def test_rejects_ensures_or_true_weakening() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64")
    fn = (
        "pub exec fn run_query(cols: &Cols) -> (res: u64)\n"
        "    requires valid_cols(cols),\n"
        "    ensures res == method_spec(cols) || true,\n"
        "{\n    0u64\n}"
    )
    result = _admit(_replace_edit_region(src, fn), spec)
    assert not result.ok


def test_rejects_ensures_smuggled_in_comment() -> None:
    """Real ensures must match; commenting out the real postcondition fails."""
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64")
    fn = (
        "pub exec fn run_query(cols: &Cols) -> (res: u64)\n"
        "    requires valid_cols(cols),\n"
        "    // ensures res == method_spec(cols),\n"
        "    ensures true,\n"
        "{\n    0u64\n}"
    )
    result = _admit(_replace_edit_region(src, fn), spec)
    assert not result.ok


def test_rejects_unimplemented() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64", body_inner="unimplemented!()")
    result = _admit(src, spec)
    assert not result.ok


def test_rejects_external_body_on_run_query() -> None:
    spec = _scalar_spec()
    fn = (
        "#[verifier::external_body]\n"
        "pub exec fn run_query(cols: &Cols) -> (res: u64)\n"
        "    requires valid_cols(cols),\n"
        "    ensures res == method_spec(cols),\n"
        "{\n    0u64\n}"
    )
    src = _replace_edit_region(build_runquery_agent_source(ret_type="u64"), fn)
    result = _admit(src, spec)
    assert not result.ok
    assert any("external_body" in v for v in result.violations)


def test_rejects_external_body_helper_in_edit() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(
        ret_type="u64",
        body_inner="#[verifier::external_body]\n    fn evil() {}\n    0u64",
    )
    result = _admit(src, spec)
    assert not result.ok


def test_rejects_arbitrary() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64", body_inner="let x = arbitrary(); 0u64")
    result = _admit(src, spec)
    assert not result.ok


def test_rejects_method_spec_redefinition() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(
        ret_type="u64",
        body_inner="pub open spec fn method_spec(cols: &Cols) -> u64 { 0 }\n    0u64",
    )
    result = _admit(src, spec)
    assert not result.ok


def test_rejects_fingerprint_tamper(tmp_path: Path) -> None:
    spec = _scalar_spec()
    dest = tmp_path / "runquery_agent.rs"
    write_runquery_agent_file(dest, ret_type="u64", body_inner="1u64")
    fp = host_edit_fingerprint(dest.read_text(encoding="utf-8"))
    tampered = dest.read_text(encoding="utf-8").replace("MethodSpec + Trusted", "TAMPERED")
    result = _admit(tampered, spec, fp=fp)
    assert not result.ok
    assert any("tampered" in v for v in result.violations)


def test_rejects_empty_body() -> None:
    spec = _scalar_spec()
    fn = (
        "pub exec fn run_query(cols: &Cols) -> (res: u64)\n"
        "    requires valid_cols(cols),\n"
        "    ensures res == method_spec(cols),\n"
        "{\n    // only comment\n}"
    )
    src = _replace_edit_region(build_runquery_agent_source(ret_type="u64"), fn)
    result = _admit(src, spec)
    assert not result.ok
    assert any("empty" in v or "comments only" in v for v in result.violations)


def test_rejects_missing_valid_cols_requires() -> None:
    spec = _scalar_spec()
    fn = (
        "pub exec fn run_query(cols: &Cols) -> (res: u64)\n"
        "    requires true,\n"
        "    ensures res == method_spec(cols),\n"
        "{\n    0u64\n}"
    )
    src = _replace_edit_region(build_runquery_agent_source(ret_type="u64"), fn)
    result = _admit(src, spec)
    assert not result.ok
    assert any("valid_cols" in v for v in result.violations)


def test_parse_run_query_fn_rejects_zero_or_many() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        parse_run_query_fn("fn other() {}")
    two = "pub exec fn run_query() {}\npub exec fn run_query() {}"
    with pytest.raises(ValueError, match="exactly one"):
        parse_run_query_fn(two)


def test_extract_agent_edit_region() -> None:
    src = build_runquery_agent_source(ret_type="u64")
    region = extract_agent_edit_region(src)
    assert "pub exec fn run_query" in region
    assert AGENT_EDIT_START not in region


def test_legacy_body_markers_not_admitted_by_edit_path() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source_legacy(ret_type="u64", body_inner="0u64")
    with pytest.raises(ValueError, match="missing AGENT_EDIT"):
        extract_agent_edit_region(src)
    result = _admit(src, spec)
    assert not result.ok


def test_map_wrong_view_ensures_rejected() -> None:
    spec = _map_spec()
    src = build_runquery_agent_source(ret_type="map_u32_str_u64")
    fn = re.sub(
        r"hashmap_u32_str_u64_view",
        "hashmap_str_u32_u64_view",
        extract_agent_edit_region(src),
    )
    result = _admit(_replace_edit_region(src, fn), spec)
    assert not result.ok


def test_rejects_map_direct_ensures_with_hashmap() -> None:
    spec = _map_spec()
    fn = (
        "pub exec fn run_query(cols: &Cols) -> "
        "(res: HashMap<(u32, String), u64>)\n"
        "    requires valid_cols(cols),\n"
        "    ensures res == method_spec(cols),\n"
        "{\n    HashMap::new()\n}"
    )
    src = _replace_edit_region(build_runquery_agent_source(ret_type="map_u32_str_u64"), fn)
    result = _admit(src, spec)
    assert not result.ok
    assert any("direct ensures" in v or "forbidden" in v for v in result.violations)


def test_rejects_ghost_map_return_type() -> None:
    spec = _map_spec()
    fn = (
        "pub exec fn run_query(cols: &Cols) -> "
        "(res: Map<(Seq<char>, u32), u64>)\n"
        "    requires valid_cols(cols),\n"
        "    ensures hashmap_u32_str_u64_view(res@) == method_spec(cols),\n"
        "{\n    HashMap::new()\n}"
    )
    src = _replace_edit_region(build_runquery_agent_source(ret_type="map_u32_str_u64"), fn)
    result = _admit(src, spec)
    assert not result.ok
    assert any("ghost Map" in v for v in result.violations)


def test_scalar_u64_direct_ensures_accepted() -> None:
    spec = _scalar_spec()
    src = build_runquery_agent_source(ret_type="u64", body_inner="99u64")
    result = _admit(src, spec)
    assert result.ok, result.violations
    assert result.rust_ret == "u64"


def test_map_view_ensures_sets_rust_ret() -> None:
    spec = _map_spec()
    src = build_runquery_agent_source(ret_type="map_u32_str_u64")
    result = _admit(src, spec)
    assert result.ok, result.violations
    assert result.rust_ret is not None
    assert "HashMap" in result.rust_ret


def test_rejects_fake_view_name() -> None:
    spec = _map_spec()
    fn = (
        "pub exec fn run_query(cols: &Cols) -> "
        "(res: HashMap<(u32, String), u64>)\n"
        "    requires valid_cols(cols),\n"
        "    ensures fake_view_xyz(res@) == method_spec(cols),\n"
        "{\n    HashMap::new()\n}"
    )
    src = _replace_edit_region(build_runquery_agent_source(ret_type="map_u32_str_u64"), fn)
    result = _admit(src, spec)
    assert not result.ok
    assert any("fake_view_xyz" in v or "untrusted view" in v for v in result.violations)


def test_accepts_multi_table_join_contract() -> None:
    from research_loop.method_spec_ret_type import resolve_ret_type_from_method_spec

    spec = _join_spec()
    ret_type = resolve_ret_type_from_method_spec(spec)
    src = build_runquery_agent_source(
        ret_type=ret_type,
        method_spec_rs=spec,
    )
    result = _admit(src, spec)
    assert result.ok, result.violations
    fn = result.run_query_fn or ""
    assert "valid_cols_num(num)" in fn
    assert "valid_cols_sub(sub)" in fn
    assert "method_spec(num, sub)" in fn


def test_rejects_multi_table_bare_cols_requires() -> None:
    spec = _join_spec()
    fn = (
        "pub exec fn run_query(num: &Cols_num, sub: &Cols_sub) -> (res: u64)\n"
        "    requires valid_cols(cols),\n"
        "    ensures res == method_spec(num, sub),\n"
        "{\n    0u64\n}"
    )
    src = _replace_edit_region(
        build_runquery_agent_source(ret_type="u64", method_spec_rs=spec),
        fn,
    )
    result = _admit(src, spec)
    assert not result.ok
    assert any("valid_cols" in v for v in result.violations)


def test_rejects_multi_table_method_spec_cols_ensures() -> None:
    spec = _join_spec()
    fn = (
        "pub exec fn run_query(num: &Cols_num, sub: &Cols_sub) -> (res: u64)\n"
        "    requires valid_cols_num(num), valid_cols_sub(sub),\n"
        "    ensures res == method_spec(cols),\n"
        "{\n    0u64\n}"
    )
    src = _replace_edit_region(
        build_runquery_agent_source(ret_type="u64", method_spec_rs=spec),
        fn,
    )
    result = _admit(src, spec)
    assert not result.ok
    assert any("ensures" in v.lower() for v in result.violations)


def test_rejects_multi_table_wrong_signature_params() -> None:
    spec = _join_spec()
    fn = (
        "pub exec fn run_query(cols: &Cols) -> (res: u64)\n"
        "    requires valid_cols(cols),\n"
        "    ensures res == method_spec(cols),\n"
        "{\n    0u64\n}"
    )
    src = _replace_edit_region(
        build_runquery_agent_source(ret_type="u64", method_spec_rs=spec),
        fn,
    )
    result = _admit(src, spec)
    assert not result.ok
    assert any("parameter" in v or "valid_cols" in v for v in result.violations)
