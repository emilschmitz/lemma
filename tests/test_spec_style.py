"""LEMMA_SPEC_STYLE routing and declarative prompt/index."""

from __future__ import annotations

from pathlib import Path

import pytest

from db_extension.optimizer import _read_lemma_spec_style, run_optimization_loop
from declarative_spec.lemma_index import lemma_index_markdown
from declarative_spec.prompt import build_declarative_prompt
from research_loop.table_assumptions import CatalogAssumptions
from verus_transpiler import transpile_sql_to_verus


@pytest.mark.parametrize(
    "env_value,expected",
    [
        (None, "recursive"),
        ("", "recursive"),
        ("recursive", "recursive"),
        ("RECURSIVE", "recursive"),
        ("declarative", "declarative"),
    ],
)
def test_read_lemma_spec_style_recursive_and_declarative(
    env_value: str | None,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if env_value is None:
        monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)
    else:
        monkeypatch.setenv("LEMMA_SPEC_STYLE", env_value)
    assert _read_lemma_spec_style() == expected


def test_read_lemma_spec_style_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMMA_SPEC_STYLE", "other")
    with pytest.raises(ValueError, match="recursive or declarative"):
        _read_lemma_spec_style()


def test_recursive_path_uses_transpiler_not_emit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LEMMA_SPEC_STYLE", raising=False)
    called: list[bool] = []

    def _boom(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("emit_declarative_spec must not run on recursive path")

    monkeypatch.setattr("declarative_spec.emit.emit_declarative_spec", _boom)
    sql = "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k"
    schema = {"t": {"k": "bigint"}}
    catalog = CatalogAssumptions(max_rows=1000)
    out = transpile_sql_to_verus(sql, schema, catalog_assumptions=catalog)
    assert "method_spec" in out
    assert not called


def test_optimizer_declarative_branch_calls_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict] = []

    def _fake_drive(**kwargs):
        recorded.append(kwargs)
        return {"status": "FAILED", "error": "stopped", "history": []}

    def _no_transpile(*_args, **_kwargs):
        raise AssertionError("transpile_sql_to_verus must not run when declarative")

    monkeypatch.setattr(
        "declarative_spec.drive.run_declarative_optimization_loop",
        _fake_drive,
    )
    monkeypatch.setattr("db_extension.optimizer.transpile_sql_to_verus", _no_transpile)
    monkeypatch.setenv("LEMMA_SPEC_STYLE", "declarative")

    sql = "SELECT k, COUNT(*) AS cnt FROM t GROUP BY k"
    result = run_optimization_loop(
        sql,
        schema={"t": {"k": "bigint"}},
        use_mock=True,
        max_iterations=1,
    )
    assert recorded, "declarative drive should run"
    assert recorded[0]["sql_query"] == sql
    assert result["error"] == "stopped"
    assert result["status"] == "FAILED"


def test_lemma_index_markdown_content() -> None:
    md = lemma_index_markdown()
    assert "lemma_u64_add_fits" in md
    assert "lemma_f64_sum_within_eps" in md
    assert "axiom_u64_obeys_hash_table_key_model" in md
    assert "may **not** declare `spec fn`" in md


def test_build_declarative_prompt_contract() -> None:
    index = lemma_index_markdown()
    prompt = build_declarative_prompt(
        sql="SELECT k FROM t",
        spec_path="context/ro/spec.rs",
        edit_path="runquery_agent.rs",
        lemma_index=index,
    )
    assert index.strip() in prompt
    assert "FLOAT_ABS_EPS" in prompt
    assert "inserts into a map" not in prompt.lower()
    assert "recursive product path" in prompt.lower() or "other spec style" in prompt.lower()


_FORBIDDEN_IN_NEW_FILES = (
    "edgar",
    "tpch",
    "duckdb",
    "sec_margin",
    "verus_transpiler",
    "assemble_verified_program",
)


def test_new_declarative_modules_forbidden_strings() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "declarative_spec" / "lemma_index.py",
        root / "declarative_spec" / "prompt.py",
        root / "declarative_spec" / "drive.py",
    ]
    for path in paths:
        text = path.read_text().lower()
        for token in _FORBIDDEN_IN_NEW_FILES:
            assert token not in text, f"{token!r} found in {path.name}"
