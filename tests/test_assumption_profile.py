"""Profiler (research_loop.assumption_packages.profile) and the JSON package loader."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from research_loop.assumption_packages import assumption_package
from research_loop.assumption_packages.check import violations
from research_loop.assumption_packages.json_io import catalog_from_dict, catalog_to_dict
from research_loop.assumption_packages.profile import (
    parse_join,
    pow2_above,
    pow2_at_least,
    profile,
    render_report,
)
from research_loop.assumption_packages.sec_margin import sec_margin_dec_catalog


def _db() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE cust (id INTEGER PRIMARY KEY, name VARCHAR, score BIGINT, note VARCHAR)")
    con.execute("INSERT INTO cust VALUES (1,'ann',10,NULL),(2,'bob',-300,'x'),(3,'cy',7,NULL)")
    con.execute("CREATE TABLE ord (oid INTEGER, cust_id INTEGER, amt DECIMAL(18,2), px DOUBLE)")
    con.execute("INSERT INTO ord VALUES (1,1,12.50,-4.5),(2,1,0.25,9.9),(3,2,100.00,2.0),(4,3,7.75,1.0)")
    return con


def test_pow2_helpers() -> None:
    assert [pow2_at_least(n) for n in (0, 1, 2, 3, 8, 9)] == [1, 1, 2, 4, 8, 16]
    assert [pow2_above(n) for n in (0, 1, 7, 8, 9)] == [1, 2, 8, 16, 16]  # strictly greater: 8 -> 16


def test_parse_join() -> None:
    assert parse_join("a.x=b.y") == ("a", "b", (("x", "y"),))
    assert parse_join("a.x=b.y, a.z=b.w") == ("a", "b", (("x", "y"), ("z", "w")))
    with pytest.raises(ValueError):
        parse_join("a.x=b.y,a.z=c.w")


def test_generated_package_holds_on_its_own_data_and_caps_are_pow2_above_measure() -> None:
    con = _db()
    cat, report, _ = profile(con, margin=4, joins=("cust.id=ord.cust_id",))
    assert violations(cat, con) == []
    cust, ord_ = cat.tables["cust"], cat.tables["ord"]
    assert cust.max_rows == 16 and ord_.max_rows == 16  # 3 and 4 rows, x4, next power of two
    assert cust.columns["score"].max_value_exclusive == 512  # |-300| = 300 -> 512
    assert cust.columns["name"].max_string_len == 4 and cust.columns["name"].max_distinct == 16
    assert ord_.columns["amt"].scale == 2 and ord_.columns["amt"].max_value_exclusive == 16384  # stored 10000
    assert ord_.columns["px"].max_value_exclusive == 16  # trunc(9.9) = 9; negatives load as 0
    assert cat.join_caps[0].max_tuples == 16  # 4 joined tuples x 4
    assert any("join cust x ord" in r["bound"] for r in report)


def test_value_margin_widens_value_caps_only() -> None:
    cat, _, _ = profile(_db(), margin=1, value_margin=4)
    assert cat.tables["cust"].columns["score"].max_value_exclusive == 2048  # 300 x 4 = 1200
    assert cat.tables["cust"].max_rows == 4  # rows x1 -> next power of two of 3


def test_nullable_is_measured_and_unique_keys_are_proposals_only() -> None:
    cat, _, proposals = profile(_db())
    assert cat.tables["cust"].columns["note"].nullable is True
    assert cat.tables["cust"].columns["name"].nullable is False
    assert cat.tables["cust"].unique_keys == ()  # not claimed until the user moves it in
    assert ["id"] in proposals["cust"] and ["name"] in proposals["cust"]  # declared PK; all-distinct string
    assert "cust_id" not in {k for ks in proposals.get("ord", []) for k in ks}  # repeats: not unique


def test_data_past_a_cap_is_reported_by_check() -> None:
    con = _db()
    cat, _, _ = profile(con)
    con.execute("INSERT INTO cust VALUES (4,'dee',100000,NULL)")
    assert any("cust.score" in v for v in violations(cat, con))


def test_report_has_one_row_per_bound_and_no_stray_pipes() -> None:
    _, report, _ = profile(_db())
    md = render_report("p", report)
    assert all(line.count("|") == 6 for line in md.splitlines() if line.startswith("|"))


def test_json_round_trip_is_identity() -> None:
    cat = sec_margin_dec_catalog()
    assert catalog_from_dict(json.loads(json.dumps(catalog_to_dict(cat)))) == cat
    gen, _, _ = profile(_db(), joins=("cust.id=ord.cust_id",))
    assert catalog_from_dict(json.loads(json.dumps(catalog_to_dict(gen)))) == gen


def test_unknown_json_field_fails_loudly() -> None:
    with pytest.raises(TypeError):
        catalog_from_dict({"tables": {"t": {"columns": {"c": {"max_value": 5}}}}})
    with pytest.raises(TypeError):
        catalog_from_dict({"tables": {"t": {"max_row": 5}}})


def test_assumption_package_accepts_json_path_and_registered_name(tmp_path: Path, monkeypatch) -> None:
    cat, _, _ = profile(_db())
    f = tmp_path / "mine.json"
    f.write_text(json.dumps({"name": "mine", **catalog_to_dict(cat), "proposals": {}}))
    assert assumption_package(str(f)) == cat
    import research_loop.assumption_packages as pk

    reg = tmp_path / "reg"
    reg.mkdir()
    (reg / "named.json").write_text(f.read_text())
    monkeypatch.setattr(pk, "REGISTRY_DIR", reg)
    assert assumption_package("named") == cat
    with pytest.raises(ValueError, match="unknown"):
        assumption_package("nope")
    with pytest.raises(FileNotFoundError):
        assumption_package(str(tmp_path / "missing.json"))
