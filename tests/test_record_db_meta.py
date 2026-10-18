import hashlib

import duckdb

from research_loop.scripts import record_db_meta


def _make(path):
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE a (x INTEGER, y DECIMAL(38,4)); INSERT INTO a VALUES (1, 1.5), (2, 2.5)")
    con.execute("CREATE TABLE b (s VARCHAR)")
    con.close()


def test_meta_rows_columns_sha(tmp_path):
    db = tmp_path / "t.duckdb"
    _make(db)
    meta = record_db_meta.describe(db)
    assert meta["rows"] == {"a": 2, "b": 0}
    assert meta["columns"]["a"] == {"x": "INTEGER", "y": "DECIMAL(38,4)"}
    assert meta["sha256"] == hashlib.sha256(db.read_bytes()).hexdigest()
    assert meta["bytes"] == db.stat().st_size


def test_meta_does_not_modify_file(tmp_path):
    db = tmp_path / "t.duckdb"
    _make(db)
    before = db.read_bytes()
    record_db_meta.describe(db)
    assert db.read_bytes() == before
