"""Agent-visible spec.rs: MethodSpec + TRUSTED agg API, no RunQuery skeleton."""

from __future__ import annotations

from pathlib import Path

from db_extension.agent.config import AgentFlags
from db_extension.agent.harness import _prepare_workspace
from db_extension.verus_bridge import resolve_ret_type_for_spec
from research_loop.agent_sandbox import prepare_workspace
from research_loop.assemble_verified_program import (
    RUNQUERY_SKELETON_MARKER,
    prepare_agent_visible_spec,
)
from verus_transpiler import transpile_sql_to_verus

_HAVING_SCHEMA = {"K": "int", "S": "string", "V": "bigint"}
_HAVING_SQL = "SELECT K, S, SUM(V) FROM t GROUP BY K, S HAVING SUM(V) > 10"
_SCALAR_SQL = "SELECT SUM(V) FROM t"
_SCALAR_SCHEMA = {"V": "bigint"}


def test_prepare_agent_visible_spec_map_includes_agg_helpers() -> None:
    raw = transpile_sql_to_verus(_HAVING_SQL, _HAVING_SCHEMA)
    ret_type = resolve_ret_type_for_spec(raw)
    assert ret_type == "map_u32_str_u64"

    out = prepare_agent_visible_spec(raw, ret_type)

    assert RUNQUERY_SKELETON_MARKER not in out
    assert "pub exec fn run_query" not in out
    assert "agg_new_u32_str__u64" in out
    assert "agg_add_u32_str__u64" in out
    assert "HashMapWithView<(u32, String), u64>" in out
    assert "Map::empty()" in out
    assert out.rstrip().endswith("} // verus!")


def test_prepare_agent_visible_spec_scalar_strips_skeleton_no_agg() -> None:
    raw = transpile_sql_to_verus(_SCALAR_SQL, _SCALAR_SCHEMA)
    ret_type = resolve_ret_type_for_spec(raw)
    assert ret_type == "u64"

    out = prepare_agent_visible_spec(raw, ret_type)

    assert RUNQUERY_SKELETON_MARKER not in out
    assert "pub exec fn run_query" not in out
    assert "agg_new_" not in out
    assert out.rstrip().endswith("} // verus!")


def test_prepare_workspace_writes_prepared_spec(tmp_path: Path) -> None:
    raw = transpile_sql_to_verus(_HAVING_SQL, _HAVING_SCHEMA)
    ws = tmp_path / "ws"
    prepare_workspace(
        ws,
        verus_spec=raw,
        sql_query=_HAVING_SQL,
        schema=_HAVING_SCHEMA,
        reset_body=True,
    )
    spec = (ws / "context" / "ro" / "spec.rs").read_text()
    assert "agg_new_u32_str__u64" in spec
    assert RUNQUERY_SKELETON_MARKER not in spec


def test_harness_prepare_workspace_writes_prepared_spec(tmp_path: Path) -> None:
    raw = transpile_sql_to_verus(_HAVING_SQL, _HAVING_SCHEMA)
    ws = tmp_path / "ws"
    flags = AgentFlags.from_mapping({"AGENT_DATA_MODE": "none"})
    _prepare_workspace(
        ws,
        query_id=1,
        verus_spec=raw,
        sql_query=_HAVING_SQL,
        schema=_HAVING_SCHEMA,
        data_path=None,
        flags=flags,
        reset_body=True,
    )
    spec = (ws / "context" / "ro" / "spec.rs").read_text()
    assert "agg_add_u32_str__u64" in spec
    assert RUNQUERY_SKELETON_MARKER not in spec
