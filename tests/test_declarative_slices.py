"""The sliced hot-loop worked examples verify against the emitted spec, and a wrong hit condition does not."""

from __future__ import annotations

from pathlib import Path

import pytest

from declarative_spec.assemble import assemble_declarative_program
from declarative_spec.emit import emit_declarative_spec
from declarative_spec.pipeline import VERUS_CANDIDATES, verify_assembled
from declarative_spec.prompt import _FIXTURES
from declarative_spec.regions import extract_agent_edit, extract_agent_helpers
from research_loop.assumption_packages import assumption_package
from research_loop.table_assumptions import CatalogAssumptions, ColumnAssumption, TableAssumptions

COUNT_MAX_SQL = "SELECT COUNT(*) AS c, MAX(ddate) AS d FROM num WHERE uom = 'shares' AND qtrs = 4"
Q6_SQL = (
    "SELECT sum(l_extendedprice * l_discount) AS revenue FROM lineitem WHERE l_shipdate >= date '1994-01-01' "
    "AND l_shipdate < date '1994-01-01' + interval '1' year AND l_discount BETWEEN 0.09 - 0.01 AND 0.09 + 0.01 AND l_quantity < 25"
)
Q6_SCHEMA = {
    "lineitem": {
        "l_quantity": "decimal(15,2)",
        "l_extendedprice": "decimal(15,2)",
        "l_discount": "decimal(15,2)",
        "l_shipdate": "date",
    }
}
# The caps the profiler proposes for TPC-H SF10 lineitem (stored scaled integers): quantity < 8192, price < 2^24, discount < 16.
Q6_CATALOG = CatalogAssumptions(
    max_rows=2**28,
    tables={
        "lineitem": TableAssumptions(
            max_rows=2**28,
            columns={
                "l_quantity": ColumnAssumption(max_value_exclusive=8192, scale=2),
                "l_extendedprice": ColumnAssumption(max_value_exclusive=2**24, scale=2),
                "l_discount": ColumnAssumption(max_value_exclusive=16, scale=2),
            },
        )
    },
)


def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    if not any(c.is_file() for c in VERUS_CANDIDATES):
        pytest.skip("verus binary not installed")
    monkeypatch.setenv("LEMMA_VERUS_BIN", str(Path(__file__).resolve().parents[1] / "scripts" / "ram" / "verus_guarded.sh"))
    monkeypatch.setenv("LEMMA_STRING_ENCODING", "dict")
    monkeypatch.setenv("LEMMA_PARALLEL_VSTD", "1")
    monkeypatch.setenv("LEMMA_NARROW_CELLS", "1")


def _run(spec: str, text: str) -> tuple[bool, str]:
    return verify_assembled(assemble_declarative_program(spec, extract_agent_edit(text), helpers=extract_agent_helpers(text)), timeout_sec=600)


@pytest.mark.parametrize(
    ("name", "sql", "schema", "catalog"),
    [
        (
            "parallel_dict_filter_count_max_slices.rs",
            COUNT_MAX_SQL,
            {"num": {"uom": "varchar", "qtrs": "int", "ddate": "int"}},
            assumption_package("sec_margin_dec"),
        ),
        ("parallel_ungrouped_product_sum_slices.rs", Q6_SQL, Q6_SCHEMA, Q6_CATALOG),
    ],
)
def test_sliced_example_verifies_and_a_wrong_hit_condition_does_not(monkeypatch: pytest.MonkeyPatch, name: str, sql: str, schema: dict, catalog: CatalogAssumptions) -> None:
    _setup(monkeypatch)
    spec = emit_declarative_spec(sql, schema, catalog)
    text = (_FIXTURES / name).read_text()
    assert "slice_subrange" in text
    ok, out = _run(spec, text)
    assert ok and "0 errors" in out, out[-2000:]
    assert "let hit: bool = hu == 1;" in text
    bad, _ = _run(spec, text.replace("let hit: bool = hu == 1;", "let hit: bool = hu == 0;", 1))
    assert not bad
