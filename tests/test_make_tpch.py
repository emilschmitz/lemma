import duckdb
import pytest

from research_loop.scripts import make_tpch


def test_tpch_tiny_tables_and_rows(tmp_path):
    path = make_tpch.build(0.01, tmp_path)
    assert path.name == "tpch_sf0.01.duckdb"
    meta = make_tpch.describe(path, 0.01)
    assert tuple(sorted(meta["rows"])) == make_tpch.TABLES
    assert meta["rows"] == {
        "customer": 1500, "lineitem": 60175, "nation": 25, "orders": 15000,
        "part": 2000, "partsupp": 8000, "region": 5, "supplier": 100,
    }
    con = duckdb.connect(str(path), read_only=True)
    assert con.execute("describe lineitem").fetchall()[4][:2] == ("l_quantity", "DECIMAL(15,2)")


def test_tpch_deterministic_content_and_no_overwrite(tmp_path):
    a = make_tpch.build(0.01, tmp_path / "a")
    b = make_tpch.build(0.01, tmp_path / "b")
    q = "select sum(hash(l_orderkey, l_partkey, l_extendedprice, l_comment)) from lineitem"
    ra, rb = (duckdb.connect(str(p), read_only=True).execute(q).fetchone() for p in (a, b))
    assert ra == rb
    with pytest.raises(FileExistsError):
        make_tpch.build(0.01, tmp_path / "a")
