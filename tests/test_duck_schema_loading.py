from pathlib import Path

import duckdb

from research_loop.scripts.sqlsmith_trusted_coverage import load_sec_schema


def _db(path: Path, ddl: list[str]) -> Path:
    con = duckdb.connect(str(path))
    for stmt in ddl:
        con.execute(stmt)
    con.close()
    return path


def test_non_sec_file_schema_comes_from_the_file(tmp_path):
    db = _db(tmp_path / "a.duckdb", [
        "CREATE TABLE widgets (id BIGINT, price DECIMAL(15,2), made DATE, label VARCHAR)",
        "CREATE TABLE owners (oid INTEGER, score DOUBLE)",
    ])
    assert load_sec_schema(db) == {
        "widgets": {"id": "bigint", "price": "decimal(15,2)", "made": "date", "label": "varchar"},
        "owners": {"oid": "integer", "score": "double"},
    }


def test_non_sec_file_with_one_sec_table_name_is_not_sec(tmp_path):
    db = _db(tmp_path / "b.duckdb", ["CREATE TABLE num (x INTEGER)", "CREATE TABLE other (y VARCHAR)"])
    assert load_sec_schema(db) == {"num": {"x": "integer"}, "other": {"y": "varchar"}}


def test_sec_file_keeps_sec_schema_with_decimal_overlay(tmp_path):
    base = load_sec_schema()
    db = _db(tmp_path / "c.duckdb", [
        f"CREATE TABLE {t} ({', '.join(f'{c} INTEGER' for c in cols)})" for t, cols in base.items()
    ])
    assert load_sec_schema(db) == base
