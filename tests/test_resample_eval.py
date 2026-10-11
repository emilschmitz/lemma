"""resample_eval: the same seed gives the same pool and pick; the burned list and near-duplicates are skipped; a replay
of the recorded decisions gives the same files."""

from __future__ import annotations

import json

import duckdb
import pytest

from research_loop.scripts.resample_eval import normal, pick_from, pick_seed, resample
from research_loop.table_assumptions import CatalogAssumptions, TableAssumptions


@pytest.fixture
def small_db(tmp_path):
    path = tmp_path / "small.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE f (k INTEGER, g VARCHAR, a INTEGER, d DECIMAL(10,2))")
    con.execute("CREATE TABLE dim (k INTEGER, nm VARCHAR, w INTEGER)")
    con.execute("INSERT INTO f SELECT i % 20, 'g' || (i % 4), i % 7, i * 1.25 FROM range(400) t(i)")
    con.execute("INSERT INTO dim SELECT i, 'n' || (i % 3), i % 5 FROM range(20) t(i)")
    con.close()
    return path


CATALOG = CatalogAssumptions(max_rows=1000, tables={"f": TableAssumptions(max_rows=1000), "dim": TableAssumptions(max_rows=1000)})


def run(db, out, seed=5, level="med", **kw):
    return resample(db, "none", seed, level, 30, 5, out, min_fact_rows=1, min_ms=0.0, catalog=CATALOG, **kw)


def test_the_same_seed_gives_byte_identical_files(small_db, tmp_path) -> None:
    a = run(small_db, tmp_path / "a")
    b = run(small_db, tmp_path / "b")
    assert (tmp_path / "a" / "pool.sql").read_bytes() == (tmp_path / "b" / "pool.sql").read_bytes()
    for q in sorted((tmp_path / "a" / "pick").iterdir()):
        assert q.read_bytes() == (tmp_path / "b" / "pick" / q.name).read_bytes()
    for m in (a, b):
        m.pop("argv"), m.pop("git_dirty")
    assert a == b
    assert a["pick_seed"] == pick_seed(5) and len(a["pick_pool_indices"]) == 5
    assert json.loads((tmp_path / "a" / "manifest.json").read_text())["db"]["table_rows"] == {"dim": 20, "f": 400}


def test_another_seed_gives_another_pool_and_the_level_is_exact(small_db, tmp_path) -> None:
    from declarative_spec.fragment import fragment_level

    run(small_db, tmp_path / "a", seed=5)
    run(small_db, tmp_path / "c", seed=6)
    assert (tmp_path / "a" / "pool.sql").read_text() != (tmp_path / "c" / "pool.sql").read_text()
    for q in (tmp_path / "a" / "pick").iterdir():
        assert fragment_level(q.read_text())[0] == "med"


def test_burned_queries_are_never_picked_and_replacements_are_deterministic(small_db, tmp_path) -> None:
    first = run(small_db, tmp_path / "a")
    pool = [q for q in (tmp_path / "a" / "pool.sql").read_text().split("\n\n") if q.strip()]
    pool = [q.split(":\n", 1)[1] for q in pool]
    burned = [pool[i] for i in first["pick_pool_indices"][:2]]
    (tmp_path / "burned.json").write_text(json.dumps(burned))
    second = run(small_db, tmp_path / "b", burned=tmp_path / "burned.json")
    third = run(small_db, tmp_path / "c", burned=tmp_path / "burned.json")
    picked = [(tmp_path / "b" / "pick" / f).read_text() for f in sorted(p.name for p in (tmp_path / "b" / "pick").iterdir())]
    assert not {normal(b) for b in burned} & {normal(p) for p in picked}
    assert second["pick_pool_indices"] == third["pick_pool_indices"]
    assert len(second["pick_pool_indices"]) == 5


def test_pick_skips_near_duplicates() -> None:
    pool = [
        "SELECT g, SUM(a) AS s FROM f WHERE a > 1 GROUP BY g;",
        "SELECT g, SUM(a) AS s FROM f WHERE a > 5 GROUP BY g;",  # same tables, columns and aggregates: a near-duplicate
        "SELECT g, MAX(a) AS s FROM f WHERE a > 1 GROUP BY g;",
    ]
    assert sorted(pick_from(pool, 1, 3, set())) in ([0, 2], [1, 2])  # one of the first two, never both


def test_replay_of_the_recorded_decisions_gives_the_same_files(small_db, tmp_path) -> None:
    a = run(small_db, tmp_path / "a")
    b = run(small_db, tmp_path / "b", replay={"decisions": a["decisions"], "ms": a["ms"]})
    assert (tmp_path / "a" / "pool.sql").read_bytes() == (tmp_path / "b" / "pool.sql").read_bytes()
    assert a["pick_pool_indices"] == b["pick_pool_indices"]
